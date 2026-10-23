"""PharmFlow farm configuration — single source of truth in Python code.

No ``farm_runtime_overrides.json``. No caps-lock JSON. No remediator rewrites.
All ``PHARMFLOW_*`` money-path env comes from this module.
"""
from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from automation.farm_canonical_phones import (
    CANONICAL_FARM_PHONES,
    ban_serials_csv,
    canonical_expect_phones,
    canonical_names_sorted,
    canonical_serials_sorted,
)

LOG_DIR = Path(r"C:\PharmFlow\logs")

# Browser allow-list — must match sequence pool tags.
MULTI_BROWSER = "farmbrowser,chromium,firefox,brave"
PATH3_BROWSERS = "farmbrowser,chromium"

_LOCK = threading.RLock()
_RUNTIME: dict[str, str] = {}
_NOTE = "pharmflow_farm_config_ssot"
_UPDATED = ""


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_tor_exe_path() -> str:
    """Return an on-disk tor.exe, preferring PharmFlow then CPharm.

    Branding left SSOT pointing at ``C:\\PharmFlow\\bundled\\tor.exe`` while the
    live binary still lives under ``C:\\CPharm\\bundled\\tor.exe``. Start farm /
    TorManager then fail with a missing binary even though a seed exists.
    """
    preferred = Path(r"C:\PharmFlow\bundled\tor.exe")
    candidates = (
        preferred,
        Path(r"C:\PharmFlow\automation\tor\tor.exe"),
        Path(r"C:\CPharm\bundled\tor.exe"),
        Path(r"C:\CPharm\automation\tor\tor.exe"),
        Path(r"C:\Tor\tor.exe"),
    )
    for cand in candidates:
        try:
            if cand.is_file():
                return str(cand)
        except OSError:
            continue
    return str(preferred)


def _resolve_tor_socks_base() -> int:
    """Prefer the freshest live Tor base broadcast over a hardcoded 9050."""
    newest: tuple[float, int] | None = None
    for path in (
        Path(r"C:\PharmFlow\logs\tor_port_bases.json"),
        Path(r"C:\CPharm\logs\tor_port_bases.json"),
    ):
        try:
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            socks = int(float(str(data.get("socks_base") or 0)))
            if socks <= 0:
                continue
            mtime = path.stat().st_mtime
            if newest is None or mtime > newest[0]:
                newest = (mtime, socks)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    if newest is not None:
        return newest[1]
    env = (os.environ.get("PHARMFLOW_TOR_SOCKS_BASE") or "").strip()
    if env.isdigit() and int(env) > 0:
        return int(env)
    return 9550


def _base_runtime() -> dict[str, str]:
    names = canonical_names_sorted()
    serials = canonical_serials_sorted()
    n = canonical_expect_phones()
    # Behind-money-day rails baked into code (no JSON drift).
    # FARM_OPERATIONS_MANUAL + 2026-08-21 money session contract:
    #   - Uneven per-phone visits/ads is the under-radar requirement (equal
    #     clone CSVs get flagged); remediator flattening to equal was a bug.
    #   - Clicks are the revenue driver; billing must leave through each
    #     phone's own exit (PHARMFLOW_MANTIS_BILLING_DIRECT=0). Host-IP
    #     billing_direct=1 is forbidden — Mantis dedupes it to $0.
    #   - PATHS=1,2,3 + Allow-ads ON means Path3 daily cap must be real
    #     (sum of DAILY_ADS). Cap 0 with PATHS including 3 is split-brain
    #     that logs "count=N/0" and starves clicks while impressions roll.
    _w = [1.0, 0.82, 0.93, 0.74, 1.05, 0.87, 0.97, 0.78, 1.02, 0.8, 0.9, 0.76]
    visit_parts = [max(1, int(999 * _w[i % len(_w)])) for i in range(max(n, 1))]
    ad_parts = [max(1, int(320 * _w[i % len(_w)])) for i in range(max(n, 1))]
    visits = ",".join(str(x) for x in visit_parts)
    ads = ",".join(str(x) for x in ad_parts)
    # Path3/hour default derived from the operator's own configured daily ad
    # volume spread across the active window (matches automation.config's
    # SCHED_ACTIVE_HOUR_START..END default of 7..23) instead of a fixed
    # literal — repo rule forbids hardcoded rate caps. merge_runtime (operator
    # / earn-plan Save) can still raise or lower this explicitly at runtime.
    _active_hours = 23 - 7
    _avg_daily_ads = sum(ad_parts) / max(1, len(ad_parts))
    path3_per_hour = max(1, round(_avg_daily_ads / _active_hours))
    return {
        "PHARMFLOW_IPV_STICKY": "21.64",
        "PHARMFLOW_FARM_IMPRESSIONS_PER_VISIT": "21.64",
        "PHARMFLOW_FARM_EST_IMPRESSIONS": "12000",
        "PHARMFLOW_FARM_SEQS_PER_HOUR": "36",
        "PHARMFLOW_FARM_DAILY_VISITS": visits,
        "PHARMFLOW_FARM_DAILY_ADS": ads,
        "PHARMFLOW_FARM_PHONE_COUNT": str(n),
        "PHARMFLOW_FARM_EXPECT_PHONES": str(n),
        "PHARMFLOW_FARM_PHONES": ",".join(names),
        "PHARMFLOW_ADB_SERIALS": ",".join(serials),
        "PHARMFLOW_FARM_BAN_SERIALS": ban_serials_csv(),
        # Allow-ads ON (bottom-ad inject / Path1-2 ad pools). Path3 click ceiling
        # matches sum(DAILY_ADS) so PATHS=1,2,3 is not a split-brain lie that
        # logs "Path3 farm-wide guard: count=N/0" and starves clicks at $0.
        # Operator / earn-plan Save mix may still raise or lower via merge_runtime.
        "PHARMFLOW_FARM_PATH3_DAILY_CAP": str(sum(ad_parts)),
        "PHARMFLOW_PATH3_DAILY_CAP": str(sum(ad_parts)),
        "PHARMFLOW_FARM_PATH3_PER_HOUR": str(path3_per_hour),
        "PHARMFLOW_PATH3_PER_HOUR": str(path3_per_hour),
        "PHARMFLOW_PATH3_CAP": str(sum(ad_parts)),
        "PHARMFLOW_FARM_PATH3_PREEMPT_MIN": "2",
        "PHARMFLOW_FARM_PATH3_GLOBAL_GAP_MIN": "0",
        "PHARMFLOW_PATH3_GAP_MIN": "0",
        "PHARMFLOW_FARM_PATH3_SPACING": "1",
        "PHARMFLOW_FARM_PATH3_PHONE_OFFSET": "1",
        "PHARMFLOW_FARM_PATH3_LEAD_MIN": "0",
        "PHARMFLOW_PREFER_PAYING": "1",
        "PHARMFLOW_SSP_PREFER_PAYING": "1",
        "PHARMFLOW_PATH3_REQUIRE_PAYING": "0",
        "PHARMFLOW_FARM_ALLOW_ADS": "1",
        "PHARMFLOW_ALLOW_ADS": "1",
        "PHARMFLOW_FARM_PATHS": "1,2,3",
        "PHARMFLOW_FARM_PATH3": "1",
        "PHARMFLOW_PATH3": "1",
        "PHARMFLOW_PATH3_ALLOW": "1",
        "PHARMFLOW_FARM_UNIQUE_SEQ": "1",
        "PHARMFLOW_FARM_IMMEDIATE_START": "1",
        "PHARMFLOW_AUTOPILOT_PAUSE": "1",
        "PHARMFLOW_FARM_STOP": "0",
        "PHARMFLOW_EMULATOR_AD_FALLBACK": "0",
        "PHARMFLOW_EMULATOR_AD_FORCE_DIRECT": "0",
        "PHARMFLOW_SKIP_SEQUENCE_ISOLATION": "0",
        "PHARMFLOW_FARM_START_STAGGER_WINDOW": "18",
        "PHARMFLOW_FARM_START_STAGGER_BAND": "18",
        "PHARMFLOW_FARM_START_STAGGER_MIN_GAP": "2",
        "PHARMFLOW_FARM_SLOT_MIN_LEAD": "0",
        "PHARMFLOW_EMULATOR_AD_FILL_WAIT": "2.8",
        "PHARMFLOW_DABFLOW_LOAD_WAIT": "2.8",
        "PHARMFLOW_AGE_GATE_WAIT": "0.55",
        "PHARMFLOW_START_DAB_VERIFY_WAIT": "1.7",
        "PHARMFLOW_AD_DWELL_MIN": "2.5",
        "PHARMFLOW_AD_DWELL_MAX": "5.0",
        "PHARMFLOW_MANTIS_INJECT_PROXY": "1",
        "PHARMFLOW_MANTIS_INJECT_MITM": "1",
        # HOST-IP BILLING IS FORBIDDEN (operator standing rule + code comment in
        # mantis_inject_proxy.py): all traffic incl. billing must leave through
        # each phone's own unique exit so Mantis never sees single-IP bot
        # patterns. 0 = billing follows the phone's normal upstream (residential
        # per-phone pool, else Tor). Never set this to 1.
        "PHARMFLOW_MANTIS_BILLING_DIRECT": "0",
        "PHARMFLOW_SKIP_MANTIS_PATCH": "0",
        "PHARMFLOW_DABFLOW_MANTIS_PATCH": "1",
        "PHARMFLOW_EMULATOR_AD_MODE": "1",
        "PHARMFLOW_FARM_CHROMIUM_ONLY": "0",
        "PHARMFLOW_FARM_BROWSERS": MULTI_BROWSER,
        "PHARMFLOW_FARM_PATH3_BROWSERS": PATH3_BROWSERS,
        "PHARMFLOW_TABLET_FARM": "1",
        "PHARMFLOW_TABLET_PHONE": "",
        "PHARMFLOW_TABLET_SERIAL": "",
        "PHARMFLOW_NEVER_SHARE_EXIT_IP": "1",
        "PHARMFLOW_REQUIRE_FARM_BROWSERS": "0",
        "PHARMFLOW_FAST_STICKY_BOOT": "1",
        "PHARMFLOW_TOR_PATH": resolve_tor_exe_path(),
        "PHARMFLOW_SKIP_BOOT_GEO": "1",
        "PHARMFLOW_GEO_TIME_WINDOW": "1",
        "PHARMFLOW_BROWSE_PROXY_MODE": "scramble",
        "PHARMFLOW_TOR_HTTP_BASE": "8118",
        # Prefer live broadcast when present (apply_farm_env heals from
        # tor_port_bases.json). Hard 9050 fights Hyper-V exclusions → WSAEACCES.
        "PHARMFLOW_TOR_SOCKS_BASE": str(_resolve_tor_socks_base()),
        "PHARMFLOW_TOR_CONTROL_BASE": "9151",
        "PHARMFLOW_FARM_MIN_SEQ_SPACING_S": "45",
        "PHARMFLOW_ALLOW_SEQUENCE_RUNS": "1",
        "PHARMFLOW_REQUIRE_UNIQUE_EXIT_IP": "1",
    }


def reset_runtime(*, note: str = "reset") -> dict[str, str]:
    """Reload defaults from code."""
    global _NOTE, _UPDATED
    with _LOCK:
        _RUNTIME.clear()
        _RUNTIME.update(_base_runtime())
        _NOTE = note
        _UPDATED = _utc()
        return deepcopy(_RUNTIME)


def get_runtime() -> dict[str, str]:
    with _LOCK:
        if not _RUNTIME:
            reset_runtime(note="init")
        return deepcopy(_RUNTIME)


def merge_runtime(updates: dict[str, Any] | None, *, note: str = "") -> bool:
    """Merge keys in-memory only. Returns True if anything changed."""
    global _NOTE, _UPDATED
    if not updates:
        return False
    with _LOCK:
        if not _RUNTIME:
            reset_runtime(note="init")
        changed = False
        for key, val in updates.items():
            if val is None:
                continue
            sk = str(key)
            if not sk.startswith("PHARMFLOW_"):
                continue
            sv = str(val)
            if _RUNTIME.get(sk) != sv:
                _RUNTIME[sk] = sv
                changed = True
        if changed:
            _NOTE = note or _NOTE
            _UPDATED = _utc()
        return changed


def apply_farm_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """Apply SSOT runtime into os.environ or a provided dict."""
    target: dict[str, str] = env if env is not None else os.environ  # type: ignore[assignment]
    data = get_runtime()
    for key, val in data.items():
        target[str(key)] = str(val)
    # Never leave TOR_PATH aimed at a missing file after branding split.
    tor = str(target.get("PHARMFLOW_TOR_PATH") or "").strip()
    if not tor or not Path(tor).is_file():
        target["PHARMFLOW_TOR_PATH"] = resolve_tor_exe_path()
    # Never stomp a live Tor SOCKS base with a dead Hyper-V-blocked default.
    live_socks = _resolve_tor_socks_base()
    target["PHARMFLOW_TOR_SOCKS_BASE"] = str(live_socks)
    return target


def purge_legacy_override_files(log_dir: Path | None = None) -> list[str]:
    """Delete JSON override rails — config lives in code now."""
    log = log_dir or LOG_DIR
    removed: list[str] = []
    for name in (
        "farm_runtime_overrides.json",
        "farm_visit_caps_lock.json",
        "_money_day_lock.json",
        "_money_day_path3_aggressive.json",
        "farm_operator_panel.json",
        "farm_panel_state.json",
    ):
        path = log / name
        if not path.is_file():
            continue
        try:
            if os.name == "nt":
                # os.system() allocates a console → visible flash on pythonw.
                # attrib via subprocess with CREATE_NO_WINDOW stays silent.
                import subprocess as _sp

                _sp.run(
                    ["attrib", "-R", "-S", "-H", str(path)],
                    stdout=_sp.DEVNULL,
                    stderr=_sp.DEVNULL,
                    **(
                        {
                            "creationflags": int(
                                getattr(_sp, "CREATE_NO_WINDOW", 0x08000000)
                            )
                        }
                        if os.name == "nt"
                        else {}
                    ),
                )
            path.unlink()
            removed.append(name)
        except OSError:
            removed.append(f"FAIL:{name}")
    return removed


def write_adb_serial_lock(
  live_by_name: dict[str, str] | None = None,
  *,
  log_dir: Path | None = None,
) -> None:
    """Persist LIVE phone→serial map only (never full canonical empties/ghosts).

    Writing CANONICAL_FARM_PHONES with blank serials re-poisoned ADB_SERIAL_MAP,
    caused REWIRE storms, and killed bottom-ads inject pins. Money path requires
    only currently live (name, serial) rows.
    """
    log = log_dir or LOG_DIR
    phones: dict[str, str] = {}
    if live_by_name:
        for name, serial in live_by_name.items():
            ser = str(serial or "").strip()
            nm = str(name or "").strip()
            if not ser or not nm:
                continue
            full = nm if nm.endswith(".gmadoa") else f"{nm}.gmadoa"
            phones[full] = ser
    if not phones:
        # Refuse to wipe a good lock with an empty write — leave file alone.
        return
    inject: dict[str, int] = {}
    for nm in phones:
        try:
            idx = int(nm.split(".", 1)[0][2:])
        except (IndexError, ValueError):
            continue
        inject[nm] = 8218 + idx
    payload = {
        "phones": phones,
        "tablet": {},
        "inject": inject,
        "note": "live_only_money_lock",
        "updated": _utc(),
        "locked_at": _utc(),
    }
    path = log / "ADB_SERIAL_MAP.lock.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        __import__("json").dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
