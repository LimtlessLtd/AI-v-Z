-- Household supplies and real appliance settings for the gym. Installed 42.21 sources and prerequisites:
-- docs/HOUSEHOLD_ACTIONS.md. Only visible fixtures and the current character's open UI are inspected.
-- This exposes player choices; the network still chooses supplies, settings, transfers and waiting.
require "TimedActions/ISCleanBandage"
require "TimedActions/ISPlumbItem"
require "TimedActions/ISToggleClothingWasher"
require "TimedActions/ISToggleClothingDryer"
require "TimedActions/ISToggleComboWasherDryer"
require "TimedActions/ISSetComboWasherDryerMode"
require "TimedActions/ISOvenUITimedAction"
require "ISUI/Fireplace/ISOvenUI"
require "ISUI/Fireplace/ISMicrowaveUI"

local A, G = AIvZ, AIvZ.gym
local U = A.u
local Q, r1 = U.Q, U.r1
local function alive(o) return o and o:getSquare() and o:getObjectIndex() ~= -1 end
local function accessible(p, o)
	return alive(o) and p:getCurrentSquare() and not ISWorldObjectContextMenu.isSomethingTo(o, p:getPlayerNum())
		and getCore():getGameMode() ~= "LastStand"
end
local function name(o) return o:getTileName() or o:getObjectName() or "appliance" end
local function info(p, e)
	return { name = name(e.o), d = r1(e.d), dx = r1(e.sq:getX() + 0.5 - p:getX()),
		dy = r1(e.sq:getY() + 0.5 - p:getY()), what = e.kind }
end

-- Called by the existing perceivable-square scan. No new long-lived object cache: the list belongs to
-- that scan only. Plumbing's hidden supplier query is used later only as the vanilla menu prerequisite.
function G.householdScan(p, o, sq, d, out)
	local kind
	if instanceof(o, "IsoCombinationWasherDryer") then kind = "combo"
	elseif instanceof(o, "IsoClothingWasher") then kind = "washer"
	elseif instanceof(o, "IsoClothingDryer") then kind = "dryer" end
	if kind then out.household[#out.household + 1] = { o = o, sq = sq, d = d, kind = kind } end
	local props = o:getProperties()
	if (props and props:has(IsoFlagType.waterPiped)) or (o:hasModData() and o:getModData().canBeWaterPiped == true) then
		out.plumbing[#out.plumbing + 1] = { o = o, sq = sq, d = d, kind = "plumbing" }
	end
end

local function laundryCanToggle(p, o, kind)
	if not accessible(p, o) then return false end
	local c = o:getContainer()
	if not c or not c:isPowered() then return false end
	return not (kind == "washer" or (kind == "combo" and o:isModeWasher())) or o:getFluidAmount() > 0
end
local function notBroken(it) return not it:isBroken() end
local function wrench(p)
	local inv = p:getInventory()
	return inv:getFirstTypeEvalRecurse("PipeWrench", notBroken) or inv:getFirstTagEvalRecurse(ItemTag.PIPE_WRENCH, notBroken)
end
local function plumbable(o)
	if not alive(o) then return false end
	local sq, props = o:getSquare(), o:getProperties()
	local can = o:hasModData() and o:getModData().canBeWaterPiped == true
	local indoor = sq:isInARoom()
	local external = indoor and o:FindExternalWaterSource()
	if can and indoor and external then return true end
	if not props or not props:has(IsoFlagType.waterPiped) or o:getUsesExternalWaterSource() then return false end
	if indoor and external then return true end
	local sandbox = getSandboxOptions()
	local shutoff = sandbox:getOptionByName("WaterShutModifier")
	return sq:getRoom() ~= nil and can and shutoff ~= nil
		and getGameTime():getWorldAgeHours() / 24 + (sandbox:getTimeSinceApo() - 1) * 30 < shutoff:getValue()
end

-- Bandage recipe menus (ISWorldObjectContextMenu.lua:1829-2035). The local CleanBandages callbacks aren't
-- exposed globals; construct their exact transfer/walk/action sequence through queueActions instead.
local CLEAN = {
	{ "Base.BandageDirty", "Base.Clean Bandage" }, { "Base.DenimStripsDirty", "Base.Clean Denim Strips" },
	{ "Base.LeatherStripsDirty", "Base.Clean Leather Strips" }, { "Base.RippedSheetsDirty", "Base.Clean Rag" },
}
-- The default installed build defines craftRecipe CleanBandage (generated/recipes/recipes_medical.txt),
-- not the old spaced-name Recipe definitions used by the legacy sink menu. It consumes 0.5 L of carried
-- water. Keep the legacy adapter only when those recipes exist, and offer the current inventory-menu path.
local CLEAN_RESULTS = { ["Base.BandageDirty"] = "Base.Bandage", ["Base.DenimStripsDirty"] = "Base.DenimStrips",
	["Base.LeatherStripsDirty"] = "Base.LeatherStrips", ["Base.RippedSheetsDirty"] = "Base.RippedSheets" }
local function modernCleanReady(p, it, recipe)
	if not recipe or not p:getCurrentSquare() or not G.has(p, it)
		or not getPlayerInventory(p:getPlayerNum()) or not getPlayerLoot(p:getPlayerNum()) then return false end
	local logic = HandcraftLogic.new(p, nil, nil)
	logic:setIsoObject(logic:findCraftSurface(p, 2))
	logic:setContainers(ISInventoryPaneContextMenu.getContainers(p))
	logic:setRecipeFromContextClick(recipe, it)
	return logic:canPerformCurrentRecipe() and logic:getRecipeData():getAllInputItems():contains(it)
end
local function cleanSource(o)
	if not alive(o) or not o:hasWater() or o:getFluidAmount() < 1 then return false end
	if instanceof(o, "IsoClothingWasher") or instanceof(o, "IsoClothingDryer") or instanceof(o, "IsoCombinationWasherDryer") then return false end
	return not (o:isTaintedWater() and getSandboxOptions():getOptionByName("EnableTaintedWaterText"):getValue())
end
local function cleanDefs(p)
	local defs = {}
	for _, def in ipairs(CLEAN) do
		local recipe = getScriptManager():getRecipe(def[2])
		local n = p:getInventory():getCountTypeRecurse(def[1])
		if recipe and n > 0 then defs[#defs + 1] = { type = def[1], recipe = recipe, n = n } end
	end
	return defs
end
local function beginClean(p, t, o)
	local src = o.data.o
	if not cleanSource(src) or not p:getCurrentSquare() then return U.fail(t, "water unavailable") end
	local items, recipes = ArrayList.new(), {}
	local water = math.floor(src:getFluidAmount())
	for _, def in ipairs(o.data.defs) do
		local first = items:size()
		local n = o.info.how == "one" and math.min(1, water) or water - first
		if n <= 0 then break end
		p:getInventory():getSomeTypeRecurse(def.type, n, items)
		for i = first, items:size() - 1 do recipes[items:get(i)] = def.recipe end
	end
	if items:isEmpty() then return U.fail(t, "no dirty bandages") end
	t.items, t.results, t.before = {}, {}, {}
	for i = 0, items:size() - 1 do
		local it = items:get(i)
		t.items[#t.items + 1] = it
		local result = recipes[it]:getResult():getFullType()
		t.results[result] = (t.results[result] or 0) + 1
		t.before[result] = p:getInventory():getCountTypeRecurse(result)
	end
	ISInventoryPaneContextMenu.transferIfNeeded(p, items)
	if not luautils.walkAdj(p, src:getSquare(), true) then return U.fail(t, "couldn't reach water") end
	for i = 0, items:size() - 1 do
		local action = ISCleanBandage:new(p, items:get(i), src, recipes[items:get(i)])
		local nativeValid = action.isValid
		action.isValid = function(self) return alive(self.waterObject) and nativeValid(self) end
		Q(action)
	end
end
G.X.clean_bandage = {
	start = function(p, t, o)
		if o.data.craft then
			if not modernCleanReady(p, o.data.it, o.data.craft) then return U.fail(t, "cleaning supplies unavailable") end
			t.modern, t.result = true, CLEAN_RESULTS[o.data.it:getFullType()]
			if not t.result then return U.fail(t, "item no longer dirty") end
			t.resultBefore = p:getInventory():getCountTypeRecurse(t.result)
			ISInventoryPaneContextMenu.OnNewCraft(o.data.it, o.data.craft, p:getPlayerNum(), false)
		else
			ISTimedActionQueue.queueActions(p, beginClean, t, o)
		end
	end,
	step = G.queueStep(20000, function(p, t, o)
		if t.modern then
			if G.has(p, o.data.it) or p:getInventory():getCountTypeRecurse(t.result) <= t.resultBefore then return "bandage not cleaned" end
			return nil
		end
		if not t.items then return "didn't start cleaning" end
		for _, it in ipairs(t.items) do if G.has(p, it) then return "bandage still dirty" end end
		for result, n in pairs(t.results) do
			if p:getInventory():getCountTypeRecurse(result) < t.before[result] + n then return "clean bandages missing" end
		end
	end),
}

-- The menu's addGetUpOption wrapper, with expected disappearance/availability checked after getting up.
local function afterGetUp(p, t, o)
	local obj, pn = o.data.o, p:getPlayerNum()
	if not alive(obj) then return U.fail(t, "appliance gone") end
	if o.verb == "laundry" then
		if not laundryCanToggle(p, obj, o.data.kind) then return U.fail(t, "power or water unavailable") end
		t.was = obj:isActivated()
		if o.data.kind == "combo" then ISWorldObjectContextMenu.onToggleComboWasherDryer(p, obj)
		elseif o.data.kind == "washer" then ISWorldObjectContextMenu.onToggleClothingWasher(nil, obj, pn)
		else ISWorldObjectContextMenu.onToggleClothingDryer(nil, obj, pn) end
	elseif o.verb == "laundry_mode" then
		if not accessible(p, obj) or not obj:getContainer() then return U.fail(t, "appliance unavailable") end
		ISWorldObjectContextMenu.onSetComboWasherDryerMode(p, obj, o.data.mode)
	elseif o.verb == "plumb" then
		local tool = wrench(p)
		if not plumbable(obj) or not tool then return U.fail(t, "plumbing unavailable") end
		-- onPlumbItem's exact equip + action sequence, with a disappeared-target validity guard.
		ISWorldObjectContextMenu.equip(p, p:getPrimaryHandItem(), tool, true)
		local action = ISPlumbItem:new(p, obj, tool)
		local nativeValid = action.isValid
		action.isValid = function(self) return alive(self.itemToPipe) and nativeValid(self) end
		Q(action)
	elseif o.verb == "appliance_settings" then
		local c = obj:getContainer()
		if not accessible(p, obj) or not c or not c:isPowered() then return U.fail(t, "appliance unavailable") end
		if c:isMicrowave() then ISWorldObjectContextMenu.onMicrowaveSetting(nil, obj, pn)
		elseif c:isStove() then ISWorldObjectContextMenu.onStoveSetting(nil, obj, pn)
		else return U.fail(t, "no settings window") end
	end
end
local function menuStart(p, t, o)
	local up = ISWaitWhileGettingUp:new(p)
	up:setOnComplete(afterGetUp, p, t, o)
	Q(up)
end
G.X.laundry = { start = menuStart, step = G.queueStep(1200, function(p, t, o)
	if not alive(o.data.o) or t.was == nil or o.data.o:isActivated() == t.was then return "didn't switch" end
end) }
G.X.laundry_mode = { start = menuStart, step = G.queueStep(1200, function(p, t, o)
	if not alive(o.data.o) or o.data.o:isModeWasher() ~= (o.data.mode == "washer") then return "mode unchanged" end
end) }
G.X.plumb = { start = menuStart, step = G.queueStep(1200, function(p, t, o)
	if not alive(o.data.o) or not o.data.o:getUsesExternalWaterSource() then return "not connected" end
end) }

-- Inspect only the real visible panel, owned by this character, at the UI's normal range. Neither
-- appliance settings nor food's internal cooking/heat state are observations while a panel is closed.
local function panelValid(p, ui)
	return ui and ui.character == p and ui:isVisible() and alive(ui.oven) and ui.oven:getContainer()
		and ui.ok and ui.close and ui.tempKnob and ui.timerKnob
		and ui.tempKnob.values[ui.tempKnob.selected] and ui.timerKnob.values[ui.timerKnob.selected]
		and p:DistTo(ui.oven:getX(), ui.oven:getY()) <= 3
end
local function panels(p, includeCloseOnly)
	local out, pn = {}, p:getPlayerNum() + 1
	for _, class in ipairs({ ISOvenUI, ISMicrowaveUI }) do
		local ui = class.instance and class.instance[pn]
		if panelValid(p, ui) or (includeCloseOnly and ui and ui.character == p and ui:isVisible()
			and type(ui.close) == "table" and ui.close.internal == "CLOSE") then out[#out + 1] = ui end
	end
	return out
end
local function panelKind(ui)
	return ISMicrowaveUI.instance and ISMicrowaveUI.instance[ui.playerNum + 1] == ui and "microwave" or "oven"
end
function G.householdObservation(p)
	local out = { panels = {} }
	for _, ui in ipairs(panels(p)) do
		out.panels[#out.panels + 1] = { kind = panelKind(ui), temperature = ui.tempKnob:getValue(),
			minutes = ui.timerKnob:getValue(), active = ui.oven:Activated(), canToggle = ui.ok:isEnabled() == true }
	end
	return out
end
G.X.appliance_settings = { start = menuStart, step = G.queueStep(1200, function(p, t, o)
	for _, ui in ipairs(panels(p)) do if ui.oven == o.data.o then return nil end end
	return "settings did not open"
end) }
local function changeDial(p, t, o)
	local ui = o.data.ui
	if not panelValid(p, ui) then return U.fail(t, "settings closed") end
	local knob = o.verb == "appliance_temperature" and ui.tempKnob or ui.timerKnob
	local found = false
	for _, v in ipairs(knob.values) do if v.value == o.data.value then found = true end end
	if not found then return U.fail(t, "setting unavailable") end
	if knob:getValue() == o.data.value then return U.done(t, "unchanged") end
	knob:setKnobPosition(o.data.value)
	knob:playSwitchSound()
	ui:ChangeKnob()
end
G.X.appliance_temperature = { start = changeDial, step = G.queueStep(90, function(p, t, o)
	if not alive(o.data.o) or o.data.o:getMaxTemperature() ~= o.data.value then return "temperature unchanged" end
end) }
G.X.appliance_timer = { start = changeDial, step = G.queueStep(90, function(p, t, o)
	if not alive(o.data.o) or o.data.o:getTimer() ~= o.data.value * 60 then return "timer unchanged" end
end) }
G.X.appliance_toggle = { start = function(p, t, o)
	local ui = o.data.ui
	if not panelValid(p, ui) or not ui.ok:isEnabled() then return U.fail(t, "button disabled") end
	t.was = ui.oven:Activated()
	ui:onClick(ui.ok)
end, step = G.queueStep(300, function(p, t, o)
	if not alive(o.data.o) or o.data.o:Activated() == t.was then return "didn't switch" end
end) }
G.X.appliance_close = { start = function(p, t, o)
	if o.data.ui.character ~= p or not o.data.ui:isVisible() then return U.fail(t, "settings closed") end
	o.data.ui:onClick(o.data.ui.close)
end, step = G.queueStep(90, function(p, t, o) if o.data.ui:isVisible() then return "still open" end end) }

G.hooks.household = function(p, list, add)
	local ar = G.s.around or {}
	local cleanCraft = getScriptManager():getCraftRecipe("CleanBandage")
	if cleanCraft then
		for _, def in ipairs(CLEAN) do
			local n = p:getInventory():getCountTypeRecurse(def[1])
			if n > 0 then
				local items = p:getInventory():getSomeTypeRecurse(def[1], n)
				for i = 0, items:size() - 1 do
					local it = items:get(i)
					if modernCleanReady(p, it, cleanCraft) then
						add(list, "clean_bandage", { name = getText(cleanCraft:getTranslationName()), type = def[1],
							from = "inventory", how = "one" }, { it = it, craft = cleanCraft })
					end
				end
			end
		end
	end
	for _, e in ipairs(ar.stoves or {}) do
		local c = e.o:getContainer()
		if accessible(p, e.o) and c and c:isPowered() and (c:isStove() or c:isMicrowave()) then
			e.kind = c:isMicrowave() and "microwave" or "oven"
			add(list, "appliance_settings", info(p, e), { o = e.o })
		end
	end
	for _, e in ipairs(ar.household or {}) do
		if laundryCanToggle(p, e.o, e.kind) then
			local i = info(p, e); i.how = e.o:isActivated() and "off" or "on"
			add(list, "laundry", i, { o = e.o, kind = e.kind })
		end
		if e.kind == "combo" and accessible(p, e.o) and e.o:getContainer() then
			local i = info(p, e); i.how = e.o:isModeWasher() and "dryer" or "washer"
			add(list, "laundry_mode", i, { o = e.o, mode = i.how })
		end
	end
	if #(ar.plumbing or {}) > 0 and wrench(p) then
		for _, e in ipairs(ar.plumbing) do if plumbable(e.o) then add(list, "plumb", info(p, e), { o = e.o }) end end
	end
	if #(ar.water or {}) > 0 then
		local defs = cleanDefs(p)
		for _, e in ipairs(ar.water) do
			if #defs > 0 and cleanSource(e.src) then
				for _, def in ipairs(defs) do
					add(list, "clean_bandage", { name = def.recipe:getName(), type = def.type, from = e.w.name,
						d = e.w.d, how = "one" }, { o = e.src, defs = { def } })
					if def.n > 1 then
						add(list, "clean_bandage", { name = def.recipe:getName(), type = def.type, from = e.w.name,
							d = e.w.d, how = "all" }, { o = e.src, defs = { def } })
					end
				end
				if #defs > 1 then add(list, "clean_bandage", { name = "all bandages", from = e.w.name, d = e.w.d,
					how = "all" }, { o = e.src, defs = defs }) end
			end
		end
	end
	for _, ui in ipairs(panels(p, true)) do
		local kind = panelKind(ui)
		if panelValid(p, ui) then
			for _, v in ipairs(ui.tempKnob.values) do
				add(list, "appliance_temperature", { name = kind, what = "temperature dial", how = tostring(v.value) },
					{ o = ui.oven, ui = ui, value = v.value })
			end
			for _, v in ipairs(ui.timerKnob.values) do
				add(list, "appliance_timer", { name = kind, minutes = v.value, how = tostring(v.value) },
					{ o = ui.oven, ui = ui, value = v.value })
			end
			if ui.ok:isEnabled() then add(list, "appliance_toggle", { name = kind, how = ui.oven:Activated() and "off" or "on" }, { o = ui.oven, ui = ui }) end
		end
		add(list, "appliance_close", { name = kind }, { o = ui.oven, ui = ui })
	end
end

-- Stable action targets, independent of visible labels and distance. The references never reach IPC.
G.sameTargets = G.sameTargets or {}
for _, verb in ipairs({ "clean_bandage", "laundry", "laundry_mode", "plumb", "appliance_settings",
	"appliance_temperature", "appliance_timer", "appliance_toggle", "appliance_close" }) do
	G.sameTargets[verb] = function(a, b) return a.data.o == b.data.o and a.data.ui == b.data.ui end
end

G.sameTargets.drink_tap = function(a, b) return a.data.src == b.data.src end
G.sameTargets.clean_bandage = function(a, b)
	return a.data.o == b.data.o and a.data.it == b.data.it and a.data.craft == b.data.craft
end
G.sameTargets.fill = function(a, b)
	if a.data.src ~= b.data.src or a.data.it ~= b.data.it then return false end
	local aa, bb = a.data.all or {}, b.data.all or {}
	if #aa ~= #bb then return false end
	local selected = {}
	for _, it in ipairs(aa) do selected[it] = true end
	for _, it in ipairs(bb) do if not selected[it] then return false end end
	return true
end
