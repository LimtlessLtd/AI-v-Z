"""What the network sees: the observation and each option turned into numbers (Phase 4).

Only what a player could perceive goes in (an allow-list, so a new field in the observation stays out until it
is added here on purpose). Moodles are the main body input, as the player's own moodle icons are. Not used:
the raw stats behind them (hunger 0.09, temperature 37.3), the world clock (`t.hour`, `t.age`; the time is
seen only on a worn watch or clock, `obs.clock`), the air temperature, map coordinates, `last.msg` (a
text explanation of a failure the player wouldn't be given), and `obs.knox` (the hidden Knox infection, which only
the reward reads). Used since version 2: `obs.protection`, the protection panel's bite and scratch defence per body
part, and each garment's tooltip (defence, holes, condition) on its own options and tied to it when worn. Since
version 3: where the zombies in sight are (each compass sector's nearest one and how many), as a player sees them on
screen, and on each option with a direction the zombies that lie that way; the building's open doors, windows and
curtains and its smashed windows, counted on squares the character has seen. Tokens since gym 0.4.25 (no
version bump): the character's own stance (sneaking, running) and which way each zombie in sight within 10
tiles faces (towards the character, side-on or away), as a player sees from its body. Since gym 0.4.33 (no version
bump): a fence's height and a drop beyond it, and whether a sheet or curtain is on a door (OPTION_FLAGS). Since
gym 0.4.35 (no version bump): half or all of a pile on the ground (`how`), and a corpse in tow (`self:dragging`).

Each side is a dense vector of fixed meaning plus a bag of hashed tokens ("inv:Base.Apple", "take:cat:food"),
so item and place names the network has never seen still get an input without a fixed vocabulary.

Also here: reading the experience files (tolerating damaged ones) and turning them into transitions.
"""

import gzip
import json
import math
import zlib
from pathlib import Path

VERSION = 3           # bump when the encoding changes: cached features and saved networks are rebuilt
                      # 2 (2026-10-12, with reward version 3): protection per body part, clothing status on options
                      # 3 (2026-10-12, owner's go-ahead): where the zombies are, by sector and per option; openings
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
    "bite": 100, "scratch": 100, "holes": 5, "patches": 5,   # a garment's tooltip: what wearing it would add
}
OPTION_WORDS = ("name", "type", "cat", "dir", "recipe", "part", "trait", "what", "area", "from", "to", "toKind",
                "fluidType", "item", "list", "ammo", "mag", "slot", "fire", "how")   # how: gym 0.4.35, half or all
# yes/no option fields added after the dense layout was fixed: a token when true, so the layout (and the trained
# network) stays. Gym 0.4.33: a tall fence, a drop beyond a fence, a sheet or curtain on a door.
OPTION_FLAGS = ("tall", "drop", "door")

# the protection panel's body parts (BodyPartType order); obs.protection gives each one's bite and scratch defence
PARTS = ("Hand_L", "Hand_R", "ForeArm_L", "ForeArm_R", "UpperArm_L", "UpperArm_R", "Torso_Upper", "Torso_Lower", "Head",
         "Neck", "Groin", "UpperLeg_L", "UpperLeg_R", "LowerLeg_L", "LowerLeg_R", "Foot_L", "Foot_R")

# compass sectors, as the gym names directions (AIvZ.lua dir8: +y is south, 45 degrees each)
SECTORS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
ZOMBIE_RANGE = 20.0   # tiles: a zombie at the character's feet counts 1, one this far or further 0
OPENINGS = ("doorsOpen", "windowsOpen", "curtainsOpen", "smashed")

STATE_DIM = (len(MOODLES) + len(WOUNDS) + len(REASONS) + len(STATUSES) + 32 + 2 * len(PARTS) + 2 * len(SECTORS) + 3
             + len(OPENINGS))
OPTION_DIM = len(OPTION_NUMBERS) + 1 + 2


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


def facing_word(f):
    """A zombie's facing (gym 0.4.25: 1 straight at the character, -1 straight away) as a player would put it."""
    return "toward" if f >= 0.7 else "away" if f <= -0.3 else "side"


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


def _bin(x, edges=(0.25, 0.5, 0.75)):
    return sum(x > e for e in edges)


def sector(dx, dy):
    """The compass sector of (dx, dy) as the gym's dir8 names it, or None for the character's own square."""
    t = 0.4142   # tan 22.5 degrees
    ns = "N" if dy < -t * abs(dx) else "S" if dy > t * abs(dx) else ""
    ew = "E" if dx > t * abs(dy) else "W" if dx < -t * abs(dy) else ""
    return (ns + ew) or None


def _near(d):
    """How close a zombie is, 1 at the character's feet to 0 at ZOMBIE_RANGE tiles or further."""
    return max(0.0, 1.0 - d / ZOMBIE_RANGE)


def _zombies(obs):
    """(dx, dy, distance) of each zombie in sight."""
    out = []
    for z in _l(_d(obs).get("zombies")):
        z = _d(z)
        dx, dy = _num(z.get("dx")), _num(z.get("dy"))
        out.append((dx, dy, _num(z.get("d"), math.hypot(dx, dy))))
    return out


def zombies_toward(dx, dy, zombies):
    """(nearness of the closest, count within 10 tiles) of the zombies within 45 degrees of the direction (dx, dy)."""
    norm = math.hypot(dx, dy)
    best, n = 0.0, 0
    if norm == 0:
        return best, n
    for zx, zy, d in zombies:
        zn = math.hypot(zx, zy)
        if zn > 0 and (dx * zx + dy * zy) / (norm * zn) >= 0.7071:
            best = max(best, _near(d))
            n += d < 10
    return best, n


def item_status_tokens(it, prefix):
    """Hashed tokens for what an item's tooltip shows (gym 0.4.11): ammo and magazine types are the item types
    themselves, so which round fits which weapon is learned from the names. Numbers are binned."""
    it = _d(it)
    toks = []
    for k in ("ammo", "mag", "slot", "fire"):
        if it.get(k) is not None:
            toks.append(f"{prefix}:{k}:{it[k]}")
    for k in ("clip", "chambered", "jammed"):
        if it.get(k):
            toks.append(f"{prefix}:{k}")
    if it.get("maxAmmo"):
        toks.append(f"{prefix}:ammo_level:{_bin(_num(it.get('loaded')) / _num(it.get('maxAmmo')))}")   # 0 = empty
    if it.get("holes"):
        toks.append(f"{prefix}:holes:{min(int(_num(it['holes'])), 4)}")
    if it.get("patches"):
        toks.append(f"{prefix}:patched")
    for k in ("cond", "head", "sharp", "blood", "dirt", "wet"):
        if it.get(k) is not None and (it.get("cat") == "clothing" or k in ("cond", "head", "sharp")):
            toks.append(f"{prefix}:{k}:{_bin(_num(it[k]))}")
    if it.get("bite") or it.get("scratch"):
        toks.append(f"{prefix}:defence:{_bin(_num(it.get('bite')) + _num(it.get('scratch')), (5, 20, 50))}")
    return toks


def encode_state(msg):
    """(dense list of STATE_DIM floats, list of token buckets) for one decision request."""
    obs = _d(msg.get("obs"))
    v, toks = [], []
    moodles = _d(obs.get("moodles"))
    v += [_num(moodles.get(m)) / 4 for m in MOODLES]
    wounds = dict.fromkeys(WOUNDS, 0)
    for w in _l(obs.get("body")):
        flags = _l(_d(w).get("flags"))
        if "bandaged" in flags:   # the health panel hides glass (and infection, burns) under a bandage
            flags = [f for f in flags if f != "glass"]
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
    # the protection panel: bite and scratch defence of each body part (gym 0.4.20), 0 where unknown
    prot = {_d(x).get("part"): _d(x) for x in _l(obs.get("protection"))}
    for part in PARTS:
        x = prot.get(part, {})
        v += [min(_num(x.get("bite")), 100.0) / 100, min(_num(x.get("scratch")), 100.0) / 100]
    # where the zombies in sight are: per compass sector, the nearest one's nearness and how many within 10 tiles
    near, count = dict.fromkeys(SECTORS, 0.0), dict.fromkeys(SECTORS, 0)
    for dx, dy, d in _zombies(obs):
        sec = sector(dx, dy)
        if sec:
            near[sec] = max(near[sec], _near(d))
            count[sec] += d < 10
    for sec in SECTORS:
        v += [near[sec], min(count[sec], 6) / 3]
    # the nearest zombie as watched: how far it closed in since the last look, whether it's down or behind a wall
    z0 = min(zs, key=lambda z: _num(z.get("d"), 99.0)) if zs else {}
    v += [_clip(_num(z0.get("closing")) / 2, -1.0, 1.0), 1.0 if z0.get("down") else 0.0, 1.0 if z0.get("blocked") else 0.0]
    # this building's openings, on squares the character has seen (gym 0.4.17, 0.4.19)
    v += [min(_num(where.get(k)), 5) / 5 for k in OPENINGS]
    # the character's own stance and which way the zombies in sight within 10 tiles face (gym 0.4.25), as tokens
    if obs.get("sneaking"):
        toks.append("self:sneaking")
    if obs.get("running"):
        toks.append("self:running")
    if obs.get("dragging"):   # gym 0.4.35
        toks.append("self:dragging")
    for z in zs:
        d, f = _num(z.get("d"), 99.0), z.get("facing")
        if d < 10 and isinstance(f, (int, float)) and not z.get("down"):
            band = "close" if d < 3 else "near" if d < 6 else "mid"
            toks.append(f"zombie:facing:{facing_word(f)}:{band}")
    for it in _l(obs.get("inv")):
        it = _d(it)
        toks.append(f"inv:{it.get('type') or it.get('name')}")
        if it.get("worn"):
            kind = it.get('type') or it.get('name')
            toks.append(f"worn:{kind}")
            # the same status tied to this garment, so a worn-out or torn piece is told apart from the rest
            toks += [f"worn:{kind}:{t.split(':', 1)[1]}" for t in item_status_tokens(it, "inv")
                     if t.startswith(("inv:cond:", "inv:holes:", "inv:patched", "inv:defence:"))]
        toks += item_status_tokens(it, "inv")
    held = obs.get("held")
    if isinstance(held, dict):
        toks.append(f"held:{held.get('type') or held.get('name')}")
        toks += item_status_tokens(held, "held")
    if where.get("room"):
        toks.append(f"room:{where['room']}")
    for s in _l(obs.get("selected")) + _l(obs.get("traits")):   # chosen at creation, then carried through the life
        toks.append(f"trait:{s}")
    return v, [bucket(x) for x in toks]


def encode_option(o, obs=None):
    """(dense list of OPTION_DIM floats, list of token buckets) for one option. `obs` is the observation it was offered
    with: an option with a direction (walk, run, enter, go_room, attack...) also gets the zombies in sight that lie
    that way, the closest one's nearness and how many within 10 tiles."""
    o = _d(o)
    verb = str(o.get("verb"))
    v = [0.0 if (verb, k) in HIDDEN_OPTION_FIELDS else _clip(_num(o.get(k)) / s) for k, s in OPTION_NUMBERS.items()]
    v.append(1.0)   # a constant input, so every option has one non-zero entry
    ahead, n = zombies_toward(_num(o.get("dx")), _num(o.get("dy")), _zombies(obs)) if obs else (0.0, 0)
    v += [ahead, min(n, 6) / 3]
    toks = [f"verb:{verb}"]
    for k in OPTION_WORDS:
        x = o.get(k)
        if x is not None and not isinstance(x, (dict, list)):
            toks.append(f"{verb}:{k}:{x}")
            toks.append(f"{k}:{x}")   # shared across verbs: "type:Base.Apple" for take, eat and drop alike
    toks += [f"{verb}:{k}" for k in OPTION_FLAGS if o.get(k) is True]
    if isinstance(o.get("zombies"), (int, float)) and o["zombies"] > 0:
        toks.append(f"{verb}:toward_zombies")
    if verb == "disassemble" and isinstance(o.get("chance"), (int, float)):   # the menu's chance of the materials
        toks.append(f"disassemble:chance:{min(int(o['chance']) // 25, 4)}")
    if isinstance(o.get("facing"), (int, float)):   # attack and shove: which way that zombie faces
        toks.append(f"{verb}:facing:{facing_word(o['facing'])}")
    return v, [bucket(x) for x in toks]


# ---------------------------------------------------------------------------------------------- reading logs

def read_records(path):
    """Every decision record in one experience file. A file that two agents wrote at once (2026-10-11 11h and
    12h) has broken gzip members or plain text in it: whatever whole lines can still be read are kept."""
    out = []
    for line in read_lines(path):
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def read_lines(path):
    """The record lines of one experience file, still as text (see read_records)."""
    data = Path(path).read_bytes()
    try:
        text = gzip.decompress(data).decode("utf-8", errors="replace")
    except (OSError, EOFError, zlib.error):
        text = _salvage(data)
    return [line for line in (x.strip() for x in text.splitlines()) if line.startswith("{")]


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
