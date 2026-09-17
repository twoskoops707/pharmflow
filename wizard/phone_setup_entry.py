"""
Shared entry for MuMu phone setup — opens the dedicated Phone Setup UI (Chromium on emulators only).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_wizard_dir = Path(__file__).resolve().parent
if str(_wizard_dir) not in sys.path:
    sys.path.insert(0, str(_wizard_dir))


def is_unified_pharmflow(argv: list[str] | None = None) -> bool:
    """True when the running process is the single shipped app exe.

    PharmFlow.exe is the unified app (formerly CPharm.exe); both names count
    so older installs keep working after the rebrand.
    """
    if not getattr(sys, "frozen", False):
        return False
    args = list(argv if argv is not None else sys.argv)
    if "--phone-setup" in args:
        return True
    return Path(sys.executable).stem.lower() in ("pharmflow", "cpharm")


def is_phone_setup_mode(argv: list[str] | None = None) -> bool:
    args = list(argv if argv is not None else sys.argv)
    if "--phone-setup" in args:
        return True
    if getattr(sys, "frozen", False):
        stem = Path(sys.executable).stem.lower()
        if stem == "pharmflowmumusetup":
            return True
    return False


def skip_launch_pharmflow_after_setup() -> bool:
    if os.environ.get("PHARMFLOW_SKIP_LAUNCH_AFTER_SETUP", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return True
    if is_unified_pharmflow():
        return True
    return is_phone_setup_mode() and "--phone-setup" in sys.argv


def phone_setup_main() -> None:
    """Dedicated MuMu checklist + GO (installs Chromium on phones, not on this PC)."""
    skip = skip_launch_pharmflow_after_setup()
    try:
        from mumu_setup_webview import is_pywebview_available, run_webview_app

        if is_pywebview_available():
            run_webview_app(skip_launch_pharmflow=skip)
            return
    except Exception:
        pass
    from pharmflow_mumu_setup import MuMuSetupTkFallback

    MuMuSetupTkFallback(skip_launch_pharmflow=skip).mainloop()
