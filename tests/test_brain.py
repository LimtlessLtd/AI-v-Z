"""Tests for the bridge's Python side: percept conversion, legal goals, the strategy policy, intent lines.

Run from the repo root:  python -m unittest discover -s tests
"""

import copy
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bridge"))

from brain import strategy  # noqa: E402
from brain.percept import Memory, dir8, summarize, time_text  # noqa: E402
from brain.prompt import build_messages  # noqa: E402

# A percept as the mod writes it: inside a kitchen, thirsty, one zombie wandering outside.
RAW = {
    "v": 1, "tick": 1200, "ack": 7, "manual": False, "dead": False, "kills": 0, "err": "",
    "pos": {"x": 10500.5, "y": 9800.5, "z": 0},
    "time": {"day": 2, "hour": 14, "min": 10, "dawn": 6, "dusk": 21, "dark": 0},
    "weather": {"rain": 0, "temp": 21.5, "fog": 0},
    "outside": False, "room": "kitchen",
    "bld": {"id": "123", "doorsOpen": 1, "windowsOpen": 0, "containers": 9, "searched": 4, "looted": False},
    "health": 96,
    "stats": {"hunger": 0.1, "thirst": 0.45, "fatigue": 0.1, "endurance": 0.9, "panic": 0},
    "moodles": {"thirst": 2},
    "wounds": [],
    "weapon": {"name": "Baseball Bat", "cond": 8, "max": 10, "melee": True, "score": 1.0},
    "inv": {"food": [{"name": "Chips", "edible": True, "rotten": False}], "water": [], "medical": [], "weapons": []},
    "weight": 4.2, "maxWeight": 12,
    "zombies": [{"dx": 18, "dy": -4, "d": 18.4, "seen": True, "chasing": False}],
    "water": [{"x": 10502, "y": 9800, "z": 0, "d": 1.5, "dir": "E", "name": "Sink", "amount": 100, "tainted": False}],
    "buildings": [
        {"id": "123", "d": 2, "dir": "HERE", "tx": 10501, "ty": 9801, "tz": 0, "rooms": ["kitchen", "bedroom"], "looted": False},
        {"id": "456", "d": 25, "dir": "S", "tx": 10500, "ty": 9826, "tz": 0, "rooms": ["bedroom"], "looted": False},
    ],
    "task": {"seq": 7, "goal": "loot_here", "status": "running", "msg": "", "phase": "walk", "age": 300},
    "reflex": {"act": "", "ago": 99999},
    "events": [{"id": 1, "t": "14:02", "msg": "found Chips"}],
    "speed": 1,
}


class PerceptTests(unittest.TestCase):
    def test_dir8_matches_the_mod(self):
        self.assertEqual(dir8(0, -5), "N")
        self.assertEqual(dir8(5, 5), "SE")
        self.assertEqual(dir8(-5, 0), "W")
        self.assertEqual(dir8(0.1, 0.1), "SE")
        self.assertEqual(dir8(0, 0), "HERE")

    def test_time_periods(self):
        self.assertIn("afternoon", time_text({"day": 1, "hour": 14, "min": 0, "dawn": 6, "dusk": 21}))
        self.assertIn("sunset in 30 min", time_text({"day": 1, "hour": 20, "min": 30, "dawn": 6, "dusk": 21}))
        self.assertIn("dusk", time_text({"day": 1, "hour": 21, "min": 30, "dawn": 6, "dusk": 21}))
        self.assertIn("night (dark)", time_text({"day": 1, "hour": 23, "min": 0, "dawn": 6, "dusk": 21}))
        self.assertIn("night (dark)", time_text({"day": 1, "hour": 4, "min": 0, "dawn": 6, "dusk": 21}))

    def test_summary_has_snapshot_shape_and_legal_goals(self):
        mem = Memory()
        mem.update(RAW)
        s = summarize(RAW, mem, random.Random(1))
        p = s.percept
        self.assertEqual(p["moodles"], {"thirst": 2})
        self.assertIn("1 door OPEN", p["building"])
        self.assertIn("containers searched 4/9", p["building"])
        self.assertEqual(p["weapon"], "Baseball Bat (80%)")
        self.assertIn("Sink 2 tiles E (taps on)", p["water"])
        self.assertEqual(p["unlooted"], ["house 25 tiles S"])   # the building we're in isn't listed
        self.assertTrue(any("found Chips" in r for r in p["recent"]))
        for goal in ("flee", "hide", "secure_building", "loot_here", "drink", "eat", "loot_building", "explore", "wait"):
            self.assertIn(goal, s.legal)
        self.assertNotIn("fight", s.legal)            # the only zombie is 18 tiles away
        self.assertNotIn("bandage", s.legal)          # no wound, no bandage
        self.assertNotIn("equip_weapon", s.legal)     # nothing better in the bag
        self.assertEqual(s.args["loot_building"], (10500, 9826, 0))
        # the prompt builds from it without errors
        self.assertIn("ALLOWED GOALS", build_messages(p, s.legal)[1]["content"])

    def test_empty_lua_tables_arrive_as_lists(self):
        raw = copy.deepcopy(RAW)
        raw["moodles"] = []
        raw["inv"] = []
        s = summarize(raw, Memory(), random.Random(1))
        self.assertEqual(s.percept["moodles"], {})
        self.assertNotIn("eat", s.legal)

    def test_bleeding_with_bandage_makes_bandage_legal_and_urgent(self):
        raw = copy.deepcopy(RAW)
        raw["zombies"] = []
        raw["wounds"] = [{"part": "ForeArm_L", "flags": ["bleeding", "laceration"]}]
        raw["inv"]["medical"] = [{"name": "Bandage", "kind": "bandage"}]
        s = summarize(raw, Memory(), random.Random(1))
        self.assertIn("ForeArm_L: BLEEDING, laceration", s.percept["wounds"])
        self.assertEqual(strategy.plan(s.percept, s.legal).goal, "bandage")

    def test_failed_building_is_not_offered_again(self):
        mem = Memory()
        raw = copy.deepcopy(RAW)
        raw["task"] = {"seq": 9, "goal": "loot_building", "status": "failed", "msg": "no route", "target": "10500,9826"}
        mem.update(raw)
        s = summarize(raw, mem, random.Random(1))
        self.assertNotIn("loot_building", s.legal)

    def test_explore_avoids_the_zombies(self):
        raw = copy.deepcopy(RAW)
        raw["zombies"] = [{"dx": 0, "dy": -8, "d": 8, "seen": True, "chasing": True}] * 5
        headings = {summarize(raw, Memory(), random.Random(i)).threat["explore_heading"] for i in range(20)}
        self.assertNotIn("N", headings)


class StrategyTests(unittest.TestCase):
    def test_five_chasing_means_flee_without_asking(self):
        raw = copy.deepcopy(RAW)
        raw["bld"] = None
        raw["zombies"] = [{"dx": 0, "dy": 6, "d": 6, "seen": True, "chasing": True}] * 5
        s = summarize(raw, Memory(), random.Random(1))
        plan = strategy.plan(s.percept, s.legal)
        self.assertEqual(plan.goal, "flee")
        self.assertTrue(plan.clear)

    def test_keeps_running_goal_unless_something_is_much_better(self):
        s = summarize(RAW, Memory(), random.Random(1))
        plan = strategy.plan(s.percept, s.legal, current_goal="loot_here", current_running=True)
        self.assertIn(plan.goal, ("loot_here", "drink", "secure_building"))
        if plan.goal == "loot_here":
            self.assertEqual(plan.source, "keep")


class IntentLineTests(unittest.TestCase):
    def test_separators_and_newlines_are_removed(self):
        import bridge as bridge_mod
        line = bridge_mod.intent_line(5, "explore", (40, -12, 0), say="I'll go | north\nnow", why="a|b", source="rules")
        self.assertEqual(line, "5|explore|40|-12|0|I'll go / north now|a/b|rules")
        self.assertEqual(line.count("|"), 7)

    def test_missing_args_are_blank(self):
        import bridge as bridge_mod
        self.assertEqual(bridge_mod.intent_line(1, "wait", ()), "1|wait||||||")


if __name__ == "__main__":
    unittest.main()
