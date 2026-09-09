"""Tests for live money-phone discovery (CPharm ADB set, skip tablet/ghost)."""
from __future__ import annotations

from unittest.mock import patch

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
    # Roster-less fleet (commit 5fa7926): the only banned names are the MuMu
    # base image ("base"/"base.gmadoa") and the retired ghost vm11. Real VM
    # names (vm4 etc.) are farmable when their folder exists on disk.
    assert is_skipped_money("base.gmadoa")
    assert is_skipped_money("base")
    assert is_skipped_money("vm11.gmadoa")
    assert not is_skipped_money("vm4.gmadoa")
    assert not is_skipped_money("vm9")
    assert not is_overflow_phone("vm10.gmadoa")
    assert not is_overflow_phone("vm8")


def test_all_cpharm_online_phones_farm() -> None:
    import automation.farm_phone_discover as fpd

    core = [
        (f"vm{i}", f"10.0.2.{i}:5555", inject_proxy_for_name(f"vm{i}"))
        for i in range(0, 10)
    ]
    extra = [("vm10", "10.0.2.136:5555", "127.0.0.1:8228")]
    # is_canonical_phone answers from the LIVE fleet on this box — patch the
    # fleet so the test is machine-independent (CI has no MuMu VMs).
    fleet = {f"vm{i}.gmadoa": f"10.0.2.{i}:5555" for i in range(0, 11)}
    with patch.object(fpd, "is_canonical_phone", lambda n: f"{n.split('.')[0]}.gmadoa" in fleet):
        filled = fpd._select_money_set(core + extra)
    names = [n for n, _, _ in filled]
    # Roster-less: every live vm is farmable; only banned names (base/vm11) and
    # non-fleet names stay out; overflow bleed never joins.
    assert "vm10" in names
    assert "vm4" in names
    assert "vm3" in names
    assert set(names) == {f"vm{i}" for i in range(0, 11)}


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
