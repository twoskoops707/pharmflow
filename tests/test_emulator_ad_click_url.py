"""Path3 must open the paying click_url even when house-fallback is off."""
from __future__ import annotations

from unittest.mock import patch

from automation.emulator_ad_mode import maybe_fallback_ad_open_url


def test_force_click_url_bypasses_fallback_off() -> None:
    opened: list[tuple[str, str]] = []

    def _open(serial: str, url: str) -> bool:
        opened.append((serial, url))
        return True

    with patch("automation.emulator_ad_mode.emulator_ad_fallback_enabled", return_value=False):
        ok = maybe_fallback_ad_open_url(
            object(),
            "10.0.2.222:5555",
            "ad_home",
            open_url_fn=_open,
            force_click_url=True,
            prefer_click_url="https://bids.mantis.marketing/clicked?x=1",
        )
    assert ok is True
    assert opened == [("10.0.2.222:5555", "https://bids.mantis.marketing/clicked?x=1")]


def test_without_force_respects_fallback_off() -> None:
    opened: list[tuple[str, str]] = []
    with patch("automation.emulator_ad_mode.emulator_ad_fallback_enabled", return_value=False):
        ok = maybe_fallback_ad_open_url(
            object(),
            "10.0.2.222:5555",
            "ad_home",
            open_url_fn=lambda s, u: opened.append((s, u) or True),
            prefer_click_url="https://bids.mantis.marketing/clicked?x=1",
        )
    assert ok is False
    assert opened == []
