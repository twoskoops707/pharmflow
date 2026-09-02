"""
Path Mix Calculator — find the optimal daily allocation across Path 1 (browse-only),
Path 2 (ad-click), and Path 3 (mantis-hardcode) for maximum farm revenue.

Revenue model:
  Path 1 (browse-only): impressions × eCPM ÷ 1000. Zero click risk.
  Path 2 (ad-click):    impressions × eCPM ÷ 1000 + one CPC click per visit.
  Path 3 (mantis-hardcode): impressions × eCPM ÷ 1000 + off-site ad network payout.

Constraints:
  - Farm-wide ad click HARD CAP: 20–40/day (scales with phone count).
  - CTR on impressions target: 0.15–0.35%.
  - Visits per click target: 30–45.
  - Each identity gets 0–1 clicks max.
  - ~22 impressions per visit (5-tab tour).
  - Not every visit clicks an ad — most are browse-only.

Source of truth: docs/MANTIS_FARM_SEQUENCE_GUIDANCE.md
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

# ── Revenue parameters (export-verified Jul 2026) ──────────────────────────

IMPRESSIONS_PER_VISIT = 22.0  # 5-tab tour with multi-zone Mantis

# Revenue per click — historical range from Mantis export
CPC_FLOOR_USD = 0.03   # Jul 26 floor (broken evCPM)
CPC_MID_USD = 0.15     # typical
CPC_CEIL_USD = 0.47    # Jul 24 best day

# eCPM range — display revenue driver
ECPM_FLOOR = 0.05      # broken (Jul 26)
ECPM_MID = 0.56        # Jul 25 actual
ECPM_TARGET = 0.75     # realistic target
ECPM_STRONG = 1.0      # strong target
ECPM_STRETCH = 2.0     # stretch (evCPM recovered)

# Path 3 (mantis-hardcode) — off-site ad interaction
# These visits still generate getdabflow impressions but also trigger
# off-site Mantis ad network payouts. Lower impression yield (~15/visit)
# because the tour is shorter, but adds a second revenue stream.
PATH3_IMPRESSIONS_PER_VISIT = 15.0
PATH3_CPC_USD = 0.25   # off-site ad network typically pays better CPC

# Click caps (farm-wide daily)
AD_CLICKS_SOFT_CAP = 20
AD_CLICKS_HARD_CAP = 40

# Target CTR on impressions
CTR_TARGET_LO = 0.15  # percent
CTR_TARGET_HI = 0.35  # percent


@dataclass
class PathMix:
    """Result of a path mix optimization."""
    phone_count: int
    total_visits: int
    path1_visits: int       # browse-only (no ad clicks)
    path2_visits: int       # ad-click (1 click each)
    path3_visits: int       # mantis-hardcode (off-site ad interaction)
    path1_pct: float
    path2_pct: float
    path3_pct: float
    est_impressions: int
    est_clicks: int          # total ad clicks (Path 2 + Path 3)
    est_revenue_low: float   # @ eCPM floor + CPC floor
    est_revenue_mid: float   # @ eCPM mid + CPC mid
    est_revenue_target: float  # @ eCPM target + CPC mid
    est_revenue_strong: float  # @ eCPM strong + CPC ceil
    est_ctr_pct: float
    visits_per_click: float | None

    def summary(self) -> str:
        vpc = f"{self.visits_per_click:.0f}" if self.visits_per_click else "∞"
        return (
            f"{self.phone_count} phones · {self.total_visits} visits/day\n"
            f"  Path 1 (browse-only): {self.path1_visits} visits ({self.path1_pct:.0f}%)\n"
            f"  Path 2 (ad-click):    {self.path2_visits} visits ({self.path2_pct:.0f}%)\n"
            f"  Path 3 (hardcode):    {self.path3_visits} visits ({self.path3_pct:.0f}%)\n"
            f"  Impressions: ~{self.est_impressions:,}  Clicks: ~{self.est_clicks}\n"
            f"  CTR: {self.est_ctr_pct:.3f}%  Visits/click: {vpc}\n"
            f"  Revenue range:\n"
            f"    Low (eCPM ${ECPM_FLOOR:.2f}):    ${self.est_revenue_low:.2f}/day  ${self.est_revenue_low * 30:.0f}/mo\n"
            f"    Mid (eCPM ${ECPM_MID:.2f}):     ${self.est_revenue_mid:.2f}/day  ${self.est_revenue_mid * 30:.0f}/mo\n"
            f"    Target (eCPM ${ECPM_TARGET:.2f}): ${self.est_revenue_target:.2f}/day  ${self.est_revenue_target * 30:.0f}/mo\n"
            f"    Strong (eCPM ${ECPM_STRONG:.2f}):${self.est_revenue_strong:.2f}/day  ${self.est_revenue_strong * 30:.0f}/mo"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "phone_count": self.phone_count,
            "total_visits": self.total_visits,
            "path1_visits": self.path1_visits,
            "path2_visits": self.path2_visits,
            "path3_visits": self.path3_visits,
            "path1_pct": round(self.path1_pct, 1),
            "path2_pct": round(self.path2_pct, 1),
            "path3_pct": round(self.path3_pct, 1),
            "est_impressions": self.est_impressions,
            "est_clicks": self.est_clicks,
            "est_ctr_pct": round(self.est_ctr_pct, 4),
            "visits_per_click": round(self.visits_per_click, 1) if self.visits_per_click else None,
            "est_revenue_low": round(self.est_revenue_low, 2),
            "est_revenue_mid": round(self.est_revenue_mid, 2),
            "est_revenue_target": round(self.est_revenue_target, 2),
            "est_revenue_strong": round(self.est_revenue_strong, 2),
        }


def _estimate_clicks_for_path2(
    total_visits: int,
    path3_visits: int,
    click_budget: int,
) -> int:
    """How many Path 2 visits should include an ad click.

    Path 3 already uses some of the click budget, so Path 2 gets the remainder.
    """
    remaining_budget = max(0, click_budget - path3_visits)
    # Don't exceed remaining budget
    return min(remaining_budget, total_visits - path3_visits)


def calculate_optimal_mix(
    phone_count: int,
    *,
    clicks_per_day: int | None = None,
    impressions_per_visit: float = IMPRESSIONS_PER_VISIT,
    ecpm: float = ECPM_TARGET,
    cpc: float = CPC_MID_USD,
) -> PathMix:
    """Calculate the optimal Path 1/2/3 mix for maximum daily revenue.

    Strategy:
    1. Set Path 3 (mantis-hardcode) to a small fraction — it adds a second ad
       network revenue stream but uses click budget and has lower impr/visit.
    2. Fill remaining click budget with Path 2 (ad-click) sequences.
    3. All other visits are Path 1 (browse-only) — pure impression generation.
    4. Optimize for: maximize impressions (display revenue) while keeping
       clicks within the 20-40 cap and CTR within 0.15-0.35%.

    The key insight: display revenue (impressions × eCPM) dominates at scale.
    Clicks add marginal CPC revenue but risk eCPM collapse if over-done.
    """
    from scorecard_api import scaling_targets

    targets = scaling_targets(phone_count)
    hard_cap = targets.get("ad_clicks_hard_cap", AD_CLICKS_HARD_CAP)

    # Default click target: ~70% of hard cap (leave headroom)
    if clicks_per_day is None:
        clicks_per_day = max(AD_CLICKS_SOFT_CAP, int(hard_cap * 0.70))
    clicks_per_day = min(clicks_per_day, hard_cap)

    # Total visits: start from sweet spot, then bump up if impressions would be short
    visit_lo, visit_hi = targets.get("farm_visits_daily_sweet", (560, 660))
    total_visits = (visit_lo + visit_hi) // 2
    # Ensure we hit the impression sweet spot: 15k-18k (4 phones)
    impr_lo, impr_hi = targets.get("impressions_daily_sweet", (15000, 18000))
    impr_mid = (impr_lo + impr_hi) // 2
    # At ~22 impr/visit, need ~impr_mid/22 visits minimum for display revenue
    min_visits_for_impr = int(impr_mid / impressions_per_visit) + 1
    total_visits = max(total_visits, min_visits_for_impr)

    # ── Path 3 allocation (mantis-hardcode) ──
    # ~5-8% of visits → off-site ad network + getdabflow impressions.
    # Each Path 3 visit uses 1 click of budget but generates a second revenue stream.
    path3_pct = 0.06  # 6% of visits
    path3_visits = max(1, int(total_visits * path3_pct))
    # Cap Path 3 at ~15% of click budget (keep most budget for Path 2)
    path3_clicks = min(path3_visits, int(clicks_per_day * 0.15))
    path3_visits = path3_clicks  # Each Path 3 visit = 1 click

    # ── Path 2 allocation (ad-click) ──
    # Fill remaining click budget. Each Path 2 visit = 1 ad click.
    remaining_clicks = clicks_per_day - path3_clicks
    path2_visits = remaining_clicks  # 1 click per Path 2 visit

    # ── Path 1 allocation (browse-only) ──
    # All remaining visits — pure impression generation, zero click risk.
    path1_visits = total_visits - path2_visits - path3_visits
    path1_visits = max(0, path1_visits)

    # Recalculate totals
    actual_total = path1_visits + path2_visits + path3_visits
    actual_clicks = path2_visits + path3_visits

    # ── Revenue estimates ──
    # Path 1: full impressions
    impr_path1 = int(path1_visits * impressions_per_visit)
    # Path 2: full impressions + 1 click each
    impr_path2 = int(path2_visits * impressions_per_visit)
    # Path 3: shorter tour → fewer impressions
    impr_path3 = int(path3_visits * PATH3_IMPRESSIONS_PER_VISIT)

    total_impressions = impr_path1 + impr_path2 + impr_path3

    # Display revenue: impressions × eCPM ÷ 1000
    display_rev_low = total_impressions * ECPM_FLOOR / 1000.0
    display_rev_mid = total_impressions * ECPM_MID / 1000.0
    display_rev_target = total_impressions * ECPM_TARGET / 1000.0
    display_rev_strong = total_impressions * ECPM_STRONG / 1000.0

    # Click revenue: Path 2 clicks × CPC + Path 3 clicks × Path3 CPC
    path2_click_rev = path2_visits * CPC_MID_USD
    path3_click_rev = path3_visits * PATH3_CPC_USD

    rev_low = display_rev_low + path2_visits * CPC_FLOOR_USD + path3_visits * CPC_FLOOR_USD
    rev_mid = display_rev_mid + path2_click_rev + path3_click_rev
    rev_target = display_rev_target + path2_click_rev + path3_click_rev
    rev_strong = display_rev_strong + path2_visits * CPC_CEIL_USD + path3_visits * PATH3_CPC_USD

    # CTR
    ctr = (actual_clicks / total_impressions * 100.0) if total_impressions > 0 else 0.0
    vpc = (actual_total / actual_clicks) if actual_clicks > 0 else None

    return PathMix(
        phone_count=phone_count,
        total_visits=actual_total,
        path1_visits=path1_visits,
        path2_visits=path2_visits,
        path3_visits=path3_visits,
        path1_pct=(path1_visits / actual_total * 100) if actual_total > 0 else 0,
        path2_pct=(path2_visits / actual_total * 100) if actual_total > 0 else 0,
        path3_pct=(path3_visits / actual_total * 100) if actual_total > 0 else 0,
        est_impressions=total_impressions,
        est_clicks=actual_clicks,
        est_revenue_low=rev_low,
        est_revenue_mid=rev_mid,
        est_revenue_target=rev_target,
        est_revenue_strong=rev_strong,
        est_ctr_pct=ctr,
        visits_per_click=vpc,
    )


def daily_path_schedule(
    phone_count: int,
    *,
    clicks_per_day: int | None = None,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """Generate a randomized daily visit schedule with path assignments.

    Returns a list of visit slots, each assigned to Path 1, 2, or 3.
    Path 2 and 3 visits are spread throughout the day (never clustered)
    to look human and avoid click spam patterns.

    Each phone's visits are interleaved with other phones via stagger.
    """
    mix = calculate_optimal_mix(phone_count, clicks_per_day=clicks_per_day)
    rng = random.Random(seed)

    # Build pool: Path 1 = "browse", Path 2 = "ad_click", Path 3 = "hardcode"
    pool: list[str] = []
    pool.extend(["browse"] * mix.path1_visits)
    pool.extend(["ad_click"] * mix.path2_visits)
    pool.extend(["hardcode"] * mix.path3_visits)

    # Shuffle — distributes ad clicks randomly across the day
    rng.shuffle(pool)

    schedule = []
    for i, path in enumerate(pool):
        schedule.append({
            "slot": i,
            "path": path,
            "sequence_type": _sequence_type_for_path(path),
        })

    return schedule


def _sequence_type_for_path(path: str) -> str:
    """Map path name to the sequence folder/type."""
    return {
        "browse": "no-ad",
        "ad_click": "ad",
        "hardcode": "ad/mantis-hardcode",
    }.get(path, "no-ad")


def optimal_playlist_config(
    phone_count: int,
    *,
    clicks_per_day: int | None = None,
) -> dict[str, Any]:
    """Generate the optimal groups_config.json phone entry for this path mix.

    Uses folder_random mode to pick from all three path types with weighted
    probability matching the optimal mix.
    """
    mix = calculate_optimal_mix(phone_count, clicks_per_day=clicks_per_day)

    # Weight distribution: Path 1 gets most weight, Path 2 moderate, Path 3 small
    # This maps to a combined playlist with weighted picks
    path1_weight = max(1, round(mix.path1_pct))
    path2_weight = max(1, round(mix.path2_pct))
    path3_weight = max(1, round(mix.path3_pct))

    return {
        "path_mix": mix.to_dict(),
        "recommended_mode": "random",
        "recommended_shuffle": "combined",
        "weight_ratio": f"{path1_weight}:{path2_weight}:{path3_weight}",
        "path1_pct": round(mix.path1_pct, 1),
        "path2_pct": round(mix.path2_pct, 1),
        "path3_pct": round(mix.path3_pct, 1),
        "click_budget": {
            "daily_cap": mix.est_clicks,
            "path2_budget": mix.path2_visits,
            "path3_budget": mix.path3_visits,
        },
        "browse_after_clicks": True,
    }


# ── CLI ────────────────────────────────────────────────────────────────────

def _main() -> int:
    import json
    import sys

    phone_count = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    clicks = int(sys.argv[2]) if len(sys.argv) > 2 else None

    mix = calculate_optimal_mix(phone_count, clicks_per_day=clicks)
    print(mix.summary())
    print()
    print("-" * 60)
    print("Recommended playlist config:")
    cfg = optimal_playlist_config(phone_count, clicks_per_day=clicks)
    print(json.dumps(cfg, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
