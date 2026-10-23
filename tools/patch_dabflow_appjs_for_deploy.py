#!/usr/bin/env python3
"""Download live getdabflow.app/js/app.js, apply Mantis fixes, write dabflow-fix/app.js for deploy."""
from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "dabflow-fix"
APP_JS_URL = "https://getdabflow.app/js/app.js"

SCREEN_ZONE_FIX = """const screenZoneMap = {
    home:     ['zone-one', 'tester'],
    timer:    ['zone-two', 'zone-three', 'zone-four'],
    stats:    ['zone-five', 'zone-six', 'zone-seven'],
    glass:    ['zone-eight', 'zone-nine', 'zone-ten', 'zone-eleven'],
    settings: ['zone-twelve', 'zone-thirteen', 'zone-fourteen', 'zone-fifteen']
};"""

COOL_VIDEO_INJECT = """
                if (!state.settings.isPremium) {
                    const videoAd = document.getElementById('cooldown-video-ad');
                    if (videoAd) {
                        videoAd.style.display = 'block';
                        if (!videoAd.querySelector('[data-mantis-zone]')) {
                            videoAd.innerHTML = '<div data-mantis-zone="zone-two"></div>';
                        }
                        if (typeof mantis !== 'undefined') {
                            setTimeout(function() {
                                mantis.push(['display', 'refresh', 'zone-two']);
                            }, 300);
                        }
                    }
                    if (typeof mantis !== 'undefined') {
                        setTimeout(function() {
                            mantis.push(['display', 'refresh']);
                        }, 300);
                    }
                }
"""


def patch_app_js(source: str) -> tuple[str, list[str]]:
    notes: list[str] = []
    out = source

    m = re.search(r"const\s+screenZoneMap\s*=\s*\{[^}]+\};", out, re.S)
    if not m:
        raise SystemExit("screenZoneMap block not found in app.js")
    if "zone-four-" in m.group(0):
        out = out[: m.start()] + SCREEN_ZONE_FIX + out[m.end() :]
        notes.append("fixed screenZoneMap trailing-dash zone typos")
    else:
        notes.append("screenZoneMap already looks fixed")

    # Insert cooldown video show when heat → cool (after playSound('heatComplete'))
    needle = "playSound('heatComplete');"
    if needle in out and COOL_VIDEO_INJECT.strip() not in out:
        out = out.replace(
            needle,
            needle + COOL_VIDEO_INJECT,
            1,
        )
        notes.append("inject cooldown-video-ad display on cool phase")
    elif "cooldown-video-ad" in out and "videoAd.style.display = 'block'" in out:
        notes.append("cooldown video show already present")

    return out, notes


def main() -> int:
    req = urllib.request.Request(APP_JS_URL, headers={"User-Agent": "PharmFlow-patch/1"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        source = resp.read().decode("utf-8", errors="replace")

    patched, notes = patch_app_js(source)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "app.js").write_text(patched, encoding="utf-8")
    (OUT_DIR / "DEPLOY.txt").write_text(
        "\n".join(
            [
                "DabFlow Mantis fix — deploy to Cloudflare Pages",
                "================================================",
                "",
                "1. In your DabFlow repo (StudioProjects/DabFlow, branch web):",
                "   Replace www/js/app.js with this file (dabflow-fix/app.js).",
                "",
                "2. git commit && git push origin web",
                "",
                "3. Cloudflare Pages redeploys getdabflow.app automatically.",
                "",
                "4. Verify: python3 automation/audit_dabflow_live.py  → OK",
                "",
                "Patches applied:",
                *[f"  - {n}" for n in notes],
                "",
                "Until deployed, PharmFlow injects a runtime fix via CDP after each open_url",
                "(PHARMFLOW_DABFLOW_MANTIS_PATCH=1, default on).",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUT_DIR / 'app.js'} ({len(patched)} bytes)")
    for n in notes:
        print(f"  • {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
