"""The baseline's strategy policy: the hand-written rules pick the goal.

This is the score the learning agent (Phase 3 on) has to beat. The running goal is kept unless something
else scores clearly higher: in the first in-game run, goals flipped every few seconds without that.
"""

from dataclasses import dataclass

from . import rules

URGENT = 85         # a score this high is an emergency: act on it immediately
KEEP_MARGIN = 15    # keep the running goal unless something else scores this much higher


@dataclass
class Plan:
    goal: str
    source: str          # "rules" or "keep"
    scores: dict
    ranked: list


def plan(percept, legal, current_goal=None, current_running=False):
    scores = rules.score_goals(percept, legal)
    ranked = sorted(legal, key=lambda g: -scores[g])
    top = ranked[0]
    if current_running and current_goal in legal and current_goal != top:
        if scores[top] < URGENT and scores[current_goal] >= scores[top] - KEEP_MARGIN:
            return Plan(current_goal, "keep", scores, ranked)
    return Plan(top, "rules", scores, ranked)
