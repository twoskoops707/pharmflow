"""Adaptive live phone map — CPharm/MuMu ADB, never a frozen vm list.

Discover whatever MuMu VMs CPharm sees as ADB-online. Ban tablet + ghost.
Inject port = 8218 + MuMu index from name (vmN → N).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.farm_canonical_phones import (  # noqa: E402
    BANNED_PHONE_NAMES,
    BANNED_SERIALS,
    CANONICAL_FARM_PHONES,
    canonical_expect_phones,
    canonical_names_sorted,
    canonical_serials_sorted,
    is_banned_phone,
    is_banned_serial,
    is_canonical_phone,
)

LOG = Path(os.environ.get("CPHARM_LOGS") or r"C:\CPharm\logs")
GHOST_NAMES = set(BANNED_PHONE_NAMES) | {"vm11", "vm11.gmadoa"}
# Ghost vm3/vm4/vm11 + canonical-only money set (never adaptive bleed).
SKIP_MONEY = set(BANNED_PHONE_NAMES) | {"vm11"}
OVERFLOW_NAMES: set[str] = set()
INJECT_BASE = int(os.environ.get("CPHARM_MANTIS_INJECT_BASE", "8218") or "8218")
VMS_DIR = Path(
    os.environ.get("CPHARM_MUMU_VMS")
    or r"C:\Program Files\Netease\MuMuPlayerARM\vms"
)
_NAME_IDX = re.compile(r"^vm(\d+)", re.I)
ADB = r"C:\CPharm\bundled\adb.exe"
if not Path(ADB).is_file():
    ADB = "adb"


def _idx_from_name(name: str) -> int | None:
    m = _NAME_IDX.match((name or "").split(".")[0])
    if not m:
        return None
    return int(m.group(1))


def short_name(name: str) -> str:
    return (name or "").split(".")[0].strip()


def is_ghost_name(name: str) -> bool:
    return is_banned_phone(name) or short_name(name).lower() in {
        g.split(".")[0] for g in GHOST_NAMES
    }


def is_skipped_money(name: str) -> bool:
    n = short_name(name).lower()
    return n in SKIP_MONEY or is_ghost_name(n)


def is_overflow_phone(name: str) -> bool:
    return short_name(name).lower() in OVERFLOW_NAMES


def inject_port_for_name(name: str) -> int:
    idx = _idx_from_name(name)
    if idx is None:
        idx = 0
    return INJECT_BASE + idx


def inject_proxy_for_name(name: str) -> str:
    return f"127.0.0.1:{inject_port_for_name(name)}"


def inject_listener_count(names: list[str] | None = None) -> int:
    """How many inject listeners (indices 0..max inclusive)."""
    idxs: list[int] = []
    src = list(names or [])
    if not src:
        try:
            src = [short for short, _serial, _proxy in discover_live_phones()]
        except Exception:
            src = []
    for n in src:
        idx = _idx_from_name(n)
        if idx is not None:
            idxs.append(idx)
    if not idxs:
        return 11
    return max(idxs) + 1


def _adb_online_serials(*, timeout: float = 6.0) -> set[str]:
    try:
        p = subprocess.run(
            [ADB, "devices"],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return set()
    online: set[str] = set()
    for line in (p.stdout or "").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            online.add(parts[0])
    return online


def _from_sticky(online: set[str] | None = None) -> list[tuple[str, str, str]]:
    ov = LOG / "farm_runtime_overrides.json"
    try:
        data = json.loads(ov.read_text(encoding="utf-8-sig")) if ov.is_file() else {}
    except Exception:
        data = {}
    phones = [
        p.strip()
        for p in str(data.get("CPHARM_FARM_PHONES") or "").split(",")
        if p.strip() and "vm11" not in p.lower()
    ]
    serials = [
        s.strip()
        for s in str(data.get("CPHARM_ADB_SERIALS") or "").split(",")
        if s.strip()
    ]
    out: list[tuple[str, str, str]] = []
    for i, phone in enumerate(phones):
        short = phone.split(".")[0]
        ser = serials[i] if i < len(serials) else ""
        if not ser:
            continue
        if is_skipped_money(short):
            continue
        if online is not None and ser not in online:
            continue
        out.append((short, ser, inject_proxy_for_name(phone)))
    return out


def _from_state_json(online: set[str]) -> list[tuple[str, str, str]]:
    """Map live ADB serials from each VM's misc/state.json AdbHost."""
    rows: list[tuple[str, str, str]] = []
    if not VMS_DIR.is_dir():
        return rows
    try:
        vms = list(VMS_DIR.iterdir())
    except OSError:
        return rows
    for vm in vms:
        if not vm.is_dir() or not vm.name.lower().startswith("vm"):
            continue
        short = short_name(vm.name)
        if is_skipped_money(short):
            continue
        state_path = vm / "misc" / "state.json"
        if not state_path.is_file():
            continue
        try:
            data = json.loads(state_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        host = str(data.get("AdbHost") or "").strip()
        port = data.get("AdbPort") or 5555
        if not host:
            continue
        try:
            serial = f"{host}:{int(port)}"
        except (TypeError, ValueError):
            continue
        if serial not in online:
            continue
        rows.append((short, serial, inject_proxy_for_name(short)))
    return rows


def _sort_key(name: str) -> int:
    idx = _idx_from_name(name)
    return 99 if idx is None else idx


def _dedupe_sort(rows: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """One row per phone name, then one phone per serial (no shared ADB)."""
    best: dict[str, tuple[str, str, str]] = {}
    for short, serial, _proxy in rows:
        key = short_name(short)
        prev = best.get(key)
        if prev is None or (
            serial.startswith("10.0.2.") and not prev[1].startswith("10.0.2.")
        ):
            best[key] = (key, serial, inject_proxy_for_name(key))
    # Second pass: one phone per serial. Stale vm0 state.json often copies a live
    # phone's AdbHost — preferring the lower index then pins inject 8218 on vm10.
    by_serial: dict[str, tuple[str, str, str]] = {}
    for key in sorted(best.keys(), key=_sort_key):
        row = best[key]
        ser = row[1]
        if not ser:
            continue
        prev = by_serial.get(ser)
        if prev is None:
            by_serial[ser] = row
            continue
        prev_i = _sort_key(prev[0])
        new_i = _sort_key(row[0])
        if prev_i == 0 and new_i > 0:
            by_serial[ser] = row
        elif new_i == 0 and prev_i > 0:
            continue
        elif new_i < prev_i:
            by_serial[ser] = row
    ordered = sorted(by_serial.values(), key=lambda r: _sort_key(r[0]))
    return ordered


def _from_cpharm(online: set[str]) -> list[tuple[str, str, str]]:
    """Same phone list CPharm.exe uses (MuMuFarmOps + ADB)."""
    rows: list[tuple[str, str, str]] = []
    try:
        from wizard.mumu_farm_ops import MuMuFarmOps

        farm = MuMuFarmOps()
        farm.list_instances()
        try:
            farm.refresh_serials()
        except Exception:
            pass
        for st in farm.get_all_phone_statuses():
            name = str(st.get("name") or "").strip()
            serial = str(st.get("adb_serial") or "").strip()
            if not name or not st.get("connected"):
                continue
            if is_skipped_money(name):
                continue
            if not serial or "ERR" in serial:
                continue
            if online and serial not in online:
                continue
            rows.append((short_name(name), serial, inject_proxy_for_name(name)))
    except Exception:
        return rows
    return rows


def _known_candidate_serials() -> list[str]:
    """Serials the farm already knows about, regardless of current adb state.

    Sources: sticky ``CPHARM_ADB_SERIALS`` overrides and each MuMu ARM VM's
    ``misc/state.json`` ``AdbHost``. These are the re-attach candidates when a
    phone falls off the adb server. Never raises.
    """
    cands: list[str] = []
    ov = LOG / "farm_runtime_overrides.json"
    try:
        if ov.is_file():
            data = json.loads(ov.read_text(encoding="utf-8-sig"))
            cands.extend(
                s.strip()
                for s in str(data.get("CPHARM_ADB_SERIALS") or "").split(",")
                if s.strip()
            )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    try:
        if VMS_DIR.is_dir():
            for vm in VMS_DIR.iterdir():
                if not vm.is_dir() or not vm.name.lower().startswith("vm"):
                    continue
                state_path = vm / "misc" / "state.json"
                if not state_path.is_file():
                    continue
                data = json.loads(state_path.read_text(encoding="utf-8-sig"))
                host = str(data.get("AdbHost") or "").strip()
                if not host:
                    continue
                try:
                    port = int(data.get("AdbPort") or 5555)
                except (TypeError, ValueError):
                    port = 5555
                cands.append(f"{host}:{port}")
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    # Dedupe while preserving order.
    return list(dict.fromkeys(cands))


def _reconnect_missing(online: set[str]) -> set[str]:
    """Re-attach known emulator serials that fell off the adb server.

    After an adb server restart (or a TCP registration timeout) every
    emulator that registered via ``adb connect`` vanishes from ``adb devices``
    even though the guest is healthy. Discovery used to treat those phones as
    gone. Re-issue ``adb connect`` for every known serial that is not currently
    online, then return the refreshed list. Never raises.
    """
    missing = [s for s in _known_candidate_serials() if s not in online]
    for serial in missing[:24]:
        try:
            subprocess.run(
                [ADB, "connect", serial],
                capture_output=True,
                text=True,
                timeout=4,
                encoding="utf-8",
                errors="replace",
            )
        except Exception:  # noqa: BLE001 — best-effort reconnect
            continue
    return _adb_online_serials(timeout=6.0)


def _select_money_set(rows: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """Canonical money phones only — drop ghost names and banned serials."""
    out: list[tuple[str, str, str]] = []
    for short, serial, proxy in rows:
        if is_skipped_money(short) or is_banned_serial(serial):
            continue
        if not is_canonical_phone(short):
            continue
        out.append((short, serial, proxy))
    return out


def discover_live_phones() -> list[tuple[str, str, str]]:
    """Return [(short_name, serial, proxy), ...] for CPharm-online money VMs.

    CPharm MuMuFarmOps is the source of truth. ARM state.json fills gaps.
    Sticky is last-resort. Tablet/ghost stay out. No hardcoded serials.
    """
    online = _adb_online_serials()
    online = _reconnect_missing(online)
    rows: list[tuple[str, str, str]] = []
    if online:
        rows.extend(_from_cpharm(online))
        rows.extend(_from_state_json(online))
        if not rows:
            rows.extend(_from_sticky(online))
    if not rows:
        return _select_money_set(_dedupe_sort(_from_cpharm(set()) or _from_sticky(None)))
    return _select_money_set(_dedupe_sort(rows))


def persist_discovered(phones: list[tuple[str, str, str]]) -> None:
    """Record live ADB snapshot — canonical lock only, no override JSON."""
    from automation.cpharm_farm_config import merge_runtime, write_adb_serial_lock

    floor = canonical_expect_phones()
    names = canonical_names_sorted()
    live_by_short = {
        short_name(short): serial
        for short, serial, _proxy in phones
        if not is_banned_serial(serial) and not is_skipped_money(short)
    }
    live_full = {
        f"{k}.gmadoa" if not k.endswith(".gmadoa") else k: v
        for k, v in live_by_short.items()
    }
    write_adb_serial_lock(live_full)
    merge_runtime(
        {
            "CPHARM_FARM_PHONES": ",".join(names),
            "CPHARM_ADB_SERIALS": ",".join(canonical_serials_sorted()),
            "CPHARM_FARM_PHONE_COUNT": str(floor),
            "CPHARM_FARM_EXPECT_PHONES": str(floor),
            "CPHARM_FARM_BAN_SERIALS": ",".join(sorted(BANNED_SERIALS)),
        },
        note="discover",
    )
    (LOG / "FARM_PHONES_CAPACITY.lock").write_text(",".join(names) + "\n", encoding="utf-8")
