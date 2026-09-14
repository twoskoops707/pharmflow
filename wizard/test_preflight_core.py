"""Tests for wizard/preflight_core.py"""

from __future__ import annotations

import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import preflight_core as pf  # noqa: E402


class PreflightCoreTests(unittest.TestCase):
    def test_build_checklist_has_core_steps(self) -> None:
        items = pf.build_checklist(Path("/nonexistent/pharmflow"))
        ids = [x["id"] for x in items]
        self.assertIn("folder", ids)
        self.assertIn("mumu", ids)
        self.assertIn("mumu_profile", ids)
        self.assertIn("adb", ids)
        self.assertIn("phones", ids)
        self.assertIn("browser", ids)
        self.assertGreaterEqual(len(ids), 8)

    def test_folder_passes_in_dev_mode(self) -> None:
        items = pf.build_checklist(Path("/nonexistent/pharmflow"))
        folder = next(x for x in items if x["id"] == "folder")
        self.assertEqual(folder["status"], "pass")

    def test_run_check_action_unknown(self) -> None:
        out = pf.run_check_action("not_a_real_action")
        self.assertFalse(out["ok"])

    def test_scan_follows_links_past_the_old_forty_link_trim(self) -> None:
        import site_mapper

        links = "".join(
            f'<a href="https://example.com/p{i}">p{i}</a>' for i in range(41)
        )
        pages = {
            "https://example.com": f"<html><title>Home</title>{links}</html>",
            "https://example.com/p40": "<html><title>Forty</title></html>",
        }

        def _fetch(url: str, timeout: int = 12) -> str:
            return pages.get(url.rstrip("/"), "")

        with unittest.mock.patch.object(site_mapper, "fetch_html", side_effect=_fetch):
            out = site_mapper.scan_site("https://example.com")
        urls = {p["url"].rstrip("/") for p in out["pages"]}
        self.assertTrue(out["ok"])
        self.assertIn("https://example.com/p40", urls)
        self.assertFalse(out["truncated"])
        self.assertEqual(out["remaining_urls"], 0)

    def test_explicit_page_limit_is_reported_as_truncated(self) -> None:
        import site_mapper

        html = '<html><a href="https://example.com/next">next</a></html>'
        with unittest.mock.patch.object(site_mapper, "fetch_html", return_value=html):
            out = site_mapper.scan_site("https://example.com", max_pages=1)
        self.assertTrue(out["ok"])
        self.assertEqual(out["pages_scanned"], 1)
        self.assertTrue(out["truncated"])
        self.assertGreaterEqual(out["remaining_urls"], 1)

    def test_starter_sequence_opens_every_mapped_page(self) -> None:
        import site_mapper

        draft = site_mapper.build_starter_sequence(
            "https://example.com",
            pages=[
                {"url": "https://example.com"},
                {"url": "https://example.com/pricing"},
            ],
        )
        opened = [s.get("url") for s in draft["steps"] if s.get("type") == "open_url"]
        self.assertEqual(
            [u.rstrip("/") for u in opened],
            ["https://example.com", "https://example.com/pricing"],
        )

    def test_scan_site_with_no_pages_is_a_failure(self) -> None:
        import site_mapper

        with unittest.mock.patch.object(
            site_mapper,
            "fetch_html",
            side_effect=OSError("timed out"),
        ):
            out = site_mapper.scan_site("https://example.com")
        self.assertFalse(out["ok"])
        self.assertEqual(out["pages_scanned"], 0)
        self.assertIn("timed out", out["error"])

    def test_phone_checks_do_not_kill_the_adb_server(self) -> None:
        import inspect

        body = inspect.getsource(pf._restart_adb_server).split('"""', 2)[-1]
        self.assertNotIn("kill-server", body)
        self.assertNotIn("start-server", body)
        with unittest.mock.patch.object(pf.subprocess, "run") as run:
            pf._restart_adb_server()
        run.assert_not_called()

    def test_fix_tablet_fails_when_no_vm_profiles_exist(self) -> None:
        fake = unittest.mock.MagicMock()
        fake.scan_mumu_vm_profiles.return_value = []
        with unittest.mock.patch.dict(sys.modules, {"mumu_farm_ops": fake}):
            out = pf.run_check_action("fix_tablet")
        self.assertFalse(out["ok"])
        self.assertEqual(out["fixed_count"], 0)
        self.assertIn("No MuMu VM profiles", out["error"])
        fake.fix_mumu_tablet_profiles.assert_not_called()

    def test_fix_tablet_already_phone_is_not_a_missing_folder(self) -> None:
        fake = unittest.mock.MagicMock()
        fake.scan_mumu_vm_profiles.return_value = [{"vm_dir": "vm0.gmadoa"}]
        fake.fix_mumu_tablet_profiles.return_value = 0
        with unittest.mock.patch.dict(sys.modules, {"mumu_farm_ops": fake}):
            out = pf.run_check_action("fix_tablet")
        self.assertTrue(out["ok"])
        self.assertIn("already Phone", out["message"])
        self.assertNotIn("not found", out["message"])

    def test_download_mumu_does_not_claim_opened_when_browser_refuses(self) -> None:
        with unittest.mock.patch.object(pf.webbrowser, "open", return_value=False):
            out = pf.run_check_action("download_mumu")
        self.assertFalse(out["ok"])
        self.assertIn("Could not open", out["message"])

    def test_refresh_is_not_ok_when_no_phone_answers(self) -> None:
        with (
            unittest.mock.patch.object(pf, "adb_usable", return_value=True),
            unittest.mock.patch.object(pf, "discover_adb_phones", return_value=[]),
        ):
            out = pf.run_check_action("refresh")
        self.assertFalse(out["ok"])
        self.assertEqual(out["phone_count"], 0)
        self.assertIn("No phones are answering", out["message"])

    def test_install_adb_is_not_ready_unless_adb_answers(self) -> None:
        with (
            unittest.mock.patch.object(pf, "download_platform_tools", return_value=True),
            unittest.mock.patch.object(pf, "adb_usable", return_value=False),
        ):
            out = pf.run_check_action("install_adb")
        self.assertFalse(out["ok"])
        self.assertNotIn("ready", out["message"])

    def test_discovery_connects_every_published_guest_not_a_ten_port_range(self) -> None:
        guests = [f"10.0.2.{i}:5555" for i in range(2, 20)]
        seen: list[str] = []

        def _connect(serials, deadline=None):
            seen.extend(serials)
            return serials

        with (
            unittest.mock.patch.object(pf, "_adb_exe", return_value="adb.exe"),
            unittest.mock.patch.object(pf.Path, "is_file", return_value=True),
            unittest.mock.patch.object(pf, "_published_guest_serials", return_value=guests),
            unittest.mock.patch.object(pf, "_redroid_adb_targets", return_value=["127.0.0.1:15555"]),
            unittest.mock.patch.object(pf, "_connect_serials", side_effect=_connect),
            unittest.mock.patch.object(pf, "list_adb_phones", return_value=guests),
        ):
            out = pf.auto_connect_all_phones()
        self.assertEqual(seen, guests + ["127.0.0.1:15555"])
        self.assertEqual(len(out), 18)
        self.assertNotIn("_AUTO_CONNECT_RANGES", pf.__dict__)

    def test_phone_check_does_not_pass_a_sixteen_phone_connect_cap(self) -> None:
        import inspect

        src = inspect.getsource(pf.try_connect_mumu_via_adb)
        self.assertNotIn("count=16", src)
        self.assertNotIn("count=12", src)
        wizard = Path(__file__).resolve().parent / "setup_wizard.py"
        connect = wizard.read_text(encoding="utf-8").split("def _connect_mumu_phones_impl")[1].split("\ndef ")[0]
        self.assertNotIn("len(connected) >= count", connect)
        self.assertNotIn("min(48", connect)
        ops = (Path(__file__).resolve().parent / "mumu_farm_ops.py").read_text(encoding="utf-8")
        discover = ops.split("def discover_serials")[1].split("\ndef ")[0]
        self.assertNotIn("max(count, 8)", discover)
        self.assertNotIn("[:count]", discover)


if __name__ == "__main__":
    unittest.main()
