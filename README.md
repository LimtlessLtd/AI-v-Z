# AI-v-Z — an AI that teaches itself to play Project Zomboid

A neural network running entirely on your own PC learns to play **Project Zomboid singleplayer (Build 42)**
in real time while you watch. The intended environment gives it what a player can perceive and every
normal gameplay action a player can take, so it learns from what happens. That coverage is not complete
yet. No cloud services, no language model, no multiplayer.

> **Status (2026-10-12): Phase 4, learning, is in progress.** A small network scores every option the
> game offers and the agent plays by those scores, retraining every 5 minutes from everything it has
> lived through. The reward was redone on 2026-10-12 (version 3, below), and the same day the network got
> to see where the zombies are and started looking several decisions ahead in training, so it starts over
> and play is clumsy for the first hours. The gym (Phase 3) works end to end for 27 action types, a subset
> of what a player can do; its known gaps (crafting, vehicles, repairs, hearing and more) are in the
> [backlog](docs/BACKLOG.md). With the agent off, a hand-written **rules baseline** plays instead: it
> loots, fights, flees, gets into locked houses through windows, keeps a home base, sleeps, bandages
> wounds with torn clothes and opens cans. That baseline is the score the self-taught agent has to beat.
> The earlier Qwen language model was removed on 2026-10-09.

## Roadmap

| Phase | What | Status |
|---|---|---|
| 0. Specs and benchmark | Hardware, model benchmarks | Done ([docs/SPECS.md](docs/SPECS.md); the Qwen benchmark is kept for the record in [docs/archive/BENCHMARK.md](docs/archive/BENCHMARK.md)) |
| 1. First watchable run | Mod, bridge, HUD, dashboard | Done |
| 2. Survival | Home base, nights, sleep, windows, loads, bandages, cans | Done: the rules baseline |
| **3. The game as a gym** | Expose normal player actions, including menus, specialised screens and continuous controls; provide player-visible and audible observations; execute choices and respawn after death. Keep the game speed you pick. | Closed 2026-10-11 ([PR #25](https://github.com/LimtlessLtd/AI-v-Z/pull/25)) with 27 action types working; the gaps (more actions, hearing, the last hidden-information leaks) are filled alongside Phase 4. See [verification](docs/PHASE3_VERIFICATION.md) and [coverage audit](docs/PHASE3_COVERAGE.md). |
| **4. Learning** | A small network scores every option; the reward is a big, steady gain for time alive, costs for lost health and new wounds, small bonuses for progress (places, items, kills), a death cost that outweighs everything else (charged when the Knox infection happens), and hints for health, wound care and clothing protection that can't be farmed. It trains on the CPU while the game runs. A Learning page on the dashboard. | In progress: the network plays and retrains every 5 min (see [Run (self-taught agent)](#run-self-taught-agent)). The Learning page also compares the rules baseline (hours, kills). |
| 5. Unattended weeks | Watchdog, crash recovery, weekly progress report, comparison with the rules baseline | |
| 6. Watchability | HUD shows what it's weighing; replays of its best lives | |

Decisions so far: it learns from natural play only (no staged practice situations), and only from its own
experience (it never watches a human play).

## Tested against

| | |
|---|---|
| Project Zomboid | **42.21.0** (Steam build `25485521`, git rev `4a0e9546ec`), singleplayer; rechecked against the running game and Steam manifest on 2026-10-09 |
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
| `obs.json` | mod, at each decision | `{id, reason, obs, options, last, err, gym}`: current observations and a capped subset of implemented actions; no hearing input yet; `{dead: true}` after a death |
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

## One-click start (Windows)

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start.ps1
```

Pulls the latest `main`, switching to it if another branch is checked out (skipped if you have local
changes), links the mod if needed, launches Project Zomboid through Steam and runs the self-taught agent
(`-NoPull`, `-NoGame`, `-Policy` available). If the game is already running and the pull changed the mod's
Lua, it hot-reloads the mod too. It prints the checkout's gym version; `Zomboid\Lua\aivz\loader.txt` shows
the one the game loaded (`OK v0.5.2 (gym 0.4.21)`). The agent polls for the game, so start order doesn't
matter: once a singleplayer game with AI-v-Z enabled is loaded, it takes over. Still manual: enable the
mod once per save, and load/start the save. The agent plays with the network and trains it (`-Policy random`
for the Phase 3 random player). Run it in its own window, not as a background task of an AI coding session,
which is killed when that session closes (backlog N3).

## Run (rules baseline)

1. Start the bridge from the repo root:

   ```bash
   python bridge/bridge.py
   ```

2. Open the dashboard at <http://127.0.0.1:8799/>.
3. Load your game and take your hands off the keyboard. The character starts playing (it no longer speaks).

Every decision is logged to `logs/decisions-YYYYMMDD.jsonl` (with the percept); deaths go to
`logs/deaths-YYYYMMDD.jsonl`.

## Run (self-taught agent)

Start it instead of the bridge (both use port 8799):

```bash
python -m agent.run
```

Its dashboard is at <http://127.0.0.1:8799/>. Load your game. Within a few seconds the agent takes over from the baseline; when the character dies it
starts a new one in a random town by itself, choosing its traits. Stopping the agent (Ctrl+C) hands the character back to the
baseline within ~6 s.

**How it learns.** The network (`agent/net.py`, about 0.7 M weights, PyTorch on the CPU) gives every option
on offer a score, Q: the reward it expects to follow from picking that option now. It sees what a player
sees: the moodles first, then wounds, health, the zombies in view and which way each one is, light, what it
carries and holds, the place and its open doors and windows, the time only when it wears a watch, and how its
last action went (`agent/features.py` lists every input, and what's kept out). Each option with a direction
(walk, run, enter, go to a room, attack) also says how close the nearest zombie that way is. It mostly picks
the top-rated options (`--temperature`, default 0.5) and one pick in ten at random (`--explore 0.1`), so it
keeps trying things it rates low. While an action runs, it is asked whether to carry on about every 0.6 game
minutes (1.5 s at 1×), and at once when the action ends. Every 5 minutes (`--train-every`, counted from the
start of the last round) a separate low-priority process (`python -m agent.learn`, 4 CPU threads, two to three
minutes) retrains it from all the experience so far, carrying on from the last network, and the agent switches
to the new one at its next decision. Each training target adds up the rewards of the next 5 decisions before it
relies on the network's own estimate (n-step returns), so a death teaches the decisions that led to it within a
round or two. Until the first network exists it plays at random. Character creation is learned the same way:
picking traits leads into the life they make.

**The reward** (`agent/reward.py`, version 3, the owner's rules of 2026-10-12; research and reasons in
[docs/REWARD_RESEARCH.md](docs/REWARD_RESEARCH.md)):

| | Points |
|---|---|
| Being alive | +1 per game minute |
| Dying | −1000 |
| The Knox infection (a bite always, a laceration 25%, a zombie scratch 7%) | −1000 when it happens; the death it causes 2-3 days later then costs nothing more |
| Health | −2 per point lost, +2 per point healed |
| Each body part with an open wound and no bandage | −10 when it appears, +10 when bandaged |
| Clothing protection (the protection panel, averaged over the body) | up to +100; putting clothing on pays what taking it off costs, and a hole, a patch or a worn-out garment costs its share |
| A kill; first items, buildings and containers | +10; +3, +5, +0.5 |
| Hunger, pain, panic and the other moodles | 0 |

The health, wound and protection terms count changes in the body's state, so a loop that ends where it started
(on, off, on again) earns nothing; they are hints that speed up learning, never a reason on their own. The
infection flag is hidden from the player and so from the network; only the reward reads it. Training re-scores
older experience under the current reward. It discounts the future by game time (a reward two game hours away
counts half), so a long action such as sleeping doesn't look better just because it lasts longer.

The dashboard shows each option's Q and the chance it had of being picked. The **Learning** page,
<http://127.0.0.1:8799/learning>, compares lives by who played them (random policy vs network), charts game
hours survived per life, lists the training rounds and shows which kinds of option it currently rates
highest.

`python -m agent.run --policy random` plays at random without training (Phase 3 behaviour).

What it writes, all under `logs/`:

| File | Contents |
|---|---|
| `experience/YYYYMMDD-HH.jsonl.gz` | Every decision: what it saw, the options, its choice and the reward since the last one. This is what Phase 4 learns from. |
| `lives.jsonl` | One line per life: game hours survived, kills, total reward and its parts, cause of the end |
| `lives-rules.jsonl` | The same per life played by the rules baseline (the bridge writes it, `policy: "rules"`; no reward, item or building counts, they are null) |
| `agent-state.json` | The life count and current life, saved after each decision so the same character carries on across agent restarts |
| `model/qnet.pt` | The current network; delete it (and `model/cache/`) to start learning from scratch |
| `model/history.jsonl`, `model/train.log` | One line per training round (loss, mean Q, what it rates highest); the trainer's output |
| `model/cache/` | Encoded experience per hour, so a round doesn't re-read finished hours |

If you stop and restart the agent during a life, it resumes that character's number, reward and progress.
The first observation after the restart earns no reward for the time the agent was off; later decisions
continue from there. A controlled restart in the running game kept life 16 and logged `resumed: true`
with zero reward for that first observation.

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
| **F7** | Show/hide the AI's HUD. Drag the panel anywhere; resize it from the bottom-right corner and the text steps up in size to match. Position and size are remembered in `Lua\aivz\hud.txt` (delete it to reset). Written in the cloud, not yet seen in game. *(H, in the original plan, opens the Health panel in 42.21, so the HUD moved to F7.)* |
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

To check option executors in a running singleplayer game, start the probe instead of the random agent:

```bash
python -m agent.run --policy probe
```

It deliberately tries the offered actions and writes its results under `logs/probe/` (including
`report.txt`). These scripted choices are for verification and **do not** enter the random agent's
training experience in `logs/experience/`. It uses the same port as the agent and bridge, so run one at
a time. The probe does not create practice scenarios; it uses whatever the current game offers.
The executor results are in [Phase 3 verification](docs/PHASE3_VERIFICATION.md). Broader action,
perception and hearing requirements are in [Phase 3 coverage](docs/PHASE3_COVERAGE.md). Passing the
executor probe does not establish full player action coverage. Raised-but-unfinished items are in [docs/BACKLOG.md](docs/BACKLOG.md).

```bash
powershell -ExecutionPolicy Bypass -File scripts/reload-mod.ps1
```

`reload-mod.ps1` hot-reloads the Lua into a running game. Lua errors appear in
`%USERPROFILE%\Zomboid\console.txt` and `Zomboid\Lua\aivz\loader.txt`. The tests include the 31
hand-made situations from the Phase 0 benchmark ([tests/snapshots.py](tests/snapshots.py)); the rules must
pick a sensible goal in all of them. `tests/test_lua.py` compiles the mod's Lua with the game's own compiler
(from `projectzomboid.jar`, on the game's Java runtime), so a syntax error shows up before the game loads it.
It needs `javac` and finds the game through Steam (or `PZ_DIR`); without them it skips. It catches syntax
errors only: a wrong method name still shows up only in the game, so check new game calls against the
installed game's Lua or `projectzomboid.jar` first.

## Repository layout

```
AGENTS.md           the owner's rules and how to work on the code, for people and any AI agent (CLAUDE.md
                    only imports it, so Claude sessions load it)
mod/AIvZ/           the Build 42 Lua mod (AIvZ.lua: reflex, tactics, HUD; AIvZGym.lua: the agent's options,
                    observations and respawns; AIvZLoader.lua: events, hot reload)
agent/              the self-taught agent: run.py (loop, logs, dashboard, trainer), link.py (the files), reward.py,
                    lives.py, policies.py (net, random, probe), features.py (what the network sees),
                    net.py (the network), learn.py (a training round), agent.html, learning.html
bridge/             bridge.py (rules baseline decision loop, dashboard server) and mind.html
brain/              baseline decision code: goals, rules, percept conversion, strategy
tests/              unit tests, the 31 benchmark situations, LuaCheck.java (the Lua compile check)
scripts/            start.ps1 (one-click start), install-mod.ps1, reload-mod.ps1
docs/               BACKLOG (what's open), SPECS, REVIEW; Phase 3 coverage and verification; ACTION_CATALOGUE,
                    OBSERVATION_AUDIT and GAP_LIST (audit against the installed game); REWARD_RESEARCH (reward
                    version 3); archive/ (BENCHMARK and DECISION_MODELS: the Phase 0 record, Qwen era)
```

## Known issues (agent and gym)

- **Player action coverage is incomplete.** Clothing wear/remove exists; crafting only covers some
  item recipes. Disassembly, driving, vehicle maintenance, repairs, transfers between chosen inventory
  containers and many other systems are missing. Existing per-verb caps also hide some legal choices. See
  [coverage audit](docs/PHASE3_COVERAGE.md) and the per-action [catalogue](docs/ACTION_CATALOGUE.md).
  `drink`, `engine_on` and the trait screen still differ from the game's own rules; `sleep` and `exercise`
  follow them in code, untested in game ([gap list](docs/GAP_LIST.md)).
- **There is no hearing input.** Helicopter audio, alarms, engines, horns, zombie banging and other
  audible cues do not currently reach the agent. The proposed audio path is not implemented.
- **Two hidden-information leaks remain in the gym.** The `enter` macro picks a window by its lock state,
  which a player can't see, and zombie visibility uses line of sight plus light instead of the game's own
  spotted list. The other leaks are fixed in the gym or kept out of the network's input
  ([OBSERVATION_AUDIT.md](docs/OBSERVATION_AUDIT.md), section 5).
- **Gym 0.4.21 hasn't run in the game yet.** It asks the agent at a steady rate while an action runs, and
  presses the respawn screens' buttons every 0.3 s instead of 1.5 s. Its Lua compiles with the game's own
  compiler and every method name exists in the game (`tests/test_lua.py`). Gym 0.4.10-0.4.20 (mod 0.5.2) ran
  from 2026-10-12 10:52 with no `AIvZ` errors in `console.txt`, and its observations carry `protection` and
  `knox`.
- **The reward changed on 2026-10-12 (version 3), and the network starts over.** It started over again the same
  day for the new inputs (`features.VERSION` 3: where the zombies are, the building's openings). On the experience
  so far, one training round with n-step targets rated decisions in line with what followed them (correlation
  with the actual return 0.5-0.94, by distance from the end of the life) where one-step targets reached 0.14-0.69. Under version 1 it survived
  no longer than random play (median about 1.4 game hours over 32 rounds and about 250 network lives):
  discomfort cost more per minute than being alive earned, so an early death scored better
  ([backlog](docs/BACKLOG.md) N1). The first training round after the update sets the old network aside and
  trains a new one from all the experience, re-scored (round numbers carry on). Lives that ended under an
  older reward keep their totals in `lives.jsonl`; the Learning page shows "–" for their reward and still
  compares their hours and kills. Experience from before gym 0.4.20 has no protection or infection readings:
  there, the infection is the expected chance from the zombie wounds seen.
- **Item status reaches the network only roughly.** It sees the protection panel's bite and scratch defence
  per body part, and each item's status (condition, holes, defence, ammo...) as binned, hashed tokens: on
  its own wear/take-off options, and tied to each worn garment. A full per-item layout is still open (backlog O6).
- **Traits are learned slowly.** Each life's observations list the character's traits (gym 0.4.7, as the
  character screen shows them), so the network can link them to how the life goes; but a trait's effect
  is spread over a whole life, and the discount makes that link weak.
- **The rules baseline's lives have no reward.** The bridge logs them (`lives-rules.jsonl`), so the Learning
  page compares hours and kills for rules, random and network play; reward, item kinds and buildings show "–"
  for rules (its percept isn't the gym observation). Not yet run against the real bridge.
- **Old experience is lopsided.** Before mod 0.5.1, every decision offered up to 24 exercise options (half
  of all options logged). Two hour files (2026-10-11 11h and 12h) were damaged by two agents running at once;
  training reads what's left of them.
- **Some targets remain unreachable.** The live probe after the 0.4.2 mod / 0.3.0 gym reload on 2026-10-09
  completed 122 of 128 searches and 831 of 842 room walks; the rest failed with a path or arrival reason.
  Long directional walks and runs can stop short or have no path. These failures are reported as failures
  to the agent. The probe repeatedly crossed the same rooms, so these counts are not a map-wide success
  rate.
- **Path failures go with danger, not speed.** A controlled test on 2026-10-11 (same save, alternating 1× and
  20× blocks, 1,776 decisions) found 17% of moves failing in 1× blocks against 22% in 20× blocks. Moves made
  while the game had dropped to 1× for a close zombie failed most (walk 35%, run 67%). Details in
  [verification](docs/PHASE3_VERIFICATION.md#controlled-speed-test-2026-10-11).
- **Fast forward only helps in quiet stretches.** With zombies close the game holds 1×, and the random
  agent is near zombies a lot, so a fast setting gains less than its number suggests.
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
