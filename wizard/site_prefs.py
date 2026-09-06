"""Wizard target site URL — user-configurable; no hardcoded site in the UI."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

# Dual import path: package (`wizard.*`) vs frozen EXE (wizard dir on sys.path).
try:
    from wizard.wizard_paths import cpharm_default_install_root
except ImportError:  # pragma: no cover — flat layout inside frozen wizard bundle
    from wizard_paths import cpharm_default_install_root  # type: ignore

DEFAULT_TARGET_SITE_URL = ""
_PREFS_NAME = "wizard_site.json"


def _prefs_path() -> Path:
    rec = cpharm_default_install_root() / "automation" / "recordings"
    rec.mkdir(parents=True, exist_ok=True)
    return rec / _PREFS_NAME


def _sync_setup_wizard_state(url: str) -> None:
    # Lazy on purpose: setup_wizard is a large tk module; top-level import is costly
    # and can create import cycles when the wizard later loads site_prefs.
    try:
        from setup_wizard import state
    except ImportError:
        try:
            from wizard.setup_wizard import state  # type: ignore
        except ImportError:
            return
    try:
        state["target_site_url"] = url
    except Exception:
        pass


def normalize_site_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    # Drop fragments so BootPage / prefs store a stable navigable URL.
    try:
        parts = urlparse(u)
        if parts.fragment:
            u = parts._replace(fragment="").geturl()
    except Exception:
        pass
    return u


def site_display_host(url: str | None = None) -> str:
    u = (url or "").strip() or load_target_site_url()
    if not u:
        return ""
    u = normalize_site_url(u)
    try:
        host = urlparse(u).netloc
        # Strip userinfo if present (user:pass@host).
        if "@" in host:
            host = host.rsplit("@", 1)[-1]
        return host or u
    except Exception:
        return u


def load_target_site_url() -> str:
    env = os.environ.get("CPHARM_TARGET_SITE_URL", "").strip()
    if env:
        return normalize_site_url(env)
    try:
        p = _prefs_path()
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            u = (data.get("target_site_url") or "").strip()
            if u:
                return normalize_site_url(u)
    except Exception:
        pass
    return ""


def save_target_site_url(url: str) -> str:
    u = normalize_site_url(url)
    try:
        _prefs_path().write_text(
            json.dumps({"target_site_url": u}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        # Import/path/IO failures must not crash BootPage URL save.
        pass
    _sync_setup_wizard_state(u)
    return u


def apply_site_url_to_boot_page(page: object | None = None) -> str:
    """Sync BootPage test URL field from prefs."""
    u = load_target_site_url()
    _sync_setup_wizard_state(u)
    if page is not None and hasattr(page, "_test_url_var"):
        try:
            page._test_url_var.set(u)
        except Exception:
            pass
    return u
