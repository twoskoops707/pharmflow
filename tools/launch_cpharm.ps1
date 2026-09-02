[CmdletBinding()]
param(
    [switch]$SkipArtifactCheck,
    [switch]$Wait
)

$ErrorActionPreference = 'Stop'
$folder = Split-Path -Parent $MyInvocation.MyCommand.Path
$required = @('CPharm.exe', 'CPharmAgent.exe', 'CPharmWatchdog.exe')

if (-not $SkipArtifactCheck) {
    $missing = @($required | Where-Object { -not (Test-Path (Join-Path $folder $_) -PathType Leaf) })
    if ($missing.Count -gt 0) {
        Write-Error ("Portable CPharm folder is incomplete. Missing: " + ($missing -join ', ') + ". Download all three EXEs into the same folder, then run this launcher again.")
        exit 1
    }
}

$main = Join-Path $folder 'CPharm.exe'
if (-not (Test-Path $main -PathType Leaf)) {
    Write-Error "CPharm.exe was not found in $folder."
    exit 1
}

$process = Start-Process -FilePath $main -WorkingDirectory $folder -PassThru
Write-Host "Started CPharm.exe (PID $($process.Id)) from $folder"
if ($Wait) { Wait-Process -Id $process.Id }
