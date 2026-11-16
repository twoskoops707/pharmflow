# PEF-39 offline seed. FARM_STOP. Never farm Start. Never swap EXE tip.
# Double-click safe: seed MANTIS.json BEFORE git/API; continue if git fails.
$ErrorActionPreference = 'Continue'
$env:PHARMFLOW_MANTIS_ALLOW_HEADED = '1'
$env:CPHARM_MANTIS_ALLOW_HEADED = '1'

$pfLogs = 'C:\PharmFlow\logs'
$cpLogs = 'C:\CPharm\logs'
New-Item -ItemType Directory -Force -Path $pfLogs, $cpLogs | Out-Null
'1' | Set-Content (Join-Path $pfLogs 'FARM_STOP.flag') -Encoding ascii

$lines = New-Object System.Collections.Generic.List[string]
function Out([string]$s) { $lines.Add($s); Write-Host $s }

function Write-Summary {
  $text = ($lines -join "`r`n") + "`r`n"
  $targets = @(
    (Join-Path $pfLogs 'mantis-pull-last.txt'),
    (Join-Path $PSScriptRoot 'mantis-pull-last.txt'),
    'C:\Users\jsmil\AppData\Local\Cursor\AgentStores\cursor_agent_stores\bc-9ee81b17-48d0-4276-a0eb-01a9897e3155\files\internal\mantis-pull-last.txt'
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

# Tip-145 status only — do not restore/swap EXE.
$expect = 'cbe9fd4dd519b970e74e1ded3f125b80e17a98616c49b2357dec0ef432dd3a39'
try {
  $sha = (Get-FileHash 'C:\PharmFlow\PharmFlow.exe' -Algorithm SHA256).Hash.ToLower()
  Out "DISK_SHA=$sha TIP145=$(if ($sha -eq $expect) { 'yes' } else { 'no' })"
} catch {
  Out "DISK_SHA=unknown TIP145=no"
}

# ---------------------------------------------------------------------------
# 1) ALWAYS seed MANTIS.json into BOTH log roots BEFORE any git/pull/API call.
# ---------------------------------------------------------------------------
$seedCandidates = New-Object System.Collections.Generic.List[string]
foreach ($p in @(
  'C:\Users\jsmil\FamFlow\logs\MANTIS.json',
  'C:\Users\jsmil\Desktop\FamFlow_Transfer_Pack_2026-08-15\secrets\MANTIS.json',
  'C:\CPharm\logs\MANTIS.json',
  'C:\PharmFlow\MANTIS.json',
  'C:\Users\jsmil\Desktop\MANTIS.json',
  'C:\Users\jsmil\Desktop\secrets\MANTIS.json',
  'C:\Users\jsmil\Downloads\MANTIS.json'
)) {
  if ($p) { [void]$seedCandidates.Add($p) }
}
# Desktop copies (one level + Transfer Pack-style secrets folders).
$desktop = 'C:\Users\jsmil\Desktop'
if (Test-Path $desktop) {
  try {
    Get-ChildItem -Path $desktop -Filter 'MANTIS.json' -File -ErrorAction SilentlyContinue |
      ForEach-Object { [void]$seedCandidates.Add($_.FullName) }
    Get-ChildItem -Path $desktop -Directory -ErrorAction SilentlyContinue | ForEach-Object {
      $hit = Join-Path $_.FullName 'MANTIS.json'
      if (Test-Path $hit) { [void]$seedCandidates.Add($hit) }
      $sec = Join-Path $_.FullName 'secrets\MANTIS.json'
      if (Test-Path $sec) { [void]$seedCandidates.Add($sec) }
    }
  } catch {}
}

$destPf = Join-Path $pfLogs 'MANTIS.json'
$destCp = Join-Path $cpLogs 'MANTIS.json'
$src = $null
foreach ($cand in $seedCandidates) {
  if (-not (Test-Path $cand)) { continue }
  # Prefer an external/source file over the destinations themselves.
  if (($cand -eq $destPf) -or ($cand -eq $destCp)) { continue }
  $src = $cand
  break
}
# Fallback: if only a log-root copy exists, mirror it to the other root.
if (-not $src) {
  if (Test-Path $destPf) { $src = $destPf }
  elseif (Test-Path $destCp) { $src = $destCp }
}

$seeded = 'no'
if ($src) {
  try {
    Copy-Item $src $destPf -Force
    Copy-Item $src $destCp -Force
    $seeded = 'yes'
    Out "SEEDED=yes from=$src size=$((Get-Item $destPf).Length)"
  } catch {
    Out "SEEDED=no err=$($_.Exception.Message)"
  }
} else {
  Out 'SEEDED=no reason=no_candidate'
}

# ---------------------------------------------------------------------------
# 2) Best-effort git deploy — NEVER abort on fetch/checkout/pull failure.
# ---------------------------------------------------------------------------
$repoTip = 'unknown'
$repo = 'C:\Users\jsmil\pharmflow'
if (Test-Path (Join-Path $repo '.git')) {
  try {
    Push-Location $repo
    try {
      git fetch origin cursor/mantis-dash-log-root-8d87 2>&1 | Out-Null
      if ($LASTEXITCODE -ne 0) { Out "GIT_FETCH=fail code=$LASTEXITCODE" }
      else { Out 'GIT_FETCH=ok' }
    } catch {
      Out "GIT_FETCH=fail err=$($_.Exception.Message)"
    }
    try {
      git checkout cursor/mantis-dash-log-root-8d87 2>&1 | Out-Null
      if ($LASTEXITCODE -ne 0) { Out "GIT_CHECKOUT=fail code=$LASTEXITCODE" }
      else { Out 'GIT_CHECKOUT=ok' }
    } catch {
      Out "GIT_CHECKOUT=fail err=$($_.Exception.Message)"
    }
    try {
      git pull --ff-only origin cursor/mantis-dash-log-root-8d87 2>&1 | Out-Null
      if ($LASTEXITCODE -ne 0) { Out "GIT_PULL=fail code=$LASTEXITCODE" }
      else { Out 'GIT_PULL=ok' }
    } catch {
      Out "GIT_PULL=fail err=$($_.Exception.Message)"
    }
    try {
      $repoTip = ((git rev-parse --short HEAD) 2>$null | Out-String).Trim()
      if (-not $repoTip) { $repoTip = 'unknown' }
    } catch {
      $repoTip = 'unknown'
    }
    Out "REPO_TIP=$repoTip"
    try {
      New-Item -ItemType Directory -Force -Path 'C:\PharmFlow\scripts','C:\PharmFlow\automation' | Out-Null
      if (Test-Path '.\scripts\farm_operator_dash.py') {
        Copy-Item '.\scripts\farm_operator_dash.py' 'C:\PharmFlow\scripts\farm_operator_dash.py' -Force
        Out 'DEPLOYED farm_operator_dash.py'
      }
      if (Test-Path '.\automation\mantis_fetch.py') {
        Copy-Item '.\automation\mantis_fetch.py' 'C:\PharmFlow\automation\mantis_fetch.py' -Force
        Out 'DEPLOYED mantis_fetch.py'
      }
    } catch {
      Out "REPO_COPY_ERR=$($_.Exception.Message)"
    }
  } catch {
    Out "REPO_DEPLOY_ERR=$($_.Exception.Message)"
    Out "REPO_TIP=$repoTip"
  } finally {
    Pop-Location -ErrorAction SilentlyContinue
  }
} else {
  Out 'REPO_TIP=unknown reason=no_git_repo'
}

# ---------------------------------------------------------------------------
# 3) mantis_pull + status (best-effort; never abort).
# ---------------------------------------------------------------------------
try {
  $null = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8091/api/mantis_pull' -TimeoutSec 180
  Out 'PULL_OK'
} catch {
  Out "PULL_ERR=$($_.Exception.Message)"
}

$mantis = 'fail'
$today = '-'
$clicks = '-'
$impr = '-'
$ecpm = '-'
try {
  $s = Invoke-RestMethod -Uri 'http://127.0.0.1:8091/api/status' -TimeoutSec 30
  $mt = $s.mantis_today
  if ($null -eq $mt) {
    Out 'MANTIS=fail notes=no_mantis_today'
  } else {
    $mantis = 'pass'
    $today = $mt.today
    if ($null -eq $today -or $today -eq '') { $today = $mt.payout_usd }
    $clicks = $mt.clicks
    $impr = $mt.impr
    if ($null -eq $impr) { $impr = $mt.impressions }
    $ecpm = $mt.ecpm
    Out ("MANTIS=pass TODAY={0} CLICKS={1} IMPR={2} ECPM={3}" -f $today, $clicks, $impr, $ecpm)
  }
} catch {
  Out "MANTIS=fail notes=$($_.Exception.Message)"
}

# Flush mid-run so dropfile exists even if ADB hangs.
Out "SUMMARY REPO_TIP=$repoTip SEEDED=$seeded MANTIS=$mantis TODAY=$today CLICKS=$clicks IMPR=$impr ECPM=$ecpm"
Out 'FARM_STOP=1'
Write-Summary

# ---------------------------------------------------------------------------
# 4) ADB: common MuMu ports + known subnet IPs (timed; never hang forever).
# ---------------------------------------------------------------------------
$adbCount = 0
$adb = 'C:\PharmFlow\bundled\adb.exe'
if (-not (Test-Path $adb)) { $adb = 'adb.exe' }
try {
  $job = Start-Job -ScriptBlock {
    param($adbPath)
    & $adbPath kill-server 2>$null
    Start-Sleep 1
    & $adbPath start-server 2>$null
    foreach ($p in @(5555, 5557, 5559, 5561, 5563, 5565, 16384, 16416, 16448, 16480, 16512, 16544)) {
      & $adbPath connect "127.0.0.1:$p" 2>$null | Out-Null
    }
    foreach ($ip in @('10.0.2.187', '10.0.2.109', '10.0.2.167', '10.0.2.215', '10.0.2.95', '10.0.2.105')) {
      & $adbPath connect "${ip}:5555" 2>$null | Out-Null
    }
    Start-Sleep 2
    $online = @((& $adbPath devices 2>$null) | Where-Object { $_ -match '\tdevice$' })
    "ADB=$($online.Count)"
  } -ArgumentList $adb
  $ok = Wait-Job $job -Timeout 45
  if ($ok) {
    $adbLine = Receive-Job $job | Select-Object -Last 1
    if ($adbLine -match 'ADB=(\d+)') { $adbCount = [int]$Matches[1] }
    Out "$adbLine"
  } else {
    Stop-Job $job -ErrorAction SilentlyContinue
    Out 'ADB=timeout'
  }
  Remove-Job $job -Force -ErrorAction SilentlyContinue
} catch {
  Out "ADB_ERR=$($_.Exception.Message)"
}

# Final structured summary (required keys).
Out "SUMMARY REPO_TIP=$repoTip SEEDED=$seeded MANTIS=$mantis TODAY=$today CLICKS=$clicks IMPR=$impr ECPM=$ecpm ADB=$adbCount FARM_STOP=1"
Out "REPO_TIP=$repoTip"
Out "SEEDED=$seeded"
Out "MANTIS=$mantis"
Out "TODAY=$today CLICKS=$clicks IMPR=$impr ECPM=$ecpm"
Out "ADB=$adbCount"
Out 'FARM_STOP=1'
Write-Summary
Out 'WROTE=mantis-pull-last.txt'
