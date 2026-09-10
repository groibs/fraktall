param(
  [string]$WhisperModel = 'small',
  [ValidateSet('auto','cuda','cpu')]
  [string]$WhisperDevice = 'auto'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = Join-Path $Root 'app'
$WhisperDir = Join-Path $Root 'local-whisper'
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
$OllamaModel = 'fraktall-qwen'
$WhisperPort = 8178

function Test-Http([string]$Url) {
  try {
    Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2 | Out-Null
    return $true
  } catch {
    return $false
  }
}

if (-not (Test-Path $AppDir)) { throw 'Fraktall app is not prepared. Run .\setup.ps1 first.' }
if (-not (Test-Path $VenvPython)) { throw 'Local Whisper environment is missing. Run .\setup.ps1 first.' }
if ($null -eq (Get-Command ollama -ErrorAction SilentlyContinue)) { throw 'Ollama is not installed. Run .\setup.ps1 first.' }

if (-not (Test-Http 'http://127.0.0.1:11434/api/tags')) {
  Write-Host 'Starting Ollama...' -ForegroundColor Cyan
  Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden | Out-Null
  for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Http 'http://127.0.0.1:11434/api/tags') { break }
  }
}
if (-not (Test-Http 'http://127.0.0.1:11434/api/tags')) { throw 'Ollama did not start on port 11434.' }

$env:WHISPER_MODEL = $WhisperModel
$env:WHISPER_DEVICE = $WhisperDevice

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

# ClipForge expects a key even when local OpenAI-compatible servers ignore it.
$env:OPENAI_API_KEY = 'fraktall-local'
$env:OPENAI_BASE_URL = 'http://127.0.0.1:11434/v1'
$env:OPENAI_TRANSCRIPTION_BASE_URL = "http://127.0.0.1:$WhisperPort/v1"

# Keep local-only defaults idempotently applied even when setup predates them.
$localDefaults = Join-Path $Root 'apply_local_defaults.py'
if (Test-Path $localDefaults) {
  & $VenvPython $localDefaults --app $AppDir
  if ($LASTEXITCODE -ne 0) { throw 'Could not apply Fraktall local defaults.' }
}

Write-Host "`nFraktall local stack ready" -ForegroundColor Green
Write-Host "LLM:       Ollama / $OllamaModel"
Write-Host "Whisper:   faster-whisper / $WhisperModel"
Write-Host 'Language:  Portuguese'
Write-Host 'Framing:   Podcast preset + active-speaker auto-reframe when faces are detected'
Write-Host "`nStarting desktop app...`n" -ForegroundColor Cyan

Push-Location $AppDir
try {
  npm run dev
} finally {
  Pop-Location
  if ($whisperProcess -and -not $whisperProcess.HasExited) {
    Stop-Process -Id $whisperProcess.Id -Force -ErrorAction SilentlyContinue
  }
}
