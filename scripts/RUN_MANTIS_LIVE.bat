@echo off
setlocal
set "REPO=C:\CPharm\cpharm-main"
if not exist "%REPO%\automation\_run_mantis_hardcode_live.py" set "REPO=%~dp0.."
cd /d "%REPO%"
echo === ADB ===
adb devices -l
set CPHARM_SKIP_TOR_WAIT=1
set CPHARM_HUMAN_VARIATION=0
set CPHARM_BROWSE_PROXY_MODE=scramble
echo === LIVE RUN experimental mantis-hardcode #01 (~3-5 min) ===
echo repo=%CD%
py -3 automation\_run_mantis_hardcode_live.py --skip-tor-wait --wait-device 30 --sequence "900x1600/ad/mantis-hardcode/dabflow__mantis_hardcode__01__mat-ceramic__conc-distillate__heat-butane.json" --out C:\CPharm\MANTIS_HARDCODE_LIVE.txt
echo === RESULT ===
type C:\CPharm\MANTIS_HARDCODE_LIVE.txt
pause
