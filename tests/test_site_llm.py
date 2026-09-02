"""Tests for optional Site Interview LLM assist."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from automation.site_profile import interview_defaults
from wizard.site_llm import apply_suggestions_to_interview_vars, suggest_profile_fields


class SiteLlmTests(unittest.TestCase):
    @patch("wizard.site_llm._chat_completion")
    def test_suggest_parses_json(self, mock_chat: MagicMock) -> None:
        mock_chat.return_value = json.dumps(
            {
                "display_name": "Example",
                "humanize": "aggressive",
                "has_gate": True,
                "gate_xy": "400,900",
                "rationale": "Age gate likely near center.",
            }
        )
        draft = interview_defaults(kind="website", name="Ex", url="https://example.com")
        out = suggest_profile_fields(draft)
        self.assertEqual(out["display_name"], "Example")
        self.assertEqual(out["humanize"], "aggressive")
        mock_chat.assert_called_once()

    def test_apply_suggestions(self) -> None:
        app = MagicMock()
        app._si_name = MagicMock()
        app._si_humanize = MagicMock()
        app._si_gate = MagicMock()
        app._si_gate_xy = MagicMock()
        app._si_kind = MagicMock()
        app._si_url = MagicMock()
        app._si_package = MagicMock()
        app._si_core_xy = MagicMock()
        app._si_core_scroll = MagicMock()
        app._si_browse = MagicMock()
        app._si_ads = MagicMock()
        app._si_phones = MagicMock()
        app._si_seqs_hr = MagicMock()
        app._si_hours = MagicMock()
        app._si_ads_hr = MagicMock()
        app._si_start_spread = MagicMock()
        app._si_ntfy = MagicMock()
        applied = apply_suggestions_to_interview_vars(
            app,
            {
                "display_name": "Demo",
                "humanize": "conservative",
                "has_gate": False,
                "target_kind": "app",
            },
        )
        self.assertIn("display_name", applied)
        app._si_name.set.assert_called_with("Demo")
        app._si_humanize.set.assert_called_with("conservative")
        app._si_gate.set.assert_called_with(False)
        app._si_kind.set.assert_called_with("app")


if __name__ == "__main__":
    unittest.main()
