#!/usr/bin/env python3
"""Farm Health Monitor — runs every 2 minutes, catches ALL issues automatically."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
CPharm = r"C:\CPharm"
ADB = os.environ.get("CPHARM_ADB") or r"C:\CPharm\bundled\adb.exe"
LOG = rf"{CPharm}\logs\farm_354.log"
MANTIS_STATE = rf"{CPharm}\logs\mantis_today_state.json"
MONITOR_LOG = rf"{CPharm}\logs\health_monitor.log"

# All known phone IPs
PHONE_IPS = [
    "10.0.2.107", "10.0.2.139", "10.0.2.13", "10.0.2.173",
    "10.0.2.209", "10.0.2.34", "10.0.2.36", "10.0.2.55",
    "10.0.2.152", "10.0.2.215", "10.0.2.51", "10.0.2.79",
]

REQUIRED_PROCS = {
    'run_farm_354.py': {'min': 1, 'max': 1, 'restart_cmd': [sys.executable, 'scripts\\run_farm_354.py']},
    'farm_watchdog.py': {'min': 1, 'max': 1, 'restart_cmd': None},  # watchdog manages itself
    'run_mantis_inject_proxies.py': {'min': 1, 'max': 1, 'restart_cmd': [sys.executable, '-u', 'scripts\\run_mantis_inject_proxies.py']},
    'farm_operator_dash.py': {'min': 1, 'max': 1, 'restart_cmd': [sys.executable, '-u', 'scripts\\farm_operator_dash.py']},
    'watch_bottom_ads.py': {'min': 1, 'max': 1, 'restart_cmd': [sys.executable, '-u', 'scripts\\watch_bottom_ads.py']},
    'ssp_paying_hunter.py': {'min': 1, 'max': 1, 'restart_cmd': [sys.executable, '-u', 'scripts\\ssp_paying_hunter.py']},
}

def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(MONITOR_LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError:
        pass

def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
        return r.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""

def get_devices():
    """Get list of connected ADB devices."""
    out = run([ADB, 'devices'], timeout=10)
    devices = []
    for line in out.split('\n'):
        if '\tdevice' in line:
            devices.append(line.split('\t')[0])
    return devices

def kill_stale_processes():
    """Kill duplicate processes, restart missing ones."""
    counts = {}
    to_kill = []
    procs_found = {}

    for p in psutil.process_iter(['pid', 'cmdline', 'name']):
        try:
            joined = ' '.join(p.cmdline() or [])
            name = str(p.info.get('name', '')).lower()
        except (psutil.Error, OSError, TypeError):
            continue
        if 'python' not in name:
            continue

        for frag, cfg in REQUIRED_PROCS.items():
            if frag in joined:
                counts[frag] = counts.get(frag, 0) + 1
                procs_found.setdefault(frag, []).append(p.pid)
                if counts[frag] > cfg['max']:
                    try:
                        psutil.Process(p.pid).kill()
                        to_kill.append((frag, p.pid))
                        log(f"  KILLED duplicate {frag} pid={p.pid}")
                    except (psutil.Error, OSError):
                        pass

    restarted = []
    for frag, cfg in REQUIRED_PROCS.items():
        if counts.get(frag, 0) < cfg['min']:
            if cfg['restart_cmd']:
                try:
                    subprocess.Popen(cfg['restart_cmd'], cwd=str(ROOT),
                                   creationflags=0x08000000,  # CREATE_NO_WINDOW
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    restarted.append(frag)
                    log(f"  RESTARTED {frag}")
                except OSError as e:
                    log(f"  FAILED to restart {frag}: {e}")

    return to_kill, restarted, counts

def check_phone_health(devices):
    """Flag phones with empty focus — diagnose only, never reboot/kill emulators."""
    stale_phones = []
    for dev in devices:
        out = run([ADB, '-s', dev, 'shell', 'dumpsys window | grep mCurrentFocus'], timeout=8)
        focus = ""
        for line in out.split('\n'):
            if 'mCurrentFocus' in line:
                focus = line.strip()
                break

        if not focus or 'null' in focus.lower():
            stale_phones.append((dev, 'null/empty focus'))
            # Prefer diagnose/fix over reboot — transient null focus is common.
            log(f"  STALE: {dev} — null focus (no reboot; HOME keyevent)")
            run([ADB, '-s', dev, 'shell', 'input', 'keyevent', '3'], timeout=5)
        elif 'lawnchair' in focus.lower() and 'launcher' in focus.lower():
            # Home screen is OK if sequence hasn't started yet, flag but don't reboot
            pass
    return stale_phones

def check_inject_health():
    """Check inject proxy ports are alive."""
    out = run(['netstat', '-ano'], timeout=10)
    inject_ports = []
    for line in out.split('\n'):
        if 'LISTEN' in line and ':822' in line:
            inject_ports.append(line.strip())

    if len(inject_ports) < 6:
        log(f"  WARNING: Only {len(inject_ports)} inject ports (need 8+)")
        return False, inject_ports
    return True, inject_ports

def check_revenue():
    """Read Mantis state and check if revenue is growing."""
    try:
        with open(MANTIS_STATE, encoding='utf-8') as f:
            state = json.load(f)
        return state
    except (OSError, json.JSONDecodeError, TypeError):
        return None

def reconnect_offline_phones(devices):
    """Try to reconnect phones that are offline."""
    reconnected = 0
    for ip in PHONE_IPS:
        serial = f"{ip}:5555"
        if serial not in devices:
            result = run([ADB, 'connect', serial], timeout=8)
            if 'connected' in result:
                reconnected += 1
                log(f"  RECONNECTED {serial}")
    return reconnected

def _log_tail(path: str, n: int = 200) -> str:
    """Last N lines of a log file (Windows-safe; no Unix tail)."""
    try:
        lines = Path(path).read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-n:])

def main_loop():
    log("=" * 60)
    log("FARM HEALTH MONITOR STARTED — checking every 120s")
    log("=" * 60)

    last_revenue = 0
    check_count = 0

    while True:
        try:
            check_count += 1
            log(f"\n--- CHECK #{check_count} ---")

            # Step 1: Kill stale processes, restart missing ones
            log("[1] Process health:")
            kills, restarts, counts = kill_stale_processes()
            for frag, count in counts.items():
                status = "✅" if count == 1 else "⚠️" if count > 1 else "❌"
                log(f"  {status} {frag}: {count}")

            # Step 2: Check devices
            log("[2] Device health:")
            devices = get_devices()
            log(f"  Connected: {len(devices)} devices")

            # Reconnect offline phones
            reconnected = reconnect_offline_phones(devices)
            if reconnected:
                devices = get_devices()  # Refresh

            # Step 3: Check phone health (stuck on home screen too long)
            log("[3] Phone health:")
            stale = check_phone_health(devices)

            # Step 4: Check inject proxy
            log("[4] Inject health:")
            inject_ok, inject_ports = check_inject_health()
            log(f"  Ports: {len(inject_ports)} {'✅' if inject_ok else '❌'}")

            # Step 5: Check revenue
            log("[5] Revenue:")
            state = check_revenue()
            if state:
                impressions = state.get('impressions', 0)
                clicks = state.get('clicks', 0)
                payout = state.get('payout_usd', 0)
                log(f"  Impressions: {impressions}")
                log(f"  Clicks: {clicks}")
                log(f"  Payout: ${payout:.2f}")

                if last_revenue > 0 and payout == last_revenue:
                    log("  ⚠️ REVENUE FLAT — no growth since last check!")
                elif last_revenue > 0:
                    delta = payout - last_revenue
                    log(f"  📈 +${delta:.2f} since last check")
                last_revenue = payout

            # Step 6: Check for critical errors in log
            log("[6] Log errors (last 5 min):")
            out = _log_tail(LOG, 200)
            error_count = out.lower().count('error')
            timeout_count = out.lower().count('timeout')
            inject_fail = out.lower().count('inject') and ':0' in out
            log(f"  Errors: {error_count}, Timeouts: {timeout_count}")
            if inject_fail:
                log("  ❌ DETECTED :0 proxy — inject broken!")

            log(f"--- CHECK #{check_count} COMPLETE ---")

        except Exception as e:
            log(f"MONITOR ERROR: {e}")

        time.sleep(120)

if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
    main_loop()
