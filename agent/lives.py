"""Lives: one per character, from its first observation to its death.

A life is identified by the save and the character's name. Each finished life is appended to
logs/lives.jsonl. The count and the life in progress are kept in logs/agent-state.json after every
decision, so restarting the agent carries on with the same character instead of counting a new life.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

from . import reward

GAP_S = 30   # real seconds between two decisions above this count as time away (the agent was off)


class Life:
    def __init__(self, number, obs):
        who = obs.get("who") or {}
        self.number = number
        self.name, self.save = who.get("name"), who.get("save")
        self.born = obs.get("born", (obs.get("t") or {}).get("age", 0))
        self.age = (obs.get("t") or {}).get("age", self.born)
        self.real_s = 0.0
        self.seen_at = time.time()
        self.decisions = 0
        self.reward = 0.0
        self.parts = {}
        self.kills = obs.get("kills", 0)
        self.progress = reward.LifeProgress()
        reward.start_life(obs, self.progress)
        self.last_obs = obs
        self.last_choice = None
        self.resumed = False   # restored from agent-state.json; cleared by the first observation after it

    def hours(self):
        return round(max(0.0, self.age - self.born), 2)

    def add(self, r, parts):
        self.reward += r
        for k, v in parts.items():
            self.parts[k] = round(self.parts.get(k, 0) + v, 3)

    def tick(self):
        now = time.time()
        self.real_s += min(GAP_S, max(0.0, now - self.seen_at))
        self.seen_at = now

    def record(self, how="died"):
        return {"life": self.number, "who": self.name, "save": self.save, "ended": how,
                "born_age": self.born, "end_age": self.age, "hours": self.hours(), "kills": self.kills,
                "reward": round(self.reward, 2), "parts": self.parts, "decisions": self.decisions,
                "real_minutes": round(self.real_s / 60, 1),
                "items_seen": len(self.progress.items), "buildings": len(self.progress.buildings),
                "last_choice": self.last_choice, "finished": datetime.now().isoformat(timespec="seconds")}

    def state(self):
        return {"number": self.number, "name": self.name, "save": self.save, "born": self.born, "age": self.age,
                "real_s": round(self.real_s, 1), "decisions": self.decisions, "reward": round(self.reward, 4),
                "parts": self.parts, "kills": self.kills, "last_choice": self.last_choice,
                "items": sorted(self.progress.items), "buildings": sorted(self.progress.buildings),
                "containers": self.progress.containers, "last_obs": self.last_obs}

    @classmethod
    def restore(cls, st):
        life = cls(st["number"], st.get("last_obs") or {})
        life.name, life.save = st.get("name"), st.get("save")
        life.born, life.age = st.get("born", life.born), st.get("age", life.age)
        life.real_s = float(st.get("real_s", 0))
        life.decisions, life.reward = int(st.get("decisions", 0)), float(st.get("reward", 0))
        life.parts, life.kills, life.last_choice = dict(st.get("parts") or {}), st.get("kills", 0), st.get("last_choice")
        life.progress.items, life.progress.buildings = set(st.get("items") or []), set(st.get("buildings") or [])
        life.progress.containers = int(st.get("containers", 0))
        life.resumed = True
        return life


class Lives:
    def __init__(self, log_dir):
        self.log_dir = Path(log_dir)
        self.state_path = self.log_dir / "agent-state.json"
        self.lives_path = self.log_dir / "lives.jsonl"
        try:
            st = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st = {}
        self.count = int(st.get("lives", 0))
        self.resumed = False   # the last observation picked up a life restored from the state file
        try:
            self.current = Life.restore(st["current"]) if st.get("current") else None
        except (KeyError, TypeError, ValueError):
            self.current = None
        self.history = self._load_history()

    def _load_history(self):
        try:
            return [json.loads(line) for line in self.lives_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, ValueError):
            return []

    def save(self):
        st = {"lives": self.count, "current": self.current.state() if self.current else None}
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def _end(self, how):
        rec = self.current.record(how)
        self.history.append(rec)
        with self.lives_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.current = None
        return rec

    def observe(self, msg):
        """Fold in a decision request. Returns (life, reward, parts, new_life, finished_record).

        The first observation after a restart (life.resumed) earns nothing: the time since the last decision
        includes the agent being off, and whatever the baseline did meanwhile isn't the agent's doing."""
        obs = msg.get("obs") or {}
        who = obs.get("who") or {}
        finished = None
        cur = self.current
        self.resumed = bool(cur and cur.resumed)
        if cur:
            cur.resumed = False
        if msg.get("dead"):
            if cur is None:
                return None, 0.0, {}, False, None
            cur.tick()
            # a death right after a restart still ends the life, but isn't pinned on the last decision
            r, parts = (0.0, {}) if self.resumed else reward.step(cur.last_obs, {**obs, "dead": True}, cur.progress)
            cur.add(r, parts)
            cur.kills = obs.get("kills", cur.kills)
            cur.age = (obs.get("t") or {}).get("age", cur.age)
            rec = self._end("died")
            self.save()
            return cur, r, parts, False, rec
        if cur is not None and (who.get("name") != cur.name or who.get("save") != cur.save):
            finished = self._end("left")   # another character or save without a death we saw
            cur = None
            self.resumed = False
        if cur is None:
            self.count += 1
            self.current = cur = Life(self.count, obs)
            self.save()
            return cur, 0.0, {}, True, finished
        cur.tick()
        if self.resumed:
            reward.start_life(obs, cur.progress)   # what it got while the agent was off earns no bonus later
            r, parts = 0.0, {}
        else:
            last = msg.get("last") or {}
            searched = 1 if last.get("verb") == "search" and last.get("status") == "done" else 0
            r, parts = reward.step(cur.last_obs, obs, cur.progress, searched)
            cur.add(r, parts)
        cur.last_obs = obs
        cur.kills = obs.get("kills", cur.kills)
        cur.age = (obs.get("t") or {}).get("age", cur.age)
        return cur, r, parts, False, finished
