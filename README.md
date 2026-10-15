# AI-v-Z — an AI that teaches itself to play Project Zomboid

A neural network running entirely on your own PC learns to play **Project Zomboid singleplayer (Build 42)**
in real time while you watch. The intended environment gives it what a player can perceive and every
normal gameplay action a player can take, so it learns from what happens. That coverage is not complete
yet. No cloud services, no language model, no multiplayer.

**Watch it learn:** <https://limtlessltd.github.io/AI-v-Z/>, with its learning charts, replays of its lives and the
network itself (a snapshot the owner publishes from the PC that plays; see [Public page](#public-page)).

> **Status (2026-10-12): Phase 4, learning, is in progress.** A small network scores every option the
> game offers and the agent plays by those scores, retraining every 5 minutes from everything it has
> lived through. The reward was redone on 2026-10-12 (version 3, then version 4 that evening, below), and the same day the network got
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
| 5. Unattended weeks | Watchdog, crash recovery, weekly progress report, comparison with the rules baseline | The game watcher restarts a hung or crashed game and the mod continues the save (2026-10-13, not yet run in the game) |
| 6. Watchability | HUD shows what it's weighing; replays of its best lives | Replays of real lives are on the [public page](#public-page) (2026-10-12) |

Decisions so far: it learns from natural play only (no staged practice situations), and only from its own
experience (it never watches a human play).

## Tested against

| | |
|---|---|
| Project Zomboid | **42.21.0** (Steam build `25485521`, git rev `4a0e9546ec`), singleplayer; rechecked against the installed sources, running-game log and Steam manifest on 2026-10-13 |
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
the one the game loaded (`OK v0.5.8 (gym 0.4.86)` after reloading this update). The agent polls for the game, so start order doesn't
matter: once a singleplayer game with AI-v-Z enabled is loaded, it takes over. Still manual: enable the
mod once per save, and load/start the save. After a crash or a hang, the game watcher starts the game again and
the mod continues the save (see below). The agent plays with the network and trains it (`-Policy random`
for the Phase 3 random player). Run it in its own window, not as a background task of an AI coding session,
which is killed when that session closes (backlog N3).

It also starts `scripts\watch-game.ps1` in a minimized window ("AI-v-Z game watcher"), unless one is already
running. The watcher keeps the game going while the agent runs (backlog N16, N17):

- If the game's window stops responding for a minute, it saves three thread dumps, the native stacks of every
  thread (`scripts\native_stacks.py`) and the heap to `logs\hang-<time>-<pid>.txt`.
- If the window still hasn't responded after 5 minutes, it closes the game and starts it again through Steam.
  It does the same when the game ends without being quit, such as a crash out of memory or a hung window
  someone closed. A quit from the game's menu is left alone, and nothing restarts while the agent isn't running.
- Before starting the game again it writes the time to `Zomboid\Lua\aivz\resume.txt`. The mod then presses the
  main menu's own Continue, and goes through the new-character screens if the saved character had died.
- At most 4 restarts an hour. Each one is logged in `logs\watcher.log`.
- `-RestartMinutes 0` turns restarts off, and `-RestartMinutes`/`-MaxRestarts` change them.

The watcher also turns on the game's GC log (`logs\gc-<pid>.log`). The Java dumps and GC logs need a JDK 25's
`jcmd`: the one in `E:\Tools\zulu25...` (Azul Zulu, portable, not on PATH), or `$env:AIVZ_JCMD`. Without it, the
restarts and native stacks still work. `watch-game.ps1 -DumpNow` saves one set of dumps by hand. To stop for the
day, stop the agent (Ctrl+C) before you quit the game, or close the watcher's window.

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
starts a new one by itself, choosing its traits: in a random town from the game's spawn screen, at one of that
town's own start points (gym 0.4.33, the owner's decision of 2026-10-12: gym 0.4.24-0.4.32 picked a random room
square instead, and some lives started on a wall line or on water and never moved). Stopping the agent (Ctrl+C) hands the character back to the
baseline within ~6 s.

**How it learns.** The network (`agent/net.py`, about 0.32 M weights, PyTorch on the CPU) gives every option
on offer a score, Q: the reward it expects to follow from picking that option now. It sees what a player
sees: the moodles first, then wounds, health, the zombies in view and which way each one is, light, what it
carries and holds, the place and its open doors and windows, whether it is sneaking or running and which way each
close zombie faces, the time only when it wears a watch, and how its last action went (`agent/features.py` lists every input, and what's kept out). Each option with a direction
(walk, run, enter, go to a room, attack, and doors, windows and curtains) also says how close the nearest zombie
that way is. It mostly picks the top-rated options (`--temperature`, default 0.25 since 2026-10-12, 0.5 before, times
how far apart that decision's scores are: the median distance from the median, so one option rated far below the
rest doesn't make the others look alike) and
one pick in ten at random (`--explore 0.1`), so it keeps trying things it rates low. While an action runs, it is
asked whether to carry on about every game minute (3 s at 1×), at once when a zombie it can see comes within
4 tiles, and at once when the action ends. It answers in about 25 ms. Every 5 minutes (`--train-every`, counted from the
start of the last round) a separate low-priority process (`python -m agent.learn`, 4 CPU threads, two to three
minutes) retrains it from all the experience so far, carrying on from the last network, and the agent switches
to the new one at its next decision. Each training target adds up the rewards of the next 5 decisions before it
relies on the network's own estimate (n-step returns), so a death teaches the decisions that led to it within a
round or two. Until the first network exists it plays at random. Character creation is learned the same way:
choosing a profession, then picking traits, leads into the life they make. Professions are the game's
own list; the existing good-trait buying and bad-trait debt repayment rule stays the same.

**The reward** (`agent/reward.py`, version 4, the owner's rules of 2026-10-12; research and reasons in
[docs/REWARD_RESEARCH.md](docs/REWARD_RESEARCH.md)):

| | Points |
|---|---|
| Being alive | +1 per game minute |
| Dying | −1000 |
| The Knox infection (a bite always, a laceration 25%, a zombie scratch 7%) | −1000 when it happens; the death it causes 2-3 days later then costs nothing more |
| Health | −2 per point lost, +2 per point healed |
| Each body part with an open wound and no bandage | −10 when it appears, +10 when bandaged |
| Clothing protection (the protection panel, averaged over the body) | up to +2,000 (shoes about 35, jeans 88; +100 in version 3); putting clothing on pays what taking it off costs, and a hole, a patch or a worn-out garment costs its share |
| A melee weapon in the hands | up to +100 by its damage (a hatchet 100, a baseball bat 73, a kitchen knife 35, a pen 7; version 4); unequipping costs what equipping paid |
| A kill; first items, buildings and containers | +10; +3, +5, +0.5 |
| Hunger, pain, panic and the other moodles | 0 |

The health, wound, protection and weapon terms count changes in the body's state, so a loop that ends where it started
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
more than 4 in sight), the character swings, an exercise ends or is cut off, or a walk stops with the character
still moving. While the AI plays, the mod presses your button again once no zombie in sight is within 8 tiles
(checked 4 times a second), so fights happen at 1× and the quiet stretches at your speed; the short drops to 1×
and back while it exercises or changes course are the game's doing. It does the same for a new character after a
death. Your pick is kept in `Zomboid\Lua\aivz\speed.txt`, so a restarted game goes back to it (from mod 0.5.3;
before, the AI played on at 1× after a restart until you pressed your button again). Unpausing with F2 brings the
game back with Play lit: that is no longer taken as a pick of 1×. To pick Play after a pause, press Play or F3.
The agent gets the same rhythm of decisions per game minute at any speed.

Measured on this PC on 2026-10-09 (a one-minute sample, time awake only; PZ runs its own fast clock
while the character sleeps): at 20× the character got through about 270 game minutes per real minute
and 176 decisions, against roughly 20–30 game minutes and 80 decisions at 1×.

## Public page

<https://limtlessltd.github.io/AI-v-Z/> shows the learning from anywhere. It has three pages:

- **Learning:** the Learning page's charts, plus loss and mean Q per round and how its liking for each kind of option
  changed over the training rounds.
- **Replays:** real lives, step by step: a top-down radar of the character, its path and the zombies in sight,
  what it perceived, every option with its Q, and its pick.
- **The network:** its layout and weights, and `qnet.npz` to download (plain arrays, no pickle).

It is a snapshot, not live. The page's code is `site/` on `main`; the data comes from the PC that plays:

```bash
powershell -ExecutionPolicy Bypass -File scripts/publish-site.ps1
```

The script does three things:

1. Exports an allow-listed snapshot of `logs/` with `python -m agent.site`: the training rounds, every life's
   summary, replays of the last 10 lives, the 10 longest and the one in progress, and the network.
2. Uploads it to the `site-data` release, a pre-release that only holds this data.
3. Starts the Pages deploy (`.github/workflows/pages.yml`, using GitHub's own `checkout`, `configure-pages`,
   `upload-pages-artifact` and `deploy-pages` actions).

Every push to `main` also redeploys, but with the last uploaded data, so run the script after merging a PR when the
page should catch up. `-DryRun` builds the snapshot without uploading it. Publishing needs the GitHub CLI (`gh`)
signed in.

Left out of the export on purpose: the hearing snapshot (wall-clock times), save names, the inventory, the
protection panel, the raw stats behind the moodles and the hidden Knox flag. Experience is kept from 2026-10-09
15:00, so older lives have no replay, and a replay of a life that began earlier starts partway through.

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
reject other `Host` headers, and change nothing. Don't expose port 8799. The one thing that leaves the PC is
the [public page](#public-page)'s data: a one-way, allow-listed export that you publish yourself. The agent never
talks to the internet, and nothing is read back from the page. The review of the two repos this builds on, and
what was left out for safety, is in [docs/REVIEW.md](docs/REVIEW.md).

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
                    net.py (the network), learn.py (a training round), agent.html, learning.html,
                    site.py (the public page's export)
site/               the public page (static HTML/JS: Learning, Replays, The network); data/ is added at deploy
.github/workflows/  pages.yml: deploys site/ and the last published data to GitHub Pages
bridge/             bridge.py (rules baseline decision loop, dashboard server) and mind.html
brain/              baseline decision code: goals, rules, percept conversion, strategy
tests/              unit tests, the 31 benchmark situations, LuaCheck.java (the Lua compile check)
scripts/            start.ps1 (one-click start), install-mod.ps1, reload-mod.ps1, publish-site.ps1 (the public page),
                    watch-game.ps1 (restarts a hung or crashed game; GC logs, thread dumps), native_stacks.py
docs/               BACKLOG (what's open), SPECS, REVIEW; Phase 3 coverage and verification; ACTION_CATALOGUE,
                    OBSERVATION_AUDIT and GAP_LIST (audit against the installed game); REWARD_RESEARCH (reward
                    version 3); archive/ (BENCHMARK and DECISION_MODELS: the Phase 0 record, Qwen era)
```

## Known issues (agent and gym)

- **Gyms 0.4.47-0.4.86 raise the repo's own option caps** (backlog row 10, written in the cloud, so none of it has been
  run in the game or through `tests.test_lua`): attack, shove, doors, windows, climb, smash, clear glass, curtains,
  search, eat, drink, equip, wear, take off, drop, craft, unbandage/unstitch/unsplint, go_room and enter now offer
  up to 8 choices each, take 16, and vehicles have no cap. The game's own range and prerequisite tests are unchanged.
  More options per decision means more tokens for the network, with no change to the dense layout. Still capped:
  the 40 observed inventory items (the reward counts them; the owner decides).
- **Gym 0.4.71 adds household supplies and cooking controls.** The bot can open an oven or microwave's real
  settings window and choose its temperature, timer, On/Off button and Close. It can reuse dirty
  bandages with the installed CleanBandage recipe and carried water, connect a plumbable fixture with a pipe wrench, switch washers/dryers and
  choose a combo machine's mode. Every choice follows the installed game's menu or window; the network
  chooses when to use it. Water choices now use all currently visible fixtures in the surrounding scan,
  with the selected source retained, and tap drinking handles face masks through the game's callback.
  All 138 tests pass, including the game's Lua checks. Wash Yourself and tap drinking completed naturally
  in the 0.4.75 follow-up; the nine new controls still need natural execution checks. The new
  family loaded through the running game's fixed file list. Gym 0.4.72 removes a redundant loading attempt
  that warned when the running game had not indexed the newly added module yet.
  Gym 0.4.75 uses this build's modern CleanBandage crafting recipe (0.5 L of carried water per item);
  the older sink recipe definitions are absent from the installed scripts. Legacy One/All entries remain
  conditional on those definitions existing; normal 42.21 inventory crafting offers One.
  The trained network is preserved. An agent restart picks up the new visible cooking-window feedback.
  [Sources, behavior and remaining coverage](docs/HOUSEHOLD_ACTIONS.md).

- **Gym 0.4.69 adds washing yourself and items**: clothing, bags, weapons and washable bandages, one item or
  all of a category at a visible water source. It uses the game's water requirements, optional soap and
  getting-up prerequisite, and checks that cleaning or bandage conversion happened. All 132 tests pass,
  including the installed game's Lua checks; natural-play verification is pending. The trained network is
  preserved; the new Without Soap warning token reaches the playing agent at its next restart. Gym 0.4.70
  also checks the actual source and items when a washing choice is picked again, so another identically named
  sink or shirt is a new action. Gym 0.4.69 loaded and ran through 601 sampled decisions with no new console
  errors; no washing was offered during that window, so completion checks remain pending.
  [Conditions and remaining coverage](docs/GAP_LIST.md#10-water-washing-cooking-light).

- **Gym 0.4.66 fires guns.** Until now `attack` with a gun walked up to the zombie and shoved it. Now it shoots from
  the gun's range, through the game's own attack hook, so the shot makes its noise and needs a round ready. An empty
  or jammed gun stops the attack, and a reload can come next. Not yet seen in the game.

- **Gym 0.4.65 lets the character keep a gun working**: eject and insert magazines, load and unload rounds (in the
  gun or a magazine), rack it or clear a jam, change the fire mode, all as the inventory menu offers them. Not yet
  seen in the game.

- **Gym 0.4.64 shows the network more of what the inventory shows a player** (backlog O5): fresh, stale, rotten,
  burnt, uncooked and frozen food as its name says, the tooltip's endurance, stress and boredom changes and (when shown)
  calories; how much is left in a drainable; whether a magazine or book has been read; a bag's weight reduction. As
  tokens, so the trained network is kept. The playing agent picks them up at its next restart.

- **Gym 0.4.63: picking the running option again carries on with it.** Decisions come every game minute while an
  action runs, which at 20x is every few ticks. Until now, picking the same option again started it over: the
  character stopped, a new path was requested and the age went back to 0. So walking actions often never arrived.
  On 2026-10-13 that happened 1,801 times in two hours (`craft` 756, `climb_fence` 361, `rest` 221...), more often
  than `continue` was picked. The same option means the same verb with the same visible fields, apart from
  distance, direction and the like; a different target still starts the new one.

- **Gym 0.4.62 adds stoves and microwaves**: switching one on or off, as its menu offers it (powered, nothing in
  the way). Cooking is the rest of the player's own doing: search it, put food in, switch on, take it out. The
  temperature and timer settings open a window and are left out. Not yet seen in the game.

- **Gym 0.4.61 adds reading** (`read`: skill books, magazines, picture books), with the menu's rules: not in the
  dark, not illiterate (except pictures), not a skill book too hard or too easy. Not yet seen in the game.

- **Gym 0.4.60 adds lights**: turning a room's light on or off at its switch, and a torch (or other item that
  switches) in the hands, attached or worn, as the game's menus offer them. Not yet seen in the game.

- **Gym 0.4.59 adds taking pills** (`take_pill`: painkillers, vitamins, sleeping tablets and the like, as the
  inventory menu offers them). Not yet seen in the game.

- **Gym 0.4.57 gives the character the whole health panel.** Besides bandaging: disinfect, poultices, stitch a
  deep wound, take out glass (with tweezers or by hand) or a bullet, clean a burn, splint a fracture. Each follows
  the panel's own item tests and wound conditions, and finds supplies where the panel does (bags, and containers by
  the character). `bandage` now offers each kind of bandage the panel lists. The Lua checks pass; not yet seen in
  the game. [Conditions](docs/GAP_LIST.md#11-medical-care-beyond-bandages). A cloud run also called its change
  0.4.57 (search offered for 8 containers); gym 0.4.58 is the two together.

- **Gym 0.4.56 lets the character fill bottles at a water source** (`fill`: one container, or all of them). Until
  now it could drink only while standing at a tap, and the longest lives died of thirst. `drink_tap` now follows the
  game's own Drink menu too: only for a source in the character's building (or both outdoors) that holds a drink.
  Those menus are built in Java in 42.21; their conditions are in [GAP_LIST item 10](docs/GAP_LIST.md). The Lua
  checks pass; not yet seen in the game.

- **Gym 0.4.55 fixes the game running out of memory.** The game crashed at 04:10 on 2026-10-13 with
  `OutOfMemoryError: Java heap space` after 87,000 decisions, and had run out once before. The Disassemble check
  kept a reading for every object the character had ever been near, because the game's Lua has no weak tables;
  it now keeps only the current surroundings. In the game since 10:26 on 2026-10-13, no `AIvZ` errors. The 3 GB
  heap is still tight: 1.45 GB of it was live 9 minutes into that session, with peaks at 94%.
  [Details](docs/BACKLOG.md#out-of-memory-and-a-hang-after-a-respawn-2026-10-13).

- **Gym 0.4.74 stops keeping every dead character in memory.** The game keeps a timed-action queue per
  character and never drops one. The game's Lua has no weak tables, so each queue kept its dead character,
  with its inventory, body, sound emitter and corpse: 45 player objects in the heap after 44 deaths, and about
  5 MB more live heap per life. At about 22 lives an hour, the 3 GB heap would have run out in about 12 hours.
  Each new life now drops the dead characters' queues. Lua checks pass; not yet run in the game.
  [Details](docs/BACKLOG.md#out-of-memory-and-a-hang-after-a-respawn-2026-10-13).

- **The game can hang, and the game watcher now restarts it.** In the hangs of 12:56 and 13:04 on 2026-10-13,
  the game's update thread waited inside the FMOD sound library while FMOD Studio's own update thread kept
  using CPU. The first hang came 10 seconds after a new character arrived and lasted 4.7 minutes before the game
  carried on. The cause inside FMOD is unknown (backlog N17). The watcher saves Java and native stacks after a
  minute. After 5 minutes it closes the game and starts it again, and the mod continues the save
  ([the watcher](#one-click-start-windows)). The restart path is not yet run in the game. Until it has worked
  once, check on the game after a hang.

- **Gym 0.4.45/0.4.46 add removal of bandages, stitches and splints (G11).** `unbandage`, `unstitch` and
  `unsplint` are offered for up to 3 body parts each and queue the same timed actions as the health panel's
  remove entries ([GAP_LIST item 11](docs/GAP_LIST.md#11-medical-care-beyond-bandages)). Written without the
  game: not run in the game, and `python -m unittest tests.test_lua` still has to be run on the PC with it.

- **Gym 0.4.44 adds profession choice before traits.** It offers the game's real list and uses its
  handler to apply skills, free traits and points. The existing trait debt rule stays the same. Next
  now respects the actual disabled button and known nonnegative points, and emergency debt repair
  preserves free profession traits. All 126 tests and installed Lua checks pass. At a natural respawn
  at 21:57, the bot chose Park Ranger from 25 professions, bought a good trait, repaid its debt and
  started the matching life. Fallback cases remain unexercised. Restart the agent for the
  selected-profession state token.
  [Sources and live checklist](docs/CHARACTER_CREATION_CHECK.md).

- **Gym 0.4.43 uses the game's spotted zombies.** The old visibility guess listed a zombie absent
  from the game's spotted list in 330 of 8,520 local samples and missed one in 66. The same corrected
  list now feeds observations, attack/shove choices, directional counts and close-zombie decisions.
  All 125 tests and installed Lua checks pass. After reload, all 98 sampled decisions matched the
  game, including 77 with zombies and 391 appearances on each list. The nearby-object
  light threshold is still a guess. See [the audit](docs/BACKLOG_CHECK_2026-10-12.md).

- **Gym 0.4.42 follows the game's furniture Rest completion.** It gets up before changing seats and
  ends the command once the game's queue finishes sitting, instead of keeping it running another
  ten real seconds. It reports the ground fallback and includes visible furniture posture as a token
  after an agent restart. Installed 42.21 source audit and all 125 tests pass. After the 21:39 reload,
  two ground rests completed at 22 ticks with sitting true. On 2026-10-13 a natural furniture rest also
  completed, followed by getting up and moving away; the separate `get_up` completed too.
  [Backlog check and learning results](docs/BACKLOG_CHECK_2026-10-12.md): the first 1,396 decisions
  after the preceding getting-up fix had no immediate path failures. The newest nine reward-4 lives
  have median survival 6.25 game hours, but bandaging is still rarely chosen and the sample is small.

- **Getting up after a rest (mod 0.5.8 / gym 0.4.41):** the old `stand` option only stopped sneaking.
  Many walks after a rest worked, but one bed rest left a character seated with hundreds of immediate
  "no way there" failures. Common movement paths now wait for the game's getting-up action first, as
  the right-click menu does. A seated character also gets a separate `get_up` choice and the network
  gets a sitting token after an agent restart. The installed Lua/compiler checks and all 125 tests pass;
  after reloading, life 792 sat on the ground, chose a walk, got up and moved away at 21:22 on
  2026-10-12. Furniture-rest recovery and the separate `get_up` were verified in natural play on 2026-10-13.
  [Evidence](docs/SITTING_CHECK.md).

- **Player action coverage is incomplete.** Clothing wear/remove exists; crafting only covers some
  item recipes. Disassembly, driving, vehicle maintenance, repairs, transfers between chosen inventory
  containers and many other systems are missing. Existing per-verb caps also hide some legal choices. See
  [coverage audit](docs/PHASE3_COVERAGE.md) and the per-action [catalogue](docs/ACTION_CATALOGUE.md).
  `drink`, `engine_on` and the trait screen still differ from the game's own rules; `sleep` and `exercise`
  follow them in code, untested in game ([gap list](docs/GAP_LIST.md)).
- **Hearing is recorded but not yet heard.** Since 2026-10-13 the agent captures the game's own audio and
  nothing else (Windows process loopback, `agent/audio_loopback.py`). Each decision record keeps the last 3 s as
  levels, left/right balance and frequency bands. `--no-hearing` turns it off. Two things are still missing.
  First, the game's sound, music and ambient volumes are 0 in its options, so everything captured is silence
  (owner decision, backlog). Second, the network doesn't use the record yet: that comes after there's real audio
  to look at. Cost measured on the PC: about 7% of a core, 2.2 KB per record before compression.
- **The known hidden-information leaks are fixed.** Zombie visibility follows the game's own spotted list since
  gym 0.4.43 (it used line of sight plus light before). Mod 0.5.7 stopped the `enter` macro picking a window by its
  lock state or among windows never seen. The other leaks are fixed in the gym or kept out of the network's input
  ([OBSERVATION_AUDIT.md](docs/OBSERVATION_AUDIT.md), section 5).
- **Gym 0.4.39 is new**: `rest` on the nearest bed as the bed menu offers it (backlog G7).
- **Gym 0.4.38**: `equip` follows the inventory menu (both hands for a working two-handed weapon; one hand
  only while the right hand has no deep wound or unsplinted fracture), `drop` inside a vehicle needs the door or
  window open, and `take` and `stow` use the loot window's own transfer (backlog G7).
- **Gym 0.4.37**: `exercise` puts the equipment in the hands first and takes worn bags off, as the fitness
  screen does; a driver without the key can hotwire a car with Electricity 1 and Mechanics 2 or the Burglar trait;
  `drink` tests for bleach as the Drink menu does (backlog G2, G5, G4).
- **Gym 0.4.36**: barricading a door or window with planks (hammer, plank, 2 nails) and prying the planks
  off with a hammer, crowbar, axe or tire iron (backlog G14b), as the game's menus allow them.
- **Gym 0.4.35 (mod 0.5.6)** (hot-reloaded on 2026-10-12 evening). Picking up half or all of a pile on the
  ground, looking into a bag lying on the ground and taking from it, and dragging a corpse and letting go of it
  (backlog G8). While dragging, the game refuses every other timed action except walks. Gym 0.4.34 leaves the raw
  stats out of `obs.json` (audit L1; the network never read them).
- **Gym 0.4.33** starts each life at the game's own start points of a random town again (see Lives
  above), and adds climbing over fences, sheets and curtains on doors, and taking sheets down. The fence work ran
  in the game for 4 minutes on 2026-10-12 before it was merged: `climb_fence` was chosen 45 times, and each time
  the next decision replaced it before the climb, as happens to most attacks (backlog, "Policy spread").
  Gym 0.4.32 offers `rest` only when not in a vehicle and not already sitting (backlog G7).
- **Gym 0.4.31 (mod 0.5.5) has only just started running in the game** (hot-reloaded at 18:32 on 2026-10-12, no
  `AIvZ` errors). It fixes two ways a character stayed in one room for good. A door or window sits on the wall
  between two squares and the game keeps it on the square south or east of that wall, so one on a room's east or
  south wall belongs to the square outside; with the curtain drawn, at night or behind a closed door that square is
  out of sight and the gym listed nothing on it. In a bathroom with a locked door the character opened the window,
  drew the curtain, and never saw the window, the curtain or a way to climb out again. Now an opening counts when
  the square on the near side is in sight. And some new characters start exactly on the line of a wall, where the
  game's pathfinder finds no way anywhere: seven lives that day were stuck on the spot they started on, for up to 66
  game hours, with a door or window a few tiles away. After two paths in a row fail there, the character now walks to the
  middle of the nearest free square with the game's auto-walk. Gym 0.4.30 offers `engine_on` only when the radial
  menu would (key, keys in the ignition or a hotwire); not yet seen in the game.
- **Gym 0.4.23-0.4.29 (mod 0.5.3-0.5.4) have only just started running in the game.** Gym 0.4.29 adds
  disassembling furniture, and gym 0.4.28 makes `drink` follow the game's Drink menu (thirst, beverage or bleach,
  half and quarter portions); neither has run in the game yet. Gym 0.4.27 adds picking items up off the ground and
  searching and taking from corpses (live from 13:56 with no errors; picked up nothing yet). Gym 0.4.26 adds hanging a sheet on
  a window as a curtain and locking or unlocking a door with its key (not yet run in the game). Gym 0.4.25 adds
  sneaking and standing up, and gives the network its own stance and which way each zombie in sight faces: live from
  13:43 on 2026-10-12, the network was crouched in 21 of its first 72 decisions. Gym 0.4.24 starts a new life in a
  random building of the picked town (see Lives above): the first 4 lives after the hot reload at 13:31 started on 4
  new squares in 3 towns. Gym 0.4.23 asks at once when a zombie it can see comes within 4 tiles (gym 0.4.21-0.4.22
  left that to the steady rate, so a zombie that appeared 2 tiles away could bite before the next decision), gives
  doors, windows and curtains a direction, and keeps your speed pick across a game restart and an F2 unpause. The Lua
  compiles with the game's own compiler, and every method name exists in the game (`tests/test_lua.py`). Gym
  0.4.21-0.4.22 ran from 11:27: decisions came a game minute apart while an action ran, and a death led to the next
  life in about 11 s (18-45 s that morning). Gym 0.4.10-0.4.20 (mod 0.5.2) ran from 10:52 with no `AIvZ` errors in
  `console.txt`.
- **Reward version 4 (2026-10-12 evening) starts the network over again.** Clothing counts 20 times more and a
  weapon in the hands counts. The first training round under it sets the old network aside (round 118 and
  before) and trains a new one from all the experience, re-scored, so play is clumsy again for a few hours. The
  policy's new spread applies once the agent is restarted (`scripts/start.ps1`); until then it picks with the old one.
- **The reward changed on 2026-10-12 (version 3), and the network started over.** It started over again the same
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
