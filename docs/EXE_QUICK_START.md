# CPharm Windows EXE Quick Start

The GitHub Release contains three separate programs. Download all three into the same folder, such as `C:\CPharm\`.

| File | Use it for | When to run |
|---|---|---|
| `CPharm.exe` | Wizard, MuMu setup, **Start farm**, Mantis operator dash **`:8091`**, sequences | Run this first |
| `CPharmAgent.exe` | Read-only project status and bounded planning | Diagnostics only |
| `CPharmWatchdog.exe` | ADB, inject, emulator health; known connection recovery | When phones drop offline |

## Mantis money farm (most operators)

1. Install **MuMu Player x64**, create portrait phones, enable USB debugging.
2. Build/install **FarmBrowser** from `farmbrowser/` (or use cached APK under `apks/`).
3. Open **CPharm.exe** → **Start farm**.
4. Open **`http://127.0.0.1:8091/`** for live money/status.
5. **Stop farm** in CPharm when shutting down.

Do **not** start `ensure_farm_24x7.py` or `run_farm_354.py` from a terminal — **Start farm** in the EXE spawns the unison stack.

Coordination with FreeBuff agent: `C:\CPharm\logs\AGENT_UNISON.json`

---

## Wizard / groups mode (legacy 9-step UI)

Big picture first: you download three tiny programs, open the **green** one, make a few phones, and press **Play**. That's the whole job.

1. **Get the programs.** From the Release, download **all three** EXEs: `CPharm.exe`, `CPharmAgent.exe`, `CPharmWatchdog.exe`. Drop them into **one** folder (like `C:\CPharm\`).
2. **Make the phones.** Install **MuMu Player** (a free program). Open it → top-right **multi-window** icon → **+ New Instance** → make **3** phones. In each phone: open Settings and turn **ON** ADB / USB debugging. (Stuck? CPharm → **Phones (step 4)** has a full checklist.)
3. **Open CPharm.** Double-click `CPharm.exe`. Click **Next** through **Install** and **Android** until you reach **Phones (step 4)**. If your phones don't appear, click **Auto-Connect All Phones**.
4. **Test a website.** Continue to **Test (step 5)**. Site loads → good, phones work.
5. **Press GO.** Go to **Run (step 9)** → **Start server** → wait for *Server running* → **Run all groups**. Watch the big live **farm status** panel.

That's the happy path. The dashboard opens at `http://localhost:8080`. If anything looks odd, scroll down — the **watchdog**, **troubleshooting**, and **cloud** sections below are all still here (they didn't go anywhere).

## First-time setup

1. Install MuMu and create portrait **Phone** instances at `900 × 1600`.
2. Enable USB debugging on each instance.
3. Put all three EXEs in one folder.
4. Open `CPharm.exe`.
5. Complete **Phones** setup and confirm the phones appear as `device` in ADB.
6. Use **Install APK** when testing an APK on connected phones.
7. Use **Steps → Edit default sequence** or **Builder** to create a sequence.
8. Use **Groups** to assign phones and saved sequences.
9. Open **Run**, click **Start server**, wait for “Server running,” then click **Run all groups**.
10. Use **CPharmWatchdog.exe** only for connection diagnostics or known repairs.

## Watchdog commands

The watchdog is a console EXE. From PowerShell in the CPharm folder:

```powershell
.\CPharmWatchdog.exe
.\CPharmWatchdog.exe --apply --repair-docker --host 127.0.0.1 --count 1
.\CPharmWatchdog.exe --apply --watch --interval 15
```

`--apply` is required for reconnect/recovery actions. Start with `--count 1`; scale only after one emulator is stable.

## Cloud/Redroid note

Redroid requires Linux Binder support. Docker Desktop/WSL may validate the Compose file but still cannot run Redroid reliably. Use MuMu on Windows, or run Redroid on a Linux host/cloud VM. Do not repeatedly restart Docker or launch eight privileged emulators while diagnosing WSL crashes.

## If a button appears to do nothing

- Close older CPharm processes and launch the newest `CPharm.exe`.
- Check the visible error banner or the Run page live log.
- For dashboard actions, start the service first and wait for “Server running.”
- For editor windows, check that Windows did not place the window behind the main app.
- Run `CPharmWatchdog.exe` and inspect the ADB/Docker result.
- If Docker crashes WSL, stop scaling and use MuMu or a Linux Redroid host.
