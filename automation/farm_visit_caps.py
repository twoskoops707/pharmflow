"""Runtime sticky / visit caps — SSOT is automation.cpharm_farm_config (no JSON overrides)."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from automation.cpharm_farm_config import (
    MULTI_BROWSER,
    PATH3_BROWSERS,
    apply_farm_env,
    get_runtime,
    merge_runtime,
    purge_legacy_override_files,
    write_adb_serial_lock,
)

# Keep in sync with automation.farm_health_audit.HOUSE_SPAM_SEQ_CAP
HOUSE_SPAM_SEQ_CAP = 36

DEFAULT_LOG = Path(r"C:\CPharm\logs")
OVERRIDES_NAME = "farm_runtime_overrides.json"  # legacy — never written
SITE_LOCK_NAME = "farm_site_lock.json"
CAPS_LOCK_NAME = "farm_visit_caps_lock.json"
STICKY_FLAG = "DABFLOW_SITE_STICKY.flag"
HOLD_FLAG = "LOANSFLOW_OPERATOR_HOLD.flag"
HOLD_DISABLED = "LOANSFLOW_HOLD_WATCHDOG_DISABLED.flag"

_MULTI_BROWSER_KEYS = (
    ("CPHARM_FARM_CHROMIUM_ONLY", "0"),
    ("CPHARM_FARM_BROWSERS", MULTI_BROWSER),
    ("CPHARM_FARM_PATH3_BROWSERS", PATH3_BROWSERS),
)


def _chromium_only_lock_active(log_dir: Path | None = None) -> bool:
    """x86_64 / AVD desktops: allow chromium-only when Brave/Firefox APKs cannot install."""
    log = _log_dir(log_dir)
    if (log / "CHROMIUM_ONLY_LOCK.flag").is_file():
        return True
    return _truthy(os.environ.get("CPHARM_ALLOW_CHROMIUM_ONLY"))


def enforce_multi_browser(target: dict[str, Any]) -> bool:
    """Force multi-browser sticky/env. Returns True if any key changed.

    Skip when ``CHROMIUM_ONLY_LOCK.flag`` or ``CPHARM_ALLOW_CHROMIUM_ONLY=1`` —
    needed on non-ARM hosts where only stock Chrome / chromium APKs install.
    """
    if _chromium_only_lock_active():
        return False
    if _truthy(target.get("CPHARM_ALLOW_CHROMIUM_ONLY")):
        return False
    changed = False
    for key, want in _MULTI_BROWSER_KEYS:
        if str(target.get(key) or "") != want:
            target[key] = want
            changed = True
    return changed


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_dir(log_dir: Path | None) -> Path:
    return Path(log_dir) if log_dir is not None else DEFAULT_LOG


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        subprocess.run(["attrib", "-R", "-S", "-H", str(path)], capture_output=True, check=False)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _as_int(val: Any, default: int = 0) -> int:
    """Parse ints; 0 is a real value (Path3 global gap 0 = parallel)."""
    if val is None:
        return default
    raw = str(val).strip()
    if raw == "":
        return default
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


def _truthy(val: Any) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def _ads_csv_all_zero(raw: Any) -> bool:
    parts = [p.strip() for p in str(raw or "").split(",") if p.strip()]
    if not parts:
        return True
    try:
        return all(int(float(p)) <= 0 for p in parts)
    except (TypeError, ValueError):
        return True


def dabflow_sticky_active(log_dir: Path | None = None) -> bool:
    log = _log_dir(log_dir)
    return (log / STICKY_FLAG).is_file()


def clear_loansflow_operator_hold(log_dir: Path | None = None) -> bool:
    log = _log_dir(log_dir)
    cleared = False
    for name in (HOLD_FLAG, "LOANSFLOW_OPERATOR_HOLD", "loansflow_hold.json"):
        p = log / name
        if not p.exists():
            continue
        if os.name == "nt":
            subprocess.run(["attrib", "-R", "-S", "-H", str(p)], capture_output=True, check=False)
        try:
            p.unlink()
            cleared = True
        except OSError:
            pass
    return cleared


def set_loansflow_operator_hold(log_dir: Path | None = None, note: str = "") -> None:
    """No-op while DabFlow sticky / watchdog-disabled (money-day policy)."""
    return


def clear_dabflow_sticky_pin(log_dir: Path | None = None) -> bool:
    """Refuse clearing DabFlow sticky this session."""
    return False


def write_site_lock(
    slug: str,
    *,
    sequence_root: str = r"C:\CPharm\automation\recordings\sequences",
    daily_visits_csv: str = "500,490,480,470",
    daily_ads_csv: str = "12,12,11,11",
    url: str = "https://getdabflow.app/",
    note: str = "site_lock",
    log_dir: Path | None = None,
    unique_sequences: bool = True,
) -> None:
    log = _log_dir(log_dir)
    want = str(slug or "dabflow").strip().lower() or "dabflow"
    note_s = str(note or "site_lock")
    # sticky_beats_hold_tonight
    if (log / STICKY_FLAG).is_file() or (log / HOLD_DISABLED).is_file():
        clear_loansflow_operator_hold(log)
        if want == "loansflow":
            want = "dabflow"
            note_s = f"refuse_loansflow_under_sticky:{note_s}"
            url = "https://getdabflow.app/"
            sequence_root = r"C:\CPharm\automation\recordings\sequences"
    payload = {
        "slug": want,
        "url": url,
        "sequence_root": sequence_root,
        "daily_visits_csv": daily_visits_csv,
        "daily_ads_csv": daily_ads_csv,
        "unique_sequences": bool(unique_sequences),
        "updated": _utc(),
        "note": note_s,
    }
    _write_json(log / SITE_LOCK_NAME, payload)


def write_visit_caps_lock(
    log_dir: Path | str | None,
    visits: str | None = None,
    seqs: int | str | None = None,
    note: str = "visit_caps",
    *,
    site_slug: str = "dabflow",
    site: str | None = None,
    min_visit_max: int = 400,
) -> None:
    """NO-OP: overrides disabled — caps were fucking up revenue."""
    pass


def _ads_csv_sum(raw: object) -> int:
    total = 0
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            total += max(0, int(float(part)))
        except (TypeError, ValueError):
            continue
    return total


def _money_path3_floor(log: Path) -> tuple[int, int, int]:
    money = _load_json(log / "_money_day_path3_aggressive.json")
    cap = _as_int(money.get("cap"), 0) or 36
    # Default 8; aggressive money-day file can raise (e.g. 14 while behind).
    hr = _as_int(money.get("per_hour"), 0) or 8
    # 0 is valid (parallel Path3). Do not treat numeric 0 as missing (or → 12).
    if "gap" in money and money.get("gap") is not None and str(money.get("gap")).strip() != "":
        gap = _as_int(money.get("gap"), 0)
    else:
        gap = 0
    return cap, hr, gap


def write_runtime_overrides(
    overrides: dict[str, Any],
    *,
    log_dir: Path | None = None,
) -> tuple[dict[str, Any], str]:
    """Merge into in-memory SSOT only — never writes farm_runtime_overrides.json."""
    merge_runtime(overrides or {}, note="ssot_merge")
    buf = get_runtime()
    if enforce_multi_browser(buf):
        merge_runtime({k: buf[k] for k, _ in _MULTI_BROWSER_KEYS}, note="browser_ssot")
    return get_runtime(), "ssot_merge"


def apply_runtime_overrides_to_env(
    env: dict[str, str] | None = None,
    *,
    log_dir: Path | None = None,
) -> dict[str, str]:
    """Apply SSOT CPHARM_* into env (or os.environ)."""
    return apply_farm_env(env)


def reassert_sticky_caps(log_dir: Path | None = None) -> dict[str, Any]:
    """No-op — caps live in cpharm_farm_config.py."""
    return {"changed": False, "visits": "", "seqs": "", "note": "ssot_no_json"}


def path3_day_reset_blocked(
    cur: dict[str, Any] | None = None,
    *,
    log_dir: Path | None = None,
) -> tuple[bool, str]:
    """Block overnight Path3 wipe when money-day ads are armed."""
    log = _log_dir(log_dir)
    cur_m = dict(cur or {})
    site_lock = _load_json(log / SITE_LOCK_NAME)
    money_day_ads = not _ads_csv_all_zero(site_lock.get("daily_ads_csv"))
    if (
        not money_day_ads
        and (
            _truthy(cur_m.get("CPHARM_AUTOPILOT_PAUSE"))
            or _truthy(os.environ.get("CPHARM_AUTOPILOT_PAUSE"))
        )
    ):
        return True, "autopilot_pause"
    if not money_day_ads:
        for name in ("farm_operator_panel.json", "farm_panel_state.json"):
            panel = _load_json(log / name)
            env = panel.get("env") if isinstance(panel.get("env"), dict) else {}
            if _truthy(env.get("CPHARM_AUTOPILOT_PAUSE")):
                return True, "autopilot_pause_panel"
    return False, ""
