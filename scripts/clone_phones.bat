@echo off
setlocal EnableDelayedExpansion
title PharmFlow - Clone Phones
color 0A

echo.
echo  ==========================================
echo   PharmFlow - Clone Master Phone
echo  ==========================================
echo.

if not defined PHARMFLOW_LEGACY_EMU_CONSOLE (
    echo  [!] This script only runs when PHARMFLOW_LEGACY_EMU_CONSOLE points to a vendor emulator CLI.
    echo  [!] For MuMu / AVD farms, add devices from PharmFlow instead:
    echo       py -3 wizard\setup_wizard.py
    pause
    exit /b 1
)

set "LEGACY_CLI=%PHARMFLOW_LEGACY_EMU_CONSOLE%"

if not exist "!LEGACY_CLI!" (
    echo  [!] Legacy emulator CLI not found.
    echo      !LEGACY_CLI!
    pause
    exit /b 1
)

echo  How many phones do you want total?
echo  (Each phone uses ~1.5GB RAM)
echo.
set /p COUNT="  Enter number of phones: "

echo.
echo  [*] Creating %COUNT% phones from master...
echo.

for /l %%i in (1,1,%COUNT%) do (
    echo  [+] Creating phone %%i...
    "!LEGACY_CLI!" copy --name "PharmFlow-%%i" --from 0
    timeout /t 8 /nobreak >nul
    echo      Done.
)

echo.
echo  ==========================================
echo   %COUNT% phones created!
echo   Run scripts\launch_all.bat to start them.
echo  ==========================================
echo.
pause
