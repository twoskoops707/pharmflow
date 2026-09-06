"""Auto-detect programs with manual browse fallback."""

from __future__ import annotations

import logging
from collections.abc import Callable
from tkinter import messagebox
from typing import Any

from wizard.gui.path_selector import PathSelectorWindow
from wizard.path_store import PROGRAM_ADB, PROGRAM_MUMU, PROGRAM_MUMU_MANAGER, PROGRAM_TOR
from wizard.path_utils import (
    DetectionResult,
    apply_adb_path,
    apply_for_program,
    apply_mumu_path,
    apply_tor_path,
    auto_detect_adb,
    auto_detect_mumu,
    auto_detect_tor,
)
from wizard.wizard_paths import load_config

logger = logging.getLogger(__name__)

__all__ = [
    "DetectionResult",
    "apply_adb_path",
    "apply_mumu_path",
    "apply_tor_path",
    "auto_detect_adb",
    "auto_detect_mumu",
    "auto_detect_tor",
    "detect_all_with_fallback",
    "detect_with_fallback",
]


def detect_with_fallback(
    parent: Any,
    program_name: str,
    auto_detect_function: Callable[[], DetectionResult],
    *,
    allow_manual: bool = True,
    current_path: str | None = None,
) -> DetectionResult:
    """Try auto-detect; offer manual browse when detection fails."""
    result = auto_detect_function()
    if result.found:
        # Persist auto-detected paths (Tor/ADB locate previously returned found
        # without save_config, so the next launch forgot them).
        if result.path:
            applied = apply_for_program(program_name, result.path)
            if applied.found:
                return applied
        return result

    if not allow_manual:
        return result

    if not messagebox.askyesno(
        f"{program_name} Not Found",
        f"Auto-detection couldn't find {program_name}.\n\nWould you like to manually locate it?",
        parent=parent,
    ):
        return DetectionResult(found=False, manual=False, detail=result.detail)

    if current_path is None:
        cfg = load_config()
        if program_name in (PROGRAM_MUMU, PROGRAM_MUMU_MANAGER):
            current_path = cfg.get("mumu_root") or result.path
        elif program_name == PROGRAM_TOR:
            current_path = cfg.get("tor_path") or result.path
        elif program_name == PROGRAM_ADB:
            current_path = cfg.get("adb_path") or result.path

    selector = PathSelectorWindow(parent, program_name, current_path=current_path)
    manual_path = selector.get_result()
    if not manual_path:
        return DetectionResult(found=False, manual=True, detail="Cancelled")

    applied = apply_for_program(program_name, manual_path)
    if applied.found:
        logger.info("Manual path for %s: %s", program_name, applied.path)
        return applied

    messagebox.showwarning("Invalid Path", applied.detail or "Please choose a valid location.", parent=parent)
    return applied


def detect_all_with_fallback(parent: Any) -> dict[str, DetectionResult]:
    """Run detection + manual fallback for MuMu, Tor, and ADB."""
    return {
        PROGRAM_MUMU: detect_with_fallback(parent, PROGRAM_MUMU, auto_detect_mumu),
        PROGRAM_TOR: detect_with_fallback(parent, PROGRAM_TOR, auto_detect_tor),
        PROGRAM_ADB: detect_with_fallback(parent, PROGRAM_ADB, auto_detect_adb),
    }
