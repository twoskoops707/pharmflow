"""
Mantis farm scorecard API — targets, humanization bands, live scheduler snapshot.

Served at GET /api/scorecard for the CPharmScorecard Android app and operators.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Dwell bands (seconds) — random uniform in [min, max] per wait step; never 0 on tab tour.
HUMANIZATION_BANDS: dict[str, dict[str, float]] = {
    "after_tab_open_sec": {"min": 3.0, "max": 5.0, "never": 0.0},
    "after_tab_switch_sec": {"min": 3.0, "max": 5.0, "never": 0.0},
    "after_scroll_bottom_sec": {"min": 2.0, "max": 4.0, "never": 0.0},
    "after_scroll_up_sec": {"min": 2.0, "max": 3.0, "never": 0.0},
    "before_leave_tab_sec": {"min": 1.0, "max": 2.0, "never": 0.0},
    "micro_gap_sec": {"min": 0.12, "max": 0.55, "never": 0.0},
    "after_ad_tap_sec": {"min": 30.0, "max": 45.0, "never": 25.0},
    "tap_pre_wait_ms": {"min": 200.0, "max": 500.0, "never": 0.0},
    "tap_jitter_px": {"min": 14.0, "max": 28.0, "never": 0.0},
}

TARGETS: dict[str, Any] = {
    "phones_default": 4,
    "hits_per_day_per_phone": [140, 165],
    "visits_daily": [560, 660],
    "impressions_daily": [10000, 20000],
    "impressions_sweet_spot": [15000, 18000],
    "ad_clicks_daily": [20, 40],
    "ad_clicks_hard_cap": 40,
    "impressions_per_visit": [18, 28],
    "ctr_on_impressions_pct": [0.15, 0.35],
    "evcpm_green": 2.0,
    "evcpm_yellow": 1.0,
    "ecpm_green": 0.15,
    "ecpm_red": 0.05,
    "monthly_scenarios": [
        {"label": "Floor (evCPM broken)", "daily_impr": 17000, "ecpm": 0.05},
        {"label": "Jul 25 actual", "daily_impr": 11000, "ecpm": 0.56},
        {"label": "Realistic target", "daily_impr": 16000, "ecpm": 0.75},
        {"label": "Strong target", "daily_impr": 18000, "ecpm": 1.0},
        {"label": "Stretch", "daily_impr": 18000, "ecpm": 2.0},
    ],
}

FORMULAS: dict[str, str] = {
    "payout_display": "impressions × eCPM ÷ 1,000",
    "blended_ecpm": "payout ÷ impressions × 1,000",
    "impressions_per_visit": "impressions ÷ farm_visits",
    "usd_per_ad_click": "payout ÷ mantis_clicks",
    "visits_per_ad_click": "farm_visits ÷ mantis_clicks",
    "evcpm_ceiling_usd": "impressions × evCPM ÷ 1,000",
    "monthly_run_rate": "payout × 30",
    "monthly_net": "(payout × 30) − monthly_operating_costs",
}

TAB_LOAD_NOTE = (
    "DabFlow calls mantis.push(['display','refresh']) on every tab switch. "
    "Premium/slow ads load at the TOP after refresh — wait 3–5 s BEFORE first scroll. "
    "Immediate scroll marks ads unviewed → eCPM ~$0.05, evCPM crash (Jul 26 pattern)."
)

DOCS_INDEX: list[dict[str, str]] = [
    {"path": "docs/MANTIS_FARM_SEQUENCE_GUIDANCE.md", "topic": "Full operator + agent handoff"},
    {"path": "docs/MANTIS_FARM_PHONE_SCALING.md", "topic": "Phone count scaling limits (N phones)"},
    {"path": "docs/MANTIS_FARM_DAILY_SCORECARD.md", "topic": "Daily scorecard formulas"},
    {"path": "docs/MANTIS_FARM_DESKTOP_CURSOR_SUMMARY.md", "topic": "Desktop Cursor one-page summary"},
    {"path": "docs/DABFLOW_FLOW_FROM_REPO.md", "topic": "Tab flow and Mantis zones"},
]

# Per-phone baselines (4-phone farm calibrated Jul 2026 export).
_BASE_PHONES = 4
_HITS_PER_PHONE_SWEET = (140, 165)
_HITS_PER_PHONE_BAND = (115, 180)
_IMPR_PER_PHONE_SWEET = (3750, 4500)  # 15k–18k ÷ 4
_IMPR_PER_VISIT_BAND = (18, 28)
_IMPR_PER_VISIT_CALIBRATE = 22
_AD_CLICKS_PER_PHONE_BAND = (5, 10)
_AD_CLICKS_SWEET_HIGH_PER_PHONE = 35 / _BASE_PHONES  # ~8.75; 35 cap at 4 phones


def scaling_targets(phone_count: int) -> dict[str, Any]:
    """
    Farm-wide limits for ``phone_count`` online phones.

    Per-phone scheduler quota (`hits_per_day`) does **not** scale — only farm totals and caps.
    Desktop Cursor: call whenever N changes. See ``docs/MANTIS_FARM_PHONE_SCALING.md``.
    """
    n = max(1, min(int(phone_count), 24))
    hits_sweet = [_HITS_PER_PHONE_SWEET[0] * n, _HITS_PER_PHONE_SWEET[1] * n]
    hits_band = [_HITS_PER_PHONE_BAND[0] * n, _HITS_PER_PHONE_BAND[1] * n]
    impr_sweet = [_IMPR_PER_PHONE_SWEET[0] * n, _IMPR_PER_PHONE_SWEET[1] * n]
    impr_band = [
        hits_band[0] * _IMPR_PER_VISIT_BAND[0],
        hits_band[1] * _IMPR_PER_VISIT_BAND[1],
    ]
    clicks_band = [_AD_CLICKS_PER_PHONE_BAND[0] * n, _AD_CLICKS_PER_PHONE_BAND[1] * n]
    clicks_sweet_high = max(clicks_band[0], round(_AD_CLICKS_SWEET_HIGH_PER_PHONE * n))
    hard_cap = round(40 * n / _BASE_PHONES)
    sweet_mid_impr = (impr_sweet[0] + impr_sweet[1]) // 2
    return {
        "phone_count": n,
        "hits_per_day_per_phone": list(_HITS_PER_PHONE_SWEET),
        "hits_per_day_per_phone_band": list(_HITS_PER_PHONE_BAND),
        "farm_visits_daily_sweet": hits_sweet,
        "farm_visits_daily_band": hits_band,
        "impressions_daily_sweet": impr_sweet,
        "impressions_daily_band": [int(impr_band[0]), int(impr_band[1])],
        "impressions_per_visit_band": list(_IMPR_PER_VISIT_BAND),
        "impressions_per_visit_calibrate": _IMPR_PER_VISIT_CALIBRATE,
        "ad_clicks_daily_sweet": [clicks_band[0], clicks_sweet_high],
        "ad_clicks_daily_band": clicks_band,
        "ad_clicks_hard_cap": hard_cap,
        "browse_only_after_clicks": hard_cap,
        "ctr_on_impressions_pct": [0.15, 0.35],
        "evcpm_green": 2.0,
        "evcpm_yellow": 1.0,
        "ecpm_green": 0.15,
        "ecpm_red": 0.05,
        "ecpm_red_min_impressions": round(10000 * n / _BASE_PHONES),
        "monthly_scenarios": [
            {
                "label": "Floor (evCPM broken)",
                "daily_impr": impr_sweet[1],
                "ecpm": 0.05,
            },
            {
                "label": "Jul 25 style (scaled impr)",
                "daily_impr": round(11000 * n / _BASE_PHONES),
                "ecpm": 0.56,
            },
            {
                "label": "Realistic target",
                "daily_impr": sweet_mid_impr,
                "ecpm": 0.75,
            },
            {
                "label": "Strong target",
                "daily_impr": impr_sweet[1],
                "ecpm": 1.0,
            },
            {
                "label": "Stretch",
                "daily_impr": impr_sweet[1],
                "ecpm": 2.0,
            },
        ],
        "scaling_doc": "docs/MANTIS_FARM_PHONE_SCALING.md",
    }


# Operator scale-up path: add one phone at a time (4 → 10 typical farm).
_INCREMENTAL_PHONE_COUNTS_DEFAULT = list(range(4, 11))


def scaling_incremental_grid(
    phone_counts: list[int] | None = None,
    *,
    operating_costs: dict[str, Any] | None = None,
    realistic_ecpm: float = 0.75,
    strong_ecpm: float = 1.0,
) -> dict[str, Any]:
    """
    Precomputed farm limits and net profit for each phone count (incremental scale-up).

    Desktop Cursor + APK: compare N=4,5,6…10 before adding the next phone.
    Operating costs are farm-fixed (AI subscription does not scale per phone).
    """
    counts = phone_counts or _INCREMENTAL_PHONE_COUNTS_DEFAULT
    costs = dict(DEFAULT_OPERATING_COSTS)
    if operating_costs:
        costs.update(operating_costs)
    monthly_costs = operating_costs_monthly_usd(costs)
    rows: list[dict[str, Any]] = []
    for raw_n in counts:
        try:
            n = max(1, min(int(raw_n), 24))
        except (TypeError, ValueError):
            continue
        t = scaling_targets(n)
        impr_lo, impr_hi = t["impressions_daily_sweet"]
        impr_mid = (impr_lo + impr_hi) // 2
        visits_lo, visits_hi = t["farm_visits_daily_sweet"]
        daily_realistic = impr_mid * realistic_ecpm / 1000.0
        daily_strong = impr_hi * strong_ecpm / 1000.0
        monthly_net_realistic = daily_realistic * 30.0 - monthly_costs
        monthly_net_strong = daily_strong * 30.0 - monthly_costs
        rows.append(
            {
                "phone_count": n,
                "farm_visits_daily_sweet": [visits_lo, visits_hi],
                "impressions_daily_sweet": [impr_lo, impr_hi],
                "impressions_daily_mid": impr_mid,
                "ad_clicks_hard_cap": t["ad_clicks_hard_cap"],
                "hits_per_day_per_phone": t["hits_per_day_per_phone"],
                "daily_gross_realistic_usd": round(daily_realistic, 2),
                "daily_gross_strong_usd": round(daily_strong, 2),
                "monthly_net_realistic_usd": round(monthly_net_realistic, 2),
                "monthly_net_strong_usd": round(monthly_net_strong, 2),
                "monthly_costs_usd": round(monthly_costs, 2),
            }
        )
    return {
        "phone_counts": [r["phone_count"] for r in rows],
        "increment_by_one": "Add one phone → re-read row for N+1; per-phone hits_per_day stays 140–165.",
        "realistic_ecpm": realistic_ecpm,
        "strong_ecpm": strong_ecpm,
        "monthly_costs_total_usd": round(monthly_costs, 2),
        "rows": rows,
        "scaling_doc": "docs/MANTIS_FARM_PHONE_SCALING.md",
    }


# Default monthly operating costs (USD) — override via scorecard_state.json "operating_costs".
DEFAULT_OPERATING_COSTS: dict[str, Any] = {
    "ai_tools_usd_month": 60.0,
    "ai_tools_label": "Cursor / AI agents (operator default)",
    "power_usd_month": 15.0,
    "power_label": "PC + MuMu farm electricity (estimate)",
    "other_usd_month": 0.0,
    "other_label": "Optional (internet, VPN, etc.)",
    "notes": (
        "Power is small at farm scale; AI subscription is the main fixed cost. "
        "Set actuals in scorecard_state.json or CPharmScorecard app."
    ),
}


def operating_costs_monthly_usd(costs: dict[str, Any] | None = None) -> float:
    c = costs or DEFAULT_OPERATING_COSTS
    total = 0.0
    for key in ("ai_tools_usd_month", "power_usd_month", "other_usd_month"):
        try:
            total += float(c.get(key, 0) or 0)
        except (TypeError, ValueError):
            pass
    return total


def profitability_projection(
    phone_count: int,
    *,
    operating_costs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Gross Mantis scenarios minus monthly operating costs for ``phone_count``."""
    scaled = scaling_targets(phone_count)
    costs = dict(DEFAULT_OPERATING_COSTS)
    if operating_costs:
        costs.update(operating_costs)
    monthly_costs = operating_costs_monthly_usd(costs)
    daily_costs = monthly_costs / 30.0
    scenarios_out: list[dict[str, Any]] = []
    for row in scaled.get("monthly_scenarios", []):
        try:
            impr = int(row.get("daily_impr", 0))
            ecpm = float(row.get("ecpm", 0))
        except (TypeError, ValueError):
            continue
        daily_gross = impr * ecpm / 1000.0
        monthly_gross = daily_gross * 30.0
        monthly_net = monthly_gross - monthly_costs
        scenarios_out.append(
            {
                "label": row.get("label", ""),
                "daily_impr": impr,
                "ecpm": ecpm,
                "daily_gross_usd": round(daily_gross, 2),
                "monthly_gross_usd": round(monthly_gross, 2),
                "monthly_costs_usd": round(monthly_costs, 2),
                "monthly_net_usd": round(monthly_net, 2),
                "daily_net_usd": round(monthly_net / 30.0, 2),
            }
        )
    return {
        "phone_count": scaled.get("phone_count"),
        "operating_costs": costs,
        "monthly_costs_total_usd": round(monthly_costs, 2),
        "daily_costs_usd": round(daily_costs, 2),
        "break_even_daily_gross_usd": round(daily_costs, 2),
        "break_even_monthly_gross_usd": round(monthly_costs, 2),
        "scenarios": scenarios_out,
        "formula_net_monthly": "monthly_gross − ai_tools − power − other",
        "formula_monthly_gross": "daily_impr × eCPM ÷ 1,000 × 30",
    }


_WATCHDOG_LOG_CANDIDATES = ("logs/cursor_monitor_loop.log", "logs/watchdog.log", "logs/farm_354.log")


def _live_farm_facts() -> dict[str, Any]:
    """Parse the watchdog's most recent ``FACT $=.. clk=.. impr=..`` line.

    The dashboard KPI is flat-zero when ``scorecard_state.json`` hasn't been
    written yet, even though the Mantis farm is genuinely earning. The watchdog
    (tools/cpharm_watchdog.py / agent loop) already logs real totals as
    ``FACT $=24.26 clk=32 impr=31834`` — read the newest such line and overlay
    it so the KPI strip shows live income instead of $0.
    """
    newest: tuple[float, dict[str, Any]] | None = None
    for rel in _WATCHDOG_LOG_CANDIDATES:
        p = Path(rel)
        if not p.is_file():
            continue
        try:
            with p.open("r", encoding="utf-8", errors="replace") as fh:
                # walk backwards: newer lines are at the tail; parse all, keep max ts
                for line in fh:
                    m = re.search(r"FACT \$=([0-9.]+) clk=([0-9]+) impr=([0-9]+)", line)
                    if not m:
                        continue
                    ts = 0.0
                    for t in (line[0:26],):
                        try:
                            import datetime as _dt
                            cand = _dt.datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
                            ts = cand
                        except Exception:
                            pass
                    facts = {
                        "payout_usd": float(m.group(1)),
                        "clicks": int(m.group(2)),
                        "impressions": int(m.group(3)),
                    }
                    if newest is None or ts >= newest[0]:
                        newest = (ts, facts)
        except OSError:
            continue
    if newest is None:
        return {}
    facts = dict(newest[1])
    try:
        if facts.get("impressions") and facts.get("payout_usd"):
            facts["ecpm"] = round(facts["payout_usd"] / facts["impressions"] * 1000.0, 2)
            facts["ctr_pct"] = round(
                facts["clicks"] / facts["impressions"] * 100.0, 3
            ) if facts.get("impressions") else 0.0
    except (ZeroDivisionError, TypeError):
        pass
    facts["source"] = "watchdog_facts"
    return facts


def build_money_kpis(
    *,
    list_phones_fn,
    recordings_dir: Path,
) -> dict[str, Any]:
    """Lean revenue/money KPI payload fed by existing scorecard state.

    Lightweight sibling of ``build_scorecard_payload`` for the dashboard KPI
    strip: reads persisted Mantis/operator state + profitability projection
    without the heavy phones/targets/docs payload.

    When operator state is empty (scorecard_state.json not yet written), falls
    back to the watchdog's live ``FACT`` totals so the strip never shows $0
    while the farm is genuinely earning.
    """
    phones = list_phones_fn()
    online = [p for p in phones if p.get("running") or p.get("status") == "device"]
    n = len(online) if online else TARGETS.get("phones_default", 4)
    op = _load_operator_mantis_state(recordings_dir)
    if not op:
        op = dict(_live_farm_facts())
    costs = op.get("operating_costs") if isinstance(op.get("operating_costs"), dict) else None
    profit = profitability_projection(n, operating_costs=costs)
    best = None
    for s in profit.get("scenarios", []):
        if best is None or s.get("monthly_net_usd", 0) > best.get("monthly_net_usd", 0):
            best = s
    return {
        "ok": True,
        "phone_count": n,
        "revenue_today_usd": round(float(op.get("payout_usd") or 0.0), 2),
        "impressions": int(op.get("impressions") or 0),
        "clicks": int(op.get("clicks") or 0),
        "ecpm": float(op.get("ecpm") or 0.0),
        "evcpm": float(op.get("evcpm") or 0.0),
        "ctr_pct": float(op.get("ctr_pct") or 0.0),
        "farm_visits": int(op.get("farm_visits") or 0),
        "farm_ad_clicks": int(op.get("farm_ad_clicks") or 0),
        "as_of": op.get("date") or op.get("source"),
        "projected": {
            "daily_gross_usd": best.get("daily_gross_usd", 0) if best else 0,
            "daily_net_usd": best.get("daily_net_usd", 0) if best else 0,
            "monthly_gross_usd": best.get("monthly_gross_usd", 0) if best else 0,
            "monthly_net_usd": best.get("monthly_net_usd", 0) if best else 0,
            "daily_impr": best.get("daily_impr", 0) if best else 0,
        },
    }


def _scorecard_state_path(recordings_dir: Path) -> Path:
    return recordings_dir / "scorecard_state.json"


def _money_history_path(recordings_dir: Path) -> Path:
    return recordings_dir / "money_history.json"


def _load_money_history(recordings_dir: Path) -> dict[str, Any]:
    p = _money_history_path(recordings_dir)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError, TypeError):
        return {}


def _save_money_history(recordings_dir: Path, hist: dict[str, Any]) -> None:
    p = _money_history_path(recordings_dir)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(hist, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def _upsert_money_day(recordings_dir: Path, state: dict[str, Any]) -> None:
    """Record today's revenue/impressions snapshot into ``money_history.json``.

    Keyed by ``date`` (ISO day) so each phone report overwrites today's row
    and older days are kept for dashboard trend charts. Best values win.
    """
    date = str(state.get("date") or "")
    if not date:
        return
    day = date[:10]
    hist = _load_money_history(recordings_dir)
    days = hist.setdefault("days", {})
    cur = days.get(day, {})

    def _better(key, conv):
        try:
            nv = conv(state.get(key))
        except (TypeError, ValueError):
            return
        ov = cur.get(key)
        try:
            if ov is None or conv(ov) < nv:
                cur[key] = nv
        except (TypeError, ValueError):
            cur[key] = nv

    # State stores ``payout_usd``; history stores ``revenue_usd`` to match
    # the dashboard's KPI field name. Best value wins within a day.
    try:
        nv = float(state.get("payout_usd"))
    except (TypeError, ValueError):
        nv = None
    if nv is not None:
        ov = cur.get("revenue_usd")
        if ov is None or float(ov) < nv:
            cur["revenue_usd"] = nv
    _better("impressions", int)
    _better("clicks", int)
    _better("ecpm", float)
    _better("evcpm", float)
    _better("farm_visits", int)
    _better("farm_ad_clicks", int)
    if state.get("phone_count") is not None:
        cur["phone_count"] = state.get("phone_count")
    days[day] = cur
    # Keep only the most recent 45 days to bound file size.
    ordered = sorted(days.keys())
    for stale in ordered[:-45]:
        days.pop(stale, None)
    _save_money_history(recordings_dir, hist)


def build_money_history(
    recordings_dir: Path,
    *,
    days: int | None = None,
) -> list[dict[str, Any]]:
    """Return recent money history rows (oldest→newest) for dashboard charts."""
    hist = _load_money_history(recordings_dir)
    rows = hist.get("days", {})
    ordered = sorted(rows.keys())
    if days is not None:
        ordered = ordered[-days:]
    out = []
    for day in ordered:
        row = dict(rows[day])
        row["date"] = day
        out.append(row)
    return out


def _load_operator_mantis_state(recordings_dir: Path) -> dict[str, Any]:
    p = _scorecard_state_path(recordings_dir)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError, TypeError):
        return {}


def build_scorecard_payload(
    *,
    list_phones_fn,
    recordings_dir: Path,
    listen_host: str,
    listen_port: int,
) -> dict[str, Any]:
    """Build JSON payload for GET /api/scorecard."""
    phones = list_phones_fn()
    online = [p for p in phones if p.get("running") or p.get("status") == "device"]

    sched: dict[str, Any] = {}
    visits_today = 0
    visits_remaining = 0
    try:
        from scheduler import PHONE_SCHED, RUNNING, _sched_lock

        with _sched_lock:
            snap = {s: dict(info) for s, info in PHONE_SCHED.items()}
            running_snap = dict(RUNNING)
        for serial, info in snap.items():
            times = info.get("times", [])
            idx = int(info.get("idx", 0))
            fired = idx
            remaining = max(0, len(times) - idx)
            visits_today += fired
            visits_remaining += remaining
            sched[serial] = {
                "hits_per_day": info.get("hits", 0),
                "fired_today": fired,
                "remaining": remaining,
                "running": running_snap.get(serial, False),
            }
    except Exception:
        sched = {}

    operator = _load_operator_mantis_state(recordings_dir)

    n = len(online) if online else TARGETS.get("phones_default", 4)
    scaled = scaling_targets(n)
    cap = scaled["ad_clicks_hard_cap"]
    op_costs = operator.get("operating_costs") if isinstance(operator.get("operating_costs"), dict) else None
    profit = profitability_projection(n, operating_costs=op_costs)
    incremental = scaling_incremental_grid(operating_costs=op_costs)

    return {
        "ok": True,
        "farm": {
            "phones_online": len(online),
            "phones_total": len(phones),
            "phones": phones,
            "visits_today": visits_today,
            "visits_remaining_today": visits_remaining,
            "scheduler": sched,
            "dashboard_url": f"http://{listen_host}:{listen_port}",
        },
        "operator_mantis": operator,
        "targets": scaled,
        "targets_baseline_4_phone": TARGETS,
        "operating_costs": profit["operating_costs"],
        "profitability": profit,
        "scaling_incremental": incremental,
        "humanization": HUMANIZATION_BANDS,
        "formulas": FORMULAS,
        "tab_load_note": TAB_LOAD_NOTE,
        "docs": DOCS_INDEX,
        "profitability_rules": [
            "Payout ≈ impressions × eCPM ÷ 1,000 — not click count at farm scale.",
            "evCPM ≥ $2 via 3–5 s random dwell after tab open (never zero waits).",
            f"Cap Mantis ad clicks per scaling_targets(N); browse-only after {cap} (N={n}).",
            "~70–85% sessions: 0 ad clicks; 0–1 per identity.",
            "CPHARM_HUMAN_VARIATION=1 always on farm.",
            "Do not cut visits because impressions are high (~22 impr/visit is normal).",
            "New phone: read docs/MANTIS_FARM_PHONE_SCALING.md + scaling_targets(N+1).",
            "Scale incrementally N=4…10: compare scaling_incremental grid before adding one phone.",
        ],
    }


def save_operator_mantis_state(recordings_dir: Path, data: dict[str, Any]) -> dict[str, Any]:
    """Persist Mantis export fields from phone POST /api/scorecard/mantis."""
    allowed = (
        "date",
        "impressions",
        "clicks",
        "payout_usd",
        "ecpm",
        "evcpm",
        "ctr_pct",
        "farm_visits",
        "farm_ad_clicks",
        "phone_count",
        "operating_costs",
    )
    clean: dict[str, Any] = {}
    for key in allowed:
        if key in data:
            clean[key] = data[key]
    p = _scorecard_state_path(recordings_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
    _upsert_money_day(recordings_dir, clean)
    return clean
