"""CREATE_NO_WINDOW must win over DETACHED_PROCESS / CREATE_NEW_CONSOLE."""

from __future__ import annotations

import sys
import unittest

from automation.no_window import (
    _CREATE_NEW_CONSOLE,
    _CREATE_NO_WINDOW,
    _DETACHED_PROCESS,
    pin_windows_console_host,
)


class NoWindowTests(unittest.TestCase):
    def test_conflicting_flags_are_stripped(self) -> None:
        flags = _DETACHED_PROCESS | _CREATE_NEW_CONSOLE | _CREATE_NO_WINDOW
        cleaned = (flags & ~(_DETACHED_PROCESS | _CREATE_NEW_CONSOLE)) | _CREATE_NO_WINDOW
        self.assertTrue(cleaned & _CREATE_NO_WINDOW)
        self.assertFalse(cleaned & _DETACHED_PROCESS)
        self.assertFalse(cleaned & _CREATE_NEW_CONSOLE)

    def test_pin_console_host_sets_registry(self) -> None:
        if sys.platform != "win32":
            self.skipTest("Windows only")
        pin_windows_console_host()
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Console\%%Startup")
        try:
            console, _ = winreg.QueryValueEx(key, "DelegationConsole")
            terminal, _ = winreg.QueryValueEx(key, "DelegationTerminal")
        finally:
            winreg.CloseKey(key)
        guid = "{B23D10C0-E52E-411E-9D5B-C09FDF709C7D}"
        self.assertEqual(console, guid)
        self.assertEqual(terminal, guid)


if __name__ == "__main__":
    unittest.main()
