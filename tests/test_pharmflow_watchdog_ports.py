"""Watchdog ADB pass must not assume 8 localhost ports or stop at 32."""
from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import pharmflow_watchdog as wd  # noqa: E402


class WatchdogPortTests(unittest.TestCase):
    def test_omitted_count_uses_published_guests(self) -> None:
        serials = [f"10.0.2.{i}:5555" for i in range(20, 32)]
        args = argparse.Namespace(count=None, host="127.0.0.1", start_port=5555)
        with patch.object(wd, "_published_guest_serials", return_value=serials):
            targets = wd.adb_check_targets(args)
        self.assertEqual(len(targets), 12)
        self.assertTrue(all(host.startswith("10.0.2.") for host, _port in targets))
        self.assertNotIn(("127.0.0.1", 5555), targets)

    def test_explicit_count_is_not_clamped_at_32(self) -> None:
        args = argparse.Namespace(count=40, host="127.0.0.1", start_port=5555)
        targets = wd.adb_check_targets(args)
        self.assertEqual(len(targets), 40)
        self.assertEqual(targets[-1], ("127.0.0.1", 5594))

    def test_source_has_no_eight_or_thirty_two_ceiling(self) -> None:
        src = (ROOT / "tools" / "pharmflow_watchdog.py").read_text(encoding="utf-8")
        self.assertNotIn("DEFAULT_PORTS", src)
        self.assertNotIn("args.count > 32", src)
        self.assertNotIn('default=8', src)


if __name__ == "__main__":
    unittest.main()
