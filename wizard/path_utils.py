"""Path normalization, apply, and auto-detect (no GUI dependencies)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wizard.path_store import (
    PROGRAM_ADB,
    PROGRAM_MUMU,
    PROGRAM_MUMU_MANAGER,
    PROGRAM_TOR,
    load_saved_paths,
    remember_path,
)
from wizard.wizard_paths import (
    bundled_adb_path,
    detect_mumu_root,
    mumu_manager_exe,
    save_config,
    tor_binary_path,
    validate_mumu_root,
)


@dataclass
class DetectionResult:
    found: bool
    path: str = ""
    manual: bool = False
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "path": self.path,
            "manual": self.manual,
            "detail": self.detail,
        }


def normalize_mumu_path(raw: str | Path) -> Path | None:
    """Accept install folder or MuMu manager EXE and return install root."""
    path = Path(raw)
    if path.is_file():
        name = path.name.lower()
        if name == "mumumanager.exe":
            root = path.parent.parent if path.parent.name.lower() == "shell" else path.parent
            return root if validate_mumu_root(root) else None
        if name == "mumunxmain.exe":
            root = path.parent.parent if path.parent.name.lower() == "nx_main" else path.parent
            return root if validate_mumu_root(root) else None
        if name == "nemux-shell-winui.manager.exe":
            root = path.parent.parent if path.parent.name.lower() == "manager" else path.parent
            return root if validate_mumu_root(root) else None
        if name == "nemux-shell-winui.exe":
            root = path.parent.parent if path.parent.name.lower() == "shell" else path.parent
            return root if validate_mumu_root(root) else None
    if validate_mumu_root(path):
        return path
    return None


def normalize_tor_path(raw: str | Path) -> Path | None:
    path = Path(raw)
    if path.is_file() and path.name.lower() == "tor.exe":
        return path
    candidate = path / "tor.exe"
    return candidate if candidate.is_file() else None


def normalize_adb_path(raw: str | Path) -> Path | None:
    path = Path(raw)
    if path.is_file() and path.name.lower() == "adb.exe":
        return path
    candidate = path / "adb.exe"
    return candidate if candidate.is_file() else None


def apply_mumu_path(raw: str | Path) -> DetectionResult:
    root = normalize_mumu_path(raw)
    if not root:
        return DetectionResult(found=False, detail="Not a valid MuMu install folder")
    save_config({"mumu_root": str(root)})
    remember_path(PROGRAM_MUMU, str(root))
    mgr = mumu_manager_exe(root)
    if mgr:
        remember_path(PROGRAM_MUMU_MANAGER, str(mgr))
    return DetectionResult(found=True, path=str(root), manual=True, detail=str(root))


def apply_tor_path(raw: str | Path) -> DetectionResult:
    tor = normalize_tor_path(raw)
    if not tor:
        return DetectionResult(found=False, detail="Select tor.exe")
    save_config({"tor_path": str(tor)})
    remember_path(PROGRAM_TOR, str(tor))
    return DetectionResult(found=True, path=str(tor), manual=True, detail=str(tor))


def apply_adb_path(raw: str | Path) -> DetectionResult:
    adb = normalize_adb_path(raw)
    if not adb:
        return DetectionResult(found=False, detail="Select adb.exe")
    save_config({"adb_path": str(adb)})
    remember_path(PROGRAM_ADB, str(adb))
    return DetectionResult(found=True, path=str(adb), manual=True, detail=str(adb))


def auto_detect_mumu() -> DetectionResult:
    root = detect_mumu_root()
    if root:
        return DetectionResult(found=True, path=str(root), detail=str(root))
    # Fall back to manually remembered install roots (saved_paths.json).
    for raw in reversed(load_saved_paths().get(PROGRAM_MUMU, [])):
        normalized = normalize_mumu_path(raw)
        if normalized:
            return DetectionResult(found=True, path=str(normalized), detail=str(normalized))
    return DetectionResult(found=False, detail="MuMu not found")


def auto_detect_mumu_manager() -> DetectionResult:
    mgr = mumu_manager_exe()
    if mgr and mgr.is_file():
        return DetectionResult(found=True, path=str(mgr), detail=str(mgr))
    for raw in reversed(load_saved_paths().get(PROGRAM_MUMU_MANAGER, [])):
        p = Path(raw)
        if p.is_file():
            return DetectionResult(found=True, path=str(p), detail=str(p))
    return DetectionResult(found=False, detail="MuMuManager.exe not found")


def auto_detect_tor() -> DetectionResult:
    tor = tor_binary_path()
    if tor.is_file():
        return DetectionResult(found=True, path=str(tor), detail=str(tor))
    for raw in reversed(load_saved_paths().get(PROGRAM_TOR, [])):
        normalized = normalize_tor_path(raw)
        if normalized:
            return DetectionResult(found=True, path=str(normalized), detail=str(normalized))
    return DetectionResult(found=False, detail="tor.exe not found")


def auto_detect_adb() -> DetectionResult:
    adb = bundled_adb_path()
    if adb.is_file():
        return DetectionResult(found=True, path=str(adb), detail=str(adb))
    for raw in reversed(load_saved_paths().get(PROGRAM_ADB, [])):
        normalized = normalize_adb_path(raw)
        if normalized:
            return DetectionResult(found=True, path=str(normalized), detail=str(normalized))
    return DetectionResult(found=False, detail="adb.exe not found")


def apply_for_program(program_name: str, raw: str) -> DetectionResult:
    if program_name in (PROGRAM_MUMU, PROGRAM_MUMU_MANAGER):
        return apply_mumu_path(raw)
    if program_name == PROGRAM_TOR:
        return apply_tor_path(raw)
    if program_name == PROGRAM_ADB:
        return apply_adb_path(raw)
    return DetectionResult(found=False, detail=f"Unknown program: {program_name}")
