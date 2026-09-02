#!/usr/bin/env python3
"""Deprecated dev shim — use fix_mumu_fingerprint.py or CPharmMuMuSetup.exe → GO."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

sys.argv[0] = str(Path(__file__).resolve().parent / "fix_mumu_fingerprint.py")
runpy.run_path(str(Path(__file__).resolve().parent / "fix_mumu_fingerprint.py"), run_name="__main__")
