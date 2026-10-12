# Backlog

What's open, in priority order, then the history and details behind each item. Status is honest: nothing
here is live-tested unless it says so. Phase 3 closed on 2026-10-11 (PR #25); its gaps are worked on
alongside Phase 4.

**Who** can take an item:
* **owner**: a decision only the owner makes.
* **local**: needs the running game, the logs or the installed game files, so a session on the owner's PC.
* **cloud**: code and docs from the repository alone, so the hourly cloud routine can do it too. A game call
  is allowed only if it is cited in [GAP_LIST.md](GAP_LIST.md), [ACTION_CATALOGUE.md](ACTION_CATALOGUE.md) or
  [OBSERVATION_AUDIT.md](OBSERVATION_AUDIT.md), or already used by the mod.

Lua written in the cloud then needs a local check (`python -m unittest tests.test_lua`: it compiles with the
game's own compiler and checks every method name against the game) and a run in the game.

## Open

| # | Item | Who | Next step |
|---|---|---|---|
| N14 | **The agent must be restarted** for the policy temperature of 2026-10-12 (0.25, was 0.5): the agent started at 11:49 still picks with 0.5. Then the first hours of gym 0.4.23 and mod 0.5.3 (a zombie within 4 tiles asks at once; doors, windows and curtains have a direction; the speed pick survives a game restart and an F2 unpause). | owner, then local | Ctrl+C the agent window and run `scripts/start.ps1` again (it hot-reloads the mod too). Then check: `loader.txt` says `OK reloaded v0.5.3 (gym 0.4.23)`; no `AIvZ` errors in `console.txt`; `aivz/speed.txt` appears after a speed key or click and a restarted game goes back to that speed; how often decisions have the reason "zombie close" (about 5% before gym 0.4.21); the network's top pick near zombies. Then update the README's gym entry. See [Learning speed](#learning-speed-owner-decisions-2026-10-12). |
| N2, N6 | After a few hours under reward version 3 and the changes above: does the network outlive random play (median 1.35 game hours), and does it bandage when bleeding? | local | Compare on the Learning page and in `lives.jsonl`. |
| 6.7 | Keep the rules baseline as a comparison player, or delete it. | owner | Decide; the gym uses some of its helpers. |
| O6 | A dense per-kind item layout for the network. Bumps `features.VERSION`, so the network starts over. | owner | Decide when; hashed tokens stand in until then. |
| Hearing | Capture the game's audio. Needs a capture library that isn't installed. | owner | Approve a library, then local. |
| G4, G5, G2 | `drink` follows the Drink menu (thirst, beverage, portions); `engine_on` follows the radial menu (keys, hotwire); `exercise` moves the equipment into the hands. | cloud | APIs cited in [GAP_LIST.md](GAP_LIST.md) items 2, 4 and 5. |
| G6 | The trait screen as the game shows it: `PointToSpend()`, Next only when enabled, profession choice. Keeps the owner's option B rule. | cloud | GAP_LIST item 6. |
| G7 | Verb prerequisites the menus apply (smash on open windows, clear_glass, equip, rest, drop, take, drink_tap, enter). | cloud | Listed under [Found in the 42.21 audit](#found-in-the-4221-audit-not-fixed-2026-10-11). |
| L1, L11, L12 | Leaks left in the gym: raw `stats` in `obs.json` (never read by the network), the `enter` macro's window choice by lock state, the zombie visibility proxy instead of `getSpottedList()`. | cloud, then local | OBSERVATION_AUDIT.md section 5; the visibility change needs a live comparison. |
| 6.1-6.3, 6.5 | Remove the repo's own guard rails: caps that hide choices, usefulness filters, macros, the character creation stages. | cloud, then local | [Guard rails](#guard-rails-item-6); keep the game's own prerequisites. |
| N15 | `console.txt` logged one `FileNotFoundException` for `act.txt` ("being used by another process") at 11:31 on 2026-10-12: the game read the file while the agent's `os.replace` swapped in a new answer. Harmless (the read returns nil and is retried 2 ticks later), but Java logs a stack trace. Reads are more frequent since gym 0.4.21 (steadier decisions, respawn steps every 0.3 s). | local | Count it over a long run; if it becomes frequent, retry the read in Lua only after a short wait, or have the agent write in place. |
| 1, N11 | Start a new game after 100 deaths in one save. | local | Audit the main-menu new-game flow; keep display and speed settings. |
| O4, O5 | Vehicle part status (the Mechanics window); food, literature, bag, drainable and key tooltips. | local | Audit as for O1-O3 first. |
| 5 | The game's own halo text from gym calls (e.g. "Not safe to sleep here."). `last.msg` is already kept from the network. | local | Audit which direct handler calls show text. |
| 4 | Calibrate the light threshold (0.2, guessed) and account for held torches. | local | Compare with the screen at night. |
| 2 | Random spawn buildings (gym 0.4.24): check in the live log that new lives start in varied buildings, and compare how long they live and how soon they meet a zombie with lives on the game's listed houses. | local | `lives.jsonl` and the first observation of each life; see item 2 under [From the owner](#from-the-owner-2026-10-11). |
| N3 | Restart the agent if it exits on its own (it is fine when run from `start.ps1`'s window). | owner | Optional: say if you want `start.ps1` to restart it. |
| G14 | Asked about by the owner 2026-10-12: hang a sheet on a window as a curtain (`ISAddSheetAction`), barricade, lock doors, climb fences; and disassembling furniture (G20, `ISDisassembleMenu`). None of these is an option yet. | local, then cloud | GAP_LIST items 14 and 20; the sheet is the smallest (a timed action on a window the character stands by, with a sheet in the inventory). |
| O7 | **What a player can tell about being seen** (owner's question, 2026-10-12): the network sees each zombie in sight (where, how far, closing, down, a wall between), the light on its own square and the building's open doors, windows and curtains. It doesn't see which way a zombie faces, its own stance (sneaking, running) or noise, and it can't sneak or crouch (G13). | owner, then cloud | Facing and stance are things a player sees; as hashed tokens they need no `features.VERSION` bump. Decide, then gym and features. |
| G8-G23 | Missing families: floor items and corpses, menus, water and stoves, medical care, reading, movement and stance, barricading, vehicles, crafting, repairs, appliances, farming and foraging, building, firearms, map and radio, the new-game flow. | local, then cloud | Audit each in the game files, then build; GAP_LIST items 8-23. |

## Learning speed (owner decisions, 2026-10-12)

Reviewed 2026-10-12 from `logs/experience` (44,466 decisions, 530 lives) and the reward version 3 network (round
37). The owner approved the four proposals that touch their decisions (L-A to L-D) the same day; L-E was in the
agent's own remit.

| # | What held learning back | Evidence | Change |
|---|---|---|---|
| L-A | **The network couldn't see where the zombies are.** The state had only counts by distance, and the walk and run options counted every zombie within 20 tiles in their direction: one at arm's length the same as one 19 tiles off. A player sees where each one is. | `obs.zombies` carries `dx`, `dy` for each zombie in sight; `features.py` didn't read them. | `features.VERSION` 3 adds, per compass sector, the nearest zombie's nearness and the count within 10 tiles. It adds the nearest zombie's closing, down and blocked, and the building's seen open doors, windows, curtains and smashed windows. Each option with a direction gets the nearest zombie that way and how many. Python only; the network started over (round 38 on). |
| L-B | **A death reached the decisions before it slowly.** One-step targets with a target network copied every 200 steps carry a reward back about 10 decisions a round. A life is 50-300 decisions, and the discount's half-life about 200. | Round 37's Q against the actual discounted return, by distance in decisions from the end of the life: correlation 0.15-0.47. | N-step targets, `learn.N_STEP = 5`. In a dry run on the same experience, one round with n-step targets gave correlations of 0.50-0.94. The same round with one-step targets and the new inputs gave 0.14-0.69. The decisions in between aren't corrected for the policy that made them, as in Rainbow and R2D2. |
| L-C | **Training used about 2 minutes of every 17.** A round started 15 minutes after the last one ended. | `train.log`: rounds of 95-180 s. | A round every 5 minutes from the start of the last (`--train-every 5`): about 3 times the rounds per hour, at the same priority on the same threads. |
| L-D (N7, guard rail 4) | **"hurt" asked about once a second while a wound bled**, 39% of all decisions, and cut off each flee. Life 530 changed course 80 times in its last 90 real seconds. | 17,180 of 44,466 decisions had the reason "hurt". | Gym 0.4.21: while an action runs, a decision every 90 game-time ticks (about 0.6 game minutes, 2 s at 1×) whatever happens. The reason still says what changed (hurt, zombie close, still at it). An action that ends asks at once, as before. Live from 11:27: decisions came 0.6 game minutes apart as intended, but the network kept the running option only 7% of the time (22% under the old triggers), and a walk or run takes 3-3.6 game minutes to finish (median, older experience), so nearly every one was cut short. Gym 0.4.22: every 150 ticks, about a game minute (3 s at 1×). |
| L-E (N8) | **About 23 s from a death to the next life** (median), while lives last 1-3 real minutes. | `G.respawnStep` pressed one button every 1.5 s, and each trait pick took two presses (ask, then read the answer). | Gym 0.4.21: a step every 0.3 s. The death screen's own 3 s wait and the settling after spawning stay. A second Respawn press does nothing (`CoopCharacterCreation:newPlayerMouse` returns while a creation window exists). Live: 11 s from the first death under 0.4.21 to the next life, against 18-45 s (median 34) that morning. |
| L-F | **A zombie that came into view 2 tiles away could bite before the next decision.** Gym 0.4.21-0.4.22 left "zombie close" to the steady rate (L-D), so the next decision was up to 3 s away at 1×. The network also rated walking away and walking toward a close zombie the same, and rest or exercise not much lower. | Close zombies (within 2.5 tiles, standing) close at 0.65 tiles/s at 1× (median, 4,291 samples), 1.1 for the fastest quarter: 2 tiles in 1-3 s. The agent answers a request in 25 ms (median, p90 34 ms, measured live). With a zombie within 3 tiles, 31% of walks away and 32% of walks toward it were followed by a death within 10 decisions. | The owner's decision, 2026-10-12: gym 0.4.23 asks at once when a zombie in sight comes within 4 tiles with no wall between (more of them than at the last decision), as before gym 0.4.21; "hurt" stays on the steady rate. Pausing the game while the agent decides would gain about 0.06 s a decision, so it isn't needed. Doors, windows and curtains also get a direction (dx, dy), so the network can tell which one is between it and a zombie (before, only the distance). |
| L-G | **The acting policy stayed random where the network had an opinion.** The temperature is in units of the spread of a decision's scores, and about 24 of 31 options sat within one spread of the best. | Since the 11:49 restart (2,263 network decisions): its top-rated option had a median 10% chance (mean 16%) and was picked 21% of the time. Replaying those decisions: temperature 0.35 gives the top option a mean 22% chance, 0.25 gives 30% (median 21%), 0.2 gives 36%, 0.1 gives 57%. | The owner's decision, 2026-10-12: `--temperature` 0.25 (was 0.5); 10% random picks stay. The estimate given to the owner before the decision was "about half"; the replay above says about 30%, and about half needs 0.1-0.15. |

N5, the first run of gym 0.4.10-0.4.20 and reward version 3, came out clean on 2026-10-12. `loader.txt` said
`OK v0.5.2 (gym 0.4.20)` from 10:52, and `console.txt` had no `AIvZ` errors. `obs.json` had `protection` and `knox`,
and round 37 trained a fresh network under reward version 3 without errors.

## From the owner, 2026-10-11

| # | Item | Phase | Status |
|---|---|---|---|
| 1 | After **100 deaths in the same game**, start a completely new game so the world doesn't run out of resources/houses. | 3 | Partly: the agent counts deaths per save (`world_deaths` in `logs/agent-state.json` and each `lives.jsonl` record; `Lives.new_world_due`). **Not done:** actually creating a new game through the game's own menus (needs a Lua adapter for the main-menu new-game flow; must be validated live and keep display/speed settings). |
| 2 | On death, choose the respawn location **randomly from those available**. 2026-10-12: the owner asked for random spawn areas, as lives kept starting in houses earlier lives had drawn zombies to. | 3 | **Gym 0.4.24 (not yet run in the game):** the town is picked at random on the game's spawn screen as before, and then a random ground-floor room of any building of that town (within 150 tiles of the town's listed points), with no building within 40 tiles of the last 20 deaths of this game session (`G.spawnPoint`, `G.RANDOM_SPAWN`). Why: the game's list for a character without a profession is about 10 houses per town (Muldraugh's `poor_houses`); the 7 small maps with one point each are Sandbox-only and not offered in this Apocalypse save. 576 lives started on 61 squares. Evidence on the owner's reason, from the 576 lives: a life starting where earlier lives of the same save started did **not** meet zombies sooner. 53% of first-time starts met a zombie within 4 tiles in their first 10 decisions (median 1.01 game hours lived), against 25-45% for repeat starts (1.27-2.15 hours). Fresh buildings may start harder, so compare after the change (Open item 2). |
| 3 | Let the AI **choose its traits** at character creation, so it can learn to offset weaknesses. | 3 (action) / 4 (learning) | **Option B, the owner's choice (gym 0.4.9, 2026-10-11, verified live):** it buys any number of good traits, each only if it leaves the points at -12 or above (`DEBT_LIMIT` in `AIvZGymActions.lua`), or stops buying; then, while the points are below 0, only bad traits; at 0 or above the game starts by itself. First live build: 5 good traits to -12, 3 bad traits back to 0 or above. History: gym 0.4.3-0.4.5 read the raw `pointToSpend` (starts at 0 whatever the screen shows) and stopped buying with points still on screen; gym 0.4.6's buy-until-0 rule kept bad traits on offer next to Continue once the points were back to 0, and the agent piled them up (up to 7 bad against 2 good); gym 0.4.8 had trait picking off. Each life's observations list its traits (`obs.traits`). Not covered: profession choice, appearance. **Open:** the network can only weakly link a trait to how a life went (option C in the 2026-10-11 discussion, per-trait scores from finished lives, was proposed and not chosen). |
| 4 | **Light levels:** don't present information a human couldn't see in the dark. | 3 | Started (gym 0.3.3, untested live): gym zombies on unlit squares (`getLightLevel` < 0.2, guessed) are hidden unless within 1.5 tiles, and `obs.light` reports the character's own square light. Gym 0.4.1 applies the same rule to door/window/curtain/container/tap scans and hides unvisited building interiors. Still to do: calibrate threshold in game, account for held torches/vision, audit building/container/item scans. Original note: audit what each observation reveals at night/in unlit rooms (zombie visibility currently uses `isCanSee`, which may not reflect darkness; building/container/item scans are unaudited). Decide on a light measure (square light level, torch/lamp held, indoors/outdoors) and expose it as an observation. |

| 5 | **No speech bubbles or announcements.** The character must not say or show anything the network didn't choose, and the network must not be handed explanations it couldn't know (e.g. "not safe to sleep here"). | 3 | Partly: all five `p:Say` calls in `AIvZ.lua` now go through a no-op `speak` helper (2026-10-11, untested in game). **Not done:** the game's own halo text from direct handler calls, and `last.msg` reason texts. Every source is listed in [Speech and announcements](#speech-and-announcements-item-5). |
| 6 | **Remove the repo's own guard rails**, so the network learns its own rules from repetition. | 3 | Not done. [Guard rails](#guard-rails-item-6) lists them, separated from the game's own prerequisites (which stay, because a player has them too). |
| 7 | **Item and vehicle status a player can see**: clothing condition, vehicle parts, weapons, ammo and which ammo/magazine fits which weapon. | 3 | Clothing, weapon and ammo status are in item records since gym 0.4.11, and the protection panel since 0.4.20 (not run in game); the network sees them as hashed tokens. Open: vehicles, other tooltips, a dense layout (O4-O6 in [Item and vehicle status](#item-and-vehicle-status-item-7)). |
| 8 | **Errors from the mod** in `console.txt` (session 2026-10-11 12:06-12:52). | 3 | Two mod errors, both explained; fixed in code (gym 0.4.4 and 0.4.5), **not yet run in game**: C1 (exercise, 517 times) and C2 (vehicle scan, twice) in [Console errors](#console-errors-item-8). |

## Found 2026-10-11

| Item | Status |
|---|---|
| Two agents ran at once: on Windows `ThreadingHTTPServer` sets `SO_REUSEADDR`, so a second agent bound the same port without an error, and both answered the game and appended to one experience file. `logs/experience/20261011-11` and `-12` have broken gzip streams. | Fixed: the agent and the bridge bind their port with `SO_EXCLUSIVEADDRUSE` and exit if it is taken. The training reader (`agent/features.py`, `read_records`) salvages whatever whole lines remain in damaged files. |
| The speed flipped between 1× and 3× during exercise and after sleep: the game sets 1× at the end of every exercise, and 3× when the character falls asleep, and the mod adopted the game's changes as the owner's pick. | Fixed (mod 0.5.1, hot-reloaded): only the owner's own speed changes (button or key) count. Exercise is no longer offered when the fitness screen would refuse it, and one duration per exercise is offered per decision instead of six. |
| The time was in every observation (`t.hour`), though a player sees it only on a watch or clock. | `obs.clock` (gym 0.4.6) gives the time only while a watch or alarm clock is worn or held, with the date and temperature on a digital one. The network's encoder (`agent/features.py`) uses `obs.clock` and never `t`. |

## Found in the overnight run, 2026-10-11/12

Reviewed 2026-10-12 from `logs/lives.jsonl` (lives 260-506), `logs/experience` (2026-10-11 18:00 to 2026-10-12
09:06: 24,710 decisions, 692 game hours alive), `logs/model/history.jsonl` and `train.log` (rounds 1-32), and
the game logs `Zomboid/Logs/logs_2026-10-11_18-33` and `2026-10-12_07-33_DebugLog.txt`. The game ran gym
0.4.9 (mod 0.5.1) throughout. Most important first.

| # | Item | Evidence | Status / proposal |
|---|---|---|---|
| N0 | **Reward version 3** (owner asked 2026-10-12: death far worse; reward bandaging, healing and protection; nothing to farm). Research and proposal in [REWARD_RESEARCH.md](REWARD_RESEARCH.md): infection risk charged when a zombie wound happens, health counted both ways, untreated wounds and worn protection as potential-based terms, so a put-on/take-off loop earns nothing. | Comparison with Crafter, OpenAI Five, Doom, MineRL, NetHack and DQN. Infection odds read from the 42.21 jar. **Done in code, not yet run in game:** reward version 3 and gym 0.4.20. The owner decided (2026-10-12) to keep death at −1000, and to make protection a hint that follows the protection actually worn, so wear and tear count. The infection is charged as the death it is, once, not as a hint (see REWARD_RESEARCH.md, "Decided"). The network sees the protection per body part and each garment's status. Merged in PR #46; first run is item N5. |
| N1 | **Staying alive scores worse than dying.** Discomfort costs more than being alive earns, and death costs only 20, so an early death scores better than a long uncomfortable life. The network has no reason to survive. | Overnight totals: alive +4,156; discomfort −9,225 (stress −2,397, pain −1,603, panic −1,429, tired −1,102, hungry −952, wet −839, thirst −625, hypothermia −267). Average per net life: discomfort −33.9, death −20, health −17.2, bleeding −3.6, alive +15.2, progress +0.3. Being alive earns 0.1/min, but one moodle at level 2 costs 0.08/min and one at level 3 costs 0.18/min. Every verb's average reward per decision is negative. From round 6 to round 32 the network's average score stays between −21 and −24, and the loss stays between 0.86 and 0.99 from round 10. Sleep scores between −7 and −169 from round 7: it lasts about a game hour, and 15 of 55 sleeps ended in death. Fixed in code by reward version 2 (the owner's rule of 2026-10-12: being alive pays +1 a game minute, being hurt costs, dying costs 1000, feeling bad costs nothing; training re-scores all older experience and discounts by game time, half-life 2 game hours), then replaced the same day by version 3 (N0). First run: item N5. |
| N2 | **The network doesn't survive any longer than random play.** | Median game hours per life: random 1.35 (256 lives), net 1.45 (246 lives), the net's last 46 overnight lives 0.86. Since the 07:33 restart (new world, day 2, 1×): 0.64 (26 lives). Kills: random 12, net 0. | Check again once the version 2 network has played for a while. |
| N3 | **Why it stopped overnight.** The agent ran as a background task of the Claude session "AI-v-Z learning agent" (started 2026-10-11 19:22). That task was killed at 02:13:10, about 6 hours after the session's last activity, when the session was shut down. Neither the agent nor the game failed. The game ran until 07:32 with nobody playing. Training stopped as well, because its timer runs inside the agent process. | The session transcript (`09de4825…`) ends with a "killed" task notification at 01:13:10 UTC. The task output is the start line and `[killed]`, with no errors. `train.log` has no round between 02:09 and 07:33. The last experience record is from 02:13:04. | Rule: long runs never go in a Claude background task. Today's agent runs from `scripts/start.ps1` in its own window (parent `explorer.exe`). Option: have `start.ps1` restart the agent if it exits. |
| N4 | A killed agent loses its unflushed decisions. `ExperienceLog` flushes only when a decision arrives, so the most recent ones sit in memory. | Life 481 made 47 decisions, but only 37 are in `logs/experience/20261012-02`. | Fixed 2026-10-12: the agent's loop also flushes decisions older than 30 s while no decision arrives (`ExperienceLog.flush_stale`, with a test). A kill mid-play can still lose up to 20 decisions or 30 s, by design (each flush is a gzip member). |
| N5 | **The game isn't running the overnight PRs.** The game loads the mod from the local checkout, which is at `80f2d69` (gym 0.4.9). PRs #27-#41, merged overnight (gym 0.4.10-0.4.19), are only on GitHub's `phase4-learning` and haven't run in game. `start.ps1` pulls `origin/main`, which stops at #26. | `obs.json` and `loader.txt` report gym 0.4.9 and mod 0.5.1. | Everything is on `main` now (owner's rule, 2026-10-12: no other long-lived branches), and `start.ps1` switches to `main`, pulls it, and hot-reloads the mod if the game is running. Checked 2026-10-12 without the game: every game call added since 0.4.9 exists in the 42.21 jar, and all the Lua compiles with the game's compiler (`tests/test_lua.py`). The first run is in [Open](#open). |
| N6 | **Bleeding mostly goes untreated.** | 42% of decisions (10,518 of 24,710) are made while bleeding. A bandage was on offer in 505 of those and Rip Clothing in 2,982; bandage was chosen 24 times. | Not a gym bug. Rip Clothing then bandage is a two-step chain the network hasn't found. Check again after N1. |
| N7 | "hurt" interrupts most actions. Health 0.5 below the last decision triggers a new one, at most every `DECIDE_GAP`. While a wound bleeds, health keeps falling, so walking away or eating is cut off over and over. | 37% of all decisions (9,109) have the reason "hurt". 215 of 271 deaths came straight after a "hurt" decision. | The owner chose a fixed rate on 2026-10-12: gym 0.4.21 ([Learning speed](#learning-speed-owner-decisions-2026-10-12), L-D). |
| N8 | About 28% of the run goes on the gaps between lives. | Median 36 s from a death to the next life's first decision (death screen, spawn select, about 10 trait picks, loading), while lives last 1-3 real minutes. | `G.respawnStep` pressed one button every 1.5 s; gym 0.4.21 presses one every 0.3 s ([Learning speed](#learning-speed-owner-decisions-2026-10-12), L-E). |
| N9 | The game speed you pick isn't remembered across a game restart. It's kept in the Lua session, so a restarted game plays at 1× until F5 (or a speed button) is pressed again. | Overnight, 50% of decisions ran at 20×. Since the 07:33 restart, 1,539 of 1,540 ran at 1×. | Fixed in code in mod 0.5.3 (2026-10-12, not yet run in the game): the pick is kept in `aivz/speed.txt`. The same day the game ran at 1x from the 12:11 restart until 13:00, when 20x was pressed again. Mod 0.5.3 also stops taking three game-made changes as the owner's pick of Play: unpausing with F2 (the game comes back with Play lit and the old multiplier), the Pause button coming back at a 1x the game had dropped to, and a drop while the mouse rests on the speed buttons. The short drops to 1x and back are the game's own: an exercise that ends or is cut off (`ISFitnessAction`), a walk that stops with the character still moving and no path (`IsoPlayer.updateInternal2`), a swing, a close zombie; the mod presses the pick again within 0.25 s once no zombie in sight is within 8 tiles. The game's own "reset speed after a timed action" option is off in `options.ini`. |
| N10 | Options that often fail (counts over the whole period). | walk fails 11% of the time and run 10%, mostly "no way there". curtain fails 27%, window 19%, search 15%, enter 9%. engine_on was tried 50 times and never finished: 48 were cut off while running and 2 got "engine didn't start". exercise gets "no effort spent" about 4 times an hour. The 292 "in too much pain" exercise refusals all happened before the 20:05 fix. | A player's pathfinding fails too, so those stay. engine_on goes with gap list G5. |
| N11 | The world `2026-10-11_12-06-26` reached 277 deaths. The 100-death limit is only reported. | `world_deaths` in `logs/agent-state.json` | Owner item 1. A new world was started at 07:33. |
| N12 | Neither game log has an error from the mod. | Vanilla only: 437 NullPointerExceptions in `IsoTree.isPlayerInsideARoom` over 14 s from 08:11:05, during a respawn, plus the usual SpriteConfig, font and map-file warnings. | Nothing to do. |
| N13 | **Training would have failed after every version change.** `learn.encode_file` left an out-of-date cache file open, and Windows refuses to replace an open file. The first round after any reward or encoding change raised `PermissionError`, and so did every later round. | Reproduced against `main`'s code in the reward version 3 dry run. | Fixed: the cache is read inside `with np.load(...)`. A test rebuilds an out-of-date cache. |
| N14 | **An empty gun looked full.** `item_status_tokens` computed `loaded / maxAmmo or 1.0`, so 0 rounds became 1.0 and got the "full" token. | Found in a scheduled run by reading the code. | Fixed in `agent/features.py` (tokens only, no layout change, `features.VERSION` unchanged); tests cover empty, partial and full. |

## Lessons: things written from memory that were wrong (2026-10-11)

Everything in `AIvZGymActions.lua` and the light/visibility code was written without the game's files; verify
against the installed Lua/Java before trusting any API name. Since 2026-10-12 `tests/test_lua.py` does part of
this on a PC with the game: it compiles the Lua with the game's compiler and flags any method name the game
doesn't have anywhere (it would have caught lesson 1, not a real name on the wrong class).

1. `Stats:getEndurance()` doesn't exist in Build 42 (use `getStats():get(CharacterStat.X)`): ~500 console errors.
2. `ISFitnessAction` needs `Fitness:setCurrentExercise` first, else a NullPointerException in `Fitness.incRegularity`.
3. Character creation only offered good traits; negative ones are probably in `listboxBadTrait` (unverified), so the
   AI overdrew its points and still started. Points rule now enforced (gym 0.4.2).
4. Hidden-information leaks (unseen zombies, unvisited building interiors, unlit objects) were in the observations;
   fixes in gym 0.3.2-0.4.1 are untested, and `isCanSee`/`getLightLevel` semantics and the 0.2 light threshold are unverified.

Checked against the installed 42.21.0 files on 2026-10-11 (read only, nothing run; details in
[ACTION_CATALOGUE.md](ACTION_CATALOGUE.md), [OBSERVATION_AUDIT.md](OBSERVATION_AUDIT.md),
[GAP_LIST.md](GAP_LIST.md)):

* Lesson 2's fix cannot work: `ISFitnessAction:new` takes a fifth argument `exeDataType` and calls
  `setCurrentExercise(exeDataType)` itself, so the call without it resets the exercise to nil. Weight
  exercises are also never offered (`getType()` vs `"Base.BarBell"`).
* Lesson 3: `listboxBadTrait` and `addBadTraitBtn` do exist. The points shown and enforced by the game come
  from the method `PointToSpend()` (profession cost, free points, negative-trait offset), not the field
  `pointToSpend` the gym reads.
* Lesson 4: `getLightLevel(pn)` is `max(r, g, b)` of the square's light for that player; `isCanSee` is a
  native flag computed with the player's view cone, which already narrows in the dark. The game's own
  "this zombie is visible" result is readable as `IsoPlayer:getSpottedList()` or `getTargetAlpha(pn)`.
* Also wrong from memory: `sleep` skips the game's "not tired enough" and "too soon" checks; `drink` lacks
  the thirst and beverage rules; `engine_on` lacks the key/hotwire check.
* The console log of 2026-10-11 12:06-12:52 confirms the first point: the session ran after the lesson 2 fix
  (commit 4d53766, merged 11:54) and still logged the `Fitness.incRegularity` exception 517 times (C1 below).

## Speech and announcements (item 5)

Recorded 2026-10-11; nothing removed yet. Paths are under `mod/AIvZ/42/media/lua/client/`.

**The mod's own `p:Say` calls (all in `AIvZ.lua`):**

| Line | Text | Runs while the agent plays? |
|---|---|---|
| 2082 | "AI online. Let's survive this." (`A.onGameStart`) | yes, at every game start |
| 1862 | "I've got it from here." (manual control ends) | yes, after you take over with the keys and let go |
| 621 | "This place will do. Home." / "I'll make this my new home." (`A.maybeSetHome`) | no, rules baseline only |
| 867 | "Too many of them!" (flee reflex) | no, rules baseline only |
| 1761 | any `say` text in `intent.txt` (field 6, the language model's line) | no, rules baseline only |

**The game's own text, triggered by the gym.** "Not safe to sleep here." is the game's `IGUI_Sleep_NotSafe`,
shown with `HaloTextHelper.addBadText` by `ISWorldObjectContextMenu.onSleepWalkToComplete`
(`client/ISUI/ISWorldObjectContextMenu.lua:1034-1047`, with `ContextMenu_PainNoSleep` and
`ContextMenu_PanicNoSleep`). The gym's `sleep` calls `onConfirmSleep` directly; a player would instead see
Sleep greyed out in the menu and never reach that code. Offering Sleep only when the menu would (gap list
item 3) stops it. Other gym verbs also call vanilla handlers directly; whether those show halo text is
**not audited**.

**Reasons the gym makes up and hands to the network.** `U.fail(t, reason)` texts reach the network as
`last.msg` in `obs.json`, and the HUD. The sleep ones (`AIvZGym.lua:819-826`: "not safe, zombies in sight",
"too panicked", "too much pain") are guessed afterwards from `getNumVisibleZombies()` and moodles; the
others come from pathfinding and internal checks ("no way there", "can't reach it", "couldn't reach it",
"took too long", "blocked", "no free square", "didn't get it", "not bandaged", "couldn't reach the bed",
"standing in furniture (...)", "item gone", "didn't move", "unsupported: ...", "error: ..."). Proposal: the
network gets only the status (`done` / `failed` / `running`) and whatever visibly changed; the reason
texts go to the debug log and the HUD only. The rules baseline has the same sleep texts (`AIvZ.lua:1680-1687`).

## Guard rails (item 6)

Recorded 2026-10-11; nothing removed yet. **Stays:** the game's own prerequisites, the rules the game's
menus and screens apply to a player. Removing those would give the network actions a player doesn't have.
Examples: Eat is greyed out at `FOOD_EATEN` >= 3 ("Can't eat more", `client/ISUI/ISInventoryPaneContextMenu.lua:500`);
Drink's 3-litre, sealed and `FOOD_EATEN` rules (`:2313`); the Sleep conditions (gap list item 3); Next on the
traits screen disabled below 0 points; climbing only where `canClimbThrough` allows it.
**Goes:** the repo's own rules, listed here.

1. **Caps that hide valid choices** (`G.options`, `AIvZGym.lua:288-480`):
   * walk/run in 8 fixed directions
   * the nearest 5 buildings
   * the nearest 5 rooms on this floor
   * attack: at most 4 zombies, within 8 tiles; shove: at most 2, within 1.6 tiles
   * doors 4, windows 4, climb 2, smash 2, clear_glass 1, curtains 3
   * search 6, take 12, eat 6, drink 2, equip 3, wear 3, take_off 4, drop 6, craft 5
   * taps 2, bandage 3
   * vehicles: the nearest 2 within 4 tiles (`AIvZGymActions.lua`)
   * `stow`: a rotating window of 12
   * `G.observe`: 40 inventory items

   Replace the caps with paging or categories so that every choice stays reachable
   (PHASE3_COVERAGE.md, "Action interface", point 3).
2. **Choices filtered for usefulness:**
   * `equip` is offered only for `HandWeapon`, though the game lets any item go in a hand.
   * `bandage` is offered only on wounded parts, and only with the first bandage found.
   * `take` is offered only within 2.5 tiles of a container already searched.
   * `search` is offered only for containers not searched before.
   * Sleep in a bed only uses the nearest bed in the current building.
   * attack/shove need a visible zombie, though a player can swing at nothing.
3. **Macros that decide for the network:**
   * `enter`: `A.travelStep`, which ranks entry windows by lock state (`AIvZ.lua:1322-1410`), then opens,
     smashes or climbs.
   * `A.stepOff` (`AIvZGym.lua:981-990`): steps off furniture by itself, fails the running action and
     blocks decisions until it is done.
   * Walking to the bed (`bedStep`).
   * Moving the bandage into the main inventory.
4. **When the network may decide:**
   * `G.needDecision` asks for a new decision on "hurt", "zombie close" or "still at it", spaced by
     `DECIDE_GAP` and `RECHECK`.
   * `G.settled` blocks decisions for about 15 s after each new life.

   **Owner decision (2026-10-12): ask at a fixed rate.** Done in gym 0.4.21, not yet run in game (see
   [Learning speed](#learning-speed-owner-decisions-2026-10-12)). `G.settled` stays.
5. **Character creation** (`AIvZGymActions.lua`):
   * the spend / repay / done stages
   * the 12-pick limit
   * the fallback after 6 refusals
   * `creationRepair` removing traits

   The game's only rule is that Next is disabled while `PointToSpend()` < 0. Offer the screen's own buttons
   (add, remove, profession, Next when enabled) and nothing else.
6. **The random policy** (`agent/policies.py:20`) keeps `continue` 4 times as likely as any other option.
   This is a property of the policy, not of the environment, and goes when a learner replaces it.
7. **The rules baseline** (`AIvZ.lua`) is a scripted player:
   * flee at 3 or more zombies within 2 tiles
   * re-arm
   * choose a home
   * close doors and windows
   * sleep tasks
   * language-model intents

   It runs only when no agent is connected. **Owner decision:** keep it as a comparison player or delete it.
   The gym uses its helpers (`travelStep`, `stepOff`, `bedStep`, `scanBuilding`, `scanWater`,
   `buildingInfo`), so those need moving first.

## Item and vehicle status (item 7)

Recorded 2026-10-11 from `G.itemInfo` (`AIvZGym.lua:116-151`) and the installed 42.21 files. Every method
named below exists and is public on a class Lua can call; it was checked in `projectzomboid.jar`, and
nothing has been run in game.

**What the network gets today:**

| Kind | Gets | Doesn't get |
|---|---|---|
| Clothing | name, type, weight, `cat`, `worn` | condition, holes, patches, blood, dirt, wetness, insulation, wind/water resistance, bite/scratch/bullet defence, run/combat speed modifiers, body location |
| Weapons | `dmg` (maximum only), `cond`, `range`, `ranged`, `twoHand` | minimum damage, head/handle condition, sharpness, ammo type, rounds loaded/maximum, magazine type and whether one is in, round chambered, jammed, spent rounds, fire mode, attached parts |
| Ammo, magazines | category "other" | ammo type, rounds in a magazine, which weapon it fits |
| Vehicles | `enter_vehicle` options (distance, seat, model name); inside: seat, engine running | every part, condition, fuel, battery, tyres, doors/windows, keys, speed, dashboard |

**What a player sees, and where it comes from:**

* **Clothing.** The inventory tooltip (`Clothing.DoTooltip`, jar) shows:
  * condition
  * insulation; wind and water resistance
  * bloody, dirty, wet
  * holes
  * bite, scratch and bullet defence, compared with what is worn in that slot
  * mask filter or tank
  * run and combat speed modifiers

  The Inspect window (`client/ISUI/ISGarmentUI.lua`) shows the hole, blood, patch and defence of each body
  part. The protection panel (`client/XpSystem/ISUI/ISCharacterProtection.lua`) shows totals per body part
  through `IsoGameCharacter:getBodyPartClothingDefense(Integer, boolean, boolean)`.

  Methods:
  * `getCondition()`, `getConditionMax()`
  * `getInsulation()`, `getWindresistance()`, `getWaterResistance()`
  * `getBloodLevel()`, `getDirtiness()`, `getWetness()`, `isWet()`
  * `getHolesNumber()`, `getPatchesNumber()`
  * `getBiteDefense()`, `getScratchDefense()`, `getBulletDefense()`
  * `getRunSpeedModifier()`, `getCombatSpeedModifier()`
  * `getBodyLocation()`, `getCoveredParts()`
  * per part: `getDefForPart(BloodBodyPartType, boolean, boolean)`, `getBloodlevelForPart(...)`,
    `getPatchType(...)`, `getVisual():getHole(part)`
* **Weapons.** The tooltip (`HandWeapon.DoTooltip`, jar) shows:
  * sharpness, condition, handle and head condition
  * damage minimum to maximum
  * bloody, range, two-handed, fire mode
  * the max-exertion warning
  * rounds loaded / maximum, magazine and ammo type
  * "Weapon jammed. Rack it.", "Spent round in chamber" / "No round in chamber"
  * spent rounds, "Contains Magazine" / "Need Magazine to operate"
  * attached parts

  Methods:
  * `getMinDamage()`, `getMaxDamage()`
  * `getHeadCondition()`, `getHeadConditionMax()`
  * `hasSharpness()`, `getSharpness()`, `getMaxSharpness()`
  * `getAmmoType()`: returns an `AmmoType`; `AmmoType:getItemKey()` is the round's item type
  * `getMagazineType()`, `getCurrentAmmoCount()`, `getMaxAmmo()`
  * `isContainsClip()`, `haveChamber()`, `isRoundChambered()`, `isSpentRoundChambered()`
  * `isJammed()`, `getSpentRoundCount()`
  * `getFireMode()`, `getFireModePossibilities()`, `getAllWeaponParts()`
* **Which ammo fits.** This is the game's reload menu,
  `ISInventoryPaneContextMenu.doReloadMenuForWeapon` (`client/ISUI/ISInventoryPaneContextMenu.lua`):
  * A weapon with `getMagazineType()` takes that magazine item (insert with
    `getBestMagazine(IsoGameCharacter)`, or eject).
  * Otherwise it loads loose rounds of `getAmmoType():getItemKey()` (`doBulletMenu`).
  * Unjam and rack follow `ISReloadWeaponAction.canRack`.

  Magazines carry `getAmmoType()`, `getCurrentAmmoCount()` and `getMaxAmmo()` (on `InventoryItem`). A
  player learns compatibility from the names on the tooltips and from which reload options appear.
* **Vehicles.**
  * Part conditions appear only in the Mechanics window. It walks to the hood, opens it (unlocking if
    needed) and opens the window: `ISVehicleMenu.onMechanic`, `client/Vehicles/ISUI/ISVehicleMenu.lua:960`;
    `ISOpenMechanicsUIAction`.
  * The window lists every part with its condition %, battery charge %, fuel %, and missing parts in red
    (`ISVehicleMechanics:doDrawItem`).
  * The dashboard while driving (`client/Vehicles/ISUI/ISVehicleDashboard.lua`) is **not audited**.

  Methods:
  * `BaseVehicle:getPartCount()`, `getPartByIndex(i)`, `getPartById(id)`. These are declared on
    `VehiclePartOwner` and used by vanilla Lua.
  * `VehiclePart:getId()`, `getCategory()`, `getCondition()`, `getInventoryItem()`
  * `getContainerContentAmount()`, `getContainerCapacity()`, `isContainer()`
  * `getDoor()`, `getWindow()`, `getLight()`
  * battery: `part:getInventoryItem():getCurrentUsesFloat()`
  * `BaseVehicle:isEngineWorking()`, `getCurrentSpeedKmHour()`

**Work items:**

| # | Item | Notes |
|---|---|---|
| O1 | **Started (gym 0.4.11, untested in game; methods as listed, each wrapped so a failure leaves the field out):** `G.clothingStatus` adds condition, insulation, wind/water resistance, blood, dirt, wetness, holes, patches, bite/scratch/bullet defence, slot. Not done: per-part defence and holes, protection panel. Clothing status in each clothing item's record: the tooltip fields above, plus per-part defence and holes from the Inspect window | Tooltips cost no game time, so they can sit in every observation for items in the inventory or an open container. The protection panel's per-part totals can go in `obs.body`. |
| O2 | **Started (gym 0.4.11, same caveat):** `G.weaponStatus` adds min damage, sharpness, head condition, fire mode and the ranged fields below. Weapon status: the tooltip fields above | Same. |
| O3 | **Started (gym 0.4.11, same caveat):** weapons carry `ammo`, `mag`, `loaded`, `maxAmmo`, `clip`, `chambered`, `jammed`, `spent`; rounds and magazines carry `ammo`, `loaded`, `maxAmmo` (`G.ammoStatus`). Not done: reload/rack/unjam actions. Ammo and magazines: their own type, rounds in a magazine; each weapon's ammo type and magazine type | Use one item-type identifier on both sides (weapon `ammo` = round's item type, `mag` = magazine item type), so matching is learnable from what the tooltips say, not given as a precomputed "fits" flag. The reload, insert, eject, rack and unjam actions are gap list item 21. |
| O4 | Vehicles: an `inspect_vehicle` action (the Mechanics window), then the part list as an observation, remembered until seen again | Outside view (open doors, smashed windows) and the dashboard need auditing first. Refuel, siphon, install and uninstall are gap list item 15. |
| O5 | Other tooltips not yet audited: food (freshness, calories, nutrition), literature (read or not), bags (weight reduction), drainables (uses left), keys (which car or door) | Audit as for O1 and O2 before building. |
| O6 | Encoding | Dozens of fields per item, for 40+ items, need a per-kind feature layout that the network can take in. **Interim (no layout change):** `features.item_status_tokens` turns the new fields into hashed tokens (ammo and magazine item types as names, binned condition, holes, jammed...), for carried and held items, so `features.VERSION` stays 1. A dense per-kind layout is still open (it would bump the version). |

## Console errors (item 8)

From `C:\Users\fab_f\Zomboid\console.txt`: session 2026-10-11 12:06-12:52, 37,210 lines, loader "OK v0.5.0".
It ran after commit 4d53766, so gym 0.4.3 with the "set current exercise" fix. Line numbers below are from
that version.

* **C1, exercise, 517 times.**
  * Error: `NullPointerException: Cannot read field "type" because "this.currentExe" is null` at
    `Fitness.incRegularity(Fitness.java:227)`, from `ISFitnessAction:exeLooped`
    (`shared/TimedActions/ISFitnessAction.lua:124`). Console lines 563-37145. Each one dumps a full stack
    trace, which makes up most of the log.
  * Cause: `exercise` calls `ISFitnessAction:new(p, name, 25, data)` without the fifth argument
    `exeDataType`. `new` calls `fitness:setCurrentExercise(exeDataType)`, setting it to nil and undoing the
    gym's own `setCurrentExercise` (`AIvZGymActions.lua:66`).
  * Fixed in code, not yet run in game:
    * Gym 0.4.4 (PR #21) passes `exeDataType`, matches equipment by full type and adds the fitness screen's
      limits and a 10-60 minute duration.
    * 0.4.4 read the duration and the limit from `o.minutes` / `o.blocked`, which are always nil (the
      option's fields are in `o.data`), so every exercise would have failed with "unsupported". Gym 0.4.5
      reads `o.data`. A new unit test checks every executor for this.
  * Still open: moving the equipment into the hands (`ISFitnessUI:equipItems`).
  * Live test: no `Fitness.incRegularity` exception, and endurance falls.
* **C2, vehicle scan, twice.**
  * Error: `attempted index: getVehicleContainer of non-table: null` at `AIvZGymActions.lua:139`
    (`nearVehicles`, from the vehicle option hook in `G.options` ← `G.request` ← tick). First at console
    line 2591.
  * Cause: `sqAt(...)` returns nil for a square that isn't loaded at the edge of the 4-tile scan. `try`
    catches the error, but Kahlua still logs every caught exception with a stack dump.
  * Fixed in code by gym 0.4.5, not yet run in game: the square is checked for nil before it is indexed.
    General rule: test for an expected nil, don't lean on `pcall`/`try` to skip it.
* **Not from the mod:** warnings about vanilla content, such as SpriteConfig `Wooden_Windows`, `Coffin` and
  `Key_Duplicator` entity scripts, the `Build_AnvilStone` icon, AngelCodeFont textures, map object files for
  the Kentucky towns, and recursive requires in WorldGen. Nothing to do.

## Found in the 42.21 audit, not fixed (2026-10-11)

Details, APIs and file references are in [GAP_LIST.md](GAP_LIST.md) (G#),
[OBSERVATION_AUDIT.md](OBSERVATION_AUDIT.md) section 5 (L#) and [ACTION_CATALOGUE.md](ACTION_CATALOGUE.md).

**Information the network gets but a player wouldn't (G1).** Status on 2026-10-12; "in code" means not run in
game (item N5):

* Open: L1 raw `stats` (11 internal values, including food sickness; in `obs.json`, never read by the network),
  L11 the `enter` macro's window choice by lock state, L12 the zombie visibility proxy (`isCanSee` plus
  light >= 0.2 instead of the game's spotted list).
* Fixed in code: L2 unseen rooms and openings (gym 0.4.15, 0.4.17, 0.4.19), L3 unseen beds (0.4.15),
  L4 time and temperature without a clock (0.4.6, 0.4.18), L5 objects behind walls (0.4.16), L6 poison in the
  drink category (0.4.12), L8 unseen vehicles (0.4.14), L9 zombie identity across occlusion (0.4.10).
* Kept from the network's input, still in `obs.json`: L7 window `locked`; L10 exact health, position, world age,
  exercise endurance, glass under a bandage.

**Verbs that are wrong:**

* G2 `exercise`: fixed in code by gym 0.4.4 and 0.4.5 (see C1), apart from moving the equipment into the
  hands. Not yet run in game.
* G3 `sleep`: follows the menu's conditions since gym `sleepBlock` (2026-10-11), not run in game.
* G4 `drink` lacks the thirst > 0.1 and beverage/bleach rules and the half/quarter portions.
* G5 `engine_on` lacks the key/hotwire/working-engine check; no Hotwire.
* G6 Trait points:
  * the gym reads the field `pointToSpend`, not `PointToSpend()`
  * NEXT is pressed while the game has it disabled
  * no profession choice
  * traits are removed in a way the screen doesn't offer

**Verb prerequisites (G7):**

* `smash` is offered for open windows.
* `clear_glass` doesn't check for an item in the primary hand.
* `equip`:
  * offers only weapons
  * doesn't check hand wounds or fractures
  * has no secondary hand or both hands
* `rest`:
  * is offered in a vehicle or already sitting
  * can't stand up
  * can't rest on furniture
* `drop` drops favourites, and works in a vehicle with the doors and windows shut.
* `take` doesn't use `ISInventoryTransferUtil` (corpse items).
* `drink_tap` keeps the nearest 5 before filtering by visibility.
* `enter` truncates to 16 buildings before filtering.

**Missing families (gap list items 8-23):**

* G8 floor items and corpses
* G9 a general adapter for the vanilla menus
* G10 drinking from sources, filling, washing, stoves, lights
* G11 medical care beyond bandages
* G12 reading
* G13 continuous movement and stance (crouch, sneak, sprint, aim)
* G14 barricading, lock and unlock, fences, sheets
* G15 vehicles beyond entering. No verified Lua path for driving: `CarController` is not exposed, and the
  `BaseVehicle` setters are untested.
* G16-G23:
  * full crafting
  * repairs and tailoring
  * generators and appliances
  * farming, foraging, fishing, trapping and animals
  * building and disassembly
  * firearms and hotbar
  * map, radio and TV
  * the new-game flow
