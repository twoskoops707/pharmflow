#!/usr/bin/env python3
"""Headless Mantis cookie refresh + today metrics into dash state.

No visible browser. No webbrowser.open. Uses pythonw-friendly headless Playwright.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["PHARMFLOW_MANTIS_ALLOW_HEADED"] = "0"
os.environ["PHARMFLOW_MANTIS_SKIP_PLAYWRIGHT"] = "0"

import automation.no_window  # noqa: E402,F401

from automation.mantis_fetch import (  # noqa: E402
    LOG_DIR,
    fetch_today,
    load_cookie_header,
    pull_today_playwright,
    save_cookie_header,
    save_operator_state,
)


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    summary = None
    err = ""
    # Prefer existing cookie if it has a real session (not only __cf_bm).
    cookie = load_cookie_header() or ""
    if cookie and (
        "connect.sid" in cookie
        or (cookie.count("=") >= 3 and not cookie.strip().startswith("__cf_bm="))
    ):
        try:
            summary = fetch_today(cookie)
        except Exception as exc:
            err = f"cookie_fetch:{exc}"
            summary = None
    if summary is None:
        try:
            summary = pull_today_playwright(headed=False)
        except Exception as exc:
            err = f"playwright:{exc}"
            print(f"FAIL {err}", flush=True)
            return 2
    path = save_operator_state(summary)
    # Also write the dash-facing snapshot shape.
    today = {
        "date": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d"),
        "impressions": summary.get("impressions"),
        "clicks": summary.get("clicks"),
        "payout_usd": summary.get("payout_usd"),
        "ecpm": summary.get("ecpm"),
        "evcpm": summary.get("evcpm"),
        "receivable_usd": summary.get("receivable_usd"),
        "paid_to_date_usd": summary.get("paid_to_date_usd"),
        "lifetime_earnings_usd": summary.get("lifetime_earnings_usd"),
        "updated": datetime.now(timezone.utc).isoformat(),
        "source": summary.get("source") or "mantis_headless",
    }
    (LOG_DIR / "mantis_today_state.json").write_text(
        json.dumps(today, indent=2) + "\n", encoding="utf-8"
    )
    # Refresh money health so dash gauges move.
    money = {
        "ts": today["updated"],
        "money_ok": float(today.get("payout_usd") or 0) > 0
        or int(today.get("impressions") or 0) > 0,
        "alert": False,
        "problems": [],
        "payout_usd": float(today.get("payout_usd") or 0),
        "ecpm": float(today.get("ecpm") or 0),
        "impressions": int(today.get("impressions") or 0),
        "ssp": {"paying": "?", "house": "?", "has_paying_fill": False},
    }
    (LOG_DIR / "FARM_MONEY_HEALTH.json").write_text(
        json.dumps(money, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"OK path={path} $={today.get('payout_usd')} "
        f"impr={today.get('impressions')} clk={today.get('clicks')} "
        f"ecpm={today.get('ecpm')}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
