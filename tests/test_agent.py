"""Tests for the self-taught agent's side: reward, lives, the file link, the random policy, the main loop.

Run from the repo root:  python -m unittest discover -s tests
"""

import argparse
import copy
import gzip
import json
import math
import os
import random
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import reward  # noqa: E402
from agent.link import GameLink, _clean  # noqa: E402
from agent.lives import Life, Lives, learning_data, rules_lives  # noqa: E402
from agent.policies import ProbePolicy, RandomPolicy, _bag, _label, robust_spread  # noqa: E402

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

    def test_searched_containers_kills_and_the_day_cap(self):
        _, parts, _ = reward.step(OBS, later(OBS, 1), self.progress, searched=3)
        self.assertAlmostEqual(parts["new_containers"], 3 * reward.NEW_CONTAINER)
        self.assertEqual(self.progress.containers, 3)
        _, parts, _ = self.step(OBS, later(OBS, 1, kills=2))
        self.assertAlmostEqual(parts["kills"], 2 * reward.KILL)
        _, parts, _ = self.step(OBS, later(OBS, 3 * 24 * 60))   # a clock jump of three days counts as one
        self.assertAlmostEqual(parts["alive"], reward.ALIVE_PER_MIN * 24 * 60)
        _, parts, _ = self.step(OBS, later(OBS, -30))   # time never runs backwards
        self.assertNotIn("alive", parts)

    def test_start_life_counts_the_held_item_and_building_and_reports_infection(self):
        first = later(OBS, held={"name": "Axe", "type": "Axe", "cat": "weapon"}, where={"building": "7,8"}, knox=True)
        fresh = reward.LifeProgress()
        self.assertEqual(reward.start_life(first, fresh), 1.0)
        self.assertIn("Axe", fresh.items)
        self.assertIn("7,8", fresh.buildings)
        self.assertEqual(reward.start_life(later(OBS, knox=False), reward.LifeProgress()), 0.0)
        self.assertEqual(reward.start_life({"dead": True}, reward.LifeProgress()), 0.0)   # no body at creation

    def test_current_version_records_are_rescored_from_their_base_parts(self):
        rec = {"reward_v": 4, "parts": {"alive": 6.0, "kills": 25.0, "new_items": 1.0, "health": -9.0, "death": -500.0}}
        r, minutes = reward.rescore(rec)
        self.assertAlmostEqual(r, 32.0)   # the observations carry health, death and infection
        self.assertAlmostEqual(minutes, 6.0 / reward.ALIVE_PER_MIN)
        self.assertEqual(reward.rescore({"reward_v": 3}), (0.0, 0.0))
        self.assertEqual(reward.rescore({"reward_v": 4, "resumed": True, "parts": {"alive": 5}}), (0.0, 0.0))

    def test_wounds_are_not_new_items(self):
        bitten = later(OBS, 1, inv=OBS["inv"] + [{"name": "Base.Wound_RHand_Bite_Female", "type": "Wound_RHand_Bite_Female",
                                                  "cat": "clothing", "w": 0, "worn": True}])
        self.assertNotIn("new_items", self.step(OBS, bitten)[1])

    def test_item_key_is_type_then_name_and_skips_wounds(self):
        self.assertEqual(reward._item_key({"type": "Axe", "name": "Hand Axe"}), "Axe")
        self.assertEqual(reward._item_key({"name": "Hand Axe"}), "Hand Axe")
        self.assertIsNone(reward._item_key({}))
        self.assertIsNone(reward._item_key({"type": "Wound_RHand_Bite"}))
        self.assertIsNone(reward._item_key({"type": "Base.Wound_RHand_Bite"}))
        self.assertIsNone(reward._item_key({"name": "Base.Wound_RHand_Bite"}))

    def test_weapon_counts_melee_by_damage_and_guns_zero(self):
        self.assertEqual(reward.weapon({"cat": "weapon", "dmg": reward.WEAPON_FULL}), 1.0)
        self.assertEqual(reward.weapon({"cat": "weapon", "dmg": 10}), 1.0)   # capped
        self.assertAlmostEqual(reward.weapon({"cat": "weapon", "dmg": 0.75}), 0.75 / reward.WEAPON_FULL)
        self.assertEqual(reward.weapon({"cat": "weapon", "dmg": 1.5, "ranged": True}), 0.0)
        self.assertEqual(reward.weapon({"cat": "food", "dmg": 1.5}), 0.0)
        self.assertEqual(reward.weapon({"cat": "weapon", "dmg": -1}), 0.0)
        self.assertEqual(reward.weapon(None), 0.0)

    def test_body_reads_wounds_protection_and_knox(self):
        self.assertIsNone(reward.body({"dead": True, "health": 50}))
        self.assertIsNone(reward.body({}))
        b = reward.body({"health": 70, "knox": True,
                         "body": [{"part": "Hand_R", "flags": ["bleeding"]},
                                  {"part": "Hand_L", "flags": ["bleeding", "bandaged"]},
                                  {"part": "Foot_L", "flags": ["scratch", "bite"]}],
                         "protection": [{"bite": 100, "scratch": 100}, {"bite": 0, "scratch": 0}]})
        self.assertEqual(b["health"], 70.0)
        self.assertEqual(b["untreated"], 2)   # the bandaged part doesn't count
        self.assertAlmostEqual(b["protection"], 0.5)
        self.assertIs(b["knox"], True)
        self.assertEqual(sorted(b["zombie_wounds"]), [("Foot_L", "bite"), ("Foot_L", "scratch")])
        self.assertIsNone(reward.body({"health": 70, "knox": "yes"})["knox"])

    def test_infected_flag_or_wound_chances_and_never_down(self):
        flagged = {"knox": True, "zombie_wounds": []}
        self.assertEqual(reward.infected(0.0, None, flagged), 1.0)
        self.assertEqual(reward.infected(0.5, None, dict(flagged, knox=False)), 0.5)   # never goes down
        none = {"knox": None, "zombie_wounds": []}
        scratched = {"knox": None, "zombie_wounds": [("Hand_R", "scratch")]}
        self.assertAlmostEqual(reward.infected(0.0, none, scratched), 0.07)
        # the same wound seen before (even as a list after a JSON round trip) adds nothing
        again = {"knox": None, "zombie_wounds": [["Hand_R", "scratch"]]}
        self.assertAlmostEqual(reward.infected(0.07, again, scratched), 0.07)
        both = {"knox": None, "zombie_wounds": [("Hand_R", "scratch"), ("Hand_L", "laceration")]}
        self.assertAlmostEqual(reward.infected(0.0, none, both), 1 - 0.93 * 0.75)
        bite = {"knox": None, "zombie_wounds": [("Hand_R", "bite")]}
        self.assertEqual(reward.infected(0.0, None, bite), 1.0)

    def test_potential_is_the_sum_of_its_parts(self):
        b = {"health": 80.0, "untreated": 2, "protection": 0.01, "weapon": 1.0}
        parts = reward.potential_parts(b)
        self.assertAlmostEqual(parts["health"], reward.PER_HEALTH * -20)
        self.assertAlmostEqual(parts["wounds"], -2 * reward.PER_UNTREATED)
        self.assertAlmostEqual(reward.potential(b), sum(parts.values()))
        self.assertEqual(reward.potential(None), 0.0)   # dead: Φ is 0
        full = dict(b, health=150.0, untreated=0, protection=0.0, weapon=0.0)
        self.assertEqual(reward.potential(full), 0.0)   # health above 100 earns nothing

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

    def test_damaged_state_file_starts_empty_and_history_is_salvaged(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "agent-state.json").write_text("{not json", encoding="utf-8")
            (Path(tmp) / "lives.jsonl").write_text('{"life":1}\n{broken', encoding="utf-8")
            lives = Lives(tmp)
            self.assertEqual((lives.count, lives.current, lives.history, lives.world_deaths), (0, None, [{"life": 1}], {}))

    def test_history_keeps_whole_lines_around_a_bad_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "lives.jsonl").write_text('{"life":1}\n{broken\n[1]\n\n{"life":2}\n', encoding="utf-8")
            self.assertEqual(Lives(tmp).history, [{"life": 1}, {"life": 2}])

    def test_each_finished_life_is_appended_to_lives_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            lives = Lives(tmp)
            for i in range(2):
                lives.observe({"id": i, "obs": later(OBS, 1), "options": OPTIONS})
                lives.observe({"id": 9, "dead": True, "obs": {"dead": True, "t": {"age": 5.0}}})
            lines = (Path(tmp) / "lives.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual([json.loads(x)["life"] for x in lines], [1, 2])
            self.assertEqual([r["life"] for r in lives.history], [1, 2])
            self.assertIsNone(lives.current)

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


class LivesHelpersTests(unittest.TestCase):
    def test_life_policy_is_the_one_with_most_decisions(self):
        life = Life(1, OBS)
        self.assertIsNone(life.policy())
        life.policies = {"random": 3, "net": 9}
        self.assertEqual(life.policy(), "net")

    def test_life_add_tick_and_hours(self):
        life = Life(1, OBS)
        life.add(2.0, {"alive": 1.5, "kill": 0.5})
        life.add(1.0, {"alive": 0.25})
        self.assertEqual((life.reward, life.parts), (3.0, {"alive": 1.75, "kill": 0.5}))
        life.age = life.born + 1.5
        self.assertEqual(life.hours(), 1.5)
        life.age = life.born - 5
        self.assertEqual(life.hours(), 0.0)   # never negative
        life.seen_at -= 1000   # a long gap (the agent was off) counts as GAP_S at most
        life.tick()
        self.assertEqual(life.real_s, 30.0)

    def test_life_state_round_trips_through_json(self):
        life = Life(4, OBS)
        life.add(1.5, {"alive": 1.5})
        life.policies = {"net": 2}
        life.progress.items = {"Bat"}
        life.progress.buildings = {"b1"}
        back = Life.restore(json.loads(json.dumps(life.state())))
        self.assertEqual((back.number, back.reward, back.parts, back.policies), (4, 1.5, {"alive": 1.5}, {"net": 2}))
        self.assertEqual((back.progress.items, back.progress.buildings), ({"Bat"}, {"b1"}))
        self.assertTrue(back.resumed)
        self.assertFalse(life.resumed)

    def test_lives_ignore_a_damaged_state_file_and_creation_or_stray_death(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "agent-state.json").write_text("{broken", encoding="utf-8")
            lives = Lives(tmp)
            self.assertEqual((lives.count, lives.current, lives.history), (0, None, []))
            self.assertEqual(lives.observe({"id": 1, "creation": True}), (None, 0.0, {}, False, None))
            self.assertEqual(lives.observe({"id": 2, "dead": True, "obs": {"dead": True}}), (None, 0.0, {}, False, None))
            self.assertEqual(lives.world_deaths, {})   # a death with no life behind it counts nothing

    def test_rules_lives_keeps_only_died_records_and_skips_bad_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(rules_lives(tmp), [])   # no file
            lines = [json.dumps({"life": 1, "ended": "died", "hours": 2.5, "reward": 10, "kills": 1, "items_seen": 4,
                                 "buildings": 2, "decisions": 50}),
                     json.dumps({"life": 2, "ended": "left", "hours": 1}),
                     json.dumps({"life": 3, "ended": "died"})]
            (Path(tmp) / "lives-rules.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
            got = rules_lives(tmp)
            self.assertEqual([x["life"] for x in got], [1, 3])
            self.assertEqual((got[0]["policy"], got[0]["items"], got[0]["decisions"]), ("rules", 4, 50))
            self.assertEqual((got[1]["hours"], got[1]["kills"]), (0, 0))   # defaults
            self.assertEqual([x["life"] for x in rules_lives(tmp, last=1)], [3])   # only the last line is read
            (Path(tmp) / "lives-rules.jsonl").write_text("{broken\n", encoding="utf-8")
            self.assertEqual(rules_lives(tmp), [])

    def test_learning_data_shows_reward_only_in_the_current_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = [{"life": 1, "ended": "died", "hours": 3, "reward": 99, "reward_v": reward.VERSION, "policy": "net"},
                       {"life": 2, "ended": "died", "hours": 1, "reward": 50, "reward_v": reward.VERSION - 1},
                       {"life": 3, "ended": "left", "hours": 9}]
            out = learning_data(tmp, history)
            self.assertEqual(out["history"], [])   # no training log yet
            lives = out["lives"]
            self.assertEqual([x["life"] for x in lives], [1, 2])   # a life that was left isn't a finished one
            self.assertEqual((lives[0]["reward"], lives[0]["policy"]), (99, "net"))
            self.assertIsNone(lives[1]["reward"])   # an older reward's points aren't comparable
            self.assertEqual(lives[1]["policy"], "random")   # lives before Phase 4
            model = Path(tmp) / "model"
            model.mkdir()
            (model / "history.jsonl").write_text('{"round": 1}\n\n{"round": 2}\nnot json\n', encoding="utf-8")
            self.assertEqual(learning_data(tmp, history)["history"], [])   # a damaged log is dropped whole
            (model / "history.jsonl").write_text('{"round": 1}\n{"round": 2}\n{"round": 3}\n', encoding="utf-8")
            self.assertEqual([x["round"] for x in learning_data(tmp, history, rounds=2)["history"]], [2, 3])
            self.assertEqual(len(learning_data(tmp, history, lives=1)["lives"]), 1)
            self.assertEqual(len(learning_data(tmp, history, rounds=None, lives=None)["history"]), 3)


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


class LinkEdgeTests(unittest.TestCase):
    def test_poll_wait_stop_and_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            link, obs = GameLink(tmp), Path(tmp) / "obs.json"
            obs.write_text('{"id": 8, "obs": {', encoding="utf-8")
            self.assertIsNone(link.poll())
            obs.write_text(json.dumps({"id": 8, "options": "bad"}), encoding="utf-8")
            os.utime(obs, ns=(1, 2 * 10**9))                 # the finished write is picked up on a later poll
            self.assertEqual(link.poll()["options"], [])     # options that aren't a list become empty
            obs.write_text("[1, 2]", encoding="utf-8")
            os.utime(obs, ns=(1, 3 * 10**9))
            self.assertIsNone(link.poll())                   # not a request
            self.assertIsNone(link.wait(timeout=0.05, every=0.01))
            obs.write_text(json.dumps({"id": 9, "options": [1]}), encoding="utf-8")
            os.utime(obs, ns=(1, 4 * 10**9))
            self.assertEqual(link.wait(timeout=1.0, every=0.01)["id"], 9)
            link.stop()
            self.assertEqual((Path(tmp) / "gym.txt").read_text(encoding="utf-8"), "off\n")
        self.assertEqual(len(_clean("x" * 200)), 80)
        self.assertEqual(_clean(None), "")


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

    def test_bag_counts_inventory_and_the_held_item(self):
        obs = {"inv": [{"name": "Bandage"}, {"name": "Bandage"}, {"name": "Axe"}], "held": {"name": "Axe"}}
        self.assertEqual(_bag(obs), {"Bandage": 2, "Axe": 2})
        self.assertEqual(_bag({"held": "nothing"}), {})   # a held item that is not a record is ignored
        self.assertEqual(_bag(None), {})

    def test_label_names_what_an_option_acts_on(self):
        self.assertEqual(_label({"verb": "eat", "name": "Apple"}), "eat Apple")
        self.assertEqual(_label({"verb": "craft", "recipe": "Make Bandage", "name": "Rag"}), "craft Make Bandage (Rag)")
        self.assertEqual(_label({"verb": "go_room", "dir": "north"}), "go_room north")
        self.assertEqual(_label({"verb": "rest"}), "rest")


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


    def test_probe_outcomes_died_failed_replaced_and_continue_cap(self):
        eat = {"verb": "eat", "name": "Apple", "type": "Apple", "cat": "food"}
        walk = {"verb": "walk", "dir": "north"}
        pol = ProbePolicy(random.Random(1), tries=5, max_continues=2)
        opts = [eat, walk]
        pol.choose({"options": opts, "obs": OBS})
        self.assertEqual(pol.pending["verb"], "eat")
        # a failed try keeps the game's message in the tally key
        pol.choose({"options": opts, "obs": OBS, "last": {"verb": "eat", "status": "failed", "msg": "not hungry"}})
        self.assertEqual(pol.tally["eat"]["failed: not hungry"], 1)
        self.assertIn("eat          failed: not hungry 1", pol.report())
        # a different pick while one is running counts the running one as replaced
        pol = ProbePolicy(random.Random(1), tries=5)
        pol.choose({"options": opts, "obs": OBS})
        pol.choose({"options": opts, "obs": OBS, "last": {"verb": "walk", "status": "running"}})
        self.assertEqual(pol.tally["eat"]["replaced"], 1)
        # death ends the pending try as died
        pol = ProbePolicy(random.Random(1), tries=5)
        pol.choose({"options": opts, "obs": OBS})
        pol.choose({"options": [], "obs": OBS, "dead": True})
        self.assertEqual(pol.tally["eat"]["died"], 1)
        self.assertIsNone(pol.pending)
        # `continue` is taken at most max_continues times in a row
        pol = ProbePolicy(random.Random(1), tries=5, max_continues=2)
        cont = [{"verb": "continue"}] + opts
        picks = [pol.choose({"options": cont, "obs": OBS, "last": {"verb": "eat", "status": "running"}})[0] for _ in range(3)]
        self.assertEqual(picks[:2], [0, 0])
        self.assertNotEqual(picks[2], 0)
        self.assertEqual(pol.choose({"options": [], "obs": OBS}), (None, [], ""))


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

    def test_experience_log_rollover_writes_the_old_hour_to_its_own_file(self):
        from unittest import mock
        from agent import run as run_mod
        with tempfile.TemporaryDirectory() as tmp:
            log = run_mod.ExperienceLog(tmp)
            real = run_mod.datetime
            with mock.patch.object(run_mod, "datetime") as dt:
                dt.now.return_value = real(2026, 10, 15, 9, 59)
                log.add({"id": 1})
                dt.now.return_value = real(2026, 10, 15, 10, 0)
                log.add({"id": 2})
                log.flush()
            names = sorted(f.name for f in Path(tmp).glob("*.jsonl.gz"))
            self.assertEqual(names, ["20261015-09.jsonl.gz", "20261015-10.jsonl.gz"])

    def test_trainer_due_and_status(self):
        """A round is due when the saved network is older than the interval, or there is none; after a try, the
        interval counts from that try."""
        import os
        import time
        from agent.run import Trainer
        with tempfile.TemporaryDirectory() as tmp:
            t = Trainer(tmp, every_min=10)
            self.assertTrue(t.due())                      # no network yet
            (Path(tmp) / "model").mkdir()
            t.model.write_bytes(b"x")
            self.assertFalse(t.due())                     # just saved
            old = time.time() - 601
            os.utime(t.model, (old, old))
            self.assertTrue(t.due())                      # older than 10 minutes
            t.last_try = time.time()
            self.assertFalse(t.due())                     # counted from the try, not the file
            t.last_try = time.time() - 601
            self.assertTrue(t.due())
            self.assertEqual(t.status(), {"every_min": 10, "running": False, "running_s": None, "last_code": None})
            t.running, t.started = True, time.time() - 5
            self.assertEqual(t.status()["running"], True)
            self.assertGreaterEqual(t.status()["running_s"], 5)

    def test_experience_log_flushes_at_twenty_decisions_and_on_death(self):
        from agent.run import ExperienceLog

        def count(tmp):
            n = 0
            for f in Path(tmp).glob("*.jsonl.gz"):
                with gzip.open(f, "rt", encoding="utf-8") as g:
                    n += sum(1 for x in g if x.strip())
            return n
        with tempfile.TemporaryDirectory() as tmp:
            log = ExperienceLog(tmp)
            for i in range(19):
                log.add({"id": i})
            self.assertEqual(count(tmp), 0)
            log.add({"id": 19})
            self.assertEqual(count(tmp), 20)
            log.add({"id": 20})
            self.assertEqual(count(tmp), 20)
            log.add({"id": 21, "dead": True})
            self.assertEqual(count(tmp), 22)
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

    def test_silence_empty_windows_and_history_limit(self):
        from agent import hearing
        from agent.hearing import Hearing
        self.assertIsNone(hearing.analyse([], [], 8000))
        quiet = hearing.analyse([0.0] * 800, [0.0] * 800, 8000)
        self.assertEqual((quiet["db_l"], quiet["db_r"], quiet["peak_db"]), (hearing.FLOOR_DB,) * 3)
        self.assertEqual(quiet["balance"], 0.0)
        # a band at or above the Nyquist frequency reads as the floor, not as an error
        self.assertEqual(quiet["bands_db"], [hearing.FLOOR_DB] * len(hearing.BANDS_HZ))

        class Src:
            available = True
            def read(s): return [(0.1 * i, [0.1] * 800, [0.1] * 800, 8000) for i in range(1, 6)]
        h = Hearing(Src(), history=3)
        self.assertEqual(len(h.snapshot(1)["windows"]), 3)

    def test_db_and_goertzel_helpers(self):
        from agent import hearing
        self.assertEqual(hearing._db(0.0), hearing.FLOOR_DB)
        self.assertEqual(hearing._db(1e-12), hearing.FLOOR_DB)   # below the floor clamps
        self.assertAlmostEqual(hearing._db(1.0), 0.0)
        self.assertAlmostEqual(hearing._db(0.1), -20.0)
        # a sinusoid of amplitude A at the probed frequency gives power A^2
        self.assertAlmostEqual(hearing._goertzel_power(self.tone(1000, 0.5), 8000, 1000), 0.25, places=3)
        # another frequency, empty input and the Nyquist frequency give (almost) nothing
        self.assertLess(hearing._goertzel_power(self.tone(1000, 0.5), 8000, 250), 1e-4)
        self.assertEqual(hearing._goertzel_power([], 8000, 1000), 0.0)
        self.assertEqual(hearing._goertzel_power([0.5] * 100, 8000, 4000), 0.0)

    def test_balance_follows_the_louder_ear(self):
        from agent import hearing
        right = hearing.analyse([0.0] * 800, [0.3] * 800, 8000)
        both = hearing.analyse([0.3] * 800, [0.3] * 800, 8000)
        self.assertGreater(right["balance"], 0.9)
        self.assertEqual(both["balance"], 0.0)
        # unequal lengths: the shorter channel decides the window
        self.assertIsNotNone(hearing.analyse([0.1] * 800, [0.1] * 400, 8000))

    def test_numpy_windows_give_the_same_numbers(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy not installed")
        from agent import hearing
        left, right = self.tone(250, 0.3, 4000, 48000), self.tone(4000, 0.05, 4000, 48000)
        plain = hearing.analyse(left, right, 48000)
        fast = hearing.analyse(np.array(left, dtype=np.float32), np.array(right, dtype=np.float32), 48000)
        for k in ("db_l", "db_r", "peak_db", "balance"):
            self.assertAlmostEqual(plain[k], fast[k], delta=0.11)
        for a, b in zip(plain["bands_db"], fast["bands_db"]):
            self.assertAlmostEqual(a, b, delta=0.2)

    def test_capture_says_why_when_the_game_is_not_running(self):
        from agent import audio_loopback
        self.assertIsNone(audio_loopback.find_pid("no-such-game-aivz.exe"))
        src = audio_loopback.ProcessLoopbackSource(exe="no-such-game-aivz.exe")
        try:
            for _ in range(50):
                if src.reason != "starting":
                    break
                time.sleep(0.1)
            self.assertFalse(src.available)
            self.assertNotEqual(src.reason, "starting")
            self.assertEqual(src.read(), [])
        finally:
            src.close()

    def test_an_agent_built_without_the_option_does_not_capture(self):
        from agent.run import Agent
        with tempfile.TemporaryDirectory() as tmp:
            agent = Agent(argparse.Namespace(lua_dir=tmp, log_dir=tmp, port=0))
            self.assertFalse(agent.hearing.snapshot()["available"])


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
        self.assertIn("G.creationStep(w.mapSpawnSelect, w.charCreationProfession, w.charCreationMain)", step)
        screens = self.src[self.src.index("function G.creationStep"):]
        screens = screens[:screens.index("\nend\n")]
        self.assertLess(screens.index("lb.selected = towns[ZombRand(#towns) + 1]"), screens.index("spawn:clickNext()"))
        for gone in ("randomizeSpawn", "G.RANDOM_SPAWN", "selectedRegion =", "GS.deaths"):
            self.assertNotIn(gone, self.src)


class KeepRunningStaticTest(unittest.TestCase):
    """Gym 0.4.74 and the game watcher (backlog N16, N17): each new life forgets the dead characters' timed-action
    queues, which the game never drops, and the watcher restarts a hung or crashed game, which the loader then
    continues from the main menu (code only, not run in the game here)."""

    def setUp(self):
        root = Path(__file__).resolve().parent.parent
        base = root / "mod/AIvZ/42/media/lua/client"
        self.gym = (base / "AIvZGym.lua").read_text(encoding="utf-8")
        self.loader = (base / "AIvZLoader.lua").read_text(encoding="utf-8")
        self.watcher = (root / "scripts/watch-game.ps1").read_text(encoding="utf-8")

    def test_a_new_life_forgets_only_dead_characters_queues(self):
        forget = self.gym[self.gym.index("local function forgetDeadQueues"):]
        forget = forget[:forget.index("\nend\n")]
        self.assertIn('instanceof(chr, "IsoGameCharacter") and chr:isDead()', forget)
        self.assertIn("for _, chr in ipairs(dead) do queues[chr] = nil end", forget)   # not while pairs() walks it
        life = self.gym[self.gym.index("function G.newLife"):]
        self.assertIn("forgetDeadQueues()", life[:life.index("\nend\n")])

    def test_the_loader_continues_only_after_a_restart(self):
        self.assertIn('tonumber((readAll("aivz/resume.txt") or ""):match("%d+"))', self.loader)
        self.assertIn("now - at < RESUME_FRESH_MS", self.loader)
        self.assertIn('getFileWriter("aivz/resume.txt", true, false)', self.loader)   # used once
        self.assertIn("MainScreen.onMenuItemMouseDownMainMenu(cont, 0, 0)", self.loader)
        self.assertIn("Events.OnFETick.Add(", self.loader)
        self.assertNotIn("reloadLuaFile(r", self.loader)   # nothing read from a file is run

    def test_the_watcher_restarts_only_for_the_agent_and_not_after_a_quit(self):
        restart = self.watcher[self.watcher.index("function Restart-Game"):]
        self.assertLess(restart.index("resume.txt"), restart.index("Start-Process 'steam://rungameid/108600'"))
        self.assertIn("if ($tail[-5..-1] -match 'GameThread exited') { return 'quit' }", self.watcher)
        self.assertIn("$ending -eq 'crash' -and $RestartMinutes -gt 0 -and (Agent-Running)", self.watcher)
        self.assertIn("$for -ge $RestartMinutes * 60 -and (Agent-Running)", self.watcher)
        self.assertIn("$recent.Count -ge $MaxRestarts", self.watcher)


@unittest.skipUnless(sys.platform == "win32", "native stacks are read with Windows' dbghelp")
class NativeStacksTests(unittest.TestCase):
    """scripts/native_stacks.py, which the game watcher runs on a hung game: every thread of another process, each
    with frames named by module."""

    def test_the_threads_of_another_process(self):
        import subprocess
        sys.path.insert(0, str(ROOT / "scripts"))
        import native_stacks
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            time.sleep(1.0)
            threads = native_stacks.stacks(child.pid)
        finally:
            child.kill()
            child.wait()
        self.assertTrue(threads)
        frames = [f for t in threads for f in t[4]]
        self.assertTrue(any(f.lower().startswith("ntdll.dll!") for f in frames), frames[:10])
        self.assertTrue(all(isinstance(t[3], float) for t in threads))


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
        self.assertIn("not e.smashed and not e.open and ns < 8", self.src)
        self.assertIn("e.glass and p:getPrimaryHandItem() and ng < 8", self.src)

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
