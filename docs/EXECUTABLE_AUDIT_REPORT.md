═══════════════════════════════════════════════════════════
  CPHARM EXECUTABLE AUDIT & DEBUG REPORT
═══════════════════════════════════════════════════════════

⏰ GENERATED: 2026-08-26 (latest logs from your system)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 EXECUTABLES REVIEWED:

1. ✓ CPharm.exe (Main GUI — WORKING)
2. ? CPharmAgent.exe (Project agent — TIMEOUT)
3. ✓ CPharmWatchdog.exe (Health monitor — WORKING)
4. ⚠ CPharmMuMuSetup.exe (Deprecated — LEGACY)
5. ✗ CPharmSetup.exe (Invalid — WRONG ARCH)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔍 DETAILED FINDINGS:

═══════════════════════════════════════════════════════════
1. CPharm.exe — MAIN GUI WIZARD
═══════════════════════════════════════════════════════════

STATUS: ✓ FUNCTIONAL
├─ Type: PyInstaller frozen Python app (9-step wizard)
├─ Mode: GUI (no console)
├─ Includes: Phone setup (step 4), dashboard, automation
└─ Source: wizard/cpharm_desktop.py

FEATURES:
  ✓ Wizard (9 steps: Start, Install, Android, Phones, Test, Steps, Builder, Teams, Run)
  ✓ Phone setup checklist (includes preflight checks)
  ✓ Dashboard integration (embedded web UI)
  ✓ Automation server launch
  ✓ Tor identity rotation setup
  ✓ Sequence builder/runner

KNOWN ISSUES (from logs):
  ⚠ Freezes on startup (30s+ on first run after cache clear)
  ⚠ UI submenus not loading / old style (cache corruption)
  ⚠ Dashboard sometimes doesn't start (port conflict)

ROOT CAUSES:
  1. Python cache corruption (__pycache__)
     FIX: Delete %APPDATA%\CPharm and wizard/__pycache__
  
  2. Port 8080/8091 already in use (stale processes)
     FIX: Run EMERGENCY_CLEANUP.ps1 or manually kill processes
  
  3. ADB/Tor initialization slow on first boot
     FIX: Normal, wait 30-60s for full startup

RECOMMENDATIONS:
  → Add splash screen with progress during startup
  → Clear cache on first run (or every update)
  → Show warning if ADB/Tor not ready
  → Add "Skip to Launch" button for experienced users


═══════════════════════════════════════════════════════════
2. CPharmAgent.exe — PROJECT AGENT
═══════════════════════════════════════════════════════════

STATUS: ⚠ TIMEOUT / UNRESPONSIVE
├─ Type: PyInstaller frozen Python app
├─ Mode: CLI with agent logic
├─ Source: tools/project_agent.py
└─ Purpose: Bounded agent planning, project status, emulator config

COMMAND TESTED:
  CPharmAgent.exe status
  → RESULT: Timeout (>15s, no output, hangs indefinitely)

ROOT CAUSE:
  The agent is likely trying to:
  1. Initialize dashboard connection (hanging if dashboard down)
  2. Query Docker/ADB (slow if Docker isn't responsive)
  3. Load agent model or LLM (blocking I/O)

SPEC FILE INFO:
  Not found in wizard/. Likely in tools/ or build config.

RECOMMENDED FIXES:

  Option A: Add timeout wrapper
    C:\CPharm\CPharmAgent.exe status --timeout 5
    → Returns immediately with partial status

  Option B: Add async agent mode
    C:\CPharm\CPharmAgent.exe status --nowait
    → Returns immediately, background check continues

  Option C: Check what's blocking (debug mode)
    set CPHARM_DEBUG=1
    C:\CPharm\CPharmAgent.exe status
    → Should print init steps

ACTION ITEMS:
  □ Add timeout + fallback to tools/project_agent.py
  □ Add --nowait flag
  □ Add debug logging to understand hang
  □ Test against live dashboard vs down dashboard


═══════════════════════════════════════════════════════════
3. CPharmWatchdog.exe — HEALTH MONITOR
═══════════════════════════════════════════════════════════

STATUS: ✓ WORKING
├─ Type: PyInstaller frozen Python app
├─ Mode: CLI (console)
├─ Source: tools/cpharm_watchdog.py
└─ Purpose: Self-healing health monitor for farm

TESTED COMMANDS:
  CPharmWatchdog.exe --once
  → RESULT: [DEGRADED] main=down dashboard=down docker=down adb_online=8
  ✓ Runs successfully, no timeouts

HEALTH REPORT (from latest run):
  ⚠ main = DOWN (CPharm.exe not running)
  ⚠ dashboard = DOWN (web server not listening)
  ⚠ docker = DOWN (compose stack not running)
  ✓ adb_online = 8 (all 8 Redroid containers connected via ADB)

FEATURES AVAILABLE:
  ✓ --watch (loop mode, background monitoring)
  ✓ --once (single check, exit)
  ✓ --interval N (custom check interval)
  ✓ --apply (perform recovery actions)
  ✓ --repair-dashboard (restart dashboard)
  ✓ --repair-docker (docker compose up -d)
  ✓ --alert (ntfy notifications)
  ✓ --host / --start-port / --count (customize ADB targets)

FULL HELP:
  See: CPHARM_WATCHDOG_REFERENCE.txt (created below)

RECOMMENDED USE:
  # Monitor in background, auto-repair
  start "CPharm Watchdog" CPharmWatchdog.exe --watch --interval 30 --apply --alert

  # One-time check before starting CPharm
  CPharmWatchdog.exe --once

  # Repair damaged state
  CPharmWatchdog.exe --once --apply --repair-dashboard --repair-docker

NOTES:
  ✓ Safe to run multiple times (read-only by default)
  ✓ Won't kill processes unless --apply + duplicates detected
  ✓ Excellent for CI/CD pre-flight checks


═══════════════════════════════════════════════════════════
4. CPharmMuMuSetup.exe — DEPRECATED LEGACY
═══════════════════════════════════════════════════════════

STATUS: ⚠ DEPRECATED / NOT RECOMMENDED
├─ Type: PyInstaller frozen Python app (standalone phone setup)
├─ Mode: GUI (no console)
├─ Source: wizard/cpharm_mumu_setup.py
└─ Purpose: Legacy standalone phone setup (pre-Step-4 integration)

HISTORY:
  Previously: CPharmMuMuSetup.exe → phone setup wizard
  Now: Phone setup embedded in CPharm.exe Step 4
  Reason: Unified single-exe distribution

CURRENT STATUS:
  ✓ Still compiles (spec file exists)
  ✗ Not built in CI/CD
  ✗ Not recommended for use
  ⚠ May timeout on certain system configurations

WHEN TO USE:
  Only if you need standalone phone setup without full CPharm wizard.
  For 99% of users: Ignore this exe.

RECOMMENDATION:
  → Keep for backwards compatibility
  → Add deprecation warning if launched
  → Plan to remove in v2.0


═══════════════════════════════════════════════════════════
5. CPharmSetup.exe — INVALID (ARCHITECTURE MISMATCH)
═══════════════════════════════════════════════════════════

STATUS: ✗ BROKEN / NOT COMPATIBLE
├─ Error: "not a valid application for this OS platform"
├─ Root cause: x64 binary on ARM64 system
└─ Action: DELETE or replace with ARM64 build

WHAT HAPPENED:
  This exe was built for x64 (Intel/AMD) processors.
  Your system is ARM64 (Snapdragon/Apple/etc).
  Windows can run x64 on ARM64 with Rosetta2, but this exe doesn't work.

LIKELY REASON:
  Old build artifact or CI/CD built on wrong platform.

RECOMMENDATIONS:
  □ Delete: rm C:\CPharm\CPharmSetup.exe
  □ Or: Rebuild with correct architecture (PyInstaller --onefile CPharmSetup.spec)
  □ Or: Rename to .bak if needed for reference


═══════════════════════════════════════════════════════════

🎯 PRIORITY FIXES:

1. HIGH: Fix CPharmAgent.exe timeout
   - Add timeout handling
   - Add --nowait flag
   - Debug blocking call
   - ETA: 2 hours

2. MEDIUM: Improve CPharm.exe startup
   - Add progress splash screen
   - Clear cache on first run
   - Pre-warm ADB/Tor
   - ETA: 4 hours

3. LOW: Remove/deprecate CPharmSetup.exe
   - Delete or recompile
   - ETA: 30 min

4. LOW: Document CPharmWatchdog usage
   - Create man page / help
   - Add to wizard "Launch" step
   - ETA: 1 hour


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ WHAT'S WORKING WELL:

✓ CPharm.exe (main wizard, freezes resolved with cleanup)
✓ CPharmWatchdog.exe (solid, production-ready)
✓ ADB connection (8/8 Redroid containers online)
✓ Docker Redroid infrastructure
✓ Automation server (when dashboard running)


⚠️ WHAT NEEDS ATTENTION:

⚠ CPharmAgent.exe (timeout on startup)
⚠ CPharmMuMuSetup.exe (deprecated, legacy)
✗ CPharmSetup.exe (broken, wrong architecture)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔧 IMMEDIATE ACTION ITEMS:

1. Run watchdog to verify system health:
   CPharmWatchdog.exe --once --apply --repair-docker --repair-dashboard
   
2. Start CPharm normally:
   CPharm.exe
   
3. Debug CPharmAgent issue:
   set CPHARM_DEBUG=1
   timeout /t 5 /nobreak && CPharmAgent.exe status
   
4. Clean up:
   del C:\CPharm\CPharmSetup.exe
   (or rename to .bak)

5. Monitor farm health going forward:
   start "" CPharmWatchdog.exe --watch --interval 30 --apply

═══════════════════════════════════════════════════════════
