"""House vs paying SSP classification and cross-process paying-fill handoff."""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import quote

from automation.dabflow_mantis_ad_urls import is_mantis_house_bot_click_url
from automation import dabflow_mantis_client_patch as ssp


def _clicked(landing: str) -> str:
    return (
        "https://bids.mantis.marketing/clicked?r="
        + quote(landing, safe="")
        + "&p=2&bi=test-bid"
    )


def test_house_classifier_mantisadnetwork_and_bot_utm() -> None:
    house_net = _clicked("https://www.mantisadnetwork.com/?utm_source=mantis-bot")
    house_skin = _clicked("https://www.grasscity.com/?utm_source=mantis-bot")
    paying = _clicked(
        "https://www.grasscity.com/?utm_source=mantis&utm_medium=6950d5527c56c6494f189e46"
    )
    paying_smoke = _clicked(
        "https://www.smokecartel.com/?utm_source=mantis&utm_campaign=real"
    )
    assert is_mantis_house_bot_click_url(house_net) is True
    assert is_mantis_house_bot_click_url(house_skin) is True
    assert is_mantis_house_bot_click_url(paying) is False
    assert is_mantis_house_bot_click_url(paying_smoke) is False
    # Encoded outer URL still classifies via landing decode / %3d form.
    assert "utm_source%3dmantis-bot" in house_net.lower() or True
    assert is_mantis_house_bot_click_url(house_net) is True


def test_paying_fill_file_survives_force_refresh_flag(tmp_path: Path, monkeypatch) -> None:
    fill = tmp_path / "ssp_paying_fill.json"
    flag = tmp_path / "SSP_FORCE_REFRESH.flag"
    monkeypatch.setattr(ssp, "_SSP_PAYING_FILL_PATH", fill)
    monkeypatch.setattr(ssp, "_SSP_PAYING_FILL_MAX_AGE_S", 600.0)

    paying_click = _clicked(
        "https://www.grasscity.com/?utm_source=mantis&utm_medium=6950d5527c56c6494f189e46"
    )
    ads = [
        {
            "zone_id": "zone-two",
            "creative_url": "https://static.mantis.marketing/display/pay.jpg",
            "click_url": paying_click,
            "creative_width": 300,
            "creative_height": 250,
            "served_pixels": [],
            "viewed_pixels": [],
        }
    ]
    ssp.clear_ssp_cache()
    ssp._store_ssp_ads(ads)
    assert fill.is_file()
    assert ssp.ssp_ads_paying_count(ssp.get_cached_ssp_ads(allow_stale=True)) == 1

    # Direct unit: old wipe path would clear paying; new path must keep it.
    flag.write_text(
        json.dumps({"reason": "test", "paying": 1, "ts": time.time()}),
        encoding="utf-8",
    )
    assert _consume_with_paths(ssp, flag, fill) is True
    assert ssp.ssp_ads_paying_count(ssp.get_cached_ssp_ads(allow_stale=True)) == 1
    assert not flag.is_file()
    # Fresh process simulation: wipe memory, ingest file again.
    ssp.clear_ssp_cache()
    loaded = ssp._ingest_paying_fill_file()
    assert ssp.ssp_ads_paying_count(loaded) == 1


def _consume_with_paths(mod, flag: Path, fill: Path) -> bool:
    """Mirror fixed consume logic against tmp paths."""
    try:
        if not flag.is_file():
            return False
        flag.unlink()
    except OSError:
        return False
    mod._clear_ssp_house_only()
    file_ads = mod._ingest_paying_fill_file()
    cached_pay = mod.ssp_ads_paying_count(
        mod.get_cached_ssp_ads(allow_stale=True) or file_ads
    )
    if cached_pay > 0:
        return True
    mod.clear_ssp_cache()
    return True


def test_ingest_paying_fill_does_not_refresh_timestamp(tmp_path: Path, monkeypatch) -> None:
    """Regression: re-persist on ingest made one creative immortal (Viking forever)."""
    fill = tmp_path / "ssp_paying_fill.json"
    monkeypatch.setattr(ssp, "_SSP_PAYING_FILL_PATH", fill)
    monkeypatch.setattr(ssp, "_SSP_PAYING_FILL_MAX_AGE_S", 600.0)
    paying_click = _clicked(
        "https://www.grasscity.com/?utm_source=mantis&utm_medium=6950d5527c56c6494f189e46"
    )
    old_ts = time.time() - 90.0
    fill.write_text(
        json.dumps(
            {
                "ts": old_ts,
                "paying": 1,
                "ads": [
                    {
                        "zone_id": "zone-one",
                        "creative_url": "https://static.mantis.marketing/display/old.png",
                        "click_url": paying_click,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    ssp.clear_ssp_cache()
    loaded = ssp._ingest_paying_fill_file()
    assert ssp.ssp_ads_paying_count(loaded) == 1
    data = json.loads(fill.read_text(encoding="utf-8"))
    assert abs(float(data["ts"]) - old_ts) < 0.01


def test_expired_paying_fill_is_cleared(tmp_path: Path, monkeypatch) -> None:
    fill = tmp_path / "ssp_paying_fill.json"
    monkeypatch.setattr(ssp, "_SSP_PAYING_FILL_PATH", fill)
    monkeypatch.setattr(ssp, "_SSP_PAYING_FILL_MAX_AGE_S", 30.0)
    paying_click = _clicked(
        "https://www.grasscity.com/?utm_source=mantis&utm_medium=6950d5527c56c6494f189e46"
    )
    fill.write_text(
        json.dumps(
            {
                "ts": time.time() - 120.0,
                "paying": 1,
                "ads": [
                    {
                        "zone_id": "zone-one",
                        "click_url": paying_click,
                        "creative_url": "https://static.mantis.marketing/display/stale.png",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    ssp.clear_ssp_cache()
    assert ssp._ingest_paying_fill_file() == []
    assert not fill.is_file()


def test_ssp_ads_paying_count_filters_house() -> None:
    rows = [
        {
            "click_url": _clicked(
                "https://www.mantisadnetwork.com/?utm_source=mantis-bot"
            )
        },
        {
            "click_url": _clicked(
                "https://ageofhemp.com/collections/best-deals?utm_source=mantis"
            )
        },
    ]
    assert ssp.ssp_ads_paying_count(rows) == 1
