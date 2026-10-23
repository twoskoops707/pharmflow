#!/usr/bin/env python3
"""Verify wizard/assets/pharmflow_app/app.js structure (no Node required)."""
from __future__ import annotations

import sys
from pathlib import Path

_JS = Path(__file__).resolve().parent / "assets" / "pharmflow_app" / "app.js"


def main() -> int:
    js = _JS.read_text(encoding="utf-8")
    required = [
        "function showToast(msg)",
        "function showBackendError(msg)",
        "function wireStaticNav()",
        "function wireActionButtons()",
        "window.PharmFlowSetup",
        "get_prereq_status",
        "run_install_all",
    ]
    for needle in required:
        if needle not in js:
            print(f"smoke_app_js: missing {needle!r}", file=sys.stderr)
            return 1
    if js.count("{") != js.count("}"):
        print("smoke_app_js: brace mismatch", file=sys.stderr)
        return 1
    if not js.strip().endswith("})();"):
        print("smoke_app_js: IIFE not closed", file=sys.stderr)
        return 1
    print("smoke_app_js: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
