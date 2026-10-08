"""Phase 0 brain benchmark: runs percept snapshots through a local Ollama model.

Usage (from the repo root):
    python bench/run_bench.py --model qwen3.5:4b
    python bench/run_bench.py --model qwen3.5:4b --cpu            # force CPU only (num_gpu 0)
    python bench/run_bench.py --model qwen3.5:4b --why-first      # schema puts "why" before "goal"
    python bench/run_bench.py --model qwen3.5:4b --long           # pad memory towards ~1.5k prompt tokens
    python bench/run_bench.py --model rules --repeats 1           # no-LLM utility baseline (bench/rules.py)

Only talks to Ollama on 127.0.0.1. Uses the Python standard library only.
"""

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from prompt import build_messages, output_schema  # noqa: E402
import rules  # noqa: E402
from snapshots import LONG_MEMORY, SNAPSHOTS  # noqa: E402

PZ_PROCESS = "ProjectZomboid64.exe"


def api(host, path, payload=None, timeout=600):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(host + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def gpu_used_mib():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        used, total = (int(x) for x in out.strip().splitlines()[0].split(","))
        return used, total
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None, None


def pz_running():
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {PZ_PROCESS}", "/NH"],
                             capture_output=True, text=True, timeout=10).stdout
        return PZ_PROCESS.lower() in out.lower()
    except OSError:
        return False


def unload_all(host):
    for m in api(host, "/api/ps").get("models", []):
        api(host, "/api/generate", {"model": m["name"], "keep_alive": 0})
    time.sleep(2)


def loaded_info(host, model):
    for m in api(host, "/api/ps").get("models", []):
        if m["name"] == model or m["model"] == model:
            return {"size_mib": round(m["size"] / 2**20), "size_vram_mib": round(m["size_vram"] / 2**20),
                    "context_length": m.get("context_length")}
    return None


def ask(host, model, snapshot, args):
    if model == "rules":
        t0 = time.perf_counter()
        goal, why = rules.decide(snapshot["percept"], snapshot["legal"])
        wall_ms = (time.perf_counter() - t0) * 1000
        return {"message": {"content": json.dumps({"goal": goal, "why": why})}}, wall_ms
    extra = LONG_MEMORY if args.long else ()
    options = {"num_ctx": args.num_ctx, "temperature": args.temperature, "num_predict": args.num_predict}
    if args.cpu:
        options["num_gpu"] = 0
    payload = {
        "model": model,
        "messages": build_messages(snapshot["percept"], snapshot["legal"], extra),
        "format": output_schema(snapshot["legal"], why_first=args.why_first),
        "think": False,
        "stream": False,
        "keep_alive": -1,
        "options": options,
    }
    t0 = time.perf_counter()
    resp = api(args.host, "/api/chat", payload)
    wall_ms = (time.perf_counter() - t0) * 1000
    return resp, wall_ms


def score(snapshot, content):
    rec = {"raw": content, "json_ok": False, "valid": False, "goal": None, "why": None,
           "sensible": False, "bad": False}
    try:
        obj = json.loads(content)
        rec["json_ok"] = isinstance(obj, dict)
    except json.JSONDecodeError:
        return rec
    if not rec["json_ok"]:
        return rec
    goal, why = obj.get("goal"), obj.get("why")
    rec["goal"], rec["why"] = goal, why
    rec["valid"] = goal in snapshot["legal"] and isinstance(why, str) and bool(why.strip())
    rec["sensible"] = goal in snapshot["sensible"]
    rec["bad"] = goal in snapshot["bad"]
    rec["why_words"] = len(why.split()) if isinstance(why, str) else None
    return rec


def pct(values, q):
    if len(values) < 2:
        return values[0] if values else None
    return statistics.quantiles(values, n=100, method="inclusive")[q - 1]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True)
    ap.add_argument("--cpu", action="store_true", help="force CPU only (options.num_gpu = 0)")
    ap.add_argument("--why-first", action="store_true", help='schema order {"why", "goal"} instead of {"goal", "why"}')
    ap.add_argument("--long", action="store_true", help="add ~25 older memory lines to every prompt")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--num-ctx", type=int, default=4096)
    ap.add_argument("--num-predict", type=int, default=80)
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--only", nargs="*", help="snapshot ids to run (default: all)")
    ap.add_argument("--tag", default="", help="extra label for the result files")
    ap.add_argument("--keep-loaded", action="store_true", help="leave the model in memory afterwards")
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--out-dir", default=str(HERE / "results"))
    args = ap.parse_args()

    use_ollama = args.model != "rules"
    if not args.host.startswith(("http://127.0.0.1", "http://localhost")):
        sys.exit("Refusing to talk to a non-local Ollama host.")

    snapshots = [s for s in SNAPSHOTS if not args.only or s["id"] in args.only]
    pz = pz_running()
    mode = "cpu" if args.cpu else "auto"
    label_parts = [args.model, mode, "why-first" if args.why_first else "goal-first",
                   "long" if args.long else "short", "pz-open" if pz else "pz-closed"]
    if args.tag:
        label_parts.append(args.tag)
    label = re.sub(r"[^A-Za-z0-9._-]+", "_", "__".join(label_parts))

    out_dir = Path(args.out_dir)
    (out_dir / "raw").mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "raw" / f"{label}.jsonl"

    print(f"[{label}] {len(snapshots)} snapshots x {args.repeats} repeats, PZ running: {pz}")
    if use_ollama:
        unload_all(args.host)
    base_used, gpu_total = gpu_used_mib()

    # Warm-up: first call loads the model; timed separately as the cold start.
    resp, cold_ms = ask(args.host, args.model, snapshots[0], args)
    after_load_used, _ = gpu_used_mib()
    loaded = loaded_info(args.host, args.model) if use_ollama else None
    print(f"  cold start {cold_ms:.0f} ms, loaded {loaded}, GPU used {base_used} -> {after_load_used} MiB")

    records, peak_used = [], after_load_used
    with raw_path.open("w", encoding="utf-8") as raw:
        for rep in range(args.repeats):
            for i, snap in enumerate(snapshots):
                resp, wall_ms = ask(args.host, args.model, snap, args)
                rec = score(snap, resp["message"]["content"])
                rec.update({
                    "snapshot": snap["id"], "rep": rep, "wall_ms": round(wall_ms, 2),
                    "load_ms": round(resp.get("load_duration", 0) / 1e6),
                    "prompt_ms": round(resp.get("prompt_eval_duration", 0) / 1e6),
                    "eval_ms": round(resp.get("eval_duration", 0) / 1e6),
                    "prompt_tokens": resp.get("prompt_eval_count"), "out_tokens": resp.get("eval_count"),
                })
                records.append(rec)
                raw.write(json.dumps(rec, ensure_ascii=False) + "\n")
                if i % 5 == 0:
                    used, _ = gpu_used_mib()
                    if used is not None and (peak_used is None or used > peak_used):
                        peak_used = used
                mark = "ok " if rec["sensible"] else ("BAD" if rec["bad"] else " - ")
                print(f"  r{rep} {snap['id']:<30} {mark} {str(rec['goal']):<16} {wall_ms:>8.1f} ms  {rec['why']}")

    walls = [r["wall_ms"] for r in records]
    by_snap = {}
    for r in records:
        by_snap.setdefault(r["snapshot"], []).append(r)
    per_snapshot = {}
    stable = 0
    for sid, recs in by_snap.items():
        goals = Counter(r["goal"] for r in recs)
        top, top_n = goals.most_common(1)[0]
        stable += top_n == len(recs)
        per_snapshot[sid] = {"goals": dict(goals), "sensible_rate": sum(r["sensible"] for r in recs) / len(recs),
                             "bad_rate": sum(r["bad"] for r in recs) / len(recs)}

    ollama_version = api(args.host, "/api/version").get("version") if use_ollama else None
    summary = {
        "label": label, "model": args.model, "mode": mode, "why_first": args.why_first, "long": args.long,
        "pz_running": pz, "when": datetime.now().isoformat(timespec="seconds"), "ollama": ollama_version,
        "settings": {"num_ctx": args.num_ctx, "temperature": args.temperature, "num_predict": args.num_predict,
                     "think": False, "keep_alive": -1, "repeats": args.repeats},
        "n": len(records),
        "valid_json_rate": sum(r["valid"] for r in records) / len(records),
        "sensible_rate": sum(r["sensible"] for r in records) / len(records),
        "bad_rate": sum(r["bad"] for r in records) / len(records),
        "stable_rate": stable / len(by_snap),
        "latency_ms": {"median": statistics.median(walls), "p95": pct(walls, 95), "max": max(walls),
                       "cold_start": round(cold_ms)},
        "tokens": {"prompt_median": statistics.median(r["prompt_tokens"] or 0 for r in records),
                   "prompt_max": max(r["prompt_tokens"] or 0 for r in records),
                   "out_median": statistics.median(r["out_tokens"] or 0 for r in records)},
        "why_words_median": statistics.median(r["why_words"] for r in records if r.get("why_words") is not None),
        "vram": {"gpu_total_mib": gpu_total, "baseline_used_mib": base_used, "after_load_used_mib": after_load_used,
                 "peak_used_mib": peak_used, "ollama_model_mib": loaded and loaded["size_mib"],
                 "ollama_model_vram_mib": loaded and loaded["size_vram_mib"]},
        "per_snapshot": per_snapshot,
    }
    (out_dir / f"{label}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if use_ollama and not args.keep_loaded:
        api(args.host, "/api/generate", {"model": args.model, "keep_alive": 0})

    lat = summary["latency_ms"]
    print(f"\n[{label}] valid {summary['valid_json_rate']:.0%}  sensible {summary['sensible_rate']:.0%}  "
          f"bad {summary['bad_rate']:.0%}  stable {summary['stable_rate']:.0%}  "
          f"median {lat['median']:.0f} ms  p95 {lat['p95']:.0f} ms  "
          f"prompt tok {summary['tokens']['prompt_max']}  VRAM model {summary['vram']['ollama_model_vram_mib']} MiB")


if __name__ == "__main__":
    main()
