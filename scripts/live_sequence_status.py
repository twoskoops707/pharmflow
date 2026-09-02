"""Print live sequence farm test status (read results + checkpoint)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wizard.wizard_paths import logs_dir


def main() -> None:
    results = logs_dir() / "live_sequence_results.jsonl"
    checkpoint = logs_dir() / "live_sequence_checkpoint.json"
    summary = logs_dir() / "live_sequence_summary.json"

    if summary.is_file():
        print(summary.read_text(encoding="utf-8"))
        return

    lines = []
    if results.is_file():
        lines = [json.loads(x) for x in results.read_text(encoding="utf-8").splitlines() if x.strip()]
    ok = sum(1 for e in lines if e.get("success"))
    fail = [e for e in lines if not e.get("success")]
    done = 0
    if checkpoint.is_file():
        try:
            done = len(json.loads(checkpoint.read_text(encoding="utf-8")).get("done", []))
        except (json.JSONDecodeError, OSError):
            pass
    print(f"Live test in progress: {len(lines)} logged, {ok} OK, {len(fail)} FAIL, {done} checkpointed")
    if lines:
        last = lines[-1]
        print(f"Last: {last.get('phone')} {last.get('sequence')} success={last.get('success')} ({last.get('elapsed_s')}s)")
    for e in fail[:20]:
        print(f"  FAIL {e.get('phone')} {e.get('sequence')}: {e.get('error')}")


if __name__ == "__main__":
    main()
