"""Tests for the self-taught agent's side: reward, lives, the file link, the random policy, the main loop.

Run from the repo root:  python -m unittest discover -s tests
"""

import argparse
import copy
import gzip
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import reward  # noqa: E402
from agent.link import GameLink  # noqa: E402
from agent.lives import Lives  # noqa: E402
from agent.policies import ProbePolicy, RandomPolicy  # noqa: E402

OBS = {
    "who": {"name": "Chris Hooks", "save": "test"}, "born": 26.0,
    "t": {"age": 27.0, "day": 2, "hour": 9, "min": 30, "dark": 0}, "kills": 0,
    "pos": {"x": 10763.7, "y": 10697.7, "z": 0}, "health": 100, "stats": {"hunger": 0.1},
    "moodles": [], "body": [], "weight": 3.0, "maxWeight": 12,
    "inv": [{"name": "T-shirt", "type": "Tshirt_DefaultTEXTURE", "cat": "clothing", "w": 1, "worn": True}],
    "zombies": [], "where": {"outside": True}, "near": {"food": 0, "drink": 0, "medical": 0, "weapon": 0, "items": 0},
}
OPTIONS = [{"verb": "wait"}, {"verb": "rest"}, {"verb": "walk", "dir": "N", "dx": 0, "dy": -1, "zombies": 0}]


def later(obs, minutes=0, **changes):
    o = copy.deepcopy(obs)
    o["t"]["age"] = round(o["t"]["age"] + minutes / 60, 4)
    o.update(changes)
    return o


class RewardTests(unittest.TestCase):
    def setUp(self):
        self.progress = reward.LifeProgress()
        reward.start_life(OBS, self.progress)

    def test_staying_alive_pays_a_little(self):
        r, parts = reward.step(OBS, later(OBS, 10), self.progress)
        self.assertAlmostEqual(parts["alive"], 1.0, places=2)
        self.assertAlmostEqual(r, 1.0, places=2)

    def test_hunger_hurts_more_the_worse_it_gets(self):
        _, mild = reward.step(later(OBS, moodles={"hungry": 1}), later(OBS, 10, moodles={"hungry": 1}), self.progress)
        _, severe = reward.step(later(OBS, moodles={"hungry": 3}), later(OBS, 10, moodles={"hungry": 3}), self.progress)
        self.assertLess(severe["discomfort"], mild["discomfort"] * 5)   # 9x the level^2
        self.assertLess(severe["discomfort"] + severe["alive"], 0)       # severe hunger outweighs being alive

    def test_bleeding_and_lost_health_cost(self):
        hurt = later(OBS, 1, health=90, body=[{"part": "Hand_L", "flags": ["bleeding"]}])
        _, parts = reward.step(OBS, hurt, self.progress)
        self.assertAlmostEqual(parts["health"], -2.0)
        self.assertLess(parts["bleeding"], 0)
        bandaged = later(OBS, 1, health=90, body=[{"part": "Hand_L", "flags": ["bleeding", "bandaged"]}])
        _, parts = reward.step(OBS, bandaged, reward.LifeProgress())
        self.assertNotIn("bleeding", parts)

    def test_progress_counts_once(self):
        with_bat = later(OBS, 1, inv=OBS["inv"] + [{"name": "Baseball Bat", "type": "BaseballBat", "cat": "weapon"}],
                         where={"outside": False, "building": "100,200"})
        _, parts = reward.step(OBS, with_bat, self.progress)
        self.assertAlmostEqual(parts["new_items"], reward.NEW_ITEM)
        self.assertAlmostEqual(parts["new_building"], reward.NEW_BUILDING)
        _, again = reward.step(with_bat, later(with_bat, 1), self.progress)
        self.assertNotIn("new_items", again)
        self.assertNotIn("new_building", again)
        fresh = reward.LifeProgress()
        reward.start_life(OBS, fresh)
        self.assertNotIn("new_items", reward.step(OBS, later(OBS, 1), fresh)[1])   # the shirt it started in

    def test_wounds_are_not_new_items(self):
        bitten = later(OBS, 1, inv=OBS["inv"] + [{"name": "Base.Wound_RHand_Bite_Female", "type": "Wound_RHand_Bite_Female",
                                                  "cat": "clothing", "w": 0, "worn": True}])
        _, parts = reward.step(OBS, bitten, self.progress)
        self.assertNotIn("new_items", parts)

    def test_kills_and_death(self):
        _, parts = reward.step(OBS, later(OBS, 1, kills=2), self.progress)
        self.assertEqual(parts["kills"], 2 * reward.KILL)
        r, parts = reward.step(OBS, {"dead": True, "kills": 0}, self.progress)
        self.assertEqual(r, reward.DEATH)


class LivesTests(unittest.TestCase):
    def test_a_life_runs_from_first_sight_to_death(self):
        with tempfile.TemporaryDirectory() as tmp:
            lives = Lives(tmp)
            life, r, _, new, _ = lives.observe({"id": 1, "obs": OBS, "options": OPTIONS})
            self.assertTrue(new)
            self.assertEqual((life.number, life.name), (1, "Chris Hooks"))
            lives.observe({"id": 2, "obs": later(OBS, 30, kills=1), "options": OPTIONS})
            _, r, _, _, rec = lives.observe({"id": 3, "dead": True, "obs": {"dead": True, "kills": 1, "t": {"age": 28.0}}})
            self.assertEqual(r, reward.DEATH)
            self.assertEqual((rec["life"], rec["hours"], rec["kills"], rec["ended"]), (1, 2.0, 1, "died"))
            again = Lives(tmp)   # restarting the agent keeps the count and the history
            self.assertEqual((again.count, len(again.history)), (1, 1))
            other = later(OBS, 1)
            other["who"] = {"name": "Kate Smith", "save": "test"}
            life, *_ = again.observe({"id": 4, "obs": other, "options": OPTIONS})
            self.assertEqual((life.number, life.name), (2, "Kate Smith"))

    def test_restarting_the_agent_carries_on_with_the_same_character(self):
        with tempfile.TemporaryDirectory() as tmp:
            lives = Lives(tmp)
            lives.observe({"id": 1, "obs": OBS, "options": OPTIONS})
            lives.observe({"id": 2, "obs": later(OBS, 30, kills=1), "options": OPTIONS})
            lives.current.decisions = 2
            lives.save()
            total = lives.current.reward
            again = Lives(tmp)   # the agent restarted
            # an hour later the same character, carrying what the baseline picked up meanwhile
            bat = later(OBS, 90, kills=1, inv=OBS["inv"] + [{"name": "Baseball Bat", "type": "BaseballBat", "cat": "weapon"}])
            life, r, parts, new, finished = again.observe({"id": 3, "obs": bat, "options": OPTIONS})
            self.assertEqual((life.number, new, finished, again.count), (1, False, None, 1))
            self.assertTrue(again.resumed)
            self.assertEqual((r, parts), (0.0, {}))   # the time away isn't the last decision's doing
            self.assertEqual((life.decisions, life.kills), (2, 1))
            self.assertAlmostEqual(life.reward, total)
            life, r, parts, *_ = again.observe({"id": 4, "obs": later(bat, 10), "options": OPTIONS})
            self.assertFalse(again.resumed)
            self.assertAlmostEqual(parts["alive"], 1.0, places=2)
            self.assertNotIn("new_items", parts)   # the bat came while the agent was off
            _, _, _, _, rec = again.observe({"id": 5, "dead": True, "obs": {"dead": True, "kills": 1, "t": {"age": 29.0}}})
            self.assertEqual((rec["life"], rec["ended"], rec["hours"]), (1, "died", 3.0))

    def test_a_different_character_after_a_restart_ends_the_old_life(self):
        with tempfile.TemporaryDirectory() as tmp:
            lives = Lives(tmp)
            lives.observe({"id": 1, "obs": OBS, "options": OPTIONS})
            again = Lives(tmp)
            other = later(OBS, 1)
            other["who"] = {"name": "Kate Smith", "save": "test"}
            life, _, _, new, finished = again.observe({"id": 2, "obs": other, "options": OPTIONS})
            self.assertEqual((life.number, new, finished["life"], finished["ended"]), (2, True, 1, "left"))
            self.assertFalse(again.resumed)
            self.assertEqual(Lives(tmp).current.name, "Kate Smith")


class LinkTests(unittest.TestCase):
    def test_requests_and_answers_go_through_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            link = GameLink(tmp)
            self.assertIsNone(link.poll())
            (Path(tmp) / "obs.json").write_text(json.dumps({"id": 7, "obs": OBS, "options": OPTIONS}), encoding="utf-8")
            msg = link.poll()
            self.assertEqual(msg["id"], 7)
            self.assertIsNone(link.poll())   # the same request isn't handed out twice
            link.act(7, 2, "walk | north\nnow")
            self.assertEqual((Path(tmp) / "act.txt").read_text(encoding="utf-8"), "7|2|walk / north now\n")
            link.beat()
            self.assertEqual((Path(tmp) / "gym.txt").read_text(encoding="utf-8"), "on|1\n")
            (Path(tmp) / "obs.json").write_text('{"id": 8, "obs": {', encoding="utf-8")   # caught mid-write
            self.assertIsNone(link.poll())


class PolicyTests(unittest.TestCase):
    def test_random_policy_mostly_lets_things_finish(self):
        pol = RandomPolicy(random.Random(1))
        msg = {"options": [{"verb": "continue"}] + OPTIONS}
        picks = [pol.choose(msg)[0] for _ in range(700)]
        self.assertGreater(picks.count(0), picks.count(1) * 2)
        i, probs, _ = pol.choose(msg)
        self.assertAlmostEqual(sum(probs), 1.0)
        self.assertEqual(pol.choose({"options": []})[0], None)


class ProbeTests(unittest.TestCase):
    def test_probe_tries_each_verb_lets_it_finish_and_reports(self):
        pol = ProbePolicy(random.Random(1), tries=1)
        eat = {"verb": "eat", "name": "Apple", "type": "Apple", "cat": "food"}
        opts = OPTIONS + [eat]
        obs = later(OBS, 0, inv=OBS["inv"] + [{"name": "Apple", "type": "Apple", "cat": "food"}])
        i, _, _ = pol.choose({"options": opts, "obs": obs})
        self.assertEqual(opts[i]["verb"], "eat")   # eating comes before walking about
        i, _, _ = pol.choose({"options": [{"verb": "continue"}] + opts, "obs": obs, "last": {"verb": "eat", "status": "running"}})
        self.assertEqual(i, 0)
        i, _, _ = pol.choose({"options": opts, "obs": OBS, "last": {"verb": "eat", "status": "done", "age": 90}})
        self.assertNotEqual(opts[i]["verb"], "eat")   # tried once: enough
        self.assertEqual(pol.results[0]["lost"], {"Apple": 1})
        self.assertIn("eat          done 1", pol.report())

    def test_probe_takes_prerequisites_after_take_checks_are_complete(self):
        weapon = {"verb": "take", "name": "Kitchen Knife", "cat": "weapon", "d": 2}
        water = {"verb": "take", "name": "Water Bottle", "water": 0.8, "d": 3}
        options = [weapon, water, {"verb": "go_room", "name": "kitchen"}]
        pol = ProbePolicy(random.Random(1), tries=1)
        for verb in pol.TEST + pol.LATE:
            if verb not in ("drink", "equip"):
                pol.tally[verb]["done"] = 1
        i, _, _ = pol.choose({"options": options, "obs": OBS})
        self.assertEqual(options[i]["name"], "Water Bottle")
        pol = ProbePolicy(random.Random(1), tries=1)
        for verb in pol.TEST + pol.LATE:
            if verb != "equip":
                pol.tally[verb]["done"] = 1
        i, _, _ = pol.choose({"options": options, "obs": OBS})
        self.assertEqual(options[i]["name"], "Kitchen Knife")


class AgentLoopTests(unittest.TestCase):
    def test_decisions_are_answered_and_logged(self):
        from agent.run import Agent
        with tempfile.TemporaryDirectory() as tmp:
            a = Agent(argparse.Namespace(lua_dir=tmp, log_dir=tmp, port=0))
            a.handle({"id": 1, "reason": "idle", "obs": OBS, "options": OPTIONS})
            act = (Path(tmp) / "act.txt").read_text(encoding="utf-8").split("|")
            self.assertEqual(act[0], "1")
            self.assertIn(int(act[1]), range(len(OPTIONS)))
            a.handle({"id": 2, "reason": "done", "obs": later(OBS, 5), "options": OPTIONS, "last": {"verb": "wait", "status": "done"}})
            a.handle({"id": 3, "reason": "died", "dead": True, "obs": {"dead": True, "kills": 0, "t": {"age": 28}}, "options": []})
            a.exp.flush()
            lines = []
            for f in (Path(tmp) / "experience").glob("*.jsonl.gz"):
                with gzip.open(f, "rt", encoding="utf-8") as g:
                    lines += [json.loads(x) for x in g if x.strip()]
            self.assertEqual([x["id"] for x in lines], [1, 2, 3])
            self.assertAlmostEqual(lines[1]["parts"]["alive"], 0.5, places=2)
            self.assertTrue(lines[2]["dead"])
            self.assertEqual(lines[2]["reward"], reward.DEATH)
            snap = a.snapshot()
            self.assertEqual(len(snap["lives"]), 1)
            self.assertIsNone(snap["life"])


if __name__ == "__main__":
    unittest.main()
