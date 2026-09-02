$ErrorActionPreference = "Stop"

# Single-EXE pipeline: one binary (CPharm.exe) bundles the GUI wizard plus the
# agent (--agent) and watchdog (--watchdog) combined-mode entrypoints.
$files = @(
  "wizard/dist/CPharm.exe"
)
foreach ($file in $files) {
  if (!(Test-Path -LiteralPath $file)) { throw "Missing build artifact: $file" }
  if ((Get-Item -LiteralPath $file).Length -lt 100000) { throw "Artifact is unexpectedly small: $file" }
}

function Invoke-ExeText([string]$path, [string[]]$arguments) {
  $output = & $path @arguments 2>&1 | Out-String
  if ($LASTEXITCODE -ne 0) { throw "$path $($arguments -join ' ') failed with exit code $LASTEXITCODE" }
  return $output
}

$exe = ".\wizard\dist\CPharm.exe"

$appVersion = Invoke-ExeText $exe @("--version")
if ($appVersion -notmatch "CPharm") { throw "CPharm.exe --version failed: $appVersion" }

$watchdogHelp = Invoke-ExeText $exe @("--watchdog", "--help")
if ($watchdogHelp -notmatch "repair-docker") { throw "CPharm.exe --watchdog --help failed" }

$agentVersion = Invoke-ExeText $exe @("--agent", "--version")
if ($agentVersion -notmatch "CPharmAgent") { throw "CPharm.exe --agent --version failed: $agentVersion" }

Write-Host "CPharm.exe (single EXE with bundled agent + watchdog) passed release smoke checks."
