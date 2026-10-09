"""Lives: one per character, from its first observation to its death.

A life is identified by the save and the character's name. Each finished life is appended to
logs/lives.jsonl; the running count survives agent restarts (logs/agent-state.json).
"""

import json
import time
from datetime import datetime
from pathlib import Path

from . import reward


class Life:
    def __init__(self, number, obs):
        who = obs.get("who") or {}
        self.number = number
        self.name, self.save = who.get("name"), who.get("save")
        self.born = obs.get("born", (obs.get("t") or {}).get("age", 0))
        self.age = (obs.get("t") or {}).get("age", self.born)
        self.started = time.time()
        self.decisions = 0
        self.reward = 0.0
        self.parts = {}
        self.kills = obs.get("kills", 0)
        self.progress = reward.LifeProgress()
        reward.start_life(obs, self.progress)
        self.last_obs = obs
        self.last_choice = None

    def hours(self):
        return round(max(0.0, self.age - self.born), 2)

    def add(self, r, parts):
        self.reward += r
        for k, v in parts.items():
            self.parts[k] = round(self.parts.get(k, 0) + v, 3)

    def record(self, how="died"):
        return {"life": self.number, "who": self.name, "save": self.save, "ended": how,
                "born_age": self.born, "end_age": self.age, "hours": self.hours(), "kills": self.kills,
                "reward": round(self.reward, 2), "parts": self.parts, "decisions": self.decisions,
                "real_minutes": round((time.time() - self.started) / 60, 1),
                "items_seen": len(self.progress.items), "buildings": len(self.progress.buildings),
                "last_choice": self.last_choice, "finished": datetime.now().isoformat(timespec="seconds")}


class Lives:
    def __init__(self, log_dir):
        self.log_dir = Path(log_dir)
        self.state_path = self.log_dir / "agent-state.json"
        self.lives_path = self.log_dir / "lives.jsonl"
        try:
            self.count = int(json.loads(self.state_path.read_text(encoding="utf-8")).get("lives", 0))
        except (OSError, ValueError):
            self.count = 0
        self.current = None
        self.history = self._load_history()

    def _load_history(self):
        try:
            return [json.loads(line) for line in self.lives_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, ValueError):
            return []

    def _save(self):
        self.state_path.write_text(json.dumps({"lives": self.count}), encoding="utf-8")

    def _end(self, how):
        rec = self.current.record(how)
        self.history.append(rec)
        with self.lives_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.current = None
        return rec

    def observe(self, msg):
        """Fold in a decision request. Returns (life, reward, parts, new_life, finished_record)."""
        obs = msg.get("obs") or {}
        who = obs.get("who") or {}
        finished = None
        cur = self.current
        if msg.get("dead"):
            if cur is None:
                return None, 0.0, {}, False, None
            r, parts = reward.step(cur.last_obs, {**obs, "dead": True}, cur.progress)
            cur.add(r, parts)
            cur.kills = obs.get("kills", cur.kills)
            cur.age = (obs.get("t") or {}).get("age", cur.age)
            return cur, r, parts, False, self._end("died")
        if cur is not None and (who.get("name") != cur.name or who.get("save") != cur.save):
            finished = self._end("left")   # another character or save without a death we saw
            cur = None
        if cur is None:
            self.count += 1
            self._save()
            self.current = cur = Life(self.count, obs)
            return cur, 0.0, {}, True, finished
        searched = 1 if (msg.get("last") or {}).get("verb") == "search" and (msg.get("last") or {}).get("status") == "done" else 0
        r, parts = reward.step(cur.last_obs, obs, cur.progress, searched)
        cur.add(r, parts)
        cur.last_obs = obs
        cur.kills = obs.get("kills", cur.kills)
        cur.age = (obs.get("t") or {}).get("age", cur.age)
        return cur, r, parts, False, finished
