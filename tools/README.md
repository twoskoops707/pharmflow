# Tools and Windows EXEs

The GitHub Release provides one executable:

- `PharmFlow.exe` — Control Panel for wizard setup, phones, APK testing, sequences, groups, dashboard, and automation. `--agent` and `--watchdog` are the same file.

Install it at `C:\PharmFlow\PharmFlow.exe`. Start that first. The full operator guide is [../docs/EXE_QUICK_START.md](../docs/EXE_QUICK_START.md).

## Unified entrypoint

From the repository root:

```bash
python tools/project_agent.py status
python tools/project_agent.py agent-plan "add a phone health check"
```

The planner is intentionally bounded: it reports context and next steps but does not execute arbitrary agent output.

## Local cloud emulator

The existing Redroid stack is managed through the same entrypoint:

```bash
# Validate compose without changing Docker state
python tools/project_agent.py emulator config

# Preview lifecycle actions (safe default)
python tools/project_agent.py emulator up

# Start/stop only when explicitly requested
python tools/project_agent.py emulator up --apply
python tools/project_agent.py emulator ps --apply
python tools/project_agent.py emulator logs --apply
python tools/project_agent.py emulator down --apply
```

The stack requires Docker with Android binder support and is intended for a Linux host or cloud VM. Windows operators use MuMu and `PharmFlow.exe`; the automation dashboard consumes both through ADB serials.

## Watchdog and connection repair

For the packaged Windows utility, run `PharmFlow.exe --watchdog` from PowerShell in `C:\PharmFlow`. For a source checkout, use the Python commands below.


Run a diagnostic pass against the backend stack and mapped ADB ports:

```bash
python tools/project_agent.py watchdog
```

Repair known Docker/ADB connection issues explicitly:

```bash
python tools/project_agent.py watchdog -- --apply --repair-docker
python tools/project_agent.py watchdog -- --apply --watch --interval 15
```

The watchdog only reconnects configured ADB endpoints and starts the known Compose services. It does not execute arbitrary commands or terminate unrelated processes. Stop a watch loop with `Ctrl+C`.
