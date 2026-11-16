# PEF-41 post-ADB: stealth fingerprint clean + attach local/cloud + gate status.
# FARM_STOP stays. Never Start farm. Never clear FARM_STOP. Tip-145 SHA report only.
$ErrorActionPreference = 'Continue'

$pfLogs = 'C:\PharmFlow\logs'
$cpLogs = 'C:\CPharm\logs'
New-Item -ItemType Directory -Force -Path $pfLogs, $cpLogs | Out-Null
'1' | Set-Content (Join-Path $pfLogs 'FARM_STOP.flag') -Encoding ascii
# Reinforce stop; do not clear any existing stop flags.
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

# ---------------------------------------------------------------------------
# 1) Tip-145 EXE SHA — report only (never restore/swap).
# ---------------------------------------------------------------------------
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
  $diskSha = 'unknown'
}
Out "DISK_SHA=$diskSha TIP145=$tip145"

# ---------------------------------------------------------------------------
# 2) adb devices count — exit if 0 (do not Start farm).
# ---------------------------------------------------------------------------
$adb = 'C:\PharmFlow\bundled\adb.exe'
if (-not (Test-Path $adb)) {
  $adbCmd = Get-Command adb.exe -ErrorAction SilentlyContinue
  if ($adbCmd) { $adb = $adbCmd.Source } else { $adb = 'adb.exe' }
}

$adbCount = 0
$adbLines = @()
try {
  $raw = & $adb devices 2>$null
  $adbLines = @($raw | Where-Object { $_ -match '\tdevice$' })
  $adbCount = $adbLines.Count
} catch {
  Out "ADB_ERR=$($_.Exception.Message)"
}
Out "ADB=$adbCount"
if ($adbCount -gt 0) {
  foreach ($d in $adbLines) { Out "DEVICE=$($d -replace '\s+', ' ')" }
}

if ($adbCount -le 0) {
  Out 'ERROR=no_adb_devices — reconnect ADB first; refusing stealth/attach (no Start farm)'
  Out 'ATTACH=skipped'
  Out 'STEALTH_OK=unknown FUNDS_OK=unknown PHONE_COUNT=0'
  Out 'GATE=skipped'
  Out 'FARM_STOP=1'
  Out "SUMMARY ADB=0 TIP145=$tip145 STEALTH_OK=unknown FUNDS_OK=unknown PHONE_COUNT=0 ATTACH=skipped FARM_STOP=1"
  Write-Summary
  Out 'WROTE=post-adb-stealth-last.txt'
  exit 2
}

# ---------------------------------------------------------------------------
# 3–5) Python: discover, optional fingerprint audit / gate (read-only),
#      attach_local_and_cloud_phones(apply_stealth) when present — never start_farm.
# ---------------------------------------------------------------------------
$repoCandidates = @(
  'C:\Users\jsmil\pharmflow',
  'C:\PharmFlow',
  'C:\CPharm',
  (Split-Path -Parent $PSScriptRoot)
)
$repoRoot = $null
foreach ($cand in $repoCandidates) {
  if (-not $cand) { continue }
  if ((Test-Path (Join-Path $cand 'tools\farm_start_gate.py')) -or
      (Test-Path (Join-Path $cand 'tools\cloud_connect.py')) -or
      (Test-Path (Join-Path $cand 'wizard\mumu_farm_ops.py'))) {
    $repoRoot = $cand
    break
  }
}
if (-not $repoRoot) { $repoRoot = 'C:\PharmFlow' }
Out "REPO_ROOT=$repoRoot"

$pyCandidates = @(
  'C:\PharmFlow\python\python.exe',
  'C:\PharmFlow\Python\python.exe',
  'C:\Users\jsmil\AppData\Local\Programs\Python\Python312\python.exe',
  'C:\Users\jsmil\AppData\Local\Programs\Python\Python311\python.exe',
  'python',
  'python3'
)
$python = $null
foreach ($p in $pyCandidates) {
  if ($p -eq 'python' -or $p -eq 'python3') {
    $cmd = Get-Command $p -ErrorAction SilentlyContinue
    if ($cmd) { $python = $cmd.Source; break }
  } elseif (Test-Path $p) {
    $python = $p
    break
  }
}
if (-not $python) {
  Out 'ERROR=no_python — cannot run stealth/attach helpers'
  Out 'EXE_BUTTON=Phones deck → Discover & attach phones (apply_stealth); check gate status; do NOT Start farm'
  Out 'FARM_STOP=1'
  Out "SUMMARY ADB=$adbCount TIP145=$tip145 STEALTH_OK=unknown FUNDS_OK=unknown PHONE_COUNT=$adbCount ATTACH=no_python FARM_STOP=1"
  Write-Summary
  Out 'WROTE=post-adb-stealth-last.txt'
  exit 3
}
Out "PYTHON=$python"

$pyCode = @'
import json
import os
import sys
from pathlib import Path

# Hard stop: never import/call start_farm.
os.environ["CPHARM_FARM_STOP"] = "1"
os.environ["PHARMFLOW_FARM_STOP"] = "1"

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "tools"))
sys.path.insert(0, str(root / "wizard"))

out = {
    "ok": False,
    "phone_count": 0,
    "phones": [],
    "stealth_ok": None,
    "funds_ok": None,
    "attach": "skipped",
    "gate": {},
    "audit": {},
    "exe_button": (
        "PharmFlow Control Panel → Phones → Discover & attach phones "
        "(applies stealth). Then check Start-farm gate status. Do NOT Start farm."
    ),
    "notes": [],
}

def emit(k, v):
    print(f"{k}={v}")

# Discover phones (ADB already counted by PowerShell; refresh via helpers when present).
phones = []
try:
    from wizard.preflight_core import discover_adb_phones  # type: ignore

    phones = [str(s).strip() for s in (discover_adb_phones(None, connect_mumu=True) or []) if str(s).strip()]
    out["notes"].append("discover=preflight_core.discover_adb_phones")
except Exception as exc:  # noqa: BLE001
    out["notes"].append(f"discover_preflight_err={exc}")
    try:
        import subprocess

        raw = subprocess.check_output(["adb", "devices"], text=True, errors="replace", timeout=30)
        phones = [ln.split()[0] for ln in raw.splitlines() if "\tdevice" in ln]
        out["notes"].append("discover=adb_devices_fallback")
    except Exception as exc2:  # noqa: BLE001
        out["notes"].append(f"discover_adb_err={exc2}")

out["phones"] = phones
out["phone_count"] = len(phones)
emit("PHONE_COUNT", out["phone_count"])

# Optional fingerprint audit (read-only).
try:
    from wizard.mumu_farm_ops import audit_fingerprint_all  # type: ignore

    if phones:
        audit = audit_fingerprint_all(phones, None)
        out["audit"] = audit if isinstance(audit, dict) else {"raw": str(audit)}
        if isinstance(audit, dict) and "all_clean" in audit:
            out["stealth_ok"] = bool(audit.get("all_clean"))
        out["notes"].append("audit=mumu_farm_ops.audit_fingerprint_all")
    else:
        out["notes"].append("audit=skipped_no_phones")
except Exception as exc:  # noqa: BLE001
    out["notes"].append(f"audit_err={exc}")

# Read-only start gate (never starts farm).
try:
    import farm_start_gate as gate  # type: ignore

    st = gate.evaluate_start_gate(serials=phones or None, apply_stealth_defaults=True)
    out["gate"] = st if isinstance(st, dict) else {"raw": str(st)}
    if isinstance(st, dict):
        if st.get("stealth_ok") is not None:
            out["stealth_ok"] = bool(st.get("stealth_ok"))
        if st.get("funds_ok") is not None:
            out["funds_ok"] = bool(st.get("funds_ok"))
        if st.get("phone_count") is not None:
            out["phone_count"] = int(st.get("phone_count") or out["phone_count"])
        out["notes"].append("gate=farm_start_gate.evaluate_start_gate")
except Exception as exc:  # noqa: BLE001
    out["notes"].append(f"gate_err={exc}")

emit("STEALTH_OK", out["stealth_ok"] if out["stealth_ok"] is not None else "unknown")
emit("FUNDS_OK", out["funds_ok"] if out["funds_ok"] is not None else "unknown")

# Attach local+cloud with apply_stealth when API exists (safe: no start_farm).
attach_fn = None
try:
    import cloud_connect as cc  # type: ignore

    attach_fn = getattr(cc, "attach_local_and_cloud_phones", None)
    if attach_fn:
        out["notes"].append("attach_api=tools.cloud_connect.attach_local_and_cloud_phones")
except Exception as exc:  # noqa: BLE001
    out["notes"].append(f"cloud_connect_import_err={exc}")

if attach_fn is None:
    try:
        # Bridge path when running from a source checkout that exposes the helper.
        from wizard import pharmflow_wizard_bridge as bridge  # type: ignore

        attach_fn = getattr(bridge, "attach_local_and_cloud_phones", None)
        if attach_fn:
            out["notes"].append("attach_api=wizard.pharmflow_wizard_bridge.attach_local_and_cloud_phones")
    except Exception as exc:  # noqa: BLE001
        out["notes"].append(f"bridge_import_err={exc}")

if callable(attach_fn):
    try:
        # Prefer keyword apply_stealth; fall back if signature differs.
        try:
            res = attach_fn(apply_stealth=True)
        except TypeError:
            try:
                res = attach_fn(root=root, apply_stealth=True)
            except TypeError:
                res = attach_fn()
        out["attach"] = "ok" if (isinstance(res, dict) and res.get("ok")) else "fail"
        if isinstance(res, dict):
            if res.get("phones"):
                out["phones"] = list(res.get("phones") or [])
                out["phone_count"] = len(out["phones"])
            if res.get("stealth_ok") is not None:
                out["stealth_ok"] = bool(res.get("stealth_ok"))
            if res.get("stealth") and isinstance(res["stealth"], dict):
                out["audit"] = res["stealth"]
                if "all_clean" in res["stealth"] and out["stealth_ok"] is None:
                    out["stealth_ok"] = bool(res["stealth"].get("all_clean"))
            out["attach_message"] = res.get("message") or res.get("error") or ""
            emit("ATTACH_MSG", (out.get("attach_message") or "")[:240])
        emit("ATTACH", out["attach"])
        # Re-read gate after attach (still read-only).
        try:
            import farm_start_gate as gate2  # type: ignore

            st2 = gate2.evaluate_start_gate(
                serials=out["phones"] or None, apply_stealth_defaults=True
            )
            if isinstance(st2, dict):
                out["gate"] = st2
                out["stealth_ok"] = bool(st2.get("stealth_ok")) if st2.get("stealth_ok") is not None else out["stealth_ok"]
                out["funds_ok"] = bool(st2.get("funds_ok")) if st2.get("funds_ok") is not None else out["funds_ok"]
                out["phone_count"] = int(st2.get("phone_count") or out["phone_count"])
                emit("STEALTH_OK", out["stealth_ok"] if out["stealth_ok"] is not None else "unknown")
                emit("FUNDS_OK", out["funds_ok"] if out["funds_ok"] is not None else "unknown")
                emit("PHONE_COUNT", out["phone_count"])
        except Exception as exc:  # noqa: BLE001
            out["notes"].append(f"gate_after_attach_err={exc}")
        out["ok"] = out["attach"] == "ok"
    except Exception as exc:  # noqa: BLE001
        out["attach"] = "error"
        out["notes"].append(f"attach_err={exc}")
        emit("ATTACH", "error")
        emit("ATTACH_ERR", str(exc)[:240])
        emit("EXE_BUTTON", out["exe_button"])
else:
    out["attach"] = "missing_api"
    emit("ATTACH", "missing_api")
    emit("EXE_BUTTON", out["exe_button"])
    out["notes"].append("Use EXE button: Discover & attach phones")

emit("PHONE_COUNT", out["phone_count"])
emit("STEALTH_OK", out["stealth_ok"] if out["stealth_ok"] is not None else "unknown")
emit("FUNDS_OK", out["funds_ok"] if out["funds_ok"] is not None else "unknown")
for n in out.get("notes") or []:
    emit("NOTE", str(n)[:200])
print("JSON=" + json.dumps({
    "ok": out["ok"],
    "phone_count": out["phone_count"],
    "stealth_ok": out["stealth_ok"],
    "funds_ok": out["funds_ok"],
    "attach": out["attach"],
    "phones": out["phones"][:32],
}, default=str))
print("START_FARM=never")
print("FARM_STOP=1")
'@

$pyFile = Join-Path $env:TEMP 'pef41_post_adb_stealth_attach.py'
Set-Content -Path $pyFile -Value $pyCode -Encoding UTF8

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
  $exeButton = 'Phones deck → Discover & attach phones; do NOT Start farm'
}

if ($attach -eq 'missing_api' -or $attach -eq 'python_err' -or $attach -eq 'error') {
  if (-not $exeButton) {
    $exeButton = 'PharmFlow → Phones → Discover & attach phones (stealth on). Check gate. Do NOT Start farm.'
  }
  Out "EXE_BUTTON=$exeButton"
}

# Re-assert FARM_STOP after Python (helpers must not clear it).
'1' | Set-Content (Join-Path $pfLogs 'FARM_STOP.flag') -Encoding ascii
Out 'FARM_STOP=1'
Out 'START_FARM=never'
Out "SUMMARY ADB=$adbCount TIP145=$tip145 STEALTH_OK=$stealthOk FUNDS_OK=$fundsOk PHONE_COUNT=$phoneCount ATTACH=$attach FARM_STOP=1"
Write-Summary
Out 'WROTE=post-adb-stealth-last.txt'
exit 0
