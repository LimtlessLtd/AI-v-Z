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
	local inv = p:getInventory()
	for name, d in pairs(ex.exercisesType) do
		-- d.item is a full type ("Base.BarBell"); the fitness screen tests it with contains(type, true)
		local need = d.item
		if not need or try(function() return inv:contains(need, true) end) then out[#out + 1] = { name = name, data = d, needs = need } end
	end
	table.sort(out, function(a, b) return a.name < b.name end)
	return out
end

-- Build 42 reads stats through CharacterStat (Stats:getEndurance() no longer exists: it logged an error per call)
local function endurance(p) return U.stat(p, "ENDURANCE") end

-- ISFitnessUI:updateButtons: the screen disables Start with these; the same limits apply here
-- (ISFitnessUI.enduranceLevelThreshold = 2, heavy load <= 2, pain <= 3, not sitting, not climbing).
local function fitnessBlocked(p)
	if p:isAsleep() or try(function() return p:getVehicle() end) then return "in a vehicle or asleep" end
	if (U.moodle(p, "ENDURANCE") or 0) > 2 then return "too tired" end
	if (U.moodle(p, "HEAVY_LOAD") or 0) > 2 then return "load too heavy" end
	if (U.moodle(p, "PAIN") or 0) > 3 then return "in too much pain" end
	if try(function() return p:isSitOnGround() end) or try(function() return p:isSittingOnFurniture() end) then return "sitting" end
	if try(function() return p:isClimbing() end) then return "climbing" end
end

-- the screen offers 10..60 game minutes in steps of 10 (ISFitnessUI:onClickTime); duration is an option parameter
local EXERCISE_MINUTES = { 10, 20, 30, 40, 50, 60 }

G.hooks.exercise = function(p, list, add)
	local why = fitnessBlocked(p)
	for _, e in ipairs(fitnessTypes(p)) do
		for _, m in ipairs(EXERCISE_MINUTES) do
			add(list, "exercise", { type = e.name, minutes = m, equipment = e.needs, unavailable = why, endurance = r2(endurance(p) or 0) },
				{ name = e.name, data = e.data, minutes = m, blocked = why })
		end
	end
end

G.X.exercise = {
	start = function(p, t, o)
		if not (rawget(_G, "ISFitnessAction") and rawget(_G, "FitnessExercises")) then return U.fail(t, "unsupported: no fitness API") end
		-- the option's own fields are in o.data (o is { verb, info, data })
		if o.data.blocked then return U.fail(t, "not allowed now: " .. o.data.blocked) end
		t.end0 = endurance(p)
		local fit = try(function() return p:getFitness() end)
		if not fit then return U.fail(t, "unsupported: no Fitness object") end
		pcall(function() fit:init() end) -- the screen does this when it opens
		-- Constructor (ISFitnessAction.lua:204): (character, exercise, timeToExe, exeData, exeDataType). The fifth
		-- argument is what sets Fitness' current exercise; omitting it left it nil.
		local ok, act = pcall(function() return ISFitnessAction:new(p, o.data.name, o.data.minutes, o.data.data, o.data.data.type) end)
		if not ok or not act then return U.fail(t, "unsupported: ISFitnessAction:new failed") end
		-- equipment hand-off (ISFitnessUI:equipItems) is NOT done here yet: exercises with a prop item need it in hand
		Q(act)
	end,
	step = G.queueStep(2400, function(p, t, o)
		local e = endurance(p)
		if t.end0 and e and e >= t.end0 - 0.001 then return "no effort spent (exercise didn't run)" end
	end),
}

-------------------------------------------------------------- stowing items (inventory organisation)
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
			-- squares at the edge may not be loaded; test for nil rather than let try() catch it (Kahlua still
			-- logs every caught exception with a stack dump: twice in the 2026-10-11 console log)
			local sq = sqAt(px + dx, py + dy, pz)
			local v = sq and try(function() return sq:getVehicleContainer() end)
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
local MAX_STEPS, WAIT_MS = 12, 20000   -- after 12 trait changes in the spend stage, finishing is the only option
local MAX_FAILS = 6                    -- repay stage: this many refused/unavailable picks, then traits are taken off

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

-- Points left to spend, as the game counts them. The game's own number when the screen exposes one
-- (pointToSpend); otherwise a conservative stand-in: 0 if the chosen traits cost nothing net, else negative,
-- so an unknown balance can never let a build that may be overdrawn start. A character may start only
-- with 0 or more points left; below 0 the game's rules say it can't.
function G.creationPoints(prof)
	local p = rawget(prof, "pointToSpend") or try(function() return prof.pointToSpend end)
	if type(p) == "number" then return p, true end
	local net = 0
	for _, it in ipairs(prof.listboxTraitSelected and prof.listboxTraitSelected.items or {}) do
		net = net + (select(2, traitLabel(it)) or 0)
	end
	return (net <= 0) and 0 or -net, false
end

-- The trait choice runs in three stages, so the screen can never be a dead end:
--   spend  (never overdrawn so far): add traits that cost points, or finish (finish is allowed at 0 or more)
--   repay  (points went below 0):    add only traits that give points back, until points are 0 or more
--   done   (repaid):                 the only option is to start the game
-- No trait is ever removed by the agent; `c.repaying` remembers that points went negative.
local function creationOptions(prof, points, c)
	local opts = {}
	local stage = c.repaying and (points >= 0 and "done" or "repay") or "spend"
	if stage ~= "done" then
		for _, key in ipairs({ "listboxTrait", "listboxBadTrait" }) do
			for i, it in ipairs(prof[key] and prof[key].items or {}) do
				local label, cost, ty = traitLabel(it)
				cost = cost or 0
				if (stage == "spend" and cost >= 0 and not (c.steps >= MAX_STEPS)) or (stage == "repay" and cost < 0) then
					opts[#opts + 1] = { verb = "add_trait", name = label, cost = cost, trait = ty and tostring(ty), idx = i, list = key }
				end
			end
		end
	end
	if points >= 0 then opts[#opts + 1] = { verb = "finish_creation" } end
	return opts, stage
end

local function click(prof, o)
	local lb = o.verb == "add_trait" and prof[o.list or "listboxTrait"] or prof.listboxTraitSelected
	lb.selected = o.idx
	local btn = o.verb == "add_trait" and ((o.list == "listboxBadTrait" and prof.addBadTraitBtn) or prof.addTraitBtn)
		or prof.removeTraitBtn
	prof:onOptionMouseDown(btn, 0, 0)
end

-- Used when the agent isn't answering or isn't playing, just before Next is pressed for it: if the traits
-- overdraw the points, take them off again (most expensive first) so the game's rule is never broken.
function G.creationRepair(prof)
	if not (prof.listboxTraitSelected and prof.removeTraitBtn) then return end
	for _ = 1, 40 do
		if G.creationPoints(prof) >= 0 then return end
		local best, bi = nil, nil
		for i, it in ipairs(prof.listboxTraitSelected.items or {}) do
			local c = select(2, traitLabel(it)) or 0
			if not best or c > best then best, bi = c, i end
		end
		if not bi then return end
		click(prof, { verb = "remove_trait", idx = bi })
	end
end

function G.creation(prof)
	if not (prof.listboxTrait and prof.listboxTraitSelected and prof.addTraitBtn and prof.removeTraitBtn) then return false end
	local c = G.s.creation
	if not c then c = { steps = 0 }; G.s.creation = c end
	local now = getTimestampMs()
	if c.asked then
		local line = U.readFirstLine("act.txt")
		local parts = line and U.split(tostring(line), "|")
		if parts and tonumber(parts[1]) == c.id then
			local o = c.opts[(tonumber(parts[2]) or -1) + 1]
			c.asked = false
			if not o then return true end   -- not a valid choice: ask again
			if o.verb == "finish_creation" then
				if G.creationPoints(prof) < 0 then return true end   -- never start overdrawn
				return false
			end
			c.steps = c.steps + 1
			local before = #selectedTraits(prof)
			click(prof, o)
			local after = #selectedTraits(prof)
			local ok = after == before + 1
			if not ok then c.fails = (c.fails or 0) + 1 end
			if G.creationPoints(prof) < 0 then c.repaying = true end
			c.last = { verb = o.verb, name = o.name, status = ok and "done" or "failed",
				msg = ok and "" or "the game didn't accept it (points or exclusions)" }
			return true
		end
		if now - c.askedAt > WAIT_MS then G.creationRepair(prof); return false end   -- no answer: carry on with Next
		return true
	end
	local points, known = G.creationPoints(prof)
	if points < 0 then c.repaying = true end
	local opts, stage = creationOptions(prof, points, c)
	-- a repay stage with nothing to pick, or that keeps being refused, would be a dead end: undo and go on
	if stage == "repay" and (#opts == 0 or (c.fails or 0) >= MAX_FAILS) then G.creationRepair(prof); return false end
	G.s.id = G.s.id + 1
	c.id, c.opts, c.asked, c.askedAt = G.s.id, opts, true, now
	local out = {}
	for i, o in ipairs(c.opts) do out[i] = o end
	U.writeFile("obs.json", A.json({ id = c.id, reason = "creation", creation = true, gym = G.VERSION,
		obs = { selected = selectedTraits(prof), points = points, points_from_game = known, may_finish = points >= 0, stage = stage,
			bad_list = prof.listboxBadTrait ~= nil, bad_button = prof.addBadTraitBtn ~= nil },
		options = out, last = c.last }))
	return true
end
