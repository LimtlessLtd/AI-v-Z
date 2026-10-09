"""The baseline bridge: hand-written rules play the character. It's the score the learning agent must beat.

    game mod --writes--> %USERPROFILE%/Zomboid/Lua/aivz/percept.json
    bridge   --writes--> %USERPROFILE%/Zomboid/Lua/aivz/intent.txt   "seq|goal|a1|a2|a3|say|why|source"
    you      --watch---> http://127.0.0.1:8799/                       live dashboard (this PC only)

Rules (brain/rules.py) score the goals the mod can carry out right now; the best one is sent to the game.

Run from the repo root:
    python bridge/bridge.py

Uses the Python standard library only.
"""

import argparse
import json
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brain import strategy  # noqa: E402
from brain.percept import Memory, summarize  # noqa: E402

DEFAULT_LUA_DIR = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Zomboid" / "Lua" / "aivz"
RECHECK_S = 6      # re-plan at least this often while a goal runs
STALE_S = 15       # no new percept for this long: the game isn't running the mod
# After a task ends, don't pick the same goal again for a while (seconds). A failed task gets a pause
# before it's retried. Securing or hiding can "finish" without having changed anything, so those rest
# too even when done. Survival goals are never held back.
COOLDOWN_FAILED_S = 60
# A failed flee ("stuck") gets a short pause so the alternatives get a turn; in game a flee that couldn't
# find a path was re-sent eight times in ten seconds.
COOLDOWN_FAILED_SHORT_S = {"flee": 15}
FLEE_COMMIT_S = 8    # once running, don't turn to fight for this long (it flipped every few seconds)
COOLDOWN_DONE_S = {"secure_building": 90, "hide": 60, "sleep": 300, "drop_weight": 120}
NEVER_COOL = {"fight", "flee", "wait", "explore"}
MIND_HTML = (Path(__file__).resolve().parent / "mind.html").read_bytes()


def clean(text, n):
    """Safe for the pipe-separated intent line: no separators, no newlines, bounded length."""
    return " ".join(str(text or "").replace("|", "/").split())[:n]


def intent_line(seq, goal, args, say="", why="", source=""):
    a = [("" if v is None else str(v)) for v in list(args)[:3]]
    a += [""] * (3 - len(a))
    return "|".join([str(seq), goal, *a, clean(say, 90), clean(why, 160), clean(source, 20)])


def bucket(d):
    if d is None:
        return "none"
    return next(b for b in ("<3", "<8", "<15", "<30", "far") if b == "far" or d < float(b[1:]))


def explain(plan):
    """The HUD's one-line reason: the winning score and the runner-up."""
    top = [(g, plan.scores[g]) for g in plan.ranked[:2]]
    return " > ".join(f"{g.replace('_', ' ')} {v:.0f}" for g, v in top)


class Bridge:
    def __init__(self, args):
        self.lua_dir = Path(args.lua_dir)
        self.lua_dir.mkdir(parents=True, exist_ok=True)
        self.percept_path = self.lua_dir / "percept.json"
        self.intent_path = self.lua_dir / "intent.txt"
        self.log_dir = Path(getattr(args, "log_dir", None) or ROOT / "logs")
        self.log_dir.mkdir(exist_ok=True)
        self.state_path = self.log_dir / "bridge-state.json"
        self.port = args.port
        self.mem = Memory()
        self.lock = threading.RLock()
        self.seq = self._load_seq()
        self.current = None
        self.raw, self.raw_at, self.mtime = None, 0.0, 0
        self.situ, self.plan, self.signature = None, None, None
        self.decisions = deque(maxlen=40)
        self.status = "waiting for the game"
        self.dead_logged = False
        self.cooldown = {}   # goal -> time.time() until which it isn't offered
        self.ended_seq = 0   # last task seq whose end was handled

    # ------------------------------------------------------------------ files
    def _load_seq(self):
        try:
            return int(json.loads(self.state_path.read_text(encoding="utf-8")).get("seq", 0))
        except (OSError, ValueError):
            return 0

    def _write_intent(self, line):
        tmp = self.intent_path.with_suffix(".tmp")
        tmp.write_text(line + "\n", encoding="utf-8")
        for _ in range(10):
            try:
                os.replace(tmp, self.intent_path)
                break
            except PermissionError:   # the game is reading it right now
                time.sleep(0.02)
        self.state_path.write_text(json.dumps({"seq": self.seq}), encoding="utf-8")

    def _read_percept(self):
        try:
            mtime = self.percept_path.stat().st_mtime_ns
        except OSError:
            return None
        if mtime == self.mtime:
            return None
        try:
            raw = json.loads(self.percept_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None   # caught the game mid-write; next read gets it
        self.mtime = mtime
        return raw

    def _log(self, name, record):
        path = self.log_dir / f"{name}-{datetime.now():%Y%m%d}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ deciding
    def _signature(self, situ):
        th, p = situ.threat, situ.percept
        moods = p["moodles"]
        return (bucket(th["nearest"]), th["chasing"] > 0, min(th["within10"], 4), th["bleeding"],
                p["where"].startswith("inside"), "night" in p["time"] or "dusk" in p["time"],
                max([moods.get(k, 0) for k in ("thirst", "hunger", "tired", "endurance", "panic")] or [0]),
                tuple(sorted(situ.legal)))

    def on_percept(self, raw):
        with self.lock:
            self.raw, self.raw_at = raw, time.time()
            self.seq = max(self.seq, int(raw.get("ack") or 0))
            if raw.get("dead"):
                if not self.dead_logged:
                    self.dead_logged = True
                    self.mem.note(raw, "died")
                    self._log("deaths", {"ts": datetime.now().isoformat(timespec="seconds"), "time": raw.get("time"),
                                         "who": (raw.get("who") or {}).get("name"), "kills": raw.get("kills"),
                                         "recent": list(self.mem.recent), "last_decisions": list(self.decisions)[-20:]})
                self.status = "dead"
                return
            self.dead_logged = False
            self.mem.update(raw)
            if raw.get("asleep"):
                # the game runs the night; the sleep task reports when the AI wakes up
                self.status = "asleep"
                return
            task = raw.get("task") or {}
            cur = self.current
            ours = cur is not None and task.get("seq") == cur["seq"]
            running = ours and task.get("status") == "running"
            # a task that ended counts even if it wasn't our latest order (an order from before a bridge
            # restart): otherwise the AI stands idle while the bridge thinks its own goal is running
            finished = task.get("status") in ("done", "failed") and int(task.get("seq") or 0) >= (cur["seq"] if cur else 0)
            if finished and task["seq"] != self.ended_seq:
                self.ended_seq = task["seq"]
                goal = task.get("goal")
                if task["status"] == "failed" and goal in COOLDOWN_FAILED_SHORT_S:
                    self.cooldown[goal] = time.time() + COOLDOWN_FAILED_SHORT_S[goal]
                elif goal not in NEVER_COOL:
                    hold = COOLDOWN_FAILED_S if task["status"] == "failed" else COOLDOWN_DONE_S.get(goal, 0)
                    if hold:
                        self.cooldown[goal] = time.time() + hold
            situ = summarize(raw, self.mem)
            now = time.time()
            cooled = [g for g in situ.legal if self.cooldown.get(g, 0) > now]
            if cooled and len(cooled) < len(situ.legal):
                situ.legal = [g for g in situ.legal if g not in cooled]
            self.situ = situ
            if raw.get("manual"):
                self.status = "you're driving"
                return
            self.status = "playing"
            sig = self._signature(situ)
            due = cur is None or finished or sig != self.signature or now - cur["at"] > RECHECK_S
            self.signature = sig
            if not due:
                return
            plan = strategy.plan(situ.percept, situ.legal, cur["goal"] if cur else None, running)
            self.plan = plan
            if (running and cur["goal"] == "flee" and plan.goal == "fight" and "flee" in situ.legal
                    and now - cur.get("t0", now) < FLEE_COMMIT_S):
                cur["at"] = now   # committed to running
                return
            if plan.source == "keep" or (running and plan.goal == cur["goal"]):
                cur["at"] = now
                return
            self._issue(plan.goal, situ.args[plan.goal], situ, plan, force=finished)

    def _issue(self, goal, args, situ, plan, force=False):
        """Send a goal to the game. Returns False when it's the goal already running (unless forced:
        a finished task's goal picked again has to be re-sent to start again)."""
        cur = self.current
        if cur and cur["goal"] == goal and list(cur["args"]) == list(args) and not force:
            cur["at"] = time.time()
            return False
        self.seq += 1
        why = explain(plan)
        self._write_intent(intent_line(self.seq, goal, args, "", why, "rules"))
        if goal == "explore":
            self.mem.explore_dir = situ.threat["explore_heading"]
        started = cur["t0"] if cur and cur["goal"] == goal and "t0" in cur else time.time()
        self.current = {"goal": goal, "args": list(args), "seq": self.seq, "source": "rules", "why": why,
                        "at": time.time(), "t0": started}
        top = sorted(plan.scores.items(), key=lambda kv: -kv[1])[:5]
        entry = {"seq": self.seq, "time": situ.percept["time"], "goal": goal, "source": "rules", "why": why, "top": top}
        self.decisions.append(entry)
        self._log("decisions", {"ts": datetime.now().isoformat(timespec="seconds"), **entry, "args": list(args),
                                "legal": situ.legal, "percept": situ.percept})
        return True

    # ------------------------------------------------------------------ dashboard
    def snapshot(self):
        with self.lock:
            raw = self.raw or {}
            situ = self.situ
            zs = raw.get("zombies") or []
            plan = self.plan
            return {
                "status": self.status if time.time() - self.raw_at < STALE_S or not self.raw else
                "no fresh percept: is the game running with the AI-v-Z mod enabled?",
                "percept_age_s": round(time.time() - self.raw_at, 1) if self.raw else None,
                "current": self.current,
                "task": raw.get("task"), "reflex": raw.get("reflex"), "manual": raw.get("manual"),
                "action": raw.get("action"),
                "err": raw.get("err"), "kills": raw.get("kills"), "speed": raw.get("speed"),
                "health": raw.get("health"), "stats": raw.get("stats"), "moodles": raw.get("moodles"),
                "asleep": raw.get("asleep"), "home": situ.percept["home"] if situ else None,
                "weight": f"{raw.get('weight', 0):.1f}/{raw.get('maxWeight', 0):.0f}" if raw else None,
                "time": situ.percept["time"] if situ else None, "where": situ.percept["where"] if situ else None,
                "weapon": situ.percept["weapon"] if situ else None,
                "zombies": {"within10": sum(1 for z in zs if z["d"] <= 10), "within40": len(zs),
                            "chasing": sum(1 for z in zs if z.get("chasing")),
                            "nearest": min((z["d"] for z in zs), default=None)},
                "groups": situ.percept["zombies"] if situ else [],
                "legal": situ.legal if situ else [],
                "scores": sorted(plan.scores.items(), key=lambda kv: -kv[1]) if plan else [],
                "who": (raw.get("who") or {}).get("name"),
                "decisions": list(self.decisions)[-20:],
                "recent": list(self.mem.recent),
            }

    def serve(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                host = (self.headers.get("Host") or "").split(":")[0]
                if host not in ("127.0.0.1", "localhost"):
                    self.send_error(403)   # blocks DNS-rebinding pages from reading it
                    return
                if self.path in ("/", "/mind"):
                    body, ctype = MIND_HTML, "text/html; charset=utf-8"
                elif self.path == "/api/state":
                    body, ctype = json.dumps(bridge.snapshot()).encode(), "application/json"
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

    # ------------------------------------------------------------------ main loop
    def run(self):
        while True:
            raw = self._read_percept()
            if raw is not None:
                try:
                    self.on_percept(raw)
                except Exception as e:   # one bad percept must not kill the bridge
                    print(f"[bridge] error handling percept: {e!r}", flush=True)
            time.sleep(0.25)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--lua-dir", default=str(DEFAULT_LUA_DIR))
    args = ap.parse_args()
    bridge = Bridge(args)
    threading.Thread(target=bridge.serve, daemon=True).start()
    print(f"AI-v-Z baseline bridge (rules); files in {bridge.lua_dir}; dashboard http://127.0.0.1:{args.port}/", flush=True)
    try:
        bridge.run()
    except KeyboardInterrupt:
        print("bridge stopped", flush=True)


if __name__ == "__main__":
    main()
