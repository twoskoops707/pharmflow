#!/usr/bin/env python3
"""Playwright smoke: DabFlow 900x1600 page load + coord elementFromPoint."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_AUTOMATION = Path(__file__).resolve().parent
sys.path.insert(0, str(_AUTOMATION))

from dabflow_layout import AGE_YES, GLASS_ART_SELECT, MAT_POS, START_DAB, STATS_AD_SLOT, HEAT_POS, nav_region
from sequences_paths import resolve_sequences_dir

SEQ_AD = (
    resolve_sequences_dir(create=False)
    / "900x1600/ad/dabflow__ad__mat-ceramic__conc-distillate__heat-propane__timer1x__human080.json"
)


def _load_taps(path: Path, limit: int = 8) -> list[tuple[int, int, str]]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    steps = data if isinstance(data, list) else data.get("steps", [])
    out: list[tuple[int, int, str]] = []
    for s in steps:
        if s.get("type") != "tap":
            continue
        x, y = int(s["x"]), int(s["y"])
        out.append((x, y, f"seq_tap_{len(out)+1}"))
        if len(out) >= limit:
            break
    return out


def _region_points() -> list[tuple[int, int, str]]:
    g = nav_region("glass")
    return [
        (AGE_YES.cx, AGE_YES.cy, "AGE_YES"),
        (MAT_POS["ceramic"].cx, MAT_POS["ceramic"].cy, "MAT_ceramic"),
        (HEAT_POS["propane"].cx, HEAT_POS["propane"].cy, "HEAT_propane"),
        (START_DAB.cx, START_DAB.cy, "START_DAB"),
        (g.cx, g.cy, "NAV_glass"),
        (GLASS_ART_SELECT.cx, GLASS_ART_SELECT.cy, "GLASS_ART_SELECT"),
        (STATS_AD_SLOT.cx, STATS_AD_SLOT.cy, "STATS_AD_SLOT"),
    ]


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIP: playwright not installed")
        return 0

    url = "https://getdabflow.app"
    points = _region_points() + _load_taps(SEQ_AD)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 900, "height": 1600})
        try:
            resp = page.goto(url, wait_until="networkidle", timeout=90000)
            status = resp.status if resp else None
        except Exception as exc:
            print(f"FAIL: page load {url}: {exc}")
            browser.close()
            return 1

        page.wait_for_timeout(3000)
        age_btn = page.evaluate(
            """() => {
                const btn = document.querySelector('#age-yes-btn');
                if (!btn) return { present: false };
                const r = btn.getBoundingClientRect();
                return {
                    present: true,
                    cx: Math.round(r.x + r.width / 2),
                    cy: Math.round(r.y + r.height / 2),
                    w: Math.round(r.width),
                    h: Math.round(r.height),
                };
            }"""
        )
        age_ok = bool(age_btn.get("present"))
        if age_ok:
            ax, ay = int(age_btn["cx"]), int(age_btn["cy"])
            dx = abs(ax - AGE_YES.cx)
            dy = abs(ay - AGE_YES.cy)
            age_align = dx <= 60 and dy <= 60
            print(
                f"  [{'OK' if age_align else 'WARN'}] #age-yes-btn center=({ax},{ay}) "
                f"layout=({AGE_YES.cx},{AGE_YES.cy}) delta=({dx},{dy})"
            )
        else:
            age_align = False
            print("  [MISS] #age-yes-btn not found on load")

        ok_coords = 0
        for x, y, label in points:
            hit = page.evaluate(
                """([x, y]) => {
                    const el = document.elementFromPoint(x, y);
                    if (!el) return { tag: null, id: '' };
                    return { tag: el.tagName, id: el.id || '' };
                }""",
                [x, y],
            )
            interactive = hit.get("tag") not in (None, "HTML", "BODY")
            if label == "AGE_YES":
                interactive = hit.get("id") == "age-yes-btn"
            if interactive:
                ok_coords += 1
            extra = f" id={hit.get('id')}" if hit.get("id") else ""
            print(f"  [{'OK' if interactive else 'MISS'}] {label} ({x},{y}) -> {hit.get('tag')}{extra}")

        if age_ok:
            page.mouse.click(AGE_YES.cx, AGE_YES.cy)
            page.wait_for_timeout(1200)
            cleared = page.evaluate(
                """() => {
                    const gate = document.getElementById('age-gate');
                    const verified = localStorage.getItem('dabflow_age_verified') === 'true';
                    const hidden = gate && (gate.style.display === 'none' || window.getComputedStyle(gate).display === 'none');
                    return verified || hidden;
                }"""
            )
            print(f"  [{'OK' if cleared else 'FAIL'}] age gate cleared after tap @ ({AGE_YES.cx},{AGE_YES.cy})")
        else:
            cleared = False

        browser.close()

    ok_load = status == 200
    print(
        f"SUMMARY load={'PASS' if ok_load else 'FAIL'} coords={ok_coords}/{len(points)} "
        f"age_btn={'PASS' if age_ok and age_align else 'FAIL'} cleared={'PASS' if cleared else 'FAIL'}"
    )
    return 0 if ok_load and age_ok and age_align and cleared and ok_coords >= len(points) // 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
