"""Shared Mantis sweet-spot scoring (dash gauges + autopilot)."""

from __future__ import annotations

from typing import Any, Literal

Tone = Literal["green", "yellow", "red"]
Kind = Literal["in", "near", "out"]


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


def _kind_from_score(score: float) -> Kind:
    if score >= 0.72:
        return "in"
    if score >= 0.4:
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
) -> dict[str, Any]:
    """Score today's Mantis levers against sweet-spot bands.

    Returns conjunction 0..1, tone, and per-lever kind/score.
    """
    impr = float(impressions or 0.0)
    clk = float(clicks or 0.0)
    ecpm_v = float(ecpm or 0.0)
    evcpm_v = float(evcpm or 0.0)
    visits = float(farm_visits or 0.0)

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

    conj = s_impr * 0.28 + s_clk * 0.18 + s_ecpm * 0.22 + s_evcpm * 0.32
    tone = _tone(conj)

    def lever(name: str, value: float, score: float) -> dict[str, Any]:
        return {
            "name": name,
            "value": value,
            "score": round(score, 4),
            "kind": _kind_from_score(score),
        }

    return {
        "conjunction": conj,
        "conjunction_pct": int(round(conj * 100)),
        "tone": tone,
        "levers": {
            "impressions": lever("impressions", impr, s_impr),
            "clicks": lever("clicks", clk, s_clk),
            "ecpm": lever("ecpm", ecpm_v, s_ecpm),
            "evcpm": lever("evcpm", evcpm_v, s_evcpm),
            "visits": lever("visits", visits, s_vis),
        },
    }
