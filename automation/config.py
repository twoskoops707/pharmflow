"""Central configuration for ports, paths, and runtime constants."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

AUTHOR_WIDTH = 900
AUTHOR_HEIGHT = 1600

# Bump when sequence JSON schema/coords change; runner refuses older files.
REQUIRED_SEQUENCE_VERSION = 3

DASHBOARD_HOST = os.environ.get("CPHARM_DASHBOARD_HOST", "127.0.0.1")
# Prefer CPHARM_PORT (dashboard listen) so CPHARM_DASHBOARD_PORT alone cannot drift.
DASHBOARD_PORT = int(
    os.environ.get("CPHARM_PORT")
    or os.environ.get("CPHARM_DASHBOARD_PORT", "8080")
)

TOR_HTTP_TUNNEL_BASE = int(os.environ.get("CPHARM_TOR_HTTP_BASE", "8118"))
TOR_SOCKS_BASE = int(os.environ.get("CPHARM_TOR_SOCKS_BASE", "9050"))
TOR_CONTROL_BASE = int(os.environ.get("CPHARM_TOR_CONTROL_BASE", "9151"))
_tor_raw = os.environ.get("CPHARM_TOR_DATA", "tor_instances")
TOR_DATA_DIR = Path(_tor_raw) if Path(_tor_raw).is_absolute() else Path(__file__).resolve().parent.parent / "tor_instances"
# Default on: farm must prove exit IP changed, not blind-rotate.
UNIQUE_EXIT_IP_RETRIES = int(os.environ.get("CPHARM_UNIQUE_EXIT_IP_RETRIES", "10") or "10")

MUMU_DEFAULT_WIDTH = 900
MUMU_DEFAULT_HEIGHT = 1600
MUMU_DEFAULT_DPI = 320
ADB_PORT_BASE = 16384
ADB_PORT_STRIDE = 32

BROWSER_MUMU = "com.mumudroid.browser"
BROWSER_CHROMIUM = "org.chromium.chrome"
BROWSER_FIREFOX = "org.mozilla.firefox"
BROWSER_BRAVE = "com.brave.browser"
BROWSER_DUCKDUCKGO = "com.duckduckgo.mobile.android"
# Verified from official Opera ARM64 APK (get.geo.opera.com) aapt badging.
BROWSER_OPERA = "com.opera.browser"
BROWSER_FARMBROWSER = "com.farmbrowser.stealth.debug"
BROWSER_FARMBROWSER_RELEASE = "com.farmbrowser.stealth"

# Path1/2/3 — FarmBrowser only (proxy + identity rotation built-in).
BROWSER_PATH12_WEIGHTS: dict[str, int] = {
    BROWSER_FARMBROWSER: 100,
    BROWSER_FARMBROWSER_RELEASE: 100,
}

def is_skip_fingerprint() -> bool:
    return os.environ.get("CPHARM_SKIP_FINGERPRINT", "").strip() in ("1", "true", "yes")


def sequences_run_allowed() -> bool:
    """False by default — set CPHARM_ALLOW_SEQUENCE_RUNS=1 to execute sequences on devices."""
    return os.environ.get("CPHARM_ALLOW_SEQUENCE_RUNS", "").strip().lower() in ("1", "true", "yes")


def is_browser_only_identity() -> bool:
    """Browser UA via chrome-command-line only — no MuMu setting.json patching on browse."""
    raw = os.environ.get("CPHARM_BROWSER_ONLY_IDENTITY", "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    return True


def is_skip_exit_proxy_clear() -> bool:
    return os.environ.get("CPHARM_SKIP_EXIT_PROXY_CLEAR", "").strip() in ("1", "true", "yes")


def is_proxy_legacy_gateway() -> bool:
    return os.environ.get("CPHARM_PROXY_LEGACY_GATEWAY", "").strip() in ("1", "true", "yes")


def require_unique_exit_ip() -> bool:
    """HARDCODED on — every sequence must prove a new Tor exit IP. Env cannot disable."""
    return True


def never_share_exit_ip_concurrent() -> bool:
    """HARDCODED on — two online farm phones must never share the same public IP."""
    return True


SKIP_FINGERPRINT = is_skip_fingerprint()
SKIP_EXIT_PROXY_CLEAR = is_skip_exit_proxy_clear()
PROXY_LEGACY_GATEWAY = is_proxy_legacy_gateway()
REQUIRE_UNIQUE_EXIT_IP = require_unique_exit_ip()
NEVER_SHARE_EXIT_IP = never_share_exit_ip_concurrent()

CHROMIUM_DOWNLOAD_URL = "https://download-chromium.appspot.com/dl/Android_arm64?type=apk"

# Playlist modes
PLAYLIST_ORDERED = "ordered"
PLAYLIST_RANDOM = "random"
PLAYLIST_SERIES = "series"

# Shuffle options
SHUFFLE_NONE = "none"
SHUFFLE_SET_A = "set_a"
SHUFFLE_SET_B = "set_b"
SHUFFLE_BOTH_SEPARATELY = "both_sets_separately"
SHUFFLE_COMBINED = "combined"


@dataclass
class PhoneConfig:
    name: str
    index: int
    adb_serial: str = ""
    tor_http_port: int = 0
    tor_socks_port: int = 0
    group: str = "default"
    width: int = MUMU_DEFAULT_WIDTH
    height: int = MUMU_DEFAULT_HEIGHT
    runtime_width: int = MUMU_DEFAULT_WIDTH
    runtime_height: int = MUMU_DEFAULT_HEIGHT

    def __post_init__(self) -> None:
        if not self.tor_http_port:
            self.tor_http_port = TOR_HTTP_TUNNEL_BASE + self.index
        if not self.tor_socks_port:
            self.tor_socks_port = TOR_SOCKS_BASE + self.index


def tor_config_path(phone_index: int, base: Path | None = None) -> Path:
    root = base or TOR_DATA_DIR
    return Path(root) / f"phone_{phone_index}" / "torrc"


def tor_data_path(phone_index: int, base: Path | None = None) -> Path:
    root = base or TOR_DATA_DIR
    return Path(root) / f"phone_{phone_index}" / "data"


# ==== merged from cpharm automation/config.py (dashboard/scheduler constants) ====

def _env_int(name: str, default: int, *, lo: int = 1, hi: int = 65535) -> int:
    try:
        v = int(os.environ.get(name, str(default)))
        return max(lo, min(hi, v))
    except (TypeError, ValueError):
        return max(lo, min(hi, default))



PORT = _env_int("CPHARM_PORT", 8080)

WS_PORT = _env_int("CPHARM_WS_PORT", PORT + 1)

# CPHARM_OFFLINE=1: wizard server start skips pip (use when deps already installed / no network).
# CPHARM_WIZARD_AUTO_INSTALL=0: disable hands-free install on the “Install tools” wizard page.
# Does not disable the dashboard itself — still requires websockets + psutil in the Python env.

# Listen address for HTTP + WebSocket (127.0.0.1 default). Use 0.0.0.0 for LAN phones — firewall permitting.
_BIND_RAW = os.environ.get("CPHARM_BIND") or os.environ.get("CPHARM_HOST") or "127.0.0.1"

BIND = _BIND_RAW.strip() or "127.0.0.1"

APK_DIR = Path(__file__).resolve().parent.parent / "apks"



def _automation_data_base() -> Path:
    """Directory for writable automation data (``recordings/``, ``tor/``)."""
    here = Path(__file__).resolve().parent
    if not getattr(sys, "frozen", False):
        return here
    env = (os.environ.get("CPHARM_HOME") or "").strip()
    if env:
        p = Path(env).expanduser() / "automation"
        if p.is_dir():
            return p
    exe_dir = Path(sys.executable).resolve().parent
    for p in (exe_dir / "automation", Path.home() / "CPharm" / "automation"):
        try:
            if (p / "dashboard.py").is_file() or (p / "recordings").exists():
                return p
        except OSError:
            continue
    return here


_auto_data = _automation_data_base()

REC_DIR = _auto_data / "recordings"

TOR_DIR = _auto_data / "tor"

# ADB ports to auto-connect on startup (covers AVD + common third-party emulators)
# AVD emulators launched by the wizard use even ports starting at 5554:
#   Phone 1 → 5554,  Phone 2 → 5556,  Phone 3 → 5558,  ... up to Phone 10 → 5572
# Other emulators: BlueStacks 5 (5555), BlueStacks instances (5565-5585),
#   MEmu (21503), NOX (62001), Genymotion (7555)
# Same JSON sequences; per-device timing/tap variance. Default ON for wizard/dashboard runs.
# Override with CPHARM_HUMAN_VARIATION=0 to disable.

HUMAN_VARIATION_FORCE = True

def _human_variation_enabled() -> bool:
    env = (os.environ.get("CPHARM_HUMAN_VARIATION") or "").strip().lower()
    if env in ("0", "false", "no", "off"):
        return False
    if env in ("1", "true", "yes", "on"):
        return True
    return HUMAN_VARIATION_FORCE



HUMAN_VARIATION = _human_variation_enabled()

# Daily scheduler: how fire times are placed in the 24h local window.
# "organic" = uneven bursts (Dirichlet/Gamma spacings — not equal intervals).
# "uniform" = classic random points then sort (legacy).
_ss = os.environ.get("CPHARM_SCHEDULE_SPREAD", "organic").strip().lower()

SCHEDULE_SPREAD = "uniform" if _ss in ("uniform", "classic", "flat") else "organic"

# When true, daily fire times are only placed in “daytime” in the *Tor exit country* (see scheduler + tor_manager).
# Avoids 3am US local fire times when the exit is in Europe/Asia, etc. Requires PySocks + working Tor per phone.

SCHED_TOR_LOCAL = os.environ.get("CPHARM_SCHED_TOR_LOCAL", "0").lower() in (
    "1", "true", "yes", "on",
)
# Inclusive local hours in the exit country (0–23). Default ≈ wake → late evening.

def _ih(name: str, default: int) -> int:
    try:
        v = int(os.environ.get(name, str(default)))
        return max(0, min(23, v))
    except (TypeError, ValueError):
        return default



SCHED_ACTIVE_HOUR_START = _ih("CPHARM_SCHED_ACTIVE_START", 7)

SCHED_ACTIVE_HOUR_END = _ih("CPHARM_SCHED_ACTIVE_END", 23)
# If geo lookup fails, use this IANA zone for the active-hour filter (default UTC band).

SCHED_FALLBACK_TZ = os.environ.get("CPHARM_SCHED_FALLBACK_TZ", "Etc/UTC").strip() or "Etc/UTC"


EMULATOR_PORTS = [
    # AVD emulators — even ports, 5554 through 5572 (supports 10 phones)
    ("127.0.0.1", 5554),
    ("127.0.0.1", 5556),
    ("127.0.0.1", 5558),
    ("127.0.0.1", 5560),
    ("127.0.0.1", 5562),
    ("127.0.0.1", 5564),
    ("127.0.0.1", 5566),
    ("127.0.0.1", 5568),
    ("127.0.0.1", 5570),
    ("127.0.0.1", 5572),
    # BlueStacks 5
    ("127.0.0.1", 5555),
    ("127.0.0.1", 5565),
    ("127.0.0.1", 5575),
    ("127.0.0.1", 5585),
    # MEmu
    ("127.0.0.1", 21503),
    # NOX Player
    ("127.0.0.1", 62001),
    # Genymotion
    ("127.0.0.1", 7555),
    # MuMu 12 — 16384 + n*32 (up to 32 instances; farms regularly exceed 10)
    *[( "127.0.0.1", 16384 + i * 32) for i in range(32)],
]
