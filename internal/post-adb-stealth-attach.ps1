# PEF-41 post-ADB: stealth fingerprint + attach + gate status.
# FARM_STOP stays. Never Start farm. Tip-145 SHA report only.
$ErrorActionPreference = 'Continue'

$pfLogs = 'C:\PharmFlow\logs'
$cpLogs = 'C:\CPharm\logs'
New-Item -ItemType Directory -Force -Path $pfLogs, $cpLogs | Out-Null
'1' | Set-Content (Join-Path $pfLogs 'FARM_STOP.flag') -Encoding ascii
if (Test-Path $cpLogs) {
  '1' | Set-Content (Join-Path $cpLogs 'FARM_STOP.flag') -Encoding ascii -ErrorAction SilentlyContinue
}

$lines = New-Object System.Collections.Generic.List[string]
function Out([string]$s) { $lines.Add($s); Write-Host $s }

function Write-Summary {
  $text = ($lines -join "`r`n") + "`r`n"
  $targets = @(
    (Join-Path $pfLogs 'post-adb-stealth-last.txt'),
    (Join-Path $PSScriptRoot 'post-adb-stealth-last.txt'),
    'C:\Users\jsmil\AppData\Local\Cursor\AgentStores\cursor_agent_stores\bc-9ee81b17-48d0-4276-a0eb-01a9897e3155\files\internal\post-adb-stealth-last.txt'
  )
  foreach ($t in $targets) {
    try {
      $dir = Split-Path -Parent $t
      if ($dir -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
      }
      [System.IO.File]::WriteAllText($t, $text)
    } catch {}
  }
}

Out 'PEF41=post-adb-stealth-attach'
Out 'FARM_STOP=1'
Out 'START_FARM=never'

$expect = 'cbe9fd4dd519b970e74e1ded3f125b80e17a98616c49b2357dec0ef432dd3a39'
$diskSha = 'unknown'
$tip145 = 'no'
try {
  if (Test-Path 'C:\PharmFlow\PharmFlow.exe') {
    $diskSha = (Get-FileHash 'C:\PharmFlow\PharmFlow.exe' -Algorithm SHA256).Hash.ToLower()
    if ($diskSha -eq $expect) { $tip145 = 'yes' }
  } else {
    $diskSha = 'missing'
  }
} catch {
  $diskSha = 'err'
}
Out "DISK_SHA=$diskSha TIP145=$tip145"

$adb = if (Test-Path 'C:\PharmFlow\bundled\adb.exe') { 'C:\PharmFlow\bundled\adb.exe' }
  elseif (Test-Path 'C:\Program Files\Netease\MuMuPlayerARM\shell\adb.exe') { 'C:\Program Files\Netease\MuMuPlayerARM\shell\adb.exe' }
  else { 'adb.exe' }
Out "ADB_BIN=$adb"
$raw = & $adb devices 2>$null
$devs = @($raw | Where-Object { $_ -match '\tdevice$' })
$adbCount = $devs.Count
Out "ADB=$adbCount"
foreach ($d in $devs) { Out "SERIAL=$d" }

if ($adbCount -lt 1) {
  Out 'ERROR=ADB=0 — refuse stealth/attach until phones connect'
  Out 'EXE_BUTTON=Phones deck -> Discover and attach phones; do NOT Start farm'
  Out 'FARM_STOP=1'
  Out "SUMMARY ADB=0 TIP145=$tip145 STEALTH_OK=unknown FUNDS_OK=unknown PHONE_COUNT=0 ATTACH=refused FARM_STOP=1"
  Write-Summary
  Out 'WROTE=post-adb-stealth-last.txt'
  exit 2
}

$repoRoot = 'C:\Users\jsmil\pharmflow'
if (-not (Test-Path $repoRoot)) { $repoRoot = 'C:\PharmFlow' }
Out "REPO_ROOT=$repoRoot"

$pyCandidates = @(
  'C:\PharmFlow\python\python.exe',
  'C:\Users\jsmil\AppData\Local\Programs\Python\Python312\python.exe',
  'C:\Users\jsmil\AppData\Local\Programs\Python\Python311\python.exe',
  'C:\Python312\python.exe',
  'C:\Python311\python.exe',
  'py',
  'python',
  'python3'
)
$python = $null
foreach ($p in $pyCandidates) {
  if ($p -eq 'python' -or $p -eq 'python3' -or $p -eq 'py') {
    $cmd = Get-Command $p -ErrorAction SilentlyContinue
    if ($cmd) { $python = $cmd.Source; break }
  } elseif (Test-Path $p) {
    $python = $p
    break
  }
}
if (-not $python) {
  Out 'ERROR=no_python'
  Out 'EXE_BUTTON=Phones deck -> Discover and attach phones; do NOT Start farm'
  Out 'FARM_STOP=1'
  Out "SUMMARY ADB=$adbCount TIP145=$tip145 STEALTH_OK=unknown FUNDS_OK=unknown PHONE_COUNT=$adbCount ATTACH=no_python FARM_STOP=1"
  Write-Summary
  exit 3
}
Out "PYTHON=$python"

$pyFile = Join-Path $PSScriptRoot 'post-adb-stealth-attach.py'
if (-not (Test-Path $pyFile)) {
  $pyFile = 'C:\Users\jsmil\AppData\Local\Cursor\AgentStores\cursor_agent_stores\bc-9ee81b17-48d0-4276-a0eb-01a9897e3155\files\internal\post-adb-stealth-attach.py'
}
Out "PY_FILE=$pyFile"

$stealthOk = 'unknown'
$fundsOk = 'unknown'
$phoneCount = $adbCount
$attach = 'unknown'
$exeButton = ''

try {
  $pyOut = & $python $pyFile $repoRoot 2>&1
  foreach ($line in @($pyOut)) {
    $s = "$line"
    Out $s
    if ($s -match '^STEALTH_OK=(.+)$') { $stealthOk = $Matches[1].Trim() }
    if ($s -match '^FUNDS_OK=(.+)$') { $fundsOk = $Matches[1].Trim() }
    if ($s -match '^PHONE_COUNT=(\d+)') { $phoneCount = [int]$Matches[1] }
    if ($s -match '^ATTACH=(.+)$') { $attach = $Matches[1].Trim() }
    if ($s -match '^EXE_BUTTON=(.+)$') { $exeButton = $Matches[1].Trim() }
  }
} catch {
  Out "PYTHON_ERR=$($_.Exception.Message)"
  $attach = 'python_err'
  $exeButton = 'Phones deck -> Discover and attach phones; do NOT Start farm'
}

if ($attach -eq 'missing_api' -or $attach -eq 'python_err' -or $attach -eq 'error') {
  if (-not $exeButton) {
    $exeButton = 'PharmFlow -> Phones -> Discover and attach phones (stealth on). Check gate. Do NOT Start farm.'
  }
  Out "EXE_BUTTON=$exeButton"
}

'1' | Set-Content (Join-Path $pfLogs 'FARM_STOP.flag') -Encoding ascii
Out 'FARM_STOP=1'
Out 'START_FARM=never'
Out "SUMMARY ADB=$adbCount TIP145=$tip145 STEALTH_OK=$stealthOk FUNDS_OK=$fundsOk PHONE_COUNT=$phoneCount ATTACH=$attach FARM_STOP=1"
Write-Summary
Out 'WROTE=post-adb-stealth-last.txt'
exit 0
