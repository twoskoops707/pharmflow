$ErrorActionPreference = "Stop"

# Single-EXE pipeline: one windowed binary (CPharm.exe) bundles the GUI wizard
# plus the agent (--agent) and watchdog (--watchdog) combined-mode entrypoints.
# The EXE is console=False, so stdout is not pipe-capturable from PowerShell;
# the release contract is a correct PROCESS EXIT CODE per CLI mode.
$files = @(
  "wizard/dist/CPharm.exe"
)
foreach ($file in $files) {
  if (!(Test-Path -LiteralPath $file)) { throw "Missing build artifact: $file" }
  if ((Get-Item -LiteralPath $file).Length -lt 100000) { throw "Artifact is unexpectedly small: $file" }
}

function Invoke-Exe([string]$path, [string[]]$arguments) {
  $p = Start-Process -FilePath $path -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
  if ($p.ExitCode -ne 0) {
    throw "$(Split-Path $path -Leaf) $($arguments -join ' ') exited with code $($p.ExitCode)"
  }
  Write-Host "  ok: $(Split-Path $path -Leaf) $($arguments -join ' ')"
}

$exe = (Resolve-Path ".\wizard\dist\CPharm.exe").Path

Write-Host "Smoke-checking single EXE ($exe):"
Invoke-Exe $exe @("--version")
Invoke-Exe $exe @("--watchdog", "--help")
Invoke-Exe $exe @("--agent", "--version")

Write-Host "CPharm.exe (single EXE with bundled agent + watchdog) passed release smoke checks."
