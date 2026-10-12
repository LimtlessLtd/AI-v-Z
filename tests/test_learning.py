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
                     "dead": False, "new_life": k == 0, "resumed": False})
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

    def test_what_the_screen_doesnt_show_stays_out(self):
        self.assertEqual(F.encode_state({"obs": {"health": 87.3}})[0], F.encode_state({"obs": {"health": 82.0}})[0])
        self.assertNotEqual(F.encode_state({"obs": {"health": 87.3}})[0], F.encode_state({"obs": {"health": 40.0}})[0])
        k = list(F.OPTION_NUMBERS).index("locked")
        self.assertEqual(F.encode_option({"verb": "window", "locked": 1})[0][k], 0.0)
        self.assertEqual(F.encode_option({"verb": "door", "locked": 1})[0][k], 1.0)
        e = list(F.OPTION_NUMBERS).index("endurance")
        self.assertEqual(F.encode_option({"verb": "exercise", "endurance": 1})[0][e], 0.0)
        self.assertEqual(len(F.encode_option({"verb": "window"})[0]), F.OPTION_DIM)

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
                             "reward": 0.0, "dead": False, "new_life": k == 0, "resumed": False})
                if k:
                    recs[-1]["reward"] = 1.0 if recs[-2]["choice"] == 0 else -1.0
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
        self.assertEqual(F.item_status_tokens({"type": "Base.Axe"}, "held"), [])
        base = {"obs": dict(OBS, inv=[gun, vest])}
        v0, _ = F.encode_state({"obs": dict(OBS, inv=[])})
        v1, t1 = F.encode_state(base)
        self.assertEqual(len(v1), F.STATE_DIM)
        self.assertGreater(len(t1), 2)
        self.assertEqual(F.VERSION, 1)   # token additions keep the layout and the trained network


if __name__ == "__main__":
    unittest.main()
