"""Shared dual-agent coordination board — Cursor + FREEBUFF work in unison.

State file: ``C:\\PharmFlow\\logs\\AGENT_UNISON.json``

Rules:
- DO NOT kill or restart MuMu emulators (both agents).
- Cursor owns infra lane; FREEBUFF owns money/SSP/ntfy lane.
- Tasks are claimed with short TTL locks to avoid duplicate work.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BOARD = Path(r"C:\PharmFlow\logs\AGENT_UNISON.json")
RULES = (
    "DO_NOT_KILL_EMULATORS",
    "PharmFlow.exe owns Start farm — agents diagnose/fix only",
    "Unique IPs + inject proxy required per phone",
)

LANES: dict[str, list[str]] = {
    "cursor": [
        "tor_path_and_bundled",
        "adb_serial_map_sync",
        "adb_reverse_repin",
        "dash_8091_keepalive",
        "runtime_overrides_permissions",
        "farm_reload_flag_when_infra_fixed",
    ],
    "freebuff": [
        "ssp_paying_hunter",
        "watch_bottom_ads",
        "mantis_pull_and_gauges",
        "ntfy_twskoops_replies",
        "sequence_progress_monitor",
        "money_monitor_alert",
    ],
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict[str, Any]:
    if not BOARD.is_file():
        return {}
    try:
        raw = json.loads(BOARD.read_text(encoding="utf-8-sig"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict[str, Any]) -> None:
    BOARD.parent.mkdir(parents=True, exist_ok=True)
    data["updated"] = _utc()
    BOARD.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def heartbeat(agent: str, *, task: str = "", note: str = "", extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Record agent heartbeat and optional current task."""
    agent = agent.strip().lower()
    if agent not in ("cursor", "freebuff"):
        raise ValueError(f"unknown agent: {agent}")
    data = _load()
    data.setdefault("rules", list(RULES))
    data.setdefault("lanes", LANES)
    agents = data.setdefault("agents", {})
    entry: dict[str, Any] = {
        "last_heartbeat": _utc(),
        "pid": os.getpid(),
        "task": task,
        "note": note,
    }
    if extra:
        entry.update(extra)
    agents[agent] = entry
    _save(data)
    return data


def claim_task(agent: str, task_id: str, *, ttl_s: float = 300.0) -> bool:
    """Try to claim a task. Returns True if this agent owns it."""
    agent = agent.strip().lower()
    data = _load()
    tasks: dict[str, Any] = data.setdefault("tasks", {})
    now = time.time()
    cur = tasks.get(task_id)
    if isinstance(cur, dict):
        owner = str(cur.get("owner") or "")
        expires = float(cur.get("expires_unix") or 0)
        if owner and owner != agent and expires > now:
            return False
    tasks[task_id] = {
        "owner": agent,
        "claimed_at": _utc(),
        "expires_unix": now + ttl_s,
    }
    _save(data)
    return True


def complete_task(agent: str, task_id: str, *, result: str = "ok") -> None:
    data = _load()
    tasks: dict[str, Any] = data.setdefault("tasks", {})
    tasks[task_id] = {
        "owner": agent,
        "completed_at": _utc(),
        "result": result,
    }
    _save(data)


def set_status(**fields: Any) -> None:
    data = _load()
    status = data.setdefault("farm_status", {})
    status.update(fields)
    status["ts"] = _utc()
    _save(data)


def read_board() -> dict[str, Any]:
    return _load()
