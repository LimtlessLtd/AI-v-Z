"""Turns the mod's raw percept (Zomboid/Lua/aivz/percept.json) into what the brain reasons over.

`summarize` returns a percept dict with the same shape as the benchmark snapshots in bench/snapshots.py,
so brain/rules.py and brain/prompt.py work unchanged on live game data. It also works out which goals are
legal right now and the arguments the mod needs to carry each one out (a building to walk to, a heading).
"""

import math
import random
from collections import deque
from dataclasses import dataclass, field

# raw moodle names from the mod -> the names rules.py and the prompt use
MOODLES = {"hungry": "hunger", "thirst": "thirst", "tired": "tired", "endurance": "endurance", "panic": "panic",
           "pain": "pain", "sick": "sick", "wet": "wet", "hypothermia": "cold", "heavy_load": "heavy_load",
           "stress": "stress"}
HOUSE_ROOMS = {"bedroom", "kitchen", "bathroom", "livingroom", "hall", "laundry"}
HOME_FAR = 120     # tiles: further than this, shelter nearby for the night instead of walking home
HIDE_RANGE = 30    # tiles: buildings this close can be run into to hide
DIRS = {"N": (0, -1), "NE": (1, -1), "E": (1, 0), "SE": (1, 1), "S": (0, 1), "SW": (-1, 1), "W": (-1, 0), "NW": (-1, -1)}


def dir8(dx, dy):
    """Compass direction of (dx, dy) with +y south, matching the mod's dir8."""
    t = 0.4142
    ns = "N" if dy < -t * abs(dx) else ("S" if dy > t * abs(dx) else "")
    ew = "E" if dx > t * abs(dy) else ("W" if dx < -t * abs(dy) else "")
    return (ns + ew) or "HERE"


def _obj(v):
    """The mod's JSON encoder writes empty tables as []; treat those as empty objects."""
    return v if isinstance(v, dict) else {}


@dataclass
class Memory:
    """What the bridge remembers between percepts (the mod keeps its own per-save memory too)."""
    recent: deque = field(default_factory=lambda: deque(maxlen=8))
    last_event_id: int = 0
    last_health: float | None = None
    unreachable: set = field(default_factory=set)   # ids (or "x,y") of buildings we couldn't get into
    # target "x,y" -> building id. The mod picks a random free square in a building each scan, so in game
    # one locked house came back four times under four different targets.
    target_ids: dict = field(default_factory=dict)
    explore_dir: str | None = None
    failed_dirs: dict = field(default_factory=dict)  # heading -> times it failed
    last_task: tuple | None = None                   # (seq, status) already recorded

    def note(self, raw, text):
        t = raw.get("time", {})
        self.recent.append(f"{t.get('hour', 0):02d}:{t.get('min', 0):02d} {text}")

    def update(self, raw):
        for ev in raw.get("events") or []:
            if ev.get("id", 0) > self.last_event_id:
                self.last_event_id = ev["id"]
                self.recent.append(f"{ev.get('t', '')} {ev.get('msg', '')}")
        hp = raw.get("health")
        if hp is not None and self.last_health is not None and hp < self.last_health - 4:
            self.note(raw, f"got hurt ({self.last_health:.0f} -> {hp:.0f} health)")
        if hp is not None:
            self.last_health = hp
        task = raw.get("task") or {}
        key = (task.get("seq"), task.get("status"))
        if task.get("status") in ("done", "failed") and key != self.last_task:
            self.last_task = key
            if task.get("status") == "failed" and task.get("target"):
                if task.get("goal") in ("loot_building", "hide"):
                    self.unreachable.add(self.target_ids.get(task["target"], task["target"]))
                elif task.get("goal") == "explore":
                    dx, dy = (float(v) for v in task["target"].split(","))
                    heading = dir8(dx, dy)
                    self.failed_dirs[heading] = self.failed_dirs.get(heading, 0) + 1


@dataclass
class Situation:
    percept: dict          # snapshot-shaped percept for rules.py / prompt.py
    legal: list            # goal ids that can be carried out right now
    args: dict             # goal id -> (a1, a2, a3) for the intent line
    threat: dict           # numbers the bridge uses to notice a changed situation
    raw: dict


def time_text(t):
    h, m = t.get("hour", 12), t.get("min", 0)
    dawn, dusk = t.get("dawn") or 6, t.get("dusk") or 20
    if not (3 <= dawn <= 10 and 15 <= dusk <= 23):   # older mod versions sent GameTime's stale 12 and 3
        dawn, dusk = 6, 21
    mins, dusk_m = h * 60 + m, round(dusk * 60)
    if mins >= dusk_m + 60 or mins < dawn * 60:
        period = "night (dark)"
    elif mins >= dusk_m:
        period = "dusk"
    elif dusk_m - mins <= 60:
        period = f"sunset in {dusk_m - mins} min"
    elif h < 12:
        period = "morning"
    elif h < 17:
        period = "afternoon"
    else:
        period = "evening"
    return f"Day {t.get('day', 1)} {h:02d}:{m:02d}, {period}"


def weather_text(w):
    rain, fog = w.get("rain", 0), w.get("fog", 0)
    sky = "heavy rain" if rain > 0.5 else ("rain" if rain > 0.05 else ("fog" if fog > 0.5 else "dry"))
    return f"{sky}, {w.get('temp', 20):.0f}C"


def building_kind(rooms):
    rooms = set(rooms or [])
    if rooms & HOUSE_ROOMS:
        return "house"
    return next(iter(sorted(rooms)), "building")


def zombie_groups(zombies):
    """Group zombies by compass direction and distance band, nearest group first."""
    groups = {}
    for z in zombies:
        d = z["d"]
        band = 5 if d <= 5 else 10 if d <= 10 else 20 if d <= 20 else 40
        key = (dir8(z["dx"], z["dy"]), band)
        g = groups.setdefault(key, {"count": 0, "dist": d, "dir": key[0], "chasing": 0, "seen": 0})
        g["count"] += 1
        g["dist"] = min(g["dist"], d)
        g["chasing"] += bool(z.get("chasing"))
        g["seen"] += bool(z.get("seen"))
    out = []
    for g in sorted(groups.values(), key=lambda g: g["dist"]):
        state = "chasing you" if g["chasing"] else ("wandering" if g["seen"] else "out of sight, heard nearby")
        out.append({"count": g["count"], "dist": round(g["dist"]), "dir": g["dir"], "state": state})
    return out[:6]


def _weapon_text(w):
    if not w:
        return "none (fists)"
    pct = round(100 * w["cond"] / w["max"]) if w.get("max") else 0
    return f"{w['name']} ({pct}%)" if w.get("melee") else f"{w['name']} (gun, {pct}%)"


def _inventory(inv, raw_rags=False, cans=0):
    inv = _obj(inv)
    food = []
    for f in inv.get("food") or []:
        if f.get("rotten"):
            food.append(f"rotten {f['name']}")
        elif f.get("edible"):
            food.append(f["name"])
        else:
            food.append(f"{f['name']} (needs cooking or opening)")
    drink = [f"{w['name']} {round(w['amount'] * 10)}/{round(w['cap'] * 10)}" for w in inv.get("water") or []]
    medical = [m["name"] for m in inv.get("medical") or []]
    if isinstance(raw_rags, dict):
        medical.append(f"you can tear your {raw_rags.get('name', 'shirt')} into bandages"
                       + (" (take it off first)" if raw_rags.get("worn") else ""))
    elif raw_rags:
        medical.append("a spare shirt to tear into bandages")
    weapons = [f"{w['name']} ({round(100 * w['cond'] / w['max']) if w.get('max') else 0}%)" for w in inv.get("weapons") or []]
    if cans:
        food = [f.replace("(needs cooking or opening)", "(can, you can open it)") if "Can" in f or "Tin" in f else f
                for f in food]
    out = {"food": food, "drink": drink, "medical": medical}
    if weapons:
        out["weapons"] = weapons
    return out


def choose_explore(raw, mem, rng=random):
    """Pick a heading for `explore`: away from zombies, not back the way we came, not where walking failed.

    Doesn't change `mem`: the bridge records the heading in `mem.explore_dir` only when it sends it.
    """
    zs = raw.get("zombies") or []
    scores = {}
    for name, (ux, uy) in DIRS.items():
        s = rng.random() * 0.3
        for z in zs:
            if z["d"] < 40 and dir8(z["dx"], z["dy"]) == name:
                s -= 2.0 / (z["d"] + 5)
        if mem.explore_dir == name:
            s += 0.4
        if mem.explore_dir and DIRS[mem.explore_dir] == (-ux, -uy):
            s -= 0.6
        s -= 0.8 * mem.failed_dirs.get(name, 0)
        scores[name] = s
    best = max(scores, key=scores.get)
    ux, uy = DIRS[best]
    scale = 40 / math.hypot(ux, uy)
    return best, (round(ux * scale), round(uy * scale), 0)


CROWDED = 3   # zombies within 8 tiles of a building that make it a bad place to go


def crowd_at(raw, x, y, radius=8):
    """Zombies (of the ones the AI knows about) within `radius` tiles of the map square (x, y)."""
    pos = raw.get("pos") or {}
    bx, by = x - pos.get("x", 0), y - pos.get("y", 0)
    return sum(1 for z in raw.get("zombies") or [] if math.hypot(z["dx"] - bx, z["dy"] - by) < radius)


def hide_target(raw, mem):
    """The building to run into when hiding from outside: close, and not where the zombies are."""
    best, best_cost = None, None
    for b in raw.get("buildings") or []:
        if b["d"] > HIDE_RANGE or b["id"] in mem.unreachable or f"{b['tx']},{b['ty']}" in mem.unreachable:
            continue
        cost = b["d"] + 6 * crowd_at(raw, b["tx"], b["ty"])
        if best_cost is None or cost < best_cost:
            best, best_cost = b, cost
    return best


def home_text(raw):
    home = raw.get("home")
    if not home:
        return None
    if home.get("here"):
        return "you are at home base"
    far = " (far: shelter nearby tonight)" if home["d"] > HOME_FAR else ""
    return f"home base {home['d']:.0f} tiles {home['dir']}{far}"


def summarize(raw, mem, rng=random):
    t = raw.get("time", {})
    moods = {MOODLES[k]: v for k, v in _obj(raw.get("moodles")).items() if k in MOODLES}
    bld = raw.get("bld")
    zombies = raw.get("zombies") or []
    buildings = raw.get("buildings") or []
    water = raw.get("water") or []
    inv = _obj(raw.get("inv"))

    # where am I
    if bld:
        where = f"inside {'home base' if bld.get('home') else 'a building'}, {raw.get('room') or 'a room'}"
        bits = ["home base"] if bld.get("home") else []
        bits.append(f"{bld['doorsOpen']} door{'s' if bld['doorsOpen'] != 1 else ''} OPEN" if bld["doorsOpen"] else "doors closed")
        if bld["windowsOpen"]:
            bits.append(f"{bld['windowsOpen']} window{'s' if bld['windowsOpen'] != 1 else ''} open")
        if bld.get("curtainsOpen"):
            bits.append(f"{bld['curtainsOpen']} curtain{'s' if bld['curtainsOpen'] != 1 else ''} open")
        if bld.get("smashed"):
            bits.append(f"{bld['smashed']} window{'s' if bld['smashed'] != 1 else ''} smashed")
        if not bld["doorsOpen"] and not bld["windowsOpen"] and not bld.get("smashed"):
            bits.append("closed up (secured)")
        bits.append(f"containers searched {bld['searched']}/{bld['containers']} on this floor")
        if bld.get("food"):
            bits.append(f"{bld['food']} food item{'s' if bld['food'] != 1 else ''} in the cupboards here")
        bits.append("has a bed" if bld.get("bed") else "no bed")
        building = ", ".join(bits)
    else:
        where = "outside"
        near = next((b for b in buildings if b["d"] <= 10), None)
        if near:
            where += f", {building_kind(near.get('rooms'))} with closed doors {near['d']:.0f} tiles {near['dir']}"
        building = None

    # wounds, written the way rules.py and the prompt expect
    wounds = []
    for w in raw.get("wounds") or []:
        flags = [("BLEEDING" if f == "bleeding" else f) for f in w.get("flags", [])]
        wounds.append(f"{w['part']}: {', '.join(flags)}")

    here_id = bld["id"] if bld else None
    # a building with zombies standing round it isn't worth walking into (the second death: 7 round a barn)
    unlooted = [b for b in buildings if not b.get("looted") and b["id"] != here_id
                and b["id"] not in mem.unreachable and f"{b['tx']},{b['ty']}" not in mem.unreachable
                and crowd_at(raw, b["tx"], b["ty"]) < CROWDED]
    looted = [b for b in buildings if b.get("looted")]
    clean_water = [w for w in water if not w.get("tainted")]
    task = raw.get("task") or {}

    percept = {
        "time": time_text(t),
        "weather": weather_text(raw.get("weather", {})),
        "where": where,
        "building": building,
        "health": round(raw.get("health", 100)),
        "moodles": moods,
        "wounds": wounds,
        "weapon": _weapon_text(raw.get("weapon")),
        "inventory": _inventory(inv, raw.get("rags"), raw.get("cans") or 0),
        "weight": f"{raw.get('weight', 0):.1f}/{raw.get('maxWeight', 1):.0f}",
        "zombies": zombie_groups(zombies),
        "home": home_text(raw),
        "water": [f"{w['name']} {w['d']:.0f} tiles {w['dir']} ({'taps on' if not w.get('tainted') else 'tainted'})" for w in water],
        "unlooted": [f"{building_kind(b.get('rooms'))} {b['d']:.0f} tiles {b['dir']}" for b in unlooted[:4]],
        "looted": [f"{building_kind(b.get('rooms'))} {b['d']:.0f} tiles {b['dir']}" for b in looted[:3]],
        "recent": list(mem.recent)[-5:],
        "last_goal": (f"{task['goal']}: {task.get('status', '')}" + (f" ({task['msg']})" if task.get("msg") else ""))
                     if task.get("goal") else None,
    }

    # which goals the mod can carry out right now, with their arguments
    # a zombie that's chasing you is a target even when it's behind you or round a corner
    targets = [z for z in zombies if z.get("seen") or z.get("chasing")]
    args = {}
    if any(z["d"] <= 15 for z in targets):
        args["fight"] = ()
    if any(z["d"] <= 20 for z in zombies):   # the mod's flee ends at 22 tiles; offered further out it ends at once
        args["flee"] = ()
    if bld:
        args["hide"] = ()
    elif (shelter := hide_target(raw, mem)) is not None:
        args["hide"] = (shelter["tx"], shelter["ty"], shelter["tz"])
        mem.target_ids[f"{shelter['tx']},{shelter['ty']}"] = shelter["id"]
    if bld:
        if bld["doorsOpen"] or bld["windowsOpen"] or bld.get("curtainsOpen"):
            # where we stand: the mod finds the building from it even if we've just stepped out of a door
            pos = raw.get("pos") or {}
            args["secure_building"] = (math.floor(pos.get("x", 0)), math.floor(pos.get("y", 0)), pos.get("z", 0))
        if bld["searched"] < bld["containers"]:
            args["loot_here"] = ()
    if inv.get("water") or clean_water:
        args["drink"] = ()
    if any(f.get("edible") for f in inv.get("food") or []) or (bld or {}).get("food") or raw.get("cans"):
        args["eat"] = ()
    if any(f == "bleeding" or f in ("bite", "deep wound", "laceration")
           for w in raw.get("wounds") or [] if "bandaged" not in w.get("flags", []) for f in w.get("flags", [])) \
            and (any(m.get("kind") == "bandage" for m in inv.get("medical") or []) or raw.get("rags")):
        args["bandage"] = ()   # a spare shirt tears into rags
    if unlooted:
        b = unlooted[0]
        args["loot_building"] = (b["tx"], b["ty"], b["tz"])
        mem.target_ids[f"{b['tx']},{b['ty']}"] = b["id"]
    held = (raw.get("weapon") or {}).get("score", 0) if (raw.get("weapon") or {}).get("melee") else 0
    if any(w.get("score", 0) > held * 1.1 for w in inv.get("weapons") or []):
        args["equip_weapon"] = ()
    if moods.get("endurance", 0) >= 1 or moods.get("panic", 0) >= 1:
        args["rest"] = ()
    home = raw.get("home")
    if home and not home.get("here"):
        args["retreat_home"] = (home["x"], home["y"], home["z"])
    # the game refuses to sleep with zombies in sight or while panicking
    seen_near = any((z.get("seen") or z.get("chasing")) and z["d"] <= 25 for z in zombies)
    if bld and moods.get("tired", 0) >= 1 and not seen_near and moods.get("panic", 0) == 0:
        args["sleep"] = ()
    junk = _obj(raw.get("junk"))
    weight, cap = raw.get("weight", 0), raw.get("maxWeight", 1) or 1
    if (junk.get("drop", 0) >= 0.5 and weight >= 0.85 * cap) or junk.get("store", 0) >= 1:
        args["drop_weight"] = ()
    heading, args["explore"] = choose_explore(raw, mem, rng)
    args["wait"] = ()

    nearest = min((z["d"] for z in zombies), default=None)
    threat = {
        "nearest": nearest,
        "chasing": sum(1 for z in zombies if z.get("chasing") and z["d"] <= 20),
        "within10": sum(1 for z in zombies if z["d"] <= 10),
        "bleeding": any("bleeding" in w.get("flags", []) for w in raw.get("wounds") or []),
        "explore_heading": heading,
    }
    return Situation(percept=percept, legal=list(args), args=args, threat=threat, raw=raw)
