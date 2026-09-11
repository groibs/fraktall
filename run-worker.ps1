param(
  [string]$WhisperModel = 'small',
  [ValidateSet('auto','cuda','cpu')]
  [string]$WhisperDevice = 'auto'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
$WhisperDir = Join-Path $Root 'local-whisper'
$WorkerDir = Join-Path $Root 'worker'
$EnvFile = Join-Path $WorkerDir '.env.local'
$WhisperPort = 8178

function Test-Http([string]$Url) {
  try {
    Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3 | Out-Null
    return $true
  } catch {
    return $false
  }
}

function Load-EnvFile([string]$Path) {
  if (-not (Test-Path $Path)) { return }
  foreach ($line in Get-Content $Path) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
    $parts = $trimmed -split '=', 2
    if ($parts.Count -ne 2) { continue }
    [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), 'Process')
  }
}

if (-not (Test-Path $VenvPython)) {
  throw 'Fraktall Python environment is missing. Run .\setup.ps1 first.'
}

if (-not (Test-Path $EnvFile)) {
  throw 'worker\.env.local is missing. Copy worker\.env.example to worker\.env.local and fill Supabase values.'
}

Load-EnvFile $EnvFile

if (-not $env:SUPABASE_URL -or -not $env:SUPABASE_SERVICE_ROLE_KEY) {
  throw 'SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required in worker\.env.local.'
}

$lmBase = if ($env:LMSTUDIO_BASE_URL) { $env:LMSTUDIO_BASE_URL.TrimEnd('/') } else { 'http://127.0.0.1:1234/v1' }
if (-not (Test-Http "$lmBase/models")) {
  throw "LM Studio is not reachable at $lmBase. Open LM Studio, load Qwen3 1.7B, and start Local Server."
}

Write-Host 'Installing/updating worker dependencies...' -ForegroundColor Cyan
& $VenvPython -m pip install -q -r (Join-Path $WorkerDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install worker dependencies.' }

$env:WHISPER_MODEL = $WhisperModel
$env:WHISPER_DEVICE = $WhisperDevice
if (-not $env:WHISPER_BASE_URL) { $env:WHISPER_BASE_URL = "http://127.0.0.1:$WhisperPort/v1" }
if (-not $env:WHISPER_MODEL) { $env:WHISPER_MODEL = $WhisperModel }

$whisperProcess = $null
if (-not (Test-Http "http://127.0.0.1:$WhisperPort/health")) {
  Write-Host "Starting local Whisper ($WhisperModel, $WhisperDevice)..." -ForegroundColor Cyan
  $whisperArgs = @('-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', "$WhisperPort")
  $whisperProcess = Start-Process `
    -FilePath $VenvPython `
    -ArgumentList $whisperArgs `
    -WorkingDirectory $WhisperDir `
    -WindowStyle Hidden `
    -PassThru

  for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Http "http://127.0.0.1:$WhisperPort/health") { break }
  }
}

if (-not (Test-Http "http://127.0.0.1:$WhisperPort/health")) {
  if ($whisperProcess -and -not $whisperProcess.HasExited) { Stop-Process -Id $whisperProcess.Id -Force }
  throw 'Local Whisper did not start on port 8178.'
}

Write-Host "`nFraktall Worker ready" -ForegroundColor Green
Write-Host "Worker:     $($env:FRAKTALL_WORKER_ID)"
Write-Host "LM Studio:  $lmBase"
Write-Host "Whisper:    $($env:WHISPER_BASE_URL)"
Write-Host "Supabase:   $($env:SUPABASE_URL)"
Write-Host "`nWaiting for jobs from the web console... Ctrl+C to stop.`n" -ForegroundColor Yellow

try {
  & $VenvPython (Join-Path $WorkerDir 'worker.py')
} finally {
  if ($whisperProcess -and -not $whisperProcess.HasExited) {
    Stop-Process -Id $whisperProcess.Id -Force -ErrorAction SilentlyContinue
  }
}
