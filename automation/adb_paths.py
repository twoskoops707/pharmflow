"""
Resolve the ``adb`` executable the same way PharmFlow (``wizard/setup_wizard.py``) prefers:
``ANDROID_HOME`` / default SDK layout / ``PATH``, not a bare ``adb`` name.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def _platform_tools_adb(sdk_root: str) -> Path | None:
    if not sdk_root:
        return None
    p = Path(sdk_root) / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
    return p if p.is_file() else None


def find_android_sdk() -> str:
    """Return SDK root containing ``platform-tools/``, or empty string."""
    extra = (os.environ.get("PHARMFLOW_ANDROID_SDK") or "").strip()
    candidates = [
        extra,
        os.environ.get("ANDROID_HOME", ""),
        os.environ.get("ANDROID_SDK_ROOT", ""),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk"),
        str(Path.home() / "Android" / "Sdk"),
        str(Path.home() / "Library" / "Android" / "sdk"),
        "C:/Android/Sdk",
        "C:/Users/Public/Android/Sdk",
    ]
    for p in candidates:
        if not p:
            continue
        root = str(Path(p))
        if Path(root, "platform-tools").is_dir():
            return root
    return ""


def adb_executable() -> str:
    """Resolve ONE adb binary for every component — bundled first.

    Two adb binaries (the PharmFlow bundled copy vs Android SDK platform-tools)
    fighting over port 5037 is the classic wedge: the newer client kills the
    older server and starts its own, dropping every phone mid-sequence. Always
    prefer the bundled adb (override with ``PHARMFLOW_BUNDLED_ADB``), then fall
    back to SDK / PATH so TCP emulators still work on machines without a bundle.
    """
    override = (os.environ.get("PHARMFLOW_BUNDLED_ADB") or "").strip()
    if override:
        p = Path(override)
        if p.is_file():
            return str(p)
    bundled = Path(__file__).resolve().parents[1] / "bundled" / (
        "adb.exe" if os.name == "nt" else "adb"
    )
    if bundled.is_file():
        return str(bundled)
    sdk = find_android_sdk()
    hit = _platform_tools_adb(sdk)
    if hit is not None:
        return str(hit)
    guess = Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools" / (
        "adb.exe" if os.name == "nt" else "adb"
    )
    if guess.is_file():
        return str(guess)
    w = shutil.which("adb")
    if w:
        return w
    return "adb"
