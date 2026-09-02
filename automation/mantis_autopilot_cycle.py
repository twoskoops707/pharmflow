"""One-shot Mantis autopilot cycle (fetch → score → steer → apply)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from automation.mantis_autopilot_apply import apply_steering_plan
from automation.mantis_gauge_score import score_levers
from automation.mantis_steering import plan_steering

LOG_DIR = Path(os.environ.get("CPHARM_LOG_DIR", r"C:\CPharm\logs"))
HB = LOG_DIR / "mantis_autopilot_heartbeat.txt"
STATE = LOG_DIR / "autopilot_state.json"
MANTIS_TODAY = LOG_DIR / "mantis_today_state.json"
OVERRIDES = LOG_DIR / "farm_runtime_overrides.json"
BUDGET = LOG_DIR / "farm_daily_budget_state.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hb(msg: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        HB.write_text(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n", encoding="utf-8")
    except OSError:
        pass


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _farm_ads_used() -> tuple[int, int]:
    d = _load(BUDGET)
    phones = d.get("phones") if isinstance(d.get("phones"), dict) else {}
    ads = 0
    visits = 0
    for row in phones.values():
        if not isinstance(row, dict):
            continue
        ads += int(row.get("ads") or 0)
        visits += int(row.get("visits") or 0)
    return ads, visits


def _save_mantis_today(summary: dict[str, Any]) -> dict[str, Any]:
    out = {
        "date": summary.get("date") or datetime.now().astimezone().date().isoformat(),
        "impressions": int(summary.get("impressions") or 0),
        "clicks": int(summary.get("clicks") or 0),
        "payout_usd": float(summary.get("payout_usd") or 0),
        "ecpm": float(summary.get("ecpm") or 0),
        "evcpm": float(summary.get("evcpm") or 0),
        "updated": summary.get("updated") or _utc(),
        "source": summary.get("source") or "mantis_graphql",
    }
    _write(MANTIS_TODAY, out)
    return out


def run_once(*, dry_run: bool | None = None, fetch: bool = True) -> dict[str, Any]:
    """Fetch (optional) → score → steer → apply. Returns summary dict."""
    summary: dict[str, Any]
    if fetch:
        try:
            from automation.mantis_fetch import pull_today

            summary = pull_today(headed=False)
        except Exception as exc:
            _hb(f"fetch_fail {exc}")
            state = _load(STATE)
            state["last_error"] = str(exc)
            state["last_error_at"] = _utc()
            _write(STATE, state)
            return {"ok": False, "error": f"fetch_fail: {exc}"}
    else:
        summary = _load(MANTIS_TODAY)
        if not summary:
            return {"ok": False, "error": "no_mantis_snapshot"}

    saved = _save_mantis_today(summary)
    farm_ads, farm_visits = _farm_ads_used()
    score = score_levers(
        saved["impressions"],
        saved["clicks"],
        saved["ecpm"],
        saved["evcpm"],
        farm_visits=farm_visits,
    )
    ov = _load(OVERRIDES)
    cur = {k: str(v) for k, v in ov.items() if str(k).startswith("CPHARM_")}
    plan = plan_steering(
        score,
        farm_ads_used=farm_ads,
        path3_count=farm_ads,
        current_overrides=cur,
        dry_run=bool(dry_run) if dry_run is not None else False,
    )
    applied = apply_steering_plan(plan, log_dir=LOG_DIR, dry_run=dry_run)

    state = _load(STATE)
    state.update(
        {
            "last_cycle_at": _utc(),
            "last_tone": score.get("tone"),
            "last_conjunction_pct": score.get("conjunction_pct"),
            "last_mantis": {
                "impressions": saved["impressions"],
                "clicks": saved["clicks"],
                "ecpm": saved["ecpm"],
                "evcpm": saved["evcpm"],
            },
            "last_plan_reason": plan.get("reason"),
            "last_actions": plan.get("actions"),
            "next_due_hint": "120-180min or yellow/red wake",
        }
    )
    if applied.get("ok"):
        state.pop("last_error", None)
    _write(STATE, state)

    out = {
        "ok": True,
        "tone": score.get("tone"),
        "conjunction_pct": score.get("conjunction_pct"),
        "mantis": saved,
        "plan_reason": plan.get("reason"),
        "actions": plan.get("actions"),
        "applied": applied.get("applied"),
        "restart": applied.get("restart"),
        "dry_run": applied.get("dry_run"),
    }
    _hb(
        f"tone={out['tone']} conj={out['conjunction_pct']} "
        f"clk={saved['clicks']} impr={saved['impressions']} "
        f"reason={out['plan_reason']} applied={out['applied']}"
    )
    return out
