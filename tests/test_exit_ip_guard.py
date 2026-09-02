"""Tests for automation/exit_ip_guard.py."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from automation.exit_ip_guard import (
    enforce_farm_unique_exit_ips,
    find_shared_exit_ips,
    probe_phone_exit_ip,
)


class ExitIpGuardTests(unittest.TestCase):
    def test_find_shared_exit_ips(self) -> None:
        shared = find_shared_exit_ips(
            {
                "vm0.gmadoa": "1.1.1.1",
                "vm1.gmadoa": "2.2.2.2",
                "vm2.gmadoa": "1.1.1.1",
            }
        )
        self.assertEqual(shared, {"1.1.1.1": ["vm0.gmadoa", "vm2.gmadoa"]})

    def test_probe_prefers_tor_fetch(self) -> None:
        tor = MagicMock()
        tor.fetch_exit_ip.return_value = "9.9.9.9"
        adb = MagicMock()
        ip = probe_phone_exit_ip(tor, 0, "10.0.2.1:5555", adb)
        self.assertEqual(ip, "9.9.9.9")
        adb.shell.assert_not_called()

    def test_enforce_rotates_colliding_phone(self) -> None:
        tor = MagicMock()
        adb = MagicMock()
        rows = [
            ("vm0.gmadoa", "10.0.2.1:5555", 0),
            ("vm1.gmadoa", "10.0.2.2:5555", 1),
        ]

        class _Result:
            ok = True
            before = "1.1.1.1"
            after = "3.3.3.3"
            error = ""

        with patch(
            "automation.exit_ip_guard.audit_concurrent_exit_ips",
            side_effect=[
                {"shared": {"1.1.1.1": ["vm0.gmadoa", "vm1.gmadoa"]}, "phones": {}},
                {"shared": {}, "phones": {"vm0.gmadoa": "1.1.1.1", "vm1.gmadoa": "3.3.3.3"}},
            ],
        ):
            tor.rotate_until_unique_ip.return_value = _Result()
            fixes = enforce_farm_unique_exit_ips(tor, adb, rows, max_rounds=2)
        tor.rotate_until_unique_ip.assert_called_once()
        self.assertTrue(any("exit_ip_unique OK" in f for f in fixes))


if __name__ == "__main__":
    unittest.main()
