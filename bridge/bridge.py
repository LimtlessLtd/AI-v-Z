"""The AI-v-Z bridge: reads what the character perceives, picks the next goal, writes it back to the game.

    game mod --writes--> %USERPROFILE%/Zomboid/Lua/aivz/percept.json
    bridge   --writes--> %USERPROFILE%/Zomboid/Lua/aivz/intent.txt   "seq|goal|a1|a2|a3|say|why|source"
    you      --watch---> http://127.0.0.1:8799/                       live dashboard (this PC only)

Rules (brain/rules.py) decide clear cases instantly. Close calls also go to the local LLM, which may
overrule the rules; the LLM also writes the one-line reason shown in the speech bubble. Above both, the LLM
sets its own aim and plan (brain/planner.py) from a long-term memory of the places it has seen, its diary
and lessons from earlier characters (brain/memory.py); the plan's current step steers the rules.

Run from the repo root:
    python bridge/bridge.py              # rules + Qwen3.5-4B via Ollama
    python bridge/bridge.py --no-llm     # rules only, no speech bubbles

Uses the Python standard library only.
"""

import argparse
import json
import os
import queue
import sys
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brain import knowledge, planner, strategy  # noqa: E402
from brain.llm import OllamaBrain  # noqa: E402
from brain.memory import WorldMemory  # noqa: E402
from brain.percept import Memory, summarize  # noqa: E402

DEFAULT_LUA_DIR = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Zomboid" / "Lua" / "aivz"
RECHECK_S = 6      # re-plan at least this often while a goal runs
SPEAK_EVERY_S = 120  # the same goal again within this long gets no new speech line (and no LLM call)
PLAN_GAP_S = 45      # at most one planning call this often (real seconds)

DIARY_SYSTEM = """You are a survivor in Project Zomboid keeping a diary. Write today's entry: 2 or 3 short
sentences, first person, plain words. What you did, what went well or badly, what you want tomorrow.
Answer with JSON only: {"entry": "..."}."""
LESSON_SYSTEM = """A survivor in Project Zomboid has just died. From their last events, write ONE sentence of
practical advice for the next survivor, at most 25 words, starting with a verb. Answer with JSON only:
{"lesson": "..."}."""
STALE_S = 15       # no new percept for this long: the game isn't running the mod
SLOW_MS = 8000     # an LLM call this slow (or a timeout) is a strike; 2 in a row reload the model
# After a task ends, don't pick the same goal again for a while (seconds). A failed task gets a pause
# before it's retried. Securing or hiding can "finish" without having changed anything, so those rest
# too even when done. Survival goals are never held back.
COOLDOWN_FAILED_S = 60
# A flee or fight that failed ("stuck", "surrounded") gets a short pause so the alternatives get a turn;
# in game a flee that couldn't find a path was re-sent eight times in ten seconds.
COOLDOWN_FAILED_SHORT_S = {"flee": 15}
FLEE_COMMIT_S = 8    # once running, don't turn to fight for this long (it flipped every few seconds)
PLAN_BLOCKED_S = 60  # a plan target with zombies round it this long: that step fails, the planner re-plans
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


class Bridge:
    def __init__(self, args):
        self.lua_dir = Path(args.lua_dir)
        self.lua_dir.mkdir(parents=True, exist_ok=True)
        self.percept_path = self.lua_dir / "percept.json"
        self.intent_path = self.lua_dir / "intent.txt"
        self.log_dir = Path(getattr(args, "log_dir", None) or ROOT / "logs")
        self.log_dir.mkdir(exist_ok=True)
        self.state_path = self.log_dir / "bridge-state.json"
        self.llm = None if args.no_llm else OllamaBrain(args.model, args.ollama)
        self.port = args.port
        self.mem = Memory()
        self.lock = threading.RLock()
        self.seq = self._load_seq()
        self.current = None
        self.raw, self.raw_at, self.mtime = None, 0.0, 0
        self.situ, self.plan, self.signature = None, None, None
        self.jobs = queue.Queue(maxsize=1)
        self.llm_state = {"model": args.model if self.llm else None, "busy": False, "last_ms": None, "calls": 0,
                          "errors": 0, "last_error": "", "ready": False, "reloads": 0}
        self.strikes = 0
        self.decisions = deque(maxlen=40)
        self.status = "waiting for the game"
        self.dead_logged = False
        self.cooldown = {}   # goal -> time.time() until which it isn't offered
        self.said = {"goal": None, "at": 0.0, "text": ""}   # last speech bubble
        # long-term: the map, diary and lessons (per character), the AI's own plan, slow LLM jobs
        self.memory_dir = self.log_dir / "memory"
        self.world, self.agenda = None, None
        self.world_ev = 0           # last game event folded into the world memory
        self.slow = deque()         # plans, diary entries, lessons: these wait behind decisions
        self.wake = threading.Event()
        self.plan_pending, self.plan_asked_at, self.woke_up = False, 0.0, False
        self.plan_line = None       # what plan.txt says now
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
                tuple(sorted(situ.legal)), p.get("plan"))

    # ------------------------------------------------------------------ long-term memory and the plan
    def _remember(self, raw):
        """Load this character's memory (a new character after a death gets a fresh one) and fold in the percept."""
        who = raw.get("who") or {}
        if who.get("name") and (self.world is None or self.world.name != who["name"] or self.world.save_id != who.get("save")):
            if self.world:
                self.world.save(force=True)
            self.world = WorldMemory(self.memory_dir, who.get("save"), who["name"])
            self.agenda = planner.Plan.from_dict(self.world.data.get("plan"))
            self.world_ev = 0
            self._write_plan_file()
        if not self.world:
            return
        for ev in raw.get("events") or []:
            if ev.get("id", 0) > self.world_ev:
                self.world_ev = ev["id"]
                self.world.note_event(raw, ev.get("msg", ""))
        self.world.observe(raw, self.mem.unreachable)
        self.world.save()

    def _follow_plan(self, raw, situ, now):
        """Point the current plan step at the game: its goal becomes legal with the plan's target."""
        situ.percept["plan"] = planner.plan_text(self.agenda)
        if not self.agenda or not self.world:
            return None
        h = planner.hint(self.agenda, situ.args, raw, self.world.places)
        self._write_plan_file()
        if not h or self.cooldown.get(h[0], 0) > now:
            return None
        goal, args = h
        step = self.agenda.current()
        if goal == "loot_building":
            from brain.percept import CROWDED, crowd_at
            if crowd_at(raw, args[0], args[1]) >= CROWDED:
                # zombies round the target: hold off; if it stays like that, the step fails and a new plan comes
                step.blocked = getattr(step, "blocked", None) or now
                if now - step.blocked > PLAN_BLOCKED_S:
                    step.status = "failed"
                    self.mem.note(raw, f"plan step failed: {step.text()} (zombies all round it)")
                    place = self.world.places.get(step.place)
                    if place is not None:
                        place["zombies"] = (raw.get("time") or {}).get("day")
                    self._save_agenda()
                return None
            step.blocked = None
        if goal in ("loot_building", "explore") and goal not in situ.legal:
            situ.legal.append(goal)
        if goal not in situ.legal:
            return None
        situ.args[goal] = tuple(args)
        if goal == "explore":
            step = self.agenda.current()
            if step and step.where:
                situ.threat["explore_heading"] = step.where
        if goal == "loot_building":
            self.mem.target_ids[f"{args[0]},{args[1]}"] = self.agenda.current().place
        return goal

    def _maybe_plan(self, raw, situ, now):
        if not self.llm or not self.world or self.plan_pending or now - self.plan_asked_at < PLAN_GAP_S:
            return
        if situ.threat["chasing"] or not self.llm_state["ready"]:
            return   # plan when things are calm
        reason = planner.needs_new_plan(self.agenda, raw, self.woke_up)
        if not reason:
            return
        self.plan_pending, self.plan_asked_at, self.woke_up = True, now, False
        self._ask_slow({"kind": "plan", "raw": raw, "percept": dict(situ.percept), "reason": reason})

    def _maybe_diary(self, raw):
        """The night's diary entry, once per day, when the AI falls asleep."""
        if not self.llm or not self.world:
            return
        day = (raw.get("time") or {}).get("day", 1)
        if any(d.get("day") == day for d in self.world.data["diary"]):
            return
        self.world.data["diary"].append({"day": day, "text": "(writing...)"})
        self._ask_slow({"kind": "diary", "raw": raw, "day": day})

    def _on_death(self, raw):
        if not self.world:
            return
        t = raw.get("time") or {}
        p = self.situ.percept if self.situ else {}
        cur = self.current or {}
        zombies = "; ".join(f"{z['count']} at {z['dist']} tiles {z['dir']} ({z['state']})" for z in p.get("zombies", [])[:4])
        plain = (f"Day {t.get('day', 1)} {t.get('hour', 0):02d}:{t.get('min', 0):02d}: {self.world.name} died "
                 f"{p.get('where', 'somewhere')}, while doing '{cur.get('goal', '?')}'. Weapon: {p.get('weapon', '?')}. "
                 f"Zombies: {zombies or 'none seen'}. Plan: {p.get('plan') or 'none'}. Last events: "
                 + "; ".join(list(self.mem.recent)[-8:]))
        if self.llm:
            self._ask_slow({"kind": "lesson", "raw": raw, "plain": plain})
        else:
            self.world.add_lesson(plain)
        self.world.save(force=True)

    def _save_agenda(self):
        if self.world:
            self.world.data["plan"] = self.agenda.to_dict() if self.agenda else None
            self.world.save(force=True)
        self._write_plan_file()

    def _write_plan_file(self):
        """plan.txt for the mod's HUD: "aim|next step"."""
        a = self.agenda
        step = a.current() if a else None
        line = f"{clean(a.aim, 90)}|{clean(f'({a.progress()}) ' + step.text(), 90) if step else ''}" if a else ""
        if line == self.plan_line:
            return
        self.plan_line = line
        try:
            (self.lua_dir / "plan.txt").write_text(line + "\n", encoding="utf-8")
        except OSError:
            pass

    def on_percept(self, raw):
        with self.lock:
            self.raw, self.raw_at = raw, time.time()
            self.seq = max(self.seq, int(raw.get("ack") or 0))
            if raw.get("dead"):
                if not self.dead_logged:
                    self.dead_logged = True
                    self.mem.note(raw, "died")
                    self._log("deaths", {"ts": datetime.now().isoformat(timespec="seconds"), "time": raw.get("time"),
                                         "kills": raw.get("kills"), "recent": list(self.mem.recent),
                                         "last_decisions": list(self.decisions)[-20:]})
                    self._on_death(raw)
                self.status = "dead"
                return
            self.dead_logged = False
            self._remember(raw)
            self.mem.update(raw)
            if raw.get("asleep"):
                # the game runs the night; the sleep task reports when the AI wakes up
                self.status = "asleep"
                self._maybe_diary(raw)
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
                line = planner.on_task_end(self.agenda, goal, task["status"], task.get("msg", ""))
                if line:
                    self.mem.note(raw, line)
                    self._save_agenda()
                if goal == "sleep" and task["status"] == "done":
                    self.woke_up = True
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
            plan_goal = self._follow_plan(raw, situ, now)
            situ.percept["knowhow"] = knowledge.relevant(situ.percept, 3)
            self.situ = situ
            self._maybe_plan(raw, situ, now)
            if raw.get("manual"):
                self.status = "you're driving"
                return
            self.status = "playing"
            sig = self._signature(situ)
            due = cur is None or finished or sig != self.signature or now - cur["at"] > RECHECK_S
            self.signature = sig
            if not due:
                return
            plan = strategy.plan(situ.percept, situ.legal, cur["goal"] if cur else None, running,
                                 cur["source"] if cur else None, plan_goal=plan_goal)
            self.plan = plan
            if (running and cur["goal"] == "flee" and plan.goal == "fight" and "flee" in situ.legal
                    and now - cur.get("t0", now) < FLEE_COMMIT_S):
                cur["at"] = now   # committed to running
                return
            if plan.source == "keep" or (running and plan.goal == cur["goal"]):
                cur["at"] = now
                return
            changed = self._issue(plan.goal, situ.args[plan.goal], situ, plan, "rules", force=finished)
            # a re-sent goal (a "wait" that timed out, say) gets no new line: in game that made the AI repeat
            # "I'm hungry and thirsty" every 15 s
            fresh = plan.goal != self.said["goal"] or now - self.said["at"] > SPEAK_EVERY_S
            if self.llm and changed and (fresh or not plan.clear):
                self._ask("narrate" if plan.clear else "choose", situ, plan.goal, plan.candidates)

    def _issue(self, goal, args, situ, plan, source, why="", say="", force=False):
        """Send a goal to the game. Returns False when it's the goal already running (unless forced:
        a finished task's goal picked again has to be re-sent to start again)."""
        cur = self.current
        if cur and cur["goal"] == goal and list(cur["args"]) == list(args) and not say and not why and not force:
            cur["at"] = time.time()
            return False
        self.seq += 1
        self._write_intent(intent_line(self.seq, goal, args, say, why, source))
        if goal == "explore":
            self.mem.explore_dir = situ.threat["explore_heading"]
        keep_why = cur["why"] if cur and cur["goal"] == goal and not why else why
        started = cur["t0"] if cur and cur["goal"] == goal and "t0" in cur else time.time()
        self.current = {"goal": goal, "args": list(args), "seq": self.seq, "source": source, "why": keep_why,
                        "at": time.time(), "t0": started}
        scores = plan.scores if plan else {}
        top = sorted(scores.items(), key=lambda kv: -kv[1])[:5]
        entry = {"seq": self.seq, "time": situ.percept["time"], "goal": goal, "source": source, "why": why,
                 "clear": plan.clear if plan else None, "top": top}
        self.decisions.append(entry)
        self._log("decisions", {"ts": datetime.now().isoformat(timespec="seconds"), **entry, "args": list(args),
                                "legal": situ.legal, "percept": situ.percept, "llm_ms": self.llm_state["last_ms"]})
        return True

    # ------------------------------------------------------------------ LLM worker
    def _ask(self, kind, situ, goal, candidates=None):
        job = {"kind": kind, "situ": situ, "goal": goal, "seq": self.seq, "candidates": candidates or situ.legal}
        try:
            self.jobs.put_nowait(job)
        except queue.Full:
            try:
                self.jobs.get_nowait()   # drop the older question; only the newest matters
            except queue.Empty:
                pass
            self.jobs.put_nowait(job)
        self.wake.set()

    def _ask_slow(self, job):
        self.slow.append(job)
        self.wake.set()

    def _next_job(self):
        """Decisions first (they're short and time-sensitive), then plans, diary entries and lessons."""
        try:
            return self.jobs.get_nowait()
        except queue.Empty:
            return self.slow.popleft() if self.slow else None

    def llm_loop(self):
        try:
            self.llm.warm_up()
            self.llm_state["ready"] = True
        except OSError as e:
            self.llm_state.update(errors=self.llm_state["errors"] + 1, last_error=f"warm-up: {e}")
        while True:
            self.wake.wait(1.0)
            self.wake.clear()
            while (job := self._next_job()) is not None:
                self._run_job(job)
                if self.strikes >= 2:
                    self._reload_llm()

    def _run_job(self, job):
        self.llm_state["busy"] = True
        try:
            if job["kind"] == "plan":
                self._make_plan(job)
            elif job["kind"] == "diary":
                self._write_diary(job)
            elif job["kind"] == "lesson":
                self._write_lesson(job)
            else:
                self._decide(job)
        except (OSError, ValueError, KeyError, TypeError) as e:
            self.llm_state.update(errors=self.llm_state["errors"] + 1, last_error=f"{job['kind']}: {e}"[:200])
            if isinstance(e, OSError):   # timeouts and refused connections, not bad answers
                self.strikes += 1
            if job["kind"] == "plan":
                self.plan_pending = False
        finally:
            self.llm_state["busy"] = False

    def _make_plan(self, job):
        messages, labels = planner.build_messages(job["percept"], job["raw"], self.world, job["reason"], self.agenda)
        obj, ms = self.llm.structured(messages, planner.output_schema(), num_predict=450)
        self.llm_state.update(plan_ms=round(ms), plans=self.llm_state.get("plans", 0) + 1)
        with self.lock:
            self.plan_pending, self.plan_asked_at = False, time.time()
            new = planner.parse_plan(obj, job["raw"], self.world, labels, job["reason"])
            self._log("plans", {"ts": datetime.now().isoformat(timespec="seconds"), "reason": job["reason"],
                                "time": job["percept"].get("time"), "answer": obj, "ms": round(ms),
                                "accepted": new is not None, "prompt": messages[1]["content"]})
            if new is None:
                self.llm_state["last_error"] = "plan: no step I can carry out; asking again later"
                return
            self.agenda = new
            self.world.data.setdefault("aims", []).append({"day": new.made_day, "aim": new.aim})
            self.mem.note(job["raw"], f"new plan: {new.aim}")
            self._save_agenda()
            cur = self.current
            if cur and self.situ:   # say it: the new aim goes in a speech bubble
                self.said = {"goal": cur["goal"], "at": time.time(), "text": new.aim}
                self._issue(cur["goal"], cur["args"], self.situ, self.plan, cur["source"], why=new.why,
                            say=f"New plan: {new.aim}")

    def _write_diary(self, job):
        today = [f"{e['t']} {e['msg']}" for e in self.world.data.get("today", []) if e.get("day") == job["day"]]
        aim = self.agenda.aim if self.agenda else "none"
        user = (f"Day {job['day']}. Kills so far: {job['raw'].get('kills', 0)}. Your aim: {aim}.\nToday:\n"
                + "\n".join(f"- {x}" for x in today[-25:] or ["(nothing written down)"]))
        obj, _ = self.llm.structured([{"role": "system", "content": DIARY_SYSTEM}, {"role": "user", "content": user}],
                                     {"type": "object", "properties": {"entry": {"type": "string", "maxLength": 400}},
                                      "required": ["entry"]}, num_predict=200)
        with self.lock:
            for d in self.world.data["diary"]:
                if d.get("day") == job["day"]:
                    d["text"] = " ".join(str(obj.get("entry", "")).split())[:400]
            del self.world.data["diary"][:-20]
            self.world.save(force=True)

    def _write_lesson(self, job):
        obj, _ = self.llm.structured([{"role": "system", "content": LESSON_SYSTEM},
                                      {"role": "user", "content": job["plain"]}],
                                     {"type": "object", "properties": {"lesson": {"type": "string", "maxLength": 200}},
                                      "required": ["lesson"]}, num_predict=80)
        lesson = " ".join(str(obj.get("lesson", "")).split())[:200]
        t = job["raw"].get("time") or {}
        with self.lock:
            self.world.add_lesson(f"Day {t.get('day', 1)}: {lesson}" if lesson else job["plain"])

    def _decide(self, job):
        """A close call or a speech line for the goal just chosen."""
        situ = job["situ"]
        legal = [job["goal"]] if job["kind"] == "narrate" else job["candidates"]
        goal, why, ms = self.llm.choose(situ.percept, legal)
        self.llm_state.update(last_ms=round(ms), calls=self.llm_state["calls"] + 1, ready=True)
        self.strikes = self.strikes + 1 if ms > SLOW_MS else 0
        with self.lock:
            cur = self.current
            if cur is None or cur["seq"] != job["seq"]:
                return   # something newer was decided while the LLM thought: drop this answer
            if (self.raw or {}).get("asleep"):
                return   # read on waking, a late "sleep" line would put the AI back to bed
            now = time.time()
            say = why if (goal != self.said["goal"] or now - self.said["at"] > SPEAK_EVERY_S) else ""
            if say:
                self.said = {"goal": goal, "at": now, "text": say}
            if goal == cur["goal"]:
                source = cur["source"] if job["kind"] == "narrate" else "rules+AI"
                self._issue(goal, cur["args"], situ, self.plan, source, why=why, say=say)
            else:
                self._issue(goal, situ.args[goal], situ, self.plan, "AI", why=why, say=say)

    def _reload_llm(self):
        """The rules keep playing meanwhile; only the speech bubbles and close calls wait."""
        self.strikes = 0
        self.llm_state.update(ready=False, reloads=self.llm_state["reloads"] + 1)
        try:
            self.llm.reload()
            self.llm_state["ready"] = True
        except OSError as e:
            self.llm_state.update(errors=self.llm_state["errors"] + 1, last_error=f"reload: {e}"[:200])

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
                "llm": self.llm_state,
                "agenda": ({"aim": self.agenda.aim, "why": self.agenda.why, "reason": self.agenda.reason,
                            "made": f"day {self.agenda.made_day}",
                            "steps": [{"do": st.do, "where": st.where, "note": st.note, "status": st.status}
                                      for st in self.agenda.steps]} if self.agenda else None),
                "planning": self.plan_pending,
                "diary": (self.world.data.get("diary") or [])[-3:] if self.world else [],
                "lessons": self.world.lessons[-4:] if self.world else [],
                "places": len(self.world.places) if self.world else 0,
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
    ap.add_argument("--model", default="qwen3.5:4b")
    ap.add_argument("--no-llm", action="store_true", help="rules only; no speech bubbles")
    ap.add_argument("--ollama", default="http://127.0.0.1:11434")
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--lua-dir", default=str(DEFAULT_LUA_DIR))
    args = ap.parse_args()
    bridge = Bridge(args)
    threading.Thread(target=bridge.serve, daemon=True).start()
    if bridge.llm:
        threading.Thread(target=bridge.llm_loop, daemon=True).start()
    print(f"AI-v-Z bridge: brain = rules{' + ' + args.model if bridge.llm else ' only'}; "
          f"files in {bridge.lua_dir}; dashboard http://127.0.0.1:{args.port}/", flush=True)
    try:
        bridge.run()
    except KeyboardInterrupt:
        print("bridge stopped", flush=True)


if __name__ == "__main__":
    main()
