#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from pharmflow_defaults import desktop_gold_default
from sequence_geometry import SEQUENCE_BASE_H, SEQUENCE_BASE_W, scale_point
from sequence_normalize import unwrap_sequence_document

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "automation" / "recordings" / "sequences"
DOC_MUMU = ROOT / "docs" / "PharmFlow_emulator_MuMu_and_sequences.md"
DEFAULT_GOLD = desktop_gold_default()

EXPLICIT_MUMU_RESOLUTIONS = {(1080, 1920), (900, 1600), (720, 1280), (540, 960)}


def _as_int(v: Any) -> int | None:
    try:
        iv = int(v)
    except (TypeError, ValueError):
        return None
    return iv if iv > 0 else None


def discover_resolutions(sequence_dir: Path, docs_path: Path) -> set[tuple[int, int]]:
    found: set[tuple[int, int]] = set(EXPLICIT_MUMU_RESOLUTIONS)
    if docs_path.exists():
        text = docs_path.read_text(encoding="utf-8")
        for m in re.finditer(r"(\d{3,4})\s*[×xX]\s*(\d{3,4})", text):
            found.add((int(m.group(1)), int(m.group(2))))
    for src in sorted(sequence_dir.rglob("*.json")):
        data = json.loads(src.read_text(encoding="utf-8"))
        steps, meta = unwrap_sequence_document(data)
        if isinstance(meta, dict):
            bw = _as_int(meta.get("base_w"))
            bh = _as_int(meta.get("base_h"))
            if bw and bh:
                found.add((bw, bh))
        if isinstance(data, dict):
            baseline_wh = str(data.get("baseline_wh", "")).strip()
            m = re.match(r"(\d{3,4})x(\d{3,4})$", baseline_wh)
            if m:
                found.add((int(m.group(1)), int(m.group(2))))
        for step in steps:
            if not isinstance(step, dict):
                continue
            if step.get("type") not in ("tap", "swipe"):
                continue
            bw = _as_int(step.get("base_w"))
            bh = _as_int(step.get("base_h"))
            if bw and bh:
                found.add((bw, bh))
    return found


def classify(path: Path, payload: object) -> str:
    """Bucket JSON into ``ads`` / ``no-ads`` / ``_review`` (ambiguous → manual review, not a canonical label)."""
    fn = path.name.lower()
    blob = fn
    try:
        blob = f"{fn} {json.dumps(payload, ensure_ascii=False).lower()}"
    except (TypeError, ValueError):
        pass
    ads_tokens = (
        "home_ad-on",
        "_ads_",
        "web_ads",
        "adclick",
        "ad-read",
        "footer_ad",
        "mid-ad",
        "postad-on",
    )
    noads_tokens = ("home_ad-off", "no_ad", "no-ad", "noad")
    ads_hit = any(tok in blob for tok in ads_tokens)
    noads_hit = any(tok in blob for tok in noads_tokens)
    if ads_hit and not noads_hit:
        return "ads"
    if noads_hit and not ads_hit:
        return "no-ads"
    return "_review"


def remap_steps(steps: list[Any], target_w: int, target_h: int) -> list[Any]:
    out: list[Any] = []
    for raw in steps:
        if not isinstance(raw, dict):
            out.append(raw)
            continue
        step = dict(raw)
        stype = step.get("type")
        if stype == "tap":
            x = _as_int(step.get("x")) or 0
            y = _as_int(step.get("y")) or 0
            src_w = _as_int(step.get("base_w")) or SEQUENCE_BASE_W
            src_h = _as_int(step.get("base_h")) or SEQUENCE_BASE_H
            nx, ny = scale_point(x, y, target_w, target_h, src_w, src_h)
            step["x"] = min(target_w, max(0, nx))
            step["y"] = min(target_h, max(0, ny))
            step["base_w"] = target_w
            step["base_h"] = target_h
        elif stype == "swipe":
            src_w = _as_int(step.get("base_w")) or SEQUENCE_BASE_W
            src_h = _as_int(step.get("base_h")) or SEQUENCE_BASE_H
            for a, b in (("x1", "y1"), ("x2", "y2")):
                x = _as_int(step.get(a)) or 0
                y = _as_int(step.get(b)) or 0
                nx, ny = scale_point(x, y, target_w, target_h, src_w, src_h)
                step[a], step[b] = min(target_w, max(0, nx)), min(target_h, max(0, ny))
            step["base_w"] = target_w
            step["base_h"] = target_h
        out.append(step)
    return out


def write_remapped(
    source_path: Path, rel: Path, gold: Path, bucket: str, targets: list[tuple[int, int]]
) -> None:
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    steps, meta = unwrap_sequence_document(payload)
    for w, h in targets:
        out_steps = remap_steps(steps, w, h)
        if isinstance(payload, list):
            out_payload: object = out_steps
        else:
            out_payload = dict(payload)
            out_payload["steps"] = out_steps
            if isinstance(meta, dict):
                merged = dict(meta)
                merged["base_w"] = w
                merged["base_h"] = h
                out_payload["meta"] = merged
            out_payload["baseline_wh"] = f"{w}x{h}"
        out_dir = gold / bucket / f"{w}x{h}" / rel.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / rel.name).write_text(json.dumps(out_payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build gold sequence dataset remapped per resolution.")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD, help="Output root (default Desktop/gold)")
    args = parser.parse_args()

    targets = sorted(discover_resolutions(SOURCE, DOC_MUMU))
    if args.gold.exists():
        shutil.rmtree(args.gold)
    args.gold.mkdir(parents=True, exist_ok=True)

    per_bucket = Counter()
    for src in sorted(SOURCE.rglob("*.json")):
        rel = src.relative_to(SOURCE)
        payload = json.loads(src.read_text(encoding="utf-8"))
        bucket = classify(src, payload)
        write_remapped(src, rel, args.gold, bucket, targets)
        per_bucket[bucket] += 1

    summary = {
        "target_resolutions": [f"{w}x{h}" for w, h in targets],
        "source_json_count": sum(per_bucket.values()),
        "source_count_by_bucket": dict(per_bucket),
    }
    (args.gold / "_build_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
