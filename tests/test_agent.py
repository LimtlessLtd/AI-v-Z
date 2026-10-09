"""Tests for the self-taught agent's side: reward, lives, the file link, the random policy, the main loop.

Run from the repo root:  python -m unittest discover -s tests
"""

import argparse
import copy
import gzip
import http.client
import json
import random
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import reward  # noqa: E402
from agent.link import GameLink  # noqa: E402
from agent.lives import Lives  # noqa: E402
from agent.policies import RandomPolicy  # noqa: E402

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
            (Path(tmp) / "obs.json").write_text('{"id": 8, "obs": {', encoding="utf-8")   # caught mid-write
            self.assertIsNone(link.poll())

    def test_the_heartbeat_carries_the_speed_asked_for(self):
        with tempfile.TemporaryDirectory() as tmp:
            link = GameLink(tmp, speed=3)
            beat = lambda: (Path(tmp) / "gym.txt").read_text(encoding="utf-8").strip().split("|")
            link.beat()
            on, n, speed, ask = beat()
            self.assertEqual((on, n, speed), ("on", "1", "3"))
            link.ask_speed(1)    # beats straight away, with a new ask number
            self.assertEqual(beat(), ["on", "2", "1", str(int(ask) + 1)])
            link.ask_speed(1)    # the same speed again is a new ask: it undoes a G press in between
            self.assertEqual(beat()[2:], ["1", str(int(ask) + 2)])
            with self.assertRaises(ValueError):
                link.ask_speed(10)
            self.assertEqual(GameLink(tmp, speed=9).speed, 1)
            link.stop()
            self.assertEqual(beat(), ["off"])


class PolicyTests(unittest.TestCase):
    def test_random_policy_mostly_lets_things_finish(self):
        pol = RandomPolicy(random.Random(1))
        msg = {"options": [{"verb": "continue"}] + OPTIONS}
        picks = [pol.choose(msg)[0] for _ in range(700)]
        self.assertGreater(picks.count(0), picks.count(1) * 2)
        i, probs, _ = pol.choose(msg)
        self.assertAlmostEqual(sum(probs), 1.0)
        self.assertEqual(pol.choose({"options": []})[0], None)


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


class DashboardTests(unittest.TestCase):
    """The dashboard's one write: the game speed, from its own page only."""

    def setUp(self):
        from agent.run import Agent
        self.tmp = tempfile.TemporaryDirectory()
        self.agent = Agent(argparse.Namespace(lua_dir=self.tmp.name, log_dir=self.tmp.name, port=0, speed=3))
        self.server = self.agent.make_server()
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def post(self, body, ctype="application/json", host=None, origin=None, path="/api/speed"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": ctype, "Host": host or f"127.0.0.1:{self.port}"}
        if origin:
            headers["Origin"] = origin
        c.request("POST", path, body=json.dumps(body), headers=headers)
        status = c.getresponse().status
        c.close()
        return status

    def test_its_own_page_can_change_the_speed(self):
        self.assertEqual(self.agent.link.speed, 3)
        self.assertEqual(self.post({"speed": 1}, origin=f"http://127.0.0.1:{self.port}"), 200)
        self.assertEqual(self.agent.link.speed, 1)
        self.assertEqual((Path(self.tmp.name) / "gym.txt").read_text(encoding="utf-8").split("|")[2], "1")
        self.assertEqual(self.post({"speed": 2}), 200)   # no Origin: curl or a script on this machine
        snap = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/agent", timeout=5))
        self.assertEqual(snap["speed"]["asked"], 2)
        self.assertTrue(snap["speed"]["pending"])   # the game hasn't reported since

    def test_other_pages_and_bad_asks_are_refused(self):
        self.assertEqual(self.post({"speed": 1}, origin="http://evil.example"), 403)
        self.assertEqual(self.post({"speed": 1}, host="evil.example"), 403)   # DNS rebinding
        self.assertEqual(self.post({"speed": 1}, ctype="text/plain"), 415)     # a form or no-preflight fetch
        self.assertEqual(self.post({"speed": 10}), 400)
        self.assertEqual(self.post(["x"]), 400)
        self.assertEqual(self.post({"speed": 1}, path="/api/other"), 404)
        self.assertEqual(self.agent.link.speed, 3)


if __name__ == "__main__":
    unittest.main()
