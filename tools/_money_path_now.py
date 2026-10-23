"""One-shot money path recovery — operator urgent tick."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("PHARMFLOW_TOR_PATH", r"C:\PharmFlow\automation\tor\tor.exe")

import automation.no_window  # noqa: F401

import psutil

PYW = Path(r"C:\Users\jsmil\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe")
LOG = Path(r"C:\PharmFlow\logs")
LOCK = json.loads((LOG / "ADB_SERIAL_MAP.lock.json").read_text(encoding="utf-8-sig"))
phones = LOCK["phones"]
inject = LOCK["inject"]
http_base = int(json.loads((LOG / "tor_port_bases.json").read_text()).get("http_base", 8268))


def port_open(port: int) -> bool:
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=0.4)
        s.close()
        return True
    except OSError:
        return False


def get_pids(marker: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or []))
            if marker in cmd:
                out.append((int(proc.info["pid"]), cmd))
        except (psutil.Error, TypeError, ValueError):
            pass
    return out


def main() -> int:
    # 1) Kill roster inject
    roster_killed: list[int] = []
    for pid, _cmd in get_pids("run_mantis_inject_proxies.py"):
        try:
            psutil.Process(pid).kill()
            psutil.Process(pid).wait(timeout=5)
            roster_killed.append(pid)
        except Exception as exc:
            print(f"roster_kill_fail pid={pid} err={exc}", flush=True)

    # 2) Ensure exactly ONE keepalive
    keepalive_pids = [p for p, _ in get_pids("pharmflow_inject_keepalive.py")]
    keepalive_pid = 0
    if len(keepalive_pids) > 1:
        keepalive_pids.sort()
        for pid in keepalive_pids[:-1]:
            try:
                psutil.Process(pid).kill()
            except Exception:
                pass
        keepalive_pid = keepalive_pids[-1]
    elif len(keepalive_pids) == 1:
        keepalive_pid = keepalive_pids[0]
    else:
        script = ROOT / "scripts" / "pharmflow_inject_keepalive.py"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)
        flags |= int(getattr(subprocess, "DETACHED_PROCESS", 0x00000008) or 0)
        flags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200) or 0)
        subprocess.Popen(
            [str(PYW), "-u", str(script)],
            cwd=str(ROOT),
            env=env,
            creationflags=flags,
            close_fds=True,
        )
        time.sleep(2.0)
        keepalive_pids = [p for p, _ in get_pids("pharmflow_inject_keepalive.py")]
        keepalive_pid = keepalive_pids[0] if keepalive_pids else 0

    farm_pids = [p for p, _ in get_pids("run_farm_354.py")]
    farm_pid = farm_pids[0] if farm_pids else 0

    # 3) heal_inject_and_tor() — no live=int
    from automation.farm_exe_self_heal import heal_inject_and_tor

    heal_fixes = heal_inject_and_tor()
    print("HEAL_FIXES:", heal_fixes[:24], flush=True)

    # 4) Hard-pin all lock-map phones
    adb = Path(r"C:\PharmFlow\bundled\adb.exe")
    if not adb.is_file():
        adb = Path(r"C:\Program Files\Netease\MuMuPlayerARM\shell\adb.exe")
    nw = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)

    def adb_run(args: list[str], timeout: float = 12.0) -> tuple[int, str]:
        r = subprocess.run(
            [str(adb), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=nw,
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    for name, ser in phones.items():
        idx = int(name.split(".")[0][2:])
        port = int(inject.get(name) or (8218 + idx))
        adb_run(["-s", ser, "reverse", f"tcp:{port}", f"tcp:{port}"])
        adb_run(
            [
                "-s",
                ser,
                "shell",
                "settings",
                "put",
                "global",
                "http_proxy",
                f"127.0.0.1:{port}",
            ]
        )

    time.sleep(0.8)

    # 5) Confirm inject + guest proxy
    inject_ports = list(range(8242, 8250))
    inject_up = sum(1 for p in inject_ports if port_open(p))
    bad_pins = 0
    for name, ser in phones.items():
        idx = int(name.split(".")[0][2:])
        want_port = int(inject.get(name) or (8218 + idx))
        want = f"127.0.0.1:{want_port}"
        _code, out = adb_run(["-s", ser, "shell", "settings", "get", "global", "http_proxy"])
        cur = (out or "").strip().splitlines()[-1] if out else ""
        if cur != want:
            bad_pins += 1
            print(f"BAD_PIN {name} want={want} got={cur}", flush=True)

    # 6) Tor HTTP ports at http_base + idx
    from automation import tor_manager

    tor_up = 0
    for idx in range(24, 32):
        tp = http_base + idx
        if port_open(tp):
            tor_up += 1
            continue
        try:
            tor_manager.start_tor_for_phone(idx)
            time.sleep(0.6)
        except Exception as exc:
            print(f"tor_start_fail idx={idx} err={exc}", flush=True)
        if port_open(tp):
            tor_up += 1
        else:
            print(f"tor_down port={tp} idx={idx}", flush=True)

    inject_up = sum(1 for p in inject_ports if port_open(p))

    print("=== RESULTS ===", flush=True)
    print(f"inject={inject_up}/8", flush=True)
    print(f"bad_pins={bad_pins}", flush=True)
    print(f"tor_http={tor_up}/8", flush=True)
    print(f"keepalive_pid={keepalive_pid}", flush=True)
    print(f"farm_pid={farm_pid}", flush=True)
    print(f"roster_inject_killed={roster_killed}", flush=True)
    print(f"http_base={http_base}", flush=True)
    return 0 if inject_up == 8 and bad_pins == 0 and tor_up == 8 else 1


if __name__ == "__main__":
    raise SystemExit(main())
