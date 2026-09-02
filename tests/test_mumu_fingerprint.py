"""Tests for automation/mumu_fingerprint.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from automation.mumu_fingerprint import (
    FingerprintProfile,
    apply_mumu_vm_fingerprint,
    apply_mumu_vm_fingerprints,
    patch_setting_json,
    read_getprop_snapshot,
    verify_fingerprint_with_getprop,
    write_adb_flags,
)


def _sample_profile() -> FingerprintProfile:
    return FingerprintProfile(
        brand="samsung",
        manufacturer="samsung",
        model="SM-G950F",
        device="dreamlte",
        hardware="samsungexynos8895",
        bootloader="G950FXXU1AQDD",
        board="universal8895",
        build_fingerprint="samsung/dreamltexx/dreamlte:9/PPR1.180610.011/G950FXXU1AQDD:user/release-keys",
        imei="353325101234567",
        mac="02:11:22:33:44:55",
        android_id="abc123def4567890",
        serial_number="R58M90ABCDE",
        user_agent="Mozilla/5.0 (Linux; Android 9; SM-G950F) AppleWebKit/537.36 Chrome/96.0.4664.45 Mobile Safari/537.36",
        webgl_renderer="ARM Mali-G78",
        canvas_seed="deadbeef",
    )


class FingerprintEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.vms_dir = Path(self.tmp.name) / "vms"
        phone_dir = self.vms_dir / "Phone-01"
        phone_dir.mkdir(parents=True)
        (phone_dir / "setting.json").write_text("{}", encoding="utf-8")
        (phone_dir / "adb_flags").write_text("", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_patch_setting_json_writes_retail_values(self) -> None:
        path = self.vms_dir / "Phone-01" / "setting.json"
        profile = _sample_profile()
        patch_setting_json(path, profile)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["phone_brand"], "samsung")
        self.assertEqual(data["phone_model"], "SM-G950F")
        self.assertEqual(data["phone_imei"], profile.imei)
        self.assertEqual(data["PhoneProp"]["Miit"], "SM-G950F")
        self.assertEqual(data["phonePropMiit"], "SM-G950F")
        self.assertEqual(data["PhonePropMode"], "Custom")
        self.assertNotIn("mumu", json.dumps(data).lower())

    def test_write_adb_flags_sets_per_phone_props(self) -> None:
        profile = _sample_profile()
        write_adb_flags(self.vms_dir, "Phone-01", profile)
        flags = (self.vms_dir / "Phone-01" / "adb_flags").read_text(encoding="utf-8")
        self.assertIn("ro.product.model=SM-G950F", flags)
        self.assertIn("ro.kernel.qemu=", flags)
        self.assertIn("ro.secure=1", flags)
        self.assertIn("ro.debuggable=0", flags)
        self.assertIn("user_agent=", flags)

    def test_apply_mumu_vm_fingerprints_batch(self) -> None:
        phone2 = self.vms_dir / "Phone-02"
        phone2.mkdir()
        (phone2 / "setting.json").write_text("{}", encoding="utf-8")
        (phone2 / "adb_flags").write_text("", encoding="utf-8")

        applied = apply_mumu_vm_fingerprints(self.vms_dir, ["Phone-01", "Phone-02"])
        self.assertEqual(set(applied.keys()), {"Phone-01", "Phone-02"})
        for name in applied:
            setting = json.loads((self.vms_dir / name / "setting.json").read_text(encoding="utf-8"))
            self.assertIn("phone_brand", setting)

    def test_verify_fingerprint_with_getprop_passes_retail_device(self) -> None:
        profile = _sample_profile()
        props = {
            "ro.kernel.qemu": "",
            "ro.product.model": profile.model,
            "ro.product.brand": profile.brand,
            "ro.product.manufacturer": profile.manufacturer,
            "ro.product.device": profile.device,
            "ro.hardware": profile.hardware,
            "ro.bootloader": profile.bootloader,
            "ro.build.fingerprint": profile.build_fingerprint,
            "ro.debuggable": "0",
            "ro.secure": "1",
            "ro.adb.secure": "1",
        }

        def getprop(key: str) -> str:
            return props.get(key, "")

        report = verify_fingerprint_with_getprop(getprop, profile, phone="Phone-01")
        self.assertTrue(report.passed)
        self.assertEqual(read_getprop_snapshot(getprop), props)

    def test_verify_soft_passes_when_profile_mismatches_but_retail_clean(self) -> None:
        """MuMu ARM may still show PhoneProp until cold boot — don't fail overall."""
        profile = _sample_profile()
        props = {
            "ro.kernel.qemu": "",
            "ro.product.model": "SM-S9180",
            "ro.product.brand": "Samsung",
            "ro.product.manufacturer": "Samsung",
            "ro.product.device": "SM-S9180",
            "ro.hardware": "SM-S9180",
            "ro.bootloader": "unknown",
            "ro.build.fingerprint": "samsung/release-keys",
            "ro.debuggable": "0",
            "ro.secure": "1",
            "ro.adb.secure": "1",
        }

        def getprop(key: str) -> str:
            return props.get(key, "")

        report = verify_fingerprint_with_getprop(getprop, profile, phone="vm0")
        self.assertTrue(report.passed)
        self.assertFalse(report.checks.get("model_match", True))
        self.assertTrue(any("model mismatch" in f for f in report.failures))

    def test_verify_fingerprint_fails_on_qemu(self) -> None:
        def getprop(key: str) -> str:
            return "1" if key == "ro.kernel.qemu" else ""

        report = verify_fingerprint_with_getprop(getprop, phone="Phone-01")
        self.assertFalse(report.passed)
        self.assertIn("ro.kernel.qemu", report.failures[0])

    def test_apply_mumu_vm_fingerprint_single(self) -> None:
        profile = _sample_profile()
        result = apply_mumu_vm_fingerprint(self.vms_dir, "Phone-01", profile=profile)
        self.assertEqual(result.model, "SM-G950F")


    def test_profile_matching_model_aligns_with_browser(self) -> None:
        from automation.mumu_fingerprint import profile_matching_model

        prof = profile_matching_model(
            "SM-S918B", brand="samsung", android_id="abcd1234abcd1234", imei="353325101234567"
        )
        self.assertEqual(prof.model, "SM-S918B")
        self.assertEqual(prof.android_id, "abcd1234abcd1234")
        self.assertEqual(prof.imei, "353325101234567")

    def test_retail_pool_has_variety(self) -> None:
        from automation.mumu_fingerprint import RETAIL_PROFILES

        models = {p["model"] for p in RETAIL_PROFILES}
        self.assertGreaterEqual(len(models), 15)


if __name__ == "__main__":
    unittest.main()
