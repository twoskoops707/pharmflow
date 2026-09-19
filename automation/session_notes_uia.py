"""Session-notes modal Skip button — uiautomator helpers for execute_steps."""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from automation.adb_paths import adb_executable
except ImportError:  # running with automation/ itself on sys.path
    from adb_paths import adb_executable

_SKIP_PATTERNS = (
    r'text="Skip"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
    r'resource-id="[^"]*skipSessionNotes[^"]*"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
    r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*text="Skip"',
    r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*resource-id="[^"]*skipSessionNotes[^"]*"',
)

_NO_WIN = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _no_win():
    """Hide console windows for adb child processes launched from the GUI EXE."""
    return _NO_WIN


def _dump_ui_xml(serial: str) -> str:
    adb = adb_executable()
    remote = "/sdcard/window_dump.xml"
    subprocess.run(
        [adb, "-s", serial, "shell", "uiautomator", "dump", remote],
        capture_output=True,
        timeout=60,
        creationflags=_no_win(),
    )
    local = Path(tempfile.gettempdir()) / f"pharmflow_uia_{serial.replace(':', '_')}.xml"
    subprocess.run(
        [adb, "-s", serial, "pull", remote, str(local)],
        capture_output=True,
        timeout=30,
        creationflags=_no_win(),
    )
    if not local.is_file():
        return ""
    return local.read_text(encoding="utf-8", errors="replace")


def skip_button_screen_bounds(serial: str) -> tuple[int, int, int, int] | None:
    text = _dump_ui_xml(serial)
    if not text.strip():
        return None
    for pat in _SKIP_PATTERNS:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return tuple(map(int, m.groups()))  # type: ignore[return-value]
    try:
        root = ET.fromstring(text)
        for node in root.iter("node"):
            label = (node.attrib.get("text") or "").strip().lower()
            rid = (node.attrib.get("resource-id") or "").lower()
            if label != "skip" and "skipsessionnotes" not in rid:
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


def skip_button_screen_center(serial: str) -> tuple[int, int] | None:
    b = skip_button_screen_bounds(serial)
    if not b:
        return None
    return (b[0] + b[2]) // 2, (b[1] + b[3]) // 2


def session_notes_modal_visible(serial: str) -> bool:
    return skip_button_screen_center(serial) is not None


def step_wants_session_notes_dismiss(step: dict | None) -> bool:
    """True when the authored step must not continue while the sheet is up."""
    if not isinstance(step, dict):
        return False
    if step.get("verify_dismiss") is True:
        return True
    return str(step.get("checkpoint") or "").strip().lower() == "popup_dismiss"


def step_wants_session_notes_gone(step: dict | None) -> bool:
    """True when the authored wait is only done after the sheet is gone."""
    if not isinstance(step, dict):
        return False
    if step.get("until_session_notes_gone") is True:
        return True
    return str(step.get("checkpoint") or "").strip().lower() == "popup_dismissed"


def wait_session_notes_gone(serial: str, *, timeout_sec: float = 8.0, poll_sec: float = 0.25) -> bool:
    deadline = time.time() + max(0.5, timeout_sec)
    while time.time() < deadline:
        if not session_notes_modal_visible(serial):
            return True
        time.sleep(poll_sec)
    return not session_notes_modal_visible(serial)


def adb_tap(serial: str, x: int, y: int) -> None:
    adb = adb_executable()
    subprocess.run(
        [adb, "-s", serial, "shell", "input", "tap", str(max(0, x)), str(max(0, y))],
        capture_output=True,
        timeout=30,
        creationflags=_no_win(),
    )


def dismiss_session_notes_verified(
    serial: str,
    *,
    json_tap: tuple[int, int] | None = None,
    json_tap_fn=None,
    max_rounds: int = 6,
) -> bool:
    for round_i in range(max_rounds):
        if not session_notes_modal_visible(serial):
            return True
        center = skip_button_screen_center(serial)
        if center:
            adb_tap(serial, center[0], center[1])
        elif json_tap and json_tap_fn:
            json_tap_fn(json_tap[0], json_tap[1])
        time.sleep(0.35 if round_i == 0 else 0.45)
    return not session_notes_modal_visible(serial)
