"""Tor control — detection, per-phone HTTPTunnelPort, adb reverse, identity rotation."""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import random
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import automation.no_window  # noqa: F401  — CREATE_NO_WINDOW for every Popen child
from automation.adb_paths import adb_executable
from automation.adb_wrapper import AdbWrapper
from automation.browser_adb import browser_pkg_for_clear
from automation.config import (
    REC_DIR,
    TOR_DIR,
    TOR_HTTP_TUNNEL_BASE,
    TOR_SOCKS_BASE,
    UNIQUE_EXIT_IP_RETRIES,
    is_proxy_legacy_gateway,
    is_skip_exit_proxy_clear,
    require_unique_exit_ip,
    tor_config_path,
    tor_data_path,
)
from automation.win_subprocess import hidden_run_kwargs, hide_console_burst
from wizard.wizard_paths import app_data_root, bundled_dir, bundle_root, logs_dir, tor_binary_path

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)
log = logger

GUEST_PROXY_HOST = "127.0.0.1"
_IP_CHECK_URLS = (
    "https://checkip.amazonaws.com/",
    "https://api.ipify.org/",
    "https://icanhazip.com/",
)
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_exit_ip_lock = threading.RLock()
# Serialize claim checks so two phones cannot accept the same exit IP.
_exit_ip_claim_lock = threading.RLock()
# phone_index -> last verified exit IP for this farm run
_last_exit_ip: dict[int, str] = {}
# phone_index -> currently held exit IP (concurrent farm phones)
_in_use_exit_ip: dict[int, str] = {}
# Recent exit IPs farm-wide (blocks reuse across phones/seqs for a while).
_RECENT_EXIT_IP_MAX = 60
_recent_exit_ips: list[str] = []

# Common Tor Browser + Expert Bundle install locations (Windows)
TOR_SEARCH_PATHS: list[Path] = [
    Path(r"C:\CPharm\bundled\tor.exe"),
    bundled_dir() / "tor.exe",
    Path(r"C:\PharmFlow\bundled\tor.exe"),
    bundle_root() / "bundled" / "tor.exe",
    bundle_root() / "tor" / "tor.exe",
    app_data_root() / "tor" / "tor.exe",
    Path(os.environ.get("CPHARM_TOR_PATH") or os.environ.get("PHARMFLOW_TOR_PATH") or ""),
    Path(r"C:\Tor\tor.exe"),
    Path(r"C:\Program Files\Tor\tor.exe"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Tor Browser" / "Browser" / "TorBrowser" / "Tor" / "tor.exe",
    Path(os.environ.get("PROGRAMFILES", "")) / "Tor Browser" / "Browser" / "TorBrowser" / "Tor" / "tor.exe",
    Path(os.environ.get("USERPROFILE", "")) / "Desktop" / "Tor Browser" / "Browser" / "TorBrowser" / "Tor" / "tor.exe",
    Path(os.environ.get("USERPROFILE", "")) / "Downloads" / "tor-win64-" / "tor" / "tor.exe",
]


class TorInstallKind(str, Enum):
    BUNDLED = "bundled"
    EXPERT_BUNDLE = "expert_bundle"
    TOR_BROWSER = "tor_browser"
    ENV_PATH = "env_path"
    UNKNOWN = "unknown"


@dataclass
class TorInstall:
    """A discovered Tor binary on the host."""

    path: Path
    kind: TorInstallKind
    label: str = ""

    @property
    def exists(self) -> bool:
        return self.path.is_file()


@dataclass
class TorInstance:
    """A running Tor process for one phone."""

    phone_index: int
    http_port: int
    socks_port: int
    config_path: Path
    process: subprocess.Popen[bytes] | None = None
    control_port: int = 0

    def __post_init__(self) -> None:
        if not self.control_port:
            self.control_port = phone_control_port(self.phone_index)

    @property
    def guest_proxy_host(self) -> str:
        return GUEST_PROXY_HOST

    @property
    def guest_proxy_port(self) -> int:
        """Port inside emulator — http_proxy 127.0.0.1:<port> via adb reverse."""
        return self.http_port

    @property
    def guest_proxy(self) -> str:
        return f"{GUEST_PROXY_HOST}:{self.http_port}"

    @property
    def host_proxy_url(self) -> str:
        return f"http://127.0.0.1:{self.http_port}"


@dataclass
class TorPhoneStatus:
    phone_index: int
    http_port: int
    socks_port: int
    running: bool
    http_tunnel_enabled: bool
    guest_proxy: str
    reverse_configured: bool
    failures: list[str] = field(default_factory=list)
    exit_ip: str = ""
    control_port: int = 0

    @property
    def ok(self) -> bool:
        return self.running and self.http_tunnel_enabled and not self.failures


@dataclass
class ExitIpRotateResult:
    ok: bool
    before: str
    after: str
    changed: bool
    retries: int
    phone_index: int
    error: str = ""
    avoided_collision: bool = False

    def log_line(self) -> str:
        changed = "yes" if self.changed else "no"
        return (
            f"IP before={self.before or '?'} after={self.after or '?'} "
            f"changed={changed} retries={self.retries}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "before": self.before,
            "after": self.after,
            "changed": self.changed,
            "retries": self.retries,
            "phone_index": self.phone_index,
            "error": self.error,
            "avoided_collision": self.avoided_collision,
        }


def _slot_index(phone_index: int) -> int:
    """Fleet slot for an absolute phone index (farm export or live-roster scan).

    Tor lanes are prewarmed for slots 0..N-1 at the runtime base; dialing
    base+absolute_idx (39 -> 8157) hit nobody when the fleet is vm39+ — the
    2026-09-13 split-brain. Precedence: the farm's slot map exported at arm
    time (CPHARM_/PHARMFLOW_INJECT_SLOT_MAP), then the live serial map/config scan
    (same rule as mantis_inject_proxy._fleet_slot), then the absolute idx.
    """
    idx = int(phone_index)
    raw = (
        os.environ.get("CPHARM_INJECT_SLOT_MAP")
        or os.environ.get("PHARMFLOW_INJECT_SLOT_MAP")
        or ""
    )
    if raw.strip():
        try:
            m = json.loads(raw)
            val = m.get(str(idx))
            if val is not None:
                return int(val)
        except Exception:
            pass
    try:
        names: list[str] = []
        for logs_dir in _logs_dirs_for_bases():
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
        idxs = sorted(int(mm.group(1)) for n in names if (mm := re.match(r"^vm(\d+)\.", n)))
        if idxs and idx in idxs:
            return idxs.index(idx)
    except Exception:
        pass
    return idx


def phone_http_port(phone_index: int) -> int:
    """Per-phone HTTPTunnelPort — slot-based so high-index fleets dial a live lane."""
    # Looked up at call time so the shifted base assigned later in this module applies.
    return int(globals().get("HTTP_TUNNEL_BASE", TOR_HTTP_TUNNEL_BASE)) + _slot_index(phone_index)


def phone_socks_port(phone_index: int) -> int:
    """Per-phone SocksPort — slot-based, same rule as HTTP (split-brain fix)."""
    return int(globals().get("BASE_PORT", TOR_SOCKS_BASE)) + _slot_index(phone_index)


def phone_control_port(phone_index: int) -> int:
    """Per-phone ControlPort for SIGNAL NEWNYM — slot-based, same rule as HTTP/SOCKS."""
    base = int(globals().get("BASE_PORT", TOR_SOCKS_BASE))
    return base + 1000 + _slot_index(phone_index)


def guest_proxy_endpoint(phone_index: int) -> str:
    """Proxy string set on the Android guest via http_proxy."""
    return f"{GUEST_PROXY_HOST}:{phone_http_port(phone_index)}"


def _parse_public_ip(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    m = _IPV4_RE.search(raw)
    if not m:
        return ""
    candidate = m.group(0)
    try:
        addr = ipaddress.ip_address(candidate)
    except ValueError:
        return ""
    if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
        return ""
    return candidate


def _exit_ip_store_path() -> Path:
    try:
        return logs_dir() / "farm_exit_ips.json"
    except Exception:
        return app_data_root() / "logs" / "farm_exit_ips.json"


def _persist_exit_ips() -> None:
    path = _exit_ip_store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "last": {str(k): v for k, v in _last_exit_ip.items()},
            "in_use": {str(k): v for k, v in _in_use_exit_ip.items()},
            "recent": list(_recent_exit_ips[-_RECENT_EXIT_IP_MAX:]),
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.debug("exit-ip persist failed: %s", exc)


def _load_exit_ips() -> None:
    path = _exit_ip_store_path()
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return
    if not isinstance(data, dict):
        return
    with _exit_ip_lock:
        for key, val in (data.get("last") or {}).items():
            try:
                idx = int(key)
            except (TypeError, ValueError):
                continue
            ip = str(val or "").strip()
            if ip:
                _last_exit_ip[idx] = ip
        for key, val in (data.get("in_use") or {}).items():
            try:
                idx = int(key)
            except (TypeError, ValueError):
                continue
            ip = str(val or "").strip()
            if ip:
                _in_use_exit_ip[idx] = ip
        recent = data.get("recent") or []
        if isinstance(recent, list):
            cleaned = [str(x).strip() for x in recent if str(x or "").strip()]
        else:
            cleaned = []
        if not cleaned:
            cleaned = [
                ip
                for ip in list(_last_exit_ip.values()) + list(_in_use_exit_ip.values())
                if ip
            ]
        if cleaned:
            # Preserve order, drop dupes.
            seen: set[str] = set()
            ordered: list[str] = []
            for ip in cleaned:
                if ip not in seen:
                    seen.add(ip)
                    ordered.append(ip)
            _recent_exit_ips.clear()
            _recent_exit_ips.extend(ordered[-_RECENT_EXIT_IP_MAX:])


def get_last_exit_ip(phone_index: int) -> str:
    with _exit_ip_lock:
        if not _last_exit_ip:
            _load_exit_ips()
        return _last_exit_ip.get(phone_index, "")


def get_in_use_exit_ips(*, exclude_phone: int | None = None) -> set[str]:
    with _exit_ip_lock:
        if not _last_exit_ip and not _in_use_exit_ip:
            _load_exit_ips()
        return {
            ip
            for idx, ip in _in_use_exit_ip.items()
            if ip and (exclude_phone is None or idx != exclude_phone)
        }


def remember_exit_ip(phone_index: int, exit_ip: str) -> None:
    if not exit_ip:
        return
    with _exit_ip_lock:
        _last_exit_ip[phone_index] = exit_ip
        _in_use_exit_ip[phone_index] = exit_ip
        if not _recent_exit_ips or _recent_exit_ips[-1] != exit_ip:
            _recent_exit_ips.append(exit_ip)
            del _recent_exit_ips[:-_RECENT_EXIT_IP_MAX]
        _persist_exit_ips()
    # Always emit on root so farm_354.log captures uniqueness proof even if
    # module loggers are mis-configured.
    logging.getLogger("farm_354").info(
        "phone=%d IP remembered after=%s", phone_index, exit_ip
    )


def try_claim_exit_ip(phone_index: int, exit_ip: str, *, before: str = "") -> tuple[bool, str]:
    """Atomically claim exit_ip if unique vs this phone's last + other/recent farm IPs.

    Returns (ok, reason). reason is '' on success.
    """
    if not exit_ip:
        return False, "empty exit ip"
    with _exit_ip_claim_lock:
        with _exit_ip_lock:
            _load_exit_ips()
            own_last = _last_exit_ip.get(phone_index, "") or before
            if own_last and exit_ip == own_last:
                return False, "same as this phone last"
            forbidden: set[str] = set()
            for idx, ip in _in_use_exit_ip.items():
                if ip and idx != phone_index:
                    forbidden.add(ip)
            for idx, ip in _last_exit_ip.items():
                if ip and idx != phone_index:
                    forbidden.add(ip)
            for ip in _recent_exit_ips:
                if ip and ip != own_last:
                    forbidden.add(ip)
            if exit_ip in forbidden:
                return False, "collides with other phone or recent farm IP"
            _last_exit_ip[phone_index] = exit_ip
            _in_use_exit_ip[phone_index] = exit_ip
            if not _recent_exit_ips or _recent_exit_ips[-1] != exit_ip:
                _recent_exit_ips.append(exit_ip)
                del _recent_exit_ips[:-_RECENT_EXIT_IP_MAX]
            _persist_exit_ips()
    logging.getLogger("farm_354").info(
        "phone=%d IP claimed after=%s (unique farm-wide)", phone_index, exit_ip
    )
    return True, ""


def release_exit_ip(phone_index: int) -> None:
    with _exit_ip_lock:
        _in_use_exit_ip.pop(phone_index, None)
        _persist_exit_ips()


def _classify_tor_path(path: Path) -> TorInstallKind:
    parts = {p.lower() for p in path.parts}
    if "tor browser" in " ".join(path.parts).lower():
        return TorInstallKind.TOR_BROWSER
    if "bundled" in parts or path.parent.name == "tor":
        return TorInstallKind.BUNDLED
    if os.environ.get("PHARMFLOW_TOR_PATH") and str(path) == os.environ.get("PHARMFLOW_TOR_PATH"):
        return TorInstallKind.ENV_PATH
    if "tor-win" in path.as_posix().lower():
        return TorInstallKind.EXPERT_BUNDLE
    return TorInstallKind.UNKNOWN


def discover_tor_installations() -> list[TorInstall]:
    """Find Tor Browser or Expert Bundle tor.exe on this machine."""
    found: list[TorInstall] = []
    seen: set[str] = set()

    def add(path: Path, label: str = "") -> None:
        if not path or not path.is_file():
            return
        key = str(path.resolve())
        if key in seen:
            return
        seen.add(key)
        found.append(
            TorInstall(
                path=path,
                kind=_classify_tor_path(path),
                label=label or path.parent.name,
            )
        )

    for candidate in TOR_SEARCH_PATHS:
        add(candidate)

    # Expert Bundle: search Downloads and Program Files for tor-win*
    for root in (
        Path(os.environ.get("USERPROFILE", "")) / "Downloads",
        Path(os.environ.get("PROGRAMFILES", "")),
        Path(os.environ.get("PROGRAMFILES(X86)", "")),
    ):
        if not root.is_dir():
            continue
        for child in root.glob("tor-win*"):
            add(child / "tor" / "tor.exe", label=child.name)
        for child in root.glob("**/tor.exe"):
            if "tor browser" in str(child).lower():
                add(child)

    return found


def detect_tor() -> TorInstall | None:
    """Return the best available Tor binary (bundled first, then system installs)."""
    installs = discover_tor_installations()
    if not installs:
        fallback = tor_binary_path()
        return TorInstall(path=fallback, kind=TorInstallKind.BUNDLED) if fallback.is_file() else None
    priority = {
        TorInstallKind.BUNDLED: 0,
        TorInstallKind.ENV_PATH: 1,
        TorInstallKind.EXPERT_BUNDLE: 2,
        TorInstallKind.TOR_BROWSER: 3,
        TorInstallKind.UNKNOWN: 4,
    }
    installs.sort(key=lambda i: priority.get(i.kind, 99))
    return installs[0]


def parse_http_tunnel_port(torrc_text: str) -> int | None:
    """Extract HTTPTunnelPort value from a torrc file."""
    for line in torrc_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"HTTPTunnelPort\s+(\d+)", line, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def verify_http_tunnel_enabled(config_path: Path, expected_port: int | None = None) -> bool:
    """Verify torrc defines HTTPTunnelPort (required for Android http_proxy)."""
    if not config_path.is_file():
        return False
    text = config_path.read_text(encoding="utf-8")
    port = parse_http_tunnel_port(text)
    if port is None:
        return False
    if expected_port is not None and port != expected_port:
        return False
    return True


def write_torrc(
    phone_index: int,
    http_port: int | None = None,
    socks_port: int | None = None,
    data_root: Path | None = None,
    control_port: int | None = None,
) -> Path:
    """Write torrc with HTTPTunnelPort (required for Android http_proxy)."""
    http_port = http_port or phone_http_port(phone_index)
    socks_port = socks_port or phone_socks_port(phone_index)
    control_port = control_port or phone_control_port(phone_index)
    data_dir = tor_data_path(phone_index, data_root)
    data_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = tor_config_path(phone_index, data_root)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    torrc = f"""# PharmFlow Tor instance for phone {phone_index}
DataDirectory {str(data_dir.resolve())}
HTTPTunnelPort {http_port}
SocksPort {socks_port}
ControlPort 127.0.0.1:{control_port}
CookieAuthentication 0
AvoidDiskWrites 1
MaxCircuitDirtiness 600
NewCircuitPeriod 300
"""
    cfg_path.write_text(torrc, encoding="utf-8")
    if not verify_http_tunnel_enabled(cfg_path, expected_port=http_port):
        raise RuntimeError(f"HTTPTunnelPort not enabled in {cfg_path}")
    logger.info(
        "Wrote Tor config for phone %d: HTTP %d, SOCKS %d, Control %d",
        phone_index,
        http_port,
        socks_port,
        control_port,
    )
    return cfg_path


class TorManager:
    """Manage per-phone Tor instances with adb reverse proxy mapping."""

    def __init__(self, adb: AdbWrapper | None = None) -> None:
        self.adb = adb or AdbWrapper()
        self.instances: dict[int, TorInstance] = {}
        install = detect_tor()
        self.tor_install = install
        self.tor_exe = install.path if install else tor_binary_path()

    def detect(self) -> dict[str, object]:
        """Return Tor detection status for preflight/dashboard."""
        installs = discover_tor_installations()
        return {
            "selected": str(self.tor_exe) if self.tor_exe else None,
            "selected_exists": self.tor_exe.is_file() if self.tor_exe else False,
            "install_kind": self.tor_install.kind.value if self.tor_install else None,
            "candidates": [
                {"path": str(i.path), "kind": i.kind.value, "label": i.label}
                for i in installs
            ],
        }

    def refresh_binary(self) -> TorInstall | None:
        """Re-scan for Tor after a download or install."""
        install = detect_tor()
        self.tor_install = install
        self.tor_exe = install.path if install else tor_binary_path()
        return install

    def _proc_age_s(self, proc: subprocess.Popen | None) -> float | None:
        """Process age in seconds, or None when the start time cannot be read."""
        if proc is None or proc.poll() is not None or not proc.pid:
            return None
        try:
            import psutil

            return max(0.0, time.time() - psutil.Process(int(proc.pid)).create_time())
        except Exception:
            return None

    def _http_down_needs_restart(self, phone_index: int, proc: subprocess.Popen | None) -> bool:
        """True when HTTP is down and the owner is stale — not a young bootstrap.

        Control-up + HTTP-down on a young (or age-unknown) process is bootstrap.
        Adopting that as "already up" used to leave the slot dead and claim healed.
        """
        if self._http_tunnel_alive(phone_index):
            return False
        age = self._proc_age_s(proc)
        try:
            budget = float(tor_wait_http_seconds())
        except Exception:
            budget = 240.0
        if age is None:
            # Can't prove stale. Control-up means HTTP may still be opening.
            return not self._control_alive(phone_index)
        return age >= budget

    def _terminate_proc(self, proc: subprocess.Popen | None) -> None:
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def start_phone_tor(
        self,
        phone_index: int,
        adb_serial: str,
        data_root: Path | None = None,
    ) -> TorInstance:
        """Start Tor for a phone and configure adb reverse to guest 127.0.0.1:<port>.

        A live process or ControlPort is not a live HTTP tunnel. Returning the
        instance in that state used to look like a restore while inject dialed
        a dead slot.
        """
        http_port = phone_http_port(phone_index)
        socks_port = phone_socks_port(phone_index)
        control_port = phone_control_port(phone_index)
        cfg = write_torrc(phone_index, http_port, socks_port, data_root, control_port)

        existing = self.instances.get(phone_index)
        proc = existing.process if existing else None
        proc_alive = proc is not None and proc.poll() is None
        http_up = self._http_tunnel_alive(phone_index)

        if proc_alive and http_up:
            logger.info("Tor already running for phone %d", phone_index)
            self._setup_reverse(adb_serial, http_port, phone_index=phone_index)
            return existing  # type: ignore[return-value]

        if proc_alive and not http_up:
            if not self._http_down_needs_restart(phone_index, proc):
                logger.info(
                    "Tor bootstrapping for phone %d — HTTP :%s not up yet",
                    phone_index,
                    http_port,
                )
                return existing  # type: ignore[return-value]
            logger.warning(
                "Tor process alive but HTTP :%s down for phone %d — restarting",
                http_port,
                phone_index,
            )
            self._terminate_proc(proc)
            self.instances.pop(phone_index, None)

        # Adopt only a listener that accepts HTTP. Control-only is a dead tunnel.
        if http_up:
            logger.info(
                "Tor tunnel already up for phone %d (adopting ControlPort %d)",
                phone_index,
                control_port,
            )
            # Farm uses this path, not start_tor_for_phone. Without the
            # publish, inject keeps the last writer's bases (dash was
            # heartbeating Tor Browser SOCKS 9150).
            _broadcast_port_bases()
            _ensure_bases_heartbeat()
            instance = TorInstance(
                phone_index=phone_index,
                http_port=http_port,
                socks_port=socks_port,
                config_path=cfg,
                process=None,
                control_port=control_port,
            )
            self.instances[phone_index] = instance
            self._setup_reverse(adb_serial, http_port, phone_index=phone_index)
            return instance

        if not self.tor_exe.is_file():
            raise FileNotFoundError(
                f"Tor binary not found: {self.tor_exe}. Install Tor Expert Bundle or set PHARMFLOW_TOR_PATH."
            )

        # DEVNULL (not PIPE): console-subsystem tor.exe + PIPE still attaches conhost and can flash.
        spawn_log = cfg.with_name(cfg.stem + "_spawn.log")
        log_f = spawn_log.open("ab")
        try:
            proc = subprocess.Popen(
                [str(self.tor_exe), "-f", str(cfg)],
                stdout=log_f,
                stderr=subprocess.STDOUT,
                **hidden_run_kwargs(),
            )
        finally:
            try:
                log_f.close()
            except Exception:
                pass
        if proc.pid:
            hide_console_burst(int(proc.pid))
        time.sleep(3.0)  # Allow Tor bootstrap
        if proc.poll() is not None:
            # Port conflict / bad torrc — adopt only when HTTP actually accepts.
            if self._http_tunnel_alive(phone_index):
                logger.warning(
                    "Tor process exited for phone %d but HTTP tunnel is up — adopting",
                    phone_index,
                )
                instance = TorInstance(
                    phone_index=phone_index,
                    http_port=http_port,
                    socks_port=socks_port,
                    config_path=cfg,
                    process=None,
                    control_port=control_port,
                )
                self.instances[phone_index] = instance
                self._setup_reverse(adb_serial, http_port, phone_index=phone_index)
                return instance
            err = ""
            try:
                err = spawn_log.read_text(encoding="utf-8", errors="replace")[-300:]
            except Exception:
                pass
            raise RuntimeError(f"Tor failed to stay up for phone {phone_index}: {err}")

        instance = TorInstance(
            phone_index=phone_index,
            http_port=http_port,
            socks_port=socks_port,
            config_path=cfg,
            process=proc,
            control_port=control_port,
        )
        self.instances[phone_index] = instance
        self._setup_reverse(adb_serial, http_port, phone_index=phone_index)
        return instance

    def _control_alive(self, phone_index: int) -> bool:
        control_port = phone_control_port(phone_index)
        try:
            with socket.create_connection(("127.0.0.1", control_port), timeout=1.5):
                return True
        except OSError:
            return False

    def _http_tunnel_alive(self, phone_index: int) -> bool:
        port = phone_http_port(phone_index)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.5):
                return True
        except OSError:
            return False

    def _setup_reverse(self, serial: str, port: int, phone_index: int | None = None) -> None:
        """
        Map host Tor HTTPTunnelPort into the emulator guest.

        Default: adb reverse tcp:<port> tcp:<port> then http_proxy 127.0.0.1:<port>
        When Mantis inject proxy is enabled: phone → inject(8218+) only → host
        Tor(8118+slot). Never stack a guest Tor reverse beside inject — that
        lets Chromium bypass MITM (no bottom-ad paint / CERTIFICATE_UNKNOWN).
        Legacy: http_proxy 10.0.2.2:<port> (PHARMFLOW_PROXY_LEGACY_GATEWAY=1)
        """
        # 10.0.2.2 is the host from the guest. Never write that proxy.
        try:
            port_i = int(port)
        except (TypeError, ValueError):
            port_i = 0
        if port_i <= 0:
            logger.warning("refusing guest proxy on %s — port %s is not a loopback exit", serial, port)
            return

        guest_port = port
        # Only arm inject when the caller named the phone. Deriving the index
        # as port - HTTP base treats a slot port as an absolute VM index and
        # arms the wrong listener. install_ca stays True — False was the
        # CERTIFICATE_UNKNOWN root cause on fresh ARM guests.
        if phone_index is not None:
            try:
                from automation.mantis_inject_proxy import (
                    ensure_inject_for_phone,
                    inject_enabled,
                    phone_inject_port,
                )

                idx = int(phone_index)
                if inject_enabled() and idx >= 0:
                    info = ensure_inject_for_phone(
                        self.adb, serial, idx, install_ca=True
                    )
                    if not info.get("ok"):
                        raise RuntimeError(
                            "inject not restored phone=%s err=%s ca=%s"
                            % (idx, info.get("error"), info.get("ca_installed"))
                        )
                    guest_port = int(info.get("port") or phone_inject_port(idx))
                    logger.info(
                        "Mantis inject-only pin phone=%d host_tor=%d inject=%d ca=%s serial=%s (no guest Tor reverse)",
                        idx,
                        port,
                        guest_port,
                        info.get("ca_installed"),
                        serial,
                    )
                    # ensure_inject already set http_proxy + inject reverse only.
                    return
            except Exception as exc:
                logger.warning("Mantis inject proxy not restored: %s", exc)
                # Pin the Tor tunnel (not :0) so a failed inject is not host-IP
                # egress, then refuse to look restored.
                self.adb.reverse(str(port_i), str(port_i), serial=serial)
                self._set_device_proxy(serial, port)
                raise

        self.adb.reverse(str(port_i), str(port_i), serial=serial)
        self._set_device_proxy(serial, guest_port)
        logger.info(
            "adb reverse tcp:%d + guest http_proxy %s:%d on %s",
            port,
            GUEST_PROXY_HOST,
            guest_port,
            serial,
        )

    def _set_device_proxy(self, serial: str, port: int) -> None:
        """Set Android http_proxy to 127.0.0.1:<port>. Never the host gateway."""
        try:
            port_i = int(port)
        except (TypeError, ValueError):
            port_i = 0
        if port_i <= 0:
            logger.warning("refusing guest proxy on %s — port %s is not a loopback exit", serial, port)
            return
        self.adb.set_http_proxy(GUEST_PROXY_HOST, port_i, serial=serial)

    def new_identity(self, phone_index: int) -> bool:
        """Request new Tor circuit for one phone (SIGHUP on Unix; restart on Windows)."""
        return self.rotate_identity(phone_index)

    def _control_newnym(self, phone_index: int) -> bool:
        """SIGNAL NEWNYM via ControlPort. Returns False if control is unavailable.

        Adopted standalone Tor uses CookieAuthentication. An empty
        AUTHENTICATE is rejected, so the circuit never moves. Cookie first,
        then the unauthenticated fallback used by CookieAuthentication 0.
        """
        inst = self.instances.get(phone_index)
        control_port = (inst.control_port if inst and inst.control_port else phone_control_port(phone_index))
        cookie = _control_auth_cookie(phone_index)
        try:
            with socket.create_connection(("127.0.0.1", control_port), timeout=5.0) as sock:
                if not _control_authenticate(sock, cookie):
                    logger.warning(
                        "Tor AUTHENTICATE failed phone=%d cookie=%s",
                        phone_index,
                        bool(cookie),
                    )
                    return False
                sock.sendall(b"SIGNAL NEWNYM\r\n")
                resp = sock.recv(256).decode("utf-8", errors="replace")
                if "250" not in resp:
                    logger.warning("Tor NEWNYM failed phone=%d: %s", phone_index, resp.strip())
                    return False
                return True
        except OSError as exc:
            logger.debug("Tor control NEWNYM unavailable phone=%d: %s", phone_index, exc)
            return False

    def _restart_tor_process(self, phone_index: int, adb_serial: str = "") -> bool:
        inst = self.instances.get(phone_index)
        if not inst:
            if adb_serial:
                try:
                    self.start_phone_tor(phone_index, adb_serial)
                    return True
                except (FileNotFoundError, OSError) as exc:
                    logger.error("Tor restart failed for phone %d: %s", phone_index, exc)
                    return False
            return False
        try:
            if inst.process and inst.process.poll() is None:
                inst.process.terminate()
                try:
                    inst.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    inst.process.kill()
                    inst.process.wait(timeout=5)
            cfg = write_torrc(
                phone_index,
                inst.http_port,
                inst.socks_port,
                control_port=inst.control_port or phone_control_port(phone_index),
            )
            spawn_log = cfg.with_name(cfg.stem + "_spawn.log")
            log_f = spawn_log.open("ab")
            try:
                proc = subprocess.Popen(
                    [str(self.tor_exe), "-f", str(cfg)],
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    **hidden_run_kwargs(),
                )
            finally:
                try:
                    log_f.close()
                except Exception:
                    pass
            if proc.pid:
                hide_console_burst(int(proc.pid))
            self.instances[phone_index] = TorInstance(
                phone_index=inst.phone_index,
                http_port=inst.http_port,
                socks_port=inst.socks_port,
                config_path=cfg,
                process=proc,
                control_port=inst.control_port or phone_control_port(phone_index),
            )
            time.sleep(3.0)
            if adb_serial:
                self._setup_reverse(adb_serial, inst.http_port, phone_index=phone_index)
            return True
        except OSError as exc:
            logger.error("Failed to restart Tor for phone %d: %s", phone_index, exc)
            return False

    def rotate_identity(self, phone_index: int, adb_serial: str = "") -> bool:
        """Rotate Tor identity for one phone; re-apply adb reverse if serial provided."""
        # Prefer NEWNYM against whatever Tor currently owns this phone's control/http ports.
        if self._control_newnym(phone_index):
            time.sleep(2.5)
            inst = self.instances.get(phone_index)
            try:
                if adb_serial and inst:
                    self._setup_reverse(adb_serial, inst.http_port, phone_index=phone_index)
                elif adb_serial:
                    self._setup_reverse(
                        adb_serial, phone_http_port(phone_index), phone_index=phone_index
                    )
            except Exception as exc:
                logger.error(
                    "Tor NEWNYM ok but proxy not restored phone=%d: %s",
                    phone_index,
                    exc,
                )
                return False
            logger.info(
                "New Tor identity for phone %d via ControlPort NEWNYM (port %d)",
                phone_index,
                phone_http_port(phone_index),
            )
            return True

        inst = self.instances.get(phone_index)
        if not inst or not inst.process or inst.process.poll() is not None:
            if adb_serial:
                try:
                    self.start_phone_tor(phone_index, adb_serial)
                    inst = self.instances.get(phone_index)
                except (FileNotFoundError, OSError, RuntimeError) as exc:
                    logger.error("Tor restart failed for phone %d: %s", phone_index, exc)
            if self._control_newnym(phone_index):
                time.sleep(2.5)
                if adb_serial:
                    try:
                        self._setup_reverse(
                            adb_serial,
                            phone_http_port(phone_index),
                            phone_index=phone_index,
                        )
                    except Exception as exc:
                        logger.error(
                            "Tor adopted but proxy not restored phone=%d: %s",
                            phone_index,
                            exc,
                        )
                        return False
                logger.info(
                    "New Tor identity for phone %d via ControlPort after adopt (port %d)",
                    phone_index,
                    phone_http_port(phone_index),
                )
                return True
            if not inst or (inst.process is not None and inst.process.poll() is not None and not self._http_tunnel_alive(phone_index)):
                logger.error("Tor not running for phone %d", phone_index)
                return False
        try:
            if hasattr(signal, "SIGHUP") and inst and inst.process and inst.process.poll() is None:
                inst.process.send_signal(signal.SIGHUP)
                time.sleep(5.0)
            elif inst and inst.process and inst.process.poll() is None:
                if not self._restart_tor_process(phone_index, adb_serial):
                    return False
                time.sleep(5.0)
                inst = self.instances.get(phone_index)
            elif not self._control_newnym(phone_index):
                logger.error("Tor NEWNYM unavailable for phone %d", phone_index)
                return False
            else:
                time.sleep(2.5)
            if adb_serial:
                self._setup_reverse(
                    adb_serial, phone_http_port(phone_index), phone_index=phone_index
                )
            logger.info(
                "New Tor identity for phone %d (port %d)",
                phone_index,
                phone_http_port(phone_index),
            )
            return True
        except (OSError, RuntimeError) as exc:
            logger.error("Failed to rotate Tor identity for phone %d: %s", phone_index, exc)
            return False

    def fetch_exit_ip(self, phone_index: int, *, timeout: float = 20.0) -> str:
        """Fetch current Tor exit IP via that phone's HTTPTunnelPort (host-side)."""
        port = phone_http_port(phone_index)
        proxy = f"http://127.0.0.1:{port}"
        handlers = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        opener = urllib.request.build_opener(handlers)
        last_err = ""
        for url in _IP_CHECK_URLS:
            try:
                with opener.open(url, timeout=timeout) as resp:
                    body = resp.read(256).decode("utf-8", errors="replace")
                ip = _parse_public_ip(body)
                if ip:
                    return ip
                last_err = f"unparseable body from {url}: {body[:80]!r}"
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_err = str(exc)
        if last_err:
            logger.warning("fetch_exit_ip failed phone=%d proxy=%s: %s", phone_index, proxy, last_err)
        return ""

    def rotate_until_unique_ip(
        self,
        phone_index: int,
        adb_serial: str = "",
        *,
        max_retries: int | None = None,
        avoid_other_phones: bool = True,
    ) -> ExitIpRotateResult:
        """Rotate Tor until exit IP is new for this phone and unused by the farm."""
        retries_budget = max_retries if max_retries is not None else max(1, UNIQUE_EXIT_IP_RETRIES)
        before = get_last_exit_ip(phone_index)
        attempts = 0
        after = ""
        avoided_collision = False
        last_reject = ""

        if adb_serial:
            try:
                self.start_phone_tor(phone_index, adb_serial)
            except (FileNotFoundError, OSError) as exc:
                result = ExitIpRotateResult(
                    ok=False,
                    before=before,
                    after="",
                    changed=False,
                    retries=0,
                    phone_index=phone_index,
                    error=f"tor start failed: {exc}",
                )
                logger.error("phone=%d %s", phone_index, result.log_line())
                return result

        if not before:
            before = self.fetch_exit_ip(phone_index)

        while attempts < retries_budget:
            attempts += 1
            if not self.rotate_identity(phone_index, adb_serial):
                continue
            # NEWNYM rate-limit: Tor may keep the same circuit briefly.
            time.sleep(1.5 + min(attempts, 3) * 0.5)
            after = self.fetch_exit_ip(phone_index)
            if not after:
                continue
            if avoid_other_phones:
                claimed, reason = try_claim_exit_ip(phone_index, after, before=before)
            else:
                # Tests / single-phone: only require change vs own last.
                if before and after == before:
                    claimed, reason = False, "same as this phone last"
                else:
                    remember_exit_ip(phone_index, after)
                    claimed, reason = True, ""
            if not claimed:
                last_reject = reason
                if "collides" in reason:
                    avoided_collision = True
                    logger.info(
                        "phone=%d exit IP %s rejected (%s) — rotating again",
                        phone_index,
                        after,
                        reason,
                    )
                continue
            # First IP of a run (empty before) still establishes a verified identity.
            changed = (not before) or (after != before)
            result = ExitIpRotateResult(
                ok=True,
                before=before,
                after=after,
                changed=changed,
                retries=attempts,
                phone_index=phone_index,
                avoided_collision=avoided_collision,
            )
            line = result.log_line()
            logger.info("phone=%d %s", phone_index, line)
            logging.getLogger("farm_354").info("phone=%d %s", phone_index, line)
            return result

        if not after:
            after = self.fetch_exit_ip(phone_index)
        claimed = False
        if after:
            if avoid_other_phones:
                claimed, last_reject = try_claim_exit_ip(phone_index, after, before=before)
            elif (not before) or after != before:
                remember_exit_ip(phone_index, after)
                claimed = True
        changed = bool(claimed and after and ((not before) or (after != before)))
        result = ExitIpRotateResult(
            ok=changed,
            before=before,
            after=after,
            changed=changed,
            retries=attempts,
            phone_index=phone_index,
            error=""
            if changed
            else (last_reject or "exit IP unchanged after bounded retries"),
            avoided_collision=avoided_collision,
        )
        level = logging.INFO if changed else logging.ERROR
        line = result.log_line()
        logger.log(
            level,
            "phone=%d %s%s",
            phone_index,
            line,
            f" err={result.error}" if result.error else "",
        )
        logging.getLogger("farm_354").log(
            level,
            "phone=%d %s%s",
            phone_index,
            line,
            f" err={result.error}" if result.error else "",
        )
        return result

    def ensure_unique_exit_ip(
        self,
        phone_index: int,
        adb_serial: str = "",
        *,
        max_retries: int | None = None,
    ) -> ExitIpRotateResult:
        """Verified different exit IP (or blind rotate when uniqueness disabled)."""
        if not require_unique_exit_ip():
            ok = self.rotate_identity(phone_index, adb_serial)
            after = self.fetch_exit_ip(phone_index) if ok else ""
            if after:
                remember_exit_ip(phone_index, after)
            return ExitIpRotateResult(
                ok=ok,
                before=get_last_exit_ip(phone_index),
                after=after,
                changed=False,
                retries=1 if ok else 0,
                phone_index=phone_index,
                error="" if ok else "rotate_identity failed",
            )
        return self.rotate_until_unique_ip(
            phone_index,
            adb_serial,
            max_retries=max_retries,
            avoid_other_phones=True,
        )

    def verify_phone_tor(self, phone_index: int, adb_serial: str = "") -> TorPhoneStatus:
        """Verify Tor process, HTTPTunnelPort in torrc, and guest proxy mapping."""
        http_port = phone_http_port(phone_index)
        socks_port = phone_socks_port(phone_index)
        cfg_path = tor_config_path(phone_index)
        failures: list[str] = []

        inst = self.instances.get(phone_index)
        running = bool(inst and inst.process and inst.process.poll() is None)
        if not running:
            running = self._control_alive(phone_index) or self._http_tunnel_alive(phone_index)
        if not running:
            failures.append("tor process not running")

        http_tunnel = verify_http_tunnel_enabled(cfg_path, expected_port=http_port)
        if not http_tunnel:
            failures.append(f"HTTPTunnelPort {http_port} not enabled in torrc")

        reverse_ok = True
        if adb_serial and not is_proxy_legacy_gateway():
            listing = self.adb.run("reverse", "--list", serial=adb_serial)
            reverse_ok = f"tcp:{http_port}" in listing.stdout
            if not reverse_ok:
                failures.append(f"adb reverse tcp:{http_port} missing on {adb_serial}")

        return TorPhoneStatus(
            phone_index=phone_index,
            http_port=http_port,
            socks_port=socks_port,
            running=running,
            http_tunnel_enabled=http_tunnel,
            guest_proxy=guest_proxy_endpoint(phone_index),
            reverse_configured=reverse_ok,
            failures=failures,
        )

    def stop_phone_tor(self, phone_index: int, adb_serial: str = "") -> None:
        """Stop Tor and clean up reverse proxy."""
        inst = self.instances.pop(phone_index, None)
        port = inst.http_port if inst else phone_http_port(phone_index)
        if inst and inst.process:
            inst.process.terminate()
            try:
                inst.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                inst.process.kill()
        if adb_serial and not is_skip_exit_proxy_clear():
            self.adb.reverse_remove(str(port), serial=adb_serial)
            self.adb.clear_http_proxy(serial=adb_serial)

    def stop_all(self) -> None:
        for idx in list(self.instances.keys()):
            self.stop_phone_tor(idx)

    def get_proxy_url(self, phone_index: int) -> str:
        return f"http://127.0.0.1:{phone_http_port(phone_index)}"

    _PROXY_GLOBAL_KEYS = (
        "http_proxy",
        "global_http_proxy_host",
        "global_http_proxy_port",
        "global_http_proxy_exclusion_list",
        "global_proxy_pac_url",
    )

    def clear_all_proxies_on_devices(self, serials: list[str]) -> list[str]:
        """Refuse. Deleting http_proxy or writing :0 sends farm traffic out the host."""
        log.warning("clear_all_proxies_on_devices refused — will not write http_proxy :0")
        return [str(s) for s in serials if s]

    def kick_default_browser_after_proxy_teardown(self, serials: list[str]) -> None:
        """Force-stop Chromium so cached proxy state is dropped."""
        from automation.config import BROWSER_CHROMIUM, BROWSER_MUMU

        for serial in serials:
            if not serial:
                continue
            for pkg in (BROWSER_CHROMIUM, BROWSER_MUMU, "com.android.chrome"):
                self.adb.shell(f"am force-stop {pkg}", serial=str(serial))


# ==== merged from pharmflow automation/tor_manager.py (warm bootstrap / adb reverse / identity) ====

def _prefs_base_value(key: str) -> Optional[int]:
    """Optional override from ``desktop_prefs.json`` so moved bases survive EXE restarts.

    Keys: ``tor_socks_base`` / ``tor_http_base``. Env wins over prefs; both are optional
    (default stays 9050 / 8118 for machines without a port conflict).
    """
    try:
        for root in (Path(__file__).resolve().parent.parent / "automation" / "recordings",
                     Path(__file__).resolve().parent / "recordings"):
            p = root / "desktop_prefs.json"
            if not p.is_file():
                continue
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                v = data.get(key)
                if isinstance(v, int) and 1024 <= v <= 65500:
                    return v
    except (OSError, json.JSONDecodeError):
        pass
    return None



def _port_base_env(name: str, default: int) -> int:
    """Read a Tor port-base offset from env, then ``desktop_prefs.json`` (clamped).

    PharmFlow and other farms on the same PC both used ``9050``/``8118``,
    so their Tor instances fought over the same SOCKS/HTTP ports. ``PHARMFLOW_TOR_*``
    / ``CPHARM_TOR_*`` (env) and ``tor_socks_base`` / ``tor_http_base``
    (desktop_prefs.json) let a second stack move — but prefs still carry the old
    evasion pair 9150/8218, which collides with mantis inject (8218+). Reject that
    pair so inject never dials itself as Tor upstream.
    """
    aliases = {
        "PHARMFLOW_TOR_SOCKS_BASE": ("CPHARM_TOR_SOCKS_BASE", "PHARMFLOW_TOR_SOCKS_BASE"),
        "PHARMFLOW_TOR_HTTP_BASE": ("CPHARM_TOR_HTTP_BASE", "PHARMFLOW_TOR_HTTP_BASE"),
        "CPHARM_TOR_SOCKS_BASE": ("CPHARM_TOR_SOCKS_BASE", "PHARMFLOW_TOR_SOCKS_BASE"),
        "CPHARM_TOR_HTTP_BASE": ("CPHARM_TOR_HTTP_BASE", "PHARMFLOW_TOR_HTTP_BASE"),
    }
    for env_name in aliases.get(name, (name,)):
        raw = os.environ.get(env_name, "").strip()
        if raw.isdigit():
            return max(1024, min(65500, int(raw)))
    pref_key = (
        "tor_http_base"
        if "HTTP" in name.upper()
        else "tor_socks_base"
    )
    v = _prefs_base_value(pref_key)
    if v is not None:
        if pref_key == "tor_http_base" and int(v) == 8218:
            return default
        if pref_key == "tor_socks_base" and int(v) == 9150:
            return default
        return v
    return default



def _tcp_port_excluded(port: int) -> bool:
    """True when Windows Hyper-V (or similar) has reserved ``port`` (WSAEACCES)."""
    # Live exclusion snapshot (2026-09-14): 9036-9535 blocks default Tor SOCKS 9050.
    # Keep HTTPTunnel 8118 clear; only skip known SOCKS collision bands.
    p = int(port)
    return 9036 <= p <= 9535


def _listen_ports_in_range(base: int, span: int) -> set[int]:
    """Ports in ``base..base+span-1`` that another process already listens on.

    Two farms share this PC (PharmFlow + PharmFlow's ``bundled\\tor.exe`` and mantis
    injectors), and their ranges overlap at runtime. Instead of hardcoding a range
    that can collide again, pick a base whose whole per-phone span is free.
    """
    try:
        import socket
        busy: set[int] = set()
        for p in range(base, base + span):
            if _tcp_port_excluded(p):
                busy.add(p)
                continue
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.15)
            try:
                if s.connect_ex(("127.0.0.1", p)) == 0:
                    busy.add(p)
            finally:
                s.close()
        return busy
    except Exception:
        return set()



def _free_port_base(base: int, span: int, step: int = 10) -> int:
    """Find a base whose entire ``span``-port window is unoccupied (searching upward)."""
    cand = base
    for _ in range(40):
        if not _listen_ports_in_range(cand, span):
            return cand
        cand += step
    return base


# Prefer a configured base, but auto-evade any other process (PharmFlow's Tor stack,
# mantis injectors, etc.) that has already claimed part of that window.
_CONFIGURED_SOCKS = _port_base_env("PHARMFLOW_TOR_SOCKS_BASE", 9050)
_CONFIGURED_HTTP = _port_base_env("PHARMFLOW_TOR_HTTP_BASE", 8118)
# Prefs 9150/8218 are the inject-collision pair — never adopt as Tor bases.
if _CONFIGURED_HTTP == 8218:
    _CONFIGURED_HTTP = 8118
    if _CONFIGURED_SOCKS == 9150:
        _CONFIGURED_SOCKS = 9050


def _logs_dirs_for_bases() -> list[Path]:
    """Tor broadcast log roots.

    Explicit LOGS/LOG_DIR env: first non-empty wins. Else dual-read CPharm + PharmFlow.
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


def _logs_dirs_for_bases_write() -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for d in list(_logs_dirs_for_bases()) + [
        Path(r"C:\CPharm\logs"),
        Path(r"C:\PharmFlow\logs"),
    ]:
        key = str(d).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def _read_broadcast_bases() -> tuple[int, int] | None:
    """Port bases broadcast by the process that owns the live Tor generation.

    The owning process heartbeats the file every 60s while its lanes live, so a
    fresh file (<120s) proves both the writer and its generation are alive. A
    stale file is ignored — that generation is dead and its bases are poison.
    Prefer the freshest valid broadcast across CPharm + PharmFlow log dirs.
    Never adopt http_base in the inject window (8218+).
    """
    best: tuple[float, int, int] | None = None
    now = time.time()
    for logs_dir in _logs_dirs_for_bases():
        state = logs_dir / "tor_port_bases.json"
        try:
            data = json.loads(state.read_text(encoding="utf-8"))
            age = now - float(data.get("ts") or 0)
            socks_b = int(data.get("socks_base") or 0)
            http_b = int(data.get("http_base") or 0)
            if age >= 120 or socks_b <= 0 or http_b <= 0 or http_b == 8218:
                continue
            ts = float(data.get("ts") or 0)
            if best is None or ts > best[0]:
                best = (ts, socks_b, http_b)
        except Exception:
            continue
    if best is None:
        return None
    return best[1], best[2]


def _free_base_or_adopt(configured: int, span: int, fallback_broadcast: int | None) -> int:
    """Adopt the live generation's base when fresh; otherwise shift to a free one.

    A fresh broadcast means lanes are listening on those bases *right now* —
    adopting keeps every process in the same generation. Re-shifting on every
    import is what made connectivity nondeterministic across restarts.
    """
    if fallback_broadcast and fallback_broadcast > 0:
        return fallback_broadcast
    return _free_port_base(configured, span)


_BROADCAST = _read_broadcast_bases()
BASE_PORT = _free_base_or_adopt(
    _CONFIGURED_SOCKS, 8, _BROADCAST[0] if _BROADCAST else None
)
# Per-phone HTTP proxy ports (Tor HTTPTunnelPort). Android ``global http_proxy`` expects
# HTTP CONNECT — **not** SOCKS. Open alongside SocksPort in :func:`start_tor_for_phone`.
HTTP_TUNNEL_BASE = _free_base_or_adopt(
    _CONFIGURED_HTTP, 8, _BROADCAST[1] if _BROADCAST else None
)
if int(HTTP_TUNNEL_BASE) == 8218:
    # Never let Tor HTTP land on the inject listen base.
    HTTP_TUNNEL_BASE = 8118
    if int(BASE_PORT) == 9150:
        BASE_PORT = 9050
if BASE_PORT != _CONFIGURED_SOCKS or HTTP_TUNNEL_BASE != _CONFIGURED_HTTP:
    logger.info(
        "Tor port bases auto-shifted to avoid other listeners: socks %s->%s http %s->%s",
        _CONFIGURED_SOCKS, BASE_PORT, _CONFIGURED_HTTP, HTTP_TUNNEL_BASE,
    )


def _broadcast_port_bases() -> None:
    """Publish the actual SOCKS/HTTP port bases to disk for *other* processes.

    The inject proxies (farm lane / run_mantis_inject_proxies) dial Tor on these
    bases but run in a different process than whoever spawned the Tor lanes, so
    they cannot see this module's runtime auto-shift. Without this broadcast,
    inject computes ``8118 + idx`` while Tor listens on the shifted base
    (e.g. ``8138 + idx``) — every upstream connect is refused, which presents on
    the phones as total loss of internet.
    """
    try:
        # 9150 is Tor Browser, not a farm SOCKS base. desktop_prefs still has
        # the old PharmFlow-evasion pair (9150/8218); publishing it made inject
        # dial a different HTTP lane than the farm worker.
        if int(BASE_PORT) == 9150 or int(HTTP_TUNNEL_BASE) == 8218:
            return
        payload = json.dumps(
            {
                "ts": time.time(),
                "socks_base": int(BASE_PORT),
                "http_base": int(HTTP_TUNNEL_BASE),
                "pid": os.getpid(),
            }
        )
        for state_dir in _logs_dirs_for_bases_write():
            try:
                state_dir.mkdir(parents=True, exist_ok=True)
                (state_dir / "tor_port_bases.json").write_text(payload, encoding="utf-8")
            except OSError:
                continue
    except Exception as exc:  # noqa: BLE001 — broadcast is best-effort
        logger.debug("tor port-base broadcast failed: %s", exc)


def _ensure_bases_heartbeat() -> None:
    """Start (once per process) the 60s heartbeat that keeps the bases file fresh.

    The freshness window in :func:`_read_broadcast_bases` doubles as a liveness
    proof for the owning generation — so the heartbeat must run while lanes are
    alive. When every lane in this process is gone, the heartbeat exits so a
    stale file can never keep masking a dead generation.
    """
    global _BASES_HEARTBEAT
    if _BASES_HEARTBEAT is not None and _BASES_HEARTBEAT.is_alive():
        return

    import threading

    def _loop() -> None:
        while True:
            if _tor_procs and all(p.poll() is not None for p in _tor_procs.values()):
                return  # generation dead — stop refreshing so consumers re-shift
            _broadcast_port_bases()
            time.sleep(60.0)

    _BASES_HEARTBEAT = threading.Thread(
        target=_loop, name="tor-bases-heartbeat", daemon=True
    )
    _BASES_HEARTBEAT.start()


_BASES_HEARTBEAT: threading.Thread | None = None


# On the emulator/phone, ``global http_proxy`` uses ``127.0.0.1:<port>`` with
# ``adb reverse tcp:<device_port> tcp:<host_tor_tunnel>``.
# **Per ``phone_idx``** we use the same port number on device and host (``8118 + idx``) with
# ``adb reverse tcp:P tcp:P`` so each phone maps to its own Tor ``HTTPTunnelPort``. Older builds
# used ``tcp:8118`` for every index on the device side, which could leave incorrect host forwards
# when multiple devices run Tor (browser: **proxy connection failed**).
_tor_procs: dict[int, subprocess.Popen] = {}
# Monotonic spawn time so a still-bootstrapping tor.exe is not killed and
# replaced on the next heal tick (that restart loop never opens HTTP).
_tor_proc_started: dict[int, float] = {}

# Host Tor bootstrap: dashboard may start one multi-index prewarm thread; per-index warm threads
# from ``start_tor_warm_background``; per-index locks so concurrent ``ensure_tor_ready`` / open_url
# paths do not spin duplicate SOCKS/HTTP polls; ``Event`` marks "ports listened successfully".
_tor_prewarm_thread: threading.Thread | None = None
_tor_prewarm_thread_lock = threading.Lock()
_tor_bootstrap_master_lock = threading.Lock()
_tor_bootstrap_idx_locks: dict[int, threading.Lock] = {}
_tor_host_ready_lock = threading.Lock()
_tor_host_ready_events: dict[int, threading.Event] = {}

# Per phone_idx: at most one alive daemon thread host-warming that index (idempotent re-entry).
_tor_idx_warm_threads: dict[int, threading.Thread] = {}
_tor_idx_warm_threads_lock = threading.Lock()

# Per phone_idx: monotonic timestamp of the most recent warm worker exit (success or failure).
# Used by :func:`ensure_tor_and_proxy_for_phone` to detect that a warm attempt **just ran** for
# this index and avoid double-spending the full ``PHARMFLOW_TOR_WAIT_SOCKS`` + ``PHARMFLOW_TOR_WAIT_HTTP``
# budget when bootstrap is already known to be slow / failing — keeps ``open_url`` from blocking
# 8+ minutes (warm budget) and then another 8 minutes (ensure budget) for the same device.
_tor_warm_last_exit_ts: dict[int, float] = {}
_tor_warm_last_exit_lock = threading.Lock()



def _record_warm_attempt_exit(phone_idx: int) -> None:
    with _tor_warm_last_exit_lock:
        _tor_warm_last_exit_ts[phone_idx] = time.monotonic()



def _recent_warm_attempt(phone_idx: int, window_sec: float = 60.0) -> bool:
    """True when a warm worker for ``phone_idx`` finished within ``window_sec`` seconds.

    A warm worker that just exited without setting :data:`_tor_host_ready_events` already burned the
    long ``wait_for_tor`` / ``wait_for_tor_http_tunnel`` budget; let the synchronous caller fall
    through with a much shorter retry instead of doubling the wall-clock cost.
    """
    with _tor_warm_last_exit_lock:
        ts = _tor_warm_last_exit_ts.get(phone_idx)
    if ts is None:
        return False
    return (time.monotonic() - ts) < max(1.0, float(window_sec))



def _tor_skip_wait_env() -> bool:
    return os.environ.get("PHARMFLOW_SKIP_TOR_WAIT", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )



def _tor_prewarm_max_idx() -> int:
    raw = os.environ.get("PHARMFLOW_TOR_PREWARM_MAX_IDX", "").strip()
    if raw:
        try:
            return max(0, min(31, int(raw)))
        except ValueError:
            pass
    return 7



def _bootstrap_lock_for(phone_idx: int) -> threading.Lock:
    with _tor_bootstrap_master_lock:
        if phone_idx not in _tor_bootstrap_idx_locks:
            _tor_bootstrap_idx_locks[phone_idx] = threading.Lock()
        return _tor_bootstrap_idx_locks[phone_idx]



def _get_host_ready_event(phone_idx: int) -> threading.Event:
    with _tor_host_ready_lock:
        if phone_idx not in _tor_host_ready_events:
            _tor_host_ready_events[phone_idx] = threading.Event()
        return _tor_host_ready_events[phone_idx]



def _resolve_warm_phone_index(phone_index: Optional[int]) -> int:
    """Default warm index: ``phone_index``, else env ``PHARMFLOW_TOR_WARM_PHONE_INDEX``, else **0**."""
    if phone_index is not None:
        return max(0, min(31, int(phone_index)))
    raw = os.environ.get("PHARMFLOW_TOR_WARM_PHONE_INDEX", "").strip()
    if raw:
        try:
            return max(0, min(31, int(raw)))
        except ValueError:
            pass
    return 0



def _warm_host_tor_ports_for_index(phone_idx: int) -> None:
    """Start standalone Tor for ``phone_idx`` if needed and wait until SOCKS + HTTP tunnel listen.

    Serialized with :func:`_bootstrap_lock_for` / host-ready :class:`threading.Event` shared with
    :func:`ensure_tor_and_proxy_for_phone` so duplicate long polls do not run in parallel. Records
    the worker's exit timestamp via :func:`_record_warm_attempt_exit` so a synchronous follow-up
    ``ensure_tor_ready`` can use a short retry budget instead of doubling the wall-clock wait.
    """
    try:
        try:
            start_tor_for_phone(phone_idx)
        except (RuntimeError, FileNotFoundError) as e:
            log.warning("Tor host warm: cannot start idx=%s — %s", phone_idx, e)
            return
        lock = _bootstrap_lock_for(phone_idx)
        ev = _get_host_ready_event(phone_idx)
        with lock:
            if ev.is_set() and wait_for_tor(phone_idx, timeout=2) and wait_for_tor_http_tunnel(phone_idx, timeout=2):
                return
            if ev.is_set():
                ev.clear()
            ws = tor_wait_socks_seconds()
            wh = tor_wait_http_seconds()
            ok_s = wait_for_tor(phone_idx, timeout=ws)
            if ok_s:
                boot_budget = tor_wait_bootstrap_seconds()
                if not wait_for_tor_bootstrap(phone_idx, timeout=boot_budget):
                    log.warning(
                        "Tor host warm: bootstrap not confirmed within %ss phone_idx=%s — "
                        "ev NOT set; browser would see ERR_TIMED_OUT",
                        boot_budget,
                        phone_idx,
                    )
                    ok_s = False
            ok_h = wait_for_tor_http_tunnel(phone_idx, timeout=wh) if ok_s else False
            if ok_s and ok_h:
                ev.set()
                log.info("Tor host warm ready phone_idx=%s", phone_idx)
            else:
                log.warning(
                    "Tor host warm: ports not ready phone_idx=%s socks=%s http=%s",
                    phone_idx,
                    ok_s,
                    ok_h,
                )
    finally:
        _record_warm_attempt_exit(phone_idx)



def _prewarm_host_tors_worker(max_idx: int) -> None:
    log.info("Tor host prewarm thread started (indices 0..%s)", max_idx)
    pre = tor_proxy_preflight()
    if not pre.get("ok"):
        log.info("Tor host prewarm skipped — %s", pre.get("error", "unknown"))
        return
    for i in range(max_idx + 1):
        _warm_host_tor_ports_for_index(i)



def _tor_warm_background_worker(phone_idx: int) -> None:
    if _tor_skip_wait_env():
        return
    pre = tor_proxy_preflight()
    if not pre.get("ok"):
        log.debug("Tor background warm skipped phone_idx=%s — %s", phone_idx, pre.get("error", "unknown"))
        return
    _warm_host_tor_ports_for_index(phone_idx)



def _join_idx_warm_thread_if_running(phone_idx: int, timeout_sec: float) -> None:
    """Block until the per-index background warm thread exits (no-op if not running)."""
    with _tor_idx_warm_threads_lock:
        t = _tor_idx_warm_threads.get(int(phone_idx))
    if t is not None and t.is_alive():
        t.join(timeout=max(0.0, float(timeout_sec)))



def start_tor_warm_background(phone_index: Optional[int] = None) -> None:
    """Start **at most one** daemon thread per ``phone_index`` that host-warms Tor for that slot.

    Idempotent: no-op when ``PHARMFLOW_SKIP_TOR_WAIT`` is set, Tor preflight fails, host ports are
    already ready, or a warm thread for this index is already alive. Does **not** apply ADB
    ``http_proxy`` — that remains in :func:`ensure_tor_and_proxy_for_phone` / ``ensure_tor_ready``.

    ``phone_index`` defaults to env ``PHARMFLOW_TOR_WARM_PHONE_INDEX`` or **0**.
    """
    if _tor_skip_wait_env():
        return
    idx = _resolve_warm_phone_index(phone_index)
    pre = tor_proxy_preflight()
    if not pre.get("ok"):
        log.debug("start_tor_warm_background: not started — %s", pre.get("error", "unknown"))
        return
    ev = _get_host_ready_event(idx)
    if ev.is_set() and wait_for_tor(idx, timeout=1) and wait_for_tor_http_tunnel(idx, timeout=1):
        return
    with _tor_idx_warm_threads_lock:
        t_prev = _tor_idx_warm_threads.get(idx)
        if t_prev is not None and t_prev.is_alive():
            return
        t = threading.Thread(
            target=_tor_warm_background_worker,
            args=(idx,),
            daemon=True,
            name=f"pharmflow-tor-warm-{idx}",
        )
        t.start()
        _tor_idx_warm_threads[idx] = t



def wait_tor_ready(phone_index: Optional[int] = None, timeout_sec: float = 240) -> bool:
    """Block until host SOCKS + HTTP tunnel accept for ``phone_index`` **without** starting Tor.

    Polls ports in short slices until ``timeout_sec`` elapses. Returns ``True`` immediately when
    ``PHARMFLOW_SKIP_TOR_WAIT`` is set. Does not spawn ``tor.exe`` or background warm threads.
    """
    if _tor_skip_wait_env():
        return True
    idx = _resolve_warm_phone_index(phone_index)
    deadline = time.time() + max(0.0, float(timeout_sec))
    while time.time() < deadline:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        chunk = int(min(3, max(1, remaining)))
        if wait_for_tor(idx, timeout=chunk) and wait_for_tor_http_tunnel(idx, timeout=chunk):
            return True
        time.sleep(0.2)
    return False



def start_tor_host_bootstrap_background(max_phone_idx: Optional[int] = None) -> None:
    """Start **one** daemon thread that brings host Tor listeners up for indices ``0..max``.

    Idempotent while the thread is alive. Does **not** touch ADB or ``http_proxy`` (that stays in
    :func:`ensure_tor_and_proxy_for_phone`). Skipped when ``PHARMFLOW_SKIP_TOR_WAIT`` is set or Tor
    preflight fails (nothing to warm).

    ``max_phone_idx`` defaults to env ``PHARMFLOW_TOR_PREWARM_MAX_IDX`` (default **7**).
    """
    if _tor_skip_wait_env():
        return
    pre = tor_proxy_preflight()
    if not pre.get("ok"):
        log.debug("Tor host bootstrap not started — %s", pre.get("error", "unknown"))
        return
    m = int(max_phone_idx) if max_phone_idx is not None else _tor_prewarm_max_idx()
    m = max(0, min(31, m))
    with _tor_prewarm_thread_lock:
        global _tor_prewarm_thread
        if _tor_prewarm_thread is not None and _tor_prewarm_thread.is_alive():
            return
        t = threading.Thread(
            target=_prewarm_host_tors_worker,
            args=(m,),
            daemon=True,
            name="pharmflow-tor-prewarm",
        )
        t.start()
        _tor_prewarm_thread = t



def ensure_tor_daemon_started_async(max_phone_idx: Optional[int] = None) -> None:
    """:func:`start_tor_host_bootstrap_background` alias for callers that expect an "async start" name.

    Not a heal. Returns before any port is listening, clamps the index, and
    warms ``0..max`` (including unused slots). Farm self-heal must call
    :func:`restore_tor_http_for_slots` and treat a down port as unrestored.
    """
    start_tor_host_bootstrap_background(max_phone_idx)


def _tcp_open(port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def align_bases_to_live_broadcast() -> tuple[int, int]:
    """Adopt the live Tor generation's bases, or the configured bases.

    A fresh ``tor_port_bases.json`` is the generation inject already dials.
    Re-shifting here is the 8118-vs-8218 split-brain. A stale file means that
    generation is dead — bind the configured bases, never a base that lands
    in the inject window (8218+). Does not invent a phone-count cap.
    """
    global BASE_PORT, HTTP_TUNNEL_BASE
    broadcast = _read_broadcast_bases()
    if broadcast:
        BASE_PORT = int(broadcast[0])
        HTTP_TUNNEL_BASE = int(broadcast[1])
        return BASE_PORT, HTTP_TUNNEL_BASE
    socks = int(_port_base_env("PHARMFLOW_TOR_SOCKS_BASE", 9050))
    http = int(_port_base_env("PHARMFLOW_TOR_HTTP_BASE", 8118))
    if http == 8218:
        log.warning(
            "configured Tor HTTP base %s collides with inject (8218) — using 8118",
            http,
        )
        http = 8118
        # Prefs 9150/8218 are the old PharmFlow-evasion pair. Forcing only HTTP
        # down to 8118 left SOCKS on Tor Browser (9150). Inject then dialed a
        # different generation than the farm. Keep the pair together.
        if socks == 9150:
            socks = 9050
    BASE_PORT = socks
    HTTP_TUNNEL_BASE = http
    return BASE_PORT, HTTP_TUNNEL_BASE


def _terminate_owned_tor(phone_idx: int) -> None:
    """Stop only the Tor process this process spawned for ``phone_idx``."""
    proc = _tor_procs.pop(phone_idx, None)
    _tor_proc_started.pop(phone_idx, None)
    try:
        _get_host_ready_event(phone_idx).clear()
    except Exception:
        pass
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=8)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _tor_http_ready_or_bootstrapping(phone_idx: int, http_port: int) -> bool:
    """True when the caller must NOT spawn another tor.exe for this slot.

    A live HTTP tunnel is ready (adopt it). A young process that has not
    opened HTTP yet is still bootstrapping — killing it every tick never
    restores the port. An old process with a dead HTTP tunnel is terminated
    so the caller can spawn a replacement.
    """
    if _tcp_open(http_port):
        return True
    proc = _tor_procs.get(phone_idx)
    if proc is None or proc.poll() is not None:
        _tor_procs.pop(phone_idx, None)
        return False
    started = float(_tor_proc_started.get(phone_idx) or 0.0)
    age = (time.monotonic() - started) if started else 1e9
    if age < float(tor_wait_http_seconds()):
        return True
    log.warning(
        "Tor slot=%s pid=%s HTTP :%s still down after %.0fs — restarting owned process",
        phone_idx,
        getattr(proc, "pid", 0),
        http_port,
        age,
    )
    _terminate_owned_tor(phone_idx)
    return False


def restore_tor_http_for_slots(slots: list[int]) -> dict[str, object]:
    """Start standalone Tor for each slot whose HTTPTunnelPort is down.

    ``slots`` are the 0..N-1 indices inject dials (``http_base + slot``), not
    absolute VM indices. Does not warm unused indices, does not clamp the
    fleet, and does not report a port restored until it accepts TCP.

    Returns restored / started / bootstrapping / still_dead / errors so a
    heal tick cannot treat a swallowed exception or an async warm as success.
    """
    socks_base, http_base = align_bases_to_live_broadcast()
    restored: list[int] = []
    started: list[int] = []
    bootstrapping: list[int] = []
    still_dead: list[int] = []
    errors: list[str] = []
    want = sorted({int(s) for s in slots if int(s) >= 0})
    for slot in want:
        port = int(http_base) + slot
        if _tcp_open(port):
            restored.append(slot)
            continue
        try:
            start_tor_for_phone(slot)
            started.append(slot)
        except Exception as exc:  # noqa: BLE001 — caller must see the failure
            errors.append(f"slot={slot}:{type(exc).__name__}:{exc}")
            still_dead.append(slot)
            continue
        if _tcp_open(port):
            restored.append(slot)
        else:
            bootstrapping.append(slot)
    if restored:
        _broadcast_port_bases()
        _ensure_bases_heartbeat()
    return {
        "socks_base": int(socks_base),
        "http_base": int(http_base),
        "restored": restored,
        "started": started,
        "bootstrapping": bootstrapping,
        "still_dead": still_dead,
        "errors": errors,
    }



def tor_wait_socks_seconds() -> int:
    """Host wait for Tor SOCKS to accept connections (bootstrap can exceed old 45s defaults).

    Override with ``PHARMFLOW_TOR_WAIT_SOCKS`` (seconds). Default **240**.
    A set value is not cut at 600. Values under 5 use 5 so a typo of 0
    does not skip the port check.
    """
    raw = os.environ.get("PHARMFLOW_TOR_WAIT_SOCKS", "").strip()
    if raw:
        try:
            return max(5, int(raw))
        except ValueError:
            pass
    return 240



def tor_wait_http_seconds() -> int:
    """Host wait for ``HTTPTunnelPort`` to accept connections.

    Override with ``PHARMFLOW_TOR_WAIT_HTTP`` (seconds). Default **240**.
    A set value is not cut at 600.
    """
    raw = os.environ.get("PHARMFLOW_TOR_WAIT_HTTP", "").strip()
    if raw:
        try:
            return max(5, int(raw))
        except ValueError:
            pass
    return 240



def tor_wait_bootstrap_seconds() -> int:
    """Host wait for Tor control ``BOOTSTRAP PROGRESS=100`` (or log equivalent).

    Separate from SOCKS/HTTP port waits — a recent background warm that failed bootstrap
    must not shrink this to ~13s. Override with ``PHARMFLOW_TOR_WAIT_BOOTSTRAP``
    (seconds). Default **120**. A set value is not cut at 600.
    """
    raw = os.environ.get("PHARMFLOW_TOR_WAIT_BOOTSTRAP", "").strip()
    if raw:
        try:
            return max(15, int(raw))
        except ValueError:
            pass
    return 120
# Serial → phone index when proxy APIs run (dashboard/teardown bookkeeping).
_tor_slots: dict[str, int] = {}



def _phone_idx_from_prefs_serial_list(serial: str) -> Optional[int]:
    """Tor slot from ``desktop_prefs.json`` ``phone_serials`` list order."""
    try:
        prefs_path = REC_DIR / "desktop_prefs.json"
        if not prefs_path.is_file():
            return None
        data = json.loads(prefs_path.read_text(encoding="utf-8"))
        lst = data.get("phone_serials")
        if not isinstance(lst, list):
            return None
        s = str(serial).strip()
        for i, entry in enumerate(lst):
            if str(entry).strip() == s:
                return int(i)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return None



def order_adb_serials_by_desktop_prefs(serials) -> list[str]:
    """Order ADB serials for Tor slot assignment (``desktop_prefs.json`` ``phone_serials`` first)."""
    want: set[str] = set()
    for entry in serials or []:
        s = str(entry).strip()
        if s:
            want.add(s)
    if not want:
        return []
    ordered: list[str] = []
    seen: set[str] = set()
    try:
        prefs_path = REC_DIR / "desktop_prefs.json"
        if prefs_path.is_file():
            data = json.loads(prefs_path.read_text(encoding="utf-8"))
            lst = data.get("phone_serials")
            if isinstance(lst, list):
                for entry in lst:
                    s = str(entry).strip()
                    if s in want and s not in seen:
                        ordered.append(s)
                        seen.add(s)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    for s in sorted(want - seen):
        ordered.append(s)
    return ordered



def order_phones_by_desktop_prefs(phones: list[dict]) -> list[dict]:
    """Reorder ``list_phones()`` rows to match ``order_adb_serials_by_desktop_prefs``."""
    by_serial = {str(p.get("serial", "")).strip(): p for p in phones if p.get("serial")}
    serials = order_adb_serials_by_desktop_prefs(by_serial.keys())
    return [by_serial[s] for s in serials if s in by_serial]



def phone_idx_from_adb_serial(serial: str) -> int:
    """Map ADB serial to Tor slot index (host ``SocksPort`` / ``HTTPTunnelPort`` offset).

    **Registered:** ``register_tor_slot`` wins (dashboard group start assigns 0..n-1).

    **AVD:** ``emulator-5554`` → ``0``, ``emulator-5556`` → ``1``, … (even port spacing).

    **MuMu-style TCP:** host port in ``16384`` … ``16896`` → ``(port - 16384) // 32``.

    **MuMu guest bridge** (``10.0.2.x:5555``): index from ``desktop_prefs.json``
    ``phone_serials`` order when present; otherwise distinct slots from the guest octet.

    **USB / other:** ``0`` unless registered.

    Keep in sync with wizard ``_wiz_phone_idx_for_tor`` and dashboard callers.
    """
    try:
        s = str(serial).strip()
        if s in _tor_slots:
            return max(0, int(_tor_slots[s]))
        if s.startswith("emulator-"):
            return max(0, (int(s.split("-")[1]) - 5554) // 2)
        if ":" in s:
            port = int(s.rsplit(":", 1)[1])
            if 16384 <= port <= 16896:
                return (port - 16384) // 32
        if _adb_serial_is_mumu_guest_bridge(s):
            idx = _phone_idx_from_prefs_serial_list(s)
            if idx is not None:
                return max(0, idx)
            m = re.match(r"^10\.0\.2\.(\d+):\d+$", s)
            if m:
                # Arbitrary MuMu guest octets (e.g. 187/132/198) must not collapse
                # onto the same Tor slot — old `min(7, octet // 10)` mapped many to 7.
                return int(m.group(1)) % 64
        return 0
    except (IndexError, ValueError):
        return 0




def _proxy_debug() -> bool:
    """Verbose reverse / proxy logging when ``PHARMFLOW_PROXY_DEBUG=1`` or ``PHARMFLOW_OPEN_URL_DEBUG=1``."""
    if os.environ.get("PHARMFLOW_PROXY_DEBUG", "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    return os.environ.get("PHARMFLOW_OPEN_URL_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")



def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")




def _adb_serial_is_mumu_guest_bridge(serial: str) -> bool:
    """True when ADB is addressed as the MuMu guest IP (e.g. ``10.0.2.244:5555`` — discover via ``adb devices`` or PharmFlow.exe → GO).

    On MuMu ARM the connect address is the VM's ``wlan0`` address, not classic AVD
    ``127.0.0.1:5554``. Those guests reach host Tor via ``adb reverse`` +
    ``127.0.0.1:<port>``; ``10.0.2.2`` is **not** routed to the Windows host.
    """
    m = re.match(r"^10\.0\.2\.(\d+):\d+$", str(serial).strip())
    if not m:
        return False
    host_octet = int(m.group(1))
    return host_octet not in (2, 15)



def _serial_looks_like_emulator(serial: str) -> bool:
    """True for AVD / MuMu TCP / common emulator ADB serial patterns."""
    ser = str(serial).strip()
    if re.match(r"^emulator-\d+$", ser):
        return True
    # MuMu bridge/NAT often lists guests as 10.0.2.x:5555 (not 127.0.0.1:16384).
    if ser.startswith("10.0.2.") and ":" in ser:
        return True
    if ":" in ser:
        try:
            port = int(ser.rsplit(":", 1)[1])
            if 16384 <= port <= 16896:
                return True
            if 7555 <= port <= 7600:
                return True
            if 5555 <= port <= 5585 and ser.startswith("127.0.0.1:"):
                return True
        except ValueError:
            pass
    return False



def _use_gateway_proxy_mode(serial: str) -> bool:
    """Never. ``10.0.2.2`` is the host from the guest, which is host-IP egress.

    ``PHARMFLOW_PROXY_LEGACY_GATEWAY`` used to select that path. It does not anymore.
    Every phone is pinned with ``adb reverse`` and ``127.0.0.1``.
    """
    del serial
    return False



def register_tor_slot(serial: str, phone_idx: int) -> None:
    """Remember device order for Tor helpers (used by dashboard proxy routes)."""
    _tor_slots[str(serial)] = int(phone_idx)



def clear_tor_slots() -> None:
    _tor_slots.clear()



def _adb_exe() -> str:
    return adb_executable()



def _shell(serial: str, *args: str, timeout: int = 15) -> subprocess.CompletedProcess:
    exe = _adb_exe()
    try:
        return subprocess.run(
            [exe, "-s", str(serial), "shell", *args],
            capture_output=True,
            text=True,
            errors="replace",  # device output can contain raw bytes — never crash sequence threads on decode
            timeout=timeout,
            **hidden_run_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError) as exc:
        # A slow/unresponsive phone must NEVER kill the sequence thread mid-run.
        # Callers only read .returncode/.stdout — a stub result is the safe path.
        log.debug("tor_manager._shell fallback serial=%s argv≈%s: %s", serial, list(args)[:4], exc)
        return subprocess.CompletedProcess(
            [exe, "-s", str(serial), "shell", *args],
            returncode=1,
            stdout="",
            stderr=str(exc),
        )



def _tor_proxy_host_for_device(serial: str) -> str:
    """Guest proxy host is always loopback.

    ``10.0.2.2`` and ``PHARMFLOW_TOR_PROXY_HOST`` are this PC from the phone.
    The pin is ``adb reverse`` plus ``127.0.0.1``.
    """
    del serial
    return "127.0.0.1"



def _tor_reverse_port_clear_max_idx() -> int:
    """Clear ``adb reverse tcp:(8118+i)`` for ``i`` in ``0..max`` (covers prewarm + farm)."""
    return max(_tor_prewarm_max_idx(), 15)



def _adb_reverse_pairs(serial: str) -> list[tuple[int, int]]:
    """Parse ``adb reverse --list`` → ``[(device_tcp, host_tcp), ...]``."""
    exe = _adb_exe()
    try:
        rr = subprocess.run(
            [exe, "-s", str(serial), "reverse", "--list"],
            capture_output=True,
            text=True,
            errors="replace",  # device output can contain raw bytes — never crash sequence threads on decode
            timeout=12,
            **hidden_run_kwargs(),
        )
        text = (rr.stdout or "") + (rr.stderr or "")
    except Exception:
        return []
    out: list[tuple[int, int]] = []
    for line in text.splitlines():
        m = re.search(r"tcp:(\d+)\s+tcp:(\d+)", line)
        if m:
            out.append((int(m.group(1)), int(m.group(2))))
    return out



def _device_http_proxy_host_port(serial: str) -> tuple[str, int] | None:
    """Read device proxy as ``(host, port)`` or ``None`` when unset."""
    try:
        r = _shell(str(serial), "settings", "get", "global", "http_proxy", timeout=8)
        val = (r.stdout or "").strip()
        if val and val.lower() not in ("null", "none") and ":" in val:
            host, port_s = val.rsplit(":", 1)
            return host.strip(), int(port_s)
        rh = _shell(str(serial), "settings", "get", "global", "global_http_proxy_host", timeout=8)
        rp = _shell(str(serial), "settings", "get", "global", "global_http_proxy_port", timeout=8)
        host = (rh.stdout or "").strip()
        port_s = (rp.stdout or "").strip()
        if host and host.lower() not in ("null", "none") and port_s.isdigit():
            return host, int(port_s)
        return None
    except (ValueError, TypeError, OSError):
        return None



def repair_adb_reverse_for_proxy(serial: str, phone_idx: int) -> dict:
    """Re-establish ``adb reverse`` when ``http_proxy`` uses ``127.0.0.1`` but mapping is missing.

    MuMu / ``adb connect`` drops reverse forwards while ``global http_proxy`` stays set — the
    browser then shows **proxy connection failed** even though Tor is listening on the host.
    """
    ser = str(serial)
    if _use_gateway_proxy_mode(ser):
        return {"repaired": False, "reason": "gateway_mode"}
    host_tunnel = http_proxy_port_for_phone_idx(int(phone_idx))
    if host_tunnel is None:
        return {"repaired": False, "reason": "no_http_tunnel"}
    expected = int(host_tunnel)
    proxy_hp = _device_http_proxy_host_port(ser)
    if proxy_hp is None:
        return {"repaired": False, "reason": "no_http_proxy_set"}
    host, port = proxy_hp
    if host not in ("127.0.0.1", "localhost") or port != expected:
        return {
            "repaired": False,
            "reason": "proxy_not_reverse_mode",
            "http_proxy": f"{host}:{port}",
        }
    rev = _adb_reverse_pairs(ser)
    if any(d == expected and h == expected for d, h in rev):
        return {"repaired": False, "reason": "reverse_ok", "port": expected}
    log.warning(
        "repair_adb_reverse_for_proxy: http_proxy=%s:%s but adb reverse missing — "
        "re-applying serial=%s phone_idx=%s",
        host,
        port,
        ser,
        phone_idx,
    )
    _reverse_tcp_remove(ser, expected)
    ok = _adb_reverse_tcp_pair_with_retries(ser, expected, expected)
    return {
        "repaired": bool(ok),
        "reason": "reapplied" if ok else "reverse_failed",
        "port": expected,
        "adb_reverse_ok": bool(ok),
    }



def _reverse_tcp_remove(serial: str, tcp_port: int) -> None:
    exe = _adb_exe()
    try:
        subprocess.run(
            [exe, "-s", str(serial), "reverse", "--remove", f"tcp:{int(tcp_port)}"],
            capture_output=True,
            text=True,
            errors="replace",  # device output can contain raw bytes — never crash sequence threads on decode
            timeout=12,
            **hidden_run_kwargs(),
        )
    except Exception:
        pass



def _reverse_clear_all_tor_proxy_ports_for_serial(serial: str) -> None:
    """Remove reverse forwards for all Tor HTTP-tunnel indices plus legacy single-port 8118."""
    for i in range(_tor_reverse_port_clear_max_idx() + 1):
        _reverse_tcp_remove(str(serial), HTTP_TUNNEL_BASE + i)
    # Older PharmFlow used a fixed device port (env default 8118) for every phone_idx.
    try:
        legacy = int(os.environ.get("PHARMFLOW_DEVICE_PROXY_PORT", "8118"))
    except ValueError:
        legacy = 8118
    _reverse_tcp_remove(str(serial), legacy)



def _adb_reverse_tcp_pair_with_retries(serial: str, device_tcp: int, host_tcp: int) -> bool:
    """Run ``adb reverse tcp:device tcp:host`` with a few retries (USB/adb races)."""
    exe = _adb_exe()
    ser = str(serial)
    last_err = ""
    for attempt in range(4):
        try:
            rr = subprocess.run(
                [
                    exe,
                    "-s",
                    ser,
                    "reverse",
                    f"tcp:{int(device_tcp)}",
                    f"tcp:{int(host_tcp)}",
                ],
                capture_output=True,
                text=True,
                errors="replace",  # device output can contain raw bytes — never crash sequence threads on decode
                timeout=25,
                **hidden_run_kwargs(),
            )
            if rr.returncode == 0:
                if _proxy_debug():
                    log.info(
                        "adb reverse ok serial=%s tcp:%s→tcp:%s out=%r err=%r",
                        ser,
                        device_tcp,
                        host_tcp,
                        (rr.stdout or "")[:200],
                        (rr.stderr or "")[:200],
                    )
                return True
            last_err = ((rr.stderr or "") + (rr.stdout or "")).strip()[:400]
        except Exception as e:
            last_err = str(e)
        time.sleep(0.15 * (2**attempt))
    log.warning(
        "adb reverse failed after retries serial=%s tcp:%s→tcp:%s last=%s",
        ser,
        device_tcp,
        host_tcp,
        last_err,
    )
    return False



def _reverse_remove_local(serial: str) -> None:
    """Backward-compatible: clear every Tor-related reverse mapping for ``serial``."""
    _reverse_clear_all_tor_proxy_ports_for_serial(serial)


# Android may store proxy in ``http_proxy`` and/or split global_http_proxy_* keys.
_PROXY_GLOBAL_KEYS = (
    "http_proxy",
    "global_http_proxy_host",
    "global_http_proxy_port",
    "global_http_proxy_exclusion_list",
    "global_proxy_pac_url",
)



def clear_all_proxies_on_devices(serials: list) -> list[str]:
    """Refuse. Deleting http_proxy or writing :0 sends farm traffic out the host."""
    log.warning("clear_all_proxies_on_devices refused — will not write http_proxy :0")
    return [str(s) for s in serials if s]



def kick_default_browser_after_proxy_teardown(serials: list) -> None:
    """Force-stop browsers so they drop cached proxy state after ``http_proxy`` is cleared."""
    for serial in serials:
        if not serial:
            continue
        ser = str(serial)
        stopped: set[str] = set()
        try:
            from browser_adb import packages_for_view_url_attempts

            for pkg in packages_for_view_url_attempts(ser, ""):
                if pkg and pkg not in stopped:
                    _shell(ser, "am", "force-stop", pkg, timeout=12)
                    stopped.add(pkg)
        except Exception:
            pass
        if stopped:
            continue
        try:
            pkg = browser_pkg_for_clear(ser, "")
            if pkg:
                _shell(ser, "am", "force-stop", pkg, timeout=12)
        except Exception:
            pass



def _resolve_tor_binary() -> Optional[str]:
    """Resolve the Tor executable path.

    Looks first in ``TOR_DIR`` (where the wizard installs the expert bundle),
    then a legacy ``C:\\Tor`` path, then ``PATH`` (``tor`` / ``tor.exe``).
    Returns ``None`` when no usable binary can be located so callers can fail
    fast with a clear message instead of letting :mod:`subprocess` raise
    ``FileNotFoundError`` deep inside an unrelated stack.
    """
    env_tor = (
        os.environ.get("CPHARM_TOR_PATH") or os.environ.get("PHARMFLOW_TOR_PATH") or ""
    ).strip()
    candidates = [
        str(TOR_DIR / "tor.exe"),
        env_tor,
        r"C:\CPharm\bundled\tor.exe",
        r"C:\PharmFlow\bundled\tor.exe",
        r"C:\CPharm\automation\tor\tor.exe",
        r"C:\PharmFlow\automation\tor\tor.exe",
        r"C:\Tor\tor.exe",
    ]
    if os.name != "nt":
        candidates.append(str(TOR_DIR / "tor"))
    for c in candidates:
        if not c:
            continue
        try:
            p = Path(c)
            if p.is_file():
                # Seed TOR_DIR so the next frozen launch finds it without env.
                try:
                    dest = TOR_DIR / "tor.exe"
                    if p.resolve() != dest.resolve() and not dest.is_file():
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(p, dest)
                except OSError:
                    pass
                return str(p if p.is_file() else TOR_DIR / "tor.exe")
        except OSError:
            continue
    # Last chance: EXE self-heal copies a seed into TOR_DIR.
    try:
        from automation.farm_exe_self_heal import ensure_tor_binary

        ensure_tor_binary()
        seeded = TOR_DIR / "tor.exe"
        if seeded.is_file():
            return str(seeded)
    except Exception:
        pass
    on_path = shutil.which("tor.exe") if os.name == "nt" else shutil.which("tor")
    if on_path is None:
        on_path = shutil.which("tor")
    if on_path:
        return on_path
    log.warning(
        "Tor executable not found in TOR_DIR (%s), legacy C:\\Tor, or PATH; "
        "Tor features will be unavailable until Tor is installed or Tor Browser is running.",
        TOR_DIR,
    )
    return None



def _standalone_tor_proc_alive(phone_idx: int) -> bool:
    proc = _tor_procs.get(phone_idx)
    return proc is not None and proc.poll() is None



def _standalone_tor_binary_available() -> bool:
    return bool(_resolve_tor_binary())



def socks_port_for_phone_idx(phone_idx: int) -> int:
    """SOCKS port that matches :func:`start_tor_for_phone`.

    Standalone Tor uses ``BASE_PORT + slot``. The slot is the roster position
    inject dials, not the absolute VM index. Tor Browser alone exposes SOCKS on
    **9150** only when no standalone ``tor.exe`` is available.
    """
    lane = _slot_index(int(phone_idx))
    if _standalone_tor_proc_alive(lane):
        return BASE_PORT + lane
    if _standalone_tor_binary_available():
        return BASE_PORT + lane
    if _tor_browser_running():
        return 9150
    return BASE_PORT + lane



def http_proxy_port_for_phone_idx(phone_idx: int) -> Optional[int]:
    """Host port for Tor **HTTPTunnelPort** — the slot listener inject dials.

    Returns ``None`` when only Tor Browser is available (SOCKS on 9150, no HTTP tunnel).
    Absolute VM index is not a port offset: vm39 dials ``http_base+0``, not ``+39``.
    """
    lane = _slot_index(int(phone_idx))
    if _standalone_tor_proc_alive(lane):
        return HTTP_TUNNEL_BASE + lane
    if _standalone_tor_binary_available():
        return HTTP_TUNNEL_BASE + lane
    if _tor_browser_running():
        return None
    return HTTP_TUNNEL_BASE + lane


_IP_ECHO_URLS = (
    "https://api.ipify.org",
    "https://icanhazip.com",
    "https://ifconfig.me/ip",
    "https://checkip.amazonaws.com",
)



def fetch_exit_ip(phone_idx: int, timeout: float = 15.0) -> str:
    """Return this phone's Tor **exit IP** as seen by an echo service.

    Requests go through the phone's own HTTPTunnelPort (``127.0.0.1:8118+idx``)
    so the answer is exactly what the site sees for that phone. Returns ``""``
    when the proxy is not reachable or every echo host fails.
    """
    port = http_proxy_port_for_phone_idx(int(phone_idx))
    if port is None:
        return ""
    import urllib.request as _ur
    proxy = f"http://127.0.0.1:{port}"
    for url in _IP_ECHO_URLS:
        try:
            req = _ur.Request(url, headers={"User-Agent": "curl/8"})
            op = _ur.build_opener(_ur.ProxyHandler({"http": proxy, "https": proxy}))
            with op.open(req, timeout=timeout) as resp:
                body = resp.read(512).decode("utf-8", "replace").strip()
            ip = re.sub(r"[^0-9.]", "", body.split("\n")[0])
            if ip:
                return ip
        except Exception:
            continue
    return ""


def country_from_control_reply(text: str) -> str:
    """Two-letter country from a Tor control ``ip-to-country`` reply, or empty."""
    match = re.search(r"ip-to-country/[0-9.]+=([A-Za-z]{2})\b", str(text or ""))
    if not match:
        return ""
    code = match.group(1).upper()
    if code in ("A1", "ZZ"):
        return ""
    return code


def tor_exit_country(phone_idx: int, timeout: float = 8.0) -> str:
    """Country of this phone's Tor exit, read through that phone's own proxy and control port.

    Empty when the exit IP or GeoIP reply is missing. Callers must not invent a host timezone.
    """
    ip = fetch_exit_ip(phone_idx, timeout=timeout)
    if not re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", ip or ""):
        return ""
    lane = _slot_index(int(phone_idx))
    ctrl_port = phone_control_port(phone_idx)
    cookie_path = TOR_DIR / f"data_{lane}" / "control_auth_cookie"
    try:
        raw_cookie = cookie_path.read_bytes()
    except OSError:
        return ""
    if not raw_cookie:
        return ""
    try:
        with socket.create_connection(("127.0.0.1", ctrl_port), timeout=3) as sock:
            sock.settimeout(3.0)
            sock.sendall(b"AUTHENTICATE " + raw_cookie.hex().encode() + b"\r\n")
            auth = b""
            while b"\n" not in auth and len(auth) < 512:
                chunk = sock.recv(256)
                if not chunk:
                    break
                auth += chunk
            if b"250" not in auth:
                return ""
            sock.sendall(b"GETINFO ip-to-country/" + ip.encode("ascii") + b"\r\n")
            resp = b""
            while len(resp) < 1024:
                chunk = sock.recv(256)
                if not chunk:
                    break
                resp += chunk
                if b"552" in resp or b"551" in resp or b"\n250 " in resp:
                    break
    except OSError:
        return ""
    return country_from_control_reply(resp.decode("utf-8", "replace"))



def ensure_unique_exit_ips(
    serials: list[str],
    *,
    max_attempts: int = 4,
    timeout: float = 15.0,
    log_fn=None,
) -> dict:
    """Rotate Tor circuits until every online phone has a **unique** exit IP.

    Tor instances are independent but can converge on the same exit node, so two
    phones can silently share an exit IP (a fingerprinting red flag and a direct
    farm risk). This walks the phones, reads each exit IP through its own proxy,
    and for any duplicate sends ``NEWNYM`` on the later phone(s) until every IP
    is unique (bounded by ``max_attempts`` per phone).

    Returns ``{"unique": bool, "ips": {serial: ip}, "rotations": int}``. Phones
    whose proxy is unreachable keep their last known IP (treated as unique-safe
    for the check; the caller can retry).
    """
    log_fn = log_fn or log.info
    rotations = 0
    for attempt in range(max_attempts):
        ips: dict[str, str] = {}
        for serial in serials:
            s = str(serial).strip()
            idx = phone_idx_from_adb_serial(s)
            ips[s] = fetch_exit_ip(idx, timeout=timeout)
        # Group by IP; unreachable phones ("") are excluded from the uniqueness
        # check (they can't share an IP they haven't got).
        by_ip: dict[str, list[str]] = {}
        for s, ip in ips.items():
            if ip:
                by_ip.setdefault(ip, []).append(s)
        dup_serials: list[tuple[str, int]] = []
        for ip, holders in by_ip.items():
            for extra in holders[1:]:
                dup_serials.append((extra, phone_idx_from_adb_serial(extra)))
        if not dup_serials:
            return {"unique": True, "ips": ips, "rotations": rotations}
        for serial, idx in dup_serials:
            _send_tor_newnym(BASE_PORT + 1000 + idx)
            rotations += 1
            log_fn(
                "rotating duplicate exit IP serial=%s phone_idx=%s (attempt %s)",
                serial,
                idx,
                attempt + 1,
            )
        if attempt < max_attempts - 1:
            time.sleep(2.0)
    return {"unique": False, "ips": ips, "rotations": rotations}



def _random_mac() -> str:
    parts = [random.randint(0x00, 0xFF) for _ in range(6)]
    parts[0] = (parts[0] & 0xFE) | 0x02
    return ":".join(f"{b:02X}" for b in parts)



def _random_imei() -> str:
    digits = [random.randint(0, 9) for _ in range(14)]
    total = sum((d * 2 - 9 if d * 2 > 9 else d * 2) if i % 2 == 1 else d
                for i, d in enumerate(digits))
    check = (10 - (total % 10)) % 10
    return "".join(map(str, digits)) + str(check)



def _tor_browser_running() -> bool:
    """Check if Tor Browser's Tor is already running on 9150."""
    try:
        with socket.create_connection(("127.0.0.1", 9150), timeout=1):
            return True
    except OSError:
        return False



def tor_proxy_preflight() -> dict:
    """
    Return whether we can use Tor: Tor Browser already listening, a known tor.exe
    path, or `tor` on PATH. ok=False in CI is expected when Tor is not installed.
    """
    if _tor_browser_running():
        return {"ok": True, "mode": "tor_browser", "socks_port": 9150}
    exe = _resolve_tor_binary()
    if exe and Path(exe).exists():
        return {"ok": True, "mode": "standalone", "tor_exe": exe}
    return {
        "ok": False,
        "error": "Tor unavailable — install Tor or start Tor Browser",
    }



def start_tor_for_phone(phone_idx: int) -> int:
    """Start a Tor process for this phone's slot. Returns the SOCKS5 port.

    Prefer **standalone** Tor (SOCKS + ``HTTPTunnelPort``) whenever ``tor.exe`` is
    available — even if Tor Browser is already listening on 9150 — because Android's
    system HTTP proxy cannot use SOCKS.

    ``phone_idx`` may be an absolute VM index or an already-resolved slot.
    The process and ports are keyed by :func:`_slot_index` so a heal that passes
    slots and a farm call that passes vm39 bind the same listener inject dials.
    Binding ``base+39`` left slot 0 dead and the tick treated the wrong port as a heal.

    If no standalone binary exists but Tor Browser's SOCKS is up, returns **9150**
    (SOCKS only; :func:`http_proxy_port_for_phone_idx` is then ``None``).
    """
    lane = _slot_index(int(phone_idx))
    lock = _bootstrap_lock_for(lane)
    with lock:
        return _start_tor_for_phone_locked(lane)


def _start_tor_for_phone_locked(phone_idx: int) -> int:
    tor_bin = _resolve_tor_binary()
    socks_port = BASE_PORT + phone_idx
    http_port = HTTP_TUNNEL_BASE + phone_idx
    ctrl_port = BASE_PORT + 1000 + phone_idx

    if tor_bin:
        # A live process object is not a live HTTP tunnel. Adopt only when the
        # port accepts; leave a young bootstrap alone; restart a stale one.
        if _tor_http_ready_or_bootstrapping(phone_idx, http_port):
            return socks_port
    else:
        if _tor_browser_running():
            log.warning(
                "Tor Browser is on port 9150 but no standalone tor executable was "
                "found — SOCKS works for desktop apps; Android ``http_proxy`` needs "
                "HTTPTunnelPort. Install Tor or add tor.exe to PATH."
            )
            return 9150

    if not tor_bin:
        raise RuntimeError(
            "Cannot start Tor: no tor executable found. Install Tor or start Tor Browser."
        )

    data_dir = TOR_DIR / f"data_{phone_idx}"
    data_dir.mkdir(parents=True, exist_ok=True)

    cfg = tempfile.NamedTemporaryFile(
        mode="w", suffix=".cfg", delete=False, dir=str(TOR_DIR)
    )
    cookie_path = data_dir / "control_auth_cookie"
    try:
        # Bind IPv4 explicitly — on some Windows setups implicit binds are flaky for probes.
        cfg.write(f"SocksPort 127.0.0.1:{socks_port}\n")
        cfg.write(f"HTTPTunnelPort 127.0.0.1:{HTTP_TUNNEL_BASE + phone_idx}\n")
        cfg.write(f"ControlPort 127.0.0.1:{ctrl_port}\n")
        cfg.write(f"DataDirectory {data_dir}\n")
        cfg.write(f"CookieAuthentication 1\n")
        cfg.write(f"CookieAuthFile {cookie_path}\n")
        # No country constraint by default — restricting ExitNodes can stall bootstrap when
        # a usable guard for the chosen country isn't quickly found (operator was hitting
        # ``SOCKS not ready within 240s``). Set ``PHARMFLOW_TOR_EXIT_NODES="{us}"`` or similar
        # to constrain again.
        _exit = os.environ.get("PHARMFLOW_TOR_EXIT_NODES", "").strip()
        if _exit:
            cfg.write(f"ExitNodes {_exit}\n")
        cfg.write("StrictNodes 0\n")
        # Surface bootstrap errors in the Tor data dir log (otherwise stdout/stderr are
        # /dev/null, leaving operators blind when bootstrap fails on Windows).
        cfg.write(f"Log notice file {data_dir / 'tor.log'}\n")
    finally:
        cfg.close()

    # CREATE_NO_WINDOW alone is not enough on some Windows hosts — use the
    # shared hidden_run_kwargs (NO_WINDOW + STARTF_USESHOWWINDOW) and burst-hide.
    proc = subprocess.Popen(
        [tor_bin, "-f", cfg.name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **hidden_run_kwargs(),
    )
    if proc.pid:
        hide_console_burst(int(proc.pid))
    _tor_procs[phone_idx] = proc
    _tor_proc_started[phone_idx] = time.monotonic()
    _broadcast_port_bases()
    _ensure_bases_heartbeat()
    return socks_port



def _control_auth_cookie(phone_index: int) -> bytes:
    """Control cookie for this phone's slot, or empty if the instance has none."""
    lane = _slot_index(int(phone_index))
    candidates = [
        TOR_DIR / f"data_{lane}" / "control_auth_cookie",
        TOR_DIR / f"data_{int(phone_index)}" / "control_auth_cookie",
    ]
    try:
        candidates.append(tor_data_path(phone_index) / "control_auth_cookie")
    except Exception:
        pass
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if raw:
            return raw
    return b""


def _control_authenticate(sock: socket.socket, cookie: bytes) -> bool:
    """AUTHENTICATE with a cookie when present, else the empty-password form."""
    if cookie:
        sock.sendall(b"AUTHENTICATE " + cookie.hex().encode() + b"\r\n")
    else:
        sock.sendall(b'AUTHENTICATE ""\r\n')
    auth = sock.recv(256).decode("utf-8", errors="replace")
    if "250" in auth:
        return True
    if cookie:
        return False
    sock.sendall(b"AUTHENTICATE\r\n")
    auth = sock.recv(256).decode("utf-8", errors="replace")
    return "250" in auth


def _send_tor_newnym(ctrl_port: int) -> bool:
    """Send NEWNYM signal to Tor control port to get a fresh circuit.

    Tor writes the control auth cookie after the control port begins listening, so a
    rotate call that arrives in the first second of bootstrap can read an empty cookie
    and silently fail AUTHENTICATE. Poll briefly for a non-empty cookie before
    connecting.
    """
    phone_idx = max(0, ctrl_port - BASE_PORT - 1000)
    cookie_path = TOR_DIR / f"data_{phone_idx}" / "control_auth_cookie"
    cookie = b""
    for _ in range(20):
        try:
            if cookie_path.exists():
                cookie = cookie_path.read_bytes()
                if cookie:
                    break
        except OSError:
            pass
        time.sleep(0.1)
    if not cookie:
        return False
    try:
        with socket.create_connection(("127.0.0.1", ctrl_port), timeout=3) as s:
            if not _control_authenticate(s, cookie):
                return False
            s.sendall(b"SIGNAL NEWNYM\r\n")
            resp = s.recv(256)
            return b"250" in resp
    except OSError:
        return False



def _refuse_guest_proxy_write(proxy_value: str) -> str:
    """Refuse empty, :0, and non-loopback guest proxies. Host gateway is host-IP egress."""
    raw = str(proxy_value or "").strip()
    if not raw or raw.lower() in ("null", "none", ":0") or raw.endswith(":0"):
        return "empty or :0"
    if not raw.startswith("127.0.0.1:"):
        return "not a loopback exit"
    try:
        port = int(raw.split(":", 1)[1])
    except (IndexError, ValueError):
        return "not a loopback exit"
    if port <= 0:
        return "empty or :0"
    return ""


def apply_host_http_proxy_adb(serial: str, phone_idx: int, host_tunnel: int) -> dict:
    """
    Apply a host HTTP tunnel port to the device ``global http_proxy``.

    Used for Tor (``8118 + idx``) and upstream forwarders (``8130 + idx``).
    """
    host_tunnel = int(host_tunnel)
    socks = socks_port_for_phone_idx(phone_idx)
    legacy = _use_gateway_proxy_mode(serial)

    dev_listen: Optional[int] = None
    adb_reverse_ok = True

    if legacy:
        host = _tor_proxy_host_for_device(serial)
        proxy_value = f"{host}:{host_tunnel}"
        proxy_mode = "legacy_gateway"
    else:
        ser = str(serial)
        dev_listen = int(host_tunnel)
        _reverse_tcp_remove(ser, dev_listen)
        adb_reverse_ok = _adb_reverse_tcp_pair_with_retries(ser, dev_listen, int(host_tunnel))
        if not adb_reverse_ok:
            # Do not point the guest at 10.0.2.2 and do not delete http_proxy.
            # Both are host-IP egress. Leave the existing pin; the heal tick
            # restores the listener without opening the host route.
            log.warning(
                "apply_host_http_proxy_adb: adb reverse FAILED serial=%s — "
                "not applying gateway (host-IP egress forbidden); leaving existing pin",
                ser,
            )
            return {
                "socks_port": socks,
                "http_proxy_port": host_tunnel,
                "proxy_host": "127.0.0.1",
                "http_proxy": None,
                "proxy_mode": "adb_reverse",
                "device_proxy_local_port": dev_listen,
                "http_proxy_applied": False,
                "adb_reverse_ok": False,
            }
        proxy_value = f"127.0.0.1:{dev_listen}"
        proxy_mode = "adb_reverse"
        host = "127.0.0.1"

    refused = _refuse_guest_proxy_write(proxy_value)
    if refused:
        log.warning(
            "apply_host_http_proxy_adb refused serial=%s proxy=%s (%s)",
            serial,
            proxy_value,
            refused,
        )
        return {
            "socks_port": socks,
            "http_proxy_port": host_tunnel,
            "proxy_host": host if legacy else "127.0.0.1",
            "http_proxy": None,
            "proxy_mode": proxy_mode,
            "device_proxy_local_port": dev_listen,
            "http_proxy_applied": False,
            "adb_reverse_ok": adb_reverse_ok,
        }

    put_ok = False
    try:
        r = _shell(
            serial,
            "settings",
            "put",
            "global",
            "http_proxy",
            proxy_value,
            timeout=12,
        )
        put_ok = r.returncode == 0
        if not put_ok:
            log.warning(
                "apply_host_http_proxy_adb settings put failed serial=%s proxy=%s rc=%s",
                serial,
                proxy_value,
                r.returncode,
            )
        else:
            log.info(
                "http_proxy serial=%s mode=%s → %s (host tunnel %s)",
                serial,
                proxy_mode,
                proxy_value,
                host_tunnel,
            )
    except Exception as e:
        log.warning("apply_host_http_proxy_adb exception serial=%s: %s", serial, e)
        put_ok = False

    if not put_ok:
        return {
            "socks_port": socks,
            "http_proxy_port": host_tunnel,
            "proxy_host": host if legacy else "127.0.0.1",
            "http_proxy": None,
            "proxy_mode": proxy_mode,
            "device_proxy_local_port": dev_listen,
            "http_proxy_applied": False,
            "adb_reverse_ok": adb_reverse_ok,
        }

    if os.environ.get("PHARMFLOW_PROXY_NO_BROWSER_KICK", "").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        try:
            pkg = browser_pkg_for_clear(str(serial), "")
            if pkg:
                _shell(str(serial), "am", "force-stop", pkg, timeout=12)
        except Exception:
            pass

    return {
        "socks_port": socks,
        "http_proxy_port": host_tunnel,
        "proxy_host": host if legacy else "127.0.0.1",
        "http_proxy": proxy_value,
        "proxy_mode": proxy_mode,
        "device_proxy_local_port": dev_listen,
        "http_proxy_applied": True,
        "adb_reverse_ok": adb_reverse_ok,
    }



def apply_identity_adb(serial: str, phone_idx: int) -> dict:
    """
    Apply Tor ``HTTPTunnelPort`` to the device ``global http_proxy``.

    **Physical USB / Wi-Fi devices:** ``adb reverse`` + ``127.0.0.1:<port>``.

    **MuMu guest-bridge** (``10.0.2.x:5555``, ``x`` not 2 or 15): ``adb reverse`` +
    ``127.0.0.1:<port>`` where ``<port> = 8118 + phone_idx`` (default).

    **Every guest:** ``adb reverse`` plus ``127.0.0.1:<port>``. ``10.0.2.2`` is this PC
    from the phone and is not written.
    """
    host_tunnel = http_proxy_port_for_phone_idx(phone_idx)
    socks = socks_port_for_phone_idx(phone_idx)

    if host_tunnel is None:
        log.warning(
            "apply_identity_adb skipped serial=%s phone_idx=%s — no HTTPTunnelPort on host "
            "(Tor Browser SOCKS-only: install Tor expert bundle / PATH tor.exe for Android http_proxy)",
            serial,
            phone_idx,
        )
        return {
            "socks_port": socks,
            "http_proxy_port": None,
            "proxy_host": None,
            "http_proxy": None,
            "proxy_mode": "skipped_no_http_tunnel",
            "device_proxy_local_port": None,
            "http_proxy_applied": False,
            "adb_reverse_ok": True,
        }

    return apply_host_http_proxy_adb(serial, phone_idx, host_tunnel)



def rotate_identity_adb(serial: str, phone_idx: int) -> dict:
    """
    Rotate this phone's identity:
    1. Request a new Tor circuit (new exit IP) via control port ``SIGNAL NEWNYM``.
    2. Re-apply the device ``http_proxy`` so Android uses the new circuit.

    This does **not** restart the tor process — Tor rotates circuits in-process (see Tor manual:
    control ``NEWNYM``). Use :func:`stop_all` only when tearing Tor down entirely.
    """
    ctrl_port = phone_control_port(int(phone_idx))
    rotated   = _send_tor_newnym(ctrl_port)
    time.sleep(1)
    result = apply_identity_adb(serial, phone_idx)
    result["circuit_rotated"] = rotated
    return result



def ensure_tor_and_proxy_for_phone(serial: str, phone_idx: int) -> dict:
    """
    Ensure standalone Tor for ``phone_idx`` is running and ``settings put global http_proxy`` is applied.

    **Idempotent:** :func:`start_tor_for_phone` is a no-op when that Tor process is already alive.
    Host SOCKS/HTTP waits are serialized per ``phone_idx`` (shared with
    :func:`start_tor_host_bootstrap_background`) so parallel ``open_url`` / group runners do not
    duplicate long polls; a ready :class:`threading.Event` gives a fast path when the prewarm thread
    or a prior caller already completed bootstrap.

    Dashboard groups / the scheduler call this before automation steps unless
    ``PHARMFLOW_SKIP_TOR_WAIT=1``. Tune bootstrap timeouts with ``PHARMFLOW_TOR_WAIT_SOCKS`` /
    ``PHARMFLOW_TOR_WAIT_HTTP`` (seconds).
    """
    register_tor_slot(str(serial), int(phone_idx))
    idx = int(phone_idx)
    # Group/open_url often call warm then ensure immediately — wait for the warm thread so we
    # do not treat an in-flight warm as "recently failed" with a 15s port cap while it is still
    # bootstrapping.
    _join_idx_warm_thread_if_running(idx, min(45.0, float(tor_wait_socks_seconds())))
    try:
        start_tor_for_phone(idx)
    except (RuntimeError, FileNotFoundError) as e:
        log.warning(
            "ensure_tor_ready failed serial=%s — leaving http_proxy "
            "(host-IP egress forbidden): %s",
            serial,
            e,
        )
        return {"ok": False, "error": str(e)}
    ws = tor_wait_socks_seconds()
    wh = tor_wait_http_seconds()
    lane = _slot_index(idx)
    if lane != idx:
        _join_idx_warm_thread_if_running(lane, min(45.0, float(tor_wait_socks_seconds())))
    lock = _bootstrap_lock_for(lane)
    ev = _get_host_ready_event(lane)
    with lock:
        quick_ok = False
        if ev.is_set():
            quick_ok = wait_for_tor(idx, timeout=3) and wait_for_tor_http_tunnel(idx, timeout=3)
            if not quick_ok:
                ev.clear()
        if not quick_ok:
            # A warm worker that just exited (within the last minute) already burned the full
            # ``ws + wh`` budget — don't double-spend it here when the inline caller (open_url) is
            # already on the hot path. Use a short retry instead so a temporary bootstrap failure
            # doesn't block the browser launch for many extra minutes.
            warm_recent = _recent_warm_attempt(idx)
            ws_eff = min(ws, 15) if warm_recent else ws
            wh_eff = min(wh, 15) if warm_recent else wh
            if not wait_for_tor(idx, timeout=ws_eff):
                msg = f"SOCKS not ready within {ws_eff}s"
                if warm_recent:
                    msg += " (after recent prewarm — see PHARMFLOW_TOR_WAIT_SOCKS)"
                proc_exit = _poll_standalone_tor_exit_code(idx)
                if proc_exit is not None:
                    msg += (
                        f"; tor.exe exited (code {proc_exit}) — install Tor expert bundle under "
                        f"{TOR_DIR} or set PATH tor.exe (see {TOR_DIR / f'data_{lane}' / 'tor.log'})"
                    )
                log.warning(
                    "ensure_tor_ready failed serial=%s — leaving http_proxy "
                    "(host-IP egress forbidden): %s",
                    serial,
                    msg,
                )
                return {"ok": False, "error": msg}
            # SOCKS port accepts TCP — verify Tor has fully bootstrapped before http_proxy / browser.
            _boot_budget = tor_wait_bootstrap_seconds()
            if not wait_for_tor_bootstrap(idx, timeout=_boot_budget):
                msg = (
                    f"Tor bootstrap not confirmed within {_boot_budget}s "
                    f"(tune PHARMFLOW_TOR_WAIT_BOOTSTRAP; log {TOR_DIR / f'data_{lane}' / 'tor.log'})"
                )
                log.warning(
                    "ensure_tor_ready failed serial=%s — leaving http_proxy "
                    "(host-IP egress forbidden): %s",
                    serial,
                    msg,
                )
                return {"ok": False, "error": msg}
            if not wait_for_tor_http_tunnel(idx, timeout=wh_eff):
                msg = f"HTTP tunnel not ready within {wh_eff}s"
                if warm_recent:
                    msg += " (after recent prewarm — see PHARMFLOW_TOR_WAIT_HTTP)"
                log.warning(
                    "ensure_tor_ready failed serial=%s — leaving http_proxy "
                    "(host-IP egress forbidden): %s",
                    serial,
                    msg,
                )
                return {"ok": False, "error": msg}
            ev.set()
    repair_adb_reverse_for_proxy(str(serial), idx)
    applied = apply_identity_adb(str(serial), idx)
    if applied.get("proxy_mode") == "emu_gateway_fallback":
        return {
            "ok": False,
            "error": "gateway fallback refused (host-IP egress forbidden)",
        }
    if applied.get("proxy_mode") == "adb_reverse" and not applied.get("adb_reverse_ok", True):
        return {
            "ok": False,
            "error": (
                "adb reverse failed — http_proxy not applied (browser would show proxy connection failed); "
                "see PHARMFLOW_PROXY_DEBUG=1, adb reverse --list, USB debugging / bridge"
            ),
        }
    if applied.get("http_proxy_applied") is False:
        return {
            "ok": False,
            "error": applied.get("error") or "http_proxy not applied",
        }
    http_port = http_proxy_port_for_phone_idx(idx)
    if http_port is None or not _tcp_open(int(http_port)):
        return {
            "ok": False,
            "error": f"http_tunnel_down_after_ensure port={http_port}",
        }
    return {"ok": True}


# Discoverable alias — device browsers load pages through ``global http_proxy``; call before
# ``am start`` VIEW intents when Tor is required so SOCKS/HTTPTunnel and ``adb reverse`` are ready.
ensure_tor_ready = ensure_tor_and_proxy_for_phone



def _poll_standalone_tor_exit_code(phone_idx: int) -> Optional[int]:
    """If our standalone ``tor`` process exited, return exit code; if running or unknown, ``None``."""
    proc = _tor_procs.get(_slot_index(int(phone_idx)))
    if proc is None:
        return None
    return proc.poll()



def _bootstrap_indicated_in_tor_log(phone_idx: int) -> bool:
    """True when Tor's notice log shows bootstrap complete (control-port fallback)."""
    lane = _slot_index(int(phone_idx))
    log_path = TOR_DIR / f"data_{lane}" / "tor.log"
    try:
        if not log_path.is_file():
            return False
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 16384))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return False
    low = tail.lower()
    return (
        "bootstrapped 100%" in low
        or "progress=100" in low
        or "tag=done" in low
        or "summary=done" in low
    )



def _tor_control_bootstrap_response_done(resp: str) -> bool:
    """Parse GETINFO status/bootstrap-phase (formats differ across Tor builds/OS)."""
    if not resp:
        return False
    up = resp.upper()
    if "PROGRESS=100" in up or "TAG=DONE" in up:
        return True
    if "SUMMARY=DONE" in up or "BOOTSTRAPPED 100%" in up:
        return True
    # Some builds embed "Progress 100" in the status line without PROGRESS= key.
    if re.search(r"\bPROGRESS\s*[=:]\s*100\b", resp, re.IGNORECASE):
        return True
    return False



def _check_tor_bootstrap_via_control(phone_idx: int, timeout: float = 30.0) -> bool:
    """Return True when Tor reports bootstrap complete via control port or tor.log.

    Only meaningful for standalone Tor processes (Tor Browser is assumed already
    bootstrapped when running). When the control cookie is slow on Windows, also
    checks the per-index ``tor.log`` tail written by ``start_tor_for_phone``.
    """
    lane = _slot_index(int(phone_idx))
    if not _standalone_tor_proc_alive(lane):
        return True
    if _bootstrap_indicated_in_tor_log(lane):
        return True
    ctrl_port = BASE_PORT + 1000 + lane
    cookie_path = TOR_DIR / f"data_{lane}" / "control_auth_cookie"
    deadline = time.time() + max(1.0, float(timeout))
    while time.time() < deadline:
        if _poll_standalone_tor_exit_code(phone_idx) is not None:
            return False
        if _bootstrap_indicated_in_tor_log(phone_idx):
            return True
        try:
            raw_cookie = cookie_path.read_bytes() if cookie_path.exists() else b""
        except OSError:
            raw_cookie = b""
        if not raw_cookie:
            time.sleep(0.4)
            continue
        try:
            with socket.create_connection(("127.0.0.1", ctrl_port), timeout=3) as s:
                s.settimeout(3.0)
                s.sendall(b"AUTHENTICATE " + raw_cookie.hex().encode() + b"\r\n")
                buf = b""
                while len(buf) < 512 and time.time() < deadline:
                    chunk = s.recv(256)
                    if not chunk:
                        break
                    buf += chunk
                    if b"250" in buf or b"515" in buf:
                        break
                if b"250" not in buf:
                    time.sleep(0.4)
                    continue
                s.sendall(b"GETINFO status/bootstrap-phase\r\n")
                resp_b = b""
                while len(resp_b) < 4096 and time.time() < deadline:
                    chunk = s.recv(512)
                    if not chunk:
                        break
                    resp_b += chunk
                    if b"250" in resp_b and (
                        b"PROGRESS" in resp_b.upper() or b"TAG" in resp_b.upper()
                    ):
                        break
                resp = resp_b.decode("utf-8", errors="replace")
                if _tor_control_bootstrap_response_done(resp):
                    return True
        except OSError:
            pass
        time.sleep(0.5)
    return _bootstrap_indicated_in_tor_log(phone_idx)



def wait_for_tor_bootstrap(phone_idx: int, timeout: int = 120) -> bool:
    """Block until Tor has fully bootstrapped (circuit ready to proxy traffic).

    ``wait_for_tor`` only checks that Tor's SOCKS port **accepts** a TCP connection;
    Tor queues requests internally until bootstrap is complete.  A browser that
    connects while Tor is still bootstrapping will hold its CONNECT tunnel open and
    eventually hit its own proxy-tunnel timeout (≈30 s on Chrome/Android) →
    ``ERR_TIMED_OUT``.  This function uses the control port to verify
    ``BOOTSTRAP PROGRESS=100`` before the browser is launched.
    """
    if not _standalone_tor_proc_alive(phone_idx):
        return True
    deadline = time.time() + max(5, int(timeout))
    while time.time() < deadline:
        if _poll_standalone_tor_exit_code(phone_idx) is not None:
            return False
        remaining = max(3.0, deadline - time.time())
        if _check_tor_bootstrap_via_control(phone_idx, min(remaining, 5.0)):
            return True
        time.sleep(0.5)
    return False



def wait_for_tor(phone_idx: int, timeout: int = 30) -> bool:
    """Wait until Tor's SOCKS port accepts connections on the host (daemon ready)."""
    port = socks_port_for_phone_idx(phone_idx)
    deadline = time.time() + timeout
    while time.time() < deadline:
        code = _poll_standalone_tor_exit_code(phone_idx)
        if code is not None:
            log.error(
                "standalone Tor exited during SOCKS wait (phone_idx=%s, exit=%s) — check tor.exe, "
                "disk space, and %s",
                phone_idx,
                code,
                TOR_DIR / f"data_{phone_idx}",
            )
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.25)
    return False



def wait_for_tor_http_tunnel(phone_idx: int, timeout: int = 30) -> bool:
    """Wait until Tor's HTTP tunnel port is up (matches Android http_proxy target)."""
    port = http_proxy_port_for_phone_idx(phone_idx)
    if port is None:
        log.warning(
            "wait_for_tor_http_tunnel: no HTTPTunnelPort for phone_idx=%s "
            "(standalone tor.exe missing — Tor Browser SOCKS cannot serve Android http_proxy)",
            phone_idx,
        )
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        code = _poll_standalone_tor_exit_code(phone_idx)
        if code is not None:
            log.error(
                "standalone Tor exited during HTTP-tunnel wait (phone_idx=%s, exit=%s)",
                phone_idx,
                code,
            )
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.25)
    return False



def randomize_mac_adb(serial: str) -> dict:
    """
    Randomize the WiFi MAC address of the device.
    Uses a locally-administered unicast MAC (starts with 02:...).
    Requires root (su) on the device.
    """
    mac = _random_mac()
    import re as _re
    if not _re.match(r'^([0-9A-F]{2}:){5}[0-9A-F]{2}$', mac, _re.IGNORECASE):
        return {"mac": mac, "applied": False}
    try:
        _shell(serial, "su", "-c", f"ip link set wlan0 address {mac}", timeout=10)
    except Exception:
        pass
    # Fallback: ip link set without su
    try:
        result = _shell(serial, "ip", "link", "set", "wlan0", "address", mac, timeout=10)
        applied = result.returncode == 0
    except Exception:
        applied = False
    return {"mac": mac, "applied": applied}



def randomize_android_id_adb(serial: str) -> str:
    """
    Generate and set a new random Android ID.
    Android ID is stored at settings/secure/android_id.
    """
    new_id = os.urandom(8).hex()
    try:
        put = _shell(serial, "settings", "put", "secure", "android_id", new_id, timeout=12)
        got = _shell(serial, "settings", "get", "secure", "android_id", timeout=12)
    except Exception:
        return ""
    live = (got.stdout or "").strip().lower()
    if put.returncode != 0 or live != new_id:
        return ""
    return new_id



def randomize_imei_adb(serial: str) -> dict:
    """Randomize the device IMEI (best-effort, requires root).

    Emulator guests (MuMu/redroid) often accept ``su`` — the same path
    :func:`randomize_mac_adb` uses. When root is unavailable this is a silent
    no-op so the farm keeps running without IMEI churn.
    """
    imei = _random_imei()
    applied = False
    for cmd in (
        ["su", "-c", f"setprop gsm.imei {imei}"],
        ["setprop", "gsm.imei", imei],
        ["su", "0", "setprop", "gsm.imei", imei],
    ):
        try:
            r = _shell(serial, *cmd, timeout=8)
            if r.returncode == 0:
                applied = True
                break
        except Exception:
            continue
    return {"imei": imei, "applied": applied}



def full_identity_reset(serial: str, phone_idx: int) -> dict:
    """
    Complete anonymity reset for a phone after a sequence completes.
    1. New Tor circuit (new exit IP)
    2. New Android ID
    3. New MAC address
    4. Clear browser cookies / app data
    """
    # 1. Rotate Tor circuit
    ctrl_port = phone_control_port(int(phone_idx))
    tor_rotated = _send_tor_newnym(ctrl_port)
    time.sleep(0.5)

    # 2. Re-apply proxy to pick up new Tor circuit. A planned port is not a pin.
    applied = apply_identity_adb(serial, phone_idx)
    want = str((applied or {}).get("http_proxy") or "").strip()
    live_proxy = ""
    try:
        live_proxy = (
            _shell(serial, "settings", "get", "global", "http_proxy", timeout=12).stdout or ""
        ).strip()
    except Exception:
        live_proxy = ""
    proxy_pinned = bool(
        want.startswith("127.0.0.1:")
        and not want.endswith(":0")
        and live_proxy == want
    )

    # 3. New Android ID — empty means the guest read did not match.
    new_android_id = randomize_android_id_adb(serial)

    # 4. New MAC (best-effort, requires root)
    mac_result = randomize_mac_adb(serial)

    # 5. New IMEI (best-effort, requires root)
    imei_result = randomize_imei_adb(serial)

    # 6. Clear default-browser session data (not hardcoded Chrome)
    try:
        pkg = browser_pkg_for_clear(serial, "")
        if pkg:
            _shell(serial, "pm", "clear", pkg, timeout=15)
            _shell(serial, "am", "force-stop", pkg, timeout=15)
    except Exception:
        pass

    return {
        "tor_circuit_rotated": tor_rotated,
        "new_android_id": new_android_id,
        "android_id_applied": bool(new_android_id),
        "http_proxy": live_proxy,
        "http_proxy_applied": proxy_pinned,
        "new_mac": mac_result.get("mac", ""),
        "mac_applied": mac_result.get("applied", False),
        "new_imei": imei_result.get("imei", ""),
        "imei_applied": imei_result.get("applied", False),
    }



def stop_all():
    """Stop and clean up all Tor processes.

    ``terminate()`` only sends the signal; without ``wait()`` the process can outlive the
    dashboard and keep ``SocksPort`` / ``HTTPTunnelPort`` bound, so the next startup gets
    ``[WinError 10048] address already in use``. Wait for graceful exit, then kill.
    """
    for idx in list(_tor_procs.keys()):
        proc = _tor_procs.pop(idx, None)
        if not proc or proc.poll() is not None:
            continue
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    log.warning("tor proc idx=%s did not exit after kill", idx)
        except OSError:
            pass
    with _tor_host_ready_lock:
        for _ev in _tor_host_ready_events.values():
            _ev.clear()
        _tor_host_ready_events.clear()
