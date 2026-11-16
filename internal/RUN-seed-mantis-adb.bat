@echo off
REM PEF-39 offline seed launcher. FARM_STOP. Never farm Start. Never swap EXE.
REM Double-click safe: always runs seed script; prints summary even if git/API fail.
setlocal
cd /d "%~dp0"
set "PS1=%~dp0seed-mantis-adb.ps1"
set "SUM1=%~dp0mantis-pull-last.txt"
set "SUM2=C:\PharmFlow\logs\mantis-pull-last.txt"

if not exist "%PS1%" (
  echo MISS seed-mantis-adb.ps1 next to this bat
  echo FARM_STOP=1
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
set "RC=%ERRORLEVEL%"

echo.
echo ===== mantis-pull-last.txt =====
if exist "%SUM1%" (
  type "%SUM1%"
) else if exist "%SUM2%" (
  type "%SUM2%"
) else (
  echo MISS summary file
  echo REPO_TIP=unknown SEEDED=no MANTIS=fail ADB=0 FARM_STOP=1
)
echo ===== end =====
echo EXIT=%RC% FARM_STOP=1
pause
exit /b %RC%
