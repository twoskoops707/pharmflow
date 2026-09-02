"""CPharm farm configuration — single source of truth in Python code.

No ``farm_runtime_overrides.json``. No caps-lock JSON. No remediator rewrites.
All ``CPHARM_*`` money-path env comes from this module.
"""
from __future__ import annotations

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

LOG_DIR = Path(r"C:\CPharm\logs")

# Browser allow-list — must match sequence pool tags.
MULTI_BROWSER = "farmbrowser,chromium,firefox,brave"
PATH3_BROWSERS = "farmbrowser,chromium"

_LOCK = threading.RLock()
_RUNTIME: dict[str, str] = {}
_NOTE = "cpharm_farm_config_ssot"
_UPDATED = ""


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base_runtime() -> dict[str, str]:
    names = canonical_names_sorted()
    serials = canonical_serials_sorted()
    n = canonical_expect_phones()
    # Behind-money-day rails baked into code (no JSON drift).
    visits = ",".join(["999"] * n)
    ads = "300,295,290,285,300,295,290,285"[: max(7, n * 4)]  # padded below
    ad_parts = [300, 295, 290, 285, 300, 295, 290, 285]
    while len(ad_parts) < n:
        ad_parts.append(285)
    ads = ",".join(str(x) for x in ad_parts[:n])
    return {
        "CPHARM_IPV_STICKY": "21.64",
        "CPHARM_FARM_IMPRESSIONS_PER_VISIT": "21.64",
        "CPHARM_FARM_EST_IMPRESSIONS": "12000",
        "CPHARM_FARM_SEQS_PER_HOUR": "36",
        "CPHARM_FARM_DAILY_VISITS": visits,
        "CPHARM_FARM_DAILY_ADS": ads,
        "CPHARM_FARM_PHONE_COUNT": str(n),
        "CPHARM_FARM_EXPECT_PHONES": str(n),
        "CPHARM_FARM_PHONES": ",".join(names),
        "CPHARM_ADB_SERIALS": ",".join(serials),
        "CPHARM_FARM_BAN_SERIALS": ban_serials_csv(),
        "CPHARM_FARM_PATH3_DAILY_CAP": "3000",
        "CPHARM_PATH3_DAILY_CAP": "3000",
        "CPHARM_FARM_PATH3_PER_HOUR": "14",
        "CPHARM_PATH3_PER_HOUR": "14",
        "CPHARM_PATH3_CAP": "3000",
        "CPHARM_FARM_PATH3_PREEMPT_MIN": "2",
        "CPHARM_FARM_PATH3_GLOBAL_GAP_MIN": "0",
        "CPHARM_PATH3_GAP_MIN": "0",
        "CPHARM_FARM_PATH3_SPACING": "1",
        "CPHARM_FARM_PATH3_PHONE_OFFSET": "1",
        "CPHARM_FARM_PATH3_LEAD_MIN": "0",
        "CPHARM_PREFER_PAYING": "1",
        "CPHARM_SSP_PREFER_PAYING": "1",
        "CPHARM_PATH3_REQUIRE_PAYING": "0",
        "CPHARM_FARM_ALLOW_ADS": "1",
        "CPHARM_ALLOW_ADS": "1",
        "CPHARM_FARM_PATHS": "1,2,3",
        "CPHARM_FARM_PATH3": "1",
        "CPHARM_PATH3": "1",
        "CPHARM_PATH3_ALLOW": "1",
        "CPHARM_FARM_UNIQUE_SEQ": "1",
        "CPHARM_FARM_IMMEDIATE_START": "1",
        "CPHARM_AUTOPILOT_PAUSE": "1",
        "CPHARM_FARM_STOP": "0",
        "CPHARM_EMULATOR_AD_FALLBACK": "1",
        "CPHARM_EMULATOR_AD_FORCE_DIRECT": "1",
        "CPHARM_SKIP_SEQUENCE_ISOLATION": "0",
        "CPHARM_FARM_START_STAGGER_WINDOW": "18",
        "CPHARM_FARM_START_STAGGER_BAND": "18",
        "CPHARM_FARM_START_STAGGER_MIN_GAP": "2",
        "CPHARM_FARM_SLOT_MIN_LEAD": "0",
        "CPHARM_EMULATOR_AD_FILL_WAIT": "2.8",
        "CPHARM_DABFLOW_LOAD_WAIT": "2.8",
        "CPHARM_AGE_GATE_WAIT": "0.55",
        "CPHARM_START_DAB_VERIFY_WAIT": "1.7",
        "CPHARM_AD_DWELL_MIN": "2.5",
        "CPHARM_AD_DWELL_MAX": "5.0",
        "CPHARM_MANTIS_INJECT_PROXY": "1",
        "CPHARM_MANTIS_INJECT_MITM": "1",
        "CPHARM_MANTIS_BILLING_DIRECT": "0",
        "CPHARM_SKIP_MANTIS_PATCH": "0",
        "CPHARM_DABFLOW_MANTIS_PATCH": "1",
        "CPHARM_EMULATOR_AD_MODE": "1",
        "CPHARM_FARM_CHROMIUM_ONLY": "0",
        "CPHARM_FARM_BROWSERS": MULTI_BROWSER,
        "CPHARM_FARM_PATH3_BROWSERS": PATH3_BROWSERS,
        "CPHARM_TABLET_FARM": "1",
        "CPHARM_TABLET_PHONE": "",
        "CPHARM_TABLET_SERIAL": "",
        "CPHARM_NEVER_SHARE_EXIT_IP": "1",
        "CPHARM_REQUIRE_FARM_BROWSERS": "0",
        "CPHARM_FAST_STICKY_BOOT": "1",
        "CPHARM_TOR_PATH": r"C:\CPharm\bundled\tor.exe",
        "CPHARM_SKIP_BOOT_GEO": "1",
        "CPHARM_GEO_TIME_WINDOW": "1",
        "CPHARM_BROWSE_PROXY_MODE": "scramble",
        "CPHARM_TOR_HTTP_BASE": "8118",
        "CPHARM_TOR_SOCKS_BASE": "9050",
        "CPHARM_TOR_CONTROL_BASE": "9151",
        "CPHARM_FARM_MIN_SEQ_SPACING_S": "45",
        "CPHARM_ALLOW_SEQUENCE_RUNS": "1",
        "CPHARM_REQUIRE_UNIQUE_EXIT_IP": "1",
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
            if not sk.startswith("CPHARM_"):
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
                os.system(f'attrib -R -S -H "{path}"')
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
    """Persist canonical phone→serial map (not override rails)."""
    log = log_dir or LOG_DIR
    phones = dict(CANONICAL_FARM_PHONES)
    if live_by_name:
        for name, serial in live_by_name.items():
            full = name if name.endswith(".gmadoa") else f"{name}.gmadoa"
            if full in phones and serial:
                phones[full] = serial
    inject = {nm: 8218 + int(nm.split(".")[0][2:]) for nm in phones}
    payload = {
        "phones": phones,
        "tablet": {},
        "inject": inject,
        "note": "cpharm_farm_config_ssot",
        "updated": _utc(),
        "locked_at": _utc(),
    }
    path = log / "ADB_SERIAL_MAP.lock.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        __import__("json").dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
