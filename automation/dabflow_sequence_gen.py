"""Generate all DabFlow blueprint sequences (Path1 A-D, Path2, Path3 A-D × ad slots).

Importable from the PharmFlow EXE (bundled under automation/). CLI entry:
  py scripts/generate_dabflow_sequences.py
"""

from __future__ import annotations

import argparse
import json
import shutil
from itertools import permutations, product
from pathlib import Path

from automation.config import (
    BROWSER_CHROMIUM,
    BROWSER_FARMBROWSER,
    REQUIRED_SEQUENCE_VERSION,
)
from automation.dabflow_mapper import load_mapping
from automation.humanize import HumanizeConfig, coord_param, maybe_random_actions, scroll_swipe_params, wait_param

ROOT = Path(__file__).resolve().parents[1]

# Path1/2/3 — FarmBrowser only.
PATH12_BROWSERS: tuple[tuple[str, str, str], ...] = (
    ("farmbrowser", BROWSER_FARMBROWSER, "FarmBrowser"),
)
_CHROMIUM_FAMILY_PKGS = frozenset({BROWSER_FARMBROWSER, "com.farmbrowser.stealth"})

PRESETS = {
    "safe": HumanizeConfig(
        timing_variation=0.08,
        coordinate_tolerance=5,
        random_actions=False,
        random_action_chance=0.0,
        scroll_duration_ms=(360, 560),
    ),
    "moderate": HumanizeConfig(
        timing_variation=0.12,
        coordinate_tolerance=8,
        random_actions=False,
        random_action_chance=0.0,
        scroll_duration_ms=(300, 480),
    ),
    "aggressive": HumanizeConfig(
        timing_variation=0.18,
        coordinate_tolerance=12,
        random_actions=True,
        random_action_chance=0.18,
        scroll_duration_ms=(260, 420),
    ),
}

TAB_SHORT = {"stats": "stats", "glass_art": "glass", "settings": "settings"}


def _step(action: str, params: dict, description: str = "") -> dict:
    return {"action": action, "params": params, "description": description}


def _seeded_scroll(seed: int, hz: HumanizeConfig, description: str, *, long: bool = True) -> dict:
    """Humanized scroll with per-sequence start/stop variance (long=True reaches tab bottom)."""
    return _step(
        "swipe",
        scroll_swipe_params(
            seed,
            hz.coordinate_tolerance,
            duration_ms=hz.scroll_duration_ms,
            long=long,
        ),
        description,
    )


def _scroll_to_bottom(seed: int, hz: HumanizeConfig, label: str, passes: int = 4) -> list[dict]:
    """Scroll down N long flicks. Callers choose depth (do not force a floor of 4)."""
    steps: list[dict] = []
    n = max(1, int(passes))
    for i in range(n):
        steps.append(
            _seeded_scroll(
                seed + i * 97,
                hz,
                f"Scroll to bottom ({label} {i + 1}/{n})",
                long=True,
            )
        )
        steps.append(
            _step(
                "wait",
                {"seconds": {"min": 0.12, "max": 0.28}},
                f"Brief settle after scroll ({label})",
            )
        )
    return steps


def _identity_first(hz: HumanizeConfig, *, browser_pkg: str = BROWSER_CHROMIUM) -> list[dict]:
    """Preamble every sequence — runner ALSO hard-enforces isolation before these steps."""
    var = hz.timing_variation
    return [
        _step(
            "clear_cookies",
            {"package": browser_pkg},
            "Wipe cookies/cache/site data (no carryover)",
        ),
        _step(
            "rotate_identity",
            {},
            "HARD isolation: new Tor exit IP + geo/tz + IMEI + browser identity",
        ),
        _step("wait", wait_param(1.5, var), "Wait after HARD isolation rotate"),
        _step("ensure_fingerprint", {}, "Verify browser headers before browse"),
    ]


def _open_flow(
    mapping,
    hz: HumanizeConfig,
    *,
    browser_pkg: str = BROWSER_CHROMIUM,
    browser_label: str = "Chromium",
) -> list[dict]:
    age = mapping.age_gate_consent()
    tol = hz.coordinate_tolerance
    steps = [
        _step("launch_app", {"package": browser_pkg}, f"Open {browser_label}"),
        _step(
            "wait",
            {"seconds": {"min": 0.5, "max": 1.0}},
            f"Settle after {browser_label} open",
        ),
    ]
    if browser_pkg in _CHROMIUM_FAMILY_PKGS:
        steps.append(
            _step(
                "tap",
                coord_param(450, 1127, tol),
                f"{browser_label} Skip / Stay signed out (FRE only)",
            )
        )
    steps.extend(
        [
            _step(
                "open_url",
                {"url": mapping.url},
                f"Open getdabflow.app in {browser_label}",
            ),
            # open_url waits AGE_GATE_LOAD_WAIT_S then taps Yes; this is a safety retap.
            _step("tap", coord_param(age.x, age.y, tol), "Age gate: Yes, I am 21+"),
            _step("wait", {"seconds": {"min": 0.75, "max": 1.2}}, "Wait for home screen"),
        ]
    )
    return steps


def _close_browser(browser_pkg: str, browser_label: str) -> dict:
    return _step(
        "close_app",
        {"package": browser_pkg},
        f"Close {browser_label}",
    )


def _selection_and_start(mapping, material: str, concentrate: str, heater: str, hz: HumanizeConfig, seed: int) -> list[dict]:
    mat = mapping.material_point(material)
    conc = mapping.concentrate_point(concentrate)
    heat = mapping.heater_point(heater)
    start = mapping.timer_start()
    reveal = mapping.start_reveal_scroll()
    tol = hz.coordinate_tolerance
    # Slight per-seq variance on reveal scroll ends
    y1 = reveal["y1"] + ((seed % 7) - 3) * 8
    y2 = reveal["y2"] + ((seed % 5) - 2) * 10
    return [
        _step("tap", coord_param(mat.x, mat.y, tol), f"Select material: {material}"),
        _step("wait", {"seconds": {"min": 0.45, "max": 0.9}}, "Wait after material"),
        _step("tap", coord_param(conc.x, conc.y, tol), f"Select concentrate: {concentrate}"),
        _step("wait", {"seconds": {"min": 0.5, "max": 1.0}}, "Wait after concentrate"),
        _step("tap", coord_param(heat.x, heat.y, tol), f"Select heater: {heater}"),
        _step("wait", {"seconds": {"min": 0.35, "max": 0.75}}, "Wait after heater"),
        _step(
            "swipe",
            {
                "x1": reveal["x1"],
                "y1": y1,
                "x2": reveal["x2"],
                "y2": y2,
                "duration_ms": reveal["duration_ms"] + (seed % 80),
            },
            "Scroll to reveal Start Perfect Dab",
        ),
        _step("wait", {"seconds": {"min": 0.4, "max": 0.8}}, "Settle before Start Perfect Dab"),
        _step("tap", coord_param(start.x, start.y, tol), "Start Perfect Dab timer"),
    ]


def _full_timer_wait() -> list[dict]:
    # Typical heat+cool ~80s; keep tight so session notes are not left up.
    return [
        _step(
            "wait",
            {"seconds": {"min": 78.0, "max": 84.0}},
            "Wait for timer to complete (heat + cool)",
        )
    ]


def _halfway_wait() -> list[dict]:
    return [
        _step(
            "wait",
            {"seconds": {"min": 45.0, "max": 60.0}},
            "Wait ~halfway through timer then exit",
        )
    ]


def _session_notes_skip(mapping, hz: HumanizeConfig) -> list[dict]:
    skip = mapping.session_notes_skip()
    tol = hz.coordinate_tolerance
    return [
        _step("wait", {"seconds": {"min": 0.15, "max": 0.35}}, "Brief wait for session notes"),
        _step("tap", coord_param(skip.x, skip.y, tol), "Session notes Skip"),
        _step("wait", {"seconds": {"min": 0.15, "max": 0.35}}, "Settle after session notes Skip"),
    ]


def _open_tab(mapping, tab: str, hz: HumanizeConfig) -> list[dict]:
    """Open a DabFlow tab then dwell 3–5s so Mantis top creatives can load (evCPM)."""
    pt = mapping.tab_point(tab)
    tol = hz.coordinate_tolerance
    return [
        _step("tap", coord_param(pt.x, pt.y, tol), f"Open tab: {pt.label}"),
        _step("wait", {"seconds": {"min": 3.0, "max": 5.0}}, f"Settle on {tab}"),
    ]


def _ad_click_and_return(mapping, hz: HumanizeConfig, *, x: int, y: int, label: str) -> list[dict]:
    tol = hz.coordinate_tolerance
    age = mapping.age_gate_consent()
    return [
        _step("wait", {"seconds": {"min": 0.6, "max": 1.2}}, f"Wait for ad fill ({label})"),
        _step("tap", coord_param(x, y, tol), f"Tap ad ({label})"),
        _step("wait", {"seconds": {"min": 8.0, "max": 14.0}}, "View ad (scroll dwell)"),
        _step("keyevent", {"code": 4}, "Back from advertiser to DabFlow"),
        _step("wait", {"seconds": {"min": 0.4, "max": 0.8}}, "Settle after returning from ad"),
        _step(
            "tap",
            coord_param(age.x, age.y, tol),
            "Age gate: Yes, I am 21+ (re-entry if shown)",
        ),
        _step("wait", {"seconds": {"min": 0.75, "max": 1.2}}, "Settle after ad re-entry"),
    ]


def _scroll_down(seed: int, hz: HumanizeConfig, label: str, passes: int) -> list[dict]:
    """Scroll down N long flicks — depth varies so different ads land in view."""
    return _scroll_to_bottom(seed, hz, label, passes=max(1, passes))


def _home_ad_flow(mapping, hz: HumanizeConfig, ad_index: int, seed: int) -> list[dict]:
    """Home feed ad — each ordinal uses a *different scroll depth*, not absolute bottom.

    Scrolling every sequence to the bottom then tapping similar Y was hitting the same ad.
    """
    slot = mapping.home_ad_slot(ad_index)
    # Depth ladder: 2 / 4 / 6 / 8 flicks so ordinals reach different Sponsored units.
    passes = int(slot.get("scrolls_before", 2 + ad_index * 2))
    steps: list[dict] = []
    steps.extend(_open_tab(mapping, "home", hz))
    steps.extend(_scroll_down(seed + 11, hz, f"home-ads-{ad_index}", passes=passes))
    # Tap the sponsored unit now in the mid/lower viewport (same screen Y across ordinals).
    x = int(slot["x"]) + ((seed % 9) - 4) * 3
    y = int(slot["y"]) + ((seed % 11) - 5) * 4
    steps.extend(_ad_click_and_return(mapping, hz, x=x, y=y, label=f"home slot {ad_index}"))
    return steps


def _tab_ad_flow(mapping, hz: HumanizeConfig, tab: str, ad_index: int, seed: int) -> list[dict]:
    """Tab ad — scroll to ordinal depth only (do not slam to absolute bottom first)."""
    slot = mapping.tab_ad_slot(tab, ad_index)
    passes = int(slot.get("scrolls_before", 2 + ad_index * 3))
    steps = _scroll_down(seed + 23, hz, f"{tab}-ads-{ad_index}", passes=passes)
    x = int(slot["x"]) + ((seed % 7) - 3) * 3
    y = int(slot["y"]) + ((seed % 9) - 4) * 4
    steps.extend(_ad_click_and_return(mapping, hz, x=x, y=y, label=f"{tab} slot {ad_index}"))
    return steps


def _browse_tabs_flow(
    mapping,
    hz: HumanizeConfig,
    tabs: tuple[str, ...],
    seed: int,
    *,
    ad_tab: str | None = None,
    ad_index: int | None = None,
) -> list[dict]:
    """Browse tabs. Ad tap only when both ad_tab and ad_index are set (Path3 only).

    Path1/2 callers must leave ad_tab/ad_index as None — never inject Tap ad steps.
    """
    steps: list[dict] = []
    for i, tab in enumerate(tabs):
        steps.extend(_open_tab(mapping, tab, hz))
        if ad_tab == tab and ad_index is not None:
            # Path3 only: depth-based scroll + tap (must NOT go to absolute bottom first).
            steps.extend(_tab_ad_flow(mapping, hz, tab, ad_index, seed + 70 + i))
        else:
            # Browse-only tab: scroll fully through content — no ad engage.
            steps.extend(_scroll_to_bottom(seed + 40 + i * 13, hz, tab, passes=5))
    return steps


def build_sequence(
    *,
    name: str,
    material: str,
    concentrate: str,
    heater: str,
    seq_type: str,
    path_id: str,
    mapping,
    hz: HumanizeConfig,
    tail: list[dict],
    inject_random: bool = True,
    extra_meta: dict | None = None,
    browser_pkg: str = BROWSER_CHROMIUM,
    browser_label: str = "Chromium",
    browser_tag: str = "chromium",
) -> dict:
    seed = hash(name) & 0xFFFFFFFF
    steps = (
        _identity_first(hz, browser_pkg=browser_pkg)
        + _open_flow(mapping, hz, browser_pkg=browser_pkg, browser_label=browser_label)
        + _selection_and_start(mapping, material, concentrate, heater, hz, seed)
        + tail
    )
    idle = mapping.screens.get("idle_tap_zones", [])
    if inject_random:
        steps = maybe_random_actions(steps, idle, hz, seed=seed)

    dabflow = {
        "material": material,
        "concentrate": concentrate,
        "heater": heater,
        "sequence_type": seq_type,
        "path_id": path_id,
        "browser": browser_pkg,
        "browser_tag": browser_tag,
        "browser_label": browser_label,
    }
    if extra_meta:
        dabflow.update(extra_meta)

    return {
        "name": name,
        "sequence_version": REQUIRED_SEQUENCE_VERSION,
        "isolation_policy": "hardcoded_every_seq",
        "description": (
            f"DabFlow {path_id} ({seq_type}/{browser_label}): "
            f"{material}/{concentrate}/{heater}"
        ),
        "author_width": mapping.base_w,
        "author_height": mapping.base_h,
        "requires_fingerprint": True,
        "preferred_browser": browser_pkg,
        "humanize": {
            "timing_variation": hz.timing_variation,
            "coordinate_tolerance": hz.coordinate_tolerance,
            "random_actions": hz.random_actions,
            "random_action_chance": hz.random_action_chance,
            "scroll_duration_ms": {"min": hz.scroll_duration_ms[0], "max": hz.scroll_duration_ms[1]},
        },
        "dabflow": dabflow,
        "steps": steps,
    }


def _slug(tabs: tuple[str, ...]) -> str:
    return "_".join(TAB_SHORT[t] for t in tabs)


def iter_all_specs(mapping, hz: HumanizeConfig):
    browse = tuple(mapping.browse_tabs)
    pairs = [(a, b) for a in browse for b in browse if a != b]
    orders = list(permutations(browse))
    h_slots = mapping.home_ad_slot_count
    t_slots = mapping.tab_ad_slot_count

    for material, concentrate, heater in product(
        mapping.materials, mapping.concentrates, mapping.heaters
    ):
        seed = hash(f"{material}_{concentrate}_{heater}") & 0xFFFFFFFF

        # Path1/2 × each browser (under-radar mix encoded in distinct stems).
        for browser_tag, browser_pkg, browser_label in PATH12_BROWSERS:
            bkw = {
                "browser_pkg": browser_pkg,
                "browser_label": browser_label,
                "browser_tag": browser_tag,
            }
            close = [_close_browser(browser_pkg, browser_label)]

            # Path 1A — close as-is
            # Browser tag goes before the trailing _complete/_halfway suffix — the
            # farm classifies pools off that suffix, so a trailing tag emptied the
            # Path1/2 pools entirely (ad=4200 complete=0 halfway=0).
            name = f"{material}_{concentrate}_{heater}_p1a_{browser_tag}_complete"
            yield Path(material) / f"{name}.json", dict(
                name=name,
                material=material,
                concentrate=concentrate,
                heater=heater,
                seq_type="complete",
                path_id="path1a",
                tail=_full_timer_wait() + _session_notes_skip(mapping, hz) + close,
                extra_meta={"variant": "A"},
                **bkw,
            )

            # Path 1B — one tab
            for tab in browse:
                name = (
                    f"{material}_{concentrate}_{heater}_p1b_"
                    f"{TAB_SHORT[tab]}_{browser_tag}_complete"
                )
                yield Path(material) / f"{name}.json", dict(
                    name=name,
                    material=material,
                    concentrate=concentrate,
                    heater=heater,
                    seq_type="complete",
                    path_id="path1b",
                    tail=_full_timer_wait()
                    + _session_notes_skip(mapping, hz)
                    + _browse_tabs_flow(mapping, hz, (tab,), seed)
                    + close,
                    extra_meta={"variant": "B", "tabs": [tab]},
                    **bkw,
                )

            # Path 1C — two tabs
            for t1, t2 in pairs:
                name = (
                    f"{material}_{concentrate}_{heater}_p1c_"
                    f"{TAB_SHORT[t1]}_{TAB_SHORT[t2]}_{browser_tag}_complete"
                )
                yield Path(material) / f"{name}.json", dict(
                    name=name,
                    material=material,
                    concentrate=concentrate,
                    heater=heater,
                    seq_type="complete",
                    path_id="path1c",
                    tail=_full_timer_wait()
                    + _session_notes_skip(mapping, hz)
                    + _browse_tabs_flow(mapping, hz, (t1, t2), seed)
                    + close,
                    extra_meta={"variant": "C", "tabs": [t1, t2]},
                    **bkw,
                )

            # Path 1D — all three tab orders
            for order in orders:
                name = (
                    f"{material}_{concentrate}_{heater}_p1d_"
                    f"{_slug(order)}_{browser_tag}_complete"
                )
                yield Path(material) / f"{name}.json", dict(
                    name=name,
                    material=material,
                    concentrate=concentrate,
                    heater=heater,
                    seq_type="complete",
                    path_id="path1d",
                    tail=_full_timer_wait()
                    + _session_notes_skip(mapping, hz)
                    + _browse_tabs_flow(mapping, hz, order, seed)
                    + close,
                    extra_meta={"variant": "D", "tabs": list(order)},
                    **bkw,
                )

            # Path 2 halfway
            name = f"{material}_{concentrate}_{heater}_timer_{browser_tag}_halfway"
            yield Path(material) / f"{name}.json", dict(
                name=name,
                material=material,
                concentrate=concentrate,
                heater=heater,
                seq_type="halfway",
                path_id="path2",
                tail=_halfway_wait()
                + [_close_browser(browser_pkg, browser_label)],
                extra_meta={"variant": "halfway"},
                **bkw,
            )

        # Path3 always Chromium (Mantis CDP).
        p3_kw = {
            "browser_pkg": BROWSER_CHROMIUM,
            "browser_label": "Chromium",
            "browser_tag": "chromium",
        }
        p3_close = [_close_browser(BROWSER_CHROMIUM, "Chromium")]

        # Path 3A — home bottom ads
        for ai in range(h_slots):
            name = f"{material}_{concentrate}_{heater}_p3a_homead{ai}_ad"
            yield Path(material) / f"{name}.json", dict(
                name=name,
                material=material,
                concentrate=concentrate,
                heater=heater,
                seq_type="ad",
                path_id="path3a",
                tail=_full_timer_wait()
                + _session_notes_skip(mapping, hz)
                + _home_ad_flow(mapping, hz, ai, seed + ai * 17)
                + p3_close,
                extra_meta={"variant": "A", "ad_page": "home", "ad_index": ai},
                **p3_kw,
            )

        # Path 3B — one tab + one ad on that tab
        for tab in browse:
            for ai in range(t_slots):
                name = f"{material}_{concentrate}_{heater}_p3b_{TAB_SHORT[tab]}_ad{ai}_ad"
                yield Path(material) / f"{name}.json", dict(
                    name=name,
                    material=material,
                    concentrate=concentrate,
                    heater=heater,
                    seq_type="ad",
                    path_id="path3b",
                    tail=_full_timer_wait()
                    + _session_notes_skip(mapping, hz)
                    + _browse_tabs_flow(
                        mapping, hz, (tab,), seed, ad_tab=tab, ad_index=ai
                    )
                    + p3_close,
                    extra_meta={"variant": "B", "tabs": [tab], "ad_tab": tab, "ad_index": ai},
                    **p3_kw,
                )

        # Path 3C — two tabs + ad on one of them
        for t1, t2 in pairs:
            for ad_tab in (t1, t2):
                for ai in range(t_slots):
                    name = (
                        f"{material}_{concentrate}_{heater}_p3c_"
                        f"{TAB_SHORT[t1]}_{TAB_SHORT[t2]}_on{TAB_SHORT[ad_tab]}_ad{ai}_ad"
                    )
                    yield Path(material) / f"{name}.json", dict(
                        name=name,
                        material=material,
                        concentrate=concentrate,
                        heater=heater,
                        seq_type="ad",
                        path_id="path3c",
                        tail=_full_timer_wait()
                        + _session_notes_skip(mapping, hz)
                        + _browse_tabs_flow(
                            mapping, hz, (t1, t2), seed, ad_tab=ad_tab, ad_index=ai
                        )
                        + p3_close,
                        extra_meta={
                            "variant": "C",
                            "tabs": [t1, t2],
                            "ad_tab": ad_tab,
                            "ad_index": ai,
                        },
                        **p3_kw,
                    )

        # Path 3D — three tabs + ad on one of them
        for order in orders:
            for ad_tab in order:
                for ai in range(t_slots):
                    name = (
                        f"{material}_{concentrate}_{heater}_p3d_"
                        f"{_slug(order)}_on{TAB_SHORT[ad_tab]}_ad{ai}_ad"
                    )
                    yield Path(material) / f"{name}.json", dict(
                        name=name,
                        material=material,
                        concentrate=concentrate,
                        heater=heater,
                        seq_type="ad",
                        path_id="path3d",
                        tail=_full_timer_wait()
                        + _session_notes_skip(mapping, hz)
                        + _browse_tabs_flow(
                            mapping, hz, order, seed, ad_tab=ad_tab, ad_index=ai
                        )
                        + p3_close,
                        extra_meta={
                            "variant": "D",
                            "tabs": list(order),
                            "ad_tab": ad_tab,
                            "ad_index": ai,
                        },
                        **p3_kw,
                    )


def write_sequences(out_dir: Path, preset: str = "moderate", *, base_only: bool = False, clean: bool = True) -> int:
    mapping = load_mapping()
    hz = PRESETS.get(preset, PRESETS["moderate"])
    expected = mapping.combination_count()
    if clean and out_dir.exists():
        for material in mapping.materials:
            mat_dir = out_dir / material
            if mat_dir.is_dir():
                shutil.rmtree(mat_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for rel, kwargs in iter_all_specs(mapping, hz):
        path = out_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = build_sequence(mapping=mapping, hz=hz, inject_random=not base_only, **kwargs)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        count += 1
    if count != expected:
        raise RuntimeError(f"Expected {expected} sequences, wrote {count}")
    return count


def write_catalog(catalog_path: Path) -> None:
    mapping = load_mapping()
    lines = [
        "# DabFlow Sequence Catalog",
        "",
        f"Source: [{mapping.url}]({mapping.url})",
        f"Baseline: {mapping.base_w}x{mapping.base_h}",
        f"Total: **{mapping.combination_count()}** "
        f"({mapping.selection_core_count()} cores × {mapping.paths_per_selection()} paths)",
        "",
        "## Live-proven coords (2026-07-11)",
        "",
        "- Start Perfect Dab: scroll into view, then tap ~(449, 1281)",
        "- Session notes Skip: ~(229, 1201)",
        "- Nav: Home(90) Timer(270) Stats(449) Glass(629) Settings(809) @ y≈1535",
        "- Home Mantis feed: multiple Sponsored cards (ordinal slots 0–3)",
        "- Tab slots: stats/glass/settings ad-slot containers (2 ordinals each)",
        "",
        f"- Required sequence_version: **{REQUIRED_SEQUENCE_VERSION}**",
        "- isolation_policy: **hardcoded_every_seq** (new IP/geo/IMEI/identity every run; runner enforces)",
        "- Path1/2: one file per browser tag (`_chromium` / `_firefox` / `_brave`)",
        "- Path3: Chromium only (Mantis CDP); ads: live on-screen slot pick",
        "",
    ]
    catalog_path.write_text("\n".join(lines), encoding="utf-8")


def write_presets(presets_dir: Path) -> None:
    presets_dir.mkdir(parents=True, exist_ok=True)
    for name, hz in PRESETS.items():
        path = presets_dir / f"{name}.json"
        path.write_text(
            json.dumps(
                {
                    "name": name,
                    "humanize": {
                        "timing_variation": hz.timing_variation,
                        "coordinate_tolerance": hz.coordinate_tolerance,
                        "random_actions": hz.random_actions,
                        "random_action_chance": hz.random_action_chance,
                        "scroll_duration_ms": {
                            "min": hz.scroll_duration_ms[0],
                            "max": hz.scroll_duration_ms[1],
                        },
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preset", default="moderate", choices=sorted(PRESETS))
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=ROOT / "automation" / "recordings" / "sequences" / "base",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=ROOT / "automation" / "recordings" / "sequences" / "sequence_catalog.md",
    )
    parser.add_argument(
        "--presets-dir",
        type=Path,
        default=ROOT / "automation" / "presets",
    )
    args = parser.parse_args()
    write_presets(args.presets_dir)
    n = write_sequences(args.base_dir, preset=args.preset, base_only=True)
    write_catalog(args.catalog)
    print(f"Generated {n} base sequences -> {args.base_dir}")
    print(f"Wrote catalog -> {args.catalog}")


if __name__ == "__main__":
    main()
