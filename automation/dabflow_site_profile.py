"""Built-in DabFlow Site Profile used as PharmFlow's reference target."""

from __future__ import annotations

from pathlib import Path

from automation.site_profile import (
    AdClick,
    BrowsePath,
    CoreAction,
    FarmPrefs,
    GateTap,
    HumanizePrefs,
    SiteProfile,
    profile_path,
    save_profile,
)


def dabflow_profile() -> SiteProfile:
    """Return the built-in reference profile without making DabFlow the product."""
    return SiteProfile(
        slug="dabflow",
        display_name="DabFlow",
        target_kind="website",
        adapter="dabflow",
        url="https://getdabflow.app/",
        gates=[
            GateTap(
                label="Age gate Yes",
                x=380,
                y=980,
                wait_before_s=1.5,
                wait_after_s=0.75,
            )
        ],
        core=CoreAction(
            kind="scroll_then_tap",
            description="Start Perfect Dab",
            x=449,
            y=1300,
            scroll_before=True,
            confirm_wait_s=2.0,
        ),
        browse_paths=[
            BrowsePath(name="home", x=90, y=1535, scroll_to_bottom=True),
            BrowsePath(name="glass", x=310, y=1535, scroll_to_bottom=True),
            BrowsePath(name="settings", x=590, y=1535, scroll_to_bottom=True),
            BrowsePath(name="stats", x=810, y=1535, scroll_to_bottom=True),
        ],
        ads=[
            AdClick(name="sponsored", x=450, y=1100, max_per_hour=1),
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
            daily_visits_csv="173,148,141,119",
            daily_ads_csv="5,4,4,3",
            impressions_per_visit=22.0,
            ntfy_topic="",
            ntfy_hourly=True,
            ntfy_interval_s=7200,
            startup_spread_minutes=2,
        ),
        notes=(
            "Built-in reference profile. The curated DabFlow catalog is generated "
            "by automation.dabflow_sequence_gen."
        ),
    )


def ensure_dabflow_profile(app_data: Path) -> Path:
    """Seed the reference profile once without overwriting operator edits."""
    path = profile_path(app_data, "dabflow")
    if path.is_file():
        return path
    return save_profile(app_data, dabflow_profile())
