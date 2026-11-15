"""Real one-login free path for cloud phones + FreeLLMAPI agent (no vapor)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cloud_connect as cc  # noqa: E402


class CloudConnectFreePathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_free_tier_limits_are_documented_not_phone_caps(self) -> None:
        ft = cc.FREE_TIER_LIMITS
        self.assertEqual(ft["path"], "oracle_always_free_redroid_plus_freellmapi")
        self.assertIn("A1.Flex", ft["compute"])
        self.assertIn("31415", ft["agent"])
        self.assertIn("no product phone ceiling", ft["phones_guidance"].lower().replace("—", "-"))
        # Must not invent a paid device farm vendor.
        blob = json.dumps(ft).lower()
        for banned in ("browserstack", "saucelabs", "lambdatest", "genymotion cloud"):
            self.assertNotIn(banned, blob)

    def test_connect_login_writes_session_and_freellm_agent(self) -> None:
        plan = cc.connect_login(
            "100.64.9.1",
            4,
            "sk-free-test-key",
            root=self.root,
            start_phones=True,
        )
        self.assertTrue(plan["ok"])
        self.assertTrue(plan["start_phones"])
        self.assertEqual(plan["host"], "100.64.9.1")
        self.assertEqual(plan["count"], 4)
        self.assertTrue(plan["agent"]["configured"])
        self.assertTrue(plan["agent"]["free_path"])
        self.assertEqual(plan["agent"]["base"], "http://127.0.0.1:31415/v1")

        session = json.loads((self.root / "cloud_session.json").read_text(encoding="utf-8"))
        self.assertEqual(session["host"], "100.64.9.1")
        self.assertEqual(session["count"], 4)

        agent = json.loads((self.root / "cloud_agent.json").read_text(encoding="utf-8"))
        self.assertEqual(agent["base"], "http://127.0.0.1:31415/v1")
        self.assertEqual(agent["model"], "auto")
        self.assertEqual(agent["api_key"], "sk-free-test-key")

        status = cc.session_status(root=self.root)
        self.assertTrue(status["ready"])
        self.assertTrue(status["ready_phones"])
        self.assertTrue(status["ready_agent"])
        self.assertIn("free_tier", status)

    def test_connect_login_reuses_saved_host_without_reprompt_fields(self) -> None:
        cc.save_session(host="100.64.1.5", count=2, root=self.root)
        with patch.object(cc, "wire_agent_config", return_value={
            "ok": True,
            "saved": True,
            "configured": True,
            "message": "Cloud agent ready (FreeLLMAPI)",
            "free_path": True,
        }):
            plan = cc.connect_login("", 0, "", root=self.root, start_phones=True)
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["host"], "100.64.1.5")
        self.assertEqual(plan["count"], 2)
        self.assertTrue(plan["start_phones"])

    def test_agent_only_login_without_host(self) -> None:
        plan = cc.connect_login(
            "",
            0,
            "sk-agent-only",
            root=self.root,
            start_phones=True,
        )
        self.assertTrue(plan["ok"])
        self.assertFalse(plan["start_phones"])
        self.assertTrue(plan["agent"]["configured"])

    def test_cloud_agent_defaults_use_freellmapi_not_openai(self) -> None:
        agent_src = (ROOT / "tools" / "cloud_agent.py").read_text(encoding="utf-8")
        self.assertIn("http://127.0.0.1:31415/v1", agent_src)
        self.assertIn("cloud_connect", agent_src)
        # Paid OpenAI must not be the silent default anymore.
        self.assertNotIn(
            'os.environ.get("PHARMFLOW_CLOUD_AGENT_BASE", "https://api.openai.com/v1")',
            agent_src,
        )

    def test_bridge_exposes_one_login_apis(self) -> None:
        bridge = (ROOT / "wizard" / "pharmflow_wizard_bridge.py").read_text(encoding="utf-8")
        self.assertIn("def cloud_connect_login(", bridge)
        self.assertIn("def cloud_session_status(", bridge)
        self.assertIn("cloud_phone_setup(", bridge)
        web = (ROOT / "wizard" / "pharmflow_app_webview.py").read_text(encoding="utf-8")
        self.assertIn("def cloud_connect_login(", web)
        self.assertIn("def cloud_session_status(", web)
        html = (ROOT / "wizard" / "assets" / "pharmflow_app" / "index.html").read_text(encoding="utf-8")
        self.assertIn("btn-cloud-connect", html)
        self.assertIn("cloud-connect-widget", html)
        js = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        self.assertIn("cloud_connect_login", js)
        self.assertIn("cloud_session_status", js)


class CloudConnectBridgeContractTests(unittest.TestCase):
    """Bridge/webview one-login wiring without importing Tk-heavy bridge modules."""

    def test_bridge_cloud_connect_login_calls_phone_setup(self) -> None:
        bridge = (ROOT / "wizard" / "pharmflow_wizard_bridge.py").read_text(encoding="utf-8")
        fn = bridge.split("def cloud_connect_login(")[1].split("\ndef ")[0]
        self.assertIn("connect_login(", fn)
        self.assertIn("cloud_phone_setup(", fn)
        self.assertIn("start_phones", fn)
        # Must not invent a paid vendor or orphan farm runner here.
        self.assertNotIn("browserstack", fn.lower())
        self.assertNotIn("run_farm_354", fn)

    def test_desktop_menu_has_one_login(self) -> None:
        desk = (ROOT / "wizard" / "pharmflow_desktop.py").read_text(encoding="utf-8")
        self.assertIn("Cloud connect (one login)", desk)
        self.assertIn("cloud_connect_login", desk)


if __name__ == "__main__":
    unittest.main()
