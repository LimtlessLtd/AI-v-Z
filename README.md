# AI-v-Z — an AI that teaches itself to play Project Zomboid

A neural network running entirely on your own PC learns to play **Project Zomboid singleplayer (Build 42)**
in real time while you watch. It isn't told how to survive. It sees what a player would see, can do what
a player could do, and learns from what happens. No cloud services, no language model, no multiplayer.

> **Status (2026-10-09):** Phase 3 (the game as a gym) works end to end: the mod lists what the character
> could do, the agent (`agent/`) picks, the mod does it, and every decision is logged with its reward.
> **Nothing is learning yet**: the agent picks at random, which collects experience for Phase 4. With
> the agent off, a hand-written **rules baseline** plays instead: it loots, fights, flees, gets into
> locked houses through windows, keeps a home base, sleeps, bandages wounds with torn clothes and opens
> cans. That baseline is the score the self-taught agent has to beat. The earlier Qwen language model
> was removed on 2026-10-09; see [Roadmap](#roadmap).

## Roadmap

| Phase | What | Status |
|---|---|---|
| 0. Specs and benchmark | Hardware, model benchmarks | Done ([docs/SPECS.md](docs/SPECS.md); the Qwen benchmark is kept for the record in [docs/BENCHMARK.md](docs/BENCHMARK.md)) |
| 1. First watchable run | Mod, bridge, HUD, dashboard | Done |
| 2. Survival | Home base, nights, sleep, windows, loads, bandages, cans | Done: the rules baseline |
| **3. The game as a gym** | The mod lists what a player could do right now (like the right-click menus), describes what a player would see (container contents once opened), carries out the chosen option with the existing motor skills, and starts a new character after a death. Keeps the game speed you pick. | In progress: works with a random agent; option executors still being checked |
| 4. Learning | A small network scores every option; rewards come from the body (hunger, thirst, pain, panic, bleeding), progress (places, items, kills, time alive) and death. It trains on the CPU while the game runs. A Learning page on the dashboard. | |
| 5. Unattended weeks | Watchdog, crash recovery, weekly progress report, comparison with the rules baseline | |
| 6. Watchability | HUD shows what it's weighing; replays of its best lives | |

Decisions so far: it learns from natural play only (no staged practice situations), and only from its own
experience (it never watches a human play).

## Tested against

| | |
|---|---|
| Project Zomboid | **42.21** (Steam build `25485521`, git rev `4a0e9546ec`), singleplayer |
| Baseline brain | Rules ([brain/rules.py](brain/rules.py)), Python 3.14 standard library |
| Learning (Phase 4) | PyTorch 2.13 (CPU), already installed |
| OS / hardware | Windows 11, i9-10900K, 32 GB RAM, RTX 2060 6 GB (see [docs/SPECS.md](docs/SPECS.md)) |

PZ mods break between builds. If Steam updates the game, re-check the version on the main menu, test
again, and update this table.

## How the baseline works

| Layer | Where | Speed | Job |
|---|---|---|---|
| Reflex | Lua mod, every 4 ticks | <1 ms | Zombies within ~3 tiles: swing, shove, grab a weapon from the bag, break away from 3+. Leaves a running flee alone |
| Tactics | Lua mod, every 10 ticks | per tick | Carries out the current goal: pathfind (through a window if the doors are locked), loot containers, eat, drink at sinks, bandage, fight, flee, close doors, windows and curtains, go home, sleep, drop junk |
| Strategy | Python bridge | on events, at least every 6 s | Rules score the goals possible right now; the best one is sent to the game. The running goal is kept unless something scores clearly higher |

Goals: `fight`, `flee`, `hide`, `secure_building`, `loot_here`, `loot_building`, `explore`, `eat`,
`drink`, `bandage`, `equip_weapon`, `rest`, `wait`, `retreat_home`, `sleep`, `drop_weight`. Only the goals
that are possible right now are offered.

| | What the baseline does |
|---|---|
| Home base | The first house with a bed it searches, closes up or sleeps in becomes home (kept in the save). If it shelters for the night more than 120 tiles from home, that shelter becomes the new home. |
| Nights | From an hour before sunset it heads home, or into the nearest building if home is far, closes the doors, windows and curtains, and stays in. It sleeps in the nearest bed when tired; the game won't allow sleep with zombies in sight, panic or bad pain. |
| Locked houses | No route in: it walks round to the cheapest ground-floor window, opens it, or smashes it and clears the glass if it's locked, climbs in and shuts it behind. Smashing is loud and the last resort. |
| Loads | It carries up to 8 foods it can eat as is (none over 1 kg), 2 drinks, 6 medical items and two weapons, and swaps to a bigger backpack. With the bag 85% full it drops junk; at home it stores spare food in a cupboard and eats from there later. |
| Wounds | Bleeding with no bandage: it tears a spare shirt into rags, or takes off the one it's wearing and tears that. |
| Cans | Opened and eaten with a can opener or a sharp knife. |
| Fights | It fights at most 3 zombies with a decent weapon (counting every zombie within 4 tiles, seen or not), one bare-handed, and otherwise runs; once running it doesn't turn back to fight for 8 s. It doesn't loot buildings with 3+ zombies round them. |

The mod talks to the bridge and to the agent through files in `%USERPROFILE%\Zomboid\Lua\aivz\`, because
PZ Lua mods can't open sockets:

| File | Written by | Contents |
|---|---|---|
| `percept.json` | mod, ~2×/s (baseline) | What the character perceives: needs, wounds, inventory, zombies, nearby water and buildings, task status |
| `intent.txt` | bridge | `seq\|goal\|a1\|a2\|a3\|say\|why\|source` |
| `gym.txt` | agent, every second | Heartbeat `on\|n`. While it keeps changing, the agent plays instead of the baseline |
| `obs.json` | mod, at each decision | `{id, reason, obs, options, last, err, gym}`: what the character perceives and every option a player has right now; `{dead: true}` after a death |
| `act.txt` | agent | `id\|option\|note`: the chosen option (0-based) |
| `reload.txt` | you / `scripts\reload-mod.ps1` | Changing it hot-reloads the mod's Lua |
| `loader.txt` | mod | Loader status and the last Lua error |

## Install

Needs Python 3.10+ and Project Zomboid Build 42.

1. Link the mod into your Zomboid mods folder. This creates a junction, not a copy, so updates to this
   repo apply directly:

   ```bash
   powershell -ExecutionPolicy Bypass -File scripts/install-mod.ps1
   ```

2. In Project Zomboid: **Mods** → enable **AI-v-Z** → back to the main menu, then start a new
   singleplayer game, or **Load** a save. An existing save keeps its own mod list: tick AI-v-Z for it
   too. (With the game closed, adding the line `mod = \AIvZ,` inside `mods { }` in the save's
   `mods.txt` does the same.) The game log says `loading AIvZ` and `Lua\aivz\loader.txt` says `OK`
   when it's on.

## Run (rules baseline)

1. Start the bridge from the repo root:

   ```bash
   python bridge/bridge.py
   ```

2. Open the dashboard at <http://127.0.0.1:8799/>.
3. Load your game and take your hands off the keyboard. The character says "AI online" and starts playing.

Every decision is logged to `logs/decisions-YYYYMMDD.jsonl` (with the percept); deaths go to
`logs/deaths-YYYYMMDD.jsonl`.

## Run (self-taught agent)

Start it instead of the bridge (both use port 8799):

```bash
python -m agent.run
```

Its dashboard is at <http://127.0.0.1:8799/>. Load your game. Within a few seconds the agent takes over from the baseline; when the character dies it
starts a new one in a random town by itself. Stopping the agent (Ctrl+C) hands the character back to the
baseline within ~6 s.

What it writes, all under `logs/`:

| File | Contents |
|---|---|
| `experience/YYYYMMDD-HH.jsonl.gz` | Every decision: what it saw, the options, its choice and the reward since the last one. This is what Phase 4 learns from. |
| `lives.jsonl` | One line per life: game hours survived, kills, total reward and its parts, cause of the end |
| `agent-state.json` | The life count, so it carries on across restarts |

### Game speed

Use the game's own speed buttons (or F2 pause, F3 1×, F4 5×, F5 20×, F6 40×): fast to learn more per day,
Play (1×) to watch. The game itself drops back to 1× whenever a zombie in sight is within 4 tiles (7 with
more than 4 in sight) or the character swings. While the AI plays, the mod presses your button again once
no zombie in sight is within 8 tiles, so fights happen at 1× and the quiet stretches at your speed. It does
the same for a new character after a death. The agent gets the same rhythm of decisions per game minute
at any speed.

Measured on this PC on 2026-10-09 (a one-minute sample, time awake only; PZ runs its own fast clock
while the character sleeps): at 20× the character got through about 270 game minutes per real minute
and 176 decisions, against roughly 20–30 game minutes and 80 decisions at 1×.

## Controls (in game)

| Key | Effect |
|---|---|
| **F7** | Show/hide the AI's HUD. *(H, in the original plan, opens the Health panel in 42.21, so the HUD moved to F7.)* |
| PZ's speed buttons, F3–F6 | Game speed, as usual. While the AI plays it keeps the one you picked (see [Game speed](#game-speed)); the HUD's bottom line shows the speed, e.g. `speed 1x (20x when clear)` after the game has dropped to 1× for a close zombie. |
| W A S D, arrows, E, Space, F, R, Q | **Manual override:** the AI stops at once and you're driving. It takes over again after ~10 s with no input and no movement. While you drive, the mod doesn't touch the speed. |
| Pause (F2) | Respected: the AI never unpauses the game. |

## Security: local only

The IPC files let **any program running as you drive your character**, which is the same trust level as
your mods folder. Nothing in AI-v-Z executes code from those files. Both dashboards bind `127.0.0.1`,
reject other `Host` headers, and change nothing. Don't expose port 8799. The review of the two repos
this builds on, and what was left out for safety, is in [docs/REVIEW.md](docs/REVIEW.md).

## Development

```bash
python -m unittest discover -s tests
```

```bash
powershell -ExecutionPolicy Bypass -File scripts/reload-mod.ps1
```

`reload-mod.ps1` hot-reloads the Lua into a running game. Lua errors appear in
`%USERPROFILE%\Zomboid\console.txt` and `Zomboid\Lua\aivz\loader.txt`. The tests include the 31
hand-made situations from the Phase 0 benchmark ([tests/snapshots.py](tests/snapshots.py)); the rules must
pick a sensible goal in all of them.

## Repository layout

```
mod/AIvZ/           the Build 42 Lua mod (AIvZ.lua: reflex, tactics, HUD; AIvZGym.lua: the agent's options,
                    observations and respawns; AIvZLoader.lua: events, hot reload)
agent/              the self-taught agent: run.py (loop, logs, dashboard), link.py (the files), reward.py,
                    lives.py, policies.py (random for now), agent.html
bridge/             bridge.py (rules baseline decision loop, dashboard server) and mind.html
brain/              baseline decision code: goals, rules, percept conversion, strategy
tests/              unit tests, and the 31 benchmark situations
scripts/            install-mod.ps1, reload-mod.ps1
docs/               SPECS, REVIEW; BENCHMARK and DECISION_MODELS (Phase 0 record, Qwen era)
```

## Known issues (agent and gym)

- **It doesn't learn yet.** The random policy dies within a few game hours most lives (15 lives in the
  first 40 minutes). That's expected until Phase 4.
- **Many options fail.** About half of walk, run, search and go-to-room choices end "no way there" or
  "couldn't reach it": the game's pathfinder gives up on targets behind walls or furniture. In short
  tests the rate went up with speed (49% at 1×, 68% at 3×), but each test was in a different place, so
  it isn't clear yet whether speed is the cause. A longer comparison is due.
- **Fast forward only helps in quiet stretches.** With zombies close the game holds 1×, and the random
  agent is near zombies a lot, so a fast setting gains less than its number suggests.
- **Restarting the agent mid-life counts that character as a new life** (the life in progress isn't
  saved across restarts).
- **Screenshots of the game freeze in borderless mode.** Windows hands back a stale frame; windowed mode
  captures fine. (This only matters when testing.)

## Known issues (rules baseline)

- **Early deaths happen.** Three Phase 2 characters died within two game days: bleeding with no bandage
  while cornered; walking into 7 zombies round a barn and flipping between fighting and fleeing. The
  fixes since (counting every close zombie, committing to a flee, avoiding crowded buildings, bandages
  from clothes) pass the unit tests but haven't had a long run in game.
- **Fleeing indoors is weak.** Flee picks a square away from the zombies and pathfinds there; inside a
  house that often goes nowhere ("stuck, can't get away"). After a failed flee it fights for 15 s
  before trying again.
- **Weapons are scarce early.** It fights bare-handed only against a single zombie and flees from more.
  It picks up melee weapons it finds while looting, but doesn't go looking for them.
- **Smashed windows stay open.** A house it smashed its way into can't be closed up (no barricading yet),
  so it isn't made home.
- **No speech bubbles.** They came from Qwen, which was removed; the HUD shows the rules' top two scores.
- Only the floor you're on is looted and closed up. Lights aren't used, raw food isn't cooked, and
  bottles aren't refilled (sinks work for the first days of a game).

## Credits & licences

AI-v-Z is MIT licensed ([LICENSE](LICENSE)). Built on [botsofcog/claude-survives-zomboid](https://github.com/botsofcog/claude-survives-zomboid) and
[whatcheers/Claude-Plays-ProjectZomboid](https://github.com/whatcheers/Claude-Plays-ProjectZomboid), both
MIT. Their notices and what was taken from each are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
