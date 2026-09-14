"""
Detect MuMu Player installs on Windows (ARM64, Global 12, legacy).

Used by PharmFlowMuMuSetup checklist and farm VM profile scanning.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

IS_WIN = sys.platform == "win32"

MUMU_MANAGER_EXES = (
    "nemux-shell-winui.Manager.exe",
    "MuMuManager.exe",
)

MUMU_GUI_EXES = (
    "MuMuPlayer.exe",
    "MuMuNxMain.exe",
    "MuMuMultiPlayer.exe",
    "nemux-shell-winui.exe",
)

MUMU_KNOWN_EXES = MUMU_MANAGER_EXES + MUMU_GUI_EXES

# Relative paths under Program Files / custom Netease root.
MUMU_RELATIVE_FOLDERS = (
    "Netease/MuMuPlayerARM",
    "Netease/MuMuPlayer",
    "Netease/MuMuPlayerGlobal-12.0",
    "Netease/MuMuPlayer-12.0",
    "Netease/MuMu Player 12",
    "MuMuPlayerARM",
    "MuMuPlayerGlobal-12.0",
    "MuMuPlayer-12.0",
    "MuMuPlayer",
    "MuMu Player 12",
)

MUMU_SUBDIRS = ("shell", "nx_main", "nx_device", "")

_SUBPROC_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WIN else 0


def _env_mumu_root() -> Path | None:
    raw = os.environ.get("PHARMFLOW_MUMU_ROOT", "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    return p if p.is_dir() else None


def _is_mumu_exe(path: Path) -> bool:
    return path.is_file() and path.name.lower() in {x.lower() for x in MUMU_KNOWN_EXES}


def install_root_from_exe(exe: Path) -> Path:
    """Walk upward from a MuMu binary until ``vms/`` exists."""
    cur = exe.resolve().parent
    for _ in range(6):
        if (cur / "vms").is_dir():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    p = exe.resolve()
    if p.parent.name.lower() in ("shell", "nx_main", "nx_device"):
        return p.parent.parent
    return p.parent


def _where_hits() -> list[Path]:
    hits: list[Path] = []
    if not IS_WIN:
        return hits
    for query in (*MUMU_MANAGER_EXES, *MUMU_GUI_EXES):
        try:
            r = subprocess.run(
                ["where", query],
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=_SUBPROC_FLAGS,
            )
            if r.returncode != 0:
                continue
            for line in (r.stdout or "").splitlines():
                p = Path(line.strip())
                if _is_mumu_exe(p):
                    hits.append(p)
        except (OSError, subprocess.TimeoutExpired):
            continue
    return hits


def _registry_install_dirs() -> list[Path]:
    dirs: list[Path] = []
    if not IS_WIN:
        return dirs
    try:
        import winreg
    except ImportError:
        return dirs
    reg_roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, reg_path in reg_roots:
        try:
            key = winreg.OpenKey(hive, reg_path)
        except OSError:
            continue
        i = 0
        while True:
            try:
                sub_name = winreg.EnumKey(key, i)
                i += 1
            except OSError:
                break
            try:
                sub = winreg.OpenKey(key, sub_name)
                name_val = winreg.QueryValueEx(sub, "DisplayName")[0]
                if "mumu" not in str(name_val).lower():
                    winreg.CloseKey(sub)
                    continue
                for val_name in ("InstallLocation", "InstallDir", "DisplayIcon"):
                    try:
                        raw = str(winreg.QueryValueEx(sub, val_name)[0]).strip().strip('"')
                        # DisplayIcon is often ``C:\...\MuMuPlayer.exe,0``
                        if "," in raw:
                            raw = raw.rsplit(",", 1)[0].strip().strip('"')
                        loc = Path(raw)
                        if loc.is_file():
                            loc = loc.parent
                        if loc.is_dir():
                            dirs.append(loc)
                    except OSError:
                        pass
                winreg.CloseKey(sub)
            except OSError:
                continue
        winreg.CloseKey(key)
    return dirs


def _base_dirs() -> list[Path]:
    bases: list[Path] = []
    env_root = _env_mumu_root()
    if env_root is not None:
        bases.append(env_root)
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA", "PROGRAMW6432"):
        raw = os.environ.get(var, "")
        if raw:
            bases.append(Path(raw))
    seen: set[str] = set()
    out: list[Path] = []
    for b in bases:
        key = str(b).lower()
        if key in seen:
            continue
        seen.add(key)
        if b.is_dir():
            out.append(b)
    return out


def _candidate_exes() -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        if not _is_mumu_exe(p):
            return
        key = str(p.resolve()).lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(p)

    env_root = _env_mumu_root()
    if env_root is not None:
        for sub in MUMU_SUBDIRS:
            for name in MUMU_KNOWN_EXES:
                add(env_root / sub / name if sub else env_root / name)

    for hit in _where_hits():
        add(hit)

    for reg_dir in _registry_install_dirs():
        for sub in MUMU_SUBDIRS:
            for name in MUMU_KNOWN_EXES:
                add(reg_dir / sub / name if sub else reg_dir / name)
        try:
            for name in MUMU_KNOWN_EXES:
                for p in reg_dir.rglob(name):
                    if p.is_file():
                        add(p)
        except OSError:
            pass

    for base in _base_dirs():
        for rel in MUMU_RELATIVE_FOLDERS:
            root = base / rel.replace("/", os.sep)
            for sub in MUMU_SUBDIRS:
                for name in MUMU_KNOWN_EXES:
                    add(root / sub / name if sub else root / name)
        try:
            netease = base / "Netease"
            if netease.is_dir():
                for child in netease.iterdir():
                    if not child.is_dir() or "mumu" not in child.name.lower():
                        continue
                    for sub in MUMU_SUBDIRS:
                        for name in MUMU_KNOWN_EXES:
                            add(child / sub / name if sub else child / name)
            for child in base.glob("MuMu*"):
                if not child.is_dir():
                    continue
                for sub in MUMU_SUBDIRS:
                    for name in MUMU_KNOWN_EXES:
                        add(child / sub / name if sub else child / name)
        except OSError:
            continue

    # Prefer manager CLI over GUI when both exist.
    def sort_key(p: Path) -> tuple[int, str]:
        name = p.name.lower()
        if name in {x.lower() for x in MUMU_MANAGER_EXES}:
            return (0, str(p))
        return (1, str(p))

    candidates.sort(key=sort_key)
    return candidates


def find_mumu_install() -> Path | None:
    """Return a MuMu executable path, or None if not found."""
    if not IS_WIN:
        return None
    hits = _candidate_exes()
    return hits[0] if hits else None


def find_mumu_install_root() -> Path | None:
    """Return MuMu install root (directory containing ``vms/`` when present)."""
    exe = find_mumu_install()
    if exe is None:
        return None
    return install_root_from_exe(exe)


def iter_mumu_install_roots() -> list[Path]:
    """All unique MuMu install roots discovered on this PC."""
    roots: list[Path] = []
    seen: set[str] = set()
    for exe in _candidate_exes():
        root = install_root_from_exe(exe)
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        roots.append(root)
    env_root = _env_mumu_root()
    if env_root is not None:
        key = str(env_root).lower()
        if key not in seen:
            roots.insert(0, env_root)
    return roots
