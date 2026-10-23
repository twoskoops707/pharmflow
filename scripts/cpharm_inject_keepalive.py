#!/usr/bin/env python3
"""Compat alias — live EXE/supervisor may still spawn this path name."""
from __future__ import annotations

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("pharmflow_inject_keepalive.py")), run_name="__main__")
