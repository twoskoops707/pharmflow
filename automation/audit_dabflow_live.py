#!/usr/bin/env python3
"""Audit live getdabflow.app Mantis ad wiring vs CPharm expectations.

Fetches public assets (JS + HTML shell). Does not bypass Cloudflare browser challenges on `/`.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request

BASE = "https://getdabflow.app"
TIMEOUT = 45


def _fetch(url: str) -> tuple[int | None, str, dict[str, str]]:
    req = urllib.request.Request(url, headers={"User-Agent": "CPharm-audit/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, resp.read().decode("utf-8", errors="replace"), headers
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return e.code, body, {k.lower(): v for k, v in e.headers.items()}
    except Exception as e:
        return None, str(e), {}


def _extract_screen_zone_map(app_js: str) -> dict[str, list[str]]:
    m = re.search(r"const\s+screenZoneMap\s*=\s*\{([^}]+)\}", app_js, re.S)
    if not m:
        return {}
    block = m.group(1)
    out: dict[str, list[str]] = {}
    for line in block.splitlines():
        mm = re.match(r"\s*(\w+)\s*:\s*\[(.*?)\]", line)
        if not mm:
            continue
        zones = [z.strip().strip("'\"") for z in mm.group(2).split(",") if z.strip()]
        out[mm.group(1)] = zones
    return out


def _html_mantis_zones(html: str) -> set[str]:
    return set(re.findall(r'data-mantis-zone="([^"]+)"', html))


def audit() -> dict:
    issues: list[str] = []
    info: dict[str, object] = {}

    st_root, body_root, hdr_root = _fetch(f"{BASE}/")
    info["root_status"] = st_root
    info["cloudflare"] = hdr_root.get("server", "").lower() == "cloudflare"
    if st_root == 403 and "cf-mitigated" in hdr_root:
        info["root_note"] = "Cloudflare managed challenge on / (expected for bots; real browsers pass)"

    st_js, app_js, hdr_js = _fetch(f"{BASE}/js/app.js")
    info["app_js_status"] = st_js
    info["app_js_bytes"] = len(app_js.encode()) if st_js == 200 else 0
    info["app_js_last_modified"] = hdr_js.get("last-modified", "")

    st_html, html, hdr_html = _fetch(f"{BASE}/css/app.css")
    info["html_shell_status"] = st_html
    info["html_shell_bytes"] = len(html.encode()) if st_html == 200 else 0
    info["html_shell_content_type"] = hdr_html.get("content-type", "")
    info["html_shell_last_modified"] = hdr_html.get("last-modified", "")

    if st_js != 200:
        issues.append(f"cannot fetch /js/app.js (HTTP {st_js})")
        return {"ok": False, "issues": issues, "info": info}

    if "mantodea.min.js" not in html and "mantodea.min.js" not in app_js:
        issues.append("Mantis mantodea.min.js not referenced in HTML shell")
    else:
        info["mantis_loader"] = True

    prop = re.search(r"property:\s*'([a-f0-9]{24})'", html)
    if prop:
        info["mantis_property"] = prop.group(1)
    else:
        issues.append("Mantis property id not found in HTML shell")

    html_zones = _html_mantis_zones(html)
    info["html_zone_count"] = len(html_zones)
    info["html_zones"] = sorted(html_zones)

    zone_map = _extract_screen_zone_map(app_js)
    info["screen_zone_map"] = zone_map

    refresh_zones = {z for zones in zone_map.values() for z in zones if z != "tester"}
    missing_in_html = sorted(z for z in refresh_zones if z not in html_zones)
    if missing_in_html:
        issues.append(
            "screenZoneMap refresh names not in HTML data-mantis-zone: "
            + ", ".join(missing_in_html)
        )

    if "cooldown-video-ad" in html:
        info["cooldown_video_slot_present"] = True
        shows_cooldown = bool(
            re.search(
                r"getElementById\(['\"]cooldown-video-ad['\"]\)[^;]*display\s*=\s*['\"]block['\"]",
                app_js,
            )
        )
        info["cooldown_video_shown_in_js"] = shows_cooldown
        if not shows_cooldown:
            issues.append(
                "#cooldown-video-ad exists in HTML but app.js never sets it display:block during cool phase"
            )
    else:
        issues.append("#cooldown-video-ad missing from deployed HTML")

    if st_html == 200 and "text/html" in info["html_shell_content_type"]:
        if html.lstrip().startswith("<!DOCTYPE") and "DabFlow" in html:
            info["html_shell_is_index"] = True
            if "css/app.css" in html:
                issues.append("HTML shell references css/app.css — verify that path is CSS not duplicate index")

    ad_slots = len(re.findall(r'id="ad-slot-\d+"', html))
    info["ad_slot_count"] = ad_slots
    if ad_slots < 15:
        issues.append(f"expected 15 ad-slot-* containers, found {ad_slots}")

    return {"ok": not issues, "issues": issues, "info": info}


def main() -> int:
    result = audit()
    print(json.dumps(result, indent=2))
    if result["ok"]:
        print("OK: live DabFlow Mantis wiring looks consistent")
        return 0
    print("FAILED:")
    for issue in result["issues"]:
        print(f"  - {issue}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
