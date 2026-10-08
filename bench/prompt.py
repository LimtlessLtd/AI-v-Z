"""Builds the AI's strategy prompt and output schema from a percept.

This is the prompt contract the bridge will use in Phase 1: the Lua mod reports a percept like the ones in
snapshots.py, the bridge renders it with `build_messages`, and Ollama's `format` constrains the answer with
`output_schema(legal_goals)`.
"""

from goals import GOALS

SYSTEM_PROMPT = """You are an AI playing a survivor in Project Zomboid (Build 42, singleplayer, Riverside, Kentucky).
You are the STRATEGY layer. A reflex layer already handles zombies within 3 tiles (shove, swing, step back)
and a tactics layer carries out the goal you pick (walking, doors, looting). Every few seconds you choose ONE
goal from ALLOWED GOALS for the next stretch of play.

Priorities, most urgent first:
1. Stay alive: zombies chasing you, bleeding, hordes. Never walk towards a horde.
2. Critical needs: severe or extreme thirst, hunger, exhaustion, cold.
3. Be inside a secured building at night. Sleep only when secured and no zombies are near.
4. Progress: loot unsearched buildings, gather water, food, weapons and medical supplies, explore.

1-3 zombies are fightable with a decent weapon and good endurance. 4 or more zombies, a weak or breaking
weapon, or severe exhaustion means flee or hide instead.

Answer with JSON only: {"goal": one allowed goal id, "why": at most 12 words, first person, shown in a speech bubble}."""

LEVELS = {1: "mild", 2: "moderate", 3: "severe", 4: "extreme"}


def _join(items, empty="none"):
    return ", ".join(items) if items else empty


def render_percept(p, extra_memory=()):
    lines = [
        f"TIME: {p['time']}. Weather: {p['weather']}.",
        f"PLACE: {p['where']}." + (f" Building: {p['building']}." if p.get("building") else ""),
    ]
    moodles = [f"{name} {LEVELS[lvl]}" for name, lvl in p["moodles"].items() if lvl]
    lines.append(f"BODY: health {p['health']}%. Moodles: {_join(moodles)}. Wounds: {_join(p['wounds'])}.")
    inv = "; ".join(f"{k}: {_join(v)}" for k, v in p["inventory"].items())
    lines.append(f"GEAR: weapon {p['weapon']}. {inv}. Weight {p['weight']}.")
    if p["zombies"]:
        groups = [f"{z['count']} at {z['dist']} tiles {z['dir']} ({z['state']})" for z in p["zombies"]]
        lines.append(f"ZOMBIES: {'; '.join(groups)}.")
    else:
        lines.append("ZOMBIES: none in sight.")
    if p.get("noise"):
        lines.append(f"NOISE: {p['noise']}.")
    lines.append(f"HOME: {p['home'] or 'none yet'}.")
    lines.append(f"KNOWN WATER: {_join(p['water'])}.")
    lines.append(f"UNLOOTED: {_join(p['unlooted'])}. LOOTED: {_join(p['looted'])}.")
    memory = list(extra_memory) + list(p["recent"])
    lines.append("MEMORY:\n" + "\n".join(f"- {m}" for m in memory))
    lines.append(f"LAST GOAL: {p['last_goal'] or 'none'}.")
    return "\n".join(lines)


def render_goals(legal):
    return "ALLOWED GOALS:\n" + "\n".join(f"- {g}: {GOALS[g]}" for g in legal)


def build_messages(percept, legal, extra_memory=()):
    user = render_percept(percept, extra_memory) + "\n\n" + render_goals(legal) + "\n\nPick one goal."
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def output_schema(legal, why_first=False):
    props = {
        "goal": {"type": "string", "enum": list(legal)},
        "why": {"type": "string", "maxLength": 90},
    }
    order = ["why", "goal"] if why_first else ["goal", "why"]
    return {
        "type": "object",
        "properties": {k: props[k] for k in order},
        "required": order,
        "additionalProperties": False,
    }
