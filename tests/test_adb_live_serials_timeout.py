"""adb_live_serials must honour the ``timeout`` kwarg shipped callers pass.

The EXE deck self-test failed with
``adb_live_serials() got an unexpected keyword argument 'timeout'`` because the
helper had no such parameter while the deck bridge, wizard and walkthrough all
passed one. That TypeError hid the live phone count from the Control Panel.
"""
from __future__ import annotations

import automation.farm_exe_self_heal as heal


def test_adb_live_serials_accepts_timeout_and_bounds_the_call(monkeypatch):
    seen: dict[str, object] = {}

    def fake_run(cmd, timeout=None, **kwargs):
        seen["cmd"] = list(cmd)
        seen["timeout"] = timeout
        return 0, "10.0.2.62:5555\tdevice\n127.0.0.1:20158\toffline\n"

    monkeypatch.setattr(heal, "_run", fake_run)
    monkeypatch.setattr(heal, "_adb_bin", lambda: "adb.exe")

    serials = heal.adb_live_serials(timeout=4.0)

    assert serials == ["10.0.2.62:5555"]
    assert seen["timeout"] == 4.0


def test_adb_live_serials_defaults_to_full_budget(monkeypatch):
    seen: dict[str, object] = {}

    def fake_run(cmd, timeout=None, **kwargs):
        seen["timeout"] = timeout
        return 0, ""

    monkeypatch.setattr(heal, "_run", fake_run)
    monkeypatch.setattr(heal, "_adb_bin", lambda: "adb.exe")

    assert heal.adb_live_serials() == []
    assert seen["timeout"] == 25.0
