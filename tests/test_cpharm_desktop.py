"""Tests for wizard/cpharm_desktop.py wizard structure."""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Headless CI may lack tkinter — stub before importing cpharm_desktop.
if "tkinter" not in sys.modules:
    tk_mod = types.ModuleType("tkinter")
    tk_mod.Tk = MagicMock
    tk_mod.Toplevel = MagicMock
    tk_mod.Frame = MagicMock
    tk_mod.Label = MagicMock
    tk_mod.Button = MagicMock
    tk_mod.Entry = MagicMock
    tk_mod.Text = MagicMock
    tk_mod.Listbox = MagicMock
    tk_mod.Checkbutton = MagicMock
    tk_mod.Radiobutton = MagicMock
    tk_mod.Canvas = MagicMock
    tk_mod.StringVar = MagicMock
    tk_mod.BooleanVar = MagicMock
    tk_mod.END = "end"
    tk_mod.scrolledtext = types.ModuleType("tkinter.scrolledtext")
    tk_mod.scrolledtext.ScrolledText = MagicMock
    tk_mod.messagebox = types.ModuleType("tkinter.messagebox")
    tk_mod.messagebox.askyesno = MagicMock(return_value=False)
    tk_mod.messagebox.showwarning = MagicMock()
    tk_mod.messagebox.showinfo = MagicMock()
    tk_mod.filedialog = types.ModuleType("tkinter.filedialog")
    tk_mod.filedialog.askopenfilename = MagicMock(return_value="")
    tk_mod.filedialog.askdirectory = MagicMock(return_value="")
    tk_mod.simpledialog = types.ModuleType("tkinter.simpledialog")
    tk_mod.simpledialog.askstring = MagicMock(return_value="")
    tk_mod.ttk = types.ModuleType("tkinter.ttk")
    tk_mod.ttk.Progressbar = MagicMock
    tk_mod.ttk.Combobox = MagicMock
    tk_mod.ttk.Scrollbar = MagicMock
    sys.modules["tkinter"] = tk_mod
    sys.modules["tkinter.scrolledtext"] = tk_mod.scrolledtext
    sys.modules["tkinter.messagebox"] = tk_mod.messagebox
    sys.modules["tkinter.filedialog"] = tk_mod.filedialog
    sys.modules["tkinter.simpledialog"] = tk_mod.simpledialog
    sys.modules["tkinter.ttk"] = tk_mod.ttk

from wizard.cpharm_desktop import WIZARD_STEPS, CPharmApp


class CPharmDesktopWizardTests(unittest.TestCase):
    def test_wizard_has_ten_steps(self) -> None:
        self.assertEqual(len(WIZARD_STEPS), 10)
        labels = [label for _, label in WIZARD_STEPS]
        self.assertEqual(
            labels,
            [
                "Start",
                "Install",
                "Android",
                "Phones",
                "Test",
                "Steps",
                "Builder",
                "Teams",
                "Play",
                "Run",
            ],
        )

    def test_screen_builders_exist(self) -> None:
        for step_id, _ in WIZARD_STEPS:
            method = f"_screen_{step_id}"
            self.assertTrue(hasattr(CPharmApp, method), f"missing {method}")

    def test_action_handlers_exist(self) -> None:
        handlers = (
            "_install_adb",
            "_install_browser",
            "_install_all",
            "_detect_mumu",
            "_create_phones",
            "_start_one",
            "_stop_one",
            "_start_all",
            "_stop_all",
            "_run_all_tests",
            "_verify_tor_all",
            "_save_built_sequence",
            "_create_team",
            "_run_sequence",
            "_run_sequence_all_phones",
            "_open_web",
            "_install_apk_all",
            "_pick_sequence_file",
            "_pick_sequence_folder",
            "_open_sequences_folder",
            "_builder_browse_apk",
            "_refresh_teams",
        )
        for name in handlers:
            self.assertTrue(hasattr(CPharmApp, name), f"missing {name}")

    def test_studio_editor_builders_imported(self) -> None:
        from wizard import studio_editors

        self.assertTrue(callable(studio_editors.build_steps_page))
        self.assertTrue(callable(studio_editors.build_builder_page))
        self.assertTrue(callable(studio_editors.build_teams_page))
        self.assertTrue(callable(studio_editors._teams_rebuild))

    def test_no_sequence_combo_attribute(self) -> None:
        self.assertFalse(hasattr(CPharmApp, "seq_combo"))

    def test_start_farm_button_refuses_external_python(self) -> None:
        """GUI Start farm must surface refuse when python money path is UP."""
        app = MagicMock(spec=CPharmApp)
        app._active_site_slug = "dabflow"
        app._log = MagicMock()
        with (
            patch("wizard.cpharm_desktop.apply_farm_prefs_to_environ"),
            patch("wizard.cpharm_desktop.load_farm_prefs", return_value={}),
            patch("wizard.cpharm_desktop.load_active_profile", return_value=None),
            patch("wizard.cpharm_desktop.start_farm", return_value=False) as sf,
            patch("wizard.cpharm_desktop.farm_running", return_value=False),
            patch("wizard.cpharm_desktop.external_python_farm_running", return_value=True),
            patch("wizard.cpharm_desktop.messagebox") as mb,
        ):
            CPharmApp._start_farm(app)
        sf.assert_called_once()
        mb.showwarning.assert_called_once()
        title, body = mb.showwarning.call_args[0][:2]
        self.assertEqual(title, "Start farm refused")
        self.assertIn("python farm", body.lower())


if __name__ == "__main__":
    unittest.main()
