#!/usr/bin/env python3
"""Replace old sequence JSON basenames using automation/recordings/_sequence_rename_basename_map.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    map_path = ROOT / "automation" / "recordings" / "_sequence_rename_basename_map.json"
    rename_map = json.loads(map_path.read_text(encoding="utf-8"))
    stem_map: dict[str, str] = {}
    for old, new in rename_map.items():
        if old.endswith(".json") and new.endswith(".json"):
            stem_map[old[:-5]] = new[:-5]

    # Docs referenced curated intermediate basenames that match close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__hdd71d4 / close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__hd2a57d content.
    if "close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__hdd71d4.json" in rename_map:
        ns = rename_map["close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__hdd71d4.json"][:-5]
        stem_map["close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__hdd71d4"] = ns
    if "close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__hd2a57d.json" in rename_map:
        stem_map["close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__hd2a57d"] = (
            rename_map["close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__hd2a57d.json"][:-5]
        )

    keys = sorted(rename_map.keys(), key=len, reverse=True)
    stem_keys = sorted(stem_map.keys(), key=len, reverse=True)

    skip_dirs = {".git", "__pycache__", ".venv", "node_modules"}
    text_suffixes = {".py", ".md", ".txt", ".yml", ".yaml", ".json", ".toml", ".cfg"}

    skip_paths = {
        (ROOT / "automation" / "recordings" / "_sequence_rename_basename_map.json").resolve(),
    }

    changed_files = 0
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.resolve() in skip_paths:
            continue
        if skip_dirs & set(path.parts):
            continue
        try:
            rel = path.relative_to(ROOT)
        except ValueError:
            continue
        if rel.parts[0] == ".git":
            continue
        suf = path.suffix.lower()
        if suf not in text_suffixes and not path.name.endswith(".generated.md"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        orig = text
        for old in keys:
            if old in text:
                text = text.replace(old, rename_map[old])
        for os in stem_keys:
            if os in text:
                text = text.replace(os, stem_map[os])
        if text != orig:
            path.write_text(text, encoding="utf-8", newline="\n")
            changed_files += 1

    print(f"updated {changed_files} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
