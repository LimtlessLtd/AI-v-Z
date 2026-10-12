# Sitting and stuck-character check, 2026-10-12

Backlog row 1 is still open. The own-start-point change removed most of the old spawn stalls, but this
check found a new stall after resting on furniture. Mod 0.5.8 / gym 0.4.41 address the seated path's
prerequisite and expose getting up. The changes pass the installed game's compiler and method-name
checks; live results for these versions must be recorded separately below.

## What the running game recorded

Read the owner's `logs/experience/20261012-18.jsonl.gz` through `20261012-21.jsonl.gz`, from 18:32:00
through 21:09:00 local time, with `agent.features.read_records`: 26,471 decisions. Count a completed
action once, grouping a choice and its following `continue` records; `last.age` is in game ticks,
not decision IDs. Do not calculate an action ID by subtracting it from the decision ID. Creation,
death, a new life and a resumed agent break a group. No choices were injected into the game.

From 19:08 (after the game's own start points returned): 21,338 decisions, 5,110 completed actions,
641 reporting `no way there`. Of these, 633 belong to life 789; only eight belong to the other lives.
The longest consecutive run of completed actions reporting that failure is 99. This is better than
the earlier thousand-action stalls, but it does **not** establish that stuck characters are fixed.

Life 789 started at the usual `(7396, 6017, 0)` point at 21:01:23. It moved normally before the stall:

| Time | Decision | Position | Last action / next choice |
|---|---:|---|---|
| 21:01:32 | 1245 | 7399.5, 6020.0 | Bed rest running; chose another bed rest |
| 21:01:33 | 1247 | 7399.5, 6020.3 | Bed rest running; chose a window |
| 21:01:33 | 1248 | 7399.5, 6020.4 | Window failed: `no way there` |
| 21:01:34 | 1257 | 7399.5, 6020.4 | Chose a walk south |
| 21:01:34 | 1258 | 7399.5, 6020.4 | Walk failed: `no way there` |

The plain ground-rest choice disappeared at decision 1247 and remained absent while it was stuck.
`G.options` offers that choice only outside a vehicle and while neither sitting on the ground nor
on furniture. In conjunction with the bed rest and unchanged position, this supports a seated
pathfinding stall. The old observations have no explicit sitting flag, so they do not establish
which animation was running. This is not an old random-spawn or wall-line stall: it moved from its
spawn, and the stuck position is away from the square's edges.

Other rests did allow later movement: 114 rest choices were immediately followed by a walk or run
(allowing `continue` in between); 54 moved more than one tile before the move ended or was replaced.
Most rests were replaced while still running. This proves movement after a rest *choice*, not
successful completion of every sit animation or reliable getting up from every furniture type.

Three finished lives since 19:08 lasted more than a game day: life 747, 67.27 hours and 755 observed
squares; 753, 42.56 hours and 168 squares; 773, 25.72 hours and 178 squares. None was confined to its
spawn. New lives still used a small set of game start points. The policy's median highest choice
probability was 0.4616 in this interval, but it spans an agent restart: logged reward versions were
3 for 18,473 decisions and 4 for 2,865. Do not treat the whole interval as the current agent settings.

The live `console.txt` also contained caught nil-property errors from `AIvZ.lua:isBed` while enumerating
rest targets (`attempted index: has of non-table: null`). Mod 0.5.8 checks for nil properties before
testing the bed flag, instead of relying on a caught exception.

## Installed 42.21 sources and the fix

All paths below are relative to the installed game's `media/lua`; Java comes from its
`projectzomboid.jar` (42.21.0, Steam build 25485521, revision 4a0e9546ec).

- `client/ISUI/ISContextMenu.lua:1038-1064`, `addGetUpOption` and `onGetUpAndThen`: the menu queues
  `ISWaitWhileGettingUp`, then calls the selected handler once getting up finishes.
- `shared/TimedActions/ISWaitWhileGettingUp.lua`, `start`, `update`, `perform`: sets `forceGetUp`
  when `character:isSitting()`, waits until that becomes false, then runs its completion callback.
- `client/TimedActions/ISTimedActionQueue.lua:229-234`, `addGetUpAndThen`: the same wrapper for an action.
  `ISTimedActionQueue.add` itself does not add that prerequisite.
- `client/Vehicles/TimedActions/ISPathFindAction.lua:start`: starts the selected path immediately.
  `J:zombie.pathfind.PathFindBehavior2.pathToLocationF` calls `setData` immediately, whereas
  `pathToCharacter` handles a target sitting on solid furniture specially. The gym uses a location
  path; it must first get its own character up through the menu's prerequisite.
- `J:zombie.ai.states.PlayerSitOnGroundState.execute` and `PlayerSitOnFurnitureState.execute`, offsets
  0-25: a player's movement-key input stops queued actions and sets `forceGetUp`. The gym's chosen
  direction uses a timed path, rather than pressing that key.

Mod 0.5.8 uses `addGetUpAndThen` for its common path helpers when `p:isSitting()`. It queues no
extra action while standing, keeps the original path's failure callback, and retains the game's
own getting-up animation. The network still selects the direction and may replace the action.

Gym 0.4.41 offers `get_up` while sitting, through `ISWaitWhileGettingUp`, and reports success only
when the character is no longer sitting. The existing `stand` choice still means ending sneaking.
It also writes `obs.sitting`; `agent/features.py` deliberately includes `self:sitting` as a hashed
token. The dense layout and features version stay the same, preserving the trained network.
An already running Python agent needs a restart to use this new token.

## Remaining live check

After a reload, look for `loader.txt` reporting mod 0.5.8 / gym 0.4.41 (or later), `obs.sitting`,
a `get_up` choice completing with sitting false, and movement after a naturally chosen furniture
rest without a stationary run of immediate `no way there` failures. Check both ground and furniture
rests. Keep row 1 open until this and its curtain/wall-line checks are satisfied. Furniture rests
are frequently replaced before they finish; a bed-rest choice alone is insufficient evidence.
