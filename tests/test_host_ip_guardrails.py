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
    from automation.cpharm_farm_config import get_runtime

    data = get_runtime()
    assert data["CPHARM_MANTIS_BILLING_DIRECT"] == "0", (
        "CPHARM_MANTIS_BILLING_DIRECT must stay 0: host-IP billing exposes a "
        "single-IP bot pattern to Mantis and dedupes clicks. Operator rule."
    )


def test_no_rails_source_sets_billing_direct_to_one() -> None:
    for path in (ROOT / "automation", ROOT / "scripts", ROOT / "tools", ROOT / "wizard"):
        for py in path.rglob("*.py"):
            text = py.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(
                r"[\"']CPHARM_MANTIS_BILLING_DIRECT[\"']\s*:\s*[\"']1[\"']", text
            ):
                raise AssertionError(
                    f"{py.relative_to(ROOT)} sets CPHARM_MANTIS_BILLING_DIRECT to 1 "
                    "(host-IP billing). Operator rule forbids this."
                )


def test_hostside_pixel_firing_stays_disabled() -> None:
    from automation.mantis_inject_proxy import fire_ssp_impression_pixels_hostside  # noqa: F401

    # The function exists for history but every call site must remain
    # commented out — the DISABLED block in _build patch JS is the proof.
    inject = (ROOT / "automation" / "mantis_inject_proxy.py").read_text(
        encoding="utf-8", errors="replace"
    )
    for line in inject.splitlines():
        stripped = line.strip()
        if stripped.startswith("fire_ssp_impression_pixels_hostside("):
            raise AssertionError(
                "active host-side pixel firing found in mantis_inject_proxy.py — "
                "impression pixels must fire from each phone's browser via its "
                "own Tor/residential exit, never the host IP"
            )


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
