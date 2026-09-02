"""Tablet visit scheduling: 1 tablet sequence per N successful phone visits.

State: C:\\CPharm\\logs\\farm_tablet_schedule.json
Sticky / env:
  CPHARM_TABLET_PHONE          MuMu instance name (e.g. tablet.gmadoa)
  CPHARM_TABLET_SERIAL         Optional ADB serial when MuMu restarts
  CPHARM_TABLET_EVERY_N_PHONE_VISITS  Default 10
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_STATE_NAME = "farm_tablet_schedule.json"
_lock = threading.Lock()
_tablet_due = threading.Event()


def _logs_dir() -> Path:
    raw = (os.environ.get("CPHARM_LOGS") or r"C:\CPharm\logs").strip()
    return Path(raw)


def _state_path() -> Path:
    return _logs_dir() / _STATE_NAME


def tablet_every_n() -> int:
    raw = (os.environ.get("CPHARM_TABLET_EVERY_N_PHONE_VISITS") or "10").strip()
    try:
        return max(1, int(float(raw)))
    except (TypeError, ValueError):
        return 10


def tablet_phone_name() -> str:
    return (os.environ.get("CPHARM_TABLET_PHONE") or "").strip()


def tablet_serial_override() -> str:
    return (os.environ.get("CPHARM_TABLET_SERIAL") or "").strip()


def is_tablet_phone(name: str) -> bool:
    n = (name or "").strip().lower()
    if not n:
        return False
    if "tablet" in n:
        return True
    tab = tablet_phone_name().lower()
    return bool(tab) and n == tab


def _empty_state() -> dict[str, Any]:
    return {
        "phone_visits_since_tablet": 0,
        "tablet_visits_total": 0,
        "tablet_pending": False,
        "last_tablet_at": "",
        "updated": "",
    }


def load_state() -> dict[str, Any]:
    path = _state_path()
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                out = _empty_state()
                out.update(data)
                return out
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return _empty_state()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_state(state: dict[str, Any]) -> None:
    state = dict(state)
    state["updated"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(_state_path(), json.dumps(state, indent=2) + "\n")


def record_phone_visit_ok() -> bool:
    """Increment phone OK counter; return True if a tablet visit was queued."""
    with _lock:
        every = tablet_every_n()
        if not tablet_phone_name() and not tablet_serial_override():
            return False
        state = load_state()
        n = int(state.get("phone_visits_since_tablet") or 0) + 1
        state["phone_visits_since_tablet"] = n
        queued = False
        if n >= every:
            state["phone_visits_since_tablet"] = 0
            state["tablet_pending"] = True
            queued = True
            _tablet_due.set()
            logger.info(
                "tablet schedule: due after %d phone OK visits (every=%d)",
                every,
                every,
            )
        save_state(state)
        return queued


def tablet_visit_pending() -> bool:
    with _lock:
        return bool(load_state().get("tablet_pending"))


def consume_tablet_pending() -> bool:
    with _lock:
        state = load_state()
        if not state.get("tablet_pending"):
            return False
        state["tablet_pending"] = False
        save_state(state)
        _tablet_due.clear()
        return True


def wait_tablet_due(timeout: float = 30.0) -> bool:
    if tablet_visit_pending():
        return True
    return bool(_tablet_due.wait(timeout=max(0.1, float(timeout))))


def record_tablet_visit_ok() -> None:
    with _lock:
        state = load_state()
        state["tablet_visits_total"] = int(state.get("tablet_visits_total") or 0) + 1
        state["last_tablet_at"] = datetime.now(timezone.utc).isoformat()
        state["tablet_pending"] = False
        save_state(state)
        _tablet_due.clear()


def resolve_tablet_serial(farm: Any) -> tuple[str, str]:
    """Return (phone_name, adb_serial) or ('', '') if tablet not configured/online."""
    phone = tablet_phone_name()
    if not phone:
        return "", ""
    override = tablet_serial_override()
    serial = override
    try:
        if hasattr(farm, "get_phone"):
            inst = farm.get_phone(phone)
            if inst is not None:
                ser = str(getattr(inst, "adb_serial", "") or "").strip()
                if ser:
                    serial = ser
        if not serial and hasattr(farm, "list_instances"):
            for inst in farm.list_instances():
                name = str(getattr(inst, "name", "") or "").strip()
                if name.lower() == phone.lower() or is_tablet_phone(name):
                    serial = str(getattr(inst, "adb_serial", "") or "").strip()
                    phone = name or phone
                    break
        if serial and hasattr(farm, "adb"):
            try:
                farm.adb.run("connect", serial, timeout=8.0)
            except Exception as exc:
                logger.debug("tablet connect soft-fail: %s", exc)
    except Exception as exc:
        logger.debug("tablet resolve soft-fail: %s", exc)
    if not serial:
        return phone, ""
    return phone, serial
