"""Keep farm running: cull dead procs, ensure remediator+dash, reconnect ADB.

Long-running companion to remediator. Safe to run one instance.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = Path(r"C:\CPharm\logs")
OUT = LOG / "_keep_farm_alive.json"
REMEDIATOR = ROOT / "scripts" / "farm_remediate_loop.py"
DASH = ROOT / "scripts" / "farm_operator_dash.py"
HUNTER = ROOT / "scripts" / "ssp_paying_hunter.py"
ADB = r"C:\CPharm\bundled\adb.exe"
if not Path(ADB).is_file():
    ADB = "adb"

INTERVAL_S = float(os.environ.get("CPHARM_KEEPALIVE_INTERVAL_S", "90"))
sys.path.insert(0, str(ROOT))

import automation.no_window  # noqa: E402,F401
from automation.cpharm_unison_dedupe import pids_for_script  # noqa: E402
from automation.farm_health_audit import apply_money_rails  # noqa: E402
from automation.farm_process_janitor import sweep_dead_processes  # noqa: E402


def _unison_active() -> bool:
    try:
        return bool(pids_for_script("cpharm_unison_supervisor.py"))
    except Exception:
        return False


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_shell_fix_if_needed() -> list[str]:
    """Scrub User-env braces that kill Cursor agent PowerShell wrapper."""
    flag = LOG / "FARM_FIX_SHELL.flag"
    report = LOG / "_shell_fix_report.json"
    script = Path(r"C:\CPharm\logs\fix_cursor_shell.py")
    if not script.is_file():
        script = ROOT / "_tmp_fix_cursor_shell.py"
    if not script.is_file():
        return ["shell_fix_missing"] if flag.is_file() else []
    # Only run when operator/agent drops the flag — never every keepalive tick.
    if not flag.is_file():
        return []
    if report.is_file():
        try:
            flag.unlink(missing_ok=True)
        except OSError:
            pass
        return []
    try:
        subprocess.run(
            [sys.executable, str(script)],
            cwd=str(ROOT),
            timeout=60,
            capture_output=True,
        )
        flag.unlink(missing_ok=True)
        return ["shell_fix_ran"]
    except Exception as exc:
        return [f"shell_fix_err:{exc}"]


def _port_ok(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2.0):
            return True
    except OSError:
        return False


def _spawn(script: Path, extra: list[str] | None = None) -> int | None:
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    if not Path(pyw).is_file():
        pyw = sys.executable
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env.setdefault("CPHARM_ALLOW_SEQUENCE_RUNS", "1")
    env.setdefault("CPHARM_FARM_STOP", "0")
    env["CPHARM_EXE_OWNED_FARM"] = "1"
    flags = 0x08000000  # CREATE_NO_WINDOW only — never OR DETACHED_PROCESS
    proc = subprocess.Popen(
        [pyw, "-u", str(script), *(extra or [])],
        cwd=str(ROOT),
        env=env,
        creationflags=flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return proc.pid


def _farm_354_pids() -> list[int]:
    try:
        import psutil
    except ImportError:
        return []
    found: list[int] = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or [])).lower()
        except (psutil.Error, TypeError, ValueError):
            continue
        if "run_farm_354.py" in cmd and "-c" not in cmd:
            found.append(int(proc.info["pid"]))
    return found


def ensure_farm_worker() -> list[str]:
    """CPharm owns the farm, but the money worker is pythonw run_farm_354.

    Frozen EXE + CPHARM_EXE_OWNED.flag made MEI ensure skip spawn, so a dead
    worker stayed dead (0 clicks). Respawn from FamFlow, never from MEI.
    """
    from automation.farm_pause import farm_halted

    if farm_halted():
        return ["farm_halted_skip_spawn"]
    if _farm_354_pids():
        return []
    farm = ROOT / "scripts" / "run_farm_354.py"
    if not farm.is_file():
        return ["farm_script_missing"]
    pid = _spawn(farm, ["--hours", "0.0"])
    return [f"spawn_farm_354 pid={pid}"]


def cull() -> list[str]:
    """Reap hung ADB, orphan consoles, leak bash/wsl, duplicate helpers."""
    return list(sweep_dead_processes())


def ensure_remediator() -> list[str]:
    fixes: list[str] = []
    reload_flag = LOG / "FARM_RELOAD_REMEDIATOR.flag"
    force_reload = reload_flag.is_file()
    if force_reload:
        try:
            reload_flag.unlink(missing_ok=True)
        except OSError:
            pass
        fixes.append("FARM_RELOAD_REMEDIATOR.flag")
    rem_age_s = -1.0
    try:
        import psutil

        alive = False
        for p in psutil.process_iter(["pid", "cmdline", "create_time"]):
            cmd = " ".join(p.info.get("cmdline") or [])
            if "farm_remediate_loop" in cmd and "-c" not in cmd:
                alive = True
                try:
                    rem_age_s = max(
                        rem_age_s, time.time() - float(p.info.get("create_time") or 0)
                    )
                except (TypeError, ValueError):
                    rem_age_s = 9999.0
    except Exception:
        alive = False
    # Fresh honest = remediator ticking. Missing honest for a young process is
    # startup lag — do NOT kill/respawn (that caused thrash loops).
    honest = LOG / "FARM_HONEST_NOW.txt"
    fresh = False
    try:
        if honest.is_file() and (time.time() - honest.stat().st_mtime) < 180:
            fresh = True
    except OSError:
        pass
    if alive and not force_reload and (fresh or rem_age_s < 180.0):
        return fixes
    if alive and (force_reload or not fresh):
        # hung remediator (alive, old, stale honest) OR forced code reload
        try:
            import psutil

            for p in psutil.process_iter(["pid", "cmdline"]):
                cmd = " ".join(p.info.get("cmdline") or [])
                if "farm_remediate_loop" in cmd and "-c" not in cmd:
                    p.kill()
                    fixes.append(f"kill_stale_rem:{p.pid}")
        except Exception:
            pass
        time.sleep(1)
        pid = _spawn(REMEDIATOR)
        fixes.append(f"respawn_remediator pid={pid}")
        return fixes
    if not alive:
        pid = _spawn(REMEDIATOR)
        fixes.append(f"spawn_remediator pid={pid}")
        time.sleep(2)
    return fixes


def ensure_hunter() -> list[str]:
    """Paying fill hunter must stay up; house-only Path3 otherwise skips every click."""
    from automation.farm_money_monitor import _cull_duplicate_hunters

    return _cull_duplicate_hunters()


def ensure_dash() -> list[str]:
    """Only spawn if nothing is listening; cull duplicate dash scripts first."""
    try:
        from automation.process_scan import cull_duplicates_keep_newest

        cull_duplicates_keep_newest(("farm_operator_dash.py",))
    except Exception:
        pass
    if _port_ok(8091):
        return []
    pid = _spawn(DASH)
    return [f"spawn_dash pid={pid}"]


def reconnect_serials() -> list[str]:
    fixes: list[str] = []
    try:
        ov = json.loads((LOG / "farm_runtime_overrides.json").read_text(encoding="utf-8-sig"))
        serials = [s.strip() for s in str(ov.get("CPHARM_ADB_SERIALS") or "").split(",") if s.strip()]
    except Exception:
        serials = []
    for ser in serials:
        try:
            r = subprocess.run([ADB, "connect", ser], capture_output=True, text=True, timeout=6)
            out = (r.stdout or r.stderr or "").strip()[:60]
            if "connected" in out.lower() or "already" in out.lower():
                fixes.append(f"adb_connect_ok {ser}")
            else:
                fixes.append(f"adb_connect {ser} {out}")
        except Exception as exc:
            fixes.append(f"adb_connect_err {ser}:{exc}")
    return fixes


def cycle() -> dict:
    fixes: list[str] = []
    try:
        from automation.process_scan import cull_duplicates_keep_newest

        fixes.extend(cull_duplicates_keep_newest())
    except Exception as exc:
        fixes.append(f"singleton_cull_err:{exc}")
    try:
        from automation.farm_pause import farm_halted, is_killed, is_paused

        if farm_halted():
            fixes.append("killed_skip" if is_killed() else "paused_skip")
            return {
                "ts": _utc(),
                "paused": True,
                "dash_up": _port_ok(8091),
                "fixes": fixes,
            }
    except Exception:
        pass
    fixes.extend(_run_shell_fix_if_needed())
    fixes.extend(cull())
    fixes.extend(ensure_dash())
    fixes.extend(ensure_remediator())
    fixes.extend(ensure_hunter())
    fixes.extend(ensure_farm_worker())
    # reconnect when honest shows offline or every ~5 cycles via flag file
    stamp = LOG / "_last_keepalive_reconnect.txt"
    do_reconnect = True
    try:
        if stamp.is_file() and (time.time() - stamp.stat().st_mtime) < 300:
            do_reconnect = False
    except OSError:
        pass
    if do_reconnect:
        fixes.extend(reconnect_serials()[:8])
        stamp.write_text(_utc(), encoding="utf-8")
    honest_age = -1.0
    try:
        honest_age = time.time() - (LOG / "FARM_HONEST_NOW.txt").stat().st_mtime
    except OSError:
        pass

    # Farm hot-reload flag (seq-fix code path) — keepalive can apply even if
    # remediator is still on an older in-memory copy.
    farm_flag = LOG / "FARM_RELOAD_FARM.flag"
    if farm_flag.is_file():
        # Do not kill mid-sequence — stale progress locks wedge unique-seq.
        # Keep the flag when skipped so reload retries once sequences drain.
        prog_path = LOG / "farm_354_progress.json"
        skip_reload = False
        try:
            prog = json.loads(prog_path.read_text(encoding="utf-8-sig"))
            act = prog.get("active_sequences") or prog.get("active_keys") or []
            if isinstance(act, dict):
                act = list(act.keys())
            if act:
                skip_reload = True
                fixes.append("SKIP_RELOAD active_sequences_present")
        except Exception:
            pass
        if skip_reload:
            fixes.append("KEEPALIVE_FARM_RELOAD_SKIPPED")
        else:
            try:
                farm_flag.unlink(missing_ok=True)
            except OSError:
                pass
            fixes.append("KEEPALIVE_FARM_RELOAD")
            try:
                import psutil

                for p in psutil.process_iter(["pid", "cmdline"]):
                    cmd = " ".join(p.info.get("cmdline") or [])
                    if "run_farm_354" in cmd and "-c" not in cmd:
                        try:
                            p.kill()
                            fixes.append(f"kill_farm:{p.pid}")
                        except Exception:
                            pass
                time.sleep(2)
                pid = _spawn(ROOT / "scripts" / "run_farm_354.py", ["--hours", "0.0"])
                fixes.append(f"spawn_farm_354 pid={pid}")
            except Exception as exc:
                fixes.append(f"farm_reload_err:{exc}")

    # Lightweight sticky / money tripwires — APPLY rails, don't just log.
    try:
        ov = json.loads((LOG / "farm_runtime_overrides.json").read_text(encoding="utf-8-sig"))
        ipv = float(ov.get("CPHARM_IPV_STICKY") or ov.get("CPHARM_FARM_IMPRESSIONS_PER_VISIT") or 0)
        seqs = int(float(ov.get("CPHARM_FARM_SEQS_PER_HOUR") or 0))
        site = {}
        try:
            site = json.loads((LOG / "farm_site_lock.json").read_text(encoding="utf-8-sig"))
        except Exception:
            site = {}
        visits = str(site.get("daily_visits_csv") or "")
        need_heat = ipv > 40 or seqs > 36 or ("500" in visits) or ("490" in visits)
        gap = int(float(ov.get("CPHARM_FARM_PATH3_GLOBAL_GAP_MIN") or 0))
        p3_hr = int(float(ov.get("CPHARM_PATH3_PER_HOUR") or 0))
        farm_p3_hr = int(float(ov.get("CPHARM_FARM_PATH3_PER_HOUR") or 0))
        req_pay = str(ov.get("CPHARM_PATH3_REQUIRE_PAYING") or "")
        try:
            dwell_bad = float(ov.get("CPHARM_AD_DWELL_MAX") or 0) > 12.0
        except (TypeError, ValueError):
            dwell_bad = False
        need_path3 = (
            gap > 0
            or p3_hr < 8
            or farm_p3_hr < 8
            or req_pay in ("1", "true", "yes", "on")
            or dwell_bad
            or str(ov.get("CPHARM_EMULATOR_AD_FORCE_DIRECT") or "") != "1"
        )
        if need_heat:
            fixes.extend(
                f"KEEPALIVE_{x}"
                for x in apply_money_rails(mode="hold", reason="keepalive_cap_ipv")
            )
        elif need_path3:
            fixes.extend(
                f"KEEPALIVE_{x}"
                for x in apply_money_rails(mode="hold", reason="keepalive_path3_gap")
            )
        elif (LOG / "FARM_HEAT_DOWN.flag").is_file():
            try:
                (LOG / "FARM_HEAT_DOWN.flag").unlink(missing_ok=True)
            except OSError:
                pass
            fixes.extend(
                f"KEEPALIVE_{x}" for x in apply_money_rails(mode="hold", reason="clear_heat")
            )
    except Exception as exc:
        fixes.append(f"keepalive_sticky_err:{exc}")

    if honest_age > 180:
        fixes.append(f"KEEPALIVE_HONEST_STALE={honest_age:.0f}s")
        # ensure_remediator already respawns; force another pass
        fixes.extend(ensure_remediator())

    state = {
        "ts": _utc(),
        "dash_up": _port_ok(8091),
        "honest_age_s": round(honest_age, 1),
        "fixes": fixes,
    }
    OUT.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(f"[keepalive] dash={state['dash_up']} honest_age={honest_age:.0f}s fixes={len(fixes)}", flush=True)
    return state


def main() -> int:
    LOG.mkdir(parents=True, exist_ok=True)
    if _unison_active():
        print("keep_farm_alive: unison supervisor owns stack — exiting", flush=True)
        return 0
    print(f"keep_farm_alive start interval={INTERVAL_S}s", flush=True)
    while True:
        t0 = time.time()
        try:
            cycle()
        except Exception as exc:
            try:
                OUT.write_text(json.dumps({"ts": _utc(), "error": str(exc)}) + "\n", encoding="utf-8")
            except OSError:
                pass
            print(f"[keepalive] ERROR {exc}", flush=True)
        time.sleep(max(20.0, INTERVAL_S - (time.time() - t0)))


if __name__ == "__main__":
    raise SystemExit(main())
