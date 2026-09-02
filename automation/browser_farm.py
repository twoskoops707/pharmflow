"""Browser flow — browser-only identity + scramble before every visit (no MuMu VM patch)."""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Any

from automation.browser_adb import (
    BrowserInfo,
    BrowserKind,
    browser_info_for_package,
    clear_browser_package,
    clear_chromium_all_data,
    open_url,
    prepare_chromium,
    select_browser,
    select_browser_weighted,
    select_chromium_browser,
)
from automation.browser_identity import (
    BrowserSessionProfile,
    ensure_browser_identity_before_browse,
)
from automation.browse_proxy import (
    browser_package_for_serial,
    dabflow_browse_active,
    prepare_browse_session,
    restore_inject_after_identity,
)
from automation.config import BROWSER_CHROMIUM, is_browser_only_identity, is_skip_fingerprint, require_unique_exit_ip
from automation.dabflow_mantis_client_patch import maybe_apply_after_open_url_step
from automation.emulator_ad_mode import (
    emulator_ad_mode_enabled,
    ensure_ads_visible_browser_hidden,
    hide_browser_chrome,
    pause_tor_for_ads,
)
from automation.mumu_shell_cli import phone_vm_index

if TYPE_CHECKING:
    from wizard.mumu_farm_ops import MuMuFarmOps

logger = logging.getLogger(__name__)

# Per-phone browser session profiles (scrambled at each sequence start).
_browser_profiles: dict[str, BrowserSessionProfile] = {}
# Chosen browser package for the current sequence (set at isolation wipe time).
_browser_choice_by_phone: dict[str, BrowserInfo] = {}


def is_path3_sequence_name(name: str) -> bool:
    stem = (name or "").strip().lower().rsplit(".", 1)[0]
    return stem.endswith("_ad") or stem.endswith("_ad_multi")


def get_browser_profile(name: str) -> BrowserSessionProfile | None:
    return _browser_profiles.get(name)


def get_browser_profile_for_serial(serial: str) -> BrowserSessionProfile | None:
    """Resolve scramble profile for a live ADB serial (android_id match, else None)."""
    serial = (serial or "").strip()
    if not serial or not _browser_profiles:
        return None
    # Prefer exact android_id match when we can read the device.
    try:
        from automation.adb_wrapper import AdbWrapper
        from automation.browser_identity import read_secure_android_id

        adb = AdbWrapper()
        live_aid = read_secure_android_id(adb, serial)
        if live_aid:
            for prof in _browser_profiles.values():
                if getattr(prof, "android_id", "") == live_aid:
                    return prof
    except Exception:
        pass
    return None


def get_sequence_browser(name: str) -> BrowserInfo | None:
    return _browser_choice_by_phone.get(name)


def choose_sequence_browser(
    farm: Any,
    name: str,
    *,
    force_chromium: bool = False,
    preferred_package: str = "",
) -> BrowserInfo | None:
    """Pick + stash browser for this sequence (Path3 => Chromium)."""
    farm.refresh_serials()
    inst = farm.get_phone(name) if hasattr(farm, "get_phone") else farm.instances.get(name)
    if not inst or not inst.adb_serial:
        return None
    name = inst.name
    serial = inst.adb_serial
    preferred = (preferred_package or "").strip()
    browser: BrowserInfo | None = None
    if force_chromium:
        browser = select_chromium_browser(farm.adb, serial) or select_browser(farm.adb, serial)
    elif preferred:
        packages = set(farm.adb.pm_list_packages(serial=serial))
        if preferred in packages:
            browser = browser_info_for_package(preferred)
        if browser is None:
            logger.warning(
                "[%s] preferred browser %s missing — weighted fallback",
                name,
                preferred,
            )
    if browser is None:
        browser = select_browser_weighted(
            farm.adb,
            serial,
            force_chromium=force_chromium,
        )
    if browser is None:
        return None
    _browser_choice_by_phone[name] = browser
    stash = getattr(farm, "_browser_choice_by_phone", None)
    if not isinstance(stash, dict):
        stash = {}
        farm._browser_choice_by_phone = stash
    stash[name] = browser.package
    # Persist before Tor/inject setup so _setup_reverse + proxy watcher never
    # slap the MITM CA onto Firefox/DuckDuckGo mid-isolate.
    try:
        from automation.browse_proxy import remember_browser_package

        remember_browser_package(serial, browser.package)
    except Exception as exc:
        logger.debug("[%s] remember browser soft-fail: %s", name, exc)
    logger.info(
        "[%s] sequence browser=%s (%s) force_chromium=%s preferred=%s",
        name,
        browser.label,
        browser.package,
        force_chromium,
        preferred or "-",
    )
    return browser



def _ensure_unique_exit_ip_after_scramble(
    farm: Any,
    name: str,
    phone_idx: int,
    serial: str,
) -> None:
    """Start Tor and verify exit IP changed vs last sequence when required.

    Per-phone ready flags — a shared farm flag caused concurrent phones to skip
    NEWNYM (one phone set ready=True → others skipped IP switch entirely).
    """
    if not require_unique_exit_ip():
        return
    ready = getattr(farm, "_exit_ip_ready_phones", None)
    if not isinstance(ready, dict):
        ready = {}
        farm._exit_ip_ready_phones = ready
    if ready.get(name):
        return
    try:
        if hasattr(farm, "setup_tor"):
            farm.setup_tor(name)
        ip_result = farm.tor.ensure_unique_exit_ip(phone_idx, serial)
        by_phone = getattr(farm, "_last_exit_ip_rotate_by_phone", None)
        if not isinstance(by_phone, dict):
            by_phone = {}
            farm._last_exit_ip_rotate_by_phone = by_phone
        by_phone[name] = ip_result
        farm._last_exit_ip_rotate = ip_result
        ready[name] = bool(getattr(ip_result, "ok", False) and getattr(ip_result, "changed", False))
        logger.info("[%s] %s", name, ip_result.log_line())
        # Device must actually route via Tor — ad-fill sometimes left http_proxy=:0.
        proxy = (farm.adb.shell("settings get global http_proxy", serial=serial).stdout or "").strip()
        try:
            from automation.tor_manager import phone_http_port as _php

            expect = f"127.0.0.1:{_php(phone_idx)}"
        except Exception:
            expect = f"127.0.0.1:{8118 + int(phone_idx)}"
        if expect not in proxy and "127.0.0.1:" not in proxy:
            logger.warning(
                "[%s] http_proxy cleared after IP rotate (%s) — re-applying Tor",
                name,
                proxy,
            )
            farm.tor.start_phone_tor(phone_idx, serial)
            proxy = (farm.adb.shell("settings get global http_proxy", serial=serial).stdout or "").strip()
        if not ip_result.ok or not ip_result.changed:
            ready[name] = False
            raise RuntimeError(
                f"exit IP not unique after rotate ({ip_result.log_line()})"
            )
        # Firefox/DDG scramble intentionally clears guest proxy after Tor is up.
        try:
            from automation.browse_proxy import (
                browse_proxy_mode,
                browser_package_for_serial,
                skips_mitm,
            )

            pkg = browser_package_for_serial(serial)
            cleared_ok = (
                skips_mitm(pkg)
                and browse_proxy_mode() in ("scramble", "direct", "upstream")
                and (not proxy or proxy.endswith(":0") or proxy.lower() in ("null", "none"))
            )
        except Exception:
            cleared_ok = False
        if "127.0.0.1:" not in proxy and not cleared_ok:
            ready[name] = False
            raise RuntimeError(f"device http_proxy not Tor after rotate (got {proxy!r})")
        ready[name] = True
    except Exception as exc:
        ready[name] = False
        logger.warning("Unique exit IP failed for %s: %s", name, exc)
        raise


def clear_browser_before_sequence(
    farm: Any,
    name: str,
    *,
    force_chromium: bool = False,
    preferred_package: str = "",
) -> bool:
    """Pick sequence browser, then wipe its history/cookies/cache before the run."""
    farm.refresh_serials()
    inst = farm.get_phone(name) if hasattr(farm, "get_phone") else farm.instances.get(name)
    if not inst or not inst.adb_serial:
        logger.warning("clear_browser_before_sequence: no device for %s", name)
        return False
    name = inst.name
    browser = choose_sequence_browser(
        farm,
        name,
        force_chromium=force_chromium,
        preferred_package=preferred_package,
    )
    if browser is None or not browser.package:
        return clear_chromium_all_data(farm.adb, inst.adb_serial)
    return clear_browser_package(farm.adb, inst.adb_serial, browser.package)


def scramble_for_sequence(
    farm: Any, name: str, *, rotate_ip: bool = True
) -> BrowserSessionProfile | None:
    """Scramble browser identity at the start of a new sequence."""
    inst = farm.get_phone(name) if hasattr(farm, "get_phone") else farm.instances.get(name)
    serial0 = getattr(inst, "adb_serial", None) if inst else None
    live = False
    if serial0:
        try:
            live = bool(farm.adb.wait_for_device(str(serial0), timeout=1.5))
        except Exception:
            live = False
    if not live:
        farm.refresh_serials()
        inst = farm.get_phone(name) if hasattr(farm, "get_phone") else farm.instances.get(name)
    if not inst or not inst.adb_serial:
        logger.error("Cannot scramble — no device for %s", name)
        return None
    name = inst.name
    serial = inst.adb_serial
    phone_idx = phone_vm_index(name, int(getattr(inst, "index", 0) or 0))
    try:
        inst.index = phone_idx
    except Exception:
        pass

    if dabflow_browse_active() or require_unique_exit_ip():
        prepare_browse_session(farm.adb, serial, phone_idx)

    profile, report = ensure_browser_identity_before_browse(
        farm.adb,
        serial,
        phone_idx,
        scramble=True,
    )
    _browser_profiles[name] = profile
    if not report.passed:
        logger.error("Browser headers not verified for %s: %s", name, report.failures)
    else:
        logger.info("Browser scrambled for %s -> %s (%s)", name, profile.model, profile.key)
    try:
        from automation.mantis_inject_proxy import publish_client_hints_for_phone

        publish_client_hints_for_phone(phone_idx, profile)
    except Exception:
        pass
    if rotate_ip:
        _ensure_unique_exit_ip_after_scramble(farm, name, phone_idx, serial)
    # prepare_browse_session clears :0 for identity verify — Chromium must not
    # linger on null/:0 through long Tor NEWNYM / Lawnchair idle (stagnant look).
    try:
        pkg = browser_package_for_serial(serial) or ""
        chosen = _browser_choice_by_phone.get(name)
        if chosen is not None and getattr(chosen, "package", None):
            pkg = chosen.package or pkg
        pinned = restore_inject_after_identity(
            farm.adb, serial, phone_idx, browser_package=pkg or None, attempts=2
        )
        logger.info("[%s] post-scramble guest proxy -> %s", name, pinned)
    except Exception as exc:
        logger.warning("[%s] post-scramble inject restore soft-fail: %s", name, exc)
    return profile


def browse_url(farm: Any, name: str, url: str) -> bool:
    """Browse with scrambled browser headers; clears Tor proxy when in scramble mode."""
    farm.refresh_serials()
    inst = farm.get_phone(name) if hasattr(farm, "get_phone") else farm.instances.get(name)
    if not inst or not inst.adb_serial:
        logger.error("No ADB serial for %s", name)
        return False
    name = inst.name
    serial = inst.adb_serial
    phone_idx = phone_vm_index(name, int(getattr(inst, "index", 0) or 0))
    try:
        inst.index = phone_idx
    except Exception:
        pass

    if not farm.adb.wait_for_device(serial, timeout=30.0):
        logger.error("Device %s offline before browse", serial)
        return False

    if dabflow_browse_active():
        prepare_browse_session(farm.adb, serial, phone_idx)

    profile = _browser_profiles.get(name)
    if profile is None:
        profile, report = ensure_browser_identity_before_browse(
            farm.adb, serial, phone_idx, scramble=True,
        )
        _browser_profiles[name] = profile
        if not report.passed and not is_skip_fingerprint():
            logger.error("Browser header verify failed for %s: %s", name, report.failures)
            return False
    else:
        from automation.browser_identity import verify_browser_headers

        report = verify_browser_headers(farm.adb, serial, profile)
        if not report.passed:
            profile, report = ensure_browser_identity_before_browse(
                farm.adb, serial, phone_idx, scramble=True,
            )
            _browser_profiles[name] = profile
            if not report.passed and not is_skip_fingerprint():
                logger.error("Browser header re-verify failed for %s", name)
                return False

    browser = _browser_choice_by_phone.get(name)
    if browser is None:
        browser = select_browser(farm.adb, serial)
    if not browser:
        logger.error("No browser available on %s", name)
        return False
    # Firefox/DDG must NOT sit on the MITM inject CA (their own cert stores reject it).
    try:
        from automation.browse_proxy import pin_guest_proxy

        pinned = pin_guest_proxy(
            farm.adb, serial, phone_idx, attempts=2, browser_package=browser.package
        )
        from automation.browse_proxy import remember_browser_package

        remember_browser_package(serial, browser.package)
        logger.info(
            "[%s] guest proxy for %s -> %s", name, browser.label, pinned
        )
    except Exception as exc:
        logger.warning("[%s] browser-aware proxy pin soft-fail: %s", name, exc)
    # Path3 / Chromium-family: apply chrome-command-line identity. Firefox skips.
    if browser.kind in (BrowserKind.CHROMIUM, BrowserKind.BRAVE, BrowserKind.OPERA):
        prepare_chromium(farm.adb, serial, profile=profile, force=True)

    dabflow = "getdabflow.app" in url.lower()
    # Open ad-fill window BEFORE navigation so we never kick browser mid-page.
    if dabflow and emulator_ad_mode_enabled(serial):
        try:
            pause_tor_for_ads(farm.adb, serial, phone_idx, kick_browser=False)
        except Exception as exc:
            logger.warning("Ad fill window soft-fail serial=%s: %s", serial, exc)
        # pause clears :0 then re-pins Chromium inject; pin again with the
        # *chosen* package so a stale remembered pkg cannot leave Chromium on :0.
        try:
            from automation.browse_proxy import pin_guest_proxy, remember_browser_package

            remember_browser_package(serial, browser.package)
            pinned = pin_guest_proxy(
                farm.adb,
                serial,
                phone_idx,
                attempts=3,
                browser_package=browser.package,
            )
            logger.info(
                "[%s] post-pause guest proxy for %s -> %s",
                name,
                browser.label,
                pinned,
            )
        except Exception as exc:
            logger.warning("[%s] post-pause proxy pin soft-fail: %s", name, exc)

    ok = open_url(farm.adb, serial, url, browser=browser, profile=profile)
    # If non-Chromium open failed, fall back once to Chromium (Path1/2 soft fail).
    if not ok and browser.package != BROWSER_CHROMIUM:
        fallback = select_chromium_browser(farm.adb, serial)
        if fallback is not None:
            logger.warning(
                "[%s] %s open failed — falling back to %s",
                name,
                browser.label,
                fallback.label,
            )
            _browser_choice_by_phone[name] = fallback
            if fallback.kind in (BrowserKind.CHROMIUM, BrowserKind.BRAVE, BrowserKind.OPERA):
                prepare_chromium(farm.adb, serial, profile=profile, force=True)
            try:
                from automation.browse_proxy import pin_guest_proxy, remember_browser_package

                remember_browser_package(serial, fallback.package)
                pin_guest_proxy(
                    farm.adb, serial, phone_idx, attempts=2, browser_package=fallback.package
                )
            except Exception:
                pass
            ok = open_url(farm.adb, serial, url, browser=fallback, profile=profile)
            browser = fallback
    # Publish Client Hints for MITM rewrite (Chromium inject path) even when CDP is dead.
    if profile is not None:
        try:
            from automation.mantis_inject_proxy import publish_client_hints_for_phone

            publish_client_hints_for_phone(phone_idx, profile)
        except Exception:
            pass
    # Chromium/Brave: force Client Hints to scrambled model (getprop is sticky on ARM).
    # Opera uses @com.opera.browser.devtools and is MITM-skip — do not poke
    # chrome_devtools_remote (that is the ClientHints CDP miss root cause).
    # MuMu Chromium 152 also often has no DevTools at all — MITM Sec-CH-UA-* is the fallback.
    if ok and browser is not None:
        try:
            from automation.browse_proxy import supports_cdp_paint
            from automation.dabflow_mantis_client_patch import (
                apply_cdp_user_agent_override,
                host_cdp_port,
            )

            if supports_cdp_paint(browser.package):
                # Brief settle so @chrome_devtools_remote is bound after am start/FRE.
                time.sleep(0.6)
                ua_res = apply_cdp_user_agent_override(
                    host_cdp_port(phone_idx),
                    profile,
                    adb=farm.adb,
                    serial=serial,
                    phone_idx=phone_idx,
                    browser_package=browser.package,
                )
                if ua_res.get("ok"):
                    logger.info(
                        "[%s] ClientHints model=%s via CDP",
                        name,
                        getattr(profile, "model", "?"),
                    )
                else:
                    logger.info(
                        "[%s] ClientHints CDP miss: %s (MITM Sec-CH-UA rewrite armed if inject)",
                        name,
                        ua_res.get("error"),
                    )
        except Exception as exc:
            logger.debug("[%s] CDP UA override soft-fail: %s", name, exc)
    # Ads must paint on Path1/2/3; Chromium chrome must stay collapsed.
    if ok and dabflow:
        try:
            if emulator_ad_mode_enabled(serial):
                ensure_ads_visible_browser_hidden(
                    farm.adb, serial, phone_idx, checkpoint="ad_home",
                    paint_creatives=True, interactive=False,
                )
            else:
                from automation.emulator_ad_mode import resume_tor_after_ads

                resume_tor_after_ads(farm.adb, serial, phone_idx)
        except Exception as exc:
            logger.warning("Ad fill / hide-chrome soft-fail serial=%s: %s", serial, exc)
            try:
                from automation.emulator_ad_mode import resume_tor_after_ads

                resume_tor_after_ads(farm.adb, serial, phone_idx)
            except Exception:
                pass
        # CRITICAL: Mantis CDP/SSP paint must run on SUCCESS (was wrongly only on open_url fail).
        if os.environ.get("CPHARM_SKIP_MANTIS_PATCH", "").strip().lower() not in (
            "1",
            "true",
            "yes",
            "on",
        ):
            time.sleep(0.8)
            try:
                maybe_apply_after_open_url_step(
                    farm.adb, serial, url, phone_idx,
                    paint_creatives=True, interactive=False,
                    profile=profile,
                )
            except Exception as exc:
                logger.warning("Optional post-open inject soft-fail serial=%s: %s", serial, exc)
            try:
                hide_browser_chrome(farm.adb, serial)
            except Exception:
                pass
    elif dabflow and emulator_ad_mode_enabled(serial):
        # open_url failed after pause — still put inject/Tor back.
        try:
            from automation.emulator_ad_mode import resume_tor_after_ads

            resume_tor_after_ads(farm.adb, serial, phone_idx)
        except Exception:
            pass
    return ok


# Backward-compatible aliases used by farm ops / dashboard.
def ensure_fingerprint_before_browse_impl(farm: MuMuFarmOps, name: str) -> BrowserSessionProfile:
    """Browser-only: scramble + verify headers (no MuMu setting.json)."""
    if is_browser_only_identity():
        prof = scramble_for_sequence(farm, name)
        if prof:
            return prof
    inst = farm.get_phone(name) if hasattr(farm, "get_phone") else farm.instances.get(name)
    if inst:
        from automation.browser_identity import profile_from_device

        return profile_from_device(farm.adb, inst.adb_serial)
    from automation.browser_identity import DeviceIdentity, BrowserSessionProfile

    fallback = DeviceIdentity(
        brand="android", manufacturer="unknown", model="device", android_release="13", build_id="UNKNOWN"
    )
    return BrowserSessionProfile.from_device(fallback, chrome_version="120.0.6099.144")


def verify_before_browse(farm: MuMuFarmOps, name: str) -> Any:
    """Verify browser headers are on device before open_url."""
    from automation.browser_identity import (
        BrowserHeaderReport,
        apply_browser_session,
        verify_browser_headers,
    )

    inst = farm.get_phone(name) if hasattr(farm, "get_phone") else farm.instances.get(name)
    if not inst:
        return BrowserHeaderReport(
            serial="",
            passed=False,
            profile_key="",
            expected_model="",
            chrome_flags_ok=False,
            failures=["phone not found"],
        )
    profile = _browser_profiles.get(inst.name)
    if not profile:
        idx = phone_vm_index(inst.name, int(getattr(inst, "index", 0) or 0))
        profile, report = ensure_browser_identity_before_browse(
            farm.adb, inst.adb_serial, idx, scramble=True,
        )
        _browser_profiles[inst.name] = profile
        return report
    report = verify_browser_headers(farm.adb, inst.adb_serial, profile)
    if report.passed:
        return report
    # Stale/failed chrome-command-line push left prior UA on device while
    # in-memory profile moved — rewrite once before hard-failing Path3.
    idx = phone_vm_index(inst.name, int(getattr(inst, "index", 0) or 0))
    try:
        apply_browser_session(farm.adb, inst.adb_serial, profile, phone_index=idx)
    except Exception as exc:
        logger.warning("chrome flags rewrite soft-fail %s: %s", name, exc)
        return report
    return verify_browser_headers(farm.adb, inst.adb_serial, profile)
