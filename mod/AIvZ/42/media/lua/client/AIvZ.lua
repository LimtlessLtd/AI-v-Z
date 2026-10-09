-- AIvZ.lua: the game half of AI-v-Z (Project Zomboid Build 42, singleplayer).
--
--   percept OUT  ~/Zomboid/Lua/aivz/percept.json  about twice a second (what the character perceives)
--   intent   IN  ~/Zomboid/Lua/aivz/intent.txt    "seq|goal|a1|a2|a3|say|why|source", written by bridge/bridge.py
--
-- Layers in this file:
--   reflex  every few ticks: swing, shove, grab a weapon or break away from zombies within ~3 tiles
--   tactics carries out the goal the bridge picked (walk, loot, eat, drink, bandage, fight, flee, close up)
--   HUD     on-screen panel with the goal, the reason, the action and vitals (F7 hides it)
-- G toggles auto fast-forward. Pressing a movement key hands control to you; the AI takes over again
-- after ~10 s without input.
--
-- Adapted from ClaudeSurvivor (c) 2026 Joel and ClaudeBot (c) 2026 whatcheers, both MIT licensed;
-- see THIRD_PARTY_NOTICES.md. All logic lives in the AIvZ table so AIvZLoader.lua can hot-reload it.

AIvZ = AIvZ or {}
local A = AIvZ
A.VERSION = "0.1.0"

local DIR = "aivz/"
local PERCEPT_EVERY = 30   -- ticks between percept writes
local INTENT_EVERY = 15    -- ticks between intent polls
local TASK_EVERY = 10      -- ticks between tactic steps
local REFLEX_EVERY = 4     -- ticks between reflex checks
local MANUAL_IDLE = 600    -- ticks without your input before the AI takes back over
local KEY_HUD = Keyboard.KEY_F7
local KEY_SPEED = Keyboard.KEY_G

A.s = A.s or { tick = 0, lastSeq = 0, task = nil, manual = false, lastHumanKey = -99999, lastMove = 0,
	reflexTick = -99999, reflexAct = "", rearmUntil = 0, autoSpeed = true, err = "", observing = false,
	kills = 0, cache = {} }
A.hud = A.hud or { visible = true, goal = "", why = "", source = "", action = "waiting for the bridge" }
A.ev = A.ev or { n = 0, list = {} }
local S, H = A.s, A.hud

---------------------------------------------------------------- helpers
local function try(f, ...) local ok, v = pcall(f, ...); if ok then return v end return nil end
local function P() return getSpecificPlayer(0) end
local function sqAt(x, y, z) return getCell():getGridSquare(x, y, z) end
local function r1(v) return math.floor((tonumber(v) or 0) * 10 + 0.5) / 10 end
local function r2(v) return math.floor((tonumber(v) or 0) * 100 + 0.5) / 100 end
local function Q(a) ISTimedActionQueue.add(a) end

-- a building's key: its corner. BuildingDef:getID() is a Java long and loses precision as a Lua number.
local function bkey(def) return def:getX() .. "," .. def:getY() end

local function qlen(p)
	local n = 0
	pcall(function() local q = ISTimedActionQueue.getTimedActionQueue(p); if q and q.queue then n = #q.queue end end)
	return n
end

local function split(s, sep)
	local out, i = {}, 1
	while true do
		local j = string.find(s, sep, i, true)
		if not j then out[#out + 1] = string.sub(s, i); break end
		out[#out + 1] = string.sub(s, i, j - 1)
		i = j + 1
	end
	return out
end

-- compass direction of (dx, dy); +y is south
local function dir8(dx, dy)
	local t = 0.4142
	local ns = (dy < -t * math.abs(dx)) and "N" or ((dy > t * math.abs(dx)) and "S" or "")
	local ew = (dx > t * math.abs(dy)) and "E" or ((dx < -t * math.abs(dy)) and "W" or "")
	if ns .. ew == "" then return "HERE" end
	return ns .. ew
end

local function getSpeed() local sc = UIManager.getSpeedControls(); return sc and sc:getCurrentGameSpeed() end
local function setSpeed(v)
	local sc = UIManager.getSpeedControls()
	if sc and sc:getCurrentGameSpeed() ~= 0 then sc:SetCurrentGameSpeed(v) end
end

function A.event(msg)
	A.ev.n = A.ev.n + 1
	local gt = getGameTime()
	A.ev.list[#A.ev.list + 1] = { id = A.ev.n, t = string.format("%02d:%02d", gt:getHour(), gt:getMinutes()), msg = tostring(msg) }
	while #A.ev.list > 12 do table.remove(A.ev.list, 1) end
end

---------------------------------------------------------------- json + files (encoder from ClaudeBot)
local function esc(s)
	s = tostring(s)
	s = s:gsub("\\", "\\\\"):gsub('"', '\\"'):gsub("\n", "\\n"):gsub("\r", ""):gsub("\t", " ")
	return s
end

local function enc(v, out)
	local t = type(v)
	if t == "table" then
		local empty = true
		for _ in pairs(v) do empty = false; break end
		if v[1] ~= nil or empty then
			out[#out + 1] = "["
			for i = 1, #v do
				if i > 1 then out[#out + 1] = "," end
				enc(v[i], out)
			end
			out[#out + 1] = "]"
		else
			out[#out + 1] = "{"
			local first = true
			for k, val in pairs(v) do
				if not first then out[#out + 1] = "," end
				first = false
				out[#out + 1] = '"' .. esc(k) .. '":'
				enc(val, out)
			end
			out[#out + 1] = "}"
		end
	elseif t == "number" then
		if v ~= v or v == math.huge or v == -math.huge then out[#out + 1] = "null"
		else out[#out + 1] = tostring(math.floor(v * 1000 + 0.5) / 1000) end
	elseif t == "boolean" then
		out[#out + 1] = tostring(v)
	elseif v == nil then
		out[#out + 1] = "null"
	else
		out[#out + 1] = '"' .. esc(v) .. '"'
	end
end

function A.json(v) local out = {}; enc(v, out); return table.concat(out) end

local function writeFile(name, s)
	local w = getFileWriter(DIR .. name, true, false)
	w:write(s)
	w:close()
end

local function readFirstLine(name)
	local r = getFileReader(DIR .. name, false)
	if not r then return nil end
	local l = r:readLine()
	r:close()
	return l
end

-- per-save memory: containers searched, buildings fully searched
local function mem(p)
	local md = p:getModData()
	md.AIvZ = md.AIvZ or {}
	local m = md.AIvZ
	m.searched = m.searched or {}
	m.looted = m.looted or {}
	return m
end

---------------------------------------------------------------- world objects
local function objList(sq)
	local t = {}
	local objs = sq:getObjects()
	for i = 0, objs:size() - 1 do t[#t + 1] = objs:get(i) end
	return t
end

local function isDoor(o)
	return instanceof(o, "IsoDoor") or (instanceof(o, "IsoThumpable") and try(function() return o:isDoor() end) == true)
end
local function isWindow(o) return instanceof(o, "IsoWindow") end

local function containersOn(sq)
	local out = {}
	for _, o in ipairs(objList(sq)) do
		local n = try(function() return o:getContainerCount() end) or 0
		for ci = 0, n - 1 do
			local c = o:getContainerByIndex(ci)
			if c then out[#out + 1] = c end
		end
	end
	return out
end

local function waterAmount(o)
	if instanceof(o, "IsoWorldInventoryObject") then return 0 end
	return try(function() return o:getFluidAmount() end) or 0
end

---------------------------------------------------------------- items
local function eachItem(c, fn, depth)
	local items = c:getItems()
	local list = {}
	for i = 0, items:size() - 1 do list[#list + 1] = items:get(i) end
	for _, it in ipairs(list) do
		fn(it, c)
		if instanceof(it, "InventoryContainer") and (depth or 0) < 1 then eachItem(it:getInventory(), fn, (depth or 0) + 1) end
	end
end

-- how much hunger this food removes, or nil if it shouldn't be eaten as is
local function foodValue(it)
	if not instanceof(it, "Food") then return nil end
	if try(function() return it:isRotten() end) then return nil end
	if try(function() return it:isbDangerousUncooked() end) and not try(function() return it:isCooked() end) then return nil end
	if try(function() return it:getScriptItem():isCantEat() end) then return nil end
	local h = try(function() return it:getHungerChange() end) or 0
	if h >= 0 then return nil end
	return -h
end

-- litres of clean drinking water in this item, and its capacity
local function waterIn(it)
	local fc = try(function() return it:getFluidContainer() end)
	if not fc then return nil end
	local amt = try(function() return fc:getAmount() end) or 0
	if amt < 0.05 then return nil end
	if try(function() return fc:isPoisonous() end) then return nil end
	if not try(function() return fc:contains(Fluid.Water) and not fc:contains(Fluid.TaintedWater) end) then return nil end
	return amt, (try(function() return fc:getCapacity() end) or amt)
end

local function medKind(it)
	local t = it:getType() or ""
	if t:find("Dirty") then return nil end
	if t:find("Bandage") or t:find("RippedSheets") then return "bandage" end
	if t:find("Disinfectant") or t:find("AlcoholWipes") then return "disinfectant" end
	if t:find("^Pills") then return "pills" end
	return nil
end

local function isMelee(w)
	return w ~= nil and instanceof(w, "HandWeapon") and not w:isRanged()
		and not try(function() return w:isBroken() end) and w:getMaxDamage() >= 0.3
end

local function weaponScore(w)
	if not isMelee(w) then return nil end
	local cm = w:getConditionMax()
	if cm <= 0 or w:getCondition() <= 0 then return nil end
	return w:getMaxDamage() * (0.3 + 0.7 * w:getCondition() / cm)
end

local function bestMelee(p)
	local best, bs = nil, 0
	eachItem(p:getInventory(), function(it)
		local s = weaponScore(it)
		if s and s > bs then best, bs = it, s end
	end)
	return best, bs
end

---------------------------------------------------------------- perception
local STATS = { "HUNGER", "THIRST", "FATIGUE", "ENDURANCE", "PANIC", "PAIN", "STRESS", "SICKNESS", "FOOD_SICKNESS", "WETNESS", "TEMPERATURE" }
local MOODLES = { "HUNGRY", "THIRST", "TIRED", "ENDURANCE", "PANIC", "PAIN", "SICK", "WET", "HYPOTHERMIA", "HYPERTHERMIA",
	"HEAVY_LOAD", "BLEEDING", "STRESS", "INJURED", "HAS_A_COLD", "DRUNK", "ZOMBIE" }

local function stat(p, k) return try(function() return p:getStats():get(CharacterStat[k]) end) or 0 end
local function moodle(p, k) return try(function() return p:getMoodles():getMoodleLevel(MoodleType[k]) end) or 0 end

-- every zombie on this floor within 45 tiles, nearest first, scanned at most once per tick
local function allZombies(p)
	if S.zc and S.zc.tick == S.tick then return S.zc.list end
	local out = {}
	local px, py, pz = p:getX(), p:getY(), p:getZ()
	local zl = getCell():getZombieList()
	for i = 0, (zl and zl:size() or 0) - 1 do
		local z = zl:get(i)
		if not z:isDead() and math.abs(z:getZ() - pz) < 1 then
			local dx, dy = z:getX() - px, z:getY() - py
			local d = math.sqrt(dx * dx + dy * dy)
			if d <= 45 then
				local sq = z:getCurrentSquare()
				local seen = (sq and try(function() return sq:isCanSee(0) end)) and true or false
				local chasing = try(function() return z:getTarget() == p end) and true or false
				out[#out + 1] = { z = z, d = d, dx = dx, dy = dy, seen = seen, chasing = chasing }
			end
		end
	end
	table.sort(out, function(a, b) return a.d < b.d end)
	S.zc = { tick = S.tick, list = out }
	return out
end

-- zombies within R tiles (R <= 45), nearest first: {z, d, dx, dy, seen, chasing}
function A.zombies(p, R)
	local out = {}
	for _, e in ipairs(allZombies(p)) do
		if e.d > R then break end
		out[#out + 1] = e
	end
	return out
end

function A.wounds(p)
	local out = {}
	local parts = p:getBodyDamage():getBodyParts()
	for i = 0, parts:size() - 1 do
		local bp = parts:get(i)
		local f = {}
		if try(function() return bp:bleeding() end) then f[#f + 1] = "bleeding" end
		if try(function() return bp:scratched() end) then f[#f + 1] = "scratch" end
		if try(function() return bp:bitten() end) then f[#f + 1] = "bite" end
		if try(function() return bp:isCut() end) then f[#f + 1] = "laceration" end
		if try(function() return bp:deepWounded() end) then f[#f + 1] = "deep wound" end
		if try(function() return bp:getFractureTime() > 0 end) then f[#f + 1] = "fracture" end
		if try(function() return bp:haveGlass() end) then f[#f + 1] = "glass" end
		if try(function() return bp:bandaged() end) then f[#f + 1] = "bandaged" end
		if #f > 0 then out[#out + 1] = { part = BodyPartType.ToString(bp:getType()), flags = f } end
	end
	return out
end

function A.inventory(p)
	local inv = { food = {}, water = {}, medical = {}, weapons = {} }
	local held = p:getPrimaryHandItem()
	eachItem(p:getInventory(), function(it)
		if instanceof(it, "Food") then
			if #inv.food < 10 then
				inv.food[#inv.food + 1] = { name = it:getDisplayName(), edible = foodValue(it) ~= nil,
					rotten = try(function() return it:isRotten() end) and true or false }
			end
		elseif waterIn(it) then
			local amt, cap = waterIn(it)
			if #inv.water < 6 then inv.water[#inv.water + 1] = { name = it:getDisplayName(), amount = r2(amt), cap = r2(cap) } end
		elseif medKind(it) then
			if #inv.medical < 8 then inv.medical[#inv.medical + 1] = { name = it:getDisplayName(), kind = medKind(it) } end
		elseif isMelee(it) and it ~= held then
			if #inv.weapons < 6 then
				inv.weapons[#inv.weapons + 1] = { name = it:getDisplayName(), cond = it:getCondition(), max = it:getConditionMax(),
					score = r2(weaponScore(it) or 0) }
			end
		end
	end)
	return inv
end

-- the building you're in, on your floor: open doors and windows, containers searched or not
function A.scanBuilding(p, b, z)
	local def = b:getDef()
	local m = mem(p)
	local info = { id = bkey(def), containers = 0, searched = 0, unsearched = {}, doorsOpen = {}, windowsOpen = {} }
	local function inside(sq) return sq ~= nil and sq:getBuilding() == b end
	for x = def:getX() - 1, def:getX2() do
		for y = def:getY() - 1, def:getY2() do
			local sq = sqAt(x, y, z)
			if sq then
				if inside(sq) then
					local n = 0
					for _, c in ipairs(containersOn(sq)) do
						n = n + 1
						local key = x .. "," .. y .. "," .. z .. "," .. n
						info.containers = info.containers + 1
						if m.searched[key] then info.searched = info.searched + 1
						else info.unsearched[#info.unsearched + 1] = { key = key, c = c, sq = sq } end
					end
				end
				for _, o in ipairs(objList(sq)) do
					if isDoor(o) or isWindow(o) then
						-- a door or window sits on the north or west edge of its square. It's on this
						-- building's outside wall if exactly one side of that edge is inside; interior
						-- doors (inside on both sides) don't keep zombies out, so they're ignored
						local other = o:getNorth() and sqAt(x, y - 1, z) or sqAt(x - 1, y, z)
						if inside(sq) ~= inside(other) then
							local open = try(function() return o:IsOpen() end)
							if isDoor(o) and open then info.doorsOpen[#info.doorsOpen + 1] = { o = o, sq = sq }
							elseif isWindow(o) and open and not try(function() return o:isSmashed() end) then
								info.windowsOpen[#info.windowsOpen + 1] = { o = o, sq = sq }
							end
						end
					end
				end
			end
		end
	end
	return info
end

function A.buildingInfo(p, fresh)
	local sq = p:getCurrentSquare()
	local b = sq and sq:getBuilding()
	if not b then return nil end
	local z = math.floor(p:getZ())
	local id = bkey(b:getDef())
	local c = S.cache.bld
	if not fresh and c and c.id == id and c.z == z and S.tick - c.at < 60 then return c end
	c = A.scanBuilding(p, b, z)
	c.at, c.z = S.tick, z
	S.cache.bld = c
	return c
end

local function roomNames(def)
	local names, seen = {}, {}
	local rooms = def:getRooms()
	for i = 0, rooms:size() - 1 do
		local n = try(function() return rooms:get(i):getName() end)
		if n and not seen[n] and #names < 4 then seen[n] = true; names[#names + 1] = n end
	end
	return names
end

-- buildings within R tiles: where they are, a square to walk to, and whether we've searched them
function A.scanBuildings(p, R)
	local px, py = math.floor(p:getX()), math.floor(p:getY())
	local seen, out = {}, {}
	local m = mem(p)
	for dx = -R, R, 4 do
		for dy = -R, R, 4 do
			local sq = sqAt(px + dx, py + dy, 0)
			local b = sq and sq:getBuilding()
			if b then
				local def = b:getDef()
				local id = bkey(def)
				if not seen[id] then
					seen[id] = true
					local cx, cy = def:getX() + def:getW() / 2, def:getY() + def:getH() / 2
					local rooms = def:getRooms()
					local tsq = nil
					for i = 0, rooms:size() - 1 do
						tsq = try(function() return rooms:get(i):getFreeSquare() end)
						if tsq and tsq:getZ() == 0 then break end
						tsq = nil
					end
					tsq = tsq or sq
					out[#out + 1] = { id = id, d = r1(math.sqrt((cx - px) ^ 2 + (cy - py) ^ 2)), dir = dir8(cx - px, cy - py),
						tx = tsq:getX(), ty = tsq:getY(), tz = tsq:getZ(), rooms = roomNames(def),
						looted = m.looted[id] and true or false, explored = try(function() return def:isAllExplored() end) and true or false }
				end
			end
		end
	end
	table.sort(out, function(a, b) return a.d < b.d end)
	while #out > 10 do table.remove(out) end
	return out
end

function A.scanWater(p, R)
	local out = {}
	local px, py, pz = math.floor(p:getX()), math.floor(p:getY()), math.floor(p:getZ())
	for dx = -R, R do
		for dy = -R, R do
			local sq = sqAt(px + dx, py + dy, pz)
			if sq then
				for _, o in ipairs(objList(sq)) do
					local amt = waterAmount(o)
					if amt > 0 then
						out[#out + 1] = { x = px + dx, y = py + dy, z = pz, d = r1(math.sqrt(dx * dx + dy * dy)), dir = dir8(dx, dy),
							name = try(function() return o:getObjectName() end) or "water", amount = r1(amt),
							tainted = try(function() return o:isTaintedWater() end) and true or false }
					end
				end
			end
		end
	end
	table.sort(out, function(a, b) return a.d < b.d end)
	while #out > 5 do table.remove(out) end
	return out
end

function A.percept(p)
	local s = { v = 1, ver = A.VERSION, tick = S.tick, ack = S.lastSeq, manual = S.manual, err = S.err, kills = S.kills }
	s.dead = p:isDead()
	local px, py, pz = p:getX(), p:getY(), math.floor(p:getZ())
	s.pos = { x = r1(px), y = r1(py), z = pz }
	local gt = getGameTime()
	local cm = getClimateManager()
	s.time = { day = gt:getNightsSurvived() + 1, hour = gt:getHour(), min = gt:getMinutes(),
		-- GameTime:getDawn()/getDusk() are stale in B42 (they read 12 and 3); the season has the real hours
		dawn = r1(try(function() return cm:getSeason():getDawn() end) or 6),
		dusk = r1(try(function() return cm:getSeason():getDusk() end) or 21),
		dark = r2(try(function() return cm:getNightStrength() end) or 0) }
	s.weather = { rain = r2(try(function() return cm:getRainIntensity() end) or 0),
		temp = r1(try(function() return cm:getTemperature() end) or 20), fog = r2(try(function() return cm:getFogIntensity() end) or 0) }
	s.outside = p:isOutside()
	local sq = p:getCurrentSquare()
	local room = sq and sq:getRoom()
	s.room = room and try(function() return room:getName() end) or nil
	local info = A.buildingInfo(p, false)
	if info then
		local openings = {}
		for _, e in ipairs(info.doorsOpen) do openings[#openings + 1] = { x = e.sq:getX(), y = e.sq:getY(), kind = "door" } end
		for _, e in ipairs(info.windowsOpen) do openings[#openings + 1] = { x = e.sq:getX(), y = e.sq:getY(), kind = "window" } end
		s.bld = { id = info.id, doorsOpen = #info.doorsOpen, windowsOpen = #info.windowsOpen, containers = info.containers,
			searched = info.searched, looted = mem(p).looted[info.id] and true or false, openings = openings }
	end
	s.health = r1(p:getBodyDamage():getOverallBodyHealth())
	s.stats = {}
	for _, k in ipairs(STATS) do s.stats[k:lower()] = r2(stat(p, k)) end
	s.moodles = {}
	for _, k in ipairs(MOODLES) do
		local v = moodle(p, k)
		if v > 0 then s.moodles[k:lower()] = v end
	end
	s.wounds = A.wounds(p)
	local w = p:getPrimaryHandItem()
	if w and instanceof(w, "HandWeapon") then
		s.weapon = { name = w:getDisplayName(), cond = w:getCondition(), max = w:getConditionMax(), melee = isMelee(w),
			score = r2(weaponScore(w) or 0) }
	end
	s.inv = A.inventory(p)
	s.weight = r1(p:getInventory():getCapacityWeight())
	s.maxWeight = r1(p:getMaxWeight())
	local zs = {}
	for i, e in ipairs(A.zombies(p, 40)) do
		if i > 60 then break end
		zs[#zs + 1] = { dx = r1(e.dx), dy = r1(e.dy), d = r1(e.d), seen = e.seen, chasing = e.chasing }
	end
	s.zombies = zs
	if not S.cache.water or S.tick - S.cache.water.at > 120 then S.cache.water = { at = S.tick, list = A.scanWater(p, 12) } end
	s.water = S.cache.water.list
	if not S.cache.blds or S.tick - S.cache.blds.at > 240 then S.cache.blds = { at = S.tick, list = A.scanBuildings(p, 60) } end
	local m = mem(p)
	for _, b in ipairs(S.cache.blds.list) do b.looted = m.looted[b.id] and true or false end
	s.buildings = S.cache.blds.list
	local t = S.task
	if t then
		s.task = { seq = t.seq, goal = t.goal, status = t.status, msg = t.msg, phase = t.phase, age = S.tick - t.t0,
			target = (t.args[1] and t.args[2] and t.args[1] ~= "") and (tostring(t.args[1]) .. "," .. tostring(t.args[2])) or nil }
	end
	s.reflex = { act = S.reflexAct, ago = S.tick - S.reflexTick }
	s.events = A.ev.list
	s.speed = getSpeed()
	return s
end

function A.writePercept(p)
	local ok, s = pcall(A.percept, p)
	if not ok then
		S.err = "percept: " .. tostring(s)
		s = { v = 1, err = S.err, tick = S.tick, ack = S.lastSeq, dead = p:isDead() }
	end
	local ok2, e2 = pcall(writeFile, "percept.json", A.json(s))
	if not ok2 then S.err = "write: " .. tostring(e2) end
end

---------------------------------------------------------------- combat (from ClaudeBot's attack/shove)
function A.swing(p, e, w)
	local z = e.z
	p:faceThisObject(z)
	if p:isAttackStarted() or try(function() return p:isPerformingAttackAnimation() end) then return end
	local down = try(function() return z:isOnFloor() end) and true or false
	pcall(function() p:setAimAtFloor(down) end)
	-- inside a weapon's reach a swing whiffs, and fists only shove: push it back instead
	if not isMelee(w) or (e.d < 0.75 and not down) then pcall(function() p:setDoShove(true) end) end
	p:setIsAiming(true)
	p:DoAttack(0)
end

-- a free square about `want` tiles away from the zombies, veering if the straight line is blocked
function A.fleeSquare(p, zs, want)
	local px, py, pz = p:getX(), p:getY(), math.floor(p:getZ())
	local fx, fy = 0, 0
	for _, e in ipairs(zs) do
		if e.d < 20 and e.d > 0.1 then
			local wgt = (20 - e.d) / 20
			fx, fy = fx - e.dx / e.d * wgt, fy - e.dy / e.d * wgt
		end
	end
	local len = math.sqrt(fx * fx + fy * fy)
	if len < 0.01 then fx, fy, len = 1, 0, 1 end
	fx, fy = fx / len, fy / len
	for _, ang in ipairs({ 0, 0.5, -0.5, 1.0, -1.0, 1.6, -1.6, 2.4, -2.4 }) do
		local c, s = math.cos(ang), math.sin(ang)
		local vx, vy = fx * c - fy * s, fx * s + fy * c
		for _, dd in ipairs({ want, want * 0.7, want * 0.45 }) do
			local sq = sqAt(math.floor(px + vx * dd), math.floor(py + vy * dd), pz)
			if sq and sq:getFloor() and try(function() return sq:isFree(false) end) then return sq end
		end
	end
	return nil
end

-- clear the action queue; the running tactic restarts from its resume point next step
function A.interrupt(p)
	ISTimedActionQueue.clear(p)
	local t = S.task
	if t and t.status == "running" then t.phase = t.resume or "start" end
end

-- Reflex: anything within ~3 tiles is handled here, every few ticks, without asking the bridge.
function A.reflex(p)
	if p:getVehicle() then return false end
	local zs = {}
	for _, e in ipairs(A.zombies(p, 3.5)) do if e.seen then zs[#zs + 1] = e end end
	if #zs == 0 then
		if S.aiming then pcall(function() p:setIsAiming(false) end); S.aiming = false end
		return false
	end
	local t = zs[1]
	local close = 0
	for _, e in ipairs(zs) do if e.d < 2 then close = close + 1 end end
	local w = p:getPrimaryHandItem()
	if close >= 3 then
		if S.tick - S.reflexTick > 60 then
			local sq = A.fleeSquare(p, A.zombies(p, 20), 10)
			if sq then
				A.interrupt(p)
				pcall(function() p:setRunning(true) end)
				Q(ISPathFindAction:pathToLocationF(p, sq:getX() + 0.5, sq:getY() + 0.5, sq:getZ()))
				S.reflexTick, S.reflexAct = S.tick, "broke away from " .. close
				A.event("reflex: broke away from " .. close .. " zombies")
				pcall(function() p:Say("Too many of them!") end)
			end
		end
		return true
	end
	if not isMelee(w) and getTimestampMs() > S.rearmUntil then
		local best = bestMelee(p)
		if best then
			S.rearmUntil = getTimestampMs() + 3000
			A.interrupt(p)
			ISInventoryPaneContextMenu.equipWeapon(best, true, best:isTwoHandWeapon(), p:getPlayerNum())
			S.reflexTick, S.reflexAct = S.tick, "grabbed " .. best:getDisplayName()
			A.event("reflex: grabbed " .. best:getDisplayName())
			return true
		end
	end
	local reach = (isMelee(w) and w:getMaxRange() or 0.9) + 0.3
	if t.d <= reach then
		if qlen(p) > 0 then A.interrupt(p) end
		A.swing(p, t, w)
		S.aiming = true
		S.reflexTick, S.reflexAct = S.tick, isMelee(w) and "swing" or "shove"
		return true
	end
	return false
end

function A.onZombieDead(z)
	local p = P()
	if p and try(function() return z:getAttackedBy() == p end) then
		S.kills = (S.kills or 0) + 1
		A.event("killed a zombie (" .. S.kills .. " so far)")
	end
end

---------------------------------------------------------------- tactics
A.tasks = {}
local function done(t, msg) t.status = "done"; if msg then t.msg = msg end end
local function fail(t, msg) t.status = "failed"; t.msg = msg; A.event(t.goal .. " failed: " .. msg) end

local function pathTo(p, t, x, y, z)
	t.pathFailed = false
	local act = ISPathFindAction:pathToLocationF(p, x + 0.5, y + 0.5, z)
	pcall(function() act:setOnFail(function() t.pathFailed = true end) end)
	Q(act)
end

local function farthestFree(p, dx, dy)
	local px, py, pz = math.floor(p:getX()), math.floor(p:getY()), math.floor(p:getZ())
	for i = 10, 1, -1 do
		local sq = sqAt(px + math.floor(dx * i / 10 + 0.5), py + math.floor(dy * i / 10 + 0.5), pz)
		if sq and sq:getFloor() and try(function() return sq:isFree(false) end) then return sq end
	end
	return nil
end

function A.startTask(p, seq, goal, args)
	local cur = S.task
	if cur and cur.status == "running" and cur.goal == goal and cur.args[1] == args[1] and cur.args[2] == args[2] then
		cur.seq = seq -- same order again (e.g. a new speech line): keep going
		return
	end
	ISTimedActionQueue.clear(p)
	pcall(function() p:setRunning(false) end)
	pcall(function() p:setIsAiming(false) end)
	S.observing = false
	S.task = { seq = seq, goal = goal, args = args, status = "running", phase = "start", t0 = S.tick, msg = "" }
	if not A.tasks[goal] then fail(S.task, "unknown goal " .. tostring(goal)) end
end

function A.taskTick(p)
	local t = S.task
	if not t or t.status ~= "running" then return end
	local ok, e = pcall(A.tasks[t.goal], p, t)
	if not ok then fail(t, "error: " .. tostring(e)); S.err = tostring(e) end
end

A.tasks.wait = function(p, t)
	if t.phase == "start" then S.observing = true; t.phase = "watch"; H.action = "watching" end
	if S.tick - t.t0 > 900 then done(t, "watched for a while") end
end

A.tasks.rest = function(p, t)
	if t.phase == "start" then
		pcall(function() p:reportEvent("EventSitOnGround") end)
		t.phase = "rest"
		H.action = "resting"
	end
	if moodle(p, "ENDURANCE") == 0 and moodle(p, "PANIC") <= 1 and S.tick - t.t0 > 600 then done(t, "rested") end
	if S.tick - t.t0 > 5400 then done(t, "rested a long time") end
end

A.tasks.eat = function(p, t)
	if t.phase == "start" then
		local best, bv = nil, 0
		eachItem(p:getInventory(), function(it)
			local v = foodValue(it)
			if v and v > bv then best, bv = it, v end
		end)
		if not best then return fail(t, "no food I can eat as is") end
		ISInventoryPaneContextMenu.eatItem(best, 1, p:getPlayerNum())
		t.msg = "eating " .. best:getDisplayName()
		H.action = t.msg
		t.phase, t.t1, t.resume = "eat", S.tick, "start"
	elseif qlen(p) == 0 and S.tick - t.t1 > 30 then
		done(t)
	end
end

A.tasks.drink = function(p, t)
	if t.phase == "start" then
		local best = nil
		eachItem(p:getInventory(), function(it) if not best and waterIn(it) then best = it end end)
		if best then
			ISInventoryPaneContextMenu.onDrinkFluid(best, 1, p)
			t.msg = "drinking from " .. best:getDisplayName()
		else
			local src = nil
			for _, w in ipairs(A.scanWater(p, 15)) do if not w.tainted then src = w; break end end
			if not src then return fail(t, "no clean water nearby") end
			local obj = nil
			for _, o in ipairs(objList(sqAt(src.x, src.y, src.z))) do if waterAmount(o) > 0 then obj = o; break end end
			if not obj or not luautils.walkAdjObject(p, obj, true, true) then return fail(t, "can't reach the " .. src.name) end
			Q(ISTakeWaterAction:new(p, nil, obj, obj:isTaintedWater()))
			t.msg = "drinking at the " .. src.name
		end
		H.action = t.msg
		t.phase, t.t1, t.resume = "drink", S.tick, "start"
	elseif qlen(p) == 0 and S.tick - t.t1 > 30 then
		done(t)
	end
end

A.tasks.equip_weapon = function(p, t)
	if t.phase == "start" then
		local best = bestMelee(p)
		if not best or best == p:getPrimaryHandItem() then return done(t, "already holding my best weapon") end
		ISInventoryPaneContextMenu.equipWeapon(best, true, best:isTwoHandWeapon(), p:getPlayerNum())
		t.msg = "equipping " .. best:getDisplayName()
		H.action = t.msg
		t.phase, t.t1 = "equip", S.tick
	elseif qlen(p) == 0 and S.tick - t.t1 > 20 then
		done(t)
	end
end

A.tasks.bandage = function(p, t)
	if t.phase == "start" then
		local part = nil
		local parts = p:getBodyDamage():getBodyParts()
		for i = 0, parts:size() - 1 do
			local bp = parts:get(i)
			if not bp:bandaged() and (bp:bleeding() or bp:bitten() or bp:deepWounded() or try(function() return bp:isCut() end)) then
				part = bp
				if bp:bleeding() then break end
			end
		end
		if not part then return done(t, "nothing left to bandage") end
		local band = nil
		eachItem(p:getInventory(), function(it) if not band and medKind(it) == "bandage" then band = it end end)
		if not band then return fail(t, "no bandages") end
		if band:getContainer() ~= p:getInventory() then Q(ISInventoryTransferAction:new(p, band, band:getContainer(), p:getInventory())) end
		Q(ISApplyBandage:new(p, p, band, part, true))
		t.msg = "bandaging " .. (try(function() return BodyPartType.getDisplayName(part:getType()) end) or "a wound")
		H.action = t.msg
		t.phase, t.t1, t.resume = "wrap", S.tick, "start"
	elseif qlen(p) == 0 and S.tick - t.t1 > 30 then
		t.phase = "start" -- more wounds? the next start finishes when none are left
	end
end

-- shared by loot_here and loot_building once inside: walk to each unsearched container on this
-- floor, take food, water, medical supplies and better weapons, mark it searched
local function wanted(it, curBest)
	if instanceof(it, "Food") and not try(function() return it:isRotten() end) then return "food" end
	if waterIn(it) then return "water" end
	if medKind(it) then return "medical" end
	local ws = weaponScore(it)
	if ws and ws > curBest * 1.1 then return "weapon" end
	return nil
end

function A.lootStep(p, t)
	if t.phase == "next" then
		local info = A.buildingInfo(p, true)
		if not info then return fail(t, "not inside a building") end
		local best, bd = nil, 1e9
		for _, u in ipairs(info.unsearched) do
			local d = (u.sq:getX() - p:getX()) ^ 2 + (u.sq:getY() - p:getY()) ^ 2
			if d < bd then best, bd = u, d end
		end
		if not best then
			mem(p).looted[info.id] = true
			return done(t, t.found and ("searched this floor, found " .. t.found) or "searched this floor, nothing useful")
		end
		t.cur = best
		ISTimedActionQueue.clear(p)
		luautils.walkToContainer(best.c, p:getPlayerNum())
		t.phase, t.t1, t.resume = "walk", S.tick, "next"
		H.action = "searching a " .. tostring(best.c:getType())
	elseif t.phase == "walk" then
		if qlen(p) > 0 and S.tick - t.t1 < 900 then return end
		local c = t.cur
		mem(p).searched[c.key] = true
		if math.abs(c.sq:getX() - p:getX()) + math.abs(c.sq:getY() - p:getY()) > 3 then t.phase = "next"; return end
		local _, curBest = bestMelee(p)
		local budget = p:getMaxWeight() - p:getInventory():getCapacityWeight()
		local names, list = {}, {}
		t.taking = {}
		local items = c.c:getItems()
		for i = 0, items:size() - 1 do list[#list + 1] = items:get(i) end
		for _, it in ipairs(list) do
			if #names >= 8 then break end
			local kind = wanted(it, curBest)
			local wgt = try(function() return it:getUnequippedWeight() end) or 1
			if kind and wgt <= budget then
				Q(ISInventoryTransferAction:new(p, it, c.c, p:getInventory()))
				budget = budget - wgt
				names[#names + 1] = it:getDisplayName()
				t.taking[#t.taking + 1] = it
				if kind == "weapon" then curBest = weaponScore(it) end
			end
		end
		if #names > 0 then
			H.action = "taking " .. table.concat(names, ", ")
			t.phase, t.t1, t.resume = "take", S.tick, "next"
		else
			t.phase = "next"
		end
	elseif t.phase == "take" then
		if qlen(p) > 0 and S.tick - t.t1 <= 900 then return end
		-- report only what actually reached the bag: a transfer can be cut short (a zombie, manual control)
		local inv, took = p:getInventory(), {}
		for _, it in ipairs(t.taking or {}) do
			if try(function() return inv:contains(it) end) then took[#took + 1] = it:getDisplayName() end
		end
		if #took > 0 then
			local found = table.concat(took, ", ")
			t.found = t.found and (t.found .. ", " .. found) or found
			A.event("took " .. found)
		end
		t.taking, t.phase = nil, "next"
	end
end

A.tasks.loot_here = function(p, t)
	if t.phase == "start" then t.phase = "next" end
	A.lootStep(p, t)
end

local function buildingId(sq)
	local b = sq and sq:getBuilding()
	return b and bkey(b:getDef()) or nil
end

A.tasks.loot_building = function(p, t)
	local tx, ty, tz = tonumber(t.args[1]), tonumber(t.args[2]), tonumber(t.args[3]) or 0
	if not tx or not ty then return fail(t, "no target building") end
	if t.phase == "start" then
		pathTo(p, t, tx, ty, tz)
		t.phase, t.t1, t.resume = "travel", S.tick, "start"
		H.action = "heading to a building " .. dir8(tx - p:getX(), ty - p:getY())
	elseif t.phase == "travel" then
		local here, there = buildingId(p:getCurrentSquare()), buildingId(sqAt(tx, ty, tz))
		if here and there and here == there then
			ISTimedActionQueue.clear(p)
			t.phase, t.resume = "next", "next"
			return
		end
		if t.pathFailed then return fail(t, "no route to the building at " .. tx .. "," .. ty) end
		if qlen(p) == 0 and S.tick - t.t1 > 60 then
			t.retries = (t.retries or 0) + 1
			if t.retries > 2 then return fail(t, "couldn't get inside the building at " .. tx .. "," .. ty) end
			pathTo(p, t, tx, ty, tz)
			t.t1 = S.tick
		end
	else
		A.lootStep(p, t)
	end
end

A.tasks.explore = function(p, t)
	local dx, dy = tonumber(t.args[1]) or 0, tonumber(t.args[2]) or 0
	if t.phase == "start" then
		local sq = farthestFree(p, dx, dy)
		if not sq then return fail(t, "nowhere to walk " .. dir8(dx, dy)) end
		pathTo(p, t, sq:getX(), sq:getY(), sq:getZ())
		t.phase, t.t1, t.resume = "walk", S.tick, "start"
		H.action = "exploring " .. dir8(dx, dy)
	elseif t.phase == "walk" then
		if t.pathFailed then return fail(t, "no route " .. dir8(dx, dy)) end
		if qlen(p) == 0 and S.tick - t.t1 > 30 then done(t, "explored " .. dir8(dx, dy)) end
	end
end

A.tasks.fight = function(p, t)
	local vis = {}
	for _, e in ipairs(A.zombies(p, 15)) do if e.seen then vis[#vis + 1] = e end end
	if #vis == 0 then
		pcall(function() p:setIsAiming(false) end)
		return done(t, "no zombies in sight")
	end
	local close = 0
	for _, e in ipairs(vis) do if e.d < 2 then close = close + 1 end end
	if close >= 3 then return fail(t, "surrounded") end
	if stat(p, "ENDURANCE") < 0.25 then return fail(t, "too exhausted to fight") end
	local e = vis[1]
	local w = p:getPrimaryHandItem()
	local reach = (isMelee(w) and w:getMaxRange() or 0.9) + 0.3
	if e.d <= reach then
		if t.pathing then ISTimedActionQueue.clear(p); t.pathing = false end
		A.swing(p, e, w)
	else
		local now = getTimestampMs()
		if not t.pathing or now - (t.lastPath or 0) > 1500 then
			ISTimedActionQueue.clear(p)
			Q(ISPathFindAction:pathToLocationF(p, e.z:getX(), e.z:getY(), e.z:getZ()))
			t.pathing, t.lastPath = true, now
		end
	end
	H.action = "fighting (" .. #vis .. " in sight)"
end

A.tasks.flee = function(p, t)
	local zs = A.zombies(p, 25)
	if #zs == 0 or zs[1].d > 22 then
		pcall(function() p:setRunning(false) end)
		return done(t, "got away")
	end
	if t.phase == "start" or qlen(p) == 0 then
		t.legs = (t.legs or 0) + 1
		if t.legs > 6 then pcall(function() p:setRunning(false) end); return done(t, "ran a long way") end
		local sq = A.fleeSquare(p, zs, 14)
		if not sq then return fail(t, "nowhere to run") end
		ISTimedActionQueue.clear(p)
		pcall(function() p:setRunning(true) end)
		Q(ISPathFindAction:pathToLocationF(p, sq:getX() + 0.5, sq:getY() + 0.5, sq:getZ()))
		t.phase, t.resume = "run", "start"
	end
	H.action = "fleeing"
end

local function closeOpening(p, e)
	if not luautils.walkAdjWindowOrDoor(p, e.sq, e.o, true) then return false end
	if isDoor(e.o) then Q(ISOpenCloseDoor:new(p, e.o)) else Q(ISOpenCloseWindow:new(p, e.o)) end
	return true
end

A.tasks.secure_building = function(p, t)
	if qlen(p) > 0 and S.tick - (t.t1 or 0) < 600 then return end
	local info = A.buildingInfo(p, true)
	if not info then return fail(t, "not inside a building") end
	t.tries = t.tries or {}
	local pick = nil
	for _, e in ipairs(info.doorsOpen) do if (t.tries[e.o] or 0) < 2 then pick = e; break end end
	if not pick then for _, e in ipairs(info.windowsOpen) do if (t.tries[e.o] or 0) < 2 then pick = e; break end end end
	if not pick then return done(t, "closed every door and window I could") end
	t.tries[pick.o] = (t.tries[pick.o] or 0) + 1
	ISTimedActionQueue.clear(p)
	closeOpening(p, pick)
	t.t1, t.resume = S.tick, "start"
	H.action = "closing up the building"
end

A.tasks.hide = function(p, t)
	if t.phase == "start" then t.phase = "close" end
	if t.phase == "close" then
		if qlen(p) > 0 then return end
		local info = A.buildingInfo(p, true)
		local px, py = p:getX(), p:getY()
		t.tries = t.tries or {}
		if info then
			for _, e in ipairs(info.doorsOpen) do
				if (t.tries[e.o] or 0) < 2 and math.abs(e.sq:getX() - px) + math.abs(e.sq:getY() - py) < 10 then
					t.tries[e.o] = (t.tries[e.o] or 0) + 1
					closeOpening(p, e)
					return
				end
			end
		end
		pcall(function() p:setSneaking(true) end)
		t.phase, t.t1, t.resume = "still", S.tick, "close"
		H.action = "hiding"
	elseif t.phase == "still" and S.tick - t.t1 > 1800 then
		done(t, "stayed hidden for a while")
	end
end

---------------------------------------------------------------- intent from the bridge
function A.pollIntent(p)
	local line = readFirstLine("intent.txt")
	if not line or line == "" then return end
	local parts = split(tostring(line), "|")
	local seq = tonumber(parts[1])
	if not seq or seq <= S.lastSeq then return end
	S.lastSeq = seq
	local goal = parts[2] or "wait"
	local say, why, src = parts[6] or "", parts[7] or "", parts[8] or ""
	if say ~= "" then pcall(function() p:Say(say) end) end
	H.goal, H.source, H.lastIntent = goal, src, S.tick
	if why ~= "" then H.why = why end
	if not S.manual then A.startTask(p, seq, goal, { parts[3], parts[4], parts[5] }) end
end

---------------------------------------------------------------- body upkeep
function A.manageSpeed(p)
	if not S.autoSpeed then return end
	local cur = getSpeed()
	if not cur or cur == 0 then return end -- paused by you: leave it
	local want = (#A.zombies(p, 45) == 0 and not S.manual) and 2 or 1
	if cur ~= want then setSpeed(want) end
end

-- sneak at mid range to avoid drawing attention; never while fleeing or in melee
function A.manageSneak(p)
	local t = S.task
	if t and t.status == "running" and (t.goal == "flee" or t.goal == "hide") then return end
	local zs = A.zombies(p, 25)
	local nd = zs[1] and zs[1].d or 99
	pcall(function() p:setSneaking(nd >= 6 and nd < 25 and S.tick - S.reflexTick > 90) end)
end

---------------------------------------------------------------- main loop
-- run one part of the loop; an error is recorded (shown in the percept and console once) but
-- never stops the other parts
local function safe(name, fn, ...)
	local ok, r = pcall(fn, ...)
	if ok then return r end
	local msg = name .. ": " .. tostring(r)
	if msg ~= S.err then S.err = msg; print("[AIvZ] " .. msg) end
	return nil
end

function A.onTick()
	S.tick = S.tick + 1
	local p = P()
	if not p then return end
	if p:isDead() then
		H.action = "DEAD"
		if S.tick % (PERCEPT_EVERY * 4) == 0 then A.writePercept(p) end
		return
	end
	local px, py = p:getX(), p:getY()
	if S.lastPX and math.abs(px - S.lastPX) + math.abs(py - S.lastPY) > 0.3 then S.lastMove = S.tick end
	S.lastPX, S.lastPY = px, py

	if S.manual then
		if S.tick - S.lastMove > MANUAL_IDLE and S.tick - S.lastHumanKey > MANUAL_IDLE and qlen(p) == 0 then
			S.manual = false
			if S.task then S.task.phase = S.task.resume or "start" end
			pcall(function() p:Say("I've got it from here.") end)
		else
			H.action = "MANUAL: you're driving"
			if S.tick % PERCEPT_EVERY == 0 then safe("percept", A.writePercept, p) end
			if S.tick % INTENT_EVERY == 0 then safe("intent", A.pollIntent, p) end
			return
		end
	end

	local took = false
	if S.tick % REFLEX_EVERY == 0 then took = safe("reflex", A.reflex, p) end
	if not took and S.tick % TASK_EVERY == 0 then safe("task", A.taskTick, p) end
	if S.tick % 15 == 0 then safe("speed", A.manageSpeed, p) end
	if S.tick % 30 == 0 then safe("sneak", A.manageSneak, p) end
	if S.observing and not took and qlen(p) == 0 and S.tick % 30 == 0 then
		local rad = (math.floor(S.tick / 30) % 8) * (math.pi / 4)
		pcall(function() p:faceLocation(px + math.cos(rad) * 4, py + math.sin(rad) * 4) end)
	end
	if S.tick % PERCEPT_EVERY == 0 then safe("percept", A.writePercept, p) end
	if S.tick % INTENT_EVERY == 0 then safe("intent", A.pollIntent, p) end
end

local MOVE_KEYS = {
	[Keyboard.KEY_W] = true, [Keyboard.KEY_A] = true, [Keyboard.KEY_S] = true, [Keyboard.KEY_D] = true,
	[Keyboard.KEY_UP] = true, [Keyboard.KEY_DOWN] = true, [Keyboard.KEY_LEFT] = true, [Keyboard.KEY_RIGHT] = true,
	[Keyboard.KEY_E] = true, [Keyboard.KEY_SPACE] = true, [Keyboard.KEY_F] = true, [Keyboard.KEY_R] = true, [Keyboard.KEY_Q] = true,
}

function A.onKeyPressed(key)
	if key == KEY_HUD then H.visible = not H.visible; return end
	if key == KEY_SPEED then
		S.autoSpeed = not S.autoSpeed
		if not S.autoSpeed then setSpeed(1) end
		return
	end
	if MOVE_KEYS[key] then
		S.lastHumanKey = S.tick
		if not S.manual then
			S.manual = true
			local p = P()
			if p then ISTimedActionQueue.clear(p) end
		end
	end
end

---------------------------------------------------------------- HUD (layout from ClaudeSurvivor)
AIvZHUD = ISUIElement:derive("AIvZHUD")

function AIvZHUD:new()
	local sh = try(function() return getCore():getScreenHeight() end) or 1080
	local h = 196
	local o = ISUIElement:new(14, sh - h - 48, 400, h)
	setmetatable(o, self)
	self.__index = self
	return o
end

function AIvZHUD:wrap(text, n)
	local out, line = {}, ""
	for word in string.gmatch(tostring(text), "%S+") do
		if #line + #word + 1 > n then out[#out + 1] = line; line = word
		else line = (line == "") and word or (line .. " " .. word) end
	end
	if line ~= "" then out[#out + 1] = line end
	return out
end

function AIvZHUD:bar(label, v, x, y, bad)
	v = math.max(0, math.min(1, v or 0))
	self:drawText(label, x, y - 1, 0.6, 0.66, 0.72, 1, UIFont.Small)
	local bx, bw = x + 32, 46
	self:drawRect(bx, y + 2, bw, 8, 0.5, 0.15, 0.19, 0.23)
	local r, g, b = 0.5, 0.82, 0.72
	if bad(v) then r, g, b = 0.9, 0.33, 0.33 end
	self:drawRect(bx, y + 2, bw * v, 8, 0.95, r, g, b)
end

function AIvZHUD:render()
	if not H.visible then return end
	local p = P()
	if not p then return end
	local w, h = self.width, self.height
	self:drawRect(0, 0, w, h, 0.62, 0.04, 0.06, 0.08)
	self:drawRectBorder(0, 0, w, h, 0.7, 0.5, 0.82, 0.72)
	self:drawText("AI", 12, 8, 0.5, 0.82, 0.72, 1, UIFont.Medium)
	local status = S.manual and "MANUAL" or ((S.tick - S.reflexTick < 60) and ("REFLEX: " .. S.reflexAct) or
		((H.lastIntent and S.tick - H.lastIntent < 60) and "NEW PLAN" or (S.task and S.task.status or "waiting")))
	self:drawTextRight(status, w - 12, 11, 1, 0.83, 0.28, 1, UIFont.Small)
	local goal = H.goal ~= "" and (H.goal .. (H.source ~= "" and ("  (" .. H.source .. ")") or "")) or "no goal yet"
	self:drawText("GOAL: " .. goal, 12, 30, 1, 0.83, 0.28, 1, UIFont.Small)
	self:drawText("NOW: " .. tostring(H.action), 12, 46, 0.9, 0.95, 1, 1, UIFont.Small)
	local ty = 64
	for _, line in ipairs(self:wrap(H.why, 60)) do
		if ty > 94 then break end
		self:drawText(line, 12, ty, 0.74, 0.79, 0.85, 1, UIFont.Small)
		ty = ty + 15
	end
	local by = 118
	local hp = try(function() return p:getBodyDamage():getOverallBodyHealth() end) or 0
	self:bar("HP", hp / 100, 12, by, function(v) return v < 0.3 end)
	self:bar("HUN", stat(p, "HUNGER"), 104, by, function(v) return v > 0.7 end)
	self:bar("THI", stat(p, "THIRST"), 196, by, function(v) return v > 0.7 end)
	self:bar("END", stat(p, "ENDURANCE"), 288, by, function(v) return v < 0.3 end)
	local zs = A.zombies(p, 30)
	local near = 0
	for _, e in ipairs(zs) do if e.d <= 10 then near = near + 1 end end
	local zt = zs[1] and (math.floor(zs[1].d) .. " tiles " .. dir8(zs[1].dx, zs[1].dy)) or "none in 30 tiles"
	self:drawText("Zombies  " .. near .. " within 10 / " .. #zs .. " within 30  (nearest " .. zt .. ")", 12, by + 22, 0.9, 0.62, 0.62, 1, UIFont.Small)
	local wpn = p:getPrimaryHandItem()
	self:drawText("Kills " .. tostring(S.kills or 0) .. "  |  " .. (wpn and wpn:getDisplayName() or "no weapon"), 12, by + 38, 0.7, 0.86, 0.7, 1, UIFont.Small)
	local gt = getGameTime()
	self:drawTextRight(string.format("day %d  %02d:%02d   F7 hide  G speed%s", gt:getNightsSurvived() + 1, gt:getHour(), gt:getMinutes(),
		S.autoSpeed and "" or " (off)"), w - 12, by + 56, 0.55, 0.6, 0.66, 1, UIFont.Small)
end

function A.startHUD()
	if A.hudUI then pcall(function() A.hudUI:removeFromUIManager() end); A.hudUI = nil end
	local ui = AIvZHUD:new()
	ui:initialise()
	ui:addToUIManager()
	A.hudUI = ui
end

function A.onGameStart()
	A.startHUD()
	local p = P()
	if p and not S.announced then
		S.announced = true
		pcall(function() p:Say("AI online. Let's survive this.") end)
	end
end

-- called by the loader after a hot reload: rebuild the HUD so it uses the new code
function A.afterReload()
	if P() then A.startHUD() end
end
