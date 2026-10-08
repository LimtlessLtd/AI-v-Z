# Phase 0 brain benchmark

Runs 31 hand-made percept snapshots (`snapshots.py`) through a decision-maker and scores each answer:

| Metric | Meaning |
|---|---|
| valid | Output is JSON with a `goal` from the snapshot's legal list and a non-empty `why` |
| sensible | `goal` is in the snapshot's "sensible" set |
| bad | `goal` is in the snapshot's "dangerous/wasteful" set |
| stable | Share of snapshots where every repeat picked the same goal |
| latency | Wall-clock per decision (median / p95), excluding the cold-start call |
| VRAM | `nvidia-smi` before and after load, plus Ollama's own `size_vram` |

The LLM settings match the plan: `format` is a JSON schema whose `goal` is an enum of the legal goals,
`think: false`, `keep_alive: -1`, `num_ctx 4096`, `temperature 0.3`, `num_predict 80`.

## Run

```bash
python bench/run_bench.py --model qwen3.5:4b
```

```bash
python bench/run_bench.py --model qwen3.5:4b --cpu
```

```bash
python bench/run_bench.py --model rules --repeats 1
```

Options: `--cpu` (no GPU), `--why-first` (schema puts the reason before the goal), `--long` (adds ~25 memory
lines to approach the 1.5k-token prompt budget), `--repeats N`, `--only <ids>`, `--tag <label>`.
To include the game's VRAM use, start Project Zomboid and load a save first. The runner detects
`ProjectZomboid64.exe` and labels the results `pz-open`.

Results go to `bench/results/<label>.json` (summary) and `bench/results/raw/<label>.jsonl` (every answer).
`python bench/report.py` prints the comparison tables used in `docs/BENCHMARK.md`.

## Files

| File | Purpose |
|---|---|
| `goals.py` | Strategy goal catalog, with the one-line descriptions shown to the model |
| `snapshots.py` | The 31 test situations with legal, sensible and bad goal sets |
| `prompt.py` | System prompt, percept rendering and output schema (reused by the bridge in Phase 1) |
| `rules.py` | No-LLM utility-scoring baseline |
| `run_bench.py` | Runner (Python stdlib only; talks only to Ollama on 127.0.0.1) |
| `report.py` | Builds comparison tables from the result files |

The snapshots and "sensible" sets were written by hand, and so was `rules.py`. That makes the rules
baseline's score optimistic. Real game logs from Phase 1 make a fairer test set.
