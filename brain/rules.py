"""No-LLM baseline: a hand-written utility scorer over the same percepts and legal goals.

Each legal goal gets a score from general survival rules (the same priorities as the LLM's system prompt);
the highest score wins. This is what the Lua tactics layer could do on its own in <1 ms with no GPU.

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
    horde = any(z["count"] >= 10 for z in zs) or sum(z["count"] for z in zs) >= 15 or bool(p.get("noise"))
    weapon_cond = 0 if "none" in p["weapon"] else _condition(p["weapon"])
    spare = [w for w in p["inventory"].get("weapons", []) if _condition(w) > max(weapon_cond, 30)]
    building = p.get("building") or ""
    time = p["time"].lower()
    weight, cap = _weight(p)
    food = p["inventory"].get("food", [])
    return {
        "chasing": chasing, "near": near, "horde": horde,
        "nearest": min((z["dist"] for z in zs), default=999),
        "weapon_cond": weapon_cond, "spare_weapon": bool(spare),
        "can_fight": chasing <= 3 and _level(p, "endurance") <= 1 and weapon_cond >= 30,
        "indoors": p["where"].startswith("inside"),
        "at_home": (p["home"] or "").startswith("you are at home"),
        "secured": "secured" in building or ("locked" in building and "OPEN" not in building),
        "open_building": "OPEN" in building or "window open" in building or "windows open" in building,
        "unsearched_here": bool(re.search(r"searched (\d+)/(\d+)", building))
                           and int(re.search(r"searched (\d+)/(\d+)", building).group(1))
                           < int(re.search(r"searched (\d+)/(\d+)", building).group(2)),
        "dark": any(w in time for w in LEVEL_WORDS),
        "dusk": "dusk" in time or "sunset" in time,
        "bleeding": any(re.search(r"(?<!not )bleeding", w, re.I) for w in p["wounds"]),
        "overloaded": weight > cap,
        "edible": [f for f in food if "rotten" not in f and "can opener" not in f and "needs" not in f],
        "has_drink": any(re.search(r"[1-9]\d*/\d+", d) for d in p["inventory"].get("drink", [])),
        "water_known": any("taps on" in w for w in p["water"]),
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
            add("fight", -100)
            add("flee", 95)
            if f["shelter_near"] and endurance >= 3:
                add("hide", 97)  # too tired to outrun them: get behind a door
        add("hide", -40 if not f["indoors"] else 0)
        for g in ("eat", "wait", "rest", "sleep", "loot_here", "loot_building", "explore"):
            add(g, -80)
    if f["horde"]:
        add("secure_building" if f["open_building"] else "hide", 88 if f["indoors"] else 0)
        add("hide", 80)
        add("retreat_home", 85 if not f["indoors"] else 0)
        add("flee", 60)
        add("fight", -100)
        add("explore", -80)
        add("loot_building", -60)
    if f["open_building"] and (f["near"] or f["dark"] or f["dusk"]):
        add("secure_building", 86)
    if f["bleeding"]:
        add("bandage", 92 if not danger else 20)
    if f["weapon_cond"] < 20 and f["spare_weapon"]:
        add("equip_weapon", 89)
        add("fight", -60)
    elif f["spare_weapon"]:
        add("equip_weapon", 40)

    # 2. Critical needs.
    add("drink", 30 + 15 * thirst if thirst >= 2 and (f["has_drink"] or f["water_known"]) else -5)
    if thirst >= 4 and f["can_fight"]:
        add("fight", 85)  # clear the way to water
    if hunger >= 2 and f["edible"]:
        add("eat", 30 + 15 * hunger)
    if not f["edible"]:
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
    if wet >= 2 or cold >= 2:
        add("retreat_home", 80)
        add("change_clothes", 70 if f["indoors"] else 30)

    # 3. Night safety.
    outdoors = not f["indoors"]
    if (f["dark"] or f["dusk"]) and outdoors:
        add("retreat_home", 85)
        add("loot_building", 30 if f["dusk"] else -50)
        add("explore", -60)
    if tired >= 2 and (f["at_home"] or f["secured"]) and not f["near"]:
        add("sleep", 80)
    if tired >= 2 and f["near"]:
        add("sleep", -90)
    if f["dark"] and f["at_home"]:
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
        if (hunger >= 2 and not f["edible"]) or (thirst >= 2 and not f["has_drink"]):
            add("loot_building", 25)
    add("wait", 5)
    return s


def decide(percept, legal):
    scores = score_goals(percept, legal)
    goal = max(legal, key=lambda g: scores[g])
    return goal, f"rules: {goal} scored {scores[goal]:.0f}"
