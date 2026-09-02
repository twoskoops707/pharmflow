"""Humanization engine for MuMu sequence automation."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

# Portrait 900x1600 — never start swipe above this (avoids notification shade).
MIN_SCROLL_Y = 533
# Chrome omnibox / voice-search mic — never idle-tap above this.
MIN_SAFE_TAP_Y = 220
AUTHOR_W = 900
AUTHOR_H = 1600


@dataclass
class HumanizeConfig:
    timing_variation: float = 0.15
    coordinate_tolerance: int = 10
    random_actions: bool = True
    random_action_chance: float = 0.25
    # Flick duration for content scrolls (faster = less stall on tabs).
    scroll_duration_ms: tuple[int, int] = (320, 520)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> HumanizeConfig:
        if not data:
            return cls()
        scroll = data.get("scroll_duration_ms", (320, 520))
        if isinstance(scroll, dict):
            scroll = (int(scroll.get("min", 320)), int(scroll.get("max", 520)))
        return cls(
            timing_variation=float(data.get("timing_variation", 0.15)),
            coordinate_tolerance=int(data.get("coordinate_tolerance", 10)),
            random_actions=bool(data.get("random_actions", True)),
            random_action_chance=float(data.get("random_action_chance", 0.25)),
            scroll_duration_ms=(int(scroll[0]), int(scroll[1])),
        )


def humanize_tap(x: int, y: int, tolerance: int = 10) -> tuple[int, int]:
    return x + random.randint(-tolerance, tolerance), y + random.randint(-tolerance, tolerance)


def humanize_timing(seconds: float, variation: float = 0.15) -> float:
    delta = seconds * variation
    return max(0.1, seconds + random.uniform(-delta, delta))


def resolve_coordinate(value: Any, tolerance: int = 10, humanize: bool = True) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, dict):
        if "base" in value:
            base = int(value["base"])
            tol = int(value.get("tolerance", tolerance))
            return humanize_tap(base, 0, tol)[0] if humanize else base
        if "min" in value and "max" in value:
            return random.randint(int(value["min"]), int(value["max"]))
    raise TypeError(f"Unsupported coordinate value: {value!r}")


def resolve_seconds(value: Any, variation: float = 0.15, humanize: bool = True) -> float:
    if isinstance(value, (int, float)):
        base = float(value)
        return humanize_timing(base, variation) if humanize else base
    if isinstance(value, dict):
        if "min" in value and "max" in value:
            return random.uniform(float(value["min"]), float(value["max"]))
        if "base" in value:
            base = float(value["base"])
            var = float(value.get("variation", variation))
            return humanize_timing(base, var) if humanize else base
    raise TypeError(f"Unsupported seconds value: {value!r}")


def resolve_duration_ms(value: Any, default_range: tuple[int, int] = (1800, 2500)) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        if "min" in value and "max" in value:
            return random.randint(int(value["min"]), int(value["max"]))
        if "base" in value:
            base = int(value["base"])
            tol = int(value.get("tolerance", 200))
            return base + random.randint(-tol, tol)
    lo, hi = default_range
    return random.randint(lo, hi)


def coord_param(
    base_x: int,
    base_y: int,
    tolerance: int = 10,
    *,
    humanized: bool = True,
) -> dict[str, Any]:
    if humanized:
        return {
            "x": {"base": base_x, "tolerance": tolerance},
            "y": {"base": base_y, "tolerance": tolerance},
        }
    return {"x": base_x, "y": base_y}


def wait_param(
    seconds: float,
    variation: float = 0.15,
    *,
    humanized: bool = True,
) -> dict[str, float | dict[str, float]]:
    if humanized:
        delta = seconds * variation
        return {"seconds": {"min": max(0.1, seconds - delta), "max": seconds + delta}}
    return {"seconds": seconds}


def scroll_swipe_params(
    seed: int,
    tolerance: int = 10,
    *,
    duration_ms: tuple[int, int] | None = None,
    long: bool = False,
) -> dict[str, Any]:
    """Finger-up swipe — start >= 1/3 screen height (533px on 1600); never from status bar.

    long=True: long flick (~700–900px) to reach tab bottoms faster.
    """
    x1 = 400 + (seed % 101)
    x2 = x1 + ((seed >> 3) % 21) - 10
    if long:
        # Bottom of content area → upper third (big travel per flick).
        y1 = 1180 + (seed % 140)  # ~1180–1320
        y2 = 380 + (seed % 120)  # ~380–500
        lo, hi = duration_ms or (320, 520)
    else:
        y1 = MIN_SCROLL_Y + 350 + (seed % 280)
        delta = 280 + (seed % 220)
        y2 = max(MIN_SCROLL_Y + 80, y1 - delta)
        lo, hi = duration_ms or (400, 650)
    if hi < lo:
        lo, hi = hi, lo
    return {
        "x1": {"base": x1, "tolerance": tolerance},
        "y1": {"base": y1, "tolerance": tolerance},
        "x2": {"base": x2, "tolerance": tolerance},
        "y2": {"base": y2, "tolerance": tolerance},
        "duration_ms": {"min": int(lo), "max": int(hi)},
    }


def enforce_scroll_coords(
    x1: int, y1: int, x2: int, y2: int, *, seed: int = 0
) -> tuple[int, int, int, int]:
    """Keep swipe start out of the notification shade; preserve intentional long scrolls."""
    # Only bump y1 when it would pull the status bar (too near the top).
    if y1 < MIN_SCROLL_Y:
        delta = abs(y1 - y2)
        y1 = MIN_SCROLL_Y + 40 + (seed % 40)
        # Keep scroll direction (up = y2 < y1)
        if y2 < y1 - 20:
            y2 = max(MIN_SCROLL_Y // 2, y1 - max(delta, 200))
        elif y2 > y1 + 20:
            y2 = min(1600 - 40, y1 + max(delta, 200))
    return x1, y1, x2, y2


def normalize_swipe_params(params: dict[str, Any]) -> dict[str, Any]:
    """Map legacy x/y swipe keys to x1/y1 and clamp y1 into safe scroll zone."""
    out = dict(params)
    if "x1" not in out and "x" in out:
        out["x1"] = out["x"]
    if "y1" not in out and "y" in out:
        out["y1"] = out["y"]
    y1 = out.get("y1")
    if isinstance(y1, dict) and int(y1.get("base", 0)) < MIN_SCROLL_Y:
        y1["base"] = max(MIN_SCROLL_Y + 40, int(y1.get("base", MIN_SCROLL_Y)))
    elif isinstance(y1, int) and y1 < MIN_SCROLL_Y:
        out["y1"] = MIN_SCROLL_Y + 40
    return out


def maybe_random_actions(
    steps: list[dict[str, Any]],
    idle_zones: list[dict[str, int]],
    config: HumanizeConfig,
    *,
    seed: int = 0,
) -> list[dict[str, Any]]:
    if not config.random_actions or not idle_zones:
        return steps
    if random.random() > config.random_action_chance:
        return steps

    # Never tap Chrome omnibox / Google voice-search mic zone
    safe_zones = [z for z in idle_zones if int(z.get("y", 0)) >= MIN_SAFE_TAP_Y]
    if not safe_zones:
        return steps
    zone = random.choice(safe_zones)
    tol = config.coordinate_tolerance
    injected: list[dict[str, Any]] = []
    # Prefer wait/scroll over tap — taps near chrome UI open voice search help
    action_kind = random.choice(["wait", "scroll", "wait", "tap"])
    if action_kind == "tap":
        injected.append(
            {
                "action": "tap",
                "params": coord_param(zone["x"], zone["y"], tol),
                "description": "Random idle tap (humanization)",
            }
        )
    elif action_kind == "wait":
        injected.append(
            {
                "action": "wait",
                "params": wait_param(random.uniform(0.5, 2.0), config.timing_variation),
                "description": "Random pause (humanization)",
            }
        )
    else:
        injected.append(
            {
                "action": "swipe",
                "params": scroll_swipe_params(seed + random.randint(0, 9999), tol),
                "description": "Scroll page (humanization)",
            }
        )

    if len(steps) < 4:
        return steps + injected
    insert_at = random.randint(2, len(steps) - 2)
    return steps[:insert_at] + injected + steps[insert_at:]
