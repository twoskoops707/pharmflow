#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import itertools
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
SEQUENCE_DIR = Path(__file__).resolve().parent
DOC_PATH = ROOT / "docs" / "HOME_COMBO_MATRIX.md"
RENAME_MAP_PATH = ROOT / "automation" / "recordings" / "_sequence_rename_basename_map.json"

WAIT_MAX = 300.0
JITTER_MAX = 120
PRE_WAIT_MAX = 10000.0
SWIPE_MS_MAX = 5000


def _home_combo_rename_map() -> dict[str, str]:
    raw = json.loads(RENAME_MAP_PATH.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for old, new in raw.items():
        if old.startswith("sequence_home_combo_v2_") and new.endswith(".json"):
            out[old] = new
    return out


def _rng_for_combo(
    entry: str,
    ad_path: str,
    footer: str,
    hero: str,
    bottom: str,
    timer: str,
    post_timer_ad: str,
    branch: str,
) -> random.Random:
    key = (
        f"{entry}|{ad_path}|{footer}|{hero}|{bottom}|{timer}|"
        f"{post_timer_ad}|{branch}|home-combo-snowflake-v1"
    )
    seed = int(hashlib.sha256(key.encode()).hexdigest()[:16], 16)
    return random.Random(seed)


def _human_wait(rng: random.Random, mean: float, sigma: float, floor: float) -> dict[str, Any]:
    secs = max(floor, min(WAIT_MAX, rng.gauss(mean, sigma)))
    return {"type": "wait", "seconds": round(secs, 3)}


def _human_tap(
    rng: random.Random,
    x: int,
    y: int,
    *,
    jitter_mean: float = 18.0,
    pre_mean: float = 380.0,
    retries: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    jitter = int(min(JITTER_MAX, max(8, round(rng.gauss(jitter_mean, 4.0)))))
    pre = float(min(PRE_WAIT_MAX, max(120.0, rng.gauss(pre_mean, 55.0))))
    r = retries if retries is not None else rng.choice([2, 2, 3, 3, 4])
    return {
        "type": "tap",
        "x": x + rng.randint(-3, 3),
        "y": y + rng.randint(-3, 3),
        "base_w": 900,
        "base_h": 1600,
        "retries": r,
        "jitter": jitter,
        "pre_wait_ms": pre,
        **extra,
    }


def _human_swipe(
    rng: random.Random,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    ms_mean: float,
) -> dict[str, Any]:
    ms = int(min(SWIPE_MS_MAX, max(280, rng.gauss(ms_mean, ms_mean * 0.12))))
    return {
        "type": "swipe",
        "x1": x1 + rng.randint(-10, 10),
        "y1": y1 + rng.randint(-12, 12),
        "x2": x2 + rng.randint(-10, 10),
        "y2": y2 + rng.randint(-12, 12),
        "ms": ms,
        "base_w": 900,
        "base_h": 1600,
    }


@dataclass(frozen=True)
class Option:
    key: str
    label: str


ENTRY_OPTIONS = (
    Option("direct", "Direct getdabflow landing"),
    Option("google_home", "Google homepage search then result"),
)
AD_PATH_OPTIONS = (
    Option("off", "No ad click path"),
    Option("on", "Include ad path click before home actions"),
)
FOOTER_OPTIONS = (
    Option("left", "Left footer anchor"),
    Option("center", "Center footer anchor"),
    Option("right", "Right footer anchor"),
)
HERO_OPTIONS = (
    Option("off", "No extra hero-top retap"),
    Option("on", "Include hero-top retap"),
)
BOTTOM_OPTIONS = (
    Option("center", "Center bottom strip tap"),
    Option("right", "Right bottom strip tap"),
    Option("left", "Left bottom strip tap"),
)
TIMER_OPTIONS = (
    Option("single96", "Single 96s timer then BACK"),
    Option("stacked", "Stacked 96+102+88 timer block"),
)
POST_TIMER_AD_OPTIONS = (
    Option("off", "No post-timer ad click before branch"),
    Option("on", "Click bottom-page ad before branch"),
)
BRANCH_OPTIONS = (
    Option("glass_art", "Go to glass art tab"),
    Option("stats", "Go to stats tab"),
    Option("settings", "Go to settings tab"),
    Option("timer_reset", "Tap reset button on timer screen"),
)

FOOTER_COORDS = {
    "left": (128, 1455),
    "center": (450, 1455),
    "right": (772, 1455),
}
BOTTOM_COORDS = {
    "center": (455, 1488),
    "right": (648, 1492),
    "left": (162, 1458),
}
BRANCH_COORDS = {
    "glass_art": (162, 1458),
    "stats": (450, 1455),
    "settings": (772, 1455),
    "timer_reset": (455, 660),
}


def _age_yes_tap(rng: random.Random) -> dict[str, Any]:
    return _human_tap(
        rng,
        359,
        912,
        jitter_mean=6.0,
        pre_mean=750.0,
        retries=5,
        age_verification=True,
        checkpoint="age_verification",
    )


def _entry_block(rng: random.Random, entry: str) -> list[dict[str, Any]]:
    if entry == "direct":
        return [
            {"type": "close_app"},
            _human_wait(rng, rng.gauss(0.62, 0.08), 0.04, 0.45),
            {
                "type": "open_url",
                "url": "https://getdabflow.app",
                "post_wait_secs": round(rng.uniform(5.2, 6.8), 2),
            },
            _human_wait(rng, rng.gauss(7.8, 0.55), 0.25, 6.2),
            _age_yes_tap(rng),
            _human_wait(rng, rng.gauss(1.22, 0.12), 0.06, 0.95),
        ]
    if entry == "google_home":
        return [
            {"type": "close_app"},
            _human_wait(rng, rng.gauss(0.62, 0.08), 0.04, 0.45),
            {
                "type": "open_url",
                "url": "https://www.google.com",
                "post_wait_secs": round(rng.uniform(4.2, 5.6), 2),
            },
            _human_wait(rng, rng.gauss(4.05, 0.35), 0.15, 3.2),
            _human_tap(rng, 450, 320, jitter_mean=18.0, pre_mean=400.0),
            _human_wait(rng, rng.gauss(1.18, 0.1), 0.05, 0.9),
            {"type": "type_text", "text": "getdabflow.app"},
            _human_wait(rng, rng.gauss(0.82, 0.08), 0.04, 0.6),
            {"type": "keyevent", "key": "66"},
            _human_wait(rng, rng.gauss(5.55, 0.45), 0.2, 4.5),
            _human_tap(rng, 450, 520, jitter_mean=22.0, pre_mean=500.0),
            _human_wait(rng, rng.gauss(6.05, 0.5), 0.25, 5.0),
            _age_yes_tap(rng),
            _human_wait(rng, rng.gauss(1.22, 0.12), 0.06, 0.95),
        ]
    raise ValueError(f"unsupported entry={entry}")


def _home_block(rng: random.Random, footer: str, hero: str, bottom: str) -> list[dict[str, Any]]:
    footer_x, footer_y = FOOTER_COORDS[footer]
    bottom_x, bottom_y = BOTTOM_COORDS[bottom]
    steps = [
        _human_tap(rng, 658, 755, jitter_mean=14.0, pre_mean=500.0),
        _human_wait(rng, rng.gauss(2.62, 0.22), 0.12, 2.0),
        _human_tap(rng, footer_x, footer_y, jitter_mean=18.0, pre_mean=380.0),
        _human_wait(rng, rng.gauss(2.18, 0.18), 0.1, 1.75),
    ]
    if hero == "on":
        steps.extend(
            [
                _human_tap(rng, 450, 420, jitter_mean=16.0, pre_mean=360.0),
                _human_wait(rng, rng.gauss(2.08, 0.16), 0.1, 1.65),
            ]
        )
    steps.extend(
        [
            _human_tap(rng, bottom_x, bottom_y, jitter_mean=32.0, pre_mean=460.0),
            _human_wait(rng, rng.gauss(5.82, 0.45), 0.3, 4.8),
        ]
    )
    return steps


def _ad_path_block(rng: random.Random, ad_path: str) -> list[dict[str, Any]]:
    if ad_path == "off":
        return []
    if ad_path == "on":
        return [
            _human_tap(rng, 450, 1040, jitter_mean=20.0, pre_mean=280.0),
            _human_wait(rng, rng.gauss(1.18, 0.12), 0.06, 0.9),
        ]
    raise ValueError(f"unsupported ad_path={ad_path}")


def _timer_lead_in(rng: random.Random) -> list[dict[str, Any]]:
    blocks: list[tuple[tuple[int, int, int, int, float], float | None]] = [
        ((432, 1188, 448, 668, 1100.0), 1.9),
        ((366, 1148, 382, 670, 980.0), 1.8),
        ((514, 1108, 498, 642, 1050.0), 2.2),
        ((446, 1202, 458, 658, 1500.0), 1.8),
    ]
    steps: list[dict[str, Any]] = []
    for i, (spec, wait_mean) in enumerate(blocks):
        x1, y1, x2, y2, ms = spec
        steps.append(_human_swipe(rng, x1, y1, x2, y2, ms))
        if i == 2:
            steps.append({"type": "keyevent", "key": "4"})
            steps.append(_human_wait(rng, rng.gauss(2.4, 0.18), 0.1, 1.85))
        elif wait_mean is not None:
            steps.append(_human_wait(rng, rng.gauss(wait_mean, wait_mean * 0.08), 0.1, wait_mean * 0.75))
    return steps


def _timer_block(rng: random.Random, timer: str) -> list[dict[str, Any]]:
    if timer == "single96":
        return [
            _human_tap(rng, 450, 705, jitter_mean=20.0, pre_mean=380.0),
            {"type": "wait", "seconds": 100.0},
            {"type": "keyevent", "key": "4"},
            _human_wait(rng, rng.gauss(2.05, 0.15), 0.08, 1.6),
        ]
    if timer == "stacked":
        return [
            _human_tap(rng, 450, 705, jitter_mean=20.0, pre_mean=380.0),
            {"type": "wait", "seconds": 305.0},
            _human_tap(rng, 455, 660, jitter_mean=18.0, pre_mean=350.0),
            _human_wait(rng, rng.gauss(2.05, 0.15), 0.08, 1.6),
        ]
    raise ValueError(f"unsupported timer={timer}")


def _post_timer_ad_block(rng: random.Random, post_timer_ad: str) -> list[dict[str, Any]]:
    if post_timer_ad == "off":
        return []
    if post_timer_ad == "on":
        return [
            _human_tap(rng, 648, 1492, jitter_mean=28.0, pre_mean=420.0),
            _human_wait(rng, rng.gauss(2.05, 0.15), 0.08, 1.6),
        ]
    raise ValueError(f"unsupported post_timer_ad={post_timer_ad}")


def _post_timer_branch_block(rng: random.Random, branch: str) -> list[dict[str, Any]]:
    x, y = BRANCH_COORDS[branch]
    if branch == "timer_reset":
        return [
            _human_tap(rng, x, y, jitter_mean=16.0, pre_mean=320.0),
            _human_wait(rng, rng.gauss(2.05, 0.15), 0.08, 1.6),
            {"type": "keyevent", "key": "4"},
            _human_wait(rng, rng.gauss(1.62, 0.12), 0.08, 1.25),
        ]
    return [
        _human_tap(rng, x, y, jitter_mean=18.0, pre_mean=360.0),
        _human_wait(rng, rng.gauss(2.05, 0.15), 0.08, 1.6),
    ]


def _identity_tail(rng: random.Random) -> list[dict[str, Any]]:
    return [
        _human_tap(rng, 620, 1395, jitter_mean=22.0, pre_mean=420.0),
        _human_wait(rng, rng.gauss(3.05, 0.25), 0.15, 2.4),
        _human_swipe(rng, 450, 1320, 465, 760, 520.0),
        _human_wait(rng, rng.gauss(2.05, 0.15), 0.08, 1.6),
        {"type": "clear_cookies"},
        _human_wait(rng, rng.gauss(1.12, 0.1), 0.06, 0.85),
        {"type": "close_app"},
        _human_wait(rng, rng.gauss(1.62, 0.12), 0.08, 1.25),
        {"type": "rotate_identity"},
        _human_wait(rng, rng.gauss(2.05, 0.15), 0.08, 1.6),
        {"type": "full_reset"},
    ]


def build_sequence(
    entry: str,
    ad_path: str,
    footer: str,
    hero: str,
    bottom: str,
    timer: str,
    post_timer_ad: str,
    branch: str,
    *,
    rng: random.Random | None = None,
) -> list[dict[str, Any]]:
    if rng is None:
        rng = _rng_for_combo(entry, ad_path, footer, hero, bottom, timer, post_timer_ad, branch)
    return (
        _entry_block(rng, entry)
        + _ad_path_block(rng, ad_path)
        + _home_block(rng, footer, hero, bottom)
        + _timer_lead_in(rng)
        + _timer_block(rng, timer)
        + _post_timer_ad_block(rng, post_timer_ad)
        + _post_timer_branch_block(rng, branch)
        + _identity_tail(rng)
    )


def filename_for_combo(
    entry: str,
    ad_path: str,
    footer: str,
    hero: str,
    bottom: str,
    timer: str,
    post_timer_ad: str,
    branch: str,
) -> str:
    return (
        "sequence_home_combo_v2_"
        f"entry-{entry}_"
        f"ad-{ad_path}_"
        f"footer-{footer}_"
        f"hero-{hero}_"
        f"bottom-{bottom}_"
        f"timer-{timer}_"
        f"postad-{post_timer_ad}_"
        f"branch-{branch}.json"
    )


def validate_sequence(seq: list[dict[str, Any]], *, path_hint: str) -> None:
    if len(seq) < 3:
        raise ValueError(f"{path_hint}: sequence too short")
    end_types = [s.get("type") for s in seq[-3:]]
    if end_types != ["rotate_identity", "wait", "full_reset"]:
        raise ValueError(f"{path_hint}: ending must be rotate_identity -> wait -> full_reset")
    for i in range(1, len(seq)):
        prev = seq[i - 1]
        cur = seq[i]
        if prev.get("type") == "wait" and cur.get("type") == "wait":
            if float(prev.get("seconds", -1)) == float(cur.get("seconds", -1)):
                raise ValueError(
                    f"{path_hint}: redundant consecutive waits at indexes {i-1},{i} "
                    f"(seconds={prev.get('seconds')})"
                )


def _write_json_with_retry(path: Path, payload: list[dict[str, Any]]) -> None:
    body = json.dumps(payload, indent=2) + "\n"
    last_exc: OSError | None = None
    for _ in range(8):
        try:
            path.write_text(body, encoding="utf-8")
            return
        except OSError as exc:
            last_exc = exc
            time.sleep(0.15)
    raise OSError(f"failed writing {path}: {last_exc}")


def write_sequences() -> list[tuple[str, str, str, str, str, str, str, str, str]]:
    rename_map = _home_combo_rename_map()
    combos: list[tuple[str, str, str, str, str, str, str, str, str]] = []
    for entry, ad_path, footer, hero, bottom, timer, post_timer_ad, branch in itertools.product(
        ENTRY_OPTIONS,
        AD_PATH_OPTIONS,
        FOOTER_OPTIONS,
        HERO_OPTIONS,
        BOTTOM_OPTIONS,
        TIMER_OPTIONS,
        POST_TIMER_AD_OPTIONS,
        BRANCH_OPTIONS,
    ):
        seq = build_sequence(
            entry.key,
            ad_path.key,
            footer.key,
            hero.key,
            bottom.key,
            timer.key,
            post_timer_ad.key,
            branch.key,
        )
        filename = filename_for_combo(
            entry.key,
            ad_path.key,
            footer.key,
            hero.key,
            bottom.key,
            timer.key,
            post_timer_ad.key,
            branch.key,
        )
        validate_sequence(seq, path_hint=filename)
        disk_name = rename_map.get(filename)
        if not disk_name:
            raise KeyError(f"{filename}: missing from {RENAME_MAP_PATH.name}")
        out_path = SEQUENCE_DIR / disk_name
        _write_json_with_retry(out_path, seq)
        combos.append(
            (
                entry.key,
                ad_path.key,
                footer.key,
                hero.key,
                bottom.key,
                timer.key,
                post_timer_ad.key,
                branch.key,
                disk_name,
            )
        )
    return combos


def write_docs(combos: list[tuple[str, str, str, str, str, str, str, str, str]]) -> None:
    lines: list[str] = []
    lines.append("# Home Combo V2 Sequence Matrix")
    lines.append("")
    lines.append("Generated by `automation/recordings/sequences/generate_home_combo_sequences.py`.")
    lines.append("")
    lines.append("## Canonical combination schema")
    lines.append("")
    lines.append("- `entry`: `direct` | `google_home`")
    lines.append("- `ad`: `off` | `on`")
    lines.append("- `footer`: `left` | `center` | `right`")
    lines.append("- `hero`: `off` | `on`")
    lines.append("- `bottom`: `center` | `right` | `left`")
    lines.append("- `timer`: `single96` | `stacked`")
    lines.append("- `postad`: `off` | `on`")
    lines.append("- `branch`: `glass_art` | `stats` | `settings` | `timer_reset`")
    lines.append("")
    lines.append(
        "- Filename pattern: "
        "`sequence_home_combo_v2_entry-<entry>_ad-<ad>_footer-<footer>_hero-<hero>_bottom-<bottom>_timer-<timer>_postad-<postad>_branch-<branch>.json`"
    )
    lines.append("")
    lines.append("## Humanization")
    lines.append("")
    lines.append("- Each combo uses a stable seeded RNG (`home-combo-snowflake-v1`).")
    lines.append("- Micro-waits, tap jitter, and swipe ms vary per file; timer long-waits stay exact.")
    lines.append("")
    lines.append("## Action dictionary")
    lines.append("")
    lines.append("- `open_url`: Launch URL using Android VIEW intent fallback chain.")
    lines.append("- `tap`: Scaled coordinate tap (`base_w`/`base_h`) with retry+jitter.")
    lines.append("- `swipe`: Scaled coordinate drag for viewport navigation.")
    lines.append("- `wait`: Explicit timing gate for UI/network stabilization.")
    lines.append("- `keyevent`: Android hardware key (`4` BACK, `66` ENTER).")
    lines.append("- `type_text`: Send text to focused input.")
    lines.append("- `clear_cookies`: Browser session cleanup (`pm clear` + force-stop fallback).")
    lines.append("- `close_app`: Force-stop target app package.")
    lines.append("- `rotate_identity`: Tor circuit/proxy rotate (IP change).")
    lines.append("- `full_reset`: Full identity reset (IP + Android ID + cleanup).")
    lines.append("")
    lines.append("## Rationale by sequence block")
    lines.append("")
    lines.append("- Entry block: controls landing source realism (`direct` vs `google_home`).")
    lines.append("- Home choice block: parameterizes footer/hero/bottom touch-path choices.")
    lines.append("- Timer lead-in block: normalizes scroll/context before timer decisions.")
    lines.append("- Timer block: isolates long-wait behavior into reusable policy options.")
    lines.append("- Identity tail block: enforces explicit IP+ID change at sequence end.")
    lines.append("")
    lines.append(f"## Master matrix ({len(combos)} sequences)")
    lines.append("")
    lines.append("| entry | ad | footer | hero | bottom | timer | postad | branch | filename |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for entry, ad_path, footer, hero, bottom, timer, post_timer_ad, branch, filename in combos:
        lines.append(
            f"| `{entry}` | `{ad_path}` | `{footer}` | `{hero}` | `{bottom}` | `{timer}` | `{post_timer_ad}` | `{branch}` | `{filename}` |"
        )
    lines.append("")
    lines.append("## Source-model limitations")
    lines.append("")
    lines.append("- Only options observed in existing docs/sequences were used.")
    lines.append("- Matrix intentionally includes timer paths only (`single96`/`stacked`) per production scope.")
    lines.append("- Ad path is represented as an explicit independent dimension (`ad-on`/`ad-off`).")
    lines.append("")
    DOC_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    # Remove stale v2-named files from prior generator runs.
    for stale in SEQUENCE_DIR.glob("sequence_home_combo_v2_*.json"):
        stale.unlink(missing_ok=True)

    combos = write_sequences()
    write_docs(combos)
    print(f"generated {len(combos)} home-combo sequences")
    print(f"docs: {DOC_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
