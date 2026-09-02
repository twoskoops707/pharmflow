"""Hard rule: concurrent farm phones must NEVER share the same public exit IP.

Used by run_farm_354, farm_remediate_loop, and CPharm Start farm. Not env-gated.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from automation.mantis_inject_proxy import inject_enabled, phone_inject_port
from automation.tor_manager import TorManager, release_exit_ip

logger = logging.getLogger(__name__)

LOG_DIR = Path(r"C:\CPharm\logs")
AUDIT_PATH = LOG_DIR / "farm_exit_ip_audit.json"
MAX_ENFORCE_ROUNDS = 4


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _phone_index(name: str, fallback: int | None = None) -> int:
    stem = name.split(".")[0]
    if stem.startswith("vm") and stem[2:].isdigit():
        return int(stem[2:])
    return int(fallback if fallback is not None else 0)


def _shell_text(result: Any) -> str:
    if result is None:
        return ""
    out = getattr(result, "stdout", result)
    return out.strip() if hasattr(out, "strip") else str(out).strip()


def probe_phone_exit_ip(
    tor: TorManager,
    phone_index: int,
    serial: str,
    adb: Any,
) -> str:
    """Return public exit IP for one phone (Tor tunnel first, then inject curl)."""
    ip = (tor.fetch_exit_ip(phone_index) or "").strip()
    if ip:
        return ip
    if serial and inject_enabled():
        port = phone_inject_port(phone_index)
        try:
            cmd = (
                f"curl -s --max-time 10 -x http://127.0.0.1:{port} "
                "https://api.ipify.org 2>/dev/null"
            )
            ip = _shell_text(adb.shell(cmd, serial=serial))
            if ip and len(ip) <= 45 and "." in ip:
                return ip
        except Exception as exc:
            logger.debug("inject ip probe failed phone=%d serial=%s: %s", phone_index, serial, exc)
    return ""


def find_shared_exit_ips(ip_by_phone: dict[str, str]) -> dict[str, list[str]]:
    """Map duplicate IP -> phone names (only non-empty IPs)."""
    buckets: dict[str, list[str]] = defaultdict(list)
    for phone, ip in ip_by_phone.items():
        if ip:
            buckets[ip].append(phone)
    return {ip: names for ip, names in buckets.items() if len(names) > 1}


def audit_concurrent_exit_ips(
    tor: TorManager,
    adb: Any,
    phone_rows: list[tuple[str, str, int]],
) -> dict[str, Any]:
    """Probe all online phones; return audit dict with collisions."""
    ip_by_phone: dict[str, str] = {}
    for name, serial, idx in phone_rows:
        ip_by_phone[name] = probe_phone_exit_ip(tor, idx, serial, adb)
    shared = find_shared_exit_ips(ip_by_phone)
    audit = {
        "ts": _utc(),
        "phones": ip_by_phone,
        "shared": shared,
        "unique_ok": not shared,
        "rule": "NEVER_SHARE_EXIT_IP",
    }
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        AUDIT_PATH.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    return audit


def enforce_farm_unique_exit_ips(
    tor: TorManager,
    adb: Any,
    phone_rows: list[tuple[str, str, int]],
    *,
    max_rounds: int = MAX_ENFORCE_ROUNDS,
) -> list[str]:
    """Rotate Tor on colliding phones until all concurrent exit IPs are unique.

    ``phone_rows`` = (phone_name, adb_serial, phone_index).
    Never kills emulators — Tor NEWNYM / restart tor process only.
    """
    fixes: list[str] = []
    if not phone_rows:
        return fixes

    name_to_row = {name: (serial, idx) for name, serial, idx in phone_rows}

    for round_n in range(1, max(1, max_rounds) + 1):
        audit = audit_concurrent_exit_ips(tor, adb, phone_rows)
        shared: dict[str, list[str]] = audit.get("shared") or {}
        if not shared:
            if round_n == 1:
                fixes.append("exit_ip_unique OK")
            else:
                fixes.append(f"exit_ip_unique OK after round {round_n - 1}")
            return fixes

        fixes.append(f"exit_ip_COLLISION round={round_n} groups={len(shared)}")
        for ip, names in shared.items():
            fixes.append(f"  shared {ip}: {','.join(names)}")
            # Keep first phone on this IP; rotate all others.
            for name in names[1:]:
                serial, idx = name_to_row[name]
                release_exit_ip(idx)
                result = tor.rotate_until_unique_ip(
                    idx,
                    serial,
                    max_retries=6,
                    avoid_other_phones=True,
                )
                tag = "OK" if result.ok else "FAIL"
                fixes.append(
                    f"  rotate {name} idx={idx} {tag} "
                    f"{result.before}->{result.after} err={result.error or ''}".strip()
                )

    audit = audit_concurrent_exit_ips(tor, adb, phone_rows)
    if audit.get("shared"):
        fixes.append("exit_ip_COLLISION persists — sequences must not start on dup IPs")
        logger.error("FARM EXIT IP COLLISION persists: %s", audit.get("shared"))
    return fixes


def phone_rows_from_farm_ops(farm: Any, online: list[tuple[str, int]]) -> list[tuple[str, str, int]]:
    """Build rows from MuMuFarmOps online list [(name, idx), ...]."""
    rows: list[tuple[str, str, int]] = []
    for name, idx in online:
        inst = farm.get_phone(name)
        serial = (getattr(inst, "adb_serial", None) or "").strip() if inst else ""
        if serial:
            rows.append((name, serial, idx))
    return rows


def phone_rows_from_remediator(
    phones: list[tuple[str, str, str]],
) -> list[tuple[str, str, int]]:
    """Build rows from remediator PHONES [(name, serial, proxy), ...]."""
    rows: list[tuple[str, str, int]] = []
    for name, serial, _proxy in phones:
        if serial:
            rows.append((name, serial, _phone_index(name)))
    return rows
