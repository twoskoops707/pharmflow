"""Residential proxy pool manager.

Reads proxies from C:\\CPharm\\config\\residential_proxies.txt
Format per line: host:port:user:pass   OR   host:port

Assigns a UNIQUE proxy to each phone index. Rotates on identity change.
Falls back to next proxy in pool if current one fails health check.
"""

from __future__ import annotations

import base64
import logging
import os
import socket
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

PROXY_LIST_PATH = Path(os.environ.get(
    "CPHARM_RESIDENTIAL_PROXY_LIST",
    r"C:\CPharm\config\residential_proxies.txt",
))

# Minimum seconds between health checks for the same proxy
HEALTH_CHECK_INTERVAL = 60.0
HEALTH_CHECK_TIMEOUT = 5.0


class _ProxyEntry:
    __slots__ = ("host", "port", "user", "password", "last_health_ok", "last_health_check", "failures")

    def __init__(self, host: str, port: int, user: str = "", password: str = "") -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.last_health_ok = False
        self.last_health_check = 0.0
        self.failures = 0

    def is_healthy(self) -> bool:
        """Return True if proxy is known good or hasn't been checked recently."""
        now = time.time()
        if self.failures >= 3:
            # Too many failures — need a fresh health check
            if now - self.last_health_check < HEALTH_CHECK_INTERVAL:
                return False
        return self.last_health_ok or (now - self.last_health_check > HEALTH_CHECK_INTERVAL)

    def mark_ok(self) -> None:
        self.last_health_ok = True
        self.last_health_check = time.time()
        self.failures = 0

    def mark_fail(self) -> None:
        self.last_health_ok = False
        self.last_health_check = time.time()
        self.failures += 1

    @property
    def has_auth(self) -> bool:
        return bool(self.user and self.password)

    @property
    def proxy_url(self) -> str:
        if self.has_auth:
            return f"http://{self.user}:{self.password}@{self.host}:{self.port}"
        return f"http://{self.host}:{self.port}"

    def __repr__(self) -> str:
        return f"Proxy({self.host}:{self.port})"


class ResidentialProxyPool:
    """Thread-safe proxy pool that assigns unique proxies per phone."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proxies: list[_ProxyEntry] = []
        self._assignments: dict[int, int] = {}  # phone_index -> proxy index
        self._load_counter = 0
        self._loaded_path: Path | None = None
        self._loaded_mtime: float = 0.0

    def _ensure_loaded(self) -> None:
        """Load proxy list if not yet loaded or file changed."""
        if not PROXY_LIST_PATH.is_file():
            if self._load_counter == 0:
                logger.warning("Residential proxy list not found: %s", PROXY_LIST_PATH)
            self._load_counter += 1
            return

        try:
            mtime = PROXY_LIST_PATH.stat().st_mtime
        except OSError:
            return

        # Must compare mtime — operators edit the list while the farm runs.
        if (
            self._loaded_path == PROXY_LIST_PATH
            and self._load_counter > 0
            and mtime == self._loaded_mtime
        ):
            return  # Already loaded and unchanged

        proxies: list[_ProxyEntry] = []
        try:
            for line in PROXY_LIST_PATH.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # host:port[:user[:password...]] — password may contain ':'
                parts = line.split(":")
                if len(parts) >= 2:
                    host = parts[0].strip()
                    try:
                        port = int(parts[1].strip())
                    except ValueError:
                        continue
                    user = parts[2].strip() if len(parts) > 2 else ""
                    pw = ":".join(parts[3:]).strip() if len(parts) > 3 else ""
                    proxies.append(_ProxyEntry(host, port, user, pw))
        except OSError as exc:
            logger.error("Failed to read proxy list %s: %s", PROXY_LIST_PATH, exc)
            return

        if proxies:
            with self._lock:
                self._proxies = proxies
                self._loaded_path = PROXY_LIST_PATH
                self._loaded_mtime = mtime
                self._load_counter += 1
                # Drop assignments that point past the new list length.
                self._assignments = {
                    phone: idx
                    for phone, idx in self._assignments.items()
                    if idx < len(proxies)
                }
            logger.info("Loaded %d residential proxies from %s", len(proxies), PROXY_LIST_PATH)

    @property
    def proxy_count(self) -> int:
        self._ensure_loaded()
        return len(self._proxies)

    def get_proxy_for_phone(self, phone_index: int) -> _ProxyEntry | None:
        """Get the currently assigned proxy for a phone, or assign a new one."""
        self._ensure_loaded()
        with self._lock:
            if not self._proxies:
                return None

            # If phone already has an assigned proxy and it's healthy, return it
            assigned_idx = self._assignments.get(phone_index)
            if assigned_idx is not None and assigned_idx < len(self._proxies):
                proxy = self._proxies[assigned_idx]
                if proxy.is_healthy():
                    return proxy

            # Find a proxy that's healthy and not yet assigned to another phone
            assigned_set = set(self._assignments.values())
            for i, proxy in enumerate(self._proxies):
                if proxy.is_healthy() and i not in assigned_set:
                    self._assignments[phone_index] = i
                    return proxy

            # All assigned — find least-failed proxy and reassign
            best_idx = min(
                range(len(self._proxies)),
                key=lambda i: self._proxies[i].failures,
            )
            self._assignments[phone_index] = best_idx
            return self._proxies[best_idx]

    def rotate_proxy_for_phone(self, phone_index: int) -> _ProxyEntry | None:
        """Force rotate to a new proxy for this phone."""
        self._ensure_loaded()
        with self._lock:
            if not self._proxies:
                return None

            # Mark current proxy as used for this phone
            old_idx = self._assignments.get(phone_index)
            assigned_set = set(self._assignments.values())

            # Find next healthy proxy not assigned elsewhere
            start = (old_idx + 1) if old_idx is not None else 0
            for offset in range(len(self._proxies)):
                idx = (start + offset) % len(self._proxies)
                proxy = self._proxies[idx]
                if proxy.is_healthy() and idx not in assigned_set:
                    self._assignments[phone_index] = idx
                    return proxy

            # Fallback: least failures
            best_idx = min(
                range(len(self._proxies)),
                key=lambda i: self._proxies[i].failures,
            )
            self._assignments[phone_index] = best_idx
            return self._proxies[best_idx]

    def mark_proxy_ok(self, proxy: _ProxyEntry) -> None:
        proxy.mark_ok()

    def mark_proxy_failed(self, proxy: _ProxyEntry) -> None:
        proxy.mark_fail()


# Module-level singleton
_pool = ResidentialProxyPool()


def get_proxy_for_phone(phone_index: int) -> _ProxyEntry | None:
    """Public API: get the assigned residential proxy for a phone."""
    return _pool.get_proxy_for_phone(phone_index)


def rotate_proxy_for_phone(phone_index: int) -> _ProxyEntry | None:
    """Public API: force rotate to a new proxy."""
    return _pool.rotate_proxy_for_phone(phone_index)


def mark_proxy_ok(proxy: _ProxyEntry) -> None:
    _pool.mark_proxy_ok(proxy)


def mark_proxy_failed(proxy: _ProxyEntry) -> None:
    _pool.mark_proxy_failed(proxy)


def connect_via_residential(proxy: _ProxyEntry, dest_host: str, dest_port: int, timeout: float = 30.0) -> socket.socket:
    """Open a connection through a residential proxy via HTTP CONNECT tunnel."""
    sock = socket.create_connection((proxy.host, proxy.port), timeout=timeout)

    # Build CONNECT request with optional proxy auth
    auth_header = ""
    if proxy.has_auth:
        creds = base64.b64encode(f"{proxy.user}:{proxy.password}".encode()).decode()
        auth_header = f"Proxy-Authorization: Basic {creds}\r\n"

    req = (
        f"CONNECT {dest_host}:{dest_port} HTTP/1.1\r\n"
        f"Host: {dest_host}:{dest_port}\r\n"
        f"{auth_header}"
        f"Proxy-Connection: keep-alive\r\n"
        f"\r\n"
    ).encode("ascii")

    sock.sendall(req)

    # Read response
    resp = b""
    while b"\r\n\r\n" not in resp and len(resp) < 4096:
        chunk = sock.recv(4096)
        if not chunk:
            sock.close()
            raise OSError(f"Residential proxy {proxy.host}:{proxy.port} closed before responding")
        resp += chunk

    status_line = resp.split(b"\r\n", 1)[0]
    # Proxies often reply "HTTP/1.1 200" or "HTTP/1.0 200 Connection established"
    # — requiring a trailing space after 200 rejected the bare "… 200" form.
    parts = status_line.split()
    ok = len(parts) >= 2 and parts[1] == b"200"
    if ok:
        proxy.mark_ok()
        return sock
    else:
        proxy.mark_fail()
        sock.close()
        raise OSError(f"Residential proxy CONNECT failed ({proxy.host}:{proxy.port}): {status_line!r}")


def get_pool_stats() -> dict:
    """Return pool stats for monitoring."""
    return {
        "total_proxies": _pool.proxy_count,
        "assignments": dict(_pool._assignments) if _pool._assignments else {},
    }
