"""The planner: the AI sets its own aim and a short plan, and the strategy layer follows it.

Rules keep the AI alive second to second (zombies, wounds, nightfall); what to do with the day is the
language model's call. At key moments (waking up, a finished or failed plan, every few game hours) the
model gets the situation, a map of the places it knows, its diary and lessons from earlier characters, and
answers with an aim in its own words and up to five steps. The bridge works through the steps: the current
step's goal scores PLAN_SCORE, enough to beat routine needs but not an emergency, and supplies its target
(which building, which direction). Emergencies interrupt; the plan resumes after.
"""

import math
from dataclasses import asdict, dataclass, field

from .percept import DIRS

PLAN_SCORE = 70          # the plan's step beats looting (50), a top-up drink (45), moderate thirst (60)...
                         # but not a fight (90), bleeding (92), nightfall (85) or severe thirst (75)
REPLAN_GAME_HOURS = 6    # a plan older than this gets revisited
EXPLORE_LEGS = 2         # an "explore" step is done after this many walks that way
MAX_TRIP = 250           # tiles: further than this isn't a day trip

# what the model may write -> the goal it maps to
ACTIONS = {
    "loot": "loot_building",        # where: a place label (P1..)
    "explore": "explore",           # where: a compass direction
    "go_home": "retreat_home",
    "search_here": "loot_here",
    "close_up": "secure_building",
    "store_loot": "drop_weight",
    "treat_wounds": "bandage",      # bandages, or rags torn from clothes
    "sleep": "sleep",
    "rest": "rest",
    "wait": "wait",
}

PLANNER_BRIEF = """You are an AI playing a survivor in Project Zomboid (Build 42, singleplayer, Kentucky).
You decide what to do with the next day or so. A reflex layer handles zombies close by, and survival rules
interrupt your plan for emergencies (zombies chasing, bleeding, nightfall, severe thirst or hunger); after
that your plan carries on.

Think like an experienced player: what is the biggest risk or lack right now? A real weapon, a backpack, food
for later (cans need a can opener or a knife), water for when the taps stop in a few days, bandages and
disinfectant, a safe home with a bed? Pick ONE aim that fixes the biggest one, in your own words, and up to 5
steps towards it. Prefer places you haven't searched; stores beat houses for their kind of goods (pharmacy:
medicine; grocery: food; hardware store: tools and weapons). Be home or closed up somewhere before dark.
Steps happen in order, starting now, so don't plan what's already true (going home when you're home,
closing up a building that's closed). "loot" walks to the place by itself. Sleep belongs at night.

Steps use these actions:
- loot: go to a known place and search it. "where" = its label, e.g. "P3".
- explore: walk a long way in a direction to find new places. "where" = N, NE, E, SE, S, SW, W or NW.
- go_home: walk back to your home base.
- search_here: search the rest of the building you're in.
- close_up: close the doors, windows and curtains of the building you're in.
- store_loot: at home, put spare food and junk away.
- treat_wounds: bandage your wounds (with bandages, or rags torn from your clothes).
- sleep, rest, wait.

Answer with JSON only: {"aim": your aim in 4-12 words, "why": one sentence, "steps": [{"do": action, "where":
label or direction or "", "note": what this step is for, 3-8 words}]}."""


@dataclass
class Step:
    do: str                 # action word from ACTIONS
    goal: str               # the goal id it maps to
    where: str = ""         # place label (P3) or compass direction
    note: str = ""
    place: str | None = None   # building id for loot steps
    target: tuple | None = None  # (x, y, z) for loot, (dx, dy, 0) for explore
    status: str = "todo"    # todo, done, failed, skipped (didn't apply when its turn came)
    tries: int = 0
    legs: int = 0

    def text(self):
        return self.note or f"{self.do} {self.where}".strip()


@dataclass
class Plan:
    aim: str
    why: str
    steps: list
    made_day: int = 1
    made_hour: float = 0.0
    reason: str = ""
    labels: dict = field(default_factory=dict)   # label -> building id, as shown to the model

    def current(self):
        return next((s for s in self.steps if s.status == "todo"), None)

    def finished(self):
        return self.current() is None

    def progress(self):
        done = sum(1 for s in self.steps if s.status != "todo")
        return f"{min(done + 1, len(self.steps))}/{len(self.steps)}"

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        if not d:
            return None
        steps = [Step(**{k: (tuple(v) if k == "target" and v is not None else v) for k, v in s.items()})
                 for s in d.get("steps", [])]
        return Plan(aim=d.get("aim", ""), why=d.get("why", ""), steps=steps, made_day=d.get("made_day", 1),
                    made_hour=d.get("made_hour", 0.0), reason=d.get("reason", ""), labels=d.get("labels", {}))


def output_schema():
    return {
        "type": "object",
        "properties": {
            "aim": {"type": "string", "maxLength": 90},
            "why": {"type": "string", "maxLength": 160},
            "steps": {"type": "array", "minItems": 1, "maxItems": 5, "items": {
                "type": "object",
                "properties": {"do": {"type": "string", "enum": list(ACTIONS)},
                               "where": {"type": "string", "maxLength": 12},
                               "note": {"type": "string", "maxLength": 60}},
                "required": ["do", "where", "note"], "additionalProperties": False}},
        },
        "required": ["aim", "why", "steps"],
        "additionalProperties": False,
    }


def _game_hours(raw):
    """Game hours since the world began. The day number ticks over at dawn, not midnight, so
    day * 24 + hour jumps by a day at 7 am; the mod sends the world's own clock."""
    t = raw.get("time") or {}
    if t.get("age") is not None:
        return float(t["age"])
    return (t.get("day", 1) - 1) * 24 + t.get("hour", 0) + t.get("min", 0) / 60


def build_messages(percept, raw, world, reason, old_plan=None):
    """The planning prompt: situation (as the strategy prompt shows it), places, diary, lessons."""
    from .prompt import render_percept
    places = world.labelled_places(raw)
    lines = [render_percept({**percept, "knowhow": None}), ""]
    lines.append("KNOWN PLACES:")
    lines += [f"- {label}: {text}" for label, _, text in places] or ["- none yet: explore to find some"]
    diary = world.data.get("diary") or []
    if diary:
        lines.append("YOUR DIARY:")
        lines += [f"- Day {d['day']}: {d['text']}" for d in diary[-3:]]
    if world.lessons:
        lines.append("LESSONS FROM SURVIVORS BEFORE YOU (they died):")
        lines += [f"- {x}" for x in world.lessons[-4:]]
    if old_plan:
        lines.append(f"YOUR LAST AIM: {old_plan.aim}")
        for s in old_plan.steps:
            lines.append(f"- {s.status}: {s.do} {s.where} ({s.note})")
    lines.append(f"\nWHY YOU'RE PLANNING NOW: {reason}.")
    lines.append("Make your plan.")
    from .knowledge import relevant
    lines.insert(-2, "KNOW-HOW (Project Zomboid):" + "".join(f"\n- {k}" for k in relevant(percept, 6, planning=True)))
    labels = {label: pid for label, pid, _ in places}
    return [{"role": "system", "content": PLANNER_BRIEF}, {"role": "user", "content": "\n".join(lines)}], labels


def parse_plan(obj, raw, world, labels, reason=""):
    """Turn the model's JSON into a Plan, dropping steps that can't be carried out. None if nothing is left."""
    if not isinstance(obj, dict):
        return None
    has_home = bool(raw.get("home"))
    steps = []
    for s in obj.get("steps") or []:
        do, where = str(s.get("do", "")), str(s.get("where", "")).strip().upper()
        note = " ".join(str(s.get("note", "")).split())[:60]
        if do not in ACTIONS:
            continue
        step = Step(do=do, goal=ACTIONS[do], where=where, note=note)
        if do == "loot":
            pid = labels.get(where)
            p = world.places.get(pid) if pid else None
            if not p or p.get("looted") or p.get("locked"):
                continue
            pos = raw.get("pos") or {}
            if pos and math.hypot(p["x"] - pos.get("x", 0), p["y"] - pos.get("y", 0)) > MAX_TRIP:
                continue
            step.place, step.target = pid, (p["x"], p["y"], p.get("z", 0))
        elif do == "explore":
            if where not in DIRS:
                continue
            ux, uy = DIRS[where]
            scale = 40 / math.hypot(ux, uy)
            step.target = (round(ux * scale), round(uy * scale), 0)
        elif do == "go_home" and not has_home:
            continue
        steps.append(step)
    # "explore E" then "loot P3" (east): loot walks there itself, and two explore legs overshoot it
    steps = [st for i, st in enumerate(steps)
             if not (st.do == "explore" and i + 1 < len(steps) and steps[i + 1].do == "loot")]
    if not steps:
        return None
    t = raw.get("time") or {}
    return Plan(aim=" ".join(str(obj.get("aim", "")).split())[:90], why=" ".join(str(obj.get("why", "")).split())[:160],
                steps=steps[:5], made_day=t.get("day", 1), made_hour=_game_hours(raw), reason=reason, labels=labels)


def needs_new_plan(plan, raw, woke_up=False):
    """Why to plan now, or None."""
    if plan is None:
        return "you have no plan yet"
    if woke_up:
        return "you just woke up: a new day"
    if plan.finished():
        failed = [s for s in plan.steps if s.status == "failed"]
        return "your plan is finished" + (f" ({len(failed)} step(s) failed)" if failed else "")
    if _game_hours(raw) - plan.made_hour >= REPLAN_GAME_HOURS:
        return f"your plan is {REPLAN_GAME_HOURS}+ hours old: check it still makes sense"
    return None


def hint(plan, legal_args, raw, places):
    """The current step as (goal, args) when it can be done now, else None. Skips steps already moot."""
    step = plan.current() if plan else None
    while step is not None:
        if step.goal == "loot_building":
            place = places.get(step.place) or {}
            if place.get("looted") or place.get("locked"):
                step.status = "done" if place.get("looted") else "failed"
                step = plan.current()
                continue
            return step.goal, step.target
        if step.goal == "retreat_home" and (raw.get("home") or {}).get("here"):
            step.status = "done"
            step = plan.current()
            continue
        if step.goal == "explore":
            return step.goal, step.target
        if step.goal in legal_args:
            return step.goal, legal_args[step.goal]
        # nothing to close, nothing left to search here, not tired: the step doesn't apply, move on.
        # (A 4B model's plans sometimes include these; waiting for them would stall the plan.)
        step.status = "skipped"
        step = plan.current()
    return None


def on_task_end(plan, goal, status, msg=""):
    """Advance the plan when the task for its current step ends. Returns a line for the AI's memory, or None."""
    step = plan.current() if plan else None
    if step is None or step.goal != goal:
        return None
    if status == "done":
        if step.goal == "explore":
            step.legs += 1
            if step.legs < EXPLORE_LEGS:
                return None
        step.status = "done"
        return f"plan step done: {step.text()}"
    step.tries += 1
    if step.tries >= 2:
        step.status = "failed"
        return f"plan step failed: {step.text()} ({msg})"
    return None


def plan_text(plan):
    """For the strategy/narration prompt and the HUD."""
    if not plan:
        return None
    step = plan.current()
    return f"{plan.aim}" + (f"; now step {plan.progress()}: {step.text()}" if step else "; all steps done")
