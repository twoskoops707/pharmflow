"""Remediator must not fight Firefox/Brave MITM-skip :0 as a dead inject pin."""
from __future__ import annotations

from automation.farm_checkin import inject_pin_needed


def test_chromium_on_inject_ok() -> None:
    assert inject_pin_needed("127.0.0.1:8225", "127.0.0.1:8225", "org.chromium.chrome") is False


def test_chromium_cleared_needs_pin() -> None:
    assert inject_pin_needed(":0", "127.0.0.1:8225", "org.chromium.chrome") is True


def test_firefox_cleared_is_ok() -> None:
    assert inject_pin_needed(":0", "127.0.0.1:8225", "org.mozilla.firefox") is False


def test_brave_cleared_is_ok() -> None:
    assert inject_pin_needed(":0", "127.0.0.1:8226", "com.brave.browser") is False


def test_wrong_inject_port_still_needs_pin() -> None:
    assert inject_pin_needed("127.0.0.1:8221", "127.0.0.1:8225", "org.chromium.chrome") is True
