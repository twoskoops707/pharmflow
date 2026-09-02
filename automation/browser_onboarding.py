"""Browser onboarding â€” get Firefox/DuckDuckGo/Opera past first-run gates.

Chromium's First Run is handled by seeding shared_prefs (browser_adb._seed_fre_complete).
Firefox (Fenix) shows its own onboarding pager ("Welcome to Firefox" / Continue /
"Set as default" / sign-in), which swallows the VIEW intent: the browser opens and
then sits on onboarding forever. Verified live on the farm â€” that is exactly what
"opens the browser then does nothing" was.

DuckDuckGo routes LAUNCHER through OnboardingActivity ("Welcome to DuckDuckGo!")
after ``pm clear``. A VIEW intent issued while that gate is active is swallowed;
Path1/2 sequences always ``launch_app`` first, so the farm must mark
``userStage.appStage = ESTABLISHED`` in Room's ``app.db`` before open_url.

Opera (com.opera.browser) is Chromium-based but still launches
``com.opera.android.startup.WelcomeActivity`` after ``pm clear`` even when Chromium
FRE prefs are seeded. Verified live: Welcome â†’ default-browser â†’ CMP consent
("Allow") blocks Path1/2 until OEM onboarding prefs are seeded
(``oem.onboarding.completed`` + ``pending.consents=0``).

Two layers, both needed:
  1. Seed the Fenix pref / DDG userStage / Opera OEM onboarding that marks
     onboarding done (fast path, rewritten right after pm clear).
  2. Tap-through walker driven by button text from the UI dump (safety net when a
     new build renames prefs or adds a screen / widget sheet).
"""

from __future__ import annotations

import base64
import logging
import re
import time

from automation.adb_wrapper import AdbWrapper
from automation.browser_privacy import apply_browser_privacy
from automation.config import BROWSER_BRAVE, BROWSER_CHROMIUM, BROWSER_DUCKDUCKGO, BROWSER_FIREFOX, BROWSER_OPERA

logger = logging.getLogger(__name__)

_BOUNDS_RE = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')

# Farm sticky site — Fenix has no real custom-homepage URL setting; we warm a
# dabflow tab after wipe and set start_on_home_never so relaunch restores it.
_FIREFOX_FARM_HOMEPAGE_URL = "https://getdabflow.app/"

# Fenix onboarding: advance buttons, in priority order. Lowercase compare.
_FIREFOX_ADVANCE_TEXTS = (
    "continue",
    "get started",
    "start browsing",
    "skip for now",
    "skip",
    "not now",
    "maybe later",
    "no thanks",
    "not interested",
    "later",
    "done",
    "next",
    "close",
)

# Android ROLE_BROWSER / notification prompts (package=permissioncontroller).
_SYSTEM_DEFAULT_BROWSER_MARKERS = (
    "as your default browser",
    "set as your default browser",
    "set firefox as your default browser",
    "set chromium as your default browser",
    "set chrome as your default browser",
    "set brave as your default browser",
    "set opera as your default browser",
    "set duckduckgo as your default browser",
    "requestroleactivity",
    "com.android.permissioncontroller:id/role",
)

_SYSTEM_DEFAULT_DISMISS_TEXTS = (
    "cancel",
    "not now",
    "no thanks",
    "don't allow",
    "dont allow",
    "deny",
)

_SYSTEM_NOTIFICATION_MARKERS = (
    "send you notifications",
    "want to send you notifications",
    "allow notifications",
    "notification permission",
)

_SYSTEM_NOTIFICATION_DISMISS_TEXTS = (
    "don't allow",
    "dont allow",
    "no thanks",
    "deny",
    "not now",
)

# Never tap these during onboarding — they open accounts, defaults, or settings.
_FIREFOX_AVOID_TEXTS = (
    "sign in",
    "sign up",
    "set as default browser",
    "set as default",
    "add account",
    "sync",
    "import from",
    "learn more",
    "privacy notice",
    "allow",
    "turn on",
    "enable notifications",
)

# Toolbar/content markers that mean onboarding is finished and a page can load.
_FIREFOX_READY_MARKERS = (
    "mozac_browser_toolbar_url_view",
    "org.mozilla.fenix:id/toolbar",
    "org.mozilla.fenix:id/mozac_browser_toolbar_container",
    "org.mozilla.fenix:id/engineView",
    "org.mozilla.fenix:id/swipeRefresh",
    "getdabflow",
    "dabflow",
    "age-yes-btn",
    "age-no-btn",
)

# In-app sheets that still block after Terms seed (wallpaper/theme/import/etc.).
_FIREFOX_BLOCKING_MARKERS = (
    "welcome to firefox",
    "speedy, safe, and",
    "make firefox your default",
    "set firefox as your default",
    "choose a theme",
    "pick a theme",
    "import from another browser",
    "sync your devices",
    "turn on notifications",
    "enable notifications",
    "add firefox to home",
    "add search widget",
)

# Copied from what Fenix itself wrote to
# /data/data/org.mozilla.firefox/shared_prefs/fenix_preferences.xml after a live
# walk-through on the farm. The "Welcome to Firefox / Continue" screen is the Terms
# of Use gate (pref_key_terms_accepted*). Verified Aug 2026: boolean+version alone
# is NOT enough â€” Fenix still shows Welcome until pref_key_terms_accepted_date
# (long, epoch ms) is present (written natively when Continue is tapped).
# Older key names are kept too â€” unknown keys are simply ignored by the app.
_FENIX_TERMS_VERSION = 5

_FENIX_PREFS_FILE = "/data/data/{pkg}/shared_prefs/fenix_preferences.xml"


def _fenix_onboarding_prefs_xml(*, now_ms: int | None = None) -> str:
    """Build Fenix SharedPreferences XML that skips splash / Welcome / junk home."""
    ts = int(now_ms if now_ms is not None else time.time() * 1000)
    return (
        '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
        "<map>\n"
        '<boolean name="pref_key_terms_accepted" value="true" />\n'
        f'<int name="pref_key_terms_accepted_version" value="{_FENIX_TERMS_VERSION}" />\n'
        f'<long name="pref_key_terms_accepted_date" value="{ts}" />\n'
        '<boolean name="pref_key_is_first_run" value="false" />\n'
        # Verified live Aug 2026: without this, Fenix re-shows the branded splash
        # after every pm clear even when Terms prefs are seeded.
        '<boolean name="pref_key_is_first_splash_screen_shown" value="true" />\n'
        '<boolean name="pref_key_app_is_onboarding_set_as_default_displayed" value="true" />\n'
        f'<long name="pref_key_last_set_as_default_prompt_shown_time" value="{ts}" />\n'
        '<boolean name="pref_key_should_show_onboarding" value="false" />\n'
        '<boolean name="pref_key_has_shown_home_onboarding" value="true" />\n'
        '<boolean name="pref_key_should_show_default_browser_onboarding" value="false" />\n'
        '<boolean name="pref_key_should_show_marketing_onboarding" value="false" />\n'
        '<boolean name="pref_key_should_show_privacy_notice" value="false" />\n'
        '<boolean name="pref_key_user_knows_about_pwa" value="true" />\n'
        '<boolean name="pref_key_should_show_sync_cfr" value="false" />\n'
        '<boolean name="pref_key_should_show_review_prompt" value="false" />\n'
        '<boolean name="pref_key_telemetry" value="false" />\n'
        '<boolean name="pref_key_experimentation_enabled" value="false" />\n'
        '<boolean name="pref_key_nimbus_experiments_fetched" value="true" />\n'
        # Open last tab (warmed dabflow), not Firefox Home / wallpaper junk.
        '<boolean name="pref_key_start_on_home_never" value="true" />\n'
        '<boolean name="pref_key_start_on_home_always" value="false" />\n'
        '<boolean name="pref_key_start_on_home_after_four_hours" value="false" />\n'
        '<boolean name="pref_key_return_to_browser" value="true" />\n'
        # Durable dabflow homepage after wipe (Fenix key names vary by build).
        '<boolean name="pref_key_enable_custom_homepage" value="true" />\n'
        '<string name="pref_key_custom_homepage_url">https://getdabflow.app/</string>\n'
        '<string name="pref_key_homepage_custom_url">https://getdabflow.app/</string>\n'
        # Best-effort: hide sponsored/top-site/Pocket sections when keys are honored.
        '<boolean name="pref_key_show_top_sites" value="false" />\n'
        '<boolean name="pref_key_enable_contile" value="false" />\n'
        '<boolean name="pref_key_pocket_homescreen_recommendations" value="false" />\n'
        '<boolean name="pref_key_pocket_sponsored_stories" value="false" />\n'
        # Toolbar on top keeps the page rect identical to what web_viewport measured.
        '<boolean name="pref_key_toolbar_bottom" value="false" />\n'
        '<int name="pref_key_app_cold_start_count" value="1" />\n'
        "</map>\n"
    )


def seed_firefox_onboarding_complete(adb: AdbWrapper, serial: str, pkg: str = BROWSER_FIREFOX) -> bool:
    """Write the Fenix prefs that mark onboarding done (adb shell is root on MuMu)."""
    prefs_file = _FENIX_PREFS_FILE.format(pkg=pkg)
    prefs_dir = prefs_file.rsplit("/", 1)[0]
    xml_body = _fenix_onboarding_prefs_xml()
    b64 = base64.b64encode(xml_body.encode("utf-8")).decode("ascii")
    owner = adb.shell(f"stat -c '%u:%g' /data/data/{pkg}", serial=serial)
    uid_gid = (owner.stdout or "").strip() or "shell:shell"
    adb.shell(f"mkdir -p {prefs_dir}", serial=serial)
    write = adb.shell(f"echo {b64} | base64 -d > {prefs_file}", serial=serial)
    adb.shell(f"chown {uid_gid} {prefs_file}", serial=serial)
    adb.shell(f"chmod 660 {prefs_file}", serial=serial)
    adb.shell(f"restorecon {prefs_file} 2>/dev/null", serial=serial)
    if write.ok:
        logger.info("Seeded Fenix onboarding-complete prefs on %s (%s owner=%s)", serial, pkg, uid_gid)
        # Re-merge privacy keys — this seed overwrites fenix_preferences.xml.
        apply_browser_privacy(adb, serial, pkg)
    else:
        logger.warning("Fenix onboarding pref seed failed on %s (%s)", serial, pkg)
    return write.ok


def pin_system_default_browser(
    adb: AdbWrapper,
    serial: str,
    package: str = BROWSER_CHROMIUM,
) -> bool:
    """Pin ``package`` as Android ROLE_BROWSER so https VIEW skips the chooser.

    Verified live on MuMu API 32: without a holder, ``resolve-activity`` for
    https:// returns ``ResolverActivity`` (no default) — every farm browser then
    fights to become default and blocks sequences with setup / "Set as default"
    sheets. After ``cmd role add-role-holder android.app.role.BROWSER``, Chromium
    owns http(s) with ``isDefault=true``.
    """
    pkg = (package or BROWSER_CHROMIUM).strip() or BROWSER_CHROMIUM
    result = adb.shell(
        f"cmd role add-role-holder --user 0 android.app.role.BROWSER {pkg}",
        serial=serial,
    )
    # Some images omit --user; retry bare form.
    if not result.ok:
        result = adb.shell(
            f"cmd role add-role-holder android.app.role.BROWSER {pkg}",
            serial=serial,
        )
    verify = adb.shell(
        "cmd package resolve-activity --brief "
        "-a android.intent.action.VIEW -d https://example.com",
        serial=serial,
    )
    out = (verify.stdout or "").lower()
    pinned = pkg.lower() in out and "isdefault=true" in out.lower().replace(" ", "")
    if pinned or result.ok:
        logger.info(
            "Pinned ROLE_BROWSER=%s on %s (resolve_ok=%s)",
            pkg,
            serial,
            pinned,
        )
        return True
    logger.warning(
        "ROLE_BROWSER pin may have failed on %s pkg=%s out=%s",
        serial,
        pkg,
        (verify.stdout or "")[:160],
    )
    return False


def system_default_browser_prompt_visible(xml: str) -> bool:
    """True when Android ROLE_BROWSER / default-browser system dialog is up."""
    if not xml:
        return False
    low = xml.lower()
    return any(m in low for m in _SYSTEM_DEFAULT_BROWSER_MARKERS)


def system_notification_prompt_visible(xml: str) -> bool:
    """True when the system notification permission dialog is covering Firefox."""
    if not xml:
        return False
    low = xml.lower()
    return any(m in low for m in _SYSTEM_NOTIFICATION_MARKERS)


def _find_text_tap(xml: str, candidates: tuple[str, ...]) -> tuple[int, int] | None:
    """Center of the highest-priority matching button text in a UI dump."""
    best: tuple[int, tuple[int, int]] | None = None
    for chunk in xml.split("<node ")[1:]:
        text_match = re.search(r'text="([^"]*)"', chunk)
        text = (text_match.group(1) if text_match else "").strip().lower()
        desc_match = re.search(r'content-desc="([^"]*)"', chunk)
        desc = (desc_match.group(1) if desc_match else "").strip().lower()
        blob = f"{text} {desc}".strip()
        if not blob:
            continue
        rank = next(
            (i for i, want in enumerate(candidates) if want == text or want == desc or want in blob),
            None,
        )
        if rank is None:
            continue
        bounds = _BOUNDS_RE.search(chunk)
        if not bounds:
            continue
        x1, y1, x2, y2 = (int(bounds.group(i)) for i in range(1, 5))
        if x2 - x1 < 20 or y2 - y1 < 20:
            continue
        center = ((x1 + x2) // 2, (y1 + y2) // 2)
        if best is None or rank < best[0]:
            best = (rank, center)
        if rank == 0:
            break
    return best[1] if best else None


def dismiss_system_default_browser_prompt(
    adb: AdbWrapper,
    serial: str,
    *,
    dump_ui,
    max_rounds: int = 3,
    settle_s: float = 0.7,
) -> bool:
    """Cancel the Android ROLE_BROWSER prompt so it never blocks a sequence."""
    dismissed = False
    for _round in range(max_rounds):
        xml = dump_ui(adb, serial)
        if not system_default_browser_prompt_visible(xml):
            return dismissed
        target = _find_text_tap(xml, _SYSTEM_DEFAULT_DISMISS_TEXTS)
        if target is None:
            adb.shell("input keyevent 4", serial=serial)  # BACK
            dismissed = True
            time.sleep(settle_s)
            continue
        adb.tap(target[0], target[1], serial=serial)
        dismissed = True
        time.sleep(settle_s)
    return dismissed


def dismiss_system_notification_prompt(
    adb: AdbWrapper,
    serial: str,
    *,
    dump_ui,
    max_rounds: int = 3,
    settle_s: float = 0.7,
) -> bool:
    """Deny notification permission so the prompt never blocks a sequence."""
    dismissed = False
    for _round in range(max_rounds):
        xml = dump_ui(adb, serial)
        if not system_notification_prompt_visible(xml):
            return dismissed
        target = _find_text_tap(xml, _SYSTEM_NOTIFICATION_DISMISS_TEXTS)
        if target is None:
            adb.shell("input keyevent 4", serial=serial)
            dismissed = True
            time.sleep(settle_s)
            continue
        adb.tap(target[0], target[1], serial=serial)
        dismissed = True
        time.sleep(settle_s)
    return dismissed


def firefox_onboarding_visible(xml: str) -> bool:
    if not xml:
        return False
    low = xml.lower()
    # System dialogs are handled by dedicated dismiss helpers first.
    if system_default_browser_prompt_visible(xml) or system_notification_prompt_visible(xml):
        return True
    if any(marker in low for marker in _FIREFOX_BLOCKING_MARKERS):
        return True
    if any(marker.lower() in low for marker in _FIREFOX_READY_MARKERS):
        return False
    return _find_advance_node(xml) is not None


def firefox_page_ready(xml: str) -> bool:
    """True when Fenix has painted a usable page/toolbar (or dabflow is visible)."""
    if not xml:
        return False
    low = xml.lower()
    return any(marker.lower() in low for marker in _FIREFOX_READY_MARKERS)


def firefox_still_booting(xml: str) -> bool:
    """True when Firefox is in the foreground but the page hasn't painted yet.

    Fenix's branded splash / blank first window has no text and no advance node,
    so ``firefox_onboarding_visible`` reports False and the sequence taps the
    logo (err=tap). Treat a Firefox-owned dump without ready markers as still
    booting so open_url keeps re-issuing VIEW until the toolbar appears.
    """
    if not xml:
        return False
    low = xml.lower()
    if firefox_page_ready(low):
        return False
    if any(marker in low for marker in _FIREFOX_BLOCKING_MARKERS):
        # Blocking sheets have explicit dismiss paths — not a silent splash.
        return False
    # Firefox owns the window (package nodes present) but nothing usable yet.
    return "org.mozilla.firefox" in low and not _find_advance_node(low)


def _find_advance_node(xml: str) -> tuple[int, int] | None:
    """Center of the highest-priority onboarding advance button in the dump."""
    best: tuple[int, tuple[int, int]] | None = None
    for chunk in xml.split("<node ")[1:]:
        low = chunk.lower()
        text_match = re.search(r'text="([^"]*)"', chunk)
        text = (text_match.group(1) if text_match else "").strip().lower()
        desc_match = re.search(r'content-desc="([^"]*)"', chunk)
        desc = (desc_match.group(1) if desc_match else "").strip().lower()
        blob = text or desc
        if not blob:
            continue
        if any(bad in blob for bad in _FIREFOX_AVOID_TEXTS):
            continue
        rank = next(
            (
                i
                for i, want in enumerate(_FIREFOX_ADVANCE_TEXTS)
                if want == text or want == desc or want in blob
            ),
            None,
        )
        if rank is None:
            continue
        bounds = _BOUNDS_RE.search(chunk)
        if not bounds:
            continue
        x1, y1, x2, y2 = (int(bounds.group(i)) for i in range(1, 5))
        if x2 - x1 < 40 or y2 - y1 < 20:
            continue
        center = ((x1 + x2) // 2, (y1 + y2) // 2)
        if best is None or rank < best[0]:
            best = (rank, center)
        if "clickable=\"true\"" in low and rank == 0:
            break
    return best[1] if best else None


def dismiss_firefox_onboarding(
    adb: AdbWrapper,
    serial: str,
    *,
    dump_ui,
    max_rounds: int = 10,
    settle_s: float = 1.0,
) -> bool:
    """Tap through Fenix onboarding / system prompts until toolbar or dabflow is up.

    `dump_ui` is injected (browser_adb._dump_ui) to keep the short-timeout
    uiautomator behavior that stops a hung dump from freezing the farm.
    """
    dismissed = False
    for round_idx in range(max_rounds):
        xml = dump_ui(adb, serial)
        if not xml:
            time.sleep(0.6)
            continue
        if system_default_browser_prompt_visible(xml):
            dismiss_system_default_browser_prompt(adb, serial, dump_ui=dump_ui)
            dismissed = True
            continue
        if system_notification_prompt_visible(xml):
            dismiss_system_notification_prompt(adb, serial, dump_ui=dump_ui)
            dismissed = True
            continue
        low = xml.lower()
        blocking = any(marker in low for marker in _FIREFOX_BLOCKING_MARKERS)
        ready = any(marker.lower() in low for marker in _FIREFOX_READY_MARKERS)
        if ready and not blocking:
            return dismissed
        target = _find_advance_node(xml)
        if target is None:
            if blocking:
                # Blind Continue / Skip region on 900x1600 — last-resort safety net.
                logger.warning(
                    "Firefox onboarding visible but no advance node on %s — probing Continue",
                    serial,
                )
                adb.tap(450, 1420, serial=serial)
                dismissed = True
                time.sleep(settle_s)
                continue
            return dismissed
        adb.tap(target[0], target[1], serial=serial)
        dismissed = True
        logger.info(
            "Firefox onboarding tap round=%d at (%d,%d) on %s",
            round_idx + 1,
            target[0],
            target[1],
            serial,
        )
        time.sleep(settle_s)
    return dismissed


def warm_firefox_dabflow_homepage(
    adb: AdbWrapper,
    serial: str,
    pkg: str = BROWSER_FIREFOX,
    *,
    dump_ui=None,
    url: str = _FIREFOX_FARM_HOMEPAGE_URL,
    settle_s: float = 2.2,
) -> bool:
    """Open dabflow once so last-tab restore (start_on_home_never) lands on farm site.

    Call after seed / pm clear. Force-stops when done so the next launch is clean.
    """
    pkg = (pkg or BROWSER_FIREFOX).strip() or BROWSER_FIREFOX
    adb.shell(f"am force-stop {pkg}", serial=serial)
    time.sleep(0.25)
    view = adb.shell(
        f'am start -a android.intent.action.VIEW -d "{url}" -p {pkg}',
        serial=serial,
    )
    if not view.ok:
        view = adb.shell(
            f'am start -a android.intent.action.VIEW -d "{url}" '
            f"-n {pkg}/org.mozilla.fenix.IntentReceiverActivity",
            serial=serial,
        )
    time.sleep(settle_s)
    if dump_ui is not None:
        dismiss_firefox_onboarding(adb, serial, dump_ui=dump_ui, max_rounds=8)
        # Re-issue VIEW if onboarding ate the first intent.
        xml = dump_ui(adb, serial) or ""
        if "getdabflow" not in xml.lower() and "dabflow" not in xml.lower():
            adb.shell(
                f'am start -a android.intent.action.VIEW -d "{url}" -p {pkg}',
                serial=serial,
            )
            time.sleep(1.2)
            dismiss_firefox_onboarding(adb, serial, dump_ui=dump_ui, max_rounds=6)
    adb.shell(f"am force-stop {pkg}", serial=serial)
    time.sleep(0.2)
    logger.info("Warmed Firefox dabflow homepage on %s (%s)", serial, pkg)
    return bool(view.ok)


def prepare_firefox_after_wipe(
    adb: AdbWrapper,
    serial: str,
    pkg: str = BROWSER_FIREFOX,
    *,
    dump_ui=None,
) -> bool:
    """Seed splash/onboarding prefs and warm dabflow so isolate/launch stays consistent."""
    ok = seed_firefox_onboarding_complete(adb, serial, pkg)
    warm_firefox_dabflow_homepage(adb, serial, pkg, dump_ui=dump_ui)
    return ok


# ---------------------------------------------------------------------------
# DuckDuckGo â€” Room userStage + tap-through safety net
# ---------------------------------------------------------------------------

# Launcher creates app.db; BrowserActivity is the VIEW target (browser_adb).
_DDG_LAUNCHER = f"{BROWSER_DUCKDUCKGO}/com.duckduckgo.app.launch.Launcher"
_DDG_APP_DB = "/data/data/{pkg}/databases/app.db"
_DDG_DB_WAIT_S = 8.0
_DDG_DB_POLL_S = 0.35

# Advance / dismiss labels (lowercase). Prefer "Not Now" / "Search only" / "Confirm".
_DDG_ADVANCE_TEXTS = (
    "not now",
    "skip",
    "got it",
    "search only",  # AI address-bar picker â€” prefer search-only, then Confirm
    "confirm",
    "continue",
    "next",
    "maybe later",
    "no thanks",
    "later",
    "done",
    "start browsing",
    "get started",
    "let's do it",
    "lets do it",
)

_DDG_AVOID_TEXTS = (
    "add widget",
    "set as default",
    "sign in",
    "sign up",
    "sync",
    "enable",
    "turn on",
    "allow",
    "learn more",
    "show brave news",  # never hit Brave-style CTAs if they leak
)

_DDG_READY_MARKERS = (
    "com.duckduckgo.mobile.android:id/omnibarTextInput",
    "com.duckduckgo.mobile.android:id/browserWebView",
    "com.duckduckgo.mobile.android:id/webViewContainer",
    "age-gate",
    "age-yes-btn",
)

_DDG_BLOCKING_MARKERS = (
    "welcome to duckduckgo",
    "com.duckduckgo.mobile.android:id/onboardingWelcomePageContainer",
    "com.duckduckgo.mobile.android:id/homeScreenWidgetBottomSheetDialogGhostButton",
    "com.duckduckgo.mobile.android:id/homeScreenWidgetBottomSheetDialogPrimaryButton",
    # Post-ESTABLISHED AI address-bar picker (blocks VIEW / sequences for minutes).
    "com.duckduckgo.mobile.android:id/inputScreenPicker",
    "com.duckduckgo.mobile.android:id/confirmButton",
    "com.duckduckgo.mobile.android:id/inputScreen",
    "want easy access to private ai chat",
    "toggle between search and duck.ai",
)


def _ddg_db_exists(adb: AdbWrapper, serial: str, pkg: str) -> bool:
    path = _DDG_APP_DB.format(pkg=pkg)
    check = adb.shell(f"test -f {path} && echo yes", serial=serial)
    return "yes" in (check.stdout or "")


def _ddg_ensure_app_db(adb: AdbWrapper, serial: str, pkg: str) -> bool:
    """Cold-start Launcher briefly so Room creates app.db, then force-stop."""
    if _ddg_db_exists(adb, serial, pkg):
        return True
    adb.shell(f"am start -n {_DDG_LAUNCHER}", serial=serial)
    deadline = time.time() + _DDG_DB_WAIT_S
    while time.time() < deadline:
        if _ddg_db_exists(adb, serial, pkg):
            break
        time.sleep(_DDG_DB_POLL_S)
    adb.shell(f"am force-stop {pkg}", serial=serial)
    time.sleep(0.35)
    return _ddg_db_exists(adb, serial, pkg)


def seed_duckduckgo_onboarding_complete(
    adb: AdbWrapper, serial: str, pkg: str = BROWSER_DUCKDUCKGO
) -> bool:
    """Mark DuckDuckGo AppStage ESTABLISHED so Launcher/VIEW skip OnboardingActivity.

    ``pm clear`` wipes Room's ``userStage`` row. After clear we briefly launch the
    Launcher (creates ``app.db``), force-stop, then upsert ESTABLISHED. Verified live:
    VIEW then loads getdabflow.app with omnibar + age-gate.

    Retries when Room has created app.db but not yet the userStage table (race
    that left splash screens stuck on the farm).
    """
    pkg = (pkg or BROWSER_DUCKDUCKGO).strip() or BROWSER_DUCKDUCKGO
    adb.shell(f"am force-stop {pkg}", serial=serial)
    if not _ddg_ensure_app_db(adb, serial, pkg):
        logger.warning("DuckDuckGo app.db missing after bootstrap on %s (%s)", serial, pkg)
        return False
    db = _DDG_APP_DB.format(pkg=pkg)
    sql = (
        "INSERT OR REPLACE INTO userStage (key, appStage) VALUES (1, 'ESTABLISHED');"
        "SELECT key||'|'||appStage FROM userStage;"
    )
    last_err = ""
    for attempt in range(5):
        # Quote carefully for adb shell â€” no nested double quotes inside sql.
        result = adb.shell(f"sqlite3 {db} \"{sql}\"", serial=serial)
        ok = result.ok and "ESTABLISHED" in (result.stdout or "")
        if ok:
            logger.info(
                "Seeded DuckDuckGo userStage=ESTABLISHED on %s (%s) -> %s",
                serial,
                pkg,
                (result.stdout or "").strip(),
            )
            apply_browser_privacy(adb, serial, pkg)
            return True
        last_err = (result.stderr or result.stdout or "").strip()[:200]
        if "no such table" in last_err.lower():
            # Cold-start again so Room migrates schema, then retry.
            adb.shell(f"am start -n {_DDG_LAUNCHER}", serial=serial)
            time.sleep(1.0 + 0.4 * attempt)
            adb.shell(f"am force-stop {pkg}", serial=serial)
            time.sleep(0.35)
            continue
        break
    logger.warning(
        "DuckDuckGo userStage seed failed on %s (%s): %s",
        serial,
        pkg,
        last_err,
    )
    return False


def duckduckgo_onboarding_visible(xml: str) -> bool:
    """True when Welcome / widget / AI-picker sheet is up (may cover an already-loaded page)."""
    if not xml:
        return False
    low = xml.lower()
    # AI address-bar picker and widget sheets block even if omnibar exists underneath.
    if any(
        marker in low
        for marker in (
            "homescreenwidgetbottomsheetdialog",
            "try our home screen widget",
            "inputscreenpicker",
            "confirmbutton",
            "want easy access to private ai chat",
            "toggle between search and duck.ai",
        )
    ):
        return True
    if any(marker.lower() in low for marker in _DDG_READY_MARKERS):
        return False
    return any(marker in low for marker in _DDG_BLOCKING_MARKERS)


def _find_ddg_advance_node(xml: str) -> tuple[int, int] | None:
    best: tuple[int, tuple[int, int]] | None = None
    low_all = xml.lower()
    # Once Search-only is already checked, Confirm must win every round or we loop forever.
    search_only_selected = (
        'resource-id="com.duckduckgo.mobile.android:id/inputscreensearchonlycheck"' in low_all
        and 'checked="true"' in low_all
    ) or (
        "inputscreensearchonlycheck" in low_all
        and 'checked="true"' in low_all
        and "inputscreensearchonly" in low_all
    )
    for chunk in xml.split("<node ")[1:]:
        text_match = re.search(r'text="([^"]*)"', chunk)
        text = (text_match.group(1) if text_match else "").strip().lower()
        # UIAutomator escapes newlines as &#10; â€” normalize before matching.
        text = text.replace("&#10;", " ").replace("\n", " ")
        rid_match = re.search(r'resource-id="([^"]*)"', chunk)
        rid = (rid_match.group(1) if rid_match else "").lower()
        if any(bad in text for bad in _DDG_AVOID_TEXTS):
            continue
        rank: int | None = None
        # Absolute priority: yellow Confirm â€” never lose to Search-only container.
        if rid.endswith("/confirmbutton") and 'clickable="true"' in chunk:
            rank = -1
        elif text == "confirm" and 'clickable="true"' in chunk:
            rank = -1
        elif text:
            # After Search-only is checked, ignore its caption or we never reach Confirm.
            if search_only_selected and ("search only" in text):
                rank = None
            else:
                rank = next(
                    (i for i, want in enumerate(_DDG_ADVANCE_TEXTS) if want == text or want in text),
                    None,
                )
        if rank is None and "homescreenwidgetbottomsheetdialogghostbutton" in rid:
            rank = 0  # "Not Now"
        if rank is None and "inputscreensearchonlycontainer" in rid and 'clickable="true"' in chunk:
            # Already selected â†’ never re-tap the container (that was the forever loop).
            rank = None if search_only_selected else 3
        if rank is None and "inputscreensearchonlycheck" in rid and 'clickable="true"' in chunk:
            rank = None if search_only_selected else 3
        if rank is None and "onboardingwelcomepagecontainer" in rid and 'clickable="true"' in chunk:
            rank = len(_DDG_ADVANCE_TEXTS)  # tap through welcome canvas last
        if rank is None:
            continue
        bounds = _BOUNDS_RE.search(chunk)
        if not bounds:
            continue
        x1, y1, x2, y2 = (int(bounds.group(i)) for i in range(1, 5))
        if x2 - x1 < 40 or y2 - y1 < 20:
            continue
        center = ((x1 + x2) // 2, (y1 + y2) // 2)
        if best is None or rank < best[0]:
            best = (rank, center)
        if rank <= 0:
            break
    return best[1] if best else None


def dismiss_duckduckgo_onboarding(
    adb: AdbWrapper,
    serial: str,
    *,
    dump_ui,
    max_rounds: int = 16,
    settle_s: float = 0.85,
) -> bool:
    """Tap through DDG Welcome / widget / AI-picker until the omnibar or page is ready."""
    dismissed = False
    for round_idx in range(max_rounds):
        xml = dump_ui(adb, serial)
        if not xml:
            time.sleep(0.6)
            continue
        if not duckduckgo_onboarding_visible(xml):
            return dismissed
        target = _find_ddg_advance_node(xml)
        if target is None:
            # Yellow Confirm sits at ~[96,1060][804,1156] on 900x1600.
            logger.warning("DuckDuckGo onboarding visible but no advance node on %s â€” probing Confirm", serial)
            adb.tap(450, 1108, serial=serial)
            dismissed = True
            time.sleep(settle_s)
            continue
        adb.tap(target[0], target[1], serial=serial)
        dismissed = True
        logger.info(
            "DuckDuckGo onboarding tap round=%d at (%d,%d) on %s",
            round_idx + 1,
            target[0],
            target[1],
            serial,
        )
        time.sleep(settle_s)
    return dismissed


# ---------------------------------------------------------------------------
# Opera â€” WelcomeActivity / default-browser / CMP consent (OEM onboarding)
# ---------------------------------------------------------------------------
# Chromium FRE prefs (first_run_flow_complete etc.) are NOT enough: after pm clear,
# Opera still routes VIEW â†’ WelcomeActivity. Live walk-through (v100.2) showed the
# completion markers below; seeding them opens BrowserActivity straight to the URL.

# (filename, typed prefs to merge â€” never wipe unrelated Opera SharedPreferences)
_OPERA_SEED_PREFS: tuple[tuple[str, dict[str, object]], ...] = (
    (
        "onboarding-mgr.xml",
        {
            "pending.consents": 0,
            "processed.consents": 105,
            "pushed.sequence": 2,
        },
    ),
    (
        "general_prefs.xml",
        {
            "oem.onboarding.completed": True,
            "oem.onboarding.reported": True,
            "onboarding.id": "farm-seeded",
        },
    ),
    (
        "user_settings.xml",
        {
            "eula_accepted.gdpr": 1,
            "has_waited_for_startup_dependencies": 1,
            "personalized_news": 0,
            "personalized_ads": 0,
            "settings_version_key": 22,
        },
    ),
    (
        "osp_onboarding_data.xml",
        {
            "Consents": 151,  # long
        },
    ),
)

# Advance Welcome / default-browser / CMP â€” never "Set as default" / Customize.
_OPERA_ADVANCE_TEXTS = (
    "skip",
    "next",
    "allow",
    "not now",
    "no thanks",
    "maybe later",
    "continue",
    "got it",
    "agree",
    "accept",
)

_OPERA_AVOID_TEXTS = (
    "set opera as default",
    "set as default",
    "customize",
    "sign in",
    "learn more",
    "terms of service",
    "privacy statement",
)

_OPERA_ADVANCE_IDS = (
    "continue_button",
    "skip_button",
    "allow_button",
    "negative_button",
    "secondary_button",
)

_OPERA_BLOCKING_MARKERS = (
    "welcome to opera",
    "com.opera.browser:id/welcome_text",
    "com.opera.browser:id/continue_button",
    "com.opera.browser:id/skip_button",
    "com.opera.browser:id/allow_button",
    "set opera as your default browser",
    "help us make opera better",
    "personalized news recommendations",
)


def _opera_pref_snip(name: str, value: object, *, as_long: bool = False) -> str:
    if isinstance(value, bool):
        return f'<boolean name="{name}" value="{"true" if value else "false"}" />'
    if isinstance(value, int) and as_long:
        return f'<long name="{name}" value="{int(value)}" />'
    if isinstance(value, int):
        return f'<int name="{name}" value="{int(value)}" />'
    return f'<string name="{name}">{value}</string>'


def _merge_opera_prefs_xml(body: str, prefs: dict[str, object], *, long_keys: set[str] | None = None) -> str:
    """Merge typed prefs into an existing SharedPreferences map (create if empty)."""
    long_keys = long_keys or set()
    text = (body or "").strip()
    if not text:
        lines = [
            '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>',
            "<map>",
        ]
        for name, value in prefs.items():
            lines.append(_opera_pref_snip(name, value, as_long=name in long_keys))
        lines.append("</map>")
        return "\n".join(lines) + "\n"

    updated = text
    for name, value in prefs.items():
        as_long = name in long_keys
        snip = _opera_pref_snip(name, value, as_long=as_long)
        if isinstance(value, bool):
            pat = re.compile(
                rf'<boolean\s+name="{re.escape(name)}"\s+value="(?:true|false)"\s*/>',
                re.I,
            )
        elif as_long:
            pat = re.compile(
                rf'<long\s+name="{re.escape(name)}"\s+value="-?\d+"\s*/>',
                re.I,
            )
        elif isinstance(value, int):
            pat = re.compile(
                rf'<int\s+name="{re.escape(name)}"\s+value="-?\d+"\s*/>',
                re.I,
            )
        else:
            pat = re.compile(
                rf'<string\s+name="{re.escape(name)}"(?:\s*/>|>[^<]*</string>)',
                re.I,
            )
        if pat.search(updated):
            updated = pat.sub(snip, updated, count=1)
        elif "</map>" in updated:
            updated = updated.replace("</map>", f"    {snip}\n</map>", 1)
        else:
            updated = updated.rstrip() + f"\n{snip}\n"
    return updated if updated.endswith("\n") else updated + "\n"


def _write_opera_pref_file(
    adb: AdbWrapper, serial: str, pkg: str, filename: str, xml_body: str, uid_gid: str
) -> bool:
    prefs_dir = f"/data/data/{pkg}/shared_prefs"
    prefs_file = f"{prefs_dir}/{filename}"
    b64 = base64.b64encode(xml_body.encode("utf-8")).decode("ascii")
    adb.shell(f"mkdir -p {prefs_dir}", serial=serial)
    write = adb.shell(f"echo {b64} | base64 -d > {prefs_file}", serial=serial)
    adb.shell(f"chown {uid_gid} {prefs_file}", serial=serial)
    adb.shell(f"chmod 660 {prefs_file}", serial=serial)
    adb.shell(f"restorecon {prefs_file} 2>/dev/null", serial=serial)
    return bool(write.ok)


def seed_opera_onboarding_complete(
    adb: AdbWrapper, serial: str, pkg: str = BROWSER_OPERA
) -> bool:
    """Mark Opera OEM Welcome / CMP complete so VIEW skips WelcomeActivity.

    Verified live after pm clear: without this, VIEW redirects to WelcomeActivity
    despite Chromium FRE prefs. With these seeds, BrowserActivity opens the URL.
    Merges into existing SharedPreferences so mid-run open_url does not wipe state.
    """
    owner = adb.shell(f"stat -c '%u:%g' /data/data/{pkg}", serial=serial)
    uid_gid = (owner.stdout or "").strip() or "shell:shell"
    ok = True
    for filename, prefs in _OPERA_SEED_PREFS:
        prefs_file = f"/data/data/{pkg}/shared_prefs/{filename}"
        cat = adb.shell(f"cat {prefs_file}", serial=serial)
        body = cat.stdout or ""
        long_keys = {"Consents"} if filename == "osp_onboarding_data.xml" else set()
        merged = _merge_opera_prefs_xml(body, prefs, long_keys=long_keys)
        if not _write_opera_pref_file(adb, serial, pkg, filename, merged, uid_gid):
            ok = False
    if ok:
        logger.info("Seeded Opera OEM onboarding-complete prefs on %s (%s)", serial, pkg)
        # Privacy only touches {pkg}_preferences.xml â€” safe after OEM seeds.
        apply_browser_privacy(adb, serial, pkg)
    else:
        logger.warning("Opera onboarding pref seed may have failed on %s (%s)", serial, pkg)
    return ok


def opera_welcome_visible(xml: str) -> bool:
    """True when Opera Welcome / default-browser / CMP consent is covering the page."""
    if not xml:
        return False
    low = xml.lower()
    return any(marker in low for marker in _OPERA_BLOCKING_MARKERS)


def _find_opera_advance_node(xml: str) -> tuple[int, int] | None:
    best: tuple[int, tuple[int, int]] | None = None
    for chunk in xml.split("<node ")[1:]:
        text_match = re.search(r'text="([^"]*)"', chunk)
        text = (text_match.group(1) if text_match else "").strip().lower()
        desc_match = re.search(r'content-desc="([^"]*)"', chunk)
        desc = (desc_match.group(1) if desc_match else "").strip().lower()
        rid_match = re.search(r'resource-id="([^"]*)"', chunk)
        rid = (rid_match.group(1) if rid_match else "").lower()
        blob = f"{text} {desc}"
        if any(bad in blob for bad in _OPERA_AVOID_TEXTS):
            continue
        rank: int | None = None
        for i, want in enumerate(_OPERA_ADVANCE_TEXTS):
            if want == text or want == desc or (text and want in text) or (desc and want in desc):
                rank = i
                break
        if rank is None:
            for i, suffix in enumerate(_OPERA_ADVANCE_IDS):
                if rid.endswith("/" + suffix) or rid.endswith(suffix):
                    # Prefer Skip/Allow ids ahead of generic continue when text missing.
                    rank = i
                    break
        if rank is None:
            continue
        bounds = _BOUNDS_RE.search(chunk)
        if not bounds:
            continue
        x1, y1, x2, y2 = (int(bounds.group(i)) for i in range(1, 5))
        if x2 - x1 < 20 or y2 - y1 < 20:
            continue
        # Prefer the clickable host when present; TextView "Next" sits inside a
        # clickable parent â€” still fine to tap text bounds.
        center = ((x1 + x2) // 2, (y1 + y2) // 2)
        if best is None or rank < best[0]:
            best = (rank, center)
        if rank == 0:
            break
    return best[1] if best else None


def dismiss_opera_welcome(
    adb: AdbWrapper,
    serial: str,
    *,
    dump_ui,
    max_rounds: int = 10,
    settle_s: float = 0.9,
) -> bool:
    """Tap through Opera Welcome / Skip / Allow until WelcomeActivity is gone."""
    dismissed = False
    for round_idx in range(max_rounds):
        xml = dump_ui(adb, serial)
        if not xml:
            time.sleep(0.5)
            continue
        if not opera_welcome_visible(xml):
            return dismissed
        target = _find_opera_advance_node(xml)
        if target is None:
            # Next/Allow are almost always bottom-center on 900x1600; Skip is
            # top-right on the default-browser page.
            logger.warning(
                "Opera Welcome visible but no advance node on %s â€” probing Next/Skip",
                serial,
            )
            adb.tap(450, 1520, serial=serial)
            time.sleep(settle_s)
            adb.tap(820, 112, serial=serial)
            dismissed = True
            time.sleep(settle_s)
            continue
        adb.tap(target[0], target[1], serial=serial)
        dismissed = True
        logger.info(
            "Opera Welcome tap round=%d at (%d,%d) on %s",
            round_idx + 1,
            target[0],
            target[1],
            serial,
        )
        time.sleep(settle_s)
    return dismissed


def prepare_browser_for_url(adb: AdbWrapper, serial: str, package: str, *, dump_ui) -> bool:
    """Per-browser pre-URL work so the VIEW intent is not swallowed by onboarding."""
    pkg = (package or "").strip()
    if pkg == BROWSER_FIREFOX:
        # Prefs only here — open_url issues the VIEW; wipe path uses prepare_firefox_after_wipe.
        seed_firefox_onboarding_complete(adb, serial, pkg)
        return True
    if pkg == BROWSER_DUCKDUCKGO:
        seed_duckduckgo_onboarding_complete(adb, serial, pkg)
        return True
    if pkg == BROWSER_OPERA:
        # Chromium FRE seed alone does not skip WelcomeActivity — OEM prefs required.
        seed_opera_onboarding_complete(adb, serial, pkg)
        return True
    if pkg == BROWSER_BRAVE:
        # Brave reuses Chromium FRE prefs; News/Rewards sheets still need a tap-through.
        from automation.browser_adb import _seed_fre_complete

        _seed_fre_complete(adb, serial, pkg)
        return True
    if pkg == BROWSER_CHROMIUM or "chromium" in pkg or pkg.endswith(".chrome"):
        from automation.browser_adb import _seed_fre_complete

        _seed_fre_complete(adb, serial, pkg)
        return True
    return True


# ---------------------------------------------------------------------------
# Brave â€” News / Rewards / first-run sheets on top of Chromium FRE
# ---------------------------------------------------------------------------

_BRAVE_ADVANCE_TEXTS = (
    "not now",
    "no thanks",
    "maybe later",
    "later",
    "skip",
    "got it",
    "continue",
    "start using brave",
    "start browsing",
    "i'll do it later",
    "ill do it later",
    "close",
    "dismiss",
)

_BRAVE_AVOID_TEXTS = (
    "show brave news",
    "turn on",
    "enable",
    "get started with rewards",
    "start earning",
    "claim",
    "learn more",
    "sign in",
    "set as default",
    "set brave as",
    "make brave",
)

_BRAVE_BLOCKING_MARKERS = (
    "today's top stories",
    "todays top stories",
    "show brave news",
    "private feed, just for you",
    "learn more about your data",
    # Default-browser / first-run questionnaire sheets.
    "set brave as your default",
    "make brave your default",
    "brave as your default browser",
    "welcome to brave",
    "get started with brave rewards",
    "brave rewards",
    "turn on brave rewards",
    "sync your devices",
    "import bookmarks",
)

# Chromium/Brave MITM or bad-cert interstitial ("Your connection is not private").
_SSL_INTERSTITIAL_MARKERS = (
    "your connection is not private",
    "connection is not private",
    "connection is not secure",
    "your connection is not secure",
    "this website is not secure",
    "website is not safe",
    "not a private connection",
    "attackers might be trying",
    "net::err_cert",
    "err_cert_authority_invalid",
    "privacy error",
    "certificate error",
    "ssl error",
)

# HSTS sites (getdabflow.app) refuse the Proceed link â€” cannot click past MITM.
_SSL_HSTS_BLOCK_MARKERS = (
    "uses hsts",
    "website uses hsts",
    "you cannot visit",
    "cannot visit getdabflow",
)

_SSL_PROCEED_TEXTS = (
    "proceed to getdabflow.app (unsafe)",
    "proceed to getdabflow.app",
    "continue to getdabflow.app (unsafe)",
    "continue to getdabflow.app",
    "proceed to ",
    "continue to ",
    "continue to site",
    "proceed anyway",
    "visit this website",
    "accept the risk and continue",
)

# Exact label only â€” never match "Hide advanced" (substring "advanced" used to
# toggle the panel forever and never reach Proceed).
_SSL_ADVANCED_EXACT = (
    "advanced",
    "details",
)


def ssl_interstitial_visible(xml: str) -> bool:
    if not xml:
        return False
    low = xml.lower()
    return any(m in low for m in _SSL_INTERSTITIAL_MARKERS)


def ssl_hsts_blocked(xml: str) -> bool:
    """True when interstitial expanded and HSTS forbids Proceed (MITM dead-end)."""
    if not xml:
        return False
    low = xml.lower()
    return any(m in low for m in _SSL_HSTS_BLOCK_MARKERS)


def _ssl_advanced_expanded(xml: str) -> bool:
    return "hide advanced" in (xml or "").lower()


def _find_ssl_tap(
    xml: str,
    candidates: tuple[str, ...],
    *,
    exact: bool = False,
) -> tuple[int, int] | None:
    best: tuple[int, tuple[int, int]] | None = None
    for chunk in xml.split("<node ")[1:]:
        text_match = re.search(r'text="([^"]*)"', chunk)
        text = (text_match.group(1) if text_match else "").strip().lower()
        desc_match = re.search(r'content-desc="([^"]*)"', chunk)
        desc = (desc_match.group(1) if desc_match else "").strip().lower()
        blob = f"{text} {desc}".strip()
        if not blob:
            continue
        rank: int | None = None
        for i, want in enumerate(candidates):
            if exact:
                if text == want or desc == want:
                    rank = i
                    break
            elif want in blob:
                # Guard: bare "advanced" must not hit "Hide advanced".
                if want == "advanced" and "hide advanced" in blob:
                    continue
                rank = i
                break
        if rank is None:
            continue
        bounds = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', chunk)
        if not bounds:
            continue
        x1, y1, x2, y2 = (int(bounds.group(i)) for i in range(1, 5))
        pt = ((x1 + x2) // 2, (y1 + y2) // 2)
        if best is None or rank < best[0]:
            best = (rank, pt)
    return best[1] if best else None


def recover_ssl_mitm_dead_end(
    adb: AdbWrapper,
    serial: str,
    package: str | None = None,
) -> None:
    """Clear guest MITM proxy and kill the browser so a direct reload can succeed.

    Verified live: Brave on inject shows ERR_CERT + HSTS with no Proceed control;
    wiping proxy to ``:0`` and force-stopping lets https://getdabflow.app load.
    """
    try:
        adb.shell("settings put global http_proxy :0", serial=serial)
    except Exception as exc:
        logger.warning("SSL HSTS recovery: clear proxy failed on %s: %s", serial, exc)
    pkg = (package or "").strip()
    if not pkg:
        return
    try:
        adb.shell(f"am force-stop {pkg}", serial=serial)
    except Exception as exc:
        logger.warning("SSL HSTS recovery: force-stop %s failed on %s: %s", pkg, serial, exc)


def dismiss_ssl_interstitial(
    adb: AdbWrapper,
    serial: str,
    *,
    dump_ui,
    max_rounds: int = 4,
    settle_s: float = 0.45,
    package: str | None = None,
) -> bool:
    """Bypass Chromium/Brave cert warning so getdabflow can load (MITM CA miss).

    Returns True if the interstitial was cleared (or never shown after a tap).
    Returns False on HSTS lockout (no Proceed) â€” caller should reload on ``:0``.
    """
    dismissed = False
    for round_idx in range(max_rounds):
        xml = dump_ui(adb, serial)
        if not ssl_interstitial_visible(xml):
            return True if dismissed else dismissed
        if ssl_hsts_blocked(xml):
            logger.warning(
                "SSL interstitial HSTS lockout on %s â€” cannot Proceed; clearing MITM",
                serial,
            )
            recover_ssl_mitm_dead_end(adb, serial, package)
            return False
        proceed = _find_ssl_tap(xml, _SSL_PROCEED_TEXTS)
        if proceed is not None:
            adb.tap(proceed[0], proceed[1], serial=serial)
            dismissed = True
            logger.info(
                "SSL interstitial Proceed tap round=%d at (%d,%d) on %s",
                round_idx + 1,
                proceed[0],
                proceed[1],
                serial,
            )
            time.sleep(settle_s)
            continue
        if _ssl_advanced_expanded(xml):
            # Panel open, no Proceed node (often HSTS) â€” one blind Proceed, then stop.
            logger.warning(
                "SSL interstitial expanded but no Proceed node on %s â€” probing once",
                serial,
            )
            adb.tap(450, 1320, serial=serial)
            dismissed = True
            time.sleep(settle_s)
            xml2 = dump_ui(adb, serial)
            if ssl_interstitial_visible(xml2) and (
                ssl_hsts_blocked(xml2) or _ssl_advanced_expanded(xml2)
            ):
                logger.warning(
                    "SSL interstitial still blocking on %s after probe â€” clearing MITM",
                    serial,
                )
                recover_ssl_mitm_dead_end(adb, serial, package)
                return False
            continue
        advanced = _find_ssl_tap(xml, _SSL_ADVANCED_EXACT, exact=True)
        if advanced is not None:
            adb.tap(advanced[0], advanced[1], serial=serial)
            dismissed = True
            logger.info(
                "SSL interstitial Advanced tap round=%d at (%d,%d) on %s",
                round_idx + 1,
                advanced[0],
                advanced[1],
                serial,
            )
            time.sleep(settle_s)
            continue
        logger.warning(
            "SSL interstitial visible but no node on %s â€” probing Advanced/Proceed",
            serial,
        )
        adb.tap(200, 1180, serial=serial)
        time.sleep(settle_s)
        adb.tap(450, 1320, serial=serial)
        dismissed = True
        time.sleep(settle_s)
    xml_final = dump_ui(adb, serial)
    if ssl_interstitial_visible(xml_final):
        if ssl_hsts_blocked(xml_final) or package:
            recover_ssl_mitm_dead_end(adb, serial, package)
        return False
    return dismissed


def brave_overlay_visible(xml: str) -> bool:
    if not xml:
        return False
    low = xml.lower()
    return any(marker in low for marker in _BRAVE_BLOCKING_MARKERS)


def _find_brave_advance_node(xml: str) -> tuple[int, int] | None:
    best: tuple[int, tuple[int, int]] | None = None
    for chunk in xml.split("<node ")[1:]:
        text_match = re.search(r'text="([^"]*)"', chunk)
        text = (text_match.group(1) if text_match else "").strip().lower()
        desc_match = re.search(r'content-desc="([^"]*)"', chunk)
        desc = (desc_match.group(1) if desc_match else "").strip().lower()
        rid_match = re.search(r'resource-id="([^"]*)"', chunk)
        rid = (rid_match.group(1) if rid_match else "").lower()
        blob = f"{text} {desc}"
        if any(bad in blob for bad in _BRAVE_AVOID_TEXTS):
            continue
        rank: int | None = None
        if text or desc:
            rank = next(
                (
                    i
                    for i, want in enumerate(_BRAVE_ADVANCE_TEXTS)
                    if want == text or want in text or want == desc or want in desc
                ),
                None,
            )
        # Common close / dismiss affordances.
        if rank is None and (
            "close" in desc
            or desc in ("dismiss", "cancel")
            or rid.endswith("/close_button")
            or rid.endswith("/negative_button")
            or "ic_close" in rid
        ):
            rank = 0
        if rank is None:
            continue
        bounds = _BOUNDS_RE.search(chunk)
        if not bounds:
            continue
        x1, y1, x2, y2 = (int(bounds.group(i)) for i in range(1, 5))
        if x2 - x1 < 20 or y2 - y1 < 20:
            continue
        center = ((x1 + x2) // 2, (y1 + y2) // 2)
        if best is None or rank < best[0]:
            best = (rank, center)
        if rank == 0:
            break
    return best[1] if best else None


def dismiss_brave_overlays(
    adb: AdbWrapper,
    serial: str,
    *,
    dump_ui,
    max_rounds: int = 6,
    settle_s: float = 0.8,
) -> bool:
    """Dismiss Brave News / Rewards / default-browser / first-run sheets."""
    dismissed = False
    for round_idx in range(max_rounds):
        xml = dump_ui(adb, serial)
        if not xml:
            time.sleep(0.5)
            continue
        if system_default_browser_prompt_visible(xml):
            dismiss_system_default_browser_prompt(adb, serial, dump_ui=dump_ui)
            dismissed = True
            continue
        if system_notification_prompt_visible(xml):
            dismiss_system_notification_prompt(adb, serial, dump_ui=dump_ui)
            dismissed = True
            continue
        if not brave_overlay_visible(xml):
            return dismissed
        target = _find_brave_advance_node(xml)
        if target is None:
            # Modal X is usually top-right of the card.
            logger.warning("Brave overlay visible but no advance node on %s â€” probing close", serial)
            adb.tap(820, 420, serial=serial)
            dismissed = True
            time.sleep(settle_s)
            continue
        adb.tap(target[0], target[1], serial=serial)
        dismissed = True
        logger.info(
            "Brave overlay tap round=%d at (%d,%d) on %s",
            round_idx + 1,
            target[0],
            target[1],
            serial,
        )
        time.sleep(settle_s)
    return dismissed


def ensure_browser_ready_for_farm(
    adb: AdbWrapper,
    serial: str,
    package: str,
    *,
    dump_ui=None,
) -> bool:
    """After isolate wipe: seed onboarding prefs and dismiss blocking splash sheets."""
    pkg = (package or "").strip()
    if not pkg:
        return False

    # Always keep Chromium as system default so Firefox/Brave/DDG stop fighting
    # for ROLE_BROWSER and https VIEW never lands on ResolverActivity.
    pin_system_default_browser(adb, serial, BROWSER_CHROMIUM)

    dump = dump_ui
    prepare_browser_for_url(adb, serial, pkg, dump_ui=dump or (lambda _a, _s: ""))

    if pkg == BROWSER_FIREFOX:
        return prepare_firefox_after_wipe(adb, serial, pkg, dump_ui=dump)

    if pkg == BROWSER_DUCKDUCKGO:
        seed_duckduckgo_onboarding_complete(adb, serial, pkg)
        if dump:
            adb.shell(
                f'am start -a android.intent.action.VIEW -d "https://getdabflow.app/" -p {pkg}',
                serial=serial,
            )
            time.sleep(2.0)
            dismiss_duckduckgo_onboarding(adb, serial, dump_ui=dump, max_rounds=8)
            adb.shell(f"am force-stop {pkg}", serial=serial)
        return True

    if pkg == BROWSER_OPERA:
        seed_opera_onboarding_complete(adb, serial, pkg)
        if dump:
            adb.shell(
                f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1",
                serial=serial,
            )
            time.sleep(2.0)
            dismiss_opera_welcome(adb, serial, dump_ui=dump)
            adb.shell(f"am force-stop {pkg}", serial=serial)
        return True

    if pkg in (BROWSER_BRAVE, BROWSER_CHROMIUM) or "chromium" in pkg or "chrome" in pkg:
        from automation.browser_adb import dismiss_chromium_fre, prepare_chromium

        prepare_chromium(adb, serial, force=True)
        if dump:
            adb.shell(
                f'am start -a android.intent.action.VIEW -d "https://getdabflow.app/" -p {pkg}',
                serial=serial,
            )
            time.sleep(1.5)
            dismiss_chromium_fre(adb, serial)
            if pkg == BROWSER_BRAVE:
                dismiss_brave_overlays(adb, serial, dump_ui=dump)
            adb.shell(f"am force-stop {pkg}", serial=serial)
        return True

    if dump:
        dismiss_blocking_browser_overlays(adb, serial, pkg, dump_ui=dump)
    return True


def dismiss_blocking_browser_overlays(
    adb: AdbWrapper,
    serial: str,
    package: str,
    *,
    dump_ui,
) -> bool:
    """One-shot safety net: clear any known browser sheet before sequence taps."""
    pkg = (package or "").strip()
    did = False
    # One snapshot for detection: every check runs against the SAME dump so a
    # clear screen costs a single uiautomator dump, not 3-6. The old per-check
    # dumps stacked into multi-second age-gate hangs across 8 busy phones.
    # Re-dump only after a real dismissal, because acting can change the screen.
    xml0 = dump_ui(adb, serial)
    if system_default_browser_prompt_visible(xml0):
        did = dismiss_system_default_browser_prompt(adb, serial, dump_ui=dump_ui) or did
        xml0 = dump_ui(adb, serial)
    if system_notification_prompt_visible(xml0):
        did = dismiss_system_notification_prompt(adb, serial, dump_ui=dump_ui) or did
        xml0 = dump_ui(adb, serial)
    if ssl_interstitial_visible(xml0):
        did = dismiss_ssl_interstitial(adb, serial, dump_ui=dump_ui) or did
        xml0 = dump_ui(adb, serial)
    if pkg == BROWSER_DUCKDUCKGO and duckduckgo_onboarding_visible(xml0):
        return dismiss_duckduckgo_onboarding(adb, serial, dump_ui=dump_ui) or did
    if pkg == BROWSER_FIREFOX and firefox_onboarding_visible(xml0):
        return dismiss_firefox_onboarding(adb, serial, dump_ui=dump_ui) or did
    if pkg == BROWSER_OPERA and opera_welcome_visible(xml0):
        return dismiss_opera_welcome(adb, serial, dump_ui=dump_ui) or did
    if pkg == BROWSER_BRAVE and brave_overlay_visible(xml0):
        return dismiss_brave_overlays(adb, serial, dump_ui=dump_ui) or did
    return did
