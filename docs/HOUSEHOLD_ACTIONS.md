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
`ISPlumbItem:complete` sets `canBeWaterPiped=false` and `getUsesExternalWaterSource()` true and syncs it.
That is proof of connecting, not of a full supplier. Disappeared squares/objects must be guarded.

## Coverage and implementation status

In progress: oven/microwave controls, laundry switching/mode, plumbing, reusable-bandage cleaning,
and water choices built from the current visible fixture scan. The network chooses every action.
Ground fluid items, general fluid-transfer UI, fuel pumps, generators and campfire/BBQ controls remain
separate catalogue gaps. Live verification must use natural opportunities and report missing cases.
