# PharmFlow / PharmFlow — Agent Handoff

**Pickup:** [`SITUATION_2026-08-16.md`](SITUATION_2026-08-16.md) → [`TRANSFER_TO_NEW_DESKTOP_CURSOR.md`](TRANSFER_TO_NEW_DESKTOP_CURSOR.md)

## Repos

| Repo | Role |
|------|------|
| **[twoskoops707/PharmFlow](https://github.com/twoskoops707/PharmFlow)** | Automation source, CI **Build PharmFlow Wizard**, unison stack, canonical phone map |
| **[twoskoops707/pharmflow](https://github.com/twoskoops707/pharmflow)** | Shipped **PharmFlow.exe** releases, **FarmBrowser** APK (`farmbrowser/`), operator sequences under `sequences/` |

FreeBuff agent works primarily from **pharmflow** + live `C:\PharmFlow\` data. Cursor pushes source → CI → replace `C:\PharmFlow\PharmFlow.exe`.

## THE FARM RUNNER IS PharmFlow.exe

| Role | Does |
|------|------|
| **Cursor** | MuMu, secrets, install EXE, diagnose logs, push fixes |
| **`C:\PharmFlow\PharmFlow.exe`** | **Start farm** / Stop / Open dashboard **`:8091`** |
| **MuMu x64** | Phones (8 canonical money VMs) |
| **FreeBuff** | SSP/mantis/money lane — `scripts/agent_unison_freebuff_tick.py`, ntfy `twskoops` |

**Never** start farming with:

`ensure_farm_24x7.py` · `run_farm_354.py` · `run_farm_cycles.py` · `start_hidden.py`

Those are **lanes inside** unison after **Start farm**, not Cursor/terminal owners.

## Unison stack (Start farm)

`scripts/pharmflow_unison_supervisor.py` — four deduped lanes:

1. `run_farm_354.py` — sequences / Path3
2. `pharmflow_stealth_guard.py` — tor, inject, ADB, FarmBrowser
3. `farm_watchdog.py` — evidence monitor
4. `agent_unison_freebuff_loop.py` — SSP paying, flat-$, path3 OK

Coordination board: `C:\PharmFlow\logs\AGENT_UNISON.json`

## FarmBrowser (money browser)

- Package: `com.farmbrowser.stealth.debug` (debug) / `com.farmbrowser.stealth` (release)
- APK built in **pharmflow** repo: `farmbrowser/`
- Sequences: `preferred_browser` + `browser_tag: farmbrowser`
- **Do not** lock allow-list to farmbrowser-only without matching sequence tags (empties pools)

## Config SSOT

All `PHARMFLOW_*` money rails: **`automation/pharmflow_farm_config.py`** — not `farm_runtime_overrides.json`.

## Code → EXE

Fix → push **`main`** → CI green → Release **PharmFlow.exe** → replace `C:\PharmFlow\PharmFlow.exe` → **Start farm**.

Verify before claiming done: `git push`, CI job, Release asset — not “files edited locally.”

## Uniqueness

`.cursor/rules/farm-unique-sequences.mdc` + `.cursor/rules/pharmflow-exe-owns-farm.mdc`

Ignore any doc that says “python owns the farm” or starts the farm from the terminal.
