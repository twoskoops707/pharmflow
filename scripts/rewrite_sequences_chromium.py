"""Rewrite sequence JSON text: MuMu Browser → Chromium (setup-installed browser)."""

from __future__ import annotations

import sys
from pathlib import Path

REPLACEMENTS = (
    ("MuMu Browser", "Chromium"),
    ("mumu browser", "Chromium"),
    ("MUMU Browser", "Chromium"),
    ("com.mumudroid.browser", "org.chromium.chrome"),
)


def rewrite_file(path: Path, *, dry_run: bool = False) -> bool:
    text = path.read_text(encoding="utf-8")
    new = text
    for old, repl in REPLACEMENTS:
        new = new.replace(old, repl)
    if new == text:
        return False
    if not dry_run:
        path.write_text(new, encoding="utf-8", newline="\n")
    return True


def rewrite_tree(root: Path, *, dry_run: bool = False) -> int:
    count = 0
    for path in root.rglob("*.json"):
        if rewrite_file(path, dry_run=dry_run):
            count += 1
    return count


def main() -> None:
    dry = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    roots = [Path(a) for a in args] if args else [
        Path("automation/recordings"),
        Path(r"C:\CPharm\automation\recordings"),
        Path(r"C:\CPharm\sequences"),
    ]
    total = 0
    for root in roots:
        if not root.exists():
            print(f"skip missing: {root}")
            continue
        n = rewrite_tree(root, dry_run=dry)
        total += n
        print(f"{'Would rewrite' if dry else 'Rewrote'} {n} file(s) under {root}")
    print(f"total={'would be ' if dry else ''}{total}")


if __name__ == "__main__":
    main()
