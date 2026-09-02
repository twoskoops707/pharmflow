"""Chromium / ChromePublic first-run — dismiss Skip ahead, sync, and ToS screens."""
from __future__ import annotations

import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from typing import Callable

from adb_paths import adb_executable
from session_notes_uia import adb_tap, _dump_ui_xml

LogFn = Callable[[str], None]

_NO_WIN = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

# Prefer skip / no-account / stay-signed-out before accepting ToS.
_SKIP_LABELS: tuple[str, ...] = (
    "stay signed out",
    "skip ahead",
    "skip",
    "use without an account",
    "no thanks",
    "not now",
    "no, thanks",
)

_ACCEPT_LABELS: tuple[str, ...] = (
    "accept & continue",
    "accept and continue",
    "i agree",
    "continue",
    "got it",
)


def _bounds_center(bounds: str) -> tuple[int, int] | None:
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    return (x1 + x2) // 2, (y1 + y2) // 2


def _center_for_label(xml: str, label: str) -> tuple[int, int] | None:
    if not xml.strip():
        return None
    target = label.strip().lower()
    esc = re.escape(label)
    for pat in (
        rf'text="{esc}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        rf'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*text="{esc}"',
        rf'content-desc="{esc}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
    ):
        m = re.search(pat, xml, flags=re.IGNORECASE)
        if m:
            x1, y1, x2, y2 = map(int, m.groups())
            return (x1 + x2) // 2, (y1 + y2) // 2
    try:
        root = ET.fromstring(xml)
        for node in root.iter("node"):
            texts = (
                node.attrib.get("text", ""),
                node.attrib.get("content-desc", ""),
            )
            if not any(t.strip().lower() == target for t in texts):
                continue
            center = _bounds_center(node.attrib.get("bounds", ""))
            if center:
                return center
    except ET.ParseError:
        pass
    return None


def _find_fre_tap(xml: str) -> tuple[tuple[int, int], str] | None:
    for label in _SKIP_LABELS:
        center = _center_for_label(xml, label)
        if center:
            return center, label
    for label in _ACCEPT_LABELS:
        center = _center_for_label(xml, label)
        if center:
            return center, label
    return None


def chromium_fre_visible(serial: str) -> bool:
    return _find_fre_tap(_dump_ui_xml(serial)) is not None


def dismiss_chromium_fre(
    serial: str,
    *,
    max_rounds: int = 8,
    log_fn: LogFn | None = None,
) -> bool:
    """Tap Stay signed out / Skip ahead / Use without an account until prompts are gone."""
    log = log_fn or (lambda _m: None)
    for round_i in range(max(1, max_rounds)):
        hit = _find_fre_tap(_dump_ui_xml(serial))
        if not hit:
            return True
        center, label = hit
        log(f"    Chromium first-run: tap «{label}» @ ({center[0]}, {center[1]})")
        adb_tap(serial, center[0], center[1])
        time.sleep(0.85 if round_i == 0 else 0.5)
    if not chromium_fre_visible(serial):
        return True
    adb = adb_executable()
    for _ in range(3):
        subprocess.run(
            [adb, "-s", serial, "shell", "input", "keyevent", "4"],
            capture_output=True,
            timeout=15,
            creationflags=_NO_WIN,
        )
        time.sleep(0.35)
    return not chromium_fre_visible(serial)


def dismiss_chromium_fre_after_open(
    serial: str,
    *,
    log_fn: LogFn | None = None,
) -> bool:
    """Dismiss sign-in / FRE prompts that appear right after launching Chromium."""
    ok = dismiss_chromium_fre(serial, max_rounds=10, log_fn=log_fn)
    time.sleep(1.25)
    ok = dismiss_chromium_fre(serial, max_rounds=6, log_fn=log_fn) and ok
    return ok
