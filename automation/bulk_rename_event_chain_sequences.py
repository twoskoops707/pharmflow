#!/usr/bin/env python3
"""Rename sequence JSON files to deterministic event-chain basenames (filesystem mv + git add)."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT / "automation"))

from sequence_event_chain_name import _snap_under_limit, generate_event_chain_basename, sha256_hex_digest
from sequence_normalize import unwrap_sequence_document


SEQUENCE_DIR = ROOT / "automation" / "recordings" / "sequences"


def _stem_fit_windows_parent(parent: Path, stem: str, digest: str) -> str:
    """Keep ``parent / (stem + '.json')`` within typical Windows path limits."""
    budget = 236 - len(str(parent.resolve()))
    budget = max(40, min(140, budget))
    if len(stem) <= budget:
        return stem
    tail = f"__h{digest[:6]}"
    hb = budget - len(tail)
    hb = max(24, hb)
    base = _snap_under_limit(stem, hb)
    return base + tail


def _load_steps(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    steps_any, _ = unwrap_sequence_document(raw)
    return [s for s in steps_any if isinstance(s, dict)]


def compute_rename_plan() -> tuple[list[tuple[Path, Path]], dict[str, str], int]:
    """
    Returns (renames old_path -> dest_path relative to repo root),
            digest_map path_str -> sha256 hex,
            collision_count (number of files that needed __h suffix).
    """
    def _include_sequence_file(p: Path) -> bool:
        n = p.name
        # Interrupted bulk-rename staging names must still be picked up.
        if n.startswith("_evtchain_tmp_"):
            return True
        if n.startswith("evtchain_stage_") or n.startswith("_evtchain_stage_"):
            return True
        return not n.startswith("_")

    paths = sorted(p for p in SEQUENCE_DIR.rglob("*.json") if _include_sequence_file(p))
    entries: list[tuple[Path, str, str, list[dict[str, Any]]]] = []
    for p in paths:
        steps = _load_steps(p)
        digest = sha256_hex_digest(steps)
        stem = generate_event_chain_basename(steps)
        entries.append((p, digest, stem, steps))

    # Group by (parent, stem) — collisions only matter within same folder + stem
    by_bucket: dict[tuple[str, str], list[tuple[Path, str, list[dict[str, Any]]]]] = defaultdict(list)
    for p, digest, stem, steps in entries:
        key = (str(p.parent.resolve()), stem)
        by_bucket[key].append((p, digest, steps))

    dest_by_path: dict[Path, Path] = {}
    collision_suffix_count = 0

    for (_parent, stem), group in sorted(by_bucket.items()):
        parent = Path(_parent)
        group_sorted = sorted(group, key=lambda x: str(x[0]))
        digest_paths: dict[str, list[Path]] = defaultdict(list)
        for p, digest, _steps in group_sorted:
            digest_paths[digest].append(p)

        multi_file_bucket = len(group_sorted) > 1

        for digest in digest_paths:
            digest_paths[digest].sort(key=lambda x: str(x))

        for digest, paths in sorted(digest_paths.items()):
            for i, p in enumerate(paths):
                if not multi_file_bucket:
                    final_stem = stem
                elif len(paths) == 1:
                    collision_suffix_count += 1
                    final_stem = f"{stem}__h{digest[:6]}"
                else:
                    collision_suffix_count += 1
                    final_stem = f"{stem}__h{digest[:6]}__n{i}"
                final_stem = _stem_fit_windows_parent(parent, final_stem, digest)
                dest_by_path[p] = parent / f"{final_stem}.json"

    renames: list[tuple[Path, Path]] = []
    for src, dst in sorted(dest_by_path.items(), key=lambda x: str(x[0])):
        if src.resolve() == dst.resolve():
            continue
        renames.append((src, dst))

    bucket_dest: dict[Path, list[Path]] = defaultdict(list)
    for src, dst in renames:
        bucket_dest[dst].append(src)
    bad = {k: v for k, v in bucket_dest.items() if len(v) > 1}
    if bad:
        msg = "; ".join(f"{k}: {v}" for k, v in list(bad.items())[:5])
        raise RuntimeError(f"duplicate rename targets (need manual dedup): {msg}")

    digest_map = {str(p.relative_to(ROOT)): d for p, d, _, _ in entries}

    return renames, digest_map, collision_suffix_count


def run_git_mv(renames: list[tuple[Path, Path]], *, apply: bool) -> None:
    """Two-phase rename (avoids overwrite swaps). Apply uses filesystem moves + one ``git add``."""
    if not renames:
        print("No renames needed.")
        return

    run_id = uuid.uuid4().hex[:10]
    staged_triples: list[tuple[Path, Path, Path]] = []
    for i, (src, dst) in enumerate(renames):
        # Do not start with "_" — sources may already be ``_evtchain_tmp_*``.
        st = src.parent / f"evtchain_stage_{run_id}_{i:05d}_{src.name}"
        staged_triples.append((src, st, dst))

    if not apply:
        for src, st, dst in staged_triples:
            print(f"git -C {ROOT} mv -- {src.relative_to(ROOT)} {st.relative_to(ROOT)}")
        for _src, st, dst in staged_triples:
            print(f"git -C {ROOT} mv -- {st.relative_to(ROOT)} {dst.relative_to(ROOT)}")
        return

    for src, st, _dst in staged_triples:
        if not src.exists():
            raise FileNotFoundError(f"missing source for rename: {src}")
        shutil.move(str(src), str(st))
    for _src, st, dst in staged_triples:
        shutil.move(str(st), str(dst))

    r = subprocess.run(
        ["git", "-C", str(ROOT), "add", "-A", "--", "automation/recordings/sequences"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print(r.stderr or r.stdout, file=sys.stderr)
        raise SystemExit(r.returncode)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Run git mv (default dry-run print)")
    args = ap.parse_args()

    renames, _digests, collision_cnt = compute_rename_plan()
    print(f"Planned renames: {len(renames)} (collision suffixes: {collision_cnt})")
    run_git_mv(renames, apply=args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
