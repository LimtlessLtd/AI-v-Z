# Backlog

Items are recorded here when raised; status is honest. Phase 3 items must be done before the Phase 4
check-in; the rest are noted so they are not lost. Nothing here is live-tested unless it says so.

## From the owner, 2026-10-11

| # | Item | Phase | Status |
|---|---|---|---|
| 1 | After **100 deaths in the same game**, start a completely new game so the world doesn't run out of resources/houses. | 3 | Partly: the agent counts deaths per save (`world_deaths` in `logs/agent-state.json` and each `lives.jsonl` record; `Lives.new_world_due`). **Not done:** actually creating a new game through the game's own menus (needs a Lua adapter for the main-menu new-game flow; must be validated live and keep display/speed settings). |
| 2 | On death, choose the respawn location **randomly from those available**. | 3 | Already behaves this way: `G.respawnStep` picks a random town from the spawn-select list. Still to confirm in the live log that every available region (not only towns with a `region`) is offered. |
| 3 | Let the AI **choose its traits** at character creation, so it can learn to offset weaknesses. | 3 (action) / 4 (learning) | Written, **untested in game**. Gym 0.4.3 runs it in three stages so it can't dead-end: *spend* (add traits that cost points, or start; start is allowed at 0 or more, at most 12 picks) -> if points go below 0, *repay* (only traits that give points back are offered, no start) -> once back at 0 or more, *done* (the only option is to start). The agent never removes traits; if repay has nothing to offer or is refused 6 times, traits are taken off and the game starts. `obs.stage` reports the stage. Earlier history: (gym 0.4.0; 0.4.2 enforces the points rule: `finish_creation` is offered only with 0 or more points left, an overdrawn build is never started, and if the agent stops answering or isn't playing, traits are removed until the points are valid before Next; points come from the game's `pointToSpend` when present, else a conservative net-cost stand-in; the observation reports `points`, `points_from_game`, `may_finish`): on the profession/traits screen, while the agent plays, `G.creation` (AIvZGymActions.lua) sends `{creation: true}` requests with `add_trait` / `remove_trait` / `finish_creation` options (label and cost as the game states them), checks whether the selected-trait list actually changed, and presses Next after `finish_creation`, 12 changes, or 20 s without an answer. Choices are logged in the experience files (`life: null`). Written from the vanilla `CharacterCreationProfession` widget names; if the screen differs it falls back to Next. Not covered: profession choice, appearance, the first (map/spawn) screen's choices beyond random town. The random policy picks traits at random; no scripted build. |
| 4 | **Light levels:** don't present information a human couldn't see in the dark. | 3 | Started (gym 0.3.3, untested live): gym zombies on unlit squares (`getLightLevel` < 0.2, guessed) are hidden unless within 1.5 tiles, and `obs.light` reports the character's own square light. Gym 0.4.1 applies the same rule to door/window/curtain/container/tap scans and hides unvisited building interiors. Still to do: calibrate threshold in game, account for held torches/vision, audit building/container/item scans. Original note: audit what each observation reveals at night/in unlit rooms (zombie visibility currently uses `isCanSee`, which may not reflect darkness; building/container/item scans are unaudited). Decide on a light measure (square light level, torch/lamp held, indoors/outdoors) and expose it as an observation. |

## Standing Phase 3 gaps (see PHASE3_COVERAGE.md)

Exercise, full crafting, disassembly, vehicles, repairs, inventory organisation, hearing, remaining
hidden-information audit (scans and caches).

## Lessons: things written from memory that were wrong (2026-10-11)

Everything in `AIvZGymActions.lua` and the light/visibility code was written without the game's files; verify
against the installed Lua/Java before trusting any API name.

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
