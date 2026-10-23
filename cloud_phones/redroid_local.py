"""PharmFlow redroid bring-up helper (Windows).

Redroid (Android-in-Docker) needs binder/ashmem on the HOST kernel. Docker
Desktop/WSL2 kernels do NOT ship binder_linux/ashmem_linux, so Android never
boots and every ADB port stays "offline". This helper:

  1. Creates as many redroid services as --count says. There is no built-in
     phone ceiling. Without --count it only starts containers that already exist.
  2. Tests whether Android actually wakes up (ADB goes "device", not offline).
  3. If it wakes up -> connects every ADB port Docker published.
  4. If it cannot wake up (WSL2/Docker Desktop) -> gives a clear explanation and
     points you at the real workarounds (native Linux host, or MuMu for local).

Usage:
    py -3 cloud_phones/redroid_local.py up --count 12
    py -3 cloud_phones/redroid_local.py status
    py -3 cloud_phones/redroid_local.py down
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

COMPOSE = Path(__file__).resolve().parent / "docker-compose.redroid.yml"
# cycled for variety, never a phone-count ceiling
_PROFILES = (
    ("samsung", "SM-A546B", "a54x", "s5e8835", "samsung/a54x/a54x:14/UP1A.231005.007/A546BXXU1AWF1:user/release-keys"),
    ("google", "Pixel 7", "panther", "panther", "google/panther/panther:14/AP2A.240805.005/12025142:user/release-keys"),
    ("google", "Pixel 8", "shiba", "shiba", "google/shiba/shiba:14/AP2A.240805.005/12025142:user/release-keys"),
    ("OnePlus", "CPH2451", "aston", "qcom", "OnePlus/aston/aston:14/UKQ1.230924.001/172000:user/release-keys"),
    ("Xiaomi", "2211133C", "fuxi", "qcom", "Xiaomi/fuxi_global/fuxi:14/UKQ1.230917.001/V816:user/release-keys"),
    ("motorola", "Edge 30 Pro", "eqs", "qcom", "motorola/eqs_gu/eqs:13/T1SJ33.117-48-7/7:user/release-keys"),
    ("Sony", "SO-51C", "pdx234", "qcom", "Sony/pdx234/pdx234:14/UKQ1.230924.001/1:user/release-keys"),
    ("samsung", "SM-G950F", "dreamlte", "samsungexynos8895", "samsung/dreamltexx/dreamlte:9/PPR1.180610.011/G950FXXU1AQDD:user/release-keys"),
)
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import docker_guard  # noqa: E402
WSL_KERNEL_MARKERS = ("microsoft-standard-WSL2", "microsoft")

ADB_HINTS = [
    r"C:\PharmFlow\bundled\adb.exe",
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


def published_redroid_ports() -> list[int]:
    """Host ports Docker published for redroid. Do not invent 5555 + index."""
    if not docker_guard.engine_running():
        return []
    rc, out = _run(
        ["docker", "ps", "-a", "--filter", "name=redroid-", "--format", "{{.Ports}}"],
        timeout=20,
    )
    if rc != 0:
        return []
    ports: list[int] = []
    seen: set[int] = set()
    for match in re.finditer(r"(?:0\.0\.0\.0|127\.0\.0\.1):(\d+)->", out or ""):
        port = int(match.group(1))
        if port in seen or port <= 0:
            continue
        seen.add(port)
        ports.append(port)
    return ports


def _connect_all(adb: str) -> None:
    ports = published_redroid_ports()
    if not ports:
        print("No published redroid ADB ports to connect.")
        return
    for port in ports:
        _run([adb, "connect", f"127.0.0.1:{port}"], timeout=20)


def parse_create_count(argv: list[str]) -> int | None:
    """Operator create count. None means do not invent one."""
    if "--count" not in argv:
        return None
    idx = argv.index("--count")
    if idx + 1 >= len(argv):
        return None
    try:
        count = int(argv[idx + 1])
    except (TypeError, ValueError):
        return None
    if count < 1:
        return None
    return count


def render_compose(count: int) -> str:
    """One service per phone. Host ADB port is assigned at create time.

    Connect still uses the port Docker published, not this formula.
    """
    if count < 1:
        raise ValueError("count must be at least 1")
    lines = [
        "# Generated by redroid_local.py. Service count is the operator --count.",
        "services:",
    ]
    for i in range(count):
        brand, model, device, hardware, fingerprint = _PROFILES[i % len(_PROFILES)]
        host_port = 5555 + i
        lines.extend(
            [
                f"  redroid-{i}:",
                "    image: redroid/redroid:14.0.0-latest",
                f"    container_name: redroid-{i}",
                "    ports:",
                f'      - "{host_port}:5555"',
                "    volumes:",
                f"      - ./data/redroid-{i}:/data",
                "    privileged: true",
                "    environment:",
                "      - REDROID_BOOTANIMATION=0",
                "      - REDROID_WIDTH=900",
                "      - REDROID_HEIGHT=1600",
                "      - REDROID_DPI=420",
                "      - REDROID_GPU_MODE=guest",
                f"      - RO_PRODUCT_BRAND={brand}",
                f"      - RO_PRODUCT_MODEL={model}",
                f"      - RO_PRODUCT_DEVICE={device}",
                f"      - RO_HARDWARE={hardware}",
                f"      - RO_BUILD_FINGERPRINT={fingerprint}",
                f"      - RO_BOOT_SERIALNO=CPH{i:08d}",
                "      - RO_KERNEL_QEMU=0",
                "      - RO_SECURE=1",
                "      - RO_BUILD_TAGS=release-keys",
                "      - RO_BUILD_TYPE=user",
                "    restart: unless-stopped",
                "    networks:",
                "      - redroid-net",
                "",
            ]
        )
    lines.extend(
        [
            "networks:",
            "  redroid-net:",
            "    driver: bridge",
            "",
        ]
    )
    return "\n".join(lines)


def write_compose(count: int, dest: Path | None = None) -> Path:
    path = dest or COMPOSE
    path.write_text(render_compose(count), encoding="utf-8")
    return path


def cmd_up(count: int | None = None) -> int:
    print("== PharmFlow redroid local bring-up ==")
    if not docker_guard.engine_running():
        print("\nX Docker engine is NOT running. Start Docker Desktop first, then rerun.")
        print("  Start-Process 'C:\\Users\\jsmil\\AppData\\Local\\Programs\\DockerDesktop\\Docker Desktop.exe'")
        return 2
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

    if count is None:
        print("No --count. Starting redroid containers that already exist.")
        print("Creating phones needs --count N. This command does not invent a phone count.")
        rc, names = _run(
            ["docker", "ps", "-a", "--filter", "name=redroid", "--format", "{{.Names}}"],
            timeout=30,
        )
        existing = [line.strip() for line in (names or "").splitlines() if line.strip()]
        if rc != 0 or not existing:
            print("No redroid containers exist yet. Pass --count N to create them.")
            return 1
        rc, out = _run(["docker", "start", *existing], timeout=180)
        print((out or "").strip()[-1200:])
        if rc != 0:
            print("\nX docker start failed.")
            return 1
        adb = _which_adb()
        _connect_all(adb)
        return 0

    print(f"Writing {count} service(s) to {COMPOSE.name}")
    write_compose(count)
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
        print("You can add them to PharmFlow as the cloud phones Docker published.")
        return 0

    print("\nX Android did NOT come online (ADB stays offline). This is the WSL2 binder limit.")
    print("  Workaround options:\n")
    print("  1. Native Linux host (recommended) — the stack is designed for Linux.")
    print("     cloud_phones/setup-oracle-cloud.sh on an Oracle Cloud ARM box.\n")
    print("  2. Custom WSL2 kernel WITH binder_linux/ashmem_linux compiled in;")
    print("     then the compose file needs /dev/binder etc mounted (advanced, Linux side).\n")
    print("  3. Local phones now = MuMu (PharmFlow Phone Setup). Use the fixed compose file")
    print("     only on a Linux host; keep Docker Desktop for MuMu/automation service only.")
    return 1


def cmd_status() -> int:
    print("== redroid status ==")
    if not docker_guard.engine_running():
        print("Docker engine is not running. No redroid containers to list.")
        rc2, dev = _run([_which_adb(), "devices"], timeout=20)
        print("\nADB devices:")
        print(dev)
        return 0
    rc, out = _run(["docker", "ps", "--filter", "name=redroid", "--format",
                    "{{.Names}}\t{{.Status}}\t{{.Ports}}"], timeout=30)
    print(out if out.strip() else "(no redroid containers running)")
    rc2, dev = _run([_which_adb(), "devices"], timeout=20)
    print("\nADB devices:")
    print(dev)
    return 0


def cmd_down() -> int:
    if not docker_guard.engine_running():
        print("Docker engine is not running. Nothing to stop.")
        return 0
    rc, out = _run(["docker", "compose", "-f", str(COMPOSE), "down"], timeout=300)
    print((out or "").strip()[-800:])
    return rc


def main() -> int:
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    if cmd == "up":
        return cmd_up(parse_create_count(sys.argv[2:]))
    if cmd == "status":
        return cmd_status()
    if cmd == "down":
        return cmd_down()
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())