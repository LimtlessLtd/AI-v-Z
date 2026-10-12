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
from agent.policies import ProbePolicy, RandomPolicy, robust_spread  # noqa: E402

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
        # dying gives back what the body's value is below 0 (Φ is 0 once dead): at most all the health and wounds.
        # Clothing and a weapon only add to Φ, so they make a death cost more, never less (reward version 4 puts
        # full cover above a death on purpose: 2,000).
        self.assertGreater(-reward.DEATH, reward.PER_HEALTH * 100 + reward.PER_UNTREATED * 17)
        _, parts, _ = self.step(later(OBS, 1, health=0), {"dead": True, "kills": 0})
        self.assertLess(parts["death"] + parts["body"], 0)

    def test_a_weapon_in_the_hands_pays_by_its_damage_and_unequipping_costs_the_same(self):
        bat = {"name": "Baseball Bat", "cat": "weapon", "dmg": 1.1, "ranged": False}
        armed = later(OBS, 1, held=bat)
        on = self.step(OBS, armed)[1]["weapon"]
        self.assertAlmostEqual(on, reward.WEAPON * 1.1 / reward.WEAPON_FULL, places=3)   # parts are kept to 4 places
        self.assertAlmostEqual(on + self.step(armed, later(OBS, 2))[1]["weapon"], 0.0)
        axe = dict(bat, dmg=3.0)
        self.assertAlmostEqual(reward.body(later(OBS, held=axe))["weapon"], 1.0)   # capped
        for held in (dict(bat, ranged=True), {"name": "Apple", "cat": "food"}):
            self.assertEqual(reward.body(later(OBS, held=held))["weapon"], 0.0)   # a gun without ammo actions, food

    def test_version_4_makes_a_garment_worth_more_than_minutes(self):
        shoes = later(OBS, 1, protection=[{"part": f, "bite": 10, "scratch": 20} for f in ("Foot_L", "Foot_R")]
                      + [{"part": "Head", "bite": 0, "scratch": 0}] * 15)
        bare = later(OBS, 0, protection=[{"part": "Head", "bite": 0, "scratch": 0}] * 17)
        self.assertGreater(self.step(bare, shoes)[1]["protection"], 30)   # shoes: about 35, half an hour of being alive

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

    def test_one_far_off_score_does_not_flatten_the_choice(self):
        # 2026-10-12: one option at -6,729 among -500 to -1,000 stretched the standard deviation, and every pick
        # came out near 1/n (the owner chose the median distance instead)
        q = [-500.0, -600.0, -700.0, -800.0, -900.0, -1000.0, -6729.0]
        mean = sum(q) / len(q)
        sd = math.sqrt(sum((x - mean) ** 2 for x in q) / len(q))
        self.assertLess(robust_spread(q), sd / 5)
        self.assertAlmostEqual(robust_spread([1.0, 2.0, 3.0]), 1.4826)
        self.assertGreater(robust_spread([0.0, 0.0, 0.0, 0.0, 9.0]), 0)   # most equal: the standard deviation


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

    def test_decisions_are_saved_while_the_game_sends_none(self):
        """Backlog N4: the 30 s check also runs while no decision arrives, so a stalled game loses nothing."""
        from agent.run import ExperienceLog
        with tempfile.TemporaryDirectory() as tmp:
            log = ExperienceLog(tmp)
            log.add({"id": 1})
            log.flush_stale()
            self.assertEqual(list(Path(tmp).glob("*.jsonl.gz")), [])   # too recent: kept for the next batch
            log.flushed -= 31
            log.flush_stale()
            with gzip.open(next(Path(tmp).glob("*.jsonl.gz")), "rt", encoding="utf-8") as g:
                self.assertEqual([json.loads(x)["id"] for x in g if x.strip()], [1])
            self.assertEqual(log.lines, [])



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
            # getTargetAlpha is the game's perceivable fade/visibility result (observation audit §1),
            # used by the local comparison diagnostic. Only getTarget() reveals hidden chase intent.
            self.assertNotRegex(code, r"\bgetTarget\b", name)
            self.assertNotIn("chasing", code, name)


class ExerciseLuaStaticTest(unittest.TestCase):
    def test_fitness_action_gets_exercise_type_and_duration(self):
        import pathlib
        src = pathlib.Path(__file__).resolve().parents[1].joinpath(
            "mod/AIvZ/42/media/lua/client/AIvZGymActions.lua").read_text()
        self.assertIn("ISFitnessAction:new(p, o.data.name, o.data.minutes, o.data.data, o.data.data.type)", src)
        self.assertIn("contains(need, true)", src)

    def test_the_screens_hand_off_comes_before_the_exercise(self):
        """Gym 0.4.37 (backlog G2): ISFitnessUI:equipItems' hand-off, then the action."""
        src = (Path(__file__).resolve().parent.parent / "mod/AIvZ/42/media/lua/client/AIvZGymActions.lua").read_text(encoding="utf-8")
        x = src[src.index("G.X.exercise = {"):]
        self.assertLess(x.index("fitnessHandOff(p, d)"), x.index("Q(act)"))
        self.assertIn('if d.prop == "primary" or d.prop == "switch" then', src)

    def test_hotwire_as_the_radial_menu_offers_it(self):
        """Gym 0.4.37 (backlog G5): ISVehicleMenu.lua:106-118, and ISVehicleMenu.onHotwire."""
        base = Path(__file__).resolve().parent.parent / "mod/AIvZ/42/media/lua/client"
        src = (base / "AIvZGymActions.lua").read_text(encoding="utf-8")
        self.assertIn("(p:getPerkLevel(Perks.Electricity) >= 1 and p:getPerkLevel(Perks.Mechanics) >= 2) or p:hasTrait(CharacterTrait.BURGLAR)", src)
        self.assertIn("ISVehicleMenu.onHotwire(p)", src)
        gym = (base / "AIvZGym.lua").read_text(encoding="utf-8")
        self.assertIn("pf:getFluidType() == FluidType.Bleach", gym)   # the Drink menu's own test (backlog G4)

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


class DecisionRateStaticTest(unittest.TestCase):
    """Gym 0.4.21 (owner's decision, backlog N7): while an option runs, decisions come at a steady game-time rate,
    and being hurt no longer asks at once. Gym 0.4.23 (owner's decision, 2026-10-12): a zombie coming within 4
    tiles asks at once again (code only, not run in the game here)."""

    def setUp(self):
        base = Path(__file__).resolve().parent.parent / "mod/AIvZ/42/media/lua/client"
        self.src = (base / "AIvZGym.lua").read_text(encoding="utf-8")
        body = self.src[self.src.index("function G.needDecision"):]
        body = body[:body.index("\nend\n")]
        self.code = "\n".join(l.split("--")[0] for l in body.splitlines())

    def test_running_options_are_rechecked_at_a_steady_rate(self):
        code = self.code
        self.assertIn("if GS.gt - GS.lastReq < STEADY then return nil end", code)
        self.assertNotIn("DECIDE_GAP", self.src)
        self.assertNotIn("RECHECK", self.src)
        self.assertLess(code.index("STEADY"), code.index('"hurt"'))   # hurt waits for the steady rate
        self.assertTrue(code.rstrip().endswith('return "still at it"'))

    def test_a_zombie_coming_close_asks_at_once(self):
        code = self.code
        self.assertLess(code.index('"zombie close"'), code.index("STEADY"))
        self.assertIn("if n > (GS.lastClose or 0) then return \"zombie close\" end", code)
        # the count it compares with is taken at every request, so one zombie asks once
        req = self.src[self.src.index("function G.request"):]
        self.assertIn("GS.lastClose = n", req[:req.index("\nend\n")])


class SpawnStaticTest(unittest.TestCase):
    """Gym 0.4.33 (owner's decision, 2026-10-12 evening): a new life starts at one of the game's own start points of a
    town picked at random on the spawn screen. Gym 0.4.24-0.4.32 swapped them for a random room square, and lives
    started on wall lines and water (code only, not run in the game here)."""

    def setUp(self):
        base = Path(__file__).resolve().parent.parent / "mod/AIvZ/42/media/lua/client"
        self.src = (base / "AIvZGym.lua").read_text(encoding="utf-8")

    def test_a_random_town_then_the_games_own_points(self):
        step = self.src[self.src.index("function G.respawnStep"):]
        step = step[:step.index("\nend\n")]
        self.assertLess(step.index("lb.selected = towns[ZombRand(#towns) + 1]"), step.index("w.mapSpawnSelect:clickNext()"))
        for gone in ("randomizeSpawn", "G.RANDOM_SPAWN", "selectedRegion =", "GS.deaths"):
            self.assertNotIn(gone, self.src)


class FloorStaticTest(unittest.TestCase):
    """Gym 0.4.35 (mod 0.5.6), backlog G8: half or all of a pile on the ground, a bag on the ground as a container of
    its own, and dragging a corpse, as the game's menus do them (code only, not run in the game here)."""

    def setUp(self):
        base = Path(__file__).resolve().parent.parent / "mod/AIvZ/42/media/lua/client"
        self.src = (base / "AIvZGym.lua").read_text(encoding="utf-8")
        self.mod = (base / "AIvZ.lua").read_text(encoding="utf-8")

    def test_piles_offer_half_above_two_and_all_above_one(self):
        self.assertIn('if n > 2 then\n\t\t\tinfo.how, info.n = "half", math.ceil(n / 2)', self.src)
        self.assertIn('if n > 1 then\n\t\t\tinfo.how, info.n = "all", n', self.src)
        grab = self.src[self.src.index("G.X.pick_up = {"):self.src.index("G.X.drag_corpse = {")]
        self.assertIn("for _, f in ipairs(o.data.items or { o.data }) do", grab)

    def test_a_bag_on_the_ground_is_searched_without_filling_it(self):
        self.assertIn('it:getCategory() == "Container" and instanceof(it, "InventoryContainer")', self.src)
        self.assertIn("if not o.data.bag and not o.data.c:isExplored() then", self.src)
        self.assertIn("local obj = bag and bag:getWorldItem() or c:getParent()", self.mod)

    def test_dragging_a_corpse(self):
        self.assertIn('if p:isDraggingCorpse() then\n\t\tadd(list, "drop_corpse", {})', self.src)
        self.assertIn("p:setDoContinueGrapple(false)", self.src)
        self.assertIn("not so:isAnimal()", self.src)
        self.assertIn("act.allowedWhileDraggingCorpses = true", self.mod)   # the queue refuses other walks


class BarricadeStaticTest(unittest.TestCase):
    """Gym 0.4.36, backlog G14b: Barricade and Unbarricade with planks, under the menu's rules, built the way the
    menu's cursor builds it (code only, not run in the game here)."""

    def setUp(self):
        base = Path(__file__).resolve().parent.parent / "mod/AIvZ/42/media/lua/client"
        self.src = (base / "AIvZGym.lua").read_text(encoding="utf-8")

    def test_offered_under_the_menus_rules(self):
        self.assertIn('inv:getFirstTagEvalRecurse(ItemTag.HAMMER, notBroken) ~= nil and inv:containsTypeRecurse("Plank")', self.src)
        self.assertIn('inv:getItemCountRecurse("Base.Nails") >= 2 and not p:tooDarkToRead()', self.src)
        self.assertIn("e.o:isBarricadeAllowed() and (not b or b:canAddPlank()) and not (isDoor and e.open)", self.src)
        self.assertIn("if canPry and b and b:getNumPlanks() > 0 then", self.src)

    def test_built_as_the_cursor_builds_it(self):
        x = self.src[self.src.index("G.X.barricade = {"):self.src.index("G.X.unbarricade = {")]
        self.assertIn('SpriteConfigManager.getObjectInfoFromSprite("carpentry_01_8")', x)
        self.assertIn("be.nSprite = mine and (north and 2 or 1) or (north and 4 or 3)", x)
        self.assertLess(x.index("U.walkAdjOpening(p, e.sq, e.o, t)"), x.index("be:tryBuild("))
        self.assertLess(x.index("if not be:isValid(bsq)"), x.index("be:tryBuild("))


class EnterMacroStaticTest(unittest.TestCase):
    """Mod 0.5.7 (backlog L11): the enter macro chooses among windows a player has seen, without their lock state."""

    def test_no_lock_state_and_only_seen_windows(self):
        src = (Path(__file__).resolve().parent.parent / "mod/AIvZ/42/media/lua/client/AIvZ.lua").read_text(encoding="utf-8")
        start = src.index("local function entryWindows")
        code = "\n".join(l.split("--")[0] for l in src[start:src.index("function A.travelStep")].splitlines())
        self.assertNotIn("isLocked", code)
        self.assertNotIn("isPermaLocked", code)
        self.assertIn("(sq:isSeen(pn) or other:isSeen(pn))", code)


class SpeedHoldStaticTest(unittest.TestCase):
    """AIvZ 0.5.3: the owner's speed pick survives a game restart (backlog N9) and isn't lost to an F2 unpause or the
    Pause button coming back at Play (code only, not run in the game here)."""

    def setUp(self):
        base = Path(__file__).resolve().parent.parent / "mod/AIvZ/42/media/lua/client"
        self.src = (base / "AIvZ.lua").read_text(encoding="utf-8")

    def test_the_pick_is_saved_and_read_back_at_load(self):
        pick = self.src[self.src.index("local function pickSpeed"):]
        pick = pick[:pick.index("\nend\n")]
        self.assertIn("writeFile, SPEED_FILE", pick)
        self.assertIn('local SPEED_FILE = "speed.txt"', self.src)
        self.assertIn("readFirstLine(SPEED_FILE)", self.src)

    def test_only_level_keys_and_real_changes_are_picks(self):
        keys = self.src[self.src.index("function A.onKeyPressed"):]
        keys = keys[:keys.index("\nend\n")]
        self.assertIn("KeybindId.NORMAL_SPEED, KeybindId.FAST_FORWARD_X1, KeybindId.FAST_FORWARD_X2", keys)
        self.assertNotIn("KeybindId.PAUSE", keys)   # unpausing with F2 comes back at Play whatever runs
        hold = self.src[self.src.index("function A.holdSpeed"):]
        self.assertNotIn("keyAt", hold[:hold.index("\nend\n")])
        self.assertIn("not (lvl == 1 and sp.seen == 0)", self.src)
        self.assertIn("isMouseButtonDown(0) and sc:isMouseOver()", hold)   # a click, not a resting mouse

    def test_the_policy_defaults_to_the_owners_temperature(self):
        import inspect
        from agent.policies import NetPolicy
        self.assertEqual(inspect.signature(NetPolicy).parameters["temperature"].default, 0.25)
        run = (Path(__file__).resolve().parent.parent / "agent/run.py").read_text(encoding="utf-8")
        self.assertIn('"--temperature", type=float, default=0.25', run)


class TrainerTests(unittest.TestCase):
    def test_rounds_start_every_period_from_the_last_start(self):
        import time
        from agent.run import Trainer
        with tempfile.TemporaryDirectory() as tmp:
            t = Trainer(tmp, every_min=5)
            self.assertTrue(t.due())   # no network yet
            t.last_try = time.time() - 4 * 60
            self.assertFalse(t.due())
            t.last_try = time.time() - 5 * 60 - 1   # a round that took 3 minutes still starts 5 after the last
            self.assertTrue(t.due())


class MenuPrerequisiteStaticTest(unittest.TestCase):
    """Gym 0.4.6: option prerequisites copied from the game's menus (code only, not run in the game)."""

    def setUp(self):
        base = Path(__file__).resolve().parent.parent / "mod/AIvZ/42/media/lua/client"
        self.src = (base / "AIvZGym.lua").read_text(encoding="utf-8")

    def test_window_option_does_not_list_lock_state(self):
        line = next(l for l in self.src.splitlines() if "local info = { d = r1(e.d), dx = dx, dy = dy, open = e.open" in l)
        self.assertNotIn("locked", line)

    def test_smash_needs_closed_window_and_clear_glass_needs_held_item(self):
        self.assertIn("not e.smashed and not e.open and ns < 2", self.src)
        self.assertIn("e.glass and p:getPrimaryHandItem() and ng < 1", self.src)

    def test_drop_skips_favourites(self):
        self.assertIn("isFavorite()", self.src)

    def test_rest_on_a_bed_as_the_bed_menu_offers_it(self):
        """Gym 0.4.39 (backlog G7): doBedMenu's Rest, run with the game's own onRest."""
        self.assertIn("if o:isFurnitureOccupied(p) or (p:isSittingOnFurniture() and p:isSitOnFurnitureObject(o)) then return false end", self.src)
        rest = self.src.split("G.X.rest = {", 1)[1].split("local function stance", 1)[0]
        self.assertIn("ISWorldObjectContextMenu.onRest(bed, p:getPlayerNum())", rest)

    def test_equip_and_drop_follow_the_inventory_menu(self):
        """Gym 0.4.38 (backlog G7): the hand rules of doEquipOption and the vehicle rule of Drop."""
        self.assertIn("if it:isTwoHandWeapon() and it:getCondition() > 0 then return not p:isItemInBothHands(it), true end", self.src)
        self.assertIn("not hand:isDeepWounded() and (hand:getFractureTime() == 0 or hand:getSplintFactor() > 0)", self.src)
        self.assertIn("ISInventoryPaneContextMenu.equipWeapon(o.data.it, true, o.data.both, p:getPlayerNum())", self.src)
        self.assertIn("if not worn and not shut and not try(function() return it:isFavorite() end)", self.src)
        self.assertIn("ISInventoryTransferUtil.newInventoryTransferAction(p, o.data.it, o.data.c, U.carryInv(p, o.data.it))", self.src)
