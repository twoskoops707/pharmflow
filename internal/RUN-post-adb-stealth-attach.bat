@echo off
REM PEF-41 post-ADB stealth + attach + gate status. FARM_STOP. Never Start farm.
REM Double-click on skoops after ADB reconnect. Tip-145 SHA report only.
setlocal
cd /d "%~dp0"
set "PS1=%~dp0post-adb-stealth-attach.ps1"
set "SUM1=%~dp0post-adb-stealth-last.txt"
set "SUM2=C:\PharmFlow\logs\post-adb-stealth-last.txt"

echo FARM_STOP=1
echo START_FARM=never

if not exist "%PS1%" (
  echo MISS post-adb-stealth-attach.ps1 next to this bat
  echo FARM_STOP=1
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
set "RC=%ERRORLEVEL%"

echo.
echo ===== post-adb-stealth-last.txt =====
if exist "%SUM1%" (
  type "%SUM1%"
) else if exist "%SUM2%" (
  type "%SUM2%"
) else (
  echo MISS summary file
  echo ADB=? TIP145=? STEALTH_OK=unknown FUNDS_OK=unknown PHONE_COUNT=0 ATTACH=miss FARM_STOP=1
)
echo ===== end =====
echo EXIT=%RC% FARM_STOP=1 START_FARM=never
pause
exit /b %RC%
