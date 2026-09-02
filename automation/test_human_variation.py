"""Tests for the blake2b → sha256 fallback in human_variation.

The fallback exists because some constrained runtimes (e.g. very old or
custom-built CPython without OpenSSL/hashlib `blake2b`) raise
``AttributeError`` when calling ``hashlib.blake2b``. The scheduler / human
variance subsystem must keep producing stable per-device digests in that
environment, so we verify the keyed and unkeyed paths both fall through to
sha256 and return digests of the requested size.
"""
from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path
from unittest import mock

_AUTOMATION_DIR = Path(__file__).resolve().parent
if str(_AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(_AUTOMATION_DIR))

import human_variation  # noqa: E402


class DigestFallbackTests(unittest.TestCase):
    def test_blake2b_path_unkeyed_returns_requested_size(self):
        out = human_variation._digest_blake2b_or_sha256(b"abc", digest_size=8)
        self.assertIsInstance(out, bytes)
        self.assertEqual(len(out), 8)

    def test_blake2b_path_keyed_differs_from_unkeyed(self):
        unkeyed = human_variation._digest_blake2b_or_sha256(b"abc", digest_size=8)
        keyed = human_variation._digest_blake2b_or_sha256(
            b"abc", digest_size=8, key=b"k"
        )
        self.assertEqual(len(keyed), 8)
        self.assertNotEqual(unkeyed, keyed)

    def test_sha256_fallback_when_blake2b_missing_unkeyed(self):
        with mock.patch.object(
            hashlib, "blake2b", side_effect=AttributeError("blake2b unavailable")
        ):
            out = human_variation._digest_blake2b_or_sha256(b"abc", digest_size=8)
        expected = hashlib.sha256(b"abc").digest()[:8]
        self.assertEqual(out, expected)

    def test_sha256_fallback_when_blake2b_missing_keyed(self):
        with mock.patch.object(
            hashlib, "blake2b", side_effect=AttributeError("blake2b unavailable")
        ):
            out = human_variation._digest_blake2b_or_sha256(
                b"abc", digest_size=8, key=b"k"
            )
        expected = hashlib.sha256(b"k" + b"\x00" + b"abc").digest()[:8]
        self.assertEqual(out, expected)

    def test_stable_seed_works_under_fallback(self):
        with mock.patch.object(
            hashlib, "blake2b", side_effect=AttributeError("blake2b unavailable")
        ):
            seed_a = human_variation.stable_seed("emulator-5554", 12345)
            seed_b = human_variation.stable_seed("emulator-5554", 12345)
            seed_c = human_variation.stable_seed("emulator-5554", 12346)
        self.assertEqual(seed_a, seed_b)
        self.assertNotEqual(seed_a, seed_c)
        self.assertGreaterEqual(seed_a, 0)
        self.assertLess(seed_a, 1 << 64)

    def test_schedule_rng_keyed_path_works_under_fallback(self):
        with mock.patch.object(
            hashlib, "blake2b", side_effect=AttributeError("blake2b unavailable")
        ):
            rng_a = human_variation.schedule_rng("emulator-5554", 20260, 24)
            rng_b = human_variation.schedule_rng("emulator-5554", 20260, 24)
        sample_a = [rng_a.random() for _ in range(5)]
        sample_b = [rng_b.random() for _ in range(5)]
        self.assertEqual(sample_a, sample_b)


if __name__ == "__main__":
    unittest.main()
