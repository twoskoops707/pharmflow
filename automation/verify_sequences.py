#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

_AUTOMATION_DIR = Path(__file__).resolve().parent
if str(_AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(_AUTOMATION_DIR))

from pharmflow_defaults import combo_sequence_basenames_from_rename_map
from sequence_normalize import load_sequence_steps_ui
from sequence_geometry import parse_wm_size_output, scale_point
from sequences_paths import fixtures_sequences_dir, resolve_sequences_dir


SUPPORTED_ACTION_TYPES = frozenset(
    {
        "open_url",
        "launch_app",
        "tap",
        "wait",
        "swipe",
        "keyevent",
        "close_app",
        "clear_cookies",
        "type_text",
        "rotate_identity",
        "full_reset",
    }
)
_PLAYSTORE_PACKAGES = frozenset({"com.android.vending"})


class VerifyError(Exception):
    pass


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VerifyError(
            f"{path}: invalid JSON at line {exc.lineno}, col {exc.colno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise VerifyError(f"{path}: failed to read file: {exc}") from exc


def _sequence_roots() -> list[tuple[Path, str]]:
    """(directory, label_prefix) for local production + CI fixtures."""
    roots: list[tuple[Path, str]] = []
    local = resolve_sequences_dir(create=False)
    if local.is_dir():
        roots.append((local, "local"))
    fx = fixtures_sequences_dir()
    if fx.is_dir():
        roots.append((fx, "fixture"))
    return roots


def _iter_step_collections(recordings_dir: Path):
    for seq_root, _tag in _sequence_roots():
        for sequence_path in sorted(seq_root.rglob("*.json")):
            if sequence_path.name.startswith("_"):
                continue
            payload = _load_json(sequence_path)
            try:
                steps, _meta = load_sequence_steps_ui(payload)
            except ValueError as exc:
                raise VerifyError(f"{sequence_path}: {exc}") from exc
            if not isinstance(steps, list):
                raise VerifyError(f"{sequence_path}: steps must be a JSON array")
            rel = sequence_path.relative_to(seq_root)
            yield f"sequence:{rel.as_posix()}", steps, sequence_path.name

    groups_path = recordings_dir / "groups_config.json"
    if groups_path.exists():
        groups_payload = _load_json(groups_path)
        groups = groups_payload.get("groups")
        if not isinstance(groups, list):
            raise VerifyError(f"{groups_path}: expected 'groups' to be a list")
        for group_idx, group in enumerate(groups):
            phones = group.get("phones", {})
            if not isinstance(phones, dict):
                continue
            for serial, phone_payload in phones.items():
                if not isinstance(phone_payload, dict):
                    continue
                steps = phone_payload.get("steps", [])
                if not isinstance(steps, list):
                    raise VerifyError(
                        f"{groups_path}: groups[{group_idx}].phones['{serial}'].steps "
                        "must be an array"
                    )
                label = f"groups_config:{serial}"
                yield label, steps, groups_path.name


def _normalized_wait_seconds(step: dict) -> float | None:
    if not isinstance(step, dict) or step.get("type") != "wait":
        return None
    try:
        return round(float(step.get("seconds", 0.0)), 6)
    except (TypeError, ValueError):
        return None


def _assert_no_consecutive_waits(
    label: str, steps: list[dict], errors: list[str]
) -> None:
    prev_was_wait = False
    for idx, step in enumerate(steps):
        is_wait = isinstance(step, dict) and step.get("type") == "wait"
        if is_wait and prev_was_wait:
            errors.append(
                f"{label}: consecutive wait steps at indexes {idx - 1}/{idx} "
                "(merge into one wait with combined duration)"
            )
        prev_was_wait = is_wait


def _assert_supported_action_types(
    label: str, steps: list[dict], errors: list[str]
) -> None:
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"{label}: step {idx} is not an object")
            continue
        action_type = step.get("type")
        if action_type not in SUPPORTED_ACTION_TYPES:
            errors.append(
                f"{label}: unsupported action type at step {idx}: {action_type!r}"
            )


def _assert_combo_ends_with_ip_id_block(
    label: str, file_name: str, steps: list[dict], errors: list[str]
) -> None:
    # Historically filenames contained ``_combo_``; after bulk renames the basename must match
    # ``_sequence_rename_basename_map.json`` keys for ``sequence_home_combo_v2_*`` / ``sequence_combo_*``.
    if "_combo_" not in file_name and file_name not in combo_sequence_basenames_from_rename_map():
        return

    step_types = [
        step.get("type") for step in steps if isinstance(step, dict) and step.get("type")
    ]
    if len(step_types) < 3:
        errors.append(f"{label}: combo sequence too short for IP+ID block")
        return

    tail = step_types[-3:]
    if tail != ["rotate_identity", "wait", "full_reset"]:
        errors.append(
            f"{label}: combo sequence must end with "
            "['rotate_identity', 'wait', 'full_reset']; got "
            f"{tail}"
        )


def _assert_age_verification_marker(label: str, steps: list[dict], anomalies: list[str]) -> None:
    has_marker = False
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("age_verification") is True or step.get("age_gate") is True:
            has_marker = True
            break
        if str(step.get("checkpoint", "")).strip().lower() in ("age_verification", "age_gate"):
            has_marker = True
            break
    if not has_marker:
        anomalies.append(
            f"{label}: missing age verification marker (age_verification/age_gate/checkpoint)"
        )


def _assert_no_playstore_packages(label: str, steps: list[dict], errors: list[str]) -> None:
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        pkg = str(step.get("package", "")).strip().lower()
        if pkg in _PLAYSTORE_PACKAGES:
            errors.append(f"{label}: step {idx} references Play Store package '{pkg}'")


def _assert_display_scaling_examples(errors: list[str]) -> None:
    wm_examples = (
        ("Physical size: 1080x1920\n", (1080, 1920)),
        ("Physical size: 1440x2560\nOverride size: 900x1600\n", (900, 1600)),
        ("Display size: 720x1280\n", (720, 1280)),
    )
    for raw, expected in wm_examples:
        parsed = parse_wm_size_output(raw)
        if parsed != expected:
            errors.append(f"display parse mismatch for '{raw.strip()}': got {parsed}, expected {expected}")
    sx, sy = scale_point(450, 800, 1080, 1920, 900, 1600)
    if (sx, sy) != (540, 960):
        errors.append(f"display scale mismatch for 900x1600->1080x1920 center: got {(sx, sy)}")


def main() -> int:
    root = Path(__file__).resolve().parent
    recordings_dir = root / "recordings"
    json_files = sorted(recordings_dir.rglob("*.json"))

    errors: list[str] = []
    anomalies: list[str] = []
    checked_collections = 0

    # 1) JSON validity for all recordings JSON.
    for json_path in json_files:
        try:
            _load_json(json_path)
        except VerifyError as exc:
            errors.append(str(exc))

    # 2-4) Sequence semantics.
    if not errors:
        for label, steps, file_name in _iter_step_collections(recordings_dir):
            checked_collections += 1
            _assert_supported_action_types(label, steps, errors)
            _assert_no_consecutive_waits(label, steps, errors)
            _assert_combo_ends_with_ip_id_block(label, file_name, steps, errors)
            _assert_age_verification_marker(label, steps, anomalies)
            _assert_no_playstore_packages(label, steps, errors)
        _assert_display_scaling_examples(errors)

    if errors:
        print(f"FAILED: {len(errors)} issue(s) found")
        for issue in errors:
            print(f"- {issue}")
        return 1

    print(
        "OK: validated "
        f"{len(json_files)} JSON file(s); checked {checked_collections} step collections"
    )
    if anomalies:
        print(f"WARN: {len(anomalies)} age-verification anomaly(s) detected")
        for issue in anomalies[:30]:
            print(f"- {issue}")
        if len(anomalies) > 30:
            print(f"- ... {len(anomalies) - 30} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
