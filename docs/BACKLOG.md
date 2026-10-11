# Backlog

Items are recorded here when raised; status is honest. Phase 3 items must be done before the Phase 4
check-in; the rest are noted so they are not lost. Nothing here is live-tested unless it says so.

## From the owner, 2026-10-11

| # | Item | Phase | Status |
|---|---|---|---|
| 1 | After **100 deaths in the same game**, start a completely new game so the world doesn't run out of resources/houses. | 3 | Partly: the agent counts deaths per save (`world_deaths` in `logs/agent-state.json` and each `lives.jsonl` record; `Lives.new_world_due`). **Not done:** actually creating a new game through the game's own menus (needs a Lua adapter for the main-menu new-game flow; must be validated live and keep display/speed settings). |
| 2 | On death, choose the respawn location **randomly from those available**. | 3 | Already behaves this way: `G.respawnStep` picks a random town from the spawn-select list. Still to confirm in the live log that every available region (not only towns with a `region`) is offered. |
| 3 | Let the AI **choose its traits** at character creation, so it can learn to offset weaknesses. | 3 (action) / 4 (learning) | Written, **untested in game** (gym 0.4.0): on the profession/traits screen, while the agent plays, `G.creation` (AIvZGymActions.lua) sends `{creation: true}` requests with `add_trait` / `remove_trait` / `finish_creation` options (label and cost as the game states them), checks whether the selected-trait list actually changed, and presses Next after `finish_creation`, 12 changes, or 20 s without an answer. Choices are logged in the experience files (`life: null`). Written from the vanilla `CharacterCreationProfession` widget names; if the screen differs it falls back to Next. Not covered: profession choice, appearance, the first (map/spawn) screen's choices beyond random town. The random policy picks traits at random; no scripted build. |
| 4 | **Light levels:** don't present information a human couldn't see in the dark. | 3 | Started (gym 0.3.3, untested live): gym zombies on unlit squares (`getLightLevel` < 0.2, guessed) are hidden unless within 1.5 tiles, and `obs.light` reports the character's own square light. Still to do: calibrate threshold in game, account for held torches/vision, audit building/container/item scans. Original note: audit what each observation reveals at night/in unlit rooms (zombie visibility currently uses `isCanSee`, which may not reflect darkness; building/container/item scans are unaudited). Decide on a light measure (square light level, torch/lamp held, indoors/outdoors) and expose it as an observation. |

## Standing Phase 3 gaps (see PHASE3_COVERAGE.md)

Exercise, full crafting, disassembly, vehicles, repairs, inventory organisation, hearing, remaining
hidden-information audit (scans and caches).
