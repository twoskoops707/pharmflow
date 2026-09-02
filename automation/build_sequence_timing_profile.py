#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GROUPS_CONFIG = ROOT / "automation" / "recordings" / "groups_config.json"
SEQUENCE_DIR = ROOT / "automation" / "recordings" / "sequences"
REPORT_PATH = ROOT / "docs" / "sequence_timing_profile.generated.md"

# Conservative floor so we only patch clearly too-short flows.
MIN_RUNTIME_SECONDS = 30.0
PATCH_WAIT_SECONDS = 1.5


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _step_runtime_seconds(step: dict[str, Any]) -> tuple[float, str]:
    step_type = str(step.get("type") or "")
    if step_type == "wait":
        return _to_float(step.get("seconds")), "wait.seconds"
    if step_type == "open_url":
        # Launch intent + post-load settle.
        return 1.25 + _to_float(step.get("post_wait_secs")), "open_url(1.25+post_wait_secs)"
    if step_type == "tap":
        return 0.18 + (_to_float(step.get("pre_wait_ms")) / 1000.0), "tap(0.18+pre_wait_ms)"
    if step_type == "swipe":
        return 0.12 + (_to_float(step.get("ms")) / 1000.0), "swipe(0.12+ms)"
    if step_type == "keyevent":
        return 0.10, "keyevent(0.10)"
    if step_type == "close_app":
        return 0.35, "close_app(0.35)"
    if step_type == "clear_cookies":
        return 0.55, "clear_cookies(0.55)"
    if step_type == "type_text":
        typed = str(step.get("text") or "")
        return 0.20 + (0.05 * len(typed)), "type_text(0.20+0.05*len)"
    if step_type == "rotate_identity":
        return 4.00, "rotate_identity(4.00)"
    if step_type == "full_reset":
        return 6.50, "full_reset(6.50)"
    return 0.0, f"{step_type or 'unknown'}(0.00)"


@dataclass
class FlowProfile:
    flow_id: str
    group_name: str
    phone: str
    source: str
    steps: list[dict[str, Any]]
    runtime_seconds: float
    risk_score: float
    short_wait_count: int
    interaction_count: int
    repeat: int
    repeat_forever: bool
    patched: bool = False


def _calc_runtime_and_counters(steps: list[dict[str, Any]]) -> tuple[float, int, int]:
    total = 0.0
    short_waits = 0
    interactions = 0
    for step in steps:
        if not isinstance(step, dict):
            continue
        t = str(step.get("type") or "")
        rt, _ = _step_runtime_seconds(step)
        total += rt
        if t == "wait":
            wait_s = _to_float(step.get("seconds"))
            if 0 < wait_s < 0.9:
                short_waits += 1
        if t in {"tap", "swipe", "keyevent", "type_text"}:
            interactions += 1
    return total, short_waits, interactions


def _risk_score(steps: list[dict[str, Any]], runtime_s: float, short_waits: int, interactions: int) -> float:
    score = 0.0
    if runtime_s < MIN_RUNTIME_SECONDS:
        score += (MIN_RUNTIME_SECONDS - runtime_s) * 1.7
    score += short_waits * 2.5
    if runtime_s > 0:
        score += (interactions / runtime_s) * 40.0
    step_types = [str(s.get("type")) for s in steps if isinstance(s, dict)]
    if "rotate_identity" in step_types and "full_reset" not in step_types:
        score += 6.0
    return round(score, 2)


def _load_steps_from_playlist(names: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    merged: list[dict[str, Any]] = []
    missing: list[str] = []
    for name in names:
        p = SEQUENCE_DIR / name
        if not p.exists():
            missing.append(name)
            continue
        payload = _load_json(p)
        if isinstance(payload, list):
            merged.extend([s for s in payload if isinstance(s, dict)])
    return merged, missing


def _collect_active_profiles(groups_payload: dict[str, Any]) -> tuple[list[FlowProfile], list[str]]:
    profiles: list[FlowProfile] = []
    notes: list[str] = []
    groups = groups_payload.get("groups", [])
    if not isinstance(groups, list):
        return profiles, ["groups_config.json: 'groups' is not a list"]
    for g_idx, group in enumerate(groups):
        if not isinstance(group, dict):
            continue
        group_name = str(group.get("name") or f"group-{g_idx + 1}")
        repeat = int(_to_float(group.get("repeat"), 1.0) or 1)
        repeat_forever = bool(group.get("repeat_forever", False))
        phones = group.get("phones", {})
        if not isinstance(phones, dict):
            continue
        for serial, phone_cfg in phones.items():
            if not isinstance(phone_cfg, dict):
                continue
            source = "inline"
            steps: list[dict[str, Any]] = []
            playlist_a = phone_cfg.get("sequence_playlist")
            playlist_b = phone_cfg.get("sequence_playlist_secondary")
            if isinstance(playlist_a, list) and playlist_a:
                source = "playlist"
                names_a = [str(x) for x in playlist_a]
                names_b = [str(x) for x in playlist_b] if isinstance(playlist_b, list) else []
                merged_a, missing_a = _load_steps_from_playlist(names_a)
                merged_b, missing_b = _load_steps_from_playlist(names_b)
                steps = merged_a + merged_b
                if missing_a or missing_b:
                    notes.append(
                        f"{group_name}/{serial}: missing playlist files: {', '.join(missing_a + missing_b)}"
                    )
            if not steps:
                raw_steps = phone_cfg.get("steps", [])
                if isinstance(raw_steps, list):
                    steps = [s for s in raw_steps if isinstance(s, dict)]

            runtime_s, short_waits, interactions = _calc_runtime_and_counters(steps)
            risk = _risk_score(steps, runtime_s, short_waits, interactions)
            profiles.append(
                FlowProfile(
                    flow_id=f"{group_name}::{serial}",
                    group_name=group_name,
                    phone=str(serial),
                    source=source,
                    steps=steps,
                    runtime_seconds=runtime_s,
                    risk_score=risk,
                    short_wait_count=short_waits,
                    interaction_count=interactions,
                    repeat=repeat,
                    repeat_forever=repeat_forever,
                )
            )
    return profiles, notes


def _apply_conservative_short_flow_patch(groups_payload: dict[str, Any], profiles: list[FlowProfile]) -> int:
    patched = 0
    profile_by_id = {p.flow_id: p for p in profiles}
    groups = groups_payload.get("groups", [])
    for g_idx, group in enumerate(groups):
        if not isinstance(group, dict):
            continue
        group_name = str(group.get("name") or f"group-{g_idx + 1}")
        phones = group.get("phones", {})
        if not isinstance(phones, dict):
            continue
        for serial, phone_cfg in phones.items():
            flow_id = f"{group_name}::{serial}"
            profile = profile_by_id.get(flow_id)
            if not profile or profile.runtime_seconds >= MIN_RUNTIME_SECONDS:
                continue
            if not isinstance(phone_cfg, dict):
                continue
            raw_steps = phone_cfg.get("steps")
            if not isinstance(raw_steps, list):
                continue
            # Conservative policy: only pad inline flows with a single wait right before
            # rotate_identity/full_reset tail if there isn't already a wait.
            insert_idx = None
            for i, step in enumerate(raw_steps):
                if isinstance(step, dict) and str(step.get("type")) in {"rotate_identity", "full_reset"}:
                    insert_idx = i
                    break
            if insert_idx is None:
                continue
            prev_is_wait = insert_idx > 0 and isinstance(raw_steps[insert_idx - 1], dict) and str(raw_steps[insert_idx - 1].get("type")) == "wait"
            if prev_is_wait:
                continue
            raw_steps.insert(insert_idx, {"type": "wait", "seconds": PATCH_WAIT_SECONDS})
            profile.patched = True
            patched += 1
    return patched


def _render_report(
    profiles: list[FlowProfile],
    patch_count: int,
    notes: list[str],
) -> str:
    lines: list[str] = []
    lines.append("# Sequence timing profile (generated)")
    lines.append("")
    lines.append(f"Generated by `automation/{Path(__file__).name}` from active flows in `automation/recordings/groups_config.json`.")
    lines.append("")
    lines.append("## Runtime math by step type (strict model)")
    lines.append("")
    lines.append("- `wait`: `seconds`")
    lines.append("- `open_url`: `1.25 + post_wait_secs`")
    lines.append("- `tap`: `0.18 + pre_wait_ms / 1000`")
    lines.append("- `swipe`: `0.12 + ms / 1000`")
    lines.append("- `keyevent`: `0.10`")
    lines.append("- `close_app`: `0.35`")
    lines.append("- `clear_cookies`: `0.55`")
    lines.append("- `type_text`: `0.20 + 0.05 * len(text)`")
    lines.append("- `rotate_identity`: `4.00`")
    lines.append("- `full_reset`: `6.50`")
    lines.append("")
    lines.append(f"- Short-flow patch threshold: `< {MIN_RUNTIME_SECONDS:.1f}s`")
    lines.append(f"- Conservative patch action: inject one `wait` step of `{PATCH_WAIT_SECONDS:.1f}s` before `rotate_identity/full_reset` if no prior wait")
    lines.append("")

    lines.append("## Ranked shortest flows (active)")
    lines.append("")
    lines.append("| Rank | Flow | Source | Runtime (s) | Steps | Risk | Patched |")
    lines.append("|---:|---|---|---:|---:|---:|:---:|")
    for idx, p in enumerate(sorted(profiles, key=lambda x: (x.runtime_seconds, -x.risk_score)), start=1):
        lines.append(
            f"| {idx} | `{p.flow_id}` | {p.source} | {p.runtime_seconds:.2f} | {len(p.steps)} | {p.risk_score:.2f} | {'yes' if p.patched else 'no'} |"
        )
    lines.append("")

    lines.append("## Ranked riskiest flows (active)")
    lines.append("")
    lines.append("| Rank | Flow | Runtime (s) | Risk | Short waits (<0.9s) | Interaction steps |")
    lines.append("|---:|---|---:|---:|---:|---:|")
    for idx, p in enumerate(sorted(profiles, key=lambda x: (-x.risk_score, x.runtime_seconds)), start=1):
        lines.append(
            f"| {idx} | `{p.flow_id}` | {p.runtime_seconds:.2f} | {p.risk_score:.2f} | {p.short_wait_count} | {p.interaction_count} |"
        )
    lines.append("")

    lines.append("## Group aggregate runtime estimates")
    lines.append("")
    lines.append("| Group | Phones | Repeat | Group runtime per cycle (s) | Group runtime estimate (s) |")
    lines.append("|---|---:|---|---:|---:|")
    by_group: dict[str, list[FlowProfile]] = {}
    for p in profiles:
        by_group.setdefault(p.group_name, []).append(p)
    for group_name in sorted(by_group):
        items = by_group[group_name]
        phones = len(items)
        per_cycle = sum(i.runtime_seconds for i in items)
        if any(i.repeat_forever for i in items):
            repeat_label = "forever"
            estimate = "n/a"
        else:
            repeat = max(i.repeat for i in items)
            repeat_label = str(repeat)
            estimate = f"{(per_cycle * repeat):.2f}"
        lines.append(f"| `{group_name}` | {phones} | {repeat_label} | {per_cycle:.2f} | {estimate} |")
    lines.append("")

    lines.append("## Patch summary")
    lines.append("")
    lines.append(f"- Active flows detected: **{len(profiles)}**")
    lines.append(f"- Flows patched for short runtime: **{patch_count}**")
    lines.append("- Patched files: `automation/recordings/groups_config.json` (inline steps only)")
    if notes:
        lines.append("")
        lines.append("## Notes")
        lines.append("")
        for n in notes:
            lines.append(f"- {n}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    groups_payload = _load_json(GROUPS_CONFIG)
    profiles, notes = _collect_active_profiles(groups_payload)

    patch_count = _apply_conservative_short_flow_patch(groups_payload, profiles)
    if patch_count:
        GROUPS_CONFIG.write_text(json.dumps(groups_payload, indent=2) + "\n", encoding="utf-8")
        # Recompute with patched steps for final report.
        profiles, notes = _collect_active_profiles(groups_payload)

    report = _render_report(profiles, patch_count, notes)
    REPORT_PATH.write_text(report, encoding="utf-8")

    print(f"WROTE: {REPORT_PATH}")
    print(f"ACTIVE_FLOWS: {len(profiles)}")
    print(f"PATCHED_SHORT_FLOWS: {patch_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
