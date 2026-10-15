"""Regression tests for setup wizard Step 8/9 and playlist UX."""
from __future__ import annotations

import inspect
import os
import sys
import tempfile
import tkinter as tk
import unittest
import unittest.mock
import urllib.error
from pathlib import Path

_wizard_dir = Path(__file__).resolve().parent
if str(_wizard_dir) not in sys.path:
    sys.path.insert(0, str(_wizard_dir))

import setup_wizard as sw  # noqa: E402
from setup_wizard import PerPhoneSequenceEditor  # noqa: E402


class WizardRegressionTests(unittest.TestCase):
    def test_open_setup_guide_opens_local_doc_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            docs = tmp_path / "docs"
            docs.mkdir(parents=True, exist_ok=True)
            guide = docs / "PharmFlow_emulator_MuMu_and_sequences.md"
            guide.write_text("# setup", encoding="utf-8")

            orig_state_dir = sw.state.get("pharmflow_dir")
            sw.state["pharmflow_dir"] = str(tmp_path)

            calls: list[str] = []
            orig_startfile = getattr(sw.os, "startfile", None)
            orig_web_open = sw.webbrowser.open
            orig_msg_info = sw.messagebox.showinfo
            orig_msg_err = sw.messagebox.showerror
            try:
                if orig_startfile is not None:
                    sw.os.startfile = lambda p: calls.append(str(p))  # type: ignore[attr-defined]
                    sw.webbrowser.open = lambda _url: (_ for _ in ()).throw(RuntimeError("unexpected URL open"))
                else:
                    sw.webbrowser.open = lambda url, **kw: calls.append(str(url)) or True
                sw.messagebox.showinfo = lambda *a, **k: None
                sw.messagebox.showerror = lambda *a, **k: None
                sw._open_setup_guide_doc()
            finally:
                if orig_startfile is not None:
                    sw.os.startfile = orig_startfile  # type: ignore[attr-defined]
                sw.webbrowser.open = orig_web_open
                sw.messagebox.showinfo = orig_msg_info
                sw.messagebox.showerror = orig_msg_err
                if orig_state_dir is None:
                    sw.state.pop("pharmflow_dir", None)
                else:
                    sw.state["pharmflow_dir"] = orig_state_dir

            self.assertTrue(calls, "expected local guide to open via OS file opener")
            self.assertTrue(calls[0].lower().endswith("pharmflow_emulator_mumu_and_sequences.md"))

    def test_playlist_add_accepts_multiple_json_paths(self) -> None:
        ed = PerPhoneSequenceEditor.__new__(PerPhoneSequenceEditor)
        ed._playlist_names = []
        ed._playlist_secondary_names = []
        ed._pl_refresh_playlist = lambda: None
        ed._pl_refresh_playlist_b = lambda: None
        marks: list[str] = []
        ed._mark_sequence_edited = lambda: marks.append("dirty")

        added = PerPhoneSequenceEditor._pl_add_from_paths(
            ed,
            [
                "/tmp/flows/a.json",
                "/tmp/flows/b.json",
                "/tmp/flows/b.json",
                "/tmp/flows/not-json.txt",
            ],
            set_b=False,
        )
        self.assertEqual(added, 2)
        self.assertEqual(ed._playlist_names, ["a.json", "b.json"])
        self.assertEqual(len(marks), 1)

    def test_playlist_uses_multiselect_dialog(self) -> None:
        src = inspect.getsource(PerPhoneSequenceEditor._pl_choose_files)
        self.assertIn("askopenfilenames", src)
        self.assertIn("one or more", src)

    def test_groups_edit_path_passes_phone_ent(self) -> None:
        src = inspect.getsource(sw.GroupsPage._build_card)
        self.assertIn("phone_ent=ent if isinstance(ent, dict) else None", src)

    def test_wizard_has_groups_tryout_entrypoint(self) -> None:
        src = inspect.getsource(sw.PharmFlowWizard.start_tryout_from_groups)
        self.assertIn("LaunchPage", src)
        self.assertIn("_start_automation_one_click", src)

    def test_wizard_pages_exclude_play_store(self) -> None:
        self.assertNotIn(sw.PlayStorePage, sw.PharmFlowWizard.PAGES)
        self.assertNotIn("Play", sw.PharmFlowWizard.PAGE_NAMES)

    def _make_groups_page_stub(self, root: tk.Tk):
        """Allocate a ``GroupsPage`` without running ``__init__`` (skips icon-loading
        side effects that are flaky across multiple ``tk.Tk()`` lifetimes — see the
        process-wide ``_icon_cache`` in ``wizard_theme.load_icon``)."""
        page = sw.GroupsPage.__new__(sw.GroupsPage)
        page.winfo_toplevel = lambda: root  # type: ignore[method-assign]
        return page

    @staticmethod
    def _make_group(serial: str, *, steps=None, playlist=None, playlist_b=None) -> dict:
        ent = {
            "steps": list(steps or []),
            "hits_per_day": sw.DEFAULT_HITS_PER_DAY,
            "use_default_template": False,
            "explicit_override": True,
            "sequence_base_w": sw.DEFAULT_SEQUENCE_BASE_W,
            "sequence_base_h": sw.DEFAULT_SEQUENCE_BASE_H,
            "sequence_playlist": list(playlist or []),
            "sequence_playlist_secondary": list(playlist_b or []),
            "sequence_playlist_mode": "ordered",
            "sequence_playlist_shuffle": "none",
        }
        return {
            "name": "Group 1",
            "phones": {serial: ent},
            "stagger_secs": 30,
            "repeat": 1,
            "repeat_forever": False,
        }

    def test_groups_page_tryout_routes_to_wizard_when_phone_has_steps(self) -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            old_state = dict(sw.state)
            try:
                sw.state["phones"] = [{"serial": "emu-1", "name": "Phone 1"}]
                sw.state["groups"] = [
                    self._make_group("emu-1", steps=[{"type": "wait", "seconds": 1}])
                ]
                page = self._make_groups_page_stub(root)
                called = {"count": 0}

                class _StubWizard:
                    def start_tryout_from_groups(self_inner) -> None:
                        called["count"] += 1

                page.app = _StubWizard()
                orig_ok = sw.messagebox.askokcancel
                sw.messagebox.askokcancel = lambda *a, **k: True
                try:
                    page._tryout_all()
                finally:
                    sw.messagebox.askokcancel = orig_ok
                self.assertEqual(called["count"], 1)
            finally:
                sw.state.clear()
                sw.state.update(old_state)
        finally:
            root.destroy()

    def test_groups_page_tryout_routes_to_wizard_when_phone_has_playlist(self) -> None:
        """A playlist with no inline steps is still considered runnable."""
        root = tk.Tk()
        root.withdraw()
        try:
            old_state = dict(sw.state)
            try:
                sw.state["phones"] = [{"serial": "emu-1", "name": "Phone 1"}]
                sw.state["groups"] = [
                    self._make_group("emu-1", playlist=["close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__hdd71d4.json"])
                ]
                page = self._make_groups_page_stub(root)

                called = {"count": 0}

                class _StubWizard:
                    def start_tryout_from_groups(self_inner) -> None:
                        called["count"] += 1

                page.app = _StubWizard()
                orig_ok = sw.messagebox.askokcancel
                sw.messagebox.askokcancel = lambda *a, **k: True
                try:
                    page._tryout_all()
                finally:
                    sw.messagebox.askokcancel = orig_ok
                self.assertEqual(called["count"], 1)
            finally:
                sw.state.clear()
                sw.state.update(old_state)
        finally:
            root.destroy()

    def test_groups_page_tryout_warns_when_nothing_to_run(self) -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            old_state = dict(sw.state)
            try:
                sw.state["phones"] = [{"serial": "emu-1", "name": "Phone 1"}]
                sw.state["groups"] = [self._make_group("emu-1")]
                page = self._make_groups_page_stub(root)

                called = {"count": 0}

                class _StubWizard:
                    def start_tryout_from_groups(self_inner) -> None:
                        called["count"] += 1

                page.app = _StubWizard()
                warns: list[tuple] = []
                orig_warn = sw.messagebox.showwarning
                orig_ok = sw.messagebox.askokcancel
                sw.messagebox.showwarning = lambda *a, **k: warns.append((a, k))
                sw.messagebox.askokcancel = lambda *a, **k: True
                try:
                    page._tryout_all()
                finally:
                    sw.messagebox.showwarning = orig_warn
                    sw.messagebox.askokcancel = orig_ok
                self.assertEqual(called["count"], 0)
                self.assertTrue(warns, "Should warn when no phone has steps or playlist")
            finally:
                sw.state.clear()
                sw.state.update(old_state)
        finally:
            root.destroy()

    def test_groups_page_tryout_aborts_on_user_cancel(self) -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            old_state = dict(sw.state)
            try:
                sw.state["phones"] = [{"serial": "emu-1", "name": "Phone 1"}]
                sw.state["groups"] = [
                    self._make_group("emu-1", steps=[{"type": "wait", "seconds": 1}])
                ]
                page = self._make_groups_page_stub(root)

                called = {"count": 0}

                class _StubWizard:
                    def start_tryout_from_groups(self_inner) -> None:
                        called["count"] += 1

                page.app = _StubWizard()
                orig_ok = sw.messagebox.askokcancel
                sw.messagebox.askokcancel = lambda *a, **k: False
                try:
                    page._tryout_all()
                finally:
                    sw.messagebox.askokcancel = orig_ok
                self.assertEqual(called["count"], 0)
            finally:
                sw.state.clear()
                sw.state.update(old_state)
        finally:
            root.destroy()

    def test_groups_page_tryout_blocks_on_empty_group(self) -> None:
        """Reuses ``can_advance`` so an empty group still blocks the tryout."""
        root = tk.Tk()
        root.withdraw()
        try:
            old_state = dict(sw.state)
            try:
                sw.state["phones"] = [{"serial": "emu-1", "name": "Phone 1"}]
                sw.state["groups"] = [
                    {
                        "name": "Group 1",
                        "phones": {},
                        "stagger_secs": 30,
                        "repeat": 1,
                        "repeat_forever": False,
                    }
                ]
                page = self._make_groups_page_stub(root)

                called = {"count": 0}

                class _StubWizard:
                    def start_tryout_from_groups(self_inner) -> None:
                        called["count"] += 1

                page.app = _StubWizard()
                warns: list[tuple] = []
                orig_warn = sw.messagebox.showwarning
                orig_ok = sw.messagebox.askokcancel
                sw.messagebox.showwarning = lambda *a, **k: warns.append((a, k))
                sw.messagebox.askokcancel = lambda *a, **k: True
                try:
                    page._tryout_all()
                finally:
                    sw.messagebox.showwarning = orig_warn
                    sw.messagebox.askokcancel = orig_ok
                self.assertEqual(called["count"], 0)
                self.assertTrue(warns, "Empty group should warn before any tryout")
            finally:
                sw.state.clear()
                sw.state.update(old_state)
        finally:
            root.destroy()

    def test_groups_page_populate_footer_actions_adds_button(self) -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            page = self._make_groups_page_stub(root)
            slot = tk.Frame(root)
            slot.pack()
            page.populate_footer_actions(slot)
            texts = [
                str(child.cget("text"))
                for child in slot.winfo_children()
                if child.winfo_class() == "Button"
            ]
            self.assertIn("Tryout / Run playlist now", texts)
        finally:
            root.destroy()

    def test_chrome_open_url_returns_ok_when_adb_clean(self) -> None:
        """``chrome_open_url`` must report success so the wizard can messagebox-verify browser control."""
        auto = Path(sw.__file__).resolve().parents[1] / "automation"
        ap = str(auto)
        if ap not in sys.path:
            sys.path.insert(0, ap)
        import browser_adb  # noqa: WPS433

        def _adb(*args, serial=None, timeout=20):
            if args[:5] == ("shell", "settings", "get", "global", "http_proxy"):
                return "127.0.0.1:8118"
            return "Starting: Intent { act=android.intent.action.VIEW }"

        with unittest.mock.patch.object(sw, "_wiz_skip_tor_wait", return_value=True), \
             unittest.mock.patch.object(sw, "_wiz_wait_browser_pid_after_open"), \
             unittest.mock.patch.object(sw, "_wiz_settle_after_open_url", return_value=0.0), \
             unittest.mock.patch.object(browser_adb, "package_installed", return_value=False), \
             unittest.mock.patch.object(
                 browser_adb,
                 "packages_for_view_url_attempts",
                 return_value=[],
             ), \
             unittest.mock.patch.object(sw, "adb", side_effect=_adb):
            ok, note = sw.chrome_open_url("serial-test", "https://example.com/")
        self.assertTrue(ok)
        self.assertIsNone(note)

    def test_chrome_open_url_empty_adb_is_not_an_open(self) -> None:
        auto = Path(sw.__file__).resolve().parents[1] / "automation"
        ap = str(auto)
        if ap not in sys.path:
            sys.path.insert(0, ap)
        import browser_adb  # noqa: WPS433

        def _adb(*args, serial=None, timeout=20):
            if args[:5] == ("shell", "settings", "get", "global", "http_proxy"):
                return "127.0.0.1:8118"
            return ""

        with unittest.mock.patch.object(sw, "_wiz_skip_tor_wait", return_value=True), \
             unittest.mock.patch.object(sw, "_wiz_wait_browser_pid_after_open"), \
             unittest.mock.patch.object(sw, "_wiz_settle_after_open_url", return_value=0.0), \
             unittest.mock.patch.object(browser_adb, "package_installed", return_value=False), \
             unittest.mock.patch.object(
                 browser_adb,
                 "packages_for_view_url_attempts",
                 return_value=[],
             ), \
             unittest.mock.patch.object(sw, "adb", side_effect=_adb):
            ok, note = sw.chrome_open_url("serial-test", "https://example.com/")
        self.assertFalse(ok)
        self.assertIn("did not open", (note or "").lower())

    def test_chrome_open_url_returns_false_when_adb_errors(self) -> None:
        auto = Path(sw.__file__).resolve().parents[1] / "automation"
        ap = str(auto)
        if ap not in sys.path:
            sys.path.insert(0, ap)
        import browser_adb  # noqa: WPS433

        with unittest.mock.patch.object(sw, "_wiz_skip_tor_wait", return_value=True), \
             unittest.mock.patch.object(sw, "_wiz_wait_browser_pid_after_open"), \
             unittest.mock.patch.object(sw, "_wiz_settle_after_open_url", return_value=0.0), \
             unittest.mock.patch.object(browser_adb, "package_installed", return_value=False), \
             unittest.mock.patch.object(
                 browser_adb,
                 "packages_for_view_url_attempts",
                 return_value=[],
             ), \
             unittest.mock.patch.object(
                 sw,
                 "adb",
                 return_value="error: no devices/emulators found",
             ):
            ok, note = sw.chrome_open_url("serial-test", "https://example.com/")
        self.assertFalse(ok)
        self.assertIn("error:", (note or "").lower())

    def test_dabflow_open_does_not_launch_when_exit_not_ready(self) -> None:
        auto = Path(sw.__file__).resolve().parents[1] / "automation"
        ap = str(auto)
        if ap not in sys.path:
            sys.path.insert(0, ap)
        import tor_manager  # noqa: WPS433

        adb = unittest.mock.Mock()
        with unittest.mock.patch.object(sw, "_wiz_prepare_browse_skip_tor", return_value=False), \
             unittest.mock.patch.object(sw, "_wiz_skip_tor_wait", return_value=False), \
             unittest.mock.patch.object(sw, "_wiz_repair_proxy_adb_reverse"), \
             unittest.mock.patch.object(tor_manager, "start_tor_warm_background"), \
             unittest.mock.patch.object(
                 tor_manager,
                 "ensure_tor_ready",
                 return_value={"ok": False, "error": "bootstrap"},
             ), \
             unittest.mock.patch.object(sw, "adb", adb), \
             unittest.mock.patch(
                 "browser_setup.prepare_for_dabflow_open",
                 return_value={"skipped": True},
             ):
            ok, note = sw.chrome_open_url("serial-test", "https://getdabflow.app/x")
        self.assertFalse(ok)
        self.assertTrue(note)
        adb.assert_not_called()

    def test_non_dabflow_open_does_not_launch_without_phone_exit(self) -> None:
        auto = Path(sw.__file__).resolve().parents[1] / "automation"
        ap = str(auto)
        if ap not in sys.path:
            sys.path.insert(0, ap)
        import browse_proxy  # noqa: WPS433

        calls: list[tuple] = []

        def _adb(*args, serial=None, timeout=20):
            calls.append(args)
            if args[:5] == ("shell", "settings", "get", "global", "http_proxy"):
                return ":0"
            return "Starting: Intent { act=android.intent.action.VIEW }"

        with unittest.mock.patch.object(sw, "_wiz_prepare_browse_skip_tor", return_value=False), \
             unittest.mock.patch.object(sw, "_wiz_skip_tor_wait", return_value=True), \
             unittest.mock.patch.object(sw, "adb", side_effect=_adb), \
             unittest.mock.patch.object(browse_proxy, "pin_guest_proxy", return_value=":0"):
            ok, note = sw.chrome_open_url("serial-test", "https://example.com/")
        self.assertFalse(ok)
        self.assertIn("no exit proxy", note or "")
        self.assertFalse(any(args[:2] == ("shell", "am") for args in calls))


class DashboardListenPortTests(unittest.TestCase):
    def setUp(self) -> None:
        sw.clear_dashboard_listen_port_cache()
        self._prev_port = os.environ.get("PHARMFLOW_PORT")
        self._prev_try = os.environ.get("PHARMFLOW_PORT_TRY_COUNT")

    def tearDown(self) -> None:
        sw.clear_dashboard_listen_port_cache()
        if self._prev_port is None:
            os.environ.pop("PHARMFLOW_PORT", None)
        else:
            os.environ["PHARMFLOW_PORT"] = self._prev_port
        if self._prev_try is None:
            os.environ.pop("PHARMFLOW_PORT_TRY_COUNT", None)
        else:
            os.environ["PHARMFLOW_PORT_TRY_COUNT"] = self._prev_try

    def test_candidate_ports_respects_try_count(self) -> None:
        os.environ["PHARMFLOW_PORT"] = "9000"
        os.environ["PHARMFLOW_PORT_TRY_COUNT"] = "3"
        self.assertEqual(sw._dashboard_candidate_ports(), [9000, 9001, 9002])

    def test_candidate_ports_not_capped_by_a_hardcoded_ceiling(self) -> None:
        # Was clamped to 128 here (and 256 in dashboard.py), so a count in
        # between let the server bind where the wizard never looked.
        os.environ["PHARMFLOW_PORT"] = "9000"
        os.environ["PHARMFLOW_PORT_TRY_COUNT"] = "200"
        ports = sw._dashboard_candidate_ports()
        self.assertEqual(len(ports), 200)
        self.assertEqual(ports[-1], 9199)

    def test_candidate_ports_stop_at_the_end_of_the_port_space(self) -> None:
        # The natural bound replacing the magic cap: never past 65535.
        os.environ["PHARMFLOW_PORT"] = "65530"
        os.environ["PHARMFLOW_PORT_TRY_COUNT"] = "100000"
        self.assertEqual(sw._dashboard_candidate_ports(), list(range(65530, 65536)))

    def test_bad_try_count_falls_back_to_default(self) -> None:
        os.environ["PHARMFLOW_PORT_TRY_COUNT"] = "not-a-number"
        self.assertEqual(sw._dashboard_port_try_count(), 20)
        os.environ["PHARMFLOW_PORT_TRY_COUNT"] = "0"
        self.assertEqual(sw._dashboard_port_try_count(), 1)

    @unittest.mock.patch.object(sw.urllib.request, "urlopen")
    def test_large_scan_does_not_block_past_the_deadline(self, mock_open: unittest.mock.MagicMock) -> None:
        """Root cause the old 128 cap papered over: leaving the executor block
        waited for every queued probe, so a wide scan froze the caller far past
        the 3.5s budget. Stragglers must be dropped at the deadline."""
        import time as _t

        os.environ["PHARMFLOW_PORT"] = "8080"
        os.environ["PHARMFLOW_PORT_TRY_COUNT"] = "400"

        def _slow_refuse(req, timeout=None):  # noqa: ARG001
            _t.sleep(0.6)  # a blackholed loopback port, scaled down
            raise urllib.error.URLError("refused")

        mock_open.side_effect = _slow_refuse
        t0 = _t.monotonic()
        found = sw.probe_dashboard_listen_port()
        elapsed = _t.monotonic() - t0
        self.assertFalse(found)
        # Old code (count clamped to 128, executor waited on every probe):
        # ceil(128/8) * 0.6s = ~9.6s. New: returns at the ~3.5s deadline, however
        # wide the scan is.
        self.assertLess(elapsed, 6.5, f"scan blocked {elapsed:.1f}s past its deadline")

    @unittest.mock.patch.object(sw.urllib.request, "urlopen")
    def test_probe_sets_cache_from_api_config(self, mock_open: unittest.mock.MagicMock) -> None:
        os.environ["PHARMFLOW_PORT"] = "8080"

        def side_effect(req, timeout=None):  # noqa: ARG001
            if ":8080/" in req.full_url:
                raise urllib.error.URLError("refused")
            if ":8081/" in req.full_url:
                cm = unittest.mock.MagicMock()
                cm.read.return_value = b'{"httpPort":8081,"wsPort":8082}'
                cm.__enter__.return_value = cm
                return cm
            raise AssertionError(req.full_url)

        mock_open.side_effect = side_effect
        self.assertTrue(sw.probe_dashboard_listen_port())
        self.assertEqual(sw.dashboard_http_port(), 8081)

    def test_launch_page_opens_dashboard_uses_probe(self) -> None:
        src = inspect.getsource(sw.LaunchPage._open_dashboard_browser)
        self.assertIn("probe_dashboard_listen_port", src)


class DefaultSequencePersistTests(unittest.TestCase):
    def test_default_sequence_survives_reload_when_groups_cannot_be_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            groups = Path(tmp) / "groups_config.json"
            prev = list(sw.state.get("default_steps") or [])
            try:
                with unittest.mock.patch(
                    "wizard_paths.groups_config_path",
                    return_value=groups,
                ):
                    sw.state["default_steps"] = [
                        {"type": "open_url", "url": "https://getdabflow.app/demo"}
                    ]
                    written = sw._persist_default_steps()
                    self.assertIsNotNone(written)
                    sw.state["default_steps"] = []
                    self.assertTrue(sw._try_load_default_steps())
                    self.assertEqual(
                        sw.state["default_steps"][0]["url"],
                        "https://getdabflow.app/demo",
                    )
            finally:
                sw.state["default_steps"] = prev


class CreatePhoneCountTests(unittest.TestCase):
    def test_any_positive_count_is_accepted(self) -> None:
        self.assertEqual(sw.coerce_phone_count("40"), 40)
        self.assertEqual(sw.coerce_phone_count(1), 1)
        self.assertIsNone(sw.coerce_phone_count("0"))
        self.assertIsNone(sw.coerce_phone_count(""))
        text = Path(sw.__file__).read_text(encoding="utf-8")
        self.assertNotIn("up to 10 phones", text)
        self.assertNotIn("up to 5 phones", text)
        self.assertIn("def coerce_phone_count", text)
        self.assertIn("There is no phone-count stop", text)


class StartEmulatorDoesNotWipeTests(unittest.TestCase):
    def test_start_keeps_the_data_disk_and_does_not_hide_the_phone(self) -> None:
        captured: dict = {}

        class _Proc:
            pass

        def _popen(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return _Proc()

        with unittest.mock.patch.object(sw.subprocess, "Popen", side_effect=_popen):
            sw.start_emulator("Pixel_Test", 5554)
        cmd = captured["cmd"]
        self.assertIn("Pixel_Test", cmd)
        self.assertNotIn("-wipe-data", cmd)
        flags = int(captured["kwargs"].get("creationflags") or 0)
        detached = int(getattr(sw.subprocess, "DETACHED_PROCESS", 0) or 0)
        self.assertFalse(flags & detached)
        self.assertIsNone(captured["kwargs"].get("startupinfo"))


class MuMuInstanceDiscoveryTests(unittest.TestCase):
    def test_partial_cli_list_does_not_hide_later_phones(self) -> None:
        cli = [
            {"index": 0, "name": "vm0", "adb_serial": "10.0.2.15:5555", "started": True},
            {"index": 1, "name": "vm1", "adb_serial": "10.0.2.16:5555", "started": True},
        ]
        disk = cli + [
            {"index": 16, "name": "vm16", "adb_serial": "10.0.2.31:5555", "started": False},
            {"index": 17, "name": "vm17", "adb_serial": "10.0.2.32:5555", "started": False},
        ]
        merged = sw._merge_mumu_instances(cli, disk)
        indexes = [row["index"] for row in merged]
        self.assertEqual(indexes, [0, 1, 16, 17])
        cli_loopback = [
            {"index": 0, "name": "vm0", "adb_serial": "127.0.0.1:16384", "started": True},
        ]
        disk_guest = [
            {"index": 0, "name": "vm0", "adb_serial": "10.0.2.15:5555", "started": True},
        ]
        replaced = sw._merge_mumu_instances(cli_loopback, disk_guest)
        self.assertEqual(replaced[0]["adb_serial"], "10.0.2.15:5555")
        body = inspect.getsource(sw._mumu_get_instances)
        self.assertNotIn("range(16)", body)
        self.assertIn("_merge_mumu_instances", body)
        self.assertIn("_mumu_instances_from_disk", body)


class ClassicStepLandingTests(unittest.TestCase):
    def test_input_command_does_not_count_an_adb_error(self) -> None:
        self.assertTrue(sw.input_command_landed(0, ""))
        self.assertFalse(sw.input_command_landed(1, ""))
        self.assertFalse(sw.input_command_landed(0, "Exception: inject failed"))
        body = inspect.getsource(sw.execute_steps)
        self.assertIn("sequence tap did not land", body)
        self.assertIn("sequence swipe did not land", body)
        self.assertIn("sequence keyevent did not land", body)
        self.assertIn("sequence type_text did not land", body)
        self.assertIn("sequence step is not runnable", body)
        self.assertIn("sequence popup dismiss did not land", body)
        self.assertIn("sequence session notes still up", body)
        self.assertIn("return True", body)


if __name__ == "__main__":
    unittest.main()
