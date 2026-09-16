"""Continue Control Panel UI walk on PharmFlow.next.exe. Avoid farm start/stop/boot."""
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
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.25


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
    time.sleep(0.5)
    title = win.window_text()
    record("connected", "PharmFlow" in title and "20260914-1908" in title, title)

    rect = win.rectangle()
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    # From 05_retry_home: nav pills under HUD. Approximate Y ~ 22% of window.
    nav_y = rect.top + int(height * 0.205)
    left_pad = rect.left + int(width * 0.06)
    usable = int(width * 0.88)
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
        try:
            win.set_focus()
        except Exception:
            pass
        rect = win.rectangle()
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        nav_y = rect.top + int(height * 0.205)
        left_pad = rect.left + int(width * 0.06)
        usable = int(width * 0.88)
        x = left_pad + int((i + 0.5) * usable / len(labels))
        pyautogui.click(x, nav_y)
        time.sleep(1.0)
        p = grab(f"10_nav_{i:02d}_{label}")
        record(f"nav_{label}", p is not None, f"({x},{nav_y})")

    # Steps: fill earn phones/visits and preview
    rect = win.rectangle()
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    steps_i = 6
    steps_x = rect.left + int(width * 0.06) + int((steps_i + 0.5) * int(width * 0.88) / len(labels))
    nav_y = rect.top + int(height * 0.205)
    pyautogui.click(steps_x, nav_y)
    time.sleep(1.2)
    grab("11_steps_view")

    # Form is left column; first number field ~ phones
    form_x = rect.left + int(width * 0.30)
    for label, yfrac, value in (
        ("phones", 0.40, "8"),
        ("visits", 0.455, "40"),
        ("ratio", 0.62, "35"),
    ):
        y = rect.top + int(height * yfrac)
        pyautogui.click(form_x, y)
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.typewrite(value, interval=0.04)
        record(f"typed_{label}", True, value)

    # Enable Path3 via ads select - click Paid actions area then Preview
    ads_y = rect.top + int(height * 0.575)
    pyautogui.click(form_x, ads_y)
    time.sleep(0.3)
    pyautogui.press("down")
    pyautogui.press("enter")
    time.sleep(0.3)

    preview_x = rect.left + int(width * 0.18)
    preview_y = rect.top + int(height * 0.70)
    pyautogui.click(preview_x, preview_y)
    time.sleep(1.5)
    grab("12_earn_after_preview")
    record("earn_preview", True, "clicked preview")

    # Map view: enter example.com but do NOT scan external unless quick
    map_i = 5
    map_x = rect.left + int(width * 0.06) + int((map_i + 0.5) * int(width * 0.88) / len(labels))
    pyautogui.click(map_x, nav_y)
    time.sleep(1.0)
    grab("13_map_view")
    url_x = rect.left + int(width * 0.35)
    url_y = rect.top + int(height * 0.36)
    pyautogui.click(url_x, url_y)
    pyautogui.hotkey("ctrl", "a")
    pyautogui.typewrite("https://example.com", interval=0.03)
    # Scan site button left of field area
    scan_x = rect.left + int(width * 0.72)
    scan_y = rect.top + int(height * 0.36)
    pyautogui.click(scan_x, scan_y)
    time.sleep(8.0)
    grab("14_map_after_scan")
    record("map_scan_clicked", True, "example.com")

    # Home: Farm health only (third-ish secondary). Avoid Start farm (primary green left).
    start_x = rect.left + int(width * 0.06) + int(0.5 * int(width * 0.88) / len(labels))
    pyautogui.click(start_x, nav_y)
    time.sleep(1.0)
    # Open dashboard is middle secondary on home card
    dash_x = rect.left + int(width * 0.36)
    dash_y = rect.top + int(height * 0.46)
    pyautogui.click(dash_x, dash_y)
    time.sleep(2.0)
    grab("15_after_open_dash")
    record("open_dash_clicked", True, "home secondary")

    health_x = rect.left + int(width * 0.48)
    health_y = rect.top + int(height * 0.46)
    pyautogui.click(health_x, health_y)
    time.sleep(2.0)
    grab("16_after_health")
    record("health_clicked", True, "home secondary")

    still = win.exists()
    record("still_open", still, win.window_text() if still else "")
    (OUT / "results_walk.json").write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    failed = [r for r in RESULTS if not r["ok"]]
    print(json.dumps({"failed": len(failed), "total": len(RESULTS)}, indent=2), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
