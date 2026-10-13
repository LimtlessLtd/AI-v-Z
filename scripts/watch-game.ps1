# The game watcher: keeps the game going for the agent, and keeps the evidence when it stops (backlog N16, N17).
# * GC logging for each game process it sees (logs\gc-<pid>.log, at most 5 files of 20 MB; logs older than 14 days
#   are deleted).
# * A hang: once the game's window has stopped responding for -HangSeconds, it saves three thread dumps 10 s apart,
#   with the native stacks of every thread (scripts\native_stacks.py: jcmd shows only the Java side, and the hangs
#   of 2026-10-13 were inside the game's audio library), and the heap, to logs\hang-<time>-<pid>.txt, once per hang.
# * Restarts, while the agent runs (python -m agent.run): a game that hasn't responded for -RestartMinutes is closed
#   (its native stacks saved once more first) and started again through Steam, and so is a game that ended without
#   being quit: a crash such as running out of memory, or a hung window someone closed. A quit leaves "GameThread
#   exited" at the end of the game's DebugLog with no uncaught exception before it, and is left alone. Before it
#   starts the game it writes the time to Zomboid\Lua\aivz\resume.txt, and the mod presses the main menu's own
#   Continue (AIvZLoader.lua). At most -MaxRestarts an hour. Each restart goes in logs\watcher.log.
#   -RestartMinutes 0 turns restarts off.
# The game's own jre64 has no jcmd: the Java dumps and GC logs need a JDK 25's (-Jcmd, $env:AIVZ_JCMD, or the newest
# E:\Tools\*jdk25*\bin\jcmd.exe). Without one it still restarts the game and saves the native stacks.
# scripts\start.ps1 starts it in a minimized window. Close that window to stop it.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/watch-game.ps1 [-Jcmd <path>] [-HangSeconds 60]
#          [-RestartMinutes 5] [-MaxRestarts 4] [-DumpNow]
#   -DumpNow  save the dumps of the running game once, now, and exit (a hang the watcher wasn't running for)
param([string]$Jcmd = $env:AIVZ_JCMD, [int]$HangSeconds = 60, [int]$RestartMinutes = 5, [int]$MaxRestarts = 4,
  [switch]$DumpNow)
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$logs = Join-Path $repo 'logs'
$aivz = Join-Path $env:USERPROFILE 'Zomboid\Lua\aivz'
$gameLogs = Join-Path $env:USERPROFILE 'Zomboid\Logs'
$stacks = Join-Path $PSScriptRoot 'native_stacks.py'
$python = Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
if (-not $Jcmd) {
  $Jcmd = Get-ChildItem 'E:\Tools\*jdk25*\bin\jcmd.exe' -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if ($Jcmd -and -not (Test-Path $Jcmd)) { $Jcmd = $null }
if (-not $Jcmd) { Write-Warning "No jcmd found (install a JDK 25, or pass -Jcmd): no GC logs or Java thread dumps." }
New-Item -ItemType Directory -Force $logs | Out-Null

function Stamp { Get-Date -Format 'HH:mm:ss' }
function Log($msg) {
  Write-Host "$(Stamp) $msg"
  Add-Content (Join-Path $logs 'watcher.log') "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
}
function Save-Native($id, $out, $label) {
  if (-not $python) { return }
  Add-Content $out "===== native stacks ($label) at $(Get-Date -Format 'HH:mm:ss.fff') ====="
  & $python $stacks $id 2>&1 | Add-Content $out
}
# three thread dumps 10 s apart (is the main thread moving?), each with the native stacks, and the heap
function Save-Dumps($id) {
  $out = Join-Path $logs ('hang-{0}-{1}.txt' -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $id)
  Write-Host "$(Stamp) saving $out"
  foreach ($n in 1..3) {
    Add-Content $out "===== thread dump $n of 3 at $(Get-Date -Format 'HH:mm:ss.fff') ====="
    if ($Jcmd) { & $Jcmd $id Thread.print -l | Add-Content $out }
    Save-Native $id $out "$n of 3"
    if ($n -lt 3) { Start-Sleep -Seconds 10 }
  }
  if ($Jcmd) {
    Add-Content $out "===== heap at $(Get-Date -Format 'HH:mm:ss.fff') ====="
    & $Jcmd $id GC.heap_info | Add-Content $out
  }
  Write-Host "$(Stamp) saved."
  return $out
}

if ($DumpNow) {
  $p = Get-Process -Name 'ProjectZomboid64' -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $p) { Write-Warning "Project Zomboid isn't running."; exit 1 }
  Save-Dumps $p.Id | Out-Null
  exit 0
}

function Agent-Running {
  [bool](Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'agent\.run' })
}
# how the game's last session ended: 'quit', or 'crash' (an uncaught exception, or a log that just stops)
function Last-Ending {
  $f = Get-ChildItem $gameLogs -Filter '*DebugLog*.txt' -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $f) { return 'crash' }
  $tail = @(Get-Content $f.FullName -Tail 200)
  if ($tail -match 'uncaughtException|OutOfMemoryError') { return 'crash' }
  if ($tail[-5..-1] -match 'GameThread exited') { return 'quit' }
  return 'crash'
}
$restarts = New-Object System.Collections.Generic.List[datetime]
function Restart-Game($why) {
  $recent = @($restarts | Where-Object { $_ -gt (Get-Date).AddHours(-1) })
  if ($recent.Count -ge $MaxRestarts) {
    Log "not restarting the game ($why): it was restarted $MaxRestarts times in the last hour"
    return $false
  }
  $restarts.Add((Get-Date))
  # the mod presses Continue on the main menu when this time is under 15 minutes old (AIvZLoader.lua)
  New-Item -ItemType Directory -Force $aivz | Out-Null
  Set-Content -Path (Join-Path $aivz 'resume.txt') -Value ([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()) -Encoding ascii
  Log "restarting the game: $why"
  Start-Process 'steam://rungameid/108600'
  return $true
}

Get-ChildItem $logs -Filter 'gc-*.log*' | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-14) } | Remove-Item
$host.UI.RawUI.WindowTitle = 'AI-v-Z game watcher'
$restartNote = if ($RestartMinutes -gt 0) { "restarts it after $RestartMinutes minutes hung or a crash, while the agent runs" } else { "no restarts" }
Write-Host "Watching Project Zomboid ($restartNote). Close this window to stop."

$logging = @{}        # game process id -> GC logging switched on
$known = $null        # the game process being watched
$stuckSince = $null   # when its window stopped responding
$dumped = $null       # the hang already saved, and where
$hangFile = $null
$startedAt = $null    # when the watcher last started the game
while ($true) {
  $p = Get-Process -Name 'ProjectZomboid64' -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $p) {
    $stuckSince = $null
    if ($known) {
      $ending = Last-Ending
      Log "game $known ended ($ending)"
      $known = $null
      if ($ending -eq 'crash' -and $RestartMinutes -gt 0 -and (Agent-Running)) {
        if (Restart-Game "it ended without being quit") { $startedAt = Get-Date }
      }
    } elseif ($startedAt -and ((Get-Date) - $startedAt).TotalMinutes -gt 5) {
      Log "the game didn't start in the 5 minutes after the restart (is Steam running?)"
      $startedAt = $null
    }
    Start-Sleep -Seconds 10
    continue
  }
  $id = $p.Id
  if ($known -ne $id) { $known = $id; $startedAt = $null; $stuckSince = $null }
  # the JVM needs a moment after Steam starts the game before it takes commands
  $age = ((Get-Date) - $p.StartTime).TotalSeconds
  if ($Jcmd -and -not $logging[$id] -and $age -gt 30) {
    $gc = Join-Path $logs "gc-$id.log"
    & $Jcmd $id VM.log output="file=$gc" output_options="filecount=5,filesize=20m" what="gc*=info" decorators="time,uptime" | Out-Null
    if ($LASTEXITCODE -eq 0) { $logging[$id] = $true; Write-Host "$(Stamp) game ${id}: GC log in $gc" }
  }
  if ($p.Responding) { $stuckSince = $null }
  elseif (-not $stuckSince) { $stuckSince = Get-Date }
  else {
    $for = ((Get-Date) - $stuckSince).TotalSeconds
    if ($for -ge $HangSeconds -and $dumped -ne "$id/$stuckSince") {
      $dumped = "$id/$stuckSince"
      Log "game $id has not responded since $($stuckSince.ToString('HH:mm:ss'))"
      $hangFile = Save-Dumps $id
    }
    if ($RestartMinutes -gt 0 -and $for -ge $RestartMinutes * 60 -and (Agent-Running)) {
      if ($hangFile -and $dumped -eq "$id/$stuckSince") { Save-Native $id $hangFile "before closing the game" }
      Log "game $id has not responded for $([int]($for / 60)) minutes: closing it"
      Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
      $p.WaitForExit(30000) | Out-Null
      $known = $null
      $stuckSince = $null
      if (Restart-Game "it hung") { $startedAt = Get-Date }
    }
  }
  Start-Sleep -Seconds 10
}
