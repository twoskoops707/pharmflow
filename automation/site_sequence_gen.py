"""Generate humanized sequence JSON from a generic SiteProfile (any website/APK)."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from automation.config import AUTHOR_HEIGHT, AUTHOR_WIDTH, REQUIRED_SEQUENCE_VERSION
from automation.site_profile import BrowsePath, SiteProfile

try:
    from wizard.sequence_humanize import humanize_steps
except ImportError:  # pragma: no cover — automation-only contexts

    def humanize_steps(
        steps: list,
        rng: random.Random | None = None,
        *,
        intensity: float = 1.0,
    ) -> list:  # type: ignore[misc]
        return list(steps)


def _step(action: str, params: dict[str, Any], description: str = "") -> dict[str, Any]:
    return {"action": action, "params": params, "description": description or action}


def _session_preamble(profile: SiteProfile, stem: str) -> list[dict[str, Any]]:
    """Per-sequence privacy and anti-correlation steps.

    The runner also prepares a fresh session defensively. Keeping these actions
    in generated JSON makes the Builder catalog self-describing and ensures the
    guarantees survive when a sequence is run manually outside farm mode.
    """
    rng = random.Random(f"{profile.slug}:{stem}:session")
    return [
        _step("rotate_identity", {}, "New verified exit IP and browser identity"),
        _step(
            "wait",
            {"seconds": round(rng.uniform(0.8, 2.4), 3)},
            "Human pause after identity rotation",
        ),
        _step("ensure_fingerprint", {}, "Verify spoofed browser fingerprint"),
        _step(
            "clear_cookies",
            {"package": "org.chromium.chrome"},
            "Clear browser history, cookies, cache, and site storage",
        ),
    ]


def _finish_target(profile: SiteProfile) -> list[dict[str, Any]]:
    package = profile.package if profile.target_kind == "app" and profile.package else "org.chromium.chrome"
    return [_step("close_app", {"package": package}, f"Close {package}")]


def _open_target(profile: SiteProfile) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    if profile.target_kind == "app" and profile.package:
        steps.append(
            _step(
                "launch_app",
                {"package": profile.package, "post_wait_secs": 2.0},
                f"Launch {profile.package}",
            )
        )
    else:
        url = profile.url or "https://example.com"
        steps.append(_step("open_url", {"url": url, "post_wait_secs": 1.5}, f"Open {url}"))
    for gate in profile.gates:
        steps.append(_step("wait", {"seconds": float(gate.wait_before_s)}, f"Wait for {gate.label}"))
        steps.append(
            _step(
                "tap",
                {"x": int(gate.x), "y": int(gate.y), "jitter": 8},
                f"Gate: {gate.label}",
            )
        )
        steps.append(_step("wait", {"seconds": float(gate.wait_after_s)}, "Settle after gate"))
    return steps


def _scroll_bottom(swipes: int = 4) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(max(1, swipes)):
        out.append(
            _step(
                "swipe",
                {"x1": 450, "y1": 1300, "x2": 450, "y2": 500, "duration_ms": 280},
                f"Scroll {i + 1}",
            )
        )
        out.append(_step("wait", {"seconds": 0.35}, "Scroll pause"))
    return out


def _core_steps(profile: SiteProfile) -> list[dict[str, Any]]:
    c = profile.core
    steps: list[dict[str, Any]] = []
    if c.scroll_before or c.kind == "scroll_then_tap":
        steps.extend(_scroll_bottom(3))
    if c.kind == "wait":
        steps.append(_step("wait", {"seconds": float(c.confirm_wait_s)}, c.description))
        return steps
    steps.append(
        _step(
            "tap",
            {"x": int(c.x), "y": int(c.y), "jitter": 10},
            c.description or "Core action",
        )
    )
    steps.append(_step("wait", {"seconds": float(c.confirm_wait_s)}, "Confirm core action"))
    return steps


def _browse(path: BrowsePath) -> list[dict[str, Any]]:
    steps = [
        _step("tap", {"x": int(path.x), "y": int(path.y), "jitter": 6}, f"Open {path.name}"),
        _step("wait", {"seconds": 0.8}, f"Settle {path.name}"),
    ]
    if path.scroll_to_bottom:
        steps.extend(_scroll_bottom(int(path.scroll_swipes)))
    return steps


def build_sequence_variants(profile: SiteProfile) -> list[dict[str, Any]]:
    """
    Build a small humanized catalog for any site:
    - path1_complete: open + gate + core
    - path1_browse_<n>: + one browse path
    - path2_browse_pair: two browse paths
    - path3_ad_<name>: browse + one ad tap (if ads configured)
    """
    variants: list[tuple[str, list[dict[str, Any]]]] = []

    def assemble(stem: str, body: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _session_preamble(profile, stem) + body + _finish_target(profile)

    stem = "path1_complete"
    variants.append((stem, assemble(stem, _open_target(profile) + _core_steps(profile))))

    for bp in profile.browse_paths[:3]:
        stem = f"path1_{bp.name}_browse"
        variants.append(
            (
                stem,
                assemble(stem, _open_target(profile) + _core_steps(profile) + _browse(bp)),
            )
        )

    if len(profile.browse_paths) >= 2:
        a, b = profile.browse_paths[0], profile.browse_paths[1]
        stem = "path2_pair_browse"
        variants.append(
            (
                stem,
                assemble(
                    stem,
                    _open_target(profile) + _core_steps(profile) + _browse(a) + _browse(b),
                ),
            )
        )

    for ad in profile.ads:
        steps = _open_target(profile) + _core_steps(profile)
        if profile.browse_paths:
            steps.extend(_browse(profile.browse_paths[0]))
        steps.append(_step("wait", {"seconds": 1.0}, "Before ad"))
        steps.append(
            _step(
                "tap",
                {"x": int(ad.x), "y": int(ad.y), "jitter": 8},
                f"Tap ad: {ad.name}",
            )
        )
        steps.append(_step("wait", {"seconds": 8.0}, "Human dwell on advertiser"))
        steps.append(_step("keyevent", {"code": 4}, "Back from advertiser"))
        stem = f"path3_{ad.name}_ad"
        variants.append((stem, assemble(stem, steps)))

    rng = random.Random(f"{profile.slug}:{profile.humanize.preset}")
    intensity = {
        "conservative": 0.5,
        "moderate": 1.0,
        "aggressive": 1.8,
    }.get(profile.humanize.preset, 1.0)
    out: list[dict[str, Any]] = []
    for stem, steps in variants:
        if profile.humanize.preset != "off":
            steps = humanize_steps(steps, rng=rng, intensity=intensity)
        out.append(
            {
                "name": f"{profile.slug}_{stem}",
                "site_slug": profile.slug,
                "site_adapter": profile.adapter,
                "sequence_version": REQUIRED_SEQUENCE_VERSION,
                "author_width": AUTHOR_WIDTH,
                "author_height": AUTHOR_HEIGHT,
                "humanize_preset": profile.humanize.preset,
                "requires_fingerprint": True,
                "runtime_guarantees": {
                    "verified_unique_exit_ip": True,
                    "fresh_android_id": True,
                    "browser_data_wipe": True,
                    "concurrent_unique_sequence": profile.humanize.concurrent_unique_sequences,
                    "full_hour_start_stagger": True,
                },
                "steps": steps,
            }
        )
    return out


def validate_sequence_variants(seqs: list[dict[str, Any]]) -> dict[str, Any]:
    """Audit Builder output before it is written or offered to the farm."""
    errors: list[str] = []
    names: set[str] = set()
    bodies: set[str] = set()
    ad_targets: set[tuple[int, int]] = set()
    start_waits: set[float] = set()
    required = {
        "rotate_identity",
        "ensure_fingerprint",
        "clear_cookies",
        "close_app",
    }
    for seq in seqs:
        name = str(seq.get("name") or "")
        if not name or name in names:
            errors.append(f"duplicate or empty sequence name: {name!r}")
        names.add(name)
        steps = seq.get("steps") if isinstance(seq.get("steps"), list) else []
        actions = {str(step.get("action") or "") for step in steps if isinstance(step, dict)}
        missing = required - actions
        if missing:
            errors.append(f"{name}: missing {', '.join(sorted(missing))}")
        if not ({"open_url", "launch_app"} & actions):
            errors.append(f"{name}: missing open_url/launch_app")
        body = json.dumps(steps, sort_keys=True, separators=(",", ":"))
        if body in bodies:
            errors.append(f"{name}: duplicate step body")
        bodies.add(body)
        for step in steps:
            if not isinstance(step, dict):
                continue
            params = step.get("params") if isinstance(step.get("params"), dict) else {}
            desc = str(step.get("description") or "").lower()
            if step.get("action") == "wait" and "identity rotation" in desc:
                seconds = params.get("seconds")
                if isinstance(seconds, (int, float)):
                    start_waits.add(round(float(seconds), 3))
            if step.get("action") == "tap" and "tap ad:" in desc:
                x, y = params.get("x"), params.get("y")
                if isinstance(x, dict):
                    x = x.get("base")
                if isinstance(y, dict):
                    y = y.get("base")
                if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                    ad_targets.add((int(x), int(y)))
    if len(seqs) > 1 and len(start_waits) < 2:
        errors.append("catalog does not vary per-sequence starting waits")
    return {
        "ok": not errors,
        "sequence_count": len(seqs),
        "unique_names": len(names),
        "unique_bodies": len(bodies),
        "unique_start_waits": len(start_waits),
        "unique_ad_targets": len(ad_targets),
        "errors": errors,
    }


def write_profile_sequences(profile: SiteProfile, out_dir: Path, *, clean: bool = False) -> int:
    """Write generated sequences under out_dir/<slug>/."""
    target = Path(out_dir) / profile.slug
    if clean and target.is_dir():
        for old in target.glob("*.json"):
            old.unlink()
    target.mkdir(parents=True, exist_ok=True)
    seqs = build_sequence_variants(profile)
    audit = validate_sequence_variants(seqs)
    if not audit["ok"]:
        raise ValueError("generated catalog failed validation: " + "; ".join(audit["errors"]))
    for seq in seqs:
        name = str(seq["name"])
        path = target / f"{name}.json"
        path.write_text(json.dumps(seq, indent=2) + "\n", encoding="utf-8")
    meta = {
        "slug": profile.slug,
        "count": len(seqs),
        "names": [s["name"] for s in seqs],
        "audit": audit,
    }
    (target / "_generated.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return len(seqs)
