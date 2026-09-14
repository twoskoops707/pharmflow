"""Type text and named keys must survive sequence load and must not pretend to land."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.sequence_runner import Sequence, SequenceRunner, SequenceStep, StepAction, _key_code  # noqa: E402


class SequenceTypeTextTests(unittest.TestCase):
    def test_builder_type_text_and_named_back_are_not_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "seq.json"
            path.write_text(
                json.dumps(
                    {
                        "name": "type",
                        "steps": [
                            {"type": "type_text", "text": "hello world"},
                            {"type": "keyevent", "key": "BACK"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            seq = Sequence.from_json(path)
        self.assertEqual(seq.steps[0].action, StepAction.TYPE_TEXT)
        self.assertEqual(seq.steps[0].params["text"], "hello world")
        self.assertEqual(_key_code(seq.steps[1].params), 4)

    def test_empty_type_text_is_not_a_typed_step(self) -> None:
        farm = MagicMock()
        runner = SequenceRunner(farm)
        seq = Sequence(name="empty", phone="vm0", steps=[])
        result = runner._run_step(
            SequenceStep(action=StepAction.TYPE_TEXT, params={"text": ""}),
            "vm0",
            "10.0.2.15:5555",
            seq,
        )
        self.assertFalse(result["ok"])
        farm.adb.shell.assert_not_called()
        farm.adb.shell.return_value = type("R", (), {"ok": False})()
        missed = runner._run_step(
            SequenceStep(action=StepAction.TYPE_TEXT, params={"text": "hi"}),
            "vm0",
            "10.0.2.15:5555",
            seq,
        )
        self.assertFalse(missed["ok"])
        farm.adb.shell.assert_called_once()


if __name__ == "__main__":
    unittest.main()
