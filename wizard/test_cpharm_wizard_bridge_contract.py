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

    def test_run_actions_are_headless(self):
        """Deck Go actions must not wait on a background Tcl pump."""
        for fn in ("start_server", "run_all_groups", "start_automation_one_click"):
            block = BRIDGE.split("def %s(" % fn)[1].split("\ndef ")[0]
            self.assertNotIn("launch_page()", block)
            self.assertNotIn("_run_on_tk", block)
            self.assertNotIn("_safe_run_on_tk", block)
        self.assertIn("def _start_dashboard_headless(", BRIDGE)
        self.assertIn("already in progress", BRIDGE.split("def _boot_then_continue(")[1].split("\ndef ")[0])

    def test_run_all_groups_calls_boot_when_present(self):
        block = BRIDGE.split("def _begin_groups_run(")[1].split("\ndef ")[0]
        self.assertIn("_boot_then_continue", block)
        self.assertIn("_wait_for_boot_worker", block)
        self.assertIn("_run_groups_on_dashboard", block)
        start = BRIDGE.split("def start_server(")[1].split("\ndef ")[0]
        self.assertIn("_begin_service_start", start)
        begin = BRIDGE.split("def _begin_service_start(")[1].split("\ndef ")[0]
        self.assertIn('"starting": True', begin)
        self.assertNotIn("return {\"ok\": True, \"started\": True}", begin)

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


class HeadlessDeckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        import sys

        root = Path(__file__).resolve().parents[1]
        wizard_dir = str(root / "wizard")
        if wizard_dir not in sys.path:
            sys.path.insert(0, wizard_dir)
        bridge_path = root / "wizard" / "cpharm_wizard_bridge.py"
        spec = importlib.util.spec_from_file_location("cpharm_wizard_bridge_headless", bridge_path)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def test_navigation_does_not_start_tk_thread(self):
        import threading

        out = self.mod.navigate_wizard_page(3)
        self.assertTrue(out.get("ok"))
        self.assertFalse(out.get("tk"))
        names = {t.name for t in threading.enumerate()}
        self.assertNotIn("cpharm-tk-bridge", names)

    def test_site_and_android_status_are_immediate(self):
        import time

        t0 = time.monotonic()
        site = self.mod.get_site_settings()
        android = self.mod.get_android_status()
        self.assertLess(time.monotonic() - t0, 15)
        self.assertIn("url", site)
        self.assertIn("ready", android)
        self.assertTrue(android.get("ok"))

    def test_live_boot_is_not_a_failure(self):
        import threading
        import time

        assert self.mod._boot_all_lock.acquire(blocking=False)
        worker = threading.Thread(target=lambda: time.sleep(30), daemon=True)
        worker.start()
        self.mod._boot_all_thread = worker
        self.mod._boot_all_started_mono = time.monotonic()
        try:
            out = self.mod.boot_all_phones()
            self.assertTrue(out.get("ok"))
            self.assertTrue(out.get("already_booting"))
            self.assertNotIn("error", out)
        finally:
            self.mod._boot_all_cancel.set()
            try:
                self.mod._boot_all_lock.release()
            except RuntimeError:
                pass

    def test_fix_internet_repins_exits_instead_of_clearing_proxy(self):
        block = BRIDGE.split("def fix_phone_internet(")[1].split("\ndef ")[0]
        self.assertNotIn("wiz_clear_phone_proxies_best_effort(", block)
        self.assertIn("heal_inject_and_tor(live=", block)

        calls: list[str] = []

        def connect():
            calls.append("connect")
            return ["connected"]

        def live():
            return ["10.0.2.1:5555"]

        def heal(*, live):
            calls.append("heal:" + ",".join(live))
            return ["repinned"]

        import automation.farm_exe_self_heal as heal_mod

        orig = (
            heal_mod.connect_live_fleet,
            heal_mod.adb_live_serials,
            heal_mod.heal_inject_and_tor,
        )
        heal_mod.connect_live_fleet = connect
        heal_mod.adb_live_serials = live
        heal_mod.heal_inject_and_tor = heal
        try:
            out = self.mod.fix_phone_internet()
        finally:
            (
                heal_mod.connect_live_fleet,
                heal_mod.adb_live_serials,
                heal_mod.heal_inject_and_tor,
            ) = orig
        self.assertIn("--cloud-agent", (ROOT / "wizard" / "cpharm_desktop.py").read_text(encoding="utf-8"))
        agent = BRIDGE.split("def agent_status(")[1].split("\ndef ")[0]
        self.assertNotIn('"--count"', agent)
        self.assertNotIn("sys.executable", agent)
        cloud = BRIDGE.split("def run_cloud_agent(")[1].split("\ndef ")[0]
        self.assertIn("--cloud-agent", cloud)
        self.assertEqual(calls, ["connect", "heal:10.0.2.1:5555"])
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("n"), 1)
        self.assertNotIn("error", out)

    def test_control_panel_open_does_not_reap_and_python_is_probed(self):
        webview = (ROOT / "wizard" / "cpharm_app_webview.py").read_text(encoding="utf-8")
        self.assertNotIn("run_startup_cleanup(", webview)
        host = BRIDGE.split("def _host_python_argv(")[1].split("\ndef ")[0]
        self.assertNotIn('return ["python"]', host)
        self.assertIn("return [], \"\"", host)
        deck = (ROOT / "wizard" / "assets" / "cpharm_app" / "app.js").read_text(encoding="utf-8")
        banner = deck.split("function showBackendError")[1].split("function requireApi")[0]
        self.assertIn("connectionMissing", banner)
        self.assertNotIn("if (dashConnected) {\n      el.hidden = true;", banner)

    def test_service_start_failure_is_visible_to_the_poll(self):
        import time

        self.mod._service_start_result.clear()
        self.mod._service_start_result.update({"ok": True, "starting": False})

        def boom() -> dict:
            return {"ok": False, "error": "no interpreter"}

        orig = self.mod._start_dashboard_headless
        self.mod._start_dashboard_headless = boom
        status: dict = {}
        try:
            out = self.mod.start_server()
            self.assertTrue(out.get("starting"))
            deadline = time.time() + 5
            while time.time() < deadline:
                status = self.mod.is_dashboard_ready()
                if status.get("ok") is False:
                    break
                time.sleep(0.05)
        finally:
            self.mod._start_dashboard_headless = orig
        self.assertFalse(status.get("ok"))
        self.assertIn("no interpreter", str(status.get("error")))


if __name__ == "__main__":
    unittest.main()
