"""Resolve local-only automation sequence JSON storage (not in git)."""

from __future__ import annotations

import os
from pathlib import Path

_ENV = "CPHARM_SEQUENCES_DIR"


def default_sequences_dir() -> Path:
    """Default local folder: ``%USERPROFILE%\\CPharm\\sequences``."""
    return Path.home() / "CPharm" / "sequences"


def resolve_sequences_dir(*, create: bool = False) -> Path:
    """
    Sequences root from ``CPHARM_SEQUENCES_DIR`` or :func:`default_sequences_dir`.

    Layout: ``{root}/{WxH}/{ad|no-ad}/*.json``
    """
    raw = (os.environ.get(_ENV) or "").strip()
    root = Path(raw).expanduser() if raw else default_sequences_dir()
    root = root.resolve()
    if create:
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return root


def fixtures_sequences_dir() -> Path:
    """Minimal JSON fixtures for CI (under ``automation/tests/fixtures/sequences``)."""
    return Path(__file__).resolve().parent / "tests" / "fixtures" / "sequences"
