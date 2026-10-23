#!/usr/bin/env python3
"""Layout smoke — no bubble panels that clip wizard content."""
from __future__ import annotations

import sys
from pathlib import Path

_HTML = Path(__file__).resolve().parent / "assets" / "pharmflow_app" / "index.html"
_CSS = Path(__file__).resolve().parent / "assets" / "pharmflow_app" / "app.css"


def main() -> int:
    html = _HTML.read_text(encoding="utf-8")
    css = _CSS.read_text(encoding="utf-8")
    if "data-bubble" in html or "bubble-panel" in html:
        print("smoke_layout: bubble markup still in index.html", file=sys.stderr)
        return 1
    if "max-height: min(200px, 28vh)" in css and "panel-instructions-boot" in css:
        print("smoke_layout: crushed boot bubble height still in app.css", file=sys.stderr)
        return 1
    if ".view-body .panel {\n  min-height: 0;\n  overflow: hidden;" in css:
        print("smoke_layout: panels still use overflow:hidden", file=sys.stderr)
        return 1
    if "phones-layout" not in html:
        print("smoke_layout: phones-layout missing", file=sys.stderr)
        return 1
    if "advanced-block" not in html:
        print("smoke_layout: run step advanced-block missing", file=sys.stderr)
        return 1
    print("smoke_layout: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
