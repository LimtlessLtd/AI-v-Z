# Household supplies and cooking controls (2026-10-13)

G10 follow-through, checked against installed Project Zomboid **42.21.0**, Steam build 25485521,
revision 4a0e9546ec. This document records source facts; implementation and live results are dated below.
No supplied items, forced choices, staged lives or changes to the owner's training settings are required.

## Earlier priorities

Rechecked at 13:55: game process 39368 and the agent started by the owner at 13:06 are still running.
The game responds; `GC.heap_info` reports 2,368 MB used of 3,072 MB (used includes reclaimable garbage,
so it is not a live-generation measurement). There are no new hang reports. N16 still needs the long
run and N17 has no demonstrated Lua fix for the captured native FMOD wait. Hearing still needs the
owner's sound decision. G11's uncommon natural treatment opportunities remain the verification blocker.
The earlier checks and comparison limitations remain in [the backlog report](BACKLOG_CHECK_2026-10-13.md).

Gym 0.4.70 now has natural washing opportunities: the 13:39:35 onward sample contained 4,204 play
decisions, 96 with Wash Yourself and 11 with item washing offered. Wash Yourself was chosen, including
at 13:50:28 (life 1083) and 13:56:06 (life 1086), then replaced; no completion was recorded in that sample.
These are option/choice counts, not grouped terminal-action counts.

## Oven and microwave settings

Installed `client/ISUI/ISWorldObjectContextMenu.lua:1196-1210` calls `onMicrowaveSetting` or
`onStoveSetting`, walks adjacent, and queues `ISOvenUITimedAction`. Its
`client/TimedActions/ISOvenUITimedAction.lua:perform` creates the real `ISMicrowaveUI` / `ISOvenUI`,
replacing that player's previous window of the same kind. Opening a window is a separate action;
it does not complete cooking or set a preferred temperature.

The world-menu prerequisite is `J:zombie.iso.ISWorldObjectContextMenuLogic.doStoveOption`:
an `IsoStove` with a container, `not isSomethingTo(stove, player)`, powered, not LastStand.
This Java method was read with the already installed CFR 0.152.

| Window | Temperature dial values (internal Celsius mapping) | Timer dial values, minutes |
|---|---|---|
| `client/ISUI/Fireplace/ISOvenUI.lua:addKnobValues` | 0, 50, 100, 150, 200, 250, 300 | 0, 1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 40, 50, 60, 90, 120 |
| `client/ISUI/Fireplace/ISMicrowaveUI.lua:addKnobValues` | 90, 110, 130, 50, 70 | 0–10, 15, 20, 25, 30, 45, 60 |

The implementation must enumerate the live knob's `values` rather than invent a shared range.
`ISKnob:setKnobPosition` / `getValue` and the window's `ChangeKnob` implement a chosen dial value.
`ChangeKnob` sets **both** max temperature and timer and syncs the object (also the stove's sprite grid);
the timer knob can represent rounded remaining minutes while running. Preserve that coupling.
Selecting an unchanged dial need not trigger a callback. The Turn On/Off button is allowed only when
the real `ok:isEnabled()`; `onClick(ok)` sends the game's own `stove/setOvenParamsAndToggle` command.
`onClick(close)` hides the window. Do not call `onChangeTempType`: it changes and saves a global preference.

Observations may include the visible panel's kind, dial values and button state **only while the window
belongs to the current character, is visible and within its normal three-tile range**. These reach the
network through explicitly allowed tokens, preserving its dense layout and `features.VERSION`.
Do not expose internal food temperature, cooking progress or a closed appliance's settings.

## Cleaning reusable bandages

**Installed recipe corrected in 0.4.75:** `media/scripts/generated/recipes/recipes_medical.txt:108-130`
defines **`craftRecipe CleanBandage`**, an InHandCraft/Health recipe taking one dirty bandage/strip/rag
and **0.5 L of water from a fluid item**, with the `ragType` mapper returning the corresponding clean item.
There are no definitions of the four old spaced-name `Recipe`s in this installed build. The jar confirms
`ScriptManager:getRecipe` reads the legacy `recipes` collection; `getCraftRecipe` is a different collection.
Checking method existence alone did not establish that those old recipe entries could ever be offered.

The gym now offers `clean_bandage` for the current recipe, for each carried dirty item, wherever the
inventory menu's `HandcraftLogic` can perform it using that selected item. It checks the same containers
and craft surface as `ISInventoryPaneContextMenu.OnNewCraft` (`:3428-3476`), then invokes that callback
with `all=false`, as `createNewRecipeContextMenu` does (`:3375-3417`). No water is supplied automatically;
the network may choose Fill and then clean with what it carries. Conversion requires the selected dirty
item to disappear and its mapped clean-item count to increase. No extra taint rule is invented for this
recipe: its own fluid-category validation controls availability.

The modern inventory menu offers **One**. All through the full crafting window remains a separate
adapter gap; the existing Wash All Bandages is still a different legal action at a fixture. The legacy
adapter below is retained only when those optional recipe definitions actually exist.

`J:ISWorldObjectContextMenuLogic.doRecipeUsingWaterMenu` lists four recipes if present in the installed
script manager and the corresponding dirty item is carried (recursively):

| Recipe | Input |
|---|---|
| `Base.Clean Bandage` | `Base.BandageDirty` |
| `Base.Clean Denim Strips` | `Base.DenimStripsDirty` |
| `Base.Clean Leather Strips` | `Base.LeatherStripsDirty` |
| `Base.Clean Rag` | `Base.RippedSheetsDirty` |

The menu offers One, All of a kind and All kinds, limited by the source's fluid amount (one unit each).
`CleanBandages.setSubmenu` (`ISWorldObjectContextMenu.lua:1885-1927`) disables them for tainted water
**when** sandbox `EnableTaintedWaterText` is true. Preserve that actual menu condition.
`CleanBandages.onCleanOne/Multiple/All` (`:1829-1874`) transfers the selected items to the main inventory,
walks adjacent and queues `ISCleanBandage:new(player, item, source, recipe)`.
These handlers are a local table, so the adapter repeats their queue construction rather than calling
a nonexistent global. `ISContextMenu:addActionsOption` (`:1079`) uses `ISTimedActionQueue.queueActions`.
`shared/TimedActions/ISCleanBandage.lua:complete` replaces each input with the recipe's result, preserves
equipped hands and consumes one water unit. Completion must check the resulting inventory counts.

## Laundry machines

Read `J:ISWorldObjectContextMenuLogic.toggleClothingWasher`, `toggleClothingDryer` and
`toggleComboWasherDryer`, plus `ISWorldObjectContextMenu.lua:1113-1187`:

- A container, no `isSomethingTo` obstruction, not LastStand.
- On/Off requires power; a washer also needs fluid amount > 0. A combo needs water only in washer mode.
  The menu greys out the toggle under these conditions even if the machine is already on.
- Combo's Washer/Dryer mode entry has no power/water gate; its target is the opposite mode.
- All callbacks use the menu's get-up wrapper, walk adjacent, and queue the matching timed action.

The callbacks are `onToggleClothingWasher`, `onToggleClothingDryer`, `onToggleComboWasherDryer` and
`onSetComboWasherDryerMode`; the corresponding actions are under `shared/TimedActions/`.
Check the final `isActivated()` / `isModeWasher()` state; starting a machine is not proof that a
laundry load has completed. The bot still chooses inventory transfers, switching and waiting itself.

## Plumbing

`J:ISWorldObjectContextMenuLogic.fetch` selects a plumbable object when:

1. `hasModData()`, `canBeWaterPiped`, an indoor square and `FindExternalWaterSource()` exists; or
2. properties have `IsoFlagType.waterPiped`, external source use is false, and an indoor external
   source exists, or a room exists before shutoff with `canBeWaterPiped`.

Pre-shutoff is the game's formula: `worldAgeHours/24 + (getTimeSinceApo()-1)*30 < WaterShutModifier`.
Use it only as the menu prerequisite, never as network input. `doWaterPipeMenu` requires an unbroken
PipeWrench (type or `ItemTag.PIPE_WRENCH`) in the recursive inventory. `onPlumbItem` (`:1528-1534`)
equips that wrench and queues `ISPlumbItem:new(player, object, wrench)`; the menu has a get-up wrapper.
The adapter repeats that equip/action sequence with a disappearing-target validity guard on the action.
`ISPlumbItem:complete` sets `canBeWaterPiped=false` and `getUsesExternalWaterSource()` true and syncs it.
That is proof of connecting, not of a full supplier. Disappeared squares/objects must be guarded.

## Coverage and implementation status

**Implemented in gym 0.4.71:** nine action types in `AIvZGymHousehold.lua`:
`appliance_settings`, `appliance_temperature`, `appliance_timer`, `appliance_toggle`, `appliance_close`,
`clean_bandage`, `laundry`, `laundry_mode`, `plumb`. Open settings and configure them are separate choices.
The 0.4.75 correction connects cleaning to this installed build's actual crafting recipe, as above.
Closing an owned visible panel remains possible if the fixture disappears. Native cleaning/plumbing
validity checks have an additional missing-fixture guard. Other expected missing squares, containers,
sources and disabled buttons are checked before calls. Outcomes check the actual state or inventory change.

The existing gym scan now records each actual water fixture **after** the visibility check, in the same
eight-tile square scan used for other objects. Drink/fill/wash use those references; no nearest-five
pre-filter or nearest-two drink/fill cap remains. Its object lists are replaced on each scan, not kept
across the character's travels. The baseline's own water scan is unchanged. Tap drinking now runs
`onDrink`, including its mask removal/re-wear, after getting up. Filling also waits for getting up and
checks recipient existence before calling `onTakeWater`. Re-picking an action compares actual source,
UI and recipient references, which are never serialized for the network.

`obs.household.panels` contains only visible, owned, nearby oven/microwave panels. `agent/features.py`
explicitly includes their kind, dial values, active state and enabled toggle button as hashed tokens.
The dense layout and `features.VERSION=3` are preserved. Training can use the tokens immediately;
the already running playing agent picks them up on its next restart. Existing option fields already
encode all nine action types and their parameters. The public page's export allow-list is unchanged.

The loader's fixed mod-file list includes the new file. A bootstrap in `AIvZGym.lua` lets the first
hot reload from an older three-file loader load it and extend that fixed list, without restarting
the game or reading executable paths from IPC. The first reload accepted 0.4.71 at 14:39:47 and wrote
`obs.household.panels`, proving the family loaded. An additional `require` emitted a warning because
the running game's require catalogue had not indexed the newly added file; 0.4.72 removes that redundant
attempt and relies on the fixed reload list (fresh game startup already loads the client files).

**Validation:** all 138 tests pass on the owner's PC, including the installed game's Lua compiler
and method-name checks. New tests verify visible-panel input, exclusion of food's hidden cooking state,
distinct dial/quantity choices, and preservation of the network layout. Natural use is not yet verified.
The network chooses every action.
Ground fluid items, general fluid-transfer UI, fuel pumps, generators and campfire/BBQ controls remain
separate catalogue gaps. Live verification must use natural opportunities and report missing cases.

## First live reload checks

0.4.72 loaded at 14:54:36. A passive 14:54:38–14:57:38 check sampled 490 decisions and wrote
`obs.household.panels` with no gym error. Wash Yourself was offered in 18 and tap drinking in 52.
None of the new household choices was offered, so this does not verify their executors or UI dial sets.
The only new console exception was the known `act.txt` sharing clash (backlog N15); no new module warning.
The 0.4.75 recipe correction requires further natural dirty-item/water opportunities.

**0.4.75 follow-up:** the loader accepted this version at 15:26:36. A passive 15:27:13–15:29:13
check sampled 429 decisions with no gym error. Tap drinking was offered in 424, Wash Yourself in 27,
and item washing in nine. After an earlier failed attempt at each, Wash Yourself completed at 15:29:02
(decision 29054), and tap drinking completed at 15:29:05 (29059). These are natural terminal-action
results; the check only read observations and console output. None of the nine new household choices
was offered and no appliance panel was open, so their execution remains unverified. The console had
one known act.txt sharing clash and another pre-existing vanilla ISEquippedItem.checkToolTip/isAnyVisible
exception; neither was a household-module error.
