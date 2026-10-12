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

The reward is the current one (agent/reward.py) for every decision: older records are re-scored as they are read,
the infection, the death and the change in the body's value Φ are worked out here from the observations of each
life in order, and a network trained under another reward version is set aside for a fresh one. The future is discounted by game
time, not by decision: being alive pays by the game minute, so with a per-decision discount an action that takes
an hour (sleeping) would collect an hour's reward in one undiscounted step and look better just for being long.
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
from agent import reward as R  # noqa: E402

HALF_LIFE_MIN = 120   # game minutes: a reward 2 game hours away counts half
GAMMA = 0.5 ** (1 / HALF_LIFE_MIN)   # per game minute
MIN_STEP_MIN = 0.1    # a decision that takes no game time (character creation, a dropped item) still discounts a little
BATCH = 256
STEPS = 2000          # updates per round (about a minute on 4 threads); each round starts from the last network
TARGET_EVERY = 200    # steps between copies of the network used for the bootstrapped targets
CQL = 0.5             # weight of the conservative term
LR = 5e-4
THREADS = 4           # CPU threads for training, leaving the rest to the game


def _meta(r):
    points, minutes = R.rescore(r)
    body = None if r.get("reason") == "creation" or r.get("dead") else R.body(r.get("obs"))
    return {"choice": r.get("choice"), "reward": points, "minutes": minutes, "body": body, "dead": bool(r.get("dead")),
            "life": r.get("life"), "reason": r.get("reason"), "new_life": bool(r.get("new_life")),
            "resumed": bool(r.get("resumed")), "options": len(r.get("options") or []),
            "verbs": [o.get("verb") for o in r.get("options") or []]}


def encode_file(path, cache_dir, live):
    """Encoded decisions of one experience file, from the cache when the file hasn't changed."""
    st = path.stat()
    key = f"{st.st_size}-{st.st_mtime_ns}-v{F.VERSION}-r{R.VERSION}"
    cp = cache_dir / f"{path.name}.npz"
    if not live and cp.exists():
        try:
            # closed before an out-of-date cache is replaced below: Windows refuses to replace an open file, which
            # failed every training round after a version change (found in the reward version 3 dry run)
            with np.load(cp, allow_pickle=False) as z:
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
        # what each decision led to, in the network's units (N.SCALE points). The minutes alive are discounted
        # within the stretch, as if paid minute by minute; the rest counts at its end.
        minutes = np.array([m.get("minutes", 0.0) for m in metas], dtype=np.float64)
        points = np.array([m["reward"] for m in metas], dtype=np.float64)
        alive = R.ALIVE_PER_MIN * (1 - GAMMA ** minutes) / (1 - GAMMA)
        self.reward = ((points - R.ALIVE_PER_MIN * minutes + alive) / N.SCALE).astype(np.float32)
        self.disc = (GAMMA ** np.maximum(minutes, MIN_STEP_MIN)).astype(np.float32)   # discount over each stretch
        self.terminal = np.array([m["dead"] or m["options"] == 0 for m in metas])
        self.choice = np.array([m["choice"] if m["choice"] is not None else -1 for m in metas], dtype=np.int64)
        tr = F.transitions(metas)
        self.ti = np.array([i for i, _ in tr], dtype=np.int64)
        self.tj = np.array([j for _, j in tr], dtype=np.int64)
        ok = (self.choice[self.ti] >= 0) & (self.choice[self.ti] < self.n_opts[self.ti])
        self.ti, self.tj = self.ti[ok], self.tj[ok]
        # the infection and the death, carried through each life, and the change in Φ over each transition: discounted
        # Φ after minus Φ before, Φ = 0 once dead. No change in Φ across a character creation (no body before) or a
        # stretch without a body observation.
        events, phi, has = self.body_values(metas)
        self.reward += (events / N.SCALE).astype(np.float32)
        dead = np.array([m["dead"] for m in metas], dtype=bool)
        i, j = self.ti, self.tj
        after = np.where(dead[j], 0.0, self.disc[j] * phi[j])
        shaped = np.where(has[i] & (has[j] | dead[j]), after - phi[i], 0.0)
        self.reward[j] += (shaped / N.SCALE).astype(np.float32)

    @staticmethod
    def body_values(metas):
        """Per record: the infection or death charged there (points), Φ of its observation, and whether it has one.
        The infection is carried through each life in file order: the game's flag where a record has it, else the
        chance from the zombie wounds seen; a death costs what the infection hasn't already charged."""
        events, phi, has = np.zeros(len(metas)), np.zeros(len(metas)), np.zeros(len(metas), dtype=bool)
        inf, last = {}, {}
        for k, m in enumerate(metas):
            life = m.get("life")
            if life is None:
                continue
            if m.get("new_life"):
                inf[life], last[life] = 0.0, None
            p = inf.get(life, 0.0)
            if m.get("dead"):
                events[k] = R.DEATH * (1 - p)
                continue
            b = m.get("body")
            if b is None:
                continue
            q = R.infected(p, last.get(life), b)
            if not m.get("resumed"):   # an infection caught while the agent was off isn't charged to it
                events[k] = R.DEATH * (q - p)
            inf[life], last[life] = q, b
            phi[k], has[k] = R.potential(b), True
        return events, phi, has

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
        y = torch.from_numpy(data.reward[J]) + torch.from_numpy(data.disc[J]) * boot
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
    return {v: round(N.SCALE * sums[v] / counts[v], 2) for v in sorted(sums, key=lambda v: -sums[v] / counts[v])}


def last_round(log_dir):
    """The last round in logs/model/history.jsonl, or 0."""
    try:
        lines = (Path(log_dir) / "model" / "history.jsonl").read_text(encoding="utf-8").splitlines()
        return max((json.loads(x).get("round", 0) for x in lines if x.strip()), default=0)
    except (OSError, ValueError):
        return 0


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
    rnd = max((meta or {}).get("round", 0), last_round(log_dir)) + 1   # a network set aside keeps the count going
    if (meta or {}).get("reward_v", 1) != R.VERSION:
        old = None   # scores of another reward: start over rather than unlearn them
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
           "q_mean": round(N.SCALE * float(np.mean(qs[-100:])), 3), "reward_v": R.VERSION,
           "seconds": round(time.time() - t0, 1),
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
