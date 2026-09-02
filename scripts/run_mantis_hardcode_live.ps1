# Run on YOUR laptop at C:\CPharm (PowerShell). Shows live step log + result file.
$ErrorActionPreference = "Stop"
Set-Location "C:\CPharm"
Write-Host "=== ADB ===" -ForegroundColor Cyan
adb devices -l
$env:CPHARM_SKIP_TOR_WAIT = "1"
$env:CPHARM_HUMAN_VARIATION = "0"
$repo = if (Test-Path "C:\CPharm\cpharm-main") { "C:\CPharm\cpharm-main" } elseif (Test-Path "C:\Users\jsmil\CPharm\cpharm-main") { "C:\Users\jsmil\CPharm\cpharm-main" } else { (Get-Location).Path }
Write-Host "repo=$repo"
py -3 "$repo\automation\_run_mantis_hardcode_live.py" `
  --skip-tor-wait `
  --wait-device 120 `
  --sequence "900x1600/ad/mantis-hardcode/dabflow__mantis_hardcode__01__mat-ceramic__conc-distillate__heat-butane.json" `
  --out "C:\CPharm\MANTIS_HARDCODE_LIVE.txt"
Write-Host "=== RESULT ===" -ForegroundColor Cyan
Get-Content "C:\CPharm\MANTIS_HARDCODE_LIVE.txt"
