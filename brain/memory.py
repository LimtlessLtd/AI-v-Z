"""Long-term memory for the planner: a map of every building the AI has seen, its diary, lessons.

Kept per character in logs/memory/<save>__<name>.json, so it survives bridge restarts. Lessons are per save
(logs/memory/<save>__lessons.json): a new character after a death starts with what the last one learned.
"""

import json
import math
import os
import re
import time
from pathlib import Path

from .percept import dir8

HOUSE_ROOMS = {"bedroom", "kitchen", "bathroom", "livingroom", "hall", "laundry", "diningroom"}
# room-name fragments -> what the building is, most specific first
KINDS = [
    ("pharmac", "pharmacy"), ("grocer", "grocery store"), ("zippee", "convenience store"),
    ("gasstore", "gas station"), ("fossoil", "gas station"), ("gas", "gas station"),
    ("tool", "hardware store"), ("hardware", "hardware store"), ("gun", "gun store"), ("police", "police station"),
    ("medic", "clinic"), ("clinic", "clinic"), ("hospital", "hospital"), ("liquor", "liquor store"),
    ("spiffo", "restaurant"), ("restaurant", "restaurant"), ("burger", "restaurant"), ("pizza", "restaurant"),
    ("diner", "restaurant"), ("cafe", "cafe"), ("bar", "bar"), ("cloth", "clothes store"), ("book", "bookstore"),
    ("warehouse", "warehouse"), ("classroom", "school"), ("school", "school"), ("church", "church"),
    ("motel", "motel"), ("hotel", "hotel"), ("mechanic", "garage"), ("office", "office"),
    ("farm", "farm building"), ("barn", "barn"), ("shed", "shed"),
]


def building_kind(rooms):
    rooms = [r.lower() for r in rooms or []]
    for frag, kind in KINDS:
        if any(frag in r for r in rooms):
            return kind
    if set(rooms) & HOUSE_ROOMS:
        return "house"
    if any("storage" in r for r in rooms):
        return "storage building"
    return rooms[0] if rooms else "building"


def _slug(text):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(text or "unknown"))[:60]


class WorldMemory:
    def __init__(self, root, save, name):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.save_id, self.name = save, name
        self.path = self.root / f"{_slug(save)}__{_slug(name)}.json"
        self.lessons_path = self.root / f"{_slug(save)}__lessons.json"
        self.data = {"name": name, "save": save, "places": {}, "diary": [], "plan": None, "aims": [], "today": []}
        self.lessons = []
        self._dirty, self._saved_at = False, 0.0
        self.load()

    # ------------------------------------------------------------------ files
    def load(self):
        try:
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        try:
            self.lessons = json.loads(self.lessons_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.lessons = []

    def _write(self, path, obj):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)

    def save(self, force=False):
        if not (self._dirty or force) or (not force and time.time() - self._saved_at < 20):
            return
        self._write(self.path, self.data)
        self._dirty, self._saved_at = False, time.time()

    def add_lesson(self, text):
        self.lessons = (self.lessons + [text])[-8:]
        self._write(self.lessons_path, self.lessons)

    # ------------------------------------------------------------------ observing the world
    @property
    def places(self):
        return self.data["places"]

    def observe(self, raw, unreachable=()):
        """Fold one percept into the map: buildings seen, looted, unreachable; today's events."""
        day = (raw.get("time") or {}).get("day", 1)
        pos = raw.get("pos") or {}
        for b in raw.get("buildings") or []:
            if pos and math.hypot(b["tx"] - pos.get("x", 0), b["ty"] - pos.get("y", 0)) > 90:
                continue   # the mod scans 60 tiles; anything further is a stale scan from before a respawn
            p = self.places.setdefault(b["id"], {"found": []})
            rooms = b.get("rooms") or p.get("rooms") or []
            p.update(kind=building_kind(rooms), rooms=rooms, x=b["tx"], y=b["ty"], z=b.get("tz", 0), seen_day=day)
            if b.get("looted"):
                p["looted"] = True
            self._dirty = True
        bld = raw.get("bld")
        if bld and bld.get("looted") and bld["id"] in self.places and not self.places[bld["id"]].get("looted"):
            self.places[bld["id"]]["looted"] = True
        for key in unreachable:
            if key in self.places and not self.places[key].get("locked"):
                self.places[key]["locked"] = True
                self._dirty = True

    def note_event(self, raw, msg):
        """Called for each new game event; remembers what was found where, and the day's story."""
        t = raw.get("time") or {}
        stamp = f"{t.get('hour', 0):02d}:{t.get('min', 0):02d}"
        today = self.data["today"]
        if today and today[0].get("day") != t.get("day"):
            today.clear()
        today.append({"day": t.get("day"), "t": stamp, "msg": msg})
        del today[:-40]
        bld = raw.get("bld")
        if msg.startswith("took ") and bld and bld["id"] in self.places:
            found = self.places[bld["id"]].setdefault("found", [])
            for item in msg[5:].split(", "):
                if item not in found:
                    found.append(item)
            del found[:-8]
        self._dirty = True

    # ------------------------------------------------------------------ for the planner
    def labelled_places(self, raw, limit=14):
        """The places worth telling the planner about, nearest first, as (label, place-id, text)."""
        pos = raw.get("pos") or {}
        px, py = pos.get("x", 0), pos.get("y", 0)
        here = (raw.get("bld") or {}).get("id")
        home_id = (raw.get("home") or {}).get("id")
        rows = []
        for pid, p in self.places.items():
            if "x" not in p:
                continue
            d = math.hypot(p["x"] - px, p["y"] - py)
            rows.append((d, pid, p))
        rows.sort(key=lambda r: r[0])
        unlooted = [r for r in rows if not r[2].get("looted") and not r[2].get("locked")]
        shops = [r for r in rows if r[2].get("kind") not in ("house", "building") and r not in unlooted[:8]]
        looted = [r for r in rows if r[2].get("looted") and r[2].get("found")]
        picked, seen = [], set()
        for group, n in ((unlooted, 8), (shops, 4), (looted, 3)):
            for r in group[:n]:
                if r[1] not in seen:
                    seen.add(r[1])
                    picked.append(r)
        picked.sort(key=lambda r: r[0])
        out = []
        for i, (d, pid, p) in enumerate(picked[:limit], 1):
            bits = [f"{p.get('kind', 'building')} {d:.0f} tiles {dir8(p['x'] - px, p['y'] - py)}"]
            if pid == here:
                bits.append("you are here")
            if pid == home_id:
                bits.append("your home base")
            if p.get("locked"):
                bits.append("couldn't get in")
            if p.get("zombies"):
                bits.append(f"zombies all round it on day {p['zombies']}")
            bits.append("searched" if p.get("looted") else "not searched yet")
            if p.get("found"):
                bits.append("found there: " + ", ".join(p["found"][-4:]))
            out.append((f"P{i}", pid, ", ".join(bits)))
        return out
