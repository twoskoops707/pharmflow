"""CPharm/dash self-monitor: money-health + flat-$ detection + auto-remediation.

ALERTS on junk eCPM, house-only SSP, impression dilution, and flat $ — not only
when payout has been unchanged for 25 minutes. last_ok / money_ok require paying
fill + non-junk eCPM (bottom-ads visible alone is NOT health).

Safe remediations: re-pin inject, SSP refresh, heat_down on house/dilution,
ensure bottom-ads watcher, cull hung adb / dup hunters. Does NOT start
ensure_farm / farm_354 dual-run.

State files under C:\\CPharm\\logs\\:
  farm_money_monitor_state.json
  farm_money_history.jsonl
  FARM_MONEY_HEALTH.json
  FARM_FLAT_DOLLAR.flag   (present while money alert active)
  SSP_FORCE_REFRESH.flag  (consumed by dabflow_mantis_client_patch)
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import automation.no_window  # noqa: E402,F401  — hide adb consoles
from automation import dabflow_mantis_client_patch as ssp_mod  # noqa: E402
from automation.farm_health_audit import apply_money_rails, behind_on_path3_clicks  # noqa: E402

LOG = Path(r"C:\CPharm\logs")
STATE = LOG / "farm_money_monitor_state.json"
HISTORY = LOG / "farm_money_history.jsonl"
FLAT_FLAG = LOG / "FARM_FLAT_DOLLAR.flag"
SSP_FLAG = LOG / "SSP_FORCE_REFRESH.flag"
PROGRESS = LOG / "farm_354_progress.json"
ADS_WATCH = LOG / "ads_watch_state.json"
MANTIS = LOG / "mantis_today_state.json"
HONEST = LOG / "FARM_HONEST_NOW.txt"

_ADB = str(Path(r"C:\CPharm\bundled\adb.exe"))
if not Path(_ADB).is_file():
    _ADB = "adb"

# Serial → inject port via MuMu VM index (8218+idx). Fallback if discover empty.
FALLBACK_PHONE_PORTS: tuple[tuple[str, int, str], ...] = (
    ("10.0.2.222:5555", 8218, "vm0"),
    ("10.0.2.171:5555", 8219, "vm1"),
    ("10.0.2.27:5555", 8220, "vm2"),
    ("10.0.2.156:5555", 8221, "vm3"),
    ("10.0.2.115:5555", 8223, "vm5"),
    ("10.0.2.75:5555", 8224, "vm6"),
    ("10.0.2.184:5555", 8225, "vm7"),
    ("10.0.2.179:5555", 8226, "vm8"),
    ("10.0.2.124:5555", 8227, "vm9"),
)
PHONE_PORTS = FALLBACK_PHONE_PORTS
_INJECT_LO = 8218
_INJECT_HI = 8231
_INJECT_SPAN = "14"

DEFAULT_FLAT_MIN = 25.0  # minutes of flat $ while actives>0 → alert
DEFAULT_TICK_S = 90.0
_MIN_DELTA_USD = 0.15  # treat sub-$0.15 moves as still-flat (noise / rounding)

log = logging.getLogger("farm_money_monitor")

_thread: threading.Thread | None = None
_stop = threading.Event()
_lock = threading.Lock()


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _port_ok(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def live_phone_ports() -> list[tuple[str, int, str]]:
    """Canonical 8 money phones — inject port per vm index."""
    try:
        from automation.farm_canonical_phones import canonical_workset

        rows = canonical_workset()
    except Exception:
        rows = []
    out: list[tuple[str, int, str]] = []
    for name, serial, proxy in rows:
        try:
            port = int(str(proxy).rsplit(":", 1)[-1])
        except (TypeError, ValueError):
            continue
        out.append((serial, port, name))
    return out


def _adb(serial: str, *args: str, timeout: float = 10.0) -> str:
    try:
        p = subprocess.run(
            [_ADB, "-s", serial, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0),
        )
        return (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"ERR:{exc}"


def _active_count() -> int:
    try:
        raw = json.loads(PROGRESS.read_text(encoding="utf-8"))
        keys = raw.get("active_keys") or raw.get("active_sequences") or []
        return len(keys)
    except (OSError, ValueError, TypeError):
        return -1


def _load_mantis() -> dict[str, Any]:
    try:
        return json.loads(MANTIS.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def pull_mantis() -> dict[str, Any]:
    """Best-effort live pull via dash; fall back to on-disk state."""
    try:
        import urllib.request

        req = urllib.request.Request(
            "http://127.0.0.1:8091/api/mantis_pull",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            body = json.loads(r.read())
        t = body.get("mantis_today") or body
        if isinstance(t, dict) and t.get("payout_usd") is not None:
            return t
    except Exception as exc:
        log.debug("mantis pull soft-fail: %s", exc)
    return _load_mantis()


def _append_history(row: dict[str, Any]) -> None:
    try:
        LOG.mkdir(parents=True, exist_ok=True)
        with HISTORY.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
    except OSError:
        pass


def _read_history_tail(n: int = 40) -> list[dict[str, Any]]:
    if not HISTORY.is_file():
        return []
    try:
        lines = HISTORY.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def probe_ssp() -> dict[str, Any]:
    """Host-side SSP snapshot (paying vs house)."""
    try:
        from automation import dabflow_mantis_client_patch as ssp

        ssp.clear_ssp_cache()
        ads = ssp.prefetch_ssp_ads(force=True) or []
        paying = int(ssp.ssp_ads_paying_count(ads))
        house = max(0, len(ads) - paying)
        zones = sorted(ssp.ssp_paying_zone_ids(force_refresh=False))
        return {
            "count": len(ads),
            "paying": paying,
            "house": house,
            "paying_zones": zones,
            "has_paying_fill": paying > 0,
            "ts": _utc(),
        }
    except Exception as exc:
        return {"error": str(exc), "paying": -1, "house": -1, "ts": _utc()}


def cull_hung_adb(*, max_kill: int = 24, min_age_s: float = 60.0) -> list[str]:
    """Kill hung adb shell/uiautomator clients (not the server).

    Provably-stale clients are killed regardless of age:
      - orphaned clients (parent python is gone — nothing will read their output)
      - duplicate fork-servers (only one server may own port 5037)
    The rest need age >= min_age_s — farm tap dumps sometimes run 20–60s under
    a wedged guest; killing healthy shells mid-sequence causes mass tap FAILs.
    The wrapper now kills its own child on timeout, so a surviving young shell
    client is a live sequence command, not a leaked zombie.
    """
    fixes: list[str] = []
    try:
        import psutil
    except ImportError:
        return fixes
    killed = 0
    now = time.time()
    for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time", "ppid"]):
        if killed >= max_kill:
            break
        try:
            name = (proc.info.get("name") or "").lower()
            if name != "adb.exe":
                continue
            cmd = " ".join(proc.info.get("cmdline") or [])
            if "fork-server" in cmd:
                continue  # governed by the watchdog's duplicate-server rule
            if not (" shell" in cmd or "uiautomator" in cmd or "dumpsys" in cmd):
                continue
            age = now - float(proc.info.get("create_time") or now)
            ppid = int(proc.info.get("ppid") or -1)
            orphan = False
            if ppid > 0:
                try:
                    orphan = not psutil.pid_exists(ppid)
                except psutil.Error:
                    orphan = False
            if not orphan and age < float(min_age_s):
                continue
            proc.kill()
            fixes.append(
                f"kill_adb_shell pid={proc.info.get('pid')} age={age:.0f}s "
                f"orphan={orphan}"
            )
            killed += 1
        except (psutil.Error, OSError):
            continue
    return fixes


def ensure_watch_bottom_ads() -> list[str]:
    fixes: list[str] = []
    pause = LOG / "PAUSE_BOTTOM_ADS_WATCH.flag"
    if pause.is_file():
        return ["watch_bottom_ads_paused"]
    try:
        import psutil

        for proc in psutil.process_iter(["pid", "cmdline"]):
            cmd = " ".join(proc.info.get("cmdline") or [])
            if "watch_bottom_ads" in cmd:
                return [f"watch_bottom_ads_ok pid={proc.info.get('pid')}"]
    except Exception:
        pass
    try:
        from automation.runtime_paths import helper_python as _hp

        pyw = Path(_hp() or sys.executable)
    except Exception:
        pyw = Path(sys.executable)
    script = ROOT / "scripts" / "watch_bottom_ads.py"
    if not script.is_file():
        return ["watch_bottom_ads_missing"]
    try:
        subprocess.Popen(
            [str(pyw if pyw.is_file() else sys.executable), "-u", str(script), "loop", "--loop", "120"],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0),
        )
        fixes.append("started_watch_bottom_ads loop=120")
    except OSError as exc:
        fixes.append(f"watch_start_fail:{exc}")
    return fixes


def soft_restart_inject_if_needed() -> list[str]:
    phones = live_phone_ports()
    ports = [p for _, p, _ in phones]
    if ports and all(_port_ok(p) for p in ports):
        return ["inject_listen_ok"]
    fixes = ["inject_ports_down → soft_restart"]
    try:
        import psutil

        for proc in psutil.process_iter(["pid", "cmdline"]):
            cmd = " ".join(proc.info.get("cmdline") or [])
            if "run_mantis_inject" in cmd:
                try:
                    proc.kill()
                    fixes.append(f"killed_inject pid={proc.info.get('pid')}")
                except (psutil.Error, OSError):
                    pass
    except Exception:
        pass
    time.sleep(1.0)
    try:
        from automation.runtime_paths import helper_python as _hp

        pyw = Path(_hp() or sys.executable)
    except Exception:
        pyw = Path(sys.executable)
    script = ROOT / "scripts" / "run_mantis_inject_proxies.py"
    try:
        subprocess.Popen(
            # --phones N = indices 0..N-1. vm10 uses index 10 → :8228.
            [str(pyw if pyw.is_file() else sys.executable), "-u", str(script), "--phones", _INJECT_SPAN],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0),
        )
        time.sleep(3.5)
        ok = all(_port_ok(p) for p in ports) if ports else False
        fixes.append(f"inject_restarted listen_ok={ok}")
    except OSError as exc:
        fixes.append(f"inject_restart_fail:{exc}")
    return fixes


def repin_all_inject() -> list[str]:
    """adb reverse inject port (+tor) then pin http_proxy. Tor-only reverse caused ERR_PROXY."""
    fixes: list[str] = []
    for serial, port, name in live_phone_ports():
        if not serial or not serial.startswith("10.0.2."):
            fixes.append(f"skip_repin {name} offline")
            continue
        try:
            from automation.farm_canonical_phones import is_banned_serial

            if is_banned_serial(serial):
                fixes.append(f"skip_repin {name} banned_serial={serial}")
                continue
        except Exception:
            pass
        tor = 8118 + (port - 8218)
        cur = _adb(serial, "shell", "settings", "get", "global", "http_proxy", timeout=5.0).strip()
        cur_port = None
        mcur = re.search(r"127\.0\.0\.1:(\d+)", cur or "")
        if mcur:
            cur_port = int(mcur.group(1))
        listing = _adb(serial, "reverse", "--list", timeout=6.0)
        keep = {port}
        if cur_port and _INJECT_LO <= cur_port <= _INJECT_HI:
            keep.add(cur_port)
        for m in re.finditer(r"tcp:(\d+)\s+tcp:\d+", listing or ""):
            g = int(m.group(1))
            if _INJECT_LO <= g <= _INJECT_HI and g not in keep:
                _adb(serial, "reverse", "--remove", f"tcp:{g}", timeout=5.0)
        _adb(serial, "reverse", f"tcp:{port}", f"tcp:{port}", timeout=8.0)
        _adb(serial, "reverse", f"tcp:{tor}", f"tcp:{tor}", timeout=6.0)
        if cur_port and cur_port != port and _INJECT_LO <= cur_port <= _INJECT_HI:
            _adb(serial, "reverse", f"tcp:{cur_port}", f"tcp:{cur_port}", timeout=6.0)
        want = f"127.0.0.1:{port}"
        _adb(serial, "shell", "settings", "put", "global", "http_proxy", want, timeout=6.0)
        time.sleep(0.15)
        _adb(serial, "shell", "settings", "put", "global", "http_proxy", want, timeout=6.0)
        got = _adb(serial, "shell", "settings", "get", "global", "http_proxy", timeout=6.0).strip()
        listing2 = _adb(serial, "reverse", "--list", timeout=6.0)
        rev_ok = f"tcp:{port}" in (listing2 or "")
        fixes.append(f"repin {name} {serial}->{want} got={got} reverse_ok={rev_ok}")
    return fixes


def nudge_chromium_dabflow() -> list[str]:
    fixes: list[str] = []
    for serial, port, name in live_phone_ports():
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
            "org.chromium.chrome/com.google.android.apps.chrome.Main",
            timeout=8.0,
        )
        fixes.append(f"am_start_dabflow {name} port={port} {out[:60].strip()}")
        time.sleep(0.25)
    return fixes


def write_ssp_force_refresh(ssp: dict[str, Any] | None = None) -> list[str]:
    payload = ssp or probe_ssp()
    try:
        SSP_FLAG.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (LOG / "_live_ssp_probe.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return [f"ssp_force_refresh paying={payload.get('paying')} house={payload.get('house')}"]
    except OSError as exc:
        return [f"ssp_flag_fail:{exc}"]


def _fresh_paying_fill_count() -> int:
    """Paying ads in ssp_paying_fill.json if hunter/prefetch just wrote them."""
    try:
        if not ssp_mod.paying_fill_file_fresh():
            return 0
        ads = ssp_mod._ingest_paying_fill_file() or []
        return int(ssp_mod.ssp_ads_paying_count(ads))
    except Exception:
        return 0


def remediate_flat(
    *,
    reason: str,
    actives: int = -1,
    clicks: int | None = None,
    payout_usd: float | None = None,
) -> list[str]:
    """Safe auto-fixes when $ is flat or money-health is bad. Never starts farm_354/ensure."""
    fixes: list[str] = [f"flat_reason={reason}"]
    fixes.extend(cull_hung_adb())
    fixes.extend(soft_restart_inject_if_needed())
    fixes.extend(repin_all_inject())
    ssp = probe_ssp()
    fixes.extend(write_ssp_force_refresh(ssp))
    paying = int(ssp.get("paying") or 0)
    if paying == 0:
        try:
            ads = ssp_mod.prefetch_ssp_ads_prefer_paying(
                attempts=14, delay_s=0.4, allow_house_fallback=False
            )
            paying = ssp_mod.ssp_ads_paying_count(ads or [])
            fixes.append(f"prefer_paying_burst paying={paying} n={len(ads or [])}")
            if paying == 0:
                fill_n = _fresh_paying_fill_count()
                if fill_n > 0:
                    paying = fill_n
                    fixes.append(f"keep_fresh_paying_fill paying={fill_n}")
                else:
                    ssp_mod.clear_ssp_paying_fill_file(reason="money_mon_house_only")
                    fixes.append("cleared_stale_paying_fill")
        except Exception as exc:
            fixes.append(f"prefer_paying_burst_fail:{exc}")
    zero_click = int(clicks or 0) < 3 and float(payout_usd or 0) < 0.50
    # Match farm_health_audit.behind_on_path3_clicks — do not treat mid-day
    # $12 / 24 clicks as "caught up" and heat-down Path3 volume.
    catching_up = (
        zero_click
        or behind_on_path3_clicks(clicks, payout_usd)
        or float(payout_usd or 0) < 15.0
    )
    # Clicks 0 + ~$0 is UTC-morning / house flip, not impression dilution.
    # Do not serialize Path3 or cut seqs to 10 while UTC day is still catching up.
    rails_mode = "hold" if (paying > 0 or catching_up) else "heat_down"
    rails_reason = (
        "flat_with_paying"
        if paying > 0
        else ("zero_click_hold" if catching_up else "flat_or_house")
    )
    try:
        fixes.extend(
            f"money_mon_{x}"
            for x in apply_money_rails(
                mode=rails_mode,
                reason=rails_reason,
                clicks=clicks,
                payout_usd=payout_usd,
            )
        )
    except Exception as exc:
        fixes.append(f"money_mon_rails_err:{exc}")
    if int(actives) == 0:
        fixes.extend(nudge_chromium_dabflow())
    else:
        fixes.append(f"skip_nudge_dabflow actives={actives}")
    fixes.extend(ensure_watch_bottom_ads())
    fixes.extend(_cull_duplicate_hunters())
    return fixes


def hunter_heartbeat_stale(
    mtime: float | None,
    now: float,
    *,
    max_age_s: float = 180.0,
) -> bool:
    """True when hunter heartbeat is missing or older than max_age_s."""
    if mtime is None:
        return True
    try:
        return (float(now) - float(mtime)) > float(max_age_s)
    except (TypeError, ValueError):
        return True


def _hunter_hb_mtime() -> float | None:
    hb = LOG / "ssp_paying_hunter_heartbeat.txt"
    try:
        if hb.is_file():
            return float(hb.stat().st_mtime)
    except OSError:
        return None
    return None


def _spawn_paying_hunter() -> int | None:
    script = ROOT / "scripts" / "ssp_paying_hunter.py"
    if not script.is_file() or psutil is None:
        return None
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    if not Path(pyw).is_file():
        pyw = sys.executable
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    flags = 0x08000000
    proc = subprocess.Popen(
        [pyw, "-u", str(script)],
        cwd=str(ROOT),
        env=env,
        creationflags=flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return int(proc.pid)


def _cull_duplicate_hunters() -> list[str]:
    """Keep exactly one live hunter. Respawn if heartbeat is stale (hung prefetch)."""
    fixes: list[str] = []
    if psutil is None:
        return fixes
    pids: list[int] = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            argv = proc.info.get("cmdline") or []
            if "-c" in argv:
                continue
            cmd = " ".join(str(x) for x in argv)
            if "ssp_paying_hunter.py" in cmd:
                pids.append(int(proc.info["pid"]))
        except (psutil.Error, OSError, TypeError, ValueError):
            continue
    stale = hunter_heartbeat_stale(_hunter_hb_mtime(), time.time())
    if len(pids) > 1:
        for pid in sorted(pids)[:-1]:
            try:
                psutil.Process(pid).kill()
                fixes.append(f"kill_dup_hunter pid={pid}")
            except (psutil.Error, OSError):
                pass
        pids = [sorted(pids)[-1]]
    if pids and stale:
        pid = pids[0]
        try:
            psutil.Process(pid).kill()
            fixes.append(f"kill_stale_hunter pid={pid}")
        except (psutil.Error, OSError):
            pass
        pids = []
    if not pids:
        spawned = _spawn_paying_hunter()
        if spawned:
            fixes.append(f"spawn_paying_hunter pid={spawned}")
    return fixes


def _money_health_problems(
    *,
    payout: float,
    ecpm: float,
    impr: int,
    actives: int,
    ssp: dict[str, Any],
    flat: bool,
    flat_minutes: float,
) -> list[str]:
    """Conditions that mean money monitoring must ALERT — not 'last_ok'."""
    problems: list[str] = []
    try:
        paying = int(ssp["paying"]) if "paying" in ssp and ssp["paying"] is not None else -1
    except (TypeError, ValueError):
        paying = -1
    try:
        house = int(ssp["house"]) if "house" in ssp and ssp["house"] is not None else -1
    except (TypeError, ValueError):
        house = -1
    if flat:
        problems.append(f"FLAT_DOLLAR {flat_minutes:.0f}m ${payout:.2f}")
    if actives > 0 and paying == 0 and house > 0:
        problems.append(f"SSP_HOUSE_ONLY paying=0 house={house}")
    if impr >= 12000 and ecpm < 0.50:
        problems.append(f"IMPR_DILUTION impr={impr} ecpm=${ecpm:.2f}")
    if payout < 15.0 and ecpm < 0.75 and impr >= 8000:
        problems.append(f"MONEY_JUNK_RATE ${payout:.2f} ecpm=${ecpm:.2f}")
    if actives > 0 and payout < 5.0 and impr >= 20000:
        problems.append(f"BURNING_IMPR_NO_PAY ${payout:.2f} impr={impr}")
    return problems


def evaluate(*, flat_min: float = DEFAULT_FLAT_MIN, do_fix: bool = True) -> dict[str, Any]:
    """One monitor tick. Returns state dict (also written to disk)."""
    mantis = pull_mantis()
    payout = float(mantis.get("payout_usd") or 0)
    ecpm = float(mantis.get("ecpm") or 0)
    impr = int(mantis.get("impressions") or 0)
    actives = _active_count()
    ads: dict[str, Any] = {}
    try:
        ads = json.loads(ADS_WATCH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        pass

    now = time.time()
    row = {
        "ts": _utc(),
        "epoch": now,
        "payout_usd": payout,
        "ecpm": ecpm,
        "impressions": impr,
        "actives": actives,
        "bottom_ads_visible": bool(ads.get("bottom_ads_visible")),
        "chromium_fg": ads.get("chromium_fg"),
    }
    _append_history(row)

    hist = _read_history_tail(60)
    flat = False
    flat_minutes = 0.0
    first_same: dict[str, Any] | None = None
    for h in reversed(hist):
        try:
            hp = float(h.get("payout_usd") or 0)
        except (TypeError, ValueError):
            continue
        if abs(hp - payout) <= _MIN_DELTA_USD:
            first_same = h
            continue
        break
    # Bad eCPM / junk inventory: don't wait 25m to notice flat $.
    effective_flat_min = float(flat_min)
    if ecpm < 0.50 and impr >= 10000:
        effective_flat_min = min(effective_flat_min, 12.0)
    if first_same and actives > 0:
        try:
            flat_minutes = max(0.0, (now - float(first_same.get("epoch") or now)) / 60.0)
        except (TypeError, ValueError):
            flat_minutes = 0.0
        flat = flat_minutes >= effective_flat_min

    impr_delta = 0
    if len(hist) >= 2:
        try:
            impr_delta = impr - int(hist[0].get("impressions") or impr)
        except (TypeError, ValueError):
            impr_delta = 0

    # Always probe SSP for health — remediations stay behind do_fix.
    ssp = probe_ssp()
    problems = _money_health_problems(
        payout=payout,
        ecpm=ecpm,
        impr=impr,
        actives=int(actives) if actives is not None else 0,
        ssp=ssp if isinstance(ssp, dict) else {},
        flat=flat,
        flat_minutes=flat_minutes,
    )
    fixes: list[str] = []
    alert = bool(problems)
    if alert and do_fix:
        try:
            clicks_n = int(mantis.get("clicks") or mantis.get("click_count") or 0)
        except (TypeError, ValueError):
            clicks_n = 0
        fixes = remediate_flat(
            reason=";".join(problems)
            + f" actives={actives} ads_visible={ads.get('bottom_ads_visible')}",
            actives=int(actives) if actives is not None else -1,
            clicks=clicks_n,
            payout_usd=payout,
        )

    if alert:
        try:
            FLAT_FLAG.write_text(
                f"MONEY_ALERT ts={_utc()} payout={payout} ecpm={ecpm} "
                f"problems={problems} actives={actives} "
                f"paying={ssp.get('paying')} house={ssp.get('house')}\n",
                encoding="utf-8",
            )
        except OSError:
            pass
    elif FLAT_FLAG.is_file():
        try:
            FLAT_FLAG.unlink()
        except OSError:
            pass

    money_ok = (
        not alert
        and payout > 0
        and ecpm >= 0.50
        and int(ssp.get("paying") or 0) > 0
    )
    state = {
        "ts": _utc(),
        "payout_usd": payout,
        "ecpm": ecpm,
        "impressions": impr,
        "impr_delta_window": impr_delta,
        "actives": actives,
        "flat": flat,
        "flat_minutes": round(flat_minutes, 1),
        "flat_threshold_min": effective_flat_min,
        "alert": alert,
        "money_ok": money_ok,
        "problems": problems,
        "ssp": ssp,
        "ads_watch": {
            "bottom_ads_visible": ads.get("bottom_ads_visible"),
            "chromium_ok": ads.get("bottom_ads_chromium_ok"),
            "chromium_total": ads.get("bottom_ads_chromium_total"),
            "chromium_fg": ads.get("chromium_fg"),
            "missing": ads.get("bottom_ads_missing"),
            "note": "visible!=paying — house creatives can paint and still pay $0",
        },
        "inject_listen": all(_port_ok(p) for _, p, _ in live_phone_ports()),
        "auto_fixes": fixes[-30:],
        "last_ok": _utc() if money_ok else None,
    }
    if state["last_ok"] is None and STATE.is_file():
        try:
            prev = json.loads(STATE.read_text(encoding="utf-8"))
            # Only keep a prior last_ok if that tick was actually money-healthy.
            if prev.get("money_ok") is True:
                state["last_ok"] = prev.get("last_ok")
        except (OSError, ValueError, TypeError):
            pass

    try:
        STATE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        (LOG / "FARM_MONEY_HEALTH.json").write_text(
            json.dumps(
                {
                    "ts": state["ts"],
                    "money_ok": money_ok,
                    "alert": alert,
                    "problems": problems,
                    "payout_usd": payout,
                    "ecpm": ecpm,
                    "impressions": impr,
                    "ssp": ssp,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass

    _patch_honest(state)
    return state


def _patch_honest(state: dict[str, Any]) -> None:
    """Append money-monitor lines into FARM_HONEST_NOW without wiping remediator body."""
    try:
        base = HONEST.read_text(encoding="utf-8") if HONEST.is_file() else ""
    except OSError:
        base = ""
    problems = state.get("problems") or []
    block = [
        "",
        "--- money_monitor ---",
        f"last_farming_ts: {state.get('ts')}",
        f"last_ok: {state.get('last_ok')}",
        f"money_ok: {state.get('money_ok')}",
        f"$NOW: ${state.get('payout_usd')} eCPM=${state.get('ecpm')} impr={state.get('impressions')}",
        f"flat: {state.get('flat')} ({state.get('flat_minutes')}m / thr={state.get('flat_threshold_min')}m)",
        f"actives: {state.get('actives')} inject={state.get('inject_listen')}",
        f"ssp: paying={((state.get('ssp') or {}).get('paying'))} "
        f"house={((state.get('ssp') or {}).get('house'))}",
        f"problems: {problems if problems else '(none)'}",
        f"ads: {state.get('ads_watch')}",
        f"alert: {state.get('alert')}",
    ]
    if state.get("auto_fixes"):
        block.append("auto_fixes:")
        for f in (state.get("auto_fixes") or [])[-12:]:
            block.append(f"  - {f}")
    marker = "--- money_monitor ---"
    if marker in base:
        base = base.split(marker)[0].rstrip()
    try:
        HONEST.write_text(base + "\n" + "\n".join(block) + "\n", encoding="utf-8")
    except OSError:
        pass


def _loop(flat_min: float, tick_s: float) -> None:
    log.info("farm_money_monitor started flat_min=%s tick=%ss", flat_min, tick_s)
    while not _stop.is_set():
        try:
            st = evaluate(flat_min=flat_min, do_fix=True)
            log.info(
                "money_mon $=%s flat=%s/%sm actives=%s paying=%s fixes=%d",
                st.get("payout_usd"),
                st.get("flat"),
                st.get("flat_minutes"),
                st.get("actives"),
                (st.get("ssp") or {}).get("paying"),
                len(st.get("auto_fixes") or []),
            )
        except Exception:
            log.exception("farm_money_monitor tick failed")
        _stop.wait(max(45.0, float(tick_s)))


def start_background(
    *,
    flat_min: float | None = None,
    tick_s: float | None = None,
) -> dict[str, Any]:
    """Idempotent daemon start (call from dash)."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return {"ok": True, "already": True, "pid_thread": _thread.name}
        _stop.clear()
        fm = float(flat_min if flat_min is not None else os.environ.get("CPHARM_FLAT_DOLLAR_MIN", DEFAULT_FLAT_MIN))
        ts = float(tick_s if tick_s is not None else os.environ.get("CPHARM_MONEY_MON_TICK_S", DEFAULT_TICK_S))
        _thread = threading.Thread(
            target=_loop,
            kwargs={"flat_min": fm, "tick_s": ts},
            name="farm-money-monitor",
            daemon=True,
        )
        _thread.start()
        return {"ok": True, "started": True, "flat_min": fm, "tick_s": ts}


def stop_background() -> None:
    _stop.set()


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"ok": False, "error": "no_state"}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(evaluate(do_fix=True), indent=2, default=str))
