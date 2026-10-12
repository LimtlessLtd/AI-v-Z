# One-click start: get the latest from GitHub, make sure the mod is linked, launch Project Zomboid (Steam)
# and run the self-taught agent. The agent takes over the character once a game is loaded.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/start.ps1 [-NoPull] [-NoGame] [-Policy net|random|probe]
param([switch]$NoPull, [switch]$NoGame, [string]$Policy = 'net')
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repo

if (-not $NoPull) {
  if (git status --porcelain) { Write-Warning "Local changes present; skipping git pull." }
  # the checked-out branch (phase4-learning while Phase 4 is in progress), not always main: pulling main left the
  # game on gym 0.4.9 while 15 PRs had been merged into phase4-learning (docs/BACKLOG.md N5)
  else { git pull --ff-only }
}

# idempotent: prints 'Already installed' when the junction exists
& (Join-Path $PSScriptRoot 'install-mod.ps1')

if (-not $NoGame) {
  if (-not (Get-Process -Name 'ProjectZomboid64' -ErrorAction SilentlyContinue)) {
    Write-Host "Launching Project Zomboid via Steam (app 108600)..."
    Start-Process 'steam://rungameid/108600'
  }
}

Write-Host "Starting the agent (Ctrl+C stops it; the rules baseline then takes the character back)."
Write-Host "In the game: Mods -> AI-v-Z enabled (once per save), then Load/start a singleplayer game. Hands off."
Write-Host "Dashboard: http://127.0.0.1:8799/"
python -m agent.run --policy $Policy
