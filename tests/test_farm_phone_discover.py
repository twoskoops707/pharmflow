"""Tests for live money-phone discovery (CPharm ADB set, skip tablet/ghost)."""
from __future__ import annotations

from automation.farm_health_audit import scale_csv
from automation.farm_phone_discover import (
    _dedupe_sort,
    _select_money_set,
    inject_listener_count,
    inject_proxy_for_name,
    is_overflow_phone,
    is_skipped_money,
)
from automation.mumu_shell_cli import phone_vm_index


def test_inject_ports_follow_vm_index() -> None:
    assert inject_proxy_for_name("vm0.gmadoa") == "127.0.0.1:8218"
    assert inject_proxy_for_name("vm9") == "127.0.0.1:8227"
    assert inject_proxy_for_name("vm10.gmadoa") == "127.0.0.1:8228"
    assert inject_listener_count(["vm0", "vm10"]) == 11


def test_skip_tablet_and_ghost() -> None:
    # Unison canonical map bans ghost vm3/vm4/vm11 (vms .51/.132 were ghosts
    # that flapped); canonical money phones are vm0/vm1/vm5/vm7/vm9/...
    assert is_skipped_money("vm4.gmadoa")
    assert is_skipped_money("vm3")
    assert is_skipped_money("vm11")
    assert not is_skipped_money("vm9")
    assert not is_overflow_phone("vm10.gmadoa")
    assert not is_overflow_phone("vm8")


def test_all_cpharm_online_phones_farm() -> None:
    core = [
        (f"vm{i}", f"10.0.2.{i}:5555", inject_proxy_for_name(f"vm{i}"))
        for i in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)
    ]
    extra = [("vm10", "10.0.2.136:5555", "127.0.0.1:8228")]
    filled = _select_money_set(core + extra)
    names = [n for n, _, _ in filled]
    # Canonical-only money set: banned ghosts (vm3/vm4) and overflow bleed never
    # join the farm — vm10 (overflow) is still a canonical money phone.
    assert "vm10" in names
    assert "vm4" not in names
    assert "vm3" not in names
    assert set(names) == {"vm0", "vm1", "vm5", "vm7", "vm9", "vm10"}


def test_scale_csv_pads_heat_down_to_nine() -> None:
    visits = scale_csv("120,115,110,105,100,95", 9)
    assert visits == "120,115,110,105,100,95,90,85,80"
    ads = scale_csv("24,24,22,22,20,20", 9, min_val=16, step=0)
    assert ads == "24,24,22,22,20,20,20,20,20"


def test_stale_vm0_does_not_steal_live_serial() -> None:
    rows = [
        ("vm0", "10.0.2.104:5555", "127.0.0.1:8218"),
        ("vm10", "10.0.2.104:5555", "127.0.0.1:8228"),
        ("vm1", "10.0.2.215:5555", "127.0.0.1:8219"),
    ]
    out = _dedupe_sort(rows)
    by_name = {n: (s, p) for n, s, p in out}
    assert "vm0" not in by_name
    assert by_name["vm10"] == ("10.0.2.104:5555", "127.0.0.1:8228")
    assert by_name["vm1"][0] == "10.0.2.215:5555"


def test_phone_vm_index() -> None:
    assert phone_vm_index("vm2.gmadoa", 0) == 2
    assert phone_vm_index("vm9", 0) == 9
    assert phone_vm_index("weird", 4) == 4
