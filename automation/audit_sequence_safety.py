#!/usr/bin/env python3
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEQUENCES_DIR = ROOT / "automation" / "recordings" / "sequences"
GROUPS_CONFIG = ROOT / "automation" / "recordings" / "groups_config.json"
REPORT_PATH = ROOT / "docs" / "sequence_safety_audit.generated.md"

TAIL_TYPES = ("rotate_identity", "wait", "full_reset")
KNOWN_OVERLAY_TAPS = {
    (450, 1488),  # common bottom consent/overlay dismiss
    (455, 660),   # stacked timer dismiss
    (450, 705),   # timer strip interaction
}
POSITIONAL_TYPES = {"tap", "swipe"}


@dataclass
class Issue:
    category: str
    detail: str
    auto_fixed: bool


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _dump_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _playlist_active_names() -> set[str]:
    if not GROUPS_CONFIG.is_file():
        return set()
    try:
        payload = _load_json(GROUPS_CONFIG)
    except Exception:
        return set()
    groups = payload.get("groups")
    if not isinstance(groups, list):
        return set()
    names: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            continue
        phones = group.get("phones")
        if not isinstance(phones, dict):
            continue
        for phone_cfg in phones.values():
            if not isinstance(phone_cfg, dict):
                continue
            for key in ("sequence_playlist", "sequence_playlist_secondary"):
                raw = phone_cfg.get(key)
                if not isinstance(raw, list):
                    continue
                for item in raw:
                    s = str(item).strip()
                    if s:
                        names.add(s)
    return names


def _active_sequence_paths() -> tuple[list[Path], str]:
    from_playlists = _playlist_active_names()
    if from_playlists:
        paths = []
        for name in sorted(from_playlists):
            p = SEQUENCES_DIR / name
            if p.is_file():
                paths.append(p)
        return paths, "playlist-referenced"
    return sorted(SEQUENCES_DIR.glob("*.json")), "all-sequences-fallback"


def _next_non_wait_step(steps: list[dict], start_idx: int) -> tuple[int, dict] | tuple[None, None]:
    for idx in range(start_idx + 1, len(steps)):
        step = steps[idx]
        if isinstance(step, dict) and step.get("type") != "wait":
            return idx, step
    return None, None


def _needs_initial_wait_after_open_url(steps: list[dict], idx: int) -> bool:
    step = steps[idx]
    post_wait = step.get("post_wait_secs")
    if isinstance(post_wait, (int, float)) and float(post_wait) >= 1.0:
        return False
    next_idx, next_step = _next_non_wait_step(steps, idx)
    if next_idx is None:
        return False
    if next_step.get("type") == "wait":
        return False
    # Any non-wait action immediately after open_url without post_wait is unsafe.
    return next_idx == idx + 1


def _detect_overlay_handling(steps: list[dict]) -> bool:
    head = steps[:10]
    for step in head:
        if not isinstance(step, dict):
            continue
        typ = step.get("type")
        if typ == "keyevent" and str(step.get("key")) == "4":
            return True
        if typ == "tap":
            x = int(step.get("x", -1))
            y = int(step.get("y", -1))
            if (x, y) in KNOWN_OVERLAY_TAPS:
                return True
            # Bottom-strip taps often represent consent / overlay dismissal.
            if y >= 1400:
                return True
    return False


def _position(step: dict) -> tuple[float, float] | None:
    typ = step.get("type")
    if typ == "tap":
        x, y = step.get("x"), step.get("y")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            return float(x), float(y)
    elif typ == "swipe":
        x, y = step.get("x2"), step.get("y2")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            return float(x), float(y)
    return None


def _tail_step_types(steps: list[dict]) -> list[str]:
    return [str(s.get("type")) for s in steps if isinstance(s, dict) and s.get("type")]


def _normalize_tail(steps: list[dict]) -> tuple[list[dict], bool]:
    types = _tail_step_types(steps)
    if len(types) >= 3 and tuple(types[-3:]) == TAIL_TYPES:
        return steps, False

    # Remove trailing rotate/wait/full_reset fragment so we can append canonical tail.
    trim = list(steps)
    while trim:
        t = trim[-1].get("type") if isinstance(trim[-1], dict) else None
        if t in {"rotate_identity", "wait", "full_reset"}:
            trim.pop()
            continue
        break

    trim.extend(
        [
            {"type": "rotate_identity"},
            {"type": "wait", "seconds": 2.0},
            {"type": "full_reset"},
        ]
    )
    return trim, True


def audit_and_fix(path: Path) -> tuple[list[Issue], bool]:
    issues: list[Issue] = []
    raw_file = _load_json(path)
    try:
        from sequence_normalize import unwrap_sequence_document

        payload, _meta = unwrap_sequence_document(raw_file)
    except ValueError as exc:
        return [Issue("json-shape", str(exc), False)], False
    if not isinstance(payload, list):
        return [Issue("json-shape", "steps payload is not array", False)], False

    steps: list[dict] = []
    for item in payload:
        if isinstance(item, dict):
            steps.append(item)
        else:
            issues.append(Issue("json-shape", "contains non-object step", False))

    changed = False

    # 1) Missing initial page-load waits (auto-fix by inserting 3.5s wait).
    idx = 0
    while idx < len(steps):
        step = steps[idx]
        if step.get("type") == "open_url" and _needs_initial_wait_after_open_url(steps, idx):
            issues.append(
                Issue(
                    "missing-initial-page-load-wait",
                    f"open_url at step {idx} followed immediately by action",
                    True,
                )
            )
            steps.insert(idx + 1, {"type": "wait", "seconds": 3.5})
            changed = True
            idx += 2
            continue
        idx += 1

    # 2) Overlay handling (audit-only; not auto-fixed due ambiguity).
    if not _detect_overlay_handling(steps):
        issues.append(
            Issue(
                "missing-overlay-handling",
                "no early back/dismiss-like overlay handling in first 10 steps",
                False,
            )
        )

    # 3) Impossible coordinate jumps (auto-fix only for adjacent positional actions without wait).
    last_pos = None
    last_pos_idx = None
    since_wait = False
    inserts: list[tuple[int, dict]] = []
    for i, step in enumerate(steps):
        typ = step.get("type")
        if typ == "wait":
            since_wait = True
            continue
        if typ not in POSITIONAL_TYPES:
            continue
        pos = _position(step)
        if pos is None:
            continue
        if last_pos is not None and last_pos_idx is not None and not since_wait:
            dist = math.dist(last_pos, pos)
            if dist > 650:
                issues.append(
                    Issue(
                        "impossible-coordinate-jump",
                        f"distance {dist:.1f} between positional steps {last_pos_idx}->{i} without wait",
                        True,
                    )
                )
                inserts.append((i, {"type": "wait", "seconds": 0.35}))
        last_pos = pos
        last_pos_idx = i
        since_wait = False

    for offset, (i, step) in enumerate(inserts):
        steps.insert(i + offset, step)
        changed = True

    # 4)/5) Cooldown/exit + IP/ID tail consistency.
    tail_types = _tail_step_types(steps)
    has_exit_hint = any(t in {"close_app", "clear_cookies"} for t in tail_types[-6:])
    has_identity_ops_anywhere = any(t in {"rotate_identity", "full_reset"} for t in tail_types)
    if not has_exit_hint and not has_identity_ops_anywhere:
        issues.append(
            Issue(
                "absent-cooldown-exit-handling",
                "sequence lacks close/clear or identity reset operations",
                False,
            )
        )

    normalized, did_tail_fix = _normalize_tail(steps)
    if did_tail_fix:
        issues.append(
            Issue(
                "inconsistent-ip-id-tail",
                "normalized tail to rotate_identity -> wait(2.0) -> full_reset",
                True,
            )
        )
        steps = normalized
        changed = True

    if changed:
        if isinstance(raw_file, dict) and isinstance(raw_file.get("steps"), list):
            out_doc = dict(raw_file)
            out_doc["steps"] = steps
            _dump_json(path, out_doc)
        else:
            _dump_json(path, steps)
    return issues, changed


def _run() -> int:
    paths, active_mode = _active_sequence_paths()
    all_issues: dict[str, list[Issue]] = {}
    changed_files: list[str] = []

    for path in paths:
        try:
            issues, changed = audit_and_fix(path)
        except Exception as exc:
            issues = [Issue("read-error", str(exc), False)]
            changed = False
        if issues:
            all_issues[path.name] = issues
        if changed:
            changed_files.append(path.name)

    counts: dict[str, int] = {}
    fixed_counts: dict[str, int] = {}
    for issues in all_issues.values():
        for issue in issues:
            counts[issue.category] = counts.get(issue.category, 0) + 1
            if issue.auto_fixed:
                fixed_counts[issue.category] = fixed_counts.get(issue.category, 0) + 1

    lines: list[str] = []
    lines.append("# Sequence Safety Audit (generated)")
    lines.append("")
    lines.append(f"- Generated: {datetime.now().astimezone().isoformat(timespec='seconds')}")
    lines.append(f"- Active scope mode: `{active_mode}`")
    lines.append(f"- Active sequence files audited: `{len(paths)}`")
    lines.append(f"- Files auto-fixed: `{len(changed_files)}`")
    lines.append("")
    lines.append("## Category Results")
    lines.append("")
    categories = [
        "missing-initial-page-load-wait",
        "missing-overlay-handling",
        "impossible-coordinate-jump",
        "absent-cooldown-exit-handling",
        "inconsistent-ip-id-tail",
    ]
    for category in categories:
        found = counts.get(category, 0)
        fixed = fixed_counts.get(category, 0)
        lines.append(f"- `{category}`: found `{found}`, auto-fixed `{fixed}`")
    lines.append("")
    lines.append("## Auto-Fixed Files")
    lines.append("")
    if changed_files:
        for name in sorted(changed_files):
            lines.append(f"- `{name}`")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("## Findings by File")
    lines.append("")
    if all_issues:
        for name in sorted(all_issues):
            lines.append(f"### `{name}`")
            for issue in all_issues[name]:
                suffix = " (auto-fixed)" if issue.auto_fixed else ""
                lines.append(f"- `{issue.category}`: {issue.detail}{suffix}")
            lines.append("")
    else:
        lines.append("- No issues found.")
        lines.append("")

    REPORT_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    print(
        f"audit complete: scope={len(paths)} files, issues={sum(counts.values())}, "
        f"auto_fixed={sum(fixed_counts.values())}, changed_files={len(changed_files)}"
    )
    print(f"wrote report: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
