"""
Normalize automation step lists for CPharm.

MuMu Player ARM keeps ``default_sequence*.json`` under the install ``manager\\``
folder. Those files use the same ``type`` values as CPharm (``open_url``, ``tap``,
``wait``, ``swipe``, ``close_app``, ``rotate_identity``, …). MuMu often stores
``wait.seconds`` as a string (``"3.5"``, ``".75"``); the runtime already coerces
via ``float()``, but normalizing produces stable JSON when saving from the wizard
or API.

CPharm-only optional fields on ``tap`` (``retries``, ``jitter``, ``pre_wait_ms``)
may be absent in MuMu exports — ``dashboard.run_sequence_step`` applies defaults.
Optional ``base_w`` / ``base_h`` on ``tap`` / ``swipe`` select the resolution those
coordinates were authored for (default ``sequence_geometry.SEQUENCE_BASE_W/H``,
900×1600). Optional ``open_url.browser_component`` (``package/activity``) forces a
specific browser; omit for a generic device ``VIEW`` intent.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from sequence_geometry import normalize_step_baseline

# human_pace_v6: instant pre-site + post-browser; humanize on-site only
FAST_TIMING_PHASES = frozenset({"pre_site_fast", "post_browser_fast"})


def step_timing_phase(step: dict) -> str | None:
    """Return ``pre_site_fast`` / ``post_browser_fast`` when the step opts out of human padding."""
    if not isinstance(step, dict):
        return None
    raw = step.get("phase") or step.get("timing_phase")
    if raw in FAST_TIMING_PHASES:
        return str(raw)
    return None


def step_is_fast_phase(step: dict) -> bool:
    return step_timing_phase(step) is not None


def step_is_timer_complete_wait(step: dict) -> bool:
    """True for the full DabFlow timer wait (must never be shortened by human variance)."""
    if not isinstance(step, dict) or step.get("type") != "wait":
        return False
    return str(step.get("checkpoint", "")).strip().lower() == "timer_complete"


def unwrap_sequence_document(data: Any) -> tuple[list[Any], dict[str, Any] | None]:
    """
    Sequence files may be a bare JSON array of steps, or an object::

        {"steps": [...], "label": "optional title", "meta": {...}}

    Returns ``(steps, meta_or_none)``. Legacy array files yield ``meta_or_none=None``.
    """
    if isinstance(data, list):
        return data, None
    if isinstance(data, dict):
        steps = data.get("steps")
        if isinstance(steps, list):
            meta: dict[str, Any] = {}
            lab = data.get("label")
            if isinstance(lab, str) and lab.strip():
                meta["label"] = lab.strip()
            extra = data.get("meta")
            if isinstance(extra, dict):
                meta.update(extra)
            elif extra is not None:
                meta["meta"] = extra
            return steps, (meta or None)
    raise ValueError("expected a JSON array of steps, or an object with a 'steps' array")


def load_sequence_steps_ui(data: Any) -> tuple[list[Any], dict[str, Any] | None]:
    """
    UI-facing loader helper used by wizard/dashboard paths.

    Returns ``(steps, meta_or_none)`` and enforces that the decoded value
    is a valid sequence document (array or wrapper with ``steps`` array).
    """
    steps, meta = unwrap_sequence_document(data)
    if not isinstance(steps, list):
        raise ValueError("file must contain a JSON array of steps or {'steps': [...]} object")
    return steps, meta


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


def _step_dedupe_signature(step: dict) -> tuple | None:
    """Signature for collapsing back-to-back identical non-wait commands."""
    t = step.get("type")
    if t == "tap":
        return (t, step.get("x"), step.get("y"))
    if t == "swipe":
        return (t, step.get("x1"), step.get("y1"), step.get("x2"), step.get("y2"), step.get("ms"))
    if t == "keyevent":
        return (t, str(step.get("key", "")))
    if t == "open_url":
        return (t, str(step.get("url", "")))
    if t in {"clear_cookies", "close_app", "rotate_identity", "full_reset", "launch_app"}:
        return (t,)
    return None


def merge_wait_into_previous(prev: dict, step: dict, *, max_seconds: float = 300.0) -> None:
    """Sum ``seconds`` from ``step`` into ``prev``; preserve ``timer_complete`` and other flags."""
    total = min(
        max_seconds,
        max(0.0, _as_float(prev.get("seconds", 0.0), 0.0))
        + max(0.0, _as_float(step.get("seconds", 0.0), 0.0)),
    )
    prev["seconds"] = round(total, 3)
    if step_is_timer_complete_wait(prev) or step_is_timer_complete_wait(step):
        prev["checkpoint"] = "timer_complete"
    elif step.get("checkpoint") and not prev.get("checkpoint"):
        prev["checkpoint"] = step.get("checkpoint")
    for key in ("phase", "ad_read", "until_session_notes_gone"):
        if step.get(key) is not None and prev.get(key) is None:
            prev[key] = step[key]


def merge_adjacent_wait_step(prev: dict, step: dict, *, max_seconds: float = 300.0) -> bool:
    """If both steps are ``wait``, merge into ``prev``. Return True when merged."""
    if prev.get("type") != "wait" or step.get("type") != "wait":
        return False
    merge_wait_into_previous(prev, step, max_seconds=max_seconds)
    return True


def merge_consecutive_waits(steps: list) -> list:
    """Public wrapper: merge back-to-back ``wait`` steps (sum ``seconds``)."""
    return _merge_consecutive_waits(steps)


def _merge_consecutive_waits(steps: list) -> list:
    """
    Merge back-to-back ``wait`` steps into one (sum ``seconds``).

    Generator humanization (``tab_switch_gap``, scroll pauses, tab dwell) may emit
    several waits in a row; operators and ``verify_sequences`` expect a single wait.
    """
    out: list = []
    for step in steps:
        if (
            out
            and isinstance(step, dict)
            and step.get("type") == "wait"
            and isinstance(out[-1], dict)
            and out[-1].get("type") == "wait"
            and not step_is_timer_complete_wait(out[-1])
            and not step_is_timer_complete_wait(step)
        ):
            merge_wait_into_previous(out[-1], step)
            continue
        out.append(step)
    return out


def _collapse_consecutive_identical_steps(steps: list) -> list:
    """Drop consecutive steps with the same dedupe signature (non-wait only)."""
    out: list = []
    prev_sig: tuple | None = None
    for step in steps:
        if not isinstance(step, dict):
            out.append(step)
            prev_sig = None
            continue
        sig = _step_dedupe_signature(step)
        if sig is not None and sig == prev_sig and out:
            prev_step = out[-1]
            if isinstance(prev_step, dict) and step.get("type") == "tap" and prev_step.get("type") == "tap":
                prev_step["retries"] = max(
                    _as_int(prev_step.get("retries", 1), 1),
                    _as_int(step.get("retries", 1), 1),
                )
            continue
        out.append(step)
        prev_sig = sig if step.get("type") != "wait" else None
    return out


def normalize_automation_steps(steps: list) -> list:
    """Return a new list with coerced numeric fields; unknown step keys are preserved."""
    if not isinstance(steps, list):
        raise TypeError("steps must be a JSON array")
    out: list = []
    for raw in steps:
        if not isinstance(raw, dict):
            out.append(raw)
            continue
        step = deepcopy(raw)
        t = step.get("type", "")
        if t == "wait":
            step["seconds"] = min(max(0.0, _as_float(step.get("seconds", 1), 1.0)), 300.0)
        elif t == "tap":
            step["x"] = max(0, _as_int(step.get("x", 0), 0))
            step["y"] = max(0, _as_int(step.get("y", 0), 0))
            normalize_step_baseline(step)
            if "retries" in step:
                step["retries"] = max(1, min(8, _as_int(step.get("retries", 1), 1)))
            if "jitter" in step:
                step["jitter"] = max(0, min(120, _as_int(step.get("jitter", 0), 0)))
            if "pre_wait_ms" in step:
                step["pre_wait_ms"] = min(max(0.0, _as_float(step.get("pre_wait_ms", 0), 0.0)), 10000.0)
        elif t == "swipe":
            for k in ("x1", "y1", "x2", "y2"):
                step[k] = max(0, _as_int(step.get(k, 0), 0))
            normalize_step_baseline(step)
            step["ms"] = max(1, min(5000, _as_int(step.get("ms", 400), 400)))
        elif t == "open_url":
            bc_raw = step.get("browser_component")
            pkg = str(step.get("package", "")).strip()
            act = str(step.get("activity", "")).strip()
            if not bc_raw and pkg and act:
                if "/" in act:
                    step["browser_component"] = act
                else:
                    step["browser_component"] = f"{pkg}/{act}"
            bc = str(step.get("browser_component", "")).strip()
            if bc and "/" not in bc:
                step.pop("browser_component", None)
            ntab = step.get("new_tab")
            if ntab is None or ntab == "":
                ntab = step.get("create_new_tab")
            if ntab is not None and ntab != "":
                if isinstance(ntab, bool):
                    step["new_tab"] = ntab
                else:
                    step["new_tab"] = str(ntab).strip().lower() in ("1", "true", "yes", "on")
            if "post_wait_secs" in step:
                step["post_wait_secs"] = min(
                    120.0, max(0.0, _as_float(step.get("post_wait_secs", 0), 0.0))
                )
        elif t == "launch_app":
            pkg = str(step.get("package", "")).strip()
            if pkg and re.match(r"^[a-zA-Z][a-zA-Z0-9_.]*$", pkg):
                step["package"] = pkg
            else:
                step.pop("package", None)
            if "post_wait_secs" in step:
                step["post_wait_secs"] = min(
                    120.0, max(0.0, _as_float(step.get("post_wait_secs", 0), 0.0))
                )
        out.append(step)
    out = _merge_consecutive_waits(out)
    out = _collapse_consecutive_identical_steps(out)
    if os.environ.get("CPHARM_SEQUENCE_STRIP_CHROME") == "1":
        from fix_sequences_strip_chrome import strip_chrome_steps_list_in_place

        strip_chrome_steps_list_in_place(out)
    return out


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Normalize a MuMu/CPharm JSON sequence file (array of step objects)."
    )
    p.add_argument("input", type=Path, help="Source JSON file")
    p.add_argument(
        "output",
        nargs="?",
        type=Path,
        help="Output JSON (default: stdout)",
    )
    args = p.parse_args(argv)
    text = args.input.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, list):
        print("Error: root JSON value must be an array.", file=sys.stderr)
        return 1
    normalized = normalize_automation_steps(data)
    out_txt = json.dumps(normalized, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(out_txt, encoding="utf-8")
    else:
        sys.stdout.write(out_txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
