"""Mantis inject proxy — phone → this → Tor/residential/direct, HTML JS inject for getdabflow.

Bypasses broken Chromium --remote-debugging-port by MITM'ing getdabflow.app
and inserting the same PATCH_JS the CDP path would run.

Ports: PHARMFLOW_MANTIS_INJECT_BASE (default 8218) + phone_index
Upstream modes:
  tor          — Tor HTTPTunnel 8118+idx (default)
  residential  — HTTP CONNECT via provider pool (unique IP per phone)
  direct       — direct connection (no proxy)
"""

from __future__ import annotations

import json
import logging
import os
import re
import select
import socket
import ssl
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from automation.config import TOR_HTTP_TUNNEL_BASE
from automation.dabflow_mantis_ad_urls import record_phone_viewed_ads
from automation.dabflow_mantis_client_patch import (
    PATCH_JS,
    _ssp_paint_expression,
    filter_ssp_ads_prefer_paying,
    get_cached_ssp_ads,
    prefetch_ssp_ads_prefer_paying,
)
logger = logging.getLogger(__name__)


def _ca():
    """Lazy import of the CA module (needs the ``cryptography`` wheel).

    Importing at module scope hard-crashed every cryptography-less environment
    at import time (native-ARM py3.14 has no wheel; see runtime_paths.helper_python).
    The proxy is importable everywhere; only the TLS-MITM paths below need the
    CA, and those run under the deps-complete helper interpreter.
    """
    from automation.mantis_inject_ca import (  # noqa: PLC0415
        ensure_ca_files,
        install_ca_on_device,
        ssl_context_for_host,
    )

    return ensure_ca_files, install_ca_on_device, ssl_context_for_host

def _env_first(*names: str, default: str = "") -> str:
    """Prefer CPHARM_* (live farm) then PHARMFLOW_* (branded) then default."""
    for name in names:
        raw = os.environ.get(name)
        if raw is not None and str(raw).strip() != "":
            return str(raw)
    return default


def _logs_dirs() -> list[Path]:
    """Operator log roots for reads.

    Explicit LOGS/LOG_DIR env: first non-empty wins (tests + single override).
    Otherwise dual-read live CPharm then branded PharmFlow.
    """
    for name in (
        "CPHARM_LOGS",
        "PHARMFLOW_LOGS",
        "CPHARM_LOG_DIR",
        "PHARMFLOW_LOG_DIR",
    ):
        raw = os.environ.get(name)
        if raw is not None and str(raw).strip() != "":
            return [Path(raw)]
    return [Path(r"C:\CPharm\logs"), Path(r"C:\PharmFlow\logs")]


def _logs_dirs_write() -> list[Path]:
    """Always dual-write sticky inject state to both operator roots."""
    out: list[Path] = []
    seen: set[str] = set()
    for d in list(_logs_dirs()) + [Path(r"C:\CPharm\logs"), Path(r"C:\PharmFlow\logs")]:
        key = str(d).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def _primary_logs_dir() -> Path:
    return _logs_dirs()[0]


INJECT_BASE = int(
    _env_first("CPHARM_MANTIS_INJECT_BASE", "PHARMFLOW_MANTIS_INJECT_BASE", default="8218")
    or "8218"
)
DABFLOW_HOSTS = ("getdabflow.app", "www.getdabflow.app")
INJECT_MARKER = b"__pharmflowMantisPatchV1"
# Tor exits often get house/bot SSP only (utm_source=mantis-bot) — GraphQL $/impr stay flat.
# Billing hosts must stay on the phone exit (Tor/residential). billing_direct defaults OFF.
_MANTIS_BILLING_HOST_SUFFIXES = (
    "ssp.mantis.marketing",
    "bids.mantis.marketing",
    "static.mantis.marketing",
    "mantis.marketing",
    "mantisadnetwork.com",
)
# Inject listen base — never adopt this as Tor HTTPTunnelPort base.
_INJECT_HTTP_BASE = 8218
_STATS_PATH = _primary_logs_dir() / "mantis_inject_stats.json"
# Farm publishes scrambled UA/Client Hints; inject proxy rewrites Chromium
# request headers when MuMu Chromium has no DevTools (CDP Emulation dead).
_CLIENT_HINTS_PATH = _primary_logs_dir() / "client_hints_by_phone.json"
_CLIENT_HINTS_LOCK = threading.Lock()
_CLIENT_HINTS_CACHE: dict[str, dict] = {}
_CLIENT_HINTS_MTIME = 0.0


def phone_inject_port(phone_index: int) -> int:
    return INJECT_BASE + int(phone_index)


def inject_port_open(port: int, timeout: float = 0.35) -> bool:
    """True when the host inject listener actually accepts TCP."""
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def mitm_enabled() -> bool:
    """MITM HTML inject — needs trusted CA on the phone (farm arms with ca=True).

    Default ON so Firefox/Brave/DuckDuckGo (no CDP) still get Mantis creatives.
    Set CPHARM_MANTIS_INJECT_MITM=0 / PHARMFLOW_MANTIS_INJECT_MITM=0 to force blind CONNECT.
    """
    raw = _env_first("CPHARM_MANTIS_INJECT_MITM", "PHARMFLOW_MANTIS_INJECT_MITM", default="1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def inject_enabled() -> bool:
    raw = _env_first(
        "CPHARM_MANTIS_INJECT_PROXY", "PHARMFLOW_MANTIS_INJECT_PROXY", default="1"
    ).strip().lower()
    return raw not in ("0", "false", "no", "off")


def upstream_mode() -> str:
    return _env_first(
        "CPHARM_MANTIS_INJECT_UPSTREAM", "PHARMFLOW_MANTIS_INJECT_UPSTREAM", default="tor"
    ).strip().lower()


def _slot_from_env(phone_index: int) -> int | None:
    """Slot map the farm owner exports at arm time (CPHARM_/PHARMFLOW_INJECT_SLOT_MAP).

    JSON object {"<absolute idx>": <slot>}. The farm knows its live fleet, so
    this is the authoritative mapping — file-based roster scans are a fallback
    and can be re-polluted by rescans mid-flight.
    """
    raw = _env_first("CPHARM_INJECT_SLOT_MAP", "PHARMFLOW_INJECT_SLOT_MAP")
    if not raw.strip():
        return None
    try:
        m = json.loads(raw)
        val = m.get(str(int(phone_index)))
        return int(val) if val is not None else None
    except Exception:
        return None


def _fleet_slot(phone_index: int) -> int | None:
    """Roster slot for a phone: its position among the LIVE vm fleet.

    Slot = absolute index minus the fleet's minimum live index (the historical
    working scheme: vm27 = Tor base + roster slot). Sources, in order: the
    live rows of ADB_SERIAL_MAP.lock.json, then pharmflow_config.json /
    cpharm_config.json. Returns None when the phone is not on the live roster
    or the roster has no vm rows.
    """
    idx = int(phone_index)
    names: list[str] = []
    for logs_dir in _logs_dirs():
        try:
            data = json.loads((logs_dir / "ADB_SERIAL_MAP.lock.json").read_text(encoding="utf-8"))
            names = [
                str(k)
                for k, v in dict(data.get("phones") or {}).items()
                if str(v or "").strip()
            ]
        except Exception:
            names = []
        if names:
            break
        for cfg_name in ("cpharm_config.json", "pharmflow_config.json"):
            try:
                cfg = json.loads((logs_dir.parent / cfg_name).read_text(encoding="utf-8"))
                names = [str(x) for x in (cfg.get("phones") or [])]
            except Exception:
                names = []
            if names:
                break
        if names:
            break
    if not names:
        return None
    idxs = sorted(int(m.group(1)) for n in names if (m := re.match(r"^vm(\d+)\.", n)))
    if not idxs or idx not in idxs:
        return None
    return idxs.index(idx)


def _is_poison_tor_http_base(base: int) -> bool:
    """True when ``base`` is the mantis inject listen base, not Tor HTTPTunnel."""
    return int(base) == int(INJECT_BASE) or int(base) == int(_INJECT_HTTP_BASE)


def _read_live_tor_http_base() -> int | None:
    """Freshest tor_port_bases.json http_base that is not the inject listen base."""
    best: tuple[float, int] | None = None
    now = time.time()
    for logs_dir in _logs_dirs():
        state = logs_dir / "tor_port_bases.json"
        try:
            data = json.loads(state.read_text(encoding="utf-8"))
            age = now - float(data.get("ts") or 0)
            base = int(data.get("http_base") or 0)
            if age >= 120 or base <= 0 or _is_poison_tor_http_base(base):
                continue
            ts = float(data.get("ts") or 0)
            if best is None or ts > best[0]:
                best = (ts, base)
        except Exception:
            continue
    return None if best is None else best[1]


def _tor_port_for_slot(base: int, phone_index: int) -> int:
    idx = int(phone_index)
    slot = _slot_from_env(idx)
    if slot is None:
        slot = _fleet_slot(idx)
    if slot is not None:
        return int(base) + int(slot)
    return int(base) + idx


def upstream_tor_port(phone_index: int) -> int:
    """Host Tor HTTPTunnelPort this phone's traffic must dial upstream.

    Tor lanes are prewarmed for a contiguous SLOT range (0..N-1) at the runtime
    HTTP base. Dialing ``base + absolute_index`` only works when slot 0 is
    live; with vm39-47 as the fleet it produced 8118+39=8157 — nobody listening
    — 10061 TLS storm + fleet-wide dead internet (2026-09-13 incident). The
    base is resolved live from the Tor owner's broadcast file; the SLOT is
    resolved from the live roster (idx - min live idx). Unmapped phones keep
    the legacy absolute behavior rather than risk sharing another lane.

    Never returns a port in the inject listen window (8218+): desktop_prefs
    still carries the old PharmFlow-evasion pair 9150/8218, and branding
    rename briefly pointed logs at a stale PharmFlow broadcast so inject
    fell through to ``phone_http_port`` = 8218+slot (inject dialing inject).
    """
    idx = int(phone_index)
    # 1) Broadcast file first: the Tor-owning process heartbeats it while its
    #    lanes live, and it is the only truth shared across processes. An
    #    in-process tor_manager import here would compute *this* process's own
    #    shifted base — correct only when we own the lanes.
    base = _read_live_tor_http_base()
    if base is not None:
        return _tor_port_for_slot(base, idx)
    # 2) Align in-process bases to the live broadcast (or 8118 when prefs say 8218).
    try:
        from automation.tor_manager import align_bases_to_live_broadcast, phone_http_port

        align_bases_to_live_broadcast()
        port = int(phone_http_port(idx))
        # Reject dialing this phone's inject listener as if it were Tor.
        if port != phone_inject_port(idx):
            slot = _slot_from_env(idx)
            if slot is None:
                slot = _fleet_slot(idx)
            inferred_base = port - (int(slot) if slot is not None else idx)
            if not _is_poison_tor_http_base(inferred_base):
                return port
    except Exception:
        pass
    # 3) Raw constant — last resort; matches unshifted default spawns.
    safe_base = int(TOR_HTTP_TUNNEL_BASE)
    if _is_poison_tor_http_base(safe_base):
        safe_base = 8118
    return _tor_port_for_slot(safe_base, idx)


def _store_viewed_beacon(phone_index: int, body: bytes) -> None:
    """Save click URLs the phone fetched so Path3 does not open a host token."""
    try:
        data = json.loads(body.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError:
        return
    ads = data.get("ads") if isinstance(data, dict) else None
    if not isinstance(ads, list):
        return
    try:
        n = record_phone_viewed_ads(phone_index, ads)
    except Exception as exc:
        logger.warning("viewed-click store failed phone=%s: %s", phone_index, exc)
        _beacon_note(f"store-fail phone={phone_index} {exc}")
        return
    sample = ""
    if not n and ads:
        first = next((a for a in ads if isinstance(a, dict)), {})
        sample = " url=" + str(first.get("click_url") or "")[:90].replace(" ", "")
    _beacon_note(f"store phone={phone_index} n={n} ads={len(ads)}{sample}")
    if n:
        logger.info("stored phone-viewed clicks phone=%s n=%s", phone_index, n)


def _beacon_note(line: str) -> None:
    try:
        for logs_dir in _logs_dirs():
            path = logs_dir / "inject_beacon.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(time.strftime("%H:%M:%S ") + line + "\n")
            break
    except OSError:
        pass


def _is_dabflow_host(host: str) -> bool:
    h = (host or "").split(":")[0].lower().strip(".")
    return h in DABFLOW_HOSTS or h.endswith(".getdabflow.app")


def billing_direct_enabled() -> bool:
    """True when billing traffic should go direct (host IP) instead of Tor.

    Default **0** — standing rule 7 (operator, 2026-09-10): host-IP egress is
    forbidden. All host-IP billing opens dedupe to one visitor and flag the
    farm as single-IP bot traffic. Tor exits are the billing path; if Mantis
    406s an exit, rotate the exit — never fall back to the host IP.
    """
    raw = _env_first(
        "CPHARM_MANTIS_BILLING_DIRECT", "PHARMFLOW_MANTIS_BILLING_DIRECT", default="0"
    ).strip().lower()
    return raw in ("1", "true", "yes")


def _is_mantis_billing_host(host: str) -> bool:
    h = (host or "").split(":")[0].lower().strip(".")
    if not h:
        return False
    for suf in _MANTIS_BILLING_HOST_SUFFIXES:
        if h == suf or h.endswith("." + suf):
            return True
    return False


def _publish_inject_stats(proxies: list) -> None:
    """Write live MITM counters so dash/agents can see inject rising.

    Only owned listeners publish. Adopted zero-stat stubs from a second process
    (farm adopting keepalive ports) used to overwrite real counters with 0.
    """
    try:
        owned = [
            p
            for p in proxies
            if getattr(p, "owns_listener", False) and getattr(p, "_sock", None) is not None
        ]
        if not owned:
            return
        rows = {}
        for p in owned:
            rows[str(int(getattr(p, "phone_index", -1)))] = {
                "listen": int(getattr(p, "listen_port", 0) or 0),
                "stats": dict(getattr(p, "stats", {}) or {}),
            }
        payload = {"updated": time.time(), "phones": rows}
        text = json.dumps(payload, indent=2) + "\n"
        for logs_dir in _logs_dirs_write():
            try:
                logs_dir.mkdir(parents=True, exist_ok=True)
                (logs_dir / "mantis_inject_stats.json").write_text(text, encoding="utf-8")
            except OSError:
                continue
    except OSError as exc:
        logger.debug("publish inject stats soft-fail: %s", exc)


def publish_client_hints_for_phone(phone_index: int, profile: object) -> None:
    """Persist scrambled UA + Client Hints for the inject-proxy MITM rewriter."""
    if profile is None:
        return
    ua = str(getattr(profile, "user_agent", "") or "")
    model = str(getattr(profile, "model", "") or "")
    if not ua or not model:
        return
    meta_fn = getattr(profile, "user_agent_metadata", None)
    metadata = meta_fn() if callable(meta_fn) else {}
    if not isinstance(metadata, dict):
        metadata = {}
    brands = metadata.get("brands") if isinstance(metadata.get("brands"), list) else []
    full = (
        metadata.get("fullVersionList")
        if isinstance(metadata.get("fullVersionList"), list)
        else []
    )
    platform = str(metadata.get("platform") or "Android")
    platform_ver = str(metadata.get("platformVersion") or "13.0.0")
    mobile = bool(metadata.get("mobile", True))

    def _brand_hdr(items: list) -> str:
        parts: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            b = str(item.get("brand") or "").replace('"', "\\\"")
            v = str(item.get("version") or "")
            if b and v:
                parts.append(f'"{b}";v="{v}"')
        return ", ".join(parts)

    sec_ch_ua = _brand_hdr(brands) or '"Chromium";v="120", "Not=A?Brand";v="24"'
    sec_ch_full = _brand_hdr(full) or sec_ch_ua
    row = {
        "user_agent": ua,
        "model": model,
        "sec_ch_ua": sec_ch_ua,
        "sec_ch_ua_full_version_list": sec_ch_full,
        "sec_ch_ua_mobile": "?1" if mobile else "?0",
        "sec_ch_ua_platform": f'"{platform}"',
        "sec_ch_ua_platform_version": f'"{platform_ver}"',
        "sec_ch_ua_model": f'"{model}"',
        "updated": time.time(),
    }
    try:
        with _CLIENT_HINTS_LOCK:
            data: dict = {}
            for logs_dir in _logs_dirs():
                path = logs_dir / "client_hints_by_phone.json"
                if not path.is_file():
                    continue
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        data = raw
                        break
                except (OSError, ValueError, TypeError):
                    continue
            data[str(int(phone_index))] = row
            text = json.dumps(data, indent=2) + "\n"
            for logs_dir in _logs_dirs_write():
                try:
                    logs_dir.mkdir(parents=True, exist_ok=True)
                    (logs_dir / "client_hints_by_phone.json").write_text(text, encoding="utf-8")
                except OSError:
                    continue
            _CLIENT_HINTS_CACHE.clear()
            _CLIENT_HINTS_CACHE.update(
                {str(k): v for k, v in data.items() if isinstance(v, dict)}
            )
        logger.info(
            "published Client Hints phone=%s model=%s for MITM/CDP",
            phone_index,
            model,
        )
    except OSError as exc:
        logger.debug("publish_client_hints soft-fail phone=%s: %s", phone_index, exc)


def _client_hints_for_phone(phone_index: int) -> dict:
    """Load published Client Hints for this inject phone (mtime-cached)."""
    global _CLIENT_HINTS_MTIME
    key = str(int(phone_index))
    path: Path | None = None
    mtime = 0.0
    for logs_dir in _logs_dirs():
        cand = logs_dir / "client_hints_by_phone.json"
        try:
            if cand.is_file():
                path = cand
                mtime = cand.stat().st_mtime
                break
        except OSError:
            continue
    with _CLIENT_HINTS_LOCK:
        if mtime and mtime == _CLIENT_HINTS_MTIME and key in _CLIENT_HINTS_CACHE:
            return dict(_CLIENT_HINTS_CACHE[key])
        if path is None:
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        _CLIENT_HINTS_CACHE.clear()
        _CLIENT_HINTS_CACHE.update(
            {str(k): v for k, v in raw.items() if isinstance(v, dict)}
        )
        _CLIENT_HINTS_MTIME = mtime
        row = _CLIENT_HINTS_CACHE.get(key)
        return dict(row) if isinstance(row, dict) else {}


def _rebuild_request(status_line: bytes, headers: dict[str, str], body: bytes) -> bytes:
    """Rebuild an HTTP/1.1 request from a header map (preserves body)."""
    lines = [status_line.rstrip(b"\r\n")]
    for k, v in headers.items():
        lines.append(f"{k}: {v}".encode("latin-1"))
    return b"\r\n".join(lines) + b"\r\n\r\n" + body


def _apply_client_hints_headers(
    headers: dict[str, str], hints: dict
) -> dict[str, str]:
    """Overwrite UA + Sec-CH-UA-* so Cloudflare sees the scrambled model."""
    if not hints:
        return headers
    out = dict(headers)
    ua = str(hints.get("user_agent") or "")
    if ua:
        out["user-agent"] = ua
    mapping = (
        ("sec-ch-ua", "sec_ch_ua"),
        ("sec-ch-ua-mobile", "sec_ch_ua_mobile"),
        ("sec-ch-ua-platform", "sec_ch_ua_platform"),
        ("sec-ch-ua-platform-version", "sec_ch_ua_platform_version"),
        ("sec-ch-ua-model", "sec_ch_ua_model"),
        ("sec-ch-ua-full-version-list", "sec_ch_ua_full_version_list"),
    )
    for hdr, key in mapping:
        val = str(hints.get(key) or "")
        if val:
            out[hdr] = val
    return out


def _build_inject_script() -> bytes:
    """PATCH_JS + delayed host SSP paint fallback (CDP /json often dead).

    Keep ``__pharmflowCssOnly=true`` so Path1/2 creatives stay non-clickable
    (pointer-events:none). Prefer paying host creatives; delay host-paint so
    native mantis.js can fill zones first (billable path). Host-paint only
    fills still-empty zones. Path3 flips cssOnly=false via CDP for clicks.
    """
    # Paint the bottom creative so the page is not empty. Do not store these
    # host tokens for Path3 — their bi/bt were issued to this PC. The page's
    # own SSP fetch is what Path3 opens.
    ads: list = []
    try:
        ads = filter_ssp_ads_prefer_paying(
            get_cached_ssp_ads(allow_stale=True) or [],
            allow_house_fallback=True,
        )
        if not ads:
            ads = prefetch_ssp_ads_prefer_paying(
                attempts=4, delay_s=0.2, allow_house_fallback=True
            )
    except Exception as exc:
        logger.debug("bottom-ad paint prefetch failed: %s", exc)
        ads = []
    paint_js = ""
    if ads:
        expr = _ssp_paint_expression(ads, empty_only=False).strip()
        if expr.endswith(";"):
            expr = expr[:-1]
        paint_js = (
            "window.__pharmflowRunHostPaint=function(){"
            "return "
            + expr
            + ";};\n"
            "setTimeout(function(){try{window.__pharmflowRunHostPaint();}catch(e){}},0);\n"
            "setTimeout(function(){try{window.__pharmflowRunHostPaint();}catch(e){}},400);\n"
        )
    return (
        "<script data-pharmflow-mantis-inject=\"1\" data-pharmflow-ssp-paint=\"1\">\n"
        "window.__pharmflowCssOnly=true;\n"
        "window.__pharmflowAllowSspPaint=true;\n"
        + PATCH_JS
        + "\n"
        + paint_js
        + "</script>\n"
    ).encode("utf-8")


def _inject_html(body: bytes) -> bytes:
    if INJECT_MARKER in body:
        return body
    lower = body.lower()
    tag = _build_inject_script()
    idx = lower.rfind(b"</body>")
    if idx >= 0:
        return body[:idx] + tag + body[idx:]
    idx = lower.rfind(b"</html>")
    if idx >= 0:
        return body[:idx] + tag + body[idx:]
    return body + tag


def _maybe_decompress(body: bytes, encoding: str) -> tuple[bytes, str]:
    """Return (body, encoding). Clears encoding when we decompress for rewrite."""
    enc = (encoding or "").lower().strip()
    if enc in ("", "identity"):
        return body, enc
    try:
        if enc == "gzip":
            import gzip

            return gzip.decompress(body), ""
        if enc == "deflate":
            import zlib

            return zlib.decompress(body), ""
        if enc in ("br", "brotli"):
            try:
                import brotli  # type: ignore

                return brotli.decompress(body), ""
            except Exception:
                return body, enc
    except Exception as exc:
        logger.debug("decompress %s failed: %s", enc, exc)
        return body, enc
    return body, enc


def _recv_until(conn: socket.socket, marker: bytes, *, limit: int = 65536) -> bytes:
    buf = b""
    while marker not in buf and len(buf) < limit:
        chunk = conn.recv(4096)
        if not chunk:
            break
        buf += chunk
    return buf


def _parse_request_line(head: bytes) -> tuple[str, str, str]:
    line = head.split(b"\r\n", 1)[0].decode("latin-1", "replace")
    parts = line.split(" ")
    if len(parts) < 3:
        return "", "", ""
    return parts[0].upper(), parts[1], parts[2]


def _host_port_from_target(target: str, default_port: int) -> tuple[str, int]:
    if target.startswith("["):
        # ipv6 — not used
        return target, default_port
    if ":" in target:
        host, _, port_s = target.rpartition(":")
        try:
            return host, int(port_s)
        except ValueError:
            return target, default_port
    return target, default_port


def _connect_via_upstream_http_proxy(
    proxy_host: str,
    proxy_port: int,
    dest_host: str,
    dest_port: int,
    *,
    timeout: float = 30.0,
) -> socket.socket:
    sock = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    req = (
        f"CONNECT {dest_host}:{dest_port} HTTP/1.1\r\n"
        f"Host: {dest_host}:{dest_port}\r\n"
        f"Proxy-Connection: keep-alive\r\n\r\n"
    ).encode("ascii")
    sock.sendall(req)
    resp = _recv_until(sock, b"\r\n\r\n")
    if b" 200 " not in resp.split(b"\r\n", 1)[0]:
        sock.close()
        raise OSError(f"upstream CONNECT failed: {resp[:200]!r}")
    return sock


def _tunnel(a: socket.socket, b: socket.socket) -> None:
    try:
        while True:
            r, _, _ = select.select([a, b], [], [], 120.0)
            if not r:
                break
            for src in r:
                dst = b if src is a else a
                data = src.recv(65536)
                if not data:
                    return
                dst.sendall(data)
    except OSError:
        return
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass


def _read_http_message(sock: ssl.SSLSocket | socket.socket) -> tuple[bytes, bytes, dict[str, str]]:
    head = _recv_until(sock, b"\r\n\r\n", limit=256_000)
    if b"\r\n\r\n" not in head:
        return head, b"", {}
    header_blob, _, rest = head.partition(b"\r\n\r\n")
    headers: dict[str, str] = {}
    for line in header_blob.split(b"\r\n")[1:]:
        if b":" not in line:
            continue
        k, _, v = line.partition(b":")
        headers[k.decode("latin-1").strip().lower()] = v.decode("latin-1").strip()
    body = rest
    cl = headers.get("content-length")
    if cl and cl.isdigit():
        need = int(cl) - len(body)
        while need > 0:
            chunk = sock.recv(min(65536, need))
            if not chunk:
                break
            body += chunk
            need -= len(chunk)
    elif headers.get("transfer-encoding", "").lower() == "chunked":
        # simplistic: read until 0 chunk (best-effort)
        while b"\r\n0\r\n\r\n" not in body and not body.endswith(b"\r\n0\r\n\r\n"):
            chunk = sock.recv(65536)
            if not chunk:
                break
            body += chunk
        # de-chunk
        body = _dechunk(body)
        headers.pop("transfer-encoding", None)
    return header_blob + b"\r\n\r\n", body, headers


def _dechunk(data: bytes) -> bytes:
    out = b""
    i = 0
    while i < len(data):
        nl = data.find(b"\r\n", i)
        if nl < 0:
            break
        try:
            size = int(data[i:nl], 16)
        except ValueError:
            break
        i = nl + 2
        if size == 0:
            break
        out += data[i : i + size]
        i += size + 2
    return out


def _is_html_content_type(ctype: str) -> bool:
    return "text/html" in (ctype or "").lower()


def _is_text_asset_content_type(ctype: str) -> bool:
    """CSS/JS/JSON/SVG — decompress to plaintext under MITM; never HTML-inject."""
    c = (ctype or "").lower()
    if not c or "text/html" in c:
        return False
    return (
        "text/css" in c
        or "javascript" in c
        or "ecmascript" in c
        or "text/js" in c
        or "application/json" in c
        or "image/svg" in c
        or c.startswith("text/")
    )


def _rebuild_response(
    status_line: bytes,
    headers: dict[str, str],
    body: bytes,
    *,
    strip_encoding: bool = False,
) -> bytes:
    """Rebuild HTTP response with accurate Content-Length.

    Only strip Content-Encoding when the body was decompressed/rewritten
    (``strip_encoding=True``). Stripping encoding while leaving a gzip/br
    body intact makes Chromium treat CSS/JS as plaintext → unstyled B&W page.
    """
    headers = dict(headers)
    headers.pop("content-length", None)
    headers.pop("transfer-encoding", None)
    headers["content-length"] = str(len(body))
    if strip_encoding:
        headers.pop("content-encoding", None)
    parts = [status_line.rstrip(b"\r\n")]
    for k, v in headers.items():
        parts.append(f"{k}: {v}".encode("latin-1", "replace"))
    return b"\r\n".join(parts) + b"\r\n\r\n" + body


class MantisInjectProxy:
    def __init__(self, phone_index: int, *, upstream: str | None = None) -> None:
        self.phone_index = int(phone_index)
        self.listen_port = phone_inject_port(self.phone_index)
        self.upstream = (upstream or upstream_mode()).lower()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None
        # False when another process already owns the listen port (keepalive).
        # Adopted stubs must never enter _PROXIES — they publish connect=0 forever
        # and wipe the owner process's live counters from disk.
        self.owns_listener = False
        self.stats = {"connect": 0, "inject": 0, "tunnel": 0, "errors": 0}

    def start(self) -> bool:
        """Bind+serve this phone's inject port. Return True only when we own it."""
        _ca()[0]()  # ensure_ca_files — lazy: needs cryptography wheel
        # Drop pre-AKI leaf certs so Chromium stops CERTIFICATE_UNKNOWN on MITM.
        try:
            from automation.mantis_inject_ca import clear_host_cert_cache

            clear_host_cert_cache()
        except Exception:
            pass
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Do NOT set SO_REUSEADDR: on Windows it allows farm + watch_proxy to both
        # LISTEN on 8218+, and guest CONNECT randomly hits a dead/half peer → ads die.
        try:
            self._sock.bind(("127.0.0.1", self.listen_port))
        except OSError as exc:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
            # Bind failure is an adopt only when something is actually
            # accepting. A dead/half socket used to be treated as success and
            # the heal tick reported the phone armed.
            if inject_port_open(self.listen_port):
                self.owns_listener = False
                logger.info(
                    "Mantis inject proxy phone=%d port %d already bound — adopting existing listener (%s)",
                    self.phone_index,
                    self.listen_port,
                    exc,
                )
                return False
            raise
        self._sock.listen(64)
        self._sock.settimeout(1.0)
        self._thread = threading.Thread(
            target=self._serve,
            name=f"mantis-inject-{self.phone_index}",
            daemon=True,
        )
        self._thread.start()
        self.owns_listener = True
        logger.info(
            "Mantis inject proxy phone=%d listen=127.0.0.1:%d upstream=%s",
            self.phone_index,
            self.listen_port,
            self.upstream,
        )
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=3.0)

    def _upstream_connect(self, host: str, port: int) -> socket.socket:
        if self.upstream == "direct":
            return socket.create_connection((host, port), timeout=30.0)
        # Residential proxy — each phone gets unique IP from provider pool
        if self.upstream == "residential":
            from automation.residential_proxy import get_proxy_for_phone, connect_via_residential
            proxy = get_proxy_for_phone(self.phone_index)
            if proxy:
                self.stats["residential_proxy"] = int(self.stats.get("residential_proxy", 0)) + 1
                try:
                    return connect_via_residential(proxy, host, port)
                except OSError as exc:
                    logger.warning("residential proxy failed phone=%d host=%s: %s", self.phone_index, host, exc)
                    # Fall through to direct on proxy failure
            return socket.create_connection((host, port), timeout=30.0)
        # Billing traffic through Tor exits gets HTTP 406 — route via host IP
        if billing_direct_enabled() and _is_mantis_billing_host(host):
            self.stats["billing_direct"] = int(self.stats.get("billing_direct", 0)) + 1
            return socket.create_connection((host, port), timeout=30.0)
        # Tor mode for non-billing traffic (stealth)
        tor_port = upstream_tor_port(self.phone_index)
        return _connect_via_upstream_http_proxy("127.0.0.1", tor_port, host, port)

    def _serve(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                client, _addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target=self._handle_client,
                args=(client,),
                daemon=True,
            ).start()

    def _handle_client(self, client: socket.socket) -> None:
        try:
            head = _recv_until(client, b"\r\n\r\n")
            if not head:
                client.close()
                return
            method, target, _ver = _parse_request_line(head)
            if method == "CONNECT":
                self.stats["connect"] += 1
                host, port = _host_port_from_target(target, 443)
                if "bids.mantis.marketing" in (host or ""):
                    _beacon_note(f"click-connect phone={self.phone_index} host={host}")
                if mitm_enabled() and _is_dabflow_host(host) and port == 443:
                    self._handle_mitm(client, host, port, head)
                else:
                    self._handle_blind_connect(client, host, port)
            else:
                # Plain HTTP — rare; tunnel via upstream rewrite if needed
                self._handle_plain_http(client, head, method, target)
        except Exception as exc:
            self.stats["errors"] += 1
            logger.debug("inject proxy client error phone=%d: %s", self.phone_index, exc)
            try:
                client.close()
            except OSError:
                pass

    def _handle_blind_connect(self, client: socket.socket, host: str, port: int) -> None:
        try:
            remote = self._upstream_connect(host, port)
        except OSError as exc:
            client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            client.close()
            raise exc
        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        self.stats["tunnel"] += 1
        _tunnel(client, remote)

    def _handle_mitm(self, client: socket.socket, host: str, port: int, _head: bytes) -> None:
        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        ctx = _ca()[2](host)  # ssl_context_for_host — lazy import
        try:
            tls_client = ctx.wrap_socket(client, server_side=True)
        except ssl.SSLError as exc:
            self.stats["errors"] += 1
            logger.warning("MITM handshake failed host=%s: %s", host, exc)
            _beacon_note(f"handshake-fail phone={self.phone_index} host={host} {exc}")
            try:
                client.close()
            except OSError:
                pass
            return

        try:
            remote_raw = self._upstream_connect(host, port)
            remote = ssl.create_default_context().wrap_socket(remote_raw, server_hostname=host)
        except OSError as exc:
            self.stats["errors"] += 1
            tls_client.close()
            logger.warning("upstream TLS failed host=%s: %s", host, exc)
            return

        try:
            while True:
                req_head = _recv_until(tls_client, b"\r\n\r\n", limit=256_000)
                if not req_head:
                    break
                # Forward request (re-buffer body if Content-Length)
                method, target, _ = _parse_request_line(req_head)
                headers_part, _, rest = req_head.partition(b"\r\n\r\n")
                req_headers: dict[str, str] = {}
                for line in headers_part.split(b"\r\n")[1:]:
                    if b":" in line:
                        k, _, v = line.partition(b":")
                        req_headers[k.decode("latin-1").lower().strip()] = v.decode(
                            "latin-1"
                        ).strip()
                body = rest
                cl = req_headers.get("content-length")
                if cl and cl.isdigit():
                    need = int(cl) - len(body)
                    while need > 0:
                        chunk = tls_client.recv(min(65536, need))
                        if not chunk:
                            break
                        body += chunk
                        need -= len(chunk)
                if method == "POST" and "__pharmflow_viewed" in target:
                    _store_viewed_beacon(self.phone_index, body)
                    tls_client.sendall(
                        b"HTTP/1.1 204 No Content\r\n"
                        b"Content-Length: 0\r\n"
                        b"Connection: keep-alive\r\n\r\n"
                    )
                    continue
                # Chromium on MuMu often has no DevTools — rewrite Client Hints here.
                # Strip brotli. We cannot rewrite br HTML, so the phone never gets
                # the click-beacon script and Path3 has no token to open.
                if _is_dabflow_host(host):
                    req_headers["accept-encoding"] = "gzip, identity"
                    hints = _client_hints_for_phone(self.phone_index)
                    if hints:
                        req_headers = _apply_client_hints_headers(req_headers, hints)
                        self.stats["client_hints"] = int(self.stats.get("client_hints", 0)) + 1
                    status_line = headers_part.split(b"\r\n", 1)[0]
                    remote.sendall(_rebuild_request(status_line, req_headers, body))
                else:
                    remote.sendall(headers_part + b"\r\n\r\n" + body)

                resp_head, resp_body, resp_headers = _read_http_message(remote)
                status_line = resp_head.split(b"\r\n", 1)[0]
                ctype = resp_headers.get("content-type", "")
                encoding = resp_headers.get("content-encoding", "").lower()
                if method == "GET" and _is_html_content_type(ctype) and resp_body:
                    decompressed, enc_left = _maybe_decompress(resp_body, encoding)
                    if enc_left in ("", "identity"):
                        new_body = _inject_html(decompressed)
                        if new_body is not decompressed and len(new_body) != len(
                            decompressed
                        ):
                            self.stats["inject"] += 1
                            logger.info(
                                "injected Mantis JS phone=%d host=%s bytes=%d→%d",
                                self.phone_index,
                                host,
                                len(decompressed),
                                len(new_body),
                            )
                        # Inline inject must run or the viewed-click beacon never
                        # posts. A page CSP that blocks script tags drops Path3.
                        resp_headers.pop("content-security-policy", None)
                        resp_headers.pop("content-security-policy-report-only", None)
                        # HTML rewritten — always serve uncompressed plaintext.
                        out = _rebuild_response(
                            status_line,
                            resp_headers,
                            new_body,
                            strip_encoding=True,
                        )
                        tls_client.sendall(out)
                    else:
                        self.stats["inject_skipped_encoding"] = (
                            int(self.stats.get("inject_skipped_encoding", 0)) + 1
                        )
                        logger.warning(
                            "inject skipped phone=%d host=%s encoding=%s",
                            self.phone_index,
                            host,
                            encoding,
                        )
                        out = _rebuild_response(
                            status_line,
                            resp_headers,
                            resp_body,
                            strip_encoding=False,
                        )
                        tls_client.sendall(out)
                elif method == "GET" and _is_text_asset_content_type(ctype) and resp_body:
                    # CSS/JS/etc: decompress to plaintext so Content-Encoding can
                    # never disagree with the body (root cause of B&W unstyled pages).
                    # Never HTML-inject these.
                    decompressed, enc_left = _maybe_decompress(resp_body, encoding)
                    if enc_left in ("", "identity"):
                        out = _rebuild_response(
                            status_line,
                            resp_headers,
                            decompressed,
                            strip_encoding=True,
                        )
                    else:
                        out = _rebuild_response(
                            status_line,
                            resp_headers,
                            resp_body,
                            strip_encoding=False,
                        )
                    tls_client.sendall(out)
                else:
                    # Binary images/fonts/etc: rebuild length after possible dechunk,
                    # keep Content-Encoding matching compressed body.
                    out = _rebuild_response(
                        status_line,
                        resp_headers,
                        resp_body,
                        strip_encoding=False,
                    )
                    tls_client.sendall(out)
                if req_headers.get("connection", "").lower() == "close":
                    break
                if resp_headers.get("connection", "").lower() == "close":
                    break
        except OSError:
            self.stats["errors"] += 1
        finally:
            for s in (tls_client, remote):
                try:
                    s.close()
                except OSError:
                    pass

    def _handle_plain_http(
        self, client: socket.socket, head: bytes, method: str, target: str
    ) -> None:
        # Absolute-form URL expected from phone http_proxy
        try:
            if target.startswith("http://"):
                u = urlparse(target)
                host = u.hostname or ""
                port = u.port or 80
            else:
                # host header
                host, port = "", 80
                for line in head.split(b"\r\n")[1:]:
                    if line.lower().startswith(b"host:"):
                        host, port = _host_port_from_target(
                            line.split(b":", 1)[1].decode().strip(), 80
                        )
                        break
            if not host:
                client.close()
                return
            # Tor HTTPTunnel expects absolute-form on :80. Residential/direct must
            # NOT be forcibly rewritten onto Tor (that discarded the chosen upstream).
            if self.upstream == "tor" and port == 80:
                tor_port = upstream_tor_port(self.phone_index)
                remote = socket.create_connection(("127.0.0.1", tor_port), timeout=30)
                remote.sendall(head)
                _tunnel(client, remote)
                return
            remote = self._upstream_connect(host, port)
            remote.sendall(head)
            _tunnel(client, remote)
        except OSError:
            self.stats["errors"] += 1
            try:
                client.close()
            except OSError:
                pass


_PROXIES: dict[int, MantisInjectProxy] = {}
_LOCK = threading.Lock()
_STATS_THREAD: "threading.Thread | None" = None


def _stats_publish_loop() -> None:
    """Heartbeat the shared inject stats file while any proxy is owned here.

    The standalone runner published these counters in its own loop, but the farm
    owns inject in-process — without this loop the shared stats file goes stale
    (or worse, keeps the last dead runner's zeros) and every monitor reads
    nothing. Publishes every 30s while proxies exist; exits when the owner is
    gone so a stale snapshot can't masquerade as live.
    """
    while True:
        with _LOCK:
            proxies = list(_PROXIES.values())
        if not proxies:
            return
        try:
            _publish_inject_stats(proxies)
        except Exception:  # noqa: BLE001 — monitoring must never break serving
            pass
        time.sleep(30.0)


def _ensure_stats_publisher() -> None:
    global _STATS_THREAD
    if _STATS_THREAD is not None and _STATS_THREAD.is_alive():
        return
    _STATS_THREAD = threading.Thread(
        target=_stats_publish_loop, name="inject-stats-publish", daemon=True
    )
    _STATS_THREAD.start()


def start_inject_proxies(phone_indices: list[int] | None = None) -> list[MantisInjectProxy]:
    idxs = phone_indices if phone_indices is not None else list(range(5))
    out: list[MantisInjectProxy] = []
    with _LOCK:
        for i in idxs:
            existing = _PROXIES.get(i)
            if (
                existing is not None
                and getattr(existing, "owns_listener", False)
                and inject_port_open(existing.listen_port)
            ):
                out.append(existing)
                continue
            if existing is not None:
                try:
                    existing.stop()
                except Exception:
                    pass
                _PROXIES.pop(i, None)
            p = MantisInjectProxy(i)
            try:
                owned = p.start()
            except OSError as exc:
                logger.warning(
                    "inject listen failed phone=%s port=%s: %s",
                    i,
                    p.listen_port,
                    exc,
                )
                continue
            # Another process (keepalive) owns the port — leave _PROXIES empty
            # so we do not publish zero counters over the owner's live stats.
            if not owned or not getattr(p, "owns_listener", False):
                if inject_port_open(p.listen_port):
                    logger.info(
                        "inject port %s owned elsewhere — not registering zero-stat stub phone=%s",
                        p.listen_port,
                        i,
                    )
                continue
            if not inject_port_open(p.listen_port):
                logger.warning(
                    "inject not accepting phone=%s port=%s after start",
                    i,
                    p.listen_port,
                )
                try:
                    p.stop()
                except Exception:
                    pass
                continue
            _PROXIES[i] = p
            out.append(p)
    _ensure_stats_publisher()
    return out


def stop_inject_proxies() -> None:
    with _LOCK:
        for p in list(_PROXIES.values()):
            p.stop()
        _PROXIES.clear()


def verify_reverse_tunnel(adb: object, serial: str, port: int) -> bool:
    """True when adb reverse tcp:<port> tcp:<port> exists for this serial.

    ADB server restarts destroy all reverse tunnels.  When that happens the
    phone still has http_proxy=127.0.0.1:<port> but traffic goes to the phone's
    own localhost (nothing there) instead of the host inject proxy.  This kills
    every impression and click because the traffic never reaches Mantis.
    """
    try:
        result = adb.run("reverse", "--list", serial=serial, timeout=8.0)  # type: ignore[attr-defined]
        needle = f"tcp:{port}"
        for line in (result.stdout or "").splitlines():
            if needle in line:
                return True
    except Exception:
        pass
    return False


def point_phone_at_inject(adb: object, serial: str, phone_index: int) -> str:
    """adb reverse + http_proxy -> inject port.  Verifies tunnel exists."""
    port = phone_inject_port(phone_index)
    # Always (re)establish reverse tunnel -- ADB server restarts destroy them.
    adb.run("reverse", f"tcp:{port}", f"tcp:{port}", serial=serial, timeout=10.0)  # type: ignore[attr-defined]
    # Verify it actually landed -- if not, retry once after a brief pause.
    if not verify_reverse_tunnel(adb, serial, port):
        logger.warning("reverse tunnel missing after setup port=%d serial=%s -- retrying", port, serial)
        time.sleep(1.0)
        adb.run("reverse", f"tcp:{port}", f"tcp:{port}", serial=serial, timeout=10.0)  # type: ignore[attr-defined]
        if not verify_reverse_tunnel(adb, serial, port):
            logger.warning(
                "reverse tunnel still missing after retry port=%d serial=%s",
                port,
                serial,
            )
    adb.set_http_proxy("127.0.0.1", port, serial=serial)  # type: ignore[attr-defined]
    return f"127.0.0.1:{port}"

def _device_has_inject_ca(adb: object, serial: str) -> bool:
    """True when the guest already trusts the inject CA (fast probe, no reinstall)."""
    try:
        from pathlib import Path

        from automation.mantis_inject_ca import (
            CA_CERT,
            android_cacert_hash,
            ensure_ca_files,
        )
        from cryptography import x509

        ensure_ca_files()
        cert_path = Path(CA_CERT)
        if not cert_path.is_file():
            # Dual-read legacy roots (branding rename).
            for cand in (
                Path(r"C:\PharmFlow\certs\mantis_inject\ca.cert.pem"),
                Path(r"C:\CPharm\certs\mantis_inject\ca.cert.pem"),
            ):
                if cand.is_file():
                    cert_path = cand
                    break
            else:
                return False
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        name = f"{android_cacert_hash(cert)}.0"
    except Exception:
        return False
    try:
        # Prefer apex when present (Android 14+ WebView). Group tests so a
        # missing system file does not short-circuit the apex probe wrongly.
        verify = adb.shell(  # type: ignore[attr-defined]
            f"(test -f /apex/com.android.conscrypt/cacerts/{name} && echo PRESENT) || "
            f"(test -f /system/etc/security/cacerts/{name} && echo PRESENT)",
            serial=serial,
            timeout=8,
        )
        return "PRESENT" in (getattr(verify, "stdout", "") or "")
    except Exception:
        return False


def ensure_inject_for_phone(
    adb: object,
    serial: str,
    phone_index: int,
    *,
    install_ca: bool = True,
) -> dict:
    """Bind the inject listener, pin the guest, and (by default) install the CA.

    ``ok`` is True only when the listener accepts and, if ``install_ca``, the
    CA is on the guest. A swallowed exception used to return ``ok: True`` with
    a dead port — the heal tick then thought the phone was armed.
    ``install_ca`` stays True by default (CERTIFICATE_UNKNOWN root cause).
    """
    port = phone_inject_port(phone_index)
    if not inject_enabled():
        return {
            "ok": False,
            "skipped": True,
            "reason": "disabled",
            "ca_installed": False,
            "port": port,
        }
    try:
        start_inject_proxies([phone_index])
    except Exception as exc:
        logger.warning(
            "inject start failed serial=%s phone=%s: %s", serial, phone_index, exc
        )
        return {
            "ok": False,
            "endpoint": "",
            "ca_installed": False,
            "port": port,
            "error": f"start:{exc}",
        }
    listening = inject_port_open(port)
    ca_ok = True
    if install_ca:
        if _device_has_inject_ca(adb, serial):
            ca_ok = True
        else:
            try:
                ca_ok = bool(_ca()[1](adb, serial))  # install_ca_on_device — lazy import
            except Exception as exc:
                logger.warning("CA install failed serial=%s: %s", serial, exc)
                ca_ok = False
    if not listening:
        return {
            "ok": False,
            "endpoint": "",
            "ca_installed": ca_ok,
            "port": port,
            "error": "inject_listener_down",
        }
    try:
        endpoint = point_phone_at_inject(adb, serial, phone_index)
    except Exception as exc:
        logger.warning("inject pin failed serial=%s: %s", serial, exc)
        return {
            "ok": False,
            "endpoint": "",
            "ca_installed": ca_ok,
            "port": port,
            "error": f"pin:{exc}",
        }
    if install_ca and not ca_ok:
        return {
            "ok": False,
            "endpoint": endpoint,
            "ca_installed": False,
            "port": port,
            "error": "ca_install_failed",
        }
    return {
        "ok": True,
        "endpoint": endpoint,
        "ca_installed": ca_ok,
        "port": port,
    }
