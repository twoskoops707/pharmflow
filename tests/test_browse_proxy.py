"""Tests for browse_proxy scramble mode defaults and guest proxy pinning."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from automation import browse_proxy as bp


class BrowseProxyTests(unittest.TestCase):
    def test_default_mode_is_scramble(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch.object(bp, "load_browse_prefs", return_value={}):
                self.assertEqual(bp.browse_proxy_mode(), "scramble")

    def test_prefs_override_mode(self) -> None:
        with patch.object(bp, "load_browse_prefs", return_value={"browse_proxy_mode": "tor"}):
            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(bp.browse_proxy_mode(), "tor")

    def test_dabflow_browse_active_for_scramble(self) -> None:
        with patch.object(bp, "browse_proxy_mode", return_value="scramble"):
            self.assertTrue(bp.dabflow_browse_active())


class GuestProxyHealthTests(unittest.TestCase):
    def test_rejects_cleared_values(self) -> None:
        for bad in ("", ":0", "null", "NULL", "none", "undefined"):
            self.assertFalse(bp.guest_proxy_healthy(bad), msg=repr(bad))

    def test_accepts_inject_endpoint(self) -> None:
        with patch.dict("os.environ", {"CPHARM_MANTIS_INJECT_PROXY": "1"}):
            self.assertTrue(bp.guest_proxy_healthy("127.0.0.1:8218", phone_idx=0))
            self.assertTrue(bp.guest_proxy_healthy("127.0.0.1:8220", phone_idx=2))

    def test_rejects_wrong_phone_port(self) -> None:
        with patch.dict("os.environ", {"CPHARM_MANTIS_INJECT_PROXY": "1"}):
            self.assertFalse(bp.guest_proxy_healthy("127.0.0.1:8219", phone_idx=0))


class PinGuestProxyTests(unittest.TestCase):
    def _adb_with_reads(self, reads: list[str]) -> MagicMock:
        adb = MagicMock()
        queue = list(reads)

        def _shell(cmd: str, serial: str | None = None, **_kw: object) -> MagicMock:
            out = MagicMock()
            if "settings get global http_proxy" in cmd:
                out.stdout = queue.pop(0) if queue else "127.0.0.1:8218"
            else:
                out.stdout = ""
            return out

        adb.shell.side_effect = _shell
        adb.set_http_proxy = MagicMock()
        adb.reverse = MagicMock()
        adb.run = MagicMock()
        return adb

    def test_pin_does_not_treat_colon_zero_as_success(self) -> None:
        """Race: settings get still returns :0 after put — must retry, not return :0."""
        adb = self._adb_with_reads([":0", ":0", "127.0.0.1:8218", "127.0.0.1:8218"])
        with patch.dict("os.environ", {"CPHARM_MANTIS_INJECT_PROXY": "1"}):
            with patch(
                "automation.mantis_inject_proxy.point_phone_at_inject",
                return_value="127.0.0.1:8218",
            ):
                with patch("time.sleep"):
                    got = bp.pin_guest_proxy(adb, "10.0.2.199:5555", 0, attempts=3)
        self.assertEqual(got, "127.0.0.1:8218")
        self.assertTrue(bp.guest_proxy_healthy(got, phone_idx=0))

    def test_pin_idempotent_when_already_healthy(self) -> None:
        adb = self._adb_with_reads(["127.0.0.1:8219"])
        with patch.dict("os.environ", {"CPHARM_MANTIS_INJECT_PROXY": "1"}):
            with patch(
                "automation.mantis_inject_proxy.point_phone_at_inject"
            ) as point:
                got = bp.pin_guest_proxy(adb, "10.0.2.44:5555", 1, attempts=3)
        self.assertEqual(got, "127.0.0.1:8219")
        point.assert_not_called()

    def test_pin_retries_after_null(self) -> None:
        adb = self._adb_with_reads(["null", "null", "127.0.0.1:8220"])
        with patch.dict("os.environ", {"CPHARM_MANTIS_INJECT_PROXY": "1"}):
            with patch(
                "automation.mantis_inject_proxy.point_phone_at_inject",
                return_value="127.0.0.1:8220",
            ):
                with patch("time.sleep"):
                    got = bp.pin_guest_proxy(adb, "10.0.2.32:5555", 2, attempts=3)
        self.assertEqual(got, "127.0.0.1:8220")


class RestoreBrowseSessionTests(unittest.TestCase):
    def test_restore_pins_after_tor_start(self) -> None:
        adb = MagicMock()
        with patch.object(bp, "browse_proxy_mode", return_value="tor"):
            with patch("automation.config.require_unique_exit_ip", return_value=True):
                with patch("automation.tor_manager.TorManager") as tor_cls:
                    tor_cls.return_value.start_phone_tor = MagicMock()
                    with patch.object(
                        bp, "pin_guest_proxy", return_value="127.0.0.1:8218"
                    ) as pin:
                        out = bp.restore_browse_session(adb, "10.0.2.199:5555", 0)
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("http_proxy"), "127.0.0.1:8218")
        pin.assert_called()


class ResumeTorAfterAdsTests(unittest.TestCase):
    def test_resume_restores_when_proxy_null_even_if_not_paused(self) -> None:
        from automation import emulator_ad_mode as eam

        adb = MagicMock()
        adb.shell.return_value = MagicMock(stdout="null")
        eam._paused.clear()
        with patch.object(eam, "browse_proxy_mode", return_value="tor"):
            with patch("automation.config.require_unique_exit_ip", return_value=True):
                with patch(
                    "automation.browse_proxy.restore_browse_session",
                    return_value={"ok": True, "http_proxy": "127.0.0.1:8218"},
                ) as restore:
                    with patch(
                        "automation.browse_proxy.pin_guest_proxy",
                        return_value="127.0.0.1:8218",
                    ):
                        out = eam.resume_tor_after_ads(adb, "10.0.2.199:5555", 0)
        restore.assert_called_once()
        self.assertEqual(out.get("http_proxy"), "127.0.0.1:8218")
        self.assertTrue(out.get("ok") or out.get("pinned"))


class RestoreInjectAfterIdentityTests(unittest.TestCase):
    def test_chromium_repins_inject_after_colon_zero(self) -> None:
        adb = MagicMock()
        reads = [":0", "127.0.0.1:8221", "127.0.0.1:8221"]

        def _shell(cmd: str, serial: str | None = None, **_kw: object) -> MagicMock:
            out = MagicMock()
            if "settings get global http_proxy" in cmd:
                out.stdout = reads.pop(0) if reads else "127.0.0.1:8221"
            else:
                out.stdout = ""
            return out

        adb.shell.side_effect = _shell
        adb.set_http_proxy = MagicMock()
        adb.reverse = MagicMock()
        adb.run = MagicMock()
        with patch.dict("os.environ", {"CPHARM_MANTIS_INJECT_PROXY": "1"}):
            with patch(
                "automation.mantis_inject_proxy.ensure_inject_for_phone",
                return_value={"ok": True, "endpoint": "127.0.0.1:8221", "port": 8221},
            ):
                with patch("time.sleep"):
                    got = bp.restore_inject_after_identity(
                        adb,
                        "10.0.2.64:5555",
                        3,
                        browser_package="org.chromium.chrome",
                        attempts=2,
                    )
        self.assertEqual(got, "127.0.0.1:8221")
        self.assertTrue(bp.guest_proxy_healthy(got, phone_idx=3))

    def test_firefox_scramble_pins_tor_not_host(self) -> None:
        adb = MagicMock()
        adb.shell.return_value = MagicMock(stdout="127.0.0.1:8119")
        adb.set_http_proxy = MagicMock()
        with patch.object(bp, "browse_proxy_mode", return_value="scramble"):
            with patch.object(bp, "expected_guest_proxy", return_value="127.0.0.1:8119"):
                with patch.object(bp, "_host_port_listens", return_value=True):
                    with patch.dict("os.environ", {"CPHARM_MANTIS_INJECT_PROXY": "1"}):
                        got = bp.restore_inject_after_identity(
                            adb,
                            "10.0.2.70:5555",
                            1,
                            browser_package="org.mozilla.firefox",
                            attempts=1,
                        )
        self.assertEqual(got, "127.0.0.1:8119")
        joined = " ".join(str(c) for c in adb.shell.call_args_list)
        self.assertNotIn("http_proxy :0", joined)


if __name__ == "__main__":
    unittest.main()
