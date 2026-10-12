# Publish the public page's data: export an allow-listed snapshot of logs/ (agent/site.py), upload it to the
# "site-data" release on GitHub and redeploy the page (.github/workflows/pages.yml). Run it after merging a PR into
# main on the PC that plays, or whenever the page should catch up. Nothing on the page is ever read back.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/publish-site.ps1 [-DryRun]
#   -DryRun  only builds the snapshot (and says where), uploads nothing
param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repo
$slug = 'LimtlessLtd/AI-v-Z'
$tag = 'site-data'
$url = 'https://limtlessltd.github.io/AI-v-Z/'

$tmp = Join-Path $env:TEMP 'aivz-site'
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
New-Item -ItemType Directory -Force $tmp | Out-Null
$zip = Join-Path $tmp 'snapshot.zip'
python -m agent.site --out (Join-Path $tmp 'data') --zip $zip
if ($LASTEXITCODE -ne 0) { throw "The export failed (python -m agent.site)." }
Write-Host ("Snapshot: {0:N1} MB" -f ((Get-Item $zip).Length / 1MB))
if ($DryRun) { Write-Host "Dry run: nothing uploaded. The export is in $tmp\data"; exit 0 }

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw "The GitHub CLI (gh) is needed to publish." }
# gh writes 'release not found' to stderr; Windows PowerShell 5.1 would turn that into an error under 'Stop'
$ErrorActionPreference = 'Continue'
gh release view $tag --repo $slug *> $null
$exists = $LASTEXITCODE -eq 0
$ErrorActionPreference = 'Stop'
if (-not $exists) {
  Write-Host "Creating the '$tag' pre-release that holds the page's data (first publish only)."
  gh release create $tag --repo $slug --target main --prerelease --title 'Page data (not a release)' `
    --notes "The data behind $url, uploaded by scripts/publish-site.ps1. Replaced on every publish; not a version of AI-v-Z."
  if ($LASTEXITCODE -ne 0) { throw "Could not create the '$tag' release." }
}
gh release upload $tag $zip --repo $slug --clobber
if ($LASTEXITCODE -ne 0) { throw "The upload failed." }
# the upload comes first, so this deploy picks up the new data (a push to main alone reuses the last upload)
gh workflow run pages.yml --repo $slug --ref main
if ($LASTEXITCODE -ne 0) { throw "Could not start the Pages deploy." }
Write-Host "Published. The page updates in a minute or two: $url"
Write-Host "To follow the deploy: gh run watch --repo $slug"
