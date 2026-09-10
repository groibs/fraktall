$ErrorActionPreference = 'Continue'

function Pass([string]$Message) { Write-Host "[OK]   $Message" -ForegroundColor Green }
function Fail([string]$Message) { Write-Host "[FAIL] $Message" -ForegroundColor Red }
function Info([string]$Message) { Write-Host "[INFO] $Message" -ForegroundColor Cyan }

function Have([string]$Name) {
  return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Check-Http([string]$Name, [string]$Url) {
  try {
    $res = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
    if ($res.StatusCode -ge 200 -and $res.StatusCode -lt 300) { Pass "$Name: $Url"; return $true }
    Fail "$Name returned HTTP $($res.StatusCode)"
    return $false
  } catch {
    Fail "$Name is not responding at $Url"
    return $false
  }
}

Write-Host "`nFraktall local check`n" -ForegroundColor White

foreach ($cmd in @('git', 'node', 'npm', 'ollama')) {
  if (Have $cmd) {
    $version = try { (& $cmd --version 2>$null | Select-Object -First 1) } catch { 'installed' }
    Pass "$cmd $version"
  } else {
    Fail "$cmd not found"
  }
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$app = Join-Path $root 'app'
$venvPython = Join-Path $root '.venv\Scripts\python.exe'

if (Test-Path $app) { Pass 'Patched desktop app folder exists' } else { Fail 'app/ missing; run setup.ps1' }
if (Test-Path $venvPython) { Pass 'Local Whisper Python environment exists' } else { Fail '.venv missing; run setup.ps1' }

$ollamaOk = Check-Http 'Ollama' 'http://127.0.0.1:11434/api/tags'
$whisperOk = Check-Http 'Whisper' 'http://127.0.0.1:8178/health'

if ($ollamaOk) {
  try {
    $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3
    $modelNames = @($tags.models | ForEach-Object { $_.name })
    if ($modelNames -match '^fraktall-qwen(?::latest)?$') {
      Pass 'fraktall-qwen is installed'
    } elseif ($modelNames -match '^qwen3:4b-instruct') {
      Fail 'Base Qwen model exists, but fraktall-qwen is missing; rerun setup.ps1 to create the tuned profile'
    } else {
      Fail 'Fraktall Qwen model is missing; rerun setup.ps1'
    }
  } catch {
    Fail 'Could not inspect Ollama models'
  }
}

if (-not $whisperOk) {
  Info 'The Whisper service normally starts automatically with run-local.ps1.'
}

Write-Host "`nIf only Whisper is offline, that is normal before run-local.ps1.`n"
