"""Browser privacy hardening for legitimate farm UI testing.

After each browser wipe / onboarding seed, disable crash reporting, telemetry,
diagnostics, usage metrics, account sync / sign-in prompts, personalized
services, and background reporting where the browser exposes safe prefs or
command-line switches. URL loading and normal browsing must keep working.

This module does **not** implement fingerprint spoofing, stealth/evasion,
ad-clicking, or anti-detection.

Limitations (read before claiming "private"):
- Prefs and flags are best-effort. Newer browser builds may rename or ignore keys.
- Site page loads, DNS, TLS, CDNs, ads/scripts on the visited page, and the farm
  Tor/proxy path still generate network traffic by design.
- Vendor code paths that ignore SharedPreferences / chrome-command-line can still
  phone home; we cannot guarantee zero exfiltration.
- DuckDuckGo is privacy-oriented by default; we only seed known opt-outs / skip
  prompts where documented keys exist.
- ``--metrics-recording-only`` still runs metrics *code* but drops uploads when
  the switch is honored; it is not a kernel-level block.
"""

from __future__ import annotations

import base64
import logging
import re
from typing import Mapping

from automation.adb_wrapper import AdbWrapper
from automation.config import (
    BROWSER_BRAVE,
    BROWSER_CHROMIUM,
    BROWSER_DUCKDUCKGO,
    BROWSER_FIREFOX,
    BROWSER_OPERA,
)

logger = logging.getLogger(__name__)

# Stock Chrome package used as Chromium fallback on some images.
_CHROME_STOCK = "com.android.chrome"

# ---------------------------------------------------------------------------
# Documented surface for operators / tests
# ---------------------------------------------------------------------------

PRIVACY_DISABLED_CONTROLS = (
    "Chromium/Brave: crash reporter (breakpad), metrics upload, domain reliability, "
    "sync, sign-in/FRE prompts, usage & crash report prefs, interest feed / autofill "
    "server communication feature flags",
    "Brave extras: P3A and stats reporting prefs when recognized",
    "Firefox: telemetry, experimentation/Nimbus, crash reporting, marketing telemetry, "
    "sync CFR / sign-in prompts (shared_prefs)",
    "DuckDuckGo: known onboarding / notification / pixel opt-out prefs when recognized",
)

PRIVACY_NOT_GUARANTEED = (
    "Zero network exfiltration from the browser process or OS",
    "Blocking first-party site, CDN, ad, or analytics traffic from loaded pages",
    "Future browser builds honoring every preference key or command-line switch",
    "Fingerprint / UA / WebRTC / canvas anonymity (out of scope)",
)

# Safe Chromium-family switches: no stealth, no networking kill-switch that
# breaks page loads (avoid --disable-background-networking / component-update).
CHROMIUM_PRIVACY_FLAGS: tuple[str, ...] = (
    "--disable-breakpad",
    "--disable-crash-reporter",
    "--metrics-recording-only",
    "--disable-domain-reliability",
    "--disable-sync",
    "--disable-features=InterestFeedContentSuggestions,AutofillServerCommunication",
)

# Chromium / Brave SharedPreferences (boolean). Unknown keys are ignored by the app.
CHROMIUM_PRIVACY_BOOL_PREFS: dict[str, bool] = {
    # Metrics / crash / diagnostics
    "metrics_reporting_enabled": False,
    "Chrome.Metrics.MetricsReportingEnabled": False,
    "Chrome.Metrics.ReportingEnabled": False,
    "usage_and_crash_reporting": False,
    "Chrome.Privacy.UsageAndCrashReportsEnabled": False,
    "crash_dump_upload_enabled": False,
    # Sync / account / personalized prompts
    "Chrome.Sync.IsSyncRequested": False,
    "Chrome.Sync.KeepReadingEnabled": False,
    "signin_allowed": False,
    "Chrome.Signin.SigninAllowed": False,
    "Chrome.Signin.Allowed": False,
    "Chrome.Signin.Promo.IsEnabled": False,
    "signin_promo_shown": True,
    "Chrome.NTP.InterestFeed.ArticlesListVisible": False,
    # Background reporting-ish surfaces
    "Chrome.Notifications.PermissionPromptShown": True,
    "Chrome.Download.PromptForDownload": False,
    # Default-browser / FRE — keep farm on page, not setup questionnaire.
    "applink.chrome_default_browser": True,
    "promos_skipped_on_first_start": True,
    "first_run_flow": True,
    "first_run_flow_complete": True,
    "skip_welcome_page": True,
}

BRAVE_EXTRA_BOOL_PREFS: dict[str, bool] = {
    "p3a_enabled": False,
    "brave_p3a_enabled": False,
    "brave_stats_reporting_enabled": False,
    "daily_stats_reporting_enabled": False,
    "Brave.P3A.Enabled": False,
    "Brave.Stats.ReportingEnabled": False,
}

# Extra Fenix keys beyond the onboarding seed (telemetry already false there).
FIREFOX_PRIVACY_BOOL_PREFS: dict[str, bool] = {
    "pref_key_telemetry": False,
    "pref_key_experimentation_enabled": False,
    "pref_key_marketing_opt_in": False,
    "pref_key_crash_reporting_always_report": False,
    "pref_key_crash_reporting_installed": False,
    "pref_key_leaks_telemetry": False,
    "pref_key_studies_enabled": False,
    "pref_key_should_show_sync_cfr": False,
    "pref_key_should_show_review_prompt": False,
    "pref_key_should_show_privacy_notice": False,
    "pref_key_nimbus_experiments_fetched": True,
}

DUCKDUCKGO_PRIVACY_BOOL_PREFS: dict[str, bool] = {
    # Onboarding / prompts — keep the browser on a page, not a tour.
    "HAS_SEEN_ONBOARDING": True,
    "ONBOARDING_COMPLETE": True,
    "USER_ENABLED_NOTIFICATIONS": False,
    "NOTIFICATIONS_ENABLED": False,
    # Best-effort pixel / usage opt-outs (keys vary by DDG build).
    "TELEMETRY_ENABLED": False,
    "USAGE_DATA_ENABLED": False,
    "PIXELS_ENABLED": False,
}

_BOOL_PREF_RE = re.compile(
    r'<boolean\s+name="([^"]+)"\s+value="(true|false)"\s*/>',
    re.IGNORECASE,
)


def privacy_limitations_summary() -> str:
    """Human-readable what we disable vs what we cannot guarantee."""
    disabled = "; ".join(PRIVACY_DISABLED_CONTROLS)
    not_guaranteed = "; ".join(PRIVACY_NOT_GUARANTEED)
    return (
        f"Disabled (best-effort): {disabled}. "
        f"Not guaranteed: {not_guaranteed}."
    )


def chromium_privacy_command_line_flags() -> str:
    """Space-joined privacy switches for chrome-command-line."""
    return " ".join(CHROMIUM_PRIVACY_FLAGS)


def append_privacy_flags(command_line: str) -> str:
    """Append privacy switches to an existing Chromium command line without duplicates."""
    base = (command_line or "").rstrip()
    if not base:
        return "chrome " + chromium_privacy_command_line_flags()
    additions: list[str] = []
    for flag in CHROMIUM_PRIVACY_FLAGS:
        # Feature-list flag: match by prefix so we do not duplicate the switch.
        token = flag.split("=", 1)[0]
        if token in base:
            continue
        additions.append(flag)
    if not additions:
        return base
    return f"{base} {' '.join(additions)}"


def merge_boolean_prefs_xml(body: str, prefs: Mapping[str, bool]) -> str:
    """Merge boolean SharedPreferences into an Android prefs XML map."""
    text = (body or "").strip()
    if not text:
        lines = [
            '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>',
            "<map>",
        ]
        for name, value in prefs.items():
            val = "true" if value else "false"
            lines.append(f'<boolean name="{name}" value="{val}" />')
        lines.append("</map>")
        return "\n".join(lines) + "\n"

    existing = {m.group(1): m.group(2).lower() == "true" for m in _BOOL_PREF_RE.finditer(text)}
    updated = text
    for name, value in prefs.items():
        val = "true" if value else "false"
        snip = f'<boolean name="{name}" value="{val}" />'
        if name in existing:
            updated = re.sub(
                rf'<boolean\s+name="{re.escape(name)}"\s+value="(true|false)"\s*/>',
                snip,
                updated,
                count=1,
                flags=re.IGNORECASE,
            )
        elif "</map>" in updated:
            updated = updated.replace("</map>", f"    {snip}\n</map>", 1)
        else:
            updated = updated.rstrip() + f"\n{snip}\n"
    return updated if updated.endswith("\n") else updated + "\n"


def _prefs_path_for_package(package: str) -> str | None:
    pkg = (package or "").strip()
    if pkg in (BROWSER_CHROMIUM, _CHROME_STOCK, BROWSER_BRAVE, BROWSER_OPERA):
        return f"/data/data/{pkg}/shared_prefs/{pkg}_preferences.xml"
    if pkg == BROWSER_FIREFOX:
        return f"/data/data/{pkg}/shared_prefs/fenix_preferences.xml"
    if pkg == BROWSER_DUCKDUCKGO:
        return f"/data/data/{pkg}/shared_prefs/{pkg}_preferences.xml"
    return None


def _bool_prefs_for_package(package: str) -> dict[str, bool] | None:
    pkg = (package or "").strip()
    if pkg in (BROWSER_CHROMIUM, _CHROME_STOCK):
        return dict(CHROMIUM_PRIVACY_BOOL_PREFS)
    if pkg in (BROWSER_BRAVE, BROWSER_OPERA):
        merged = dict(CHROMIUM_PRIVACY_BOOL_PREFS)
        if pkg == BROWSER_BRAVE:
            merged.update(BRAVE_EXTRA_BOOL_PREFS)
        return merged
    if pkg == BROWSER_FIREFOX:
        return dict(FIREFOX_PRIVACY_BOOL_PREFS)
    if pkg == BROWSER_DUCKDUCKGO:
        return dict(DUCKDUCKGO_PRIVACY_BOOL_PREFS)
    return None


def _write_prefs_file(
    adb: AdbWrapper,
    serial: str,
    package: str,
    prefs_path: str,
    xml_body: str,
) -> bool:
    """Write prefs via base64 decode on device (root adb shell on MuMu)."""
    b64 = base64.b64encode(xml_body.encode("utf-8")).decode("ascii")
    prefs_dir = prefs_path.rsplit("/", 1)[0]
    owner = adb.shell(f"stat -c '%u:%g' /data/data/{package}", serial=serial)
    uid_gid = (owner.stdout or "").strip() or "shell:shell"
    adb.shell(f"mkdir -p {prefs_dir}", serial=serial)
    write = adb.shell(f"echo {b64} | base64 -d > {prefs_path}", serial=serial)
    adb.shell(f"chown {uid_gid} {prefs_path}", serial=serial)
    adb.shell(f"chmod 660 {prefs_path}", serial=serial)
    adb.shell(f"restorecon {prefs_path} 2>/dev/null", serial=serial)
    return bool(write.ok)


def apply_browser_privacy(adb: AdbWrapper, serial: str, package: str) -> bool:
    """Apply best-effort privacy prefs for a known browser package.

    Safe no-op for unknown packages. Preserves existing FRE / onboarding keys by
    merging into the current SharedPreferences XML when present.
    """
    pkg = (package or "").strip()
    prefs = _bool_prefs_for_package(pkg)
    prefs_path = _prefs_path_for_package(pkg)
    if not prefs or not prefs_path:
        return False

    cat = adb.shell(f"cat {prefs_path}", serial=serial)
    body = cat.stdout or ""
    merged = merge_boolean_prefs_xml(body, prefs)
    ok = _write_prefs_file(adb, serial, pkg, prefs_path, merged)
    if ok:
        logger.info("Applied browser privacy prefs on %s (%s)", serial, pkg)
    else:
        logger.warning("Browser privacy pref write failed on %s (%s)", serial, pkg)
    return ok
