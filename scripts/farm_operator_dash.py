#!/usr/bin/env python3
"""FamFlow Farm Operator — adjustable dash for 5 phones + knobs I monitor.

  py -u scripts/farm_operator_dash.py
  → http://127.0.0.1:8091

Writes:
  C:\\CPharm\\logs\\farm_operator_panel.json   (full panel state)
  C:\\CPharm\\logs\\farm_panel_state.json      (synced twin for farm worker)
  C:\\CPharm\\logs\\farm_runtime_overrides.json (CPHARM_* — source of truth for caps)

Pull from Mantis → gauges, then closed-loop autopilot (browse-only at ≥40 clicks,
kill evening flood, dwell/throttle) via automation/mantis_autopilot_*.py.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, render_template_string, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import automation.no_window  # noqa: E402,F401  (kill child console-window flashes)
from automation.browse_proxy import browse_proxy_mode, save_browse_prefs  # noqa: E402
from automation.farm_pause import (  # noqa: E402
    clear_kill_switch,
    engage_kill_switch,
)
from automation.farm_visit_caps import (  # noqa: E402
    clear_dabflow_sticky_pin,
    set_loansflow_operator_hold,
    write_runtime_overrides,
)
from automation.farm_sites import (  # noqa: E402
    apply_site_to_panel,
    list_farm_sites,
    seed_builtin_profiles,
    site_info,
)
from automation.mantis_farm_math import (  # noqa: E402
    TARGET_PROFIT_REALISTIC_USD,
    TARGET_PROFIT_STRONG_USD,
    TARGET_PROFIT_STRETCH_USD,
)

from wizard.wizard_paths import sequences_dir as wizard_sequences_dir  # noqa: E402

LOG_DIR = Path(r"C:\CPharm\logs")
PANEL = LOG_DIR / "farm_operator_panel.json"
OVERRIDES = Path("NUL") if __import__('os').name == 'nt' else Path('/dev/null')  # DISABLED: caps were killing revenue
FARM_LOG = LOG_DIR / "farm_354.log"
ADS_WATCH = LOG_DIR / "ads_watch_state.json"
CYCLE_LOG = LOG_DIR / "farm_cycles.log"
DAILY_BUDGET = LOG_DIR / "farm_daily_budget_state.json"
PROGRESS = LOG_DIR / "farm_354_progress.json"
PATH3_DAILY = LOG_DIR / "farm_path3_daily_state.json"
MANTIS_TODAY = LOG_DIR / "mantis_today_state.json"
AUTOPILOT_STATE = LOG_DIR / "autopilot_state.json"
EXIT_IPS = LOG_DIR / "farm_exit_ips.json"
SERIAL_MAP = LOG_DIR / "ADB_SERIAL_MAP.lock.json"
SERIAL_BROWSER = LOG_DIR / "serial_browser_pkg.json"

HOST = os.environ.get("CPHARM_OPERATOR_HOST", "127.0.0.1")
PORT = int(os.environ.get("CPHARM_OPERATOR_PORT", "8091") or "8091")

_PS_FARM_CACHE: dict[str, Any] | None = None
_PS_FARM_CACHE_TS = 0.0


def _subprocess_hidden_kwargs() -> dict[str, Any]:
    """Prevent blank PowerShell/console flashes on Windows."""
    if sys.platform != "win32":
        return {}
    kwargs: dict[str, Any] = {
        "creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0),
    }
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = si
    except Exception:
        pass
    return kwargs


DEFAULT_PHONES = [
    "vm0.gmadoa",
    "vm1.gmadoa",
    "vm2.gmadoa",
    "vm3.gmadoa",
    "vm4.gmadoa",
    "vm5.gmadoa",
]


def _phones_from_sticky() -> list[str]:
    """Adaptive phone list from remediator sticky (ban vm11). Fallback = DEFAULT_PHONES."""
    try:
        data = json.loads(OVERRIDES.read_text(encoding="utf-8-sig")) if OVERRIDES.is_file() else {}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        data = {}
    raw = str(data.get("CPHARM_FARM_PHONES") or "")
    phones = [
        p.strip() if "." in p.strip() else f"{p.strip()}.gmadoa"
        for p in raw.split(",")
        if p.strip() and "vm11" not in p.lower() and p.strip().lower().startswith("vm")
    ]
    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for p in phones:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out or list(DEFAULT_PHONES)

# Knobs the farm actually honors (plus a few ad-fill critical ones).
# CPHARM_FARM_HOURS is locked to 0 (24h day mode) in save_panel — not a user knob.
# Seqs/hour and Path3/hour are NOT knobs — day mode paces from per-phone daily visits/ads.
KNOBS: list[dict[str, Any]] = [
    {"key": "CPHARM_FARM_PATHS", "label": "Paths enabled", "type": "text", "default": "1,2,3", "group": "cadence"},
    {"key": "CPHARM_FARM_ALLOW_ADS", "label": "Allow ads (Path3)", "type": "toggle", "default": "1", "group": "ads"},
    # Ad inject/patch/CDP settings are HARDCODED in save_panel + apply_money_rails.
    # Removed from dash UI to prevent accidental toggle (they kill revenue when off).
    {"key": "CPHARM_EMULATOR_AD_FILL_WAIT", "label": "Ad fill wait (sec)", "type": "number", "default": "4", "group": "ads"},
    {"key": "CPHARM_BROWSE_PROXY_MODE", "label": "Browse proxy", "type": "select", "default": "scramble", "options": ["scramble", "tor", "direct"], "group": "identity"},
    {"key": "CPHARM_REQUIRE_UNIQUE_EXIT_IP", "label": "Unique Tor exit IP", "type": "toggle", "default": "1", "group": "identity"},
    {"key": "CPHARM_GEO_TIME_WINDOW", "label": "Geo awake window", "type": "toggle", "default": "1", "group": "identity"},
    {"key": "CPHARM_GEO_WINDOW_START", "label": "Geo window start", "type": "text", "default": "09:30", "group": "identity"},
    {"key": "CPHARM_GEO_WINDOW_END", "label": "Geo window end", "type": "text", "default": "00:00", "group": "identity"},
    {"key": "CPHARM_AGE_GATE_WAIT", "label": "Age gate wait (sec, no ads)", "type": "number", "default": "0.8", "group": "timing"},
    {"key": "CPHARM_DABFLOW_LOAD_WAIT", "label": "DabFlow load wait (sec)", "type": "number", "default": "2.0", "group": "timing"},
    {"key": "CPHARM_START_DAB_VERIFY_WAIT", "label": "Start Dab verify wait", "type": "number", "default": "2.5", "group": "timing"},
    {"key": "CPHARM_FARM_START_STAGGER_WINDOW", "label": "Start stagger window (sec)", "type": "number", "default": "120", "group": "timing"},
    {"key": "CPHARM_FARM_START_STAGGER_MIN_GAP", "label": "Start stagger min gap (sec)", "type": "number", "default": "15", "group": "timing"},
    {"key": "CPHARM_FARM_START_STAGGER_BAND", "label": "Start stagger band/window alias (sec)", "type": "number", "default": "120", "group": "timing"},
    {"key": "CPHARM_FARM_SLOT_JITTER", "label": "Seq slot jitter (±sec)", "type": "number", "default": "55", "group": "timing"},
    {"key": "CPHARM_FARM_START_STAGGER_JITTER", "label": "Legacy start jitter (sec)", "type": "number", "default": "40", "group": "timing"},
]

LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("farm_operator")

# Money-day short stagger. Profile used to invent WINDOW=1800 / MIN_GAP=306.
_MONEY_STAGGER_WINDOW = "120"
_MONEY_STAGGER_MIN_GAP = "15"
_MONEY_STAGGER_JITTER = "40"
_STAGGER_KEYS = (
    "CPHARM_FARM_START_STAGGER_WINDOW",
    "CPHARM_FARM_START_STAGGER_MIN_GAP",
    "CPHARM_FARM_START_STAGGER_BAND",
    "CPHARM_FARM_START_STAGGER_JITTER",
)


def _as_stagger_float(raw: Any, default: float = 0.0) -> float:
    try:
        return float(str(raw or "").strip() or default)
    except (TypeError, ValueError):
        return float(default)


def _money_day_stagger_env(
    env: dict[str, Any] | None = None,
    disk_ov: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Sticky short stagger wins; anything >300s snaps to money-day 120/15."""
    env = env or {}
    disk_ov = disk_ov or {}
    sticky_w = _as_stagger_float(disk_ov.get("CPHARM_FARM_START_STAGGER_WINDOW"), 0.0)
    sticky_g = _as_stagger_float(disk_ov.get("CPHARM_FARM_START_STAGGER_MIN_GAP"), 0.0)
    cur_w = _as_stagger_float(env.get("CPHARM_FARM_START_STAGGER_WINDOW"), 0.0)
    if 0.0 < sticky_w <= 300.0:
        want_w = sticky_w
        want_g = sticky_g if 0.0 < sticky_g <= 120.0 else float(_MONEY_STAGGER_MIN_GAP)
    elif 0.0 < cur_w <= 300.0:
        want_w = cur_w
        want_g = _as_stagger_float(
            env.get("CPHARM_FARM_START_STAGGER_MIN_GAP"), float(_MONEY_STAGGER_MIN_GAP)
        )
        if want_g <= 0.0 or want_g > 120.0:
            want_g = float(_MONEY_STAGGER_MIN_GAP)
    else:
        want_w = float(_MONEY_STAGGER_WINDOW)
        want_g = float(_MONEY_STAGGER_MIN_GAP)
    want_j = _as_stagger_float(
        disk_ov.get("CPHARM_FARM_START_STAGGER_JITTER")
        or env.get("CPHARM_FARM_START_STAGGER_JITTER"),
        float(_MONEY_STAGGER_JITTER),
    )
    if want_j <= 0.0 or want_j > 90.0:
        want_j = float(_MONEY_STAGGER_JITTER)
    return {
        "CPHARM_FARM_START_STAGGER_WINDOW": str(int(want_w)),
        "CPHARM_FARM_START_STAGGER_BAND": str(int(want_w)),
        "CPHARM_FARM_START_STAGGER_MIN_GAP": str(int(want_g)),
        "CPHARM_FARM_START_STAGGER_JITTER": str(int(want_j)),
    }


app = Flask(__name__)
_lock = threading.RLock()

# Single-flight check-in cache — nested /api/status polls used to spawn unbounded
# dash-checkin threads (100+), spike CPU, and balloon RSS when ADB hung.
_CHECKIN_CACHE: dict[str, Any] = {
    "result": None,
    "ts": 0.0,
    "inflight": False,
    "lock": threading.Lock(),
}
_CHECKIN_CACHE_TTL_S = 20.0
_CHECKIN_STALE_OK_S = 120.0


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        # utf-8-sig tolerates BOM from PowerShell Set-Content.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


# Per-phone daily budgets from MANTIS_FARM_SEQUENCE_GUIDANCE.md:
# ~115–180 visits/phone (~450–720 farm), ~3–5 ads/phone (~12–20 farm), wiggled.
DEFAULT_BUDGETS: dict[str, dict[str, int]] = {
    "vm0.gmadoa": {"visits": 173, "ads": 5},
    "vm1.gmadoa": {"visits": 148, "ads": 4},
    "vm2.gmadoa": {"visits": 141, "ads": 4},
    "vm3.gmadoa": {"visits": 119, "ads": 3},
}


def _default_panel() -> dict[str, Any]:
    env = {k["key"]: str(k["default"]) for k in KNOBS}
    # Unique-seq is a hard farm invariant — always on for every site.
    env["CPHARM_FARM_UNIQUE_SEQ"] = "1"
    env["CPHARM_SITE_SLUG"] = "dabflow"
    return {
        "updated": _utc(),
        "phones": list(DEFAULT_PHONES),
        "forever": True,
        "hours": 0.0,
        "env": env,
        "budgets": {p: dict(DEFAULT_BUDGETS.get(p, {"visits": 0, "ads": 0})) for p in DEFAULT_PHONES},
        "notes": "Ads must be visible on Path1/2/3; Path3 only engages.",
        "last_action": None,
        "last_action_at": None,
        "active_site_slug": "dabflow",
    }


def load_panel() -> dict[str, Any]:
    base = _default_panel()
    if not PANEL.is_file():
        return base
    try:
        data = json.loads(PANEL.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return base
    if not isinstance(data, dict):
        return base
    base.update(
        {
            k: data[k]
            for k in (
                "phones",
                "forever",
                "hours",
                "notes",
                "last_action",
                "last_action_at",
                "active_site_slug",
            )
            if k in data
        }
    )
    if isinstance(data.get("budgets"), dict):
        merged = dict(base.get("budgets") or {})
        for phone, row in data["budgets"].items():
            if not isinstance(row, dict):
                continue
            try:
                merged[str(phone)] = {
                    "visits": max(0, int(float(row.get("visits", 0) or 0))),
                    "ads": max(0, int(float(row.get("ads", 0) or 0))),
                }
            except (TypeError, ValueError):
                continue
        base["budgets"] = merged
    env = dict(base["env"])
    if isinstance(data.get("env"), dict):
        for k, v in data["env"].items():
            env[str(k)] = str(v)
    base["env"] = env
    base["updated"] = data.get("updated") or base["updated"]
    return base


def save_panel(panel: dict[str, Any]) -> dict[str, Any]:
    panel = dict(panel)
    panel["updated"] = _utc()
    phones = [p for p in panel.get("phones") or [] if isinstance(p, str) and p.startswith("vm")]
    if not phones:
        phones = _phones_from_sticky()
    # Adaptive: follow sticky live set when it has more phones than stale panel.
    sticky = _phones_from_sticky()
    if len(sticky) > len(phones):
        phones = sticky
    panel["phones"] = phones[:12]
    panel["forever"] = True
    # Always 24h day mode — pace from daily visit/ad budgets, midnight reset.
    panel["hours"] = 0.0
    form_env = panel.get("env") if isinstance(panel.get("env"), dict) else {}
    prev_panel = load_panel()
    prev_env = prev_panel.get("env") if isinstance(prev_panel.get("env"), dict) else {}
    # Also keep extras already on disk overrides (gap, humanize, chromium lock, …)
    disk_ov = _read_json_file(OVERRIDES)
    # Start from prior CPHARM_* so Save no longer wipes non-knob params back to defaults.
    env: dict[str, str] = {}
    for src in (disk_ov, prev_env, form_env):
        if not isinstance(src, dict):
            continue
        for k, v in src.items():
            if str(k).startswith("CPHARM_") and v not in (None, ""):
                env[str(k)] = str(v)
    for knob in KNOBS:
        key = str(knob["key"])
        if key in form_env and form_env[key] not in (None, ""):
            env[key] = str(form_env[key])
        elif key not in env:
            env[key] = str(knob["default"])
    # Pin money-day short stagger: refuse profile/UI thrash back to 1800/306.
    env.update(_money_day_stagger_env(env, disk_ov))
    # Hard invariants for visible ads + per-seq isolation (do NOT force Tor —
    # operator/desktop_prefs choose scramble|tor|direct; scramble is recommended).
    # CDP always fails on MuMu (/json closed) — inject proxy handles MITM paint.
    # SKIP_MANTIS_PATCH=0 so Mantis creative paint + billing pixels fire on Path3.
    env["CPHARM_SKIP_MANTIS_PATCH"] = "0"
    env["CPHARM_DABFLOW_MANTIS_PATCH"] = "1"
    env["CPHARM_ALLOW_SEQUENCE_RUNS"] = "1"
    # billing_direct MUST stay OFF — routes all clicks from HOST IP.
    # Each phone needs its own Tor exit IP for Mantis to count clicks.
    env["CPHARM_MANTIS_BILLING_DIRECT"] = "0"
    # CRITICAL: inject proxy must NEVER be disabled by stale panel env.
    # Without inject, CDP probes run (30-60s waste) and no creative paint.
    env["CPHARM_MANTIS_INJECT_PROXY"] = "1"
    env["CPHARM_MANTIS_INJECT_MITM"] = "1"
    env["CPHARM_EMULATOR_AD_MODE"] = "1"
    # Never disable concurrent unique-sequence lock from the operator panel.
    env["CPHARM_FARM_UNIQUE_SEQ"] = "1"
    slug = str(panel.get("active_site_slug") or env.get("CPHARM_SITE_SLUG") or "dabflow").strip()
    # DabFlow sticky / watchdog-disabled beats LoansFlow hold this session.
    try:
        if (LOG_DIR / "DABFLOW_SITE_STICKY.flag").is_file() or (
            LOG_DIR / "LOANSFLOW_HOLD_WATCHDOG_DISABLED.flag"
        ).is_file():
            slug = "dabflow"
            hp = LOG_DIR / "LOANSFLOW_OPERATOR_HOLD.flag"
            if hp.is_file():
                try:
                    hp.unlink(missing_ok=True)
                except OSError:
                    pass
        elif (LOG_DIR / "LOANSFLOW_OPERATOR_HOLD.flag").is_file():
            slug = "loansflow"
        else:
            site_lock = _read_json_file(LOG_DIR / "farm_site_lock.json")
            locked = str(site_lock.get("slug") or "").strip().lower()
            lock_note = str(site_lock.get("note") or "")
            if locked == "loansflow" and lock_note.startswith("operator_"):
                # sticky already handled above; refuse operator loansflow lock tonight
                slug = "dabflow" if (LOG_DIR / "DABFLOW_SITE_STICKY.flag").is_file() else "loansflow"
            elif (LOG_DIR / "DABFLOW_SITE_STICKY.flag").is_file():
                slug = "dabflow"
            else:
                caps = _read_json_file(LOG_DIR / "farm_visit_caps_lock.json")
                if str(caps.get("CPHARM_SITE_SLUG") or "").strip().lower() == "dabflow":
                    slug = "dabflow"
    except Exception:
        pass
    panel["active_site_slug"] = slug or "dabflow"
    env["CPHARM_SITE_SLUG"] = panel["active_site_slug"]
    if panel["active_site_slug"] == "loansflow":
        # Non-DabFlow farms must point at sequences/<slug>/ (see run_farm_354).
        env["CPHARM_FARM_SEQUENCE_ROOT"] = str(wizard_sequences_dir() / "loansflow")
        env.setdefault("CPHARM_NTFY_TOPIC", "twskoops")
        # DabFlow Mantis catch-up must not bleed onto LoansFlow AdSense warming.
        env.pop("CPHARM_SWEET_SPOT_LOCK", None)
        env.pop("CPHARM_SWEET_SPOT_LOCK_UNTIL", None)
    elif panel["active_site_slug"] == "dabflow":
        env.pop("CPHARM_FARM_SEQUENCE_ROOT", None)
    env["CPHARM_FARM_STOP"] = "0"
    env["CPHARM_FARM_HOURS"] = "0"
    mode = str(env.get("CPHARM_BROWSE_PROXY_MODE") or "scramble").strip().lower()
    if mode not in ("scramble", "tor", "direct", "upstream"):
        mode = "scramble"
    env["CPHARM_BROWSE_PROXY_MODE"] = mode
    try:
        save_browse_prefs(browse_proxy_mode=mode)
    except Exception:
        pass
    # Path1/2/3 — keep Path3 when ads are allowed; do NOT re-arm Path3 during
    # browse-only catch-up (ALLOW_ADS=0 / sweet-spot impr_catchup).
    ads_on = str(env.get("CPHARM_FARM_ALLOW_ADS") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    lock = str(env.get("CPHARM_SWEET_SPOT_LOCK") or "").strip().lower()
    catchup_lock = lock in ("impr_catchup", "1", "true", "yes", "on")
    # LoansFlow never uses DabFlow Mantis catch-up browse-only mode.
    if panel["active_site_slug"] == "loansflow":
        catchup_lock = False
        if str(form_env.get("CPHARM_FARM_ALLOW_ADS") or env.get("CPHARM_FARM_ALLOW_ADS") or "1").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        ):
            ads_on = True
            env["CPHARM_FARM_ALLOW_ADS"] = "1"
    paths = str(env.get("CPHARM_FARM_PATHS") or ("1,2,3" if ads_on else "1,2"))
    parts = [p.strip() for p in paths.split(",") if p.strip()]
    if ads_on and not catchup_lock:
        for need in ("1", "2", "3"):
            if need not in parts:
                parts.append(need)
    else:
        # Browse-only: Path1/2 only.
        parts = [p for p in parts if p in ("1", "2")] or ["1", "2"]
    env["CPHARM_FARM_PATHS"] = ",".join(parts)

    # Per-phone daily budgets → CPHARM_FARM_DAILY_VISITS / _ADS ordered by phone list.
    raw_budgets = panel.get("budgets") if isinstance(panel.get("budgets"), dict) else {}
    prev_budgets = (
        prev_panel.get("budgets") if isinstance(prev_panel.get("budgets"), dict) else {}
    )
    # Sticky high-cap lock (autopilot $100 push) — never Save back to ~295.
    caps_lock = _read_json_file(LOG_DIR / "farm_visit_caps_lock.json")
    try:
        target_usd = float(
            env.get("CPHARM_TARGET_PROFIT_STRONG_USD")
            or env.get("CPHARM_TARGET_PROFIT_USD")
            or 0
        )
    except (TypeError, ValueError):
        target_usd = 0.0
    high_caps = target_usd >= 90.0 or catchup_lock or bool(
        str(caps_lock.get("CPHARM_FARM_DAILY_VISITS") or "").strip()
    )
    if panel["active_site_slug"] == "loansflow":
        high_caps = False
    lock_vparts = [
        p.strip()
        for p in str(caps_lock.get("CPHARM_FARM_DAILY_VISITS") or "").split(",")
        if p.strip()
    ]
    disk_vparts = [
        p.strip()
        for p in str(disk_ov.get("CPHARM_FARM_DAILY_VISITS") or "").split(",")
        if p.strip()
    ]
    budgets: dict[str, dict[str, int]] = {}
    for phone in phones:
        row = raw_budgets.get(phone) if isinstance(raw_budgets.get(phone), dict) else {}
        prev_row = prev_budgets.get(phone) if isinstance(prev_budgets.get(phone), dict) else {}
        dflt = DEFAULT_BUDGETS.get(phone, {"visits": 100, "ads": 2})
        # Prefer form → previous saved → guidance defaults (never silently revert to
        # DEFAULT_BUDGETS when the operator already set higher sweet-spot caps).
        try:
            visits = max(0, int(float(row.get("visits", prev_row.get("visits", dflt["visits"])) or 0)))
        except (TypeError, ValueError):
            visits = int(prev_row.get("visits") or dflt["visits"])
        try:
            ads = max(0, int(float(row.get("ads", prev_row.get("ads", dflt["ads"])) or 0)))
        except (TypeError, ValueError):
            ads = int(prev_row.get("ads") or dflt["ads"])
        if visits <= 0:
            visits = int(prev_row.get("visits") or dflt["visits"])
        if ads <= 0 and ads_on:
            ads = int(prev_row.get("ads") or dflt["ads"])
        if not ads_on or catchup_lock:
            ads = 0
        budgets[phone] = {"visits": visits, "ads": ads}
    # If Save would drop below the $100 floor while lock/target is high, keep disk/lock.
    try:
        form_max = max(int(budgets[p]["visits"]) for p in phones) if phones else 0
    except (TypeError, ValueError):
        form_max = 0
    if high_caps and form_max < 400:
        keep_parts = lock_vparts if len(lock_vparts) >= len(phones) else disk_vparts
        if len(keep_parts) >= len(phones):
            for i, phone in enumerate(phones):
                try:
                    budgets[phone]["visits"] = max(400, int(float(keep_parts[i])))
                except (TypeError, ValueError, IndexError):
                    budgets[phone]["visits"] = max(400, int(budgets[phone]["visits"] or 0))
        else:
            for phone in phones:
                budgets[phone]["visits"] = max(400, int(budgets[phone]["visits"] or 0))
    panel["budgets"] = budgets
    env["CPHARM_FARM_DAILY_VISITS"] = ",".join(str(budgets[p]["visits"]) for p in phones)
    env["CPHARM_FARM_DAILY_ADS"] = ",".join(str(budgets[p]["ads"]) for p in phones)
    # Farm-wide Path3 ceiling = sum of per-phone ad budgets (0 while browse-only).
    total_ads = sum(budgets[p]["ads"] for p in phones)
    total_visits = sum(budgets[p]["visits"] for p in phones)
    if ads_on and not catchup_lock:
        env["CPHARM_FARM_PATH3_DAILY_CAP"] = str(max(1, total_ads))
    else:
        env["CPHARM_FARM_PATH3_DAILY_CAP"] = "0"
        env["CPHARM_FARM_PATH3_PER_HOUR"] = "0"
        env["CPHARM_FARM_ALLOW_ADS"] = "0"
    try:
        ipv = float(
            env.get("CPHARM_FARM_IMPRESSIONS_PER_VISIT")
            or prev_env.get("CPHARM_FARM_IMPRESSIONS_PER_VISIT")
            or 22
        )
    except (TypeError, ValueError):
        ipv = 22.0
    if ipv <= 0:
        ipv = 22.0
    env["CPHARM_FARM_IMPRESSIONS_PER_VISIT"] = str(ipv)
    env["CPHARM_FARM_EST_IMPRESSIONS"] = str(int(round(total_visits * ipv)))
    # Day mode: pacing is remaining visits÷hours left. Keep SEQS floor during
    # $100 catch-up so autopilot/ensure do not fall back to 15–22.
    if high_caps:
        try:
            seqs_now = int(
                float(
                    str(
                        form_env.get("CPHARM_FARM_SEQS_PER_HOUR")
                        or disk_ov.get("CPHARM_FARM_SEQS_PER_HOUR")
                        or caps_lock.get("CPHARM_FARM_SEQS_PER_HOUR")
                        or 28
                    )
                )
            )
        except (TypeError, ValueError):
            seqs_now = 28
        # GO_BIG money day: honor the operator's SEQS_PER_HOUR (sticky/caps-lock),
        # never clamp to 22 — the old ceiling capped impressions and starved revenue.
        env["CPHARM_FARM_SEQS_PER_HOUR"] = str(max(18, seqs_now))
    else:
        env.pop("CPHARM_FARM_SEQS_PER_HOUR", None)
    # Keep PATH3_PER_HOUR / GLOBAL_GAP if operator or autopilot set them.
    panel["env"] = env

    PANEL.write_text(json.dumps(panel, indent=2), encoding="utf-8")

    overrides = {**env, "updated": panel["updated"], "CPHARM_FARM_PHONES": ",".join(panel["phones"])}
    # Preserve ADB serials / non-env operator notes already on disk.
    for keep in (
        "CPHARM_ADB_SERIALS",
        "CPHARM_FARM_PHONES",
        "gauge_push_note",
        "autopilot_last_reason",
        "CPHARM_FARM_CHROMIUM_ONLY",
        "CPHARM_FARM_BROWSERS",
        "CPHARM_DISPLAY_LOCK",
        "CPHARM_MANTIS_INJECT_PROXY",
        "CPHARM_MANTIS_INJECT_MITM",
        "tick_verify_note",
        "CPHARM_FARM_PHONE_COUNT",
        "CPHARM_FARM_EXPECT_PHONES",
        "CPHARM_AUTOPILOT_PAUSE",
    ):
        if keep in disk_ov and keep not in overrides:
            overrides[keep] = disk_ov[keep]
    # Unavoidable sticky floor — same guard as autopilot apply.
    write_runtime_overrides(overrides, log_dir=LOG_DIR)
    return panel


def _ps_farm() -> dict[str, Any]:
    """List farm helper processes — psutil only (never spawn PowerShell)."""
    global _PS_FARM_CACHE, _PS_FARM_CACHE_TS
    now = time.time()
    if _PS_FARM_CACHE is not None and (now - _PS_FARM_CACHE_TS) < 20.0:
        return _PS_FARM_CACHE
    try:
        from automation.process_scan import iter_matching_processes

        rows = iter_matching_processes()
    except Exception:
        rows = []
    _PS_FARM_CACHE = {"processes": rows}
    _PS_FARM_CACHE_TS = now
    return _PS_FARM_CACHE


def _tail(path: Path, n: int = 40) -> list[str]:
    """Read last n lines without loading the whole farm log into memory."""
    if not path.is_file() or n <= 0:
        return []
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            if size <= 0:
                return []
            block = 8192
            data = b""
            while size > 0 and data.count(b"\n") <= n:
                step = min(block, size)
                size -= step
                fh.seek(size)
                data = fh.read(step) + data
                if size == 0:
                    break
            text = data.decode("utf-8", errors="replace")
            lines = text.splitlines()
            return lines[-n:]
    except OSError:
        return []


_CMD_INTEREST = (
    "IP claimed",
    "IP before=",
    "isolate phone=",
    "seq IP",
    "Path3",
    "Farm check-in",
    "unique-seq",
    "ERROR",
    "FAIL",
    "rejected (",
    "ONLINE",
    "farm logging ready",
)


def _cmd_console_lines(n: int = 50) -> list[str]:
    """Operator-facing console: recent cmds sent + interesting farm lines."""
    out: list[str] = []
    hist = LOG_DIR / "dash_cmd_history.log"
    if hist.is_file():
        try:
            for line in hist.read_text(encoding="utf-8", errors="replace").splitlines()[-12:]:
                out.append(line)
        except OSError:
            pass
    farm_lines = _tail(FARM_LOG, 120)
    interesting = [
        ln for ln in farm_lines if any(tok in ln for tok in _CMD_INTEREST)
    ][-max(8, n - len(out)) :]
    out.extend(interesting)
    return out[-n:]


def _append_cmd_history(text: str) -> None:
    hist = LOG_DIR / "dash_cmd_history.log"
    try:
        hist.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%H:%M:%S")
        with hist.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] YOU → {text}\n")
    except OSError:
        pass


def _kill_farm() -> None:
    try:
        from automation.process_scan import kill_matching

        kill_matching(("run_farm_354.py", "run_farm_cycles.py"))
    except Exception:
        pass


def _start_farm(panel: dict[str, Any]) -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    for k, v in (panel.get("env") or {}).items():
        env[str(k)] = str(v)
    env["CPHARM_ALLOW_SEQUENCE_RUNS"] = "1"
    env["CPHARM_FARM_STOP"] = "0"
    # Do not pass hardcoded --phones — run_farm_354 / cycles adapt to live ADB.
    args = [sys.executable, "-u", str(ROOT / "scripts" / "run_farm_cycles.py")]
    # Daily budgets → always day mode (hours=0), forever — no 6h cycle restarts.
    args += ["--forever", "--hours", "0"]
    proc = subprocess.Popen(
        args,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return int(proc.pid)


def _clear_phones(phones: list[str]) -> list[str]:
    from automation.browser_adb import clear_chromium_all_data
    from automation.config import BROWSER_CHROMIUM
    from wizard.mumu_farm_ops import MuMuFarmOps

    farm = MuMuFarmOps()
    farm.list_instances()
    out: list[str] = []
    for name in phones:
        inst = farm.get_phone(name)
        ser = getattr(inst, "adb_serial", None) if inst else None
        if not ser:
            out.append(f"{name}: missing")
            continue
        farm.adb.shell(f"am force-stop {BROWSER_CHROMIUM}", serial=ser)
        ok = clear_chromium_all_data(farm.adb, ser)
        out.append(f"{name}: clear={'ok' if ok else 'fail'} ({ser})")
    return out


def _tz_for_geo(geo: str) -> str:
    """Map 'City, Country' from isolation logs to IANA tz."""
    g = (geo or "").strip().lower()
    if not g:
        return ""
    try:
        from automation.phone_geo_time import GEO_CATALOG

        for loc in GEO_CATALOG:
            if loc.label.lower() == g or loc.city.lower() in g:
                return loc.tz
    except Exception:
        pass
    return ""


def _local_time_for_geo(geo: str) -> str:
    tz = _tz_for_geo(geo)
    if not tz:
        return ""
    try:
        from zoneinfo import ZoneInfo

        local = datetime.now(timezone.utc).astimezone(ZoneInfo(tz))
        return local.strftime("%H:%M") + f" {tz.split('/')[-1]}"
    except Exception:
        return ""


# Money-day MuMu index → inject port via CPharm discover (vmN → 8218+N).


def _inject_port_for(short: str) -> str:
    """Expected inject listen port for phone_N / vmN (no adb)."""
    try:
        from automation.farm_phone_discover import inject_port_for_name

        return str(inject_port_for_name(short))
    except Exception:
        pass
    s = str(short or "").split(".", 1)[0]
    try:
        if s.startswith("phone_"):
            n = int(s.rsplit("_", 1)[-1])
        elif s.startswith("vm"):
            n = int(s[2:].split(".", 1)[0])
        else:
            return ""
    except Exception:
        return ""
    return str(8218 + n) if 0 <= n <= 20 else ""


def _vm_index(short: str) -> int | None:
    m = re.match(r"^vm(\d+)$", str(short or "").split(".", 1)[0], re.I)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _read_json_obj(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _geo_by_serial_from_log() -> dict[str, str]:
    """Best-effort last GEO label per serial from farm_354.log (no ADB)."""
    if not FARM_LOG.is_file():
        return {}
    try:
        size = FARM_LOG.stat().st_size
        with FARM_LOG.open("rb") as fh:
            fh.seek(max(0, size - 250_000))
            chunk = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return {}
    out: dict[str, str] = {}
    for line in chunk.splitlines():
        # GEO 10.0.2.171:5555 -> Hong Kong, China tz=Asia/Hong_Kong ...
        m = re.search(
            r"GEO\s+(\d+\.\d+\.\d+\.\d+:\d+)\s+->\s+(.+?)\s+tz=",
            line,
        )
        if m:
            out[m.group(1)] = m.group(2).strip()
            continue
        m2 = re.search(
            r"geo apply serial=(\d+\.\d+\.\d+\.\d+:\d+)\s+place=(.+?)\s+tz=",
            line,
        )
        if m2:
            out[m2.group(1)] = m2.group(2).strip().rstrip(",")
    return out


def _phone_live_overlay() -> dict[str, dict[str, str]]:
    """Merge serial map + exit IPs + browser pkgs + ads_watch into per-short facts."""
    out: dict[str, dict[str, str]] = {}
    sm = _read_json_obj(SERIAL_MAP)
    phones = sm.get("phones") if isinstance(sm.get("phones"), dict) else {}
    inject = sm.get("inject") if isinstance(sm.get("inject"), dict) else {}
    for name, serial in phones.items():
        short = str(name).split(".", 1)[0]
        port = inject.get(name) or inject.get(short) or _inject_port_for(short)
        out[short] = {
            "serial": str(serial or ""),
            "inject_port": str(port or ""),
            "proxy": f"127.0.0.1:{port}" if port else "",
            "browser": "",
            "exit_ip": "",
            "geo": "",
        }
    exits = _read_json_obj(EXIT_IPS)
    in_use = exits.get("in_use") if isinstance(exits.get("in_use"), dict) else {}
    last_ex = exits.get("last") if isinstance(exits.get("last"), dict) else {}
    for short, row in list(out.items()):
        idx = _vm_index(short)
        if idx is None:
            continue
        ip = str(in_use.get(str(idx)) or last_ex.get(str(idx)) or "").strip()
        if ip:
            row["exit_ip"] = ip
    browsers = _read_json_obj(SERIAL_BROWSER)
    for short, row in out.items():
        ser = row.get("serial") or ""
        pkg = str(browsers.get(ser) or "").strip()
        if pkg:
            row["browser"] = pkg.rsplit(".", 1)[-1] if "." in pkg else pkg
    ads = _read_json_obj(ADS_WATCH)
    for ph in ads.get("phones") or []:
        if not isinstance(ph, dict):
            continue
        short = str(ph.get("name") or "").split(".", 1)[0]
        if not short:
            continue
        row = out.setdefault(
            short,
            {
                "serial": "",
                "inject_port": "",
                "proxy": "",
                "browser": "",
                "exit_ip": "",
                "geo": "",
            },
        )
        if ph.get("serial"):
            row["serial"] = str(ph.get("serial"))
        if ph.get("proxy") and "not found" not in str(ph.get("proxy")):
            row["proxy"] = str(ph.get("proxy"))
        fg = str(ph.get("fg") or "")
        browserish = (
            "chrome" in fg
            or "chromium" in fg
            or "firefox" in fg
            or "brave" in fg
            or "opera" in fg
            or "duckduckgo" in fg
        )
        if browserish:
            row["browser"] = fg.rsplit(".", 1)[-1]
    geos = _geo_by_serial_from_log()
    for short, row in out.items():
        ser = row.get("serial") or ""
        if ser and geos.get(ser):
            row["geo"] = geos[ser]
    return out


_GUEST_PROXY_CACHE: dict[str, Any] = {"ts": 0.0, "by_short": {}}


def _live_guest_proxy_by_short() -> dict[str, dict[str, str]]:
    """Best-effort live guest http_proxy + browser per vmN (cached 12s, hard 4s budget).

    Must never hang /api/status — dash was timing out when MuMu/ADB stalled.
    """
    now = time.time()
    if now - float(_GUEST_PROXY_CACHE.get("ts") or 0) < 12.0 and _GUEST_PROXY_CACHE.get(
        "by_short"
    ):
        return dict(_GUEST_PROXY_CACHE["by_short"])
    out: dict[str, dict[str, str]] = {}
    deadline = time.time() + 4.0
    try:
        from automation.adb_wrapper import AdbWrapper
        from automation.browse_proxy import (
            browser_package_for_serial,
            resolve_browser_package,
        )

        adb = AdbWrapper()
        # Prefer remembered pkgs + last-known serials from progress/panel — skip
        # MuMuFarmOps.refresh when under time pressure.
        serials: list[tuple[str, int]] = []
        try:
            from wizard.mumu_farm_ops import MuMuFarmOps

            if time.time() < deadline - 1.5:
                farm = MuMuFarmOps()
                farm.refresh_serials()
                for inst in farm.list_instances():
                    serial = str(getattr(inst, "adb_serial", "") or "")
                    idx = getattr(inst, "index", None)
                    if serial and idx is not None:
                        serials.append((serial, int(idx)))
        except Exception:
            serials = []
        if not serials:
            # Fallback: known MuMu ARM endpoints.
            serials = [
                ("10.0.2.61:5555", 0),
                ("10.0.2.136:5555", 1),
                ("10.0.2.133:5555", 2),
                ("10.0.2.28:5555", 3),
            ]
        for serial, idx in serials:
            if time.time() >= deadline:
                break
            short = f"vm{idx}"
            try:
                proxy = (
                    adb.shell(
                        "settings get global http_proxy",
                        serial=serial,
                        timeout=2.0,
                    ).stdout
                    or ""
                ).strip()
            except Exception:
                proxy = "?"
            pkg = ""
            try:
                pkg = browser_package_for_serial(serial) or ""
                if not pkg and time.time() < deadline:
                    pkg = resolve_browser_package(adb, serial) or ""
            except Exception:
                pkg = ""
            label = pkg.rsplit(".", 1)[-1] if pkg else "?"
            if "firefox" in pkg:
                label = "firefox"
            elif "duckduckgo" in pkg:
                label = "duckduckgo"
            elif "brave" in pkg:
                label = "brave"
            elif "chromium" in pkg or "chrome" in pkg:
                label = "chromium"
            out[short] = {"proxy": proxy or ":0", "browser": label, "serial": serial}
    except Exception:
        pass
    if out:
        _GUEST_PROXY_CACHE["ts"] = now
        _GUEST_PROXY_CACHE["by_short"] = out
    return dict(out)


def _progress_blob() -> dict[str, Any]:
    if not PROGRESS.is_file():
        return {}
    try:
        return json.loads(PROGRESS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _daily_budget_blob() -> dict[str, Any]:
    """Today's per-phone visits/ads from farm_daily_budget_state.json."""
    today = datetime.now().astimezone().date().isoformat()
    if not DAILY_BUDGET.is_file():
        return {"date": today, "phones": {}}
    try:
        raw = json.loads(DAILY_BUDGET.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {"date": today, "phones": {}}
    if not isinstance(raw, dict) or str(raw.get("date") or "") != today:
        return {"date": today, "phones": {}}
    phones = raw.get("phones") if isinstance(raw.get("phones"), dict) else {}
    return {"date": today, "phones": phones}


def _path3_daily_blob() -> dict[str, Any]:
    today = datetime.now().astimezone().date().isoformat()
    if not PATH3_DAILY.is_file():
        return {"date": today, "count": 0}
    try:
        raw = json.loads(PATH3_DAILY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {"date": today, "count": 0}
    if not isinstance(raw, dict) or str(raw.get("date") or "") != today:
        return {"date": today, "count": 0}
    try:
        count = max(0, int(raw.get("count") or 0))
    except (TypeError, ValueError):
        count = 0
    return {"date": today, "count": count}


def _operator_today() -> str:
    """Pacific calendar date — matches Mantis DAY buckets used by the farm."""
    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


def _default_mantis_today() -> dict[str, Any]:
    today = _operator_today()
    return {
        "date": today,
        "impressions": 0,
        "clicks": 0,
        "payout_usd": 0.0,
        "ecpm": 0.0,
        "evcpm": 0.0,
        "receivable_usd": None,
        "paid_to_date_usd": None,
        "lifetime_earnings_usd": None,
        "updated": None,
    }


def load_mantis_today() -> dict[str, Any]:
    """Operator / GraphQL Mantis numbers for today (dash totals)."""
    base = _default_mantis_today()
    today = base["date"]
    if not MANTIS_TODAY.is_file():
        return base
    try:
        raw = json.loads(MANTIS_TODAY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return base
    if not isinstance(raw, dict):
        return base
    # Keep showing last pull if file date matches Pacific today; otherwise blank.
    if str(raw.get("date") or "") != today:
        return base
    out = dict(base)
    for key in ("impressions", "clicks"):
        try:
            out[key] = max(0, int(raw.get(key) or 0))
        except (TypeError, ValueError):
            pass
    for key in ("payout_usd", "ecpm", "evcpm"):
        try:
            out[key] = float(raw.get(key) or 0)
        except (TypeError, ValueError):
            pass
    for key in ("receivable_usd", "paid_to_date_usd", "lifetime_earnings_usd"):
        if raw.get(key) is None or raw.get(key) == "":
            out[key] = None
            continue
        try:
            out[key] = float(raw.get(key))
        except (TypeError, ValueError):
            out[key] = None
    out["updated"] = raw.get("updated")
    out["source"] = raw.get("source")
    return out


def save_mantis_today(data: dict[str, Any]) -> dict[str, Any]:
    today = _operator_today()
    cur = load_mantis_today()
    out = {
        "date": today,
        "impressions": cur["impressions"],
        "clicks": cur["clicks"],
        "payout_usd": cur["payout_usd"],
        "ecpm": cur["ecpm"],
        "evcpm": cur["evcpm"],
        "receivable_usd": cur.get("receivable_usd"),
        "paid_to_date_usd": cur.get("paid_to_date_usd"),
        "lifetime_earnings_usd": cur.get("lifetime_earnings_usd"),
        "updated": _utc(),
    }
    if "impressions" in data:
        try:
            out["impressions"] = max(0, int(data.get("impressions") or 0))
        except (TypeError, ValueError):
            pass
    if "clicks" in data:
        try:
            out["clicks"] = max(0, int(data.get("clicks") or 0))
        except (TypeError, ValueError):
            pass
    for key in ("payout_usd", "ecpm", "evcpm"):
        if key in data:
            try:
                out[key] = float(data.get(key) or 0)
            except (TypeError, ValueError):
                pass
    for key in ("receivable_usd", "paid_to_date_usd", "lifetime_earnings_usd"):
        if key not in data:
            continue
        if data.get(key) is None or data.get(key) == "":
            out[key] = None
            continue
        try:
            out[key] = float(data.get(key))
        except (TypeError, ValueError):
            pass
    if data.get("source"):
        out["source"] = str(data.get("source"))
    MANTIS_TODAY.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    # True-up impressions/visit from Mantis actuals (stop pacing on a stale guess).
    try:
        visits = 0
        if DAILY_BUDGET.is_file():
            bud = json.loads(DAILY_BUDGET.read_text(encoding="utf-8"))
            phones = bud.get("phones") if isinstance(bud.get("phones"), dict) else {}
            for row in phones.values():
                if isinstance(row, dict):
                    visits += int(row.get("visits") or 0)
        impr = int(out.get("impressions") or 0)
        if visits >= 40 and impr > 0:
            live_ipv = round(impr / visits, 2)
            ov = _read_json_file(OVERRIDES)
            try:
                old = float(ov.get("CPHARM_FARM_IMPRESSIONS_PER_VISIT") or 22)
            except (TypeError, ValueError):
                old = 22.0
            # House-fill dilution days show live_ipv 80–120+. Never write that into
            # sticky — it fights the Jul-30 sweet spot (~13–22) and caps eCPM.
            SWEET_MAX = 28.0
            SWEET_MIN = 12.0
            if live_ipv > SWEET_MAX:
                log.warning(
                    "ipv true-up BLOCKED dilution live_ipv=%.2f (sweet<=%.0f) impr=%s visits=%s",
                    live_ipv,
                    SWEET_MAX,
                    impr,
                    visits,
                )
                if isinstance(ov, dict) and len(ov) >= 20:
                    ov["ipv_true_up"] = (
                        f"blocked {old}->{live_ipv} dilution; hold sweet-spot"
                    )
                    # Keep / restore sweet-spot ipv + modest EST target.
                    hold = old if SWEET_MIN <= old <= SWEET_MAX else 21.64
                    ov["CPHARM_FARM_IMPRESSIONS_PER_VISIT"] = str(hold)
                    ov["CPHARM_IPV_STICKY"] = str(hold)
                    ov["CPHARM_FARM_EST_IMPRESSIONS"] = "16000"
                    ov["updated"] = _utc()
                    OVERRIDES.write_text(
                        json.dumps(ov, indent=2) + "\n", encoding="utf-8"
                    )
            elif abs(old - live_ipv) >= 0.5:
                # Refuse to rewrite sticky from empty/partial reads — a {}
                # true-up previously wiped PATH3/UNIQUE/ALLOW_ADS money-day rails.
                if (
                    not isinstance(ov, dict)
                    or len(ov) < 20
                    or "CPHARM_FARM_PATH3" not in ov
                    or "CPHARM_FARM_UNIQUE_SEQ" not in ov
                ):
                    log.warning(
                        "ipv true-up skipped: sticky incomplete keys=%s",
                        len(ov) if isinstance(ov, dict) else -1,
                    )
                else:
                    capped = max(SWEET_MIN, min(SWEET_MAX, live_ipv))
                    ov["CPHARM_FARM_IMPRESSIONS_PER_VISIT"] = str(capped)
                    try:
                        # EST = plan target, not today's diluted volume.
                        ov["CPHARM_FARM_EST_IMPRESSIONS"] = str(
                            min(int(impr), 18000) if impr > 0 else 16000
                        )
                    except Exception:
                        pass
                    ov["updated"] = _utc()
                    ov["ipv_true_up"] = f"{old}->{capped} from mantis (raw={live_ipv})"
                    OVERRIDES.write_text(
                        json.dumps(ov, indent=2) + "\n", encoding="utf-8"
                    )
                # Mirror into panel env so Save doesn't wipe it.
                for panel_path in (PANEL, LOG_DIR / "farm_panel_state.json"):
                    if not panel_path.is_file():
                        continue
                    try:
                        panel = json.loads(panel_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError, TypeError):
                        continue
                    if not isinstance(panel, dict):
                        continue
                    env = panel.get("env") if isinstance(panel.get("env"), dict) else {}
                    hold_ipv = (
                        max(SWEET_MIN, min(SWEET_MAX, live_ipv))
                        if live_ipv <= SWEET_MAX
                        else (old if SWEET_MIN <= old <= SWEET_MAX else 21.64)
                    )
                    env["CPHARM_FARM_IMPRESSIONS_PER_VISIT"] = str(hold_ipv)
                    env["CPHARM_FARM_EST_IMPRESSIONS"] = "16000"
                    panel["env"] = env
                    panel_path.write_text(json.dumps(panel, indent=2), encoding="utf-8")
    except Exception as exc:
        log.debug("ipv true-up soft-fail: %s", exc)
    # Keep scorecard_api state in sync when present.
    try:
        from automation.scorecard_api import save_operator_mantis_state
        from wizard.wizard_paths import app_data_root

        recordings = app_data_root() / "automation" / "recordings"
        if not recordings.is_dir():
            recordings = ROOT / "automation" / "recordings"
        save_operator_mantis_state(
            recordings,
            {
                "date": today,
                "impressions": out["impressions"],
                "clicks": out["clicks"],
                "payout_usd": out["payout_usd"],
                "ecpm": out["ecpm"],
                "evcpm": out["evcpm"],
            },
        )
    except Exception:
        pass
    return out


def _day_totals(
    phone_rows: list[dict[str, Any]],
    *,
    panel: dict[str, Any],
    path3_count: int,
    mantis: dict[str, Any],
) -> dict[str, Any]:
    day_v = sum(int(r.get("day_visits") or 0) for r in phone_rows)
    day_a = sum(int(r.get("day_ads") or 0) for r in phone_rows)
    cap_v = sum(int(r.get("visits_cap") or 0) for r in phone_rows)
    cap_a = sum(int(r.get("ads_cap") or 0) for r in phone_rows)
    try:
        ipv = float(
            ((panel.get("env") or {}) if isinstance(panel.get("env"), dict) else {}).get(
                "CPHARM_FARM_IMPRESSIONS_PER_VISIT"
            )
            or 22
        )
    except (TypeError, ValueError):
        ipv = 22.0
    if ipv <= 0:
        ipv = 22.0
    est_impr = int(round(day_v * ipv))
    plan_impr = int(round(cap_v * ipv))
    m_impr = int(mantis.get("impressions") or 0)
    m_clicks = int(mantis.get("clicks") or 0)
    # When Mantis has numbers, those ARE the impressions — not visits×guess.
    if m_impr > 0:
        display_impr = m_impr
        impr_source = "mantis"
        impr_per_visit = (m_impr / day_v) if day_v > 0 else 0.0
        # Remaining-day pace uses live ipv (or assumed only if no visits yet).
        pace_ipv = impr_per_visit if impr_per_visit > 0 else ipv
        plan_impr = int(round(cap_v * pace_ipv)) if cap_v > 0 else plan_impr
        est_impr = display_impr
    else:
        display_impr = est_impr
        impr_source = "assumed"
        impr_per_visit = ipv if day_v else 0.0
    ctr = (m_clicks / m_impr * 100.0) if m_impr > 0 and m_clicks > 0 else 0.0
    vpc = (day_v / m_clicks) if m_clicks > 0 else None
    return {
        "farm_visits": day_v,
        "farm_visits_cap": cap_v,
        "farm_ads": day_a,
        "farm_ads_cap": cap_a,
        "farm_ads_left": max(0, cap_a - day_a),
        "path3_count": path3_count,
        "path3_cap": cap_a,
        "est_impressions": est_impr,
        "display_impressions": display_impr,
        "impressions_source": impr_source,
        "plan_impressions": plan_impr,
        "impressions_per_visit_assumed": ipv,
        "mantis_impressions": m_impr,
        "mantis_clicks": m_clicks,
        "mantis_payout_usd": float(mantis.get("payout_usd") or 0),
        "mantis_ecpm": float(mantis.get("ecpm") or 0),
        "mantis_evcpm": float(mantis.get("evcpm") or 0),
        "mantis_receivable_usd": (
            None
            if mantis.get("receivable_usd") is None
            else float(mantis.get("receivable_usd") or 0)
        ),
        "mantis_paid_to_date_usd": (
            None
            if mantis.get("paid_to_date_usd") is None
            else float(mantis.get("paid_to_date_usd") or 0)
        ),
        "mantis_lifetime_earnings_usd": (
            None
            if mantis.get("lifetime_earnings_usd") is None
            else float(mantis.get("lifetime_earnings_usd") or 0)
        ),
        "impressions_per_visit_live": round(impr_per_visit, 2),
        "ctr_impr_pct": round(ctr, 3),
        "visits_per_mantis_click": round(vpc, 1) if vpc is not None else None,
        "gap_mantis_minus_farm_ads": m_clicks - day_a,
        # Day profit targets — beat yesterday when we have a bar; else guidance floor.
        "target_profit_usd": float(TARGET_PROFIT_REALISTIC_USD),
        "target_profit_strong_usd": float(TARGET_PROFIT_STRONG_USD),
        "target_profit_stretch_usd": float(TARGET_PROFIT_STRETCH_USD),
        "yesterday_profit_usd": _yesterday_profit_usd(),
        "est_profit_today_usd": round(
            (
                (m_impr * float(mantis.get("ecpm") or 0) / 1000.0)
                if m_impr > 0 and float(mantis.get("ecpm") or 0) > 0
                else float(mantis.get("payout_usd") or 0)
            ),
            2,
        ),
    }


def _yesterday_profit_usd() -> float | None:
    """Pacific yesterday Mantis payout if we pulled it (beat-this bar)."""
    try:
        from datetime import timedelta

        yday = (
            datetime.now(ZoneInfo("America/Los_Angeles")).date() - timedelta(days=1)
        ).isoformat()
        path = LOG_DIR / f"mantis_day_{yday}.json"
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        return round(float(raw.get("payout_usd") or 0), 2)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _inject_proxy_alive() -> bool:
    return any(
        "run_mantis_inject_proxies" in str(p.get("cmd", ""))
        for p in (_ps_farm().get("processes") or [])
    )


def _cpharm_exe_running() -> bool:
    """True when CPharm.exe owns the farm (1.4.1+ — no python run_farm_354)."""
    try:
        import psutil

        for proc in psutil.process_iter(["name"]):
            if str(proc.info.get("name") or "").lower() == "cpharm.exe":
                return True
    except Exception:
        pass
    return False


def _farm_progress_fresh(max_age_s: float = 180.0) -> bool:
    """farm_354_progress.json updated recently, or has active sequences."""
    try:
        prog = _progress_blob()
        if prog.get("active_sequences") or prog.get("active_keys"):
            return True
        updated = str(prog.get("updated") or "")
        if not updated:
            return False
        from datetime import datetime, timezone

        ts = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        return age <= max_age_s
    except Exception:
        return False


def _farm_worker_alive(procs: list[dict[str, Any]] | None = None) -> bool:
    rows = procs if procs is not None else (_ps_farm().get("processes") or [])
    if any("run_farm_354" in str(p.get("cmd", "")) for p in rows):
        return True
    # EXE-owned farm: CPharm.exe + fresh progress / actives (no python worker).
    if not _cpharm_exe_running():
        return False
    if _farm_progress_fresh():
        return True
    # Belt-and-suspenders: live unique-seq actives mean the EXE farm is running
    # even if the progress timestamp parser hiccups.
    try:
        prog = _progress_blob()
        if prog.get("active_sequences") or prog.get("active_keys"):
            return True
    except Exception:
        pass
    return False


def _farm_owner_label(procs: list[dict[str, Any]] | None = None) -> str:
    rows = procs if procs is not None else (_ps_farm().get("processes") or [])
    py = any("run_farm_354" in str(p.get("cmd", "")) for p in rows)
    exe = _cpharm_exe_running()
    if exe and not py:
        return "CPharm.exe"
    if py and exe:
        return "python+CPharm.exe"
    if py:
        return "python"
    return "none"


def _monitor_payload() -> dict[str, Any]:
    """Auditor truth for the dash — what was found AND what was fixed."""
    text = ""
    try:
        text = (LOG_DIR / "FARM_MONITOR_NOW.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    last = _read_json_file(LOG_DIR / "FARM_MONITOR_LAST_FIX.json")
    heat = (LOG_DIR / "FARM_HEAT_DOWN.flag").is_file()
    crit = 0
    fixes_n = 0
    for ln in text.splitlines():
        if ln.startswith("critical="):
            try:
                parts = ln.replace("=", " ").split()
                for i, tok in enumerate(parts):
                    if tok == "critical" and i + 1 < len(parts):
                        crit = int(parts[i + 1])
                    if tok == "fixes" and i + 1 < len(parts):
                        fixes_n = int(parts[i + 1])
            except (TypeError, ValueError):
                pass
    return {
        "text": text.strip(),
        "heat_down": heat,
        "critical": crit,
        "fixes": fixes_n,
        "last_fix": last if isinstance(last, dict) else {},
    }


def _checkin_fallback_from_procs() -> dict[str, Any]:
    """Process-liveness fallback when gather_checkin is slow/hung.

    Prefer remediator FARM_HONEST_NOW so the dash never pretends only 2 phones
    are up while ADB is actually 6/6.
    """
    procs = _ps_farm().get("processes") or []
    farm_up = _farm_worker_alive(procs)
    cycles_up = any("run_farm_cycles" in str(p.get("cmd", "")) for p in procs)
    inject_up = any("run_mantis_inject_proxies" in str(p.get("cmd", "")) for p in procs)
    exe_up = _cpharm_exe_running()
    adb_online = None
    adb_expect = None
    honest_line = ""
    try:
        honest = (LOG_DIR / "FARM_HONEST_NOW.txt").read_text(encoding="utf-8", errors="replace")
        for ln in honest.splitlines()[:12]:
            if "ADB phones" in ln:
                honest_line = ln.strip()
                # e.g. "ADB phones 6/6 offline=0 | ..."
                parts = ln.replace("|", " ").split()
                for i, tok in enumerate(parts):
                    if tok == "phones" and i + 1 < len(parts) and "/" in parts[i + 1]:
                        a, _, b = parts[i + 1].partition("/")
                        adb_online = int(a)
                        adb_expect = int(b)
                        break
                break
    except (OSError, ValueError, TypeError):
        pass
    if farm_up:
        owner = "CPharm.exe" if exe_up and not any(
            "run_farm_354" in str(p.get("cmd", "")) for p in procs
        ) else "python"
        phone_bit = (
            f"Phones: {adb_online}/{adb_expect} ADB (remediator)"
            if adb_online is not None and adb_expect is not None
            else "Phones: (remediator pending)"
        )
        return {
            "ok": True,
            "error": "check-in deferred",
            "text": (
                f"Farm UP · {phone_bit} · owner={owner} · "
                f"cycles={'yes' if cycles_up else 'no'} · inject={'yes' if inject_up else 'no'}"
                + (f" · {honest_line}" if honest_line else "")
            ),
            "verdict": "up",
            "farm_up": True,
            "adb_online": adb_online,
            "expect_phones": adb_expect,
        }
    return {
        "ok": False,
        "error": "check-in deferred",
        "text": "Farm worker not running — check-in deferred",
        "verdict": "down",
        "farm_up": False,
    }


def _gather_checkin_sync() -> dict[str, Any]:
    try:
        from automation.farm_checkin import format_checkin, gather_checkin

        snap = gather_checkin()
        return {
            "ok": True,
            "verdict": snap.verdict,
            "text": format_checkin(snap),
            "farm_up": snap.farm_up,
            "adb_online": snap.adb_online,
            "expect_phones": snap.expect_phones,
            "start_phones": snap.start_phones,
            "cycle_ran": snap.cycle_ran,
            "cycle_ok": snap.cycle_ok,
            "cycle_fail": snap.cycle_fail,
            "path3_clicks": snap.path3_clicks,
            "ip_switches": snap.ip_switches,
            "proxies_ok": snap.proxies_ok,
            "proxies_total": snap.proxies_total,
            "proxy_bad": snap.proxy_bad,
            "per_phone": snap.per_phone_done,
            "deadline": snap.deadline_utc.isoformat() if snap.deadline_utc else None,
        }
    except Exception as exc:
        log.warning("checkin gather failed: %s", exc)
        return {
            "ok": False,
            "error": str(exc),
            "text": f"check-in unavailable: {exc}",
            "verdict": "error",
        }


def _checkin_bg_worker() -> None:
    try:
        result = _gather_checkin_sync()
        with _CHECKIN_CACHE["lock"]:
            _CHECKIN_CACHE["result"] = result
            _CHECKIN_CACHE["ts"] = time.time()
    finally:
        with _CHECKIN_CACHE["lock"]:
            _CHECKIN_CACHE["inflight"] = False


def _checkin_payload() -> dict[str, Any]:
    """Cached single-flight check-in — never stacks threads per /api/status poll."""
    now = time.time()
    with _CHECKIN_CACHE["lock"]:
        cached = _CHECKIN_CACHE.get("result")
        age = now - float(_CHECKIN_CACHE.get("ts") or 0)
        inflight = bool(_CHECKIN_CACHE.get("inflight"))
        if isinstance(cached, dict) and age < _CHECKIN_CACHE_TTL_S:
            return cached
        if not inflight:
            _CHECKIN_CACHE["inflight"] = True
            threading.Thread(
                target=_checkin_bg_worker, name="dash-checkin", daemon=True
            ).start()
        if isinstance(cached, dict) and age < _CHECKIN_STALE_OK_S:
            return cached
    return _checkin_fallback_from_procs()


def _overlay_live_gameplay(site: dict[str, Any], panel: dict[str, Any]) -> dict[str, Any]:
    """Site-meta is the gameplay rundown — must match sticky/overrides, not profile defaults.

    Profile catalog still supplies URL + sequence pool counts. Caps / pace / phones /
    browsers come from farm_runtime_overrides (+ farm_site_lock) so Visits 308/645
    and this bar never disagree.
    """
    out = dict(site) if isinstance(site, dict) else {}
    ov = _read_json_file(OVERRIDES)
    lock = _read_json_file(LOG_DIR / "farm_site_lock.json")
    env = panel.get("env") if isinstance(panel.get("env"), dict) else {}

    def _pick(*keys: str, default: str = "") -> str:
        for k in keys:
            for src in (ov, lock, env):
                if not isinstance(src, dict):
                    continue
                v = src.get(k)
                if v is not None and str(v).strip() != "":
                    return str(v).strip()
        return default

    visits = _pick(
        "CPHARM_FARM_DAILY_VISITS",
        "daily_visits_csv",
        default=str(out.get("daily_visits_csv") or ""),
    )
    ads = _pick(
        "CPHARM_FARM_DAILY_ADS",
        "daily_ads_csv",
        default=str(out.get("daily_ads_csv") or ""),
    )
    phones_csv = _pick("CPHARM_FARM_PHONES")
    phones = [str(p) for p in (panel.get("phones") or []) if p]
    if not phones:
        phones = [p.strip() for p in phones_csv.split(",") if p.strip()]
    # Cap CSVs to active phone count so rundown/metrics agree (no phantom slots).
    n = len(phones) if phones else 0
    if n > 0:
        v_list = [x.strip() for x in visits.split(",") if x.strip()]
        a_list = [x.strip() for x in ads.split(",") if x.strip()]
        if len(v_list) >= n:
            visits = ",".join(v_list[:n])
        if len(a_list) >= n:
            ads = ",".join(a_list[:n])
    ipv = _pick("CPHARM_IPV_STICKY", "CPHARM_FARM_IMPRESSIONS_PER_VISIT", default="22")
    seqs = _pick("CPHARM_FARM_SEQS_PER_HOUR", default="?")
    browsers = _pick("CPHARM_FARM_BROWSERS", default="chromium,firefox,brave")
    chrom_only = _pick("CPHARM_FARM_CHROMIUM_ONLY", default="0") != "0"
    unique = _pick("CPHARM_FARM_UNIQUE_SEQ", default="1") != "0"
    ntfy = _pick("CPHARM_NTFY_TOPIC", default=str(out.get("ntfy_topic") or "twskoops"))
    heat = (LOG_DIR / "FARM_HEAT_DOWN.flag").is_file()
    visit_sum = 0
    ad_sum = 0
    try:
        visit_sum = sum(int(float(x)) for x in visits.split(",") if x.strip())
    except (TypeError, ValueError):
        visit_sum = 0
    try:
        ad_sum = sum(int(float(x)) for x in ads.split(",") if x.strip())
    except (TypeError, ValueError):
        ad_sum = 0

    out["daily_visits_csv"] = visits
    out["daily_ads_csv"] = ads
    out["ntfy_topic"] = ntfy
    out["gameplay"] = {
        "phones_n": len(phones),
        "phones": phones,
        "visits_csv": visits,
        "ads_csv": ads,
        "visits_cap_sum": visit_sum,
        "ads_cap_sum": ad_sum,
        "seqs_per_hour": seqs,
        "ipv": ipv,
        "browsers": browsers,
        "chromium_only": chrom_only,
        "unique_seq": unique,
        "heat_down": heat,
        "ntfy_topic": ntfy,
        "source": "sticky" if (ov or lock) else "profile",
    }
    return out


def status_payload() -> dict[str, Any]:
    panel = load_panel()
    # Farm runtime overrides are source of truth for daily caps (autopilot /
    # ensure write these). Keep dash Done/Planned aligned with what farm runs.
    try:
        if OVERRIDES.is_file():
            ov = json.loads(OVERRIDES.read_text(encoding="utf-8"))
            if isinstance(ov, dict):
                env = panel.get("env") if isinstance(panel.get("env"), dict) else {}
                for key in (
                    "CPHARM_FARM_DAILY_VISITS",
                    "CPHARM_FARM_DAILY_ADS",
                    "CPHARM_FARM_ALLOW_ADS",
                    "CPHARM_FARM_PATHS",
                    "CPHARM_FARM_PATH3_DAILY_CAP",
                    "CPHARM_FARM_PATH3_GLOBAL_GAP_MIN",
                    "CPHARM_FARM_PATH3_PER_HOUR",
                    "CPHARM_BROWSE_PROXY_MODE",
                    "CPHARM_REQUIRE_UNIQUE_EXIT_IP",
                    "CPHARM_HUMAN_VARIATION",
                    "CPHARM_FARM_BROWSERS",
                    "CPHARM_DABFLOW_LOAD_WAIT",
                    "CPHARM_FARM_EVENING_SEQS_PER_HOUR",
                    "CPHARM_FARM_SEQS_PER_HOUR",
                    "CPHARM_FARM_IMPRESSIONS_PER_VISIT",
                    "CPHARM_IPV_STICKY",
                    "CPHARM_FARM_CHROMIUM_ONLY",
                    "CPHARM_FARM_PHONES",
                    "CPHARM_FARM_UNIQUE_SEQ",
                    "CPHARM_NTFY_TOPIC",
                ):
                    if key in ov and ov[key] not in (None, ""):
                        env[str(key)] = str(ov[key])
                panel["env"] = env
                phones = list(panel.get("phones") or DEFAULT_PHONES)
                vparts = [
                    p.strip()
                    for p in str(env.get("CPHARM_FARM_DAILY_VISITS") or "").split(",")
                    if p.strip()
                ]
                aparts = [
                    p.strip()
                    for p in str(env.get("CPHARM_FARM_DAILY_ADS") or "").split(",")
                    if p.strip()
                ]
                if vparts:
                    budgets = (
                        dict(panel["budgets"])
                        if isinstance(panel.get("budgets"), dict)
                        else {}
                    )
                    for i, name in enumerate(phones):
                        try:
                            vv = max(0, int(float(vparts[i if i < len(vparts) else -1])))
                        except (TypeError, ValueError, IndexError):
                            vv = int((budgets.get(name) or {}).get("visits") or 0)
                        try:
                            aa = max(
                                0,
                                int(float(aparts[i if i < len(aparts) else -1]))
                                if aparts
                                else 0,
                            )
                        except (TypeError, ValueError, IndexError):
                            aa = int((budgets.get(name) or {}).get("ads") or 0)
                        budgets[str(name)] = {"visits": vv, "ads": aa}
                    panel["budgets"] = budgets
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    ads = {}
    if ADS_WATCH.is_file():
        try:
            ads = json.loads(ADS_WATCH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            ads = {}
    procs = _ps_farm()
    proc_rows = procs.get("processes", []) or []
    farm_alive = _farm_worker_alive(proc_rows)
    farm_owner = _farm_owner_label(proc_rows)
    cycles_alive = any("run_farm_cycles" in str(p.get("cmd", "")) for p in proc_rows)
    inject_alive = any(
        "run_mantis_inject_proxies" in str(p.get("cmd", "")) for p in proc_rows
    )
    checkin = _checkin_payload()
    # EXE-owned farm: never leave check-in stuck on DOWN when CPharm is alive.
    if farm_alive and isinstance(checkin, dict) and not checkin.get("farm_up"):
        checkin = dict(checkin)
        checkin["farm_up"] = True
        checkin["ok"] = True
        if str(checkin.get("verdict") or "").upper() in {"", "DOWN", "UNKNOWN", "?"}:
            checkin["verdict"] = "UP"
        owner = farm_owner or "CPharm.exe"
        text = str(checkin.get("text") or "")
        if "DOWN" in text.upper() or not text.strip():
            checkin["text"] = (
                f"Farm check-in - UP (owner={owner}) · "
                "CPharm.exe in-process farm"
            )
    prog = _progress_blob()
    daily = _daily_budget_blob()
    daily_phones = daily.get("phones") if isinstance(daily.get("phones"), dict) else {}
    phones_prog = prog.get("phones") or {}
    panel_phones = list(panel.get("phones") or [])
    sticky_phones = _phones_from_sticky()
    if len(sticky_phones) >= len(panel_phones):
        panel_phones = sticky_phones
    if not panel_phones:
        panel_phones = list(DEFAULT_PHONES)
    # Keep panel in sync so checkboxes / budgets show all adaptive phones.
    if panel.get("phones") != panel_phones:
        panel = dict(panel)
        panel["phones"] = panel_phones
        try:
            PANEL.write_text(json.dumps(panel, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass
    budgets = panel.get("budgets") if isinstance(panel.get("budgets"), dict) else {}
    phone_rows: list[dict[str, Any]] = []
    live_overlay = _phone_live_overlay()
    live_proxy: dict[str, dict[str, str]] = {}
    for idx, name in enumerate(panel_phones):
        short = str(name).split(".")[0]
        blob = phones_prog.get(name) or phones_prog.get(short) or {}
        last = blob.get("last") if isinstance(blob, dict) else {}
        if not isinstance(last, dict):
            last = {}
        vm_i = _vm_index(short)
        day_key = str(vm_i) if vm_i is not None else str(idx)
        day_row = (
            daily_phones.get(day_key)
            if isinstance(daily_phones.get(day_key), dict)
            else (
                daily_phones.get(str(idx))
                if isinstance(daily_phones.get(str(idx)), dict)
                else {}
            )
        )
        try:
            day_visits = max(0, int(day_row.get("visits") or 0))
        except (TypeError, ValueError):
            day_visits = 0
        try:
            day_ads = max(0, int(day_row.get("ads") or 0))
        except (TypeError, ValueError):
            day_ads = 0
        # Prefer last entry's day counters when present (fresher mid-write).
        try:
            if last.get("day_visits") is not None:
                day_visits = max(day_visits, int(last.get("day_visits") or 0))
            if last.get("day_ads") is not None:
                day_ads = max(day_ads, int(last.get("day_ads") or 0))
        except (TypeError, ValueError):
            pass
        cap_row = budgets.get(name) if isinstance(budgets.get(name), dict) else {}
        if not cap_row and isinstance(budgets.get(short), dict):
            cap_row = budgets.get(short) or {}
        try:
            visits_cap = max(0, int(cap_row.get("visits") or 0))
        except (TypeError, ValueError):
            visits_cap = 0
        try:
            ads_cap = max(0, int(cap_row.get("ads") or 0))
        except (TypeError, ValueError):
            ads_cap = 0
        ov = live_overlay.get(short) or {}
        gp = live_proxy.get(short) if isinstance(live_proxy.get(short), dict) else {}
        ip_before = str(last.get("ip_before") or "").strip()
        ip_after = str(last.get("ip_after") or "").strip() or str(ov.get("exit_ip") or "").strip()
        geo = str(last.get("geo") or "").strip() or str(ov.get("geo") or "").strip()
        guest_proxy = (
            str(gp.get("proxy") or "").strip()
            or str(ov.get("proxy") or "").strip()
        )
        browser = (
            str(gp.get("browser") or "").strip()
            or str(ov.get("browser") or "").strip()
        )
        phone_rows.append(
            {
                "name": name,
                "short": short,
                "done": int(blob.get("done") or 0) if isinstance(blob, dict) else 0,
                "day_visits": day_visits,
                "day_ads": day_ads,
                "visits_cap": visits_cap,
                "ads_cap": ads_cap,
                "success": last.get("success"),
                "path3": bool(last.get("path3"))
                or str(last.get("sequence") or "").endswith("_ad")
                or str(last.get("sequence") or "").endswith("_ad_multi"),
                "ip_changed": bool(last.get("ip_changed")),
                "ip_before": ip_before,
                "ip_after": ip_after,
                "geo": geo,
                "local_time": _local_time_for_geo(geo),
                "tz": _tz_for_geo(geo),
                "elapsed_s": last.get("elapsed_s"),
                "sequence": last.get("sequence") or "",
                "inject_port": str(ov.get("inject_port") or _inject_port_for(short)),
                "guest_proxy": guest_proxy,
                "browser": browser,
                "serial": str(ov.get("serial") or gp.get("serial") or ""),
            }
        )
    active_seqs = list(prog.get("active_sequences") or [])
    active_keys = list(prog.get("active_keys") or [])
    active_path3 = [
        s
        for s in active_seqs
        if str(s).endswith("_ad") or str(s).endswith("_ad_multi")
    ]
    path3_blob = _path3_daily_blob()
    mantis = load_mantis_today()
    totals = _day_totals(
        phone_rows,
        panel=panel,
        path3_count=int(path3_blob.get("count") or 0),
        mantis=mantis,
    )
    try:
        live_mode = browse_proxy_mode()
    except Exception:
        live_mode = str((panel.get("env") or {}).get("CPHARM_BROWSE_PROXY_MODE") or "scramble")
    slug = str(
        panel.get("active_site_slug")
        or (panel.get("env") or {}).get("CPHARM_SITE_SLUG")
        or "dabflow"
    ).strip() or "dabflow"
    try:
        seed_builtin_profiles()
        site = site_info(slug, phones=list(panel.get("phones") or DEFAULT_PHONES)).to_dict()
        sites = list_farm_sites(phones=list(panel.get("phones") or DEFAULT_PHONES))
    except Exception as exc:
        log.warning("farm site info failed: %s", exc)
        site = {"slug": slug, "display_name": slug, "unique_sequences": True, "error": str(exc)}
        sites = []
    # Gameplay rundown = sticky truth (caps/pace/phones), not profile defaults.
    site = _overlay_live_gameplay(site, panel)
    unique_on = str((panel.get("env") or {}).get("CPHARM_FARM_UNIQUE_SEQ") or "1") != "0"
    money_mon: dict[str, Any] = {}
    try:
        from automation.farm_money_monitor import load_state as _money_mon_state

        money_mon = _money_mon_state() or {}
    except Exception as exc:
        money_mon = {"ok": False, "error": str(exc)}
    return {
        "panel": panel,
        "knobs": KNOBS,
        "default_phones": list(panel.get("phones") or _phones_from_sticky() or DEFAULT_PHONES),
        "farm_alive": farm_alive,
        "farm_owner": farm_owner,
        "cycles_alive": cycles_alive,
        "inject_alive": inject_alive,
        "browse_proxy_mode": live_mode,
        "processes": procs.get("processes", []),
        "ads_watch": ads,
        "money_monitor": money_mon,
        "monitor": _monitor_payload(),
        "checkin": checkin,
        "phone_rows": phone_rows,
        "totals": totals,
        "mantis_today": mantis,
        "path3_daily": path3_blob,
        "progress_updated": prog.get("updated"),
        "progress_deadline": prog.get("deadline"),
        "active_sequences": active_seqs,
        "active_keys": active_keys,
        "active_path3": active_path3,
        "active_path3_count": len(active_path3),
        "farm_log_tail": _tail(FARM_LOG, 40),
        "cmd_log": _cmd_console_lines(),
        "cycle_log_tail": _tail(CYCLE_LOG, 12),
        "panel_path": str(PANEL),
        "overrides_path": str(OVERRIDES),
        "ts": _utc(),
        "autopilot": _read_json_file(AUTOPILOT_STATE),
        "active_site_slug": slug,
        "site": site,
        "sites": sites,
        "unique_seq": {
            "enabled": unique_on,
            "active_keys": active_keys,
            "active_sequences": active_seqs,
            "used_stems_path": str(LOG_DIR / f"farm_used_stems_{slug}.json"),
        },
        "hint": (
            "Pull from Mantis steers the farm (overrides = visit/ad truth). "
            "Path3 follows Allow ads + paths (today: on when ALLOW_ADS=1). "
            "Only at ≥40 clicks with impr still short does autopilot freeze Path3. "
            "CDP FAIL on whisper door != sequence death."
            if slug == "dabflow"
            else (
                "LoansFlow farm · https://loansflow.loan/ · unique-seq ON · "
                "ntfy twskoops · daily visits/ads from site profile. "
                "AdSense warming — Path3 taps are sparse placeholders until ads live."
            )
        ),
    }


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>FamFlow Farm</title>
<style>
:root{
  --bg:#12151a; --panel:#1a1f27; --panel2:#222833; --line:#2e3642;
  --text:#e7ecf2; --muted:#8b97a8; --accent:#3d9a78; --accent2:#2f7d61;
  --warn:#c9a227; --err:#c45c5c; --ok:#3d9a78;
  --input:#0f1318; --focus:#4db892; --mono:ui-monospace,Consolas,monospace;
}
*{box-sizing:border-box}
body{margin:0;font-family:"Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--text);font-size:13px}
.shell{max-width:960px;margin:0 auto;padding:8px 10px 12px}
.top{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:6px}
h1{margin:0;font-size:15px;font-weight:650}
.verdict{font-weight:650;color:var(--ok)}
.verdict.bad{color:var(--err)}
.row{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.pill{padding:2px 7px;border:1px solid var(--line);border-radius:4px;font-size:11px;color:var(--muted);line-height:1.4}
.pill.on{border-color:var(--ok);color:var(--ok)}
.pill.off{border-color:var(--err);color:var(--err)}
.pill.warn{border-color:var(--warn);color:var(--warn)}
.site-bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:4px 0 8px;padding:6px 8px;background:var(--panel);border:1px solid var(--line);border-radius:6px}
.site-bar label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.site-bar select{background:var(--input);color:var(--text);border:1px solid var(--line);border-radius:4px;padding:4px 8px;font-size:12px}
.site-meta{font-size:11px;color:var(--muted);line-height:1.45;flex:1;min-width:200px}
.site-meta b{color:var(--text)}
.site-meta .tag{color:var(--warn);font-weight:650}
.site-meta .okish{color:var(--ok)}
/* Even stat tiles — never 8-across crunch; same column width every row */
.metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;margin:6px 0}
@media (min-width:520px){.metrics{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (min-width:720px){.metrics{grid-template-columns:repeat(4,minmax(0,1fr))}}
@media (min-width:980px){.metrics{grid-template-columns:repeat(5,minmax(0,1fr))}}
.metric{background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:6px 8px;text-align:center;min-width:0}
.metric .k{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.metric .v{font-size:14px;font-weight:650;line-height:1.25;margin-top:2px;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.gauge-board{display:flex;flex-direction:column;gap:8px;margin:8px 0}
.focal-stage{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(280px,1fr);gap:8px;align-items:stretch}
@media (max-width:980px){.focal-stage{grid-template-columns:1fr}}
.gauge-hero,.gauge-grid,#phoneWrap{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px 12px;position:relative;overflow:hidden}
.gauge-hero{border-color:rgba(61,154,120,.35);box-shadow:0 0 0 1px rgba(61,154,120,.08),0 8px 28px rgba(0,0,0,.25)}
.gauge-hero::before,.gauge-grid::before{content:"";position:absolute;inset:0;background:radial-gradient(ellipse 80% 60% at 50% 0%,rgba(61,154,120,.14),transparent 70%);pointer-events:none}
.gauge-hero h2,.gauge-grid h2,#phoneHead{margin:0 0 2px;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:650;position:relative}
.gauge-hero .sub,.gauge-grid .sub{font-size:11px;color:var(--muted);margin:0 0 8px;position:relative}
.conj-wrap{display:flex;align-items:flex-start;justify-content:center;gap:18px;flex-wrap:wrap;position:relative}
.conj-svg{width:min(320px,100%);height:auto;filter:drop-shadow(0 0 14px rgba(61,154,120,.22));flex:0 0 auto}
.conj-meta{min-width:180px;flex:1 1 220px;position:relative}
.conj-score{font-size:48px;font-weight:750;letter-spacing:-.03em;line-height:1;font-variant-numeric:tabular-nums}
.conj-score.green{color:var(--ok)} .conj-score.yellow{color:var(--warn)} .conj-score.red{color:var(--err)}
.conj-label{font-size:13px;font-weight:650;margin-top:4px}
.conj-bits{margin-top:10px;display:flex;flex-direction:column;gap:4px}
.conj-bit{display:flex;justify-content:space-between;gap:8px;font-size:11px;color:var(--muted);border-bottom:1px solid var(--line);padding-bottom:3px}
.conj-bit b{color:var(--text);font-weight:650;font-variant-numeric:tabular-nums}
.conj-bit .tag{font-size:10px;padding:1px 6px;border-radius:3px;border:1px solid var(--line)}
.conj-bit .tag.in{color:var(--ok);border-color:rgba(61,154,120,.45);background:rgba(61,154,120,.12)}
.conj-bit .tag.near{color:var(--warn);border-color:rgba(201,162,39,.45);background:rgba(201,162,39,.1)}
.conj-bit .tag.out{color:var(--err);border-color:rgba(196,92,92,.45);background:rgba(196,92,92,.1)}
.mini-gauges{display:grid;grid-template-columns:1fr;gap:6px;position:relative}
@media (min-width:900px){.mini-gauges{grid-template-columns:1fr 1fr}}
.vg{display:grid;grid-template-columns:72px 1fr;gap:8px 10px;align-items:center;padding:6px 0;border-bottom:1px solid var(--line)}
.vg:last-child{border-bottom:0}
@media (min-width:900px){.vg{border-bottom:1px solid var(--line)}.vg:nth-last-child(-n+2){border-bottom:0}}
.vg-lab{font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);line-height:1.25}
.vg-lab b{display:block;color:var(--text);font-size:13px;font-weight:700;font-variant-numeric:tabular-nums;margin-top:2px}
.vg-lab .delta{display:block;font-size:9px;margin-top:3px;font-weight:650}
.vg-lab .delta.up{color:var(--ok)}
.vg-lab .delta.down{color:var(--warn)}
.vg-lab .delta.flat{color:var(--muted)}
.vg-bars{display:flex;flex-direction:column;gap:4px;min-width:0}
.vg-row{display:grid;grid-template-columns:34px 1fr 64px;gap:6px;align-items:center}
.vg-row .tag{font-size:9px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.vg-track{height:12px;background:#1a2028;border-radius:3px;overflow:hidden;position:relative;border:1px solid var(--line)}
.vg-fill{height:100%;border-radius:2px;min-width:2px;transition:width .55s cubic-bezier(.2,.8,.2,1)}
.vg-fill.now{background:linear-gradient(90deg,#5a2a2a,#c45c5c)}
.vg-fill.now.ok{background:linear-gradient(90deg,#1e4a38,#3d9a78)}
.vg-fill.now.warn{background:linear-gradient(90deg,#5a4820,#c9a227)}
.vg-fill.fix{background:linear-gradient(90deg,#1a3d55,#4a9ec8);opacity:.95}
.vg-num{font-size:11px;font-weight:650;font-variant-numeric:tabular-nums;text-align:right;color:var(--text);white-space:nowrap}
.vg-num.fix{color:#8ec8e8}
.vg-band{grid-column:2 / -1;font-size:9px;color:var(--muted);margin-top:-1px}
.gauge-grid{display:flex;flex-direction:column}
.gauge-grid .sub{margin-bottom:6px}
.arc-track{stroke:#2a323e;fill:none;stroke-linecap:round}
.arc-sweet{stroke:rgba(61,154,120,.35);fill:none;stroke-linecap:butt}
.arc-val{fill:none;stroke-linecap:round;transition:stroke-dashoffset .7s cubic-bezier(.2,.8,.2,1), stroke .35s ease}
.needle{transition:transform .7s cubic-bezier(.2,.8,.2,1);transform-origin:100px 100px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:4px 6px}
table.phones{width:100%;border-collapse:collapse;font-size:12px}
table.phones th,table.phones td{padding:3px 5px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
table.phones th{color:var(--muted);font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.03em}
table.phones tr:last-child td{border-bottom:0}
#phoneWrap{margin:0;overflow:visible;display:flex;flex-direction:column;min-width:0}
#phoneHead{display:flex;justify-content:space-between;align-items:center;margin:0 0 8px;font-family:var(--mono);font-size:12px;text-transform:none;letter-spacing:0}
#phoneHead strong{color:var(--ok,#7dcea0)}
#phoneCards{display:flex;flex-direction:column;gap:6px}
.ph-card{background:var(--panel2);border:1px solid var(--line);border-radius:6px;padding:7px 8px;display:grid;gap:3px}
.ph-card .ph-top{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.ph-card .ph-name{font-weight:700;font-size:13px}
.ph-card .ph-stat{font-family:var(--mono);font-size:11px;color:var(--muted);white-space:nowrap}
.ph-card .ph-ip{font-family:var(--mono);font-size:12px;line-height:1.3;word-break:break-all}
.ph-card .ph-ip .from{color:var(--muted)}
.ph-card .ph-ip .arrow{color:var(--muted);margin:0 4px}
.ph-card .ph-geo{font-size:12px;line-height:1.3}
.ph-card .ph-geo .lt{color:var(--muted);font-family:var(--mono);font-size:11px;margin-left:6px}
.ph-card .ph-meta{font-family:var(--mono);font-size:10px;color:var(--muted);display:flex;flex-wrap:wrap;gap:6px 10px}
.ip{font-family:var(--mono);font-size:11px;white-space:nowrap}
.ip .from{color:var(--muted)}
.ip .arrow{color:var(--muted);margin:0 3px}
.geo{line-height:1.25}
.geo .loc{display:block}
.geo .lt{color:var(--muted);font-family:var(--mono);font-size:11px}
.btn{border:0;border-radius:4px;padding:4px 8px;font-weight:600;cursor:pointer;font-size:11px;line-height:1.3}
.btn.primary{background:var(--accent);color:#06140f}
.btn.primary:hover{background:var(--accent2)}
.btn.ghost{background:var(--panel2);color:var(--text);border:1px solid var(--line)}
.btn.danger{background:#5a2a2a;color:#f2dede;border:1px solid #7a3a3a}
.ok{color:var(--ok)} .bad{color:var(--err)} .warn{color:var(--warn)}
.one{margin:4px 0 0;font-family:var(--mono);font-size:11px;color:#c5d4cc;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#monitorBox{margin:6px 0 0;padding:6px 8px;background:#12161c;border:1px solid var(--line);border-radius:6px;font-family:var(--mono);font-size:11px;line-height:1.35;white-space:pre-wrap;color:#c5d4cc;max-height:160px;overflow:auto}
#monitorBox.heat{border-color:#a67c2a;color:#f0d9a0}
#monitorBox.crit{border-color:#8a3a3a;color:#f2dede}
.cmdbox{margin-top:6px;background:var(--panel);border:1px solid var(--line);border-radius:6px;overflow:hidden}
.cmdbox .cmdhead{display:flex;justify-content:space-between;align-items:center;padding:4px 8px;border-bottom:1px solid var(--line);font-size:11px;color:var(--muted)}
.cmdbox .cmdhead strong{color:var(--text);font-size:12px}
pre.cmd{background:#0a0d11;margin:0;padding:6px 8px;max-height:140px;overflow:auto;font-family:var(--mono);font-size:11px;line-height:1.35;white-space:pre-wrap;color:#b8c4b0}
.cmdrow{display:flex;gap:6px;padding:6px 8px;border-top:1px solid var(--line);background:var(--panel2)}
.cmdrow input{flex:1;background:var(--input);border:1px solid var(--line);color:var(--text);border-radius:4px;padding:6px 8px;font-size:12px;font-family:var(--mono)}
.cmdrow input:focus{outline:1px solid var(--focus);border-color:var(--focus)}
details.more{margin-top:8px;border:1px solid var(--line);border-radius:6px;background:var(--panel)}
details.more>summary{cursor:pointer;padding:6px 8px;font-weight:600;font-size:12px;color:var(--muted);list-style:none}
details.more>summary::-webkit-details-marker{display:none}
details.more[open]>summary{border-bottom:1px solid var(--line);color:var(--text)}
.more-body{padding:8px}
.tabs{display:flex;gap:6px;margin-bottom:8px}
.tab{background:transparent;border:1px solid var(--line);color:var(--muted);padding:4px 8px;border-radius:4px;cursor:pointer;font-size:11px}
.tab.active{border-color:var(--accent);color:var(--text);background:var(--panel2)}
.tab.stub{opacity:.65}
label{display:block;font-size:11px;color:var(--muted);margin-bottom:2px}
input[type=text],input[type=number],select{width:100%;background:var(--input);border:1px solid var(--line);color:var(--text);border-radius:4px;padding:5px 7px;font-size:12px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px}
.phone{display:flex;align-items:center;gap:5px;padding:4px 6px;background:var(--panel2);border:1px solid var(--line);border-radius:4px;font-size:11px}
.phone input{width:auto}
.field{margin-bottom:6px}
.group-title{margin:8px 0 4px;font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.actions{display:flex;gap:5px;flex-wrap:wrap;margin-top:8px}
.note{font-size:11px;color:var(--muted);line-height:1.35}
pre.log{background:var(--input);border:1px solid var(--line);border-radius:4px;padding:6px;max-height:120px;overflow:auto;font-size:10px;line-height:1.3;white-space:pre-wrap;margin:0}
.toast{position:fixed;right:10px;bottom:10px;background:var(--panel2);border:1px solid var(--line);padding:7px 10px;border-radius:4px;display:none;z-index:20;font-size:12px}
.wizard .step{background:var(--panel2);border:1px solid var(--line);border-radius:4px;padding:7px;margin-bottom:6px;font-size:12px}
</style>
</head>
<body>
<div class="shell">
  <div class="top">
    <h1>Farm <span class="verdict" id="verdict">…</span></h1>
    <div class="row" id="statusPills"></div>
    <div class="row">
      <button class="btn ghost" id="btnCheckinNtfy" type="button">ntfy</button>
      <button class="btn ghost" id="btnRefreshTop" type="button">↻</button>
      <button class="btn primary" id="btnClearRestart" type="button">Clear+restart</button>
      <button class="btn danger" id="btnStop" type="button">Stop</button>
    </div>
  </div>
  <div class="site-bar">
    <label for="sitePick">Site</label>
    <select id="sitePick" title="Farm target">
      <option value="dabflow">DabFlow</option>
      <option value="loansflow">LoansFlow</option>
    </select>
    <button class="btn ghost" id="btnApplySite" type="button" title="Apply site profile budgets + sequence root">Apply site</button>
    <div class="site-meta" id="siteMeta">Loading site…</div>
  </div>
  <div class="tabs" id="publisherTabs" style="margin:4px 0 2px">
    <button class="tab active" type="button" data-pub="mantis">Mantis</button>
    <button class="tab stub" type="button" data-pub="adsense" title="Same panels later">AdSense (later)</button>
    <button class="tab stub" type="button" data-pub="ezoic" title="Same panels later">Ezoic (later)</button>
    <button class="tab stub" type="button" data-pub="other" title="Same panels later">Other SSP (later)</button>
  </div>
  <p class="note" id="publisherNote" style="margin:0 0 6px">Publisher: Mantis (live pull). Other publishers plug into the same gauges later.</p>
  <div class="metrics" id="metrics"></div>
  <div class="gauge-board" id="gaugeBoard">
    <div class="focal-stage">
      <div class="gauge-hero">
        <h2>Farm health · $$</h2>
        <p class="sub">Focal dial — $ toward $100 · floor $40 · strong $55 · stretch $100</p>
        <p class="sub" id="goalLeftLine" style="margin-top:-4px;color:var(--text)">Left: —</p>
        <div class="conj-wrap">
          <svg class="conj-svg" viewBox="0 0 200 130" aria-label="Profit gauge">
            <defs>
              <linearGradient id="conjGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="#c45c5c"/>
                <stop offset="40%" stop-color="#c9a227"/>
                <stop offset="55%" stop-color="#c9a227"/>
                <stop offset="100%" stop-color="#3d9a78"/>
              </linearGradient>
            </defs>
            <path class="arc-track" d="M20 110 A80 80 0 0 1 180 110" stroke-width="14"/>
            <path d="M20 110 A80 80 0 0 1 180 110" fill="none" stroke="url(#conjGrad)" stroke-width="14" stroke-linecap="round" opacity=".35"/>
            <path id="conjArc" class="arc-val" d="M20 110 A80 80 0 0 1 180 110" stroke="url(#conjGrad)" stroke-width="14" stroke-dasharray="251.2" stroke-dashoffset="251.2"/>
            <g id="conjNeedle" class="needle">
              <line x1="100" y1="110" x2="100" y2="38" stroke="#e7ecf2" stroke-width="2.5" stroke-linecap="round"/>
              <circle cx="100" cy="110" r="5" fill="#e7ecf2"/>
            </g>
            <text x="18" y="126" fill="#8b97a8" font-size="9">$0</text>
            <text x="72" y="126" fill="#8b97a8" font-size="9">$40</text>
            <text x="108" y="126" fill="#8b97a8" font-size="9">$55</text>
            <text x="152" y="126" fill="#8b97a8" font-size="9">$100</text>
          </svg>
          <div class="conj-meta">
            <div class="conj-score" id="conjScore">—</div>
            <div class="conj-label" id="conjLabel">Waiting…</div>
            <div class="conj-bits" id="conjBits"></div>
          </div>
        </div>
      </div>
      <div id="phoneWrap">
        <div id="phoneHead"><strong id="phoneCount">Phones —</strong><span id="phoneHint">IP + location</span></div>
        <div id="phoneCards"></div>
        <p class="note" id="totalsLine" style="margin:6px 4px 2px">Totals loading…</p>
      </div>
    </div>
    <div class="gauge-grid">
      <h2>Secondary · pace</h2>
      <p class="sub">NOW vs AFTER CORRECTION — below the $$ focal; inform only</p>
      <div class="mini-gauges" id="miniGauges"></div>
    </div>
  </div>
  <div class="panel" style="margin-top:6px">
    <div class="row" style="gap:8px;flex-wrap:wrap;align-items:end">
      <div class="field" style="margin:0;min-width:110px">
        <label>Mantis impr</label>
        <input id="mantisImpr" type="number" min="0" step="1" placeholder="—" readonly title="Live from Mantis pull — not editable"/>
      </div>
      <div class="field" style="margin:0;min-width:90px">
        <label>Mantis clicks</label>
        <input id="mantisClicks" type="number" min="0" step="1" placeholder="—" readonly title="Live from Mantis pull — not editable"/>
      </div>
      <div class="field" style="margin:0;min-width:90px">
        <label>Payout $</label>
        <input id="mantisPayout" type="number" min="0" step="0.01" placeholder="—" readonly title="Live from Mantis pull — not editable"/>
      </div>
      <div class="field" style="margin:0;min-width:80px">
        <label>eCPM</label>
        <input id="mantisEcpm" type="number" min="0" step="0.01" placeholder="—" readonly title="Live from Mantis pull — not editable"/>
      </div>
      <div class="field" style="margin:0;min-width:80px">
        <label>evCPM</label>
        <input id="mantisEvcpm" type="number" min="0" step="0.01" placeholder="—" readonly title="Live from Mantis pull — not editable"/>
      </div>
      <div class="field" style="margin:0;min-width:100px">
        <label>Paid to date $</label>
        <input id="mantisPaidToDate" type="number" min="0" step="0.01" placeholder="0" readonly title="From Mantis: lifetime PAYOUT − balance"/>
      </div>
      <div class="field" style="margin:0;min-width:110px">
        <label>Receivable $</label>
        <input id="mantisReceivable" type="number" min="0" step="0.01" placeholder="0" readonly title="Mantis Property.balance (unpaid)"/>
      </div>
      <div class="field" style="margin:0;min-width:120px">
        <label>Target profit $</label>
        <input id="mantisTargetProfit" type="text" readonly title="Beat yesterday · floor $40 / strong $55 / stretch $100 (impr × eCPM, not click spam)"/>
      </div>
      <button class="btn primary" id="btnPullMantis" type="button">Pull from Mantis</button>
      <button class="btn ghost" id="btnSaveMantis" type="button" style="display:none" disabled title="Mantis totals are pull-only">Save Mantis</button>
      <label class="note" style="display:flex;align-items:center;gap:4px;margin:0">
        <input id="mantisAutoPull" type="checkbox" checked style="width:auto"/>
        auto every 15m
      </label>
      <span class="note" id="mantisHint">Pull → gauges + autopilot steer</span>
      <span class="note" id="autopilotHint" style="flex:1 1 100%"></span>
    </div>
  </div>
  <p class="one" id="checkinOne" title="">Loading…</p>
  <pre id="monitorBox" title="Auditor: finds AND fixes">MONITOR — waiting for remediator…</pre>

  <div class="cmdbox">
    <div class="cmdhead">
      <strong>Command → agent</strong>
      <span>ntfy wake · live farm log</span>
    </div>
    <pre class="cmd" id="cmdConsole">Waiting for farm…</pre>
    <div class="cmdrow">
      <input id="cmdInput" type="text" placeholder="Type a command for the agent (Enter to send)…" autocomplete="off"/>
      <button class="btn primary" id="btnCmdSend" type="button">Send</button>
    </div>
  </div>

  <details class="more">
    <summary>Controls · knobs · logs</summary>
    <div class="more-body">
      <div class="tabs">
        <button class="tab active" data-tab="full" type="button">Full</button>
        <button class="tab" data-tab="wizard" type="button">Wizard</button>
      </div>
      <div id="tab-full">
        <div class="grid3" id="phoneBox"></div>
        <div class="group-title">Daily budget / phone (visits · ad clicks)</div>
        <div id="budgetBox"></div>
        <p class="note" id="budgetMath" style="margin:4px 0 8px">Est. impressions = visits × ~22 · target ~12–20 ad clicks/day · ~30–45 visits/click</p>
        <div class="group-title">Cadence</div>
        <div class="grid2" id="knobs-cadence"></div>
        <div class="group-title">Ads</div>
        <div class="grid2" id="knobs-ads"></div>
        <div class="group-title">Identity / Tor / Inject</div>
        <div class="grid2" id="knobs-identity"></div>
        <div class="group-title">Timing</div>
        <div class="grid2" id="knobs-timing"></div>
        <div class="field" style="margin-top:8px">
          <label>Notes</label>
          <input id="notes" type="text" placeholder="Watch for…"/>
        </div>
        <div class="row" style="margin-top:4px">
          <span class="note" style="color:var(--ok)">24h day mode — table shows actual OK visits/ads today · caps idle when hit · midnight reset for tomorrow</span>
        </div>
      </div>
      <div id="tab-wizard" style="display:none" class="wizard">
        <div class="step"><strong>1.</strong> <button class="btn ghost" type="button" id="wizAllPhones">All 6 phones</button></div>
        <div class="step"><strong>2.</strong>
          <button class="btn ghost wizPreset" data-preset="calm" type="button">Calm</button>
          <button class="btn ghost wizPreset" data-preset="normal" type="button">Normal</button>
          <button class="btn ghost wizPreset" data-preset="heavy" type="button">Heavy</button>
        </div>
        <div class="step"><strong>3.</strong> <button class="btn ghost" type="button" id="wizAdsSafe">Ads-safe + inject</button></div>
      </div>
      <div class="actions">
        <button class="btn primary" id="btnSave" type="button">Save</button>
        <button class="btn primary" id="btnRestart" type="button">Restart</button>
        <button class="btn ghost" id="btnClear" type="button">Clear phones</button>
        <button class="btn ghost" id="btnRefresh" type="button">Refresh</button>
        <button class="btn ghost" id="btnReloadPanel" type="button">Reload knobs</button>
        <span id="dirtyHint" style="display:none;color:var(--warn);font-size:11px;font-weight:600">unsaved edits — Save to keep</span>
      </div>
      <p class="note" style="margin-top:6px"><code id="panelPath"></code> · <code id="overridesPath"></code></p>
      <div class="group-title">Active</div>
      <p class="note" id="activePath3">Path3 active now: 0</p>
      <pre class="log" id="activeLog"></pre>
      <div class="group-title">Processes</div>
      <pre class="log" id="procLog"></pre>
      <div class="group-title">Farm log</div>
      <pre class="log" id="farmLog"></pre>
      <div class="group-title">Ads watch</div>
      <pre class="log" id="adsLog"></pre>
    </div>
  </details>
</div>
<div class="toast" id="toast"></div>
<script>
let STATE = null;
let PANEL_LOADED = false;
let PANEL_DIRTY = false;
const GROUPS = ['cadence','ads','identity','timing'];

function markDirty(){
  PANEL_DIRTY = true;
  const el = document.getElementById('dirtyHint');
  if(el) el.style.display = 'inline';
}

function clearDirty(){
  PANEL_DIRTY = false;
  const el = document.getElementById('dirtyHint');
  if(el) el.style.display = 'none';
}

function toast(msg){
  const t = document.getElementById('toast');
  t.textContent = msg; t.style.display='block';
  setTimeout(()=>t.style.display='none', 3200);
}

function phoneChecks(selected){
  const box = document.getElementById('phoneBox');
  box.innerHTML = '';
  (STATE.default_phones||[]).forEach(p=>{
    const d=document.createElement('label'); d.className='phone';
    const c=document.createElement('input'); c.type='checkbox'; c.value=p; c.checked=selected.includes(p);
    d.appendChild(c); d.appendChild(document.createTextNode(p.split('.')[0]));
    box.appendChild(d);
  });
}

function renderBudgets(panel){
  const box=document.getElementById('budgetBox');
  if(!box) return;
  box.innerHTML='';
  const budgets=(panel && panel.budgets)||{};
  let totV=0, totA=0;
  (STATE.default_phones||[]).forEach(p=>{
    const b=budgets[p]||{};
    const row=document.createElement('div');
    row.className='row';
    row.style.cssText='align-items:center;gap:8px;margin-bottom:4px';
    const name=document.createElement('span');
    name.textContent=p.split('.')[0];
    name.style.cssText='width:44px;font-family:var(--mono);font-size:11px;color:var(--muted)';
    row.appendChild(name);
    [['visits','visits',b.visits],['ads','ad clicks',b.ads]].forEach(([field,lab,val])=>{
      const wrap=document.createElement('div');
      wrap.className='field';
      wrap.style.cssText='margin:0;flex:1';
      const l=document.createElement('label'); l.textContent=lab; wrap.appendChild(l);
      const inp=document.createElement('input');
      inp.type='number'; inp.min='0'; inp.step='1';
      inp.value=(val===undefined||val===null)?'':val;
      inp.className='budget';
      inp.dataset.phone=p; inp.dataset.field=field;
      wrap.appendChild(inp); row.appendChild(wrap);
      if(field==='visits') totV += Number(val||0);
      if(field==='ads') totA += Number(val||0);
    });
    box.appendChild(row);
  });
  const math=document.getElementById('budgetMath');
  if(math){
    const ipv=Number((panel.env&&panel.env.CPHARM_FARM_IMPRESSIONS_PER_VISIT)||22)||22;
    const impr=Math.round(totV*ipv);
    const vpc=totA>0?Math.round(totV/totA):'—';
    const ctr=impr>0&&totA>0?((totA/impr)*100).toFixed(2)+'%':'—';
    math.textContent=`Plan: ${totV} visits/day · ~${impr} impr (@${ipv}/visit) · ${totA} ad clicks · ~${vpc} visits/click · est CTR ${ctr}`;
  }
}

function knobEl(k, val){
  const wrap=document.createElement('div'); wrap.className='field';
  const lab=document.createElement('label'); lab.textContent=k.label; wrap.appendChild(lab);
  let input;
  if(k.type==='toggle'){
    input=document.createElement('select');
    ;[['1','On'],['0','Off']].forEach(([v,l])=>{
      const o=document.createElement('option'); o.value=v; o.textContent=l; if(String(val)===v)o.selected=true; input.appendChild(o);
    });
  } else if(k.type==='select'){
    input=document.createElement('select');
    (k.options||[]).forEach(v=>{ const o=document.createElement('option'); o.value=v; o.textContent=v; if(String(val)===v)o.selected=true; input.appendChild(o); });
  } else {
    input=document.createElement('input'); input.type=k.type==='number'?'number':'text'; input.value=val??'';
  }
  input.dataset.key=k.key; input.className='knob'; wrap.appendChild(input); return wrap;
}

function renderKnobs(panel){
  GROUPS.forEach(g=>{ const el=document.getElementById('knobs-'+g); if(el) el.innerHTML=''; });
  (STATE.knobs||[]).forEach(k=>{
    const host=document.getElementById('knobs-'+k.group); if(!host) return;
    host.appendChild(knobEl(k, (panel.env||{})[k.key]));
  });
}

function collectPanel(){
  const phones=[...document.querySelectorAll('#phoneBox input:checked')].map(x=>x.value);
  const env={};
  document.querySelectorAll('.knob').forEach(el=>{ env[el.dataset.key]=el.value; });
  const budgets={};
  document.querySelectorAll('.budget').forEach(el=>{
    const p=el.dataset.phone; if(!p) return;
    budgets[p]=budgets[p]||{visits:0,ads:0};
    budgets[p][el.dataset.field]=parseInt(el.value||'0',10)||0;
  });
  return {
    phones,
    forever: true,
    hours: 0,
    notes: document.getElementById('notes').value||'',
    env,
    budgets,
    active_site_slug: document.getElementById('sitePick').value||'dabflow',
  };
}

function applyPanel(panel){
  phoneChecks(panel.phones||[]);
  renderBudgets(panel);
  renderKnobs(panel);
  document.getElementById('notes').value=panel.notes||'';
  document.getElementById('panelPath').textContent=STATE.panel_path;
  document.getElementById('overridesPath').textContent=STATE.overrides_path;
  const slug=panel.active_site_slug||(panel.env||{}).CPHARM_SITE_SLUG||'dabflow';
  const pick=document.getElementById('sitePick');
  if(pick && [...pick.options].some(o=>o.value===slug)) pick.value=slug;
  // Re-bind dirty tracking after knobs/phones are rebuilt.
  document.querySelectorAll('#phoneBox input, .knob, .budget, #notes, #sitePick').forEach(el=>{
    el.removeEventListener('change', markDirty);
    el.removeEventListener('input', markDirty);
    el.addEventListener('change', markDirty);
    el.addEventListener('input', markDirty);
  });
  clearDirty();
  PANEL_LOADED = true;
}

function metric(k,v){
  const t = esc(String(v??''));
  return '<div class="metric" title="'+esc(k)+': '+t+'"><div class="k">'+esc(k)+'</div><div class="v">'+t+'</div></div>';
}

function esc(s){
  return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

/** Map value onto 0..1 across [min,max]. */
function _norm(v, min, max){
  if(max<=min) return 0;
  return Math.max(0, Math.min(1, (Number(v||0)-min)/(max-min)));
}

/** Score how deep inside a sweet band [lo,hi] (1=center, 0=outside). Soft falloff outside. */
function _bandScore(v, lo, hi, hardMin, hardMax){
  v = Number(v||0);
  if(v>=lo && v<=hi){
    const mid=(lo+hi)/2, half=(hi-lo)/2 || 1;
    return 0.75 + 0.25*(1-Math.abs(v-mid)/half);
  }
  if(v<lo){
    const span=Math.max(1e-6, lo-(hardMin??0));
    return Math.max(0, 0.75*((v-(hardMin??0))/span));
  }
  const span=Math.max(1e-6, (hardMax??hi*1.5)-hi);
  return Math.max(0, 0.75*(1-(v-hi)/span));
}

function _arcPath(){ return 'M20 110 A80 80 0 0 1 180 110'; }
const ARC_LEN = 251.2; // pi*80 approx for semicircle

function _fmtNum(v, money){
  v = Number(v||0);
  if(!v && v!==0) return '—';
  if(money) return '$'+v.toFixed(2);
  if(v>=1000) return Math.round(v).toLocaleString();
  return String(Math.round(v*100)/100);
}

/** Vertical NOW vs FIX compare row. */
function _vgHtml(id, label, nowTxt, fixTxt, deltaTxt, deltaCls, bandTxt){
  return '<div class="vg" id="'+id+'">'+
    '<div class="vg-lab">'+esc(label)+'<b id="'+id+'-nowtxt">'+esc(nowTxt)+'</b>'+
      '<span class="delta '+(deltaCls||'flat')+'" id="'+id+'-delta">'+esc(deltaTxt||'')+'</span></div>'+
    '<div class="vg-bars">'+
      '<div class="vg-row"><span class="tag">now</span><div class="vg-track" id="'+id+'-nowtrack"><div class="vg-fill now" id="'+id+'-now" style="width:0%"></div></div><span class="vg-num" id="'+id+'-nownum">'+esc(nowTxt)+'</span></div>'+
      '<div class="vg-row"><span class="tag">fix</span><div class="vg-track" id="'+id+'-fixtrack"><div class="vg-fill fix" id="'+id+'-fix" style="width:0%"></div></div><span class="vg-num fix" id="'+id+'-fixnum">'+esc(fixTxt)+'</span></div>'+
      '<div class="vg-band" id="'+id+'-band">'+esc(bandTxt||'')+'</div>'+
    '</div></div>';
}

function _setVg(id, nowV, fixV, scaleMax, nowTxt, fixTxt, deltaTxt, deltaCls, bandTxt, nowTone){
  const max = Math.max(1e-6, Number(scaleMax)||1);
  const nw = Math.max(0, Math.min(100, (Number(nowV||0)/max)*100));
  const fw = Math.max(0, Math.min(100, (Number(fixV||0)/max)*100));
  const nowEl = document.getElementById(id+'-now');
  const fixEl = document.getElementById(id+'-fix');
  if(nowEl){
    nowEl.style.width = nw.toFixed(1)+'%';
    nowEl.className = 'vg-fill now'+(nowTone==='ok'?' ok':(nowTone==='warn'?' warn':''));
  }
  if(fixEl) fixEl.style.width = fw.toFixed(1)+'%';
  const set=(sid,v)=>{ const n=document.getElementById(sid); if(n) n.textContent=v; };
  set(id+'-nowtxt', nowTxt);
  set(id+'-nownum', nowTxt);
  set(id+'-fixnum', fixTxt);
  set(id+'-band', bandTxt||'');
  const d=document.getElementById(id+'-delta');
  if(d){ d.textContent=deltaTxt||''; d.className='delta '+(deltaCls||'flat'); }
}

function _setArc(arcId, needleId, t, color){
  t = Math.max(0, Math.min(1, t));
  const arc = document.getElementById(arcId);
  const needle = document.getElementById(needleId);
  if(arc){
    arc.style.strokeDashoffset = String(ARC_LEN * (1-t));
    if(color) arc.style.stroke = color;
  }
  if(needle){
    // semicircle: -90deg (left) to +90deg (right)
    needle.style.transform = 'rotate(' + (-90 + t*180) + 'deg)';
  }
}

function _tone(score){
  if(score >= 0.72) return {cls:'green', color:'#3d9a78', label:'STRETCH ZONE'};
  if(score >= 0.45) return {cls:'yellow', color:'#c9a227', label:'CHASING $$'};
  return {cls:'red', color:'#c45c5c', label:'UNDER FLOOR'};
}

function _bit(name, txt, kind){
  return '<div class="conj-bit"><span>'+esc(name)+'</span><span><b>'+esc(txt)+'</b> <span class="tag '+kind+'">'+esc(kind.toUpperCase())+'</span></span></div>';
}

function _kindFromScore(s){
  if(s>=0.72) return 'in';
  if(s>=0.4) return 'near';
  return 'out';
}

function _kindFromPayout(p, floor, strong){
  if(p >= strong) return 'in';
  if(p >= floor) return 'near';
  return 'out';
}

function renderGauges(s){
  const t = s.totals || {};
  const m = s.mantis_today || {};
  const g = (s.site && s.site.gameplay) || {};
  const box = document.getElementById('miniGauges');
  if(!box) return;
  if(box.dataset.ready !== 'vg2'){
    box.innerHTML =
      _vgHtml('gImpr','Impressions','—','—','','flat','sweet 15–18k') +
      _vgHtml('gClk','Ad clicks','—','—','','flat','sweet 20–40') +
      _vgHtml('gEcpm','eCPM','—','—','','flat','need ≥ $0.15 · aim higher') +
      _vgHtml('gEvcpm','evCPM','—','—','','flat','need ≥ $2.00');
    box.dataset.ready = 'vg2';
  }

  // Operator money goals on the gauge (ignore catch-up target_profit_* which may be $100).
  const floorUsd = 40;
  const strongUsd = 55;
  const stretchUsd = 100;

  const impr = Number(t.mantis_impressions || m.impressions || 0);
  const clk = Number(t.mantis_clicks || m.clicks || 0);
  const ecpm = Number(t.mantis_ecpm || m.ecpm || 0);
  const evcpm = Number(t.mantis_evcpm || m.evcpm || 0);
  const visits = Number(t.farm_visits || 0);
  const payout = Number(t.mantis_payout_usd || m.payout_usd || 0);
  const estPay = (impr>0 && ecpm>0) ? (impr*ecpm/1000) : payout;
  const pay = estPay > 0 ? estPay : payout;

  // AFTER CORRECTION targets from sticky gameplay + money rails.
  // AFTER CORRECTION: sticky ipv × visit cap (not diluted live day-pace).
  const stickyPlan = (Number(g.visits_cap_sum) || Number(t.farm_visits_cap) || 0) * Number(g.ipv || 21.64);
  const planImpr = (stickyPlan > 0 && stickyPlan < 40000) ? stickyPlan : 16500;
  const fixImpr = Math.min(18000, Math.max(15000, planImpr)); // land in sweet
  const adsCap = Number(g.ads_cap_sum || t.farm_ads_cap || 0);
  const fixClk = adsCap > 0 ? Math.min(40, Math.max(20, Math.round(adsCap * 0.55))) : 28;
  // Paying SSP path: cut house dilution → eCPM/evCPM recover toward money floor.
  const needEcpmForFloor = (floorUsd / Math.max(1, fixImpr)) * 1000;
  const fixEcpm = Math.max(ecpm, Math.min(2.5, Math.max(0.35, needEcpmForFloor)));
  const fixEvcpm = Math.max(2.0, evcpm < 2 ? 2.2 : evcpm);
  const fixPay = (fixImpr * fixEcpm) / 1000;

  const sImpr = _bandScore(impr, 15000, 18000, 0, 50000);
  let sClk;
  if(clk>=20 && clk<=40) sClk = _bandScore(clk, 20, 40, 0, 60);
  else if(clk<20) sClk = _bandScore(clk, 20, 40, 0, 60) * 0.9;
  else sClk = Math.max(0, 1 - (clk-40)/40) * 0.5;
  const sEcpm = ecpm<=0 ? 0 : (ecpm>=0.15 ? Math.min(1, 0.55 + (ecpm-0.15)/1.5) : Math.max(0, ecpm/0.15)*0.4);
  const sEvcpm = evcpm<=0 ? 0 : (evcpm>=2 ? Math.min(1, 0.7+(evcpm-2)/4) : (evcpm>=1 ? 0.35+0.3*(evcpm-1) : evcpm/1*0.35));
  const sVis = _bandScore(visits, 560, 660, 0, 800);
  const sPay = Math.max(0, Math.min(1, pay / Math.max(1e-6, stretchUsd)));
  const conj = (sPay*0.70 + sImpr*0.10 + sEcpm*0.10 + sEvcpm*0.07 + sClk*0.03);
  const tone = _tone(conj);

  const toneOf = (sc)=> sc>=0.72 ? 'ok' : (sc>=0.4 ? 'warn' : '');
  const dImpr = impr - fixImpr;
  const dClk = fixClk - clk;
  const dEcpm = fixEcpm - ecpm;
  const dEvcpm = fixEvcpm - evcpm;

  _setVg('gImpr', impr, fixImpr, Math.max(impr, fixImpr, 20000),
    _fmtNum(impr), _fmtNum(fixImpr),
    dImpr>500 ? ('cut '+_fmtNum(dImpr)+' (kill house spam)') : (Math.abs(dImpr)<=500?'in sweet':'raise pace'),
    dImpr>500 ? 'down' : (Math.abs(dImpr)<=500?'flat':'up'),
    'sweet 15–18k · plan '+_fmtNum(planImpr)+' · heat-down ipv '+(g.ipv||'—'),
    toneOf(sImpr));
  _setVg('gClk', clk, fixClk, Math.max(clk, fixClk, 50),
    _fmtNum(clk), _fmtNum(fixClk),
    dClk>0 ? ('+'+_fmtNum(dClk)+' Path3 toward cap '+(adsCap||'—')) : (dClk<0?'trim click spam':'hold band'),
    dClk>0 ? 'up' : (dClk<0?'down':'flat'),
    'sweet 20–40 · ads cap '+(adsCap||'—'),
    toneOf(sClk));
  _setVg('gEcpm', ecpm, fixEcpm, Math.max(ecpm, fixEcpm, 1.5),
    _fmtNum(ecpm, true), _fmtNum(fixEcpm, true),
    dEcpm>0.01 ? ('+$'+dEcpm.toFixed(2)+' if paying SSP fills') : 'hold',
    dEcpm>0.01 ? 'up' : 'flat',
    '≥ $0.15 · $$ at fix ≈ $'+fixPay.toFixed(2)+'/day',
    toneOf(sEcpm));
  _setVg('gEvcpm', evcpm, fixEvcpm, Math.max(evcpm, fixEvcpm, 5),
    _fmtNum(evcpm, true), _fmtNum(fixEvcpm, true),
    dEvcpm>0.05 ? ('+$'+dEvcpm.toFixed(2)+' to quality floor') : 'at/above floor',
    dEvcpm>0.05 ? 'up' : 'flat',
    'need ≥ $2.00 · corrections cut dilution',
    toneOf(sEvcpm));

  // Needle tracks money-first conjunction; score reads as $ toward stretch.
  _setArc('conjArc','conjNeedle', conj, null);
  const scoreEl = document.getElementById('conjScore');
  const labelEl = document.getElementById('conjLabel');
  if(scoreEl){
    scoreEl.textContent = '$'+pay.toFixed(0);
    scoreEl.className = 'conj-score '+tone.cls;
  }
  const leftTo = (goal)=>{
    const g0 = Number(goal)||0;
    const rem = Math.max(0, g0 - pay);
    if(pay >= g0) return 'hit $'+g0.toFixed(0);
    return '$'+rem.toFixed(2)+' to $'+g0.toFixed(0);
  };
  if(labelEl){
    const pct = Math.round(sPay*100);
    labelEl.textContent = tone.label+' · '+pct+'% of $'+stretchUsd.toFixed(0)+' · floor $'+floorUsd.toFixed(0)+' / strong $'+strongUsd.toFixed(0)+
      ' · fix≈$'+fixPay.toFixed(0);
  }
  const leftEl = document.getElementById('goalLeftLine');
  if(leftEl){
    leftEl.textContent =
      'Left: '+leftTo(floorUsd)+' · '+leftTo(strongUsd)+' · '+leftTo(stretchUsd)+
      '  (today $'+pay.toFixed(2)+' · after-fix ≈ $'+fixPay.toFixed(2)+')';
  }

  const bits = document.getElementById('conjBits');
  if(bits){
    const paid = t.mantis_paid_to_date_usd;
    const recv = t.mantis_receivable_usd;
    const paidTxt = (paid==null || paid==='') ? '—' : ('$'+Number(paid).toFixed(2));
    const recvTxt = (recv==null || recv==='') ? '—' : ('$'+Number(recv).toFixed(2));
    bits.innerHTML =
      _bit('Est $ today', '$'+pay.toFixed(2)+' / $'+stretchUsd.toFixed(0), _kindFromPayout(pay, floorUsd, strongUsd)) +
      _bit('After correction ≈', '$'+fixPay.toFixed(2), _kindFromPayout(fixPay, floorUsd, strongUsd)) +
      _bit('Left to $'+floorUsd.toFixed(0)+' (floor)', leftTo(floorUsd), pay>=floorUsd?'in':'out') +
      _bit('Left to $'+strongUsd.toFixed(0)+' (strong)', leftTo(strongUsd), pay>=strongUsd?'in':(pay>=floorUsd?'near':'out')) +
      _bit('Left to $'+stretchUsd.toFixed(0)+' (stretch)', leftTo(stretchUsd), pay>=stretchUsd?'in':(pay>=strongUsd?'near':'out')) +
      _bit('Impr NOW → FIX', _fmtNum(impr)+' → '+_fmtNum(fixImpr), _kindFromScore(sImpr)) +
      _bit('Clicks NOW → FIX', clk+' → '+fixClk, _kindFromScore(sClk)) +
      _bit('eCPM NOW → FIX', '$'+ecpm.toFixed(2)+' → $'+fixEcpm.toFixed(2), _kindFromScore(sEcpm)) +
      _bit('evCPM NOW → FIX', '$'+evcpm.toFixed(2)+' → $'+fixEvcpm.toFixed(2), _kindFromScore(sEvcpm)) +
      _bit('Visits', visits+' / cap '+(g.visits_cap_sum||t.farm_visits_cap||'—'), _kindFromScore(sVis)) +
      _bit('Yesterday $', (t.yesterday_profit_usd==null)?'—':('$'+Number(t.yesterday_profit_usd).toFixed(2)), 'in') +
      _bit('Paid to date', paidTxt, (Number(paid||0)>0)?'in':'near') +
      _bit('Receivable', recvTxt, (Number(recv||0)>=50)?'in':(Number(recv||0)>0?'near':'out'));
  }
}

function renderCheckin(s){
  const c = s.checkin || {};
  const t = s.totals || {};
  const v = document.getElementById('verdict');
  const raw = String(c.verdict || '').toLowerCase();
  const label = (raw==='healthy'||raw==='up') ? (raw||'up')
    : (raw==='down'||raw==='error') ? raw
    : (s.farm_alive ? 'up' : (raw || '?'));
  v.textContent = label;
  const good = label==='healthy' || label==='up';
  v.className = 'verdict' + (good ? '' : ' bad');
  const one = (c.text||c.error||'').replace(/\n/g,' · ');
  const el = document.getElementById('checkinOne');
  el.textContent = one;
  el.title = c.text || '';
  const mon = s.monitor || {};
  const mb = document.getElementById('monitorBox');
  if(mb){
    const heat = !!mon.heat_down;
    const crit = Number(mon.critical||0);
    mb.className = crit>0 ? 'crit' : (heat ? 'heat' : '');
    mb.textContent = mon.text || (
      'MONITOR — no FARM_MONITOR_NOW yet · heat_down='+heat+
      ' · last_fixes='+((mon.last_fix&&mon.last_fix.fixes)||[]).length
    );
  }
  const dayV = t.farm_visits ?? 0;
  const capV = t.farm_visits_cap ?? 0;
  const dayA = t.farm_ads ?? 0;
  const capA = t.farm_ads_cap ?? 0;
  const mImpr = t.mantis_impressions ?? 0;
  const mClk = t.mantis_clicks ?? 0;
  const disp = (mImpr > 0) ? mImpr : (t.display_impressions ?? t.est_impressions ?? 0);
  const plan = t.plan_impressions ?? 0;
  const src = t.impressions_source || (mImpr > 0 ? 'mantis' : 'assumed');
  const imprLabel = src === 'mantis' ? 'Mantis impr' : 'Impr (paced)';
  document.getElementById('metrics').innerHTML = [
    metric('Visits', dayV + (capV?('/'+capV):'')),
    metric(imprLabel, disp ? disp.toLocaleString() : '—'),
    metric('Day pace', plan ? plan.toLocaleString() : '—'),
    metric('Farm ads', dayA+(capA?('/'+capA):'')+(t.farm_ads_left!=null?(' left '+t.farm_ads_left):'')),
    metric('Mantis clicks', mClk || '—'),
    metric('Paid to date', (t.mantis_paid_to_date_usd==null)?'—':('$'+Number(t.mantis_paid_to_date_usd).toFixed(2))),
    metric('Receivable', (t.mantis_receivable_usd==null)?'—':('$'+Number(t.mantis_receivable_usd).toFixed(2))),
    metric('Target $', '$'+Number(t.target_profit_usd||40).toFixed(0)+' · $'+Number(t.target_profit_strong_usd||55).toFixed(0)+' · $'+Number(t.target_profit_stretch_usd||100).toFixed(0)),
    metric('Est $ today', (t.est_profit_today_usd!=null)?('$'+Number(t.est_profit_today_usd).toFixed(2)):'—'),
    metric('OK/Fail/P3', (c.cycle_ok!=null?c.cycle_ok:(dayV||'—'))+'/'+(c.cycle_fail!=null?c.cycle_fail:'—')+'/'+(t.path3_count??c.path3_clicks??'—')),
  ].join('');
  const gap = t.gap_mantis_minus_farm_ads;
  const line = document.getElementById('totalsLine');
  if(line){
    const paid = t.mantis_paid_to_date_usd;
    const recv = t.mantis_receivable_usd;
    line.textContent =
      'TOTALS today · visits '+dayV+(capV?('/'+capV):'')+
      ' · farm ads '+dayA+(capA?('/'+capA):'')+
      ' · Path3 '+ (t.path3_count??0)+'/'+(t.path3_cap??capA)+
      ' · '+imprLabel+' '+Number(disp||0).toLocaleString()+
      (plan?(' · day pace '+Number(plan).toLocaleString()):'')+
      ' · clicks '+mClk+
      (paid!=null?(' · paid $'+Number(paid).toFixed(2)):'')+
      (recv!=null?(' · receivable $'+Number(recv).toFixed(2)):'')+
      ' · target $'+Number(t.target_profit_usd||40).toFixed(0)+'–$'+Number(t.target_profit_strong_usd||55).toFixed(0)+
      ' · stretch $'+Number(t.target_profit_stretch_usd||100).toFixed(0)+
      (t.yesterday_profit_usd!=null?(' · beat yesterday $'+Number(t.yesterday_profit_usd).toFixed(2)):'')+
      (t.est_profit_today_usd!=null?(' · est today $'+Number(t.est_profit_today_usd).toFixed(2)):'')+
      (t.visits_per_mantis_click!=null?(' · '+t.visits_per_mantis_click+' visits/click'):'')+
      (gap!=null?(' · gap Mantis−farm ads='+gap):'');
  }
  const m = s.mantis_today || {};
  const set = (id,val)=>{ const n=document.getElementById(id); if(n && document.activeElement!==n) n.value = (val||val===0)?val:''; };
  set('mantisImpr', m.impressions);
  set('mantisClicks', m.clicks);
  set('mantisPayout', m.payout_usd);
  set('mantisEcpm', m.ecpm);
  set('mantisEvcpm', m.evcpm);
  set('mantisPaidToDate', m.paid_to_date_usd);
  set('mantisReceivable', m.receivable_usd);
  const tp = document.getElementById('mantisTargetProfit');
  if(tp) tp.value = '$'+Number(t.target_profit_usd||40).toFixed(0)+' / strong $'+Number(t.target_profit_strong_usd||55).toFixed(0)+' / stretch $'+Number(t.target_profit_stretch_usd||100).toFixed(0)+(t.yesterday_profit_usd!=null?(' · beat yday $'+Number(t.yesterday_profit_usd).toFixed(2)):'');
  const hint = document.getElementById('mantisHint');
  if(hint) hint.textContent = m.updated ? ('saved '+String(m.updated).replace('T',' ').slice(0,19)+(m.source?(' · '+m.source):'')) : 'Pull → gauges + autopilot';
  const ap = s.autopilot || {};
  const apEl = document.getElementById('autopilotHint');
  if(apEl){
    const reason = ap.last_move_reason || ap.last_reason || ap.reason || '';
    const when = ap.last_move_at || ap.updated || ap.last_apply_at || ap.last_restart_at || '';
    apEl.textContent = reason
      ? ('Autopilot: '+String(reason).slice(0,120)+(when?(' · '+String(when).replace('T',' ').slice(0,19)):''))
      : 'Autopilot: idle (Pull or 2–3h worker steers when gauges leave green)';
  }
  renderGauges(s);
}

function renderPhones(s){
  const box = document.getElementById('phoneCards');
  if(!box) return;
  box.innerHTML = '';
  const rows = s.phone_rows||[];
  const head = document.getElementById('phoneCount');
  const hint = document.getElementById('phoneHint');
  const c = s.checkin||{};
  const adb = (c.adb_online!=null && c.expect_phones!=null)
    ? (c.adb_online+'/'+c.expect_phones+' ADB')
    : (rows.length+' rows');
  if(head) head.textContent = 'Phones '+adb;
  rows.forEach(r=>{
    const card=document.createElement('div');
    card.className='ph-card';
    const last = r.success===true ? '<span class="ok">OK</span>' : (r.success===false ? '<span class="bad">FAIL</span>' : '<span class="warn">…</span>');
    const before = esc(r.ip_before||'—');
    const after = esc(r.ip_after||'—');
    const ipCls = r.ip_changed ? 'ok' : '';
    const loc = esc(r.geo||'—');
    const lt = esc(r.local_time||'');
    const visits = (r.day_visits!=null ? r.day_visits : r.done);
    const vCap = r.visits_cap||0;
    const clicks = (r.day_ads!=null ? r.day_ads : 0);
    const aCap = r.ads_cap||0;
    const nTxt = vCap>0 ? (visits+'/'+vCap) : String(visits??0);
    const cTxt = aCap>0 ? (clicks+'/'+aCap) : String(clicks??0);
    const proxy = esc(r.guest_proxy||(':'+(r.inject_port||'?')));
    const browser = esc(r.browser||'—');
    card.innerHTML =
      '<div class="ph-top">'+
        '<span class="ph-name">'+esc(r.short)+' '+last+(r.path3?' <span class="warn">P3</span>':'')+'</span>'+
        '<span class="ph-stat" title="visits / ads today">'+esc(nTxt)+' · ads '+esc(cTxt)+'</span>'+
      '</div>'+
      '<div class="ph-ip" title="Tor exit IP in → out">'+
        '<span class="from">'+before+'</span><span class="arrow">→</span><span class="'+ipCls+'">'+after+'</span>'+
      '</div>'+
      '<div class="ph-geo"><span class="loc">'+loc+'</span>'+(lt?'<span class="lt">'+lt+'</span>':'')+'</div>'+
      '<div class="ph-meta"><span>'+browser+'</span><span>'+proxy+'</span></div>';
    box.appendChild(card);
  });
  if(hint) hint.textContent = (s.farm_alive?'farm UP':'farm ?')+' · IP in→out + geo';
  document.getElementById('activeLog').textContent = (s.active_sequences||[]).map(n=>{
    const stem=String(n||'');
    const p3 = stem.endsWith('_ad') || stem.endsWith('_ad_multi');
    return (p3 ? '[P3] ' : '[P1/2] ') + stem;
  }).join('\\n') || '(idle)';
  const p3n = s.active_path3_count || 0;
  const activeMeta = document.getElementById('activePath3');
  if(activeMeta) activeMeta.textContent = 'Path3 active now: ' + p3n;
  const cmd = document.getElementById('cmdConsole');
  if(cmd){
    const atBottom = cmd.scrollTop + cmd.clientHeight >= cmd.scrollHeight - 24;
    cmd.textContent = (s.cmd_log||s.farm_log_tail||[]).join('\\n') || '(quiet)';
    if(atBottom) cmd.scrollTop = cmd.scrollHeight;
  }
}

function renderStatus(s){
  const pills=document.getElementById('statusPills');
  pills.innerHTML='';
  const mk=(label,on,warn)=>{ const p=document.createElement('span'); p.className='pill '+(warn?'warn':(on?'on':'off')); p.textContent=label+(on?'':'!'); pills.appendChild(p); };
  const site=s.site||{};
  mk('day', true);
  mk(site.display_name||s.active_site_slug||'site', true);
  mk('unique-seq', !!(s.unique_seq&&s.unique_seq.enabled!==false));
  mk('farm', s.farm_alive);
  mk('inj', s.inject_alive);
  const mode = String(s.browse_proxy_mode || ((s.panel||{}).env||{}).CPHARM_BROWSE_PROXY_MODE || '?');
  mk('proxy:'+mode, true, mode==='tor');
  const c=s.checkin||{};
  if(c.proxy_bad && c.proxy_bad.length) mk('guest', false, true);
  else if(c.proxies_total) mk('guest '+c.proxies_ok+'/'+c.proxies_total, true);
  const meta=document.getElementById('siteMeta');
  if(meta){
    const u=s.unique_seq||{};
    const g=site.gameplay||{};
    const keys=(u.active_keys||[]).length;
    const seqs=(u.active_sequences||[]).length;
    const phonesN = g.phones_n || (s.default_phones||[]).length || '?';
    const visitCap = g.visits_cap_sum || '';
    const adCap = g.ads_cap_sum || '';
    const heat = g.heat_down ? '<span class="tag">heat-down</span> · ' : '';
    const uniq = (g.unique_seq!==false && u.enabled!==false) ? '<span class="okish">unique ON</span>' : '<span class="tag">unique OFF</span>';
    const brows = g.chromium_only ? 'chromium' : (g.browsers||'?');
    meta.innerHTML =
      '<b>'+esc(site.display_name||s.active_site_slug||'?')+'</b> · '+
      esc(site.url||'')+
      ' · phones '+phonesN+
      ' · seqs/hr '+esc(String(g.seqs_per_hour||'?'))+
      ' · ipv '+esc(String(g.ipv||'?'))+
      ' · '+esc(brows)+
      ' · '+uniq+
      ' · '+heat+
      'visits '+esc(g.visits_csv||site.daily_visits_csv||'?')+(visitCap?(' (cap '+visitCap+')'):'')+
      ' · ads '+esc(g.ads_csv||site.daily_ads_csv||'?')+(adCap?(' (cap '+adCap+')'):'')+
      ' · pool P1/P2/P3 '+[site.path1_count||0,site.path2_count||0,site.path3_count||0].join('/')+
      ' · live locks '+seqs+' seq / '+keys+' keys'+
      ' · ntfy '+esc(g.ntfy_topic||site.ntfy_topic||'—');
    meta.title = 'Gameplay rundown (sticky). Metrics visit/ad caps must match these CSVs.';
  }
  const pick=document.getElementById('sitePick');
  if(pick && s.active_site_slug && [...pick.options].some(o=>o.value===s.active_site_slug)){
    if(!PANEL_DIRTY) pick.value=s.active_site_slug;
  }
  renderCheckin(s);
  renderPhones(s);
  document.getElementById('procLog').textContent = (s.processes||[]).map(p=>p.pid+'  '+p.cmd).join('\\n') || '(none)';
  document.getElementById('farmLog').textContent = (s.farm_log_tail||[]).join('\\n');
  const ads=s.ads_watch||{};
  const mm=s.money_monitor||{};
  const bottom =
    (ads.bottom_ads_visible===true) ? ('BOTTOM_AD_PAINT='+
      (ads.bottom_ads_chromium_ok??'?')+'/'+(ads.bottom_ads_chromium_total??'?')+
      ' (NOT phone count)'+
      (ads.bottom_ads_missing&&ads.bottom_ads_missing.length?(' missing_paint='+ads.bottom_ads_missing.join(',')) : ''))
    : (ads.bottom_ads_visible===false ? 'BOTTOM_AD_PAINT=NO' : 'BOTTOM_AD_PAINT=—');
  const flatLine = mm.flat
    ? ('FLAT_$ ALERT '+ (mm.flat_minutes??'?')+'m $'+ (mm.payout_usd??'?')
       +' paying='+((mm.ssp||{}).paying??'?')+' house='+((mm.ssp||{}).house??'?'))
    : ('flat_$=ok $'+(mm.payout_usd??'—')+' paying='+((mm.ssp||{}).paying??'—'));
  document.getElementById('adsLog').textContent =
    bottom+
    '\n'+flatLine+
    '\nfarm_alive='+ads.farm_alive+
    '\nmantis_fail='+(ads.mantis_fail_window??'—')+
    ' (CDP noise OK)'+
    '\nmantis_ok='+(ads.mantis_ok_window??'—')+
    (ads.ts?('\nts='+ads.ts):'');
}

async function refresh(opts){
  const forcePanel = !!(opts && opts.forcePanel);
  try{
    const r=await fetch('/api/status', {cache:'no-store'});
    if(!r.ok) throw new Error('status '+r.status);
    STATE=await r.json();
  } catch(e){
    toast('status refresh failed: '+e);
    return;
  }
  // Never clobber knobs mid-edit — live poll only updates status/phones/logs.
  if(!PANEL_LOADED || forcePanel){
    applyPanel(STATE.panel);
  } else if(STATE.panel_path){
    document.getElementById('panelPath').textContent=STATE.panel_path;
    document.getElementById('overridesPath').textContent=STATE.overrides_path;
  }
  renderStatus(STATE);
  try{ renderGauges(STATE); } catch(_e){}
}

async function post(url, body){
  const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
  const j=await r.json();
  if(!r.ok || j.ok===false) throw new Error(j.error||'request failed');
  return j;
}

document.querySelectorAll('.tab').forEach(btn=>{
  btn.addEventListener('click',()=>{
    document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    const tab=btn.dataset.tab;
    document.getElementById('tab-full').style.display = tab==='full'?'block':'none';
    document.getElementById('tab-wizard').style.display = tab==='wizard'?'block':'none';
  });
});

document.getElementById('btnSave').onclick=async()=>{
  try{ await post('/api/save', collectPanel()); clearDirty(); toast('Saved'); await refresh({forcePanel:true}); }
  catch(e){ toast(String(e)); }
};
document.getElementById('btnRestart').onclick=async()=>{
  try{ await post('/api/restart', collectPanel()); clearDirty(); toast('Restarted'); await refresh({forcePanel:true}); }
  catch(e){ toast(String(e)); }
};
document.getElementById('btnClearRestart').onclick=async()=>{
  try{
    toast('Clearing…');
    await post('/api/clear', collectPanel());
    const j=await post('/api/restart', collectPanel());
    clearDirty();
    toast('Cleared + restart pid='+(j.pid||'?'));
    await refresh({forcePanel:true});
  } catch(e){ toast(String(e)); }
};
document.getElementById('btnStop').onclick=async()=>{
  try{ await post('/api/stop', {}); toast('Stopped'); await refresh(); }
  catch(e){ toast(String(e)); }
};
document.getElementById('btnApplySite').onclick=async()=>{
  const slug=document.getElementById('sitePick').value||'dabflow';
  try{
    toast('Applying '+slug+'…');
    await post('/api/site', {slug, reset_budgets:true});
    clearDirty();
    toast(slug+' site applied (Save+Clear+restart to run)');
    await refresh({forcePanel:true});
  } catch(e){ toast(String(e)); }
};
document.getElementById('btnClear').onclick=async()=>{
  try{ const j=await post('/api/clear', collectPanel()); toast((j.results||[]).join(' | ')); await refresh(); }
  catch(e){ toast(String(e)); }
};
document.getElementById('btnRefresh').onclick=()=>refresh({forcePanel:!PANEL_DIRTY});
document.getElementById('btnRefreshTop').onclick=()=>refresh();
document.getElementById('btnReloadPanel').onclick=()=>refresh({forcePanel:true});
document.getElementById('btnCheckinNtfy').onclick=async()=>{
  try{ await post('/api/checkin_ntfy', {}); toast('ntfy sent'); await refresh(); }
  catch(e){ toast(String(e)); }
};
document.getElementById('btnSaveMantis').onclick=async()=>{
  const num=(id)=>{ const v=document.getElementById(id).value; return v===''?0:Number(v); };
  try{
    await post('/api/mantis_today', {
      impressions: num('mantisImpr'),
      clicks: num('mantisClicks'),
      payout_usd: num('mantisPayout'),
      ecpm: num('mantisEcpm'),
      evcpm: num('mantisEvcpm'),
    });
    toast('Mantis totals saved');
    await refresh();
  } catch(e){ toast(String(e)); }
};
document.getElementById('btnPullMantis').onclick=async()=>{
  const hint=document.getElementById('mantisHint');
  try{
    if(hint) hint.textContent='Pulling from Mantis account…';
    toast('Pulling Mantis…');
    const j=await post('/api/mantis_pull', {});
    const ap=(j.autopilot||{});
    const steered=ap.applied ? ' · autopilot steered' : '';
    toast('Mantis pulled · '+((j.mantis_today||{}).impressions||'?')+' impr / '+((j.mantis_today||{}).clicks||'?')+' clicks'+steered);
    await refresh();
  } catch(e){
    toast(String(e));
    if(hint) hint.textContent='Pull failed — '+String(e);
  }
};

let _mantisAutoTimer=null;
function _armMantisAuto(){
  if(_mantisAutoTimer){ clearInterval(_mantisAutoTimer); _mantisAutoTimer=null; }
  const on=document.getElementById('mantisAutoPull');
  if(!on || !on.checked) return;
  _mantisAutoTimer=setInterval(async()=>{
    try{
      await post('/api/mantis_pull', {});
      await refresh();
      toast('Mantis auto-pulled');
    } catch(e){
      console.warn('mantis auto-pull', e);
    }
  }, 15*60*1000);
}
document.getElementById('mantisAutoPull').onchange=_armMantisAuto;
// First auto-pull ~45s after load (let farm status settle), then every 15m.
setTimeout(async()=>{
  const on=document.getElementById('mantisAutoPull');
  if(on && on.checked){
    try{ await post('/api/mantis_pull', {}); await refresh(); } catch(_e){}
  }
}, 45000);
_armMantisAuto();

async function sendCmd(){
  const inp = document.getElementById('cmdInput');
  const text = (inp.value||'').trim();
  if(!text) return;
  try{
    await post('/api/cmd', {text});
    inp.value = '';
    toast('Sent to agent via ntfy');
    await refresh();
  } catch(e){ toast(String(e)); }
}
document.getElementById('btnCmdSend').onclick = () => sendCmd();
document.getElementById('cmdInput').addEventListener('keydown', (e)=>{
  if(e.key==='Enter'){ e.preventDefault(); sendCmd(); }
});
document.getElementById('wizAllPhones').onclick=()=>{
  document.querySelectorAll('#phoneBox input').forEach(c=>c.checked=true);
  markDirty();
  toast('All 6');
};
document.getElementById('wizAdsSafe').onclick=()=>{
  // Ad inject/patch/CDP settings are HARDCODED in save_panel — not knobs.
  const set=(k,v)=>{ const el=document.querySelector('.knob[data-key="'+k+'"]'); if(el) el.value=v; };
  set('CPHARM_FARM_ALLOW_ADS','1');
  set('CPHARM_FARM_PATHS','1,2,3');
  set('CPHARM_EMULATOR_AD_FILL_WAIT','2.0');
  set('CPHARM_BROWSE_PROXY_MODE','scramble');
  set('CPHARM_REQUIRE_UNIQUE_EXIT_IP','1');
  markDirty();
  toast('Ads-safe + scramble preset (Save)');
};
document.querySelectorAll('.wizPreset').forEach(btn=>{
  btn.onclick=()=>{
    const p=btn.dataset.preset;
    // Cadence is derived from per-phone daily visits/ads — presets only tweak budgets.
    const mul = p==='calm' ? 0.75 : (p==='heavy' ? 1.25 : 1.0);
    document.querySelectorAll('input.budget').forEach(el=>{
      const cur=parseInt(el.value||'0',10)||0;
      const next=el.dataset.field==='ads'
        ? Math.max(0, Math.round(cur*mul))
        : Math.max(1, Math.round(cur*mul));
      el.value=String(next);
    });
    markDirty();
    toast(p+' (daily budgets)');
  };
});

document.querySelectorAll('#publisherTabs .tab').forEach(btn=>{
  btn.addEventListener('click', ()=>{
    const slug = btn.dataset.pub || '';
    const stub = btn.classList.contains('stub');
    document.querySelectorAll('#publisherTabs .tab').forEach(t=>t.classList.remove('active'));
    btn.classList.add('active');
    const note = document.getElementById('publisherNote');
    if(stub){
      if(note) note.textContent = 'Publisher '+slug+' not wired yet — same gauge panels later (PublisherProvider stub).';
      toast(slug+' later — Mantis stays live');
      return;
    }
    if(note) note.textContent = 'Publisher: Mantis (live pull via /api/mantis_pull). Other SSPs share the same panels later.';
  });
});

refresh();
setInterval(refresh, 10000);
</script>
</body>
</html>
"""


@app.get("/")
def index():
    return render_template_string(HTML)


@app.get("/api/status")
def api_status():
    return jsonify(status_payload())


@app.get("/api/publishers")
def api_publishers():
    """Publisher tab payload — Mantis live; others stubbed for later plug-in."""
    try:
        from automation.publisher_providers import publishers_payload

        return jsonify(publishers_payload())
    except Exception as exc:
        log.warning("api/publishers failed: %s", exc)
        return jsonify(
            {
                "ok": True,
                "active": "mantis",
                "publishers": [
                    {"slug": "mantis", "display_name": "Mantis", "configured": True, "stub": False},
                    {"slug": "adsense", "display_name": "AdSense (later)", "configured": False, "stub": True},
                    {"slug": "ezoic", "display_name": "Ezoic (later)", "configured": False, "stub": True},
                    {"slug": "other", "display_name": "Other SSP (later)", "configured": False, "stub": True},
                ],
                "error": str(exc),
            }
        )


@app.post("/api/save")
def api_save():
    body = request.get_json(force=True, silent=True) or {}
    with _lock:
        panel = load_panel()
        panel.update(
            {
                k: body[k]
                for k in ("phones", "forever", "hours", "notes", "env", "budgets", "active_site_slug")
                if k in body
            }
        )
        panel["last_action"] = "save"
        panel["last_action_at"] = _utc()
        saved = save_panel(panel)
    return jsonify({"ok": True, "panel": saved})


@app.get("/api/sites")
def api_sites():
    try:
        seed_builtin_profiles()
        phones = list(load_panel().get("phones") or DEFAULT_PHONES)
        return jsonify({"ok": True, "sites": list_farm_sites(phones=phones)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/site")
def api_site():
    body = request.get_json(force=True, silent=True) or {}
    slug = str(body.get("slug") or body.get("active_site_slug") or "").strip().lower()
    if slug not in {"dabflow", "loansflow"}:
        return jsonify({"ok": False, "error": "slug must be dabflow or loansflow"}), 400
    # tick289: refuse loansflow while dabflow sticky / watchdog-disabled.
    if slug == "loansflow":
        if (LOG_DIR / "DABFLOW_SITE_STICKY.flag").is_file() or (LOG_DIR / "LOANSFLOW_HOLD_WATCHDOG_DISABLED.flag").is_file():
            return jsonify({"ok": False, "error": "loansflow blocked: dabflow sticky session"}), 409
        clear_dabflow_sticky_pin(LOG_DIR)
        set_loansflow_operator_hold(LOG_DIR, note="operator_api_site_loansflow")
    reset = bool(body.get("reset_budgets", True))
    with _lock:
        panel = load_panel()
        try:
            panel = apply_site_to_panel(panel, slug, reset_budgets=reset)
        except Exception as exc:
            log.exception("apply site failed")
            return jsonify({"ok": False, "error": str(exc)}), 500
        panel["last_action"] = f"site:{slug}"
        panel["last_action_at"] = _utc()
        saved = save_panel(panel)
    return jsonify({"ok": True, "panel": saved, "site": saved.get("site")})

@app.post("/api/stop")
def api_stop():
    with _lock:
        _kill_farm()
        panel = load_panel()
        panel["last_action"] = "stop"
        panel["last_action_at"] = _utc()
        panel["env"]["CPHARM_FARM_STOP"] = "1"
        save_panel(panel)
        # keep stop sticky in overrides until restart clears it
        try:
            data = json.loads(OVERRIDES.read_text(encoding="utf-8")) if OVERRIDES.is_file() else {}
            data["CPHARM_FARM_STOP"] = "1"
            data["updated"] = _utc()
            OVERRIDES.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass
    return jsonify({"ok": True})


@app.post("/api/kill-switch")
def api_kill_switch():
    """Panic stop — farm must not auto-respawn until /api/restart."""
    with _lock:
        engage_kill_switch(note="dash_kill_switch")
        _kill_farm()
        panel = load_panel()
        panel["last_action"] = "kill-switch"
        panel["last_action_at"] = _utc()
        panel["env"]["CPHARM_FARM_STOP"] = "1"
        save_panel(panel)
        try:
            data = json.loads(OVERRIDES.read_text(encoding="utf-8")) if OVERRIDES.is_file() else {}
            data["CPHARM_FARM_STOP"] = "1"
            data["updated"] = _utc()
            OVERRIDES.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass
    return jsonify({"ok": True, "kill_switch": True})


@app.post("/api/restart")
def api_restart():
    body = request.get_json(force=True, silent=True) or {}
    with _lock:
        panel = load_panel()
        panel.update(
            {
                k: body[k]
                for k in ("phones", "forever", "hours", "notes", "env", "budgets", "active_site_slug")
                if k in body
            }
        )
        panel["env"]["CPHARM_FARM_STOP"] = "0"
        panel["last_action"] = "restart"
        panel["last_action_at"] = _utc()
        saved = save_panel(panel)
        clear_kill_switch()
        _kill_farm()
        time.sleep(2)
        pid = _start_farm(saved)
    return jsonify({"ok": True, "pid": pid, "panel": saved})


@app.post("/api/clear")
def api_clear():
    body = request.get_json(force=True, silent=True) or {}
    phones = body.get("phones") or load_panel().get("phones") or DEFAULT_PHONES
    try:
        results = _clear_phones(list(phones)[:5])
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    panel = load_panel()
    panel["last_action"] = "clear"
    panel["last_action_at"] = _utc()
    save_panel(panel)
    return jsonify({"ok": True, "results": results})


@app.post("/api/checkin_ntfy")
def api_checkin_ntfy():
    try:
        from automation.farm_checkin import gather_checkin, publish_checkin

        snap = gather_checkin()
        ok = publish_checkin(snap)
        return jsonify({"ok": bool(ok), "verdict": snap.verdict, "text": _checkin_payload().get("text")})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/mantis_today")
def api_mantis_today():
    """Mantis totals are pull-only — reject manual edits from the dash."""
    return jsonify(
        {
            "ok": False,
            "error": "Mantis totals are pull-only (use Pull from Mantis). Manual save disabled.",
        }
    ), 403


# Single-flight + freshness for /api/mantis_pull. Helpers (remediator /
# watch_bottom_ads / money_monitor) call this endpoint every cycle; each
# GraphQL pull takes 10-40s and stacked pulls froze the dash. A pull completed
# within CPHARM_MANTIS_PULL_FRESH_S returns the saved state instantly, and a
# concurrent pull never starts a second GraphQL fetch.
_MANTIS_PULL_LOCK = threading.Lock()
_MANTIS_PULL_LAST_OK = {"t": 0.0}
_MANTIS_PULL_FRESH_S = float(
    os.environ.get("CPHARM_MANTIS_PULL_FRESH_S", "90").strip() or 90
)


@app.post("/api/mantis_pull")
def api_mantis_pull():
    """Live pull from Mantis admin (your Dab Flow account) → gauges."""
    totals = status_payload().get("totals")

    def _cached(note: str):
        return jsonify(
            {
                "ok": True,
                "mantis_today": load_mantis_today(),
                "totals": totals,
                "cached": True,
                "note": note,
            }
        )

    if time.monotonic() - _MANTIS_PULL_LAST_OK["t"] < _MANTIS_PULL_FRESH_S:
        return _cached("fresh")
    if not _MANTIS_PULL_LOCK.acquire(blocking=False):
        return _cached("inflight")
    try:
        box: dict[str, Any] = {}

        def _run() -> None:
            try:
                from automation.mantis_fetch import pull_today

                summary = pull_today(headed=False)
                saved = save_mantis_today(
                    {
                        "impressions": summary.get("impressions"),
                        "clicks": summary.get("clicks"),
                        "payout_usd": summary.get("payout_usd"),
                        "ecpm": summary.get("ecpm"),
                        "evcpm": summary.get("evcpm"),
                        "receivable_usd": summary.get("receivable_usd"),
                        "paid_to_date_usd": summary.get("paid_to_date_usd"),
                        "lifetime_earnings_usd": summary.get("lifetime_earnings_usd"),
                        "source": summary.get("source") or "mantis_graphql",
                    }
                )
                # Close the loop: yellow/red / over-cap -> steer farm immediately.

                # Overnight sticky/pause: never invoke restore_path3_day_reset from dash pull.

                steer: dict[str, Any] = {}

                try:

                    from pathlib import Path as _Path

                    from automation.farm_visit_caps import path3_day_reset_blocked

                    _ov = _read_json_file(OVERRIDES) if OVERRIDES.is_file() else {}

                    _cur = {k: str(v) for k, v in _ov.items() if str(k).startswith("CPHARM_")}

                    _blk, _why = path3_day_reset_blocked(_cur, log_dir=LOG_DIR)

                    if _blk or (_Path(LOG_DIR) / "DABFLOW_SITE_STICKY.flag").is_file():

                        steer = {

                            "ok": True,

                            "applied": False,

                            "skipped": True,

                            "reason": f"skip_restore_path3:{_why or "dabflow_site_sticky"}",

                        }

                    else:

                        from automation.mantis_autopilot_cycle import run_once

                        steer = run_once(fetch=False)

                except Exception as steer_exc:

                    log.warning("mantis_pull steer soft-fail: %s", steer_exc)

                    steer = {"ok": False, "error": str(steer_exc)}

                box["result"] = {"ok": True, "mantis_today": saved, "autopilot": steer}
            except Exception as exc:
                log.exception("mantis_pull failed")
                box["result"] = {"ok": False, "error": str(exc)}

        thr = threading.Thread(target=_run, name="mantis-pull", daemon=True)
        thr.start()
        thr.join(timeout=120.0)
        if thr.is_alive():
            return jsonify({"ok": False, "error": "Mantis pull timed out (120s)"}), 504
        result = box.get("result") or {"ok": False, "error": "no result"}
        if not result.get("ok"):
            # Soft-fail: keep dash UI alive with last known Mantis snapshot.
            # Do NOT return bare 502 that looks like the dash "shut down".
            cached = load_mantis_today()
            return jsonify(
                {
                    "ok": False,
                    "error": result.get("error") or "mantis pull failed",
                    "mantis_today": cached,
                    "totals": totals,
                    "cached": True,
                    "note": "pull_failed_using_cache — re-auth Mantis manually "
                    "(CPHARM_MANTIS_ALLOW_HEADED=1) when ready",
                }
            ), 200
        _MANTIS_PULL_LAST_OK["t"] = time.monotonic()
        result["totals"] = totals
        return jsonify(result)
    finally:
        _MANTIS_PULL_LOCK.release()


@app.post("/api/cmd")
def api_cmd():
    """Operator command window → ntfy wake for the agent."""
    body = request.get_json(silent=True) or {}
    text = str(body.get("text") or body.get("cmd") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "empty command"}), 400
    if len(text) > 2000:
        text = text[:2000]
    _append_cmd_history(text)
    # Do NOT ntfy operator commands — hourly check-in is the only outbound digest.
    # Commands stay in dash history for the agent / local ops.
    return jsonify({"ok": True, "sent": text, "ntfy": False, "note": "logged locally; ntfy max 1/2h check-in only"})



@app.get("/api/money_monitor")
def api_money_monitor_get():
    try:
        from automation.farm_money_monitor import load_state

        return jsonify({"ok": True, "state": load_state()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/money_monitor")
def api_money_monitor_run():
    """Force one flat-$ evaluate + remediation tick."""
    body = request.get_json(silent=True) or {}
    do_fix = bool(body.get("fix", True))
    try:
        from automation.farm_money_monitor import evaluate, start_background

        start_background()
        state = evaluate(do_fix=do_fix)
        return jsonify({"ok": True, "state": state})
    except Exception as exc:
        log.exception("money_monitor failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


def main() -> int:
    # Seed panel on first launch so I can monitor immediately.
    if not PANEL.is_file():
        save_panel(_default_panel())
        log.info("seeded %s", PANEL)
    # Exclusive bind — Windows can LISTEN twice on :8091 with SO_REUSEADDR and
    # then API requests hang / look "dash down". Refuse a second instance.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        probe.bind((HOST, PORT))
        probe.close()
    except OSError as exc:
        log.error(
            "dash port %s:%s already in use (%s) — refusing duplicate instance",
            HOST,
            PORT,
            exc,
        )
        try:
            probe.close()
        except OSError:
            pass
        return 2
    try:
        from automation.farm_money_monitor import start_background

        started = start_background()
        log.info("farm_money_monitor %s", started)
    except Exception as exc:
        log.warning("farm_money_monitor start soft-fail: %s", exc)
    log.info("Farm Operator dash http://%s:%s", HOST, PORT)
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
