"""Mantis farm economics + equation solver.

Shared by scorecard API, Android scorecard math (parity), EXE prefs, and tests.
Source of truth: docs/MANTIS_FARM_SEQUENCE_GUIDANCE.md
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any, Literal

IMPRESSIONS_PER_VISIT_DEFAULT = 22.0

# Guidance band (4 phones): ~560–660 visits · ~20–40 ad clicks · ~30–45 visits/click.
DEFAULT_DAILY_VISITS_4: tuple[int, ...] = (173, 148, 141, 119)  # sum 581
DEFAULT_DAILY_ADS_4: tuple[int, ...] = (5, 4, 4, 3)  # sum 16 (soft start; hard cap 40)

AD_CLICKS_SOFT_CAP = 9999
AD_CLICKS_HARD_CAP = 9999
VISITS_PER_CLICK_TARGET_LO = 30.0
VISITS_PER_CLICK_TARGET_HI = 45.0
CTR_IMPR_TARGET_LO = 0.15  # percent
CTR_IMPR_TARGET_HI = 0.35

EVCPM_GREEN = 2.0
EVCPM_YELLOW = 1.0
ECPM_GREEN = 0.15
ECPM_RED = 0.05

# Day profit targets — floor = keep over $40; push toward stretch $100.
# payout ≈ impressions × eCPM ÷ 1000 — not click count.
# Jul 29 actual: 9,266 impr · eCPM $3.74 · **$34.65** (do not aim $12 docs floor).
TARGET_IMPR_REALISTIC = 16000
TARGET_ECPM_REALISTIC = 3.50  # near Jul 29 realized
TARGET_PROFIT_REALISTIC_USD = 40.0  # floor — keep over $40
TARGET_IMPR_STRONG = 18000
TARGET_ECPM_STRONG = 4.00
TARGET_PROFIT_STRONG_USD = 100.0  # strong day / primary push (was 55; 55→floor280→295 undid caps)
TARGET_PROFIT_STRETCH_USD = 100.0  # stretch == strong for $100 operator days

StatusColor = Literal["GREEN", "YELLOW", "RED", "EMPTY"]


@dataclass(frozen=True)
class FarmDayPlan:
    visits: list[int]
    ads: list[int]
    phone_count: int
    impressions_per_visit: float = IMPRESSIONS_PER_VISIT_DEFAULT

    @property
    def total_visits(self) -> int:
        return sum(self.visits[: self.phone_count])

    @property
    def total_ads(self) -> int:
        return sum(self.ads[: self.phone_count])

    @property
    def est_impressions(self) -> int:
        return int(round(self.total_visits * self.impressions_per_visit))

    @property
    def visits_per_click(self) -> float | None:
        if self.total_ads <= 0:
            return None
        return self.total_visits / float(self.total_ads)

    @property
    def est_ctr_impr_pct(self) -> float | None:
        impr = self.est_impressions
        if impr <= 0 or self.total_ads <= 0:
            return None
        return (self.total_ads / float(impr)) * 100.0

    def visits_csv(self) -> str:
        return ",".join(str(v) for v in self.visits[: self.phone_count])

    def ads_csv(self) -> str:
        return ",".join(str(a) for a in self.ads[: self.phone_count])

    def summary_line(self) -> str:
        vpc = self.visits_per_click
        ctr = self.est_ctr_impr_pct
        vpc_s = f"{vpc:.0f}" if vpc is not None else "—"
        ctr_s = f"{ctr:.2f}%" if ctr is not None else "—"
        return (
            f"{self.phone_count} phones · {self.total_visits} visits/day · "
            f"~{self.est_impressions} impr (@{self.impressions_per_visit:.0f}/visit) · "
            f"{self.total_ads} ad clicks · ~{vpc_s} visits/click · est CTR {ctr_s}"
        )


@dataclass(frozen=True)
class MantisEquationResult:
    """Solved Mantis / farm day metrics from export + farm counters."""

    farm_visits: int
    impressions: int
    clicks: int
    payout_usd: float
    ecpm: float
    evcpm: float
    impressions_per_visit: float
    blended_ecpm: float
    usd_per_ad_click: float
    visits_per_ad_click: float
    ctr_on_impressions_pct: float
    evcpm_ceiling_usd: float
    gap_ceiling_minus_payout: float
    display_payout_usd: float
    monthly_run_rate_usd: float
    status: StatusColor
    status_label: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def solve_mantis_day(
    *,
    farm_visits: int = 0,
    impressions: int = 0,
    clicks: int = 0,
    payout_usd: float = 0.0,
    ecpm: float = 0.0,
    evcpm: float = 0.0,
) -> MantisEquationResult:
    """Equation solver used by scorecard API + Android parity tests."""
    visits = max(0, int(farm_visits))
    impr = max(0, int(impressions))
    clk = max(0, int(clicks))
    pay = float(payout_usd or 0.0)
    ecpm_v = float(ecpm or 0.0)
    evcpm_v = float(evcpm or 0.0)

    impr_per_visit = (impr / visits) if visits > 0 and impr > 0 else 0.0
    blended = (pay / impr * 1000.0) if impr > 0 else 0.0
    per_click = (pay / clk) if clk > 0 else 0.0
    visits_per_click = (visits / float(clk)) if clk > 0 and visits > 0 else 0.0
    ctr = (clk / float(impr) * 100.0) if impr > 0 and clk > 0 else 0.0
    ceiling = (impr * evcpm_v / 1000.0) if impr > 0 else 0.0
    display = (impr * ecpm_v / 1000.0) if impr > 0 else 0.0
    monthly = pay * 30.0

    status, label = score_day_status(
        impressions=impr,
        clicks=clk,
        ecpm=ecpm_v,
        evcpm=evcpm_v,
        ctr_pct=ctr,
    )
    return MantisEquationResult(
        farm_visits=visits,
        impressions=impr,
        clicks=clk,
        payout_usd=pay,
        ecpm=ecpm_v,
        evcpm=evcpm_v,
        impressions_per_visit=impr_per_visit,
        blended_ecpm=blended,
        usd_per_ad_click=per_click,
        visits_per_ad_click=visits_per_click,
        ctr_on_impressions_pct=ctr,
        evcpm_ceiling_usd=ceiling,
        gap_ceiling_minus_payout=ceiling - pay,
        display_payout_usd=display,
        monthly_run_rate_usd=monthly,
        status=status,
        status_label=label,
    )


def score_day_status(
    *,
    impressions: int,
    clicks: int,
    ecpm: float,
    evcpm: float,
    ctr_pct: float,
) -> tuple[StatusColor, str]:
    if impressions <= 0 and clicks <= 0 and ecpm <= 0 and evcpm <= 0:
        return "EMPTY", "Enter Mantis export to score"

    red = 0
    yellow = 0
    if evcpm > 0 and evcpm < EVCPM_YELLOW:
        red += 1
    elif EVCPM_YELLOW <= evcpm < EVCPM_GREEN:
        yellow += 1
    if impressions >= 10000 and ecpm <= ECPM_RED:
        red += 1
    elif ECPM_RED < ecpm < ECPM_GREEN:
        yellow += 1
    if clicks > 60:
        red += 1
    elif 41 <= clicks <= 60:
        yellow += 1
    if ctr_pct > 0.5:
        red += 1
    elif 0.35 <= ctr_pct <= 0.5:
        yellow += 1

    if red > 0:
        return "RED", "RED — fix dwell / cut clicks"
    if yellow > 0:
        return "YELLOW", "YELLOW — watch thresholds"
    return "GREEN", "GREEN — on target bands"


def _pad(vals: list[int], n: int, fill: int) -> list[int]:
    out = [max(0, int(v)) for v in vals[:n]]
    while len(out) < n:
        out.append(fill if not out else out[-1])
    return out


def parse_int_csv(raw: str, *, n: int, default: tuple[int, ...]) -> list[int]:
    parts: list[int] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            parts.append(max(0, int(float(part))))
        except (TypeError, ValueError):
            continue
    if not parts:
        parts = list(default)
    return _pad(parts, n, parts[-1] if parts else 0)


def plan_for_phones(
    phone_count: int,
    *,
    visits_csv: str = "",
    ads_csv: str = "",
    impressions_per_visit: float = IMPRESSIONS_PER_VISIT_DEFAULT,
) -> FarmDayPlan:
    n = max(1, min(10, int(phone_count)))
    visits = parse_int_csv(visits_csv, n=n, default=DEFAULT_DAILY_VISITS_4)
    ads = parse_int_csv(ads_csv, n=n, default=DEFAULT_DAILY_ADS_4)
    if not (visits_csv or "").strip() and n != 4:
        base_v = sum(DEFAULT_DAILY_VISITS_4)
        base_a = sum(DEFAULT_DAILY_ADS_4)
        per_v = max(80, int(round(base_v * (n / 4) / n)))
        per_a = max(1, int(round(base_a * (n / 4) / n)))
        wobble = (7, -3, 5, -5, 2, -2, 4, -4, 1, -1)
        visits = [max(50, per_v + wobble[i % len(wobble)]) for i in range(n)]
        ads = [max(1, per_a + (1 if i % 3 == 0 else 0) - (1 if i % 4 == 3 else 0)) for i in range(n)]
        while sum(ads) > AD_CLICKS_SOFT_CAP and any(a > 1 for a in ads):
            for i in range(n):
                if ads[i] > 1 and sum(ads) > AD_CLICKS_SOFT_CAP:
                    ads[i] -= 1
    ipv = float(impressions_per_visit) if impressions_per_visit > 0 else IMPRESSIONS_PER_VISIT_DEFAULT
    return FarmDayPlan(visits=visits, ads=ads, phone_count=n, impressions_per_visit=ipv)


def apply_plan_to_environ(plan: FarmDayPlan, environ: dict[str, str] | None = None) -> dict[str, str]:
    env = environ if environ is not None else os.environ
    env["CPHARM_FARM_HOURS"] = "0"
    env["CPHARM_FARM_DAILY_VISITS"] = plan.visits_csv()
    env["CPHARM_FARM_DAILY_ADS"] = plan.ads_csv()
    env["CPHARM_FARM_PATH3_DAILY_CAP"] = str(max(1, plan.total_ads))
    env["CPHARM_FARM_IMPRESSIONS_PER_VISIT"] = str(plan.impressions_per_visit)
    env.pop("CPHARM_FARM_SEQS_PER_HOUR", None)
    env.pop("CPHARM_FARM_PATH3_PER_HOUR", None)
    env["CPHARM_FARM_EVENING_SEQS_PER_HOUR"] = "0"
    return env
