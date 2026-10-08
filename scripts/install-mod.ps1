# Links mod\AIvZ into your Project Zomboid mods folder as a directory junction (no admin rights needed),
# so the game always runs the code in this repo. After editing the Lua, run scripts\reload-mod.ps1 to
# hot-reload it in a running game. Uninstall: delete %USERPROFILE%\Zomboid\mods\AIvZ (only the link goes).
$ErrorActionPreference = 'Stop'
$src = (Resolve-Path (Join-Path $PSScriptRoot '..\mod\AIvZ')).Path
$zomboid = Join-Path $env:USERPROFILE 'Zomboid'
$dst = Join-Path $zomboid 'mods\AIvZ'

if (-not (Test-Path $zomboid)) { throw "No Zomboid folder at $zomboid. Launch Project Zomboid once first." }
New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
New-Item -ItemType Directory -Force (Join-Path $zomboid 'Lua\aivz') | Out-Null

if (Test-Path $dst) {
  $item = Get-Item $dst -Force
  if ($item.LinkType -eq 'Junction' -and @($item.Target)[0] -eq $src) { Write-Host "Already installed: $dst -> $src"; return }
  throw "$dst already exists and isn't a link to this repo. Move it away first."
}
New-Item -ItemType Junction -Path $dst -Target $src | Out-Null
Write-Host "Installed: $dst -> $src" -ForegroundColor Green
Write-Host "In Project Zomboid: Mods -> enable 'AI-v-Z', then load or start a singleplayer game."
