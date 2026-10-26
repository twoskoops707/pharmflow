"""Path3 must not open a clicked URL that Mantis will accept and then pay $0 for."""
from __future__ import annotations

from urllib.parse import quote

from automation.dabflow_mantis_ad_urls import _zone_lookup_keys, has_live_click_token

_LIVE_BI = "6f1c2a90-4b3e-4d11-9c2a-1e8b7a0d44c1"
_LIVE_BT = "1712345678"
_GRASSCITY = (
    "https://www.grasscity.com/?utm_source=mantis"
    "&utm_medium=6950d5527c56c6494f189e46&utm_campaign=live-fill"
)


def _clicked(landing: str, *, bi: str = _LIVE_BI, bt: str | None = _LIVE_BT) -> str:
    url = (
        "https://bids.mantis.marketing/clicked?r="
        + quote(landing, safe="")
        + "&p=2&bi="
        + bi
    )
    if bt is not None:
        url += "&bt=" + bt
    return url


def test_rejects_clicked_url_missing_bt() -> None:
    missing_bt = _clicked(_GRASSCITY, bt=None)
    empty_bt = _clicked(_GRASSCITY, bt="")
    assert "bt=" not in missing_bt
    assert has_live_click_token(missing_bt) is False
    assert has_live_click_token(empty_bt) is False


def test_rejects_synthetic_bi_even_with_bt() -> None:
    for bi in ("pharmflow-fallback", "mantis-hardcode", "mantis-bot"):
        assert has_live_click_token(_clicked(_GRASSCITY, bi=bi)) is False


def test_accepts_uuid_bi_digit_bt_and_advertiser_landing() -> None:
    live = _clicked(_GRASSCITY)
    assert f"bi={_LIVE_BI}" in live
    assert f"bt={_LIVE_BT}" in live
    assert "grasscity.com" in live
    assert has_live_click_token(live) is True


def test_rejects_house_bot_and_non_clicked() -> None:
    house = _clicked("https://www.mantisadnetwork.com/?utm_source=mantis-bot")
    bot_skin = _clicked("https://www.weedmaps.com/?utm_source=mantis-bot")
    landing_only = _GRASSCITY
    assert has_live_click_token(house) is False
    assert has_live_click_token(bot_skin) is False
    assert has_live_click_token(landing_only) is False
    assert has_live_click_token("") is False


def test_click_url_for_zone_does_not_open_stale_cache(monkeypatch) -> None:
    """Prefetch's allow_stale return must not replace the phone's live token."""
    from automation import dabflow_mantis_client_patch as ssp

    stale = _clicked("https://www.weedmaps.com/?utm_source=mantis")
    fallback = _clicked("https://www.grasscity.com/?utm_source=mantis", bi="pharmflow-fallback", bt=None)

    def fake_cached(*, allow_stale: bool = True):
        if allow_stale:
            return [{"zone_id": "zone-one", "click_url": stale}]
        return []

    monkeypatch.setattr(ssp, "get_cached_ssp_ads", fake_cached)
    monkeypatch.setattr(ssp, "prefetch_ssp_ads", lambda **k: [{"zone_id": "zone-one", "click_url": stale}])
    monkeypatch.setattr(
        ssp,
        "prefetch_ssp_ads_prefer_paying",
        lambda **k: [{"zone_id": "zone-one", "click_url": stale}],
    )
    monkeypatch.setattr(ssp, "paying_fill_file_fresh", lambda: False)
    monkeypatch.setattr(
        ssp,
        "_ingest_paying_fill_file",
        lambda **k: [{"zone_id": "zone-one", "click_url": fallback}],
    )
    monkeypatch.setattr(ssp, "ssp_recently_house_only", lambda: False)
    monkeypatch.setattr(ssp, "_mark_ssp_house_only", lambda: None)
    monkeypatch.setattr(ssp, "_clear_ssp_house_only", lambda: None)

    assert ssp.click_url_for_zone("zone-one", prefer_paying=True, force_refresh=True) is None


def test_resolve_path3_rejects_missing_bt_and_fallback_bi(monkeypatch) -> None:
    from automation import sequence_runner as sr

    missing_bt = _clicked(_GRASSCITY, bt=None)
    fallback = _clicked(_GRASSCITY, bi="pharmflow-fallback")
    monkeypatch.setattr(sr, "click_url_for_zone", lambda *a, **k: missing_bt)
    monkeypatch.setattr(sr, "prefetch_ssp_ads_prefer_paying", lambda **k: [])
    monkeypatch.setattr(sr, "paying_fill_file_fresh", lambda: False)
    assert sr.resolve_path3_paying_click_url("zone-one", missing_bt) == ""
    assert sr.resolve_path3_click_url("zone-one", fallback) == ""
    monkeypatch.setenv("PHARMFLOW_PATH3_REQUIRE_PAYING", "0")
    assert sr.resolve_path3_click_url("zone-one", fallback) == ""


def test_resolve_path3_skips_stale_fill_file(monkeypatch) -> None:
    from automation import sequence_runner as sr

    live = _clicked(_GRASSCITY)
    monkeypatch.setattr(sr, "click_url_for_zone", lambda *a, **k: "")
    monkeypatch.setattr(sr, "prefetch_ssp_ads_prefer_paying", lambda **k: [])
    monkeypatch.setattr(sr, "paying_fill_file_fresh", lambda: False)
    monkeypatch.setattr(
        sr,
        "_ingest_paying_fill_file",
        lambda **k: [{"zone_id": "zone-one", "click_url": live}],
    )
    assert sr.resolve_path3_paying_click_url("zone-one", "") == ""
    monkeypatch.setattr(sr, "paying_fill_file_fresh", lambda: True)
    assert sr.resolve_path3_paying_click_url("zone-one", "") == live


def test_phone_zero_viewed_click_is_used(tmp_path, monkeypatch) -> None:
    """vm0 is index 0. A stored phone-fetched URL must still be readable."""
    from automation import dabflow_mantis_ad_urls as urls

    live = _clicked(_GRASSCITY)
    path = tmp_path / "phone_viewed_clicks.json"
    monkeypatch.setattr(urls, "_VIEWED_CLICKS_PATH", path)
    stored = urls.record_phone_viewed_ads(0, [{"zone_id": "zone-one", "click_url": live}])
    assert stored == 1
    assert urls.phone_viewed_click_url(0, "zone-one") == live
    runner = (tmp_path / "unused")
    del runner
    src = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "automation"
        / "sequence_runner.py"
    ).read_text(encoding="utf-8")
    block = src.split("Open only the click URL the phone itself fetched.", 1)[1].split(
        "prefer_ok = bool(prefer_click)", 1
    )[0]
    assert "int(phone_idx) > 0" not in block
    assert "phone_viewed_click_url(viewed_idx, zone)" in block


def test_zone_lookup_accepts_trailing_hyphen() -> None:
    assert _zone_lookup_keys("zone-twelve") == ("zone-twelve", "zone-twelve-")
    assert _zone_lookup_keys("zone-twelve-") == ("zone-twelve-", "zone-twelve")
    assert _zone_lookup_keys("") == ()
