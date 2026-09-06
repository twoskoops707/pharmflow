#!/usr/bin/env python3
"""24/7 farm keeper: keep day-mode farm + helpers alive.

Watches farm worker (24h day / daily caps), proxy inject watch, and mouse tickler.
Restarts anything missing. Safe to run alongside a healthy farm (does not
kill a live run_farm_354).

Ops model (preferred): keep ``run_farm_cycles.py --forever --hours 0 --no-kill``
as the supervisor. It adopts/waits on a live farm_354 and respawns the worker
if it dies. ensure must NOT kill that cycles supervisor when farm_354 is
healthy Ã¢â‚¬â€ only cull duplicate farm_354 workers. A single-process 24x7 without
cycles is possible but not current ops; prefer cycles alive.
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
sys.path.insert(0, str(ROOT))

import automation.no_window  # noqa: E402,F401  (kill child console-window flashes)

from automation.browse_proxy import browse_proxy_mode
from automation.farm_visit_caps import (
    apply_runtime_overrides_to_env,
    clear_loansflow_operator_hold,
    reassert_sticky_caps,
    write_site_lock,
)
from automation.win_subprocess import hidden_run_kwargs

LOG_DIR = Path(os.environ.get("CPHARM_LOG_DIR", r"C:\CPharm\logs"))
HB = LOG_DIR / "ensure_farm_24x7_heartbeat.txt"
OVERRIDES = LOG_DIR / "farm_runtime_overrides.json"
INTERVAL_S = float(os.environ.get("CPHARM_ENSURE_24X7_INTERVAL", "60") or "60")
PHONES = [
    p.strip()
    for p in (
        os.environ.get("CPHARM_FARM_PHONES")
        or "vm0.gmadoa,vm1.gmadoa,vm2.gmadoa,vm3.gmadoa"
    ).split(",")
    if p.strip()
]
HOURS = os.environ.get("CPHARM_FARM_HOURS", "0") or "0"




def _normalize_phones_csv(raw: str) -> str:
    """Accept plain csv or accidental nested JSON; always return vm csv."""
    s = (raw or "").strip()
    if not s:
        return ""
    if s.startswith("{"):
        try:
            nested = json.loads(s)
            if isinstance(nested, dict) and nested.get("CPHARM_FARM_PHONES"):
                s = str(nested.get("CPHARM_FARM_PHONES") or "").strip()
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    parts = [x.strip() for x in s.replace(";", ",").split(",") if x.strip()]
    # Drop accidental nested keys if JSON partially leaked
    parts = [p for p in parts if p.lower() not in {"updated", "note"} and not p.startswith("{")]
    return ",".join(parts)


def _restore_capacity_phones_lock() -> bool:
    """Keep capacity lock phones in sticky â€” never reintroduce ghost vm11."""
    lock = LOG_DIR / "FARM_PHONES_CAPACITY.lock"
    if not lock.is_file():
        return False
    raw = _normalize_phones_csv(lock.read_text(encoding="utf-8").strip())
    # Ban ghost vm11 forever â€” adaptive remediator owns the live money map.
    parts = [p for p in raw.split(",") if p.strip() and "vm11" not in p.lower()]
    raw = ",".join(parts)
    if not raw:
        return False
    # Self-heal nested lock contents so we never rewrite sticky as nested JSON.
    try:
        if lock.read_text(encoding="utf-8").strip() != raw:
            lock.write_text(raw + "\n", encoding="utf-8")
    except OSError:
        pass
    try:
        data = {}
        if OVERRIDES.is_file():
            data = json.loads(OVERRIDES.read_text(encoding="utf-8-sig"))
        if _normalize_phones_csv(str(data.get("CPHARM_FARM_PHONES") or "")) == raw:
            return False
        data["CPHARM_FARM_PHONES"] = raw
        data["updated"] = datetime.now(timezone.utc).isoformat()
        data["tick_verify_note"] = "capacity_lock_no_vm11"
        OVERRIDES.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _phones_from_overrides() -> list[str]:
    """Live phone list from sticky overrides (vm0 offline drops, etc.)."""
    try:
        if OVERRIDES.is_file():
            ov = json.loads(OVERRIDES.read_text(encoding="utf-8-sig"))
            raw = _normalize_phones_csv(str(ov.get("CPHARM_FARM_PHONES") or ""))
            if raw:
                return [x.strip() for x in raw.split(",") if x.strip()]
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return list(PHONES)


def _hb(msg: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        HB.write_text(
            f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def _count(needle: str) -> int:
    from automation.process_scan import pids_matching

    return len(pids_matching(needle))


def _farm_354_procs() -> list[tuple[int, float]]:
    """Return [(pid, create_time)] for real run_farm_354.py workers only."""
    try:
        import psutil
    except ImportError:
        return []
    rows: list[tuple[int, float]] = []
    for proc in psutil.process_iter(["pid", "name", "create_time"]):
        try:
            name = str(proc.info.get("name") or "").lower()
            if name not in ("python.exe", "pythonw.exe", "py.exe"):
                continue
            parts = [str(x).lower() for x in (proc.cmdline() or [])]
            # Real worker argv includes the script path; skip -c one-liners / ensure.
            if "-c" in parts:
                continue
            joined = " ".join(parts)
            if "run_farm_354.py" not in joined:
                continue
            if "ensure_farm_24x7" in joined:
                continue
            rows.append((int(proc.info["pid"]), float(proc.info.get("create_time") or 0.0)))
        except (psutil.Error, TypeError, ValueError, KeyError, OSError):
            continue
    return rows


def _cull_duplicate_farm_354(actions: list[str]) -> None:
    """Keep the oldest farm_354; kill extras so phones aren't double-driven."""
    rows = _farm_354_procs()
    if len(rows) <= 1:
        return
    rows.sort(key=lambda r: r[1])  # oldest first
    keep_pid = rows[0][0]
    try:
        import psutil
    except ImportError:
        return
    for pid, _ctime in rows[1:]:
        try:
            psutil.Process(pid).kill()
            actions.append(f"kill_dup_farm:{pid}(keep={keep_pid})")
        except (psutil.Error, OSError):
            pass


def _cull_singleton_helpers(actions: list[str]) -> None:
    """One dash / keepalive / remediator / inject / cycles â€” no race doubles."""
    try:
        from automation.process_scan import cull_duplicates_keep_newest

        for fix in cull_duplicates_keep_newest():
            actions.append(fix)
    except Exception as exc:
        actions.append(f"singleton_cull_err:{exc}")


def _ensure_keepalive_and_remediator(actions: list[str]) -> None:
    """ensure used to omit these â€” keepalive was the only remediator parent."""
    if _count("keep_farm_alive.py") < 1:
        _start_hidden("scripts/keep_farm_alive.py")
        actions.append("keep_farm_alive")
    if (LOG_DIR / "REMEDIATOR_OFF.flag").is_file():
        actions.append("remediator_off_flag")
    elif _count("farm_remediate_loop.py") < 1:
        _start_hidden("scripts/farm_remediate_loop.py")
        actions.append("remediator")
    if _count("watch_bottom_ads.py") < 1:
        _start_hidden("scripts/watch_bottom_ads.py", "loop", "--loop", "75")
        actions.append("watch_bottom_ads")


def _apply_overrides(env: dict[str, str]) -> None:
    apply_runtime_overrides_to_env(env, log_dir=LOG_DIR)


def _start_hidden(script_rel: str, *args: str) -> None:
    # Permanently refuse loansflow hold watchdog (dabflow sticky until operator re-enables).
    _rel = str(script_rel or "").replace("\\", "/").lower()
    if "loansflow_hold_watchdog" in _rel or "_loansflow_oneshot_hold" in _rel or "lf_hold" in _rel or "ff_session_lf_hold" in _rel or "hold_enforcer" in _rel:
        return
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    # Prefer bundled adb â€” PATH platform-tools\adb.exe opens Windows Terminal flashes.
    bundled_adb_dir = r"C:\CPharm\bundled"
    if Path(bundled_adb_dir).is_dir():
        env["PATH"] = bundled_adb_dir + os.pathsep + env.get("PATH", "")
    _apply_overrides(env)
    env.setdefault("CPHARM_ALLOW_SEQUENCE_RUNS", "1")
    # Never default ads ON under overnight sticky/pause (setdefault only if unset).
    _ap_pause = str(env.get("CPHARM_AUTOPILOT_PAUSE") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    if _ap_pause or (LOG_DIR / "DABFLOW_SITE_STICKY.flag").is_file():
        env.setdefault("CPHARM_FARM_ALLOW_ADS", "0")
    else:
        env.setdefault("CPHARM_FARM_ALLOW_ADS", "1")
    env.setdefault("CPHARM_REQUIRE_UNIQUE_EXIT_IP", "1")
    # Honor overrides/desktop_prefs (scramble recommended). Do not force Tor.
    mode = str(env.get("CPHARM_BROWSE_PROXY_MODE") or "").strip().lower()
    if mode not in ("scramble", "tor", "direct", "upstream"):
        try:
            mode = browse_proxy_mode()
        except Exception:
            mode = "scramble"
    env["CPHARM_BROWSE_PROXY_MODE"] = mode
    env.setdefault("CPHARM_MANTIS_INJECT_PROXY", "1")
    env["CPHARM_FARM_STOP"] = "0"
    env.setdefault("CPHARM_FARM_IMMEDIATE_START", "1")
    env.setdefault("CPHARM_FARM_SLOT_MIN_LEAD", "0")
    env.setdefault("CPHARM_NTFY_DIGEST_INTERVAL", "10800")
    env.setdefault("CPHARM_PROXY_WATCH_INTERVAL", "3")
    env.setdefault("CPHARM_FARM_EXPECT_PHONES", str(len(PHONES) or 4))
    # Forever plan Ã¢â‚¬â€ never leave PATH3 as a bare float that old parsers choke on.
    raw_p3 = str(env.get("CPHARM_FARM_PATH3_PER_HOUR") or "1")
    try:
        env["CPHARM_FARM_PATH3_PER_HOUR"] = str(int(float(raw_p3)))
    except ValueError:
        env["CPHARM_FARM_PATH3_PER_HOUR"] = "1"
    cmd = [
        sys.executable,
        "-u",
        str(ROOT / "scripts" / "start_hidden.py"),
        script_rel,
        *args,
    ]
    creation = 0
    kwargs: dict = {}
    if sys.platform == "win32":
        creation = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        kwargs["creationflags"] = creation
    subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **kwargs,
    )


def _adb_serials_from_sticky() -> list[str]:
    """Locked serial list from sticky + tablet Ã¢â‚¬â€ avoid fighting adb every tick."""
    serials: list[str] = []
    try:
        if OVERRIDES.is_file():
            ov = json.loads(OVERRIDES.read_text(encoding="utf-8-sig"))
            raw = str(ov.get("CPHARM_ADB_SERIALS") or "").strip()
            serials.extend([s.strip() for s in raw.split(",") if s.strip()])
            tab = str(ov.get("CPHARM_TABLET_SERIAL") or "").strip()
            if tab and tab not in serials:
                serials.append(tab)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    if not serials:
        raw = os.environ.get("CPHARM_ADB_SERIALS") or ""
        serials = [s.strip() for s in raw.split(",") if s.strip()]
    lock = LOG_DIR / "ADB_SERIAL_MAP.lock.json"
    try:
        if lock.is_file():
            data = json.loads(lock.read_text(encoding="utf-8-sig"))
            for bucket in (data.get("phones") or {}, data.get("tablet") or {}):
                for ser in bucket.values():
                    s = str(ser or "").strip()
                    if s and s not in serials:
                        serials.append(s)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return serials


def _adb_exe() -> str:
    """Prefer bundled adb — bare PATH adb often missing or flashes Terminal."""
    bundled = Path(r"C:\CPharm\bundled\adb.exe")
    if bundled.is_file():
        return str(bundled)
    return os.environ.get("ADB") or os.environ.get("CPHARM_ADB") or "adb"


def _adb_devices_state() -> dict[str, str]:
    adb = _adb_exe()
    try:
        r = subprocess.run(
            [adb, "devices"],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
            **hidden_run_kwargs(),
        )
        out: dict[str, str] = {}
        for line in (r.stdout or "").splitlines()[1:]:
            parts = line.strip().split()
            if len(parts) >= 2:
                out[parts[0]] = parts[1]
        return out
    except (OSError, subprocess.TimeoutExpired):
        return {}


def _adb_serial_probe_ok(adb_exe: str, serial: str) -> bool:
    try:
        probe = subprocess.run(
            [adb_exe, "-s", serial, "shell", "echo", "ok"],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
            **hidden_run_kwargs(),
        )
        return probe.returncode == 0 and "ok" in (probe.stdout or "")
    except (OSError, subprocess.TimeoutExpired):
        return False


def _adb_keepalive() -> str:
    """Probe-only by default Ã¢â‚¬â€ connect/reconnect ONE serial if offline (never kill-server, never wm)."""
    if _count("emu_keepalive.py") >= 1:
        return "adb=delegated_emu_keepalive"
    serials = _adb_serials_from_sticky()
    if not serials:
        return "adb=0/0"
    adb = _adb_exe()
    states = _adb_devices_state()
    online = 0
    touched = 0
    max_touch = int(os.environ.get("CPHARM_ENSURE_ADB_MAX_TOUCH", "1") or "1")
    for serial in serials:
        if states.get(serial) == "device" and _adb_serial_probe_ok(adb, serial):
            online += 1
            continue
        if touched >= max_touch:
            continue
        st = states.get(serial, "missing")
        if st not in ("offline", "missing", "unauthorized"):
            continue
        touched += 1
        try:
            subprocess.run(
                [adb, "connect", serial],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
                **hidden_run_kwargs(),
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        states = _adb_devices_state()
        if states.get(serial) == "device" and _adb_serial_probe_ok(adb, serial):
            online += 1
    return f"adb={online}/{len(serials)}"



def _load_overrides_dict() -> dict:
    try:
        if OVERRIDES.is_file():
            data = json.loads(OVERRIDES.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return {}


def _truthy(val: object) -> bool:
    return str(val or "").strip().lower() in ("1", "true", "yes", "on")


def _suppress_thrash_watchers() -> bool:
    """Money-day ops: dash_forever_watch / farm_fail_review fight inject + ADB."""
    if (LOG_DIR / "ENSURE_NO_THRASH_WATCHERS.flag").is_file():
        return True
    if _truthy(os.environ.get("CPHARM_ENSURE_NO_THRASH_WATCHERS")):
        return True
    ov = _load_overrides_dict()
    if _truthy(ov.get("CPHARM_ENSURE_NO_THRASH_WATCHERS")):
        return True
    ap_paused = _truthy(
        ov.get("CPHARM_AUTOPILOT_PAUSE") or os.environ.get("CPHARM_AUTOPILOT_PAUSE")
    )
    ap_kill = (LOG_DIR / "AUTOPILOT_OVERNIGHT_KILL.flag").is_file()
    if not (ap_paused or ap_kill):
        return False
    if _truthy(ov.get("CPHARM_FARM_PATH3") or ov.get("CPHARM_PATH3")):
        return True
    if _truthy(ov.get("CPHARM_FARM_ALLOW_ADS")):
        return True
    if ap_kill and (LOG_DIR / "DABFLOW_SITE_STICKY.flag").is_file():
        return True
    return False


def _cull_thrash_watchers(actions: list[str]) -> None:
    """Keep inject/ADB stable: cull dash thrash watchers on money day.

    Never kill farm_fail_review â€” it patches/quarantines broken seqs as FAILs land.
    """
    try:
        from automation.process_scan import kill_matching

        for needle in ("dash_forever_watch.py",):
            killed = kill_matching(needle)
            if killed:
                actions.append(f"kill_{needle.split('.')[0]}:{killed}")
    except Exception:
        pass


def ensure_once(*, sweep_dead: bool = True) -> str:
    actions: list[str] = []
    # Unison owns the stack — do not respawn remediator/keepalive that it culls.
    if _count("cpharm_unison_supervisor.py") >= 1:
        _hb("unison_owns_stack")
        return "unison_owns_stack"
    try:
        from automation.farm_pause import farm_halted, is_killed, is_paused, seconds_until_resume

        if farm_halted():
            left = int(seconds_until_resume()) if is_paused() else -1
            actions.append("farm_killed" if is_killed() else f"farm_paused_left={left}s")
            # Dash only while halted — do not respawn farm workers.
            if _count("farm_operator_dash") < 1:
                _start_hidden("scripts/farm_operator_dash.py")
                actions.append("dash")
            if is_paused() and not is_killed() and _count("farm_midnight_watch.py") < 1:
                _start_hidden("scripts/farm_midnight_watch.py")
                actions.append("midnight_watch")
            return ",".join(actions) if actions else "halted"
    except Exception as exc:
        actions.append(f"pause_check_err:{exc}")
    try:
        # Site sticky: LoansFlow operator hold wins; otherwise DabFlow money-day sticky.
        try:
            hold = LOG_DIR / "LOANSFLOW_OPERATOR_HOLD.flag"
            loans_enabled = LOG_DIR / "LOANSFLOW_FARM_ENABLED.flag"
            dab_flag = LOG_DIR / "DABFLOW_SITE_STICKY.flag"
            want_loansflow = hold.is_file() or loans_enabled.is_file()
            if want_loansflow:
                if dab_flag.is_file():
                    try:
                        dab_flag.unlink(missing_ok=True)
                        actions.append("cleared_dabflow_sticky_for_loansflow")
                    except OSError:
                        pass
                if not hold.is_file():
                    hold.write_text(
                        "operator loansflow farm enabled\n", encoding="utf-8"
                    )
                write_site_lock(
                    "loansflow",
                    sequence_root=r"C:\CPharm\automation\recordings\sequences\loansflow",
                    daily_visits_csv="120,100,90,80",
                    daily_ads_csv="3,2,2,2",
                    url="https://loansflow.loan/",
                    note="ensure_loansflow_operator_hold",
                )
                actions.append("loansflow_operator_reassert")
            else:
                if hold.is_file():
                    try:
                        hold.unlink(missing_ok=True)
                        actions.append("cleared_loansflow_hold")
                    except OSError:
                        pass
                if not dab_flag.is_file():
                    dab_flag.write_text("dabflow sticky ensure\n", encoding="utf-8")
                # Modest Path3/ads under dabflow sticky — but never undercut an
                # active money-day aggressive floor (Path3 unblock / catch-up).
                _prev_lock = {}
                try:
                    _slp = LOG_DIR / "farm_site_lock.json"
                    if _slp.is_file():
                        _prev_lock = json.loads(_slp.read_text(encoding="utf-8-sig"))
                except (OSError, json.JSONDecodeError, TypeError):
                    _prev_lock = {}
                _floor = {}
                try:
                    _fp = LOG_DIR / "_money_day_path3_aggressive.json"
                    if _fp.is_file():
                        _floor = json.loads(_fp.read_text(encoding="utf-8-sig"))
                except (OSError, json.JSONDecodeError, TypeError):
                    _floor = {}
                _ads = str(_prev_lock.get("daily_ads_csv") or "").strip()
                _floor_ads = str(_floor.get("ads") or "").strip()
                def _sum_csv(raw: str) -> int:
                    total = 0
                    for part in str(raw or "").split(","):
                        part = part.strip()
                        if not part:
                            continue
                        try:
                            total += int(float(part))
                        except (TypeError, ValueError):
                            pass
                    return total
                if _sum_csv(_floor_ads) > _sum_csv(_ads):
                    _ads = _floor_ads
                if _sum_csv(_ads) <= 0:
                    _ads = "4,4,3,3"
                _visits = str(_prev_lock.get("daily_visits_csv") or "").strip()
                _floor_visits = str(_floor.get("visits") or "").strip()
                if _sum_csv(_floor_visits) > _sum_csv(_visits):
                    _visits = _floor_visits
                if not _visits:
                    _visits = "500,490,480,470"
                _note = "ensure_dabflow_sticky_path3_modest"
                if _sum_csv(_ads) >= 280:
                    _note = "ensure_dabflow_sticky_path3_money_day"
                write_site_lock(
                    "dabflow",
                    sequence_root=r"C:\CPharm\automation\recordings\sequences",
                    daily_visits_csv=_visits,
                    daily_ads_csv=_ads,
                    url="https://getdabflow.app/",
                    note=_note,
                )
                actions.append("dabflow_sticky_reassert")
        except Exception as exc:
            actions.append(f"sticky_site_err:{exc}")
        sticky = reassert_sticky_caps(LOG_DIR)
        if _restore_capacity_phones_lock():
            actions.append("capacity_phones_lock")
        if sticky.get("changed"):
            actions.append(
                f"sticky_caps:{sticky.get('visits')}/{sticky.get('seqs')}"
            )
    except Exception as exc:
        actions.append(f"sticky_caps_err:{exc}")
    try:
        import importlib.util

        _day_path = ROOT / "scripts" / "apply_farm_day_plan.py"
        _spec = importlib.util.spec_from_file_location("apply_farm_day_plan", _day_path)
        if _spec is None or _spec.loader is None:
            raise ImportError(f"cannot load {_day_path}")
        _day_mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_day_mod)
        day = _day_mod.apply_if_due(force_restart=True)
        if day.get("reason") == "applied":
            actions.append(f"day_plan:{day.get('date')}")
        elif day.get("reason") not in ("already_applied", "not_today", "no_plan"):
            actions.append(f"day_plan:{day.get('reason')}")
    except Exception as exc:
        actions.append(f"day_plan_err:{exc}")
    try:
        actions.append(_adb_keepalive())
    except Exception as exc:
        actions.append(f"adb_err:{exc}")
    if sweep_dead:
        try:
            from scripts.clear_dead_farm_procs import clear_dead

            result = clear_dead()
            if int(result.get("killed") or 0) > 0:
                actions.append(f"dead:{result.get('killed')}")
        except Exception as exc:
            actions.append(f"dead_err:{exc}")
    # Cull before spawn so a race with keepalive cannot double-bind :8091.
    _cull_singleton_helpers(actions)
    _ensure_keepalive_and_remediator(actions)
    if _count("mouse_tickler.py") < 1:
        _start_hidden("scripts/mouse_tickler.py")
        actions.append("tickler")
    if _count("watch_proxy_inject") < 1:
        _start_hidden("scripts/watch_proxy_inject.py")
        actions.append("proxy_watch")
    if _count("run_mantis_inject_proxies") < 1 and _count("run_mantis_inject") < 1:
        # MuMu indices are not dense 0..N-1 (vm5 â†’ index 5 â†’ :8223).
        # --phones N starts indices 0..N-1; need N >= max_live_index+1.
        # Floor 6 covers sticky map vm1..vm5 (8219..8223) plus unused 8218.
        try:
            from automation.farm_phone_discover import inject_listener_count

            inject_n = max(11, int(inject_listener_count()), len(PHONES) or 0)
        except Exception:
            inject_n = 11
        _start_hidden(
            "scripts/run_mantis_inject_proxies.py",
            "--phones",
            str(inject_n),
            "--no-install-ca",
        )
        actions.append("inject")
    if _count("farm_operator_dash") < 1:
        _start_hidden("scripts/farm_operator_dash.py")
        actions.append("dash")
    # loansflow_hold_watchdog permanently suppressed (dabflow sticky session).
    _no_thrash = _suppress_thrash_watchers()
    if _no_thrash:
        _cull_thrash_watchers(actions)
        actions.append("thrash_watchers_suppressed")
    # Always keep fail_review up â€” thrash suppress must not block seq auto-fix.
    if _count("farm_fail_review.py") < 1:
        _start_hidden("scripts/farm_fail_review.py")
        actions.append("fail_review")
    # Operator OFF: NTFY_OFF.flag or digest interval 0 â€” do not respawn digests.
    _ntfy_off = (LOG_DIR / "NTFY_OFF.flag").is_file()
    _digest = "0"
    try:
        if OVERRIDES.is_file():
            _ov_ntfy = json.loads(OVERRIDES.read_text(encoding="utf-8-sig"))
            _digest = str(
                _ov_ntfy.get("CPHARM_NTFY_DIGEST_INTERVAL")
                or os.environ.get("CPHARM_NTFY_DIGEST_INTERVAL")
                or "10800"
            ).strip() or "10800"
        else:
            _digest = os.environ.get("CPHARM_NTFY_DIGEST_INTERVAL", "10800").strip() or "10800"
    except Exception:
        _digest = os.environ.get("CPHARM_NTFY_DIGEST_INTERVAL", "10800").strip() or "10800"
    if _ntfy_off or _digest in {"0", "off", "false", "no"}:
        actions.append("hourly_ntfy_suppressed")
    elif _count("farm_hourly_ntfy.py") < 1:
        _start_hidden(
            "scripts/farm_hourly_ntfy.py",
            "--interval",
            _digest,
            "--baseline",
            "--no-wait",
        )
        actions.append("hourly_ntfy")
    # Honor runtime pause / sticky dabflow ops: do not respawn autopilot when paused.
    ap_paused = False
    try:
        ov = {}
        if OVERRIDES.is_file():
            ov = json.loads(OVERRIDES.read_text(encoding="utf-8-sig"))
        ap_paused = str(
            ov.get("CPHARM_AUTOPILOT_PAUSE") or os.environ.get("CPHARM_AUTOPILOT_PAUSE") or "0"
        ).strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        ap_paused = str(os.environ.get("CPHARM_AUTOPILOT_PAUSE") or "0").strip().lower() in (
            "1", "true", "yes", "on",
        )
    # Hard kill flag: never respawn AP while present (money-day / overnight).
    ap_kill_flag = (LOG_DIR / "AUTOPILOT_OVERNIGHT_KILL.flag").is_file()
    if ap_kill_flag:
        ap_paused = True
    # Keep autopilot DOWN while pause=1. DabFlow sticky alone no longer implies
    # ads-off (operator may re-arm modest Path3 under sticky for revenue days).
    if ap_paused:
        killed_ap = 0
        try:
            from automation.process_scan import kill_matching, pids_matching

            if pids_matching("mantis_autopilot.py"):
                killed_ap = kill_matching("mantis_autopilot.py")
        except Exception:
            killed_ap = 0
        actions.append("autopilot_paused")
        if ap_kill_flag:
            actions.append("autopilot_kill_flag")
        if killed_ap:
            actions.append(f"autopilot_killed:{killed_ap}")
    elif _count("mantis_autopilot.py") < 1:
        _start_hidden("scripts/mantis_autopilot.py")
        actions.append("mantis_autopilot")
    if _no_thrash:
        pass
    elif _count("dash_forever_watch.py") < 1:
        _start_hidden("scripts/dash_forever_watch.py")
        actions.append("dash_forever_watch")
    # Operator may set C:\CPharm\logs\NTFY_NO_AUTO_REPLY.flag or NTFY_OFF.flag â€”
    # do not respawn auto-reply / agent-wake bots.
    _ntfy_no_auto = (LOG_DIR / "NTFY_NO_AUTO_REPLY.flag").is_file() or (
        LOG_DIR / "NTFY_OFF.flag"
    ).is_file()
    if not _ntfy_no_auto:
        if _count("ntfy_farm_responder.py") < 1:
            _start_hidden("scripts/ntfy_farm_responder.py")
            actions.append("ntfy_responder")
        if _count("ntfy_agent_wake.py") < 1:
            _start_hidden("scripts/ntfy_agent_wake.py")
            actions.append("ntfy_wake")
    else:
        actions.append("ntfy_auto_reply_suppressed")
    if _count("emu_keepalive.py") < 1:
        _start_hidden("scripts/emu_keepalive.py")
        actions.append("emu_keepalive")
    # x86 AVD overnight only. MuMu farms must not spawn this — it polls adb /
    # launches emulator.exe every tick and flashes console windows.
    _avd_watch = str(os.environ.get("CPHARM_AVD_WATCHDOG") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    if _avd_watch:
        if _count("emu_overnight_watchdog.py") < 1:
            _start_hidden("scripts/emu_overnight_watchdog.py")
            actions.append("emu_overnight_watchdog")
    elif _count("emu_overnight_watchdog.py") >= 1:
        try:
            from automation.process_scan import kill_matching

            killed_avd = kill_matching("emu_overnight_watchdog.py")
            if killed_avd:
                actions.append(f"emu_overnight_watchdog_culled:{killed_avd}")
        except Exception:
            actions.append("emu_overnight_watchdog_cull_err")
    if _count("suppress_console_flash.py") < 1:
        _start_hidden("scripts/suppress_console_flash.py")
        actions.append("suppress")
    # Preferred ops: cycles --no-kill supervises farm_354 (adopt/wait/respawn).
    # Keep the cycles supervisor alive even when farm_354 is already healthy Ã¢â‚¬â€
    # it adopts the live worker. Never kill cycles; cull duplicate farm_354.
    # When CPharm.exe owns the farm, do not spawn a second farm/cycles worker.
    from automation.cpharm_exe_owned import exe_owns_farm

    if exe_owns_farm():
        actions.append("exe_owned_skip_farm_spawn")
        _cull_duplicate_farm_354(actions)
        _cull_singleton_helpers(actions)
        status = (
            f"farm={len(_farm_354_procs())} cycles={_count('run_farm_cycles.py')} "
            f"watch={_count('watch_proxy_inject')} inject={_count('run_mantis_inject')} "
            f"fail={_count('farm_fail_review')} ntfy={_count('farm_hourly_ntfy')} "
            f"resp={_count('ntfy_farm_responder')} wake={_count('ntfy_agent_wake')} "
            f"tickler={_count('mouse_tickler.py')} "
            f"fixes={','.join(actions) if actions else '0'}"
        )
        _hb(status)
        return status
    cycles_n = _count("run_farm_cycles.py")
    if cycles_n < 1:
        # Day mode: hours=0 Ã¢â€ â€™ farm runs on daily visit/ad caps, no 6h cycle restarts.
        args = ["--forever", "--hours", "0", "--no-kill", "--phones", *_phones_from_overrides()]
        _start_hidden("scripts/run_farm_cycles.py", *args)
        actions.append("cycles")
        time.sleep(5)
        cycles_n = _count("run_farm_cycles.py")
    # If cycles is up but farm worker died mid-gap, kick a farm directly.
    # Cycles will adopt it on the next iteration / keep waiting.
    if cycles_n >= 1 and len(_farm_354_procs()) < 1:
        farm_args = ["--hours", "0", "--phones", *_phones_from_overrides()]
        _start_hidden("scripts/run_farm_354.py", *farm_args)
        actions.append("farm")
    _cull_duplicate_farm_354(actions)
    _cull_singleton_helpers(actions)
    status = (
        f"farm={len(_farm_354_procs())} cycles={_count('run_farm_cycles.py')} "
        f"watch={_count('watch_proxy_inject')} inject={_count('run_mantis_inject')} "
        f"fail={_count('farm_fail_review')} ntfy={_count('farm_hourly_ntfy')} "
        f"resp={_count('ntfy_farm_responder')} wake={_count('ntfy_agent_wake')} "
        f"tickler={_count('mouse_tickler.py')} "
        f"fixes={','.join(actions) if actions else '0'}"
    )
    _hb(status)
    return status


def main() -> int:
    if sys.platform != "win32":
        print("ensure_farm_24x7 is Windows-only", file=sys.stderr)
        return 2
    _hb("started")
    while True:
        try:
            # Same cadence spirit as proxy watch: every tick, sweep orphans then
            # restart any missing singleton helper.
            ensure_once(sweep_dead=True)
        except Exception as exc:
            _hb(f"error {exc}")
        time.sleep(max(15.0, INTERVAL_S))


if __name__ == "__main__":
    raise SystemExit(main())
