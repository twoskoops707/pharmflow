"""Tests for Chromium first-run UI dismissal helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_AUTO = Path(__file__).resolve().parent
if str(_AUTO) not in sys.path:
    sys.path.insert(0, str(_AUTO))

import chromium_fre_uia as fre  # noqa: E402


_SAMPLE_FRE = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node text="Welcome to Chrome" bounds="[0,0][900,1600]" />
  <node text="Skip ahead" clickable="true" bounds="[300,1400][600,1500]" />
</hierarchy>
"""

_SAMPLE_SYNC = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node content-desc="Use without an account" clickable="true" bounds="[100,1200][800,1300]" />
</hierarchy>
"""


class ChromiumFreUiaTests(unittest.TestCase):
    def test_finds_skip_ahead_center(self) -> None:
        hit = fre._find_fre_tap(_SAMPLE_FRE)
        self.assertIsNotNone(hit)
        center, label = hit  # type: ignore[misc]
        self.assertEqual(label, "skip ahead")
        self.assertEqual(center, (450, 1450))

    def test_prefers_skip_over_accept(self) -> None:
        xml = """<hierarchy>
          <node text="Accept &amp; continue" bounds="[100,1400][800,1500]" />
          <node text="Skip" bounds="[700,50][880,120]" />
        </hierarchy>"""
        hit = fre._find_fre_tap(xml)
        self.assertIsNotNone(hit)
        _center, label = hit  # type: ignore[misc]
        self.assertEqual(label, "skip")

    def test_finds_stay_signed_out(self) -> None:
        xml = """<hierarchy>
          <node text="Stay signed out" clickable="true" bounds="[200,1300][700,1400]" />
        </hierarchy>"""
        hit = fre._find_fre_tap(xml)
        self.assertIsNotNone(hit)
        center, label = hit  # type: ignore[misc]
        self.assertEqual(label, "stay signed out")
        self.assertEqual(center, (450, 1350))

    def test_finds_use_without_account(self) -> None:
        hit = fre._find_fre_tap(_SAMPLE_SYNC)
        self.assertIsNotNone(hit)
        _center, label = hit  # type: ignore[misc]
        self.assertEqual(label, "use without an account")


if __name__ == "__main__":
    unittest.main()
