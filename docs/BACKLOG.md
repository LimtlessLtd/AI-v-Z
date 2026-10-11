# Backlog

Items are recorded here when raised; status is honest. Phase 3 items must be done before the Phase 4
check-in; the rest are noted so they are not lost. Nothing here is live-tested unless it says so.

## From the owner, 2026-10-11

| # | Item | Phase | Status |
|---|---|---|---|
| 1 | After **100 deaths in the same game**, start a completely new game so the world doesn't run out of resources/houses. | 3 | Partly: the agent counts deaths per save (`world_deaths` in `logs/agent-state.json` and each `lives.jsonl` record; `Lives.new_world_due`). **Not done:** actually creating a new game through the game's own menus (needs a Lua adapter for the main-menu new-game flow; must be validated live and keep display/speed settings). |
| 2 | On death, choose the respawn location **randomly from those available**. | 3 | Already behaves this way: `G.respawnStep` picks a random town from the spawn-select list. Still to confirm in the live log that every available region (not only towns with a `region`) is offered. |
| 3 | Let the AI **choose its traits** at character creation, so it can learn to offset weaknesses. | 3 (action) / 4 (learning) | **Option B, the owner's choice (gym 0.4.9, 2026-10-11, verified live):** it buys any number of good traits, each only if it leaves the points at -12 or above (`DEBT_LIMIT` in `AIvZGymActions.lua`), or stops buying; then, while the points are below 0, only bad traits; at 0 or above the game starts by itself. First live build: 5 good traits to -12, 3 bad traits back to 0 or above. History: gym 0.4.3-0.4.5 read the raw `pointToSpend` (starts at 0 whatever the screen shows) and stopped buying with points still on screen; gym 0.4.6's buy-until-0 rule kept bad traits on offer next to Continue once the points were back to 0, and the agent piled them up (up to 7 bad against 2 good); gym 0.4.8 had trait picking off. Each life's observations list its traits (`obs.traits`). Not covered: profession choice, appearance. **Open:** the network can only weakly link a trait to how a life went (option C in the 2026-10-11 discussion, per-trait scores from finished lives, was proposed and not chosen). |
| 4 | **Light levels:** don't present information a human couldn't see in the dark. | 3 | Started (gym 0.3.3, untested live): gym zombies on unlit squares (`getLightLevel` < 0.2, guessed) are hidden unless within 1.5 tiles, and `obs.light` reports the character's own square light. Gym 0.4.1 applies the same rule to door/window/curtain/container/tap scans and hides unvisited building interiors. Still to do: calibrate threshold in game, account for held torches/vision, audit building/container/item scans. Original note: audit what each observation reveals at night/in unlit rooms (zombie visibility currently uses `isCanSee`, which may not reflect darkness; building/container/item scans are unaudited). Decide on a light measure (square light level, torch/lamp held, indoors/outdoors) and expose it as an observation. |

| 5 | **No speech bubbles or announcements.** The character must not say or show anything the network didn't choose, and the network must not be handed explanations it couldn't know (e.g. "not safe to sleep here"). | 3 | Partly: all five `p:Say` calls in `AIvZ.lua` now go through a no-op `speak` helper (2026-10-11, untested in game). **Not done:** the game's own halo text from direct handler calls, and `last.msg` reason texts. Every source is listed in [Speech and announcements](#speech-and-announcements-item-5). |
| 6 | **Remove the repo's own guard rails**, so the network learns its own rules from repetition. | 3 | Not done. [Guard rails](#guard-rails-item-6) lists them, separated from the game's own prerequisites (which stay, because a player has them too). |
| 7 | **Item and vehicle status a player can see**: clothing condition, vehicle parts, weapons, ammo and which ammo/magazine fits which weapon. | 3 | **The network sees almost none of it today.** Work items O1-O6 in [Item and vehicle status](#item-and-vehicle-status-item-7), with verified APIs. |
| 8 | **Errors from the mod** in `console.txt` (session 2026-10-11 12:06-12:52). | 3 | Two mod errors, both explained; fixed in code (gym 0.4.4 and 0.4.5), **not yet run in game**: C1 (exercise, 517 times) and C2 (vehicle scan, twice) in [Console errors](#console-errors-item-8). |

## Found 2026-10-11

| Item | Status |
|---|---|
| Two agents ran at once: on Windows `ThreadingHTTPServer` sets `SO_REUSEADDR`, so a second agent bound the same port without an error, and both answered the game and appended to one experience file. `logs/experience/20261011-11` and `-12` have broken gzip streams. | Fixed: the agent and the bridge bind their port with `SO_EXCLUSIVEADDRUSE` and exit if it is taken. The training reader (`agent/features.py`, `read_records`) salvages whatever whole lines remain in damaged files. |
| The speed flipped between 1× and 3× during exercise and after sleep: the game sets 1× at the end of every exercise, and 3× when the character falls asleep, and the mod adopted the game's changes as the owner's pick. | Fixed (mod 0.5.1, hot-reloaded): only the owner's own speed changes (button or key) count. Exercise is no longer offered when the fitness screen would refuse it, and one duration per exercise is offered per decision instead of six. |
| The time was in every observation (`t.hour`), though a player sees it only on a watch or clock. | `obs.clock` (gym 0.4.6) gives the time only while a watch or alarm clock is worn or held, with the date and temperature on a digital one. The network's encoder (`agent/features.py`) uses `obs.clock` and never `t`. |

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
* The console log of 2026-10-11 12:06-12:52 confirms the first point: the session ran after the lesson 2 fix
  (commit 4d53766, merged 11:54) and still logged the `Fitness.incRegularity` exception 517 times (C1 below).

## Speech and announcements (item 5)

Recorded 2026-10-11; nothing removed yet. Paths are under `mod/AIvZ/42/media/lua/client/`.

**The mod's own `p:Say` calls (all in `AIvZ.lua`):**

| Line | Text | Runs while the agent plays? |
|---|---|---|
| 2082 | "AI online. Let's survive this." (`A.onGameStart`) | yes, at every game start |
| 1862 | "I've got it from here." (manual control ends) | yes, after you take over with the keys and let go |
| 621 | "This place will do. Home." / "I'll make this my new home." (`A.maybeSetHome`) | no, rules baseline only |
| 867 | "Too many of them!" (flee reflex) | no, rules baseline only |
| 1761 | any `say` text in `intent.txt` (field 6, the language model's line) | no, rules baseline only |

**The game's own text, triggered by the gym.** "Not safe to sleep here." is the game's `IGUI_Sleep_NotSafe`,
shown with `HaloTextHelper.addBadText` by `ISWorldObjectContextMenu.onSleepWalkToComplete`
(`client/ISUI/ISWorldObjectContextMenu.lua:1034-1047`, with `ContextMenu_PainNoSleep` and
`ContextMenu_PanicNoSleep`). The gym's `sleep` calls `onConfirmSleep` directly; a player would instead see
Sleep greyed out in the menu and never reach that code. Offering Sleep only when the menu would (gap list
item 3) stops it. Other gym verbs also call vanilla handlers directly; whether those show halo text is
**not audited**.

**Reasons the gym makes up and hands to the network.** `U.fail(t, reason)` texts reach the network as
`last.msg` in `obs.json`, and the HUD. The sleep ones (`AIvZGym.lua:819-826`: "not safe, zombies in sight",
"too panicked", "too much pain") are guessed afterwards from `getNumVisibleZombies()` and moodles; the
others come from pathfinding and internal checks ("no way there", "can't reach it", "couldn't reach it",
"took too long", "blocked", "no free square", "didn't get it", "not bandaged", "couldn't reach the bed",
"standing in furniture (...)", "item gone", "didn't move", "unsupported: ...", "error: ..."). Proposal: the
network gets only the status (`done` / `failed` / `running`) and whatever visibly changed; the reason
texts go to the debug log and the HUD only. The rules baseline has the same sleep texts (`AIvZ.lua:1680-1687`).

## Guard rails (item 6)

Recorded 2026-10-11; nothing removed yet. **Stays:** the game's own prerequisites, the rules the game's
menus and screens apply to a player. Removing those would give the network actions a player doesn't have.
Examples: Eat is greyed out at `FOOD_EATEN` >= 3 ("Can't eat more", `client/ISUI/ISInventoryPaneContextMenu.lua:500`);
Drink's 3-litre, sealed and `FOOD_EATEN` rules (`:2313`); the Sleep conditions (gap list item 3); Next on the
traits screen disabled below 0 points; climbing only where `canClimbThrough` allows it.
**Goes:** the repo's own rules, listed here.

1. **Caps that hide valid choices** (`G.options`, `AIvZGym.lua:288-480`):
   * walk/run in 8 fixed directions
   * the nearest 5 buildings
   * the nearest 5 rooms on this floor
   * attack: at most 4 zombies, within 8 tiles; shove: at most 2, within 1.6 tiles
   * doors 4, windows 4, climb 2, smash 2, clear_glass 1, curtains 3
   * search 6, take 12, eat 6, drink 2, equip 3, wear 3, take_off 4, drop 6, craft 5
   * taps 2, bandage 3
   * vehicles: the nearest 2 within 4 tiles (`AIvZGymActions.lua`)
   * `stow`: a rotating window of 12
   * `G.observe`: 40 inventory items

   Replace the caps with paging or categories so that every choice stays reachable
   (PHASE3_COVERAGE.md, "Action interface", point 3).
2. **Choices filtered for usefulness:**
   * `equip` is offered only for `HandWeapon`, though the game lets any item go in a hand.
   * `bandage` is offered only on wounded parts, and only with the first bandage found.
   * `take` is offered only within 2.5 tiles of a container already searched.
   * `search` is offered only for containers not searched before.
   * Sleep in a bed only uses the nearest bed in the current building.
   * attack/shove need a visible zombie, though a player can swing at nothing.
3. **Macros that decide for the network:**
   * `enter`: `A.travelStep`, which ranks entry windows by lock state (`AIvZ.lua:1322-1410`), then opens,
     smashes or climbs.
   * `A.stepOff` (`AIvZGym.lua:981-990`): steps off furniture by itself, fails the running action and
     blocks decisions until it is done.
   * Walking to the bed (`bedStep`).
   * Moving the bandage into the main inventory.
4. **When the network may decide:**
   * `G.needDecision` asks for a new decision on "hurt", "zombie close" or "still at it", spaced by
     `DECIDE_GAP` and `RECHECK`.
   * `G.settled` blocks decisions for about 15 s after each new life.

   **Owner decision:** keep these triggers, or ask at a fixed rate and let the network learn when to
   change course?
5. **Character creation** (`AIvZGymActions.lua`):
   * the spend / repay / done stages
   * the 12-pick limit
   * the fallback after 6 refusals
   * `creationRepair` removing traits

   The game's only rule is that Next is disabled while `PointToSpend()` < 0. Offer the screen's own buttons
   (add, remove, profession, Next when enabled) and nothing else.
6. **The random policy** (`agent/policies.py:20`) keeps `continue` 4 times as likely as any other option.
   This is a property of the policy, not of the environment, and goes when a learner replaces it.
7. **The rules baseline** (`AIvZ.lua`) is a scripted player:
   * flee at 3 or more zombies within 2 tiles
   * re-arm
   * choose a home
   * close doors and windows
   * sleep tasks
   * language-model intents

   It runs only when no agent is connected. **Owner decision:** keep it as a comparison player or delete it.
   The gym uses its helpers (`travelStep`, `stepOff`, `bedStep`, `scanBuilding`, `scanWater`,
   `buildingInfo`), so those need moving first.

## Item and vehicle status (item 7)

Recorded 2026-10-11 from `G.itemInfo` (`AIvZGym.lua:116-151`) and the installed 42.21 files. Every method
named below exists and is public on a class Lua can call; it was checked in `projectzomboid.jar`, and
nothing has been run in game.

**What the network gets today:**

| Kind | Gets | Doesn't get |
|---|---|---|
| Clothing | name, type, weight, `cat`, `worn` | condition, holes, patches, blood, dirt, wetness, insulation, wind/water resistance, bite/scratch/bullet defence, run/combat speed modifiers, body location |
| Weapons | `dmg` (maximum only), `cond`, `range`, `ranged`, `twoHand` | minimum damage, head/handle condition, sharpness, ammo type, rounds loaded/maximum, magazine type and whether one is in, round chambered, jammed, spent rounds, fire mode, attached parts |
| Ammo, magazines | category "other" | ammo type, rounds in a magazine, which weapon it fits |
| Vehicles | `enter_vehicle` options (distance, seat, model name); inside: seat, engine running | every part, condition, fuel, battery, tyres, doors/windows, keys, speed, dashboard |

**What a player sees, and where it comes from:**

* **Clothing.** The inventory tooltip (`Clothing.DoTooltip`, jar) shows:
  * condition
  * insulation; wind and water resistance
  * bloody, dirty, wet
  * holes
  * bite, scratch and bullet defence, compared with what is worn in that slot
  * mask filter or tank
  * run and combat speed modifiers

  The Inspect window (`client/ISUI/ISGarmentUI.lua`) shows the hole, blood, patch and defence of each body
  part. The protection panel (`client/XpSystem/ISUI/ISCharacterProtection.lua`) shows totals per body part
  through `IsoGameCharacter:getBodyPartClothingDefense(Integer, boolean, boolean)`.

  Methods:
  * `getCondition()`, `getConditionMax()`
  * `getInsulation()`, `getWindresistance()`, `getWaterResistance()`
  * `getBloodLevel()`, `getDirtiness()`, `getWetness()`, `isWet()`
  * `getHolesNumber()`, `getPatchesNumber()`
  * `getBiteDefense()`, `getScratchDefense()`, `getBulletDefense()`
  * `getRunSpeedModifier()`, `getCombatSpeedModifier()`
  * `getBodyLocation()`, `getCoveredParts()`
  * per part: `getDefForPart(BloodBodyPartType, boolean, boolean)`, `getBloodlevelForPart(...)`,
    `getPatchType(...)`, `getVisual():getHole(part)`
* **Weapons.** The tooltip (`HandWeapon.DoTooltip`, jar) shows:
  * sharpness, condition, handle and head condition
  * damage minimum to maximum
  * bloody, range, two-handed, fire mode
  * the max-exertion warning
  * rounds loaded / maximum, magazine and ammo type
  * "Weapon jammed. Rack it.", "Spent round in chamber" / "No round in chamber"
  * spent rounds, "Contains Magazine" / "Need Magazine to operate"
  * attached parts

  Methods:
  * `getMinDamage()`, `getMaxDamage()`
  * `getHeadCondition()`, `getHeadConditionMax()`
  * `hasSharpness()`, `getSharpness()`, `getMaxSharpness()`
  * `getAmmoType()`: returns an `AmmoType`; `AmmoType:getItemKey()` is the round's item type
  * `getMagazineType()`, `getCurrentAmmoCount()`, `getMaxAmmo()`
  * `isContainsClip()`, `haveChamber()`, `isRoundChambered()`, `isSpentRoundChambered()`
  * `isJammed()`, `getSpentRoundCount()`
  * `getFireMode()`, `getFireModePossibilities()`, `getAllWeaponParts()`
* **Which ammo fits.** This is the game's reload menu,
  `ISInventoryPaneContextMenu.doReloadMenuForWeapon` (`client/ISUI/ISInventoryPaneContextMenu.lua`):
  * A weapon with `getMagazineType()` takes that magazine item (insert with
    `getBestMagazine(IsoGameCharacter)`, or eject).
  * Otherwise it loads loose rounds of `getAmmoType():getItemKey()` (`doBulletMenu`).
  * Unjam and rack follow `ISReloadWeaponAction.canRack`.

  Magazines carry `getAmmoType()`, `getCurrentAmmoCount()` and `getMaxAmmo()` (on `InventoryItem`). A
  player learns compatibility from the names on the tooltips and from which reload options appear.
* **Vehicles.**
  * Part conditions appear only in the Mechanics window. It walks to the hood, opens it (unlocking if
    needed) and opens the window: `ISVehicleMenu.onMechanic`, `client/Vehicles/ISUI/ISVehicleMenu.lua:960`;
    `ISOpenMechanicsUIAction`.
  * The window lists every part with its condition %, battery charge %, fuel %, and missing parts in red
    (`ISVehicleMechanics:doDrawItem`).
  * The dashboard while driving (`client/Vehicles/ISUI/ISVehicleDashboard.lua`) is **not audited**.

  Methods:
  * `BaseVehicle:getPartCount()`, `getPartByIndex(i)`, `getPartById(id)`. These are declared on
    `VehiclePartOwner` and used by vanilla Lua.
  * `VehiclePart:getId()`, `getCategory()`, `getCondition()`, `getInventoryItem()`
  * `getContainerContentAmount()`, `getContainerCapacity()`, `isContainer()`
  * `getDoor()`, `getWindow()`, `getLight()`
  * battery: `part:getInventoryItem():getCurrentUsesFloat()`
  * `BaseVehicle:isEngineWorking()`, `getCurrentSpeedKmHour()`

**Work items:**

| # | Item | Notes |
|---|---|---|
| O1 | **Started (gym 0.4.11, untested in game; methods as listed, each wrapped so a failure leaves the field out):** `G.clothingStatus` adds condition, insulation, wind/water resistance, blood, dirt, wetness, holes, patches, bite/scratch/bullet defence, slot. Not done: per-part defence and holes, protection panel. Clothing status in each clothing item's record: the tooltip fields above, plus per-part defence and holes from the Inspect window | Tooltips cost no game time, so they can sit in every observation for items in the inventory or an open container. The protection panel's per-part totals can go in `obs.body`. |
| O2 | **Started (gym 0.4.11, same caveat):** `G.weaponStatus` adds min damage, sharpness, head condition, fire mode and the ranged fields below. Weapon status: the tooltip fields above | Same. |
| O3 | **Started (gym 0.4.11, same caveat):** weapons carry `ammo`, `mag`, `loaded`, `maxAmmo`, `clip`, `chambered`, `jammed`, `spent`; rounds and magazines carry `ammo`, `loaded`, `maxAmmo` (`G.ammoStatus`). Not done: reload/rack/unjam actions. Ammo and magazines: their own type, rounds in a magazine; each weapon's ammo type and magazine type | Use one item-type identifier on both sides (weapon `ammo` = round's item type, `mag` = magazine item type), so matching is learnable from what the tooltips say, not given as a precomputed "fits" flag. The reload, insert, eject, rack and unjam actions are gap list item 21. |
| O4 | Vehicles: an `inspect_vehicle` action (the Mechanics window), then the part list as an observation, remembered until seen again | Outside view (open doors, smashed windows) and the dashboard need auditing first. Refuel, siphon, install and uninstall are gap list item 15. |
| O5 | Other tooltips not yet audited: food (freshness, calories, nutrition), literature (read or not), bags (weight reduction), drainables (uses left), keys (which car or door) | Audit as for O1 and O2 before building. |
| O6 | Encoding | Dozens of fields per item, for 40+ items, need a per-kind feature layout that the network can take in. **Interim (no layout change):** `features.item_status_tokens` turns the new fields into hashed tokens (ammo and magazine item types as names, binned condition, holes, jammed...), for carried and held items, so `features.VERSION` stays 1. A dense per-kind layout is still open (it would bump the version). |

## Console errors (item 8)

From `C:\Users\fab_f\Zomboid\console.txt`: session 2026-10-11 12:06-12:52, 37,210 lines, loader "OK v0.5.0".
It ran after commit 4d53766, so gym 0.4.3 with the "set current exercise" fix. Line numbers below are from
that version.

* **C1, exercise, 517 times.**
  * Error: `NullPointerException: Cannot read field "type" because "this.currentExe" is null` at
    `Fitness.incRegularity(Fitness.java:227)`, from `ISFitnessAction:exeLooped`
    (`shared/TimedActions/ISFitnessAction.lua:124`). Console lines 563-37145. Each one dumps a full stack
    trace, which makes up most of the log.
  * Cause: `exercise` calls `ISFitnessAction:new(p, name, 25, data)` without the fifth argument
    `exeDataType`. `new` calls `fitness:setCurrentExercise(exeDataType)`, setting it to nil and undoing the
    gym's own `setCurrentExercise` (`AIvZGymActions.lua:66`).
  * Fixed in code, not yet run in game:
    * Gym 0.4.4 (PR #21) passes `exeDataType`, matches equipment by full type and adds the fitness screen's
      limits and a 10-60 minute duration.
    * 0.4.4 read the duration and the limit from `o.minutes` / `o.blocked`, which are always nil (the
      option's fields are in `o.data`), so every exercise would have failed with "unsupported". Gym 0.4.5
      reads `o.data`. A new unit test checks every executor for this.
  * Still open: moving the equipment into the hands (`ISFitnessUI:equipItems`).
  * Live test: no `Fitness.incRegularity` exception, and endurance falls.
* **C2, vehicle scan, twice.**
  * Error: `attempted index: getVehicleContainer of non-table: null` at `AIvZGymActions.lua:139`
    (`nearVehicles`, from the vehicle option hook in `G.options` ← `G.request` ← tick). First at console
    line 2591.
  * Cause: `sqAt(...)` returns nil for a square that isn't loaded at the edge of the 4-tile scan. `try`
    catches the error, but Kahlua still logs every caught exception with a stack dump.
  * Fixed in code by gym 0.4.5, not yet run in game: the square is checked for nil before it is indexed.
    General rule: test for an expected nil, don't lean on `pcall`/`try` to skip it.
* **Not from the mod:** warnings about vanilla content, such as SpriteConfig `Wooden_Windows`, `Coffin` and
  `Key_Duplicator` entity scripts, the `Build_AnvilStone` icon, AngelCodeFont textures, map object files for
  the Kentucky towns, and recursive requires in WorldGen. Nothing to do.

## Found in the 42.21 audit, not fixed (2026-10-11)

Each line is open. Details, APIs and file references are in [GAP_LIST.md](GAP_LIST.md) (G#),
[OBSERVATION_AUDIT.md](OBSERVATION_AUDIT.md) section 5 (L#) and [ACTION_CATALOGUE.md](ACTION_CATALOGUE.md).

**Information the network gets but a player wouldn't (G1):**

* L1 raw `stats` (11 internal values, including food sickness)
* L2 unseen rooms in `go_room` and in the building opening counts
* L3 beds in unseen rooms and on unseen floors
* L4 time without a watch or alarm clock; date and temperature without a digital one; `weather.temp` is
  not the temperature the clock shows
* L5 objects behind walls within 1.5 tiles (`perceivable`)
* L6 poison used to classify drinks (`isPoisonous()` in `U.waterIn`)
* L7 window `locked`
* L8 vehicles within 4 tiles regardless of sight
* L9 zombie identity kept across occlusion (`closing`)
* L10 exact health, position, world age and exercise endurance; glass reported under a bandage
* L11 the `enter` macro's window choice by lock state
* L12 the zombie visibility proxy (`isCanSee` plus light >= 0.2 instead of the game's spotted list)

**Verbs that are wrong:**

* G2 `exercise`: fixed in code by gym 0.4.4 and 0.4.5 (see C1), apart from moving the equipment into the
  hands. Not yet run in game.
* G3 `sleep` skips "not tired enough" and "too soon".
* G4 `drink` lacks the thirst > 0.1 and beverage/bleach rules and the half/quarter portions.
* G5 `engine_on` lacks the key/hotwire/working-engine check; no Hotwire.
* G6 Trait points:
  * the gym reads the field `pointToSpend`, not `PointToSpend()`
  * NEXT is pressed while the game has it disabled
  * no profession choice
  * traits are removed in a way the screen doesn't offer

**Verb prerequisites (G7):**

* `smash` is offered for open windows.
* `clear_glass` doesn't check for an item in the primary hand.
* `equip`:
  * offers only weapons
  * doesn't check hand wounds or fractures
  * has no secondary hand or both hands
* `rest`:
  * is offered in a vehicle or already sitting
  * can't stand up
  * can't rest on furniture
* `drop` drops favourites, and works in a vehicle with the doors and windows shut.
* `take` doesn't use `ISInventoryTransferUtil` (corpse items).
* `drink_tap` keeps the nearest 5 before filtering by visibility.
* `enter` truncates to 16 buildings before filtering.

**Missing families (gap list items 8-23):**

* G8 floor items and corpses
* G9 a general adapter for the vanilla menus
* G10 drinking from sources, filling, washing, stoves, lights
* G11 medical care beyond bandages
* G12 reading
* G13 continuous movement and stance (crouch, sneak, sprint, aim)
* G14 barricading, lock and unlock, fences, sheets
* G15 vehicles beyond entering. No verified Lua path for driving: `CarController` is not exposed, and the
  `BaseVehicle` setters are untested.
* G16-G23:
  * full crafting
  * repairs and tailoring
  * generators and appliances
  * farming, foraging, fishing, trapping and animals
  * building and disassembly
  * firearms and hotbar
  * map, radio and TV
  * the new-game flow
