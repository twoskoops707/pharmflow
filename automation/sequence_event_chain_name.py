"""
Deterministic filesystem basenames for sequence JSON (event-chain style).

See automation/recordings/sequences/NAMING_PATTERN.txt. Uses tap semantics where
coordinates match known combo-matrix anchors (generate_home_combo_sequences.py);
otherwise tap_<xband>_<yband> on the step baseline grid (900×1600-style thirds × quartiles).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse

from sequence_normalize import normalize_automation_steps

# Match automation/recordings/sequences/generate_home_combo_sequences.py anchors (±tol px).
_TOL = 22

_SEMANTIC_TAPS: list[tuple[tuple[int, int], str]] = [
    ((450, 1488), "consent_strip"),
    ((359, 912), "age_modal"),
    ((658, 755), "landing_hero"),
    ((450, 420), "hero_top"),
    ((128, 1455), "footer_left"),
    ((450, 1455), "footer_center"),
    ((772, 1455), "footer_right"),
    ((455, 1488), "bottom_center"),
    ((648, 1492), "bottom_right"),
    ((162, 1458), "bottom_left"),
    ((450, 705), "timer_screen"),
    ((455, 660), "timer_reset_btn"),
    ((620, 1395), "post_timer_nav"),
    ((648, 1492), "post_timer_ad"),
    ((450, 320), "google_search_box"),
    ((450, 520), "google_serp_first"),
]

_SWIPE_UP_EPS = 80  # y2 sufficiently above y1 → swipe up (finger moves up)


def _canonical_json_bytes(steps: list[dict[str, Any]]) -> bytes:
    normalized = normalize_automation_steps(list(steps))
    return json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex_digest(steps: list[dict[str, Any]]) -> str:
    return hashlib.sha256(_canonical_json_bytes(steps)).hexdigest()


def _windows_safe_segment(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*]', "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "x"


def _snap_under_limit(s: str, limit: int) -> str:
    """Truncate at the last ``__`` boundary before ``limit`` (avoid broken tokens)."""
    if limit <= 1:
        return "x"
    if len(s) <= limit:
        return s
    chunk = s[:limit]
    cut = chunk.rfind("__")
    if cut >= max(12, limit // 5):
        return chunk[:cut]
    return chunk.rstrip("_").rstrip("-") or "x"


def _band_xy(x: int, y: int, bw: int, bh: int) -> tuple[str, str]:
    """Thirds horizontally (L/C/R), quartiles vertically (top/umid/lmid/lbot)."""
    if bw <= 0:
        bw = 900
    if bh <= 0:
        bh = 1600
    xt = x / float(bw)
    if xt < 1.0 / 3.0:
        xb = "L"
    elif xt < 2.0 / 3.0:
        xb = "C"
    else:
        xb = "R"
    yt = y / float(bh)
    if yt < 0.25:
        yb = "top"
    elif yt < 0.5:
        yb = "umid"
    elif yt < 0.75:
        yb = "lmid"
    else:
        yb = "lbot"
    return xb, yb


def _nearest_semantic_tap(x: int, y: int, bw: int, bh: int) -> str | None:
    """If (x,y) matches a known anchor at this baseline, return short token."""
    # Scale semantic points if baseline differs from 900×1600 authoring.
    from sequence_geometry import scale_point

    best: tuple[float, str] | None = None
    for (sx, sy), label in _SEMANTIC_TAPS:
        ax, ay = sx, sy
        if bw != 900 or bh != 1600:
            ax, ay = scale_point(sx, sy, bw, bh, 900, 1600)
        d = (x - ax) ** 2 + (y - ay) ** 2
        if d <= _TOL * _TOL and (best is None or d < best[0]):
            best = (d, label)
    return best[1] if best else None


def _wait_token(seconds: float) -> str | None:
    if seconds < 2.25:
        return None  # micro — omitted
    s = float(seconds)
    if 94.0 <= s <= 98.0:
        return "timer96s"
    if s >= 60.0:
        return f"w{int(round(s))}s"
    if s >= 10.0:
        return f"w{int(round(s))}s"
    # shorter but non-micro
    return f"w{int(round(s))}s"


def _host_token(url: str) -> str:
    try:
        net = urlparse(url).netloc or ""
    except Exception:
        net = ""
    net = net.lower().strip()
    if net.startswith("www."):
        net = net[4:]
    host = _windows_safe_segment(net.replace(".", "_"))
    return host or "url"


def _type_text_token(text: str) -> str:
    raw = (text or "").strip().lower()
    if not raw:
        return "type_empty"
    if "getdabflow" in raw or raw.endswith(".app"):
        return "type_query_getdabflow"
    if len(raw) <= 24 and re.match(r"^[a-z0-9._-]+$", raw):
        return "type_" + raw.replace(".", "_")[:24]
    return "type_txt"


def generate_event_chain_basename(steps_in: list[dict[str, Any]], *, max_stem_chars: int = 96) -> str:
    """
    Build event-chain basename without '.json'. Join segments with '__'.
    Truncates deterministically when over max_stem_chars (Windows ~200 with extension).
    """
    steps = [s for s in steps_in if isinstance(s, dict)]
    tokens: list[str] = []

    pending_swipe_up = 0

    def flush_swipes() -> None:
        nonlocal pending_swipe_up
        if pending_swipe_up <= 0:
            return
        if pending_swipe_up == 1:
            tokens.append("su")
        else:
            tokens.append(f"su_x{pending_swipe_up}")
        pending_swipe_up = 0

    for step in steps:
        t = str(step.get("type", "") or "")
        if t == "close_app":
            flush_swipes()
            pkg = str(step.get("package", "") or "")
            # Basename segment kept as ``close_chrome`` for stable hashes; runtime uses whatever ``package`` says.
            if "chrome" in pkg.lower():
                tokens.append("close_chrome")
            else:
                tokens.append("close_app")
        elif t == "open_url":
            flush_swipes()
            url = str(step.get("url", "") or "")
            host = _host_token(url)
            tokens.append(f"open_{host}")
            # post-load dwell folded into next phases per NAMING — omit dedicated token
        elif t == "launch_app":
            flush_swipes()
            pkg = str(step.get("package", "") or "app")
            tokens.append(f"launch_{_windows_safe_segment(pkg.replace('.', '_'))}")
        elif t == "wait":
            flush_swipes()
            try:
                sec = float(step.get("seconds", 0) or 0)
            except (TypeError, ValueError):
                sec = 0.0
            wt = _wait_token(sec)
            if wt:
                tokens.append(wt)
        elif t == "tap":
            flush_swipes()
            try:
                x = int(step.get("x", 0))
                y = int(step.get("y", 0))
            except (TypeError, ValueError):
                x, y = 0, 0
            bw = int(step.get("base_w") or 900)
            bh = int(step.get("base_h") or 1600)
            sem = _nearest_semantic_tap(x, y, bw, bh)
            if sem:
                tokens.append(f"tap_{sem}")
            else:
                xb, yb = _band_xy(x, y, bw, bh)
                tokens.append(f"tap_{xb}_{yb}")
        elif t == "swipe":
            try:
                y1 = int(step.get("y1", 0))
                y2 = int(step.get("y2", 0))
            except (TypeError, ValueError):
                y1, y2 = 0, 0
            # Finger moves up → larger content scroll down
            if y2 < y1 - 12:
                pending_swipe_up += 1
            else:
                flush_swipes()
                tokens.append("swipe")
        elif t == "keyevent":
            flush_swipes()
            key = str(step.get("key", "") or "")
            if key == "4":
                tokens.append("back")
            elif key == "66":
                tokens.append("enter")
            else:
                tokens.append(f"key_{key}")
        elif t == "type_text":
            flush_swipes()
            tokens.append(_type_text_token(str(step.get("text", "") or "")))
        elif t == "clear_cookies":
            flush_swipes()
            tokens.append("clear_cookies")
        elif t == "rotate_identity":
            flush_swipes()
            tokens.append("rotate")
        elif t == "full_reset":
            flush_swipes()
            tokens.append("full_reset")
        else:
            flush_swipes()
            tokens.append(_windows_safe_segment(t or "step"))

    flush_swipes()

    # Compress common cleanup tail for readability (deterministic).
    tail_pat = ("clear_cookies", "close_chrome", "rotate", "full_reset")
    for _ in range(3):
        if len(tokens) >= 4:
            maybe = tuple(tokens[-4:])
            if maybe == tail_pat:
                tokens = tokens[:-4] + ["clear_close_rotate_reset"]
                break

    stem = "__".join(tokens)
    for bad in '<>:"/\\|?*':
        stem = stem.replace(bad, "_")
    if len(stem) <= max_stem_chars:
        return stem

    # Truncate middle: keep head/tail token counts fixed.
    head_n, tail_n = 10, 8
    if len(tokens) <= head_n + tail_n + 1:
        return _snap_under_limit(stem, max_stem_chars)

    head = tokens[:head_n]
    tail = tokens[-tail_n:]
    snip = len(tokens) - head_n - tail_n
    stem2 = "__".join(head) + f"__snip{snip}__" + "__".join(tail)
    if len(stem2) > max_stem_chars:
        stem2 = _snap_under_limit(stem2, max_stem_chars)
    return stem2


def final_basename_for_steps(steps: list[dict[str, Any]], *, collision_hex: str | None = None) -> str:
    """
    collision_hex: first 6 chars of sha256 when disambiguating colliding stems.
    """
    base = generate_event_chain_basename(steps)
    if collision_hex:
        hx = re.sub(r"[^0-9a-f]", "", collision_hex.lower())[:6]
        if len(hx) < 6:
            hx = (hx + "000000")[:6]
        return f"{base}__h{hx}"
    return base
