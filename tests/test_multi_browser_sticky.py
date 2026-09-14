"""Unique-seq must never stay locked to chromium-only via sticky."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation.farm_visit_caps import (
    MULTI_BROWSER,
    PATH3_BROWSERS,
    apply_runtime_overrides_to_env,
    enforce_multi_browser,
)


class MultiBrowserStickyTests(unittest.TestCase):
    def test_enforce_rewrites_chromium_only(self) -> None:
        ov = {
            "PHARMFLOW_FARM_CHROMIUM_ONLY": "1",
            "PHARMFLOW_FARM_BROWSERS": "chromium",
            "PHARMFLOW_FARM_PATH3_BROWSERS": "chromium,firefox,brave",
        }
        self.assertTrue(enforce_multi_browser(ov))
        self.assertEqual(ov["PHARMFLOW_FARM_CHROMIUM_ONLY"], "0")
        self.assertEqual(ov["PHARMFLOW_FARM_BROWSERS"], MULTI_BROWSER)
        self.assertEqual(ov["PHARMFLOW_FARM_PATH3_BROWSERS"], PATH3_BROWSERS)
        self.assertFalse(enforce_multi_browser(ov))

    def test_apply_runtime_overrides_refuses_chromium_lock(self) -> None:
        """Legacy sticky JSON is dead by design — code SSOT wins, chromium
        can never re-lock via that path (pharmflow_farm_config is the SSOT;
        legacy override files are purged at startup)."""
        with tempfile.TemporaryDirectory() as tmp:
            sticky = Path(tmp) / "farm_runtime_overrides.json"
            sticky.write_text(
                json.dumps(
                    {
                        "PHARMFLOW_FARM_CHROMIUM_ONLY": "1",
                        "PHARMFLOW_FARM_BROWSERS": "chromium",
                        "PHARMFLOW_FARM_SEQS_PER_HOUR": "14",
                    }
                ),
                encoding="utf-8",
            )
            env: dict[str, str] = {}
            apply_runtime_overrides_to_env(env, log_dir=Path(tmp))
            # SSOT values, NOT the sticky file's 14 / chromium lock.
            from automation.pharmflow_farm_config import get_runtime

            ssot = get_runtime()
            self.assertEqual(env["PHARMFLOW_FARM_SEQS_PER_HOUR"], ssot["PHARMFLOW_FARM_SEQS_PER_HOUR"])
            self.assertEqual(env["PHARMFLOW_FARM_CHROMIUM_ONLY"], "0")
            self.assertEqual(env["PHARMFLOW_FARM_BROWSERS"], MULTI_BROWSER)

    def test_operator_config_cannot_relock_chromium(self) -> None:
        from automation import farm_pause

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp)
            cfg = log / "farm_operator_config.json"
            ov_path = log / "farm_runtime_overrides.json"
            cfg.write_text(
                json.dumps(
                    {
                        "chromium_only": "1",
                        "unique_seq": "1",
                        "seqs_per_hour": "14",
                    }
                ),
                encoding="utf-8",
            )
            ov_path.write_text("{}", encoding="utf-8")
            with (
                patch.object(farm_pause, "CONFIG_FILE", cfg),
                patch.object(farm_pause, "OVERRIDES", ov_path),
                patch.object(farm_pause, "LOG", log),
            ):
                changed = farm_pause.apply_operator_config_to_overrides()
            data = json.loads(ov_path.read_text(encoding="utf-8"))
            self.assertEqual(data["PHARMFLOW_FARM_CHROMIUM_ONLY"], "0")
            self.assertEqual(data["PHARMFLOW_FARM_BROWSERS"], MULTI_BROWSER)
            self.assertIn("multi_browser", changed)
            self.assertEqual(data["PHARMFLOW_FARM_SEQS_PER_HOUR"], "14")


if __name__ == "__main__":
    unittest.main()
