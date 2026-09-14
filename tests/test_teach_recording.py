"""Teach Mode must not claim a recording or a replay that did not land."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "automation") not in sys.path:
    sys.path.insert(0, str(ROOT / "automation"))

import teach  # noqa: E402


class TeachRecordingTests(unittest.TestCase):
    def test_start_is_not_a_recording_when_getevent_exits(self) -> None:
        proc = MagicMock()
        proc.poll.return_value = 1
        proc.stdout = MagicMock()
        with (
            patch.object(teach, "adb_executable", return_value="adb"),
            patch.object(teach.subprocess, "Popen", return_value=proc),
        ):
            out = teach.start_recording("10.0.2.20:5555")
        self.assertIsNone(out)
        self.assertFalse(teach._recording_active)

    def test_replay_does_not_count_a_failed_sendevent(self) -> None:
        rec = teach.REC_DIR / "session_honesty_test.rec"
        rec.write_text(
            json.dumps([
                {"t": 0, "d": "/dev/input/event1", "type": "0003", "code": "0035", "value": "00000001"},
            ]),
            encoding="utf-8",
        )
        failed = MagicMock(returncode=1)
        try:
            with (
                patch.object(teach, "adb_executable", return_value="adb"),
                patch.object(teach.subprocess, "run", return_value=failed),
            ):
                sent = teach.replay_on_phone("10.0.2.20:5555", str(rec))
        finally:
            rec.unlink(missing_ok=True)
        self.assertEqual(sent, 0)


if __name__ == "__main__":
    unittest.main()
