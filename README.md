# AI-v-Z — a local AI that plays Project Zomboid

An AI running entirely on your own PC plays **Project Zomboid singleplayer (Build 42)** in real time while
you watch. You see the game, an in-game HUD and speech bubbles with the AI's reasoning, and a local web
dashboard of its "mind". It uses no cloud APIs and no multiplayer.

> **Status:** Phase 1 (first watchable run) is built but **not yet verified in game**. The bridge and
> the Python side pass their tests and an offline run; the Lua mod still needs its first in-game load.
> Benchmarks: [docs/BENCHMARK.md](docs/BENCHMARK.md). Design research: [docs/DECISION_MODELS.md](docs/DECISION_MODELS.md).

## Tested against

| | |
|---|---|
| Project Zomboid | **42.21** (Steam build `25485521`, git rev `4a0e9546ec`), singleplayer |
| Ollama | 0.40.1, model store `E:\Ollama\models` |
| Brain | Rules ([brain/rules.py](brain/rules.py)) + `qwen3.5:4b` (Q4_K_M) for close calls and speech |
| OS / GPU | Windows 11, RTX 2060 6 GB (see [docs/SPECS.md](docs/SPECS.md)) |

PZ mods break between builds. If Steam updates the game, re-check the version on the main menu, test
again, and update this table.

## How it works

| Layer | Where | Speed | Job |
|---|---|---|---|
| Reflex | Lua mod, every 4 ticks | <1 ms | Zombies within ~3 tiles: swing, shove, grab a weapon from the bag, break away from 3+ |
| Tactics | Lua mod, every 10 ticks | per tick | Carries out the current goal: pathfind, loot containers, eat, drink at sinks, bandage, fight, flee, close doors |
| Strategy | Python bridge | on events, at least every 6 s | Rules score the legal goals. Clear winners act immediately; close calls also go to Qwen, which may overrule the rules. Qwen writes the one-line reason shown in the speech bubble |

Goals the AI can pick (Phase 1): `fight`, `flee`, `hide`, `secure_building`, `loot_here`, `loot_building`,
`explore`, `eat`, `drink`, `bandage`, `equip_weapon`, `rest`, `wait`. Only the goals that are possible
right now are offered.

The mod and the bridge talk through files in `%USERPROFILE%\Zomboid\Lua\aivz\`, because PZ Lua mods
can't open sockets:

| File | Written by | Contents |
|---|---|---|
| `percept.json` | mod, ~2×/s | What the character perceives: needs, wounds, inventory, zombies, nearby water and buildings, task status |
| `intent.txt` | bridge | `seq\|goal\|a1\|a2\|a3\|say\|why\|source` |
| `reload.txt` | you / `scripts\reload-mod.ps1` | Changing it hot-reloads the mod's Lua |
| `loader.txt` | mod | Loader status and the last Lua error |

## Install

Needs Python 3.10+ (stdlib only), Ollama with `qwen3.5:4b`, and Project Zomboid Build 42.

1. Link the mod into your Zomboid mods folder. This creates a junction, not a copy, so updates to this
   repo apply directly:

   ```bash
   powershell -ExecutionPolicy Bypass -File scripts/install-mod.ps1
   ```

2. In Project Zomboid: **Mods** → enable **AI-v-Z** → back to the main menu, then start a new
   singleplayer game, or **Load** a save. For an existing save, make sure AI-v-Z is ticked in that save's
   mod list.

## Run

1. Start the bridge (from the repo root). It loads the model into memory, which takes ~15 s:

   ```bash
   python bridge/bridge.py
   ```

   Use `--no-llm` for rules only, with no speech bubbles.
2. Open the dashboard at <http://127.0.0.1:8799/>.
3. Load your game and take your hands off the keyboard. The character says "AI online" and starts playing.

Every decision is logged to `logs/decisions-YYYYMMDD.jsonl` (with the percept) for later training. Deaths
go to `logs/deaths-YYYYMMDD.jsonl`.

## Controls (in game)

| Key | Effect |
|---|---|
| **F7** | Show/hide the AI's HUD. *(H, in the original plan, opens the Health panel in 42.21, so the HUD moved to F7.)* |
| **G** | Toggle auto fast-forward: 2× speed when no zombie is within 45 tiles. *(G is otherwise only the multiplayer safety toggle.)* |
| W A S D, arrows, E, Space, F, R, Q | **Manual override:** the AI stops at once and you're driving. It takes over again after ~10 s with no input and no movement. |
| Pause (speed 0) | Respected: the AI never unpauses the game. |

## Security: local only

The IPC files let **any program running as you drive your character**, which is the same trust level as
your mods folder. Nothing in AI-v-Z executes code from those files. The dashboard binds `127.0.0.1`,
rejects other `Host` headers, and changes nothing. The bridge only talks to Ollama on `127.0.0.1`. Don't
expose port 8799. The review of the two repos this builds on, and what was left out for safety, is in
[docs/REVIEW.md](docs/REVIEW.md).

## Development

```bash
python -m unittest discover -s tests
```

```bash
powershell -ExecutionPolicy Bypass -File scripts/reload-mod.ps1
```

`reload-mod.ps1` hot-reloads the Lua into a running game. Lua errors appear in
`%USERPROFILE%\Zomboid\console.txt` and `Zomboid\Lua\aivz\loader.txt`.

## Repository layout

```
mod/AIvZ/           the Build 42 Lua mod (AIvZ.lua: reflex, tactics, HUD; AIvZLoader.lua: events, hot reload)
bridge/             bridge.py (decision loop, LLM worker, dashboard server) and mind.html
brain/              shared decision code: goals, prompt, rules, percept conversion, strategy, Ollama client
bench/              Phase 0 benchmark: 31 situations, runner, report
tests/              unit tests for brain/ and the bridge
scripts/            install-mod.ps1, reload-mod.ps1
docs/               SPECS, BENCHMARK, DECISION_MODELS, REVIEW
```

## Known issues

- **Not yet run in game.** Expect the first in-game load to surface Lua API mismatches; they show up in
  `console.txt` and on the dashboard.
- Only the floor you're on is looted. Unopened cans aren't opened, so they don't count as food yet.
  Curtains aren't closed.
- There's no home base yet, so `retreat_home` and `sleep` aren't offered (Phase 2).
- On this 6 GB GPU, Windows makes room for Qwen while PZ runs by moving some graphics memory into system
  RAM. Decisions take ~1.0 s instead of 0.8 s. Watch for game stutter. See
  [docs/BENCHMARK.md](docs/BENCHMARK.md).
- Ollama's auto-updater can replace the server version without asking. Turn it off in the Ollama app if
  you want a fixed version.

## Credits & licences

Built on [botsofcog/claude-survives-zomboid](https://github.com/botsofcog/claude-survives-zomboid) and
[whatcheers/Claude-Plays-ProjectZomboid](https://github.com/whatcheers/Claude-Plays-ProjectZomboid), both
MIT. Their notices and what was taken from each are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
