# One-click start: get the latest from GitHub, make sure the mod is linked, launch Project Zomboid (Steam)
# and run the self-taught agent. The agent takes over the character once a game is loaded.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/start.ps1 [-NoPull] [-NoGame] [-Policy net|random|probe]
param([switch]$NoPull, [switch]$NoGame, [string]$Policy = 'net')
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repo
$running = [bool](Get-Process -Name 'ProjectZomboid64' -ErrorAction SilentlyContinue)

if (-not $NoPull) {
  if (git status --porcelain) { Write-Warning "Local changes present; skipping git pull." }
  else {
    # everything lands on main (the owner's rule, 2026-10-12)
    if ((git rev-parse --abbrev-ref HEAD) -ne 'main') { git switch main }
    $before = git rev-parse HEAD
    git pull --ff-only origin main
    # a game that is already running has the old Lua loaded: hot-reload it (a game started later loads the new)
    git diff --quiet $before HEAD -- mod
    if ($LASTEXITCODE -ne 0 -and $running) {
      Write-Host "The mod's Lua changed and the game is running: reloading it."
      & (Join-Path $PSScriptRoot 'reload-mod.ps1')
    }
  }
}

# idempotent: prints 'Already installed' when the junction exists
& (Join-Path $PSScriptRoot 'install-mod.ps1')

if (-not $NoGame -and -not $running) {
  Write-Host "Launching Project Zomboid via Steam (app 108600)..."
  Start-Process 'steam://rungameid/108600'
}

# which gym this checkout has; Zomboid\Lua\aivz\loader.txt says which one the game loaded
$gym = Select-String -Path (Join-Path $repo 'mod\AIvZ\42\media\lua\client\AIvZGym.lua') -Pattern '^G\.VERSION = "(.+)"' |
  Select-Object -First 1
if ($gym) { Write-Host "This checkout: gym $($gym.Matches[0].Groups[1].Value)" }

Write-Host "Starting the agent (Ctrl+C stops it; the rules baseline then takes the character back)."
Write-Host "In the game: Mods -> AI-v-Z enabled (once per save), then Load/start a singleplayer game. Hands off."
Write-Host "Dashboard: http://127.0.0.1:8799/"
python -m agent.run --policy $Policy
