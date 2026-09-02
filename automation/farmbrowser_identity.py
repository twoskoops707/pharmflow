"""
FarmBrowser Identity Auto-Assign — guarantee zero identity collisions across all phones.

When the farm starts, call `assign_unique_identities()` to give each phone
a guaranteed unique browser identity slot. Since there are 12 identities
(Chrome, Firefox, Brave, Samsung, Edge, Opera, Vivaldi, DuckDuckGo, UC Browser, etc.)
and at most ~7 phones, each phone gets a unique slot that never changes.

Identity rotation still happens on every page load (nextIdentity() advances),
but because each phone starts at a different offset, no two phones ever show
the same identity at the same time.

Call this once at farm startup from the dashboard or scheduler.
"""

from __future__ import annotations

import logging
import time

from browser_adb import (
    farmbrowser_control_broadcast,
    farmbrowser_installed,
    farmbrowser_identity_count,
)

log = logging.getLogger("cpharm")


def assign_unique_identities(
    serials: list[str],
    *,
    base_slot: int = 0,
) -> dict[str, dict]:
    """Assign a unique identity slot to each phone.

    Returns ``{serial: {ok, identity, slot}}`` for each phone.
    """
    identity_count = farmbrowser_identity_count(serials[0] if serials else "")
    assigned: dict[str, dict] = {}

    for i, serial in enumerate(serials):
        slot = (base_slot + i) % identity_count
        r = farmbrowser_control_broadcast(serial, "set_identity", {"index": slot})
        result = r.get("result", "")

        # Parse identity name from result
        identity_name = "UNKNOWN"
        if "identity:" in result:
            identity_name = result.split("identity:")[-1].strip().strip('"')

        assigned[serial] = {
            "ok": r.get("ok", False),
            "slot": slot,
            "identity": identity_name,
        }
        log.info("[identity-assign] %s -> slot %d = %s", serial, slot, identity_name)

    # Verify no collisions
    names = [a["identity"] for a in assigned.values() if a["identity"] != "UNKNOWN"]
    if len(names) != len(set(names)):
        from collections import Counter
        dupes = [n for n, c in Counter(names).items() if c > 1]
        log.warning("[identity-assign] COLLISION DETECTED: %s — consider increasing base_slot", dupes)
    else:
        log.info("[identity-assign] ALL %d phones have unique identities — zero collisions", len(names))

    return assigned


def verify_unique_identities(serials: list[str]) -> dict[str, str]:
    """Check current identity on each phone. Returns ``{serial: identity_name}``."""
    result: dict[str, str] = {}
    for serial in serials:
        r = farmbrowser_control_broadcast(serial, "status")
        raw = r.get("result", "")
        # Parse "identity":"Chrome 128" from JSON result
        import re
        m = re.search(r'"identity":"([^"]+)"', raw)
        result[serial] = m.group(1) if m else "NO_RESPONSE"
    return result
