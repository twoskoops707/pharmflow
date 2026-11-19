"""The live Tor SOCKS base must never be a port Windows reserves.

Hyper-V/WinNAT reserve a fresh TCP range every boot; a SocksPort inside one
fails with WSAEACCES. A stale ``tor_port_bases.json`` recording 9050 used to be
trusted, so every lane pointed at an unbindable port and the Start farm gate
refused on guest proxies with no upstream.
"""
from __future__ import annotations

import json

import automation.pharmflow_farm_config as cfg


def _stub_record(monkeypatch, tmp_path, socks_base: int) -> None:
    record = tmp_path / "tor_port_bases.json"
    record.write_text(json.dumps({"socks_base": socks_base}), encoding="utf-8")
    monkeypatch.setattr(
        cfg,
        "Path",
        lambda p: record if "tor_port_bases.json" in str(p) else type(record)(str(p)),
    )


def test_stored_9050_is_rejected(monkeypatch, tmp_path):
    _stub_record(monkeypatch, tmp_path, 9050)
    monkeypatch.setattr(cfg, "_windows_excluded_tcp_ranges", lambda: [])
    monkeypatch.delenv("PHARMFLOW_TOR_SOCKS_BASE", raising=False)

    assert cfg._resolve_tor_socks_base() == cfg._SAFE_SOCKS_BASE


def test_excluded_range_forces_a_different_base(monkeypatch, tmp_path):
    excluded = [(9036, 9700)]
    _stub_record(monkeypatch, tmp_path, 9600)
    monkeypatch.setattr(cfg, "_windows_excluded_tcp_ranges", lambda: excluded)
    monkeypatch.delenv("PHARMFLOW_TOR_SOCKS_BASE", raising=False)

    resolved = cfg._resolve_tor_socks_base()

    assert resolved != 9600
    assert cfg._socks_base_is_bindable(resolved, excluded) is True


def test_bindable_stored_base_is_kept(monkeypatch, tmp_path):
    _stub_record(monkeypatch, tmp_path, 9550)
    monkeypatch.setattr(cfg, "_windows_excluded_tcp_ranges", lambda: [(45027, 45126)])
    monkeypatch.delenv("PHARMFLOW_TOR_SOCKS_BASE", raising=False)

    assert cfg._resolve_tor_socks_base() == 9550


def test_lane_span_is_what_gets_checked():
    span = cfg._SOCKS_LANE_SPAN
    excluded = [(9550 + span - 1, 9600)]

    assert cfg._socks_base_is_bindable(9550, excluded) is False
    assert cfg._socks_base_is_bindable(9550, [(9036, 9500)]) is True
