"""
Humanize recorded automation sequences (JSON array of steps).

Adds bounded random variance to timing fields so playback looks less robotic.
Stored ``tap.jitter`` is left unchanged: ``dashboard.run_sequence_step`` already
applies :func:`human_variation.effective_tap_jitter` and per-tap coordinate noise
when ``CPHARM_HUMAN_VARIATION=1``; baking the same bump into JSON doubled radius.

Respects the same numeric bounds as ``sequence_normalize`` / runtime. When
``automation/`` is importable, spread constants match ``human_variation`` and
output is passed through ``normalize_automation_steps`` for stable typing.

This module is stdlib-only aside from those optional automation passes.
"""

from __future__ import annotations

import json
import os
import random
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

# One-time stderr notes when CPHARM_WIZARD_DEBUG or CPHARM_WIZ_DEBUG is set and optional imports fail.
_seq_debug_keys: set[str] = set()


def _seq_debug_enabled() -> bool:
    for key in ("CPHARM_WIZARD_DEBUG", "CPHARM_WIZ_DEBUG"):
        v = os.environ.get(key, "").strip().lower()
        if v and v not in ("0", "false", "no", "off"):
            return True
    return False


def _seq_debug_once(key: str, exc: BaseException) -> None:
    if not _seq_debug_enabled() or key in _seq_debug_keys:
        return
    _seq_debug_keys.add(key)
    try:
        print(f"[sequence_humanize] {key}: {exc!r}", file=sys.stderr)
    except OSError:
        pass


_MS_CAP = 10000.0
_WAIT_CAP = 300.0
_POST_WAIT_CAP = 120.0


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _as_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _hv_spreads() -> tuple[float, float]:
    """(WAIT_SPREAD, PRE_WAIT_SPREAD) from human_variation when automation is importable."""
    root = Path(__file__).resolve().parent.parent / "automation"
    if not (root / "human_variation.py").is_file():
        return (0.08, 0.06)
    import sys

    ap = str(root)
    if ap not in sys.path:
        sys.path.insert(0, ap)
    try:
        from human_variation import PRE_WAIT_SPREAD, WAIT_SPREAD

        return (float(WAIT_SPREAD), float(PRE_WAIT_SPREAD))
    except (ImportError, ModuleNotFoundError, AttributeError, TypeError, ValueError) as e:
        _seq_debug_once("human_variation spreads", e)
        return (0.08, 0.06)


def _maybe_normalize_steps(steps: list) -> list:
    """Coerce numeric fields when automation package is available."""
    root = Path(__file__).resolve().parent.parent / "automation"
    mod = root / "sequence_normalize.py"
    if not mod.is_file():
        return steps
    import sys

    ap = str(root)
    if ap not in sys.path:
        sys.path.insert(0, ap)
    try:
        from sequence_normalize import normalize_automation_steps

        return normalize_automation_steps(steps)
    except (ImportError, ModuleNotFoundError, AttributeError, TypeError, ValueError) as e:
        _seq_debug_once("normalize_automation_steps", e)
        return steps


def humanize_steps(
    steps: list,
    rng: random.Random | None = None,
    *,
    intensity: float = 1.0,
) -> list:
    """
    Return a deep copy of *steps* with randomized delays (and swipe duration).

    - ``wait.seconds``: scaled with ``human_variation.WAIT_SPREAD`` when importable.
    - ``open_url.post_wait_secs``: same spread as waits when present and > 0.
    - ``tap.pre_wait_ms``: scaled when the key is present (``human_variation.PRE_WAIT_SPREAD``).
    - ``tap.jitter``: unchanged (see module docstring).
    - ``swipe.ms``: ±10%, clamped to [1, 5000]; endpoints unchanged (precision).

    With ``CPHARM_HUMAN_VARIATION=1``, wait and pre_wait_ms scale again at playback.
    """
    if not isinstance(steps, list):
        raise TypeError("steps must be a JSON array")
    r = rng or random.Random()
    w_spread, pre_spread = _hv_spreads()
    scale = max(0.0, min(3.0, float(intensity)))
    w_spread *= scale
    pre_spread *= scale
    out: list = []
    for raw in steps:
        if not isinstance(raw, dict):
            out.append(deepcopy(raw))
            continue
        step = deepcopy(raw)
        # Support both flat prior format ({"type": "wait", "seconds": N}) and
        # Studio format ({"action": "wait", "params": {"seconds": N}}).
        t = str(step.get("type") or step.get("action") or "").strip()
        use_params = isinstance(step.get("params"), dict)
        bag: dict[str, Any] = step["params"] if use_params else step

        if t == "wait":
            base = _as_float(bag.get("seconds", 1), 1.0)
            lo, hi = 1.0 - w_spread, 1.0 + w_spread
            bag["seconds"] = min(_WAIT_CAP, max(0.0, base * r.uniform(lo, hi)))
        elif t in ("open_url", "launch_app"):
            if "post_wait_secs" in bag:
                base = _as_float(bag.get("post_wait_secs", 0), 0.0)
                if base > 0:
                    lo, hi = 1.0 - w_spread, 1.0 + w_spread
                    bag["post_wait_secs"] = min(
                        _POST_WAIT_CAP, max(0.0, base * r.uniform(lo, hi))
                    )
        elif t == "tap":
            if "pre_wait_ms" in bag:
                pw = _as_float(bag.get("pre_wait_ms", 0), 0.0)
                lo, hi = 1.0 - pre_spread, 1.0 + pre_spread
                bag["pre_wait_ms"] = min(_MS_CAP, max(0.0, pw * r.uniform(lo, hi)))
        elif t == "swipe":
            ms = _as_int(bag.get("ms", bag.get("duration_ms", 400)), 400)
            new_ms = max(1, min(5000, int(ms * r.uniform(0.9, 1.1))))
            if "duration_ms" in bag and "ms" not in bag:
                bag["duration_ms"] = new_ms
            else:
                bag["ms"] = new_ms
        out.append(step)
    return _maybe_normalize_steps(out)


def humanize_sequence_file(
    input_path: Path,
    output_path: Path,
    *,
    seed: int | None = None,
) -> dict[str, Any]:
    """
    Read JSON array from *input_path*, humanize, write *output_path* (UTF-8).

    Returns a small stats dict: step count, paths, seed used.
    """
    text = input_path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("root JSON value must be an array of steps")
    rng = random.Random(seed) if seed is not None else random.Random()
    human = humanize_steps(data, rng)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(human, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "steps": len(human),
        "input": str(input_path),
        "output": str(output_path),
        "seed": seed,
    }
