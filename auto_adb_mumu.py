#!/usr/bin/env python3
"""
Auto-connect all emulator phones: Docker Redroid + MuMu.

Usage:
  python auto_adb_mumu.py                    # Both Docker + MuMu
  python auto_adb_mumu.py --docker-only      # Docker only
  python auto_adb_mumu.py --mumu-only        # MuMu only
  python auto_adb_mumu.py --list             # List without connecting
  python auto_adb_mumu.py --timeout 10       # Custom timeout
  python auto_adb_mumu.py --json             # JSON output

Output:
  Prints connected phones to stdout (one per line)
  Exit code 0 = success, 1 = failures detected
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

IS_WIN = sys.platform == "win32"

# Mirror diagnostics to logs/pharmflow.log (same location the wizard monitors),
# honoring the PHARMFLOW_LOGS override used by the watchdog. stderr stays on the
# console so --json output on stdout remains machine-parseable.
_ROOT = Path(__file__).resolve().parent
_LOG_DIR = Path(os.environ.get("PHARMFLOW_LOGS") or (_ROOT / "logs"))


def _logger() -> logging.Logger:
    """Return a module logger appending to logs/pharmflow.log (never raises)."""
    lg = logging.getLogger("auto_adb_mumu")
    if not lg.handlers:
        lg.setLevel(logging.INFO)
        try:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            h = logging.FileHandler(_LOG_DIR / "pharmflow.log", encoding="utf-8")
            h.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s [auto_adb_mumu] %(message)s"))
            lg.addHandler(h)
            lg.propagate = False
        except OSError:
            pass
    return lg


def _log_file(msg: str) -> None:
    """Print a diagnostic to stderr and mirror it to logs/pharmflow.log."""
    print(msg, file=sys.stderr)
    try:
        _logger().info(msg)
    except Exception:
        pass

# Common ADB paths
ADB_PATHS = [
    Path("C:\\PharmFlow\\bundled\\adb.exe") if IS_WIN else Path("/usr/bin/adb"),
    Path("C:\\Android\\platform-tools\\adb.exe") if IS_WIN else None,
    Path(os.environ.get("ANDROID_HOME", "")) / "platform-tools" / ("adb.exe" if IS_WIN else "adb"),
]
ADB_PATHS = [p for p in ADB_PATHS if p and p.is_file()]


def find_adb() -> Optional[Path]:
    """Find ADB executable."""
    for p in ADB_PATHS:
        if p.is_file():
            return p
    try:
        # list-form; no shell needed for where/which
        result = subprocess.run(
            ["where", "adb"] if IS_WIN else ["which", "adb"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip().split("\n")[0])
    except Exception:
        pass
    return None


def run_adb(adb_exe: Path, args: list, timeout: int = 8) -> tuple[int, str, str]:
    """Run adb command, return (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            [str(adb_exe)] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", f"ADB timeout after {timeout}s"
    except Exception as e:
        return 1, "", str(e)


def discover_docker_phones(adb_exe: Path, timeout: int = 8) -> list[str]:
    """Discover Docker Redroid containers (ports 5555-5562)."""
    phones = []
    for port in range(5555, 5563):
        addr = f"127.0.0.1:{port}"
        rc, out, err = run_adb(adb_exe, ["connect", addr], timeout=timeout)
        if rc == 0 and "connected" in out.lower():
            phones.append(addr)
    return phones


def discover_mumu_phones(adb_exe: Path, timeout: int = 8) -> list[str]:
    """Discover MuMu emulators (ports 16384-16393)."""
    phones = []
    for port in range(16384, 16394):
        addr = f"127.0.0.1:{port}"
        rc, out, err = run_adb(adb_exe, ["connect", addr], timeout=timeout)
        if rc == 0 and "connected" in out.lower():
            phones.append(addr)
    return phones


def list_adb_devices(adb_exe: Path, timeout: int = 8) -> list[str]:
    """List all connected ADB devices."""
    rc, out, err = run_adb(adb_exe, ["devices", "-l"], timeout=timeout)
    if rc != 0:
        return []
    devices = []
    for line in out.split("\n"):
        line = line.strip()
        if not line or line.startswith("List") or line.startswith("*"):
            continue
        parts = line.split()
        if parts and "device" in line.lower() and "offline" not in line.lower():
            devices.append(parts[0])
    return devices


def main():
    parser = argparse.ArgumentParser(
        description="Auto-connect all Docker Redroid and MuMu phones to ADB"
    )
    parser.add_argument(
        "--docker-only",
        action="store_true",
        help="Connect Docker Redroid only (ports 5555-5562)",
    )
    parser.add_argument(
        "--mumu-only",
        action="store_true",
        help="Connect MuMu only (ports 16384-16393)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List detected phones without connecting",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=8,
        help="ADB command timeout in seconds (default: 8)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    # Find ADB
    adb_exe = find_adb()
    if not adb_exe:
        _log_file("ERROR: ADB not found. Install Android SDK or PharmFlow.")
        return 1

    _log_file(f"[*] Using ADB: {adb_exe}")
    
    # Determine what to discover
    discover_docker = not args.mumu_only
    discover_mumu = not args.docker_only

    # Discover phones
    _log_file("[*] Discovering emulators...")
    
    docker_phones = []
    mumu_phones = []
    
    if discover_docker:
        _log_file("[*] Scanning Docker Redroid (ports 5555-5562)...")
        docker_phones = discover_docker_phones(adb_exe, timeout=args.timeout)
    
    if discover_mumu:
        _log_file("[*] Scanning MuMu (ports 16384-16393)...")
        mumu_phones = discover_mumu_phones(adb_exe, timeout=args.timeout)
    
    all_phones = docker_phones + mumu_phones

    if not all_phones:
        _log_file("ERROR: No phones discovered")
        return 1

    _log_file(f"[+] Found {len(all_phones)} phone(s) ({len(docker_phones)} Docker, {len(mumu_phones)} MuMu)")

    # List or connect
    if args.list:
        for phone in all_phones:
            print(phone)
        return 0

    # Connect all
    _log_file("[*] Connecting all phones...")
    connected = []
    for phone in all_phones:
        rc, out, err = run_adb(adb_exe, ["connect", phone], timeout=args.timeout)
        if rc == 0:
            connected.append(phone)
            _log_file(f"[+] {phone}: OK")
        else:
            _log_file(f"[-] {phone}: FAILED ({err})")

    # Verify
    _log_file("[*] Verifying ADB devices...")
    time.sleep(1)
    devices = list_adb_devices(adb_exe, timeout=args.timeout)
    _log_file(f"[+] ADB online: {len(devices)} device(s)")

    if args.json:
        output = {
            "docker_phones": docker_phones,
            "mumu_phones": mumu_phones,
            "total_discovered": len(all_phones),
            "connected": connected,
            "adb_devices": devices,
            "success": len(connected) > 0,
        }
        print(json.dumps(output, indent=2))
    else:
        for device in devices:
            print(device)

    return 0 if connected else 1


if __name__ == "__main__":
    sys.exit(main())
