"""Boot-order host gates: CPU/RAM headroom before launching another VM.

Implements the scaling plan's boot-order rule inside the farm's own boot code,
so the EXE enforces it automatically: never launch the next emulator while the
host is starved (RAM free below the floor or CPU saturated), and pace boots
one at a time (the boot loop already waits for each phone's ADB before
continuing — the gate adds the host-health condition to that pacing).

This is a host-health gate, NOT a phone-count cap: there is no limit on how
many phones may run. It only delays (or skips, on timeout) the *next* VM
launch until the host can absorb it without wedging the whole farm.

Env knobs (all optional):
- ``PHARMFLOW_BOOT_MIN_FREE_RAM_MB`` — floor for free RAM before a launch (default 2200)
- ``PHARMFLOW_BOOT_MAX_CPU_PCT``     — CPU ceiling for a launch window (default 85)
- ``PHARMFLOW_BOOT_GATE_TIMEOUT_S``  — max seconds to wait for headroom per phone (default 600)
- ``PHARMFLOW_BOOT_GATE_DISABLED``   — set to ``1`` to bypass gates entirely
"""

from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

DEFAULT_MIN_FREE_RAM_MB = 2200
DEFAULT_MAX_CPU_PCT = 85.0
DEFAULT_GATE_TIMEOUT_S = 600.0
GATE_POLL_S = 5.0


def _env_float(name: str, default: float) -> float:
    try:
        raw = os.environ.get(name, "").strip()
        return float(raw) if raw else default
    except (TypeError, ValueError):
        return default


def gate_disabled() -> bool:
    return os.environ.get("PHARMFLOW_BOOT_GATE_DISABLED", "").strip() in {"1", "true", "yes"}


def gate_settings() -> dict:
    """Effective gate thresholds (surfaced in logs so operators see the knobs)."""
    return {
        "min_free_ram_mb": _env_float("PHARMFLOW_BOOT_MIN_FREE_RAM_MB", DEFAULT_MIN_FREE_RAM_MB),
        "max_cpu_pct": _env_float("PHARMFLOW_BOOT_MAX_CPU_PCT", DEFAULT_MAX_CPU_PCT),
        "timeout_s": _env_float("PHARMFLOW_BOOT_GATE_TIMEOUT_S", DEFAULT_GATE_TIMEOUT_S),
        "disabled": gate_disabled(),
    }


def host_headroom() -> dict:
    """One-shot host health sample: free RAM in MB and a short CPU average."""
    import psutil

    vm = psutil.virtual_memory()
    # Non-blocking windowed CPU sample: interval=None diffs since the last call;
    # prime with a short blocking sample so the first read is meaningful.
    cpu = psutil.cpu_percent(interval=0.35)
    return {
        "free_ram_mb": (vm.available / (1024 * 1024)) if vm.available <= vm.total else (vm.total - vm.used) / (1024 * 1024),
        "total_ram_mb": vm.total / (1024 * 1024),
        "cpu_pct": cpu,
    }


def headroom_ok(sample: dict | None = None, *, min_free_ram_mb: float | None = None, max_cpu_pct: float | None = None) -> tuple[bool, str]:
    """Judge a headroom sample against thresholds → (ok, reason)."""
    s = sample if sample is not None else host_headroom()
    floor_mb = min_free_ram_mb if min_free_ram_mb is not None else gate_settings()["min_free_ram_mb"]
    cpu_cap = max_cpu_pct if max_cpu_pct is not None else gate_settings()["max_cpu_pct"]
    if s["free_ram_mb"] < floor_mb:
        return False, f"free RAM {s['free_ram_mb']:.0f}MB < floor {floor_mb:.0f}MB"
    if s["cpu_pct"] > cpu_cap:
        return False, f"CPU {s['cpu_pct']:.0f}% > ceiling {cpu_cap:.0f}%"
    return True, f"headroom ok (RAM {s['free_ram_mb']:.0f}MB free, CPU {s['cpu_pct']:.0f}%)"


def wait_for_boot_headroom(
    *,
    label: str = "phone",
    min_free_ram_mb: float | None = None,
    max_cpu_pct: float | None = None,
    timeout_s: float | None = None,
    log_fn=None,
) -> bool:
    """Block until the host has headroom for one more VM launch.

    Returns True when headroom is available, False on timeout (caller should
    skip that launch — booting into a starved host wedges every phone, which
    is exactly the failure mode the scaling plan forbids).
    """
    if gate_disabled():
        return True

    settings = gate_settings()
    floor_mb = min_free_ram_mb if min_free_ram_mb is not None else settings["min_free_ram_mb"]
    cpu_cap = max_cpu_pct if max_cpu_pct is not None else settings["max_cpu_pct"]
    deadline = time.time() + (timeout_s if timeout_s is not None else settings["timeout_s"])

    last_reason = ""
    while True:
        try:
            ok, reason = headroom_ok(min_free_ram_mb=floor_mb, max_cpu_pct=cpu_cap)
        except Exception as exc:  # noqa: BLE001 — a psutil hiccup must not kill a boot
            logger.warning("boot gate: headroom sample failed (%s) — allowing launch", exc)
            return True
        if ok:
            if last_reason:
                _log(log_fn, f"{label}: host recovered — {reason}")
            return True
        if reason != last_reason:
            _log(log_fn, f"{label}: waiting for host headroom — {reason}")
            last_reason = reason
        if time.time() >= deadline:
            _log(log_fn, f"{label}: headroom wait timed out after {settings['timeout_s']:.0f}s ({reason}) — skipping launch")
            return False
        time.sleep(GATE_POLL_S)


def _log(log_fn, msg: str) -> None:
    logger.info("%s", msg)
    if log_fn is not None:
        try:
            log_fn(msg)
        except Exception:  # noqa: BLE001 — log sinks must never break gating
            pass
