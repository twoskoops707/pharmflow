# Sync C:\PharmFlow from GitHub main + latest Release exes + sequences.
# Run in PowerShell ON YOUR LAPTOP (not cloud):
#   cd C:\PharmFlow\pharmflow-main
#   git pull origin main
#   powershell -ExecutionPolicy Bypass -File scripts\SYNC_PHARMFLOW_FROM_GITHUB.ps1

$ErrorActionPreference = "Stop"
$PharmFlow = if (Test-Path "C:\PharmFlow") { "C:\PharmFlow" } else { $PSScriptRoot | Split-Path -Parent | Split-Path -Parent }
$Repo = if (Test-Path "$PharmFlow\pharmflow-main\.git") { "$PharmFlow\pharmflow-main" }
        elseif (Test-Path "$PharmFlow\.git") { $PharmFlow }
        else { (Get-Location).Path }

Write-Host "PharmFlow folder: $PharmFlow" -ForegroundColor Cyan
Write-Host "Git repo:      $Repo" -ForegroundColor Cyan

Set-Location $Repo
Write-Host "`n=== git pull origin main ===" -ForegroundColor Yellow
git fetch origin --prune
git pull origin main

Write-Host "`n=== copy sequences -> $PharmFlow\sequences ===" -ForegroundColor Yellow
$src = Join-Path $Repo "sequences"
$dst = Join-Path $PharmFlow "sequences"
if (-not (Test-Path $src)) { throw "missing $src" }
New-Item -ItemType Directory -Force -Path $dst | Out-Null
robocopy $src $dst /MIR /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
$hc = Join-Path $dst "900x1600\ad\mantis-hardcode"
Write-Host "mantis-hardcode files: $((Get-ChildItem $hc -Filter *.json -ErrorAction SilentlyContinue).Count) (expect 5)"

Write-Host "`n=== download latest Release exe ===" -ForegroundColor Yellow
$tag = (gh release list --limit 1 --json tagName -q ".[0].tagName" 2>$null)
if (-not $tag) { $tag = "wizard-427" }
Write-Host "Release tag: $tag"
gh release download $tag -p "PharmFlow.exe" -D "C:\PharmFlow" --clobber
Get-ChildItem "$PharmFlow\*.exe" | Format-Table Name, Length, LastWriteTime

Write-Host "`n=== verify ===" -ForegroundColor Yellow
git log -1 --oneline
Write-Host "DONE. Exes in $PharmFlow ; sequences in $dst"
Write-Host "Test experimental seq: scripts\RUN_MANTIS_LIVE.bat" -ForegroundColor Green
