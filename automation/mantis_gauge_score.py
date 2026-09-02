"""Shared Mantis sweet-spot scoring (dash gauges + autopilot).

Conjunction is money-first: payout toward stretch $100 dominates.
Secondary levers (impr / eCPM / evCPM / clicks) inform but cannot outrank $$.
"""

from __future__ import annotations

from typing import Any, Literal

from automation.mantis_farm_math import (
    TARGET_PROFIT_REALISTIC_USD,
    TARGET_PROFIT_STRETCH_USD,
)

Tone = Literal["green", "yellow", "red"]
Kind = Literal["in", "near", "out"]

# Operator dial landmarks (floor / strong mid / stretch). Catch-up budgeting may
# use a different TARGET_PROFIT_STRONG_USD; the gauge always reads these.
GAUGE_PROFIT_FLOOR_USD = float(TARGET_PROFIT_REALISTIC_USD)  # $40
GAUGE_PROFIT_STRONG_USD = 55.0
GAUGE_PROFIT_STRETCH_USD = float(TARGET_PROFIT_STRETCH_USD)  # $100

# Money must dominate; remaining weight is quality/pace only.
_W_PAYOUT = 0.70
_W_IMPR = 0.10
_W_ECPM = 0.10
_W_EVCPM = 0.07
_W_CLICKS = 0.03


def _band_score(v: float, lo: float, hi: float, hard_min: float, hard_max: float) -> float:
    if lo <= v <= hi:
        mid = (lo + hi) / 2.0
        half = (hi - lo) / 2.0 or 1.0
        return 0.75 + 0.25 * (1.0 - abs(v - mid) / half)
    if v < lo:
        span = max(1e-6, lo - hard_min)
        return max(0.0, 0.75 * ((v - hard_min) / span))
    span = max(1e-6, hard_max - hi)
    return max(0.0, 0.75 * (1.0 - (v - hi) / span))


def _payout_score(payout_usd: float, stretch_usd: float = GAUGE_PROFIT_STRETCH_USD) -> float:
    """Linear 0..1 toward stretch $ (full needle = stretch)."""
    stretch = max(1e-6, float(stretch_usd))
    return max(0.0, min(1.0, float(payout_usd or 0.0) / stretch))


def _kind_from_score(score: float) -> Kind:
    if score >= 0.72:
        return "in"
    if score >= 0.4:
        return "near"
    return "out"


def _kind_from_payout(payout_usd: float) -> Kind:
    p = float(payout_usd or 0.0)
    if p >= GAUGE_PROFIT_STRONG_USD:
        return "in"
    if p >= GAUGE_PROFIT_FLOOR_USD:
        return "near"
    return "out"


def _tone(conjunction: float) -> Tone:
    if conjunction >= 0.72:
        return "green"
    if conjunction >= 0.45:
        return "yellow"
    return "red"


def score_levers(
    impressions: float,
    clicks: float,
    ecpm: float,
    evcpm: float,
    farm_visits: float = 0.0,
    payout_usd: float = 0.0,
) -> dict[str, Any]:
    """Score today's Mantis levers — $$ toward stretch dominates conjunction.

    Returns conjunction 0..1, tone, and per-lever kind/score.
    """
    impr = float(impressions or 0.0)
    clk = float(clicks or 0.0)
    ecpm_v = float(ecpm or 0.0)
    evcpm_v = float(evcpm or 0.0)
    visits = float(farm_visits or 0.0)
    # Prefer explicit payout; else impr × eCPM / 1000.
    pay = float(payout_usd or 0.0)
    if pay <= 0 and impr > 0 and ecpm_v > 0:
        pay = impr * ecpm_v / 1000.0

    s_impr = _band_score(impr, 15000.0, 18000.0, 0.0, 22000.0)
    if 20.0 <= clk <= 40.0:
        s_clk = _band_score(clk, 20.0, 40.0, 0.0, 60.0)
    elif clk < 20.0:
        s_clk = _band_score(clk, 20.0, 40.0, 0.0, 60.0) * 0.9
    else:
        # Over hard sweet edge — burns money.
        s_clk = max(0.0, 1.0 - (clk - 40.0) / 40.0) * 0.5

    if ecpm_v <= 0:
        s_ecpm = 0.0
    elif ecpm_v >= 0.15:
        s_ecpm = min(1.0, 0.55 + (ecpm_v - 0.15) / 1.5)
    else:
        s_ecpm = max(0.0, (ecpm_v / 0.15) * 0.4)

    if evcpm_v <= 0:
        s_evcpm = 0.0
    elif evcpm_v >= 2.0:
        s_evcpm = min(1.0, 0.7 + (evcpm_v - 2.0) / 4.0)
    elif evcpm_v >= 1.0:
        s_evcpm = 0.35 + 0.3 * (evcpm_v - 1.0)
    else:
        s_evcpm = (evcpm_v / 1.0) * 0.35

    s_vis = _band_score(visits, 560.0, 660.0, 0.0, 800.0) if visits > 0 else 0.0
    s_pay = _payout_score(pay)

    conj = (
        s_pay * _W_PAYOUT
        + s_impr * _W_IMPR
        + s_ecpm * _W_ECPM
        + s_evcpm * _W_EVCPM
        + s_clk * _W_CLICKS
    )
    tone = _tone(conj)

    def lever(name: str, value: float, score: float, kind: Kind | None = None) -> dict[str, Any]:
        return {
            "name": name,
            "value": value,
            "score": round(score, 4),
            "kind": kind if kind is not None else _kind_from_score(score),
        }

    return {
        "conjunction": conj,
        "conjunction_pct": int(round(conj * 100)),
        "tone": tone,
        "payout_progress": round(s_pay, 4),
        "payout_usd": round(pay, 2),
        "targets": {
            "floor_usd": GAUGE_PROFIT_FLOOR_USD,
            "strong_usd": GAUGE_PROFIT_STRONG_USD,
            "stretch_usd": GAUGE_PROFIT_STRETCH_USD,
        },
        "weights": {
            "payout": _W_PAYOUT,
            "impressions": _W_IMPR,
            "ecpm": _W_ECPM,
            "evcpm": _W_EVCPM,
            "clicks": _W_CLICKS,
        },
        "levers": {
            "payout": lever("payout", pay, s_pay, _kind_from_payout(pay)),
            "impressions": lever("impressions", impr, s_impr),
            "clicks": lever("clicks", clk, s_clk),
            "ecpm": lever("ecpm", ecpm_v, s_ecpm),
            "evcpm": lever("evcpm", evcpm_v, s_evcpm),
            "visits": lever("visits", visits, s_vis),
        },
    }
