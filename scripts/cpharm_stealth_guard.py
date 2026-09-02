#!/usr/bin/env python3
"""Lane 2 — internet / stealth / lights / inject / ADB / FarmBrowser. No override JSON."""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = Path(r"C:\CPharm\logs")
sys.path.insert(0, str(ROOT))

import automation.no_window  # noqa: E402,F401

from automation.cpharm_farm_config import apply_farm_env, purge_legacy_override_files  # noqa: E402
from automation.cpharm_farmbrowser_guard import ensure_phones_farmbrowser  # noqa: E402
from automation.cpharm_unison_dedupe import dedupe_keep_newest, pids_for_script  # noqa: E402

INTERVAL_S = float(os.environ.get("CPHARM_STEALTH_GUARD_INTERVAL_S", "60"))
PID_FILE = LOG / "cpharm_stealth_guard.pid"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_inject_and_dash() -> list[str]:
    fixes: list[str] = []
    fixes.extend(dedupe_keep_newest("run_mantis_inject_proxies.py"))
    fixes.extend(dedupe_keep_newest("farm_operator_dash.py"))
    try:
        from scripts.farm_remediate_loop import ensure_dash_up

        fixes.extend(ensure_dash_up()[:3])
    except Exception as exc:
        fixes.append(f"dash_err:{exc}")
    if pids_for_script("run_mantis_inject_proxies.py"):
        return fixes
    try:
        import subprocess

        from automation.farm_phone_discover import inject_listener_count

        span = max(8, inject_listener_count())
        pyw = sys.executable.replace("python.exe", "pythonw.exe")
        if not Path(pyw).is_file():
            pyw = sys.executable
        script = ROOT / "scripts" / "run_mantis_inject_proxies.py"
        if script.is_file():
            env = os.environ.copy()
            env["PYTHONPATH"] = str(ROOT)
            apply_farm_env(env)
            subprocess.Popen(
                [pyw, "-u", str(script), "--phones", str(span)],
                cwd=str(ROOT),
                env=env,
                creationflags=0x08000000,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            fixes.append(f"spawn_inject span={span}")
    except Exception as exc:
        fixes.append(f"inject_err:{exc}")
    return fixes


def _tick() -> list[str]:
    from scripts import farm_remediate_loop as rem

    fixes: list[str] = []
    fixes.extend(_ensure_inject_and_dash())
    try:
        from automation.farm_pause import farm_halted

        if farm_halted():
            fixes.append("farm_halted")
            return fixes
    except Exception:
        pass
    try:
        (LOG / "_stealth_guard_heartbeat.txt").write_text(_utc() + "\n", encoding="utf-8")
    except OSError:
        pass
    fixes.extend(rem.ensure_farm_reload_if_flagged())
    fixes.extend(rem.reconnect_missing(rem.adb_online()))
    online = rem.adb_online()
    rows, coord = rem.coordinate_phones(online)
    fixes.extend(coord[:10])
    # FarmBrowser: install + lawnchair stop — skip UI re-arm when sequences active.
    try:
        n_actives = 0
        prog = LOG / "farm_354_progress.json"
        if prog.is_file():
            import json

            pdata = json.loads(prog.read_text(encoding="utf-8-sig"))
            n_actives = len(pdata.get("active") or [])
        fixes.extend(
            ensure_phones_farmbrowser(rows, allow_ui_rearm=(n_actives == 0))[:8]
        )
    except Exception as exc:
        fixes.append(f"fb_guard_err:{exc}")
    try:
        from automation.exit_ip_guard import enforce_farm_unique_exit_ips
        from automation.tor_manager import TorManager

        ip_rows = [
            (r["name"], r["serial"], int(r["name"].split(".")[0][2:]))
            for r in rows
            if r.get("state") == "device" and r.get("serial")
        ]
        if ip_rows:
            tor = TorManager()
            fixes.extend(enforce_farm_unique_exit_ips(tor, tor.adb, ip_rows)[:10])
    except Exception as exc:
        fixes.append(f"exit_ip_err:{exc}")
    try:
        from automation.mumu_fingerprint import (
            ensure_windows_gpu_prefs_for_mumu,
            reassert_all_vm_gpu_accel,
        )
        from wizard.wizard_paths import mumu_vms_dir

        vms = mumu_vms_dir() or Path(r"C:\Program Files\Netease\MuMuPlayer\vms")
        gfix = ensure_windows_gpu_prefs_for_mumu()
        gfix.extend(reassert_all_vm_gpu_accel(vms))
        fixes.extend(gfix[:4])
    except Exception as exc:
        fixes.append(f"gpu_err:{exc}")
    return fixes


def main() -> int:
    if PID_FILE.is_file():
        try:
            old = int(PID_FILE.read_text(encoding="utf-8").strip())
            os.kill(old, 0)
            print("cpharm_stealth_guard already running", flush=True)
            return 0
        except (OSError, ValueError, ProcessLookupError):
            PID_FILE.unlink(missing_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    apply_farm_env()
    purge_legacy_override_files()
    print(f"cpharm_stealth_guard start interval={INTERVAL_S}s", flush=True)
    try:
        while True:
            try:
                fixes = _tick()
                if fixes:
                    print(f"{_utc()} {' '.join(fixes[:8])}", flush=True)
            except Exception as exc:
                print(f"{_utc()} STEALTH_ERR {exc}", flush=True)
            time.sleep(max(15.0, INTERVAL_S))
    finally:
        PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
