#!/usr/bin/env python3
"""Keep the farm worker alive in 24h day mode (daily visit/ad caps).

Default: --forever --hours 0 (no 6h cycle cutovers). Legacy --hours N still
supported for fixed windows.

  py -u scripts/run_farm_cycles.py --forever --hours 0
  py -u scripts/run_farm_cycles.py --cycles 4 --hours 6   # legacy

Starts the hourly ntfy digest (farm_hourly_ntfy.py) if it is not already running;
set PHARMFLOW_NTFY_DIGEST_INTERVAL=0 to disable it or to another seconds value.
START/DONE notifications are disabled unless PHARMFLOW_NTFY_CYCLE_EVENTS=1.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import automation.no_window  # noqa: E402,F401  (kill child console-window flashes)
from automation.farm_visit_caps import apply_runtime_overrides_to_env  # noqa: E402

LOG_DIR = Path(r"C:\PharmFlow\logs")
FARM_SCRIPT = ROOT / "scripts" / "run_farm_354.py"
CYCLE_LOG = LOG_DIR / "farm_cycles.log"
OVERRIDES = LOG_DIR / "farm_runtime_overrides.json"
TOPIC = "twskoops"


def cycle_ntfy_enabled() -> bool:
    return os.environ.get("PHARMFLOW_NTFY_CYCLE_EVENTS", "0").strip().lower() in {"1", "true", "yes", "on"}


def _merge_runtime_overrides(env: dict[str, str]) -> None:
    """Apply fail-review / operator-panel bumps before each cycle subprocess."""
    apply_runtime_overrides_to_env(env, log_dir=LOG_DIR)


def _phones_from_overrides() -> list[str] | None:
    """Operator dash writes PHARMFLOW_FARM_PHONES=vm0.gmadoa,vm1..."""
    if not OVERRIDES.exists():
        return None
    try:
        data = json.loads(OVERRIDES.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    raw = str(data.get("PHARMFLOW_FARM_PHONES") or "").strip()
    if not raw:
        return None
    phones = [p.strip().lstrip("\ufeff") for p in raw.split(",") if p.strip().lstrip("\ufeff").startswith("vm")]
    return phones or None


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _setup() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("farm_cycles")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(CYCLE_LOG, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)
    return log


log = _setup()


def ntfy(title: str, body: str, *, priority: str = "default", tags: str = "repeat,phone") -> None:
    if not cycle_ntfy_enabled():
        log.info("ntfy skipped cycle event title=%r", title)
        return
    # Share the global 1/hour cap with farm_checkin (never bypass).
    try:
        from automation.farm_checkin import publish_ntfy

        ok = publish_ntfy(title, body, tags=tags, priority=priority, force=False)
        log.info("ntfy %s %s", "OK" if ok else "throttled", title)
    except Exception as exc:
        log.warning("ntfy failed: %s", exc)


def _kill_existing_farm() -> None:
    try:
        from automation.process_scan import kill_matching

        # Only the farm worker — not this cycles wrapper.
        kill_matching("run_farm_354.py")
    except Exception:
        pass


def _ensure_proxy_watch(env: dict[str, str]) -> None:
    """Keep inject-proxy watcher alive — ad-fill :0 must be re-pinned within seconds."""
    try:
        import psutil
    except ImportError:
        return
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or []))
            if "watch_proxy_inject.py" in cmd:
                return
        except (psutil.Error, TypeError):
            continue
    watch_env = dict(env)
    watch_env.setdefault("PHARMFLOW_MANTIS_INJECT_PROXY", "1")
    watch_env.setdefault("PHARMFLOW_MANTIS_INJECT_MITM", "1")
    watch_env.setdefault("PHARMFLOW_PROXY_WATCH_INTERVAL", "3")
    from automation.win_subprocess import hidden_run_kwargs

    py = sys.executable
    if sys.platform == "win32":
        cand = Path(py).with_name("pythonw.exe")
        if cand.is_file():
            py = str(cand)
    subprocess.Popen(
        [py, "-u", str(ROOT / "scripts" / "watch_proxy_inject.py")],
        cwd=str(ROOT),
        env=watch_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **hidden_run_kwargs(),
    )
    log.info(
        "started watch_proxy_inject (interval=%ss)",
        watch_env.get("PHARMFLOW_PROXY_WATCH_INTERVAL", "3"),
    )


def _ensure_digest_reporter(env: dict[str, str]) -> None:
    """Keep the hourly ntfy digest alive so the operator gets a per-browser check-in."""
    log_dir = Path(os.environ.get("PHARMFLOW_LOG_DIR") or os.environ.get("PHARMFLOW_LOGS") or r"C:\PharmFlow\logs")
    if (log_dir / "NTFY_OFF.flag").is_file() or (log_dir / "NTFY_NO_AUTO_REPLY.flag").is_file():
        return
    interval = env.get("PHARMFLOW_NTFY_DIGEST_INTERVAL", "3600").strip() or "3600"
    if interval in {"0", "off", "false", "no"}:
        return
    try:
        import psutil
    except ImportError:
        return
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or []))
            if "farm_hourly_ntfy.py" in cmd:
                return
        except (psutil.Error, TypeError):
            continue
    from automation.win_subprocess import hidden_run_kwargs

    py = sys.executable
    if sys.platform == "win32":
        cand = Path(py).with_name("pythonw.exe")
        if cand.is_file():
            py = str(cand)
    subprocess.Popen(
        [
            py,
            "-u",
            str(ROOT / "scripts" / "farm_hourly_ntfy.py"),
            "--interval",
            interval,
            "--no-wait",
        ],
        cwd=str(ROOT),
        env=dict(env),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **hidden_run_kwargs(),
    )
    log.info("started farm_hourly_ntfy (interval=%ss)", interval)


def _ensure_fail_review(env: dict[str, str]) -> None:
    """Keep local fail-review alive — classifies FAILs and applies known fixes."""
    if env.get("PHARMFLOW_FAIL_REVIEW", "1").strip().lower() in {"0", "off", "false", "no"}:
        return
    try:
        import psutil
    except ImportError:
        return
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or []))
            if "farm_fail_review.py" in cmd:
                return
        except (psutil.Error, TypeError):
            continue
    from automation.win_subprocess import hidden_run_kwargs

    py = sys.executable
    if sys.platform == "win32":
        cand = Path(py).with_name("pythonw.exe")
        if cand.is_file():
            py = str(cand)
    subprocess.Popen(
        [py, "-u", str(ROOT / "scripts" / "farm_fail_review.py")],
        cwd=str(ROOT),
        env=dict(env),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **hidden_run_kwargs(),
    )
    log.info("started farm_fail_review")


def run_one_cycle(
    cycle: int,
    total: int | None,
    hours: float,
    env: dict[str, str],
    phones: list[str] | None = None,
) -> int:
    label = f"{cycle}/forever" if total is None else f"{cycle}/{total}"
    day_mode = float(hours) <= 0
    if day_mode:
        ntfy(
            f"PharmFlow 24h day {label} START",
            f"[PharmFlow] Starting 24h day mode {label} at {_utc()}\n"
            f"Daily visit/ad caps · midnight reset · 2h ntfy digests · fail review local-only",
            tags="rocket,phone",
        )
        log.info("day %s START (24h / daily caps, no hour cycle)", label)
    else:
        ntfy(
            f"PharmFlow window {label} START",
            f"[PharmFlow] Starting {hours:g}h farm window {label} at {_utc()}\n"
            f"Geo awake-window 09:30-00:00 · 2h ntfy digests only · fail review local-only",
            tags="rocket,phone",
        )
        log.info("window %s START hours=%.1f", label, hours)
    cycle_env = dict(env)
    _merge_runtime_overrides(cycle_env)
    # Honor operator browse mode (scramble|tor|direct). Isolation still wipes
    # cookies + new fingerprint/IMEI + unique exit when REQUIRE_UNIQUE_EXIT_IP=1.
    mode = str(cycle_env.get("PHARMFLOW_BROWSE_PROXY_MODE") or "").strip().lower()
    if mode not in ("scramble", "tor", "direct", "upstream"):
        mode = "scramble"
    cycle_env["PHARMFLOW_BROWSE_PROXY_MODE"] = mode
    cycle_env.setdefault("PHARMFLOW_REQUIRE_UNIQUE_EXIT_IP", "1")
    cycle_env["PHARMFLOW_FARM_STOP"] = "0"
    _ensure_proxy_watch(cycle_env)
    _ensure_digest_reporter(cycle_env)
    _ensure_fail_review(cycle_env)

    # If a farm is already running (manual start / prior cycle), adopt it instead of
    # spawning a second copy or killing a healthy mid-cycle farm.
    try:
        from automation.process_scan import pids_matching

        existing = pids_matching("run_farm_354.py")
    except Exception:
        existing = []
    if existing:
        log.info("cycle %s adopting existing farm pids=%s", label, existing)
        import psutil

        while True:
            alive = []
            for pid in existing:
                try:
                    if psutil.pid_exists(pid) and psutil.Process(pid).is_running():
                        alive.append(pid)
                except (psutil.Error, OSError):
                    continue
            if not alive:
                break
            time.sleep(15)
            existing = alive
        log.info("cycle %s adopted farm ended", label)
        rc = 0
    else:
        cmd = [sys.executable, "-u", str(FARM_SCRIPT), "--hours", str(hours)]
        if float(hours) <= 0:
            log.info("cycle %s DAY MODE (hours=0) — farm runs on daily budgets, no cycle cutover", label)
        if phones:
            cmd.append("--phones")
            cmd.extend(phones)
        from automation.win_subprocess import hidden_run_kwargs

        err_path = LOG_DIR / "farm_354_cycle_stderr.txt"
        out_path = LOG_DIR / "farm_354_cycle_stdout.txt"
        err_f = err_path.open("ab")
        out_f = out_path.open("ab")
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                env=cycle_env,
                stdout=out_f,
                stderr=err_f,
                **hidden_run_kwargs(),
            )
        finally:
            try:
                out_f.close()
                err_f.close()
            except Exception:
                pass
        log.info("cycle %s farm pid=%s", label, proc.pid)
        rc = proc.wait()
        log.info("cycle %s END rc=%s", label, rc)
        if rc not in (0, None):
            try:
                tail = err_path.read_text(encoding="utf-8", errors="replace")[-800:]
                if tail.strip():
                    log.warning("cycle %s stderr tail: %s", label, tail.strip())
            except OSError:
                pass
    if total is None:
        next_msg = "Continuing 24h day mode…" if day_mode else "Starting next forever window…"
    elif cycle < total:
        next_msg = "Starting next window…"
    else:
        next_msg = f"All {total} windows complete."
    if day_mode:
        ntfy(
            f"PharmFlow 24h day {label} DONE",
            f"[PharmFlow] Farm process ended {label} rc={rc} at {_utc()}\n{next_msg}",
            tags="white_check_mark,phone" if rc == 0 else "warning,phone",
            priority="default" if rc == 0 else "high",
        )
    else:
        ntfy(
            f"PharmFlow window {label} DONE",
            f"[PharmFlow] Finished {hours:g}h window {label} rc={rc} at {_utc()}\n{next_msg}",
            tags="white_check_mark,phone" if rc == 0 else "warning,phone",
            priority="default" if rc == 0 else "high",
        )
    return int(rc or 0)


def _acquire_single_instance_lock() -> bool:
    """Refuse to start when another cycles supervisor is already alive.

    The 2026-09-13 incident: multiple supervisors (manual + ensure respawn)
    each ran the no-kill adopt loop, but with --no-kill omitted each new
    supervisor killed the previous supervisor's worker (rc=15 boot loop).
    Lock = pid + create_time, verified with psutil so stale pid reuse cannot
    pass. Returns True when THIS process is the sole supervisor.
    """
    import psutil

    lock = LOG_DIR / "run_farm_cycles.singleton.lock"
    me = os.getpid()
    try:
        if lock.is_file():
            raw = json.loads(lock.read_text(encoding="utf-8-sig"))
            other_pid = int(raw.get("pid") or 0)
            other_ctime = float(raw.get("create_time") or 0.0)
            if other_pid > 0 and psutil.pid_exists(other_pid):
                try:
                    proc = psutil.Process(other_pid)
                    if (
                        proc.is_running()
                        and abs(proc.create_time() - other_ctime) < 1.0
                        and "run_farm_cycles" in " ".join(proc.cmdline() or []).lower()
                    ):
                        log.info("single-instance: cycles already running pid=%s — exiting", other_pid)
                        return False
                except (psutil.Error, OSError):
                    pass
    except (json.JSONDecodeError, OSError, ValueError):
        pass
    me_ctime = psutil.Process(me).create_time()
    lock.write_text(
        json.dumps({"pid": me, "create_time": me_ctime}, separators=(",", ":")),
        encoding="utf-8",
    )
    log.info("single-instance lock acquired pid=%s", me)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=4, help="Number of cycles (ignored with --forever)")
    ap.add_argument(
        "--forever",
        action="store_true",
        help="Repeat H-hour cycles forever (Ctrl+C / kill process to stop)",
    )
    ap.add_argument(
        "--hours",
        type=float,
        default=0.0,
        help="Hours per cycle. 0 = day mode (daily budgets, farm runs without cycle restarts).",
    )
    ap.add_argument(
        "--phones",
        nargs="*",
        default=None,
        help="Optional phone names passed through to run_farm_354.py --phones",
    )
    ap.add_argument("--no-kill", action="store_true", help="Do not kill existing farm first")
    args = ap.parse_args()

    if not _acquire_single_instance_lock():
        return 0
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PHARMFLOW_ALLOW_SEQUENCE_RUNS"] = "1"
    env["PHARMFLOW_FARM_STOP"] = "0"
    env.setdefault("PHARMFLOW_FARM_PATHS", "1,2,3")
    env.setdefault("PHARMFLOW_FARM_ALLOW_ADS", "1")
    env["PHARMFLOW_SKIP_MANTIS_PATCH"] = "0"
    env.setdefault("PHARMFLOW_DABFLOW_MANTIS_PATCH", "1")
    env.setdefault("PHARMFLOW_EMULATOR_AD_FILL_WAIT", "4")
    env.setdefault("PHARMFLOW_EMULATOR_AD_MODE", "1")
    env.setdefault("PHARMFLOW_EMULATOR_AD_FORCE_DIRECT", "1")
    env.setdefault("PHARMFLOW_EMULATOR_AD_FALLBACK", "1")
    env.setdefault("PHARMFLOW_MANTIS_INJECT_PROXY", "1")
    env.setdefault("PHARMFLOW_MANTIS_INJECT_MITM", "1")
    env.setdefault("PHARMFLOW_FARM_SEQS_PER_HOUR", "15")
    env.setdefault("PHARMFLOW_FARM_PATH3_PER_HOUR", "1")
    _merge_runtime_overrides(env)
    mode = str(env.get("PHARMFLOW_BROWSE_PROXY_MODE") or "").strip().lower()
    if mode not in ("scramble", "tor", "direct", "upstream"):
        mode = "scramble"
    env["PHARMFLOW_BROWSE_PROXY_MODE"] = mode
    env.setdefault("PHARMFLOW_REQUIRE_UNIQUE_EXIT_IP", "1")
    env.setdefault("PHARMFLOW_GEO_TIME_WINDOW", "1")
    env.setdefault("PHARMFLOW_GEO_WINDOW_START", "09:30")
    env.setdefault("PHARMFLOW_GEO_WINDOW_END", "00:00")
    env.setdefault("PHARMFLOW_AGE_GATE_WAIT", "0.8")
    env.setdefault("PHARMFLOW_DABFLOW_LOAD_WAIT", "2.0")

    if not args.no_kill:
        _kill_existing_farm()
        time.sleep(2)

    forever = bool(args.forever) or int(args.cycles) <= 0
    total: int | None = None if forever else int(args.cycles)
    day_mode = float(args.hours) <= 0
    if day_mode:
        plan = "24h DAY MODE forever (daily visit/ad caps, midnight reset — no hour cycles)"
    elif forever:
        plan = f"forever x {args.hours:g}h windows (no end)"
    else:
        plan = f"{total} windows × {args.hours:g}h (~{(total or 0) * args.hours:g}h total)"
    ntfy(
        "PharmFlow 24h day plan armed" if day_mode else (
            "PharmFlow forever plan armed" if forever else f"PharmFlow {total}×{args.hours:g}h plan armed"
        ),
        f"[PharmFlow] Running {plan}. Routine ntfy is 2h digest only. "
        f"Failed sequences will be reviewed/fixed locally.",
        tags="calendar,phone",
    )
    log.info("plan armed: %s", plan)

    phones = list(args.phones) if args.phones else None
    # Do not force sticky phone lists into run_farm_354 — it adapts to live ADB.
    if phones:
        log.info("phones CLI preference (farm still adapts to online): %s", phones)

    worst = 0
    cycle = 0
    fail_streak = 0
    while True:
        cycle += 1
        rc = run_one_cycle(cycle, total, float(args.hours), env, phones=phones)
        worst = max(worst, abs(rc))
        if total is not None and cycle >= total:
            break
        # Forever: back off hard on crash loops so a bad override cannot peg CPU.
        if rc not in (0, None):
            fail_streak += 1
            pause = min(300.0, 15.0 * fail_streak)
            log.warning("cycle rc=%s fail_streak=%s pause=%.0fs", rc, fail_streak, pause)
            time.sleep(pause)
        else:
            fail_streak = 0
            time.sleep(15)
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
