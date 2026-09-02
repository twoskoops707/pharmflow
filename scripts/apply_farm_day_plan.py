#!/usr/bin/env python3
"""Apply C:\\CPharm\\logs\\farm_day_plan.json when local date matches.

Merges plan env into farm_runtime_overrides.json, syncs panel, and restarts
run_farm_354 once per date so daily visit/ad caps + ALLOW_ADS take effect.
Safe to call every minute from ensure_farm_24x7.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import automation.no_window  # noqa: E402,F401

LOG_DIR = Path(os.environ.get("CPHARM_LOG_DIR", r"C:\CPharm\logs"))
PLAN = LOG_DIR / "farm_day_plan.json"
OVERRIDES = LOG_DIR / "farm_runtime_overrides.json"
PANEL = LOG_DIR / "farm_panel_state.json"
APPLIED = LOG_DIR / "farm_day_plan_applied.json"


def _today() -> str:
    return datetime.now().astimezone().date().isoformat()


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def apply_if_due(*, force_restart: bool = True) -> dict:
    """Apply dated day plan when local date matches. Returns status dict."""
    plan = _load(PLAN)
    if not plan:
        return {"ok": False, "reason": "no_plan"}
    date = str(plan.get("date") or "").strip()
    today = _today()
    if not date or date != today:
        return {"ok": True, "reason": "not_today", "plan_date": date, "today": today}

    applied = _load(APPLIED)
    if str(applied.get("date") or "") == today and applied.get("ok"):
        return {"ok": True, "reason": "already_applied", "date": today}

    env_patch = plan.get("env") if isinstance(plan.get("env"), dict) else {}
    ov = _load(OVERRIDES)
    for key, value in env_patch.items():
        if str(key).startswith("CPHARM_"):
            ov[str(key)] = str(value)
    ov["gauge_push_note"] = str(plan.get("note") or "day plan applied")
    ov["updated"] = datetime.now(timezone.utc).isoformat()
    ov["day_plan_date"] = today
    _write(OVERRIDES, ov)

    panel = _load(PANEL)
    if panel:
        penv = panel.get("env") if isinstance(panel.get("env"), dict) else {}
        for key, value in env_patch.items():
            if str(key).startswith("CPHARM_"):
                penv[str(key)] = str(value)
        panel["env"] = penv
        panel["updated"] = ov["updated"]
        _write(PANEL, panel)

    restarted = False
    if force_restart:
        try:
            from automation.process_scan import kill_matching, pids_matching

            before = pids_matching("run_farm_354.py")
            if before:
                kill_matching("run_farm_354.py")
                time.sleep(2.0)
            restarted = True
        except Exception as exc:
            return {
                "ok": False,
                "reason": "restart_failed",
                "error": str(exc),
                "date": today,
            }

    status = {
        "ok": True,
        "reason": "applied",
        "date": today,
        "restarted": restarted,
        "targets": plan.get("targets"),
        "env": {k: ov.get(k) for k in env_patch if str(k).startswith("CPHARM_")},
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }
    _write(APPLIED, status)
    return status


def main() -> int:
    status = apply_if_due(force_restart="--no-restart" not in sys.argv)
    print(json.dumps(status, indent=2))
    return 0 if status.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
