"""Boot-order host gates (scaling plan) — regression tests.

The EXE's boot path and the farm's self-heal spin-up must never launch a VM
into a starved host (RAM floor + CPU ceiling), paced one launch at a time.
These gates are host-health only — they must not cap phone count.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture()
def bg():
    from automation import boot_gates as bg_mod

    return bg_mod


def test_headroom_ok_judges_samples(bg) -> None:
    good = {"free_ram_mb": 4000.0, "total_ram_mb": 16000.0, "cpu_pct": 40.0}
    low_ram = {"free_ram_mb": 500.0, "total_ram_mb": 16000.0, "cpu_pct": 10.0}
    hot_cpu = {"free_ram_mb": 4000.0, "total_ram_mb": 16000.0, "cpu_pct": 99.0}

    ok, why = bg.headroom_ok(good, min_free_ram_mb=2200, max_cpu_pct=85)
    assert ok and "ok" in why

    ok, why = bg.headroom_ok(low_ram, min_free_ram_mb=2200, max_cpu_pct=85)
    assert not ok and "RAM" in why

    ok, why = bg.headroom_ok(hot_cpu, min_free_ram_mb=2200, max_cpu_pct=85)
    assert not ok and "CPU" in why


def test_host_headroom_sample_shape(bg) -> None:
    s = bg.host_headroom()
    assert {"free_ram_mb", "total_ram_mb", "cpu_pct"} <= set(s)
    assert s["free_ram_mb"] >= 0 and 0.0 <= s["cpu_pct"] <= 100.0


def test_gate_disabled_env_bypasses_wait(bg, monkeypatch) -> None:
    monkeypatch.setenv("CPHARM_BOOT_GATE_DISABLED", "1")
    assert bg.wait_for_boot_headroom(label="t") is True


def test_wait_returns_false_on_timeout_not_forever(bg, monkeypatch) -> None:
    """Impossible thresholds must time out (skip launch), never wedge the boot."""
    monkeypatch.setattr(bg, "GATE_POLL_S", 0.05)
    ok = bg.wait_for_boot_headroom(
        label="t",
        min_free_ram_mb=10**9,
        timeout_s=0.5,
        log_fn=lambda m: None,
    )
    assert ok is False


def test_wait_passes_when_headroom_available(bg) -> None:
    ok = bg.wait_for_boot_headroom(
        label="t",
        min_free_ram_mb=1.0,
        max_cpu_pct=100.0,
        timeout_s=5.0,
    )
    assert ok is True


def test_gate_settings_env_overrides(bg, monkeypatch) -> None:
    monkeypatch.setenv("CPHARM_BOOT_MIN_FREE_RAM_MB", "1500")
    monkeypatch.setenv("CPHARM_BOOT_MAX_CPU_PCT", "70")
    s = bg.gate_settings()
    assert s["min_free_ram_mb"] == 1500.0 and s["max_cpu_pct"] == 70.0
