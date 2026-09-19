"""Runtime Mantis zone fix for live getdabflow.app — injected via Chrome DevTools Protocol."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from automation.adb_wrapper import AdbWrapper
from automation.dabflow_mantis_ad_urls import (
    has_live_click_token,
    is_mantis_house_bot_click_url,
)

logger = logging.getLogger(__name__)

DABFLOW_HOST_RE = re.compile(r"(^|\.)getdabflow\.app$", re.I)
DEVICE_CDP_PORT = 9222

# All Mantis zones on getdabflow.app (matches fixedZones in PATCH_JS).
ALL_MANTIS_ZONES: tuple[str, ...] = (
    "zone-one",
    "zone-two",
    "zone-three",
    "zone-four",
    "zone-five",
    "zone-six",
    "zone-seven",
    "zone-eight",
    "zone-nine",
    "zone-ten",
    "zone-eleven",
    "zone-twelve",
    "zone-thirteen",
    "zone-fourteen",
    "zone-fifteen",
    "tester",
)

# Host-side SSP cache — page loads fast; cold SSP fetches were making creatives lag.
_SSP_LOCK = threading.Lock()
_SSP_ADS: list[dict[str, Any]] = []
_SSP_FETCHED_AT = 0.0
_SSP_INFLIGHT = False
_SSP_HOUSE_ONLY_AT = 0.0
_SSP_FETCH_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)
# Cross-process handoff: hunter runs out-of-process; in-memory _store_ssp_ads
# never reaches farm workers. Persist paying creatives here for farm load.
# Dual-root: live farm sticky state is still under C:\CPharm; branding also
# writes C:\PharmFlow. Prefer CPharm for reads; dual-write both.
def _ssp_logs_dirs() -> list[Path]:
    return [Path(r"C:\CPharm\logs"), Path(r"C:\PharmFlow\logs")]


_SSP_PAYING_FILL_PATH = _ssp_logs_dirs()[0] / "ssp_paying_fill.json"
# Inject proxy publishes each phone's real browser fingerprint here; the host
# SSP fetches below adopt it so Mantis serves the paying tier. Measured
# 2026-09-11: bare urllib UA → paying=0 (bot tier) on every round, while the
# same probe with phone client hints → paying=4. Without this the hunter's
# bare probes saw only mantis-bot fill (utm_source=mantis-bot) for hours.
_CLIENT_HINTS_PUBLISH_PATH = _ssp_logs_dirs()[0] / "client_hints_by_phone.json"
_CLIENT_HINTS_CACHE: tuple[float, dict[str, dict[str, str]]] = (0.0, {})
_CLIENT_HINTS_LOCK = threading.Lock()


def _paying_fill_paths() -> list[Path]:
    # Dual-root convention (CPharm + PharmFlow) by default; an explicit
    # override of _SSP_PAYING_FILL_PATH (tests, operator pinning) wins so the
    # module attribute stays the single source of truth it was before.
    override = Path(_SSP_PAYING_FILL_PATH)
    if override != _ssp_logs_dirs()[0] / override.name:
        return [override]
    return [d / "ssp_paying_fill.json" for d in _ssp_logs_dirs()]


def _client_hints_paths() -> list[Path]:
    return [d / "client_hints_by_phone.json" for d in _ssp_logs_dirs()]


def _load_client_hints(max_age_s: float = 600.0) -> dict[str, str] | None:
    """Latest published phone client hints, or None when stale/missing.

    The inject proxy refreshes the publish file as phones boot (its per-phone
    updater stamps ``updated``), so mtime freshness is liveness proof — a stale
    file falls back to the plain host UA rather than poisoning every fetch.
    """
    global _CLIENT_HINTS_CACHE
    with _CLIENT_HINTS_LOCK:
        cached_at, cached = _CLIENT_HINTS_CACHE
    now = time.time()
    if cached and now - cached_at < 30.0:
        return dict(cached)
    data = None
    for path in _client_hints_paths():
        try:
            if not path.is_file():
                continue
            if now - path.stat().st_mtime > max_age_s:
                continue
            parsed = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(parsed, dict) and parsed:
                data = parsed
                break
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    if not isinstance(data, dict):
        return None
    for row in (data or {}).values():
        if isinstance(row, dict) and str(row.get("user_agent") or ""):
            row["_src"] = str(row.get("updated") or 0.0)
    best = max(
        (r for r in (data or {}).values() if isinstance(r, dict) and r.get("user_agent")),
        key=lambda r: float(r.get("_src") or 0.0),
        default=None,
    )
    if not best:
        return None
    hints = {
        "user_agent": str(best.get("user_agent") or ""),
        "sec-ch-ua": str(best.get("sec_ch_ua") or ""),
        "sec-ch-ua-mobile": str(best.get("sec_ch_ua_mobile") or "?1"),
        "sec-ch-ua-platform": str(best.get("sec_ch_ua_platform") or "\"Android\""),
        "sec-ch-ua-platform-version": str(best.get("sec_ch_ua_platform_version") or ""),
        "sec-ch-ua-model": str(best.get("sec_ch_ua_model") or ""),
        "sec-ch-ua-full-version-list": str(best.get("sec_ch_ua_full_version_list") or ""),
    }
    with _CLIENT_HINTS_LOCK:
        _CLIENT_HINTS_CACHE = (now, hints)
    return dict(hints)


def _ssp_browser_headers() -> dict[str, str]:
    """Host SSP headers shaped like the phones' real browser requests.

    Falls back to the static mobile UA when the inject proxy has not published
    hints yet (fresh install / phones down) — never returns an empty UA.
    """
    hints = _load_client_hints()
    if not hints or not hints.get("user_agent"):
        return {"User-Agent": _SSP_FETCH_UA}
    headers = {"User-Agent": hints["user_agent"]}
    for key in (
        "sec-ch-ua",
        "sec-ch-ua-mobile",
        "sec-ch-ua-platform",
        "sec-ch-ua-platform-version",
        "sec-ch-ua-model",
        "sec-ch-ua-full-version-list",
    ):
        val = (hints.get(key) or "").strip()
        if val:
            headers[key] = val
    return headers
# Wall-clock age of the *original* hunter write. Must NOT be refreshed on ingest
# or the same creative is replayed forever while live SSP is house-only.
_SSP_PAYING_FILL_MAX_AGE_S = 120.0


_STICKY_OVERRIDES = Path(r"C:\PharmFlow\logs\farm_runtime_overrides.json")
_sticky_mtime: float = -1.0
_sticky_cache: dict[str, str] = {}


def _sticky_overrides() -> dict[str, str]:
    """Mtime-cached sticky PHARMFLOW_* so money knobs apply without Farm Start bounce."""
    global _sticky_mtime, _sticky_cache
    try:
        mtime = _STICKY_OVERRIDES.stat().st_mtime
    except OSError:
        _sticky_mtime = -1.0
        _sticky_cache = {}
        return _sticky_cache
    if mtime == _sticky_mtime:
        return _sticky_cache
    try:
        data = json.loads(_STICKY_OVERRIDES.read_text(encoding="utf-8"))
        _sticky_cache = {
            str(k): str(v)
            for k, v in (data or {}).items()
            if str(k).startswith("PHARMFLOW_")
        }
        _sticky_mtime = mtime
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return _sticky_cache


def _env_or_sticky_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        raw = (_sticky_overrides().get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _ssp_ttl() -> float:
    # Re-read sticky/env each call so money-day TTL knobs apply without process recycle.
    # No hardcoded min/max range — repo rule forbids artificial caps. Only guard
    # against a literally negative duration; any positive operator value stands.
    return max(0.0, _env_or_sticky_float("PHARMFLOW_SSP_CACHE_TTL", 90.0))


def _ssp_refresh_s() -> float:
    return max(0.0, _env_or_sticky_float("PHARMFLOW_SSP_CACHE_REFRESH", 45.0))


def _ssp_house_only_ttl() -> float:
    # money-day sticky may set this low (e.g. 4s) so house TTL does not block
    # paying return — no floor imposed here beyond non-negative.
    return max(0.0, _env_or_sticky_float("PHARMFLOW_SSP_HOUSE_ONLY_TTL", 45.0))


def ssp_cache_age_s() -> float:
    if _SSP_FETCHED_AT <= 0:
        return 1e9
    return max(0.0, time.monotonic() - _SSP_FETCHED_AT)


def get_cached_ssp_ads(*, allow_stale: bool = True) -> list[dict[str, Any]]:
    """Return cached SSP creatives (empty if never fetched)."""
    with _SSP_LOCK:
        ads = list(_SSP_ADS)
        age = ssp_cache_age_s()
    if not ads:
        return []
    if age <= _ssp_ttl():
        return ads
    return ads if allow_stale else []


def _paying_fill_file_age_s() -> float:
    """Wall age of ssp_paying_fill.json from its original ``ts`` (not mtime)."""
    best = 1e9
    for path in _paying_fill_paths():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            ts = float((data or {}).get("ts") or 0.0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if ts <= 0:
            continue
        best = min(best, max(0.0, time.time() - ts))
    return best


def paying_fill_file_fresh() -> bool:
    """True when shared paying fill exists and is within max age."""
    return _paying_fill_file_age_s() <= _SSP_PAYING_FILL_MAX_AGE_S


def clear_ssp_paying_fill_file(*, reason: str = "") -> bool:
    """Delete stale shared paying fill so farm stops replaying one creative."""
    cleared = False
    for path in _paying_fill_paths():
        try:
            if not path.is_file():
                continue
            path.unlink()
            cleared = True
        except OSError as exc:
            logger.debug("clear paying fill soft-fail path=%s: %s", path, exc)
    if cleared:
        logger.info(
            "Cleared ssp_paying_fill.json reason=%s",
            reason or "expired",
        )
    return cleared


def _persist_paying_fill(ads: list[dict[str, Any]]) -> None:
    """Write paying creatives for other processes (hunter → farm).

    Merge-by-zone: SSP rotates inventory per request, so one probe rarely
    returns paying creatives for every zone at once. Merging accumulates
    multi-zone paying inventory in the shared fill file instead of
    overwriting it with the last probe's single zone. Per-ad ``_ts``
    timestamps age out entries older than the max age so the file never
    replays stale creatives forever.
    """
    now = time.time()
    fresh_rows: dict[str, dict[str, Any]] = {}
    for path in _paying_fill_paths():
        try:  # seed from the previous file so other zones survive this write
            prev = json.loads(path.read_text(encoding="utf-8"))
            for row in (prev or {}).get("ads") or []:
                if (
                    isinstance(row, dict)
                    and now - float(row.get("_ts") or 0.0) <= _SSP_PAYING_FILL_MAX_AGE_S
                ):
                    fresh_rows[str(row.get("zone_id") or "")] = row
            if fresh_rows:
                break
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    for a in ads or []:
        if (
            isinstance(a, dict)
            and str(a.get("click_url") or "").startswith("http")
            and not is_mantis_house_bot_click_url(str(a.get("click_url") or ""))
        ):
            row = dict(a)
            row["_ts"] = now
            fresh_rows[str(row.get("zone_id") or "")] = row
    if not fresh_rows:
        return
    paying_rows = list(fresh_rows.values())
    payload = {
        "ts": now,
        "paying": len(paying_rows),
        "ads": paying_rows,
    }
    text = json.dumps(payload)
    for path in _paying_fill_paths():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            logger.debug("SSP paying-fill persist soft-fail path=%s: %s", path, exc)


def _ingest_paying_fill_file(*, max_age_s: float | None = None) -> list[dict[str, Any]]:
    """Load cross-process paying fill into this process cache when fresher/better.

    Critical: do **not** re-persist on ingest. Re-writing ``ts`` made a single
    creative immortal while the hunter saw house-only for thousands of rounds.
    """
    age_limit = (
        _SSP_PAYING_FILL_MAX_AGE_S if max_age_s is None else max(15.0, float(max_age_s))
    )
    best: tuple[float, list[dict[str, Any]]] | None = None
    for path in _paying_fill_paths():
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        try:
            ts = float((data or {}).get("ts") or 0.0)
        except (TypeError, ValueError):
            continue
        age = time.time() - ts if ts > 0 else 1e9
        if ts <= 0 or age > age_limit:
            continue
        ads = [a for a in ((data or {}).get("ads") or []) if isinstance(a, dict)]
        if ssp_ads_paying_count(ads) <= 0:
            continue
        if best is None or ts > best[0]:
            best = (ts, ads)
    if best is None:
        # Expire any leftover stale files once nothing fresh remains.
        if _paying_fill_file_age_s() < 1e8 and _paying_fill_file_age_s() > age_limit:
            clear_ssp_paying_fill_file(
                reason=f"expired_age={_paying_fill_file_age_s():.0f}s"
            )
        return []
    ads = best[1]
    # persist=False — keep original hunter timestamp so fill can expire.
    _store_ssp_ads(ads, persist=False)
    _clear_ssp_house_only()
    return get_cached_ssp_ads(allow_stale=True) or ads


def _store_ssp_ads(ads: list[dict[str, Any]], *, persist: bool = True) -> None:
    global _SSP_ADS, _SSP_FETCHED_AT
    incoming_pay = ssp_ads_paying_count(ads)
    with _SSP_LOCK:
        cached_pay = ssp_ads_paying_count(_SSP_ADS)
        if incoming_pay == 0 and cached_pay > 0:
            # Keep a *fresh* shared paying fill; wipe memory when fill is gone/expired
            # so we stop painting the same Viking creative forever.
            if paying_fill_file_fresh():
                return
            clear_ssp_paying_fill_file(reason="house_overwrite_stale_fill")
        _SSP_ADS = list(ads)
        _SSP_FETCHED_AT = time.monotonic()
    if incoming_pay > 0 and persist:
        _persist_paying_fill(ads)
        _clear_ssp_house_only()
    elif incoming_pay == 0 and not paying_fill_file_fresh():
        clear_ssp_paying_fill_file(reason="house_store_no_fresh_fill")

def clear_ssp_cache() -> None:
    """Drop host SSP cache so the next Path3 open re-fetches live inventory."""
    global _SSP_ADS, _SSP_FETCHED_AT, _SSP_HOUSE_ONLY_AT
    with _SSP_LOCK:
        _SSP_ADS = []
        _SSP_FETCHED_AT = 0.0
        _SSP_HOUSE_ONLY_AT = 0.0
    logger.info("SSP cache cleared")


def _mark_ssp_house_only() -> None:
    global _SSP_HOUSE_ONLY_AT
    with _SSP_LOCK:
        _SSP_HOUSE_ONLY_AT = time.monotonic()


def _clear_ssp_house_only() -> None:
    global _SSP_HOUSE_ONLY_AT
    with _SSP_LOCK:
        _SSP_HOUSE_ONLY_AT = 0.0


def ssp_recently_house_only() -> bool:
    """True if a recent refresh found only house/bot creatives (debounce thrash)."""
    with _SSP_LOCK:
        marked = _SSP_HOUSE_ONLY_AT
    if marked <= 0:
        return False
    return (time.monotonic() - marked) < _ssp_house_only_ttl()


def ssp_paying_zone_ids(*, force_refresh: bool = False) -> set[str]:
    """Zone ids currently holding non-house SSP click_urls."""
    _ingest_paying_fill_file()
    if force_refresh or not get_cached_ssp_ads(allow_stale=True):
        ads = prefetch_ssp_ads(force=True)
    else:
        ads = get_cached_ssp_ads(allow_stale=True)
    # Prefer in-memory paying; if force refresh returned house, keep file/cache paying.
    if ssp_ads_paying_count(ads) == 0:
        cached = get_cached_ssp_ads(allow_stale=True)
        if ssp_ads_paying_count(cached) > 0:
            ads = cached
        else:
            file_ads = _ingest_paying_fill_file()
            if ssp_ads_paying_count(file_ads) > 0:
                ads = file_ads
    paying: set[str] = set()
    for ad in ads or []:
        click = str(ad.get("click_url") or "").strip()
        if not click.startswith("http"):
            continue
        if is_mantis_house_bot_click_url(click):
            continue
        zone = str(ad.get("zone_id") or "").strip()
        if zone:
            paying.add(zone)
    if paying:
        _clear_ssp_house_only()
    elif ads:
        _mark_ssp_house_only()
    return paying


def ssp_has_paying_fill(*, force_refresh: bool = False) -> bool:
    """True when at least one non-house advertiser click_url is in SSP inventory."""
    # Cross-process hunter fill beats a stale house-only TTL in this worker.
    _ingest_paying_fill_file()
    if ssp_ads_paying_count(get_cached_ssp_ads(allow_stale=True)) > 0:
        _clear_ssp_house_only()
        return True
    if not force_refresh and ssp_recently_house_only():
        return False
    return bool(ssp_paying_zone_ids(force_refresh=force_refresh))


def ssp_ads_paying_count(ads: list[dict[str, Any]] | None) -> int:
    """Count non-house SSP creatives in a payload."""
    n = 0
    for ad in ads or []:
        click = str(ad.get("click_url") or "").strip()
        if click.startswith("http") and not is_mantis_house_bot_click_url(click):
            n += 1
    return n


def filter_ssp_ads_prefer_paying(
    ads: list[dict[str, Any]] | None,
    *,
    allow_house_fallback: bool = True,
) -> list[dict[str, Any]]:
    """Prefer paying creatives.

    When inventory is house-only (``utm_source=mantis-bot`` / mantisadnetwork),
    ``allow_house_fallback=False`` returns [] so host-paint does not crowd out
    native mantis.js with non-billable house creatives. Click paths already
    refuse house via ``click_url_for_zone(prefer_paying=True)``.
    """
    rows = [a for a in (ads or []) if isinstance(a, dict)]
    paying = [
        a
        for a in rows
        if str(a.get("click_url") or "").startswith("http")
        and not is_mantis_house_bot_click_url(str(a.get("click_url") or ""))
    ]
    if paying:
        return paying
    return rows if allow_house_fallback else []


def fire_ssp_impression_pixels_hostside(
    ads: list[dict[str, Any]] | None,
    *,
    paying_only: bool = True,
) -> int:
    """Fire served/viewed pixels from the host (bypasses phone Tor flakes).

    House/bot pixels return HTTP 200 but do **not** move publisher GraphQL
    impressions — skip them when ``paying_only`` is set.
    """
    fired = 0
    for ad in ads or []:
        click = str(ad.get("click_url") or "").strip()
        if paying_only and (
            not click.startswith("http") or is_mantis_house_bot_click_url(click)
        ):
            continue
        urls = list(ad.get("served_pixels") or []) + list(ad.get("viewed_pixels") or [])
        for url in urls:
            u = str(url or "").strip()
            if not u.startswith("http"):
                continue
            try:
                req = urllib.request.Request(
                    u,
                    headers={
                        "User-Agent": _SSP_FETCH_UA,
                        "Referer": "https://getdabflow.app/",
                    },
                )
                with urllib.request.urlopen(req, timeout=8.0) as resp:
                    resp.read(64)
                fired += 1
            except Exception as exc:
                logger.debug("host pixel fire soft-fail: %s", exc)
    if fired:
        logger.info("host-side impression pixels fired count=%d", fired)
    return fired


def _consume_ssp_force_refresh_flag() -> bool:
    """Wake farm SSP refresh without destroying a live paying fill.

    Hunter / money monitor drop this flag after finding paying inventory. The old
    path wiped ``_SSP_ADS`` then re-fetched house — throwing away the fill the
    hunter just locked. Now: ingest shared paying file first; only clear memory
    when there is no paying creative to keep.
    """
    flag = Path(r"C:\PharmFlow\logs\SSP_FORCE_REFRESH.flag")
    try:
        if not flag.is_file():
            return False
        flag.unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.debug("SSP force-refresh flag soft-fail: %s", exc)
        return False

    _clear_ssp_house_only()
    file_ads = _ingest_paying_fill_file()
    cached_pay = ssp_ads_paying_count(get_cached_ssp_ads(allow_stale=True) or file_ads)
    if cached_pay > 0:
        logger.info(
            "SSP_FORCE_REFRESH.flag consumed — kept paying=%d (no cache wipe)",
            cached_pay,
        )
        return True
    clear_ssp_cache()
    logger.info("SSP_FORCE_REFRESH.flag consumed — house TTL cleared, cache empty")
    return True


def prefetch_ssp_ads(*, force: bool = False) -> list[dict[str, Any]]:
    """Blocking fetch into cache. Prefer get_cached_ssp_ads + ensure_ssp_cache_warm."""
    _ingest_paying_fill_file()
    if _consume_ssp_force_refresh_flag():
        force = True
        # Hunter may have just persisted paying fill — serve it immediately.
        cached_pay = get_cached_ssp_ads(allow_stale=True)
        if ssp_ads_paying_count(cached_pay) > 0:
            return cached_pay
    if not force:
        cached = get_cached_ssp_ads(allow_stale=False)
        if cached:
            return cached
    try:
        ads = fetch_ssp_display_ads(timeout=6.0)
        if ads:
            paying = ssp_ads_paying_count(get_cached_ssp_ads(allow_stale=True) or ads)
            logger.info(
                "SSP cache refreshed count=%d paying=%d age=0s",
                len(get_cached_ssp_ads(allow_stale=True) or ads),
                paying,
            )
            if paying:
                _clear_ssp_house_only()
            else:
                # Do not stamp house-only if shared file still holds paying.
                if ssp_ads_paying_count(get_cached_ssp_ads(allow_stale=True)) == 0:
                    file_ads = _ingest_paying_fill_file()
                    if ssp_ads_paying_count(file_ads) == 0:
                        _mark_ssp_house_only()
        cached = get_cached_ssp_ads(allow_stale=True)
        if ssp_ads_paying_count(cached) > 0:
            return cached
        return cached or ads
    except Exception as exc:
        logger.warning("SSP prefetch failed: %s", exc)
        return get_cached_ssp_ads(allow_stale=True) or _ingest_paying_fill_file()


def prefetch_ssp_ads_prefer_paying(
    *,
    attempts: int = 8,
    delay_s: float = 0.4,
    allow_house_fallback: bool = True,
) -> list[dict[str, Any]]:
    """Burst-fetch until at least one paying creative appears (or attempts exhausted).

    Clears house-only debounce between attempts so a brief paying return is not
    skipped by TTL. Rotates request timezone and Tor HTTP tunnels after host
    house-only — does not fabricate clicks, only re-probes live SSP inventory.
    """
    best: list[dict[str, Any]] = []
    tzs = (-8, -7, -6, -5, -4, 0)
    n_attempts = max(1, int(attempts))
    for i in range(n_attempts):
        _clear_ssp_house_only()
        tz = tzs[i % len(tzs)]
        ads: list[dict[str, Any]] = []
        try:
            ads = fetch_ssp_display_ads(timeout=6.0, timezone=tz) or []
        except Exception as exc:
            logger.debug("SSP prefer-paying host fetch soft-fail: %s", exc)
            ads = prefetch_ssp_ads(force=True) or []
        # Probe live fleet Tor HTTP tunnels — never hardcoded dead VM indexes.
        # upstream_tor_port(22) with vm38-47 live returns base+22 (nobody
        # listening), so the Tor leg never ran and host-IP paying fills were
        # locked. Opening those after a phone house impression pays $0.
        tor_ports: list[int] = []
        try:
            from automation.mantis_inject_proxy import upstream_tor_port

            lock = Path(
                os.environ.get("PHARMFLOW_LOGS")
                or os.environ.get("PHARMFLOW_LOG_DIR")
                or r"C:\PharmFlow\logs"
            ) / "ADB_SERIAL_MAP.lock.json"
            live_idxs: list[int] = []
            try:
                phones = json.loads(lock.read_text(encoding="utf-8")).get("phones") or {}
                for name in phones:
                    m = re.match(r"^vm(\d+)\.", str(name))
                    if m:
                        live_idxs.append(int(m.group(1)))
            except Exception:
                live_idxs = []
            if not live_idxs:
                live_idxs = list(range(8))
            seen_ports: set[int] = set()
            for idx in sorted(set(live_idxs)):
                port = int(upstream_tor_port(idx))
                if port in seen_ports:
                    continue
                seen_ports.add(port)
                tor_ports.append(port)
        except Exception:
            tor_ports = []
        # Prefer phone-exit inventory. Host-direct paying tokens must not win —
        # Path3 opening them after a Tor impression is a silent $0 click.
        host_ads = list(ads)
        via_tor: list[dict[str, Any]] = []
        if tor_ports:
            tor_port = tor_ports[i % len(tor_ports)]
            try:
                via_tor = fetch_ssp_display_ads_via_tor(
                    tor_http_port=tor_port, timezone=tz, timeout=10.0
                ) or []
            except Exception as exc:
                logger.debug(
                    "SSP prefer-paying tor:%s soft-fail: %s", tor_port, exc
                )
                via_tor = []
        tor_paying = ssp_ads_paying_count(via_tor)
        if tor_paying > 0:
            _store_ssp_ads(via_tor)
            _clear_ssp_house_only()
            return filter_ssp_ads_prefer_paying(
                via_tor, allow_house_fallback=allow_house_fallback
            )
        # Tor house-only this round — keep best empty of host tokens.
        if allow_house_fallback and via_tor:
            if ssp_ads_paying_count(via_tor) >= ssp_ads_paying_count(best):
                best = via_tor
        elif allow_house_fallback and host_ads and not best:
            best = host_ads
        if i + 1 < n_attempts:
            time.sleep(max(0.05, float(delay_s)))
    if not allow_house_fallback:
        return []
    return filter_ssp_ads_prefer_paying(
        best or get_cached_ssp_ads(allow_stale=True) or [],
        allow_house_fallback=True,
    )


def ensure_ssp_cache_warm() -> None:
    """Non-blocking: keep SSP creatives warm so paint is instant after page load."""
    global _SSP_INFLIGHT
    age = ssp_cache_age_s()
    need = age >= _ssp_refresh_s() or not get_cached_ssp_ads(allow_stale=True)
    if not need:
        return
    with _SSP_LOCK:
        if _SSP_INFLIGHT:
            return
        _SSP_INFLIGHT = True

    def _worker() -> None:
        global _SSP_INFLIGHT
        try:
            prefetch_ssp_ads(force=True)
        finally:
            with _SSP_LOCK:
                _SSP_INFLIGHT = False

    threading.Thread(target=_worker, name="ssp-prefetch", daemon=True).start()


PATCH_JS = r"""
(function pharmflowDabflowMantisPatch() {
  // Re-runnable: farm may re-inject after navigation / age-gate.
  window.__pharmflowMantisPatchV1 = true;
  var PROPERTY_ID = '6950d5527c56c6494f189e46';
  var SSP = 'https://ssp.mantis.marketing/display';
  var fixedZones = {
    home: ['zone-one', 'tester'],
    timer: ['zone-two', 'zone-three', 'zone-four'],
    stats: ['zone-five', 'zone-six', 'zone-seven'],
    glass: ['zone-eight', 'zone-nine', 'zone-ten', 'zone-eleven'],
    settings: ['zone-twelve', 'zone-thirteen', 'zone-fourteen', 'zone-fifteen']
  };
  function ensureBottomTesterZone() {
    // Home lists 'tester' but dabflow HTML has no data-mantis-zone=tester.
    // Mount BELOW #recommended (not inside) — recommend.min.js wipes children.
    var wrap = document.getElementById('pharmflow-bottom-ad');
    var z = wrap && wrap.querySelector('[data-mantis-zone="tester"]');
    if (wrap && z) {
      wrap.style.cssText = 'display:block!important;visibility:visible!important;opacity:1!important;'
        + 'min-height:250px;width:100%;max-width:320px;margin:0.75rem auto 5.5rem;text-align:center;'
        + 'overflow:visible!important;position:relative;z-index:20;';
      return z;
    }
    wrap = document.createElement('div');
    wrap.id = 'pharmflow-bottom-ad';
    wrap.className = 'ad-container pharmflow-bottom-ad';
    wrap.setAttribute('data-pharmflow-bottom-host', '1');
    wrap.style.cssText = 'display:block!important;visibility:visible!important;opacity:1!important;'
      + 'min-height:250px;width:100%;max-width:320px;margin:0.75rem auto 5.5rem;text-align:center;'
      + 'overflow:visible!important;position:relative;z-index:20;';
    z = document.createElement('div');
    z.setAttribute('data-mantis-zone', 'tester');
    z.setAttribute('data-pharmflow-bottom', '1');
    wrap.appendChild(z);
    var rec = document.getElementById('recommended');
    var anchor = rec && (rec.parentElement || rec);
    var main = document.querySelector('main') || document.getElementById('app') || document.body;
    if (anchor && anchor.parentNode) {
      anchor.parentNode.insertBefore(wrap, anchor.nextSibling);
    } else {
      var btn = document.getElementById('start-dab-btn');
      if (btn && btn.parentNode) {
        btn.parentNode.insertBefore(wrap, btn.nextSibling);
      } else {
        main.appendChild(wrap);
      }
    }
    return z;
  }
  function findZone(zoneId) {
    if (!zoneId) return null;
    if (zoneId === 'tester') {
      return ensureBottomTesterZone();
    }
    return document.querySelector('[data-mantis-zone="' + zoneId + '"]')
      || document.querySelector('[data-mantis-zone="' + zoneId + '-"]')
      || document.querySelector('[data-mantis-zone^="' + zoneId + '"]');
  }
  function fixSlotCss() {
    try {
      document.querySelectorAll('.ad-container, [id^="ad-slot-"], [data-mantis-zone]').forEach(function(el) {
        el.style.minWidth = '300px';
        el.style.width = '100%';
        el.style.maxWidth = '100%';
        el.style.minHeight = el.style.minHeight || '250px';
        el.style.display = 'block';
        el.style.visibility = 'visible';
        el.style.opacity = '1';
        el.style.overflow = 'visible';
      });
      // Path1/2 may display creatives, but normal functional taps must pass
      // through no ad link. Path3 explicitly sets cssOnly=false before paint.
      var interactive = window.__pharmflowCssOnly === false;
      document.querySelectorAll('.pharmflow-mantis-creative').forEach(function(el) {
        el.style.pointerEvents = interactive ? 'auto' : 'none';
        el.style.cursor = interactive ? 'pointer' : 'default';
        if (interactive) {
          el.removeAttribute('aria-disabled');
          el.removeAttribute('tabindex');
        } else {
          el.setAttribute('aria-disabled', 'true');
          el.setAttribute('tabindex', '-1');
        }
      });
      // Real Mantis iframes / sponsored nodes also steal taps on Path1/2.
      // When cssOnly, kill pointer events on the whole ad surface.
      if (!interactive) {
        document.querySelectorAll(
          'iframe[src*="mantis"], iframe[id*="mantis"], iframe[class*="mantis"],'
          + ' [contentdesc*="adsbymantis"], [aria-label*="adsbymantis"],'
          + ' a[href*="mantisadnetwork"], a[href*="clicked?r="],'
          + ' [id^="ad-slot-"], [data-mantis-zone], .ad-container'
        ).forEach(function(el) {
          try {
            el.style.pointerEvents = 'none';
            el.setAttribute('aria-disabled', 'true');
          } catch (e2) {}
        });
      }
    } catch (e) {}
  }
  function firePixels(urls) {
    (urls || []).forEach(function(u) {
      try { var i = new Image(); i.src = u; } catch (e) {}
    });
  }
  function paintAd(ad) {
    if (!ad || !ad.zone_id || !ad.creative_url) return false;
    var z = findZone(ad.zone_id);
    if (!z) return false;
    // Path1/2 must not wipe a native iframe. Path3 (cssOnly false) replaces
    // it so the visible creative and the click token are the same fill.
    try {
      var interactive = window.__pharmflowCssOnly === false;
      if (!interactive && z.querySelector('iframe')) return false;
      if (!interactive && z.querySelector('img[src*="mantis"], img[src*="static.mantis"]')
          && !z.querySelector('.pharmflow-mantis-creative')) return false;
    } catch (eSkip) {}
    fixSlotCss();
    z.style.minWidth = '300px';
    z.style.width = '100%';
    z.style.minHeight = (ad.creative_height || 250) + 'px';
    var w = ad.creative_width || 300;
    var h = ad.creative_height || 250;
    var href = ad.click_url || '#';
    // aria-label/content markers so UIAutomator live-pick finds CDP creatives.
    z.innerHTML = '<a class="pharmflow-mantis-creative" href="' + href
      + '" target="_blank" rel="noopener noreferrer" aria-label="adsbymantis"'
      + ' data-mantis-zone="' + ad.zone_id + '"'
      + ' style="display:block;width:100%;text-align:center;">'
      + '<img src="' + ad.creative_url + '" width="' + w + '" height="' + h
      + '" alt="sponsored" style="max-width:100%;height:auto;display:inline-block;margin:0 auto;" loading="eager" decoding="async">'
      + '</a>';
    firePixels(ad.served_pixels);
    firePixels(ad.viewed_pixels);
    // NEVER scrollIntoView here — it shifts the home selection viewport so
    // Path1/2 material/heater/start taps land on the creative instead.
    return true;
  }
  function reportViewed(ads) {
    try {
      var slim = [];
      (ads || []).forEach(function(ad) {
        if (!ad || !ad.click_url || !ad.zone_id) return;
        slim.push({zone_id: ad.zone_id, click_url: ad.click_url});
      });
      if (!slim.length) return;
      fetch('https://getdabflow.app/__pharmflow_viewed', {
        method: 'POST',
        headers: {'Content-Type': 'text/plain'},
        body: JSON.stringify({ads: slim}),
        credentials: 'omit',
        mode: 'same-origin',
        keepalive: true
      }).catch(function() {});
    } catch (e) {}
  }
  // Host-prefetched bi/bt do not match the impression this phone's exit
  // fetched. Capture the SSP JSON the page itself received and store that.
  if (!window.__pharmflowSspHooked) {
    window.__pharmflowSspHooked = true;
    function paintPhoneBottom(ads) {
      var ad = null;
      (ads || []).forEach(function(item) {
        if (ad || !item || !item.creative_url) return;
        var h = item.creative_height || 0;
        if (h >= 200 || !ad) ad = item;
      });
      if (!ad || !ad.creative_url) return;
      var wrap = document.getElementById('pharmflow-bottom-ad');
      if (!wrap) {
        wrap = document.createElement('div');
        wrap.id = 'pharmflow-bottom-ad';
        wrap.setAttribute('data-pharmflow-bottom-host', '1');
        var rec = document.getElementById('recommended');
        var main = document.querySelector('main') || document.body;
        if (rec && rec.parentElement) rec.parentElement.insertBefore(wrap, rec.nextSibling);
        else if (main) main.appendChild(wrap);
        else document.body.appendChild(wrap);
      }
      wrap.style.cssText = 'display:block!important;visibility:visible!important;opacity:1!important;'
        + 'min-height:250px;width:100%;max-width:320px;margin:0.75rem auto 5.5rem;text-align:center;'
        + 'overflow:visible!important;position:relative;z-index:20;';
      var href = ad.click_url || '#';
      wrap.innerHTML = '<a class="pharmflow-mantis-creative" href="' + href
        + '" data-mantis-zone="tester" style="display:block;width:100%;text-align:center;">'
        + '<img src="' + ad.creative_url + '" width="300" height="250" alt="sponsored"'
        + ' style="max-width:100%;height:auto;display:inline-block;"></a>';
    }
    function captureSspPayload(data) {
      var ads = (data && data.ads) || [];
      try { paintPhoneBottom(ads); } catch (ePaint) {}
      try { reportViewed(ads); } catch (eCap) {}
    }
    if (window.fetch) {
      var origFetch = window.fetch;
      window.fetch = function(input, init) {
        var url = '';
        try { url = (typeof input === 'string') ? input : ((input && input.url) || ''); } catch (eUrl) {}
        var pending = origFetch.apply(this, arguments);
        if (String(url).indexOf('ssp.mantis.marketing') !== -1 && pending && pending.then) {
          pending.then(function(resp) {
            try {
              resp.clone().json().then(captureSspPayload).catch(function() {});
            } catch (eClone) {}
          }).catch(function() {});
        }
        return pending;
      };
    }
    if (window.XMLHttpRequest) {
      var origSend = XMLHttpRequest.prototype.send;
      XMLHttpRequest.prototype.send = function(body) {
        this.addEventListener('load', function() {
          try {
            var u = this.responseURL || '';
            if (u.indexOf('ssp.mantis.marketing') === -1) return;
            captureSspPayload(JSON.parse(this.responseText || '{}'));
          } catch (eXhr) {}
        });
        return origSend.apply(this, arguments);
      };
    }
  }
  function paintFromSsp(zoneList) {
    // cssOnly blocks interactive Path1/2 taps. AllowSspPaint (MITM inject) still
    // fetches SSP + fires served/viewed pixels so Mantis impressions can bill
    // when CDP /json is dead. Path3 sets cssOnly=false for clickable ads.
    if (window.__pharmflowCssOnly && !window.__pharmflowAllowSspPaint) return;
    var zones = zoneList && zoneList.length ? zoneList : ['zone-one','zone-two','zone-five','zone-nine','zone-twelve'];
    var widths = {};
    zones.forEach(function(z) { widths[z] = 300; });
    var body = JSON.stringify({
      url: location.href.split('#')[0],
      is_iframe: false,
      demo: false,
      last_viewed: {},
      property_id: PROPERTY_ID,
      zones: zones,
      widths: widths,
      timezone: 0
    });
    try {
      fetch(SSP, {
        method: 'POST',
        headers: {'Content-Type': 'text/plain'},
        body: body,
        credentials: 'omit',
        mode: 'cors'
      }).then(function(r) { return r.json(); }).then(function(data) {
        if (window.__pharmflowCssOnly && !window.__pharmflowAllowSspPaint) return;
        var ads = (data && data.ads) || [];
        var painted = 0;
        ads.forEach(function(ad) {
          if (paintAd(ad)) painted += 1;
          else {
            firePixels(ad && ad.served_pixels);
            firePixels(ad && ad.viewed_pixels);
          }
        });
        reportViewed(ads);
        window.__pharmflowMantisPainted = painted;
        fixSlotCss();
      }).catch(function() {});
    } catch (e) {}
  }
  function refreshZones(zones) {
    if (window.__pharmflowCssOnly && !window.__pharmflowAllowSspPaint) {
      fixSlotCss();
      return;
    }
    if (window.__pharmflowCssOnly && window.__pharmflowAllowSspPaint) {
      fixSlotCss();
      // Give native mantis.js first crack (billable); host/SSP paint is fallback.
      if (typeof mantis !== 'undefined' && zones) {
        try {
          zones.forEach(function(z) {
            try { mantis.push(['display', 'refresh', z]); } catch (e1) {}
            try { mantis.push(['display', 'refresh', z + '-']); } catch (e2) {}
          });
        } catch (e3) {}
        setTimeout(function() { paintFromSsp(zones); }, 2500);
        return;
      }
      paintFromSsp(zones);
      return;
    }
    if (!zones || typeof mantis === 'undefined') {
      paintFromSsp(zones);
      return;
    }
    setTimeout(function() {
      zones.forEach(function(z) {
        try { mantis.push(['display', 'refresh', z]); } catch (e) {}
        try { mantis.push(['display', 'refresh', z + '-']); } catch (e) {}
      });
      // Delayed paintFromSsp only fills still-empty zones (see paintAd skip).
      setTimeout(function() { paintFromSsp(zones); }, 2200);
    }, 40);
  }
  if (typeof switchScreen === 'function' && !window.__pharmflowSwitchWrapped) {
    window.__pharmflowSwitchWrapped = true;
    var prevSwitch = switchScreen;
    switchScreen = function(screenName) {
      prevSwitch.apply(this, arguments);
      if (screenName === 'settings' && typeof initializeQRCode === 'function') {
        setTimeout(initializeQRCode, 100);
      }
      fixSlotCss();
      refreshZones(fixedZones[screenName] || fixedZones.home);
    };
  }
  // Default: CSS-only makes a painted Path1/2 creative non-interactive.
  // Path3 / ad-fill sets window.__pharmflowCssOnly=false before enabling ad clicks.
  // MITM sets __pharmflowAllowSspPaint so impression pixels still fire without clicks.
  if (typeof window.__pharmflowCssOnly === 'undefined') {
    window.__pharmflowCssOnly = true;
  }
  fixSlotCss();
  if (!window.__pharmflowCssOnly || window.__pharmflowAllowSspPaint) {
    refreshZones(fixedZones.home);
    paintFromSsp(fixedZones.home.concat(fixedZones.timer, fixedZones.stats, fixedZones.glass, fixedZones.settings));
  }
  if (!window.__pharmflowCoolAdTimer) {
    window.__pharmflowCoolAdTimer = setInterval(function() {
      try {
        // Path1/2 (cssOnly): keep re-arming pointer-events:none — native Mantis
        // iframes/SDK nodes spawn after first paint and otherwise steal taps → clicks.
        if (window.__pharmflowCssOnly) {
          fixSlotCss();
          return;
        }
        var modeEl = document.getElementById('timer-mode');
        if (!modeEl || !modeEl.textContent || modeEl.textContent.indexOf('Cool') < 0) return;
        var videoAd = document.getElementById('cooldown-video-ad');
        if (!videoAd || videoAd.style.display !== 'none') return;
        videoAd.style.display = 'block';
        if (!videoAd.querySelector('[data-mantis-zone]')) {
          videoAd.innerHTML = '<div data-mantis-zone="zone-two"></div>';
        }
        if (typeof mantis !== 'undefined') {
          mantis.push(['display', 'refresh', 'zone-two']);
        }
        paintFromSsp(['zone-two', 'zone-three']);
      } catch (e) {}
    }, 600);
  }
  return true;
})();
""".strip()


def patch_enabled_from_env() -> bool:
    raw = os.environ.get("PHARMFLOW_DABFLOW_MANTIS_PATCH", "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return True


def patch_enabled_from_prefs(prefs: dict | None) -> bool | None:
    if not isinstance(prefs, dict):
        return None
    if "dabflow_mantis_patch" in prefs:
        return bool(prefs.get("dabflow_mantis_patch"))
    return None


def is_dabflow_url(url: str) -> bool:
    try:
        from urllib.parse import urlparse

        host = urlparse(url).netloc.split(":")[0]
        return bool(DABFLOW_HOST_RE.search(host))
    except Exception:
        return "getdabflow.app" in (url or "").lower()


def host_cdp_port(phone_idx: int) -> int:
    return DEVICE_CDP_PORT + max(0, min(31, int(phone_idx)))


def cdp_debug_flag(port: int = DEVICE_CDP_PORT) -> str:
    return f"--remote-debugging-port={port}"


def cdp_abstract_sockets(browser_package: str | None = None) -> tuple[str, ...]:
    """Abstract DevTools socket names for the foreground Chromium-family browser.

    Opera binds ``@com.opera.browser.devtools`` — NOT ``@chrome_devtools_remote``.
    Forwarding Opera (or a dead Chromium) to chrome_devtools_remote yields
    ``Remote end closed connection without response`` on /json.
    Chromium/Brave may also expose ``@chrome_devtools_remote_<pid>``.
    """
    pkg = (browser_package or "").strip().lower()
    if pkg == "com.opera.browser" or pkg.endswith(".opera.browser"):
        return ("com.opera.browser.devtools", "chrome_devtools_remote")
    if pkg == "com.brave.browser" or "brave" in pkg:
        return ("chrome_devtools_remote", "brave_devtools_remote")
    if pkg:
        return ("chrome_devtools_remote",)
    # Unknown package: try Chromium first, then Opera (farm includes both).
    return ("chrome_devtools_remote", "com.opera.browser.devtools", "brave_devtools_remote")


def _device_forward_targets(browser_package: str | None = None) -> list[str]:
    """Default ``adb forward`` target order: abstract DevTools sockets first, then the
    device tcp:DEVICE_CDP_PORT fallback. Modern Chrome binds DevTools to the abstract
    socket, not tcp:9222 — see ensure_adb_forward, which applies this same ordering but
    reprioritizes by what's actually live on the device via /proc/net/unix.
    """
    targets = [f"localabstract:{name}" for name in cdp_abstract_sockets(browser_package)]
    targets.append(f"tcp:{DEVICE_CDP_PORT}")
    return targets


def _list_unix_devtools_sockets(adb: AdbWrapper, serial: str) -> list[str]:
    """Live ``@…devtools…`` abstract names from /proc/net/unix (pid-scoped too)."""
    try:
        out = adb.shell("cat /proc/net/unix", serial=serial, timeout=6.0).stdout or ""
    except Exception:
        return []
    found: list[str] = []
    for line in out.splitlines():
        if "devtools" not in line.lower():
            continue
        if "@" not in line:
            continue
        name = line.rsplit("@", 1)[-1].strip()
        if name and name not in found:
            found.append(name)
    return found


def _probe_cdp_json(host_port: int, *, timeout: float = 3.0) -> list[dict[str, Any]] | None:
    """Return target list if /json responds; None on connection/parse failure."""
    url = f"http://127.0.0.1:{host_port}/json"
    req = urllib.request.Request(url, headers={"User-Agent": "PharmFlow-cdp/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    if isinstance(data, list):
        return [t for t in data if isinstance(t, dict)]
    return None


def ensure_adb_forward(
    adb: AdbWrapper,
    serial: str,
    phone_idx: int,
    *,
    browser_package: str | None = None,
    wait_sec: float = 6.0,
) -> int:
    """Forward host CDP port to the browser's abstract DevTools socket (MuMu trick door).

    tcp:9222 is usually dead on MuMu user builds. Chromium/Brave expose
    ``@chrome_devtools_remote``; Opera uses ``@com.opera.browser.devtools``.
    We wait for the socket, try package-specific abstracts, verify /json, then
    fall back to device tcp:9222.
    """
    host_port = host_cdp_port(phone_idx)
    preferred = cdp_abstract_sockets(browser_package)
    deadline = time.monotonic() + max(0.0, wait_sec)
    last_err = "no socket"
    while True:
        live = _list_unix_devtools_sockets(adb, serial)
        # Prefer live sockets that match the package, then any live DevTools, then hints.
        ordered: list[str] = []
        for name in preferred:
            if name in live and name not in ordered:
                ordered.append(name)
        for name in live:
            # Pid-scoped chrome_devtools_remote_12345 — often the only live door.
            if name.startswith("chrome_devtools_remote") and name not in ordered:
                ordered.append(name)
            elif name not in ordered and "devtools" in name:
                # Skip other browsers' sockets when we know the package.
                pkg = (browser_package or "").strip().lower()
                if pkg and "opera" in pkg and "opera" not in name:
                    continue
                if pkg and "brave" in pkg and "opera" in name:
                    continue
                if pkg and "chromium" in pkg and "opera" in name:
                    continue
                ordered.append(name)
        for name in preferred:
            if name not in ordered:
                ordered.append(name)
        try_names = ordered or list(preferred)
        for name in try_names:
            adb.run("forward", "--remove", f"tcp:{host_port}", serial=serial, timeout=8.0)
            result = adb.run(
                "forward",
                f"tcp:{host_port}",
                f"localabstract:{name}",
                serial=serial,
                timeout=8.0,
            )
            if not result.ok:
                last_err = (result.stderr or result.stdout or f"forward {name} failed").strip()
                continue
            targets = _probe_cdp_json(host_port)
            if targets is not None:
                if name != "chrome_devtools_remote":
                    logger.info(
                        "CDP forward serial=%s via=@%s port=%s tabs=%d",
                        serial,
                        name,
                        host_port,
                        len(targets),
                    )
                return host_port
            last_err = f"@{name} forward ok but /json closed/empty"
        # Fallback: classic TCP debugging port from chrome-command-line.
        adb.run("forward", "--remove", f"tcp:{host_port}", serial=serial, timeout=8.0)
        result2 = adb.run(
            "forward",
            f"tcp:{host_port}",
            f"tcp:{DEVICE_CDP_PORT}",
            serial=serial,
            timeout=8.0,
        )
        if result2.ok:
            targets = _probe_cdp_json(host_port)
            if targets is not None:
                logger.info(
                    "CDP forward serial=%s via=tcp:%s port=%s tabs=%d",
                    serial,
                    DEVICE_CDP_PORT,
                    host_port,
                    len(targets),
                )
                return host_port
            last_err = f"tcp:{DEVICE_CDP_PORT} forward ok but /json closed"
        else:
            last_err = (
                "adb forward failed (abstract + tcp): "
                f"{last_err} | "
                f"{(result2.stderr or result2.stdout or '').strip()}"
            )
        if time.monotonic() >= deadline:
            break
        time.sleep(0.45)
    raise RuntimeError(last_err)


def _list_cdp_targets(host_port: int) -> list[dict[str, Any]]:
    targets = _probe_cdp_json(host_port, timeout=5.0)
    if targets is None:
        raise urllib.error.URLError("Remote end closed connection without response")
    return targets


def _pick_dabflow_target(targets: list[dict[str, Any]]) -> dict[str, Any] | None:
    for target in targets:
        u = str(target.get("url", ""))
        if "getdabflow.app" in u.lower() and target.get("webSocketDebuggerUrl"):
            return target
    for target in targets:
        if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
            return target
    return None


async def _cdp_evaluate(ws_url: str, expression: str, *, timeout_sec: float = 8) -> dict:
    import websockets

    msg = {
        "id": 1,
        "method": "Runtime.evaluate",
        "params": {"expression": expression, "returnByValue": True, "awaitPromise": False},
    }
    async with websockets.connect(ws_url, open_timeout=timeout_sec, close_timeout=2) as ws:
        await ws.send(json.dumps(msg))
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout_sec)
            payload = json.loads(raw)
            if payload.get("id") == 1:
                return payload
    return {"error": "timeout waiting for CDP response"}


async def _cdp_call(
    ws_url: str,
    method: str,
    params: dict[str, Any],
    *,
    msg_id: int = 1,
    timeout_sec: float = 8,
) -> dict[str, Any]:
    import websockets

    msg = {"id": msg_id, "method": method, "params": params}
    async with websockets.connect(ws_url, open_timeout=timeout_sec, close_timeout=2) as ws:
        await ws.send(json.dumps(msg))
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout_sec)
            payload = json.loads(raw)
            if payload.get("id") == msg_id:
                return payload
    return {"error": f"timeout waiting for CDP {method}"}


def apply_cdp_user_agent_override(
    host_port: int,
    profile: Any,
    *,
    retries: int = 6,
    retry_delay_sec: float = 0.55,
    adb: AdbWrapper | None = None,
    serial: str | None = None,
    phone_idx: int | None = None,
    browser_package: str | None = None,
) -> dict[str, Any]:
    """Force UA + Client Hints (Sec-CH-UA-Model) to match the scrambled profile.

    chrome-command-line ``--user-agent`` alone does not rewrite Client Hints;
    Chromium keeps model from getprop (sticky MuMu PhoneProp until cold boot).
    Cloudflare device analytics key off CH-UA-Model / UA-CH — this CDP call is
    what makes each sequence look like a different phone on the wire.
    """
    if profile is None:
        return {"ok": False, "error": "no profile"}
    ua = getattr(profile, "user_agent", "") or ""
    model = getattr(profile, "model", "") or ""
    if not ua or not model:
        return {"ok": False, "error": "profile missing ua/model"}
    meta_fn = getattr(profile, "user_agent_metadata", None)
    metadata = meta_fn() if callable(meta_fn) else {}
    if not isinstance(metadata, dict) or not metadata:
        metadata = {
            "brands": [{"brand": "Chromium", "version": "120"}, {"brand": "Not=A?Brand", "version": "24"}],
            "fullVersionList": [
                {"brand": "Chromium", "version": "120.0.6099.144"},
                {"brand": "Not=A?Brand", "version": "10.0.0.0"},
            ],
            "platform": "Android",
            "platformVersion": "13.0.0",
            "architecture": "",
            "model": model,
            "mobile": True,
            "bitness": "",
            "wow64": False,
        }
    params = {
        "userAgent": ua,
        "acceptLanguage": "en-US,en",
        "platform": "Linux armv8l",
        "userAgentMetadata": metadata,
    }
    last_err = "no target"
    port = int(host_port)
    for attempt in range(max(1, retries)):
        try:
            # Re-bind DevTools each attempt — browser may have relaunched after
            # FRE/SSL/force-stop, leaving a stale adb forward that closes /json.
            if adb is not None and serial and phone_idx is not None:
                try:
                    port = ensure_adb_forward(
                        adb,
                        serial,
                        int(phone_idx),
                        browser_package=browser_package,
                        wait_sec=2.0 if attempt else 3.0,
                    )
                except Exception as fwd_exc:
                    last_err = str(fwd_exc)
                    if attempt + 1 < retries:
                        time.sleep(retry_delay_sec)
                    continue
            targets = _list_cdp_targets(port)
            target = _pick_dabflow_target(targets)
            if not target:
                last_err = (
                    f"no CDP page target (attempt {attempt + 1}, "
                    f"{len(targets)} tabs, pkg={browser_package or '?'})"
                )
                if attempt + 1 < retries:
                    time.sleep(retry_delay_sec)
                continue
            ws_url = str(target["webSocketDebuggerUrl"])
            result = asyncio.run(
                _cdp_call(ws_url, "Emulation.setUserAgentOverride", params)
            )
            if isinstance(result.get("error"), str):
                last_err = str(result.get("error"))
                if attempt + 1 < retries:
                    time.sleep(retry_delay_sec)
                continue
            if isinstance(result.get("error"), dict):
                last_err = str(result.get("error"))
                if attempt + 1 < retries:
                    time.sleep(retry_delay_sec)
                continue
            logger.info(
                "CDP UA/ClientHints override model=%s port=%s tab=%s",
                model,
                port,
                str(target.get("url", ""))[:60],
            )
            return {
                "ok": True,
                "model": model,
                "target_url": target.get("url"),
                "via": "cdp_ua_override",
                "host_port": port,
            }
        except Exception as exc:
            last_err = str(exc)
            if attempt + 1 < retries:
                time.sleep(retry_delay_sec)
    return {"ok": False, "error": last_err, "model": model}


def inject_patch(
    host_port: int,
    *,
    retries: int = 5,
    retry_delay_sec: float = 0.55,
    paint_creatives: bool = False,
    interactive: bool | None = None,
) -> dict[str, Any]:
    """Inject PATCH_JS. Creatives only when paint_creatives=True.

    interactive defaults to paint_creatives when None. Path3 sets interactive=True
    so creatives receive clicks; Path1/2 may show creatives with pointer-events:none.
    """
    if interactive is None:
        interactive = paint_creatives
    ensure_ssp_cache_warm()
    ads: list[dict[str, Any]] = []
    if paint_creatives:
        try:
            # Host-paint paying only — never embed house fallback over native SDK.
            ads = prefetch_ssp_ads_prefer_paying(
                attempts=8, delay_s=0.35, allow_house_fallback=False
            )
        except Exception:
            ads = [
                a
                for a in (get_cached_ssp_ads(allow_stale=True) or [])
                if str(a.get("click_url") or "").startswith("http")
                and not is_mantis_house_bot_click_url(str(a.get("click_url") or ""))
            ]
            if not ads:
                raw = prefetch_ssp_ads(force=True) or []
                ads = filter_ssp_ads_prefer_paying(raw, allow_house_fallback=False)
        if ssp_ads_paying_count(ads) > 0:
            # Do not fire served/viewed pixels from the host. That is host-IP
            # egress: Mantis dedupes them and the click cannot bind. The phone
            # must fire the pixel through its own exit.
            logger.debug(
                "skip host pixel relay n=%s (phone exit must fire the impression)",
                ssp_ads_paying_count(ads),
            )
    css_only = not interactive if paint_creatives else True
    css_flag = "true" if css_only else "false"
    last_err = "no target"
    for attempt in range(max(1, retries)):
        try:
            targets = _list_cdp_targets(host_port)
            target = _pick_dabflow_target(targets)
            if not target:
                last_err = f"no CDP page target (attempt {attempt + 1}, {len(targets)} tabs)"
                if attempt + 1 < retries:
                    time.sleep(retry_delay_sec)
                continue
            ws_url = str(target["webSocketDebuggerUrl"])
            if paint_creatives and ads:
                expression = (
                    f"window.__pharmflowCssOnly={css_flag};\n"
                    "window.__pharmflowAllowSspPaint=true;\n"
                    "window.__pharmflowMantisPainted=0;\n"
                    + PATCH_JS
                    + "\n"
                    + _ssp_paint_expression(ads, empty_only=True)
                )
            elif paint_creatives:
                expression = (
                    f"window.__pharmflowCssOnly={css_flag};\n"
                    "window.__pharmflowAllowSspPaint=true;\n"
                    "window.__pharmflowMantisPainted=0;\n"
                    + PATCH_JS
                )
            else:
                expression = "window.__pharmflowCssOnly=true;\n" + PATCH_JS
            result = asyncio.run(_cdp_evaluate(ws_url, expression))
            err = (result.get("result") or {}).get("exceptionDetails")
            if err:
                return {"ok": False, "error": str(err), "target_url": target.get("url")}
            val = (result.get("result") or {}).get("result", {}).get("value")
            painted = 0
            if paint_creatives and isinstance(val, (int, float)):
                painted = int(val)
            elif paint_creatives and ads:
                painted = len(ads)
            if paint_creatives:
                ensure_ssp_cache_warm()
            return {
                "ok": bool(val) or painted > 0 or not paint_creatives,
                "target_url": target.get("url"),
                "cdp": result,
                "ssp_paint": {
                    "ok": painted > 0 if paint_creatives else True,
                    "painted": painted,
                    "cached": True,
                    "css_only": css_only,
                    "interactive": interactive,
                    "paying": ssp_ads_paying_count(ads) if paint_creatives else 0,
                    "zones": [a.get("zone_id") for a in ads] if paint_creatives else [],
                },
            }
        except (urllib.error.URLError, OSError, asyncio.TimeoutError) as exc:
            last_err = str(exc)
            if attempt + 1 < retries:
                time.sleep(retry_delay_sec)
    return {"ok": False, "error": last_err}


def _ssp_paint_expression(
    ads: list[dict[str, Any]],
    *,
    empty_only: bool = False,
) -> str:
    """Build JS that paints host-fetched SSP creatives into Mantis zones (avoids CORS).

    When ``empty_only`` is True, skip zones that already have a native Mantis
    iframe/img so we do not wipe billable SDK fills with house host-paint.
    """
    # Prefer paying; if SSP is house-only, still embed house creatives so empty
    # zones get a visible bottom banner (clicks stay prefer-paying elsewhere).
    prefer = filter_ssp_ads_prefer_paying(ads, allow_house_fallback=True)
    if not prefer:
        return "0;"
    # Guarantee a bottom tester paint target when inventory has no tester row.
    if not any(str(a.get("zone_id") or "") == "tester" for a in prefer):
        fat = None
        for a in prefer:
            if not a or not a.get("creative_url"):
                continue
            h = int(a.get("creative_height") or 0)
            if h >= 200:
                fat = a
                break
        if fat is None:
            fat = next((a for a in prefer if a and a.get("creative_url")), None)
        if fat is not None:
            prefer = list(prefer) + [
                {
                    **fat,
                    "zone_id": "tester",
                    "creative_height": max(int(fat.get("creative_height") or 0), 250),
                    "creative_width": int(fat.get("creative_width") or 300),
                }
            ]
    payload = json.dumps(prefer, separators=(",", ":"))
    empty_flag = "true" if empty_only else "false"
    return f"""
(function() {{
  var ads = {payload};
  var emptyOnly = {empty_flag};
  // Kick creative downloads immediately (before DOM work) so images race the page paint.
  ads.forEach(function(ad) {{
    if (!ad || !ad.creative_url) return;
    try {{ var pre = new Image(); pre.decoding = 'async'; pre.src = ad.creative_url; }} catch (e) {{}}
  }});
  function ensureBottomTesterZone() {{
    var wrap = document.getElementById('pharmflow-bottom-ad');
    var zEl = wrap && wrap.querySelector('[data-mantis-zone=\"tester\"]');
    if (wrap && zEl) {{
      wrap.style.cssText = 'display:block!important;visibility:visible!important;opacity:1!important;'
        + 'min-height:250px;width:100%;max-width:320px;margin:0.75rem auto 5.5rem;text-align:center;'
        + 'overflow:visible!important;position:relative;z-index:20;';
      return zEl;
    }}
    wrap = document.createElement('div');
    wrap.id = 'pharmflow-bottom-ad';
    wrap.className = 'ad-container pharmflow-bottom-ad';
    wrap.setAttribute('data-pharmflow-bottom-host', '1');
    wrap.style.cssText = 'display:block!important;visibility:visible!important;opacity:1!important;'
      + 'min-height:250px;width:100%;max-width:320px;margin:0.75rem auto 5.5rem;text-align:center;'
      + 'overflow:visible!important;position:relative;z-index:20;';
    zEl = document.createElement('div');
    zEl.setAttribute('data-mantis-zone', 'tester');
    zEl.setAttribute('data-pharmflow-bottom', '1');
    wrap.appendChild(zEl);
    var rec = document.getElementById('recommended');
    var anchor = rec && (rec.parentElement || rec);
    var main = document.querySelector('main') || document.getElementById('app') || document.body;
    if (anchor && anchor.parentNode) {{
      anchor.parentNode.insertBefore(wrap, anchor.nextSibling);
    }} else {{
      var btn = document.getElementById('start-dab-btn');
      if (btn && btn.parentNode) {{
        btn.parentNode.insertBefore(wrap, btn.nextSibling);
      }} else {{
        main.appendChild(wrap);
      }}
    }}
    return zEl;
  }}
  function findZone(zoneId) {{
    if (!zoneId) return null;
    if (zoneId === 'tester') return ensureBottomTesterZone();
    return document.querySelector('[data-mantis-zone=\"' + zoneId + '\"]')
      || document.querySelector('[data-mantis-zone=\"' + zoneId + '-\"]')
      || document.querySelector('[data-mantis-zone^=\"' + zoneId + '\"]');
  }}
  function zoneAlreadyFilled(z) {{
    if (!z) return false;
    try {{
      if (z.querySelector('iframe')) return true;
      if (z.querySelector('img[src*=\"mantis\"], img[src*=\"static.mantis\"]')) return true;
      if (z.querySelector('.pharmflow-mantis-creative')) return true;
      var html = (z.innerHTML || '').trim();
      if (html.length > 40) return true;
    }} catch (e) {{}}
    return false;
  }}
  function firePixels(urls) {{
    (urls || []).forEach(function(u) {{
      try {{ var i = new Image(); i.src = u; }} catch (e) {{}}
    }});
  }}
  var painted = 0;
  // Prefer a 300x250 creative for bottom tester when SSP only returns a skinny 320x50.
  var fat = null;
  ads.forEach(function(ad) {{
    if (!ad || !ad.creative_url) return;
    var h = ad.creative_height || 0;
    if (h >= 200 && (!fat || ad.zone_id === 'zone-one')) fat = ad;
  }});
  ads.forEach(function(ad) {{
    if (!ad || !ad.zone_id || !ad.creative_url) return;
    var paintAd = ad;
    if (ad.zone_id === 'tester' && fat && (ad.creative_height || 0) < 100) {{
      paintAd = Object.assign({{}}, ad, {{
        creative_url: fat.creative_url,
        creative_width: fat.creative_width || 300,
        creative_height: fat.creative_height || 250,
        click_url: fat.click_url || ad.click_url,
        served_pixels: (ad.served_pixels || []).concat(fat.served_pixels || []),
        viewed_pixels: (ad.viewed_pixels || []).concat(fat.viewed_pixels || [])
      }});
    }}
    var z = findZone(paintAd.zone_id);
    if (!z) return;
    if (emptyOnly && zoneAlreadyFilled(z)) return;
    var slot = z.closest('.ad-container, [id^=\"ad-slot-\"]') || z.parentElement;
    [z, slot].forEach(function(el) {{
      if (!el || !el.style) return;
      el.style.minWidth = '300px';
      el.style.width = '100%';
      el.style.maxWidth = '100%';
      el.style.minHeight = (paintAd.creative_height || 250) + 'px';
      el.style.display = 'block';
      el.style.visibility = 'visible';
      el.style.opacity = '1';
      el.style.overflow = 'visible';
    }});
    var w = paintAd.creative_width || 300;
    var h = paintAd.creative_height || 250;
    var href = paintAd.click_url || '#';
    z.innerHTML = '<a class=\"pharmflow-mantis-creative\" href=\"' + href
      + '\" target=\"_blank\" rel=\"noopener noreferrer\" aria-label=\"adsbymantis\"'
      + ' data-mantis-zone=\"' + paintAd.zone_id + '\"'
      + ' style=\"display:block;width:100%;text-align:center;\">'
      + '<img src=\"' + paintAd.creative_url + '\" width=\"' + w + '\" height=\"' + h
      + '\" alt=\"sponsored\" loading=\"eager\" decoding=\"async\" style=\"max-width:100%;height:auto;display:inline-block;margin:0 auto;\">'
      + '</a>';
    var link = z.querySelector('.pharmflow-mantis-creative');
    if (link) {{
      var interactive = window.__pharmflowCssOnly === false;
      link.style.pointerEvents = interactive ? 'auto' : 'none';
      link.style.cursor = interactive ? 'pointer' : 'default';
      if (!interactive) {{
        link.setAttribute('aria-disabled', 'true');
        link.setAttribute('tabindex', '-1');
      }}
    }}
    firePixels(paintAd.served_pixels);
    firePixels(paintAd.viewed_pixels);
    // Do not scrollIntoView — steals Path1/2 selection viewport.
    painted += 1;
  }});
  if (painted > 0) {{
    window.__pharmflowMantisPainted = (window.__pharmflowMantisPainted || 0) + painted;
  }}
  return painted;
}})();
""".strip()


def _normalize_ssp_ads_payload(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    ads_out: list[dict[str, Any]] = []
    for ad in (data or {}).get("ads") or []:
        if not isinstance(ad, dict):
            continue
        zone = str(ad.get("zone_id") or "").strip()
        creative = str(ad.get("creative_url") or "").strip()
        if not zone or not creative:
            continue
        ads_out.append(
            {
                "zone_id": zone,
                "creative_url": creative,
                "click_url": str(ad.get("click_url") or "").strip(),
                "creative_width": int(ad.get("creative_width") or 300),
                "creative_height": int(ad.get("creative_height") or 250),
                "served_pixels": list(ad.get("served_pixels") or []),
                "viewed_pixels": list(ad.get("viewed_pixels") or []),
            }
        )
    return ads_out


def _ssp_display_body(
    zones: list[str] | tuple[str, ...] | None,
    *,
    timezone: int = 0,
) -> dict[str, Any]:
    from automation.dabflow_mantis_ad_urls import DABFLOW_PAGE_URL, MANTIS_PROPERTY_ID

    want = list(zones or ALL_MANTIS_ZONES)
    return {
        "url": DABFLOW_PAGE_URL,
        "is_iframe": False,
        "demo": False,
        "last_viewed": {},
        "property_id": MANTIS_PROPERTY_ID,
        "zones": want,
        "widths": {z: 300 for z in want},
        "timezone": int(timezone),
    }


def fetch_ssp_display_ads(
    zones: list[str] | tuple[str, ...] | None = None,
    *,
    timeout: float = 6.0,
    timezone: int = 0,
) -> list[dict[str, Any]]:
    """Host-side SSP display fetch — full creative payloads (not just landing URLs)."""
    from automation.dabflow_mantis_ad_urls import MANTIS_SSP_DISPLAY

    body = _ssp_display_body(zones, timezone=timezone)
    req = urllib.request.Request(
        MANTIS_SSP_DISPLAY,
        data=json.dumps(body).encode("utf-8"),
        headers={**_ssp_browser_headers(), "Content-Type": "text/plain"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    ads_out = _normalize_ssp_ads_payload(data if isinstance(data, dict) else {})
    if ads_out:
        _store_ssp_ads(ads_out)
    return ads_out


def fetch_ssp_display_ads_via_tor(
    *,
    tor_http_port: int,
    zones: list[str] | tuple[str, ...] | None = None,
    timezone: int = 0,
    timeout: float = 12.0,
) -> list[dict[str, Any]]:
    """SSP /display via Tor HTTPTunnel CONNECT — same exit path phones use."""
    host = "ssp.mantis.marketing"
    body = json.dumps(_ssp_display_body(zones, timezone=timezone)).encode("utf-8")
    raw = socket.create_connection(("127.0.0.1", int(tor_http_port)), timeout)
    try:
        raw.sendall(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n".encode())
        hdr = b""
        while b"\r\n\r\n" not in hdr:
            chunk = raw.recv(1)
            if not chunk:
                break
            hdr += chunk
            if len(hdr) > 4096:
                break
        if b"200" not in hdr.split(b"\r\n", 1)[0]:
            raise OSError(f"Tor CONNECT failed port={tor_http_port}: {hdr[:120]!r}")
        ctx = ssl.create_default_context()
        tls = ctx.wrap_socket(raw, server_hostname=host)
        raw = None  # ownership transferred
        tor_headers = _ssp_browser_headers()
        header_lines = [f"POST /display HTTP/1.1", f"Host: {host}", "Content-Type: text/plain"]
        for hk, hv in tor_headers.items():
            header_lines.append(f"{hk}: {hv}")
        header_lines += [
            f"Content-Length: {len(body)}",
            "Connection: close",
            "",
            "",
        ]
        req = "\r\n".join(header_lines).encode() + body
        tls.sendall(req)
        data = b""
        while True:
            chunk = tls.recv(8192)
            if not chunk:
                break
            data += chunk
        tls.close()
    finally:
        if raw is not None:
            try:
                raw.close()
            except OSError:
                pass
    _, _, payload = data.partition(b"\r\n\r\n")
    text = payload.decode("utf-8", "replace")
    idx = text.find("{")
    if idx < 0:
        raise OSError(f"no SSP JSON via tor:{tor_http_port}")
    try:
        parsed = json.loads(text[idx:])
    except json.JSONDecodeError:
        # Chunked responses: stitch non-hex lines after first `{`.
        buf: list[str] = []
        for line in text.split("\r\n"):
            if not line:
                continue
            try:
                int(line, 16)
                continue
            except ValueError:
                buf.append(line)
        joined = "".join(buf)
        jdx = joined.find("{")
        if jdx < 0:
            raise
        parsed = json.loads(joined[jdx:])
    ads_out = _normalize_ssp_ads_payload(parsed if isinstance(parsed, dict) else {})
    if ads_out:
        _store_ssp_ads(ads_out)
    return ads_out


def paint_ssp_creatives_via_cdp(ws_url: str) -> dict[str, Any]:
    """Paint creatives into page zones via CDP using host SSP cache (no browser CORS)."""
    ensure_ssp_cache_warm()
    ads = get_cached_ssp_ads(allow_stale=True)
    if not ads:
        try:
            ads = prefetch_ssp_ads(force=True)
        except Exception as exc:
            logger.warning("SSP display fetch failed: %s", exc)
            return {"ok": False, "error": str(exc), "painted": 0}
    if not ads:
        return {"ok": False, "error": "no ssp ads", "painted": 0}
    try:
        enable = "window.__pharmflowCssOnly=false;\nwindow.__pharmflowMantisPainted=0;\n"
        result = asyncio.run(_cdp_evaluate(ws_url, enable + _ssp_paint_expression(ads)))
        painted = (result.get("result") or {}).get("result", {}).get("value")
        ok = bool(painted)
        logger.info(
            "SSP creatives painted via CDP count=%s cache_age=%.1fs",
            painted,
            ssp_cache_age_s(),
        )
        return {
            "ok": ok,
            "painted": painted,
            "zones": [a["zone_id"] for a in ads],
            "cdp": result,
            "cached": True,
        }
    except Exception as exc:
        logger.warning("SSP CDP paint failed: %s", exc)
        return {"ok": False, "error": str(exc), "painted": 0}


def _fresh_paying_fill_ads() -> list[dict[str, Any]]:
    """Shared fill only inside the freshness window. Stale file tokens pay $0."""
    if not paying_fill_file_fresh():
        return []
    return _ingest_paying_fill_file() or []


def _ads_just_prefetched() -> list[dict[str, Any]]:
    """Ads a live fetch just stored. Never the stale ``allow_stale`` cache.

    ``prefetch_ssp_ads`` / ``prefetch_ssp_ads_prefer_paying`` return
    ``get_cached_ssp_ads(allow_stale=True)`` when the live probe misses. Those
    bi/bt values are bound to a dead impression: HTTP 200, $0. Callers that
    open a URL must ignore that return and read only the TTL-fresh cache.
    """
    return get_cached_ssp_ads(allow_stale=False) or []


def click_url_for_zone(
    zone: str,
    *,
    allow_any: bool = True,
    prefer_paying: bool = True,
    force_refresh: bool = False,
) -> str | None:
    """Return a live Mantis SSP click_url (tracking redirect), never a landing page.

    When ``prefer_paying`` is set, skip house/bot creatives and any clicked URL
    without a live bi+bt token. A stale host cache or a synthetic wrap
    (``bi=pharmflow-fallback`` / no ``bt``) returns HTTP 200 and pays $0.
    """
    want = (zone or "").strip()
    ads: list[dict[str, Any]] = []
    # Token freshness: Mantis click URLs are bound to the impression tokens
    # (bi/bt) of the fill that produced them. Never choose a URL from
    # get_cached_ssp_ads(allow_stale=True). Past the TTL, prefetch; if that
    # returns nothing, leave ads empty rather than replaying a dead token.
    cached_now = get_cached_ssp_ads(allow_stale=False)
    if force_refresh or not cached_now:
        try:
            prefetch_ssp_ads(force=True)
        except Exception:
            pass
        ads = _ads_just_prefetched()
    else:
        ads = cached_now
    if prefer_paying and ssp_ads_paying_count(ads) == 0:
        file_ads = _fresh_paying_fill_ads()
        if ssp_ads_paying_count(file_ads) > 0:
            ads = file_ads

    def _pick(from_ads: list[dict[str, Any]], *, paying_only: bool) -> str | None:
        if want:
            for ad in from_ads:
                if str(ad.get("zone_id") or "").strip() != want:
                    continue
                click = str(ad.get("click_url") or "").strip()
                if not click.startswith("http"):
                    continue
                if paying_only and not has_live_click_token(click):
                    continue
                return click
        if allow_any:
            for ad in from_ads:
                click = str(ad.get("click_url") or "").strip()
                if not click.startswith("http"):
                    continue
                if paying_only and not has_live_click_token(click):
                    continue
                return click
        return None

    if prefer_paying:
        hit = _pick(ads, paying_only=True)
        if hit:
            _clear_ssp_house_only()
            return hit
        # Cache may be house-only — burst-refresh for advertiser fill.
        # Skip thrash when a recent refresh already proved inventory is house-only
        # unless caller forced refresh (Path3 open always force_refresh).
        if force_refresh or not ssp_recently_house_only():
            try:
                prefetch_ssp_ads_prefer_paying(
                    attempts=6 if force_refresh else 3,
                    delay_s=0.3,
                    allow_house_fallback=False,
                )
            except Exception:
                pass
            # Burst falls back to allow_stale=True when every probe misses.
            # Do not open that return — only a live store or a fresh fill file.
            ads = _ads_just_prefetched()
            if ssp_ads_paying_count(ads) == 0:
                file_ads = _fresh_paying_fill_ads()
                if ssp_ads_paying_count(file_ads) > 0:
                    ads = file_ads
            hit = _pick(ads, paying_only=True)
            if hit:
                _clear_ssp_house_only()
                return hit
        _mark_ssp_house_only()
        logger.warning(
            "SSP click_url: only house/bot inventory zone=%s count=%d — no paying fill",
            want or "*",
            len(ads or []),
        )
        return None
    return _pick(ads, paying_only=False)


_CREATIVE_BOUNDS_JS = """
(function() {
  var dpr = window.devicePixelRatio || 1;
  var out = [];
  document.querySelectorAll('a.pharmflow-mantis-creative').forEach(function(a) {
    var href = a.href || '';
    if (!href || href === '#' || href.indexOf('javascript:') === 0) return;
    var pe = (a.style && a.style.pointerEvents) || '';
    if (window.__pharmflowCssOnly === true || pe === 'none') return;
    var r = a.getBoundingClientRect();
    if (r.width < 40 || r.height < 40) return;
    if (r.bottom < 80 || r.top > (window.innerHeight || 1600) - 40) return;
    out.push({
      x: Math.round((r.left + r.width / 2) * dpr),
      y: Math.round((r.top + r.height / 2) * dpr),
      w: Math.round(r.width * dpr),
      h: Math.round(r.height * dpr),
      href: href,
      zone: a.getAttribute('data-mantis-zone') || ''
    });
  });
  return out;
})();
""".strip()


def cdp_creative_tap_targets(
    adb: AdbWrapper,
    serial: str,
    phone_idx: int,
) -> list[dict[str, Any]]:
    """Return on-screen CDP-painted creative centers (device px) + click hrefs."""
    try:
        pkg = None
        try:
            from automation.browse_proxy import browser_package_for_serial

            pkg = browser_package_for_serial(str(serial))
        except Exception:
            pkg = None
        host_port = ensure_adb_forward(
            adb, serial, phone_idx, browser_package=pkg, wait_sec=2.0
        )
        targets = _list_cdp_targets(host_port)
        target = _pick_dabflow_target(targets)
        if not target:
            return []
        ws_url = str(target["webSocketDebuggerUrl"])
        result = asyncio.run(_cdp_evaluate(ws_url, _CREATIVE_BOUNDS_JS))
        value = (result.get("result") or {}).get("result", {}).get("value")
        if not isinstance(value, list):
            return []
        out: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            try:
                out.append(
                    {
                        "x": int(item["x"]),
                        "y": int(item["y"]),
                        "w": int(item.get("w") or 0),
                        "h": int(item.get("h") or 0),
                        "href": str(item.get("href") or ""),
                        "zone": str(item.get("zone") or ""),
                        "key": f"cdp@{int(item['y']) // 80 * 80}",
                        "slot": "cdp-creative",
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
        return out
    except Exception as exc:
        logger.warning("CDP creative bounds soft-fail serial=%s: %s", serial, exc)
        return []


def load_desktop_prefs() -> dict:
    try:
        from wizard.wizard_paths import desktop_prefs_file

        path = desktop_prefs_file()
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {}


def apply_after_open_url(
    adb: AdbWrapper,
    serial: str,
    url: str,
    phone_idx: int,
    *,
    enabled: bool | None = None,
    prefs: dict | None = None,
    paint_creatives: bool = False,
    interactive: bool | None = None,
) -> dict[str, Any]:
    if enabled is None:
        pref = patch_enabled_from_prefs(prefs)
        enabled = pref if pref is not None else patch_enabled_from_env()
    if not enabled or not is_dabflow_url(url):
        return {"ok": True, "skipped": True, "reason": "disabled or not dabflow"}

    ensure_ssp_cache_warm()
    pkg = None
    try:
        from automation.browse_proxy import browser_package_for_serial

        pkg = browser_package_for_serial(str(serial))
    except Exception:
        pkg = None
    try:
        host_port = ensure_adb_forward(
            adb, serial, phone_idx, browser_package=pkg, wait_sec=2.0
        )
    except Exception as exc:
        logger.warning("dabflow patch: adb forward failed serial=%s — %s", serial, exc)
        return {"ok": False, "error": f"adb forward: {exc}"}

    result = inject_patch(
        host_port,
        paint_creatives=paint_creatives,
        interactive=interactive,
    )
    if result.get("ok"):
        logger.info(
            "dabflow Mantis patch injected serial=%s url=%s paint=%s interactive=%s",
            serial,
            result.get("target_url", url),
            paint_creatives,
            interactive if interactive is not None else paint_creatives,
        )
    else:
        logger.warning(
            "dabflow Mantis patch failed serial=%s — %s (need --remote-debugging-port in chrome flags)",
            serial,
            result.get("error"),
        )
    return result


def maybe_apply_after_open_url_step(
    adb: AdbWrapper,
    serial: str,
    url: str,
    phone_idx: int,
    *,
    log_failure: bool = True,
    paint_creatives: bool = False,
    interactive: bool | None = None,
    profile: Any = None,
) -> dict[str, Any]:
    from automation.browse_proxy import browser_package_for_serial, supports_cdp_paint

    pkg = ""
    try:
        pkg = browser_package_for_serial(str(serial)) or ""
    except Exception:
        pkg = ""
    cdp_ok = bool(pkg) and supports_cdp_paint(pkg)

    if not is_dabflow_url(url):
        # Still apply Client Hints on Chromium/Brave for non-dabflow pages.
        if profile is not None and cdp_ok:
            try:
                return apply_cdp_user_agent_override(
                    host_cdp_port(phone_idx),
                    profile,
                    adb=adb,
                    serial=serial,
                    phone_idx=phone_idx,
                    browser_package=pkg,
                )
            except Exception as exc:
                return {"ok": False, "error": str(exc), "soft_fail": True}
        return {"skipped": True}
    # CDP always fails on MuMu (/json closed) — skip straight to inject proxy.
    # The inject proxy handles MITM HTML injection of creatives + billing pixels.
    try:
        from automation.mantis_inject_proxy import inject_enabled
        if inject_enabled():
            return {"skipped": True, "reason": "inject_proxy_active", "package": pkg}
    except Exception:
        pass
    # CDP only works on Chromium-family (Chromium + Brave). Firefox/DDG/Opera skip paint.
    # Do NOT gate on skips_mitm — Brave skips MITM inject but still needs CDP paint.
    if pkg and not cdp_ok:
        return {
            "skipped": True,
            "reason": "non_chromium_browser",
            "package": pkg,
        }
    # Client Hints override first so Cloudflare sees the scrambled model on this tab.
    if profile is not None and cdp_ok:
        try:
            ua_result = apply_cdp_user_agent_override(
                host_cdp_port(phone_idx),
                profile,
                adb=adb,
                serial=serial,
                phone_idx=phone_idx,
                browser_package=pkg or None,
            )
            if not ua_result.get("ok") and log_failure:
                logger.info(
                    "CDP UA override miss serial=%s (%s)",
                    serial,
                    ua_result.get("error"),
                )
        except Exception as exc:
            logger.debug("CDP UA override soft-fail serial=%s: %s", serial, exc)
    try:
        prefs = load_desktop_prefs()
        result = apply_after_open_url(
            adb,
            serial,
            url,
            phone_idx,
            prefs=prefs,
            paint_creatives=paint_creatives,
            interactive=interactive,
        )
        if result.get("ok"):
            tab = str(result.get("target_url", url))[:60]
            logger.info(
                "Mantis patch OK serial=%s via=devtools_remote tab=%s paint=%s interactive=%s",
                serial,
                tab,
                paint_creatives,
                interactive if interactive is not None else paint_creatives,
            )
            return result
        if result.get("skipped"):
            return result
        # CDP still down — HTML inject proxy may still land the same PATCH_JS.
        if log_failure:
            logger.info(
                "Mantis CDP miss serial=%s (%s) — relying on inject proxy if enabled",
                serial,
                result.get("error"),
            )
        result["via"] = "cdp_miss_proxy_fallback"
        return result
    except Exception as exc:
        # Never raise — Windows console print/encoding must not abort open_url / age gate.
        if log_failure:
            logger.warning("dabflow Mantis patch error serial=%s: %s", serial, exc)
        return {"ok": False, "error": str(exc), "soft_fail": True}
