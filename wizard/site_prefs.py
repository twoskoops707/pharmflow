"""Wizard target site URL — user-configurable; no hardcoded site in the UI."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_TARGET_SITE_URL = ""
_PREFS_NAME = "wizard_site.json"


def _prefs_path() -> Path:
    from wizard_paths import cpharm_default_install_root

    rec = cpharm_default_install_root() / "automation" / "recordings"
    rec.mkdir(parents=True, exist_ok=True)
    return rec / _PREFS_NAME


def normalize_site_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u


def site_display_host(url: str | None = None) -> str:
    u = (url or "").strip() or load_target_site_url()
    if not u:
        return ""
    u = normalize_site_url(u)
    try:
        host = urlparse(u).netloc
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
    except OSError:
        pass
    try:
        from setup_wizard import state

        state["target_site_url"] = u
    except Exception:
        pass
    return u


def apply_site_url_to_boot_page(page: object | None = None) -> str:
    """Sync BootPage test URL field from prefs."""
    u = load_target_site_url()
    try:
        from setup_wizard import state

        state["target_site_url"] = u
    except Exception:
        pass
    if page is not None and hasattr(page, "_test_url_var"):
        try:
            page._test_url_var.set(u)
        except Exception:
            pass
    return u
