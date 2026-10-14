# Backlog

What's open, in priority order (work it from the top: see [Open](#open)), then the history and details behind each item. Status is honest: nothing
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

**Work this list from the top.** Every agent (a local session, the hourly cloud routine, Codex or another) takes
the **first** row in "Work, in priority order" whose **Who** it can do, and finishes or advances it before
starting a lower row. A row with an open PR is taken (`gh pr list`): take the next one. Skip a row only for a blocker you write into its "Next step" (for example "needs the
game's files: no source for X"), so the next agent doesn't repeat the search. A new finding goes in where its
priority puts it, with the reason; only the owner moves the existing rows. A finished row leaves the list (its
details stay below, marked done with the PR). On 2026-10-12 the owner asked for the backlog to be worked in priority order and left the order to the local
session: first what helps the network survive zombies, then wrong data, then care and supplies, then breadth.

### Waiting on the owner

Agents leave these alone until the owner decides; then the item moves into the list below.

| # | Item | Next step |
|---|---|---|
| ~~N14~~ | **Done: the owner restarted the agent and the game at 10:26 on 2026-10-13** (agent process from 10:26:43, gym 0.4.55 loaded), so the sitting, furniture-posture and selected-profession tokens (gym 0.4.41/0.4.42/0.4.44) now reach the network. | – |
| Sound | **The game's sound is off**: `soundVolume`, `musicVolume` and `ambientVolume` are 0 in `options.ini`, so the new hearing capture (row 4) records silence. A player hears zombies, doors, glass, alarms and helicopters. | Turn the game's sound up in its own options. To keep the room quiet, one way to try: mute Project Zomboid in the Windows volume mixer instead; whether process loopback still hears it then must be measured (a local session can, with `agent/audio_loopback.py`). |
| O6 | A dense per-kind item layout for the network. Bumps `features.VERSION`, so the network starts over. | Decide when; hashed tokens stand in until then. |
| 6.7 | Keep the rules baseline as a comparison player, or delete it. | Decide; the gym uses some of its helpers. |
| ~~Reward 4~~ | **Decided and built (2026-10-12 evening): the proposal below, reward version 4** ([REWARD_RESEARCH.md](REWARD_RESEARCH.md) section 7). The owner asked (2026-10-12) for a reward for holding a weapon and for protective clothing, and for a cost to taking clothes off. Clothing is already in reward version 3, as Φ (+100 x the protection panel's average cover, so taking a garment off costs exactly what putting it on paid), but too small to matter: the median cover is 0.006 (0.6 points), shoes are worth 1.8 points and jeans 4.4, a few game minutes of the alive reward. A weapon earns nothing. Proposal: version 4 with the clothing term x20 (jeans 88, full cover 2,000) and a weapon term in Φ for a melee weapon in the hands, by its damage. Both are potential-based, so equipping and unequipping in a loop earns nothing. | Decide the sizes. A reward version change sets the trained network aside and trains a new one from all the experience (`learn.py`, `reward_v`). |
| ~~Policy spread~~ | **Decided and built (2026-10-12 evening): the median distance** (`policies.robust_spread`; needs an agent restart). The network's choices are close to random: about 0.03 for each of ~34 options. The policy is softmax(Q / (0.25 x the spread of this decision's Q)), and one option rated far below the rest (-6,729 against -500 to -1,000) makes the spread so large that the rest look alike. With a zombie within 2 tiles it walked or ran 38% of the time, exercised 6%, took clothes off 5%, shoved 4% and attacked 3%. | Decide whether the spread should ignore outliers (the median distance from the median, say); it is a training setting. |
| N3 | Restart the agent if it exits on its own (it is fine when run from `start.ps1`'s window). | Optional: say if you want `start.ps1` to restart it. |

### Work, in priority order

| Order | # | Item | Who | Next step |
|---|---|---|---|---|
| **Check what just changed** | | | | |
| 0 | N16, N17 | **The game ran out of Java heap, and sometimes hangs right after a respawn** ([details](#out-of-memory-and-a-hang-after-a-respawn-2026-10-13)). On top because either stops the training until someone restarts the game. **N16:** out of heap after 31,000 and 87,000 decisions (2026-10-12 17:15, 2026-10-13 04:10, the overnight crash). `GS.moveProps` kept every object ever scanned, because the game's Lua has no weak tables; gym 0.4.55 keeps only the latest scan's. In the game since 10:26 on 2026-10-13, no `AIvZ` errors. Its first major collection, 9 minutes in, found 1,449 MB of the 3 GB heap live, and young collections start at 94%: little room for a spike. **N17:** hung on 2026-10-12 11:55 and 2026-10-13 10:00, about 2 in 700 respawns, cause not found. The owner allowed installs (2026-10-13): Azul Zulu JDK 25 is in `E:\Tools`, and `scripts/watch-game.ps1` (started by `start.ps1`) keeps GC logs and saves thread dumps when the window stops responding for a minute. | local | **13 Oct, 15:15 (gym 0.4.74, game watcher):** dead characters stayed in memory, about 5 MB of live heap a life: the game's `ISTimedActionQueue.queues` keeps every character it ever queued an action for. Each new life now drops the dead ones. The watcher now saves native stacks of a hung game, closes it after 5 minutes without a response, or after a crash, and starts it again while the agent runs; the mod presses the main menu's Continue. The stacks of 12:57 and 13:05 show the game waiting on FMOD Studio's update thread, which kept using CPU ([follow-up](#out-of-memory-and-a-hang-after-a-respawn-2026-10-13)). **Next:** after the pull and a reload, the heap's `IsoPlayer` count (`jcmd <pid> GC.class_histogram`) should stay at 1-2 and the old generation's `Live:` flat; the first restart in `logs\watcher.log` should end with the agent playing again; the next hang's native stacks show what FMOD Studio's thread does. **13 Oct, 13:19 audit:** six dumps identify a non-returning native FMOD call during an animal update, with no AIvZ stack; the heap reached 1,738 MB live. [Evidence](BACKLOG_CHECK_2026-10-13.md#n16n17-heap-and-native-audio-hang). **Blockers:** no demonstrated Lua fix for the native wait; the session ended before 90,000 decisions. Keep collecting the new process's logs. **N16 so far (gym 0.4.55+, game started 10:26):** old generation live after each major collection 1,425-1,449 MB at 10:36-10:43, 1,500-1,536 MB until 11:01, 1,558-1,609 MB from 11:06 to 11:42 (the rise came with a drive through new areas, then it held). **N16:** in `logs\gc-<pid>.log`, follow the old generation's `Live:` at each `Major Collection` over a long session. If it stays near 1.5 GB, the leak is gone. If it climbs, another table keyed by game objects is never emptied: look for those. Then a session past 90,000 decisions with no `OutOfMemoryError` in `console.txt`. If it stays flat but near the top, put a larger heap (`-Xmx` in `ProjectZomboid64.json`, the PC has 32 GB) to the owner. **N17:** at the next hang, read `logs\hang-*.txt`: the main thread's stack in all three dumps shows where it spins. |
| 0b | Re-pick | **Gym 0.4.63: picking the running option again carries on with it** instead of starting it over ([details](#the-running-option-picked-again-2026-10-13)). 1,801 such restarts in two hours on 2026-10-13, more than `continue` picks. | local | **0.4.71 target follow-through:** new household/water actions compare actual source, UI and recipient references before carrying on; identical visible labels do not imply identical targets. **13 Oct longer check:** 09:30–11:30 versus 11:30–12:55: done/hour 2,184 versus 2,195, failed/1,000 play decisions 84.2 versus 37.4, fence done/failed 129/127 versus 189/63. [Method and limits](BACKLOG_CHECK_2026-10-13.md#re-picking-an-action-longer-comparison). **Blocker for attributing improvement:** other gym changes and different lives share this sample; continue natural observation. **First 13 minutes (live from 11:30 on 2026-10-13, against 09:30-11:29):** actions done 2,428/h (was 2,282/h); `climb_fence` 44 done, 4 failed (was 129 and 127); `light_switch` 5 done (none before). Failures per 1,000 decisions 69 (was 83), most of them `go_room` "no free square" (109), which fails at once and so isn't this change: gym 0.4.67 stops offering such rooms. **Next:** the same comparison over a few hours. |
| 1 | Stuck | **Gym 0.4.31 (mod 0.5.5): no more characters kept in one room for good** (the owner watched it happen four times; [details](#stuck-in-rooms-fights-and-clothes-2026-10-12-evening)). Hot-reloaded at 18:32 on 2026-10-12, no `AIvZ` errors. A door or window counts when the square on the near side of its wall is in sight (a drawn curtain, the night or a closed door hid every opening on a room's east and south walls); after two paths in a row fail from a spot on a wall line, the character walks to the middle of the nearest free square. First results (18:32-19:20): windows behind drawn curtains are listed (70 decisions offered to open a drawn curtain, against 1 in the 9,580 before). Two lives still got stuck, both on the old random spawn before gym 0.4.33: 735 started in a derelict room whose only door was locked (1,594 failures, then died); 739 started on a corner, the step-off took it to the middle of the square, and paths still failed from there 886 times (a walled-in spot). Since the game's own start points came back at 19:08: 0 "no way there" in 192 finished actions. Reward version 4: round 126 (19:20) is a fresh network; `climb` went from -5,472 to -57 against the average option, `take_off` -62 is below `wear` -54. 19:08-19:50: 1 "no way there" in 7,581 decisions, 18 lives on 14 start points (11308,6671 three times); the two long lives (747: 67.3 game hours, 753: 42.6) moved about (755 and 168 squares) and died of thirst, not stuck. Round 132 (19:48): `wear` -129 is below `take_off` -55 again, so the clothing term isn't learned yet. **Fence hopping:** see [the details](#fence-hopping-2026-10-12-evening). | local | **Sitting check complete, 13 Oct:** life 1056 rested on furniture, got up before movement and moved away; a standalone `get_up` completed at 12:32:18. The owner restarted for the tokens. [Exact sequence](BACKLOG_CHECK_2026-10-13.md#sitting-and-subsequent-movement). The old furniture/get-up/token blocker below is resolved; broader long-run room/path checks remain. **21:31 audit:** [follow-through report](BACKLOG_CHECK_2026-10-12.md): 1,396 decisions / 331 completed outcomes after the 21:21:49 reload, zero immediate path failures. A bed-rest choice led to sitting and a completed sheet removal after getting up. Gym 0.4.42 ([PR #82](https://github.com/LimtlessLtd/AI-v-Z/pull/82)) adds explicit furniture posture and ends rest when the game finishes sitting. **Remaining verification blocker:** the owner must restart for the new tokens; naturally completed standalone `get_up` and explicit furniture-rest examples are still needed. No choices or scenario will be scripted to obtain them. **21:09 follow-up:** [sitting check](SITTING_CHECK.md): 641 immediate path failures since 19:08, 633 in life 789 after a bed rest; longest completed-failure run 99. Mod 0.5.8 / gym 0.4.41 wait for getting up before common paths, add `get_up` and `obs.sitting`, and guard nil bed properties (caught errors seen in `console.txt`). Compiler/method checks and all 125 tests pass. Reloaded successfully; at 21:22 life 792 got up and walked after a ground rest, with get_up offered while seated. Furniture rests and standalone get_up completion remain pending. First verify a seated character gets up and moves after a natural furniture rest, with no stationary failure loop; restart the Python agent for the sitting token. Then the remaining checks. In the experience logs from 18:32: no run of thousands of "no way there" in a row (1,190-1,956 in a row before, with runs of about 50 in an ordinary life); a `window` or `climb` offered while its curtain is drawn, and `curtain` offered to open one; a position leaving a wall line right after a failure; no life of more than a game day in one room unless its doors are locked and it has no window; with gym 0.4.33, new lives on the game's own start points (a handful of squares per town, as before gym 0.4.24). Reward version 4: the first training round after the merge starts a new network (`train.log`, `history.jsonl` `reward_v` 4); after the owner restarts the agent, the top pick's chance in `experience` `probs` (median about 0.5 against 0.15) and fewer `take_off`; `wear`, `equip` and `unequip` shares. Then the README's gym entry. |
| 2 | N14, 2 | First hours of gym 0.4.23-0.4.29 and mod 0.5.3-0.5.4 after the agent restart (the restart also brings the policy temperature 0.25 and the new stance, facing and disassembly tokens to the agent). Seen live on 2026-10-12 before the restart, no `AIvZ` errors: "zombie close" asks at once (0.4.23); 4 of 4 new lives in new buildings in 3 towns (0.4.24); sneak offered and taken, the network crouched in 21 of 72 decisions, zombie facing from -1 to 1 (0.4.25); lock and unlock offered 8 times in 311 decisions, not yet chosen, and no character carried a sheet (0.4.26); `pick_up` offered and chosen 3 times, with no corpse in sight yet (0.4.27); no tools for disassembly and no drinks on offer yet (0.4.28 drink, 0.4.29 disassembly). Gym 0.4.33 adds climbing fences, sheets and curtains on doors and taking sheets down (in the game from 15:12 to 15:16 on an unmerged branch: `climb_fence` chosen 45 times, each replaced by the next decision before the climb). Seen 17:15-19:50 (27,687 decisions, gym 0.4.31 from 18:32, 0.4.33 from 19:06; the agent of 17:15, so still temperature 0.25 and the old spread), no `AIvZ` errors: done `pick_up` 859 times, `sneak` 335, `shove` 22, `search` 47 (19 kinds of container, 1 corpse), `drink_tap` 4, `equip` 1, `climb_fence` 377 (all low fences, none tall yet), `remove_sheet` 1 and `curtain` 1 (both windows). Not yet done: `lock_door` (once "the lock didn't turn"), `hang_sheet`, `disassemble`, `climb`, `drink`, and `attack` (57 picks, each replaced while running). The game logged 28 `act.txt` and 1 `gym.txt` sharing clashes in 2.6 hours (row 12). | local | **13 Oct audit:** furniture-rest recovery and standalone get-up now verified; [report](BACKLOG_CHECK_2026-10-13.md). **Remaining variant blocker:** no naturally completed locked-door/sheet-hanging/disassembly/corpse-drag/barricade/hotwire/equipped-exercise example in this sample. **G6 normal respawn verified at 21:57:** 25 professions offered, Park Ranger selected, good traits bought within -12, bad traits repaid debt, and the new life matched the profession; [details](CHARACTER_CREATION_CHECK.md). Emergency-repair and timeout variants remain unexercised. **21:31 audit:** [report](BACKLOG_CHECK_2026-10-12.md): six vehicle entries now completed, plus takes/stows/wears, low fences, searches, sheet removal, tap drinking and three bandages. **Variant verification blocker:** no naturally offered barricade/unbarricade/hotwire opportunity or completed standalone get-up, disassembly, door lock, sheet hanging or corpse dragging in this window. The prior bed-rest executor stayed running after seating; gym 0.4.42 fixes completion. Await natural opportunities, not supplied items or scripted choices. `loader.txt` says `v0.5.4 (gym 0.4.29)` or later; no `AIvZ` errors in `console.txt`; `aivz/speed.txt` after a speed pick, and a restarted game goes back to that speed; share of "zombie close" decisions (about 5% before gym 0.4.21); the network's top pick near zombies; time to the first zombie within 4 tiles and game hours per life, against the lives on the game's listed houses (backlog item 2); the first `lock_door`, `hang_sheet`, corpse `search`, `pick_up` done and `disassemble` in the logs, and that `ISMoveablesAction` works at 20x; gym 0.4.33: the first `climb_fence` done (low and tall, landing on the far side), a `hang_sheet` on a door, `remove_sheet`, and a door left as it was after a door-sheet walk (`restoreDoor`); gym 0.4.35 (mod 0.5.6, hot-reloaded at 20:12): a `pick_up` with `how` half or all that ends with the whole count, a bag on the ground searched (no items added to it) and taken from, `drag_corpse` ending with the character dragging it, a walk while dragging, and `drop_corpse`; gym 0.4.39: a `rest` with `bed` that ends with the character on the bed; gym 0.4.36 (hot-reloaded at 20:22): the first `barricade` that puts a plank up (on the side the character stands, the hammer equipped, a plank and a nail gone) and the first `unbarricade` that takes one off; whether a zombie stops at a barricaded window; gym 0.4.37: an `exercise` with a barbell or dumbbell that starts with it in the hands and spends endurance (and fewer "no effort spent", 9 of 338 on 2026-10-12), the first `hotwire`, and `drink` offered for bleach. Then update the README's gym entry. |
| 3 | N2, N6 | Survival and wound care after the recent changes. | local | **13 Oct audit:** 68 deaths since the 10:26 restart, median 2.335 game hours, zero kills; bandages picked in 92 of 1,480 bleeding decisions offering one. [Report](BACKLOG_CHECK_2026-10-13.md#treatments-and-supplies). **Comparison blocker:** several gym changes and environments differ, so this is no isolated learning comparison. **21:31 audit:** [report](BACKLOG_CHECK_2026-10-12.md): random median 1.355 hours (256 deaths); all net 1.51 (532); current reward-4 cohort 6.25 (nine), zero kills. Only two bandage picks in 135 bleeding decisions offering one since 20:55; no completed bandage in that current interval. **Comparison blocker:** the current cohort is small and includes a seated stall; collect a larger natural-play cohort before attributing survival gains to learning. Bandaging remains rare; keep the owner's reward/algorithm unchanged. |
| **What the character perceives** | | | | |
| 4 | Hearing | The game's own audio as the network's input, as a player hears it ([PHASE3_COVERAGE.md](PHASE3_COVERAGE.md#hearing-proposed-input-not-implemented)). The owner allowed installs on 2026-10-13, which put this at row 4 as planned. **Capture done (2026-10-13, no install needed: comtypes and numpy were there):** `agent/audio_loopback.py` captures ProjectZomboid64.exe alone, by Windows process loopback, in 0.25 s windows. `agent/hearing.py` keeps 12 of them (3 s) in every decision record. Live on the PC: capturing, no gaps, about 7% of a core, 2.2 KB per record raw (records were 8.3 KB raw, 0.4 KB gzipped). All silent: the game's volume is 0 ("Waiting on the owner", Sound). | local | **Still blocked, 13 Oct:** the owner's sound decision is pending; leave sound settings alone. After the owner's sound decision and an agent restart: check the windows aren't silent; measure what 20x does to the audio (pitch, dropped sounds) and record size with real audio. Then the input: hashed tokens per window (band levels and balance, coarsely binned) keep the dense layout and the trained network; a dense audio block would bump `features.VERSION` (owner decision O6). |
| **Care and supplies** | | | | |
| 7 | G11 | Medical care beyond bandages: disinfect, stitch, splint, remove glass, pills. | cloud, then local | **13 Oct live audit:** 17 bandages, five unbandages and three glass removals logged since 10:26. **Remaining verification blocker:** no naturally completed disinfect/stitch/splint/poultice/bullet/burn/unstitch/unsplint/pill example. [Evidence](BACKLOG_CHECK_2026-10-13.md#treatments-and-supplies). **Removal-signature blocker cleared, 2026-10-12:** installed 42.21 health-panel handlers and constructors verify removal of bandages, stitches and splints; [GAP_LIST item 11](GAP_LIST.md#11-medical-care-beyond-bandages) has exact nil arguments and menu prerequisites, plus glass tool/hand variants. **Gym 0.4.45 (cloud, not run in the game, `tests.test_lua` not run here):** `unbandage` is offered for up to 3 bandaged parts and queues `ISApplyBandage:new(p, p, nil, part, false)`, as `HRemoveBandage:perform` does. **Gym 0.4.46 (cloud, not run in the game, `tests.test_lua` not run here):** `unstitch` (`bp:stitched()`, `ISStitch:new(p, p, nil, part, false)`) and `unsplint` (`getSplintFactor() > 0`, `ISSplint:new(p, p, nil, nil, part, false)`), up to 3 parts each, as `HRemoveStitch`/`HRemoveSplint` do. **Gym 0.4.57 (local, 2026-10-13; `tests.test_lua` passes for 0.4.45-0.4.57; not yet seen in the game):** every other treatment on the health panel, read in the installed `ISHealthPanel.lua` (handler table in GAP_LIST item 11): `disinfect`, `poultice`, `stitch`, `remove_glass` (each tool kind or `Hands`), `remove_bullet`, `clean_burn`, `splint`. `bandage` now follows `HApplyBandage` too: any kind with bandage power, the panel's injury test, supplies from the panel's containers, no cap of 3. **Gym 0.4.59:** `take_pill`, the inventory menu's Take Pills with its own handler. **Next:** watch for each treatment and a pill completing, especially `disinfect` and `stitch` on a deep wound. |
| 8 | G10 | Water, washing, cooking, light: drink/fill, wash, stoves/microwaves, laundry and plumbing. | cloud, then local | **Gym 0.4.71–0.4.75, [PR #118](https://github.com/LimtlessLtd/AI-v-Z/pull/118):** nine household action types implement real oven/microwave settings, bandage-cleaning recipes, laundry toggles/mode and plumbing. Visible-fixture water choices replace the old source caps/cache and retain the selected object; tap drinking uses the game's mask handling. All 138 tests pass, including game Lua checks. Loaded 0.4.72: 490 sampled decisions, no gym errors or new module warnings, but no new household option offered. **0.4.75 recipe correction:** the installed scripts define modern `CleanBandage` (0.5 L of carried water); old sink recipe definitions are absent. The real inventory crafting callback now handles this choice. **15:27–15:29 passive 0.4.75 check:** 429 decisions, no gym errors; natural Wash Yourself completed at 15:29:02 (decision 29054) and tap drinking at 15:29:05 (29059). **Natural verification blocker:** none of the nine new household choices was offered; no completed appliance/laundry/plumbing or modern cleaning example yet. [Exact sources and limits](HOUSEHOLD_ACTIONS.md). **Next:** natural settings/dial/timer, bandage conversion, plumbing and laundry results; body/item/All washing and later bottle drinking. **Remaining code:** ground fluid items, general fluid-transfer UI, dispenser/fuel controls; catalogue lists other appliances. The playing agent needs its next restart for the new panel-feedback tokens; the dense layout/network are preserved. |
| 9 | G12 | Reading (skill books, magazines), with the menu's light and literacy rules. | local | GAP_LIST item 12. **Gym 0.4.61 (local, 2026-10-13; `tests.test_lua` passes; not yet seen in the game):** `read`, with the menu's tests read in the installed Lua (now in GAP_LIST item 12) and its own `readItem`. **Next:** watch for a completed read (pages moved, or a magazine's title read) and for skill XP afterwards. |
| **The gym's own limits and upkeep** | | | | |
| 10 | 6.1-6.3, 6.5 | Remove the repo's own guard rails: caps that hide choices, usefulness filters, macros, the character creation stages. | cloud, then local | [Guard rails](#guard-rails-item-6); keep the game's own prerequisites. **Gym 0.4.47 (cloud, not run in the game, `tests.test_lua` not run here):** attack cap 4 to 8 zombies (the 8-tile range stays). **Gym 0.4.48 (cloud, not run in the game, `tests.test_lua` not run here):** shove cap 2 to 8 (the 1.6-tile range stays). **Gym 0.4.49 (cloud, not run in the game, `tests.test_lua` not run here):** door cap 4 to 8. **Gym 0.4.50 (cloud, not run in the game, `tests.test_lua` not run here):** window cap 4 to 8. **Gym 0.4.51 (cloud, not run in the game, `tests.test_lua` not run here):** climb cap 2 to 8 (the 2.5-tile range and `canClimbThrough` stay). **Gym 0.4.52 (cloud, not run in the game, `tests.test_lua` not run here):** smash cap 2 to 8 (the 2.5-tile range and the closed, unbroken window test stay). **Gym 0.4.53 (cloud, not run in the game, `tests.test_lua` not run here):** clear_glass cap 1 to 8 (the 2.5-tile range and a held item stay). **Gym 0.4.54 (cloud, not run in the game, `tests.test_lua` not run here):** curtain cap 3 to 8 (the 8-tile scan range stays). **Gym 0.4.57 (cloud, not run in the game, `tests.test_lua` not run here):** search cap 6 to 8 (only containers not searched before are offered, as before). **Gym 0.4.68 (cloud, not run in the game, `tests.test_lua` not run here):** take cap 12 to 16 (the 2.5-tile range and a searched container stay). **Gym 0.4.73 (cloud, not run in the game, `tests.test_lua` not run here):** eat cap 6 to 8 (the stuffed test and `G.eatable` stay). **Gym 0.4.76 (cloud, not run in the game, `tests.test_lua` not run here):** drink cap 6 to 8 options (the code's cap was 6, not the 2 this list said; each portion counts as an option; `G.drinkable` stays). **Gym 0.4.77 (cloud, not run in the game, `tests.test_lua` not run here):** equip cap 3 to 8 (still `HandWeapon` only and the hand-fit test; the usefulness filter is list 2). **Gym 0.4.78 (cloud, not run in the game, `tests.test_lua` not run here):** wear cap 3 to 8 (still `Clothing` or a back bag, not already worn). **Gym 0.4.79 (cloud, not run in the game, `tests.test_lua` not run here):** take_off cap 4 to 8 (still only worn items). **Gym 0.4.80 (cloud, not run in the game, `tests.test_lua` not run here):** drop cap 6 to 8 (still not worn, not shut, not favourite). **Gym 0.4.81 (cloud, not run in the game, `tests.test_lua` not run here):** craft cap 5 to 8 (still `G.recipes` per item). **Gym 0.4.82 (cloud, not run in the game, `tests.test_lua` not run here):** unbandage, unstitch and unsplint caps 3 to 8 each (still only parts the game reports bandaged, stitched or splinted; the body has 17 parts). **Gym 0.4.83 (cloud, not run in the game, `tests.test_lua` not run here):** vehicle cap 2 to none (every vehicle on a visible square within 4 tiles; `taps 2` in this list was stale, taps have had no cap since 0.4.71). **Gym 0.4.84 (cloud, not run in the game, `tests.test_lua` not run here):** stow window 12 to 16 (it already pages through every move by decision id, so all stay reachable; destinations, the room test and the 2.5-tile container range stay). **Gym 0.4.85 (cloud, not run in the game, `tests.test_lua` not run here):** go_room cap 5 to 8 (still explored rooms on this floor with a free square). **Gym 0.4.86 (cloud, not run in the game, `tests.test_lua` not run here):** enter cap 5 to 8 buildings (still only buildings in sight now or remembered). Next: the last cap in list 1, observed items 40 (`G.observe`; needs paging, not a number change), one per run. **Blocker found 2026-10-14 (cloud):** raising the 40 in `G.observe` is not a safe number change. `agent/reward.py` counts every `inv` item as a "new item" (`progress.items`, lines ~175 and ~216), so a larger observation changes the owner's reward for heavy inventories; the dense feature already clips at 40 (`features.py` line 252, now pinned by a test), the rest are hashed tokens. Needs the owner's say on whether the reward should keep counting only the first 40 before the cap moves. **Also blocked (2026-10-14, cloud):** the `equip` usefulness filter (list 2) needs the menu's exact predicate for non-weapons; see Guard rails list 2. **2026-10-14 (cloud) status:** every remaining cloud step in rows 7-10 is built or blocked as written above (row 7 and 8 wait on natural examples in the game), so the run did upkeep: tests for `health_band`, `facing_word`, `sector`, `zombies_toward` and `read_lines`. **2026-10-14 (cloud, later run):** README versions checked against the code (gym 0.4.86, mod 0.5.8, reward 4, features 3: current); tests for `_num`, `_clip`, `_bin`, `bucket`, `_zombies` and `_salvage`. **2026-10-14 (cloud, third run):** test for `reward.potential` (sum of `potential_parts`, 0 when dead, no credit above 100 health). **2026-10-14 (cloud, fourth run):** test for `read_records` (bad JSON lines skipped, damaged gzip salvaged, non-gzip file gives nothing). |
| 11 | 1, N11 | Start a new game after 100 deaths in one save (the save is at 49). | local | Audit the main-menu new-game flow; keep display and speed settings. |
| 12 | N15 | `console.txt` logged a `FileNotFoundException` for `act.txt` ("being used by another process"): the game read the file while the agent's `os.replace` swapped in a new answer. Harmless (the read returns nil and is retried 2 ticks later), but Java logs a stack trace each time. Once at 11:31 on 2026-10-12, then 11 times in the game session from 12:11 to 14:10, mostly at 20x, where decisions come several times a second, and 28 times from 17:15 to 19:53 (about 11 an hour), plus once for `gym.txt`. (A local check script that read `act.txt` every 30 ms ran during some of them: read `obs.json` and the logs instead.) | local | Count it over a long run; if it becomes frequent, retry the read in Lua only after a short wait, or have the agent write in place. |
| 13 | O4, O5 | Vehicle part status (the Mechanics window); food, literature, bag, drainable and key tooltips. | local | **O5 done (gym 0.4.64, 2026-10-13; not yet seen in the game):** audited in the decompiled jar and the Lua. Food: what the name says (`Food.getName`: Fresh/Stale/Rotten from age against `offAge`/`offAgeMax`, Burnt, Uncooked, Frozen), the tooltip's endurance, stress and boredom changes, and calories only when the tooltip shows nutrition (a readable package or the Nutritionist trait). Drainables: the Remaining bar. Literature: has been read, pages. Bags: weight reduction. Keys show nothing more than their name. These reach the network as hashed tokens (`item_status_tokens`, and `fresh` and the flags on options such as `eat`): no layout change. Training uses them at once; the playing agent after its next restart. **Next:** O4 (vehicles). **Gym 0.4.65:** the firearm actions O3 was missing: eject/insert a magazine, load/unload rounds, rack or unjam, fire mode, load/unload a magazine, each as the inventory menu offers it (ACTION_CATALOGUE). **Gym 0.4.66:** `attack` fires a gun from its range through `ISReloadWeaponAction.attackHook` (until then a gun meant walking up and shoving). **Next:** watch for a ranged `attack` that kills, and its noise drawing zombies. |
| 14 | 5 | The game's own halo text from gym calls (e.g. "Not safe to sleep here."). `last.msg` is already kept from the network. | local | Audit which direct handler calls show text. |
| 15 | 4 | Calibrate the light threshold (0.2, guessed) and account for held torches. | local | Compare with the screen at night. |
| **Breadth** | | | | |
| 16 | G9 | A general adapter for the vanilla right-click menus: the scalable route to every menu action. | local | GAP_LIST item 9; side effects need live tests. |
| 17 | G15-G19, G21-G23 | Vehicles beyond entering, crafting window recipes, repairs, generators and appliances, farming, foraging, fishing, trapping, firearms, map and radio, the new-game flow. | local, then cloud | Audit each in the game files, then build; GAP_LIST items 15-23. |
| **Watching it** | | | | |
| 18 | P1 | The [public page](#public-page-owner-request-2026-10-12)'s replay radar shows the character, its path and the zombies, but no walls, doors or buildings: the observation has no geometry. | local, then cloud | Decide what a player sees that could be drawn (the room's openings already have counts, not positions); any new field reaches the page only when added to `agent/site.py`. |

## The running option picked again (2026-10-13)

At 20x a decision comes every few ticks while an action runs (one per game minute, gym 0.4.21), and until gym 0.4.63
a pick of the option already running started it over (`G.start`: `stopMoving`, a new path, the age back to 0). From
the experience logs, 09:30-11:40: of 9,391 decisions made while an action ran, 1,530 picked `continue`, 2,781 the
same verb, and 1,801 the very same option (the same visible fields bar distance, direction, age, zombies that way,
closing and facing): `craft` 756, `climb_fence` 361, `rest` 221, `pick_up` 157, `go_room` 118, `stow` 48. Actions
ended done 4,472 times and failed 1,291. Gym 0.4.63 treats the very same option as `continue`; a different target
still starts the new one. **Check:** more actions ending done per hour (the same count from the logs), fewer
"running" actions replaced, and walking actions (`go_room`, `light_switch`, `climb_fence`) arriving.

## Out of memory and a hang after a respawn (2026-10-13)

**N16, the Java heap (fixed in gym 0.4.55, not yet run in the game).** The game crashed at 04:10 on 2026-10-13
with `java.lang.OutOfMemoryError: Java heap space`, first in the world streamer saving the player
(`PlayerDB.updateWorldStreamer`), then on the main thread (`LightingJNI.updateVisibleRooms`), and the window
closed. The session of 13:20 on 2026-10-12 had already run out, while saving on quit at 17:15. The heap is the
game's default 3 GB (`-Xmx3072m` in `ProjectZomboid64.json`). Running out followed the number of decisions, not
hours or lives (session times from the DebugLogs, lives and decisions from `logs/lives.jsonl`):

| Session | Hours | Lives | Decisions | How it ended |
|---|---|---|---|---|
| 2026-10-11 18:31 | 13.0 | 246 | 21,035 | quit normally |
| 2026-10-12 13:20 | 3.9 | 121 | 31,430 | out of heap while saving on quit |
| 2026-10-12 20:53 | 7.3 | 200 | 87,245 | out of heap, crashed |

At each decision `G.scanAround` reads what the Disassemble menu would (`ISMoveableSpriteProps.fromObject`) for
every object within 3 tiles, floors and walls included. Gym 0.4.28 (2026-10-12 14:02) cached those readings in
`GS.moveProps`, keyed by the object, with `__mode = "k"` to let old ones go, and never emptied it (not between
lives, and a reload kept it). Kahlua, the game's Lua, has no weak tables: no class under `se/krka/kahlua` in the
42.21 `projectzomboid.jar` mentions `__mode` (`KahluaThread` has `__index` and `__newindex`). So the table kept
every object the character had been near since the game started, and its reading, and everything the object
refers to. Gym 0.4.55 keeps the readings of the objects the latest scan looked at and lets the rest go; a reload
empties it. `GS.zprev` has the same metatable but is pruned at every decision, so it stays small.

The first measurements, with gym 0.4.55 in a game started at 10:26 on 2026-10-13 (`jcmd <pid> GC.heap_info`, and
GC logging switched on in the running game with `jcmd <pid> VM.log`). The game's collector is generational ZGC
(`-XX:+UseZGC`, from the `windows` section of `ProjectZomboid64.json`). Young collections came every few seconds,
triggered by "High Usage" at 94% of the 3,072 MB, and freed about 1 GB each (GC(63): 2,878 MB to 1,876 MB). The
first major collection, GC(66) at 9 minutes, found 1,449 MB of the old generation live (2,410 MB to 1,776 MB in
all). So in ordinary play about half the heap is live and the young generation fills most of the rest. A spike
on top, such as a new town loading at a respawn or a save (the 17:15 error was in `GlobalModData.save`
allocating a buffer), has little room. If `Live:` stays near 1.5 GB over hours, the leak is gone, and the
remaining question is headroom, which is the owner's call on `-Xmx`.

The tools (2026-10-13, after the owner allowed installs): Azul Zulu JDK 25.0.4.1, the portable zip checked
against Azul's SHA-256, in `E:\Tools\zulu25.36.205-ca-jdk25.0.4.1-win_x64` (E: because C: had 46 GB free; not on
PATH). Its `jcmd` attaches to the game by process id (`jcmd -l` doesn't list the game, which has no
`hsperfdata`). `scripts/watch-game.ps1` uses it.

**N17 follow-up (2026-10-13, 13:19):** the watcher captured six stacks at 12:57 and 13:05: the game-logic MainThread is inside native `FMOD_Studio_EventInstance3D` while updating an animal, and the render thread waits for it. This identifies where those hangs stopped, not the reason inside the native call or the earlier respawn hangs. [Evidence and remaining blocker](BACKLOG_CHECK_2026-10-13.md#n16n17-heap-and-native-audio-hang).

**N16/N17 follow-up (2026-10-13, 15:15; gym 0.4.74 and the game watcher).** The owner found the game hung again
and wants it to run unattended for long stretches.

*The hangs of 12:56 and 13:04.* The game's DebugLog has a new character at 12:56:00, then no line until 13:00:52,
only 492 frames later; the experience logs stop at 12:56:11 and resume at 13:00:52. So the game ran about 10 s
into the new life, stopped for 4.7 minutes and carried on (the owner had been clicking the window). It stopped
again at 13:04:08, 3 minutes later in the same life, and the owner restarted everything at 13:06. In all six
dumps the game-logic `MainThread` waits in `FMOD_Studio_EventInstance3D` (setting a sound's 3D position, for an
animal's emitter) and uses no CPU between dumps. The thread jcmd lists as "Thread-2", with no Java frames, is
FMOD Studio's own update thread: in the running game, the thread that jcmd names Thread-2 has its start address in
`fmodstudio.dll` (`scripts/native_stacks.py`; Windows' `NtQueryInformationThread`). It used 7.8 s and 3.8 s of CPU
in the two 12 s gaps of the first hang, and 5.2 s and 0.1 s in the second. So the game waits for FMOD Studio
to take more commands, and Studio's thread is busy or stuck on something not yet seen. Before both hangs the
character was swapping clothes and items several times a second, each of which plays a sound. The game's volumes
are 0 (`options.ini`), which doesn't stop FMOD's work. Things ruled out: pausing on focus loss (`IngameState.onDisplayFocusLost` only pauses
with `focusloss=true`; it is `false`); the game never suspends FMOD's mixer (no class calls
`FMOD_System_MixerSuspend`); the microphone re-opens at 11:17 and 13:17 came from the options screen
(`MainOptions.lua` 2033-2047 call `setOptionVoiceEnable`/`setOptionVoiceRecordDevice`), not from a hang. The game
does record the microphone in singleplayer (`voiceEnable=true`, "Microphone (USB 2.0 Camera)";
`VoiceManager.InitVMClient` starts FMOD recording); the `-novoip` launch option would stop that, and `-nosound`
would stop FMOD altogether (`MainScreenState` 225-236), but there's no evidence that either is the cause, and
`-nosound` would also take away hearing. Left to the owner.

*Dead characters kept (N16, fixed in gym 0.4.74).* `jcmd <pid> GC.class_histogram` on the game started at 13:06
counted 45 `IsoPlayer` (and 525 `CharacterSoundEmitter` = 296 zombies + 184 animals + 45 players) after 44 deaths
in that game. The vanilla `ISTimedActionQueue:new` stores each character's queue in `ISTimedActionQueue.queues[character]`
(client/TimedActions/ISTimedActionQueue.lua:144) and nothing removes it; Kahlua has no weak tables. Each queue
kept its dead character and what it refers to (inventory, body, emitter, corpse via `diedBody`). The old
generation's live size went from 1,460-1,505 MB (13:16-13:51) to 1,697-1,702 MB (15:01-15:12), about 5 MB a life:
at 22 lives an hour, the 3 GB heap would run out in about 12 hours. `G.newLife` now drops the queues of dead
characters. The game itself stops a removed player's sounds after 5 s (`IsoPlayer.UpdateRemovedEmitters`), so
the dead characters' emitters didn't keep FMOD busy. Foraging's per-character tables are cleared on death
(`ISSearchManager.destroyUI`, `ISSearchWindow.destroyUI`).

*Keeping it running.* `scripts/watch-game.ps1` now also saves the native stacks of every thread with each
thread dump (`scripts/native_stacks.py`: Windows' dbghelp walks each thread's stack from the modules' unwind
data, frame names are the nearest export; each thread is suspended a few ms; 99 threads in 0.3 s). While the
agent runs, it closes a game that hasn't responded for 5 minutes and starts it again through Steam, and does the
same for a game that ended without being quit. A quit ends the DebugLog with "GameThread exited" and no
`uncaughtException`, and is left alone. At most 4 restarts an hour, logged in `logs\watcher.log`. Before starting
the game it writes the time to `Zomboid\Lua\aivz\resume.txt`. On the main menu `AIvZLoader.lua` reads it once (a
time under 15 minutes old) and presses Continue (`MainScreen.onMenuItemMouseDownMainMenu` with the Continue
label, which honours the menu's own delay and dialogs). If the saved character was dead, the gym presses the
new-character screens as after a death in the game (`G.creationStep`, shared with `G.respawnStep`). The agent
needs no change: it skips only a repeated decision id (`agent/link.py`), and hearing finds the new process.
Not yet run in the game: the next hang or crash is the first test.

**N17, the earlier hangs right after a new character arrives (no captured stacks).** The game stopped twice right after a
respawn: on 2026-10-12 at 11:55, 6 minutes into its session, and on 2026-10-13 at 10:00, 34 minutes in. Both
DebugLogs end with the new character arriving ("1 players found", "player 0 is mouse"; on 2026-10-13 also four
"Missing tile definition: lighting_outdoor_01_off_17/18" from `IsoCell.PlaceLot`), then nothing, and Windows
logged "Application Hang" when each window was closed. On 2026-10-13 no `obs.json` followed the spawn, and in
the hung process one thread (the main one, where the Lua runs) used a whole core while the other 98 were idle;
7.9 GB private memory; no exception logged. That isn't how the night's full heap went (an `OutOfMemoryError`,
logged), and the 2026-10-12 hang came before gym 0.4.28, so this is not N16. In those first seconds the gym only waits for the world to settle
(3 s), checks for furniture under the character, and holds the speed pick: it clicks the held speed (20x,
`aivz/speed.txt` = 3) every 15 ticks while no zombie is in sight. None of that loops, and the speed hold has run
since 2026-10-09, through the 13-hour session above without a hang. The game's runtime (Zulu 25.0.1 in `jre64`)
has no `jcmd` or `jstack` and exposes no counters (no `hsperfdata`), so the stack has to come from a JDK. Since
2026-10-13 the game watcher saves it: three thread dumps 10 s apart after a minute without a response, in
`logs\hang-<time>-<pid>.txt`. Tested with `-DumpNow` on the running game (three dumps and the heap in 28 s, the
game carried on). A main thread with the same stack in all three dumps is where it spins.

## Stuck in rooms, fights and clothes (2026-10-12 evening)

**21:09 follow-up, sitting:** [SITTING_CHECK.md](SITTING_CHECK.md) records the first-priority live audit,
including the new bed-rest stall in life 789 and the correction to the earlier claim that walking always
gets a seated character up. Mod 0.5.8 / gym 0.4.41 address the missing get-up prerequisite; live
verification remains in row 1. Long finished lives 747, 753 and 773 visited 755, 168 and 178 observed
squares, respectively, so the old spawn stalls are improved but this row cannot close yet.

The owner watched characters stuck in a room four times (a bathroom with a barricaded door, a window open and never
climbed through), saw it rarely shove, never attack or pick up a weapon, keep taking its clothes off, and climb back and
forth over one fence. From the experience logs of 07:33-18:09 (51,045 decisions, 236 lives) and `lives.jsonl`:

* **The window vanished behind its curtain (fixed in gym 0.4.31).** Life 676, 16:17: a bathroom whose door was locked
  (the character often stood on the door's own square). It opened the window, and `climb` was offered for 6
  decisions and not taken; then it drew the curtain. From then on the window, the curtain and `climb` were never
  offered again in 786 decisions, until the owner climbed it out at 16:21. The window is on the bathroom's east wall,
  which the game keeps on the square outside, and the gym listed doors and windows only on squares in sight: the
  curtain hid that square. At night the outside squares are too dark as well, so windows on east and south walls
  came and went as it moved. `G.scanAround` now also counts an opening when the square on the near side of its wall
  is perceivable.
* **No path from a wall line (fixed in gym 0.4.31, mod 0.5.5).** Seven lives never left the spot they started on, or
  left it only a few times: 610 (65.6 game hours), 618 (49.5), 644 (24.6), 668 (11.9), 623 (5.8), 633 and 621 (717, 83.5
  hours in a boathouse, started on a water tile, says the owner). Every walk, run, door, window and room failed
  "no way there" at once, 1,190-1,956 times in a row, with an unlocked door 3 tiles away in 644. All stood exactly on
  a square's edge (x or y a whole number). Over the day, path actions failed "no way there" 84% of the time from a
  square's corner and 67% from an edge, against 21% elsewhere. `PolygonalMap2.findPath` fails when the start square
  `isReallySolid()` or when `VisibilityGraph.getPointOutsideObstacles` can't move the start point out of the walls
  round it (42.21 bytecode). The spot was the mod's own spawn square: gym 0.4.24-0.4.32 started each life on a random
  square of a random room, at the square's corner, and next to a wall that corner is on the wall's line; the owner
  then asked for the game's own start points back (gym 0.4.33). A player walks off with the keys; the gym only walks
  by the pathfinder. `A.stepOff` now also steps off a wall line after two failures from the same spot (backlog N10's "a player's pathfinding fails too"
  was partly this).
* **Being stuck paid best.** The three longest lives of the day were stuck ones (83.5, 65.6, 49.5 game hours, dying of
  thirst), while 168 of the 183 lives in the 10:52 save were bitten, most within about 1.5 game hours; kills: 3 in
  183 lives. So far, staying in one room is the best play the network has seen, and it rates `climb` lowest of all
  its options: 773 below the median option on average over 2,436 offers, -2,800 against -1,200 in that bathroom. It
  chose `climb` 10 times in the day. With nobody stuck any more that should wear off with training.
* **Fights.** `attack` was chosen 178 times and 148 of them were replaced at the very next decision (94 asked because
  it was hurt, 48 because a zombie was close), mostly by `walk` or `run`: decisions keep coming while an action runs.
  A weapon was in the hands in 1% of decisions and any weapon in the bag in 3% (saucepans and pens, mostly), so
  `attack` is usually a shove or a stomp. See "Policy spread" and "Reward 4" under Waiting on the owner.
* **Clothes.** `take_off` was chosen 1,710 times and `wear` 800 in the day. Reward version 3 already charges taking
  clothes off, but at a few points per garment (Reward 4 above).
* **The fence.** The `climb_fence` option was in the game only from 15:12 to 15:16 (the fence work, gym 0.4.30 on the
  branch `claude/gym-fences`, went into a GitHub Desktop stash at 15:16, and is restored as gym 0.4.33; `main`'s gym 0.4.30 had no fences). In
  those 4 minutes the network took it 45 times in 340 offers, a share of 0.14 against 0.006 for `climb`. Since the
  restart at 17:15 the climbing is the game's own pathfinder: `PathFindBehavior2` calls `climbOverFence` and
  `IsoPlayer.climbOverWall` when a route crosses a fence, and `walk` and `run` aim 12-15 tiles away, so one walk
  crosses the fence and a walk the other way, which the near-random policy picks as often, crosses back.
* **Furniture in front of a window.** `IsoWindow.canClimbThrough` checks only the far side (not solid, not water,
  `PolygonalMap2.canStandAt`). To get there the gym uses the game's `AdjacentFreeTileFinder.FindWindowOrDoor`, which
  takes the far side's square when the near one is blocked, so the walk fails "no way there", as the game's own menu
  does. A player picks the furniture up or takes it apart (`disassemble` is there, picking furniture up is not).

## Exercise hand-off, hotwiring, the bleach test: G2, G5, G4 (done 2026-10-12 evening, gym 0.4.37)

The rest of the row "`exercise` moves the equipment into the hands; `engine_on` follows the radial menu", which waited
for the game's files. `exercise` now does what the fitness screen's Start does first (`ISFitnessUI:equipItems`): the
hands emptied for an exercise with no prop, its barbell or dumbbell into the hands for one with a prop, worn bags off.
The screen's re-equip when the exercise ends is left out (it runs only while the screen is open, and the next
decision's action would clear it from the queue). `hotwire` is offered to a driver as the radial menu offers it
(`ISVehicleMenu.lua:106-118`) and runs `ISVehicleMenu.onHotwire`. `drink` now tests `getFluidType() ==
FluidType.Bleach`, the Drink menu's own test, instead of a name. Details: [GAP_LIST.md](GAP_LIST.md) items 2, 4 and 5.
Live check: Open row 2.

## Barricades, G14b (done 2026-10-12 evening, gym 0.4.36)

`barricade` puts a plank on a door or window, `unbarricade` takes one off, for the nearest openings in sight, when
the door and window menus would list them (J:ISWorldObjectContextMenuLogic.doBarricadeMenu: a hammer, a plank, 2
nails, light to read by; Unbarricade: a hammer, crowbar, axe or tire iron). In 42.21 the menu's Barricade hands a
build cursor an `ISBuildIsoEntity` for the `BarricadePlanks` entity (a crafting recipe: hammer kept, 1 plank, 1 nail),
so the gym builds one the same way and does what a click on the opening's edge does (`ISBuildingObject.tryBuild`),
after the mod's walk, from the side it walks to. The old `ISBarricadeAction` is left alone: no 42.21 menu queues it.
Metal sheet and metal bar barricades (blowtorch, welding) are not done. The planks already up are on both options, as
a word. Live check: Open row 2. The "Survive zombies" group of the list is empty with this; findings for it go in
under a new heading.

## Items on the ground and corpses, G8 (done 2026-10-12 evening, gym 0.4.35)

The rest of backlog row G8, after picking up and corpse searches (gym 0.4.27). `pick_up` now takes one, half or all
of a pile, grouped as the world menu groups a square's items (by name); a bag lying on the ground is a container
for `search` and `take`, as the loot window lists it (not filled when looked into, as the loot window doesn't);
`drag_corpse` and `drop_corpse` do the menu's Grab > Corpse and Drop Corpse, and `obs.dragging` says a corpse is in
tow (a token). While dragging, the game's queue refuses every action that doesn't allow it, so the mod's walk now
allows it as the game's own walks do (mod 0.5.6). Placing an item is left out on purpose: `drop` already puts it on
the character's square, and the 3D cursor only picks a spot within the square and a rotation, which the observation
doesn't show. Details and citations: [GAP_LIST.md](GAP_LIST.md) item 8 and [ACTION_CATALOGUE.md](ACTION_CATALOGUE.md)
section 3.2. Live check: Open row 2.

## Fence hopping (2026-10-12 evening)

The owner had seen the character climb back and forth over one fence. Since gym 0.4.33 (19:06) the network picks
`climb_fence` in 45% of its decisions (3,406 of 7,581 to 19:50): in the median it is its second-best option, 263 above
the median option, and training round 132 rates it the highest verb (+341 against the average option). Life 753 climbed
one fence east and west 1,542 times in its 2,094 decisions and stayed on 168 squares. It lived 42.6 game hours without a
bite and died of thirst; life 758 is doing the same. Zombies were in sight in 837 of those decisions, but none came
near: the nearest was 22.9 tiles away in the median and 17.3 or more 90% of the time. So hopping isn't a way past close
zombies. It's a way of staying in one small place, which has paid best in the network's experience so far (the stuck
lives, [above](#stuck-in-rooms-fights-and-clothes-2026-10-12-evening)). Nothing rewards a climb in itself: the reward
has no term for it, and a back-and-forth loop earns nothing from Φ. It is the network's own learning, so nothing
changes in the gym; drinking and eating between hops are still to learn.

## Public page (owner request, 2026-10-12)

The owner asked to see the learning from anywhere. <https://limtlessltd.github.io/AI-v-Z/> (README "Public page")
has the Learning charts, a verbs × rounds heatmap of how its preferences changed, replays of real lives (the
radar, what it perceived, the top 10 options by Q and its pick) and the network (layout, weights, `qnet.npz`).
Owner decisions: replays of real lives rather than a toy simulation (the network would act outside anything it
learned from); GitHub Pages deployed by Actions from `site/` on `main`, with the data in the `site-data` release
so it stays out of git history; refreshed after merges on the owner's PC with `scripts/publish-site.ps1`.

Found while building it: the network has 322,945 weights, not the "about 0.7 M" the README and `agent/net.py`
said (corrected). The verb heatmap and the mean-Q chart jump at round 37, the first round under reward version 3.

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

**Done 2026-10-12, gym 0.4.25 (not yet run in the game):** Open rows 3 and 4 of the first ordered list. G13a: `sneak` and `stand` options (the C key's `setSneaking` toggle), and `obs.sneaking` / `obs.running`. O7: `zombies[].facing` (and on `attack`/`shove`), 1 facing the character, -1 facing away. Both reach the network as tokens (`self:sneaking`, `zombie:facing:toward:close`...), so `features.VERSION` stays 3. Still not seen: noise the character makes, and whether a zombie has noticed it (hidden AI state; a player reads it from the zombie coming closer, which `closing` already gives).

N5, the first run of gym 0.4.10-0.4.20 and reward version 3, came out clean on 2026-10-12. `loader.txt` said
`OK v0.5.2 (gym 0.4.20)` from 10:52, and `console.txt` had no `AIvZ` errors. `obs.json` had `protection` and `knox`,
and round 37 trained a fresh network under reward version 3 without errors.

## From the owner, 2026-10-11

| # | Item | Phase | Status |
|---|---|---|---|
| 1 | After **100 deaths in the same game**, start a completely new game so the world doesn't run out of resources/houses. | 3 | **Sitting check complete, 13 Oct:** life 1056 rested on furniture, got up before movement and moved away; a standalone `get_up` completed at 12:32:18. The owner restarted for the tokens. [Exact sequence](BACKLOG_CHECK_2026-10-13.md#sitting-and-subsequent-movement). The old furniture/get-up/token blocker below is resolved; broader long-run room/path checks remain. Partly: the agent counts deaths per save (`world_deaths` in `logs/agent-state.json` and each `lives.jsonl` record; `Lives.new_world_due`). **Not done:** actually creating a new game through the game's own menus (needs a Lua adapter for the main-menu new-game flow; must be validated live and keep display/speed settings). |
| 2 | On death, choose the respawn location **randomly from those available**. 2026-10-12: the owner asked for random spawn areas, as lives kept starting in houses earlier lives had drawn zombies to. | 3 | **13 Oct audit:** furniture-rest recovery and standalone get-up now verified; [report](BACKLOG_CHECK_2026-10-13.md). **Remaining variant blocker:** no naturally completed locked-door/sheet-hanging/disassembly/corpse-drag/barricade/hotwire/equipped-exercise example in this sample. **Owner's decision of 2026-10-12 evening: the game's own start points, gym 0.4.33** (in the game from 19:08: the next 4 lives started on the game's own points in 3 towns, the squares lives used before gym 0.4.24). The town is still picked at random on the game's spawn screen, and the game then places the character at one of that town's listed points. Gym 0.4.24-0.4.32 swapped the points for a random square of a random ground-floor room of the town, clear of the last 20 deaths (`G.spawnPoint`, `G.RANDOM_SPAWN`, now removed). That square was a corner of the room's tiles, so next to a wall the character stood on the wall's line, where the pathfinder finds no way anywhere; others were water (a boathouse) or a bathroom with a locked door. Seven lives that day never left their first spot, for up to 66 game hours ([details](#stuck-in-rooms-fights-and-clothes-2026-10-12-evening)). Earlier: **Gym 0.4.24 (not yet run in the game):** the town is picked at random on the game's spawn screen as before, and then a random ground-floor room of any building of that town (within 150 tiles of the town's listed points), with no building within 40 tiles of the last 20 deaths of this game session (`G.spawnPoint`, `G.RANDOM_SPAWN`). Why: the game's list for a character without a profession is about 10 houses per town (Muldraugh's `poor_houses`); the 7 small maps with one point each are Sandbox-only and not offered in this Apocalypse save. 576 lives started on 61 squares. Evidence on the owner's reason, from the 576 lives: a life starting where earlier lives of the same save started did **not** meet zombies sooner. 53% of first-time starts met a zombie within 4 tiles in their first 10 decisions (median 1.01 game hours lived), against 25-45% for repeat starts (1.27-2.15 hours). Fresh buildings may start harder, so compare after the change (Open item 2). |
| 3 | Let the AI **choose its traits** at character creation, so it can learn to offset weaknesses. | 3 (action) / 4 (learning) | **13 Oct audit:** 68 deaths since the 10:26 restart, median 2.335 game hours, zero kills; bandages picked in 92 of 1,480 bleeding decisions offering one. [Report](BACKLOG_CHECK_2026-10-13.md#treatments-and-supplies). **Comparison blocker:** several gym changes and environments differ, so this is no isolated learning comparison. **Option B, the owner's choice (gym 0.4.9, 2026-10-11, verified live):** it buys any number of good traits, each only if it leaves the points at -12 or above (`DEBT_LIMIT` in `AIvZGymActions.lua`), or stops buying; then, while the points are below 0, only bad traits; at 0 or above the game starts by itself. First live build: 5 good traits to -12, 3 bad traits back to 0 or above. History: gym 0.4.3-0.4.5 read the raw `pointToSpend` (starts at 0 whatever the screen shows) and stopped buying with points still on screen; gym 0.4.6's buy-until-0 rule kept bad traits on offer next to Continue once the points were back to 0, and the agent piled them up (up to 7 bad against 2 good); gym 0.4.8 had trait picking off. Each life's observations list its traits (`obs.traits`). Not covered: profession choice, appearance. **Open:** the network can only weakly link a trait to how a life went (option C in the 2026-10-11 discussion, per-trait scores from finished lives, was proposed and not chosen). |
| 4 | **Light levels:** don't present information a human couldn't see in the dark. | 3 | **Still blocked, 13 Oct:** the owner's sound decision is pending; leave sound settings alone. Started (gym 0.3.3, untested live): gym zombies on unlit squares (`getLightLevel` < 0.2, guessed) are hidden unless within 1.5 tiles, and `obs.light` reports the character's own square light. Gym 0.4.1 applies the same rule to door/window/curtain/container/tap scans and hides unvisited building interiors. Still to do: calibrate threshold in game, account for held torches/vision, audit building/container/item scans. Original note: audit what each observation reveals at night/in unlit rooms (zombie visibility currently uses `isCanSee`, which may not reflect darkness; building/container/item scans are unaudited). Decide on a light measure (square light level, torch/lamp held, indoors/outdoors) and expose it as an observation. |

| 5 | **No speech bubbles or announcements.** The character must not say or show anything the network didn't choose, and the network must not be handed explanations it couldn't know (e.g. "not safe to sleep here"). | 3 | Partly: all five `p:Say` calls in `AIvZ.lua` now go through a no-op `speak` helper (2026-10-11, untested in game). **Not done:** the game's own halo text from direct handler calls, and `last.msg` reason texts. Every source is listed in [Speech and announcements](#speech-and-announcements-item-5). |
| 6 | **Remove the repo's own guard rails**, so the network learns its own rules from repetition. | 3 | Not done. [Guard rails](#guard-rails-item-6) lists them, separated from the game's own prerequisites (which stay, because a player has them too). |
| 7 | **Item and vehicle status a player can see**: clothing condition, vehicle parts, weapons, ammo and which ammo/magazine fits which weapon. | 3 | **13 Oct live audit:** 17 bandages, five unbandages and three glass removals logged since 10:26. **Remaining verification blocker:** no naturally completed disinfect/stitch/splint/poultice/bullet/burn/unstitch/unsplint/pill example. [Evidence](BACKLOG_CHECK_2026-10-13.md#treatments-and-supplies). Clothing, weapon and ammo status are in item records since gym 0.4.11, and the protection panel since 0.4.20 (not run in game); the network sees them as hashed tokens. Open: vehicles, other tooltips, a dense layout (O4-O6 in [Item and vehicle status](#item-and-vehicle-status-item-7)). |
| 8 | G10 | Water, washing, cooking, light: drink/fill, wash, stoves/microwaves, laundry and plumbing. | cloud, then local | **Gym 0.4.71–0.4.75, [PR #118](https://github.com/LimtlessLtd/AI-v-Z/pull/118):** nine household action types implement real oven/microwave settings, bandage-cleaning recipes, laundry toggles/mode and plumbing. Visible-fixture water choices replace the old source caps/cache and retain the selected object; tap drinking uses the game's mask handling. All 138 tests pass, including game Lua checks. Loaded 0.4.72: 490 sampled decisions, no gym errors or new module warnings, but no new household option offered. **0.4.75 recipe correction:** the installed scripts define modern `CleanBandage` (0.5 L of carried water); old sink recipe definitions are absent. The real inventory crafting callback now handles this choice. **15:27–15:29 passive 0.4.75 check:** 429 decisions, no gym errors; natural Wash Yourself completed at 15:29:02 (decision 29054) and tap drinking at 15:29:05 (29059). **Natural verification blocker:** none of the nine new household choices was offered; no completed appliance/laundry/plumbing or modern cleaning example yet. [Exact sources and limits](HOUSEHOLD_ACTIONS.md). **Next:** natural settings/dial/timer, bandage conversion, plumbing and laundry results; body/item/All washing and later bottle drinking. **Remaining code:** ground fluid items, general fluid-transfer UI, dispenser/fuel controls; catalogue lists other appliances. The playing agent needs its next restart for the new panel-feedback tokens; the dense layout/network are preserved. |

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
   * the nearest 8 buildings (was 5 until gym 0.4.86, cloud, not run in the game)
   * the nearest 8 rooms on this floor that go_room can reach (was 5 until gym 0.4.85, cloud, not run in the game)
   * attack: at most 8 zombies, within 8 tiles (was 4 until gym 0.4.47, cloud, not run in the game); shove: at most 8 (was 2 until gym 0.4.48, cloud, not run in the game), within 1.6 tiles
   * doors 8 (was 4 until gym 0.4.49, cloud, not run in the game), windows 8 (was 4 until gym 0.4.50, cloud, not run in the game), climb 8 (was 2 until gym 0.4.51, cloud, not run in the game), smash 8 (was 2 until gym 0.4.52, cloud, not run in the game), clear_glass 8 (was 1 until gym 0.4.53, cloud, not run in the game), curtains 8 (was 3 until gym 0.4.54, cloud, not run in the game)
   * search 8 (was 6 until gym 0.4.57, cloud, not run in the game), take 16 (was 12 until gym 0.4.68, cloud, not run in the game), eat 8 (was 6 until gym 0.4.73, cloud, not run in the game), drink 8 (was 6 until gym 0.4.76, cloud, not run in the game), equip 8 (was 3 until gym 0.4.77, cloud, not run in the game), wear 8 (was 3 until gym 0.4.78, cloud, not run in the game), take_off 8 (was 4 until gym 0.4.79, cloud, not run in the game), drop 8 (was 6 until gym 0.4.80, cloud, not run in the game), craft 8 (was 5 until gym 0.4.81, cloud, not run in the game)
   * taps: no cap (gym 0.4.71); bandage: no cap (health panel, gym 0.4.57); unbandage, unstitch, unsplint 8 each (was 3 until gym 0.4.82, cloud, not run in the game)
   * vehicles: every one in sight within 4 tiles (was the nearest 2 until gym 0.4.83, cloud, not run in the game; `AIvZGymActions.lua`)
   * `stow`: a rotating window of 16 (was 12 until gym 0.4.84, cloud, not run in the game)
   * `G.observe`: 40 inventory items

   Replace the caps with paging or categories so that every choice stays reachable
   (PHASE3_COVERAGE.md, "Action interface", point 3).
2. **Choices filtered for usefulness:**
   * `equip` is offered only for `HandWeapon`, though the game lets any item go in a hand.
     **Blocker found 2026-10-14 (cloud):** the menu's rule for other items ("any item except all-food, clothing and forced two-handers", ACTION_CATALOGUE.md) is cited only as prose, and `equipEntry` calls `isTwoHandWeapon()`/`getCondition()` on the item, which are not shown to exist on every `InventoryItem`. Needs the installed `ISInventoryPaneContextMenu.lua` (`createMenu` :426-436, `doEquipOption` :4129) or the jar to write the exact predicate; a local session can do it.
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

**G6 closed for code and normal-flow verification (2026-10-12, [PR #84](https://github.com/LimtlessLtd/AI-v-Z/pull/84)):**
25 real professions were offered at a natural respawn; Park Ranger was selected, the unchanged option-B
rule bought a good trait and repaid the debt, and the next life matched the profession. The Next guard
ran in the game. [Exact observed sequence and limits](CHARACTER_CREATION_CHECK.md).
Medical removals (G11) now have verified installed signatures; their implementation is next.

**L12 closed (2026-10-12, [PR #83](https://github.com/LimtlessLtd/AI-v-Z/pull/83)):** gym 0.4.43
matched the game's spotted list in all 98 post-reload samples, including 77 with zombies present
(391 appearances on each list). G6 is implemented in gym 0.4.44 ([PR #84](https://github.com/LimtlessLtd/AI-v-Z/pull/84));
its normal natural-respawn flow was subsequently verified at 21:57 (details above).

**G7 follow-up (2026-10-12, [PR #82](https://github.com/LimtlessLtd/AI-v-Z/pull/82)):**
the remaining furniture source audit is complete; the get-up wrapper and completion fixes are in
gym 0.4.42. This row leaves Open for code work; its natural-play variant checks stay in rows 1/2.
See [the priority-order report](BACKLOG_CHECK_2026-10-12.md).

Details, APIs and file references are in [GAP_LIST.md](GAP_LIST.md) (G#),
[OBSERVATION_AUDIT.md](OBSERVATION_AUDIT.md) section 5 (L#) and [ACTION_CATALOGUE.md](ACTION_CATALOGUE.md).

**Information the network gets but a player wouldn't (G1).** Status on 2026-10-12; "in code" means not run in
game (item N5):

* Fixed in code: L1 raw `stats` (11 internal values, including food sickness) no longer in the gym's `obs.json`
  (gym 0.4.34; the rules baseline's own percept in `AIvZ.lua` keeps them; not run in the game).
* Fixed in loaded code: L11 the enter macro's window selection (mod 0.5.7); L12 uses the game's spotted list in gym 0.4.43 ([PR #83](https://github.com/LimtlessLtd/AI-v-Z/pull/83)). **Live comparison passed:** 98 sampled decisions, 77 nonempty, 391 zombie appearances on both lists, zero extras or omissions. L12 leaves Open; this is a comparison to the game's spotting result, not a claim that every fade animation was inspected on screen.
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
* G4 `drink`: fixed in code by gym 0.4.28 (thirst > 0.1 for water sources, beverage or bleach otherwise, half and quarter portions as `portion`); not run in the game.
* G14a fences and sheets on doors: done in code by gym 0.4.33 (2026-10-12; loaded live from 15:12 to 15:16 as part of an unmerged branch with no error; `climb_fence` was chosen 45 times and each was replaced by the next decision before the climb; no door sheet seen yet). In 42.21 the right-click menu has no climb entry for a fence (`J:ISWorldObjectContextMenuLogic.doHoppableMenu` only offers throwing a dragged corpse over); a player climbs with the Interact key: `J:IsoPlayer.doContextNSWE` → `doContextHopOverFence(dir)` (the `HoppableN`/`HoppableW` flag on the character's square or the one beyond, `getHoppable(north)`) → `ContextualActionHandlers.ClimbOverFence` → `onClimbOverFence` → `ISClimbOverFence:new(character, fence, dir)`; tall ones `doContextClimbOverWall` (`canClimbOverWall(dir)`, then `climbOverWall(dir)`). A tap refuses a climb onto a drop (`isSafeToClimbOver`: the far square `TreatAsSolidFloor` or `HasStairsBelow`); holding the key allows it, so the gym offers both and says `drop`. Doors: `doDoorMenu` offers Add sheet when `HasCurtains()` is nil, `canAddCurtain()` and a sheet is carried, and Open/Close and Remove curtains once one is up; `IsoDoor` is its own curtain (`HasCurtains()` returns the door, `isCurtainOpen()`), reached from `getAddSheetSquare`/`getSheetSquare`, which must be free, and `restoreDoor` puts the door back after the walk.
* G5 `engine_on` lacks the key/hotwire/working-engine check; no Hotwire.
* G6 Trait points:
  * the gym reads the field `pointToSpend`, not `PointToSpend()`
  * NEXT is pressed while the game has it disabled
  * no profession choice
  * traits are removed in a way the screen doesn't offer

**Verb prerequisites (G7):** most are done in the gym (checked against the code on 2026-10-12, not run in the game):

* Done: `smash` only for closed windows (`AIvZGym.lua` window options), `clear_glass` only with an item in the
  primary hand, `drop` skips favourites, `drink_tap` filters by visibility before keeping 2, `enter` filters to
  buildings seen or visited before keeping 5. `rest` is offered only when not in a vehicle and not already
  sitting (gym 0.4.33).
* Left, needs the game's files (no repo doc cites the call):
  * `equip`: offers only weapons; doesn't check hand wounds or fractures; has no secondary hand or both hands
    (`ISInventoryPaneContextMenu.OnSecondWeapon`/`OnTwoHandsEquip`, GAP_LIST item 7).
  * `rest`: can't stand up or rest on furniture (`ISWorldObjectContextMenu.onRest`).
  * `drop` in a vehicle with the doors and windows shut.
  * `take` doesn't use `ISInventoryTransferUtil` (corpse items).

**Missing families (gap list items 8-23):**

* G8 floor items and corpses
* G9 a general adapter for the vanilla menus
* G10 drinking from sources, filling, washing, stoves, lights
* G11 medical care beyond bandages
* G12 reading
* G13 continuous movement and stance (crouch, sneak, sprint, aim)
* G14 barricading (lock and unlock, fences, and sheets on windows and doors are done in code: gym 0.4.26, 0.4.33)
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
