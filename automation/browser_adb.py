"""Browser management — prefer Chromium (setup-installed), then MuMu/system fallback."""

from __future__ import annotations

import base64
import json
import logging
import os
import random
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from automation.adb_wrapper import AdbWrapper
from automation.browser_onboarding import (
    dismiss_brave_overlays,
    dismiss_blocking_browser_overlays,
    dismiss_duckduckgo_onboarding,
    dismiss_firefox_onboarding,
    dismiss_opera_welcome,
    dismiss_ssl_interstitial,
    duckduckgo_onboarding_visible,
    firefox_onboarding_visible,
    firefox_page_ready,
    firefox_still_booting,
    brave_overlay_visible,
    opera_welcome_visible,
    prepare_firefox_after_wipe,
    seed_duckduckgo_onboarding_complete,
    seed_firefox_onboarding_complete,
    seed_opera_onboarding_complete,
    ssl_hsts_blocked,
    ssl_interstitial_visible,
)
from automation.browser_privacy import apply_browser_privacy
from automation.config import (
    BROWSER_BRAVE,
    BROWSER_CHROMIUM,
    BROWSER_DUCKDUCKGO,
    BROWSER_FARMBROWSER,
    BROWSER_FARMBROWSER_RELEASE,
    BROWSER_FIREFOX,
    BROWSER_MUMU,
    BROWSER_OPERA,
    BROWSER_PATH12_WEIGHTS,
)
from automation.web_viewport import (
    calibrate,
    clear_viewport,
    element_center,
    remap_tap,
    set_viewport_for_package,
)

if TYPE_CHECKING:
    from automation.browser_identity import BrowserSessionProfile

logger = logging.getLogger(__name__)

# Shared with scripts/farm_fail_review.py — wait bumps applied without farm restart.
_RUNTIME_OVERRIDES = Path(r"C:\CPharm\logs\farm_runtime_overrides.json")
_overrides_cache_mtime: float = -1.0
_overrides_cache: dict[str, str] = {}


class BrowserKind(Enum):
    FARMBROWSER = "farmbrowser"
    CHROMIUM = "chromium"
    BRAVE = "brave"
    FIREFOX = "firefox"
    DUCKDUCKGO = "duckduckgo"
    OPERA = "opera"
    MUMU = "mumu"
    SYSTEM = "system"


@dataclass
class BrowserInfo:
    kind: BrowserKind
    package: str
    activity: str
    label: str


MUMU_ACTIVITY = "com.mumudroid.browser/.BrowserActivity"
CHROMIUM_ACTIVITY = "org.chromium.chrome/com.google.android.apps.chrome.Main"
CHROME_STOCK = "com.android.chrome"
CHROME_STOCK_ACTIVITY = "com.android.chrome/com.google.android.apps.chrome.Main"
BRAVE_ACTIVITY = "com.brave.browser/com.google.android.apps.chrome.Main"
FIREFOX_ACTIVITY = "org.mozilla.firefox/org.mozilla.fenix.IntentReceiverActivity"
# DuckDuckGo launch gate then BrowserActivity; VIEW intents resolve via package.
DUCKDUCKGO_ACTIVITY = (
    "com.duckduckgo.mobile.android/com.duckduckgo.app.browser.BrowserActivity"
)
DUCKDUCKGO_LAUNCHER = (
    "com.duckduckgo.mobile.android/com.duckduckgo.app.launch.Launcher"
)
# Verified live: am start VIEW → com.opera.android.BrowserActivity (aliases target it).
OPERA_ACTIVITY = "com.opera.browser/com.opera.android.BrowserActivity"
FARMBROWSER_ACTIVITY = (
    "com.farmbrowser.stealth.debug/com.farmbrowser.stealth.browser.BrowserActivity"
)
FARMBROWSER_ACTIVITY_RELEASE = (
    "com.farmbrowser.stealth/com.farmbrowser.stealth.browser.BrowserActivity"
)
SYSTEM_BROWSER = "com.android.browser"
SYSTEM_ACTIVITY = "com.android.browser/.BrowserActivity"

# Chromium-family kinds that share FRE / chrome-command-line behavior.
# Opera is Chromium-based; MITM is skipped separately (own CA trust).
_CHROMIUM_FAMILY = (BrowserKind.CHROMIUM, BrowserKind.BRAVE, BrowserKind.OPERA)

# Portrait 900x1600 — FRE "Stay signed out" / Skip button center.
# MUST stay below the DabFlow age-gate Yes/No row (~y 920–1120). Tapping
# (450,1127) while the gate is painted hits the No / under-21 button.
CHROMIUM_SKIP_TAP = (450, 1280)
# After pm clear, FRE paints slowly — dump-too-early falsely reports "not visible".
# Same class of bug as age-gate 80ms: wait for splash to actually paint.
_FRE_PAINT_WAIT_S = 4.5
_FRE_PAINT_POLL_S = 0.45
# Keep in sync with dabflow_overlays.AGE_GATE_* (avoid circular import).
# Live-proven Yes center (Brave/Chromium 900x1600): left button ~[90,926][442,1076].
# Old (380,980) sat on the top-right edge of Yes — humanize jitter could miss.
_DABFLOW_AGE_GATE_YES = (270, 1020)
_DABFLOW_AGE_GATE_YES_ID = "age-yes-btn"
_DABFLOW_AGE_GATE_NO_ID = "age-no-btn"
_DABFLOW_AGE_GATE_LOAD_WAIT_S = 1.5
_DABFLOW_AGE_GATE_POST_YES_SETTLE_S = 0.55
# Fenix needs the Terms screen to paint before we can tell whether the seed worked.
_FIREFOX_ONBOARDING_WAIT_S = 2.5
# DuckDuckGo Welcome / widget / AI-picker paint window after VIEW.
_DUCKDUCKGO_ONBOARDING_WAIT_S = 2.8


def _runtime_overrides() -> dict[str, str]:
    """Load fail-review wait bumps (mtime-cached)."""
    global _overrides_cache_mtime, _overrides_cache
    try:
        mtime = _RUNTIME_OVERRIDES.stat().st_mtime
    except OSError:
        _overrides_cache_mtime = -1.0
        _overrides_cache = {}
        return _overrides_cache
    if mtime == _overrides_cache_mtime:
        return _overrides_cache
    try:
        data = json.loads(_RUNTIME_OVERRIDES.read_text(encoding="utf-8"))
        _overrides_cache = {
            str(k): str(v)
            for k, v in (data or {}).items()
            if str(k).startswith("CPHARM_")
        }
        _overrides_cache_mtime = mtime
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return _overrides_cache


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        raw = (_runtime_overrides().get(name) or "").strip()
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


def fre_paint_wait_s() -> float:
    return _env_float("CPHARM_FRE_PAINT_WAIT", _FRE_PAINT_WAIT_S)


def firefox_onboarding_wait_s() -> float:
    return _env_float("CPHARM_FIREFOX_ONBOARDING_WAIT", _FIREFOX_ONBOARDING_WAIT_S)


def duckduckgo_onboarding_wait_s() -> float:
    return _env_float("CPHARM_DUCKDUCKGO_ONBOARDING_WAIT", _DUCKDUCKGO_ONBOARDING_WAIT_S)


def dabflow_age_gate_load_wait_s() -> float:
    """Seconds to wait for the age-gate Yes button to paint — not for ads.

    Age gate has no Mantis creatives. Do **not** inherit CPHARM_DABFLOW_LOAD_WAIT
    (that wait is for home/tab ad paint / evCPM dwell). Keep this short.
    """
    # Hard ceiling so a mistaken long override cannot stall every open_url.
    return min(2.0, max(0.2, _env_float("CPHARM_AGE_GATE_WAIT", _DABFLOW_AGE_GATE_LOAD_WAIT_S)))

_prepared_serials: set[str] = set()

# Chromium user-data paths (wiped by pm clear; listed for explicit cache purge fallback).
_CHROMIUM_DATA_DIRS = (
    "/data/data/org.chromium.chrome",
    "/data/data/org.chromium.chrome/app_chrome",
    "/data/data/org.chromium.chrome/cache",
    "/data/data/org.chromium.chrome/app_webview",
)


# Seeded into shared_prefs after every pm clear so Chromium never re-shows the
# First Run Experience (Stay-signed-out / sign-in promo / default-browser).
# pm clear wipes sentinels; without these, every sequence battles FRE instead of
# loading the site. Canonical Chromium key is ``first_run_flow`` (ChromePreferenceKeys);
# farm Chromium builds also honor ``first_run_flow_complete`` — write both.
# ``applink.chrome_default_browser=true`` suppresses DefaultBrowserPromo sheets
# (verified live: phones had it false → endless "set as default" / setup prompts).
_FRE_COMPLETE_PREFS_XML = (
    '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
    "<map>\n"
    # Canonical + legacy FRE-complete keys
    '<boolean name="first_run_flow" value="true" />\n'
    '<boolean name="first_run_flow_complete" value="true" />\n'
    '<boolean name="Chrome.FirstRun.FirstRunFlowComplete" value="true" />\n'
    '<boolean name="lightweight_first_run_flow" value="true" />\n'
    '<boolean name="first_run_tos_accepted" value="true" />\n'
    '<boolean name="Chrome.FirstRun.TosAccepted" value="true" />\n'
    '<boolean name="Chrome.FirstRun.SkipWelcomePage" value="true" />\n'
    '<boolean name="skip_welcome_page" value="true" />\n'
    '<boolean name="first_run_signin_complete" value="true" />\n'
    '<boolean name="promos_skipped_on_first_start" value="true" />\n'
    # Lie "already default" so Chromium/Brave stop ROLE_BROWSER / promo sheets.
    '<boolean name="applink.chrome_default_browser" value="true" />\n'
    '<int name="Chrome.DefaultBrowserPromo.PromoedCount" value="99" />\n'
    '<int name="Chrome.DefaultBrowserPromo.SessionCount" value="99" />\n'
    '<long name="Chrome.DefaultBrowserPromo.LastPromoTime" value="4102444800000" />\n'
    # MuMu is ro.debuggable=0 — without this CachedFlag, chrome-command-line
    # (and --remote-debugging-port for Mantis CDP) is ignored so ad slots stay empty.
    '<boolean name="Chrome.Flags.CachedFlag.CommandLineOnNonRooted" value="true" />\n'
    "</map>\n"
)

# Boolean FRE / default-browser keys merged into existing prefs (wipe or mid-run).
_FRE_BOOL_PREFS: dict[str, bool] = {
    "first_run_flow": True,
    "first_run_flow_complete": True,
    "Chrome.FirstRun.FirstRunFlowComplete": True,
    "lightweight_first_run_flow": True,
    "first_run_tos_accepted": True,
    "Chrome.FirstRun.TosAccepted": True,
    "Chrome.FirstRun.SkipWelcomePage": True,
    "skip_welcome_page": True,
    "first_run_signin_complete": True,
    "promos_skipped_on_first_start": True,
    "applink.chrome_default_browser": True,
    "Chrome.Flags.CachedFlag.CommandLineOnNonRooted": True,
}


def _write_prefs_xml_to_device(
    adb: AdbWrapper,
    serial: str,
    prefs_file: str,
    xml_body: str,
    uid_gid: str,
) -> bool:
    """Write SharedPreferences XML without blowing Windows CreateProcess limits.

    Large Chromium prefs (100KB+) cannot be ``echo $b64 | base64 -d`` via adb.exe
    (WinError 206). Prefer ``adb push`` then on-device ``cp``.
    """
    remote = f"/data/local/tmp/cpharm_fre_prefs_{abs(hash(serial)) % 10_000_000}.xml"
    local_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".xml", delete=False
        ) as tmp:
            tmp.write(xml_body if xml_body.endswith("\n") else xml_body + "\n")
            local_path = tmp.name
        pushed = adb.push(local_path, remote, serial=serial)
        if pushed.ok:
            write = adb.shell(
                f"cp {remote} {prefs_file} && chown {uid_gid} {prefs_file} "
                f"&& chmod 660 {prefs_file} && restorecon {prefs_file} 2>/dev/null; "
                f"rm -f {remote}",
                serial=serial,
            )
            return bool(write.ok)
        # Small payloads: fall back to base64 echo (wipe / empty prefs).
        b64 = base64.b64encode(xml_body.encode("utf-8")).decode("ascii")
        if len(b64) > 24_000:
            logger.warning(
                "FRE prefs push failed and payload too large for echo on %s",
                serial,
            )
            return False
        write = adb.shell(f"echo {b64} | base64 -d > {prefs_file}", serial=serial)
        adb.shell(f"chown {uid_gid} {prefs_file}", serial=serial)
        adb.shell(f"chmod 660 {prefs_file}", serial=serial)
        adb.shell(f"restorecon {prefs_file} 2>/dev/null", serial=serial)
        return bool(write.ok)
    finally:
        if local_path:
            try:
                os.unlink(local_path)
            except OSError:
                pass


def _seed_fre_complete(adb: AdbWrapper, serial: str, pkg: str) -> bool:
    """Mark Chromium/Brave First Run + default-browser promo complete.

    Merges into existing SharedPreferences when present so we do not wipe runtime
    flags; after ``pm clear`` the file is empty and we write the full seed XML.
    """
    from automation.browser_privacy import merge_boolean_prefs_xml

    prefs_dir = f"/data/data/{pkg}/shared_prefs"
    prefs_file = f"{prefs_dir}/{pkg}_preferences.xml"
    owner = adb.shell(f"stat -c '%u:%g' /data/data/{pkg}", serial=serial)
    uid_gid = (owner.stdout or "").strip() or "shell:shell"
    adb.shell(f"mkdir -p {prefs_dir}", serial=serial)
    existing = adb.shell(f"cat {prefs_file}", serial=serial)
    body = (existing.stdout or "").strip()
    if body and "<map" in body:
        merged = merge_boolean_prefs_xml(body, _FRE_BOOL_PREFS)
        # Ensure promo-count ints exist (merge_boolean_prefs_xml is bool-only).
        for snip in (
            '<int name="Chrome.DefaultBrowserPromo.PromoedCount" value="99" />',
            '<int name="Chrome.DefaultBrowserPromo.SessionCount" value="99" />',
            '<long name="Chrome.DefaultBrowserPromo.LastPromoTime" value="4102444800000" />',
        ):
            name = snip.split('name="', 1)[1].split('"', 1)[0]
            if name not in merged:
                merged = merged.replace("</map>", f"    {snip}\n</map>", 1)
            else:
                # Force high counts so promo does not re-arm after a few sessions.
                tag = "long" if snip.startswith("<long") else "int"
                merged = re.sub(
                    rf'<{tag}\s+name="{re.escape(name)}"\s+value="[^"]*"\s*/>',
                    snip,
                    merged,
                    count=1,
                )
        xml_body = merged
    else:
        xml_body = _FRE_COMPLETE_PREFS_XML
    ok = _write_prefs_xml_to_device(adb, serial, prefs_file, xml_body, uid_gid)
    if ok:
        logger.info("Seeded FRE-complete pref on %s (%s owner=%s)", serial, pkg, uid_gid)
    else:
        logger.warning("FRE-complete seed may have failed on %s (%s)", serial, pkg)
    return ok


def clear_chromium_all_data(adb: AdbWrapper, serial: str, *, package: str = BROWSER_CHROMIUM) -> bool:
    """Wipe Chromium history, cookies, cache, and all site storage before a sequence."""
    packages = set(adb.pm_list_packages(serial=serial))
    pkg = package if package in packages else None
    if pkg is None and CHROME_STOCK in packages:
        pkg = CHROME_STOCK
    if pkg is None:
        logger.warning("clear_chromium_all_data: no Chromium package on %s", serial)
        return False

    adb.shell(f"am force-stop {pkg}", serial=serial)
    result = adb.shell(f"pm clear {pkg}", serial=serial)
    ok = result.ok or "Success" in (result.stdout or "")
    if not ok:
        for path in _CHROMIUM_DATA_DIRS:
            adb.shell(f"rm -rf {path}/*", serial=serial)
        verify = adb.shell(f"pm clear {pkg}", serial=serial)
        ok = verify.ok or "Success" in (verify.stdout or "")

    _prepared_serials.discard(serial)
    if ok:
        # Re-seed FRE-complete immediately: pm clear removed the sentinel and
        # onboarding would otherwise block the site on every sequence.
        _seed_fre_complete(adb, serial, pkg)
        # Best-effort telemetry/crash/sync opt-outs (does not claim zero exfil).
        apply_browser_privacy(adb, serial, pkg)
        # Opera WelcomeActivity ignores Chromium FRE — seed OEM onboarding too.
        if pkg == BROWSER_OPERA:
            seed_opera_onboarding_complete(adb, serial, pkg)
        logger.info("Cleared Chromium history/cookies/site data on %s (%s)", serial, pkg)
    else:
        logger.warning("Chromium data clear may be incomplete on %s (%s)", serial, pkg)
    return ok


_BOUNDS_RE = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
# Only Stay signed out / Skip — never Help, Manage, Terms, Continue, voice search.
_DISMISS_IDS = ("signin_fre_dismiss_button",)
_DISMISS_TEXTS = ("stay signed out", "use without an account", "use without an account")
_FRE_BLOCKLIST = (
    "help",
    "learn more",
    "voice",
    "search",
    "settings",
    "continue as",
    "add account",
    "terms of service",
    "manage",
    "fre_footer",
)
_OMNIBOX_IDS = ("url_bar", "omnibox", "search_box", "location_bar")


def browser_info_for_package(package: str) -> BrowserInfo | None:
    """Map a known package name to BrowserInfo (installed or not)."""
    pkg = (package or "").strip()
    if pkg in (BROWSER_FARMBROWSER, BROWSER_FARMBROWSER_RELEASE):
        act = (
            FARMBROWSER_ACTIVITY
            if pkg == BROWSER_FARMBROWSER
            else FARMBROWSER_ACTIVITY_RELEASE
        )
        return BrowserInfo(BrowserKind.FARMBROWSER, pkg, act, "FarmBrowser")
    if pkg == BROWSER_CHROMIUM:
        return BrowserInfo(BrowserKind.CHROMIUM, BROWSER_CHROMIUM, CHROMIUM_ACTIVITY, "Chromium")
    if pkg == CHROME_STOCK:
        return BrowserInfo(BrowserKind.CHROMIUM, CHROME_STOCK, CHROME_STOCK_ACTIVITY, "Chrome")
    if pkg == BROWSER_BRAVE:
        return BrowserInfo(BrowserKind.BRAVE, BROWSER_BRAVE, BRAVE_ACTIVITY, "Brave")
    if pkg == BROWSER_FIREFOX:
        return BrowserInfo(BrowserKind.FIREFOX, BROWSER_FIREFOX, FIREFOX_ACTIVITY, "Firefox")
    if pkg == BROWSER_DUCKDUCKGO:
        return BrowserInfo(
            BrowserKind.DUCKDUCKGO, BROWSER_DUCKDUCKGO, DUCKDUCKGO_ACTIVITY, "DuckDuckGo"
        )
    if pkg == BROWSER_OPERA:
        return BrowserInfo(BrowserKind.OPERA, BROWSER_OPERA, OPERA_ACTIVITY, "Opera")
    if pkg == BROWSER_MUMU:
        return BrowserInfo(BrowserKind.MUMU, BROWSER_MUMU, MUMU_ACTIVITY, "MuMu Browser")
    if pkg == SYSTEM_BROWSER:
        return BrowserInfo(BrowserKind.SYSTEM, SYSTEM_BROWSER, SYSTEM_ACTIVITY, "System Browser")
    return None


def select_chromium_browser(adb: AdbWrapper, serial: str) -> BrowserInfo | None:
    packages = set(adb.pm_list_packages(serial=serial))
    for pkg in (BROWSER_FARMBROWSER, BROWSER_FARMBROWSER_RELEASE):
        if pkg in packages:
            return browser_info_for_package(pkg)
    if BROWSER_CHROMIUM in packages:
        return BrowserInfo(BrowserKind.CHROMIUM, BROWSER_CHROMIUM, CHROMIUM_ACTIVITY, "Chromium")
    if CHROME_STOCK in packages:
        return BrowserInfo(BrowserKind.CHROMIUM, CHROME_STOCK, CHROME_STOCK_ACTIVITY, "Chrome")
    return None


def select_mumu_browser(adb: AdbWrapper, serial: str) -> BrowserInfo | None:
    packages = set(adb.pm_list_packages(serial=serial))
    if BROWSER_MUMU in packages:
        return BrowserInfo(BrowserKind.MUMU, BROWSER_MUMU, MUMU_ACTIVITY, "MuMu Browser")
    return None


def select_browser(adb: AdbWrapper, serial: str) -> BrowserInfo | None:
    packages = set(adb.pm_list_packages(serial=serial))
    for pkg in (BROWSER_FARMBROWSER, BROWSER_FARMBROWSER_RELEASE):
        if pkg in packages:
            return browser_info_for_package(pkg)
    if BROWSER_CHROMIUM in packages:
        return BrowserInfo(BrowserKind.CHROMIUM, BROWSER_CHROMIUM, CHROMIUM_ACTIVITY, "Chromium")
    if CHROME_STOCK in packages:
        return BrowserInfo(BrowserKind.CHROMIUM, CHROME_STOCK, CHROME_STOCK_ACTIVITY, "Chrome")
    # Never fall back to MuMu / system browser — those look ancient and steal
    # focus from Chromium/Brave/FF/DDG during Path1–3. Prefer VIEW intent.
    if BROWSER_MUMU in packages or SYSTEM_BROWSER in packages:
        logger.warning(
            "Chromium missing on %s — refusing MuMu/system browser; using VIEW intent",
            serial,
        )
    logger.warning("No known browser package on %s — using generic VIEW intent", serial)
    return BrowserInfo(BrowserKind.SYSTEM, "", "", "Default VIEW")


def select_browser_weighted(
    adb: AdbWrapper,
    serial: str,
    *,
    force_chromium: bool = False,
    rng: random.Random | None = None,
) -> BrowserInfo | None:
    """Pick a browser for Path1/2 (weighted) or force Chromium for Path3."""
    if force_chromium:
        return select_chromium_browser(adb, serial) or select_browser(adb, serial)

    packages = set(adb.pm_list_packages(serial=serial))
    candidates: list[tuple[BrowserInfo, int]] = []
    for pkg, weight in BROWSER_PATH12_WEIGHTS.items():
        if weight <= 0 or pkg not in packages:
            continue
        info = browser_info_for_package(pkg)
        if info is not None:
            candidates.append((info, int(weight)))

    if not candidates:
        return select_browser(adb, serial)

    r = rng or random.Random()
    pick = r.choices(
        [c[0] for c in candidates],
        weights=[c[1] for c in candidates],
        k=1,
    )[0]
    logger.info(
        "Path1/2 browser pick serial=%s -> %s (%s)",
        serial,
        pick.label,
        pick.package,
    )
    return pick


def clear_browser_package(adb: AdbWrapper, serial: str, package: str) -> bool:
    """Force-stop + pm clear any browser package; Chromium-family re-seeds FRE."""
    pkg = (package or "").strip()
    if not pkg:
        return False
    packages = set(adb.pm_list_packages(serial=serial))
    if pkg not in packages:
        logger.warning("clear_browser_package: %s not installed on %s", pkg, serial)
        return False

    info = browser_info_for_package(pkg)
    if info is not None and info.kind in _CHROMIUM_FAMILY:
        return clear_chromium_all_data(adb, serial, package=pkg)

    adb.shell(f"am force-stop {pkg}", serial=serial)
    result = adb.shell(f"pm clear {pkg}", serial=serial)
    ok = result.ok or "Success" in (result.stdout or "")
    _prepared_serials.discard(serial)
    clear_viewport(serial)
    if ok and pkg == BROWSER_FIREFOX:
        # pm clear wipes Terms/splash prefs — reseed + warm dabflow last-tab so
        # Path1/2 launch_app does not land on Firefox Home / splash junk.
        prepare_firefox_after_wipe(adb, serial, pkg, dump_ui=_dump_ui)
    elif ok and pkg == BROWSER_DUCKDUCKGO:
        # pm clear wipes Room userStage → OnboardingActivity; seed ESTABLISHED + privacy.
        seed_duckduckgo_onboarding_complete(adb, serial, pkg)
    elif ok:
        # Other non-Chromium packages: privacy seed after wipe.
        apply_browser_privacy(adb, serial, pkg)
    if ok:
        logger.info("Cleared browser data on %s (%s)", serial, pkg)
    else:
        logger.warning("Browser clear may be incomplete on %s (%s)", serial, pkg)
    return ok


def _tap_center(adb: AdbWrapper, serial: str, x1: int, y1: int, x2: int, y2: int) -> bool:
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    return adb.tap(cx, cy, serial=serial).ok


# Cap concurrent uiautomator dumps — 8×12s dumps deadlocked ADB and froze the farm.
# Shared across every dump path (browser_adb, ad_slot_pick, dabflow_overlays) so
# 10 phones can never stack more than 2 concurrent uiautomator dumps on the ADB server.
_UI_DUMP_SEM = threading.Semaphore(2)

# Per-serial dump circuit breaker: when uiautomator is wedged (host CPU oversubscribed,
# VM starved), every dump attempt costs its full timeout and the caller falls back to
# fixed coords anyway. After 3 straight failures, skip dump attempts for 45s so the
# farm stops paying 1.5s×N per sequence on a phone whose uiautomator cannot answer.
_DUMP_FAIL_COUNT: dict[str, int] = {}
_DUMP_SKIP_UNTIL: dict[str, float] = {}
_DUMP_BREAKER_MAX_FAILS = 3
_DUMP_BREAKER_COOLDOWN_S = 45.0


def dump_breaker_skip(serial: str) -> bool:
    """True when this serial's uiautomator is on cooldown — callers should fall back."""
    until = _DUMP_SKIP_UNTIL.get(serial, 0.0)
    if time.time() >= until:
        return False
    return True


def dump_breaker_note(serial: str, ok: bool) -> None:
    """Feed dump outcomes into the per-serial circuit breaker."""
    if ok:
        _DUMP_FAIL_COUNT.pop(serial, None)
        _DUMP_SKIP_UNTIL.pop(serial, None)
        return
    n = _DUMP_FAIL_COUNT.get(serial, 0) + 1
    _DUMP_FAIL_COUNT[serial] = n
    if n >= _DUMP_BREAKER_MAX_FAILS:
        _DUMP_SKIP_UNTIL[serial] = time.time() + _DUMP_BREAKER_COOLDOWN_S
        _DUMP_FAIL_COUNT[serial] = 0
        logger.warning(
            "dump circuit breaker: %s uiautomator wedged — skipping dumps %.0fs",
            serial,
            _DUMP_BREAKER_COOLDOWN_S,
        )


DUMP_TIMEOUT_S = 8.0
DUMP_RETRY_TIMEOUT_S = 10.0
DUMP_CAT_TIMEOUT_S = 2.5

# Per-serial unwedge kicks — never hammer the same phone more than once per 90s.
_UNWEDGE_KICKED: dict[str, float] = {}
_UNWEDGE_COOLDOWN_S = 90.0


def _kick_unwedge(serial: str) -> None:
    """Kill the wedged guest uiautomator + reset that serial's transport (async).

    The dump breaker previously only *skipped* dumps for 45s — the phone stayed
    wedged and taps/swipes kept queuing behind the hung uiautomator process.
    This actively clears the guest-side process and reconnects the adb transport
    for the affected serial only (never adb kill-server — that drops all phones).
    Runs in a daemon thread so the sequence pipeline never blocks on it.
    """
    now = time.time()
    if now - _UNWEDGE_KICKED.get(serial, 0.0) < _UNWEDGE_COOLDOWN_S:
        return
    _UNWEDGE_KICKED[serial] = now

    def _work() -> None:
        adb = AdbWrapper()
        try:
            adb.shell("pkill -f uiautomator", serial=serial, timeout=6)
            adb.shell(
                "rm -f /sdcard/cpharm_ui.xml /sdcard/cpharm_overlay.xml /sdcard/cpharm_ad_pick.xml",
                serial=serial,
                timeout=6,
            )
            adb.disconnect(serial, timeout=8)
            adb.connect(serial, timeout=15)
            logger.warning(
                "unwedge %s: uiautomator killed + transport reset",
                serial,
            )
        except Exception as exc:  # noqa: BLE001 — never let recovery crash the farm
            logger.warning("unwedge failed on %s: %s", serial, exc)

    threading.Thread(target=_work, daemon=True, name=f"unwedge-{serial}").start()


def _dump_ui(adb: AdbWrapper, serial: str, *, timeout: float = DUMP_TIMEOUT_S) -> str:
    """UI dump with a real timeout and one retry.

    The old 1.2s default was shorter than a healthy ARM-VM dump — uiautomator
    on Snapdragon guests routinely needs 2-6s — so almost every dump timed out,
    flows went blind, and taps fell back to fixed coordinates. Now: 8s first
    attempt, one 10s retry on a pure timeout. The circuit breaker still trips
    on a truly wedged guest (worst case ~18s before it trips, well under the
    janitor's 25s wedged threshold) and _kick_unwedge clears the guest process.
    The 2-concurrent dump semaphore still bounds stack-up across 8+ phones.
    """
    if dump_breaker_skip(serial):
        return ""
    with _UI_DUMP_SEM:
        dump = adb.shell(
            "uiautomator dump /sdcard/cpharm_ui.xml",
            serial=serial,
            timeout=timeout,
        )
        if not dump.ok and dump.returncode == 124:
            logger.warning(
                "uiautomator dump timed out on %s (%.1fs) — one retry at %.0fs",
                serial,
                timeout,
                DUMP_RETRY_TIMEOUT_S,
            )
            dump_breaker_note(serial, False)
            if dump_breaker_skip(serial):
                _kick_unwedge(serial)
                return ""
            dump = adb.shell(
                "uiautomator dump /sdcard/cpharm_ui.xml",
                serial=serial,
                timeout=DUMP_RETRY_TIMEOUT_S,
            )
            if not dump.ok and dump.returncode == 124:
                logger.warning("uiautomator dump retry timed out on %s", serial)
                dump_breaker_note(serial, False)
                if dump_breaker_skip(serial):
                    _kick_unwedge(serial)
                return ""
        cat = adb.shell("cat /sdcard/cpharm_ui.xml", serial=serial, timeout=DUMP_CAT_TIMEOUT_S)
        body = cat.stdout or ""
        dump_breaker_note(serial, len(body) >= 500)
        return body


def _fre_visible(xml: str) -> bool:
    if not xml:
        return False
    low = xml.lower()
    return (
        "fre_pager" in xml
        or "signin_fre_dismiss_button" in xml
        or "signin_fre_continue_button" in xml
        or "Stay signed out" in xml
        or "stay signed out" in low
        or "Make Chrome your own" in xml
        or "use without an account" in low
        or "signin_fre" in low
    )


def _dabflow_in_dump(xml: str) -> bool:
    """True when DabFlow / age-gate WebView content is present in the dump."""
    if not xml:
        return False
    low = xml.lower()
    return (
        "getdabflow" in low
        or "dabflow" in low
        or "are you 21" in low
        or "yes, i am" in low
        or "start perfect dab" in low
        or "start-dab-btn" in low
    )


def _age_gate_visible(xml: str) -> bool:
    """True when the DabFlow HTML age gate (Yes 21+ / No) is on screen.

    Critical: FRE Stay-signed-out probe coords sit on the age-gate No button.
    Never blind-tap FRE while this is True.
    """
    if not xml:
        return False
    low = xml.lower()
    if "age-yes-btn" in low or "age-no-btn" in low:
        return True
    if "are you 21" in low:
        return True
    if "yes, i am 21" in low or "yes, i am" in low:
        return True
    return False


def _past_fre(xml: str) -> bool:
    """True when Chromium chrome shows we are past FRE (never DabFlow alone).

    DabFlow WebView can appear in dumps while Stay signed out still overlays the
    screen (or FRE nodes are missing from uiautomator). Treating DabFlow as
    past-FRE caused dismiss to skip — age gate then "OK" under a still-visible FRE.
    """
    if not xml or _fre_visible(xml):
        return False
    # Age gate up with no FRE markers = past splash; open_url will tap Yes next.
    if _age_gate_visible(xml):
        return True
    # Never skip dismiss just because DabFlow/age-gate text is in the dump.
    if _dabflow_in_dump(xml):
        return False
    low = xml.lower()
    if any(tok in low for tok in ("url_bar", "omnibox", "location_bar", "search_box")):
        return True
    return False


def _tap_fre_dismiss_from_xml(adb: AdbWrapper, serial: str, xml: str) -> bool:
    """Tap Stay signed out from dump nodes only — never Help / Manage / Add account."""
    for node in xml.split("<node "):
        chunk = node.lower()
        is_dismiss = "signin_fre_dismiss_button" in chunk or "stay signed out" in chunk
        is_alt = "use without an account" in chunk
        if not is_dismiss and not is_alt:
            continue
        if "fre_footer" in chunk or "signin_fre_footer" in chunk:
            continue
        if "signin_fre_continue_button" in chunk or "add account" in chunk:
            continue
        if any(bad in chunk for bad in _FRE_BLOCKLIST) and "stay signed out" not in chunk:
            continue
        m = _BOUNDS_RE.search(node)
        if not m:
            continue
        x1, y1, x2, y2 = (int(m.group(i)) for i in range(1, 5))
        cy = (y1 + y2) // 2
        # Stay signed out is mid/lower portrait; allow slight layout drift.
        if cy < 850 or cy > 1400:
            continue
        if _tap_center(adb, serial, x1, y1, x2, y2):
            time.sleep(0.75)
            logger.info("Dismissed Chromium FRE via dismiss button on %s at y=%d", serial, cy)
            return True
    return False


def _probe_stay_signed_out(adb: AdbWrapper, serial: str) -> None:
    """Blind Stay-signed-out / Use-without-account tap at proven coords."""
    x, y = CHROMIUM_SKIP_TAP
    adb.tap(x, y, serial=serial)
    time.sleep(0.55)
    logger.info("Probed Chromium Stay-signed-out tap (%d,%d) on %s", x, y, serial)


def dismiss_chromium_fre(
    adb: AdbWrapper,
    serial: str,
    *,
    wait_paint_s: float | None = None,
) -> bool:
    """Dismiss FRE when visible; wait for splash to paint, then retry+verify.

    After pm clear, FRE always appears but paints slowly. Dumping immediately
    falsely reports "not visible" and skips dismiss — leaving Stay signed out up
    so age gate / Start Perfect Dab never work.

    Never treat DabFlow WebView alone as past-FRE (overlay / missing FRE nodes).
    Only early-exit when Chromium chrome (omnibox) is up with no FRE markers.
    """
    paint_budget = fre_paint_wait_s() if wait_paint_s is None else max(0.0, wait_paint_s)
    deadline = time.monotonic() + paint_budget
    xml = ""
    while True:
        xml = _dump_ui(adb, serial)
        if _fre_visible(xml):
            break
        # Omnibox-only past-FRE (no DabFlow) — safe to skip full wait.
        if _past_fre(xml):
            logger.info("Chromium FRE not present on %s (already past splash)", serial)
            return True
        # Age gate painted = past FRE. NEVER probe Stay-signed-out here — that
        # tap lands on the age-gate No / under-21 button (was (450,1127)).
        if _age_gate_visible(xml):
            logger.info(
                "DabFlow age gate visible on %s — skipping FRE probe (Yes tap handles gate)",
                serial,
            )
            return True
        # DabFlow in dump without FRE markers: do NOT skip — splash may still be up.
        if _dabflow_in_dump(xml):
            logger.info(
                "DabFlow visible without FRE markers on %s — probing Stay-signed-out (no skip)",
                serial,
            )
            _probe_stay_signed_out(adb, serial)
            xml = _dump_ui(adb, serial)
            if _fre_visible(xml):
                break
            if _age_gate_visible(xml):
                return True
            # Probe done; continue dismiss/verify loop below.
            break
        if time.monotonic() >= deadline:
            # Never saw FRE or past-FRE markers — may still be painting; blind Skip tap.
            # Bail if age gate appeared during the wait — do not tap No.
            if _age_gate_visible(xml):
                logger.info(
                    "Age gate appeared during FRE wait on %s — skipping Stay-signed-out probe",
                    serial,
                )
                return True
            logger.warning(
                "Chromium FRE not confirmed after %.1fs on %s — probing Stay-signed-out tap",
                paint_budget,
                serial,
            )
            _probe_stay_signed_out(adb, serial)
            xml = _dump_ui(adb, serial)
            if _age_gate_visible(xml):
                return True
            if not _fre_visible(xml):
                return True
            break
        time.sleep(_FRE_PAINT_POLL_S)

    for attempt in range(3):
        xml = xml if attempt == 0 else _dump_ui(adb, serial)
        if not _fre_visible(xml):
            return True
        tapped = _tap_fre_dismiss_from_xml(adb, serial, xml)
        if not tapped:
            x, y = CHROMIUM_SKIP_TAP
            tapped = adb.tap(x, y, serial=serial).ok
            if tapped:
                time.sleep(0.55)
                logger.info(
                    "Dismissed Chromium FRE via Stay-signed-out tap (%d,%d) on %s",
                    x,
                    y,
                    serial,
                )
        if not tapped:
            return False
        time.sleep(0.45)
        xml = _dump_ui(adb, serial)
        if not _fre_visible(xml):
            return True
        logger.warning(
            "Chromium FRE still visible after dismiss attempt %d on %s — retrying",
            attempt + 1,
            serial,
        )
    return not _fre_visible(xml or _dump_ui(adb, serial))


def defocus_chromium_omnibox(adb: AdbWrapper, serial: str, *, dump_xml: str | None = None) -> bool:
    """If URL/omnibox is focused or Google NTP/search sheet is showing, clear it safely."""
    xml = dump_xml if dump_xml is not None else _dump_ui(adb, serial)
    low = xml.lower()
    on_dabflow = "getdabflow" in low or "dabflow" in low
    on_google = ("google.com" in low or 'text="google"' in low) and not on_dabflow
    search_sheet = "tap to see search results" in low or "search results" in low
    omnibox_focused = False
    for node in xml.split("<node "):
        chunk = node.lower()
        if not any(oid in chunk for oid in _OMNIBOX_IDS):
            continue
        if 'focused="true"' in chunk:
            omnibox_focused = True
            break
    if not omnibox_focused and not on_google and not search_sheet:
        return False
    if search_sheet:
        # Bottom Google suggestion sheet — BACK dismisses without leaving DabFlow.
        adb.keyevent(4, serial=serial)
        time.sleep(0.25)
        logger.info("Dismissed Google search suggestion sheet on %s", serial)
        return True
    ok = adb.tap(450, 640, serial=serial).ok
    if ok:
        time.sleep(0.2)
        logger.info(
            "Defocused Chromium omnibox on %s (google=%s focused=%s)",
            serial,
            on_google,
            omnibox_focused,
        )
    return ok


def prepare_chromium(
    adb: AdbWrapper,
    serial: str,
    *,
    profile: BrowserSessionProfile | None = None,
    force: bool = False,
) -> bool:
    """Write retail UA flags; do not open about:blank / FRE here (open_url dismisses once)."""
    if profile is not None:
        from automation.browser_identity import apply_browser_session

        apply_browser_session(adb, serial, profile)
        force = True

    if not force and serial in _prepared_serials:
        return True
    browser = select_chromium_browser(adb, serial)
    if not browser:
        return False

    if profile is None:
        from automation.browser_identity import apply_browser_session, profile_from_device

        profile = profile_from_device(adb, serial)
        apply_browser_session(adb, serial, profile)

    adb.shell(f"am force-stop {browser.package}", serial=serial)
    time.sleep(0.4)
    _prepared_serials.add(serial)
    return True


# MuMu often mounts /data/local/tmp RO — keep URL on /data/local when possible.
_VIEW_URL_DEVICE_PATH = "/data/local/cpharm_view_url.txt"
_VIEW_URL_DEVICE_PATH_TMP = "/data/local/tmp/cpharm_view_url.txt"
# Windows adb.exe CreateProcess limit — long Mantis URLs in `am start -d "..."` → WinError 206.
_MAX_DIRECT_VIEW_URL_LEN = 900


def _push_view_url(adb: AdbWrapper, serial: str, url: str) -> bool:
    """Push browse URL to device; host cmdline stays short (WinError 206 safe)."""
    local_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".txt", delete=False
        ) as tmp:
            tmp.write(url)
            local_path = tmp.name
        for remote in (_VIEW_URL_DEVICE_PATH, _VIEW_URL_DEVICE_PATH_TMP):
            pushed = adb.push(local_path, remote, serial=serial)
            if pushed.ok:
                adb.shell(f"chmod 644 {remote} 2>/dev/null; true", serial=serial)
                return True
            low = (pushed.stderr or "").lower()
            if "read-only" in low or "read only" in low:
                logger.warning("view url push RO on %s path=%s", serial, remote)
                continue
            logger.warning(
                "view url push failed on %s path=%s: %s", serial, remote, pushed.stderr
            )
        return False
    finally:
        if local_path:
            try:
                os.unlink(local_path)
            except OSError:
                pass


def _view_url_data_ref(adb: AdbWrapper, serial: str, url: str) -> str:
    """Return `-d` argument: direct quoted URL or device-side $(cat ...) expansion."""
    if len(url) <= _MAX_DIRECT_VIEW_URL_LEN and '"' not in url and "$(" not in url:
        return f'"{url}"'
    if _push_view_url(adb, serial, url):
        return f'"$(cat {_VIEW_URL_DEVICE_PATH})"'
    logger.warning(
        "view url file push failed on %s — direct am start may hit WinError 206",
        serial,
    )
    escaped = url.replace('"', '\\"')
    return f'"{escaped}"'


def _am_start_view(
    adb: AdbWrapper,
    serial: str,
    url: str,
    target: BrowserInfo,
    extra_flags: str = "",
) -> bool:
    """Issue VIEW intent with a short host adb cmd (URL via device file when long)."""
    data_ref = _view_url_data_ref(adb, serial, url)
    if target.activity:
        cmd = f"am start -a android.intent.action.VIEW -d {data_ref} -n {target.activity}"
    else:
        cmd = f"am start -a android.intent.action.VIEW -d {data_ref}"
    if extra_flags:
        cmd = f"{cmd} {extra_flags}"
    result = adb.shell(cmd, serial=serial)
    if result.ok:
        return True
    if not target.package:
        return False
    fallback = adb.shell(
        f"am start -a android.intent.action.VIEW -d {data_ref} -p {target.package}",
        serial=serial,
    )
    return fallback.ok


def open_url(
    adb: AdbWrapper,
    serial: str,
    url: str,
    browser: BrowserInfo | None = None,
    extra_flags: str = "",
    profile: BrowserSessionProfile | None = None,
) -> bool:
    """Open URL in Chromium; dismiss FRE once after launch if splash is present."""
    target = browser or select_browser(adb, serial)
    if not target:
        return False
    chromium_family = target.kind in _CHROMIUM_FAMILY
    if chromium_family:
        # Skip force-stop if browse_url already prepared this serial.
        already = serial in _prepared_serials
        prepare_chromium(adb, serial, profile=profile, force=not already and bool(profile))
    elif target.kind is BrowserKind.FIREFOX:
        # Fenix swallows VIEW while Terms/splash is up — seed every open.
        seed_firefox_onboarding_complete(adb, serial, target.package)
    elif target.kind is BrowserKind.DUCKDUCKGO:
        # Launcher/VIEW hit OnboardingActivity until userStage is ESTABLISHED.
        seed_duckduckgo_onboarding_complete(adb, serial, target.package)
    if target.kind is BrowserKind.OPERA:
        # WelcomeActivity ignores Chromium FRE seed — OEM prefs must be present
        # before VIEW or the intent is redirected into onboarding.
        seed_opera_onboarding_complete(adb, serial, target.package)
    # Recorded coords are Chromium-authored; seed this browser's page rect up front.
    set_viewport_for_package(serial, target.package)

    def _launch_view() -> bool:
        return _am_start_view(adb, serial, url, target, extra_flags)

    if not _launch_view():
        return False
    dabflow = "getdabflow" in (url or "").lower()
    if target.kind is BrowserKind.FIREFOX:
        # Safety net: splash / Terms / default / notification sheets can still
        # paint after a seed miss — dismiss, then re-issue VIEW (dabflow sticky).
        # Fenix's branded splash has NO text/advance markers, so a bare dump
        # looks "ready" and every sequence tap lands on the logo -> err=tap.
        # Poll until the toolbar/page markers appear or Firefox leaves focus.
        time.sleep(firefox_onboarding_wait_s())
        _ff_ready = False
        for _ff_round in range(4):
            xml_ff = _dump_ui(adb, serial)
            if firefox_page_ready(xml_ff):
                _ff_ready = True
                break
            if firefox_still_booting(xml_ff):
                # Splash or blank Fenix window up — keep re-issuing VIEW until
                # the toolbar paints (slow on 1 GB VMs with 10 phones).
                dismiss_firefox_onboarding(adb, serial, dump_ui=_dump_ui, max_rounds=6)
                seed_firefox_onboarding_complete(adb, serial, target.package)
                _launch_view()
                time.sleep(firefox_onboarding_wait_s())
                continue
            if not firefox_onboarding_visible(xml_ff):
                break
            dismiss_firefox_onboarding(adb, serial, dump_ui=_dump_ui, max_rounds=10)
            seed_firefox_onboarding_complete(adb, serial, target.package)
            _launch_view()
            time.sleep(1.0)
        if not _ff_ready and not firefox_page_ready(_dump_ui(adb, serial)):
            logger.warning(
                "Firefox still on splash/blank after %s attempts on %s — falling back",
                4,
                serial,
            )
            return False
    if target.kind is BrowserKind.DUCKDUCKGO:
        # Splash / widget / AI-picker can reappear after VIEW — hammer dismiss,
        # re-seed, and re-issue the intent until omnibar/page is reachable.
        for _round in range(3):
            time.sleep(duckduckgo_onboarding_wait_s())
            xml = _dump_ui(adb, serial)
            if not duckduckgo_onboarding_visible(xml):
                break
            dismiss_duckduckgo_onboarding(adb, serial, dump_ui=_dump_ui, max_rounds=16)
            seed_duckduckgo_onboarding_complete(adb, serial, target.package)
            _launch_view()
            time.sleep(1.0)
    if chromium_family:
        # FRE prefs were already seeded before this function — skip the
        # expensive dismiss_chromium_fre poll (2s + dumps).  The age gate
        # tap in open_url handles any residual overlay.
        time.sleep(0.3)
        # One quick overlay check instead of full dismiss_chromium_fre.
        dismiss_blocking_browser_overlays(
            adb, serial, target.package, dump_ui=_dump_ui
        )
        defocus_chromium_omnibox(adb, serial)
        ssl_xml = _dump_ui(adb, serial)
        if ssl_interstitial_visible(ssl_xml):
            cleared = dismiss_ssl_interstitial(
                adb, serial, dump_ui=_dump_ui, package=target.package
            )
            # HSTS + MITM has no Proceed — reload once on direct (:0).
            if not cleared and (ssl_hsts_blocked(ssl_xml) or ssl_interstitial_visible(_dump_ui(adb, serial))):
                logger.warning(
                    "SSL HSTS/MITM dead-end on %s (%s) — reopening URL direct",
                    serial,
                    target.package,
                )
                time.sleep(0.4)
                _launch_view()
                time.sleep(1.2)
                dismiss_chromium_fre(adb, serial)
                if ssl_interstitial_visible(_dump_ui(adb, serial)):
                    dismiss_ssl_interstitial(
                        adb, serial, dump_ui=_dump_ui, package=target.package
                    )
        if target.kind is BrowserKind.BRAVE:
            time.sleep(0.4)
            if brave_overlay_visible(_dump_ui(adb, serial)):
                dismiss_brave_overlays(adb, serial, dump_ui=_dump_ui)
        if target.kind is BrowserKind.OPERA:
            # WelcomeActivity is not Chromium FRE — seed + tap-through if present.
            time.sleep(0.5)
            if opera_welcome_visible(_dump_ui(adb, serial)):
                dismiss_opera_welcome(adb, serial, dump_ui=_dump_ui)
                seed_opera_onboarding_complete(adb, serial, target.package)
                _launch_view()
                time.sleep(1.0)
                if opera_welcome_visible(_dump_ui(adb, serial)):
                    dismiss_opera_welcome(adb, serial, dump_ui=_dump_ui)
        if dabflow:
            # Re-check FRE after page load — Stay signed out can appear late over DabFlow.
            time.sleep(0.35)
            if _fre_visible(_dump_ui(adb, serial)):
                dismiss_chromium_fre(adb, serial, wait_paint_s=1.0)
            if target.kind is BrowserKind.OPERA and opera_welcome_visible(_dump_ui(adb, serial)):
                dismiss_opera_welcome(adb, serial, dump_ui=_dump_ui)
            if ssl_interstitial_visible(_dump_ui(adb, serial)):
                cleared = dismiss_ssl_interstitial(
                    adb, serial, dump_ui=_dump_ui, package=target.package
                )
                if not cleared:
                    logger.warning(
                        "SSL still up after dismiss on %s — reopening URL direct",
                        serial,
                    )
                    time.sleep(0.4)
                    _launch_view()
                    time.sleep(1.2)
                    if ssl_interstitial_visible(_dump_ui(adb, serial)):
                        dismiss_ssl_interstitial(
                            adb, serial, dump_ui=_dump_ui, package=target.package
                        )
            if target.kind is BrowserKind.BRAVE and brave_overlay_visible(_dump_ui(adb, serial)):
                dismiss_brave_overlays(adb, serial, dump_ui=_dump_ui)
    if dabflow:
        # Wait for age gate to paint, then tap Yes (works across browsers).
        time.sleep(dabflow_age_gate_load_wait_s())
        # Late sheets (DDG AI picker / Brave News) can pop after VIEW — clear first.
        dismiss_blocking_browser_overlays(
            adb, serial, target.package, dump_ui=_dump_ui
        )
        gate_xml = _dump_ui(adb, serial)
        # Calibrate from the page's own rect so later sequence taps are remapped.
        calibrate(serial, xml=gate_xml, package=target.package)
        resolved = element_center(gate_xml, _DABFLOW_AGE_GATE_YES_ID)
        if resolved is not None:
            ax, ay = resolved
            logger.info("Age gate YES via age-yes-btn bounds (%d,%d) on %s", ax, ay, serial)
        else:
            # Prefer left-center of Yes — never mid-screen (hits No).
            ax, ay = remap_tap(serial, *_DABFLOW_AGE_GATE_YES)
            logger.info("Age gate YES via fallback tap (%d,%d) on %s", ax, ay, serial)
        # Guard: never tap the right-half No button if dump exposes it.
        no_pt = element_center(gate_xml, _DABFLOW_AGE_GATE_NO_ID)
        if no_pt is not None and abs(ax - no_pt[0]) < 40 and abs(ay - no_pt[1]) < 40:
            logger.warning(
                "Age gate tap (%d,%d) too close to No (%d,%d) — forcing Yes fallback",
                ax,
                ay,
                no_pt[0],
                no_pt[1],
            )
            ax, ay = remap_tap(serial, *_DABFLOW_AGE_GATE_YES)
        adb.tap(ax, ay, serial=serial)
        time.sleep(_DABFLOW_AGE_GATE_POST_YES_SETTLE_S)
        # AI picker / Brave News often appear only after the first page paint.
        dismiss_blocking_browser_overlays(
            adb, serial, target.package, dump_ui=_dump_ui
        )
        if chromium_family:
            post = _dump_ui(adb, serial)
            if _fre_visible(post):
                dismiss_chromium_fre(adb, serial, wait_paint_s=1.0)
                time.sleep(0.3)
                adb.tap(ax, ay, serial=serial)
                time.sleep(_DABFLOW_AGE_GATE_POST_YES_SETTLE_S)
                post = _dump_ui(adb, serial)
            if target.kind is BrowserKind.OPERA and opera_welcome_visible(post):
                dismiss_opera_welcome(adb, serial, dump_ui=_dump_ui)
                time.sleep(0.3)
                adb.tap(ax, ay, serial=serial)
                time.sleep(_DABFLOW_AGE_GATE_POST_YES_SETTLE_S)
        return True
    return True

def is_chromium_available(adb: AdbWrapper, serial: str) -> bool:
    packages = set(adb.pm_list_packages(serial=serial))
    return BROWSER_CHROMIUM in packages or CHROME_STOCK in packages


def is_mumu_browser_available(adb: AdbWrapper, serial: str) -> bool:
    return BROWSER_MUMU in adb.pm_list_packages(serial=serial)


def discover_browsers(adb: AdbWrapper, serial: str) -> list[BrowserInfo]:
    packages = set(adb.pm_list_packages(serial=serial))
    found: list[BrowserInfo] = []
    for pkg in (
        BROWSER_FARMBROWSER,
        BROWSER_FARMBROWSER_RELEASE,
        BROWSER_CHROMIUM,
        CHROME_STOCK,
        BROWSER_BRAVE,
        BROWSER_FIREFOX,
        BROWSER_DUCKDUCKGO,
        BROWSER_OPERA,
        BROWSER_MUMU,
        SYSTEM_BROWSER,
    ):
        if pkg in packages:
            info = browser_info_for_package(pkg)
            if info is not None:
                found.append(info)
    return found


def launch_app(adb: AdbWrapper, serial: str, package: str) -> bool:
    from automation.farm_launch_guard import is_denied_launch_package, is_farm_browser_package

    pkg = (package or "").strip()
    if not pkg:
        return False
    if is_denied_launch_package(pkg) or (
        not is_farm_browser_package(pkg) and pkg not in ("com.android.browser",)
    ):
        # Farm sequences only launch Chromium/Firefox/Brave/DDG/Opera.
        logger.warning("launch_app refused non-browser/denied package=%s serial=%s", pkg, serial)
        return False
    result = adb.shell(
        f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1",
        serial=serial,
    )
    if result.ok and "No activities" not in result.stdout and "Error" not in result.stdout:
        return True
    resolve = adb.shell(f"cmd package resolve-activity --brief {pkg}", serial=serial)
    line = (resolve.stdout or "").strip().splitlines()
    activity = line[-1].strip() if line else ""
    if "/" in activity:
        started = adb.shell(f"am start -n {activity}", serial=serial)
        return started.ok
    return False


# ==== merged from cpharm automation/browser_adb.py (farmbrowser/package helpers) ====

def _pkg_is_chrome_family(pkg: str) -> bool:
    p = (pkg or "").strip().lower()
    return any(p == known or p.startswith(known + ".") for known in _CHROME_PKG_PREFIXES)


# Order after ``default_view_package``: prefer FarmBrowser first (has built-in
# proxy, identity rotation, JS interface), then Tor-aware / proxy-respecting browsers,
# then OEM / Samsung Internet / stock browser, with Chrome strictly last.
# Chromium honors the system proxy inconsistently and triggers ERR_TIMED_OUT.
_BROWSER_CLEAR_FALLBACKS = (
    # ★ FarmBrowser — CPharm stealth browser (top priority)
    "com.farmbrowser.stealth.debug",
    "com.farmbrowser.stealth",
    # Tor-aware / proxy-faithful Android browsers
    "org.torproject.torbrowser",
    "org.torproject.torbrowser_alpha",
    "info.guardianproject.orfox",
    "us.spotco.fennec_dos",          # Mull
    "org.mozilla.fennec_fdroid",     # Fennec
    "io.github.forkmaintainers.iceraven",
    "org.mozilla.fennec_aurora",
    "org.bromite.bromite",
    # OEM / stock browsers (honor http_proxy via system WebView)
    "com.sec.android.app.sbrowser",
    "com.samsung.android.app.sbrowser",
    "com.mumudroid.browser",
    "mark.via.gp",
    "com.mmbox.browser",
    "org.mozilla.firefox",
    "com.microsoft.emmx",
    "com.opera.browser",
    # Chromium sideload (CDP + Mantis patch) before stock AOSP browser.
    "org.chromium.chrome",
    "com.android.chrome",
    "com.chrome.beta",
    # Stock AOSP Browser absolute last — no CDP, empty Mantis slots on MuMu.
    "com.android.browser",
)



def looks_like_package(value: str) -> bool:
    return bool(value and _PKG_STEP_RE.match(value))



def package_installed(serial: str, pkg: str) -> bool:
    if not pkg or not _PKG_STEP_RE.match(pkg):
        return False
    exe = adb_executable()
    try:
        r = subprocess.run(
            [exe, "-s", serial, "shell", "pm", "path", pkg],
            capture_output=True,
            text=True,
            errors="replace",  # device output can contain raw bytes — never crash sequence threads on decode
            timeout=12,
            creationflags=_SUBPROC_FLAGS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if r.returncode not in (0, None):
        return False
    out = (r.stdout or "").strip()
    return bool(out) and "package:" in out.lower()



def default_view_package(serial: str) -> Optional[str]:
    """Best-effort package for current default VIEW handler for https URLs."""
    exe = adb_executable()
    try:
        r = subprocess.run(
            [
                exe,
                "-s",
                serial,
                "shell",
                "cmd",
                "package",
                "resolve-activity",
                "--brief",
                "-a",
                "android.intent.action.VIEW",
                "-d",
                "https://example.com",
            ],
            capture_output=True,
            text=True,
            errors="replace",  # device output can contain raw bytes — never crash sequence threads on decode
            timeout=12,
            creationflags=_SUBPROC_FLAGS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode not in (0, None):
        return None
    for line in (r.stdout or "").splitlines():
        txt = line.strip()
        if not txt or "/" not in txt:
            continue
        pkg = txt.split("/", 1)[0].strip()
        if looks_like_package(pkg):
            return pkg
    return None



def _installed_browser_candidates(serial: str) -> list[str]:
    exe = adb_executable()
    try:
        r = subprocess.run(
            [exe, "-s", serial, "shell", "pm", "list", "packages"],
            capture_output=True,
            text=True,
            errors="replace",  # device output can contain raw bytes — never crash sequence threads on decode
            timeout=12,
            creationflags=_SUBPROC_FLAGS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if r.returncode not in (0, None):
        return []
    out: list[str] = []
    for line in (r.stdout or "").splitlines():
        pkg = line.strip().replace("package:", "", 1).strip()
        if not looks_like_package(pkg):
            continue
        low = pkg.lower()
        if any(
            k in low
            for k in (
                "sbrowser",
                "chrome",
                "browser",
                "firefox",
                "edge",
                "opera",
                "duckduckgo",
                "mumu",
                "nemu",
                "tor",
                "fennec",
                "mull",
                "bromite",
                "iceraven",
                "orfox",
            )
        ):
            out.append(pkg)
    return out


_AOSP_STOCK_BROWSER = "com.android.browser"



def farmbrowser_installed(serial: str) -> bool:
    """True when FarmBrowser is installed on *serial*."""
    return (
        package_installed(serial, _FARMBROWSER_PKG)
        or package_installed(serial, _FARMBROWSER_PKG_RELEASE)
    )



def farmbrowser_pkg(serial: str) -> str | None:
    """Return the installed FarmBrowser package name, or ``None``."""
    if package_installed(serial, _FARMBROWSER_PKG):
        return _FARMBROWSER_PKG
    if package_installed(serial, _FARMBROWSER_PKG_RELEASE):
        return _FARMBROWSER_PKG_RELEASE
    return None



def farmbrowser_control_broadcast(
    serial: str, action: str, extras: dict | None = None
) -> dict:
    """Send a control broadcast to FarmBrowser via ADB.

    ``extras`` is a dict of string/int/bool extras added to the intent.
    Returns ``{ok, result, rc}``.
    """
    pkg = farmbrowser_pkg(serial)
    if not pkg:
        return {"ok": False, "error": "FarmBrowser not installed"}
    cmd = [
        "shell", "am", "broadcast",
        "-a", "com.farmbrowser.stealth.CONTROL",
        "-n", f"{pkg}/com.farmbrowser.stealth.browser.FarmBrowserReceiver",
        "--es", "action", action,
    ]
    if extras:
        for k, v in extras.items():
            if isinstance(v, bool):
                cmd.extend(["--ez", k, str(v).lower()])
            elif isinstance(v, int):
                cmd.extend(["--ei", k, str(v)])
            else:
                cmd.extend(["--es", k, str(v)])
    cmd.append("--receiver-include-background")
    exe = adb_executable()
    try:
        r = subprocess.run(
            [exe, "-s", serial] + cmd,
            capture_output=True, text=True, errors="replace",
            timeout=15,
            creationflags=_SUBPROC_FLAGS,
        )
        result_line = ""
        for line in (r.stdout or "").splitlines():
            if "result" in line.lower() or "broadcastresult" in line.lower():
                result_line = line.strip()
                break
        return {
            "ok": r.returncode == 0,
            "result": result_line or (r.stdout or "").strip()[:500],
            "rc": r.returncode,
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}


def farmbrowser_set_identity(serial: str, index: int) -> dict:
    """Force FarmBrowser to use a specific browser identity by index.

    This guarantees each phone shows a different browser (Chrome, Firefox, etc.).
    Use ``farmbrowser_identity_count()`` to know the range.
    """
    return farmbrowser_control_broadcast(serial, "set_identity", {"index": index})



def farmbrowser_identity_count(serial: str) -> int:
    """Return the number of browser identities available in FarmBrowser."""
    # 12 identities defined in BrowserIdentity.kt as of current build
    return 12


# getdabflow.app on-site Mantis ads need Chromium CDP (--remote-debugging-port).
_DABFLOW_AD_BROWSER_PRIORITY = (
    # ★ FarmBrowser first — it has proxy support + identity rotation
    "com.farmbrowser.stealth.debug",
    "com.farmbrowser.stealth",
    # Chromium CDP fallbacks
    "org.chromium.chrome",
    "com.android.chrome",
    "com.chrome.beta",
    "com.chrome.dev",
    "com.chrome.canary",
    "com.google.android.apps.chrome",
)



def packages_for_dabflow_view_url_attempts(serial: str, preferred: str = "") -> list[str]:
    """Like :func:`packages_for_view_url_attempts` but Chromium-first for Mantis CDP ads."""
    base = packages_for_view_url_attempts(serial, preferred)
    ordered: list[str] = []
    for pkg in _DABFLOW_AD_BROWSER_PRIORITY:
        if pkg in base and pkg not in ordered:
            ordered.append(pkg)
    for pkg in base:
        if pkg not in ordered:
            ordered.append(pkg)
    return ordered



def packages_for_view_url_attempts(serial: str, preferred: str = "") -> list[str]:
    """Installed browser packages in the same priority order as :func:`browser_pkg_for_clear`.

    Ordering: explicit ``preferred`` from the step (if any), then
    :func:`default_view_package` when it is NOT a Chrome-family package and NOT the
    stock AOSP browser (MuMu images default to ``com.android.browser`` which lacks CDP
    and breaks on-site Mantis ads — prefer MuMu/Chromium from fallbacks first), then
    :data:`_BROWSER_CLEAR_FALLBACKS`, then other installed candidates.
    """
    cands: list[str] = []
    if looks_like_package(preferred):
        cands.append(preferred)
    default_pkg = default_view_package(serial)
    if (
        default_pkg
        and default_pkg not in cands
        and not _pkg_is_chrome_family(default_pkg)
        and default_pkg != _AOSP_STOCK_BROWSER
    ):
        cands.append(default_pkg)
    cands.extend(p for p in _BROWSER_CLEAR_FALLBACKS if p not in cands)
    for pkg in _installed_browser_candidates(serial):
        if pkg not in cands:
            cands.append(pkg)
    if default_pkg and default_pkg not in cands:
        cands.append(default_pkg)
    return [pkg for pkg in cands if package_installed(serial, pkg)]



def browser_pkg_for_clear(serial: str, preferred: str) -> Optional[str]:
    """Pick an installed browser package for ``pm clear`` / ``force-stop``."""
    pkgs = packages_for_view_url_attempts(serial, preferred)
    return pkgs[0] if pkgs else None




_WEBVIEW_TOP_CACHE: dict[str, tuple[float, int]] = {}
_WEBVIEW_TOP_CACHE_TTL = 45.0
_WEBVIEW_UI_DUMP = "/sdcard/cpharm_webview_ui.xml"
_WEBVIEW_BOUNDS_RE = re.compile(
    r'class="android\.webkit\.WebView"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
)



def parse_webview_top_from_ui_xml(xml: str) -> int | None:
    """Return WebView content top edge (screen Y) from a uiautomator dump."""
    if not (xml or "").strip():
        return None
    best: int | None = None
    for m in _WEBVIEW_BOUNDS_RE.finditer(xml):
        top = int(m.group(2))
        if best is None or top < best:
            best = top
    return best



def invalidate_webview_inset_cache(serial: str | None = None) -> None:
    if serial is None:
        _WEBVIEW_TOP_CACHE.clear()
    else:
        _WEBVIEW_TOP_CACHE.pop(serial, None)



def webview_content_top_inset(serial: str, *, force_refresh: bool = False) -> int:
    """Map page-space sequence Y to screen Y: add WebView top inset (browser chrome)."""
    import os
    import time

    raw = (os.environ.get("CPHARM_WEBVIEW_TOP_INSET") or "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    if (os.environ.get("CPHARM_WEBVIEW_NO_INSET") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return 0

    now = time.time()
    if not force_refresh:
        ent = _WEBVIEW_TOP_CACHE.get(serial)
        if ent is not None and now - ent[0] < _WEBVIEW_TOP_CACHE_TTL:
            return ent[1]

    inset: int | None = None
    exe = adb_executable()
    try:
        subprocess.run(
            [exe, "-s", serial, "shell", "uiautomator", "dump", _WEBVIEW_UI_DUMP],
            capture_output=True,
            text=True,
            errors="replace",  # device output can contain raw bytes — never crash sequence threads on decode
            timeout=25,
            creationflags=_SUBPROC_FLAGS,
        )
        r = subprocess.run(
            [exe, "-s", serial, "shell", "cat", _WEBVIEW_UI_DUMP],
            capture_output=True,
            text=True,
            errors="replace",  # device output can contain raw bytes — never crash sequence threads on decode
            timeout=15,
            creationflags=_SUBPROC_FLAGS,
        )
        inset = parse_webview_top_from_ui_xml(r.stdout or "")
    except (OSError, subprocess.TimeoutExpired):
        inset = None

    if inset is None:
        try:
            wr = subprocess.run(
                [exe, "-s", serial, "shell", "wm", "size"],
                capture_output=True,
                text=True,
                errors="replace",  # device output can contain raw bytes — never crash sequence threads on decode
                timeout=10,
                creationflags=_SUBPROC_FLAGS,
            )
            from sequence_geometry import parse_wm_size_output

            phys = parse_wm_size_output(wr.stdout or "")
            inset = int(round(192 * phys[1] / 1600)) if phys else 192
        except (OSError, subprocess.TimeoutExpired, ImportError):
            inset = 192

    inset = max(0, int(inset))
    _WEBVIEW_TOP_CACHE[serial] = (now, inset)
    return inset


__all__ = [
    "browser_pkg_for_clear",
    "default_view_package",
    "farmbrowser_control_broadcast",
    "farmbrowser_identity_count",
    "farmbrowser_installed",
    "farmbrowser_pkg",
    "farmbrowser_set_identity",
    "looks_like_package",
    "package_installed",
    "packages_for_view_url_attempts",
    "invalidate_webview_inset_cache",
    "parse_webview_top_from_ui_xml",
    "webview_content_top_inset",
]
