"""Path3 rails: farm-wide gap must not serialize all phones to ~5 clicks/hour."""
from __future__ import annotations

from pathlib import Path

from automation.farm_health_audit import HOLD, apply_money_rails, scale_csv
from automation.farm_visit_caps import write_runtime_overrides
from automation.mantis_steering import _path3_click_budget, plan_steering


def test_nine_phone_ads_sum_exceeds_old_48_cap() -> None:
    ads = scale_csv(HOLD["ads"], 9, min_val=16, step=0)
    parts = [int(x) for x in ads.split(",")]
    assert len(parts) == 9
    assert sum(parts) > 48


def test_hold_rails_set_path3_cap_to_ads_sum_and_parallel_gap(tmp_path: Path, monkeypatch) -> None:
    import automation.farm_health_audit as audit
    from automation.cpharm_farm_config import get_runtime, merge_runtime, reset_runtime

    monkeypatch.setattr(audit, "LOG", tmp_path)
    reset_runtime(note="test")
    merge_runtime({"CPHARM_FARM_PHONE_COUNT": "9"}, note="test")
    # Caught-up day → Path3 cap = sum of per-phone ad budgets, parallel (gap 0).
    apply_money_rails(mode="hold", reason="test_path3", clicks=50, payout_usd=20.0)
    data = get_runtime()
    ads = [int(x) for x in str(data["CPHARM_FARM_DAILY_ADS"]).split(",")]
    assert int(data["CPHARM_FARM_PATH3_DAILY_CAP"]) == sum(ads)
    assert data["CPHARM_FARM_PATH3_GLOBAL_GAP_MIN"] == "0"
    assert data["CPHARM_FARM_PATH3_PER_HOUR"] == "60"
    assert data["CPHARM_FARM_SEQS_PER_HOUR"] == "36"
    assert data["CPHARM_FARM_UNIQUE_SEQ"] == "1"
    assert data["CPHARM_EMULATOR_AD_FORCE_DIRECT"] == "1"
    assert data["CPHARM_EMULATOR_AD_FALLBACK"] == "1"
    assert not (tmp_path / "FARM_HEAT_DOWN.flag").is_file()


def test_hold_rails_push_path3_when_behind(tmp_path: Path, monkeypatch) -> None:
    import automation.farm_health_audit as audit
    from automation.cpharm_farm_config import get_runtime, merge_runtime, reset_runtime

    monkeypatch.setattr(audit, "LOG", tmp_path)
    reset_runtime(note="test")
    merge_runtime({"CPHARM_FARM_PHONE_COUNT": "7"}, note="test")
    # Behind on clicks/$ → Path3 cap floors at 3000 and stays parallel; seqs 36.
    apply_money_rails(mode="hold", reason="test_behind", clicks=5, payout_usd=2.0)
    data = get_runtime()
    assert data["CPHARM_FARM_PATH3_DAILY_CAP"] == "3000"
    assert data["CPHARM_FARM_PATH3_PER_HOUR"] == "60"
    assert data["CPHARM_FARM_SEQS_PER_HOUR"] == "36"
    assert data["CPHARM_FARM_PATH3_GLOBAL_GAP_MIN"] == "0"
    assert data["CPHARM_FARM_UNIQUE_SEQ"] == "1"


def test_heat_down_does_not_drip_path3(tmp_path: Path, monkeypatch) -> None:
    import automation.farm_health_audit as audit
    from automation.cpharm_farm_config import get_runtime, merge_runtime, reset_runtime

    monkeypatch.setattr(audit, "LOG", tmp_path)
    reset_runtime(note="test")
    merge_runtime({"CPHARM_FARM_PHONE_COUNT": "8"}, note="test")
    # UTC $0 / clicks 0 is not dilution — must degrade to HOLD rails, no flag.
    apply_money_rails(mode="heat_down", reason="test_house", clicks=0, payout_usd=0.0)
    data = get_runtime()
    assert data["CPHARM_FARM_PATH3_DAILY_CAP"] == "3000"  # behind floor
    assert data["CPHARM_FARM_PATH3_GLOBAL_GAP_MIN"] == "0"
    assert data["CPHARM_FARM_PATH3_PER_HOUR"] == "60"
    assert data["CPHARM_PATH3_REQUIRE_PAYING"] == "0"
    assert data["CPHARM_EMULATOR_AD_FORCE_DIRECT"] == "1"
    # Must not cut seqs to 10/14 heat-down.
    assert data["CPHARM_FARM_SEQS_PER_HOUR"] == "36"
    assert data["CPHARM_FARM_EST_IMPRESSIONS"] == "12000"
    assert not (tmp_path / "FARM_HEAT_DOWN.flag").is_file()


def test_heat_down_with_clicks_cuts_seqs_not_path3_gap(tmp_path: Path, monkeypatch) -> None:
    import automation.farm_health_audit as audit
    from automation.cpharm_farm_config import get_runtime, merge_runtime, reset_runtime

    monkeypatch.setattr(audit, "LOG", tmp_path)
    reset_runtime(note="test")
    merge_runtime({"CPHARM_FARM_PHONE_COUNT": "8"}, note="test")
    apply_money_rails(mode="heat_down", reason="test_house", clicks=50, payout_usd=20.0)
    data = get_runtime()
    ads = [int(x) for x in str(data["CPHARM_FARM_DAILY_ADS"]).split(",")]
    assert int(data["CPHARM_FARM_PATH3_DAILY_CAP"]) == sum(ads)
    assert data["CPHARM_FARM_PATH3_GLOBAL_GAP_MIN"] == "0"
    assert data["CPHARM_FARM_PATH3_PER_HOUR"] == "8"
    # Heat-down cuts Path3 pace (8/hr), never sequence volume (36) or gap.
    assert data["CPHARM_FARM_SEQS_PER_HOUR"] == "36"
    assert (tmp_path / "FARM_HEAT_DOWN.flag").is_file()


def test_resolve_path3_prefetch_after_force_refresh(monkeypatch) -> None:
    from automation import sequence_runner as sr

    calls: list[dict] = []
    pref = {"n": 0}

    def fake_click(zone, *, allow_any=True, prefer_paying=True, force_refresh=False):
        calls.append({"zone": zone, "force": force_refresh})
        if force_refresh and pref["n"]:
            return (
                "https://bids.mantis.marketing/clicked?r=https://www.grasscity.com/"
                "&p=2&bi=pay"
            )
        return (
            "https://bids.mantis.marketing/clicked?r="
            "https://www.mantisadnetwork.com/?utm_source=mantis-bot"
        )

    def fake_prefetch(*, attempts=14, delay_s=0.25, allow_house_fallback=False):
        pref["n"] += 1
        return [{"click_url": "https://bids.mantis.marketing/clicked?r=https://ok"}]

    monkeypatch.setattr(sr, "click_url_for_zone", fake_click)
    monkeypatch.setattr(sr, "prefetch_ssp_ads_prefer_paying", fake_prefetch)
    got = sr.resolve_path3_paying_click_url("zone-a", "")
    assert pref["n"] == 1
    assert any(c["force"] for c in calls)
    assert "bids.mantis.marketing/clicked" in got
    assert "mantis-bot" not in got.lower()


def test_resolve_path3_never_returns_house_url(monkeypatch) -> None:
    from automation import sequence_runner as sr

    monkeypatch.setattr(
        sr,
        "click_url_for_zone",
        lambda *a, **k: (
            "https://bids.mantis.marketing/clicked?r="
            "https://www.mantisadnetwork.com/?utm_source=mantis-bot"
        ),
    )
    monkeypatch.setattr(sr, "prefetch_ssp_ads_prefer_paying", lambda **k: [])
    assert sr.resolve_path3_paying_click_url("z") == ""
    monkeypatch.setenv("CPHARM_PATH3_REQUIRE_PAYING", "0")
    house = (
        "https://bids.mantis.marketing/clicked?r="
        "https://www.mantisadnetwork.com/?utm_source=mantis-bot"
    )
    assert sr.resolve_path3_click_url("z", house) == house


def test_visit_caps_keeps_gap_zero(tmp_path: Path) -> None:
    (tmp_path / "farm_site_lock.json").write_text(
        '{"slug": "dabflow", "daily_ads_csv": "24,24,22,22,20,20,20,20"}',
        encoding="utf-8",
    )
    (tmp_path / "farm_runtime_overrides.json").write_text(
        '{"CPHARM_FARM_PATH3_GLOBAL_GAP_MIN": "0", "CPHARM_FARM_PATH3_DAILY_CAP": "10"}',
        encoding="utf-8",
    )
    fixed, _ = write_runtime_overrides({}, log_dir=tmp_path)
    assert fixed["CPHARM_FARM_PATH3_GLOBAL_GAP_MIN"] == "0"
    assert int(fixed["CPHARM_FARM_PATH3_DAILY_CAP"]) >= 172


def test_steering_does_not_clamp_path3_to_40() -> None:
    budget = _path3_click_budget(
        {"CPHARM_FARM_DAILY_ADS": "24,24,22,22,20,20,20,20", "CPHARM_FARM_PATH3_DAILY_CAP": "172"}
    )
    assert budget >= 172
    score = {
        "tone": "yellow",
        "levers": {
            "clicks": {"value": 36},
            "evcpm": {"value": 9.0, "kind": "in"},
            "ecpm": {"value": 0.7},
            "impressions": {"value": 5000},
        },
    }
    out = plan_steering(
        score,
        current_overrides={
            "CPHARM_FARM_DAILY_ADS": "24,24,22,22,20,20,20,20",
            "CPHARM_FARM_PATH3_DAILY_CAP": "172",
            "CPHARM_FARM_ALLOW_ADS": "1",
        },
    )
    assert out["overrides_patch"].get("CPHARM_FARM_PATH3_DAILY_CAP") != "40"
    assert "browse_only" not in {a["type"] for a in out["actions"]}
