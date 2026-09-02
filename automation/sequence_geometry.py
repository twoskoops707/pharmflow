"""
Sequence tap/swipe coordinates are authored against a design baseline resolution.
At runtime, ``dashboard.run_sequence_step`` scales x/y to the device's ``wm size``
(see ``SEQUENCE_BASE_W`` / ``SEQUENCE_BASE_H`` and per-step ``base_w`` / ``base_h``).

MuMu / narrow portrait sequences in this repo use **900×1600**; omitting
``base_w`` / ``base_h`` on a step uses that default. Override globally with
``CPHARM_SEQUENCE_BASE_W`` / ``CPHARM_SEQUENCE_BASE_H`` if needed.

getdabflow landing flows often insert **preflight** taps before the hero tap
``(658, 755)``: bottom-strip consent ~``(450, 1488)`` then modal-age band
~``(450, 1040)``, each step tagged with the same baseline so scaling matches
the funnel steps (see ``close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__hdd71d4.json``).
"""

from __future__ import annotations

import os
import re
from typing import Any


def _int_env(name: str, default: int) -> int:
    try:
        v = int(os.environ.get(name, str(default)))
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


SEQUENCE_BASE_W = _int_env("CPHARM_SEQUENCE_BASE_W", 900)
SEQUENCE_BASE_H = _int_env("CPHARM_SEQUENCE_BASE_H", 1600)


def parse_wm_size_output(raw: str) -> tuple[int, int] | None:
    """Parse ``adb shell wm size`` stdout.

    Prefers **Override size** (logical size used for input) when present, else
    **Physical size**, else the first ``WxH`` token pair on any line.
    """
    if not (raw or "").strip():
        return None
    override: tuple[int, int] | None = None
    physical: tuple[int, int] | None = None
    line_re = re.compile(
        r"(?P<label>Physical|Override|Display)\s+size:\s*(?P<w>\d+)\s*[xX]\s*(?P<h>\d+)",
        re.IGNORECASE,
    )
    for line in raw.splitlines():
        m = line_re.search(line.strip())
        if not m:
            continue
        w, h = int(m.group("w")), int(m.group("h"))
        if w <= 0 or h <= 0:
            continue
        lab = m.group("label").lower()
        if lab == "override":
            override = (w, h)
        else:
            physical = (w, h)
    if override is not None:
        return override
    if physical is not None:
        return physical
    generic = re.compile(r"\b(\d{2,5})\s*[xX]\s*(\d{2,5})\b")
    for line in raw.splitlines():
        m = generic.search(line)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            if w > 0 and h > 0:
                return w, h
    return None


def baseline_from_step(step: dict[str, Any]) -> tuple[int, int]:
    """Return (base_w, base_h) for scaling this step; falls back to global baseline."""
    bw = step.get("base_w")
    bh = step.get("base_h")
    if bw is None or bh is None:
        return SEQUENCE_BASE_W, SEQUENCE_BASE_H
    try:
        ibw = int(bw)
        ibh = int(bh)
    except (TypeError, ValueError):
        return SEQUENCE_BASE_W, SEQUENCE_BASE_H
    if ibw <= 0 or ibh <= 0:
        return SEQUENCE_BASE_W, SEQUENCE_BASE_H
    return ibw, ibh


def normalize_step_baseline(step: dict[str, Any]) -> tuple[int, int]:
    """Coerce and persist valid ``base_w``/``base_h`` fields onto a step."""
    bw, bh = baseline_from_step(step)
    step["base_w"] = bw
    step["base_h"] = bh
    return bw, bh


def scale_point(
    x: int,
    y: int,
    phys_w: int,
    phys_h: int,
    base_w: int,
    base_h: int,
) -> tuple[int, int]:
    """Map (x, y) from baseline resolution to physical: independent sx, sy (portrait UI)."""
    if base_w <= 0 or base_h <= 0:
        return max(0, x), max(0, y)
    if phys_w == base_w and phys_h == base_h:
        return max(0, x), max(0, y)
    nx = int(round(x * phys_w / base_w))
    ny = int(round(y * phys_h / base_h))
    return max(0, nx), max(0, ny)



def baseline_y_to_screen_y(
    y: int,
    *,
    phys_h: int,
    base_h: int,
    wv_top: int,
) -> int:
    """Map authored baseline page Y to ADB screen Y (MuMu/DabFlow: add WebView chrome inset only)."""
    _ = (phys_h, base_h)  # reserved for future scaled baselines
    return max(0, y + wv_top)

def _smoke() -> None:
    assert parse_wm_size_output("Physical size: 1080x2340\n") == (1080, 2340)
    assert parse_wm_size_output("Display size: 1080x2400\n") == (1080, 2400)
    assert parse_wm_size_output("Physical size: 1440 x 2560\nOverride size: 1080 x 1920\n") == (
        1080,
        1920,
    )
    assert scale_point(450, 800, 2160, 4680, 900, 1600) == (1080, 2340)
    assert scale_point(100, 200, 1080, 2340, 900, 1600) == (120, 292)
    assert scale_point(100, 200, 1080, 2340, 1080, 2340) == (100, 200)
    step = {"type": "tap", "base_w": "1080", "base_h": "1920"}
    assert normalize_step_baseline(step) == (1080, 1920)
    assert step["base_w"] == 1080 and step["base_h"] == 1920
    step_bad = {"type": "tap", "base_w": "0", "base_h": None}
    assert normalize_step_baseline(step_bad) == (SEQUENCE_BASE_W, SEQUENCE_BASE_H)
    print("sequence_geometry smoke OK")


if __name__ == "__main__":
    _smoke()
