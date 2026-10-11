"""Hearing: what the character could hear, from the game's own rendered audio.

Design (docs/PHASE3_COVERAGE.md, "Hearing"): capture the PZ process's stereo output, cut it into short
overlapping windows and turn each into a few numbers: stereo level, level change, left/right balance and
energy in log-spaced frequency bands. A rolling history of windows goes into every decision record, so
replay has the same hearing evidence the agent had. Levels are absolute (dBFS), never normalised per
window, so a distant alarm stays quieter than a nearby one.

What exists: the feature maths, the rolling history with gap marking, and the decision-record snapshot.
What does NOT exist yet: a capture source. Process-loopback capture on Windows needs a library that isn't
installed, so `NullSource` reports audio as unavailable with a reason; nothing is substituted from hidden
world state (no OnWorldSound feed, no event flags). Plug a real source in by implementing `read()`.
Pure standard library; not validated against live game audio.
"""

import math
import time
from collections import deque

BANDS_HZ = (60, 120, 250, 500, 1000, 2000, 4000, 8000)   # Goertzel centres, roughly octave-spaced
FLOOR_DB = -90.0


def _db(x):
    return FLOOR_DB if x <= 1e-9 else max(FLOOR_DB, 20.0 * math.log10(x))


def _goertzel_power(samples, rate, freq):
    """Mean squared amplitude of one frequency in `samples` (Goertzel recurrence)."""
    n = len(samples)
    if n == 0 or freq >= rate / 2:
        return 0.0
    k = 2.0 * math.cos(2.0 * math.pi * freq / rate)
    s1 = s2 = 0.0
    for x in samples:
        s1, s2 = x + k * s1 - s2, s1
    power = s1 * s1 + s2 * s2 - k * s1 * s2
    return 4.0 * power / (n * n)   # amplitude^2 of a sinusoid at that frequency


def analyse(left, right, rate):
    """Features of one window of stereo samples (floats in -1..1)."""
    n = min(len(left), len(right))
    if n == 0:
        return None
    left, right = left[:n], right[:n]
    rms_l = math.sqrt(sum(x * x for x in left) / n)
    rms_r = math.sqrt(sum(x * x for x in right) / n)
    mono = [(a + b) / 2.0 for a, b in zip(left, right)]
    peak = max(max(abs(x) for x in left), max(abs(x) for x in right))
    total = rms_l + rms_r
    return {
        "db_l": round(_db(rms_l), 1), "db_r": round(_db(rms_r), 1), "peak_db": round(_db(peak), 1),
        "balance": round((rms_r - rms_l) / total, 3) if total > 1e-9 else 0.0,   # -1 left .. +1 right
        "bands_db": [round(_db(math.sqrt(_goertzel_power(mono, rate, f))), 1) for f in BANDS_HZ],
    }


class NullSource:
    """No capture available: says so, once, with the reason."""

    available = False

    def __init__(self, reason="no audio capture backend installed (process loopback capture not set up)"):
        self.reason = reason

    def read(self):
        return []


class Hearing:
    """Turns whatever the source yields into a rolling history. A source's read() returns a list of
    (monotonic_time, left_samples, right_samples, rate) windows captured since the last call."""

    def __init__(self, source=None, history=12):
        self.source = source or NullSource()
        self.windows = deque(maxlen=history)
        self.gaps = 0
        self._last_end = None

    def poll(self):
        for t, left, right, rate in self.source.read():
            f = analyse(left, right, rate)
            if f is None:
                continue
            dur = len(left) / float(rate)
            if self._last_end is not None and t - dur - self._last_end > 0.5 * dur:
                f["gap"] = True   # capture dropped audio before this window
                self.gaps += 1
            prev = self.windows[-1] if self.windows else None
            f["t"] = round(t, 3)
            f["d_db"] = round(max(f["db_l"], f["db_r"]) - max(prev["db_l"], prev["db_r"]), 1) if prev else 0.0
            self._last_end = t
            self.windows.append(f)

    def snapshot(self, decision_id=None, game_age=None, speed=None):
        """The hearing evidence for one decision record."""
        self.poll()
        base = {"decision": decision_id, "game_age": game_age, "speed": speed, "real": round(time.time(), 3)}
        if not getattr(self.source, "available", True):
            return {**base, "available": False, "reason": self.source.reason}
        return {**base, "available": True, "gaps": self.gaps, "bands_hz": list(BANDS_HZ), "windows": list(self.windows)}
