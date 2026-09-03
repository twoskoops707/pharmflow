[CmdletBinding()]
param(
    [switch]$SkipArtifactCheck,
    [switch]$Wait
)

$ErrorActionPreference = 'Stop'
$folder = Split-Path -Parent $MyInvocation.MyCommand.Path
$required = @('PharmFlow.exe')

if (-not $SkipArtifactCheck) {
    $missing = @($required | Where-Object { -not (Test-Path (Join-Path $folder $_) -PathType Leaf) })
    if ($missing.Count -gt 0) {
        Write-Error ("Portable PharmFlow folder is incomplete. Missing: " + ($missing -join ', ') + ". Download PharmFlow.exe into this folder, then run this launcher again.")
        exit 1
    }
}

$main = Join-Path $folder 'PharmFlow.exe'
if (-not (Test-Path $main -PathType Leaf)) {
    Write-Error "PharmFlow.exe was not found in $folder."
    exit 1
}

$process = Start-Process -FilePath $main -WorkingDirectory $folder -PassThru
Write-Host "Started PharmFlow.exe (PID $($process.Id)) from $folder"
if ($Wait) { Wait-Process -Id $process.Id }