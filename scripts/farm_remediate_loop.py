#!/usr/bin/env python3
"""Continuous remediating farm monitor — every ~60s. CPharm owns farm; no dual start.

Owns: FIXES + PROFIT math + phone COORDINATION + DASH keep-alive (:8091).
Writes authoritative C:\\CPharm\\logs\\FARM_HONEST_NOW.txt and farm_remediator_profit.json.

Never cull farm_operator_dash. If :8091 is down, restart it immediately every cycle.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

LOG = Path(r"C:\CPharm\logs")
HONEST = LOG / "FARM_HONEST_NOW.txt"
TICK_LOG = LOG / "farm_remediate_loop.jsonl"
PROFIT_JSON = LOG / "farm_remediator_profit.json"
SSP_FLAG = LOG / "SSP_FORCE_REFRESH.flag"
FLAT_FLAG = LOG / "FARM_FLAT_DOLLAR.flag"
MANTIS = LOG / "mantis_today_state.json"
PROGRESS = LOG / "farm_354_progress.json"
ADS_WATCH = LOG / "ads_watch_state.json"
DASH_URL = "http://127.0.0.1:8091"
DASH_PORT = 8091

ADB = r"C:\CPharm\bundled\adb.exe"
if not Path(ADB).is_file():
    ADB = "adb"

# Fallback seed if discover returns empty (cold start).
_FALLBACK_PHONES: tuple[tuple[str, str, str], ...] = (
    ("vm0", "10.0.2.222:5555", "127.0.0.1:8218"),
    ("vm1", "10.0.2.171:5555", "127.0.0.1:8219"),
    ("vm2", "10.0.2.27:5555", "127.0.0.1:8220"),
    ("vm3", "10.0.2.156:5555", "127.0.0.1:8221"),
    ("vm5", "10.0.2.115:5555", "127.0.0.1:8223"),
    ("vm6", "10.0.2.75:5555", "127.0.0.1:8224"),
    ("vm7", "10.0.2.184:5555", "127.0.0.1:8225"),
    ("vm8", "10.0.2.179:5555", "127.0.0.1:8226"),
    ("vm9", "10.0.2.124:5555", "127.0.0.1:8227"),
)
TABLET_SERIAL = os.environ.get("CPHARM_TABLET_SERIAL", "10.0.2.155:5555").strip()

# Operator money rails — remediator calculates against these every cycle.
TARGET_FLOOR_USD = 40.0
TARGET_STRONG_USD = 55.0
TARGET_STRETCH_USD = 100.0

INTERVAL_S = float(os.environ.get("CPHARM_REMEDIATE_INTERVAL_S", "60"))
ROOT = Path(__file__).resolve().parents[1]
DASH_SCRIPT = ROOT / "scripts" / "farm_operator_dash.py"
_FAIL_REVIEW_MOD = None
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import automation.no_window  # noqa: E402,F401  — CREATE_NO_WINDOW (cull WT-adb flash)
from automation.farm_phone_discover import (  # noqa: E402
    discover_live_phones,
    inject_proxy_for_name,
    persist_discovered,
)
from automation.farm_canonical_phones import (  # noqa: E402
    CANONICAL_FARM_PHONES,
    ban_serials_csv,
    canonical_expect_phones,
    canonical_inject_ports,
    canonical_names_sorted,
    canonical_serials_sorted,
    canonical_workset,
    is_banned_serial,
)
from automation.config import BROWSER_FARMBROWSER  # noqa: E402
from automation.farm_health_audit import HEAT_DOWN as _HEAT_DOWN_RAILS  # noqa: E402
from automation.farm_health_audit import HOLD as _HOLD_RAILS  # noqa: E402

FB_ACTIVITY = "com.farmbrowser.stealth.browser.BrowserActivity"
from automation.farm_health_audit import behind_on_path3_clicks as _behind_clicks  # noqa: E402
from automation.farm_health_audit import audit as health_audit  # noqa: E402
from automation.farm_health_audit import scale_csv as _scale_csv  # noqa: E402
from automation.farm_process_janitor import sweep_dead_processes  # noqa: E402
from automation.farm_checkin import inject_pin_needed  # noqa: E402
from automation.farm_visit_caps import enforce_multi_browser  # noqa: E402
from automation.mumu_fingerprint import (  # noqa: E402
    ensure_windows_gpu_prefs_for_mumu,
    reassert_all_vm_gpu_accel,
)
from wizard.wizard_paths import mumu_vms_dir  # noqa: E402


def _active_money_rails() -> dict[str, str]:
    """Respect auditor heat-down flag so remediator doesn't re-crank the oven.

    UTC $0 / clicks 0 is not dilution — keep HOLD seqs/Path3 even if the flag
    is present from an earlier house-only tick.
    """
    flag = LOG / "FARM_HEAT_DOWN.flag"
    if flag.is_file() and not _behind_clicks():
        return dict(_HEAT_DOWN_RAILS)
    return dict(_HOLD_RAILS)


def live_phones() -> list[tuple[str, str, str]]:
    """Canonical 8 money phones — never adaptive bleed to ghost VMs."""
    online = set(adb_online())
    rows = canonical_workset(online)
    live = [(short, serial, proxy) for short, serial, proxy in rows if serial in online]
    if live:
        persist_discovered(live)
    return rows


# Back-compat alias — modules that still read PHONES get last discover or fallback.
PHONES = _FALLBACK_PHONES


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dash_port_ok() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", DASH_PORT), timeout=2.0):
            return True
    except OSError:
        return False


def ensure_farm_reload_if_flagged() -> list[str]:
    """Operator/agent can drop FARM_RELOAD_FARM.flag to respawn run_farm_354 with new sticky.

    Soft-reload is allowed even when CPharm.exe owns the farm — we only recycle
    the run_farm_354 worker with current overrides (not ensure_farm takeover).
    Skipping spawn here left Path3 stuck on a stale env cap (e.g. 192 vs 324).
    """
    flag = LOG / "FARM_RELOAD_FARM.flag"
    if not flag.is_file():
        return []
    fixes: list[str] = ["FARM_RELOAD_FARM.flag seen"]
    try:
        flag.unlink(missing_ok=True)
    except OSError:
        pass
    from automation.cpharm_exe_owned import exe_owns_farm

    if exe_owns_farm():
        fixes.append("exe_owned_soft_reload_worker")
    try:
        import psutil
    except Exception as exc:
        return [f"farm_reload_psutil_err:{exc}"]
    killed: list[int] = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        cmd = " ".join(p.info.get("cmdline") or [])
        if "run_farm_354" in cmd:
            try:
                p.kill()
                killed.append(int(p.info["pid"]))
            except Exception:
                pass
    if killed:
        fixes.append(f"killed_farm_354={killed}")
        time.sleep(2.0)
    farm_script = ROOT / "scripts" / "run_farm_354.py"
    if not farm_script.is_file():
        fixes.append("farm_script_missing")
        return fixes
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    if not Path(pyw).is_file():
        pyw = sys.executable
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    try:
        ov = json.loads((LOG / "farm_runtime_overrides.json").read_text(encoding="utf-8-sig"))
        if isinstance(ov, dict):
            for k, v in ov.items():
                if str(k).startswith("CPHARM_") and v is not None:
                    env[str(k)] = str(v)
    except Exception:
        pass
    env["CPHARM_FARM_CHROMIUM_ONLY"] = "0"
    env["CPHARM_FARM_BROWSERS"] = "chromium,firefox,brave"
    env["CPHARM_FARM_PATH3_BROWSERS"] = "chromium"
    env["CPHARM_FARM_STOP"] = "0"
    env["CPHARM_FARM_UNIQUE_SEQ"] = "1"
    try:
        proc = subprocess.Popen(
            [pyw, "-u", str(farm_script)],
            cwd=str(ROOT),
            env=env,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0) or 0x08000000,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        fixes.append(f"spawned_farm_354 pid={proc.pid}")
        (LOG / "_farm_reload_last.json").write_text(
            json.dumps({"ts": _utc(), "fixes": fixes}, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        fixes.append(f"spawn_farm_err:{exc}")
    return fixes


def _dash_process_alive() -> bool:
    try:
        import psutil
    except ImportError:
        return False
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            name = str(proc.info.get("name") or "").lower()
            if name not in ("python.exe", "pythonw.exe"):
                continue
            cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or [])).lower()
            if "farm_operator_dash.py" in cmd:
                return True
        except Exception:
            continue
    return False


def ensure_dash_up() -> list[str]:
    """Keep :8091 up. Never cull a listening dash; only spawn if none exist."""
    fixes: list[str] = []
    try:
        from automation.process_scan import cull_duplicates_keep_newest

        fixes.extend(cull_duplicates_keep_newest(("farm_operator_dash.py",)))
    except Exception:
        pass
    if _dash_port_ok():
        return fixes
    if _dash_process_alive():
        for _ in range(10):
            time.sleep(0.5)
            if _dash_port_ok():
                return fixes
        fixes.append("DASH_DOWN hung_dash — replacing")
        try:
            import psutil

            for proc in psutil.process_iter(["name", "cmdline"]):
                name = str(proc.info.get("name") or "").lower()
                cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or [])).lower()
                if name in ("python.exe", "pythonw.exe") and "farm_operator_dash.py" in cmd:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        except Exception:
            pass
        time.sleep(0.4)
    else:
        fixes.append("DASH_DOWN detected — restarting farm_operator_dash :8091")
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    if not Path(pyw).is_file():
        pyw = sys.executable
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    try:
        subprocess.Popen(
            [pyw, "-u", str(DASH_SCRIPT)],
            cwd=str(ROOT),
            env=env,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0) or 0x08000000,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(16):
            time.sleep(0.4)
            if _dash_port_ok():
                fixes.append("DASH_UP restored http://127.0.0.1:8091/")
                return fixes
        fixes.append("DASH_RESTART_FAILED still_down")
    except Exception as exc:
        fixes.append(f"DASH_RESTART_ERR:{exc}")
    return fixes


def _adb(serial: str, *args: str, timeout: float = 8.0) -> str:
    try:
        p = subprocess.run(
            [ADB, "-s", serial, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)),
        )
        return ((p.stdout or "") + (p.stderr or "")).strip()
    except Exception as exc:
        return f"ERR:{exc}"


def _adb_global(*args: str, timeout: float = 8.0) -> str:
    try:
        p = subprocess.run(
            [ADB, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)),
        )
        return ((p.stdout or "") + (p.stderr or "")).strip()
    except Exception as exc:
        return f"ERR:{exc}"


def cull_adb_shells() -> list[str]:
    """Reap hung ADB, orphan consoles, leak bash/wsl, duplicate helpers."""
    return sweep_dead_processes()


def _repin_proxy(serial: str, port: int) -> str:
    """adb reverse inject(+tor) then pin guest http_proxy; re-assert after :0 races."""
    want = f"127.0.0.1:{port}"
    tor = 8118 + (port - 8218)
    cur = get_proxy(serial)
    _adb(serial, "reverse", f"tcp:{port}", f"tcp:{port}", timeout=8.0)
    _adb(serial, "reverse", f"tcp:{tor}", f"tcp:{tor}", timeout=6.0)
    _adb(serial, "shell", "settings", "put", "global", "http_proxy", want, timeout=5.0)
    time.sleep(0.2)
    # Isolate often flips :0 in the same second — re-assert.
    _adb(serial, "shell", "settings", "put", "global", "http_proxy", want, timeout=5.0)
    got = get_proxy(serial)
    listing = _adb(serial, "reverse", "--list", timeout=6.0)
    rev_ok = f"tcp:{port}" in (listing or "")
    return f"repin {serial}->{want} got={got} reverse_ok={rev_ok} had={cur}"


def _is_money_browser_fg(top: str) -> bool:
    t = (top or "").lower()
    return "farmbrowser" in t


def _is_true_chromium(top: str) -> bool:
    """Legacy name — true when FarmBrowser (or Chromium fallback) is FG."""
    if _is_money_browser_fg(top):
        return True
    t = (top or "").lower()
    return "org.chromium.chrome" in t and "brave" not in t and "opera" not in t


def inject_listen_ok(phones: list[tuple[str, str, str]] | None = None) -> bool:
    """Inject listeners for canonical 8 (8218+idx per vm)."""
    needed = set(canonical_inject_ports())
    ok = 0
    for port in sorted(needed):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                ok += 1
        except OSError:
            pass
    threshold = max(1, len(needed) - 1)
    return ok >= threshold


def _lock_money_sticky() -> list[str]:
    """Sync live phone discovery only — do NOT rewrite operator rails every tick.

    Operator knobs live in farm_operator_config.json (set at resume / dash).
    Remediator only updates serial map + phone count when ADB set changes.
    """
    fixes: list[str] = []
    phones = live_phones()
    global PHONES
    PHONES = tuple(phones)  # type: ignore[misc]
    money_phones = ",".join(canonical_names_sorted())
    money_serials = ",".join(canonical_serials_sorted())
    n = str(canonical_expect_phones())
    sticky_names = canonical_names_sorted()
    sticky_serials = canonical_serials_sorted()
    lock_path = LOG / "ADB_SERIAL_MAP.lock.json"
    try:
        if lock_path.is_file():
            lock_raw = json.loads(lock_path.read_text(encoding="utf-8-sig"))
            pmap = dict(lock_raw.get("phones") or {})
            # Keep lock if it already has full canonical set; never adopt adaptive ghosts.
            lock_names = sorted(
                pmap.keys(),
                key=lambda nm: int(nm.split(".")[0][2:]) if nm.split(".")[0][2:].isdigit() else 99,
            )
            if len(lock_names) >= canonical_expect_phones():
                sticky_names = lock_names
                sticky_serials = [str(pmap[nm]) for nm in sticky_names if pmap.get(nm)]
                money_phones = ",".join(sticky_names)
                money_serials = ",".join(sticky_serials)
                n = str(len(sticky_names))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    # Operator: every online phone farms (including former tablet vm4).
    tablet_farms = str(
        os.environ.get("CPHARM_TABLET_FARM")
        or ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    try:
        from automation.cpharm_farm_config import get_runtime

        peek = get_runtime()
        if str(peek.get("CPHARM_TABLET_FARM") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            tablet_farms = True
    except Exception:
        pass
    want = {
        "CPHARM_FARM_PHONES": money_phones,
        "CPHARM_FARM_PHONE_COUNT": n,
        "CPHARM_FARM_EXPECT_PHONES": n,
        "CPHARM_ADB_SERIALS": money_serials,
        "CPHARM_FARM_BAN_SERIALS": ban_serials_csv(),
    }
    if tablet_farms:
        want["CPHARM_TABLET_FARM"] = "1"
        want["CPHARM_TABLET_PHONE"] = ""
        want["CPHARM_TABLET_SERIAL"] = ""
    else:
        want["CPHARM_TABLET_PHONE"] = "vm4.gmadoa"
        want["CPHARM_TABLET_SERIAL"] = TABLET_SERIAL
    ov_path = LOG / "farm_runtime_overrides.json"
    try:
        from automation.cpharm_farm_config import get_runtime, merge_runtime, write_adb_serial_lock

        data = get_runtime()
        changed = False
        for k, v in want.items():
            if str(data.get(k) or "") != str(v):
                changed = True
        if enforce_multi_browser(data):
            changed = True
        if changed:
            merge_runtime(want, note="phones_sync")
            buf = get_runtime()
            if enforce_multi_browser(buf):
                from automation.farm_visit_caps import _MULTI_BROWSER_KEYS

                merge_runtime({k: buf[k] for k, _ in _MULTI_BROWSER_KEYS}, note="browser_ssot")
            live_map = {name: serial for name, serial, _p in phones}
            write_adb_serial_lock(live_map)
            fixes.append("phones_sync")
        # Heat-down only: touch caps/site when operator flag says dilution — not every tick.
        if (LOG / "FARM_HEAT_DOWN.flag").is_file():
            rails = _active_money_rails()
            caps_path = LOG / "farm_visit_caps_lock.json"
            site_path = LOG / "farm_site_lock.json"
            try:
                caps = {}
                if caps_path.is_file():
                    caps = json.loads(caps_path.read_text(encoding="utf-8-sig"))
                if not isinstance(caps, dict):
                    caps = {}
                want_visits = _scale_csv(rails["visits"], max(4, len(phones)))
                want_ads = _scale_csv(rails["ads"], max(4, len(phones)), min_val=16, step=0)
                if (
                    str(caps.get("CPHARM_FARM_SEQS_PER_HOUR") or "") != rails["seqs"]
                    or str(caps.get("CPHARM_FARM_DAILY_VISITS") or "") != want_visits
                ):
                    caps["CPHARM_FARM_SEQS_PER_HOUR"] = rails["seqs"]
                    caps["CPHARM_FARM_DAILY_VISITS"] = want_visits
                    caps["note"] = "remediator_rails_heat"
                    caps["updated"] = _utc()
                    caps_path.write_text(json.dumps(caps, indent=2) + "\n", encoding="utf-8")
                    fixes.append("caps_lock_heat")
                if site_path.is_file():
                    site = json.loads(site_path.read_text(encoding="utf-8-sig"))
                    if isinstance(site, dict) and (
                        str(site.get("daily_visits_csv") or "") != want_visits
                        or str(site.get("daily_ads_csv") or "") != want_ads
                    ):
                        site["daily_visits_csv"] = want_visits
                        site["daily_ads_csv"] = want_ads
                        site["note"] = "remediator_rails_heat"
                        site["updated"] = _utc()
                        site_path.write_text(json.dumps(site, indent=2) + "\n", encoding="utf-8")
                        fixes.append("site_lock_heat")
            except Exception as exc:
                fixes.append(f"caps_lock_err:{exc}")
    except Exception as exc:
        fixes.append(f"sticky_lock_err:{exc}")

    lock_path = LOG / "ADB_SERIAL_MAP.lock.json"
    try:
        sticky_path = LOG / "FARM_STICKY_7_PHONES.lock"
        tablet_block: dict[str, str] = {}
        if not sticky_path.is_file():
            tablet_block = {"vm4.gmadoa": TABLET_SERIAL}
        expect = canonical_expect_phones()
        try:
            ov_peek = LOG / "farm_runtime_overrides.json"
            if ov_peek.is_file():
                peek = json.loads(ov_peek.read_text(encoding="utf-8-sig"))
                expect = max(
                    expect,
                    int(str(peek.get("CPHARM_FARM_EXPECT_PHONES") or canonical_expect_phones()) or canonical_expect_phones()),
                )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
        live_clean = [
            (name, serial, proxy)
            for name, serial, proxy in PHONES
            if not is_banned_serial(serial)
        ]
        if len(live_clean) < expect:
            fixes.append(f"adb_lock_skip_shrink n={len(live_clean)} expect={expect}")
            lock = {
                "phones": dict(CANONICAL_FARM_PHONES),
                "tablet": tablet_block,
                "inject": {
                    nm: 8218 + int(nm.split(".")[0][2:])
                    for nm in CANONICAL_FARM_PHONES
                },
                "locked_at": _utc(),
                "note": f"canonical_sticky expect={expect} live={len(live_clean)}",
                "updated": _utc(),
            }
            lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
            fixes.append("canonical_lock_restored")
        else:
            phones_map = dict(CANONICAL_FARM_PHONES)
            for short, serial, _proxy in live_clean:
                fname = f"{short}.gmadoa" if not str(short).endswith(".gmadoa") else short
                ser = str(serial or "").strip()
                if fname in phones_map and ser.startswith("10.0.2.") and not is_banned_serial(ser):
                    phones_map[fname] = ser
            lock = {
                "phones": phones_map,
                "tablet": tablet_block,
                "inject": {
                    nm: 8218 + int(nm.split(".")[0][2:]) for nm in phones_map
                },
                "locked_at": _utc(),
                "note": f"canonical_sticky live={len(live_clean)} expect={expect}",
                "updated": _utc(),
            }
            lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        fixes.append(f"adb_lock_err:{exc}")
    return fixes


def calc_profit(mantis: dict, *, ssp: dict | None = None) -> dict:
    """Operator profit math vs $40 / $55 / $100 rails. Remediator owns this."""
    payout = float(mantis.get("payout_usd") or 0)
    clicks = int(mantis.get("clicks") or 0)
    impr = int(mantis.get("impressions") or 0)
    ecpm = float(mantis.get("ecpm") or 0)
    evcpm = float(mantis.get("evcpm") or 0)
    receivable = float(mantis.get("receivable_usd") or 0)
    ctr = (100.0 * clicks / impr) if impr > 0 else 0.0
    try:
        now_pt = datetime.now(ZoneInfo("America/Los_Angeles"))
    except Exception:
        now_pt = datetime.now(timezone.utc)
    day_start = now_pt.replace(hour=0, minute=0, second=0, microsecond=0)
    hours_elapsed = max(0.05, (now_pt - day_start).total_seconds() / 3600.0)
    hours_left = max(0.0, 24.0 - hours_elapsed)
    usd_per_hour = payout / hours_elapsed
    proj_eod = usd_per_hour * 24.0
    gap_floor = round(max(0.0, TARGET_FLOOR_USD - payout), 2)
    gap_strong = round(max(0.0, TARGET_STRONG_USD - payout), 2)
    gap_stretch = round(max(0.0, TARGET_STRETCH_USD - payout), 2)
    need_hr_floor = (gap_floor / hours_left) if hours_left > 0.25 else gap_floor
    if payout >= TARGET_STRETCH_USD:
        tone = "stretch"
    elif payout >= TARGET_STRONG_USD:
        tone = "strong"
    elif payout >= TARGET_FLOOR_USD:
        tone = "floor"
    elif proj_eod >= TARGET_FLOOR_USD:
        tone = "pace_ok"
    else:
        tone = "behind"
    paying = (ssp or {}).get("paying")
    return {
        "ts": _utc(),
        "local_date": now_pt.strftime("%Y-%m-%d"),
        "hours_elapsed": round(hours_elapsed, 2),
        "hours_left": round(hours_left, 2),
        "payout_usd": payout,
        "receivable_usd": receivable,
        "clicks": clicks,
        "impressions": impr,
        "ctr_pct": round(ctr, 3),
        "ecpm": ecpm,
        "evcpm": evcpm,
        "usd_per_hour": round(usd_per_hour, 3),
        "proj_eod_usd": round(proj_eod, 2),
        "target_floor_usd": TARGET_FLOOR_USD,
        "target_strong_usd": TARGET_STRONG_USD,
        "target_stretch_usd": TARGET_STRETCH_USD,
        "gap_floor_usd": gap_floor,
        "gap_strong_usd": gap_strong,
        "gap_stretch_usd": gap_stretch,
        "need_usd_per_hour_for_floor": round(need_hr_floor, 3),
        "ssp_paying": paying,
        "tone": tone,
        "source": mantis.get("source") or "mantis_today_state",
    }


def coordinate_phones(online: list[str]) -> tuple[list[dict], list[str]]:
    """Pin Chromium to inject. Do not fight Firefox/Brave MITM-skip ``:0``."""
    fixes: list[str] = []
    rows: list[dict] = []
    for name, serial, proxy in PHONES:
        if serial not in online:
            rows.append(
                {
                    "name": name,
                    "serial": serial,
                    "state": "OFFLINE",
                    "proxy": "?",
                    "top": "?",
                    "want": proxy,
                }
            )
            continue
        port = int(proxy.rsplit(":", 1)[-1])
        cur = get_proxy(serial)
        top = top_pkg(serial)
        if inject_pin_needed(cur, proxy, top):
            # Wrong port or Chromium :0 after isolate — always fix.
            fixes.append(_repin_proxy(serial, port))
            cur = get_proxy(serial)
            if inject_pin_needed(cur, proxy, top):
                time.sleep(0.35)
                fixes.append(_repin_proxy(serial, port))
                cur = get_proxy(serial)
                top = top_pkg(serial)
        rows.append(
            {
                "name": name,
                "serial": serial,
                "state": "device",
                "proxy": cur,
                "top": (top or "")[:100],
                "want": proxy,
                "proxy_ok": not inject_pin_needed(cur, proxy, top),
            }
        )
    return rows, fixes


def _non_money_fg(top: str) -> bool:
    t = (top or "").lower()
    return any(
        x in t
        for x in (
            "lawnchair",
            "launcher",
            "gallery3d",
            "camera",
            "vending",
            "contacts",
            "dialer",
            "not responding",
            "anr",
            "unknown",
            "err:",
            "settings",
            "systemui",
            "packageinstaller",
        )
    )


def _ensure_ca(serial: str) -> str:
    """Reinstall MITM CA after MuMu wipe / IMEI scramble (fixes 'Internet not private')."""
    try:
        from automation.adb_wrapper import AdbWrapper
        from automation.mantis_inject_ca import install_ca_on_device

        adb = AdbWrapper(ADB)
        ok = bool(install_ca_on_device(adb, serial))
        return f"ca_install {serial} ok={ok}"
    except Exception as exc:
        return f"ca_install {serial} err={exc}"


_CA_STAMP = LOG / "_last_ca_install_ts.json"


def _ca_due(serial: str, *, every_s: float = 3600.0) -> bool:
    try:
        data = json.loads(_CA_STAMP.read_text(encoding="utf-8")) if _CA_STAMP.exists() else {}
    except Exception:
        data = {}
    last = float(data.get(serial) or 0)
    return (time.time() - last) >= every_s


def _mark_ca(serial: str) -> None:
    try:
        data = json.loads(_CA_STAMP.read_text(encoding="utf-8")) if _CA_STAMP.exists() else {}
    except Exception:
        data = {}
    data[serial] = time.time()
    _CA_STAMP.write_text(json.dumps(data), encoding="utf-8")


def top_pkg(serial: str) -> str:
    """Return resumed package — MuMu often lies via dumpsys activity top / focus."""
    out = _adb(serial, "shell", "dumpsys", "activity", "activities", timeout=8.0)
    m = re.search(r"topResumedActivity=ActivityRecord\{[^ ]+ u0 ([^/]+)/", out or "")
    if m:
        return m.group(1)
    m2 = re.search(r"mFocusedApp=ActivityRecord\{[^ ]+ u0 ([^/]+)/", out or "")
    if m2:
        return m2.group(1)
    # Fallback: first ACTIVITY line (may be stale Lawnchair on MuMu).
    out2 = _adb(serial, "shell", "dumpsys", "activity", "top", timeout=6.0)
    for line in (out2 or "").splitlines():
        if "ACTIVITY" in line:
            return line.strip()[:160]
    return (out2 or out or "")[:80] or "unknown"


def get_proxy(serial: str) -> str:
    raw = _adb(serial, "shell", "settings", "get", "global", "http_proxy", timeout=5.0)
    lines = [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]
    return lines[0] if lines else ""


def revive_phone(
    name: str,
    serial: str,
    proxy: str,
    *,
    need_more_chromium: bool = True,
    top: str | None = None,
    allow_ui_rearm: bool = True,
) -> list[str]:
    """Repin inject; re-arm Chromium when idle OR when FG Chromium count is below 4.

    Path1/2 Brave/Opera rotates are left alone once Chromium FG >= 4 — re-arm
    only when money phones drop below that floor (or Lawnchair/ANR).

    When farm sequences are active, skip am_start/taps/swipe — those fight
    UniqueSequenceLock runs and cause tap FAILs. Proxy repin always allowed.
    """
    fixes: list[str] = []
    _adb(serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP", timeout=4.0)
    port = int(proxy.rsplit(":", 1)[-1])
    cur = get_proxy(serial)
    # Always reverse+reassert when :0 / wrong / drift — isolate races clear pins.
    if cur != proxy or cur in (":0", "null", "", "none"):
        fixes.append(_repin_proxy(serial, port))
    if top is None:
        top = top_pkg(serial)
    top_l = (top or "").lower()
    idle = _non_money_fg(top)
    # Money BOTTOM_ADS needs true Chromium FG — Brave/Opera share chrome.Main dumpsys.
    chrom = _is_money_browser_fg(top) or _is_true_chromium(top)
    other_browser = any(
        x in top_l
        for x in ("brave", "firefox", "opera", "duckduckgo", "org.chromium.chrome")
    ) and not _is_money_browser_fg(top)
    # Hold Brave/FF/Opera Path1/2 when Chromium floor already met.
    if chrom:
        return fixes
    if other_browser and not need_more_chromium and not idle:
        return fixes
    anr = "not responding" in top_l or "anr" in top_l
    # Mid-farm: still re-arm Lawnchair/gallery/settings/idle — those are not
    # "sequence owns the screen", they are dead FG. Only skip rearm when some
    # other non-idle app is up (rare) and farm is active.
    if not allow_ui_rearm and not anr and not idle:
        fixes.append(f"skip_ui_rearm {name} farm_active")
        return fixes
    if idle or need_more_chromium or anr:
        if anr:
            _adb(serial, "shell", "am", "force-stop", BROWSER_FARMBROWSER, timeout=6.0)
            _adb(serial, "shell", "am", "force-stop", "org.chromium.chrome", timeout=6.0)
            fixes.append(f"force_stop_anr {name}")
        try:
            from automation.farm_launch_guard import (
                DENIED_LAUNCH_PACKAGES,
                is_denied_launch_package,
                package_from_top_line,
            )

            stray = package_from_top_line(top or "")
            if stray and is_denied_launch_package(stray):
                _adb(serial, "shell", "am", "force-stop", stray, timeout=6.0)
                fixes.append(f"force_stop_stray {name} {stray}")
            for pkg in DENIED_LAUNCH_PACKAGES:
                if pkg in top_l:
                    _adb(serial, "shell", "am", "force-stop", pkg, timeout=6.0)
                    fixes.append(f"force_stop_stray {name} {pkg}")
        except Exception as exc:
            fixes.append(f"stray_stop_err {name} {exc}")
        if other_browser and need_more_chromium:
            # Soft-stop competing browsers so Chromium can hold FG across rotate.
            for pkg in (
                "com.brave.browser",
                "org.mozilla.firefox",
                "com.opera.browser",
                "com.duckduckgo.mobile.android",
            ):
                if pkg.split(".")[1] in top_l or pkg in top_l:
                    _adb(serial, "shell", "am", "force-stop", pkg, timeout=6.0)
                    fixes.append(f"force_stop_other {name} {pkg}")
        out = _adb(
            serial,
            "shell",
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            "https://getdabflow.app/",
            "-n",
            f"{BROWSER_FARMBROWSER}/{FB_ACTIVITY}",
            timeout=10.0,
        )
        fixes.append(f"am_start_dabflow {name} {out[:40]}")
        time.sleep(1.2)
        top2 = top_pkg(serial)
        if not (_is_money_browser_fg(top2) or _is_true_chromium(top2)):
            # Never tap Lawnchair/home — dock icons are Camera/Gallery/Play Store.
            fixes.append(f"skip_age_gate_taps {name} fg={top2[:60]}")
        else:
            for x, y in ((540, 1020), (450, 900), (270, 1020)):
                _adb(serial, "shell", "input", "tap", str(x), str(y), timeout=3.0)
            fixes.append(f"age_gate_taps {name}")
            # Remount dabflow after wipe/#recommended: light scroll so bottom slot paints.
            _adb(serial, "shell", "input", "swipe", "450", "1200", "450", "600", "350", timeout=4.0)
            fixes.append(f"scroll_remount {name}")
        # Re-pin after browser start — isolate/scramble often flips :0 mid-launch.
        got2 = get_proxy(serial)
        if got2 != proxy:
            fixes.append(_repin_proxy(serial, port))
    return fixes


def adb_online() -> list[str]:
    out = _adb_global("devices", timeout=8.0)
    online = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            online.append(parts[0])
    return online


def reconnect_missing(online: list[str]) -> list[str]:
    fixes = []
    for name, serial, _proxy in PHONES:
        if serial not in online:
            out = _adb_global("connect", serial, timeout=8.0)
            fixes.append(f"adb_connect {name} {serial} {out[:60]}")
    return fixes


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def pull_mantis_soft() -> dict:
    try:
        import urllib.request

        req = urllib.request.Request(
            "http://127.0.0.1:8091/api/mantis_pull",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode())
    except Exception as exc:
        return {"error": str(exc)}


def ssp_probe() -> dict:
    try:
        from automation.dabflow_mantis_client_patch import (
            clear_ssp_cache,
            prefetch_ssp_ads,
            ssp_ads_paying_count,
            prefetch_ssp_ads_prefer_paying,
        )

        clear_ssp_cache()
        raw = prefetch_ssp_ads(force=True) or []
        paying = int(ssp_ads_paying_count(raw))
        house = max(0, len(raw) - paying)
        pref = []
        if paying == 0:
            pref = prefetch_ssp_ads_prefer_paying(
                attempts=4, delay_s=0.3, allow_house_fallback=False
            ) or []
        payload = {
            "paying": paying,
            "house": house,
            "count": len(raw),
            "prefer_paying": ssp_ads_paying_count(pref) if pref is not None else 0,
            "ts": _utc(),
        }
        SSP_FLAG.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
    except Exception as exc:
        return {"error": str(exc), "paying": -1, "house": -1}


def cycle() -> dict:
    fixes: list[str] = []
    try:
        from automation.farm_pause import farm_halted, is_killed, is_paused, seconds_until_resume

        if farm_halted():
            left = int(seconds_until_resume()) if is_paused() else -1
            fixes.append("killed" if is_killed() else f"paused_left={left}s")
            # Keep dash truth while farm sleeps.
            fixes.extend(ensure_dash_up())
            state = {
                "ts": _utc(),
                "paused": True,
                "seconds_until_resume": left,
                "adb_online": len(adb_online()),
                "fixes": fixes,
            }
            try:
                HONEST.write_text(
                    f"FARM PAUSED — resume in {left}s\nDASH {DASH_URL}\n",
                    encoding="utf-8",
                )
            except OSError:
                pass
            return state
    except Exception as exc:
        fixes.append(f"pause_err:{exc}")
    # Heartbeat BEFORE heavy work so operators can see the loop is alive.
    try:
        (LOG / "_remediator_heartbeat.txt").write_text(_utc() + "\n", encoding="utf-8")
    except OSError:
        pass
    # DASH is operator truth — keep it up BEFORE anything else. Never cull it.
    fixes.extend(ensure_dash_up())
    # Keep MuMu on Adreno High / DirectX (Snapdragon). NPU is not used by MuMu.
    try:
        stamp = LOG / "_gpu_reassert_ts.txt"
        due = True
        if stamp.is_file():
            try:
                age = time.time() - stamp.stat().st_mtime
                due = age >= float(os.environ.get("CPHARM_GPU_REASSERT_S", "600"))
            except OSError:
                due = True
        if due:
            vms_env = (os.environ.get("CPHARM_MUMU_VMS") or "").strip()
            if vms_env:
                vms = Path(vms_env)
            else:
                vms = mumu_vms_dir() or Path(r"C:\Program Files\Netease\MuMuPlayer\vms")
            gfix = ensure_windows_gpu_prefs_for_mumu()
            gfix.extend(reassert_all_vm_gpu_accel(vms))
            if gfix:
                fixes.extend(gfix[:6])
            stamp.write_text(_utc() + "\n", encoding="utf-8")
    except Exception as exc:
        fixes.append(f"gpu_reassert_err:{exc}")
    # Hot-reload farm when agent drops FARM_RELOAD_FARM.flag (picks up seq fixes).
    fixes.extend(ensure_farm_reload_if_flagged())
    # Fix broken sequences as FAILs land (patch JSON / quarantine / wait bumps).
    # Fix broken sequences as FAILs land (patch JSON / quarantine / wait bumps).
    try:
        global _FAIL_REVIEW_MOD
        if _FAIL_REVIEW_MOD is None:
            fr_path = ROOT / "scripts" / "farm_fail_review.py"
            spec = importlib.util.spec_from_file_location("farm_fail_review_live", fr_path)
            if spec is None or spec.loader is None:
                raise RuntimeError("fail_review spec missing")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _FAIL_REVIEW_MOD = mod
        fail_review = _FAIL_REVIEW_MOD
        fr_state = fail_review.load_state()
        rows = fail_review.tail_new_rows(fr_state)
        n_fail = 0
        for row in rows:
            if row.get("success"):
                continue
            n_fail += 1
            fail_review.review_row(row, fr_state)
        fail_review.save_state(fr_state)
        if n_fail:
            fixes.append(f"fail_review_fixed={n_fail}")
        else:
            fixes.append("fail_review_tick")
    except Exception as exc:
        fixes.append(f"fail_review_err:{exc}")
    # Keep bottom-ads watcher alive (dash "2/4 paint" confusion + ad truth).
    try:
        pause_ads = LOG / "PAUSE_BOTTOM_ADS_WATCH.flag"
        if pause_ads.is_file():
            fixes.append("watch_bottom_ads_paused")
        else:
            from automation.farm_money_monitor import ensure_watch_bottom_ads

            fixes.extend(ensure_watch_bottom_ads()[:3])
    except Exception as exc:
        fixes.append(f"ads_watch_ensure_err:{exc}")
    # PREVENT: rewrite sticky every tick so ensure/adaptive cannot reintroduce dead serials.
    fixes.extend(_lock_money_sticky())
    fixes.extend(cull_adb_shells())
    online = adb_online()
    fixes.extend(reconnect_missing(online))
    online = adb_online()

    # COORDINATE: every money phone on its exact inject port (no 8220-on-vm5 fights).
    phone_rows, coord_fixes = coordinate_phones(online)
    fixes.extend(coord_fixes)

    # HARD RULE: concurrent phones must NEVER share the same public exit IP.
    try:
        from automation.exit_ip_guard import enforce_farm_unique_exit_ips
        from automation.tor_manager import TorManager

        ip_rows = [
            (
                r["name"],
                r["serial"],
                int(r["name"].split(".")[0][2:]),
            )
            for r in phone_rows
            if r.get("state") == "device" and r.get("serial")
        ]
        if ip_rows:
            tor = TorManager()
            fixes.extend(enforce_farm_unique_exit_ips(tor, tor.adb, ip_rows)[:16])
    except Exception as exc:
        fixes.append(f"exit_ip_guard_err:{exc}")

    n_expect = canonical_expect_phones()
    chrom_before = sum(1 for r in phone_rows if _is_true_chromium(r.get("top") or ""))
    need_more_chromium = chrom_before < max(1, n_expect - 1)

    # Farm owns taps while sequences run — remediator must not am_start/age_gate mid-seq.
    prog = load_json(PROGRESS)
    actives = prog.get("active") or prog.get("active_sequences") or []
    if isinstance(actives, dict):
        actives = list(actives.keys())
    n_actives = len(actives) if isinstance(actives, list) else 0
    allow_ui_rearm = n_actives == 0

    # FIX: CA (at most one phone/cycle — install_ca can block minutes) + Chromium FG.
    ca_done = False
    for r in phone_rows:
        if r.get("state") != "device":
            continue
        name, serial, proxy = r["name"], r["serial"], r["want"]
        if (not ca_done) and _ca_due(serial):
            fixes.append(_ensure_ca(serial))
            _mark_ca(serial)
            ca_done = True
        f = revive_phone(
            name,
            serial,
            proxy,
            need_more_chromium=need_more_chromium,
            top=r.get("top"),
            allow_ui_rearm=allow_ui_rearm,
        )
        fixes.extend(f)
        if f:
            r["top"] = (top_pkg(serial) or "")[:100]
            r["proxy"] = get_proxy(serial)
            r["proxy_ok"] = not inject_pin_needed(r["proxy"], proxy, r.get("top"))

    # Operator monitor truth (OK/FAIL/patches/pause) — one JSON for dash/agents.
    try:
        spec = importlib.util.spec_from_file_location(
            "farm_operator_monitor_live", ROOT / "scripts" / "farm_operator_monitor.py"
        )
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.write_truth()
            fixes.append("operator_truth")
    except Exception as exc:
        fixes.append(f"operator_truth_err:{exc}")

    inject_ok = inject_listen_ok(list(PHONES))
    if not inject_ok:
        fixes.append("inject_listen_low")
        try:
            from automation.farm_money_monitor import repin_all_inject, soft_restart_inject_if_needed

            fixes.extend(soft_restart_inject_if_needed()[:6])
            if not inject_listen_ok(list(PHONES)):
                fixes.extend(repin_all_inject()[:12])
        except Exception as exc:
            fixes.append(f"inject_restart_err:{exc}")

    ads = load_json(ADS_WATCH)

    # Mantis pull — rare. Failed pulls used to spawn headed Chromium to the
    # Mantis website then die, looking like the dash shut down. Cookie/headless
    # only; backoff hard so remediator does not reopen browsers every 2 minutes.
    stamp = LOG / "_last_mantis_pull_ts.txt"
    do_pull = True
    try:
        if stamp.exists() and (time.time() - stamp.stat().st_mtime) < 1800:
            do_pull = False
    except OSError:
        pass
    if do_pull:
        os.environ["CPHARM_MANTIS_ALLOW_HEADED"] = "0"
        pull_mantis_soft()
        stamp.write_text(_utc(), encoding="utf-8")
        fixes.append("mantis_pull")

    mantis = load_json(MANTIS)
    ssp: dict = {"paying": "?", "house": "?"}
    need_ssp = True
    try:
        from automation.farm_money_monitor import evaluate, start_background

        start_background()
        st = evaluate(do_fix=True)
        ssp = st.get("ssp") or ssp
        fixes.extend((st.get("auto_fixes") or [])[:8])
        if st.get("flat"):
            FLAT_FLAG.write_text(_utc(), encoding="utf-8")
            need_ssp = True
        else:
            if FLAT_FLAG.exists():
                FLAT_FLAG.unlink(missing_ok=True)
    except Exception as exc:
        fixes.append(f"money_mon_err:{exc}")
        need_ssp = True

    if need_ssp:
        ssp = ssp_probe()
        fixes.append(f"ssp_probe paying={ssp.get('paying')} house={ssp.get('house')}")

    # Re-load mantis after pull / money_mon.
    mantis = load_json(MANTIS)
    profit = calc_profit(mantis, ssp=ssp if isinstance(ssp, dict) else {})
    try:
        PROFIT_JSON.write_text(json.dumps(profit, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass

    chromium_fg = sum(1 for r in phone_rows if _is_true_chromium(r.get("top") or ""))
    inject_pinned = sum(1 for r in phone_rows if r.get("proxy_ok"))
    lawnchair = sum(1 for r in phone_rows if "lawnchair" in (r.get("top") or "").lower())
    offline = sum(1 for r in phone_rows if r.get("state") == "OFFLINE")

    state = {
        "ts": _utc(),
        "adb_online": sum(
            1
            for r in phone_rows
            if r.get("state") == "device"
            and not is_banned_serial(str(r.get("serial") or ""))
        ),
        "adb_expect": n_expect,
        "offline": offline,
        "actives": len(actives) if isinstance(actives, list) else 0,
        "chromium_fg": chromium_fg,
        "lawnchair": lawnchair,
        "inject_pinned": inject_pinned,
        "inject_listen": inject_ok,
        "bottom_ads": ads.get("bottom_ads_visible"),
        "profit": profit,
        "payout_usd": profit["payout_usd"],
        "ecpm": profit["ecpm"],
        "impressions": profit["impressions"],
        "ssp": ssp,
        "phones": phone_rows,
        "fixes": fixes,
    }

    # AUTHORITATIVE honest — remediator owns this file (watchers must not fight it).
    lines = [
        f"FARM_HONEST_NOW {_utc()}  [remediator]",
        f"DASH {'UP' if _dash_port_ok() else 'DOWN'} {DASH_URL}/",
        f"ADB phones {state['adb_online']}/{n_expect} offline={offline} | actives={state['actives']} "
        f"| chromium_fg={chromium_fg} | lawn={lawnchair}",
        f"inject_pinned={inject_pinned}/{n_expect} listen={inject_ok} | bottom_ads={ads.get('bottom_ads_visible')}",
        (
            f"PROFIT ${profit['payout_usd']:.2f}  eCPM=${profit['ecpm']:.2f}  "
            f"impr={profit['impressions']} clk={profit['clicks']} CTR={profit['ctr_pct']:.2f}%  "
            f"tone={profit['tone']}"
        ),
        (
            f"PACE ${profit['usd_per_hour']:.2f}/hr → proj_eod ${profit['proj_eod_usd']:.2f}  "
            f"| gap floor ${profit['gap_floor_usd']:.2f} strong ${profit['gap_strong_usd']:.2f} "
            f"stretch ${profit['gap_stretch_usd']:.2f}  "
            f"| need ${profit['need_usd_per_hour_for_floor']:.2f}/hr for $40"
        ),
        f"TARGETS floor=${TARGET_FLOOR_USD:.0f} strong=${TARGET_STRONG_USD:.0f} "
        f"stretch=${TARGET_STRETCH_USD:.0f} | SSP paying={ssp.get('paying')} house={ssp.get('house')}",
        "PHONES (adaptive):",
    ]
    for r in phone_rows:
        ok = "OK" if r.get("proxy_ok") else "BAD_PROXY"
        lines.append(
            f"  {r['name']} {r['serial']} {ok} proxy={r.get('proxy')} want={r.get('want')} "
            f"top={r.get('top')}"
        )
    lines.append("FIXES:")
    if fixes:
        for f in fixes[:50]:
            lines.append(f"  - {f}")
    else:
        lines.append("  - (none)")
    HONEST.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Catch the breaks we previously missed (dash 2-phone lie, ipv dilution, SSP house-only…)
    try:
        mon = health_audit(profit=profit, ssp=ssp if isinstance(ssp, dict) else {}, state=state)
        if mon:
            fixes.extend(mon[:12])
            state["monitor"] = mon
            lines.append("MONITOR:")
            for m in mon[:12]:
                lines.append(f"  ! {m}")
            HONEST.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as exc:
        fixes.append(f"monitor_audit_err:{exc}")
    try:
        with TICK_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(state, default=str) + "\n")
    except OSError:
        pass
    print(
        f"[remediate] ADB={state['adb_online']}/{n_expect} actives={state['actives']} chrom={chromium_fg} "
        f"pin={inject_pinned}/{n_expect} ${profit['payout_usd']:.2f} pace=${profit['usd_per_hour']:.2f}/hr "
        f"tone={profit['tone']} paying={ssp.get('paying')} fixes={len(fixes)}",
        flush=True,
    )
    return state


def main() -> int:
    LOG.mkdir(parents=True, exist_ok=True)
    crash_log = LOG / "farm_remediate_loop.stderr.log"
    print(f"farm_remediate_loop start interval={INTERVAL_S}s (FIX+PROFIT+COORD adaptive)", flush=True)
    while True:
        t0 = time.time()
        try:
            st = cycle()
            # Faster loop when phones are broken / behind floor.
            profit = (st or {}).get("profit") or {}
            expect = max(1, int((st or {}).get("adb_expect") or len(PHONES) or 1))
            broken = (
                int((st or {}).get("inject_pinned") or 0) < max(1, expect - 1)
                or int((st or {}).get("chromium_fg") or 0) < max(1, expect - 1)
                or int((st or {}).get("offline") or 0) > 0
                or str(profit.get("tone") or "") == "behind"
            )
            sleep_for = 35.0 if broken else INTERVAL_S
        except Exception as exc:
            tb = traceback.format_exc()
            msg = f"FARM_HONEST_NOW {_utc()}\nLOOP_ERROR {exc}\n"
            try:
                HONEST.write_text(msg, encoding="utf-8")
            except OSError:
                pass
            try:
                with crash_log.open("a", encoding="utf-8") as fh:
                    fh.write(f"\n{_utc()} LOOP_ERROR\n{tb}\n")
            except OSError:
                pass
            print(f"[remediate] ERROR {exc}", flush=True)
            sleep_for = 20.0
        elapsed = time.time() - t0
        time.sleep(max(5.0, sleep_for - elapsed))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        try:
            with (LOG / "farm_remediate_loop.stderr.log").open("a", encoding="utf-8") as fh:
                fh.write(f"\n{_utc()} FATAL\n{traceback.format_exc()}\n")
        except OSError:
            pass
        raise
