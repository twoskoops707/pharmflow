# Run on YOUR laptop at C:\PharmFlow (PowerShell). Shows live step log + result file.
$ErrorActionPreference = "Stop"
Set-Location "C:\PharmFlow"
Write-Host "=== ADB ===" -ForegroundColor Cyan
adb devices -l
$env:PHARMFLOW_SKIP_TOR_WAIT = "1"
$env:PHARMFLOW_HUMAN_VARIATION = "0"
$repo = if (Test-Path "C:\PharmFlow\pharmflow-main") { "C:\PharmFlow\pharmflow-main" } elseif (Test-Path "C:\Users\jsmil\PharmFlow\pharmflow-main") { "C:\Users\jsmil\PharmFlow\pharmflow-main" } else { (Get-Location).Path }
Write-Host "repo=$repo"
py -3 "$repo\automation\_run_mantis_hardcode_live.py" `
  --skip-tor-wait `
  --wait-device 120 `
  --sequence "900x1600/ad/mantis-hardcode/dabflow__mantis_hardcode__01__mat-ceramic__conc-distillate__heat-butane.json" `
  --out "C:\PharmFlow\MANTIS_HARDCODE_LIVE.txt"
Write-Host "=== RESULT ===" -ForegroundColor Cyan
Get-Content "C:\PharmFlow\MANTIS_HARDCODE_LIVE.txt"
