-- AIvZLoader.lua: event glue and hot reload for AIvZ.lua.
-- Adapted from ClaudeBotLoader (c) 2026 whatcheers, MIT licensed; see THIRD_PARTY_NOTICES.md.
--
-- The game loads AIvZ.lua and AIvZGym.lua (all the logic) before this file. Changing the contents of
-- ~/Zomboid/Lua/aivz/reload.txt re-runs both from this mod's folder with reloadLuaFile (B42 has no
-- loadstring), so code changes apply without restarting the game. Only the mod's own files are ever
-- reloaded; there is deliberately no way to run arbitrary code from a file.
AIvZLoader = AIvZLoader or {}
local L = AIvZLoader

local function readAll(path)
	local r = getFileReader(path, false)
	if not r then return nil end
	local lines = {}
	local l = r:readLine()
	while l do lines[#lines + 1] = l; l = r:readLine() end
	r:close()
	return table.concat(lines, "\n")
end

local function status(msg)
	local w = getFileWriter("aivz/loader.txt", true, false)
	w:write(tostring(msg))
	w:close()
end

-- the mod's own files, and only those: AIvZ.lua (baseline, motor skills) and AIvZGym.lua (the agent's side)
L.FILES = { "AIvZ.lua", "AIvZGym.lua", "AIvZGymActions.lua", "AIvZGymHousehold.lua" }

function L.path(name)
	local info = getModInfoByID("AIvZ")
	local v = info.getVersionDir and info:getVersionDir()
	if v then return v .. "/media/lua/client/" .. name end
	return info:getDir() .. "/42/media/lua/client/" .. name
end

function L.reload()
	for _, name in ipairs(L.FILES) do
		local ok, e = pcall(function() reloadLuaFile(L.path(name)) end)
		if not ok then status("ERR reload " .. name .. ": " .. tostring(e)); return false end
	end
	status("OK reloaded v" .. tostring(AIvZ and AIvZ.VERSION) .. " (gym " .. tostring(AIvZ and AIvZ.gym and AIvZ.gym.VERSION)
		.. ") at " .. tostring(getTimestampMs()))
	if AIvZ and AIvZ.afterReload then pcall(AIvZ.afterReload) end
	return true
end

L.last = L.last or readAll("aivz/reload.txt")
L.lastCheck = 0

local function checkReload()
	local now = getTimestampMs()
	if now - L.lastCheck < 1000 then return end
	L.lastCheck = now
	local r = readAll("aivz/reload.txt")
	if r and r ~= L.last then
		L.last = r
		L.reload()
	end
end

local function call(name, ...)
	if AIvZ and AIvZ[name] then
		local ok, e = pcall(AIvZ[name], ...)
		if not ok then
			e = tostring(e)
			if e ~= L.lastErr then
				L.lastErr = e
				print("[AIvZ] " .. name .. ": " .. e)
				status("ERR " .. name .. ": " .. e)
			end
		end
	end
end

-- Back into the game after the game watcher (scripts/watch-game.ps1) restarted a hung or crashed game: it writes
-- the time in ms into aivz/resume.txt before it starts the game again. On the main menu, a time under
-- RESUME_FRESH_MS old is used once (the file is emptied), and the main menu's own Continue is pressed
-- (MainScreen.onMenuItemMouseDownMainMenu with the Continue label, OptionScreens/MainScreen.lua 1319-1347, which
-- waits out the menu's own delay and dialogs). A save whose character had died goes on to the new-character
-- screens, which the gym presses as after a death in the game (G.creationStep). Gives up after RESUME_GIVE_UP_MS.
-- Only a time is read from the file, never code; without the file the main menu is left to the owner.
local RESUME_FRESH_MS = 15 * 60 * 1000
local RESUME_WAIT_MS, RESUME_STEP_MS, RESUME_GIVE_UP_MS = 5000, 300, 180000
local resume = nil   -- { since, last, pressed }, while a resume is under way (pressed: when Continue went ahead)

local function resumeStep()
	local now = getTimestampMs()
	if L.resumeChecked == nil then
		L.resumeChecked = true
		local at = tonumber((readAll("aivz/resume.txt") or ""):match("%d+"))
		if at and now - at >= 0 and now - at < RESUME_FRESH_MS then
			local w = getFileWriter("aivz/resume.txt", true, false)
			w:write("")
			w:close()
			resume = { since = now, last = 0 }
			status("resuming the latest save after a restart by the game watcher")
		end
	end
	if not resume or now - resume.since < RESUME_WAIT_MS or now - resume.last < RESUME_STEP_MS then return end
	resume.last = now
	local ms = MainScreen.instance
	if not ms or ms.inGame or now - resume.since > RESUME_GIVE_UP_MS then
		if ms and not ms.inGame and not resume.pressed then status("resume gave up: Continue didn't go ahead in 3 minutes") end
		resume = nil
		return
	end
	local G = AIvZ and AIvZ.gym
	if G and G.creationStep and G.creationStep(MapSpawnSelect.instance, ms.charCreationProfession, ms.charCreationMain) then
		return
	end
	-- continueLatestSaveAux hides the bottom panel (Continue's parent) once it goes ahead (MainScreen.lua 1240);
	-- while the menu's delay or a dialog holds it back, the panel stays and the press is tried again
	local cont, panel = ms.latestSaveOption, ms.bottomPanel
	if not resume.pressed and cont and cont:isVisible() and panel and panel:isVisible() then
		MainScreen.onMenuItemMouseDownMainMenu(cont, 0, 0)
		resume.pressed = not panel:isVisible()
	end
end

-- the gym's version too, so loader.txt shows which code the game loaded (scripts/start.ps1 prints the repo's)
status(AIvZ and AIvZ.VERSION and ("OK v" .. AIvZ.VERSION .. " (gym " .. tostring(AIvZ.gym and AIvZ.gym.VERSION) .. ")")
	or "ERR AIvZ.lua did not load")
Events.OnTick.Add(function() call("onTick") end)
Events.OnRenderTick.Add(checkReload)
Events.OnKeyPressed.Add(function(key) call("onKeyPressed", key) end)
Events.OnGameStart.Add(function() call("onGameStart") end)
Events.OnZombieDead.Add(function(z) call("onZombieDead", z) end)
Events.OnFETick.Add(function()
	local ok, e = pcall(resumeStep)
	if not ok then resume = nil; status("ERR resume: " .. tostring(e)) end
end)
