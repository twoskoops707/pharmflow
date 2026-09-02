"""Discover and resolve sequence JSON paths (base/ tree only when present)."""

from __future__ import annotations

import json
from pathlib import Path

from automation.config import REQUIRED_SEQUENCE_VERSION


def _canonical_search_roots(directory: Path) -> list[Path]:
    """Use ``base/`` only — humanized duplicates and legacy flat trees are ignored."""
    base = directory / "base"
    if base.is_dir():
        return [base]
    return [directory]


def discover_sequence_files(directory: Path, *, recursive: bool = True) -> list[Path]:
    """Return v3+ sequence JSON files under the canonical tree (skips older versions)."""
    if not directory.is_dir():
        return []
    pattern = "**/*.json" if recursive else "*.json"
    files: list[Path] = []
    for root in _canonical_search_roots(directory):
        for path in sorted(root.glob(pattern)):
            if path.name == "sequence_catalog.md":
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if "steps" not in data:
                continue
            if int(data.get("sequence_version") or 0) < REQUIRED_SEQUENCE_VERSION:
                continue
            files.append(path)
    return files


def sequence_id(path: Path, root: Path) -> str:
    """Relative sequence id used by dashboard/scheduler (no .json suffix)."""
    rel = path.relative_to(root)
    if rel.parent == Path("."):
        return rel.stem
    return str(rel.with_suffix("")).replace("\\", "/")


def resolve_sequence_path(directory: Path, name: str) -> Path:
    """Resolve a sequence name to a JSON file (supports nested paths)."""
    normalized = name.replace("\\", "/").strip("/")
    if normalized.endswith(".json"):
        normalized = normalized[:-5]

    direct = directory / f"{normalized}.json"
    if direct.is_file():
        return direct

    nested = directory / "base" / f"{normalized}.json"
    if nested.is_file():
        return nested

    matches = [p for p in discover_sequence_files(directory) if p.stem == Path(normalized).name]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        base_matches = [p for p in matches if "base" in p.parts]
        if len(base_matches) == 1:
            return base_matches[0]
        raise FileNotFoundError(
            f"Ambiguous sequence name '{name}' — use a path like "
            f"'{sequence_id(matches[0], directory)}' ({len(matches)} matches)"
        )

    raise FileNotFoundError(f"Sequence not found: {directory / normalized}.json")


def list_sequence_ids(directory: Path) -> list[str]:
    """List runnable v3+ sequence ids for UI dropdowns (base/ only)."""
    files = discover_sequence_files(directory)
    return [sequence_id(p, directory) for p in files]
