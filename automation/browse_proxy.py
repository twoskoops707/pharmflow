"""Browse proxy modes — scramble (default) clears Tor so Mantis ads can fill."""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

LogFn = Callable[[str], None]
_VALID_MODES = frozenset({"tor", "scramble", "direct", "upstream"})
# Android settings get returns these when proxy is cleared / unset.
_CLEARED_PROXY_VALUES = frozenset({"", ":0", "null", "none", "undefined"})


def _prefs_path() -> Path:
    from wizard.wizard_paths import desktop_prefs_file

    return desktop_prefs_file()


def load_browse_prefs() -> dict:
    try:
        p = _prefs_path()
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {}


def save_browse_prefs(**updates: object) -> dict:
    data = load_browse_prefs()
    data.update(updates)
    p = _prefs_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def browse_proxy_mode() -> str:
    raw = os.environ.get("CPHARM_BROWSE_PROXY_MODE", "").strip().lower()
    if raw in _VALID_MODES:
        return raw
    pref = str(load_browse_prefs().get("browse_proxy_mode") or "").strip().lower()
    if pref in _VALID_MODES:
        return pref
    return "scramble"


def browse_proxy_mode_label(mode: str | None = None) -> str:
    m = (mode or browse_proxy_mode()).strip().lower()
    return {
        "tor": "Tor (privacy — ads may not fill on MuMu)",
        "scramble": "Scramble (recommended — direct + new device each visit)",
        "direct": "Direct (home IP, same device look)",
        "upstream": "Upstream (per-phone residential proxy)",
    }.get(m, m)


def upstream_proxy_url_for_phone(phone_idx: int) -> str | None:
    """Return per-phone upstream URL from ``phone_upstream_proxies`` prefs, if any."""
    prefs = load_browse_prefs()
    lst = prefs.get("phone_upstream_proxies")
    if not isinstance(lst, list):
        return None
    if phone_idx < 0 or phone_idx >= len(lst):
        return None
    raw = str(lst[phone_idx] or "").strip()
    return raw or None


def _parse_upstream_url(url: str) -> tuple[str, int, str | None]:
    """Parse ``http://user:pass@host:port`` into host, port, optional Basic auth."""
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https", ""):
        raise ValueError(f"unsupported upstream scheme: {u.scheme}")
    host = u.hostname or ""
    port = u.port or (443 if u.scheme == "https" else 80)
    if not host:
        raise ValueError("upstream proxy missing host")
    auth = None
    if u.username:
        user = u.username
        pwd = u.password or ""
        token = base64.b64encode(f"{user}:{pwd}".encode()).decode("ascii")
        auth = f"Basic {token}"
    return host, int(port), auth


def sync_browse_proxy_env_from_prefs() -> str:
    if os.environ.get("CPHARM_BROWSE_PROXY_MODE", "").strip():
        return browse_proxy_mode()
    mode = browse_proxy_mode()
    os.environ["CPHARM_BROWSE_PROXY_MODE"] = mode
    return mode


def dabflow_browse_active() -> bool:
    """True when getdabflow browse should bypass Tor (scramble/direct/upstream)."""
    return browse_proxy_mode() in ("scramble", "direct", "upstream")


def prepare_browse_session(
    adb: object,
    serial: str,
    phone_idx: int,
    log_fn: LogFn | None = None,
    *,
    force_clear_tor: bool = False,
    kick_browser: bool = True,
) -> dict:
    """Pin the guest to its inject port. Never clear http_proxy.

    Scramble prefs used to delete the proxy so the page loaded on the host
    route. That drops inject, so creatives never paint and clicks pay $0.
    force_clear_tor and kick_browser are ignored — both wiped the ad page.
    """
    log = log_fn or (lambda _m: None)
    mode = browse_proxy_mode()
    ser = str(serial)
    idx = int(phone_idx)
    out: dict = {"mode": mode, "force_clear_tor": False, "kick_browser": False}
    _ = (force_clear_tor, kick_browser)
    pinned = pin_guest_proxy(adb, ser, idx)
    out["http_proxy"] = pinned
    out["pinned"] = True
    if not guest_proxy_healthy(pinned, idx):
        out["ok"] = False
        log(f"Browse proxy: pin failed serial={ser} proxy={pinned!r}")
        return out
    log(f"Browse proxy: pinned inject {pinned} (mode={mode}, not host) serial={ser}")
    if mode == "scramble":
        try:
            from automation import emulator_ad_mode as eam

            out["scramble"] = eam.scramble_device_session(adb, ser, idx, log_fn=log)  # type: ignore[arg-type]
        except Exception as exc:
            log(f"Browse proxy: scramble failed serial={ser} — {exc}")
            out["scramble_error"] = str(exc)
    out["ok"] = True
    return out


def _host_port_listens(port: int, host: str = "127.0.0.1", timeout: float = 0.6) -> bool:
    """True when something on the HOST actually accepts TCP on *port*.

    A guest proxy pin to a host port with no listener silently kills the
    phone's internet AND every impression (traffic goes to localhost:nothing).
    ``guest_proxy_healthy`` only checks the setting string — this is the
    real reachability probe used before trusting a pin.
    """
    import socket

    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (OSError, ValueError, OverflowError):
        return False


def guest_proxy_healthy(value: str, phone_idx: int | None = None) -> bool:
    """True when Android http_proxy is a usable 127.0.0.1:<port> (not :0/null/empty)."""
    raw = (value or "").strip()
    if not raw or raw.lower() in _CLEARED_PROXY_VALUES or raw.endswith(":0"):
        return False
    if not raw.startswith("127.0.0.1:"):
        return False
    try:
        port = int(raw.split(":", 1)[1])
    except (IndexError, ValueError):
        return False
    if port <= 0:
        return False
    if phone_idx is None:
        return True
    want = expected_guest_proxy_ports(int(phone_idx))
    return port in want


def expected_guest_proxy_ports(phone_idx: int) -> set[int]:
    """Accept inject port when enabled, else Tor HTTPTunnelPort (either is routable)."""
    from automation.tor_manager import phone_http_port

    ports = {int(phone_http_port(phone_idx))}
    try:
        from automation.mantis_inject_proxy import inject_enabled, phone_inject_port

        if inject_enabled():
            ports.add(int(phone_inject_port(phone_idx)))
    except Exception:
        pass
    return ports


# Last browser package per serial — so Tor restore pins Tor for Firefox/DDG, not MITM.
# Persisted to disk: the proxy watcher is a *separate process* and used to always
# re-pin inject (8218+), wiping Tor pins and freezing Firefox/DDG on HSTS cert errors.
_serial_browser_pkg: dict[str, str] = {}
_BROWSER_PKG_PATH = Path(r"C:\CPharm\logs\serial_browser_pkg.json")
# Browsers that must NOT use guest MITM inject (8218+). Firefox/DDG reject our
# CA; Brave often shows "not safe website" even after system CA install (own
# trust / HTTPS upgrades). Brave still gets ads via Chromium CDP paint.
_MITM_SKIP_PACKAGES = frozenset(
    {
        "org.mozilla.firefox",
        "com.duckduckgo.mobile.android",
        "com.brave.browser",
    }
)

# Chromium-family packages that support DevTools remote paint (not MITM).
_CDP_PAINT_PACKAGES = frozenset(
    {
        "org.chromium.chrome",
        "com.brave.browser",
        "com.android.chrome",
        "com.chrome.browser",
    }
)


def _load_browser_pkg_disk() -> dict[str, str]:
    try:
        if _BROWSER_PKG_PATH.is_file():
            data = json.loads(_BROWSER_PKG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items() if v}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return {}


def _save_browser_pkg_disk() -> None:
    try:
        _BROWSER_PKG_PATH.parent.mkdir(parents=True, exist_ok=True)
        merged = _load_browser_pkg_disk()
        merged.update(_serial_browser_pkg)
        _BROWSER_PKG_PATH.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def remember_browser_package(serial: str, package: str | None) -> None:
    ser = str(serial)
    pkg = (package or "").strip()
    if pkg:
        _serial_browser_pkg[ser] = pkg
    else:
        _serial_browser_pkg.pop(ser, None)
    _save_browser_pkg_disk()


def browser_package_for_serial(serial: str) -> str | None:
    ser = str(serial)
    if ser in _serial_browser_pkg:
        return _serial_browser_pkg[ser]
    disk = _load_browser_pkg_disk()
    pkg = disk.get(ser)
    if pkg:
        _serial_browser_pkg[ser] = pkg
    return pkg


def detect_foreground_browser_package(adb: object, serial: str) -> str | None:
    """Best-effort package from the resumed activity (watcher fallback)."""
    try:
        out = (
            adb.shell(  # type: ignore[union-attr]
                "dumpsys activity activities",
                serial=serial,
                timeout=8.0,
            ).stdout
            or ""
        )
    except Exception:
        return None
    for line in out.splitlines():
        low = line.lower()
        if "topresumedactivity" not in low and "mresumedactivity" not in low:
            continue
        for pkg in (
            "org.mozilla.firefox",
            "com.duckduckgo.mobile.android",
            "com.brave.browser",
            "com.android.chrome",
            "org.chromium.chrome",
            "com.chrome.browser",
        ):
            if pkg in low:
                return pkg
    return None


def resolve_browser_package(adb: object | None, serial: str, explicit: str | None = None) -> str | None:
    """Resolve active browser for proxy pinning.

    Foreground wins over stale in-memory/disk remember. The proxy watcher is a
    long-lived process; without this it kept Chromium in RAM and re-pinned
    inject (8218+) onto Firefox/DDG/Brave after the farm switched browsers.
    """
    pkg = (explicit or "").strip()
    if pkg:
        return pkg
    remembered = browser_package_for_serial(serial)
    if adb is None:
        return remembered
    detected = detect_foreground_browser_package(adb, serial)
    if detected:
        if detected != remembered:
            remember_browser_package(serial, detected)
        return detected
    return remembered


def skips_mitm(browser_package: str | None) -> bool:
    pkg = (browser_package or "").strip().lower()
    if not pkg:
        return False
    return pkg in _MITM_SKIP_PACKAGES or pkg.endswith(".firefox")


def supports_cdp_paint(browser_package: str | None) -> bool:
    """True when Mantis creatives can be painted via Chromium DevTools Protocol."""
    pkg = (browser_package or "").strip().lower()
    if not pkg:
        return False
    if pkg in _CDP_PAINT_PACKAGES:
        return True
    return "chromium" in pkg or pkg.endswith(".chrome")


def expected_guest_proxy(phone_idx: int, browser_package: str | None = None) -> str:
    """Preferred guest http_proxy endpoint.

    Chromium → inject 8218+ (MITM paints Mantis creatives when CA trusted).
    Brave/Firefox/DuckDuckGo → never MITM, but still Tor HTTP. Clearing to
    :0 is host-IP egress and is forbidden.
    """
    if skips_mitm(browser_package):
        from automation.tor_manager import phone_http_port

        return f"127.0.0.1:{int(phone_http_port(phone_idx))}"
    try:
        from automation.mantis_inject_proxy import inject_enabled, phone_inject_port

        if inject_enabled():
            return f"127.0.0.1:{int(phone_inject_port(phone_idx))}"
    except Exception:
        pass
    from automation.tor_manager import phone_http_port

    return f"127.0.0.1:{int(phone_http_port(phone_idx))}"


def _read_guest_proxy(adb: object, serial: str) -> str:
    try:
        return (
            adb.shell("settings get global http_proxy", serial=serial).stdout or ""  # type: ignore[union-attr]
        ).strip()
    except Exception:
        return ""


def restore_browse_session(
    adb: object,
    serial: str,
    phone_idx: int,
    log_fn: LogFn | None = None,
) -> dict:
    """Restore Tor after ad browse when mode is tor."""
    log = log_fn or (lambda _m: None)
    mode = browse_proxy_mode()
    # Scramble/direct stay off Tor so ads keep filling; isolation already rotated IP.
    if mode != "tor":
        log(f"Browse proxy: keeping {mode} (no Tor restore) serial={serial}")
        return {"skipped": True, "reason": mode}
    try:
        from automation.tor_manager import TorManager

        tor = TorManager(adb)  # type: ignore[arg-type]
        tor.start_phone_tor(int(phone_idx), str(serial))
        # Ad-fill clears to :0; start_phone_tor can race. Always pin inject (or Tor) port.
        proxy = pin_guest_proxy(
            adb,
            str(serial),
            int(phone_idx),
            attempts=3,
            browser_package=browser_package_for_serial(str(serial)),
        )
        if not guest_proxy_healthy(proxy, int(phone_idx)):
            proxy = pin_guest_proxy(
                adb,
                str(serial),
                int(phone_idx),
                attempts=3,
                browser_package=browser_package_for_serial(str(serial)),
            )
        log(f"Browse proxy: Tor restored serial={serial} http_proxy={proxy}")
        ok = guest_proxy_healthy(proxy, int(phone_idx))
        return {"ok": ok, "http_proxy": proxy}
    except Exception as exc:
        log(f"Browse proxy: Tor restore failed serial={serial} — {exc}")
        return {"ok": False, "error": str(exc)}


def restore_inject_after_identity(
    adb: object,
    serial: str,
    phone_idx: int,
    *,
    browser_package: str | None = None,
    attempts: int = 3,
) -> str:
    """Re-pin guest proxy after scramble/identity wipe that cleared ``:0``.

    Chromium mid-seq must never linger on ``:0``/null when inject is armed —
    ``prepare_browse_session`` / onboarding wipe intentionally clear Tor, then
    this restores inject (8218+) before long Tor NEWNYM or Lawnchair idle.
    Firefox/Brave/Opera/DDG keep ``:0`` in scramble/direct (MITM-skip).
    """
    ser = str(serial)
    idx = int(phone_idx)
    pkg = resolve_browser_package(adb, ser, browser_package)
    if pkg:
        remember_browser_package(ser, pkg)

    if skips_mitm(pkg):
        # MITM-skip browsers still pin Tor HTTP. Never clear to :0.
        return pin_guest_proxy(
            adb, ser, idx, attempts=attempts, browser_package=pkg
        )

    try:
        from automation.mantis_inject_proxy import ensure_inject_for_phone, inject_enabled

        if inject_enabled():
            for inj_try in range(max(1, int(attempts))):
                try:
                    info = ensure_inject_for_phone(
                        adb, ser, idx, install_ca=True
                    )
                    endpoint = (info.get("endpoint") or "").strip()
                    if info.get("ok") and guest_proxy_healthy(endpoint, idx):
                        pinned = pin_guest_proxy(
                            adb, ser, idx, attempts=2, browser_package=pkg
                        )
                        if guest_proxy_healthy(pinned, idx):
                            logger.info(
                                "inject restored after identity serial=%s "
                                "phone=%d endpoint=%s",
                                ser,
                                idx,
                                pinned,
                            )
                            return pinned
                except Exception as exc:
                    logger.warning(
                        "inject restore retry %d/%d serial=%s: %s",
                        inj_try + 1,
                        attempts,
                        ser,
                        exc,
                    )
                if inj_try + 1 < attempts:
                    time.sleep(0.6 * (inj_try + 1))
    except Exception as exc:
        logger.warning("inject restore soft-fail serial=%s: %s", ser, exc)

    pinned = pin_guest_proxy(adb, ser, idx, attempts=attempts, browser_package=pkg)
    if not guest_proxy_healthy(pinned, idx) and not skips_mitm(pkg):
        logger.warning(
            "inject restore still unhealthy serial=%s phone=%d proxy=%r pkg=%s",
            ser,
            idx,
            pinned,
            pkg,
        )
    return pinned


def _push_farmbrowser_proxy(adb: object, serial: str, port: int, package: str) -> None:
    """FarmBrowser ignores a later system http_proxy until set_proxy is broadcast.

    A phone left on DIRECT sends page and click traffic out the MuMu NAT
    (host IP). Mantis then drops the click. Never send type=none / clear_proxy.
    """
    pkg = (package or "").strip()
    if "farmbrowser" not in pkg and port <= 0:
        return
    if "farmbrowser" not in pkg:
        return
    try:
        adb.shell(  # type: ignore[attr-defined]
            "am broadcast -a com.farmbrowser.stealth.CONTROL "
            f"-n {pkg}/com.farmbrowser.stealth.browser.FarmBrowserReceiver "
            "--es action set_proxy --es host 127.0.0.1 "
            f"--ei port {int(port)} --es type http --receiver-include-background",
            serial=serial,
            timeout=12.0,
        )
    except Exception as exc:
        logger.warning("FarmBrowser set_proxy soft-fail serial=%s: %s", serial, exc)


def pin_guest_proxy(
    adb: object,
    serial: str,
    phone_idx: int,
    *,
    attempts: int = 3,
    browser_package: str | None = None,
) -> str:
    """Idempotently force guest http_proxy to the right port for this browser.

    Never treat :0 / null / empty as success. An empty expected endpoint
    falls back to the slot Tor HTTP port. Never write http_proxy :0.
    """
    idx = int(phone_idx)
    ser = str(serial)
    pkg = resolve_browser_package(adb, ser, browser_package)
    want = expected_guest_proxy(idx, browser_package=pkg)
    tries = max(1, int(attempts))
    last = ""

    if not want:
        from automation.tor_manager import phone_http_port

        want = f"127.0.0.1:{int(phone_http_port(idx))}"
        logger.warning(
            "pin_guest_proxy empty expected serial=%s phone=%d — using Tor HTTP %s (not :0)",
            ser,
            idx,
            want,
        )

    want_port = int(want.rsplit(":", 1)[-1])

    # Inject listen ports are 8218+; Tor HTTPTunnel is 8118+.
    use_inject = False
    try:
        from automation.mantis_inject_proxy import inject_enabled, phone_inject_port

        use_inject = (
            bool(inject_enabled())
            and not skips_mitm(pkg)
            and want_port == int(phone_inject_port(idx))
        )
    except Exception:
        use_inject = False

    for attempt in range(tries):
        cur = _read_guest_proxy(adb, ser)
        if guest_proxy_healthy(cur, idx) and cur == want:
            if _host_port_listens(want_port):
                return cur
            logger.warning(
                "pin_guest_proxy dead listener serial=%s phone=%d proxy=%s — restoring",
                ser,
                idx,
                cur,
            )
            if use_inject:
                try:
                    from automation.mantis_inject_proxy import start_inject_proxies

                    start_inject_proxies([idx])
                except Exception as exc:
                    logger.warning("pin inject restart failed serial=%s: %s", ser, exc)
            else:
                try:
                    from automation.tor_manager import start_tor_for_phone

                    start_tor_for_phone(idx)
                except Exception as exc:
                    logger.warning("pin tor restart failed serial=%s: %s", ser, exc)
            if _host_port_listens(want_port):
                return cur

        applied = False
        if use_inject:
            try:
                # Always (re)install farm CA — Brave/Chromium "not safe" when
                # inject is armed without a trusted CA on the guest.
                from automation.mantis_inject_proxy import ensure_inject_for_phone

                info = ensure_inject_for_phone(adb, ser, idx, install_ca=True)
                if not info.get("ok"):
                    logger.warning(
                        "pin inject not restored serial=%s phone=%d err=%s ca=%s",
                        ser,
                        idx,
                        info.get("error"),
                        info.get("ca_installed"),
                    )
                    applied = False
                else:
                    applied = True
                # CRITICAL: verify adb reverse tunnel exists -- ADB restarts destroy them
                from automation.mantis_inject_proxy import verify_reverse_tunnel
                if applied and not verify_reverse_tunnel(adb, ser, want_port):
                    logger.warning("REVERSE TUNNEL MISSING port=%d serial=%s — re-establishing", want_port, ser)
                    adb.reverse(str(want_port), str(want_port), serial=ser)  # type: ignore[union-attr]
            except Exception as exc:
                logger.debug("pin inject failed serial=%s: %s", ser, exc)

        if not applied:
            from automation.tor_manager import phone_http_port

            port = int(phone_http_port(idx)) if not use_inject else want_port
            try:
                adb.reverse(str(port), str(port), serial=ser)  # type: ignore[union-attr]
            except Exception:
                pass
            try:
                adb.set_http_proxy("127.0.0.1", port, serial=ser)  # type: ignore[union-attr]
                applied = True
            except Exception as exc:
                logger.debug("pin tor proxy failed serial=%s: %s", ser, exc)

        last = _read_guest_proxy(adb, ser)
        if (
            guest_proxy_healthy(last, idx)
            and (last == want or last.endswith(f":{want_port}"))
            and _host_port_listens(want_port)
        ):
            _push_farmbrowser_proxy(adb, ser, want_port, pkg)
            return last
        if attempt + 1 < tries:
            time.sleep(0.12 * (attempt + 1))

    if guest_proxy_healthy(last, idx):
        # Health by string value is NOT enough: a pin whose host port has no
        # listener (dead inject/tor, adb server restart wiped reverse tunnel)
        # passes the string check but kills every impression AND the phone's
        # own internet (http_proxy -> localhost:nothing). Probe the host side
        # before trusting the pin.
        try:
            last_port = int(last.rsplit(":", 1)[-1])
        except (IndexError, ValueError):
            last_port = 0
        if last_port > 0 and not _host_port_listens(last_port):
            # Do not clear to :0. That is host-IP egress (MuMu NAT). Leave the
            # pin so the heal tick can restore the listener without opening
            # the phone onto the host route.
            logger.warning(
                "pin_guest_proxy DEAD PIN serial=%s phone=%d proxy=%s host:%d not listening — not clearing to :0 (host-IP egress forbidden)",
                ser,
                idx,
                last,
                last_port,
            )
            return last
        _push_farmbrowser_proxy(adb, ser, last_port, pkg)
        return last
    logger.warning(
        "pin_guest_proxy still unhealthy serial=%s phone=%d last=%r want=%s pkg=%s",
        ser,
        idx,
        last,
        want,
        browser_package,
    )
    return last if last else ":0"
