"""Contract tests for PharmFlow EXE File/Edit/View/Options/Help menubar."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = (ROOT / "wizard" / "pharmflow_app_webview.py").read_text(encoding="utf-8-sig")
HTML = (ROOT / "wizard" / "assets" / "pharmflow_app" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.css").read_text(encoding="utf-8")


class MenubarContractTests(unittest.TestCase):
    def test_deck_html_has_full_menubar(self):
        self.assertIn('id="deck-menubar"', HTML)
        for label in ("File", "Edit", "View", "Options", "Help"):
            self.assertIn(f">{label}</button>", HTML)
        for action in (
            "file.open",
            "file.save",
            "file.import",
            "file.open_folder",
            "file.open_logs",
            "file.exit",
            "edit.undo",
            "edit.cut",
            "edit.copy",
            "edit.paste",
            "view.start",
            "view.go",
            "view.health",
            "view.farm_dash",
            "view.control_dash",
            "view.gate_status",
            "options.farm_prefs",
            "options.reset_step",
            "options.gate_status",
            "options.gate_status_full",
            "options.classic_wizard",
            "help.guide",
            "help.about",
        ):
            self.assertIn(f'data-menu-action="{action}"', HTML)

    def test_deck_css_styles_menubar(self):
        self.assertIn(".deck-menubar", CSS)
        self.assertIn(".deck-menu-panel", CSS)
        self.assertIn(".deck-menu-trigger", CSS)

    def test_js_menu_dispatch_is_ssot(self):
        self.assertIn("function wireDeckMenubar()", JS)
        self.assertIn("function menuAction(action)", JS)
        self.assertIn("window.__pharmflowMenuAction = menuAction", JS)
        self.assertIn("menuLoadSequence", JS)
        self.assertIn("menuSaveSequence", JS)
        self.assertIn("menuFarmPrefs", JS)
        self.assertIn("menuDumpGateStatus", JS)
        self.assertIn("dump_gate_status_fast", JS)
        self.assertIn("openAbout", JS)
        # No dead stub toasts for core actions
        self.assertNotIn("Coming soon", JS.split("function menuAction")[1].split("window.__pharmflowOpenHelp")[0])

    def test_native_menu_mirrors_deck_actions(self):
        block = WEB.split("def _build_native_menu(")[1].split("\n# WebView2")[0]
        for label in ('"File"', '"Edit"', '"View"', '"Options"', '"Help"'):
            self.assertIn(label, block)
        for action in (
            "file.open",
            "file.save",
            "file.import",
            "file.exit",
            "edit.copy",
            "view.start",
            "view.farm_dash",
            "view.gate_status",
            "options.farm_prefs",
            "options.gate_status",
            "options.gate_status_full",
            "help.guide",
            "help.about",
        ):
            self.assertIn(action, block)
        self.assertIn("__pharmflowMenuAction", block)

    def test_webview_exposes_folder_about_exit_apis(self):
        for name in (
            "open_pharmflow_folder",
            "open_logs_folder",
            "get_about_info",
            "exit_app",
            "dump_gate_status_fast",
        ):
            self.assertIn(f"def {name}(", WEB)


if __name__ == "__main__":
    unittest.main()
