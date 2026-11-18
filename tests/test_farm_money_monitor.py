"""Unit tests for money-health alerts (not flat-$ alone)."""
from __future__ import annotations

from automation.farm_money_monitor import _money_health_problems


def test_junk_ecpm_and_dilution_alert_without_flat_dollar() -> None:
    problems = _money_health_problems(
        payout=4.36,
        ecpm=0.16,
        impr=27000,
        actives=5,
        ssp={"paying": 0, "house": 8},
        flat=False,
        flat_minutes=0.0,
    )
    assert any(p.startswith("SSP_HOUSE_ONLY") for p in problems)
    assert any(p.startswith("IMPR_DILUTION") for p in problems)
    assert any(p.startswith("MONEY_JUNK_RATE") for p in problems)
    assert any(p.startswith("BURNING_IMPR_NO_PAY") for p in problems)


def test_healthy_paying_fill_no_problems() -> None:
    problems = _money_health_problems(
        payout=42.0,
        ecpm=2.5,
        impr=18000,
        actives=5,
        ssp={"paying": 3, "house": 1},
        flat=False,
        flat_minutes=0.0,
    )
    assert problems == []


def test_flat_dollar_alone_is_a_problem() -> None:
    problems = _money_health_problems(
        payout=12.0,
        ecpm=1.2,
        impr=5000,
        actives=4,
        ssp={"paying": 2, "house": 0},
        flat=True,
        flat_minutes=28.0,
    )
    assert any(p.startswith("FLAT_DOLLAR") for p in problems)


def test_hunter_heartbeat_stale_missing_or_old() -> None:
    from automation.farm_money_monitor import hunter_heartbeat_stale

    now = 1_000_000.0
    assert hunter_heartbeat_stale(None, now) is True
    assert hunter_heartbeat_stale(now - 10, now) is False
    assert hunter_heartbeat_stale(now - 181, now) is True


def test_fresh_paying_fill_not_cleared(monkeypatch) -> None:
    from automation import farm_money_monitor as mon

    monkeypatch.setattr(mon.ssp_mod, "paying_fill_file_fresh", lambda: True)
    monkeypatch.setattr(mon.ssp_mod, "_ingest_paying_fill_file", lambda: [{"click_url": "x"}])
    monkeypatch.setattr(mon.ssp_mod, "ssp_ads_paying_count", lambda ads: 2)
    cleared = {"n": 0}

    def boom(*_a, **_k):
        cleared["n"] += 1
        return True

    monkeypatch.setattr(mon.ssp_mod, "clear_ssp_paying_fill_file", boom)
    assert mon._fresh_paying_fill_count() == 2
    assert cleared["n"] == 0


def test_probe_ssp_prefers_fresh_paying_fill_over_host_house(monkeypatch) -> None:
    """money_ok must see hunter fill even when a host re-probe would be house-only."""
    from automation import farm_money_monitor as mon

    paying_ads = [
        {
            "zone_id": "zone-one",
            "click_url": (
                "https://bids.mantis.marketing/clicked?r="
                "https%3A%2F%2Fwww.grasscity.com%2F%3Futm_source%3Dmantis&bi=x&bt=y"
            ),
        }
    ]

    monkeypatch.setattr(mon.ssp_mod, "_ingest_paying_fill_file", lambda: paying_ads)
    monkeypatch.setattr(mon.ssp_mod, "ssp_ads_paying_count", lambda ads: 1 if ads else 0)
    monkeypatch.setattr(
        mon.ssp_mod,
        "prefetch_ssp_ads",
        lambda force=False: (_ for _ in ()).throw(
            AssertionError("host prefetch must not run when fill is paying")
        ),
    )
    monkeypatch.setattr(mon.ssp_mod, "ssp_paying_zone_ids", lambda force_refresh=False: {"zone-one"})

    out = mon.probe_ssp()
    assert out["paying"] == 1
    assert out["has_paying_fill"] is True
    assert out["paying_zones"] == ["zone-one"]
