#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from cpharm_defaults import home_combo_v2_key_for_basename, iter_home_combo_v2_sequence_paths
from sequence_normalize import unwrap_sequence_document

ROOT = Path(__file__).resolve().parents[1]
SEQUENCE_DIR = ROOT / "automation" / "recordings" / "sequences"
DEFAULT_DOC_PATH = ROOT / "docs" / "sequence_naming_and_schema.generated.md"

COMBO_FILENAME_RE = re.compile(
    r"^sequence_home_combo_v2_"
    r"entry-(?P<entry>[a-z0-9_]+)_"
    r"ad-(?P<ad>off|on)_"
    r"footer-(?P<footer>left|center|right)_"
    r"hero-(?P<hero>off|on)_"
    r"bottom-(?P<bottom>left|center|right)_"
    r"timer-(?P<timer>single96|stacked)_"
    r"postad-(?P<postad>off|on)_"
    r"branch-(?P<branch>glass_art|stats|settings|timer_reset)"
    r"\.json$"
)

DWELL_BAND_BY_TIMER = {
    "single96": "dwell-single",
    "stacked": "dwell-stacked",
}

EXIT_MODE_BY_TIMER = {
    "single96": "exit-back",
    "stacked": "exit-tap-dismiss",
}

TAIL_MODE_WITH_IP_ID = "tail-ipid"
TAIL_MODE_NO_IP_ID = "tail-none"
IP_ID_TAIL = ("rotate_identity", "wait", "full_reset")


@dataclass(frozen=True)
class ComboSchema:
    file_name: str
    combo: str
    variant: str
    dwell_band: str
    exit_mode: str
    ip_id_tail: str
    entry: str
    ad: str
    footer: str
    hero: str
    bottom: str
    timer: str
    postad: str
    branch: str


class SchemaError(Exception):
    pass


def _load_steps(path: Path) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SchemaError(
            f"{path.name}: invalid JSON at line {exc.lineno}, col {exc.colno}: {exc.msg}"
        ) from exc
    try:
        steps, _meta = unwrap_sequence_document(payload)
    except ValueError as exc:
        raise SchemaError(f"{path.name}: {exc}") from exc
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            raise SchemaError(f"{path.name}: step {idx} is not an object")
    return steps


def _step_types(steps: list[dict]) -> list[str]:
    return [str(step.get("type")) for step in steps if step.get("type")]


def _has_tap(steps: list[dict], x: int, y: int) -> bool:
    for step in steps:
        if step.get("type") != "tap":
            continue
        if step.get("x") == x and step.get("y") == y:
            return True
    return False


def _has_key_back(steps: list[dict]) -> bool:
    for step in steps:
        if step.get("type") != "keyevent":
            continue
        if str(step.get("key")) == "4":
            return True
    return False


def _combo_from_match(file_name: str, match: re.Match[str], steps: list[dict]) -> ComboSchema:
    entry = match.group("entry")
    ad = match.group("ad")
    footer = match.group("footer")
    hero = match.group("hero")
    bottom = match.group("bottom")
    timer = match.group("timer")
    postad = match.group("postad")
    branch = match.group("branch")

    step_types = _step_types(steps)
    has_ip_id_tail = tuple(step_types[-3:]) == IP_ID_TAIL
    if not has_ip_id_tail:
        raise SchemaError(
            f"{file_name}: expected tail {list(IP_ID_TAIL)} for combo sequences"
        )

    dwell_band = DWELL_BAND_BY_TIMER[timer]
    expected_exit = EXIT_MODE_BY_TIMER[timer]

    if timer == "single96":
        if not _has_key_back(steps):
            raise SchemaError(f"{file_name}: timer-single96 requires keyevent BACK exit")
    elif timer == "stacked":
        if not _has_tap(steps, 455, 660):
            raise SchemaError(f"{file_name}: timer-stacked requires tap-dismiss at (455,660)")
    if postad == "on" and not _has_tap(steps, 648, 1492):
        raise SchemaError(f"{file_name}: postad-on requires bottom ad tap at (648,1492)")
    if branch == "glass_art" and not _has_tap(steps, 162, 1458):
        raise SchemaError(f"{file_name}: branch-glass_art requires tap at (162,1458)")
    if branch == "stats" and not _has_tap(steps, 450, 1455):
        raise SchemaError(f"{file_name}: branch-stats requires tap at (450,1455)")
    if branch == "settings" and not _has_tap(steps, 772, 1455):
        raise SchemaError(f"{file_name}: branch-settings requires tap at (772,1455)")
    if branch == "timer_reset" and not _has_tap(steps, 455, 660):
        raise SchemaError(f"{file_name}: branch-timer_reset requires reset tap at (455,660)")

    return ComboSchema(
        file_name=file_name,
        combo="home_combo",
        variant=f"entry-{entry}.footer-{footer}.hero-{hero}.bottom-{bottom}",
        dwell_band=dwell_band,
        exit_mode=expected_exit,
        ip_id_tail=TAIL_MODE_WITH_IP_ID if has_ip_id_tail else TAIL_MODE_NO_IP_ID,
        entry=entry,
        ad=ad,
        footer=footer,
        hero=hero,
        bottom=bottom,
        timer=timer,
        postad=postad,
        branch=branch,
    )


def collect_combo_schema(sequence_dir: Path) -> tuple[list[ComboSchema], list[str]]:
    """Validate v2 home-combo files, including **renamed** basenames (see ``_sequence_rename_basename_map.json``)."""
    schemas: list[ComboSchema] = []
    errors: list[str] = []
    for path in iter_home_combo_v2_sequence_paths(sequence_dir):
        file_key = path.name
        if COMBO_FILENAME_RE.match(file_key):
            canon_key = file_key
        else:
            canon_key = home_combo_v2_key_for_basename(file_key) or ""
        match = COMBO_FILENAME_RE.match(canon_key) if canon_key else None
        if not match:
            errors.append(
                f"{path.name}: cannot resolve v2 combo canonical key "
                "(expected legacy ``sequence_home_combo_v2_*.json`` name or a basename listed under "
                "such keys in automation/recordings/_sequence_rename_basename_map.json)"
            )
            continue
        try:
            steps = _load_steps(path)
            schemas.append(_combo_from_match(path.name, match, steps))
        except SchemaError as exc:
            errors.append(str(exc))
    return schemas, errors


def _render_docs(schemas: list[ComboSchema]) -> str:
    by_dwell = Counter(item.dwell_band for item in schemas)
    by_exit = Counter(item.exit_mode for item in schemas)
    by_tail = Counter(item.ip_id_tail for item in schemas)

    lines: list[str] = []
    lines.append("# Sequence naming and schema (generated)")
    lines.append("")
    lines.append("Generated by `automation/validate_sequence_schema.py`.")
    lines.append("")
    lines.append(
        "- Combo matrix JSON may ship under hashed basenames; validation resolves canonical "
        "`sequence_home_combo_v2_*` keys via `automation/recordings/_sequence_rename_basename_map.json`."
    )
    lines.append("")
    lines.append("## Deterministic convention (combo family)")
    lines.append("")
    lines.append(
        "- Filename grammar: "
        "`sequence_home_combo_v2_entry-<entry>_ad-<ad>_footer-<footer>_hero-<hero>_bottom-<bottom>_timer-<timer>_postad-<postad>_branch-<branch>.json`"
    )
    lines.append("- Canonical schema keys per file:")
    lines.append("  - `combo`: fixed family id (`home_combo`)")
    lines.append("  - `variant`: `entry-<entry>.footer-<footer>.hero-<hero>.bottom-<bottom>`")
    lines.append("  - `dwell_band`: derived from `timer` (`dwell-single|dwell-stacked`)")
    lines.append("  - `exit_mode`: derived from timer behavior (`exit-back|exit-tap-dismiss`)")
    lines.append("  - `ip_id_tail`: `tail-ipid` iff ending types are `rotate_identity -> wait -> full_reset`")
    lines.append("")
    lines.append("## Allowed tokens")
    lines.append("")
    lines.append("- `entry`: `direct` | `google_home`")
    lines.append("- `ad`: `off` | `on`")
    lines.append("- `footer`: `left` | `center` | `right`")
    lines.append("- `hero`: `off` | `on`")
    lines.append("- `bottom`: `left` | `center` | `right`")
    lines.append("- `timer`: `single96` | `stacked`")
    lines.append("- `postad`: `off` | `on`")
    lines.append("- `branch`: `glass_art` | `stats` | `settings` | `timer_reset`")
    lines.append("")
    lines.append(f"## Observed inventory ({len(schemas)} combo files)")
    lines.append("")
    lines.append("- Dwell bands:")
    for key in sorted(by_dwell):
        lines.append(f"  - `{key}`: {by_dwell[key]}")
    lines.append("- Exit modes:")
    for key in sorted(by_exit):
        lines.append(f"  - `{key}`: {by_exit[key]}")
    lines.append("- IP/ID tails:")
    for key in sorted(by_tail):
        lines.append(f"  - `{key}`: {by_tail[key]}")
    lines.append("")
    lines.append("## Validation commands")
    lines.append("")
    lines.append("- Validate schema only:")
    lines.append("  - `py -3 automation/validate_sequence_schema.py --check`")
    lines.append("  - `python automation/validate_sequence_schema.py --check`")
    lines.append("- Regenerate this doc + validate:")
    lines.append(
        "  - `py -3 automation/validate_sequence_schema.py --write-doc docs/sequence_naming_and_schema.generated.md`"
    )
    lines.append(
        "  - `python automation/validate_sequence_schema.py --write-doc docs/sequence_naming_and_schema.generated.md`"
    )
    lines.append("- Full sequence checks (existing + schema helper):")
    lines.append("  - `py -3 automation/verify_sequences.py`")
    lines.append("  - `py -3 automation/validate_sequence_schema.py --check`")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate deterministic naming/schema convention for combo sequence files."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate schema rules and exit non-zero on mismatch.",
    )
    parser.add_argument(
        "--write-doc",
        nargs="?",
        const=str(DEFAULT_DOC_PATH),
        help="Write generated schema doc (default: docs/sequence_naming_and_schema.generated.md).",
    )
    args = parser.parse_args()

    run_check = args.check or not args.write_doc
    schemas, errors = collect_combo_schema(SEQUENCE_DIR)

    if run_check and not schemas and not errors:
        print(
            "WARN: no home_combo_v2 matrix JSON found under automation/recordings/sequences "
            "(no legacy glob matches and no rename-map targets on disk)."
        )

    if run_check and errors:
        print(f"FAILED: {len(errors)} schema issue(s)")
        for issue in errors:
            print(f"- {issue}")
        return 1

    if run_check:
        print(f"OK: validated {len(schemas)} combo sequence file(s)")

    if args.write_doc:
        out_path = Path(args.write_doc)
        if not out_path.is_absolute():
            out_path = ROOT / out_path
        out_path.write_text(_render_docs(schemas), encoding="utf-8")
        print(f"WROTE: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
