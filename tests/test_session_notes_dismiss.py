"""Session-notes dismiss is an authored step, not a comment the runner skips."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.sequence_runner import Sequence, SequenceRunner, SequenceStep, StepAction  # noqa: E402
from automation.session_notes_uia import (  # noqa: E402
    step_wants_session_notes_dismiss,
    step_wants_session_notes_gone,
)


class SessionNotesDismissTests(unittest.TestCase):
    def test_authored_flags_are_the_only_trigger(self) -> None:
        self.assertTrue(step_wants_session_notes_dismiss({"verify_dismiss": True}))
        self.assertTrue(step_wants_session_notes_dismiss({"checkpoint": "popup_dismiss"}))
        self.assertFalse(step_wants_session_notes_dismiss({"checkpoint": "tab_glass"}))
        self.assertTrue(step_wants_session_notes_gone({"until_session_notes_gone": True}))
        self.assertTrue(step_wants_session_notes_gone({"checkpoint": "popup_dismissed"}))
        self.assertFalse(step_wants_session_notes_gone({"checkpoint": "timer_complete"}))

    def test_farm_load_keeps_the_dismiss_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "seq.json"
            path.write_text(
                json.dumps(
                    {
                        "name": "notes",
                        "steps": [
                            {"type": "tap", "x": 1, "y": 2, "verify_dismiss": True, "checkpoint": "popup_dismiss"},
                            {"type": "wait", "seconds": 0.5, "until_session_notes_gone": True, "checkpoint": "popup_dismissed"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            seq = Sequence.from_json(path)
        self.assertTrue(step_wants_session_notes_dismiss(seq.steps[0].params))
        self.assertTrue(step_wants_session_notes_gone(seq.steps[1].params))

    def test_wait_fails_when_the_sheet_is_still_up(self) -> None:
        farm = MagicMock()
        runner = SequenceRunner(farm)
        seq = Sequence(name="notes", phone="vm0", steps=[])
        with (
            patch("automation.sequence_runner.wait_session_notes_gone", return_value=False),
            patch("automation.sequence_runner.time.sleep"),
        ):
            result = runner._run_step(
                SequenceStep(
                    action=StepAction.WAIT,
                    params={"seconds": 0, "until_session_notes_gone": True},
                ),
                "vm0",
                "10.0.2.15:5555",
                seq,
            )
        self.assertFalse(result["ok"])
        self.assertIn("still up", result["error"])

    def test_plain_wait_does_not_dump_the_screen(self) -> None:
        farm = MagicMock()
        runner = SequenceRunner(farm)
        seq = Sequence(name="notes", phone="vm0", steps=[])
        with (
            patch("automation.sequence_runner.wait_session_notes_gone") as gone,
            patch("automation.sequence_runner.time.sleep"),
        ):
            result = runner._run_step(
                SequenceStep(action=StepAction.WAIT, params={"seconds": 0}),
                "vm0",
                "10.0.2.15:5555",
                seq,
            )
        self.assertTrue(result["ok"])
        gone.assert_not_called()

    def test_dashboard_group_runner_honors_the_same_flags(self) -> None:
        src = (ROOT / "automation" / "dashboard.py").read_text(encoding="utf-8")
        tap = src.split('elif t == "tap":', 1)[1].split('elif t == "wait":', 1)[0]
        wait = src.split('elif t == "wait":', 1)[1].split('elif t == "swipe":', 1)[0]
        self.assertIn("step_wants_session_notes_dismiss", tap)
        self.assertIn("popup dismiss did not land", tap)
        self.assertIn("step_wants_session_notes_gone", wait)
        self.assertIn("session notes still up", wait)


if __name__ == "__main__":
    unittest.main()
