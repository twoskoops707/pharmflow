"""Tests for automation/dashboard.py — asyncio HTTP API (post-Flask rewrite)."""

from __future__ import annotations

import asyncio
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import automation.dashboard as dashboard


def _run(coro):
    return asyncio.run(coro)


class DashboardApiTests(unittest.TestCase):
    """Drive the real handlers (handle_get / handle_post) with mocked ADB layer."""

    def test_index_serves_ui(self) -> None:
        resp = _run(dashboard.handle_get("/"))
        self.assertEqual(resp[:12], b"HTTP/1.1 200")
        self.assertIn(b"PharmFlow", resp)
        self.assertIn(b"/api/phones", resp)

    def test_api_phones(self) -> None:
        with patch.object(dashboard, "list_phones", return_value=[{"serial": "127.0.0.1:16384", "status": "device"}]):
            resp = _run(dashboard.handle_get("/api/phones"))
        self.assertEqual(resp[:12], b"HTTP/1.1 200")
        body = json.loads(resp.split(b"\r\n\r\n", 1)[1])
        # Envelope object: the Farm Remote APK's parsePhones reads ``phones``.
        self.assertTrue(body.get("ok"))
        self.assertIsInstance(body.get("phones"), list)
        self.assertEqual(body["phones"][0]["serial"], "127.0.0.1:16384")

    def test_api_config_names_app(self) -> None:
        resp = _run(dashboard.handle_get("/api/config"))
        body = json.loads(resp.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(body.get("appName"), "PharmFlow")
        self.assertIn("httpPort", body)

    def test_api_ip_reports_listen_url(self) -> None:
        with patch.object(dashboard, "get_local_ip", return_value="127.0.0.1"):
            resp = _run(dashboard.handle_get("/api/ip"))
        body = json.loads(resp.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(body["ip"], "127.0.0.1")
        self.assertIn("url", body)

    def test_api_stealth_payload(self) -> None:
        with patch.object(dashboard, "_get_stealth_payload", return_value=[]):
            resp = _run(dashboard.handle_get("/api/stealth"))
        body = json.loads(resp.split(b"\r\n\r\n", 1)[1])
        self.assertTrue(body["ok"])
        self.assertEqual(body["phones"], [])

    def test_unknown_api_404(self) -> None:
        resp = _run(dashboard.handle_get("/api/does_not_exist"))
        self.assertIn(b"404", resp.split(b"\r\n", 1)[0])

    def test_api_money_history(self) -> None:
        with patch("scorecard_api.build_money_history", return_value=[{"day": "2026-09-08", "usd": 0.13}]):
            resp = _run(dashboard.handle_get("/api/money/history"))
        body = json.loads(resp.split(b"\r\n\r\n", 1)[1])
        self.assertTrue(body["ok"])
        self.assertEqual(body["days"][0]["usd"], 0.13)

    def test_post_connect_requires_address(self) -> None:
        resp = _run(dashboard.handle_post("/api/devices/connect", json.dumps({}).encode()))
        self.assertIn(b"400", resp.split(b"\r\n", 1)[0])

    def test_post_connect_calls_adb_and_pushes(self) -> None:
        with (
            # Real adb prints "connected to <addr>" on success — the handler's
            # _adb_connect_landed requires that exact phrase (not bare "connected").
            patch.object(dashboard, "_adb_global", return_value=MagicMock(text="connected to 127.0.0.1:16384", returncode=0)) as adb,
            patch.object(dashboard, "push_phones", new=MagicMock()) as push_mock,
        ):
            # push_phones is awaited — wrap as coroutine.
            async def _push():
                return None

            push_mock.side_effect = _push
            resp = _run(
                dashboard.handle_post(
                    "/api/devices/connect",
                    json.dumps({"address": "127.0.0.1:16384"}).encode(),
                )
            )
        adb.assert_called_once()
        body = json.loads(resp.split(b"\r\n\r\n", 1)[1])
        self.assertTrue(body["ok"])

    def test_force_utf8_stdio_does_not_close_replaced_stream(self) -> None:
        """Regression: replacing stdout must never orphan-close the previous fd.

        The old code assigned ``io.TextIOWrapper(sys.stdout.buffer, ...)`` which
        let the discarded wrapper close the underlying stream on GC — this
        crashed pytest capture and any embedding host.
        """
        buf = io.BytesIO()
        replaced = io.TextIOWrapper(buf, encoding="cp1252")
        orig = sys.stdout
        sys.stdout = replaced
        try:
            dashboard._force_utf8_stdio()
            new = sys.stdout
            self.assertIsNot(new, replaced)
            self.assertIn("utf-8", (getattr(new, "encoding", "") or "").lower())
            self.assertFalse(buf.closed)
            new.write("probe")
            new.flush()
            self.assertEqual(buf.getvalue(), b"probe")
        finally:
            new = sys.stdout
            try:
                new.detach()  # keep buf open when the temp wrapper is GC'd
            except Exception:
                pass
            sys.stdout = orig


class RosterCountHonestyTests(unittest.TestCase):
    def test_projection_uses_live_phones_and_does_not_stop_at_24(self) -> None:
        from automation.scorecard_api import build_money_kpis, scaling_targets

        zero = scaling_targets(0)
        self.assertEqual(zero["phone_count"], 0)
        self.assertEqual(zero["ad_clicks_hard_cap"], 0)
        wide = scaling_targets(40)
        self.assertEqual(wide["phone_count"], 40)
        self.assertGreater(wide["ad_clicks_hard_cap"], scaling_targets(24)["ad_clicks_hard_cap"])
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_money_kpis(
                list_phones_fn=lambda: [
                    {"serial": "10.0.2.15:5555", "running": False},
                    {"serial": "10.0.2.16:5555", "running": True},
                ],
                recordings_dir=Path(tmp),
            )
            self.assertEqual(payload["phone_count"], 1)
            stale = Path(tmp) / "scorecard_state.json"
            stale.write_text(
                '{"date": "2000-01-01", "payout_usd": 88.0, "clicks": 9, "impressions": 100}',
                encoding="utf-8",
            )
            with patch("automation.scorecard_api._live_farm_facts", return_value={}):
                stale_payload = build_money_kpis(
                    list_phones_fn=lambda: [],
                    recordings_dir=Path(tmp),
                )
            self.assertEqual(stale_payload["revenue_today_usd"], 0.0)
            self.assertEqual(stale_payload["clicks"], 0)
            self.assertEqual(stale_payload["impressions"], 0)

    def test_watchdog_fact_from_another_day_is_not_revenue_today(self) -> None:
        from datetime import datetime, timezone

        from automation import scorecard_api

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "cursor_monitor_loop.log"
            now = datetime.now(timezone.utc).isoformat()
            log.write_text(
                "2000-01-01T00:00:00+00:00 FACT $=99.00 clk=9 impr=900\n"
                + now
                + " FACT $=4.50 clk=2 impr=80\n"
                + "FACT $=12.00 clk=3 impr=100\n",
                encoding="utf-8",
            )
            with patch.object(scorecard_api, "_fact_log_paths", return_value=[log]):
                facts = scorecard_api._live_farm_facts()
        self.assertEqual(facts.get("payout_usd"), 4.50)
        self.assertEqual(facts.get("clicks"), 2)
        html = Path(dashboard.__file__).resolve().parent.joinpath("dashboard.html").read_text(encoding="utf-8")
        self.assertIn("p && p.running", html)
        self.assertNotIn("max=\"3600\"", html)
        src = Path(__file__).resolve().parents[1].joinpath("automation", "scorecard_api.py").read_text(encoding="utf-8")
        self.assertNotIn("min(int(phone_count), 24)", src)
        self.assertNotIn("phones_default\", 4)", src)


if __name__ == "__main__":
    unittest.main()
