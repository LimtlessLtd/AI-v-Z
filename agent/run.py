"""Run the self-taught agent: it plays through the mod's gym, logs every decision, and serves a dashboard.

    python -m agent.run                  # from the repo root; dashboard http://127.0.0.1:8799/
    python -m agent.run --speed 1        # start at normal speed, to watch (the default is 3x, to learn)

While it runs, the agent plays instead of the rules baseline (start one or the other, not both: they share
the dashboard port). Stopping it hands the character back to the baseline within ~6 s. The game speed can
be changed while it runs with the dashboard's 1x/2x/3x buttons, or with G in game.

Experience goes to logs/experience/YYYYMMDD-HH.jsonl.gz, one line per decision:
    {ts, life, id, reason, obs, options, choice, probs, policy, reward, parts, dead}
where reward/parts are for what happened since the previous decision of the same life. That's everything
the learner (Phase 4) needs, and the reward can be recomputed later from the raw observations.
"""

import argparse
import gzip
import json
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

from agent.link import DEFAULT_LUA_DIR, SPEEDS, GameLink  # noqa: E402
from agent.lives import Lives  # noqa: E402
from agent.policies import RandomPolicy  # noqa: E402

PAGE = (Path(__file__).resolve().parent / "agent.html").read_bytes()


class ExperienceLog:
    """Hourly gzip files of decisions; a new gzip member per flush, which gzip readers handle."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lines, self.hour = [], None

    def add(self, record):
        hour = datetime.now().strftime("%Y%m%d-%H")
        if self.hour and hour != self.hour:
            self.flush()
        self.hour = hour
        self.lines.append(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        if len(self.lines) >= 20 or record.get("dead"):
            self.flush()

    def flush(self):
        if not self.lines:
            return
        with gzip.open(self.root / f"{self.hour}.jsonl.gz", "at", encoding="utf-8") as f:
            f.write("\n".join(self.lines) + "\n")
        self.lines = []


class Agent:
    def __init__(self, args):
        self.link = GameLink(args.lua_dir, getattr(args, "speed", 1))
        self.log_dir = Path(args.log_dir or ROOT / "logs")
        self.log_dir.mkdir(exist_ok=True)
        self.lives = Lives(self.log_dir)
        self.exp = ExperienceLog(self.log_dir / "experience")
        self.policy = RandomPolicy()
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
               "last": msg.get("last"), "reward": r, "parts": parts, "dead": bool(msg.get("dead")), "new_life": new}
        if finished:
            self.recent.appendleft(f"life {finished['life']} ({finished['who']}) {finished['ended']} after "
                                   f"{finished['hours']} game hours, {finished['kills']} kills, reward {finished['reward']}")
        if new:
            self.recent.appendleft(f"life {life.number} begins: {life.name}")
        if not msg.get("dead") and life:
            i, probs, note = self.policy.choose(msg)
            if i is not None:
                self.link.act(msg["id"], i, f"life {life.number}: {note}")
                life.decisions += 1
                opt = msg["options"][i]
                life.last_choice = opt.get("verb")
                rec.update(choice=i, probs=[round(p, 4) for p in probs], policy=self.policy.name)
                if opt.get("verb") != "continue":
                    self.recent.appendleft(f"#{msg['id']} {msg.get('reason')}: {opt.get('verb')} "
                                           f"{opt.get('name') or opt.get('dir') or opt.get('recipe') or ''}".rstrip())
        self.exp.add(rec)
        with self.lock:
            self.decisions += 1
            self.last_at = time.time()
            self.last = {"msg": msg, "choice": rec.get("choice"), "probs": rec.get("probs"), "reward": r, "parts": parts}

    def snapshot(self):
        with self.lock:
            cur = self.lives.current
            last = self.last or {}
            msg = last.get("msg") or {}
            obs = msg.get("obs") or {}
            return {
                "connected": time.time() - self.last_at < 15 if self.last_at else False,
                "policy": self.policy.name, "decisions": self.decisions,
                "life": None if not cur else {"number": cur.number, "who": cur.name, "hours": cur.hours(),
                                              "kills": cur.kills, "reward": round(cur.reward, 2), "parts": cur.parts,
                                              "decisions": cur.decisions, "items": len(cur.progress.items),
                                              "buildings": len(cur.progress.buildings)},
                "obs": {k: obs.get(k) for k in ("t", "health", "moodles", "body", "weight", "maxWeight", "held", "where", "near", "speed")}
                       | {"zombies": len(obs.get("zombies") or [])},
                "reason": msg.get("reason"), "last": msg.get("last"), "err": msg.get("err"), "gym": msg.get("gym"),
                # asked: what this agent asks for; mode: what the game plays at (G may have changed it);
                # now: how fast it actually runs (0 paused, 1 while you drive or just after a zombie is spotted);
                # pending: the game hasn't reported since the last ask
                "speed": {"asked": self.link.speed, "mode": (msg.get("speed") or {}).get("mode"), "now": obs.get("speed"),
                          "pending": (msg.get("speed") or {}).get("asked") != f"{self.link.speed}#{self.link.ask}"},
                "options": [{**o, "p": (last.get("probs") or [None] * len(msg.get("options") or []))[i]}
                            for i, o in enumerate(msg.get("options") or [])],
                "choice": last.get("choice"), "reward": last.get("reward"), "parts": last.get("parts"),
                "lives": self.lives.history[-60:], "recent": list(self.recent),
            }

    def make_server(self):
        """The dashboard: 127.0.0.1 only. The one thing it can change is the game speed."""
        agent = self

        class Handler(BaseHTTPRequestHandler):
            def _local(self):
                host = (self.headers.get("Host") or "").split(":")[0]
                if host not in ("127.0.0.1", "localhost"):
                    self.send_error(403)   # blocks DNS-rebinding pages
                    return False
                return True

            def _send(self, body, ctype):
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if not self._local():
                    return
                if self.path in ("/", "/agent"):
                    self._send(PAGE, "text/html; charset=utf-8")
                elif self.path == "/api/agent":
                    self._send(json.dumps(agent.snapshot()).encode(), "application/json")
                else:
                    self.send_error(404)

            def do_POST(self):
                if not self._local():
                    return
                # other web pages open in your browser can't ask: they'd send their own Origin, and a JSON
                # body from another origin needs a CORS preflight this server never answers
                port = self.server.server_address[1]
                origin = self.headers.get("Origin")
                if origin and origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
                    self.send_error(403)
                    return
                if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                    self.send_error(415)
                    return
                if self.path != "/api/speed":
                    self.send_error(404)
                    return
                try:
                    n = min(int(self.headers.get("Content-Length") or 0), 1000)
                    agent.link.ask_speed(int(json.loads(self.rfile.read(n) or b"{}").get("speed")))
                except (ValueError, TypeError, AttributeError):
                    self.send_error(400, f"speed must be one of {SPEEDS}")
                    return
                self._send(json.dumps({"asked": agent.link.speed}).encode(), "application/json")

            def log_message(self, *a):
                pass

        return ThreadingHTTPServer(("127.0.0.1", self.port), Handler)

    def serve(self):
        self.make_server().serve_forever()

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
    ap.add_argument("--log-dir", default=None)
    ap.add_argument("--speed", type=int, choices=SPEEDS, default=3,
                    help="game speed to start at: 3 (default) to learn faster, 1 to watch")
    args = ap.parse_args()
    agent = Agent(args)
    threading.Thread(target=agent.serve, daemon=True).start()
    print(f"AI-v-Z agent ({agent.policy.name} policy, {args.speed}x speed); life {agent.lives.count} so far; "
          f"dashboard http://127.0.0.1:{args.port}/", flush=True)
    try:
        agent.run()
    except KeyboardInterrupt:
        print("agent stopped; the rules baseline takes over if it's running", flush=True)


if __name__ == "__main__":
    main()
