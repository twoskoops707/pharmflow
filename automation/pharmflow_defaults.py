"""Shared defaults and rename-map helpers so validators stay aligned after bulk renames."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEQUENCE_RENAME_MAP_PATH = ROOT / "automation" / "recordings" / "_sequence_rename_basename_map.json"


def desktop_gold_default() -> Path:
    """Default gold dataset folder (per-user Desktop; avoid hardcoding a Windows profile)."""
    return Path.home() / "Desktop" / "gold"


@lru_cache(maxsize=1)
def load_sequence_rename_map() -> dict[str, str]:
    if not SEQUENCE_RENAME_MAP_PATH.is_file():
        return {}
    try:
        raw = json.loads(SEQUENCE_RENAME_MAP_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, str):
            out[k] = v
    return out


@lru_cache(maxsize=1)
def _v2_basename_to_combo_key() -> dict[str, str]:
    m: dict[str, str] = {}
    for old_key, new_base in load_sequence_rename_map().items():
        if old_key.startswith("sequence_home_combo_v2_"):
            m[new_base] = old_key
    return m


def home_combo_v2_key_for_basename(basename: str) -> str | None:
    """Map hashed sequence basename → canonical ``sequence_home_combo_v2_*.json`` key, if any."""
    return _v2_basename_to_combo_key().get(basename)


def iter_home_combo_v2_sequence_paths(sequence_dir: Path) -> list[Path]:
    """On-disk combo matrix files: legacy glob plus basenames from ``_sequence_rename_basename_map.json``."""
    paths: dict[str, Path] = {}
    for p in sequence_dir.glob("sequence_home_combo_v2_*.json"):
        paths[p.name] = p
    for new_base in _v2_basename_to_combo_key():
        p = sequence_dir / new_base
        if p.is_file():
            paths[p.name] = p
    return sorted(paths.values(), key=lambda x: x.name)


@lru_cache(maxsize=1)
def combo_sequence_basenames_from_rename_map() -> frozenset[str]:
    """Basenames that came from home-combo matrix renames (for tail validation in verify_sequences)."""
    out: set[str] = set()
    for old_key, new_base in load_sequence_rename_map().items():
        if old_key.startswith("sequence_home_combo_v2_") or old_key.startswith(
            "sequence_combo_entry-"
        ):
            out.add(new_base)
    return frozenset(out)

