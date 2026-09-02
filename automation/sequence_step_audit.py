"""Audit automation sequences for consecutive duplicate step types."""
from __future__ import annotations

from typing import Any

from sequence_normalize import unwrap_sequence_document

_DEDUPE_TYPES = frozenset(
    {
        "wait",
        "tap",
        "swipe",
        "keyevent",
        "open_url",
        "clear_cookies",
        "close_app",
        "rotate_identity",
        "full_reset",
        "launch_app",
    }
)


def _tap_same_coords(a: dict[str, Any], b: dict[str, Any], *, jitter_px: int = 0) -> bool:
    try:
        ax, ay = int(a.get("x", 0)), int(a.get("y", 0))
        bx, by = int(b.get("x", 0)), int(b.get("y", 0))
    except (TypeError, ValueError):
        return False
    if jitter_px <= 0:
        return ax == bx and ay == by
    return abs(ax - bx) <= jitter_px and abs(ay - by) <= jitter_px


def find_consecutive_duplicate_violations(
    steps: list[Any],
    *,
    label: str = "",
    tap_jitter_px: int = 0,
) -> list[str]:
    """Return human-readable violations for back-to-back duplicate command types."""
    prefix = f"{label}: " if label else ""
    violations: list[str] = []
    prev: dict[str, Any] | None = None
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            prev = None
            continue
        t = step.get("type")
        if prev and prev.get("type") == t and t in _DEDUPE_TYPES:
            if t == "swipe":
                prev = step
                continue
            if t == "wait":
                violations.append(
                    f"{prefix}consecutive wait at {idx - 1}/{idx} "
                    f"({prev.get('seconds')}+{step.get('seconds')})"
                )
            elif t == "tap" and _tap_same_coords(prev, step, jitter_px=tap_jitter_px):
                violations.append(
                    f"{prefix}consecutive tap same coords at {idx - 1}/{idx} "
                    f"({step.get('x')},{step.get('y')})"
                )
            elif t != "tap":
                violations.append(f"{prefix}consecutive {t} at {idx - 1}/{idx}")
        prev = step
    return violations


def audit_sequence_document(payload: Any, *, label: str = "", tap_jitter_px: int = 0) -> list[str]:
    steps, _meta = unwrap_sequence_document(payload)
    if not isinstance(steps, list):
        return [f"{label}: steps payload is not a list" if label else "steps payload is not a list"]
    return find_consecutive_duplicate_violations(steps, label=label, tap_jitter_px=tap_jitter_px)
