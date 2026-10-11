"""Run the self-taught agent: it plays through the mod's gym, logs every decision, learns, and serves a dashboard.

    python -m agent.run                  # from the repo root; dashboard http://127.0.0.1:8799/ (Learning: /learning)
    python -m agent.run --policy random  # plays at random and doesn't train (Phase 3 behaviour)
    python -m agent.run --policy probe   # test tool: tries every kind of option in game (logs/probe/report.txt)

The default net policy plays by the network's scores (agent/net.py) and retrains it every 15 minutes in a
separate low-priority process (agent/learn.py, also runnable by hand), from all the experience so far.

While it runs, the agent plays instead of the rules baseline (start one or the other, not both: they share
the dashboard port). Stopping it hands the character back to the baseline within ~6 s. Set the game speed
with the game's own buttons (or F3-F6); the mod keeps your pick while the agent plays.

Experience goes to logs/experience/YYYYMMDD-HH.jsonl.gz, one line per decision:
    {ts, life, id, reason, obs, options, last, choice, probs, policy, reward, parts, dead, new_life, resumed}
where reward/parts are for what happened since the previous decision of the same life ("resumed": the agent
was restarted in between, so that stretch earns nothing). These records support later learning,
and the reward can be recomputed later from the raw observations. Action and perception coverage are
still incomplete (docs/PHASE3_COVERAGE.md); these records have no hearing input. Restarting carries on
with the same character (logs/agent-state.json).
"""

import argparse
import gzip
import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.link import DEFAULT_LUA_DIR, GameLink  # noqa: E402
from agent.hearing import Hearing  # noqa: E402
from agent.lives import Lives  # noqa: E402
from agent.policies import NetPolicy, ProbePolicy, RandomPolicy  # noqa: E402

PAGE = (Path(__file__).resolve().parent / "agent.html").read_bytes()
LEARN_PAGE = (Path(__file__).resolve().parent / "learning.html").read_bytes()
BELOW_NORMAL = 0x00004000   # Windows process priority class for training, so the game keeps the CPU it needs


class Trainer:
    """Runs a training round (python -m agent.learn) in its own process when the saved network is more than
    `every_min` minutes old, at below-normal priority. The playing agent picks up each new network itself."""

    def __init__(self, log_dir, every_min):
        self.log_dir, self.every = Path(log_dir), every_min * 60
        self.model = self.log_dir / "model" / "qnet.pt"
        self.running, self.started, self.last_try, self.last_code = False, None, None, None

    def due(self):
        if self.last_try and time.time() - self.last_try < self.every:
            return False
        try:
            return time.time() - self.model.stat().st_mtime >= self.every
        except OSError:
            return True

    def loop(self):
        while True:
            if self.due():
                self.run_once()
            time.sleep(15)

    def run_once(self):
        self.running, self.started = True, time.time()
        self.last_try = self.started
        (self.log_dir / "model").mkdir(parents=True, exist_ok=True)
        try:
            with (self.log_dir / "model" / "train.log").open("a", encoding="utf-8") as log:
                log.write(f"--- {datetime.now().isoformat(timespec='seconds')}\n")
                log.flush()
                r = subprocess.run([sys.executable, "-m", "agent.learn", "--log-dir", str(self.log_dir)], cwd=ROOT,
                                   stdout=log, stderr=subprocess.STDOUT, timeout=3600,
                                   creationflags=BELOW_NORMAL if os.name == "nt" else 0)
            self.last_code = r.returncode
        except (OSError, subprocess.SubprocessError) as e:
            self.last_code = repr(e)
        finally:
            self.running = False

    def status(self):
        return {"every_min": round(self.every / 60), "running": self.running,
                "running_s": round(time.time() - self.started) if self.running else None, "last_code": self.last_code}


class ExclusiveHTTPServer(ThreadingHTTPServer):
    """A dashboard server that owns its port. ThreadingHTTPServer sets SO_REUSEADDR, which on Windows lets a
    second process bind the same port without an error, so a second agent or bridge ran alongside the first."""

    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class ExperienceLog:
    """Hourly gzip files of decisions; a new gzip member per flush, which gzip readers handle. Flushed every
    20 decisions or 30 s, so a killed agent (Windows gives no chance to clean up) loses half a minute at most."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lines, self.hour, self.flushed = [], None, time.time()

    def add(self, record):
        hour = datetime.now().strftime("%Y%m%d-%H")
        if self.hour and hour != self.hour:
            self.flush()
        self.hour = hour
        self.lines.append(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        if len(self.lines) >= 20 or record.get("dead") or time.time() - self.flushed > 30:
            self.flush()

    def flush(self):
        self.flushed = time.time()
        if not self.lines:
            return
        with gzip.open(self.root / f"{self.hour}.jsonl.gz", "at", encoding="utf-8") as f:
            f.write("\n".join(self.lines) + "\n")
        self.lines = []


class Agent:
    def __init__(self, args):
        self.link = GameLink(args.lua_dir)
        probe = getattr(args, "policy", "random") == "probe"
        # the probe's choices are scripted, so its experience stays apart from what the agent learns from
        self.log_dir = Path(args.log_dir or ROOT / "logs" / ("probe" if probe else ""))
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.lives = Lives(self.log_dir)
        self.exp = ExperienceLog(self.log_dir / "experience")
        name = getattr(args, "policy", "net")
        self.policy = ProbePolicy() if probe else RandomPolicy() if name == "random" else \
            NetPolicy(self.log_dir / "model" / "qnet.pt", temperature=getattr(args, "temperature", 0.5),
                      explore=getattr(args, "explore", 0.1))
        every = getattr(args, "train_every", 15)
        self.trainer = Trainer(self.log_dir, every) if name == "net" and every > 0 else None
        self.hearing = Hearing()   # no capture source yet: records 'unavailable' rather than inventing input
        self.port = args.port
        self.lock = threading.Lock()
        self.last = None            # the latest request and choice, for the dashboard
        self.recent = deque(maxlen=30)
        self.decisions = 0
        self.last_at = 0.0

    def handle(self, msg):
        life, r, parts, new, finished = self.lives.observe(msg)
        rec = {"ts": datetime.now().isoformat(timespec="seconds"), "life": life.number if life else None,
               "id": msg.get("id"), "reason": msg.get("reason"), "obs": msg.get("obs"), "options": msg.get("options"),
               "last": msg.get("last"), "reward": r, "parts": parts, "dead": bool(msg.get("dead")), "new_life": new,
               "resumed": self.lives.resumed}
        obs = msg.get("obs") or {}
        rec["hearing"] = self.hearing.snapshot(msg.get("id"), (obs.get("t") or {}).get("age"), obs.get("speed"))
        if finished:
            self.recent.appendleft(f"life {finished['life']} ({finished['who']}) {finished['ended']} after "
                                   f"{finished['hours']} game hours, {finished['kills']} kills, reward {finished['reward']}")
        if new:
            self.recent.appendleft(f"life {life.number} begins: {life.name}")
        if self.lives.resumed:
            self.recent.appendleft(f"life {life.number} ({life.name}) carries on after a restart")
        note = None
        if not msg.get("dead") and (life or msg.get("creation")):
            i, probs, note = self.policy.choose(msg)
            if i is not None:
                self.link.act(msg["id"], i, f"life {life.number}: {note}" if life else f"creation: {note}")
                # "net" only once there is a network; before that the net policy plays at random
                acting = self.policy.name if getattr(self.policy, "net", True) is not None else "random"
                opt = msg["options"][i]
                if life:
                    life.decisions += 1
                    life.last_choice = opt.get("verb")
                    life.policies[acting] = life.policies.get(acting, 0) + 1
                rec.update(choice=i, probs=[round(p, 4) for p in probs], policy=acting)
                q = getattr(self.policy, "last_q", None)
                if q:
                    rec["q"] = [round(x, 3) for x in q]
                if opt.get("verb") != "continue":
                    self.recent.appendleft(f"#{msg['id']} {msg.get('reason')}: {opt.get('verb')} "
                                           f"{opt.get('name') or opt.get('dir') or opt.get('recipe') or ''}".rstrip())
        self.exp.add(rec)
        self.lives.save()
        if hasattr(self.policy, "report") and (msg.get("dead") or self.decisions % 10 == 0):
            tries = "\n".join(json.dumps(x, ensure_ascii=False) for x in self.policy.results[-80:])
            (self.log_dir / "report.txt").write_text(f"{self.policy.report()}\n\n{tries}\n", encoding="utf-8")
        with self.lock:
            self.decisions += 1
            self.last_at = time.time()
            self.last = {"msg": msg, "choice": rec.get("choice"), "probs": rec.get("probs"), "q": rec.get("q"),
                         "reward": r, "parts": parts, "note": note}

    def snapshot(self):
        with self.lock:
            cur = self.lives.current
            last = self.last or {}
            msg = last.get("msg") or {}
            obs = msg.get("obs") or {}
            meta = getattr(self.policy, "meta", None) or {}
            n = len(msg.get("options") or [])
            probs, qs = last.get("probs") or [None] * n, last.get("q") or [None] * n
            return {
                "connected": time.time() - self.last_at < 15 if self.last_at else False,
                "policy": self.policy.name, "decisions": self.decisions, "note": last.get("note"),
                "model": {k: meta.get(k) for k in ("round", "trained_at", "transitions")} if meta else None,
                "life": None if not cur else {"number": cur.number, "who": cur.name, "hours": cur.hours(),
                                              "kills": cur.kills, "reward": round(cur.reward, 2), "parts": cur.parts,
                                              "decisions": cur.decisions, "items": len(cur.progress.items),
                                              "buildings": len(cur.progress.buildings)},
                "obs": {k: obs.get(k) for k in ("t", "health", "moodles", "body", "weight", "maxWeight", "held", "where", "near", "speed")}
                       | {"zombies": len(obs.get("zombies") or [])},
                "reason": msg.get("reason"), "last": msg.get("last"), "err": msg.get("err"), "gym": msg.get("gym"),
                "options": [{**o, "p": probs[i], "q": qs[i]} for i, o in enumerate(msg.get("options") or [])],
                "choice": last.get("choice"), "reward": last.get("reward"), "parts": last.get("parts"),
                "lives": self.lives.history[-60:], "recent": list(self.recent),
            }

    def _rules_lives(self):
        """Lives the rules baseline played (written by the bridge to logs/lives-rules.jsonl), for comparison."""
        try:
            lines = (self.log_dir / "lives-rules.jsonl").read_text(encoding="utf-8").splitlines()
            recs = [json.loads(x) for x in lines[-400:] if x.strip()]
        except (OSError, ValueError):
            return []
        return [{"life": x.get("life"), "policy": "rules", "hours": x.get("hours", 0), "reward": x.get("reward"),
                 "kills": x.get("kills", 0), "items": x.get("items_seen"), "buildings": x.get("buildings"),
                 "decisions": x.get("decisions", 0)} for x in recs if x.get("ended") == "died"]

    def learning(self):
        """The Learning page's data: training rounds, and lives compared by the policy that played them."""
        hist = []
        try:
            lines = (self.log_dir / "model" / "history.jsonl").read_text(encoding="utf-8").splitlines()
            hist = [json.loads(x) for x in lines[-200:] if x.strip()]
        except (OSError, ValueError):
            pass
        lives = [{"life": x.get("life"), "policy": x.get("policy") or "random", "hours": x.get("hours", 0),
                  "reward": x.get("reward", 0), "kills": x.get("kills", 0), "items": x.get("items_seen", 0),
                  "buildings": x.get("buildings", 0), "decisions": x.get("decisions", 0)}
                 for x in self.lives.history if x.get("ended") == "died"]
        lives += self._rules_lives()
        return {"history": hist, "lives": lives[-400:], "trainer": self.trainer.status() if self.trainer else None,
                "policy": self.policy.name}

    def server(self):
        """The dashboard's HTTP server, bound to 127.0.0.1 (raises OSError if the port is taken)."""
        agent = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                host = (self.headers.get("Host") or "").split(":")[0]
                if host not in ("127.0.0.1", "localhost"):
                    self.send_error(403)   # blocks DNS-rebinding pages from reading it
                    return
                if self.path in ("/", "/agent"):
                    body, ctype = PAGE, "text/html; charset=utf-8"
                elif self.path == "/api/agent":
                    body, ctype = json.dumps(agent.snapshot()).encode(), "application/json"
                elif self.path == "/learning":
                    body, ctype = LEARN_PAGE, "text/html; charset=utf-8"
                elif self.path == "/api/learning":
                    with agent.lock:
                        data = agent.learning()
                    body, ctype = json.dumps(data).encode(), "application/json"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        return ExclusiveHTTPServer(("127.0.0.1", self.port), Handler)

    def run(self):
        self.link.start_heartbeat()
        try:
            while True:
                msg = self.link.wait(1.0)
                if msg is None:
                    continue
                try:
                    self.handle(msg)
                except Exception as e:   # one bad message must not stop the agent
                    print(f"[agent] error handling #{msg.get('id')}: {e!r}", flush=True)
        finally:
            self.exp.flush()
            self.link.stop()


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--lua-dir", default=str(DEFAULT_LUA_DIR))
    ap.add_argument("--log-dir", default=None, help="default logs/ (logs/probe/ for the probe)")
    ap.add_argument("--policy", choices=("net", "random", "probe"), default="net")
    ap.add_argument("--train-every", type=float, default=15, help="minutes between training rounds (0: never)")
    ap.add_argument("--temperature", type=float, default=0.5,
                    help="net policy: lower picks the top-rated option more often (in spreads of the scores)")
    ap.add_argument("--explore", type=float, default=0.1, help="net policy: share of picks made at random")
    args = ap.parse_args()
    agent = Agent(args)
    # The port doubles as a lock: a second agent (or the bridge) on it used to lose only its dashboard and
    # play on, so two answered the game and appended to the same experience file, which broke its gzip
    # stream (logs/experience/20261011-11 and -12).
    try:
        server = agent.server()
    except OSError as e:
        print(f"port {args.port} is taken ({e.strerror}): another agent or the bridge is already running. "
              f"Stop it first.", flush=True)
        sys.exit(1)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if agent.trainer:
        threading.Thread(target=agent.trainer.loop, daemon=True).start()
    cur = agent.lives.current
    print(f"AI-v-Z agent ({agent.policy.name} policy); {agent.lives.count} lives so far"
          f"{f', carrying on with life {cur.number} ({cur.name})' if cur else ''}; "
          f"dashboard http://127.0.0.1:{args.port}/", flush=True)
    try:
        agent.run()
    except KeyboardInterrupt:
        print("agent stopped; the rules baseline takes over if it's running", flush=True)


if __name__ == "__main__":
    main()
