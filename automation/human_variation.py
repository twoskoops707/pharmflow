"""
Per-device human-like variance: same step semantics, stable RNG per (serial, cycle).

Enable via ``CPHARM_HUMAN_VARIATION=1`` (always on for Mantis farm profitability).
"""
from __future__ import annotations

import hashlib
import os
import random
from typing import Optional

# Tune: wait duration multiplier is uniform in [1 - WAIT_SPREAD, 1 + WAIT_SPREAD]
WAIT_SPREAD = 0.08
# Extra tap jitter (px): when step omits jitter, use AUTO_JITTER range; else add up to EXTRA_ON_TOP
AUTO_JITTER_MIN = 2
AUTO_JITTER_MAX = 7
EXTRA_ON_TOP = 4
# Between-step pause (seconds) when human variation is on
STEP_GAP_MIN = 0.08
STEP_GAP_MAX = 0.18
# Same intent when human variation is off (scheduler / non-HV path)
FALLBACK_STEP_GAP_MIN = 0.35
FALLBACK_STEP_GAP_MAX = 0.55
# Pre-tap delay scaling
PRE_WAIT_SPREAD = 0.06
# Cap scaled pre-tap wait (ms) so bad configs cannot stall taps unbounded
PRE_WAIT_MS_CAP = 10000.0
# Multi-phone stagger: scale base delay by ± this fraction (open_url / legacy paths)
STAGGER_JITTER_FRAC = 0.15
# Group phone stagger: ± this fraction around ``stagger_secs`` when ``human_stagger`` (default on)
GROUP_STAGGER_JITTER_FRAC = 0.40
# Between playlist file launches on the same phone (seconds)
SEQUENCE_START_GAP_MIN = 0.8
SEQUENCE_START_GAP_MAX = 3.5
# Between full playlist repeat cycles (seconds)
PLAYLIST_CYCLE_PAUSE_MIN = 2.0
PLAYLIST_CYCLE_PAUSE_MAX = 8.0
# After each scheduled "hit" completes, pause before the next wait loop (seconds)
INTER_SCHEDULED_HIT_MIN = 0.72
INTER_SCHEDULED_HIT_MAX = 1.38
# When all hits for the day are done, idle until next local midnight (bounds only)
POST_DAY_IDLE_MIN_SEC = 60.0
POST_DAY_IDLE_MAX_SEC = 300.0
# Blake2b key so schedule RNG stream never collides with :func:`stable_seed` mixes
_SCHED_RNG_KEY = b"cpharm.sched.firetimes.v1"


def _digest_blake2b_or_sha256(data: bytes, *, digest_size: int = 8, key: bytes | None = None) -> bytes:
    try:
        if key is not None:
            return hashlib.blake2b(data, digest_size=digest_size, key=key).digest()
        return hashlib.blake2b(data, digest_size=digest_size).digest()
    except AttributeError:
        if key is not None:
            mix = hashlib.sha256(key + b"\x00" + data).digest()
        else:
            mix = hashlib.sha256(data).digest()
        return mix[:digest_size]


def enabled() -> bool:
    raw = os.environ.get("CPHARM_HUMAN_VARIATION", "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def stable_seed(serial: str, cycle: int) -> int:
    """Deterministic 64-bit seed from device id + run cycle (day/index/iteration)."""
    h = _digest_blake2b_or_sha256(serial.encode("utf-8"), digest_size=8)
    base = int.from_bytes(h, "little")
    mixed = base ^ (cycle * 0x9E3779B97F4A7C15) ^ (len(serial) << 48)
    return mixed & 0xFFFFFFFFFFFFFFFF


def rng_for_run(serial: str, cycle: int) -> random.Random:
    return random.Random(stable_seed(serial, cycle))


def schedule_rng(
    serial: str,
    local_day_index: int,
    hits_per_day: int,
    geo_mix: str = "",
) -> random.Random:
    """
    Stable RNG for generating one day's fire offsets.

    Same ``serial``, ``local_day_index`` (e.g. ``int(local_midnight_ts // 86400)``),
    ``hits_per_day``, and optional ``geo_mix`` (e.g. Tor exit ISO country) produce
    the same sequence across restarts. A **new calendar day** or a changed quota /
    exit geography yields a different schedule.
    """
    if geo_mix:
        payload = f"{serial}\x00{local_day_index}\x00{hits_per_day}\x00{geo_mix}".encode("utf-8")
    else:
        payload = f"{serial}\x00{local_day_index}\x00{hits_per_day}".encode("utf-8")
    h = _digest_blake2b_or_sha256(payload, digest_size=8, key=_SCHED_RNG_KEY)
    seed = int.from_bytes(h, "little") & 0xFFFFFFFFFFFFFFFF
    return random.Random(seed)


def scaled_wait_seconds(
    base: float,
    rng: random.Random,
    *,
    checkpoint: str | None = None,
) -> float:
    """Scale automation ``wait`` duration by uniform(1−WAIT_SPREAD, 1+WAIT_SPREAD).

  ``checkpoint`` ``timer_complete`` is never scaled — the wait must cover the full
  UI timer plus completion animation and session-notes modal buffer.
    """
    if str(checkpoint or "").strip().lower() == "timer_complete":
        return max(0.0, float(base))
    lo, hi = 1.0 - WAIT_SPREAD, 1.0 + WAIT_SPREAD
    return max(0.0, base * rng.uniform(lo, hi))


def scaled_pre_wait_ms(base_ms: float, rng: random.Random) -> float:
    """Scale pre-tap delay like ``scaled_wait_seconds``, capped at ``PRE_WAIT_MS_CAP``."""
    if base_ms <= 0:
        return 0.0
    lo, hi = 1.0 - PRE_WAIT_SPREAD, 1.0 + PRE_WAIT_SPREAD
    return min(PRE_WAIT_MS_CAP, base_ms * rng.uniform(lo, hi))


def effective_tap_jitter(step_jitter: int, rng: Optional[random.Random]) -> int:
    """Clamp step jitter to [0,120]; if human mode and rng set, add bounded variance."""
    j = max(0, min(120, step_jitter))
    if rng is None or not enabled():
        return j
    if j == 0:
        return rng.randint(AUTO_JITTER_MIN, AUTO_JITTER_MAX)
    return min(120, j + rng.randint(0, EXTRA_ON_TOP))


def step_gap_seconds(rng: random.Random) -> float:
    """Random pause (seconds) after each automation step when human variation is on."""
    return rng.uniform(STEP_GAP_MIN, STEP_GAP_MAX)


def inter_scheduled_hit_seconds(rng: random.Random) -> float:
    """Bounded delay after a scheduled run finishes before the worker goes back to sleep."""
    return rng.uniform(INTER_SCHEDULED_HIT_MIN, INTER_SCHEDULED_HIT_MAX)


def stagger_seconds(base: float, rng: Optional[random.Random]) -> float:
    """
    Delay between devices when staggering launches/actions.

    With human variation enabled, scales ``base`` by uniform(1−j, 1+j) where
    j = :data:`STAGGER_JITTER_FRAC` so multi-phone traffic is less perfectly aligned.
    """
    if base <= 0:
        return 0.0
    b = float(base)
    if rng is None or not enabled():
        return b
    lo, hi = 1.0 - STAGGER_JITTER_FRAC, 1.0 + STAGGER_JITTER_FRAC
    return max(0.0, b * rng.uniform(lo, hi))


def sequence_start_gap_seconds(rng: random.Random) -> float:
    """Random pause before starting the next playlist sequence on the same phone."""
    return rng.uniform(SEQUENCE_START_GAP_MIN, SEQUENCE_START_GAP_MAX)


def playlist_cycle_pause_seconds(rng: random.Random) -> float:
    """Random pause before the next full playlist pass (group repeat iteration)."""
    return rng.uniform(PLAYLIST_CYCLE_PAUSE_MIN, PLAYLIST_CYCLE_PAUSE_MAX)


def group_stagger_seconds(group: dict, rng: random.Random) -> float:
    """
    Delay before starting the next phone in a group run.

    ``groups_config`` options (first match wins):

    - ``stagger_min`` + ``stagger_max``: uniform random in [min, max] seconds.
    - ``stagger_secs`` with ``human_stagger`` true (default): base × uniform(0.6, 1.4).
    - ``stagger_secs`` with ``human_stagger`` false: fixed base (legacy).
    """
    smin = group.get("stagger_min")
    smax = group.get("stagger_max")
    if smin is not None and smax is not None:
        try:
            lo, hi = float(smin), float(smax)
            if lo > hi:
                lo, hi = hi, lo
            if hi > 0:
                return rng.uniform(max(0.0, lo), hi)
        except (TypeError, ValueError):
            pass
    try:
        base = float(group.get("stagger_secs", 0))
    except (TypeError, ValueError):
        base = 0.0
    if base <= 0:
        return 0.0
    human = group.get("human_stagger", True)
    if human is False or str(human).strip().lower() in ("0", "false", "no", "off"):
        return base
    j = GROUP_STAGGER_JITTER_FRAC
    return max(0.0, base * rng.uniform(1.0 - j, 1.0 + j))
