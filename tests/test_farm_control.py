"""Tests for Site Profile → farm runtime wiring."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation.site_profile import interview_defaults
from wizard.farm_control import (
    _HELPER_SPECS,
    _dabflow_sequence_root,
    _dir_has_v3_sequences,
    _farm_args,
    _resolve_helper_python,
    _set_test_phone_result,
    apply_profile_farm_env,
    ensure_operator_stack,
    external_python_farm_running,
    start_farm,
    test_phone_status,
)


class FarmControlTests(unittest.TestCase):
    def test_test_phone_failure_is_visible_to_the_poll(self) -> None:
        import wizard.farm_control as fc

        prev = dict(fc._test_phone_result)
        try:
            _set_test_phone_result(
                {"ok": False, "starting": False, "error": "MuMu spin-up failed: no serial"}
            )
            status = test_phone_status()
            self.assertFalse(status.get("ok"))
            self.assertFalse(status.get("starting"))
            self.assertIn("no serial", status.get("error") or "")
        finally:
            fc._test_phone_result = prev

    def test_profile_selects_phone_count_catalog_and_two_hour_digest(self) -> None:
        profile = interview_defaults(
            kind="website",
            name="Example",
            url="https://example.com",
        )
        profile.farm.phone_count = 4
        profile.farm.startup_spread_minutes = 30
        profile.farm.ntfy_interval_s = 7200
        clear_keys = [
            "PHARMFLOW_FARM_PHONE_COUNT",
            "PHARMFLOW_NTFY_INTERVAL_S",
            "PHARMFLOW_FARM_START_STAGGER_BAND",
            "PHARMFLOW_FARM_START_STAGGER_WINDOW",
            "PHARMFLOW_FARM_START_STAGGER_MIN_GAP",
            "PHARMFLOW_FARM_START_STAGGER_JITTER",
            "PHARMFLOW_FARM_SEQUENCE_ROOT",
        ]
        with (
            patch("wizard.farm_control.sequences_dir", return_value=Path("C:/seqs")),
            patch("wizard.farm_control._apply_sticky_overrides", lambda: None),
            patch.dict(os.environ, {}, clear=False),
        ):
            for k in clear_keys:
                os.environ.pop(k, None)
            os.environ["PHARMFLOW_FARM_PHONE_COUNT"] = "4"
            os.environ["PHARMFLOW_FARM_EXPECT_PHONES"] = "4"
            apply_profile_farm_env(profile)
            self.assertNotIn("PHARMFLOW_FARM_PHONE_COUNT", os.environ)
            self.assertNotIn("PHARMFLOW_FARM_EXPECT_PHONES", os.environ)
            self.assertNotIn("PHARMFLOW_FARM_DAILY_VISITS", os.environ)
            self.assertEqual(os.environ["PHARMFLOW_NTFY_INTERVAL_S"], "7200")
            self.assertEqual(os.environ["PHARMFLOW_FARM_START_STAGGER_BAND"], "120")
            self.assertEqual(os.environ["PHARMFLOW_FARM_START_STAGGER_WINDOW"], "120")
            self.assertEqual(os.environ["PHARMFLOW_FARM_START_STAGGER_MIN_GAP"], "15")
            self.assertEqual(
                Path(os.environ["PHARMFLOW_FARM_SEQUENCE_ROOT"]),
                Path("C:/seqs") / profile.slug,
            )
            self.assertEqual(os.environ["PHARMFLOW_REQUIRE_UNIQUE_EXIT_IP"], "1")

        args = _farm_args(Path("run.py"), 6.0, profile)
        self.assertEqual(args, [str(Path("run.py")), "--hours", "6.0"])

    def test_farm_args_never_hardcode_phone_list(self) -> None:
        profile = interview_defaults(kind="website", name="Nine", url="https://example.com")
        profile.farm.phone_count = 9
        args = _farm_args(Path("run.py"), 0.0, profile)
        self.assertEqual(args, [str(Path("run.py")), "--hours", "0.0"])
        self.assertNotIn("--phones", args)

    def test_dabflow_sequence_root_prefers_cpharm_when_pharmflow_pool_missing(self) -> None:
        """Branding left live halfway pools under C:\\CPharm — Start farm must find them."""
        cpharm = Path(r"C:\CPharm\automation\recordings\sequences")
        if not cpharm.is_dir():
            self.skipTest("C:\\CPharm recordings pool not on this box")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PHARMFLOW_FARM_SEQUENCE_ROOT", None)

            def _has(cand: Path) -> bool:
                text = str(cand).replace("/", "\\").lower()
                if "pharmflow" in text and "cpharm" not in text:
                    return False
                return _dir_has_v3_sequences(cand)

            with patch("wizard.farm_control._dir_has_v3_sequences", side_effect=_has):
                root = _dabflow_sequence_root()
        self.assertIsNotNone(root)
        assert root is not None
        self.assertTrue("cpharm" in str(root).lower())
        self.assertTrue(any(root.rglob("*halfway*.json")))

    def test_money_day_mitm_and_path3_defaults(self) -> None:
        keys = [
            "PHARMFLOW_MANTIS_BILLING_DIRECT",
            "PHARMFLOW_MANTIS_INJECT_PROXY",
            "PHARMFLOW_MANTIS_INJECT_MITM",
            "PHARMFLOW_FARM_PATH3",
            "PHARMFLOW_PATH3",
            "PHARMFLOW_FARM_UNIQUE_SEQ",
            "PHARMFLOW_FARM_CHROMIUM_ONLY",
            "PHARMFLOW_SKIP_SEQUENCE_ISOLATION",
            "PHARMFLOW_AUTOPILOT_PAUSE",
            "PHARMFLOW_EMULATOR_AD_FALLBACK",
            "PHARMFLOW_EMULATOR_AD_FORCE_DIRECT",
        ]
        cleared = {k: "" for k in keys}
        with (
            patch("wizard.farm_control._apply_sticky_overrides", lambda: None),
            patch.dict(os.environ, cleared, clear=False),
        ):
            for k in keys:
                os.environ.pop(k, None)
            apply_profile_farm_env(None)
            self.assertEqual(os.environ["PHARMFLOW_MANTIS_BILLING_DIRECT"], "0")
            self.assertEqual(os.environ["PHARMFLOW_MANTIS_INJECT_PROXY"], "1")
            self.assertEqual(os.environ["PHARMFLOW_MANTIS_INJECT_MITM"], "1")
            self.assertEqual(os.environ["PHARMFLOW_FARM_PATH3"], "1")
            self.assertEqual(os.environ["PHARMFLOW_PATH3"], "1")
            self.assertEqual(os.environ["PHARMFLOW_FARM_UNIQUE_SEQ"], "1")
            self.assertEqual(os.environ["PHARMFLOW_FARM_CHROMIUM_ONLY"], "0")
            from automation.farm_visit_caps import MULTI_BROWSER, PATH3_BROWSERS

            # Browsers are pinned by the SSOT in code (farmbrowser = money browser).
            self.assertEqual(os.environ["PHARMFLOW_FARM_BROWSERS"], MULTI_BROWSER)
            # Path3 sticks to CDP-capable browsers (inject). Path1/2 stay multi-browser.
            self.assertEqual(os.environ["PHARMFLOW_FARM_PATH3_BROWSERS"], PATH3_BROWSERS)
            self.assertEqual(os.environ["PHARMFLOW_SKIP_SEQUENCE_ISOLATION"], "0")
            self.assertEqual(os.environ["PHARMFLOW_AUTOPILOT_PAUSE"], "1")
            self.assertEqual(os.environ["PHARMFLOW_EMULATOR_AD_FALLBACK"], "0")
            self.assertEqual(os.environ["PHARMFLOW_EMULATOR_AD_FORCE_DIRECT"], "0")

    def test_ssot_defaults_win_over_legacy_override_file(self) -> None:
        # Unison moved ALL farm rails into code (pharmflow_farm_config.py). The legacy
        # farm_runtime_overrides.json is purged, never read — SSOT defaults apply.
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "farm_runtime_overrides.json"
            legacy.write_text(
                json.dumps(
                    {
                        "PHARMFLOW_FARM_PATH3_DAILY_CAP": "36",
                        "PHARMFLOW_FARM_UNIQUE_SEQ": "0",
                        "PHARMFLOW_SITE_SLUG": "legacy",
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch("automation.pharmflow_farm_config.LOG_DIR", Path(tmp)),
                patch.dict(os.environ, {}, clear=False),
            ):
                os.environ.pop("PHARMFLOW_FARM_PATH3_DAILY_CAP", None)
                apply_profile_farm_env(None)
                self.assertFalse(legacy.exists())  # purged by _apply_sticky_overrides
                self.assertEqual(os.environ["PHARMFLOW_FARM_PATH3_DAILY_CAP"], "3000")
                self.assertEqual(os.environ["PHARMFLOW_FARM_UNIQUE_SEQ"], "1")
                self.assertEqual(os.environ["PHARMFLOW_SITE_SLUG"], "dabflow")

    def test_browsers_pinned_by_ssot_not_legacy_file(self) -> None:
        # Legacy overrides cannot force a chromium-only farm: the browser pool is
        # pinned in pharmflow_farm_config.py (farmbrowser = money browser) and the
        # legacy override file is purged on start.
        from automation.farm_visit_caps import MULTI_BROWSER, PATH3_BROWSERS

        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "farm_runtime_overrides.json"
            legacy.write_text(
                json.dumps(
                    {
                        "PHARMFLOW_FARM_CHROMIUM_ONLY": "1",
                        "PHARMFLOW_FARM_BROWSERS": "chromium",
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch("automation.pharmflow_farm_config.LOG_DIR", Path(tmp)),
                patch.dict(os.environ, {}, clear=False),
            ):
                apply_profile_farm_env(None)
                self.assertEqual(os.environ["PHARMFLOW_FARM_CHROMIUM_ONLY"], "0")
                self.assertEqual(os.environ["PHARMFLOW_FARM_BROWSERS"], MULTI_BROWSER)
                self.assertEqual(
                    os.environ["PHARMFLOW_FARM_PATH3_BROWSERS"], PATH3_BROWSERS
                )
                self.assertFalse(legacy.exists())

    def test_start_farm_takes_over_external_python(self) -> None:
        # Unison contract: start_farm stops any external python farm, arms the
        # unison supervisor stack (farm/stealth/watchdog), and returns True. It
        # no longer spawns a farm script directly.
        # farm_running is patched with side_effect: pre-arm check -> False
        # (not yet running), post-arm verification -> True (stack alive).
        msgs: list[str] = []
        with (
            patch("wizard.farm_control.farm_process_alive", side_effect=[False, True]) as run_fn,
            patch("wizard.farm_control.external_python_farm_running", return_value=True),
            patch("wizard.farm_control.stop_external_python_farm", return_value=[111]) as stop_fn,
            patch("automation.farm_exe_self_heal.run_self_heal", return_value={"fixes": []}),
            patch("wizard.farm_control.ensure_operator_stack", return_value=["unison armed"]) as ensure_fn,
            patch("wizard.farm_control.mark_exe_owned"),
            patch("wizard.farm_control._resolve_helper_python", return_value=None),
            patch("wizard.farm_control._start_digest", return_value=None),
            patch("wizard.farm_control.open_operator_dashboard", return_value=None),
        ):
            ok = start_farm(log=lambda m, _lvl="ok": msgs.append(m), takeover=True)
            self.assertTrue(ok)  # Unison stack armed after takeover
            run_fn.assert_called()
            stop_fn.assert_called()
            ensure_fn.assert_called()
            self.assertTrue(any("unison" in m.lower() for m in msgs))

    def test_start_farm_refuses_when_already_running(self) -> None:
        # Unison contract: farm_running() is authoritative — a running stack
        # means refuse, no takeover logic runs at all.
        msgs: list[str] = []
        with (
            patch("wizard.farm_control.farm_process_alive", return_value=True),
            patch("wizard.farm_control.external_python_farm_running", return_value=False) as ext_fn,
        ):
            ok = start_farm(log=lambda m, _lvl="ok": msgs.append(m), takeover=True)
        self.assertFalse(ok)
        ext_fn.assert_not_called()
        self.assertTrue(any("already running" in m.lower() for m in msgs))

    def test_start_farm_refuses_without_takeover(self) -> None:
        with (
            patch("wizard.farm_control.farm_process_alive", return_value=False),
            patch("wizard.farm_control.external_python_farm_running", return_value=True),
        ):
            msgs: list[str] = []
            ok = start_farm(
                log=lambda m, _lvl="ok": msgs.append(m),
                takeover=False,
            )
            self.assertFalse(ok)
            self.assertTrue(any("External python farm" in m for m in msgs))

    def test_stop_farm_no_stack_to_kill(self) -> None:
        """stop_farm with nothing alive: returns False, still clears the marker.

        Fully mocked — the real _kill_farm_stack scans and kills machine-wide
        processes, which a unit test must never do.
        """
        from wizard.farm_control import stop_farm

        with (
            patch("wizard.farm_control.clear_exe_owned") as clear_fn,
            patch("wizard.farm_control._kill_farm_stack", return_value=[]) as kill_fn,
        ):
            msgs: list[str] = []
            ok = stop_farm(log=lambda m, _lvl="ok": msgs.append(m))
        self.assertFalse(ok)  # nothing was running -> nothing stopped
        kill_fn.assert_called_once()
        clear_fn.assert_called_once()

    def test_stop_farm_tears_down_owned_helpers(self) -> None:
        """Owned Popen helpers + stack needles are killed; marker cleared.

        The psutil machine scan is mocked — this test exercises stop_farm's
        accounting, not live process termination.
        """
        from wizard.farm_control import stop_farm

        with (
            patch("wizard.farm_control.clear_exe_owned") as clear_fn,
            patch("wizard.farm_control._kill_farm_stack", return_value=[4321]) as kill_fn,
        ):
            msgs: list[str] = []
            ok = stop_farm(log=lambda m, _lvl="ok": msgs.append(m))
        self.assertTrue(ok)
        kill_fn.assert_called_once()
        clear_fn.assert_called_once()
        self.assertTrue(any("4321" in m for m in msgs))

    def test_external_python_farm_helper_callable(self) -> None:
        # Smoke: helper imports psutil and returns bool without raising.
        self.assertIsInstance(external_python_farm_running(), bool)

    def test_external_python_farm_ignores_fresh_log_heartbeat(self) -> None:
        """A touched farm_354.log is not a live run_farm_354 process."""
        with (
            patch("wizard.farm_control._farm_heartbeat_alive", return_value=True),
            patch("psutil.process_iter", return_value=[]),
        ):
            self.assertFalse(external_python_farm_running())

    def test_operator_stack_three_unison_lanes(self) -> None:
        # Unison stack: one supervisor lane arms farm + stealth + watchdog; the
        # old per-helper scripts (remediate loop, keep-alive, inject proxies,
        # hunter, watch_bottom_ads) were consolidated into the supervisor.
        names = {spec[0] for spec in _HELPER_SPECS}
        self.assertEqual(
            names,
            {
                "suppress_console_flash.py",
                "farm_operator_dash.py",
                "pharmflow_unison_supervisor.py",
            },
        )

    def test_resolve_helper_python_returns_usable_path(self) -> None:
        path = _resolve_helper_python()
        self.assertIsNotNone(path)
        assert path is not None
        self.assertTrue(Path(path).is_file())
        self.assertNotIn("PharmFlow.exe", path)
        self.assertNotIn("PharmFlow.exe", path)

    def test_ensure_operator_stack_skips_alive_helpers(self) -> None:
        msgs: list[str] = []
        with patch("wizard.farm_control._helper_already_alive", return_value=True):
            notes = ensure_operator_stack(log=lambda m, lvl="ok": msgs.append(f"{lvl}:{m}"))
        self.assertTrue(any("already up" in n for n in notes))
        # Helper-python resolution is lazy: the line only logs when a helper
        # actually needs spawning, so "already up" notes are the only output.
        self.assertEqual(
            len(notes),
            sum(1 for n in notes if "already up" in n),
        )
        self.assertGreaterEqual(len(notes), len(_HELPER_SPECS))

    def test_start_farm_arms_fail_when_stack_not_alive(self) -> None:
        # Post-arm aliveness check guards the money path: if the unison stack
        # did not come up, start_farm must clear the exe-owned marker and fail.
        msgs: list[str] = []
        with (
            patch("wizard.farm_control.farm_process_alive", return_value=False),
            patch("wizard.farm_control.external_python_farm_running", return_value=False),
            patch("automation.farm_exe_self_heal.run_self_heal", return_value={"fixes": []}),
            patch("wizard.farm_control.ensure_operator_stack", return_value=[]),
            patch("wizard.farm_control._wait_farm_armed", return_value=False),
            patch("wizard.farm_control.mark_exe_owned"),
            patch("wizard.farm_control.clear_exe_owned") as clear_fn,
            patch("wizard.farm_control._resolve_helper_python", return_value=None),
        ):
            ok = start_farm(log=lambda m, _lvl="ok": msgs.append(m), takeover=True)
        self.assertFalse(ok)
        clear_fn.assert_called_once()
        self.assertTrue(any("failed to arm" in m.lower() for m in msgs))

    def test_fresh_log_does_not_block_start(self) -> None:
        """A recent farm_354.log is not a live farm. Start must try, not report already running."""
        msgs: list[str] = []
        with (
            patch("wizard.farm_control.farm_running", return_value=True),
            patch("wizard.farm_control.farm_process_alive", return_value=False),
            patch("wizard.farm_control.external_python_farm_running", return_value=False),
            patch("automation.farm_exe_self_heal.run_self_heal", return_value={"fixes": []}),
            patch("wizard.farm_control.ensure_operator_stack", return_value=[]) as ensure_fn,
            patch("wizard.farm_control._wait_farm_armed", return_value=False),
            patch("wizard.farm_control.mark_exe_owned"),
            patch("wizard.farm_control.clear_exe_owned"),
            patch("wizard.farm_control._resolve_helper_python", return_value=None),
        ):
            ok = start_farm(log=lambda m, _lvl="ok": msgs.append(m), takeover=True)
        self.assertFalse(ok)
        ensure_fn.assert_called_once()
        self.assertFalse(any("already running" in m.lower() for m in msgs))

    def test_arm_wait_ignores_a_fresh_log(self) -> None:
        from wizard.farm_control import _wait_farm_armed

        with (
            patch("wizard.farm_control.farm_running", return_value=True),
            patch("wizard.farm_control.farm_process_alive", return_value=False),
            patch("wizard.farm_control._helper_already_alive", return_value=False),
            patch("wizard.farm_control.time.sleep"),
            patch("wizard.farm_control.time.time", side_effect=[0, 0, 100]),
        ):
            self.assertFalse(_wait_farm_armed(timeout_s=20))

    def test_open_operator_dashboard_waits_then_opens(self) -> None:
        from wizard.farm_control import open_operator_dashboard

        calls: list[str] = []

        class _Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_open(url: str) -> bool:
            calls.append(url)
            return True

        with (
            patch("wizard.farm_control.ensure_operator_stack", return_value=[]),
            patch("urllib.request.urlopen", return_value=_Resp()),
            patch("webbrowser.open", side_effect=fake_open),
        ):
            ok = open_operator_dashboard(wait_s=1.0, open_browser=True)
        self.assertTrue(ok)
        self.assertEqual(calls, ["http://127.0.0.1:8091/"])

    def test_open_operator_dashboard_does_not_claim_a_refused_browser(self) -> None:
        from wizard import farm_control as fc

        class _Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        logs: list[str] = []
        fc._dash_browser_opened = False
        with (
            patch("wizard.farm_control.ensure_operator_stack", return_value=[]),
            patch("urllib.request.urlopen", return_value=_Resp()),
            patch("webbrowser.open", return_value=False),
        ):
            ok = fc.open_operator_dashboard(
                wait_s=1.0,
                open_browser=True,
                log=lambda msg, level="ok": logs.append(f"{level}:{msg}"),
            )
        self.assertTrue(ok)
        self.assertFalse(fc._dash_browser_opened)
        self.assertTrue(any("browser did not open" in line for line in logs))
        self.assertFalse(any(line.startswith("ok:Opened") for line in logs))

    def test_open_operator_dashboard_default_no_browser(self) -> None:
        from wizard import farm_control as fc

        calls: list[str] = []

        class _Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        fc._dash_browser_opened = False
        with (
            patch("wizard.farm_control.ensure_operator_stack", return_value=[]),
            patch("urllib.request.urlopen", return_value=_Resp()),
            patch("webbrowser.open", side_effect=lambda url: calls.append(url) or True),
        ):
            ok = fc.open_operator_dashboard(wait_s=1.0, open_browser=False)
        self.assertTrue(ok)
        self.assertEqual(calls, [])

    def test_phone_plan_is_not_capped_at_ten(self) -> None:
        from automation.mantis_farm_math import plan_for_phones

        plan = plan_for_phones(16)
        self.assertEqual(plan.phone_count, 16)
        self.assertEqual(len(plan.visits), 16)
        self.assertEqual(len(plan.ads), 16)
        src = Path(__file__).resolve().parents[1] / "wizard" / "farm_control.py"
        text = src.read_text(encoding="utf-8")
        self.assertNotIn("_PHONE_NAMES", text)
        self.assertNotIn("min(len(_PHONE_NAMES)", text)
        interview = Path(__file__).resolve().parents[1] / "wizard" / "site_interview.py"
        self.assertNotIn("min(10, phones)", interview.read_text(encoding="utf-8"))

    def test_spin_up_connects_the_published_port_not_5555_plus_index(self) -> None:
        import time
        from unittest.mock import MagicMock

        import wizard.farm_control as fc

        connected: list[str] = []
        calls = {"n": 0}

        def _rows():
            calls["n"] += 1
            if calls["n"] == 1:
                return [{"idx": 3, "name": "redroid-3", "up": False, "ports": []}]
            return [{"idx": 3, "name": "redroid-3", "up": True, "ports": ["127.0.0.1:16001"]}]

        adb = MagicMock()
        adb.devices_detailed.return_value = []

        def _connect(serial: str) -> None:
            connected.append(serial)

        adb.connect.side_effect = _connect
        adb.wait_for_device.side_effect = lambda serial, timeout=45.0: serial == "127.0.0.1:16001"

        fc._test_phone_active = False
        with (
            patch.object(fc, "_redroid_containers", side_effect=_rows),
            patch.object(fc, "_docker_cli", return_value=(0, "")),
            patch("automation.adb_wrapper.AdbWrapper", return_value=adb),
        ):
            out = fc.spin_up_test_phone()
            self.assertTrue(out.get("started"))
            deadline = time.time() + 5
            status: dict = {}
            while time.time() < deadline:
                status = fc.test_phone_status()
                if status.get("starting") is False:
                    break
                time.sleep(0.05)
        self.assertTrue(status.get("ok"), status)
        self.assertIn("16001", str(status.get("message")))
        self.assertEqual(connected, ["127.0.0.1:16001"])
        self.assertNotIn("127.0.0.1:5558", connected)
        flag_deadline = time.time() + 2
        while fc._test_phone_active and time.time() < flag_deadline:
            time.sleep(0.02)
        self.assertFalse(fc._test_phone_active)
        src = Path(__file__).resolve().parents[1] / "wizard" / "farm_control.py"
        body = src.read_text(encoding="utf-8").split("def spin_up_test_phone")[1].split("\ndef ")[0]
        self.assertNotIn("5555 + idx", body)

    def test_spin_up_does_not_treat_an_online_phone_as_the_spare(self) -> None:
        import time
        from unittest.mock import MagicMock

        import wizard.farm_control as fc

        started: list[list[str]] = []
        calls = {"n": 0}

        def _rows():
            calls["n"] += 1
            online = {"idx": 0, "name": "redroid-0", "up": True, "ports": ["127.0.0.1:16000"]}
            if calls["n"] == 1:
                spare = {"idx": 1, "name": "redroid-1", "up": False, "ports": []}
            else:
                spare = {"idx": 1, "name": "redroid-1", "up": True, "ports": ["127.0.0.1:16001"]}
            return [online, spare]

        adb = MagicMock()
        adb.devices_detailed.return_value = [
            type("Dev", (), {"serial": "127.0.0.1:16000", "online": True})()
        ]
        adb.wait_for_device.side_effect = lambda serial, timeout=45.0: serial == "127.0.0.1:16001"

        def _docker(args, timeout=120.0):
            started.append(list(args))
            return (0, "")

        fc._test_phone_active = False
        with (
            patch.object(fc, "_redroid_containers", side_effect=_rows),
            patch.object(fc, "_docker_cli", side_effect=_docker),
            patch("automation.adb_wrapper.AdbWrapper", return_value=adb),
        ):
            out = fc.spin_up_test_phone()
            self.assertTrue(out.get("started"))
            deadline = time.time() + 5
            status: dict = {}
            while time.time() < deadline:
                status = fc.test_phone_status()
                if status.get("starting") is False:
                    break
                time.sleep(0.05)
        self.assertTrue(status.get("ok"), status)
        self.assertIn("16001", str(status.get("message")))
        self.assertNotIn("16000", str(status.get("message")))
        self.assertEqual(started, [["start", "redroid-1"]])
        flag_deadline = time.time() + 2
        while fc._test_phone_active and time.time() < flag_deadline:
            time.sleep(0.02)
        self.assertFalse(fc._test_phone_active)

    def test_spin_up_does_not_claim_a_boot_when_every_phone_is_online(self) -> None:
        import time
        from unittest.mock import MagicMock

        import wizard.farm_control as fc

        adb = MagicMock()
        adb.devices_detailed.return_value = [
            type("Dev", (), {"serial": "127.0.0.1:16000", "online": True})()
        ]
        farm = MagicMock()
        farm.list_instances.return_value = []
        farm.enumerate_adb_devices.return_value = []
        fc._test_phone_active = False
        with (
            patch.object(
                fc,
                "_redroid_containers",
                return_value=[{"idx": 0, "name": "redroid-0", "up": True, "ports": ["127.0.0.1:16000"]}],
            ),
            patch.object(fc, "_docker_cli") as docker,
            patch("automation.adb_wrapper.AdbWrapper", return_value=adb),
            patch("wizard.mumu_farm_ops.MuMuFarmOps", return_value=farm),
        ):
            out = fc.spin_up_test_phone()
            self.assertTrue(out.get("started"))
            deadline = time.time() + 5
            status: dict = {}
            while time.time() < deadline:
                status = fc.test_phone_status()
                if status.get("starting") is False:
                    break
                time.sleep(0.05)
        self.assertTrue(status.get("ok"), status)
        self.assertIn("Nothing was spun up", str(status.get("message")))
        docker.assert_not_called()
        farm.start_phone.assert_not_called()
        flag_deadline = time.time() + 2
        while fc._test_phone_active and time.time() < flag_deadline:
            time.sleep(0.02)
        self.assertFalse(fc._test_phone_active)


if __name__ == "__main__":
    unittest.main()
