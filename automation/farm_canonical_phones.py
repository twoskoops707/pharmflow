"""Farm phone fleet — derived from this machine's live MuMu VMs, never hardcoded.

The old module pinned a fixed 8-VM roster with yesterday's guest IPs. VMs get
renumbered or pruned by the MuMu manager on every reboot, and docker / Android
Studio / cloud devices come and go — so any pinned list goes stale and the farm
idles while a live phone waits. The fleet is therefore read from disk each time:

  * names    = vm*.gmadoa folders under the MuMu install (current reality)
  * serials  = each VM's misc/state.json AdbHost:AdbPort (published by the guest)
  * fallback = PHARMFLOW_FARM_PHONES env (operator's explicit override, no MuMu box)

Nothing here decides which phones the FARM runs; the farm runs whatever is live
on ADB. This module only answers "what fleet exists on this box right now" for
tools that want to manage or report on the box's own phones.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Final

_MUMU_CANDIDATES = (
    Path(r"C:\Program Files\Netease\MuMuPlayerARM"),
    Path(r"C:\Program Files\Netease\MuMuPlayer 12"),
    Path(r"C:\Program Files\Netease\MuMuPlayer"),
)
_VM_DIR_RE = re.compile(r"^vm(\d+)\.gmadoa$", re.IGNORECASE)

# Localhost proxy ports are never farmed as devices; everything else that is
# LIVE on ADB is farmable. IPs recycle across reboots, so no 10.0.2.x / emulator
# serial is banned by default — the operator can still ban via PHARMFLOW_FARM_BAN_SERIALS.
BANNED_SERIALS: Final[frozenset[str]] = frozenset()
BANNED_PHONE_NAMES: Final[frozenset[str]] = frozenset({"base", "base.gmadoa"})


def _mumu_root() -> Path | None:
    env = (os.environ.get("PHARMFLOW_MUMU_ROOT") or "").strip()
    if env:
        p = Path(env)
        if p.is_dir():
            return p
    for cand in _MUMU_CANDIDATES:
        if cand.is_dir():
            return cand
    return None


def _fleet_from_env() -> dict[str, str]:
    """Operator override (PHARMFLOW_FARM_PHONES=vm0,vm1,...) — serials empty; live
    ADB or the caller resolves them. Used only when no MuMu vms dir exists."""
    raw = os.environ.get("PHARMFLOW_FARM_PHONES") or ""
    out: dict[str, str] = {}
    for part in str(raw).split(","):
        name = str(part).strip().lstrip("\ufeff")
        if name:
            out[name if "." in name else f"{name}.gmadoa"] = ""
    return out


def _serial_from_state(vm_path: Path) -> str:
    """MuMu ARM publishes the guest ADB endpoint in misc/state.json."""
    state_path = vm_path / "misc" / "state.json"
    if not state_path.is_file():
        return ""
    try:
        data = json.loads(state_path.read_text(encoding="utf-8-sig"))
        host = str(data.get("AdbHost") or "").strip()
        port = data.get("AdbPort") or 5555
        if host:
            return f"{host}:{int(port)}"
    except (OSError, ValueError, json.JSONDecodeError, TypeError):
        pass
    return ""


def _fleet_from_disk() -> dict[str, str]:
    """name → serial for every MuMu VM folder currently on this box."""
    root = _mumu_root()
    if root is None:
        return _fleet_from_env()
    vms_dir = root / "vms"
    if not vms_dir.is_dir():
        return _fleet_from_env()
    out: dict[str, str] = {}
    for child in sorted(vms_dir.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        m = _VM_DIR_RE.match(child.name)
        if not m:
            continue
        serial = _serial_from_state(child)
        if serial:
            out[child.name] = serial
        else:
            out[child.name] = ""
    if not out:
        return _fleet_from_env()
    return out


def _sorted_names(fleet: dict[str, str]) -> list[str]:
    def key(name: str) -> int:
        m = _VM_DIR_RE.match(name)
        return int(m.group(1)) if m else 999
    return sorted(fleet.keys(), key=key)


def _running_vm_indices() -> set[int]:
    """VmIndex set of MuMu shells actually running right now (live authority)."""
    import psutil
    idxs: set[int] = set()
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            if "nemux-shell" not in (proc.info["name"] or "").lower():
                continue
            cmd = " ".join(proc.info["cmdline"] or [])
            m = re.search(r"--VmIndex\s+(\d+)", cmd)
            if m:
                idxs.add(int(m.group(1)))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return idxs


def _fleet() -> dict[str, str]:
    fleet = _fleet_from_disk()
    running = _running_vm_indices()
    if running:
        # LIVE-ONLY fleet: running shells are the authority. Stale disk folders
        # are NOT phones — a 49-folder disk snapshot poisoned the roster, Tor
        # lane sizing and inject port mapping on 2026-09-13 (OPS_NOTES).
        keep = {
            name: serial
            for name, serial in fleet.items()
            if (m := _VM_DIR_RE.match(name)) and int(m.group(1)) in running
        }
        if keep:
            return keep
    return fleet


# Import-time snapshot for legacy direct-dict consumers. Prefer the functions;
# they re-derive on every call so the fleet tracks manager prunes/renumbers.
CANONICAL_FARM_PHONES: Final[dict[str, str]] = _fleet()


def canonical_expect_phones() -> int:
    # Operator override wins, else live shells, else disk fleet (cold start).
    env = (os.environ.get("PHARMFLOW_FARM_EXPECT_PHONES") or "").strip()
    if env.isdigit() and int(env) > 0:
        return int(env)
    return len(_fleet())


def canonical_names_sorted() -> list[str]:
    return _sorted_names(_fleet())


def canonical_serials_sorted() -> list[str]:
    return [_fleet().get(n, "") for n in canonical_names_sorted()]


def disk_fleet_map() -> dict[str, str]:
    """Full on-disk MuMu VM roster (cold + stopped), never live-only shrunk."""
    return dict(_fleet_from_disk())


def disk_fleet_names_sorted() -> list[str]:
    return _sorted_names(_fleet_from_disk())


def is_banned_serial(serial: str) -> bool:
    s = (serial or "").strip()
    if not s:
        return True
    # Localhost proxy ports are not devices; anything real is farmable.
    return s.startswith("127.0.0.1:")


def is_banned_phone(name: str) -> bool:
    return (name or "").strip().lower() in BANNED_PHONE_NAMES


def ban_serials_csv() -> str:
    operator = os.environ.get("PHARMFLOW_FARM_BAN_SERIALS") or ""
    parts = [s.strip() for s in str(operator).split(",") if s.strip()]
    return ",".join(sorted(set(parts)))


def is_canonical_phone(name: str) -> bool:
    """True when the name is a VM folder on this box (or operator-listed)."""
    short = (name or "").split(".")[0].strip().lower()
    return f"{short}.gmadoa" in _fleet() or (name or "").strip() in _fleet()


def canonical_inject_ports() -> list[int]:
    return [8218 + int(m.group(1)) for m in (_VM_DIR_RE.match(n) for n in canonical_names_sorted()) if m]


def canonical_workset(
    online_serials: set[str] | frozenset[str] | None = None,
) -> list[tuple[str, str, str]]:
    """(short, serial, proxy) for the fleet on this box.

    Serial comes from the VM's own state.json (fresh) or the online ADB set —
    never from a pinned table. ``online_serials`` narrows which rows are
    reported as ready but every row is listed so operators see the fleet.
    """
    online = set(online_serials or ())
    rows: list[tuple[str, str, str]] = []
    fleet = _fleet()
    for fname in _sorted_names(fleet):
        short = fname.split(".")[0]
        m = _VM_DIR_RE.match(fname)
        idx = int(m.group(1)) if m else 0
        proxy = f"127.0.0.1:{8218 + idx}"
        serial = (fleet.get(fname) or "").strip()
        # Always list every fleet row (operator visibility). When the caller
        # passes online_serials, still include offline rows — never collapse to
        # empty-serial placeholders only (that made am start hit
        # "more than one device/emulator" with adb -s "").
        if online and serial and serial not in online:
            rows.append((short, serial, proxy))
            continue
        rows.append((short, serial, proxy))
    return rows
