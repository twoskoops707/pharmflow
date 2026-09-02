"""DabFlow timer math mirrored from ``www/js/app.js`` CONFIG + ``calculateTimings()``."""

from __future__ import annotations

from itertools import product
from typing import NamedTuple

# --- mirrored from DabFlow www/js/app.js CONFIG (origin/web) ---
MAX_HEAT_TIME = 20
MIN_COOL_TIME = 50
MAX_COOL_TIME = 85

MATERIAL_CFG: dict[str, dict[str, int]] = {
    "quartz": {"heatUp": 18, "coolDown": 60},
    "titanium": {"heatUp": 15, "coolDown": 70},
    "ceramic": {"heatUp": 20, "coolDown": 75},
}
HEATER_CFG: dict[str, dict[str, float]] = {
    "butane": {"heatModifier": 1.1, "coolModifier": 1.0},
    "propane": {"heatModifier": 1.0, "coolModifier": 0.95},
}
CONCENTRATE_CFG: dict[str, dict[str, float]] = {
    "shatter": {"coolModifier": 1.0},
    "wax": {"coolModifier": 0.93},
    "live-resin": {"coolModifier": 1.05},
    "rosin": {"coolModifier": 1.08},
    "diamonds": {"coolModifier": 1.15},
    "crumble": {"coolModifier": 0.95},
    "budder": {"coolModifier": 0.97},
    "sauce": {"coolModifier": 1.10},
    "hash-rosin": {"coolModifier": 1.12},
    "distillate": {"coolModifier": 0.90},
}

MATERIALS = tuple(MATERIAL_CFG.keys())
CONCENTRATES = tuple(CONCENTRATE_CFG.keys())
HEATERS = tuple(HEATER_CFG.keys())

# showCompletionAnimation(): 3500ms hold + 1500ms fade + 500ms before modal
COMPLETION_ANIMATION_SEC = 5.5
MODAL_RENDER_BUFFER_SEC = 1.0  # session-notes modal ready to tap after animation


class TimerTimings(NamedTuple):
    heat: int
    cool: int
    total: int
    wait_seconds: float


def calculate_timings(material: str, concentrate: str, heater: str) -> tuple[int, int, int]:
    """Return (heat_sec, cool_sec, total_sec) with app.js safety caps applied."""
    m = MATERIAL_CFG[material]
    h = HEATER_CFG[heater]
    c = CONCENTRATE_CFG[concentrate]
    heat = round(m["heatUp"] * h["heatModifier"])
    cool = round(m["coolDown"] * h["coolModifier"] * c["coolModifier"])
    if heat > MAX_HEAT_TIME:
        heat = MAX_HEAT_TIME
    if cool < MIN_COOL_TIME:
        cool = MIN_COOL_TIME
    if cool > MAX_COOL_TIME:
        cool = MAX_COOL_TIME
    return heat, cool, heat + cool


def timer_half_cool_wait_seconds(material: str, concentrate: str, heater: str) -> float:
    """Early-exit wait: full heat phase + halfway through cool down (no completion/modal)."""
    heat, cool, _ = calculate_timings(material, concentrate, heater)
    return round(heat + cool / 2.0, 1)


def timer_wait_seconds(material: str, concentrate: str, heater: str) -> float:
    """Automation wait: UI total (heat+cool) + completion animation + modal buffer."""
    _, _, ui_total = calculate_timings(material, concentrate, heater)
    return round(ui_total + COMPLETION_ANIMATION_SEC + MODAL_RENDER_BUFFER_SEC, 1)


def timer_timings(material: str, concentrate: str, heater: str) -> TimerTimings:
    heat, cool, total = calculate_timings(material, concentrate, heater)
    return TimerTimings(
        heat=heat,
        cool=cool,
        total=total,
        wait_seconds=timer_wait_seconds(material, concentrate, heater),
    )


def all_combo_waits() -> list[tuple[str, str, str, TimerTimings]]:
    out: list[tuple[str, str, str, TimerTimings]] = []
    for material, concentrate, heater in product(MATERIALS, CONCENTRATES, HEATERS):
        out.append((material, concentrate, heater, timer_timings(material, concentrate, heater)))
    return out


def timer_wait_range() -> tuple[float, float, tuple[str, str, str], tuple[str, str, str]]:
    """Return (min_wait, max_wait, min_combo, max_combo)."""
    combos = all_combo_waits()
    min_row = min(combos, key=lambda row: row[3].wait_seconds)
    max_row = max(combos, key=lambda row: row[3].wait_seconds)
    return (
        min_row[3].wait_seconds,
        max_row[3].wait_seconds,
        (min_row[0], min_row[1], min_row[2]),
        (max_row[0], max_row[1], max_row[2]),
    )
