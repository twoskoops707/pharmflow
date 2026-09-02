"""Age-gate Yes button — uiautomator helpers (portrait + landscape MuMu Chrome)."""
from __future__ import annotations

import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from adb_paths import adb_executable

_AGE_YES_PATTERNS = (
    r'text="[^"]*YES, I AM 21[^"]*"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
    r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*text="[^"]*YES, I AM 21[^"]*"',
    r'resource-id="[^"]*age-yes[^"]*"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
    r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*resource-id="[^"]*age-yes[^"]*"',
)


def _no_win():
    """Hide console windows for adb child processes launched from the GUI EXE."""
    import sys

    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _dump_ui_xml(serial: str) -> str:
    adb = adb_executable()
    remote = "/sdcard/window_dump.xml"
    subprocess.run(
        [adb, "-s", serial, "shell", "uiautomator", "dump", remote],
        capture_output=True,
        timeout=60,
        creationflags=_no_win(),
    )
    local = Path(tempfile.gettempdir()) / f"cpharm_age_uia_{serial.replace(':', '_')}.xml"
    subprocess.run(
        [adb, "-s", serial, "pull", remote, str(local)],
        capture_output=True,
        timeout=30,
        creationflags=_no_win(),
    )
    if not local.is_file():
        return ""
    return local.read_text(encoding="utf-8", errors="replace")


def _bounds_center(bounds: tuple[int, int, int, int]) -> tuple[int, int]:
    x1, y1, x2, y2 = bounds
    return (x1 + x2) // 2, (y1 + y2) // 2


def age_yes_button_screen_bounds(serial: str) -> tuple[int, int, int, int] | None:
    text = _dump_ui_xml(serial)
    if not text.strip():
        return None
    for pat in _AGE_YES_PATTERNS:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return tuple(map(int, m.groups()))  # type: ignore[return-value]
    try:
        root = ET.fromstring(text)
        for node in root.iter("node"):
            label = node.attrib.get("text", "") or node.attrib.get("content-desc", "")
            norm = label.strip().lower()
            if "yes, i am 21" not in norm and "age-yes" not in norm:
                continue
            m = re.match(
                r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",
                node.attrib.get("bounds", ""),
            )
            if m:
                return tuple(map(int, m.groups()))  # type: ignore[return-value]
    except ET.ParseError:
        pass
    return None


def age_yes_button_screen_center(serial: str) -> tuple[int, int] | None:
    b = age_yes_button_screen_bounds(serial)
    if not b:
        return None
    return _bounds_center(b)


def age_gate_modal_visible(serial: str) -> bool:
    return age_yes_button_screen_center(serial) is not None


def wait_for_age_yes_button(serial: str, *, timeout_sec: float = 12.0) -> tuple[int, int] | None:
    """Poll uiautomator until the Yes button appears (avoids tapping before the modal loads)."""
    import time

    deadline = time.monotonic() + max(0.5, float(timeout_sec))
    while time.monotonic() < deadline:
        center = age_yes_button_screen_center(serial)
        if center:
            return center
        time.sleep(0.35)
    return None
