"""What the network sees: the observation and each option turned into numbers (Phase 4).

Only what a player could perceive goes in (an allow-list, so a new field in the observation stays out until it
is added here on purpose). Moodles are the main body input, as the player's own moodle icons are. Not used:
the raw stats behind them (hunger 0.09, temperature 37.3), the world clock (`t.hour`, `t.age`; the time is
seen only on a worn watch or clock, `obs.clock`), the air temperature, map coordinates, and `last.msg` (a
text explanation of a failure the player wouldn't be given).

Each side is a dense vector of fixed meaning plus a bag of hashed tokens ("inv:Base.Apple", "take:cat:food"),
so item and place names the network has never seen still get an input without a fixed vocabulary.

Also here: reading the experience files (tolerating damaged ones) and turning them into transitions.
"""

import gzip
import json
import math
import zlib
from pathlib import Path

VERSION = 1           # bump when the encoding changes: cached features and saved networks are rebuilt
BUCKETS = 4096        # hashed-token buckets per side

MOODLES = ("hungry", "thirst", "tired", "endurance", "panic", "pain", "sick", "wet", "hypothermia", "hyperthermia",
           "heavy_load", "bleeding", "stress", "injured", "has_a_cold", "drunk", "zombie", "bored", "unhappy", "angry",
           "windchill", "cant_sprint", "uncomfortable", "noxious_smell", "food_eaten")
WOUNDS = ("bleeding", "scratch", "laceration", "bite", "bandaged", "deep wound", "glass", "burn", "fracture", "infected")
REASONS = ("hurt", "failed", "still at it", "done", "zombie close", "idle", "creation")
STATUSES = ("running", "done", "failed")

# option fields with a number or a yes/no, and the scale that brings them near 0..1
OPTION_NUMBERS = {
    "d": 20, "dx": 20, "dy": 20, "cost": 10, "minutes": 60, "w": 10, "zombies": 5, "closing": 1, "blocked": 1,
    "down": 1, "open": 1, "locked": 1, "exterior": 1, "glass": 1, "smashed": 1, "here": 1, "indoors": 1,
    "visited": 1, "rooms": 10, "tainted": 1, "worn": 1, "hunger": 50, "thirst": 50, "unhappy": 50, "rotten": 1,
    "cooked": 1, "raw": 1, "sealed": 1, "age": 30, "unavailable": 1, "bleeding": 1, "running": 1, "bed": 1,
    "endurance": 1, "cap": 50, "cond": 10, "dmg": 5, "range": 5, "ranged": 1, "twoHand": 1, "med": 1, "seat": 4,
}
OPTION_WORDS = ("name", "type", "cat", "dir", "recipe", "part", "trait", "what", "area", "from", "to", "toKind",
                "fluidType", "item", "list")

STATE_DIM = len(MOODLES) + len(WOUNDS) + len(REASONS) + len(STATUSES) + 32
OPTION_DIM = len(OPTION_NUMBERS) + 1


def _d(v):
    return v if isinstance(v, dict) else {}


def _l(v):
    return v if isinstance(v, list) else []


def _num(v, default=0.0):
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)) and math.isfinite(v):
        return float(v)
    return default


def bucket(token):
    return zlib.crc32(token.encode("utf-8")) % BUCKETS


# Inputs a player can't see (OBSERVATION_AUDIT.md): a window's lock isn't shown by the menu, and the fitness
# screen shows endurance as a moodle, not a number. The slots stay (the layout and the network are kept), but
# are always 0.
HIDDEN_OPTION_FIELDS = {("window", "locked"), ("exercise", "endurance")}
HEALTH_BANDS = (90, 80, 70, 60, 50, 40, 20, 10, 0)   # the health panel's status text changes at these


def health_band(h):
    """The overall health as the panel's wording bands it (OK at 100, then one step per band), 0..1."""
    if h >= 100:
        return 1.0
    for i, b in enumerate(HEALTH_BANDS):
        if h > b:
            return round(0.9 - 0.1 * i, 1)
    return 0.0


def _clip(x, lo=-5.0, hi=5.0):
    return lo if x < lo else hi if x > hi else x


def encode_state(msg):
    """(dense list of STATE_DIM floats, list of token buckets) for one decision request."""
    obs = _d(msg.get("obs"))
    v, toks = [], []
    moodles = _d(obs.get("moodles"))
    v += [_num(moodles.get(m)) / 4 for m in MOODLES]
    wounds = dict.fromkeys(WOUNDS, 0)
    for w in _l(obs.get("body")):
        flags = _l(_d(w).get("flags"))
        for f in flags:
            if f in wounds:
                wounds[f] += 1
            toks.append(f"wound:{_d(w).get('part')}:{f}")
    v += [min(n, 6) / 3 for n in wounds.values()]
    reason = msg.get("reason")
    v += [1.0 if reason == r else 0.0 for r in REASONS]
    last = _d(msg.get("last"))
    v += [1.0 if last.get("status") == s else 0.0 for s in STATUSES]
    if last.get("verb"):
        toks.append(f"last:{last['verb']}:{last.get('status')}")
    # 32 general inputs
    t, light, where, near = _d(obs.get("t")), _d(obs.get("light")), _d(obs.get("where")), _d(obs.get("near"))
    clock = obs.get("clock") if isinstance(obs.get("clock"), dict) else None
    hour = (_num(clock.get("hour")) + _num(clock.get("min")) / 60) if clock else 0.0
    zs = [_d(z) for z in _l(obs.get("zombies"))]
    dists = [_num(z.get("d"), 99.0) for z in zs]
    nearest = min(dists) if dists else 99.0
    weight, maxw = _num(obs.get("weight")), _num(obs.get("maxWeight"), 1.0) or 1.0
    speed = max(1.0, _num(obs.get("speed"), 1.0))
    creation = bool(msg.get("creation")) or reason == "creation"   # a logged record keeps only the reason
    v += [
        health_band(_num(obs.get("health"), 100.0)) if not creation else 1.0,
        _num(light.get("here"), 1.0), _num(t.get("dark")), 1.0 if where.get("outside") else 0.0,
        1.0 if where.get("building") else 0.0, 1.0 if obs.get("asleep") else 0.0,
        1.0 if clock else 0.0, math.sin(hour / 24 * 2 * math.pi) if clock else 0.0,
        math.cos(hour / 24 * 2 * math.pi) if clock else 0.0, _num(_d(obs.get("weather")).get("rain")),
        _clip(weight / maxw), maxw / 20,
        min(len(zs), 20) / 10, max(0.0, 1 - nearest / 20), sum(d < 2 for d in dists) / 3,
        sum(d < 5 for d in dists) / 5, sum(d < 10 for d in dists) / 5,
        (sum(_num(z.get("closing")) for z in zs) / len(zs)) if zs else 0.0,
        sum(1 for z in zs if z.get("down")) / 3, sum(1 for z in zs if z.get("blocked")) / 3,
        min(_num(near.get("food")), 5) / 5, min(_num(near.get("drink")), 5) / 5, min(_num(near.get("medical")), 5) / 5,
        min(_num(near.get("weapon")), 5) / 5, min(_num(near.get("items")), 5) / 5,
        math.log(speed) / math.log(40),
        min(len(_l(obs.get("inv"))), 40) / 20, 1.0 if isinstance(obs.get("held"), dict) else 0.0,
        1.0 if creation else 0.0, _clip(_num(obs.get("points")) / 10) if creation else 0.0,
        min(len(_l(obs.get("selected"))), 20) / 10 if creation else 0.0,
        1.0 if creation and obs.get("stage") == "pay" else 0.0,
    ]
    for it in _l(obs.get("inv")):
        it = _d(it)
        toks.append(f"inv:{it.get('type') or it.get('name')}")
        if it.get("worn"):
            toks.append(f"worn:{it.get('type') or it.get('name')}")
    held = obs.get("held")
    if isinstance(held, dict):
        toks.append(f"held:{held.get('type') or held.get('name')}")
    if where.get("room"):
        toks.append(f"room:{where['room']}")
    for s in _l(obs.get("selected")) + _l(obs.get("traits")):   # chosen at creation, then carried through the life
        toks.append(f"trait:{s}")
    return v, [bucket(x) for x in toks]


def encode_option(o):
    """(dense list of OPTION_DIM floats, list of token buckets) for one option."""
    o = _d(o)
    verb = str(o.get("verb"))
    v = [0.0 if (verb, k) in HIDDEN_OPTION_FIELDS else _clip(_num(o.get(k)) / s) for k, s in OPTION_NUMBERS.items()]
    v.append(1.0)   # a constant input, so every option has one non-zero entry
    toks = [f"verb:{verb}"]
    for k in OPTION_WORDS:
        x = o.get(k)
        if x is not None and not isinstance(x, (dict, list)):
            toks.append(f"{verb}:{k}:{x}")
            toks.append(f"{k}:{x}")   # shared across verbs: "type:Base.Apple" for take, eat and drop alike
    if isinstance(o.get("zombies"), (int, float)) and o["zombies"] > 0:
        toks.append(f"{verb}:toward_zombies")
    return v, [bucket(x) for x in toks]


# ---------------------------------------------------------------------------------------------- reading logs

def read_records(path):
    """Every decision record in one experience file. A file that two agents wrote at once (2026-10-11 11h and
    12h) has broken gzip members or plain text in it: whatever whole lines can still be read are kept."""
    data = Path(path).read_bytes()
    try:
        text = gzip.decompress(data).decode("utf-8", errors="replace")
    except (OSError, EOFError, zlib.error):
        text = _salvage(data)
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def _salvage(data):
    parts, i = [], 0
    while True:
        j = data.find(b"\x1f\x8b\x08", i)
        if j < 0:
            break
        d = zlib.decompressobj(31)
        try:
            parts.append(d.decompress(data[j:]).decode("utf-8", errors="replace"))
            i = j + max(3, len(data[j:]) - len(d.unused_data))
        except zlib.error:
            i = j + 3
    return "\n".join(parts)


def transitions(records):
    """Pairs (i, j) of record indices: decision i, and the next decision j of the same stream, with j's reward
    being what decision i led to. Streams: one life, and a character creation running into the life it made.
    A record marked 'resumed' starts nothing new: what happened while the agent was off isn't its doing."""
    out = []
    for i in range(len(records) - 1):
        a, b = records[i], records[i + 1]
        if a.get("choice") is None or not a.get("options"):
            continue
        if b.get("resumed"):
            continue
        if a.get("reason") == "creation":
            ok = b.get("reason") == "creation" or b.get("new_life")
        else:
            ok = a.get("life") is not None and b.get("life") == a.get("life") and not b.get("new_life")
        if ok:
            out.append((i, i + 1))
    return out
