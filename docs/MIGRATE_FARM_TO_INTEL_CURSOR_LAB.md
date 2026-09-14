> **Superseded:** the product is a single `PharmFlow.exe` in `C:\PharmFlow\` (`--watchdog`, `--agent`, phone setup in-process). Data still lives under `C:\PharmFlow\`. Ignore EXE names below.

# Move PharmFlow farm → older Intel PC (“New Cursor Lab”)

> **SUPERSEDED — DO NOT FOLLOW THE PYTHON FARM STEPS IN THIS FILE.**  
> Use **[TRANSFER_TO_NEW_DESKTOP_CURSOR.md](TRANSFER_TO_NEW_DESKTOP_CURSOR.md)** only.  
> **PharmFlow.exe** runs the farm (Start farm in the UI).  
> **Never** run `ensure_farm_24x7.py` / `run_farm_354.py` from Cursor to start farming on a new PC.  
> Success = `C:\PharmFlow\PharmFlow.exe` + 4–6 MuMu x64 phones + dash `:8091`.  
> Section “### 7) Start farm 24×7” below with `ensure_farm_24x7.py` is **WRONG for transfer — ignore it.**

Source today was SKOOPS; target Intel + MuMu x64 + **PharmFlow.exe**.

Transfer options:

| Channel | Location |
|---------|----------|
| **Email (preferred)** | Zip on Desktop: `PharmFlow_Farm_Migration_Intel.zip` — Outlook draft to your Gmail; also folder under OneDrive if needed |
| OneDrive backup | `OneDrive\2026 Zion\PharmFlow_Farm_Migration_2026-07-27\` |
| Paste prompt for Intel Cursor | Desktop: `INTEL_CURSOR_PASTE_PROMPT.txt` |

MuMu on Intel: `C:\Program Files\Netease\MuMuPlayer` (set `PHARMFLOW_MUMU_ROOT` if detect fails).

---

## Goals

1. Farm runs on the Intel box (ADB phones, Tor, inject proxies, uniqueness locks).
2. Cursor stays signed in as your **New Cursor Lab** (agent worker / local chat on that machine).
3. Easy transfer: **GitHub** for code, **email zip** for secrets/state; SKOOPS is source of truth until cutover, then stop ARM keepers.

---

## Do not copy blindly

| Thing | Why |
|-------|-----|
| ARM MuMu serials (`10.0.2.133` etc.) | New Intel VMs get **new** `10.0.2.x` addresses |
| `MuMuPlayerARM` install | Intel needs **MuMu Player** / Global **x64** |
| Huge `farm_354.log` | Optional; not required to run |
| `farm_used_stems_*.json` | Optional: copy only if you want to continue the same draw-without-replacement day |

Uniqueness rules stay on: concurrent unique-seq lock, draw-without-replacement, per-seq isolation, stagger.

---

## A. On the Intel PC (once)

### 1) Accounts & Cursor Lab

1. Sign into **Windows** with the same Microsoft account that syncs OneDrive (or wait for the pack folder).
2. Install **Cursor**, sign in with the **same Cursor account** as on SKOOPS.
3. Keep Cursor open on that machine (or at least the agent worker) so it is the always-on lab.
4. Optional remote control from phone/laptop: in a terminal on the Intel box, start Cursor’s agent worker for this machine (name it e.g. `CursorLab-Intel`) and bookmark the `cursor.com/agents` URL from the CLI output.

### 2) Python + repo

```powershell
# Prefer a real Python 3.11–3.14 install (not Store stub)
py -3 --version

git clone https://github.com/twoskoops707/PharmFlow.git C:\Users\jsmil\PharmFlow
cd C:\Users\jsmil\PharmFlow
py -3 -m pip install -r requirements.txt psutil tzlocal
```

If your Windows username is not `jsmil`, either create the same path or update the Startup `.bat` and any hardcoded `C:\Users\jsmil\PharmFlow` paths.

### 3) MuMu x64 (Intel)

1. Install **MuMu Player** for Windows x64 from [mumuglobal.com](https://www.mumuglobal.com) (not the ARM build).
2. Typical root: `C:\Program Files\Netease\MuMuPlayer` or `MuMuPlayerGlobal`.
3. Create **4** Android instances (match resolution you use on farm, usually 900×1600).
4. Boot all four; confirm ADB:

```powershell
New-Item -ItemType Directory -Force C:\PharmFlow\bundled | Out-Null
# After clone, copy ADB if needed:
Copy-Item -Force C:\Users\jsmil\PharmFlow\bundled_adb\* C:\PharmFlow\bundled\ -ErrorAction SilentlyContinue
C:\PharmFlow\bundled\adb.exe devices
```

You should see four `10.0.2.<n>:5555 device` lines. **Write them down** — they replace the ARM serials.

### 4) Apply OneDrive pack

```powershell
$pack = "$env:USERPROFILE\OneDrive\2026 Zion\PharmFlow_Farm_Migration_2026-07-27"
# If OneDrive path differs, find the folder named PharmFlow_Farm_Migration_2026-07-27

New-Item -ItemType Directory -Force C:\PharmFlow\logs, C:\Users\jsmil\PharmFlow\logs | Out-Null

Copy-Item -Force "$pack\secrets\MANTIS.json" C:\Users\jsmil\PharmFlow\logs\MANTIS.json
Copy-Item -Force "$pack\pharmflow_state\*" C:\PharmFlow\ -Exclude *.json
# Prefs / groups go at PharmFlow root; runtime JSON under logs:
Copy-Item -Force "$pack\pharmflow_state\desktop_prefs.json" C:\PharmFlow\
Copy-Item -Force "$pack\pharmflow_state\groups.json" C:\PharmFlow\
Copy-Item -Force "$pack\pharmflow_state\pharmflow_config.json" C:\PharmFlow\
Copy-Item -Force "$pack\pharmflow_state\saved_paths.json" C:\PharmFlow\
Copy-Item -Force "$pack\pharmflow_state\farm_runtime_overrides.json" C:\PharmFlow\logs\
Copy-Item -Force "$pack\pharmflow_state\mantis_today_state.json" C:\PharmFlow\logs\
Copy-Item -Force "$pack\pharmflow_state\NTFY_NO_AUTO_REPLY.flag" C:\PharmFlow\logs\
```

Or run the helper (after pull):

```powershell
cd C:\Users\jsmil\PharmFlow
powershell -ExecutionPolicy Bypass -File scripts\apply_farm_migration_pack.ps1
```

### 5) Remap phones (critical)

Edit `C:\PharmFlow\desktop_prefs.json` and `C:\PharmFlow\logs\farm_runtime_overrides.json`:

- Set `phone_order` / `PHARMFLOW_FARM_PHONES` to `vm0.gmadoa,…` matching how many live phones you run (usually 4).
- Do **not** paste old ARM `10.0.2.*` into configs that auto-discover from live ADB — prefer live discovery.
- If anything still hardcodes serials, update after `adb devices`.

Set MuMu root if auto-detect fails:

```powershell
$env:PHARMFLOW_MUMU_ROOT = 'C:\Program Files\Netease\MuMuPlayer'   # adjust if needed
```

### 6) Browsers + sequences

```powershell
cd C:\Users\jsmil\PharmFlow
$env:PYTHONPATH = 'C:\Users\jsmil\PharmFlow'
py -3 scripts\sideload_farm_browsers.py --download-only
py -3 scripts\sideload_farm_browsers.py --install
# Sequences: either already in the git clone, or regenerate:
# py -3 scripts\generate_dabflow_sequences.py
```

### 7) Start farm 24×7 — **WRONG FOR NEW DESKTOPS — IGNORE**

~~Do not run `ensure_farm_24x7.py` or Startup bat.~~  
**Correct:** install `C:\PharmFlow\PharmFlow.exe` → click **Start farm**.  
See [TRANSFER_TO_NEW_DESKTOP_CURSOR.md](TRANSFER_TO_NEW_DESKTOP_CURSOR.md).

### 8) Smoke checks

```powershell
C:\PharmFlow\bundled\adb.exe devices
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -match 'ensure_farm|run_farm_354|run_farm_cycles|run_mantis_inject|farm_operator|process_janitor'
} | ForEach-Object { if ($_.CommandLine -match '([\w\-]+\.py)') { $_.ProcessId; $Matches[1] } }
Get-Content C:\PharmFlow\logs\farm_354.log -Tail 40
```

Healthy: inject proxies up, unique Tor exits, Path1/2/3 progressing, no two phones on the same sequence identity.

---

## B. On SKOOPS (ARM) at cutover

1. **Stop** farm keepers so Mantis clicks/impr don’t double from two machines:

```powershell
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -match 'ensure_farm|run_farm_354|run_farm_cycles|run_mantis_inject|farm_operator|process_janitor|ntfy_readonly'
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

2. Remove or rename `Startup\PharmFlowEnsure24x7.bat` on ARM so it does not come back after reboot.
3. Leave MuMu/Tor alone if you still want this laptop as a spare — just don’t run two farms against the same Mantis day budget.

---

## C. What OneDrive pack contains

| Path in pack | Purpose |
|--------------|---------|
| `secrets\MANTIS.json` | Mantis login file (gitignored; never commit) |
| `pharmflow_state\farm_runtime_overrides.json` | Caps, dwell-related waits, Path3 cap, visits/ads |
| `pharmflow_state\desktop_prefs.json` | Farm prefs template (remap phones) |
| `pharmflow_state\groups.json` | Groups / steps |
| `pharmflow_state\NTFY_NO_AUTO_REPLY.flag` | Keeps ntfy read-only |
| `startup\PharmFlowEnsure24x7.bat` | Login autostart |
| `MANIFEST.json` | Source host + checklist |

Code stays on **GitHub** (`PharmFlow` `main`). Re-pack anytime on SKOOPS:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\pack_farm_migration.ps1
```

---

## D. “New Cursor Lab” always on

1. Intel PC: power settings → never sleep while plugged in; screen can turn off.
2. Cursor installed + signed in; open workspace `C:\Users\jsmil\PharmFlow`.
3. Startup: `PharmFlowEnsure24x7.bat` (farm) + optional Cursor shortcut.
4. From your phone or Snapdragon: use Cursor agents / remote worker against **CursorLab-Intel**, not the ARM box, after cutover.
5. Same GitHub account: `git pull` on Intel after pushes from either machine.

---

## E. Questions that block a hands-on finish from this chat

Reply with whatever you know:

1. **Same Windows username** on Intel (`jsmil`) or different?
2. Is **OneDrive** already signed in and is the pack folder visible?
3. Is **MuMu x64** already installed? Path?
4. Can you open **Cursor on the Intel PC** on `C:\Users\jsmil\PharmFlow` so the next message can be answered *there* (I can then apply + verify ADB/farm live)?
5. Cutover: **stop ARM farm the same day** Intel goes live (recommended)?
