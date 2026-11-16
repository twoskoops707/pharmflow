"""1:1 phone-side process budget — live phone count owns Tor/inject helpers."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from automation.phone_process_budget import (
    PhoneBudget,
    active_phone_budget,
    enforce_phone_process_budget,
    phone_helper_count,
    prune_surplus_inject,
    prune_surplus_tor,
)


def test_active_budget_is_one_to_one_with_lock_map(tmp_path: Path, monkeypatch) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "ADB_SERIAL_MAP.lock.json").write_text(
        json.dumps(
            {
                "phones": {
                    "vm24.gmadoa": "10.0.2.10:5555",
                    "vm27.gmadoa": "10.0.2.11:5555",
                    "vm39.gmadoa": "10.0.2.12:5555",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PHARMFLOW_LOGS", str(logs))
    live = {"10.0.2.10:5555", "10.0.2.11:5555", "10.0.2.12:5555"}
    with patch(
        "automation.phone_process_budget._adb_live_serials", return_value=live
    ):
        budget = active_phone_budget(live_serials=live)
    assert budget.count == 3
    assert budget.abs_indices == (24, 27, 39)
    assert budget.slots == (0, 1, 2)
    assert budget.inject_ports == (8242, 8245, 8257)
    assert len(budget.slots) == len(budget.abs_indices) == budget.count


def test_enforce_publishes_slot_map_and_reports_budget(tmp_path: Path, monkeypatch) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "ADB_SERIAL_MAP.lock.json").write_text(
        json.dumps(
            {
                "phones": {
                    "vm5.gmadoa": "10.0.2.5:5555",
                    "vm8.gmadoa": "10.0.2.8:5555",
                }
            }
        ),
        encoding="utf-8",
    )
    (logs / "tor_port_bases.json").write_text(
        json.dumps({"http_base": 8118, "socks_base": 9050}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PHARMFLOW_LOGS", str(logs))
    live = {"10.0.2.5:5555", "10.0.2.8:5555"}

    with patch(
        "automation.phone_process_budget.prune_surplus_tor",
        return_value=["tor_budget_ok n=2"],
    ), patch(
        "automation.phone_process_budget.prune_surplus_inject",
        return_value=["inject_inproc_ok n=2"],
    ):
        fixes = enforce_phone_process_budget(live_serials=live, apply=False)

    text = " ".join(fixes)
    assert "phone_budget n=2" in text
    assert "slot_map n=2" in text
    import os

    assert os.environ.get("PHARMFLOW_INJECT_SLOT_MAP")
    mapping = json.loads(os.environ["PHARMFLOW_INJECT_SLOT_MAP"])
    assert mapping == {"5": 0, "8": 1}


def test_prune_surplus_tor_targets_slots_beyond_n(tmp_path: Path, monkeypatch) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "tor_port_bases.json").write_text(
        json.dumps({"http_base": 8118}), encoding="utf-8"
    )
    monkeypatch.setenv("PHARMFLOW_LOGS", str(logs))
    budget = PhoneBudget(
        names=("vm1.gmadoa",),
        serials=("10.0.2.1:5555",),
        abs_indices=(1,),
        slots=(0,),
        count=1,
    )
    # Slot 0 allowed; slot 3 (8121) is surplus.
    with patch(
        "automation.phone_process_budget._tcp_open",
        side_effect=lambda port, timeout=0.35: int(port) == 8121,
    ), patch(
        "automation.phone_process_budget._listening_pid", return_value=4242
    ), patch(
        "automation.phone_process_budget._kill_pid", return_value=True
    ):
        fixes = prune_surplus_tor(budget=budget, apply=True)
    assert any("tor_surplus_killed pid=4242 port=8121" in f for f in fixes), fixes


def test_prune_surplus_inject_stops_out_of_budget_inproc() -> None:
    budget = PhoneBudget(
        names=("vm24.gmadoa",),
        serials=("10.0.2.24:5555",),
        abs_indices=(24,),
        slots=(0,),
        count=1,
    )
    with patch(
        "automation.mantis_inject_proxy.stop_inject_proxies_except",
        return_value=[25, 26],
    ) as stop, patch(
        "automation.phone_process_budget._tcp_open", return_value=False
    ):
        fixes = prune_surplus_inject(budget=budget, apply=True)
    stop.assert_called_once_with([24])
    assert any("inject_inproc_stopped idxs=[25, 26]" in f for f in fixes), fixes
