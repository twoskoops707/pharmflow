"""Tests for humanize scroll safety and sequence version gate."""

from __future__ import annotations

import json
import os
from pathlib import Path

from automation.config import REQUIRED_SEQUENCE_VERSION
from automation.humanize import MIN_SCROLL_Y, enforce_scroll_coords, normalize_swipe_params, scroll_swipe_params
from automation.sequence_runner import Sequence
from wizard.dabflow_studio import DEFAULT_FARM_HOURS, apply_farm_prefs_to_environ, farm_prefs_defaults, rationale_text
from automation.dabflow_mapper import load_mapping

def test_scroll_swipe_starts_below_third_screen() -> None:
    params = scroll_swipe_params(seed=42, tolerance=10)
    y1 = params["y1"]["base"]
    y2 = params["y2"]["base"]
    assert y1 >= MIN_SCROLL_Y + 350
    assert y2 >= MIN_SCROLL_Y + 80
    assert y1 > y2


def test_normalize_swipe_maps_x_y_to_x1_y1() -> None:
    out = normalize_swipe_params({"x": {"base": 450}, "y": {"base": 100}, "x2": {"base": 450}, "y2": {"base": 500}})
    assert "x1" in out
    assert int(out["y1"]["base"]) >= MIN_SCROLL_Y + 40


def test_enforce_scroll_overrides_top_coords() -> None:
    x1, y1, x2, y2 = enforce_scroll_coords(450, 50, 450, 200, seed=7)
    assert y1 >= MIN_SCROLL_Y
    assert y1 > 50  # bumped out of notification shade


def test_enforce_scroll_preserves_long_ad_reveal() -> None:
    x1, y1, x2, y2 = enforce_scroll_coords(450, 1100, 450, 450, seed=3)
    assert y1 == 1100
    assert y2 == 450


def test_regenerated_sequence_has_version_and_age_gate() -> None:
    path = Path("automation/recordings/sequences/base/ceramic/ceramic_budder_butane_p1a_chromium_complete.json")  # per-browser Unison SSOT
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get("sequence_version", 0) >= REQUIRED_SEQUENCE_VERSION
    steps = data["steps"]
    assert any(s.get("description", "").startswith("Age gate:") for s in steps)
    age = next(s for s in steps if s.get("description", "").startswith("Age gate:"))
    assert age["params"]["y"]["base"] == 980
    assert any("Start Perfect Dab" in (s.get("description") or "") for s in steps)
    assert any("Scroll to reveal Start Perfect Dab" in (s.get("description") or "") for s in steps)
    assert any("Session notes Skip" in (s.get("description") or "") for s in steps)
    swipes = [s for s in steps if s.get("action") == "swipe"]
    assert swipes
    y1 = swipes[0]["params"]["y1"]
    y1_val = y1["base"] if isinstance(y1, dict) else int(y1)
    assert y1_val >= MIN_SCROLL_Y


def test_sequence_from_json_loads_version() -> None:
    path = Path("automation/recordings/sequences/base/ceramic/ceramic_budder_butane_p1a_chromium_complete.json")  # per-browser Unison SSOT
    seq = Sequence.from_json(path)
    assert seq.sequence_version >= REQUIRED_SEQUENCE_VERSION


def test_dabflow_combination_count_is_full_catalog() -> None:
    mapping = load_mapping()
    assert mapping.selection_core_count() == 60  # 3×10×2
    assert mapping.paths_per_selection() == 104  # Path1/2 (× FarmBrowser) + Path3, Unison SSOT
    assert mapping.combination_count() == 6240


def test_dabflow_rationale_exposes_scroll_and_path_rules() -> None:
    text = rationale_text()
    assert "6240" in text
    assert "below the fold" in text
    assert "exactly one ad click" in text
    assert "Path1" in text
    assert "Path3" in text
    assert "30–45s" in text or "30-45s" in text
    assert f"sequence_version ≥ {REQUIRED_SEQUENCE_VERSION}" in text or f"sequence_version >= {REQUIRED_SEQUENCE_VERSION}" in text
    assert str(int(DEFAULT_FARM_HOURS)) in text
    assert "hash_rosin" in text
    assert "p3a_homeadN_ad" in text


def test_farm_prefs_include_hours_and_env() -> None:
    prefs = farm_prefs_defaults()
    assert prefs["hours"] == 6.0
    assert prefs["path3_per_hour"] == 2
    apply_farm_prefs_to_environ(prefs)
    assert os.environ.get("CPHARM_FARM_HOURS") == "6.0"
    assert os.environ.get("CPHARM_FARM_PATH3_PER_HOUR") == "2"
