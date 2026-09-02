"""
Auto-connect all phones (Docker Redroid + MuMu emulators).

Detects and connects BOTH:
  • Docker Redroid containers (ports 5555-5562)
  • MuMu emulators (ports 16384-16393)

Usage:
  python auto_phone_adb.py                    # Both Docker + MuMu
  python auto_phone_adb.py --docker-only      # Docker only
  python auto_phone_adb.py --mumu-only        # MuMu only
  python auto_phone_adb.py --timeout 15       # Custom timeout
"""

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

IS_WIN = sys.platform == "win32"

# Mirror diagnostics to logs/cpharm.log (same location the wizard monitors),
# honoring the CPHARM_LOGS override used by the watchdog.
_ROOT = Path(__file__).resolve().parent
_LOG_DIR = Path(os.environ.get("CPHARM_LOGS") or (_ROOT / "logs"))


def _logger() -> logging.Logger:
    """Return a module logger appending to logs/cpharm.log (never raises)."""
    lg = logging.getLogger("auto_phone_adb")
    if not lg.handlers:
        lg.setLevel(logging.INFO)
        try:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            h = logging.FileHandler(_LOG_DIR / "cpharm.log", encoding="utf-8")
            h.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s [auto_phone_adb] %(message)s"))
            lg.addHandler(h)
            lg.propagate = False
        except OSError:
            pass
    return lg


def _log(msg: str) -> None:
    """Print to console and mirror the line to logs/cpharm.log."""
    print(msg)
    try:
        _logger().info(msg)
    except Exception:
        pass


def find_adb() -> Path:
    """Find adb executable."""
    candidates = [
        Path("C:/CPharm/bundled/adb.exe") if IS_WIN else Path("/usr/bin/adb"),
        Path(f"{Path.home()}/.android/platform-tools/adb"),
    ]
    for adb in candidates:
        if adb.is_file():
            return adb
    raise RuntimeError("ADB not found. Install Android SDK or CPharm.")


def adb_cmd(adb: Path, args: list, timeout: int = 10) -> tuple[int, str]:
    """Run adb command."""
    try:
        result = subprocess.run(
            [str(adb)] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return 1, f"timeout ({timeout}s)"
    except Exception as e:
        return 1, str(e)


def connect_docker_phones(adb: Path, timeout_per_connect: int = 10) -> list[str]:
    """Connect Docker Redroid containers (ports 5555-5562)."""
    _log("[*] Connecting Docker Redroid (ports 5555-5562)...")
    connected = []
    for port in range(5555, 5563):
        addr = f"127.0.0.1:{port}"
        rc, msg = adb_cmd(adb, ["connect", addr], timeout=timeout_per_connect)
        if rc == 0 and ("connected" in msg.lower() or "already" in msg.lower()):
            connected.append(addr)
            _log(f"  [+] {addr}")
        else:
            _log(f"  [-] {addr}")
    return connected


def connect_mumu_phones(adb: Path, timeout_per_connect: int = 10) -> list[str]:
    """Connect MuMu emulators (ports 16384-16393)."""
    _log("[*] Connecting MuMu emulators (ports 16384-16393)...")
    connected = []
    for port in range(16384, 16394):
        addr = f"127.0.0.1:{port}"
        rc, msg = adb_cmd(adb, ["connect", addr], timeout=timeout_per_connect)
        if rc == 0 and ("connected" in msg.lower() or "already" in msg.lower()):
            connected.append(addr)
            _log(f"  [+] {addr}")
        else:
            _log(f"  [-] {addr}")
    return connected


def connect_all_phones(docker: bool = True, mumu: bool = True, wait_boot: bool = True, timeout_per_connect: int = 10) -> list[str]:
    """
    Auto-connect all emulator phones.
    
    Args:
        docker: Connect Docker Redroid (ports 5555-5562)
        mumu: Connect MuMu emulators (ports 16384-16393)
        wait_boot: Wait 30s for containers to fully boot
        timeout_per_connect: ADB timeout per connect attempt
    
    Returns:
        List of connected device addresses
    """
    adb = find_adb()
    _log(f"[*] Using ADB: {adb}")
    
    if wait_boot:
        _log("[*] Waiting 30s for emulators to fully boot...")
        time.sleep(30)
    
    all_connected = []
    
    if docker:
        docker_connected = connect_docker_phones(adb, timeout_per_connect)
        all_connected.extend(docker_connected)
    
    if mumu:
        mumu_connected = connect_mumu_phones(adb, timeout_per_connect)
        all_connected.extend(mumu_connected)
    
    if not all_connected:
        _log("[!] No phones connected yet; ADB may still be initializing.")
        _log("[*] Waiting 10s and retrying...")
        time.sleep(10)
        rc, msg = adb_cmd(adb, ["devices"], timeout=timeout_per_connect)
        _log(f"[*] ADB devices:\n{msg}")
    
    return all_connected


def verify_phones(count: int = 8, timeout: int = 10) -> bool:
    """Verify that ADB sees at least `count` connected phones.

    Parses ``adb devices`` output properly instead of substring matching so the
    header line ("List of devices attached") is not miscounted as a device."""
    adb = find_adb()
    rc, msg = adb_cmd(adb, ["devices"], timeout=timeout)
    if rc != 0:
        return False
    online = 0
    for line in msg.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            online += 1
    _log(f"[*] ADB reports {online} online devices (expecting {count})")
    return online >= count


if __name__ == "__main__":
    docker_mode = "--docker-only" in sys.argv
    mumu_mode = "--mumu-only" in sys.argv
    
    # Default: both
    if not docker_mode and not mumu_mode:
        docker_mode = True
        mumu_mode = True
    
    _log("=" * 50)
    if docker_mode and mumu_mode:
        _log("CONNECTING ALL PHONES (Docker + MuMu)")
    elif docker_mode:
        _log("CONNECTING DOCKER REDROID ONLY")
    else:
        _log("CONNECTING MUMU ONLY")
    _log("=" * 50)
    print()
    
    connected = connect_all_phones(docker=docker_mode, mumu=mumu_mode)
    _log(f"\n[+] Connected: {len(connected)} phone(s)")
    for addr in connected:
        _log(f"    {addr}")
    
    _log("\n[*] Verifying in 5s...")
    time.sleep(5)
    if verify_phones(count=len(connected)):
        _log("\n[OK] All phones verified!")
        sys.exit(0)
    else:
        _log("\n[!] Not all phones verified yet (may need more boot time)")
        sys.exit(1)
