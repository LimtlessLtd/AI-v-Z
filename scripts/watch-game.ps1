# Keeps the Java side's evidence for backlog N16 (the heap) and N17 (the game hanging right after a respawn).
# For each game process it sees, it turns on GC logging (logs\gc-<pid>.log, at most 5 files of 20 MB; logs older
# than 14 days are deleted). When the game's window has stopped responding for -HangSeconds, it saves three thread
# dumps 10 s apart and the heap to logs\hang-<time>-<pid>.txt, once per hang. It only reads (jcmd's Thread.print
# and GC.heap_info) and switches the logging on; it never stops or changes the game. The game's own jre64 has no
# jcmd: it needs a JDK 25's (-Jcmd, $env:AIVZ_JCMD, or the newest E:\Tools\*jdk25*\bin\jcmd.exe).
# scripts\start.ps1 starts it in a minimized window. Close that window to stop it.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/watch-game.ps1 [-Jcmd <path>] [-HangSeconds 60] [-DumpNow]
#   -DumpNow  save the dumps of the running game once, now, and exit (a hang the watcher wasn't running for)
param([string]$Jcmd = $env:AIVZ_JCMD, [int]$HangSeconds = 60, [switch]$DumpNow)
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$logs = Join-Path $repo 'logs'
if (-not $Jcmd) {
  $Jcmd = Get-ChildItem 'E:\Tools\*jdk25*\bin\jcmd.exe' -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $Jcmd -or -not (Test-Path $Jcmd)) {
  Write-Warning "No jcmd found (install a JDK 25, or pass -Jcmd): not watching."
  exit 1
}
New-Item -ItemType Directory -Force $logs | Out-Null

function Stamp { Get-Date -Format 'HH:mm:ss' }
# three thread dumps 10 s apart (is the main thread moving?) and the heap
function Save-Dumps($id) {
  $out = Join-Path $logs ('hang-{0}-{1}.txt' -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $id)
  Write-Host "$(Stamp) saving $out"
  foreach ($n in 1..3) {
    Add-Content $out "===== thread dump $n of 3 at $(Get-Date -Format 'HH:mm:ss.fff') ====="
    & $Jcmd $id Thread.print -l | Add-Content $out
    if ($n -lt 3) { Start-Sleep -Seconds 10 }
  }
  Add-Content $out "===== heap at $(Get-Date -Format 'HH:mm:ss.fff') ====="
  & $Jcmd $id GC.heap_info | Add-Content $out
  Write-Host "$(Stamp) saved. The game is left as it is."
}

if ($DumpNow) {
  $p = Get-Process -Name 'ProjectZomboid64' -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $p) { Write-Warning "Project Zomboid isn't running."; exit 1 }
  Save-Dumps $p.Id
  exit 0
}

Get-ChildItem $logs -Filter 'gc-*.log*' | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-14) } | Remove-Item
$host.UI.RawUI.WindowTitle = 'AI-v-Z game watcher'
Write-Host "Watching Project Zomboid with $Jcmd. Close this window to stop."

$logging = @{}        # game process id -> GC logging switched on
$stuckSince = $null   # when the window stopped responding
$dumped = $null       # the hang already saved
while ($true) {
  $p = Get-Process -Name 'ProjectZomboid64' -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $p) { $stuckSince = $null; Start-Sleep -Seconds 10; continue }
  $id = $p.Id
  # the JVM needs a moment after Steam starts the game before it takes commands
  if (-not $logging[$id] -and ((Get-Date) - $p.StartTime).TotalSeconds -gt 30) {
    $gc = Join-Path $logs "gc-$id.log"
    & $Jcmd $id VM.log output="file=$gc" output_options="filecount=5,filesize=20m" what="gc*=info" decorators="time,uptime" | Out-Null
    if ($LASTEXITCODE -eq 0) { $logging[$id] = $true; Write-Host "$(Stamp) game ${id}: GC log in $gc" }
  }
  if ($p.Responding) { $stuckSince = $null }
  elseif (-not $stuckSince) { $stuckSince = Get-Date }
  elseif (((Get-Date) - $stuckSince).TotalSeconds -ge $HangSeconds -and $dumped -ne "$id/$stuckSince") {
    $dumped = "$id/$stuckSince"
    Write-Host "$(Stamp) game ${id} has not responded since $($stuckSince.ToString('HH:mm:ss'))"
    Save-Dumps $id
  }
  Start-Sleep -Seconds 10
}
