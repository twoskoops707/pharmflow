═══════════════════════════════════════════════════════════
  CPHARMWATCHDOG REFERENCE
═══════════════════════════════════════════════════════════

📋 WHAT IS CPHARMWATCHDOG?

Self-healing health monitor for the CPharm farm. Continuously checks:
  ✓ Is CPharm.exe main process alive?
  ✓ Is Dashboard HTTP (8080) answering?
  ✓ Are ADB cloud/emulator endpoints reachable?
  ✓ Is Docker Redroid stack running?
  ✓ Duplicate processes (kill stale instances)

Safety model:
  • Nothing killed except known duplicates
  • Read-only by default (use --apply to enable recovery)
  • Never modifies filesystem outside logs
  • Optional ntfy notifications on state changes

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 QUICK START:

# One-time health check
CPharmWatchdog.exe --once

# Run in background, auto-repair
CPharmWatchdog.exe --watch --interval 30 --apply --alert

# Check every 60s, repair dashboard if down
CPharmWatchdog.exe --watch --interval 60 --repair-dashboard

# Verify specific ADB ports
CPharmWatchdog.exe --once --host 127.0.0.1 --start-port 5555 --count 8

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📖 COMMAND REFERENCE:

Basic Modes:
  --once              Single pass, exit (default)
  --watch             Loop forever, check every --interval seconds
  --interval SECONDS  Check interval (default: 15)
                      Recommended: 30-60 for production

Recovery Actions (use with --apply):
  --apply             Enable recovery actions (default: dry-run mode)
  --repair-dashboard  Respawn dashboard if HTTP is down
  --repair-docker     Restart Docker compose stack if down
  --service NAME      Limit Docker repair to one service
  
  Examples:
    CPharmWatchdog.exe --once --apply --repair-dashboard
    CPharmWatchdog.exe --watch --apply --repair-docker

Process Reaper (built-in, every --reap-interval in --watch mode):
  Kills dead/used/unneeded/stale processes as soon as they are discovered:
    • duplicate adb fork-server instances (only one may own port 5037)
    • duplicate dashboard.py / duplicate farm worker scripts (keeps newest)
    • dead-parent python helpers outside the farm allowlist
    • Tor instances with a missing or duplicated config (never touches
      farm-owned/adopted Tor, so income is protected)
  Detection always runs and is logged every sweep; actual kills require --apply.
  --reap-only         Run a single maintenance sweep and exit (reaper, plus
                      stealth exit-IP check when --stealth is given)
  --no-reap           Disable the kill pass (detection still logged)
  --reap-interval N   Min seconds between sweeps (default: 60)
  
  Examples:
    CPharmWatchdog.exe --reap-only                    # report stale processes
    CPharmWatchdog.exe --reap-only --apply            # kill stale immediately
    CPharmWatchdog.exe --watch --apply                # monitor + kill every 60s

Stealth / exit-IP uniqueness (--stealth):
  Verifies every phone holds a UNIQUE Tor exit IP via the dashboard's
  /api/stealth/verify endpoint and rotates duplicates when the farm runs
  unattended. This runs on the SAME sweep as the process reaper, so stealth
  recovery and stale-process cleanup share one 60s maintenance cadence
  (the dashboard endpoint is NOT hit every check interval).

  --stealth           Enable exit-IP uniqueness verification/rotation
                      (runs with each reaper sweep; needs dashboard up)

  Examples:
    CPharmWatchdog.exe --watch --apply --stealth        # sweep every 60s: reap + stealth
    CPharmWatchdog.exe --reap-only --stealth            # single maintenance tick
    CPharmWatchdog.exe --reap-only --stealth --apply    # kill stale + rotate dupes now

Monitoring:
  --alert             Send ntfy notifications on state changes
                      (up → down, down → up transitions)
                      Requires: ntfy.sh account or self-hosted instance

ADB Configuration:
  --host HOST         ADB target host (default: 127.0.0.1)
  --start-port PORT   ADB start port (default: 5555)
  --count COUNT       Number of ADB ports to check (default: 8)
  
  Examples:
    CPharmWatchdog.exe --once --host 127.0.0.1 --start-port 5555 --count 8
    CPharmWatchdog.exe --once --host 127.0.0.1 --start-port 16384 --count 10  (MuMu)

Diagnostic:
  -h, --help          Show help
  --version           Show version

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔍 HEALTH REPORT FORMAT:

Status line:
  [HEALTHY] main=up dashboard=up docker=up adb_online=8
  [DEGRADED] main=down dashboard=down docker=down adb_online=8
  [CRITICAL] main=down dashboard=down docker=down adb_online=0

Components:
  main = Is CPharm.exe running?
  dashboard = Is HTTP server (8080) responding?
  docker = Are Redroid containers up?
  adb_online = How many ADB devices are online?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🚀 PRODUCTION SETUPS:

Option 1: Manual checks
  Run before starting CPharm:
    CPharmWatchdog.exe --once --apply --repair-docker
    CPharm.exe

Option 2: Background monitoring (Task Scheduler)
  Create scheduled task:
    Program: C:\CPharm\CPharmWatchdog.exe
    Arguments: --watch --interval 30 --apply --alert
    Run: On startup (or at logon)
    User: SYSTEM or current user

  PowerShell:
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $action = New-ScheduledTaskAction -Execute "C:\CPharm\CPharmWatchdog.exe" `
      -Argument "--watch --interval 30 --apply --alert"
    Register-ScheduledTask -TaskName "CPharm Watchdog" -Trigger $trigger -Action $action

Option 3: Batch file wrapper
  Create: C:\CPharm\watchdog_background.bat
    @echo off
    start "CPharm Watchdog" CPharmWatchdog.exe --watch --interval 30 --apply --alert
    REM Keep running, auto-restart if crashes
    :loop
    timeout /t 5 >nul
    tasklist | find /i "CPharmWatchdog.exe" >nul || goto :start
    goto :loop
    :start
    CPharmWatchdog.exe --watch --interval 30 --apply --alert
    goto :loop

Option 4: Docker container (for remote monitoring)
  Use CPharmWatchdog in a monitoring container:
    docker run -d \
      -e CPHARM_HOST=docker.for.mac.host.internal \
      -e CPHARM_PORT=8080 \
      cpharm-watchdog:latest \
      --watch --interval 60 --alert --apply

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚙️ ADVANCED USAGE:

Detect and repair stale processes:
  CPharmWatchdog.exe --once --apply
  # Kills duplicate run_mantis_inject.py, farm_354.py, etc.

Monitor multiple emulator farms:
  # Farm A: Docker Redroid (ports 5555-5562)
  CPharmWatchdog.exe --watch --host 127.0.0.1 --start-port 5555 --count 8
  
  # Farm B: MuMu emulators (ports 16384-16393)
  CPharmWatchdog.exe --watch --host 127.0.0.1 --start-port 16384 --count 10

Integration with ntfy.sh alerts:
  Setup: Create ntfy.sh account or self-hosted instance
  
  Usage:
    set NTFY_TOPIC=mycpharm-alerts
    set NTFY_URL=https://ntfy.sh
    CPharmWatchdog.exe --watch --interval 30 --alert
  
  Receives notifications on state changes:
    [ALERT] CPharm: main down (recovered)
    [ALERT] CPharm: dashboard down (will auto-repair in 30s)
    [ALERT] CPharm: 2 adb devices offline

Exit codes:
  0 = All healthy
  1 = Issues detected (--once mode, no --apply)
  2 = Recovery action failed (--apply mode)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 SAMPLE OUTPUTS:

Healthy farm:
  $ CPharmWatchdog.exe --once
  [HEALTHY] main=up dashboard=up docker=up adb_online=8
  $ echo %ERRORLEVEL%
  0

Degraded (dashboard down, ADB OK):
  $ CPharmWatchdog.exe --once
  [DEGRADED] main=up dashboard=down docker=up adb_online=8
  $ echo %ERRORLEVEL%
  1

Repair and recover:
  $ CPharmWatchdog.exe --once --apply --repair-dashboard
  [DEGRADED] main=up dashboard=down docker=up adb_online=8
  [REPAIR] Respawning dashboard...
  [CHECKING] main=up dashboard=up (recovered!) docker=up adb_online=8
  [HEALTHY] main=up dashboard=up docker=up adb_online=8

Background monitoring:
  $ start "" CPharmWatchdog.exe --watch --interval 30 --alert
  [WATCH] Started monitoring every 30s
  [HEALTHY] main=up dashboard=up docker=up adb_online=8
  [HEALTHY] (repeat every 30s)
  [ALERT] dashboard=down, will repair
  [REPAIR] Respawning dashboard...
  [ALERT] dashboard=up (recovered!)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔗 INTEGRATION POINTS:

In CPharm.exe wizard:
  - "Launch" step → Add "Health Check" button
    Calls: CPharmWatchdog.exe --once --apply
    Shows: Health report + recommend next steps

In CI/CD pipelines:
  Pre-flight check before starting CPharm:
    script: |
      CPharmWatchdog.exe --once --apply --repair-docker
      if errorlevel 1 exit /b 1
      CPharm.exe

In monitoring dashboards:
  Read health status from watchdog output:
    CPharmWatchdog.exe --once --json
    (future feature: JSON output mode)

═══════════════════════════════════════════════════════════
