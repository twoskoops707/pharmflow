"""Evidence-based farm investigation for watchdog — no assumptions, no estimates.

Every problem must cite a concrete source (log line, JSON field, process name, port).
Flat $ / errors / sequence FAILs → farm issue → research then apply safe fixes only.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOG = Path(os.environ.get("PHARMFLOW_LOGS") or r"C:\PharmFlow\logs")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ADB = Path(r"C:\PharmFlow\bundled\adb.exe")

# Groups state the dashboard editor serves from. Corruption here used to hard-lock
# the operator out of group editing until manual intervention — the watchdog now
# repairs it automatically (quarantine + rebuild), same policy as the /api/load fix.
_GROUPS_CFG = ROOT / "automation" / "recordings" / "groups_config.json"


def _helper_py() -> str:
    """Deps-complete interpreter for fix scripts (cryptography required).

    On ARM64 boxes the PATH python is native-arm64 and has no cryptography
    wheel, which silently kills fix children (CA/Tor repair). Prefer a
    system pythonw that can import the full stack.
    """
    try:
        from automation.runtime_paths import helper_python

        found = helper_python()
        if found:
            return found
    except Exception:
        pass
    return sys.executable
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PAUSE_ADS = LOG / "PAUSE_BOTTOM_ADS_WATCH.flag"
STICKY_7 = LOG / "FARM_STICKY_7_PHONES.lock"
REPORT = LOG / "watchdog_farm_investigation.json"

# HARDCODED ghost roster removed — restoring dead 10.0.2.x IPs re-poisoned the
# farm (OPS_NOTES b7021c8 class). Sticky rebuild is live-ADB only via
# automation.farm_exe_self_heal.


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {}


def _run(cmd: list[str], timeout: float = 12) -> tuple[int, str]:
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, creationflags=FLAGS
        )
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as exc:
        return 1, str(exc)


def _port_listen(port: int) -> bool:
    import socket

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.5):
            return True
    except OSError:
        return False


def _proc_cmdlines() -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    try:
        import psutil

        for p in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmd = " ".join(p.info.get("cmdline") or [])
                rows.append((int(p.info["pid"]), cmd))
            except Exception:
                continue
    except ImportError:
        pass
    return rows


def _farm_log_tail(n: int = 120) -> list[str]:
    fl = LOG / "farm_354.log"
    if not fl.is_file():
        return []
    try:
        return fl.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


def _parse_log_evidence(lines: list[str]) -> dict[str, Any]:
    ev: dict[str, Any] = {
        "last_line": lines[-1] if lines else "",
        "log_age_s": None,
        "p3_ok": 0,
        "p3_fail": 0,
        "adb_timeouts": 0,
        "progress": {},
        "active_n": 0,
        "last_progress_ts": "",
        "boot_only": False,
        "online_logged": False,
    }
    fl = LOG / "farm_354.log"
    if fl.is_file():
        try:
            ev["log_age_s"] = round(time.time() - fl.stat().st_mtime, 1)
        except OSError:
            pass
    for ln in lines:
        if "P3-AD OK" in ln:
            ev["p3_ok"] += 1
        if "P3-AD FAIL" in ln:
            ev["p3_fail"] += 1
        if "ADB timeout" in ln:
            ev["adb_timeouts"] += 1
        if "ONLINE " in ln:
            ev["online_logged"] = True
        m = re.search(r"progress (\{[^}]+\})", ln)
        if m:
            try:
                ev["progress"] = eval(m.group(1))  # noqa: S307
            except Exception:
                pass
            am = re.search(r"active=\[([^\]]*)\]", ln)
            if am:
                ev["active_n"] = len([x for x in am.group(1).split(",") if x.strip()])
            ev["last_progress_ts"] = ln[:19]
    if lines:
        tail_text = "\n".join(lines[-30:])
        ev["boot_only"] = (
            "farm logging ready" in tail_text
            and "ONLINE " not in tail_text
            and "progress " not in tail_text
            and ev["log_age_s"] is not None
            and ev["log_age_s"] > 120
        )
    return ev


def gather_evidence() -> dict[str, Any]:
    """Collect only measurable facts from disk/processes — never infer health."""
    mantis = _read_json(LOG / "mantis_today_state.json")
    money_health = _read_json(LOG / "FARM_MONEY_HEALTH.json")
    try:
        _mh_parsed = datetime.fromisoformat(str(money_health.get("ts") or ""))
        money_health_age_s: float | None = max(
            0.0, (datetime.now(timezone.utc) - _mh_parsed).total_seconds()
        )
    except Exception:
        money_health_age_s = None
    progress = _read_json(LOG / "farm_354_progress.json")
    lock = _read_json(LOG / "ADB_SERIAL_MAP.lock.json")
    lines = _farm_log_tail(200)
    log_ev = _parse_log_evidence(lines)

    _, adb_out = _run([str(ADB), "devices"], timeout=20)
    adb_live = [
        ln.split()[0]
        for ln in adb_out.splitlines()
        if "\tdevice" in ln and not ln.startswith("127.0.0.1:")
    ]

    procs = _proc_cmdlines()
    # Only DUPLICATE instances are fighters now — single watch_bottom_ads /
    # farm_fail_review are supervised unison lanes, not stray dump storms.
    _fighter_names = ("watch_bottom_ads", "farm_fail_review")
    _fighter_counts: dict[str, int] = {}
    for _pid, _cmd in procs:
        for _n in _fighter_names:
            if _n in _cmd:
                _fighter_counts[_n] = _fighter_counts.get(_n, 0) + 1
                break
    fighters = [
        pid
        for pid, cmd in procs
        if any(n in cmd for n in _fighter_names)
        and _fighter_counts[next(n for n in _fighter_names if n in cmd)] > 1
    ]
    farm_pids = [pid for pid, cmd in procs if "run_farm_354" in cmd]
    dash_up = _port_listen(8091)
    phones_map = dict(lock.get("phones") or {})
    mapped_live = [
        str(s).strip()
        for s in phones_map.values()
        if str(s).strip() and not str(s).strip().startswith("127.0.0.1:")
    ]
    inject_ports = []
    for name in phones_map:
        try:
            idx = int(str(name).split(".")[0][2:])
            inject_ports.append(8218 + idx)
        except (TypeError, ValueError, IndexError):
            continue
    if not inject_ports:
        inject_ports = [8218]
    inject_any = any(_port_listen(p) for p in inject_ports)
    tor_ports = [8118 + (p - 8218) for p in inject_ports]
    tor_any = any(_port_listen(p) for p in tor_ports)
    tor_8118 = _port_listen(8118)
    tor_on_inject = inject_any and not tor_any
    inject_8218 = inject_any

    payout = float(mantis.get("payout_usd") or 0)
    clicks = int(mantis.get("clicks") or 0)
    impr = int(mantis.get("impressions") or 0)

    actives = progress.get("active_sequences") or progress.get("active") or []
    if isinstance(actives, dict):
        actives = list(actives.keys())
    stale_actives = bool(actives) and log_ev.get("boot_only")

    sticky = _read_json(STICKY_7)
    sticky_serials = [
        str(s).strip()
        for s in dict(sticky.get("phones") or {}).values()
        if str(s).strip()
    ]
    sticky_stale = bool(sticky_serials) and not any(s in adb_live for s in sticky_serials)

    return {
        "ts": _utc(),
        "mantis": {"payout_usd": payout, "clicks": clicks, "impressions": impr},
        "money_health": money_health,
        "money_health_age_s": money_health_age_s,
        "adb_live_n": len(adb_live),
        "adb_live": adb_live,
        "lock_phones_n": len(mapped_live),
        "lock_entries_n": len(phones_map),
        "farm_pid_n": len(farm_pids),
        "farm_pids": farm_pids,
        "dump_fighter_pids": fighters,
        "dash_8091": dash_up,
        "tor_8118": tor_8118,
        "tor_any": tor_any,
        "inject_any": inject_any,
        "inject_ports": inject_ports,
        "sticky_stale": sticky_stale,
        "inject_8218": inject_8218,
        "tor_collision_8218": tor_on_inject,
        "log": log_ev,
        "progress_active_n": len(actives) if isinstance(actives, list) else 0,
        "stale_active_locks": stale_actives,
    }


def detect_problems(ev: dict[str, Any]) -> list[dict[str, str]]:
    """Return problems with proof strings — no guessed severity."""
    problems: list[dict[str, str]] = []
    m = ev.get("mantis") or {}
    log_ev = ev.get("log") or {}
    mh = ev.get("money_health") or {}

    if mh.get("alert") is True:
        probs = mh.get("problems") or []
        problems.append(
            {
                "id": "money_health_alert",
                "proof": f"FARM_MONEY_HEALTH.json alert=true problems={probs}",
            }
        )
    if mh.get("flat") is True:
        problems.append(
            {
                "id": "flat_dollar",
                "proof": (
                    f"FARM_MONEY_HEALTH.json flat=true flat_minutes={mh.get('flat_minutes')} "
                    f"payout={m.get('payout_usd')} clicks={m.get('clicks')}"
                ),
            }
        )

    impr_delta = int(mh.get("impr_delta_window") or 0)
    if impr_delta > 150 and int(m.get("clicks") or 0) > 0:
        hist_flat = mh.get("flat") or mh.get("alert")
        if hist_flat:
            problems.append(
                {
                    "id": "impr_up_money_flat",
                    "proof": (
                        f"impr_delta_window={impr_delta} payout={m.get('payout_usd')} "
                        f"clicks={m.get('clicks')} (impressions climbing, $ flat)"
                    ),
                }
            )

    if log_ev.get("p3_fail", 0) > 0 and log_ev.get("p3_ok", 0) == 0:
        problems.append(
            {
                "id": "seq_all_fail_no_ok",
                "proof": (
                    f"farm_354.log tail: P3-AD FAIL={log_ev.get('p3_fail')} "
                    f"P3-AD OK={log_ev.get('p3_ok')}"
                ),
            }
        )

    if int(log_ev.get("adb_timeouts") or 0) >= 5:
        problems.append(
            {
                "id": "adb_timeout_storm",
                "proof": f"farm_354.log tail: ADB timeout count={log_ev.get('adb_timeouts')}",
            }
        )

    if ev.get("dump_fighter_pids"):
        problems.append(
            {
                "id": "dump_fighters_running",
                "proof": f"pids={ev.get('dump_fighter_pids')} watch_bottom_ads|farm_fail_review",
            }
        )

    if ev.get("tor_collision_8218"):
        problems.append(
            {
                "id": "tor_on_inject_port",
                "proof": (
                    f"inject ports up {[min(ev.get('inject_ports') or [0]), max(ev.get('inject_ports') or [0])]} "
                    f"but matching Tor HTTP down — possible Tor/inject collision "
                    f"(legacy check named 8218/8118; live fleet uses lock-map ports)"
                ),
            }
        )

    if not ev.get("farm_pid_n"):
        problems.append({"id": "farm_worker_down", "proof": "no run_farm_354 process"})

    age = log_ev.get("log_age_s")
    if ev.get("farm_pid_n") and age is not None and float(age) > 180:
        problems.append(
            {
                "id": "farm_log_stale",
                "proof": f"farm_354.log mtime age_s={age} farm_pid={ev.get('farm_pids')}",
            }
        )

    if log_ev.get("boot_only"):
        problems.append(
            {
                "id": "farm_stuck_boot",
                "proof": (
                    "log tail has farm logging ready but no ONLINE/progress "
                    f"age_s={age} stale_active_locks={ev.get('stale_active_locks')}"
                ),
            }
        )

    lock_n = int(ev.get("lock_phones_n") or 0)
    adb_n = int(ev.get("adb_live_n") or 0)
    # No phone-count ceiling — shrunk means mapped live < currently attached ADB.
    if adb_n > 0 and lock_n < adb_n and STICKY_7.is_file():
        problems.append(
            {
                "id": "phone_map_shrunk",
                "proof": (
                    f"ADB_SERIAL_MAP mapped_live={lock_n} adb_live={adb_n} "
                    "(sticky present — rebuild from live)"
                ),
            }
        )

    if ev.get("sticky_stale"):
        problems.append(
            {
                "id": "sticky_stale",
                "proof": "FARM_STICKY serials none match adb devices",
            }
        )
    if ev.get("farm_pid_n") and not ev.get("inject_any"):
        problems.append(
            {
                "id": "inject_down",
                "proof": "run_farm_354 alive but no inject listener on mapped ports",
            }
        )
    if ev.get("farm_pid_n") and not ev.get("tor_any") and not ev.get("tor_8118"):
        problems.append(
            {
                "id": "tor_down",
                "proof": "run_farm_354 alive but no Tor HTTP tunnel listeners",
            }
        )
    if int(ev.get("lock_entries_n") or 0) > lock_n + 2:
        problems.append(
            {
                "id": "ghost_map_entries",
                "proof": (
                    f"ADB_SERIAL_MAP entries={ev.get('lock_entries_n')} "
                    f"mapped_live={lock_n}"
                ),
            }
        )

    if not ev.get("dash_8091"):
        problems.append({"id": "dash_down", "proof": "127.0.0.1:8091 not accepting TCP"})

    return problems


def _kill_pids(pids: list[int]) -> list[str]:
    fixes: list[str] = []
    try:
        import psutil

        for pid in pids:
            try:
                psutil.Process(pid).kill()
                fixes.append(f"killed_pid={pid}")
            except Exception as exc:
                fixes.append(f"kill_fail_{pid}:{exc}")
    except ImportError:
        fixes.append("kill_skip:no_psutil")
    return fixes



def _restore_sticky_7() -> list[str]:
    """Rebuild serial map + sticky from LIVE adb only — never hardcoded ghosts."""
    try:
        from automation.farm_exe_self_heal import run_self_heal

        report = run_self_heal(reason="watchdog_sticky_rebuild")
        return [f"exe_self_heal:{x}" for x in (report.get("fixes") or [])][:20]
    except Exception as exc:  # noqa: BLE001
        return [f"sticky_live_rebuild_fail:{exc}"]



def _repair_groups_config() -> list[str]:
    """Quarantine + rebuild groups_config.json when it is unreadable or unparseable."""
    fixes: list[str] = []
    try:
        if not _GROUPS_CFG.is_file():
            return fixes
        cfg = json.loads(_GROUPS_CFG.read_text(encoding="utf-8"))
        if not isinstance(cfg, dict) or not isinstance(cfg.get("groups"), list):
            raise ValueError("groups key missing or not a list")
        return fixes  # healthy — nothing to do
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        try:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            quarantine = _GROUPS_CFG.with_name(f"groups_config.corrupt_{stamp}.json")
            quarantine.write_text(
                _GROUPS_CFG.read_text(errors="replace"), encoding="utf-8"
            )
            _GROUPS_CFG.write_text('{"groups": []}\n', encoding="utf-8")
            fixes.append(f"repaired_groups_config (was: {type(exc).__name__})")
        except OSError as exc2:
            fixes.append(f"repair_groups_config_fail:{exc2}")
    return fixes


def _clear_stale_progress_locks() -> list[str]:
    fixes: list[str] = []
    p = LOG / "farm_354_progress.json"
    data = _read_json(p)
    if not data:
        return fixes
    had = bool(data.get("active_sequences") or data.get("active_keys"))
    if not had:
        return fixes
    data["active_sequences"] = []
    data["active_keys"] = []
    data["watchdog_cleared_stale"] = _utc()
    try:
        p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        fixes.append("cleared_stale_active_sequences")
    except OSError as exc:
        fixes.append(f"clear_progress_fail:{exc}")
    return fixes


def apply_fixes(problems: list[dict[str, str]], ev: dict[str, Any], *, apply: bool) -> list[str]:
    """Map proven problems → safe fixes. Dry-run when apply=False."""
    if not apply:
        return [f"dry_run would_fix={','.join(p['id'] for p in problems)}"]

    fixes: list[str] = []
    ids = {p["id"] for p in problems}

    # Money signals from a STALE FARM_MONEY_HEALTH.json are ghosts, not facts —
    # the monitor was down and the file still says $0.00. Never pause the ads
    # watcher or kill lanes over data older than 10 minutes.
    _mh = ev.get("money_health") or {}
    _mh_age = ev.get("money_health_age_s")
    _money_ghost = (
        ids <= {"money_health_alert", "flat_dollar", "impr_up_money_flat"}
        and isinstance(_mh_age, (int, float))
        and _mh_age > 600
    )
    if _money_ghost:
        fixes.append(f"money_data_stale_age_s={int(_mh_age)} — no lane kills")

    _real_paint_problems = ids & {
        "dump_fighters_running",
        "adb_timeout_storm",
        "seq_all_fail_no_ok",
        "tor_on_inject_port",
    }
    # Never write PAUSE_BOTTOM_ADS_WATCH — that flag stops ensure_watch_bottom_ads
    # and leaves phones with proxy=null / wrong inject while Chromium is FG.
    # Kill dump fighters only; keep the ads watcher alive for money.
    if _real_paint_problems:
        fixes.append("skip_pause_bottom_ads_watch (money)")
        if PAUSE_ADS.is_file():
            try:
                PAUSE_ADS.unlink()
                fixes.append("cleared_PAUSE_BOTTOM_ADS_WATCH")
            except OSError:
                pass

    if "dump_fighters_running" in ids or "adb_timeout_storm" in ids or "seq_all_fail_no_ok" in ids:
        fixes.extend(_kill_pids(list(ev.get("dump_fighter_pids") or [])))

    if ids & {"phone_map_shrunk", "farm_stuck_boot", "sticky_stale", "ghost_map_entries", "inject_down", "tor_down"}:
        fixes.extend(_restore_sticky_7())

    if "farm_stuck_boot" in ids and ev.get("stale_active_locks"):
        fixes.extend(_clear_stale_progress_locks())

    # Groups config health runs every cycle regardless of other problems — a
    # corrupt file blocks group editing silently while the farm itself runs fine.
    try:
        fixes.extend(_repair_groups_config())
    except Exception as exc:  # noqa: BLE001 — watchdog must never crash on repair
        fixes.append(f"groups_repair_err:{exc}")

    try:
        from automation.farm_money_monitor import cull_hung_adb, evaluate

        culled = cull_hung_adb(max_kill=20, min_age_s=25)
        if culled:
            fixes.append(f"cull_hung_adb={culled}")
    except Exception as exc:
        fixes.append(f"cull_adb_err:{exc}")

    money_ids = {"flat_dollar", "money_health_alert", "impr_up_money_flat"}
    if ids & money_ids:
        try:
            from automation.farm_money_monitor import evaluate

            state = evaluate(flat_min=8.0, do_fix=True)
            fixes.append(f"money_evaluate alert={state.get('alert')} flat={state.get('flat')}")
            fixes.extend((state.get("auto_fixes") or [])[-6:])
        except Exception as exc:
            fixes.append(f"money_evaluate_err:{exc}")

    if "tor_on_inject_port" in ids:
        # Never spawn roster _fix_tor_inject_ports_now (hardcoded 8218 storm +
        # 120s timeout). Clear pause only; farm/EXE owns absolute inject ports.
        fixes.append("skip_fix_tor_inject (use lock-map ports; no 8218 helper)")
        if PAUSE_ADS.is_file():
            try:
                PAUSE_ADS.unlink()
                fixes.append("cleared_PAUSE_BOTTOM_ADS_WATCH")
            except OSError:
                pass

    if "adb_timeout_storm" in ids or "seq_all_fail_no_ok" in ids:
        script = ROOT / "scripts" / "_unwedge_uiautomator_now.py"
        if script.is_file():
            code, out = _run([_helper_py(), str(script)], timeout=90)
            fixes.append(f"unwedge exit={code}")

    # Only reload farm when worker down or stuck boot — never on adb timeout alone.
    if "farm_worker_down" in ids or "farm_stuck_boot" in ids:
        (LOG / "FARM_RELOAD_FARM.flag").write_text("watchdog_investigate", encoding="utf-8")
        fixes.append("flagged_FARM_RELOAD")

    if "dash_down" in ids:
        script = ROOT / "scripts" / "farm_operator_dash.py"
        pyw = Path(r"C:\Users\jsmil\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe")
        if script.is_file() and pyw.is_file():
            subprocess.Popen(
                [str(pyw), "-u", str(script)],
                cwd=str(ROOT),
                creationflags=FLAGS,
            )
            fixes.append("spawned_farm_operator_dash")

    # Duplicates are already deduped by the supervisor (dedupe_keep_newest);
    # the old blanket re-kill here murdered the supervised lanes every cycle.

    return fixes


def investigate(*, apply: bool = True) -> dict[str, Any]:
    """One full research + optional fix pass. Writes watchdog_farm_investigation.json."""
    ev = gather_evidence()
    problems = detect_problems(ev)
    fixes = apply_fixes(problems, ev, apply=apply) if problems else []
    report = {
        "ts": _utc(),
        "apply": apply,
        "evidence": ev,
        "problems": problems,
        "fixes": fixes,
        "problem_count": len(problems),
    }
    try:
        LOG.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    return report


def format_report(report: dict[str, Any]) -> str:
    lines = [
        f"WATCHDOG FARM {report.get('ts')} apply={report.get('apply')}",
        f"problems={report.get('problem_count')}",
    ]
    m = (report.get("evidence") or {}).get("mantis") or {}
    log_ev = (report.get("evidence") or {}).get("log") or {}
    lines.append(
        f"FACT $={m.get('payout_usd')} clk={m.get('clicks')} impr={m.get('impressions')} "
        f"log_age_s={log_ev.get('log_age_s')} p3_ok={log_ev.get('p3_ok')} p3_fail={log_ev.get('p3_fail')} "
        f"adb_live={(report.get('evidence') or {}).get('adb_live_n')}"
    )
    for p in report.get("problems") or []:
        lines.append(f"  ! {p.get('id')}: {p.get('proof')}")
    for f in report.get("fixes") or []:
        lines.append(f"  fix: {f}")
    return "\n".join(lines)
