"""
Live Mantis ad landing URLs for DabFlow (property 6950d5527c56c6494f189e46).

Used by mantis-hardcode test sequences: ``open_url`` to the advertiser destination
instead of tapping a Mantis zone on getdabflow.app.

Fetch at generation time via the public Mantis SSP ``/display`` endpoint (same contract
as ``mantodea.min.js``). Falls back to cached landing URLs when the network is down.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

MANTIS_PROPERTY_ID = "6950d5527c56c6494f189e46"
MANTIS_SSP_DISPLAY = "https://ssp.mantis.marketing/display"
DABFLOW_PAGE_URL = "https://getdabflow.app/"

# Post-timer tab zones used in combo ad paths (see dabflow_layout TAB_MATRIX_SPECS).
POST_TIMER_ZONES = ("zone-five", "zone-eight", "zone-nine", "zone-twelve")

ZONE_TO_AD_CHECKPOINT: dict[str, str] = {
    "zone-five": "ad_stats",
    "zone-six": "ad_stats",
    "zone-seven": "ad_stats",
    "zone-eight": "ad_glass",
    "zone-nine": "ad_glass",
    "zone-ten": "ad_glass",
    "zone-eleven": "ad_glass",
    "zone-twelve": "ad_settings",
    "zone-thirteen": "ad_settings",
    "zone-fourteen": "ad_settings",
    "zone-fifteen": "ad_settings",
    "zone-one": "ad_home",
    "zone-two": "ad_timer_banner",
    "zone-three": "ad_timer_banner",
}

# Cached from live SSP fetch 2026-07-05 — used when fetch fails (utm_medium = publisher property id).
FALLBACK_LANDING_URLS: dict[str, str] = {
    "zone-five": (
        "https://ageofhemp.com/collections/best-deals"
        "?utm_source=mantis&utm_medium=6950d5527c56c6494f189e46&utm_campaign=mantis-hardcode"
    ),
    "zone-eight": (
        "https://ageofhemp.com/collections/best-deals"
        "?utm_source=mantis&utm_medium=6950d5527c56c6494f189e46&utm_campaign=mantis-hardcode"
    ),
    "zone-nine": (
        "https://ageofhemp.com/collections/best-deals"
        "?utm_source=mantis&utm_medium=6950d5527c56c6494f189e46&utm_campaign=mantis-hardcode"
    ),
    "zone-twelve": (
        "https://www.grasscity.com/"
        "?utm_source=mantis&utm_medium=6950d5527c56c6494f189e46&utm_campaign=mantis-hardcode"
    ),
    "zone-one": (
        "https://www.grasscity.com/"
        "?utm_source=mantis&utm_medium=6950d5527c56c6494f189e46&utm_campaign=mantis-hardcode"
    ),
    "zone-two": (
        "https://www.smokecartel.com/"
        "?utm_source=mantis&utm_medium=6950d5527c56c6494f189e46&utm_campaign=mantis-hardcode"
    ),
    "zone-three": (
        "https://www.mantisadnetwork.com/"
        "?utm_source=mantis&utm_medium=6950d5527c56c6494f189e46&utm_campaign=mantis-hardcode"
    ),
}

# Five distinct test rows: combo + tab that receives hardcoded open_url.
HARDOCODE_TEST_SPECS: tuple[tuple[str, str, str, str, str], ...] = (
    ("ceramic", "distillate", "butane", "stats", "zone-five"),
    ("quartz", "shatter", "propane", "glass", "zone-nine"),
    ("titanium", "live-resin", "butane", "stats", "zone-one"),
    ("ceramic", "rosin", "propane", "glass", "zone-two"),
    ("quartz", "wax", "butane", "settings", "zone-three"),
)


def decode_click_landing(click_url: str) -> str:
    """Extract advertiser landing URL from a Mantis ``click_url`` (``r=`` query param)."""
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(click_url).query)
    raw = qs.get("r", [""])[0]
    return urllib.parse.unquote(raw) if raw else ""


def tag_landing_with_publisher(
    url: str,
    property_id: str = MANTIS_PROPERTY_ID,
) -> str:
    """
    Ensure Mantis publisher (property) id is in the ad landing link as ``utm_medium``.

    Live SSP ``click_url`` payloads often include campaign/content ids; this keeps those
    when present and always sets ``utm_source=mantis`` + ``utm_medium=<property_id>``.
    """
    if not (url or "").strip():
        return url
    parsed = urllib.parse.urlparse(url.strip())
    qd = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    campaign = qd.get("utm_campaign", "")
    content = qd.get("utm_content", "")
    weak_campaigns = frozenset(
        {"", "mantis-bot", "Banner", "Top Sellers", "Top+Sellers", "mantis-hardcode"}
    )
    qd["utm_source"] = "mantis"
    qd["utm_medium"] = property_id
    if campaign and campaign not in weak_campaigns:
        qd["utm_campaign"] = campaign
    else:
        qd["utm_campaign"] = "mantis-hardcode"
    if content:
        qd["utm_content"] = content
    elif "utm_content" in qd:
        del qd["utm_content"]
    new_query = urllib.parse.urlencode(qd, quote_via=urllib.parse.quote)
    return urllib.parse.urlunparse(parsed._replace(query=new_query))


def fetch_mantis_landing_urls(
    zones: tuple[str, ...] | list[str] | None = None,
    *,
    timeout: float = 20.0,
) -> dict[str, str]:
    """
    Query Mantis SSP for current ads; return ``zone_id -> landing URL`` (decoded from click_url).
    """
    want = list(zones or POST_TIMER_ZONES)
    body: dict[str, Any] = {
        "url": DABFLOW_PAGE_URL,
        "is_iframe": False,
        "demo": False,
        "last_viewed": {},
        "property_id": MANTIS_PROPERTY_ID,
        "zones": want,
        "widths": {z: 300 for z in want},
        "timezone": 0,
    }
    req = urllib.request.Request(
        MANTIS_SSP_DISPLAY,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "text/plain",
            "User-Agent": "CPharm-mantis-hardcode/1.0 (Linux; Android 13) Mobile",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    out: dict[str, str] = {}
    for ad in data.get("ads") or []:
        zone = str(ad.get("zone_id") or "").strip()
        click = str(ad.get("click_url") or "").strip()
        if not zone or not click:
            continue
        landing = decode_click_landing(click)
        if landing:
            out[zone] = tag_landing_with_publisher(landing)
    return out


def resolve_hardcode_ad_urls(
    zones: tuple[str, ...] | list[str] | None = None,
    *,
    prefer_live: bool = True,
) -> dict[str, str]:
    """Merge live SSP results with ``FALLBACK_LANDING_URLS`` for requested zones."""
    want = list(zones or POST_TIMER_ZONES)
    merged = dict(FALLBACK_LANDING_URLS)
    if prefer_live:
        try:
            live = fetch_mantis_landing_urls(want)
            merged.update(live)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
            pass
    return {z: tag_landing_with_publisher(merged[z]) for z in want if z in merged}


def ad_checkpoint_for_zone(zone: str) -> str:
    return ZONE_TO_AD_CHECKPOINT.get(zone, "ad_hardcode_open")


def landing_for_zone(zone: str, *, prefer_live: bool = True) -> str:
    urls = resolve_hardcode_ad_urls([zone], prefer_live=prefer_live)
    if zone not in urls:
        raise KeyError(f"no landing URL for Mantis zone {zone!r}")
    return urls[zone]
