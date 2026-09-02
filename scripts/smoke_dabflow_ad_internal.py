#!/usr/bin/env python3
"""Internal DabFlow ad validation — offline audit + optional live smoke on one phone."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.config import REQUIRED_SEQUENCE_VERSION, sequences_run_allowed
from automation.dabflow_mantis_ad_urls import fetch_mantis_landing_urls, resolve_hardcode_ad_urls
from automation.sequence_paths import discover_sequence_files

SMOKE_ZONES = ("zone-one", "zone-three")
AD_MARKERS = ("Tap home ad banner", "Tap post-timer ad banner", "zone-one", "zone-three")


def audit_ad_sequences(seq_root: Path) -> tuple[int, list[str]]:
    """Ensure every *_ad.json under base/ is v2 and contains home + post-timer ad steps."""
    errors: list[str] = []
    ad_files = [p for p in discover_sequence_files(seq_root) if p.stem.endswith("_ad")]
    for path in ad_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        if int(data.get("sequence_version") or 0) < REQUIRED_SEQUENCE_VERSION:
            errors.append(f"{path.name}: sequence_version < {REQUIRED_SEQUENCE_VERSION}")
            continue
        descs = " | ".join(str(s.get("description") or "") for s in data.get("steps") or [])
        if "Tap home ad banner" not in descs:
            errors.append(f"{path.name}: missing home ad tap step")
        if "Tap post-timer ad banner" not in descs and "post-timer ad" not in descs.lower():
            errors.append(f"{path.name}: missing post-timer ad tap step")
    return len(ad_files), errors


def audit_mantis_ssp() -> tuple[dict[str, str], list[str]]:
    """Fetch live Mantis ads for home + post-timer zones."""
    warnings: list[str] = []
    live = fetch_mantis_landing_urls(list(SMOKE_ZONES))
    merged = resolve_hardcode_ad_urls(list(SMOKE_ZONES), prefer_live=True)
    for zone in SMOKE_ZONES:
        if zone not in live:
            warnings.append(f"SSP returned no live ad for {zone} (fallback will be used)")
        if zone not in merged:
            warnings.append(f"No landing URL resolved for {zone}")
    return merged, warnings


def run_live_smoke(phone: str, seq_path: Path) -> int:
    if not sequences_run_allowed():
        print("ERROR: Set CPHARM_ALLOW_SEQUENCE_RUNS=1 before live smoke test.")
        return 1

    from automation.sequence_runner import Sequence, SequenceRunner
    from wizard.mumu_farm_ops import MuMuFarmOps

    farm = MuMuFarmOps()
    devices = farm.list_instances()
    if not devices:
        print("ERROR: No ADB devices — connect vm0 only, then retry.")
        return 1

    seq = Sequence.from_json(seq_path)
    seq.phone = phone
    runner = SequenceRunner(farm)
    print(f"Running live smoke on {phone}: {seq.name}")
    report = runner.run(seq)
    print(json.dumps(report, indent=2))
    if not report.get("success"):
        return 1
    print("Check /sdcard/Download/cpharm_smoke_ad_home.png on device for ad proof.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Internal DabFlow ad smoke / audit")
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT / "automation" / "recordings" / "sequences",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run smoke_ad_home_v2.json on a connected phone",
    )
    parser.add_argument("--phone", default=os.environ.get("CPHARM_SMOKE_PHONE", "vm0.gmadoa"))
    args = parser.parse_args()

    seq_root = args.root
    if (seq_root / "sequences").is_dir():
        seq_root = seq_root / "sequences"

    all_v2 = discover_sequence_files(seq_root)
    humanized_left = list((seq_root / "humanized").rglob("*.json")) if (seq_root / "humanized").is_dir() else []
    print(f"Canonical v2 sequences (base/ only): {len(all_v2)}")
    if humanized_left:
        print(f"WARNING: {len(humanized_left)} humanized duplicates still on disk — delete that folder")

    ad_count, ad_errors = audit_ad_sequences(seq_root)
    print(f"Ad sequences audited: {ad_count}")
    if ad_errors:
        print("Ad sequence errors:")
        for err in ad_errors[:20]:
            print(f"  - {err}")
        if len(ad_errors) > 20:
            print(f"  ... and {len(ad_errors) - 20} more")
        return 1

    try:
        urls, ssp_warnings = audit_mantis_ssp()
        print("Mantis landing URLs:")
        for zone, url in urls.items():
            print(f"  {zone}: {url[:80]}...")
        for w in ssp_warnings:
            print(f"  WARN: {w}")
    except Exception as exc:
        print(f"Mantis SSP fetch failed: {exc}")
        return 1

    smoke_path = seq_root / "base" / "smoke" / "smoke_ad_home_v2.json"
    if not smoke_path.is_file():
        print(f"ERROR: missing {smoke_path}")
        return 1

    if args.live:
        return run_live_smoke(args.phone, smoke_path)

    print("Offline audit OK. For device proof: CPHARM_ALLOW_SEQUENCE_RUNS=1 py scripts/smoke_dabflow_ad_internal.py --live")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
