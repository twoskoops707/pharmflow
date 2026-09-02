#!/usr/bin/env python3
"""Mantis → score → steer → apply. Closes the dash feedback loop.

  py -u scripts/mantis_autopilot.py --once
  py -u scripts/mantis_autopilot.py          # loop (2–3h + yellow/red wake)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import automation.no_window  # noqa: E402,F401

from automation.mantis_autopilot_cycle import LOG_DIR, STATE, run_once

WAKE = LOG_DIR / "autopilot_wake.flag"
HB = LOG_DIR / "mantis_autopilot_heartbeat.txt"


def _hb(msg: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        HB.write_text(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n", encoding="utf-8")
    except OSError:
        pass


def _load_state() -> dict:
    if not STATE.is_file():
        return {}
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _sleep_until_next() -> None:
    delay = random.randint(120 * 60, 180 * 60)
    end = time.time() + delay
    while time.time() < end:
        if WAKE.is_file():
            try:
                WAKE.unlink()
            except OSError:
                pass
            return
        state = _load_state()
        tone = str(state.get("last_tone") or "")
        if tone in ("yellow", "red"):
            last = state.get("last_cycle_at") or ""
            try:
                ts = datetime.fromisoformat(str(last).replace("Z", "+00:00")).timestamp()
                if time.time() - ts > 900:
                    return
            except Exception:
                return
        time.sleep(20)


def main() -> int:
    ap = argparse.ArgumentParser(description="Mantis gauge autopilot")
    ap.add_argument("--once", action="store_true", help="Single cycle then exit")
    ap.add_argument("--no-fetch", action="store_true", help="Score last saved Mantis only")
    ap.add_argument("--dry-run", action="store_true", help="Log plan without writing overrides")
    args = ap.parse_args()

    if args.once:
        out = run_once(dry_run=True if args.dry_run else None, fetch=not args.no_fetch)
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok") else 1

    _hb("autopilot loop start")
    while True:
        try:
            out = run_once(dry_run=True if args.dry_run else None, fetch=True)
            print(json.dumps(out), flush=True)
        except Exception as exc:
            _hb(f"cycle_err {exc}")
            print(json.dumps({"ok": False, "error": str(exc)}), flush=True)
        _sleep_until_next()


if __name__ == "__main__":
    raise SystemExit(main())
