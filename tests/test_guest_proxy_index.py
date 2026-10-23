"""Guest-proxy index lookup must not stop at phone 16."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.farm_checkin import _idx_from_guest_proxy  # noqa: E402


class GuestProxyIndexTests(unittest.TestCase):
    def test_inject_port_past_phone_15_is_that_phone(self) -> None:
        with (
            patch("automation.farm_checkin._roster_indexes", return_value=[]),
            patch("automation.mantis_inject_proxy.INJECT_BASE", 8218),
            patch("automation.mantis_inject_proxy.phone_inject_port", side_effect=lambda i: 8218 + int(i)),
            patch("automation.tor_manager.HTTP_TUNNEL_BASE", 8118),
            patch("automation.tor_manager.phone_http_port", side_effect=lambda i: 8118 + int(i)),
        ):
            self.assertEqual(_idx_from_guest_proxy("127.0.0.1:8238"), 20)

    def test_tor_port_past_phone_15_is_that_phone(self) -> None:
        with (
            patch("automation.farm_checkin._roster_indexes", return_value=[]),
            patch("automation.mantis_inject_proxy.INJECT_BASE", 8218),
            patch("automation.mantis_inject_proxy.phone_inject_port", side_effect=lambda i: 8218 + int(i)),
            patch("automation.tor_manager.HTTP_TUNNEL_BASE", 8118),
            patch("automation.tor_manager.phone_http_port", side_effect=lambda i: 8118 + int(i)),
        ):
            self.assertEqual(_idx_from_guest_proxy("127.0.0.1:8138"), 20)

    def test_roster_slot_wins_over_a_linear_zero(self) -> None:
        def _http(idx: int) -> int:
            return 8118 if int(idx) == 39 else 8118 + int(idx)

        with (
            patch("automation.farm_checkin._roster_indexes", return_value=[39]),
            patch("automation.mantis_inject_proxy.INJECT_BASE", 8218),
            patch("automation.mantis_inject_proxy.phone_inject_port", side_effect=lambda i: 8218 + int(i)),
            patch("automation.tor_manager.HTTP_TUNNEL_BASE", 8118),
            patch("automation.tor_manager.phone_http_port", side_effect=_http),
        ):
            self.assertEqual(_idx_from_guest_proxy("127.0.0.1:8118"), 39)

    def test_cleared_proxy_is_not_an_index(self) -> None:
        self.assertIsNone(_idx_from_guest_proxy(""))
        self.assertIsNone(_idx_from_guest_proxy(":0"))
        self.assertIsNone(_idx_from_guest_proxy("127.0.0.1:0"))

    def test_source_does_not_scan_sixteen_indexes(self) -> None:
        src = (ROOT / "automation" / "farm_checkin.py").read_text(encoding="utf-8")
        body = src.split("def _idx_from_guest_proxy", 1)[1].split("def _proxy_ok_for_serial", 1)[0]
        self.assertNotIn("range(16)", body)


if __name__ == "__main__":
    unittest.main()
