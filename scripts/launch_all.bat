@echo off
setlocal EnableDelayedExpansion
title PharmFlow - Launch All Phones
color 0A

echo.
echo  ==========================================
echo   PharmFlow - Launching All Phones
echo  ==========================================
echo.

if not defined PHARMFLOW_LEGACY_EMU_CONSOLE (
    echo  [!] This script only runs when PHARMFLOW_LEGACY_EMU_CONSOLE points to a vendor emulator CLI.
    echo  [!] For MuMu Player and Android Studio AVDs, start instances from PharmFlow:
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

set COUNT=0
for /f "tokens=1,2 delims=," %%i in ('"!LEGACY_CLI!" list2') do (
    set INDEX=%%i
    set NAME=%%j
    if /i "!NAME:~0,6!"=="PharmFlow" (
        set /a COUNT+=1
        echo  [+] Starting !NAME! (index !INDEX!)...
        "!LEGACY_CLI!" launch --index !INDEX!
        timeout /t 3 /nobreak >nul
    )
)

if %COUNT%==0 (
    echo  [!] No PharmFlow phones found.
    echo  [!] Create instances from PharmFlow, or run scripts\clone_phones.bat if your CLI supports it.
    pause
    exit /b 1
)

echo.
echo  ==========================================
echo   %COUNT% phones launched!
echo.
echo   Dashboard: run automation\start_dashboard.bat
echo   then open http://localhost:8080
echo  ==========================================
echo.
pause
