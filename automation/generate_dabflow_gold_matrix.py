#!/usr/bin/env python3
"""
Generate DabFlow gold automation JSON at baseline 900×1600, remapped per MuMu resolution.

Output goes to the **local** sequences folder only (``CPHARM_SEQUENCES_DIR`` or
``~/CPharm/sequences``) — never the git repo. Layout: ``{WxH}/{ad|no-ad}/*.json``.

Every combo includes: timer → tab excursion (Glass → select → exit → home) →
stats scroll → (ad path) scroll-to-bottom → ad tap → ≥30s dwell → identity tail.

Ad vs no-ad (combo matrix):
  - **no-ad:** full combo timer wait → skip popup → visit 1–3 tabs (human scroll each).
  - **ad:** same timer → skip → visit 1–3 tabs → ad tap on one tab → scroll-bottom OR
    ~30s dwell on ad → reopen getdabflow.app or close via identity tail.
  - No back-to-back duplicate step types; consecutive waits are merged into one.

Humanization (within ``sequence_normalize`` / dashboard caps):
  - Gaussian-ish waits clipped to [floor, 300]s
  - tap ``jitter`` (px), ``pre_wait_ms``, ``retries`` on taps
  - Segmented scrolls with pauses and occasional upward nudges
  - Tab-switch double micro-waits, think delays after timer reset

Schema ceilings enforced here (cannot exceed without changing CPharm):
  - ``wait.seconds`` ≤ 300
  - ``tap.jitter`` ≤ 120
  - ``tap.pre_wait_ms`` ≤ 10000
  - ``swipe.ms`` ≤ 5000
  - ``open_url.post_wait_secs`` ≤ 120

Identity tail: ``close_app`` → ``wait`` → ``rotate_identity`` → ``wait`` → ``full_reset``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_gold_dataset import remap_steps  # noqa: E402
from dabflow_layout import (  # noqa: E402
    BW,
    BH,
    AGE_YES,
    GLASS_ART_SELECT,
    HEAT_POS,
    HEAT_POS_MUMU,
    MAT_POS,
    MAT_POS_MUMU,
    AGE_YES_MUMU,
    AGE_GATE_PRE_WAIT_MAX_MS,
    SCROLL_TO_START_DAB_SWIPES,
    SESSION_NOTES_SKIP_MUMU,
    SESSION_NOTES_SKIP_ONE,
    STATS_SCROLL_BOTTOM_SWIPES,
    TAB_GLASS,
    TAB_SETTINGS,
    TAB_STATS,
    scroll_bottom_swipes,
    START_DAB_AFTER_SCROLL,
    STATS_AD_SLOT,
    HOME_AD_SLOT,
    TIMER_COOLDOWN_VIDEO_AD,
    TIMER_AD_SLOT,
    TIMER_AD_SLOT_LOWER,
    GLASS_AD_SLOT,
    SETTINGS_AD_SLOT,
    concentrate_region,
    concentrate_region_mumu,
    jitter_point,
    nav_region,
)
from dabflow_timer import (  # noqa: E402
    COMPLETION_ANIMATION_SEC,
    CONCENTRATES,
    HEATERS,
    MATERIALS,
    MODAL_RENDER_BUFFER_SEC,
    calculate_timings,
    timer_wait_seconds,
    timer_wait_range,
)
from sequence_normalize import merge_adjacent_wait_step, normalize_automation_steps  # noqa: E402
from sequences_paths import resolve_sequences_dir  # noqa: E402

SCHEMA_WAIT_MAX = 300.0
SCHEMA_JITTER_MAX = 120
SCHEMA_PRE_WAIT_MAX = 10000.0
SCHEMA_SWIPE_MS_MAX = 5000
SCHEMA_OPEN_URL_WAIT_MAX = 120.0
DABFLOW_OPEN_URL_POST_WAIT_FLOOR_SEC = 1.0
# human_pace_v8: pre-site ≤~2s to age gate (real users tap yes in ~2–3s)
PRE_SITE_CLEAR_WAIT_MAX_SEC = 0.35
PRE_SITE_OPEN_URL_POST_WAIT_MIN_SEC = 0.75
PRE_SITE_OPEN_URL_POST_WAIT_MAX_SEC = 1.25
PRE_SITE_SETTLE_WAIT_MAX_SEC = 0.22
POST_BROWSER_WAIT_MAX_SEC = 0.5
# on_site funnel pacing (seconds unless noted) — v7 quick age→3 picks→start dab
MEANINGFUL_TAP_GAP_FLOOR_SEC = 0.10
SELECTION_GAP_MEAN_SEC = 0.15
SELECTION_GAP_SIGMA_SEC = 0.03
POST_AGE_WAIT_MEAN_SEC = 0.20
POST_AGE_WAIT_FLOOR_SEC = 0.15
PRE_START_DAB_MEAN_SEC = 0.18
PRE_START_DAB_FLOOR_SEC = 0.15
TAB_SWITCH_GAP_FLOOR_SEC = 0.35
TAB_TOUR_POST_TAB_WAIT_SEC = 0.25
TAB_TOUR_SWIPE_WAIT_SEC = 0.25
SESSION_NOTES_DISMISS_WAIT_SEC = 0.25
AGE_PRE_WAIT_FLOOR_MS = 100.0
INTERACTIVE_PRE_WAIT_FLOOR_MS = 100.0
INTERACTIVE_PRE_WAIT_MEAN_MS = 150.0
TAP_JITTER_FLOOR_PX = 15
TAP_JITTER_CEIL_PX = 30
AD_MIN_DWELL_SEC = 30.0
AD_MAX_DWELL_SEC = 45.0
AD_PRE_TAP_HESITATION_FLOOR_SEC = 1.0

RESOLUTIONS = ((540, 960), (720, 1280), (900, 1600), (1080, 1920))


def option_hash_blob() -> str:
    h = hashlib.sha256()
    for name, blob in (
        ("materials", MATERIALS),
        ("concentrates", CONCENTRATES),
        ("heaters", HEATERS),
    ):
        h.update(name.encode())
        h.update(json.dumps(blob).encode())
    return h.hexdigest()


def rng_for(combo_id: str, flow: str, *, human_bucket: str) -> random.Random:
    seed = int(
        hashlib.sha256(f"{combo_id}|{flow}|{human_bucket}|dabflow-gold-v8".encode()).hexdigest()[:16],
        16,
    )
    return random.Random(seed)


def human_bucket(combo_id: str, flow: str, resolution: str) -> str:
    """Stable per-file snowflake id (combo × flow × resolution)."""
    h = int(
        hashlib.sha256(f"{combo_id}|{flow}|{resolution}|dabflow-snowflake-v1".encode()).hexdigest(),
        16,
    )
    return f"{h % 997:03d}"


def fast_wait(rng: random.Random, *, max_sec: float, mean: float | None = None) -> dict[str, Any]:
    """Short bounded wait for pre_site_fast / post_browser_fast (no Gaussian padding)."""
    cap = min(SCHEMA_WAIT_MAX, max(0.05, float(max_sec)))
    if mean is None:
        secs = cap * rng.uniform(0.55, 1.0)
    else:
        secs = min(cap, max(0.05, rng.uniform(mean * 0.85, cap)))
    return {"type": "wait", "seconds": round(secs, 3), "phase": "pre_site_fast"}


def post_browser_wait(rng: random.Random) -> dict[str, Any]:
    cap = POST_BROWSER_WAIT_MAX_SEC
    secs = min(cap, max(0.05, rng.uniform(0.12, cap)))
    return {"type": "wait", "seconds": round(secs, 3), "phase": "post_browser_fast"}


def human_wait(rng: random.Random, mean: float, sigma: float, floor: float) -> dict[str, Any]:
    v = rng.gauss(mean, sigma)
    v = max(floor, min(SCHEMA_WAIT_MAX, v))
    return {"type": "wait", "seconds": round(v, 3)}


def _wait_seconds(step: dict[str, Any]) -> float:
    try:
        return float(step.get("seconds", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _append_step(steps: list[dict[str, Any]], step: dict[str, Any]) -> None:
    """Append one step; merge into previous wait when both are ``wait``."""
    if steps and isinstance(step, dict) and isinstance(steps[-1], dict):
        if merge_adjacent_wait_step(steps[-1], step, max_seconds=SCHEMA_WAIT_MAX):
            return
    steps.append(step)


def _extend_steps(steps: list[dict[str, Any]], chunk: list[dict[str, Any]]) -> None:
    for step in chunk:
        _append_step(steps, step)


def _append_timer_complete_wait(
    steps: list[dict[str, Any]],
    material: str,
    concentrate: str,
    heater: str,
) -> float:
    """One full combo timer wait after start_dab — merges with prior micro-wait if present."""
    timer_wait = round(float(timer_wait_seconds(material, concentrate, heater)), 1)
    _append_step(
        steps,
        {
            "type": "wait",
            "seconds": timer_wait,
            "checkpoint": "timer_complete",
        },
    )
    return timer_wait


def meaningful_tap_gap(rng: random.Random) -> dict[str, Any]:
    """Pause between funnel taps (material / concentrate / heater / nav)."""
    return human_wait(
        rng,
        rng.gauss(SELECTION_GAP_MEAN_SEC, SELECTION_GAP_SIGMA_SEC),
        0.03,
        MEANINGFUL_TAP_GAP_FLOOR_SEC,
    )


def tab_switch_gap(rng: random.Random) -> list[dict[str, Any]]:
    """Single hesitation wait before bottom-nav tap (no back-to-back waits)."""
    mean = rng.gauss(0.50, 0.08)
    if rng.random() < 0.25:
        mean += rng.uniform(0.05, 0.12)
    return [human_wait(rng, mean, 0.10, TAB_SWITCH_GAP_FLOOR_SEC)]


def age_verification_tap(rng: random.Random) -> dict[str, Any]:
    """First interactive step after ``open_url`` — tap Yes immediately (MuMu coords)."""
    cx, cy = AGE_YES_MUMU.cx, AGE_YES_MUMU.cy
    step = {
        "type": "tap",
        "x": cx,
        "y": cy,
        "base_w": BW,
        "base_h": BH,
        "retries": 5,
        "jitter": int(min(5, max(2, round(rng.gauss(3.0, 0.8))))),
        "pre_wait_ms": float(
            min(
                AGE_GATE_PRE_WAIT_MAX_MS,
                max(AGE_PRE_WAIT_FLOOR_MS, rng.gauss(70.0, 20.0)),
            )
        ),
        "age_verification": True,
        "checkpoint": "age_verification",
        "phase": "on_site_human",
    }
    return step


def tap_human_region(
    region,
    rng: random.Random,
    *,
    critical: bool,
    retries: int | None = None,
) -> dict[str, Any]:
    x, y = jitter_point(region, rng)
    jitter = int(
        min(
            SCHEMA_JITTER_MAX,
            max(
                TAP_JITTER_FLOOR_PX,
                min(TAP_JITTER_CEIL_PX, round(rng.gauss(22.0 if critical else 21.0, 4.0))),
            ),
        )
    )
    pre = float(
        min(
            SCHEMA_PRE_WAIT_MAX,
            max(
                INTERACTIVE_PRE_WAIT_FLOOR_MS,
                min(400.0, rng.gauss(INTERACTIVE_PRE_WAIT_MEAN_MS if critical else 140.0, 30.0)),
            ),
        )
    )
    r = retries if retries is not None else rng.choice([2, 2, 2, 3, 3])
    return {
        "type": "tap",
        "x": x,
        "y": y,
        "base_w": BW,
        "base_h": BH,
        "retries": r,
        "jitter": jitter,
        "pre_wait_ms": pre,
    }


def think_after_reset(rng: random.Random) -> list[dict[str, Any]]:
    return [human_wait(rng, rng.gauss(0.735, 0.32), 0.15, 0.2)]


def timer_session_wait_seconds(
    material: str,
    concentrate: str,
    heater: str,
    rng: random.Random,  # noqa: ARG001 — kept for call-site compatibility
) -> dict[str, Any]:
    """Wait step: exact per-combo ``timer_wait_seconds()`` (no jitter; never shortened)."""
    secs = round(float(timer_wait_seconds(material, concentrate, heater)), 1)
    return {
        "type": "wait",
        "seconds": secs,
        "checkpoint": "timer_complete",
    }


def _open_url_post_wait_secs(url: str, rng: random.Random) -> float:
    if "getdabflow.app" in (url or "").lower():
        return round(
            min(
                PRE_SITE_OPEN_URL_POST_WAIT_MAX_SEC,
                max(
                    PRE_SITE_OPEN_URL_POST_WAIT_MIN_SEC,
                    rng.uniform(PRE_SITE_OPEN_URL_POST_WAIT_MIN_SEC, PRE_SITE_OPEN_URL_POST_WAIT_MAX_SEC),
                ),
            ),
            3,
        )
    return min(SCHEMA_OPEN_URL_WAIT_MAX, max(3.0, rng.uniform(3.0, 4.0)))


def scroll_home_to_start_dab(rng: random.Random) -> list[dict[str, Any]]:
    """Scroll #home-screen down until #start-dab-btn is on-screen (MuMu webview fold)."""
    steps: list[dict[str, Any]] = []
    for i, sw in enumerate(SCROLL_TO_START_DAB_SWIPES):
        _append_step(
            steps,
            {
                "type": "swipe",
                "x1": sw["x1"],
                "y1": sw["y1"],
                "x2": sw["x2"],
                "y2": sw["y2"],
                "ms": sw["ms"],
                "base_w": BW,
                "base_h": BH,
                **({"checkpoint": "scroll_to_start_dab"} if i == len(SCROLL_TO_START_DAB_SWIPES) - 1 else {}),
            },
        )
        _append_step(
            steps,
            human_wait(
                rng,
                rng.gauss(SELECTION_GAP_MEAN_SEC, SELECTION_GAP_SIGMA_SEC),
                0.03,
                MEANINGFUL_TAP_GAP_FLOOR_SEC,
            ),
        )
    return steps


def scroll_to_bottom(
    rng: random.Random,
    *,
    segments: int | None = None,
) -> list[dict[str, Any]]:
    """Repeated downward swipes until page bottom (900×1600 baseline), human pacing."""
    steps: list[dict[str, Any]] = []
    n = segments if segments is not None else rng.randint(7, 11)
    y_cursor = rng.randint(1180, 1380)
    for _ in range(n):
        x1 = 450 + rng.randint(-48, 48)
        dy = rng.randint(200, 360)
        y1 = y_cursor
        y2 = max(280, y1 - dy)
        ms = int(min(SCHEMA_SWIPE_MS_MAX, max(320, rng.gauss(820.0, 220.0))))
        _append_step(
            steps,
            {
                "type": "swipe",
                "x1": x1,
                "y1": y1,
                "x2": x1 + rng.randint(-18, 18),
                "y2": y2,
                "ms": ms,
                "base_w": BW,
                "base_h": BH,
            },
        )
        _append_step(steps, human_wait(rng, rng.gauss(0.29, 0.08), 0.12, 0.2))
        y_cursor = max(320, y2 + rng.randint(-20, 40))
    _append_step(steps, human_wait(rng, rng.gauss(0.595, 0.15), 0.25, 0.35))
    return steps


def segmented_scroll_down(
    rng: random.Random,
    *,
    segments: int | None = None,
    reading_pause_prob: float = 0.32,
) -> list[dict[str, Any]]:
    """Many short swipes + pauses + occasional upward nudge."""
    out: list[dict[str, Any]] = []
    n = segments if segments is not None else rng.randint(11, 18)
    y_low = rng.randint(1320, 1485)
    for i in range(n):
        x1 = 430 + rng.randint(-52, 52)
        dy = rng.randint(140, 320)
        y1 = y_low
        y2 = max(380, y_low - dy)
        ms = int(min(SCHEMA_SWIPE_MS_MAX, max(260, rng.gauss(780.0, 240.0))))
        out.append(
            {
                "type": "swipe",
                "x1": x1,
                "y1": y1,
                "x2": x1 + rng.randint(-22, 22),
                "y2": y2,
                "ms": ms,
                "base_w": BW,
                "base_h": BH,
            }
        )
        gap_mu = (0.266 + rng.random() * 0.385)
        if rng.random() < reading_pause_prob and i > 2:
            gap_mu += rng.gauss(1.96, 0.77)
        out.append(human_wait(rng, gap_mu, gap_mu * 0.35, 0.12))
        if rng.random() < 0.14:
            out.append(
                {
                    "type": "swipe",
                    "x1": x1 + rng.randint(-30, 30),
                    "y1": y2 + 80,
                    "x2": x1 + rng.randint(-30, 30),
                    "y2": min(1420, y2 + rng.randint(90, 180)),
                    "ms": int(min(SCHEMA_SWIPE_MS_MAX, rng.gauss(420.0, 130.0))),
                    "base_w": BW,
                    "base_h": BH,
                }
            )
            out.append(human_wait(rng, rng.gauss(0.315, 0.11), 0.1, 0.15))
        y_low = min(1485, y2 + rng.randint(-40, 60))
    return out


def sample_ad_dwell_seconds(rng: random.Random) -> float:
    """Human Gaussian dwell on ad landing, clipped to [30, 45]s."""
    v = rng.gauss(37.5, 4.5)
    return min(SCHEMA_WAIT_MAX, min(AD_MAX_DWELL_SEC, max(AD_MIN_DWELL_SEC, v)))


def ad_slot_tap(rng: random.Random) -> dict[str, Any]:
    """Tap STATS_AD_SLOT with hesitation pre_wait and selection markers."""
    step = tap_human_region(STATS_AD_SLOT, rng, critical=False, retries=3)
    step["ad_selected"] = True
    step["checkpoint"] = "ad_selected"
    step["pre_wait_ms"] = float(
        min(
            SCHEMA_PRE_WAIT_MAX,
            max(INTERACTIVE_PRE_WAIT_FLOOR_MS * 2, rng.gauss(1200.0, 280.0)),
        )
    )
    return step


def ad_landing_micro_scroll(rng: random.Random) -> dict[str, Any]:
    """Small scroll on ad landing page during read dwell."""
    x1 = 450 + rng.randint(-48, 48)
    y1 = rng.randint(820, 1040)
    y2 = max(520, y1 - rng.randint(60, 160))
    return {
        "type": "swipe",
        "x1": x1,
        "y1": y1,
        "x2": x1 + rng.randint(-18, 18),
        "y2": y2,
        "ms": int(min(SCHEMA_SWIPE_MS_MAX, max(280, rng.gauss(520.0, 140.0)))),
        "base_w": BW,
        "base_h": BH,
    }


def _normalize_ad_dwell_waits(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Clamp summed ad-read waits to [AD_MIN_DWELL_SEC, AD_MAX_DWELL_SEC]."""
    wait_idxs = [i for i, s in enumerate(steps) if isinstance(s, dict) and s.get("type") == "wait"]
    if not wait_idxs:
        return [
            {
                "type": "wait",
                "seconds": round(AD_MIN_DWELL_SEC, 3),
                "checkpoint": "ad_dwell",
                "ad_read": True,
            }
        ]
    total = sum(float(steps[i].get("seconds", 0)) for i in wait_idxs)
    if total < AD_MIN_DWELL_SEC:
        deficit = AD_MIN_DWELL_SEC - total
        last = wait_idxs[-1]
        patched = dict(steps[last])
        patched["seconds"] = round(float(patched.get("seconds", 0)) + deficit, 3)
        patched.setdefault("checkpoint", "ad_dwell")
        patched["ad_read"] = True
        steps[last] = patched
        total = AD_MIN_DWELL_SEC
    if total > AD_MAX_DWELL_SEC:
        excess = total - AD_MAX_DWELL_SEC
        last = wait_idxs[-1]
        patched = dict(steps[last])
        patched["seconds"] = round(max(0.5, float(patched.get("seconds", 0)) - excess), 3)
        steps[last] = patched
    return steps


def ad_read_dwell_pack(rng: random.Random) -> list[dict[str, Any]]:
    """≥30s ad read dwell with optional micro-scrolls (no consecutive waits)."""
    total = sample_ad_dwell_seconds(rng)
    steps: list[dict[str, Any]] = []
    if rng.random() < 0.6:
        first = round(total * rng.uniform(0.42, 0.62), 3)
        mid = round(total * rng.uniform(0.18, 0.28), 3)
        extra_mid = 0.0
        steps.append({"type": "wait", "seconds": first, "checkpoint": "ad_read"})
        steps.append(ad_landing_micro_scroll(rng))
        steps.append(human_wait(rng, mid, mid * 0.25, 0.45))
        if rng.random() < 0.45:
            steps.append(ad_landing_micro_scroll(rng))
            extra = human_wait(rng, rng.gauss(0.8, 0.25), 0.2, 0.35)
            extra_mid = float(extra["seconds"])
            steps.append(extra)
        last = round(max(0.5, total - first - mid - extra_mid), 3)
        if last < 2.0:
            prev = dict(steps[-1])
            prev["seconds"] = round(float(prev.get("seconds", 0)) + last, 3)
            prev["checkpoint"] = "ad_dwell"
            prev["ad_read"] = True
            steps[-1] = prev
        else:
            steps.append(ad_landing_micro_scroll(rng))
            steps.append(
                {"type": "wait", "seconds": last, "checkpoint": "ad_dwell", "ad_read": True}
            )
    else:
        dwell = round(total, 3)
        steps.append({"type": "wait", "seconds": dwell, "checkpoint": "ad_dwell", "ad_read": True})
    return _normalize_ad_dwell_waits(steps)


def ad_post_tap_scroll_pack(rng: random.Random) -> list[dict[str, Any]]:
    """Light scroll while on ad landing (after mandatory ≥30s dwell)."""
    steps = segmented_scroll_down(rng, segments=rng.randint(4, 7), reading_pause_prob=0.28)
    _append_step(steps, human_wait(rng, rng.gauss(1.75, 0.56), 0.85, 1.25))
    return steps


def tab_excursion_exit_repeat(rng: random.Random, material: str) -> list[dict[str, Any]]:
    """
    Mandatory: Glass tab → select art card → BACK exit → Home (go again).
    Coords at 900×1600 — see ``dabflow_layout`` / ``operator_sequences_900x1600.md``.
    """
    steps: list[dict[str, Any]] = []
    _extend_steps(steps, tab_switch_gap(rng))
    _append_step(steps, tap_human_region(nav_region("glass"), rng, critical=False))
    _append_step(steps, human_wait(rng, rng.gauss(1.05, 0.28), 0.32, 0.7))
    _append_step(steps, tap_human_region(GLASS_ART_SELECT, rng, critical=False))
    _append_step(steps, human_wait(rng, rng.gauss(0.84, 0.25), 0.28, 0.56))
    _append_step(steps, {"type": "keyevent", "key": "4"})
    _append_step(steps, human_wait(rng, rng.gauss(0.98, 0.27), 0.32, 0.7))
    _extend_steps(steps, tab_switch_gap(rng))
    _append_step(steps, tap_human_region(nav_region("home"), rng, critical=False))
    _append_step(steps, human_wait(rng, rng.gauss(1.05, 0.29), 0.35, 0.7))
    if rng.random() < 0.45:
        _append_step(steps, tap_human_region(MAT_POS[material], rng, critical=False))
        _append_step(steps, meaningful_tap_gap(rng))
    return steps


def ad_interaction_block(rng: random.Random) -> list[dict[str, Any]]:
    """Scroll to bottom → hesitate → ad tap → ≥30s read dwell → post-ad scroll → BACK."""
    steps: list[dict[str, Any]] = []
    _extend_steps(steps, scroll_to_bottom(rng))
    _append_step(steps, human_wait(rng, rng.gauss(1.47, 0.4), 0.35, AD_PRE_TAP_HESITATION_FLOOR_SEC))
    _append_step(steps, ad_slot_tap(rng))
    _extend_steps(steps, ad_read_dwell_pack(rng))
    _extend_steps(steps, ad_post_tap_scroll_pack(rng))
    _append_step(steps, {"type": "keyevent", "key": "4"})
    _append_step(steps, human_wait(rng, rng.gauss(1.54, 0.56), 0.6, 0.85))
    return steps


TAB_MATRIX_SPECS: tuple[tuple[str, Any, str, Any, str], ...] = (
    ("glass", TAB_GLASS, "tab_glass_scrolled_bottom", GLASS_AD_SLOT, "ad_glass"),
    ("stats", TAB_STATS, "tab_scrolled_bottom", STATS_AD_SLOT, "ad_stats"),
    ("settings", TAB_SETTINGS, "tab_settings_scrolled_bottom", SETTINGS_AD_SLOT, "ad_settings"),
)


def _ad_bracketed_scroll_steps(
    rng: random.Random,
    swipe_specs: list[dict[str, Any]],
    *,
    total_sec: float | None = None,
    last_checkpoint: str | None = None,
) -> list[dict[str, Any]]:
    """
    Ad-only scroll shape: one wait → swipe(s) → one wait.

    ``total_sec`` is the combined pre+post pause budget (varies per sequence).
    Swipes sit between the waits with no interleaved waits.
    """
    steps: list[dict[str, Any]] = []
    budget = total_sec if total_sec is not None else round(rng.uniform(2.4, 6.4), 3)
    pre = round(budget * rng.uniform(0.38, 0.52), 3)
    post = round(max(0.28, budget - pre), 3)
    _append_step(steps, {"type": "wait", "seconds": pre})
    for i, sw in enumerate(swipe_specs):
        swipe = dict(sw)
        if i == len(swipe_specs) - 1 and last_checkpoint:
            swipe["checkpoint"] = last_checkpoint
        _append_step(steps, swipe)
    _append_step(steps, {"type": "wait", "seconds": post})
    return steps


def _ad_landing_scroll_swipes(rng: random.Random, *, segments: int | None = None) -> list[dict[str, Any]]:
    """Build downward swipes for ad-landing bracketed scroll (no waits)."""
    n = segments if segments is not None else rng.randint(3, 6)
    specs: list[dict[str, Any]] = []
    y_cursor = rng.randint(1180, 1380)
    for _ in range(n):
        x1 = 450 + rng.randint(-48, 48)
        dy = rng.randint(200, 360)
        y1 = y_cursor
        y2 = max(280, y1 - dy)
        ms = int(min(SCHEMA_SWIPE_MS_MAX, max(320, rng.gauss(820.0, 220.0))))
        specs.append(
            {
                "type": "swipe",
                "x1": x1,
                "y1": y1,
                "x2": x1 + rng.randint(-18, 18),
                "y2": y2,
                "ms": ms,
                "base_w": BW,
                "base_h": BH,
            }
        )
        y_cursor = max(320, y2 + rng.randint(-20, 40))
    return specs


def _pick_tab_visits(rng: random.Random) -> list[tuple[str, Any, str, Any, str]]:
    """Some sequences visit one tab, others two or three (shuffled order)."""
    pool = list(TAB_MATRIX_SPECS)
    rng.shuffle(pool)
    count = rng.choice([1, 1, 2, 2, 3])
    return pool[:count]


def _human_scroll_tab(
    rng: random.Random,
    tab_key: str,
    tab_reg,
    bottom_cp: str,
    *,
    for_ad: bool = False,
) -> list[dict[str, Any]]:
    """Bottom-nav tap + scroll to tab bottom. Ad path: wait→swipes→wait; no-ad: swipe/wait alternation."""
    steps: list[dict[str, Any]] = []
    _extend_steps(steps, tab_switch_gap(rng))
    tab_tap = tap_human_region(tab_reg, rng, critical=False, retries=rng.choice([2, 3, 3, 4]))
    tab_tap["checkpoint"] = f"tab_{tab_key}"
    tab_tap["bottom_nav"] = True
    _append_step(steps, tab_tap)
    _append_step(steps, human_wait(rng, rng.gauss(0.55, 0.12), 0.08, 0.22))
    swipes = scroll_bottom_swipes(tab_key)
    swipe_specs: list[dict[str, Any]] = []
    for sw in swipes:
        ms = int(min(SCHEMA_SWIPE_MS_MAX, max(280, sw["ms"] + rng.randint(-120, 180))))
        swipe_specs.append(
            {
                "type": "swipe",
                "x1": sw["x1"] + rng.randint(-8, 8),
                "y1": sw["y1"] + rng.randint(-10, 10),
                "x2": sw["x2"] + rng.randint(-8, 8),
                "y2": sw["y2"] + rng.randint(-10, 10),
                "ms": ms,
                "base_w": BW,
                "base_h": BH,
            }
        )
    if for_ad:
        _extend_steps(
            steps,
            _ad_bracketed_scroll_steps(
                rng,
                swipe_specs,
                total_sec=round(rng.uniform(2.8, 5.6), 3),
                last_checkpoint=bottom_cp,
            ),
        )
    else:
        for i, swipe in enumerate(swipe_specs):
            if i == len(swipe_specs) - 1:
                swipe["checkpoint"] = bottom_cp
            _append_step(steps, swipe)
            if i < len(swipe_specs) - 1:
                _append_step(
                    steps,
                    human_wait(rng, rng.gauss(0.28, 0.07), 0.05, 0.14),
                )
    return steps


def _ad_landing_engagement(rng: random.Random) -> list[dict[str, Any]]:
    """On ad landing: ~30s wait OR bracketed scroll (wait→swipes→wait) then ~30s dwell."""
    steps: list[dict[str, Any]] = []
    dwell = round(sample_ad_dwell_seconds(rng), 3)
    if rng.random() < 0.5:
        _append_step(
            steps,
            {"type": "wait", "seconds": dwell, "checkpoint": "ad_dwell", "ad_read": True},
        )
    else:
        landing_swipes = _ad_landing_scroll_swipes(rng, segments=rng.randint(3, 6))
        _extend_steps(
            steps,
            _ad_bracketed_scroll_steps(
                rng,
                landing_swipes,
                total_sec=round(rng.uniform(3.2, 7.0), 3),
            ),
        )
        _append_step(
            steps,
            {"type": "wait", "seconds": dwell, "checkpoint": "ad_dwell", "ad_read": True},
        )
    return steps


def _return_to_dabflow_or_close(rng: random.Random, url: str) -> list[dict[str, Any]]:
    """Half the sequences reopen getdabflow.app; others rely on identity-tail close_app."""
    steps: list[dict[str, Any]] = []
    if rng.random() < 0.5:
        _append_step(steps, {"type": "keyevent", "key": "4"})
        post = round(rng.uniform(1.3, 2.4), 3)
        _append_step(
            steps,
            {
                "type": "open_url",
                "url": url,
                "post_wait_secs": post,
                "checkpoint": "returned_to_dabflow",
            },
        )
        _append_step(steps, human_wait(rng, rng.gauss(0.62, 0.14), 0.1, 0.32))
    return steps


def post_timer_no_ad_tab_tour(rng: random.Random) -> list[dict[str, Any]]:
    """After timer: visit 1–3 tabs with human scroll only."""
    steps: list[dict[str, Any]] = []
    for tab_key, tab_reg, bottom_cp, _, _ in _pick_tab_visits(rng):
        _extend_steps(steps, _human_scroll_tab(rng, tab_key, tab_reg, bottom_cp))
    return steps


def _pick_tab_visits_for_ad_tab(
    rng: random.Random,
    ad_tab_key: str,
) -> tuple[list[tuple[str, Any, str, Any, str]], int]:
    """Visit 1–3 tabs; ad hardcode/tap always lands on ``ad_tab_key``."""
    pool = list(TAB_MATRIX_SPECS)
    rng.shuffle(pool)
    count = rng.choice([1, 1, 2, 2, 3])
    visits = pool[:count]
    ad_spec = next(spec for spec in TAB_MATRIX_SPECS if spec[0] == ad_tab_key)
    if not any(v[0] == ad_tab_key for v in visits):
        if len(visits) >= 3:
            visits[-1] = ad_spec
        else:
            visits.append(ad_spec)
    ad_on = next(i for i, v in enumerate(visits) if v[0] == ad_tab_key)
    return visits, ad_on


def post_timer_ad_hardcode_excursion(
    rng: random.Random,
    *,
    ad_url: str,
    ad_checkpoint: str,
    ad_tab_key: str,
    url: str = "https://getdabflow.app",
) -> list[dict[str, Any]]:
    """
    After full timer + popup skip: tab tour → ``open_url`` to hard-coded Mantis ad landing
    (no on-site ad tap) → dwell/scroll on landing → return to getdabflow or identity tail.
    """
    visits, ad_on = _pick_tab_visits_for_ad_tab(rng, ad_tab_key)
    steps: list[dict[str, Any]] = []
    for i, (tab_key, tab_reg, bottom_cp, _ad_slot, _ad_cp) in enumerate(visits):
        _extend_steps(steps, _human_scroll_tab(rng, tab_key, tab_reg, bottom_cp, for_ad=True))
        if i != ad_on:
            continue
        _append_step(
            steps,
            human_wait(rng, rng.gauss(1.2, 0.35), 0.3, AD_PRE_TAP_HESITATION_FLOOR_SEC),
        )
        post = round(
            min(
                SCHEMA_OPEN_URL_WAIT_MAX,
                max(DABFLOW_OPEN_URL_POST_WAIT_FLOOR_SEC, rng.uniform(2.0, 4.8)),
            ),
            3,
        )
        _append_step(
            steps,
            {
                "type": "open_url",
                "url": ad_url,
                "post_wait_secs": post,
                "checkpoint": ad_checkpoint,
                "ad_selected": True,
                "mantis_hardcode": True,
            },
        )
        _extend_steps(steps, _ad_landing_engagement(rng))
    _extend_steps(steps, _return_to_dabflow_or_close(rng, url))
    return steps


def post_timer_ad_excursion(
    rng: random.Random,
    *,
    url: str = "https://getdabflow.app",
) -> list[dict[str, Any]]:
    """
    After full timer + popup skip: visit 1–3 tabs (human scroll) → ad tap on one tab →
    scroll-bottom OR ~30s dwell on ad → return to getdabflow or close via identity tail.
    """
    visits = _pick_tab_visits(rng)
    ad_on = rng.randrange(len(visits))
    steps: list[dict[str, Any]] = []
    for i, (tab_key, tab_reg, bottom_cp, ad_slot, ad_cp) in enumerate(visits):
        _extend_steps(steps, _human_scroll_tab(rng, tab_key, tab_reg, bottom_cp, for_ad=True))
        if i != ad_on:
            continue
        _append_step(
            steps,
            human_wait(rng, rng.gauss(1.2, 0.35), 0.3, AD_PRE_TAP_HESITATION_FLOOR_SEC),
        )
        ad_tap = tap_human_region(ad_slot, rng, critical=False, retries=rng.choice([3, 4, 4, 5]))
        ad_tap["ad_selected"] = True
        ad_tap["checkpoint"] = ad_cp
        _append_step(steps, ad_tap)
        _extend_steps(steps, _ad_landing_engagement(rng))
    _extend_steps(steps, _return_to_dabflow_or_close(rng, url))
    return steps


def tour_tabs_before_stats(rng: random.Random) -> list[dict[str, Any]]:
    """Visit tabs before stats scroll; ends on stats."""
    middle = ["home", "timer", "settings"]
    rng.shuffle(middle)
    ordered = middle + ["stats"]
    steps: list[dict[str, Any]] = []
    for tab in ordered:
        _extend_steps(steps, tab_switch_gap(rng))
        _append_step(steps, tap_human_region(nav_region(tab), rng, critical=(tab == "stats")))
        dwell = rng.gauss(1.05, 0.28) if tab != "stats" else rng.gauss(0.7, 0.2)
        if tab != "stats" and rng.random() < 0.28:
            dwell += rng.gauss(0.525, 0.18)
        floor = 0.7 if tab != "stats" else 0.56
        _append_step(steps, human_wait(rng, dwell, dwell * 0.25, floor))
    return steps


def session_notes_skip_block(rng: random.Random) -> list[dict[str, Any]]:
    """Timer complete → session-notes modal → skipSessionNotes() (app.js)."""
    steps: list[dict[str, Any]] = []
    skip = tap_human_region(SESSION_NOTES_SKIP_ONE, rng, critical=True, retries=4)
    skip["checkpoint"] = "popup_dismiss"
    skip["pre_wait_ms"] = 500.0
    skip["verify_dismiss"] = True
    _append_step(steps, skip)
    _append_step(
        steps,
        {
            "type": "wait",
            "seconds": SESSION_NOTES_DISMISS_WAIT_SEC,
            "checkpoint": "popup_dismissed",
            "until_session_notes_gone": True,
        },
    )
    return steps


def _mantis_tap_step(
    region,
    *,
    checkpoint: str,
    pre_wait_ms: float | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    if rng is not None:
        tap = tap_human_region(region, rng, critical=False, retries=rng.choice([3, 4, 4, 5]))
        tap["ad_selected"] = True
        tap["checkpoint"] = checkpoint
        return tap
    return _combo_tap(
        region.cx,
        region.cy,
        jitter=18,
        retries=4,
        pre_wait_ms=pre_wait_ms if pre_wait_ms is not None else 400.0,
        ad_selected=True,
        checkpoint=checkpoint,
    )


def append_home_ad_tap(steps: list[dict[str, Any]], rng: random.Random) -> None:
    """Tap home Mantis banner after scroll-to-start (ad-slot-1 / zone-one)."""
    _append_step(steps, _mantis_tap_step(HOME_AD_SLOT, checkpoint="ad_home", rng=rng))
    view = human_wait(rng, rng.gauss(1.45, 0.22), 0.12, 1.05)
    view["checkpoint"] = "ad_home_view"
    _append_step(steps, view)


def append_timer_wait_with_cooldown_ads(
    steps: list[dict[str, Any]],
    material: str,
    concentrate: str,
    heater: str,
    rng: random.Random,
) -> float:
    """Heat wait → cooldown video + timer banners during cool → completion/modal buffer."""
    heat, cool, _ = calculate_timings(material, concentrate, heater)
    _append_step(
        steps,
        {"type": "wait", "seconds": float(heat), "checkpoint": "timer_heat_complete"},
    )
    _append_step(
        steps,
        _mantis_tap_step(TIMER_COOLDOWN_VIDEO_AD, checkpoint="ad_timer_video", rng=rng),
    )
    vid_view = human_wait(rng, rng.gauss(3.1, 0.35), 0.2, 2.4)
    vid_view["checkpoint"] = "ad_timer_video_view"
    vid_view["ad_read"] = True
    _append_step(steps, vid_view)
    _append_step(
        steps,
        _mantis_tap_step(TIMER_AD_SLOT, checkpoint="ad_timer_banner", rng=rng),
    )
    _append_step(steps, human_wait(rng, rng.gauss(2.05, 0.28), 0.15, 1.45))
    _append_step(
        steps,
        _mantis_tap_step(TIMER_AD_SLOT_LOWER, checkpoint="ad_timer_banner_lower", rng=rng),
    )
    tail = round(float(cool + COMPLETION_ANIMATION_SEC + MODAL_RENDER_BUFFER_SEC), 1)
    _append_step(
        steps,
        {"type": "wait", "seconds": tail, "checkpoint": "timer_complete"},
    )
    return round(float(heat + vid_view["seconds"] + 2.05 + tail), 1)


def stats_tab_before_ad_steps(*, checkpoint: str = "tab_stats_for_ad") -> list[dict[str, Any]]:
    """Switch to Stats tab before tapping the Mantis banner (required after tab tour)."""
    return [
        _combo_tap(
            TAB_STATS.cx,
            TAB_STATS.cy,
            jitter=12,
            retries=3,
            checkpoint=checkpoint,
            bottom_nav=True,
        ),
        {"type": "wait", "seconds": 0.8},
    ]


def append_mantis_ad_block(steps: list[dict[str, Any]]) -> None:
    """Legacy single Stats ad tap — prefer ``bottom_nav_tab_tour_steps(include_ads=True)``."""
    _extend_steps(steps, stats_tab_before_ad_steps())
    _append_step(steps, _mantis_tap_step(STATS_AD_SLOT, checkpoint="ad_tapped", pre_wait_ms=400.0))
    _append_step(
        steps,
        {
            "type": "wait",
            "seconds": AD_MIN_DWELL_SEC,
            "checkpoint": "ad_read_30s",
            "ad_read": True,
        },
    )


def _combo_tap(cx: int, cy: int, **extra: Any) -> dict[str, Any]:
    return {
        "type": "tap",
        "x": cx,
        "y": cy,
        "base_w": BW,
        "base_h": BH,
        **extra,
    }


def session_notes_skip_steps(rng: random.Random) -> list[dict[str, Any]]:
    """MuMu-validated skip tap + dismiss guard — per-sequence human timing."""
    tap = tap_human_region(SESSION_NOTES_SKIP_ONE, rng, critical=False, retries=rng.choice([3, 4, 4, 5]))
    tap["checkpoint"] = "popup_dismiss"
    tap["verify_dismiss"] = True
    dismiss = human_wait(
        rng,
        rng.gauss(SESSION_NOTES_DISMISS_WAIT_SEC, 0.06),
        0.04,
        max(0.15, SESSION_NOTES_DISMISS_WAIT_SEC * 0.65),
    )
    dismiss["checkpoint"] = "popup_dismissed"
    dismiss["until_session_notes_gone"] = True
    return [tap, dismiss]


def session_notes_skip_steps_deterministic() -> list[dict[str, Any]]:
    """Legacy fixed skip steps (demo ONE canonical reference only)."""
    return [
        _combo_tap(
            SESSION_NOTES_SKIP_ONE.cx,
            SESSION_NOTES_SKIP_ONE.cy,
            jitter=8,
            retries=4,
            pre_wait_ms=500.0,
            checkpoint="popup_dismiss",
            verify_dismiss=True,
        ),
        {
            "type": "wait",
            "seconds": SESSION_NOTES_DISMISS_WAIT_SEC,
            "checkpoint": "popup_dismissed",
            "until_session_notes_gone": True,
        },
    ]


def one_timer_cycle(
    rng: random.Random,
    material: str,
    concentrate: str,
    heater: str,
    *,
    include_start_dab: bool,
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    if include_start_dab:
        _extend_steps(steps, scroll_home_to_start_dab(rng))
        start = tap_human_region(START_DAB_AFTER_SCROLL, rng, critical=True)
        start["checkpoint"] = "timer_started"
        _append_step(steps, start)
    _append_step(steps, timer_session_wait_seconds(material, concentrate, heater, rng))
    _extend_steps(steps, session_notes_skip_block(rng))
    return steps


def demo_browser_close_only() -> list[dict[str, Any]]:
    """Single browser close at end of minimal demo flows (no identity tail)."""
    return [
        {"type": "close_app", "phase": "post_browser_fast", "checkpoint": "browser_closed"},
    ]


def bottom_nav_tab_tour_steps(
    *,
    rng: random.Random,
    tab_wait_sec: float | None = None,
    between_swipe_wait_sec: float | None = None,
    include_ads: bool = False,
) -> list[dict[str, Any]]:
    """Glass → Stats → Settings: tap each bottom tab, scroll to bottom, optional Mantis taps."""
    tab_wait = tab_wait_sec if tab_wait_sec is not None else round(rng.uniform(0.20, 0.38), 3)
    between_swipe = (
        between_swipe_wait_sec if between_swipe_wait_sec is not None else round(rng.uniform(0.20, 0.36), 3)
    )
    steps: list[dict[str, Any]] = []
    tab_specs = (
        ("glass", TAB_GLASS, "tab_glass_scrolled_bottom", GLASS_AD_SLOT, "ad_glass"),
        ("stats", TAB_STATS, "tab_scrolled_bottom", STATS_AD_SLOT, "ad_stats"),
        ("settings", TAB_SETTINGS, "tab_settings_scrolled_bottom", SETTINGS_AD_SLOT, "ad_settings"),
    )
    for tab_key, reg, bottom_cp, ad_slot, ad_cp in tab_specs:
        _extend_steps(steps, tab_switch_gap(rng))
        tap = tap_human_region(reg, rng, critical=False, retries=rng.choice([2, 3, 3, 4]))
        tap["checkpoint"] = f"tab_{tab_key}"
        tap["bottom_nav"] = True
        _append_step(steps, tap)
        _append_step(steps, {"type": "wait", "seconds": tab_wait})
        swipes = scroll_bottom_swipes(tab_key)
        for i, sw in enumerate(swipes):
            cp = bottom_cp if i == len(swipes) - 1 else None
            ms = int(min(SCHEMA_SWIPE_MS_MAX, max(280, sw["ms"] + rng.randint(-120, 180))))
            _append_step(
                steps,
                {
                    "type": "swipe",
                    "x1": sw["x1"] + rng.randint(-8, 8),
                    "y1": sw["y1"] + rng.randint(-10, 10),
                    "x2": sw["x2"] + rng.randint(-8, 8),
                    "y2": sw["y2"] + rng.randint(-10, 10),
                    "ms": ms,
                    "base_w": BW,
                    "base_h": BH,
                    **({"checkpoint": cp} if cp else {}),
                },
            )
            if i < len(swipes) - 1:
                _append_step(steps, {"type": "wait", "seconds": between_swipe})
        if include_ads:
            _append_step(steps, _mantis_tap_step(ad_slot, checkpoint=ad_cp, rng=rng))
            if tab_key == "stats":
                _extend_steps(steps, ad_read_dwell_pack(rng))
            else:
                view = human_wait(rng, rng.gauss(2.15, 0.35), 0.2, 1.5)
                view["checkpoint"] = f"{ad_cp}_view"
                _append_step(steps, view)
    return steps


def glass_stats_tab_tour_steps(
    *,
    rng: random.Random | None = None,
    tab_wait_sec: float = TAB_TOUR_POST_TAB_WAIT_SEC,
    between_swipe_wait_sec: float = TAB_TOUR_SWIPE_WAIT_SEC,
) -> list[dict[str, Any]]:
    """Backward-compatible alias — full three-tab tour."""
    if rng is None:
        return bottom_nav_tab_tour_steps_legacy(
            tab_wait_sec=tab_wait_sec,
            between_swipe_wait_sec=between_swipe_wait_sec,
        )
    return bottom_nav_tab_tour_steps(
        rng=rng,
        tab_wait_sec=tab_wait_sec,
        between_swipe_wait_sec=between_swipe_wait_sec,
    )


def bottom_nav_tab_tour_steps_legacy(
    *,
    tab_wait_sec: float = TAB_TOUR_POST_TAB_WAIT_SEC,
    between_swipe_wait_sec: float = TAB_TOUR_SWIPE_WAIT_SEC,
    include_ads: bool = False,
) -> list[dict[str, Any]]:
    """Fixed-timing tab tour (demo ONE reference only)."""
    steps: list[dict[str, Any]] = []
    tab_specs = (
        ("glass", TAB_GLASS, "tab_glass_scrolled_bottom", GLASS_AD_SLOT, "ad_glass"),
        ("stats", TAB_STATS, "tab_scrolled_bottom", STATS_AD_SLOT, "ad_stats"),
        ("settings", TAB_SETTINGS, "tab_settings_scrolled_bottom", SETTINGS_AD_SLOT, "ad_settings"),
    )
    for tab_key, reg, bottom_cp, ad_slot, ad_cp in tab_specs:
        _append_step(
            steps,
            _combo_tap(
                reg.cx,
                reg.cy,
                jitter=12,
                retries=3,
                checkpoint=f"tab_{tab_key}",
                bottom_nav=True,
            ),
        )
        _append_step(steps, {"type": "wait", "seconds": tab_wait_sec})
        swipes = scroll_bottom_swipes(tab_key)
        for i, sw in enumerate(swipes):
            cp = bottom_cp if i == len(swipes) - 1 else None
            _append_step(
                steps,
                {
                    "type": "swipe",
                    "x1": sw["x1"],
                    "y1": sw["y1"],
                    "x2": sw["x2"],
                    "y2": sw["y2"],
                    "ms": sw["ms"],
                    "base_w": BW,
                    "base_h": BH,
                    **({"checkpoint": cp} if cp else {}),
                },
            )
            if i < len(swipes) - 1:
                _append_step(steps, {"type": "wait", "seconds": between_swipe_wait_sec})
        if include_ads:
            _append_step(steps, _mantis_tap_step(ad_slot, checkpoint=ad_cp, pre_wait_ms=400.0))
            if tab_key == "stats":
                _append_step(
                    steps,
                    {
                        "type": "wait",
                        "seconds": AD_MIN_DWELL_SEC,
                        "checkpoint": "ad_read_30s",
                        "ad_read": True,
                    },
                )
            else:
                _append_step(steps, {"type": "wait", "seconds": 2.0, "checkpoint": f"{ad_cp}_view"})
    return steps


def demo_post_popup_exit_tail(
    *,
    tab: str | None = "both",
    close_app: bool = True,
) -> list[dict[str, Any]]:
    """Demo tail after session-notes Skip.

    ``tab=None`` → close only. ``tab='both'`` (default) → glass+stats+settings tour + close.
    ``tab='stats'|'glass'`` → single tab + scroll (legacy).
    """
    steps: list[dict[str, Any]] = []
    if tab == "both":
        steps.extend(bottom_nav_tab_tour_steps())
    elif tab in ("glass", "stats", "settings"):
        tab_key = tab
        reg = {
            "glass": TAB_GLASS,
            "stats": TAB_STATS,
            "settings": TAB_SETTINGS,
        }[tab_key]
        _append_step(
            steps,
            _combo_tap(
                reg.cx,
                reg.cy,
                jitter=12,
                retries=3,
                checkpoint=f"tab_{tab_key}",
                bottom_nav=True,
            ),
        )
        _append_step(steps, {"type": "wait", "seconds": TAB_TOUR_POST_TAB_WAIT_SEC})
        swipes = scroll_bottom_swipes(tab_key)
        for i, sw in enumerate(swipes):
            cp = (
                "tab_glass_scrolled_bottom"
                if tab_key == "glass" and i == len(swipes) - 1
                else "tab_scrolled_bottom"
                if tab_key == "stats" and i == len(swipes) - 1
                else "tab_settings_scrolled_bottom"
                if tab_key == "settings" and i == len(swipes) - 1
                else None
            )
            _append_step(
                steps,
                {
                    "type": "swipe",
                    "x1": sw["x1"],
                    "y1": sw["y1"],
                    "x2": sw["x2"],
                    "y2": sw["y2"],
                    "ms": sw["ms"],
                    "base_w": BW,
                    "base_h": BH,
                    **({"checkpoint": cp} if cp else {}),
                },
            )
            if i < len(swipes) - 1:
                _append_step(steps, {"type": "wait", "seconds": TAB_TOUR_SWIPE_WAIT_SEC})
    if close_app:
        steps.extend(demo_browser_close_only())
    return steps


def dedupe_consecutive_step_types(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse consecutive duplicate commands (waits merged, identical taps/swipes dropped)."""
    return normalize_automation_steps(steps)


def demo_identity_tail_block(rng: random.Random | None = None) -> list[dict[str, Any]]:
    """Identity tail: close_app → rotate_identity → full_reset (human gaps when rng set)."""
    if rng is None:
        return [
            {
                "type": "close_app",
                "phase": "post_browser_fast",
                "checkpoint": "browser_closed",
            },
            {"type": "wait", "seconds": 0.27, "phase": "post_browser_fast"},
            {
                "type": "rotate_identity",
                "phase": "post_browser_fast",
                "checkpoint": "identity_rotated",
            },
            {"type": "wait", "seconds": 0.39, "phase": "post_browser_fast"},
            {
                "type": "full_reset",
                "phase": "post_browser_fast",
                "checkpoint": "session_reset",
            },
        ]
    steps: list[dict[str, Any]] = [
        {
            "type": "close_app",
            "phase": "post_browser_fast",
            "checkpoint": "browser_closed",
        },
    ]
    _append_step(steps, post_browser_wait(rng))
    _append_step(
        steps,
        {
            "type": "rotate_identity",
            "phase": "post_browser_fast",
            "checkpoint": "identity_rotated",
        },
    )
    _append_step(steps, post_browser_wait(rng))
    _append_step(
        steps,
        {
            "type": "full_reset",
            "phase": "post_browser_fast",
            "checkpoint": "session_reset",
        },
    )
    return steps


def build_combo_matrix_steps(
    material: str,
    concentrate: str,
    heater: str,
    *,
    flow: str,
    url: str = "https://getdabflow.app",
    skip_tab_tour: bool = False,
    rng: random.Random,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Demo-ONE flow for every mat×conc×heat combo — per-sequence human pacing (snowflake).

    open → age → 3 picks → scroll → start dab → ONE combo timer wait → skip →
    (no-ad: glass/stats/settings tab tour) OR
    (ad: one tab → scroll → ad tap → scroll bottom → ≥30s dwell) → identity tail.
    """
    heat, cool, total = calculate_timings(material, concentrate, heater)
    conc = concentrate_region_mumu(concentrate)

    steps: list[dict[str, Any]] = []
    _extend_steps(steps, pre_site_fast_block(rng, url))
    for step in steps:
        if step.get("type") == "open_url":
            step["checkpoint"] = "loaded"
            break

    age = age_verification_tap(rng)
    age["checkpoint"] = "age_verification"
    _append_step(steps, age)
    _append_step(
        steps,
        human_wait(
            rng,
            rng.gauss(POST_AGE_WAIT_MEAN_SEC, 0.03),
            0.03,
            POST_AGE_WAIT_FLOOR_SEC,
        ),
    )

    pick_regions = (
        (MAT_POS_MUMU[material], False),
        (conc, False),
        (HEAT_POS_MUMU[heater], False),
    )
    for i, (region, critical) in enumerate(pick_regions):
        _append_step(steps, tap_human_region(region, rng, critical=critical))
        if i < len(pick_regions) - 1:
            _append_step(steps, meaningful_tap_gap(rng))
        else:
            done_wait = human_wait(
                rng,
                rng.gauss(PRE_START_DAB_MEAN_SEC, 0.02),
                0.02,
                PRE_START_DAB_FLOOR_SEC,
            )
            done_wait["checkpoint"] = "selections_done"
            _append_step(steps, done_wait)

    _extend_steps(steps, scroll_home_to_start_dab(rng))

    start = tap_human_region(START_DAB_AFTER_SCROLL, rng, critical=True, retries=5)
    start["checkpoint"] = "timer_started"
    start["pre_wait_ms"] = float(min(600.0, max(280.0, rng.gauss(450.0, 60.0))))
    _append_step(steps, start)

    timer_wait = _append_timer_complete_wait(steps, material, concentrate, heater)

    _extend_steps(steps, session_notes_skip_steps(rng))

    if not skip_tab_tour:
        if flow == "ad":
            _extend_steps(steps, post_timer_ad_excursion(rng, url=url))
        else:
            _extend_steps(steps, post_timer_no_ad_tab_tour(rng))

    _extend_steps(steps, demo_identity_tail_block(rng))

    steps = dedupe_consecutive_step_types(steps)
    flow_label = "ad" if flow == "ad" else "no-ads"
    meta: dict[str, Any] = {
        "flow": flow_label,
        "dabflow_material": material,
        "dabflow_concentrate": concentrate,
        "dabflow_heater": heater,
        "timer_cycles": 1,
        "baseline_wh": f"{BW}x{BH}",
        "base_w": BW,
        "base_h": BH,
        "humanization": "snowflake_v1",
        "description": (
            "Combo matrix: age, 3 picks, scroll, start dab, full combo timer wait, "
            "skip popup; no-ad=tab tour, ad=post-timer tab scroll + ad link + ≥30s dwell"
        ),
        "timer_heat_sec": heat,
        "timer_cool_sec": cool,
        "timer_total_sec": total,
        "timer_wait_seconds": timer_wait,
        "completion_animation_sec": COMPLETION_ANIMATION_SEC,
        "modal_render_buffer_sec": MODAL_RENDER_BUFFER_SEC,
        "timer_wait_formula": (
            f"ui_total({total})+COMPLETION_ANIMATION({COMPLETION_ANIMATION_SEC})+"
            f"MODAL_BUFFER({MODAL_RENDER_BUFFER_SEC})={timer_wait}"
        ),
        "identity_tail": True,
        "start_dab_coords": f"({START_DAB_AFTER_SCROLL.cx},{START_DAB_AFTER_SCROLL.cy})",
    }
    if flow == "ad":
        meta["ad_min_dwell_sec"] = AD_MIN_DWELL_SEC
        meta["ad_max_dwell_sec"] = AD_MAX_DWELL_SEC
    return steps, meta


def build_demo_one_steps(
    material: str = "ceramic",
    concentrate: str = "distillate",
    heater: str = "propane",
    *,
    url: str = "https://getdabflow.app",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Minimal demo ONE: open once → age → 3 picks → scroll → timer → skip → close once."""
    from dabflow_layout import (  # noqa: WPS433 — same package
        AGE_YES_MUMU,
        HEAT_POS_MUMU,
        MAT_POS_MUMU,
        SCROLL_TO_START_DAB_SWIPES,
        SESSION_NOTES_SKIP_MUMU,
        START_DAB_AFTER_SCROLL,
        concentrate_region_mumu,
    )

    heat, cool, total = calculate_timings(material, concentrate, heater)
    conc = concentrate_region_mumu(concentrate)

    def _tap(cx: int, cy: int, **extra: Any) -> dict[str, Any]:
        return {
            "type": "tap",
            "x": cx,
            "y": cy,
            "base_w": BW,
            "base_h": BH,
            **extra,
        }

    steps: list[dict[str, Any]] = []
    _append_step(steps, {"type": "clear_cookies"})
    _append_step(
        steps,
        {
            "type": "open_url",
            "url": url,
            "post_wait_secs": DABFLOW_OPEN_URL_POST_WAIT_FLOOR_SEC,
            "checkpoint": "loaded",
            "phase": "pre_site_fast",
        },
    )
    _append_step(
        steps,
        _tap(
            AGE_YES_MUMU.cx,
            AGE_YES_MUMU.cy,
            jitter=4,
            retries=5,
            age_verification=True,
            checkpoint="age_verification",
        ),
    )
    _append_step(steps, {"type": "wait", "seconds": 0.38})
    _append_step(steps, _tap(MAT_POS_MUMU[material].cx, MAT_POS_MUMU[material].cy, jitter=15, retries=2))
    _append_step(steps, {"type": "wait", "seconds": 0.28})
    _append_step(steps, _tap(conc.cx, conc.cy, jitter=15, retries=2))
    _append_step(steps, {"type": "wait", "seconds": 0.28})
    _append_step(steps, _tap(HEAT_POS_MUMU[heater].cx, HEAT_POS_MUMU[heater].cy, jitter=15, retries=2))
    _append_step(steps, {"type": "wait", "seconds": 0.28, "checkpoint": "selections_done"})
    for i, sw in enumerate(SCROLL_TO_START_DAB_SWIPES):
        _append_step(
            steps,
            {
                "type": "swipe",
                "x1": sw["x1"],
                "y1": sw["y1"],
                "x2": sw["x2"],
                "y2": sw["y2"],
                "ms": sw["ms"],
                "base_w": BW,
                "base_h": BH,
                **(
                    {"checkpoint": "scroll_to_start_dab"}
                    if i == len(SCROLL_TO_START_DAB_SWIPES) - 1
                    else {}
                ),
            },
        )
        _append_step(
            steps,
            {"type": "wait", "seconds": 0.5 if i == len(SCROLL_TO_START_DAB_SWIPES) - 1 else 0.28},
        )
    _append_step(
        steps,
        _tap(
            START_DAB_AFTER_SCROLL.cx,
            START_DAB_AFTER_SCROLL.cy,
            jitter=8,
            retries=5,
            pre_wait_ms=450.0,
            checkpoint="timer_started",
        ),
    )
    timer_wait = _append_timer_complete_wait(steps, material, concentrate, heater)
    _extend_steps(steps, session_notes_skip_steps_deterministic())
    _extend_steps(steps, glass_stats_tab_tour_steps())
    for tail_step in demo_identity_tail_block():
        _append_step(steps, tail_step)
    steps = dedupe_consecutive_step_types(steps)
    meta = {
        "flow": "demo-ONE",
        "canonical": True,
        "dabflow_material": material,
        "dabflow_concentrate": concentrate,
        "dabflow_heater": heater,
        "timer_cycles": 1,
        "baseline_wh": f"{BW}x{BH}",
        "base_w": BW,
        "base_h": BH,
        "description": (
            "Canonical demo: age gate, fast selections, full timer wait, session-notes Skip, "
            "glass tab, scroll bottom, stats tab, scroll bottom, settings tab, scroll bottom, identity tail"
        ),
        "timer_heat_sec": heat,
        "timer_cool_sec": cool,
        "timer_total_sec": total,
        "timer_wait_seconds": timer_wait,
        "completion_animation_sec": COMPLETION_ANIMATION_SEC,
        "modal_render_buffer_sec": MODAL_RENDER_BUFFER_SEC,
        "timer_wait_formula": (
            f"ui_total({total})+COMPLETION_ANIMATION({COMPLETION_ANIMATION_SEC})+"
            f"MODAL_BUFFER({MODAL_RENDER_BUFFER_SEC})={timer_wait}"
        ),
        "identity_tail": True,
    }
    return steps, meta


def build_demo_two_steps(
    material: str = "ceramic",
    concentrate: str = "distillate",
    heater: str = "propane",
    *,
    url: str = "https://getdabflow.app",
    ad_dwell_sec: float = AD_MIN_DWELL_SEC,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Minimal ad demo: full timer → post-timer tab ad tap + dwell → close (no identity tail)."""
    demo_rng = rng_for("demo-TWO", "ad", human_bucket="000")
    steps, meta = build_combo_matrix_steps(
        material,
        concentrate,
        heater,
        flow="ad",
        url=url,
        skip_tab_tour=False,
        rng=demo_rng,
    )
    trimmed: list[dict[str, Any]] = []
    for step in steps:
        t = step.get("type")
        if t in ("rotate_identity", "full_reset"):
            continue
        if t == "close_app" and step.get("checkpoint") == "browser_closed":
            trimmed.append(step)
            break
        trimmed.append(step)
    if not trimmed or trimmed[-1].get("type") != "close_app":
        trimmed.extend(demo_browser_close_only())
    steps = dedupe_consecutive_step_types(trimmed)
    heat, cool, total = calculate_timings(material, concentrate, heater)
    meta = dict(meta)
    meta.update(
        {
            "flow": "demo-TWO",
            "canonical": True,
            "description": "Minimal ad demo: full timer → post-timer tab ad tap + ≥30s dwell + close",
            "ad_slots": (
                f"post-timer tab (glass|stats|settings) → "
                f"STATS ({STATS_AD_SLOT.cx},{STATS_AD_SLOT.cy}) or sibling zone"
            ),
            "ad_dwell_seconds": ad_dwell_sec,
            "timer_heat_sec": heat,
            "timer_cool_sec": cool,
            "timer_total_sec": total,
            "identity_tail": False,
        }
    )
    return steps, meta


def pre_site_fast_block(rng: random.Random, url: str) -> list[dict[str, Any]]:
    """clear_cookies → open_url → brief settle — post_wait + settle ≤ ~2s before age tap."""
    steps: list[dict[str, Any]] = []
    _append_step(steps, {"type": "clear_cookies", "phase": "pre_site_fast"})
    w = fast_wait(rng, max_sec=PRE_SITE_CLEAR_WAIT_MAX_SEC, mean=0.25)
    _append_step(steps, w)
    _append_step(
        steps,
        {
            "type": "open_url",
            "url": url,
            "post_wait_secs": _open_url_post_wait_secs(url, rng),
            "phase": "pre_site_fast",
        },
    )
    settle = dict(fast_wait(rng, max_sec=PRE_SITE_SETTLE_WAIT_MAX_SEC, mean=0.35))
    settle["phase"] = "pre_site_fast"
    _append_step(steps, settle)
    return steps


def on_site_human_block(
    rng: random.Random,
    material: str,
    concentrate: str,
    heater: str,
    flow: str,
    *,
    timer2x: bool,
) -> list[dict[str, Any]]:
    """Age gate through ad/no-ad interaction — human_pace_v7 funnel gaps."""
    steps: list[dict[str, Any]] = []
    age = age_verification_tap(rng)
    age["phase"] = "on_site_human"
    _append_step(steps, age)
    _append_step(
        steps,
        human_wait(
            rng,
            rng.gauss(POST_AGE_WAIT_MEAN_SEC, 0.03),
            0.03,
            POST_AGE_WAIT_FLOOR_SEC,
        ),
    )

    regions = (
        (MAT_POS[material], True),
        (concentrate_region(concentrate), True),
        (HEAT_POS[heater], True),
    )
    for i, (region, critical) in enumerate(regions):
        tap = tap_human_region(region, rng, critical=critical)
        tap["phase"] = "on_site_human"
        _append_step(steps, tap)
        if i < len(regions) - 1:
            _append_step(steps, meaningful_tap_gap(rng))
        else:
            done_wait = human_wait(
                rng,
                rng.gauss(PRE_START_DAB_MEAN_SEC, 0.02),
                0.02,
                PRE_START_DAB_FLOOR_SEC,
            )
            done_wait["checkpoint"] = "selections_done"
            _append_step(steps, done_wait)

    _extend_steps(
        steps,
        one_timer_cycle(
            rng,
            material,
            concentrate,
            heater,
            include_start_dab=True,
        ),
    )
    if timer2x:
        _extend_steps(steps, think_after_reset(rng))
        _extend_steps(
            steps,
            one_timer_cycle(
                rng,
                material,
                concentrate,
                heater,
                include_start_dab=True,
            ),
        )
    _extend_steps(steps, tab_excursion_exit_repeat(rng, material))
    _extend_steps(steps, tour_tabs_before_stats(rng))
    _extend_steps(steps, segmented_scroll_down(rng))

    if flow == "ad":
        _extend_steps(steps, ad_interaction_block(rng))
    else:
        _extend_steps(steps, scroll_to_bottom(rng, segments=rng.randint(4, 7)))
    return steps


def post_browser_fast_block(rng: random.Random) -> list[dict[str, Any]]:
    """close_app → rotate_identity → full_reset with minimal waits."""
    return [
        {"type": "close_app", "phase": "post_browser_fast"},
        post_browser_wait(rng),
        {"type": "rotate_identity", "phase": "post_browser_fast"},
        post_browser_wait(rng),
        {"type": "full_reset", "phase": "post_browser_fast"},
    ]


def build_sequence(
    material: str,
    concentrate: str,
    heater: str,
    flow: str,
    *,
    timer2x: bool,
    rng: random.Random,
    url: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta: dict[str, Any] = {
        "dabflow_material": material,
        "dabflow_concentrate": concentrate,
        "dabflow_heater": heater,
        "timer_cycles": 2 if timer2x else 1,
        "flow": flow,
        "baseline_wh": f"{BW}x{BH}",
        "humanization": "gaussian_waits_human_pace_v7",
        "timing_phases": ["pre_site_fast", "on_site_human", "post_browser_fast"],
        "tab_excursion": "glass_select_exit_home",
        "ad_min_dwell_sec": AD_MIN_DWELL_SEC if flow == "ad" else None,
        "ad_max_dwell_sec": AD_MAX_DWELL_SEC if flow == "ad" else None,
    }
    steps: list[dict[str, Any]] = []
    _extend_steps(steps, pre_site_fast_block(rng, url))
    _extend_steps(
        steps,
        on_site_human_block(
            rng,
            material,
            concentrate,
            heater,
            flow,
            timer2x=timer2x,
        ),
    )
    _extend_steps(steps, post_browser_fast_block(rng))

    steps = normalize_automation_steps(steps)
    return steps, meta


def combo_id(material: str, concentrate: str, heater: str) -> str:
    return f"{material}__{concentrate}__{heater}"


def combo_matrix_filename(flow: str, material: str, concentrate: str, heater: str) -> str:
    flow_token = "ad" if flow == "ad" else "no_ads"
    return (
        f"dabflow__{flow_token}__mat-{material}__conc-{concentrate}__heat-{heater}.json"
    )


def mantis_hardcode_test_filename(index: int, material: str, concentrate: str, heater: str) -> str:
    return (
        f"dabflow__mantis_hardcode__{index:02d}__mat-{material}__conc-{concentrate}__heat-{heater}.json"
    )


def build_mantis_hardcode_test_steps(
    material: str,
    concentrate: str,
    heater: str,
    *,
    ad_url: str,
    ad_checkpoint: str,
    ad_tab_key: str,
    url: str = "https://getdabflow.app",
    rng: random.Random,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Combo matrix funnel with post-timer ``open_url`` to a Mantis ad landing (no ad tap)."""
    heat, cool, total = calculate_timings(material, concentrate, heater)
    conc = concentrate_region_mumu(concentrate)

    steps: list[dict[str, Any]] = []
    _extend_steps(steps, pre_site_fast_block(rng, url))
    for step in steps:
        if step.get("type") == "open_url":
            step["checkpoint"] = "loaded"
            break

    age = age_verification_tap(rng)
    age["checkpoint"] = "age_verification"
    _append_step(steps, age)
    _append_step(
        steps,
        human_wait(
            rng,
            rng.gauss(POST_AGE_WAIT_MEAN_SEC, 0.03),
            0.03,
            POST_AGE_WAIT_FLOOR_SEC,
        ),
    )

    pick_regions = (
        (MAT_POS_MUMU[material], False),
        (conc, False),
        (HEAT_POS_MUMU[heater], False),
    )
    for i, (region, critical) in enumerate(pick_regions):
        _append_step(steps, tap_human_region(region, rng, critical=critical))
        if i < len(pick_regions) - 1:
            _append_step(steps, meaningful_tap_gap(rng))
        else:
            done_wait = human_wait(
                rng,
                rng.gauss(PRE_START_DAB_MEAN_SEC, 0.02),
                0.02,
                PRE_START_DAB_FLOOR_SEC,
            )
            done_wait["checkpoint"] = "selections_done"
            _append_step(steps, done_wait)

    _extend_steps(steps, scroll_home_to_start_dab(rng))

    start = tap_human_region(START_DAB_AFTER_SCROLL, rng, critical=True, retries=5)
    start["checkpoint"] = "timer_started"
    start["pre_wait_ms"] = float(min(600.0, max(280.0, rng.gauss(450.0, 60.0))))
    _append_step(steps, start)

    timer_wait = _append_timer_complete_wait(steps, material, concentrate, heater)
    _extend_steps(steps, session_notes_skip_steps(rng))
    _extend_steps(
        steps,
        post_timer_ad_hardcode_excursion(
            rng,
            ad_url=ad_url,
            ad_checkpoint=ad_checkpoint,
            ad_tab_key=ad_tab_key,
            url=url,
        ),
    )
    _extend_steps(steps, demo_identity_tail_block(rng))

    steps = dedupe_consecutive_step_types(steps)
    meta: dict[str, Any] = {
        "flow": "mantis-hardcode",
        "dabflow_material": material,
        "dabflow_concentrate": concentrate,
        "dabflow_heater": heater,
        "timer_cycles": 1,
        "baseline_wh": f"{BW}x{BH}",
        "base_w": BW,
        "base_h": BH,
        "humanization": "snowflake_v1",
        "description": (
            "Mantis hardcode test: full combo timer, skip popup, tab tour, open_url to "
            "advertiser landing (no on-site ad tap), ≥30s dwell, identity tail"
        ),
        "timer_heat_sec": heat,
        "timer_cool_sec": cool,
        "timer_total_sec": total,
        "timer_wait_seconds": timer_wait,
        "completion_animation_sec": COMPLETION_ANIMATION_SEC,
        "modal_render_buffer_sec": MODAL_RENDER_BUFFER_SEC,
        "timer_wait_formula": (
            f"ui_total({total})+COMPLETION_ANIMATION({COMPLETION_ANIMATION_SEC})+"
            f"MODAL_BUFFER({MODAL_RENDER_BUFFER_SEC})={timer_wait}"
        ),
        "identity_tail": True,
        "start_dab_coords": f"({START_DAB_AFTER_SCROLL.cx},{START_DAB_AFTER_SCROLL.cy})",
        "ad_min_dwell_sec": AD_MIN_DWELL_SEC,
        "ad_max_dwell_sec": AD_MAX_DWELL_SEC,
        "mantis_hardcode": True,
        "mantis_ad_url": ad_url,
        "mantis_ad_tab": ad_tab_key,
        "mantis_ad_checkpoint": ad_checkpoint,
    }
    return steps, meta


def write_payload_all_resolutions(
    output_root: Path,
    rel_dir: Path,
    filename: str,
    payload: dict,
) -> list[Path]:
    """Write one sequence JSON under every MuMu resolution folder."""
    from build_gold_dataset import remap_steps

    written: list[Path] = []
    for w, h in RESOLUTIONS:
        tag = f"{w}x{h}"
        out_obj = dict(payload)
        steps = payload.get("steps")
        if isinstance(steps, list):
            out_obj["steps"] = remap_steps(list(steps), w, h)
        meta = payload.get("meta")
        if isinstance(meta, dict):
            m = dict(meta)
            m["base_w"] = w
            m["base_h"] = h
            out_obj["meta"] = m
        out_obj["baseline_wh"] = tag
        out_dir = output_root / tag / rel_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / filename
        target.write_text(json.dumps(out_obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(target)
    return written


def generate_mantis_hardcode_tests(
    output_root: Path,
    *,
    url: str = "https://getdabflow.app",
    count: int = 5,
) -> list[Path]:
    """Write ``count`` mantis-hardcode test JSON files under every resolution."""
    from dabflow_mantis_ad_urls import (  # noqa: WPS433
        HARDOCODE_TEST_SPECS,
        ad_checkpoint_for_zone,
        resolve_hardcode_ad_urls,
    )

    specs = list(HARDOCODE_TEST_SPECS[: max(1, count)])
    zones = tuple({row[4] for row in specs})
    ad_urls = resolve_hardcode_ad_urls(zones)

    written: list[Path] = []
    for idx, (material, concentrate, heater, ad_tab, zone) in enumerate(specs, start=1):
        if zone not in ad_urls:
            raise KeyError(f"no Mantis landing URL for zone {zone!r}")
        ad_url = ad_urls[zone]
        ad_checkpoint = ad_checkpoint_for_zone(zone)
        combo = combo_id(material, concentrate, heater)
        bucket = human_bucket(combo, "mantis-hardcode", "900x1600")
        rng = rng_for(combo, "mantis-hardcode", human_bucket=bucket)
        steps, meta = build_mantis_hardcode_test_steps(
            material,
            concentrate,
            heater,
            ad_url=ad_url,
            ad_checkpoint=ad_checkpoint,
            ad_tab_key=ad_tab,
            url=url,
            rng=rng,
        )
        meta["human_bucket"] = bucket
        meta["mantis_zone"] = zone
        payload = {
            "steps": steps,
            "meta": meta,
            "label": (
                f"DabFlow mantis-hardcode #{idx:02d} {material}/{concentrate}/{heater} "
                f"→ {ad_tab} ({zone})"
            ),
        }
        fname = mantis_hardcode_test_filename(idx, material, concentrate, heater)
        for target in write_payload_all_resolutions(
            output_root, Path("ad") / "mantis-hardcode", fname, payload
        ):
            written.append(target)
            print(f"wrote {target}")
    return written


def _purge_stale_matrix_files(output_root: Path) -> int:
    """Remove legacy humanized matrix JSON; preserve demo ONE/TWO."""
    removed = 0
    keep = {"dabflow__demo__ONE.json", "dabflow__demo__TWO.json"}
    for w, h in RESOLUTIONS:
        for flow_dir in ("ad", "no-ad"):
            d = output_root / f"{w}x{h}" / flow_dir
            if not d.is_dir():
                continue
            for fp in d.glob("dabflow__*.json"):
                if fp.name in keep:
                    continue
                fp.unlink(missing_ok=True)
                removed += 1
    return removed


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate DabFlow combo matrix sequences (local only).")
    ap.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Local sequences root (default: CPHARM_SEQUENCES_DIR or ~/CPharm/sequences)",
    )
    ap.add_argument(
        "--url",
        default="https://getdabflow.app",
        help="DabFlow web URL",
    )
    ap.add_argument(
        "--gold",
        action="store_true",
        help="Legacy humanized gold matrix (tab excursion, timer2x, etc.)",
    )
    ap.add_argument(
        "--resolution",
        default=None,
        help="Only emit one resolution folder, e.g. 900x1600",
    )
    ap.add_argument(
        "--flow-dir",
        default=None,
        choices=("ad", "no-ad"),
        help="Only emit one flow subfolder (ad or no-ad)",
    )
    ap.add_argument(
        "--update-demo-one",
        action="store_true",
        help="Rewrite dabflow__demo__ONE.json at 900x1600/no-ad from build_demo_one_steps()",
    )
    ap.add_argument(
        "--update-demo-two",
        action="store_true",
        help="Rewrite dabflow__demo__TWO.json at 900x1600/ad from build_demo_two_steps()",
    )
    ap.add_argument(
        "--generate-mantis-hardcode-tests",
        type=int,
        nargs="?",
        const=5,
        metavar="N",
        help="Write N mantis-hardcode test sequences (default 5) under 900x1600/ad/mantis-hardcode/",
    )
    ap.add_argument(
        "--skip-purge",
        action="store_true",
        help="Do not delete stale matrix files before writing",
    )
    args = ap.parse_args()

    output_root = (args.output or resolve_sequences_dir(create=True)).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    if args.gold:
        return _main_gold_matrix(output_root, url=args.url)

    if args.update_demo_one:
        steps, meta = build_demo_one_steps()
        payload = {
            "steps": steps,
            "meta": meta,
            "label": "DabFlow demo ONE (canonical gold reference)",
        }
        for target in write_payload_all_resolutions(
            output_root, Path("no-ad"), "dabflow__demo__ONE.json", payload
        ):
            print(f"wrote {target}")

    if args.update_demo_two:
        steps, meta = build_demo_two_steps()
        payload = {
            "steps": steps,
            "meta": meta,
            "label": "DabFlow demo TWO: age + home/timer/tab Mantis ads + close",
        }
        for target in write_payload_all_resolutions(
            output_root, Path("ad"), "dabflow__demo__TWO.json", payload
        ):
            print(f"wrote {target}")

    if args.generate_mantis_hardcode_tests is not None:
        generate_mantis_hardcode_tests(
            output_root,
            url=args.url,
            count=int(args.generate_mantis_hardcode_tests),
        )

    if args.update_demo_one or args.update_demo_two or args.generate_mantis_hardcode_tests is not None:
        if args.flow_dir or args.gold:
            pass  # continue into matrix generation below
        elif not args.resolution:
            # Demo-only / hardcode-only refresh (no matrix regen requested).
            return 0

    resolutions = list(RESOLUTIONS)
    if args.resolution:
        parts = str(args.resolution).lower().split("x")
        if len(parts) != 2:
            print(f"invalid --resolution {args.resolution!r}", file=sys.stderr)
            return 2
        resolutions = [(int(parts[0]), int(parts[1]))]

    flow_dirs = (("no-ad", "no-ads"), ("ad", "ad"))
    if args.flow_dir:
        flow_dirs = (
            ("no-ad", "no-ads") if args.flow_dir == "no-ad" else ("ad", "ad"),
        )

    removed = 0 if args.skip_purge else _purge_stale_matrix_files(output_root)
    min_wait, max_wait, min_combo, max_combo = timer_wait_range()

    stats: dict[str, Any] = {
        "mode": "combo_matrix_demo_one_flow_snowflake",
        "humanization": "per_combo_flow_resolution_rng_v1",
        "option_sha256": option_hash_blob(),
        "combos_per_resolution": len(MATERIALS) * len(CONCENTRATES) * len(HEATERS),
        "no_ads_files": 0,
        "ad_files": 0,
        "total_json": 0,
        "stale_files_removed": removed,
        "output_root": str(output_root),
        "resolutions": [f"{w}x{h}" for w, h in resolutions],
        "timer_wait_min_sec": min_wait,
        "timer_wait_max_sec": max_wait,
        "timer_wait_min_combo": {
            "material": min_combo[0],
            "concentrate": min_combo[1],
            "heater": min_combo[2],
        },
        "timer_wait_max_combo": {
            "material": max_combo[0],
            "concentrate": max_combo[1],
            "heater": max_combo[2],
        },
        "flow": (
            "open → age → 3 picks → scroll → start dab → combo timer wait → "
            "skip → glass/stats/settings tabs → scroll → identity tail"
        ),
    }

    for flow_dir, flow in flow_dirs:
        for mat in MATERIALS:
            for conc in CONCENTRATES:
                for heat in HEATERS:
                    cid = combo_id(mat, conc, heat)
                    fname = combo_matrix_filename(flow, mat, conc, heat)

                    for w, h in resolutions:
                        res_tag = f"{w}x{h}"
                        bucket = human_bucket(cid, flow, res_tag)
                        rng = rng_for(cid, flow, human_bucket=bucket)
                        steps, meta = build_combo_matrix_steps(
                            mat, conc, heat, flow=flow, url=args.url, rng=rng
                        )
                        meta = dict(meta)
                        meta["human_bucket"] = bucket
                        meta["base_w"] = w
                        meta["base_h"] = h
                        meta["baseline_wh"] = res_tag

                        rem = remap_steps(list(steps), w, h)
                        out_obj = {
                            "steps": rem,
                            "meta": meta,
                            "label": f"DabFlow {flow} {cid} ({res_tag})",
                        }

                        out_dir = output_root / res_tag / flow_dir
                        out_dir.mkdir(parents=True, exist_ok=True)
                        target = out_dir / fname
                        target.write_text(
                            json.dumps(out_obj, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8",
                        )

                        stats["total_json"] += 1
                        if flow == "no-ads":
                            stats["no_ads_files"] += 1
                        else:
                            stats["ad_files"] += 1

    summary_path = output_root / "_dabflow_matrix_summary.json"
    summary_path.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2))
    return 0


def _main_gold_matrix(output_root: Path, *, url: str) -> int:
    combos = [(m, c, h) for m in MATERIALS for c in CONCENTRATES for h in HEATERS]
    stats: dict[str, Any] = {
        "option_sha256": option_hash_blob(),
        "timer1x_files": 0,
        "timer2x_files": 0,
        "no_ads_files": 0,
        "ad_files": 0,
        "total_json": 0,
        "output_root": str(output_root),
        "resolutions": [f"{w}x{h}" for w, h in RESOLUTIONS],
        "timer2x_fraction_expected": 0.20,
        "ad_min_dwell_sec": AD_MIN_DWELL_SEC,
        "ad_max_dwell_sec": AD_MAX_DWELL_SEC,
        "humanization": [
            "human_pace_v8: pre_site_fast (≤2s post_wait+settle to age gate) + fast funnel taps + post_browser_fast",
            "Mandatory Glass tab → select → BACK → Home after timer",
            "Ad path: scroll-to-bottom → hesitate → ad tap (ad_selected) → read dwell 30-45s",
            "No-ad path: optional scroll-to-bottom before identity tail",
            "On-site: Gaussian waits, jitter taps, segmented stats scroll",
            "identity tail: close_app → rotate_identity → full_reset (≤0.5s gaps)",
        ],
    }

    for flow_dir, flow in (("no-ad", "no-ads"), ("ad", "ad")):
        for mat in MATERIALS:
            for conc in CONCENTRATES:
                for heat in HEATERS:
                    cid = combo_id(mat, conc, heat)
                    hcode = int(hashlib.md5(f"{cid}|{flow}".encode()).hexdigest(), 16)
                    timer2x = (hcode % 5) == 0
                    human_bucket = f"{hcode % 997:03d}"
                    rng = rng_for(cid, flow, human_bucket=human_bucket)

                    steps, meta = build_sequence(
                        mat,
                        conc,
                        heat,
                        flow,
                        timer2x=timer2x,
                        rng=rng,
                        url=url,
                    )
                    payload = {"steps": steps, "meta": meta, "label": f"DabFlow {flow} {cid}"}

                    fname_parts = [
                        "dabflow",
                        flow.replace("-", "_"),
                        f"mat-{mat}",
                        f"conc-{conc}",
                        f"heat-{heat}",
                        "timer2x" if timer2x else "timer1x",
                        f"human{human_bucket}",
                    ]
                    fname = "__".join(fname_parts) + ".json"

                    for w, h in RESOLUTIONS:
                        rem = remap_steps(list(payload["steps"]), w, h)
                        out_obj = dict(payload)
                        out_obj["steps"] = rem
                        out_obj["meta"] = dict(meta)
                        out_obj["meta"]["base_w"] = w
                        out_obj["meta"]["base_h"] = h
                        out_obj["baseline_wh"] = f"{w}x{h}"

                        out_dir = output_root / f"{w}x{h}" / flow_dir
                        out_dir.mkdir(parents=True, exist_ok=True)
                        target = out_dir / fname
                        target.write_text(
                            json.dumps(out_obj, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8",
                        )

                        stats["total_json"] += 1
                        if timer2x:
                            stats["timer2x_files"] += 1
                        else:
                            stats["timer1x_files"] += 1
                        if flow == "no-ads":
                            stats["no_ads_files"] += 1
                        else:
                            stats["ad_files"] += 1

    summary_path = output_root / "_dabflow_matrix_summary.json"
    summary_path.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
