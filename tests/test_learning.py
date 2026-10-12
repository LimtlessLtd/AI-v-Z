"""Tests for Phase 4: the encoding, the network, a training round, and the net policy.

Run from the repo root:  python -m unittest discover -s tests
"""

import argparse
import copy
import gzip
import importlib.util
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from agent import features as F  # noqa: E402
from agent import reward as R  # noqa: E402
from test_agent import OBS, OPTIONS, later  # noqa: E402

# the encoding tests need nothing extra; the network's need PyTorch (on the owner's PC, not always in the cloud)
needs_torch = unittest.skipUnless(importlib.util.find_spec("torch"), "PyTorch isn't installed here")


def life_records(life, n, start_id=1, die=True):
    """A made-up life as the agent logs it: n decisions, then (optionally) a death."""
    recs, obs = [], copy.deepcopy(OBS)
    for k in range(n):
        o = later(obs, 5 * k)
        recs.append({"life": life, "id": start_id + k, "reason": "done", "obs": o, "options": OPTIONS,
                     "last": {"verb": "wait", "status": "done"}, "choice": k % len(OPTIONS), "reward": 0.5 if k else 0.0,
                     "parts": {"alive": 0.5} if k else {}, "dead": False, "new_life": k == 0, "resumed": False})
    if die:
        recs.append({"life": life, "id": start_id + n, "reason": "died", "obs": {"dead": True}, "options": [],
                     "reward": -20.0, "dead": True, "new_life": False, "resumed": False})
    return recs


def write_experience(root, records, name="20260101-00.jsonl.gz"):
    d = Path(root) / "experience"
    d.mkdir(parents=True, exist_ok=True)
    with gzip.open(d / name, "wt", encoding="utf-8") as f:
        f.write("\n".join(json.dumps(r) for r in records) + "\n")


class EncodingTests(unittest.TestCase):
    def test_sizes_are_fixed_whatever_the_observation(self):
        for obs in (OBS, {}, {"moodles": {"hungry": 3, "panic": 2}, "clock": {"hour": 7, "min": 30}},
                    {"selected": ["Athletic"], "points": -2, "stage": "pay"}):
            dense, toks = F.encode_state({"obs": obs, "reason": "done"})
            self.assertEqual(len(dense), F.STATE_DIM)
            self.assertTrue(all(0 <= t < F.BUCKETS for t in toks))
        for o in OPTIONS + [{"verb": "take", "name": "Apple", "type": "Base.Apple", "d": 3.5, "rotten": True}, {}]:
            dense, toks = F.encode_option(o)
            self.assertEqual(len(dense), F.OPTION_DIM)

    def test_moodles_go_in_and_raw_stats_and_world_clock_do_not(self):
        a = F.encode_state({"obs": OBS})[0]
        b = F.encode_state({"obs": {**OBS, "moodles": {"hungry": 2}}})[0]
        self.assertNotEqual(a, b)
        c = F.encode_state({"obs": {**OBS, "stats": {"hunger": 0.9}, "t": {**OBS["t"], "hour": 22}, "pos": {"x": 1}}})[0]
        self.assertEqual(a, c)
        d = F.encode_state({"obs": {**OBS, "clock": {"hour": 22, "min": 0}}})[0]
        self.assertNotEqual(a, d)   # the time counts once a watch shows it

    def test_protection_goes_in_and_the_infection_stays_out(self):
        base = {**OBS, "protection": [{"part": "Torso_Upper", "bite": 0, "scratch": 0}]}
        jacket = {**OBS, "protection": [{"part": "Torso_Upper", "bite": 40, "scratch": 60}]}
        self.assertNotEqual(F.encode_state({"obs": base})[0], F.encode_state({"obs": jacket})[0])
        self.assertEqual(F.encode_state({"obs": {**OBS, "knox": True}}), F.encode_state({"obs": {**OBS, "knox": False}}))
        worn = {"name": "Jacket", "type": "Jacket_Leather", "cat": "clothing", "worn": True, "cond": 0.1, "holes": 2}
        toks = F.encode_state({"obs": {**OBS, "inv": [worn]}})[1]
        self.assertIn(F.bucket("worn:Jacket_Leather:holes:2"), toks)   # the wear is tied to the garment
        k = list(F.OPTION_NUMBERS).index("bite")
        self.assertEqual(F.encode_option({"verb": "wear", "bite": 40})[0][k], 0.4)

    def test_what_the_screen_doesnt_show_stays_out(self):
        self.assertEqual(F.encode_state({"obs": {"health": 87.3}})[0], F.encode_state({"obs": {"health": 82.0}})[0])
        self.assertNotEqual(F.encode_state({"obs": {"health": 87.3}})[0], F.encode_state({"obs": {"health": 40.0}})[0])
        k = list(F.OPTION_NUMBERS).index("locked")
        self.assertEqual(F.encode_option({"verb": "window", "locked": 1})[0][k], 0.0)
        self.assertEqual(F.encode_option({"verb": "door", "locked": 1})[0][k], 1.0)
        e = list(F.OPTION_NUMBERS).index("endurance")
        self.assertEqual(F.encode_option({"verb": "exercise", "endurance": 1})[0][e], 0.0)
        self.assertEqual(len(F.encode_option({"verb": "window"})[0]), F.OPTION_DIM)

    def test_where_the_zombies_are_goes_in(self):
        """Version 3: the state says which way each zombie in sight is; an option with a direction says which lie
        that way (dx, dy as the gym gives them: +y is south)."""
        north = {**OBS, "zombies": [{"d": 2.0, "dx": 0.0, "dy": -2.0, "closing": 1.0}]}
        south = {**OBS, "zombies": [{"d": 2.0, "dx": 0.0, "dy": 2.0, "closing": 1.0}]}
        self.assertNotEqual(F.encode_state({"obs": north})[0], F.encode_state({"obs": south})[0])
        base = len(F.MOODLES) + len(F.WOUNDS) + len(F.REASONS) + len(F.STATUSES) + 32 + 2 * len(F.PARTS)
        n = base + 2 * F.SECTORS.index("N")
        dense = F.encode_state({"obs": north})[0]
        self.assertAlmostEqual(dense[n], 0.9)          # nearness of the closest in the north sector
        self.assertAlmostEqual(dense[n + 1], 1 / 3)    # one within 10 tiles
        self.assertEqual(dense[base + 2 * F.SECTORS.index("S")], 0.0)
        self.assertEqual([F.sector(1, -1), F.sector(-3, 0.5), F.sector(0, 0)], ["NE", "W", None])
        walk_n = {"verb": "walk", "dir": "N", "dx": 0, "dy": -1, "zombies": 1}
        walk_s = {"verb": "walk", "dir": "S", "dx": 0, "dy": 1, "zombies": 0}
        self.assertAlmostEqual(F.encode_option(walk_n, north)[0][-2], 0.9)
        self.assertEqual(F.encode_option(walk_s, north)[0][-2:], [0.0, 0.0])
        self.assertEqual(F.encode_option(walk_n)[0][-2:], [0.0, 0.0])   # without the observation: nothing
        self.assertEqual(len(F.encode_option(walk_n, north)[0]), F.OPTION_DIM)
        dark = {**OBS, "zombies": []}   # a zombie the gym doesn't list (unseen) can't show up
        self.assertEqual(F.encode_option(walk_n, dark)[0][-2:], [0.0, 0.0])

    def test_stance_and_zombie_facing_go_in_as_tokens(self):
        """Gym 0.4.25: the character's own stance and which way the zombies in sight face, as tokens (the dense
        layout, and with it the trained network, stays as it is)."""
        z = {"d": 2.0, "dx": 0.0, "dy": -2.0}
        at_me = {**OBS, "zombies": [{**z, "facing": 0.9}]}
        away = {**OBS, "zombies": [{**z, "facing": -0.8}]}
        s1, s2 = F.encode_state({"obs": at_me}), F.encode_state({"obs": away})
        self.assertEqual(s1[0], s2[0])
        self.assertNotEqual(s1[1], s2[1])
        self.assertIn(F.bucket("zombie:facing:toward:close"), s1[1])
        self.assertIn(F.bucket("zombie:facing:away:close"), s2[1])
        far = {**OBS, "zombies": [{"d": 15.0, "dx": 0.0, "dy": -15.0, "facing": 0.9}]}
        self.assertNotIn(F.bucket("zombie:facing:toward:mid"), F.encode_state({"obs": far})[1])

    def test_fence_and_door_sheet_flags_go_in_as_tokens(self):
        """Gym 0.4.33: a tall fence, a drop beyond it and a sheet on a door are tokens; the dense part (the layout the
        trained network reads) is the same as without them, and the fence's direction is a word like walk's."""
        low = {"verb": "climb_fence", "d": 2.0, "dx": 1.5, "dy": 0.0, "dir": "E", "tall": False, "drop": False}
        tall = dict(low, tall=True, drop=True)
        (d1, t1), (d2, t2) = F.encode_option(low, OBS), F.encode_option(tall, OBS)
        self.assertEqual(d1, d2)
        self.assertNotIn(F.bucket("climb_fence:tall"), t1)
        self.assertIn(F.bucket("climb_fence:tall"), t2)
        self.assertIn(F.bucket("climb_fence:drop"), t2)
        self.assertIn(F.bucket("dir:E"), t1)
        on_door = F.encode_option({"verb": "curtain", "d": 1.0, "open": True, "door": True}, OBS)[1]
        on_window = F.encode_option({"verb": "curtain", "d": 1.0, "open": True}, OBS)[1]
        self.assertIn(F.bucket("curtain:door"), on_door)
        self.assertNotIn(F.bucket("curtain:door"), on_window)
        sneaking = F.encode_state({"obs": {**OBS, "sneaking": True}})
        self.assertIn(F.bucket("self:sneaking"), sneaking[1])
        self.assertEqual(sneaking[0], F.encode_state({"obs": OBS})[0])
        self.assertEqual(len(sneaking[0]), F.STATE_DIM)

    def test_sitting_is_visible_without_changing_the_network_layout(self):
        standing = F.encode_state({"obs": OBS})
        sitting = F.encode_state({"obs": {**OBS, "sitting": True}})
        self.assertEqual(standing[0], sitting[0])
        self.assertEqual(len(sitting[0]), F.STATE_DIM)
        self.assertIn(F.bucket("self:sitting"), sitting[1])
        self.assertNotIn(F.bucket("self:sitting"), standing[1])
        self.assertEqual(standing, F.encode_state({"obs": {**OBS, "sitting": False}}))
        furniture = F.encode_state({"obs": {**OBS, "sitting": True, "sittingOnFurniture": True}})
        self.assertEqual(sitting[0], furniture[0])
        self.assertIn(F.bucket("self:sitting:furniture"), furniture[1])
        self.assertNotIn(F.bucket("self:sitting:furniture"), sitting[1])
        get_up = F.encode_option({"verb": "get_up"}, OBS)
        self.assertIn(F.bucket("verb:get_up"), get_up[1])

    def test_pile_and_dragging_go_in_as_tokens(self):
        """Gym 0.4.35: half or all of a pile on the ground is a word on pick_up, and a corpse in tow a state token; the
        dense parts stay as they are."""
        one = {"verb": "pick_up", "d": 1.0, "dx": 1.0, "dy": 0.0, "type": "Base.Nails", "w": 0.01}
        (d1, t1), (d2, t2) = F.encode_option(one, OBS), F.encode_option(dict(one, how="all", n=12), OBS)
        self.assertEqual(d1, d2)
        self.assertIn(F.bucket("pick_up:how:all"), t2)
        self.assertNotIn(F.bucket("pick_up:how:all"), t1)
        two = F.encode_option({"verb": "barricade", "d": 1.0, "planks": 2, "door": True}, OBS)
        self.assertIn(F.bucket("barricade:planks:2"), two[1])
        self.assertIn(F.bucket("barricade:door"), two[1])
        self.assertEqual(two[0], F.encode_option({"verb": "barricade", "d": 1.0, "planks": 0, "door": True}, OBS)[0])
        dragging = F.encode_state({"obs": {**OBS, "dragging": True}})
        self.assertIn(F.bucket("self:dragging"), dragging[1])
        self.assertEqual(dragging[0], F.encode_state({"obs": OBS})[0])
        hit = {"verb": "attack", "d": 1.0, "dx": 1.0, "dy": 0.0, "facing": -0.5}
        self.assertIn(F.bucket("attack:facing:away"), F.encode_option(hit)[1])
        scrap = {"verb": "disassemble", "name": "Wooden Chair", "d": 1.0, "chance": 60}
        self.assertIn(F.bucket("disassemble:chance:2"), F.encode_option(scrap)[1])
        self.assertEqual(len(F.encode_option(scrap)[0]), F.OPTION_DIM)
        self.assertEqual([F.facing_word(x) for x in (1.0, 0.7, 0.2, -0.3, -1.0)], ["toward", "toward", "side", "away", "away"])

    def test_open_doors_and_windows_seen_go_in(self):
        shut = {**OBS, "where": {"building": "b1", "doorsOpen": 0, "windowsOpen": 0}}
        open_ = {**OBS, "where": {"building": "b1", "doorsOpen": 2, "windowsOpen": 1}}
        self.assertNotEqual(F.encode_state({"obs": shut})[0], F.encode_state({"obs": open_})[0])

    def test_glass_under_a_bandage_stays_out(self):
        def enc(flags):
            return F.encode_state({"obs": {"body": [{"part": "Hand_L", "flags": flags}]}})
        self.assertEqual(enc(["glass", "bandaged"]), enc(["bandaged"]))
        self.assertNotEqual(enc(["glass"]), enc([]))

    def test_traits_look_the_same_at_creation_and_in_the_life(self):
        at_creation = F.encode_state({"obs": {"selected": ["Athletic"]}, "reason": "creation"})[1]
        in_life = F.encode_state({"obs": {**OBS, "traits": ["Athletic"]}})[1]
        self.assertIn(F.bucket("trait:Athletic"), at_creation)
        self.assertIn(F.bucket("trait:Athletic"), in_life)

    def test_damaged_files_give_up_what_can_still_be_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.jsonl.gz"
            good = gzip.compress(b'{"id": 1}\n{"id": 2}\n')
            p.write_bytes(good + b'2026 plain text from a second writer\n' + gzip.compress(b'{"id": 3}\n')[:-6])
            ids = [r["id"] for r in F.read_records(p)]
            self.assertIn(1, ids)
            self.assertIn(2, ids)

    def test_transitions_stay_inside_a_life_and_skip_restarts(self):
        recs = life_records(1, 3) + life_records(2, 3, start_id=10)
        recs[-2]["resumed"] = True   # life 2's third decision came after an agent restart
        tr = F.transitions(recs)
        self.assertIn((0, 1), tr)
        self.assertIn((2, 3), tr)        # the last decision leads to the death
        self.assertNotIn((3, 4), tr)     # a death doesn't lead into the next life
        self.assertNotIn((5, 6), tr)     # nothing is pinned across a restart

    def test_character_creation_runs_into_the_life_it_made(self):
        creation = [{"life": None, "reason": "creation", "obs": {"selected": []}, "choice": 0,
                     "options": [{"verb": "add_trait", "name": "Lucky", "cost": 4}], "reward": 0.0},
                    {"life": None, "reason": "creation", "obs": {"selected": ["Lucky"]}, "choice": 0,
                     "options": [{"verb": "finish_creation"}], "reward": 0.0}]
        recs = creation + life_records(7, 2)
        tr = F.transitions(recs)
        self.assertIn((0, 1), tr)
        self.assertIn((1, 2), tr)


@needs_torch
class NetworkTests(unittest.TestCase):
    def test_one_score_per_option_and_it_survives_saving(self):
        from agent import net as N
        net = N.QNet()
        msg = {"obs": OBS, "options": OPTIONS, "reason": "idle"}
        q = N.q_values(net, msg)
        self.assertEqual(len(q), len(OPTIONS))
        with tempfile.TemporaryDirectory() as tmp:
            N.save(net, Path(tmp) / "m" / "qnet.pt", round=3)
            net2, meta = N.load(Path(tmp) / "m" / "qnet.pt")
            self.assertEqual(meta["round"], 3)
            for x, y in zip(q, N.q_values(net2, msg)):
                self.assertAlmostEqual(x, y, places=5)

    def test_a_training_round_learns_which_option_pays(self):
        """Option 0 ('wait') pays 1, the others cost 1: after training, wait must score highest."""
        from agent import learn, net as N
        rng = random.Random(1)
        recs = []
        for life in range(1, 41):
            for k in range(8):
                c = rng.randrange(len(OPTIONS))
                recs.append({"life": life, "reason": "done", "obs": later(OBS, 5 * k), "options": OPTIONS, "choice": c,
                             "reward": 0.0, "reward_v": R.VERSION, "dead": False, "new_life": k == 0, "resumed": False})
                if k:   # training reads the parts (a first item stands in for any pay-off)
                    recs[-1]["parts"] = {"new_items": 100.0 if recs[-2]["choice"] == 0 else -100.0}
        with tempfile.TemporaryDirectory() as tmp:
            write_experience(tmp, recs)
            rec = learn.train(tmp, steps=400, quiet=True)
            self.assertEqual(rec["round"], 1)
            self.assertTrue((Path(tmp) / "model" / "qnet.pt").exists())
            self.assertTrue((Path(tmp) / "model" / "history.jsonl").exists())
            net, _ = N.load(Path(tmp) / "model" / "qnet.pt")
            q = N.q_values(net, {"obs": OBS, "options": OPTIONS, "reason": "done"})
            self.assertEqual(q.index(max(q)), 0, q)
            rec2 = learn.train(tmp, steps=50, quiet=True)   # the next round carries on from the saved network
            self.assertEqual(rec2["round"], 2)
            self.assertFalse(rec2["fresh"])

    def test_old_experience_is_rescored_and_discounted_by_game_time(self):
        """Version 1 records (life_records: 5 game minutes apart, death -20) are read under the current reward."""
        from agent import learn, net as N
        with tempfile.TemporaryDirectory() as tmp:
            write_experience(tmp, life_records(1, 3))
            data = learn.Data(tmp)
            self.assertAlmostEqual(float(data.reward[3]), R.DEATH / N.SCALE, places=5)
            alive = R.ALIVE_PER_MIN * (1 - learn.GAMMA ** 5) / (1 - learn.GAMMA)   # 5 minutes, paid minute by minute
            self.assertAlmostEqual(float(data.reward[1]), alive / N.SCALE, places=5)
            self.assertAlmostEqual(float(data.disc[1]), learn.GAMMA ** 5, places=5)
            self.assertAlmostEqual(learn.GAMMA ** learn.HALF_LIFE_MIN, 0.5, places=6)

    def test_the_infection_and_the_body_value_go_through_each_life(self):
        """Life 1 is bitten (gym 0.4.20 flag) at its 2nd decision and dies at its 4th; a jacket goes on and off."""
        from agent import learn, net as N
        recs = life_records(1, 4)
        for r in recs[1:4]:
            r["obs"]["knox"] = True
            r["obs"]["body"] = [{"part": "ForeArm_R", "flags": ["bite"]}]
        recs[0]["obs"]["knox"] = False
        events, phi, has = learn.Data.body_values([learn._meta(r) for r in recs])
        self.assertEqual(list(events), [0.0, R.DEATH, 0.0, 0.0, 0.0])   # charged once, the death costs nothing more
        self.assertEqual(list(has), [True, True, True, True, False])
        self.assertAlmostEqual(phi[1] - phi[0], -R.PER_UNTREATED)
        jacket = life_records(2, 3, die=False)
        jacket[1]["obs"]["protection"] = [{"part": "Torso_Upper", "bite": 50, "scratch": 50}]
        for r in (jacket[0], jacket[2]):
            r["obs"]["protection"] = [{"part": "Torso_Upper", "bite": 0, "scratch": 0}]
        _, phi, _ = learn.Data.body_values([learn._meta(r) for r in jacket])
        self.assertAlmostEqual((phi[1] - phi[0]) + (phi[2] - phi[1]), 0.0)   # on, then off: nothing gained

    def test_targets_add_up_the_next_rewards_of_the_life(self):
        """N-step targets: from a life's first decision the rewards of the next N_STEP decisions, each discounted by
        the game time before it; near the end, the death ends the sum and nothing is bootstrapped after it."""
        from agent import learn
        with tempfile.TemporaryDirectory() as tmp:
            write_experience(tmp, life_records(1, 8))
            data = learn.Data(tmp)
        n = learn.N_STEP
        self.assertGreater(n, 1)
        first = list(data.ti).index(0)
        r, d = 0.0, 1.0
        for k in range(1, n + 1):
            r += d * float(data.reward[k])
            d *= float(data.disc[k])
        self.assertAlmostEqual(float(data.n_reward[first]), r, places=4)
        self.assertAlmostEqual(float(data.n_disc[first]), d, places=5)
        self.assertEqual(int(data.n_state[first]), n)
        last = list(data.ti).index(7)   # the last decision: its next record is the death
        self.assertEqual(int(data.n_state[last]), 8)
        self.assertTrue(data.terminal[8])
        self.assertAlmostEqual(float(data.n_reward[last]), float(data.reward[8]), places=5)
        before = list(data.ti).index(8 - 2)   # two before the death: two rewards, then terminal
        self.assertEqual(int(data.n_state[before]), 8)

    def test_an_out_of_date_cache_is_rebuilt(self):
        """A version change makes every cached hour out of date; rebuilding one replaces the file it just read."""
        from agent import learn
        with tempfile.TemporaryDirectory() as tmp:
            write_experience(tmp, life_records(1, 3))
            learn.Data(tmp)   # writes the cache (the file's hour isn't the current one)
            old = R.VERSION
            try:
                R.VERSION = old + 100
                data = learn.Data(tmp)   # out of date: read, closed, rebuilt
            finally:
                R.VERSION = old
            self.assertEqual(len(data.meta), 4)

    def test_a_network_of_another_reward_is_set_aside(self):
        from agent import learn, net as N
        with tempfile.TemporaryDirectory() as tmp:
            write_experience(tmp, sum((life_records(n, 8) for n in range(1, 41)), []))
            N.save(N.QNet(), Path(tmp) / "model" / "qnet.pt", round=31)   # saved under reward version 1
            rec = learn.train(tmp, steps=20, quiet=True)
            self.assertTrue(rec["fresh"])
            self.assertEqual((rec["round"], rec["reward_v"]), (32, R.VERSION))
            (Path(tmp) / "model" / "qnet.pt").unlink()   # an encoding change: the saved network can't even be loaded
            self.assertEqual(learn.train(tmp, steps=20, quiet=True)["round"], 33)   # the count goes on from the history


@needs_torch
class NetPolicyTests(unittest.TestCase):
    def test_plays_at_random_until_a_network_exists_then_by_its_scores(self):
        from agent import net as N
        from agent.policies import NetPolicy
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model" / "qnet.pt"
            pol = NetPolicy(path, rng=random.Random(0))
            i, probs, note = pol.choose({"obs": OBS, "options": OPTIONS})
            self.assertIn("no network yet", note)
            self.assertIsNone(pol.last_q)
            N.save(N.QNet(), path, round=1)
            i, probs, note = pol.choose({"obs": OBS, "options": OPTIONS})
            self.assertEqual(len(pol.last_q), len(OPTIONS))
            self.assertAlmostEqual(sum(probs), 1.0, places=6)
            self.assertTrue(note.startswith("net r1"))

    def test_the_agent_logs_scores_and_which_policy_played_each_life(self):
        from agent import net as N
        from agent.run import Agent
        with tempfile.TemporaryDirectory() as tmp:
            N.save(N.QNet(), Path(tmp) / "model" / "qnet.pt", round=1)
            a = Agent(argparse.Namespace(lua_dir=tmp, log_dir=tmp, port=0))
            a.handle({"id": 1, "reason": "idle", "obs": OBS, "options": OPTIONS})
            a.handle({"id": 2, "reason": "died", "dead": True, "obs": {"dead": True, "kills": 0, "t": {"age": 28}}, "options": []})
            a.exp.flush()
            with gzip.open(next((Path(tmp) / "experience").glob("*.gz")), "rt", encoding="utf-8") as g:
                first = json.loads(g.readline())
            self.assertEqual(first["policy"], "net")
            self.assertEqual(len(first["q"]), len(OPTIONS))
            self.assertEqual(a.lives.history[-1]["policy"], "net")
            self.assertEqual(a.learning()["lives"][-1]["policy"], "net")


class TraitRuleLuaTest(unittest.TestCase):
    def test_trait_choice_follows_the_owners_option_b(self):
        src = (ROOT / "mod/AIvZ/42/media/lua/client/AIvZGymActions.lua").read_text(encoding="utf-8")
        self.assertIn("prof:PointToSpend()", src)   # the number the screen shows, not the raw pointToSpend
        self.assertNotIn("MAX_STEPS", src)           # any number of good traits...
        self.assertIn("local DEBT_LIMIT = -12", src)
        self.assertIn('cost > 0 and points - cost >= DEBT_LIMIT', src)   # ...as long as each fits the debt limit
        self.assertIn('if points >= 0 then return false end', src)        # paid back: the game starts, no more bad traits
        self.assertNotIn('verb = "finish_creation"', src)
        gym = (ROOT / "mod/AIvZ/42/media/lua/client/AIvZGym.lua").read_text(encoding="utf-8")
        self.assertIn("G.CHOOSE_TRAITS = true", gym)

    def test_item_status_reaches_the_network_as_tokens_only(self):
        gun = {"type": "Base.Pistol", "name": "Pistol", "cat": "weapon", "ranged": True, "ammo": "Base.Bullets9mm",
               "mag": "Base.9mmClip", "loaded": 3, "maxAmmo": 15, "jammed": True, "cond": 0.9}
        vest = {"type": "Base.Vest", "name": "Vest", "cat": "clothing", "holes": 2, "cond": 0.2, "bite": 40}
        toks = F.item_status_tokens(gun, "inv")
        self.assertIn("inv:ammo:Base.Bullets9mm", toks)
        self.assertIn("inv:mag:Base.9mmClip", toks)
        self.assertIn("inv:jammed", toks)
        self.assertIn("inv:holes:2", F.item_status_tokens(vest, "inv"))
        self.assertIn("inv:ammo_level:0", F.item_status_tokens(dict(gun, loaded=3), "inv"))   # 3 of 15
        self.assertIn("inv:ammo_level:0", F.item_status_tokens(dict(gun, loaded=0), "inv"))   # empty is not full
        self.assertIn("inv:ammo_level:3", F.item_status_tokens(dict(gun, loaded=15), "inv"))
        self.assertEqual(F.item_status_tokens({"type": "Base.Axe"}, "held"), [])
        base = {"obs": dict(OBS, inv=[gun, vest])}
        v0, _ = F.encode_state({"obs": dict(OBS, inv=[])})
        v1, t1 = F.encode_state(base)
        self.assertEqual(len(v1), F.STATE_DIM)
        self.assertGreater(len(t1), 2)
        self.assertEqual(F.VERSION, 3)   # 2: protection and clothing status (reward version 3); 3: where the zombies are


if __name__ == "__main__":
    unittest.main()
