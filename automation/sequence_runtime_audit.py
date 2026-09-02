#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RECORDINGS_DIR = ROOT / "automation" / "recordings"
SEQUENCES_DIR = RECORDINGS_DIR / "sequences"
GROUPS_CFG = RECORDINGS_DIR / "groups_config.json"
REPORT_PATH = ROOT / "docs" / "sequence_runtime_audit.generated.md"

MIN_OPEN_URL_POST_WAIT = 5.0
MIN_EXIT_COOLDOWN = 2.0
MIN_SEQUENCE_FLOOR = 45.0


@dataclass
class RuntimeParts:
    waits: float = 0.0
    open_url_post_wait: float = 0.0
    tap_pre_wait: float = 0.0
    tap_retry_gap: float = 0.0
    swipe_ms: float = 0.0
    inter_step_gap: float = 0.0

    @property
    def expected_seconds(self) -> float:
        return (
            self.waits
            + self.open_url_post_wait
            + self.tap_pre_wait
            + self.tap_retry_gap
            + self.swipe_ms
            + self.inter_step_gap
        )


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(v: Any, default: int = 0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _is_action_step(step: dict[str, Any]) -> bool:
    return step.get("type") in {"tap", "swipe", "type_text", "keyevent"}


def compute_runtime_parts(steps: list[dict[str, Any]]) -> RuntimeParts:
    parts = RuntimeParts()
    parts.inter_step_gap = 0.3 * len(steps)
    for step in steps:
        t = step.get("type")
        if t == "wait":
            parts.waits += max(0.0, min(300.0, _f(step.get("seconds", 1.0), 1.0)))
        elif t == "open_url":
            parts.open_url_post_wait += max(
                0.0, min(120.0, _f(step.get("post_wait_secs", 0.0), 0.0))
            )
        elif t == "tap":
            pre_ms = max(0.0, min(10000.0, _f(step.get("pre_wait_ms", 0.0), 0.0)))
            parts.tap_pre_wait += min(pre_ms / 1000.0, 10.0)
            retries = max(1, min(8, _i(step.get("retries", 1), 1)))
            if retries > 1:
                # run_sequence_step sleeps random 0.08..0.22 between retries.
                parts.tap_retry_gap += 0.08 * (retries - 1)
        elif t == "swipe":
            parts.swipe_ms += max(0.001, min(5.0, _f(step.get("ms", 400), 400.0) / 1000.0))
    return parts


def static_issues(path: Path, steps: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            issues.append(f"step {idx}: non-object entry")
            continue
        t = step.get("type")
        nxt = steps[idx + 1] if idx + 1 < len(steps) and isinstance(steps[idx + 1], dict) else None
        if t == "open_url" and nxt and _is_action_step(nxt):
            post = _f(step.get("post_wait_secs", 0.0), 0.0)
            if post < MIN_OPEN_URL_POST_WAIT:
                issues.append(f"step {idx}: open_url missing sufficient post_wait_secs before action")
        if t == "wait" and nxt and nxt.get("type") == "wait":
            issues.append(f"step {idx}/{idx+1}: consecutive waits")
        if t == "tap":
            bw = _i(step.get("base_w", 900), 900)
            bh = _i(step.get("base_h", 1600), 1600)
            x = _i(step.get("x", 0), 0)
            y = _i(step.get("y", 0), 0)
            if bw > 0 and (x < 0 or x > bw):
                issues.append(f"step {idx}: tap x={x} outside baseline width={bw}")
            if bh > 0 and (y < 0 or y > bh):
                issues.append(f"step {idx}: tap y={y} outside baseline height={bh}")
        if t in {"rotate_identity", "full_reset"}:
            prev = steps[idx - 1] if idx > 0 and isinstance(steps[idx - 1], dict) else None
            if not prev or prev.get("type") != "wait" or _f(prev.get("seconds", 0.0), 0.0) < MIN_EXIT_COOLDOWN:
                issues.append(f"step {idx}: missing >= {MIN_EXIT_COOLDOWN:.1f}s cooldown before {t}")

    parts = compute_runtime_parts(steps)
    if parts.expected_seconds < MIN_SEQUENCE_FLOOR:
        issues.append(
            f"runtime floor {parts.expected_seconds:.2f}s below realistic minimum {MIN_SEQUENCE_FLOOR:.0f}s"
        )
    if len(steps) < 8:
        issues.append("sequence has very few steps")
    return issues


def _merge_adjacent_waits(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for step in steps:
        if (
            out
            and isinstance(out[-1], dict)
            and out[-1].get("type") == "wait"
            and isinstance(step, dict)
            and step.get("type") == "wait"
        ):
            out[-1]["seconds"] = round(
                max(0.0, min(300.0, _f(out[-1].get("seconds", 0.0), 0.0) + _f(step.get("seconds", 0.0), 0.0))),
                3,
            )
        else:
            out.append(step)
    return out


def apply_conservative_fixes(steps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    fixed = [dict(step) if isinstance(step, dict) else step for step in steps]
    changes: list[str] = []

    # 1) Stabilize open_url when action immediately follows.
    for idx, step in enumerate(fixed):
        if not isinstance(step, dict) or step.get("type") != "open_url":
            continue
        nxt = fixed[idx + 1] if idx + 1 < len(fixed) and isinstance(fixed[idx + 1], dict) else None
        if nxt and _is_action_step(nxt):
            cur = _f(step.get("post_wait_secs", 0.0), 0.0)
            if cur < MIN_OPEN_URL_POST_WAIT:
                step["post_wait_secs"] = MIN_OPEN_URL_POST_WAIT
                changes.append(f"step {idx}: set open_url post_wait_secs={MIN_OPEN_URL_POST_WAIT}")

    # 2) Ensure cooldown before rotate_identity/full_reset.
    idx = 0
    while idx < len(fixed):
        step = fixed[idx]
        if isinstance(step, dict) and step.get("type") in {"rotate_identity", "full_reset"}:
            prev = fixed[idx - 1] if idx > 0 and isinstance(fixed[idx - 1], dict) else None
            if not prev or prev.get("type") != "wait":
                fixed.insert(idx, {"type": "wait", "seconds": MIN_EXIT_COOLDOWN})
                changes.append(f"step {idx}: inserted cooldown wait before {step.get('type')}")
                idx += 1
            elif _f(prev.get("seconds", 0.0), 0.0) < MIN_EXIT_COOLDOWN:
                prev["seconds"] = MIN_EXIT_COOLDOWN
                changes.append(f"step {idx-1}: raised cooldown wait to {MIN_EXIT_COOLDOWN}s")
        idx += 1

    # 3) Floor runtime to realistic minimum by extending final dwell.
    parts = compute_runtime_parts([s for s in fixed if isinstance(s, dict)])
    if parts.expected_seconds < MIN_SEQUENCE_FLOOR:
        deficit = round(MIN_SEQUENCE_FLOOR - parts.expected_seconds, 3)
        inserted = False
        for i in range(len(fixed) - 1, -1, -1):
            st = fixed[i]
            if isinstance(st, dict) and st.get("type") == "wait":
                st["seconds"] = round(max(0.0, _f(st.get("seconds", 0.0), 0.0) + deficit), 3)
                inserted = True
                changes.append(f"step {i}: increased final wait by {deficit:.3f}s to hit runtime floor")
                break
        if not inserted:
            fixed.append({"type": "wait", "seconds": round(deficit, 3)})
            changes.append(f"appended terminal wait {deficit:.3f}s to hit runtime floor")

    fixed = _merge_adjacent_waits([s for s in fixed if isinstance(s, dict)])
    return fixed, changes


def load_sequence(path: Path) -> list[dict[str, Any]]:
    from sequence_normalize import unwrap_sequence_document

    payload = json.loads(path.read_text(encoding="utf-8"))
    try:
        steps, _meta = unwrap_sequence_document(payload)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    if not isinstance(steps, list):
        raise ValueError(f"{path}: steps must be a JSON array")
    return [s for s in steps if isinstance(s, dict)]


def runtime_for_group_config(sequence_runtime: dict[str, float]) -> list[tuple[str, str, float]]:
    if not GROUPS_CFG.exists():
        return []
    payload = json.loads(GROUPS_CFG.read_text(encoding="utf-8"))
    out: list[tuple[str, str, float]] = []
    for group in payload.get("groups", []):
        gname = str(group.get("name", "Group"))
        phones = group.get("phones", {})
        if not isinstance(phones, dict):
            continue
        for serial, ent in phones.items():
            total = 0.0
            if isinstance(ent, dict) and isinstance(ent.get("steps"), list):
                total = compute_runtime_parts([s for s in ent["steps"] if isinstance(s, dict)]).expected_seconds
            out.append((gname, str(serial), total))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit sequence runtime realism and apply conservative timing fixes.")
    ap.add_argument("--fix", action="store_true", help="Apply conservative auto-fixes in-place.")
    ap.add_argument("--report", type=Path, default=REPORT_PATH, help="Output markdown report path.")
    args = ap.parse_args()

    seq_paths = sorted(SEQUENCES_DIR.glob("*.json"))
    rows: list[dict[str, Any]] = []
    fixed_files: list[tuple[Path, list[str], float, float]] = []
    sequence_runtime: dict[str, float] = {}

    for path in seq_paths:
        steps = load_sequence(path)
        parts = compute_runtime_parts(steps)
        issues = static_issues(path, steps)
        before = parts.expected_seconds
        after = before
        if args.fix:
            fixed_steps, changes = apply_conservative_fixes(steps)
            if changes and fixed_steps != steps:
                path.write_text(json.dumps(fixed_steps, indent=2) + "\n", encoding="utf-8")
                after = compute_runtime_parts(fixed_steps).expected_seconds
                fixed_files.append((path, changes, before, after))
                steps = fixed_steps
                issues = static_issues(path, steps)
                parts = compute_runtime_parts(steps)
        sequence_runtime[path.name] = parts.expected_seconds
        rows.append(
            {
                "name": path.name,
                "steps": len(steps),
                "expected_seconds": parts.expected_seconds,
                "issues": issues,
            }
        )

    rows_sorted = sorted(rows, key=lambda r: r["expected_seconds"])
    suspicious = [r for r in rows_sorted if r["issues"]]
    top_short = rows_sorted[:20]
    group_runtime = runtime_for_group_config(sequence_runtime)

    lines: list[str] = []
    lines.append("# Sequence Runtime Audit (generated)")
    lines.append("")
    lines.append(f"- Sequence files scanned: **{len(rows)}**")
    lines.append(f"- Suspicious sequences (runtime/static): **{len(suspicious)}**")
    lines.append(f"- Auto-fixed files this run: **{len(fixed_files)}**")
    lines.append("")
    lines.append("## Top short sequences (expected runtime floor)")
    lines.append("")
    lines.append("| sequence | steps | expected_seconds | issue_count |")
    lines.append("|---|---:|---:|---:|")
    for r in top_short:
        lines.append(f"| `{r['name']}` | {r['steps']} | {r['expected_seconds']:.2f} | {len(r['issues'])} |")
    lines.append("")
    lines.append("## Suspicious sequences (ranked)")
    lines.append("")
    for r in suspicious[:80]:
        lines.append(f"- `{r['name']}` — {r['expected_seconds']:.2f}s")
        for issue in r["issues"][:6]:
            lines.append(f"  - {issue}")
    lines.append("")
    lines.append("## Group runtime totals (`groups_config.json` inline steps)")
    lines.append("")
    if group_runtime:
        lines.append("| group | serial | expected_seconds |")
        lines.append("|---|---|---:|")
        for gname, serial, secs in group_runtime:
            lines.append(f"| `{gname}` | `{serial}` | {secs:.2f} |")
    else:
        lines.append("- No `groups_config.json` inline-step entries found.")
    lines.append("")
    lines.append("## Applied conservative fixes")
    lines.append("")
    if fixed_files:
        for path, changes, before, after in fixed_files:
            lines.append(f"- `{path.name}`: {before:.2f}s -> {after:.2f}s")
            for c in changes:
                lines.append(f"  - {c}")
    else:
        lines.append("- None")
    lines.append("")
    args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"scanned={len(rows)} suspicious={len(suspicious)} fixed={len(fixed_files)}")
    print(f"report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
