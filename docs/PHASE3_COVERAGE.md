# Phase 3 action and hearing coverage — 2026-10-09

> **2026-10-11:** a full audit against the installed 42.21.0 files is in
> [ACTION_CATALOGUE.md](ACTION_CATALOGUE.md) (every player action, its vanilla source and the repo's status),
> [OBSERVATION_AUDIT.md](OBSERVATION_AUDIT.md) (what a player can perceive; remaining leaks) and
> [GAP_LIST.md](GAP_LIST.md) (ordered work with the exact APIs). It was done by reading the game's Lua and
> disassembling the jar; nothing was run in the game.

Phase 3 is not complete. The live verification covered all 27 **implemented** option types;
it did not establish that the agent can do everything a player can do. No network is learning yet.
This audit records current evidence and the work required before the Phase 4 check-in.

Target: normal singleplayer gameplay in Project Zomboid **42.21.0**, Steam build `25485521`,
revision `4a0e9546ec`. Actions become available under the same prerequisites as for a player.
Unavailable actions may be described with the same visible reason as the UI. Debug/admin commands,
hidden world state and changes to settings are not normal character actions.

## Current action coverage

| Family | Current gym | Remaining examples |
|---|---|---|
| Movement and combat | Eight-direction walks/runs, building/room paths, attack/shove | Continuous aiming and movement, crouching/sneaking, sprinting, climbing fences, firearm controls, ground attacks, interruption; verify each against normal controls |
| Clothing and equipment | Wear/remove some clothes and bags, equip/unequip primary weapon | All eligible items and equipment slots, secondary hand, clothing inspection, tailoring, cleaning and repair |
| Inventory | Search, take, drop | Choose item/quantity/source/destination; transfer into bags, cupboards and vehicle storage, nested containers, stacks, favourites, rename and placement; inventory UI operations |
| Crafting | Some recipes associated with inventory items | Complete known recipes from Build 42 crafting/workstation systems; choose materials, tools, amounts and recipe parameters; cooking/evolved recipes |
| Disassembly and construction | None | Furniture/object disassembly, item dismantling, moving/rotating furniture, building, barricading and related tool actions |
| Fitness | None | Exercise types, required equipment, duration, cancellation, normal endurance/load/pain restrictions |
| Vehicles | None | Enter/exit, seats, ignition/keys/hotwiring, steering/throttle/brake/reverse, headlights/horn/windows, fuel, trailers, parts inspection/install/remove/repair |
| Repair and maintenance | None beyond bandaging the character | Weapons/items, clothing, vehicles, generators and appliances, with normal tools/skills/materials |
| Health and personal actions | Bandage, rest, sleep, eat/drink | Full health panel treatments, medication, washing, sitting/standing, exercise and other normal character interactions |
| World systems | Doors/windows/curtains, taps | Electricity, appliances, generators, radios/TV, farming, animals, fishing, trapping, foraging, fire, alarms and other Build 42 interactions |
| Information and specialised UI | Basic inventory/body/weather/nearby observations | Books/maps, skills/recipes, fitness, health, crafting, mechanics and other screens; selectable dialog choices |

The implemented verbs are `attack`, `bandage`, `clear_glass`, `climb`, `craft`, `curtain`, `door`,
`drink`, `drink_tap`, `drop`, `eat`, `enter`, `equip`, `go_room`, `rest`, `run`, `search`, `shove`,
`sleep`, `smash`, `take`, `take_off`, `unequip`, `wait`, `walk`, `wear`, `window`, plus `continue`
for an action already running. Families above are an audit checklist, not a claim of exhaustive coverage.

`G.options` imposes per-verb caps: for example, at most five crafts, three wear options, three equip
options, six drops and twelve takes. `G.observe` caps inventory at 40 non-held items. The held item
is skipped by the general inventory option loop. Even implemented families omit valid item variants.
`G.recipes` relies on item-linked recipes plus three named fallback recipes; it is not the complete
Build 42 crafting system.

## Progress 2026-10-11 (gym 0.4.0; code written, **none of it run in the game**)

* `AIvZGymActions.lua` (new, loaded after the gym through `G.hooks`) adds verbs `exercise` (every entry of
  `FitnessExercises.exercisesType` whose equipment is carried; outcome = endurance actually spent), `stow`
  (any item to any carried bag, the main inventory or a searched container within 2.5 tiles; a window of 12
  moves that rotates each decision so every item/destination pair stays reachable), and `enter_vehicle`,
  `exit_vehicle`, `engine_on`, `engine_off`. Each guards its API calls and fails with "unsupported: ..." if
  Build 42.21 differs from the vanilla signatures they were written from (`ISFitnessAction:new`,
  `ISVehicleMenu.onEnter/onExit/onStartEngine/onShutOff`). Driving (steering/throttle), seats other than
  entering, repairs, disassembly and the fitness screen's reps/duration choices are **not** covered.
* `agent/hearing.py` computes stereo level, level change, balance and band energies per window, keeps a
  rolling history with capture-gap marking, and adds a `hearing` record to every decision. There is **no
  capture source yet**, so every record says `available: false` with the reason. Windows process-loopback
  capture needs a library that isn't installed; ask before installing.
* `obs.speed` records the game's speed multiplier (read only).

## Progress 2026-10-11 (gym 0.4.3, code only, not run in the game)

* Hidden-information fix: gym zombie observations and `attack`/`shove` options no longer carry `chasing`
  (the game's `getTarget() == player`, internal AI state) or the redundant `seen`. They carry what a player can
  watch instead: relative position, distance, `blocked`, `down`, and `closing` (tiles closed since the last
  decision that saw that same zombie, absent if not seen within ~15 s of game ticks). A Python test guards
  that the gym Lua never reads `getTarget`. The rules baseline (`AIvZ.lua`) still uses `chasing`; it is not the gym.
* Still open from the leakage audit: `sq:isCanSee` as a field-of-view proxy, recipe/target caches
  (`G.recipes` evaluates recipes against containers the player may not have looked in), no memory of
  previously seen zombies.

## Action interface to build

1. Enumerate the game's available inventory/world context-menu trees and their normal prerequisites.
   Keep the complete menu path, target and parameters. Invoke the same selected callback/timed action
   a player would invoke. IPC continues to select an option ID; it must never supply executable code.
2. Add adapters for non-menu controls and specialised screens. Selecting a menu entry that opens
   mechanics, crafting or fitness must expose the choices within that screen, not count as completing
   the underlying repair/craft/exercise. Driving needs continuous controls and timely observations.
3. Represent parameterised choices explicitly: item, slot, quantity, destination, recipe/material,
   duration, seat or control value as appropriate. Large choice sets can use navigable categories and
   pages: all choices must remain reachable, without selecting a supposedly useful subset for the agent.
4. Refresh availability before execution, respect normal range/visibility/knowledge requirements,
   and report cancellation, failure and actual effects. A queued command is not proof of success.
5. Audit every menu/control/screen family against the installed build and normal play logs. Record
   unsupported entries and adapters explicitly. Keep diagnostic/probe choices out of training logs.

Installed-source evidence: `ISContextMenu:onMouseUp` dispatches enabled entries using `onSelect`,
`target` and `param1` through `param10`. `ISWorldObjectContextMenu.createMenu` and
`ISInventoryPaneContextMenu` build menus and trigger their fill events. `ISDisassembleMenu`,
`ISFitnessUI`, and `Vehicles/ISUI/ISVehicleMenu` contain the missing disassembly, fitness and vehicle
interfaces. Menu builders also change UI state and can depend on mouse picking; they cannot simply
be called for every nearby object on every tick without an isolation and target-selection audit.

## Hearing: proposed input, not implemented

Capture **the PZ process's rendered stereo audio** locally, keeping a rolling buffer. Windows provides
[process loopback capture](https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/).
Check the available runtime/build tools and measure capture latency on this PC before choosing an
implementation. Ask before any installation. Avoid microphone capture or the mix of unrelated apps.

Convert small overlapping audio windows into numerical input: stereo time/frequency features,
overall level, changes in level, and left/right balance. A spectrogram is simply sound energy by
frequency over time. Preserve enough recent windows to convey rhythmic banging, repeated alarms,
engine changes and sustained rotor noise. Do not normalise every window to the same loudness.
Stereo balance is an audible cue, not an exact compass bearing or source coordinate.

The later network should learn sound patterns from its own play. No language model, pretrained sound
classifier, scripted survival response, or `helicopter_event_active` flag is required. Hearing a rotor
sound may eventually change its choices because of what it has experienced, not because an event
handler tells it to hide. An unheard alarm or hidden zombie must not become an observation just
because it exists in the world.

This path includes whatever is actually audible: helicopter, house/car/watch alarms, engines, horns,
sirens, zombie vocalisations and banging, footsteps, breaking glass, gunshots, weather, radios and
other sounds. It inherits the game's current mix and hearing effects; validate those against this
build. If audio is unavailable, record that explicitly rather than substituting hidden source data.

Sample continuously, including between decisions. Associate the audio history with real timestamps,
decision IDs, game age and the observed game speed. Preserve brief transients, pause/resume boundaries,
capture gaps and sustained sounds. Keep audio/feature records in the experience data so replay has
the same hearing evidence that was available when each action was selected. Measure storage cost and
latency before committing to window sizes or a model architecture. Do not change PZ speed mechanisms.

Why not just use `OnWorldSound`? Inspection of the installed `projectzomboid.jar` shows that
`WorldSoundManager` supports zombie/animal attraction queries and separately registers
`OnWorldSound`. `Helicopter.updateSound` and `Alarm.updateSound` use FMOD event calls directly;
their world-sound emissions are separate from audio playback. A world-sound list is therefore not
proof of what the player hears, nor a complete feed of audible audio. Lua-only sound hooks need a
coverage/audibility audit if used for diagnostics. Do not expose their hidden source identities or
coordinates as a substitute for hearing.

## Perception audit and completion gates

**Progress 2026-10-11 (gym 0.3.2, not live-tested):** zombie observations, `attack`/`shove` options,
walk/run "zombies toward" counts, building crowd counts and the "zombie close" decision trigger now use
only zombies the character can currently see (`visibleZombies` in `AIvZGym.lua`, based on square visibility).
Gym 0.4.1 extends this to the scans (code only, untested live): doors, windows, curtains and containers
within 8 tiles are offered only on squares in line of sight and lit enough (or within 1.5 tiles); taps likewise;
distant buildings are listed only if they have been in line of sight (kept as a map memory, `m.bseen`), and
their room names and looted/explored marks only once visited. Buildings use line of sight but not light.
Still open: `sq:isCanSee` is a square-visibility proxy that needs checking against the real field of view
(e.g. zombies behind the character); `scanAround`/`scanBuildings` and recipe/target caches are unaudited;
the rules baseline (`AIvZ.lua`) still uses all-zombie data (it is not the gym). No memory of previously
seen zombies is kept yet.

The current gym serialises all nearby zombies from `A.zombies`, including `seen=false`, with positions
and hidden chase-target flags; those records also affect direction and building crowd annotations.
World scans and cached recipe/target metadata need the same visibility/knowledge audit. Fix this
information leakage before training: visible evidence can identify targets; audible evidence must
remain limited to what can be heard. Preserve memory of previously observed things without granting
fresh knowledge of hidden changes.

Phase 3 completion requires an explicit menu/control/screen coverage audit, reachable action
parameters, player-perceivable observations, an implemented and measured hearing path, and honest
executor outcomes. Unit checks and live evidence must distinguish implemented coverage from all
player actions. Natural play remains the source of live evidence; do not stage practice scenarios.
Do not start Phase 4 before a user check-in. Its earlier DRRN proposal must account for temporal
audio and continuous controls, once this environment work is validated.

## Progress 2026-10-11 (gym 0.4.4, code only, not run in the game)

* `exercise` fixed per GAP_LIST item 2: `ISFitnessAction:new` now gets its fifth argument (the exercise type),
  equipment is matched by full item type with `contains(type, true)` (the old short-type comparison never matched
  `Base.BarBell`/`Base.DumbBell`), `Fitness:init()` is called first, the fitness screen's limits (endurance,
  heavy load, pain, sitting, climbing, vehicle) are reported as `unavailable` and refused at start, and the duration
  (10-60 game minutes) is an explicit option parameter. **Not done:** moving the equipment into hand
  (`ISFitnessUI:equipItems`), so prop exercises may still fail. Needs a live test: no `Fitness.incRegularity`
  exception and endurance must fall.
