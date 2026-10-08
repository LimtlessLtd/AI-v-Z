-- AIvZLoader.lua: event glue and hot reload for AIvZ.lua.
-- Adapted from ClaudeBotLoader (c) 2026 whatcheers, MIT licensed; see THIRD_PARTY_NOTICES.md.
--
-- The game loads AIvZ.lua (all the logic) before this file. Changing the contents of
-- ~/Zomboid/Lua/aivz/reload.txt re-runs AIvZ.lua from this mod's folder with reloadLuaFile (B42 has
-- no loadstring), so code changes apply without restarting the game. Only the mod's own file is
-- ever reloaded; there is deliberately no way to run arbitrary code from a file.
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

function L.path()
	local info = getModInfoByID("AIvZ")
	local v = info.getVersionDir and info:getVersionDir()
	if v then return v .. "/media/lua/client/AIvZ.lua" end
	return info:getDir() .. "/42/media/lua/client/AIvZ.lua"
end

function L.reload()
	local ok, e = pcall(function() reloadLuaFile(L.path()) end)
	if not ok then status("ERR reload: " .. tostring(e)); return false end
	status("OK reloaded v" .. tostring(AIvZ and AIvZ.VERSION) .. " at " .. tostring(getTimestampMs()) .. " from " .. L.path())
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

status(AIvZ and AIvZ.VERSION and ("OK v" .. AIvZ.VERSION) or "ERR AIvZ.lua did not load")
Events.OnTick.Add(function() call("onTick") end)
Events.OnRenderTick.Add(checkReload)
Events.OnKeyPressed.Add(function(key) call("onKeyPressed", key) end)
Events.OnGameStart.Add(function() call("onGameStart") end)
Events.OnZombieDead.Add(function(z) call("onZombieDead", z) end)
