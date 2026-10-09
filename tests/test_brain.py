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

import bridge as bridge_mod  # noqa: E402
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
        # B42's season gives fractional hours
        self.assertIn("sunset in 36 min", time_text({"day": 1, "hour": 21, "min": 0, "dawn": 7.1, "dusk": 21.6}))

    def test_impossible_dawn_and_dusk_are_ignored(self):
        # GameTime:getDawn()/getDusk() read 12 and 3 in 42.21; 10:05 is still morning
        self.assertIn("morning", time_text({"day": 1, "hour": 10, "min": 5, "dawn": 12, "dusk": 3}))

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

    def test_fights_a_lone_zombie_bare_handed_despite_a_distant_horde(self):
        # the first in-game run: unarmed, one zombie on top of us, 40 heard 30 tiles away. It kept fleeing.
        raw = copy.deepcopy(RAW)
        raw["bld"], raw["outside"], raw["weapon"] = None, True, None
        raw["zombies"] = ([{"dx": -0.5, "dy": -0.5, "d": 0.7, "seen": True, "chasing": True}]
                          + [{"dx": 20, "dy": -22, "d": 30, "seen": False, "chasing": False}] * 40)
        s = summarize(raw, Memory(), random.Random(1))
        self.assertEqual(strategy.plan(s.percept, s.legal).goal, "fight")

    def test_chasing_zombie_out_of_sight_can_be_fought(self):
        raw = copy.deepcopy(RAW)
        raw["zombies"] = [{"dx": 0, "dy": 3, "d": 3, "seen": False, "chasing": True}]
        self.assertIn("fight", summarize(raw, Memory(), random.Random(1)).legal)

    def test_keeps_running_goal_unless_something_is_much_better(self):
        s = summarize(RAW, Memory(), random.Random(1))
        plan = strategy.plan(s.percept, s.legal, current_goal="loot_here", current_running=True)
        self.assertIn(plan.goal, ("loot_here", "drink", "secure_building"))
        if plan.goal == "loot_here":
            self.assertEqual(plan.source, "keep")

    def test_llm_pick_sticks_while_it_runs(self):
        # in game, rules and LLM overruled each other every few seconds; now the LLM's pick is kept
        raw = copy.deepcopy(RAW)
        raw["bld"]["doorsOpen"] = 0   # an open door with a zombie around is urgent; that's tested below
        s = summarize(raw, Memory(), random.Random(1))
        plan = strategy.plan(s.percept, s.legal, current_goal="wait", current_running=True, current_source="AI")
        self.assertEqual((plan.goal, plan.source), ("wait", "keep"))

    def test_llm_pick_gives_way_to_an_emergency(self):
        raw = copy.deepcopy(RAW)
        raw["bld"] = None
        raw["zombies"] = [{"dx": 0, "dy": 6, "d": 6, "seen": True, "chasing": True}] * 5
        s = summarize(raw, Memory(), random.Random(1))
        plan = strategy.plan(s.percept, s.legal, current_goal="wait", current_running=True, current_source="AI")
        self.assertEqual(plan.goal, "flee")

    def test_llm_only_chooses_among_close_options(self):
        s = summarize(RAW, Memory(), random.Random(1))
        plan = strategy.plan(s.percept, s.legal)
        if not plan.clear:
            top = plan.scores[plan.ranked[0]]
            self.assertLessEqual(len(plan.candidates), strategy.MAX_CANDIDATES)
            self.assertTrue(all(plan.scores[g] >= top - strategy.CLEAR_MARGIN for g in plan.candidates))
            self.assertEqual(plan.candidates[0], plan.goal)
        else:
            self.assertEqual(plan.candidates, [])


class BridgeTests(unittest.TestCase):
    def make_bridge(self, tmp):
        import argparse
        args = argparse.Namespace(lua_dir=tmp, log_dir=tmp, no_llm=True, model="none", ollama=None, port=0)
        return bridge_mod.Bridge(args)

    def intent(self, b):
        return (b.intent_path.read_text(encoding="utf-8").split("|")[:2])

    def test_finished_task_is_restarted_or_replaced(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            b = self.make_bridge(tmp)
            raw = copy.deepcopy(RAW)
            raw["zombies"], raw["bld"]["doorsOpen"] = [], 0
            b.on_percept(raw)
            seq, goal = self.intent(b)
            raw = copy.deepcopy(raw)
            raw["task"] = {"seq": int(seq), "goal": goal, "status": "done", "msg": "", "phase": "start", "age": 900}
            b.on_percept(raw)
            seq2, _ = self.intent(b)
            self.assertEqual(int(seq2), int(seq) + 1)   # a new order went out, even if it's the same goal

    def test_an_ended_task_from_another_order_is_noticed(self):
        # an order from before a bridge restart finished: the bridge must not wait on its own goal forever
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            b = self.make_bridge(tmp)
            raw = copy.deepcopy(RAW)
            raw["zombies"], raw["bld"]["doorsOpen"] = [], 0
            b.on_percept(raw)
            seq, _ = self.intent(b)
            raw = copy.deepcopy(raw)
            raw["ack"] = int(seq) + 5
            raw["task"] = {"seq": int(seq) + 5, "goal": "sleep", "status": "done", "msg": "woke up", "phase": "asleep", "age": 400}
            b.on_percept(raw)
            self.assertEqual(int(self.intent(b)[0]), int(seq) + 6)

    def test_secure_building_rests_after_finishing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            b = self.make_bridge(tmp)
            raw = copy.deepcopy(RAW)
            b.on_percept(raw)
            seq, _ = self.intent(b)
            raw = copy.deepcopy(raw)
            raw["task"] = {"seq": int(seq), "goal": "secure_building", "status": "done", "msg": "", "phase": "start",
                           "age": 900}
            b.current["goal"] = "secure_building"
            b.on_percept(raw)
            self.assertNotIn("secure_building", b.situ.legal)
            self.assertNotEqual(self.intent(b)[1], "secure_building")


def outside(raw, zombies=()):
    raw = copy.deepcopy(raw)
    raw["bld"], raw["outside"], raw["room"] = None, True, None
    raw["zombies"] = list(zombies)
    return raw


class SurvivalTests(unittest.TestCase):
    """Phase 2: home base, nights, sleep, weight."""

    def test_scattered_zombies_far_off_are_not_a_horde(self):
        # in game: 16 spread over 22-40 tiles of town, none chasing or in sight. The AI "fled" on the spot.
        zs = ([{"dx": 0, "dy": -24, "d": 24, "seen": False, "chasing": False}] * 6
              + [{"dx": 30, "dy": 0, "d": 30, "seen": False, "chasing": False}] * 7
              + [{"dx": -35, "dy": 5, "d": 35.4, "seen": False, "chasing": False}] * 3)
        s = summarize(outside(RAW, zs), Memory(), random.Random(1))
        self.assertNotIn("flee", s.legal)   # nothing within 20 tiles to run from
        self.assertNotEqual(strategy.plan(s.percept, s.legal).goal, "hide")

    def test_hide_from_outside_runs_into_a_building_away_from_the_zombies(self):
        raw = outside(RAW, [{"dx": 0, "dy": 6, "d": 6, "seen": True, "chasing": False}] * 3)
        raw["buildings"] = [
            {"id": "a", "d": 8, "dir": "S", "tx": 10500, "ty": 9807, "tz": 0, "rooms": ["kitchen"], "looted": True},
            {"id": "b", "d": 14, "dir": "N", "tx": 10500, "ty": 9786, "tz": 0, "rooms": ["bedroom"], "looted": False},
            {"id": "c", "d": 45, "dir": "E", "tx": 10545, "ty": 9800, "tz": 0, "rooms": ["bedroom"], "looted": False},
        ]
        s = summarize(raw, Memory(), random.Random(1))
        self.assertEqual(s.args["hide"], (10500, 9786, 0))   # not the one the zombies stand next to

    def test_home_is_described_and_can_be_walked_to(self):
        raw = copy.deepcopy(RAW)
        raw["home"] = {"x": 10460, "y": 9800, "z": 0, "d": 40.5, "dir": "W", "here": False}
        s = summarize(raw, Memory(), random.Random(1))
        self.assertEqual(s.percept["home"], "home base 40 tiles W")
        self.assertEqual(s.args["retreat_home"], (10460, 9800, 0))
        raw["home"]["here"], raw["bld"]["home"] = True, True
        s = summarize(raw, Memory(), random.Random(1))
        self.assertEqual(s.percept["home"], "you are at home base")
        self.assertTrue(s.percept["where"].startswith("inside home base"))
        self.assertNotIn("retreat_home", s.legal)

    def test_dusk_outside_goes_home_or_shelters_when_home_is_far(self):
        raw = outside(RAW)
        raw["time"] = {"day": 1, "hour": 20, "min": 40, "dawn": 6, "dusk": 21}
        raw["moodles"] = {}
        raw["home"] = {"x": 10460, "y": 9800, "z": 0, "d": 40, "dir": "W", "here": False}
        s = summarize(raw, Memory(), random.Random(1))
        self.assertEqual(strategy.plan(s.percept, s.legal).goal, "retreat_home")
        raw["home"]["d"] = 300
        s = summarize(raw, Memory(), random.Random(1))
        self.assertEqual(strategy.plan(s.percept, s.legal).goal, "hide")
        self.assertEqual(len(s.args["hide"]), 3)

    def test_stays_home_at_sunset(self):
        # in game: at home 20 minutes before sunset, "next house" outscored everything indoors, so the AI
        # walked out, got sent home, and walked out again
        raw = copy.deepcopy(RAW)
        raw["time"] = {"day": 1, "hour": 21, "min": 14, "dawn": 7.1, "dusk": 21.6}
        raw["bld"].update(doorsOpen=0, searched=9, home=True, bed=True)
        raw["home"] = {"x": 10500, "y": 9800, "z": 0, "d": 1, "dir": "HERE", "here": True}
        raw["moodles"], raw["zombies"] = {}, []
        s = summarize(raw, Memory(), random.Random(1))
        self.assertNotIn(strategy.plan(s.percept, s.legal).goal, ("loot_building", "explore"))

    def test_sleeps_at_night_at_a_closed_up_home(self):
        raw = copy.deepcopy(RAW)
        raw["time"] = {"day": 2, "hour": 23, "min": 30, "dawn": 6, "dusk": 21}
        raw["bld"].update(doorsOpen=0, searched=9, home=True, bed=True)
        raw["home"] = {"x": 10500, "y": 9800, "z": 0, "d": 1, "dir": "HERE", "here": True}
        raw["moodles"], raw["zombies"] = {"tired": 1}, []
        s = summarize(raw, Memory(), random.Random(1))
        self.assertEqual(strategy.plan(s.percept, s.legal).goal, "sleep")

    def test_no_sleep_with_a_zombie_in_sight(self):
        raw = copy.deepcopy(RAW)
        raw["moodles"] = {"tired": 3}
        raw["zombies"] = [{"dx": 5, "dy": 0, "d": 5, "seen": True, "chasing": False}]
        self.assertNotIn("sleep", summarize(raw, Memory(), random.Random(1)).legal)

    def test_heavy_bag_sheds_junk(self):
        raw = copy.deepcopy(RAW)
        raw["bld"]["doorsOpen"], raw["zombies"], raw["moodles"] = 0, [], {}
        raw["weight"], raw["junk"] = 11.5, {"drop": 7.0, "store": 0}
        s = summarize(raw, Memory(), random.Random(1))
        self.assertEqual(strategy.plan(s.percept, s.legal).goal, "drop_weight")
        raw["weight"] = 6   # light enough: junk can wait
        self.assertNotIn("drop_weight", summarize(raw, Memory(), random.Random(1)).legal)

    def test_hungry_eats_from_the_cupboards(self):
        raw = copy.deepcopy(RAW)
        raw["inv"]["food"], raw["moodles"], raw["zombies"] = [], {"hungry": 2}, []
        raw["bld"].update(doorsOpen=0, food=3, searched=9)   # with rooms left to search it is a close call
        s = summarize(raw, Memory(), random.Random(1))
        self.assertIn("3 food items in the cupboards here", s.percept["building"])
        self.assertEqual(strategy.plan(s.percept, s.legal).goal, "eat")

    def test_cornered_fights_back_instead_of_fetching_water(self):
        # the first death: flee kept failing ("stuck"), fight was ruled out, so the AI went for a drink and
        # bled out under two zombies
        raw = copy.deepcopy(RAW)
        raw["moodles"] = {"thirst": 2, "endurance": 2, "panic": 3, "pain": 2}
        raw["zombies"] = [{"dx": 1, "dy": 1, "d": 1.4, "seen": True, "chasing": True}] * 2
        s = summarize(raw, Memory(), random.Random(1))
        legal = [g for g in s.legal if g != "flee"]   # flee cooling down after it failed
        self.assertEqual(strategy.plan(s.percept, legal).goal, "fight")

    def test_bleeding_without_bandages_tears_a_shirt(self):
        raw = copy.deepcopy(RAW)
        raw["zombies"], raw["rags"] = [], True
        raw["wounds"] = [{"part": "Hand_R", "flags": ["bleeding", "laceration"]}]
        s = summarize(raw, Memory(), random.Random(1))
        self.assertIn("a spare shirt to tear into bandages", s.percept["inventory"]["medical"])
        self.assertEqual(strategy.plan(s.percept, s.legal).goal, "bandage")

    def test_bridge_stays_quiet_while_asleep(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            args = __import__("argparse").Namespace(lua_dir=tmp, log_dir=tmp, no_llm=True, model="none", ollama=None, port=0)
            b = bridge_mod.Bridge(args)
            raw = copy.deepcopy(RAW)
            raw["asleep"] = True
            b.on_percept(raw)
            self.assertFalse(b.intent_path.exists())
            self.assertEqual(b.status, "asleep")


class IntentLineTests(unittest.TestCase):
    def test_separators_and_newlines_are_removed(self):
        line = bridge_mod.intent_line(5, "explore", (40, -12, 0), say="I'll go | north\nnow", why="a|b", source="rules")
        self.assertEqual(line, "5|explore|40|-12|0|I'll go / north now|a/b|rules")
        self.assertEqual(line.count("|"), 7)

    def test_missing_args_are_blank(self):
        import bridge as bridge_mod
        self.assertEqual(bridge_mod.intent_line(1, "wait", ()), "1|wait||||||")


if __name__ == "__main__":
    unittest.main()
