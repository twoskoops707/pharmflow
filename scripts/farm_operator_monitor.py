#!/usr/bin/env python3
"""Single operator truth file — OK/FAIL, patches, pause, profit, phones.

Written every 60s while remediator runs; also callable standalone.
"""
from __future__ import annotations

import json
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LOG = Path(r"C:\PharmFlow\logs")
OUT = LOG / "FARM_OPERATOR_TRUTH.json"
HONEST = LOG / "FARM_HONEST_NOW.txt"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _tail_results(n: int = 12) -> list[dict]:
    path = LOG / "farm_354_results.jsonl"
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    rows: list[dict] = []
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def build_truth() -> dict:
    from automation.farm_pause import is_paused, pause_state, seconds_until_resume

    prog = _load_json(LOG / "farm_354_progress.json")
    mantis = _load_json(LOG / "mantis_today_state.json")
    profit = _load_json(LOG / "farm_remediator_profit.json")
    config = _load_json(LOG / "farm_operator_config.json")
    quarantine = _load_json(LOG / "farm_seq_quarantine.json")
    results = _tail_results(20)
    ok = sum(1 for r in results if r.get("success"))
    fail = sum(1 for r in results if r.get("success") is False)
    actives = prog.get("active_sequences") or []
    phones_prog = prog.get("phones") or {}
    dash_up = False
    try:
        with socket.create_connection(("127.0.0.1", 8091), timeout=0.5):
            dash_up = True
    except OSError:
        pass
    patches_n = 0
    patch_path = LOG / "farm_seq_patches.jsonl"
    if patch_path.is_file():
        patches_n = sum(1 for _ in patch_path.read_text(encoding="utf-8", errors="replace").splitlines() if _.strip())

    return {
        "ts": _utc(),
        "paused": is_paused(),
        "pause": pause_state(),
        "seconds_until_resume": round(seconds_until_resume(), 1),
        "dash_up": dash_up,
        "dash_url": "http://127.0.0.1:8091/",
        "adb_expect": config.get("phones_expect") or prog.get("phones_expect"),
        "actives_n": len(actives) if isinstance(actives, list) else 0,
        "actives": (actives[:8] if isinstance(actives, list) else []),
        "results_window": {"ok": ok, "fail": fail, "total": len(results)},
        "last_results": [
            {
                "ok": bool(r.get("success")),
                "phone": r.get("phone"),
                "stem": (r.get("sequence") or r.get("stem") or "")[:60],
                "error": r.get("error"),
                "failed_at": r.get("failed_at"),
            }
            for r in results[-8:]
        ],
        "payout_usd": mantis.get("payout_usd"),
        "ecpm": mantis.get("ecpm"),
        "impressions": mantis.get("impressions"),
        "profit_tone": (profit.get("tone") if isinstance(profit, dict) else None),
        "operator_config": config,
        "quarantine_stems": list((quarantine.get("stems") or {}).keys())[:20],
        "seq_patches_n": patches_n,
        "phones_progress": {
            k: {
                "done": v.get("done"),
                "last_ok": (v.get("last") or {}).get("success"),
                "last_err": (v.get("last") or {}).get("error"),
            }
            for k, v in phones_prog.items()
            if isinstance(v, dict)
        },
    }


def write_truth() -> dict:
    truth = build_truth()
    LOG.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(truth, indent=2) + "\n", encoding="utf-8")
    if truth.get("paused"):
        left = int(truth.get("seconds_until_resume") or 0)
        HONEST.write_text(
            f"FARM PAUSED — resume in {left}s\n"
            f"DASH {truth.get('dash_url')}\n"
            f"operator truth: {OUT}\n",
            encoding="utf-8",
        )
    return truth


def main() -> int:
    if "--loop" in sys.argv:
        while True:
            try:
                t = write_truth()
                print(f"[monitor] paused={t.get('paused')} ok={t['results_window']['ok']} fail={t['results_window']['fail']}", flush=True)
            except Exception as exc:
                print(f"[monitor] err {exc}", flush=True)
            time.sleep(60.0)
        return 0
    print(json.dumps(write_truth(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
