"""Earn plan uses the operator's numbers. It does not invent a fleet or a click ceiling."""
from __future__ import annotations

import json
import random
from pathlib import Path

from automation.earn_plan import (
    applied_ads_per_phone,
    applied_path3_farm_cap,
    applied_visits_per_phone,
    compute_earn_plan,
    load_earn_plan,
    random_phone_counts,
    save_earn_plan,
)


def test_refuses_a_missing_phone_count() -> None:
    out = compute_earn_plan({"target_usd": 18, "ecpm": 1})
    assert out["ok"] is False
    assert "phones" in out["error"]


def test_target_payout_sets_path_counts_without_a_click_ceiling() -> None:
    out = compute_earn_plan(
        {
            "phones": 2,
            "target_usd": 4.4,
            "ecpm": 1.0,
            "impressions_per_visit": 22,
            "visits_per_paid_action": 35,
            "ads_allowed": True,
            "path2_share": 0.20,
            "awake_hours": 16,
            "spread_seed": 7,
        },
        rng=random.Random(7),
    )
    assert out["ok"] is True
    # 4.4 * 1000 / 1 / 22 = 200 visits. 200 / 2 phones = 100 mean each.
    assert out["visits_per_phone"] == 100
    assert sum(out["visits_by_phone"]) == 200
    assert len(out["visits_by_phone"]) == 2
    assert out["visits_by_phone"][0] != out["visits_by_phone"][1]
    assert sum(out["path3_by_phone"]) == sum(
        v // 35 for v in out["visits_by_phone"]
    )
    assert sum(out["path1_by_phone"]) + sum(out["path2_by_phone"]) + sum(out["path3_by_phone"]) == 200
    assert out["implied_usd"] == 200 * 22 * 1.0 / 1000.0


def test_typed_visits_win_over_the_payout_inversion() -> None:
    out = compute_earn_plan(
        {
            "phones": 3,
            "visits_per_phone": 40,
            "target_usd": 500,
            "ecpm": 2,
            "visits_per_paid_action": 40,
            "ads_allowed": True,
            "spread_seed": 3,
        },
        rng=random.Random(3),
    )
    assert out["ok"] is True
    assert out["visits_per_phone"] == 40
    assert out["visit_source"] == "operator_visits"
    assert sum(out["visits_by_phone"]) == 120
    assert len(set(out["visits_by_phone"])) > 1


def test_ads_off_puts_every_visit_on_path_1_and_2() -> None:
    out = compute_earn_plan(
        {
            "phones": 1,
            "visits_per_phone": 10,
            "ads_allowed": False,
            "path2_share": 0.20,
        }
    )
    assert out["ok"] is True
    assert out["path3_by_phone"] == [0]
    assert out["paths"] == "1,2"
    assert out["path1_by_phone"][0] + out["path2_by_phone"][0] == 10


def test_ads_on_without_a_quality_ratio_is_an_error() -> None:
    out = compute_earn_plan({"phones": 1, "visits_per_phone": 10, "ads_allowed": True})
    assert out["ok"] is False
    assert "visits per paid action" in out["error"]


def test_save_writes_the_plan_and_does_not_replace_a_failed_compute(tmp_path: Path) -> None:
    dest = tmp_path / "earn_plan.json"
    dest.write_text("{not json", encoding="utf-8")
    failed = save_earn_plan({"phones": 0}, dest)
    assert failed["ok"] is False
    assert dest.read_text(encoding="utf-8") == "{not json"
    saved = save_earn_plan(
        {
            "phones": 1,
            "visits_per_phone": 8,
            "ads_allowed": False,
            "path2_share": 0,
            "spread_seed": 1,
        },
        dest,
    )
    assert saved["saved"] is True
    disk = json.loads(dest.read_text(encoding="utf-8"))
    assert disk["visits_by_phone"] == [8]
    assert load_earn_plan(dest)["visits_by_phone"] == [8]


def test_more_live_phones_raise_the_path3_farm_cap(tmp_path: Path) -> None:
    dest = tmp_path / "earn_plan.json"
    saved = save_earn_plan(
        {
            "phones": 2,
            "visits_per_phone": 70,
            "ads_allowed": True,
            "visits_per_paid_action": 35,
            "spread_seed": 11,
        },
        dest,
    )
    assert sum(saved["path3_by_phone"]) >= 2
    assert applied_path3_farm_cap(2, dest) == sum(saved["path3_by_phone"])
    assert applied_path3_farm_cap(6, dest) >= applied_path3_farm_cap(2, dest)
    assert applied_visits_per_phone(0, dest) != applied_visits_per_phone(1, dest)
    assert applied_ads_per_phone(0, dest) is not None


def test_random_phone_counts_sum_and_differ() -> None:
    out = random_phone_counts(200, 4, random.Random(42))
    assert sum(out) == 200
    assert len(out) == 4
    assert len(set(out)) > 1
