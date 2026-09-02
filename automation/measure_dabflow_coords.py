#!/usr/bin/env python3
"""Measure DabFlow interactive element centers at 900x1600 from live site."""
from __future__ import annotations

import json
import sys

SELECTORS = [
    ("AGE_YES", "#age-yes-btn"),
    ("AGE_NO", "#age-no-btn"),
    ("MAT_quartz", '[data-setting="material"][data-value="quartz"]'),
    ("MAT_titanium", '[data-setting="material"][data-value="titanium"]'),
    ("MAT_ceramic", '[data-setting="material"][data-value="ceramic"]'),
    ("CONC_shatter", '[data-setting="concentrate"][data-value="shatter"]'),
    ("CONC_wax", '[data-setting="concentrate"][data-value="wax"]'),
    ("CONC_live-resin", '[data-setting="concentrate"][data-value="live-resin"]'),
    ("CONC_rosin", '[data-setting="concentrate"][data-value="rosin"]'),
    ("CONC_diamonds", '[data-setting="concentrate"][data-value="diamonds"]'),
    ("CONC_crumble", '[data-setting="concentrate"][data-value="crumble"]'),
    ("CONC_budder", '[data-setting="concentrate"][data-value="budder"]'),
    ("CONC_sauce", '[data-setting="concentrate"][data-value="sauce"]'),
    ("CONC_hash-rosin", '[data-setting="concentrate"][data-value="hash-rosin"]'),
    ("CONC_distillate", '[data-setting="concentrate"][data-value="distillate"]'),
    ("HEAT_butane", '[data-setting="heater"][data-value="butane"]'),
    ("HEAT_propane", '[data-setting="heater"][data-value="propane"]'),
    ("START_DAB", "#start-dab-btn"),
    ("PAUSE_BTN", "#pause-btn"),
    ("RESET_BTN", "#reset-btn"),
    ("NAV_home", '[data-screen="home"].nav-item'),
    ("NAV_timer", '[data-screen="timer"].nav-item'),
    ("NAV_stats", '[data-screen="stats"].nav-item'),
    ("NAV_glass", '[data-screen="glass"].nav-item'),
    ("NAV_settings", '[data-screen="settings"].nav-item'),
    ("HOME_AD", "#home-screen .ad-container.banner"),
    ("STATS_AD", "#stats-screen .ad-container.banner"),
    ("SESSION_NOTES_SKIP", '#session-notes-modal button[onclick="skipSessionNotes()"]'),
]


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 1

    url = "https://getdabflow.app"
    results: dict[str, dict] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 900, "height": 1600})
        page.goto(url, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(2000)

        for name, sel in SELECTORS:
            info = page.evaluate(
                """(sel) => {
                    const el = document.querySelector(sel);
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    return {
                        x: Math.round(r.x), y: Math.round(r.y),
                        w: Math.round(r.width), h: Math.round(r.height),
                        cx: Math.round(r.x + r.width / 2),
                        cy: Math.round(r.y + r.height / 2),
                        visible: r.width > 0 && r.height > 0,
                    };
                }""",
                sel,
            )
            results[name] = info

        # Age yes/no left-right verification
        yes = results.get("AGE_YES")
        no = results.get("AGE_NO")
        if yes and no:
            print(f"AGE YES cx={yes['cx']} (left={yes['x']})  NO cx={no['cx']} (left={no['x']})")
            print(f"  YES is LEFT of NO: {yes['cx'] < no['cx']}")

        # Click age yes, then measure timer/glass elements
        if yes:
            page.mouse.click(yes["cx"], yes["cy"])
            page.wait_for_timeout(1500)

        for name, sel in SELECTORS:
            if name.startswith("NAV_") or name in ("PAUSE_BTN", "RESET_BTN", "STATS_AD", "GLASS_ART"):
                pass
        # Re-measure home elements after age gate
        for name, sel in SELECTORS:
            if name.startswith("AGE_"):
                continue
            info = page.evaluate(
                """(sel) => {
                    const el = document.querySelector(sel);
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    return {
                        x: Math.round(r.x), y: Math.round(r.y),
                        w: Math.round(r.width), h: Math.round(r.height),
                        cx: Math.round(r.x + r.width / 2),
                        cy: Math.round(r.y + r.height / 2),
                        visible: r.width > 0 && r.height > 0,
                    };
                }""",
                sel,
            )
            if info:
                results[name] = info

        # Session notes Skip (modal must be visible)
        skip_info = page.evaluate(
            """() => {
                const modal = document.getElementById('session-notes-modal');
                if (!modal) return null;
                modal.style.display = 'block';
                const btn = modal.querySelector('button[onclick="skipSessionNotes()"]');
                if (!btn) return null;
                const r = btn.getBoundingClientRect();
                return {
                    x: Math.round(r.x), y: Math.round(r.y),
                    w: Math.round(r.width), h: Math.round(r.height),
                    cx: Math.round(r.x + r.width / 2),
                    cy: Math.round(r.y + r.height / 2),
                };
            }"""
        )
        if skip_info:
            results["SESSION_NOTES_SKIP"] = skip_info

        # Navigate to stats for ad slot
        stats = results.get("NAV_stats")
        if stats:
            page.mouse.click(stats["cx"], stats["cy"])
            page.wait_for_timeout(800)
            info = page.evaluate(
                """() => {
                    const el = document.querySelector('#stats-screen .ad-container.banner');
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    return {
                        x: Math.round(r.x), y: Math.round(r.y),
                        w: Math.round(r.width), h: Math.round(r.height),
                        cx: Math.round(r.x + r.width / 2),
                        cy: Math.round(r.y + r.height / 2),
                    };
                }"""
            )
            results["STATS_AD"] = info

        # Navigate to glass for first art card
        glass_nav = results.get("NAV_glass")
        if glass_nav:
            page.mouse.click(glass_nav["cx"], glass_nav["cy"])
            page.wait_for_timeout(800)
            info = page.evaluate(
                """() => {
                    const screen = document.getElementById('glass-screen');
                    if (!screen) return null;
                    const link = screen.querySelector('a[href*="instagram"], a[href*="mobius"]');
                    if (!link) {
                        const any = screen.querySelector('a[target="_blank"]');
                        if (!any) return null;
                        const r = any.getBoundingClientRect();
                        return {
                            x: Math.round(r.x), y: Math.round(r.y),
                            w: Math.round(r.width), h: Math.round(r.height),
                            cx: Math.round(r.x + r.width / 2),
                            cy: Math.round(r.y + r.height / 2),
                            selector: any.getAttribute('href') || '',
                        };
                    }
                    const r = link.getBoundingClientRect();
                    return {
                        x: Math.round(r.x), y: Math.round(r.y),
                        w: Math.round(r.width), h: Math.round(r.height),
                        cx: Math.round(r.x + r.width / 2),
                        cy: Math.round(r.y + r.height / 2),
                        selector: link.getAttribute('href') || '',
                    };
                }"""
            )
            results["GLASS_ART_SELECT"] = info

        # Timer screen controls
        timer_nav = results.get("NAV_timer")
        if timer_nav:
            page.mouse.click(results["NAV_home"]["cx"], results["NAV_home"]["cy"])
            page.wait_for_timeout(500)
            start = results.get("START_DAB")
            if start:
                page.mouse.click(start["cx"], start["cy"])
                page.wait_for_timeout(1000)
                for name, sel in [("PAUSE_BTN", "#pause-btn"), ("RESET_BTN", "#reset-btn")]:
                    info = page.evaluate(
                        """(sel) => {
                            const el = document.querySelector(sel);
                            if (!el) return null;
                            const r = el.getBoundingClientRect();
                            return {
                                cx: Math.round(r.x + r.width / 2),
                                cy: Math.round(r.y + r.height / 2),
                                w: Math.round(r.width), h: Math.round(r.height),
                            };
                        }""",
                        sel,
                    )
                    if info:
                        results[name] = info

        browser.close()

    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
