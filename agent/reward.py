"""What the agent is rewarded for: staying alive and making progress (chosen 2026-10-09).

The reward says what hurts and what counts as progress, never what to do about it. Between two
observations of the same life:

  alive       +0.1 per game minute survived
  health      +0.2 per health point gained (and -0.2 per point lost)
  discomfort  -0.02 x level^2 per game minute for each bad moodle (hunger, thirst, tiredness, panic, pain,
              sickness, cold, heat, wet, stress), and -0.1 per game minute per bleeding wound. A body that
              feels bad is the only hint that eating, drinking, sleeping or bandaging matter.
  kills       +1 per zombie killed
  progress    +0.3 the first time each kind of item is in the bag this life, +0.5 the first time it's inside
              each building, +0.05 the first time it looks into each container
  death       -20

Every part is logged separately (logs/experience), so the weights can be changed and old experience
re-scored later.
"""

ALIVE_PER_MIN = 0.1
HEALTH = 0.2
DISCOMFORT = 0.02
BLEEDING_PER_MIN = 0.1
KILL = 1.0
NEW_ITEM = 0.3
NEW_BUILDING = 0.5
NEW_CONTAINER = 0.05
DEATH = -20.0

BAD_MOODLES = ("hungry", "thirst", "tired", "panic", "pain", "sick", "hypothermia", "hyperthermia", "wet", "stress")


def _d(v):
    return v if isinstance(v, dict) else {}


def _l(v):
    return v if isinstance(v, list) else []


class LifeProgress:
    """What this life has already been rewarded for (the 'first time' bonuses)."""

    def __init__(self):
        self.items, self.buildings, self.containers = set(), set(), 0


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
    if dh:
        parts["health"] = HEALTH * dh
    # discomfort over the interval: the average of the levels at both ends
    pm, cm = _d(prev.get("moodles")), _d(cur.get("moodles"))
    pain = sum(((pm.get(k, 0) ** 2 + cm.get(k, 0) ** 2) / 2) for k in BAD_MOODLES)
    if pain and minutes:
        parts["discomfort"] = -DISCOMFORT * pain * minutes
    bleeding = sum(1 for w in _l(cur.get("body")) if "bleeding" in _l(w.get("flags")) and "bandaged" not in _l(w.get("flags")))
    if bleeding and minutes:
        parts["bleeding"] = -BLEEDING_PER_MIN * bleeding * minutes
    kills = (cur.get("kills") or 0) - (prev.get("kills") or 0)
    if kills > 0:
        parts["kills"] = KILL * kills
    new_items = 0
    for it in _l(cur.get("inv")) + ([cur["held"]] if isinstance(cur.get("held"), dict) else []):
        key = it.get("type") or it.get("name")
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


def start_life(first_obs, progress):
    """Count what a new character starts with, so its own clothes don't earn 'new item' bonuses."""
    for it in _l(first_obs.get("inv")) + ([first_obs["held"]] if isinstance(first_obs.get("held"), dict) else []):
        key = it.get("type") or it.get("name")
        if key:
            progress.items.add(key)
    b = _d(first_obs.get("where")).get("building")
    if b:
        progress.buildings.add(b)
