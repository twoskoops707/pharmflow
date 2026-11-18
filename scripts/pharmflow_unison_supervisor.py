#!/usr/bin/env python3
"""PharmFlow unison supervisor — four lanes, one stack.

Lane 1: run_farm_354.py              — sequences / Path3 / money worker
Lane 2: pharmflow_stealth_guard.py      — tor, inject, ADB, GPU, dash
Lane 3: farm_watchdog.py             — evidence monitor + FARM_MONITOR_NOW
Lane 4: agent_unison_freebuff_loop.py — SSP paying, flat-$, path3 OK (FREEBUFF)

PharmFlow.exe Start Farm spawns THIS script (not ensure_farm / remediator soup).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = Path(r"C:\PharmFlow\logs")
PID_FILE = LOG / "pharmflow_unison_supervisor.pid"
STATE_FILE = LOG / "pharmflow_unison_state.json"
sys.path.insert(0, str(ROOT))

import automation.no_window  # noqa: F401

from automation.pharmflow_farm_config import (  # noqa: E402
    apply_farm_env,
    reset_runtime,
)

from automation.pharmflow_unison_dedupe import dedupe_keep_newest  # noqa: E402
from automation.singleton_liveness import check_tick  # noqa: E402
from automation.ssp_paying_hunter_lane import (  # noqa: E402
    ensure_pharmflow_paying_hunter,
    process_is_pharmflow_hunter,
)

LANES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # ADB bond keeper: holds/repairs/starts the adb connection to every known
    # emulator serial from the first second of farm setup onward. Runs BEFORE
    # the farm lane so phones are on adb before adoption, and keeps re-attaching
    # them when the adb server drops them. Never churns VMs.
    ("adb-keeper", "adb_bond_keeper.py", ()),
    ("farm", "run_farm_354.py", ()),
    # Inject keepalive is money-critical (holds 8242–8249). Previously only
    # spawned opportunistically by self-heal/stealth — if it died, inject could
    # stay down for a full heal cadence. Supervise it like every other lane.
    ("inject-keep", "pharmflow_inject_keepalive.py", ()),
    ("stealth", "pharmflow_stealth_guard.py", ()),
    ("watchdog", "farm_watchdog.py", ()),
    ("freebuff", "agent_unison_freebuff_loop.py", ()),
    # Money lanes: the bottom-ads watcher keeps ad slots visible/repaired and
    # the SSP paying hunter keeps the shared paying-fill cache stocked. They
    # used to depend on whoever happened to spawn them (money remediate is
    # retired) — dying silently and freezing impressions. Supervised here so
    # the EXE self-heals them like every other lane.
    ("ads-watch", "watch_bottom_ads.py", ()),
    ("ssp-hunter", "ssp_paying_hunter.py", ()),
    # Mantis autopilot — the closed earning loop (fetch real Mantis payouts →
    # gauge → steer → apply overrides → wake on red). This is the loop that
    # drove the Jul/Aug earning months in FamFlow's ensure_farm_24x7 manager.
    # The unison supervisor never learned this lane, so it went dormant at the
    # cutover and the farm lost its tuning + paying-window capture. Supervised
    # like every other lane; loop mode sleeps 120-180min but wakes early on
    # yellow/red tones or the autopilot_wake.flag file.
    ("autopilot", "mantis_autopilot.py", ()),
    # Money monitor as its own lane: keeps FARM_MONEY_HEALTH.json fresh even
    # when the operator dash is down — stale $0.00 data made the watchdog
    # panic-fix (kill watcher) over ghost problems. Runs the module directly
    # (automation/ path) in loop mode.
    ("money-mon", "farm_money_monitor.py", ("loop", "--tick", "90")),
    # Process reaper: watches the live process table and kills provably stale
    # duplicates/orphans (duplicate adb fork-servers, orphaned adb/shell
    # clients stuck >180s, duplicate Tor data dirs). Never touches farm-owned
    # or adopted processes. Keeps the machine lean while the farm earns.
    ("reaper", "pharmflow_watchdog.py", ("--watch", "--apply", "--reap-interval", "60")),
    # LLM farm manager (FreeLLMAPI via cloud_agent.json). EXE-owned monitor that
    # inspects ADB/farm logs and applies safe repairs — no emu kill.
    ("ai-farm", "pharmflow_ai_farm_loop.py", ()),
)
INTERVAL_S = float(os.environ.get("PHARMFLOW_UNISON_INTERVAL_S", "45"))
FLAGS = 0x08000000  # CREATE_NO_WINDOW


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pyw() -> str:
    """Deps-complete interpreter (cryptography) for lane children.

    Native-ARM64 Windows python has no cryptography wheel, so spawning with
    sys.executable on ARM boxes kills every lane child at import. Prefer a
    system pythonw that can import the full stack.
    """
    try:
        from automation.runtime_paths import helper_python

        found = helper_python()
        if found:
            return found
    except Exception:
        pass
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    return pyw if Path(pyw).is_file() else sys.executable


def _pid_alive_is_supervisor(pid: int) -> bool:
    """True only if *pid* is still this supervisor script (not a recycled PID)."""
    if pid <= 0:
        return False
    try:
        import psutil
    except ImportError:
        # No psutil: existence probe only (best effort).
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False
    try:
        proc = psutil.Process(pid)
        if not proc.is_running():
            return False
        cmd = " ".join(str(x) for x in (proc.cmdline() or []))
        return "pharmflow_unison_supervisor.py" in cmd and "-c" not in cmd
    except Exception:
        # AccessDenied / race: do not claim a foreign PID is the supervisor.
        return False


def _lane_pids() -> dict[str, list[int]]:
    out: dict[str, list[int]] = {name: [] for name, *_ in LANES}
    try:
        import psutil
    except ImportError:
        return out
    needles = {name: script for name, script, _ in LANES}
    try:
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                argv = list(proc.info.get("cmdline") or [])
                cmd = " ".join(str(x) for x in argv)
                pid = int(proc.info.get("pid") or 0)
            except (TypeError, ValueError, psutil.Error):
                continue
            for name, script in needles.items():
                if script not in cmd or "-c" in cmd:
                    continue
                # ssp-hunter: FamFlow/CPharm basename matches must NOT count —
                # they blocked PharmFlow spawn (tip-150 HUNTER_EXE_CHILD=0).
                if name == "ssp-hunter":
                    try:
                        if not process_is_pharmflow_hunter(psutil.Process(pid)):
                            continue
                    except (psutil.Error, OSError):
                        continue
                out[name].append(pid)
    except Exception:
        # A process can die while process_iter materializes attrs — psutil then
        # raises from the iterator itself. Partial results are fine; a scan must
        # NEVER take the supervisor down (2026-09-19 crash loop).
        pass
    return out


def _have_process_scan() -> bool:
    try:
        import psutil  # noqa: F401

        return True
    except ImportError:
        return False


def _spawn_lane(name: str, script: str, args: tuple[str, ...] = ()) -> int | None:
    path = ROOT / "scripts" / script
    if not path.is_file():
        path = ROOT / "tools" / script
    if not path.is_file():
        path = ROOT / "automation" / script
    if not path.is_file():
        return None
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["PHARMFLOW_EXE_OWNED_FARM"] = "1"
    apply_farm_env(env)
    # Operator standing rule: every sequence isolates (cookies/FP/IP/proxy/IMEI).
    env["PHARMFLOW_SKIP_SEQUENCE_ISOLATION"] = "0"
    env["PHARMFLOW_ALLOW_SEQUENCE_RUNS"] = "1"
    proc = subprocess.Popen(
        [_pyw(), "-u", str(path), *args],
        cwd=str(ROOT),
        env=env,
        creationflags=FLAGS if sys.platform == "win32" else 0,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return proc.pid


def _stealth_gate_blocks_farm() -> bool:
    """HARD RULE (2026-10-09): do not respawn farm while stealth gate is down."""
    gate = LOG / "FARM_STEALTH_GATE_STOP.json"
    stop = LOG / "PHARMFLOW_FARM_STOP.flag"
    if gate.is_file():
        return True
    if stop.is_file():
        try:
            return "stealth_gate" in stop.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
    return False


_STEALTH_GATE_BLOCKED_LANES = frozenset(
    {
        "farm",
        "ads-watch",
        "ssp-hunter",
        "autopilot",
        "freebuff",
        "ai-farm",
    }
)


def _ensure_lanes() -> list[str]:
    notes: list[str] = []
    # Without a process scanner, refuse to spawn — otherwise every interval
    # forks another copy of every lane (respawn storm).
    if not _have_process_scan():
        notes.append("skip_spawn_no_psutil")
        return notes
    for _name, script, _args in LANES:
        # Ownership-aware ensure for ssp-hunter (culls FamFlow/CPharm blockers).
        if _name == "ssp-hunter":
            continue
        extras = dedupe_keep_newest(script)
        for pid in extras:
            notes.append(f"dedupe_{script}:{pid}")
    pids = _lane_pids()
    gate_block = _stealth_gate_blocks_farm()
    if gate_block:
        notes.append("stealth_gate_active")
    else:
        # Paying hunter required while farm runs — never optional, never FamFlow.
        notes.extend(ensure_pharmflow_paying_hunter(root=ROOT, cull_foreign=True))
    for name, script, args in LANES:
        if name == "ssp-hunter":
            # Handled by ensure_pharmflow_paying_hunter (ownership-aware).
            continue
        if gate_block and name in _STEALTH_GATE_BLOCKED_LANES:
            continue
        if pids.get(name):
            continue
        pid = _spawn_lane(name, script, args)
        if pid:
            notes.append(f"spawn_{name}={pid}")
        else:
            notes.append(f"missing_{name}")
    return notes


def _ensure_freebuff_queue() -> list[str]:
    """Refresh FREEBUFF task queue on AGENT_UNISON.json (idempotent)."""
    notes: list[str] = []
    assign = ROOT / "scripts" / "agent_unison_assign_freebuff.py"
    if not assign.is_file():
        return notes
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        proc = subprocess.run(
            [_pyw(), "-u", str(assign)],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=FLAGS if sys.platform == "win32" else 0,
        )
        if proc.returncode == 0:
            notes.append("freebuff_queue_assigned")
        else:
            notes.append(f"freebuff_assign_rc={proc.returncode}")
    except (OSError, subprocess.TimeoutExpired) as exc:
        notes.append(f"freebuff_assign_err:{exc}")
    return notes


def _kill_legacy_stack() -> list[str]:
    """Retire competing babysit scripts — unison owns the stack now."""
    killed: list[str] = []
    keepalive_markers = (
        "pharmflow_inject_keepalive.py",
        "_arm_inject_keepalive.py",
    )
    retire = (
        "ensure_farm_24x7.py",
        "keep_farm_alive.py",
        "farm_remediate_loop.py",
        "farm_health_monitor.py",
        "emu_overnight_watchdog.py",
        "farm_midnight_watch.py",
        "agent_unison_freebuff_tick.py",
        "cpharm_unison_supervisor.py",
        "automation.dashboard",
        "-m automation.dashboard",
        "run_farm_cycles.py",
        "_fix_tor_inject",
        "_money_arm_inject",
        "scripts/_fix_",
        "scripts/_flash_",
        "run_mantis_inject_proxies.py",
        # FREEBUFF lane owns agent_unison_freebuff_loop; do not kill it here.
        # watch_bottom_ads / ssp_paying_hunter are supervised LANES now.
    )
    try:
        import psutil

        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or []))
            except (psutil.Error, TypeError, ValueError):
                continue
            if any(marker in cmd for marker in keepalive_markers):
                continue
            for needle in retire:
                if needle in cmd and "-c" not in cmd:
                    try:
                        proc.terminate()
                        killed.append(f"{needle}:{proc.info['pid']}")
                    except (psutil.Error, TypeError):
                        pass
    except ImportError:
        pass
    return killed


def main() -> int:
    LOG.mkdir(parents=True, exist_ok=True)
    if PID_FILE.is_file():
        try:
            old = int(PID_FILE.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            old = 0
            PID_FILE.unlink(missing_ok=True)
        else:
            if _pid_alive_is_supervisor(old):
                print("pharmflow_unison_supervisor already running", flush=True)
                return 0
            PID_FILE.unlink(missing_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    reset_runtime(note="unison_start")
    apply_farm_env()
    # Dash/EXE operator file wins over code SSOT (Path3 off until operator enables).
    try:
        from wizard.farm_settings import apply_saved_to_env

        n_saved = apply_saved_to_env()
    except Exception as exc:  # noqa: BLE001
        n_saved = 0
        boot_notes_err = f"apply_saved_err:{exc}"
    else:
        boot_notes_err = ""
    boot_notes = _ensure_freebuff_queue()
    if n_saved:
        boot_notes.append(f"operator_settings={n_saved}")
    if boot_notes_err:
        boot_notes.append(boot_notes_err)
    try:
        from automation.farm_exe_self_heal import run_self_heal

        heal = run_self_heal(reason="unison_boot")
        boot_notes.extend((heal.get("fixes") or [])[:8])
    except Exception as exc:
        boot_notes.append(f"self_heal_boot_err:{exc}")
    print(
        f"pharmflow_unison_supervisor pid={os.getpid()} "
        f"lanes={[n for n, _s, _a in LANES]} "
        f"{' '.join(boot_notes)}",
        flush=True,
    )
    tick = 0
    try:
        while True:
            try:
                notes = _kill_legacy_stack() + _ensure_lanes()
                tick += 1
                # Singleton liveness metric: alert when any pidfile-gated
                # singleton has zero running instances for more than one
                # tick (the keep-newest dedupe kill/revive signature).
                try:
                    live = check_tick(tick_s=INTERVAL_S)
                    if live.get("alert"):
                        notes.extend(f"singleton_down:{a}" for a in live.get("alerts") or [])
                except Exception as exc:
                    notes.append(f"singleton_liveness_err:{exc}")
                # Self-heal every other interval — tor seed, ghost prune, inject/tor down.
                if tick % 2 == 0:
                    try:
                        from automation.farm_exe_self_heal import run_self_heal

                        heal = run_self_heal(reason="unison_tick")
                        notes.extend(
                            f"heal:{x}" for x in (heal.get("fixes") or []) if "ok" not in str(x)
                        )
                    except Exception as exc:
                        notes.append(f"self_heal_err:{exc}")
            except Exception as exc:
                # Uncaught lane ensure used to kill the supervisor; stealth /
                # keep-alive then respawned → crash/respawn loop.
                print(f"{_utc()} ensure_lanes soft-fail: {exc}", flush=True)
                time.sleep(max(20.0, INTERVAL_S))
                continue
            if notes:
                try:
                    try:
                        pids_now = _lane_pids()
                    except Exception:
                        pids_now = {}
                    STATE_FILE.write_text(
                        json.dumps(
                            {"ts": _utc(), "notes": notes, "pids": pids_now},
                            indent=2,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                except OSError as exc:
                    print(f"{_utc()} state write soft-fail: {exc}", flush=True)
                print(f"{_utc()} {' '.join(notes[:10])}", flush=True)
            time.sleep(max(20.0, INTERVAL_S))
    except KeyboardInterrupt:
        pass
    finally:
        PID_FILE.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
