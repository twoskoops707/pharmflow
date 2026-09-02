"""Utility — strip hardcoded Chrome/browser package refs from sequence JSON files."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

STRIP_KEYS = {"package", "browser_package", "chrome_package", "component"}
STRIP_PACKAGES = {
    "com.android.chrome",
    "org.chromium.chrome",
    "com.mumudroid.browser",
    "com.chrome.beta",
}


def strip_sequence_file(path: Path, dry_run: bool = False) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    changed = False

    for step in data.get("steps", []):
        params = step.get("params", {})
        for key in list(params.keys()):
            if key in STRIP_KEYS:
                del params[key]
                changed = True
            if key == "package" and params.get(key) in STRIP_PACKAGES:
                del params[key]
                changed = True
        if step.get("action") == "open_url" and "package" in step:
            del step["package"]
            changed = True

    if changed and not dry_run:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        logger.info("Stripped browser refs from %s", path)
    return changed


def strip_directory(directory: Path, dry_run: bool = False) -> int:
    count = 0
    for f in directory.glob("*.json"):
        if strip_sequence_file(f, dry_run=dry_run):
            count += 1
    return count


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("automation/recordings/sequences")
    dry = "--dry-run" in sys.argv
    n = strip_directory(target, dry_run=dry)
    print(f"{'Would strip' if dry else 'Stripped'} {n} file(s) in {target}")


if __name__ == "__main__":
    main()
