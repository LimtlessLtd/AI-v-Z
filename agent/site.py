"""The public page's data (site/, https://limtlessltd.github.io/AI-v-Z/): an allow-listed export of the logs.

    python -m agent.site --out DIR [--zip FILE]   # from the repo root; scripts/publish-site.ps1 uploads the zip

It writes:
    summary.json          training rounds and every life (the Learning page's data, lives.learning_data)
    lives/index.json      the lives that have a replay: the last few, the longest ones, and the life in progress
    lives/<n>.json        a replay, one step per decision: what it perceived, its top options with Q, its pick
    net.json, qnet.npz    the network's layout and weights (needs PyTorch; net.json says why when skipped)

Only the fields named here leave the PC, so a new field in the logs stays off the page until it is added on
purpose. Left out on purpose: the hearing snapshot (wall-clock times), save names, the inventory, the
protection panel, the raw stats behind the moodles and the hidden Knox flag. Nothing is read back from the page.
"""

import argparse
import json
import math
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import features as F  # noqa: E402
from agent import reward  # noqa: E402
from agent.lives import Lives, learning_data  # noqa: E402

RECENT, LONGEST = 10, 10   # replays: the last finished lives, and the longest ones that still have experience
TOP = 10                   # options kept per step, the best by Q, plus the one picked
ZOMBIES = 40               # zombies kept per step, nearest first
ROUND_KEYS = ("round", "trained_at", "decisions", "lives", "loss_first", "loss", "q_mean", "seconds", "reward_v",
              "verbs")
LIFE_AT = re.compile(r'"life":\s?(\d+)')   # records start {"ts":"…","life":N,…}: a life's lines are found unparsed


def num(v, nd=2):
    """A finite number rounded to nd places, else None (JSON has no NaN)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return round(v, nd) if nd else round(v)


def text(v):
    return v if isinstance(v, str) else ""


def dct(v):
    return v if isinstance(v, dict) else {}


def label(o):
    """What an option acts on, as the dashboard names it (agent/agent.html what())."""
    for k in ("name", "dir", "what", "part", "type"):
        if o.get(k) not in (None, ""):
            return str(o[k])
    return ""


def detail(o):
    """The rest of an option a viewer needs (agent/agent.html detail(), plus a few more)."""
    bits = []
    if isinstance(o.get("d"), (int, float)):
        bits.append(f"{o['d']} tiles")
    if o.get("zombies"):
        bits.append(f"{o['zombies']} zombies that way")
    if "open" in o and o.get("verb") in ("door", "window", "curtain"):
        bits.append("open" if o["open"] else "closed")
    for k, word in (("locked", "locked"), ("exterior", "outside"), ("smashed", "smashed"), ("rotten", "rotten"),
                    ("worn", "worn"), ("bed", "bed"), ("visited", "visited"), ("bleeding", "bleeding"),
                    ("tall", "tall"), ("drop", "a drop beyond"), ("door", "on a door")):
        if o.get(k) is True:
            bits.append(word)
    if o.get("recipe"):
        bits.append(str(o["recipe"]))
    if o.get("item"):
        bits.append("with " + str(o["item"]))
    if o.get("from"):
        bits.append("from " + str(o["from"]))
    if o.get("to"):
        bits.append("to " + str(o["to"]))
    if isinstance(o.get("minutes"), (int, float)):
        bits.append(f"{o['minutes']} min")
    if isinstance(o.get("cost"), (int, float)):
        bits.append(f"cost {o['cost']}")
    if isinstance(o.get("facing"), (int, float)):
        bits.append("facing " + {"toward": "it", "away": "away", "side": "side-on"}[F.facing_word(o["facing"])])
    return ", ".join(bits)


def step(r):
    """One decision of a replay, from an experience record: only the fields the page shows."""
    obs = dct(r.get("obs"))
    t, pos, where = dct(obs.get("t")), dct(obs.get("pos")), dct(obs.get("where"))
    opts = [o for o in r.get("options") or [] if isinstance(o, dict)]
    q, p, c = r.get("q") or [], r.get("probs") or [], r.get("choice")
    qs = [num(q[i], 1) if i < len(q) else None for i in range(len(opts))]
    ps = [num(p[i], 3) if i < len(p) else None for i in range(len(opts))]
    order = sorted(range(len(opts)), key=lambda i: -qs[i]) if all(x is not None for x in qs) and opts else \
        list(range(len(opts)))
    keep = order[:TOP]
    if isinstance(c, int) and 0 <= c < len(opts) and c not in keep:
        keep.append(c)
    s = {"t": [t.get("day"), t.get("hour"), t.get("min")], "age": num(t.get("age")),
         "why": text(r.get("reason")), "pol": text(r.get("policy")), "n": len(opts),
         "o": [[text(opts[i].get("verb")), label(opts[i]), detail(opts[i]), qs[i], ps[i], int(i == c)] for i in keep]}
    if pos:
        s["pos"] = [num(pos.get("x"), 1), num(pos.get("y"), 1), num(pos.get("z"), 0)]
    if isinstance(obs.get("health"), (int, float)):
        s["hp"] = num(obs["health"], 0)
    moodles = {str(k): v for k, v in dct(obs.get("moodles")).items() if isinstance(v, (int, float))}
    if moodles:
        s["m"] = moodles
    wounds = [[text(w.get("part")), [text(f) for f in w.get("flags") or []]] for w in obs.get("body") or []
              if isinstance(w, dict)]
    if wounds:
        s["w"] = wounds
    zs = sorted((z for z in obs.get("zombies") or [] if isinstance(z, dict)), key=lambda z: num(z.get("d")) or 0)
    if zs:
        s["z"] = [[num(z.get("dx"), 1), num(z.get("dy"), 1), num(z.get("facing")), int(bool(z.get("down"))),
                   int(bool(z.get("blocked")))] for z in zs[:ZOMBIES]]
    if where:
        s["in"] = "" if where.get("outside") else text(where.get("room")) or "a room"
    held = obs.get("held")
    if isinstance(held, dict) and held.get("name"):
        s["held"] = text(held["name"])
    s["mv"] = "asleep" if obs.get("asleep") else "running" if obs.get("running") else "sneaking" if obs.get("sneaking") else ""
    last = dct(r.get("last"))
    if last.get("verb"):
        s["last"] = [text(last.get("verb")), text(last.get("status")), text(last.get("msg"))]
    s["r"] = num(r.get("reward"))
    if dct(r.get("parts")):
        s["parts"] = {str(k): num(v) for k, v in r["parts"].items()}
    if r.get("dead"):
        s["dead"] = 1
    return s


def pick_lives(history, current):
    """(the lives wanted for replays, candidates for the longest): the last finished lives, the longest finished ones
    (the earliest lives have no experience left, so more candidates than needed), and the life in progress."""
    done = [x for x in history if isinstance(x.get("life"), int)]
    recent = [x["life"] for x in done[-RECENT:]]
    longest = [x["life"] for x in sorted(done, key=lambda x: -(x.get("hours") or 0))[:LONGEST * 4]]
    now = [current.number] if current else []
    return recent, longest, now


def collect(exp_dir, wanted):
    """({life: [steps]}, {life: [traits]}) for the wanted lives, from every experience file. Only their lines are
    parsed. The traits are the ones the first record of the life shows."""
    steps, traits = {n: [] for n in wanted}, {}
    for path in sorted(Path(exp_dir).glob("*.jsonl.gz")):
        for line in F.read_lines(path):
            m = LIFE_AT.search(line[:80])
            if not m or int(m.group(1)) not in steps:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            n = r.get("life")
            if n not in steps or r.get("reason") == "creation":
                continue
            steps[n].append(step(r))
            if n not in traits and isinstance(dct(r.get("obs")).get("traits"), list):
                traits[n] = [text(x) for x in r["obs"]["traits"]]
    return steps, traits


def replays(log_dir, lives):
    """(index, {life: replay}) for the lives picked by pick_lives that still have experience."""
    exp = Path(log_dir) / "experience"
    recent, longest, now = pick_lives(lives.history, lives.current)
    steps, traits = collect(exp, set(recent) | set(longest) | set(now))
    longest = [n for n in longest if steps.get(n)][:LONGEST]
    by_life = {x["life"]: x for x in lives.history if isinstance(x.get("life"), int)}
    index, out = [], {}
    for n in dict.fromkeys(recent + longest + now):
        if not steps.get(n):
            continue
        x = by_life.get(n)
        if x:
            meta = {"life": n, "who": text(x.get("who")), "policy": text(x.get("policy")) or "random",
                    "hours": num(x.get("hours")), "kills": x.get("kills", 0), "ended": text(x.get("ended")),
                    "reward": num(x.get("reward")) if x.get("reward_v", 1) == reward.VERSION else None,
                    "reward_v": x.get("reward_v", 1), "born": num(x.get("born_age")),
                    "last_choice": text(x.get("last_choice"))}
        else:   # the life in progress
            cur = lives.current
            meta = {"life": n, "who": text(cur.name), "policy": text(cur.policy()) or "random", "hours": cur.hours(),
                    "kills": cur.kills, "ended": "playing", "reward": num(cur.reward), "reward_v": cur.reward_v,
                    "born": num(cur.born), "last_choice": text(cur.last_choice)}
        meta["picked"] = [w for w, ls in (("recent", recent), ("longest", longest), ("playing", now)) if n in ls]
        meta["steps"] = len(steps[n])
        index.append(meta)
        out[n] = {**meta, "traits": traits.get(n, []), "data": steps[n]}
    return index, out


def network(log_dir, out_dir):
    """net.json's content; writes qnet.npz (plain arrays, no pickle) beside it when there is a network."""
    try:
        from agent import net as N
    except ImportError:
        return {"available": False, "why": "PyTorch isn't installed on the PC that published this page"}
    model, meta = N.load(Path(log_dir) / "model" / "qnet.pt")
    if model is None:
        return {"available": False, "why": "no trained network yet"}
    arrays, layers = {}, []
    for name, t in model.state_dict().items():
        a = t.detach().cpu().numpy()
        arrays[name] = a
        counts, edges = np.histogram(a, bins=24)
        layers.append({"name": name, "shape": list(a.shape), "count": int(a.size),
                       "mean": num(float(a.mean()), 5), "std": num(float(a.std()), 5),
                       "hist": [int(x) for x in counts], "range": [num(float(edges[0]), 4), num(float(edges[-1]), 4)]})
    np.savez_compressed(Path(out_dir) / "qnet.npz", **arrays)
    return {"available": True, "round": meta.get("round"), "trained_at": meta.get("trained_at"),
            "decisions": meta.get("decisions"), "total": sum(x["count"] for x in layers), "layers": layers,
            "sizes": {"state_dim": F.STATE_DIM, "option_dim": F.OPTION_DIM, "buckets": F.BUCKETS, "emb": N.EMB,
                      "hidden": N.HIDDEN, "out": N.OUT},
            "features_v": F.VERSION, "scale": N.SCALE}


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")


def export(log_dir, out_dir):
    """Writes the page's data into out_dir. Returns a one-line summary."""
    log_dir, out_dir = Path(log_dir), Path(out_dir)
    (out_dir / "lives").mkdir(parents=True, exist_ok=True)
    for old in (out_dir / "lives").glob("*.json"):   # a replay dropped from the index must not be published
        old.unlink()
    lives = Lives(log_dir)
    data = learning_data(log_dir, lives.history, rounds=None, lives=None)
    hist = [{k: h.get(k) for k in ROUND_KEYS if k in h} for h in data["history"]]
    cur = lives.current
    index, reps = replays(log_dir, lives)
    net = network(log_dir, out_dir)
    write(out_dir / "summary.json", {
        "generated": datetime.now().isoformat(timespec="seconds"), "reward_v": reward.VERSION,
        "features_v": F.VERSION, "history": hist, "lives": data["lives"],
        "playing": {"life": cur.number, "who": text(cur.name), "hours": cur.hours(), "kills": cur.kills,
                    "decisions": cur.decisions} if cur else None,
        "network": {k: net.get(k) for k in ("available", "round", "trained_at", "total", "why") if k in net}})
    write(out_dir / "lives" / "index.json", index)
    for n, rep in reps.items():
        write(out_dir / "lives" / f"{n}.json", rep)
    write(out_dir / "net.json", net)
    return (f"{len(hist)} training rounds, {len(data['lives'])} lives, {len(reps)} replays "
            f"({sum(len(r['data']) for r in reps.values())} steps), network: "
            f"{'round ' + str(net.get('round')) if net.get('available') else net.get('why')}")


def zip_dir(src, dest):
    """The folder as a zip with '/' separators (PowerShell 5.1's Compress-Archive writes '\\', which unzip on the
    Pages runner mishandles)."""
    src = Path(src)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(p for p in src.rglob("*") if p.is_file()):
            z.write(f, f.relative_to(src).as_posix())


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log-dir", default=str(ROOT / "logs"))
    ap.add_argument("--out", required=True, help="the folder to write into (its lives/*.json are replaced)")
    ap.add_argument("--zip", help="also pack the folder into this zip (what scripts/publish-site.ps1 uploads)")
    args = ap.parse_args()
    print(export(args.log_dir, args.out), flush=True)
    if args.zip:
        zip_dir(args.out, args.zip)


if __name__ == "__main__":
    main()
