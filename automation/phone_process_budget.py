"""1:1 phone-side process budget — active ADB/phone count owns every helper class.

Operator hard rule: Tor, inject listeners, ADB helpers, FarmBrowser/stealth
lanes, and any other per-phone helper must match active phone count 1:1.
No orphan extras of any class.

This is a *live-fleet budget* (N = phones up / lock-map money set), not a
hardcoded phone-count ceiling. Operator config and live ADB remain law for
how many phones exist; spawners may not invent surplus lanes beyond that N.
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("phone_process_budget")

_VM_IDX = re.compile(r"^vm(\d+)", re.IGNORECASE)
_CREATE_NO_WINDOW = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)
INJECT_BASE = int(
    os.environ.get("PHARMFLOW_MANTIS_INJECT_BASE")
    or os.environ.get("CPHARM_MANTIS_INJECT_BASE")
    or "8218"
)


@dataclass(frozen=True)
class PhoneBudget:
    """Live per-phone roster with packed Tor slots and absolute inject indices."""

    names: tuple[str, ...]
    serials: tuple[str, ...]
    abs_indices: tuple[int, ...]
    slots: tuple[int, ...]
    count: int

    @property
    def inject_ports(self) -> tuple[int, ...]:
        return tuple(INJECT_BASE + i for i in self.abs_indices)


def _logs_dirs() -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for name in (
        "PHARMFLOW_LOGS",
        "PHARMFLOW_LOG_DIR",
        "CPHARM_LOGS",
        "CPHARM_LOG_DIR",
    ):
        raw = (os.environ.get(name) or "").strip()
        if not raw:
            continue
        key = str(Path(raw)).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(Path(raw))
    for raw in (r"C:\PharmFlow\logs", r"C:\CPharm\logs"):
        key = str(Path(raw)).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(Path(raw))
    return out


def _vm_index(name: str) -> int | None:
    m = _VM_IDX.match((name or "").split(".")[0].strip())
    return int(m.group(1)) if m else None


def _read_lock_phones() -> list[tuple[str, str, int]]:
    """(name, serial, abs_idx) from ADB_SERIAL_MAP.lock.json."""
    for logs in _logs_dirs():
        path = logs / "ADB_SERIAL_MAP.lock.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        phones = dict(data.get("phones") or {})
        if not phones:
            continue
        rows: list[tuple[str, str, int]] = []
        for name, serial in phones.items():
            ser = str(serial or "").strip()
            if not ser or ser.startswith("127.0.0.1:"):
                continue
            idx = _vm_index(str(name))
            if idx is None:
                continue
            rows.append((str(name), ser, idx))
        if rows:
            rows.sort(key=lambda r: r[2])
            return rows
    return []


def _adb_live_serials() -> set[str]:
    try:
        from automation.farm_exe_self_heal import adb_live_serials

        return set(adb_live_serials())
    except Exception:
        pass
    try:
        from automation.farm_phone_discover import _adb_online_serials

        return set(_adb_online_serials())
    except Exception:
        return set()


def active_phone_budget(*, live_serials: set[str] | None = None) -> PhoneBudget:
    """Derive the 1:1 process budget from the live money roster.

    Prefer lock-map phones that answer on ADB. If ADB is empty, keep the lock
    map (heal/bootstrap still needs exact abs indices). If the lock map is
    empty, fall back to live fleet discovery.
    """
    live = set(live_serials) if live_serials is not None else _adb_live_serials()
    rows = _read_lock_phones()
    if rows and live:
        rows = [r for r in rows if r[1] in live]
    if not rows:
        try:
            from automation.tor_manager import live_fleet_indices

            idxs = list(live_fleet_indices())
        except Exception:
            idxs = []
        if idxs:
            rows = [(f"vm{i}.gmadoa", "", i) for i in idxs]
    if not rows:
        try:
            from automation.farm_phone_discover import discover_live_phones

            discovered = list(discover_live_phones())
            for short, serial, _proxy in discovered:
                idx = _vm_index(short)
                if idx is None:
                    continue
                rows.append((f"{short}.gmadoa" if "." not in short else short, serial, idx))
            rows.sort(key=lambda r: r[2])
        except Exception:
            rows = []

    # One row per abs index (first serial wins).
    by_idx: dict[int, tuple[str, str, int]] = {}
    for name, ser, idx in rows:
        by_idx.setdefault(idx, (name, ser, idx))
    ordered = [by_idx[i] for i in sorted(by_idx)]
    names = tuple(r[0] for r in ordered)
    serials = tuple(r[1] for r in ordered)
    abs_indices = tuple(r[2] for r in ordered)
    slots = tuple(range(len(abs_indices)))
    return PhoneBudget(
        names=names,
        serials=serials,
        abs_indices=abs_indices,
        slots=slots,
        count=len(abs_indices),
    )


def phone_helper_count() -> int:
    """Active phone count for every per-phone helper class (Tor/inject/etc.)."""
    return active_phone_budget().count


def _tcp_open(port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _tor_http_base() -> int:
    for logs in _logs_dirs():
        path = logs / "tor_port_bases.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            base = int(data.get("http_base") or 0)
            if base > 0:
                return base
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    try:
        return int(
            os.environ.get("PHARMFLOW_TOR_HTTP_BASE")
            or os.environ.get("CPHARM_TOR_HTTP_BASE")
            or "8118"
        )
    except ValueError:
        return 8118


def _kill_pid(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    if sys.platform == "win32":
        try:
            r = subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                timeout=15,
                creationflags=_CREATE_NO_WINDOW,
            )
            return int(r.returncode or 0) == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    try:
        os.kill(pid, 9)
        return True
    except OSError:
        return False


def _listening_pid(port: int) -> int | None:
    try:
        import psutil
    except ImportError:
        return None
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status != "LISTEN":
                continue
            laddr = conn.laddr
            if not laddr or int(laddr.port) != int(port):
                continue
            if laddr.ip not in ("127.0.0.1", "::1", "0.0.0.0", "::"):
                continue
            pid = int(conn.pid or 0)
            return pid if pid > 0 else None
    except (psutil.Error, OSError, TypeError, ValueError):
        return None
    return None


def _http_port_from_tor_cmdline(cmdline: str) -> int | None:
    """Best-effort HTTPTunnelPort from ``tor.exe -f <cfg>``."""
    m = re.search(r"-f\s+(\S+)", cmdline or "", flags=re.I)
    if not m:
        return None
    cfg = Path(m.group(1).strip('"'))
    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        mm = re.match(r"HTTPTunnelPort\s+(?:127\.0\.0\.1:)?(\d+)", line.strip(), re.I)
        if mm:
            return int(mm.group(1))
    return None


def prune_surplus_tor(*, budget: PhoneBudget | None = None, apply: bool = True) -> list[str]:
    """Kill Tor listeners whose slot is outside 0..N-1 (extras beyond phone count)."""
    fixes: list[str] = []
    b = budget or active_phone_budget()
    n = int(b.count)
    http_base = _tor_http_base()
    allowed_ports = {http_base + s for s in b.slots}

    # Drop in-process owned Tor beyond budget first.
    try:
        from automation import tor_manager

        owned = getattr(tor_manager, "_tor_procs", {}) or {}
        for slot in list(owned.keys()):
            try:
                si = int(slot)
            except (TypeError, ValueError):
                continue
            if si >= n:
                if apply:
                    try:
                        tor_manager._terminate_owned_tor(si)
                    except Exception as exc:  # noqa: BLE001
                        fixes.append(f"tor_owned_stop_err slot={si}:{exc}")
                        continue
                fixes.append(f"tor_surplus_owned_slot={si}")
    except Exception as exc:  # noqa: BLE001
        fixes.append(f"tor_owned_prune_err:{exc}")

    # Scan a bounded window above N for squatters (N..N+64).
    scan_hi = max(n + 64, n + 1)
    for slot in range(n, scan_hi):
        port = http_base + slot
        if not _tcp_open(port):
            continue
        pid = _listening_pid(port)
        if pid is None:
            fixes.append(f"tor_surplus_listen port={port} slot={slot} pid=?")
            continue
        if apply and _kill_pid(pid):
            fixes.append(f"tor_surplus_killed pid={pid} port={port} slot={slot}")
        else:
            tag = "tor_surplus_would_kill" if not apply else "tor_surplus_kill_fail"
            fixes.append(f"{tag} pid={pid} port={port} slot={slot}")

    # Also cull tor.exe whose cfg HTTP port is outside the allowed set when
    # process count exceeds N (covers non-listening bootstraps).
    try:
        import psutil

        tor_rows: list[tuple[int, int | None]] = []
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = str(proc.info.get("name") or "").lower()
                if name not in {"tor.exe", "tor"}:
                    continue
                pid = int(proc.info.get("pid") or 0)
                cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or []))
                port = _http_port_from_tor_cmdline(cmd)
                tor_rows.append((pid, port))
            except (psutil.Error, TypeError, ValueError):
                continue
        extras = [
            (pid, port)
            for pid, port in tor_rows
            if port is not None and port not in allowed_ports
        ]
        # If we have more tor.exe than phones even with unknown ports, keep the
        # newest N that look budgeted and cull the rest only when port is known-surplus.
        if len(tor_rows) > n and extras:
            for pid, port in extras:
                if apply and _kill_pid(pid):
                    fixes.append(f"tor_surplus_cfg_killed pid={pid} port={port}")
                else:
                    tag = "tor_surplus_cfg_would_kill" if not apply else "tor_surplus_cfg_kill_fail"
                    fixes.append(f"{tag} pid={pid} port={port}")
        fixes.append(f"tor_budget n={n} live_tor≈{len(tor_rows)} base={http_base}")
    except ImportError:
        fixes.append(f"tor_budget n={n} psutil_missing base={http_base}")
    except Exception as exc:  # noqa: BLE001
        fixes.append(f"tor_surplus_scan_err:{exc}")

    if not any("tor_surplus" in f for f in fixes):
        fixes.append(f"tor_budget_ok n={n}")
    return fixes


def prune_surplus_inject(*, budget: PhoneBudget | None = None, apply: bool = True) -> list[str]:
    """Stop in-process inject proxies and kill surplus listeners outside live abs indices."""
    fixes: list[str] = []
    b = budget or active_phone_budget()
    keep = set(b.abs_indices)
    keep_ports = set(b.inject_ports)

    try:
        from automation import mantis_inject_proxy as mip

        stopped = mip.stop_inject_proxies_except(sorted(keep)) if apply else []
        if stopped:
            fixes.append(f"inject_inproc_stopped idxs={stopped}")
        else:
            fixes.append(f"inject_inproc_ok n={len(keep)}")
    except Exception as exc:  # noqa: BLE001
        fixes.append(f"inject_inproc_prune_err:{exc}")

    if not keep_ports and b.count == 0:
        fixes.append("inject_budget n=0")
        return fixes

    # Probe a window covering known keep ports ± neighbors for squatters.
    if keep:
        lo = min(keep)
        hi = max(keep)
        probe = list(range(max(0, lo - 2), hi + 8))
    else:
        probe = list(range(0, 8))
    for idx in probe:
        if idx in keep:
            continue
        port = INJECT_BASE + idx
        if not _tcp_open(port):
            continue
        pid = _listening_pid(port)
        if pid is None:
            fixes.append(f"inject_surplus_listen port={port} idx={idx}")
            continue
        # Only kill when the owner looks like an inject helper (never MuMu / EXE UI).
        owner_ok = False
        try:
            import psutil

            proc = psutil.Process(pid)
            cmd = " ".join(str(x) for x in (proc.cmdline() or [])).lower()
            owner_ok = any(
                m in cmd
                for m in (
                    "mantis_inject",
                    "inject_keepalive",
                    "run_mantis_inject",
                    "run_farm_354",
                    "pharmflow.exe",
                    "cpharm.exe",
                )
            )
        except Exception:
            owner_ok = False
        if not owner_ok:
            fixes.append(f"inject_surplus_foreign pid={pid} port={port}")
            continue
        if apply and _kill_pid(pid):
            fixes.append(f"inject_surplus_killed pid={pid} port={port} idx={idx}")
        else:
            tag = "inject_surplus_would_kill" if not apply else "inject_surplus_kill_fail"
            fixes.append(f"{tag} pid={pid} port={port} idx={idx}")

    fixes.append(f"inject_budget n={b.count} ports={list(b.inject_ports)[:12]}")
    return fixes


def enforce_phone_process_budget(
    *,
    live_serials: set[str] | list[str] | None = None,
    apply: bool = True,
) -> list[str]:
    """Cap every phone-side helper class to active phone count 1:1."""
    live_set: set[str] | None
    if live_serials is None:
        live_set = None
    else:
        live_set = {str(s).strip() for s in live_serials if str(s).strip()}
    budget = active_phone_budget(live_serials=live_set)
    fixes: list[str] = [f"phone_budget n={budget.count} abs={list(budget.abs_indices)[:16]}"]
    # Publish slot map so Tor dials stay packed 0..N-1.
    if budget.abs_indices:
        slot_map = {str(idx): slot for slot, idx in enumerate(budget.abs_indices)}
        raw = json.dumps(slot_map, separators=(",", ":"))
        os.environ["PHARMFLOW_INJECT_SLOT_MAP"] = raw
        os.environ["CPHARM_INJECT_SLOT_MAP"] = raw
        fixes.append(f"slot_map n={budget.count}")
    fixes.extend(prune_surplus_tor(budget=budget, apply=apply))
    fixes.extend(prune_surplus_inject(budget=budget, apply=apply))
    return fixes


def budget_snapshot() -> dict[str, Any]:
    b = active_phone_budget()
    return {
        "count": b.count,
        "names": list(b.names),
        "serials": list(b.serials),
        "abs_indices": list(b.abs_indices),
        "slots": list(b.slots),
        "inject_ports": list(b.inject_ports),
        "tor_http_base": _tor_http_base(),
    }
