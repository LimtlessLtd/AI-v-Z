"""A short Project Zomboid Build 42 handbook, so a 4B model doesn't have to know the game.

Each fact is written for this project and checked against the game's own files in 42.21 (recipes in
media/scripts/generated/recipes, items in media/scripts/generated/items) where it can be. `relevant` picks
the facts that matter right now from the percept, and the planner and strategy prompts include them as
KNOW-HOW. Pushing the right facts works better than letting a small model decide when to look something
up: it rarely asks about what it doesn't know it's missing. (In game it said "I need to find bandages"
while wearing a T-shirt it could have torn into some.)
"""

import re

# (trigger, fact). Triggers are names from `situation` below.
FACTS = [
    ("bleeding", "Bleeding kills fast: bandage it now. No bandages? Tear any cotton clothing (T-shirt, shirt, "
                 "vest, sheet) into rags by hand; take off what you're wearing first if you must. Jeans and "
                 "leather need scissors or a sharp knife."),
    ("wounded", "Clean wounds with disinfectant or alcohol wipes before bandaging, and change dirty bandages, "
                "or they get infected."),
    ("deep_wound", "A deep wound needs stitching (suture needle, or needle and thread); glass in a wound must "
                   "come out first (tweezers)."),
    ("bitten", "A zombie bite almost always means you will turn. Bandage it, eat, rest, and make the time count."),
    ("no_bandages", "Bandages, disinfectant and painkillers are in bathrooms, pharmacies and clinics. Rags from "
                    "torn clothes work as bandages."),
    ("cans", "Canned food keeps for years but needs a can opener; a sharp knife also opens cans (slower)."),
    ("hungry", "Eat fresh food first (fridges rot once the power goes). Raw meat and eggs must be cooked."),
    ("thirsty", "Taps and sinks work for the first days only; fill bottles and pots while they do. Rain "
                "barrels and rivers need boiling."),
    ("night", "At night zombies see a lit window from far away: close curtains, stay in, sleep in a closed-up "
              "house."),
    ("tired", "Sleep in a bed in a closed-up house with no zombies in sight; the game won't let you sleep with "
              "zombies around or while panicking."),
    ("crowd", "More than 3 zombies at once is how survivors die. Back off, shove to make space, fight at a "
              "doorway, or run and break line of sight."),
    ("fighting", "Shove a zombie to knock it down, then stomp or hit it on the ground. Fighting drains "
                 "endurance; an exhausted survivor swings slowly."),
    ("weak_weapon", "Weapons break. Carry a spare. Axes, crowbars, bats and hammers are good; kitchen tools "
                    "break fast."),
    ("no_weapon", "Fists only work on a single zombie. Any hammer, crowbar, bat, pipe or plank is a big step "
                  "up: look in garages, sheds and hardware stores."),
    ("heavy", "A worn backpack carries more for less weight. Over your limit you move slowly and tire fast."),
    ("locked", "Locked doors: go in through a window. Smashing glass is loud and cuts you unless you clear "
               "the glass first."),
    ("panic", "Panic and stress ruin your aim. Getting somewhere safe and quiet calms you down."),
    ("cold_wet", "Wet clothes and cold cause hypothermia: get indoors, dry off, change clothes."),
    ("pain", "Painkillers ease pain for a few hours; bad pain stops you sleeping."),
    ("planning", "Shops beat houses for their goods: pharmacy for medicine, grocery for food, hardware store "
                 "and garages for tools and weapons, gas stations for snacks and drinks."),
    ("planning", "Noise draws zombies from far away: smashing windows, gunshots, car alarms, running."),
    ("no_home", "A home base is a house with a bed you can close up, near water and food; come back to it "
                "before dark."),
]


def situation(percept, raw=None):
    """The triggers that hold right now, from the strategy percept (and the raw one if given)."""
    p, raw = percept, raw or {}
    moods = p.get("moodles", {})
    wounds = " ".join(p.get("wounds") or []).lower()
    inv = p.get("inventory") or {}
    medical = " ".join(inv.get("medical") or []).lower()
    food = " ".join(inv.get("food") or []).lower()
    zombies = p.get("zombies") or []
    weapon = (p.get("weapon") or "").lower()
    m = re.search(r"\((\d+)%", weapon)
    weight = re.match(r"([\d.]+)/([\d.]+)", p.get("weight") or "")
    time = (p.get("time") or "").lower()
    s = set()
    if re.search(r"(?<!not )bleeding", wounds):
        s.add("bleeding")
    if wounds:
        s.add("wounded")
    if "deep wound" in wounds or "glass" in wounds:
        s.add("deep_wound")
    if "bite" in wounds:
        s.add("bitten")
    if wounds and not any(k in medical for k in ("bandage", "rag", "tear")):
        s.add("no_bandages")
    if "can" in food or "tin" in food:
        s.add("cans")
    if moods.get("hunger", 0) >= 2:
        s.add("hungry")
    if moods.get("thirst", 0) >= 2 or not inv.get("drink"):
        s.add("thirsty")
    if "night" in time or "dusk" in time or "sunset" in time:
        s.add("night")
    if moods.get("tired", 0) >= 2:
        s.add("tired")
    near = sum(z["count"] for z in zombies if z["dist"] <= 15)
    if near >= 3:
        s.add("crowd")
    if any("chasing" in z["state"] for z in zombies):
        s.add("fighting")
    if "none" in weapon:
        s.add("no_weapon")
    elif m and int(m.group(1)) < 40:
        s.add("weak_weapon")
    if weight and float(weight.group(1)) >= 0.85 * float(weight.group(2)):
        s.add("heavy")
    if any("couldn't get in" in r or "no way into" in r or "no route" in r for r in p.get("recent") or []):
        s.add("locked")
    if moods.get("panic", 0) >= 2 or moods.get("stress", 0) >= 2:
        s.add("panic")
    if moods.get("wet", 0) >= 2 or moods.get("cold", 0) >= 1:
        s.add("cold_wet")
    if moods.get("pain", 0) >= 2:
        s.add("pain")
    if not p.get("home"):
        s.add("no_home")
    return s


def relevant(percept, limit=4, planning=False):
    """The facts that matter now, most urgent first (FACTS is in priority order)."""
    s = situation(percept)
    if planning:
        s.add("planning")
    out = [fact for trigger, fact in FACTS if trigger in s]
    return out[:limit]
