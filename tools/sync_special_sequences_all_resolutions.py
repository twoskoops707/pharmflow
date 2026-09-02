#!/usr/bin/env python3
"""Copy demo / early-exit / mantis-hardcode sequences to every MuMu resolution."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "automation"))

from build_gold_dataset import remap_steps  # noqa: E402
from generate_dabflow_gold_matrix import RESOLUTIONS  # noqa: E402

SOURCE_TAG = "900x1600"
SPECIAL_GLOBS = (
    "no-ad/dabflow__demo__ONE.json",
    "ad/dabflow__demo__TWO.json",
    "no-ad/early-exit/dabflow__early_exit__*.json",
    "ad/mantis-hardcode/dabflow__mantis_hardcode__*.json",
)


def _sequence_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()
    for p in (
        ROOT / "sequences",
        ROOT.parent / "sequences",
        Path.home() / "CPharm" / "sequences",
    ):
        try:
            key = str(p.resolve())
        except OSError:
            continue
        if p.is_dir() and key not in seen:
            seen.add(key)
            roots.append(p)
    return roots


def _remap_payload(payload: dict | list, w: int, h: int) -> dict | list:
    if isinstance(payload, list):
        return remap_steps(payload, w, h)
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    steps = payload.get("steps")
    if isinstance(steps, list):
        out["steps"] = remap_steps(list(steps), w, h)
    meta = payload.get("meta")
    if isinstance(meta, dict):
        m = dict(meta)
        m["base_w"] = w
        m["base_h"] = h
        out["meta"] = m
    out["baseline_wh"] = f"{w}x{h}"
    tag = f"{w}x{h}"
    label = out.get("label")
    if isinstance(label, str) and SOURCE_TAG in label:
        out["label"] = label.replace(SOURCE_TAG, tag)
    return out


def sync_root(seq_root: Path) -> tuple[int, int]:
    src_base = seq_root / SOURCE_TAG
    if not src_base.is_dir():
        return 0, 0

    sources: list[Path] = []
    for pattern in SPECIAL_GLOBS:
        sources.extend(sorted(src_base.glob(pattern)))

    written = 0
    for src in sources:
        rel = src.relative_to(src_base)
        try:
            payload = json.loads(src.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue

        for w, h in RESOLUTIONS:
            tag = f"{w}x{h}"
            dst = seq_root / tag / rel
            if tag == SOURCE_TAG and dst.is_file():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            remapped = _remap_payload(payload, w, h)
            dst.write_text(json.dumps(remapped, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            written += 1

    return len(sources), written


def main() -> int:
    total_src = 0
    total_out = 0
    for root in _sequence_roots():
        n_src, n_out = sync_root(root)
        if n_out:
            print(f"{root}: {n_src} canonical specials -> {n_out} resolution files")
        total_src += n_src
        total_out += n_out

    tags = ", ".join(f"{w}x{h}" for w, h in RESOLUTIONS)
    print(f"Done. {total_out} files written across [{tags}] from {total_src} source specials per root.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
