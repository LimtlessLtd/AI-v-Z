# Hot-reloads the mod's Lua (AIvZ.lua, AIvZGym.lua, AIvZGymActions.lua) in a running game: the mod's loader
# watches this file and re-runs those files (from the mod folder only) whenever its contents change.
$f = Join-Path $env:USERPROFILE 'Zomboid\Lua\aivz\reload.txt'
New-Item -ItemType Directory -Force (Split-Path $f) | Out-Null
Set-Content -Path $f -Value (Get-Date -Format o) -Encoding ascii
$status = Join-Path $env:USERPROFILE 'Zomboid\Lua\aivz\loader.txt'
Start-Sleep -Seconds 2
if (Test-Path $status) { Write-Host "loader: $(Get-Content $status -Raw)" } else { Write-Host "loader status not found (is the game running with the mod?)" }
