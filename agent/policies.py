"""Policies choose one of the options the gym offers.

Phase 3 has the random policy: it checks the gym end to end and gives the learner (Phase 4) its first
experience. A random agent that changed its mind at every interruption would never finish anything, so it
keeps the running option ("continue") four times as often as any other single option.

The probe policy is a test tool, not a player: it checks that each kind of option does what it says in the
real game (python -m agent.run --policy probe). It tries every verb a few times as they come up, lets each
run to its end, and reports how each ended and what changed in the bag. Its logs go to logs/probe, apart
from the experience the agent learns from.
"""

import collections
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


def _bag(obs):
    obs = obs or {}
    items = list(obs.get("inv") or []) + ([obs["held"]] if isinstance(obs.get("held"), dict) else [])
    return collections.Counter(i.get("name") for i in items)


def _label(o):
    what = o.get("name") or o.get("recipe") or o.get("dir") or o.get("type") or o.get("part") or ""
    if o.get("verb") == "craft":
        what = f"{o.get('recipe')} ({o.get('name')})"
    return f"{o.get('verb')} {what}".strip()


class ProbePolicy:
    """Tries each verb up to `tries` times, the first ones in TEST first, and explores to find more to try."""

    name = "probe"
    TEST = ("bandage", "eat", "drink", "craft", "take", "climb", "smash", "clear_glass", "drink_tap", "wear",
            "take_off", "equip", "unequip", "drop", "door", "window", "curtain", "search", "go_room", "enter")
    LATE = ("walk", "run", "attack", "shove", "rest", "wait", "sleep")   # now and then: they cost lives or time
    EXPLORE = ("search", "enter", "go_room", "walk")

    def __init__(self, rng=None, tries=3, max_continues=12):
        self.rng = rng or random.Random()
        self.tries, self.max_continues = tries, max_continues
        self.tally = collections.defaultdict(collections.Counter)   # verb -> outcome -> n
        self.results = []                                           # every finished try, newest last
        self.pending = None                                         # the option running now
        self.continues = 0

    def _settle(self, msg):
        """Fold in how the pending option ended, if it has."""
        p = self.pending
        if not p:
            return
        last = msg.get("last") or {}
        if msg.get("dead"):
            outcome, note = "died", ""
        elif last.get("verb") == p["verb"] and last.get("status") in ("done", "failed"):
            outcome, note = last["status"], last.get("msg") or ""
        else:
            return
        before, after = p["bag"], _bag(msg.get("obs"))
        res = {"verb": p["verb"], "what": p["label"], "outcome": outcome, "msg": note, "age": last.get("age"),
               "speed": p["speed"], "gained": dict(after - before), "lost": dict(before - after)}
        self.results.append(res)
        self.tally[p["verb"]][outcome + (f": {note}" if outcome == "failed" and note else "")] += 1
        self.pending = None

    def tried(self, verb):
        return sum(self.tally[verb].values()) + (1 if self.pending and self.pending["verb"] == verb else 0)

    def choose(self, msg):
        self._settle(msg)
        options = msg.get("options") or []
        if not options:
            return None, [], ""
        probs = [0.0] * len(options)
        verbs = [o.get("verb") for o in options]
        if "continue" in verbs and self.continues < self.max_continues:
            self.continues += 1
            i = verbs.index("continue")
        else:
            i = self._pick(options)
            self.continues = 0
            if self.pending:   # replaced before it ended
                self.tally[self.pending["verb"]]["replaced"] += 1
                self.pending = None
            o = options[i]
            if o.get("verb") != "continue":
                self.pending = {"verb": o.get("verb"), "label": _label(o), "bag": _bag(msg.get("obs")),
                                "speed": (msg.get("obs") or {}).get("speed")}
        probs[i] = 1.0
        return i, probs, f"probe: {_label(options[i])}"

    def _pick(self, options):
        idx = [i for i, o in enumerate(options) if o.get("verb") != "continue"]
        order = self.TEST + (self.LATE if self.rng.random() < 0.25 else ())
        for verb in order:
            if self.tried(verb) >= self.tries:
                continue
            cands = [i for i in idx if options[i].get("verb") == verb]
            if verb == "search":   # the ones in this building first, nearest first
                cands.sort(key=lambda i: (not options[i].get("here", True), options[i].get("d", 99)))
            elif verb == "enter":
                cands = [i for i in cands if not options[i].get("visited")] or cands
                cands.sort(key=lambda i: options[i].get("d", 99))
            elif verb == "sleep" and cands:
                cands.sort(key=lambda i: not options[i].get("bed"))
            if cands:
                return cands[0] if verb in ("search", "enter", "sleep") else self.rng.choice(cands)
        # A drink or weapon has to reach the bag before its executor can be tested. Take one from a
        # container found in natural play even after the ordinary three take checks are complete.
        for needed, predicate in (("drink", lambda o: o.get("water", 0) > 0),
                                  ("equip", lambda o: o.get("cat") == "weapon")):
            if self.tried(needed) < self.tries and needed not in (o.get("verb") for o in options):
                cands = [i for i in idx if options[i].get("verb") == "take" and predicate(options[i])]
                if cands:
                    return min(cands, key=lambda i: options[i].get("d", 99))
        for verb in self.EXPLORE:   # everything on offer has been tried enough: go and find more
            cands = [i for i in idx if options[i].get("verb") == verb and (verb != "search" or options[i].get("here", True))]
            if verb == "enter":
                cands = [i for i in cands if not options[i].get("visited")]
            if verb == "go_room" and self.tried("go_room") > 6:
                continue   # don't shuttle forever between rooms in the same house
            if cands:
                return min(cands, key=lambda i: options[i].get("d", 0)) if verb != "walk" else self.rng.choice(cands)
        return self.rng.choice(idx)

    def report(self):
        lines = []
        for verb in self.TEST + self.LATE:
            if self.tally[verb]:
                lines.append(f"{verb:12s} " + ", ".join(f"{k} {n}" for k, n in self.tally[verb].most_common()))
        return "\n".join(lines)
