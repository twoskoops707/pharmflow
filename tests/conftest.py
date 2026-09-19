"""Mirror the runtime import paths the frozen app and wizard smoke scripts use.

``wizard/pharmflow_wizard_bridge.py`` imports ``setup_wizard`` and ``wizard_theme``
as top-level modules — valid because the webview shell inserts ``wizard/`` into
``sys.path`` before importing it (and the CI smoke scripts do the same). Tests
importing the bridge need the same path setup.

Also: this dev box has operator ``PHARMFLOW_*`` variables set user-globally, which
leaks machine state into tests (SEQS_PER_HOUR, PHONE_COUNT, Tor ports...).
Scrub them BEFORE any test module import so module-level ``os.environ`` reads
see a clean slate. A whitelist keeps explicit per-test patches working.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_WIZARD_DIR = Path(__file__).resolve().parents[1] / "wizard"
if str(_WIZARD_DIR) not in sys.path:
    sys.path.insert(0, str(_WIZARD_DIR))

# Keep vars that must survive (none currently, but explicit beats implicit).
_KEEP = {"PHARMFLOW_ALLOW_SEQUENCE_RUNS", "PHARMFLOW_PORT", "PHARMFLOW_HOST"}
for _key in [k for k in os.environ if k.startswith("PHARMFLOW_") and k not in _KEEP]:
    del os.environ[_key]


@pytest.fixture(autouse=True)
def _isolate_env_per_test():
    """Snapshot/restore os.environ around every test.

    The scrub above only runs once per session — a single test that mutates the
    environment (e.g. the real start_farm writing PHARMFLOW_UNISON_MODE) would
    otherwise poison every later test in the process (the sequence-isolation
    skip veto leaked exactly that way).
    """
    snapshot = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(snapshot)
