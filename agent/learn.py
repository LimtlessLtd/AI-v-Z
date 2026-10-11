"""Train the network on the experience logs (Phase 4). One run is one training round:

    python -m agent.learn            # from the repo root; the agent also runs this itself every 15 minutes

It reads every decision in logs/experience, learns Q (net.py) by Double-DQN updates over those decisions
(off-policy, so the random policy's experience counts too), and saves logs/model/qnet.pt, which the playing
agent picks up at its next decision. A conservative term (CQL, Kumar et al. 2020) holds down the scores of
options the experience says little about: without it, the max in each update picked options that were
rarely or never tried in that situation, their arbitrary scores fed back, and the scores drifted upwards
(round 2 of 2026-10-11 rated the average option +3 where the logged return averages -19). Each round carries on from the last saved network. Encoded hours are
cached in logs/model/cache (the hour being written is always re-read). Rounds are logged to
logs/model/history.jsonl, which the dashboard's Learning page shows.
"""

import argparse
import copy
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import features as F  # noqa: E402
from agent import net as N  # noqa: E402

GAMMA = 0.97          # per decision: a reward 23 decisions away counts half
BATCH = 256
STEPS = 2000          # updates per round (about a minute on 4 threads); each round starts from the last network
TARGET_EVERY = 200    # steps between copies of the network used for the bootstrapped targets
CQL = 0.5             # weight of the conservative term
LR = 5e-4
THREADS = 4           # CPU threads for training, leaving the rest to the game


def _meta(r):
    return {"choice": r.get("choice"), "reward": r.get("reward") or 0.0, "dead": bool(r.get("dead")),
            "life": r.get("life"), "reason": r.get("reason"), "new_life": bool(r.get("new_life")),
            "resumed": bool(r.get("resumed")), "options": len(r.get("options") or []),
            "verbs": [o.get("verb") for o in r.get("options") or []]}


def encode_file(path, cache_dir, live):
    """Encoded decisions of one experience file, from the cache when the file hasn't changed."""
    st = path.stat()
    key = f"{st.st_size}-{st.st_mtime_ns}-v{F.VERSION}"
    cp = cache_dir / f"{path.name}.npz"
    if not live and cp.exists():
        try:
            z = np.load(cp, allow_pickle=False)
            if str(z["key"]) == key:
                meta = json.loads(str(z["meta"]))
                return meta, N.Pack(z["sd"], z["st"], z["so"]), N.Pack(z["od"], z["ot"], z["oo"])
        except (OSError, ValueError, KeyError):
            pass
    recs = F.read_records(path)
    meta = [_meta(r) for r in recs]
    S = N.Pack.of([F.encode_state(r) for r in recs], F.STATE_DIM)
    O = N.Pack.of([F.encode_option(o) for r in recs for o in (r.get("options") or [])], F.OPTION_DIM)
    if not live:
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = cp.with_name(cp.name + ".tmp.npz")
        np.savez_compressed(tmp, key=np.array(key), meta=np.array(json.dumps(meta)), sd=S.dense, st=S.toks, so=S.offs,
                            od=O.dense, ot=O.toks, oo=O.offs)
        tmp.replace(cp)
    return meta, S, O


def _cat(packs):
    dense = np.concatenate([p.dense for p in packs]) if packs else np.zeros((0, 1), np.float32)
    toks, offs, base = [], [], 0
    for p in packs:
        toks.append(p.toks)
        offs.append(p.offs + base)
        base += len(p.toks)
    return N.Pack(dense, np.concatenate(toks) if toks else np.zeros(0, np.int64),
                  np.concatenate(offs) if offs else np.zeros(0, np.int64))


class Data:
    def __init__(self, log_dir):
        files = sorted((Path(log_dir) / "experience").glob("*.jsonl.gz"))
        cache = Path(log_dir) / "model" / "cache"
        hour = datetime.now().strftime("%Y%m%d-%H")
        metas, ss, os_ = [], [], []
        for f in files:
            m, s, o = encode_file(f, cache, live=f.name.startswith(hour))
            metas += m
            ss.append(s)
            os_.append(o)
        self.meta, self.S, self.O = metas, _cat(ss), _cat(os_)
        n_opts = np.array([m["options"] for m in metas], dtype=np.int64)
        self.start = np.zeros(len(metas) + 1, dtype=np.int64)
        self.start[1:] = np.cumsum(n_opts)
        self.n_opts = n_opts
        self.reward = np.array([m["reward"] for m in metas], dtype=np.float32)
        self.terminal = np.array([m["dead"] or m["options"] == 0 for m in metas])
        self.choice = np.array([m["choice"] if m["choice"] is not None else -1 for m in metas], dtype=np.int64)
        tr = F.transitions(metas)
        self.ti = np.array([i for i, _ in tr], dtype=np.int64)
        self.tj = np.array([j for _, j in tr], dtype=np.int64)
        ok = (self.choice[self.ti] >= 0) & (self.choice[self.ti] < self.n_opts[self.ti])
        self.ti, self.tj = self.ti[ok], self.tj[ok]

    def option_rows(self, recs):
        """All option rows of these records, and which of them (0..len(recs)-1) each row belongs to."""
        counts = self.n_opts[recs]
        rows = N.ranges(self.start[recs], self.start[recs + 1])
        seg = np.repeat(np.arange(len(recs)), counts)
        return rows, torch.from_numpy(seg)


def q_all(net, data, recs):
    rows, seg = data.option_rows(recs)
    hs = net.states(*data.S.rows(recs))
    ha = net.options(*data.O.rows(rows))
    return net.score(hs, seg, ha), seg


def _logsumexp(q, seg, n):
    m = torch.full((n,), -1e9).scatter_reduce(0, seg, q.detach(), "amax")
    return torch.log(torch.zeros(n).index_add(0, seg, torch.exp(q - m[seg]))) + m


def step(net, target, opt, data, rng):
    idx = rng.integers(0, len(data.ti), BATCH)
    I, J = data.ti[idx], data.tj[idx]
    q_s, seg_s = q_all(net, data, I)   # every option of each situation, the chosen one among them
    first = np.zeros(len(I), dtype=np.int64)
    first[1:] = np.cumsum(data.n_opts[I])[:-1]
    q = q_s[torch.from_numpy(first + data.choice[I])]
    with torch.no_grad():
        boot = torch.zeros(len(J))
        live = np.nonzero(~data.terminal[J])[0]
        if len(live):
            Jl = J[live]
            q_on, seg = q_all(net, data, Jl)
            q_tg, _ = q_all(target, data, Jl)
            best = torch.full((len(Jl),), -1e9).scatter_reduce(0, seg, q_on, "amax")
            sel = q_on >= best[seg] - 1e-6   # Double DQN: the online network picks, the target network values
            val = torch.full((len(Jl),), -1e9).scatter_reduce(0, seg[sel], q_tg[sel], "amax")
            boot[torch.from_numpy(live)] = val
        y = torch.from_numpy(data.reward[J]) + GAMMA * boot
    td = torch.nn.functional.smooth_l1_loss(q, y)
    # only pushes down: the logged choice is held up by its own target, so lifting it as well (standard CQL)
    # added a bias that compounded through the discount
    conservative = (_logsumexp(q_s, seg_s, len(I)) - q.detach()).mean()
    loss = td + CQL * conservative
    opt.zero_grad()
    loss.backward()
    torch.nn.utils.clip_grad_norm_(net.parameters(), 5.0)
    opt.step()
    return td.item(), q.mean().item()


def verb_values(net, data, last=3000):
    """How each kind of option scores against the average option in the same situation, over the latest
    decisions. (A plain average of Q would mostly say where an option is offered: eating is offered when
    hungry, and hungry situations score low whatever is picked.)"""
    recs = np.arange(max(0, len(data.meta) - last), len(data.meta))
    recs = recs[data.n_opts[recs] > 0]
    sums, counts = defaultdict(float), defaultdict(int)
    with torch.no_grad():
        for k in range(0, len(recs), 256):
            chunk = recs[k:k + 256]
            q, seg = q_all(net, data, chunk)
            mean = torch.zeros(len(chunk)).index_add(0, seg, q) / torch.from_numpy(data.n_opts[chunk]).float()
            q = (q - mean[seg]).numpy()
            verbs = [v for r in chunk for v in data.meta[r]["verbs"]]
            for v, x in zip(verbs, q):
                sums[v] += float(x)
                counts[v] += 1
    return {v: round(sums[v] / counts[v], 2) for v in sorted(sums, key=lambda v: -sums[v] / counts[v])}


def train(log_dir, steps=None, fresh=False, quiet=False):
    torch.set_num_threads(THREADS)
    t0 = time.time()
    log_dir = Path(log_dir)
    model_path = log_dir / "model" / "qnet.pt"
    data = Data(log_dir)
    if len(data.ti) < BATCH:
        msg = f"not enough experience yet: {len(data.ti)} transitions"
        if not quiet:
            print(msg, flush=True)
        return {"skipped": msg}
    old, meta = N.load(model_path)
    rnd = (meta or {}).get("round", 0) + 1
    net = N.QNet() if fresh or old is None else old
    net.train()
    target = copy.deepcopy(net)
    opt = torch.optim.Adam(net.parameters(), lr=LR)
    rng = np.random.default_rng()
    n = steps or STEPS
    losses, qs = [], []
    for k in range(n):
        if k % TARGET_EVERY == 0:
            target.load_state_dict(net.state_dict())
        loss, qm = step(net, target, opt, data, rng)
        losses.append(loss)
        qs.append(qm)
    net.eval()
    lives = {m["life"] for m in data.meta if m["life"] is not None}
    rec = {"round": rnd, "trained_at": datetime.now().isoformat(timespec="seconds"), "steps": n, "fresh": bool(fresh or old is None),
           "decisions": len(data.meta), "transitions": int(len(data.ti)), "lives": len(lives),
           "loss_first": round(float(np.mean(losses[:50])), 4), "loss": round(float(np.mean(losses[-100:])), 4),
           "q_mean": round(float(np.mean(qs[-100:])), 3), "seconds": round(time.time() - t0, 1),
           "verbs": verb_values(net, data)}
    N.save(net, model_path, **{k: v for k, v in rec.items() if k != "verbs"})
    with (log_dir / "model" / "history.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if not quiet:
        print(json.dumps(rec, ensure_ascii=False), flush=True)
    return rec


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log-dir", default=str(ROOT / "logs"))
    ap.add_argument("--steps", type=int, default=None, help="gradient steps (default %d)" % STEPS)
    ap.add_argument("--fresh", action="store_true", help="start from a new network instead of the saved one")
    args = ap.parse_args()
    train(args.log_dir, args.steps, args.fresh)


if __name__ == "__main__":
    main()
