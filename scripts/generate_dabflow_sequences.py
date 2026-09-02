#!/usr/bin/env python3
"""CLI wrapper — generation lives in automation.dabflow_sequence_gen (EXE-importable)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from automation.dabflow_sequence_gen import main

if __name__ == "__main__":
    main()
