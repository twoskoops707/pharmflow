#!/usr/bin/env python3
"""Cursor assigns FREEBUFF work queue — written to AGENT_UNISON.json."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = Path(r"C:\PharmFlow\logs")
BOARD = LOG / "AGENT_UNISON.json"
sys.path.insert(0, str(ROOT))


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    mantis: dict = {}
    try:
        mantis = json.loads((LOG / "mantis_today_state.json").read_text(encoding="utf-8-sig"))
    except Exception:
        pass

    board: dict = {}
    if BOARD.is_file():
        try:
            board = json.loads(BOARD.read_text(encoding="utf-8-sig"))
        except Exception:
            board = {}

    tasks = [
        {
            "id": "flat_dollar_fix",
            "owner": "freebuff",
            "priority": 1,
            "reason": f"payout=${mantis.get('payout_usd')} clicks={mantis.get('clicks')} — verify flat, run evaluate+remediate",
            "script": "scripts/agent_unison_freebuff_tick.py",
        },
        {
            "id": "ssp_paying_burst",
            "owner": "freebuff",
            "priority": 2,
            "reason": "keep paying inventory >=3; prefetch_ssp_ads_prefer_paying if house-only",
            "script": "scripts/agent_unison_freebuff_tick.py",
        },
        {
            "id": "path3_ok_monitor",
            "owner": "freebuff",
            "priority": 3,
            "reason": "count P3-AD OK in farm_354.log; kill dump fighters if ok=0",
            "script": "scripts/agent_unison_freebuff_tick.py",
        },
        {
            "id": "money_tick",
            "owner": "freebuff",
            "priority": 4,
            "reason": "probe SSP + update AGENT_UNISON farm_status",
            "script": "scripts/agent_unison_freebuff_tick.py",
        },
    ]

    board["freebuff_queue"] = tasks
    board["freebuff_assigned_by"] = "cursor"
    board["freebuff_assigned_at"] = _utc()
    board["cursor_note"] = (
        "FREEBUFF: run agent_unison_freebuff_tick.py every 45s. "
        "Flat $ + impr up + clk flat = farm broken until P3-AD OK in log."
    )
    board["updated"] = _utc()
    BOARD.write_text(json.dumps(board, indent=2) + "\n", encoding="utf-8")
    (LOG / "AGENT_COORD_FREEBUFF.flag").write_text(_utc(), encoding="utf-8")
    print("ASSIGNED", len(tasks), "tasks to FREEBUFF", flush=True)
    for t in tasks:
        print(f"  [{t['priority']}] {t['id']}: {t['reason']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
