#!/usr/bin/env python3
"""
Deterministic checks for ``browser_builder_webview`` (no GUI, no pywebview required).

Covers URL validation, dimension clamping, pywebview-absence behavior, busy-session
short-circuiting, and the diagnostic ``last_error`` accessor.

From repo root:

  py -3 wizard/smoke_browser_builder.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_WIZ = Path(__file__).resolve().parent
if str(_WIZ) not in sys.path:
    sys.path.insert(0, str(_WIZ))


def _fail(msg: str) -> int:
    print(f"smoke_browser_builder: {msg}", file=sys.stderr)
    return 1


def main() -> int:
    import browser_builder_webview as bbw

    # ── URL validation ────────────────────────────────────────────────
    cases = [
        ("https://example.com", True),
        ("http://localhost:8080/path?x=1", True),
        ("HTTPS://Example.com", True),  # urlparse keeps scheme case-insensitive
        ("", False),
        ("   ", False),
        ("example.com", False),  # missing scheme
        ("ftp://example.com", False),  # unsupported scheme
        ("https://", False),  # missing host
        ("javascript:alert(1)", False),
        ("file:///c:/x", False),
    ]
    for url, expected in cases:
        ok, normalized = bbw.validate_url(url)
        if ok is not expected:
            return _fail(f"validate_url({url!r}) -> {ok}, expected {expected}")
        if ok and normalized != url.strip():
            return _fail(f"validate_url normalize mismatch for {url!r}: got {normalized!r}")

    # ── Dimension clamping ────────────────────────────────────────────
    if bbw.clamp_dims(0, 0) != (320, 480):
        return _fail("clamp_dims(0, 0) lower bound")
    if bbw.clamp_dims(99999, 99999) != (4096, 4096):
        return _fail("clamp_dims upper bound")
    if bbw.clamp_dims("not-a-number", None) != (320, 480):
        return _fail("clamp_dims with garbage input")
    if bbw.clamp_dims(900, 1600) != (900, 1600):
        return _fail("clamp_dims passthrough")

    # ── Public error code constants stable across versions ────────────
    for name, expected in (
        ("ERR_IMPORT", "import"),
        ("ERR_BADURL", "badurl"),
        ("ERR_BUSY", "busy"),
        ("ERR_START", "start_failed"),
    ):
        if getattr(bbw, name) != expected:
            return _fail(f"error code drift: {name}={getattr(bbw, name)!r}")

    # ── try_load_url / close are safe with no active session ──────────
    if bbw.try_load_url("https://example.com") is not False:
        return _fail("try_load_url with no window must return False")
    if bbw.close() is not False:
        return _fail("close() with no window must return False")
    if bbw.is_session_active():
        return _fail("is_session_active() should be False at rest")

    # ── Behavior with pywebview absent vs present ─────────────────────
    if bbw.is_pywebview_available():
        # Real package present: bad URL must surface as ERR_BADURL (not ERR_IMPORT).
        ok, err = bbw.launch_browser_builder("not a url", 800, 600, lambda *a: None, lambda *a: None)
        if ok or err != bbw.ERR_BADURL:
            return _fail(f"launch_browser_builder badurl path: ok={ok!r} err={err!r}")
        pywebview_status = "available"
    else:
        # Without pywebview every launch must short-circuit on import — even with a valid URL.
        ok, err = bbw.launch_browser_builder(
            "https://example.com", 800, 600, lambda *a: None, lambda *a: None
        )
        if ok or err != bbw.ERR_IMPORT:
            return _fail(f"launch_browser_builder import path: ok={ok!r} err={err!r}")
        pywebview_status = "absent"

    # ── Busy-session short-circuit (independent of pywebview presence) ─
    bbw._busy_starting = True  # noqa: SLF001 — internal flag exercised intentionally
    try:
        ok, err = bbw.launch_browser_builder(
            "https://example.com", 800, 600, lambda *a: None, lambda *a: None
        )
        if bbw.is_pywebview_available():
            # With pywebview installed we should hit the busy gate after URL validation.
            if ok or err != bbw.ERR_BUSY:
                return _fail(f"launch_browser_builder busy path: ok={ok!r} err={err!r}")
        else:
            # Without pywebview the import gate fires first; that is expected and acceptable.
            if ok or err != bbw.ERR_IMPORT:
                return _fail(f"launch_browser_builder busy+no-pywebview: ok={ok!r} err={err!r}")
    finally:
        bbw._busy_starting = False  # noqa: SLF001

    # ── last_error() always returns a string, even when nothing has failed ─
    le = bbw.last_error()
    if not isinstance(le, str):
        return _fail(f"last_error() must be str, got {type(le).__name__}")

    print(f"smoke_browser_builder: OK  pywebview={pywebview_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
