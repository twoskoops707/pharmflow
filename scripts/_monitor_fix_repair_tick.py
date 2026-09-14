#!/usr/bin/env python3
"""Cursor+FREEBUFF monitor tick — phones first, stealth second. Never kills MuMu."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = Path(r"C:\PharmFlow\logs")
sys.path.insert(0, str(ROOT))

from automation.adb_wrapper import AdbWrapper
from automation.agent_unison import heartbeat, set_status
from automation.browse_proxy import _read_guest_proxy, pin_guest_proxy
from automation.farm_checkin import gather_checkin
from automation.farm_money_monitor import cull_hung_adb, probe_ssp
from automation.mantis_inject_proxy import ensure_inject_for_phone, verify_reverse_tunnel

PY = Path(r"C:\Users\jsmil\AppData\Local\Python\pythoncore-3.14-64\python.exe")
ADB = Path(r"C:\PharmFlow\bundled\adb.exe")
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
OVERRIDES = LOG / "farm_runtime_overrides.json"
LOCK = LOG / "ADB_SERIAL_MAP.lock.json"
PAUSE_ADS = LOG / "PAUSE_BOTTOM_ADS_WATCH.flag"
TICK_LOG = LOG / "cursor_monitor_tick.log"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _echo(msg: str) -> None:
    line = f"{_utc()} {msg}"
    print(line, flush=True)
    try:
        TICK_LOG.parent.mkdir(parents=True, exist_ok=True)
        with TICK_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _run(cmd: list[str], timeout: float = 15) -> tuple[int, str]:
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, creationflags=FLAGS
        )
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as exc:
        return 1, str(exc)


def _kill_dump_fighters() -> list[str]:
    fixes: list[str] = []
    try:
        import psutil
    except ImportError:
        return fixes
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(proc.info.get("cmdline") or [])
            if "watch_bottom_ads" in cmd or "farm_fail_review" in cmd:
                pid = int(proc.info["pid"])
                proc.kill()
                tag = "watch" if "watch_bottom" in cmd else "fail_review"
                fixes.append(f"killed_{tag}={pid}")
        except Exception:
            continue
    return fixes


def _farm_progress() -> tuple[dict[str, int], int, str]:
    fl = LOG / "farm_354.log"
    if not fl.is_file():
        return {}, 0, ""
    try:
        lines = fl.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
    except OSError:
        return {}, 0, ""
    prog: dict[str, int] = {}
    active_n = 0
    last = ""
    for ln in reversed(lines):
        if not last:
            last = ln
        m = re.search(r"progress (\{[^}]+\})", ln)
        if m:
            try:
                prog = eval(m.group(1))  # noqa: S307 — trusted local log
            except Exception:
                prog = {}
            am = re.search(r"active=\[([^\]]*)\]", ln)
            if am:
                active_n = len([x for x in am.group(1).split(",") if x.strip()])
            break
    return prog, active_n, last


def _adb_live() -> list[str]:
    _, out = _run([str(ADB), "devices"], timeout=20)
    return [ln.split()[0] for ln in out.splitlines() if "\tdevice" in ln and not ln.startswith("127.0.0.1:")]


def _fix_serial_map(live: set[str]) -> dict[str, str]:
    lock: dict = {}
    if LOCK.is_file():
        lock = json.loads(LOCK.read_text(encoding="utf-8-sig"))
    phones: dict[str, str] = dict(lock.get("phones") or {})
    tablet: dict[str, str] = dict(lock.get("tablet") or {})

    # vm3 lives at 10.0.2.132 (inject 8221) — remediator sometimes labels it vm1
    if phones.get("vm1.gmadoa") == "10.0.2.132:5555" and "vm3.gmadoa" not in phones:
        phones["vm3.gmadoa"] = phones.pop("vm1.gmadoa")
    tablet.pop("vm4.gmadoa", None)  # ghost offline tablet serial

    # Drop offline serials — never drop during ADB timeout storms (keep sticky map)
    for name in list(phones.keys()):
        ser = phones[name]
        if ser not in live and not ser.startswith("10.0.2."):
            phones.pop(name, None)

    inject = {p: 8218 + int(p.split(".")[0][2:]) for p in phones}
    lock.update(
        {
            "phones": phones,
            "tablet": tablet,
            "inject": inject,
            "note": "cursor_monitor_tick",
            "updated": _utc(),
        }
    )
    LOCK.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return phones


def _merge_stealth_overrides(phones: dict[str, str], serials: list[str]) -> None:
    cur: dict = {}
    if OVERRIDES.is_file():
        cur = json.loads(OVERRIDES.read_text(encoding="utf-8-sig"))
    names = sorted(phones.keys(), key=lambda x: int(x.split(".")[0][2:]))
    serials_sorted = [phones[n] for n in names]
    cur.update(
        {
            "PHARMFLOW_FARM_PHONES": ",".join(names),
            "PHARMFLOW_ADB_SERIALS": ",".join(serials_sorted),
            "PHARMFLOW_FARM_PHONE_COUNT": str(len(names)),
            "PHARMFLOW_FARM_EXPECT_PHONES": str(len(names)),
            "PHARMFLOW_FARM_STOP": "0",
            "PHARMFLOW_FARM_UNIQUE_SEQ": "1",
            "PHARMFLOW_SKIP_SEQUENCE_ISOLATION": "0",
            "PHARMFLOW_NEVER_SHARE_EXIT_IP": "1",
            "PHARMFLOW_MANTIS_INJECT_PROXY": "1",
            "PHARMFLOW_TOR_PATH": r"C:\PharmFlow\bundled\tor.exe",
            "PHARMFLOW_TOR_HTTP_BASE": "8118",
            "PHARMFLOW_AUTOPILOT_PAUSE": "1",
            "cursor_monitor": _utc(),
        }
    )
    OVERRIDES.write_text(json.dumps(cur, indent=2) + "\n", encoding="utf-8")


def _repin_bad(phones: dict[str, str]) -> list[str]:
    adb = AdbWrapper()
    fixes: list[str] = []
    for name, ser in sorted(phones.items(), key=lambda x: int(x[0].split(".")[0][2:])):
        if ser.startswith("127.0.0.1:"):
            continue
        idx = int(name.split(".")[0][2:])
        port = 8218 + idx
        want = f"127.0.0.1:{port}"
        try:
            proxy = _read_guest_proxy(adb, ser)
        except Exception:
            proxy = None
        bad = proxy in (None, ":0", "null", "", "none") or (
            isinstance(proxy, str) and (proxy.endswith(":0") or want not in proxy)
        )
        if not bad:
            continue
        try:
            adb.reverse(str(port), str(port), serial=ser)
            ensure_inject_for_phone(adb, ser, idx, install_ca=False)
            pin_guest_proxy(adb, ser, idx)
            ok = verify_reverse_tunnel(adb, ser, port)
            got = _read_guest_proxy(adb, ser)
            fixes.append(f"{name}->{want} got={got} rev={ok}")
        except Exception as exc:
            fixes.append(f"{name}_repin_fail:{exc}")
    return fixes


def main() -> int:
    PAUSE_ADS.write_text(_utc() + " cursor_monitor", encoding="utf-8")
    fixes: list[str] = []

    prog, active_n, last_ln = _farm_progress()
    ok_phones = sum(1 for v in prog.values() if int(v) > 0)
    fixes.append(f"progress ok={ok_phones}/{len(prog) or '?'} active={active_n}")

    fixes.extend(_kill_dump_fighters())
    culled = cull_hung_adb(max_kill=25, min_age_s=20)
    if culled:
        fixes.append(f"cull_adb={culled}")

    live = set(_adb_live())
    fixes.append(f"adb_live={len(live)}")
    phones = _fix_serial_map(live)
    _merge_stealth_overrides(phones, list(phones.values()))
    fixes.extend(_repin_bad(phones))

    # vm7 relay serial in farm log — repin by name if still broken
    vm7_ser = phones.get("vm7.gmadoa")
    if vm7_ser and "127.0.0.1" in last_ln and "8225" in last_ln:
        fixes.extend(_repin_bad({"vm7.gmadoa": vm7_ser}))

    try:
        ssp = probe_ssp()
        paying = int(ssp.get("paying") or 0)
        house = int(ssp.get("house") or 0)
        fixes.append(f"ssp paying={paying} house={house}")
    except Exception as exc:
        paying, house = -1, -1
        fixes.append(f"ssp_err:{exc}")

    snap = gather_checkin(fixes=fixes, note="Cursor monitor tick · stealth ON")
    heartbeat("cursor", task="monitor_tick", note=f"ok={ok_phones} adb={len(live)}")
    set_status(
        adb_n=len(live),
        farm_up=snap.farm_up,
        verdict=snap.verdict,
        progress_ok=ok_phones,
        progress_total=len(prog),
        ssp_paying=paying,
        ssp_house=house,
        monitor_fixes=fixes[-12:],
        freebuff_lane="run agent_unison_freebuff_tick.py",
    )

    if ok_phones < max(1, len(prog) - 1) or "ADB timeout" in last_ln:
        (LOG / "FARM_RELOAD_FARM.flag").write_text("monitor_tick", encoding="utf-8")

    _echo(" | ".join(fixes[-14:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
