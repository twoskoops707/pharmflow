"""Live Path3 ad-slot picking — never hammer the same sponsored unit.

Each DabFlow page has multiple ad blocks; each block rotates creatives.
We dump the hierarchy, collect tappable ad-slot-* / Sponsored nodes, and pick
one that differs from the phone's recent taps (page + ordinal + approximate Y).
"""

from __future__ import annotations

import logging
import random
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

_BOUNDS_RE = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
_SLOT_ID_RE = re.compile(r'ad-slot-(\d+)', re.I)

# phone -> list of recent keys like "ad-slot-2@y1100"
_recent_by_serial: dict[str, list[str]] = {}


def _dump_xml(adb: Any, serial: str) -> str:
    # Share browser_adb's semaphore + per-serial circuit breaker so the ad-pick
    # dump cannot stack on top of the other dump paths (10 phones, one ADB server).
    from automation.browser_adb import (
        DUMP_CAT_TIMEOUT_S,
        DUMP_TIMEOUT_S,
        _UI_DUMP_SEM,
        dump_breaker_note,
        dump_breaker_skip,
    )

    if dump_breaker_skip(serial):
        return ""
    with _UI_DUMP_SEM:
        dump = adb.shell(
            "uiautomator dump /sdcard/pharmflow_ad_pick.xml",
            serial=serial,
            timeout=DUMP_TIMEOUT_S,
        )
        if not dump.ok and getattr(dump, "returncode", 0) == 124:
            dump_breaker_note(serial, False)
            return ""
        body = (
            adb.shell(
                "cat /sdcard/pharmflow_ad_pick.xml", serial=serial, timeout=DUMP_CAT_TIMEOUT_S
            ).stdout
            or ""
        )
        dump_breaker_note(serial, len(body) >= 500)
        return body


# Mantis creatives now render as real iframes: content-desc "adsbymantis",
# a 32-char hex creative id, and a "clicked?r=...mantisadnetwork" click node.
_AD_MARKERS = ("ad-slot", "adsbymantis", "sponsored", "clicked?r=", "mantisadnetwork")
# Nav bar sits at y>=1535; allow ads that render just above it (stats/glass tabs
# paint the creative at the very bottom, ~1482-1521, which the old <=1450 band
# silently dropped so the tap fell back and missed).
_AD_Y_MIN = 300
_AD_Y_MAX = 1520


def _collect_ad_targets(xml: str) -> list[dict[str, Any]]:
    """Return tappable ad targets from a UI dump."""
    out: list[dict[str, Any]] = []
    if not xml:
        return out
    for node in xml.split("<node "):
        low = node.lower()
        if not any(marker in low for marker in _AD_MARKERS):
            continue
        m = _BOUNDS_RE.search(node)
        if not m:
            continue
        x1, y1, x2, y2 = (int(m.group(i)) for i in range(1, 5))
        if x2 <= x1 or y2 <= y1 or (x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0):
            continue
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        # On-screen band — skip chrome / nav, keep bottom-of-tab creatives.
        if cy < _AD_Y_MIN or cy > _AD_Y_MAX or cx < 40 or cx > 880:
            continue
        slot_m = _SLOT_ID_RE.search(node)
        slot = f"ad-slot-{slot_m.group(1)}" if slot_m else "sponsored"
        # Prefer nodes that look like the creative card, not tiny labels.
        area = (x2 - x1) * (y2 - y1)
        if area < 8000:
            continue
        key = f"{slot}@y{(cy // 80) * 80}"
        out.append(
            {
                "key": key,
                "slot": slot,
                "x": cx,
                "y": cy,
                "area": area,
                "bounds": (x1, y1, x2, y2),
            }
        )
    # De-dupe by key keeping largest area.
    best: dict[str, dict[str, Any]] = {}
    for t in out:
        prev = best.get(t["key"])
        if prev is None or t["area"] > prev["area"]:
            best[t["key"]] = t
    return list(best.values())


def nudge_tap_off_ads(
    adb: Any,
    serial: str,
    x: int,
    y: int,
    *,
    pad: int = 12,
) -> tuple[int, int, bool]:
    """If (x,y) sits inside a live ad card, shift above it so Path1/2 never click.

    Impressions still count from painted/viewable creatives; only the tap is moved.
    """
    xml = _dump_xml(adb, serial)
    targets = _collect_ad_targets(xml)
    if not targets:
        return int(x), int(y), False
    for t in targets:
        bounds = t.get("bounds")
        if not bounds or len(bounds) != 4:
            continue
        x1, y1, x2, y2 = (int(v) for v in bounds)
        if (x1 - pad) <= x <= (x2 + pad) and (y1 - pad) <= y <= (y2 + pad):
            # Prefer above the creative; if that collides with chrome, go below.
            ny = y1 - 48
            if ny < _AD_Y_MIN:
                ny = min(_AD_Y_MAX, y2 + 48)
            logger.warning(
                "nudge tap off ad serial=%s from=(%d,%d) to=(%d,%d) slot=%s",
                serial,
                x,
                y,
                x,
                ny,
                t.get("slot"),
            )
            return int(x), int(ny), True
    return int(x), int(y), False


def pick_live_ad_coords(
    adb: Any,
    serial: str,
    *,
    fallback_xy: tuple[int, int],
    preferred_slot: str | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Pick a live ad tap that differs from recent picks on this phone."""
    r = rng or random.Random()
    xml = _dump_xml(adb, serial)
    targets = _collect_ad_targets(xml)
    recent = list(_recent_by_serial.get(serial, []))
    recent_set = set(recent[-12:])

    fresh = [t for t in targets if t["key"] not in recent_set]
    pool = fresh or targets

    if preferred_slot and pool:
        pref = [t for t in pool if preferred_slot in t["slot"] or preferred_slot in t["key"]]
        if pref:
            pool = pref

    if not pool:
        # One scroll then retry — different creatives come into view.
        adb.swipe(450, 1200, 450, 500, 420, serial=serial)
        time.sleep(0.7)
        xml = _dump_xml(adb, serial)
        targets = _collect_ad_targets(xml)
        fresh = [t for t in targets if t["key"] not in recent_set]
        pool = fresh or targets

    if not pool:
        fx, fy = fallback_xy
        logger.warning(
            "live ad pick: no slots on %s — fallback (%d,%d)", serial, fx, fy
        )
        return {"ok": False, "x": fx, "y": fy, "key": "fallback", "slot": "fallback"}

    # Weight toward less-recent / different Y bands.
    weights = []
    for t in pool:
        w = 3.0
        if t["key"] in recent_set:
            w *= 0.15
        if recent and t["key"] == recent[-1]:
            w *= 0.05
        weights.append(max(0.05, w))
    choice = r.choices(pool, weights=weights, k=1)[0]
    hist = _recent_by_serial.setdefault(serial, [])
    hist.append(choice["key"])
    if len(hist) > 24:
        del hist[:-18]
    logger.info(
        "live ad pick serial=%s slot=%s xy=(%d,%d) key=%s pool=%d fresh=%d",
        serial,
        choice["slot"],
        choice["x"],
        choice["y"],
        choice["key"],
        len(targets),
        len(fresh),
    )
    return {
        "ok": True,
        "x": int(choice["x"]),
        "y": int(choice["y"]),
        "key": choice["key"],
        "slot": choice["slot"],
        "pool": len(targets),
    }
