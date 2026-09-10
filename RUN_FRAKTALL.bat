@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-local.ps1"
if errorlevel 1 (
  echo.
  echo O Fraktall encerrou com erro. Leia a mensagem acima.
  pause
)
