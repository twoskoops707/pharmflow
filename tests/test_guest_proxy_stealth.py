"""Guest proxy stealth: inject listen alone is not a real upstream."""

from __future__ import annotations

from unittest.mock import patch

from automation import browse_proxy as bp


def test_inject_without_tor_upstream_fails_stealth() -> None:
    with (
        patch.object(bp, "_host_port_listens", side_effect=lambda port, **_k: port == 8220),
        patch(
            "automation.mantis_inject_proxy.upstream_tor_port",
            return_value=8120,
        ),
        patch(
            "automation.mantis_inject_proxy.phone_inject_port",
            side_effect=lambda i: 8218 + int(i),
        ),
        patch(
            "automation.mantis_inject_proxy.INJECT_BASE",
            8218,
        ),
        patch(
            "automation.mantis_inject_proxy.upstream_mode",
            return_value="tor",
        ),
    ):
        ok, reason = bp.guest_proxy_stealth_ok("127.0.0.1:8220", phone_idx=2)
    assert ok is False
    assert "upstream_tor_dead" in reason


def test_inject_with_live_tor_upstream_passes() -> None:
    with (
        patch.object(
            bp,
            "_host_port_listens",
            side_effect=lambda port, **_k: port in (8220, 8120),
        ),
        patch(
            "automation.mantis_inject_proxy.upstream_tor_port",
            return_value=8120,
        ),
        patch(
            "automation.mantis_inject_proxy.phone_inject_port",
            side_effect=lambda i: 8218 + int(i),
        ),
        patch("automation.mantis_inject_proxy.INJECT_BASE", 8218),
        patch("automation.mantis_inject_proxy.upstream_mode", return_value="tor"),
    ):
        ok, reason = bp.guest_proxy_stealth_ok("127.0.0.1:8220", phone_idx=2)
    assert ok is True
    assert "inject+tor" in reason


def test_cleared_proxy_never_stealth_ok() -> None:
    ok, reason = bp.guest_proxy_stealth_ok(":0", phone_idx=0)
    assert ok is False
    assert "guest_unhealthy" in reason


def test_fleet_audit_requires_all_phones() -> None:
    serials = ["a:5555", "b:5555", "c:5555"]
    readings = {
        "a:5555": "127.0.0.1:8218",
        "b:5555": "127.0.0.1:8219",
        "c:5555": "127.0.0.1:8220",
    }

    def _listen(port: int, **_k: object) -> bool:
        # Only first two inject ports + their Tor upstreams listen.
        return port in (8218, 8219, 8118, 8119)

    with (
        patch.object(bp, "_host_port_listens", side_effect=_listen),
        patch(
            "automation.mantis_inject_proxy.upstream_tor_port",
            side_effect=lambda i: 8118 + int(i),
        ),
        patch(
            "automation.mantis_inject_proxy.phone_inject_port",
            side_effect=lambda i: 8218 + int(i),
        ),
        patch("automation.mantis_inject_proxy.INJECT_BASE", 8218),
        patch("automation.mantis_inject_proxy.upstream_mode", return_value="tor"),
        patch.object(
            bp,
            "guest_proxy_healthy",
            side_effect=lambda value, phone_idx=None: str(value).startswith("127.0.0.1:"),
        ),
    ):
        out = bp.audit_fleet_upstream_proxies(
            serials,
            read_proxy=lambda s: readings[s],
            index_for_serial=lambda s: serials.index(s),
        )
    assert out["ok"] is False
    assert out["ok_count"] == 2
    assert out["total"] == 3
    assert out["bad_count"] == 1
    assert out["bad"][0]["serial"] == "c:5555"
