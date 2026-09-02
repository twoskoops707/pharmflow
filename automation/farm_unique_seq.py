"""Farm-wide concurrent unique-sequence reservation (EXE + CLI farm share this).

Hard rule: two phones never run the same sequence identity at once.
Identity keys:
  - file:{stem}  — exact sequence file
  - ad:{slot}    — Path3 / ad slot when present in the stem
"""

from __future__ import annotations

import re
import threading
from typing import Callable

AdKeyFn = Callable[[str], str | None]

_AD_SLOT_RE = re.compile(r"(?:homead|_ad)(\d+)|on([a-z]+)_ad(\d+)", re.I)


def default_ad_key(stem: str) -> str | None:
    """Extract a stable ad-slot key from a sequence stem, if any."""
    low = stem.lower()
    if not ("_ad" in low or "homead" in low):
        return None
    m = _AD_SLOT_RE.search(stem)
    if not m:
        return "ad:generic"
    if m.group(1) is not None:
        return f"homead{m.group(1)}"
    return f"on{m.group(2)}_ad{m.group(3)}"


def identity_keys(stem: str, *, ad_key_fn: AdKeyFn | None = None) -> set[str]:
    """Reservation keys for one sequence stem."""
    keys = {f"file:{stem}"}
    fn = ad_key_fn or default_ad_key
    ad_key = fn(stem)
    if ad_key:
        keys.add(f"ad:{ad_key}")
    return keys


class UniqueSequenceLock:
    """Thread-safe reservation set for concurrent farm workers."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active: set[str] = set()

    @property
    def active(self) -> set[str]:
        with self._lock:
            return set(self._active)

    def try_reserve(self, keys: set[str]) -> bool:
        if not keys:
            return False
        with self._lock:
            if keys & self._active:
                return False
            self._active.update(keys)
            return True

    def release(self, keys: set[str]) -> None:
        if not keys:
            return
        with self._lock:
            self._active.difference_update(keys)

    def conflicts(self, keys: set[str]) -> set[str]:
        with self._lock:
            return set(keys & self._active)
