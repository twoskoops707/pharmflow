"""Hard denylist: farm must never start Camera / Gallery / Settings / dialer / etc.

Used by launch_app, am start / monkey helpers, sequence taps, and remediator
re-arm. Wizard setup may still open Settings via unscoped settings intents.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

FARM_BROWSER_PACKAGES = frozenset(
    {
        "com.farmbrowser.stealth.debug",
        "com.farmbrowser.stealth",
        "org.chromium.chrome",
        "com.android.chrome",
        "com.brave.browser",
        "org.mozilla.firefox",
        "com.duckduckgo.mobile.android",
        "com.opera.browser",
        "com.opera.mini.native",
    }
)

DENIED_LAUNCH_PACKAGES = frozenset(
    {
        "com.android.camera",
        "com.android.camera2",
        "com.android.gallery3d",
        "com.google.android.GoogleCamera",
        "com.google.android.apps.photos",
        "com.android.contacts",
        "com.android.dialer",
        "com.android.phone",
        "com.google.android.dialer",
        "com.google.android.contacts",
        "com.android.vending",
        "com.android.settings",
        "com.android.mms",
        "com.android.messaging",
        "com.google.android.apps.messaging",
        "com.google.android.youtube",
        "com.android.deskclock",
        "com.android.calendar",
        "com.android.music",
        "com.android.documentsui",
        "com.android.calculator2",
        "com.android.email",
        "com.google.android.gm",
        "com.google.android.apps.maps",
        "com.android.soundrecorder",
        "org.codeaurora.snapcam",
        "app.lawnchair",
        "ch.deletescape.lawnchair",
        "com.google.android.apps.nexuslauncher",
    }
)

_DENY_TOKENS = (
    "camera",
    "camcorder",
    "gallery",
    "snapcam",
    "dialer",
    "contacts",
)

_P_RE = re.compile(r"(?:^|\s)-p\s+(\S+)")
_N_RE = re.compile(r"(?:^|\s)-n\s+(\S+)")
_MONKEY_P = re.compile(r"monkey(?:\s+\S+)*\s+-p\s+(\S+)")
_FG_RE = re.compile(r"topResumedActivity=ActivityRecord\{[^ ]+ u0 ([^/]+)/")
_FOCUS_RE = re.compile(r"mFocusedApp=ActivityRecord\{[^ ]+ u0 ([^/]+)/")

_CAPTURE_MARKERS = (
    "IMAGE_CAPTURE",
    "android.media.action.IMAGE_CAPTURE",
    "android.media.action.VIDEO_CAPTURE",
    "android.intent.action.IMAGE_CAPTURE",
)


def package_from_component(component: str) -> str:
    raw = (component or "").strip()
    if not raw:
        return ""
    return raw.split("/", 1)[0].strip()


def is_farm_browser_package(package: str) -> bool:
    pkg = package_from_component(package).lower()
    if not pkg:
        return False
    if pkg in FARM_BROWSER_PACKAGES:
        return True
    if "chromium" in pkg:
        return True
    if pkg.endswith(".chrome") and "vending" not in pkg:
        return True
    if "firefox" in pkg or "brave" in pkg or "duckduckgo" in pkg or "opera" in pkg:
        return True
    return False


def is_launcher_package(package: str) -> bool:
    pkg = (package or "").lower()
    if not pkg:
        return False
    if is_farm_browser_package(pkg):
        return False
    return "lawnchair" in pkg or "launcher" in pkg


def is_denied_launch_package(package: str) -> bool:
    pkg = package_from_component(package)
    if not pkg:
        return False
    if is_farm_browser_package(pkg):
        return False
    low = pkg.lower()
    if low in {p.lower() for p in DENIED_LAUNCH_PACKAGES}:
        return True
    return any(token in low for token in _DENY_TOKENS)


def extract_launch_package(command: str) -> str:
    cmd = (command or "").strip()
    m = _MONKEY_P.search(cmd)
    if m:
        return package_from_component(m.group(1))
    m = _P_RE.search(cmd)
    if m:
        return package_from_component(m.group(1))
    m = _N_RE.search(cmd)
    if m:
        return package_from_component(m.group(1))
    return ""


def blocked_launch_reason(command: str) -> str | None:
    """Return a reason if this shell command must not run on the farm."""
    cmd = (command or "").strip()
    if not cmd:
        return None
    low = cmd.lower()
    is_start = low.startswith("am start") or " am start " in f" {low}"
    is_monkey = low.startswith("monkey ") or low.startswith("monkey\t")
    if not is_start and not is_monkey:
        return None
    for marker in _CAPTURE_MARKERS:
        if marker.lower() in low:
            return f"denied capture intent ({marker})"
    pkg = extract_launch_package(cmd)
    if pkg and is_denied_launch_package(pkg):
        return f"denied package {pkg}"
    return None


def parse_foreground_package(dumpsys_text: str) -> str:
    text = dumpsys_text or ""
    m = _FG_RE.search(text) or _FOCUS_RE.search(text)
    return m.group(1) if m else ""


def package_from_top_line(top: str) -> str:
    """Parse remediator/dumpsys 'top' strings into a package name."""
    t = (top or "").strip()
    if not t:
        return ""
    if t.startswith("ACTIVITY "):
        rest = t.split(None, 1)[-1]
        return package_from_component(rest.split()[0] if rest else "")
    if "/" in t:
        return package_from_component(t.split()[0])
    return package_from_component(t.split()[0] if t.split() else t)


def skip_tap_reason_for_fg(fg_package: str) -> str | None:
    """If set, sequence/remediator must not tap (home dock would open Camera)."""
    fg = (fg_package or "").strip()
    if not fg:
        return None
    if is_farm_browser_package(fg):
        return None
    if is_denied_launch_package(fg) or is_launcher_package(fg):
        return fg
    low = fg.lower()
    if "permissioncontroller" in low or "systemui" in low or "packageinstaller" in low:
        return fg
    return None


def foreground_package(adb: Any, serial: str) -> str:
    try:
        out = adb.shell("dumpsys activity activities", serial=serial, timeout=3.5)
        text = (getattr(out, "stdout", None) or "") if out is not None else ""
        return parse_foreground_package(text)
    except Exception:
        logger.debug("fg package probe failed serial=%s", serial, exc_info=True)
        return ""


def should_skip_content_tap(adb: Any, serial: str) -> str | None:
    return skip_tap_reason_for_fg(foreground_package(adb, serial))


_DABFLOW_HOME = "https://getdabflow.app/"
_FARMBROWSER_ACTIVITY = "com.farmbrowser.stealth.browser.BrowserActivity"


def bring_browser_foreground_dabflow(
    adb: Any,
    serial: str,
    package: str,
    *,
    force_stop_fg: str | None = None,
) -> bool:
    """Put the money browser on dabflow and verify it actually owns FG.

    Fire-and-forget ``am start -p`` left Settings/Gallery on top → Path3
    ``foreign_fg`` FAIL. Force-stop denied FG, component-start FarmBrowser when
    possible, then re-read ``topResumedActivity``.
    """
    pkg = (package or "").strip() or "com.farmbrowser.stealth.debug"
    try:
        if force_stop_fg and (
            is_denied_launch_package(force_stop_fg) or is_launcher_package(force_stop_fg)
        ):
            adb.shell(f"am force-stop {force_stop_fg}", serial=serial, timeout=6.0)
            time.sleep(0.45)
        if "farmbrowser" in pkg.lower():
            adb.shell(
                f'am start -a android.intent.action.VIEW -d "{_DABFLOW_HOME}" '
                f"-n {pkg}/{_FARMBROWSER_ACTIVITY}",
                serial=serial,
                timeout=10.0,
            )
        else:
            adb.shell(
                f'am start -a android.intent.action.VIEW -d "{_DABFLOW_HOME}" -p {pkg}',
                serial=serial,
                timeout=10.0,
            )
        time.sleep(0.85)
        fg = foreground_package(adb, serial)
        ok = bool(fg) and (
            is_farm_browser_package(fg) or fg == pkg or skip_tap_reason_for_fg(fg) is None
        )
        logger.info(
            "FG dabflow serial=%s pkg=%s fg=%s ok=%s",
            serial,
            pkg,
            fg or "-",
            ok,
        )
        return ok
    except Exception as exc:
        logger.warning("FG dabflow soft-fail serial=%s pkg=%s: %s", serial, pkg, exc)
        return False
