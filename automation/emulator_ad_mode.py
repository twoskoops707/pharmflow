"""
MuMu / emulator ad viewing — integrates with :mod:`browse_proxy`.

When browse mode is ``scramble`` / ``direct`` / ``upstream``:
  - Clears Tor ``http_proxy`` before getdabflow browse so Mantis can fill
  - ``scramble`` rotates android_id + retail browser profile each session
  - Waits longer before ad taps + SSP landing fallback when slots stay empty

Disable auto direct/scramble: ``CPHARM_EMULATOR_AD_MODE=0``
Skip fallback only: ``CPHARM_EMULATOR_AD_FALLBACK=0``
"""
from __future__ import annotations

import os
import random
import re
import subprocess
import sys
import time
from typing import Callable

from adb_paths import adb_executable

_SUBPROC_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

_MUMU_SERIAL_RE = re.compile(r"^10\.0\.2\.\d+:\d+$")
_URL_BAR_RE = re.compile(
    r'resource-id="[^"]*url_bar[^"]*"[^>]*text="([^"]*)"',
    re.IGNORECASE,
)
_paused: set[str] = set()

LogFn = Callable[[str], None]


def _env_on(name: str, *, default: bool = True) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return default


def browse_proxy_mode() -> str:
    try:
        import browse_proxy as bp

        return bp.browse_proxy_mode()
    except Exception:
        raw = os.environ.get("CPHARM_BROWSE_PROXY_MODE", "").strip().lower()
        if raw in ("tor", "direct", "scramble", "upstream"):
            return raw
        return "scramble"


def is_mumu_serial(serial: str) -> bool:
    return bool(_MUMU_SERIAL_RE.match((serial or "").strip()))


def emulator_ad_mode_enabled(serial: str | None = None) -> bool:
    """True when dabflow browse should bypass Tor."""
    if not _env_on("CPHARM_EMULATOR_AD_MODE", default=True):
        return False
    mode = browse_proxy_mode()
    if mode in ("direct", "scramble", "upstream"):
        return True
    if mode == "tor":
        return _env_on("CPHARM_EMULATOR_AD_FORCE_DIRECT", default=False) and bool(
            serial and is_mumu_serial(serial)
        )
    return False


def should_restore_tor_after_ads() -> bool:
    if browse_proxy_mode() in ("direct", "scramble", "upstream"):
        return _env_on("CPHARM_EMULATOR_AD_RESTORE_TOR", default=False)
    return True


def session_scramble_enabled() -> bool:
    mode = browse_proxy_mode()
    if mode == "scramble":
        return _env_on("CPHARM_AD_SESSION_SCRAMBLE", default=True)
    if mode == "upstream":
        return _env_on("CPHARM_AD_SESSION_SCRAMBLE", default=True)
    return _env_on("CPHARM_AD_SESSION_SCRAMBLE", default=False)


def emulator_ad_fallback_enabled() -> bool:
    return _env_on("CPHARM_EMULATOR_AD_FALLBACK", default=True)


def emulator_ad_fill_wait_sec() -> float:
    raw = os.environ.get("CPHARM_EMULATOR_AD_FILL_WAIT", "").strip()
    if raw:
        try:
            return max(0.0, min(60.0, float(raw)))
        except ValueError:
            pass
    return 15.0


def _adb(serial: str, *args: str, timeout: float = 20) -> str:
    r = subprocess.run(
        [adb_executable(), "-s", serial, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=_SUBPROC_FLAGS,
        errors="replace",
    )
    return (r.stdout or "") + (r.stderr or "")


def scramble_device_session(
    serial: str,
    phone_idx: int,
    log_fn: LogFn | None = None,
) -> dict:
    log = log_fn or (lambda _m: None)
    ser = str(serial)
    try:
        import mumu_fingerprint as mf

        pool = mf.RETAIL_PROFILE_POOL
        idx = (int(phone_idx) + int(time.time()) // 1800 + random.randint(0, max(1, len(pool) - 1))) % len(
            pool
        )
        prof = mf.profile_for_index(idx)
        fp = mf.apply_browser_fingerprint_adb(ser, prof, farm_index=phone_idx)
        log(
            f"Session scramble: {prof.get('model', prof.get('key', '?'))} "
            f"android_id rotated serial={ser}"
        )
        return {"ok": True, "profile": fp.get("profile"), "model": fp.get("model")}
    except Exception as exc:
        log(f"Session scramble failed serial={ser} — {exc}")
        return {"ok": False, "error": str(exc)}


def chromium_url_bar_text(serial: str) -> str:
    remote = "/sdcard/cpharm_url_bar.xml"
    try:
        subprocess.run(
            [adb_executable(), "-s", serial, "shell", "uiautomator", "dump", remote],
            capture_output=True,
            timeout=25,
            creationflags=_SUBPROC_FLAGS,
        )
        xml = _adb(serial, "shell", "cat", remote, timeout=12)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    m = _URL_BAR_RE.search(xml)
    if m:
        return m.group(1).strip()
    m2 = re.search(r'text="([^"]*getdabflow[^"]*)"', xml, re.I)
    return m2.group(1).strip() if m2 else ""


def still_on_dabflow(serial: str) -> bool:
    low = chromium_url_bar_text(serial).lower()
    if not low:
        return True
    return "getdabflow.app" in low


def pause_tor_for_ads(serial: str, phone_idx: int, log_fn: LogFn | None = None) -> dict:
    """Prepare browse session for getdabflow (delegates to :mod:`browse_proxy`)."""
    log = log_fn or (lambda _m: None)
    ser = str(serial)
    if not emulator_ad_mode_enabled(ser):
        return {"skipped": True, "mode": browse_proxy_mode()}
    if ser in _paused:
        return {"skipped": True, "reason": "already_paused"}

    try:
        import browse_proxy as bp

        out = bp.prepare_browse_session(ser, int(phone_idx), log_fn=log)
        _paused.add(ser)
        return out
    except Exception as exc:
        log(f"Browse session prep failed serial={ser} — {exc}")
        return {"ok": False, "error": str(exc)}


def resume_tor_after_ads(serial: str, phone_idx: int, log_fn: LogFn | None = None) -> dict:
    log = log_fn or (lambda _m: None)
    ser = str(serial)
    if ser not in _paused:
        return {"skipped": True}
    _paused.discard(ser)
    if not should_restore_tor_after_ads():
        log(f"Browse proxy: keeping {browse_proxy_mode()} (no Tor restore) serial={ser}")
        return {"skipped": True, "reason": "non_tor_mode"}
    try:
        import browse_proxy as bp

        return bp.restore_browse_session(ser, int(phone_idx), log_fn=log)
    except Exception as exc:
        log(f"Browse proxy restore failed serial={ser} — {exc}")
        return {"ok": False, "error": str(exc)}


def ad_checkpoint_to_zone(checkpoint: str) -> str | None:
    from dabflow_mantis_ad_urls import ZONE_TO_AD_CHECKPOINT

    cp = (checkpoint or "").strip().lower()
    for zone, ad_cp in ZONE_TO_AD_CHECKPOINT.items():
        if ad_cp == cp:
            return zone
    return None


def fallback_landing_for_checkpoint(checkpoint: str) -> str | None:
    zone = ad_checkpoint_to_zone(checkpoint)
    if not zone:
        return None
    from dabflow_mantis_ad_urls import FALLBACK_LANDING_URLS

    return FALLBACK_LANDING_URLS.get(zone)


def prepare_ad_tap(serial: str, checkpoint: str, log_fn: LogFn | None = None) -> None:
    if not emulator_ad_mode_enabled(serial):
        return
    wait = emulator_ad_fill_wait_sec()
    if wait > 0:
        (log_fn or (lambda _m: None))(f"Ad browse: waiting {wait:g}s for Mantis fill…")
        time.sleep(wait)


def maybe_fallback_ad_open_url(
    serial: str,
    checkpoint: str,
    *,
    open_url_fn,
    log_fn: LogFn | None = None,
) -> bool:
    log = log_fn or (lambda _m: None)
    if not emulator_ad_mode_enabled(serial) or not emulator_ad_fallback_enabled():
        return False
    time.sleep(2.0)
    if not still_on_dabflow(serial):
        log("Ad browse: tap left getdabflow — no fallback")
        return False
    url = fallback_landing_for_checkpoint(checkpoint)
    if not url:
        log(f"Ad browse: no fallback URL for checkpoint={checkpoint}")
        return False
    log(f"Ad browse: on-site ad empty — open_url fallback → {url[:72]}…")
    open_url_fn(serial, url)
    return True
