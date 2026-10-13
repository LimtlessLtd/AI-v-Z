-- AIvZGym.lua: Project Zomboid as a gym for the self-taught agent (agent/ in the repo).
--
--   obs.json OUT  when a decision is needed: observations and a capped subset of implemented player
--                 options. No hearing input yet. Written again with "dead" when the character dies.
--   act.txt  IN   "id|option|note" from the agent (option is 0-based; note shows on the HUD)
--   gym.txt  IN   heartbeat "on|n" from the agent. While it keeps changing, the agent plays instead of the
--                 rules baseline (the keys still hand control to you, as before)
--
-- The implemented options approximate a subset of the right-click menus: wait, rest, walk or run in a
-- direction, go into a building or another room, attack or shove a zombie, open or close a door, window or
-- curtain, lock or unlock a door with its key, barricade a door or window with planks or pry the planks off,
-- hang a sheet on a window, climb through a window, smash one,
-- clear its glass, search a container, a corpse or a bag on the ground, take an item out of one it has searched,
-- pick an item up off the ground (one, half or all of a pile), drag a corpse and let go of it, disassemble furniture, drop/eat/drink/equip/wear/take off an item, craft one of an item's own recipes, drink
-- from a tap, bandage a wound, sleep, sneak or stand up. Nothing in here judges what's good: the agent learns
-- that from what happens. The doing (pathfinding, swings, the game's timed actions) comes from AIvZ.lua.
-- After a death, it starts a new character in a random town of the game's spawn screen, at that town's own
-- start points, by pressing the game's own buttons in code (G.respawnStep).

require "TimedActions/ISWashClothing"
require "TimedActions/ISWashYourself"

local A = AIvZ
local U = A.u
A.gym = A.gym or {}
local G = A.gym
-- 0.4.57 was taken twice (PR #102 the health panel, PR #103 search for 8 containers): 0.4.58 is both
G.VERSION = "0.4.83"
-- Trait picking at character creation (AIvZGymActions.lua, G.creation), under the owner's option B rule (a
-- debt limit, then bad traits only until the points are back to 0). Off, the trait screen's Next is pressed
-- with no traits chosen (gym 0.4.8 had it off while the rule was redone).
G.CHOOSE_TRAITS = true
G.s = G.s or { id = 0, waiting = false, cur = nil, beat = nil, beatAt = 0, beatCheck = 0, lastReq = -99999 }
local GS = G.s
GS.gt = GS.gt or 0
if GS.lastReq > GS.gt then GS.lastReq = -99999 end   -- reloaded over a version that counted real ticks
local try, P, sqAt, Q, qlen, r1, r2 = U.try, U.P, U.sqAt, U.Q, U.qlen, U.r1, U.r2
local H = A.hud

-- While an option runs, the agent is asked whether to carry on at a steady rate (the owner's decision of
-- 2026-10-12, backlog N7), and at once when a zombie it can see comes within 4 tiles with no wall between (the
-- owner's decision the same day, gym 0.4.23). Until gym 0.4.20 a drop in health also asked at once, at most every
-- 45 ticks, and otherwise every 600: while a wound bled that was about once a second, 39% of all decisions, and it
-- cut off every flee. "hurt" now waits for the steady rate; the reason still says what changed since the last
-- decision ("hurt", "zombie close" or "still at it"). An option that ends asks at once.
-- STEADY is in game-time ticks (GS.gt: a tick at 5x speed counts five times), so the agent gets the same rhythm
-- of decisions per game minute at any speed you pick: 150 is about a game minute, 3 s at 1x. Gym 0.4.21 had 90
-- (0.6 game minutes): a walk or run takes 3-3.6 game minutes to finish, and a young network that keeps the running
-- option only now and then (7% of the time in the first lives) cut nearly every one short.
-- Gym 0.4.21-0.4.22 had the zombie on the steady rate too: one that came into view 2 tiles off reached the
-- character in 1-3 s (close zombies close at 0.65 tiles/s, median at 1x, 1.1 for the fastest quarter), while the
-- next decision was up to 3 s away. The agent answers in about 25 ms, so the decision itself costs no time.
local STEADY = 150
local ANSWER_WAIT = 600    -- real ticks: give up waiting for the agent and ask again
local DIRECT_RECIPES = { "RipClothing", "OpenCannedFood", "OpenCannedFoodWithKnifeOrSharpStoneFlake" }
local DIRS = { { "N", 0, -1 }, { "NE", 1, -1 }, { "E", 1, 0 }, { "SE", 1, 1 }, { "S", 0, 1 }, { "SW", -1, 1 },
	{ "W", -1, 0 }, { "NW", -1, -1 } }

local function tick() return A.s.tick end
local function dist(p, x, y) return math.sqrt((x - p:getX()) ^ 2 + (y - p:getY()) ^ 2) end
-- Zombies the game has spotted for this character: J:IsoPlayer.updateLOS/getSpottedList (installed 42.21;
-- OBSERVATION_AUDIT section 1). The old square/light proxy disagreed in the local comparison (L12).
-- Use this membership for observations, options, directions and close-zombie triggers, without another
-- guessed light threshold. The light threshold below still applies to nearby objects, not zombies.
local LIGHT_MIN, NEAR = 0.2, 1.5

local function squareLight(sq, pn)
	return sq and try(function() return sq:getLightLevel(pn) end)
end

local function visibleZombies(p, R)
	local out, shown = {}, {}
	local spotted = p:getSpottedList()
	if not spotted then return out end
	for i = 0, spotted:size() - 1 do
		local z = spotted:get(i)
		if instanceof(z, "IsoZombie") then shown[z] = true end
	end
	-- A.zombies retains the existing same-floor, alive, distance and obstruction checks, nearest first.
	for _, e in ipairs(A.zombies(p, R)) do
		if shown[e.z] then out[#out + 1] = e end
	end
	return out
end

-- What a player can tell about a zombie they see: where it is, whether it is down, whether a wall is in the
-- way, and (from watching it) how far it has closed in since the last decision that saw it. The game's own
-- chase target (z:getTarget()) is hidden AI state and is deliberately not exposed to the agent.
GS.zprev = GS.zprev or setmetatable({}, { __mode = "k" })
local function zombieView(e)
	local now, prev = tick(), GS.zprev[e.z]
	if prev and prev.at == now then return prev.view end   -- observe and options share one view per tick
	local closing
	if prev and now - prev.at <= 900 then closing = r1(prev.d - e.d) end
	-- which way it faces, as a player sees from its body (gym 0.4.25): 1 straight at the character, -1 straight
	-- away. Its forward direction is what the body shows, not where its AI is headed.
	local facing
	local fx, fy = e.z:getForwardDirectionX(), e.z:getForwardDirectionY()
	local fn = math.sqrt(fx * fx + fy * fy)
	if fn > 0 and e.d > 0 then facing = r1(-(fx * e.dx + fy * e.dy) / (fn * e.d)) end
	local view = { dx = r1(e.dx), dy = r1(e.dy), d = r1(e.d), closing = closing, blocked = e.blocked, facing = facing,
		down = try(function() return e.z:isOnFloor() end) == true }
	GS.zprev[e.z] = { d = e.d, at = now, view = view }
	return view
end

-- a square the character can make things out on right now: in line of sight and lit enough, or right next to it
local function perceivable(p, sq, d)
	if not sq then return false end
	-- next to the character: not through a wall (the loot window's rule is reachability; couldSee is the line-of-sight flag)
	if d <= NEAR then return try(function() return sq:isCouldSee(p:getPlayerNum()) end) ~= false end
	if try(function() return sq:isCanSee(p:getPlayerNum()) end) ~= true then return false end
	local l = squareLight(sq, p:getPlayerNum())
	return l == nil or l >= LIGHT_MIN
end

local function seen(p)
	local m = U.mem(p)
	m.seen = m.seen or {}   -- containers this character has looked into, by "x,y,z,n"
	return m.seen
end

---------------------------------------------------------------- is the agent connected?
function G.active()
	local now = getTimestampMs()
	if now - GS.beatCheck > 1000 then
		GS.beatCheck = now
		local line = U.readFirstLine("gym.txt")
		if line and line:sub(1, 2) == "on" and line ~= GS.beat then GS.beat, GS.beatAt = line, now end
	end
	return GS.beat ~= nil and now - GS.beatAt < 6000
end

---------------------------------------------------------------- what an item is, for the agent
local function category(it)
	if instanceof(it, "Food") then return "food" end
	if U.waterIn(it, true) then return "drink" end
	if U.medKind(it) then return "medical" end
	if instanceof(it, "HandWeapon") then return "weapon" end
	if instanceof(it, "InventoryContainer") then return "bag" end
	if instanceof(it, "Clothing") then return "clothing" end
	if instanceof(it, "Literature") then return "literature" end
	return "other"
end

-- Item status a player reads off the tooltip (backlog O1-O3). Every call is wrapped: a method that fails leaves
-- its field out. Item types are given the same way on weapon and ammo sides ("ammo", "mag") so that what fits
-- what is learned from them, not handed over as a flag. Method names are from the 42.21 jar; not run in game.
local function status(i, key, f)
	local v = try(f)
	if type(v) == "number" then v = r2(v) end
	if v ~= nil then i[key] = v end
end

function G.weaponStatus(i, it)
	status(i, "minDmg", function() return it:getMinDamage() end)
	status(i, "sharp", function() return it:hasSharpness() and it:getSharpness() / math.max(0.01, it:getMaxSharpness()) or nil end)
	status(i, "head", function()
		local m = it:getHeadConditionMax()
		return m and m > 0 and it:getHeadCondition() / m or nil
	end)
	if i.ranged then
		status(i, "ammo", function() local a = it:getAmmoType(); return a and a:getItemKey() end)
		status(i, "mag", function() return it:getMagazineType() end)
		status(i, "loaded", function() return it:getCurrentAmmoCount() end)
		status(i, "maxAmmo", function() return it:getMaxAmmo() end)
		status(i, "clip", function() return it:isContainsClip() and 1 or 0 end)
		status(i, "chambered", function() return it:isRoundChambered() and 1 or 0 end)
		status(i, "jammed", function() return it:isJammed() and 1 or 0 end)
		status(i, "spent", function() return it:getSpentRoundCount() end)
		status(i, "fire", function() return it:getFireMode() end)
	end
end

-- rounds and magazines: their own type, and how many rounds a magazine holds
function G.ammoStatus(i, it)
	if instanceof(it, "HandWeapon") then return end
	local a = try(function() return it:getAmmoType() end)
	if a then
		status(i, "ammo", function() return a:getItemKey() end)
		status(i, "loaded", function() return it:getCurrentAmmoCount() end)
		status(i, "maxAmmo", function() return it:getMaxAmmo() end)
	end
end

function G.clothingStatus(i, it)
	status(i, "cond", function()
		local m = it:getConditionMax()
		return m and m > 0 and it:getCondition() / m or nil
	end)
	status(i, "insul", function() return it:getInsulation() end)
	status(i, "wind", function() return it:getWindresistance() end)
	status(i, "waterRes", function() return it:getWaterResistance() end)
	status(i, "blood", function() return it:getBloodLevel() end)
	status(i, "dirt", function() return it:getDirtiness() end)
	status(i, "wet", function() return it:getWetness() end)
	status(i, "holes", function() return it:getHolesNumber() end)
	status(i, "patches", function() return it:getPatchesNumber() end)
	status(i, "bite", function() return it:getBiteDefense() end)
	status(i, "scratch", function() return it:getScratchDefense() end)
	status(i, "bullet", function() return it:getBulletDefense() end)
	status(i, "slot", function() return tostring(it:getBodyLocation()) end)
end

function G.itemInfo(p, it)
	local i = { name = it:getDisplayName(), type = it:getType(), cat = category(it),
		w = r2(try(function() return it:getUnequippedWeight() end) or 0) }
	if instanceof(it, "Food") then
		i.hunger = r2(try(function() return it:getHungerChange() end) or 0)
		i.thirst = r2(try(function() return it:getThirstChange() end) or 0)
		i.unhappy = r2(try(function() return it:getUnhappyChange() end) or 0)
		i.rotten = try(function() return it:isRotten() end) == true
		i.cooked = try(function() return it:isCooked() end) == true
		i.raw = (try(function() return it:isbDangerousUncooked() end) == true) and not i.cooked
		i.sealed = U.sealedCan(it) or (try(function() return it:getScriptItem():isCantEat() end) == true)
	end
	local water = U.waterIn(it, true)
	if water then i.water = r2(water) end
	local fc = try(function() return it:getFluidContainer() end)
	local amount = fc and try(function() return fc:getAmount() end)
	if amount and amount >= 0.05 then
		i.fluid = r2(amount)
		i.fluidType = try(function() return fc:getPrimaryFluid():getFluidTypeString() end)
	end
	local med = U.medKind(it)
	if med then i.med = med end
	if instanceof(it, "HandWeapon") then
		local cm = it:getConditionMax()
		i.dmg = r2(it:getMaxDamage())
		i.cond = cm > 0 and r2(it:getCondition() / cm) or 0
		i.range = r2(it:getMaxRange())
		i.ranged = it:isRanged() == true
		i.twoHand = it:isTwoHandWeapon() == true
		G.weaponStatus(i, it)
	end
	G.ammoStatus(i, it)
	if instanceof(it, "Clothing") then G.clothingStatus(i, it) end
	if instanceof(it, "InventoryContainer") then i.cap = U.bagCapacity(it) end
	if instanceof(it, "Clothing") or instanceof(it, "InventoryContainer") then
		i.worn = try(function() return p:isEquipped(it) end) == true
	end
	G.itemStatus(i, p, it)
	return i
end

-- More of what the inventory shows a player (gym 0.4.64, backlog O5; read in the decompiled 42.21 jar and the Lua):
-- * food: what its name says (Food.getName: Fresh while age < offAge, Rotten from offAgeMax, Stale between; Burnt;
--   Uncooked for a cookable one not cooked; Frozen), and the tooltip's other changes (Food.DoTooltip: endurance,
--   stress, boredom), with calories only when the tooltip shows nutrition: a package the character can read (not
--   illiterate, not too dark, labelled) or the Nutritionist trait;
-- * a drainable: the Remaining bar (ISInventoryPane:drawItemDetails, unless HIDE_REMAINING);
-- * literature: has been read (Literature.DoTooltip, its title) and how far into a book (pages);
-- * a bag: its weight reduction (InventoryContainer.DoTooltip).
function G.itemStatus(i, p, it)
	if instanceof(it, "Food") then
		if it:isBurnt() then
			i.burnt = true
		elseif not it:isFertilized() then
			local age, off, offMax = it:getAge(), it:getOffAge(), it:getOffAgeMax()
			if off < 1000000000 and age < off then i.fresh = "fresh"
			elseif offMax < 1000000000 and age >= offMax then i.fresh = "rotten"
			elseif offMax < 1000000000 and age >= off then i.fresh = "stale" end
		end
		if not i.cooked and not i.burnt and it:isIsCookable() and not it:hasTag(ItemTag.HIDE_COOKED) and not it:hasTag(ItemTag.HIDE_UNCOOKED) then
			i.uncooked = true
		end
		if it:isFrozen() then i.frozen = true end
		if it:getEnduranceChange() ~= 0 then i.endurance = r2(it:getEnduranceChange()) end
		if it:getStressChange() ~= 0 then i.stress = r2(it:getStressChange()) end
		if it:getBoredomChange() ~= 0 then i.boredom = r2(it:getBoredomChange()) end
		local readable = it:isPackaged() and not p:hasTrait(CharacterTrait.ILLITERATE) and not p:tooDarkToRead()
			and it:getModData().NoLabel == nil
		if readable or p:hasTrait(CharacterTrait.NUTRITIONIST) or p:hasTrait(CharacterTrait.NUTRITIONIST2) then
			i.kcal = math.floor(it:getCalories() + 0.5)
		end
	end
	if instanceof(it, "Drainable") and not it:hasTag(ItemTag.HIDE_REMAINING) then i.left = r2(it:getCurrentUsesFloat()) end
	if instanceof(it, "Literature") then
		local title = it:getModData().literatureTitle
		if title then i.beenRead = p:isLiteratureRead(title) end
		if it:getNumberOfPages() > 0 then i.pages = r2(it:getAlreadyReadPages() / it:getNumberOfPages()) end
	end
	if instanceof(it, "InventoryContainer") and it:getWeightReduction() ~= 0 then i.reduce = it:getWeightReduction() end
end

---------------------------------------------------------------- what the character perceives
-- The character's traits, as the character screen lists them (ISCharacterScreen reads them the same way), with
-- the labels the trait screen used: what the agent picked at creation, plus any its profession gave
function G.traits(p)
	local out = {}
	try(function()
		local known = p:getCharacterTraits():getKnownTraits()
		for i = 0, known:size() - 1 do
			local def = CharacterTraitDefinition.getCharacterTraitDefinition(known:get(i))
			out[#out + 1] = def and def:getLabel() or tostring(known:get(i))
		end
	end)
	return out
end

local function isClock(it) return it ~= nil and (instanceof(it, "AlarmClock") or instanceof(it, "AlarmClockClothing")) end

-- What the screen's clock shows, or nil. The game shows it (zombie.ui.Clock.resize) for a watch or alarm
-- clock that is worn, or one in the main inventory that is worn or in a hand. A digital one (ItemTag.DIGITAL)
-- also shows the date and the temperature; an analogue one, the time.
function G.clock(p)
	local seen, digital = false, false
	local function look(it)
		seen = true
		if try(function() return it:hasTag(ItemTag.DIGITAL) end) then digital = true end
	end
	local worn = p:getWornItems()
	for i = 0, worn:size() - 1 do
		local it = worn:getItemByIndex(i)
		if isClock(it) then look(it) end
	end
	U.eachItem(p:getInventory(), function(it)
		if isClock(it) and (it:isWorn() or it:isEquipped()) then look(it) end
	end, 1)
	if not seen then return nil end
	local gt = getGameTime()
	local c = { hour = gt:getHour(), min = gt:getMinutes(), digital = digital }
	if digital then
		c.day, c.month = gt:getDay() + 1, gt:getMonth() + 1
		-- what the clock shows: the air temperature at the character (ClimateManager.getAirTemperatureForCharacter)
		c.temp = r1(try(function() return getClimateManager():getAirTemperatureForCharacter(p) end) or 0)
	end
	return c
end

-- the protection panel's numbers (ISCharacterProtection): per body part, the bite and scratch defence of the worn
-- clothing covering it, a garment with a hole over that part not counting, at most 100. In 42.21 a garment's
-- defence goes only when a hole opens over a part, a patch replaces the fabric, or its condition reaches 0
-- (Clothing.getDefForPart, getBiteDefense), so this is what wear does to protection.
function G.protection(p)
	local out = {}
	for i = 0, BodyPartType.ToIndex(BodyPartType.MAX) - 1 do
		local bite = try(function() return p:getBodyPartClothingDefense(i, true, false) end)
		local scratch = try(function() return p:getBodyPartClothingDefense(i, false, false) end)
		if bite and scratch then
			out[#out + 1] = { part = BodyPartType.ToString(BodyPartType.FromIndex(i)), bite = math.floor(bite + 0.5),
				scratch = math.floor(scratch + 0.5) }
		end
	end
	return out
end

-- whether the character carries the Knox infection. A player isn't told (the game rolls it when a zombie wound
-- lands: scratch 7%, laceration 25%, bite always), so features.py keeps it out of the network's input; only the
-- reward reads it, to charge the coming death when the infection happens (REWARD_RESEARCH.md)
function G.knox(p)
	local bd = p:getBodyDamage()
	if try(function() return bd:IsInfected() end) == true then return true end
	local parts = bd:getBodyParts()
	for i = 0, parts:size() - 1 do
		if try(function() return parts:get(i):IsInfected() end) == true then return true end
	end
	return false
end

function G.observe(p, dead)
	local o = {}
	local gt, cm = getGameTime(), getClimateManager()
	local d = p:getDescriptor()
	local m = U.mem(p)
	o.who = { name = d:getForename() .. " " .. d:getSurname(), save = tostring(getWorld():getWorld()) }
	local profession = d:getCharacterProfession()   -- CharacterCreationProfession.lua:1097, installed 42.21
	o.profession = profession and tostring(profession) or nil
	-- o.t is bookkeeping for the reward and the logs: a player sees the time only on a watch or clock
	-- (o.clock), and the darkness ("dark") always
	o.t = { age = r2(gt:getWorldAgeHours()), day = gt:getNightsSurvived() + 1, hour = gt:getHour(), min = gt:getMinutes(),
		dark = r2(try(function() return cm:getNightStrength() end) or 0) }
	o.kills = m.kills or 0
	if dead then o.dead = true; return o end
	if not m.born then m.born = o.t.age end
	o.born = m.born
	o.pos = { x = r1(p:getX()), y = r1(p:getY()), z = math.floor(p:getZ()) }
	o.health = r1(p:getBodyDamage():getOverallBodyHealth())
	o.moodles = {}
	for _, k in ipairs(U.MOODLES) do
		local v = U.moodle(p, k)
		if v > 0 then o.moodles[k:lower()] = v end
	end
	o.speed = try(function() return gt:getTrueMultiplier() end) or try(function() return gt:getMultiplier() end)   -- read only
	o.clock = G.clock(p)
	o.traits = G.traits(p)
	o.body = A.wounds(p)
	o.protection = G.protection(p)
	o.knox = G.knox(p)   -- reward only, never the network's input
	local l = squareLight(p:getCurrentSquare(), p:getPlayerNum())
	o.light = { known = l ~= nil, here = l and r2(l) or nil }
	o.asleep = try(function() return p:isAsleep() end) == true
	-- the character's own stance, as the player sees it (gym 0.4.25)
	o.sneaking, o.running = p:isSneaking() == true, (p:isRunning() or p:isSprinting()) == true
	o.sitting = p:isSitting() == true   -- visible body posture, gym 0.4.41; a hashed token in features.py
	o.sittingOnFurniture = p:isSittingOnFurniture() == true   -- distinguish the menu's floor fallback (gym 0.4.42)
	o.dragging = p:isDraggingCorpse() == true   -- a corpse in tow (gym 0.4.35)
	o.weather = { rain = r2(try(function() return cm:getRainIntensity() end) or 0) }   -- no temperature: only a digital clock shows it (o.clock.temp)
	o.weight, o.maxWeight = r1(p:getInventory():getCapacityWeight()), r1(p:getMaxWeight())
	local held = p:getPrimaryHandItem()
	o.held = held and G.itemInfo(p, held) or nil
	o.inv = {}
	U.eachItem(p:getInventory(), function(it)
		if #o.inv < 40 and it ~= held and not it:isHidden() then o.inv[#o.inv + 1] = G.itemInfo(p, it) end
	end)
	o.zombies = {}
	for i, e in ipairs(visibleZombies(p, 30)) do
		if i > 40 then break end
		o.zombies[#o.zombies + 1] = zombieView(e)
	end
	-- a zombie that left view is forgotten: a player can't tell a look-alike that comes back from the same one
	for z, m in pairs(GS.zprev) do if m.at ~= tick() then GS.zprev[z] = nil end end
	local sq = p:getCurrentSquare()
	local room = sq and sq:getRoom()
	o.where = { outside = p:isOutside(), room = room and try(function() return room:getName() end) or nil }
	local info = A.buildingInfo(p, false)
	if info then
		o.where.building = info.id
		-- only openings on squares the player has seen: the whole-floor scan counts rooms never visited (audit leak 2)
		local pn = p:getPlayerNum()
		local function seen(list)
			local n = 0
			for _, e in ipairs(list) do
				if e.sq == nil or try(function() return e.sq:isSeen(pn) end) ~= false then n = n + 1 end
			end
			return n
		end
		o.where.doorsOpen, o.where.windowsOpen, o.where.curtainsOpen = seen(info.doorsOpen), seen(info.windowsOpen), seen(info.curtainsOpen)
		o.where.smashed = info.smashedAt and seen(info.smashedAt) or info.smashed
	end
	-- what it remembers is in containers it has looked into nearby
	o.near = { food = 0, drink = 0, medical = 0, weapon = 0, items = 0 }
	G.scanAround(p)
	for _, c in ipairs(GS.around.containers) do
		if c.known and c.d <= 12 then
			U.eachItem(c.c, function(it)
				o.near.items = o.near.items + 1
				local k = category(it)
				if o.near[k] then o.near[k] = o.near[k] + 1 end
			end, 1)
		end
	end
	o.speed = U.getSpeed()
	if G.householdObservation then o.household = G.householdObservation(p) end
	return o
end

---------------------------------------------------------------- the surroundings, scanned once per decision
-- doors, windows, curtains and containers on this floor within 8 tiles
-- What the Disassemble menu would read for an object (ISDisassembleMenu.createMenu: ISMoveableSpriteProps.fromObject,
-- and a multi-tile object only while its whole sprite grid stands), kept per object: at 20x decisions come several
-- times a second. Only the objects the last scan looked at are kept (G.scanAround swaps in the new set). The game's
-- Lua (Kahlua, projectzomboid.jar se/krka/kahlua) has no weak tables, no __mode anywhere, so a table keyed by
-- objects keeps every one alive: gym 0.4.28-0.4.54 kept every object ever scanned, across lives, and the game ran out
-- of Java heap after 31k and 87k decisions (2026-10-12 17:15, 2026-10-13 04:10). A reload drops the old table.
GS.moveProps = {}
local SCRAP_RANGE = 3
-- Fences: a square's north and west edges, with the flags the Interact key reads (IsoPlayer.doContextHopOverFence:
-- HoppableN/W on the square; doContextClimbOverWall for the tall ones). `back` is the climb from the other side.
local FENCE_RANGE = 6
local FENCE_EDGES = nil   -- built on first use, so nothing here reads a game global while the file loads
local function fenceEdges()
	FENCE_EDGES = FENCE_EDGES or {
		{ low = IsoFlagType.HoppableN, tall = IsoFlagType.TallHoppableN, dx = 0, dy = -1, north = true, dir = "N", back = "S" },
		{ low = IsoFlagType.HoppableW, tall = IsoFlagType.TallHoppableW, dx = -1, dy = 0, north = false, dir = "W", back = "E" },
	}
	return FENCE_EDGES
end
local function scrapProps(o, keep)
	local mp = GS.moveProps[o]
	if mp == nil then
		-- guarded: the menu only reads objects a player clicks, and an error here would take every option down.
		-- A failure is cached, so it is logged once while the object stays in range.
		mp = try(function() return ISMoveableSpriteProps.fromObject(o) end) or false
		if mp and mp.isMultiSprite and not mp:getSpriteGridInfo(o:getSquare(), true) then mp = false end
	end
	keep[o] = mp
	return mp or nil
end

-- a door or window: it sits on the north or west edge of its square, so `other` is the square on the far side
local function addOpening(out, p, o, sq, d, pz)
	local other = o:getNorth() and sqAt(sq:getX(), sq:getY() - 1, pz) or sqAt(sq:getX() - 1, sq:getY(), pz)
	local ext = (sq:getBuilding() ~= nil) ~= (other ~= nil and other:getBuilding() ~= nil)
	local e = { o = o, sq = sq, d = d, exterior = ext, open = try(function() return o:IsOpen() end) == true,
		locked = U.winIs(o, "isLocked") }
	if U.isDoor(o) then
		-- the menu says "Door Is Locked" when couldBeOpen(player) is false, which counts keys (observation audit, leak 7)
		local cbo = try(function() return o:couldBeOpen(p) end)
		if cbo ~= nil then e.locked = cbo ~= true end
		out.doors[#out.doors + 1] = e
		-- a sheet hung on a door is its curtain (IsoDoor:HasCurtains() returns the door itself), drawn from the
		-- sheet's side of the doorway (getSheetSquare), as the door menu does (gym 0.4.33)
		if instanceof(o, "IsoDoor") and o:HasCurtains() then
			out.curtains[#out.curtains + 1] = { o = o, sq = o:getSheetSquare() or sq, d = d, open = o:isCurtainOpen(), door = true }
		end
	else
		e.smashed = U.winIs(o, "isSmashed")
		e.glass = e.smashed and not U.winIs(o, "isGlassRemoved")
		e.barricaded = U.winIs(o, "isBarricaded")
		out.windows[#out.windows + 1] = e
		local cur = o:HasCurtains()
		if cur then out.curtains[#out.curtains + 1] = { o = cur, sq = cur:getSquare() or sq, d = d, open = cur:IsOpen() } end
	end
end

function G.scanAround(p)
	if GS.around and GS.around.tick == tick() then return GS.around end
	local px, py, pz = math.floor(p:getX()), math.floor(p:getY()), math.floor(p:getZ())
	local here = p:getCurrentSquare()
	local hb = here and here:getBuilding()
	local out = { tick = tick(), doors = {}, windows = {}, curtains = {}, containers = {}, floor = {}, scrap = {}, fences = {},
		corpses = {}, lights = {}, stoves = {}, water = {}, household = {}, plumbing = {} }
	local keep = {}   -- the Disassemble readings of the objects this scan looks at (GS.moveProps)
	local known = seen(p)
	local vis = {}
	local function sees(dx, dy)
		local k = (dx + 9) * 32 + dy + 9
		if vis[k] == nil then vis[k] = perceivable(p, sqAt(px + dx, py + dy, pz), math.sqrt(dx * dx + dy * dy)) end
		return vis[k]
	end
	for dx = -8, 8 do
		for dy = -8, 8 do
			local sq = sqAt(px + dx, py + dy, pz)
			local d = math.sqrt(dx * dx + dy * dy)
			if sq and not sees(dx, dy) then
				-- A door or window is on the wall between two squares, and the game keeps it on the square to the
				-- south or east of that wall: one on a room's east or south wall belongs to the square outside.
				-- With its curtain drawn, at night, or behind a closed door that square is out of sight, and gym
				-- 0.4.30 and earlier listed nothing on it, so the window the player looks at from inside vanished
				-- (2026-10-12: a bathroom whose door was locked; it opened the window, drew the curtain, and never
				-- saw the window, the curtain or a way to climb out again). Seen from the near side, it counts.
				local north, west = sees(dx, dy - 1), sees(dx - 1, dy)
				if north or west then
					for _, o in ipairs(U.objList(sq)) do
						if (U.isDoor(o) or U.isWindow(o)) and (o:getNorth() and north or not o:getNorth() and west) then
							addOpening(out, p, o, sq, d, pz)
						end
					end
				end
			elseif sq then   -- perceivable: not through walls or in the dark
				local n = 0
				for _, c in ipairs(U.containersOn(sq)) do
					n = n + 1
					local key = (px + dx) .. "," .. (py + dy) .. "," .. pz .. "," .. n
					out.containers[#out.containers + 1] = { c = c, sq = sq, d = d, key = key, known = known[key] == true,
						indoors = sq:getBuilding() ~= nil, type = tostring(c:getType()) }
				end
				-- items on the ground and corpses, as the loot window lists them (ISInventoryPage:refreshBackpacks:
				-- getWorldObjects() and getStaticMovingObjects() with a container) (gym 0.4.27)
				local wobs = sq:getWorldObjects()
				for i = 0, wobs:size() - 1 do
					local w = wobs:get(i)
					local it = w:getItem()
					if it then
						out.floor[#out.floor + 1] = { w = w, it = it, sq = sq, d = d }
						-- a bag lying there is a container of its own, as the loot window lists it (refreshBackpacks:
						-- getCategory() "Container", item:getInventory()) (gym 0.4.35)
						if it:getCategory() == "Container" and instanceof(it, "InventoryContainer") then
							local key = "bag:" .. it:getID()
							out.containers[#out.containers + 1] = { c = it:getInventory(), sq = sq, d = d, key = key,
								known = known[key] == true, indoors = sq:getBuilding() ~= nil, type = "bag",
								name = it:getDisplayName(), bag = true }
						end
					end
				end
				local sobs = sq:getStaticMovingObjects()
				for i = 0, sobs:size() - 1 do
					local so = sobs:get(i)
					local c = so:getContainer()
					if c then
						local key = "body:" .. (px + dx) .. "," .. (py + dy) .. "," .. pz .. "," .. i
						out.containers[#out.containers + 1] = { c = c, sq = sq, d = d, key = key, known = known[key] == true,
							indoors = sq:getBuilding() ~= nil, type = "corpse" }
					end
					if instanceof(so, "IsoDeadBody") and not so:isAnimal() then
						out.corpses[#out.corpses + 1] = { b = so, sq = sq, d = d }
					end
				end
				for _, o in ipairs(U.objList(sq)) do
					-- Actual visible fixture references; no truncation before visibility or substitution
					-- of another object later on the same square. The baseline's scan stays separate.
					if U.waterAmount(o) > 0 then
						out.water[#out.water + 1] = { src = o, w = { x = sq:getX(), y = sq:getY(), z = sq:getZ(), d = r1(d),
							name = o:getTileName() or o:getObjectName(), tainted = o:isTaintedWater() == true } }
					end
					if G.householdScan then G.householdScan(p, o, sq, d, out) end
					if d <= SCRAP_RANGE and not instanceof(o, "IsoWorldInventoryObject") then
						local mp = scrapProps(o, keep)
						if mp and mp.canScrap then out.scrap[#out.scrap + 1] = { o = o, mp = mp, sq = sq, d = d } end
					end
					if U.isDoor(o) or U.isWindow(o) then addOpening(out, p, o, sq, d, pz) end
					-- a light switch, as the world menu fetches one (J:ISWorldObjectContextMenuLogic.fetch, 42.21): on a
					-- square in a room, or one that can be modified (gym 0.4.60)
					if instanceof(o, "IsoLightSwitch") and (sq:getRoom() ~= nil or o:getCanBeModified()) then
						out.lights[#out.lights + 1] = { o = o, sq = sq, d = d }
					end
					-- a stove or microwave, as the world menu fetches one (fetch: IsoStove with a container) (gym 0.4.62)
					if instanceof(o, "IsoStove") and o:getContainer() then out.stoves[#out.stoves + 1] = { o = o, sq = sq, d = d } end
				end
				-- fences on this square's edges (gym 0.4.33). Each edge is listed once, from the side the character is on:
				-- it stands on that square and climbs toward the other. "drop": nothing to stand on beyond
				-- (IsoPlayer.isSafeToClimbOver: the Interact key then climbs only when held, not tapped).
				if d <= FENCE_RANGE then
					for _, edge in ipairs(fenceEdges()) do
						local low, tall = sq:has(edge.low), sq:has(edge.tall)
						if low or tall then
							local other = sqAt(px + dx + edge.dx, py + dy + edge.dy, pz)
							local mine = (edge.north and p:getY() >= sq:getY()) or (not edge.north and p:getX() >= sq:getX())
							local stand, far = sq, other
							if not mine then stand, far = other, sq end
							if stand and far and stand:isFree(false) then
								out.fences[#out.fences + 1] = { sq = sq, stand = stand, far = far, north = edge.north,
									dir = mine and edge.dir or edge.back, tall = not low,
									drop = not (far:TreatAsSolidFloor() or far:HasStairsBelow()),
									d = dist(p, stand:getX() + 0.5, stand:getY() + 0.5),
									ex = sq:getX() + (edge.north and 0.5 or 0), ey = sq:getY() + (edge.north and 0 or 0.5) }
							end
						end
					end
				end
			end
		end
	end
	local byD = function(a, b) return a.d < b.d end
	table.sort(out.doors, byD); table.sort(out.windows, byD); table.sort(out.curtains, byD); table.sort(out.containers, byD)
	table.sort(out.floor, byD); table.sort(out.scrap, byD); table.sort(out.fences, byD); table.sort(out.corpses, byD)
	table.sort(out.lights, byD); table.sort(out.stoves, byD)
	table.sort(out.water, function(a, b) return a.w.d < b.w.d end)
	table.sort(out.household, byD); table.sort(out.plumbing, byD)
	out.building = hb
	GS.moveProps = keep
	GS.around = out
	return out
end

---------------------------------------------------------------- the options
-- each option gets its own copy of the info: one item can be eaten, dropped and crafted, and those must not
-- share (they did: the agent was told "drop Cabbage" for what the game would have eaten)
local function add(list, verb, info, data)
	local i = {}
	for k, v in pairs(info) do i[k] = v end
	i.verb = verb
	list[#list + 1] = { verb = verb, info = i, data = data or {} }
end

local function count(list, verb)
	local n = 0
	for _, o in ipairs(list) do if o.verb == verb then n = n + 1 end end
	return n
end

-- the water source on a square, as the water scan found it (A.scanWater: an object holding fluid), or nil
local function waterObjectAt(x, y, z)
	local sq = sqAt(x, y, z)
	if not sq then return nil end
	for _, o in ipairs(U.objList(sq)) do if U.waterAmount(o) > 0 then return o end end
end

-- Wash submenu, installed 42.21 J:ISWorldObjectContextMenuLogic.doWashClothingMenu/setWashClothingTooltip.
-- It reads the main inventory, not items inside bags; soap is optional. A body's wash can use partial water,
-- but an item or a category's Wash All needs the full amount displayed on its tooltip.
local function washSource(p, src)
	local sq = src and src:getSquare()
	return sq and src:getObjectIndex() ~= -1 and sq:getBuilding() == p:getBuilding() and src:hasWater()
		and not instanceof(src, "IsoClothingWasher") and not instanceof(src, "IsoClothingDryer")
		and not instanceof(src, "IsoCombinationWasherDryer")
end
local function washGroups(p)
	local inv, groups = p:getInventory(), {}
	local function collect(name, items, allowed)
		local group = { name = name, items = {} }
		for i = 0, items:size() - 1 do
			local it = items:get(i)
			if allowed(it) then group.items[#group.items + 1] = it end
		end
		table.sort(group.items, function(a, b) return ISWashClothing.GetRequiredSoap(a) < ISWashClothing.GetRequiredSoap(b) end)
		if #group.items > 0 then groups[#groups + 1] = group end
	end
	collect("clothing", inv:getItemsFromCategory("Clothing"), function(it)
		return not it:isHidden() and (it:hasBlood() or it:hasDirt()) and not it:hasTag(ItemTag.BREAK_WHEN_WET)
	end)
	collect("bandages", inv:getAllTag(ItemTag.CAN_BE_WASHED), function(it) return it:getJobDelta() == 0 end)
	collect("weapons", inv:getItemsFromCategory("Weapon"), function(it) return it:hasBlood() end)
	collect("containers", inv:getItemsFromCategory("Container"), function(it)
		return not it:isHidden() and (it:hasBlood() or it:hasDirt())
	end)
	return groups
end
local function washOptions(p, list, sources)
	if #sources == 0 then return end
	local groups = washGroups(p)
	local bodyWater = ISWashYourself.GetRequiredWater(p)
	if #groups == 0 and bodyWater == 0 then return end
	local soaps = p:getInventory():getSoapList(nil, true)
	local soapLeft = ISWashClothing.GetSoapRemaining(soaps)
	for _, s in ipairs(sources) do
		local src, w = s.src, s.w
		if washSource(p, src) then
			local water = src:getFluidAmount()
			if bodyWater > 0 and water >= 1 then
				add(list, "wash_yourself", { name = w.name, d = w.d,
					noSoap = ISWashYourself.GetSoapRemaining(soaps) < ISWashYourself.GetRequiredSoap(p) }, { src = src })
			end
			for _, group in ipairs(groups) do
				local soapNeeded, waterNeeded = ISWorldObjectContextMenu.calculateSoapAndWaterRequired(group.items)
				if water >= waterNeeded then
					add(list, "wash", { name = group.name, from = w.name, d = w.d, how = "all", noSoap = soapLeft < soapNeeded },
						{ src = src, items = group.items })
				end
				for _, it in ipairs(group.items) do
					if water >= ISWashClothing.GetRequiredWater(it) then
						add(list, "wash", { name = it:getDisplayName(), type = it:getFullType(), from = w.name, d = w.d,
							noSoap = soapLeft < ISWashClothing.GetRequiredSoap(it) }, { src = src, items = { it } })
					end
				end
			end
		end
	end
end

-- Treatment as the health panel offers it (client/XpSystem/ISUI/ISHealthPanel.lua, 42.21; gym 0.4.57). Its
-- handlers look for supplies in every container ISInventoryPaneContextMenu.getContainers lists (the inventory and
-- its bags, and the containers the loot window shows by the character) and in the bags inside those
-- (BaseHandler:checkItems, :1037-1067); the item tests are each handler's checkItem.
local function medSupplies(p)
	local out, done = {}, {}
	local pn = p:getPlayerNum()
	if not getPlayerInventory(pn) or not getPlayerLoot(pn) then return out end
	local function scan(c, children)
		local items = c:getItems()
		for i = 0, items:size() - 1 do
			local it = items:get(i)
			if not it:IsInventoryContainer() then out[#out + 1] = it
			elseif children then children[#children + 1] = it:getInventory() end
		end
	end
	local containers = ISInventoryPaneContextMenu.getContainers(p)
	for i = 0, containers:size() - 1 do
		local c, children = containers:get(i), {}
		done[c] = true
		scan(c, children)
		for _, c2 in ipairs(children) do
			if not done[c2] then done[c2] = true; scan(c2, nil) end
		end
	end
	return out
end
local function isPlank(t) return t == "Plank" or t == "TreeBranch2" or t == "WoodenStick2" or t == "TreeBranch" or t == "WoodenStick" end
local MED = {
	bandage = function(it) return it:getBandagePower() > 0 end,   -- HApplyBandage :1153
	disinfect = function(it)   -- HDisinfect :1310-1321: at least 40% alcohol, more than 0.15 L; or a drainable of power 4
		if it:hasComponent(ComponentType.FluidContainer) then
			local fc = it:getFluidContainer()
			return fc:getAmount() > 0.15 and fc:getProperties():getAlcohol() / fc:getAmount() + 0.001 >= 0.4
		end
		return it:IsDrainable() and it:getAlcoholPower() == 4.0
	end,
	suture = function(it) return it:getType() == "SutureNeedle" end,   -- HStitch :1366-1376
	needle = function(it) return it:getType() == "Needle" or it:hasTag(ItemTag.SEWING_NEEDLE) end,
	thread = function(it) return (it:getType() == "Thread" or it:hasTag(ItemTag.THREAD)) and it:getCurrentUsesFloat() >= 0 end,
	glass = function(it)   -- HRemoveGlass :1483-1487
		return it:hasTag(ItemTag.REMOVE_GLASS) or it:getType() == "SutureNeedleHolder" or it:getType() == "Tweezers"
	end,
	bullet = function(it)   -- HRemoveBullet :1673-1677
		return it:hasTag(ItemTag.REMOVE_BULLET) or it:getType() == "Tweezers" or it:getType() == "SutureNeedleHolder"
	end,
	burn = function(it) return it:getBandagePower() >= 2 end,   -- HCleanBurn :1721-1725
	splint = function(it) return it:getType() == "Splint" end,   -- HSplint :1543-1552
	plank = function(it) return isPlank(it:getType()) end,
	sheet = function(it) return it:getType() == "RippedSheets" end,
}
-- HApplyComfrey, HApplyGarlic, HApplyPlantain (:1284-1300): an item of that type, and the action that applies it
local POULTICES = {
	{ type = "PlantainCataplasm", cls = function() return ISPlantainCataplasm end, on = function(bp) return bp:getPlantainFactor() > 0 end },
	{ type = "ComfreyCataplasm", cls = function() return ISComfreyCataplasm end, on = function(bp) return bp:getComfreyFactor() > 0 end },
	{ type = "WildGarlicCataplasm", cls = function() return ISGarlicCataplasm end, on = function(bp) return bp:getGarlicFactor() > 0 end },
}
local function firstOf(items, test) for _, it in ipairs(items) do if test(it) then return it end end end
-- the first item of each kind that passes, as the menus list a kind once (BaseHandler:getAllItemTypes)
local function eachKind(items, test)
	local out, seen = {}, {}
	for _, it in ipairs(items) do
		if not seen[it:getFullType()] and test(it) then seen[it:getFullType()] = true; out[#out + 1] = it end
	end
	return out
end
-- BaseHandler:isInjured (:1032-1035)
local function injured(bp) return (bp:HasInjury() or bp:stitched() or bp:getSplintFactor() > 0) and not bp:bandaged() end

-- The inventory menu's Take Pills (ISInventoryPaneContextMenu.lua, 42.21; gym 0.4.59): a DrainableComboItem tagged
-- CONSUMABLE (:301-307). When it lists items it needs to hand (getRequireInHandOrInventory, a lighter for something
-- smoked), the entry is greyed out unless one of them, not used up, is in the inventory, or a smokable can be lit
-- in the vehicle or from an open flame (doPillsMenu :1140-1173).
local function notUsedUp(it) return it:getCurrentUsesFloat() > 0 end
-- The inventory menu's Read (ISInventoryPaneContextMenu.lua, 42.21; gym 0.4.61). Literature: category Literature,
-- not a notebook one can write in, not print media (:242-244). Greyed out (doLiteratureMenu :1030-1137): too dark to
-- read, asleep, illiterate unless it's pictures, a skill book more than a level above the skill or at or below it;
-- and the handler skips a blank notebook (UNINTERESTING, onLiteratureItems :2804-2819). "reread" when the menu says
-- Re-read (the title was read before).
-- The inventory menu's firearm entries (ISInventoryPaneContextMenu.lua, 42.21; gym 0.4.65). For any HandWeapon with
-- an ammo type (doReloadMenuForWeapon :1876-1903): eject the magazine, or insert the best one the character has
-- (getBestMagazine; greyed out without one); a gun without magazines loads rounds when there are any to load and
-- unloads when it has some (doBulletMenu :1857-1874); unjam a jammed gun, or rack it (ISReloadWeaponAction.canRack).
-- Another fire mode when it has more than one (doChangeFireModeMenu :1793-1803). A magazine (getMaxAmmo() > 0, not a
-- weapon) loads rounds when it isn't full and there are some, and unloads when it has any (doMagazineMenu
-- :1970-1989). Its own Insert Magazine entry (doReloadMenuForMagazine) is left to the gun's, which takes the best.
local function withHow(info, how)
	local i = {}
	for k, v in pairs(info) do i[k] = v end
	i.how = how
	return i
end
local function gunOptions(list, p, it, info)
	local inv = p:getInventory()
	if instanceof(it, "HandWeapon") then
		if it:getAmmoType() then
			if it:getMagazineType() then
				if it:isContainsClip() then
					add(list, "eject_mag", info, { it = it })
				else
					local clip = it:getBestMagazine(p)
					if clip then add(list, "insert_mag", info, { it = it, mag = clip }) end
				end
			else
				local key = it:getAmmoType():getItemKey()
				if math.min(it:getMaxAmmo() - it:getCurrentAmmoCount(), inv:getItemCountRecurse(key)) > 0 then
					add(list, "load_rounds", info, { it = it })
				end
				if it:getCurrentAmmoCount() > 0 then add(list, "unload_rounds", info, { it = it }) end
			end
			if it:isJammed() then add(list, "rack", withHow(info, "unjam"), { it = it })
			elseif ISReloadWeaponAction.canRack(it) then add(list, "rack", info, { it = it }) end
		end
		local modes = it:getFireModePossibilities()
		if modes and modes:size() > 1 then
			for m = 0, modes:size() - 1 do
				local mode = modes:get(m)
				if mode ~= it:getFireMode() then add(list, "fire_mode", withHow(info, mode), { it = it, mode = mode }) end
			end
		end
	elseif it:getMaxAmmo() > 0 and it:getAmmoType() then
		if it:getCurrentAmmoCount() < it:getMaxAmmo() then
			local n = math.min(inv:getItemCountRecurse(it:getAmmoType():getItemKey()), it:getMaxAmmo() - it:getCurrentAmmoCount())
			if n > 0 then add(list, "load_mag", info, { it = it, n = n }) end
		end
		if it:getCurrentAmmoCount() > 0 then add(list, "unload_mag", info, { it = it }) end
	end
end
local function readEntry(p, it)
	if it:getCategory() ~= "Literature" or it:canBeWrite() or (it:hasModData() and it:getModData().printMedia) then return nil end
	if p:tooDarkToRead() or p:isAsleep() or it:hasTag(ItemTag.UNINTERESTING) then return nil end
	if p:hasTrait(CharacterTrait.ILLITERATE) and not it:hasTag(ItemTag.PICTUREBOOK) and not it:hasTag(ItemTag.PICTURE) then return nil end
	local book = SkillBook[it:getSkillTrained()]
	if book and book.perk then
		local lvl = p:getPerkLevel(book.perk)
		if it:getLvlSkillTrained() ~= -1 and it:getLvlSkillTrained() > lvl + 1 then return nil end
		if it:getMaxLevelTrained() ~= -1 and it:getMaxLevelTrained() <= lvl then return nil end
	end
	local title = it:getModData().literatureTitle
	return (title and p:isLiteratureRead(title)) and "reread" or "read"
end
-- The inventory menu's Turn On / Turn Off (ISInventoryPaneContextMenu.lua :248-253 and :866-879, 42.21; gym 0.4.60):
-- an item that can be activated, in the hands or attached (not a weapon, not an SCBA), or worn with some use left;
-- not a drainable that's used up, not a lit candle or lantern (those have their own menus); a garment with nothing
-- left is greyed out
local function switchEntry(p, it)
	if not it:canBeActivated() then return false end
	local reach = ((p:isHandItem(it) or (p:isAttachedItem(it) and not instanceof(it, "HandWeapon"))) and not it:hasTag(ItemTag.SCBA))
		or (it:isWorn() and it:getCurrentUsesFloat() > 0)
	if not reach or (instanceof(it, "Drainable") and it:getCurrentUsesFloat() <= 0) then return false end
	local t = it:getType()
	if t == "CandleLit" or t == "Lantern_HurricaneLit" or it:hasTag(ItemTag.LIT_LANTERN) then return false end
	return not (instanceof(it, "Clothing") and it:getUsedDelta() == 0)
end
local function pillsEntry(p, it)
	if not it:hasTag(ItemTag.CONSUMABLE) or not instanceof(it, "DrainableComboItem") then return false end
	local need = it:getRequireInHandOrInventory()
	if not need then return true end
	if it:hasTag(ItemTag.SMOKABLE) then
		local v = p:getVehicle()
		if (v and v:canLightSmoke(p)) or ISInventoryPaneContextMenu.hasOpenFlame(p) then return true end
	end
	for i = 0, need:size() - 1 do
		if p:getInventory():getFirstTypeEvalRecurse(moduleDotType(it:getModule(), need:get(i)), notUsedUp) then return true end
	end
	return false
end

-- barricades (gym 0.4.36): the tools as the menus find them (J:ISWorldObjectContextMenuLogic.doBarricadeMenu's
-- hammer test, ISWorldObjectContextMenu's predicateRemoveBarricade), and the planks on one side of an opening
local function notBroken(it) return not it:isBroken() end
local function removesBarricade(it) return it:hasTag(ItemTag.REMOVE_BARRICADE) and not it:isBroken() end
local function planksOn(o, same)
	local b = same and o:getBarricadeOnSameSquare() or o:getBarricadeOnOppositeSquare()
	return b and b:getNumPlanks() or 0
end

-- The inventory menu's equip entries (ISInventoryPaneContextMenu.createMenu :426-436, doEquipOption :4129-4151):
-- Equip Two Hands for a two-handed weapon in working condition not already in both hands; Equip Primary while the
-- right hand has no deep wound and no fracture, or a splinted one, unless it's the primary item alone already.
-- Returns whether it's offered and whether with both hands. (gym 0.4.38)
local function equipEntry(p, it)
	if it:isTwoHandWeapon() and it:getCondition() > 0 then return not p:isItemInBothHands(it), true end
	if p:isPrimaryHandItem(it) and not p:isSecondaryHandItem(it) then return false end
	local hand = p:getBodyDamage():getBodyPart(BodyPartType.Hand_R)
	return not hand:isDeepWounded() and (hand:getFractureTime() == 0 or hand:getSplintFactor() > 0), false
end

-- Drop from inside a vehicle needs the seat's door, or that door's window, open: the menu greys Drop out otherwise
-- (ISInventoryPaneContextMenu.createMenu :351-371, :641-651, "ContextMenu_DropFromVehicle"). (gym 0.4.38)
local function shutIn(p)
	local v = p:getVehicle()
	if not v then return false end
	local doorPart = v:getPassengerDoor(v:getSeat(p))
	local windowPart = VehicleUtils.getChildWindow(doorPart)
	local door = doorPart and doorPart:getDoor()
	local window = windowPart and windowPart:getWindow()
	return (door and not door:isOpen() and window and not (window:isOpen() or window:isDestroyed())) and true or false
end

-- The bed menu's Rest (J:ISWorldObjectContextMenuLogic.doBedMenu, for a bed-flagged object): not when something is
-- between the bed and the free square next to it (its private isSomethingTo: IsoGridSquare.isSomethingTo from the
-- character's square, or from AdjacentFreeTileFinder.Find's when not next to it), someone is on it, or the
-- character sits on it already; and only in the same room or with its square in sight (isCanSee). (gym 0.4.39)
local function bedRestable(p, o)
	local sq, here = o:getSquare(), p:getCurrentSquare()
	if not (sq and here) then return false end
	local from = AdjacentFreeTileFinder.isTileOrAdjacent(here, sq) and here or AdjacentFreeTileFinder.Find(sq, p, nil)
	if from and sq:isSomethingTo(from) then return false end
	if o:isFurnitureOccupied(p) or (p:isSittingOnFurniture() and p:isSitOnFurnitureObject(o)) then return false end
	return sq:getRoom() == here:getRoom() or sq:isCanSee(p:getPlayerNum())
end

local function zombiesToward(zs, dname)
	local n = 0
	for _, e in ipairs(zs) do if e.d < 20 and U.dir8(e.dx, e.dy) == dname then n = n + 1 end end
	return n
end

-- Why the game's Sleep menu entry would be unavailable (J:ISWorldObjectContextMenuLogic.doSleepOption), as the
-- reason text the player sees; nil when sleeping is allowed. Only things on screen: tiredness moodle-style stat,
-- zombies in sight, recent sleep, pain and panic.
local function sleepBlock(p)
	local fatigue = try(function() return p:getStats():get(CharacterStat.FATIGUE) end)
	if fatigue and fatigue <= 0.3 then return "not tired enough" end
	local st = try(function() return p:getStats() end)
	if st then
		if (try(function() return st:getNumVisibleZombies() end) or 0) > 0 or (try(function() return st:getNumChasingZombies() end) or 0) > 0
			or (try(function() return st:getNumVeryCloseZombies() end) or 0) > 0 then return "not safe, zombies in sight" end
	end
	local since = try(function() return p:getHoursSurvived() - p:getLastHourSleeped() end)
	if since and since <= 1 then return "slept too recently" end
	if (try(function() return p:getSleepingTabletEffect() end) or 0) < 2000 then
		if U.moodle(p, "PAIN") >= 2 and (fatigue or 0) <= 0.85 then return "too much pain" end
		if U.moodle(p, "PANIC") >= 1 then return "too panicked" end
	end
	return nil
end

function G.options(p)
	local list = {}
	local pn = p:getPlayerNum()
	local cur = GS.cur
	if cur and cur.status == "running" then add(list, "continue", { what = cur.verb, age = tick() - cur.t0 }) end
	add(list, "wait", {})
	-- shared/TimedActions/ISWaitWhileGettingUp.lua and ISContextMenu:onGetUpAndThen (42.21):
	-- a separate Get Up choice for a seated character; `stand` below only ends sneaking.
	if p:isSitting() then add(list, "get_up", {}) end
	-- sitting down: not in a vehicle and not already sitting (the fitness screen's own test, GAP_LIST item 2;
	-- the calls are the ones AIvZ.lua already makes)
	if not p:getVehicle() and not (try(function() return p:isSitOnGround() or p:isSittingOnFurniture() end) == true) then
		add(list, "rest", {})
	end
	-- the C key (IsoPlayer.updateSneakKey toggles setSneaking): crouch and sneak, or stand back up. It stays as
	-- chosen while the character walks (more slowly when sneaking) until changed. Not in a vehicle.
	if not p:getVehicle() then add(list, p:isSneaking() and "stand" or "sneak", {}) end
	local zs = visibleZombies(p, 30)
	for _, d in ipairs(DIRS) do
		local n = zombiesToward(zs, d[1])
		add(list, "walk", { dir = d[1], dx = d[2], dy = d[3], zombies = n }, { dx = d[2], dy = d[3] })
		add(list, "run", { dir = d[1], dx = d[2], dy = d[3], zombies = n }, { dx = d[2], dy = d[3] })
	end
	-- buildings around (the nearest 5 apart from this one)
	local m = U.mem(p)
	m.visited = m.visited or {}
	m.bseen = m.bseen or {}   -- buildings the character has had in line of sight, kept like a map memory
	if not GS.blds or tick() - GS.blds.at > 240 then
		-- only buildings in sight now or remembered; what is inside (room names, looted/explored marks) is
		-- known only once visited
		local known = {}
		for _, b in ipairs(A.scanBuildings(p, 60)) do
			if try(function() return sqAt(b.tx, b.ty, b.tz):isCanSee(p:getPlayerNum()) end) == true then m.bseen[b.id] = true end
			if m.bseen[b.id] or m.visited[b.id] then
				if not m.visited[b.id] then b.rooms, b.looted, b.explored = nil, nil, nil end
				known[#known + 1] = b
			end
		end
		GS.blds = { at = tick(), list = known }
	end
	local here = A.buildingInfo(p, false)
	local nb = 0
	for _, b in ipairs(GS.blds.list) do
		if nb >= 5 then break end
		if not here or b.id ~= here.id then
			nb = nb + 1
			local crowd = 0
			for _, e in ipairs(zs) do
				if math.sqrt((e.dx - (b.tx - p:getX())) ^ 2 + (e.dy - (b.ty - p:getY())) ^ 2) < 8 then crowd = crowd + 1 end
			end
			add(list, "enter", { d = b.d, dx = r1(b.tx - p:getX()), dy = r1(b.ty - p:getY()), rooms = b.rooms,
				visited = m.visited[b.id] == true, zombies = crowd }, { tx = b.tx, ty = b.ty, tz = b.tz, id = b.id })
		end
	end
	-- other rooms of this building on this floor
	local sq = p:getCurrentSquare()
	local b = sq and sq:getBuilding()
	if b then
		local myRoom = sq:getRoom()
		local myDef = myRoom and try(function() return myRoom:getRoomDef() end)
		local rooms = b:getDef():getRooms()
		local rl = {}
		for i = 0, rooms:size() - 1 do
			local r = rooms:get(i)
			-- only rooms the character has seen (observation audit, leak 2); if the call fails the room is kept
			local explored = try(function() return r:isExplored() end)
			if r:getZ() == math.floor(p:getZ()) and r ~= myDef and explored ~= false then
				local cx, cy = r:getX() + r:getW() / 2, r:getY() + r:getH() / 2
				rl[#rl + 1] = { r = r, d = dist(p, cx, cy), dx = cx - p:getX(), dy = cy - p:getY() }
			end
		end
		table.sort(rl, function(a, c) return a.d < c.d end)
		-- the five nearest that go_room can go to: a room with no free square fails at once ("no free square", 109
		-- times in 13 minutes on 2026-10-13, the network picking it again and again), so it isn't offered (gym 0.4.67)
		local rooms5 = 0
		for _, e in ipairs(rl) do
			if rooms5 >= 5 then break end
			if try(function() return e.r:getFreeSquare() end) then
				rooms5 = rooms5 + 1
				add(list, "go_room", { name = try(function() return e.r:getName() end) or "room", d = r1(e.d), dx = r1(e.dx),
					dy = r1(e.dy), area = e.r:getW() * e.r:getH() }, { r = e.r })
			end
		end
	end
	-- zombies
	for _, e in ipairs(zs) do
		if e.d > 8 or count(list, "attack") >= 8 then break end
		local info = zombieView(e)
		add(list, "attack", info, { z = e.z })
		if e.d < 1.6 and count(list, "shove") < 8 then add(list, "shove", info, { z = e.z }) end
	end
	-- doors, windows, curtains, with where each one is (dx, dy from the character, as for the other options with a
	-- place): a player sees which door is the one between them and a zombie. Gym 0.4.22 and earlier gave the
	-- distance only.
	local ar = G.scanAround(p)
	local function at(e)
		return r1(e.sq:getX() + 0.5 - p:getX()), r1(e.sq:getY() + 0.5 - p:getY())
	end
	local inv = p:getInventory()
	-- Add Sheet: a window with no curtain, or a door that can take one, with a sheet anywhere in the inventory
	-- (doWindowMenu: HasCurtains() is nil; doDoorMenu: HasCurtains() is nil and canAddCurtain(); both
	-- containsTypeRecurse("Sheet")). The curtain it makes then has its own open and close option.
	local sheet = inv:containsTypeRecurse("Sheet")
	local nw, nc, ns, ng, nh = 0, 0, 0, 0, 0
	for i = 1, math.min(8, #ar.doors) do
		local e = ar.doors[i]
		local dx, dy = at(e)
		add(list, "door", { d = r1(e.d), dx = dx, dy = dy, open = e.open, locked = e.locked, exterior = e.exterior }, e)
		if sheet and nh < 2 and instanceof(e.o, "IsoDoor") and e.o:HasCurtains() == nil and e.o:canAddCurtain() then
			nh = nh + 1; add(list, "hang_sheet", { d = r1(e.d), dx = dx, dy = dy, exterior = e.exterior, door = true }, e)
		end
		-- Lock or Unlock: a closed door whose key is in the inventory (J:ISWorldObjectContextMenuLogic.doDoorMenu:
		-- not IsOpen, the door's key id, haveThisKeyId; Lock unless isLockedByKey). The key id as ISLockDoor:isValid
		-- reads it.
		if not e.open then
			local id = instanceof(e.o, "IsoDoor") and e.o:checkKeyId() or e.o:getKeyId()
			if id and id ~= -1 and inv:haveThisKeyId(id) then
				add(list, e.o:isLockedByKey() and "unlock_door" or "lock_door",
					{ d = r1(e.d), dx = dx, dy = dy, exterior = e.exterior }, e)
			end
		end
	end
	for _, e in ipairs(ar.windows) do
		if not e.barricaded then
			-- the lock state is not shown for a window (the game tells you only when you try it), so it is not listed
			local dx, dy = at(e)
			local info = { d = r1(e.d), dx = dx, dy = dy, open = e.open, exterior = e.exterior, smashed = e.smashed, glass = e.glass }
			if not e.smashed and nw < 8 then nw = nw + 1; add(list, "window", info, e) end
			if e.d < 2.5 and nc < 8 and try(function() return e.o:canClimbThrough(p) end) then
				nc = nc + 1; add(list, "climb", { d = info.d, dx = dx, dy = dy, exterior = e.exterior, glass = e.glass }, e)
			end
			-- the Smash entry exists only for a closed, unbroken window (ISWorldObjectContextMenuLogic.doWindowMenu)
			if e.d < 2.5 and not e.smashed and not e.open and ns < 8 then ns = ns + 1; add(list, "smash", { d = info.d, dx = dx, dy = dy, exterior = e.exterior }, e) end
			-- Remove Glass Shards needs something in the primary hand (the menu greys it out otherwise)
			if e.d < 2.5 and e.glass and p:getPrimaryHandItem() and ng < 8 then ng = ng + 1; add(list, "clear_glass", { d = info.d, dx = dx, dy = dy }, e) end
			if sheet and nh < 2 and e.o:HasCurtains() == nil then
				nh = nh + 1; add(list, "hang_sheet", { d = info.d, dx = dx, dy = dy, exterior = e.exterior }, e)
			end
		end
	end
	-- Barricade with planks, and Unbarricade, on doors and windows (J:ISWorldObjectContextMenuLogic.doBarricadeMenu:
	-- isBarricadeAllowed(), no barricade on the character's side or one that takes another plank, a hammer that isn't
	-- broken, a plank and 2 nails in the inventory, light enough to read by (the entry is greyed out otherwise);
	-- Unbarricade: planks on the character's side and a RemoveBarricade tool). A door only while shut
	-- (BuildRecipeCode.barricade.OnIsValidPlanks). The planks already up are what a player sees. (gym 0.4.36)
	local canBuild = inv:getFirstTagEvalRecurse(ItemTag.HAMMER, notBroken) ~= nil and inv:containsTypeRecurse("Plank")
		and inv:getItemCountRecurse("Base.Nails") >= 2 and not p:tooDarkToRead()
	local canPry = inv:getFirstEvalRecurse(removesBarricade) ~= nil
	if (canBuild or canPry) and not p:getVehicle() then
		local nb = 0
		for _, group in ipairs({ ar.doors, ar.windows }) do
			for _, e in ipairs(group) do
				if nb >= 4 then break end
				local isDoor = U.isDoor(e.o)
				local b = e.o:getBarricadeForCharacter(p)
				local dx, dy = at(e)
				local info = { d = r1(e.d), dx = dx, dy = dy, exterior = e.exterior, door = isDoor or nil,
					planks = b and b:getNumPlanks() or 0 }
				if canBuild and e.o:isBarricadeAllowed() and (not b or b:canAddPlank()) and not (isDoor and e.open) then
					nb = nb + 1; add(list, "barricade", info, e)
				end
				if canPry and b and b:getNumPlanks() > 0 then nb = nb + 1; add(list, "unbarricade", info, e) end
			end
		end
	end
	-- curtains, on windows and (gym 0.4.33) on doors; Remove curtains takes the sheet down into the inventory, greyed
	-- out by the menu when a sheet wouldn't fit (ISWorldObjectContextMenu.addRemoveCurtainOption)
	local sheetItem = getScriptManager():FindItem("Base.Sheet")
	local roomForSheet = sheetItem ~= nil and inv:hasRoomFor(p, sheetItem:getActualWeight())
	for i = 1, math.min(8, #ar.curtains) do
		local e = ar.curtains[i]
		local dx, dy = at(e)
		add(list, "curtain", { d = r1(e.d), dx = dx, dy = dy, open = e.open, door = e.door }, e)
		if roomForSheet and i <= 2 then add(list, "remove_sheet", { d = r1(e.d), dx = dx, dy = dy, door = e.door }, e) end
	end
	-- fences: climb over, as the Interact key does at a fence (IsoPlayer.doContextHopOverFence, doContextClimbOverWall
	-- for tall ones); the nearest edges, at most two per direction. A tall one next to the character only when the
	-- game would let it climb (canClimbOverWall: the Interact key does nothing otherwise).
	local mySq, perDir, nf = p:getCurrentSquare(), {}, 0
	for _, f in ipairs(ar.fences) do
		if nf >= 4 or p:getVehicle() then break end
		local can = not (f.tall and f.stand == mySq) or p:canClimbOverWall(IsoDirections[f.dir])
		if can and (perDir[f.dir] or 0) < 2 then
			perDir[f.dir], nf = (perDir[f.dir] or 0) + 1, nf + 1
			add(list, "climb_fence", { d = r1(f.d), dx = r1(f.ex - p:getX()), dy = r1(f.ey - p:getY()), dir = f.dir,
				tall = f.tall, drop = f.drop }, f)
		end
	end
	-- containers: search the ones not looked into yet; take from the ones it has, when standing by them.
	-- "here": in the building the character is in (or both outside); the rest are usually out of reach.
	local nt = 0
	for _, c in ipairs(ar.containers) do
		local here = c.sq:getBuilding() == ar.building
		if not c.known and count(list, "search") < 8 then
			add(list, "search", { d = r1(c.d), type = c.type, name = c.name, indoors = c.indoors, here = here }, c)
		elseif c.known and c.d < 2.5 and nt < 16 then
			U.eachItem(c.c, function(it)
				if nt < 16 and not it:isHidden() then
					nt = nt + 1
					local i = G.itemInfo(p, it)
					i.from, i.d, i.here = c.type, r1(c.d), here
					add(list, "take", i, { it = it, c = c.c })
				end
			end, 1)
		end
	end
	-- Disassemble: an object within SCRAP_RANGE tiles that the menu lists (canScrapObject(...).craftValid) and allows
	-- (.canScrap: the tools it needs are carried); "chance" is the menu's chance of getting the materials back
	local nd = 0
	for i, e in ipairs(ar.scrap) do
		if nd >= 4 or i > 8 then break end
		local result, chance = e.mp:canScrapObject(p)
		if result.craftValid and result.canScrap then
			nd = nd + 1
			add(list, "disassemble", { name = Translator.getMoveableDisplayName(e.mp.name), d = r1(e.d),
				dx = r1(e.sq:getX() + 0.5 - p:getX()), dy = r1(e.sq:getY() + 0.5 - p:getY()), chance = chance }, e)
		end
	end
	-- items on the ground in sight: pick one up (the world menu's Grab, ISWorldObjectContextMenu.onGrabWItem). The menu
	-- makes the items of one name on a square one entry, "Name (n)", with One, Half (more than 2) and All
	-- (J:ISWorldObjectContextMenuLogic.handleGrabWorldItem; onGrabHalfWItems takes ceil(n / 2)) (piles: gym 0.4.35)
	local piles, order = {}, {}
	for _, f in ipairs(ar.floor) do
		local k = f.sq:getX() .. "," .. f.sq:getY() .. "," .. tostring(f.it:getName())
		if not piles[k] then piles[k] = {}; order[#order + 1] = piles[k] end
		table.insert(piles[k], f)
	end
	for i = 1, math.min(6, #order) do
		local pile = order[i]
		local f, n = pile[1], #pile
		local info = G.itemInfo(p, f.it)
		info.d, info.dx, info.dy = r1(f.d), r1(f.sq:getX() + 0.5 - p:getX()), r1(f.sq:getY() + 0.5 - p:getY())
		add(list, "pick_up", info, f)
		if n > 2 then
			info.how, info.n = "half", math.ceil(n / 2)
			add(list, "pick_up", info, { w = f.w, it = f.it, sq = f.sq, items = { unpack(pile, 1, info.n) } })
		end
		if n > 1 then
			info.how, info.n = "all", n
			add(list, "pick_up", info, { w = f.w, it = f.it, sq = f.sq, items = pile })
		end
	end
	-- corpses: drag one, or let go of the one being dragged (the world menu's Grab > Corpse and Drop Corpse,
	-- J:ISWorldObjectContextMenuLogic.handleGrabWorldItem, ISWorldObjectContextMenu.handleGrabCorpseSubmenu: not an
	-- animal, not from a vehicle, not while carrying a corpse, not on a burning square) (gym 0.4.35)
	if p:isDraggingCorpse() then
		add(list, "drop_corpse", {})
	elseif not p:getVehicle() and inv:getItemCount("Base.CorpseMale") == 0 then
		for i = 1, math.min(2, #ar.corpses) do
			local e = ar.corpses[i]
			if not e.sq:haveFire() then
				add(list, "drag_corpse", { d = r1(e.d), dx = r1(e.b:getX() - p:getX()), dy = r1(e.b:getY() - p:getY()) }, e)
			end
		end
	end
	-- Turn a light on or off at its switch, as the switch's menu offers it (ISWorldObjectContextMenu.doLightSwitchOption,
	-- 42.21): nothing in the way between the character and it (isSomethingTo), and canSwitchLight (gym 0.4.60)
	for _, l in ipairs(ar.lights) do
		if not ISWorldObjectContextMenu.isSomethingTo(l.o, p:getPlayerNum()) and l.o:canSwitchLight() then
			add(list, "light_switch", { d = r1(l.d), dx = r1(l.sq:getX() + 0.5 - p:getX()), dy = r1(l.sq:getY() + 0.5 - p:getY()),
				how = l.o:isActivated() and "off" or "on" }, { o = l.o })
		end
	end
	-- Turn a stove or microwave on or off, as its menu offers it (J:ISWorldObjectContextMenuLogic.doStoveOption, 42.21):
	-- nothing in the way (isSomethingTo), and its container has power. Cooking is the rest of the player's own doing:
	-- search it, stow food in, switch on, take the food out. The menu's Settings open a window and are left out.
	-- (gym 0.4.62)
	for _, s in ipairs(ar.stoves) do
		if not ISWorldObjectContextMenu.isSomethingTo(s.o, p:getPlayerNum()) and s.o:getContainer():isPowered() then
			add(list, "stove", { d = r1(s.d), dx = r1(s.sq:getX() + 0.5 - p:getX()), dy = r1(s.sq:getY() + 0.5 - p:getY()),
				how = s.o:Activated() and "off" or "on", what = s.o:isMicrowave() and "microwave" or "stove" }, { o = s.o })
		end
	end
	-- the inventory
	local shut = shutIn(p)
	local held = p:getPrimaryHandItem()
	if held then add(list, "unequip", G.itemInfo(p, held), { it = held }) end
	if held then gunOptions(list, p, held, G.itemInfo(p, held)) end
	if held and switchEntry(p, held) then
		local info = G.itemInfo(p, held)
		info.how = held:isActivated() and "off" or "on"
		add(list, "switch_item", info, { it = held })
	end
	local crafts = 0
	local stuffed = U.moodle(p, "FOOD_EATEN") >= 3
	U.eachItem(p:getInventory(), function(it)
		if it == held or it:isHidden() then return end
		local info = G.itemInfo(p, it)
		local worn = info.worn
		if not stuffed and count(list, "eat") < 8 then
			local ok, opening = G.eatable(p, it)
			if ok then
				info.open = opening ~= nil
				add(list, "eat", info, { it = it, opening = opening })
				info.open = nil
			end
		end
		if count(list, "drink") < 8 then
			local amount, opening, portions = G.drinkable(p, it)
			if amount then
				info.open = opening ~= nil
				for _, portion in ipairs(portions) do
					info.portion = portion
					add(list, "drink", info, { it = it, opening = opening, portion = portion })
				end
				info.open, info.portion = nil, nil
			end
		end
		if pillsEntry(p, it) then add(list, "take_pill", info, { it = it }) end
		gunOptions(list, p, it, info)
		local reading = count(list, "read") < 8 and readEntry(p, it)
		if reading then
			info.how = reading
			add(list, "read", info, { it = it })
			info.how = nil
		end
		if switchEntry(p, it) then
			info.how = it:isActivated() and "off" or "on"
			add(list, "switch_item", info, { it = it })
			info.how = nil
		end
		if instanceof(it, "HandWeapon") and count(list, "equip") < 8 then
			local ok, both = equipEntry(p, it)
			if ok then add(list, "equip", info, { it = it, both = both }) end
		end
		if (instanceof(it, "Clothing") or U.isBackBag(it)) and not worn and count(list, "wear") < 8 then add(list, "wear", info, { it = it }) end
		if worn and count(list, "take_off") < 8 then add(list, "take_off", info, { it = it }) end
		if not worn and not shut and not try(function() return it:isFavorite() end) and count(list, "drop") < 8 then add(list, "drop", info, { it = it }) end
		if crafts < 8 then
			for _, r in ipairs(G.recipes(p, it)) do
				if crafts < 8 then
					crafts = crafts + 1
					info.recipe = r.name
					add(list, "craft", info, { it = it, recipe = r.recipe })
					info.recipe = nil
				end
			end
		end
	end)
	-- All water fixtures in the current perceivable-square scan (gym 0.4.71). No stale visibility cache
	-- or nearest-five/nearest-two cap. Ground fluid items remain a separate adapter.
	-- A source's menu (J:ISWorldObjectContextMenuLogic.doWashClothingOrYourselfMenu, 42.21) has Drink and Fill only
	-- for a source in the character's building, or both outdoors (doDrinkWaterMenu, doFillFluidMenu). Drink also
	-- needs a drink in it (its primary fluid in FluidCategory.Beverage) and no washer or dryer (gym 0.4.56; until
	-- then drink_tap was offered for the two nearest sources in sight, whichever building they were in).
	local sources = {}
	for _, s in ipairs(ar.water or {}) do
		local sq = s.src:getSquare()
		if sq and sq:getBuilding() == p:getBuilding() then sources[#sources + 1] = s end
	end
	for _, s in ipairs(sources) do
		local fluid, w = s.src:getPrimaryFluid(), s.w
		if fluid and fluid:isCategory(FluidCategory.Beverage)
			and not instanceof(s.src, "IsoClothingWasher") and not instanceof(s.src, "IsoClothingDryer") then
			add(list, "drink_tap", { d = w.d, tainted = w.tainted, name = w.name }, { src = s.src, x = w.x, y = w.y, z = w.z })
		end
	end
	-- Fill a carried container (gym 0.4.56), as doFillFluidMenu offers it: not with a full inventory (the entry is
	-- greyed out then); a container whose fluid container isn't full and takes water (canAddFluid(Fluid.Water)), and
	-- that the source can pour into (canTransferFluidTo). The menu has one entry per container name (Fill One fills
	-- the first) and Fill All for more than one: so has this, at the two nearest sources. The menu searches bags in
	-- bags (getAllRecurse); this, the inventory and the bags in it.
	if #sources > 0 and not p:hasFullInventory() then
		local cans = {}
		U.eachItem(p:getInventory(), function(it)
			local fc = it:getFluidContainer()
			if fc and not fc:isFull() and fc:canAddFluid(Fluid.Water) then cans[#cans + 1] = it end
		end)
		for i = 1, (#cans > 0 and #sources or 0) do
			local w, src = sources[i].w, sources[i].src
			local into, named = {}, {}
			for _, it in ipairs(cans) do
				if src:canTransferFluidTo(it:getFluidContainer()) then
					into[#into + 1] = it
					if not named[it:getName()] then
						named[it:getName()] = true
						add(list, "fill", { d = w.d, tainted = w.tainted, name = w.name, type = it:getFullType() },
							{ src = src, x = w.x, y = w.y, z = w.z, it = it })
					end
				end
			end
			if #into > 1 then
				add(list, "fill", { d = w.d, tainted = w.tainted, name = w.name, how = "all" }, { src = src, x = w.x, y = w.y, z = w.z, all = into })
			end
		end
	end
	washOptions(p, list, sources)
	-- Treatment for each body part, as the health panel's menu offers it (gym 0.4.57; the handlers above MED): one
	-- option per kind of supply, as its submenus list them. With an injury not under a bandage (injured): bandage,
	-- disinfect, a poultice (none on yet), stitch a deep wound with no glass in it, take out glass (with a tool or by
	-- hand) or a bullet, clean a burn that needs it. Splint a fracture, not on the head or torso, that isn't stitched
	-- or splinted. Until gym 0.4.56 only `bandage` was offered, with the first item named Bandage or RippedSheets from
	-- the bag, for at most 3 parts, and with its own idea of a wound.
	local supplies = medSupplies(p)
	local parts = p:getBodyDamage():getBodyParts()
	for i = 0, parts:size() - 1 do
		local bp = parts:get(i)
		local part = BodyPartType.ToString(bp:getType())
		if injured(bp) then
			for _, it in ipairs(eachKind(supplies, MED.bandage)) do
				add(list, "bandage", { part = part, bleeding = bp:bleeding(), item = it:getDisplayName(), type = it:getFullType() },
					{ part = bp, it = it })
			end
			for _, it in ipairs(eachKind(supplies, MED.disinfect)) do
				add(list, "disinfect", { part = part, type = it:getFullType() }, { part = bp, it = it })
			end
			if bp:getPlantainFactor() == 0 and bp:getComfreyFactor() == 0 and bp:getGarlicFactor() == 0 then
				for _, pl in ipairs(POULTICES) do
					local it = firstOf(supplies, function(x) return x:getType() == pl.type end)
					if it then add(list, "poultice", { part = part, type = it:getFullType() }, { part = bp, it = it, pl = pl }) end
				end
			end
			if bp:isDeepWounded() and not bp:haveGlass() then
				local suture = firstOf(supplies, MED.suture)
				local needle, thread = firstOf(supplies, MED.needle), firstOf(supplies, MED.thread)
				-- a suture needle is needle and thread in one; otherwise both, and the action takes the thread
				if suture then add(list, "stitch", { part = part, type = suture:getFullType() }, { part = bp, it = suture, move = { suture } }) end
				if needle and thread then
					add(list, "stitch", { part = part, type = needle:getFullType(), item = thread:getDisplayName() },
						{ part = bp, it = thread, move = { needle, thread } })
				end
			end
			if bp:haveGlass() then
				for _, it in ipairs(eachKind(supplies, MED.glass)) do
					add(list, "remove_glass", { part = part, type = it:getFullType() }, { part = bp, it = it })
				end
				add(list, "remove_glass", { part = part, type = "Hands" }, { part = bp })   -- the menu's "Hand" entry
			end
			if bp:haveBullet() then
				for _, it in ipairs(eachKind(supplies, MED.bullet)) do
					add(list, "remove_bullet", { part = part, type = it:getFullType() }, { part = bp, it = it })
				end
			end
			if bp:isNeedBurnWash() then
				for _, it in ipairs(eachKind(supplies, MED.burn)) do
					add(list, "clean_burn", { part = part, type = it:getFullType() }, { part = bp, it = it })
				end
			end
		end
		-- HSplint:addToMenu (:1554-1607): a made splint, or each kind of plank or stick with the first kind of sheet
		local bt = bp:getType()
		if bt ~= BodyPartType.Head and bt ~= BodyPartType.Torso_Upper and bt ~= BodyPartType.Torso_Lower and bp:HasInjury()
			and not bp:stitched() and bp:getSplintFactor() <= 0 and bp:getFractureTime() > 0 then
			for _, it in ipairs(eachKind(supplies, MED.splint)) do
				add(list, "splint", { part = part, type = it:getFullType() }, { part = bp, it = it })
			end
			local sheet = firstOf(supplies, MED.sheet)
			if sheet then
				for _, it in ipairs(eachKind(supplies, MED.plank)) do
					add(list, "splint", { part = part, type = it:getFullType(), item = sheet:getDisplayName() }, { part = bp, it = it, sheet = sheet })
				end
			end
		end
	end
	-- a bandage that can come off, as the health panel offers it (HRemoveBandage, ISHealthPanel.lua:1204-1220; GAP_LIST 11)
	do
		local parts = p:getBodyDamage():getBodyParts()
		for i = 0, parts:size() - 1 do
			local bp = parts:get(i)
			if count(list, "unbandage") < 8 and bp:bandaged() then
				add(list, "unbandage", { part = BodyPartType.ToString(bp:getType()) }, { part = bp })
			end
			-- stitches and a splint come off the same way (HRemoveStitch 1460-1472, HRemoveSplint 1646-1662)
			if count(list, "unstitch") < 8 and bp:stitched() then
				add(list, "unstitch", { part = BodyPartType.ToString(bp:getType()) }, { part = bp })
			end
			if count(list, "unsplint") < 8 and bp:getSplintFactor() > 0 then
				add(list, "unsplint", { part = BodyPartType.ToString(bp:getType()) }, { part = bp })
			end
		end
	end
	-- rest on the nearest bed here, as the bed menu offers it (gym 0.4.39)
	if b and not p:getVehicle() then
		local bed = A.beds(p, b, true)[1]
		if bed and bedRestable(p, bed.o) then add(list, "rest", { bed = true, d = bed.d }, { bed = bed.o }) end
	end
	-- sleep: in the nearest bed here, or on the floor; only when the game's Sleep menu entry would be enabled
	local noSleep = sleepBlock(p)
	if b and not noSleep then
		local bed = A.beds(p, b, true)[1]
		if bed then add(list, "sleep", { bed = true, d = bed.d }, { bed = bed.o }) end
	end
	-- the game's floor-sleep check reads the square (an error once, with none, mid-climb)
	if p:getSquare() and not noSleep then add(list, "sleep", { bed = false }, {}) end
	-- further families (AIvZGymActions.lua) register here; one failing must not take the others down
	local names = {}
	for name in pairs(G.hooks) do names[#names + 1] = name end
	table.sort(names)
	for _, name in ipairs(names) do
		local ok, e = pcall(G.hooks[name], p, list, add, count)
		if not ok then A.s.err = "option hook " .. name .. ": " .. tostring(e) end
	end
	return list
end

-- the right-click menu's Eat: food with a hunger value, or one it can open first ("Open and Eat", a sealed
-- can with an opener or a knife). Returns ok and, for the latter, the opening recipe.
function G.eatable(p, it)
	if not instanceof(it, "Food") then return false end
	local script = it:getScriptItem()
	local name = try(function() return it:getOpeningRecipe() end)
	local opening = name and try(function() return getScriptManager():getCraftRecipe(name) end) or nil
	if opening and not try(function()
		local logic = HandcraftLogic.new(p, nil, nil)
		logic:setContainers(ISInventoryPaneContextMenu.getContainers(p))
		logic:setRecipeFromContextClick(opening, it)
		return logic:canPerformCurrentRecipe()
	end) then opening = nil end
	if opening then return true, opening end
	if try(function() return script:isCantEat() end) then return false end
	if (try(function() return it:getHungChange() end) or 0) < 0 then return true, nil end
	-- a drink or the like ("Drink" in the menu), unless it needs something else to hand (a lighter)
	return it:getCustomMenuOption() ~= nil and not it:getRequireInHandOrInventory(), nil
end

-- Match the game's Drink fluid menu (ISInventoryPaneContextMenu.createMenu :437-444, GAP_LIST item 4): a water
-- source only while thirst > 0.1, any other fluid only if its primary fluid is a beverage or bleach; containers
-- up to three litres, with an opening recipe when a sealed container needs one. Returns the amount, the opening
-- recipe and the portions offered (1 = all; 0.5 and 0.25 when the container is at least that full).
function G.drinkable(p, it)
	local fc = try(function() return it:getFluidContainer() end)
	if not fc then return nil end
	local amount = try(function() return fc:getAmount() end) or 0
	local capacity = try(function() return fc:getCapacity() end) or 99
	if amount < 0.05 or capacity > 3 then return nil end
	if try(function() return it:isWaterSource() end) then
		if (U.stat(p, "THIRST") or 0) <= 0.1 then return nil end
	else
		local pf = try(function() return fc:getPrimaryFluid() end)
		if not pf then return nil end
		local beverage = try(function() return pf:isCategory(FluidCategory.Beverage) end)
		-- the menu's own test, getFluidType() == FluidType.Bleach (gym 0.4.37; until then the name from getFluidTypeString)
		local bleach = pf:getFluidType() == FluidType.Bleach
		if not (beverage or bleach) then return nil end
	end
	local opening = nil
	if try(function() return it:isSealed() end) then
		local name = try(function() return it:getOpeningRecipe() end)
		opening = name and try(function() return getScriptManager():getCraftRecipe(name) end) or nil
		if opening and not try(function()
			local logic = HandcraftLogic.new(p, nil, nil)
			logic:setContainers(ISInventoryPaneContextMenu.getContainers(p))
			logic:setRecipeFromContextClick(opening, it)
			return logic:canPerformCurrentRecipe()
		end) then opening = nil end
	end
	if not opening and not try(function() return fc:canPlayerEmpty() end) then return nil end
	if U.moodle(p, "FOOD_EATEN") >= 3 and (try(function() return fc:getProperties():getHungerChange() end) or 0) ~= 0 then return nil end
	local portions = { 1 }
	if capacity > 0 and amount / capacity >= 0.5 then portions[#portions + 1] = 0.5 end
	if capacity > 0 and amount / capacity >= 0.25 then portions[#portions + 1] = 0.25 end
	return amount, opening, portions
end

-- an item's own recipes, the ones the game lets it do right now (the right-click menu's craft options)
function G.recipes(p, it)
	GS.rcache = GS.rcache or {}
	local c = GS.rcache[it]
	if c and tick() - c.at < 600 then return c.list end
	local out = {}
	local containers = ISInventoryPaneContextMenu.getContainers(p)
	local rl = try(function() return CraftRecipeManager.getUniqueRecipeItems(it, p, containers) end)
	if rl then
		for i = 0, rl:size() - 1 do
			local r = rl:get(i)
			local ok = try(function()
				local logic = HandcraftLogic.new(p, nil, nil)
				logic:setContainers(containers)
				logic:setRecipeFromContextClick(r, it)
				return logic:canPerformCurrentRecipe() and logic:getRecipeData():getAllInputItems():contains(it)
			end)
			if ok then out[#out + 1] = { recipe = r, name = r:getName() } end
		end
	end
	-- the game's list came back empty for every item when tested (42.21, worn clothes, food, a bread knife);
	-- these three are known to work through the same crafting call, so they're checked directly too
	for _, name in ipairs(DIRECT_RECIPES) do
		local seenIt = false
		for _, e in ipairs(out) do if e.name == name then seenIt = true end end
		if not seenIt then
			local r = U.craftable(p, name, it)
			if r then out[#out + 1] = { recipe = r, name = name } end
		end
	end
	GS.rcache[it] = { at = tick(), list = out }
	return out
end

---------------------------------------------------------------- doing the chosen option
local function stopMoving(p)
	ISTimedActionQueue.clear(p)
	pcall(function() p:setRunning(false) end)
	pcall(function() p:setIsAiming(false) end)
end

-- generic end: the queued actions finished (or it has been too long). `check` looks at what happened and
-- returns why the option didn't do what it says, or nil. Without it, an action the game dropped at once (a
-- locked door, a window out of reach) came back "done" after 20 ticks with nothing changed.
local function queueStep(maxTicks, check)
	return function(p, t, o)
		local age = tick() - t.t0
		if t.pathFailed then return U.fail(t, "no way there") end
		local over = age > (maxTicks or 900)
		if (qlen(p) == 0 and age > 20) or over then
			local why = check and check(p, t, o)
			-- some effects land after the action leaves the queue (a smash breaks the glass partway through
			-- its animation): give it a second and a half before calling it a failure
			if why and not over then
				t.emptyAt = t.emptyAt or tick()
				if tick() - t.emptyAt < 90 then return end
			end
			if why then return U.fail(t, over and "took too long" or why) end
			U.done(t, over and "took too long" or nil)
		end
	end
end

local function isOpen(o) return try(function() return o:IsOpen() end) == true end
local function has(p, it) return try(function() return p:getInventory():containsRecursive(it) end) == true end
local function worn(p, it) return try(function() return p:isEquipped(it) end) == true end

G.X = {}
G.hooks = G.hooks or {}   -- name -> function(p, list, add, count) adding options
G.queueStep, G.has, G.worn = queueStep, has, worn
G.X.wait = { start = function() end, step = function(p, t) if tick() - t.t0 > 120 then U.done(t) end end }
G.X.get_up = {
	start = function(p) Q(ISWaitWhileGettingUp:new(p)) end,
	step = queueStep(600, function(p) if p:isSitting() then return "still sitting" end end),
}
-- On a bed: ISWorldObjectContextMenu.onRest, the game's path to a place on it (ISPathFindAction:pathToSitOnFurniture)
-- and then ISRestAction; when no place is free it goes next to it and sits on the ground (onRestPathFailed)
-- 42.21 doBedMenu uses addGetUpOption: get up from another seat first. ISRestAction:update completes once
-- SitOnFurnitureStarted is set; sitting then recovers endurance passively. Don't keep a finished sit running
-- for another 600 ticks: subsequent choices can wait, read or get up while the character is still seated.
G.X.rest = {
	start = function(p, t, o)
		if o.data.bed then
			local function onUp()
				local bed = o.data.bed
				if not bed:getSquare() or bed:getObjectIndex() == -1 then return U.fail(t, "seat gone") end
				ISWorldObjectContextMenu.onRest(bed, p:getPlayerNum())
			end
			if p:isSitting() then
				local action = ISWaitWhileGettingUp:new(p)
				action:setOnComplete(onUp)
				Q(action)
			else onUp() end
			return
		end
		p:reportEvent("EventSitOnGround")   -- ISWorldObjectContextMenu.onSitOnGround (42.21)
	end,
	step = function(p, t, o)
		local age = tick() - t.t0
		if age > 20 and qlen(p) == 0 and p:isSitting() then
			local fallback = o.data.bed and not p:isSittingOnFurniture()
			return U.done(t, fallback and "sat on the ground" or nil)
		end
		if age > 1200 then U.fail(t, "didn't sit down") end
	end,
}
local function stance(on)
	return {
		start = function(p) p:setSneaking(on) end,
		step = function(p, t)
			if tick() - t.t0 < 10 then return end
			if p:isSneaking() == on then U.done(t) else U.fail(t, "didn't change") end
		end,
	}
end
G.X.sneak, G.X.stand = stance(true), stance(false)
local function arrived(p, t) if t.to and dist(p, t.to[1] + 0.5, t.to[2] + 0.5) > 1.5 then return "stopped short" end end
local function walkStart(n, running)
	return function(p, t, o)
		local sq = U.farthestFree(p, o.data.dx * n, o.data.dy * n)
		if not sq then return U.fail(t, "blocked") end
		pcall(function() p:setRunning(running) end)
		t.to = { sq:getX(), sq:getY() }
		U.pathTo(p, t, sq:getX(), sq:getY(), sq:getZ())
	end
end
G.X.walk = { start = walkStart(12, false), step = queueStep(600, arrived) }
G.X.run = { start = walkStart(15, true), step = queueStep(600, arrived) }
G.X.enter = {
	start = function(p, t, o) t.args = { o.data.tx, o.data.ty, o.data.tz } end,
	step = function(p, t, o)
		if A.travelStep(p, t, o.data.tx, o.data.ty, o.data.tz) and qlen(p) == 0 then
			U.mem(p).visited = U.mem(p).visited or {}
			U.mem(p).visited[o.data.id] = true
			U.done(t)
		end
		if tick() - t.t0 > 3600 and t.status == "running" then U.fail(t, "took too long") end
	end,
}
G.X.go_room = {
	start = function(p, t, o)
		local sq = try(function() return o.data.r:getFreeSquare() end)
		if not sq then return U.fail(t, "no free square") end
		t.to = { sq:getX(), sq:getY() }
		U.pathTo(p, t, sq:getX(), sq:getY(), sq:getZ())
	end,
	step = queueStep(600, arrived),
}
local AIM_TICKS = 15   -- how long a gun is aimed before the first shot (gym 0.4.66)
G.X.attack = {
	start = function() end,
	step = function(p, t, o)
		local z = o.data.z
		if not z or z:isDead() then return U.done(t, z and "it's down for good" or "gone") end
		local d = dist(p, z:getX(), z:getY())
		local w = p:getPrimaryHandItem()
		-- A gun is fired from its range, as a click fires it: through the game's own attack hook
		-- (ISReloadWeaponAction.attackHook, Hook.Attack, 42.21), which checks a round is ready (canShoot), makes the
		-- shot's noise for the zombies to hear, and attacks. Aimed for AIM_TICKS first (a guess, not measured). With
		-- nothing to shoot it stops, so a reload can come next. Until gym 0.4.66 a gun counted as no weapon: the
		-- character walked up to the zombie and shoved it.
		local ranged = w ~= nil and instanceof(w, "HandWeapon") and w:isRanged()
		local reach = ranged and w:getMaxRange() or ((U.isMelee(w) and w:getMaxRange() or 0.9) + 0.3)
		if ranged and not ISReloadWeaponAction.canShoot(p, w) then
			p:setIsAiming(false)
			return U.fail(t, "can't shoot: empty, jammed, safe or no round chambered")
		end
		if d <= reach then
			if t.pathing then ISTimedActionQueue.clear(p); t.pathing = false end
			if ranged then
				p:faceThisObject(z)
				p:setIsAiming(true)
				t.aimFrom = t.aimFrom or tick()
				if tick() - t.aimFrom >= AIM_TICKS and not p:isAttackStarted() then ISReloadWeaponAction.attackHook(p, 0, w) end
			else
				A.swing(p, { z = z, d = d }, w)
			end
		elseif not t.pathing or tick() - (t.lastPath or 0) > 90 then
			ISTimedActionQueue.clear(p)
			Q(ISPathFindAction:pathToLocationF(p, z:getX(), z:getY(), z:getZ()))
			t.pathing, t.lastPath = true, tick()
		end
		if tick() - t.t0 > 480 then U.done(t, "gave up") end
	end,
}
G.X.shove = {
	start = function(p, t, o)
		local z = o.data.z
		if not z or z:isDead() then return U.done(t) end
		p:faceThisObject(z)
		pcall(function() p:setDoShove(true) end)
		p:setIsAiming(true)
		p:DoAttack(0)
	end,
	step = function(p, t) if tick() - t.t0 > 30 then pcall(function() p:setIsAiming(false) end); U.done(t) end end,
}
-- doors, windows and curtains toggle: the check is that it moved
local function toggled(p, t, o)
	if isOpen(o.data.o) == t.wasOpen then return o.data.locked and "it's locked" or "it didn't move" end
end
G.X.door = {
	start = function(p, t, o)
		t.wasOpen = isOpen(o.data.o)
		if not U.closeOpening(p, o.data, t) then U.fail(t, "can't reach it") end
	end,
	step = queueStep(600, toggled),
}
G.X.window = G.X.door
-- a curtain's state: an IsoCurtain on a window, or a door with a sheet (both ICurtain.isCurtainOpen)
local function curtainOpen(c) return try(function() return c:isCurtainOpen() end) == true end
-- A door's sheet is reached from one side of the doorway (getAddSheetSquare to hang it, getSheetSquare once up), which
-- must be free; the menu gives up otherwise. The walk through the doorway leaves the door as it was
-- (ISWorldObjectContextMenu.restoreDoor, as the menu's walk does). The mod's walk, not ISWalkToTimedAction.
local function walkToDoorSheet(p, door, sq, t)
	if not (sq and sq:isFree(false)) then return false end
	if sq ~= p:getCurrentSquare() then
		t.pathFailed = false
		local act = ISPathFindAction:pathToLocationF(p, sq:getX() + 0.5, sq:getY() + 0.5, sq:getZ())
		act:setOnFail(function() t.pathFailed = true end)
		act:setOnComplete(ISWorldObjectContextMenu.restoreDoor, p, door, door:IsOpen())
		Q(act)
	end
	return true
end
-- ISWorldObjectContextMenu.onOpenCloseCurtain: a window's curtain from its square (or next to the window), a door's
-- from the sheet's side of the doorway
G.X.curtain = {
	start = function(p, t, o)
		t.wasOpen = curtainOpen(o.data.o)
		local ok
		if o.data.door then
			ok = walkToDoorSheet(p, o.data.o, o.data.sq, t)
			if ok then Q(ISOpenCloseCurtain:new(p, o.data.o)) end
		else
			ok = U.closeCurtain(p, o.data, t)
		end
		if not ok then U.fail(t, "can't reach it") end
	end,
	step = queueStep(600, function(p, t, o) if curtainOpen(o.data.o) == t.wasOpen then return "it didn't move" end end),
}
-- ISWorldObjectContextMenu.onAddSheet, with the mod's walk (the game's ISWalkToTimedAction fails at 20x and 40x):
-- stand on the square the sheet goes up from if it is free, else next to the window (a door: only from that square);
-- the sheet into the main inventory if it is in a bag (ISAddSheetAction:isValid looks there); then the timed action
G.X.hang_sheet = {
	start = function(p, t, o)
		local w = o.data.o
		local sheet = p:getInventory():getFirstTypeRecurse("Sheet")
		if not sheet then return U.fail(t, "no sheet") end
		local sq = w:getAddSheetSquare(p)
		if instanceof(w, "IsoDoor") then
			if not walkToDoorSheet(p, w, sq, t) then return U.fail(t, "can't reach it") end
		elseif sq and sq:isFree(false) then U.walkTo(p, sq, t)
		elseif not U.walkAdjOpening(p, o.data.sq, w, t) then return U.fail(t, "can't reach it") end
		ISWorldObjectContextMenu.transferIfNeeded(p, sheet)
		Q(ISAddSheetAction:new(p, w))
	end,
	step = queueStep(900, function(p, t, o) if o.data.o:HasCurtains() == nil then return "no curtain went up" end end),
}
-- ISWorldObjectContextMenu.onRemoveCurtain: the sheet comes down into the inventory. A window's curtain from its own
-- square if free, else next to the window; a door's from the sheet's side of the doorway.
G.X.remove_sheet = {
	start = function(p, t, o)
		local c, ok = o.data.o, nil
		if o.data.door then ok = walkToDoorSheet(p, c, c:getSheetSquare(), t)
		elseif o.data.sq and o.data.sq:isFree(false) then ok = U.walkTo(p, o.data.sq, t)
		else ok = U.walkAdjOpening(p, o.data.sq, c, t) end
		if not ok then return U.fail(t, "can't reach it") end
		Q(ISRemoveSheetAction:new(p, c))
	end,
	step = queueStep(900, function(p, t, o)
		local up = o.data.door and o.data.o:HasCurtains() ~= nil or (not o.data.door and o.data.o:getObjectIndex() ~= -1)
		if up then return "the sheet is still up" end
	end),
}
-- Over a fence, as the Interact key does it: IsoPlayer.doContextHopOverFence → ContextualActionHandlers.ClimbOverFence
-- → ISWorldObjectContextMenu.onClimbOverFence, ISClimbOverFence with the fence (the flagged square's getHoppable) and the
-- direction; a tall one doContextClimbOverWall → climbOverWall(dir), which checks canClimbOverWall itself. From the
-- square next to it on the character's side, walked to with the mod's walk (luautils.walkAdjFence uses
-- ISWalkToTimedAction, which fails at 20x and 40x). Done once the character stands on the far side.
G.X.climb_fence = {
	start = function(p, t, o) U.walkTo(p, o.data.stand, t) end,
	step = function(p, t, o)
		local f = o.data
		if t.pathFailed then return U.fail(t, "no way there") end
		local sq = p:getCurrentSquare()
		if t.climbing then
			if sq == f.far then return U.done(t) end
			if qlen(p) == 0 and not p:isClimbing() and tick() - t.climbing > 120 then return U.fail(t, "didn't get over") end
			if tick() - t.t0 > 1800 then U.fail(t, "took too long") end
			return
		end
		if qlen(p) > 0 then
			if tick() - t.t0 > 1200 then U.fail(t, "took too long") end
			return
		end
		if sq ~= f.stand then return U.fail(t, "couldn't get to it") end
		local dir = IsoDirections[f.dir]
		if f.tall then
			if not p:canClimbOverWall(dir) then return U.fail(t, "can't climb it") end
			p:faceDirection(dir)
			p:climbOverWall(dir)
		else
			local fence = f.sq:getHoppable(f.north)
			if not fence then return U.fail(t, "the fence is gone") end
			Q(ISClimbOverFence:new(p, fence, dir))
		end
		t.climbing = tick()
	end,
}
-- ISWorldObjectContextMenu.onLockDoor / onUnLockDoor, with the mod's walk
local function lockDoor(lock)
	return {
		start = function(p, t, o)
			if not U.walkAdjOpening(p, o.data.sq, o.data.o, t) then return U.fail(t, "can't reach it") end
			Q(ISLockDoor:new(p, o.data.o, lock))
		end,
		step = queueStep(600, function(p, t, o) if o.data.o:isLockedByKey() ~= lock then return "the lock didn't turn" end end),
	}
end
G.X.lock_door, G.X.unlock_door = lockDoor(true), lockDoor(false)
-- The side of an opening the character will stand on after walking to `adj`: true for the opening's own square (the
-- square south of a north edge, east of a west edge)
local function ownSide(e, adj)
	if e.o:getNorth() then return adj:getY() >= e.sq:getY() end
	return adj:getX() >= e.sq:getX()
end
-- Barricade: the menu entry hands the build cursor an ISBuildIsoEntity for the BarricadePlanks entity
-- (ISWorldObjectContextMenu.onBarricade("carpentry_01_8")); a click on an opening's edge then runs
-- ISBuildingObject.tryBuild, which equips the hammer and queues ISBuildAction for the entity's recipe (a plank and a
-- nail, BuildWallHammer). The gym does that click on the edge from the side it walks to: the entity faces N or W on
-- the opening's own square, S or E on the square beyond (nSprite 2, 1, 4, 3: ISBuildIsoEntity:getFace). The walk is
-- the mod's (the cursor's luautils.walkAdjWall uses ISWalkToTimedAction, which fails at 20x and 40x).
G.X.barricade = {
	start = function(p, t, o)
		local e = o.data
		local ok, adj = U.walkAdjOpening(p, e.sq, e.o, t)
		if not ok then return U.fail(t, "can't reach it") end
		local north, mine = e.o:getNorth(), ownSide(e, adj)
		local x, y, z = e.sq:getX(), e.sq:getY(), e.sq:getZ()
		local bsq = mine and e.sq or (north and sqAt(x, y - 1, z) or sqAt(x - 1, y, z))
		local info = SpriteConfigManager.getObjectInfoFromSprite("carpentry_01_8")
		if not (bsq and info) then return U.fail(t, "can't barricade it") end
		local be = ISBuildIsoEntity:new(p, info, 1, ISInventoryPaneContextMenu.getContainers(p))
		be.player, be.dragNilAfterPlace = p:getPlayerNum(), false   -- as IsoCell.setDrag and onBarricade set them
		be.nSprite = mine and (north and 2 or 1) or (north and 4 or 3)
		be.walkTo = function() return true end   -- the mod's walk is queued already
		be:getSprite()
		if not be:isValid(bsq) then return U.fail(t, "can't barricade it") end
		t.same, t.planks = mine, planksOn(e.o, mine)
		be:tryBuild(bsq:getX(), bsq:getY(), bsq:getZ())
	end,
	step = queueStep(3600, function(p, t, o)
		if planksOn(o.data.o, t.same) <= t.planks then return "no plank went up" end
	end),
}
-- ISWorldObjectContextMenu.onUnbarricade, with the mod's walk: a RemoveBarricade tool into the hands
-- (ISWorldObjectContextMenu.equip), then ISUnbarricadeAction, which takes one plank off the character's side
G.X.unbarricade = {
	start = function(p, t, o)
		local e = o.data
		local ok, adj = U.walkAdjOpening(p, e.sq, e.o, t)
		if not ok then return U.fail(t, "can't reach it") end
		t.same = ownSide(e, adj)
		t.planks = planksOn(e.o, t.same)
		if t.planks == 0 then return U.fail(t, "no planks on this side") end
		if not ISWorldObjectContextMenu.equip(p, p:getPrimaryHandItem(), removesBarricade, true) then
			return U.fail(t, "nothing to pry it with")
		end
		Q(ISUnbarricadeAction:new(p, e.o))
	end,
	step = queueStep(3600, function(p, t, o)
		if planksOn(o.data.o, t.same) >= t.planks then return "the planks are still up" end
	end),
}
local function atWindow(make, check)
	return {
		start = function(p, t, o)
			local ok, adj = U.walkAdjOpening(p, o.data.sq, o.data.o, t)
			if not ok then return U.fail(t, "can't reach it") end
			t.from = adj
			Q(make(p, o.data.o))
		end,
		step = queueStep(600, check),
	}
end
-- through a window: it ends up on the other side of the wall from the square it climbed from
G.X.climb = atWindow(function(p, w) return ISClimbThroughWindow:new(p, w, 0) end, function(p, t, o)
	local sq, from = p:getCurrentSquare(), t.from
	if not sq or sq == from then return "didn't get through" end
	if o.data.exterior and (sq:getBuilding() ~= nil) == (from:getBuilding() ~= nil) then return "didn't get through" end
end)
G.X.smash = atWindow(function(p, w) return ISSmashWindow:new(p, w) end, function(p, t, o)
	if not U.winIs(o.data.o, "isSmashed") then return "it didn't break" end
end)
G.X.clear_glass = atWindow(function(p, w) return ISRemoveBrokenGlass:new(p, w) end, function(p, t, o)
	if not U.winIs(o.data.o, "isGlassRemoved") then return "the glass is still there" end
end)
G.X.search = {
	start = function(p, t, o)
		if not U.walkToContainer(p, o.data.c, t) then U.fail(t, "can't reach it") end
	end,
	step = function(p, t, o)
		if t.pathFailed then return U.fail(t, "no way there") end
		if qlen(p) > 0 and tick() - t.t0 < 900 then return end
		if dist(p, o.data.sq:getX() + 0.5, o.data.sq:getY() + 0.5) > 2.5 then return U.fail(t, "couldn't reach it") end
		-- looking in fills a container the first time, as the loot window does (ISInventoryPage:checkExplored,
		-- singleplayer): a corpse's pockets, or a cupboard the loot window hasn't listed yet. Not a bag on the
		-- ground: the loot window lists those without checkExplored
		if not o.data.bag and not o.data.c:isExplored() then
			ItemPicker.fillContainer(o.data.c, p)
			o.data.c:setExplored(true)
		end
		seen(p)[o.data.key] = true
		local n = 0
		U.eachItem(o.data.c, function() n = n + 1 end, 1)
		U.done(t, n .. " items inside")
	end,
}
G.X.take = {
	start = function(p, t, o)
		if not U.walkToContainer(p, o.data.c, t) then return U.fail(t, "can't reach it") end
		-- the loot window's own constructor (ISInventoryTransferUtil, gym 0.4.38): ISInventoryTransferAction, or
		-- ISGrabCorpseItem for a corpse item
		Q(ISInventoryTransferUtil.newInventoryTransferAction(p, o.data.it, o.data.c, U.carryInv(p, o.data.it)))
	end,
	step = function(p, t, o)
		if t.pathFailed then return U.fail(t, "no way there") end
		if qlen(p) > 0 and tick() - t.t0 < 900 then return end
		if has(p, o.data.it) then
			A.event("took " .. o.data.it:getDisplayName())
			U.done(t)
		else
			U.fail(t, "didn't get it")
		end
	end,
}
-- ISDisassembleMenu.disassemble, after the mod's walk next to the object: its own walk (luautils.walkAdj) then
-- finds the character within reach and queues nothing, and it equips the tools and queues ISMoveablesAction "scrap"
G.X.disassemble = {
	start = function(p, t, o)
		local sq, here = o.data.sq, p:getCurrentSquare()
		local near = here and math.abs(sq:getX() + 0.5 - p:getX()) <= 1.6 and math.abs(sq:getY() + 0.5 - p:getY()) <= 1.6
			and here:canReachTo(sq)
		if not near then
			local adj = AdjacentFreeTileFinder.Find(sq, p)
			if not adj then return U.fail(t, "can't reach it") end
			U.walkTo(p, adj, t)
		end
	end,
	step = function(p, t, o)
		if t.pathFailed then return U.fail(t, "no way there") end
		if qlen(p) > 0 and tick() - t.t0 < 3600 then return end
		local gone = not o.data.sq:getObjects():contains(o.data.o)
		if t.queued then
			if gone then return U.done(t) end
			return U.fail(t, tick() - t.t0 >= 3600 and "took too long" or "it's still there")
		end
		if gone then return U.fail(t, "it's gone") end
		t.queued = true
		ISDisassembleMenu.disassemble(p, { object = o.data.o, moveProps = o.data.mp, square = o.data.sq })
		if qlen(p) == 0 then return U.fail(t, "couldn't start") end
	end,
}
-- ISWorldObjectContextMenu.onGrabWItem, with the mod's walk (luautils.walkAdj uses ISWalkToTimedAction, which
-- fails at 20x and 40x): onto the item's square or next to it, then ISGrabItemAction with the game's grab time
-- Half or all of a pile (gym 0.4.35): an ISGrabItemAction for each item, as onGrabHalfWItems and onGrabAllWItems do.
G.X.pick_up = {
	start = function(p, t, o)
		local w, sq = o.data.w, o.data.sq
		if not w:getSquare() then return U.fail(t, "it's gone") end
		local here = p:getCurrentSquare()
		if sq ~= here and (not here or sq:DistToProper(here) >= 1.5) then
			local to = sq:isFree(false) and sq or AdjacentFreeTileFinder.Find(sq, p)
			if not to then return U.fail(t, "can't reach it") end
			U.walkTo(p, to, t)
		end
		for _, f in ipairs(o.data.items or { o.data }) do
			if f.w:getSquare() then Q(ISGrabItemAction:new(p, f.w, ISWorldObjectContextMenu.grabItemTime(p, f.w))) end
		end
	end,
	step = function(p, t, o)
		if t.pathFailed then return U.fail(t, "no way there") end
		local items = o.data.items or { o.data }
		if qlen(p) > 0 and tick() - t.t0 < 900 + 300 * (#items - 1) then return end
		local got = 0
		for _, f in ipairs(items) do if has(p, f.it) then got = got + 1 end end
		if got == 0 then return U.fail(t, "didn't get it") end
		A.event("picked up " .. (got > 1 and got .. " x " or "") .. o.data.it:getDisplayName())
		U.done(t, got < #items and ("got " .. got .. " of " .. #items) or nil)
	end,
}
-- Grab > Corpse, as ISWorldObjectContextMenu.onGrabCorpseItem queues it: the game's walk to the corpse
-- (ISPathFindAction:pathToGrabCorpse), the hands emptied, then ISGrabCorpseAction; done once dragging it
G.X.drag_corpse = {
	start = function(p, t, o)
		local b = o.data.b
		if b:getStaticMovingObjectIndex() < 0 then return U.fail(t, "it's gone") end
		Q(ISPathFindAction:pathToGrabCorpse(p, b))
		local h1, h2 = p:getPrimaryHandItem(), p:getSecondaryHandItem()
		if h1 then Q(ISUnequipAction:new(p, h1, 50)) end
		if h2 and h2 ~= h1 then Q(ISUnequipAction:new(p, h2, 50)) end
		Q(ISGrabCorpseAction:new(p, b))
	end,
	step = function(p, t, o)
		if p:isDraggingCorpse() then return U.done(t) end
		if qlen(p) > 0 and tick() - t.t0 < 1800 then return end
		U.fail(t, qlen(p) > 0 and "took too long" or "didn't get hold of it")
	end,
}
-- Drop Corpse: what the menu entry does (handleGrabWorldItem_onDropCorpse, setDoContinueGrapple(false))
G.X.drop_corpse = {
	start = function(p, t, o) p:setDoContinueGrapple(false) end,
	step = function(p, t, o)
		if not p:isDraggingCorpse() then return U.done(t) end
		if tick() - t.t0 > 300 then U.fail(t, "still dragging it") end
	end,
}
G.X.drop = {
	start = function(p, t, o) ISInventoryPaneContextMenu.dropItem(o.data.it, p:getPlayerNum()) end,
	step = queueStep(300, function(p, t, o) if has(p, o.data.it) then return "still has it" end end),
}
local function hungerLeft(it) return try(function() return it:getHungChange() end) end
G.X.eat = {
	start = function(p, t, o)
		t.left = hungerLeft(o.data.it)
		if o.data.opening then ISInventoryPaneContextMenu.eatItem(o.data.it, 1, p:getPlayerNum(), o.data.opening, 100)
		else ISInventoryPaneContextMenu.eatItem(o.data.it, 1, p:getPlayerNum()) end
	end,
	step = queueStep(1200, function(p, t, o)
		-- eaten: gone, or less of it left (an opened can becomes a new item, so the sealed one is gone too)
		if has(p, o.data.it) and hungerLeft(o.data.it) == t.left then return "didn't eat it" end
	end),
}
-- light_switch: the menu's ISWorldObjectContextMenu.onToggleLight (:1328-1351), which walks to the side of the wall the
-- switch is on and queues ISToggleLightAction; switch_item: ISInventoryPaneContextMenu.onActivateItem (:2880-2885),
-- at once (gym 0.4.60)
G.X.light_switch = {
	start = function(p, t, o)
		t.was = o.data.o:isActivated()
		ISWorldObjectContextMenu.onToggleLight(nil, o.data.o, p:getPlayerNum())
	end,
	step = queueStep(900, function(p, t, o) if o.data.o:isActivated() == t.was then return "didn't switch" end end),
}
G.X.switch_item = {
	start = function(p, t, o)
		t.was = o.data.it:isActivated()
		ISInventoryPaneContextMenu.onActivateItem(o.data.it, p:getPlayerNum())
	end,
	step = queueStep(60, function(p, t, o) if o.data.it:isActivated() == t.was then return "didn't switch" end end),
}
-- stove: the menu's ISWorldObjectContextMenu.onToggleStove (:1189-1194): next to it, ISToggleStoveAction (gym 0.4.62)
-- firearms (gym 0.4.65): each runs the menu's own handler, which equips the gun first where the menu does
local function rounds(it) return it:getCurrentAmmoCount() end
G.X.eject_mag = {
	start = function(p, t, o) ISInventoryPaneContextMenu.onEjectMagazine(p, o.data.it) end,
	step = queueStep(900, function(p, t, o) if o.data.it:isContainsClip() then return "magazine still in" end end),
}
G.X.insert_mag = {
	start = function(p, t, o) ISInventoryPaneContextMenu.onInsertMagazine(p, o.data.it, o.data.mag) end,
	step = queueStep(900, function(p, t, o) if not o.data.it:isContainsClip() then return "no magazine in" end end),
}
G.X.load_rounds = {
	start = function(p, t, o) t.n = rounds(o.data.it); ISInventoryPaneContextMenu.onLoadBulletsIntoFirearm(p, o.data.it) end,
	step = queueStep(1800, function(p, t, o) if rounds(o.data.it) <= t.n then return "loaded nothing" end end),
}
G.X.unload_rounds = {
	start = function(p, t, o) t.n = rounds(o.data.it); ISInventoryPaneContextMenu.onUnloadBulletsFromFirearm(p, o.data.it) end,
	step = queueStep(1800, function(p, t, o) if rounds(o.data.it) >= t.n then return "unloaded nothing" end end),
}
G.X.rack = {   -- done when it's no longer jammed, or anything about its rounds changed
	start = function(p, t, o)
		local g = o.data.it
		t.state = tostring(g:isJammed()) .. tostring(g:isRoundChambered()) .. tostring(g:isSpentRoundChambered()) .. rounds(g)
		ISInventoryPaneContextMenu.onRackGun(p, g)
	end,
	step = queueStep(900, function(p, t, o)
		local g = o.data.it
		if tostring(g:isJammed()) .. tostring(g:isRoundChambered()) .. tostring(g:isSpentRoundChambered()) .. rounds(g) == t.state then
			return "nothing changed"
		end
	end),
}
G.X.fire_mode = {   -- onChangefiremode (:1805-1811): at once
	start = function(p, t, o) ISInventoryPaneContextMenu.onChangefiremode(p, o.data.it, o.data.mode) end,
	step = queueStep(60, function(p, t, o) if o.data.it:getFireMode() ~= o.data.mode then return "mode unchanged" end end),
}
G.X.load_mag = {
	start = function(p, t, o) t.n = rounds(o.data.it); ISInventoryPaneContextMenu.onLoadBulletsInMagazine(p, o.data.it, o.data.n) end,
	step = queueStep(1800, function(p, t, o) if rounds(o.data.it) <= t.n then return "loaded nothing" end end),
}
G.X.unload_mag = {
	start = function(p, t, o) t.n = rounds(o.data.it); ISInventoryPaneContextMenu.onUnloadBulletsFromMagazine(p, o.data.it) end,
	step = queueStep(1800, function(p, t, o) if rounds(o.data.it) >= t.n then return "unloaded nothing" end end),
}
G.X.stove = {
	start = function(p, t, o)
		t.was = o.data.o:Activated()
		ISWorldObjectContextMenu.onToggleStove(nil, o.data.o, p:getPlayerNum())
	end,
	step = queueStep(900, function(p, t, o) if o.data.o:Activated() == t.was then return "didn't switch" end end),
}
-- read (gym 0.4.61): the menu's onLiteratureItems -> readItem (:2804-2832): into the main inventory, ISReadABook, back
-- where it was. Done when the pages read moved (a book) or the title is now read (a magazine); a book read to the
-- end starts again from page 0 when the action is made (ISReadABook:new), so its pages are taken after that.
G.X.read = {
	start = function(p, t, o)
		local it = o.data.it
		t.title = it:getModData().literatureTitle
		ISInventoryPaneContextMenu.readItem(it, p:getPlayerNum())
		t.pages = it:getAlreadyReadPages()
	end,
	step = queueStep(20000, function(p, t, o)
		local it = o.data.it
		if it:getNumberOfPages() > 0 then
			if it:getAlreadyReadPages() == t.pages then return "read nothing" end
		elseif t.title and not p:isLiteratureRead(t.title) then
			return "read nothing"
		end
	end),
}
-- the menu's own handler (onPillsItems -> takePill, :3667-3686): into the main inventory, the mask off, the pill,
-- the mask back on, the box back where it was. Done when the box has less in it, or is gone.
G.X.take_pill = {
	start = function(p, t, o)
		t.left = o.data.it:getCurrentUsesFloat()
		ISInventoryPaneContextMenu.takePill(o.data.it, p:getPlayerNum())
	end,
	step = queueStep(900, function(p, t, o) if o.data.it:getCurrentUsesFloat() >= t.left then return "didn't take it" end end),
}
G.X.drink = {
	start = function(p, t, o)
		t.fluid = try(function() return o.data.it:getFluidContainer():getAmount() end) or 0
		ISInventoryPaneContextMenu.onDrinkFluid(o.data.it, o.data.portion or 1, p, o.data.opening, o.data.it)
	end,
	step = queueStep(1200, function(p, t, o)
		if has(p, o.data.it) and (try(function() return o.data.it:getFluidContainer():getAmount() end) or 0) > t.fluid - 0.01 then return "didn't drink" end
	end),
}
local function beginWaterUse(p, t, o)
	local src = o.data.src or waterObjectAt(o.data.x, o.data.y, o.data.z)
	if not src or not src:getSquare() or src:getObjectIndex() == -1 or src:getFluidAmount() <= 0 then
		return U.fail(t, "no water there")
	end
	if o.verb == "drink_tap" then
		t.thirst = U.stat(p, "THIRST")
		-- The real callback walks, removes an eating mask, drinks, then re-wears it (:2038-2048).
		ISWorldObjectContextMenu.onDrink(nil, src, p:getPlayerNum())
	else
		t.items, t.before = o.data.all or { o.data.it }, {}
		for i, it in ipairs(t.items) do
			local fc = it:getFluidContainer()
			if not has(p, it) or not it:getContainer() or not fc then return U.fail(t, "container gone") end
			t.before[i] = fc and fc:getAmount() or 0
		end
		ISWorldObjectContextMenu.onTakeWater(nil, src, o.data.all, o.data.it, p:getPlayerNum())
	end
end
local function waterUseStart(p, t, o)
	local up = ISWaitWhileGettingUp:new(p)
	up:setOnComplete(beginWaterUse, p, t, o)
	Q(up)
end
G.X.drink_tap = {
	start = waterUseStart,
	step = queueStep(1200, function(p, t)
		if t.thirst == nil then return "didn't start drinking" end
		if t.thirst > 0.05 and U.stat(p, "THIRST") > t.thirst - 0.01 then return "didn't drink" end
	end),
}
-- fill (gym 0.4.56): the Fill menu's own handler, ISWorldObjectContextMenu.onTakeWater (:2050). It walks next to the
-- source, takes each container into the main inventory, queues ISTakeWaterAction with it and puts it back; with a
-- list (Fill All) it fills each in turn. Done when one of them holds more than before.
local function fluidIn(it)
	local fc = it and it:getFluidContainer()
	return fc and fc:getAmount() or 0
end
G.X.fill = {
	start = waterUseStart,
	step = queueStep(3000, function(p, t)
		if not t.items then return "didn't start filling" end
		for i, it in ipairs(t.items) do if fluidIn(it) > t.before[i] + 0.01 then return nil end end
		return "didn't fill"
	end),
}
-- Wash uses the submenu's get-up wrapper and callbacks (ISContextMenu:onGetUpAndThen, :1046;
-- ISWorldObjectContextMenu.onWashClothing/onWashYourself, :1777-1825). Recheck the source and items after
-- getting up; a disappeared object or insufficient water is an expected refusal, not a caught exception.
local function beginWash(p, t, o)
	local src = o.data.src
	if not washSource(p, src) then return U.fail(t, "water source gone") end
	if o.verb == "wash_yourself" then
		t.before = ISWashYourself.GetRequiredWater(p)
		if t.before == 0 or src:getFluidAmount() < 1 then return U.fail(t, "nothing to wash or no water") end
		ISWorldObjectContextMenu.onWashYourself(p, src, p:getInventory():getSoapList(nil, false))
		return
	end
	local allowed = {}
	for _, group in ipairs(washGroups(p)) do for _, it in ipairs(group.items) do allowed[it] = true end end
	for _, it in ipairs(o.data.items) do if not allowed[it] then return U.fail(t, "item no longer washable") end end
	local _, water = ISWorldObjectContextMenu.calculateSoapAndWaterRequired(o.data.items)
	if src:getFluidAmount() < water then return U.fail(t, "not enough water") end
	t.converted, t.expected, t.counts = {}, {}, {}
	for _, it in ipairs(o.data.items) do
		local result = it:getItemAfterCleaning()
		if result then
			t.converted[it] = true
			t.expected[result] = (t.expected[result] or 0) + 1
			t.counts[result] = p:getInventory():getCountTypeRecurse(result)
		end
	end
	ISWorldObjectContextMenu.onWashClothing(p, src, p:getInventory():getSoapList(nil, true), o.data.items, nil)
end
local function washStart(p, t, o)
	local up = ISWaitWhileGettingUp:new(p)
	up:setOnComplete(beginWash, p, t, o)
	Q(up)
end
G.X.wash_yourself = {
	start = washStart,
	step = queueStep(6000, function(p, t)
		if not t.before or ISWashYourself.GetRequiredWater(p) >= t.before then return "didn't wash" end
	end),
}
G.X.wash = {
	start = washStart,
	step = queueStep(20000, function(p, t, o)
		if not t.converted then return "didn't start washing" end
		for _, it in ipairs(o.data.items) do
			if t.converted[it] then
				if has(p, it) then return "bandage still dirty" end
			elseif it:hasBlood() or it:hasDirt() then return "item still dirty" end
		end
		for result, n in pairs(t.expected) do
			if p:getInventory():getCountTypeRecurse(result) < t.counts[result] + n then return "cleaned item missing" end
		end
	end),
}
G.X.equip = {
	start = function(p, t, o) ISInventoryPaneContextMenu.equipWeapon(o.data.it, true, o.data.both, p:getPlayerNum()) end,
	step = queueStep(300, function(p, t, o) if p:getPrimaryHandItem() ~= o.data.it then return "not in hand" end end),
}
G.X.unequip = {
	start = function(p, t, o) Q(ISUnequipAction:new(p, o.data.it, 50)) end,
	step = queueStep(300, function(p, t, o) if p:getPrimaryHandItem() == o.data.it then return "still in hand" end end),
}
G.X.wear = {
	start = function(p, t, o) ISInventoryPaneContextMenu.wearItem(o.data.it, p:getPlayerNum()) end,
	step = queueStep(600, function(p, t, o) if not worn(p, o.data.it) then return "not wearing it" end end),
}
G.X.take_off = {
	start = function(p, t, o) Q(ISUnequipAction:new(p, o.data.it, 50)) end,
	step = queueStep(600, function(p, t, o) if worn(p, o.data.it) then return "still wearing it" end end),
}
local function itemCount(p) local n = 0; U.eachItem(p:getInventory(), function() n = n + 1 end); return n end
G.X.craft = {
	start = function(p, t, o)
		t.n0 = itemCount(p)
		ISInventoryPaneContextMenu.OnNewCraft(o.data.it, o.data.recipe, p:getPlayerNum(), false)
	end,
	step = queueStep(1800, function(p, t, o)
		if has(p, o.data.it) and itemCount(p) == t.n0 then return "nothing made" end
	end),
}
-- the health panel's toPlayerInventory (ISHealthPanel.lua:1117-1127): a supply from a bag or a container nearby
-- comes into the main inventory first
local function toInventory(p, it)
	if it:getContainer() ~= p:getInventory() then
		Q(ISInventoryTransferUtil.newInventoryTransferAction(p, it, it:getContainer(), p:getInventory()))
	end
end
-- each handler's perform, with the character as its own doctor (ISHealthPanel.lua; gym 0.4.57 for all but bandage)
G.X.bandage = {
	start = function(p, t, o)
		toInventory(p, o.data.it)
		Q(ISApplyBandage:new(p, p, o.data.it, o.data.part, true))
	end,
	step = queueStep(900, function(p, t, o) if not o.data.part:bandaged() then return "not bandaged" end end),
}
G.X.disinfect = {   -- HDisinfect:perform :1351-1356; ISDisinfect:complete raises the part's alcohol level
	start = function(p, t, o)
		t.level = o.data.part:getAlcoholLevel()
		toInventory(p, o.data.it)
		Q(ISDisinfect:new(p, p, o.data.it, o.data.part))
	end,
	step = queueStep(900, function(p, t, o) if o.data.part:getAlcoholLevel() <= t.level then return "not disinfected" end end),
}
G.X.poultice = {   -- HApplyPoultice:perform :1277-1282
	start = function(p, t, o)
		toInventory(p, o.data.it)
		Q(o.data.pl.cls():new(p, p, o.data.it, o.data.part))
	end,
	step = queueStep(900, function(p, t, o) if not o.data.pl.on(o.data.part) then return "not applied" end end),
}
G.X.stitch = {   -- HStitch:perform :1434-1448
	start = function(p, t, o)
		for _, it in ipairs(o.data.move) do toInventory(p, it) end
		Q(ISStitch:new(p, p, o.data.it, o.data.part, true))
	end,
	step = queueStep(1800, function(p, t, o) if not o.data.part:stitched() then return "not stitched" end end),
}
G.X.remove_glass = {   -- HRemoveGlass:perform :1520-1530: by hand, handPain true
	start = function(p, t, o)
		if o.data.it then toInventory(p, o.data.it) end
		Q(ISRemoveGlass:new(p, p, o.data.part, o.data.it == nil))
	end,
	step = queueStep(1800, function(p, t, o) if o.data.part:haveGlass() then return "glass still in" end end),
}
G.X.remove_bullet = {   -- HRemoveBullet:perform :1706-1711
	start = function(p, t, o)
		toInventory(p, o.data.it)
		Q(ISRemoveBullet:new(p, p, o.data.part))
	end,
	step = queueStep(1800, function(p, t, o) if o.data.part:haveBullet() then return "bullet still in" end end),
}
G.X.clean_burn = {   -- HCleanBurn:perform :1755-1760
	start = function(p, t, o)
		toInventory(p, o.data.it)
		Q(ISCleanBurn:new(p, p, o.data.it, o.data.part))
	end,
	step = queueStep(900, function(p, t, o) if o.data.part:isNeedBurnWash() then return "burn not cleaned" end end),
}
G.X.splint = {   -- HSplint:perform :1620-1634: the sheet, then the plank (or a made splint alone)
	start = function(p, t, o)
		if o.data.sheet then toInventory(p, o.data.sheet) end
		toInventory(p, o.data.it)
		Q(ISSplint:new(p, p, o.data.sheet, o.data.it, o.data.part, true))
	end,
	step = queueStep(1800, function(p, t, o) if o.data.part:getSplintFactor() <= 0 then return "not splinted" end end),
}
G.X.unbandage = {
	start = function(p, t, o) Q(ISApplyBandage:new(p, p, nil, o.data.part, false)) end,
	step = queueStep(900, function(p, t, o) if o.data.part:bandaged() then return "still bandaged" end end),
}
G.X.unstitch = {
	start = function(p, t, o) Q(ISStitch:new(p, p, nil, o.data.part, false)) end,
	step = queueStep(900, function(p, t, o) if o.data.part:stitched() then return "still stitched" end end),
}
G.X.unsplint = {
	start = function(p, t, o) Q(ISSplint:new(p, p, nil, nil, o.data.part, false)) end,
	step = queueStep(900, function(p, t, o) if o.data.part:getSplintFactor() > 0 then return "still splinted" end end),
}
G.X.sleep = {
	start = function(p, t, o) pcall(function() p:setSneaking(false) end) end,
	step = function(p, t, o)
		local asleep = try(function() return p:isAsleep() end) == true
		if asleep then t.slept = true; return end
		if t.slept then return U.done(t, "woke up") end
		if not t.t1 then
			if U.bedStep(p, t, o.data.bed) then t.t1 = tick() end
			if tick() - t.t0 > 2400 then U.fail(t, "couldn't reach the bed") end
			return
		end
		if qlen(p) == 0 and tick() - t.t1 > 90 then
			-- the game's own reasons, as it shows them over the character's head
			U.fail(t, sleepBlock(p) or "couldn't fall asleep")
		end
	end,
}

local function label(o)
	local i = o.info
	local what = i.name or i.recipe or i.dir or i.type or i.part or ""
	if o.verb == "enter" then what = (i.rooms and i.rooms[1] or "building") .. " " .. math.floor(i.d or 0) .. " tiles" end
	if o.verb == "attack" or o.verb == "shove" then what = "zombie " .. math.floor(i.d or 0) .. " tiles" end
	if o.verb == "go_room" then what = i.name end
	if o.verb == "craft" then what = (i.recipe or "") .. " (" .. (i.name or "") .. ")" end
	return (o.verb:gsub("_", " ") .. " " .. tostring(what)):gsub("%s+$", "")
end

-- The option that is running, picked again: the same verb and the same visible fields, leaving out those that change
-- as the character moves or the target turns (distance, direction, age, zombies that way, closing, facing).
local MOVING_FIELDS = { d = true, dx = true, dy = true, age = true, zombies = true, closing = true, facing = true }
local function sameOption(a, b)
	if not a or not b or a.verb ~= b.verb then return false end
	local targetCheck = G.sameTargets and G.sameTargets[a.verb]
	if targetCheck and not targetCheck(a, b) then return false end
	-- Washing choices may have identical visible labels at different sinks, or for two shirts of the same
	-- type. Carry on only for the same actual source and selected items. These local references are not input
	-- to the network. For All, item order may change as soap requirements change, but the target set must match.
	if a.verb == "wash" or a.verb == "wash_yourself" then
		if a.data.src ~= b.data.src then return false end
		if a.verb == "wash" then
			if #a.data.items ~= #b.data.items then return false end
			local selected = {}
			for _, it in ipairs(a.data.items) do selected[it] = true end
			for _, it in ipairs(b.data.items) do if not selected[it] then return false end end
		end
	end
	for k, v in pairs(a.info) do if not MOVING_FIELDS[k] and b.info[k] ~= v then return false end end
	for k, v in pairs(b.info) do if not MOVING_FIELDS[k] and a.info[k] ~= v then return false end end
	return true
end

function G.start(p, o, note)
	H.why = note or ""
	if o.verb == "continue" then return end
	-- Picking the running option again carries on with it, as continue does (gym 0.4.63). Decisions come every game
	-- minute while an action runs (gym 0.4.21), at 20x every few ticks, and starting over each time (stopMoving, a
	-- new path, the age back to 0) kept actions from finishing: on 2026-10-13 (09:30-11:40), 1,801 decisions picked
	-- the running option again (craft 756, climb_fence 361, rest 221, pick_up 157, go_room 118), against 1,530
	-- that picked continue. A different target still starts the new one.
	local cur = GS.cur
	if cur and cur.status == "running" and sameOption(cur.o, o) then return end
	stopMoving(p)
	local t = { verb = o.verb, goal = o.verb, status = "running", t0 = tick(), args = {}, msg = "", o = o }
	GS.cur = t
	H.goal, H.source, H.action = label(o), "agent", label(o)
	local ok, e = pcall(G.X[o.verb].start, p, t, o)
	if not ok then t.status, t.msg = "failed", "error: " .. tostring(e) end
end

function G.step(p)
	local t = GS.cur
	if not t or t.status ~= "running" then return end
	local ok, e = pcall(G.X[t.verb].step, p, t, t.o)
	if not ok then t.status, t.msg = "failed", "error: " .. tostring(e) end
	if t.status ~= "running" then
		pcall(function() p:setRunning(false) end)
		H.action = t.verb .. ": " .. t.status .. (t.msg ~= "" and (" (" .. t.msg .. ")") or "")
	end
end

---------------------------------------------------------------- asking the agent
function G.request(p, reason)
	GS.id = GS.id + 1
	local opts = G.options(p)
	GS.opts = opts
	local out = {}
	for i, o in ipairs(opts) do out[i] = o.info end
	local cur = GS.cur
	local msg = { id = GS.id, reason = reason, err = A.s.err, gym = G.VERSION, obs = G.observe(p), options = out,
		last = cur and { verb = cur.verb, status = cur.status, msg = cur.msg, age = tick() - cur.t0 } or nil }
	U.writeFile("obs.json", A.json(msg))
	GS.waiting, GS.reqTick, GS.lastReq = true, tick(), GS.gt
	GS.lastHp = p:getBodyDamage():getOverallBodyHealth()
	local n = 0
	for _, e in ipairs(visibleZombies(p, 4)) do if not e.blocked then n = n + 1 end end
	GS.lastClose = n
end

function G.poll(p)
	local line = U.readFirstLine("act.txt")
	if not line then return end
	local parts = U.split(tostring(line), "|")
	if tonumber(parts[1]) ~= GS.id then return end
	GS.waiting = false
	local o = GS.opts and GS.opts[(tonumber(parts[2]) or -1) + 1]
	if o then G.start(p, o, parts[3]) end
end

-- why a new decision is needed now, or nil
function G.needDecision(p)
	local cur = GS.cur
	if not cur or cur.status ~= "running" then return cur and cur.status or "idle" end
	-- more zombies in sight within 4 tiles than at the last decision: ask now (each request stores the count, so
	-- one zombie asks once, and again only after a decision that saw it gone)
	local n = 0
	for _, e in ipairs(visibleZombies(p, 4)) do if not e.blocked then n = n + 1 end end
	if n > (GS.lastClose or 0) then return "zombie close" end
	if GS.gt - GS.lastReq < STEADY then return nil end
	if GS.lastHp and p:getBodyDamage():getOverallBodyHealth() < GS.lastHp - 0.5 then return "hurt" end
	return "still at it"
end

---------------------------------------------------------------- death and the next life
function G.dead(p)
	if not GS.deadSent then
		GS.deadSent = true
		GS.id = GS.id + 1
		local ok, obs = pcall(G.observe, p, true)
		U.writeFile("obs.json", A.json({ id = GS.id, reason = "died", dead = true, obs = ok and obs or { dead = true }, options = {} }))
		GS.cur, GS.waiting, GS.opts = nil, false, nil
		GS.respawn = { last = getTimestampMs() }
		H.goal, H.action, H.why = "", "DEAD", "starting a new character..."
	end
	G.respawnStep()
end

-- Where a new life starts: the owner's decision of 2026-10-12 (evening). The town is picked at random on the
-- game's own spawn screen, and the game puts the character at one of that town's own start points. Gym
-- 0.4.24-0.4.32 swapped those for a random square of a random ground-floor room of the town (G.spawnPoint),
-- clear of the last 20 deaths. That square was a corner of the room's tiles (whole-number x and y), and next
-- to a wall it lay on the wall's line, where the game's pathfinder finds no way anywhere; others were water
-- (a boathouse) or closed rooms. Seven lives on 2026-10-12 never left the spot they started on, for up to 66
-- game hours, and the owner asked for the game's own start options back.

-- press the death screen's and character creation's own buttons, one every RESPAWN_MS. Each step looks at which
-- screen is up and presses only its button, and a second Respawn press is ignored by the game
-- (CoopCharacterCreation:newPlayerMouse returns while a creation window exists), so nothing is pressed twice.
-- Until gym 0.4.20 a step came every 1.5 s, and each trait pick took two (ask, then read the answer): about 23 s
-- from a death to the next life (backlog N8). The death screen's own 3 s wait (ISPostDeathUI:update) stays.
local RESPAWN_MS = 300
function G.respawnStep()
	local r = GS.respawn
	if not r or getTimestampMs() - r.last < RESPAWN_MS then return end
	r.last = getTimestampMs()
	local w = CoopCharacterCreation.instance
	if not w then
		local ui = ISPostDeathUI.instance and ISPostDeathUI.instance[0]
		if ui and ui.waitOver then ui:onRespawn() end
		return
	end
	G.creationStep(w.mapSpawnSelect, w.charCreationProfession, w.charCreationMain)
end

-- One press on whichever new-character screen is up: the town (a random one of the spawn screen's), the
-- profession and traits, then the last screen's Next. The same three screens follow a death in the game
-- (CoopCharacterCreation) and the main menu's Continue on a save whose character is dead (MapSpawnSelect.instance
-- and MainScreen.instance's panels, OptionScreens/MainScreen.lua continueLatestSaveAux 1244-1274), which the
-- loader presses after the game watcher restarted the game (AIvZLoader.lua). True if something was pressed.
function G.creationStep(spawn, prof, main)
	if spawn and spawn:isVisible() then
		local lb = spawn.listbox
		local towns = {}
		for i, item in ipairs(lb and lb.items or {}) do if item.item and item.item.region then towns[#towns + 1] = i end end
		if #towns > 0 then lb.selected = towns[ZombRand(#towns) + 1] end
		spawn:clickNext()
		return true
	elseif prof and prof:isVisible() then
		-- with the agent playing and G.CHOOSE_TRAITS on, it picks traits here (AIvZGymActions.lua); otherwise, or if that fails, Next
		local handled = G.CHOOSE_TRAITS and G.creation and G.active() and select(2, pcall(G.creation, prof))
		if not handled then
			if G.creationRepair then pcall(G.creationRepair, prof) end   -- never start overdrawn
			-- CharacterCreationProfession:render disables playButton while PointToSpend() < 0;
			-- ISButton:onMouseUp checks its enabled state. Directly invoking NEXT used to bypass both.
			if G.creationReady and G.creationReady(prof) then
				prof:onOptionMouseDown(prof.playButton, 0, 0)
			end
		end
		return true
	elseif main and main:isVisible() then
		main:onOptionMouseDown({ internal = "NEXT" }, 0, 0)
		return true
	end
	return false
end

-- The game keeps a timed-action queue per character, keyed by the character, and never drops one
-- (ISTimedActionQueue.queues[character] = o, client/TimedActions/ISTimedActionQueue.lua:144; nothing sets it back to
-- nil, and Kahlua has no weak tables). A player dies a few times in a game; the agent dies a thousand times a day,
-- and every dead character stayed in memory with all it refers to: its inventory, body, sound emitter and corpse.
-- On 2026-10-13 the heap held 45 IsoPlayer objects after 44 deaths in that game (jcmd GC.class_histogram), and the
-- old generation's live size grew by about 4 MB a life (backlog N16). Each new life forgets the dead ones' queues.
local function forgetDeadQueues()
	local queues = ISTimedActionQueue and ISTimedActionQueue.queues
	if not queues then return end
	local dead = {}
	for chr in pairs(queues) do
		if instanceof(chr, "IsoGameCharacter") and chr:isDead() then dead[#dead + 1] = chr end
	end
	for _, chr in ipairs(dead) do queues[chr] = nil end
end

function G.newLife()
	GS.deadSent, GS.respawn, GS.cur, GS.waiting, GS.opts, GS.creation = false, nil, nil, false, nil, nil
	GS.blds, GS.water, GS.around, GS.rcache, GS.lastHp, GS.lastClose = nil, nil, nil, nil, nil, nil
	forgetDeadQueues()
	A.event("a new life begins")
end

-- A new character (or a game just loaded): the world round it loads over the first seconds, and the first
-- decisions used to come before that and fail at once ("blocked": no squares there yet). Wait 3 s and a game
-- minute, 15 s at most.
function G.settled(p)
	local d = p:getDescriptor()
	local who = d:getForename() .. " " .. d:getSurname()
	if GS.who ~= who then
		GS.who, GS.settle = who, { at = getTimestampMs(), age = getGameTime():getWorldAgeHours() }
		H.action = "getting my bearings"
	end
	local s = GS.settle
	if not s then return true end
	local real = getTimestampMs() - s.at
	if real > 15000 or (real > 3000 and getGameTime():getWorldAgeHours() - s.age > 1 / 60) then GS.settle = nil end
	return GS.settle == nil
end

---------------------------------------------------------------- every tick while the agent is connected
function G.tick(p)
	if p:isDead() then return G.dead(p) end
	if GS.deadSent then G.newLife() end
	if try(function() return p:isAsleep() end) then
		H.action = "asleep"
		if tick() % 10 == 0 then G.step(p) end
		return
	end
	GS.gt = GS.gt + (U.getSpeed() or 1)
	-- standing in furniture: off it first (the body's doing, like walking off with the keys), and no new
	-- decisions until then. What was running carries on to its end, unless the step itself cuts it short.
	local stepping = A.stepOff(p)
	local cur = GS.cur
	if stepping and A.s.stepOff and cur and cur.status == "running" and cur.verb ~= "sleep" then
		U.fail(cur, "standing in furniture (" .. tostring(A.s.stepOff.what) .. ")")
	end
	if not G.settled(p) then return end
	if tick() % 4 == 0 then G.step(p) end
	if stepping then H.action = "stepping off the furniture"; return end
	if GS.waiting then
		if tick() % 2 == 0 then G.poll(p) end
		if tick() - GS.reqTick > ANSWER_WAIT then GS.waiting = false end
		return
	end
	local why = G.needDecision(p)
	if why then G.request(p, why) end
end

-- Bootstrap the new family on the first reload from an older three-file loader. Extending only this
-- explicit mod-file allow-list also makes subsequent reloads refresh it; no IPC-provided path is run.
if AIvZLoader and AIvZLoader.FILES then
	local listed = false
	for _, f in ipairs(AIvZLoader.FILES) do if f == "AIvZGymHousehold.lua" then listed = true end end
	if not listed then table.insert(AIvZLoader.FILES, "AIvZGymHousehold.lua") end
end
