"""Set up Tor must not call a missing pin 'ready' or compress slots."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.dashboard import _guest_loopback_pinned, _tor_setup_line  # noqa: E402


class TorSetupLineTests(unittest.TestCase):
    def test_socks_up_without_a_pin_is_not_ready(self) -> None:
        line = _tor_setup_line(
            "vm20",
            ok_socks=True,
            ok_http=True,
            pinned=False,
            w_socks=30,
            w_http=30,
        )
        self.assertNotIn("Tor ready", line)
        self.assertIn("FAILED", line)
        self.assertIn("loopback", line)

    def test_ready_requires_a_loopback_pin(self) -> None:
        line = _tor_setup_line(
            "vm20",
            ok_socks=True,
            ok_http=True,
            pinned=True,
            w_socks=30,
            w_http=30,
        )
        self.assertEqual(line, "vm20: Tor ready")
        self.assertTrue(_guest_loopback_pinned({"http_proxy_applied": True, "http_proxy": "127.0.0.1:8238"}))
        self.assertFalse(_guest_loopback_pinned({"http_proxy_applied": True, "http_proxy": "10.0.2.2:8118"}))
        self.assertFalse(_guest_loopback_pinned({"http_proxy_applied": False, "http_proxy": "127.0.0.1:8118"}))

    def test_setup_and_groups_do_not_number_only_the_phones_that_answered(self) -> None:
        src = (ROOT / "automation" / "dashboard.py").read_text(encoding="utf-8")
        setup = src.split('if path == "/api/proxy/setup":', 1)[1].split('if path == "/api/proxy/rotate":', 1)[0]
        self.assertIn("_phone_idx_from_serial", setup)
        self.assertNotIn("register_tor_slot(p[\"serial\"], i)", setup)
        groups = src.split("def _start_groups_pipeline", 1)[1].split("def ", 1)[0]
        self.assertNotIn("register_tor_slot(_ser, _slot_i)", groups)
        self.assertIn("register_tor_slot(_ser, _phone_idx_from_serial(_ser))", groups)


if __name__ == "__main__":
    unittest.main()
