#!/usr/bin/env python3
"""Patch the installed pywebview winforms.py so the frozen EXE carries the fix.

On ARM64 (.NET 8 coreclr path), pywebview 6.2.x OpenFolderDialog reflects
netfx-only FileDialogNative + IFileDialog types at class-definition time.
That reflection raises inside the module import, so a *runtime* text patch is
useless when the module is frozen as bytecode — the import dies before any
code runs. The only way the frozen EXE works is to patch the source file in
site-packages BEFORE PyInstaller compiles it, so the frozen bytecode contains
the stub.

This script idempotently replaces the OpenFolderDialog class in the installed
pywebview copy with a no-op stub (same marker the runtime path uses:
PHARMFLOW_NET8_OPENFOLDER_PATCH). Runs in CI immediately before `pyinstaller`.
Exit code 0 always — a missing/mismatched file is logged, not fatal.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARKER = "PHARMFLOW_NET8_OPENFOLDER_PATCH"


def main() -> int:
    try:
        import webview
    except Exception as exc:  # pragma: no cover - env-dependent
        print(f"patch_winforms: cannot import webview: {exc}")
        return 0

    path = Path(webview.__file__).resolve().parent / "platforms" / "winforms.py"
    if not path.is_file():
        print(f"patch_winforms: winforms.py not found at {path}")
        return 0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"patch_winforms: read failed: {exc}")
        return 0
    if MARKER in text:
        print("patch_winforms: already patched, no-op")
        return 0

    needle = "class OpenFolderDialog:\n"
    start = text.find(needle)
    if start < 0:
        print("patch_winforms: OpenFolderDialog class not found (version drift?)")
        return 0
    rest = text[start + len(needle) :]
    end_rel = rest.find("\n_main_window_created")
    if end_rel < 0:
        end_rel = rest.find("\nclass ")
    if end_rel < 0:
        print("patch_winforms: could not locate end of OpenFolderDialog")
        return 0

    stub = (
        "class OpenFolderDialog:\n"
        f"    # {MARKER}\n"
        "    foldersFilter = 'Folders|\\n'\n"
        "\n"
        "    @classmethod\n"
        "    def show(cls, parent=None, initialDirectory=None, allow_multiple=False, title=None):\n"
        "        return None\n"
        "\n"
    )
    new_text = text[:start] + stub + rest[end_rel + 1 :]
    try:
        path.write_text(new_text, encoding="utf-8")
    except OSError as exc:
        print(f"patch_winforms: write failed: {exc}")
        return 0
    print(f"patch_winforms: patched {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())