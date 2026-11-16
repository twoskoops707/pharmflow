"""Ownership flag reconcile — sticky flag after EXE death must clear."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import automation.pharmflow_exe_owned as owned


def test_reconcile_noop_when_exe_alive(tmp_path: Path, monkeypatch) -> None:
    flag = tmp_path / "PHARMFLOW_EXE_OWNED.flag"
    flag.write_text("owned_by=PharmFlow.exe\n", encoding="utf-8")
    monkeypatch.setattr(owned, "EXE_OWNED_FLAG", flag)
    monkeypatch.delenv("PHARMFLOW_EXE_OWNED_FARM", raising=False)
    monkeypatch.delenv("PHARMFLOW_FARM_IN_PROCESS", raising=False)

    with mock.patch.object(owned, "pharmflow_exe_alive", return_value=True):
        notes = owned.reconcile_stale_exe_ownership(reap=False)

    assert notes == []
    assert flag.is_file()


def test_reconcile_clears_stale_flag_without_reap(tmp_path: Path, monkeypatch) -> None:
    flag = tmp_path / "PHARMFLOW_EXE_OWNED.flag"
    flag.write_text("owned_by=PharmFlow.exe\n", encoding="utf-8")
    monkeypatch.setattr(owned, "EXE_OWNED_FLAG", flag)
    monkeypatch.delenv("PHARMFLOW_EXE_OWNED_FARM", raising=False)
    monkeypatch.delenv("PHARMFLOW_FARM_IN_PROCESS", raising=False)

    with mock.patch.object(owned, "pharmflow_exe_alive", return_value=False):
        notes = owned.reconcile_stale_exe_ownership(reap=False)

    assert "stale_exe_owned" in notes
    assert "cleared_stale_exe_owned" in notes
    assert not flag.is_file()
    assert not owned.exe_owns_farm()


def test_reconcile_reap_runs_once_when_stale(tmp_path: Path, monkeypatch) -> None:
    flag = tmp_path / "PHARMFLOW_EXE_OWNED.flag"
    flag.write_text("owned_by=PharmFlow.exe\n", encoding="utf-8")
    monkeypatch.setattr(owned, "EXE_OWNED_FLAG", flag)
    monkeypatch.delenv("PHARMFLOW_EXE_OWNED_FARM", raising=False)
    monkeypatch.delenv("PHARMFLOW_FARM_IN_PROCESS", raising=False)

    with mock.patch.object(owned, "pharmflow_exe_alive", return_value=False):
        with mock.patch(
            "automation.farm_exe_self_heal.reap_stale_processes",
            return_value=["extra_reap clean", "storm_reap clean"],
        ) as reap_fn:
            notes = owned.reconcile_stale_exe_ownership(reap=True)

    reap_fn.assert_called_once_with(apply=True)
    assert "cleared_stale_exe_owned" in notes
    assert "extra_reap clean" in notes
    assert not flag.is_file()


def test_farm_keep_excludes_competing_babysitters() -> None:
    from tools.pharmflow_watchdog import FARM_KEEP_SCRIPTS

    for poison in (
        "ensure_farm_24x7.py",
        "keep_farm_alive.py",
        "farm_remediate_loop.py",
        "cpharm_unison_supervisor.py",
    ):
        assert poison not in FARM_KEEP_SCRIPTS, poison
    assert "pharmflow_unison_supervisor.py" in FARM_KEEP_SCRIPTS
