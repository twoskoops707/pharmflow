import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = (ROOT / "wizard" / "cpharm_wizard_bridge.py").read_text(encoding="utf-8-sig")


class CPharmWizardBridgeContractTests(unittest.TestCase):
    def test_sequence_editor_waits_on_dialog(self):
        self.assertIn("dlg.grab_set()", BRIDGE)
        self.assertIn("dlg.wait_window()", BRIDGE)
        self.assertNotIn("parent.wait_window(dlg)", BRIDGE)

    def test_page_windows_are_visible_and_reused(self):
        self.assertIn("_page_windows[page_index] = win", BRIDGE)
        self.assertIn("_show_tk_window(win)", BRIDGE)
        self.assertIn("_open_wizard_page_window(6", BRIDGE)
        self.assertIn("_open_wizard_page_window(7", BRIDGE)

    def test_run_actions_use_visible_run_page(self):
        self.assertIn("_open_wizard_page_window(8", BRIDGE)
        self.assertIn("page._run_groups()", BRIDGE)
        self.assertIn("page._start_automation_one_click()", BRIDGE)

    def test_spawn_failure_is_surfaced_not_silent(self):
        # When the separate-process launch fails, the returned dict must carry an
        # "error" so the WebView shows a visible banner instead of failing silently.
        self.assertIn("_spawn_with_visible_fallback", BRIDGE)
        self.assertTrue(BRIDGE.count("success_augment") >= 4, "page-8 actions should augment success")
        # Guard the regression: no caller should swallow a failed spawn without an error key.
        import re
        for fn in ("open_sequence_builder", "open_groups_manager", "start_server"):
            block = BRIDGE.split("def %s(" % fn)[1].split("\ndef ")[0]
            self.assertIn("_spawn_with_visible_fallback", block)

    def test_spawn_failure_returns_error_dict(self):
        """Behavioral: a failed spawn surfaces in the returned dict."""
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        bridge_path = root / "wizard" / "cpharm_wizard_bridge.py"
        if not bridge_path.is_file():
            self.skipTest("bridge source not present")
        try:
            import sys
            import importlib.util
            import io
            import contextlib
            wizard_dir = str(root / "wizard")
            if wizard_dir not in sys.path:
                sys.path.append(wizard_dir)
            spec = importlib.util.spec_from_file_location("cpharm_wizard_bridge_test", bridge_path)
            mod = importlib.util.module_from_spec(spec)
            with contextlib.redirect_stderr(io.StringIO()):
                spec.loader.exec_module(mod)
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"bridge import skipped: {exc}")

        def _fail_spawn(_idx, **kw):
            return {"ok": False, "error": "mock spawn boom"}

        original_spawn = mod._spawn_wizard_page
        try:
            mod._spawn_wizard_page = _fail_spawn
            # Failed spawn + successful fake fallback -> error key surfaced, ok stays True.
            out = mod._spawn_with_visible_fallback(6, fallback=lambda: {"ok": True})
            self.assertIn("error", out, "spawn failure must set an error key")
            self.assertIn("Spawn failed: mock spawn boom", out["error"])
            self.assertTrue(out.get("ok", False), "in-process fallback should still succeed")

            # Failed spawn + failed fallback -> error carries spawn failure and fallback failure.
            out2 = mod._spawn_with_visible_fallback(7, fallback=lambda: {"ok": False, "error": "fb die"})
            self.assertIn("Spawn failed: mock spawn boom", out2["error"])
            self.assertIn("fb die", out2["error"])
            self.assertFalse(out2["ok"])

            # Successful spawn -> returned as-is with augment, no error.
            mod._spawn_wizard_page = lambda _idx, **kw: {"ok": True, "spawned": True}
            out3 = mod._spawn_with_visible_fallback(8, action="start_server",
                                                    success_augment={"started": True},
                                                    fallback=lambda: {"ok": True})
            self.assertTrue(out3.get("spawned"))
            self.assertEqual(out3.get("started"), True)
            self.assertNotIn("error", out3)
        finally:
            mod._spawn_wizard_page = original_spawn


if __name__ == "__main__":
    unittest.main()
