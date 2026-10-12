# Action catalogue: Project Zomboid 42.21.0 player actions vs the gym (2026-10-11)

This lists the normal player actions in the installed build and says, for each, where the game implements it,
what it needs, and what the gym does with it. It is the action half of the Phase 3 audit; perception is in
[OBSERVATION_AUDIT.md](OBSERVATION_AUDIT.md) and the ordered work list is in [GAP_LIST.md](GAP_LIST.md).
Nothing in this file was run in the game: it comes from reading the installed files (see "Evidence").

## Evidence and conventions

* **Game files read**: `D:/Program Files/steamapps/common/ProjectZomboid/media/lua/**` (paths below are
  relative to `media/lua/`) and `projectzomboid.jar`. Every class in the jar (23,829) was indexed with a
  small class-file reader (methods, signatures, annotations, constant-pool strings), and the classes cited
  here were disassembled with `javap -c` (JDK 11 reads the build's class version 69). Java sources are cited
  as `J:class.method`; offsets refer to the `javap` listing.
* **Which Java methods Lua can call** (verified in `J:se.krka.kahlua.integration.expose.LuaJavaClassExposer`):
  for each class in `LuaManager$Exposer`'s list, `exposeMethods` registers every method from
  `Class.getMethods()` that is public, non-static and not annotated `@zombie.HiddenFromLua`. Inherited public
  methods therefore work on an exposed subclass: `IsoPlayer:setDoShove` is declared in the unexposed
  `IsoLivingCharacter` and is still callable (vanilla `shared/TimedActions/ISReloadWeaponAction.lua:433`
  calls `character:isDoShove()`). Instance fields (e.g. `IsoGameCharacter.isVisibleToPlayer`) are not
  readable from Lua.
* **Status** of each action in this repo:
  * **covered**: offered with the game's prerequisites and parameters, through the same callback or timed
    action a player triggers;
  * **partial**: offered, but some parameters, variants or prerequisites differ, or a different but working
    path is used;
  * **wrong**: the call or its preconditions disagree with the installed game so that the option fails,
    or is offered where the game would not allow it;
  * **missing**: not offered.
  Repo references are `file:line` under `mod/AIvZ/42/media/lua/client/` unless a directory is given.
* "**not audited**" in the prerequisites column means the option was found in the source but its
  conditions were not read line by line; "**unverified**" means a claim that could not be checked in the
  installed files.

## 1. How a player's choice reaches the game (verified)

* Right-click menus are `ISContextMenu` tables. `client/ISUI/ISContextMenu.lua:50` (`onMouseUp`) calls
  `option.onSelect(option.target, option.param1 … option.param10)` unless the option is `notAvailable` or
  disabled. `addGetUpOption` (`:1038`) wraps the callback so a sitting character stands first.
* **The B42.21 world menu is built in Java.** `client/ISUI/ISWorldObjectContextMenu.lua:143`
  (`createMenu`) returns early when the game is paused, the world map is open, the character is asleep, or a
  trade window is open; it calls `J:zombie.iso.ISWorldObjectContextMenuLogic.fetch` on each clicked object
  and then `J:ISWorldObjectContextMenuLogic.createMenuEntries`, which adds about 170 option call sites through
  `J:zombie.ui.ISUIWrapper.ISContextMenuWrapper.addOption/addGetUpOption` and names the Lua callbacks as
  strings (`LuaManager.getFunctionObject("ISWorldObjectContextMenu.onOpenCloseDoor")`). It then fires
  `OnFillWorldObjectContextMenu`, whose handlers add the vehicle, foraging, hutch, feeding-trough, build and
  corpse-storage entries. `client/Context/ISMenuContextWorld.lua:41` also refuses when dead, asleep, paused
  or fishing.
* **Only drawn objects can be clicked.** `J:zombie.iso.IsoObjectPicker.ContextPick` skips objects whose
  `getTargetAlpha(0) == 0` (offset 128) and wall-type tiles below full alpha; B42 normally takes the
  `J:FBORenderObjectPicker.ContextPick` branch (`PerformanceSettings.fboRenderChunk`), not disassembled
  (unverified).
* **Inventory menus are Lua**: `client/ISUI/ISInventoryPaneContextMenu.lua:26` (`createMenu`), also refused
  while paused. Its recipe and opening checks use `ISInventoryPaneContextMenu.getContainers(player)`
  (`:2425`): the inventory window's and the loot window's current containers.
* **The loot window defines "within reach".** `client/ISUI/ISInventoryPage.lua:1537` (`refreshBackpacks`)
  lists the 3x3 squares around the character that `currentSquare:canReachTo(square)` allows: floor items
  (`getWorldObjects`), corpses (`getStaticMovingObjects`), object containers and adjacent vehicle parts.
  `checkExplored` (`:1511`) **fills a container with loot the first time it is listed**
  (`ItemPicker.fillContainer`) and marks it explored. Unexplored containers are empty until then.
* Most actions are timed actions queued with `ISTimedActionQueue.add`; walking to the target uses
  `ISWalkToTimedAction`/`luautils.walkAdj*`, which the repo replaces with `ISPathFindAction` for speed
  reasons recorded in [PHASE3_VERIFICATION.md](PHASE3_VERIFICATION.md).

## 2. Controls (keyboard and mouse)

Bindings from `shared/keyBinding.lua`; keyboard state is read in Java through
`J:zombie.characters.CharacterInputKeyBinding` and `J:zombie.characters.component.CharacterInputComponent`
(`isForwardKeyDown`, `isRunButtonDown`, `isSprintButtonDown`, `isCrouchButtonDown`, `isAimKeyDownInternal`,
`isMeleeButtonDownInternal`, `isAttackButtonDown`, `isInteractButtonDownInternal`, `isWalkToButtonDown`,
`isCancelActionButtonDown`, `isManualFloorAtkButtonDown`, `isReloadWeaponButtonPressed`,
`isRackFirearmButtonPressed`). There is no Lua method that injects key state: `J:zombie.input.GameKeyboard`
only reads it.

| Control (default key) | Vanilla source | Parameters / prerequisites | Repo status |
|---|---|---|---|
| Move (W A S D) | `CharacterInputComponent.getInputMoveVector`; facing follows the mouse | Continuous 2D vector, any time; facing is continuous | **partial**: `walk` in 8 directions to the farthest free square ≤12 tiles, by pathfinding (`AIvZGym.lua:296-300`, `:604-613`). No continuous vector, no facing control. Candidate APIs: `IsoGameCharacter:setAutoWalk(boolean)` + `setAutoWalkDirection(Vector2)` (used by the repo's `A.stepOff`, `AIvZ.lua:1003-1004`), `faceLocation(float,float)`, `setForwardDirection(float,float)` (all verified to exist) |
| Run (L-Shift, hold or toggle) | `CharacterInputComponent.isRunButtonDown`, `toggleForceRun` | Not while exhausted (not audited) | **partial**: `run` = `setRunning(true)` + pathfind (`AIvZGym.lua:608`, `:614`) |
| Sprint (L-Alt) | `CharacterInputComponent.isSprintButtonDown` | Endurance; `CANT_SPRINT` moodle | **missing** (`IsoGameCharacter:setSprinting(boolean)` exists) |
| Crouch / sneak (C) | `CharacterInputComponent.isCrouchButtonDown`; `J:IsoPlayer.updateSneakKey` toggles `setSneaking(!isSneaking())` | — | **covered** since gym 0.4.25 (2026-10-12, not yet run in the game): `sneak` when standing, `stand` when sneaking, not in a vehicle; it stays while walking. `sleep` still stands up first. |
| Interact (E): open/close door or window, climb (hold), grab corpse (hold) | `J:IsoPlayer.doContextNSWE(dir)`, toward the facing direction, in this order: sheet rope, door/window/frame, hutch, butcher hook, animal, rest on furniture, curtain (Shift), throw a grabbed corpse, hop a fence, climb a tall fence | Adjacent object | **partial**: doors, windows, curtains and fences (gym 0.4.33) through the actions below; sheet rope, rest on furniture and the animal entries **missing** |
| Walk to (Y) | `ISWorldObjectContextMenu.onWalkTo` (`client/ISUI/ISWorldObjectContextMenu.lua:2545`) → `ISWalkToCursor` | Any reachable square | **partial**: only directions, rooms and buildings (`AIvZGym.lua:296-353`) |
| Cancel action (Esc) | `CharacterInputComponent.isCancelActionButtonDown`; `ISPathFindAction:update` stops on it | — | **partial**: choosing any other option clears the queue (`AIvZGym.lua:563-567`, `:843`); no explicit cancel |
| Sit on ground (unbound) | `shared/TimedActions/ISSitOnGround.lua` / `ISWorldObjectContextMenu.onSitOnGround` (`:2835`) | Not in a vehicle, not already sitting (`createMenuEntries` offsets 3745-3800) | **covered**: `rest` reports `EventSitOnGround` like the menu; gym 0.4.32 applies these prerequisites. Ground-rest animation completion is not yet checked by the executor. |
| Get up from ground or furniture | `shared/TimedActions/ISWaitWhileGettingUp.lua`; `client/ISUI/ISContextMenu.lua:onGetUpAndThen` (`:1046`); `client/TimedActions/ISTimedActionQueue.lua:addGetUpAndThen` (`:229`) | Sitting; wait for the game's getting-up animation | **covered in code** since gym 0.4.41 / mod 0.5.8: `get_up`, plus the menu's get-up prerequisite before common movement paths. `stand` only ends sneaking. Installed compiler/method checks pass; see [sitting check](SITTING_CHECK.md) for live evidence and remaining verification. |
| Attack (LMB, with aim) | Java combat (`J:zombie.CombatManager`) | Weapon, endurance, charge | **partial**: `attack` paths to a visible zombie and calls `A.swing` → `IsoPlayer:DoAttack(0)` (`AIvZGym.lua:635-653`, `AIvZ.lua:797-808`); no free aim or charge |
| Aim (Ctrl / RMB) | `CharacterInputComponent.isAimKeyDownInternal` | — | **partial**: only inside `attack`/`shove` (`setIsAiming(true)`) |
| Melee / shove (Space) | `isMeleeButtonDownInternal` | — | **partial**: `shove` = `setDoShove(true)` + `DoAttack(0)` (`AIvZGym.lua:654-664`) |
| Floor attack (L-Alt) | `J:CombatManager.calculateAttackVars` (reads `MANUAL_FLOOR_ATTACK`) | Target on the floor | **partial**: automatic `setAimAtFloor` for downed zombies (`AIvZ.lua:801-802`) |
| Reload (R), rack (X), sharpen (R) | `client/ISUI/ISFirearmRadialMenu.lua`, `shared/TimedActions/ISReloadWeaponAction.lua` | Firearm/ammo or sharpenable blade | **missing** |
| Shout (Q) | `IsoGameCharacter:Callout()` (verified); `client/ISUI/ISEmoteRadialMenu.lua` | — | **missing** |
| Emote wheel (Q hold) | `client/ISUI/ISEmoteRadialMenu.lua` | — | **missing** |
| Light source (F) | `client/ISUI/ISLightSourceRadialMenu.lua`, `server/Items/ItemBindingHandler.lua` | Torch/lighter etc. | **missing** |
| Hotbar slots (1-8) | `client/Hotbar/ISHotbar.lua:548` (`activateSlot`) → `equipItem` (`:575`) | Item attached to a slot | **missing** |
| Drop held items / worn bag, grab corpse (unbound by default) | `client/Farming/CFarming_Interact.lua`, `shared/TimedActions/ISGrabCorpseAction.lua` | — | **missing** (single drop exists, see 4) |
| Vehicle: start engine (N), brake (Space), cruise control (Shift), headlights (F), heater (O), mechanics (U), horn (Q), radial (V), switch seat (Z) | `client/Vehicles/ISUI/ISVehicleMenu.lua` (`onKeyPressed` `:1644`), `J:zombie.core.physics.CarController.updateControls` | See section 6 | **partial**: engine on/off only (`AIvZGymActions.lua:150-201`) |
| Drive: throttle, reverse, steer (W S A D) | `J:CarController.updateControls` reads `GameKeyboard.isKeyDown(FORWARD/BACKWARD/LEFT/RIGHT/BRAKE/CRUISE_CONTROL)` directly | Continuous | **missing**. `CarController` is not exposed to Lua. Candidates on the exposed `BaseVehicle`: `setRegulator(boolean)`, `setRegulatorSpeed(float)`, `setCurrentSteering(float)`, `setForceBrake()` (exist; whether `updateControls` overrides them each tick is **unverified**) |
| Open panels: inventory (I), skills (L), health (H), info (J), protection (P), crafting (B), building, map (M), survival guide (F1), moveable info (]) | `client/ISUI/ISInventoryPage.lua`, `server/XpSystem/XpUpdate.lua`, `client/ISUI/Crafting/ISHandcraftWindow.lua`, `client/ISUI/Building/ISBuildWindow.lua`, `client/ISUI/Maps/ISWorldMap.lua` | Map: sandbox `Map.AllowWorldMap`, light if `Map.MapNeedsLight` (`ISWorldMap.lua:1491-1603`) | **missing** as actions; the panels' information is covered in OBSERVATION_AUDIT.md |
| Rotate / toggle mode in cursors (R, Tab) | `server/BuildingObjects/ISMoveableCursor.lua:147` (`setMoveableMode`) | Build or move cursor active | **missing** |
| Zoom, pan camera | `CharacterInputComponent.isZoomIn/OutButtonPressed` | Changes what is on screen | not an action; noted because zoom changes what a player can see |
| Pause and speed (F2-F6) | `UIManager.getSpeedControls()` | — | excluded: the user owns game speed (README) |

## 3. World right-click menu

Java builders are in `J:zombie.iso.ISWorldObjectContextMenuLogic`; Lua callbacks in
`client/ISUI/ISWorldObjectContextMenu.lua` unless stated. "Walk" means the callback walks next to the object
first (`luautils.walkAdj*`).

### 3.1 Doors, windows, curtains, fences, barricades

| Action | Vanilla source | Prerequisites / parameters | Repo status |
|---|---|---|---|
| Open / close door | `doDoorMenu` → `onOpenCloseDoor` (`:2400`: `CancelAction`, walk, `ISOpenCloseDoor:new(player, door)`) | Option is `notAvailable` with tooltip "Door Is Locked" when `ILockableDoor:couldBeOpen(player)` is false (offsets 480-525) | **partial**: `door` (`AIvZGym.lua:363-366`, `:669-675`) calls `ISOpenCloseDoor:new` (signature verified) after `ISPathFindAction`. It reports `locked = isLocked()` instead of `couldBeOpen(p)`, offers locked doors as selectable, and scans only 4 doors within 8 tiles |
| Lock / unlock door | `doDoorMenu` → `onLockDoor` (`:1514`) / `onUnLockDoor` (`:1521`) | Door closed, key in inventory (`haveThisKeyId`), `isLockedByKey` | **covered** since gym 0.4.26 (2026-10-12, not yet run in the game): `lock_door` / `unlock_door` on a closed door whose key (`checkKeyId()` for `IsoDoor`, else `getKeyId()`) is in the inventory, `ISLockDoor:new(character, door, lock)` after the mod's walk next to it. |
| Open / close window | `doWindowMenu` → `onOpenCloseWindow` (`:2279`) → `ISOpenCloseWindow:new(player, window)` | Close: open, not smashed, no barricade. Open: closed, not smashed, no barricade, sprite lacks `WindowLocked` (offsets 732-977). A window locked by `isLocked()` still shows "Open" | **partial**: `window` (`AIvZGym.lua:367-371`, `:676`) uses the same action; it adds a `locked` field the menu does not show (see OBSERVATION_AUDIT.md) |
| Smash window | `doWindowMenu` (offset 1069) → `onSmashWindow` (`:2367`) → `ISSmashWindow:new(player, window)` | Closed, not smashed, not barricaded | **partial**: `smash` (`AIvZGym.lua:375`, `:701-703`) is also offered for open windows |
| Remove broken glass | `doWindowMenu` → `onRemoveBrokenGlass` (`:2374`) → `ISRemoveBrokenGlass:new(player, window)` | Smashed, glass not removed; `notAvailable` without an item in the primary hand (offset 296-329) | **partial**: `clear_glass` (`AIvZGym.lua:376`, `:704-706`) ignores the primary-hand requirement |
| Climb through window | `doWindowMenu` → `onClimbThroughWindow` (`:2355`) → `ISClimbThroughWindow:new(player, window, 0)` | `IsoWindow:canClimbThrough(player)`; special case when trapped next to it | **covered** for `IsoWindow` (`AIvZGym.lua:372-374`, `:696-700`); window frames and thumpable windows (`doThumpableWindowFrameMenu`) **missing** |
| Throw corpse through window / over fence | `doWindowMenu` (offset 689), `doHoppableMenu` → `onThrowCorpseThroughWindow` (`:2394`), `onThrowCorpseOverFence` (`:2388`) | Dragging a corpse | **missing** |
| Climb over fence / low wall | The Interact key only in 42.21 (`doHoppableMenu` adds no climb entry, just Throw corpse over fence): `J:IsoPlayer.doContextNSWE` → `doContextHopOverFence(dir)` → `ContextualActionHandlers.ClimbOverFence` (`client/TimedActions/ISContextualActions.lua:3`) → `onClimbOverFence` (`:2347`) → `ISClimbOverFence:new(character, fence, dir)`; tall fences `doContextClimbOverWall` → `IsoPlayer:climbOverWall(dir)` | `HoppableN`/`HoppableW` on the character's square (climbing N/W) or the next square S/E (climbing S/E), fence from `getHoppable(north)`; tall: `TallHoppableN/W` and `canClimbOverWall(dir)`; a tap refuses a drop beyond (`isSafeToClimbOver`), a held key allows it | **covered** since gym 0.4.33 (loaded live from 15:12 to 15:16 on 2026-10-12 as part of an unmerged branch: offered in 340 decisions, chosen 45 times, and every time the next decision replaced it before the climb; a third of the offers were tall fences): `climb_fence` for fence edges on squares in sight within 6 tiles (nearest 4, two per direction), with `dir`, `tall` and `drop`; the mod walks to the square on its side, then queues `ISClimbOverFence` (low) or calls `climbOverWall` (tall). A tall fence next to the character is offered only when `canClimbOverWall` allows it |
| Open / close curtain | `doWindowMenu` (offsets 1403-1566), `doDoorMenu` (offset 133) → `onOpenCloseCurtain` (`:2255`) → `ISOpenCloseCurtain:new(player, curtain)` | Curtain on window, frame or door; Shift-click | **covered** for window and door curtains since gym 0.4.33 (doors not yet run in the game): `curtain`, with `door` for a sheet on a door (`IsoDoor:HasCurtains()` returns the door, `isCurtainOpen()`), drawn from `getSheetSquare()` with `restoreDoor` after the walk, as the menu does; window frames **missing** |
| Add sheet / remove curtains | `onAddSheet` (`:2193`), `addRemoveCurtainOption`/`onRemoveCurtain` (`:2235`) | Sheet in inventory (window: `HasCurtains()` nil; door: also `canAddCurtain()`); room for a sheet (`hasRoomFor`, `Base.Sheet` weight) when removing | **covered** since gym 0.4.26 (windows) and 0.4.33 (doors, removing; not yet run in the game): `hang_sheet` on a window or a door, `remove_sheet` on the 2 nearest curtains, as `onAddSheet` / `onRemoveCurtain` do it with the mod's walk (a door's from the free sheet square only, as the menu) |
| Add / remove escape rope | `doSheetRopeOptions` (`:2985`), `onAddSheetRope` (`:2289`), `onRemoveSheetRope` (`:2323`) | Sheet rope/rope count `countAddSheetRope`; hammer + nails unless `TieSheetRope` | **missing** |
| Climb sheet rope | `createMenuEntries` offset 2145 → `onClimbSheetRope` (`:2177`) | `IsoPlayer:canClimbSheetRope`, Strength perk | **missing** |
| Barricade (planks / metal sheet / metal bars) | `doBarricadeMenu`, `doBarricadeOption` → `onBarricade` (`:3046`) | Hammer, plank + nails; or blowtorch + welding rods + Metal Welding; `notAvailable` when `IsoPlayer:tooDarkToRead()` | **partial** in gym 0.4.36 (2026-10-12, not yet run in the game): `barricade` with planks, for the nearest doors and windows, when `J:ISWorldObjectContextMenuLogic.doBarricadeMenu` would list it (`isBarricadeAllowed()`; no barricade on the character's side or `canAddPlank()`; a `HAMMER`-tagged tool not broken, `containsTypeRecurse("Plank")`, `getItemCountRecurse("Base.Nails") >= 2`; not `tooDarkToRead()`; a door only shut, `BuildRecipeCode.barricade.OnIsValidPlanks`). `onBarricade("carpentry_01_8")` hands the build cursor an `ISBuildIsoEntity` for the `BarricadePlanks` entity (`scripts/generated/entities/barricades/entity_barricade_planks.txt`: hammer kept, 1 plank, 1 nail, `BuildWallHammer`); the gym builds one the same way, sets the face from the side it walks to (`nSprite` 1-4, `ISBuildIsoEntity:getFace`), checks `isValid` and calls `ISBuildingObject.tryBuild` after the mod's walk. Not yet: metal sheet and metal bars |
| Unbarricade (planks / metal / bars) | `doDoorMenu`, `doWindowMenu`, `doThumpableMenu` → `onUnbarricade` (`:2136`), `onUnbarricadeMetal` (`:2145`), `onUnbarricadeMetalBar` (`:2153`) | Planks: a `REMOVE_BARRICADE`-tagged tool not broken (`predicateRemoveBarricade`, `ISWorldObjectContextMenu.lua:138`) and planks on the character's side (`getBarricadeForCharacter`, `getNumPlanks() > 0`); metal: blowtorch (`checkBlowTorchForBarricade`) | **partial** in gym 0.4.36 (not yet run in the game): `unbarricade` for planks, as `onUnbarricade` does it after the mod's walk (`ISWorldObjectContextMenu.equip` with the tool, `ISUnbarricadeAction:new(character, item)`, one plank a time). Not yet: metal |
| Use / remove padlock, combination padlock | `doPadLockMenu` → `onPutPadlock` (`:1610`), `onRemovePadlock` (`:1618`), `onPutDigitalPadlock` (`:1569`), `onRemoveDigitalPadlock` (`:1544`) | Padlock and its key / code dialog | **missing** |
| Pick up broken glass | `createMenuEntries` offset 1155 → `onPickupBrokenGlass` (`:2381`) | Glass on the ground | **missing** |

### 3.2 Items, corpses and the ground

| Action | Vanilla source | Prerequisites / parameters | Repo status |
|---|---|---|---|
| Grab one / half / all of an item on the ground | `handleGrabWorldItem` → `onGrabWItem` (`:1436`), `onGrabHalfWItems` (`:1448`), `onGrabAllWItems` (`:1466`) | Item visible on a square without a wall between (`isWallTo`) | **covered** in gym 0.4.35 (2026-10-12; one item seen working in the game, 859 times that evening): `pick_up` grabs one item on a square in sight within 8 tiles, with `ISGrabItemAction:new(character, worldItem, grabItemTime)` after the mod's walk onto the square or next to it. The items of one name on a square are one entry, as `J:ISWorldObjectContextMenuLogic.handleGrabWorldItem` groups them (`getItem():getName()`), the nearest 6 entries; a pile of more than one also gets `how` "all", more than two "half" (`ceil(n / 2)`, as `onGrabHalfWItems` counts), one `ISGrabItemAction` per item. Not yet: the `isWallTo` check |
| Extended 3D placement | `handleGrabWorldItem` → `onExtendedPlacement` (`:331`) | Item on the ground | **missing** |
| Grab / drop corpse | `handleGrabWorldItem` (offsets 51, 527) → `onGrabCorpseItem` (`:1488`), `handleGrabWorldItem_onDropCorpse` (`:249`) | Not in a vehicle; Interact hold also works | **covered** in gym 0.4.35 (mod 0.5.6, not yet run in the game): `drag_corpse` for the nearest 2 corpses in sight, as `handleGrabCorpseSubmenu` allows (not an animal, not from a vehicle, no `Base.CorpseMale` carried, no fire on the square), queued as `onGrabCorpseItem` does (`ISPathFindAction:pathToGrabCorpse`, the hands emptied, `ISGrabCorpseAction`); done when `isDraggingCorpse()`. `drop_corpse` while dragging: `setDoContinueGrapple(false)`. `ISTimedActionQueue.add` refuses any action without `allowedWhileDraggingCorpses` while dragging (`client/TimedActions/ISTimedActionQueue.lua:164`); the mod's walk sets it, as `ISWalkToTimedAction:new` does. `obs.dragging` |
| Loot a corpse | Loot window lists `IsoDeadBody` containers (`ISInventoryPage.lua` `refreshBackpacks`) | Adjacent, reachable | **partial** since gym 0.4.27 (not yet run in the game): corpses on squares in sight are containers of type `corpse` for `search` (which fills them as `ISInventoryPage:checkExplored` does) and then `take`; walked to with the mod's walk. A bag lying on the ground is a container of type `bag` too (gym 0.4.35, not yet run in the game): `refreshBackpacks` lists a floor item of category "Container" by its `getInventory()`, without `checkExplored`, so `search` doesn't fill it; walked to at its square (`getContainingItem():getWorldItem()`) |
| Burn corpse | `doBurnBodyMenu` → `onBurnCorpse` (`:1634`) | `START_FIRE` tag item, lighter or matches; fuel (not audited) | **missing** |
| Dig graves / bury corpse / fill grave | `doShovelAndRackMenu`, `doBuryCorpseMenu` → `onDigGraves` (`:2760`), `onBuryCorpse` (`:2767`), `onFillGrave` (`:2785`) | Shovel-type item (`DIG_GRAVE` tag) in hand; grave capacity 5; distance check | **missing** |
| Drop corpse into / grab corpse from a container | `shared/BodyDragging/corpseStorageCheck.lua:73`, `:171` | Dragging a corpse; suitable container | **missing** |
| Remove ground cover / ore / stump | `prePickupGroundCoverItem` → `onPickupGroundCoverItem` (`:2849`); `onRemoveGroundCoverItemHammerOrPickAxe` (`:2873`); `onRemoveGroundCoverItemPickAxe` (`:2865`) | Pickaxe/hammer as listed | **missing** |
| Rake / pick up dung | `createMenuEntries` offset 3664, `doShovelAndRackMenu` → `onRakeDung` (`:2844`) | `TAKE_DUNG` tag in hand | **missing** |
| Clean stains / remove graffiti | `doCleaningMenu` → `onCleanBlood` (`:2415`), `onCleanGraffiti` (`:2461`) | Bleach or cleaning liquid (graffiti: petrol) and a `CLEAN_STAINS` tool | **missing** |
| Gardening: scythe grass, remove grass, remove bush, remove wall vine | `doGardeningSubmenu` → `onScytheGrass` (`:2839`), `onRemoveGrass` (`:2521`), `onRemovePlant` (`:2499`) | Scythe; cutting tool for bushes (predicates not audited) | **missing** |
| Chop tree | `doTreeMenu` → `onChopTree` (`:833`) | Unbroken item with tag `CHOP_TREE` (`lambda$doTreeMenu$0`) | **missing** |
| Destroy (sledgehammer) | `doDestroyMenu` → `onDestroy` (`:822`) | Sledgehammer (not audited) | **missing** |
| Disassemble furniture/fixtures | `client/ISUI/ISDisassembleMenu.lua:3` (`createMenu`) → `disassemble` (`:83`) | Moveable with scrap definition and the tools it names | **partial** since gym 0.4.29 (2026-10-12, not yet run in the game): `disassemble` for objects in sight within 3 tiles that the menu lists and allows (`canScrapObject(...).craftValid` and `.canScrap`, nearest 4 of 8 checked), with the menu's success chance; the mod walks next to it, then `ISDisassembleMenu.disassemble` equips the tools and queues `ISMoveablesAction` "scrap". Objects further away are not offered yet |
| Pick up / place / rotate / scrap furniture | `client/ISUI/ISMoveableContextMenu.lua:13`, `server/BuildingObjects/ISMoveableCursor.lua:147` | Weight, tools per object | **missing** |
| Walk to | `createMenuEntries` offset 3828 → `onWalkTo` (`:2545`) | — | **partial** (see section 2) |
| Sit on ground | `createMenuEntries` offset 3776 → `onSitOnGround` (`:2835`) | Not in vehicle, not sitting | **partial** (`rest`) |

### 3.3 Beds, furniture and sleep

| Action | Vanilla source | Prerequisites / parameters | Repo status |
|---|---|---|---|
| Rest on furniture | `doBedMenu` (offset 194) → `onRest` (`:915`) → `ISPathFindAction:pathToSitOnFurniture` + `ISRestAction` | Furniture square `isCanSee` or same room; not occupied | **missing** |
| Sleep (bed, ground, ground with pillow) | `doSleepOption` → `onSleep` (`:949`) → confirm dialog → `onConfirmSleep` (`:987`) → `onSleepWalkToComplete` (`:1034`) | `notAvailable` when fatigue ≤ 0.3 ("Not tired enough"), zombies visible/chasing/very close, slept within the last hour, pain ≥ 2 with fatigue ≤ 0.85, or panic ≥ 1 (Java offsets 238-512). Duration is set by the game from fatigue and bed quality | **wrong**: `sleep` (`AIvZGym.lua:467-473`, `:808-827`) calls `onConfirmSleep(nil, {internal="YES"}, pn, bed)` directly through `U.bedStep` (`AIvZ.lua:1646-1657`), skipping the fatigue and "too soon" checks, so the agent can lie down when a player could not. Beds are searched through the whole building (see observation audit) |
| Get on bed | `doBedOption` (`:2619`) → `onGetOnBed` (`:2632`) | Debug only (`[DEBUG]` labels) | excluded |

### 3.4 Water, fluids, washing

| Action | Vanilla source | Prerequisites / parameters | Repo status |
|---|---|---|---|
| Drink from a tap, sink, barrel, river | `doDrinkWaterMenu` → `onDrink` (`:2038`) → walk, `ISTakeWaterAction:new(player, nil, waterObject, waterObject:isTaintedWater())` | Water source; removes and re-wears a face mask | **partial**: `drink_tap` (`AIvZGym.lua:442-452`, `:762-773`) uses the same action (signature verified) but no mask handling; only the 5 nearest sources are considered before the visibility filter (`AIvZ.lua:688`) |
| Fill a container (one / all) | `doFillFluidMenu` → `onTakeWater` (`:2050`) | Empty/fillable container in inventory | **missing** |
| Wash yourself / clothing / all clothing / containers / weapons / bandages | `doWashClothingMenu` → `onWashYourself` (`:1819`), `onWashClothing` (`:1777`) | Water amount, soap optional | **missing** |
| Clean bandages (one / all) | `doRecipeUsingWaterMenu` → `CleanBandages.onCleanOne/Multiple/All` (`:1829-1885`) | Dirty bandages, water | **missing** |
| Fluid container info / transfer / add fluid from item / empty | `doFluidContainerMenu` → `onFluidInfo` (`:2803`), `onFluidTransfer` (`:2793`), `onAddFluidFromItem` (`:2128`), `onFluidEmpty` (`:2820`) | World fluid container | **missing** |
| Water dispenser with bottle | `onWaterDispenserBottle` (`:1390`) | Bottle | **missing** |
| Take fuel (pump) | `doFuelMenu` → `doFillFuelMenu` (`:1677`) → `onTakeFuelNew` (`:2102`) | Power (or sandbox), fuel left, container | **missing** |

### 3.5 Appliances, power, light, fire

| Action | Vanilla source | Prerequisites / parameters | Repo status |
|---|---|---|---|
| Light switch on/off, add/remove bulb, battery, battery connector | `doLightSwitchOption` (`:1210`) → `onToggleLight` (`:1328`), `onLightBulb` (`:1353`), `onLightBattery` (`:1378`), `onLightModify` (`:1365`) | Power; bulb/battery items | **missing** |
| Stove / microwave on/off, settings | `doStoveOption` → `onToggleStove` (`:1189`), `onStoveSetting` (`:1203`), `onMicrowaveSetting` (`:1196`); `client/ISUI/Fireplace/ISOvenUI.lua` | Power or fuel | **missing** |
| Washer / dryer / combo on/off and mode | `toggleClothingWasher`, `toggleClothingDryer`, `toggleComboWasherDryer` → `:1113`, `:1120`, `:1177`, `:1183` | Power, water | **missing** |
| Generator: info, on/off, connect/disconnect, fix, add fuel, take | `doGeneratorMenu` → `onInfoGenerator` (`:533`), `onActivateGenerator` (`:547`), `onPlugGenerator` (`:540`), `onFixGenerator` (`:554`), `onAddFuelGenerator` (`:565`), `onTakeGenerator` (`:665`) | Electrical ≥ 3 or known recipe "Generator"; fuel; scrap electronics to fix | **missing** |
| Car battery charger: on/off, connect/remove battery, take | `handleCarBatteryCharger` (`:444`) | Charger placed; battery | **missing** |
| Plumb a sink/object | `doWaterPipeMenu` → `onPlumbItem` (`:1528`) | Pipe wrench | **missing** |
| Extinguish fire | `doExtinguishFireMenu` → `onRemoveFire` (`:512`) | Extinguisher or water source item | **missing** |
| Clear ashes | `createMenuEntries` offset 1722 → `onClearAshes` (`:1626`) | Shovel-type item | **missing** |
| Campfire: info, add fuel (one / all / all that fit), light (petrol, literature, kindling), put out, remove, place corpse | `shared/Camping/ISCampingMenu.lua:155-424` | Fuel items, lighter/matches or notched plank + stick | **missing** |
| BBQ: info, on/off, insert/remove propane, extinguish | `client/ISUI/ISBBQMenu.lua:32-79` | Propane tank | **missing** |
| Thumpable light: toggle, insert/remove fuel | `onToggleThumpableLight` (`:895`), `onInsertFuel` (`:902`), `onRemoveFuel` (`:908`) | Lamp-type thumpable | **missing** |
| Radio / TV: device options | `handleInteraction` (offset 771) / `client/ISUI/ISRadioAndTvMenu.lua:8-34` → `client/RadioCom/ISRadioWindow.lua` | Device placed or held | **missing** |
| Compost: get / add | `handleCompost` (`:355`) → `onGetCompost` (`:496`), `onAddCompost` (`:504`) | Composter, rotten food / sack | **missing** |

### 3.6 Farming, foraging, fishing, trapping, animals

| Action | Vanilla source | Prerequisites / parameters | Repo status |
|---|---|---|---|
| Dig furrow, info, fertilise, compost, harvest, water (amounts), treat mildew/flies/slugs/aphids, remove, sow seeds | `client/Farming/ISUI/ISFarmingMenu.lua:122-1077` | Shovel/trowel or hands; seeds; water container | **missing** |
| Take sand / gravel / dirt / clay | `client/BuildingObjects/ISUI/ISInventoryBuildMenu.lua:82-98` | Empty sack, shovel | **missing** |
| Foraging: toggle search mode, pick up found items (one / half / all, into container) | `client/Foraging/ISSearchManager.lua:1416` (`toggleSearchMode`), `client/Foraging/ISBaseIcon.lua:83-138` | Not in vehicle | **missing** |
| Inspect animal track | `client/Foraging/ISAnimalTracksMenu.lua:4-15` | Track visible/found | **missing** |
| Fishing: open fishing window, cast/reel | `doFishingMenu` → `openFishWindow` (`:337`, `PZAPI.UI.FishWindow`), `client/Fishing/FishingHandler.lua` | Rod with line/hook/lure, water square | **missing** |
| Fishing net: place, check, remove, add bait; chum: make, add | `doFishNetOptions`, `doPlacedFishNetOptions`, `doChumOptions`, `doCreateChumOptions` → `:679`, `:783`, `:796`, `:802`, `:789`, `:349` | Net, bait, sand for chum | **missing** |
| Trap: add/discard bait, check, remove; disarm and take | `server/Traps/ISUI/ISTrapMenu.lua:35-77`; `doTrapMenu` → `onTakeTrap` (`:1481`) | Trap placed | **missing** |
| Animals: info, feed from hand, give water, attach/detach rope, attach to tree, milk, shear, pick up, lure, pet, kill; butcher body, get bones | `client/ISUI/Animal/ISAnimalContextMenu.lua:13-698` | Rope, bucket, shears, weapon, food | **missing** |
| Hutch: info, open/close doors, put animal in; grab eggs | `client/ISUI/Hutch/ISHutchMenu.lua:20-50`, `client/ISUI/Hutch/ISHutchUI.lua:153-458` | Hutch | **missing** |
| Feeding trough info; butcher hook | `client/FeedingTrough/ISUI/ISFeedingTroughMenu.lua:43-50`; `onButcherHook` (`:1396`) → `client/ISUI/Animal/ISButcherHookUI.lua` | Trough / hook placed | **missing** |
| Animal zone check | `ISAnimalContextMenu.lua:1052` | Designation zone | **missing** |

### 3.7 Building and crafting stations

| Action | Vanilla source | Prerequisites / parameters | Repo status |
|---|---|---|---|
| Build from the build menu / window | `client/Entity/ISUI/ISEntityBuildMenu.lua:42-87`, `client/ISUI/Building/ISBuildWindow.lua`, `ISInventoryPaneContextMenu.doBuildRecipeListForItem` (`:1302`) | Recipe known, materials, tools, skill, light; placement cursor (position, rotation) | **missing** |
| Open a crafting station (workbench, furnace…) | `client/Context/World/ISContextEntity.lua:23` (`openPanel`) | Entity with a crafting component | **missing** |
| Context-config custom entries on entities | `J:ISWorldObjectContextMenuLogic.doContextConfigOptions` → `ISWorldObjectContextMenu.onCustomFunction` (`:3042`) | Entity script defines them | **missing** |

### 3.8 Multiplayer-only (excluded)

Safehouse view/claim/war (`onViewSafeHouse` `:526`, `onTakeSafeHouse` `:517`, `onClaimWar` `:522`), other
players' medical check, wake up, trade and stats (`doClickedPlayerMenu`, `:860-889`). Not reachable in
singleplayer.

## 4. Inventory item right-click menu

Source `client/ISUI/ISInventoryPaneContextMenu.lua` unless stated; line numbers of the callbacks are in
brackets. The menu is built for the selected item(s) in the inventory or loot window.

| Action | Vanilla source | Prerequisites / parameters | Repo status |
|---|---|---|---|
| Wear (and clothing variants, e.g. hood up/down) | `doWearClothingMenu` (`:1777`) → `onWearItems` (`:2850`) → `wearItem` (`:2888`) → `ISWearClothing`; `doClothingItemExtraMenu` (`:4370`) | Clothing not broken, or wearable container; not already equipped | **partial**: `wear` (`AIvZGym.lua:427`, `:782-785`) calls `wearItem(item, playerNum)` (verified), at most 3 per decision, no extra options |
| Unequip / take off | `:637` → `onUnEquip` (`:2836`) → `unequipItem` (`:2843`) → `ISUnequipAction:new(char, item, 50)` | Equipped | **partial**: `unequip`/`take_off` (`AIvZGym.lua:403`, `:428`, `:778-789`) queue `ISUnequipAction:new(p, it, 50)` (signature verified) but skip the lit candle/lantern handling in `unequipItem` |
| Drop | `:642` → `onDropItems` (`:3810`) → `dropItem` (`:3831`) | In player inventory, not all favourites; in a vehicle needs an open door or window | **partial**: `drop` (`AIvZGym.lua:429`, `:737-740`) calls `dropItem(item, playerNum)` (verified) for at most 6 unworn items; not favourites (gym 0.4.32); in a vehicle only with the seat's door or its window open (gym 0.4.38, `createMenu` `:351-371`, `:641-651`; not yet run in the game) |
| Place item on the ground (one / half / all, 3D) | `doPlace3DItemOption` → `onPlaceItemOnGround` (`:4457`) | — | **missing** |
| Equip primary / secondary / both hands | `doEquipOption` (`:4129`) → `OnPrimaryWeapon` (`:3649`), `OnSecondWeapon` (`:3715`), `OnTwoHandsEquip` (`:3693`) → `equipWeapon` (`:3731`) | Any item except all-food, clothing and forced two-handers; unavailable if that hand has a deep wound or an unsplinted fracture | **partial**: `equip` (`AIvZGym.lua:426`, `:774-777`) only for `HandWeapon`, at most 3. Since gym 0.4.38 (not yet run in the game) as the menu lists it: Two Hands for a two-handed weapon with `getCondition() > 0` not already in both hands (`:426-429`), otherwise Primary while the right hand has no deep wound and no unsplinted fracture (`doEquipOption`). Not offered: Secondary |
| Take generator / grab corpse item | `:408` → `equipHeavyItem` (`:4157`); `:418` → `grabCorpseItem` | Not in a vehicle | **missing** |
| Eat all / half / quarter; Open and eat | `:494-518` → `onEatItems` (`:3777`) → `eatItem` (`:3579`); opening recipe through `HandcraftLogic` | Food with hunger change < 0 or an opening recipe the player can do; `notAvailable` when `FOOD_EATEN` ≥ 3; half/quarter by hunger size | **partial**: `eat` (`AIvZGym.lua:405-417`, `:742-752`) calls `eatItem(item, 1, playerNum[, opening, 100])` (signature verified): "All" only, at most 6 |
| Custom food command (Smoke, Drink…) | `doEatOption` (`:2121`) | Needs the item in `getRequireInHandOrInventory()` (an `ArrayList`) or an open flame | **partial**: offered only when nothing is required (`AIvZGym.lua:502`) |
| Take pills | `doPillsMenu` (`:1140`) → `onPillsItems` (`:3667`) | `CONSUMABLE` tag and drainable | **missing** |
| Drink fluid (all / half / quarter, open and drink) | `:437-444` → `doDrinkFluidMenu` (`:2276`) → `onDrinkFluid` (`:2258`) | Water sources only when thirst > 0.1; other fluids only if the primary fluid is `FluidCategory.Beverage` or `FluidType.Bleach`; `notAvailable` when sealed without opener, capacity > 3 L, or `FOOD_EATEN` ≥ 3 for nourishing fluids | **wrong**: `drink` (`AIvZGym.lua:418-424`, `:505-526`, `:753-761`) offers any fluid ≤ 3 L that `canPlayerEmpty()`, without the thirst or beverage rule, so non-beverage fluids can be drunk; "All" only |
| Pour on ground / dump contents | `:453` → `onDumpContents` (`:4100`) | `canReplaceStoreWater` | **missing** |
| Consolidate drainables | `checkConsolidate` (`:2153`) → `onConsolidate` (`:2192`), `onConsolidateAll` (`:2196`) | Several partial drainables | **missing** |
| Fluid: container info, transfer, empty, autodrink on/off | `client/ISUI/ISFluidContainerMenu.lua:9-37`, `client/Fluids/ISFluidTransferUI.lua` | Fluid container | **missing** |
| Read / look at pictures / reread | `doLiteratureMenu` (`:1030`) → `onLiteratureItems` (`:2804`) → `readItem` (`:2825`) | `notAvailable` when `tooDarkToRead()`, illiterate (unless picture book), skill book too hard (`getLvlSkillTrained > level + 1`) or too easy; asleep | **missing** |
| Inspect print media; check back cover (media) | `doPrintMediaMenu` (`:1007`), `onMediaText` (`:2974`) | Light, literate | **missing** |
| Read / write note | `:573-575` → `onWriteSomething` (`:2699`) | Pen/pencil to write; light; literate | **missing** |
| Read map / rename map | `:595-603` → `onCheckMap` (`:2661`), `onRenameMap` (`:2634`) | Light | **missing** |
| Research craft recipe | `:557` → `onResearchRecipe` (`:4561`) | Researchable recipes; light | **missing** |
| Craft from an item (one / all) | `addNewCraftingDynamicalContextMenu` (`:3365`) → `OnNewCraft` (`:3428`) | `CraftRecipeManager.getUniqueRecipeItems(item, player, containers)`; `HandcraftLogic` checks | **partial**: `craft` (`AIvZGym.lua:430-439`, `:528-560`, `:791-799`) uses the same list and `OnNewCraft(item, recipe, playerNum, false)` (verified), "One" only, at most 5, plus three named fallbacks; results are cached 600 ticks |
| Show recipes the item is used in / build recipes | `doRecipeListForItem` (`:1297`), `doBuildRecipeListForItem` (`:1302`) → `ISEntityUI.OpenHandcraftWindow/OpenBuildWindow` | — | **missing** |
| Add ingredient to an evolved recipe (soup, salad…) | `doEvorecipeMenu` (`:4233`) → `onAddItemInEvoRecipe` (`:2372`) | Base item + ingredient | **missing** |
| Inspect clothing | `:617` → `onInspectClothing` (`:1456`) | Clothing covering parts | **missing** |
| Tailoring: patch hole, add padding, remove patch | `doClothingPatchMenu` (`:1481`) → `repairClothing` (`:1625`), `removePatch` (`:1602`); `client/ISUI/ISGarmentUI.lua` | Needle, thread, fabric | **missing** |
| Wring out wet clothes / dry self with towel | `:859` → `onWringClothing` (`:2559`); `:885` → `onDryMyself` (`:2551`) | Wetness > 15 / wet character | **missing** |
| Dye hair / beard; make-up | `:888-891` → `onDyeHair` (`:2531`); `doMakeUpMenu` (`:4299`) → `client/ISUI/ISMakeUpUI.lua` | Hair dye ≥ 0.5; make-up item | **missing** |
| Apply bandage (choose body part) | `doBandageMenu` (`:1306`) → `onApplyBandage` (`:2772`) → `ISApplyBandage` | All selected items are bandages; damaged part | **partial**: `bandage` (`AIvZGym.lua:453-466`, `:800-807`) queues `ISApplyBandage:new(p, p, item, part, true)` (signature verified) with the first bandage found, at most 3 parts |
| Turn on / off (flashlight, lighter-type items) | `:866-879` → `onActivateItem` (`:2880`) | `canBeActivated`, in hand or attached, charge > 0 | **missing** |
| Repair item (fixers) | `:903-913` → `buildFixingMenu` (`:2393`) → `onFix` (`:2512`) | `FixingManager.getFixes`; fixer item and skill | **missing** |
| Weapon upgrade add / remove | `:760-791` → `onUpgradeWeapon` (`:3798`), `onRemoveUpgradeWeapon` (`:3789`) | Weapon part, tools | **missing** |
| Firearms: fire mode, insert/eject magazine, load/unload rounds, rack/unjam | `doChangeFireModeMenu` (`:1793`), `doReloadMenuForWeapon` (`:1876`), `doMagazineMenu` (`:1970`), `doReloadMenuForBullets` (`:1813`) | Ammo, magazine | **missing** |
| Traps and bombs: set timer, place, link/trigger/reset remote | `:793-831` → `onSetBombTimer` (`:2572`), `onPlaceTrap` (`:3785`), `OnLinkRemoteController` (`:2213`), `OnTriggerRemoteController` (`:2207`); `ISTrapMenu.onPlaceTrap` | Trap/bomb items | **missing** |
| Fishing rod: add/remove bait, change hook, change line | `addFishRodOptions` (`:1342`) | Rod and parts | **missing** |
| Install furniture (moveable item) | `client/ISUI/ISMoveableContextMenu.lua:13` | Moveable in inventory | **missing** |
| Alarm clock: set / stop | `:914-918` → `onSetAlarm` (`:2617`), `onStopAlarm` (`:2598`); `client/ISUI/ISAlarmClockDialog.lua` | Digital clock | **missing** |
| Device options (portable radio) | `:897` → `ISRadioAndTvMenu.openRadioPanel` | Radio in hand or on back | **missing** |
| Change recording (media) | `client/Context/Inventory/InvContextMedia.lua:16-23` | Recorded media | **missing** |
| Grab one / half / all (from loot) | `doGrabMenu` (`:4206`) | Item not in player inventory | **partial**: `take` (`AIvZGym.lua:383-400`, `:721-736`) moves one item from a searched container with `ISInventoryTransferUtil.newInventoryTransferAction(p, item, src, dest)` since gym 0.4.38, as the loot window does (it swaps in `ISGrabCorpseItem` for corpse items; before, `ISInventoryTransferAction:new`) to the worn backpack or the main inventory; at most 12 |
| Move to (inventory, worn bag, hand item, key ring, open container, floor) | `:655-730` → `onMoveItemsTo` (`:2978`), `onPutItems` (`:2897`) | `hasRoomForAny`; not favourites | **partial**: `stow` (`AIvZGymActions.lua:98-131`) moves one item between the main inventory, bags in it and searched containers within 2.5 tiles, 12 moves per decision rotating with the decision id; no floor destination, no key rings |
| Transfer all / take all / unpack | `:733-741` → `ISInventoryPage.transferAll` (`client/ISUI/ISInventoryPage.lua:209`), `lootAll` (`:205`) | — | **missing** |
| Put in container (loot) | `:925-929` → `onPutItems` (`:2897`) | Loot window shows a container | **partial** via `stow` |
| Favourite, unwanted, usable in recipes, rename bag, rename food | `doMoreContextMenu` (`:4614`) → `onFavorite` (`:2968`), `onWanted`/`onUnwanted` (`:4602-4608`), `onNoRecipes` (`:4596`), `onRenameBag` (`:2643`), `onRenameFood` (`:2652`) | — | **missing** |
| Hotbar: attach / remove | `client/Hotbar/ISHotbar.lua:139-164` → `attachItem` (`:348`), `removeItem` (`:325`) | Slot type matches item | **missing** |
| Animal in inventory: info, drop; animal corpse: butcher, bones | `client/ISUI/Animal/ISAnimalContextMenu.lua:13-16`, `:641-661` | — | **missing** |
| Inspect track | `:756` → `onInspectTrack` (`:3689`) | Track item | **missing** |
| Entity custom entries | `doContextConfigOptions` (`:4570`) → `onCustomFunction` (`:4592`) | Item has `ContextMenuConfig` | **missing** |

## 5. Inventory and loot windows (no menu)

| Action | Vanilla source | Parameters | Repo status |
|---|---|---|---|
| Drag and drop between containers (inventory, bags, loot containers, floor) | `client/ISUI/ISInventoryPane.lua:1215` (`onMouseUp`), `:632` (`transferItemsByWeight`) | Item(s), destination | **partial** via `take`/`stow`/`drop` |
| Double-click item (equip/wear/use) | `ISInventoryPane.lua:1145`, `:957` (`doContextualDblClick`) | — | **partial** (same effects through menu verbs) |
| Loot all / transfer all / remove all (bin) | `client/ISUI/ISInventoryPage.lua:205`, `:209`, `:2162` | — | **missing** |
| Stove toggle in the loot window | `ISInventoryPage.lua:271` (`toggleStove`) | Stove container shown | **missing** |
| Rename container | `ISInventoryPage.lua:1383`, `:1920` | — | **missing** |
| Select a container tab; sort list | `ISInventoryPage` container buttons; `ISInventoryPane.lua:195-200` | — | UI only |

## 6. Vehicles

Sources in `client/Vehicles/ISUI/` unless stated.

| Action | Vanilla source | Prerequisites / parameters | Repo status |
|---|---|---|---|
| Enter vehicle (choose seat) | Outside radial `ISVehicleMenu.showRadialMenuOutside` (`ISVehicleMenu.lua:277`) → `onShowSeatUI` (`:1611`, `ISVehicleSeatUI`) → `onEnter(playerObj, vehicle, seat)` (`:1372`) | Seat installed; occupied seats prompt moving items; locked doors handled in `onEnterAux` (`:1454`) | **partial**: `enter_vehicle` (`AIvZGymActions.lua:160-178`) calls `onEnter(p, v, seat)` (signature verified) for free installed seats of the 2 nearest vehicles within 4 tiles, with no visibility check |
| Exit vehicle | In-vehicle radial (`:228`) → `onExit(playerObj, seatFrom)` (`:1552`) | Passenger: vehicle stopped; driver stops first | **covered**: `exit_vehicle` (`AIvZGymActions.lua:151-153`, `:180-186`) |
| Switch seat | Radial `IGUI_SwitchSeat` (`:85`) → `onShowSeatUI`/`onSwitchSeat` (`:1103`) | `canSwitchSeat` | **missing** |
| Start engine | Radial (`:89-101`) → `onStartEngine` (`:1164`) → `ISStartVehicleEngine` | Driver, `isEngineWorking()`, not running or started, and (sandbox `VehicleEasyUse`, or key in inventory or ignition, or hotwired) | **covered** in code since gym 0.4.30 (not yet run in the game): `engine_on` only under these conditions; Hotwire is its own row |
| Shut off engine | Radial (`:89`) → `onShutOff` (`:1176`) | Driver, engine running | **covered**: `engine_off` |
| Hotwire | Radial (`:111-120`) → `onHotwire` (`:1172`) | No key; Electricity ≥ 1 and Mechanics ≥ 2, or Burglar | **covered** in gym 0.4.37 (2026-10-12, not yet run in the game): `hotwire` for the driver when the radial menu's slice would work (`ISVehicleMenu.lua:106-118`: not hotwired, engine neither started nor running, no `VehicleEasyUse`, keys not in the ignition, no key carried, and the skills or Burglar), `ISVehicleMenu.onHotwire`; done when `isHotwired()` (`tryHotwire` can fail) |
| Headlights, heater, horn, lightbar | `onToggleHeadlights` (`:1114`), `onToggleHeater` (`:1133`), `onHorn` (`:1699`), `onLightbar` (`:1724`) | Driver for lights/horn; part present | **missing** |
| Car radio (device options) | Radial (`:155`) → `onSignalDevice` (`:1160`) | Front seat | **missing** |
| Open/close own window; lock/unlock doors | `ISVehiclePartMenu.onOpenCloseWindow` (`ISVehiclePartMenu.lua:346`), `onLockDoors` (`:360`) | Window openable | **missing** |
| Sleep in vehicle | Radial (`:190-225`) → `onSleep` (`:1194`) | Same fatigue/safety/pain/panic rules as beds; vehicle stopped | **missing** |
| Open/close/lock/unlock a door from outside; smash window; wash | Outside radial (`:324-357`) → `onOpenDoor` (`:1223`), `onCloseDoor` (`:1238`), `onLockDoor` (`:1242`), `onUnlockDoor` (`:1246`), `ISVehiclePartMenu.onSmashWindow` (`:367`), `onWash` (`:1250`) | Key for locks; water for washing | **missing** |
| Trunk / glovebox / seats as containers | Loot window lists accessible parts (`ISInventoryPage.lua` vehicle branch) | `canAccessContainer` | **missing** (vehicle containers are not scanned) |
| Refuel: add gasoline, siphon, pump | `ISVehicleMenu.FillPartMenu` (`:1054`) → `ISVehiclePartMenu.onAddGasoline` (`:256`), `onTakeGasoline` (`:270`), `onPumpGasoline` (`:234`) | Petrol can; hose to siphon; pump with power | **missing** |
| Attach / detach trailer or tow | `doTowingMenu` (`:377`, `:562`) → `onAttachTrailer` (`:1728`), `onDetachTrailer` (`:1736`) | Tow points aligned | **missing** |
| Animals in trailer: check, put, remove | `FillMenuOutsideVehicle` (`:594`) → `:828-856` | Trailer with animal capacity | **missing** |
| Dismantle burnt wreck | `onRemoveBurntVehicle` (`:881`) | Blowtorch etc. (not audited) | **missing** |
| Mechanics window: install, uninstall, repair, inflate/deflate tyre, part info, take engine parts, repair engine, repair lightbar, smash or open window | `ISVehicleMechanics:doPartContextMenu` (`ISVehicleMechanics.lua:225-348`), `ISVehiclePartMenu.onInstallPart` (`:163`), `onUninstallPart` (`:201`), `onInflateTire` (`:290`), `onDeflateTire` (`:305`), `ISVehicleMechanics.onRepairEngine` (`:418`), `onTakeEngineParts` (`:463`), `onRepairLightbar` (`:451`) | Vehicle stopped; tools, parts and Mechanics level per part script | **missing** |
| Drive (throttle, reverse, steer, brake, cruise) | `J:CarController.updateControls` | Continuous; keyboard only | **missing** (see section 2) |

## 7. Specialised screens

| Screen / action | Vanilla source | Parameters / prerequisites | Repo status |
|---|---|---|---|
| Health panel treatments per body part: bandage, remove bandage, poultice, disinfect, stitch, remove stitch, remove glass (tweezers or hand), splint, remove splint, remove bullet, clean burn | `client/XpSystem/ISUI/ISHealthPanel.lua:1162-1735` (`HApplyBandage`, `HRemoveBandage`, `HApplyPoultice`, `HDisinfect`, `HStitch`, `HRemoveStitch`, `HRemoveGlass`, `HSplint`, `HRemoveSplint`, `HRemoveBullet`, `HCleanBurn`) | Item per treatment; wound state | **partial**: bandage only (see section 4) |
| Character screen: cut/tie/untie hair, trim/shave beard | `client/XpSystem/ISUI/ISCharacterScreen.lua:378-514` | Scissors/razor (not audited) | **missing** |
| Fitness screen: choose exercise, duration, OK, cancel | `client/ISUI/ISFitnessUI.lua` | 7 exercises from `shared/Definitions/FitnessExercises.lua` (squats, pushups, situp, burpees, barbellcurl, dumbbellpress, bicepscurl); duration 10-60 game minutes in steps of 10 (`onClickTime`); OK disabled for endurance moodle > 2, heavy-load moodle > 2, sitting, in vehicle, pain moodle > 3, climbing (`updateButtons`); equipment `inventory:contains("Base.BarBell"/"Base.DumbBell", true)`; `equipItems` unequips hands and worn bags first; then `ISFitnessAction:new(player, exercise, minutes, exeData, exeData.type)` via `ISTimedActionQueue.addGetUpAndThen` | **partial** (code only, not yet run in the game since these fixes): `exercise` (`AIvZGymActions.lua`) calls `ISFitnessAction:new(p, name, minutes, exeData, exeData.type)` with the screen's durations (10-60), tests the equipment with `contains(item, true)`, follows `updateButtons`' conditions, and since gym 0.4.37 does `equipItems`' hand-off first. Not done: the screen's re-equip when the exercise ends (`ISFitnessUI:update`, only while the screen is open), `addGetUpAndThen` (sitting is already excluded) |
| Crafting window (B): pick recipe, inputs, quantity, craft | `client/ISUI/Crafting/ISHandcraftWindow.lua`, `client/Entity/ISUI/CraftRecipe/ISHandCraftPanel.lua` | Known recipes, inputs, tools, surface, light | **missing** (only item-menu crafts, section 4) |
| Build window | `client/ISUI/Building/ISBuildWindow.lua`, `client/Entity/ISUI/BuildRecipe/ISBuildPanel.lua` | Recipe, materials, cursor placement | **missing** |
| World map: open, place symbols and notes, mini-map | `client/ISUI/Maps/ISWorldMap.lua:1500` (`ShowWorldMap`), `ISMapSymbolDialog.lua`, `ISTextBoxMap.lua`, `ISMiniMap.lua` | Sandbox `AllowWorldMap`; light when `MapNeedsLight` | **missing** |
| Radio/TV window: power, volume, channel, media | `client/RadioCom/ISRadioWindow.lua` and `RadioWindowModules/*` | Device | **missing** |
| Garment UI: patch, remove patches | `client/ISUI/ISGarmentUI.lua:125-222` | Needle, thread, fabric | **missing** |
| Make-up UI | `client/ISUI/ISMakeUpUI.lua` | Make-up item | **missing** |
| Fluid transfer window | `client/Fluids/ISFluidTransferUI.lua` | Source, target, amount | **missing** |
| Oven / stove settings | `client/ISUI/Fireplace/ISOvenUI.lua` | Temperature, timer | **missing** |
| Alarm clock dialog | `client/ISUI/ISAlarmClockDialog.lua` | Hour, minute | **missing** |
| Butcher hook, hutch, feeding trough, animal info windows | `client/ISUI/Animal/ISButcherHookUI.lua`, `client/ISUI/Hutch/ISHutchUI.lua`, `client/FeedingTrough/ISUI/ISFeedingTroughUI.lua`, `client/ISUI/Animal/ISAnimalUI.lua` | — | **missing** |
| Generator info, campfire info, farming info | `client/ISUI/ISGeneratorInfoWindow.lua`, `client/Camping/ISUI/ISCampingInfoWindow.lua`, `client/Farming/ISUI/ISFarmingInfo.lua` | — | **missing** (information only) |
| Sleep-hours dialog | `client/ISUI/ISSleepDialog.lua` | Not opened by any other vanilla Lua file (searched); possibly Java or unused | unverified |

## 8. New game, character creation, death

| Action | Vanilla source | Parameters / prerequisites | Repo status |
|---|---|---|---|
| New game from the main menu (mode, world, sandbox) | `client/OptionScreens/NewGameScreen.lua`, `WorldSelect.lua`, `SandboxOptions.lua`, `LoadGameScreen.lua` | Sandbox values are game settings, not character actions | **missing**: BACKLOG item 1 needs the new-game flow without changing settings |
| Choose spawn region (or Random) | `client/OptionScreens/MapSpawnSelect.lua:465` (`fillList`: one item per region plus a "Random" item with `region = nil`); respawn uses `CoopMapSpawnSelect.lua:90` (`clickNext`: `setSpawnRegion(region.key or region.name)`) | List index | **covered** for respawn: `G.respawnStep` picks a random item with a `region` and calls `clickNext` (`AIvZGym.lua:928-933`); the agent itself does not choose it |
| Choose profession | `client/OptionScreens/CharacterCreationProfession.lua:434` (`onSelectProf`), list `listboxProf` | Profession cost changes the points | **missing**: the first profession in the list stays selected |
| Add good trait / add bad trait | `onOptionMouseDown` `ADDTRAIT`/`ADDBADTRAIT` (`:518`), `addTrait` (`:643`): `pointToSpend = pointToSpend - cost`; lists `listboxTrait` (cost > 0) and `listboxBadTrait` (cost ≤ 0), exclusions by `doTestForMutuallyExclusiveTraits` | Selected list item; mutual exclusions | **partial**: `G.creation` (`AIvZGymActions.lua:203-330`) uses these widget names, all present in 42.21 (`listboxBadTrait` and `addBadTraitBtn` exist, `:234-286`) |
| Remove trait, reset, randomize, presets | `REMOVETRAIT`, `RESETTRAITS`, `RANDOMIZE` (`:518-628`) | Not for profession-granted (free) traits | **partial**: removal only in `G.creationRepair`, never as the agent's choice |
| Points and "Next" | `CharacterCreationProfession:PointToSpend()` (`:860`) = `pointToSpend + cost + SandboxVars.CharacterFreePoints - negativeTraitOffset` (offset only when sandbox `NegativeTraitsPenalty` ≠ 1); `render` (`:827-836`) disables the play button while it is below 0 | — | **wrong**: `G.creationPoints` (`AIvZGymActions.lua:229-237`) reads the raw `pointToSpend` field, which omits profession cost, free points and the negative-trait offset; Next is pressed through `onOptionMouseDown({internal="NEXT"})` (`AIvZGym.lua:939`), which bypasses the disabled button. Use `prof:PointToSpend()` |
| Appearance: name, gender, skin colour, hair style/colour/stubble, beard style/stubble, voice type/pitch, clothing per slot, outfit preset, random, save/delete build | `client/OptionScreens/CharacterCreationMain.lua:234-1522` | Combo boxes, colour pickers, text entries | **missing** (Next only, `AIvZGym.lua:941-943`) |
| Start (play) | `CoopCharacterCreationMain:onOptionMouseDown` `NEXT` → `CoopCharacterCreation.instance:accept()` (`client/OptionScreens/CoopCharacterCreationMain.lua`) | — | **covered** (`AIvZGym.lua:941-943`) |
| Respawn after death; exit; quit | `client/ISUI/ISPostDeathUI.lua:149` (`onRespawn`), `:142` (`onExit`), `:111` (`onQuitToDesktop`); buttons appear after `waitOver` (3 s, `:73-84`) | — | **covered** for respawn (`AIvZGym.lua:922-926`) |

## 9. Excluded

Debug, admin and cheat entries (`addDebugOption`, `[DEBUG]` labels, `ISVehicleMechanics` CHEAT entries,
`ISFarmingMenu.lua:411-433`, `ISAnimalContextMenu.lua:327-413`, `ISHealthPanel.lua:1822-1870`,
`client/DebugUIs/**`, `ISWorldMap` teleport and grid entries), multiplayer-only screens (chat, trading,
safehouse, map sharing, server options), game settings and speed controls (user-owned), and the tutorial.

## 10. Summary

* The gym offers 33 in-game verbs plus `continue`, and `add_trait`/`finish_creation` on the trait screen.
  Against the installed game, **covered** (callback, signature and prerequisites match): climbing through
  an `IsoWindow`, exit vehicle, engine off, respawn, spawn region, start. Every other implemented verb is
  **partial**, and `sleep`, `drink`, `exercise`, `engine_on` and the trait points are **wrong** as
  described above. No implemented call uses a misspelled API or a wrong argument order, except
  `ISFitnessAction:new` (missing argument) and the `pointToSpend` field (wrong value).
* Whole families are **missing**: floor items and corpses, every world-object interaction other than
  doors/windows/curtains/taps/beds, all repairs and maintenance, building, barricading, farming, fishing,
  trapping, foraging, animals, cooking, literature, firearms, the health panel beyond bandaging, the
  crafting and build windows, vehicles beyond entering and the ignition, driving, and appearance and
  profession choice.
* The ordered list of what to build next, with the API facts each item needs, is in
  [GAP_LIST.md](GAP_LIST.md).
