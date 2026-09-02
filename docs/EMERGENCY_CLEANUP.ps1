# CPharm Emergency Cleanup & Restart
Write-Host "=== CPharm Emergency Recovery ===" -ForegroundColor Yellow

# 1. Kill all CPharm/Python processes
Write-Host "[1/6] Killing stale processes..." -ForegroundColor Cyan
Get-Process | Where-Object { 
    $_.ProcessName -match "python|adb" -or 
    $_.Path -match "CPharm" 
} | ForEach-Object {
    Stop-Process -Id $_.Id -Force -ErrorAction Ignore
}
Start-Sleep 2

# 2. Clear port locks
Write-Host "[2/6] Clearing port locks..." -ForegroundColor Cyan
$ports = @(8080, 8091, 8118, 8119, 8120, 8121, 8122, 8123, 8124, 8125, 8126, 8127, 9050, 9051, 9052, 9053, 9054, 9055, 9056, 9057, 9058, 9059)
foreach ($port in $ports) {
    $proc = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Ignore | Select-Object -First 1
    if ($proc) {
        Get-Process -Id $proc.OwningProcess -ErrorAction Ignore | Stop-Process -Force -ErrorAction Ignore
    }
}

# 3. Restart ADB server
Write-Host "[3/6] Restarting ADB server..." -ForegroundColor Cyan
& "C:\CPharm\bundled\adb.exe" kill-server 2>&1 | Out-Null
Start-Sleep 1
& "C:\CPharm\bundled\adb.exe" start-server 2>&1 | Out-Null
Start-Sleep 2

# 4. Clear stale logs
Write-Host "[4/6] Cleaning stale log entries..." -ForegroundColor Cyan
$logDir = "C:\CPharm\logs"
Remove-Item "$logDir\dash_trace.log" -ErrorAction Ignore
Remove-Item "$logDir\*heartbeat*" -ErrorAction Ignore

# 5. Verify MuMu
Write-Host "[5/6] Checking MuMu status..." -ForegroundColor Cyan
$mumuProc = Get-Process | Where-Object { $_.Path -match "MuMu" } | Select-Object -First 1
if ($mumuProc) {
    Write-Host "  OK: MuMu running"
} else {
    Write-Host "  WARNING: MuMu not running"
}

# 6. Done
Write-Host "[6/6] Cleanup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Next: Start CPharm.exe and follow Launch wizard" -ForegroundColor Yellow
