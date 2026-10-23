#!/usr/bin/env python3
"""Wait for FARM_PAUSED_UNTIL, then cold-start the full money stack from snapshot."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LOG = Path(r"C:\PharmFlow\logs")
INTERVAL_S = 30.0


def _count(needle: str) -> int:
    try:
        import psutil

        n = 0
        for p in psutil.process_iter(["cmdline"]):
            if needle in " ".join(p.info.get("cmdline") or []):
                n += 1
        return n
    except Exception:
        return 0


def _spawn(script: str, *extra: str) -> int | None:
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    if not Path(pyw).is_file():
        pyw = sys.executable
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    from automation.farm_visit_caps import apply_runtime_overrides_to_env

    apply_runtime_overrides_to_env(env, log_dir=LOG)
    env["PHARMFLOW_FARM_STOP"] = "0"
    env["PHARMFLOW_FARM_UNIQUE_SEQ"] = "1"
    env["PHARMFLOW_FARM_CHROMIUM_ONLY"] = "0"
    env["PHARMFLOW_FARM_BROWSERS"] = "chromium,firefox,brave"
    env["PHARMFLOW_FARM_PATH3_BROWSERS"] = "chromium,firefox,brave"
    proc = subprocess.Popen(
        [pyw, "-u", str(ROOT / "scripts" / script), *extra],
        cwd=str(ROOT),
        env=env,
        creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0) or 0x08000000,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.pid


def resume_stack() -> dict:
    from automation.farm_pause import apply_operator_config_to_overrides, clear_pause, is_paused

    if is_paused():
        return {"skipped": "still_paused"}

    fixes: list[str] = []
    fixes.extend(apply_operator_config_to_overrides())
    clear_pause()

    # Reconnect ADB from snapshot
    snap_path = LOG / "farm_midnight_snapshot.json"
    if snap_path.is_file():
        try:
            snap = json.loads(snap_path.read_text(encoding="utf-8-sig"))
            adb = r"C:\PharmFlow\bundled\adb.exe"
            if not Path(adb).is_file():
                adb = "adb"
            for row in snap.get("phones") or []:
                ser = str(row.get("serial") or "").strip()
                if ser:
                    subprocess.run([adb, "connect", ser], capture_output=True, timeout=10)
        except Exception as exc:
            fixes.append(f"adb_connect_err:{exc}")

    # Same visual stack: dash already up; start money workers.
    if _count("farm_operator_dash") < 1:
        fixes.append(f"dash pid={_spawn('farm_operator_dash.py')}")
    n_phones = 6
    try:
        cfg = json.loads((LOG / "farm_operator_config.json").read_text(encoding="utf-8-sig"))
        n_phones = max(6, int(cfg.get("phones_expect") or 6))
    except Exception:
        n_phones = 6
    fixes.append(f"inject pid={_spawn('run_mantis_inject_proxies.py', '--phones', str(n_phones), '--no-install-ca')}")
    fixes.append(f"remediator pid={_spawn('farm_remediate_loop.py')}")
    fixes.append(f"keepalive pid={_spawn('keep_farm_alive.py')}")
    fixes.append(f"watch_ads pid={_spawn('watch_bottom_ads.py', 'loop', '--loop', '120')}")
    fixes.append(f"cycles pid={_spawn('run_farm_cycles.py', '--forever', '--hours', '0', '--no-kill')}")

    honest = (
        f"FARM RESUMED {time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
        f"DASH http://127.0.0.1:8091/\n"
        f"fixes: {fixes}\n"
    )
    (LOG / "FARM_HONEST_NOW.txt").write_text(honest, encoding="utf-8")
    out = {"ts": time.time(), "fixes": fixes}
    (LOG / "_farm_midnight_resume.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> int:
    from automation.farm_pause import is_paused, pause_state, seconds_until_resume

    LOG.mkdir(parents=True, exist_ok=True)
    (LOG / "_midnight_watch_heartbeat.txt").write_text(
        json.dumps({"started": time.time(), "state": pause_state()}), encoding="utf-8"
    )
    resumed = False
    while True:
        try:
            (LOG / "_midnight_watch_heartbeat.txt").write_text(
                json.dumps(
                    {
                        "ts": time.time(),
                        "paused": is_paused(),
                        "seconds_left": round(seconds_until_resume(), 1),
                    }
                ),
                encoding="utf-8",
            )
            if not is_paused():
                if not resumed:
                    resume_stack()
                    resumed = True
                    # Stay alive but idle — ensure won't double-spawn if already up.
                time.sleep(120.0)
                continue
            time.sleep(INTERVAL_S)
        except Exception as exc:
            try:
                (LOG / "_midnight_watch_error.txt").write_text(str(exc), encoding="utf-8")
            except OSError:
                pass
            time.sleep(60.0)


if __name__ == "__main__":
    raise SystemExit(main())
