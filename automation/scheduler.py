"""
PharmFlow Scheduler — daily hit quota per phone with random fire-times.
Per-phone: given hits_per_day, generates N fire-times spread randomly across 24h and executes the sequence.
"""
import asyncio
import datetime
import json
import logging
import os
import re
import random
import sys
import threading
import time as _time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))

import human_variation as hv
import tor_manager
from config import (
    SCHEDULE_SPREAD,
    SCHED_ACTIVE_HOUR_END,
    SCHED_ACTIVE_HOUR_START,
    SCHED_TOR_LOCAL,
)
from sequence_normalize import normalize_automation_steps

log = logging.getLogger("scheduler")

# Lazy import — importing ``dashboard`` at module load couples scheduler startup to the full
# dashboard stack; ``dashboard`` already lazy-imports this module in ``handle_scheduler``.
_dashboard_mod = None


def _dashboard():
    global _dashboard_mod
    if _dashboard_mod is None:
        import dashboard as _d

        _dashboard_mod = _d
    return _dashboard_mod

PHONE_SCHED = {}    # serial -> {"hits": N, "times": [epoch], "idx": N}
RUNNING = {}         # serial -> bool
_main_loop = None    # event loop captured from async context
_sched_lock = threading.Lock()


_SERIAL_RE = re.compile(r"^[A-Za-z0-9._:\-]+$")


def plan_scheduler_start(data: dict) -> dict:
    """Resolve a start payload into per-phone jobs. Does not start threads.

    Exit-country daytime leaves ``times`` empty. The worker places them after the
    phone's Tor exit country is known, and does not fall back to the host clock.
    """
    if not isinstance(data, dict):
        return {"error": "body must be an object"}
    serials = [str(s) for s in data.get("serials", []) if _SERIAL_RE.match(str(s))]
    try:
        hits = max(0, int(data.get("hits_per_day", 0)))
    except (TypeError, ValueError):
        return {"error": "hits_per_day must be an integer"}
    try:
        if "schedule_spread" in data:
            spread = _spread_name(data.get("schedule_spread"))
        else:
            spread = _spread_name(None)
    except ValueError as exc:
        return {"error": str(exc)}
    tor_local = bool(data["schedule_tor_local"]) if "schedule_tor_local" in data else bool(SCHED_TOR_LOCAL)
    default_steps = data.get("steps", [])
    if not isinstance(default_steps, list):
        return {"error": "steps must be a list"}
    steps_map = data.get("steps_per_serial") or {}
    if not isinstance(steps_map, dict):
        return {"error": "steps_per_serial must be an object"}
    hits_map = data.get("hits_per_serial") or {}
    if not isinstance(hits_map, dict):
        return {"error": "hits_per_serial must be an object"}
    jobs = []
    errors = []
    for serial in serials:
        phone_steps = steps_map.get(serial, default_steps)
        if not isinstance(phone_steps, list):
            errors.append(f"{serial}: steps are not a list")
            continue
        if serial in hits_map:
            try:
                phone_hits = max(0, int(hits_map[serial]))
            except (TypeError, ValueError):
                errors.append(f"{serial}: hits_per_day is not an integer")
                continue
        else:
            phone_hits = hits
        times = [] if tor_local else _gen_today(phone_hits, spread=spread)
        jobs.append({
            "serial": serial,
            "steps": list(phone_steps),
            "hits": phone_hits,
            "times": times,
            "spread": spread,
            "tor_local": tor_local,
        })
    return {"jobs": jobs, "errors": errors, "spread": spread, "tor_local": tor_local}


def _name(serial: str) -> str:
    try:
        return next(p["name"] for p in _dashboard().list_phones() if p["serial"] == serial)
    except StopIteration:
        return serial


def _spread_name(spread: str | None) -> str:
    if spread is None or str(spread).strip() == "":
        return SCHEDULE_SPREAD
    raw = str(spread).strip().lower()
    if raw in ("uniform", "classic", "flat"):
        return "uniform"
    if raw == "organic":
        return "organic"
    raise ValueError("schedule_spread must be organic or uniform")


def _hour_in_exit_daytime(hour: int, day_start: int, day_end: int) -> bool:
    if day_start <= day_end:
        return day_start <= hour <= day_end
    return hour >= day_start or hour <= day_end


def _exit_daytime_epochs(tz: ZoneInfo, day_start: int, day_end: int) -> list[float]:
    """Host-today seconds whose clock hour is daytime in the exit timezone."""
    midnight = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    epochs: list[float] = []
    for sec in range(86400):
        local = (midnight + datetime.timedelta(seconds=sec)).astimezone(tz)
        if _hour_in_exit_daytime(local.hour, day_start, day_end):
            epochs.append(midnight.timestamp() + sec)
    return epochs


def _pick_epochs(pool: list[float], hits: int, organic: bool) -> list[float]:
    if hits <= 0 or not pool:
        return []
    count = len(pool)
    if hits > count:
        extra = [random.choice(pool) for _ in range(hits - count)]
        return sorted(list(pool) + extra)
    if not organic or hits == 1:
        return sorted(random.sample(pool, hits))
    weights = [random.gammavariate(1.2, 1.0) for _ in range(hits)]
    total = sum(weights) or 1.0
    acc = 0.0
    used: set[int] = set()
    chosen: list[float] = []
    for weight in weights:
        acc += weight / total
        idx = min(count - 1, max(0, int(acc * count)))
        if idx in used:
            for delta in range(1, count):
                for cand in (idx + delta, idx - delta):
                    if 0 <= cand < count and cand not in used:
                        idx = cand
                        break
                else:
                    continue
                break
        used.add(idx)
        chosen.append(pool[idx])
    return sorted(chosen)


def _gen_today(hits: int, spread: str | None = None, tz: str | None = None) -> list:
    """Generate ``hits`` fire epochs for today.

    ``spread`` is the Uneven vs uniform checkbox. ``tz`` is the exit-country zone.
    A missing or unknown zone returns no times. It does not fall back to the host clock.
    """
    if hits <= 0:
        return []
    mode = _spread_name(spread)
    if tz:
        try:
            zone = ZoneInfo(str(tz))
        except Exception:
            return []
        pool = _exit_daytime_epochs(zone, SCHED_ACTIVE_HOUR_START, SCHED_ACTIVE_HOUR_END)
        return _pick_epochs(pool, hits, mode == "organic")
    mn = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    if mode == "organic" and hits > 1:
        # Dirichlet-like spacings: gamma samples then normalize to the 86400s window.
        weights = [random.gammavariate(1.2, 1.0) for _ in range(hits)]
        total = sum(weights) or 1.0
        offsets = []
        acc = 0.0
        for w in weights:
            acc += (w / total) * 86400.0
            offsets.append(acc)
        offsets = [max(0.0, min(86399.0, o + random.uniform(-90, 90))) for o in offsets]
        offsets.sort()
        return [mn + o for o in offsets]
    offsets = sorted(random.uniform(0, 86400) for _ in range(hits))
    return [mn + o for o in offsets]


# Capital timezone. Tor GeoIP does not report a city, so a multi-zone country uses that capital.
_TZ_BY_COUNTRY = {
    "AD": "Europe/Andorra", "AE": "Asia/Dubai", "AF": "Asia/Kabul", "AL": "Europe/Tirane",
    "AM": "Asia/Yerevan", "AO": "Africa/Luanda", "AR": "America/Argentina/Buenos_Aires",
    "AT": "Europe/Vienna", "AU": "Australia/Sydney", "AZ": "Asia/Baku", "BA": "Europe/Sarajevo",
    "BD": "Asia/Dhaka", "BE": "Europe/Brussels", "BG": "Europe/Sofia", "BH": "Asia/Bahrain",
    "BR": "America/Sao_Paulo", "BY": "Europe/Minsk", "CA": "America/Toronto", "CH": "Europe/Zurich",
    "CL": "America/Santiago", "CN": "Asia/Shanghai", "CO": "America/Bogota", "CR": "America/Costa_Rica",
    "CY": "Asia/Nicosia", "CZ": "Europe/Prague", "DE": "Europe/Berlin", "DK": "Europe/Copenhagen",
    "DZ": "Africa/Algiers", "EE": "Europe/Tallinn", "EG": "Africa/Cairo", "ES": "Europe/Madrid",
    "FI": "Europe/Helsinki", "FR": "Europe/Paris", "GB": "Europe/London", "GE": "Asia/Tbilisi",
    "GR": "Europe/Athens", "HK": "Asia/Hong_Kong", "HR": "Europe/Zagreb", "HU": "Europe/Budapest",
    "ID": "Asia/Jakarta", "IE": "Europe/Dublin", "IL": "Asia/Jerusalem", "IN": "Asia/Kolkata",
    "IS": "Atlantic/Reykjavik", "IT": "Europe/Rome", "JP": "Asia/Tokyo", "KE": "Africa/Nairobi",
    "KR": "Asia/Seoul", "KZ": "Asia/Almaty", "LT": "Europe/Vilnius", "LU": "Europe/Luxembourg",
    "LV": "Europe/Riga", "MA": "Africa/Casablanca", "MD": "Europe/Chisinau", "MK": "Europe/Skopje",
    "MX": "America/Mexico_City", "MY": "Asia/Kuala_Lumpur", "NG": "Africa/Lagos", "NL": "Europe/Amsterdam",
    "NO": "Europe/Oslo", "NZ": "Pacific/Auckland", "PA": "America/Panama", "PE": "America/Lima",
    "PH": "Asia/Manila", "PL": "Europe/Warsaw", "PT": "Europe/Lisbon", "RO": "Europe/Bucharest",
    "RS": "Europe/Belgrade", "RU": "Europe/Moscow", "SE": "Europe/Stockholm", "SG": "Asia/Singapore",
    "SI": "Europe/Ljubljana", "SK": "Europe/Bratislava", "TH": "Asia/Bangkok", "TR": "Europe/Istanbul",
    "TW": "Asia/Taipei", "UA": "Europe/Kyiv", "US": "America/New_York", "UY": "America/Montevideo",
    "VN": "Asia/Ho_Chi_Minh", "ZA": "Africa/Johannesburg",
}


def timezone_for_exit_country(code: str) -> str:
    return _TZ_BY_COUNTRY.get(str(code or "").strip().upper(), "")


def _exit_tz_for_serial(serial: str) -> str:
    idx = tor_manager.phone_idx_from_adb_serial(serial)
    return timezone_for_exit_country(tor_manager.tor_exit_country(idx))


_ALLOWED_STEP_TYPES = frozenset({
    "open_url", "launch_app", "tap", "wait", "swipe", "keyevent",
    "close_app", "clear_cookies", "type_text",
    "rotate_identity", "full_reset",
})


def _has_age_verification_marker(steps: list) -> bool:
    if not isinstance(steps, list):
        return False
    for raw in steps:
        if not isinstance(raw, dict):
            continue
        if raw.get("age_verification") is True or raw.get("age_gate") is True:
            return True
        marker = str(raw.get("checkpoint", "")).strip().lower()
        if marker in ("age_verification", "age_gate"):
            return True
    return False


def _run_steps(serial: str, steps: list):
    if os.environ.get("PHARMFLOW_SKIP_TOR_WAIT", "").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        pre = tor_manager.tor_proxy_preflight()
        if not pre.get("ok"):
            log.error("[scheduler] Tor unavailable — %s (set PHARMFLOW_SKIP_TOR_WAIT=1 to bypass)", pre.get("error"))
            return False
        idx = tor_manager.phone_idx_from_adb_serial(serial)
        log.info("[scheduler] waiting for Tor bootstrap + proxy for %s …", serial)
        ens = tor_manager.ensure_tor_and_proxy_for_phone(serial, idx)
        if not ens.get("ok"):
            log.error("[scheduler] Tor not ready for %s — %s", serial, ens.get("error"))
            return False

    normalized = normalize_automation_steps(list(steps or []))
    hv_rng = hv.rng_for_run(serial, int(_time.time())) if hv.enabled() else None
    if not _has_age_verification_marker(normalized):
        log.warning(
            "[scheduler] %s sequence missing age verification marker; flagging anomaly",
            _name(serial),
        )
        _broadcast_from_thread(
            {
                "type": "log",
                "msg": f"[scheduler] {_name(serial)} anomaly: sequence missing age verification marker",
            }
        )
    ran = 0
    for step in normalized:
        if not isinstance(step, dict):
            continue
        step_type = step.get("type", "")
        if step_type not in _ALLOWED_STEP_TYPES:
            log.warning(
                "[scheduler] %s step %s is not a runnable step — hit not counted",
                _name(serial),
                step_type,
            )
            return False
        if _dashboard().run_sequence_step(serial, step, hv_rng=hv_rng) is False:
            log.warning("[scheduler] %s step %s did not land — hit not counted", _name(serial), step_type)
            return False
        ran += 1
        if hv_rng is not None:
            _time.sleep(hv.step_gap_seconds(hv_rng))
        else:
            _time.sleep(random.uniform(0.35, 0.55))
    if ran < 1:
        log.warning("[scheduler] %s had no runnable steps — hit not counted", _name(serial))
        return False
    idx = tor_manager.phone_idx_from_adb_serial(serial)
    tor_manager.full_identity_reset(serial, idx)
    return True


def _broadcast_from_thread(msg: dict):
    if _main_loop is not None:
        asyncio.run_coroutine_threadsafe(_dashboard().broadcast(msg), _main_loop)


def _sleep_while_running(serial: str, seconds: float) -> None:
    deadline = _time.time() + seconds
    while _time.time() < deadline:
        with _sched_lock:
            if not RUNNING.get(serial, False):
                return
        _time.sleep(min(5.0, deadline - _time.time()))


def _sched_loop(serial: str, steps: list, hits_per_day: int):
    log.info("[scheduler] %s started (%s hits/day)", _name(serial), hits_per_day)
    if hits_per_day <= 0:
        log.info("[scheduler] %s stopping — hits_per_day<=0 (would busy-spin)", _name(serial))
        with _sched_lock:
            RUNNING.pop(serial, None)
        return
    while True:
        with _sched_lock:
            if not RUNNING.get(serial, False):
                break
            info  = PHONE_SCHED.get(serial, {})
            times = list(info.get("times", []))
            idx   = info.get("idx", 0)

        now = _time.time()
        mn_today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

        if not times or (times and times[0] < mn_today):
            spread = info.get("spread")
            tor_local = bool(info.get("tor_local"))
            tz_name = ""
            if tor_local:
                tz_name = _exit_tz_for_serial(serial)
                if not tz_name:
                    log.error(
                        "[scheduler] %s exit country is unknown — not placing a host-clock schedule",
                        _name(serial),
                    )
                    _broadcast_from_thread({
                        "type": "log",
                        "msg": (
                            f"[scheduler] {_name(serial)} daytime in the Tor exit country "
                            "could not be placed. No host-clock schedule was started."
                        ),
                    })
                    _sleep_while_running(serial, 60)
                    continue
            try:
                new_times = _gen_today(hits_per_day, spread=spread, tz=tz_name or None)
            except ValueError as exc:
                log.error("[scheduler] %s %s", _name(serial), exc)
                _sleep_while_running(serial, 60)
                continue
            if tor_local and not new_times:
                log.error("[scheduler] %s exit daytime window is empty — not using the host clock", _name(serial))
                _sleep_while_running(serial, 60)
                continue
            with _sched_lock:
                stored = dict(PHONE_SCHED.get(serial) or {})
                stored.update({
                    "hits": hits_per_day,
                    "times": new_times,
                    "idx": 0,
                    "spread": spread,
                    "tor_local": tor_local,
                    "tz": tz_name,
                })
                PHONE_SCHED[serial] = stored
            log.info("[scheduler] %s new day schedule: %s hits", _name(serial), len(new_times))
            _broadcast_from_thread({
                "type": "scheduler_update", "serial": serial,
                "hits_per_day": hits_per_day, "times": new_times})
            continue

        if idx >= len(times):
            _broadcast_from_thread({"type": "scheduler_done_today", "serial": serial})
            _time.sleep(random.uniform(60, 300))
            continue

        wait = times[idx] - now
        if wait > 0:
            _time.sleep(min(wait, 30))
            continue

        log.info("[scheduler] %s firing [%s/%s]", _name(serial), idx + 1, len(times))
        _broadcast_from_thread({
            "type": "scheduler_tick", "serial": serial,
            "count": idx + 1, "total": len(times)})
        if _run_steps(serial, steps) is False:
            log.warning("[scheduler] %s fire did not land — not counting this hit", _name(serial))
            _time.sleep(30)
            continue
        with _sched_lock:
            if serial in PHONE_SCHED:
                PHONE_SCHED[serial]["idx"] = idx + 1
        _time.sleep(1)

    with _sched_lock:
        RUNNING.pop(serial, None)
    log.info("[scheduler] %s stopped", _name(serial))


async def handle_scheduler(path: str, body_bytes: bytes, method: str = "POST"):
    global _main_loop
    _main_loop = asyncio.get_running_loop()

    data = {}
    if body_bytes and method != "GET":
        try:
            data = json.loads(body_bytes)
        except Exception:
            pass

    if path == "/api/scheduler/generate":
        if data.get("schedule_tor_local"):
            return _dashboard().json_err(
                "exit-country daytime cannot be previewed without each phone's Tor exit"
            )
        plan = plan_scheduler_start(data)
        if plan.get("error"):
            return _dashboard().json_err(plan["error"])
        result = {}
        with _sched_lock:
            for job in plan["jobs"]:
                PHONE_SCHED[job["serial"]] = {
                    "hits": job["hits"],
                    "times": job["times"],
                    "idx": 0,
                    "spread": job["spread"],
                    "tor_local": False,
                    "tz": "",
                }
                result[job["serial"]] = [
                    datetime.datetime.fromtimestamp(t).strftime("%H:%M") for t in job["times"]
                ]
        return _dashboard().json_ok({"ok": True, "schedule": result})

    if path == "/api/scheduler/start":
        plan = plan_scheduler_start(data)
        if plan.get("error"):
            return _dashboard().json_err(plan["error"])
        started = []
        already = []
        with _sched_lock:
            for job in plan["jobs"]:
                serial = job["serial"]
                if RUNNING.get(serial, False):
                    already.append(serial)
                    continue
                PHONE_SCHED[serial] = {
                    "hits": job["hits"],
                    "times": job["times"],
                    "idx": 0,
                    "spread": job["spread"],
                    "tor_local": job["tor_local"],
                    "tz": "",
                }
                RUNNING[serial] = True
                threading.Thread(
                    target=_sched_loop,
                    args=(serial, job["steps"], job["hits"]),
                    daemon=True,
                ).start()
                started.append(serial)
        if not started and not already:
            detail = "; ".join(plan["errors"]) or "no phones to schedule"
            return _dashboard().json_err(detail)
        return _dashboard().json_ok({
            "ok": True,
            "started": started,
            "already_running": already,
            "errors": plan["errors"],
            "tor_local": plan["tor_local"],
        })

    if path == "/api/scheduler/stop":
        with _sched_lock:
            for k in list(RUNNING):
                RUNNING[k] = False
        return _dashboard().json_ok({"ok": True})

    if path == "/api/scheduler/status":
        with _sched_lock:
            snapshot = {s: dict(info) for s, info in PHONE_SCHED.items()}
            running_snap = dict(RUNNING)
        out = {}
        for s, info in snapshot.items():
            times = info.get("times", [])
            idx   = info.get("idx", 0)
            out[s] = {
                "hits_per_day": info.get("hits", 0),
                "fired_today":  idx,
                "remaining":    max(0, len(times) - idx),
                "running":      running_snap.get(s, False),
            }
        return _dashboard().json_ok(out)

    return _dashboard().json_ok({"ok": False, "error": "unknown route"})
