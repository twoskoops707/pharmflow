"""CPharm redroid bring-up helper (Windows).

Redroid (Android-in-Docker) needs binder/ashmem on the HOST kernel. Docker
Desktop/WSL2 kernels do NOT ship binder_linux/ashmem_linux, so Android never
boots and every ADB port stays "offline". This helper:

  1. Brings up the redroid stack with the fixed compose file.
  2. Tests whether Android actually wakes up (ADB goes "device", not offline).
  3. If it wakes up -> registers 127.0.0.1:5555..5562 for local cloud phones.
  4. If it cannot wake up (WSL2/Docker Desktop) -> gives a clear explanation and
     points you at the real workarounds (native Linux host, or MuMu for local).

Usage:
    py -3 cloud_phones/redroid_local.py up
    py -3 cloud_phones/redroid_local.py status
    py -3 cloud_phones/redroid_local.py down
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

COMPOSE = Path(__file__).resolve().parent / "docker-compose.redroid.yml"
PORTS = [5555 + i for i in range(8)]  # redroid-0..7
WSL_KERNEL_MARKERS = ("microsoft-standard-WSL2", "microsoft")

ADB_HINTS = [
    r"C:\CPharm\bundled\adb.exe",
    Path.home() / "AppData/Local/Android/Sdk/platform-tools/adb.exe",
    "adb",
]


def _which_adb() -> str:
    for candidate in ADB_HINTS[:-1]:  # explicit paths first
        p = Path(candidate)
        if p.is_file():
            return str(p)
    return "adb"


def _run(cmd: list[str], timeout: int = 900, capture: bool = True) -> tuple[int, str]:
    kwargs = {"capture_output": capture, "text": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.run(cmd, timeout=timeout, **kwargs)
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _host_kernel_is_wsl() -> bool:
    rc, out = _run(["docker", "info"], timeout=30)
    if rc == 0:
        for line in out.splitlines():
            if line.startswith("Kernel Version:"):
                return any(m in line.lower() for m in WSL_KERNEL_MARKERS)
    return False


def _adb_wakes_up(timeout: int = 90) -> bool:
    adb = _which_adb()
    _run([adb, "start-server"], timeout=30, capture=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        rc, out = _run([adb, "devices"], timeout=20)
        if rc == 0:
            dev = [
                l.split()[0]
                for l in out.splitlines()[1:]
                if len(l.split()) >= 2 and l.split()[1] in ("device",)
            ]
            cloud = [d for d in dev if d.startswith("127.0.0.") or d.startswith("localhost:")]
            if cloud:
                return True
        time.sleep(10)
    return False


def _connect_all(adb: str) -> None:
    for p in PORTS:
        _run([adb, "connect", f"127.0.0.1:{p}"], timeout=20)


def cmd_up() -> int:
    print("== CPharm redroid local bring-up ==")
    rc, _ = _run(["docker", "info"], timeout=30, capture=True)
    if rc != 0:
        print("\nX Docker engine is NOT running. Start Docker Desktop first, then rerun.")
        print("  Start-Process 'C:\\Users\\jsmil\\AppData\\Local\\Programs\\DockerDesktop\\Docker Desktop.exe'")
        return 2

    wsl = _host_kernel_is_wsl()
    if wsl:
        print("! Host kernel is WSL2 / Docker Desktop.")
        print("  redroid requires binder/ashmem which this kernel does not expose.")
        print("  The stack may start but Android will NOT boot (ADB stays offline).")
        print("  Proceeding anyway to prove it, then telling you the workaround.\n")

    print(f"Starting stack: {COMPOSE.name}")
    rc, out = _run(["docker", "compose", "-f", str(COMPOSE), "up", "-d"], timeout=900)
    print((out or "").strip()[-1200:])
    if rc != 0:
        print("\nX compose up failed — see Docker Desktop logs / Compose output above.")
        return 1

    print("\nWaiting for Android to boot inside the containers...")
    ok = _adb_wakes_up(timeout=100)
    adb = _which_adb()
    if ok:
        _connect_all(adb)
        rc2, dev = _run([adb, "devices"], timeout=20)
        print("\nOK — ADB shows cloud phones online:")
        print(dev)
        print("You can add them to CPharm as cloud phones (127.0.0.1:5555..k).")
        return 0

    print("\nX Android did NOT come online (ADB stays offline). This is the WSL2 binder limit.")
    print("  Workaround options:\n")
    print("  1. Native Linux host (recommended) — the stack is designed for Linux.")
    print("     cloud_phones/setup-oracle-cloud.sh on an Oracle Cloud ARM box.\n")
    print("  2. Custom WSL2 kernel WITH binder_linux/ashmem_linux compiled in;")
    print("     then the compose file needs /dev/binder etc mounted (advanced, Linux side).\n")
    print("  3. Local phones now = MuMu (CPharm Phone Setup). Use the fixed compose file")
    print("     only on a Linux host; keep Docker Desktop for MuMu/automation service only.")
    return 1


def cmd_status() -> int:
    print("== redroid status ==")
    rc, out = _run(["docker", "ps", "--filter", "name=redroid", "--format",
                    "{{.Names}}\t{{.Status}}\t{{.Ports}}"], timeout=30)
    print(out if out.strip() else "(no redroid containers running)")
    rc2, dev = _run([_which_adb(), "devices"], timeout=20)
    print("\nADB devices:")
    print(dev)
    return 0


def cmd_down() -> int:
    rc, out = _run(["docker", "compose", "-f", str(COMPOSE), "down"], timeout=300)
    print((out or "").strip()[-800:])
    return rc


def main() -> int:
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    if cmd == "up":
        return cmd_up()
    if cmd == "status":
        return cmd_status()
    if cmd == "down":
        return cmd_down()
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())