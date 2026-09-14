"""
Legacy Play Store automation — NOT used for DabFlow browser testing.

DabFlow runs via ``open_url`` → https://getdabflow.app (no Google account, no Play Store).
These helpers remain for optional manual /api/playstore/* calls only; the operator
dashboard (dashboard.html) does not link here.
"""
from __future__ import annotations

import random
import subprocess
import sys
import time
import threading
from typing import Callable, Optional

from adb_paths import adb_executable
from browser_adb import am_start_reported_landing, monkey_launch_reported

_SUBPROC_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _adb_result(serial: str, *args, timeout: int = 20) -> subprocess.CompletedProcess:
    exe = adb_executable()
    try:
        return subprocess.run(
            [exe, "-s", serial, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_SUBPROC_FLAGS,
        )
    except Exception as e:
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr=str(e))


def _adb(serial: str, *args, timeout: int = 20) -> str:
    try:
        r = _adb_result(serial, *args, timeout=timeout)
        return r.stdout.strip()
    except Exception as e:
        return f"ERROR: {e}"


def _screen_size(serial: str) -> tuple[int, int]:
    """Return (width, height) of the device screen."""
    raw = _adb(serial, "shell", "wm", "size")
    for part in (raw or "").split():
        part = part.replace("X", "x")
        if "x" in part and part.replace("x", "").isdigit():
            try:
                w, h = part.split("x")
                return int(w), int(h)
            except ValueError:
                pass
    return 1280, 720


def _scale(serial: str, x: int, y: int, base_w: int = 1280, base_h: int = 720) -> tuple[int, int]:
    """Scale coordinates from base resolution to actual device resolution."""
    w, h = _screen_size(serial)
    return round(x * w / base_w), round(y * h / base_h)


def _intent(serial: str, url: str) -> str:
    result = _adb_result(
        serial, "shell", "am", "start",
        "-a", "android.intent.action.VIEW",
        "-d", url,
    )
    return f"{result.stdout or ''}\n{result.stderr or ''}"


def _command_landed(result: subprocess.CompletedProcess) -> bool:
    """True when adb accepted an input command. Empty stdout is enough for a tap.

    A non-zero exit or an error line is not a tap, a swipe, or typed text.
    """
    if result.returncode != 0:
        return False
    blob = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
    if "error:" in blob or "exception" in blob:
        return False
    return True


def _input_text(serial: str, text: str) -> bool:
    safe = text.replace(" ", "%s").replace("'", "").replace('"', "")
    return _command_landed(_adb_result(serial, "shell", "input", "text", safe))


def _keyevent(serial: str, code: int) -> bool:
    return _command_landed(_adb_result(serial, "shell", "input", "keyevent", str(code)))


def _tap(serial: str, x: int, y: int) -> bool:
    return _command_landed(_adb_result(serial, "shell", "input", "tap", str(x), str(y)))


def _swipe(serial: str, x1: int, y1: int, x2: int, y2: int, ms: int = 400) -> bool:
    return _command_landed(
        _adb_result(
            serial, "shell", "input", "swipe",
            str(x1), str(y1), str(x2), str(y2), str(ms),
        )
    )


def _wake(serial: str):
    _adb(serial, "shell", "input", "keyevent", "224")
    time.sleep(0.4)
    _adb(serial, "shell", "input", "keyevent", "82")
    time.sleep(0.3)


def _intent_failed(result: str) -> bool:
    """True unless ``am start`` reported a start or a delivery.

    Any non-empty reply that is not ``Starting:``, ``intent has been delivered``,
    or ``brought to the front`` is not an open. Empty output is not an open.
    """
    return not am_start_reported_landing(result or "", "")


def open_store_page_serial(serial: str, package: str) -> bool:
    """Open the Play Store listing for a specific package.
    
    Tries market:// first (faster, deeper link). Falls back to https:// 
    for devices without Play Store (e.g. some emulators, F-Droid devices).
    """
    _wake(serial)
    result = _intent(serial, f"market://details?id={package}")
    time.sleep(2)
    if not _intent_failed(result):
        return True
    # If market:// fails (no Play Store), fall back to browser URL
    fallback = _intent(serial, f"https://play.google.com/store/apps/details?id={package}")
    time.sleep(2)
    return not _intent_failed(fallback)


def search_store(serial: str, query: str) -> bool:
    """Open Play Store search results for a query string."""
    _wake(serial)
    safe_q = query.replace(" ", "+")
    result = _intent(serial, f"market://search?q={safe_q}")
    time.sleep(2)
    if not _intent_failed(result):
        return True
    fallback = _intent(serial, f"https://play.google.com/store/search?q={safe_q}&c=apps")
    time.sleep(2)
    return not _intent_failed(fallback)


def install_from_store(serial: str, package: str, on_log: Optional[Callable] = None) -> bool:
    """Open the Play Store listing and tap Install.
    
    Coordinates are scaled dynamically from 1280x720 baseline.
    Install button is top-right of the app page in Play Store.
    """
    if on_log:
        on_log(f"{serial}: opening Play Store for {package}")
    if not open_store_page_serial(serial, package):
        if on_log:
            on_log(f"{serial}: store page did not open — Install was not tapped")
        return False

    ix, iy = _scale(serial, 1100, 200)
    if not _tap(serial, ix, iy):
        if on_log:
            on_log(f"{serial}: Install tap did not land")
        return False
    time.sleep(1)

    cx, cy = _scale(serial, 640, 450)
    if not _tap(serial, cx, cy):
        if on_log:
            on_log(f"{serial}: Install confirm tap did not land")
        return False
    time.sleep(2)

    if on_log:
        on_log(f"{serial}: Install tap sent — store did not confirm the install")
    return True


def launch_app(serial: str, package: str, on_log: Optional[Callable] = None) -> bool:
    """Launch an installed app via monkey launcher intent."""
    if on_log:
        on_log(f"{serial}: launching {package}")
    _wake(serial)
    result = _adb_result(
        serial, "shell", "monkey", "-p", package,
        "-c", "android.intent.category.LAUNCHER", "1",
    )
    time.sleep(2)
    if not monkey_launch_reported(result.stdout or "", result.stderr or ""):
        if on_log:
            on_log(f"{serial}: did not launch {package}")
        return False
    if on_log:
        on_log(f"{serial}: launch command landed — window not confirmed")
    return True


def leave_review(
    serial: str,
    package: str,
    stars: int,
    review_text: str,
    on_log: Optional[Callable] = None,
) -> bool:
    """Navigate to app's Play Store page, tap review section,
    select star rating, type the review, and submit.
    Coordinates scale dynamically from 1280x720 baseline.
    """
    if on_log:
        on_log(f"{serial}: opening review page for {package}")
    if not open_store_page_serial(serial, package):
        if on_log:
            on_log(f"{serial}: store page did not open — review was not sent")
        return False
    for _ in range(3):
        x1, y1 = _scale(serial, 640, 500)
        x2, y2 = _scale(serial, 640, 200)
        if not _swipe(serial, x1, y1, x2, y2, 500):
            if on_log:
                on_log(f"{serial}: review swipe did not land")
            return False
        time.sleep(0.6)

    wx, wy = _scale(serial, 640, 550)
    if not _tap(serial, wx, wy):
        if on_log:
            on_log(f"{serial}: review tap did not land")
        return False
    time.sleep(1.5)

    try:
        star_n = int(stars)
    except (TypeError, ValueError):
        star_n = 5
    star_n = max(1, min(5, star_n))
    star_x_base = 270 + (star_n - 1) * 100
    sx, sy = _scale(serial, star_x_base, 400)
    if not _tap(serial, sx, sy):
        if on_log:
            on_log(f"{serial}: star tap did not land")
        return False
    time.sleep(0.8)

    tx, ty = _scale(serial, 640, 500)
    if not _tap(serial, tx, ty):
        if on_log:
            on_log(f"{serial}: review field tap did not land")
        return False
    time.sleep(0.6)

    if not _input_text(serial, review_text):
        if on_log:
            on_log(f"{serial}: review text did not land")
        return False
    time.sleep(0.4)

    sbx, sby = _scale(serial, 1050, 620)
    if not _tap(serial, sbx, sby):
        if on_log:
            on_log(f"{serial}: review submit tap did not land")
        return False
    time.sleep(1)

    if on_log:
        on_log(f"{serial}: review taps sent — store did not confirm the review ({star_n} star)")
    return True


def run_full_sequence(
    phones: list[dict],
    package: str,
    search_query: str,
    stars: int,
    review_text: str,
    delay_secs: int,
    on_log: Optional[Callable] = None,
    on_complete: Optional[Callable] = None,
):
    """
    Run the full Play Store sequence on each phone, staggered by delay_secs.
    Sequence per phone: search -> open page -> install -> launch -> review.
    phones: list of dicts with at least {"serial": str, "name": str, "running": bool}
    """
    def run():
        running = [p for p in phones if p.get("running")]
        landed = 0
        failed = 0
        asked = bool(search_query or package or (review_text and stars))
        for i, phone in enumerate(running):
            serial = phone["serial"]
            name = phone.get("name", serial)
            if i > 0 and delay_secs > 0:
                actual = max(0.1, delay_secs + random.uniform(-delay_secs * 0.3, delay_secs * 0.3))
                time.sleep(actual)
            phone_ok = asked
            try:
                if search_query:
                    if on_log:
                        on_log(f"{name}: searching for '{search_query}'")
                    if not search_store(serial, search_query):
                        phone_ok = False
                        if on_log:
                            on_log(f"{name}: search did not open")
                    else:
                        time.sleep(2)
                if phone_ok and package:
                    if not install_from_store(serial, package, on_log=on_log):
                        phone_ok = False
                    else:
                        time.sleep(5)
                        if not launch_app(serial, package, on_log=on_log):
                            phone_ok = False
                        else:
                            time.sleep(3)
                if phone_ok and review_text and stars:
                    if not leave_review(serial, package, stars, review_text, on_log=on_log):
                        phone_ok = False
            except Exception as e:
                phone_ok = False
                if on_log:
                    on_log(f"{name}: error - {e}")
            if phone_ok:
                landed += 1
            else:
                failed += 1
        if on_complete:
            on_complete({"landed": landed, "failed": failed, "targeted": len(running)})
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t
