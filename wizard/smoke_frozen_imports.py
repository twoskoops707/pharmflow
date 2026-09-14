#!/usr/bin/env python3
"""
Frozen-wizard import smoke: same modules PyInstaller must resolve (NameError at import = CI fail).

Import order matches recommended frozen-app load: theme, sequence_humanize, browser_builder_webview, setup_wizard, pharmflow_desktop (PyInstaller entry).

From repo root:

  py -3 wizard/smoke_frozen_imports.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_WIZ = Path(__file__).resolve().parent
if str(_WIZ) not in sys.path:
    sys.path.insert(0, str(_WIZ))

import wizard_paths  # noqa: F401
import wizard_theme  # noqa: F401
import sequence_humanize  # noqa: F401
import browser_builder_webview  # noqa: F401
import setup_wizard  # noqa: F401
import pharmflow_desktop  # noqa: F401
import pharmflow_wizard_bridge  # noqa: F401

# PyInstaller must ship these for Boot/Go fingerprint + lazy wizard imports in PharmFlow.exe
wizard_paths.automation_on_sys_path()
import adb_paths  # noqa: F401
import browser_adb  # noqa: F401
import config  # noqa: F401
import device_open_url  # noqa: F401
import human_variation  # noqa: F401
import mumu_fingerprint  # noqa: F401
import mumu_farm_ops  # noqa: F401
import sequence_geometry  # noqa: F401
import sequence_normalize  # noqa: F401
import session_notes_uia  # noqa: F401
import tor_manager  # noqa: F401
import dabflow_mantis_client_patch  # noqa: F401


def main() -> int:
    import pharmflow_wizard_bridge as bridge

    steps = bridge.get_wizard_steps()
    # Deck + bridge share 10 steps (Site Map was added as step 6). Keep this
    # count in lockstep with WIZARD_STEPS / the deck STEP_IDS list.
    if len(steps) != 10:
        print(f"smoke_frozen_imports: expected 10 wizard steps, got {len(steps)}", file=sys.stderr)
        return 1
    rows = bridge.scan_prereqs()
    if not rows or len(rows) < 3:
        print("smoke_frozen_imports: scan_prereqs returned no rows", file=sys.stderr)
        return 1
    for step_id in ("steps", "builder", "teams"):
        if not hasattr(bridge, "open_classic_wizard"):
            print("smoke_frozen_imports: open_classic_wizard missing", file=sys.stderr)
            return 1
        if step_id not in bridge._STEP_ID_TO_INDEX:
            print(f"smoke_frozen_imports: unknown step {step_id!r}", file=sys.stderr)
            return 1
    print("smoke_frozen_imports: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
