@echo off
setlocal EnableDelayedExpansion
title FarmBrowser - Sideloader
color 0A

set APK=%~dp0app\build\outputs\apk\debug\app-debug.apk

echo.
echo  ==========================================
echo   FarmBrowser - Sideloading on All Phones
echo  ==========================================
echo.

:: Check APK exists
if not exist "%APK%" (
    echo  [!] APK not found at: %APK%
    echo  [!] Build first:
    echo       cd %~dp0
    echo       gradlew.bat assembleDebug
    echo.
    pause
    exit /b 1
)

echo  [*] APK: %APK%
echo.

:: Check ADB
where adb >nul 2>&1
if errorlevel 1 (
    echo  [!] adb not found in PATH.
    echo  [!] Add Android SDK platform-tools to PATH, or use bundled\adb.exe
    set "ADB=%~dp0..\bundled\adb.exe"
    if exist "!ADB!" (
        echo  [+] Using bundled ADB: !ADB!
    ) else (
        echo  [!] No ADB found. Install Android SDK platform-tools.
        pause
        exit /b 1
    )
) else (
    set "ADB=adb"
)

echo  [*] Scanning for connected devices...
echo.

set COUNT=0
for /f "tokens=1" %%d in ('!ADB! devices ^| findstr /r "device$"') do (
    set /a COUNT+=1
    echo  [!COUNT!] Installing on %%d ...
    !ADB! -s %%d install -r "%APK%"
    if errorlevel 1 (
        echo      [!] Install FAILED on %%d
    ) else (
        echo      [+] Installed on %%d
    )
    echo.
)

if %COUNT%==0 (
    echo  [!] No devices found. Connect emulators first:
    echo       - MuMu: launch from MuMu Manager
    echo       - AVD:  emulator -avd <name>
    echo       - Check: adb devices
    pause
    exit /b 1
)

echo  ==========================================
echo   Installed on %COUNT% phone(s)!
echo  ==========================================
echo.
echo  Next: Set as default browser on each phone:
echo    adb shell cmd package set-home-activity com.farmbrowser.stealth/.browser.BrowserActivity
echo.
pause
