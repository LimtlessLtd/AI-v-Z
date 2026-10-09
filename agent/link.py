"""The agent's end of the file link with the mod's gym (mod/.../AIvZGym.lua).

    gym.txt   agent -> mod   heartbeat "on|n|speed|ask" every second; while it changes, the agent plays.
                             speed is the game speed asked for (1, 2 or 3); ask goes up with every new ask,
                             and the mod takes each ask once (the G key can change the speed in between)
    obs.json  mod -> agent   a decision request: {id, reason, obs, options, last, speed} (or {dead: true})
    act.txt   agent -> mod   "id|option|note": the chosen option, 0-based, and a note for the HUD

Local files only: anything that can write to %USERPROFILE%\\Zomboid\\Lua\\aivz can drive the character,
the same trust level as the mods folder. Nothing read from these files is executed.
"""

import json
import os
import threading
import time
from pathlib import Path

DEFAULT_LUA_DIR = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Zomboid" / "Lua" / "aivz"
SPEEDS = (1, 2, 3)


def _clean(text, n=80):
    return " ".join(str(text or "").replace("|", "/").split())[:n]


class GameLink:
    def __init__(self, lua_dir=DEFAULT_LUA_DIR, speed=1):
        self.dir = Path(lua_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.obs_path, self.act_path, self.beat_path = self.dir / "obs.json", self.dir / "act.txt", self.dir / "gym.txt"
        self.last_id, self.mtime = None, None
        self._beat = 0
        self._stop = threading.Event()
        self._beat_lock = threading.Lock()   # the heartbeat thread and the dashboard both beat
        self.speed = speed if speed in SPEEDS else 1
        self.ask = int(time.time())   # a fresh number per run: starting the agent always sets its speed

    # ------------------------------------------------------------------ heartbeat
    def beat(self):
        with self._beat_lock:
            self._beat += 1
            self._write(self.beat_path, f"on|{self._beat}|{self.speed}|{self.ask}")

    def ask_speed(self, speed):
        """Ask the game to run at 1x, 2x or 3x; it takes it within a second or two."""
        if speed not in SPEEDS:
            raise ValueError(f"speed must be one of {SPEEDS}")
        with self._beat_lock:
            self.speed = speed
            self.ask += 1
        self.beat()

    def start_heartbeat(self):
        def loop():
            while not self._stop.is_set():
                try:
                    self.beat()
                except OSError:
                    pass
                self._stop.wait(1.0)
        threading.Thread(target=loop, daemon=True).start()

    def stop(self):
        """Hand the character back to the rules baseline (the mod notices within ~6 s)."""
        self._stop.set()
        try:
            with self._beat_lock:
                self._write(self.beat_path, "off")
        except OSError:
            pass

    # ------------------------------------------------------------------ requests and answers
    def poll(self):
        """The next decision request, or None. The game writes obs.json without a temp file, so a read can
        catch it half-written; that read fails to parse and the next poll gets it."""
        try:
            mtime = self.obs_path.stat().st_mtime_ns
        except OSError:
            return None
        if mtime == self.mtime:
            return None
        try:
            msg = json.loads(self.obs_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        self.mtime = mtime
        if not isinstance(msg, dict) or msg.get("id") == self.last_id:
            return None
        self.last_id = msg.get("id")
        if not isinstance(msg.get("options"), list):
            msg["options"] = []
        return msg

    def wait(self, timeout=1.0, every=0.02):
        end = time.time() + timeout
        while time.time() < end:
            msg = self.poll()
            if msg is not None:
                return msg
            time.sleep(every)
        return None

    def act(self, msg_id, option, note=""):
        self._write(self.act_path, f"{int(msg_id)}|{int(option)}|{_clean(note)}")

    def _write(self, path, text):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text + "\n", encoding="utf-8")
        for _ in range(10):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:   # the game is reading it right now
                time.sleep(0.01)
