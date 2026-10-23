"""Operator pause/resume — farm off until a wall-clock time, dash stays up.

Replaces ad-hoc PHARMFLOW_FARM_STOP fights. ensure/keepalive/remediator honor
FARM_PAUSED_UNTIL.json; they do not respawn farm workers while paused.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from automation.farm_visit_caps import enforce_multi_browser

LOG = Path(os.environ.get("PHARMFLOW_LOGS") or r"C:\PharmFlow\logs")
PAUSE_FILE = LOG / "FARM_PAUSED_UNTIL.json"
KILL_FLAG = LOG / "FARM_KILL.flag"
SNAPSHOT_FILE = LOG / "farm_midnight_snapshot.json"
CONFIG_FILE = LOG / "farm_operator_config.json"
OVERRIDES = LOG / "farm_runtime_overrides.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(raw: str) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def pause_state() -> dict[str, Any] | None:
    if not PAUSE_FILE.is_file():
        return None
    try:
        data = json.loads(PAUSE_FILE.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def is_paused(*, now: datetime | None = None) -> bool:
    st = pause_state()
    if not st:
        return False
    until = _parse_ts(str(st.get("until") or ""))
    if until is None:
        return bool(st.get("paused"))
    current = now or datetime.now(timezone.utc)
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current < until.astimezone(timezone.utc)


def is_killed() -> bool:
    """Phuper-style panic flag — farm must not respawn until operator clears it."""
    return KILL_FLAG.is_file()


def farm_halted(*, now: datetime | None = None) -> bool:
    return is_killed() or is_paused(now=now)


def engage_kill_switch(*, note: str = "") -> Path:
    KILL_FLAG.parent.mkdir(parents=True, exist_ok=True)
    KILL_FLAG.write_text(
        json.dumps({"ts": _utc(), "note": note or "operator_kill_switch"}, indent=2) + "\n",
        encoding="utf-8",
    )
    return KILL_FLAG


def clear_kill_switch() -> None:
    try:
        KILL_FLAG.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def seconds_until_resume(*, now: datetime | None = None) -> float:
    st = pause_state()
    if not st:
        return 0.0
    until = _parse_ts(str(st.get("until") or ""))
    if until is None:
        return 86400.0
    current = now or datetime.now(timezone.utc)
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return max(0.0, (until.astimezone(timezone.utc) - current.astimezone(timezone.utc)).total_seconds())


def capture_snapshot(*, note: str = "") -> dict[str, Any]:
    """Freeze operator intent + live discovery for midnight resume."""
    ov: dict[str, Any] = {}
    if OVERRIDES.is_file():
        try:
            ov = json.loads(OVERRIDES.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            ov = {}
    phones: list[tuple[str, str, str]] = []
    try:
        from automation.farm_phone_discover import live_phones

        phones = list(live_phones())
    except Exception:
        pass
    snap: dict[str, Any] = {
        "captured": _utc(),
        "note": note,
        "dash_port": 8091,
        "keep_dash": True,
        "phones": [{"name": n, "serial": s, "proxy": p} for n, s, p in phones],
        "operator": {
            k: v
            for k, v in ov.items()
            if str(k).startswith("PHARMFLOW_") and k
            not in (
                "PHARMFLOW_FARM_STOP",
                "PHARMFLOW_AUTOPILOT_PAUSE",
            )
        },
    }
    # Operator config: explicit knobs (not rewritten every remediator tick).
    config = {
        "updated": _utc(),
        "source": "farm_pause.capture_snapshot",
        "phones_expect": len(phones) or int(ov.get("PHARMFLOW_FARM_EXPECT_PHONES") or 6),
        "daily_visits": ov.get("PHARMFLOW_FARM_DAILY_VISITS"),
        "daily_ads": ov.get("PHARMFLOW_FARM_DAILY_ADS"),
        "seqs_per_hour": ov.get("PHARMFLOW_FARM_SEQS_PER_HOUR"),
        "stagger_window": ov.get("PHARMFLOW_FARM_START_STAGGER_WINDOW", "150"),
        "stagger_min_gap": ov.get("PHARMFLOW_FARM_START_STAGGER_MIN_GAP", "18"),
        "age_gate_wait": "2.0",
        "dabflow_load_wait": "5.5",
        "start_dab_verify_wait": "2.5",
        "ipv_per_visit": ov.get("PHARMFLOW_IPV_STICKY") or ov.get("PHARMFLOW_FARM_IMPRESSIONS_PER_VISIT") or "21.64",
        "chromium_only": ov.get("PHARMFLOW_FARM_CHROMIUM_ONLY", "0"),
        "unique_seq": ov.get("PHARMFLOW_FARM_UNIQUE_SEQ", "1"),
        "allow_ads": ov.get("PHARMFLOW_FARM_ALLOW_ADS", "1"),
        "path3_daily_cap": ov.get("PHARMFLOW_FARM_PATH3_DAILY_CAP", "24"),
    }
    LOG.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_FILE.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return snap


def pause_until(
    when: datetime,
    *,
    reason: str = "operator pause",
    snapshot: bool = True,
) -> dict[str, Any]:
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    payload: dict[str, Any] = {
        "paused": True,
        "since": _utc(),
        "until": when.isoformat(),
        "reason": reason,
    }
    if snapshot:
        payload["snapshot"] = str(SNAPSHOT_FILE)
        capture_snapshot(note=reason)
    LOG.mkdir(parents=True, exist_ok=True)
    PAUSE_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    # Hard stop for workers that read overrides.
    try:
        ov: dict[str, Any] = {}
        if OVERRIDES.is_file():
            ov = json.loads(OVERRIDES.read_text(encoding="utf-8-sig"))
        ov["PHARMFLOW_FARM_STOP"] = "1"
        ov["updated"] = _utc()
        ov["pause_note"] = reason
        OVERRIDES.write_text(json.dumps(ov, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    return payload


def pause_until_local_midnight(tz_name: str = "America/Los_Angeles") -> dict[str, Any]:
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if now >= midnight:
        from datetime import timedelta

        midnight = midnight + timedelta(days=1)
    return pause_until(midnight, reason=f"paused until local midnight ({tz_name})")


def clear_pause() -> None:
    try:
        PAUSE_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        ov: dict[str, Any] = {}
        if OVERRIDES.is_file():
            ov = json.loads(OVERRIDES.read_text(encoding="utf-8-sig"))
        ov["PHARMFLOW_FARM_STOP"] = "0"
        ov.pop("pause_note", None)
        ov["updated"] = _utc()
        OVERRIDES.write_text(json.dumps(ov, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def apply_operator_config_to_overrides() -> list[str]:
    """Merge farm_operator_config.json into runtime overrides once at resume."""
    if not CONFIG_FILE.is_file():
        return ["no_operator_config"]
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return ["operator_config_unreadable"]
    ov: dict[str, Any] = {}
    if OVERRIDES.is_file():
        try:
            ov = json.loads(OVERRIDES.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            ov = {}
    mapping = {
        "daily_visits": "PHARMFLOW_FARM_DAILY_VISITS",
        "daily_ads": "PHARMFLOW_FARM_DAILY_ADS",
        "seqs_per_hour": "PHARMFLOW_FARM_SEQS_PER_HOUR",
        "stagger_window": "PHARMFLOW_FARM_START_STAGGER_WINDOW",
        "stagger_min_gap": "PHARMFLOW_FARM_START_STAGGER_MIN_GAP",
        "age_gate_wait": "PHARMFLOW_AGE_GATE_WAIT",
        "dabflow_load_wait": "PHARMFLOW_DABFLOW_LOAD_WAIT",
        "start_dab_verify_wait": "PHARMFLOW_START_DAB_VERIFY_WAIT",
        "ipv_per_visit": "PHARMFLOW_FARM_IMPRESSIONS_PER_VISIT",
        # chromium_only omitted — unique-seq forbids locking sticky to chromium-only.
        "unique_seq": "PHARMFLOW_FARM_UNIQUE_SEQ",
        "allow_ads": "PHARMFLOW_FARM_ALLOW_ADS",
        "path3_daily_cap": "PHARMFLOW_FARM_PATH3_DAILY_CAP",
    }
    changed: list[str] = []
    for cfg_key, env_key in mapping.items():
        val = cfg.get(cfg_key)
        if val is None:
            continue
        sval = str(val)
        if str(ov.get(env_key) or "") != sval:
            ov[env_key] = sval
            changed.append(env_key)
    if cfg.get("ipv_per_visit"):
        ov["PHARMFLOW_IPV_STICKY"] = str(cfg["ipv_per_visit"])
    ov["PHARMFLOW_FARM_STOP"] = "0"
    ov["PHARMFLOW_FARM_UNIQUE_SEQ"] = "1"
    if enforce_multi_browser(ov):
        changed.append("multi_browser")
    ov["updated"] = _utc()
    OVERRIDES.write_text(json.dumps(ov, indent=2) + "\n", encoding="utf-8")
    return changed or ["operator_config_applied"]
