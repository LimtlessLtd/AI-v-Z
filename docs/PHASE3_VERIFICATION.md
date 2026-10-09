# Phase 3 verification — 2026-10-09

Tested in the running singleplayer game, Project Zomboid 42.21.0 (Steam build `25485521`,
revision `4a0e9546ec`), with the agent and probe on the user's PC. The probe used naturally
offered options in the current save. Its scripted choices are kept in `logs/probe/`, outside
the random agent's experience. No game speed or save scenario was set up for these checks.

## Executor and path checks

The installed game's `WalkToTimedAction.lua` rejects `ISWalkToTimedAction` above game speed level 2.
Its `luautils.walkToContainer` and `walkAdjWindowOrDoor` queue that action, which explained
the earlier fast-speed failures. The gym now queues `ISPathFindAction` for these walks, checks
whether the target was reached or the requested effect happened, and reports failures as such.

The probe's live reports show completed searches, takes, doors, windows, curtains, climbs,
smashes, glass removal, clothing, food, tap drinking, crafting, bandaging, sleep, combat,
movement and building entry. Failed paths, locked openings and unchanged objects are reported
as failures. A craft produced three rags from a T-shirt; bandaging consumed rags. Some
outcomes, such as attack and rest, show that the command ran, while the body's subsequent
state and reward determine whether it helped.

For the continuous probe sample after reloading mod 0.4.2 / gym 0.3.0 at 21:10 (local time):

| Option | 1× done / failed | 20× done / failed |
|---|---:|---:|
| Search container | 35 / 6 | 87 / 0 |
| Go to room | 14 / 11 | 817 / 0 |
| Walk in direction | 0 / 1 | 1 / 1 |
| Run in direction | 0 / 2 | 1 / 0 |

These are action outcomes from `logs/probe/experience/*.jsonl.gz`, not independent or randomly
sampled trials. The probe repeated some room walks many times. The game often forced 1× near
zombies, and the character visited different locations at the two speeds. The data supports
that high speed no longer causes the previous blanket walk-to failure; it does not establish
that speed itself changes pathfinding success. Directional walks still sometimes stop short,
and containers behind walls or furniture can remain unreachable.

## Restart and automated checks

A controlled restart of the live probe resumed life 16 (Ann Marquis) with its accumulated
decision count. The first experience record after restart had `resumed: true`, `new_life: false`
and zero reward, excluding time when the agent was off. The save file
`logs/probe/agent-state.json` contains the ongoing life, reward components and progress.
The repository test suite passes with `python -m unittest discover -s tests`.

The focused probe subsequently equipped and unequipped a pencil three times each, at both 1×
and 20×. Review of the game's fluid menu showed that it offers beverages other than water;
gym 0.3.1 now includes those fluid containers. The probe found chocolate milk in a naturally
searched container, took it and completed a carried-fluid drink at 20×. Its inventory entry
disappeared and thirst fell from 0.13 to 0.09 in the next observation. No item was placed and
no practice scenario was staged. Across the probe logs, all 27 defined option types have at
least one `done` outcome. This establishes executor coverage, while the path and item variants
described above can still fail in play.

The hot reload cleanup no longer calls `GameTime:setMultiplier`. The live loader accepted mod
0.4.3 / gym 0.3.1 with no Lua error; game speed remains under the game's own controls.
