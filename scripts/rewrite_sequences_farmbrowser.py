#!/usr/bin/env python3
"""Rewrite all sequence JSON to FarmBrowser — preferred_browser, packages, tags."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from automation.config import BROWSER_FARMBROWSER  # noqa: E402

FB = BROWSER_FARMBROWSER
FB_LABEL = "FarmBrowser"
FB_TAG = "farmbrowser"

OLD_PKGS = (
    "org.chromium.chrome",
    "com.android.chrome",
    "org.mozilla.firefox",
    "com.brave.browser",
    "com.duckduckgo.mobile.android",
    "com.opera.browser",
    "com.mumudroid.browser",
)

LABEL_REPLACEMENTS = (
    ("Chromium", FB_LABEL),
    ("Firefox", FB_LABEL),
    ("Brave", FB_LABEL),
    ("DuckDuckGo", FB_LABEL),
    ("Opera", FB_LABEL),
    ("MuMu Browser", FB_LABEL),
)

DEFAULT_ROOTS = (
    ROOT / "automation" / "recordings" / "sequences",
    Path(r"C:\PharmFlow\automation\recordings\sequences"),
    Path(r"C:\PharmFlow\sequences"),
)


def _patch_step(step: dict) -> None:
    params = step.get("params")
    if isinstance(params, dict):
        pkg = str(params.get("package") or "").strip()
        if pkg in OLD_PKGS:
            params["package"] = FB
    desc = str(step.get("description") or "")
    for old, new in LABEL_REPLACEMENTS:
        if old in desc:
            step["description"] = desc.replace(old, new)
            break


def rewrite_file(path: Path, *, dry_run: bool = False) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    changed = False

    if str(data.get("preferred_browser") or "") in OLD_PKGS:
        data["preferred_browser"] = FB
        changed = True
    elif not data.get("preferred_browser"):
        data["preferred_browser"] = FB
        changed = True

    meta = data.get("meta")
    if isinstance(meta, dict):
        if str(meta.get("browser") or "") in OLD_PKGS:
            meta["browser"] = FB
            changed = True
        if str(meta.get("browser_tag") or "") != FB_TAG:
            if meta.get("browser_tag"):
                meta["browser_tag"] = FB_TAG
                changed = True
            else:
                meta["browser_tag"] = FB_TAG
                changed = True
        if str(meta.get("browser_label") or "") != FB_LABEL:
            meta["browser_label"] = FB_LABEL
            changed = True

    steps = data.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict):
                before = json.dumps(step, sort_keys=True)
                _patch_step(step)
                if json.dumps(step, sort_keys=True) != before:
                    changed = True

    if not changed:
        return False
    if not dry_run:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def rewrite_tree(root: Path, *, dry_run: bool = False) -> int:
    n = 0
    if not root.is_dir():
        return 0
    for path in root.rglob("*.json"):
        if rewrite_file(path, dry_run=dry_run):
            n += 1
    return n


def main() -> int:
    dry = "--dry-run" in sys.argv
    args = [Path(a) for a in sys.argv[1:] if a != "--dry-run"]
    roots = args or list(DEFAULT_ROOTS)
    total = 0
    for root in roots:
        count = rewrite_tree(root, dry_run=dry)
        total += count
        print(f"{'Would rewrite' if dry else 'Rewrote'} {count} under {root}")
    print(f"total={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
