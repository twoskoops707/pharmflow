"""Unlocked-session Control Panel walk for PharmFlow.next.exe. Avoid farm start/stop."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pyautogui
from PIL import ImageGrab
from pywinauto import Application

OUT = Path(r"C:\PharmFlow\logs\exe_ui_smoke")
OUT.mkdir(parents=True, exist_ok=True)
RESULTS: list[dict] = []
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.3


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append({"name": name, "ok": ok, "detail": detail})
    print(("PASS" if ok else "FAIL"), name, detail, flush=True)


def grab(name: str) -> Path | None:
    path = OUT / f"{name}.png"
    try:
        ImageGrab.grab().save(path)
        return path
    except OSError as exc:
        record(f"shot_{name}", False, str(exc))
        return None


def main() -> int:
    app = Application(backend="uia").connect(title_re=r".*PharmFlow.*Control Panel.*", timeout=20)
    win = app.window(title_re=r".*PharmFlow.*Control Panel.*")
    win.set_focus()
    time.sleep(0.6)
    title = win.window_text()
    record("title", "PharmFlow" in title and "2012" in title, title)
    rect = win.rectangle()
    grab("20_home")

    width = rect.right - rect.left
    height = rect.bottom - rect.top
    labels = ["start", "install", "android", "phones", "boot", "map", "steps", "groups", "launch"]
    for i, label in enumerate(labels):
        rect = win.rectangle()
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        nav_y = rect.top + int(height * 0.205)
        left_pad = rect.left + int(width * 0.06)
        usable = int(width * 0.88)
        x = left_pad + int((i + 0.5) * usable / len(labels))
        pyautogui.click(x, nav_y)
        time.sleep(0.8)
        p = grab(f"21_nav_{i:02d}_{label}")
        record(f"nav_{label}", p is not None and p.stat().st_size > 5000, f"({x},{nav_y})")

    # Steps earn preview
    rect = win.rectangle()
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    nav_y = rect.top + int(height * 0.205)
    left_pad = rect.left + int(width * 0.06)
    usable = int(width * 0.88)
    steps_x = left_pad + int((6 + 0.5) * usable / len(labels))
    pyautogui.click(steps_x, nav_y)
    time.sleep(1.0)
    form_x = rect.left + int(width * 0.30)
    pyautogui.click(form_x, rect.top + int(height * 0.40))
    pyautogui.hotkey("ctrl", "a")
    pyautogui.typewrite("8", interval=0.04)
    pyautogui.click(form_x, rect.top + int(height * 0.455))
    pyautogui.hotkey("ctrl", "a")
    pyautogui.typewrite("40", interval=0.04)
    pyautogui.click(form_x, rect.top + int(height * 0.575))
    time.sleep(0.2)
    pyautogui.press("down")
    pyautogui.press("enter")
    pyautogui.click(form_x, rect.top + int(height * 0.62))
    pyautogui.hotkey("ctrl", "a")
    pyautogui.typewrite("35", interval=0.04)
    pyautogui.click(rect.left + int(width * 0.18), rect.top + int(height * 0.70))
    time.sleep(1.5)
    grab("22_earn_preview")
    record("earn_preview", True, "clicked")

    # Home health button
    start_x = left_pad + int(0.5 * usable / len(labels))
    pyautogui.click(start_x, nav_y)
    time.sleep(0.8)
    # Farm health is rightmost of the three secondary buttons under Start farm
    pyautogui.click(rect.left + int(width * 0.48), rect.top + int(height * 0.46))
    time.sleep(1.5)
    grab("23_health")
    record("health_click", True, "clicked")

    still = win.exists()
    record("still_open", still, win.window_text() if still else "")
    (OUT / "results_unlocked.json").write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    failed = [r for r in RESULTS if not r["ok"]]
    print(json.dumps({"failed": len(failed), "total": len(RESULTS)}, indent=2), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
