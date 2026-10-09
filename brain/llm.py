"""Talks to the local Ollama server with the benchmarked settings (see docs/BENCHMARK.md)."""

import json
import time
import urllib.request

from .prompt import build_messages, output_schema


class OllamaBrain:
    # A decision older than ~20 s is stale anyway; the bridge drops it. Waiting longer only blocks the queue.
    def __init__(self, model="qwen3.5:4b", host="http://127.0.0.1:11434", num_ctx=4096, temperature=0.3, timeout=20):
        if not host.startswith(("http://127.0.0.1", "http://localhost")):
            raise ValueError("Ollama host must be local (127.0.0.1 or localhost)")
        self.model, self.host, self.timeout = model, host, timeout
        self.options = {"num_ctx": num_ctx, "temperature": temperature, "num_predict": 80}

    def _post(self, path, payload, timeout=None):
        req = urllib.request.Request(self.host + path, json.dumps(payload).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
            return json.loads(resp.read())

    def choose(self, percept, legal, extra_memory=()):
        """Ask for one goal out of `legal` plus a short first-person reason. Returns (goal, why, ms)."""
        payload = {
            "model": self.model,
            "messages": build_messages(percept, legal, extra_memory),
            "format": output_schema(legal),
            "think": False,
            "stream": False,
            "keep_alive": -1,
            "options": self.options,
        }
        t0 = time.perf_counter()
        resp = self._post("/api/chat", payload)
        ms = (time.perf_counter() - t0) * 1000
        obj = json.loads(resp["message"]["content"])
        goal, why = obj.get("goal"), str(obj.get("why") or "").strip()
        if goal not in legal:
            raise ValueError(f"model picked {goal!r}, not one of {legal}")
        return goal, why, ms

    def warm_up(self):
        """Load the model into memory so the first in-game decision isn't a 5-15 s cold start."""
        self._post("/api/generate", {"model": self.model, "prompt": "", "keep_alive": -1}, timeout=120)

    def reload(self):
        """Unload and reload the model. In the first in-game run, Ollama 0.40.1 went from ~1.4 s per call
        to timing out on every call after ~30 min with qwen3.5:4b; a fresh load fixed it."""
        self._post("/api/generate", {"model": self.model, "prompt": "", "keep_alive": 0}, timeout=60)
        self.warm_up()
