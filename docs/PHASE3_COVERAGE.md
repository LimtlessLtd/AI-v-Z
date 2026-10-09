# Phase 3 action and hearing coverage — 2026-10-09

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
