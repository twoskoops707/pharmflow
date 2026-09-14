"""Assign phone geo/timezone to places where local time is in an allowed window.

Default window: 09:30–24:00 (midnight) local time. Used so farm phones appear
somewhere on Earth that is currently awake (late morning through evening), not
at the operator's overnight local clock.
"""

from __future__ import annotations

import logging
import os
import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Sequence
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Inclusive start, exclusive end (midnight).
DEFAULT_WINDOW_START = time(9, 30)
DEFAULT_WINDOW_END = time(0, 0)  # treated as 24:00


@dataclass(frozen=True)
class GeoLocale:
    """A real place: IANA tz + approx coordinates."""

    city: str
    country: str
    tz: str
    lat: float
    lon: float

    @property
    def label(self) -> str:
        return f"{self.city}, {self.country}"


# Spread across UTC+2 … UTC+12 (covers 09:30–24:00 for most of the UTC day).
# Used when US cannabis markets are asleep. Do not pick these while US is in-window.
GEO_CATALOG: tuple[GeoLocale, ...] = (
    GeoLocale("Berlin", "Germany", "Europe/Berlin", 52.52, 13.405),
    GeoLocale("Cairo", "Egypt", "Africa/Cairo", 30.0444, 31.2357),
    GeoLocale("Athens", "Greece", "Europe/Athens", 37.9838, 23.7275),
    GeoLocale("Moscow", "Russia", "Europe/Moscow", 55.7558, 37.6173),
    GeoLocale("Dubai", "UAE", "Asia/Dubai", 25.2048, 55.2708),
    GeoLocale("Karachi", "Pakistan", "Asia/Karachi", 24.8607, 67.0011),
    GeoLocale("Delhi", "India", "Asia/Kolkata", 28.6139, 77.2090),
    GeoLocale("Dhaka", "Bangladesh", "Asia/Dhaka", 23.8103, 90.4125),
    GeoLocale("Bangkok", "Thailand", "Asia/Bangkok", 13.7563, 100.5018),
    GeoLocale("Singapore", "Singapore", "Asia/Singapore", 1.3521, 103.8198),
    GeoLocale("Hong Kong", "China", "Asia/Hong_Kong", 22.3193, 114.1694),
    GeoLocale("Tokyo", "Japan", "Asia/Tokyo", 35.6762, 139.6503),
    GeoLocale("Seoul", "South Korea", "Asia/Seoul", 37.5665, 126.9780),
    GeoLocale("Sydney", "Australia", "Australia/Sydney", -33.8688, 151.2093),
    GeoLocale("Brisbane", "Australia", "Australia/Brisbane", -27.4698, 153.0251),
)

# Mantis cannabis demand is US. Isolation must prefer these whenever local time
# is inside the awake window — Dubai/Delhi/etc. yield house/bot fill and $0 clicks.
PAYING_MARKET_GEO: tuple[GeoLocale, ...] = (
    GeoLocale("Los Angeles", "USA", "America/Los_Angeles", 34.0522, -118.2437),
    GeoLocale("Denver", "USA", "America/Denver", 39.7392, -104.9903),
    GeoLocale("Phoenix", "USA", "America/Phoenix", 33.4484, -112.0740),
    GeoLocale("Portland", "USA", "America/Los_Angeles", 45.5152, -122.6784),
    GeoLocale("Seattle", "USA", "America/Los_Angeles", 47.6062, -122.3321),
    GeoLocale("Las Vegas", "USA", "America/Los_Angeles", 36.1699, -115.1398),
    GeoLocale("Chicago", "USA", "America/Chicago", 41.8781, -87.6298),
    GeoLocale("Austin", "USA", "America/Chicago", 30.2672, -97.7431),
    GeoLocale("Detroit", "USA", "America/Detroit", 42.3314, -83.0458),
    GeoLocale("New York", "USA", "America/New_York", 40.7128, -74.0060),
    GeoLocale("Boston", "USA", "America/New_York", 42.3601, -71.0589),
    GeoLocale("Miami", "USA", "America/New_York", 25.7617, -80.1918),
)


def active_geo_catalog() -> tuple[GeoLocale, ...]:
    """US paying markets first, then overnight east-hemisphere fallback."""
    return PAYING_MARKET_GEO + GEO_CATALOG


def _window_enabled() -> bool:
    return os.environ.get("PHARMFLOW_GEO_TIME_WINDOW", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def parse_window(
    start: time | None = None,
    end: time | None = None,
) -> tuple[time, time]:
    """Parse PHARMFLOW_GEO_WINDOW_START / END as HH:MM (default 09:30–00:00)."""
    s = start or DEFAULT_WINDOW_START
    e = end or DEFAULT_WINDOW_END
    raw_s = os.environ.get("PHARMFLOW_GEO_WINDOW_START", "").strip()
    raw_e = os.environ.get("PHARMFLOW_GEO_WINDOW_END", "").strip()
    if raw_s:
        hh, mm = raw_s.split(":", 1)
        s = time(int(hh), int(mm))
    if raw_e:
        hh, mm = raw_e.split(":", 1)
        e = time(int(hh), int(mm))
    return s, e


def local_in_window(now_utc: datetime, tz_name: str, start: time, end: time) -> bool:
    """True if local clock in tz is within [start, end) wrapping midnight if needed."""
    zi = ZoneInfo(tz_name)
    local = now_utc.astimezone(zi)
    t = local.time().replace(tzinfo=None)
    if start <= end and not (start == time(0, 0) and end == time(0, 0)):
        # Normal range e.g. 09:30–18:00. end==00:00 means through end of day.
        if end == time(0, 0):
            return t >= start
        return start <= t < end
    # Wrapped range e.g. 22:00–06:00
    return t >= start or t < end


def locales_in_window(
    now_utc: datetime | None = None,
    *,
    start: time | None = None,
    end: time | None = None,
    catalog: Sequence[GeoLocale] | None = None,
) -> list[GeoLocale]:
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    w_start, w_end = parse_window(start, end)
    pool = tuple(catalog) if catalog is not None else active_geo_catalog()
    out: list[GeoLocale] = []
    for loc in pool:
        try:
            if local_in_window(now, loc.tz, w_start, w_end):
                out.append(loc)
        except Exception as exc:
            logger.debug("skip locale %s: %s", loc.tz, exc)
    return out


def pick_locales_for_phones(
    n: int,
    *,
    now_utc: datetime | None = None,
    rng: random.Random | None = None,
) -> list[GeoLocale]:
    """Pick up to n locales — ALWAYS prefer US paying markets.

    80% US cities (Mantis pays for US cannabis traffic), 20% international
    for stealth diversity.  US picks cycle through all paying markets so
    every phone gets a unique US city each sequence.
    """
    r = rng or random.Random()
    us_count = max(1, int(n * 0.8))  # 80% US
    intl_count = n - us_count         # 20% international

    # US: always available, shuffle and rotate
    us_pool = list(PAYING_MARKET_GEO)
    r.shuffle(us_pool)
    us_picks = [us_pool[i % len(us_pool)] for i in range(us_count)]

    # International: pick from in-window or fallback catalog
    eligible = locales_in_window(now_utc)
    intl_catalog = [loc for loc in eligible if loc not in PAYING_MARKET_GEO]
    if not intl_catalog:
        intl_catalog = list(GEO_CATALOG)
    r.shuffle(intl_catalog)
    intl_picks = [intl_catalog[i % len(intl_catalog)] for i in range(intl_count)]

    combined = us_picks + intl_picks
    r.shuffle(combined)
    return combined[:n]


def utc_offset_hours(tz_name: str, now_utc: datetime | None = None) -> float:
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(ZoneInfo(tz_name))
    off = local.utcoffset() or timedelta(0)
    return off.total_seconds() / 3600.0


def apply_geo_to_phone(adb: object, serial: str, locale: GeoLocale) -> bool:
    """
    Set Android timezone + best-effort mock GPS for *serial*.

    ``adb`` must expose ``.shell(cmd, serial=...)``.
    """
    shell = getattr(adb, "shell", None)
    if not callable(shell):
        raise TypeError("adb must provide shell()")

    ok = True
    cmds = [
        "settings put global auto_time_zone 0",
        "settings put global auto_time 0",
        f"setprop persist.sys.timezone {locale.tz}",
        f"setprop persist.sys.locale en-US",
    ]
    # Android 10+ location inject (best effort; may no-op without permission).
    cmds.extend(
        [
            f"cmd location set-location -- {locale.lat} {locale.lon}",
            f"am broadcast -a android.intent.action.TIMEZONE_CHANGED --es time-zone {locale.tz}",
        ]
    )
    for cmd in cmds:
        try:
            shell(cmd, serial=serial)
        except Exception as exc:
            ok = False
            logger.debug("%s geo cmd failed (%s): %s", serial, cmd[:40], exc)

    # Align wall clock roughly to locale local time (epoch seconds for that zone "now").
    try:
        now = datetime.now(timezone.utc)
        local = now.astimezone(ZoneInfo(locale.tz))
        # date -u MMDDhhmmYYYY.ss then set timezone — MuMu often ignores; try anyway.
        stamp = local.strftime("%m%d%H%M%Y.%S")
        shell(f"su 0 date {stamp}", serial=serial)
    except Exception:
        pass

    logger.info(
        "geo apply serial=%s place=%s tz=%s lat=%.4f lon=%.4f ok=%s",
        serial,
        locale.label,
        locale.tz,
        locale.lat,
        locale.lon,
        ok,
    )
    return ok


def apply_geo_window_to_serials(
    adb: object,
    serials: Sequence[str],
    *,
    now_utc: datetime | None = None,
) -> list[tuple[str, GeoLocale]]:
    """Assign and apply one in-window locale per serial. Returns assignments."""
    if not _window_enabled():
        logger.info("PHARMFLOW_GEO_TIME_WINDOW disabled — skipping geo apply")
        return []
    locales = pick_locales_for_phones(len(serials), now_utc=now_utc)
    assigned: list[tuple[str, GeoLocale]] = []
    for serial, loc in zip(serials, locales):
        apply_geo_to_phone(adb, serial, loc)
        assigned.append((serial, loc))
    return assigned
