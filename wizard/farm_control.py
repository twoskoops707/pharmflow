"""Start/stop the multi-phone farm from the EXE (any Site Profile)."""

from __future__ import annotations

import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import automation.no_window  # noqa: F401  — CREATE_NO_WINDOW for farm/helper children
from automation.site_profile import SiteProfile, load_profile
from automation.mantis_farm_math import apply_plan_to_environ, plan_for_phones
from automation.cpharm_farm_config import apply_farm_env, purge_legacy_override_files
from automation.cpharm_exe_owned import (
    clear_exe_owned,
    exe_owns_farm,
    mark_exe_owned,
)
from automation.farm_visit_caps import MULTI_BROWSER, PATH3_BROWSERS, enforce_multi_browser
from automation.win_subprocess import hidden_run_kwargs
from scripts.farm_hourly_ntfy import run_reporter
from wizard.wizard_paths import app_data_root, bundle_root, load_config, sequences_dir


_farm_proc: subprocess.Popen[Any] | None = None
_farm_thread: threading.Thread | None = None
_digest_thread: threading.Thread | None = None
_digest_stop = threading.Event()
_farm_lock = threading.RLock()
_helper_lock = threading.RLock()
_PHONE_NAMES = tuple(f"vm{i}.gmadoa" for i in range(12))
_TABLET_PHONE = "vm4.gmadoa"
_STICKY_OVERRIDES = Path(r"C:\CPharm\logs\farm_runtime_overrides.json")
_EXTERNAL_FARM_NEEDLES = (
    "run_farm_354.py",
    "run_farm_cycles.py",
)
# Unison supervisor owns farm + stealth + watchdog. Dash only helper besides unison.
_HELPER_SPECS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("suppress_console_flash.py", (), "suppress_console_flash.py"),
    ("farm_operator_dash.py", (), "farm_operator_dash.py"),
    ("cpharm_unison_supervisor.py", (), "cpharm_unison_supervisor.py"),
)
# stop_farm must tear down the whole stack — start_farm never sets _farm_proc.
_STOP_FARM_NEEDLES = (
    "cpharm_unison_supervisor.py",
    "farm_operator_dash.py",
    "suppress_console_flash.py",
    "run_farm_354.py",
    "run_farm_cycles.py",
    "cpharm_stealth_guard.py",
    "farm_watchdog.py",
    "agent_unison_freebuff_loop.py",
)
_helper_procs: dict[str, subprocess.Popen[Any]] = {}
_helper_threads: dict[str, threading.Thread] = {}


def _inject_span() -> str:
    """Inject listener count from CPharm-live VMs (vmN → N+1 ports)."""
    try:
        from automation.farm_phone_discover import inject_listener_count

        return str(max(1, int(inject_listener_count())))
    except Exception:
        return "11"


def _helper_script_path(name: str) -> Path | None:
    root = bundle_root()
    script = root / "scripts" / name
    if script.is_file():
        return script
    alt = Path(__file__).resolve().parents[1] / "scripts" / name
    return alt if alt.is_file() else None


_probe_cache: dict[tuple[str, str], bool] = {}


def _python_can_import(python_exe: str, module: str) -> bool:
    """True when python_exe can actually import module (cached probe).

    Existence of pythonw.exe says nothing about which packages it has — a
    flask-less interpreter made the operator dash die silently at startup.
    """
    key = (python_exe, module)
    if key in _probe_cache:
        return _probe_cache[key]
    ok = False
    try:
        proc = subprocess.run(
            [python_exe, "-c", f"import {module}"],
            capture_output=True,
            timeout=20,
            **hidden_run_kwargs(),
        )
        ok = proc.returncode == 0
    except Exception:
        ok = False
    _probe_cache[key] = ok
    return ok


def _resolve_helper_python(*, requires: str = "psutil") -> str | None:
    """Return a real python/pythonw for helper processes.

    Frozen CPharm.exe cannot re-exec ``CPharm.exe -u script.py`` as a headless
    worker. Prefer system pythonw; None means fall back to in-process threads.
    ``requires`` names a module the helper needs — candidates are probed so a
    python without the package is skipped instead of silently crashing the
    helper at startup.
    """
    if not getattr(sys, "frozen", False):
        exe = sys.executable
        # Prefer pythonw when it has the package; if pythonw is flask-less
        # (common on ARM PATH installs) fall back to python.exe instead of
        # returning None and silently dropping to a broken in-process dash.
        if os.name == "nt" and exe.lower().endswith("python.exe"):
            pyw = exe[:-10] + "pythonw.exe"
            if Path(pyw).is_file() and _python_can_import(pyw, requires):
                return pyw
        return exe if _python_can_import(exe, requires) else None

    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates: list[Path] = []
    # The frozen bundle extracts .pyd extensions compiled for the SAME CPython
    # that built it (sys.version_info). Helper lanes run under a real pythonw
    # with the bundle on sys.path, so a version mismatch kills every lane with
    # "Module use of pythonXXX.dll conflicts with this version of Python".
    # Prefer a pythonw matching the build version before anything else.
    maj, minor = sys.version_info[:2]
    candidates = [
        local / "Python" / f"pythoncore-{maj}.{minor}-64" / "pythonw.exe",
        local / "Programs" / "Python" / f"Python{maj}{minor}" / "pythonw.exe",
        Path(f"C:\\Python{maj}{minor}\\pythonw.exe"),
    ]
    candidates += [
        local / "Python" / "pythoncore-3.14-64" / "pythonw.exe",
        local / "Python" / "pythoncore-3.13-64" / "pythonw.exe",
        local / "Python" / "pythoncore-3.12-64" / "pythonw.exe",
        local / "Programs" / "Python" / "Python312" / "pythonw.exe",
        local / "Programs" / "Python" / "Python311" / "pythonw.exe",
        Path(r"C:\Python312\pythonw.exe"),
        Path(r"C:\Python311\pythonw.exe"),
    ]
    for cand in candidates:
        if cand.is_file() and "CPharm" not in str(cand):
            if _python_can_import(str(cand), requires):
                return str(cand)
    for name in ("pythonw", "python"):
        found = shutil.which(name)
        if found and "CPharm" not in found and _python_can_import(found, requires):
            return found
    return None


def _helper_already_alive(needle: str) -> bool:
    """True when a helper matching *needle* is already our child or on the bus.

    Checks owned ``_helper_procs`` first (psutil cmdline is often AccessDenied
    right after spawn). Skips ``python -c`` probe processes so an import probe
    cannot look like a live dash/unison worker.
    """
    for name, proc in list(_helper_procs.items()):
        if needle not in name and name not in needle:
            continue
        try:
            if proc.poll() is None:
                return True
        except OSError:
            continue
    try:
        import psutil
    except ImportError:
        thr = _helper_threads.get(needle)
        return bool(thr and thr.is_alive())
    self_pid = os.getpid()
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            pid = int(proc.info.get("pid") or 0)
            if pid in {0, self_pid}:
                continue
            parts = [str(x) for x in (proc.info.get("cmdline") or [])]
            # Needle can appear inside a ``-c "…farm_operator_dash…"`` probe.
            if any(p == "-c" for p in parts):
                continue
            cmd = " ".join(parts)
            if needle in cmd:
                return True
        except (psutil.Error, TypeError, ValueError):
            continue
    thr = _helper_threads.get(needle)
    return bool(thr and thr.is_alive())


def _spawn_helper_thread(
    name: str,
    script: Path,
    argv_extra: tuple[str, ...],
    *,
    log: Callable[[str, str], None] | None,
) -> None:
    """Run a long-lived helper inside the EXE when no system python exists."""

    def _log(msg: str, level: str = "ok") -> None:
        if log:
            log(msg, level)

    def target() -> None:
        old_argv = list(sys.argv)
        try:
            sys.argv = [str(script), *argv_extra]
            runpy.run_path(str(script), run_name="__main__")
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 0
            _log(f"helper {name} exited (code={code})", "ok" if code == 0 else "warn")
        except Exception as exc:  # noqa: BLE001 — keep EXE farm up
            _log(f"helper {name} crashed: {exc}", "err")
        finally:
            sys.argv = old_argv

    t = threading.Thread(target=target, name=f"cpharm-{Path(name).stem}", daemon=True)
    _helper_threads[name] = t
    t.start()
    _log(f"spawned {name} in-process thread={t.name}", "ok")


def ensure_operator_stack(*, log: Callable[[str, str], None] | None = None) -> list[str]:
    """Bring up remediator, dash, keepalive, ensure, inject, hunter, watch_ads.

    Start Farm must own the FIX + money path — not leave operators on a separate
    python babysit stack. Frozen EXE prefers system pythonw for true processes;
    otherwise helpers run as daemon threads via runpy (same pattern as farm).
    """
    notes: list[str] = []

    def _log(msg: str, level: str = "ok") -> None:
        if log:
            log(msg, level)
        notes.append(f"{level}:{msg}")

    with _helper_lock:
        root = bundle_root()
        spawn_kw = hidden_run_kwargs()
        # Helper lanes have different package needs — the dash needs flask, the rest
        # need psutil. Resolve per-helper so a flask-less python never silently
        # kills the dash at startup (proven failure on this ARM64 box).
        _helper_requires = {
            "farm_operator_dash.py": "flask",
        }
        helper_py_by_require: dict[str, str | None] = {}

        def _helper_python_for(name: str) -> str | None:
            req = _helper_requires.get(name, "psutil")
            if req not in helper_py_by_require:
                helper_py_by_require[req] = _resolve_helper_python(requires=req)
                if helper_py_by_require[req]:
                    _log(f"operator helpers ({req}) via {helper_py_by_require[req]}", "ok")
                else:
                    _log(f"no system python with {req} — {name} runs in-process", "warn")
            return helper_py_by_require[req]

        for name, argv_extra, needle in _HELPER_SPECS:
            if name == "run_mantis_inject_proxies.py":
                argv_extra = ("--phones", str(_inject_span()))
            if _helper_already_alive(needle):
                _log(f"operator stack already up: {name}", "ok")
                continue
            script = _helper_script_path(name)
            if script is None:
                _log(f"operator stack missing: {name}", "err")
                continue
            env = os.environ.copy()
            env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
            env.setdefault("CPHARM_FARM_STOP", "0")
            helper_py = _helper_python_for(name)
            if helper_py:
                try:
                    proc = subprocess.Popen(
                        [helper_py, "-u", str(script), *argv_extra],
                        cwd=str(root if (root / "automation").is_dir() else script.parent.parent),
                        env=env,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        **spawn_kw,
                    )
                    # Flask-less / bad PYTHONPATH dies in <1s with DEVNULL — surface it.
                    time.sleep(0.7)
                    if proc.poll() is not None:
                        _log(
                            f"spawn {name} died immediately (code={proc.returncode}) "
                            "— trying in-process",
                            "warn",
                        )
                        _spawn_helper_thread(name, script, argv_extra, log=log)
                    else:
                        _helper_procs[name] = proc
                        _log(f"spawned {name} pid={proc.pid}", "ok")
                except OSError as exc:
                    _log(f"spawn {name} failed: {exc} — trying in-process", "warn")
                    _spawn_helper_thread(name, script, argv_extra, log=log)
            else:
                _spawn_helper_thread(name, script, argv_extra, log=log)
        return notes


OPERATOR_DASH_URL = "http://127.0.0.1:8091/"
_dash_browser_opened = False


def open_operator_dashboard(
    *,
    log: Callable[[str, str], None] | None = None,
    wait_s: float = 45.0,
    open_browser: bool = False,
) -> bool:
    """Ensure operator dash is listening on :8091.

    Does **not** open a browser tab by default — repeated Start farm / agent
    restarts were spawning dash tabs forever. Pass ``open_browser=True`` only
    for the explicit UI button.
    """
    import urllib.error
    import urllib.request

    global _dash_browser_opened

    def _log(msg: str, level: str = "ok") -> None:
        if log:
            log(msg, level)

    ensure_operator_stack(log=log)
    deadline = time.time() + max(1.0, float(wait_s))
    up = False
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(OPERATOR_DASH_URL, timeout=2) as resp:
                if int(getattr(resp, "status", 200) or 200) == 200:
                    up = True
                    break
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            time.sleep(0.4)
    if up:
        _log("Farm Operator dash :8091 UP", "ok")
    else:
        _log("Dash :8091 still starting", "warn")
    if open_browser and not _dash_browser_opened:
        import webbrowser

        webbrowser.open(OPERATOR_DASH_URL)
        _dash_browser_opened = True
        _log("Opened Farm Operator dash once in browser", "ok")
    return up


def external_python_farm_running() -> bool:
    """True when FamFlow python money-path farm/cycles are already alive."""
    try:
        import psutil
    except ImportError:
        return False
    self_pid = os.getpid()
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            pid = int(proc.info.get("pid") or 0)
            if pid in {0, self_pid}:
                continue
            cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or [])).lower()
            if any(needle in cmd for needle in _EXTERNAL_FARM_NEEDLES):
                return True
        except (psutil.Error, TypeError, ValueError):
            continue
    return False


def stop_external_python_farm(
    *,
    log: Callable[[str, str], None] | None = None,
) -> list[int]:
    """Kill external run_farm_354 / run_farm_cycles so CPharm can own the path."""

    def _log(msg: str, level: str = "ok") -> None:
        if log:
            log(msg, level)

    killed: list[int] = []
    try:
        import psutil
    except ImportError:
        _log("psutil missing — cannot stop external farm", "err")
        return killed
    self_pid = os.getpid()
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            pid = int(proc.info.get("pid") or 0)
            if pid in {0, self_pid}:
                continue
            cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or [])).lower()
            if not any(needle in cmd for needle in _EXTERNAL_FARM_NEEDLES):
                continue
            proc.kill()
            killed.append(pid)
        except (psutil.Error, TypeError, ValueError, OSError):
            continue
    if killed:
        _log(f"took over — stopped external farm pids={killed}", "ok")
        time.sleep(1.5)
    else:
        _log("no external farm/cycles to stop", "ok")
    return killed


def farm_running() -> bool:
    """True if unison supervisor or farm worker is alive."""
    with _farm_lock:
        if _farm_proc is not None and _farm_proc.poll() is None:
            return True
        if _farm_thread is not None and _farm_thread.is_alive():
            return True
    # In-process / owned-child unison counts — start_farm never sets _farm_proc.
    if _helper_already_alive("cpharm_unison_supervisor.py"):
        return True
    try:
        from automation.cpharm_unison_dedupe import pids_for_script

        if pids_for_script("cpharm_unison_supervisor.py"):
            return True
    except ImportError:
        pass
    return external_python_farm_running()


def _kill_farm_stack(*, log: Callable[[str, str], None] | None = None) -> list[int]:
    """Terminate owned helper Popen children + matching stack needles."""

    def _log(msg: str, level: str = "ok") -> None:
        if log:
            log(msg, level)

    killed: list[int] = []
    with _helper_lock:
        for name, proc in list(_helper_procs.items()):
            try:
                if proc.poll() is None:
                    pid = int(proc.pid)
                    try:
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                    except OSError:
                        pass
                    killed.append(pid)
            except (OSError, TypeError, ValueError):
                pass
            _helper_procs.pop(name, None)
    try:
        import psutil
    except ImportError:
        if killed:
            _log(f"stopped owned helper pids={killed}", "ok")
        return killed
    self_pid = os.getpid()
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            pid = int(proc.info.get("pid") or 0)
            if pid in {0, self_pid} or pid in killed:
                continue
            parts = [str(x) for x in (proc.info.get("cmdline") or [])]
            if any(p == "-c" for p in parts):
                continue
            cmd = " ".join(parts)
            if not any(needle in cmd for needle in _STOP_FARM_NEEDLES):
                continue
            proc.kill()
            killed.append(pid)
        except (psutil.Error, TypeError, ValueError, OSError):
            continue
    if killed:
        _log(f"farm stack stopped pids={killed}", "ok")
        time.sleep(0.8)
    return killed


def _apply_sticky_overrides() -> None:
    """SSOT from code — no farm_runtime_overrides.json."""
    purge_legacy_override_files()
    apply_farm_env()


def _persist_multi_browser_sticky() -> None:
    """No-op — browsers pinned in cpharm_farm_config.py."""
    return


def _dabflow_sequence_root() -> Path | None:
    """Resolve the operator dabflow pool (900x1600/no-ad + ad dabflow sequences).

    Returns None when no on-disk pool exists so callers keep the runtime
    default rather than inventing a path.
    """
    if os.environ.get("CPHARM_FARM_SEQUENCE_ROOT", "").strip():
        return None
    # dabflow money pool is the v3 runtime recordings tree (ad/complete/halfway
    # combos per material), not the legacy v0 sequences/900x1600 matrix.
    for cand in (
        Path(r"C:\CPharm\automation\recordings\sequences"),
        Path.home() / "CPharm" / "automation" / "recordings" / "sequences",
    ):
        if _dir_has_v3_sequences(cand):
            return cand
    for cand in (
        Path(r"C:\CPharm\sequences"),
        Path.home() / "CPharm" / "sequences",
        Path(r"C:\Users\jsmil\CPharm\sequences"),
    ):
        if _dir_has_v3_sequences(cand):
            return cand
    return None


def _dir_has_v3_sequences(cand: Path) -> bool:
    """True when the dir contains any v3+ sequence JSON (runnable by the farm)."""
    if not cand.is_dir():
        return False
    import json as _json

    try:
        it = cand.rglob("*.json")
        for _i, path in enumerate(it):
            if _i >= 200:
                break
            try:
                data = _json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and int(data.get("sequence_version") or 0) >= 3:
                return True
    except OSError:
        return False
    return False


def _apply_dabflow_pool_env() -> None:
    pool = _dabflow_sequence_root()
    if pool is not None:
        os.environ["CPHARM_FARM_SEQUENCE_ROOT"] = str(pool)


def apply_profile_farm_env(profile: SiteProfile | None) -> None:
    """Map SiteProfile farm prefs onto CPHARM_FARM_* env for the runner.

    Sticky overrides win. Money-day defaults: scramble + FORCE_DIRECT=0 + FALLBACK=0.
    """
    _apply_sticky_overrides()
    os.environ["CPHARM_ALLOW_SEQUENCE_RUNS"] = "1"
    # Keep Mantis zone refresh on so ads paint on Path1/2/3 (Path3 only clicks).
    os.environ["CPHARM_SKIP_MANTIS_PATCH"] = "0"
    os.environ.setdefault("CPHARM_DABFLOW_MANTIS_PATCH", "1")
    os.environ.setdefault("CPHARM_EMULATOR_AD_FILL_WAIT", "4")
    os.environ.setdefault("CPHARM_EMULATOR_AD_MODE", "1")
    # Money-day rails (sticky may already set these).
    os.environ.setdefault("CPHARM_EMULATOR_AD_FORCE_DIRECT", "0")
    os.environ.setdefault("CPHARM_EMULATOR_AD_FALLBACK", "0")
    os.environ.setdefault("CPHARM_BROWSE_PROXY_MODE", "scramble")
    os.environ["CPHARM_REQUIRE_UNIQUE_EXIT_IP"] = "1"
    os.environ["CPHARM_NEVER_SHARE_EXIT_IP"] = "1"
    os.environ.setdefault("CPHARM_FARM_PATHS", "1,2,3")
    os.environ.setdefault("CPHARM_FARM_PATH3", "1")
    os.environ.setdefault("CPHARM_PATH3", "1")
    os.environ.setdefault("CPHARM_FARM_ALLOW_ADS", "1")
    os.environ.setdefault("CPHARM_FARM_UNIQUE_SEQ", "1")
    # Unique-seq Path1/2 needs dedicated stems per browser — sticky must not lock chromium-only.
    os.environ["CPHARM_FARM_CHROMIUM_ONLY"] = "0"
    os.environ["CPHARM_FARM_BROWSERS"] = MULTI_BROWSER
    os.environ["CPHARM_FARM_PATH3_BROWSERS"] = PATH3_BROWSERS
    _persist_multi_browser_sticky()
    os.environ.setdefault("CPHARM_SITE_SLUG", "dabflow")
    os.environ.setdefault("CPHARM_SKIP_SEQUENCE_ISOLATION", "0")
    # MITM inject: billing_direct + prefer-paying (no house fallback) live in
    # automation.mantis_inject_proxy / dabflow_mantis_client_patch — keep ON.
    os.environ.setdefault("CPHARM_MANTIS_INJECT_PROXY", "1")
    os.environ.setdefault("CPHARM_MANTIS_INJECT_MITM", "1")
    os.environ.setdefault("CPHARM_MANTIS_BILLING_DIRECT", "1")
    # AP DOWN by default so EXE Start cannot fight sticky Path3/ads.
    os.environ.setdefault("CPHARM_AUTOPILOT_PAUSE", "1")
    os.environ.setdefault("CPHARM_GEO_TIME_WINDOW", "1")
    os.environ.setdefault("CPHARM_GEO_WINDOW_START", "09:30")
    os.environ.setdefault("CPHARM_GEO_WINDOW_END", "00:00")
    if profile is None:
        # Plan fills gaps only — sticky CPHARM_* already applied above.
        plan = plan_for_phones(int(os.environ.get("CPHARM_FARM_PHONE_COUNT") or 4))
        _apply_plan_gaps(plan)
        # dabflow is the default site — without an active profile the lane must
        # still point at the on-disk pool, never the empty bundle recordings dir.
        slug = os.environ.get("CPHARM_SITE_SLUG", "dabflow").strip() or "dabflow"
        if slug == "dabflow":
            _apply_dabflow_pool_env()
        return
    f = profile.farm
    phone_count = max(1, min(len(_PHONE_NAMES), int(f.phone_count)))
    if os.environ.get("CPHARM_FARM_PHONE_COUNT"):
        try:
            phone_count = max(1, min(len(_PHONE_NAMES), int(os.environ["CPHARM_FARM_PHONE_COUNT"])))
        except ValueError:
            pass
    plan = plan_for_phones(
        phone_count,
        visits_csv=str(
            os.environ.get("CPHARM_FARM_DAILY_VISITS")
            or getattr(f, "daily_visits_csv", "")
            or ""
        ),
        ads_csv=str(
            os.environ.get("CPHARM_FARM_DAILY_ADS")
            or getattr(f, "daily_ads_csv", "")
            or ""
        ),
        impressions_per_visit=float(
            os.environ.get("CPHARM_FARM_IMPRESSIONS_PER_VISIT")
            or getattr(f, "impressions_per_visit", 22.0)
            or 22.0
        ),
    )
    _apply_plan_gaps(plan)
    os.environ.setdefault("CPHARM_FARM_ALLOW_ADS", "1" if f.allow_ads else "0")
    os.environ.setdefault(
        "CPHARM_NTFY_INTERVAL_S", str(max(300, int(f.ntfy_interval_s)))
    )
    # Money-day short stagger only. Sticky already applied above (force).
    # Never invent profile 30-min spreads (1800/306) — that stagnated actives.
    os.environ.setdefault("CPHARM_FARM_START_STAGGER_WINDOW", "120")
    os.environ.setdefault("CPHARM_FARM_START_STAGGER_BAND", "120")
    os.environ.setdefault("CPHARM_FARM_START_STAGGER_MIN_GAP", "15")
    os.environ.setdefault("CPHARM_FARM_START_STAGGER_JITTER", "40")
    # If a long profile-era value leaked into process env (not sticky), snap it.
    try:
        win_now = float(os.environ.get("CPHARM_FARM_START_STAGGER_WINDOW") or "0")
    except ValueError:
        win_now = 0.0
    if win_now > 300.0:
        os.environ["CPHARM_FARM_START_STAGGER_WINDOW"] = "120"
        os.environ["CPHARM_FARM_START_STAGGER_BAND"] = "120"
        os.environ["CPHARM_FARM_START_STAGGER_MIN_GAP"] = "15"
        os.environ["CPHARM_FARM_START_STAGGER_JITTER"] = "40"
    os.environ.setdefault("CPHARM_FARM_PHONE_COUNT", str(phone_count))
    os.environ.setdefault("CPHARM_SITE_SLUG", profile.slug)
    if profile.adapter == "dabflow":
        # dabflow pools live on disk as <root>/900x1600/{no-ad,ad}/dabflow__*.json.
        # Never drop to the empty bundle recordings dir — that strands the farm
        # with zero sequences.
        _apply_dabflow_pool_env()
    else:
        os.environ.setdefault(
            "CPHARM_FARM_SEQUENCE_ROOT", str(sequences_dir() / profile.slug)
        )
    if f.ntfy_topic:
        os.environ.setdefault("CPHARM_NTFY_TOPIC", f.ntfy_topic)
    if profile.humanize.concurrent_unique_sequences:
        os.environ["CPHARM_FARM_UNIQUE_SEQ"] = "1"
    else:
        os.environ.setdefault("CPHARM_FARM_UNIQUE_SEQ", "0")


def _apply_plan_gaps(plan: Any) -> None:
    """Apply mantis plan env only where sticky/env has no value yet."""
    before = {k: v for k, v in os.environ.items() if k.startswith("CPHARM_")}
    apply_plan_to_environ(plan)
    for key, old in before.items():
        os.environ[key] = old


def _farm_args(script: Path, hours: float, profile: SiteProfile | None) -> list[str]:
    """Hours only — live ADB phones are discovered inside run_farm_354 via CPharm."""
    return [str(script), "--hours", str(hours)]


def _farm_script() -> Path:
    root = bundle_root()
    cand = root / "scripts" / "run_farm_354.py"
    if cand.is_file():
        return cand
    alt = Path(__file__).resolve().parent.parent / "scripts" / "run_farm_354.py"
    if alt.is_file():
        return alt
    return cand


def _run_farm_in_thread(
    script: Path,
    hours: float,
    profile: SiteProfile | None,
    log: Callable[[str, str], None] | None,
) -> None:
    global _farm_thread

    def _log(msg: str, level: str = "ok") -> None:
        if log:
            log(msg, level)

    def target() -> None:
        old_argv = list(sys.argv)
        try:
            sys.argv = _farm_args(script, hours, profile)
            runpy.run_path(str(script), run_name="__main__")
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 0
            _log(f"Farm exited (code={code})", "ok" if code == 0 else "warn")
        except Exception as exc:
            _log(f"Farm crashed: {exc}", "err")
        finally:
            sys.argv = old_argv
            _digest_stop.set()

    t = threading.Thread(target=target, name="cpharm-farm", daemon=True)
    _farm_thread = t
    t.start()
    _log(
        f"Farm started in-process (thread={t.name}, hours={hours}, "
        f"unique-seq={'on' if os.environ.get('CPHARM_FARM_UNIQUE_SEQ') == '1' else 'off'})",
        "ok",
    )


def _start_digest(profile: SiteProfile | None, log: Callable[[str, str], None] | None) -> None:
    global _digest_thread

    if profile is None or not profile.farm.ntfy_hourly or not profile.farm.ntfy_topic:
        return
    if _digest_thread is not None and _digest_thread.is_alive():
        return
    _digest_stop.clear()
    interval_s = max(300, int(profile.farm.ntfy_interval_s))

    def target() -> None:
        run_reporter(
            interval_s=interval_s,
            baseline=False,
            wait_for_start=False,
            stop_event=_digest_stop,
        )

    _digest_thread = threading.Thread(target=target, name="cpharm-ntfy-digest", daemon=True)
    _digest_thread.start()
    if log:
        log(f"ntfy digest started (every {interval_s // 60} minutes)", "ok")


def _stop_digest_when_process_exits(proc: subprocess.Popen[Any]) -> None:
    def target() -> None:
        proc.wait()
        _digest_stop.set()

    threading.Thread(target=target, name="cpharm-farm-monitor", daemon=True).start()


def start_farm(
    *,
    profile: SiteProfile | None = None,
    hours: float | None = None,
    log: Callable[[str, str], None] | None = None,
    takeover: bool = True,
) -> bool:
    """Spawn farm runner + operator stack. Returns True if started.

    When ``takeover`` is True (default), any external python farm/cycles are
    stopped so CPharm owns the money path independently.
    """
    global _farm_proc

    def _log(msg: str, level: str = "ok") -> None:
        if log:
            log(msg, level)

    with _farm_lock:
        if farm_running():
            _log("Farm already running", "warn")
            return False
        if external_python_farm_running():
            if not takeover:
                _log(
                    "External python farm/cycles already UP — refuse duplicate start",
                    "warn",
                )
                return False
            stop_external_python_farm(log=log)
        apply_profile_farm_env(profile)
        # Wizard Advanced panels persist user overrides here; re-apply after
        # profile defaults so user tweaks win, before lanes spawn with env.
        try:
            from wizard.farm_settings import apply_saved_to_env

            applied = apply_saved_to_env()
            if applied:
                _log(f"Applied {applied} wizard farm setting(s)", "ok")
        except Exception as exc:
            _log(f"apply wizard farm settings failed: {exc}", "warn")
        os.environ["CPHARM_FARM_STOP"] = "0"
        helper_py = _resolve_helper_python()
        # Prefer real pythonw workers; only use in-process farm when frozen w/o python.
        in_process = bool(getattr(sys, "frozen", False) and not helper_py)
        mark_exe_owned(in_process=in_process)
        os.environ["CPHARM_UNISON_MODE"] = "1"
        # Unison owns farm + stealth + watchdog — do not also spawn run_farm_354 here.
        ensure_operator_stack(log=log)
        if not farm_running():
            _log("Farm stack failed to arm (unison/helpers not alive)", "err")
            clear_exe_owned()
            return False
        _log("Farm unison stack armed (farm/stealth/watchdog)", "ok")
        _start_digest(profile, log)
        threading.Thread(
            target=lambda: open_operator_dashboard(log=log),
            name="cpharm-open-dash",
            daemon=True,
        ).start()
        return True


def stop_farm(*, log: Callable[[str, str], None] | None = None) -> bool:
    global _farm_proc, _farm_thread

    def _log(msg: str, level: str = "ok") -> None:
        if log:
            log(msg, level)

    with _farm_lock:
        _digest_stop.set()
        os.environ["CPHARM_FARM_STOP"] = "1"
        stopped = False
        if _farm_proc is not None and _farm_proc.poll() is None:
            pid = _farm_proc.pid
            try:
                _farm_proc.terminate()
                try:
                    _farm_proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    _farm_proc.kill()
            except OSError as exc:
                _log(f"Farm stop error: {exc}", "err")
                return False
            _farm_proc = None
            _log(f"Farm stopped (was pid={pid})", "ok")
            stopped = True
        if _farm_thread is not None and _farm_thread.is_alive():
            _log("Farm stop requested (in-process thread will exit on next cycle)", "warn")
            stopped = True
        # Unison path: start_farm never sets _farm_proc — tear down helpers too.
        stack_killed = _kill_farm_stack(log=log)
        if stack_killed:
            stopped = True
        clear_exe_owned()
        if not stopped:
            _log("Farm was not running", "warn")
        return stopped


def load_active_profile(slug: str | None) -> SiteProfile | None:
    if not slug:
        cfg = load_config()
        slug = str(cfg.get("active_site_slug") or "").strip() or None
    if not slug:
        return None
    try:
        return load_profile(app_data_root(), slug)
    except (OSError, ValueError, TypeError, KeyError):
        return None


# ---------------------------------------------------------------------------
# Spin up ONE phone for testing — explicit user click ONLY, never automatic
# ---------------------------------------------------------------------------
_test_phone_lock = threading.Lock()
_test_phone_active = False


def _docker_cli(argv: list[str], timeout: float = 40.0) -> tuple[int, str]:
    try:
        r = subprocess.run(
            ["docker", *argv],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            **hidden_run_kwargs(),
        )
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as exc:  # noqa: BLE001 — surface text to the log
        return 1, str(exc)


def _redroid_containers() -> list[tuple[int, str, bool]]:
    """[(idx, name, is_up)] for every redroid-N container docker knows."""
    code, out = _docker_cli(
        ["ps", "-a", "--filter", "name=redroid-", "--format", "{{.Names}}|{{.Status}}"]
    )
    if code != 0:
        return []
    rows: list[tuple[int, str, bool]] = []
    for line in out.splitlines():
        name, _, status = line.partition("|")
        m = re.match(r"^redroid-(\d+)$", name.strip())
        if not m:
            continue
        rows.append((int(m.group(1)), name.strip(), status.strip().startswith("Up")))
    return sorted(rows)


def spin_up_test_phone(*, log: Callable[[str, str], None] | None = None) -> dict:
    """Bring up ONE phone for testing when the operator clicks the button.

    Never runs automatically. Order of preference: a redroid (Android-in-
    Docker) phone already running but not on ADB, then a stopped redroid
    container (docker start), then an offline real MuMu VM. The work runs in a
    background thread and the call returns immediately with an honest message;
    self-heal in the farm runner is the only other phone spin-up, and it is
    limited to phones that were ONLINE when that farm run started.
    """
    global _test_phone_active

    def _log(msg: str, level: str = "ok") -> None:
        if log:
            try:
                log(msg, level)
            except Exception:
                pass

    with _test_phone_lock:
        if _test_phone_active:
            return {
                "ok": True,
                "started": False,
                "busy": True,
                "message": "A test phone is already coming up — wait a moment.",
            }
        _test_phone_active = True

    def _run() -> None:
        try:
            from automation.adb_wrapper import AdbWrapper

            adb = AdbWrapper()
            live = {
                d.serial
                for d in adb.devices_detailed()
                if getattr(d, "online", False)
            }
            redroids = _redroid_containers()
            # 1) Already-running redroid that is simply not adb-connected yet.
            for idx, name, up in redroids:
                if not up:
                    continue
                target = f"127.0.0.1:{5555 + idx}"
                if target in live:
                    _log(f"{name} is already online ({target}) — ready to test.", "ok")
                    return
            for idx, name, up in redroids:
                if not up:
                    continue
                target = f"127.0.0.1:{5555 + idx}"
                _log(f"{name} is running — connecting ADB ({target})…")
                adb.connect(target)
                if adb.wait_for_device(target, timeout=45.0):
                    _log(f"{name} online ({target}) — ready to test.", "ok")
                    return
            # 2) Stopped redroid container -> docker start just that one.
            for idx, name, up in redroids:
                if up:
                    continue
                _log(f"{name} is stopped — starting it (docker start)…")
                code, err = _docker_cli(["start", name], timeout=120.0)
                if code != 0:
                    _log(f"{name} failed to start: {err}", "err")
                    continue
                target = f"127.0.0.1:{5555 + idx}"
                adb.connect(target)
                if adb.wait_for_device(target, timeout=120.0):
                    _log(f"{name} online ({target}) — ready to test.", "ok")
                    return
                _log(
                    f"{name} started but no ADB yet — give it a minute, then "
                    "press Open site on phones.",
                    "warn",
                )
                return
            # 3) Offline real MuMu VM (explicit user click — never automatic).
            from wizard.mumu_farm_ops import MuMuFarmOps

            farm = MuMuFarmOps()
            insts = farm.list_instances() or []
            live_serials = {
                d.serial
                for d in farm.enumerate_adb_devices()
                if getattr(d, "online", False)
            }

            def _looks_offline(inst: Any) -> bool:
                ser = str(getattr(inst, "adb_serial", None) or "").strip()
                # Invented classic localhost serials are never live on MuMu ARM.
                if not ser or ser.startswith("127.0.0.1:"):
                    return True
                return ser not in live_serials

            offline = sorted(
                (
                    i
                    for i in insts
                    if (i.name or "").startswith("vm") and _looks_offline(i)
                ),
                key=lambda i: i.index,
            )
            if not offline:
                _log(
                    "No stopped redroid and every MuMu phone is already online — "
                    "nothing to spin up.",
                    "warn",
                )
                return
            pick = offline[0]
            _log(
                f"Booting one MuMu test phone: {pick.name} "
                "(takes a few minutes on this box)…"
            )
            try:
                ok = farm.start_phone(pick.name)
            except Exception as exc:  # noqa: BLE001
                ok = False
                _log(f"MuMu spin-up failed: {exc}", "err")
            if ok:
                _log(f"{pick.name} is up — ready to test.", "ok")
            else:
                _log(
                    f"{pick.name} launch started but ADB is not up yet — wait a few "
                    "minutes, then press Open site on phones.",
                    "warn",
                )
        except Exception as exc:  # noqa: BLE001
            _log(f"Test phone spin-up error: {exc}", "err")
        finally:
            global _test_phone_active
            _test_phone_active = False

    threading.Thread(target=_run, name="cpharm-test-phone", daemon=True).start()
    return {
        "ok": True,
        "started": True,
        "message": "Spinning up one test phone in the background — watch the Test log.",
    }
