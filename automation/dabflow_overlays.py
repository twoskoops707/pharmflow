"""Dismiss Chromium splash, native alerts, and DabFlow HTML age gate (no PharmFlow GUI needed)."""

from __future__ import annotations

import logging
import random
import re
import time
from typing import Any

from automation.adb_wrapper import AdbWrapper
from automation.browser_adb import _env_float, dismiss_chromium_fre

logger = logging.getLogger(__name__)

_BOUNDS_RE = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')

# Live-calibrated 900x1600: YES is left button on age modal.
# Center of live Yes ~[90,926][442,1076]. Old (380,980) was top-right edge —
# and FRE Stay-signed-out probe at (450,1127) was hitting No.
AGE_GATE_YES = (270, 1020)
# Cold load after cookie clear: SPA + age modal need >80ms (b21b421 overshot).
# 1.5s is enough for gate paint without the old 2s+FRE dump loop.
AGE_GATE_LOAD_WAIT_S = 1.5
# After Yes: home material row needs a beat before selection taps.
AGE_GATE_POST_YES_SETTLE_S = 0.55
# Floor for sequence JSON "Wait for home screen" (gen had 0.05–0.12).
HOME_SCREEN_WAIT_MIN_S = 0.75
HOME_SCREEN_WAIT_MAX_S = 1.2
# Start Perfect Dab — must be scrolled into view; blind 1320 fails when bounds are [0,0].
START_DAB_FALLBACK = (449, 1281)  # live-proven; bounds center ~1328 misses under nav
START_REVEAL_SWIPE = (450, 1150, 450, 550, 480)
# Strong markers only — bare "Pause" false-positived green logs without a live timer.
_TIMER_MARKERS = ("HEAT YOUR BANGER", "heat your banger", "COOL DOWN", "Cool Down")


def _fg_pkg(adb: AdbWrapper, serial: str) -> str:
    out = adb.shell("dumpsys activity activities", serial=serial, timeout=8.0)
    text = (out.stdout or "") if out is not None else ""
    m = re.search(r"topResumedActivity=ActivityRecord\{[^ ]+ u0 ([^/]+)/", text)
    return m.group(1) if m else ""


def _is_dabflow_browser_fg(fg: str) -> bool:
    """Any farm browser (Chromium/Brave/Firefox/Opera) can run Start Perfect Dab."""
    from automation.farm_launch_guard import is_farm_browser_package

    return is_farm_browser_package(fg)


def _browser_pkg_for_serial(serial: str) -> str:
    try:
        from automation.browse_proxy import browser_package_for_serial

        pkg = (browser_package_for_serial(str(serial)) or "").strip()
        if pkg:
            return pkg
    except Exception:
        pass
    return "org.chromium.chrome"


def _bring_chromium_dabflow(adb: AdbWrapper, serial: str) -> bool:
    """If Lawnchair/gallery stole FG, bring DabFlow forward in the current farm browser."""
    fg = (_fg_pkg(adb, serial) or "").lower()
    if _is_dabflow_browser_fg(fg):
        return True
    logger.warning(
        "Start Dab: farm browser not FG (%s) on %s — bringing DabFlow forward",
        fg,
        serial,
    )
    browser_pkg = _browser_pkg_for_serial(serial)
    if "lawnchair" in fg or fg.endswith(".launcher3"):
        adb.shell(f"am force-stop {fg}", serial=serial, timeout=6.0)
        time.sleep(0.35)
    adb.shell(
        f"monkey -p {browser_pkg} -c android.intent.category.LAUNCHER 1",
        serial=serial,
        timeout=8.0,
    )
    time.sleep(0.9)
    adb.shell(
        "am start -a android.intent.action.VIEW -d https://getdabflow.app/",
        serial=serial,
        timeout=8.0,
    )
    time.sleep(1.8)
    fg2 = (_fg_pkg(adb, serial) or "").lower()
    if _is_dabflow_browser_fg(fg2):
        return True
    adb.shell(
        f"am start -a android.intent.action.VIEW -d https://getdabflow.app/ "
        f"-n {browser_pkg}/org.chromium.chrome.browser.ChromeTabbedActivity",
        serial=serial,
        timeout=8.0,
    )
    time.sleep(1.2)
    fg3 = (_fg_pkg(adb, serial) or "").lower()
    return _is_dabflow_browser_fg(fg3)

def _dump_xml(adb: AdbWrapper, serial: str) -> str:
    """Pull UI hierarchy; fast-fail on timeout (partial dumps false-fail Start Dab)."""
    from automation.browser_adb import (
        DUMP_CAT_TIMEOUT_S,
        DUMP_TIMEOUT_S,
        _UI_DUMP_SEM,
        dump_breaker_note,
        dump_breaker_skip,
    )

    if dump_breaker_skip(serial):
        return ""
    for attempt in range(2):
        with _UI_DUMP_SEM:
            dump = adb.shell(
                "uiautomator dump /sdcard/pharmflow_overlay.xml",
                serial=serial,
                timeout=DUMP_TIMEOUT_S,
            )
            if not dump.ok and dump.returncode == 124:
                logger.warning(
                    "overlay uiautomator dump timed out on %s (attempt %d)",
                    serial,
                    attempt + 1,
                )
                dump_breaker_note(serial, False)
                time.sleep(0.3)
                continue
            body = (
                adb.shell(
                    "cat /sdcard/pharmflow_overlay.xml", serial=serial, timeout=DUMP_CAT_TIMEOUT_S
                ).stdout
                or ""
            )
        if len(body) >= 2000:
            dump_breaker_note(serial, True)
            return body
        time.sleep(0.3)
    return ""


def _tap_bounds(adb: AdbWrapper, serial: str, x1: int, y1: int, x2: int, y2: int) -> bool:
    return adb.tap((x1 + x2) // 2, (y1 + y2) // 2, serial=serial).ok


def _start_dab_node_present(xml: str) -> bool:
    low = (xml or "").lower()
    return "start-dab-btn" in low or "start perfect dab" in low


def _find_start_dab_bounds(xml: str) -> tuple[int, int, int, int] | None:
    for node in xml.split("<node "):
        low = node.lower()
        if "start-dab-btn" not in low and "start perfect dab" not in low:
            continue
        m = _BOUNDS_RE.search(node)
        if not m:
            continue
        x1, y1, x2, y2 = (int(m.group(i)) for i in range(1, 5))
        if x2 <= x1 or y2 <= y1:
            continue
        # Off-screen / not laid out — common on MuMu until scrolled into view.
        if x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0:
            continue
        cy = (y1 + y2) // 2
        if cy < 400 or cy > 1500:
            continue
        return x1, y1, x2, y2
    return None


def _timer_running(xml: str, *, tapped_live_bounds: bool = False) -> bool:
    if not xml:
        return False
    # Still on home with a *tappable* Start button → timer not running.
    if _find_start_dab_bounds(xml):
        return False
    low = xml.lower()
    if any(tok.lower() in low for tok in _TIMER_MARKERS):
        return True
    # WebView often omits HEAT YOUR BANGER from a11y. After a live-bounds tap,
    # Start leaving the tappable hierarchy means the timer UI took over.
    if tapped_live_bounds and not _find_start_dab_bounds(xml):
        return True
    return False


def _cdp_click_start_dab(adb: AdbWrapper, serial: str) -> bool:
    """Click Start Perfect Dab via Chrome DevTools — stock Chrome often hides a11y."""
    try:
        import asyncio

        from automation.dabflow_mantis_client_patch import (
            _cdp_evaluate,
            _list_cdp_targets,
            ensure_adb_forward,
            host_cdp_port,
        )

        phone_idx = 0
        ensure_adb_forward(
            adb, serial, phone_idx, browser_package="com.android.chrome", wait_sec=2.0
        )
        port = host_cdp_port(phone_idx)
        targets = _list_cdp_targets(port) or []
        page = None
        for t in targets:
            url = str(t.get("url") or "")
            if (
                t.get("type") == "page"
                and "getdabflow" in url.lower()
                and t.get("webSocketDebuggerUrl")
            ):
                page = t
                break
        if page is None:
            for t in targets:
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    page = t
                    break
        if page is None:
            return False
        js = """
(() => {
  const match = (el) => {
    const t = ((el && (el.innerText || el.textContent)) || '').toLowerCase();
    const id = ((el && el.id) || '').toLowerCase();
    return id.includes('start-dab') || t.includes('start perfect dab');
  };
  let el = document.querySelector('#start-dab-btn')
    || document.querySelector('[id*="start-dab"]')
    || [...document.querySelectorAll('button,a,[role="button"]')].find(match);
  if (!el) return {ok:false, reason:'missing'};
  try { el.scrollIntoView({block:'center', inline:'nearest'}); } catch (e) {}
  try { el.click(); } catch (e) { return {ok:false, reason:String(e)}; }
  return {ok:true, id: el.id || '', text: ((el.innerText||el.textContent||'').slice(0,48))};
})()
"""
        result = asyncio.run(_cdp_evaluate(str(page["webSocketDebuggerUrl"]), js))
        val = ((result.get("result") or {}).get("result") or {}).get("value") or {}
        ok = bool(isinstance(val, dict) and val.get("ok"))
        if ok:
            logger.info("Start Perfect Dab CDP click OK on %s (%s)", serial, val)
        else:
            logger.warning(
                "Start Perfect Dab CDP click miss on %s (%s)", serial, val or result
            )
        return ok
    except Exception as exc:
        logger.warning("Start Perfect Dab CDP click soft-fail on %s: %s", serial, exc)
        return False


def ensure_start_perfect_dab(
    adb: AdbWrapper,
    serial: str,
    *,
    fallback_xy: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Scroll-reveal Start Perfect Dab, tap live bounds, verify timer started."""
    report: dict[str, Any] = {
        "scrolled": 0,
        "tapped": False,
        "coords": None,
        "timer_started": False,
        "bounds": None,
        "live_bounds": False,
    }
    report["chromium_fg"] = _bring_chromium_dabflow(adb, serial)
    # CDP always fails on MuMu (/json closed) — skip straight to ADB tap.
    if False and _cdp_click_start_dab(adb, serial):
        time.sleep(_env_float("PHARMFLOW_START_DAB_VERIFY_WAIT", 1.5))
        xml = _dump_xml(adb, serial)
        if _timer_running(xml, tapped_live_bounds=True) or (
            xml and not _find_start_dab_bounds(xml)
        ):
            report["tapped"] = True
            report["timer_started"] = True
            report["coords"] = ("cdp", "click")
            report["live_bounds"] = True
            logger.info("Start Perfect Dab OK via CDP on %s", serial)
            return report
        report["tapped"] = True
        report["timer_started"] = True
        report["coords"] = ("cdp", "click")
        report["cdp_soft"] = True
        logger.info("Start Perfect Dab CDP soft-OK on %s (verify dump ambiguous)", serial)
        return report
    fx, fy = fallback_xy or START_DAB_FALLBACK
    x1s, y1s, x2s, y2s, dur = START_REVEAL_SWIPE

    def _tap_xy_from_bounds(b: tuple[int, int, int, int]) -> tuple[int, int]:
        # Live-proven: full-bounds center (~1328) misses under nav; upper-third ~1281 hits.
        x1, y1, x2, y2 = b
        cx = (x1 + x2) // 2
        cy = y1 + max(24, (y2 - y1) // 3)
        cy = min(cy, 1300)
        return cx, cy

    def _reveal_bounds() -> tuple[int, int, int, int] | None:
        # Zero-bounds start-dab-btn is common until scrolled — keep swiping harder.
        for pass_i in range(8):
            xml = _dump_xml(adb, serial)
            if _timer_running(xml):
                report["timer_started"] = True
                logger.info("Timer already running on %s — skip Start tap", serial)
                return None
            bounds = _find_start_dab_bounds(xml)
            if bounds:
                return bounds
            # Stronger upward fling when node present but [0,0][0,0].
            fling = dur + 80 + pass_i * 50
            adb.swipe(x1s, y1s, x2s, max(200, y2s - pass_i * 40), fling, serial=serial)
            report["scrolled"] = pass_i + 1
            time.sleep(0.55)
        return None

    bounds = _reveal_bounds()
    if report["timer_started"]:
        return report

    live = False
    if bounds:
        report["bounds"] = list(bounds)
        live = True
        cx, cy = _tap_xy_from_bounds(bounds)
    else:
        adb.swipe(x1s, y1s, x2s, y2s, dur + 120, serial=serial)
        report["scrolled"] = report["scrolled"] + 1
        time.sleep(0.55)
        xml = _dump_xml(adb, serial)
        bounds = _find_start_dab_bounds(xml)
        if bounds:
            report["bounds"] = list(bounds)
            live = True
            cx, cy = _tap_xy_from_bounds(bounds)
        else:
            if not report.get("chromium_fg"):
                report["chromium_fg"] = _bring_chromium_dabflow(adb, serial)
            if not report.get("chromium_fg"):
                logger.warning(
                    "skip start-dab fallback tap on %s — farm browser not FG after relaunch",
                    serial,
                )
                report["skipped_foreign_fg"] = True
                return report
            cx, cy = fx, fy
            logger.warning(
                "start-dab-btn not tappable on %s — fallback tap (%d,%d)", serial, cx, cy
            )

    report["live_bounds"] = live
    ok = adb.tap(cx, cy, serial=serial).ok
    report["tapped"] = bool(ok)
    report["coords"] = (cx, cy)
    if not ok:
        return report

    verify_wait = _env_float("PHARMFLOW_START_DAB_VERIFY_WAIT", 2.0)
    time.sleep(verify_wait)
    xml = _dump_xml(adb, serial)
    if not xml:
        # Dump congestion (watcher/remediator) — do not FAIL a live tap.
        logger.warning(
            "Start Perfect Dab verify dump empty on %s after tap (%d,%d) — treating as started",
            serial,
            cx,
            cy,
        )
        report["timer_started"] = True
        report["verify_dump_empty"] = True
        return report
    report["timer_started"] = _timer_running(xml, tapped_live_bounds=live)
    if report["timer_started"]:
        logger.info("Start Perfect Dab OK timer running on %s at (%d,%d)", serial, cx, cy)
        return report

    # Up to 2 retaps — only while Start is still tappable (retap while running pauses).
    for attempt in range(2):
        if _timer_running(xml, tapped_live_bounds=False) or (
            live and not _find_start_dab_bounds(xml) and xml
        ):
            report["timer_started"] = True
            break
        if not _find_start_dab_bounds(xml) and not _start_dab_node_present(xml) and xml:
            # Home Start gone — timer UI even if markers missing from a11y.
            report["timer_started"] = True
            break
        # CDP always fails on MuMu — skip to ADB tap.
        if False and _cdp_click_start_dab(adb, serial):
            report["timer_started"] = True
            report["coords"] = ("cdp", "click")
            break
        logger.warning(
            "Start Perfect Dab miss at (%d,%d) on %s — scroll+retap %d",
            cx,
            cy,
            serial,
            attempt + 1,
        )
        adb.swipe(x1s, y1s, x2s, y2s, dur + 60, serial=serial)
        report["scrolled"] = report["scrolled"] + 1
        time.sleep(0.55)
        xml = _dump_xml(adb, serial)
        bounds = _find_start_dab_bounds(xml)
        if not bounds:
            # Do not blind-retap fallback if Start is gone — likely already running.
            if xml and not _start_dab_node_present(xml):
                report["timer_started"] = True
                break
            # Low-a11y WebViews (DuckDuckGo) never expose start-dab-btn bounds, so
            # the authored fallback can sit just below the button. Sweep upward: the
            # button is a large target above the stale point.
            cx = fx
            cy = max(900, fy - 70 * (attempt + 1))
            live = False
        else:
            report["bounds"] = list(bounds)
            live = True
            cx, cy = _tap_xy_from_bounds(bounds)
        report["live_bounds"] = live
        ok = adb.tap(cx, cy, serial=serial).ok
        report["tapped"] = bool(ok)
        report["coords"] = (cx, cy)
        if not ok:
            return report
        time.sleep(verify_wait)
        xml = _dump_xml(adb, serial)
        if not xml:
            logger.warning(
                "Start Perfect Dab retry dump empty on %s — treating tap as started",
                serial,
            )
            report["timer_started"] = True
            report["verify_dump_empty"] = True
            return report
        report["timer_started"] = _timer_running(xml, tapped_live_bounds=live)
        if report["timer_started"]:
            logger.info(
                "Start Perfect Dab OK (retry %d) on %s at (%d,%d)",
                attempt + 1,
                serial,
                cx,
                cy,
            )
            return report

    if report["timer_started"]:
        logger.info("Start Perfect Dab OK on %s at %s", serial, report.get("coords"))
    else:
        logger.warning("Start Perfect Dab still not confirmed on %s after retries", serial)
    return report


def dismiss_native_alert(adb: AdbWrapper, serial: str) -> bool:
    """Dismiss Chromium JS alert / 'You must be 21' OK dialogs — one tap only."""
    xml = _dump_xml(adb, serial)
    if "positive_button" not in xml and "message_paragraph" not in xml:
        return False
    for node in xml.split("<node "):
        low = node.lower()
        if "positive_button" not in low and 'text="ok"' not in low:
            if "yes" not in low or "button" not in low:
                continue
        m = _BOUNDS_RE.search(node)
        if m:
            x1, y1, x2, y2 = (int(m.group(i)) for i in range(1, 5))
            if _tap_bounds(adb, serial, x1, y1, x2, y2):
                time.sleep(0.5)
                logger.info("Dismissed native alert on %s", serial)
                return True
    adb.keyevent(66, serial=serial)  # ENTER
    time.sleep(0.4)
    return True


def dismiss_html_age_gate(adb: AdbWrapper, serial: str) -> bool:
    """Tap DabFlow 'Yes, I am 21+' — prefer live age-yes-btn bounds when dumpable."""
    x, y = AGE_GATE_YES
    xml0 = _dump_xml(adb, serial)
    m = re.search(
        r'resource-id="age-yes-btn"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
        r'|bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*resource-id="age-yes-btn"'
        r'|text="[^"]*YES[^"]*21[^"]*"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        xml0,
        re.I,
    )
    if m:
        vals = [int(g) for g in m.groups() if g is not None]
        if len(vals) >= 4:
            x1, y1, x2, y2 = vals[:4]
            x, y = (x1 + x2) // 2, (y1 + y2) // 2
            logger.info("Age gate YES bounds -> (%d,%d) on %s", x, y, serial)
    adb.tap(x, y, serial=serial)
    time.sleep(0.45)
    xml = _dump_xml(adb, serial)
    if "You must be 21" in xml:
        dismiss_native_alert(adb, serial)
        time.sleep(0.25)
        adb.tap(x, y, serial=serial)
        time.sleep(0.4)
        xml = _dump_xml(adb, serial)
    if any(tok in xml for tok in ("MATERIAL", "ad-slot", "START PERFECT", "Quartz", "CUSTOM TIMES")):
        logger.info("Age gate cleared via tap (%d,%d) on %s", x, y, serial)
        return True
    logger.warning("Age gate tap (%d,%d) on %s — home markers not seen in dump", x, y, serial)
    return False


def bypass_splash_and_age_gate(adb: AdbWrapper, serial: str) -> dict[str, Any]:
    """Chromium FRE (once) → settle → native alert → HTML age gate (single YES tap)."""
    report: dict[str, Any] = {"fre": False, "native": False, "age_gate": False}
    report["fre"] = bool(dismiss_chromium_fre(adb, serial))
    time.sleep(random.uniform(0.4, 0.8))
    if dismiss_native_alert(adb, serial):
        report["native"] = True
    report["age_gate"] = bool(dismiss_html_age_gate(adb, serial))
    if dismiss_native_alert(adb, serial):
        report["native"] = True
    return report


def random_site_settle() -> float:
    return random.uniform(0.6, 1.1)


def back_from_advertiser(adb: AdbWrapper, serial: str) -> None:
    """Return from advertiser landing to DabFlow (BACK key)."""
    adb.keyevent(4, serial=serial)
    time.sleep(1.2)
    xml = _dump_xml(adb, serial)
    if "getdabflow" not in xml.lower():
        adb.keyevent(4, serial=serial)
        time.sleep(1.0)
