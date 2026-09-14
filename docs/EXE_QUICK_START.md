# PharmFlow Windows EXE Quick Start

The GitHub Release ships **one** program: `PharmFlow.exe`. Put it in `C:\PharmFlow\`.

Phone setup, the project agent, and the watchdog are the same binary. There is no separate setup EXE, agent EXE, or watchdog EXE.

| How you start it | Use it for |
|---|---|
| `PharmFlow.exe` | Control Panel: wizard, phone setup, **Start farm**, dash **`:8091`** |
| `PharmFlow.exe --watchdog` | ADB / connection check (same file) |
| `PharmFlow.exe --agent` | Project diagnostics (same file) |

Settings and logs stay under `C:\CPharm\` (not the EXE folder).

## Mantis money farm (most operators)

1. Start your phones yourself (MuMu, AVD, or a real device). The EXE does not open or close emulators.
2. Install **FarmBrowser** on each phone.
3. Open **PharmFlow.exe** → **Start farm**.
4. Open **`http://127.0.0.1:8091/`** for live money/status.
5. **Stop farm** in PharmFlow when shutting down. Closing the window does not tear down phone exits.

Do **not** start `ensure_farm_24x7.py` or `run_farm_354.py` from a terminal — **Start farm** in PharmFlow.exe owns the unison stack.

Coordination with FreeBuff agent: `C:\CPharm\logs\AGENT_UNISON.json`

---

## Wizard / groups mode

1. Download **PharmFlow.exe** into `C:\PharmFlow\`.
2. Install **MuMu Player**. Create phones. In each phone turn **ON** ADB / USB debugging. Stuck? PharmFlow → **Phones (step 4)** has the checklist and **Set up my phones**.
3. Double-click `PharmFlow.exe`. Click **Next** through **Install** and **Android** until **Phones**.
4. Continue to **Test (step 5)** and open the site on a phone.
5. **Run (step 9)** → **Start service** → **Run all groups**, or **Start automation**.

The wizard dashboard is `http://localhost:8080`. The money dashboard is `http://127.0.0.1:8091/`.

## Watchdog

From PowerShell in `C:\PharmFlow`:

```powershell
.\PharmFlow.exe --watchdog
.\PharmFlow.exe --watchdog --apply
.\PharmFlow.exe --agent
```

`--apply` is required before the watchdog changes anything. It does not replace **Start farm**.

## If a button appears to do nothing

- Close older PharmFlow windows and launch the newest `C:\PharmFlow\PharmFlow.exe`.
- Check the error banner or the Run page log.
- For dashboard actions, start the service and wait for “Server running.”
- Editor windows must be visible. If a file dialog is behind the Control Panel, Alt-Tab to it.
- `PharmFlow.exe --watchdog` reports farm, ADB, and dashboard state. It is not a second program.
