# CLAUDE.md

## Operator standing rules (ALWAYS in effect)

1. **Always show the to-do list.** Maintain and display a live to-do list for every task thread — write it at the start, update it as items complete, and show current state on request. Never work "invisibly."
2. **No caps or limits in code.** Never hardcode phone-count ceilings, rate caps, or artificial limits into farm/EXE code.
3. **Never power VMs off via adb.** `adb reboot -p` leaves MuMu ARM VMs unable to restart (see OPS_NOTES 2026-09-10). Restart cycles go through the MuMu UI/manager only.
4. **Host-IP egress is forbidden for farm traffic.** Every phone's traffic (impressions AND billing clicks) leaves through that phone's own exit — never the host IP.
5. **Read the notes first.** Check OPS_NOTES.md, CLAUDE.md (this file), and prior thread context before changing farm/money-path code.
6. **Fix root causes, not symptoms.** No patches over broken behavior; write the code correctly, test it, and only then commit.
7. **No terminal flashing.** Farm child processes launch with CREATE_NO_WINDOW (see automation/no_window.py) — never regress that.
8. **Money is priority #1.** Farm earn-rate outranks everything; verify money is flowing before and after any change.

## Focused watchdog

`tools/cpharm_watchdog.py` is the supported connection-recovery helper. It checks Docker Compose, TCP emulator ports, and ADB connectivity, and only applies known repairs when `--apply` is provided. Use `python tools/project_agent.py watchdog -- --apply --repair-docker` for a one-shot repair or add `--watch` for monitoring.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build

GitHub Actions builds **two** Windows exes on every push to **`main`** (see `.github/workflows/build-wizard.yml`):

| Spec | Output |
|------|--------|
| `wizard/CPharm.spec` | **CPharm.exe** (Home + full wizard + dashboard shell) |
| `wizard/CPharmMuMuSetup.spec` | **CPharmMuMuSetup.exe** (MuMu checklist, fingerprint, browser, launch CPharm) |

Both attach to the same [GitHub Release](https://github.com/twoskoops707/cpharm/releases) tag `wizard-<run_number>`.

There is no local PyInstaller build on Linux — CI runs on `windows-latest` only.

**Operator / agent handoff:** `docs/AGENT_HANDOFF_2026-07-04.md`

## Syntax check (quick local validation)

```bash
python3 -m py_compile wizard/setup_wizard.py
python3 -m py_compile wizard/cpharm_desktop.py
python3 -m py_compile automation/dashboard.py
python3 -m py_compile automation/tor_manager.py
python3 -m py_compile wizard/cpharm_mumu_setup.py
python3 -m py_compile wizard/mumu_setup_core.py
python3 -m py_compile wizard/browser_setup.py
python3 -m py_compile automation/mumu_fingerprint.py
```

## Run the dashboard server locally

```bash
cd automation && python dashboard.py
```

Dashboard serves on port `8080` (HTTP) and `8081` (WebSocket), defined in `automation/config.py`.

## Architecture

### Dual-exe split (MuMu first-run)

| Component | Role |
|-----------|------|
| `wizard/mumu_setup_core.py` | Setup GO: adb, fingerprint, `browser_setup`, groups seed |
| `wizard/browser_setup.py` | Browser detect/sideload; optional Chromium snapshot download |
| `wizard/preflight_core.py` | Checklist Steps 1–7 for setup UI |
| `automation/mumu_fingerprint.py` | VM + ADB fingerprint; `ensure_fingerprint_before_browse` before each `open_url` |
| `automation/browser_adb.py` | Runtime browser order (MuMu Browser before Chrome) |

Wizard **does not** re-run full fingerprint by default — copy points users to **CPharmMuMuSetup.exe** first.

### Wizard UI vs automation server

**1. CPharm (wizard module)** (`wizard/setup_wizard.py`, ~12k lines — large single module)
- Single-file tkinter GUI (**CPharm**) that walks users through first-time setup
- Nine primary screens (`CPharmWizard.PAGES`): Welcome → Prerequisites → Android Studio → Phone Farm → Boot → Automation → Sequence Generator → Groups → Launch (`wizard/setup_wizard.py`). Extra page classes (e.g. `WebpePage`, deprecated `PlayStorePage`) exist outside that linear flow (not in `PAGES`).
- All pages extend `PageBase(tk.Frame)` and are shown by `CPharmWizard(tk.Tk)`
- Phone sequences are stored **per-phone** inside groups: `group["phones"][serial]["steps"]` — not at the group level
- Downloads: Java, Python, Android cmdline-tools, Tor expert bundle, CPharm repo ZIP
- `_urlretrieve(url, dest, hook)` wraps `urllib.request.urlretrieve` with per-attempt socket timeout plus bounded retries/backoff for transient download failures
- Per-phone sequence editing uses `PerPhoneSequenceEditor` (defined at top of file, line ~114)
- ARM64 Windows detection: checks `PROCESSOR_ARCHITEW6432` env var + registry; ARM64 emulator needs arm64-v8a system image

**2. Automation Server** (`automation/dashboard.py`)
- Raw asyncio TCP HTTP server (no Flask/Django) + WebSocket broadcast
- All automation uses ADB device serials (not indices)
- Groups of phones run in parallel threads; phones within a group stagger via `stagger_secs`
- `state["groups"]` is a list of group dicts; each group has `phones: {serial: {"steps": [...]}}`
- Wizard smoke/CI: `wizard/smoke_frozen_imports.py`, `wizard/smoke_browser_builder.py`, and `python -m unittest discover -s wizard -p "test_sequence_generator*.py"` (currently `test_sequence_generator_edge_cases.py`)

### Key automation modules

| File | Purpose |
|------|---------|
| `automation/config.py` | Ports (8080/8081), path constants (APK_DIR, REC_DIR, TOR_DIR), EMULATOR_PORTS list |
| `automation/tor_manager.py` | One Tor process per phone; SOCKS port = 9050 + phone_idx; Android HTTP proxy via `settings put global http_proxy` |
| `automation/scheduler.py` | Daily hit quota per phone — generates N random fire-times across 24h; step types: open_url, tap, wait, swipe, keyevent, close_app, rotate_identity, clear_cookies, type_text, full_reset |
| `automation/teach.py` | Record `getevent -lt` from one phone; replay via `sendevent` on others |
| `automation/playstore.py` | Legacy Play Store automation (not used for DabFlow browser testing) |

### State schema

Shared `state` dict in wizard:
```python
state = {
    "phones":     [{"serial": str, "name": str, ...}],   # booted phones
    "groups":     [{"name": str, "phones": {serial: {"steps": [...]}},
                    "stagger_secs": int, "repeat": int, "repeat_forever": bool}],
    "cpharm_dir": str,    # path to cloned repo root
    "python_cmd": str,    # "python" or "python3"
    "sdk_path":   str,    # Android SDK root
    "avds":       [...],  # list of AVD names
}
```

### GitHub Actions / branch notes

- Default branch on `origin` is **`main`** (`git remote show origin` → “HEAD branch: main”).
- Local checkouts can drift: **`refs/remotes/origin/HEAD`** is a *symbolic ref* set when the remote was first added, so it can keep pointing at an old convenience branch (e.g. `arm64-emulator-fix`) even after GitHub's default branch is changed. To resync without force-pushing anything, run:

  ```bash
  git fetch origin --prune
  git remote set-head origin -a
  ```

  After that `git symbolic-ref refs/remotes/origin/HEAD` should print `refs/remotes/origin/main`.
- The wizard’s GitHub ZIP fallback downloads **`main`** (`CPHARM_ZIP_URL` → `.../refs/heads/main.zip`). Legacy branch name **`master`** may still exist on some forks or old clones.
- Build triggers: push to **`main`** builds **both** exes and publishes GitHub Release (not Actions artifacts as default download).
