"""Built-in LoansFlow Site Profile for PharmFlow / PharmFlow farm sequences."""

from __future__ import annotations

from pathlib import Path

from automation.site_profile import (
    AdClick,
    BrowsePath,
    CoreAction,
    FarmPrefs,
    HumanizePrefs,
    SiteProfile,
    profile_path,
    save_profile,
)

# Prefer plural .com when DNS is live; GitHub Pages is the interim URL.
LOANSFLOW_URL = "https://twoskoops707.github.io/loansflow/"
LOANSFLOW_TOOLS_URL = "https://twoskoops707.github.io/loansflow/tools/"
LOANSFLOW_CANONICAL = "https://loansflows.com/"


def loansflow_profile() -> SiteProfile:
    """Mobile 900x1600 farm profile — landing + calculators + ad slots."""
    return SiteProfile(
        slug="loansflow",
        display_name="LoansFlow",
        target_kind="website",
        adapter="loansflow",
        url=LOANSFLOW_URL,
        gates=[],
        # Coords from Playwright remap @ 900x1600 (2026-07-29)
        core=CoreAction(
            kind="tap",
            description="Launch calculators CTA",
            x=180,
            y=1509,
            scroll_before=False,
            confirm_wait_s=2.5,
        ),
        browse_paths=[
            BrowsePath(name="sba_card", x=450, y=494, scroll_to_bottom=True, scroll_swipes=3),
            BrowsePath(name="mortgage_card", x=450, y=1022, scroll_to_bottom=True, scroll_swipes=3),
            BrowsePath(name="tools_sba_tab", x=126, y=136, scroll_to_bottom=True, scroll_swipes=4),
            BrowsePath(name="tools_loc_tab", x=549, y=136, scroll_to_bottom=True, scroll_swipes=3),
            BrowsePath(name="tools_mortgage_tab", x=735, y=136, scroll_to_bottom=True, scroll_swipes=4),
        ],
        ads=[
            AdClick(name="home_sponsored", x=450, y=345, max_per_hour=1),
            AdClick(name="tools_incontent", x=440, y=977, max_per_hour=1),
            AdClick(name="tools_anchor", x=450, y=1552, max_per_hour=1),
        ],
        humanize=HumanizePrefs(
            preset="moderate",
            concurrent_unique_sequences=True,
        ),
        farm=FarmPrefs(
            phone_count=4,
            seqs_per_hour=0,
            hours=0.0,
            allow_ads=True,
            ads_per_hour=0,
            # Conservative day-one targets until AdSense live (impressions still count for policy/warming).
            daily_visits_csv="120,100,90,80",
            daily_ads_csv="3,2,2,2",
            impressions_per_visit=12.0,
            ntfy_topic="twskoops",
            ntfy_hourly=True,
            ntfy_interval_s=7200,
            startup_spread_minutes=22,
        ),
        notes=(
            "LoansFlow calculator suite. FREE live URL: GitHub Pages. "
            "Optional cheap custom domain later (see loansflow docs/DOMAIN.md). "
            "Ads placeholders until AdSense/Ezoic approve — farm warms traffic/SEO first."
        ),
    )


def ensure_loansflow_profile(app_data: Path) -> Path:
    """Seed LoansFlow profile once without overwriting operator edits."""
    path = profile_path(app_data, "loansflow")
    if path.is_file():
        return path
    return save_profile(app_data, loansflow_profile())
