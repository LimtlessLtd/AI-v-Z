# Observation audit: what the gym tells the agent vs what a player can perceive (2026-10-11)

Project Zomboid 42.21.0, gym 0.4.3. The question for every field is whether a human playing this character
could know it from the screen, the sound, or their own memory of what they saw. Anything else is a
hidden-information leak and must not reach the learner. Hearing is not covered here beyond noting that it
is absent ([PHASE3_COVERAGE.md](PHASE3_COVERAGE.md)). The action side is in
[ACTION_CATALOGUE.md](ACTION_CATALOGUE.md); the ordered fixes are in [GAP_LIST.md](GAP_LIST.md).
Everything here comes from reading the installed Lua and disassembling `projectzomboid.jar`; **none of it
has been checked in a running game**.

Repo references are `file:line` under `mod/AIvZ/42/media/lua/client/`. Game Lua paths are relative to
`media/lua/`; Java is cited as `J:class.method` with `javap` offsets.

## 1. How the game decides what the player sees (verified in the installed files)

**Characters (zombies, animals, other players).** `J:zombie.characters.IsoPlayer.updateLOS` runs over every
moving object in the cell. An object is a candidate when its square is `isCanSee(pn)` (or, for a zombie,
`IsoZombie.canSeeHeadSquare`) or, within `IsoPlayer.getDetectionRange()`, `isCouldSee(pn)` (offsets
452-583). It is then visible only if `IsoGameCharacter.isVisibleToPlayer[pn]` is true; that array is
written by `IsoGameCharacter.updateSeenVisibility(int)` from `TestIfSeen(int, IsoPlayer)`, which requires:
distance ≤ `GameTime.getViewDist()`; the square couldSee and canSee (or the head square); and a light test
built from the average of r, g, b of the target's square (treated as 1 above 0.6), a fall-off with
distance over the view distance and `max(IsoPlayer.getDotWithForwardDirection(x, y), 0.5)`, compared with
a very small threshold (`× 100 > 0.025`; offsets 153-405, only partly decoded). Visible objects are
pushed onto the player's spotted list and get `setTargetAlpha(pn, 1)`; the rest fade to alpha 0 (offsets
886-932, 1099-1110). The player itself is also on the list (offset 191).

* Lua can read the result through **`IsoPlayer:getSpottedList()`** (`java.util.Stack<IsoMovingObject>`,
  public, `IsoPlayer` exposed) and **`IsoObject:getTargetAlpha(int playerIndex)`** (float). The boolean
  array itself is a field and is not readable from Lua.
* `Stats:getNumVisibleZombies()` counts a subset of the spotted zombies: within 7 tiles, not ghost or
  fake-dead, and in the player's room (both outdoors counts as the same; offsets 650-723). The sleep check
  uses it.

**Squares.** `IsoGridSquare:isCouldSee(int)`, `isCanSee(int)` and `isSeen(int)` only read flags from the
native lighting (`J:zombie.iso.LightingJNI`, `Lighting64.dll`). The Java side feeds it, per player
(`LightingJNI.updatePlayer`): position, look vector, `calculateVisionCone` (144° base, narrowed by up to
126° in darkness and by fatigue, drunkenness and panic, widened by up to 36° for Eagle Eyed by day or
Night Vision by night, clamped to 18-180°, multiplied by worn items' vision factor; a 324° base in
vehicles), effective fatigue, detection range and Short Sighted. So `isCanSee` already
depends on the view cone and darkness; exactly how is native code (**unverified**). `isSeen` reads like
"has been seen"; its exact meaning and whether it resets for a new character are **unverified**.

**Light.** `IsoGridSquare:getLightLevel(int pn)` returns `max(r, g, b)` of that player's light info for
the square (`getLightLevel(-1)` → `getLightLevel2()`). The game's own spotting rule uses the average of
r, g, b, not the maximum, and a far lower threshold. **`IsoPlayer:tooDarkToRead()`** (exists, exposed) is
the game's darkness test for reading, crafting with light, barricading and the map.

**Rooms.** `RoomDef:isExplored()` is written by `IsoRoom.onSee`, `IsoGridSquare.checkRoomSeen` and
`FBORenderCell.checkSeenRooms` (also touched by `RandomizedBuildingBase.ChunkLoaded`, not read), and saved
with the map (`IsoMetaGrid.load/savePart`). From these callers it is the game's "this room has been seen"
flag (inferred, **live test**). It belongs to the world, so a new character in the same save would inherit
the rooms earlier characters saw (memory the new character does not have).

**Containers.** The loot window lists containers on the 3x3 squares around the character that
`IsoGridSquare:canReachTo` allows, and fills a container with loot the first time it is listed
(`client/ISUI/ISInventoryPage.lua:1511`, `:1537`). Unexplored containers are empty until then.

**What can be clicked.** `J:IsoObjectPicker.ContextPick` ignores objects whose `getTargetAlpha(0)` is 0.

**HUD and panels.**
* Clock: `J:zombie.ui.Clock.resize` makes it visible only when the character wears an `AlarmClock` or
  `AlarmClockClothing` (a watch), or has one in inventory that is worn or equipped. Date and temperature
  digits are drawn only when that item has tag `DIGITAL` (`Clock.isDateVisible()` = visible and digital);
  the temperature comes from `ClimateManager:getAirTemperatureForCharacter`. Lua:
  `UIManager.getClock():isVisible()` and `:isDateVisible()` (both exposed).
* Health panel: overall status text from `J:zombie.ui.NewHealthPanel.getDamageStatusString`, bands of
  `BodyDamage:getHealth()`: 100 "OK", > 90, > 80, > 70, > 60, > 50, > 40, > 20, > 10, > 0, dead. Per-part
  list (`client/XpSystem/ISUI/ISHealthPanel.lua:620-850`): scratch, laceration and deep wound with
  severity, bite, pain, stiffness, bleeding, fracture with severity, splint, bandage or dirty bandage,
  stitches; infected wound, lodged bullet, burn and glass shards **only while that part is not bandaged**.
  Pain level text appears only with the cheat or a skilled doctor (`:470-472`).
* Moodles: `J:zombie.ui.MoodlesUI` draws the moodles the character's `Moodles` reports, but keeps
  `FOOD_EATEN` off screen below its high level (update offsets 222-254); `ENDURANCE` has a percentage
  background. The full display rule was not decoded.
* Character screen: `IsoGameCharacter:getZombieKills()`, body weight, traits; "Survived for" only when the
  clock shows the date (`client/XpSystem/ISUI/ISCharacterScreen.lua:227-240`).
* Item tooltips (`J:Food.DoTooltip`, `J:HandWeapon.DoTooltip`, `J:InventoryItem.DoTooltip`): hunger,
  thirst, endurance, stress, boredom, unhappiness, nutrition, "Dangerous uncooked", weapon damage, range,
  condition, sharpness, encumbrance, capacity, wetness, tainted water (`Tooltip_item_TaintedWater`).
* Door menu: "Door Is Locked" when `couldBeOpen(player)` is false (see the catalogue, 3.1). A window locked
  by `IsoWindow:isLocked()` is not shown as locked.
* World map: shows the player when sandbox `Map.AllowWorldMap` is on (`client/ISUI/Maps/ISWorldMap.lua:1491`,
  `showPlayers = true` at `:1472`); light needed if `Map.MapNeedsLight`.

## 2. Observation fields (`G.observe`, `AIvZGym.lua:154-216`)

Verdicts: **ok** (a player perceives it), **proxy** (a summary of something visible, acceptable if
coarse), **precision** (visible, but given far more exactly than any screen shows), **leak** (not
perceivable now), **gap** (perceivable but missing).

| Field | Source | Verdict | Fix and API |
|---|---|---|---|
| `who.name`, `who.save` | `SurvivorDesc:getForename/getSurname`, `IsoWorld:getWorld()` | ok | — |
| `t.age`, `born` | `GameTime:getWorldAgeHours()` | leak (no clock shows hours since the world began) | Keep for logging and reward outside `obs`; do not give it to the learner |
| `t.day` | `GameTime:getNightsSurvived()+1` | proxy (countable from nights seen) | Acceptable; or only when `Clock:isDateVisible()` |
| `t.hour`, `t.min` | `GameTime:getHour/getMinutes` | **leak** without a watch or alarm clock worn or in hand | Only when `UIManager.getClock():isVisible()` is true; otherwise omit |
| `t.dark` | `ClimateManager:getNightStrength()` | proxy (scene brightness) | Acceptable; or use `tooDarkToRead()` and `light` only |
| `kills` | mod's own count from `OnZombieDead` with `getAttackedBy() == p` (`AIvZ.lua:894-902`) | ok, but not the number shown | Use `IsoGameCharacter:getZombieKills()` (the character screen value) |
| `pos` x, y, z | `IsoPlayer:getX/getY/getZ` | precision (a map pin at most, and only with the map allowed) | Remove exact coordinates, or round heavily and only if `ISWorldMap.IsAllowed()` |
| `health` | `BodyDamage:getOverallBodyHealth()` to 0.1 | precision | Report the health-panel band from `BodyDamage:getHealth()` (thresholds above) |
| `stats.*` (hunger, thirst, fatigue, endurance, panic, pain, stress, sickness, food_sickness, wetness, temperature) | `Stats:get(CharacterStat.X)` raw values | **leak** (players see moodle levels, not these numbers; food_sickness is never shown) | Drop `stats`; the moodle levels carry what is visible. Endurance may be kept as a coarse fraction (moodle background); temperature as the health panel shows it (**unverified** whether it shows body temperature) |
| `moodles` | `Moodles:getMoodleLevel(MoodleType.X)` for 17 types | ok; gap: `BORED`, `UNHAPPY`, `ANGRY`, `WINDCHILL`, `CANT_SPRINT`, `UNCOMFORTABLE`, `NOXIOUS_SMELL`, high `FOOD_EATEN` are visible but not reported | Add the missing `MoodleType` constants (all exist); whether `ZOMBIE` is ever drawn is **unverified** |
| `speed` | `GameTime:getTrueMultiplier` then overwritten by `U.getSpeed()` (`AIvZGym.lua:175`, `:214`) | ok (speed buttons) | Remove the duplicate assignment |
| `body` | `A.wounds` (`AIvZ.lua:467-484`): bleeding, scratch, bite, laceration, deep wound, fracture, glass, bandaged | mostly ok; **leak**: `glass` is reported under a bandage, where the panel hides it; gap: severity, dirty bandage, stitches, splints, burns, bullets, infected wound, pain, stiffness | Report exactly what `ISHealthPanel` draws, with its `not bodyPart:bandaged()` conditions |
| `light` | `IsoGridSquare:getLightLevel(pn)` on the own square | proxy (a number the player cannot read) | Coarse bins, or `IsoPlayer:tooDarkToRead()` |
| `asleep` | `IsoGameCharacter:isAsleep()` | ok | — |
| `weather.rain` | `ClimateManager:getRainIntensity()` | proxy (visible and audible) | Acceptable, coarse |
| `weather.temp` | `ClimateManager:getTemperature()` | **leak** unless a digital clock is visible (and then it shows `getAirTemperatureForCharacter`) | Report `getAirTemperatureForCharacter(p)` only when `UIManager.getClock():isDateVisible()` |
| `weight`, `maxWeight` | `ItemContainer:getCapacityWeight`, `IsoGameCharacter:getMaxWeight` | ok (inventory window) | — |
| `held`, `inv[]` | `G.itemInfo` (`AIvZGym.lua:116-151`), 40 items at most | mostly ok (tooltip values); see the item rows below | — |
| `inv[].cat == "drink"`, `inv[].water` | `U.waterIn` (`AIvZ.lua:223-231`) rejects `FluidContainer:isPoisonous()` and tainted water | **leak** for mixtures the player cannot identify (poison is not on any tooltip read here; tainted water has tooltip text) | Classify from `getFluidContainer():getPrimaryFluid()` and tooltip-visible properties only; never from `isPoisonous()` |
| `inv[].dmg`, `cond`, `range`, `twoHand` | `HandWeapon:getMaxDamage/getCondition/getMaxRange/isTwoHandWeapon` | ok (weapon tooltip shows damage, condition, range, "limited impact one-handed") | — |
| `inv[].raw`, `rotten`, `cooked`, `hunger`, `thirst`, `unhappy` | `Food` getters | ok (tooltip and name) | — |
| `inv[]` coverage | first 40 non-held, non-hidden items (`AIvZGym.lua:184-187`) | gap: more items are visible in the inventory window | Page or summarise instead of truncating |
| `zombies[]` | `visibleZombies` (`AIvZGym.lua:52-61`): `isCanSee(0)` and `getLightLevel ≥ 0.2` or within 1.5 tiles | proxy that disagrees with the game's rule (see 1) | Use membership of `p:getSpottedList()` (filter `instanceof(o, "IsoZombie")`), or `z:getTargetAlpha(pn) > 0` |
| `zombies[].closing` | per-object memory in `GS.zprev` (`AIvZGym.lua:66-76`) for up to 900 ticks | **leak**: identity is kept across occlusion through the Java object, which a player cannot do for a look-alike zombie that left view | Reset `GS.zprev[z]` whenever `z` is not on the spotted list |
| `zombies[].facing` | gym 0.4.25: the zombie's `getForwardDirectionX/Y` against the direction to the character, 1 facing it, -1 facing away | ok (a player sees which way a zombie's body faces; the AI's target stays hidden) | — |
| `sneaking`, `running` | gym 0.4.25: `isSneaking()`, `isRunning() or isSprinting()` of the character | ok (a player sees their own stance) | — |
| `zombies[].blocked` | `IsoGridSquare:isBlockedTo` on the first step (`AIvZ.lua:422-430`) | ok (a wall or door between is visible) | — |
| `where.outside` | `IsoGameCharacter:isOutside()` | ok | — |
| `where.room` | `IsoRoom:getName()` (map data, e.g. `kitchen`) | proxy (the label is not displayed; the furniture is) | Keep only for the room the character is in |
| `where.building` | building corner key `x,y` (`AIvZ.lua:55`) | ok as an identifier | — |
| `where.doorsOpen/windowsOpen/curtainsOpen/smashed` | `A.scanBuilding` over the whole floor of the building (`AIvZ.lua:511-562`) | **leak**: counts openings in rooms never seen | Count only openings on squares with `isSeen(pn)` (or rooms with `RoomDef:isExplored()`), from memory of what was seen |
| `near.*` | items in searched containers within 12 tiles (`AIvZGym.lua:202-213`) | ok as memory, but read live | Store a snapshot when the container is looked at |

## 3. Option fields (what the option list reveals)

| Verb and field | Source | Verdict | Fix and API |
|---|---|---|---|
| `walk`/`run` `zombies` | visible zombies per direction (`AIvZGym.lua:282-300`) | proxy | Same zombie fix as above |
| `enter` (which buildings are offered) | `A.scanBuildings(p, 60)` keeps the 16 nearest ground-floor buildings before the "seen" filter (`AIvZ.lua:665`); "seen" tests `isCanSee` on a free square *inside* a room (`AIvZGym.lua:310`) | gap (likely too few buildings: interior squares are rarely in sight from outside; **unverified** in game) and coverage bug (truncation before filtering) | Remember a building when any of its exterior wall or door squares `isCanSee(pn)`; filter before truncating |
| `enter` `rooms`, `visited`, `zombies` | names only once visited (`AIvZGym.lua:312`); visible zombies | ok | — |
| `enter` executor (not an observation, but it acts on hidden state) | `A.travelStep` → `A.enterStep` → `entryWindows` (`AIvZ.lua:1322-1410`) ranks every exterior window of the building, seen or not, by `isLocked()`/`isPermaLocked()` and then opens, smashes or climbs on the agent's behalf | **leak** into behaviour: the macro picks windows a player could not know to be unlocked | Split into the agent's own window options (only seen windows), or let the macro try windows in order of distance and learn locks by failing |
| `go_room` (rooms, names, distances, areas) | every `RoomDef` of the building on this floor (`AIvZGym.lua:333-353`) | **leak**: layout and names of rooms never seen | Offer only rooms with `RoomDef:isExplored()` (exists); track per character because the flag is per world |
| `attack`/`shove` | `zombieView` | proxy | Spotted-list fix |
| `door.locked` | gym 0.4.13: `not couldBeOpen(p)` when the method answers, else `isLocked()` (untested in game); was `IsoDoor:isLocked()` | close to ok: the menu shows "Door Is Locked" from `couldBeOpen(player)` | Use `couldBeOpen(p)` (exists on `IsoDoor` and `IsoThumpable`) so it matches the menu, including keys |
| `window.locked` | `IsoWindow:isLocked()` | **leak**: the menu does not show it | Remove; report it only after a failed attempt |
| `door/window/curtain/search` at ≤ 1.5 tiles | `perceivable` returns true for any square within 1.5 tiles (`AIvZGym.lua:79-85`) | **leak** through walls | Require `IsoGridSquare:canReachTo` from the current square (the loot window's rule) or `isCouldSee(pn)` |
| `door/window/curtain/search` beyond 1.5 tiles | `isCanSee(pn)` and `getLightLevel ≥ 0.2` (guessed threshold) | proxy; probably stricter than the screen for objects in rooms seen earlier if those stay drawn (**live test**) | Use `isSeen(pn)` for remembered static objects and `isCanSee(pn)` plus `tooDarkToRead()` or the spotted-list light rule for their current state (**needs live test**) |
| `search.type`, `indoors`, `here` | container type, building membership | ok | — |
| `door/window/curtain` on a wall | gym 0.4.31: a door or window counts when its own square is perceivable **or** the square on the near side of its wall is (the game keeps it on the square south or east of the wall, so one on a room's east or south wall belongs to the square outside) | gap, **fixed in gym 0.4.31**: with the curtain drawn, at night or behind a closed door the square outside is out of sight, and every opening on those walls vanished (2026-10-12: a character in a bathroom with a locked door drew the curtain over the window it had opened and never saw the window again) | A player sees a wall's door or window from inside the room; same light rule, on the near square |
| `door/window/curtain/climb/smash/clear_glass.dx, dy` | gym 0.4.23: the object's square centre relative to the character | ok (a player sees where a door or window is; the same squares as the options themselves) | — |
| `take` items | live contents of searched containers within 2.5 tiles | ok (the loot window shows them) | — |
| `craft` availability | `CraftRecipeManager.getUniqueRecipeItems` with `ISInventoryPaneContextMenu.getContainers` (inventory and loot-window containers), cached 600 ticks (`AIvZGym.lua:528-560`) | ok (same inputs as the game's menu); stale up to 600 ticks | Re-check `HandcraftLogic:canPerformCurrentRecipe()` at execution |
| `drink_tap.tainted` | `IsoObject:isTaintedWater()` | ok if the sandbox shows tainted water text (`EnableTaintedWaterText`, read in `ISInventoryPaneContextMenu.doDrinkForThirstMenu`); the world tooltip was not read (**unverified**) | Gate on `getSandboxOptions():getOptionByName("EnableTaintedWaterText"):getValue()` |
| `drink_tap` candidates | `A.scanWater(p, 10)` truncated to 5 before the visibility filter (`AIvZ.lua:688`, `AIvZGym.lua:442-448`) | coverage bug | Filter first |
| `sleep.bed`, `d` | `A.beds` over every floor of the building (`AIvZ.lua:579-597`) | **leak**: beds in unseen rooms and floors | Only beds on `isSeen(pn)` squares or explored rooms |
| `bandage` | body parts and first bandage in the bag | ok (health panel) | — |
| `exercise.endurance` | raw `Stats:get(CharacterStat.ENDURANCE)` (`AIvZGymActions.lua:47`, `:53`) | **leak** (precision) | Use the moodle level, as the fitness screen does |
| `enter_vehicle` vehicles | `IsoGridSquare:getVehicleContainer()` within 4 tiles, no visibility check (`AIvZGymActions.lua:134-148`) | **leak**, fixed in gym 0.4.14: only vehicles on a square with `isCanSee(pn)` are offered (untested in game) | Vehicles are never on the spotted list (`updateLOS` skips `BaseVehicle`, offset 176); use `vehicle:getTargetAlpha(pn) > 0` (`BaseVehicle` is an `IsoObject`; **live test**) or `isCanSee(pn)` of its squares |
| `enter_vehicle.name` | `VehicleScript:getName()` (script id) | proxy | Prefer the display name |
| creation `points`, `selected`, option costs | raw `pointToSpend`, trait labels/costs | costs ok; **points wrong** (see catalogue 8) | `prof:PointToSpend()` |

## 4. Scans and caches

| Scan / cache | Where | Finding |
|---|---|---|
| `allZombies` | `AIvZ.lua:433-455` | All zombies within 45 tiles on the floor; `isCanSee(0)` hard-codes player 0 (fine in singleplayer). Gym filters it; the rules baseline still uses unseen ones and `chasing` (not the gym). |
| `GS.zprev` | `AIvZGym.lua:66` | Weak table keyed by zombie object; carries identity across occlusion (leak above). |
| `G.scanAround` / `GS.around` | `AIvZGym.lua:220-264` | Rebuilt per tick; 1.5-tile through-wall leak; containers keyed by square and index (`x,y,z,n`), which shifts if objects on the square change. Corpses, floor items and vehicle parts are never scanned (catalogue 3.2). |
| `m.seen` | `AIvZGym.lua:87-91` | Containers looked into, kept in the character's mod data: correct per-character memory. |
| `m.bseen`, `m.visited` | `AIvZGym.lua:302-317` | Per-character map memory; see the `enter` row. |
| `GS.blds` (240 ticks), `GS.water` (120 ticks) | `AIvZGym.lua:305-316`, `:442-448` | Stale lists between refreshes; truncation before filtering. |
| `GS.rcache` (600 ticks) | `AIvZGym.lua:530-559` | Keyed by item object; stale availability. |
| `A.buildingInfo` cache (60 ticks) | `AIvZ.lua:564-576` | Whole-floor openings (leak above). |
| Decision reason `hurt` | `G.needDecision` | Until gym 0.4.20 a trigger: a 0.5 drop of exact health asked at once, a timing signal finer than the screen. Since 0.4.21 (owner's decision, 2026-10-12) decisions come at a steady rate while an action runs, and `hurt` only labels one: the reason still reports a drop the health band may not show. Use the band or bleeding/moodle changes. |
| Decision reason `zombie close` | `G.needDecision` | Visible zombies within 4 tiles with no wall between; inherits the zombie-visibility proxy. A trigger again since gym 0.4.23 (owner's decision, 2026-10-12): more of them than at the last decision asks at once. Gym 0.4.21-0.4.22 had it only as a label on the steady decision. A player sees a zombie come close at once, so the timing reveals nothing hidden. |
| Reward | `agent/reward.py` | Version 3 (2026-10-12) uses exact `health`, open and bandaged wounds, the protection panel, the hidden Knox infection flag (`obs.knox`), kills, new items/buildings/containers; no moodles. A reward is a training signal, not an observation, so hidden values there teach the network what matters without showing it the value itself: the infection flag is the deliberate case (the death it causes is charged when it happens). |
| Hearing | `agent/hearing.py` | No capture source; every record says `available: false`. |

## 5. Remaining hidden-information leaks, in order of impact

1. **Raw `stats`** (not reaching the network: `agent/features.py` is an allow-list and never reads `stats`; still in `obs.json`, the logs and the bridge) (11 exact internal values, including food sickness) in every observation. Fix: remove;
   rely on moodles (`Moodles:getMoodleLevel`).
2. **Unseen rooms** (`go_room` options fixed in gym 0.4.15 with `RoomDef:isExplored()`, kept if the call fails; untested in game; gym 0.4.17 counts open doors, windows and curtains only on `isSeen(pn)` squares; gym 0.4.19 counts smashed windows on seen squares too; untested in game): `go_room` options and the building opening counts expose layout, names and state of
   rooms never seen. Fix: `RoomDef:isExplored()` plus per-character memory; `IsoGridSquare:isSeen(pn)` for
   squares.
3. **Beds in unseen rooms/floors** (fixed in gym 0.4.15: `A.beds(p, b, true)` keeps beds on `isSeen(pn)` squares; the rules baseline still sees all; untested in game) through the `sleep` option. Same fix.
4. **Time of day and temperature without a watch.** (Gym 0.4.18: `weather.temp` is gone from the observation; a digital clock's `clock.temp` is `getAirTemperatureForCharacter(p)`, as the clock shows it; untested in game. `t.hour`/`t.age` remain as bookkeeping. Not reaching the network: it reads `obs.clock`, never `t.hour`/`t.age` or `weather.temp`; `obs.clock` itself is gated on a worn watch since gym 0.4.6. They remain in `obs.json`.) Fix: time only when `UIManager.getClock():isVisible()`;
   temperature only when `isDateVisible()`, using `ClimateManager:getAirTemperatureForCharacter(p)` as the
   clock does.
5. **Through-wall objects within 1.5 tiles** (`perceivable`; gym 0.4.16 requires `isCouldSee(pn)` for them, kept if the call fails; untested in game). Fix: `IsoGridSquare:canReachTo` /
   `isCouldSee(pn)`.
6. **Poison in the drink category** (`FluidContainer:isPoisonous()` in `U.waterIn`). Fixed in gym 0.4.12 (the gym calls `U.waterIn(it, true)`, which skips the poison test; the rules baseline keeps it; untested in game). Original fix note: classify from
   visible fluid type only.
7. **Window `locked`.** Already dropped from the window options (not listed in the gym) and zeroed in the network input. Original fix: drop until a failed attempt; doors: `couldBeOpen(p)`.
8. **Vehicles within 4 tiles regardless of sight.** Fixed in gym 0.4.14 with the square's `isCanSee(pn)` (not the alpha; untested in game). Original fix note: `getTargetAlpha(pn)` (needs live check) or square
   `isCanSee(pn)`.
9. **Zombie identity across occlusion** in `closing` (fixed in gym 0.4.10, not yet seen in game). Fix: forget a zombie when it leaves the spotted list.
10. **Exact health, exact position, exact endurance in `exercise`, world age, glass under a bandage.** (Network side: health goes in as the panel's band, and position, world age and exercise endurance are not read; the wound flag `glass` is dropped for a body part that is bandaged, as the health panel hides it; the mod still reports it in `obs.json`.)
    Fix: bands and coarse or no values as listed in section 2; wound flags with the health panel's
    conditions.
11. **The `enter` macro's window choice** uses lock state of unseen windows (`AIvZ.lua:1322-1353`).
    Fix: see the `enter` executor row in section 3.
12. **Zombie visibility proxy** (`isCanSee` + max-light ≥ 0.2). Not a leak in the strict sense but not the
    game's rule: it can both show zombies the screen hides (behind the player, in the dark beyond the
    light test) and hide ones it shows. Fix: `IsoPlayer:getSpottedList()` / `getTargetAlpha(pn)`.

## 6. Perceivable things the agent does not get (gaps, not leaks)

Sound of any kind; floor items and corpses next to the character; contents of adjacent containers the
loot window shows without walking (the gym needs a `search` first); animals, fires, smoke, vehicles in
sight; other moodles listed in section 2; health-panel details beyond the eight wound flags; the item
tooltips' nutrition and other effects; whether it is light enough to read (`tooDarkToRead()`); the map.

## 7. What needs live testing

* Whether `getSpottedList()` and `getTargetAlpha(pn)` change exactly when zombies appear and fade on screen,
  by day, at night, behind the character and through windows.
* What `isSeen(pn)` and `RoomDef:isExplored()` hold after death and respawn in the same save.
* Whether static objects in rooms seen earlier but now out of sight stay clickable (picker alpha) and show
  their current state on screen.
* Whether `vehicle:getTargetAlpha(pn)` tracks vehicle visibility.
* Whether the tainted-water text appears in the world tooltip with the default sandbox.
* Whether exterior squares of a building seen from the street are `isCanSee(pn)` (for building memory).

## 8. Kept from the network's input (agent/features.py)

Three leaks are cut on the learner's side, without a `features.VERSION` bump (the input slots stay, so the
trained network is kept; the values it sees change a little, so it adapts over the next rounds):

* `window.locked` is always 0 (leak item 7; doors keep `locked`).
* `exercise.endurance` is always 0 (leak item 10; the endurance moodle is already an input).
* Overall health goes in as the health panel's band, not the exact figure (leak item 10, precision).

The Lua side still reports these fields; fixing them at the source is separate and needs the game.

**Added with reward version 3 (gym 0.4.20, `features.VERSION` 2, 2026-10-12):**

* `obs.protection`: the protection panel's own numbers (`IsoGameCharacter:getBodyPartClothingDefense`,
  `client/XpSystem/ISUI/ISCharacterProtection.lua:77-78`). A player sees these, so they go into the network.
* `obs.knox`: whether the character carries the Knox infection (`BodyDamage:IsInfected`). The game doesn't tell
  the player, so the allow-list keeps it out of the network (a test checks this); only the reward reads it.
