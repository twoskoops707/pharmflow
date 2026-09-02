@echo off
setlocal EnableDelayedExpansion
title CPharm - Install App
color 0A

set APKDIR=%~dp0..\apks

echo.
echo  ==========================================
echo   CPharm - Install App on Master Phone
echo  ==========================================
echo.

:: Find APK
set APK=
for %%f in ("%APKDIR%\*.apk") do set APK=%%f

if not defined APK (
    echo  [!] No APK found in apks\ folder.
    echo  [!] Drop your .apk file there and try again.
    pause & exit /b 1
)

echo  [*] Found: %APK%

if defined CPHARM_LEGACY_EMU_CONSOLE (
    set "LEGACY_CLI=%CPHARM_LEGACY_EMU_CONSOLE%"
    if not exist "!LEGACY_CLI!" (
        echo  [!] CPHARM_LEGACY_EMU_CONSOLE path not found:
        echo      !LEGACY_CLI!
        pause & exit /b 1
    )
    echo  [*] Installing on master phone (index 0) via legacy CLI...
    "!LEGACY_CLI!" installapp --index 0 --filename "%APK%"
    goto :AFTER_INSTALL
)

where adb >nul 2>&1
if errorlevel 1 (
    echo  [!] adb not found in PATH.
    echo  [!] Install Android platform-tools, or set CPHARM_LEGACY_EMU_CONSOLE, or use CPharm:
    echo       py -3 wizard\setup_wizard.py
    pause & exit /b 1
)

echo  [*] Installing via adb (single connected device / default target)...
adb install -r "%APK%"
if errorlevel 1 (
    echo  [!] adb install failed. Connect one emulator or device, or use CPharm.
    pause & exit /b 1
)

:AFTER_INSTALL
echo.
echo  ==========================================
echo   Done! For multi-device farms, use CPharm (MuMu / AVD).
echo  ==========================================
echo.
pause
