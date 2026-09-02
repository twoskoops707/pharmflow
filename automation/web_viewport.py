"""Per-browser web viewport calibration so recorded taps land in every browser.

All DabFlow sequences were recorded in Chromium at 900x1600, where the page area
is [0,160]-[900,1600]. Other browsers reserve different chrome, measured live:

    Chromium  page [0,160]-[900,1600]  h=1440   (top toolbar only)
    Brave     page [0,160]-[900,1504]  h=1344   (top toolbar + bottom toolbar)
    Firefox   page [0,176]-[900,1600]  h=1424   (taller top toolbar)

So a recorded y is up to ~60px off in Firefox/Brave — enough to miss a button and
leave the sequence "just sitting there". Taps are remapped from the authoring
viewport into the live one instead of re-recording thousands of sequences per
browser, and the live rect is read from the page's own root node when available so
a browser update that changes toolbar height self-corrects.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from automation.config import (
    BROWSER_BRAVE,
    BROWSER_CHROMIUM,
    BROWSER_DUCKDUCKGO,
    BROWSER_FIREFOX,
)

logger = logging.getLogger(__name__)

_BOUNDS_RE = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
_RESOURCE_ID_RE = re.compile(r'resource-id="([^"]*)"')

# Page-root candidates, best first. DabFlow's #age-gate / #app are full-viewport.
_PAGE_ROOT_IDS = ("age-gate", "app", "app-root")
_ENGINE_VIEW_IDS = (
    "org.mozilla.firefox:id/engineView",
    "org.mozilla.firefox:id/swipeRefresh",
    "com.duckduckgo.mobile.android:id/webViewContainer",
    "com.duckduckgo.mobile.android:id/swipeRefreshContainer",
)
_WEBVIEW_CLASSES = ("android.webkit.WebView",)


@dataclass(frozen=True)
class WebViewport:
    top: int
    bottom: int

    @property
    def height(self) -> int:
        return max(1, self.bottom - self.top)


# Chromium 900x1600 — every sequence's recorded coordinate space.
AUTHOR_VIEWPORT = WebViewport(top=160, bottom=1600)

# Measured on the farm; used when a UI dump is unavailable or implausible.
KNOWN_VIEWPORTS: dict[str, WebViewport] = {
    BROWSER_CHROMIUM: WebViewport(160, 1600),
    BROWSER_BRAVE: WebViewport(160, 1504),
    BROWSER_FIREFOX: WebViewport(176, 1600),
    # DuckDuckGo: measured live — webViewContainer [0,176]-[900,1600] on 900x1600.
    BROWSER_DUCKDUCKGO: WebViewport(176, 1600),
}

# Screen is 900x1600; a page rect outside these bounds means we parsed the wrong node.
_MIN_PLAUSIBLE_HEIGHT = 1000
_MAX_PLAUSIBLE_HEIGHT = 1600
_MIN_PLAUSIBLE_WIDTH = 800

_live_viewports: dict[str, WebViewport] = {}


def viewport_from_dump(xml: str) -> WebViewport | None:
    """Read the live page rect from a uiautomator dump, or None if not found."""
    if not xml:
        return None
    best: tuple[int, WebViewport] | None = None
    for chunk in xml.split("<node ")[1:]:
        rid_match = _RESOURCE_ID_RE.search(chunk)
        rid = rid_match.group(1) if rid_match else ""
        is_root = rid in _PAGE_ROOT_IDS
        is_engine = rid in _ENGINE_VIEW_IDS
        is_webview = any(f'class="{cls}"' in chunk for cls in _WEBVIEW_CLASSES)
        if not (is_root or is_engine or is_webview):
            continue
        bounds = _BOUNDS_RE.search(chunk)
        if not bounds:
            continue
        x1, y1, x2, y2 = (int(bounds.group(i)) for i in range(1, 5))
        if x2 - x1 < _MIN_PLAUSIBLE_WIDTH:
            continue
        height = y2 - y1
        if not _MIN_PLAUSIBLE_HEIGHT <= height <= _MAX_PLAUSIBLE_HEIGHT:
            continue
        # Prefer the page root (#age-gate) over engineView over a bare WebView.
        rank = 0 if is_root else (1 if is_engine else 2)
        if best is None or rank < best[0]:
            best = (rank, WebViewport(top=y1, bottom=y2))
    return best[1] if best else None


def calibrate(serial: str, *, xml: str = "", package: str = "") -> WebViewport:
    """Cache the viewport for a serial from a dump, falling back to measured values."""
    vp = viewport_from_dump(xml)
    source = "dump"
    if vp is None:
        vp = KNOWN_VIEWPORTS.get((package or "").strip(), AUTHOR_VIEWPORT)
        source = "known"
    previous = _live_viewports.get(serial)
    _live_viewports[serial] = vp
    if previous != vp:
        logger.info(
            "web viewport %s (%s) top=%d bottom=%d h=%d src=%s",
            serial,
            package or "?",
            vp.top,
            vp.bottom,
            vp.height,
            source,
        )
    return vp


def set_viewport_for_package(serial: str, package: str) -> WebViewport:
    """Seed the measured viewport for a package before the page is loaded."""
    vp = KNOWN_VIEWPORTS.get((package or "").strip(), AUTHOR_VIEWPORT)
    _live_viewports[serial] = vp
    return vp


def clear_viewport(serial: str) -> None:
    _live_viewports.pop(serial, None)


def get_viewport(serial: str) -> WebViewport | None:
    return _live_viewports.get(serial)


def remap_y(serial: str, y: int) -> int:
    """Map an authored Chromium y into the live browser viewport.

    Mobile WebViews do **not** uniformly scale page layout when the chrome
    changes. Brave keeps the same top inset as Chromium and only adds a bottom
    toolbar — linear height scaling shoved Path1 heater/tab taps up into the
    Mantis ad band (clicks burned with ads off). Use an offset-only remap:
    shift by top-chrome delta, then pull any tap that would land in the bottom
    browser chrome up into the live page (sticky DabFlow nav).
    """
    vp = _live_viewports.get(serial)
    if vp is None or vp == AUTHOR_VIEWPORT:
        return int(y)
    dy = int(vp.top) - int(AUTHOR_VIEWPORT.top)
    mapped = int(y) + dy
    # Authored nav / bottom controls sit near y=1535 on Chromium. On Brave the
    # page ends ~1504 — keep those taps on the in-page sticky nav, not the
    # browser's own bottom toolbar and not scaled into mid-page ads.
    if mapped >= int(vp.bottom):
        mapped = int(vp.bottom) - 48
    if mapped < int(vp.top):
        mapped = int(vp.top) + 8
    return int(mapped)


def remap_tap(serial: str, x: int, y: int) -> tuple[int, int]:
    return int(x), remap_y(serial, y)


def element_center(xml: str, element_id: str) -> tuple[int, int] | None:
    """Center of a web element by its HTML id (exposed as resource-id in dumps)."""
    if not xml or not element_id:
        return None
    for chunk in xml.split("<node ")[1:]:
        rid_match = _RESOURCE_ID_RE.search(chunk)
        if not rid_match or rid_match.group(1) != element_id:
            continue
        bounds = _BOUNDS_RE.search(chunk)
        if not bounds:
            continue
        x1, y1, x2, y2 = (int(bounds.group(i)) for i in range(1, 5))
        return ((x1 + x2) // 2, (y1 + y2) // 2)
    return None
