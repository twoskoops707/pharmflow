#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sequence_normalize import unwrap_sequence_document

ROOT = Path(__file__).resolve().parent.parent
SEQUENCE_DIR = ROOT / "automation" / "recordings" / "sequences"
GROUPS_CONFIG = ROOT / "automation" / "recordings" / "groups_config.json"

TAB_X_LANES = (162, 450, 520, 528, 690, 772)
TAB_Y_MIN = 1400
AD_WAIT_MIN = 10.0
AD_WAIT_MAX = 45.0
TIMER_WAIT_MIN = 60.0
FOLLOW_TIMER_SHORT_WAIT_MIN = 10.0


@dataclass(frozen=True)
class SequenceDoc:
    label: str
    steps: list[dict[str, Any]]
    path_hint: str


@dataclass(frozen=True)
class Analysis:
    ad_indices: list[int]
    timer_indices: list[int]
    tab_indices: list[int]
    maybe_timer_missing: bool
    maybe_tab_missing: bool


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_docs() -> list[SequenceDoc]:
    docs: list[SequenceDoc] = []

    for path in sorted(SEQUENCE_DIR.rglob("*.json")):
        raw = _load_json(path)
        steps_any, meta = unwrap_sequence_document(raw)
        steps: list[dict[str, Any]] = [s for s in steps_any if isinstance(s, dict)]
        label = ""
        if isinstance(raw, dict):
            label = str(raw.get("label", "")).strip()
        if not label and isinstance(meta, dict):
            label = str(meta.get("scenario_title", "")).strip()
        docs.append(
            SequenceDoc(
                label=label,
                steps=steps,
                path_hint=f"sequence:{path.relative_to(SEQUENCE_DIR).as_posix()}",
            )
        )

    if GROUPS_CONFIG.exists():
        raw = _load_json(GROUPS_CONFIG)
        groups = raw.get("groups")
        if isinstance(groups, list):
            for gi, group in enumerate(groups):
                if not isinstance(group, dict):
                    continue
                phones = group.get("phones")
                if not isinstance(phones, dict):
                    continue
                for serial, phone_payload in phones.items():
                    if not isinstance(phone_payload, dict):
                        continue
                    steps_any = phone_payload.get("steps", [])
                    if not isinstance(steps_any, list):
                        continue
                    steps: list[dict[str, Any]] = [
                        s for s in steps_any if isinstance(s, dict)
                    ]
                    docs.append(
                        SequenceDoc(
                            label=f"group-{gi + 1}:{serial}",
                            steps=steps,
                            path_hint=f"groups_config:{serial}",
                        )
                    )

    return docs


def _step_wait_seconds(step: dict[str, Any]) -> float | None:
    if step.get("type") != "wait":
        return None
    try:
        return float(step.get("seconds", 0))
    except (TypeError, ValueError):
        return None


def _is_tab_tap(step: dict[str, Any]) -> bool:
    if step.get("type") != "tap":
        return False
    x = step.get("x")
    y = step.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return False
    if y < TAB_Y_MIN:
        return False
    return any(abs(float(x) - lane) <= 55 for lane in TAB_X_LANES)


def _has_label_token(text: str, token: str) -> bool:
    return re.search(rf"(?:^|[_\\-\\s]){re.escape(token)}(?:$|[_\\-\\s])", text) is not None


def _is_ad_tap(steps: list[dict[str, Any]], idx: int, ad_hint_enabled: bool) -> bool:
    step = steps[idx]
    if step.get("type") != "tap":
        return False
    if _is_tab_tap(step):
        return False
    x = step.get("x")
    y = step.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return False
    # Conservative ad geometry ranges (middle / footer ad zones).
    in_mid_zone = 660 <= float(y) <= 940 and 220 <= float(x) <= 720
    in_footer_zone = 1280 <= float(y) <= 1520 and 280 <= float(x) <= 760
    if not (in_mid_zone or in_footer_zone):
        return False

    # Require dwell-like wait right after tap to avoid false positives.
    for nxt in steps[idx + 1 : idx + 4]:
        sec = _step_wait_seconds(nxt)
        if sec is None:
            continue
        if sec >= TIMER_WAIT_MIN:
            # Likely timer hold, not ad dwell.
            return False
        if AD_WAIT_MIN <= sec <= AD_WAIT_MAX:
            return True
    # Without an ad hint, do not classify geometry-only taps as ad clicks.
    if not ad_hint_enabled:
        return False
    return False


def _analyze(doc: SequenceDoc) -> Analysis:
    ad_indices: list[int] = []
    timer_indices: list[int] = []
    tab_indices: list[int] = []

    token_space = f"{doc.path_hint.lower()} {doc.label.lower()}"
    ad_hint_enabled = _has_label_token(token_space, "ad") or ("_ad-" in token_space)

    for idx, step in enumerate(doc.steps):
        if _is_tab_tap(step):
            tab_indices.append(idx)
        if _is_ad_tap(doc.steps, idx, ad_hint_enabled=ad_hint_enabled):
            ad_indices.append(idx)

        sec = _step_wait_seconds(step)
        if sec is not None and sec >= TIMER_WAIT_MIN:
            # Long wait likely timer; require follow-up micro action + short/medium wait.
            has_timer_tail = False
            for nxt in doc.steps[idx + 1 : idx + 4]:
                t = nxt.get("type")
                if t in ("swipe", "tap"):
                    has_timer_tail = True
                    continue
                nsec = _step_wait_seconds(nxt)
                if nsec is not None and nsec >= FOLLOW_TIMER_SHORT_WAIT_MIN:
                    has_timer_tail = True
            if has_timer_tail:
                timer_indices.append(idx)

    maybe_timer_missing = (not timer_indices) and _has_label_token(token_space, "timer")
    maybe_tab_missing = (not tab_indices) and _has_label_token(token_space, "tab")
    return Analysis(
        ad_indices=ad_indices,
        timer_indices=timer_indices,
        tab_indices=tab_indices,
        maybe_timer_missing=maybe_timer_missing,
        maybe_tab_missing=maybe_tab_missing,
    )


def validate_docs(docs: list[SequenceDoc]) -> tuple[list[str], list[str], int]:
    violations: list[str] = []
    ambiguous: list[str] = []
    ad_docs = 0
    for doc in docs:
        analysis = _analyze(doc)
        if not analysis.ad_indices:
            continue
        ad_docs += 1

        first_ad = min(analysis.ad_indices)
        if analysis.maybe_timer_missing:
            ambiguous.append(f"{doc.path_hint}: ad detected but timer block not confidently detected")
        if analysis.maybe_tab_missing:
            ambiguous.append(f"{doc.path_hint}: ad detected but tab-nav block not confidently detected")

        if analysis.timer_indices and first_ad < min(analysis.timer_indices):
            violations.append(
                f"{doc.path_hint}: ad step index {first_ad} appears before timer index {min(analysis.timer_indices)}"
            )
        if analysis.tab_indices and first_ad < min(analysis.tab_indices):
            violations.append(
                f"{doc.path_hint}: ad step index {first_ad} appears before tab-nav index {min(analysis.tab_indices)}"
            )
        if analysis.timer_indices and analysis.tab_indices:
            must_after = max(min(analysis.timer_indices), min(analysis.tab_indices))
            if first_ad < must_after:
                violations.append(
                    f"{doc.path_hint}: ad step index {first_ad} appears before timer+tab prerequisite index {must_after}"
                )

    return violations, ambiguous, ad_docs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate sequence ordering: timer + tab-nav before ad-click steps."
    )
    parser.add_argument(
        "--strict-missing",
        action="store_true",
        help="Treat missing timer/tab blocks in ad-bearing docs as failures (default: warnings).",
    )
    args = parser.parse_args()

    docs = _iter_docs()
    violations, ambiguous, ad_docs = validate_docs(docs)
    if args.strict_missing and ambiguous:
        violations.extend(ambiguous)
        ambiguous = []

    if violations:
        print(f"FAILED: {len(violations)} ordering issue(s) across {ad_docs} ad-bearing docs")
        for issue in violations[:200]:
            print(f"- {issue}")
        if len(violations) > 200:
            print(f"- ... {len(violations) - 200} more")
        if ambiguous:
            print(f"WARN: {len(ambiguous)} ambiguous doc(s)")
            for item in ambiguous[:80]:
                print(f"- {item}")
            if len(ambiguous) > 80:
                print(f"- ... {len(ambiguous) - 80} more")
        return 1

    print(f"OK: validated ordering in {len(docs)} doc(s); ad-bearing docs={ad_docs}")
    if ambiguous:
        print(f"WARN: {len(ambiguous)} ambiguous doc(s) left unchanged")
        for item in ambiguous[:80]:
            print(f"- {item}")
        if len(ambiguous) > 80:
            print(f"- ... {len(ambiguous) - 80} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
