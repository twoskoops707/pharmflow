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
            guide = docs / "CPharm_emulator_MuMu_and_sequences.md"
            guide.write_text("# setup", encoding="utf-8")

            orig_state_dir = sw.state.get("cpharm_dir")
            sw.state["cpharm_dir"] = str(tmp_path)

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
                    sw.state.pop("cpharm_dir", None)
                else:
                    sw.state["cpharm_dir"] = orig_state_dir

            self.assertTrue(calls, "expected local guide to open via OS file opener")
            self.assertTrue(calls[0].lower().endswith("cpharm_emulator_mumu_and_sequences.md"))

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
        src = inspect.getsource(sw.CPharmWizard.start_tryout_from_groups)
        self.assertIn("LaunchPage", src)
        self.assertIn("_start_automation_one_click", src)

    def test_wizard_pages_exclude_play_store(self) -> None:
        self.assertNotIn(sw.PlayStorePage, sw.CPharmWizard.PAGES)
        self.assertNotIn("Play", sw.CPharmWizard.PAGE_NAMES)

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
                 return_value="Starting: Intent { act=android.intent.action.VIEW }",
             ):
            ok, note = sw.chrome_open_url("serial-test", "https://example.com/")
        self.assertTrue(ok)
        self.assertIsNone(note)

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


class DashboardListenPortTests(unittest.TestCase):
    def setUp(self) -> None:
        sw.clear_dashboard_listen_port_cache()
        self._prev_port = os.environ.get("CPHARM_PORT")
        self._prev_try = os.environ.get("CPHARM_PORT_TRY_COUNT")

    def tearDown(self) -> None:
        sw.clear_dashboard_listen_port_cache()
        if self._prev_port is None:
            os.environ.pop("CPHARM_PORT", None)
        else:
            os.environ["CPHARM_PORT"] = self._prev_port
        if self._prev_try is None:
            os.environ.pop("CPHARM_PORT_TRY_COUNT", None)
        else:
            os.environ["CPHARM_PORT_TRY_COUNT"] = self._prev_try

    def test_candidate_ports_respects_try_count(self) -> None:
        os.environ["CPHARM_PORT"] = "9000"
        os.environ["CPHARM_PORT_TRY_COUNT"] = "3"
        self.assertEqual(sw._dashboard_candidate_ports(), [9000, 9001, 9002])

    @unittest.mock.patch.object(sw.urllib.request, "urlopen")
    def test_probe_sets_cache_from_api_config(self, mock_open: unittest.mock.MagicMock) -> None:
        os.environ["CPHARM_PORT"] = "8080"

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


if __name__ == "__main__":
    unittest.main()
