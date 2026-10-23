"""HARDCODED per-sequence isolation — not optional, not env-gated.

Before EVERY sequence (farm + EXE SequenceRunner):
  - wipe browser cookies / cache / site storage
  - new Tor exit IP (verified changed vs last + other phones — NEVER share IP with another online phone)
  - new browser identity (UA / model / android_id)
  - display resolution: permanent when PHARMFLOW_DISPLAY_LOCK=1; else at most once per
    PHARMFLOW_RES_MIN_INTERVAL_MIN (default 240) — NOT every sequence
  - make/model/IMEI/android_id/UA/geo/Tor/proxy: ALWAYS every sequence (display lock
    does NOT disable identity rotation)
  - new geo/timezone/location
  - best-effort new IMEI / MuMu fingerprint when available

Nothing that could tie this run to the previous sequence may remain
(except sticky display resolution between interval windows).
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from automation.browser_farm import (
    clear_browser_before_sequence,
    get_sequence_browser,
    scramble_for_sequence,
)
from automation.browser_onboarding import ensure_browser_ready_for_farm, pin_system_default_browser
from automation.browse_proxy import (
    browse_proxy_mode,
    guest_proxy_healthy,
    remember_browser_package,
    restore_inject_after_identity,
    skips_mitm,
)
from automation.config import BROWSER_CHROMIUM
from automation.display_resolution import maybe_rotate_display_for_isolate
from automation.farm_launch_guard import bring_browser_foreground_dabflow
from automation.mumu_fingerprint import generate_imei
from automation.mumu_shell_cli import phone_vm_index
from automation.phone_geo_time import (
    PAYING_MARKET_GEO,
    GeoLocale,
    active_geo_catalog,
    apply_geo_to_phone,
    locales_in_window,
)
from automation.tor_manager import phone_http_port

logger = logging.getLogger(__name__)

# Last geo per serial — next sequence must pick a different city when possible.
_last_geo_by_serial: dict[str, str] = {}
_last_imei_by_phone: dict[str, str] = {}
_last_serial_by_phone: dict[str, str] = {}
_GEO_STATE = Path(os.environ.get("PHARMFLOW_LOGS") or r"C:\PharmFlow\logs") / "farm_last_geo.json"


def _load_last_geo() -> None:
    try:
        data = json.loads(_GEO_STATE.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            _last_geo_by_serial.update({str(k): str(v) for k, v in data.items() if v})
    except Exception:
        pass


def _save_last_geo() -> None:
    try:
        _GEO_STATE.parent.mkdir(parents=True, exist_ok=True)
        _GEO_STATE.write_text(json.dumps(_last_geo_by_serial, indent=0) + "\n", encoding="utf-8")
    except Exception:
        logger.debug("last-geo persist soft-fail", exc_info=True)


_load_last_geo()


@dataclass
class IsolationReport:
    ok: bool
    phone: str
    serial: str = ""
    ip_before: str = ""
    ip_after: str = ""
    ip_changed: bool = False
    ip_retries: int = 0
    geo_label: str = ""
    geo_tz: str = ""
    browser_model: str = ""
    browser_brand: str = ""
    android_id: str = ""
    imei: str = ""
    device_serial: str = ""
    http_proxy: str = ""
    display_size: str = ""
    display_density: int = 0
    errors: list[str] = field(default_factory=list)

    def log_line(self) -> str:
        return (
            f"isolate phone={self.phone} ok={self.ok} "
            f"IP {self.ip_before or '?'}->{self.ip_after or '?'} changed={'yes' if self.ip_changed else 'no'} "
            f"geo={self.geo_label or '?'} brand={self.browser_brand or '?'} "
            f"model={self.browser_model or '?'} "
            f"android_id={self.android_id or '?'} imei={self.imei or '?'} "
            f"serial={self.device_serial or '?'} "
            f"wm={self.display_size or '?'}@{self.display_density or '?'} "
            f"proxy={self.http_proxy or '?'} "
            f"errs={';'.join(self.errors) if self.errors else 'none'}"
        )


def _append_isolation_jsonl(report: IsolationReport) -> None:
    """Operator-visible per-seq identity proof (IP/geo/IMEI/UA/android_id)."""
    try:
        path = Path(os.environ.get("PHARMFLOW_LOGS") or r"C:\PharmFlow\logs") / "farm_isolation.jsonl"
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "ok": report.ok,
            "phone": report.phone,
            "serial": report.serial,
            "ip_before": report.ip_before,
            "ip_after": report.ip_after,
            "ip_changed": report.ip_changed,
            "ip_retries": report.ip_retries,
            "geo": report.geo_label,
            "geo_tz": report.geo_tz,
            "brand": report.browser_brand,
            "model": report.browser_model,
            "android_id": report.android_id,
            "imei": report.imei,
            "device_serial": report.device_serial,
            "proxy": report.http_proxy,
            "wm": report.display_size,
            "errors": list(report.errors),
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=True) + "\n")
    except Exception:
        logger.debug("isolation jsonl soft-fail", exc_info=True)


def _pick_fresh_locale(serial: str, rng: random.Random | None = None) -> GeoLocale:
    r = rng or random.Random()
    eligible = locales_in_window()
    # ALWAYS include US paying markets — Mantis only counts US cannabis clicks.
    # Even at night in US, Tor exits may land on US nodes; the geo spoof
    # makes the click appear to come from a paying market.
    for loc in PAYING_MARKET_GEO:
        if loc not in eligible:
            eligible.append(loc)
    paying = [loc for loc in eligible if loc in PAYING_MARKET_GEO]
    if len(paying) >= 2:
        eligible = paying
    elif len(eligible) < 2:
        eligible = list(active_geo_catalog())
    last = _last_geo_by_serial.get(serial, "")
    others = {v for k, v in _last_geo_by_serial.items() if k != serial and v}
    pool = [loc for loc in eligible if loc.label != last]
    unique_pool = [loc for loc in pool if loc.label not in others]
    if unique_pool:
        return r.choice(unique_pool)
    if pool:
        return r.choice(pool)
    full = [loc for loc in active_geo_catalog() if loc.label != last] or list(
        active_geo_catalog()
    )
    return r.choice(full)


def _apply_fresh_geo(adb: Any, serial: str) -> GeoLocale:
    """Always apply a new place — ignores PHARMFLOW_GEO_TIME_WINDOW off switch."""
    loc = _pick_fresh_locale(serial)
    apply_geo_to_phone(adb, serial, loc)
    _last_geo_by_serial[serial] = loc.label
    _save_last_geo()
    return loc


def _force_unique_exit_ip(farm: Any, phone: str, phone_idx: int, serial: str) -> Any:
    """Always rotate until exit IP changes — env cannot disable this.

    Retry count from PHARMFLOW_UNIQUE_EXIT_IP_RETRIES (farm default 12). Floor
    scales with concurrent phones so 8-phone collision pools don't exhaust
    a hard cap of 4 (that caused ~46% isolate fails on vm30/vm31).
    """
    if hasattr(farm, "setup_tor"):
        farm.setup_tor(phone)
    try:
        max_retries = max(1, int(os.environ.get("PHARMFLOW_UNIQUE_EXIT_IP_RETRIES") or "12"))
    except (TypeError, ValueError):
        max_retries = 12
    try:
        active = len(getattr(farm, "instances", None) or {}) or 0
    except Exception:
        active = 0
    if active <= 0:
        active = 8
    # Collision pool grows with farm size — give NEWNYM more chances.
    max_retries = max(max_retries, 4 + (active // 2))
    # Call rotate_until_unique_ip directly so require_unique_exit_ip() env is irrelevant.
    ip_result = farm.tor.rotate_until_unique_ip(
        phone_idx,
        serial,
        max_retries=max_retries,
        avoid_other_phones=True,
    )
    by_phone = getattr(farm, "_last_exit_ip_rotate_by_phone", None)
    if not isinstance(by_phone, dict):
        by_phone = {}
        farm._last_exit_ip_rotate_by_phone = by_phone
    by_phone[phone] = ip_result
    farm._last_exit_ip_rotate = ip_result
    return ip_result


def _ensure_device_tor_proxy(farm: Any, phone_idx: int, serial: str) -> str:
    farm.tor.start_phone_tor(phone_idx, serial)
    proxy = (farm.adb.shell("settings get global http_proxy", serial=serial).stdout or "").strip()
    expect = f"127.0.0.1:{phone_http_port(phone_idx)}"
    if expect not in proxy:
        farm.tor.start_phone_tor(phone_idx, serial)
        time.sleep(0.5)
        proxy = (farm.adb.shell("settings get global http_proxy", serial=serial).stdout or "").strip()
    return proxy


def _read_guest_http_proxy(farm: Any, serial: str) -> str:
    try:
        out = farm.adb.shell("settings get global http_proxy", serial=serial)
    except Exception:
        return ""
    return (getattr(out, "stdout", None) or "").strip()


def _write_loopback_and_read(farm: Any, serial: str, port: int) -> str:
    """Write a loopback exit, then return what the guest actually has."""
    if port <= 0:
        return _read_guest_http_proxy(farm, serial)
    writer = getattr(farm.adb, "set_http_proxy", None)
    if callable(writer):
        writer("127.0.0.1", int(port), serial=serial)
    else:
        farm.adb.shell(
            f"settings put global http_proxy 127.0.0.1:{int(port)}",
            serial=serial,
        )
    return _read_guest_http_proxy(farm, serial)


def _pin_inject_for_isolate(
    farm: Any,
    phone: str,
    phone_idx: int,
    serial: str,
    *,
    preferred_browser: str = "",
) -> str:
    """Always restore inject (Chromium) or browser-aware pin after identity clear."""
    chosen = get_sequence_browser(phone)
    pkg = (getattr(chosen, "package", None) or preferred_browser or "").strip()
    if pkg:
        remember_browser_package(serial, pkg)
    # 2 attempts — 5× ensure_inject + sleeps stacked 3× per isolate burned minutes.
    pinned = restore_inject_after_identity(
        farm.adb, serial, phone_idx, browser_package=pkg or None, attempts=2
    )
    needs_inject = bool(pkg and not skips_mitm(pkg))
    if needs_inject and not guest_proxy_healthy(pinned, phone_idx):
        # Retry with longer backoff — inject proxy may need time to establish
        # after isolation clears the proxy.  Do NOT hard-fail: a Tor or even
        # direct sequence still generates impressions/clicks.
        for extra in range(3):
            time.sleep(1.0 + extra * 0.8)
            pinned = restore_inject_after_identity(
                farm.adb, serial, phone_idx,
                browser_package=pkg or None, attempts=2,
            )
            if guest_proxy_healthy(pinned, phone_idx):
                break
        if not guest_proxy_healthy(pinned, phone_idx):
            # Tor is the backup exit. It is not a pin until the guest read matches.
            logger.warning(
                "inject restore failed serial=%s phone=%d proxy=%r — "
                "trying Tor",
                serial, phone_idx, pinned,
            )
            tor_port = int(phone_http_port(phone_idx) or 0)
            if tor_port <= 0:
                logger.warning(
                    "inject restore failed serial=%s phone=%d — "
                    "not writing http_proxy :0",
                    serial,
                    phone_idx,
                )
                pinned = _read_guest_http_proxy(farm, serial)
            else:
                pinned = _write_loopback_and_read(farm, serial, tor_port)
                if not guest_proxy_healthy(pinned, phone_idx):
                    logger.warning(
                        "tor fallback did not land serial=%s phone=%d proxy=%r",
                        serial,
                        phone_idx,
                        pinned,
                    )
    live = (pinned or "").strip() or _read_guest_http_proxy(farm, serial)
    if guest_proxy_healthy(live, phone_idx):
        return live
    if pkg and skips_mitm(pkg):
        mode = browse_proxy_mode()
        cleared = (
            not live
            or live.lower() in ("null", "none", "undefined")
            or live.endswith(":0")
        )
        # Scramble/direct/upstream are phone-exit modes. A cleared guest
        # proxy is that mode. A host address is not, and :0 is not invented.
        if mode in ("scramble", "direct", "upstream") and cleared:
            return live
    raise RuntimeError(f"http_proxy is not a loopback exit ({live!r})")


def _best_effort_imei(
    farm: Any,
    phone: str,
    *,
    android_id: str = "",
    model: str = "",
    brand: str = "",
    user_agent: str = "",
) -> tuple[str, str]:
    """New IMEI + serial every sequence — always patch MuMu setting.json when vms_dir exists.

    Align PhoneProp/IMEI/serial with the browser scramble model when provided. Live
    getprop on MuMu ARM stays sticky until cold boot (ro.* is immutable at runtime);
    the web-visible identity is chrome-command-line + CDP Client Hints / Firefox prefs.
    Returns (imei, device_serial).
    """
    last = _last_imei_by_phone.get(phone, "")
    last_serial = _last_serial_by_phone.get(phone, "")
    imei = generate_imei()
    for _ in range(6):
        if imei != last:
            break
        imei = generate_imei()
    device_serial = ""
    try:
        from automation.mumu_fingerprint import (
            apply_fingerprint,
            generate_serial,
            profile_matching_model,
            random_profile,
        )

        vms_dir = getattr(farm, "vms_dir", None)
        if vms_dir:
            if model:
                prof = profile_matching_model(
                    model,
                    brand=brand,
                    android_id=android_id,
                    imei=imei,
                    user_agent=user_agent,
                )
            else:
                prof = random_profile()
            # Keep generated IMEI if random_profile somehow collides with last.
            if getattr(prof, "imei", "") == last:
                prof.imei = imei
            else:
                imei = getattr(prof, "imei", None) or imei
            device_serial = generate_serial()
            for _ in range(6):
                if device_serial != last_serial:
                    break
                device_serial = generate_serial()
            prof.serial_number = device_serial
            if android_id:
                prof.android_id = android_id
            # Patch setting.json only — no cold boot mid-sequence (ARM getprop
            # needs a full VM restart to pick up PhoneProp; see cold_boot docs).
            apply_fingerprint(farm.vms_dir, phone, prof, shell_fn=None)
            farm._profiles = getattr(farm, "_profiles", {})
            if isinstance(farm._profiles, dict):
                farm._profiles[phone] = prof
            device_serial = getattr(prof, "serial_number", "") or device_serial
            logger.info(
                "[%s] MuMu IMEI/fingerprint patched brand=%s model=%s imei=%s serial=%s "
                "(PhoneProp applies on next cold boot; web uses browser UA/CH)",
                phone,
                getattr(prof, "brand", "?"),
                getattr(prof, "model", "?"),
                imei,
                device_serial,
            )
    except Exception as exc:
        logger.warning("[%s] MuMu IMEI patch soft-fail: %s", phone, exc)
    _last_imei_by_phone[phone] = imei
    if device_serial:
        _last_serial_by_phone[phone] = device_serial
    stash = getattr(farm, "_last_imei_by_phone", None)
    if not isinstance(stash, dict):
        stash = {}
        farm._last_imei_by_phone = stash
    stash[phone] = imei
    return imei, device_serial


def isolation_skip_allowed() -> bool:
    """Live farm / EXE-owned stack never skips isolation.

    Demo/verify scripts may set PHARMFLOW_SKIP_SEQUENCE_ISOLATION only when they
    are NOT live farm (ALLOW_SEQUENCE_RUNS off) and not EXE/unison owned.
    """
    if os.environ.get("PHARMFLOW_EXE_OWNED_FARM", "").strip() in ("1", "true", "yes"):
        return False
    if os.environ.get("PHARMFLOW_UNISON_MODE", "").strip() in ("1", "true", "yes"):
        return False
    skip = os.environ.get("PHARMFLOW_SKIP_SEQUENCE_ISOLATION", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if not skip:
        return False
    live = os.environ.get("PHARMFLOW_ALLOW_SEQUENCE_RUNS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    return not live


def isolate_before_sequence(
    farm: Any,
    phone: str,
    *,
    force_chromium: bool = False,
    preferred_browser: str = "",
) -> IsolationReport:
    """HARDCODED full isolation. Raises RuntimeError if IP did not change."""
    inst = farm.get_phone(phone) if hasattr(farm, "get_phone") else farm.instances.get(phone)
    if not inst or not getattr(inst, "adb_serial", None):
        farm.refresh_serials()
        inst = farm.get_phone(phone) if hasattr(farm, "get_phone") else farm.instances.get(phone)
    if not inst or not getattr(inst, "adb_serial", None):
        raise RuntimeError(f"isolation: no device for {phone}")

    phone = getattr(inst, "name", phone)
    serial = inst.adb_serial
    try:
        serial_live = bool(serial) and farm.adb.wait_for_device(str(serial), timeout=1.5)
    except Exception:
        serial_live = False
    if not serial_live:
        farm.refresh_serials()
        inst = farm.get_phone(phone) if hasattr(farm, "get_phone") else farm.instances.get(phone)
        if not inst or not getattr(inst, "adb_serial", None):
            raise RuntimeError(f"isolation: no device for {phone}")
        phone = getattr(inst, "name", phone)
        serial = inst.adb_serial
    # Prefer vmN from name — MuMu prefs/slot order must not drive inject 8218+N.
    phone_idx = phone_vm_index(phone, int(getattr(inst, "index", 0) or 0))
    if int(getattr(inst, "index", 0) or 0) != phone_idx:
        try:
            inst.index = phone_idx
        except Exception:
            pass
    report = IsolationReport(ok=False, phone=phone, serial=serial)

    ready = getattr(farm, "_exit_ip_ready_phones", None)
    if not isinstance(ready, dict):
        ready = {}
        farm._exit_ip_ready_phones = ready
    ready[phone] = False

    # 0) Keep MuMu/stock system browser from stealing focus (stale UI).
    try:
        farm.adb.shell("am force-stop com.android.browser", serial=serial)
        farm.adb.shell(
            "pm disable-user --user 0 com.android.browser", serial=serial
        )
    except Exception as exc:
        logger.debug("[%s] system browser disable soft-fail: %s", phone, exc)

    # 0a) Pin Chromium as ROLE_BROWSER before wipe/launch so https never hits
    # ResolverActivity and Firefox/Brave stop fighting "become default".
    try:
        pin_system_default_browser(farm.adb, serial, BROWSER_CHROMIUM)
    except Exception as exc:
        logger.warning("[%s] ROLE_BROWSER pin soft-fail: %s", phone, exc)

    # 0b) Spotify (preinstalled on some MuMu images) steals FG when an SSP/ad
    # creative deep-links spotify:// or open.spotify.com — then crash-loops
    # ("Application Error: com.spotify.music") while Chromium should own the screen.
    # Farm never launches Spotify; disable so VIEW intents cannot reopen it.
    try:
        farm.adb.shell("am force-stop com.spotify.music", serial=serial)
        farm.adb.shell(
            "pm disable-user --user 0 com.spotify.music", serial=serial
        )
        farm.adb.shell(
            "cmd package suspend com.spotify.music", serial=serial
        )
    except Exception as exc:
        logger.debug("[%s] Spotify disable soft-fail: %s", phone, exc)

    # 1) Wipe chosen browser site data / cookies / cache (Path3 => Chromium)
    try:
        if not clear_browser_before_sequence(
            farm,
            phone,
            force_chromium=force_chromium,
            preferred_package=preferred_browser,
        ):
            report.errors.append("browser clear incomplete")
            raise RuntimeError("isolation browser clear incomplete")
    except Exception as exc:
        if "browser clear incomplete" in str(exc):
            raise
        report.errors.append(f"browser clear: {exc}")
        raise RuntimeError(report.errors[-1]) from exc

    # 1b) Chromium Path3: seed FRE prefs only — uiautomator dump storms after wipe
    # were 4–12s × N phones and froze ADB for the whole farm.
    # Firefox/Brave/Opera still need the dump walker.
    try:
        from automation.browser_adb import _dump_ui, prepare_chromium

        browser = get_sequence_browser(phone)
        pkg = (preferred_browser or getattr(browser, "package", None) or "").strip()
        if pkg:
            pkg_l = pkg.lower()
            is_chromium = (
                "chromium" in pkg_l
                or pkg_l.endswith(".chrome")
                or "chrome" in pkg_l
            ) and "brave" not in pkg_l
            if is_chromium:
                prepare_chromium(farm.adb, serial, force=True)
            else:
                ensure_browser_ready_for_farm(
                    farm.adb, serial, pkg, dump_ui=_dump_ui
                )
    except Exception as exc:
        report.errors.append(f"browser ready: {exc}")
        logger.warning("[%s] browser ready after wipe soft-fail: %s", phone, exc)

    # 2) New geo / timezone / mock location (always)
    try:
        loc = _apply_fresh_geo(farm.adb, serial)
        report.geo_label = loc.label
        report.geo_tz = loc.tz
    except Exception as exc:
        report.errors.append(f"geo: {exc}")
        logger.warning("[%s] geo isolation soft-fail: %s", phone, exc)

    # 3) New browser identity (UA / android_id / model scramble) — IP handled below
    try:
        ready[phone] = False
        before_aid = ""
        try:
            from automation.browser_identity import read_secure_android_id

            before_aid = read_secure_android_id(farm.adb, serial)
        except Exception:
            before_aid = ""
        profile = scramble_for_sequence(farm, phone, rotate_ip=False)
        if profile is None:
            raise RuntimeError("browser scramble returned None")
        report.browser_model = getattr(profile, "model", "") or ""
        report.browser_brand = getattr(profile, "brand", "") or ""
        report.android_id = getattr(profile, "android_id", "") or ""
        if before_aid and report.android_id and report.android_id == before_aid:
            raise RuntimeError(
                f"android_id did not change ({before_aid[:8]}…)"
            )
    except Exception as exc:
        report.errors.append(f"scramble: {exc}")
        raise RuntimeError(f"isolation browser scramble failed: {exc}") from exc

    # 3a) Immediately re-pin inject after scramble's :0 clear — do not leave
    # Chromium on null/:0 through long display/Tor NEWNYM (stagnant Lawnchair look).
    try:
        report.http_proxy = _pin_inject_for_isolate(
            farm,
            phone,
            phone_idx,
            serial,
            preferred_browser=preferred_browser,
        )
    except Exception as exc:
        report.errors.append(f"proxy early restore: {exc}")
        logger.warning("[%s] early inject restore soft-fail: %s", phone, exc)

    # 3b) Display resolution — permanent lock (PHARMFLOW_DISPLAY_LOCK) or interval throttle.
    # Per-seq force_new scramble is intentionally off; gate in
    # maybe_rotate_display_for_isolate / DISPLAY_LOCK / RES_MIN_INTERVAL.
    try:
        disp = maybe_rotate_display_for_isolate(farm.adb, serial, phone=phone)
        if disp is None:
            report.errors.append("display claim incomplete")
            logger.warning("[%s] display isolate soft-fail", phone)
        else:
            report.display_size = disp.size
            report.display_density = int(disp.density)
    except Exception as exc:
        report.errors.append(f"display: {exc}")
        logger.warning("[%s] display isolation soft-fail: %s", phone, exc)

    # 4) Unique Tor exit IP — always attempt (env cannot disable), but do NOT
    # abort the sequence when the exit pool collides or NEWNYM sticks. Hard-fail
    # here starved open_url/MITM (mantis connect=0) while phones burned minutes
    # on retries. Soft-warn + continue so ads still fire; cookie/IMEI stay hard.
    try:
        ip_result = _force_unique_exit_ip(farm, phone, phone_idx, serial)
        report.ip_before = getattr(ip_result, "before", "") or ""
        report.ip_after = getattr(ip_result, "after", "") or ""
        report.ip_changed = bool(getattr(ip_result, "changed", False))
        report.ip_retries = int(getattr(ip_result, "retries", 0) or 0)
        if not report.ip_changed or not report.ip_after:
            detail = (
                ip_result.log_line()
                if hasattr(ip_result, "log_line")
                else "IP unchanged"
            )
            report.errors.append(f"IP soft: {detail}")
            logger.warning("[%s] unique-exit soft-fail (continuing): %s", phone, detail)
    except Exception as exc:
        report.errors.append(f"IP soft: {exc}")
        logger.warning("[%s] unique-exit soft-fail (continuing): %s", phone, exc)

    # 5) Tor process up for unique exit; guest proxy is browser-aware (see
    # TorManager._setup_reverse — no MITM inject on Firefox/DDG).
    try:
        report.http_proxy = _ensure_device_tor_proxy(farm, phone_idx, serial)
    except Exception as exc:
        report.errors.append(f"proxy: {exc}")
        ready[phone] = False
        raise RuntimeError(f"isolation Tor proxy failed: {exc}") from exc

    # 5b) Final pin — Chromium must be on inject; never leave :0/null after isolate.
    try:
        report.http_proxy = _pin_inject_for_isolate(
            farm,
            phone,
            phone_idx,
            serial,
            preferred_browser=preferred_browser,
        )
    except Exception as exc:
        report.errors.append(f"proxy pin: {exc}")
        ready[phone] = False
        raise RuntimeError(f"isolation guest proxy pin failed: {exc}") from exc

    # 6) New IMEI + serial — required every sequence (operator standing rule)
    try:
        report.imei, report.device_serial = _best_effort_imei(
            farm,
            phone,
            android_id=report.android_id,
            model=report.browser_model,
            brand=report.browser_brand or getattr(profile, "brand", "") or "",
            user_agent=getattr(profile, "user_agent", "") or "",
        )
        if not (report.imei or "").strip():
            raise RuntimeError("IMEI empty after apply_fingerprint")
    except Exception as exc:
        report.errors.append(f"imei: {exc}")
        raise RuntimeError(f"isolation IMEI failed: {exc}") from exc

    # 7) Bring sequence browser to dabflow FG — do not leave Lawnchair after isolate OK.
    try:
        chosen = get_sequence_browser(phone)
        pkg = (
            getattr(chosen, "package", None) or preferred_browser or ""
        ).strip()
        if pkg:
            bring_browser_foreground_dabflow(farm.adb, serial, pkg)
            # Skip third full inject restore if early/final pin already healthy.
            if not guest_proxy_healthy(report.http_proxy or "", phone_idx):
                report.http_proxy = _pin_inject_for_isolate(
                    farm,
                    phone,
                    phone_idx,
                    serial,
                    preferred_browser=preferred_browser,
                )
    except Exception as exc:
        report.errors.append(f"fg dabflow: {exc}")
        logger.warning("[%s] post-isolate FG soft-fail: %s", phone, exc)

    ready[phone] = True
    # Unique exit is required. Cookie/IMEI still raise. A reused Tor exit must
    # not be logged as isolated; do not raise here — that starved open_url
    # while NEWNYM was stuck. The NEWNYM cookie auth is the rotation fix.
    report.ok = bool(report.ip_changed and report.ip_after)
    logger.info("[%s] %s", phone, report.log_line())
    logging.getLogger("farm_354").info("[%s] %s", phone, report.log_line())
    _append_isolation_jsonl(report)
    farm._last_isolation_by_phone = getattr(farm, "_last_isolation_by_phone", {})
    if isinstance(farm._last_isolation_by_phone, dict):
        farm._last_isolation_by_phone[phone] = report
    return report
