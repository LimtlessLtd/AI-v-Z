"""Hearing: what the character could hear, from the game's own rendered audio.

Design (docs/PHASE3_COVERAGE.md, "Hearing"): capture the PZ process's stereo output, cut it into short
overlapping windows and turn each into a few numbers: stereo level, level change, left/right balance and
energy in log-spaced frequency bands. A rolling history of windows goes into every decision record, so
replay has the same hearing evidence the agent had. Levels are absolute (dBFS), never normalised per
window, so a distant alarm stays quieter than a nearby one.

The source is agent/audio_loopback.py (2026-10-13): Windows process-loopback capture of the game alone. When it
can't capture (no game running, not Windows) the record says audio is unavailable and why; nothing is ever
substituted from hidden world state (no OnWorldSound feed, no event flags). `NullSource` stands in for tests.
The maths takes lists (standard library) or numpy arrays (the capture's, much faster); both give the same
numbers. Not yet part of the network's input: agent/features.py doesn't read it.
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


def _analyse_np(left, right, rate, np):
    """analyse() for numpy arrays: the same numbers, the Goertzel power as the DFT at each centre frequency."""
    n = min(len(left), len(right))
    left, right = left[:n].astype(np.float64), right[:n].astype(np.float64)
    rms_l, rms_r = float(np.sqrt(np.mean(left * left))), float(np.sqrt(np.mean(right * right)))
    mono = (left + right) / 2.0
    peak = float(max(np.abs(left).max(), np.abs(right).max()))
    total = rms_l + rms_r
    idx = np.arange(n)
    bands = []
    for f in BANDS_HZ:
        if f >= rate / 2:
            bands.append(FLOOR_DB)
            continue
        x = np.dot(mono, np.exp(-2j * np.pi * f * idx / rate))
        bands.append(round(_db(math.sqrt(4.0 * abs(x) ** 2 / (n * n))), 1))
    return {
        "db_l": round(_db(rms_l), 1), "db_r": round(_db(rms_r), 1), "peak_db": round(_db(peak), 1),
        "balance": round((rms_r - rms_l) / total, 3) if total > 1e-9 else 0.0,
        "bands_db": bands,
    }


def analyse(left, right, rate):
    """Features of one window of stereo samples (floats in -1..1): lists, or numpy arrays."""
    n = min(len(left), len(right))
    if n == 0:
        return None
    if hasattr(left, "dtype"):
        import numpy as np
        return _analyse_np(left, right, rate, np)
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
