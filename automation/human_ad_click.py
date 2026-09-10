"""Human-style Path3 ad engagement — random tab/zone every sequence.

Every Path3 ad tap should feel like a different person: pick a fresh tab,
light-scroll, land on a live creative, jitter the tap. Avoid repeating the
last tab/slot on the same phone.

After the ad click lands on the advertiser/Mantis page, slowly scroll to the
bottom like a human reading the offer.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import Any

from automation.ad_slot_pick import pick_live_ad_coords
from automation.dabflow_mantis_ad_urls import TAB_TO_ZONE, ZONE_TO_AD_CHECKPOINT
from automation.dabflow_mantis_client_patch import ssp_paying_zone_ids
from automation.dabflow_mapper import load_mapping

logger = logging.getLogger(__name__)

# Tabs that host active mobile Mantis zones on getdabflow.app.
AD_TABS: tuple[str, ...] = ("home", "timer", "stats", "glass_art", "settings")

_TAB_COORDS_900x1600: dict[str, tuple[int, int]] = {
    "home": (90, 1535),
    "timer": (270, 1535),
    "stats": (449, 1535),
    "glass_art": (629, 1535),
    "settings": (809, 1535),
}

_last_tab_by_serial: dict[str, str] = {}
_recent_tabs_by_serial: dict[str, list[str]] = {}

PaintAfterNavFn = Callable[[str, str, str], None]
CdpTargetsFn = Callable[[], list[dict[str, Any]]]


def _tab_xy(tab: str) -> tuple[int, int]:
    try:
        mapping = load_mapping()
        pt = mapping.tab_point(tab)
        return int(pt.x), int(pt.y)
    except Exception:
        return _TAB_COORDS_900x1600.get(tab, (449, 1535))


def _pick_tab(serial: str, rng: random.Random) -> str:
    """Always a different tab than last; prefer unused tabs until all 5 used.

    When SSP currently has paying fill on some zones, bias toward those tabs so
    Path3 open_url is more likely to bill instead of house/bot-only inventory.
    """
    last = _last_tab_by_serial.get(serial, "")
    hist = _recent_tabs_by_serial.get(serial, [])
    used_cycle = set(hist[-len(AD_TABS) :]) if hist else set()
    unused = [t for t in AD_TABS if t not in used_cycle and t != last]
    pool = unused or [t for t in AD_TABS if t != last] or list(AD_TABS)
    paying_tabs: list[str] = []
    try:
        # Force refresh so house-only TTL cannot hide a paying return mid-Path3.
        paying_zones = ssp_paying_zone_ids(force_refresh=True)
        if paying_zones:
            paying_tabs = [
                t for t in pool if TAB_TO_ZONE.get(t, "") in paying_zones
            ]
    except Exception:
        paying_tabs = []
    if paying_tabs:
        return rng.choice(paying_tabs)
    return rng.choice(pool)


def _scale_xy(scale_fn: Any | None, x: int, y: int) -> tuple[int, int]:
    if scale_fn is None:
        return x, y
    try:
        sx, sy = scale_fn(x, y)
        return int(sx), int(sy)
    except Exception:
        return x, y


def _human_scroll(
    adb: Any,
    serial: str,
    rng: random.Random,
    passes: int,
    scale_fn: Any | None = None,
) -> None:
    for _ in range(max(0, passes)):
        x = 420 + rng.randint(-40, 40)
        y1 = 1180 + rng.randint(-60, 40)
        y2 = 420 + rng.randint(-40, 80)
        sx, sy1 = _scale_xy(scale_fn, x, y1)
        _, sy2 = _scale_xy(scale_fn, x, y2)
        dur = 380 + rng.randint(0, 160)
        try:
            adb.swipe(sx, sy1, sx, sy2, dur, serial=serial)
        except Exception:
            break
        time.sleep(0.35 + rng.random() * 0.45)


def human_scroll_ad_landing(
    adb: Any,
    serial: str,
    *,
    rng: random.Random | None = None,
    passes: int | None = None,
    scale_fn: Any | None = None,
) -> dict[str, Any]:
    """After ad click: slowly scroll the landing/offer page to the bottom.

    Operator rule (repeated): do not bounce off the top — read down the page
    like a person. Slow long swipes with pauses between them.
    """
    r = rng or random.Random()
    n = int(passes) if passes is not None else r.choice((4, 5, 5, 6, 7))
    n = max(3, min(10, n))
    # Let the landing paint before the first swipe. 3–5s: Mantis scores
    # bounce-rate per click; sub-2s bounces can void click billing.
    settle = 3.0 + r.random() * 2.0
    time.sleep(settle)
    for i in range(n):
        x = 450 + r.randint(-55, 55)
        # Long, slow upward flick (finger moves down→up content).
        y1 = 1320 + r.randint(-40, 40)
        y2 = 380 + r.randint(-50, 60)
        sx, sy1 = _scale_xy(scale_fn, x, y1)
        _, sy2 = _scale_xy(scale_fn, x, y2)
        dur = 720 + r.randint(0, 480)  # 0.7–1.2s human drag
        try:
            adb.swipe(sx, sy1, sx, sy2, dur, serial=serial)
        except Exception as exc:
            logger.warning(
                "ad-landing scroll soft-fail serial=%s pass=%d: %s", serial, i + 1, exc
            )
            break
        # Pause like reading a section.
        time.sleep(1.1 + r.random() * 1.6)
    # Hold at bottom before leaving — quality-signal dwell on the offer page.
    hold = 4.0 + r.random() * 4.0
    time.sleep(hold)
    out = {"ok": True, "scrolls": n, "settle_s": round(settle, 2), "hold_s": round(hold, 2)}
    logger.info(
        "ad-landing human scroll serial=%s scrolls=%d settle=%.1fs hold=%.1fs",
        serial,
        n,
        settle,
        hold,
    )
    return out


def human_path3_ad_engage(
    adb: Any,
    serial: str,
    *,
    fallback_xy: tuple[int, int],
    scale_fn: Any | None = None,
    rng: random.Random | None = None,
    after_nav_paint: PaintAfterNavFn | None = None,
    cdp_targets_fn: CdpTargetsFn | None = None,
) -> dict[str, Any]:
    """Navigate to a random ad tab, re-paint, pick a live creative.

    Paint must happen AFTER tab navigation — zones for stats/glass/settings are
    not in the DOM on home, so pre-nav paint left Path3 tapping empty fallbacks.

    Returns coords + metadata for the Path3 tap. Soft-fails to fallback_xy.
    """
    r = rng or random.Random()
    tab = _pick_tab(serial, r)
    logger.info(
        "[%s] Path3 ad tab=%s (rotate among home/timer/stats/glass/settings)",
        serial,
        tab,
    )
    zone = TAB_TO_ZONE.get(tab, "zone-one")
    checkpoint = ZONE_TO_AD_CHECKPOINT.get(zone, "ad_home")
    out: dict[str, Any] = {
        "ok": False,
        "tab": tab,
        "zone": zone,
        "checkpoint": checkpoint,
        "x": int(fallback_xy[0]),
        "y": int(fallback_xy[1]),
        "key": "fallback",
        "slot": "fallback",
        "click_url": "",
    }

    tx, ty = _tab_xy(tab)
    if scale_fn is not None:
        try:
            tx, ty = scale_fn(tx, ty)
        except Exception:
            pass
    tx += r.randint(-10, 10)
    ty += r.randint(-6, 6)
    try:
        adb.tap(tx, ty, serial=serial)
        # Mantis viewability: 5–8s pre-click dwell — the tab's impression
        # pixels must land (server-acknowledged) before the tap fires, or the
        # click binds to an uncounted impression and never registers.
        dwell = 5.0 + r.random() * 3.0
        time.sleep(dwell)
        out["tab_dwell_s"] = round(dwell, 2)
        out["tab_tap"] = (tx, ty)
    except Exception as exc:
        logger.warning("human ad tab tap soft-fail serial=%s tab=%s: %s", serial, tab, exc)

    if tab == "home":
        passes = r.choice((1, 2, 2, 3, 4))
    elif tab == "timer":
        passes = r.choice((0, 0, 1))
    else:
        passes = r.choice((0, 1, 1, 2))
    _human_scroll(adb, serial, r, passes, scale_fn=scale_fn)
    out["scrolls"] = passes
    time.sleep(2.0 + r.random() * 2.0)

    if after_nav_paint is not None:
        try:
            after_nav_paint(tab, zone, checkpoint)
            time.sleep(0.45 + r.random() * 0.35)
        except Exception as exc:
            logger.warning("human Path3 after-nav paint soft-fail: %s", exc)

    if cdp_targets_fn is not None:
        try:
            targets = cdp_targets_fn() or []
            if zone:
                zmatch = [t for t in targets if t.get("zone") == zone]
                if zmatch:
                    targets = zmatch
            if targets:
                choice = r.choice(targets)
                out.update(
                    {
                        "ok": True,
                        "x": int(choice["x"]) + r.randint(-12, 12),
                        "y": int(choice["y"]) + r.randint(-10, 10),
                        "key": str(choice.get("key") or "cdp"),
                        "slot": str(choice.get("slot") or "cdp-creative"),
                        "click_url": str(choice.get("href") or ""),
                        "human": True,
                        "tab": tab,
                        "zone": zone,
                        "checkpoint": checkpoint,
                    }
                )
                _last_tab_by_serial[serial] = tab
                hist = _recent_tabs_by_serial.setdefault(serial, [])
                hist.append(tab)
                if len(hist) > 12:
                    del hist[:-10]
                logger.info(
                    "human Path3 ad serial=%s tab=%s zone=%s scrolls=%s xy=(%s,%s) key=%s",
                    serial,
                    tab,
                    zone,
                    passes,
                    out.get("x"),
                    out.get("y"),
                    out.get("key"),
                )
                return out
        except Exception as exc:
            logger.warning("human CDP creative pick soft-fail: %s", exc)

    try:
        live = pick_live_ad_coords(
            adb,
            serial,
            fallback_xy=fallback_xy,
            preferred_slot=None,
            rng=r,
        )
        out.update(live)
        out["x"] = int(live["x"]) + r.randint(-12, 12)
        out["y"] = int(live["y"]) + r.randint(-10, 10)
        out["tab"] = tab
        out["zone"] = zone
        out["checkpoint"] = checkpoint
        out["human"] = True
    except Exception as exc:
        logger.warning("human live ad pick soft-fail: %s", exc)

    _last_tab_by_serial[serial] = tab
    hist = _recent_tabs_by_serial.setdefault(serial, [])
    hist.append(tab)
    if len(hist) > 12:
        del hist[:-10]

    logger.info(
        "human Path3 ad serial=%s tab=%s zone=%s scrolls=%s xy=(%s,%s) key=%s",
        serial,
        tab,
        zone,
        passes,
        out.get("x"),
        out.get("y"),
        out.get("key"),
    )
    return out
