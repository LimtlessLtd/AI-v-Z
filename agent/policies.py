"""Policies choose one of the options the gym offers.

Phase 3 has only the random policy: it checks the gym end to end and gives the learner (Phase 4) its first
experience. A random agent that changed its mind at every interruption would never finish anything, so it
keeps the running option ("continue") four times as often as any other single option.
"""

import random


class RandomPolicy:
    name = "random"

    def __init__(self, rng=None, keep_weight=4.0):
        self.rng = rng or random.Random()
        self.keep_weight = keep_weight

    def choose(self, msg):
        """Returns (option index, probabilities, note for the HUD)."""
        options = msg.get("options") or []
        if not options:
            return None, [], ""
        weights = [self.keep_weight if o.get("verb") == "continue" else 1.0 for o in options]
        total = sum(weights)
        probs = [w / total for w in weights]
        i = self.rng.choices(range(len(options)), weights=weights)[0]
        return i, probs, f"random pick, 1 of {len(options)}"
