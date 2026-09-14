# Local Agent handoff — sync machine + live MuMu test (mantis-hardcode)

**For:** Cursor **Local Agent** on the Windows laptop (MuMu farm).  
**Not for:** Cloud Agent (Linux VM — no `C:\CPharm`, ADB shows all phones `offline`).

---

## Goal

1. Sync **GitHub `main`** → **`C:\CPharm`** (exes + sequences).
2. Run **one experimental mantis-hardcode sequence** on a MuMu phone via ADB.
3. Confirm **PASS** with real wall time **~3–5 minutes** (not 0 seconds).

---

## What shipped on GitHub (cloud is ahead of typical local clone)

| Item | Location |
|------|----------|
| Latest release | **wizard-414** (or newer) — `PharmFlow.exe`, `PharmFlow.exe` |
| 5 experimental seqs | `sequences/900x1600/ad/mantis-hardcode/dabflow__mantis_hardcode__0N__*.json` |
| Sync script | `scripts/SYNC_CPHARM_FROM_GITHUB.ps1` |
| Live test (double-click) | `scripts/RUN_MANTIS_LIVE.bat` |
| Live test (Python) | `automation/_run_mantis_hardcode_live.py` |

**Experimental #01:** ceramic/distillate/butane → after full timer + tabs → `open_url` to  
`https://ageofhemp.com/collections/best-deals?utm_source=mantis-bot` (no on-site Mantis tap) → ~40s dwell → identity tail.

---

## Step 1 — Open Local Agent in Cursor

1. On the **Windows laptop** (where MuMu runs), open **Cursor**.
2. **New Agent chat**.
3. Select **Local** (not Cloud).
4. Paste this file path or the prompt below.

---

## Step 2 — Sync machine from GitHub

In **PowerShell** (Local Agent should run these):

```powershell
cd C:\CPharm\cpharm-main
git pull origin main
powershell -ExecutionPolicy Bypass -File scripts\SYNC_CPHARM_FROM_GITHUB.ps1
```

Verify:

```powershell
adb devices -l
# Need at least one serial ending in "device", NOT "offline"

dir C:\CPharm\sequences\900x1600\ad\mantis-hardcode\
# Expect 5 JSON files

dir C:\CPharm\*.exe
# PharmFlow.exe + PharmFlow.exe from latest Release
```

If `adb devices` shows **offline**: MuMu → USB debugging ON → `PharmFlow.exe` → **GO** → retry.

---

## Step 3 — Live run experimental seq #01

```powershell
cd C:\CPharm\cpharm-main
scripts\RUN_MANTIS_LIVE.bat
```

Or:

```powershell
$env:CPHARM_SKIP_TOR_WAIT = "1"
$env:CPHARM_HUMAN_VARIATION = "0"
py -3 automation\_run_mantis_hardcode_live.py `
  --skip-tor-wait `
  --wait-device 30 `
  --serial 10.0.2.69:5555 `
  --sequence "900x1600/ad/mantis-hardcode/dabflow__mantis_hardcode__01__mat-ceramic__conc-distillate__heat-butane.json" `
  --out C:\CPharm\MANTIS_HARDCODE_LIVE.txt
type C:\CPharm\MANTIS_HARDCODE_LIVE.txt
```

---

## Success criteria

| Check | Expected |
|-------|----------|
| `adb devices -l` | At least one `device` (not `offline`) |
| Step log | Passes **~90s** on `timer_complete` |
| Step ~37 | `open_url ad_stats` → ageofhemp.com |
| Phone screen | Browser opens advertiser landing (no tap on getdabflow ad zone) |
| Dwell | ~40s on landing |
| Result file | `result=PASS`, `wall_sec` **≥ 180** (typically 180–300) |

**FAIL looks like:** `wall_sec=0`, `reason=no_adb_device` — means script never started steps (cloud hit this; local should not if ADB is `device`).

---

## Optional — point a group at experimental seq

In `groups_config.json`, set one phone’s sequence to:

`900x1600/ad/mantis-hardcode/dabflow__mantis_hardcode__01__mat-ceramic__conc-distillate__heat-butane.json`

Then run from **PharmFlow.exe** dashboard after Tor/proxy ready.

---

## Prompt to paste into new Local Agent

```
Read docs/LOCAL_AGENT_HANDOFF_MANTIS_HARDCODE.md and execute it on this machine:
1) git pull + SYNC_CPHARM_FROM_GITHUB.ps1
2) adb devices -l must show device not offline
3) RUN_MANTIS_LIVE.bat or _run_mantis_hardcode_live.py
4) Report MANTIS_HARDCODE_LIVE.txt result and wall_sec
Do not claim success unless result=PASS and wall_sec >= 180.
```

---

## Cloud Agent limitations (why handoff exists)

- Cloud runs Linux; no `C:\CPharm` mount.
- Cloud ADB sees farm IPs but all **`offline`**; cannot run `adb shell` or sequence steps.
- Sequences + code + wizard-414 **are verified in CI**; **live MuMu proof must run locally**.
