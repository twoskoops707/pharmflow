"""Standing-rule guardrails: host-IP egress is forbidden for farm traffic.

Operator rule (2026-09-10, after the billing_direct=1 incident): every phone's
traffic — impressions AND billing clicks — must leave through that phone's own
unique exit (residential pool entry or Tor). Mantis flags single-IP traffic as
bot; host-IP billing also dedupes clicks. The rails default must stay "0"
forever, and the inject proxy must never gain a code path that fires billing
or impression pixels from the host IP.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_billing_direct_default_is_zero() -> None:
    from automation.pharmflow_farm_config import get_runtime

    data = get_runtime()
    assert data["PHARMFLOW_MANTIS_BILLING_DIRECT"] == "0", (
        "PHARMFLOW_MANTIS_BILLING_DIRECT must stay 0: host-IP billing exposes a "
        "single-IP bot pattern to Mantis and dedupes clicks. Operator rule."
    )


def test_no_rails_source_sets_billing_direct_to_one() -> None:
    for path in (ROOT / "automation", ROOT / "scripts", ROOT / "tools", ROOT / "wizard"):
        for py in path.rglob("*.py"):
            text = py.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(
                r"[\"']PHARMFLOW_MANTIS_BILLING_DIRECT[\"']\s*:\s*[\"']1[\"']", text
            ):
                raise AssertionError(
                    f"{py.relative_to(ROOT)} sets PHARMFLOW_MANTIS_BILLING_DIRECT to 1 "
                    "(host-IP billing). Operator rule forbids this."
                )


def test_hostside_pixel_firing_stays_disabled() -> None:
    # Host-side pixel firing must stay gone — impressions leave each phone exit.
    inject = (ROOT / "automation" / "mantis_inject_proxy.py").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "fire_ssp_impression_pixels_hostside" not in inject
    for line in inject.splitlines():
        stripped = line.strip()
        if stripped.startswith("fire_ssp_impression_pixels_hostside("):
            raise AssertionError(
                "active host-side pixel firing found in mantis_inject_proxy.py — "
                "impression pixels must fire from each phone's browser via its "
                "own Tor/residential exit, never the host IP"
            )


def test_inject_proxy_billing_direct_source_default_is_zero() -> None:
    """The inject proxy's own env default must be "0" — not just the rails data.

    The 2026-09-10 incident shipped twice: once in the rails data and once as a
    hardcoded "1" default inside billing_direct_enabled(). Pin the source so a
    second copy of the bug cannot silently appear.
    """
    inject = (ROOT / "automation" / "mantis_inject_proxy.py").read_text(
        encoding="utf-8", errors="replace"
    )
    assert 'default="0"' in inject and "MANTIS_BILLING_DIRECT" in inject, (
        "billing_direct_enabled() must default to 0 (no host-IP egress) — "
        "standing rule 7"
    )
    from automation.mantis_inject_proxy import billing_direct_enabled

    assert billing_direct_enabled() is False


def test_upstream_tor_port_follows_live_broadcast(tmp_path, monkeypatch) -> None:
    """Inject upstream must dial the live Tor generation's shifted base."""
    import json
    import time as _time

    (tmp_path / "tor_port_bases.json").write_text(
        json.dumps(
            {"ts": _time.time(), "socks_base": 9990, "http_base": 8880, "pid": 123}
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("CPHARM_LOG_DIR", raising=False)
    monkeypatch.delenv("PHARMFLOW_LOG_DIR", raising=False)
    monkeypatch.setenv("CPHARM_LOGS", str(tmp_path))
    monkeypatch.delenv("PHARMFLOW_LOGS", raising=False)
    from automation.mantis_inject_proxy import upstream_tor_port

    assert upstream_tor_port(2) == 8882
    assert upstream_tor_port(22) == 8902


def test_upstream_tor_port_ignores_stale_broadcast(tmp_path, monkeypatch) -> None:
    """A dead generation's broadcast must never be dialed (its ports are poison)."""
    import json
    import time as _time

    (tmp_path / "tor_port_bases.json").write_text(
        json.dumps(
            {
                "ts": _time.time() - 3600,
                "socks_base": 9990,
                "http_base": 8880,
                "pid": 123,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("CPHARM_LOG_DIR", raising=False)
    monkeypatch.delenv("PHARMFLOW_LOG_DIR", raising=False)
    monkeypatch.setenv("CPHARM_LOGS", str(tmp_path))
    monkeypatch.delenv("PHARMFLOW_LOGS", raising=False)
    from automation.mantis_inject_proxy import TOR_HTTP_TUNNEL_BASE, upstream_tor_port

    assert upstream_tor_port(2) != 8882
    # Falls back to the in-process resolver or the raw constant — both are
    # ≥ the configured base, never the stale broadcast's value.
    assert upstream_tor_port(2) >= TOR_HTTP_TUNNEL_BASE
    assert upstream_tor_port(2) != 8218 + 2


def test_upstream_tor_port_refuses_inject_window_broadcast(tmp_path, monkeypatch) -> None:
    """http_base in the inject listen window (8218+) must never be dialed as Tor."""
    import json
    import time as _time

    (tmp_path / "tor_port_bases.json").write_text(
        json.dumps(
            {"ts": _time.time(), "socks_base": 9150, "http_base": 8218, "pid": 123}
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("CPHARM_LOG_DIR", raising=False)
    monkeypatch.delenv("PHARMFLOW_LOG_DIR", raising=False)
    monkeypatch.setenv("CPHARM_LOGS", str(tmp_path))
    monkeypatch.delenv("PHARMFLOW_LOGS", raising=False)
    from automation.mantis_inject_proxy import upstream_tor_port

    port = upstream_tor_port(0)
    assert port != 8218
    assert port >= 8118


def test_billing_route_prefers_residential_then_tor_not_host() -> None:
    inject = (ROOT / "automation" / "mantis_inject_proxy.py").read_text(
        encoding="utf-8", errors="replace"
    )
    res = inject.find('"residential"')
    tor = inject.find("upstream_tor_port(self.phone_index)")
    host = inject.find("billing_direct_enabled() and _is_mantis_billing_host")
    assert res != -1 and tor != -1 and host != -1
    # The host-IP billing branch must sit BELOW the residential branch and must
    # be gated behind billing_direct_enabled() (default 0) so a misconfig can
    # never silently route billing from the host IP.
    assert res < host < tor
