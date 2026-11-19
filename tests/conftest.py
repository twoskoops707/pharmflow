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
import tempfile
from pathlib import Path

import pytest

_WIZARD_DIR = Path(__file__).resolve().parents[1] / "wizard"
if str(_WIZARD_DIR) not in sys.path:
    sys.path.insert(0, str(_WIZARD_DIR))

# Keep vars that must survive (none currently, but explicit beats implicit).
_KEEP = {"PHARMFLOW_ALLOW_SEQUENCE_RUNS", "PHARMFLOW_PORT", "PHARMFLOW_HOST"}
for _key in [k for k in os.environ if k.startswith("PHARMFLOW_") and k not in _KEEP]:
    del os.environ[_key]

# Tests must never read or write the operator's LIVE farm state. Without an
# explicit log root, the start gate, phone budget and Tor prewarm resolvers all
# fall back to C:\PharmFlow\logs — so a test run both read the host lock map
# (wrong phone counts) and could latch a real FARM_STOP that then refused every
# later Start farm. Point every log-root variable at a throwaway session dir.
_TEST_LOGS_DIR = Path(tempfile.mkdtemp(prefix="pharmflow-test-logs-"))
for _key in ("PHARMFLOW_LOG_DIR", "PHARMFLOW_LOGS", "CPHARM_LOGS", "CPHARM_LOG_DIR"):
    os.environ[_key] = str(_TEST_LOGS_DIR)


@pytest.fixture(autouse=True)
def _reset_bridge_start_latch():
    """Clear the module-global Start-farm latch between tests.

    ``_farm_starting``/``_farm_start_result`` live on the bridge module. A test
    that starts an adoption/dashboard worker leaves them set, so a later test
    sees ``start_farm_from_app()`` answer "already in progress" and fails on
    state it never created.
    """
    try:
        import pharmflow_wizard_bridge as _bridge
    except Exception:  # noqa: BLE001 — suite may run without the wizard path
        yield
        return
    _bridge._farm_starting = False
    _bridge._farm_start_result = {}
    yield
    _bridge._farm_starting = False
    _bridge._farm_start_result = {}


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
