# Phase 3 gap list, in priority order (2026-10-11)

What to fix or build next, with the facts about the installed game (42.21.0) that each item needs. Each
API below was checked in the installed Lua or in `projectzomboid.jar` (method present, public, on a class
Lua can call); "**unverified**" marks what could not be checked without running the game, and
"**live test**" what only the running game can settle. Evidence and per-action status are in
[ACTION_CATALOGUE.md](ACTION_CATALOGUE.md); perception findings in [OBSERVATION_AUDIT.md](OBSERVATION_AUDIT.md).
Repo paths are under `mod/AIvZ/42/media/lua/client/`; game Lua paths under `media/lua/`.

Ordering: first what makes current data wrong (leaks, broken verbs), then the families a survivor needs
most, then breadth. Nothing here is Phase 4 work.

## P0: stop collecting wrong data

### 1. Remove hidden information from observations and options
Details and the field list are in OBSERVATION_AUDIT.md sections 2-5. APIs (all exist and are callable):
* Zombies seen: `IsoPlayer:getSpottedList()` → `java.util.Stack` of `IsoMovingObject` (contains the player
  itself; filter `instanceof(o, "IsoZombie")`), or `IsoObject:getTargetAlpha(int playerNum)` > 0.
  Live test: compare with what the screen shows at night and behind the character.
* Rooms seen: `RoomDef:isExplored()` (from `IsoGridSquare:getRoom():getRoomDef()` or
  `BuildingDef:getRooms()`); world-wide, so keep a per-character set alongside it.
* Squares: `IsoGridSquare:isSeen(int)`, `isCouldSee(int)`, `isCanSee(int)`, `canReachTo(IsoGridSquare)`.
* Clock: `UIManager.getClock():isVisible()` (time), `:isDateVisible()` (date and temperature);
  temperature as shown: `ClimateManager:getAirTemperatureForCharacter(IsoGameCharacter)`.
* Health band: `BodyDamage:getHealth()` with the `NewHealthPanel.getDamageStatusString` thresholds
  100 / 90 / 80 / 70 / 60 / 50 / 40 / 20 / 10 / 0.
* Kills as displayed: `IsoGameCharacter:getZombieKills()`.
* Doors as the menu shows them: `IsoDoor:couldBeOpen(IsoGameCharacter)`, `IsoThumpable:couldBeOpen(...)`.
* Darkness as the game judges it: `IsoPlayer:tooDarkToRead()`.
* Drop: the `stats` block, `window.locked`, `exercise.endurance`, world age in `obs`, exact `pos`.
* The `enter` macro (`A.enterStep`/`entryWindows`, `AIvZ.lua:1322-1410`) ranks every exterior window, seen or
  not, by `IsoWindow:isLocked()`/`isPermaLocked()`. Restrict it to windows the character has seen and drop
  the lock state from the ranking.

### 2. Fix `exercise` (AIvZGymActions.lua:29-74): it cannot work as written
* Constructor: `ISFitnessAction:new(character, exercise, timeToExe, exeData, exeDataType)`
  (`shared/TimedActions/ISFitnessAction.lua:204`). The screen calls it as
  `ISFitnessAction:new(player, selectedExe, minutes, exeData, exeData.type)` and queues it with
  `ISTimedActionQueue.addGetUpAndThen(player, action)` (`client/ISUI/ISFitnessUI.lua`, `onClick` "OK").
  `new` calls `fitness:setCurrentExercise(exeDataType)`, so the missing fifth argument sets it to nil and
  the earlier `setCurrentExercise` at `AIvZGymActions.lua:66` is overwritten.
* `timeToExe` is game minutes; the screen offers 10, 20, … 60 (`ISFitnessUI:onClickTime`). Expose this as
  the option parameter.
* Equipment: `FitnessExercises.exercisesType[name].item` is a full type (`"Base.BarBell"`,
  `"Base.DumbBell"`); test with `p:getInventory():contains(item, true)` as `ISFitnessUI:addExerciseToList`
  does (the repo compares `getType()`, so these exercises never appear).
* Preconditions to copy from `ISFitnessUI:updateButtons`: `MoodleType.ENDURANCE` ≤ 2
  (`ISFitnessUI.enduranceLevelThreshold`), `HEAVY_LOAD` ≤ 2, not `sitonground` / `isSittingOnFurniture()`,
  no vehicle, `PAIN` ≤ 3, not climbing. Also `ISFitnessAction:isValidStart`.
* Before queuing, do what `ISFitnessUI:equipItems` does: unequip hands for exercises without `prop`, equip
  the item (`ISWorldObjectContextMenu.equip(player, handItem, item, primary, twoHands)`), unequip worn
  `InventoryContainer`s with `ISUnequipAction:new(player, item, 50)`. The screen calls
  `player:getFitness():init()` when it opens (`ISFitnessUI:new`).
* Live test: the console must show no `Fitness.incRegularity` exception and endurance must fall.

### 3. Make `sleep` respect the game's conditions (**code done 2026-10-11, gym `sleepBlock`; not run in game**) (AIvZGym.lua:467-473, 808-827; AIvZ.lua:1646-1657)
The menu marks Sleep unavailable (`J:ISWorldObjectContextMenuLogic.doSleepOption`) when:
`Stats:get(CharacterStat.FATIGUE)` ≤ 0.3 ("Not tired enough"); `Stats:getNumVisibleZombies()`,
`getNumChasingZombies()` or `getNumVeryCloseZombies()` > 0; `p:getHoursSurvived() - p:getLastHourSleeped()`
≤ 1; with `p:getSleepingTabletEffect()` < 2000: `PAIN` moodle ≥ 2 and fatigue ≤ 0.85, or `PANIC` ≥ 1. The
repo calls `ISWorldObjectContextMenu.onConfirmSleep` directly, which only rechecks zombies, pain and panic
in `onSleepWalkToComplete` (`client/ISUI/ISWorldObjectContextMenu.lua:1034`). Offer Sleep only when the menu
would, and report the same reasons. Vehicle sleep has the same rules
(`client/Vehicles/ISUI/ISVehicleMenu.lua:190-225`).

### 4. Make `drink` follow the Drink menu (AIvZGym.lua:505-526)
`ISInventoryPaneContextMenu.createMenu` (`client/ISUI/ISInventoryPaneContextMenu.lua:437-444`): items with
`isWaterSource()` only when `Stats:get(CharacterStat.THIRST)` > 0.1; any other fluid container only when
not empty and its primary fluid `isCategory(FluidCategory.Beverage)` or is `FluidType.Bleach`. Then
`doDrinkFluidMenu` (`:2276`) applies the sealed, 3-litre and `FOOD_EATEN` rules (already copied). Add the
half and quarter portions (`onDrinkFluid(item, 0.5 | 0.25, playerObj, openingRecipe, item)`), shown when
amount/capacity ≥ 0.5 / ≥ 0.25.

### 5. Make `engine_on` follow the radial menu (AIvZGymActions.lua:150-201)
`ISVehicleMenu.showRadialMenu` (`client/Vehicles/ISUI/ISVehicleMenu.lua:87-101`): driver, `isEngineWorking()`,
not `isEngineRunning()`, not `isEngineStarted()`, and `SandboxVars.VehicleEasyUse` or
`p:getInventory():haveThisKeyId(v:getKeyId())` or `v:isKeysInIgnition()` or `v:isHotwired()`. Add Hotwire
(`ISVehicleMenu.onHotwire(playerObj)` → `ISHotwireVehicle:new(character)`) when there is no key and
Electricity ≥ 1 and Mechanics ≥ 2, or the Burglar trait (`:106-120`).

### 6. Trait points and profession (AIvZGymActions.lua:203-330, AIvZGym.lua:934-940)
* Points: `prof:PointToSpend()` (`client/OptionScreens/CharacterCreationProfession.lua:860`) =
  `pointToSpend + cost + SandboxVars.CharacterFreePoints - negativeTraitOffset()` (offset only if sandbox
  `NegativeTraitsPenalty` ≠ 1). The repo reads the field `pointToSpend`, which omits all three.
* Next: the game disables `prof.playButton` while `PointToSpend()` < 0 (`render`, `:827-836`); pressing
  NEXT through `onOptionMouseDown` bypasses it. Check `PointToSpend() >= 0` first.
* Profession: list `prof.listboxProf.items[i].item` (`CharacterProfessionDefinition`), choose with
  `prof:onSelectProf(def)` (`:434`). Add it as the first creation stage.
* Remove trait: `listboxTraitSelected.selected = i` then `onOptionMouseDown({internal = "REMOVETRAIT"})`;
  free (profession-granted) traits cannot be removed (`item:isFree()`).
* Widget names used by the repo are correct for 42.21: `listboxTrait`, `listboxBadTrait`,
  `listboxTraitSelected`, `addTraitBtn` (`ADDTRAIT`), `addBadTraitBtn` (`ADDBADTRAIT`), `removeTraitBtn`.

### 7. Small prerequisite fixes in existing verbs
* `smash` only for closed windows (`J:ISWorldObjectContextMenuLogic.doWindowMenu` offsets 888-1069).
* `clear_glass` needs an item in the primary hand (offset 296); otherwise report the game's reason.
* `equip`: any item may go in a hand (`ISInventoryPaneContextMenu.doEquipOption`, `:4129`), but not into a
  hand with a deep wound or an unsplinted fracture; add secondary
  (`ISInventoryPaneContextMenu.OnSecondWeapon(items, player)`, `:3715`) and both hands
  (`OnTwoHandsEquip(items, player)`, `:3693`), or call `equipWeapon(item, primary, twoHands, playerNum)`.
* `rest`: offer only when not in a vehicle and not already sitting; add standing up and resting on
  furniture (`ISWorldObjectContextMenu.onRest(bed, playerNum)` → `ISRestAction:new(character, bed,
  useAnimations)`).
* `drop`: skip favourites (`item:isFavorite()`), and in a vehicle require an open door or window.
* `take`: use `ISInventoryTransferUtil.newInventoryTransferAction(character, item, src, dest, time)` as
  vanilla does (corpse items become `ISGrabCorpseItem`).
* `drink_tap`: filter by visibility before keeping the nearest 5 (`AIvZ.lua:688`).
* `enter`: remember buildings from exterior squares in sight, filter before truncating to 16.

## P1: families a survivor needs, with entry points

### 8. Items on the ground and corpses
* Floor items: `IsoGridSquare:getWorldObjects()` → `IsoWorldInventoryObject:getItem()`.
  Grab: `ISWorldObjectContextMenu.onGrabWItem(worldobjects, WItem, playerNum)` (`:1436`; walks with
  `luautils.walkAdj`, then `ISGrabItemAction:new(character, WItem, time)`), `onGrabHalfWItems` (`:1448`),
  `onGrabAllWItems(worldobjects, WItems, playerNum)` (`:1466`). Hide items behind a wall
  (`IsoGridSquare:isWallTo`, as `handleGrabWorldItem` does).
* Corpses: `IsoGridSquare:getStaticMovingObjects()` → `IsoDeadBody:getContainer()`; the loot window lists
  them in `ISInventoryPage:refreshBackpacks` (`client/ISUI/ISInventoryPage.lua:1537`). Explore with the same
  rule as `checkExplored` (`:1511`): `ItemPicker.fillContainer(container, playerObj)` (`ItemPicker` is
  `ItemPickerJava`, `server/Items/ItemPicker.lua:1`; `fillContainer(ItemContainer, IsoPlayer)`) then
  `container:setExplored(true)` — or let the loot window do it by standing adjacent (**live test** which
  happens when the window is hidden).
* Place on ground: `ISInventoryPaneContextMenu.onPlaceItemOnGround(items, playerObj)` (`:4457`) or
  `ISDropWorldItemAction:new(character, item, sq, xoffset, yoffset, zoffset, rotation, isMultiple)`.

### 9. A general adapter for the vanilla menus (the scalable route to "every menu action")
* World menu: `ISWorldObjectContextMenu.createMenu(playerNum, worldobjects, x, y, test)`
  (`client/ISUI/ISWorldObjectContextMenu.lua:143`) builds an `ISContextMenu` from
  `ISContextMenu.get(player, x, y)`; options are `context.options[1..numOptions-1]` with `name`,
  `onSelect`, `target`, `param1..param10`, `notAvailable`, `toolTip`, and `subOption` (index for
  `context:getSubMenu(num)`, `ISContextMenu.lua:1226`). Selecting means calling
  `option.onSelect(option.target, option.param1, …, option.param10)` as `ISContextMenu:onMouseUp` does
  (`:70`). Options added with `addGetUpOption` have `onSelect = ISContextMenu.onGetUpAndThen`, the context
  as target and the real callback in `param1` (`ISContextMenu.lua:1038-1055`); calling them queues
  `ISWaitWhileGettingUp` first and needs the context's `player` field.
* Inventory menu: `ISInventoryPaneContextMenu.createMenu(playerNum, isInPlayerInventory, items, x, y,
  origin)` (`:26`).
* Inputs: `worldobjects` normally come from the picker; build them from objects on perceivable squares
  (OBSERVATION_AUDIT.md). `createMenu` refuses while paused or asleep.
* Side effects to handle (**live test**): `getCell():setDrag(nil, player)`, tooltip pools, the shared
  per-player context instance, `context:setVisible(false)` afterwards, and Java-side mouse coordinates
  (`screenToIsoX/Y` in `handleInteraction`, `handleGrabWorldItem`).
* Many entries start a **cursor** instead of an action (`getCell():setDrag(cursor, playerNum)`): walk to,
  barricade (`ISWorldObjectContextMenu.onBarricade(spriteName, playerObj)` → `ISBuildIsoEntity`, `:3046`),
  clean stains/graffiti, remove plant/grass, scythe, rake, moveables, building. They need the target
  square passed to the cursor (`ISMoveableCursor:create(x, y, z, north, sprite)`,
  `server/BuildingObjects/ISMoveableCursor.lua:186`, and similar) — **live test** per cursor.

### 10. Water, washing, cooking, light
* Drink from a source: `ISWorldObjectContextMenu.onDrink(worldobjects, waterObject, playerNum)` (`:2038`):
  walk, remove eating mask (`ISInventoryPaneContextMenu.getEatingMask(playerObj, true)`),
  `ISTakeWaterAction:new(character, nil, waterObject, waterObject:isTaintedWater())`, re-wear the mask.
* Fill: `onTakeWater(worldobjects, waterObject, waterContainerList, waterContainer, playerNum)` (`:2050`).
* Wash: `onWashYourself(playerObj, sink, soapList)` (`:1819`) → `ISWashYourself:new(character, sink)`;
  `onWashClothing(playerObj, sink, soapList, washList, singleClothing)` (`:1777`) →
  `ISWashClothing:new(character, sink, item, bloodAmount, dirtAmount, noSoap)`.
* Stove/microwave: `ISWorldObjectContextMenu.onToggleStove(worldobjects, stove, playerNum)` (`:1189`) →
  `ISToggleStoveAction:new(character, object)`; settings `onStoveSetting`/`onMicrowaveSetting`.
* Lights: `onToggleLight(worldobjects, light, playerNum)` (`:1328`) → `ISToggleLightAction:new(character,
  object)`; held lights `ISInventoryPaneContextMenu.onActivateItem(light, playerNum)` (`:2880`).

### 11. Medical care beyond bandages
Health-panel handlers in `client/XpSystem/ISUI/ISHealthPanel.lua:1162-1735`; the timed actions take
`(character, otherPlayer, …)`, with the character as its own patient:
`ISApplyBandage:new(character, otherPlayer, item, bodyPart, doIt)`, `ISDisinfect:new(character,
otherPlayer, alcohol, bodyPart)`, `ISStitch:new(character, otherPlayer, item, bodyPart, doIt)`,
`ISSplint:new(character, otherPlayer, rippedSheet, plank, bodyPart, doIt)`, `ISRemoveGlass:new(character,
otherPlayer, bodyPart, handPain)`, `ISRemoveBullet:new(character, otherPlayer, bodyPart)`,
`ISCleanBurn:new(character, otherPlayer, bandage, bodyPart)`, `ISTakePillAction:new(character, item)`.
Removing bandages/stitches/splints goes through the same panel classes (`HRemoveBandage`, `HRemoveStitch`,
`HRemoveSplint`); their actions were not read (**unverified** signatures).

### 12. Reading
`ISInventoryPaneContextMenu.onLiteratureItems(items, playerNum)` (`:2804`) → `readItem` →
`ISReadABook:new(character, item)`. Menu conditions (`doLiteratureMenu`, `:1030`): not
`tooDarkToRead()`, not Illiterate (unless a picture book), skill book level ≤ perk level + 1 and above the
max level, not asleep.

### 13. Continuous movement and stance
No key injection exists (`J:zombie.input.GameKeyboard` only reads). Exposed setters on the player:
`setAutoWalk(boolean)` + `setAutoWalkDirection(Vector2)` (the repo already uses them in `A.stepOff`),
`setRunning`, `setSprinting`, `setSneaking`, `setIsAiming`, `faceLocation(float, float)`,
`setForwardDirection(float, float)`. `setForceRun/setForceSprint/setForceAim` are default methods of
`CharacterInputComponentEntity` that `IsoPlayer` should inherit (callable by the exposure rule;
**unverified** in game). **Live test** whether auto-walk respects collisions, stops on obstacles, and
how often the direction must be refreshed.

### 14. Barricading, doors and window variants
Barricade (cursor, see 9) and `ISBarricadeAction:new(character, item, isMetal, isMetalBar)`; unbarricade
`onUnbarricade(worldobjects, window, playerNum)` (`:2136`) → `ISUnbarricadeAction:new(character, item)`;
lock/unlock doors `onLockDoor(worldobjects, playerNum, door)` (`:1514`), `onUnLockDoor(worldobjects,
playerNum, door, doorKeyId)` (`:1521`); climb over fences `onClimbOverFence(worldobjects, fence, direction,
playerNum)` (`:2347`) → `ISClimbOverFence:new(character, item, direction)`; add sheet `onAddSheet`
(`:2193`) → `ISAddSheetAction:new(character, item)`; door curtains and window frames (catalogue 3.1).

### 15. Vehicles beyond entering
Switch seat `ISSwitchVehicleSeat:new(character, seatTo, seatFrom)`; headlights
`ISVehicleMenu.onToggleHeadlights(playerObj)` (`:1114`); refuel
`ISAddGasolineToVehicle:new(character, part, item, otherItems)`, siphon
`ISTakeGasolineFromVehicle:new(character, part, item, otherItems)`, pump
`ISRefuelFromGasPump:new(character, part, fuelStation)`; parts `ISInstallVehiclePart:new(character, part,
item, maxTimeInit)`, `ISUninstallVehiclePart:new(character, part, workTime)`; vehicle containers through the
loot window's vehicle branch (`BaseVehicle:canAccessContainer(partIndex, player)`).
**Driving has no verified Lua path**: `J:CarController.updateControls` reads the keyboard directly and
`CarController` is not exposed. Candidates on `BaseVehicle` (exist): `setRegulator(boolean)`,
`setRegulatorSpeed(float)`, `setCurrentSteering(float)`, `setForceBrake()`. **Live test** whether they
drive the car or are overwritten each update; otherwise driving needs a different input route.

## P2: breadth

16. Crafting window recipes not tied to one item (`client/ISUI/Crafting/ISHandcraftWindow.lua`), "All"
    quantities (`OnNewCraft(item, recipe, playerNum, true)`), evolved recipes
    (`onAddItemInEvoRecipe(recipe, baseItem, usedItem, playerNum)`, `:2372`).
17. Repairs with fixers (`ISInventoryPaneContextMenu.buildFixingMenu`, `:2393` → `onFix`, `:2512`),
    tailoring (`repairClothing`, `:1625`), weapon upgrades.
18. Generators, appliances, plumbing, fuel (catalogue 3.4-3.5).
19. Farming, foraging (`ISSearchManager:toggleSearchMode(bool)`,
    `client/Foraging/ISSearchManager.lua:1416`), fishing (`client/Fishing/FishingHandler.lua`), trapping,
    animals (catalogue 3.6).
20. Building and disassembly (`ISDisassembleMenu.createMenu(worldObjects, context, playerObj)`,
    `client/ISUI/ISDisassembleMenu.lua:3`), moveables.
21. Firearms (`client/ISUI/ISFirearmRadialMenu.lua`, `ISInventoryPaneContextMenu.doReloadMenuForWeapon`,
    `:1876`), hotbar (`ISHotbar:attachItem(item, slot, slotIndex, slotDef, doAnim)`,
    `client/Hotbar/ISHotbar.lua:348`; `activateSlot(slotIndex)`, `:548`), shout (`IsoGameCharacter:Callout()`).
22. Map (`ISWorldMap.ShowWorldMap(playerNum, centerX, centerY, zoom)`, `:1500`; sandbox
    `Map.AllowWorldMap`), radio/TV, alarm clock, appearance and hair.
23. New-game flow from the main menu (BACKLOG item 1): `client/OptionScreens/NewGameScreen.lua`,
    `WorldSelect.lua`, `MapSpawnSelect.lua`, keeping the sandbox and display settings unchanged.

## Not covered here
Hearing (no capture source; see PHASE3_COVERAGE.md), and anything that changes game settings or speed.
