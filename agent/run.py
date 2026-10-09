"""Run the self-taught agent: it plays through the mod's gym, logs every decision, and serves a dashboard.

    python -m agent.run                  # from the repo root; dashboard http://127.0.0.1:8799/
    python -m agent.run --policy probe   # test tool: tries every kind of option in game (logs/probe/report.txt)

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
from agent.lives import Lives  # noqa: E402
from agent.policies import ProbePolicy, RandomPolicy  # noqa: E402

PAGE = (Path(__file__).resolve().parent / "agent.html").read_bytes()


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
        self.policy = ProbePolicy() if probe else RandomPolicy()
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
        if finished:
            self.recent.appendleft(f"life {finished['life']} ({finished['who']}) {finished['ended']} after "
                                   f"{finished['hours']} game hours, {finished['kills']} kills, reward {finished['reward']}")
        if new:
            self.recent.appendleft(f"life {life.number} begins: {life.name}")
        if self.lives.resumed:
            self.recent.appendleft(f"life {life.number} ({life.name}) carries on after a restart")
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
        self.lives.save()
        if hasattr(self.policy, "report") and (msg.get("dead") or self.decisions % 10 == 0):
            tries = "\n".join(json.dumps(x, ensure_ascii=False) for x in self.policy.results[-80:])
            (self.log_dir / "report.txt").write_text(f"{self.policy.report()}\n\n{tries}\n", encoding="utf-8")
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
                "options": [{**o, "p": (last.get("probs") or [None] * len(msg.get("options") or []))[i]}
                            for i, o in enumerate(msg.get("options") or [])],
                "choice": last.get("choice"), "reward": last.get("reward"), "parts": last.get("parts"),
                "lives": self.lives.history[-60:], "recent": list(self.recent),
            }

    def serve(self):
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

        ThreadingHTTPServer(("127.0.0.1", self.port), Handler).serve_forever()

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
    ap.add_argument("--policy", choices=("random", "probe"), default="random")
    args = ap.parse_args()
    agent = Agent(args)
    threading.Thread(target=agent.serve, daemon=True).start()
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
