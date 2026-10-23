"""Generate LoansFlow farm sequences into PharmFlow recordings catalog."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from automation.loansflow_site_profile import LOANSFLOW_TOOLS_URL, LOANSFLOW_URL, loansflow_profile
from automation.site_profile import AdClick, BrowsePath, CoreAction, save_profile
from automation.site_sequence_gen import write_profile_sequences

# Coords from Playwright remap @ 900x1600 (docs in loansflow repo)
HOME_CTA = (180, 1509)  # Launch calculators (hero)
HOME_AD = (450, 345)  # after scroll to #tools
TOOL_SBA = (450, 494)
TOOL_MORTGAGE = (450, 1022)
TOOLS_ANCHOR_AD = (450, 1552)
TOOLS_INCONTENT_AD = (440, 977)
TOOLS_CALC_CTA = (697, 1079)  # Calculate / primary after scroll
STEP_SBA = (126, 136)
STEP_LOC = (549, 136)
STEP_MORTGAGE = (735, 136)


def build_profile():
    p = loansflow_profile()
    p.url = LOANSFLOW_URL
    p.core = CoreAction(
        kind="tap",
        description="Launch calculators",
        x=HOME_CTA[0],
        y=HOME_CTA[1],
        scroll_before=False,
        confirm_wait_s=2.5,
    )
    p.browse_paths = [
        BrowsePath(name="sba_card", x=TOOL_SBA[0], y=TOOL_SBA[1], scroll_to_bottom=True, scroll_swipes=3),
        BrowsePath(name="mortgage_card", x=TOOL_MORTGAGE[0], y=TOOL_MORTGAGE[1], scroll_to_bottom=True, scroll_swipes=3),
        BrowsePath(name="tools_sba_tab", x=STEP_SBA[0], y=STEP_SBA[1], scroll_to_bottom=True, scroll_swipes=4),
        BrowsePath(name="tools_loc_tab", x=STEP_LOC[0], y=STEP_LOC[1], scroll_to_bottom=True, scroll_swipes=3),
        BrowsePath(name="tools_mortgage_tab", x=STEP_MORTGAGE[0], y=STEP_MORTGAGE[1], scroll_to_bottom=True, scroll_swipes=4),
    ]
    p.ads = [
        AdClick(name="home_sponsored", x=HOME_AD[0], y=HOME_AD[1], max_per_hour=1),
        AdClick(name="tools_incontent", x=TOOLS_INCONTENT_AD[0], y=TOOLS_INCONTENT_AD[1], max_per_hour=1),
        AdClick(name="tools_anchor", x=TOOLS_ANCHOR_AD[0], y=TOOLS_ANCHOR_AD[1], max_per_hour=1),
    ]
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate LoansFlow PharmFlow sequences")
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "automation" / "recordings" / "sequences",
        help="Sequence output root",
    )
    ap.add_argument(
        "--app-data",
        type=Path,
        default=ROOT / "automation" / "sites",
        help="Where to save profile.json",
    )
    ap.add_argument("--clean", action="store_true")
    args = ap.parse_args()

    profile = build_profile()
    args.app_data.mkdir(parents=True, exist_ok=True)
    saved = save_profile(args.app_data, profile)
    count = write_profile_sequences(profile, args.out, clean=args.clean)

    catalog = {
        "slug": profile.slug,
        "url": profile.url,
        "tools_url": LOANSFLOW_TOOLS_URL,
        "count": count,
        "profile": str(saved),
        "out": str(args.out / profile.slug),
        "notes": profile.notes,
    }
    cat_path = args.out / profile.slug / "sequence_catalog.md"
    cat_path.parent.mkdir(parents=True, exist_ok=True)
    cat_path.write_text(
        f"""# LoansFlow Sequence Catalog

Source: [{profile.url}]({profile.url})
Tools: [{LOANSFLOW_TOOLS_URL}]({LOANSFLOW_TOOLS_URL})
Baseline: 900×1600
Total: **{count}** sequences

## Farm prefs
- daily_visits_csv: `{profile.farm.daily_visits_csv}`
- daily_ads_csv: `{profile.farm.daily_ads_csv}`
- impressions_per_visit: {profile.farm.impressions_per_visit}
- ntfy: `{profile.farm.ntfy_topic}`
- unique sequences: **required**

## Remap
Coords from Playwright map. Re-run `node tools/browser/map-loansflow.js` in the loansflow repo after UI changes.

When `loansflow.top` is live, update profile url and regenerate.
""",
        encoding="utf-8",
    )
    meta_path = args.out / profile.slug / "_launch.json"
    meta_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(catalog, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
