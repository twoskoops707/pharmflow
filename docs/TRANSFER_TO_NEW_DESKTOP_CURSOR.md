# Move PharmFlow farm to another Windows PC (Cursor sets up · **PharmFlow.exe runs**)

**Read this first. Follow this order. Do not invent alternatives.**

| Who | Job |
|-----|-----|
| **Cursor** (on the new PC) | **Setup / diagnose only** — MuMu x64, secrets, install `PharmFlow.exe`, help wizard, verify ADB + dash |
| **`C:\PharmFlow\PharmFlow.exe`** | **THE ONLY FARM RUNNER** — user clicks **Start farm** / **Stop farm** / **Open dashboard** |
| **MuMu Player x64** | The phones |

### Cursor must NEVER do these (farm via Python)

Do **not** start, schedule, or “bring up” the farm with:

- `python` / `py` + `scripts\ensure_farm_24x7.py`
- `scripts\run_farm_354.py` / `run_farm_cycles.py`
- `scripts\start_hidden.py …`
- `scripts\run_mantis_inject_proxies.py` as the farm owner
- any “start the farm from the terminal” recipe

Those scripts exist for **inside** PharmFlow after **Start farm**, or for old docs. On a new desktop, **if PharmFlow.exe is not running Start farm, you are doing it wrong.**

### Also forbidden

- **Android Studio / AVD** — not the farm  
- BlueStacks / LDPlayer / Nox — not supported  
- MuMu **ARM** on Intel/AMD  
- Stopping at **1 phone** — need **4–6**  
- Declaring “done” with **no** `http://127.0.0.1:8091/`  
- Copying PharmFlow `.py` over `C:\PharmFlow\` and calling the EXE fixed  

---

## Roles in one picture

```
YOU + Cursor (setup ONLY — never Start farm from Python)
        │
        ├─ install MuMu Player x64
        ├─ download PharmFlow.exe → C:\PharmFlow\PharmFlow.exe   ← REQUIRED PRODUCT
        ├─ apply secrets zip into C:\PharmFlow\
        └─ open PharmFlow.exe → wizard → N phones online
                │
                ▼
     OPERATOR clicks in PharmFlow.exe UI:
                Start farm
                │
                ├─ farm worker + uniqueness locks
                ├─ inject / Tor / remediator
                └─ dashboard http://127.0.0.1:8091/   ← REQUIRED
```

---

## Paste into Cursor on the NEW PC (first chat)

```text
COMPLETE COMPUTER INSTALL + SETUP of the PharmFlow/PharmFlow phone farm on this x64 Windows PC.

You are SETUP ONLY. You do NOT run the farm from Python/Cursor.

Read first (after clone):
  docs/SITUATION_2026-08-16.md
  docs/TRANSFER_TO_NEW_DESKTOP_CURSOR.md
  docs/START_HERE.md
Follow those exactly. If any older doc says ensure_farm / run_farm_354 / start_hidden, IGNORE it.

THE ONLY FARM RUNNER IS C:\PharmFlow\PharmFlow.exe
Human clicks Start farm / Stop farm / Open dashboard in that EXE.
Dashboard MUST be http://127.0.0.1:8091/

========== HARD NEVER ==========
- Android Studio / AVD / BlueStacks / LDPlayer / Nox / MuMu ARM
- py/python scripts\ensure_farm_24x7.py
- run_farm_354.py / run_farm_cycles.py / start_hidden.py to start the farm
- run_mantis_inject_proxies.py as farm owner
- Building a Cursor/Python farm and calling setup done
- Skipping PharmFlow.exe
- Stopping at 1 phone
- Declaring done with no :8091 dash
- Copying PharmFlow .py over C:\PharmFlow\ and calling the EXE updated
- Disabling unique-seq / isolation / draw-without-replacement
If dash is down: tell the HUMAN to click Start farm in PharmFlow.exe. Do NOT spawn ensure_farm.

========== DO THIS IN ORDER ==========
0) Machine: Intel/AMD x64, 16GB RAM min (32GB preferred), SSD, never-sleep on AC.
1) Install Git (winget Git.Git). Clone:
     git clone https://github.com/twoskoops707/PharmFlow.git %USERPROFILE%\PharmFlow
     cd %USERPROFILE%\PharmFlow && git checkout main && git pull
   Open that folder in Cursor. Re-read the three docs above from THIS clone.
2) Install MuMu Player x64/Global from https://www.mumuglobal.com
   Typical: C:\Program Files\Netease\MuMuPlayer or MuMuPlayerGlobal
   Set user env PHARMFLOW_MUMU_ROOT if PharmFlow cannot find it.
3) Create C:\PharmFlow\bundled, logs, apks, certs.
   Optional: copy %USERPROFILE%\PharmFlow\bundled_adb\* → C:\PharmFlow\bundled\
4) Download PharmFlow.exe from GitHub Releases wizard-64 or NEWER (app 1.4.9+):
     https://github.com/twoskoops707/PharmFlow/releases
   Place at C:\PharmFlow\PharmFlow.exe  — if this file is missing, setup has FAILED.
5) Apply the private secrets zip (USB/email — NEVER commit):
     MANTIS.json → C:\PharmFlow\logs\
     pharmflow_state\* → C:\PharmFlow\
     farm_runtime_overrides.json → C:\PharmFlow\logs\
     certs → C:\PharmFlow\certs\
   Edit pharmflow_config.json / saved_paths.json:
     mumu_root = THIS PC MuMu x64 path (not MuMuPlayerARM)
     phone_count = 6 (or 4–6)
     adb_path = C:\PharmFlow\bundled\adb.exe
   Delete stale serial maps: C:\PharmFlow\logs\adb_live_serials.json and ADB_SERIAL_MAP.lock.json
6) Launch C:\PharmFlow\PharmFlow.exe. Wizard: detect MuMu x64, 6 phones, USB-debug tip once, install tools/browsers, create/start phones.
7) Verify: C:\PharmFlow\bundled\adb.exe devices  → multiple "device" lines (4–6), not one emulator.
8) TELL THE HUMAN: in PharmFlow.exe click Start farm, then Open dashboard.
9) Verify http://127.0.0.1:8091/ loads and shows phones. Chromium inject not stuck on :0/null.

========== DONE ONLY IF ALL TRUE ==========
- MuMu x64 installed, 4–6 instances running
- ADB N/N device via C:\PharmFlow\bundled\adb.exe
- C:\PharmFlow\PharmFlow.exe running with Start farm ACTIVE (not idle wizard)
- http://127.0.0.1:8091/ loads
- Old PC farm STOPPED (one PC farms Mantis per day)

Do not pip-install a Python farm stack as the runner. Python is optional for diagnose only.
Uniqueness locks stay ON.
```

---

## Machine requirements (new PC)

| Need | Spec |
|------|------|
| CPU | Intel or AMD **x64** |
| RAM | 16 GB min, **32 GB** preferred for 6 phones |
| Disk | SSD, **≥ 80 GB** free |
| Power | Never sleep while plugged in |
| Apps | Cursor + Git; Python optional (diagnose only — **not** to run the farm) |
| Emulator | **MuMu Player x64 / Global** — https://www.mumuglobal.com |
| Product | **PharmFlow.exe** from https://github.com/twoskoops707/PharmFlow/releases |

---

## Step-by-step (new PC)

### 1) Cursor workspace (source + docs only)

```powershell
winget install Git.Git --accept-package-agreements
git clone https://github.com/twoskoops707/PharmFlow.git $env:USERPROFILE\PharmFlow
cd $env:USERPROFILE\PharmFlow
git checkout main
git pull
```

Open **`$env:USERPROFILE\PharmFlow`** in Cursor. Paste the prompt above.  
**Do not** start farm scripts from this repo.

### 2) MuMu Player x64 ONLY

1. Download **MuMu Player** Windows **x64 / Global** from [mumuglobal.com](https://www.mumuglobal.com).  
2. Typical roots: `C:\Program Files\Netease\MuMuPlayer` or `...\MuMuPlayerGlobal`  
3. If needed:

```powershell
[System.Environment]::SetEnvironmentVariable(
  'PHARMFLOW_MUMU_ROOT',
  'C:\Program Files\Netease\MuMuPlayer',
  'User'
)
```

**Do not install Android Studio for this farm.**

### 3) Install **PharmFlow.exe** (mandatory — this is the product)

1. Open https://github.com/twoskoops707/PharmFlow/releases  
2. Download **PharmFlow.exe** from **wizard-64 or newer** (app 1.4.9+)  
3. Place at **`C:\PharmFlow\PharmFlow.exe`**  

```powershell
New-Item -ItemType Directory -Force C:\PharmFlow\bundled, C:\PharmFlow\logs, C:\PharmFlow\apks, C:\PharmFlow\certs | Out-Null
# Optional: ADB helpers from repo if Release did not already place them
Copy-Item -Force $env:USERPROFILE\PharmFlow\bundled_adb\* C:\PharmFlow\bundled\ -ErrorAction SilentlyContinue
```

**If this step is skipped, setup has failed.** Cursor must not “compensate” by running Python farm scripts.

### 4) Apply the private secrets zip (email / USB)

```powershell
$pack = "$env:USERPROFILE\Desktop\PharmFlow_Transfer_Pack_YYYY-MM-DD"  # your unzipped folder
Copy-Item -Force "$pack\secrets\MANTIS.json" C:\PharmFlow\logs\
Copy-Item -Force "$pack\pharmflow_state\*" C:\PharmFlow\
Copy-Item -Force "$pack\pharmflow_state\farm_runtime_overrides.json" C:\PharmFlow\logs\ -ErrorAction SilentlyContinue
Copy-Item -Force "$pack\certs\*" C:\PharmFlow\certs\ -Recurse -ErrorAction SilentlyContinue
```

Edit `C:\PharmFlow\pharmflow_config.json` / `saved_paths.json`:

- `mumu_root` → MuMu **x64** on **this** PC  
- `phone_count` → **6** (or 4–6)  
- `adb_path` → `C:\PharmFlow\bundled\adb.exe`  

```powershell
Remove-Item C:\PharmFlow\logs\adb_live_serials.json, C:\PharmFlow\logs\ADB_SERIAL_MAP.lock.json -ErrorAction SilentlyContinue
```

### 5) Run **PharmFlow.exe** wizard (not Python)

1. Double-click **`C:\PharmFlow\PharmFlow.exe`**  
2. Wizard: detect MuMu x64 → **6 phones** → tools/browsers/phones  
3. Confirm:

```powershell
C:\PharmFlow\bundled\adb.exe devices
```

Multiple `device` lines required.

### 6) Human starts the farm **inside PharmFlow**

In the **PharmFlow.exe** window (not Cursor terminal):

1. **Start farm**  
2. **Open dashboard** → `http://127.0.0.1:8091/`  

| Check | Pass |
|-------|------|
| MuMu | x64; 4–6 instances |
| ADB | N/N `device` |
| **PharmFlow.exe** | Process running; **Start farm** active |
| Dash | `:8091` loads |
| Proxies | not stuck on `:0` / `null` |
| Old PC | farm **stopped** |

### 7) Daily use

1. MuMu on  
2. **`C:\PharmFlow\PharmFlow.exe` → Start farm**  
3. Dash `:8091`  
4. **Stop farm** in PharmFlow when needed  

Cursor does not press Start from the shell.

---

## Cutover — stop the OLD machine

When the new PC has PharmFlow Start farm + dash healthy:

```powershell
# Stop old python dual-stack if any (old PC only)
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -match 'ensure_farm|run_farm_354|run_farm_cycles|run_mantis_inject|farm_operator'
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\PharmFlowEnsure24x7.bat" -ErrorAction SilentlyContinue
```

Also quit old **PharmFlow.exe** / Stop farm on the old PC. Only **one** PC farms Mantis per day.

---

## What Cursor may do vs must not do

| Cursor MAY | Cursor must NOT |
|------------|-----------------|
| Install MuMu x64, Git | Install Android Studio for the farm |
| Download/install **PharmFlow.exe** to `C:\PharmFlow\` | Run `ensure_farm` / `run_farm_354` / `start_hidden` to start farming |
| Apply secrets; fix `mumu_root` | Leave farm on 1 phone |
| Help PharmFlow wizard / ADB | Skip PharmFlow.exe and farm from Python |
| Ask human to click **Start farm** in PharmFlow | Call setup “done” with no dash / no PharmFlow |
| Read `C:\PharmFlow\logs\` | Disable unique-seq; live-patch `.py` over EXE |

### Code fixes later

Frozen EXE = bundled code. Fix in repo → push `main` → **Build PharmFlow Wizard** → new Release **PharmFlow.exe** → replace file → human **Start farm** again.

---

## Links

| What | Path / URL |
|------|------------|
| This doc | `docs/TRANSFER_TO_NEW_DESKTOP_CURSOR.md` |
| Situation (money + EXE) | [SITUATION_2026-08-16.md](SITUATION_2026-08-16.md) |
| Operator short | [START_HERE.md](START_HERE.md) |
| Releases (**install PharmFlow.exe here**) | https://github.com/twoskoops707/PharmFlow/releases/tag/wizard-64 |
| Dash | http://127.0.0.1:8091/ |

---

## Older docs (do not follow for farm start)

- [`MIGRATE_FARM_TO_INTEL_CURSOR_LAB.md`](MIGRATE_FARM_TO_INTEL_CURSOR_LAB.md) — **superseded**; its `ensure_farm_24x7.py` section is **wrong** for new desktops.  
- Any guide that says `py scripts\run_farm_354.py` to start the farm — **wrong**; use **PharmFlow.exe → Start farm**.  

**If anything conflicts with this file, this file wins.**
