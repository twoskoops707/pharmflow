# Auto-connect ALL phones: Docker Redroid + MuMu emulators
# Usage: 
#   .\auto_adb_connect.ps1                 (both Docker + MuMu)
#   .\auto_adb_connect.ps1 -DockerOnly     (Docker only)
#   .\auto_adb_connect.ps1 -MumuOnly       (MuMu only)
#   .\auto_adb_connect.ps1 -Timeout 15     (custom timeout)

param(
    [switch]$DockerOnly,
    [switch]$MumuOnly,
    [int]$Timeout = 8
)

$AdbExe = "C:\CPharm\bundled\adb.exe"
if (-not (Test-Path $AdbExe)) {
    Write-Host "ERROR: ADB not found at $AdbExe" -ForegroundColor Red
    exit 1
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "AUTO-CONNECT ALL PHONES" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Determine which to connect
if ($DockerOnly) {
    $ConnectDocker = $true
    $ConnectMumu = $false
} elseif ($MumuOnly) {
    $ConnectDocker = $false
    $ConnectMumu = $true
} else {
    $ConnectDocker = $true
    $ConnectMumu = $true
}

$AllPhones = @()

# Connect Docker Redroid
if ($ConnectDocker) {
    Write-Host "[*] Connecting Docker Redroid (ports 5555-5562)..." -ForegroundColor Cyan
    $Ports = 5555..5562
    foreach ($Port in $Ports) {
        $Addr = "127.0.0.1:$Port"
        try {
            $Output = & $AdbExe connect $Addr 2>&1
            if ($Output -match "connected|already") {
                $AllPhones += $Addr
                Write-Host "  [+] $Addr" -ForegroundColor Green
            } else {
                Write-Host "  [-] $Addr" -ForegroundColor Red
            }
        } catch {
            Write-Host "  [?] $Addr (error)" -ForegroundColor Yellow
        }
    }
}

# Connect MuMu emulators
if ($ConnectMumu) {
    Write-Host "[*] Connecting MuMu emulators (ports 16384-16393)..." -ForegroundColor Cyan
    $Ports = 16384..16393
    foreach ($Port in $Ports) {
        $Addr = "127.0.0.1:$Port"
        try {
            $Output = & $AdbExe connect $Addr 2>&1
            if ($Output -match "connected|already") {
                $AllPhones += $Addr
                Write-Host "  [+] $Addr" -ForegroundColor Green
            } else {
                Write-Host "  [-] $Addr" -ForegroundColor Red
            }
        } catch {
            Write-Host "  [?] $Addr (error)" -ForegroundColor Yellow
        }
    }
}

if ($AllPhones.Count -eq 0) {
    Write-Host "ERROR: No phones found" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[+] Discovered $($AllPhones.Count) phone(s)" -ForegroundColor Green

Write-Host "[*] Verifying ADB connections..." -ForegroundColor Cyan
Start-Sleep 1

$Output = & $AdbExe devices -l
$ConnectedCount = ($Output | Select-String "device" | Measure-Object).Count - 1

Write-Host "[+] ADB online: $ConnectedCount device(s)" -ForegroundColor Green
$Output | Select-String "device" | Select-Object -Skip 1

if ($ConnectedCount -gt 0) {
    Write-Host ""
    Write-Host "[OK] Success! $ConnectedCount phone(s) ready" -ForegroundColor Green
    exit 0
} else {
    Write-Host ""
    Write-Host "[WAIT] No devices online yet (ADB initializing...)" -ForegroundColor Yellow
    Write-Host "Try again in 30s if still offline" -ForegroundColor Yellow
    exit 1
}
