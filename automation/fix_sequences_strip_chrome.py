#!/usr/bin/env python3
"""
Remove Chrome pinning from recorded sequence JSON so ``open_url`` / cookie clears /
``close_app`` resolve the device default browser (see ``browser_pkg_for_clear``).

Deterministic rewrite: parse JSON, mutate in place, write only when changed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_AUTOMATION_DIR = Path(__file__).resolve().parent
if str(_AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(_AUTOMATION_DIR))

from device_open_url import _component_is_chrome

# Legacy AOSP package ids that are not MuMu Browser / Chrome on real farms.
_LEGACY_PINNED_PACKAGES = frozenset(
    {
        "com.android.browser",
    }
)

# Mirror ``device_open_url._CHROME_PACKAGE_PREFIXES`` for bare package strings.
_CHROME_PKG_PREFIXES = (
    "com.android.chrome",
    "com.chrome.beta",
    "com.chrome.dev",
    "com.chrome.canary",
    "com.google.android.apps.chrome",
    "org.chromium.chrome",
)

_COSMETIC_KEYS = frozenset(
    {
        "label",
        "description",
        "note",
        "notes",
        "comment",
        "title",
        "hint",
        "message",
        "summary",
    }
)

_CHROME_WORD = re.compile(r"\bChrome\b")


def package_name_is_chrome(pkg: str) -> bool:
    p = (pkg or "").strip().lower()
    if not p:
        return False
    for known in _CHROME_PKG_PREFIXES:
        if p == known or p.startswith(known + "."):
            return True
    return False


def _replace_chrome_display_word(s: str) -> str:
    return _CHROME_WORD.sub("browser", s)


def walk_cosmetic_strings(obj: Any) -> bool:
    """Replace standalone word ``Chrome`` → ``browser`` in cosmetic string fields."""
    changed = False
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and k in _COSMETIC_KEYS:
                nv = _replace_chrome_display_word(v)
                if nv != v:
                    obj[k] = nv
                    changed = True
            else:
                if walk_cosmetic_strings(v):
                    changed = True
    elif isinstance(obj, list):
        for item in obj:
            if walk_cosmetic_strings(item):
                changed = True
    return changed


def strip_chrome_from_step(step: dict[str, Any]) -> bool:
    changed = False
    t = step.get("type")
    if t == "open_url":
        bc_raw = step.get("browser_component")
        if isinstance(bc_raw, str) and bc_raw.strip():
            if _component_is_chrome(bc_raw.strip()):
                step.pop("browser_component", None)
                changed = True
        pkg = str(step.get("package", "")).strip()
        if package_name_is_chrome(pkg):
            step.pop("package", None)
            changed = True
            if str(step.get("activity", "")).strip():
                step.pop("activity", None)
                changed = True
    elif t in ("clear_cookies", "close_app", "launch_app"):
        pkg = str(step.get("package", "")).strip()
        if package_name_is_chrome(pkg) or pkg in _LEGACY_PINNED_PACKAGES:
            step.pop("package", None)
            changed = True
    return changed


def _strip_steps_recursive(node: Any) -> bool:
    """Walk arbitrary JSON tree; strip Chrome pinning from every step-shaped dict."""
    changed = False
    if isinstance(node, dict):
        if strip_chrome_from_step(node):
            changed = True
        for v in node.values():
            if _strip_steps_recursive(v):
                changed = True
    elif isinstance(node, list):
        for item in node:
            if _strip_steps_recursive(item):
                changed = True
    return changed


def strip_chrome_document_in_place(data: Any) -> bool:
    changed = _strip_steps_recursive(data)
    if walk_cosmetic_strings(data):
        changed = True
    return changed


def strip_chrome_steps_list_in_place(steps: list[Any]) -> bool:
    changed = False
    for item in steps:
        if isinstance(item, dict) and strip_chrome_from_step(item):
            changed = True
    return changed


def process_file(path: Path, *, dry_run: bool) -> bool:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    before = raw
    if not strip_chrome_document_in_place(data):
        return False
    out = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if out == before:
        return False
    if not dry_run:
        path.write_text(out, encoding="utf-8")
    return True


def iter_json_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.json") if p.is_file())


def main() -> int:
    ap = argparse.ArgumentParser(description="Strip Chrome pinning from sequence JSON files.")
    ap.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Directory tree of JSON sequences (default: repo sequences/ + recordings/sequences)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes only; do not write files",
    )
    args = ap.parse_args()
    repo = _AUTOMATION_DIR.parent
    roots: list[Path]
    if args.root is not None:
        roots = [args.root.resolve()]
    else:
        roots = [
            repo / "sequences",
            _AUTOMATION_DIR / "recordings" / "sequences",
        ]
    roots = [r for r in roots if r.is_dir()]
    if not roots:
        print("Error: no sequence directories found", file=sys.stderr)
        return 1

    modified = 0
    for root in roots:
        for path in iter_json_files(root):
            try:
                if process_file(path, dry_run=args.dry_run):
                    modified += 1
                    print(f"{'would write' if args.dry_run else 'updated'}: {path.relative_to(repo)}")
            except (json.JSONDecodeError, OSError) as exc:
                print(f"Error: {path}: {exc}", file=sys.stderr)
                return 1

    print(f"Done. Files {'that would change' if args.dry_run else 'modified'}: {modified}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
