"""
Browse proxy modes for getdabflow / Mantis ad runs.

``desktop_prefs.json``:
  ``browse_proxy_mode``: ``tor`` | ``scramble`` | ``direct`` | ``upstream``
  ``phone_upstream_proxies``: optional list parallel to ``phone_serials``
    (``http://user:pass@host:port`` — local forwarder adds auth for Android)

Env override: ``CPHARM_BROWSE_PROXY_MODE``.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import select
import socket
import socketserver
import threading
import time
from typing import Callable
from urllib.parse import urlparse

log = logging.getLogger(__name__)

UPSTREAM_HTTP_BASE = 8130
LogFn = Callable[[str], None]

_forwarder_lock = threading.Lock()
_forwarder_threads: dict[int, threading.Thread] = {}
_forwarder_stop: dict[int, threading.Event] = {}

_VALID_MODES = frozenset({"tor", "scramble", "direct", "upstream"})


def _prefs_path():
    from config import REC_DIR

    return REC_DIR / "desktop_prefs.json"


def load_browse_prefs() -> dict:
    try:
        p = _prefs_path()
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {}


def save_browse_prefs(**updates) -> dict:
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
    prefs = load_browse_prefs()
    lst = prefs.get("phone_upstream_proxies")
    if not isinstance(lst, list):
        return None
    if phone_idx < 0 or phone_idx >= len(lst):
        return None
    raw = str(lst[phone_idx] or "").strip()
    return raw or None


def upstream_local_port(phone_idx: int) -> int:
    return UPSTREAM_HTTP_BASE + int(phone_idx)


def sync_browse_proxy_env_from_prefs() -> str:
    """Copy prefs mode into ``CPHARM_BROWSE_PROXY_MODE`` when env unset."""
    if os.environ.get("CPHARM_BROWSE_PROXY_MODE", "").strip():
        return browse_proxy_mode()
    mode = browse_proxy_mode()
    os.environ["CPHARM_BROWSE_PROXY_MODE"] = mode
    return mode


def _parse_upstream_url(url: str) -> tuple[str, int, str | None]:
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


class _UpstreamProxyHandler(socketserver.BaseRequestHandler):
    upstream_host: str = ""
    upstream_port: int = 0
    proxy_auth: str | None = None

    def handle(self) -> None:
        client = self.request
        try:
            client.settimeout(120)
            header = b""
            while b"\r\n\r\n" not in header and len(header) < 65536:
                chunk = client.recv(4096)
                if not chunk:
                    return
                header += chunk
            first_line = header.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
            parts = first_line.split()
            if len(parts) < 2:
                return
            method, target = parts[0].upper(), parts[1]
            up = socket.create_connection((self.upstream_host, self.upstream_port), timeout=60)
            up.settimeout(120)
            if method == "CONNECT":
                host_port = target
                req = f"CONNECT {host_port} HTTP/1.1\r\nHost: {host_port}\r\n"
                if self.proxy_auth:
                    req += f"Proxy-Authorization: {self.proxy_auth}\r\n"
                req += "\r\n"
                up.sendall(req.encode("latin-1"))
                resp = b""
                while b"\r\n\r\n" not in resp and len(resp) < 65536:
                    chunk = up.recv(4096)
                    if not chunk:
                        return
                    resp += chunk
                if b" 200 " not in resp.split(b"\r\n", 1)[0]:
                    client.sendall(resp)
                    return
                client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                self._relay(client, up)
            else:
                up.sendall(header)
                self._relay(client, up)
        except OSError as exc:
            log.debug("upstream forwarder client error: %s", exc)
        finally:
            try:
                client.close()
            except OSError:
                pass

    @staticmethod
    def _relay(a: socket.socket, b: socket.socket) -> None:
        sockets = [a, b]
        while True:
            try:
                readable, _, _ = select.select(sockets, [], [], 120)
            except (OSError, ValueError):
                break
            if not readable:
                break
            for sock in readable:
                other = b if sock is a else a
                try:
                    data = sock.recv(65536)
                except OSError:
                    return
                if not data:
                    return
                try:
                    other.sendall(data)
                except OSError:
                    return


def _make_handler_class(host: str, port: int, auth: str | None):
    return type(
        "UpstreamProxyHandler",
        (_UpstreamProxyHandler,),
        {"upstream_host": host, "upstream_port": port, "proxy_auth": auth},
    )


def stop_upstream_forwarder(phone_idx: int) -> None:
    with _forwarder_lock:
        ev = _forwarder_stop.pop(int(phone_idx), None)
        if ev:
            ev.set()
        _forwarder_threads.pop(int(phone_idx), None)


def ensure_upstream_forwarder(phone_idx: int, upstream_url: str) -> dict:
    """Start local unauthenticated HTTP proxy → authenticated upstream."""
    idx = int(phone_idx)
    host, port, auth = _parse_upstream_url(upstream_url)
    listen_port = upstream_local_port(idx)
    with _forwarder_lock:
        t = _forwarder_threads.get(idx)
        if t and t.is_alive():
            return {"ok": True, "port": listen_port, "reused": True}
        stop_upstream_forwarder(idx)
        stop_ev = threading.Event()
        handler = _make_handler_class(host, port, auth)

        def _serve() -> None:
            try:
                with socketserver.ThreadingTCPServer(
                    ("127.0.0.1", listen_port),
                    handler,
                ) as srv:
                    srv.daemon_threads = True
                    srv.timeout = 1.0
                    while not stop_ev.is_set():
                        srv.handle_request()
            except OSError as exc:
                log.warning("upstream forwarder stopped phone_idx=%s: %s", idx, exc)

        th = threading.Thread(target=_serve, name=f"cpharm-upstream-{idx}", daemon=True)
        _forwarder_stop[idx] = stop_ev
        _forwarder_threads[idx] = th
        th.start()
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", listen_port), timeout=0.3):
                return {"ok": True, "port": listen_port, "upstream": f"{host}:{port}"}
        except OSError:
            time.sleep(0.05)
    return {"ok": False, "port": listen_port, "error": "forwarder did not bind in time"}


def _farmbrowser_set_proxy(serial: str, host: str, port: int, proxy_type: str = "http") -> bool:
    """Use FarmBrowser's ADB broadcast interface to set proxy directly.

    Returns ``True`` when the broadcast was sent successfully.
    Falls back silently when FarmBrowser is not installed.
    """
    try:
        from browser_adb import farmbrowser_control_broadcast

        result = farmbrowser_control_broadcast(
            serial, "set_proxy",
            {"host": host, "port": port, "type": proxy_type},
        )
        if result.get("ok"):
            log.debug("FarmBrowser proxy set via broadcast serial=%s %s:%s", serial, host, port)
            return True
        log.debug("FarmBrowser broadcast failed serial=%s: %s", serial, result)
    except ImportError:
        pass
    return False


def _farmbrowser_clear_proxy(serial: str) -> bool:
    """Clear FarmBrowser's proxy via ADB broadcast."""
    try:
        from browser_adb import farmbrowser_control_broadcast

        result = farmbrowser_control_broadcast(serial, "clear_proxy")
        return bool(result.get("ok"))
    except ImportError:
        pass
    return False


def _farmbrowser_rotate_identity(serial: str) -> str:
    """Rotate FarmBrowser identity via ADB broadcast. Returns identity name."""
    try:
        from browser_adb import farmbrowser_control_broadcast

        result = farmbrowser_control_broadcast(serial, "rotate_identity")
        return result.get("result", "")
    except ImportError:
        pass
    return ""


def prepare_browse_session(
    serial: str,
    phone_idx: int,
    log_fn: LogFn | None = None,
) -> dict:
    """Apply browse mode before getdabflow ``open_url``.

    When FarmBrowser is the active browser, proxy changes are pushed directly
    to the app via ADB broadcast (``FarmBrowserReceiver``) — faster and more
    reliable than ADB ``settings put global http_proxy``.
    """
    log = log_fn or (lambda _m: None)
    mode = browse_proxy_mode()
    ser = str(serial)
    idx = int(phone_idx)
    out: dict = {"mode": mode}

    # Detect FarmBrowser presence
    try:
        from browser_adb import farmbrowser_installed

        has_fb = farmbrowser_installed(ser)
    except ImportError:
        has_fb = False
    out["farmbrowser"] = has_fb

    if mode == "tor":
        # Even in Tor mode, FarmBrowser should know about the proxy so it can
        # display the indicator and route traffic.  The ADB-level http_proxy
        # already points at the host Tor tunnel — FarmBrowser auto-detects it.
        out["skipped"] = True
        if has_fb:
            # Rotate identity on each Tor session for maximum stealth
            out["identity_rotated"] = bool(_farmbrowser_rotate_identity(ser))
        return out

    import tor_manager as tm

    try:
        tm.clear_all_proxies_on_devices([ser])
        tm.kick_default_browser_after_proxy_teardown([ser])
    except Exception as exc:
        log(f"Browse proxy: clear Tor proxy failed serial={ser} — {exc}")
        out["clear_error"] = str(exc)

    # Clear FarmBrowser's internal proxy when switching modes
    if has_fb:
        _farmbrowser_clear_proxy(ser)

    if mode == "upstream":
        url = upstream_proxy_url_for_phone(idx)
        if url:
            fwd = ensure_upstream_forwarder(idx, url)
            out["forwarder"] = fwd
            if fwd.get("ok"):
                applied = tm.apply_host_http_proxy_adb(ser, idx, int(fwd["port"]))
                out["http_proxy"] = applied
                log(f"Browse proxy: upstream serial={ser} local={fwd['port']}")
                # Also push proxy directly to FarmBrowser for immediate use
                if has_fb:
                    _farmbrowser_set_proxy(ser, "127.0.0.1", int(fwd["port"]), "http")
                try:
                    import emulator_ad_mode as eam

                    out["scramble"] = eam.scramble_device_session(ser, idx, log_fn=log)
                except Exception as exc:
                    out["scramble_error"] = str(exc)
            else:
                log(f"Browse proxy: upstream forwarder failed — {fwd.get('error')}")
        else:
            log(f"Browse proxy: upstream mode but no proxy URL for phone_idx={idx} — using scramble")
            mode = "scramble"
            out["mode"] = "scramble"

    if mode in ("scramble", "direct"):
        log(f"Browse proxy: {mode} (direct internet) serial={ser}")
        if mode == "scramble":
            try:
                import emulator_ad_mode as eam

                out["scramble"] = eam.scramble_device_session(ser, idx, log_fn=log)
            except Exception as exc:
                log(f"Browse proxy: scramble failed serial={ser} — {exc}")
                out["scramble_error"] = str(exc)
        # Rotate FarmBrowser identity on scramble for extra diversity
        if has_fb:
            out["identity_rotated"] = bool(_farmbrowser_rotate_identity(ser))

    out["ok"] = True
    return out


def restore_browse_session(
    serial: str,
    phone_idx: int,
    log_fn: LogFn | None = None,
) -> dict:
    """After ad browse / close — restore Tor when mode is ``tor``."""
    log = log_fn or (lambda _m: None)
    mode = browse_proxy_mode()
    if mode != "tor":
        log(f"Browse proxy: keeping {mode} (no Tor restore) serial={serial}")
        return {"skipped": True, "reason": mode}
    try:
        import tor_manager as tm

        result = tm.ensure_tor_and_proxy_for_phone(str(serial), int(phone_idx))
        log(f"Browse proxy: Tor restored serial={serial}")
        return {"ok": bool(result.get("ok", True)), "tor": result}
    except Exception as exc:
        log(f"Browse proxy: Tor restore failed serial={serial} — {exc}")
        return {"ok": False, "error": str(exc)}


def dabflow_browse_active(serial: str | None = None) -> bool:
    """True when dabflow should bypass Tor (scramble/direct/upstream)."""
    mode = browse_proxy_mode()
    if mode in ("scramble", "direct", "upstream"):
        return True
    if mode == "tor":
        return False
    return False
