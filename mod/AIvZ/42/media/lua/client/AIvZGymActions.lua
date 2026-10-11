-- AIvZGymActions.lua: further player-action families for the gym: exercise, moving items between
-- containers, and getting in and out of vehicles. Loaded after AIvZGym.lua; each family registers an
-- option hook (G.hooks) and an executor (G.X.<verb>).
--
-- STATUS: written from knowledge of the vanilla Lua (ISFitnessUI/ISFitnessAction, ISInventoryTransferAction,
-- ISVehicleMenu), NOT yet run against Build 42.21 -- the cloud environment has no game files. Every call
-- is guarded: a missing API fails the option with a visible reason ("unsupported: ...") rather than a
-- crash or a fake success. Outcomes are checked against what actually changed. Nothing here judges what
-- is worth doing. See docs/PHASE3_COVERAGE.md.

local A = AIvZ
local U = A.u
local G = A.gym
local try, Q, qlen, r1, r2, sqAt = U.try, U.Q, U.qlen, U.r1, U.r2, U.sqAt
local function tick() return A.s.tick end

-- Parameter windows: every choice stays reachable over time. A capped list starts at a different offset
-- each decision (page = decision id), so no subset is ever favoured.
local function window(n, cap, page)
	if n <= cap then return 1, n end
	local start = (page * cap) % n
	return start + 1, start + cap
end
local function eachWindowed(list, cap, page, fn)
	local a, b = window(#list, cap, page)
	for i = a, b do fn(list[((i - 1) % #list) + 1]) end
end

---------------------------------------------------------------- exercise
-- FitnessExercises.exercisesType: name -> { item = required item type, prop = ..., ... }. Availability follows
-- the fitness screen: required equipment carried, and not too tired (Endurance moodle).
local function fitnessTypes(p)
	local out = {}
	local ex = rawget(_G, "FitnessExercises")
	if not ex or not ex.exercisesType then return out end
	local have = {}
	U.eachItem(p:getInventory(), function(it) have[it:getType()] = true end)
	for name, d in pairs(ex.exercisesType) do
		local need = d.item
		if not need or have[need] then out[#out + 1] = { name = name, data = d, needs = need } end
	end
	table.sort(out, function(a, b) return a.name < b.name end)
	return out
end

local function endurance(p) return try(function() return p:getStats():getEndurance() end) end

G.hooks.exercise = function(p, list, add)
	if p:isAsleep() or try(function() return p:getVehicle() end) then return end
	local tired = (U.moodle(p, "ENDURANCE") or 0) >= 2
	for _, e in ipairs(fitnessTypes(p)) do
		add(list, "exercise", { type = e.name, equipment = e.needs, tired = tired, endurance = r2(endurance(p) or 0) },
			{ name = e.name, data = e.data })
	end
end

G.X.exercise = {
	start = function(p, t, o)
		if not (rawget(_G, "ISFitnessAction") and rawget(_G, "FitnessExercises")) then return U.fail(t, "unsupported: no fitness API") end
		t.end0, t.xp0 = endurance(p), try(function() return p:getXp():getXP(Perks.Fitness) end)
		-- the fitness screen queues one timed action per set; reps/regularity come from its defaults
		Q(ISFitnessAction:new(p, o.data.name, 25, o.data.data))
	end,
	step = G.queueStep(2400, function(p, t, o)
		local e = endurance(p)
		if t.end0 and e and e >= t.end0 - 0.001 then return "no effort spent (exercise didn't run)" end
	end),
}

---------------------------------------------------------------- stowing items (inventory organisation)
-- Move an item between containers the character can reach: worn/carried bags and searched containers
-- within 2.5 tiles. The destination is part of the option, as in the inventory screen's transfer.
local function destinations(p, ar)
	local out = {}
	local main = p:getInventory()
	out[#out + 1] = { c = main, name = "main inventory", kind = "inventory" }
	U.eachItem(main, function(it)
		if instanceof(it, "InventoryContainer") then
			out[#out + 1] = { c = it:getInventory(), name = it:getDisplayName(), kind = "bag", item = it }
		end
	end, 1)
	for _, c in ipairs(ar and ar.containers or {}) do
		if c.known and c.d < 2.5 then out[#out + 1] = { c = c.c, name = c.type, kind = "container" } end
	end
	return out
end

local function roomFor(dest, it)
	return try(function() return dest.c:hasRoomFor(getPlayer(), it) end) ~= false
end

G.hooks.stow = function(p, list, add)
	local ar = G.scanAround(p)
	local dests = destinations(p, ar)
	if #dests < 2 then return end
	local moves = {}
	local main = p:getInventory()
	local function consider(it, src)
		if it:isHidden() or G.worn(p, it) or it == p:getPrimaryHandItem() or it == p:getSecondaryHandItem() then return end
		for _, d in ipairs(dests) do
			if d.c ~= src and not (d.item and d.item == it) then moves[#moves + 1] = { it = it, src = src, dest = d } end
		end
	end
	for _, d in ipairs(dests) do
		U.eachItem(d.c, function(it) consider(it, it:getContainer()) end, 1)
	end
	local page = G.s.id or 0
	eachWindowed(moves, 12, page, function(m)
		local info = G.itemInfo(p, m.it)
		info.to, info.toKind = m.dest.name, m.dest.kind
		info.from = try(function() return m.src:getType() end) or "container"
		if roomFor(m.dest, m.it) then add(list, "stow", info, m) end
	end)
end

G.X.stow = {
	start = function(p, t, o)
		local d = o.data
		if not d.it:getContainer() then return U.fail(t, "item gone") end
		Q(ISInventoryTransferAction:new(p, d.it, d.it:getContainer(), d.dest.c))
	end,
	step = G.queueStep(900, function(p, t, o)
		if o.data.it:getContainer() ~= o.data.dest.c then return "didn't move" end
	end),
}

---------------------------------------------------------------- vehicles (enter, exit, engine)
local function nearVehicles(p, radius)
	local out, seen = {}, {}
	local px, py, pz = math.floor(p:getX()), math.floor(p:getY()), math.floor(p:getZ())
	for dx = -radius, radius do
		for dy = -radius, radius do
			local v = try(function() return sqAt(px + dx, py + dy, pz):getVehicleContainer() end)
			if v and not seen[v] then
				seen[v] = true
				out[#out + 1] = { v = v, d = math.sqrt((v:getX() - p:getX()) ^ 2 + (v:getY() - p:getY()) ^ 2) }
			end
		end
	end
	table.sort(out, function(a, b) return a.d < b.d end)
	return out
end

G.hooks.vehicle = function(p, list, add)
	local inside = try(function() return p:getVehicle() end)
	if inside then
		add(list, "exit_vehicle", { seat = try(function() return inside:getSeat(p) end) }, { v = inside })
		local on = try(function() return inside:isEngineRunning() end) == true
		if try(function() return inside:isDriver(p) end) then
			add(list, on and "engine_off" or "engine_on", { running = on }, { v = inside })
		end
		return
	end
	for i, e in ipairs(nearVehicles(p, 4)) do
		if i > 2 then break end
		local seats = try(function() return e.v:getMaxPassengers() end) or 0
		for s = 0, seats - 1 do
			if try(function() return e.v:isSeatInstalled(s) and not e.v:isSeatOccupied(s) end) then
				add(list, "enter_vehicle", { d = r1(e.d), seat = s, name = try(function() return e.v:getScript():getName() end) },
					{ v = e.v, seat = s })
			end
		end
	end
end

local function inVehicle(p) return try(function() return p:getVehicle() end) end
G.X.enter_vehicle = {
	start = function(p, t, o)
		if not (rawget(_G, "ISVehicleMenu") and ISVehicleMenu.onEnter) then return U.fail(t, "unsupported: no ISVehicleMenu.onEnter") end
		ISVehicleMenu.onEnter(p, o.data.v, o.data.seat)
	end,
	step = G.queueStep(900, function(p) if not inVehicle(p) then return "didn't get in" end end),
}
G.X.exit_vehicle = {
	start = function(p, t, o)
		if not (rawget(_G, "ISVehicleMenu") and ISVehicleMenu.onExit) then return U.fail(t, "unsupported: no ISVehicleMenu.onExit") end
		ISVehicleMenu.onExit(p, o.data.v:getSeat(p))
	end,
	step = G.queueStep(600, function(p) if inVehicle(p) then return "still inside" end end),
}
local function engine(on)
	return {
		start = function(p, t, o)
			local f = rawget(_G, "ISVehicleMenu") and (on and ISVehicleMenu.onStartEngine or ISVehicleMenu.onShutOff)
			if not f then return U.fail(t, "unsupported: no engine control in ISVehicleMenu") end
			f(p)
		end,
		step = G.queueStep(900, function(p, t, o)
			if (try(function() return o.data.v:isEngineRunning() end) == true) ~= on then
				return on and "engine didn't start" or "engine still running"
			end
		end),
	}
end
G.X.engine_on, G.X.engine_off = engine(true), engine(false)

---------------------------------------------------------------- character creation: choosing traits
-- Called from G.respawnStep on the profession/traits screen while the agent plays. Each call (every 1.5 s)
-- either asks the agent (obs.json {creation = true}), reads its answer from act.txt, or gives up waiting.
-- Options: add or remove one trait (with its point cost as the game states it), or finish (Next). The game
-- enforces its own point budget and exclusions: an add that doesn't take effect is reported as failed.
-- Written from the vanilla CharacterCreationProfession (listboxTrait, listboxTraitSelected, addTraitBtn,
-- removeTraitBtn); NOT yet run in Build 42.21. If the screen differs, it returns false and Next is pressed.
local MAX_STEPS, WAIT_MS = 12, 20000   -- at most 12 trait changes per character, then Next

local function traitLabel(item)
	local t = item and item.item
	return try(function() return t:getLabel() end) or tostring(item and item.text or "?"),
		try(function() return t:getCost() end), try(function() return t:getType() end)
end

local function selectedTraits(prof)
	local out = {}
	for _, it in ipairs(prof.listboxTraitSelected and prof.listboxTraitSelected.items or {}) do out[#out + 1] = (traitLabel(it)) end
	return out
end

local function creationOptions(prof)
	local opts = {}
	for i, it in ipairs(prof.listboxTrait and prof.listboxTrait.items or {}) do
		local label, cost, ty = traitLabel(it)
		opts[#opts + 1] = { verb = "add_trait", name = label, cost = cost, trait = ty and tostring(ty), idx = i }
	end
	for i, it in ipairs(prof.listboxTraitSelected and prof.listboxTraitSelected.items or {}) do
		local label, cost, ty = traitLabel(it)
		opts[#opts + 1] = { verb = "remove_trait", name = label, cost = cost, trait = ty and tostring(ty), idx = i }
	end
	opts[#opts + 1] = { verb = "finish_creation" }
	return opts
end

function G.creation(prof)
	if not (prof.listboxTrait and prof.listboxTraitSelected and prof.addTraitBtn and prof.removeTraitBtn) then return false end
	local c = G.s.creation
	if not c then c = { steps = 0 }; G.s.creation = c end
	if c.steps >= MAX_STEPS then return false end
	local now = getTimestampMs()
	if c.asked then
		local line = U.readFirstLine("act.txt")
		local parts = line and U.split(tostring(line), "|")
		if parts and tonumber(parts[1]) == c.id then
			local o = c.opts[(tonumber(parts[2]) or -1) + 1]
			c.asked = false
			if not o or o.verb == "finish_creation" then return false end
			c.steps = c.steps + 1
			local before = #selectedTraits(prof)
			local lb = o.verb == "add_trait" and prof.listboxTrait or prof.listboxTraitSelected
			lb.selected = o.idx
			prof:onOptionMouseDown(o.verb == "add_trait" and prof.addTraitBtn or prof.removeTraitBtn, 0, 0)
			local after = #selectedTraits(prof)
			local want = o.verb == "add_trait" and before + 1 or before - 1
			c.last = { verb = o.verb, name = o.name, status = after == want and "done" or "failed",
				msg = after == want and "" or "the game didn't accept it (points or exclusions)" }
			return true
		end
		if now - c.askedAt > WAIT_MS then return false end   -- the agent isn't answering: carry on with Next
		return true
	end
	G.s.id = G.s.id + 1
	c.id, c.opts, c.asked, c.askedAt = G.s.id, creationOptions(prof), true, now
	local out = {}
	for i, o in ipairs(c.opts) do out[i] = o end
	U.writeFile("obs.json", A.json({ id = c.id, reason = "creation", creation = true, gym = G.VERSION,
		obs = { selected = selectedTraits(prof) }, options = out, last = c.last }))
	return true
end
