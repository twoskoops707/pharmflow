═══════════════════════════════════════════════════════════
  PHARMFLOWWATCHDOG REFERENCE
═══════════════════════════════════════════════════════════

📋 WHAT IS PHARMFLOWWATCHDOG?

Self-healing health monitor for the PharmFlow farm. Continuously checks:
  ✓ Is PharmFlow.exe main process alive?
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
PharmFlow.exe --watchdog --once

# Run in background, auto-repair
PharmFlow.exe --watchdog --watch --interval 30 --apply --alert

# Check every 60s, repair dashboard if down
PharmFlow.exe --watchdog --watch --interval 60 --repair-dashboard

# Verify specific ADB ports
PharmFlow.exe --watchdog --once --host 127.0.0.1 --start-port 5555 --count 8

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
    PharmFlow.exe --watchdog --once --apply --repair-dashboard
    PharmFlow.exe --watchdog --watch --apply --repair-docker

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
    PharmFlow.exe --watchdog --reap-only                    # report stale processes
    PharmFlow.exe --watchdog --reap-only --apply            # kill stale immediately
    PharmFlow.exe --watchdog --watch --apply                # monitor + kill every 60s

Stealth / exit-IP uniqueness (--stealth):
  Verifies every phone holds a UNIQUE Tor exit IP via the dashboard's
  /api/stealth/verify endpoint and rotates duplicates when the farm runs
  unattended. This runs on the SAME sweep as the process reaper, so stealth
  recovery and stale-process cleanup share one 60s maintenance cadence
  (the dashboard endpoint is NOT hit every check interval).

  --stealth           Enable exit-IP uniqueness verification/rotation
                      (runs with each reaper sweep; needs dashboard up)

  Examples:
    PharmFlow.exe --watchdog --watch --apply --stealth        # sweep every 60s: reap + stealth
    PharmFlow.exe --watchdog --reap-only --stealth            # single maintenance tick
    PharmFlow.exe --watchdog --reap-only --stealth --apply    # kill stale + rotate dupes now

Monitoring:
  --alert             Send ntfy notifications on state changes
                      (up → down, down → up transitions)
                      Requires: ntfy.sh account or self-hosted instance

ADB Configuration:
  --host HOST         ADB target host (default: 127.0.0.1)
  --start-port PORT   ADB start port (default: 5555)
  --count COUNT       Number of ADB ports to check (default: 8)
  
  Examples:
    PharmFlow.exe --watchdog --once --host 127.0.0.1 --start-port 5555 --count 8
    PharmFlow.exe --watchdog --once --host 127.0.0.1 --start-port 16384 --count 10  (MuMu)

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
  main = Is PharmFlow.exe running?
  dashboard = Is HTTP server (8080) responding?
  docker = Are Redroid containers up?
  adb_online = How many ADB devices are online?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🚀 PRODUCTION SETUPS:

Option 1: Manual checks
  Run before starting PharmFlow:
    PharmFlow.exe --watchdog --once --apply --repair-docker
    PharmFlow.exe

Option 2: Background monitoring (Task Scheduler)
  Create scheduled task:
    Program: C:\PharmFlow\PharmFlow.exe --watchdog
    Arguments: --watch --interval 30 --apply --alert
    Run: On startup (or at logon)
    User: SYSTEM or current user

  PowerShell:
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $action = New-ScheduledTaskAction -Execute "C:\PharmFlow\PharmFlow.exe --watchdog" `
      -Argument "--watch --interval 30 --apply --alert"
    Register-ScheduledTask -TaskName "PharmFlow Watchdog" -Trigger $trigger -Action $action

Option 3: Batch file wrapper
  Create: C:\PharmFlow\watchdog_background.bat
    @echo off
    start "PharmFlow Watchdog" PharmFlow.exe --watchdog --watch --interval 30 --apply --alert
    REM Keep running, auto-restart if crashes
    :loop
    timeout /t 5 >nul
    tasklist | find /i "PharmFlow.exe --watchdog" >nul || goto :start
    goto :loop
    :start
    PharmFlow.exe --watchdog --watch --interval 30 --apply --alert
    goto :loop

Option 4: Docker container (for remote monitoring)
  Use PharmFlowWatchdog in a monitoring container:
    docker run -d \
      -e PHARMFLOW_HOST=docker.for.mac.host.internal \
      -e PHARMFLOW_PORT=8080 \
      pharmflow-watchdog:latest \
      --watch --interval 60 --alert --apply

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚙️ ADVANCED USAGE:

Detect and repair stale processes:
  PharmFlow.exe --watchdog --once --apply
  # Kills duplicate run_mantis_inject.py, farm_354.py, etc.

Monitor multiple emulator farms:
  # Farm A: Docker Redroid (ports 5555-5562)
  PharmFlow.exe --watchdog --watch --host 127.0.0.1 --start-port 5555 --count 8
  
  # Farm B: MuMu emulators (ports 16384-16393)
  PharmFlow.exe --watchdog --watch --host 127.0.0.1 --start-port 16384 --count 10

Integration with ntfy.sh alerts:
  Setup: Create ntfy.sh account or self-hosted instance
  
  Usage:
    set NTFY_TOPIC=mypharmflow-alerts
    set NTFY_URL=https://ntfy.sh
    PharmFlow.exe --watchdog --watch --interval 30 --alert
  
  Receives notifications on state changes:
    [ALERT] PharmFlow: main down (recovered)
    [ALERT] PharmFlow: dashboard down (will auto-repair in 30s)
    [ALERT] PharmFlow: 2 adb devices offline

Exit codes:
  0 = All healthy
  1 = Issues detected (--once mode, no --apply)
  2 = Recovery action failed (--apply mode)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 SAMPLE OUTPUTS:

Healthy farm:
  $ PharmFlow.exe --watchdog --once
  [HEALTHY] main=up dashboard=up docker=up adb_online=8
  $ echo %ERRORLEVEL%
  0

Degraded (dashboard down, ADB OK):
  $ PharmFlow.exe --watchdog --once
  [DEGRADED] main=up dashboard=down docker=up adb_online=8
  $ echo %ERRORLEVEL%
  1

Repair and recover:
  $ PharmFlow.exe --watchdog --once --apply --repair-dashboard
  [DEGRADED] main=up dashboard=down docker=up adb_online=8
  [REPAIR] Respawning dashboard...
  [CHECKING] main=up dashboard=up (recovered!) docker=up adb_online=8
  [HEALTHY] main=up dashboard=up docker=up adb_online=8

Background monitoring:
  $ start "" PharmFlow.exe --watchdog --watch --interval 30 --alert
  [WATCH] Started monitoring every 30s
  [HEALTHY] main=up dashboard=up docker=up adb_online=8
  [HEALTHY] (repeat every 30s)
  [ALERT] dashboard=down, will repair
  [REPAIR] Respawning dashboard...
  [ALERT] dashboard=up (recovered!)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔗 INTEGRATION POINTS:

In PharmFlow.exe wizard:
  - "Launch" step → Add "Health Check" button
    Calls: PharmFlow.exe --watchdog --once --apply
    Shows: Health report + recommend next steps

In CI/CD pipelines:
  Pre-flight check before starting PharmFlow:
    script: |
      PharmFlow.exe --watchdog --once --apply --repair-docker
      if errorlevel 1 exit /b 1
      PharmFlow.exe

In monitoring dashboards:
  Read health status from watchdog output:
    PharmFlow.exe --watchdog --once --json
    (future feature: JSON output mode)

═══════════════════════════════════════════════════════════
