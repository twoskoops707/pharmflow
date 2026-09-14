"""Apply autopilot steering plans to farm overrides + audit log."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_LOG_DIR = Path(os.environ.get("PHARMFLOW_LOG_DIR", r"C:\PharmFlow\logs"))
_RESTART_MIN_GAP_S = 600.0


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _dry_run_flag(explicit: bool | None) -> bool:
    if explicit is not None:
        return bool(explicit)
    return os.environ.get("PHARMFLOW_AUTOPILOT_DRY_RUN", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _restart_farm_rate_limited(log_dir: Path) -> dict[str, Any]:
    """Kill run_farm_354 at most once per 10 minutes; ensure/cycles respawn."""
    state_path = log_dir / "autopilot_state.json"
    state = _load_json(state_path)
    now = time.time()
    last = float(state.get("last_restart_ts") or 0.0)
    if last and (now - last) < _RESTART_MIN_GAP_S:
        return {
            "restarted": False,
            "skipped": "rate_limited",
            "retry_in_s": int(_RESTART_MIN_GAP_S - (now - last)),
        }
    try:
        from automation.process_scan import kill_matching, pids_matching

        before = pids_matching("run_farm_354.py")
        if before:
            kill_matching("run_farm_354.py")
        state["last_restart_ts"] = now
        state["last_restart_at"] = _utc()
        state["last_restart_pids"] = before
        _write_json(state_path, state)
        return {"restarted": bool(before), "pids": before}
    except Exception as exc:
        return {"restarted": False, "error": str(exc)}


def apply_steering_plan(
    plan: dict[str, Any],
    *,
    log_dir: Path | None = None,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    """Merge plan overrides into farm_runtime_overrides.json and audit."""
    log = Path(log_dir) if log_dir is not None else DEFAULT_LOG_DIR
    is_dry = _dry_run_flag(dry_run)
    overrides_path = log / "farm_runtime_overrides.json"
    panel_path = log / "farm_panel_state.json"
    operator_panel_path = log / "farm_operator_panel.json"
    actions_path = log / "autopilot_actions.jsonl"
    state_path = log / "autopilot_state.json"

    patch = plan.get("overrides_patch") if isinstance(plan.get("overrides_patch"), dict) else {}
    patch = {str(k): str(v) for k, v in patch.items() if str(k).startswith("PHARMFLOW_")}
    actions = plan.get("actions") if isinstance(plan.get("actions"), list) else []
    reason = str(plan.get("reason") or "")

    audit = {
        "ts": _utc(),
        "dry_run": is_dry,
        "reason": reason,
        "tone": plan.get("tone"),
        "actions": actions,
        "overrides_patch": patch,
        "restart_farm_requested": bool(plan.get("restart_farm")),
        "clicks": plan.get("clicks"),
        "impressions": plan.get("impressions"),
        "ecpm": plan.get("ecpm"),
        "evcpm": plan.get("evcpm"),
    }

    if is_dry:
        _append_jsonl(actions_path, audit)
        state = _load_json(state_path)
        state.update(
            {
                "last_move_at": _utc(),
                "last_move_reason": reason,
                "last_move_dry_run": True,
                "last_tone": plan.get("tone"),
            }
        )
        _write_json(state_path, state)
        return {"ok": True, "dry_run": True, "applied": False, "audit": audit}

    if patch:
        ov = _load_json(overrides_path)
        ov.update(patch)
        ov["updated"] = _utc()
        ov["gauge_push_note"] = f"autopilot: {reason}"
        ov["autopilot_last_reason"] = reason
        _write_json(overrides_path, ov)

        for panel_file in (panel_path, operator_panel_path):
            panel = _load_json(panel_file)
            if not panel and panel_file == operator_panel_path:
                continue
            env = panel.get("env") if isinstance(panel.get("env"), dict) else {}
            env.update(patch)
            panel["env"] = env
            # Keep per-phone budget widgets aligned with DAILY_VISITS/_ADS.
            phones = panel.get("phones") if isinstance(panel.get("phones"), list) else []
            vparts = [
                p.strip()
                for p in str(env.get("PHARMFLOW_FARM_DAILY_VISITS") or "").split(",")
                if p.strip()
            ]
            aparts = [
                p.strip()
                for p in str(env.get("PHARMFLOW_FARM_DAILY_ADS") or "").split(",")
                if p.strip()
            ]
            if phones and vparts:
                budgets = panel.get("budgets") if isinstance(panel.get("budgets"), dict) else {}
                for i, name in enumerate(phones):
                    try:
                        vv = max(0, int(float(vparts[i if i < len(vparts) else -1])))
                    except (TypeError, ValueError, IndexError):
                        continue
                    try:
                        aa = max(
                            0,
                            int(float(aparts[i if i < len(aparts) else -1])) if aparts else 0,
                        )
                    except (TypeError, ValueError, IndexError):
                        aa = 0
                    budgets[str(name)] = {"visits": vv, "ads": aa}
                panel["budgets"] = budgets
            panel["updated"] = ov["updated"]
            _write_json(panel_file, panel)

    restart_info: dict[str, Any] = {"restarted": False}
    if patch and plan.get("restart_farm"):
        restart_info = _restart_farm_rate_limited(log)
    audit["restart"] = restart_info
    _append_jsonl(actions_path, audit)

    state = _load_json(state_path)
    state.update(
        {
            "last_move_at": _utc(),
            "last_move_reason": reason,
            "last_move_dry_run": False,
            "last_tone": plan.get("tone"),
            "last_patch": patch,
            "last_restart": restart_info,
        }
    )
    _write_json(state_path, state)

    return {
        "ok": True,
        "dry_run": False,
        "applied": bool(patch),
        "restart": restart_info,
        "audit": audit,
    }
