$ErrorActionPreference = "Stop"

$files = @(
  "wizard/dist/CPharm.exe",
  "dist/CPharmAgent.exe",
  "dist/CPharmWatchdog.exe"
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

$agentVersion = Invoke-ExeText ".\dist\CPharmAgent.exe" @("--version")
if ($agentVersion -notmatch "CPharmAgent") { throw "CPharmAgent --version failed: $agentVersion" }
$watchdogVersion = Invoke-ExeText ".\dist\CPharmWatchdog.exe" @("--version")
if ($watchdogVersion -notmatch "CPharmWatchdog") { throw "CPharmWatchdog --version failed: $watchdogVersion" }
$agentHelp = Invoke-ExeText ".\dist\CPharmAgent.exe" @("--help")
if ($agentHelp -notmatch "agent-plan") { throw "CPharmAgent --help failed" }
$watchdogHelp = Invoke-ExeText ".\dist\CPharmWatchdog.exe" @("--help")
if ($watchdogHelp -notmatch "repair-docker") { throw "CPharmWatchdog --help failed" }

Write-Host "All three CPharm EXE artifacts passed release smoke checks."
