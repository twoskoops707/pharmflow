#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import json

from sequence_normalize import normalize_automation_steps, unwrap_sequence_document


def _load_steps(p: Path) -> list:
    data = json.loads(p.read_text(encoding="utf-8"))
    try:
        steps, _meta = unwrap_sequence_document(data)
    except ValueError as exc:
        raise AssertionError(f"{p.name}: {exc}") from exc
    if not isinstance(steps, list):
        raise AssertionError(f"{p.name}: expected steps array")
    return steps


def _propagate_template(default_steps: list, groups: list[dict]) -> None:
    for g in groups:
        phones = g.get("phones") or {}
        if not isinstance(phones, dict):
            continue
        for _, pdata in phones.items():
            if not isinstance(pdata, dict):
                continue
            if bool(pdata.get("use_default_template", True)):
                pdata["steps"] = list(default_steps)


def main() -> int:
    seq_dir = Path(__file__).resolve().parent / "recordings" / "sequences"
    files = sorted(seq_dir.glob("*.json"))
    if not files:
        raise AssertionError("No sample sequence JSON files found")

    for fp in files:
        raw = _load_steps(fp)
        norm = normalize_automation_steps(raw)
        if len(norm) != len(raw):
            raise AssertionError(
                f"{fp.name}: normalization changed step count ({len(raw)} -> {len(norm)})"
            )

    default_a = normalize_automation_steps(_load_steps(files[0]))
    default_b = normalize_automation_steps(_load_steps(files[min(1, len(files) - 1)]))
    override = normalize_automation_steps(_load_steps(files[-1]))

    groups = [
        {
            "name": "Group 1",
            "phones": {
                "phone-template": {
                    "steps": list(default_a),
                    "use_default_template": True,
                },
                "phone-override": {
                    "steps": list(override),
                    "use_default_template": False,
                },
            },
        }
    ]
    _propagate_template(default_b, groups)
    pmap = groups[0]["phones"]
    assert len(pmap["phone-template"]["steps"]) == len(default_b), "template did not update"
    assert len(pmap["phone-override"]["steps"]) == len(override), "override was unexpectedly replaced"

    print(f"ok: validated {len(files)} sequence files + template propagation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
