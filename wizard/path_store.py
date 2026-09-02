"""Persist manually assigned program paths for reuse."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from wizard.wizard_paths import app_data_root

logger = logging.getLogger(__name__)

PROGRAM_MUMU = "MuMu Player"
PROGRAM_MUMU_MANAGER = "MuMu Manager"
PROGRAM_TOR = "Tor"
PROGRAM_ADB = "ADB"

ALL_PROGRAMS = (PROGRAM_MUMU, PROGRAM_MUMU_MANAGER, PROGRAM_TOR, PROGRAM_ADB)


def saved_paths_file() -> Path:
    return app_data_root() / "saved_paths.json"


def load_saved_paths() -> dict[str, list[str]]:
    path = saved_paths_file()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return {str(k): [str(p) for p in v if p] for k, v in raw.items() if isinstance(v, list)}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load saved paths: %s", exc)
        return {}


def save_saved_paths(data: dict[str, list[str]]) -> None:
    path = saved_paths_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def remember_path(program_name: str, path: str) -> None:
    """Append a path to the program history (most recent last)."""
    normalized = str(Path(path))
    data = load_saved_paths()
    entries = data.get(program_name, [])
    if normalized in entries:
        entries.remove(normalized)
    entries.append(normalized)
    data[program_name] = entries[-10:]
    save_saved_paths(data)
