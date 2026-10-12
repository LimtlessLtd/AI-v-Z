"""Tests for the public page's export (agent/site.py) and the Learning data it shares with the dashboard.

Run from the repo root:  python -m unittest discover -s tests
"""

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from agent import reward  # noqa: E402
from agent import site  # noqa: E402
from agent.lives import learning_data  # noqa: E402
from test_agent import OBS, later  # noqa: E402
from test_learning import write_experience  # noqa: E402

needs_torch = unittest.skipUnless(importlib.util.find_spec("torch"), "PyTorch isn't installed here")

# every key a replay step may have (agent/site.py step); anything else would be a field leaking onto the page
STEP_KEYS = {"t", "age", "why", "pol", "n", "o", "pos", "hp", "m", "w", "z", "in", "held", "mv", "last", "r", "parts", "dead"}
OPTIONS = [{"verb": "walk", "dir": d, "dx": 0, "dy": -1, "zombies": 0} for d in "NESW"] + \
    [{"verb": "take", "name": f"Item {k}", "type": f"Base.Item{k}", "d": 1.5, "from": "counter"} for k in range(10)]


def record(life, k, choice, **extra):
    obs = later(copy.deepcopy(OBS), 5 * k, moodles={"thirst": 2},
                zombies=[{"dx": 3.0, "dy": -4.0, "d": 5.0, "facing": 0.9, "down": False, "blocked": False}])
    q = [-100.0 - 10 * i for i in range(len(OPTIONS))]   # option 0 rated best, the last one worst
    return {"ts": "2026-10-12T10:00:00", "life": life, "id": 100 * life + k, "reason": "done", "obs": obs,
            "options": OPTIONS, "last": {"verb": "walk", "status": "done"}, "reward": 1.5, "parts": {"alive": 1.5},
            "reward_v": reward.VERSION, "dead": False, "new_life": k == 0, "resumed": False,
            "hearing": {"real": 1791811317.8, "available": False}, "choice": choice, "probs": [1 / len(OPTIONS)] * len(OPTIONS),
            "policy": "net", "q": q, **extra}


def make_logs(root):
    root = Path(root)
    lives = [{"life": 1, "who": "Old Timer", "save": "2026-10-08_21-30-48", "ended": "died", "hours": 50.0, "kills": 3,
              "reward": -20.0, "decisions": 900, "policy": None, "born_age": 1.0},
             {"life": 2, "who": "Chris Hooks", "save": "test", "ended": "died", "hours": 2.0, "kills": 0,
              "reward": -900.0, "reward_v": reward.VERSION, "decisions": 3, "policy": "net", "born_age": 26.0},
             {"life": 3, "who": "Sam Lee", "save": "test", "ended": "died", "hours": 0.5, "kills": 1,
              "reward": -990.0, "reward_v": reward.VERSION, "decisions": 2, "policy": "net", "born_age": 26.0}]
    (root / "lives.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lives), encoding="utf-8")
    (root / "lives-rules.jsonl").write_text(json.dumps({"life": 1, "ended": "died", "hours": 4.0, "kills": 2}) + "\n",
                                            encoding="utf-8")
    (root / "model").mkdir()
    rounds = [{"round": 1, "trained_at": "2026-10-12T10:00:00", "steps": 2000, "fresh": True, "decisions": 10, "lives": 2,
               "loss_first": 1.0, "loss": 0.5, "q_mean": -10.0, "reward_v": reward.VERSION, "seconds": 30,
               "verbs": {"walk": 5.0, "take": -5.0}}]
    (root / "model" / "history.jsonl").write_text(json.dumps(rounds[0]) + "\n", encoding="utf-8")
    # life 1 has no experience left; life 2 picked an option outside the 10 best; life 3 picked the best
    write_experience(root, [record(2, 0, 12), record(2, 1, 13), record(2, 2, 0, dead=True), record(3, 0, 0), record(3, 1, 1)])


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.logs, self.out = Path(self.tmp.name) / "logs", Path(self.tmp.name) / "out"
        self.logs.mkdir()
        make_logs(self.logs)

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, *parts):
        return json.loads((self.out.joinpath(*parts)).read_text(encoding="utf-8"))

    def test_summary_keeps_the_rounds_and_every_life(self):
        site.export(self.logs, self.out)
        s = self.read("summary.json")
        self.assertEqual(set(s["history"][0]), set(site.ROUND_KEYS))   # "steps" and "fresh" stay home
        self.assertEqual([x["life"] for x in s["lives"]], [1, 2, 3, 1])
        self.assertEqual(s["lives"][0]["policy"], "random")             # lives before Phase 4 were random
        self.assertIsNone(s["lives"][0]["reward"])                      # an old reward version's total isn't shown
        self.assertEqual(s["lives"][-1]["policy"], "rules")
        self.assertIsNone(s["playing"])

    def test_replays_only_for_lives_with_experience(self):
        site.export(self.logs, self.out)
        index = self.read("lives", "index.json")
        self.assertEqual([x["life"] for x in index], [2, 3])
        self.assertIn("recent", index[0]["picked"])
        self.assertFalse((self.out / "lives" / "1.json").exists())

    def test_replay_steps_carry_only_allow_listed_fields(self):
        site.export(self.logs, self.out)
        text = (self.out / "lives" / "2.json").read_text(encoding="utf-8")
        for left_out in ("hearing", "1791811317", '"save"', "Tshirt", '"stats"', '"inv"'):
            self.assertNotIn(left_out, text)
        rep = json.loads(text)
        self.assertEqual(rep["born"], 26.0)
        self.assertEqual(len(rep["data"]), 3)
        for s in rep["data"]:
            self.assertLessEqual(set(s), STEP_KEYS)
        self.assertEqual(rep["data"][0]["m"], {"thirst": 2})
        self.assertEqual(rep["data"][0]["z"], [[3.0, -4.0, 0.9, 0, 0]])
        self.assertEqual(rep["data"][2]["dead"], 1)

    def test_options_are_the_ten_best_by_q_plus_the_pick(self):
        site.export(self.logs, self.out)
        first = self.read("lives", "2.json")["data"][0]
        self.assertEqual(first["n"], len(OPTIONS))
        self.assertEqual(len(first["o"]), site.TOP + 1)
        qs = [o[3] for o in first["o"][:site.TOP]]
        self.assertEqual(qs, sorted(qs, reverse=True))
        self.assertEqual(first["o"][-1][:2], ["take", "Item 8"])        # option 12, picked though rated low
        self.assertEqual([o[5] for o in first["o"]], [0] * site.TOP + [1])
        best = self.read("lives", "3.json")["data"][0]
        self.assertEqual(len(best["o"]), site.TOP)                       # the pick is already among the best
        self.assertEqual(best["o"][0][5], 1)

    def test_a_replay_dropped_from_the_index_is_removed(self):
        (self.out / "lives").mkdir(parents=True)
        (self.out / "lives" / "99.json").write_text("{}", encoding="utf-8")
        site.export(self.logs, self.out)
        self.assertFalse((self.out / "lives" / "99.json").exists())

    def test_the_zip_uses_forward_slashes(self):
        site.export(self.logs, self.out)
        dest = Path(self.tmp.name) / "snapshot.zip"
        site.zip_dir(self.out, dest)
        names = zipfile.ZipFile(dest).namelist()
        self.assertIn("lives/index.json", names)
        self.assertFalse(any("\\" in n for n in names))

    def test_no_network_yet_is_said_plainly(self):
        site.export(self.logs, self.out)
        net = self.read("net.json")
        self.assertFalse(net["available"])
        self.assertTrue(net["why"])
        self.assertFalse((self.out / "qnet.npz").exists())

    @needs_torch
    def test_the_network_is_exported_as_plain_arrays(self):
        import numpy as np
        from agent import net as N
        model = N.QNet()
        N.save(model, self.logs / "model" / "qnet.pt", round=7, trained_at="2026-10-12T10:00:00")
        site.export(self.logs, self.out)
        net = self.read("net.json")
        self.assertTrue(net["available"])
        self.assertEqual(net["round"], 7)
        self.assertEqual(net["total"], sum(p.numel() for p in model.parameters()))
        with np.load(self.out / "qnet.npz", allow_pickle=False) as z:
            self.assertEqual(set(z.files), set(model.state_dict()))


class LearningDataTests(unittest.TestCase):
    def test_the_dashboard_gets_the_last_rounds_and_lives(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_logs(tmp)
            history = [json.loads(x) for x in (Path(tmp) / "lives.jsonl").read_text(encoding="utf-8").splitlines()]
            d = learning_data(tmp, history)
            self.assertEqual(set(d), {"history", "lives"})
            self.assertEqual(len(d["history"]), 1)
            self.assertEqual(learning_data(tmp, history, lives=2)["lives"][-1]["policy"], "rules")
            self.assertEqual(len(learning_data(tmp, history, lives=2)["lives"]), 2)
            self.assertEqual(len(learning_data(tmp, history, rounds=None, lives=None)["lives"]), 4)


if __name__ == "__main__":
    unittest.main()
