"""What the agent is rewarded for (the owner's rules of 2026-10-12; research in docs/REWARD_RESEARCH.md).

Staying alive is a big, steady gain, dying costs most, and feeling bad (hunger, pain, panic and the other moodles)
costs nothing in itself. Per stretch between two observations of the same life:

  alive       +1 per game minute survived (60 a game hour)
  kills       +10 per zombie killed
  progress    +3 the first time each kind of item is in the bag this life, +5 the first time it's inside
              each building, +0.5 the first time it looks into each container
  infection   -1000 when the Knox infection happens: it kills 2-3 days later, beyond what the network looks ahead,
              so the death is charged then, and the death itself costs nothing more
  death       -1000 (less whatever an infection already charged)

These decide what is truly best. On top of them, the body's condition counts through a value Φ of each moment,
and the reward is its change (potential-based shaping, Ng, Harada & Russell 1999):

  Φ = 2 x (health - 100)       getting hurt costs, healing pays the same back
      - 10 x untreated wounds   body parts with an open wound and no bandage
      + 2000 x protection       the protection panel's bite and scratch defence, averaged over the 17 body parts
                                (0-1): putting clothing on pays what taking it off costs, and a hole, a patch or a
                                worn-out garment costs its share as it happens. Shoes are worth about 35, jeans 88.
      + 100 x weapon            a melee weapon in the hands, by its damage: min(1, max damage / 1.5), so a hatchet
                                100, a crowbar 77, a baseball bat 73, a kitchen knife 35, a pen 7. Unequipping it
                                costs what equipping it paid.
  and Φ is 0 once dead.

Any loop that ends where it started earns nothing from Φ, and Ng et al. prove such terms never change which play
is best: they are hints that make learning faster. The infection is a real event instead, so that a bite counts
as the death it is; it can't be undone, so there is nothing to farm.

Records from before gym 0.4.20 have no infection flag: for them the infection is the expected chance from the
zombie wounds seen (scratch 7%, laceration 25%, bite 100%: BodyPart.setScratched, setCut, SetBitten in 42.21).

Version 1 (to 2026-10-12) charged every bad moodle per minute and death only 20, so dying early scored best.
Version 2 (2026-10-12) counted health and wounds only as losses and death as the only real cost. Version 3
(2026-10-12) had protection at 100 and no weapon: a garment was worth a few points, a few game minutes of being
alive, and the network kept taking its clothes off; version 4 (the owner's decision, 2026-10-12 evening) is
x20 on clothing and adds the weapon. `rescore` and learn.Data turn a logged record of any version into the current
reward, so training learns it from all the experience.
"""

VERSION = 4

ALIVE_PER_MIN = 1.0
KILL = 10.0
NEW_ITEM = 3.0
NEW_BUILDING = 5.0
NEW_CONTAINER = 0.5
DEATH = -1000.0

PER_HEALTH = 2.0      # Φ per health point below 100 (0 at full health, so a healthy body costs nothing to keep)
PER_UNTREATED = 10.0  # Φ lost per body part with an open wound and no bandage
PROTECTION = 2000.0   # Φ for full bite and scratch cover everywhere (100 in version 3)
WEAPON = 100.0        # Φ for a melee weapon in the hands with at least WEAPON_FULL max damage
WEAPON_FULL = 1.5     # max damage worth the full WEAPON (a hatchet 1.5, a bat 1.1, a kitchen knife 0.52, a pen 0.1)

OPEN_WOUNDS = ("bleeding", "scratch", "laceration", "bite", "deep wound")
INFECTION_CHANCE = {"scratch": 0.07, "laceration": 0.25, "bite": 1.0}   # BodyPart.setScratched/setCut/SetBitten

BASE_PARTS = ("alive", "kills", "new_items", "new_building", "new_containers")   # infection and death: from the observations
V1 = {"alive": 0.1, "kills": 1.0, "new_items": 0.3, "new_building": 0.5, "new_containers": 0.05}


def _d(v):
    return v if isinstance(v, dict) else {}


def _l(v):
    return v if isinstance(v, list) else []


def _num(v, default=0.0):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default


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


def body(obs):
    """What Φ and the infection are worked out from in one observation, or None without one (creation, death):
    {health, untreated, protection 0-1, weapon 0-1, knox True/False/None, zombie_wounds: [(part, kind)]}."""
    obs = _d(obs)
    if obs.get("dead") or obs.get("health") is None:
        return None
    untreated, zw = 0, []
    for w in _l(obs.get("body")):
        flags = _l(_d(w).get("flags"))
        if "bandaged" not in flags and any(f in OPEN_WOUNDS for f in flags):
            untreated += 1
        zw += [(_d(w).get("part"), f) for f in flags if f in INFECTION_CHANCE]
    prot = _l(obs.get("protection"))
    cover = sum(min(100.0, _num(_d(x).get("bite"))) + min(100.0, _num(_d(x).get("scratch"))) for x in prot)
    return {"health": _num(obs.get("health")), "untreated": untreated,
            "protection": cover / (200.0 * len(prot)) if prot else 0.0, "weapon": weapon(obs.get("held")),
            "knox": obs["knox"] if isinstance(obs.get("knox"), bool) else None, "zombie_wounds": zw}


def weapon(held):
    """How much the item in the hands counts as a weapon (0-1): a melee weapon by its max damage (the gym's item
    record: cat "weapon", dmg, ranged). A gun counts 0: without the aiming and ammo actions it is no use yet."""
    held = _d(held)
    if held.get("cat") != "weapon" or held.get("ranged") is True:
        return 0.0
    return max(0.0, min(1.0, _num(held.get("dmg")) / WEAPON_FULL))


def infected(prev_infected, prev_body, cur_body):
    """The infection (0-1) after `cur_body`: the game's flag when the record has it, else the chance carried so far
    combined with the infection chance of each zombie wound that wasn't there before. It never goes down: the
    infection has no cure."""
    if cur_body["knox"] is not None:
        return max(prev_infected, 1.0 if cur_body["knox"] else 0.0)
    p = prev_infected
    seen = {tuple(w) for w in prev_body["zombie_wounds"]} if prev_body else set()   # lists after a JSON round trip
    for part, kind in {tuple(w) for w in cur_body["zombie_wounds"]} - seen:
        p = 1 - (1 - p) * (1 - INFECTION_CHANCE[kind])
    return p


def potential_parts(b):
    """Φ of one moment, by part (they sum to Φ); all zero once dead (b None)."""
    if b is None:
        return {"health": 0.0, "wounds": 0.0, "protection": 0.0, "weapon": 0.0}
    return {"health": PER_HEALTH * (min(b["health"], 100.0) - 100.0), "wounds": -PER_UNTREATED * b["untreated"],
            "protection": PROTECTION * b["protection"], "weapon": WEAPON * b.get("weapon", 0.0)}


def potential(b):
    return sum(potential_parts(b).values())


def step(prev, cur, progress, searched=0, inf=0.0):
    """Reward for what happened between observation `prev` and observation `cur` (same life), with the change in Φ
    undiscounted (training discounts it by the game time in between). `inf` is the infection (0-1) after `prev`.
    `searched` is how many new containers the last action looked into. Returns (total, parts, infection after)."""
    parts = {}
    pb = body(prev)
    before = potential_parts(pb)
    if cur.get("dead"):
        parts["death"] = DEATH * (1 - inf)   # an infection already charged its share
        kills = (cur.get("kills") or 0) - (prev.get("kills") or 0)
        if kills > 0:
            parts["kills"] = KILL * kills
        parts["body"] = -sum(before.values())   # Φ is 0 once dead
        parts = {k: round(v, 4) for k, v in parts.items() if abs(v) > 1e-9}
        return round(sum(parts.values()), 4), parts, inf
    minutes = max(0.0, ((cur.get("t") or {}).get("age", 0) - (prev.get("t") or {}).get("age", 0)) * 60)
    minutes = min(minutes, 24 * 60)   # a day asleep at most; guards against a clock jump
    parts["alive"] = ALIVE_PER_MIN * minutes
    cb = body(cur)
    after_inf = infected(inf, pb, cb) if cb else inf
    if after_inf > inf:
        parts["infection"] = DEATH * (after_inf - inf)
    if pb and cb:
        after = potential_parts(cb)
        for k in after:
            parts[k] = after[k] - before[k]
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
    parts = {k: round(v, 4) for k, v in parts.items() if abs(v) > 1e-9}
    return round(sum(parts.values()), 4), parts, after_inf


def rescore(rec):
    """A logged record's alive, kills and progress reward under the current weights, and the game minutes it covers.
    Training adds the infection, the death and the change in Φ itself, from the observations of each life in order
    (learn.Data). Versions 2 to 4 logged these parts at today's weights; version 1 records (no `reward_v`) are
    converted. A record the agent marked 'resumed' earns nothing."""
    if rec.get("resumed"):
        return 0.0, 0.0
    parts = _d(rec.get("parts"))
    if rec.get("reward_v") in (2, 3, 4):
        return round(sum(_num(parts.get(k)) for k in BASE_PARTS), 4), _num(parts.get("alive")) / ALIVE_PER_MIN
    if rec.get("dead"):
        return round(KILL * _num(parts.get("kills")) / V1["kills"], 4), 0.0
    minutes = _num(parts.get("alive")) / V1["alive"]
    r = ALIVE_PER_MIN * minutes + KILL * _num(parts.get("kills")) / V1["kills"]
    r += NEW_ITEM * _num(parts.get("new_items")) / V1["new_items"]
    r += NEW_BUILDING * _num(parts.get("new_building")) / V1["new_building"]
    r += NEW_CONTAINER * _num(parts.get("new_containers")) / V1["new_containers"]
    return round(r, 4), minutes


def start_life(first_obs, progress):
    """Count what a new character starts with, so its own clothes don't earn 'new item' bonuses. Returns the
    infection it starts with (0 unless the record's flag says it's infected)."""
    for it in _l(first_obs.get("inv")) + ([first_obs["held"]] if isinstance(first_obs.get("held"), dict) else []):
        key = _item_key(it)
        if key:
            progress.items.add(key)
    b = _d(first_obs.get("where")).get("building")
    if b:
        progress.buildings.add(b)
    fb = body(first_obs)
    return 1.0 if fb and fb["knox"] else 0.0
