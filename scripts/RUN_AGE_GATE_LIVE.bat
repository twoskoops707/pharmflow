@echo off
setlocal
set "REPO=C:\CPharm\cpharm-main"
if not exist "%REPO%\automation\_run_age_gate_live.py" set "REPO=%~dp0.."
cd /d "%REPO%"
set CPHARM_HUMAN_VARIATION=0
set CPHARM_USE_SHELL_WM_FOCUS_CHEAT=1
py -3 automation\_run_age_gate_live.py %*
if errorlevel 1 exit /b 1
type C:\CPharm\AGE_GATE_TIMING.txt
exit /b 0
