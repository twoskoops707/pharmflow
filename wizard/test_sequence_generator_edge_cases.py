import inspect
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

_wizard_dir = Path(__file__).resolve().parent
if str(_wizard_dir) not in sys.path:
    sys.path.insert(0, str(_wizard_dir))

# `_load_file` does a local `from sequence_normalize import load_sequence_steps_ui`,
# so make sure the automation module is importable for tests that exercise loading.
_automation_dir = _wizard_dir.parent / "automation"
if _automation_dir.is_dir() and str(_automation_dir) not in sys.path:
    sys.path.insert(0, str(_automation_dir))

import browser_builder_webview as bbw  # noqa: E402
from setup_wizard import SequenceGeneratorPage  # noqa: E402


class _DummyVar:
    def __init__(self) -> None:
        self.value = None

    def set(self, value):
        self.value = value


class _DummyCanvas:
    def __init__(self, width=360, height=220):
        self.width = width
        self.height = height

    def winfo_width(self):
        return self.width

    def winfo_height(self):
        return self.height


class SequenceGeneratorEdgeCaseTests(unittest.TestCase):
    def test_substep_screens_split_responsibilities(self):
        """Each phase owns one job; we don't duplicate save/test buttons across screens.

        Gate picks website vs app; web/app setup collects URL or package; advanced holds templates;
        Build edits actions; Save handles file output.
        """
        gate_src = inspect.getsource(SequenceGeneratorPage._build_gate_screen)
        web_src = inspect.getsource(SequenceGeneratorPage._build_web_setup_screen)
        app_src = inspect.getsource(SequenceGeneratorPage._build_app_setup_screen)
        advanced_src = inspect.getsource(SequenceGeneratorPage._build_advanced_tools_card)
        build_src = inspect.getsource(SequenceGeneratorPage._build_build_screen)
        save_src = inspect.getsource(SequenceGeneratorPage._build_save_screen)

        for token in ('"What are we automating?"', '"Website (URL)"', '"App (APK / package)"'):
            self.assertIn(token, gate_src, f"missing on Gate: {token}")

        for token in ('"Website address"', '"Continue →"', '"Load sequence file'):
            self.assertIn(token, web_src, f"missing on Web setup: {token}")

        for token in ('"Package name"', '"Browse APK', '"Continue →"'):
            self.assertIn(token, app_src, f"missing on App setup: {token}")

        self.assertIn('"Use this layout"', advanced_src, "missing template apply on Advanced")

        for token in ('"Add action"', '"Quick edit"', '"Make pauses feel more natural (recommended)"'):
            self.assertIn(token, build_src, f"missing on Build: {token}")
        for token in ('"Save sequence"', '"Save As'):
            self.assertNotIn(token, build_src, f"Build screen must not duplicate: {token}")

        for token in ('"Save sequence"', '"Save As', '"Run Test"', '"Add to Schedule"'):
            self.assertIn(token, save_src, f"missing on Save: {token}")

    def test_load_calibration_profile_invalid_json_uses_defaults(self):
        page = SequenceGeneratorPage.__new__(SequenceGeneratorPage)
        page._cal_profile = {"scale_x": 1.0, "scale_y": 1.0, "offset_x": 0.0, "offset_y": 0.0}
        page._calibration_var = _DummyVar()
        with tempfile.TemporaryDirectory() as tmp:
            calibration_path = Path(tmp) / "bad_calibration.json"
            calibration_path.write_text("{not valid json", encoding="utf-8")
            page._calibration_path = lambda: calibration_path
            SequenceGeneratorPage._load_calibration_profile(page)

        self.assertEqual(page._cal_profile["scale_x"], 1.0)
        self.assertEqual(page._cal_profile["scale_y"], 1.0)
        self.assertEqual(page._cal_profile["offset_x"], 0.0)
        self.assertEqual(page._cal_profile["offset_y"], 0.0)
        self.assertEqual(page._calibration_var.value, "Could not read saved tap alignment; using defaults.")

    def test_capture_release_without_touch_input_is_noop(self):
        page = SequenceGeneratorPage.__new__(SequenceGeneratorPage)
        page._record_armed = True
        page._drag_start = None
        page._steps = []
        event = SimpleNamespace(x=10, y=15)

        SequenceGeneratorPage._capture_release(page, event)

        self.assertEqual(page._steps, [])
        self.assertIsNone(page._drag_start)

    def test_viewport_to_baseline_clamps_out_of_bounds_coords(self):
        page = SequenceGeneratorPage.__new__(SequenceGeneratorPage)
        page._cal_profile = {"scale_x": 1.0, "scale_y": 1.0, "offset_x": 0.0, "offset_y": 0.0}
        page._profile_dims = lambda: (900, 1600)
        page._viewport_canvas = _DummyCanvas(width=360, height=220)

        x, y = SequenceGeneratorPage._viewport_to_baseline(page, -120, 9999)

        self.assertEqual((x, y), (0, 1600))

    def test_run_test_warns_negative_coords(self):
        page = SequenceGeneratorPage.__new__(SequenceGeneratorPage)
        page._steps = [
            {"type": "tap", "x": -1, "y": 5},
            {"type": "swipe", "x1": 10, "y1": -3, "x2": 20, "y2": 30, "ms": 200},
        ]
        page._normalize_with_context = lambda steps: steps
        page._validation_lines = lambda: (["ok"], True)
        page._profile_dims = lambda: (900, 1600)
        page._save_status_var = _DummyVar()
        result = {}
        page._set_run_log = lambda text: result.setdefault("log", text)

        SequenceGeneratorPage._run_test(page)

        log_text = result.get("log", "")
        self.assertIn("tap is outside the screen size you chose", log_text)
        self.assertIn("swipe goes outside the screen size you chose", log_text)
        # Log formats dimensions as (900×1600) or similar; allow × or ASCII x.
        self.assertRegex(
            log_text,
            r"tap is outside the screen size you chose \(900[×x]1600\)",
        )
        self.assertRegex(
            log_text,
            r"swipe goes outside the screen size you chose \(900[×x]1600\)",
        )

    @staticmethod
    def _make_load_ready_page() -> SequenceGeneratorPage:
        """Bare ``SequenceGeneratorPage`` with the attributes ``_load_file`` touches.

        Mirrors how the running widget exposes Tk vars/labels but stays headless;
        any later code that would have hit Tk widgets is replaced with no-ops.
        """
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
        page._refresh_builder = lambda *_args, **_kw: None
        page._show_phase = lambda phase: setattr(page, "_phase_after_load", phase)
        page._profile_dims = lambda: (
            int(page._base_w_var.value or 900),
            int(page._base_h_var.value or 1600),
        )
        # `_load_file` evaluates ``parent=self.winfo_toplevel()`` before the
        # patched filedialog runs, so give it a stub that doesn't need real Tk.
        page.winfo_toplevel = lambda: None
        return page

    def test_load_wrapped_sequence_json_imports_steps_and_label(self):
        """Wrapped ``{"steps": [...], "label": ...}`` files import like bare arrays.

        This is the same shape ``e8e6742`` taught the wizard to accept; without coverage
        a future refactor could silently regress to "file must be a JSON array of steps".
        """
        page = self._make_load_ready_page()
        wrapped = {
            "label": "Direct visit (wrapped)",
            "steps": [
                {"type": "open_url", "url": "https://example.test"},
                {"type": "tap", "x": 120, "y": 240, "base_w": 900, "base_h": 1600},
                {"type": "wait", "seconds": 2.0},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            seq_path = Path(tmp) / "wrapped.json"
            seq_path.write_text(json.dumps(wrapped), encoding="utf-8")
            from tkinter import filedialog
            orig = filedialog.askopenfilename
            try:
                filedialog.askopenfilename = lambda **_kw: str(seq_path)
                SequenceGeneratorPage._load_file(page)
            finally:
                filedialog.askopenfilename = orig

        self.assertEqual(len(page._steps), 3)
        self.assertEqual(page._steps[0]["type"], "open_url")
        self.assertEqual(page._url_var.value, "https://example.test")
        self.assertEqual(page._target_kind, "website")
        self.assertEqual(page._phase_after_load, "builder")
        self.assertIsNotNone(page._import_info_var.value)
        self.assertIn("Direct visit (wrapped)", page._import_info_var.value)
        self.assertIn("Steps loaded: 3", page._import_info_var.value)

    def test_load_bare_array_sequence_json_imports_steps(self):
        """Legacy bare-array files keep working after the wrapped-doc upgrade."""
        page = self._make_load_ready_page()
        bare = [
            {"type": "open_url", "url": "https://bare.example"},
            {"type": "swipe", "x1": 10, "y1": 20, "x2": 30, "y2": 40, "ms": 600,
             "base_w": 720, "base_h": 1280},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            seq_path = Path(tmp) / "bare.json"
            seq_path.write_text(json.dumps(bare), encoding="utf-8")
            from tkinter import filedialog
            orig = filedialog.askopenfilename
            try:
                filedialog.askopenfilename = lambda **_kw: str(seq_path)
                SequenceGeneratorPage._load_file(page)
            finally:
                filedialog.askopenfilename = orig

        self.assertEqual(len(page._steps), 2)
        self.assertEqual(page._url_var.value, "https://bare.example")
        self.assertEqual(page._target_kind, "website")
        self.assertEqual(page._phase_after_load, "builder")
        # Baseline hint from the swipe step should be applied to the page profile.
        self.assertEqual(page._base_w_var.value, 720)
        self.assertEqual(page._base_h_var.value, 1280)
        self.assertIn("Steps loaded: 2", page._import_info_var.value)
        # Legacy files have no label → the meta suffix must not leak in.
        self.assertNotIn("Label:", page._import_info_var.value)

    def test_save_writes_normalized_steps_round_trip(self):
        """``_do_save`` should hit disk with normalized JSON when validation passes."""
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

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "saved.json"
            page._target_path = lambda use_dialog: str(out)
            SequenceGeneratorPage._do_save(page, use_dialog=False)
            self.assertTrue(out.exists(), "expected sequence file to be written")
            round_trip = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(len(round_trip), 6)
        self.assertEqual(round_trip[0]["type"], "open_url")
        self.assertEqual(round_trip[-1]["type"], "full_reset")
        self.assertIn("Saved successfully", page._save_status_var.value or "")

    def test_save_blocks_when_validation_fails(self):
        """A failing validation must not silently overwrite a sequence file on disk."""
        page = SequenceGeneratorPage.__new__(SequenceGeneratorPage)
        page._steps = [{"type": "wait", "seconds": 1.0}]
        page._normalize_with_context = lambda steps: list(steps)
        page._validation_lines = lambda: (["fail"], False)
        page._save_status_var = _DummyVar()
        page._status_var = _DummyVar()
        page._status_lbl = SimpleNamespace(config=lambda **_kw: None)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "blocked.json"
            page._target_path = lambda use_dialog: str(out)
            SequenceGeneratorPage._do_save(page, use_dialog=False)

        self.assertFalse(out.exists())
        self.assertIn("Cannot save", page._save_status_var.value or "")

    def test_human_like_slow_scroll_uses_current_baseline(self):
        """Slow-scroll helper builds a ~2.1 s swipe stamped with the page baseline.

        With the human-timing toggle off, the swipe duration is exact (no Gaussian
        wobble). Pinning the precise ms is the cleanest way to assert that and
        also keep the test deterministic.
        """
        page = SequenceGeneratorPage.__new__(SequenceGeneratorPage)
        page._base_w_var = SimpleNamespace(get=lambda: 720)
        page._base_h_var = SimpleNamespace(get=lambda: 1280)
        page._human_timing_var = SimpleNamespace(get=lambda: False)

        swipe = SequenceGeneratorPage._human_slow_scroll_up(page)

        self.assertEqual(swipe["type"], "swipe")
        self.assertEqual(swipe["ms"], 2100)
        self.assertEqual(swipe["base_w"], 720)
        self.assertEqual(swipe["base_h"], 1280)
        self.assertGreater(swipe["y1"], swipe["y2"], "scrolling up means y1 > y2")

    def test_human_timing_toggle_jitters_swipe_duration(self):
        """Toggling natural-timing on adds bounded Gaussian wobble to swipe.ms."""
        page = SequenceGeneratorPage.__new__(SequenceGeneratorPage)
        page._base_w_var = SimpleNamespace(get=lambda: 900)
        page._base_h_var = SimpleNamespace(get=lambda: 1600)
        page._human_timing_var = SimpleNamespace(get=lambda: True)

        rng = random.Random(42)
        original_gauss = random.gauss
        try:
            random.gauss = rng.gauss
            samples = [
                SequenceGeneratorPage._swipe_step(page, 100, 200, 110, 210, 900)["ms"]
                for _ in range(40)
            ]
        finally:
            random.gauss = original_gauss

        self.assertGreater(len(set(samples)), 1, "human timing should vary swipe.ms run-to-run")
        for ms in samples:
            self.assertGreaterEqual(ms, 80)
            self.assertLessEqual(ms, 5000)

    def test_human_like_micro_wait_in_natural_band(self):
        """``_human_micro_wait_gap`` produces a wait inside the human_variation gap band."""
        page = SequenceGeneratorPage.__new__(SequenceGeneratorPage)
        rng = random.Random(0)
        original_uniform = random.uniform
        try:
            random.uniform = rng.uniform
            for _ in range(20):
                step = SequenceGeneratorPage._human_micro_wait_gap(page)
                self.assertEqual(step["type"], "wait")
                self.assertGreaterEqual(step["seconds"], 0.28)
                self.assertLessEqual(step["seconds"], 0.52)
        finally:
            random.uniform = original_uniform

    def test_human_like_arm_jitter_increments_and_caps_at_100(self):
        """Repeatedly arming the jitter boost should accumulate, then clamp at 100."""
        page = SequenceGeneratorPage.__new__(SequenceGeneratorPage)
        page._tap_jitter_boost_next = 0
        page._save_status_var = _DummyVar()

        SequenceGeneratorPage._human_arm_jitter_next_tap(page)
        self.assertEqual(page._tap_jitter_boost_next, 14)
        SequenceGeneratorPage._human_arm_jitter_next_tap(page)
        self.assertEqual(page._tap_jitter_boost_next, 28)

        page._tap_jitter_boost_next = 95
        SequenceGeneratorPage._human_arm_jitter_next_tap(page)
        self.assertEqual(page._tap_jitter_boost_next, 100)
        self.assertIn("extra randomness", page._save_status_var.value or "")

    def test_human_like_boost_selected_jitter_only_targets_taps(self):
        """Boosting selected jitter is a no-op on non-tap steps and bumps tap jitter otherwise."""
        page = SequenceGeneratorPage.__new__(SequenceGeneratorPage)
        page._steps = [
            {"type": "tap", "x": 100, "y": 200, "jitter": 20, "base_w": 900, "base_h": 1600},
            {"type": "wait", "seconds": 1.0},
        ]
        page._save_status_var = _DummyVar()
        page._normalize_with_context = lambda steps: list(steps)
        page._refresh_builder = lambda *_a, **_kw: None

        page._selected_index = lambda: 0
        SequenceGeneratorPage._human_boost_selected_tap_jitter(page)
        self.assertEqual(page._steps[0]["jitter"], 32)

        page._selected_index = lambda: 1
        SequenceGeneratorPage._human_boost_selected_tap_jitter(page)
        self.assertEqual(page._steps[0]["jitter"], 32, "tap jitter must not change when wait is selected")
        self.assertNotIn("jitter", page._steps[1])
        self.assertIn("not a tap", page._save_status_var.value or "")

        page._selected_index = lambda: None
        page._save_status_var = _DummyVar()
        SequenceGeneratorPage._human_boost_selected_tap_jitter(page)
        self.assertIn("Select a tap step", page._save_status_var.value or "")

    def test_human_timing_var_default_is_on(self):
        """The natural-timing toggle defaults to on so most users get human-like steps."""
        page = SequenceGeneratorPage.__new__(SequenceGeneratorPage)
        ctor_src = inspect.getsource(SequenceGeneratorPage.__init__)
        self.assertIn("self._human_timing_var = tk.BooleanVar(value=True)", ctor_src)
        # Sanity: the build screen ties the checkbox to that var.
        build_src = inspect.getsource(SequenceGeneratorPage._build_build_screen)
        self.assertIn("variable=self._human_timing_var", build_src)

    def test_url_vs_app_mode_toolbox_exposes_both(self):
        """The Navigation toolbox surfaces both the website and installed-app entry points.

        These two entries are the user-visible split between URL mode and App mode in
        the post-gate builder; if either disappears, the wizard silently loses a
        whole automation flavor.
        """
        nav = SequenceGeneratorPage._TOOLBOX.get("Navigation", {})
        self.assertIn("Open website", nav)
        self.assertIn("Launch installed app", nav)

    def test_load_app_sequence_routes_to_app_mode(self):
        """A sequence whose first action is ``launch_app`` lands in App mode.

        URL files set ``_target_kind='website'`` and copy the URL into ``_url_var``;
        App files must instead set ``_target_kind='app'`` and copy the package name
        into ``_package_var`` so the rest of the wizard treats it as an app run.
        """
        page = self._make_load_ready_page()
        app_doc = [
            {"type": "launch_app", "package": "com.example.target"},
            {"type": "tap", "x": 200, "y": 400, "base_w": 900, "base_h": 1600},
            {"type": "wait", "seconds": 1.5},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            seq_path = Path(tmp) / "app.json"
            seq_path.write_text(json.dumps(app_doc), encoding="utf-8")
            from tkinter import filedialog
            orig = filedialog.askopenfilename
            try:
                filedialog.askopenfilename = lambda **_kw: str(seq_path)
                SequenceGeneratorPage._load_file(page)
            finally:
                filedialog.askopenfilename = orig

        self.assertEqual(page._target_kind, "app")
        self.assertEqual(page._package_var.value, "com.example.target")
        self.assertIsNone(page._url_var.value, "URL should not be set for app sequences")
        self.assertEqual(page._phase_after_load, "builder")
        self.assertIn("App package in file: com.example.target", page._import_info_var.value)

    def test_browser_builder_reports_start_failure(self):
        orig_is_available = bbw.is_pywebview_available
        orig_validate_url = bbw.validate_url
        orig_try_load_url = bbw.try_load_url
        orig_run = bbw._run_webview_session
        try:
            bbw.is_pywebview_available = lambda: True
            bbw.validate_url = lambda _url: (True, "https://example.com")
            bbw.try_load_url = lambda _url: False

            def _raise(*_args, **_kwargs):
                raise RuntimeError("simulated startup failure")

            bbw._run_webview_session = _raise
            ok, err = bbw.launch_browser_builder("https://example.com", 900, 1600, lambda *_: None, lambda *_: None)
        finally:
            bbw.is_pywebview_available = orig_is_available
            bbw.validate_url = orig_validate_url
            bbw.try_load_url = orig_try_load_url
            bbw._run_webview_session = orig_run

        self.assertFalse(ok)
        self.assertEqual(err, bbw.ERR_START)
        self.assertIn("simulated startup failure", bbw.last_error())


if __name__ == "__main__":
    unittest.main()
