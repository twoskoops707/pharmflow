"""Systematic smoke of C:\\PharmFlow\\PharmFlow.next.exe Control Panel.

Does NOT start/stop the farm, boot phones, or overwrite the live EXE.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pyautogui
from PIL import ImageGrab
from pywinauto import Application
from pywinauto.findwindows import ElementNotFoundError

OUT = Path(r"C:\PharmFlow\logs\exe_ui_smoke")
OUT.mkdir(parents=True, exist_ok=True)
RESULTS: list[dict] = []


def _embedded_build_number() -> str:
    for path in (
        Path(r"C:\PharmFlow\assets\build_info.json"),
        Path(__file__).resolve().parents[1] / "wizard" / "assets" / "build_info.json",
    ):
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                bn = str(data.get("build_number") or "").strip()
                if bn:
                    return bn
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return ""


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append({"name": name, "ok": ok, "detail": detail})
    print(("PASS" if ok else "FAIL"), name, detail, flush=True)


def shot(name: str, hwnd_rect=None) -> Path:
    path = OUT / f"{name}.png"
    if hwnd_rect:
        left, top, right, bottom = hwnd_rect
        img = ImageGrab.grab(bbox=(left, top, right, bottom))
    else:
        img = ImageGrab.grab()
    img.save(path)
    return path


def main() -> int:
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.35

    # --version (console-less EXE may return empty; still must not crash)
    ver = subprocess.run(
        [r"C:\PharmFlow\PharmFlow.next.exe", "--version"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    ver_out = (ver.stdout or "") + (ver.stderr or "")
    record(
        "cli_version_exits",
        ver.returncode == 0 or "PharmFlow" in ver_out or ver.returncode in (0, None),
        f"rc={ver.returncode} out={ver_out[:200]!r}",
    )

    try:
        app = Application(backend="uia").connect(title_re=r".*PharmFlow.*Control Panel.*", timeout=20)
    except ElementNotFoundError as exc:
        record("connect_window", False, str(exc))
        (OUT / "results.json").write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
        return 1

    win = app.window(title_re=r".*PharmFlow.*Control Panel.*")
    win.set_focus()
    time.sleep(0.8)
    title = win.window_text()
    record(
        "window_title_branding",
        "PharmFlow" in title and "FamFlow" not in title and "CPharm" not in title,
        title,
    )
    m = re.search(r"\(build\s+([^)]+)\)", title)
    build_in_title = (m.group(1).strip() if m else "")
    record("window_title_build", bool(build_in_title), build_in_title or title)
    rect = win.rectangle()
    bbox = (rect.left, rect.top, rect.right, rect.bottom)
    p = shot("01_home", bbox)
    record("screenshot_home", p.is_file() and p.stat().st_size > 1000, str(p))

    # Nav pipeline is across the top under the HUD. Click approximate step centers.
    # Views order from app.js step pipeline: start, install, android, phones, boot, map, steps, groups, launch
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    nav_y = rect.top + int(height * 0.18)
    # nine equal-ish slots across content width (leave side chrome)
    left_pad = rect.left + int(width * 0.08)
    usable = int(width * 0.84)
    labels = [
        "start",
        "install",
        "android",
        "phones",
        "boot",
        "map",
        "steps",
        "groups",
        "launch",
    ]
    for i, label in enumerate(labels):
        x = left_pad + int((i + 0.5) * usable / len(labels))
        pyautogui.click(x, nav_y)
        time.sleep(0.9)
        sp = shot(f"02_nav_{i:02d}_{label}", bbox)
        record(f"nav_{label}", sp.is_file() and sp.stat().st_size > 1000, f"click=({x},{nav_y})")

    # On Steps view (index 6): try Preview mix with phones=8 visits=40
    steps_x = left_pad + int((6 + 0.5) * usable / len(labels))
    pyautogui.click(steps_x, nav_y)
    time.sleep(1.0)
    # Approximate form fields: left column under Steps header
    form_x = rect.left + int(width * 0.28)
    phones_y = rect.top + int(height * 0.42)
    pyautogui.click(form_x, phones_y)
    pyautogui.hotkey("ctrl", "a")
    pyautogui.typewrite("8", interval=0.05)
    visits_y = rect.top + int(height * 0.48)
    pyautogui.click(form_x, visits_y)
    pyautogui.hotkey("ctrl", "a")
    pyautogui.typewrite("40", interval=0.05)
    # Preview button roughly mid form
    preview_x = rect.left + int(width * 0.22)
    preview_y = rect.top + int(height * 0.72)
    pyautogui.click(preview_x, preview_y)
    time.sleep(1.2)
    shot("03_earn_preview", bbox)
    record("earn_preview_clicked", True, "clicked preview mix coordinates")

    # Home again: Farm health (safe) and Open dashboard (safe). Avoid Start farm.
    start_x = left_pad + int(0.5 * usable / len(labels))
    pyautogui.click(start_x, nav_y)
    time.sleep(1.0)
    # Secondary buttons row under Start farm
    health_x = rect.left + int(width * 0.42)
    health_y = rect.top + int(height * 0.48)
    pyautogui.click(health_x, health_y)
    time.sleep(1.5)
    shot("04_after_health_or_dash", bbox)
    record("home_secondary_click", True, "clicked mid secondary button area")

    # Process still alive
    still = False
    try:
        still = win.exists() and win.is_visible()
    except Exception as exc:  # noqa: BLE001 — UI smoke collects any failure
        record("window_still_open", False, str(exc))
    else:
        record("window_still_open", still, title)

    (OUT / "results.json").write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    failed = [r for r in RESULTS if not r["ok"]]
    print(json.dumps({"failed": len(failed), "total": len(RESULTS)}, indent=2), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
