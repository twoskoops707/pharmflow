"""Host paint must not replace a native Mantis fill."""

from __future__ import annotations

from urllib.parse import quote

_PAYING_AD = {
    "zone_id": "zone-one",
    "creative_url": "https://example.test/creative.png",
    "click_url": (
        "https://bids.mantis.marketing/clicked?r="
        + quote(
            "https://www.grasscity.com/?utm_source=mantis&utm_medium=6950d5527c56c6494f189e46",
            safe="",
        )
        + "&bi=live&bt=1"
    ),
    "creative_width": 300,
    "creative_height": 250,
    "served_pixels": [],
    "viewed_pixels": [],
}

_HOUSE_AD = {
    "zone_id": "zone-one",
    "creative_url": "https://example.test/house.png",
    "click_url": (
        "https://bids.mantis.marketing/clicked?r="
        "https%3A%2F%2Fwww.mantisadnetwork.com%2F&bi=live&bt=1"
    ),
    "creative_width": 300,
    "creative_height": 250,
    "served_pixels": [],
    "viewed_pixels": [],
}


def test_inject_script_paints_empty_zones_only(monkeypatch) -> None:
    monkeypatch.setattr(
        "automation.mantis_inject_proxy.get_cached_ssp_ads",
        lambda allow_stale=True: [_PAYING_AD],
    )
    monkeypatch.setattr(
        "automation.mantis_inject_proxy.prefetch_ssp_ads_prefer_paying",
        lambda **_kwargs: [],
    )
    from automation.mantis_inject_proxy import _build_inject_script

    text = _build_inject_script().decode("utf-8")
    assert "var emptyOnly = true" in text
    assert "var emptyOnly = false" not in text
    assert "},2000);" in text
    assert "},0);" not in text


def test_inject_script_skips_house_only_paint(monkeypatch) -> None:
    """House inventory must not become a host-paint fallback."""
    monkeypatch.setattr(
        "automation.mantis_inject_proxy.get_cached_ssp_ads",
        lambda allow_stale=True: [_HOUSE_AD],
    )
    monkeypatch.setattr(
        "automation.mantis_inject_proxy.prefetch_ssp_ads_prefer_paying",
        lambda **_kwargs: [],
    )
    from automation.mantis_inject_proxy import _build_inject_script

    text = _build_inject_script().decode("utf-8")
    assert "__pharmflowRunHostPaint" not in text
    assert "mantisadnetwork.com" not in text
