#!/usr/bin/env python3
"""
Verify DabFlow age gate before funnel taps: Playwright coord check + optional emulator run.

Run from repo root::

    py -3 automation/smoke_browser_and_sequence.py

Uses ``dabflow_layout.AGE_YES``, ``browser_coord_smoke`` logic, and wizard ``execute_steps``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_AUTOMATION = ROOT / "automation"


def _playwright_age_gate_check() -> int:
    sys.path.insert(0, str(_AUTOMATION))
    from dabflow_layout import AGE_YES

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIP: playwright not installed (browser age gate check)")
        return 0

    url = "https://getdabflow.app"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 900, "height": 1600})
        page.goto(url, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(3000)
        btn = page.query_selector("#age-yes-btn")
        if btn is None:
            print("FAIL: #age-yes-btn missing before tap")
            browser.close()
            return 1
        rect = btn.bounding_box() or {}
        cx = int(rect.get("x", 0) + rect.get("width", 0) / 2)
        cy = int(rect.get("y", 0) + rect.get("height", 0) / 2)
        print(f"age-yes-btn center=({cx},{cy}) layout=({AGE_YES.cx},{AGE_YES.cy})")
        page.mouse.click(AGE_YES.cx, AGE_YES.cy)
        page.wait_for_timeout(1500)
        still = page.evaluate(
            """() => {
                const gate = document.getElementById('age-gate');
                const verified = localStorage.getItem('dabflow_age_verified') === 'true';
                const hidden = gate && (gate.style.display === 'none' || window.getComputedStyle(gate).display === 'none');
                return !(verified || hidden);
            }"""
        )
        browser.close()
        if still:
            print("FAIL: age gate still visible after layout tap")
            return 1
        print("OK: age gate cleared in Playwright @ 900x1600")
        return 0


def _first_tap_after_open(steps: list[dict]) -> dict | None:
    seen_open = False
    for step in steps:
        if not isinstance(step, dict):
            continue
        t = step.get("type")
        if t == "open_url":
            seen_open = True
            continue
        if t == "wait":
            continue
        if seen_open and t == "tap":
            return step
    return None


def _age_gate_prefix(steps: list[dict]) -> list[dict]:
    """Steps through first post-age wait (inclusive), stopping before material tap."""
    out: list[dict] = []
    age_done = False
    for step in steps:
        if not isinstance(step, dict):
            continue
        t = step.get("type")
        out.append(dict(step))
        if t == "tap" and (
            step.get("age_verification") is True
            or step.get("age_gate") is True
            or str(step.get("checkpoint", "")).strip().lower() in ("age_verification", "age_gate")
        ):
            age_done = True
            continue
        if age_done and t == "wait":
            break
    return out


def _emulator_age_gate_smoke(serial: str) -> int:
    sys.path.insert(0, str(_AUTOMATION))
    from sequences_paths import resolve_sequences_dir

    seq_path = (
        resolve_sequences_dir(create=False)
        / "900x1600/ad/dabflow__ad__mat-ceramic__conc-distillate__heat-propane__timer1x__human080.json"
    )
    if not seq_path.is_file():
        print("FAIL: missing gold matrix sequence", seq_path)
        return 3

    raw = json.loads(seq_path.read_text(encoding="utf-8"))
    steps = raw if isinstance(raw, list) else raw.get("steps", [])
    first_tap = _first_tap_after_open(steps)
    if first_tap is None:
        print("FAIL: no tap found after open_url in matrix sequence")
        return 4
    if not (
        first_tap.get("age_verification") is True
        or first_tap.get("age_gate") is True
        or str(first_tap.get("checkpoint", "")).strip().lower() in ("age_verification", "age_gate")
    ):
        print("FAIL: first tap after open_url is not marked age_verification")
        return 5

    prefix = _age_gate_prefix(steps)
    print(f"=== emulator age gate prefix ({len(prefix)} steps) serial={serial} ===")

    sys.path.insert(0, str(ROOT / "wizard"))
    from setup_wizard import _normalize_sequence_steps, execute_steps

    norm = _normalize_sequence_steps(prefix)
    execute_steps(norm, serial)
    print("OK: emulator age gate prefix finished (verify UI cleared age modal manually if needed)")
    return 0


def main() -> int:
    sys.path.insert(0, str(_AUTOMATION))

    rc = _playwright_age_gate_check()
    if rc != 0:
        return rc

    from adb_paths import adb_executable

    adb = adb_executable()
    r = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=20)
    print("=== adb devices ===")
    print(r.stdout or "")
    if r.returncode != 0:
        print("WARN: adb devices failed; skipping emulator leg")
        return 0

    serial = ""
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if line.endswith("\tdevice"):
            serial = line.split("\t", 1)[0].strip()
            break
    if not serial:
        print("SKIP: no emulator — Playwright age gate check passed")
        return 0

    return _emulator_age_gate_smoke(serial)


if __name__ == "__main__":
    raise SystemExit(main())
