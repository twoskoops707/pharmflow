#!/usr/bin/env python3
"""
End-to-end smoke for the Step 7 generator: load → edit → save round-trip.

Mirrors what `test_sequence_generator_edge_cases.py` checks under unittest, but as
a single script run that surfaces failures with non-zero exit even when unittest
discovery is bypassed (e.g. PyInstaller spec smoke or quick local triage).

From repo root::

    py -3 wizard/smoke_sequence_generator_flow.py
"""
from __future__ import annotations

import json
import random
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

_WIZ = Path(__file__).resolve().parent
if str(_WIZ) not in sys.path:
    sys.path.insert(0, str(_WIZ))
_AUTO = _WIZ.parent / "automation"
if _AUTO.is_dir() and str(_AUTO) not in sys.path:
    sys.path.insert(0, str(_AUTO))

from setup_wizard import SequenceGeneratorPage  # noqa: E402


class _DummyVar:
    def __init__(self) -> None:
        self.value = None

    def set(self, value):
        self.value = value


def _make_page() -> SequenceGeneratorPage:
    page = SequenceGeneratorPage.__new__(SequenceGeneratorPage)
    page._steps = []
    page._target_kind = None
    page._url_var = _DummyVar()
    page._package_var = _DummyVar()
    page._base_w_var = _DummyVar()
    page._base_h_var = _DummyVar()
    page._viewport_var = _DummyVar()
    page._import_info_var = _DummyVar()
    page._status_var = _DummyVar()
    page._save_status_var = _DummyVar()
    page._status_lbl = SimpleNamespace(config=lambda **_kw: None)
    page._normalize_with_context = lambda steps: list(steps)
    page._set_tools_enabled = lambda enabled: None
    page._refresh_builder = lambda *_a, **_kw: None
    page._show_phase = lambda phase: setattr(page, "_phase_after_load", phase)
    page._profile_dims = lambda: (
        int(page._base_w_var.value or 900),
        int(page._base_h_var.value or 1600),
    )
    # `_load_file` evaluates ``parent=self.winfo_toplevel()`` before the
    # patched filedialog runs, so give it a stub that doesn't need real Tk.
    page.winfo_toplevel = lambda: None
    return page


def _patched_dialog(path: Path):
    """Context-manager-ish helper that swaps `filedialog.askopenfilename`."""
    from tkinter import filedialog

    orig = filedialog.askopenfilename
    filedialog.askopenfilename = lambda **_kw: str(path)
    return orig


def _restore_dialog(orig) -> None:
    from tkinter import filedialog

    filedialog.askopenfilename = orig


def _check_load_wrapped(tmp: Path) -> None:
    page = _make_page()
    wrapped = {
        "label": "Smoke wrapped",
        "steps": [
            {"type": "open_url", "url": "https://wrapped.example"},
            {"type": "tap", "x": 120, "y": 240, "base_w": 900, "base_h": 1600},
            {"type": "wait", "seconds": 2.0},
        ],
    }
    p = tmp / "wrapped.json"
    p.write_text(json.dumps(wrapped), encoding="utf-8")
    orig = _patched_dialog(p)
    try:
        SequenceGeneratorPage._load_file(page)
    finally:
        _restore_dialog(orig)
    assert len(page._steps) == 3, f"wrapped: expected 3 steps, got {len(page._steps)}"
    assert page._url_var.value == "https://wrapped.example", page._url_var.value
    assert page._target_kind == "website", page._target_kind
    assert page._phase_after_load == "builder", page._phase_after_load
    assert "Smoke wrapped" in (page._import_info_var.value or "")


def _check_load_bare(tmp: Path) -> None:
    page = _make_page()
    bare = [
        {"type": "open_url", "url": "https://bare.example"},
        {"type": "swipe", "x1": 10, "y1": 20, "x2": 30, "y2": 40, "ms": 600,
         "base_w": 720, "base_h": 1280},
    ]
    p = tmp / "bare.json"
    p.write_text(json.dumps(bare), encoding="utf-8")
    orig = _patched_dialog(p)
    try:
        SequenceGeneratorPage._load_file(page)
    finally:
        _restore_dialog(orig)
    assert len(page._steps) == 2
    assert page._url_var.value == "https://bare.example"
    assert page._target_kind == "website", page._target_kind
    assert page._base_w_var.value == 720, page._base_w_var.value
    assert page._base_h_var.value == 1280, page._base_h_var.value


def _check_save_round_trip(tmp: Path) -> None:
    page = SequenceGeneratorPage.__new__(SequenceGeneratorPage)
    page._steps = [
        {"type": "open_url", "url": "https://example.test"},
        {"type": "tap", "x": 450, "y": 1040, "base_w": 900, "base_h": 1600,
         "retries": 2, "jitter": 18, "pre_wait_ms": 260},
        {"type": "wait", "seconds": 4.0},
        {"type": "rotate_identity"},
        {"type": "wait", "seconds": 2.0},
        {"type": "full_reset"},
    ]
    page._normalize_with_context = lambda steps: list(steps)
    page._validation_lines = lambda: (["ok"], True)
    page._save_status_var = _DummyVar()
    page._status_var = _DummyVar()
    page._status_lbl = SimpleNamespace(config=lambda **_kw: None)
    out = tmp / "saved.json"
    page._target_path = lambda use_dialog: str(out)
    SequenceGeneratorPage._do_save(page, use_dialog=False)
    assert out.exists(), "save did not write a file"
    round_trip = json.loads(out.read_text(encoding="utf-8"))
    assert round_trip[0]["type"] == "open_url"
    assert round_trip[-1]["type"] == "full_reset"


def _check_human_like_helpers() -> None:
    page = SequenceGeneratorPage.__new__(SequenceGeneratorPage)
    page._base_w_var = SimpleNamespace(get=lambda: 720)
    page._base_h_var = SimpleNamespace(get=lambda: 1280)
    # Slow-scroll baseline assertion runs against the deterministic (off) branch.
    page._human_timing_var = SimpleNamespace(get=lambda: False)

    swipe = SequenceGeneratorPage._human_slow_scroll_up(page)
    assert swipe["type"] == "swipe" and swipe["ms"] == 2100
    assert swipe["base_w"] == 720 and swipe["base_h"] == 1280
    assert swipe["y1"] > swipe["y2"], "slow scroll up must travel upward"

    rng = random.Random(123)
    orig = random.uniform
    try:
        random.uniform = rng.uniform
        for _ in range(10):
            step = SequenceGeneratorPage._human_micro_wait_gap(page)
            assert step["type"] == "wait"
            assert 0.28 <= step["seconds"] <= 0.52
    finally:
        random.uniform = orig

    # Toggling natural timing on must add bounded variance to swipe.ms.
    page._human_timing_var = SimpleNamespace(get=lambda: True)
    rng2 = random.Random(7)
    orig_gauss = random.gauss
    try:
        random.gauss = rng2.gauss
        ms_samples = [
            SequenceGeneratorPage._swipe_step(page, 100, 200, 110, 210, 900)["ms"]
            for _ in range(20)
        ]
    finally:
        random.gauss = orig_gauss
    assert len(set(ms_samples)) > 1, "human timing should vary swipe.ms"
    for ms in ms_samples:
        assert 80 <= ms <= 5000, f"swipe.ms out of bounds: {ms}"

    page._tap_jitter_boost_next = 0
    page._save_status_var = _DummyVar()
    SequenceGeneratorPage._human_arm_jitter_next_tap(page)
    SequenceGeneratorPage._human_arm_jitter_next_tap(page)
    assert page._tap_jitter_boost_next == 28
    page._tap_jitter_boost_next = 95
    SequenceGeneratorPage._human_arm_jitter_next_tap(page)
    assert page._tap_jitter_boost_next == 100, page._tap_jitter_boost_next


def _check_url_vs_app_mode_state(tmp: Path) -> None:
    """Both URL and App entry points are exposed, and an App-mode file routes correctly."""
    nav = SequenceGeneratorPage._TOOLBOX.get("Navigation", {})
    assert "Open website" in nav, "URL flow regressed: 'Open website' missing"
    assert "Launch installed app" in nav, "App flow regressed: 'Launch installed app' missing"

    page = _make_page()
    app_doc = [
        {"type": "launch_app", "package": "com.example.smoke"},
        {"type": "tap", "x": 200, "y": 400, "base_w": 900, "base_h": 1600},
    ]
    p = tmp / "app_smoke.json"
    p.write_text(json.dumps(app_doc), encoding="utf-8")
    orig = _patched_dialog(p)
    try:
        SequenceGeneratorPage._load_file(page)
    finally:
        _restore_dialog(orig)
    assert page._target_kind == "app", page._target_kind
    assert page._package_var.value == "com.example.smoke", page._package_var.value
    assert page._url_var.value is None, page._url_var.value
    assert page._phase_after_load == "builder"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _check_load_wrapped(tmp)
        _check_load_bare(tmp)
        _check_save_round_trip(tmp)
        _check_url_vs_app_mode_state(tmp)
    _check_human_like_helpers()
    print("smoke_sequence_generator_flow: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
