@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM  Build CloudPhones.exe
REM  
REM  Prerequisites:
REM    pip install pyinstaller
REM
REM  Output:
REM    cloud_phones\dist\CloudPhones.exe
REM    CloudPhones.exe (copied to project root)
REM ─────────────────────────────────────────────────────────────────────────────

echo.
echo ========================================
echo   Building CloudPhones.exe
echo ========================================
echo.

REM Check PyInstaller
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller
)

REM Run the build script
python cloud_phones\build_cloud_phones.py

if errorlevel 1 (
    echo.
    echo Build failed! Check the output above for errors.
    pause
    exit /b 1
)

echo.
echo Done! CloudPhones.exe is ready.
echo.
pause
