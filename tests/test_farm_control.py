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
    _farm_args,
    _resolve_helper_python,
    apply_profile_farm_env,
    ensure_operator_stack,
    external_python_farm_running,
    start_farm,
)


class FarmControlTests(unittest.TestCase):
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
            "CPHARM_FARM_PHONE_COUNT",
            "CPHARM_NTFY_INTERVAL_S",
            "CPHARM_FARM_START_STAGGER_BAND",
            "CPHARM_FARM_START_STAGGER_WINDOW",
            "CPHARM_FARM_START_STAGGER_MIN_GAP",
            "CPHARM_FARM_START_STAGGER_JITTER",
            "CPHARM_FARM_SEQUENCE_ROOT",
        ]
        with (
            patch("wizard.farm_control.sequences_dir", return_value=Path("C:/seqs")),
            patch("wizard.farm_control._apply_sticky_overrides", lambda: None),
            patch.dict(os.environ, {}, clear=False),
        ):
            for k in clear_keys:
                os.environ.pop(k, None)
            apply_profile_farm_env(profile)
            self.assertEqual(os.environ["CPHARM_FARM_PHONE_COUNT"], "4")
            self.assertEqual(os.environ["CPHARM_NTFY_INTERVAL_S"], "7200")
            self.assertEqual(os.environ["CPHARM_FARM_START_STAGGER_BAND"], "120")
            self.assertEqual(os.environ["CPHARM_FARM_START_STAGGER_WINDOW"], "120")
            self.assertEqual(os.environ["CPHARM_FARM_START_STAGGER_MIN_GAP"], "15")
            self.assertEqual(
                Path(os.environ["CPHARM_FARM_SEQUENCE_ROOT"]),
                Path("C:/seqs") / profile.slug,
            )
            self.assertEqual(os.environ["CPHARM_REQUIRE_UNIQUE_EXIT_IP"], "1")

        args = _farm_args(Path("run.py"), 6.0, profile)
        self.assertEqual(args, [str(Path("run.py")), "--hours", "6.0"])

    def test_farm_args_never_hardcode_phone_list(self) -> None:
        profile = interview_defaults(kind="website", name="Nine", url="https://example.com")
        profile.farm.phone_count = 9
        args = _farm_args(Path("run.py"), 0.0, profile)
        self.assertEqual(args, [str(Path("run.py")), "--hours", "0.0"])
        self.assertNotIn("--phones", args)

    def test_money_day_mitm_and_path3_defaults(self) -> None:
        keys = [
            "CPHARM_MANTIS_BILLING_DIRECT",
            "CPHARM_MANTIS_INJECT_PROXY",
            "CPHARM_MANTIS_INJECT_MITM",
            "CPHARM_FARM_PATH3",
            "CPHARM_PATH3",
            "CPHARM_FARM_UNIQUE_SEQ",
            "CPHARM_FARM_CHROMIUM_ONLY",
            "CPHARM_SKIP_SEQUENCE_ISOLATION",
            "CPHARM_AUTOPILOT_PAUSE",
            "CPHARM_EMULATOR_AD_FALLBACK",
            "CPHARM_EMULATOR_AD_FORCE_DIRECT",
        ]
        cleared = {k: "" for k in keys}
        with (
            patch("wizard.farm_control._apply_sticky_overrides", lambda: None),
            patch.dict(os.environ, cleared, clear=False),
        ):
            for k in keys:
                os.environ.pop(k, None)
            apply_profile_farm_env(None)
            self.assertEqual(os.environ["CPHARM_MANTIS_BILLING_DIRECT"], "1")
            self.assertEqual(os.environ["CPHARM_MANTIS_INJECT_PROXY"], "1")
            self.assertEqual(os.environ["CPHARM_MANTIS_INJECT_MITM"], "1")
            self.assertEqual(os.environ["CPHARM_FARM_PATH3"], "1")
            self.assertEqual(os.environ["CPHARM_PATH3"], "1")
            self.assertEqual(os.environ["CPHARM_FARM_UNIQUE_SEQ"], "1")
            self.assertEqual(os.environ["CPHARM_FARM_CHROMIUM_ONLY"], "0")
            from automation.farm_visit_caps import MULTI_BROWSER, PATH3_BROWSERS

            # Browsers are pinned by the SSOT in code (farmbrowser = money browser).
            self.assertEqual(os.environ["CPHARM_FARM_BROWSERS"], MULTI_BROWSER)
            # Path3 sticks to CDP-capable browsers (inject). Path1/2 stay multi-browser.
            self.assertEqual(os.environ["CPHARM_FARM_PATH3_BROWSERS"], PATH3_BROWSERS)
            self.assertEqual(os.environ["CPHARM_SKIP_SEQUENCE_ISOLATION"], "0")
            self.assertEqual(os.environ["CPHARM_AUTOPILOT_PAUSE"], "1")
            self.assertEqual(os.environ["CPHARM_EMULATOR_AD_FALLBACK"], "0")
            self.assertEqual(os.environ["CPHARM_EMULATOR_AD_FORCE_DIRECT"], "0")

    def test_ssot_defaults_win_over_legacy_override_file(self) -> None:
        # Unison moved ALL farm rails into code (cpharm_farm_config.py). The legacy
        # farm_runtime_overrides.json is purged, never read — SSOT defaults apply.
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "farm_runtime_overrides.json"
            legacy.write_text(
                json.dumps(
                    {
                        "CPHARM_FARM_PATH3_DAILY_CAP": "36",
                        "CPHARM_FARM_UNIQUE_SEQ": "0",
                        "CPHARM_SITE_SLUG": "legacy",
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch("automation.cpharm_farm_config.LOG_DIR", Path(tmp)),
                patch.dict(os.environ, {}, clear=False),
            ):
                os.environ.pop("CPHARM_FARM_PATH3_DAILY_CAP", None)
                apply_profile_farm_env(None)
                self.assertFalse(legacy.exists())  # purged by _apply_sticky_overrides
                self.assertEqual(os.environ["CPHARM_FARM_PATH3_DAILY_CAP"], "3000")
                self.assertEqual(os.environ["CPHARM_FARM_UNIQUE_SEQ"], "1")
                self.assertEqual(os.environ["CPHARM_SITE_SLUG"], "dabflow")

    def test_browsers_pinned_by_ssot_not_legacy_file(self) -> None:
        # Legacy overrides cannot force a chromium-only farm: the browser pool is
        # pinned in cpharm_farm_config.py (farmbrowser = money browser) and the
        # legacy override file is purged on start.
        from automation.farm_visit_caps import MULTI_BROWSER, PATH3_BROWSERS

        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "farm_runtime_overrides.json"
            legacy.write_text(
                json.dumps(
                    {
                        "CPHARM_FARM_CHROMIUM_ONLY": "1",
                        "CPHARM_FARM_BROWSERS": "chromium",
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch("automation.cpharm_farm_config.LOG_DIR", Path(tmp)),
                patch.dict(os.environ, {}, clear=False),
            ):
                apply_profile_farm_env(None)
                self.assertEqual(os.environ["CPHARM_FARM_CHROMIUM_ONLY"], "0")
                self.assertEqual(os.environ["CPHARM_FARM_BROWSERS"], MULTI_BROWSER)
                self.assertEqual(
                    os.environ["CPHARM_FARM_PATH3_BROWSERS"], PATH3_BROWSERS
                )
                self.assertFalse(legacy.exists())

    def test_start_farm_takes_over_external_python(self) -> None:
        # Unison contract: start_farm stops any external python farm, arms the
        # unison supervisor stack (farm/stealth/watchdog), and returns True. It
        # no longer spawns a farm script directly.
        msgs: list[str] = []
        with (
            patch("wizard.farm_control.farm_running", return_value=False),
            patch("wizard.farm_control.external_python_farm_running", return_value=True),
            patch("wizard.farm_control.stop_external_python_farm", return_value=[111]) as stop_fn,
            patch("wizard.farm_control.ensure_operator_stack", return_value=["unison armed"]),
            patch("wizard.farm_control.mark_exe_owned"),
            patch("wizard.farm_control._resolve_helper_python", return_value=None),
            patch("wizard.farm_control._start_digest", return_value=None),
            patch("wizard.farm_control.open_operator_dashboard", return_value=None),
        ):
            ok = start_farm(log=lambda m, _lvl="ok": msgs.append(m), takeover=True)
            self.assertTrue(ok)  # Unison stack armed after takeover
            stop_fn.assert_called()
            self.assertTrue(any("unison" in m.lower() for m in msgs))

    def test_start_farm_can_refuse_without_takeover(self) -> None:
        with (
            patch("wizard.farm_control.farm_running", return_value=False),
            patch("wizard.farm_control.external_python_farm_running", return_value=True),
        ):
            msgs: list[str] = []
            ok = start_farm(
                log=lambda m, _lvl="ok": msgs.append(m),
                takeover=False,
            )
            self.assertFalse(ok)
            self.assertTrue(any("External python farm" in m for m in msgs))

    def test_stop_farm_clears_python_farm(self) -> None:
        from wizard.farm_control import stop_farm

        with (
            patch("wizard.farm_control.clear_exe_owned") as clear_fn,
        ):
            msgs: list[str] = []
            ok = stop_farm(log=lambda m, _lvl="ok": msgs.append(m))
            self.assertFalse(ok)  # no in-process farm proc
            clear_fn.assert_called_once()

    def test_external_python_farm_helper_callable(self) -> None:
        # Smoke: helper imports psutil and returns bool without raising.
        self.assertIsInstance(external_python_farm_running(), bool)

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
                "cpharm_unison_supervisor.py",
            },
        )

    def test_resolve_helper_python_returns_usable_path(self) -> None:
        path = _resolve_helper_python()
        self.assertIsNotNone(path)
        assert path is not None
        self.assertTrue(Path(path).is_file())
        self.assertNotIn("CPharm.exe", path)

    def test_ensure_operator_stack_skips_alive_helpers(self) -> None:
        msgs: list[str] = []
        with patch("wizard.farm_control._helper_already_alive", return_value=True):
            notes = ensure_operator_stack(log=lambda m, lvl="ok": msgs.append(f"{lvl}:{m}"))
        self.assertTrue(any("already up" in n for n in notes))
        self.assertEqual(len(notes), len(_HELPER_SPECS) + 1)  # + helper_py log line

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


if __name__ == "__main__":
    unittest.main()
