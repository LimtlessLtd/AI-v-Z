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
-- curtain, climb through a window, smash one, clear its glass, search a container, take an item out of one
-- it has searched, drop/eat/drink/equip/wear/take off an item, craft one of an item's own recipes, drink
-- from a tap, bandage a wound, sleep, sneak or stand up. Nothing in here judges what's good: the agent learns
-- that from what happens. The doing (pathfinding, swings, the game's timed actions) comes from AIvZ.lua.
-- After a death, it starts a new character in a random building of a random town by pressing the game's own
-- buttons in code (G.respawnStep, G.spawnPoint).

local A = AIvZ
local U = A.u
A.gym = A.gym or {}
local G = A.gym
G.VERSION = "0.4.25"
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
-- zombies the character can see right now. Unseen ones (behind walls, out of sight) are hidden world
-- state: they appear in no observation, option, direction count or decision trigger.
-- Light: a lit-enough square only. A human can't pick out a zombie standing in the dark, so a zombie on an
-- unlit square is not offered either, unless it is right next to the character. LIGHT_MIN is a guess for the
-- 0..1 square light level and has not been calibrated in game. If the light API isn't there, light is
-- unknown and only line of sight applies (obs.light.known = false says so).
local LIGHT_MIN, NEAR = 0.2, 1.5

local function squareLight(sq, pn)
	return sq and try(function() return sq:getLightLevel(pn) end)
end

local function visibleZombies(p, R)
	local out, pn = {}, p:getPlayerNum()
	for _, e in ipairs(A.zombies(p, R)) do
		if e.seen then
			local l = squareLight(e.z:getCurrentSquare(), pn)
			if e.d <= NEAR or l == nil or l >= LIGHT_MIN then out[#out + 1] = e end
		end
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
	return i
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
	o.stats = {}
	for _, k in ipairs(U.STATS) do o.stats[k:lower()] = r2(U.stat(p, k)) end
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
	return o
end

---------------------------------------------------------------- the surroundings, scanned once per decision
-- doors, windows, curtains and containers on this floor within 8 tiles
function G.scanAround(p)
	if GS.around and GS.around.tick == tick() then return GS.around end
	local px, py, pz = math.floor(p:getX()), math.floor(p:getY()), math.floor(p:getZ())
	local here = p:getCurrentSquare()
	local hb = here and here:getBuilding()
	local out = { tick = tick(), doors = {}, windows = {}, curtains = {}, containers = {} }
	local known = seen(p)
	for dx = -8, 8 do
		for dy = -8, 8 do
			local sq = sqAt(px + dx, py + dy, pz)
			local d = math.sqrt(dx * dx + dy * dy)
			if sq and perceivable(p, sq, d) then   -- not through walls or in the dark
				local n = 0
				for _, c in ipairs(U.containersOn(sq)) do
					n = n + 1
					local key = (px + dx) .. "," .. (py + dy) .. "," .. pz .. "," .. n
					out.containers[#out.containers + 1] = { c = c, sq = sq, d = d, key = key, known = known[key] == true,
						indoors = sq:getBuilding() ~= nil, type = tostring(c:getType()) }
				end
				for _, o in ipairs(U.objList(sq)) do
					if U.isDoor(o) or U.isWindow(o) then
						local other = o:getNorth() and sqAt(sq:getX(), sq:getY() - 1, pz) or sqAt(sq:getX() - 1, sq:getY(), pz)
						local ext = (sq:getBuilding() ~= nil) ~= (other ~= nil and other:getBuilding() ~= nil)
						local e = { o = o, sq = sq, d = d, exterior = ext, open = try(function() return o:IsOpen() end) == true,
							locked = U.winIs(o, "isLocked") }
						if U.isDoor(o) then
							-- the menu says "Door Is Locked" when couldBeOpen(player) is false, which counts keys (observation audit, leak 7)
							local cbo = try(function() return o:couldBeOpen(p) end)
							if cbo ~= nil then e.locked = cbo ~= true end
							out.doors[#out.doors + 1] = e
						else
							e.smashed = U.winIs(o, "isSmashed")
							e.glass = e.smashed and not U.winIs(o, "isGlassRemoved")
							e.barricaded = U.winIs(o, "isBarricaded")
							out.windows[#out.windows + 1] = e
							local cur = o:HasCurtains()
							if cur then out.curtains[#out.curtains + 1] = { o = cur, sq = cur:getSquare() or sq, d = d, open = cur:IsOpen() } end
						end
					end
				end
			end
		end
	end
	local byD = function(a, b) return a.d < b.d end
	table.sort(out.doors, byD); table.sort(out.windows, byD); table.sort(out.curtains, byD); table.sort(out.containers, byD)
	out.building = hb
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
	add(list, "rest", {})
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
		for i = 1, math.min(5, #rl) do
			local e = rl[i]
			add(list, "go_room", { name = try(function() return e.r:getName() end) or "room", d = r1(e.d), dx = r1(e.dx),
				dy = r1(e.dy), area = e.r:getW() * e.r:getH() }, { r = e.r })
		end
	end
	-- zombies
	for _, e in ipairs(zs) do
		if e.d > 8 or count(list, "attack") >= 4 then break end
		local info = zombieView(e)
		add(list, "attack", info, { z = e.z })
		if e.d < 1.6 and count(list, "shove") < 2 then add(list, "shove", info, { z = e.z }) end
	end
	-- doors, windows, curtains, with where each one is (dx, dy from the character, as for the other options with a
	-- place): a player sees which door is the one between them and a zombie. Gym 0.4.22 and earlier gave the
	-- distance only.
	local ar = G.scanAround(p)
	local function at(e)
		return r1(e.sq:getX() + 0.5 - p:getX()), r1(e.sq:getY() + 0.5 - p:getY())
	end
	for i = 1, math.min(4, #ar.doors) do
		local e = ar.doors[i]
		local dx, dy = at(e)
		add(list, "door", { d = r1(e.d), dx = dx, dy = dy, open = e.open, locked = e.locked, exterior = e.exterior }, e)
	end
	local nw, nc, ns, ng = 0, 0, 0, 0
	for _, e in ipairs(ar.windows) do
		if not e.barricaded then
			-- the lock state is not shown for a window (the game tells you only when you try it), so it is not listed
			local dx, dy = at(e)
			local info = { d = r1(e.d), dx = dx, dy = dy, open = e.open, exterior = e.exterior, smashed = e.smashed, glass = e.glass }
			if not e.smashed and nw < 4 then nw = nw + 1; add(list, "window", info, e) end
			if e.d < 2.5 and nc < 2 and try(function() return e.o:canClimbThrough(p) end) then
				nc = nc + 1; add(list, "climb", { d = info.d, dx = dx, dy = dy, exterior = e.exterior, glass = e.glass }, e)
			end
			-- the Smash entry exists only for a closed, unbroken window (ISWorldObjectContextMenuLogic.doWindowMenu)
			if e.d < 2.5 and not e.smashed and not e.open and ns < 2 then ns = ns + 1; add(list, "smash", { d = info.d, dx = dx, dy = dy, exterior = e.exterior }, e) end
			-- Remove Glass Shards needs something in the primary hand (the menu greys it out otherwise)
			if e.d < 2.5 and e.glass and p:getPrimaryHandItem() and ng < 1 then ng = ng + 1; add(list, "clear_glass", { d = info.d, dx = dx, dy = dy }, e) end
		end
	end
	for i = 1, math.min(3, #ar.curtains) do
		local e = ar.curtains[i]
		local dx, dy = at(e)
		add(list, "curtain", { d = r1(e.d), dx = dx, dy = dy, open = e.open }, e)
	end
	-- containers: search the ones not looked into yet; take from the ones it has, when standing by them.
	-- "here": in the building the character is in (or both outside); the rest are usually out of reach.
	local nt = 0
	for _, c in ipairs(ar.containers) do
		local here = c.sq:getBuilding() == ar.building
		if not c.known and count(list, "search") < 6 then
			add(list, "search", { d = r1(c.d), type = c.type, indoors = c.indoors, here = here }, c)
		elseif c.known and c.d < 2.5 and nt < 12 then
			U.eachItem(c.c, function(it)
				if nt < 12 and not it:isHidden() then
					nt = nt + 1
					local i = G.itemInfo(p, it)
					i.from, i.d, i.here = c.type, r1(c.d), here
					add(list, "take", i, { it = it, c = c.c })
				end
			end, 1)
		end
	end
	-- the inventory
	local held = p:getPrimaryHandItem()
	if held then add(list, "unequip", G.itemInfo(p, held), { it = held }) end
	local crafts = 0
	local stuffed = U.moodle(p, "FOOD_EATEN") >= 3
	U.eachItem(p:getInventory(), function(it)
		if it == held or it:isHidden() then return end
		local info = G.itemInfo(p, it)
		local worn = info.worn
		if not stuffed and count(list, "eat") < 6 then
			local ok, opening = G.eatable(p, it)
			if ok then
				info.open = opening ~= nil
				add(list, "eat", info, { it = it, opening = opening })
				info.open = nil
			end
		end
		if count(list, "drink") < 2 then
			local amount, opening = G.drinkable(p, it)
			if amount then
				info.open = opening ~= nil
				add(list, "drink", info, { it = it, opening = opening })
				info.open = nil
			end
		end
		if instanceof(it, "HandWeapon") and count(list, "equip") < 3 then add(list, "equip", info, { it = it }) end
		if (instanceof(it, "Clothing") or U.isBackBag(it)) and not worn and count(list, "wear") < 3 then add(list, "wear", info, { it = it }) end
		if worn and count(list, "take_off") < 4 then add(list, "take_off", info, { it = it }) end
		if not worn and not try(function() return it:isFavorite() end) and count(list, "drop") < 6 then add(list, "drop", info, { it = it }) end
		if crafts < 5 then
			for _, r in ipairs(G.recipes(p, it)) do
				if crafts < 5 then
					crafts = crafts + 1
					info.recipe = r.name
					add(list, "craft", info, { it = it, recipe = r.recipe })
					info.recipe = nil
				end
			end
		end
	end)
	-- taps and sinks
	if not GS.water or tick() - GS.water.at > 120 then
		local seenWater = {}
		for _, w in ipairs(A.scanWater(p, 10)) do
			if perceivable(p, sqAt(w.x, w.y, w.z), w.d) then seenWater[#seenWater + 1] = w end
		end
		GS.water = { at = tick(), list = seenWater }
	end
	for i = 1, math.min(2, #GS.water.list) do
		local w = GS.water.list[i]
		add(list, "drink_tap", { d = w.d, tainted = w.tainted, name = w.name }, { x = w.x, y = w.y, z = w.z })
	end
	-- wounds that could take a bandage, with the first bandage in the bag
	local band = nil
	U.eachItem(p:getInventory(), function(it) if not band and U.medKind(it) == "bandage" then band = it end end)
	if band then
		local parts = p:getBodyDamage():getBodyParts()
		for i = 0, parts:size() - 1 do
			local bp = parts:get(i)
			if count(list, "bandage") < 3 and not bp:bandaged() and (bp:bleeding() or bp:scratched() or bp:bitten() or bp:deepWounded()
				or try(function() return bp:isCut() end)) then
				add(list, "bandage", { part = BodyPartType.ToString(bp:getType()), bleeding = bp:bleeding(), item = band:getDisplayName() },
					{ part = bp, it = band })
			end
		end
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

-- Match the game's Drink fluid menu: filled, player-usable containers up to three litres, with an opening
-- recipe when a sealed container needs one. This includes soda and other drinks, not only clean water.
function G.drinkable(p, it)
	local fc = try(function() return it:getFluidContainer() end)
	if not fc then return nil end
	local amount = try(function() return fc:getAmount() end) or 0
	if amount < 0.05 or (try(function() return fc:getCapacity() end) or 99) > 3 then return nil end
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
	return amount, opening
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
G.X.rest = {
	start = function(p) pcall(function() p:reportEvent("EventSitOnGround") end) end,
	step = function(p, t) if tick() - t.t0 > 600 then U.done(t) end end,
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
G.X.attack = {
	start = function() end,
	step = function(p, t, o)
		local z = o.data.z
		if not z or z:isDead() then return U.done(t, z and "it's down for good" or "gone") end
		local d = dist(p, z:getX(), z:getY())
		local w = p:getPrimaryHandItem()
		local reach = (U.isMelee(w) and w:getMaxRange() or 0.9) + 0.3
		if d <= reach then
			if t.pathing then ISTimedActionQueue.clear(p); t.pathing = false end
			A.swing(p, { z = z, d = d }, w)
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
G.X.curtain = {
	start = function(p, t, o)
		t.wasOpen = isOpen(o.data.o)
		if not U.closeCurtain(p, o.data, t) then U.fail(t, "can't reach it") end
	end,
	step = queueStep(600, toggled),
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
		seen(p)[o.data.key] = true
		local n = 0
		U.eachItem(o.data.c, function() n = n + 1 end, 1)
		U.done(t, n .. " items inside")
	end,
}
G.X.take = {
	start = function(p, t, o)
		if not U.walkToContainer(p, o.data.c, t) then return U.fail(t, "can't reach it") end
		Q(ISInventoryTransferAction:new(p, o.data.it, o.data.c, U.carryInv(p, o.data.it)))
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
G.X.drink = {
	start = function(p, t, o)
		t.fluid = try(function() return o.data.it:getFluidContainer():getAmount() end) or 0
		ISInventoryPaneContextMenu.onDrinkFluid(o.data.it, 1, p, o.data.opening, o.data.it)
	end,
	step = queueStep(1200, function(p, t, o)
		if has(p, o.data.it) and (try(function() return o.data.it:getFluidContainer():getAmount() end) or 0) > t.fluid - 0.01 then return "didn't drink" end
	end),
}
G.X.drink_tap = {
	start = function(p, t, o)
		local obj = nil
		for _, x in ipairs(U.objList(sqAt(o.data.x, o.data.y, o.data.z))) do if U.waterAmount(x) > 0 then obj = x; break end end
		if not obj or not luautils.walkAdjObject(p, obj, true, true) then return U.fail(t, "can't reach it") end
		t.thirst = U.stat(p, "THIRST")
		Q(ISTakeWaterAction:new(p, nil, obj, obj:isTaintedWater()))
	end,
	step = queueStep(1200, function(p, t)
		if t.thirst > 0.05 and U.stat(p, "THIRST") > t.thirst - 0.01 then return "didn't drink" end
	end),
}
G.X.equip = {
	start = function(p, t, o) ISInventoryPaneContextMenu.equipWeapon(o.data.it, true, o.data.it:isTwoHandWeapon(), p:getPlayerNum()) end,
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
G.X.bandage = {
	start = function(p, t, o)
		local band = o.data.it
		if band:getContainer() ~= p:getInventory() then Q(ISInventoryTransferAction:new(p, band, band:getContainer(), p:getInventory())) end
		Q(ISApplyBandage:new(p, p, band, o.data.part, true))
	end,
	step = queueStep(900, function(p, t, o) if not o.data.part:bandaged() then return "not bandaged" end end),
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

function G.start(p, o, note)
	H.why = note or ""
	if o.verb == "continue" then return end
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
local SPAWN_MARGIN, DEATH_CLEAR, DEATHS_KEPT = 150, 40, 20   -- tiles, tiles, lives (G.spawnPoint)
GS.deaths = GS.deaths or {}
GS.towns = GS.towns or {}
function G.dead(p)
	if not GS.deadSent then
		GS.deadSent = true
		GS.id = GS.id + 1
		local ok, obs = pcall(G.observe, p, true)
		U.writeFile("obs.json", A.json({ id = GS.id, reason = "died", dead = true, obs = ok and obs or { dead = true }, options = {} }))
		GS.cur, GS.waiting, GS.opts = nil, false, nil
		GS.respawn = { last = getTimestampMs() }
		H.goal, H.action, H.why = "", "DEAD", "starting a new character..."
		-- where it died: the next lives start clear of it (G.spawnPoint)
		GS.deaths[#GS.deaths + 1] = { x = p:getX(), y = p:getY() }
		if #GS.deaths > DEATHS_KEPT then table.remove(GS.deaths, 1) end
	end
	G.respawnStep()
end

-- Where a new life starts (the owner's decision of 2026-10-12). The game's respawn puts a character without a
-- profession in one of the few houses its town lists (Muldraugh lists 10; Riverside, Rosewood and West Point
-- about as many): 576 lives up to that day started on 61 squares. With G.RANDOM_SPAWN on, the town is still
-- picked at random on the game's own spawn screen, and then the region's listed points are swapped for one
-- square in a random ground-floor room of a random building of that town: any building whose middle is within
-- SPAWN_MARGIN tiles of the box round the town's listed points, and none within DEATH_CLEAR tiles of where one
-- of the last DEATHS_KEPT lives died (kept for this game session only). CoopCharacterCreation:accept1 then
-- spawns there as it would at a listed point. IsoMetaGrid:getRandomRoomNotInRange and getRandomIndoorCoord
-- would do this but are empty stubs in 42.21 (they return null), and getBuildingsIntersecting only searches
-- the cell of its corner, so the building list is filtered here.
-- A standing spot inside a room can hold furniture; the character steps off it first (A.stepOff).
G.RANDOM_SPAWN = true
local function pointXY(sp)
	if sp.worldX then return sp.worldX * 300 + sp.posX, sp.worldY * 300 + sp.posY end
	return sp.posX, sp.posY
end

-- the town's buildings, worked out once per region and game session
local function townBuildings(region)
	local key = region.key or region.name
	if GS.towns[key] then return GS.towns[key] end
	local x1, y1, x2, y2
	for _, list in pairs(region.points or {}) do
		for _, sp in ipairs(list) do
			local x, y = pointXY(sp)
			if x and y then
				x1, y1 = math.min(x1 or x, x), math.min(y1 or y, y)
				x2, y2 = math.max(x2 or x, x), math.max(y2 or y, y)
			end
		end
	end
	if not x1 then return nil end
	local out = {}
	local all = getWorld():getMetaGrid():getBuildings()
	for i = 0, all:size() - 1 do
		local b = all:get(i)
		local bx, by = b:getX() + b:getW() / 2, b:getY() + b:getH() / 2
		if bx >= x1 - SPAWN_MARGIN and bx <= x2 + SPAWN_MARGIN and by >= y1 - SPAWN_MARGIN and by <= y2 + SPAWN_MARGIN then
			out[#out + 1] = b
		end
	end
	GS.towns[key] = out
	return out
end

-- one square in a random ground-floor room of a random building of the town, clear of recent deaths, or nil
function G.spawnPoint(region)
	local list = region and townBuildings(region)
	if not list or #list == 0 then return nil end
	for _ = 1, 40 do
		local b = list[ZombRand(#list) + 1]
		local bx, by = b:getX() + b:getW() / 2, b:getY() + b:getH() / 2
		local clear = true
		for _, d in ipairs(GS.deaths) do
			if math.abs(d.x - bx) < DEATH_CLEAR and math.abs(d.y - by) < DEATH_CLEAR then clear = false; break end
		end
		if clear then
			local rooms, rs = {}, b:getRooms()
			for i = 0, rs:size() - 1 do
				local r = rs:get(i)
				if r:getZ() == 0 and not r:isEmptyOutside() and r:getRects():size() > 0 then rooms[#rooms + 1] = r end
			end
			if #rooms > 0 then
				local rects = rooms[ZombRand(#rooms) + 1]:getRects()
				local rc = rects:get(ZombRand(rects:size()))
				return { posX = rc:getX() + ZombRand(math.max(1, rc:getW())), posY = rc:getY() + ZombRand(math.max(1, rc:getH())), posZ = 0 }
			end
		end
	end
	return nil
end

-- after the spawn screen's Next: the picked region with every profession's points swapped for one random square
local function randomizeSpawn(sel)
	local reg = sel.selectedRegion
	local pt = reg and reg.points and G.spawnPoint(reg)
	if not pt then return end
	local points = { unemployed = { pt } }
	for k in pairs(reg.points) do points[k] = { pt } end
	sel.selectedRegion = { name = reg.name, key = reg.key, file = reg.file, points = points }
	GS.spawnAt = pt
	A.event("new life in " .. tostring(reg.name) .. " at " .. pt.posX .. "," .. pt.posY)
end

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
	if w.mapSpawnSelect and w.mapSpawnSelect:isVisible() then
		local lb = w.mapSpawnSelect.listbox
		local towns = {}
		for i, item in ipairs(lb and lb.items or {}) do if item.item and item.item.region then towns[#towns + 1] = i end end
		if #towns > 0 then lb.selected = towns[ZombRand(#towns) + 1] end
		w.mapSpawnSelect:clickNext()
		if G.RANDOM_SPAWN then randomizeSpawn(w.mapSpawnSelect) end
	elseif w.charCreationProfession and w.charCreationProfession:isVisible() then
		-- with the agent playing and G.CHOOSE_TRAITS on, it picks traits here (AIvZGymActions.lua); otherwise, or if that fails, Next
		local handled = G.CHOOSE_TRAITS and G.creation and G.active() and select(2, pcall(G.creation, w.charCreationProfession))
		if not handled then
			if G.creationRepair then pcall(G.creationRepair, w.charCreationProfession) end   -- never start overdrawn
			w.charCreationProfession:onOptionMouseDown({ internal = "NEXT" }, 0, 0)
		end
	elseif w.charCreationMain and w.charCreationMain:isVisible() then
		w.charCreationMain:onOptionMouseDown({ internal = "NEXT" }, 0, 0)
	end
end

function G.newLife()
	GS.deadSent, GS.respawn, GS.cur, GS.waiting, GS.opts, GS.creation = false, nil, nil, false, nil, nil
	GS.blds, GS.water, GS.around, GS.rcache, GS.lastHp, GS.lastClose = nil, nil, nil, nil, nil, nil
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
