"""The baseline: a hand-written utility scorer over percepts and legal goals.

Each legal goal gets a score from general survival rules; the highest score wins (brain/strategy.py).
This is the score to beat for the learning agent.

Caveat: the same person wrote these rules and the benchmark's "sensible" answers, so its score on the
benchmark is optimistic. Judge it on new snapshots or real game logs before trusting it.
"""

import re

LEVEL_WORDS = ("night", "dark")


def _level(p, name):
    return p["moodles"].get(name, 0)


def _condition(text):
    m = re.search(r"\((\d+)%", text or "")
    return int(m.group(1)) if m else 0


def _weight(p):
    m = re.match(r"([\d.]+)/([\d.]+)", p["weight"])
    return (float(m.group(1)), float(m.group(2))) if m else (0.0, 1.0)


def features(p):
    zs = p["zombies"]
    chasing = sum(z["count"] for z in zs if z["dist"] <= 15 and re.search(r"chasing|banging", z["state"]))
    near = sum(z["count"] for z in zs if z["dist"] <= 20)
    # everything within 4 tiles counts, seen or not: in game 7 stood round the AI, only the 3 in front were
    # "chasing", and it picked a fight with a frying pan
    within4 = sum(z["count"] for z in zs if z["dist"] <= 4)
    # A big group anywhere in earshot is a horde. Scattered ones only count when many are close: in game,
    # 16 spread over 22-40 tiles of town (none chasing, none in sight) had the AI "fleeing" on the spot.
    horde = (any(z["count"] >= 10 for z in zs) or sum(z["count"] for z in zs if z["dist"] <= 25) >= 15
             or bool(p.get("noise")))
    # A horde in the distance is a reason to shelter, not to let one zombie chew on you: in game, 40 heard
    # 30 tiles away stopped the AI fighting the single zombie on top of it. Only a close one rules out fighting.
    close = [z for z in zs if z["dist"] <= 20]
    horde_close = any(z["count"] >= 10 for z in close) or sum(z["count"] for z in close) >= 15
    weapon_cond = 0 if "none" in p["weapon"] else _condition(p["weapon"])
    spare = [w for w in p["inventory"].get("weapons", []) if _condition(w) > max(weapon_cond, 30)]
    building = p.get("building") or ""
    time = p["time"].lower()
    weight, cap = _weight(p)
    food = p["inventory"].get("food", [])
    home = p.get("home") or ""
    home_dist = re.search(r"(\d+) tiles", home)
    edible = [f for f in food if "rotten" not in f and "can opener" not in f and "needs" not in f]
    return {
        "chasing": chasing, "near": near, "horde": horde, "horde_close": horde_close,
        "nearest": min((z["dist"] for z in zs), default=999),
        "weapon_cond": weapon_cond, "spare_weapon": bool(spare),
        # armed: up to 3 chasing. Bare hands: one zombie, nothing else close (shove it down, stomp it)
        "can_fight": _level(p, "endurance") <= 1 and ((chasing <= 3 and within4 <= 3 and weapon_cond >= 30)
                                                       or (chasing == 1 and within4 <= 1 and near <= 2)),
        "indoors": p["where"].startswith("inside"),
        "at_home": home.startswith("you are at home"),
        "home_known": bool(home),
        # further than this, walking home at dusk is riskier than closing up a building nearby
        "home_far": bool(home_dist) and int(home_dist.group(1)) > 120,
        "secured": "secured" in building or ("locked" in building and "OPEN" not in building),
        "open_building": "OPEN" in building or "window open" in building or "windows open" in building,
        "unsearched_here": bool(re.search(r"searched (\d+)/(\d+)", building))
                           and int(re.search(r"searched (\d+)/(\d+)", building).group(1))
                           < int(re.search(r"searched (\d+)/(\d+)", building).group(2)),
        "dark": any(w in time for w in LEVEL_WORDS),
        "dusk": "dusk" in time or "sunset" in time,
        "bleeding": any(re.search(r"(?<!not )bleeding", w, re.I) for w in p["wounds"]),
        "overloaded": weight > cap,
        "heavy": weight >= 0.85 * cap,
        "edible": edible,
        "has_food": bool(edible) or bool(re.search(r"\d+ food items? in the cupboards", building))
                    or any("you can open it" in f for f in food),
        # zombies that can see you, or that you can see: the game won't let you sleep with these around
        "near_visible": sum(z["count"] for z in zs if z["dist"] <= 20 and "out of sight" not in z["state"]),
        "has_drink": any(re.search(r"[1-9]\d*/\d+", d) for d in p["inventory"].get("drink", [])),
        "water_known": any("taps on" in w for w in p["water"]),
        # a working tap a few steps away: a sip costs nothing
        "water_near": any("taps on" in w and int((re.search(r"(\d+) tiles", w) or [0, 99])[1]) <= 10 for w in p["water"]),
        "curtains_open": bool(re.search(r"\d+ curtains? open", building)),
        "shelter_near": "open door" in p["where"] or "closed doors" in p["where"],
    }


def score_goals(p, legal):
    f = features(p)
    thirst, hunger = _level(p, "thirst"), _level(p, "hunger")
    tired, endurance, panic = _level(p, "tired"), _level(p, "endurance"), _level(p, "panic")
    pain, sick = _level(p, "pain"), _level(p, "sick")
    wet, cold = _level(p, "wet"), _level(p, "cold")
    danger = f["chasing"] > 0
    s = {g: 0.0 for g in legal}

    def add(goal, value):
        if goal in s:
            s[goal] += value

    # 1. Stay alive.
    if danger:
        if f["can_fight"]:
            add("fight", 90)
        else:
            if "flee" in legal:
                add("fight", -100)
                add("flee", 95)
            else:
                # cornered (running failed, or nowhere to run): fighting back beats anything else. In game
                # the AI went to fetch a drink while two zombies bit it, and bled out.
                add("fight", 80)
            if f["shelter_near"] and endurance >= 3:
                add("hide", 97)  # too tired to outrun them: get behind a door
        add("hide", -40 if not f["indoors"] else 0)
        if f["nearest"] < 5:
            add("secure_building", -60)   # they're already in reach: no time to go round the doors
        if f["nearest"] < 10:
            add("retreat_home", -80)      # a walk home with zombies on you: run first, go home after
        for g in ("eat", "drink", "wait", "rest", "sleep", "loot_here", "loot_building", "explore", "drop_weight"):
            add(g, -80)
    if f["horde"]:
        add("secure_building" if f["open_building"] else "hide", 88 if f["indoors"] else 0)
        add("hide", 80)
        add("retreat_home", 85 if not f["indoors"] and not f["home_far"] else 0)
        add("flee", 60)
        add("fight", -100 if f["horde_close"] or not danger else 0)
        add("explore", -80)
        add("loot_building", -60)
    if f["open_building"] and (f["near"] or f["dark"] or f["dusk"]):
        add("secure_building", 86)
    elif f["curtains_open"] and f["indoors"] and (f["dark"] or f["dusk"] or f["at_home"]) and not danger:
        add("secure_building", 70)   # draw the curtains: zombies see in through windows
    if f["bleeding"]:
        add("bandage", 92 if not danger else 20)
    if f["weapon_cond"] < 20 and f["spare_weapon"]:
        add("equip_weapon", 89)
        add("fight", -60)
    elif f["spare_weapon"]:
        add("equip_weapon", 40)

    # 2. Critical needs.
    if thirst >= 2 and (f["has_drink"] or f["water_known"]):
        add("drink", 30 + 15 * thirst)
    elif thirst >= 1 and (f["has_drink"] or f["water_near"]) and not danger:
        add("drink", 45)   # top up while it's right there (in game it said "thirsty" next to a tap and didn't drink)
    else:
        add("drink", -5)
    if thirst >= 4 and f["can_fight"]:
        add("fight", 85)  # clear the way to water
    if hunger >= 2 and f["has_food"]:
        add("eat", 30 + 15 * hunger)
    elif hunger >= 1 and f["has_food"] and not danger:
        add("eat", 38)
    if not f["has_food"]:
        add("eat", -50)
    if sick >= 2:
        add("rest", 70)
        add("eat", -30)
    if endurance >= 2 and not danger:
        add("rest", 75)
    if panic >= 2 and not danger:
        add("rest", 65)
        add("hide", 50)
    if pain >= 2:
        add("take_medicine", 72)
    if f["overloaded"]:
        add("retreat_home", 70)
        add("drop_weight", 65)
    elif f["heavy"]:
        add("drop_weight", 62)   # a full bag means the next house's food stays behind
    if f["at_home"]:
        add("drop_weight", 45)   # store spare food at home (only offered when there's something to store)
    if wet >= 2 or cold >= 2:
        add("retreat_home", 80)
        add("change_clothes", 70 if f["indoors"] else 30)

    # 3. Night safety: home before dark, or a building nearby closed up for the night. Sleep there.
    outdoors = not f["indoors"]
    safe_inside = f["at_home"] or (f["indoors"] and f["secured"])
    if (f["dark"] or f["dusk"]) and outdoors:
        if f["home_known"] and not f["home_far"]:
            add("retreat_home", 85)
        else:
            add("hide", 84)   # get into the nearest building and shut it
        add("loot_building", 30 if f["dusk"] else -50)
        add("explore", -60)
    if (f["dark"] or f["dusk"]) and f["indoors"]:
        # it's getting dark: stay in. In game the AI walked out to loot at sunset and was sent straight home,
        # over and over, because nothing indoors scored above the next house.
        add("loot_building", -60)
        add("explore", -60)
        add("wait", 30)
    if tired >= 2 and safe_inside and not f["near_visible"]:
        add("sleep", 80)
    elif tired >= 1 and f["dark"] and safe_inside and not f["near_visible"]:
        add("sleep", 78)
    if tired >= 1 and f["near_visible"]:
        add("sleep", -90)
    if f["dark"] and safe_inside:
        add("wait", 40)
        add("rest", 35)
        add("explore", -60)
        add("loot_building", -60)

    # 4. Progress.
    if f["unsearched_here"] and not danger:
        add("loot_here", 60)
    if not f["dark"]:
        add("loot_building", 50 if p["unlooted"] else -10)
        add("explore", 30)
        if (hunger >= 2 and not f["has_food"]) or (thirst >= 2 and not f["has_drink"] and not f["water_known"]):
            add("loot_building", 25)
    if f["heavy"]:   # a full bag takes nothing home: shed weight first
        add("loot_building", -30)
        add("loot_here", -15)
    add("wait", 5)
    return s


def decide(percept, legal):
    scores = score_goals(percept, legal)
    goal = max(legal, key=lambda g: scores[g])
    return goal, f"rules: {goal} scored {scores[goal]:.0f}"
