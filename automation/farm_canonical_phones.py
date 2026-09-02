"""Canonical 8-phone farm map — single source of truth.

Remediator, discover, watchdog, and emergency scripts must never shrink below this
set or adopt ghost MuMu serials (vm3/vm4 adaptive bleed).
"""
from __future__ import annotations

from typing import Final

# Operator sticky 8 — vm0, vm1, vm5, vm7, vm9, vm10, vm12, vm13
CANONICAL_FARM_PHONES: Final[dict[str, str]] = {
    "vm0.gmadoa": "10.0.2.187:5555",
    "vm1.gmadoa": "10.0.2.57:5555",
    "vm5.gmadoa": "10.0.2.198:5555",
    "vm7.gmadoa": "10.0.2.130:5555",
    "vm9.gmadoa": "10.0.2.119:5555",
    "vm10.gmadoa": "10.0.2.110:5555",
    "vm12.gmadoa": "10.0.2.203:5555",
    "vm13.gmadoa": "10.0.2.225:5555",
}

# Ghost / bleed serials — never farm money on these.
BANNED_SERIALS: Final[frozenset[str]] = frozenset(
    {
        "10.0.2.216",
        "10.0.2.108",
        "10.0.2.132",  # vm3 ghost
        "10.0.2.51",  # vm4 ghost
        "10.0.2.186",
        "127.0.0.1:16544",
    }
)

BANNED_PHONE_NAMES: Final[frozenset[str]] = frozenset(
    {"vm3", "vm4", "vm11", "vm3.gmadoa", "vm4.gmadoa", "vm11.gmadoa"}
)


def canonical_expect_phones() -> int:
    return len(CANONICAL_FARM_PHONES)


def canonical_names_sorted() -> list[str]:
    return sorted(
        CANONICAL_FARM_PHONES.keys(),
        key=lambda nm: int(nm.split(".")[0][2:]),
    )


def canonical_serials_sorted() -> list[str]:
    return [CANONICAL_FARM_PHONES[n] for n in canonical_names_sorted()]


def is_banned_serial(serial: str) -> bool:
    s = (serial or "").strip()
    if not s:
        return False
    if s in BANNED_SERIALS:
        return True
    return s.startswith("127.0.0.1:")


def is_banned_phone(name: str) -> bool:
    short = (name or "").split(".")[0].strip().lower()
    full = (name or "").strip().lower()
    return short in BANNED_PHONE_NAMES or full in BANNED_PHONE_NAMES


def ban_serials_csv() -> str:
    return ",".join(sorted(BANNED_SERIALS))


def is_canonical_phone(name: str) -> bool:
    short = (name or "").split(".")[0].strip().lower()
    return f"{short}.gmadoa" in CANONICAL_FARM_PHONES


def canonical_inject_ports() -> list[int]:
    return [8218 + int(nm.split(".")[0][2:]) for nm in canonical_names_sorted()]


def canonical_workset(
    online_serials: set[str] | frozenset[str] | None = None,
) -> list[tuple[str, str, str]]:
    """(short, serial, proxy) for canonical 8 — overlay lock serial when online."""
    online = set(online_serials or ())
    lock: dict[str, str] = {}
    try:
        import json
        from pathlib import Path

        p = Path(r"C:\CPharm\logs") / "ADB_SERIAL_MAP.lock.json"
        if p.is_file():
            raw = json.loads(p.read_text(encoding="utf-8-sig"))
            lock = dict(raw.get("phones") or {})
    except Exception:
        lock = {}
    rows: list[tuple[str, str, str]] = []
    for fname in canonical_names_sorted():
        short = fname.split(".")[0]
        idx = int(short[2:])
        proxy = f"127.0.0.1:{8218 + idx}"
        serial = str(lock.get(fname) or CANONICAL_FARM_PHONES[fname]).strip()
        if is_banned_serial(serial):
            serial = CANONICAL_FARM_PHONES[fname]
        if serial in online and not is_banned_serial(serial):
            pass
        elif CANONICAL_FARM_PHONES[fname] in online:
            serial = CANONICAL_FARM_PHONES[fname]
        rows.append((short, serial, proxy))
    return rows
