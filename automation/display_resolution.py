"""Per-phone display resolution for farm identity uniqueness.

Device resolution = ``adb shell wm size`` (Override size), NOT browser viewport.
Portrait only. Changes throttled by PHARMFLOW_RES_MIN_INTERVAL_MIN / PHARMFLOW_DISPLAY_LOCK.
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DISPLAY_PROFILES: tuple[tuple[str, int], ...] = (
    ("720x1600", 320),
    ("1080x1920", 420),
    ("1080x2160", 400),
    ("1080x2220", 420),
    ("1080x2280", 440),
    ("1080x2316", 420),
    ("1080x2340", 440),
    ("1080x2400", 420),
    ("1080x2408", 400),
    ("1080x2460", 420),
    ("900x1600", 320),
)
TABLET_DISPLAY_PROFILES: tuple[tuple[str, int], ...] = (
    ("1600x2560", 320),
    ("1200x1920", 280),
    ("1536x2048", 320),
)
DEFAULT_RES_MIN_INTERVAL_MIN = 240
_SIZE_RE = re.compile(r"(\d+)x(\d+)", re.I)
_LOCK_NAME = "farm_display_resolutions.json"


@dataclass(frozen=True)
class DisplayProfile:
    size: str
    density: int


def _logs_dir() -> Path:
    raw = (os.environ.get("PHARMFLOW_LOGS") or r"C:\PharmFlow\logs").strip()
    return Path(raw)


def _lock_path() -> Path:
    return _logs_dir() / _LOCK_NAME


def _env_truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def res_min_interval_minutes() -> int:
    raw = (os.environ.get("PHARMFLOW_RES_MIN_INTERVAL_MIN") or "").strip()
    if not raw:
        return int(DEFAULT_RES_MIN_INTERVAL_MIN)
    try:
        return max(0, int(float(raw)))
    except (TypeError, ValueError):
        return int(DEFAULT_RES_MIN_INTERVAL_MIN)


def display_force_assign_enabled() -> bool:
    return _env_truthy("PHARMFLOW_DISPLAY_FORCE_ASSIGN")


def display_lock_enabled() -> bool:
    return _env_truthy("PHARMFLOW_DISPLAY_LOCK")


def parse_size_wh(size: str) -> tuple[int, int] | None:
    m = _SIZE_RE.search(size or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def is_portrait_size(size: str) -> bool:
    wh = parse_size_wh(size)
    return bool(wh) and wh[1] > wh[0]


def is_landscape_size(size: str) -> bool:
    wh = parse_size_wh(size)
    return bool(wh) and wh[0] > wh[1]


def device_role(*, serial: str = "", phone: str = "") -> str:
    name = (phone or "").strip().lower()
    if "tablet" in name or (os.environ.get("PHARMFLOW_TABLET_SERIAL") or "").strip() == (
        serial or ""
    ).strip():
        return "tablet"
    return "phone"


def profiles_for_role(role: str) -> tuple[tuple[str, int], ...]:
    if role == "tablet":
        return TABLET_DISPLAY_PROFILES
    return DISPLAY_PROFILES


def _parse_wm_size(text: str) -> str:
    """Extract Override or Physical size as WxH."""
    raw = text or ""
    for line in raw.splitlines():
        low = line.lower()
        if "override" in low and "size" in low:
            m = _SIZE_RE.search(line)
            if m:
                return f"{m.group(1)}x{m.group(2)}"
    m = _SIZE_RE.search(raw)
    return f"{m.group(1)}x{m.group(2)}" if m else ""


def read_wm_size(adb: Any, serial: str, *, timeout: float = 8.0) -> str:
    try:
        out = (adb.shell("wm size", serial=serial, timeout=timeout).stdout or "").strip()
    except Exception:
        return ""
    return _parse_wm_size(out)


def is_known_size(size: str) -> bool:
    s = _parse_wm_size(size) or (size or "").strip()
    known = {p[0] for p in DISPLAY_PROFILES} | {p[0] for p in TABLET_DISPLAY_PROFILES}
    return s in known


def _density_for_size(size: str, role: str = "phone") -> int:
    s = _parse_wm_size(size) or size
    for sz, dens in profiles_for_role(role):
        if sz == s:
            return dens
    for sz, dens in DISPLAY_PROFILES + TABLET_DISPLAY_PROFILES:
        if sz == s:
            return dens
    return 420


def portrait_swap(size: str) -> str:
    wh = parse_size_wh(size)
    if not wh:
        return size
    w, h = wh
    if h >= w:
        return f"{w}x{h}"
    return f"{h}x{w}"


def _load_lock() -> dict[str, Any]:
    path = _lock_path()
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return {"by_serial": {}, "updated": ""}


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


def _parse_iso(raw: str) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def serial_permanently_locked(serial: str) -> bool:
    data = _load_lock()
    if data.get("permanent_lock") or data.get("lock_mode") == "permanent":
        row = (data.get("by_serial") or {}).get(serial) or {}
        if isinstance(row, dict) and (
            row.get("permanent_lock") or row.get("locked") or data.get("permanent_lock")
        ):
            return True
    return False


def minutes_since_last_change(serial: str) -> float | None:
    row = (_load_lock().get("by_serial") or {}).get(serial) or {}
    if not isinstance(row, dict):
        return None
    dt = _parse_iso(str(row.get("changed_at") or row.get("updated") or ""))
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 60.0)


def may_change_resolution(serial: str) -> bool:
    if display_force_assign_enabled():
        return True
    if display_lock_enabled() or serial_permanently_locked(serial):
        return False
    interval = res_min_interval_minutes()
    if interval <= 0:
        return True
    mins = minutes_since_last_change(serial)
    if mins is None:
        return True
    return mins >= float(interval)


def occupied_sizes(*, exclude_serial: str = "") -> set[str]:
    out: set[str] = set()
    for ser, row in (_load_lock().get("by_serial") or {}).items():
        if ser == exclude_serial or not isinstance(row, dict):
            continue
        sz = str(row.get("size") or "").strip()
        if sz:
            out.add(sz)
    return out


def pick_display_profile(
    *,
    serial: str = "",
    phone: str = "",
    prefer_current: str = "",
    avoid: set[str] | None = None,
) -> DisplayProfile:
    role = device_role(serial=serial, phone=phone)
    pool = list(profiles_for_role(role))
    avoid = set(avoid or ())
    avoid |= occupied_sizes(exclude_serial=serial)
    cur = _parse_wm_size(prefer_current) or prefer_current
    if cur and is_portrait_size(cur) and cur not in avoid:
        return DisplayProfile(cur, _density_for_size(cur, role))
    free = [(sz, d) for sz, d in pool if sz not in avoid]
    if not free:
        free = pool
    sz, dens = random.choice(free)
    return DisplayProfile(sz, dens)


def remember_display(
    serial: str,
    *,
    size: str,
    density: int,
    phone: str = "",
    locked: bool = True,
) -> None:
    data = _load_lock()
    by = data.setdefault("by_serial", {})
    if not isinstance(by, dict):
        by = {}
        data["by_serial"] = by
    now = datetime.now(timezone.utc).isoformat()
    prev = by.get(serial) if isinstance(by.get(serial), dict) else {}
    row = {
        "size": size,
        "density": int(density),
        "phone": phone or str(prev.get("phone") or ""),
        "locked": locked,
        "permanent_lock": bool(
            prev.get("permanent_lock")
            or data.get("permanent_lock")
            or display_lock_enabled()
        ),
        "updated": now,
        "changed_at": now
        if str(prev.get("size") or "") != size
        else str(prev.get("changed_at") or now),
    }
    by[serial] = row
    data["updated"] = now
    if display_lock_enabled():
        data["permanent_lock"] = True
        data["lock_mode"] = "permanent"
    _atomic_write(_lock_path(), json.dumps(data, indent=2) + "\n")


def apply_display_profile(adb: Any, serial: str, profile: DisplayProfile) -> bool:
    try:
        adb.shell(f"wm size {profile.size}", serial=serial, timeout=10.0)
        adb.shell(f"wm density {int(profile.density)}", serial=serial, timeout=10.0)
        time.sleep(0.4)
        got = read_wm_size(adb, serial)
        return bool(got) and _parse_wm_size(got) == profile.size
    except Exception as exc:
        logger.warning("apply_display_profile %s failed: %s", serial, exc)
        return False


def claim_current_display(
    adb: Any, serial: str, *, phone: str = ""
) -> DisplayProfile | None:
    size = read_wm_size(adb, serial)
    if not size:
        return None
    if is_landscape_size(size):
        size = portrait_swap(size)
    dens = _density_for_size(size, device_role(serial=serial, phone=phone))
    remember_display(serial, size=size, density=dens, phone=phone)
    return DisplayProfile(size, dens)


def fix_landscape_if_needed(
    adb: Any, serial: str, *, phone: str = ""
) -> tuple[bool, str]:
    cur = read_wm_size(adb, serial)
    if not cur:
        return False, "no wm size"
    if is_portrait_size(cur):
        return True, cur
    portrait = portrait_swap(cur)
    if not is_known_size(portrait):
        profile = pick_display_profile(serial=serial, phone=phone)
        portrait = profile.size
        dens = profile.density
    else:
        dens = _density_for_size(portrait, device_role(serial=serial, phone=phone))
    ok = apply_display_profile(adb, serial, DisplayProfile(portrait, dens))
    if ok:
        remember_display(serial, size=portrait, density=dens, phone=phone)
        return True, portrait
    return False, cur


def ensure_portrait_display(
    adb: Any, serial: str, *, phone: str = ""
) -> tuple[bool, str]:
    """Landscape bypasses DISPLAY_LOCK; portrait returns current size."""
    return fix_landscape_if_needed(adb, serial, phone=phone)


def scramble_display(
    adb: Any, serial: str, *, phone: str = "", force: bool = False
) -> DisplayProfile | None:
    if not force and not may_change_resolution(serial):
        return claim_current_display(adb, serial, phone=phone)
    profile = pick_display_profile(
        serial=serial, phone=phone, prefer_current=read_wm_size(adb, serial)
    )
    if apply_display_profile(adb, serial, profile):
        remember_display(
            serial, size=profile.size, density=profile.density, phone=phone
        )
        return profile
    return claim_current_display(adb, serial, phone=phone)


def ensure_unique_display(
    adb: Any,
    serial: str,
    *,
    phone: str = "",
    scramble: bool = False,
) -> tuple[bool, str]:
    """Ensure portrait known size; optionally scramble if unlocked."""
    ok_p, size = ensure_portrait_display(adb, serial, phone=phone)
    if not ok_p:
        return False, size
    cur = read_wm_size(adb, serial) or size
    occupied = occupied_sizes(exclude_serial=serial)
    needs = (not is_known_size(cur)) or (cur in occupied) or scramble
    if needs and may_change_resolution(serial):
        profile = pick_display_profile(
            serial=serial, phone=phone, prefer_current=cur, avoid=occupied
        )
        if apply_display_profile(adb, serial, profile):
            remember_display(
                serial, size=profile.size, density=profile.density, phone=phone
            )
            return True, profile.size
    if is_known_size(cur) and is_portrait_size(cur):
        dens = _density_for_size(cur, device_role(serial=serial, phone=phone))
        remember_display(serial, size=cur, density=dens, phone=phone)
        return True, cur
    # locked but bad — still claim current
    claim_current_display(adb, serial, phone=phone)
    return bool(cur), cur


def maybe_rotate_display_for_isolate(
    adb: Any, serial: str, *, phone: str = ""
) -> DisplayProfile | None:
    """Honor DISPLAY_LOCK / RES_MIN — usually claim only, no thrash."""
    ok_p, _ = ensure_portrait_display(adb, serial, phone=phone)
    if not ok_p:
        return None
    if display_lock_enabled() or not may_change_resolution(serial):
        return claim_current_display(adb, serial, phone=phone)
    return scramble_display(adb, serial, phone=phone, force=False)


def set_global_permanent_lock(enabled: bool = True) -> None:
    data = _load_lock()
    data["permanent_lock"] = bool(enabled)
    data["lock_mode"] = "permanent" if enabled else "interval"
    data["updated"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(_lock_path(), json.dumps(data, indent=2) + "\n")


def assign_distinct_to_serials(
    adb: Any,
    serials: list[str],
    *,
    phones: dict[str, str] | None = None,
) -> dict[str, str]:
    phones = phones or {}
    used: set[str] = set()
    out: dict[str, str] = {}
    for serial in serials:
        phone = phones.get(serial, "")
        profile = pick_display_profile(
            serial=serial, phone=phone, avoid=used
        )
        used.add(profile.size)
        if apply_display_profile(adb, serial, profile):
            remember_display(
                serial, size=profile.size, density=profile.density, phone=phone
            )
            out[serial] = profile.size
        else:
            out[serial] = read_wm_size(adb, serial)
    return out


def sanitize_lock_file_portrait_only() -> int:
    data = _load_lock()
    by = data.get("by_serial")
    if not isinstance(by, dict):
        return 0
    fixed = 0
    for ser, row in list(by.items()):
        if not isinstance(row, dict):
            continue
        sz = str(row.get("size") or "")
        if is_landscape_size(sz):
            row["size"] = portrait_swap(sz)
            row["updated"] = datetime.now(timezone.utc).isoformat()
            fixed += 1
    if fixed:
        data["updated"] = datetime.now(timezone.utc).isoformat()
        _atomic_write(_lock_path(), json.dumps(data, indent=2) + "\n")
    return fixed
