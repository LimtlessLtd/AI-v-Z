"""The strategy policy: rules decide clear cases instantly; unclear ones also go to the LLM.

See docs/DECISION_MODELS.md for why: the rule scorer beat every model on the benchmark, the LLM is
there for close calls and to explain decisions in the speech bubble.
"""

from dataclasses import dataclass

from . import rules

CLEAR_MARGIN = 15   # top rule score beats the runner-up by this much: no need to ask the LLM
URGENT = 85         # a score this high is an emergency: act on it immediately
KEEP_MARGIN = 15    # keep the running goal unless something else scores this much higher


@dataclass
class Plan:
    goal: str
    source: str          # "rules" or "keep"
    clear: bool          # False: worth asking the LLM
    scores: dict
    ranked: list


def plan(percept, legal, current_goal=None, current_running=False):
    scores = rules.score_goals(percept, legal)
    ranked = sorted(legal, key=lambda g: -scores[g])
    top = ranked[0]
    runner_up = scores[ranked[1]] if len(ranked) > 1 else float("-inf")
    clear = scores[top] - runner_up >= CLEAR_MARGIN or scores[top] >= URGENT
    if (current_running and current_goal in legal and current_goal != top
            and scores[current_goal] >= scores[top] - KEEP_MARGIN):
        return Plan(current_goal, "keep", True, scores, ranked)
    return Plan(top, "rules", clear, scores, ranked)
