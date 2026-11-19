"""No phones answering ADB must not look like a stealth failure.

``evaluate_start_gate`` set ``stealth_ok``/``proxy_ok`` to False when the fleet
was empty, which is the same shape as a real stealth leak. Start farm then
wrote FARM_STEALTH_GATE_STOP.json + sticky PHARMFLOW_FARM_STOP=1, and the farm
stayed refused even after the phones finished booting — the recurring "farm
stopped again" symptom.
"""
from __future__ import annotations

import tools.farm_start_gate as gate


def _no_funds(monkeypatch):
    monkeypatch.setattr(gate, "_funds_snapshot", lambda: {})
    monkeypatch.setattr(gate, "_income_path_ready", lambda prefs: (True, []))
    monkeypatch.setattr(gate, "_desktop_prefs", lambda: {})


def test_empty_fleet_reports_no_verdict(monkeypatch, tmp_path):
    _no_funds(monkeypatch)
    monkeypatch.setattr(gate, "_logs_dir", lambda: tmp_path)
    monkeypatch.setattr(gate, "_proxy_audit", lambda phones, log=None: {"ok": False, "total": 0})
    monkeypatch.setattr(
        gate,
        "_stealth_audit",
        lambda phones, log=None: {"ok": True, "all_clean": True, "phones": 0},
    )

    result = gate.evaluate_start_gate(serials=[], apply_stealth_defaults=False)

    assert result["ok"] is False
    assert result["stealth_ok"] is None
    assert result["proxy_ok"] is None
    assert "no phones answering" in str(result["error"])


def test_empty_fleet_still_refuses(monkeypatch, tmp_path):
    _no_funds(monkeypatch)
    monkeypatch.setattr(gate, "_logs_dir", lambda: tmp_path)
    monkeypatch.setattr(gate, "_proxy_audit", lambda phones, log=None: {"ok": False, "total": 0})
    monkeypatch.setattr(
        gate,
        "_stealth_audit",
        lambda phones, log=None: {"ok": True, "all_clean": True, "phones": 0},
    )

    result = gate.evaluate_start_gate(serials=[], apply_stealth_defaults=False)

    assert result["gate_label"]
    assert result["phone_count"] == 0
