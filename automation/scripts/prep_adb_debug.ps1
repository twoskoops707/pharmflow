# Optional prep: enable ADB-friendly flags on a connected device (run from repo root).
# Does NOT replace tapping Build number seven times for Developer options — do that in the emulator UI once.
param(
    [string]$Serial = ""
)
$ErrorActionPreference = "Stop"
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
if (-not (Test-Path $adb)) { $adb = "adb" }
$s = if ($Serial) { @("-s", $Serial) } else { @() }
& $adb @s @("shell", "settings", "put", "global", "adb_enabled", "1")
& $adb @s @("shell", "settings", "put", "global", "development_settings_enabled", "1")
Write-Host "Done (best-effort). Enable USB debugging in Developer options if not already."
