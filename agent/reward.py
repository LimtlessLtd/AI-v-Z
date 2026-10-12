"""What the agent is rewarded for (the owner's rule, 2026-10-12): staying alive is a big, steady gain; being
damaged or hurt costs; dying costs so much that it outweighs everything else. Feeling bad (hunger, thirst,
pain, panic and the other moodles) costs nothing in itself: it matters only through the damage it leads to.

The reward says what hurts and what counts as progress, never what to do about it. Between two
observations of the same life:

  alive       +1 per game minute survived (60 a game hour)
  hurt        -2 per health point lost (healing earns nothing back)
  wounds      for each new wound the body shows: scratch or glass -10, laceration -20, deep wound -30,
              bite or fracture -50
  kills       +10 per zombie killed
  progress    +3 the first time each kind of item is in the bag this life, +5 the first time it's inside
              each building, +0.5 the first time it looks into each container
  death       -1000

Losing all 100 health costs 200 and a life of 16 game hours earns 960, so a death costs more than either.
Kills and progress keep the same size next to being alive as in version 1.

Version 1 (2026-10-09 to 2026-10-12) paid 0.1 a game minute alive, charged every bad moodle each minute
(discomfort) and death only 20, so a long uncomfortable life scored worse than an early death (BACKLOG.md
N1). Every part is logged separately, and `rescore` turns a record logged under version 1 into the current
weights, so training learns the current reward from all the experience.
"""

VERSION = 2

ALIVE_PER_MIN = 1.0
HURT_PER_HP = 2.0
WOUNDS = {"scratch": 10.0, "glass": 10.0, "laceration": 20.0, "deep wound": 30.0, "bite": 50.0, "fracture": 50.0}
KILL = 10.0
NEW_ITEM = 3.0
NEW_BUILDING = 5.0
NEW_CONTAINER = 0.5
DEATH = -1000.0

# version 1's weights, to read its logged parts back as counts
V1 = {"alive": 0.1, "health": 0.2, "kills": 1.0, "new_items": 0.3, "new_building": 0.5, "new_containers": 0.05}


def _d(v):
    return v if isinstance(v, dict) else {}


def _l(v):
    return v if isinstance(v, list) else []


def _item_key(it):
    """What counts as a kind of item, or None. B42 keeps each wound as a hidden 'Wound_...' item in the
    inventory; before gym 0.3.0 those reached the observation and a bite paid the new-item bonus."""
    key = it.get("type") or it.get("name")
    if not key or str(key).startswith(("Wound_", "Base.Wound_")) or str(it.get("name", "")).startswith("Base.Wound_"):
        return None
    return key


class LifeProgress:
    """What this life has already been rewarded for (the 'first time' bonuses)."""

    def __init__(self):
        self.items, self.buildings, self.containers = set(), set(), 0


def _wounds_of(obs):
    return {(w.get("part"), f) for w in _l(_d(obs).get("body")) for f in _l(w.get("flags")) if f in WOUNDS}


def new_wounds(prev, cur):
    """The cost of the wounds `cur` shows that `prev` didn't, as (body part, kind) pairs. A wound stays listed under
    a bandage, so bandaging one doesn't make it new again; a wound that healed and comes back counts again."""
    return sum(WOUNDS[kind] for _, kind in _wounds_of(cur) - _wounds_of(prev))


def step(prev, cur, progress, searched=0):
    """Reward for what happened between observation `prev` and observation `cur` (same life).

    `searched` is how many new containers the last action looked into. Returns (total, parts)."""
    parts = {}
    if cur.get("dead"):
        parts["death"] = DEATH
        kills = (cur.get("kills") or 0) - (prev.get("kills") or 0)
        if kills > 0:
            parts["kills"] = KILL * kills
        return round(sum(parts.values()), 4), parts
    minutes = max(0.0, ((cur.get("t") or {}).get("age", 0) - (prev.get("t") or {}).get("age", 0)) * 60)
    minutes = min(minutes, 24 * 60)   # a day asleep at most; guards against a clock jump
    parts["alive"] = ALIVE_PER_MIN * minutes
    dh = (cur.get("health") or 0) - (prev.get("health") or 0)
    if dh < 0:
        parts["hurt"] = HURT_PER_HP * dh
    w = new_wounds(prev, cur)
    if w:
        parts["wounds"] = -w
    kills = (cur.get("kills") or 0) - (prev.get("kills") or 0)
    if kills > 0:
        parts["kills"] = KILL * kills
    new_items = 0
    for it in _l(cur.get("inv")) + ([cur["held"]] if isinstance(cur.get("held"), dict) else []):
        key = _item_key(it)
        if key and key not in progress.items:
            progress.items.add(key)
            new_items += 1
    if new_items:
        parts["new_items"] = NEW_ITEM * new_items
    b = _d(cur.get("where")).get("building")
    if b and b not in progress.buildings:
        progress.buildings.add(b)
        parts["new_building"] = NEW_BUILDING
    if searched > 0:
        progress.containers += searched
        parts["new_containers"] = NEW_CONTAINER * searched
    parts = {k: round(v, 4) for k, v in parts.items() if v}
    return round(sum(parts.values()), 4), parts


def rescore(rec, prev_obs=None):
    """A logged decision record's reward under the current weights, and the game minutes it covers (alive).

    Records of this version are taken as logged. Version 1 records (no `reward_v`) are rebuilt from their parts:
    the minutes alive, the health change, kills and first-time counts come back exactly; moodle discomfort and
    bleeding are dropped; new wounds come from comparing the observation with `prev_obs` (the same life's previous
    observation), so without it they count nothing. A record the agent marked 'resumed' earns nothing."""
    if rec.get("resumed"):
        return 0.0, 0.0
    parts = _d(rec.get("parts"))
    if rec.get("reward_v") == VERSION:
        return float(rec.get("reward") or 0.0), parts.get("alive", 0.0) / ALIVE_PER_MIN
    if rec.get("dead"):
        r = DEATH + KILL * parts.get("kills", 0.0) / V1["kills"]
        return round(r, 4), 0.0
    minutes = parts.get("alive", 0.0) / V1["alive"]
    dh = parts.get("health", 0.0) / V1["health"]
    r = ALIVE_PER_MIN * minutes + HURT_PER_HP * min(0.0, dh)
    r += KILL * parts.get("kills", 0.0) / V1["kills"]
    r += NEW_ITEM * parts.get("new_items", 0.0) / V1["new_items"]
    r += NEW_BUILDING * parts.get("new_building", 0.0) / V1["new_building"]
    r += NEW_CONTAINER * parts.get("new_containers", 0.0) / V1["new_containers"]
    if prev_obs and rec.get("obs"):
        r -= new_wounds(prev_obs, rec["obs"])
    return round(r, 4), minutes


def start_life(first_obs, progress):
    """Count what a new character starts with, so its own clothes don't earn 'new item' bonuses."""
    for it in _l(first_obs.get("inv")) + ([first_obs["held"]] if isinstance(first_obs.get("held"), dict) else []):
        key = _item_key(it)
        if key:
            progress.items.add(key)
    b = _d(first_obs.get("where")).get("building")
    if b:
        progress.buildings.add(b)
