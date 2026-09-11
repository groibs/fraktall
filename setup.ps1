param(
  [switch]$SkipOllama,
  [switch]$SkipPullModel,
  [switch]$ForceReset
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = Join-Path $Root 'app'
$VenvDir = Join-Path $Root '.venv'
$Upstream = 'https://github.com/JeremySNR/clip-forge.git'
$UpstreamCommit = '35814e546db958c6d66d4f82697bf6c2136d62af'
$BaseModel = 'qwen3:4b-instruct'
$FraktallModel = 'fraktall-qwen'

function Refresh-Path {
  $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $user = [Environment]::GetEnvironmentVariable('Path', 'User')
  $env:Path = "$machine;$user"
}

function Have([string]$Name) {
  return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Ensure-WingetPackage([string]$Command, [string]$PackageId) {
  if (Have $Command) { return }
  if (-not (Have 'winget')) {
    throw "'$Command' is missing and winget is unavailable. Install $PackageId manually, then rerun setup.ps1."
  }
  Write-Host "Installing $PackageId..." -ForegroundColor Cyan
  winget install --id $PackageId -e --silent --accept-source-agreements --accept-package-agreements
  Refresh-Path
  if (-not (Have $Command)) {
    throw "Installed $PackageId, but '$Command' is still not visible in PATH. Reopen PowerShell and rerun setup.ps1."
  }
}

function Test-Http([string]$Url) {
  try {
    Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2 | Out-Null
    return $true
  } catch {
    return $false
  }
}

function Resolve-Python {
  if (Have 'py') {
    foreach ($version in @('3.11', '3.12', '3.10')) {
      & py "-$version" -c "import sys" *> $null
      if ($LASTEXITCODE -eq 0) { return @('py', "-$version") }
    }
  }

  if (Have 'python') {
    try {
      $minor = (& python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null).Trim()
      if ($minor -in @('3.10', '3.11', '3.12')) { return @('python') }
    } catch {}
  }

  return $null
}

function Invoke-PythonScript([string]$ScriptPath, [string[]]$ScriptArgs) {
  if ($pythonCmd.Count -eq 2) {
    & $pythonCmd[0] $pythonCmd[1] $ScriptPath @ScriptArgs
  } else {
    & $pythonCmd[0] $ScriptPath @ScriptArgs
  }
  if ($LASTEXITCODE -ne 0) { throw "Python script failed: $ScriptPath" }
}

Write-Host "`nFraktall local setup" -ForegroundColor Green
Write-Host "Workspace: $Root`n"

Ensure-WingetPackage 'git' 'Git.Git'
Ensure-WingetPackage 'node' 'OpenJS.NodeJS.LTS'

$pythonCmd = Resolve-Python
if ($null -eq $pythonCmd) {
  if (-not (Have 'winget')) { throw 'Python 3.10, 3.11 or 3.12 is required.' }
  Write-Host 'Installing Python 3.11...' -ForegroundColor Cyan
  winget install --id Python.Python.3.11 -e --silent --accept-source-agreements --accept-package-agreements
  Refresh-Path
  $pythonCmd = Resolve-Python
}
if ($null -eq $pythonCmd) {
  throw 'Python 3.11 was not detected. Close PowerShell, reopen it and rerun setup.ps1.'
}

if (-not $SkipOllama) {
  if (-not (Have 'ollama')) {
    Write-Host 'Installing Ollama...' -ForegroundColor Cyan
    if (Have 'winget') {
      winget install --id Ollama.Ollama -e --silent --accept-source-agreements --accept-package-agreements
    } else {
      irm https://ollama.com/install.ps1 | iex
    }
    Refresh-Path
  }
  if (-not (Have 'ollama')) {
    throw 'Ollama installation finished but ollama.exe is not visible. Reopen PowerShell and rerun setup.ps1.'
  }

  if (-not (Test-Http 'http://127.0.0.1:11434/api/tags')) {
    Write-Host 'Starting Ollama server...' -ForegroundColor Cyan
    Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden | Out-Null
    for ($i = 0; $i -lt 30; $i++) {
      Start-Sleep -Seconds 1
      if (Test-Http 'http://127.0.0.1:11434/api/tags') { break }
    }
  }

  if (-not $SkipPullModel) {
    Write-Host "Pulling $BaseModel..." -ForegroundColor Cyan
    ollama pull $BaseModel
    Write-Host "Creating tuned local profile $FraktallModel..." -ForegroundColor Cyan
    ollama create $FraktallModel -f (Join-Path $Root 'Modelfile')
  }
}

if (Test-Path (Join-Path $AppDir '.git')) {
  Write-Host 'Refreshing pinned ClipForge source...' -ForegroundColor Cyan
  git -C $AppDir fetch origin $UpstreamCommit --depth=1
  git -C $AppDir checkout --detach $UpstreamCommit
  git -C $AppDir reset --hard $UpstreamCommit
  if ($ForceReset) { git -C $AppDir clean -fd }
} else {
  if (Test-Path $AppDir) { Remove-Item -Recurse -Force $AppDir }
  Write-Host 'Cloning pinned ClipForge base...' -ForegroundColor Cyan
  git clone --no-tags $Upstream $AppDir
  git -C $AppDir checkout --detach $UpstreamCommit
}

Write-Host 'Applying Fraktall patches...' -ForegroundColor Cyan
Invoke-PythonScript (Join-Path $Root 'apply_patch_runner.py') @('--app', $AppDir)
Invoke-PythonScript (Join-Path $Root 'apply_local_defaults.py') @('--app', $AppDir)

Write-Host 'Installing desktop app dependencies...' -ForegroundColor Cyan
Push-Location $AppDir
try {
  npm ci
} finally {
  Pop-Location
}

if (-not (Test-Path $VenvDir)) {
  Write-Host 'Creating local Whisper environment...' -ForegroundColor Cyan
  if ($pythonCmd.Count -eq 2) {
    & $pythonCmd[0] $pythonCmd[1] -m venv $VenvDir
  } else {
    & $pythonCmd[0] -m venv $VenvDir
  }
}

$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
if (-not (Test-Path $VenvPython)) { throw 'Virtual environment Python was not created.' }

Write-Host 'Installing faster-whisper dependencies...' -ForegroundColor Cyan
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $Root 'local-whisper\requirements.txt')

Write-Host "`nSetup complete." -ForegroundColor Green
Write-Host 'Run:' -ForegroundColor White
Write-Host '  .\run-local.ps1' -ForegroundColor Yellow
Write-Host "`nDefaults: Portuguese, podcast curation, fraktall-qwen local, faster-whisper Small local.`n"