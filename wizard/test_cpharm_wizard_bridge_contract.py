import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = (ROOT / "wizard" / "cpharm_wizard_bridge.py").read_text(encoding="utf-8-sig")


class CPharmWizardBridgeContractTests(unittest.TestCase):
    def test_cursor_sequence_endpoints_exist(self):
        for name in (
            "cursor_get_sequence",
            "cursor_add_step",
            "cursor_update_step",
            "cursor_remove_step",
            "cursor_move_step",
        ):
            self.assertIn(f"def {name}(", BRIDGE)

    def test_cursor_group_endpoints_exist(self):
        for name in ("cursor_add_group", "cursor_remove_group", "cursor_rename_group"):
            self.assertIn(f"def {name}(", BRIDGE)

    def test_deck_builder_and_groups_are_headless(self):
        for fn in ("open_sequence_builder", "open_groups_manager"):
            block = BRIDGE.split("def %s(" % fn)[1].split("\ndef ")[0]
            self.assertIn('"deck"', block)
            self.assertNotIn("_open_wizard_page_window", block)
            self.assertNotIn("_spawn_with_visible_fallback", block)

    def test_run_actions_use_hidden_launch_page(self):
        for fn in ("start_server", "run_all_groups", "start_automation_one_click"):
            block = BRIDGE.split("def %s(" % fn)[1].split("\ndef ")[0]
            self.assertIn("launch_page()", block)
            self.assertNotIn("_open_wizard_page_window(8", block)

    def test_run_all_groups_calls_boot_when_present(self):
        block = BRIDGE.split("def run_all_groups(")[1].split("\ndef ")[0]
        self.assertIn("boot_all_phones", block)
        self.assertIn("page._run_groups()", block)

    def test_boot_all_phones_exists(self):
        self.assertIn("def boot_all_phones(", BRIDGE)

    def test_spawn_helper_still_surfaces_errors(self):
        """_spawn_with_visible_fallback remains for any leftover spawn callers."""
        self.assertIn("_spawn_with_visible_fallback", BRIDGE)
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
            out = mod._spawn_with_visible_fallback(6, fallback=lambda: {"ok": True})
            self.assertIn("error", out, "spawn failure must set an error key")
            self.assertIn("Spawn failed: mock spawn boom", out["error"])
            self.assertTrue(out.get("ok", False), "in-process fallback should still succeed")

            out2 = mod._spawn_with_visible_fallback(7, fallback=lambda: {"ok": False, "error": "fb die"})
            self.assertIn("Spawn failed: mock spawn boom", out2["error"])
            self.assertIn("fb die", out2["error"])
            self.assertFalse(out2["ok"])

            mod._spawn_wizard_page = lambda _idx, **kw: {"ok": True, "spawned": True}
            out3 = mod._spawn_with_visible_fallback(
                8,
                action="start_server",
                success_augment={"started": True},
                fallback=lambda: {"ok": True},
            )
            self.assertTrue(out3.get("spawned"))
            self.assertEqual(out3.get("started"), True)
            self.assertNotIn("error", out3)
        finally:
            mod._spawn_wizard_page = original_spawn


if __name__ == "__main__":
    unittest.main()
