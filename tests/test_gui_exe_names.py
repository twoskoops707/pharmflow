import unittest

from automation.process_scan import GUI_EXE_NAMES


class GuiExeNameTests(unittest.TestCase):
    def test_current_and_legacy_control_panel_count(self) -> None:
        self.assertIn("pharmflow.exe", GUI_EXE_NAMES)
        self.assertIn("cpharm.exe", GUI_EXE_NAMES)


if __name__ == "__main__":
    unittest.main()
