"""Strategy-level goals the AI's brain can pick from.

The tactics layer (Lua) carries out whichever goal is chosen. Each percept snapshot exposes only the goals
that are legal in that state, e.g. `drink` only when a water source is known or carried.
"""

GOALS = {
    "fight": "Attack the visible zombies with the equipped weapon (ok for 1-3 zombies with good endurance).",
    "flee": "Run away from zombies, break line of sight, then continue.",
    "hide": "Get into the nearest building if outside, close the doors, stay still and quiet until threats pass.",
    "secure_building": "Close and lock doors and windows of the current building.",
    "retreat_home": "Walk back to the home base (in through a window if the doors are locked).",
    "drink": "Drink from a carried bottle or the nearest known water source.",
    "fill_water": "Fill empty bottles at a working water source.",
    "eat": "Eat the best food from the bag, or from the cupboards here.",
    "bandage": "Disinfect and bandage open or bleeding wounds.",
    "take_medicine": "Take painkillers or other pills from inventory.",
    "rest": "Sit down to recover endurance and calm down.",
    "sleep": "Sleep in the nearest bed in this building (on the floor if there's none).",
    "loot_here": "Search the unsearched containers in the current building.",
    "loot_building": "Go to the nearest unlooted building (in through a window if it's locked) and search it.",
    "explore": "Walk into unexplored streets to discover new buildings.",
    "equip_weapon": "Equip the best weapon from inventory.",
    "drop_weight": "Leave junk behind (spare weapons and clothes, food you can't eat); at home, store spare food in the cupboards.",
    "change_clothes": "Change into dry clothes from inventory.",
    "wait": "Stay where you are and watch; nothing urgent to do.",
}
