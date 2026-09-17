import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = (ROOT / "wizard" / "pharmflow_wizard_bridge.py").read_text(encoding="utf-8-sig")


class PharmFlowWizardBridgeContractTests(unittest.TestCase):
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

    def test_groups_detail_remaps_stale_serials_to_live_adb(self):
        """E06: Groups must adopt live ADB like dashboard run-all-groups, not exact ∩ only."""
        block = BRIDGE.split("def _groups_detail_from_state(")[1].split("\ndef ")[0]
        self.assertIn("remap_groups_phones_to_live", block)
        self.assertIn("_persist_groups_config", block)
        self.assertIn("from wizard_paths import remap_groups_phones_to_live", BRIDGE)

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
        bridge_path = root / "wizard" / "pharmflow_wizard_bridge.py"
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
            spec = importlib.util.spec_from_file_location("pharmflow_wizard_bridge_test", bridge_path)
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
        bridge_path = root / "wizard" / "pharmflow_wizard_bridge.py"
        spec = importlib.util.spec_from_file_location("pharmflow_wizard_bridge_headless", bridge_path)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def setUp(self) -> None:
        self._reset_boot_worker()

    def tearDown(self) -> None:
        self._reset_boot_worker()

    def _reset_boot_worker(self) -> None:
        """Boot tests must not leave the process-wide boot lock held."""
        mod = self.mod
        thr = getattr(mod, "_boot_all_thread", None)
        if thr is not None and thr.is_alive():
            try:
                mod._boot_all_cancel.set()
            except Exception:
                pass
            thr.join(5)
        mod._boot_all_thread = None
        mod._boot_all_started_mono = None
        lock = mod._boot_all_lock
        # Drain a stuck lock so the next test can acquire cleanly.
        if not lock.acquire(blocking=False):
            try:
                lock.release()
            except RuntimeError:
                pass
            if not lock.acquire(blocking=False):
                return
        try:
            lock.release()
        except RuntimeError:
            pass
        try:
            mod._boot_all_cancel.clear()
        except Exception:
            pass

    def test_arm_guest_is_mumu_only_when_state_json_published_it(self):
        kind = self.mod._adb_phone_kind
        guests = self.mod._mumu_guest_serials({"vm0": "10.0.2.15:5555", "vm1": "127.0.0.1:16384"})
        self.assertEqual(
            kind("10.0.2.15:5555", mumu_serials=guests, redroid_ports=set()),
            "MuMu",
        )
        self.assertEqual(
            kind("10.0.2.99:5555", mumu_serials=guests, redroid_ports=set()),
            "emu/TCP",
        )
        self.assertEqual(
            kind("127.0.0.1:16001", mumu_serials=set(), redroid_ports={16001}),
            "redroid",
        )
        self.assertNotIn("10.0.2.2", guests)

    def test_inventory_does_not_count_every_adb_phone_as_mumu(self):
        src = (ROOT / "wizard" / "pharmflow_wizard_bridge.py").read_text(encoding="utf-8")
        body = src.split("def get_machine_capabilities", 1)[1].split("\ndef ", 1)[0]
        self.assertNotIn("enumerate_adb_devices", body)
        self.assertIn("_mumu_guest_serials", body)
        self.assertIn('out["docker"] = True', body)
        js = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        self.assertIn("phone(s) answering ADB", js)
        self.assertNotIn("the farm can adopt", js)

    def test_run_test_url_opens_every_live_phone(self):
        import unittest.mock

        import setup_wizard as sw

        phones = [
            {"serial": "10.0.2.2:5555", "name": "A"},
            {"serial": "10.0.2.3:5555", "name": "B"},
        ]
        seen: list[str] = []

        def fake_open(serial, url):
            seen.append(str(serial))
            return url.endswith("/ok") or serial.endswith("2:5555"), ""

        prev = list(sw.state.get("phones") or [])
        try:
            sw.state["phones"] = phones
            with unittest.mock.patch.object(self.mod, "_prepare_editor_state"), \
                 unittest.mock.patch.object(sw, "chrome_open_url", fake_open), \
                 unittest.mock.patch("site_prefs.save_target_site_url"), \
                 unittest.mock.patch("site_prefs.load_target_site_url", return_value=""):
                out = self.mod.run_test_url("https://getdabflow.app/ok")
        finally:
            sw.state["phones"] = prev
        self.assertEqual(seen, ["10.0.2.2:5555", "10.0.2.3:5555"])
        self.assertEqual(out.get("opened"), 2)
        self.assertTrue(out.get("ok"))

    def test_navigation_does_not_start_tk_thread(self):
        import threading

        out = self.mod.navigate_wizard_page(3)
        self.assertTrue(out.get("ok"))
        self.assertFalse(out.get("tk"))
        names = {t.name for t in threading.enumerate()}
        self.assertNotIn("pharmflow-tk-bridge", names)

    def test_android_ready_is_not_mumu_selected(self):
        import unittest.mock

        import setup_wizard as sw

        prev_mumu = sw.state.get("use_mumu")
        prev_sdk = sw.state.get("sdk_path")
        sw.state["use_mumu"] = True
        sw.state["sdk_path"] = ""
        try:
            with unittest.mock.patch.object(sw, "find_sdk", return_value=""), unittest.mock.patch.object(
                sw, "sdk_tool", return_value=r"C:\missing\adb.exe"
            ):
                status = self.mod.get_android_status()
        finally:
            sw.state["use_mumu"] = prev_mumu
            sw.state["sdk_path"] = prev_sdk
        self.assertFalse(status.get("ready"))
        self.assertNotEqual(status.get("status"), "Ready")
        self.assertIn("SDK not installed", status.get("status") or "")
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            plat = Path(tmp) / "platform-tools"
            plat.mkdir()
            with unittest.mock.patch.object(sw, "find_sdk", return_value=tmp), unittest.mock.patch.object(
                sw, "sdk_tool", return_value=str(plat / "adb.exe")
            ):
                folder_only = self.mod.get_android_status()
        self.assertFalse(folder_only.get("ready"))
        self.assertNotEqual(folder_only.get("status"), "Ready")
        bridge_src = (ROOT / "wizard" / "pharmflow_wizard_bridge.py").read_text(encoding="utf-8")
        self.assertNotIn("min(90.0, float(_dashboard_ready_timeout_sec()))", bridge_src)
        wizard = (ROOT / "wizard" / "setup_wizard.py").read_text(encoding="utf-8")
        self.assertNotIn("Google has no Windows ARM64 emulator", wizard)
        self.assertIn("emulator.exe is not an ARM64 binary. Starting anyway.", wizard)
        bridge = (ROOT / "wizard" / "pharmflow_wizard_bridge.py").read_text(encoding="utf-8")
        load = bridge.split("def load_sequence_from_path(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("That file has no steps.", load)

    def test_empty_sequence_file_is_not_a_load(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.json"
            path.write_text("[]", encoding="utf-8")
            out = self.mod.load_sequence_from_path(str(path))
        self.assertFalse(out.get("ok"))
        self.assertIn("no steps", (out.get("error") or "").lower())

    def test_site_and_android_status_are_immediate(self):
        import time

        t0 = time.monotonic()
        site = self.mod.get_site_settings()
        android = self.mod.get_android_status()
        self.assertLess(time.monotonic() - t0, 15)
        self.assertIn("url", site)
        self.assertIn("ready", android)
        self.assertTrue(android.get("ok"))

    def test_cloud_command_failure_is_visible_to_the_poll(self):
        import io
        import time
        import unittest.mock

        class _Proc:
            def __init__(self) -> None:
                self.returncode = 2
                self.stdout = io.StringIO("cloud boom\n")

            def wait(self) -> int:
                return self.returncode

        with unittest.mock.patch.object(self.mod.subprocess, "Popen", return_value=_Proc()):
            out = self.mod.run_cloud_phone_command("status", "", 0)
            self.assertTrue(out.get("starting"))
            status: dict = {}
            deadline = time.time() + 5
            while time.time() < deadline:
                status = self.mod.cloud_command_status()
                if status.get("starting") is False:
                    break
                time.sleep(0.05)
            thr = self.mod._cloud_thread
            if thr is not None:
                thr.join(2)
        self.assertFalse(status.get("ok"))
        self.assertFalse(status.get("starting"))
        self.assertIn("exit 2", str(status.get("error")))

    def test_boot_with_no_instances_is_visible_to_the_poll(self):
        import time
        import types
        import unittest.mock

        import setup_wizard as sw

        fleet = types.ModuleType("farm_canonical_phones")
        fleet.canonical_names_sorted = lambda: []
        fleet.canonical_serials_sorted = lambda: []
        fleet.disk_fleet_map = lambda: {}
        fleet.disk_fleet_names_sorted = lambda: []
        fleet.is_banned_phone = lambda _name: False
        cli = types.ModuleType("mumu_shell_cli")
        cli.instance_shell_running = lambda _idx: False

        def _must_not_launch(*_a, **_k):
            raise AssertionError("boot must not launch a VM when no instances exist")

        cli.launch_instance_index = _must_not_launch
        with unittest.mock.patch.object(sw, "_find_mumu_manager", return_value=None), \
             unittest.mock.patch.object(self.mod, "_redroid_rows", return_value=[]), \
             unittest.mock.patch.object(
                 self.mod, "_boot_stopped_avds", return_value={"found": 0, "started": [], "already": [], "failed": []}
             ), \
             unittest.mock.patch.dict(
                 "sys.modules",
                 {
                     "automation.farm_canonical_phones": fleet,
                     "automation.mumu_shell_cli": cli,
                 },
             ):
            out = self.mod.boot_all_phones()
            self.assertTrue(out.get("started"))
            status: dict = {}
            deadline = time.time() + 8
            while time.time() < deadline:
                status = self.mod.boot_all_status()
                if status.get("starting") is False and status.get("ok") is False:
                    break
                time.sleep(0.05)
            thr = self.mod._boot_all_thread
            if thr is not None:
                thr.join(2)
        self.assertFalse(status.get("ok"))
        self.assertFalse(status.get("starting"))
        self.assertIn("No MuMu", str(status.get("error")))

    def test_boot_starts_stopped_redroid_on_the_published_port(self):
        import time
        import types
        import unittest.mock

        import setup_wizard as sw

        fleet = types.ModuleType("farm_canonical_phones")
        fleet.canonical_names_sorted = lambda: []
        fleet.canonical_serials_sorted = lambda: []
        fleet.disk_fleet_map = lambda: {}
        fleet.disk_fleet_names_sorted = lambda: []
        fleet.is_banned_phone = lambda _name: False
        cli = types.ModuleType("mumu_shell_cli")
        cli.instance_shell_running = lambda _idx: False
        cli.launch_instance_index = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("must not launch MuMu when only redroid is stopped")
        )
        rows = [
            {"name": "redroid-3", "up": False, "ports": []},
            {"name": "redroid-3", "up": True, "ports": ["127.0.0.1:16001"]},
        ]
        connected: list[str] = []

        def _rows():
            return [rows.pop(0)] if rows else [{"name": "redroid-3", "up": True, "ports": ["127.0.0.1:16001"]}]

        def _adb(*args, serial=None, timeout=8):
            if args and args[0] == "connect":
                connected.append(args[1])
                return "connected"
            if serial == "127.0.0.1:16001":
                return "ok"
            return ""

        with unittest.mock.patch.object(sw, "_find_mumu_manager", return_value=None), \
             unittest.mock.patch.object(self.mod, "_redroid_rows", side_effect=_rows), \
             unittest.mock.patch.object(
                 self.mod, "_boot_stopped_avds", return_value={"found": 0, "started": [], "already": [], "failed": []}
             ), \
             unittest.mock.patch.object(self.mod, "_docker_start_named", return_value=(0, "")), \
             unittest.mock.patch.object(sw, "adb", side_effect=_adb), \
             unittest.mock.patch.dict(
                 "sys.modules",
                 {
                     "automation.farm_canonical_phones": fleet,
                     "automation.mumu_shell_cli": cli,
                 },
             ):
            out = self.mod.boot_all_phones()
            self.assertTrue(out.get("started"))
            status: dict = {}
            deadline = time.time() + 8
            while time.time() < deadline:
                status = self.mod.boot_all_status()
                if status.get("starting") is False:
                    break
                time.sleep(0.05)
            thr = self.mod._boot_all_thread
            if thr is not None:
                thr.join(2)
        self.assertTrue(status.get("ok"), status)
        self.assertEqual(status.get("redroid_started"), 1)
        self.assertIn("127.0.0.1:16001", connected)
        self.assertNotIn("127.0.0.1:5558", connected)

    def test_boot_launches_a_stopped_avd_without_wiping_it(self):
        argv = self.mod._avd_launch_argv(r"C:\sdk\emulator\emulator.exe", "Pixel_Test")
        self.assertIn("-avd", argv)
        self.assertIn("Pixel_Test", argv)
        self.assertNotIn("-wipe-data", argv)

        import time
        import types
        import unittest.mock

        import setup_wizard as sw

        fleet = types.ModuleType("farm_canonical_phones")
        fleet.canonical_names_sorted = lambda: []
        fleet.canonical_serials_sorted = lambda: []
        fleet.disk_fleet_map = lambda: {}
        fleet.disk_fleet_names_sorted = lambda: []
        fleet.is_banned_phone = lambda _name: False
        cli = types.ModuleType("mumu_shell_cli")
        cli.instance_shell_running = lambda _idx: False
        launched: list[str] = []

        def _launch(emu: str, name: str) -> None:
            launched.append(name)
            if "-wipe-data" in self.mod._avd_launch_argv(emu, name):
                raise AssertionError("AVD launch must not wipe the data disk")

        with unittest.mock.patch.object(sw, "_find_mumu_manager", return_value=None), \
             unittest.mock.patch.object(self.mod, "_redroid_rows", return_value=[]), \
             unittest.mock.patch.object(sw, "list_avds", return_value=["Pixel_Test"]), \
             unittest.mock.patch.object(sw, "sdk_tool", return_value=__file__), \
             unittest.mock.patch.object(self.mod, "_running_avd_names", return_value=set()), \
             unittest.mock.patch.object(self.mod.boot_gate, "wait_for_boot_headroom", return_value=True), \
             unittest.mock.patch.object(self.mod, "_emulator_serials", return_value=set()), \
             unittest.mock.patch.object(self.mod, "_wait_new_emulator_serial", return_value="emulator-5554"), \
             unittest.mock.patch.object(sw, "wait_for_boot", return_value=True), \
             unittest.mock.patch.object(self.mod, "_launch_avd_process", side_effect=_launch), \
             unittest.mock.patch.dict(
                 "sys.modules",
                 {
                     "automation.farm_canonical_phones": fleet,
                     "automation.mumu_shell_cli": cli,
                 },
             ):
            out = self.mod.boot_all_phones()
            self.assertTrue(out.get("started"))
            status: dict = {}
            deadline = time.time() + 8
            while time.time() < deadline:
                status = self.mod.boot_all_status()
                if status.get("starting") is False:
                    break
                time.sleep(0.05)
            thr = self.mod._boot_all_thread
            if thr is not None:
                thr.join(2)
        self.assertTrue(status.get("ok"), status)
        self.assertEqual(status.get("avd_started"), 1)
        self.assertEqual(launched, ["Pixel_Test"])

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
        self.assertIn("_exits_after_heal(", block)
        exits = BRIDGE.split("def _exits_after_heal(")[1].split("\ndef ")[0]
        self.assertIn("guest_proxy_healthy", exits)

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
        import setup_wizard as sw

        orig_read = sw._wiz_read_guest_proxy
        sw._wiz_read_guest_proxy = lambda _serial: "127.0.0.1:8118"
        try:
            out = self.mod.fix_phone_internet()
            sw._wiz_read_guest_proxy = lambda _serial: ":0"
            refused = self.mod.fix_phone_internet()
        finally:
            sw._wiz_read_guest_proxy = orig_read
            (
                heal_mod.connect_live_fleet,
                heal_mod.adb_live_serials,
                heal_mod.heal_inject_and_tor,
            ) = orig
        self.assertIn("--cloud-agent", (ROOT / "wizard" / "pharmflow_desktop.py").read_text(encoding="utf-8"))
        agent = BRIDGE.split("def agent_status(")[1].split("\ndef ")[0]
        self.assertNotIn('"--count"', agent)
        self.assertNotIn("sys.executable", agent)
        cloud = BRIDGE.split("def run_cloud_agent(")[1].split("\ndef ")[0]
        self.assertIn("--cloud-agent", cloud)
        self.assertEqual(
            calls,
            ["connect", "heal:10.0.2.1:5555", "connect", "heal:10.0.2.1:5555"],
        )
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("n"), 1)
        self.assertNotIn("error", out)
        self.assertFalse(refused.get("ok"))
        self.assertIn("Exit still missing", refused.get("error") or "")

    def test_control_panel_open_does_not_reap_and_python_is_probed(self):
        webview = (ROOT / "wizard" / "pharmflow_app_webview.py").read_text(encoding="utf-8")
        self.assertNotIn("run_startup_cleanup(", webview)
        host = BRIDGE.split("def _host_python_argv(")[1].split("\ndef ")[0]
        self.assertNotIn('return ["python"]', host)
        self.assertIn("return [], \"\"", host)
        deck = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
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

    def test_poll_keeps_whether_the_browser_opened(self):
        prev = dict(self.mod._service_start_result)
        try:
            self.mod._service_start_result.clear()
            self.mod._service_start_result.update(
                {"ok": True, "starting": False, "ready": True, "dashboard_opened": True}
            )
            opened = self.mod.is_dashboard_ready()
            self.assertTrue(opened.get("dashboard_opened"))
            self.mod._service_start_result["dashboard_opened"] = False
            closed = self.mod.is_dashboard_ready()
            self.assertFalse(closed.get("dashboard_opened"))
        finally:
            self.mod._service_start_result.clear()
            self.mod._service_start_result.update(prev)


class ListApiErrorTests(unittest.TestCase):
    def test_failed_check_is_not_an_empty_list(self):
        import sys
        from pathlib import Path

        wizard = Path(__file__).resolve().parent
        if str(wizard) not in sys.path:
            sys.path.insert(0, str(wizard))
        from pharmflow_app_webview import _items_or_raise

        with self.assertRaises(RuntimeError):
            _items_or_raise({"ok": False, "error": "adb down"}, "Prerequisite check")
        self.assertEqual(_items_or_raise({"ok": True, "items": []}, "Prerequisite check"), [])


class FarmHudSourceTests(unittest.TestCase):
    def test_hud_money_comes_from_operator_status_not_relative_logs(self):
        block = BRIDGE.split("def get_farm_hud(")[1].split("\ndef ")[0]
        self.assertIn("_operator_status()", block)
        self.assertIn("_mantis_today_file()", block)
        self.assertIn("_status_farm_process_alive", block)
        self.assertNotIn("_live_farm_facts", block)
        # Do not call the display-only farm_running() shortcut from the HUD.
        # Substring "farm_running" also appears inside external_python_farm_running.
        self.assertNotIn("farm_running(", block)
        self.assertNotIn("import farm_running", block)
        self.assertNotIn('status.get("farm_alive")', block)

    def test_hud_running_requires_a_worker_process(self):
        import sys
        from pathlib import Path

        wizard = Path(__file__).resolve().parent
        if str(wizard) not in sys.path:
            sys.path.insert(0, str(wizard))
        from pharmflow_wizard_bridge import _status_farm_process_alive

        self.assertTrue(
            _status_farm_process_alive(
                {"farm_alive": False, "processes": [{"cmd": "python run_farm_354.py"}]}
            )
        )
        self.assertFalse(
            _status_farm_process_alive(
                {
                    "farm_alive": True,
                    "farm_owner": "PharmFlow.exe",
                    "processes": [{"cmd": "C:\\PharmFlow\\PharmFlow.exe"}],
                }
            )
        )
        self.assertIsNone(_status_farm_process_alive({"farm_alive": True}))

    def test_hud_maps_operator_money_and_ignores_a_stale_file(self):
        import json
        import os
        import sys
        import tempfile
        from datetime import datetime
        from pathlib import Path
        from zoneinfo import ZoneInfo

        wizard = Path(__file__).resolve().parent
        if str(wizard) not in sys.path:
            sys.path.insert(0, str(wizard))
        from pharmflow_wizard_bridge import _hud_money_from_mantis, _mantis_today_file

        today = datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
        self.assertIsNone(
            _hud_money_from_mantis(
                {"payout_usd": 99, "clicks": 9, "impressions": 9, "date": "2000-01-01"},
                source="operator_status",
            )
        )
        self.assertIsNone(
            _hud_money_from_mantis(
                {"payout_usd": 12.5, "clicks": 4, "impressions": 800},
                source="operator_status",
            )
        )
        mapped = _hud_money_from_mantis(
            {"payout_usd": 12.5, "clicks": 4, "impressions": 800, "ecpm": 15.62, "date": today},
            source="operator_status",
        )
        self.assertIsNotNone(mapped)
        assert mapped is not None
        self.assertEqual(mapped["revenue_today_usd"], 12.5)
        self.assertEqual(mapped["clicks"], 4)
        self.assertEqual(mapped["money_source"], "operator_status")

        today = datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mantis_today_state.json"
            path.write_text(
                json.dumps({"date": "2000-01-01", "payout_usd": 99, "clicks": 9, "impressions": 9}),
                encoding="utf-8",
            )
            old = os.environ.get("PHARMFLOW_LOG_DIR")
            os.environ["PHARMFLOW_LOG_DIR"] = tmp
            try:
                self.assertIsNone(_mantis_today_file())
                path.write_text(
                    json.dumps(
                        {
                            "date": today,
                            "payout_usd": 3.25,
                            "clicks": 2,
                            "impressions": 100,
                            "ecpm": 32.5,
                        }
                    ),
                    encoding="utf-8",
                )
                live = _mantis_today_file()
            finally:
                if old is None:
                    os.environ.pop("PHARMFLOW_LOG_DIR", None)
                else:
                    os.environ["PHARMFLOW_LOG_DIR"] = old
        self.assertIsNotNone(live)
        assert live is not None
        self.assertEqual(live["revenue_today_usd"], 3.25)
        self.assertEqual(live["money_source"], "mantis_today_state")


class RunStepDoesNotRewriteBrowseModeTests(unittest.TestCase):
    def test_opening_run_does_not_save_scramble(self):
        js = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        block = js.split("async function refreshGo()")[1].split("function pct(")[0]
        self.assertNotIn("save_browse_mode", block)
        self.assertNotIn("Ready to launch", block)
        self.assertIn("Could not load the run summary", block)

    def test_start_poll_does_not_treat_a_log_as_a_running_farm(self):
        js = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        block = js.split("async function pollFarmStart(")[1].split("async function pollServiceStart(")[0]
        self.assertNotIn("st.external", block)
        self.assertIn("st.running && !st.starting", block)
        self.assertNotIn("lanes are live", block)
        self.assertIn("st.dashboard_ready === true", block)
        status = BRIDGE.split("def farm_status_from_app(")[1].split("\ndef ")[0]
        self.assertIn("operator_dashboard_listening", status)
        self.assertIn("farm_process_alive", status)
        self.assertNotIn("import farm_running", status)
        hud = js.split("async function refreshHud()")[1].split("function startHudPoll(")[0]
        self.assertNotIn("h.external", hud)
        self.assertNotIn("farm_alive", hud)
        self.assertIn("function farmWorkerUp", js)

    def test_blank_browse_mode_is_rejected(self):
        block = BRIDGE.split("def save_browse_mode(")[1].split("\ndef ")[0]
        self.assertNotIn('or "scramble"', block)
        self.assertIn("Browse mode must be", block)


class CheckAndHumanizeHonestyTests(unittest.TestCase):
    def test_phone_checks_do_not_toast_complete_on_a_failed_checklist(self):
        js = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        block = js.split("async function refreshSetup(")[1].split("async function refreshJourney(")[0]
        self.assertNotIn("Phone checks complete", block)
        self.assertIn('item.status === "fail"', block)
        self.assertIn("no phones answering ADB", block)

    def test_dashboard_button_does_not_claim_opened_unless_the_browser_opened(self):
        js = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        block = js.split("async function openFarmDash()")[1].split("if (btnStartHome")[0]
        self.assertNotIn("if (res) showToast", block)
        self.assertIn("res.opened !== true", block)
        self.assertIn("did not open in the browser", block)

    def test_deck_copy_does_not_say_the_exe_never_starts_phones(self):
        html = (ROOT / "wizard" / "assets" / "pharmflow_app" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("never opens or closes emulators", html)
        self.assertNotIn("never boots or closes", html)
        self.assertNotIn("never forces a specific emulator", html)
        self.assertNotIn("startup cleanup only clears", html)
        self.assertIn("This button does not boot phones", html)
        self.assertIn("started when you ask", html)

    def test_no_phones_message_does_not_claim_the_program_cannot_start_mumu(self):
        text = (ROOT / "wizard" / "mumu_setup_core.py").read_text(encoding="utf-8")
        block = text.split("def _no_phones_message")[1].split("\ndef ")[0]
        self.assertNotIn("cannot start MuMu", block)
        self.assertIn("Boot all phones", block)

    def test_humanize_with_no_steps_is_a_failure(self):
        import sys
        from unittest.mock import patch

        wizard = ROOT / "wizard"
        if str(wizard) not in sys.path:
            sys.path.insert(0, str(wizard))
        import pharmflow_wizard_bridge as bridge
        from setup_wizard import state

        prev = state.get("groups")
        try:
            state["groups"] = [{"name": "g", "phones": {"serial": {"steps": []}}}]
            with (
                patch.object(bridge, "_prepare_editor_state"),
                patch.object(bridge, "_persist_editor_state") as persist,
            ):
                out = bridge.run_humanize_all_sequences()
        finally:
            if prev is None:
                state.pop("groups", None)
            else:
                state["groups"] = prev
        self.assertFalse(out["ok"])
        self.assertEqual(out["count"], 0)
        self.assertIn("No phone sequences", out["error"])
        persist.assert_not_called()

    def test_agent_status_ignores_a_fresh_log_and_the_open_exe(self):
        import sys
        from unittest.mock import patch

        wizard = ROOT / "wizard"
        if str(wizard) not in sys.path:
            sys.path.insert(0, str(wizard))
        import pharmflow_wizard_bridge as bridge

        status = {
            "ok": True,
            "farm_alive": True,
            "farm_owner": "PharmFlow.exe",
            "processes": [{"cmd": r"C:\PharmFlow\PharmFlow.exe"}],
        }
        with (
            patch.object(bridge, "_operator_status", return_value=status),
            patch.object(bridge, "_emit_log"),
            patch("wizard.farm_control.farm_process_alive", return_value=False),
            patch("wizard.farm_control.external_python_farm_running", return_value=False),
            patch("automation.farm_exe_self_heal.adb_live_serials", return_value=[]),
            patch("setup_wizard.probe_dashboard_listen_port", return_value=False),
            patch("urllib.request.urlopen", side_effect=OSError("down")),
        ):
            out = bridge.agent_status()
        self.assertTrue(out["ok"])
        self.assertFalse(out["running"])
        self.assertIn("Farm down", out["message"])
        self.assertEqual(out["adb"], 0)


class StopFarmProcessTests(unittest.TestCase):
    def test_a_fresh_log_is_not_a_running_farm_to_stop(self):
        import sys
        from unittest.mock import patch

        wizard = ROOT / "wizard"
        if str(wizard) not in sys.path:
            sys.path.insert(0, str(wizard))
        import pharmflow_wizard_bridge as bridge

        with (
            patch("wizard.farm_control.farm_process_alive", return_value=False),
            patch("wizard.farm_control.external_python_farm_running", return_value=False),
            patch("wizard.farm_control.stop_farm") as stop,
            patch("wizard.farm_control.farm_running", return_value=True),
        ):
            out = bridge.stop_farm_from_app()
        self.assertTrue(out["ok"])
        self.assertFalse(out["running"])
        self.assertFalse(out["stopped"])
        self.assertIn("already stopped", out["message"])
        stop.assert_not_called()

    def test_stop_does_not_claim_stopped_while_the_worker_is_alive(self):
        import sys
        from unittest.mock import patch

        wizard = ROOT / "wizard"
        if str(wizard) not in sys.path:
            sys.path.insert(0, str(wizard))
        import pharmflow_wizard_bridge as bridge

        with (
            patch("wizard.farm_control.farm_process_alive", return_value=True),
            patch("wizard.farm_control.stop_farm", return_value=True),
        ):
            out = bridge.stop_farm_from_app()
        self.assertFalse(out["ok"])
        self.assertTrue(out["running"])
        self.assertFalse(out["stopped"])
        self.assertIn("still running", out["error"])

    def test_home_stop_keeps_the_button_on_when_the_worker_remains(self):
        js = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        block = js.split("return a.stop_farm();")[1].split("btn-open-dash-home")[0]
        self.assertIn("res.running", block)
        stopped = block.split("applyHomeFarmState(false)")[0]
        self.assertIn("res.running", stopped)


class FarmSettingsDoNotCapTests(unittest.TestCase):
    def test_advanced_panel_does_not_offer_phone_or_rate_caps(self):
        import sys

        wizard = ROOT / "wizard"
        if str(wizard) not in sys.path:
            sys.path.insert(0, str(wizard))
        import farm_settings

        keys = {str(e["key"]) for e in farm_settings.CATALOG}
        self.assertTrue(keys.isdisjoint(farm_settings._EXE_CAP_KEYS))

    def test_saved_phone_count_is_not_applied_on_farm_start(self):
        import json
        import os
        import sys
        import tempfile
        from unittest.mock import patch

        wizard = ROOT / "wizard"
        if str(wizard) not in sys.path:
            sys.path.insert(0, str(wizard))
        import farm_settings

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wizard_farm_settings.json"
            path.write_text(
                json.dumps(
                    {
                        "PHARMFLOW_FARM_EXPECT_PHONES": "4",
                        "PHARMFLOW_FARM_SEQS_PER_HOUR": "15",
                        "PHARMFLOW_GEO_TIME_WINDOW": "1",
                    }
                ),
                encoding="utf-8",
            )
            os.environ["PHARMFLOW_FARM_EXPECT_PHONES"] = "4"
            os.environ["PHARMFLOW_FARM_SEQS_PER_HOUR"] = "15"
            os.environ.pop("PHARMFLOW_GEO_TIME_WINDOW", None)
            with patch.object(farm_settings, "user_settings_path", return_value=path):
                n = farm_settings.apply_saved_to_env()
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("PHARMFLOW_FARM_EXPECT_PHONES", stored)
            self.assertNotIn("PHARMFLOW_FARM_SEQS_PER_HOUR", stored)
            self.assertEqual(stored.get("PHARMFLOW_GEO_TIME_WINDOW"), "1")
            self.assertEqual(os.environ.get("PHARMFLOW_GEO_TIME_WINDOW"), "1")
            self.assertNotIn("PHARMFLOW_FARM_EXPECT_PHONES", os.environ)
            self.assertNotIn("PHARMFLOW_FARM_SEQS_PER_HOUR", os.environ)
            self.assertEqual(n, 1)
            os.environ.pop("PHARMFLOW_GEO_TIME_WINDOW", None)

    def test_farm_settings_save_requires_disk_readback(self):
        import json
        import sys
        import tempfile
        from unittest.mock import patch

        wizard = ROOT / "wizard"
        if str(wizard) not in sys.path:
            sys.path.insert(0, str(wizard))
        import farm_settings

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wizard_farm_settings.json"
            with (
                patch.object(farm_settings, "user_settings_path", return_value=path),
                patch.object(farm_settings, "_apply_to_env"),
            ):
                out = farm_settings.save({"PHARMFLOW_FARM_BAN_SERIALS": "10.0.2.16:5555"})
            self.assertTrue(out["ok"])
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(stored["PHARMFLOW_FARM_BAN_SERIALS"], "10.0.2.16:5555")

            def lie(_data):
                path.write_text("{}\n", encoding="utf-8")

            with (
                patch.object(farm_settings, "user_settings_path", return_value=path),
                patch.object(farm_settings, "_write_saved", side_effect=lie),
                patch.object(farm_settings, "_apply_to_env") as apply,
            ):
                missed = farm_settings.save({"PHARMFLOW_FARM_BAN_SERIALS": "10.0.2.99:5555"})
            self.assertFalse(missed["ok"])
            apply.assert_not_called()

    def test_control_dashboard_button_does_not_open_the_farm_dashboard(self):
        js = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        block = js.split('getElementById("btn-open-dash")')[1].split("btn-cloud-setup")[0]
        self.assertIn("openControlDash", block)
        self.assertNotIn("openFarmDash", block)
        opener = js.split("async function openControlDash()")[1].split("const btnStartHome")[0]
        self.assertIn("a.open_dashboard()", opener)
        self.assertNotIn("open_farm_dashboard", opener)
        self.assertIn("res.opened !== true", opener)

    def test_start_farm_does_not_mark_running_unless_a_worker_is_up(self):
        js = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        block = js.split("return a.start_farm();")[1].split("btn-stop-farm-home")[0]
        self.assertIn("res.started && res.running", block)
        self.assertNotIn("else if (res && res.started) {", block)

    def test_install_everything_does_not_claim_adb_or_webview(self):
        html = (ROOT / "wizard" / "assets" / "pharmflow_app" / "index.html").read_text(encoding="utf-8")
        block = html.split('id="btn-install-all"')[1].split("</button>")[0]
        self.assertIn("Does not install WebView2", block)
        self.assertNotIn("Android SDK tools", block)
        self.assertIn("Android SDK and ADB are the next step", block)
        js = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("Everything is already installed", js)
        wizard = (ROOT / "wizard" / "setup_wizard.py").read_text(encoding="utf-8")
        self.assertNotIn("Open MuMu yourself", wizard)

    def test_health_live_is_a_worker_not_a_fresh_log(self):
        bridge = (ROOT / "wizard" / "pharmflow_wizard_bridge.py").read_text(encoding="utf-8")
        block = bridge.split("def get_farm_health", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("farm_process_alive", block)
        self.assertIn('out["farm_alive"] = alive', block)
        js = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        health = js.split("function renderHealth", 1)[1].split("async function refreshHealth", 1)[0]
        self.assertIn("No farm worker process is running", health)
        self.assertNotIn("sessions are clean", health)
        self.assertIn("An empty window is not a clean farm", health)
        for marker in (
            "Groups accepted",
            "Automation accepted",
        ):
            after = js.split(marker, 1)[1][:240]
            self.assertNotIn("stepComplete.go = true", after)

    def test_health_overlay_ignores_a_fresh_log(self):
        import sys
        import unittest.mock

        wizard = ROOT / "wizard"
        if str(wizard) not in sys.path:
            sys.path.insert(0, str(wizard))
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        import pharmflow_wizard_bridge as bridge

        def fake_snapshot():
            return {
                "ok": True,
                "farm_alive": True,
                "log_age_s": 3,
                "log_path": "farm_354.log",
            }

        with unittest.mock.patch("automation.farm_health.snapshot", fake_snapshot), unittest.mock.patch(
            "wizard.farm_control.farm_process_alive", return_value=False
        ), unittest.mock.patch(
            "wizard.farm_control.external_python_farm_running", return_value=False
        ):
            out = bridge.get_farm_health()
        self.assertTrue(out.get("ok"))
        self.assertFalse(out.get("farm_alive"))

    def test_running_avd_process_is_not_up_without_its_serial(self):
        from pharmflow_wizard_bridge import avd_name_from_emu_reply, serial_for_running_avd

        self.assertEqual(avd_name_from_emu_reply("Pixel_6\nOK\n"), "Pixel_6")
        self.assertEqual(avd_name_from_emu_reply("OK\n"), "")
        found = serial_for_running_avd(
            "Pixel_6",
            serials=["emulator-5554", "emulator-5556"],
            emu_name=lambda serial: "Pixel_6\nOK\n" if serial == "emulator-5556" else "Other\nOK\n",
        )
        self.assertEqual(found, "emulator-5556")
        missing = serial_for_running_avd(
            "Pixel_6",
            serials=["emulator-5554"],
            emu_name=lambda _serial: "Other\nOK\n",
        )
        self.assertEqual(missing, "")
        src = (ROOT / "wizard" / "pharmflow_wizard_bridge.py").read_text(encoding="utf-8")
        already = src.split("if name in running:", 1)[1].split("if not boot_gate.wait_for_boot_headroom", 1)[0]
        self.assertIn("serial_for_running_avd", already)
        self.assertIn("not counted as booted", already)
        self.assertNotIn("AVD already running", already)

    def test_save_sequence_fails_when_disk_does_not_keep_it(self):
        import sys
        import tempfile
        import unittest.mock
        from pathlib import Path

        wizard = ROOT / "wizard"
        if str(wizard) not in sys.path:
            sys.path.insert(0, str(wizard))
        import pharmflow_wizard_bridge as bridge
        import setup_wizard

        steps = [{"type": "wait", "seconds": 1}]
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "seq.json"
            real_write = Path.write_text

            def _write_empty(self, data, *args, **kwargs):
                if self == dest:
                    return real_write(self, "[]", *args, **kwargs)
                return real_write(self, data, *args, **kwargs)

            with unittest.mock.patch.object(bridge, "_reload_persisted_wizard_state"), unittest.mock.patch.dict(
                setup_wizard.state, {"default_steps": steps}
            ), unittest.mock.patch.object(Path, "write_text", _write_empty), unittest.mock.patch.object(
                bridge, "_commit_default_steps"
            ) as commit:
                missed = bridge.save_sequence_to_path(str(dest))
            self.assertFalse(missed.get("ok"))
            self.assertIn("not saved", missed.get("error") or "")
            commit.assert_not_called()

            with unittest.mock.patch.object(bridge, "_reload_persisted_wizard_state"), unittest.mock.patch.dict(
                setup_wizard.state, {"default_steps": steps}
            ), unittest.mock.patch.object(
                bridge, "_commit_default_steps", return_value={"ok": True, "count": 1, "steps": steps}
            ):
                kept = bridge.save_sequence_to_path(str(dest))
        self.assertTrue(kept.get("ok"))
        self.assertEqual(kept.get("count"), 1)

    def test_save_site_url_fails_when_disk_does_not_keep_it(self):
        import sys
        import unittest.mock

        wizard = ROOT / "wizard"
        if str(wizard) not in sys.path:
            sys.path.insert(0, str(wizard))
        import pharmflow_wizard_bridge as bridge

        with unittest.mock.patch("site_prefs.save_target_site_url", return_value="https://example.com"), unittest.mock.patch(
            "site_prefs.load_target_site_url", return_value=""
        ):
            missed = bridge.save_site_url("https://example.com")
        self.assertFalse(missed.get("ok"))
        self.assertIn("not saved", missed.get("error") or "")
        with unittest.mock.patch("site_prefs.save_target_site_url", return_value="https://example.com"), unittest.mock.patch(
            "site_prefs.load_target_site_url", return_value="https://example.com"
        ), unittest.mock.patch("site_prefs.site_display_host", return_value="example.com"):
            kept = bridge.save_site_url("https://example.com")
        self.assertTrue(kept.get("ok"))
        self.assertEqual(kept.get("url"), "https://example.com")

    def test_install_does_not_claim_a_window_until_the_child_marks_ready(self):
        import sys
        import tempfile

        wizard = ROOT / "wizard"
        if str(wizard) not in sys.path:
            sys.path.insert(0, str(wizard))
        import wizard_tk_spawn as spawn

        class Dead:
            returncode = 1

            def poll(self):
                return 1

        class Alive:
            returncode = None

            def poll(self):
                return None

        with tempfile.TemporaryDirectory() as tmp:
            ready = Path(tmp) / "ready.txt"
            err = Path(tmp) / "err.log"
            err.write_text("Tk failed before mainloop\n", encoding="utf-8")
            dead = spawn.confirm_spawned_window(Dead(), ready, err, timeout=0.4)
            self.assertFalse(dead["ok"])
            self.assertFalse(dead["window_ready"])
            self.assertIn("exited before it opened", dead["error"])
            self.assertIn("Tk failed", dead["error"])
            waiting = spawn.confirm_spawned_window(Alive(), ready, err, timeout=0.4)
            self.assertTrue(waiting["started"])
            self.assertFalse(waiting["window_ready"])
            self.assertIn("not up yet", waiting["message"])
            ready.write_text("ready\n", encoding="utf-8")
            opened = spawn.confirm_spawned_window(Alive(), ready, err, timeout=0.4)
            self.assertTrue(opened["window_ready"])
            self.assertIn("Opened a wizard window", opened["message"])
        desktop = (ROOT / "wizard" / "pharmflow_desktop.py").read_text(encoding="utf-8")
        page = desktop.split("def run_internal_tk_page(")[1].split("def _use_classic_tk_shell")[0]
        self.assertLess(page.index("_mark_internal_tk_ready()"), page.index("root.mainloop()"))
        js = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        install = js.split("run_install_all")[1].split("btn-android-install")[0]
        self.assertIn("res.started && res.window_ready", install)
        self.assertIn("The window is not up yet", install)

    def test_sequence_file_dialog_error_is_not_a_cancel(self):
        web = (ROOT / "wizard" / "pharmflow_app_webview.py").read_text(encoding="utf-8")
        picker = web.split("def pick_sequence_json(")[1].split("def load_sequence_from_path")[0]
        self.assertNotIn('cancelled": True, "error"', picker)
        js = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        load = js.split('getElementById("btn-load-sequence")')[1].split('getElementById("btn-save-sequence")')[0]
        self.assertLess(load.index("pick.error"), load.index("pick.cancelled"))

    def test_cloud_agent_step_limit_is_not_a_finish(self):
        agent = (ROOT / "tools" / "cloud_agent.py").read_text(encoding="utf-8")
        limit = agent.split("reached step limit")[1].split("def build_parser")[0]
        self.assertIn("return 4", limit)
        self.assertNotIn("return 0", limit)
        js = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("run_cloud_agent(goal.trim(), allowApply, \"\", \"\", 14)", js)
        bridge = (ROOT / "wizard" / "pharmflow_wizard_bridge.py").read_text(encoding="utf-8")
        self.assertIn("stopped at its step limit", bridge)
        cloud = bridge.split("def run_cloud_agent(")[1].split("\ndef ")[0]
        self.assertIn("if max_steps is not None", cloud)
        self.assertLess(cloud.index("if max_steps is not None"), cloud.index("--max-steps"))
        web = (ROOT / "wizard" / "pharmflow_app_webview.py").read_text(encoding="utf-8")
        wrap = web.split("def run_cloud_agent(")[1].split("\n    def ")[0]
        self.assertIn("if max_steps is not None", wrap)
        self.assertNotIn("max_steps: int = 12", wrap)
        wizard = (ROOT / "wizard" / "setup_wizard.py").read_text(encoding="utf-8")
        self.assertNotIn("min(h, 1440)", wizard)
        self.assertNotIn("min(int(var.get()), 1440)", wizard)
        sched = (ROOT / "automation" / "scheduler.py").read_text(encoding="utf-8")
        self.assertNotIn("1440", sched)

    def test_farm_dashboard_button_does_not_open_the_control_server(self):
        bridge = (ROOT / "wizard" / "pharmflow_wizard_bridge.py").read_text(encoding="utf-8")
        block = bridge.split("def open_farm_dashboard(")[1].split("def get_farm_health(")[0]
        self.assertIn("127.0.0.1:8091", block)
        self.assertNotIn("dashboard_base_url", block)
        self.assertNotIn("probe_dashboard_listen_port", block)
        self.assertIn("does not open the control dashboard", block)
        js = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        opener = js.split("async function openFarmDash()")[1].split("async function openControlDash()")[0]
        self.assertIn("a.open_farm_dashboard()", opener)
        self.assertNotIn("a.open_dashboard()", opener)
        self.assertIn(":8091", opener)
        html = (ROOT / "wizard" / "assets" / "pharmflow_app" / "index.html").read_text(encoding="utf-8")
        start = html.split('id="btn-start-server"')[1].split("</button>")[0]
        self.assertIn("control dashboard", start)
        self.assertIn("not the farm dashboard", start)
        self.assertNotIn("opens the dashboard in your browser", start)

    def test_journey_phones_are_not_done_without_a_live_phone(self):
        import sys
        import unittest.mock
        from pathlib import Path

        wizard = ROOT / "wizard"
        if str(wizard) not in sys.path:
            sys.path.insert(0, str(wizard))
        import pharmflow_wizard_bridge as bridge

        def _phones(out: dict) -> bool:
            return next(s for s in out["steps"] if s["id"] == "phones")["complete"]

        def _run(phones: list[str]):
            with (
                unittest.mock.patch.object(bridge, "scan_prereqs", return_value=[]),
                unittest.mock.patch.object(bridge, "_reload_persisted_wizard_state"),
                unittest.mock.patch("mumu_setup_core.data_root", return_value=Path(".")),
                unittest.mock.patch("mumu_setup_core.setup_awaiting_cold_boot", return_value=False),
                unittest.mock.patch("preflight_core.mumu_setup_already_done", return_value=True),
                unittest.mock.patch("preflight_core.list_adb_phones", return_value=phones) as listed,
            ):
                out = bridge.get_journey_state()
            return out, listed

        empty, listed = _run([])
        self.assertFalse(_phones(empty))
        listed.assert_called_once_with(timeout=4)
        live, _listed = _run(["10.0.2.20:5555"])
        self.assertTrue(_phones(live))

    def test_phones_nav_is_not_done_without_a_live_phone(self):
        js = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        idx = js.index("setup_already_done")
        block = js[idx - 220 : idx + 400]
        self.assertIn("livePhones > 0", block)
        self.assertIn("stepComplete.phones = false", block)
        self.assertNotIn(
            "if (state && (state.ready || state.setup_already_done)) stepComplete.phones = true;",
            js,
        )

    def test_empty_advanced_step_is_hidden(self):
        js = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        block = js.split("async function ensureAdvanced(")[1].split("function advStatus(")[0]
        self.assertIn("if (!entries.length)", block)
        self.assertIn("box.hidden = true", block)


if __name__ == "__main__":
    unittest.main()
