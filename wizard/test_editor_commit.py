"""Group and step saves must fail when disk does not keep them."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / "wizard"
if str(WIZARD) not in sys.path:
    sys.path.insert(0, str(WIZARD))

import pharmflow_wizard_bridge as bridge  # noqa: E402
from setup_wizard import state  # noqa: E402


class EditorCommitTests(unittest.TestCase):
    def test_group_save_fails_when_no_phone_is_assigned(self) -> None:
        prev_groups = state.get("groups")
        prev_steps = state.get("default_steps")
        try:
            with self._tmp_paths():
                state["groups"] = [{"name": "Group 1", "phones": {}}]
                state["default_steps"] = []
                before_groups, before_steps = bridge._editor_snapshot()
                state["groups"].append({"name": "Group 2", "phones": {}})
                with patch("setup_wizard._persist_groups_config", return_value=None):
                    err = bridge._commit_editor_state(
                        require_groups=True,
                        require_steps=False,
                        before_groups=before_groups,
                        before_steps=before_steps,
                    )
                self.assertEqual([g.get("name") for g in state["groups"]], ["Group 1"])
        finally:
            state["groups"] = prev_groups
            state["default_steps"] = prev_steps
        self.assertIsNotNone(err)
        self.assertIn("no phones are assigned", err or "")

    def test_group_save_keeps_the_disk_copy(self) -> None:
        prev_groups = state.get("groups")
        prev_steps = state.get("default_steps")
        try:
            with self._tmp_paths() as (groups_path, steps_path):
                state["groups"] = [
                    {
                        "name": "Live",
                        "phones": {"10.0.2.16:5555": {"steps": [{"type": "wait", "seconds": 1}]}},
                    }
                ]
                state["default_steps"] = [{"type": "wait", "seconds": 1}]
                err = bridge._commit_editor_state(require_groups=True, require_steps=True)
                self.assertIsNone(err)
                stored = json.loads(groups_path.read_text(encoding="utf-8"))
                self.assertEqual(stored["groups"], state["groups"])
                self.assertTrue(steps_path.is_file())
        finally:
            state["groups"] = prev_groups
            state["default_steps"] = prev_steps

    def test_group_save_rolls_back_when_the_write_does_not_land(self) -> None:
        prev_groups = state.get("groups")
        prev_steps = state.get("default_steps")
        try:
            with self._tmp_paths() as (groups_path, _steps_path):
                original = [{"name": "Live", "phones": {"10.0.2.16:5555": {"steps": [{"type": "wait"}]}}}]
                groups_path.write_text(
                    json.dumps({"groups": original}) + "\n",
                    encoding="utf-8",
                )
                state["groups"] = original
                state["default_steps"] = []
                before_groups, before_steps = bridge._editor_snapshot()
                state["groups"] = original + [{"name": "Phantom", "phones": {"10.0.2.16:5555": {"steps": []}}}]
                with patch("setup_wizard._persist_groups_config", return_value=None):
                    err = bridge._commit_editor_state(
                        require_groups=True,
                        require_steps=False,
                        before_groups=before_groups,
                        before_steps=before_steps,
                    )
                self.assertIn("not saved", err or "")
                self.assertEqual(state["groups"], original)
                stored = json.loads(groups_path.read_text(encoding="utf-8"))
                self.assertEqual(stored["groups"], original)
        finally:
            state["groups"] = prev_groups
            state["default_steps"] = prev_steps

    def test_starter_sequence_is_not_the_default_unless_disk_matches(self) -> None:
        prev_groups = state.get("groups")
        prev_steps = state.get("default_steps")
        try:
            state["groups"] = [{"name": "empty", "phones": {}}]
            state["default_steps"] = []
            with self._tmp_paths() as (_groups_path, steps_path):
                starter = steps_path.parent / "starter.json"
                steps = [{"type": "open_url", "url": "https://example.com"}]

                def fake_save(payload, host, output_dir=None):
                    starter.write_text(json.dumps(payload), encoding="utf-8")
                    return starter

                with (
                    patch.object(
                        bridge,
                        "last_completed_scan",
                        return_value={"pages": [{"url": "https://example.com"}]},
                    ),
                    patch(
                        "site_mapper.build_starter_sequence",
                        return_value={"steps": steps, "note": "draft", "pages_mapped": 1},
                    ),
                    patch("site_mapper.save_sequence", side_effect=fake_save),
                    patch("setup_wizard._persist_default_steps", return_value=None),
                ):
                    failed = bridge.apply_site_sequence("https://example.com")
                self.assertFalse(failed["ok"])
                self.assertNotIn("saved", failed)
                self.assertFalse(starter.is_file())
                self.assertEqual(state["default_steps"], [])

                def real_steps_write():
                    from setup_wizard import _persist_default_steps

                    return _persist_default_steps()

                with (
                    patch.object(
                        bridge,
                        "last_completed_scan",
                        return_value={"pages": [{"url": "https://example.com"}]},
                    ),
                    patch(
                        "site_mapper.build_starter_sequence",
                        return_value={"steps": steps, "note": "draft", "pages_mapped": 1},
                    ),
                    patch("site_mapper.save_sequence", side_effect=fake_save),
                ):
                    saved = bridge.apply_site_sequence("https://example.com")
                self.assertTrue(saved.get("ok"))
                self.assertTrue(saved.get("saved"))
                self.assertEqual(json.loads(steps_path.read_text(encoding="utf-8"))["steps"], steps)
        finally:
            state["groups"] = prev_groups
            state["default_steps"] = prev_steps

    def test_first_run_setup_uses_the_real_setup_and_phone_setup_is_visible(self) -> None:
        setup = (WIZARD / "setup_desktop.py").read_text(encoding="utf-8")
        desktop = (WIZARD / "pharmflow_desktop.py").read_text(encoding="utf-8")
        self.assertNotIn("MuMuSetupCore", setup)
        self.assertNotIn("create_all_phones", setup)
        worker = setup.split("def _setup_worker")[1].split("\ndef ")[0]
        self.assertIn("run_full_setup", worker)
        self.assertIn("if not ok or not live", worker)
        spawn = desktop.split("def _launch_phone_setup_subprocess")[1].split("\ndef ")[0]
        call = spawn.split("subprocess.Popen", 1)[1]
        self.assertNotIn("DETACHED_PROCESS", call)
        self.assertNotIn("CREATE_NO_WINDOW", call)
        self.assertIn("SW_SHOWNORMAL", spawn)
        menu = desktop.split("def run_main_window")[1].split("def _examples_dir")[0]
        self.assertNotIn("Preferences", menu)
        self.assertNotIn('state="disabled"', menu)

    def test_classic_dashboard_menu_does_not_open_a_dead_url(self) -> None:
        src = (WIZARD / "pharmflow_desktop.py").read_text(encoding="utf-8")
        block = src.split("def _try_open_dashboard")[1].split("\ndef ")[0]
        self.assertIn("if not probe_dashboard_listen_port()", block)
        self.assertIn("opened = bool(webbrowser.open(url))", block)
        self.assertIn("browser did not open", block)

    def test_classic_clone_does_not_claim_copied_unless_groups_are_written(self) -> None:
        src = (WIZARD / "setup_wizard.py").read_text(encoding="utf-8")
        block = src.split("def clone_all")[1].split("\n                    cl_img")[0]
        self.assertIn("_persist_groups_config()", block)
        self.assertIn("Copy was not saved", block)
        self.assertLess(block.find("_persist_groups_config()"), block.find("copied to all phones"))

    def test_empty_group_does_not_replace_groups_that_already_have_phones(self) -> None:
        import tempfile

        import mumu_setup_core as core

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "groups_config.json"
            existing = {
                "groups": [
                    {
                        "name": "Live",
                        "phones": {"10.0.2.15:5555": {"steps": [{"type": "wait", "seconds": 9}]}},
                    },
                    {"name": "Empty", "phones": {}},
                ]
            }
            path.write_text(json.dumps(existing), encoding="utf-8")
            with patch.object(core, "_groups_config_path", return_value=path), patch.object(
                core, "write_groups_config"
            ) as writer:
                out, wrote = core.repair_groups_if_empty(["10.0.2.16:5555"], Path(tmp))
            writer.assert_not_called()
            self.assertFalse(wrote)
            self.assertEqual(out, path)
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(stored["groups"][0]["phones"]["10.0.2.15:5555"]["steps"][0]["seconds"], 9)

    def test_classic_add_and_remove_group_persist_before_rebuild(self) -> None:
        src = (WIZARD / "setup_wizard.py").read_text(encoding="utf-8")
        add = src.split("def _add_group")[1].split("\n    def _remove_group")[0]
        self.assertIn("_write_groups_or_warn", add)
        self.assertLess(add.find("_write_groups_or_warn"), add.find("self._rebuild()"))
        self.assertIn('state["groups"].pop()', add)
        rem = src.split("def _remove_group")[1].split("\n    def _rebuild")[0]
        self.assertIn("_write_groups_or_warn", rem)
        self.assertLess(rem.find("_write_groups_or_warn"), rem.find("self._rebuild()"))
        self.assertIn('state["groups"].insert', rem)
        name = src.split("def _persist_name")[1].split("name_ent.bind")[0]
        self.assertIn("_write_groups_or_warn", name)
        timing = src.split("def save(*_):")[1].split("def int_timing_entry")[0]
        self.assertIn("_write_groups_or_warn", timing)
        hits = src.split("def persist_hits")[1].split("hits_ent.bind")[0]
        self.assertIn("_write_groups_or_warn", hits)
        ready_log = src.split('MuMuPlayer phone(s) ready.\\n")')[0]
        self.assertIn("if phones:", ready_log[-80:])
        self.assertIn("No phones connected. Nothing is ready.", src)

    def test_classic_natural_timing_does_not_claim_applied_unless_groups_are_written(self) -> None:
        src = (WIZARD / "setup_wizard.py").read_text(encoding="utf-8")
        block = src.split("def _humanize_all_sequences")[1].split("\n    def ")[0]
        self.assertIn("_persist_groups_config()", block)
        self.assertIn("Natural timing was not saved", block)
        self.assertLess(block.find("_persist_groups_config()"), block.find("Applied natural timing"))
        self.assertLess(block.find("Natural timing was not saved"), block.find("Applied natural timing"))

    def test_setup_log_does_not_paint_a_negative_line_green(self) -> None:
        js = (WIZARD / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        fn = js.split("function classifySetupLine")[1].split("function setBusy")[0]
        warn = fn.split("log-line-warn")[0]
        ok = fn.split("log-line-ok")[0]
        self.assertIn("not ready", warn)
        self.assertIn("not installed", warn)
        self.assertLess(fn.find("log-line-warn"), fn.find("log-line-ok"))
        self.assertIn("\\bready\\b", ok)
        append = js.split("function appendLog")[1].split("function classifySetupLine")[0]
        self.assertIn("perLine", append)
        self.assertIn("classifySetupLine(line)", append)
        mapped = js.split("function logClass")[1].split("function appendLog")[0]
        self.assertIn('cls === "err"', mapped)
        self.assertIn("log-line-err", mapped)
        self.assertIn("log-line-warn", mapped)

    def test_deck_toasts_require_a_saved_flag(self) -> None:
        js = (WIZARD / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        for label in ("Add group failed", "Rename group failed", "Remove group failed", "Add step failed"):
            start = js.find(label)
            self.assertGreater(start, 0, label)
            window = js[start - 220:start]
            self.assertIn("res.saved !== true", window, label)
        gen = js.split("Generate sequence")[1].split("refreshSteps")[0]
        self.assertIn("res.saved !== true", gen)
        seq = js.split('showToast("Sequence saved")')[0]
        self.assertIn("res.saved === true", seq[-180:])
        site = js.split("Site URL was not saved")[0]
        self.assertIn("res.saved !== true", site[-220:])

    def _tmp_paths(self):
        import tempfile
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            with tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                groups = root / "groups_config.json"
                steps = root / "default_sequence.json"

                def groups_path():
                    return groups

                def steps_path():
                    return steps

                with (
                    patch("setup_wizard.groups_config_path", groups_path),
                    patch("wizard_paths.groups_config_path", groups_path),
                    patch("wizard_paths.default_sequence_path", steps_path),
                ):
                    yield groups, steps

        return _ctx()


if __name__ == "__main__":
    unittest.main()
