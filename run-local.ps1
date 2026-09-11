param(
  [string]$WhisperModel = 'small',
  [ValidateSet('auto','cuda','cpu')]
  [string]$WhisperDevice = 'auto',
  [ValidateSet('lmstudio','ollama')]
  [string]$LlmProvider = 'lmstudio',
  [string]$AnalysisModel = ''
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = Join-Path $Root 'app'
$WhisperDir = Join-Path $Root 'local-whisper'
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
$WhisperPort = 8178
$OllamaModel = 'fraktall-qwen'
$LmStudioBase = 'http://127.0.0.1:1234/v1'
$OllamaBase = 'http://127.0.0.1:11434/v1'

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

$ChatBase = ''
if ($LlmProvider -eq 'lmstudio') {
  if (-not $AnalysisModel.Trim()) { $AnalysisModel = 'qwen/qwen3-1.7b' }
  if (-not (Test-Http "$LmStudioBase/models")) {
    throw 'LM Studio local server is not reachable on http://127.0.0.1:1234. Open LM Studio > Developer > Local Server and switch Status to Running.'
  }
  $ChatBase = $LmStudioBase
  $env:FRAKTALL_NO_THINK = '1'
} else {
  if (-not $AnalysisModel.Trim()) { $AnalysisModel = $OllamaModel }
  if ($null -eq (Get-Command ollama -ErrorAction SilentlyContinue)) {
    throw 'Ollama is not installed. Run .\setup.ps1 first or use -LlmProvider lmstudio.'
  }
  if (-not (Test-Http 'http://127.0.0.1:11434/api/tags')) {
    Write-Host 'Starting Ollama...' -ForegroundColor Cyan
    Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden | Out-Null
    for ($i = 0; $i -lt 30; $i++) {
      Start-Sleep -Seconds 1
      if (Test-Http 'http://127.0.0.1:11434/api/tags') { break }
    }
  }
  if (-not (Test-Http 'http://127.0.0.1:11434/api/tags')) { throw 'Ollama did not start on port 11434.' }
  $ChatBase = $OllamaBase
  Remove-Item Env:FRAKTALL_NO_THINK -ErrorAction SilentlyContinue
}

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
$env:OPENAI_BASE_URL = $ChatBase
$env:OPENAI_TRANSCRIPTION_BASE_URL = "http://127.0.0.1:$WhisperPort/v1"
$env:FRAKTALL_ANALYSIS_MODEL = $AnalysisModel

# Keep local-only defaults idempotently applied even when setup predates them.
$localDefaults = Join-Path $Root 'apply_local_defaults.py'
if (Test-Path $localDefaults) {
  & $VenvPython $localDefaults --app $AppDir
  if ($LASTEXITCODE -ne 0) { throw 'Could not apply Fraktall local defaults.' }
}

# Provider/model are runtime choices so switching LM Studio <-> Ollama does not
# require regenerating the whole patched ClipForge checkout.
$runtimeOverrides = Join-Path $Root 'apply_runtime_overrides.py'
if (Test-Path $runtimeOverrides) {
  & $VenvPython $runtimeOverrides --app $AppDir
  if ($LASTEXITCODE -ne 0) { throw 'Could not apply Fraktall runtime provider overrides.' }
}

Write-Host "`nFraktall local stack ready" -ForegroundColor Green
Write-Host "LLM:       $LlmProvider / $AnalysisModel"
Write-Host "API:       $ChatBase"
Write-Host "Whisper:   faster-whisper / $WhisperModel"
Write-Host 'Language:  Portuguese'
Write-Host 'Framing:   Podcast preset + active-speaker auto-reframe when faces are detected'
if ($LlmProvider -eq 'lmstudio') {
  Write-Host 'Qwen mode: /no_think (fast structured extraction)'
}
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
