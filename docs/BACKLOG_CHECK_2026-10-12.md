# Backlog follow-through, 2026-10-12 evening

Read-only checks of the owner's naturally generated logs, through **21:31 local time**. No actions
were chosen by the checking code and no scenario, speed, supplies or training settings were changed.

## Row 1: stuck characters and sitting

From the mod 0.5.8 / gym 0.4.41 reload at 21:21:49 through 21:31: 1,396 decisions and 331 terminal
action outcomes; **zero** `no way there` outcomes. A terminal outcome is counted once per selected
action and its following `continue` decisions; `last.age` is ticks, not an action identifier.

At 21:22:05, life 792 chose bed rest at decision 7021, was sitting in decisions 7022-7025, chose
`remove_sheet` at 7025, was no longer sitting at 7026 and had moved 2.1 tiles by 7027. At 7028 the
sheet removal was done. This extends the ground-rest evidence in [SITTING_CHECK.md](SITTING_CHECK.md).
The old field does not distinguish a furniture seat from the bed menu's fallback to the ground.

The running agent was started at 20:53:55, before the new sitting inputs were written. Its logged
reward version is now 4 and its maximum-choice probabilities are more concentrated than before
(median 0.8646 in the first 868 decisions examined after the reload). The sitting tokens still
need an owner restart. Do not restart or direct its play just to obtain verification examples.

The remaining checks need a naturally completed standalone `get_up`, explicit furniture posture,
and more time without a stationary failure loop. Keep row 1 open; missing examples are a verification
blocker, not evidence of a failure. The older curtain and wall-line examples remain in the backlog.

## Row 2: naturally completed action coverage

From 17:15 through 21:31, completed outcomes include 961 low-fence climbs, 128 searches, 101 takes,
67 stows, 85 wears, 103 take-offs, 23 tap drinks, 18 sleeps, 10 sheet removals, three bandages and
one weapon equip. Six vehicle entries completed. No completed attack, window climb, door lock,
sheet hanging, disassembly or corpse dragging appeared. A completed executor is evidence of its
reported effect, not a substitute for checking a specific pile count or fence's height.

Barricading, unbarricading, hotwiring and equipment-specific exercise still need a naturally
available opportunity; this check provides none. Likewise, vehicle entry does not verify driving
or a particular seat. Leave these variants open rather than supply items or choose actions for
the learner. The rest executor's own delayed completion is corrected in gym 0.4.42 below.

## Row 3: survival and bandaging

The baseline is the same legacy random cohort the dashboard treats as random: lives without a
policy field, excluding `ended: left`. Later records include policy explicitly. Every row below
uses finished deaths through 21:31; the current unfinished life is excluded.

| Cohort | Finished deaths | Median game hours | Kills |
|---|---:|---:|---:|
| Legacy random | 256 | 1.355 | 12 |
| All network lives | 532 | 1.51 | 3 |
| Network lives finishing 19:08-20:55 | 45 | 2.60 | 0 |
| Network lives logged under reward 4 | 9 | 6.25 | 0 |

The newest cohort looks better, but nine lives, different worlds and game fixes cannot establish
that training alone caused an improvement. Life 789 in that cohort also had the seated stall.
Keep the larger-cohort comparison open; do not change the owner's reward or algorithm.

| Decision window | Play decisions | Bleeding | Bandage offered while bleeding | Bandage chosen while bleeding | Completed bandages |
|---|---:|---:|---:|---:|---:|
| 17:15-21:31 | 45,895 | 5,537 | 661 | 14 | 3 |
| 20:55-21:31 (current agent) | 8,311 | 1,430 | 135 | 2 | 0 |

Creation and death records are excluded from play decisions. Bleeding means a body part has
`bleeding` in its flags. Completed bandages are terminal action outcomes in the whole window;
the wounds need not still be bleeding at the completion. Bandaging is still rarely selected when
offered. This does not establish an executor bug; the current interval has no finished bandage
with which to test it. More natural play is needed.

## Row 4 / G7: which furniture gets Rest

Installed 42.21 `projectzomboid.jar`, `zombie.iso.ISWorldObjectContextMenuLogic.fetch`, offsets
1639-1667: only an object's sprite with `IsoFlagType.bed` populates the context's `bed` field.
`createMenuEntries`, offsets 2626-2672, passes that field to `doBedMenu`. Non-bed-flagged chairs or
sofas do **not** gain a vanilla Rest entry merely because they have seating data. The gym's bed-flag
test is correct for that menu; the earlier unverified backlog question is resolved.

`doBedMenu`, offsets 116-223, applies obstruction, occupancy, own-seat and room/visibility rules,
then uses **addGetUpOption**, before `chairCheck` at 227-269. The chair name test suppresses Sleep,
not Rest. Thus bed-flagged chairs can offer Rest even when they cannot offer Sleep.

Game Lua, relative to installed `media/lua`:

- `client/ISUI/ISContextMenu.lua:onGetUpAndThen` queues `ISWaitWhileGettingUp` and invokes the selected
  handler after the character stands. `doBedMenu` applies that wrapper to Rest too.
- `client/ISUI/ISWorldObjectContextMenu.lua:onRest/onRestPathFound/onRestPathFailed` (915-944) paths
  to seating, queues `ISRestAction`, or falls back to ground sitting beside the object.
- `shared/TimedActions/ISRestAction.lua:update` (42-54) completes when `SitOnFurnitureStarted` is set;
  its comment states that endurance then recovers passively, including while reading.
- `shared/TimedActions/ISWaitWhileGettingUp.lua:start/update/perform` waits for `isSitting()` to end.

Gym 0.4.42 adds this missing get-up wrapper when changing seats, guards against a removed target,
and completes rest once the game's queue has finished and the character is sitting. A ground
fallback is reported honestly as `sat on the ground`. It no longer waits another 600 ticks after
the sit has finished. `obs.sittingOnFurniture` and a hashed `self:sitting:furniture` token distinguish
furniture from the ground, without a dense-layout change or network reset. The owner must restart
the Python agent for that token. Source audit and installed compiler/method checks are complete;
live variant checks stay in rows 1 and 2.

## Row 5 / L12: proxy versus the game's spotted list

Gym 0.4.42 live follow-up at 21:42:05: 395 logged decisions, 37 terminal outcomes and zero immediate
path failures. Two ground rests (lives 801 and 802) completed with sitting true at age 22 ticks,
instead of the old 600-tick delay. No explicit furniture completion appeared in that window.

The existing local diagnostic in `aivz/spotted.txt` was already running before this session. Its
snapshot here contains 8,520 rows: on **330** the gym lists a zombie absent from the game's spotted
list; on **66** the game's list has a zombie the gym omits; two rows have both discrepancies. Totals
are 473 extra and 91 missing zombie appearances across decision samples, not unique zombies.

Example diagnostic row: decision 186, 11.7 game hour, local light 0.81: gym one, game zero, extra one,
target alpha zero, nearest extra eight tiles. At decision 23 the game listed a zombie 15 tiles away
while the gym listed none. In samples with character-square light below 0.2, there were 17 game-only,
nine proxy-only and one both-disagree samples. Character-square light is only a diagnostic band,
not the target's light or a complete darkness test.

This supports replacing the gym's square/light proxy with `getSpottedList()` membership, as already
cited in [OBSERVATION_AUDIT.md](OBSERVATION_AUDIT.md) section 1 and L12. The fields belong in every
consumer: observed zombies, attack/shove choices, directional counts and the close-zombie decision
trigger. The baseline's internal threat detection is separate. Compare the same diagnostic after
the change; leave the pre-existing diagnostic edits uncommitted and preserved.

Gym 0.4.43 applies this change: membership in the current player's spotted list filters the existing
same-floor, alive, distance-sorted records. A missing spotted list yields none, without falling back
to the old guess. Nearby-object light checks are separate and retain their existing threshold.
All 125 tests pass, including installed-game Lua compilation and method-name checks. The next
verification is a diagnostic comparison after reloading, including decisions with zombies present.

**After reload:** gym 0.4.43 matched all 98 diagnostic samples (decision IDs 11204-11324, sampled
passively over 90 seconds): 77 were nonempty, with 391 zombie appearances on each list, zero
extra-zombie samples and zero missing-zombie samples. These are appearances across decisions,
not 391 different zombies. This verifies the running helper against the game's spotting result;
it is not a pixel-by-pixel check of every fade transition. L12's code/comparison item is closed.

The final integrated PC check found a false positive in the old chase-target source guard:
`getTargetAlpha` in the preserved local diagnostic matched its substring ban on `getTarget`.
The guard now rejects the exact `getTarget` name (including indirect references) and permits the visible fade
result already cited in observation-audit section 1. The diagnostic itself remains unchanged.
