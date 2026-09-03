"""Single source of truth for the PharmFlow app version and build number.

Build-number source priority (so any shipped EXE is identifiable):
  1. ``assets/build_info.json`` bundled at build time by CI (run number + commit),
  2. ``CPHARM_BUILD_NUMBER`` env var (local builds / override),
  3. short git commit of the checkout,
  4. a UTC timestamp fallback.

The version module is intentionally dependency-light (no tk, no wizard imports) so
it can be imported by the CLI entrypoint, the WebView shell, and Tk windows alike.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

APP_NAME = "PharmFlow"
APP_VERSION = "1.5.0"


def _root() -> Path:
    this = Path(__file__).resolve()
    # file is at <root>/wizard/cpharm_version.py
    return this.parents[1]


def _bundled_build_info() -> dict:
    """Read assets/build_info.json under the frozen bundle or the source tree."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        mp = Path(sys._MEIPASS)
        candidates += [mp / "assets" / "build_info.json", mp / "wizard" / "assets" / "build_info.json"]
    candidates.append(_root() / "assets" / "build_info.json")
    candidates.append(Path(__file__).resolve().parent / "assets" / "build_info.json")
    for p in candidates:
        try:
            if p.is_file():
                return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return {}


def _env_build() -> str:
    return os.environ.get("CPHARM_BUILD_NUMBER", "").strip()


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(_root()), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            sha = out.stdout.strip()
            return sha[:12] if sha else ""
    except Exception:  # noqa: BLE001
        pass
    return ""


def _date_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")


def build_label() -> str:
    """Human-friendly build suffix, e.g. '1234' (CI bundle), 'git-abc123', or a UTC stamp."""
    info = _bundled_build_info()
    b = str(info.get("build_number") or "").strip()
    if b:
        return b
    env = _env_build()
    if env:
        return env
    git = _git_commit()
    if git:
        return "git-" + git
    return _date_stamp()


def commit_sha() -> str:
    """Source commit from the bundled build info, else git/empty."""
    info = _bundled_build_info()
    c = str(info.get("commit") or "").strip()
    if c:
        return c
    try:
        return _git_commit()
    except Exception:  # noqa: BLE001
        return ""


BUILD_LABEL = build_label()
BUILD_COMMIT = commit_sha()


def display_version(*, short: bool = False) -> str:
    base = f"{APP_NAME} {APP_VERSION}"
    if short:
        return base
    suffix = BUILD_LABEL
    if BUILD_COMMIT and BUILD_COMMIT != suffix.replace("git-", ""):
        suffix = f"{suffix} @ {BUILD_COMMIT[:8]}"
    return f"{base} (build {suffix})"


def instance_title(suffix: str) -> str:
    """Window title, e.g. 'PharmFlow — Control Panel (build 1234)'."""
    return f"{APP_NAME} — {suffix} (build {BUILD_LABEL})"


if __name__ == "__main__":
    print(display_version(short="--short" in sys.argv))