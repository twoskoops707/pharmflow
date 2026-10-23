from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_AUTOMATION_DIR = Path(__file__).resolve().parent
if str(_AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(_AUTOMATION_DIR))

import mumu_fingerprint as mf  # noqa: E402


class MumuFingerprintTests(unittest.TestCase):
    def test_profile_for_model_farm_presets(self):
        p = mf.profile_for_model("SM-S9110")
        self.assertIsNotNone(p)
        self.assertEqual(p["key"], "sm_s9110")
        p2 = mf.profile_for_model("XQ-DE72")
        self.assertIsNotNone(p2)
        self.assertEqual(p2["key"], "xq_de72")

    def test_profile_for_index_scales_beyond_three(self):
        p0 = mf.profile_for_index(0)
        p1 = mf.profile_for_index(1)
        self.assertNotEqual(p0["key"], p1["key"])
        self.assertGreaterEqual(len(mf.RETAIL_PROFILE_POOL), 12)

    def test_user_agent_matches_profile_model(self):
        prof = mf.profile_for_model("GC3VE")
        self.assertIsNotNone(prof)
        ua = mf.build_mobile_user_agent(prof)
        self.assertIn("Pixel 7a", ua)
        self.assertIn("Android 14", ua)
        self.assertNotIn("sdk_gphone", ua.lower())

    def test_chromium_flags_disable_automation(self):
        prof = mf.PHONE_PROFILES[0]
        flags = mf.build_chromium_flags(prof)
        self.assertIn("--disable-blink-features=AutomationControlled", flags)
        self.assertIn("--user-agent=", flags)

    def test_patch_mumu_setting_json(self):
        with tempfile.TemporaryDirectory() as td:
            sp = Path(td) / "setting.json"
            sp.write_text(
                json.dumps(
                    {
                        "ResolutionPresetSelected": {"ResolutionType": "Tablet"},
                        "FramebufferWidth": 1600,
                        "FramebufferHeight": 900,
                    }
                ),
                encoding="utf-8",
            )
            prof = mf.PHONE_PROFILES[1]
            r = mf.patch_mumu_setting_json(sp, prof, randomize_ids=False)
            self.assertTrue(r["patched"])
            data = json.loads(sp.read_text(encoding="utf-8"))
            self.assertEqual(data["phonePropBrand"], prof["brand"])
            self.assertEqual(data["phonePropModel"], prof["model"])
            self.assertEqual(data["ResolutionPresetSelected"]["ResolutionType"], "Phone")
            self.assertEqual(data["FramebufferWidth"], 900)
            self.assertEqual(data["FramebufferHeight"], 1600)

    def test_patch_skips_when_profile_already_matches(self):
        prof = mf.PHONE_PROFILES[1]
        gpu = prof.get("gpu_preset")
        with tempfile.TemporaryDirectory() as td:
            sp = Path(td) / "setting.json"
            payload = {
                "phonePropBrand": prof["brand"],
                "phonePropModel": prof["model"],
                "phoneModel": prof["model"],
                "phonePropMiit": prof.get("miit") or prof["model"],
                "ResolutionPresetSelected": {"ResolutionType": "Phone"},
                "DeviceOrientation": "Portrait",
                "FramebufferWidth": 900,
                "FramebufferHeight": 1600,
                "FramebufferDPI": 300,
            }
            if gpu:
                payload["phonePropGPUModel"] = gpu
                payload["gpuModel"] = gpu
                payload["GpuModel"] = gpu
            sp.write_text(json.dumps(payload), encoding="utf-8")
            before = sp.read_text(encoding="utf-8")
            r = mf.patch_mumu_setting_json(sp, prof, randomize_ids=True)
            after = sp.read_text(encoding="utf-8")
            self.assertFalse(r["patched"])
            self.assertEqual(r.get("note"), "already matched profile")
            self.assertEqual(before, after)

    def test_audit_detects_qemu_leak(self):
        props = {
            "ro.kernel.qemu": "1",
            "ro.product.model": "SM-S9110",
            "ro.product.manufacturer": "samsung",
            "ro.product.brand": "samsung",
            "ro.hardware": "qcom",
            "ro.build.characteristics": "phone",
        }

        def fake_getprop(serial: str, name: str) -> str:
            return props.get(name, "")

        with mock.patch.object(mf, "getprop", side_effect=fake_getprop):
            audit = mf.audit_device_fingerprint("10.0.2.15:5555")
        self.assertTrue(any("ro.kernel.qemu" in x for x in audit.leaks))

    def test_audit_clean_retail_props(self):
        props = {
            "ro.kernel.qemu": "0",
            "ro.product.model": "SM-S9110",
            "ro.product.manufacturer": "samsung",
            "ro.product.brand": "samsung",
            "ro.hardware": "qcom",
            "ro.build.characteristics": "phone",
            "ro.product.device": "dm1q",
        }

        def fake_getprop(serial: str, name: str) -> str:
            return props.get(name, "")

        with (
            mock.patch.object(mf, "getprop", side_effect=fake_getprop),
            mock.patch.object(mf, "_shell", return_value=mock.Mock(returncode=0, stdout='--user-agent="SM-S9110"')),
        ):
            audit = mf.audit_device_fingerprint("10.0.2.15:5555")
        self.assertEqual(audit.leaks, [])

    def test_apply_all_serials_distinct_profiles(self):
        serials = ["10.0.2.144:5555", "10.0.2.15:5555", "10.0.2.16:5555"]

        with (
            mock.patch.object(mf, "apply_mumu_vm_fingerprints", return_value=[]),
            mock.patch.object(mf, "apply_browser_fingerprint_adb") as mock_apply,
            mock.patch.object(mf, "audit_device_fingerprint") as mock_audit,
        ):
            mock_apply.return_value = {"user_agent_written": True, "profile": "x", "model": "M"}
            mock_audit.return_value = mf.FingerprintAudit(
                serial="s", profile_key="x", leaks=[]
            )
            summary = mf.apply_fingerprint_all_serials(serials, patch_vms=False)
        self.assertEqual(len(summary["phones"]), 3)
        self.assertEqual(mock_apply.call_count, 3)

    def test_skip_env_disables_ensure(self):
        with mock.patch.dict("os.environ", {"PHARMFLOW_SKIP_FINGERPRINT": "1"}):
            r = mf.ensure_fingerprint_before_browse("serial")
        self.assertTrue(r.get("skipped"))


if __name__ == "__main__":
    unittest.main()
