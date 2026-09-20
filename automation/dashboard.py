"""
PharmFlow Dashboard — ADB-native backend.
Works with any Android device: AVD emulators, BlueStacks, Genymotion, MEmu, NOX, real phones.

Launch (Windows): double-click automation/run_dashboard.bat or start_dashboard.bat — both ``cd``
to ``automation/`` first so ``dashboard.html`` / config paths resolve next to ``dashboard.py``.

Ports and default bind are set in ``config.py``. **Primary HTTP port** is ``PHARMFLOW_PORT`` (default 8080);
``PHARMFLOW_WS_PORT`` defaults to HTTP+1. If the HTTP bind fails with address-in-use (Windows WinError 10048,
Unix EADDRINUSE / errno 98), the server tries the next ports up to ``PHARMFLOW_PORT_TRY_COUNT`` attempts (default 20).
WebSocket binds to the configured WS port unless that equals the chosen HTTP port, then the next free port is used.
If ``PHARMFLOW_HOST`` is set, it overrides the bind address for HTTP/WebSocket and the ``bind`` field in ``/api/config``
(otherwise ``BIND`` from config is used). For unattended Windows launches, ``PHARMFLOW_UNATTENDED=1`` makes
``start_dashboard.bat`` skip the final ``pause``.
"""

import sys, io


def _force_utf8_stdio() -> None:
    """Force UTF-8 stdio without closing the streams we replace.

    Wrapping ``sys.stdout.buffer`` directly orphans the original TextIOWrapper,
    which closes its underlying fd when garbage-collected — that breaks any
    host that owns fd 1/2 (pytest capture, frozen apps). ``detach()`` moves the
    buffer out of the old wrapper so it can never close it.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        enc = (getattr(stream, "encoding", "") or "").lower()
        if stream is None or "utf-8" in enc or not hasattr(stream, "detach"):
            continue
        try:
            setattr(
                sys,
                name,
                io.TextIOWrapper(stream.detach(), encoding="utf-8", errors="replace", line_buffering=True),
            )
        except Exception:
            continue


_force_utf8_stdio()

import automation.no_window  # noqa: E402,F401  — CREATE_NO_WINDOW for adb/tor children
from automation.session_notes_uia import (  # noqa: E402
    dismiss_session_notes_verified,
    step_wants_session_notes_dismiss,
    step_wants_session_notes_gone,
    wait_session_notes_gone,
)

import datetime
from zoneinfo import ZoneInfo
import asyncio
import base64
import errno
import concurrent.futures
from dataclasses import dataclass
import json
import logging
import mimetypes
import os
import re
import socket
import subprocess
import time
import random
import threading
import urllib.parse
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
for _p in (SCRIPT_DIR, REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from automation.earn_plan import (  # noqa: E402
    compute_earn_plan,
    load_earn_plan,
    save_earn_plan,
)

try:
    from websockets.server import serve
except ImportError as e:
    print(
        "  [pharmflow] Missing Python dependency (websockets).\n"
        "           Install with:  py -3 -m pip install --user \"websockets>=12.0\"\n"
        "           Offline/air-gap: pre-install wheels into this environment, or use a venv.\n",
        file=sys.stderr,
    )
    raise SystemExit(1) from e

import tor_manager
import mumu_fingerprint
import teach as teach_mod
import playstore as ps_mod  # legacy — not linked from dashboard.html operator UI
from config import PORT, WS_PORT, BIND, APK_DIR, REC_DIR

# Config defaults (``PHARMFLOW_PORT`` / ``PHARMFLOW_WS_PORT``). Runtime listen ports may differ after bind fallback.
CONFIG_HTTP_PORT = PORT
CONFIG_WS_PORT = WS_PORT
LISTEN_HTTP_PORT = PORT
LISTEN_WS_PORT = WS_PORT
from sequence_normalize import (
    normalize_automation_steps,
    step_is_fast_phase,
    step_is_timer_complete_wait,
)
from sequence_geometry import (
    SEQUENCE_BASE_H,
    SEQUENCE_BASE_W,
    baseline_from_step,
    baseline_y_to_screen_y,
    normalize_step_baseline,
    parse_wm_size_output,
    scale_point,
)
from device_open_url import am_start_view_url_argv
from adb_paths import adb_executable
from adb_wrapper import AdbWrapper
from browse_proxy import guest_proxy_healthy, pin_guest_proxy
from browser_adb import (
    _pkg_is_chrome_family,
    am_start_reported_landing,
    apk_install_reported,
    monkey_launch_reported,
    pm_clear_reported,
    browser_pkg_for_clear,
    invalidate_webview_inset_cache,
    looks_like_package,
    packages_for_view_url_attempts,
    webview_content_top_inset,
)
import human_variation as _hv
from sequence_playlist import (
    estimate_step_count,
    is_playlist_cycle_end,
    normalize_playlist_ref,
    playlist_cycle_length,
    resolve_step_chunks,
    resolve_steps,
)
from wizard.wizard_paths import sequences_dir as _sequences_dir

logging.basicConfig(level=logging.INFO, format="  %(message)s")
log = logging.getLogger("pharmflow")

LISTEN_HOST = os.environ.get("PHARMFLOW_HOST", "").strip() or BIND

# Quick actions are fixed shortcuts (not sequence-scaled); tune per farm if needed.
_QUICK_ACTIONS = {
    "swipe_up":     ("shell", "input", "swipe", "640", "700", "640", "200", "400"),
    "swipe_down":   ("shell", "input", "swipe", "640", "200", "640", "700", "400"),
    "swipe_left":   ("shell", "input", "swipe", "900", "360", "100", "360", "400"),
    "swipe_right":  ("shell", "input", "swipe", "100", "360", "900", "360", "400"),
    "home":         ("shell", "input", "keyevent", "3"),
    "lock":         ("shell", "input", "keyevent", "26"),
    "wake":         ("shell", "input", "keyevent", "224"),
    "clear_recents":("shell", "input", "keyevent", "187"),
}

_ws_clients: set = set()
_teach_state    = {"state": "idle", "file": None}
_running_groups: dict[str, bool] = {}
# Phones whose Tor could not be brought up during group preflight — skipped this
# pass instead of aborting the whole farm (one bad phone used to stop everyone).
_group_skip_serials: set[str] = set()
_app_cache:      dict[str, dict]  = {}
_app_cache_time: dict[str, float] = {}
APP_CACHE_TTL = 30.0
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=32)

# ``adb shell wm size`` per serial — short TTL to limit ADB traffic during step loops
_wm_size_cache: dict[str, tuple[float, tuple[int, int] | None]] = {}
_WM_SIZE_CACHE_TTL = 60.0

# TCP ADB serials (e.g. 10.0.2.66:5555 / 127.0.0.1:16384) — reconnect when the host drops the session.
_TCP_ADB_SERIAL_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}:\d{2,5}$")
_device_preflight_ok_at: dict[str, float] = {}
_DEVICE_PREFLIGHT_TTL_SEC = 2.0
_device_tcp_miss_streak: dict[str, int] = {}
_tcp_reconnect_burst_log_at: dict[str, float] = {}
# After Tor apply / group preflight, avoid ``adb connect`` churn that drops MuMu TCP sessions.
_adb_post_tor_grace_until: dict[str, float] = {}
_inject_events_doc_hint_logged = False
_inject_actionable_logged: set[str] = set()
_adb_session_start_server_attempted = False
# Cooldown (seconds) between ADB-server restarts — the server can wedge repeatedly
# under 7-phone concurrency, so allow recovery more than once per process, but
# never tighter than this (prevents a kill/start loop).
_adb_server_recover_min_gap = 60.0
_adb_server_recover_last: float = 0.0

# Last ADB failures from group runs (thread-safe; for /api/groups/run response note + GET).
_group_adb_errors: list[dict] = []
_group_adb_errors_lock = threading.Lock()
_GROUP_ADB_ERRORS_MAX = 80

# Last-run status per (group, serial) for the live /api/groups/status panel.
_group_phone_runs: dict[tuple[str, str], dict] = {}
_group_phone_runs_lock = threading.Lock()


def _set_phone_run(group_name: str, serial: str, **fields) -> None:
    with _group_phone_runs_lock:
        _group_phone_runs[(group_name, serial)] = {
            "serial": serial,
            "group": group_name,
            "updated_utc": time.time(),
            "state": "idle",
            "iteration": 0,
            "result": "",
            **fields,
        }


def _get_phone_runs() -> list[dict]:
    with _group_phone_runs_lock:
        return [dict(v) for v in _group_phone_runs.values()]


def _group_finish_log(name: str) -> str:
    """Finish line for a group run. Never a checkmark, and never 'done' with no completed phone."""
    if not _running_groups.get(name):
        return f"[{name}] Stopped"
    runs = [r for r in _get_phone_runs() if r.get("group") == name]
    failed = [r for r in runs if r.get("state") == "error"]
    completed = [
        r for r in runs if r.get("state") == "done" and r.get("result") == "completed"
    ]
    if not completed:
        extra = f" ({len(failed)} failed)" if failed else ""
        return f"[{name}] Finished with no completed phones{extra}"
    if failed:
        return f"[{name}] Finished — {len(completed)} phone(s) completed, {len(failed)} failed"
    return f"[{name}] Finished — {len(completed)} phone(s) completed"


def _load_groups_cfg() -> tuple[dict | None, str]:
    """Read groups_config.json. A bad file is left on disk, not replaced with []."""
    if not GROUPS_CFG.exists():
        return None, "no groups_config.json found — create a group below"
    try:
        cfg = json.loads(GROUPS_CFG.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError):
        return None, "groups_config.json could not be read — the file was not replaced"
    if not isinstance(cfg, dict) or not isinstance(cfg.get("groups"), list):
        return None, "groups_config.json could not be read — the file was not replaced"
    return cfg, ""


def _persist_groups_cfg(cfg: dict) -> bool:
    """Write groups_config.json and keep the claim only if the disk copy matches."""
    expected = cfg.get("groups")
    if not isinstance(expected, list):
        return False
    try:
        REC_DIR.mkdir(parents=True, exist_ok=True)
        GROUPS_CFG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        stored = json.loads(GROUPS_CFG.read_text(encoding="utf-8"))
    except (OSError, TypeError, json.JSONDecodeError, UnicodeError, ValueError):
        return False
    return stored.get("groups") == expected


# Per-phone live stealth-panel state (exit IP, disguise, fingerprint, rotation count).
_stealth_state: dict[str, dict] = {}
_stealth_lock = threading.Lock()
_STEALTH_IP_TTL = 20.0


def _stealth_exit_ip(serial: str, idx: int) -> str:
    """Best-effort fetch of this phone's Tor exit IP, cached for ``_STEALTH_IP_TTL``."""
    now = time.time()
    with _stealth_lock:
        st = _stealth_state.get(serial)
        if st and st.get("exit_ip") and now - st.get("exit_ts", 0) < _STEALTH_IP_TTL:
            return st["exit_ip"]
    ip = tor_manager.fetch_exit_ip(idx, timeout=7.0)
    with _stealth_lock:
        st = _stealth_state.setdefault(serial, {})
        st["exit_ip"] = ip
        st["exit_ts"] = time.time()
    return ip


def _stealth_cached_exit_ip(serial: str) -> str:
    """Read-only peek at the cached exit IP — never does network I/O (safe for the server loop)."""
    with _stealth_lock:
        st = _stealth_state.get(serial)
        if st and st.get("exit_ip"):
            return st["exit_ip"]
    return ""


def _set_phone_stealth(serial: str, **fields) -> None:
    with _stealth_lock:
        _stealth_state.setdefault(serial, {}).update(fields)


def _bump_phone_rotation(serial: str) -> None:
    with _stealth_lock:
        st = _stealth_state.setdefault(serial, {})
        st["rotation_count"] = st.get("rotation_count", 0) + 1


def _identity_reset_landed(result: dict | None) -> bool:
    """A new circuit is not a reset unless the guest read is the written loopback exit."""
    result = result or {}
    return bool(result.get("tor_circuit_rotated")) and bool(result.get("http_proxy_applied"))


def _identity_reset_log(label: str, result: dict | None) -> str:
    """Finish line for a reset. Success means a new circuit and a pinned guest exit."""
    result = result or {}
    proxy = str(result.get("http_proxy") or "").strip()
    if _identity_reset_landed(result):
        return f"{label} identity reset — new Tor circuit on {proxy}"
    if result.get("tor_circuit_rotated") and not result.get("http_proxy_applied"):
        return (
            f"{label} identity reset failed — circuit changed but the guest exit was not pinned"
            + (f" ({proxy})" if proxy else "")
        )
    return f"{label} identity reset failed — no new Tor circuit"


def _get_stealth_payload() -> list[dict]:
    """Per-phone live stealth snapshot for the Run page panel.

    Exit IPs are served from the warm cache (never blocks the server loop); missing
    ones are kicked off on a best-effort background thread and appear on the next poll.
    Disguise / fingerprint / rotation counts come from the last assessed run state.
    """
    rows = []
    for p in list_phones():
        if not p["running"]:
            continue
        serial = p["serial"]
        idx = _phone_idx_from_serial(serial)
        ip = _stealth_cached_exit_ip(serial)
        if not ip:
            threading.Thread(target=_stealth_exit_ip, args=(serial, idx), daemon=True).start()
        with _stealth_lock:
            st = _stealth_state.get(serial, {})
        disguise = st.get("disguise", "")
        if not disguise:
            try:
                prof = mumu_fingerprint.profile_for_serial(serial, farm_index=idx)
                if prof and prof.get("brand") and prof.get("model"):
                    disguise = f"{prof['brand']} {prof['model']}"
                    _set_phone_stealth(serial, disguise=disguise)
            except Exception:
                disguise = ""
        rows.append({
            "serial": serial,
            "name": p["name"],
            "exit_ip": ip,
            "ip_online": bool(ip),
            "disguise": disguise or "—",
            "fp_state": st.get("fp_state", "not-assessed"),
            "leak_count": st.get("leak_count", 0),
            "rotation_count": st.get("rotation_count", 0),
        })
    return rows


# Real dabflow farm-visit tally: bumped on every successful getdabflow ``open_url``.
# Persisted so the money KPI strip shows actual farm traffic even before the operator
# exports Mantis numbers (POST /api/scorecard/mantis).
_farm_visits_tally: dict[str, int] = {}
_farm_visits_lock = threading.Lock()
_farm_visits_last_write = 0.0


def _tally_today_key() -> str:
    """Pacific day, same day Mantis uses. A UTC date splits today's visits at 5pm."""
    return datetime.datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


def _load_farm_visits_tally() -> dict[str, int]:
    try:
        p = REC_DIR / "farm_visits.json"
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): int(v) for k, v in data.items()}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return {}


def _farm_visits_today() -> int:
    with _farm_visits_lock:
        return _farm_visits_tally.get(_tally_today_key(), 0)


def _bump_farm_visit(serial: str) -> None:
    """Increment today's real dabflow visit counter and persist (throttled)."""
    global _farm_visits_last_write
    with _farm_visits_lock:
        _farm_visits_tally[_tally_today_key()] = _farm_visits_tally.get(_tally_today_key(), 0) + 1
        now = time.time()
        if now - _farm_visits_last_write < 10.0:
            return
        _farm_visits_last_write = now
        try:
            p = REC_DIR / "farm_visits.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(_farm_visits_tally, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass


def _stealth_warm_exit_ips() -> None:
    """Daemon loop: refresh per-phone exit IPs so the panel never blocks the server."""
    while True:
        try:
            for p in list_phones():
                if not p["running"]:
                    continue
                _stealth_exit_ip(p["serial"], _phone_idx_from_serial(p["serial"]))
        except Exception:
            log.debug("stealth warm pass failed", exc_info=True)
        time.sleep(12.0)


# Background exit-IP uniqueness verification (triggered by /api/stealth/verify,
# run off the event loop so a slow multi-phone rotate can never freeze the server).
_stealth_verify_lock = threading.Lock()
_stealth_verify_running = False
_stealth_verify_last: dict = {}


def _start_exit_ip_verification_if_idle() -> None:
    """Kick a background uniqueness verify if none is running and the feature is enabled."""
    global _stealth_verify_running
    with _stealth_verify_lock:
        if (
            not _stealth_verify_running
            and _unique_exit_ips_enabled()
            and not _pharmflow_skip_tor_wait()
        ):
            _stealth_verify_running = True
            threading.Thread(target=_run_exit_ip_verification, daemon=True).start()


def _run_exit_ip_verification() -> None:
    global _stealth_verify_running, _stealth_verify_last
    try:
        serials = [p["serial"] for p in list_phones() if p["running"]]
        if not serials:
            _stealth_verify_last = {"ok": True, "unique": True, "rotations": 0, "ips": {}, "phones": 0}
            return
        uniq = tor_manager.ensure_unique_exit_ips(serials, max_attempts=3, timeout=10.0)
        _stealth_verify_last = {"ok": True, "phones": len(serials), **uniq}
        log.info(
            "[stealth] background exit-IP verification: unique=%s rotations=%s",
            uniq.get("unique"), uniq.get("rotations"),
        )
    except Exception as exc:  # noqa: BLE001
        _stealth_verify_last = {"ok": False, "error": str(exc)}
        log.debug("stealth exit-IP verification failed", exc_info=True)
    finally:
        _stealth_verify_running = False



def _groups_status_running_names() -> list[str]:
    """Names of groups whose runner flag is still True (not stopped / finished)."""
    return sorted(k for k, v in _running_groups.items() if v)


def _interruptible_sleep(seconds: float, running_check) -> None:
    """Sleep up to ``seconds``, returning early when ``running_check()`` is false."""
    if seconds <= 0:
        return
    deadline = time.time() + float(seconds)
    while time.time() < deadline:
        if not running_check():
            return
        time.sleep(min(0.5, max(0.0, deadline - time.time())))


def _group_playlist_cycle_len(group: dict) -> int:
    pl_min = 1
    pmap = group.get("phones") or {}
    if isinstance(pmap, dict):
        for ent in pmap.values():
            if isinstance(ent, dict):
                pl_min = max(pl_min, playlist_cycle_length(ent))
    return pl_min


def _group_series_mode(group: dict) -> bool:
    pmap = group.get("phones") or {}
    if not isinstance(pmap, dict):
        return False
    for ent in pmap.values():
        if isinstance(ent, dict) and (ent.get("sequence_playlist_mode") or "").strip().lower() in (
            "series",
            "folder",
            "folder_random",
        ):
            return True
    return False


def _iteration_start_pause_seconds(group: dict, iteration: int, rng: random.Random) -> float:
    """Pause before a new group iteration (between playlist slots or repeat cycles)."""
    if iteration <= 0:
        return 0.0
    if _group_series_mode(group):
        return _hv.playlist_cycle_pause_seconds(rng)
    pl_cycle = _group_playlist_cycle_len(group)
    if pl_cycle <= 1:
        return _hv.playlist_cycle_pause_seconds(rng)
    if iteration % pl_cycle == 0:
        return _hv.playlist_cycle_pause_seconds(rng)
    return _hv.sequence_start_gap_seconds(rng)


HTML_FILE      = SCRIPT_DIR / "dashboard.html"
PLAYSTORE_FILE = SCRIPT_DIR / "playstore.html"
GROUPS_CFG     = REC_DIR / "groups_config.json"
DESKTOP_PREFS  = REC_DIR / "desktop_prefs.json"

# Matches wizard `DEFAULT_HITS_PER_DAY` — per-phone daily scheduler quota default
DEFAULT_HITS_PER_DAY = 720


def _desktop_prefs_for_api() -> dict:
    """Optional flags from ``desktop_prefs.json`` (e.g. Tor proxy configured). Merged into ``/api/config``."""
    if not DESKTOP_PREFS.exists():
        return {}
    try:
        data = json.loads(DESKTOP_PREFS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict = {}
    v = data.get("tor_proxy_configured")
    if isinstance(v, bool):
        out["tor_proxy_configured"] = v
    mode = data.get("browse_proxy_mode")
    if isinstance(mode, str) and mode.strip():
        out["browse_proxy_mode"] = mode.strip().lower()
    # Legacy key — was mislabeled as browser stealth; means Tor proxy was configured.
    legacy = data.get("stealth_enabled")
    if isinstance(legacy, bool) and "tor_proxy_configured" not in out:
        out["tor_proxy_configured"] = legacy
    # Stealth settings persisted from the dashboard so they survive restarts
    # and are visible to the GUI via /api/config.
    for name in ("rotate_every_sequence", "unique_exit_ips"):
        pv = data.get(name)
        if isinstance(pv, bool):
            out[name] = pv
    return out


# ── ADB helpers ───────────────────────────────────────────────────────────────

_ADB_SUBPROC_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _adb_truthy_env(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes")


def _adb_env_disabled(name: str) -> bool:
    """True only when the env var is explicitly set to a falsey value (0/no/false)."""
    return (os.environ.get(name) or "").strip().lower() in ("0", "false", "no", "off")


def _adb_debug_enabled() -> bool:
    return _adb_truthy_env("PHARMFLOW_ADB_DEBUG")


def _adb_debug(msg: str, *args) -> None:
    if _adb_debug_enabled():
        log.info("[adb-debug] " + msg, *args)


def _adb_post_tor_grace_seconds() -> float:
    raw = (os.environ.get("PHARMFLOW_ADB_POST_TOR_GRACE_SEC") or "12").strip()
    try:
        return min(60.0, max(0.0, float(raw)))
    except (TypeError, ValueError):
        return 12.0


def note_adb_serial_tor_settled(serial: str) -> None:
    """Mark *serial* as recently Tor/proxy-ready — suppresses aggressive TCP reconnect churn."""
    if not serial:
        return
    grace = _adb_post_tor_grace_seconds()
    if grace <= 0:
        return
    _adb_post_tor_grace_until[str(serial)] = time.time() + grace
    _device_preflight_ok_at[str(serial)] = time.time()
    _device_tcp_miss_streak[str(serial)] = 0
    _adb_debug("tor settled serial=%s grace_sec=%.1f", serial, grace)


def _adb_in_post_tor_grace(serial: str) -> bool:
    until = _adb_post_tor_grace_until.get(serial)
    return until is not None and time.time() < until


def _adb_connect_on_failure_enabled(serial: str) -> bool:
    """Default **on** for ``IP:port`` ADB serials (TCP drops); off for USB ``emulator-*`` unless forced."""
    if not _TCP_ADB_SERIAL_RE.match(serial):
        return False
    v = (os.environ.get("PHARMFLOW_ADB_CONNECT_ON_FAILURE") or "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    if v in ("1", "true", "yes", "on"):
        return True
    return True


def _touch_wake_default_serial(serial: str) -> bool:
    """Emulator-class serials get touch-wake unless explicitly disabled (see ``_touch_wake_enabled``)."""
    if serial.startswith("emulator-"):
        return True
    return bool(_TCP_ADB_SERIAL_RE.match(serial))


def _emulator_automation_profile(serial: str) -> bool:
    """Wider tap jitter + wake defaults when treating this device as an emulator farm unit."""
    return _adb_truthy_env("PHARMFLOW_EMULATOR_MODE") or _touch_wake_default_serial(serial)


def _touch_wake_enabled(serial: str) -> bool:
    """Wake before tap/swipe: explicit env wins; else default **on** for emulator TCP / ``emulator-*``."""
    raw = (os.environ.get("PHARMFLOW_TOUCH_WAKE_BEFORE_INPUT") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return _emulator_automation_profile(serial)


def _emulator_tap_jitter_multiplier(serial: str) -> float:
    if not _emulator_automation_profile(serial):
        return 1.0
    try:
        m = float(os.environ.get("PHARMFLOW_EMULATOR_TAP_JITTER_MULT", "1.35") or 1.35)
    except (TypeError, ValueError):
        return 1.35
    return min(3.0, max(1.0, m))


def _pharmflow_skip_tor_wait() -> bool:
    return os.environ.get("PHARMFLOW_SKIP_TOR_WAIT", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _prefs_flag(name: str, default: bool | None = None) -> bool | None:
    """Boolean flag from ``desktop_prefs.json`` (``None`` when absent/unparseable)."""
    try:
        if DESKTOP_PREFS.exists():
            data = json.loads(DESKTOP_PREFS.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                v = data.get(name)
                if isinstance(v, bool):
                    return v
    except (json.JSONDecodeError, OSError):
        pass
    return default


def _write_stealth_prefs(**fields: bool | None) -> dict | None:
    """Merge stealth flags and keep them only if the disk copy matches.

    A corrupt prefs file is not replaced. Replacing it used to wipe
    ``mumu_setup_complete``.
    """
    updates = {k: v for k, v in fields.items() if isinstance(v, bool)}
    if not updates:
        return None
    data: dict = {}
    if DESKTOP_PREFS.exists():
        try:
            loaded = json.loads(DESKTOP_PREFS.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeError):
            return None
        if not isinstance(loaded, dict):
            return None
        data = loaded
    data.update(updates)
    try:
        DESKTOP_PREFS.parent.mkdir(parents=True, exist_ok=True)
        DESKTOP_PREFS.write_text(json.dumps(data, indent=2), encoding="utf-8")
        stored = json.loads(DESKTOP_PREFS.read_text(encoding="utf-8"))
    except (OSError, TypeError, json.JSONDecodeError, UnicodeError, ValueError):
        return None
    if not isinstance(stored, dict):
        return None
    for key, value in updates.items():
        if stored.get(key) is not value:
            return None
    return stored


def _rotate_every_sequence_enabled() -> bool:
    """Rotate fingerprint/proxy/Tor/IMEI after every sequence run (default ON).

    Precedence: ``PHARMFLOW_ROTATE_EVERY_SEQUENCE`` env, then ``desktop_prefs.json``
    ``rotate_every_sequence``, then default ON. Set explicitly to ``0`` to restore
    the old playlist-cycle-end behavior.
    """
    v = os.environ.get("PHARMFLOW_ROTATE_EVERY_SEQUENCE")
    if v is not None:
        return v.strip().lower() not in ("0", "false", "no", "off")
    pref = _prefs_flag("rotate_every_sequence", True)
    return pref if pref is not None else True


def _unique_exit_ips_enabled() -> bool:
    """Enforce a unique Tor exit IP per phone (default ON).

    Precedence: ``PHARMFLOW_UNIQUE_EXIT_IPS`` env, then ``desktop_prefs.json``
    ``unique_exit_ips``, then default ON.
    """
    v = os.environ.get("PHARMFLOW_UNIQUE_EXIT_IPS")
    if v is not None:
        return v.strip().lower() not in ("0", "false", "no", "off")
    pref = _prefs_flag("unique_exit_ips", True)
    return pref if pref is not None else True


@dataclass(frozen=True)
class AdbResult:
    argv: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str

    @property
    def text(self) -> str:
        return ((self.stdout or "") + (self.stderr or "")).strip()


_ADB_FAIL_HINTS = (
    "error:",
    "error ",
    "cannot connect",
    "device offline",
    "no devices/emulators",
    "adb.exe:",
    "adb: ",
    "failed to",
    "not found",
    "unable to",
    "closed",
    "unauthorized",
    "permission denied",
)


def _adb_indicates_trouble(res: AdbResult) -> bool:
    if res.returncode is not None and res.returncode != 0:
        return True
    low = res.text.lower()
    if not low:
        return False
    return any(h in low for h in _ADB_FAIL_HINTS)


def _adb_combine_run(argv: list[str], timeout: int) -> AdbResult:
    av = tuple(argv)
    try:
        r = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            errors="replace",  # device output can contain raw bytes (0x81 etc.) that crash cp1252 decoding
            timeout=timeout,
            creationflags=_ADB_SUBPROC_FLAGS,
        )
        return AdbResult(
            argv=av,
            returncode=r.returncode,
            stdout=r.stdout or "",
            stderr=r.stderr or "",
        )
    except Exception as e:
        log.warning("adb error argv=%s: %s", argv[:5], e)
        return AdbResult(argv=av, returncode=None, stdout="", stderr=str(e))


def _adb_output_suggests_daemon_failure(res: AdbResult) -> bool:
    low = res.text.lower()
    if not low:
        return False
    needles = (
        "cannot connect to daemon",
        "failed to start daemon",
        "daemon not running",
        "daemon still not running",
        "daemon died",
    )
    return any(n in low for n in needles)


def _adb_output_suggests_timeout(res: AdbResult) -> bool:
    """A wedged ADB server times out every command — same symptom as a dead daemon.

    ``_adb_combine_run`` catches the subprocess timeout and returns rc=None with
    the exception text in stderr; rc=15 (adb's own protocol timeout) also counts.
    """
    if res.returncode is None and res.stderr:
        return True
    if res.returncode == 15:
        return True
    low = res.text.lower()
    return "timed out" in low or "timeout" in low


def _adb_with_optional_daemon_recovery(argv: list[str], timeout: int) -> AdbResult:
    """Run adb once; if the daemon looks dead, ``start-server`` once and retry.

    ``adb kill-server`` drops every live phone. A timeout on one command is not
    a reason to do that. start-server brings a dead daemon up and leaves an
    already-running daemon alone.

    Enabled by default (``PHARMFLOW_ADB_START_SERVER=0`` to disable).
    """
    global _adb_session_start_server_attempted
    global _adb_server_recover_last
    res = _adb_combine_run(argv, timeout)
    now = time.time()
    if (
        # Recovery is ON by default; only ``PHARMFLOW_ADB_START_SERVER=0`` disables it.
        # (Earlier code required the var to be truthy, so a plain ``python dashboard.py``
        # never recovered from a wedged daemon — the farm stalled until a manual restart.)
        _adb_env_disabled("PHARMFLOW_ADB_START_SERVER")
        or now - _adb_server_recover_last < _adb_server_recover_min_gap
        or not (_adb_output_suggests_daemon_failure(res) or _adb_output_suggests_timeout(res))
    ):
        return res
    _adb_session_start_server_attempted = True
    _adb_server_recover_last = now
    exe = argv[0] if argv else adb_executable()
    log.warning(
        "ADB command failed — start-server and retry argv≈%s (no kill-server; next try in %.0fs)",
        " ".join(str(x) for x in argv[:6]),
        _adb_server_recover_min_gap,
    )
    _adb_combine_run([exe, "start-server"], timeout=25)
    # MuMu TCP sessions drop with the server; reconnect the guest-bridge phones.
    _adb_reconnect_known_phones()
    return _adb_combine_run(argv, timeout)


def _adb_reconnect_known_phones() -> None:
    """Re-``adb connect`` every known MuMu guest-bridge serial after a server restart.

    A dropped TCP session is not a reason to kill the ADB server. Known serials come from
    the live ``devices`` list plus saved prefs so fresh IPs churned by MuMu are covered.
    """
    known: set[str] = set()
    try:
        raw = _adb_combine_run([adb_executable(), "devices"], timeout=10)
        for line in (raw.stdout or "").splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 1 and parts[0].strip():
                known.add(parts[0].strip())
    except Exception:
        pass
    try:
        prefs_p = REC_DIR / "desktop_prefs.json"
        if prefs_p.is_file():
            data = json.loads(prefs_p.read_text(encoding="utf-8"))
            known.update(str(s).strip() for s in (data.get("phone_serials") or []))
        if GROUPS_CFG.is_file():
            data = json.loads(GROUPS_CFG.read_text(encoding="utf-8"))
            for g in data.get("groups", []):
                known.update(str(s).strip() for s in (g.get("phones") or {}))
    except (OSError, json.JSONDecodeError):
        pass
    exe = adb_executable()
    for serial in sorted(known):
        if not serial:
            continue
        try:
            _adb_combine_run([exe, "connect", serial], timeout=8)
        except Exception:
            pass


def _record_group_adb_error(group_name: str, serial: str, tag: str, res: AdbResult) -> None:
    row = {
        "group": group_name,
        "serial": serial,
        "tag": tag,
        "returncode": res.returncode,
        "detail": res.text[:800],
    }
    with _group_adb_errors_lock:
        _group_adb_errors.append(row)
        del _group_adb_errors[:-_GROUP_ADB_ERRORS_MAX]


def _adb_landed(res: AdbResult) -> bool:
    """True only when adb returned and did not report a failure."""
    return not _adb_indicates_trouble(res)


def _adb(serial: str, *args, timeout: int = 15) -> AdbResult:
    exe = adb_executable()
    res = _adb_with_optional_daemon_recovery([exe, "-s", serial, *args], timeout)
    if _adb_indicates_trouble(res):
        log.warning(
            "ADB issue serial=%s rc=%s argv≈%s — %s",
            serial,
            res.returncode,
            " ".join(str(x) for x in res.argv[2:8]),
            res.text[:500],
        )
    return res


def _serial_listed_as_online_device(serial: str) -> bool:
    raw = _adb_global("devices").text
    for line in raw.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[0] == serial and parts[1] == "device":
            return True
    return False


def _serial_adb_devices_state(serial: str) -> str | None:
    """Second column from ``adb devices`` for *serial* (``device`` / ``offline`` / …), or ``None`` if absent."""
    raw = _adb_global("devices").text
    for line in raw.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[0] == serial:
            return parts[1]
    return None


def _try_adb_tcp_reconnect(serial: str) -> AdbResult:
    """Re-issue ``adb connect`` for IP:port serials (MuMu / Wi‑Fi debugging drops).

    If ``adb devices`` lists the serial as ``offline``, run ``adb disconnect`` then ``adb connect``
    once (stale TCP state). Skips connect when the serial is already ``device`` — redundant
    ``adb connect`` on MuMu often drops an otherwise healthy session.
    """
    state = _serial_adb_devices_state(serial)
    if state == "device":
        _adb_debug("tcp reconnect skipped — already device serial=%s", serial)
        return AdbResult(argv=(), returncode=0, stdout="already connected", stderr="")
    if state == "offline":
        log.warning("ADB serial=%s listed as offline in adb devices — disconnect then connect", serial)
        _adb_global("disconnect", serial, timeout=10)
        time.sleep(0.12)
    return _adb_global("connect", serial, timeout=12)


def _tcp_shell_failure_suggests_reconnect(low: str) -> bool:
    """Broad match for dropped TCP sessions (not only ``device not found``)."""
    if not low:
        return False
    hints = (
        "not found",
        "device offline",
        "no devices",
        "no device",
        "closed",
        "cannot connect",
        "unable to connect",
        "connection refused",
        "connection reset",
        "connection aborted",
        "did not ack",
    )
    return any(h in low for h in hints)


def _maybe_log_tcp_reconnect_burst(serial: str, streak: int, every_n: int) -> None:
    """One log line per reconnect burst (debounced) to avoid spam across rapid steps."""
    now = time.time()
    prev = _tcp_reconnect_burst_log_at.get(serial, 0.0)
    if now - prev < 8.0:
        return
    _tcp_reconnect_burst_log_at[serial] = now
    log.warning(
        "ADB TCP serial not responding (%s) — attempting adb connect (miss #%s; interval=%s). "
        "Set PHARMFLOW_ADB_CONNECT_ON_FAILURE=0 to disable reconnects for this serial class.",
        serial,
        streak,
        every_n,
    )


def ensure_adb_serial_ready(serial: str, adb_issue_cb=None) -> bool:
    """Cheap preflight + optional TCP reconnect before sequence steps.

    Skipped when ``PHARMFLOW_SKIP_DEVICE_PREFLIGHT=1``. Uses a short per-serial cache so
    burst steps do not hammer ``adb shell echo``.
    """
    if _adb_truthy_env("PHARMFLOW_SKIP_DEVICE_PREFLIGHT"):
        return True
    now = time.time()
    ttl = _DEVICE_PREFLIGHT_TTL_SEC
    if _adb_in_post_tor_grace(serial):
        ttl = max(ttl, _adb_post_tor_grace_seconds())
    prev = _device_preflight_ok_at.get(serial)
    if prev is not None and now - prev < ttl:
        return True

    res = _adb(serial, "shell", "echo", "ok", timeout=10)
    ok_shell = (res.returncode in (0, None)) and ("ok" in ((res.stdout or "") + (res.stderr or "")).lower())
    if ok_shell:
        _device_preflight_ok_at[serial] = now
        _device_tcp_miss_streak[serial] = 0
        return True

    # MuMu bridge can be briefly busy right after Tor ``adb reverse`` + force-stop — retry shell
    # before any ``adb connect`` that may drop the TCP session.
    if _adb_in_post_tor_grace(serial):
        for attempt in range(2):
            try:
                bo = float(os.environ.get("PHARMFLOW_ADB_POST_TOR_SHELL_RETRY_SEC", "0.55") or 0.55)
            except (TypeError, ValueError):
                bo = 0.55
            time.sleep(min(2.0, max(0.15, bo * (attempt + 1))))
            res_retry = _adb(serial, "shell", "echo", "ok", timeout=12)
            ok_retry = (res_retry.returncode in (0, None)) and (
                "ok" in ((res_retry.stdout or "") + (res_retry.stderr or "")).lower()
            )
            if ok_retry:
                _adb_debug("post-tor grace shell retry OK serial=%s attempt=%s", serial, attempt + 1)
                _device_preflight_ok_at[serial] = time.time()
                _device_tcp_miss_streak[serial] = 0
                return True
            res = res_retry

    low = res.text.lower()
    looks_missing = ("not found" in low and "device" in low) or ("offline" in low) or (
        "no devices" in low
    )
    tcp_wants_reconnect = _tcp_shell_failure_suggests_reconnect(low) or looks_missing
    if adb_issue_cb is not None and _adb_indicates_trouble(res):
        adb_issue_cb("device_preflight", res)

    try:
        every_n = max(1, int(os.environ.get("PHARMFLOW_ADB_RECONNECT_EVERY_N_FAILURES", "2") or "2"))
    except (TypeError, ValueError):
        every_n = 2
    _device_tcp_miss_streak[serial] = _device_tcp_miss_streak.get(serial, 0) + 1
    streak = _device_tcp_miss_streak[serial]

    # First miss + every Nth miss (1-based streak): e.g. N=3 reconnect at streak 1,4,7,…
    connect_ok = _adb_connect_on_failure_enabled(serial)
    in_grace = _adb_in_post_tor_grace(serial)
    devices_state = _serial_adb_devices_state(serial)
    # During post-Tor grace, only reconnect when adb devices shows offline (not transient shell lag).
    grace_blocks_reconnect = in_grace and devices_state == "device"
    if grace_blocks_reconnect:
        _adb_debug(
            "post-tor grace: skip adb connect serial=%s streak=%s state=%s",
            serial,
            streak,
            devices_state,
        )
    if (
        connect_ok
        and _TCP_ADB_SERIAL_RE.match(serial)
        and tcp_wants_reconnect
        and (streak % every_n == 1)
        and not grace_blocks_reconnect
    ):
        _maybe_log_tcp_reconnect_burst(serial, streak, every_n)
        _try_adb_tcp_reconnect(serial)
        try:
            bo = float(os.environ.get("PHARMFLOW_ADB_RECONNECT_BACKOFF_SEC", "") or 0)
        except (TypeError, ValueError):
            bo = 0.0
        if bo <= 0:
            bo = min(2.8, 0.42 + min(streak, 12) * 0.14)
        time.sleep(min(4.0, max(0.2, bo)))
        res2 = _adb(serial, "shell", "echo", "ok", timeout=12)
        ok2 = (res2.returncode in (0, None)) and (
            "ok" in ((res2.stdout or "") + (res2.stderr or "")).lower()
        )
        if ok2:
            _device_preflight_ok_at[serial] = time.time()
            _device_tcp_miss_streak[serial] = 0
            invalidate_cache(serial)
            log.info("ADB TCP reconnect OK serial=%s", serial)
            if not _pharmflow_skip_tor_wait():
                try:
                    idx = _phone_idx_from_serial(serial)
                    tor_manager.repair_adb_reverse_for_proxy(serial, idx)
                except Exception:
                    log.debug("repair_adb_reverse after reconnect failed serial=%s", serial, exc_info=True)
            return True
        if adb_issue_cb is not None and _adb_indicates_trouble(res2):
            adb_issue_cb("device_preflight_reconnect", res2)

    if not _serial_listed_as_online_device(serial):
        log.error(
            "Phone not responding (%s). If MuMu was closed, start that phone. "
            "On Boot, click Start all phones. See docs/PharmFlow_emulator_MuMu_and_sequences.md",
            serial,
        )
    else:
        log.error(
            "ADB serial=%s appears in adb devices but shell failed — unauthorized, offline, "
            "or emulator stuck; retry when the device UI is responsive.",
            serial,
        )
    return False


def _maybe_wake_before_touch(serial: str) -> None:
    """KEYCODE_WAKEUP before tap/swipe when enabled (default on for emulator TCP / ``emulator-*``)."""
    if not _touch_wake_enabled(serial):
        return
    _adb(serial, "shell", "input", "keyevent", "224", timeout=8)
    try:
        dly = float(os.environ.get("PHARMFLOW_TOUCH_WAKE_DELAY_SEC", "0.35") or 0.35)
    except (TypeError, ValueError):
        dly = 0.35
    time.sleep(min(2.5, max(0.0, dly)))


def _open_url_am_start_timeout_sec() -> float:
    """Timeout for each ``adb shell am start`` attempt (MuMu cold start / busy system).

    Override ``PHARMFLOW_OPEN_URL_AM_START_TIMEOUT_SEC`` (default **35**, clamped 15–120).
    """
    try:
        v = float(os.environ.get("PHARMFLOW_OPEN_URL_AM_START_TIMEOUT_SEC", "35") or 35)
    except (TypeError, ValueError):
        v = 35.0
    return max(15.0, min(120.0, v))


def _open_url_debug_enabled() -> bool:
    """Verbose ``open_url`` diagnostics (resolve-activity snapshot after PID timeout, etc.)."""
    return _adb_truthy_env("PHARMFLOW_OPEN_URL_DEBUG")


def _pid_wait_pkg_running(serial: str, pkg: str) -> bool:
    """True if ``pidof`` or ``pgrep -f`` sees the package (some OEM ROMs omit ``pidof`` matches)."""
    pr = _adb(serial, "shell", "pidof", pkg, timeout=8)
    if pr.returncode in (0, None) and (pr.stdout or "").strip():
        return True
    pr2 = _adb(serial, "shell", "pgrep", "-f", pkg, timeout=8)
    return pr2.returncode in (0, None) and bool((pr2.stdout or "").strip())


def _wait_for_browser_pid_after_open(serial: str, step: dict) -> None:
    """Poll ``pidof`` for resolved browser packages after ``am start`` (cold/slow browser start).

    After the process appears, callers should still sleep for first-navigation paint when the step
    omits ``post_wait_secs`` — see :func:`_open_url_settle_after_pid` (``PHARMFLOW_OPEN_URL_*``).
    For slow SPAs, add a sequence ``wait`` step following ``open_url``.
    """
    pref = str(step.get("package", "")).strip()
    pkgs = packages_for_view_url_attempts(serial, pref)
    if not pkgs:
        return
    try:
        timeout = float(os.environ.get("PHARMFLOW_OPEN_URL_LAUNCH_WAIT_SEC", "65"))
    except (TypeError, ValueError):
        timeout = 65.0
    timeout = max(8.0, min(timeout, 180.0))
    deadline = time.time() + timeout
    while time.time() < deadline:
        for pkg in pkgs:
            if _pid_wait_pkg_running(serial, pkg):
                return
        time.sleep(0.48)
    log.warning(
        "ERROR_TIMEOUT browser PID wait serial=%s candidates=%s — cold/slow browser, MuMu quirk, or launch blocked; "
        "raise PHARMFLOW_OPEN_URL_LAUNCH_WAIT_SEC (default 65), add open_url post_wait_secs / sequence wait step (see docs).",
        serial,
        pkgs[:8],
    )
    if _open_url_debug_enabled():
        r1 = _adb(
            serial,
            "shell",
            "cmd",
            "package",
            "resolve-activity",
            "--brief",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            "https://example.com",
            timeout=14,
        )
        log.warning(
            "open_url DEBUG resolve-activity serial=%s rc=%s → %s",
            serial,
            r1.returncode,
            (r1.text or "")[:500],
        )


def _open_url_default_extra_sleep(step: dict) -> float:
    """Env default seconds after PID settle when the step omits ``post_wait_secs`` (emulator cold start).

    Default **6** when unset (was 0) — MuMu/AVD Chromium often needs time after ``am start``.
    """
    if step.get("post_wait_secs") is not None and str(step.get("post_wait_secs", "")).strip() != "":
        return 0.0
    try:
        v = float(os.environ.get("PHARMFLOW_OPEN_URL_DEFAULT_WAIT_SEC", "6") or 6)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, v)


def _open_url_first_nav_floor_sec() -> float:
    """Minimum extra settle after browser PID (first paint / proxy path); merged with default wait via max()."""
    try:
        v = float(os.environ.get("PHARMFLOW_OPEN_URL_FIRST_NAV_SEC", "4") or 4)
    except (TypeError, ValueError):
        return 4.0
    return max(0.0, v)


def _open_url_settle_after_pid(step: dict) -> float:
    """Sleep duration after ``pidof`` success when ``post_wait_secs`` is omitted: max(env default, first-nav floor)."""
    if step.get("post_wait_secs") is not None and str(step.get("post_wait_secs", "")).strip() != "":
        return 0.0
    return max(_open_url_default_extra_sleep(step), _open_url_first_nav_floor_sec())


def _device_network_hint_online(serial: str) -> bool | None:
    """Best-effort guest egress check for ``PHARMFLOW_OPEN_URL_NET_CHECK``. None = inconclusive."""
    pr = _adb(serial, "shell", "ping", "-c", "1", "-W", "3", "8.8.8.8", timeout=14)
    text = ((pr.stdout or "") + (pr.stderr or "")).lower()
    if pr.returncode == 0 and ("1 received" in text or "bytes from" in text):
        return True
    if "100% packet loss" in text or "network is unreachable" in text or "unknown host" in text:
        return False
    return None


def _open_url_new_tab_flag(step: dict) -> bool | None:
    raw = step.get("new_tab")
    if raw is None or raw == "":
        raw = step.get("create_new_tab")
    if isinstance(raw, bool):
        return raw
    if raw is None or raw == "":
        return None
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _normalize_url_for_intent(raw) -> str:
    txt = str(raw or "").strip()
    if not txt:
        return txt
    if "://" not in txt and "." in txt and " " not in txt:
        txt = f"https://{txt}"
    try:
        p = urllib.parse.urlparse(txt)
    except Exception:
        return txt
    if p.scheme in ("http", "https") and p.netloc:
        return urllib.parse.urlunparse(p._replace(fragment=""))
    return txt


def _profile_dim(raw, fallback: int) -> int:
    try:
        v = int(raw)
        return v if v > 0 else fallback
    except (TypeError, ValueError):
        return fallback


def _apply_phone_sequence_profile(steps: list, ent: dict) -> list:
    """Keep tap/swipe baselines consistent with per-phone profile metadata."""
    if not isinstance(steps, list):
        return []
    bw = _profile_dim(ent.get("sequence_base_w"), SEQUENCE_BASE_W)
    bh = _profile_dim(ent.get("sequence_base_h"), SEQUENCE_BASE_H)
    out: list = []
    for raw in steps:
        if not isinstance(raw, dict):
            out.append(raw)
            continue
        step = dict(raw)
        if step.get("type") in ("tap", "swipe"):
            if "base_w" not in step or "base_h" not in step:
                step["base_w"] = bw
                step["base_h"] = bh
            normalize_step_baseline(step)
        out.append(step)
    return out


def _open_url_shell_argv(url: str, step: dict) -> list[str]:
    """Build ``am start`` argv for ``open_url`` — device default browser unless step forces a component."""
    bc_raw = step.get("browser_component")
    bc = bc_raw.strip() if isinstance(bc_raw, str) and bc_raw.strip() else ""
    pkg = str(step.get("package", "")).strip()
    act = str(step.get("activity", "")).strip()
    nt = _open_url_new_tab_flag(step)
    if bc and "/" in bc:
        return am_start_view_url_argv(url, browser_component=bc, new_tab=nt)
    # Legacy sequences set only package=com.android.chrome with no activity; prefer generic VIEW
    # so the phone's actual default browser opens (emulators often mis-resolve defaults to Chrome).
    if pkg == "com.android.chrome" and not act:
        pkg = ""
    if pkg and _PKG_STEP_RE.match(pkg) and act and "/" not in act:
        return am_start_view_url_argv(
            url,
            browser_component=f"{pkg}/{act}",
            new_tab=nt,
        )
    if pkg and _PKG_STEP_RE.match(pkg):
        return am_start_view_url_argv(url, package=pkg, new_tab=nt)
    return am_start_view_url_argv(url)


def _open_url_attempts(url: str, step: dict, serial: str | None = None) -> list[tuple[str, list[str]]]:
    """Ordered attempts with reasons for telemetry.

    When ``serial`` is provided and the step does not explicitly pin a
    ``browser_component`` or ``package``, OEM/non-Chrome packages from
    :func:`browser_adb.packages_for_view_url_attempts` are placed **before** the
    generic ACTION_VIEW attempt. Generic VIEW lets Android pick the device default
    which is often Chrome; Chrome on many emulator builds bypasses Android
    ``global http_proxy`` → ERR_TIMED_OUT through Tor. By routing the primary
    attempt through an explicit non-Chrome package (MuMu browser, Samsung Internet,
    etc.) the system http_proxy → Tor tunnel is honoured from the first try.
    Generic VIEW is kept as a final safety net.
    """
    nt = _open_url_new_tab_flag(step)
    bc_raw = step.get("browser_component")
    bc = bc_raw.strip() if isinstance(bc_raw, str) and bc_raw.strip() else ""
    pref = str(step.get("package", "")).strip()

    seen: set[tuple[str, ...]] = set()
    uniq: list[tuple[str, list[str]]] = []

    def _add(why: str, argv: list[str]) -> None:
        key = tuple(argv)
        if key not in seen:
            seen.add(key)
            uniq.append((why, argv))

    step_argv = _open_url_shell_argv(url, step)
    step_is_generic = step_argv == am_start_view_url_argv(url)

    if bc and "/" in bc:
        _add("step-configured", step_argv)
        pkg = bc.split("/", 1)[0].strip()
        if looks_like_package(pkg):
            _add("component-missing-try-package", am_start_view_url_argv(url, package=pkg))
        _add("generic-device-default", am_start_view_url_argv(url, new_tab=nt))
        return uniq

    if not step_is_generic:
        _add("step-configured", step_argv)

    if serial:
        if "getdabflow.app" in (url or "").lower():
            from browser_adb import packages_for_dabflow_view_url_attempts

            serial_pkgs = packages_for_dabflow_view_url_attempts(serial, pref)
        else:
            serial_pkgs = packages_for_view_url_attempts(serial, pref)
        for pkg in serial_pkgs:
            _add(f"oem-pkg-{pkg}", am_start_view_url_argv(url, package=pkg))
        if serial_pkgs and all(_pkg_is_chrome_family(p) for p in serial_pkgs):
            log.warning(
                "open_url: only Chrome-family browsers found on serial=%s — Chrome often bypasses "
                "Android global http_proxy on emulators → ERR_TIMED_OUT through Tor; "
                "install Firefox or MuMu Browser for reliable proxy routing",
                serial,
            )
    elif looks_like_package(pref):
        _add("package-specific", am_start_view_url_argv(url, package=pref))

    if step_is_generic:
        _add("step-configured", step_argv)
    _add("generic-device-default", am_start_view_url_argv(url, new_tab=nt))
    return uniq


_OPEN_URL_BROWSER_NET_RE = re.compile(
    r"(?:net::|ERR_CONNECTION|ERR_TIMED_OUT|ERR_NAME_NOT_RESOLVED|ERR_PROXY_CONNECTION_FAILED|ERR_ADDRESS_UNREACHABLE|"
    r"ERR_EMPTY_RESPONSE|ERR_INTERNET_DISCONNECTED|ERR_SSL_PROTOCOL_ERROR|ERR_FAILED)",
    re.I,
)


def _open_url_nav_retry_enabled() -> bool:
    """Default **on** — the retry is the primary recovery path when the just-applied
    http_proxy hadn't taken effect at the moment Chromium opened its first connection.
    Operators can disable via ``PHARMFLOW_OPEN_URL_NAV_RETRY=0`` for the old behaviour.
    """
    raw = (os.environ.get("PHARMFLOW_OPEN_URL_NAV_RETRY") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    return True


def _open_url_browser_net_error(res: AdbResult) -> bool:
    """True when ``am start`` output carries browser-page network errors.

    ADB can return success while stderr/log text includes a Chromium offline marker from
    the already-open tab. This is distinct from ADB trouble and gets one optional generic
    ACTION_VIEW retry only when ``PHARMFLOW_OPEN_URL_NAV_RETRY=1``.
    """
    hay = (res.stderr or "") or res.text
    return bool(_OPEN_URL_BROWSER_NET_RE.search(hay or ""))


def _retry_open_url_action_view_for_browser_net_error(serial: str, url: str, res: AdbResult) -> AdbResult:
    """Retry navigation once with generic ACTION_VIEW for browser-side net error text."""
    if not _open_url_nav_retry_enabled() or not _open_url_browser_net_error(res):
        return res
    try:
        _nb = float(os.environ.get("PHARMFLOW_OPEN_URL_NAV_RETRY_BACKOFF_SEC", "1.5") or 1.5)
    except (TypeError, ValueError):
        _nb = 1.5
    _nb = min(15.0, max(0.0, _nb))
    if _nb:
        time.sleep(_nb)
    log.info(
        "open_url: browser net-error marker after am start serial=%s — retrying generic ACTION_VIEW once",
        serial,
    )
    retry = _adb(serial, *am_start_view_url_argv(url), timeout=int(_open_url_am_start_timeout_sec()))
    if _adb_indicates_trouble(retry):
        log.warning(
            "open_url generic nav retry failed serial=%s rc=%s — %s",
            serial,
            retry.returncode,
            retry.text[:300],
        )
    return retry


def _looks_like_inject_events_denied(res: AdbResult) -> bool:
    low = res.text.lower()
    has_inject = ("inject_events" in low) or ("inject events" in low)
    if not has_inject:
        return False
    return (
        ("securityexception" in low)
        or ("permission denied" in low)
        or ("requires" in low and "permission" in low)
        or ("not allowed" in low)
    )


def _log_inject_events_doc_hint_if_needed(res_fb: AdbResult) -> None:
    """One-shot hint when keyevent fallback also hits INJECT_EVENTS (non-root OEM/emulator policy)."""
    global _inject_events_doc_hint_logged
    if _inject_events_doc_hint_logged or not _looks_like_inject_events_denied(res_fb):
        return
    _inject_events_doc_hint_logged = True
    log.error(
        "Input injection still blocked after keyevent fallback — enable Developer options → "
        "USB debugging (Security settings) on the emulator if present; disable aggressive overlays. "
        "See docs/PharmFlow_emulator_MuMu_and_sequences.md — MuMu / emulator checklist."
    )


def _log_inject_events_actionable_once(serial: str, gesture: str) -> None:
    """First failure per serial+gesture: operator-facing fix for ``INJECT_EVENTS``."""
    key = f"{serial}:{gesture}"
    if key in _inject_actionable_logged:
        return
    _inject_actionable_logged.add(key)
    log.error(
        "Cannot tap this phone (%s): turn on Developer options → "
        "USB debugging (Security settings). See docs/PharmFlow_emulator_MuMu_and_sequences.md",
        serial,
        gesture,
    )


def _wm_focus_cheat_enabled() -> bool:
    return _adb_truthy_env("PHARMFLOW_USE_SHELL_WM_FOCUS_CHEAT")


def _inject_retry_after_close_dialogs(serial: str, argv_after_shell: list[str]) -> AdbResult:
    """Dismiss system dialogs then retry one ``adb shell …`` input command (best-effort)."""
    _adb(serial, "shell", "am", "broadcast", "-a", "android.intent.action.CLOSE_SYSTEM_DIALOGS", timeout=8)
    time.sleep(0.28)
    return _adb(serial, "shell", *argv_after_shell, timeout=12)


def _force_stop_browser_for_dabflow_cdp(serial: str, url: str) -> None:
    """Force-stop the browser before opening a getdabflow.app URL when the Mantis
    patch is enabled so Chromium cold-starts and reads the flags file that carries
    ``--remote-debugging-port=9222``.

    Chrome/Chromium only reads ``/data/local/tmp/chrome-command-line`` at process
    start. A warm ``am start`` reuses the already-running process, which never picks
    up the CDP flag → CDP never listens → the dabflow Mantis ad-injection fails with
    "Remote end closed connection without response" → zero impressions → zero income.
    """
    if "getdabflow.app" not in (url or "").lower():
        return
    try:
        from dabflow_mantis_client_patch import (
            load_desktop_prefs,
            patch_enabled_from_env,
            patch_enabled_from_prefs,
        )

        pref = patch_enabled_from_prefs(load_desktop_prefs())
        enabled = pref if pref is not None else patch_enabled_from_env()
        if not enabled:
            return
    except Exception:
        return  # never block the open on a patch-enablement check
    try:
        from browser_adb import packages_for_dabflow_view_url_attempts

        pkgs = packages_for_dabflow_view_url_attempts(serial)
        for pkg in pkgs[:2]:
            res = _adb(serial, "shell", "am", "force-stop", pkg, timeout=10)
            if _adb_indicates_trouble(res):
                log.debug(
                    "force-stop for dabflow CDP rc=%s serial=%s pkg=%s — %s",
                    res.returncode,
                    serial,
                    pkg,
                    res.text[:200],
                )
        if pkgs:
            log.info(
                "open_url: dabflow CDP cold-restart serial=%s pkgs=%s",
                serial,
                pkgs[:2],
            )
    except Exception:
        log.debug("dabflow CDP force-stop failed serial=%s", serial, exc_info=True)


def _dead_tor_http_reason(phone_idx: int, guest_proxy: str, tor_ready: dict) -> str:
    """Skip the launch only when the guest exit is this phone's Tor HTTP port and Tor is down.

    An inject loopback exit does not need Tor. A dead Tor port is not host-IP
    egress, but launching into it is not an opened page.
    """
    if tor_ready.get("ok"):
        return ""
    try:
        tor_port = int(tor_manager.phone_http_port(phone_idx))
    except (TypeError, ValueError):
        return ""
    if (guest_proxy or "").strip() != f"127.0.0.1:{tor_port}":
        return ""
    return str(tor_ready.get("error") or "Tor is not ready")


def _open_url_result_log(name: str, url: str, *, opened: bool, note: str = "") -> str:
    """Log line for /api/open_url. Never says opened when the tap failed."""
    if opened:
        return f"Opened {url} on {name}"
    detail = (note or "phone did not open a browser").strip()
    return f"{name}: page not opened — {detail}"


def _dashboard_open_exit_ready(serial: str) -> tuple[bool, str]:
    """Refuse to open a page until the guest proxy is 127.0.0.1 with a port.

    Empty, :0, or any other host sends the page out the VM NAT (this PC).
    One pin attempt, then a re-read. Failure does not launch the browser.
    """
    res = _adb(serial, "shell", "settings", "get", "global", "http_proxy", timeout=8)
    cur = (res.stdout or "").strip()
    if guest_proxy_healthy(cur):
        return True, cur
    try:
        pinned = pin_guest_proxy(
            AdbWrapper(),
            str(serial),
            _phone_idx_from_serial(serial),
            attempts=1,
        )
    except Exception as exc:
        log.warning("open_url exit pin failed serial=%s: %s", serial, exc)
        pinned = ""
    if guest_proxy_healthy(str(pinned or "")):
        return True, str(pinned)
    again = _adb(serial, "shell", "settings", "get", "global", "http_proxy", timeout=8)
    again_val = (again.stdout or "").strip()
    if guest_proxy_healthy(again_val):
        return True, again_val
    if _adb_indicates_trouble(res) and not cur:
        return False, (res.text or "could not read this phone's exit")[:200]
    return False, (
        "This phone has no exit proxy, so the page was not opened. "
        "Traffic would leave this PC. Fix phone internet, then try again."
    )


def _open_url_with_fallbacks(serial: str, url: str, step: dict) -> AdbResult:
    last = AdbResult(argv=tuple(), returncode=None, stdout="", stderr="open_url not attempted")
    tout = _open_url_am_start_timeout_sec()
    try:
        inter_attempt_sleep = float(
            os.environ.get("PHARMFLOW_OPEN_URL_INTER_ATTEMPT_SEC", "0.6") or 0.6
        )
    except (TypeError, ValueError):
        inter_attempt_sleep = 0.6
    inter_attempt_sleep = min(5.0, max(0.0, inter_attempt_sleep))
    attempts_seq = list(_open_url_attempts(url, step, serial))
    for i, (why, argv) in enumerate(attempts_seq):
        res = _adb(serial, *argv, timeout=int(tout))
        if _open_url_debug_enabled():
            log.info(
                "open_url DEBUG serial=%s reason=%s rc=%s argv≈%s — %s",
                serial,
                why,
                res.returncode,
                " ".join(str(x) for x in res.argv[2:10]),
                res.text[:400],
            )
        if am_start_reported_landing(res.stdout, res.stderr):
            if why != "step-configured":
                log.info("open_url fallback success serial=%s reason=%s", serial, why)
            return res
        log.warning(
            "open_url failed serial=%s reason=%s rc=%s argv≈%s — %s",
            serial,
            why,
            res.returncode,
            " ".join(str(x) for x in res.argv[2:8]),
            res.text[:300],
        )
        last = res
        # Don't spam the device when Tor/proxy isn't ready — short breath between fallback
        # attempts lets adb reverse / browser state settle before the next ``am start``.
        if inter_attempt_sleep and i + 1 < len(attempts_seq):
            time.sleep(inter_attempt_sleep)
    return last


def _fallback_keyevent_for_swipe(x1: int, y1: int, x2: int, y2: int) -> str | None:
    dx = x2 - x1
    dy = y2 - y1
    if abs(dy) >= abs(dx):
        # Gesture swipe up (dy < 0) usually means scroll down.
        return "PAGE_DOWN" if dy < 0 else "PAGE_UP"
    return "DPAD_RIGHT" if dx > 0 else "DPAD_LEFT"


def _adb_global(*args, timeout: int = 10) -> AdbResult:
    exe = adb_executable()
    res = _adb_with_optional_daemon_recovery([exe, *args], timeout)
    if _adb_indicates_trouble(res):
        log.warning(
            "ADB issue (global) rc=%s argv≈%s — %s",
            res.returncode,
            " ".join(str(x) for x in res.argv[1:8]),
            res.text[:500],
        )
    return res




def _mumu_guest_ips_from_arp() -> list[str]:
    """MuMu guest-bridge hosts on 10.0.2.x often appear in the Windows ARP table."""
    try:
        import subprocess

        cp = subprocess.run(
            ["arp", "-a"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        out = cp.stdout or ""
    except Exception:
        return []
    ips: list[str] = []
    for line in out.splitlines():
        m = re.search(r"\b(10\.0\.2\.(?!1\b|255\b)\d{1,3})\b", line)
        if not m:
            continue
        ip = m.group(1)
        if ip not in ips:
            ips.append(ip)
    return ips

def _published_redroid_serials() -> list[str]:
    """Host ports Docker published for redroid. Do not invent 5555 + index.

    Do not call docker when the engine is down — that CLI shim opens Docker Desktop.
    """
    try:
        import docker_guard
    except Exception:
        return []
    if not docker_guard.engine_running():
        return []
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                "name=redroid-",
                "--format",
                "{{.Ports}}",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=flags,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    serials: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"(?:0\.0\.0\.0|127\.0\.0\.1):(\d+)->", proc.stdout or ""):
        serial = f"127.0.0.1:{match.group(1)}"
        if serial in seen:
            continue
        seen.add(serial)
        serials.append(serial)
    return serials


def auto_connect_targets() -> list[str]:
    """Every published guest the service should attach.

    A fixed localhost port list is not the roster. ARM guests publish
    AdbHost. Redroid publishes a host port. Neither is a count.
    """
    serials: list[str] = []
    try:
        from automation.farm_phone_discover import _known_candidate_serials
    except Exception:
        try:
            from farm_phone_discover import _known_candidate_serials
        except Exception:
            _known_candidate_serials = None  # type: ignore[assignment]
    if _known_candidate_serials is not None:
        try:
            serials.extend(_known_candidate_serials() or [])
        except Exception:
            pass
    try:
        serials.extend(_published_redroid_serials())
    except Exception:
        pass
    for ip in _mumu_guest_ips_from_arp():
        serials.append(f"{ip}:5555")
    out: list[str] = []
    seen: set[str] = set()
    for serial in serials:
        text = str(serial or "").strip()
        if not text or text in seen or ":" not in text:
            continue
        seen.add(text)
        out.append(text)
    return out


def auto_connect_emulators():
    """Attach every published guest. Not a fixed localhost port list."""
    for serial in auto_connect_targets():
        host, _, port_s = serial.rpartition(":")
        try:
            port = int(port_s)
        except ValueError:
            continue
        try:
            sock = socket.socket()
            sock.settimeout(0.3)
            reachable = sock.connect_ex((host, port)) == 0
            sock.close()
        except Exception:
            reachable = False
        if reachable:
            _adb_global("connect", serial, timeout=5)


def _running_phones_ordered() -> list[dict]:
    """Running ADB devices in ``desktop_prefs.json`` Tor slot order."""
    return tor_manager.order_phones_by_desktop_prefs(
        [p for p in list_phones() if p["running"]]
    )


def list_phones() -> list[dict]:
    """Return all ADB-connected Android devices, real or emulated."""
    raw = _adb_global("devices", "-l").text
    phones = []
    for line in raw.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial = parts[0]
        status = parts[1]
        running = (status == "device")

        # Parse model name from -l output (model:Pixel_6 → Pixel 6)
        name = serial
        for part in parts[2:]:
            if part.startswith("model:"):
                name = part.split(":", 1)[1].replace("_", " ")
                break

        # Detect device type for display
        if serial.startswith("emulator-"):
            dtype = "emulator"
        elif re.match(r"^[\d.]+:\d+$", serial):
            dtype = "wifi"
        else:
            dtype = "real"

        phones.append({
            "serial":  serial,
            "name":    name,
            "running": running,
            "type":    dtype,
            "app":     _get_installed_app(serial) if running else {"package": "", "version": ""},
        })
    return phones


def _get_installed_app(serial: str) -> dict:
    now = time.time()
    if serial in _app_cache and now - _app_cache_time.get(serial, 0) < APP_CACHE_TTL:
        return _app_cache[serial]

    result = {"package": "", "version": ""}
    try:
        raw  = _adb(serial, "shell", "pm", "list", "packages", "-3").text
        pkgs = [line.strip().replace("package:", "") for line in raw.splitlines() if line.strip()]
        if pkgs:
            pkg     = pkgs[0]
            ver_raw = _adb(serial, "shell", "dumpsys", "package", pkg).text
            version = "?"
            for line in ver_raw.splitlines():
                if "versionName" in line:
                    version = line.strip().split("=")[-1]
                    break
            result = {"package": pkg, "version": version}
    except Exception:
        pass

    _app_cache[serial]      = result
    _app_cache_time[serial] = now
    return result


def invalidate_cache(serial: str):
    invalidate_webview_inset_cache(serial)
    _app_cache.pop(serial, None)
    _app_cache_time.pop(serial, None)
    _wm_size_cache.pop(serial, None)


def _physical_size_for_serial(serial: str) -> tuple[int, int] | None:
    """Return (width, height) from ``wm size``, or None if ADB/parse fails."""
    now = time.time()
    ent = _wm_size_cache.get(serial)
    if ent is not None and now - ent[0] < _WM_SIZE_CACHE_TTL:
        return ent[1]
    raw = _adb(serial, "shell", "wm", "size").text
    dims = parse_wm_size_output(raw)
    _wm_size_cache[serial] = (now, dims)
    return dims


def _scale_xy_for_serial(serial: str, x: int, y: int, base_w: int, base_h: int) -> tuple[int, int]:
    """Scale sequence coordinates to the device's reported size; unchanged if lookup fails."""
    if _adb_truthy_env("PHARMFLOW_SEQUENCE_NO_SCALE"):
        return max(0, x), max(0, y)
    phys = _physical_size_for_serial(serial)
    if not phys:
        return max(0, x), max(0, y)
    return scale_point(x, y, phys[0], phys[1], base_w, base_h)


def _clamp_xy_for_serial(serial: str, x: int, y: int) -> tuple[int, int]:
    """Clamp coordinates to current wm size bounds when available."""
    phys = _physical_size_for_serial(serial)
    if not phys:
        return max(0, x), max(0, y)
    max_x = max(0, phys[0] - 1)
    max_y = max(0, phys[1] - 1)
    return min(max_x, max(0, x)), min(max_y, max(0, y))


def _coerce_step_int(value, default: int = 0) -> int:
    """Accept ints/floats/numeric strings from step payloads."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _phone_entry_for_serial(pmap: dict, adb_serial: str) -> dict | None:
    """Resolve ``phones`` map entry when config keys differ from ADB by whitespace only."""
    if not isinstance(pmap, dict) or not isinstance(adb_serial, str):
        return None
    if adb_serial in pmap and isinstance(pmap[adb_serial], dict):
        return pmap[adb_serial]
    want = adb_serial.strip()
    for k, v in pmap.items():
        if isinstance(k, str) and k.strip() == want and isinstance(v, dict):
            return v
    return None


def _inline_steps_fallback(group: dict, ent: dict) -> list:
    """Inline ``steps`` only (before playlist overlay)."""
    per = ent.get("steps")
    if isinstance(per, list) and len(per) > 0:
        return per
    legacy = group.get("steps")
    if isinstance(legacy, list) and len(legacy) > 0:
        return list(legacy)
    return list(per) if isinstance(per, list) else []


def _phone_steps_for_run(group: dict, adb_serial: str, iteration: int = 0) -> tuple[list, str | None]:
    """Per-phone steps; optional playlists (set A / optional set B) per ``sequence_playlist_mode`` / ``sequence_playlist_shuffle``."""
    pmap = group.get("phones") or {}
    if not isinstance(pmap, dict):
        pmap = {}
    ent = _phone_entry_for_serial(pmap, adb_serial) or {}
    inline = _inline_steps_fallback(group, ent)
    steps, pl_name = resolve_steps(ent, iteration, adb_serial, inline)
    normalized = normalize_automation_steps(steps) if isinstance(steps, list) else []
    profiled = _apply_phone_sequence_profile(normalized, ent)
    return profiled, pl_name


def _normalize_phone_entry_for_runtime(phone_ent: dict) -> dict:
    """Best-effort runtime normalization for one ``groups[].phones[serial]`` entry."""
    if not isinstance(phone_ent, dict):
        return {}
    ent = dict(phone_ent)
    ent["steps"] = normalize_automation_steps(ent.get("steps", [])) if isinstance(ent.get("steps"), list) else []
    bw = _profile_dim(ent.get("sequence_base_w"), SEQUENCE_BASE_W)
    bh = _profile_dim(ent.get("sequence_base_h"), SEQUENCE_BASE_H)
    ent["sequence_base_w"] = bw
    ent["sequence_base_h"] = bh
    ent["sequence_profile_key"] = f"{bw}x{bh}"
    pl = ent.get("sequence_playlist")
    if isinstance(pl, list):
        clean: list[str] = []
        for item in pl:
            if not isinstance(item, str):
                continue
            ref = normalize_playlist_ref(item)
            if ref and ref not in clean:
                clean.append(ref)
        ent["sequence_playlist"] = clean
    pl2 = ent.get("sequence_playlist_secondary")
    if isinstance(pl2, list):
        clean2: list[str] = []
        for item in pl2:
            if not isinstance(item, str):
                continue
            ref = normalize_playlist_ref(item)
            if ref and ref not in clean2:
                clean2.append(ref)
        ent["sequence_playlist_secondary"] = clean2
    return ent


def _normalize_groups_payload(raw_groups: list) -> list:
    """Normalize incoming groups payload while preserving unknown keys for compatibility."""
    if not isinstance(raw_groups, list):
        return []
    normalized_groups: list = []
    for raw_group in raw_groups:
        if not isinstance(raw_group, dict):
            normalized_groups.append(raw_group)
            continue
        group = dict(raw_group)
        phones = group.get("phones")
        if isinstance(phones, dict):
            out_phones: dict[str, dict] = {}
            for raw_serial, raw_ent in phones.items():
                if not isinstance(raw_serial, str):
                    continue
                serial = raw_serial.strip()
                if not serial:
                    continue
                out_phones[serial] = _normalize_phone_entry_for_runtime(raw_ent)
            group["phones"] = out_phones
        normalized_groups.append(group)
    return normalized_groups


_APK_NAME_RE = re.compile(r"^[A-Za-z0-9_\- .]+\.apk$", re.IGNORECASE)


def _group_apk_path(group: dict):
    """Validate and resolve a group's ``apk`` (filename under APK_DIR).

    Returns a real ``Path`` or ``None``. The name is validated against a strict
    regex and the resolved path must stay inside ``APK_DIR`` so a malicious
    ``apk`` value can never point outside the APK folder.
    """
    name = str(group.get("apk") or "").strip()
    if not name or not _APK_NAME_RE.match(name):
        return None
    try:
        p = (APK_DIR / name).resolve()
    except (ValueError, OSError):
        return None
    if not str(p).startswith(str(APK_DIR.resolve())):
        return None
    return p if p.is_file() else None


def _install_group_apk_once(group: dict, serial: str, group_name: str, iteration: int, loop) -> None:
    """Install a group's APK on one phone before its first sequence run.

    Runs once (iteration 0) per group run. Safe no-op when the group has no
    ``apk`` or the value is invalid (see :func:`_group_apk_path`).
    """
    if iteration != 0:
        return
    apk = _group_apk_path(group)
    if apk is None:
        return
    try:
        r = subprocess.run(
            [adb_executable(), "-s", serial, "install", "-r", str(apk)],
            capture_output=True,
            timeout=180,
            creationflags=_ADB_SUBPROC_FLAGS,
        )
        # capture_output=True yields bytes — str "Success" in bytes raises TypeError.
        out = (r.stdout or b"") + (r.stderr or b"")
        ok = bool(r) and r.returncode == 0 and b"Success" in out
    except (OSError, subprocess.TimeoutExpired, TypeError):
        ok = False
    invalidate_cache(serial)
    asyncio.run_coroutine_threadsafe(
        broadcast({"type": "log",
                   "msg": f"[{group_name}] {apk.name} "
                          f"{'installed' if ok else 'APK install failed'} on {serial}"}),
        loop,
    )


def _total_steps_for_groups_online(raw_groups: list, online_serials: set[str]) -> int:
    n = 0
    for g in raw_groups:
        if not isinstance(g, dict):
            continue
        pmap = g.get("phones") or {}
        if not isinstance(pmap, dict):
            continue
        for raw_key in pmap:
            if not isinstance(raw_key, str) or not raw_key.strip():
                continue
            sk = raw_key.strip()
            if sk not in online_serials:
                continue
            ent = _phone_entry_for_serial(pmap, sk) or {}
            inline = _inline_steps_fallback(g, ent)
            n += estimate_step_count(ent, inline)
    return n


def _online_serials_for_group(group: dict, online_serials: set[str]) -> list[str]:
    """ADB serials from ``group['phones']`` that are online (keys normalized with ``strip``)."""
    phone_map = group.get("phones") or {}
    if not isinstance(phone_map, dict):
        return []
    out: list[str] = []
    for raw_key in phone_map.keys():
        if not isinstance(raw_key, str):
            continue
        sk = raw_key.strip()
        if sk in online_serials:
            out.append(sk)
    return list(dict.fromkeys(out))


def _slot_sort_key(serial: str) -> tuple:
    """Stable farm-slot order for MuMu guest-bridge serials (``10.0.2.N:5555``).

    Emulator serials (and their assigned IPs) change on every reboot; the only stable
    identity is the farm slot. Ordering by the guest octet keeps Tor-slot assignment
    (``phone_idx_from_adb_serial`` fallback ``N // 10``) aligned with config order so
    a group's playlists stay bound to the same farm slot regardless of IP churn.
    """
    m = re.match(r"^10\.0\.2\.(\d+):\d+$", str(serial).strip())
    if m:
        return (0, int(m.group(1)), str(serial))
    m2 = re.match(r"^emulator-(\d+)$", str(serial).strip())
    if m2:
        return (1, int(m2.group(1)), str(serial))
    return (2, 0, str(serial))


def _remap_group_serials_to_live(raw_groups: list, online_serials: set[str], *, persist: bool = True) -> dict:
    """Re-key each group's ``phones`` map to live ADB serials by farm slot.

    MuMu (and emulators in general) reassign guest IPs on every reboot, so a saved
    ``groups_config.json`` quickly points at dead serials. Instead of refusing to run,
    the runner pairs each configured phone entry (in slot order) with the matching live
    serial (in slot order) and rewrites the map. The remap is persisted so the GUI shows
    the live serials too.

    Returns ``{"remapped": int, "total_groups": int}``.
    """
    if not online_serials:
        return {"remapped": 0, "total_groups": len(raw_groups)}
    live_sorted = sorted(online_serials, key=_slot_sort_key)
    remapped = 0
    for g in raw_groups:
        if not isinstance(g, dict):
            continue
        pmap = g.get("phones")
        if not isinstance(pmap, dict) or not pmap:
            continue
        keys = [str(k).strip() for k in pmap.keys() if str(k).strip()]
        if not keys:
            continue
        if all(k in online_serials for k in keys):
            continue  # already live — no churn
        # Fewer live phones than configured slots is normal (emulators reboot,
        # reconnect slowly, some stay offline) — still run every phone that IS
        # online, pairing the first N configured slots with the N live serials.
        # Skipping the whole group here is why the farm looked dead: an 8-slot
        # config against 6 live phones bailed and ran nothing.
        n = min(len(keys), len(live_sorted))
        new_map: dict[str, dict] = {}
        for i in range(n):
            new_map[live_sorted[i]] = pmap[keys[i]] if isinstance(pmap[keys[i]], dict) else {}
        g["phones"] = new_map
        remapped += 1
    saved = False
    prefs_saved = False
    if persist and remapped:
        saved = _persist_groups_cfg({"groups": raw_groups})
        prefs_saved = _sync_phone_serials_prefs(list(live_sorted))
    return {
        "remapped": remapped,
        "total_groups": len(raw_groups),
        "saved": saved,
        "prefs_saved": prefs_saved,
    }


def _sync_phone_serials_prefs(live_sorted: list[str]) -> bool:
    """Rewrite ``phone_serials`` only if the disk copy matches.

    A corrupt prefs file is not replaced. Replacing it used to wipe
    ``mumu_setup_complete``.
    """
    prefs_path = REC_DIR / "desktop_prefs.json"
    data: dict = {}
    if prefs_path.is_file():
        try:
            loaded = json.loads(prefs_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return False
        if not isinstance(loaded, dict):
            return False
        data = loaded
    data["phone_serials"] = list(live_sorted)
    try:
        prefs_path.parent.mkdir(parents=True, exist_ok=True)
        prefs_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        stored = json.loads(prefs_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, json.JSONDecodeError, UnicodeError, ValueError):
        return False
    return isinstance(stored, dict) and stored.get("phone_serials") == list(live_sorted)


def _redroid_name_from_ps_text(serial: str, text: str) -> str | None:
    """Container name whose published host port is this serial. Never 5555 + index."""
    want = str(serial or "").strip()
    if not want.startswith("127.0.0.1:"):
        return None
    for line in (text or "").splitlines():
        if "\t" not in line:
            continue
        name, ports = line.split("\t", 1)
        name = name.strip().lstrip("/")
        if not name.startswith("redroid-"):
            continue
        for match in re.finditer(r"(?:0\.0\.0\.0|127\.0\.0\.1):(\d+)->", ports):
            if f"127.0.0.1:{match.group(1)}" == want:
                return name
    return None


def _redroid_name_for_serial(serial: str) -> str | None:
    """Published redroid container for a host serial. Do not call docker if the engine is down."""
    if not str(serial or "").startswith("127.0.0.1:"):
        return None
    if not _docker_engine_running():
        return None
    code, out = _docker_cmd(
        ["docker", "ps", "-a", "--filter", "name=redroid-", "--format", "{{.Names}}\t{{.Ports}}"],
        timeout=15,
    )
    if code != 0:
        return None
    return _redroid_name_from_ps_text(serial, out)


def _stop_device_result(serial: str) -> dict:
    """Stop a phone without ``adb reboot -p``.

    Studio AVD: ``emu kill``. Redroid: ``docker stop`` on the published container.
    MuMu and other TCP guests: disconnect ADB only. Powering those off with
    ``adb reboot -p`` wedges the VM.
    """
    serial = str(serial or "").strip()
    if serial.startswith("emulator-"):
        res = _adb(serial, "emu", "kill")
        stopped = emu_kill_landed(res.text, res.returncode)
        return {
            "serial": serial,
            "action": "killed" if stopped else "failed",
            "ok": stopped,
            "note": "AVD stopped" if stopped else (res.text or "emu kill did not report OK")[:200],
        }
    redroid = _redroid_name_for_serial(serial)
    if redroid:
        if not _docker_engine_running():
            return {
                "serial": serial,
                "action": "failed",
                "ok": False,
                "name": redroid,
                "note": "Docker is not running — the phone was not stopped.",
            }
        code, out = _docker_cmd(["docker", "stop", redroid], timeout=90)
        icode, iout = _docker_cmd(
            ["docker", "inspect", "-f", "{{.State.Running}}", redroid],
            timeout=15,
        )
        _adb_global("disconnect", serial)
        stopped = docker_stop_landed(code, icode, iout)
        return {
            "serial": serial,
            "action": "docker_stop" if stopped else "failed",
            "ok": stopped,
            "name": redroid,
            "note": (
                f"Stopped {redroid}"
                if stopped
                else (iout or out or "container still running")[:200]
            ),
        }
    if re.match(r"^[\d.]+:\d+$", serial):
        res = _adb_global("disconnect", serial)
        disconnected = not _adb_indicates_trouble(res)
        return {
            "serial": serial,
            "action": "disconnected" if disconnected else "failed",
            "ok": disconnected,
            "note": (
                "Disconnected from ADB. The phone was not powered off — "
                "power MuMu off in the MuMu window, not with adb."
                if disconnected
                else (res.text or "disconnect failed")[:200]
            ),
        }
    return {
        "serial": serial,
        "action": "skipped",
        "ok": False,
        "note": "USB phones cannot be stopped from here.",
    }


def _stop_device(serial: str) -> dict:
    return _stop_device_result(serial)


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "unknown"


def dashboard_reach_host() -> str:
    """Host the operator can actually open.

    A loopback bind does not accept the PC's LAN address. Advertising that
    LAN address copied a dead link and looked like a phone exit. An all-interfaces
    bind can be reached on the LAN address. Phone traffic never uses this host.
    """
    host = str(LISTEN_HOST or "").strip()
    if host in ("", "0.0.0.0", "::", "[::]"):
        return get_local_ip()
    return host




def _phone_idx_from_serial(serial: str) -> int:
    """Tor slot from ADB serial — delegated to :func:`tor_manager.phone_idx_from_adb_serial`."""
    return tor_manager.phone_idx_from_adb_serial(serial)


def _guest_loopback_pinned(applied: dict | None) -> bool:
    """True only when the guest proxy write landed on 127.0.0.1:<port>."""
    if not isinstance(applied, dict) or not applied.get("http_proxy_applied"):
        return False
    proxy = str(applied.get("http_proxy") or "").strip()
    if not proxy.startswith("127.0.0.1:") or proxy.endswith(":0"):
        return False
    try:
        return int(proxy.split(":", 1)[1]) > 0
    except (IndexError, ValueError):
        return False


def _tor_setup_line(
    name: str,
    *,
    ok_socks: bool,
    ok_http: bool,
    pinned: bool,
    w_socks: float,
    w_http: float,
) -> str:
    """SOCKS up is not a pin. Tor ready means the guest has a loopback exit."""
    if ok_socks and ok_http and pinned:
        return f"{name}: Tor ready"
    parts: list[str] = []
    if not ok_socks:
        parts.append(f"Tor still starting (waited {w_socks}s)")
    if not ok_http:
        parts.append(f"Internet tunnel not open (waited {w_http}s)")
    if not pinned:
        parts.append("guest proxy was not set to a loopback exit")
    return f"{name}: FAILED: " + "; ".join(parts)


_SEQUENCE_STEP_TYPES = frozenset({
    "open_url", "launch_app", "tap", "wait", "swipe", "keyevent",
    "close_app", "clear_cookies", "type_text",
    "rotate_identity", "full_reset",
})
_PKG_STEP_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.]*$")
_KEY_STEP_RE = re.compile(r"^[A-Z0-9_]+$")


def run_sequence_step(serial: str, step: dict, interrupt_check=None, hv_rng=None, adb_issue_cb=None) -> bool:
    """Execute one automation step. Used by groups runner and the daily scheduler.

    Returns False when the step did not land. Callers must not mark that phone completed.

    ``hv_rng``: per-run :class:`random.Random` from ``human_variation.rng_for_run(serial, cycle)``
    when human-like variance is enabled (see ``config.HUMAN_VARIATION``).

    ``adb_issue_cb``: optional ``callable(tag: str, res: AdbResult)`` when ADB output/rc indicates failure
    (groups runner uses this to push WebSocket log lines and fill ``/api/groups/adb_errors``).
    """
    def _notify_adb(tag: str, res: AdbResult) -> None:
        if adb_issue_cb is not None and _adb_indicates_trouble(res):
            adb_issue_cb(tag, res)

    if interrupt_check is not None and not interrupt_check():
        return False
    t = step.get("type", "")
    if t not in _SEQUENCE_STEP_TYPES:
        return False
    if not ensure_adb_serial_ready(serial, adb_issue_cb):
        log.warning("Skipping automation step type=%s — device not reachable serial=%s", t, serial)
        return False
    if t == "open_url":
        try:
            _idx_rep = _phone_idx_from_serial(serial)
            _rep = tor_manager.repair_adb_reverse_for_proxy(serial, _idx_rep)
            if _rep.get("repaired"):
                log.info(
                    "Proxy reverse repaired serial=%s port=%s",
                    serial,
                    _rep.get("port"),
                )
        except Exception:
            log.debug("repair_adb_reverse before open_url failed serial=%s", serial, exc_info=True)
        invalidate_webview_inset_cache(serial)
        url = _normalize_url_for_intent(step.get("url", "https://google.com"))
        try:
            _p = urllib.parse.urlparse(url)
            if _p.scheme not in ("http", "https") or not _p.netloc or " " in url:
                return False
        except Exception:
            return False
        _idx_ou = _phone_idx_from_serial(serial)
        _ens_ou = {"ok": True}
        if not _pharmflow_skip_tor_wait():
            tor_manager.start_tor_warm_background(_idx_ou)
            _ens_ou = tor_manager.ensure_tor_ready(serial, _idx_ou)
            if _ens_ou.get("ok"):
                note_adb_serial_tor_settled(serial)
            else:
                log.warning(
                    "open_url: Tor/proxy not ready serial=%s (%s)",
                    serial,
                    _ens_ou.get("error", "unknown"),
                )
        try:
            _fp = mumu_fingerprint.ensure_fingerprint_before_browse(
                serial,
                log_fn=lambda msg: log.info("open_url fingerprint serial=%s — %s", serial, msg),
            )
            if _fp.get("audit", {}).get("leaks"):
                log.warning(
                    "open_url fingerprint leaks serial=%s count=%s — cold-boot MuMu after "
                    "PharmFlow Phones → Set up my phones, or Boot/Launch → Re-apply hide emulator",
                    serial,
                    len(_fp["audit"]["leaks"]),
                )
            _sa = _fp.get("audit") or {}
            _sl = _sa.get("leaks") or []
            _set_phone_stealth(
                serial,
                fp_state="clean" if _sa.get("clean") else ("leaking" if _sl else "assessed"),
                leak_count=len(_sl),
            )
            try:
                _prof_dis = mumu_fingerprint.profile_for_serial(serial, farm_index=_idx_ou)
                if _prof_dis and _prof_dis.get("brand"):
                    _set_phone_stealth(serial, disguise=f"{_prof_dis['brand']} {_prof_dis['model']}")
            except Exception:
                pass
        except Exception:
            log.debug("fingerprint before open_url failed serial=%s", serial, exc_info=True)
        if _adb_truthy_env("PHARMFLOW_OPEN_URL_NET_CHECK"):
            _hint = _device_network_hint_online(serial)
            if _hint is False:
                try:
                    _nb = float(os.environ.get("PHARMFLOW_OPEN_URL_NET_BACKOFF_SEC", "3") or 3)
                except (TypeError, ValueError):
                    _nb = 3.0
                _nb = min(20.0, max(0.0, _nb))
                log.info(
                    "open_url: optional ping check looks offline serial=%s — sleeping %.1fs before launch "
                    "(emulator bridge/DNS issues: see docs/PharmFlow_emulator_MuMu_and_sequences.md checklist)",
                    serial,
                    _nb,
                )
                time.sleep(_nb)
        try:
            _rb = float(os.environ.get("PHARMFLOW_OPEN_URL_RETRY_BACKOFF_SEC", "2.5") or 2.5)
        except (TypeError, ValueError):
            _rb = 2.5
        _rb = min(30.0, max(0.5, _rb))

        exit_ok, exit_note = _dashboard_open_exit_ready(serial)
        if not exit_ok:
            # Empty, :0, or any host other than 127.0.0.1 sends the page out this PC.
            log.warning("open_url refused serial=%s — %s", serial, exit_note)
            if adb_issue_cb is not None:
                adb_issue_cb(
                    "open_url",
                    AdbResult(argv=(), returncode=1, stdout="", stderr=exit_note),
                )
            return False
        _tor_block = _dead_tor_http_reason(_idx_ou, exit_note, _ens_ou)
        if _tor_block:
            log.warning(
                "open_url refused serial=%s — Tor HTTP exit is not ready (%s)",
                serial,
                _tor_block,
            )
            if adb_issue_cb is not None:
                adb_issue_cb(
                    "open_url",
                    AdbResult(argv=(), returncode=1, stdout="", stderr=_tor_block),
                )
            return False
        _force_stop_browser_for_dabflow_cdp(serial, url)
        res = _open_url_with_fallbacks(serial, url, step)
        landed = am_start_reported_landing(res.stdout, res.stderr)
        if not landed:
            log.warning(
                "open_url am start did not land serial=%s — retry once after %.1fs",
                serial,
                _rb,
            )
            time.sleep(_rb)
            res = _open_url_with_fallbacks(serial, url, step)
        res = _retry_open_url_action_view_for_browser_net_error(serial, url, res)
        landed = am_start_reported_landing(res.stdout, res.stderr)
        _notify_adb("open_url", res)
        if landed and "getdabflow.app" in (url or "").lower():
            _bump_farm_visit(serial)
        if landed:
            _wait_for_browser_pid_after_open(serial, step)
        try:
            pws = step.get("post_wait_secs", None)
            if pws is not None and pws != "":
                base = max(0.0, float(pws))
                if "getdabflow.app" in url.lower():
                    from dabflow_layout import AGE_GATE_OPEN_POST_WAIT_MAX_SEC

                    phase = str(step.get("phase") or "").lower()
                    cp = str(step.get("checkpoint") or "").lower()
                    if step_is_fast_phase(step) or phase in ("pre_site_fast", "") or cp in ("loaded", ""):
                        base = min(base, AGE_GATE_OPEN_POST_WAIT_MAX_SEC)
                try:
                    extra = float(os.environ.get("PHARMFLOW_OPEN_URL_EXTRA_WAIT", "") or 0)
                except (TypeError, ValueError):
                    extra = 0.0
                if step_is_fast_phase(step):
                    extra = 0.0
                extra = max(0.0, extra)
                time.sleep(base + extra)
            elif not step_is_fast_phase(step):
                _settle = _open_url_settle_after_pid(step)
                if _settle > 0:
                    time.sleep(_settle)
        except (TypeError, ValueError):
            pass
        if "getdabflow.app" in url.lower():
            try:
                from dabflow_mantis_client_patch import maybe_apply_after_open_url_step

                maybe_apply_after_open_url_step(
                    serial,
                    url,
                    _phone_idx_from_serial(serial),
                )
            except Exception:
                log.debug("dabflow Mantis patch after open_url failed serial=%s", serial, exc_info=True)
        if not landed:
            return False
    elif t == "launch_app":
        pkg = str(step.get("package", "")).strip()
        if not _PKG_STEP_RE.match(pkg):
            return False
        res = _adb(
            serial,
            "shell",
            "monkey",
            "-p",
            pkg,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        )
        if not monkey_launch_reported(res.stdout, res.stderr):
            log.warning("launch_app monkey did not land serial=%s pkg=%s — retry once", serial, pkg)
            time.sleep(0.4)
            res = _adb(
                serial,
                "shell",
                "monkey",
                "-p",
                pkg,
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            )
        if not monkey_launch_reported(res.stdout, res.stderr):
            _notify_adb(
                "launch_app",
                AdbResult(
                    argv=res.argv,
                    returncode=1,
                    stdout=res.stdout,
                    stderr=res.stderr or "monkey did not report events injected",
                ),
            )
            return False
        _notify_adb("launch_app", res)
        try:
            pws = step.get("post_wait_secs", None)
            if pws is not None and pws != "":
                base = max(0.0, float(pws))
                try:
                    extra = float(os.environ.get("PHARMFLOW_OPEN_URL_EXTRA_WAIT", "") or 0)
                except (TypeError, ValueError):
                    extra = 0.0
                extra = max(0.0, extra)
                time.sleep(base + extra)
        except (TypeError, ValueError):
            pass
    elif t == "tap":
        tap_landed = False
        pre_ms = float(step.get("pre_wait_ms", 0) or 0)
        is_age_pre = bool(
            step.get("age_verification") is True
            or step.get("age_gate") is True
            or str(step.get("checkpoint", "")).strip().lower() in ("age_verification", "age_gate")
        )
        if _hv.enabled() and hv_rng is not None and pre_ms > 0:
            pre_ms = _hv.scaled_pre_wait_ms(pre_ms, hv_rng)
        if is_age_pre:
            from dabflow_layout import AGE_GATE_PRE_WAIT_MAX_MS

            pre_ms = min(AGE_GATE_PRE_WAIT_MAX_MS, pre_ms)
        if pre_ms > 0:
            time.sleep(pre_ms / 1000.0)
        try:
            retries = int(step.get("retries", 1) or 1)
        except (TypeError, ValueError):
            retries = 1
        is_age = bool(
            step.get("age_verification") is True
            or step.get("age_gate") is True
            or str(step.get("checkpoint", "")).strip().lower() in ("age_verification", "age_gate")
        )
        if is_age:
            retries = max(retries, 5)
        retries = max(1, retries)
        try:
            jitter = int(step.get("jitter", 0) or 0)
        except (TypeError, ValueError):
            jitter = 0
        jitter = max(0, jitter)
        if is_age:
            jitter = min(jitter, 6)
        _ej_mult = 1.0 if is_age else _emulator_tap_jitter_multiplier(serial)
        ej = int(round(_hv.effective_tap_jitter(jitter, hv_rng) * _ej_mult))
        if is_age:
            ej = min(ej, 6)
        _bw, _bh = baseline_from_step(step)
        _bx0 = _coerce_step_int(step.get("x", 0), 0)
        _by0 = _coerce_step_int(step.get("y", 0), 0)
        if is_age:
            from dabflow_layout import age_gate_page_bounds, age_gate_tap_page_coords

            _bx0, _by0 = age_gate_tap_page_coords()
            age_x_lo, age_x_hi, age_y_lo, age_y_hi = age_gate_page_bounds()
        bx, by_page = _scale_xy_for_serial(serial, _bx0, _by0, _bw, _bh)
        _wv_top = webview_content_top_inset(serial, force_refresh=is_age)
        _phys = _physical_size_for_serial(serial)
        _phys_h = _phys[1] if _phys else _bh
        is_bottom_nav = bool(step.get("bottom_nav"))
        if is_bottom_nav:
            by = by_page
        else:
            by = baseline_y_to_screen_y(by_page, phys_h=_phys_h, base_h=_bh, wv_top=_wv_top)
        bx, by = _clamp_xy_for_serial(serial, bx, by)
        age_x_min = age_x_max = age_y_min = age_y_max = None
        if is_age:
            age_x_min, _ = _scale_xy_for_serial(serial, age_x_lo, 0, _bw, _bh)
            age_x_max, _ = _scale_xy_for_serial(serial, age_x_hi, 0, _bw, _bh)
            _, age_y_lo_s = _scale_xy_for_serial(serial, 0, age_y_lo, _bw, _bh)
            _, age_y_hi_s = _scale_xy_for_serial(serial, 0, age_y_hi, _bw, _bh)
            age_y_min = baseline_y_to_screen_y(age_y_lo_s, phys_h=_phys_h, base_h=_bh, wv_top=_wv_top)
            age_y_max = baseline_y_to_screen_y(age_y_hi_s, phys_h=_phys_h, base_h=_bh, wv_top=_wv_top)
        _maybe_wake_before_touch(serial)
        age_tapped_uia = False
        if is_age:
            try:
                from age_gate_uia import wait_for_age_yes_button

                uia_center = wait_for_age_yes_button(serial, timeout_sec=12.0)
            except Exception:
                uia_center = None
            if uia_center:
                ucx, ucy = uia_center
                for r in range(retries):
                    if interrupt_check is not None and not interrupt_check():
                        return False
                    jx = ucx + (hv_rng.randint(-ej, ej) if hv_rng else random.randint(-ej, ej))
                    jy = ucy + (hv_rng.randint(-ej, ej) if hv_rng else random.randint(-ej, ej))
                    jx, jy = _clamp_xy_for_serial(serial, jx, jy)
                    if _adb_truthy_env("PHARMFLOW_LOG_ADB_INPUT"):
                        log.info("adb input tap (age uia) serial=%s x=%s y=%s", serial, jx, jy)
                    res = _adb(serial, "shell", "input", "tap", str(jx), str(jy))
                    _notify_adb("tap_age_uia", res)
                    if _adb_landed(res):
                        tap_landed = True
                    if r + 1 < retries:
                        time.sleep(hv_rng.uniform(0.12, 0.28) if hv_rng else random.uniform(0.12, 0.28))
                age_tapped_uia = True
        if not age_tapped_uia:
            for r in range(retries):
                if interrupt_check is not None and not interrupt_check():
                    return False
                jx = bx + (hv_rng.randint(-ej, ej) if hv_rng else random.randint(-ej, ej))
                jy = by + (hv_rng.randint(-ej, ej) if hv_rng else random.randint(-ej, ej))
                jx, jy = _clamp_xy_for_serial(serial, jx, jy)
                if is_age and age_x_min is not None and age_x_max is not None:
                    jx = min(age_x_max, max(age_x_min, jx))
                    jy = min(age_y_max, max(age_y_min, jy))
                if _adb_truthy_env("PHARMFLOW_LOG_ADB_INPUT"):
                    log.info("adb input tap serial=%s x=%s y=%s", serial, jx, jy)
                res = _adb(serial, "shell", "input", "tap", str(jx), str(jy))
                _notify_adb("tap", res)
                if _adb_landed(res):
                    tap_landed = True
                if _looks_like_inject_events_denied(res):
                    _log_inject_events_actionable_once(serial, "tap")
                    if _wm_focus_cheat_enabled():
                        res = _inject_retry_after_close_dialogs(
                            serial, ["input", "tap", str(jx), str(jy)]
                        )
                        _notify_adb("tap_wm_focus_cheat_retry", res)
                    if _looks_like_inject_events_denied(res):
                        log.warning(
                            "tap blocked by device policy serial=%s (INJECT_EVENTS). "
                            "Trying keyevent ENTER.",
                            serial,
                        )
                        res_fb = _adb(serial, "shell", "input", "keyevent", "ENTER")
                        _notify_adb("tap_policy_fallback_enter", res_fb)
                        if _adb_landed(res_fb):
                            tap_landed = True
                        _log_inject_events_doc_hint_if_needed(res_fb)
                if r + 1 < retries:
                    if is_age:
                        gap = hv_rng.uniform(0.12, 0.28) if hv_rng else random.uniform(0.12, 0.28)
                    elif hv_rng is not None:
                        gap = hv_rng.uniform(0.08, 0.22)
                    else:
                        gap = random.uniform(0.08, 0.22)
                    time.sleep(gap)
        if is_age:
            time.sleep(0.05)
        if not tap_landed:
            return False
        if step_wants_session_notes_dismiss(step) and not dismiss_session_notes_verified(serial):
            log.warning("popup dismiss did not land serial=%s", serial)
            return False
    elif t == "wait":
        try:
            secs = float(step.get("seconds", 1))
        except (TypeError, ValueError):
            secs = 1.0
        if secs < 0:
            secs = 0.0
        cp = str(step.get("checkpoint", "")).strip().lower()
        if (
            _hv.enabled()
            and hv_rng is not None
            and not step_is_fast_phase(step)
            and not step_is_timer_complete_wait(step)
        ):
            secs = _hv.scaled_wait_seconds(secs, hv_rng, checkpoint=cp)
            if secs < 0:
                secs = 0.0
        deadline = time.time() + secs
        while time.time() < deadline:
            if interrupt_check is not None and not interrupt_check():
                return False
            time.sleep(min(0.25, max(0.0, deadline - time.time())))
        if step_wants_session_notes_gone(step) and not wait_session_notes_gone(
            serial, timeout_sec=8.0
        ):
            log.warning("session notes still up serial=%s", serial)
            return False
    elif t == "swipe":
        _sw_bw, _sw_bh = baseline_from_step(step)
        x1, y1 = _scale_xy_for_serial(
            serial,
            _coerce_step_int(step.get("x1", 0), 0),
            _coerce_step_int(step.get("y1", 0), 0),
            _sw_bw,
            _sw_bh,
        )
        x2, y2 = _scale_xy_for_serial(
            serial,
            _coerce_step_int(step.get("x2", 0), 0),
            _coerce_step_int(step.get("y2", 0), 0),
            _sw_bw,
            _sw_bh,
        )
        _wv_top_sw = webview_content_top_inset(serial, force_refresh=False)
        _phys_sw = _physical_size_for_serial(serial)
        _phys_h_sw = _phys_sw[1] if _phys_sw else _sw_bh
        y1 = baseline_y_to_screen_y(y1, phys_h=_phys_h_sw, base_h=_sw_bh, wv_top=_wv_top_sw)
        y2 = baseline_y_to_screen_y(y2, phys_h=_phys_h_sw, base_h=_sw_bh, wv_top=_wv_top_sw)
        x1, y1 = _clamp_xy_for_serial(serial, x1, y1)
        x2, y2 = _clamp_xy_for_serial(serial, x2, y2)
        _maybe_wake_before_touch(serial)
        if _adb_truthy_env("PHARMFLOW_LOG_ADB_INPUT"):
            log.info(
                "adb input swipe serial=%s x1=%s y1=%s x2=%s y2=%s",
                serial, x1, y1, x2, y2,
            )
        ms_gesture = str(max(1, _coerce_step_int(step.get("ms", 400), 400)))
        swipe_argv = [
            "input",
            "swipe",
            str(x1),
            str(y1),
            str(x2),
            str(y2),
            ms_gesture,
        ]
        res = _adb(serial, "shell", *swipe_argv)
        _notify_adb("swipe", res)
        if _looks_like_inject_events_denied(res):
            _log_inject_events_actionable_once(serial, "swipe")
            if _wm_focus_cheat_enabled():
                res = _inject_retry_after_close_dialogs(serial, swipe_argv)
                _notify_adb("swipe_wm_focus_cheat_retry", res)
            if _looks_like_inject_events_denied(res):
                key = _fallback_keyevent_for_swipe(x1, y1, x2, y2)
                if key:
                    log.warning(
                        "swipe blocked by device policy serial=%s (INJECT_EVENTS). "
                        "Fallback keyevent %s.",
                        serial,
                        key,
                    )
                    res_fb = _adb(serial, "shell", "input", "keyevent", key)
                    _notify_adb(f"swipe_policy_fallback_{key.lower()}", res_fb)
                    if _adb_landed(res_fb):
                        res = res_fb
                    _log_inject_events_doc_hint_if_needed(res_fb)
        if not _adb_landed(res):
            return False
    elif t == "keyevent":
        key = str(step.get("key", "BACK"))
        if not _KEY_STEP_RE.match(key):
            return False
        res = _adb(serial, "shell", "input", "keyevent", key)
        _notify_adb("keyevent", res)
        if not _adb_landed(res):
            return False
    elif t == "close_app":
        preferred = str(step.get("package", "")).strip()
        pkg = preferred if looks_like_package(preferred) else ""
        if not pkg:
            pkg = browser_pkg_for_clear(serial, "") or ""
        if not pkg or not _PKG_STEP_RE.match(pkg):
            log.info("close_app did not land — no browser package resolved on %s", serial)
            return False
        res = _adb(serial, "shell", "am", "force-stop", pkg)
        _notify_adb("close_app", res)
        if not _adb_landed(res):
            return False
    elif t == "rotate_identity":
        idx = _phone_idx_from_serial(serial)
        rotated = tor_manager.rotate_identity_adb(serial, idx)
        if not (bool(isinstance(rotated, dict) and rotated.get("circuit_rotated")) and _guest_loopback_pinned(rotated)):
            log.warning(
                "rotate_identity did not land a new loopback exit serial=%s proxy=%s",
                serial,
                (rotated or {}).get("http_proxy") if isinstance(rotated, dict) else "",
            )
            _notify_adb(
                "rotate_identity",
                AdbResult(
                    argv=(),
                    returncode=1,
                    stdout="",
                    stderr="rotate did not pin a new loopback exit",
                ),
            )
            return False
    elif t == "clear_cookies":
        preferred = str(step.get("package", "")).strip()
        if preferred and not _PKG_STEP_RE.match(preferred):
            log.info("clear_cookies ignored invalid package '%s' on %s", preferred, serial)
            preferred = ""
        pkg = browser_pkg_for_clear(serial, preferred)
        if not pkg:
            log.info("clear_cookies did not land — no browser package found on %s", serial)
            return False
        res = _adb(serial, "shell", "pm", "clear", pkg)
        if not pm_clear_reported(res.stdout, res.stderr):
            log.warning("clear_cookies pm clear did not report Success serial=%s pkg=%s — retry once", serial, pkg)
            time.sleep(0.4)
            res = _adb(serial, "shell", "pm", "clear", pkg)
        if not pm_clear_reported(res.stdout, res.stderr):
            log.warning(
                "clear_cookies did not clear %s on %s — force-stop is not a cookie clear",
                pkg,
                serial,
            )
            _notify_adb(
                "clear_cookies",
                AdbResult(
                    argv=res.argv,
                    returncode=1,
                    stdout=res.stdout,
                    stderr=res.stderr or "pm clear did not report Success",
                ),
            )
            return False
        _adb(serial, "shell", "am", "force-stop", pkg)
    elif t == "type_text":
        raw_text = step.get("text", "")
        text = urllib.parse.quote(raw_text, safe="").replace("%20", "%s")
        res = _adb(serial, "shell", "input", "text", text)
        _notify_adb("type_text", res)
        if not _adb_landed(res):
            return False
    elif t == "full_reset":
        idx = _phone_idx_from_serial(serial)
        reset = tor_manager.full_identity_reset(serial, idx)
        if not _identity_reset_landed(reset if isinstance(reset, dict) else None):
            log.warning(
                "full_reset did not land a new circuit on a pinned loopback exit serial=%s proxy=%s",
                serial,
                (reset or {}).get("http_proxy") if isinstance(reset, dict) else "",
            )
            _notify_adb(
                "full_reset",
                AdbResult(
                    argv=(),
                    returncode=1,
                    stdout="",
                    stderr="identity reset did not land a new circuit on a pinned loopback exit",
                ),
            )
            return False
    return True


def _get_resources() -> dict:
    try:
        import psutil
        mem = psutil.virtual_memory()
        max_phones = max(0, int((mem.available / 1024**3 - 2.0) / 1.5))
        return {
            "ram_used_pct":          mem.percent,
            "ram_used_gb":           round(mem.used       / 1024**3, 1),
            "ram_free_gb":           round(mem.available  / 1024**3, 1),
            "ram_total_gb":          round(mem.total      / 1024**3, 1),
            "max_phones_recommended": max_phones,
        }
    except ImportError:
        return {
            "ram_used_pct": 0, "ram_used_gb": 0,
            "ram_free_gb": 0, "ram_total_gb": 0,
            "max_phones_recommended": None,
        }


# ── WebSocket broadcast ───────────────────────────────────────────────────────

async def broadcast(msg: dict):
    if not _ws_clients:
        return
    data = json.dumps(msg)
    clients = set(_ws_clients)
    await asyncio.gather(*[ws.send(data) for ws in clients], return_exceptions=True)


async def push_phones():
    await broadcast({"type": "phones_update", "phones": list_phones()})


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _http(code: int, ctype: str, body: bytes, extra: str = "") -> bytes:
    status = {200: "OK", 204: "No Content", 400: "Bad Request", 404: "Not Found"}.get(code, "OK")
    headers = (
        f"HTTP/1.1 {code} {status}\r\n"
        f"Content-Type: {ctype}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Access-Control-Allow-Origin: *\r\n"
        "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
        + extra + "\r\n"
    )
    return headers.encode() + body


def json_ok(data: dict, code: int = 200) -> bytes:
    return _http(code, "application/json", json.dumps(data).encode())


def json_err(msg: str, code: int = 400) -> bytes:
    return _http(code, "application/json", json.dumps({"ok": False, "error": msg}).encode(), "")


def _adb_connect_landed(text: str, returncode: int) -> bool:
    """adb connect succeeded only when it says the device is connected."""
    if returncode != 0:
        return False
    blob = (text or "").lower()
    if any(word in blob for word in ("cannot", "failed", "unable", "error")):
        return False
    return "connected to" in blob or "already connected" in blob


def html_resp(html: str) -> bytes:
    body = html.encode("utf-8")
    return _http(200, "text/html; charset=utf-8", body)


def file_resp(fpath: Path) -> bytes:
    if not fpath.exists():
        return _http(404, "text/plain", b"Not Found")
    mime, _ = mimetypes.guess_type(str(fpath))
    return _http(200, mime or "application/octet-stream", fpath.read_bytes(),
                 "Cache-Control: max-age=3600\r\n")


def cors_ok() -> bytes:
    return _http(204, "text/plain", b"")


def _load_html() -> str:
    if HTML_FILE.exists():
        return HTML_FILE.read_text(encoding="utf-8")
    return "<h1 style='color:#00e676;font-family:monospace'>dashboard.html not found</h1>"


# ── Docker (redroid) phone control + monitoring ──────────────────────────────
# Read what Docker is doing (container state, adb reachability, recent logs) and
# control redroid phones (start/stop/restart + adb connect) from the dashboard.

def _docker_cmd(argv: list[str], timeout: float = 30) -> tuple[int, str]:
    try:
        r = subprocess.run(
            argv, capture_output=True, text=True, errors="replace", timeout=timeout,
            cwd=str(SCRIPT_DIR.parent), creationflags=_ADB_SUBPROC_FLAGS,
        )
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def _tcp_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _docker_engine_running() -> bool:
    """True only when the docker CLI cannot wake Docker Desktop."""
    try:
        if str(SCRIPT_DIR.parent) not in sys.path:
            sys.path.insert(0, str(SCRIPT_DIR.parent))
        from docker_guard import engine_running

        return bool(engine_running())
    except Exception:  # noqa: BLE001
        return False


def _host_port_from_docker_port_text(text: str) -> int | None:
    """Host port from ``docker port`` output. None if Docker did not publish one."""
    ports: list[int] = []
    for match in re.finditer(r"(?:0\.0\.0\.0|127\.0\.0\.1|\[::\]):(\d+)", text or ""):
        port = int(match.group(1))
        if port > 0:
            ports.append(port)
    return ports[0] if ports else None


def _published_host_port(name: str, guest_port: int = 5555) -> int | None:
    """Published host port for one redroid container. Never 5555 + index."""
    code, out = _docker_cmd(["docker", "port", name, str(int(guest_port))], timeout=15)
    if code != 0:
        return None
    return _host_port_from_docker_port_text(out)


def _docker_phone_state() -> tuple[list[dict], str]:
    """Read live redroid containers. Do not stop at the services in a compose file."""
    if not _docker_engine_running():
        # Docker Desktop's CLI shim would launch the GUI from any docker call -
        # report off instead of waking it.
        return [], "Docker off - start Docker Desktop yourself to use redroid phones"
    code, out = _docker_cmd(
        ["docker", "ps", "-a", "--filter", "name=redroid-", "--format", "{{.Names}}\t{{.Status}}"],
        timeout=20,
    )
    if code != 0:
        return [], (out[-300:] or "docker unavailable")

    rows: dict[str, dict] = {}
    for line in (out or "").splitlines():
        if "\t" not in line:
            continue
        name, status = line.split("\t", 1)
        name = name.strip().lstrip("/")
        status = status.strip()
        if not name.startswith("redroid-"):
            continue
        if status.startswith("Up"):
            state_s = "running"
        elif ("Exit" in status) or ("Dead" in status) or status.lower() == "exited":
            state_s = "stopped"
        else:
            state_s = "other"
        rows[name] = {"name": name, "state": state_s, "status": status}

    online = {str(p.get("serial")) for p in list_phones()}
    result: list[dict] = []
    for name, base in sorted(rows.items()):
        port = _published_host_port(name)
        serial = f"127.0.0.1:{port}" if port else ""
        base["adb_port"] = port
        base["tcp_open"] = bool(port) and _tcp_open("127.0.0.1", port)
        base["serial"] = serial
        if serial in online:
            base["adb_state"] = "online"
        elif base["tcp_open"]:
            base["adb_state"] = "listen"
        else:
            base["adb_state"] = "dead"
        _, tail = _docker_cmd(["docker", "logs", "--tail", "6", name], timeout=10)
        base["log_tail"] = tail[-600:]
        result.append(base)
    return result, ""


def emu_kill_landed(text: str, returncode: int | None) -> bool:
    """True only when the emulator console accepted kill.

    ``adb emu kill`` prints OK on success and KO on failure. A silent exit 0
    does not mean the AVD stopped.
    """
    if returncode not in (None, 0):
        return False
    low = (text or "").lower()
    if not low or "ko" in low or "error" in low or "fail" in low:
        return False
    return "ok" in low


def docker_stop_landed(stop_code: int, inspect_code: int, inspect_text: str) -> bool:
    """True only when docker stop exited 0 and the container is not still running.

    ``docker stop`` can exit 0 while the container is still running. The operator
    toast must not say Stopped unless inspect says it is down.
    """
    if stop_code != 0 or inspect_code != 0:
        return False
    return (inspect_text or "").strip().lower() == "false"


async def handle_docker_action(body: bytes) -> bytes:
    try:
        req = json.loads(body or b"{}")
    except Exception:
        return json_err("bad json body")
    name = str(req.get("name") or "").strip()
    action = str(req.get("action") or "").strip()
    valid = name.startswith("redroid-") and name.replace("redroid-", "").isdigit()
    if action not in ("start", "stop", "restart") or not valid:
        return json_err("action must be start|stop|restart for a redroid-N container")
    if not _docker_engine_running():
        return json_err("Docker off - start Docker Desktop yourself, then retry")
    code, out = _docker_cmd(["docker", action, name], timeout=90)
    detail = (out or "")[-400:]
    port = None
    connected = False
    stopped = False
    if action == "stop":
        icode, iout = _docker_cmd(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            timeout=15,
        )
        stopped = docker_stop_landed(code, icode, iout)
        if not stopped:
            detail = (detail + " " + (iout or "container still running")).strip()[-400:]
    if code == 0 and action in ("start", "restart"):
        port = _published_host_port(name)
        if port:
            try:
                proc = subprocess.run(
                    [adb_executable(), "connect", f"127.0.0.1:{port}"],
                    capture_output=True, text=True, errors="replace", timeout=10,
                    creationflags=_ADB_SUBPROC_FLAGS,
                )
                text = ((proc.stdout or "") + (proc.stderr or "")).strip()
                connected = _adb_connect_landed(text, proc.returncode)
            except (OSError, subprocess.TimeoutExpired):
                connected = False
    return json_ok(
        {
            "ok": stopped if action == "stop" else code == 0,
            "stopped": stopped,
            "action": action,
            "name": name,
            "detail": detail,
            "adb_port": port,
            "connected": connected,
        },
        200 if code == 0 else 500,
    )


# ── HTTP request handler ──────────────────────────────────────────────────────

async def handle_http(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        header_bytes = b""
        while b"\r\n\r\n" not in header_bytes:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=5)
            if not chunk:
                break
            header_bytes += chunk

        header_text, _, body_start = header_bytes.partition(b"\r\n\r\n")
        lines = header_text.decode("utf-8", errors="replace").splitlines()
        if not lines:
            writer.close()
            return

        method, path_qs, *_ = lines[0].split(" ", 2)
        path = urllib.parse.urlparse(path_qs).path

        content_length = 0
        for line in lines[1:]:
            if line.lower().startswith("content-length:"):
                try:
                    content_length = int(line.split(":", 1)[1].strip())
                except (ValueError, IndexError):
                    pass
                break

        if content_length > 50_000_000:
            writer.close()
            return
        body_bytes = body_start
        remaining  = content_length - len(body_start)
        while remaining > 0:
            chunk = await asyncio.wait_for(reader.read(min(remaining, 65536)), timeout=10)
            if not chunk:
                break
            body_bytes += chunk
            remaining  -= len(chunk)

        if method == "GET":
            if path.startswith("/api/scheduler"):
                response = await handle_scheduler(path, body_bytes)
            else:
                response = await handle_get(path)
        elif method == "POST":
            response = await handle_post(path, body_bytes)
        elif method == "OPTIONS":
            response = cors_ok()
        else:
            response = _http(404, "text/plain", b"Not Found")

        writer.write(response)
        await writer.drain()

    except Exception as e:
        log.warning("HTTP handler error: %s", e)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


_SEQ_LIST_CACHE: tuple = ()


async def handle_get(path: str) -> bytes:
    static = {
        "/":              lambda: html_resp(_load_html()),
        "/index.html":    lambda: html_resp(_load_html()),
        "/manifest.json": lambda: file_resp(SCRIPT_DIR / "manifest.json"),
        "/sw.js":         lambda: file_resp(SCRIPT_DIR / "sw.js"),
        "/icon-192.png":  lambda: file_resp(SCRIPT_DIR / "icon-192.png"),
        "/icon-512.png":  lambda: file_resp(SCRIPT_DIR / "icon-512.png"),
    }
    if path in static:
        return static[path]()
    if path == "/playstore":
        # Legacy page — not linked from dashboard.html; DabFlow is browser-only (getdabflow.app).
        if PLAYSTORE_FILE.exists():
            return html_resp(PLAYSTORE_FILE.read_text(encoding="utf-8"))
        return _http(404, "text/plain", b"playstore.html not found")
    if path == "/api/phones":
        # Envelope object (not a bare list): the Farm Remote APK parses ``phones``
        # from the JSON body; a top-level array would read as 0 phones there.
        return json_ok({"ok": True, "phones": list_phones()})
    if path == "/api/stealth":
        return json_ok({"ok": True, "phones": _get_stealth_payload(), "updated_utc": time.time()})
    if path == "/api/stealth/verify":
        # Watchdog-facing single-pass uniqueness check. Always returns immediately; the
        # actual multi-phone exit-IP read + rotate runs in a background thread so a slow
        # verification can never block the server. ``last`` carries the most recent result.
        _start_exit_ip_verification_if_idle()
        return json_ok({
            "ok": True,
            "running": _stealth_verify_running,
            "unique_exit_ips": _unique_exit_ips_enabled(),
            "last": dict(_stealth_verify_last) if _stealth_verify_last else {},
        })
    if path == "/api/ip":
        ip = dashboard_reach_host()
        return json_ok(
            {
                "ip": ip,
                "url": f"http://{ip}:{LISTEN_HTTP_PORT}",
                "label": "This PC",
                "httpPort": LISTEN_HTTP_PORT,
                "wsPort": LISTEN_WS_PORT,
            }
        )
    if path == "/api/earn-plan":
        plan = load_earn_plan()
        if not plan:
            return json_ok({"ok": True, "saved": False})
        return json_ok(plan)
    if path == "/api/config":
        cfg = {
            "httpPort": LISTEN_HTTP_PORT,
            "wsPort": LISTEN_WS_PORT,
            "port": LISTEN_HTTP_PORT,
            "bind": LISTEN_HOST,
            "appName": "PharmFlow",
        }
        cfg.update(_desktop_prefs_for_api())
        return json_ok(cfg)
    if path == "/api/apks":
        APK_DIR.mkdir(exist_ok=True)
        files = [{"name": f.name, "size_mb": round(f.stat().st_size / 1024 / 1024, 1)}
                 for f in sorted(APK_DIR.glob("*.apk"))]
        return json_ok(files)
    if path == "/api/recordings":
        return json_ok(teach_mod.list_recordings())
    if path == "/api/resources":
        return json_ok(_get_resources())
    # Dashboard dashboard.html loads groups with GET; POST also accepted in handle_post.
    if path == "/api/groups/load":
        cfg, err = _load_groups_cfg()
        if err:
            return json_err(err)
        return json_ok(cfg)
    if path == "/api/sequences/list":
        # Sequence library for playlist pickers: every *.json under the sequences
        # tree keyed by profile (base resolution, e.g. 900x1600) and flow folder
        # (ad, site, ...). Refs are sequences-root-relative so they survive
        # normalize_playlist_ref / resolve_sequence_file round-trips. Uses the
        # same sequences_dir() source as resolve_sequence_file — never a drift.
        SEQ_ROOT = _sequences_dir()
        global _SEQ_LIST_CACHE
        now_s = time.time()
        if _SEQ_LIST_CACHE and now_s - _SEQ_LIST_CACHE[0] < 60:
            return json_ok(_SEQ_LIST_CACHE[1])
        if not SEQ_ROOT.is_dir():
            return json_ok({"ok": True, "sequences": [], "root": str(SEQ_ROOT)})
        out: list[dict] = []
        try:
            # Names/paths only — no per-file reads (the real tree has thousands
            # of sequences; opening each one made this endpoint time out).
            for p in sorted(SEQ_ROOT.rglob("*.json")):
                if p.name.startswith("_"):
                    continue
                rel = p.relative_to(SEQ_ROOT)
                parts = rel.parts
                if len(parts) < 2:
                    continue
                out.append(
                    {
                        "ref": rel.as_posix(),
                        "name": p.stem,
                        "profile": parts[0],
                        "folder": parts[1] if len(parts) >= 3 else "",
                    }
                )
        except OSError as e:
            return json_err(f"scan failed: {e}")
        payload = {"ok": True, "sequences": out, "root": str(SEQ_ROOT)}
        _SEQ_LIST_CACHE = (now_s, payload)
        return json_ok(payload)
    if path == "/api/groups/adb_errors":
        with _group_adb_errors_lock:
            snap = list(_group_adb_errors)
        return json_ok({"ok": True, "adb_errors": snap})
    if path == "/api/scorecard":
        from scorecard_api import build_scorecard_payload

        payload = build_scorecard_payload(
            list_phones_fn=list_phones,
            recordings_dir=REC_DIR,
            listen_host=dashboard_reach_host(),
            listen_port=LISTEN_HTTP_PORT,
        )
        return json_ok(payload)
    if path == "/api/docker/status":
        dock, derr = _docker_phone_state()
        return json_ok({"ok": not derr, "error": derr or None, "containers": dock})
    if path == "/api/money/status":
        from scorecard_api import build_money_kpis

        payload = build_money_kpis(
            list_phones_fn=list_phones,
            recordings_dir=REC_DIR,
        )
        # Overlay today's REAL dabflow farm traffic so the KPI strip is never
        # flat-zero while the farm actually opens pages (Mantis export arrives
        # separately via POST /api/scorecard/mantis).
        live_visits = _farm_visits_today()
        if live_visits and (not payload.get("farm_visits")):
            payload["farm_visits"] = live_visits
            payload["visits_source"] = "farm_tally"
        return json_ok(payload)
    if path == "/api/money/history":
        from scorecard_api import build_money_history

        return json_ok(
            {"ok": True, "days": build_money_history(REC_DIR, days=45)}
        )
    if path == "/api/groups/status":
        groups: list[dict] = []
        running = _groups_status_running_names()
        try:
            grp_cfg = (json.loads(GROUPS_CFG.read_text()) or {}).get("groups", [])
        except (OSError, json.JSONDecodeError):
            grp_cfg = []
        runs = _get_phone_runs()
        by_key = {(r["group"], r["serial"]): r for r in runs}
        for g in grp_cfg:
            if not isinstance(g, dict):
                continue
            gname = str(g.get("name") or "Group")
            pmap = g.get("phones") or {}
            phones = []
            if isinstance(pmap, dict):
                for serial in pmap:
                    ent = pmap[serial]
                    r = by_key.get((gname, serial)) or {}
                    pname = ent.get("name") if isinstance(ent, dict) else serial
                    phones.append({
                        "serial": serial,
                        "name": pname or serial,
                        "state": r.get("state", "idle"),
                        "iteration": r.get("iteration", 0),
                        "result": r.get("result", ""),
                        "updated_utc": r.get("updated_utc", 0),
                    })
            groups.append({"name": gname, "running": gname in running,
                           "apk": str(g.get("apk") or ""), "phones": phones})
        return json_ok({"groups": groups, "running": running})
    return _http(404, "text/plain", b"Not Found")


async def handle_post(path: str, body: bytes) -> bytes:
    data = {}
    if body:
        try:
            data = json.loads(body)
        except Exception:
            pass

    # ── Scheduler (wizard POSTs here; GET also supported in main handler) ──
    if path.startswith("/api/scheduler"):
        return await handle_scheduler(path, body)

    if path == "/api/scorecard/mantis":
        from scorecard_api import save_operator_mantis_state

        saved = save_operator_mantis_state(REC_DIR, data)
        return json_ok({"ok": True, "saved": saved})

    # ── Persist stealth settings (survive restarts) ──
    if path == "/api/earn-plan":
        body = data if isinstance(data, dict) else {}
        if body.get("preview") is True:
            return json_ok(compute_earn_plan(body))
        return json_ok(save_earn_plan(body))
    if path == "/api/stealth/settings":
        upd = {}
        if isinstance(data.get("rotate_every_sequence"), bool):
            upd["rotate_every_sequence"] = data["rotate_every_sequence"]
        if isinstance(data.get("unique_exit_ips"), bool):
            upd["unique_exit_ips"] = data["unique_exit_ips"]
        if not upd:
            return json_err("no valid settings provided")
        saved = _write_stealth_prefs(**upd)
        if not saved:
            return json_err("Stealth setting was not saved — disk copy does not match.")
        return json_ok({
            "ok": True,
            "saved": True,
            "rotate_every_sequence": _rotate_every_sequence_enabled(),
            "unique_exit_ips": _unique_exit_ips_enabled(),
        })

    # ── Connect / disconnect device ──
    if path == "/api/devices/connect":
        addr = data.get("address", "").strip()
        if not addr:
            return json_err("no address provided")
        if ":" not in addr:
            addr = addr + ":5555"
        # Allow IPv4, localhost, or simple hostnames with a port
        if not re.match(r"^[a-zA-Z0-9._-]+:\d{2,5}$", addr):
            return json_err("invalid address")
        out = _adb_global("connect", addr, timeout=10)
        if not _adb_connect_landed(out.text, out.returncode):
            return json_err((out.text or "").strip() or "could not connect")
        await push_phones()
        return json_ok({"ok": True, "result": out.text, "adb_returncode": out.returncode})

    if path == "/api/devices/disconnect":
        serial = data.get("serial", "").strip()
        if not serial or not re.match(r"^[a-zA-Z0-9._:\-]+$", serial):
            return json_err("invalid serial")
        out = _adb_global("disconnect", serial, timeout=5)
        blob = (out.text or "").lower()
        landed = out.returncode == 0 and "disconnected" in blob and "error" not in blob
        if not landed:
            return json_err((out.text or "").strip() or "could not disconnect")
        await push_phones()
        return json_ok({"ok": True, "disconnected": True, "result": out.text})

    if path == "/api/devices/refresh":
        auto_connect_emulators()
        await push_phones()
        answering = [p for p in list_phones() if p.get("running")]
        if not answering:
            return json_err("No phones are answering ADB. Start the phones, then find them again.")
        return json_ok({"ok": True, "n": len(answering)})

    # ── APK upload ──
    if path == "/api/upload":
        filename = data.get("name", "").strip()
        file_b64 = data.get("data", "")
        if not filename or not file_b64:
            return json_err("missing name or data")
        safe_name = Path(filename).name
        if not re.match(r'^[A-Za-z0-9_\-. ]+\.apk$', safe_name) or not safe_name:
            return json_err("only .apk files with safe names allowed")
        if len(file_b64) > 200_000_000:
            return json_err("file too large")
        APK_DIR.mkdir(exist_ok=True)
        dest = APK_DIR / safe_name
        try:
            raw = base64.b64decode(file_b64)
        except Exception:
            return json_err("invalid base64 data")
        try:
            dest.write_bytes(raw)
            stored = dest.read_bytes()
        except OSError:
            return json_err("APK was not saved — disk copy does not match.")
        if stored != raw:
            return json_err("APK was not saved — disk copy does not match.")
        return json_ok({"ok": True, "saved": True, "name": safe_name, "bytes": len(stored)})

    # ── APK install ──
    if path == "/api/install":
        apk_name = data.get("apk", "").strip()
        if not apk_name:
            return json_err("no apk specified")
        apk_path = (APK_DIR / Path(apk_name).name).resolve()
        if not str(apk_path).startswith(str(APK_DIR.resolve())):
            return json_err("invalid path")
        if not apk_path.exists():
            return json_err("file not found")
        phones = _running_phones_ordered()
        if not phones:
            return json_err("No phones connected — nothing to install. Start the phones, then try again.")

        async def install_all():
            loop = asyncio.get_running_loop()
            for p in phones:
                serial = p["serial"]
                await broadcast({"type": "install_progress",
                                 "serial": serial, "status": "installing"})
                proc = await loop.run_in_executor(
                    None,
                    lambda s=serial, ap=str(apk_path): subprocess.run(
                        [adb_executable(), "-s", s, "install", "-r", ap],
                        capture_output=True,
                        timeout=120,
                        creationflags=_ADB_SUBPROC_FLAGS,
                    )
                )
                text = (
                    (proc.stdout or b"") + b"\n" + (proc.stderr or b"")
                ).decode("utf-8", "replace")
                installed = apk_install_reported(text, "", proc.returncode)
                invalidate_cache(serial)
                if installed:
                    await broadcast({"type": "install_progress",
                                     "serial": serial, "status": "done"})
                else:
                    await broadcast({
                        "type": "install_progress",
                        "serial": serial,
                        "status": "error",
                        "error": (text.strip() or "adb install failed")[-240:],
                    })
            await push_phones()

        asyncio.create_task(install_all())
        return json_ok({"ok": True, "started": True, "n": len(phones)})

    # ── Phone stop (universal) ──
    if path == "/api/phone/stop":
        serial = data.get("serial", "").strip()
        if not serial:
            return json_err("no serial")
        result = await asyncio.get_running_loop().run_in_executor(None, _stop_device_result, serial)
        await push_phones()
        if not result.get("ok"):
            return json_err(str(result.get("note") or "Phone was not stopped"))
        return json_ok({"ok": True, **result})

    # ── Stop all running devices ──
    if path == "/api/stop_all":
        phones = _running_phones_ordered()
        if not phones:
            return json_err("No phones are answering ADB.")

        def stop_all() -> list[dict]:
            return [_stop_device_result(p["serial"]) for p in phones]

        results = await asyncio.get_running_loop().run_in_executor(None, stop_all)
        await push_phones()
        stopped = [r for r in results if r.get("action") in ("killed", "docker_stop")]
        disconnected = [r for r in results if r.get("action") == "disconnected"]
        failed = [r for r in results if not r.get("ok")]
        if not stopped and not disconnected:
            return json_err("No phone was stopped or disconnected.")
        return json_ok({
            "ok": True,
            "stopped": len(stopped),
            "disconnected": len(disconnected),
            "failed": len(failed),
            "results": results,
        })

    # ── Refresh / re-scan ──
    if path == "/api/start_all":
        auto_connect_emulators()
        await push_phones()
        answering = [p for p in list_phones() if p.get("running")]
        if not answering:
            return json_err("No phones are answering ADB. Start the phones, then find them again.")
        return json_ok({"ok": True, "n": len(answering)})

    # ── URL launcher ──
    if path == "/api/open_url":
        url         = _normalize_url_for_intent(data.get("url", ""))
        auto_rotate = bool(data.get("auto_rotate", False))
        try:
            stagger    = max(0, int(data.get("stagger_secs", 0)))
            dwell_secs = max(0, int(data.get("dwell_secs", 30)))
        except (TypeError, ValueError):
            return json_err("stagger_secs and dwell_secs must be integers")
        try:
            _parsed = urllib.parse.urlparse(url)
            if _parsed.scheme not in ("http", "https") or not _parsed.netloc or " " in url:
                raise ValueError
        except Exception:
            return json_err("URL must be a valid http:// or https:// URL")
        phones = _running_phones_ordered()
        target = str(data.get("target") or "all").strip() or "all"
        if target != "all":
            phones = [p for p in phones if p.get("serial") == target]
        if not phones:
            return json_err(
                "No phones are answering ADB. Start the phones, then open the page again."
            )
        loop   = asyncio.get_running_loop()

        def _phones_with_exit() -> list:
            ready = []
            for p in phones:
                ok, note = _dashboard_open_exit_ready(p["serial"])
                if ok:
                    ready.append(p)
                    continue
                asyncio.run_coroutine_threadsafe(
                    broadcast(
                        {
                            "type": "log",
                            "msg": f"{p['name']}: page not opened — {note}",
                        }
                    ),
                    loop,
                )
            return ready

        phones = await asyncio.get_running_loop().run_in_executor(None, _phones_with_exit)
        if not phones:
            return json_err(
                "No phone has a loopback exit, so the page was not opened. "
                "Traffic would leave this PC. Fix phone internet, then try again."
            )

        def _rotate_after(p: dict, delay: int):
            time.sleep(delay)
            idx = _phone_idx_from_serial(p["serial"])
            # Stop the device’s default / resolved browser only — not a fixed package list.
            br = browser_pkg_for_clear(p["serial"], "")
            if br:
                _adb(p["serial"], "shell", "am", "force-stop", br)
            tor_manager.register_tor_slot(p["serial"], idx)
            result = tor_manager.rotate_identity_adb(p["serial"], idx)
            # A new circuit without a pinned loopback exit is not a rotation.
            # The page already opened on the old exit; do not claim the identity changed.
            landed = bool(result.get("circuit_rotated")) and _guest_loopback_pinned(result)
            proxy = str(result.get("http_proxy") or "not pinned")
            if landed:
                msg = f"{p['name']}: identity rotated — new Tor circuit on {proxy}"
            else:
                circuit = "yes" if result.get("circuit_rotated") else "no"
                msg = (
                    f"{p['name']}: identity was not rotated — "
                    f"circuit={circuit} · proxy={proxy}"
                )
            asyncio.run_coroutine_threadsafe(broadcast({"type": "log", "msg": msg}), loop)

        async def open_all():
            for i, p in enumerate(phones):
                if i > 0 and stagger > 0:
                    delay = (
                        _hv.stagger_seconds(float(stagger), _hv.rng_for_run(p["serial"], i))
                        if _hv.enabled()
                        else float(stagger)
                    )
                    await asyncio.sleep(delay)
                # Device-only VIEW intent (never host browser). Generic handler
                # avoids hard dependency on Google Chrome; optional explicit component via
                # open_url step field ``browser_component`` in sequences.
                exit_ok, exit_note = _dashboard_open_exit_ready(p["serial"])
                if not exit_ok:
                    await broadcast(
                        {
                            "type": "log",
                            "msg": (
                                f"{p['name']}: page not opened — {exit_note}"
                            ),
                        }
                    )
                    continue
                _idx_ou = _phone_idx_from_serial(p["serial"])
                _ens_ou = {"ok": True}
                if not _pharmflow_skip_tor_wait():
                    tor_manager.start_tor_warm_background(_idx_ou)
                    _ens_ou = tor_manager.ensure_tor_ready(p["serial"], _idx_ou)
                    if not _ens_ou.get("ok"):
                        log.warning(
                            "open_url API: Tor/proxy not ready serial=%s (%s)",
                            p["serial"],
                            _ens_ou.get("error", "unknown"),
                        )
                _tor_block = _dead_tor_http_reason(_idx_ou, exit_note, _ens_ou)
                if _tor_block:
                    await broadcast(
                        {
                            "type": "log",
                            "msg": (
                                f"{p['name']}: page not opened — Tor HTTP exit is not ready "
                                f"({_tor_block[:120]})"
                            ),
                        }
                    )
                    continue
                res = _open_url_with_fallbacks(p["serial"], url, {})
                res = _retry_open_url_action_view_for_browser_net_error(p["serial"], url, res)
                opened = am_start_reported_landing(res.stdout, res.stderr)
                if opened:
                    # Same follow-through as ``run_sequence_step`` ``open_url`` (PID wait + settle).
                    _wait_for_browser_pid_after_open(p["serial"], {})
                    try:
                        _api_settle = _open_url_settle_after_pid({})
                        if _api_settle > 0:
                            time.sleep(_api_settle)
                    except (TypeError, ValueError):
                        pass
                    await broadcast(
                        {"type": "log", "msg": _open_url_result_log(p["name"], url, opened=True)}
                    )
                else:
                    await broadcast(
                        {
                            "type": "log",
                            "msg": _open_url_result_log(
                                p["name"], url, opened=False, note=res.text[:220]
                            ),
                        }
                    )
                if opened and auto_rotate:
                    threading.Thread(
                        target=_rotate_after, args=(p, dwell_secs), daemon=True
                    ).start()

        asyncio.create_task(open_all())
        return json_ok({
            "ok": True,
            "queued": True,
            "started": False,
            "n": len(phones),
            "targeted": len(phones),
        })

    # ── Teach mode ──
    if path == "/api/teach/start":
        phones = _running_phones_ordered()
        if not phones:
            return json_err("no phones running")
        first_serial = phones[0]["serial"]
        rec_file = teach_mod.start_recording(first_serial)
        if not rec_file:
            _teach_state["state"] = "idle"
            _teach_state["file"] = ""
            await broadcast({"type": "teach_status", **_teach_state})
            return json_err("Recording did not start — getevent is not running on that phone.")
        _teach_state["state"] = "recording"
        _teach_state["serial"] = first_serial
        _teach_state["file"] = rec_file
        await broadcast({"type": "teach_status", **_teach_state})
        return json_ok({"ok": True, "recording": True, "file": rec_file})

    if path == "/api/teach/stop":
        rec_file = teach_mod.stop_recording()
        events = teach_mod.recording_event_count(rec_file)
        _teach_state["state"] = "idle"
        if events < 1:
            _teach_state["file"] = ""
            await broadcast({"type": "teach_status", **_teach_state})
            return json_err("No taps were captured.")
        _teach_state["file"] = rec_file
        await broadcast({"type": "teach_status", **_teach_state})
        return json_ok({"ok": True, "file": rec_file, "events": events})

    if path == "/api/teach/play":
        rec = data.get("file") or _teach_state.get("file")
        try:
            delay = max(0, int(data.get("delay_secs", 60)))
        except (TypeError, ValueError):
            delay = 60
        if not rec:
            return json_err("no recording found")
        events = teach_mod.recording_event_count(rec)
        if events < 1:
            return json_err("No taps were captured in that recording.")
        try:
            rec_resolved = Path(rec).resolve()
            if not str(rec_resolved).startswith(str(REC_DIR.resolve())):
                return json_err("invalid recording path")
        except Exception:
            return json_err("invalid recording path")
        source_serial = _teach_state.get("serial", "")
        phones = [p for p in _running_phones_ordered() if p["serial"] != source_serial]
        if not phones:
            return json_err(
                "No other phone is answering. Boot another phone, then play the recording."
            )
        _teach_state["state"] = "playing"
        await broadcast({"type": "teach_status", **_teach_state})
        loop = asyncio.get_running_loop()

        def on_done(sent: int = 0):
            _teach_state["state"] = "idle"
            asyncio.run_coroutine_threadsafe(broadcast({"type": "teach_status", **_teach_state}), loop)
            if sent < 1:
                msg = "Teach playback finished — no event landed."
            else:
                msg = (
                    f"Teach playback sent {sent} event(s) — the phone screen was not confirmed."
                )
            asyncio.run_coroutine_threadsafe(
                broadcast({"type": "log", "msg": msg}),
                loop,
            )

        teach_mod.replay_all(phones, rec, delay_secs=delay, on_complete=on_done)
        return json_ok({"ok": True, "started": True, "n": len(phones), "events": events})

    # ── Tor / identity ──
    if path == "/api/proxy/setup":
        phones = _running_phones_ordered()
        loop   = asyncio.get_running_loop()

        if not phones:
            return json_err("No phones are answering ADB. Start the phones, then set up Tor.")

        pre = tor_manager.tor_proxy_preflight()
        if not pre.get("ok"):
            return json_err(pre.get("error", "Tor unavailable — install Tor or start Tor Browser"))

        def setup() -> int:
            pinned = 0
            tor_manager.clear_tor_slots()
            try:
                for p in phones:
                    # Prefs / guest slot, not "nth phone that answered". A gap
                    # must not pin a later phone onto someone else's exit.
                    idx = _phone_idx_from_serial(p["serial"])
                    tor_manager.register_tor_slot(p["serial"], idx)
                    try:
                        tor_manager.start_tor_for_phone(idx)
                    except (FileNotFoundError, RuntimeError) as e:
                        msg = f"{p['name']}: Tor could not start — {e}"
                        asyncio.run_coroutine_threadsafe(
                            broadcast({"type": "log", "msg": msg}), loop
                        )
                        continue
                    w_socks = tor_manager.tor_wait_socks_seconds()
                    w_http = tor_manager.tor_wait_http_seconds()
                    ok_socks = tor_manager.wait_for_tor(idx, timeout=w_socks)
                    ok_http = tor_manager.wait_for_tor_http_tunnel(idx, timeout=w_http)
                    applied = tor_manager.apply_identity_adb(p["serial"], idx)
                    landed = ok_socks and ok_http and _guest_loopback_pinned(applied)
                    if landed:
                        pinned += 1
                    msg = _tor_setup_line(
                        str(p.get("name") or p["serial"]),
                        ok_socks=ok_socks,
                        ok_http=ok_http,
                        pinned=_guest_loopback_pinned(applied),
                        w_socks=w_socks,
                        w_http=w_http,
                    )
                    asyncio.run_coroutine_threadsafe(broadcast({"type": "log", "msg": msg}), loop)
                if pinned == len(phones) and pinned:
                    done = f"Tor setup finished — {pinned} phone(s) have a loopback exit."
                elif pinned:
                    done = (
                        f"Tor setup incomplete — {pinned} of {len(phones)} phone(s) "
                        "have a loopback exit. The rest were not pinned."
                    )
                else:
                    done = "Tor setup failed — no phone got a loopback exit."
                asyncio.run_coroutine_threadsafe(
                    broadcast({"type": "log", "msg": done}), loop
                )
            except Exception as e:
                asyncio.run_coroutine_threadsafe(
                    broadcast({"type": "log", "msg": f"Tor setup error: {e}"}), loop
                )
            return pinned

        pinned = await asyncio.get_running_loop().run_in_executor(None, setup)
        if pinned < 1:
            return json_err("No phone got a loopback exit. Read the log.")
        return json_ok({"ok": True, "n": pinned, "targeted": len(phones), "tor_preflight": pre})

    if path == "/api/proxy/rotate":
        phones = _running_phones_ordered()
        if not phones:
            return json_err("No phones connected — nothing to rotate. Start the phones, then try again.")
        loop   = asyncio.get_running_loop()

        def rotate_all():
            pinned = 0
            for p in phones:
                idx = _phone_idx_from_serial(p["serial"])
                tor_manager.register_tor_slot(p["serial"], idx)
                try:
                    result = tor_manager.rotate_identity_adb(p["serial"], idx)
                except Exception as exc:
                    msg = f"{p['name']}: rotate failed — {exc}"
                    asyncio.run_coroutine_threadsafe(broadcast({"type": "log", "msg": msg}), loop)
                    continue
                landed = bool(result.get("circuit_rotated")) and _guest_loopback_pinned(result)
                if landed:
                    pinned += 1
                    msg = f"{p['name']}: rotated · exit={result.get('http_proxy')}"
                else:
                    msg = (
                        f"{p['name']}: rotate failed · "
                        f"circuit={'yes' if result.get('circuit_rotated') else 'no'} · "
                        f"proxy={result.get('http_proxy') or 'not pinned'}"
                    )
                asyncio.run_coroutine_threadsafe(broadcast({"type": "log", "msg": msg}), loop)
            if pinned == len(phones):
                done = f"Rotated {pinned} phone(s) onto a new exit."
            elif pinned:
                done = (
                    f"Rotated {pinned} of {len(phones)} phone(s). "
                    "The rest did not get a new loopback exit."
                )
            else:
                done = "No phone got a new identity. Exits were not changed."
            asyncio.run_coroutine_threadsafe(broadcast({"type": "log", "msg": done}), loop)
            return pinned

        pinned = await asyncio.get_running_loop().run_in_executor(None, rotate_all)
        if pinned < 1:
            return json_err("No phone got a new exit.")
        return json_ok({"ok": True, "n": pinned, "targeted": len(phones)})

    if path == "/api/proxy/teardown":
        # Run ADB + Tor cleanup off the asyncio loop so WS / other POST handlers stay responsive.
        loop = asyncio.get_running_loop()

        def _proxy_teardown_sync() -> tuple[list[str], str, int, bool]:
            # This route used to delete guest http_proxy and stop Tor. That
            # sends farm traffic out the VM/host path. Re-pin the live exits.
            from automation.farm_exe_self_heal import (
                adb_live_serials,
                connect_live_fleet,
                heal_inject_and_tor,
            )

            notes: list[str] = []
            try:
                notes.extend(connect_live_fleet() or [])
            except Exception as exc:
                notes.append(f"connect_failed:{exc}")
            phones = [str(s) for s in (adb_live_serials() or []) if str(s).strip()]
            try:
                notes.extend(heal_inject_and_tor(live=phones) or [])
            except Exception as exc:
                return phones, f"Re-pin failed: {exc}", 0, False
            failed = [
                n
                for n in notes
                if "repin_fail" in n or n.startswith("inject_start_err") or n.startswith("connect_failed")
            ]
            pinned = [n for n in notes if n.startswith("repin ") and "repin_fail" not in n]
            if not phones:
                return (
                    phones,
                    "No phones connected — nothing to re-pin. Start the phones, then try again.",
                    0,
                    False,
                )
            if failed or len(pinned) < len(phones):
                detail = "; ".join(failed or ["no loopback pin landed"])[:400]
                return phones, f"Re-pin failed: {detail}", len(pinned), False
            msg = (
                f"Re-pinned {len(pinned)} phone(s) onto their own exits. "
                "Proxies were not cleared."
            )
            return phones, msg, len(pinned), True

        phones, msg, n, pinned_ok = await loop.run_in_executor(_executor, _proxy_teardown_sync)
        await broadcast({"type": "log", "msg": msg})
        if not pinned_ok:
            return json_err(msg)
        return json_ok({
            "ok": True,
            "message": msg,
            "cleared_serials": phones,
            "n": n,
            "repinned": True,
        })

    # ── Groups: run different sequences on different phone sets in parallel ──

    # ── Full identity reset (new IP + new Android ID + new MAC) ──
    if path == "/api/identity/reset":
        serial = data.get("serial", "").strip()
        if not serial:
            return json_err("no serial")
        idx = _phone_idx_from_serial(serial)
        loop = asyncio.get_running_loop()

        def do_reset():
            try:
                return tor_manager.full_identity_reset(serial, idx)
            except Exception as exc:
                return {"tor_circuit_rotated": False, "error": str(exc)}

        result = await loop.run_in_executor(None, do_reset)
        msg = _identity_reset_log(serial, result)
        await broadcast({"type": "log", "msg": msg})
        if not _identity_reset_landed(result):
            return json_err(msg)
        return json_ok({"ok": True, "rotated": True, "message": msg})

    # ── Reset all running phones ──
    if path == "/api/identity/reset_all":
        phones = _running_phones_ordered()
        loop = asyncio.get_running_loop()
        if not phones:
            return json_err("No phones connected — nothing to reset. Start the phones, then try again.")

        def do_reset_all() -> int:
            rotated = 0
            for p in phones:
                idx = _phone_idx_from_serial(p["serial"])
                try:
                    result = tor_manager.full_identity_reset(p["serial"], idx)
                except Exception as exc:
                    asyncio.run_coroutine_threadsafe(
                        broadcast({"type": "log", "msg": f"{p['name']}: identity reset failed — {exc}"}),
                        loop,
                    )
                    continue
                if _identity_reset_landed(result):
                    rotated += 1
                asyncio.run_coroutine_threadsafe(
                    broadcast({"type": "log", "msg": _identity_reset_log(p["name"], result)}),
                    loop,
                )
            return rotated

        rotated = await loop.run_in_executor(None, do_reset_all)
        if rotated < 1:
            return json_err("No phone got a new Tor circuit on a pinned loopback exit.")
        return json_ok({"ok": True, "n": rotated, "targeted": len(phones)})

    if path == "/api/groups/run":
        raw_groups = data.get("groups")
        if isinstance(raw_groups, list):
            raw_groups = _normalize_groups_payload(raw_groups)
        if not raw_groups:
            if GROUPS_CFG.exists():
                try:
                    raw_groups = _normalize_groups_payload(
                        json.loads(GROUPS_CFG.read_text()).get("groups", [])
                    )
                except (json.JSONDecodeError, OSError):
                    return json_err("corrupt groups_config.json")
        if not raw_groups:
            return json_err("no groups provided and no saved groups_config.json found")

        all_phones = {p["serial"]: p for p in list_phones() if p["running"]}
        online_serials = set(all_phones.keys())
        # Emulator serials churn on every reboot — auto-remap saved slots onto the
        # live phones (by farm slot) instead of refusing to run.
        remap = _remap_group_serials_to_live(raw_groups, online_serials)
        if remap.get("remapped"):
            if remap.get("saved"):
                remap_msg = (
                    f"[PharmFlow] Auto-remapped groups to live phones ({len(online_serials)} online)"
                )
            else:
                remap_msg = (
                    "[PharmFlow] Remapped groups in memory only — disk copy does not match "
                    f"({len(online_serials)} online)"
                )
            log.info(remap_msg)
            asyncio.get_running_loop().call_soon_threadsafe(
                lambda msg=remap_msg: asyncio.ensure_future(
                    broadcast({"type": "log", "msg": msg}),
                )
            )
        configured_serials: set[str] = set()
        for g in raw_groups:
            for s in (g.get("phones") or {}):
                if isinstance(s, str) and s.strip():
                    configured_serials.add(s.strip())
        if not configured_serials:
            return json_err("no phones assigned in any group")
        if not (configured_serials & online_serials):
            return json_err(
                "no group phone serials match running ADB devices — "
                f"running_adb_serials={sorted(online_serials)} "
                f"group_config_serials={sorted(configured_serials)}"
            )
        phones_targeted = len(configured_serials & online_serials)
        total_runnable_steps = _total_steps_for_groups_online(raw_groups, online_serials)
        if total_runnable_steps == 0:
            return json_err(
                "no runnable automation steps: each online phone in these groups has an empty per-phone "
                "step list and there are no legacy group-level steps. Add steps in the dashboard or wizard."
            )

        loop = asyncio.get_running_loop()
        with _group_adb_errors_lock:
            _group_adb_errors.clear()
        _running_groups.clear()
        _group_skip_serials.clear()
        for g in raw_groups:
            if isinstance(g, dict):
                gn = str(g.get("name") or "Group")
                _running_groups[gn] = True

        # Tor bootstrap + http_proxy can take minutes per phone; run off the HTTP handler
        # so wizard/dashboard clients get an immediate JSON response (see _start_groups_pipeline).
        if not _pharmflow_skip_tor_wait():
            tor_pf = tor_manager.tor_proxy_preflight()
            if not tor_pf.get("ok"):
                _running_groups.clear()
                return json_err(
                    tor_pf.get(
                        "error",
                        "Tor unavailable on this PC — install tor.exe / Tor Browser, or set "
                        "PHARMFLOW_SKIP_TOR_WAIT=1 to run groups without Tor.",
                    )
                )

        def _run_steps_adb(steps: list, serial: str, group_name: str, iteration: int) -> str:
            ic = lambda: _running_groups.get(group_name, True)
            cycle = iteration * 1_000_003 + (_hv.stable_seed(serial, 0) & 0xFFFFF)
            rng = _hv.rng_for_run(serial, cycle) if _hv.enabled() else None

            def _adb_issue_cb(tag: str, res: AdbResult) -> None:
                _record_group_adb_error(group_name, serial, tag, res)
                msg = (
                    f"[{group_name}] Phone link problem ({tag}) on {serial} — "
                    f"{res.text[:400]}"
                )
                asyncio.run_coroutine_threadsafe(broadcast({"type": "log", "msg": msg}), loop)

            for step in steps:
                if not ic():
                    return "stopped"
                landed = run_sequence_step(
                    serial,
                    step,
                    interrupt_check=ic,
                    hv_rng=rng,
                    adb_issue_cb=_adb_issue_cb,
                )
                if not ic():
                    return "stopped"
                if landed is False:
                    kind = str(step.get("type") or "step")
                    asyncio.run_coroutine_threadsafe(
                        broadcast({
                            "type": "log",
                            "msg": f"[{group_name}] {kind} did not land on {serial} — sequence stopped",
                        }),
                        loop,
                    )
                    return f"{kind} did not land"
                if step_is_fast_phase(step):
                    time.sleep(0.05)
                elif step.get("phase") == "on_site_human":
                    time.sleep(rng.uniform(0.05, 0.12) if rng is not None else 0.08)
                elif rng is not None:
                    time.sleep(_hv.step_gap_seconds(rng))
                else:
                    time.sleep(0.3)
            return ""

        def _effective_group_repeat(group: dict, repeat: int, forever: bool) -> int:
            """Ensure ordered/random playlists run every file at least once per group run."""
            if forever:
                return repeat
            pl_min = 1
            pmap = group.get("phones") or {}
            if isinstance(pmap, dict):
                for ent in pmap.values():
                    if isinstance(ent, dict):
                        pl_min = max(pl_min, playlist_cycle_length(ent))
            effective = max(repeat, pl_min)
            if effective > repeat:
                asyncio.run_coroutine_threadsafe(
                    broadcast(
                        {
                            "type": "log",
                            "msg": (
                                f"[{group.get('name', 'Group')}] Playlist has {pl_min} slot(s) — "
                                f"running {effective} iteration(s) (repeat was {repeat})"
                            ),
                        }
                    ),
                    loop,
                )
            return effective

        def _run_group(group: dict):
            name    = group.get("name", "Group")
            phone_map = group.get("phones", {})   # {serial: {steps:[...]}}
            base_serials = _online_serials_for_group(group, set(all_phones.keys()))
            # Always bind serials — previously only set inside `if _group_skip_serials`,
            # so the happy path (empty skip set) raised NameError before any phone ran.
            serials = [s for s in base_serials if s not in _group_skip_serials]

            def _retry_skipped_async() -> None:
                """Re-check skipped phones in the background; rejoin them when ready.

                A phone skipped at preflight (slow Tor bootstrap, ADB settling) would
                otherwise stay idle for the WHOLE `repeat_forever` run. Probe each
                skipped serial once; on success remove it from the skip set so the
                next iteration picks it up. Runs off the group thread so a slow
                probe never stalls the phones that are already working.
                """
                if not _group_skip_serials:
                    return
                for s in list(_group_skip_serials):
                    if s not in base_serials:
                        continue
                    if not _running_groups.get(name):
                        return
                    try:
                        idx = _phone_idx_from_serial(s)
                        ens = tor_manager.ensure_tor_and_proxy_for_phone(s, idx)
                    except Exception:
                        continue
                    if ens and ens.get("ok"):
                        _group_skip_serials.discard(s)
                        msg = f"[{name}] {s} Tor recovered — rejoining the farm ✓"
                        log.info(msg)
                        asyncio.run_coroutine_threadsafe(
                            broadcast({"type": "log", "msg": msg}), loop)

            try:
                repeat  = int(group.get("repeat", 1))
            except (TypeError, ValueError):
                repeat = 1
            rv      = group.get("repeat_forever", False)
            forever = rv if isinstance(rv, bool) else str(rv).lower() == "true"
            repeat = _effective_group_repeat(group, repeat, forever)

            try:
                asyncio.run_coroutine_threadsafe(
                    broadcast({"type": "log", "msg": f"[{name}] Starting on {len(serials)} phone(s)"}),
                    loop)
                if not serials:
                    asyncio.run_coroutine_threadsafe(
                        broadcast({
                            "type": "log",
                            "msg": f"[{name}] No running phone matched this group — check Boot / Start all phones",
                        }),
                        loop,
                    )

                def _run_one_phone(serial, iteration):
                    if not _running_groups.get(name):
                        return
                    try:
                        phone_name = all_phones[serial]["name"]
                        pmap = group.get("phones") or {}
                        ent = _phone_entry_for_serial(pmap, serial) or {}
                        _set_phone_run(name, serial, state="running", iteration=iteration, result="")
                        inline = _inline_steps_fallback(group, ent)
                        _install_group_apk_once(group, serial, name, iteration, loop)
                        chunks = resolve_step_chunks(ent, iteration, serial, inline)
                        if not chunks:
                            phone_steps, pl_from = _phone_steps_for_run(group, serial, iteration)
                            chunks = [(phone_steps, pl_from)]
                        cycle = iteration * 1_000_003 + (_hv.stable_seed(serial, 0) & 0xFFFFF)
                        gap_rng = _hv.rng_for_run(serial, cycle + 77)
                        ran_any = False
                        step_fail = ""
                        rotate_every = _rotate_every_sequence_enabled()
                        for ci, (phone_steps, pl_from) in enumerate(chunks):
                            if not _running_groups.get(name):
                                step_fail = step_fail or "stopped"
                                break
                            if ci > 0:
                                gap = _hv.sequence_start_gap_seconds(gap_rng)
                                _interruptible_sleep(gap, lambda: _running_groups.get(name, False))
                            pl_note = f" playlist={pl_from}" if pl_from else ""
                            asyncio.run_coroutine_threadsafe(
                                broadcast({"type": "log",
                                               "msg": f"[{name}] Run {iteration+1} on {phone_name} "
                                               f"({len(phone_steps)} steps){pl_note}"}), loop)
                            step_fail = _run_steps_adb(phone_steps, serial, name, iteration)
                            if step_fail:
                                break
                            ran_any = ran_any or bool(phone_steps)
                            # Rotate fingerprint/proxy/Tor/IMEI after EVERY sequence so a
                            # fresh identity drives each run (not just playlist-cycle end).
                            if ran_any and rotate_every and not step_fail:
                                idx = _phone_idx_from_serial(serial)
                                asyncio.run_coroutine_threadsafe(
                                    broadcast({"type": "log",
                                               "msg": f"[{name}] New identity on {phone_name}…"}), loop)
                                result = tor_manager.full_identity_reset(serial, idx)
                                if _identity_reset_landed(result):
                                    _bump_phone_rotation(serial)
                                asyncio.run_coroutine_threadsafe(
                                    broadcast({"type": "log",
                                               "msg": _identity_reset_log(f"[{name}] {phone_name}", result)}), loop)
                        at_cycle_end = (
                            not isinstance(ent, dict)
                            or is_playlist_cycle_end(ent, iteration)
                        )
                        if ran_any and at_cycle_end and not rotate_every and not step_fail:
                            idx = _phone_idx_from_serial(serial)
                            asyncio.run_coroutine_threadsafe(
                                broadcast({"type": "log",
                                           "msg": f"[{name}] New identity on {phone_name}…"}), loop)
                            result = tor_manager.full_identity_reset(serial, idx)
                            if _identity_reset_landed(result):
                                _bump_phone_rotation(serial)
                            asyncio.run_coroutine_threadsafe(
                                broadcast({"type": "log",
                                           "msg": _identity_reset_log(f"[{name}] {phone_name}", result)}), loop)
                        if step_fail == "stopped":
                            _set_phone_run(name, serial, state="stopped", iteration=iteration, result="stopped")
                        elif step_fail:
                            _set_phone_run(name, serial, state="error", iteration=iteration, result=step_fail)
                        else:
                            _set_phone_run(name, serial, state="done", iteration=iteration, result="completed")
                    except Exception as e:
                        log.exception("group run failed serial=%s", serial)
                        _set_phone_run(name, serial, state="error", iteration=iteration, result=str(e))
                        asyncio.run_coroutine_threadsafe(
                            broadcast({"type": "log",
                                       "msg": f"[{name}] ERROR on {serial}: {e!s}"}),
                            loop,
                        )

                iteration = 0
                while _running_groups.get(name) and (forever or iteration < repeat):
                    # Forever mode: phones skipped at preflight may have recovered
                    # (Tor bootstrap finished, ADB settled) — let them rejoin.
                    if forever and _group_skip_serials and iteration > 0:
                        threading.Thread(
                            target=_retry_skipped_async, daemon=True).start()
                    # Emulators churn IPs constantly (reboots reassign 10.0.2.x).
                    # Re-sync to LIVE ADB every iteration so dropped phones are
                    # swapped for their replacements instead of going stale — the
                    # farm follows the phones, never a frozen serial list.
                    live_now = {p["serial"] for p in list_phones() if p["running"]}
                    if base_serials and live_now:
                        serials = [
                            s for s in base_serials
                            if s in live_now and s not in _group_skip_serials
                        ]
                        # Pick up emulator IP churn: if a configured slot's serial
                        # vanished, re-map that slot onto a live replacement.
                        missing = [s for s in base_serials if s not in live_now]
                        if missing:
                            extras = sorted(
                                (s for s in live_now if s not in base_serials),
                                key=_slot_sort_key,
                            )
                            if extras:
                                for i, old_s in enumerate(missing):
                                    if i < len(extras):
                                        serials.append(extras[i])
                                        log.info(
                                            "[%s] slot churn: %s → %s (live ADB re-sync)",
                                            name, old_s, extras[i],
                                        )
                    if iteration > 0:
                        pause_rng = _hv.rng_for_run(name, iteration * 1_003)
                        pause = _iteration_start_pause_seconds(group, iteration, pause_rng)
                        if pause > 0:
                            _interruptible_sleep(pause, lambda: _running_groups.get(name, False))
                    threads = []
                    for i, serial in enumerate(serials):
                        if not _running_groups.get(name):
                            break
                        if i > 0:
                            eff = _hv.group_stagger_seconds(
                                group, _hv.rng_for_run(serial, iteration * 10_000 + i)
                            )
                            if eff > 0:
                                _interruptible_sleep(eff, lambda: _running_groups.get(name, False))
                        t = threading.Thread(
                            target=_run_one_phone, args=(serial, iteration), daemon=True)
                        t.start()
                        threads.append(t)
                    for t in threads:
                        # A 300s cutoff started the next pass while a long wait
                        # was still running. Wait until the phone finishes, or
                        # until the operator stops the group.
                        while t.is_alive() and _running_groups.get(name):
                            t.join(timeout=0.5)
                    if not _running_groups.get(name):
                        break
                    # Every-sequence rotation churns exit IPs — re-verify uniqueness
                    # after each iteration so two phones can never share an IP for long.
                    if not _pharmflow_skip_tor_wait() and len(serials) > 1 and _unique_exit_ips_enabled():
                        uniq = tor_manager.ensure_unique_exit_ips(
                            serials, max_attempts=3, timeout=10.0
                        )
                        log.info(
                            "[%s] post-iteration unique exit IPs: unique=%s rotations=%s",
                            name, uniq.get("unique"), uniq.get("rotations"),
                        )
                        if uniq.get("rotations"):
                            asyncio.run_coroutine_threadsafe(
                                broadcast(
                                    {
                                        "type": "log",
                                        "msg": (
                                            f"[{name}] Rotated {uniq['rotations']} phone(s) to keep "
                                            "unique exit IPs"
                                        ),
                                    }
                                ),
                                loop,
                            )
                    iteration += 1

                asyncio.run_coroutine_threadsafe(
                    broadcast({"type": "log", "msg": _group_finish_log(name)}), loop)
            finally:
                # Always clear running flag — uncaught errors previously left the
                # group stuck as "running" forever in status / WebSocket panels.
                _running_groups.pop(name, None)
                asyncio.run_coroutine_threadsafe(
                    broadcast({"type": "groups_status", "running": _groups_status_running_names()}), loop)

        def _start_groups_pipeline() -> None:
            try:
                if not _pharmflow_skip_tor_wait():
                    asyncio.run_coroutine_threadsafe(
                        broadcast(
                            {
                                "type": "log",
                                "msg": "Waiting for Tor to start (first time can take a few minutes)…",
                            }
                        ),
                        loop,
                    )
                    tor_manager.clear_tor_slots()
                    _group_serials = tor_manager.order_adb_serials_by_desktop_prefs(configured_serials & online_serials)
                    for _ser in _group_serials:
                        tor_manager.register_tor_slot(_ser, _phone_idx_from_serial(_ser))
                    for serial in _group_serials:
                        if not any(_running_groups.values()):
                            return
                        idx = _phone_idx_from_serial(serial)
                        tor_manager.start_tor_warm_background(idx)
                        ens = tor_manager.ensure_tor_and_proxy_for_phone(serial, idx)
                        if not ens.get("ok"):
                            # One phone's Tor failing must NOT kill the whole farm —
                            # skip it, run the phones that are ready, and report.
                            # (A single slow/offline slot used to abort everything.)
                            _group_skip_serials.add(serial)
                            msg = (
                                f"Skipped: {serial} — Tor not ready "
                                f"({ens.get('error', 'unknown')}). Running other phones; "
                                "this one stays idle this pass."
                            )
                            asyncio.run_coroutine_threadsafe(
                                broadcast({"type": "log", "msg": msg}), loop
                            )
                            continue
                        note_adb_serial_tor_settled(serial)
                        if ensure_adb_serial_ready(serial):
                            _adb_debug("group preflight OK after Tor serial=%s", serial)
                        else:
                            log.warning(
                                "group start: adb shell preflight failed after Tor serial=%s — "
                                "steps may skip until bridge recovers (see PHARMFLOW_ADB_DEBUG=1)",
                                serial,
                            )
                    asyncio.run_coroutine_threadsafe(
                        broadcast(
                            {
                                "type": "log",
                                "msg": "Tor is ready — starting group runs.",
                            }
                        ),
                        loop,
                    )
                    if not _pharmflow_skip_tor_wait():
                        _group_serials_all = tor_manager.order_adb_serials_by_desktop_prefs(
                            configured_serials & online_serials
                        )
                        if len(_group_serials_all) > 1 and _unique_exit_ips_enabled():
                            log.info("Checking unique exit IPs across %s phone(s)…", len(_group_serials_all))
                            asyncio.run_coroutine_threadsafe(
                                broadcast(
                                    {
                                        "type": "log",
                                        "msg": "Checking unique exit IPs across phones…",
                                    }
                                ),
                                loop,
                            )
                            uniq = tor_manager.ensure_unique_exit_ips(
                                _group_serials_all, max_attempts=4, timeout=12.0
                            )
                            confirmed = sum(1 for v in uniq.get("ips", {}).values() if v)
                            log.info(
                                "unique exit IPs: confirmed=%s/%s unique=%s rotations=%s",
                                confirmed, len(_group_serials_all), uniq.get("unique"), uniq.get("rotations"),
                            )
                            if uniq.get("rotations"):
                                asyncio.run_coroutine_threadsafe(
                                    broadcast(
                                        {
                                            "type": "log",
                                            "msg": (
                                                f"Rotated {uniq['rotations']} phone(s) to unique exit IPs "
                                                f"({confirmed}/{len(_group_serials_all)} confirmed)"
                                            ),
                                        }
                                    ),
                                    loop,
                                )
                            if not uniq.get("unique"):
                                log.warning("could not confirm all phones on unique exit IPs")
                                asyncio.run_coroutine_threadsafe(
                                    broadcast(
                                        {
                                            "type": "log",
                                            "msg": (
                                                "WARNING: could not confirm all phones on unique exit IPs "
                                                "— rerunning uniqueness check during the run."
                                            ),
                                        }
                                    ),
                                    loop,
                                )
                for group in raw_groups:
                    if not any(_running_groups.values()):
                        break
                    _executor.submit(_run_group, group)
            except Exception:
                log.exception("group start pipeline failed")
                for k in list(_running_groups.keys()):
                    _running_groups[k] = False
                asyncio.run_coroutine_threadsafe(
                    broadcast(
                        {
                            "type": "log",
                            "msg": "Group start failed — see dashboard log on this PC",
                        }
                    ),
                    loop,
                )
                asyncio.run_coroutine_threadsafe(
                    broadcast(
                        {"type": "groups_status", "running": _groups_status_running_names()}
                    ),
                    loop,
                )

        _executor.submit(_start_groups_pipeline)

        await broadcast({"type": "groups_status", "running": _groups_status_running_names()})
        run_plan = [
            {"name": g.get("name"), "serials_matched": _online_serials_for_group(g, online_serials)}
            for g in raw_groups
            if isinstance(g, dict)
        ]
        with _group_adb_errors_lock:
            err_snapshot = list(_group_adb_errors)
        return json_ok(
            {
                "ok": True,
                "groups": len(raw_groups),
                "phones_targeted": phones_targeted,
                "serials_online": sorted(online_serials),
                "group_run_plan": run_plan,
                "adb_errors": err_snapshot,
                "adb_errors_note": (
                    "Populated during the run when ADB reports failure (check dashboard log). "
                    "GET /api/groups/adb_errors returns the rolling buffer."
                ),
                "accepted": True,
                "tor_preflight_async": not _pharmflow_skip_tor_wait(),
                "start_note": (
                    "Starting groups — watch the Activity Log. This does not mean they finished."
                ),
            }
        )

    if path == "/api/groups/stop":
        name = str(data.get("name") or "").strip()
        if name:
            if not _running_groups.get(name):
                return json_err(f"Group {name} is not running.")
            _running_groups[name] = False
            await broadcast({"type": "log", "msg": f"Stopping group: {name}"})
            stopping = 1
        else:
            running = [k for k, v in _running_groups.items() if v]
            if not running:
                return json_err("No groups are running.")
            for k in running:
                _running_groups[k] = False
            await broadcast({"type": "log", "msg": f"Stopping {len(running)} group(s)."})
            stopping = len(running)
        await broadcast({"type": "groups_status", "running": _groups_status_running_names()})
        return json_ok({"ok": True, "stopping": stopping})


    # ── Clone master steps to all phones in a group ──
    if path == "/api/groups/clone":
        group_name = data.get("name", "").strip()
        source_serial = data.get("source_serial", "").strip()
        if not GROUPS_CFG.exists():
            return json_err("no saved groups_config.json found")
        try:
            cfg = json.loads(GROUPS_CFG.read_text())
        except (json.JSONDecodeError, OSError):
            return json_err("corrupt groups_config.json")
        groups = cfg.get("groups", [])
        target = None
        for g in groups:
            if g.get("name") == group_name:
                target = g
                break
        if not target:
            return json_err(f"group '{group_name}' not found")
        source_steps = []
        phone_map = target.get("phones", {})
        if source_serial and source_serial in phone_map:
            source_steps = (phone_map[source_serial] or {}).get("steps", [])
        elif isinstance(target.get("steps"), list) and target["steps"]:
            # Legacy: shared steps (backwards compat)
            source_steps = target["steps"]
        if not source_steps:
            return json_err("no source steps found to clone")
        # Clone to all phones in the group (preserve per-phone hits_per_day if present)
        for serial in phone_map:
            if isinstance(phone_map[serial], dict):
                prev_hits = phone_map[serial].get("hits_per_day")
                phone_map[serial]["steps"] = list(source_steps)
                if prev_hits is not None:
                    try:
                        phone_map[serial]["hits_per_day"] = max(0, int(prev_hits))
                    except (TypeError, ValueError):
                        phone_map[serial]["hits_per_day"] = DEFAULT_HITS_PER_DAY
                else:
                    phone_map[serial]["hits_per_day"] = DEFAULT_HITS_PER_DAY
            else:
                phone_map[serial] = {
                    "steps": list(source_steps),
                    "hits_per_day": DEFAULT_HITS_PER_DAY,
                }
        if not _persist_groups_cfg(cfg):
            return json_err("Cloned steps were not saved — disk copy does not match.")
        return json_ok({
            "ok": True,
            "saved": True,
            "cloned": len(phone_map),
            "steps_count": len(source_steps),
        })

    # ── Get/Update per-phone steps ──
    if path == "/api/groups/phone_steps":
        group_name = data.get("name", "").strip()
        serial = data.get("serial", "").strip()
        new_steps = data.get("steps")
        if not GROUPS_CFG.exists():
            return json_err("no saved groups_config.json found")
        try:
            cfg = json.loads(GROUPS_CFG.read_text())
        except Exception:
            return json_err("corrupt groups_config.json")
        for g in cfg.get("groups", []):
            if g.get("name") == group_name:
                phone_map = g.get("phones", {})
                if new_steps is not None:
                    # Update steps for this phone
                    if serial not in phone_map:
                        phone_map[serial] = {}
                    steps_to_save = (
                        normalize_automation_steps(new_steps)
                        if isinstance(new_steps, list)
                        else new_steps
                    )
                    if isinstance(phone_map[serial], dict):
                        phone_map[serial]["steps"] = steps_to_save
                    else:
                        phone_map[serial] = {"steps": steps_to_save}
                    if not _persist_groups_cfg(cfg):
                        return json_err("Phone steps were not saved — disk copy does not match.")
                    return json_ok({
                        "ok": True,
                        "saved": True,
                        "serial": serial,
                        "steps": steps_to_save,
                    })
                else:
                    # Return current steps for this phone
                    steps = (phone_map.get(serial) or {}).get("steps", []) if isinstance(phone_map.get(serial), dict) else []
                    return json_ok({"serial": serial, "steps": steps})
        return json_err("group not found")

    # ── Delete a saved group (per-operator delete from the dashboard UI) ──
    if path == "/api/groups/delete":
        name = str(data.get("name") or "").strip()
        if not name:
            return json_err("missing group name")
        if not GROUPS_CFG.exists():
            return json_err("no groups_config.json found")
        try:
            cfg = json.loads(GROUPS_CFG.read_text())
        except (json.JSONDecodeError, OSError):
            return json_err("corrupt groups_config.json")
        groups = cfg.get("groups") if isinstance(cfg, dict) else None
        if not isinstance(groups, list):
            return json_err("groups_config.json has no groups list")
        before = len(groups)
        groups = [g for g in groups if not (isinstance(g, dict) and str(g.get("name") or "").strip() == name)]
        if len(groups) == before:
            return json_err(f"group not found: {name}")
        if not _persist_groups_cfg({"groups": groups}):
            return json_err("Group was not deleted — disk copy does not match.")
        return json_ok({"ok": True, "deleted": name, "groups": len(groups)})

    # ── Save full groups config (dashboard / wizard parity with recordings/groups_config.json) ──
    if path == "/api/docker/action":
        return await handle_docker_action(body)

    if path == "/api/groups/save":
        raw = data.get("groups")
        if raw is None:
            return json_err("missing groups")
        if not isinstance(raw, list):
            return json_err("groups must be a JSON array")
        cfg = {"groups": _normalize_groups_payload(raw)}
        if not _persist_groups_cfg(cfg):
            log.warning("groups save failed: disk copy does not match")
            return json_err("Group was not saved — disk copy does not match.")
        return json_ok({"ok": True, "saved": True, "groups": len(cfg["groups"])})

    if path == "/api/groups/load":
        cfg, err = _load_groups_cfg()
        if err:
            return json_err(err)
        return json_ok(cfg)

    # ── App tester: launch app ──
    if path == "/api/launch_app":
        package = data.get("package", "").strip()
        target  = data.get("target", "all")
        try:
            stagger = max(0, int(data.get("stagger_secs", 0)))
        except (TypeError, ValueError):
            stagger = 0
        if not package:
            return json_err("no package specified")
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_.]*$', package):
            return json_err("invalid package name")
        phones  = list_phones()
        targets = [p for p in phones if p["running"] and (target == "all" or p["serial"] == target)]
        if not targets:
            return json_err("No phones are answering ADB.")
        loop    = asyncio.get_running_loop()

        def do_launch() -> int:
            launched = 0
            for i, p in enumerate(targets):
                if i > 0 and stagger > 0:
                    d = (
                        _hv.stagger_seconds(float(stagger), _hv.rng_for_run(p["serial"], i))
                        if _hv.enabled()
                        else float(stagger)
                    )
                    time.sleep(d)
                res = _adb(p["serial"], "shell", "monkey", "-p", package,
                           "-c", "android.intent.category.LAUNCHER", "1")
                if monkey_launch_reported(res.stdout, res.stderr):
                    launched += 1
                    msg = f"{p['name']}: launched {package}"
                else:
                    msg = f"{p['name']}: did not launch {package}"
                asyncio.run_coroutine_threadsafe(
                    broadcast({"type": "log", "msg": msg}), loop
                )
            return launched

        launched = await asyncio.get_running_loop().run_in_executor(None, do_launch)
        if launched < 1:
            return json_err("No phone launched the app.")
        return json_ok({"ok": True, "n": launched, "targeted": len(targets)})

    # ── App tester: type text ──
    if path == "/api/input_text":
        text   = data.get("text", "")
        target = data.get("target", "all")
        if not str(text):
            return json_err("no text")
        safe   = urllib.parse.quote(text, safe="").replace("%20", "%s")
        phones  = list_phones()
        targets = [p for p in phones if p["running"] and (target == "all" or p["serial"] == target)]
        if not targets:
            return json_err("No phones are answering ADB.")
        loop    = asyncio.get_running_loop()

        def do_type() -> int:
            typed = 0
            for p in targets:
                res = _adb(p["serial"], "shell", "input", "text", safe)
                if _adb_landed(res):
                    typed += 1
            msg = (
                f"Typed on {typed} of {len(targets)} phone(s)"
                if typed
                else "Typed on 0 phones — input did not land"
            )
            asyncio.run_coroutine_threadsafe(
                broadcast({"type": "log", "msg": msg}), loop
            )
            return typed

        typed = await asyncio.get_running_loop().run_in_executor(None, do_type)
        if typed < 1:
            return json_err("Text was not typed on any phone.")
        return json_ok({"ok": True, "n": typed, "targeted": len(targets)})

    # ── App tester: key event ──
    if path == "/api/input_key":
        try:
            keycode = int(data.get("keycode", 66))
        except (TypeError, ValueError):
            return json_err("invalid keycode")
        if keycode < 0:
            return json_err("keycode must be zero or greater")
        target  = data.get("target", "all")
        phones  = list_phones()
        targets = [p for p in phones if p["running"] and (target == "all" or p["serial"] == target)]
        if not targets:
            return json_err("No phones are answering ADB.")

        def do_keys() -> int:
            sent = 0
            for p in targets:
                res = _adb(p["serial"], "shell", "input", "keyevent", str(keycode))
                if _adb_landed(res):
                    sent += 1
            return sent

        sent = await asyncio.get_running_loop().run_in_executor(None, do_keys)
        if sent < 1:
            return json_err("Key was not sent to any phone.")
        return json_ok({"ok": True, "n": sent, "targeted": len(targets)})

    # ── App tester: quick action ──
    if path == "/api/quick_action":
        action = data.get("action", "")
        target = data.get("target", "all")
        if action not in _QUICK_ACTIONS and action != "screenshot":
            return json_err("unknown action")
        phones  = list_phones()
        targets = [p for p in phones if p["running"] and (target == "all" or p["serial"] == target)]
        if not targets:
            return json_err("No phones are answering ADB.")
        loop    = asyncio.get_running_loop()

        def do_action() -> int:
            landed = 0
            cmd = _QUICK_ACTIONS.get(action)
            if action == "screenshot":
                for p in targets:
                    ts  = int(time.time())
                    out = f"/sdcard/pharmflow_{ts}.png"
                    res = _adb(p["serial"], "shell", "screencap", "-p", out)
                    if _adb_landed(res):
                        landed += 1
                        msg = f"{p['name']}: screenshot → {out}"
                    else:
                        msg = f"{p['name']}: screenshot failed"
                    asyncio.run_coroutine_threadsafe(
                        broadcast({"type": "log", "msg": msg}), loop
                    )
            elif cmd:
                for p in targets:
                    res = _adb(p["serial"], *cmd)
                    if _adb_landed(res):
                        landed += 1
            return landed

        landed = await asyncio.get_running_loop().run_in_executor(None, do_action)
        if landed < 1:
            return json_err("Action did not land on any phone.")
        return json_ok({"ok": True, "n": landed, "targeted": len(targets)})

    # ── Legacy Play Store API (not in operator dashboard UI; browser-only DabFlow) ──
    if path == "/api/playstore/run":
        package = data.get("package", "").strip()
        query   = data.get("query", "").strip()
        review  = data.get("review", "").strip()
        try:
            stars = int(data.get("stars", 0))
            delay = max(0, int(data.get("delay_secs", 60)))
        except (TypeError, ValueError):
            return json_err("stars and delay_secs must be integers")
        if stars and not (1 <= stars <= 5):
            return json_err("stars must be between 1 and 5")
        if package and not re.match(r'^[a-zA-Z][a-zA-Z0-9_.]*$', package):
            return json_err("invalid package name")
        phones = [p for p in list_phones() if p.get("running")]
        if not phones:
            return json_err("No phones are answering ADB.")
        loop   = asyncio.get_running_loop()

        def on_log(msg):
            asyncio.run_coroutine_threadsafe(broadcast({"type": "log", "msg": msg}), loop)

        def on_done(result=None):
            landed = 0
            failed = 0
            if isinstance(result, dict):
                landed = int(result.get("landed") or 0)
                failed = int(result.get("failed") or 0)
            if landed < 1:
                msg = "Play Store run did not land on any phone."
            else:
                msg = (
                    f"Play Store commands landed on {landed} phone(s). "
                    "The store screen was not confirmed."
                )
                if failed:
                    msg += f" Failed on {failed}."
            asyncio.run_coroutine_threadsafe(
                broadcast({"type": "log", "msg": msg}),
                loop,
            )
            asyncio.run_coroutine_threadsafe(
                broadcast({
                    "type": "playstore_done",
                    "landed": landed,
                    "failed": failed,
                }),
                loop,
            )

        ps_mod.run_full_sequence(phones, package, query, stars, review,
                                 delay_secs=delay, on_log=on_log, on_complete=on_done)
        return json_ok({"ok": True, "started": True, "n": len(phones)})

    if path == "/api/playstore/open":
        package = data.get("package", "").strip()
        if not package or not re.match(r'^[a-zA-Z][a-zA-Z0-9_.]*$', package):
            return json_err("invalid package name")
        phones = _running_phones_ordered()
        if not phones:
            return json_err("No phones are answering ADB.")
        loop   = asyncio.get_running_loop()

        def _open() -> int:
            opened = 0
            for p in phones:
                ok = bool(ps_mod.open_store_page_serial(p["serial"], package))
                if ok:
                    opened += 1
                    msg = f"{p['name']}: opened {package}"
                else:
                    msg = f"{p['name']}: did not open {package}"
                asyncio.run_coroutine_threadsafe(
                    broadcast({"type": "log", "msg": msg}), loop
                )
            return opened

        opened = await asyncio.get_running_loop().run_in_executor(None, _open)
        if opened < 1:
            return json_err("No phone opened the store page.")
        return json_ok({"ok": True, "n": opened, "targeted": len(phones)})

    return _http(404, "text/plain", b"Not Found")


# ── WebSocket ─────────────────────────────────────────────────────────────────

async def handle_scheduler(path, body_bytes):
    from scheduler import handle_scheduler as _hs
    return await _hs(path, body_bytes=body_bytes)

async def ws_handler(websocket):
    if len(_ws_clients) >= 20:
        await websocket.close(1008, "Too many clients")
        return
    _ws_clients.add(websocket)
    try:
        await push_phones()
        async for _ in websocket:
            pass
    except Exception:
        pass
    finally:
        _ws_clients.discard(websocket)


async def auto_refresh():
    while True:
        await asyncio.sleep(10)
        try:
            await push_phones()
        except Exception:
            pass


def _port_try_count() -> int:
    # No ceiling: the bind loops below are bounded by the port space (65535)
    # and stop at the first successful bind, so a large value costs nothing.
    # Capping here (256) while the wizard probe capped at 128 meant a count in
    # between could bind where the wizard never looked.
    try:
        v = int(os.environ.get("PHARMFLOW_PORT_TRY_COUNT", "20"))
        return max(1, v)
    except (TypeError, ValueError):
        return 20


def _addr_in_use(exc: OSError) -> bool:
    if exc.errno == errno.EADDRINUSE:
        return True
    if exc.errno in (10048, 98):
        return True
    if getattr(exc, "winerror", None) == 10048:
        return True
    return False


async def _start_http_server_with_port_fallback(
    host: str, start_port: int, max_attempts: int
) -> tuple[asyncio.base_events.Server, int]:
    last_err: OSError | None = None
    hi = min(65535, start_port + max_attempts - 1)
    for port in range(start_port, hi + 1):
        try:
            srv = await asyncio.start_server(handle_http, host, port)
            return srv, port
        except OSError as e:
            last_err = e
            if not _addr_in_use(e):
                raise
            if port < hi:
                log.info("Port %s busy, trying %s…", port, port + 1)
    if last_err is not None:
        raise last_err
    raise OSError(errno.EADDRINUSE, "no HTTP port available in scan range")


async def _start_ws_server_with_port_fallback(
    host: str, preferred_ws: int, http_port: int, max_attempts: int
):
    """Bind the WebSocket server on a port other than ``http_port``; retry if busy."""
    first = preferred_ws if preferred_ws != http_port else http_port + 1
    last_err: OSError | None = None
    port = first
    attempts = 0
    while port <= 65535 and attempts < max_attempts:
        if port == http_port:
            port += 1
            continue
        try:
            ws_srv = await serve(ws_handler, host, port)
            return ws_srv, port
        except OSError as e:
            last_err = e
            if not _addr_in_use(e):
                raise
            if attempts + 1 < max_attempts and port < 65535:
                log.info("WebSocket port %s busy, trying %s…", port, port + 1)
            port += 1
            attempts += 1
    if last_err is not None:
        raise last_err
    raise OSError(errno.EADDRINUSE, "no WebSocket port available in scan range")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    global LISTEN_HTTP_PORT, LISTEN_WS_PORT

    APK_DIR.mkdir(exist_ok=True)
    ip = dashboard_reach_host()

    # Try to connect to any emulators already running
    log.info("Scanning for connected devices…")
    threading.Thread(target=auto_connect_emulators, daemon=True).start()
    threading.Thread(target=_stealth_warm_exit_ips, daemon=True).start()
    try:
        _farm_visits_tally.update(_load_farm_visits_tally())
    except Exception:
        pass

    if not _pharmflow_skip_tor_wait():
        tor_manager.start_tor_host_bootstrap_background()

    max_tries = _port_try_count()
    http_server, http_p = await _start_http_server_with_port_fallback(
        LISTEN_HOST, CONFIG_HTTP_PORT, max_tries
    )
    ws_server, ws_p = await _start_ws_server_with_port_fallback(
        LISTEN_HOST, CONFIG_WS_PORT, http_p, max_tries
    )
    LISTEN_HTTP_PORT = http_p
    LISTEN_WS_PORT = ws_p

    log.info(
        "Bound HTTP on %s:%s and WebSocket on %s:%s (launcher URLs must use these ports if not default)",
        LISTEN_HOST,
        LISTEN_HTTP_PORT,
        LISTEN_HOST,
        LISTEN_WS_PORT,
    )

    print("\n  ╔══════════════════════════════════════════╗")
    print("  ║   PharmFlow  •  ready                       ║")
    print("  ║                                          ║")
    print(f"  ║   On this PC:  http://{ip}:{LISTEN_HTTP_PORT}    ║")
    print(
        f"  ║   Bind:        {LISTEN_HOST}:{LISTEN_HTTP_PORT} (HTTP)  "
        f"{LISTEN_HOST}:{LISTEN_WS_PORT} (WS)   ║"
    )
    print("  ║   Phone traffic does not use this address.    ║")
    print("  ║                                          ║")
    print("  ║   Press Ctrl+C to stop                   ║")
    print(f"  ╚══════════════════════════════════════════╝\n")

    async with http_server, ws_server:
        await asyncio.gather(
            http_server.serve_forever(),
            ws_server.wait_closed(),
            auto_refresh(),
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  PharmFlow stopped.")
