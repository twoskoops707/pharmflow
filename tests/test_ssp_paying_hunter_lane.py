"""PharmFlow paying hunter must be owned by tip EXE — not FamFlow/CPharm."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import automation.ssp_paying_hunter_lane as lane


def test_foreign_famflow_cmdline_does_not_count_as_pharmflow() -> None:
    cmd = r"C:\FamFlow\pythonw.exe -u C:\CPharm\scripts\ssp_paying_hunter.py"
    assert lane.cmdline_has_hunter(cmd)
    assert lane.cmdline_looks_foreign(cmd)
    assert not lane.cmdline_looks_pharmflow(cmd)


def test_pharmflow_cmdline_counts_as_owned() -> None:
    cmd = r"C:\Python314\pythonw.exe -u C:\PharmFlow\scripts\ssp_paying_hunter.py"
    assert lane.cmdline_has_hunter(cmd)
    assert lane.cmdline_looks_pharmflow(cmd)
    assert not lane.cmdline_looks_foreign(cmd)


def test_process_ownership_via_env_flag() -> None:
    proc = SimpleNamespace(
        cmdline=lambda: ["pythonw.exe", "-u", "scripts\\ssp_paying_hunter.py"],
        environ=lambda: {"PHARMFLOW_EXE_OWNED_FARM": "1"},
        cwd=lambda: r"C:\Users\tmp\AppData\Local\Temp\_MEI123",
    )
    assert lane.process_is_pharmflow_hunter(proc)
    assert not lane.process_is_foreign_hunter(proc)


def test_process_foreign_cpharm_cwd() -> None:
    proc = SimpleNamespace(
        cmdline=lambda: ["pythonw.exe", "-u", "scripts\\ssp_paying_hunter.py"],
        environ=lambda: {"PYTHONPATH": r"C:\CPharm"},
        cwd=lambda: r"C:\CPharm",
    )
    assert not lane.process_is_pharmflow_hunter(proc)
    assert lane.process_is_foreign_hunter(proc)


def test_ensure_spawns_when_only_foreign_hunter_alive(tmp_path: Path, monkeypatch) -> None:
    script = tmp_path / "scripts" / "ssp_paying_hunter.py"
    script.parent.mkdir(parents=True)
    script.write_text("# hunter\n", encoding="utf-8")
    (tmp_path / "automation").mkdir()

    foreign = SimpleNamespace(
        pid=111,
        cmdline=lambda: [
            r"C:\FamFlow\pythonw.exe",
            "-u",
            r"C:\CPharm\scripts\ssp_paying_hunter.py",
        ],
        environ=lambda: {},
        cwd=lambda: r"C:\CPharm",
        kill=mock.Mock(),
    )

    class _ProcIter:
        def __init__(self, procs):
            self._procs = procs

        def __iter__(self):
            return iter(self._procs)

    fake_psutil = SimpleNamespace(
        process_iter=lambda attrs=None: _ProcIter([foreign]),
        Process=lambda pid: foreign if pid == 111 else SimpleNamespace(kill=mock.Mock()),
        Error=Exception,
    )
    monkeypatch.setitem(__import__("sys").modules, "psutil", fake_psutil)
    monkeypatch.setattr(lane, "spawn_pharmflow_paying_hunter", lambda root=None: 999)
    monkeypatch.setattr(lane, "pharmflow_hunter_pids", lambda: [])
    monkeypatch.setattr(lane, "foreign_hunter_pids", lambda: [111])
    monkeypatch.setattr(lane, "time", SimpleNamespace(sleep=lambda _s: None))

    notes = lane.ensure_pharmflow_paying_hunter(root=tmp_path, cull_foreign=True)
    assert any(n.startswith("kill_foreign_hunter") for n in notes)
    assert "spawn_pharmflow_hunter pid=999" in notes


def test_ensure_ok_when_pharmflow_hunter_already_alive(monkeypatch) -> None:
    monkeypatch.setattr(lane, "cull_foreign_paying_hunters", lambda: [])
    monkeypatch.setattr(lane, "pharmflow_hunter_pids", lambda: [4242])
    monkeypatch.setattr(
        lane,
        "spawn_pharmflow_paying_hunter",
        lambda root=None: (_ for _ in ()).throw(AssertionError("must not spawn")),
    )
    notes = lane.ensure_pharmflow_paying_hunter(cull_foreign=True)
    assert notes == ["pharmflow_hunter_ok pid=4242"]


def test_unison_lanes_include_ssp_hunter() -> None:
    src = Path(__file__).resolve().parents[1] / "scripts" / "pharmflow_unison_supervisor.py"
    text = src.read_text(encoding="utf-8")
    assert '("ssp-hunter", "ssp_paying_hunter.py"' in text
    assert "ensure_pharmflow_paying_hunter" in text
    assert "process_is_pharmflow_hunter" in text


def test_hunter_primary_log_is_pharmflow() -> None:
    src = Path(__file__).resolve().parents[1] / "scripts" / "ssp_paying_hunter.py"
    text = src.read_text(encoding="utf-8")
    assert 'or r"C:\\PharmFlow\\logs"' in text
    assert '_LOG_MIRRORS = (Path(r"C:\\PharmFlow\\logs"), Path(r"C:\\CPharm\\logs"))' in text
    assert "ssp_paying_hunter_heartbeat.txt" in text
