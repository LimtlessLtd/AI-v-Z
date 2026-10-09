-- AIvZGym.lua: Project Zomboid as a gym for the self-taught agent (agent/ in the repo).
--
--   obs.json OUT  when a decision is needed: what the character perceives, and every option a player
--                 would have right now. Written again with "dead" when the character dies.
--   act.txt  IN   "id|option|note" from the agent (option is 0-based; note shows on the HUD)
--   gym.txt  IN   heartbeat "on|n" from the agent. While it keeps changing, the agent plays instead of the
--                 rules baseline (the keys still hand control to you, as before)
--
-- The options are what a player could do now, like the right-click menus: wait, rest, walk or run in a
-- direction, go into a building or another room, attack or shove a zombie, open or close a door, window or
-- curtain, climb through a window, smash one, clear its glass, search a container, take an item out of one
-- it has searched, drop/eat/drink/equip/wear/take off an item, craft one of an item's own recipes, drink
-- from a tap, bandage a wound, sleep. Nothing in here judges what's good: the agent learns that from what
-- happens. The doing (pathfinding, swings, the game's timed actions) comes from AIvZ.lua.
-- After a death, it starts a new character in a random town by pressing the game's own buttons in code.

local A = AIvZ
local U = A.u
A.gym = A.gym or {}
local G = A.gym
G.VERSION = "0.2.0"
G.s = G.s or { id = 0, waiting = false, cur = nil, beat = nil, beatAt = 0, beatCheck = 0, lastReq = -99999 }
local GS = G.s
GS.gt = GS.gt or 0
if GS.lastReq > GS.gt then GS.lastReq = -99999 end   -- reloaded over a version that counted real ticks
local try, P, sqAt, Q, qlen, r1, r2 = U.try, U.P, U.sqAt, U.Q, U.qlen, U.r1, U.r2
local H = A.hud

-- DECIDE_GAP and RECHECK are in game-time ticks (GS.gt: a tick at 5x speed counts five times), so the agent
-- gets the same rhythm of decisions per game minute at any speed you pick
local DECIDE_GAP = 45      -- at most this often while something is running (interrupts)
local RECHECK = 600        -- a long-running option gets a "continue?" decision this often
local ANSWER_WAIT = 600    -- real ticks: give up waiting for the agent and ask again
local DIRECT_RECIPES = { "RipClothing", "OpenCannedFood", "OpenCannedFoodWithKnifeOrSharpStoneFlake" }
local DIRS = { { "N", 0, -1 }, { "NE", 1, -1 }, { "E", 1, 0 }, { "SE", 1, 1 }, { "S", 0, 1 }, { "SW", -1, 1 },
	{ "W", -1, 0 }, { "NW", -1, -1 } }

local function tick() return A.s.tick end
local function dist(p, x, y) return math.sqrt((x - p:getX()) ^ 2 + (y - p:getY()) ^ 2) end
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
	if U.waterIn(it) then return "drink" end
	if U.medKind(it) then return "medical" end
	if instanceof(it, "HandWeapon") then return "weapon" end
	if instanceof(it, "InventoryContainer") then return "bag" end
	if instanceof(it, "Clothing") then return "clothing" end
	if instanceof(it, "Literature") then return "literature" end
	return "other"
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
	local water = U.waterIn(it)
	if water then i.water = r2(water) end
	local med = U.medKind(it)
	if med then i.med = med end
	if instanceof(it, "HandWeapon") then
		local cm = it:getConditionMax()
		i.dmg = r2(it:getMaxDamage())
		i.cond = cm > 0 and r2(it:getCondition() / cm) or 0
		i.range = r2(it:getMaxRange())
		i.ranged = it:isRanged() == true
		i.twoHand = it:isTwoHandWeapon() == true
	end
	if instanceof(it, "InventoryContainer") then i.cap = U.bagCapacity(it) end
	if instanceof(it, "Clothing") or instanceof(it, "InventoryContainer") then
		i.worn = try(function() return p:isEquipped(it) end) == true
	end
	return i
end

---------------------------------------------------------------- what the character perceives
function G.observe(p, dead)
	local o = {}
	local gt, cm = getGameTime(), getClimateManager()
	local d = p:getDescriptor()
	local m = U.mem(p)
	o.who = { name = d:getForename() .. " " .. d:getSurname(), save = tostring(getWorld():getWorld()) }
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
	o.body = A.wounds(p)
	o.asleep = try(function() return p:isAsleep() end) == true
	o.weather = { rain = r2(try(function() return cm:getRainIntensity() end) or 0), temp = r1(try(function() return cm:getTemperature() end) or 20) }
	o.weight, o.maxWeight = r1(p:getInventory():getCapacityWeight()), r1(p:getMaxWeight())
	local held = p:getPrimaryHandItem()
	o.held = held and G.itemInfo(p, held) or nil
	o.inv = {}
	U.eachItem(p:getInventory(), function(it)
		if #o.inv < 40 and it ~= held then o.inv[#o.inv + 1] = G.itemInfo(p, it) end
	end)
	o.zombies = {}
	for i, e in ipairs(A.zombies(p, 30)) do
		if i > 40 then break end
		o.zombies[#o.zombies + 1] = { dx = r1(e.dx), dy = r1(e.dy), d = r1(e.d), seen = e.seen, chasing = e.chasing,
			blocked = e.blocked, down = try(function() return e.z:isOnFloor() end) == true }
	end
	local sq = p:getCurrentSquare()
	local room = sq and sq:getRoom()
	o.where = { outside = p:isOutside(), room = room and try(function() return room:getName() end) or nil }
	local info = A.buildingInfo(p, false)
	if info then
		o.where.building = info.id
		o.where.doorsOpen, o.where.windowsOpen, o.where.curtainsOpen = #info.doorsOpen, #info.windowsOpen, #info.curtainsOpen
		o.where.smashed = info.smashed
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
			if sq then
				local d = math.sqrt(dx * dx + dy * dy)
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
						if U.isDoor(o) then out.doors[#out.doors + 1] = e
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

function G.options(p)
	local list = {}
	local pn = p:getPlayerNum()
	local cur = GS.cur
	if cur and cur.status == "running" then add(list, "continue", { what = cur.verb, age = tick() - cur.t0 }) end
	add(list, "wait", {})
	add(list, "rest", {})
	local zs = A.zombies(p, 30)
	for _, d in ipairs(DIRS) do
		local n = zombiesToward(zs, d[1])
		add(list, "walk", { dir = d[1], dx = d[2], dy = d[3], zombies = n }, { dx = d[2], dy = d[3] })
		add(list, "run", { dir = d[1], dx = d[2], dy = d[3], zombies = n }, { dx = d[2], dy = d[3] })
	end
	-- buildings around (the nearest 5 apart from this one)
	if not GS.blds or tick() - GS.blds.at > 240 then GS.blds = { at = tick(), list = A.scanBuildings(p, 60) } end
	local here = A.buildingInfo(p, false)
	local m = U.mem(p)
	m.visited = m.visited or {}
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
			if r:getZ() == math.floor(p:getZ()) and r ~= myDef then
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
		local info = { d = r1(e.d), dx = r1(e.dx), dy = r1(e.dy), seen = e.seen, chasing = e.chasing, blocked = e.blocked,
			down = try(function() return e.z:isOnFloor() end) == true }
		add(list, "attack", info, { z = e.z })
		if e.d < 1.6 and count(list, "shove") < 2 then add(list, "shove", info, { z = e.z }) end
	end
	-- doors, windows, curtains
	local ar = G.scanAround(p)
	for i = 1, math.min(4, #ar.doors) do
		local e = ar.doors[i]
		add(list, "door", { d = r1(e.d), open = e.open, locked = e.locked, exterior = e.exterior }, e)
	end
	local nw, nc, ns, ng = 0, 0, 0, 0
	for _, e in ipairs(ar.windows) do
		if not e.barricaded then
			local info = { d = r1(e.d), open = e.open, locked = e.locked, exterior = e.exterior, smashed = e.smashed, glass = e.glass }
			if not e.smashed and nw < 4 then nw = nw + 1; add(list, "window", info, e) end
			if e.d < 2.5 and nc < 2 and try(function() return e.o:canClimbThrough(p) end) then
				nc = nc + 1; add(list, "climb", { d = info.d, exterior = e.exterior, glass = e.glass }, e)
			end
			if e.d < 2.5 and not e.smashed and ns < 2 then ns = ns + 1; add(list, "smash", { d = info.d, exterior = e.exterior }, e) end
			if e.d < 2.5 and e.glass and ng < 1 then ng = ng + 1; add(list, "clear_glass", { d = info.d }, e) end
		end
	end
	for i = 1, math.min(3, #ar.curtains) do
		local e = ar.curtains[i]
		add(list, "curtain", { d = r1(e.d), open = e.open }, e)
	end
	-- containers: search the ones not looked into yet; take from the ones it has, when standing by them
	local nt = 0
	for _, c in ipairs(ar.containers) do
		if not c.known and count(list, "search") < 6 then
			add(list, "search", { d = r1(c.d), type = c.type, indoors = c.indoors }, c)
		elseif c.known and c.d < 2.5 and nt < 12 then
			U.eachItem(c.c, function(it)
				if nt < 12 then
					nt = nt + 1
					local i = G.itemInfo(p, it)
					i.from, i.d = c.type, r1(c.d)
					add(list, "take", i, { it = it, c = c.c })
				end
			end, 1)
		end
	end
	-- the inventory
	local held = p:getPrimaryHandItem()
	if held then add(list, "unequip", G.itemInfo(p, held), { it = held }) end
	local crafts = 0
	U.eachItem(p:getInventory(), function(it)
		if it == held then return end
		local info = G.itemInfo(p, it)
		local worn = info.worn
		if instanceof(it, "Food") and count(list, "eat") < 6 then add(list, "eat", info, { it = it }) end
		if info.water and count(list, "drink") < 2 then add(list, "drink", info, { it = it }) end
		if instanceof(it, "HandWeapon") and count(list, "equip") < 3 then add(list, "equip", info, { it = it }) end
		if (instanceof(it, "Clothing") or U.isBackBag(it)) and not worn and count(list, "wear") < 3 then add(list, "wear", info, { it = it }) end
		if worn and count(list, "take_off") < 4 then add(list, "take_off", info, { it = it }) end
		if not worn and count(list, "drop") < 6 then add(list, "drop", info, { it = it }) end
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
	if not GS.water or tick() - GS.water.at > 120 then GS.water = { at = tick(), list = A.scanWater(p, 10) } end
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
	-- sleep: in the nearest bed here, or on the floor
	if b then
		local bed = A.beds(p, b)[1]
		if bed then add(list, "sleep", { bed = true, d = bed.d }, { bed = bed.o }) end
	end
	add(list, "sleep", { bed = false }, {})
	return list
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
				return logic:canPerformCurrentRecipe()
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

-- generic end: the queued actions finished (or it has been too long)
local function queueStep(maxTicks)
	return function(p, t)
		local age = tick() - t.t0
		if t.pathFailed then return U.fail(t, "no way there") end
		if qlen(p) == 0 and age > 20 then return U.done(t) end
		if age > (maxTicks or 900) then U.done(t, "took too long") end
	end
end

G.X = {}
G.X.wait = { start = function() end, step = function(p, t) if tick() - t.t0 > 120 then U.done(t) end end }
G.X.rest = {
	start = function(p) pcall(function() p:reportEvent("EventSitOnGround") end) end,
	step = function(p, t) if tick() - t.t0 > 600 then U.done(t) end end,
}
local function walkStart(n, running)
	return function(p, t, o)
		local sq = U.farthestFree(p, o.data.dx * n, o.data.dy * n)
		if not sq then return U.fail(t, "blocked") end
		pcall(function() p:setRunning(running) end)
		U.pathTo(p, t, sq:getX(), sq:getY(), sq:getZ())
	end
end
G.X.walk = { start = walkStart(12, false), step = queueStep(600) }
G.X.run = { start = walkStart(15, true), step = queueStep(600) }
G.X.enter = {
	start = function(p, t, o) t.args = { o.data.tx, o.data.ty, o.data.tz } end,
	step = function(p, t, o)
		if A.travelStep(p, t, o.data.tx, o.data.ty, o.data.tz) and qlen(p) == 0 then
			U.mem(p).visited = U.mem(p).visited or {}
			U.mem(p).visited[o.data.id] = true
			U.done(t)
		end
		if tick() - t.t0 > 3600 and t.status == "running" then U.done(t, "took too long") end
	end,
}
G.X.go_room = {
	start = function(p, t, o)
		local sq = try(function() return o.data.r:getFreeSquare() end)
		if not sq then return U.fail(t, "no free square") end
		U.pathTo(p, t, sq:getX(), sq:getY(), sq:getZ())
	end,
	step = queueStep(600),
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
G.X.door = { start = function(p, t, o) if not U.closeOpening(p, o.data) then U.fail(t, "can't reach it") end end, step = queueStep(600) }
G.X.window = G.X.door
G.X.curtain = { start = function(p, t, o) if not U.closeCurtain(p, o.data) then U.fail(t, "can't reach it") end end, step = queueStep(600) }
local function atWindow(make)
	return {
		start = function(p, t, o)
			if not luautils.walkAdjWindowOrDoor(p, o.data.sq, o.data.o, true) then return U.fail(t, "can't reach it") end
			Q(make(p, o.data.o))
		end,
		step = queueStep(600),
	}
end
G.X.climb = atWindow(function(p, w) return ISClimbThroughWindow:new(p, w, 0) end)
G.X.smash = atWindow(function(p, w) return ISSmashWindow:new(p, w) end)
G.X.clear_glass = atWindow(function(p, w) return ISRemoveBrokenGlass:new(p, w) end)
G.X.search = {
	start = function(p, t, o) luautils.walkToContainer(o.data.c, p:getPlayerNum()) end,
	step = function(p, t, o)
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
		luautils.walkToContainer(o.data.c, p:getPlayerNum())
		Q(ISInventoryTransferAction:new(p, o.data.it, o.data.c, U.carryInv(p, o.data.it)))
	end,
	step = function(p, t, o)
		if qlen(p) > 0 and tick() - t.t0 < 900 then return end
		if try(function() return p:getInventory():containsRecursive(o.data.it) end) then
			A.event("took " .. o.data.it:getDisplayName())
			U.done(t)
		else
			U.fail(t, "didn't get it")
		end
	end,
}
G.X.drop = { start = function(p, t, o) ISInventoryPaneContextMenu.dropItem(o.data.it, p:getPlayerNum()) end, step = queueStep(300) }
G.X.eat = { start = function(p, t, o) ISInventoryPaneContextMenu.eatItem(o.data.it, 1, p:getPlayerNum()) end, step = queueStep(1200) }
G.X.drink = { start = function(p, t, o) ISInventoryPaneContextMenu.onDrinkFluid(o.data.it, 1, p) end, step = queueStep(1200) }
G.X.drink_tap = {
	start = function(p, t, o)
		local obj = nil
		for _, x in ipairs(U.objList(sqAt(o.data.x, o.data.y, o.data.z))) do if U.waterAmount(x) > 0 then obj = x; break end end
		if not obj or not luautils.walkAdjObject(p, obj, true, true) then return U.fail(t, "can't reach it") end
		Q(ISTakeWaterAction:new(p, nil, obj, obj:isTaintedWater()))
	end,
	step = queueStep(1200),
}
G.X.equip = {
	start = function(p, t, o) ISInventoryPaneContextMenu.equipWeapon(o.data.it, true, o.data.it:isTwoHandWeapon(), p:getPlayerNum()) end,
	step = queueStep(300),
}
G.X.unequip = { start = function(p, t, o) Q(ISUnequipAction:new(p, o.data.it, 50)) end, step = queueStep(300) }
G.X.wear = { start = function(p, t, o) ISInventoryPaneContextMenu.wearItem(o.data.it, p:getPlayerNum()) end, step = queueStep(600) }
G.X.take_off = { start = function(p, t, o) Q(ISUnequipAction:new(p, o.data.it, 50)) end, step = queueStep(600) }
G.X.craft = {
	start = function(p, t, o) ISInventoryPaneContextMenu.OnNewCraft(o.data.it, o.data.recipe, p:getPlayerNum(), false) end,
	step = queueStep(1800),
}
G.X.bandage = {
	start = function(p, t, o)
		local band = o.data.it
		if band:getContainer() ~= p:getInventory() then Q(ISInventoryTransferAction:new(p, band, band:getContainer(), p:getInventory())) end
		Q(ISApplyBandage:new(p, p, band, o.data.part, true))
	end,
	step = queueStep(900),
}
G.X.sleep = {
	start = function(p, t, o)
		ISWorldObjectContextMenu.onConfirmSleep(nil, { internal = "YES" }, p:getPlayerNum(), o.data.bed)
	end,
	step = function(p, t)
		local asleep = try(function() return p:isAsleep() end) == true
		if asleep then t.slept = true; return end
		if t.slept then return U.done(t, "woke up") end
		if qlen(p) == 0 and tick() - t.t0 > 90 then U.fail(t, "couldn't fall asleep") end
		if tick() - t.t0 > 2400 then U.fail(t, "couldn't reach the bed") end
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
	for _, e in ipairs(A.zombies(p, 4)) do if not e.blocked then n = n + 1 end end
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
	if GS.gt - GS.lastReq < DECIDE_GAP then return nil end
	if GS.lastHp and p:getBodyDamage():getOverallBodyHealth() < GS.lastHp - 0.5 then return "hurt" end
	local n = 0
	for _, e in ipairs(A.zombies(p, 4)) do if not e.blocked then n = n + 1 end end
	if n > (GS.lastClose or 0) then return "zombie close" end
	if GS.gt - GS.lastReq > RECHECK then return "still at it" end
	return nil
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

-- press the death screen's and character creation's own buttons, one per second and a half
function G.respawnStep()
	local r = GS.respawn
	if not r or getTimestampMs() - r.last < 1500 then return end
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
	elseif w.charCreationProfession and w.charCreationProfession:isVisible() then
		w.charCreationProfession:onOptionMouseDown({ internal = "NEXT" }, 0, 0)
	elseif w.charCreationMain and w.charCreationMain:isVisible() then
		w.charCreationMain:onOptionMouseDown({ internal = "NEXT" }, 0, 0)
	end
end

function G.newLife()
	GS.deadSent, GS.respawn, GS.cur, GS.waiting, GS.opts = false, nil, nil, false, nil
	GS.blds, GS.water, GS.around, GS.rcache, GS.lastHp, GS.lastClose = nil, nil, nil, nil, nil, nil
	A.event("a new life begins")
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
	if tick() % 4 == 0 then G.step(p) end
	if GS.waiting then
		if tick() % 2 == 0 then G.poll(p) end
		if tick() - GS.reqTick > ANSWER_WAIT then GS.waiting = false end
		return
	end
	local why = G.needDecision(p)
	if why then G.request(p, why) end
end
