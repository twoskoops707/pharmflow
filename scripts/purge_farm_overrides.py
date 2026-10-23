#!/usr/bin/env python3
"""Delete all farm override JSON — config is automation/pharmflow_farm_config.py."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from automation.pharmflow_farm_config import purge_legacy_override_files, reset_runtime, apply_farm_env


def main() -> int:
    removed = purge_legacy_override_files()
    reset_runtime(note="purge_cli")
    apply_farm_env()
    print("PURGED:", ", ".join(removed) or "(none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
