"""Tests for the self-taught agent's side: reward, lives, the file link, the random policy, the main loop.

Run from the repo root:  python -m unittest discover -s tests
"""

import argparse
import copy
import gzip
import json
import math
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

    def step(self, a, b, inf=0.0):
        return reward.step(a, b, self.progress, inf=inf)

    def test_staying_alive_pays_steadily(self):
        r, parts, _ = self.step(OBS, later(OBS, 10))
        self.assertAlmostEqual(parts["alive"], 10.0, places=2)
        self.assertAlmostEqual(r, 10.0, places=2)

    def test_feeling_bad_costs_nothing(self):
        bad = {"hungry": 3, "thirst": 3, "panic": 4, "pain": 3, "stress": 2, "wet": 2}
        _, parts, _ = self.step(later(OBS, moodles=bad), later(OBS, 10, moodles=bad))
        self.assertEqual(set(parts), {"alive"})

    def test_getting_hurt_costs_and_healing_pays_it_back(self):
        hurt = later(OBS, 1, health=90)
        self.assertAlmostEqual(self.step(OBS, hurt)[1]["health"], -20.0)
        self.assertAlmostEqual(self.step(hurt, later(hurt, 1, health=100))[1]["health"], 20.0)

    def test_a_wound_costs_until_it_is_bandaged(self):
        cut = later(OBS, 1, body=[{"part": "Hand_L", "flags": ["bleeding", "laceration"]}])
        self.assertAlmostEqual(self.step(OBS, cut)[1]["wounds"], -reward.PER_UNTREATED)
        bandaged = later(cut, 1, body=[{"part": "Hand_L", "flags": ["bleeding", "laceration", "bandaged"]}])
        self.assertAlmostEqual(self.step(cut, bandaged)[1]["wounds"], reward.PER_UNTREATED)
        self.assertAlmostEqual(self.step(bandaged, cut)[1]["wounds"], -reward.PER_UNTREATED)   # the bandage comes off

    def test_protection_pays_on_and_costs_off_so_a_loop_earns_nothing(self):
        bare = later(OBS, 0, protection=[{"part": p, "bite": 0, "scratch": 0} for p in ("Torso_Upper", "Neck")])
        jacket = later(bare, 1, protection=[{"part": "Torso_Upper", "bite": 40, "scratch": 60}, {"part": "Neck", "bite": 0, "scratch": 0}])
        on = self.step(bare, jacket)[1]["protection"]
        self.assertAlmostEqual(on, reward.PROTECTION * 100 / 400)
        off = self.step(jacket, later(bare, 2))[1]["protection"]
        self.assertAlmostEqual(on + off, 0.0)
        torn = later(jacket, 1, protection=[{"part": "Torso_Upper", "bite": 0, "scratch": 0}, {"part": "Neck", "bite": 0, "scratch": 0}])
        self.assertLess(self.step(jacket, torn)[1]["protection"], 0)   # a hole over the torso: the jacket's share goes

    def test_the_infection_is_the_death_it_brings(self):
        bitten = later(OBS, 1, knox=True, body=[{"part": "ForeArm_R", "flags": ["bite", "bleeding"]}])
        r, parts, inf = self.step(later(OBS, knox=False), bitten)
        self.assertEqual((parts["infection"], inf), (reward.DEATH, 1.0))
        again = later(bitten, 1, body=bitten["body"] + [{"part": "Hand_L", "flags": ["bite"]}])
        self.assertNotIn("infection", self.step(bitten, again, inf)[1])   # charged once
        _, parts, _ = self.step(again, {"dead": True, "kills": 0}, inf)
        self.assertNotIn("death", parts)                                   # the death was already charged
        tree = later(OBS, 1, knox=False, body=[{"part": "Hand_L", "flags": ["scratch"]}])
        self.assertNotIn("infection", self.step(later(OBS, knox=False), tree)[1])   # not infected: no charge

    def test_without_the_games_flag_a_zombie_wound_charges_its_chance(self):
        scratched = later(OBS, 1, body=[{"part": "Hand_L", "flags": ["scratch"]}])
        _, parts, inf = self.step(OBS, scratched)
        self.assertAlmostEqual(parts["infection"], 0.07 * reward.DEATH)
        _, parts, _ = self.step(scratched, {"dead": True, "kills": 0}, inf)
        self.assertAlmostEqual(parts["death"], 0.93 * reward.DEATH)   # a life costs one death in all

    def test_a_death_outweighs_a_long_life_and_all_its_damage(self):
        self.assertGreater(-reward.DEATH, reward.ALIVE_PER_MIN * 16 * 60)
        self.assertGreater(-reward.DEATH, reward.PER_HEALTH * 100 + reward.PER_UNTREATED * 17 + reward.PROTECTION)

    def test_older_records_are_rescored(self):
        v1 = {"reward": -5.6, "parts": {"alive": 1.0, "health": -2.0, "discomfort": -5.0, "bleeding": -0.1, "new_building": 0.5}}
        # 10 minutes alive and a new building; health, discomfort and bleeding are left to the observations
        self.assertEqual(reward.rescore(v1), (10 + 5, 10.0))
        self.assertEqual(reward.rescore({"dead": True, "reward": -20.0, "parts": {"death": -20.0, "kills": 1.0}}), (10.0, 0.0))
        self.assertEqual(reward.rescore({**v1, "resumed": True}), (0.0, 0.0))
        v2 = {"reward": -13.0, "parts": {"alive": 7.0, "hurt": -20.0}, "reward_v": 2}
        self.assertEqual(reward.rescore(v2), (7.0, 7.0))

    def test_progress_counts_once(self):
        with_bat = later(OBS, 1, inv=OBS["inv"] + [{"name": "Baseball Bat", "type": "BaseballBat", "cat": "weapon"}],
                         where={"outside": False, "building": "100,200"})
        _, parts, _ = self.step(OBS, with_bat)
        self.assertAlmostEqual(parts["new_items"], reward.NEW_ITEM)
        self.assertAlmostEqual(parts["new_building"], reward.NEW_BUILDING)
        _, again, _ = self.step(with_bat, later(with_bat, 1))
        self.assertNotIn("new_items", again)
        self.assertNotIn("new_building", again)
        fresh = reward.LifeProgress()
        reward.start_life(OBS, fresh)
        self.assertNotIn("new_items", reward.step(OBS, later(OBS, 1), fresh)[1])   # the shirt it started in

    def test_wounds_are_not_new_items(self):
        bitten = later(OBS, 1, inv=OBS["inv"] + [{"name": "Base.Wound_RHand_Bite_Female", "type": "Wound_RHand_Bite_Female",
                                                  "cat": "clothing", "w": 0, "worn": True}])
        self.assertNotIn("new_items", self.step(OBS, bitten)[1])

    def test_kills_and_death(self):
        _, parts, _ = self.step(OBS, later(OBS, 1, kills=2))
        self.assertEqual(parts["kills"], 2 * reward.KILL)
        r, parts, _ = self.step(OBS, {"dead": True, "kills": 0})
        self.assertEqual(r, reward.DEATH)   # at full health the body's value is 0, so nothing else goes with it


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

    def test_deaths_are_counted_per_save_and_survive_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            lives = Lives(tmp)
            for i in range(3):
                lives.observe({"id": i, "obs": later(OBS, 1), "options": OPTIONS})
                _, _, _, _, rec = lives.observe({"id": 9, "dead": True, "obs": {"dead": True, "t": {"age": 5.0}}})
                self.assertEqual(rec["world_deaths"], i + 1)
            again = Lives(tmp)
            self.assertEqual(again.deaths_in("test"), 3)
            self.assertFalse(again.new_world_due("test"))
            again.world_deaths["test"] = 100
            self.assertTrue(again.new_world_due("test"))

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
            self.assertAlmostEqual(parts["alive"], 10.0, places=1)
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
        water = {"verb": "take", "name": "Water Bottle", "fluid": 0.8, "d": 3}
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
        pol = ProbePolicy(random.Random(1), tries=1)
        i, _, _ = pol.choose({"options": options + [{"verb": "drink", "name": "Water Bottle"}], "obs": OBS})
        self.assertEqual(i, len(options))   # use the bottle already in the bag before taking another


class AgentLoopTests(unittest.TestCase):
    def test_a_second_agent_cannot_take_the_dashboard_port(self):
        from agent.run import Agent
        with tempfile.TemporaryDirectory() as tmp:
            first = Agent(argparse.Namespace(lua_dir=tmp, log_dir=tmp, port=0)).server()
            try:
                port = first.server_address[1]
                with self.assertRaises(OSError):   # on Windows a plain HTTPServer would have bound it too
                    Agent(argparse.Namespace(lua_dir=tmp, log_dir=tmp, port=port)).server()
            finally:
                first.server_close()

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
            self.assertAlmostEqual(lines[1]["parts"]["alive"], 5.0, places=2)
            self.assertEqual(lines[1]["reward_v"], reward.VERSION)
            self.assertTrue(lines[2]["dead"])
            self.assertEqual(lines[2]["reward"], reward.DEATH)
            snap = a.snapshot()
            self.assertEqual(len(snap["lives"]), 1)
            self.assertIsNone(snap["life"])



class SleepGateStaticTest(unittest.TestCase):
    def test_sleep_options_follow_game_menu_conditions(self):
        src = (Path(__file__).resolve().parent.parent / "mod/AIvZ/42/media/lua/client/AIvZGym.lua").read_text(encoding="utf-8")
        self.assertIn("local function sleepBlock(p)", src)
        self.assertIn("CharacterStat.FATIGUE", src)
        self.assertIn("getLastHourSleeped", src)
        self.assertIn("if p:getSquare() and not noSleep then", src)

if __name__ == "__main__":
    unittest.main()


class HearingTests(unittest.TestCase):
    def tone(self, freq, amp, n=2000, rate=8000):
        return [amp * math.sin(2 * math.pi * freq * i / rate) for i in range(n)]

    def test_features_are_absolute_and_stereo_aware(self):
        from agent import hearing
        loud = hearing.analyse(self.tone(1000, 0.5), [0.0] * 2000, 8000)
        quiet = hearing.analyse(self.tone(1000, 0.05), [0.0] * 2000, 8000)
        self.assertLess(loud["balance"], -0.9)   # all on the left
        self.assertAlmostEqual(loud["db_l"] - quiet["db_l"], 20.0, delta=0.5)   # not normalised
        band = hearing.BANDS_HZ.index(1000)
        self.assertEqual(max(range(len(loud["bands_db"])), key=loud["bands_db"].__getitem__), band)

    def test_without_a_source_hearing_says_unavailable(self):
        from agent.hearing import Hearing
        snap = Hearing().snapshot(decision_id=7, game_age=3.5, speed=1)
        self.assertFalse(snap["available"])
        self.assertIn("reason", snap)
        self.assertNotIn("windows", snap)

    def test_history_marks_gaps_and_level_changes(self):
        from agent.hearing import Hearing

        class Src:
            available = True
            def __init__(s, w): s.w = w
            def read(s): w, s.w = s.w, []; return w
        tone = self.tone(500, 0.1, 800)
        loud = self.tone(500, 0.4, 800)
        dur = 0.1
        h = Hearing(Src([(1.0, tone, tone, 8000), (1.1, loud, loud, 8000), (2.0, tone, tone, 8000)]))
        snap = h.snapshot(1)
        ws = snap["windows"]
        self.assertGreater(ws[1]["d_db"], 10)
        self.assertTrue(ws[2].get("gap"))
        self.assertEqual(snap["gaps"], 1)


class CreationTests(unittest.TestCase):
    def test_trait_choices_are_logged_without_starting_a_life(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(lua_dir=tmp, log_dir=tmp, policy="random", port=0)
            from agent.run import Agent
            agent = Agent(args)
            msg = {"id": 5, "creation": True, "reason": "creation", "obs": {"selected": []},
                   "options": [{"verb": "add_trait", "name": "Lucky", "cost": 4}, {"verb": "finish_creation"}]}
            agent.handle(msg)
            self.assertEqual(agent.lives.count, 0)
            self.assertIsNone(agent.lives.current)
            self.assertTrue((Path(tmp) / "act.txt").exists())


class GymLeakageTests(unittest.TestCase):
    """Static guard (the Lua is not run here): the gym must not hand the agent hidden zombie AI state."""

    def test_gym_does_not_expose_chase_target(self):
        base = Path(__file__).resolve().parent.parent / "mod/AIvZ/42/media/lua/client"
        for name in ("AIvZGym.lua", "AIvZGymActions.lua"):
            code = "\n".join(l.split("--")[0] for l in (base / name).read_text(encoding="utf-8").splitlines())
            self.assertNotIn("getTarget", code, name)
            self.assertNotIn("chasing", code, name)


class ExerciseLuaStaticTest(unittest.TestCase):
    def test_fitness_action_gets_exercise_type_and_duration(self):
        import pathlib
        src = pathlib.Path(__file__).resolve().parents[1].joinpath(
            "mod/AIvZ/42/media/lua/client/AIvZGymActions.lua").read_text()
        self.assertIn("ISFitnessAction:new(p, o.data.name, o.data.minutes, o.data.data, o.data.data.type)", src)
        self.assertIn("contains(need, true)", src)

    def test_executors_read_option_fields_from_data(self):
        # An executor gets the option as { verb, info, data } (add() in AIvZGym.lua); its own fields are in
        # o.data. Gym 0.4.4 read o.minutes / o.blocked, which are always nil, so every exercise failed.
        import re
        base = Path(__file__).resolve().parent.parent / "mod/AIvZ/42/media/lua/client"
        for name in ("AIvZGym.lua", "AIvZGymActions.lua"):
            src = (base / name).read_text(encoding="utf-8")
            for block in re.findall(r"^G\.X\.\w+ = \{.*?^\}", src, re.M | re.S):
                code = "\n".join(l.split("--")[0] for l in block.splitlines())
                fields = set(re.findall(r"\bo\.(\w+)", code))
                self.assertLessEqual(fields, {"data", "info", "verb"}, f"{name}: {block.splitlines()[0]}")


class MenuPrerequisiteStaticTest(unittest.TestCase):
    """Gym 0.4.6: option prerequisites copied from the game's menus (code only, not run in the game)."""

    def setUp(self):
        base = Path(__file__).resolve().parent.parent / "mod/AIvZ/42/media/lua/client"
        self.src = (base / "AIvZGym.lua").read_text(encoding="utf-8")

    def test_window_option_does_not_list_lock_state(self):
        line = next(l for l in self.src.splitlines() if "local info = { d = r1(e.d), open = e.open" in l)
        self.assertNotIn("locked", line)

    def test_smash_needs_closed_window_and_clear_glass_needs_held_item(self):
        self.assertIn("not e.smashed and not e.open and ns < 2", self.src)
        self.assertIn("e.glass and p:getPrimaryHandItem() and ng < 1", self.src)

    def test_drop_skips_favourites(self):
        self.assertIn("isFavorite()", self.src)
