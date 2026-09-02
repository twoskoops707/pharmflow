"""Emulator ad browse — scramble mode + Mantis CDP patch + SSP fallback (prior EXE protocol)."""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Callable

from automation.browse_proxy import browse_proxy_mode
from automation.browser_adb import defocus_chromium_omnibox
from automation.browser_identity import scramble_browser_session
from automation.config import BROWSER_CHROMIUM
from automation.dabflow_mantis_ad_urls import (
    ad_checkpoint_to_zone,
    fallback_landing_for_checkpoint,
    resolve_hardcode_ad_urls,
)
from automation.farm_launch_guard import (
    bring_browser_foreground_dabflow,
    should_skip_content_tap,
)

LogFn = Callable[[str], None]
logger = logging.getLogger(__name__)

_MUMU_SERIAL_RE = re.compile(r"^10\.0\.2\.\d+:\d+$")
_URL_BAR_RE = re.compile(
    r'resource-id="[^"]*url_bar[^"]*"[^>]*text="([^"]*)"',
    re.IGNORECASE,
)
_paused: set[str] = set()


def _env_on(name: str, *, default: bool = True) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return default


def emulator_ad_mode_enabled(serial: str | None = None) -> bool:
    if not _env_on("CPHARM_EMULATOR_AD_MODE", default=True):
        return False
    mode = browse_proxy_mode()
    if mode in ("direct", "scramble", "upstream"):
        return True
    if mode == "tor":
        return _env_on("CPHARM_EMULATOR_AD_FORCE_DIRECT", default=False) and bool(
            serial and _MUMU_SERIAL_RE.match(serial)
        )
    return False


def emulator_ad_fallback_enabled() -> bool:
    return _env_on("CPHARM_EMULATOR_AD_FALLBACK", default=True)


def session_scramble_enabled() -> bool:
    mode = browse_proxy_mode()
    if mode in ("scramble", "upstream"):
        return _env_on("CPHARM_AD_SESSION_SCRAMBLE", default=True)
    return _env_on("CPHARM_AD_SESSION_SCRAMBLE", default=False)


def emulator_ad_fill_wait_sec() -> float:
    raw = os.environ.get("CPHARM_EMULATOR_AD_FILL_WAIT", "").strip()
    if raw:
        try:
            return max(0.0, min(60.0, float(raw)))
        except ValueError:
            pass
    # Keep short — sequences already include an explicit Mantis fill wait.
    return 2.0


def ad_checkpoint_from_description(description: str) -> str:
    desc = (description or "").lower()
    if "home" in desc and "ad" in desc:
        return "ad_home"
    if "post-timer" in desc:
        return "ad_timer_banner"
    if "stats" in desc and "ad" in desc:
        return "ad_stats"
    if "glass" in desc and "ad" in desc:
        return "ad_glass"
    if "settings" in desc and "ad" in desc:
        return "ad_settings"
    if "timer" in desc and "ad" in desc:
        return "ad_timer_banner"
    return "ad_timer_banner"


def chromium_url_bar_text(adb: object, serial: str) -> str:
    remote = "/sdcard/cpharm_url_bar.xml"
    try:
        adb.shell("uiautomator dump /sdcard/cpharm_url_bar.xml", serial=serial)  # type: ignore[union-attr]
        result = adb.shell(f"cat {remote}", serial=serial)  # type: ignore[union-attr]
        xml = result.stdout or ""
    except (OSError, AttributeError):
        return ""
    match = _URL_BAR_RE.search(xml)
    if match:
        return match.group(1).strip()
    match2 = re.search(r'text="([^"]*getdabflow[^"]*)"', xml, re.I)
    return match2.group(1).strip() if match2 else ""


def still_on_dabflow(adb: object, serial: str) -> bool:
    low = chromium_url_bar_text(adb, serial).lower()
    if not low:
        return True
    return "getdabflow.app" in low


def scramble_device_session(
    adb: object,
    serial: str,
    phone_idx: int,
    log_fn: LogFn | None = None,
) -> dict:
    log = log_fn or (lambda _m: None)
    ser = str(serial)
    if not session_scramble_enabled():
        return {"skipped": True, "reason": "scramble_disabled"}

    try:
        profile, applied = scramble_browser_session(adb, ser, int(phone_idx))  # type: ignore[arg-type]
        log(
            f"Session scramble: {profile.brand} {profile.model} "
            f"android_id rotated serial={ser}"
        )
        return {
            "ok": bool(applied.get("user_agent_written")),
            "profile": profile.key,
            "model": profile.model,
        }
    except Exception as exc:
        log(f"Session scramble failed serial={ser} — {exc}")
        return {"ok": False, "error": str(exc)}


def pause_tor_for_ads(
    adb: object,
    serial: str,
    phone_idx: int,
    log_fn: LogFn | None = None,
    *,
    kick_browser: bool = False,
) -> dict:
    if not emulator_ad_mode_enabled(serial):
        return {"skipped": True, "mode": browse_proxy_mode()}
    ser = str(serial)
    if ser in _paused:
        return {"skipped": True, "reason": "already_paused"}

    from automation.browse_proxy import prepare_browse_session

    # Under Tor + unique-exit, FORCE_DIRECT must actually clear the device proxy
    # or Mantis creatives never paint (and Path3 taps empty slots).
    # Default kick_browser=False so an already-open DabFlow tab is not killed.
    force = _env_on("CPHARM_EMULATOR_AD_FORCE_DIRECT", default=False)
    mode = browse_proxy_mode()
    # Scramble/direct already cleared at sequence start — only force Tor clear here.
    force_clear = force or mode == "tor"
    out = prepare_browse_session(
        adb,
        ser,
        int(phone_idx),
        log_fn=log_fn,
        force_clear_tor=force_clear,
        kick_browser=kick_browser,
    )
    if out.get("skipped") and not out.get("ok"):
        return out
    _paused.add(ser)
    return out


def resume_tor_after_ads(
    adb: object,
    serial: str,
    phone_idx: int,
    log_fn: LogFn | None = None,
) -> dict:
    log = log_fn or (lambda _m: None)
    ser = str(serial)
    was_paused = ser in _paused
    _paused.discard(ser)
    from automation.config import require_unique_exit_ip

    if browse_proxy_mode() in ("direct", "scramble", "upstream") and not require_unique_exit_ip():
        if not _env_on("CPHARM_EMULATOR_AD_RESTORE_TOR", default=False):
            log(f"Browse proxy: keeping {browse_proxy_mode()} (no Tor restore) serial={ser}")
            return {"skipped": True, "reason": "non_tor_mode"}
    # If pause-tracking desynced but proxy is still cleared, force restore anyway.
    from automation.browse_proxy import guest_proxy_healthy, pin_guest_proxy, restore_browse_session

    try:
        cur = (adb.shell("settings get global http_proxy", serial=ser).stdout or "").strip()  # type: ignore[union-attr]
    except Exception:
        cur = ""
    # Always restore after an ad-fill pause. Only skip when we never paused AND proxy is healthy.
    if not was_paused and guest_proxy_healthy(cur, int(phone_idx)):
        return {"skipped": True, "reason": "proxy_already_up", "http_proxy": cur}

    out = restore_browse_session(adb, ser, int(phone_idx), log_fn=log)
    # Absolute last line of defense: pin inject even if Tor start reported ok with :0.
    try:
        pinned = pin_guest_proxy(adb, ser, int(phone_idx), attempts=3)
        out = dict(out or {})
        out["http_proxy"] = pinned
        out["pinned"] = True
        if guest_proxy_healthy(pinned, int(phone_idx)):
            out["ok"] = True
    except Exception as exc:
        out = dict(out or {})
        out["pin_error"] = str(exc)
    return out


def prepare_ad_tap(serial: str, checkpoint: str = "", log_fn: LogFn | None = None) -> None:
    if not emulator_ad_mode_enabled(serial):
        return
    wait = emulator_ad_fill_wait_sec()
    if wait > 0:
        label = checkpoint or "slot"
        (log_fn or (lambda _m: None))(f"Ad browse: waiting {wait:g}s for Mantis fill ({label})…")
        time.sleep(wait)


def resolve_ad_fallback_url(checkpoint: str, *, prefer_live: bool = True) -> str | None:
    """Live Mantis SSP URL when available, else cached fallback (prior EXE protocol)."""
    zone = ad_checkpoint_to_zone(checkpoint)
    if zone and prefer_live:
        urls = resolve_hardcode_ad_urls([zone], prefer_live=True)
        if zone in urls:
            return urls[zone]
    return fallback_landing_for_checkpoint(checkpoint)


def maybe_fallback_ad_open_url(
    adb: object,
    serial: str,
    checkpoint: str,
    *,
    open_url_fn: Callable[[str, str], bool],
    log_fn: LogFn | None = None,
    force_click_url: bool = False,
    prefer_click_url: str = "",
) -> bool:
    log = log_fn or (lambda _m: None)
    # Path3 billing: painted slot taps do not increment Mantis clicks.
    # Always open the paying click_url even when house-fallback is off.
    if force_click_url:
        url = (prefer_click_url or "").strip()
        if not url.startswith("http"):
            url = (resolve_ad_fallback_url(checkpoint) or "").strip()
        if not url.startswith("http"):
            log(f"Ad browse: force click_url missing checkpoint={checkpoint}")
            return False
        log(f"Ad browse: open paying click_url → {url[:72]}…")
        return bool(open_url_fn(serial, url))
    if not emulator_ad_mode_enabled(serial) or not emulator_ad_fallback_enabled():
        return False
    time.sleep(2.0)
    if not still_on_dabflow(adb, serial):
        log("Ad browse: tap left getdabflow — no fallback needed")
        return False
    url = resolve_ad_fallback_url(checkpoint)
    if not url:
        log(f"Ad browse: no fallback URL for checkpoint={checkpoint}")
        return False
    log(f"Ad browse: on-site ad empty — open_url fallback → {url[:72]}…")
    return open_url_fn(serial, url)


def hide_browser_chrome(adb: object, serial: str, log_fn: LogFn | None = None) -> dict:
    """Keep DabFlow content fullscreen — hide Chromium chrome / system bars.

    Operator rule: ads must be visible on-page; browser chrome must not cover them.
    """
    log = log_fn or (lambda _m: None)
    ser = str(serial)
    out: dict = {"serial": ser}
    try:
        # Immersive sticky for Chromium — collapses status/nav while browsing DabFlow.
        adb.shell(  # type: ignore[union-attr]
            f"settings put global policy_control immersive.full={BROWSER_CHROMIUM}",
            serial=ser,
        )
        out["immersive"] = True
    except Exception as exc:
        out["immersive_error"] = str(exc)
    skip_fg = should_skip_content_tap(adb, ser)
    if skip_fg:
        # Lawnchair steals FG mid-Path3; recover Chromium before giving up.
        was_fg = skip_fg
        try:
            bring_browser_foreground_dabflow(adb, ser, BROWSER_CHROMIUM)
            time.sleep(0.4)
            skip_fg = should_skip_content_tap(adb, ser)
            if not skip_fg:
                logger.info(
                    "hide_browser_chrome recovered FG serial=%s was=%s",
                    ser,
                    was_fg,
                )
        except Exception as exc:
            logger.warning("hide_browser_chrome FG recover soft-fail serial=%s: %s", ser, exc)
    if skip_fg:
        out["skipped_foreign_fg"] = skip_fg
        log(f"Browser chrome hide skipped — foreign FG {skip_fg}")
        logger.warning("hide_browser_chrome skip taps serial=%s fg=%s", ser, skip_fg)
        return out
    try:
        out["omnibox_defocus"] = bool(defocus_chromium_omnibox(adb, ser))  # type: ignore[arg-type]
    except Exception as exc:
        out["omnibox_error"] = str(exc)
    try:
        # Tap mid-content to collapse expanded URL bar / tab strip if still up.
        adb.tap(450, 720, serial=ser)  # type: ignore[union-attr]
        time.sleep(0.15)
        out["content_tap"] = True
    except Exception as exc:
        out["content_tap_error"] = str(exc)
    log(f"Browser chrome hidden serial={ser} immersive={out.get('immersive')} omnibox={out.get('omnibox_defocus')}")
    logger.info(
        "Browser chrome hidden serial=%s immersive=%s omnibox=%s",
        ser,
        out.get("immersive"),
        out.get("omnibox_defocus"),
    )
    return out


def ensure_ads_visible_browser_hidden(
    adb: object,
    serial: str,
    phone_idx: int,
    *,
    checkpoint: str = "ad_home",
    log_fn: LogFn | None = None,
    paint_creatives: bool = False,
    interactive: bool | None = None,
    resume_tor: bool = True,
) -> dict:
    """Brief direct ad-fill window + Mantis paint + wait + hide chrome, then restore Tor.

    Under unique-exit farm mode, leaving http_proxy=:0 for the whole sequence made
    every phone browse the same direct IP. Restore Tor immediately after fill wait.
    """
    log = log_fn or (lambda _m: None)
    out: dict = {"serial": str(serial)}
    try:
        out["pause"] = pause_tor_for_ads(
            adb, serial, phone_idx, log_fn=log, kick_browser=False
        )
    except Exception as exc:
        out["pause_error"] = str(exc)
        log(f"Ad fill pause soft-fail serial={serial}: {exc}")
    # Paint Mantis creatives WHILE direct (SSP + static.mantis often blocked via Tor).
    if os.environ.get("CPHARM_SKIP_MANTIS_PATCH", "").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        try:
            from automation.dabflow_mantis_client_patch import maybe_apply_after_open_url_step

            out["mantis_patch"] = maybe_apply_after_open_url_step(
                adb,  # type: ignore[arg-type]
                str(serial),
                "https://getdabflow.app/",
                int(phone_idx),
                paint_creatives=paint_creatives,
                interactive=interactive,
            )
        except Exception as exc:
            out["mantis_patch_error"] = str(exc)
            log(f"Ad fill Mantis paint soft-fail serial={serial}: {exc}")
    try:
        prepare_ad_tap(serial, checkpoint, log_fn=log)
        out["fill_wait"] = emulator_ad_fill_wait_sec()
    except Exception as exc:
        out["fill_error"] = str(exc)
    if resume_tor:
        # CRITICAL: put Tor/inject back on the device before the rest of the sequence browses.
        try:
            out["resume"] = resume_tor_after_ads(adb, serial, phone_idx, log_fn=log)
        except Exception as exc:
            out["resume_error"] = str(exc)
            log(f"Ad fill Tor restore soft-fail serial={serial}: {exc}")
        # Belt + suspenders: if still :0/null, force start_phone_tor + idempotent pin.
        try:
            from automation.browse_proxy import guest_proxy_healthy, pin_guest_proxy
            from automation.tor_manager import TorManager

            proxy = (adb.shell("settings get global http_proxy", serial=str(serial)).stdout or "").strip()  # type: ignore[union-attr]
            if not guest_proxy_healthy(proxy, int(phone_idx)):
                TorManager(adb).start_phone_tor(int(phone_idx), str(serial))  # type: ignore[arg-type]
                proxy2 = pin_guest_proxy(adb, str(serial), int(phone_idx), attempts=3)
                out["force_restore"] = proxy2
                log(f"Ad fill force proxy restore serial={serial} -> {proxy2}")
        except Exception as exc:
            out["force_restore_error"] = str(exc)
            log(f"Ad fill force proxy restore failed serial={serial}: {exc}")
    else:
        out["resume"] = {"skipped": True, "reason": "resume_tor=False"}
    out["hide"] = hide_browser_chrome(adb, serial, log_fn=log)
    return out
