"""Mantis ad zones, checkpoints, live SSP fetch, and fallback landing URLs for DabFlow."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

MANTIS_PROPERTY_ID = "6950d5527c56c6494f189e46"
MANTIS_SSP_DISPLAY = "https://ssp.mantis.marketing/display"
DABFLOW_PAGE_URL = "https://getdabflow.app/"

TAB_TO_ZONE: dict[str, str] = {
    "timer": "zone-two",
    "stats": "zone-five",
    "glass_art": "zone-nine",
    "settings": "zone-twelve",
    "home": "zone-one",
    "post_timer": "zone-three",
}

# All active mobile zones (primary + siblings) for human Path3 rotation.
TAB_ZONES: dict[str, tuple[str, ...]] = {
    "home": ("zone-one", "tester"),
    "timer": ("zone-two", "zone-three", "zone-four"),
    "stats": ("zone-five", "zone-six", "zone-seven"),
    "glass_art": ("zone-eight", "zone-nine", "zone-ten", "zone-eleven"),
    "settings": ("zone-twelve", "zone-thirteen", "zone-fourteen", "zone-fifteen"),
}

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

FALLBACK_LANDING_URLS: dict[str, str] = {
    "zone-one": (
        "https://www.grasscity.com/"
        "?utm_source=mantis&utm_medium=6950d5527c56c6494f189e46&utm_campaign=pharmflow-fallback"
    ),
    "zone-two": (
        "https://www.smokecartel.com/"
        "?utm_source=mantis&utm_medium=6950d5527c56c6494f189e46&utm_campaign=pharmflow-fallback"
    ),
    "zone-three": (
        "https://www.smokecartel.com/"
        "?utm_source=mantis&utm_medium=6950d5527c56c6494f189e46&utm_campaign=pharmflow-fallback"
    ),
    "zone-five": (
        "https://ageofhemp.com/collections/best-deals"
        "?utm_source=mantis&utm_medium=6950d5527c56c6494f189e46&utm_campaign=pharmflow-fallback"
    ),
    "zone-eight": (
        "https://ageofhemp.com/collections/best-deals"
        "?utm_source=mantis&utm_medium=6950d5527c56c6494f189e46&utm_campaign=pharmflow-fallback"
    ),
    "zone-nine": (
        "https://ageofhemp.com/collections/best-deals"
        "?utm_source=mantis&utm_medium=6950d5527c56c6494f189e46&utm_campaign=pharmflow-fallback"
    ),
    "zone-twelve": (
        "https://www.grasscity.com/"
        "?utm_source=mantis&utm_medium=6950d5527c56c6494f189e46&utm_campaign=pharmflow-fallback"
    ),
}


def decode_click_landing(click_url: str) -> str:
    """Extract advertiser landing URL from a Mantis ``click_url`` (``r=`` query param)."""
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(click_url).query)
    raw = qs.get("r", [""])[0]
    return urllib.parse.unquote(raw) if raw else ""


def has_live_click_token(click_url: str) -> bool:
    """True only for a token-bound paying click (bi+bt), never a synthetic wrap.

    A clicked URL without the fill's bi/bt returns HTTP 200 and pays $0.
    """
    raw = (click_url or "").strip()
    if "bids.mantis.marketing/clicked" not in raw.lower():
        return False
    if is_mantis_house_bot_click_url(raw):
        return False
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query)
    bi = (qs.get("bi") or [""])[0].strip().lower()
    bt = (qs.get("bt") or [""])[0].strip()
    if not bi or not bt:
        return False
    if bi in ("pharmflow-fallback", "cpharm-fallback", "mantis-hardcode", "mantis-bot"):
        return False
    return True


def _viewed_clicks_paths() -> list[Path]:
    """Live CPharm first, branded PharmFlow second (dual-read / dual-write)."""
    out: list[Path] = []
    seen: set[str] = set()
    for raw in (
        r"C:\CPharm\logs\phone_viewed_clicks.json",
        r"C:\PharmFlow\logs\phone_viewed_clicks.json",
    ):
        key = str(Path(raw)).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(Path(raw))
    return out


_VIEWED_CLICKS_PATH = _viewed_clicks_paths()[0]
# Same sequence can scroll for several minutes after the page paints.
# 300s expired the token before Path3's tap, so the open was skipped.
_VIEWED_CLICK_TTL_S = 900.0
_viewed_lock = threading.Lock()


def record_phone_viewed_ads(phone_index: int, ads: list) -> int:
    """Store click URLs the phone itself fetched. Host SSP tokens do not match."""
    now = time.time()
    key = str(int(phone_index))
    with _viewed_lock:
        data: dict = {}
        for path in _viewed_clicks_paths():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and raw:
                    data = raw
                    break
            except (OSError, json.JSONDecodeError, TypeError):
                continue
        bucket = dict(data.get(key) or {})
        stored = 0
        for ad in ads or []:
            if not isinstance(ad, dict):
                continue
            zone = str(ad.get("zone_id") or "").strip()
            url = str(ad.get("click_url") or "").strip()
            if not zone or not has_live_click_token(url):
                continue
            bucket[zone] = {"url": url, "ts": now}
            stored += 1
        data[key] = bucket
        text = json.dumps(data)
        for path in _viewed_clicks_paths():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".json.tmp")
                tmp.write_text(text, encoding="utf-8")
                tmp.replace(path)
            except OSError:
                continue
    return stored


def _zone_lookup_keys(zone: str) -> tuple[str, ...]:
    """SSP zone ids arrive with and without a trailing hyphen.

    The page stores ``zone-twelve-``. Path3 asks for ``zone-twelve``.
    An exact match misses the click the phone just fetched.
    """
    want = str(zone or "").strip()
    if not want:
        return ()
    alt = want[:-1] if want.endswith("-") else want + "-"
    if alt == want:
        return (want,)
    return (want, alt)


def phone_viewed_click_url(
    phone_index: int,
    zone: str,
    *,
    max_age_s: float = _VIEWED_CLICK_TTL_S,
) -> str:
    """Click URL from this phone's own fill, or empty if missing/stale."""
    keys = _zone_lookup_keys(zone)
    if not keys:
        return ""
    for path in _viewed_clicks_paths():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        bucket = data.get(str(int(phone_index))) or {}
        if not isinstance(bucket, dict):
            continue
        for want in keys:
            row = bucket.get(want) or {}
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "").strip()
            try:
                ts = float(row.get("ts") or 0)
            except (TypeError, ValueError):
                ts = 0.0
            if not url or (time.time() - ts) > float(max_age_s):
                continue
            if not has_live_click_token(url):
                continue
            return url
    return ""


def is_mantis_house_bot_click_url(click_url: str) -> bool:
    """True for SSP house/bot creatives that open but do not move publisher $/clicks.

    Live ``bids.mantis.marketing/clicked`` URLs with house landings still look like
    tracking redirects to the farm, but GraphQL payout/clicks stay flat:

    - ``r=`` → mantisadnetwork.com (any utm)
    - ``utm_source=mantis-bot`` on *any* host (incl. advertiser skins like grasscity)

    Paying fills use real advertiser landings with ``utm_source=mantis`` (not
    ``mantis-bot``). Check both the raw click URL and the decoded ``r=`` landing
    (including percent-encoded forms).
    """
    u = (click_url or "").strip().lower()
    if not u.startswith("http"):
        return False
    land = decode_click_landing(click_url).lower()
    blob = f"{u}\n{land}"
    # Tick 484: grasscity.com?utm_source=mantis-bot was logged billable; $/clk flat.
    if "utm_source=mantis-bot" in blob or "utm_source%3dmantis-bot" in blob:
        return True
    if land and "mantisadnetwork.com" in land:
        return True
    if not land and "mantisadnetwork.com" in u:
        return True
    return False


def tag_landing_with_publisher(
    url: str,
    property_id: str = MANTIS_PROPERTY_ID,
) -> str:
    """Ensure Mantis publisher id is in the ad landing link as ``utm_medium``."""
    if not (url or "").strip():
        return url
    parsed = urllib.parse.urlparse(url.strip())
    qd = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    campaign = qd.get("utm_campaign", "")
    content = qd.get("utm_content", "")
    weak_campaigns = frozenset(
        {"", "mantis-bot", "Banner", "Top Sellers", "Top+Sellers", "mantis-hardcode", "pharmflow-fallback"}
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


def wrap_paying_click_url(landing: str, *, bid_id: str = "pharmflow-fallback") -> str:
    """Build a ``bids.mantis.marketing/clicked`` URL around a publisher-tagged landing.

    Slot taps alone do not bill; opening this tracking redirect is the Jul 30 path.
    Never wraps house/bot landings (returns empty).
    """
    land = tag_landing_with_publisher((landing or "").strip())
    if not land.startswith("http"):
        return ""
    probe = f"https://bids.mantis.marketing/clicked?r={urllib.parse.quote(land, safe='')}"
    if is_mantis_house_bot_click_url(probe):
        return ""
    return (
        "https://bids.mantis.marketing/clicked?r="
        + urllib.parse.quote(land, safe="")
        + f"&p=2&bi={bid_id}"
    )


def tag_click_url_with_publisher(click_url: str) -> str:
    """Rewrite ``r=`` landing on a live clicked URL with utm_source=mantis + publisher."""
    raw = (click_url or "").strip()
    if not raw.startswith("http"):
        return ""
    if "bids.mantis.marketing/clicked" not in raw.lower():
        return ""
    land = decode_click_landing(raw)
    if not land:
        return raw
    tagged = tag_landing_with_publisher(land)
    if is_mantis_house_bot_click_url(
        f"https://bids.mantis.marketing/clicked?r={urllib.parse.quote(tagged, safe='')}"
    ):
        return ""
    parsed = urllib.parse.urlparse(raw)
    qd = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    qd["r"] = tagged
    new_query = urllib.parse.urlencode(qd, quote_via=urllib.parse.quote)
    return urllib.parse.urlunparse(parsed._replace(query=new_query))


def paying_fallback_click_url(zone: str = "", checkpoint: str = "") -> str:
    """Paying clicked URL from hardcode/fallback landings (never house/bot)."""
    land = ""
    z = (zone or "").strip()
    if z:
        land = FALLBACK_LANDING_URLS.get(z) or ""
    if not land and checkpoint:
        land = fallback_landing_for_checkpoint(checkpoint) or ""
    if not land:
        land = FALLBACK_LANDING_URLS.get("zone-one") or ""
    return wrap_paying_click_url(land)


def fetch_mantis_landing_urls(
    zones: tuple[str, ...] | list[str] | None = None,
    *,
    timeout: float = 20.0,
) -> dict[str, str]:
    """Query Mantis SSP for current ads; return ``zone_id -> landing URL``."""
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
            "User-Agent": "PharmFlow-mantis-hardcode/1.0 (Linux; Android 13) Mobile",
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


def fallback_url_for_tab(tab: str) -> str | None:
    zone = TAB_TO_ZONE.get(tab.replace("-", "_"))
    if not zone:
        return None
    return FALLBACK_LANDING_URLS.get(zone)


def fallback_url_for_zone(zone: str) -> str | None:
    return FALLBACK_LANDING_URLS.get(zone)


def ad_checkpoint_to_zone(checkpoint: str) -> str | None:
    cp = (checkpoint or "").strip().lower()
    for zone, ad_cp in ZONE_TO_AD_CHECKPOINT.items():
        if ad_cp == cp:
            return zone
    return None


def fallback_landing_for_checkpoint(checkpoint: str) -> str | None:
    zone = ad_checkpoint_to_zone(checkpoint)
    if not zone:
        return None
    return FALLBACK_LANDING_URLS.get(zone)
