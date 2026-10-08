"""Prints markdown comparison tables from bench/results/*.json."""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from snapshots import SNAPSHOTS  # noqa: E402


def load(results_dir):
    return sorted((json.loads(p.read_text(encoding="utf-8")) for p in Path(results_dir).glob("*.json")),
                  key=lambda r: (r["model"] != "rules", r["model"], r["label"]))


def short(r):
    parts = [r["model"], r["mode"]]
    if r["why_first"]:
        parts.append("why-first")
    if r["long"]:
        parts.append("long")
    parts.append("PZ open" if r["pz_running"] else "PZ closed")
    return " · ".join(parts)


def fmt_ms(v):
    return "<1" if v is not None and v < 1 else f"{v:,.0f}"


def summary_table(results):
    rows = ["| Config | Valid JSON | Sensible | Bad | Stable | Median ms | p95 ms | Cold start ms "
            "| Prompt tok (max) | Model VRAM MiB | GPU used before → peak MiB |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        lat, v, t = r["latency_ms"], r["vram"], r["tokens"]
        gpu = (f"{v['baseline_used_mib']} → {v['peak_used_mib']}"
               if v.get("baseline_used_mib") is not None and r["model"] != "rules" else "–")
        model_vram = "–" if v.get("ollama_model_vram_mib") is None else f"{v['ollama_model_vram_mib']} / {v['ollama_model_mib']}"
        rows.append(f"| {short(r)} | {r['valid_json_rate']:.0%} | {r['sensible_rate']:.0%} | {r['bad_rate']:.0%} "
                    f"| {r['stable_rate']:.0%} | {fmt_ms(lat['median'])} | {fmt_ms(lat['p95'])} "
                    f"| {fmt_ms(lat['cold_start'])} | {t['prompt_max'] or '–'} | {model_vram} | {gpu} |")
    return "\n".join(rows)


def snapshot_table(results):
    header = "| Snapshot | Sensible | " + " | ".join(short(r) for r in results) + " |"
    rows = [header, "|---|---|" + "---|" * len(results)]
    for s in SNAPSHOTS:
        cells = []
        for r in results:
            ps = r["per_snapshot"].get(s["id"])
            if not ps:
                cells.append("–")
                continue
            picks = ", ".join(f"{g}×{n}" if n > 1 else str(g)
                              for g, n in sorted(ps["goals"].items(), key=lambda kv: -kv[1]))
            mark = "✅" if ps["sensible_rate"] == 1 else ("❌" if ps["bad_rate"] > 0 else "⚠️")
            cells.append(f"{mark} {picks}")
        rows.append(f"| `{s['id']}` | {', '.join(s['sensible'])} | " + " | ".join(cells) + " |")
    return "\n".join(rows)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    results = load(sys.argv[1] if len(sys.argv) > 1 else HERE / "results")
    print(summary_table(results))
    print()
    print(snapshot_table(results))
