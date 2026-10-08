# AI-v-Z — a local AI that plays Project Zomboid

The AI is an open-weight model running locally through Ollama. It plays **Project Zomboid singleplayer (Build 42)**
in real time while you watch. You see the game window, an in-game HUD with speech bubbles showing the AI's
reasoning, and a local web dashboard. It uses no cloud APIs and no multiplayer.

> **Status:** Step 1 (specs) is done, and the Step 2 benchmark has first results (PZ closed): see
> [docs/BENCHMARK.md](docs/BENCHMARK.md). The game mod doesn't exist yet.

## Tested against

| | |
|---|---|
| Project Zomboid | **42.21** (Steam build `25485521`, git rev `4a0e9546ec`), singleplayer |
| Ollama | 0.40.1, model store `E:\Ollama\models` |
| Brain model | `qwen3.5:4b` (Q4_K_M) is the best LLM option on this PC. Decision models `tev1:0.8b` / `tev1:4b-q4_K_M` were also tested. Whether rules, a decision model or the LLM makes the decisions is still open |
| OS / GPU | Windows 11, RTX 2060 6 GB (see [docs/SPECS.md](docs/SPECS.md)) |

PZ mods break between builds. If Steam updates the game, re-check the version on the main menu and update
this table after re-testing.

## How it works (planned)

| Layer | Where | Speed | Job |
|---|---|---|---|
| Reflex | Lua, every few ticks | <1 ms | Anything within ~3 tiles: shove, swing, back off, flee, close door |
| Tactics | Lua utility AI | per tick | Carries out the current goal: pathfind, open doors, loot containers |
| Strategy | LLM via Ollama | every ~5–10 s or on events | Picks the next goal from the currently legal list, with a one-line "why" for the speech bubble |

The Lua mod and the bridge communicate through files in `%USERPROFILE%\Zomboid\Lua\`, because PZ Lua
mods can't open sockets.

## Security: local only

The IPC files let **any local process drive your character**. The bridge and dashboard bind to `127.0.0.1`
only and must never be exposed to the network. Don't run untrusted programs that can write to
`%USERPROFILE%\Zomboid\Lua\` while the AI is active.

## Repository layout

```
docs/SPECS.md       machine specs + model-tier recommendation
docs/BENCHMARK.md   Phase 0 model benchmark results
docs/DECISION_MODELS.md  research: Jev-style open decision models vs LLMs
bench/              Phase 0 benchmark (Python stdlib only, talks to Ollama on 127.0.0.1:11434)
bench/rules.py      no-LLM utility-scoring baseline
```

## Benchmark (Phase 0)

```bash
python bench/run_bench.py --model qwen3.5:4b
```

See [bench/README.md](bench/README.md) for options (CPU-only mode, repeats, field order).

## Install / run / controls

To be written in Phase 1. Planned keys: **H** toggles the HUD, **G** toggles auto fast-forward, and any
manual movement input overrides the AI.

## Known issues

- Ollama's auto-updater can replace the server version without asking. Turn it off in the Ollama app if
  you want a fixed version.
- On a 6 GB GPU, the 4B model and PZ may not both fit in VRAM. Ollama then moves part of the model to the
  CPU, and decisions get slower. See [docs/SPECS.md](docs/SPECS.md).

## Credits & licences

Phase 1 will fork [botsofcog/claude-survives-zomboid](https://github.com/botsofcog/claude-survives-zomboid)
(MIT) and borrow from [whatcheers/Claude-Plays-ProjectZomboid](https://github.com/whatcheers/Claude-Plays-ProjectZomboid)
(MIT). Their licence notices will be kept alongside any code taken from them.
