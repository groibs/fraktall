param(
  [switch]$SkipSetup
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = Join-Path $Root 'app'

if (-not $SkipSetup) {
  & (Join-Path $Root 'setup.ps1') -SkipPullModel
}

if (-not (Test-Path (Join-Path $AppDir 'package.json'))) {
  throw 'Patched app is missing. Run setup.ps1 first.'
}

Push-Location $AppDir
try {
  npm run typecheck
  npm test
  npm run package
  Write-Host "`nWindows package build finished. Check app\release\" -ForegroundColor Green
} finally {
  Pop-Location
}
