@echo off
setlocal
cd /d "%~dp0"
echo.
echo Fraktall - instalacao local
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
  echo.
  echo A instalacao falhou. Leia a mensagem acima.
  pause
  exit /b 1
)
echo.
echo Instalacao concluida. Agora execute RUN_FRAKTALL.bat
pause
