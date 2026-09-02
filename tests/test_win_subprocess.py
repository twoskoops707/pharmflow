"""Tests for automation/win_subprocess.py."""

from __future__ import annotations

import subprocess
import sys
import unittest
from unittest.mock import patch

from automation.win_subprocess import hidden_run_kwargs


class WinSubprocessTests(unittest.TestCase):
    def test_non_windows_empty(self) -> None:
        with patch.object(sys, "platform", "linux"):
            self.assertEqual(hidden_run_kwargs(), {})

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_windows_hides_console(self) -> None:
        kwargs = hidden_run_kwargs()
        self.assertIn("creationflags", kwargs)
        self.assertEqual(kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)
        self.assertIn("startupinfo", kwargs)
        si = kwargs["startupinfo"]
        self.assertTrue(si.dwFlags & subprocess.STARTF_USESHOWWINDOW)


if __name__ == "__main__":
    unittest.main()
