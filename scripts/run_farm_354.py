#!/usr/bin/env python3
"""
Farm runner — Path 1/2 primary, Path 3 ads capped.

Cadence (default = 24h day mode):
  - Soft cap: 15 sequences per hour per phone, spread across the hour
  - Per-phone daily visit/ad budgets (midnight reset) — not hour cycles
  - Path 3 (ad): scheduled into Path 1/2 under per-phone daily ad caps
  - PHARMFLOW_FARM_HOURS=0 / --hours 0 → run all day on daily caps

    $env:PHARMFLOW_ALLOW_SEQUENCE_RUNS='1'
    $env:PHARMFLOW_FARM_PATHS='1,2,3'
    $env:PHARMFLOW_FARM_ALLOW_ADS='1'
    $env:PHARMFLOW_FARM_DAILY_VISITS='148,102,97,52'
    $env:PHARMFLOW_FARM_DAILY_ADS='5,1,4,2'
    py scripts/run_farm_354.py --hours 0
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
import re
import sys
import threading
import time
import traceback
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import automation.no_window  # noqa: E402,F401  (kill child console-window flashes)
from automation import boot_gates  # noqa: E402
from automation.farm_visit_caps import apply_runtime_overrides_to_env  # noqa: E402
from automation.farm_pause import farm_halted  # noqa: E402

# Sticky money-day Path3 (CAP/GAP/ads/FALLBACK/FORCE_DIRECT/…) from
# farm_runtime_overrides.json MUST win before setdefaults — soft-recycle /
# bare spawn without launcher env must not fall back to CAP=5 / gap=180.
apply_runtime_overrides_to_env()

# Operator overrides (wizard Advanced panels -> wizard_farm_settings.json) are
# applied a second time HERE because the SSOT merge above unconditionally
# clobbers env. Re-applying from the operator file after that merge makes the
# wizard the authority over the listed keys for this lane process, no matter
# which code path spawned it (EXE unison lane, dev runner, soft recycle).
try:
    from wizard.farm_settings import apply_saved_to_env as _apply_operator_overrides

    _operator_applied = _apply_operator_overrides()
except Exception:
    _operator_applied = 0

from wizard.wizard_paths import bundled_adb_path

os.environ.setdefault("PHARMFLOW_ADB", str(bundled_adb_path()))

os.environ.setdefault("PHARMFLOW_ALLOW_SEQUENCE_RUNS", "1")
# Wait for Mantis creatives to paint before Path3 taps (0 = never engage fill/fallback).
os.environ.setdefault("PHARMFLOW_EMULATOR_AD_FILL_WAIT", "4")
# Browse mode: honor env/overrides/desktop_prefs (scramble recommended for ad fill).
# Isolation still does wipe + fingerprint/IMEI + unique exit when required.
_browse = os.environ.get("PHARMFLOW_BROWSE_PROXY_MODE", "").strip().lower()
if _browse not in ("scramble", "tor", "direct", "upstream"):
    try:
        from automation.browse_proxy import sync_browse_proxy_env_from_prefs

        sync_browse_proxy_env_from_prefs()
    except Exception:
        os.environ["PHARMFLOW_BROWSE_PROXY_MODE"] = "scramble"
os.environ.setdefault("PHARMFLOW_REQUIRE_UNIQUE_EXIT_IP", "1")
os.environ.setdefault("PHARMFLOW_GEO_TIME_WINDOW", "1")
os.environ["PHARMFLOW_UNIQUE_EXIT_IP_RETRIES"] = os.environ.get("PHARMFLOW_UNIQUE_EXIT_IP_RETRIES") or "12"
# Ads must paint on Path1/2/3 browse — keep the live Mantis zone refresh on.
os.environ["PHARMFLOW_SKIP_MANTIS_PATCH"] = "0"
os.environ.setdefault("PHARMFLOW_DABFLOW_MANTIS_PATCH", "1")
# Every sequence: cookies + fingerprint + IP + proxy + IMEI (never skip on live farm).
os.environ["PHARMFLOW_SKIP_SEQUENCE_ISOLATION"] = "0"
os.environ["PHARMFLOW_ALLOW_SEQUENCE_RUNS"] = "1"
# Under Tor, briefly allow ad fill/fallback helpers so Path3 can engage when inventory is thin.
# FORCE_DIRECT/FALLBACK default OFF — host-IP egress forbidden; SSOT/dash override if needed.
os.environ.setdefault("PHARMFLOW_EMULATOR_AD_MODE", "1")
os.environ.setdefault("PHARMFLOW_EMULATOR_AD_FORCE_DIRECT", "0")
os.environ.setdefault("PHARMFLOW_EMULATOR_AD_FALLBACK", "0")
# MITM HTML inject + baked SSP creatives (Firefox/Brave/DDG have no Chromium CDP).
# Inject stays ON. MITM stays ON — OPS_NOTES: CERTIFICATE_UNKNOWN is fixed by
# install_ca=True, not by turning MITM off (that zeros painted ads).
os.environ["PHARMFLOW_MANTIS_INJECT_PROXY"] = "1"
os.environ["PHARMFLOW_MANTIS_INJECT_MITM"] = "1"
# Standing rule 7: host-IP billing is forbidden. Assignment, not setdefault —
# a parent "1" (wizard_farm_settings.json) must not be inherited. Mantis
# dedupes host-IP clicks and they pay $0. Billing leaves each phone's exit.
os.environ["PHARMFLOW_MANTIS_BILLING_DIRECT"] = "0"
# Do NOT setdefault ALLOW_ADS=1 / PATHS=1,2,3 — that kept Path3 constantly on.
# Unset → _ads_allowed() false, _farm_paths() = {1,2}.
os.environ.setdefault("PHARMFLOW_FARM_SEQS_PER_HOUR", "15")

from automation.config import REQUIRED_SEQUENCE_VERSION, sequences_run_allowed
from automation.display_resolution import (
    _parse_wm_size,
    ensure_portrait_display,
    ensure_unique_display,
    is_known_size,
    is_portrait_size,
    read_wm_size,
    sanitize_lock_file_portrait_only,
)
from automation.tablet_scheduler import (
    consume_tablet_pending,
    is_tablet_phone,
    record_phone_visit_ok,
    record_tablet_visit_ok,
    resolve_tablet_serial,
    tablet_every_n,
    tablet_phone_name,
    tablet_serial_override,
    wait_tablet_due,
)
from automation.farm_unique_seq import UniqueSequenceLock, identity_keys as farm_identity_keys
from automation.farm_phone_discover import short_name as _phone_short
from automation.farm_canonical_phones import (  # noqa: E402
    CANONICAL_FARM_PHONES,
    ban_serials_csv,
    canonical_expect_phones,
    canonical_names_sorted,
    is_banned_serial,
)
from automation.earn_plan import (  # noqa: E402
    applied_ads_allowed,
    applied_ads_per_phone,
    applied_halfway_share,
    applied_path3_farm_cap,
    applied_path3_per_hour,
    applied_paths,
    applied_visits_per_phone,
)
from automation.humanize import MIN_SCROLL_Y
from automation.phone_geo_time import apply_geo_window_to_serials
from automation.sequence_paths import discover_sequence_files
from automation.sequence_runner import Sequence, SequenceRunner
from automation.browser_apk_catalog import ensure_missing_farm_browsers_on_serials
from wizard.mumu_farm_ops import MuMuFarmOps
from wizard.wizard_paths import (
    bind_live_phone_entries,
    groups_config_path,
    is_nested_recordings_path,
    load_groups_list,
    logs_dir,
    phone_entry_steps,
    resolve_playlist_ref,
    sequences_dir,
)

logger = logging.getLogger("farm_354")

TARGET_PER_PHONE = 9999  # duration-limited by --hours
# Path2 halfway ratio (env PHARMFLOW_FARM_HALFWAY_RATIO). Default 0.20; raise for
# impression catch-up so phones don't sit in long Path1 completes.
try:
    HALFWAY_RATIO = max(
        0.0,
        min(1.0, float(os.environ.get("PHARMFLOW_FARM_HALFWAY_RATIO", "0.20") or "0.20")),
    )
except (TypeError, ValueError):
    HALFWAY_RATIO = 0.20


def _halfway_share() -> float:
    """Path 2 share. A saved earn plan wins so a dash save applies without restart."""
    planned = applied_halfway_share()
    if planned is not None:
        return planned
    return HALFWAY_RATIO


AUTHOR_W, AUTHOR_H = 900, 1600
TIMER_WAIT_MIN = 75.0
OMNIBOX_MAX_Y = 180
def _env_int(name: str, default: str) -> int:
    """Parse env as int; accept floats like '1.5' from the operator dash."""
    raw = os.environ.get(name, default) or default
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return int(float(default))


def _path3_per_hour(phone_idx: int = 0) -> int:
    # A saved earn plan is that phone's daily Path 3 count. Missing file keeps env.
    # Never floor to 8 (that kept Path3 permanently hot).
    planned = applied_path3_per_hour(phone_idx)
    if planned is not None:
        return planned
    return max(0, _env_int("PHARMFLOW_FARM_PATH3_PER_HOUR", "0"))


def _path3_fallback_daily_cap() -> int:
    """Daily Path3 volume implied by the configured per-hour rate.

    Used only when there is no earn plan and the operator never set
    ``PHARMFLOW_FARM_PATH3_DAILY_CAP`` -- the cap then simply tracks what the
    per-hour rate would produce over a day on the expected fleet, never an
    invented ceiling independent of real configuration.
    """
    per_hour = max(0, _env_int("PHARMFLOW_FARM_PATH3_PER_HOUR", "0"))
    phones = max(0, canonical_expect_phones())
    return per_hour * 24 * phones


def _path3_daily_cap_env_default() -> int:
    """``PHARMFLOW_FARM_PATH3_DAILY_CAP`` if the operator set it explicitly
    (including an explicit "0"), else :func:`_path3_fallback_daily_cap`.
    """
    raw = os.environ.get("PHARMFLOW_FARM_PATH3_DAILY_CAP")
    if raw is not None and raw.strip():
        return max(0, _env_int("PHARMFLOW_FARM_PATH3_DAILY_CAP", "0"))
    return _path3_fallback_daily_cap()


def _path3_farm_daily_cap() -> int:
    """Live Path3 ceiling.

    A saved earn plan sets the cap to path3-per-phone times the larger of the
    planned phone count and the live expect. More phones raise it. A missing
    plan falls back to :func:`_path3_daily_cap_env_default`, and a sticky
    override can still raise it.
    """
    planned = applied_path3_farm_cap(canonical_expect_phones())
    if planned is not None:
        return planned
    cap = _path3_daily_cap_env_default()
    try:
        log_dir = Path(
            os.environ.get("PHARMFLOW_LOGS")
            or os.environ.get("PHARMFLOW_LOG_DIR")
            or r"C:\PharmFlow\logs"
        )
        ov = log_dir / "farm_runtime_overrides.json"
        if ov.is_file():
            data = json.loads(ov.read_text(encoding="utf-8-sig"))
            sticky = int(float(str(data.get("PHARMFLOW_FARM_PATH3_DAILY_CAP") or 0)))
            if sticky > cap:
                cap = sticky
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return max(0, cap)


def _path3_global_gap_min() -> int:
    """Farm-wide minutes between Path3 starts. 0 = phones click in parallel.

    Unique-seq still refuses the same ad identity at once. A farm-wide gap
    serializes every phone onto one click pipeline and starves Path3.
    """
    return max(0, _env_int("PHARMFLOW_FARM_PATH3_GLOBAL_GAP_MIN", "0"))


def _path3_slot_spacing_min() -> int:
    return max(1, _env_int("PHARMFLOW_FARM_PATH3_SPACING", "2"))


# Evening fill: force N visits/phone/hour until local midnight on EVENING_UNTIL date,
# then normal daily caps (PHARMFLOW_FARM_DAILY_VISITS / _ADS) apply after midnight reset.
EVENING_SEQS_PER_HOUR = max(0, _env_int("PHARMFLOW_FARM_EVENING_SEQS_PER_HOUR", "0"))
EVENING_UNTIL = (os.environ.get("PHARMFLOW_FARM_EVENING_UNTIL") or "").strip()
# Farm-wide Path3 ceiling — re-read via _path3_farm_daily_cap() (sticky can change).
PATH3_DAILY_CAP = _path3_daily_cap_env_default()
PATH3_PER_HOUR = max(0, _env_int("PHARMFLOW_FARM_PATH3_PER_HOUR", "0"))
PATH3_GLOBAL_MIN_GAP_MIN = max(0, _env_int("PHARMFLOW_FARM_PATH3_GLOBAL_GAP_MIN", "0"))
# Never schedule Path3 in the past (restart / late-hour flood), and require a short lead.
PATH3_MIN_LEAD_MIN = _env_int("PHARMFLOW_FARM_PATH3_LEAD_MIN", "0")
# Skip a due slot that is already this many minutes stale (missed window).
PATH3_DUE_GRACE_MIN = _env_int("PHARMFLOW_FARM_PATH3_GRACE_MIN", "10")
# Hold (don't start Path1/2) when the next Path3 slot is this many minutes away.
# Typical complete seq is ~6–8 min; without this, a non-ad start one minute before
# a Path3 slot spans the window and the slot is marked missed after grace.
PATH3_PREEMPT_MIN = max(0, _env_int("PHARMFLOW_FARM_PATH3_PREEMPT_MIN", "2"))
# Minimum gap between Path3 slots on one phone (if >1).
PATH3_SLOT_SPACING_MIN = _env_int("PHARMFLOW_FARM_PATH3_SPACING", "8")
# Small per-phone lead so ads do not align; keep low so late hours still fit 4 slots.
PATH3_PHONE_OFFSET_MIN = _env_int("PHARMFLOW_FARM_PATH3_PHONE_OFFSET", "1")
PATH3_SLOT_LO = 0
PATH3_SLOT_HI = 56  # exclusive upper bound for sampling


def _parse_int_list(raw: str, *, default: list[int], n: int = 6) -> list[int]:
    """Parse comma-separated ints; pad to at least n phones (never drop phone 4/5)."""
    out: list[int] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(max(0, int(float(part))))
        except (TypeError, ValueError):
            continue
    if not out:
        out = list(default) if default else [0] * n
    # Pad to n (6-phone farm); do not truncate a longer operator CSV.
    target = max(int(n), len(out))
    while len(out) < target:
        out.append(out[-1] if out else 0)
    return out


# Per-phone daily budgets (phone0..phone5). Empty / 0 = unlimited for that index.
# Example: PHARMFLOW_FARM_DAILY_VISITS=400,400,400,400,400,400
DAILY_VISITS = _parse_int_list(
    os.environ.get("PHARMFLOW_FARM_DAILY_VISITS", ""),
    default=[0, 0, 0, 0, 0, 0],
    n=6,
)
DAILY_ADS = _parse_int_list(
    os.environ.get("PHARMFLOW_FARM_DAILY_ADS", ""),
    default=[0, 0, 0, 0, 0, 0],
    n=6,
)
_DAILY_BUDGET_ENABLED = any(v > 0 for v in DAILY_VISITS) or any(a > 0 for a in DAILY_ADS)

SEQS_PER_HOUR = max(1, _env_int("PHARMFLOW_FARM_SEQS_PER_HOUR", "15"))

# Exact mean spacing for the configured hourly budget. Per-slot jitter and a
# randomized per-phone phase prevent lockstep without front-loading the hour.
PHONE_SPACING_S = {
    i: float(os.environ.get(f"PHARMFLOW_FARM_SPACING_{i}", str(3600.0 / max(1, SEQS_PER_HOUR))) or "240")
    for i in range(6)
}
# Jitter around each scheduled slot (±seconds) — irregular, not identical gaps.
_slot_jitter = float(os.environ.get("PHARMFLOW_FARM_SLOT_JITTER", "55") or "55")
# Never launch a newly-created hourly slot immediately after a restart.
SLOT_MIN_LEAD_S = float(os.environ.get("PHARMFLOW_FARM_SLOT_MIN_LEAD", "45") or "45")
# Random farm-start window: every phone picks a random delay in [0, WINDOW],
# then delays are nudged so phones keep a random min gap (no lockstep, no fixed order).
START_STAGGER_WINDOW_S = float(
    os.environ.get(
        "PHARMFLOW_FARM_START_STAGGER_WINDOW",
        os.environ.get("PHARMFLOW_FARM_START_STAGGER_BAND", "240"),
    )
    or "240"
)
START_STAGGER_MIN_GAP_S = float(os.environ.get("PHARMFLOW_FARM_START_STAGGER_MIN_GAP", "25") or "25")
# Legacy aliases kept for dash overrides that still write BAND/JITTER.
START_STAGGER_BAND_S = START_STAGGER_WINDOW_S
START_STAGGER_JITTER_S = float(os.environ.get("PHARMFLOW_FARM_START_STAGGER_JITTER", "90") or "90")


def _random_phone_start_delays(n: int, rng: random.Random | None = None) -> list[float]:
    """Return n start delays (seconds): random order, random gaps, inside WINDOW."""
    rng = rng or random.Random(os.urandom(16))
    # Operator window is authoritative — no silent 30s floor (it defeated the
    # Advanced-panel override, e.g. window=18 still produced 23–29s delays).
    window = max(10.0, float(START_STAGGER_WINDOW_S))
    min_gap = max(5.0, min(float(START_STAGGER_MIN_GAP_S), window / max(2, n)))
    if n <= 0:
        return []
    if n == 1:
        return [rng.uniform(5.0, min(60.0, window))]
    # Sample + sort, then push apart so phones never start together.
    delays = sorted(rng.uniform(0.0, window) for _ in range(n))
    for i in range(1, n):
        if delays[i] - delays[i - 1] < min_gap:
            delays[i] = delays[i - 1] + min_gap + rng.uniform(0.0, min_gap * 0.5)
    # If we spilled past window, rebuild with a gap that provably fits so the
    # scale-down can never shrink a gap below the jitter tolerance.
    if delays[-1] > window:
        fit_gap = (window / max(1, n - 1)) * 0.92
        headroom = max(0.0, window - fit_gap * (n - 1))
        delays[0] = rng.uniform(0.0, headroom)
        for i in range(1, n):
            delays[i] = delays[i - 1] + fit_gap + rng.uniform(0.0, headroom * 0.3)
        # Final safety: scale into window if still over.
        if delays[-1] > window:
            scale = window / delays[-1]
            delays = [d * scale for d in delays]
    # Shuffle which phone gets which delay (breaks vm0-always-first).
    rng.shuffle(delays)
    return [max(0.0, float(d)) for d in delays]

# Legacy name only — never the source of truth. Farm adapts to live ADB phones.
PHONE_ORDER: tuple[str, ...] = ()


def _sticky_phone_preference() -> list[str]:
    """Optional ordering hint from sticky/env — never a hard membership filter."""
    raw = (os.environ.get("PHARMFLOW_FARM_PHONES") or "").strip()
    if not raw:
        log_dir = Path(
            os.environ.get("PHARMFLOW_LOGS")
            or os.environ.get("PHARMFLOW_LOG_DIR")
            or r"C:\PharmFlow\logs"
        )
        ov = log_dir / "farm_runtime_overrides.json"
        try:
            if ov.is_file():
                data = json.loads(ov.read_text(encoding="utf-8-sig"))
                raw = str(data.get("PHARMFLOW_FARM_PHONES") or "").strip()
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            raw = ""
    return [
        p.strip().lstrip("\ufeff")
        for p in raw.split(",")
        if p.strip().lstrip("\ufeff").startswith("vm")
    ]


def _banned_serials() -> set[str]:
    """Serials that must never join the money farm (ghost VMs, sideload blockers)."""
    banned: set[str] = set()
    for src in (
        os.environ.get("PHARMFLOW_FARM_BAN_SERIALS") or "",
    ):
        for part in str(src).split(","):
            s = part.strip()
            if s:
                banned.add(s)
    try:
        ov = logs_dir() / "farm_runtime_overrides.json"
        if ov.is_file():
            data = json.loads(ov.read_text(encoding="utf-8-sig"))
            raw = str(data.get("PHARMFLOW_FARM_BAN_SERIALS") or "")
            for part in raw.split(","):
                s = part.strip()
                if s:
                    banned.add(s)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return banned


def _is_tablet_instance(name: str, serial: str) -> bool:
    # Operator: every online phone is a money phone. Never treat vm4 as
    # non-farming tablet unless explicitly re-enabled via env.
    if (os.environ.get("PHARMFLOW_TABLET_FARM") or "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return False
    if is_tablet_phone(name) or (
        tablet_phone_name() and name.lower() == tablet_phone_name().lower()
    ):
        return True
    tab_ser = tablet_serial_override().strip()
    if tab_ser and serial and serial == tab_ser:
        return True
    return False


def _ensure_farm_inject(farm: object, online: list[tuple[str, int]]) -> None:
    """Bind absolute inject ports + pin guests; spawn detached keepalive.

    Standing rule: phones pinned to 8242+ with inject down = no bottom ads.
    Farm arms listeners in-process AND spawns a detached keepalive so ports
    survive farm thread death / lane restarts.
    """
    import subprocess as _sp

    from automation.browse_proxy import pin_guest_proxy
    from automation.mantis_inject_proxy import ensure_inject_for_phone, start_inject_proxies
    from automation.win_subprocess import hidden_run_kwargs

    idxs = sorted({int(idx) for _name, idx in online if int(idx) >= 0})
    if not idxs:
        return
    # Export the slot map BEFORE arming: Tor lanes are prewarmed for slots
    # 0..N-1 at the runtime HTTP base, so each phone's inject upstream must
    # dial base + (idx - min idx). Absolute dialing (39 -> 8157) killed the
    # whole fleet's upstream on 2026-09-13. The keepalive child inherits this
    # env too, so adopted lanes resolve identically.
    os.environ["PHARMFLOW_INJECT_SLOT_MAP"] = json.dumps(
        {str(i): pos for pos, i in enumerate(idxs)}, separators=(",", ":")
    )
    started = start_inject_proxies(idxs)
    logger.info("INJECT farm-owned listeners n=%s idxs=%s", len(started), idxs)
    adb_bin = None
    try:
        from automation.adb_paths import adb_executable

        adb_bin = adb_executable()
    except Exception:
        adb_bin = r"C:\PharmFlow\bundled\adb.exe"
    for name, idx in online:
        try:
            inst = farm.get_phone(name)  # type: ignore[attr-defined]
        except Exception:
            inst = None
        serial = getattr(inst, "adb_serial", None) if inst else None
        if not serial:
            continue
        want_port = 8218 + int(idx)
        try:
            ensure_inject_for_phone(farm.adb, serial, int(idx), install_ca=True)  # type: ignore[attr-defined]
            pinned = pin_guest_proxy(farm.adb, serial, int(idx), attempts=3)  # type: ignore[attr-defined]
            # Hard assert absolute port — roster-idx pins (8218+0..3) keep winning races.
            if adb_bin and Path(adb_bin).is_file():
                _sp.run(
                    [
                        adb_bin,
                        "-s",
                        str(serial),
                        "reverse",
                        f"tcp:{want_port}",
                        f"tcp:{want_port}",
                    ],
                    capture_output=True,
                    timeout=10,
                    **hidden_run_kwargs(),
                )
                _sp.run(
                    [
                        adb_bin,
                        "-s",
                        str(serial),
                        "shell",
                        "settings",
                        "put",
                        "global",
                        "http_proxy",
                        f"127.0.0.1:{want_port}",
                    ],
                    capture_output=True,
                    timeout=10,
                    **hidden_run_kwargs(),
                )
            logger.info("INJECT pin %s idx=%s -> %s (hard=%s)", name, idx, pinned, want_port)
        except Exception as exc:  # noqa: BLE001
            logger.warning("INJECT pin fail %s idx=%s: %s", name, idx, exc)
    # Detached keepalive — must outlive this farm process's parent trees.
    try:
        from automation.pharmflow_unison_dedupe import pids_for_script

        if not pids_for_script("pharmflow_inject_keepalive.py"):
            script = ROOT / "scripts" / "pharmflow_inject_keepalive.py"
            if script.is_file():
                pyw = sys.executable.replace("python.exe", "pythonw.exe")
                if not Path(pyw).is_file():
                    pyw = sys.executable
                flags = int(getattr(_sp, "CREATE_NO_WINDOW", 0) or 0)
                flags |= int(getattr(_sp, "DETACHED_PROCESS", 0x00000008) or 0)
                flags |= int(getattr(_sp, "CREATE_NEW_PROCESS_GROUP", 0x00000200) or 0)
                _sp.Popen(
                    [pyw, "-u", str(script)],
                    cwd=str(ROOT),
                    env={**os.environ, "PYTHONPATH": str(ROOT)},
                    stdout=_sp.DEVNULL,
                    stderr=_sp.DEVNULL,
                    creationflags=flags,
                    close_fds=True,
                )
                logger.info("INJECT spawned detached pharmflow_inject_keepalive")
    except Exception as exc:  # noqa: BLE001
        logger.warning("INJECT keepalive spawn soft-fail: %s", exc)

    def _inject_watchdog_loop() -> None:
        while not _stop_requested():
            time.sleep(25.0)
            try:
                import socket as _sock

                dead = []
                for i in idxs:
                    port = 8218 + int(i)
                    try:
                        c = _sock.create_connection(("127.0.0.1", port), 0.35)
                        c.close()
                    except OSError:
                        dead.append(port)
                if not dead:
                    continue
                logger.warning("INJECT listeners dead %s — re-arm in-process", dead)
                start_inject_proxies(idxs)
                for name, idx in online:
                    try:
                        inst = farm.get_phone(name)  # type: ignore[attr-defined]
                    except Exception:
                        continue
                    serial = getattr(inst, "adb_serial", None) if inst else None
                    if not serial:
                        continue
                    want_port = 8218 + int(idx)
                    try:
                        pin_guest_proxy(farm.adb, serial, int(idx), attempts=2)  # type: ignore[attr-defined]
                        if adb_bin and Path(adb_bin).is_file():
                            _sp.run(
                                [
                                    adb_bin,
                                    "-s",
                                    str(serial),
                                    "shell",
                                    "settings",
                                    "put",
                                    "global",
                                    "http_proxy",
                                    f"127.0.0.1:{want_port}",
                                ],
                                capture_output=True,
                                timeout=10,
                                **hidden_run_kwargs(),
                            )
                    except Exception:
                        pass
            except Exception as exc:  # noqa: BLE001
                logger.debug("INJECT watchdog soft-fail: %s", exc)

    if not getattr(_ensure_farm_inject, "_watch_started", False):
        _ensure_farm_inject._watch_started = True  # type: ignore[attr-defined]
        threading.Thread(
            target=_inject_watchdog_loop, name="farm-inject-watch", daemon=True
        ).start()


def _reap_orphan_tor() -> int:
    """Kill tor.exe instances whose parent chain is dead (prior farm restart).

    A crashed/restarted farm lane leaves its per-phone Tor fleet behind. Those
    orphans squat the canonical 8118+/9050+/10050+ port bases; the next lane
    shifts its own Tor to dead ports, and every sequence dies at isolation
    ("fetch_exit_ip failed ... actively refused") — zero ads, zero clicks. Reap
    orphans at startup so the canonical bases are reclaimed and the phone proxy
    pin is never dead. Never touches Tor owned by a live lane (its ancestor
    chain contains a live python). Returns how many were killed.
    """
    import subprocess  # noqa: PLC0415 — lazy like the rest of this module
    from automation.win_subprocess import hidden_run_kwargs as _hidden_subprocess_kwargs
    reaped = 0
    # One CIM snapshot: (pid -> (name, ppid)) for every process. Deterministic
    # and matches the stack's existing WMI process scans.
    table: dict[int, tuple[str, int]] = {}
    try:
        ps = (
            "Get-CimInstance Win32_Process | "
            "Select-Object ProcessId,ParentProcessId,Name | ConvertTo-Json -Compress"
        )
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=25,
            errors="replace",
            **_hidden_subprocess_kwargs(),
        ).stdout
        rows = json.loads(out or "[]")
        if isinstance(rows, dict):
            rows = [rows]
        for r in rows:
            try:
                pid = int(r.get("ProcessId") or 0)
                ppid = int(r.get("ParentProcessId") or 0)
                name = str(r.get("Name") or "")
            except (TypeError, ValueError):
                continue
            if pid:
                table[pid] = (name, ppid)
    except Exception as exc:  # noqa: BLE001
        logger.warning("TOR REAP scan failed: %s", exc)
        return 0
    tor_pids = [pid for pid, (name, _ppid) in table.items() if name.lower() == "tor.exe"]
    for pid in tor_pids:
        # Walk the ancestor chain; any live python owner means a farm lane owns it.
        seen: set[int] = set()
        owned = False
        cur_pid = pid
        while cur_pid and cur_pid not in seen:
            seen.add(cur_pid)
            entry = table.get(cur_pid)
            if entry is None:
                break  # parent chain broken = orphan
            name, ppid = entry
            if name.lower().startswith("python"):
                owned = True
                break
            cur_pid = ppid
        if owned:
            continue
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                timeout=8,
                errors="replace",
                **_hidden_subprocess_kwargs(),
            )
            logger.warning("TOR REAP: killed orphan tor pid=%s (parent chain dead)", pid)
            reaped += 1
        except Exception:  # noqa: BLE001
            pass
    if reaped:
        time.sleep(2.0)  # let the port bases release before Tor re-spawns
    return reaped


def _lock_boot_ready(farm: MuMuFarmOps) -> bool:
    """True when ADB_SERIAL_MAP.lock covers enough live MuMu ARM serials to skip connect_adb."""
    log_dir = Path(
        os.environ.get("PHARMFLOW_LOGS")
        or os.environ.get("PHARMFLOW_LOG_DIR")
        or r"C:\PharmFlow\logs"
    )
    lock_path = log_dir / "ADB_SERIAL_MAP.lock.json"
    if not lock_path.is_file():
        return False
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8-sig"))
        phones_map = dict(data.get("phones") or {})
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False
    if not phones_map:
        return False
    expect = 0
    try:
        ov = log_dir / "farm_runtime_overrides.json"
        if ov.is_file():
            raw_ov = json.loads(ov.read_text(encoding="utf-8-sig"))
            expect = int(str(raw_ov.get("PHARMFLOW_FARM_EXPECT_PHONES") or "0") or "0")
    except (OSError, json.JSONDecodeError, TypeError, ValueError, ValueError):
        expect = 0
    if expect <= 0:
        expect = len(phones_map)
    live = {
        d.serial
        for d in farm.adb.devices_detailed()
        if d.online and d.serial.startswith("10.0.2.")
    }
    banned = _banned_serials()
    matched = sum(
        1
        for _name, ser in phones_map.items()
        if str(ser or "").strip() in live and str(ser or "").strip() not in banned
    )
    return matched >= expect


def _running_shell_indexes() -> set[int]:
    """Indexes of MuMu VMs whose emulator shell is actually running.

    Keeps the discovery connect pass bounded: only live shells are probed,
    never the full configured VM list (40+ dead guests wedge on adb timeouts).
    """
    import re as _re
    import psutil

    out: set[int] = set()
    try:
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                name = str(proc.info.get("name") or "").lower()
                if "nemux-shell-winui" not in name:
                    continue
                cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or []))
                m = _re.search(r"--VmIndex (\d+)", cmd)
                if m:
                    out.add(int(m.group(1)))
            except (psutil.Error, TypeError, ValueError):
                continue
    except Exception:
        pass
    return out


def _discover_available_phones(
    farm: MuMuFarmOps,
    *,
    include_names: set[str] | None = None,
) -> list[str]:
    """Every MuMu VM that is ADB-online right now.

    Tablet is skipped unless it is explicitly in ``include_names`` (operator ALL6).
    """
    try:
        farm.refresh_serials()
    except Exception as exc:
        logger.debug("refresh_serials during discover: %s", exc)
    fast_boot = os.environ.get("PHARMFLOW_FAST_STICKY_BOOT", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    if not fast_boot or not _lock_boot_ready(farm):
        instances = list(farm.list_instances())
        # Zero live ADB devices (MuMu ARM guests, Studio AVD, docker, cloud all
        # absent) must not walk 40+ VMs doing per-phone adb connect timeouts —
        # that wedges the farm lane for minutes. Skip the connect pass and let
        # the standby scan below re-probe as devices appear.
        try:
            live_now = farm.enumerate_adb_devices()
            any_live = any(
                d.online
                and (d.serial.startswith("10.0.2.") or d.serial.startswith("127.0.0.1:"))
                for d in live_now
            )
        except Exception:
            any_live = True  # probe when the ADB bus is uncertain
        if any_live:
            # Devices are already on the ADB bus. Do NOT walk every configured
            # VM with adb connect — each dead guest costs a TCP timeout and the
            # full pass wedges the farm lane for minutes (observed: one live
            # phone + stale multi-phone lock froze discovery for 10+ min). Only
            # probe emulators whose shell process is actually running.
            running_idxs = _running_shell_indexes()
            for inst in instances:
                try:
                    idx = int(getattr(inst, "index", -1) or -1)
                except (TypeError, ValueError):
                    idx = -1
                if idx in running_idxs:
                    try:
                        farm.connect_adb(inst.name)
                    except Exception:
                        pass
            try:
                farm.list_instances()
            except Exception:
                pass
        else:
            logger.info("discover: zero live ADB devices — standby scan (connect pass skipped)")
    else:
        logger.info("discover fast sticky boot — skip connect_adb/mpid rescan")
    available: list[str] = []
    banned = _banned_serials()
    covered_serials: set[str] = set()
    for st in farm.get_all_phone_statuses():
        name = str(st.get("name") or "").strip()
        serial = str(st.get("adb_serial") or "").strip()
        if serial:
            covered_serials.add(serial)
        if not name or not st.get("connected"):
            continue
        if serial and serial in banned:
            logger.info("discover skip banned serial: %s %s", name, serial)
            continue
        if serial and serial.startswith("127.0.0.1:"):
            logger.info("discover skip localhost ghost: %s %s", name, serial)
            continue
        if _is_tablet_instance(name, serial):
            if include_names and name in include_names:
                logger.info("discover include tablet (sticky ALL6): %s", name)
            else:
                logger.info("discover skip tablet: %s serial=%s", name, serial or "?")
                continue
        available.append(name)
    # Roster-less: adopt EVERY live ADB device, including ones with no MuMu VM
    # folder — Android Studio AVDs, docker containers, cloud phones. Each is
    # registered under a synthetic name bound to its serial so the whole run
    # path (sessions, pacing, groups) treats it like any other phone.
    try:
        for dev in farm.enumerate_adb_devices():
            serial = str(getattr(dev, "serial", "") or "").strip()
            if not getattr(dev, "online", False) or not serial:
                continue
            if serial.startswith("127.0.0.1:"):
                continue
            if serial in covered_serials or serial in banned:
                continue
            sname = serial.replace(":", "-").replace(".", "-")
            name = f"adb-{sname}"
            try:
                farm.register_serial_phone(name, serial)
            except Exception as exc:
                logger.debug("register live device %s failed: %s", serial, exc)
                continue
            covered_serials.add(serial)
            available.append(name)
            logger.info("discover adopt live ADB device %s as %s", serial, name)
    except Exception as exc:
        logger.debug("live device adoption scan failed: %s", exc)
    # Operator model: the farm runs whatever is LIVE on ADB, always — MuMu,
    # Android Studio AVD, docker, cloud. A remembered/sticky phone list may
    # order discovery but must NEVER exclude a live phone (a stale list left
    # a live device idle for hours). No membership filtering.
    preferred_list = _sticky_phone_preference()
    if preferred_list:
        avail_set = set(available)
        ordered = [p for p in preferred_list if p in avail_set]
        ordered += [p for p in available if p not in set(preferred_list)]
        available = ordered
    return available


def _rewire_missing_phones(farm: MuMuFarmOps, missing: list[str]) -> list[str]:
    """Actively reconnect ADB to phones discovery missed, never just adapt away.

    A phone whose VM is running but dropped off the ADB bus (wedged 5037
    server, MuMu NAT re-addressing, ADB restart wiping reverse tunnels) shows
    as "offline" even though Android is up. Before the farm logs "adapted
    away" it must attempt a real rewire: reconnect every known serial (ARM
    state.json, lock map, instance serial) plus the MuMu ARM host-port
    endpoint. Returns the names that came back online.
    """
    reattached: list[str] = []
    if not missing:
        return reattached
    logger.info("REWIRE: attempting adb rewire for %d missing phone(s): %s", len(missing), ",".join(missing))
    for name in missing:
        try:
            inst = farm.get_phone(name) if hasattr(farm, "get_phone") else farm.instances.get(name)
        except Exception:
            inst = None
        if inst is None:
            continue
        idx = -1
        try:
            idx = int(getattr(inst, "index", -1) or -1)
        except (TypeError, ValueError):
            pass
        candidates: list[str] = []
        try:
            arm = farm._arm_adb_serial_from_state(name)
            if arm:
                candidates.append(arm)
        except Exception:
            pass
        if getattr(inst, "adb_serial", None):
            candidates.append(inst.adb_serial)
        if idx >= 0:
            candidates.append(f"127.0.0.1:{16384 + idx * 32}")
        seen: set[str] = set()
        for serial in candidates:
            if not serial or ":" not in serial or serial in seen:
                continue
            # Ghost dial protection: banned serials hang the shared adb server
            # for the full TCP timeout each — never dial them.
            if is_banned_serial(serial):
                continue
            seen.add(serial)
            try:
                r = farm.adb.run("connect", serial, timeout=6.0)
            except Exception as exc:
                logger.debug("rewire connect %s failed: %s", serial, exc)
                continue
            if r.ok or "already connected" in (r.stdout or "").lower():
                try:
                    up = farm.adb.wait_for_device(serial, timeout=3.0)
                except Exception:
                    up = False
                if up:
                    inst.adb_serial = serial
                    reattached.append(name)
                    logger.info("REWIRE: %s back online via %s", name, serial)
                    break
    return reattached


def _order_phones(available: list[str], preferred: list[str] | None = None) -> list[str]:
    """Order PharmFlow-online phones; preferred is sort hint only, never a cap."""
    avail_set = {p for p in available if p}
    preferred = [p for p in (preferred or []) if p]
    ordered: list[str] = []
    seen: set[str] = set()
    for p in preferred:
        if p in avail_set and p not in seen:
            ordered.append(p)
            seen.add(p)
    rest = sorted(avail_set, key=lambda n: (_idx_from_phone_name(n), n.lower()))
    for p in rest:
        if p not in seen:
            ordered.append(p)
            seen.add(p)
    return ordered


def _idx_from_phone_name(name: str) -> int:
    short = _phone_short(name)
    if short.lower().startswith("vm"):
        try:
            return int(short[2:].split(".", 1)[0])
        except ValueError:
            return 99
    return 99


def _persist_live_phones(phones: list[str], farm: MuMuFarmOps) -> None:
    """Record the phones that are ACTUALLY live into sticky/lock for dash/ops.

    Roster-less by design: what is persisted is exactly the fleet running right
    now, never a pinned canonical list that can go stale when VMs renumber.
    """
    live = [p for p in phones if p]
    # Only canonical vmN.gmadoa names belong in sticky config: synthetic
    # adb-10-0-2-x names leak here when instance mapping lags and then poison
    # every later boot (they cannot be mapped back to MuMu indexes/ports).
    sticky = [p for p in live if re.match(r"^vm\d+\.gmadoa$", p)]
    names = sticky  # never fall back to full canonical disk roster
    if not names:
        logger.warning("persist_live_phones: no vmN.gmadoa in live set — skip lock write")
        return
    expect = len(names)
    log_dir = Path(
        os.environ.get("PHARMFLOW_LOGS")
        or os.environ.get("PHARMFLOW_LOG_DIR")
        or r"C:\PharmFlow\logs"
    )
    # LIVE ONLY — empty canonical slots re-poison rewire/inject/watchers.
    serials: dict[str, str] = {}
    live_by_name = {p: p for p in live}
    seen: set[str] = set()
    for name in sorted(names, key=lambda n: int(re.match(r"vm(\d+)", n).group(1)) if re.match(r"vm(\d+)", n) else 0):
        inst = farm.get_phone(name) if hasattr(farm, "get_phone") else None
        ser = str(getattr(inst, "adb_serial", "") or "").strip()
        if ser and ":" in ser and not is_banned_serial(ser):
            if ser in seen:
                continue
            seen.add(ser)
            serials[name] = ser
        elif name in live_by_name and ser and not is_banned_serial(ser):
            if ser in seen:
                continue
            seen.add(ser)
            serials[name] = ser
    # Drop names that never resolved a live serial.
    names = [n for n in names if (serials.get(n) or "").strip()]
    if not names:
        logger.warning("persist_live_phones: zero resolved serials — skip lock write")
        return
    expect = len(names)
    now = datetime.now(timezone.utc).isoformat()
    ov_path = log_dir / "farm_runtime_overrides.json"
    try:
        data: dict[str, object] = {}
        if ov_path.is_file():
            raw = json.loads(ov_path.read_text(encoding="utf-8-sig"))
            if isinstance(raw, dict):
                data = raw
        data["PHARMFLOW_FARM_PHONES"] = ",".join(names)
        data["PHARMFLOW_FARM_PHONE_COUNT"] = str(expect)
        data["PHARMFLOW_FARM_EXPECT_PHONES"] = str(expect)
        data["PHARMFLOW_ADB_SERIALS"] = ",".join(
            serials[n] for n in names if (serials.get(n) or "").strip()
        )
        data["PHARMFLOW_FARM_BAN_SERIALS"] = ban_serials_csv()
        data["updated"] = now
        data["tick_verify_note"] = (
            f"live_only sticky live={len(live)} expect={expect}"
        )
        ov_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.environ["PHARMFLOW_FARM_PHONES"] = str(data["PHARMFLOW_FARM_PHONES"])
        os.environ["PHARMFLOW_ADB_SERIALS"] = str(data.get("PHARMFLOW_ADB_SERIALS") or "")
        os.environ["PHARMFLOW_FARM_EXPECT_PHONES"] = str(expect)
    except OSError as exc:
        logger.warning("persist sticky phones failed: %s", exc)
    try:
        def _inject_port(name: str) -> int:
            m = re.match(r"^vm(\d+)\.gmadoa$", name)
            return 8218 + int(m.group(1)) if m else 0

        lock = {
            "phones": {n: serials[n] for n in names},
            "tablet": {},
            "inject": {nm: _inject_port(nm) for nm in names},
            "locked_at": now,
            "note": f"live_fleet live={len(names)} expect={expect}",
            "updated": now,
        }
        tab = tablet_phone_name()
        tab_ser = tablet_serial_override()
        if tab and tab_ser:
            lock["tablet"] = {tab: tab_ser}
        (log_dir / "ADB_SERIAL_MAP.lock.json").write_text(
            json.dumps(lock, indent=2) + "\n", encoding="utf-8"
        )
        # Sticky lock must match live map — never restore ancient ghost IPs.
        (log_dir / "FARM_STICKY_7_PHONES.lock").write_text(
            json.dumps({"phones": dict(lock["phones"]), "updated": now}, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        logger.debug("persist serial lock failed: %s", exc)
    try:
        panel_path = log_dir / "farm_operator_panel.json"
        if panel_path.is_file():
            panel = json.loads(panel_path.read_text(encoding="utf-8-sig"))
            if isinstance(panel, dict):
                panel["phones"] = list(phones)
                panel["updated"] = now
                env = panel.get("env") if isinstance(panel.get("env"), dict) else {}
                env["PHARMFLOW_FARM_PHONES"] = ",".join(phones)
                env["PHARMFLOW_FARM_PHONE_COUNT"] = str(len(phones))
                env["PHARMFLOW_FARM_EXPECT_PHONES"] = str(len(phones))
                if serials:
                    env["PHARMFLOW_ADB_SERIALS"] = ",".join(
                        serials[p] for p in phones if serials.get(p)
                    )
                panel["env"] = env
                panel_path.write_text(json.dumps(panel, indent=2) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.debug("persist panel phones failed: %s", exc)


# Legacy defaults — live farm uses automation.display_resolution pool instead.
TARGET_WM = "900x1600"
TARGET_DENSITY = 320
WM_RETRY_ATTEMPTS = 3
REPEAT_FAIL_THRESHOLD = 3
RESULTS_TAIL_BYTES = 2_000_000
FAIL_REVIEWS_TAIL_BYTES = 1_000_000
# Runtime-only failures — re-validate JSON but do not quarantine on these alone.
_RUNTIME_FAIL_MARKERS = (
    "bad resolution",
    "start perfect dab",
    "open_url",
    "disconnect",
    "adb",
    "device",
    "serial",
    "fre",
    "age gate",
    "splash",
)

def _farm_paths() -> set[str]:
    planned = applied_paths()
    if planned:
        return planned
    raw = os.environ.get("PHARMFLOW_FARM_PATHS", "1,2").strip().lower()
    if raw in ("all", "*"):
        return {"1", "2", "3"}
    return {p.strip() for p in raw.split(",") if p.strip()}


def _ads_allowed() -> bool:
    planned = applied_ads_allowed()
    if planned is not None:
        return planned
    return os.environ.get("PHARMFLOW_FARM_ALLOW_ADS", "0").strip().lower() in ("1", "true", "yes")


def _visible_ads_required() -> bool:
    return os.environ.get("PHARMFLOW_REQUIRE_VISIBLE_ADS", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _path3_daily_state_path() -> Path:
    return logs_dir() / "farm_path3_daily_state.json"


def _load_path3_daily_state() -> dict[str, object]:
    today = datetime.now().astimezone().date().isoformat()
    path = _path3_daily_state_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        raw = {}
    if str(raw.get("date") or "") != today:
        return {"date": today, "count": 0, "last_at": 0.0}
    return {
        "date": today,
        "count": max(0, int(raw.get("count") or 0)),
        "last_at": max(0.0, float(raw.get("last_at") or 0.0)),
    }


def _path3_available_today(*, now: float | None = None) -> bool:
    cap = _path3_farm_daily_cap()
    if cap <= 0:
        return False
    state = _load_path3_daily_state()
    if int(state["count"]) >= cap:
        return False
    current = time.time() if now is None else float(now)
    last_at = float(state["last_at"])
    gap_s = _path3_global_gap_min() * 60.0
    return not last_at or current - last_at >= gap_s


def _reserve_path3_today(*, now: float | None = None) -> dict[str, object] | None:
    """Atomically called under the farm worker lock before a Path3 run."""
    current = time.time() if now is None else float(now)
    if not _path3_available_today(now=current):
        return None
    state = _load_path3_daily_state()
    state["count"] = int(state["count"]) + 1
    state["last_at"] = current
    path = _path3_daily_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def _unreserve_path3_today() -> None:
    """Roll back a Path3 reserve on FAIL or non-billable OK — keep daily ad math honest."""
    state = _load_path3_daily_state()
    state["count"] = max(0, int(state["count"]) - 1)
    # Keep last_at so the global gap still spaces retries (don't spam Path3).
    path = _path3_daily_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _path3_forced_click_ok(report: dict | None) -> bool | None:
    """True if forced Path3 click_url open billed; False if it failed; None if no forced open.

    SequenceRunner sets ``ad_fallback_forced`` + ``ad_fallback`` on Path3 ad taps.
    House/bot-only SSP returns False (open refused) while the sequence can still OK.
    """
    if not isinstance(report, dict):
        return None
    saw_forced = False
    any_ok = False
    for step in report.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if step.get("ad_fallback_forced"):
            saw_forced = True
            if step.get("ad_fallback"):
                any_ok = True
    if not saw_forced:
        return None
    return any_ok


# How many times to re-run a failed slot before giving up and moving on.
# Failures do NOT count toward daily visit/ad budgets — only OK does.
FAIL_RETRY_MAX = max(1, _env_int("PHARMFLOW_FARM_FAIL_RETRY", "2"))


def _daily_budget_path() -> Path:
    return logs_dir() / "farm_daily_budget_state.json"


def _empty_phone_budget() -> dict[str, int]:
    return {"visits": 0, "ads": 0}


def _load_daily_budget() -> dict[str, object]:
    today = datetime.now().astimezone().date().isoformat()
    path = _daily_budget_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        raw = {}
    # No fleet size is assumed here. Rows are created on demand by
    # _record_phone_visit and a missing row reads as empty (_phone_budget_row),
    # so a new day starts with no rows and a phone of ANY index gets one the
    # moment it records a visit. (Pre-seeding a fixed eight-row roster, with a
    # floor of six, was a fixed-fleet-size literal; the other readers of this
    # file -- the operator dash and autopilot -- already treat an empty map as
    # "nothing used yet".)
    if str(raw.get("date") or "") != today:
        return {"date": today, "phones": {}}
    phones_raw = raw.get("phones") if isinstance(raw.get("phones"), dict) else {}
    phones: dict[str, dict[str, int]] = {}
    # Preserve every phone index on disk, whatever it is (8+ phone farms used to
    # lose idx>=6 every load, resetting visit/ad counters mid-day).
    for key, row in phones_raw.items():
        try:
            idx_key = str(int(str(key)))
        except (TypeError, ValueError):
            continue
        if not isinstance(row, dict):
            phones[idx_key] = _empty_phone_budget()
        else:
            phones[idx_key] = {
                "visits": max(0, int(row.get("visits") or 0)),
                "ads": max(0, int(row.get("ads") or 0)),
            }
    return {"date": today, "phones": phones}


def _save_daily_budget(state: dict[str, object]) -> None:
    path = _daily_budget_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _phone_budget_row(state: dict[str, object], phone_idx: int) -> dict[str, int]:
    phones = state.get("phones")
    if not isinstance(phones, dict):
        return _empty_phone_budget()
    row = phones.get(str(phone_idx))
    if not isinstance(row, dict):
        return _empty_phone_budget()
    return {
        "visits": max(0, int(row.get("visits") or 0)),
        "ads": max(0, int(row.get("ads") or 0)),
    }


def _phone_visits_cap(phone_idx: int) -> int:
    # A saved earn plan uses a random per-phone list. Extra live phones draw
    # around the mean. It does not replay a short CSV that would shrink a fleet.
    planned = applied_visits_per_phone(phone_idx)
    if planned is not None:
        return planned if phone_idx >= 0 else 0
    # Re-read env so midnight day-plan / panel bumps take effect without stale import caps.
    visits = _parse_int_list(
        os.environ.get("PHARMFLOW_FARM_DAILY_VISITS", ""),
        default=list(DAILY_VISITS) if DAILY_VISITS else [0] * 6,
        n=max(6, phone_idx + 1, len(DAILY_VISITS)),
    )
    if phone_idx < 0:
        return 0
    if phone_idx >= len(visits):
        return int(visits[-1]) if visits else 0
    return int(visits[phone_idx])


def _phone_ads_cap(phone_idx: int) -> int:
    planned = applied_ads_per_phone(phone_idx)
    if planned is not None:
        return planned if phone_idx >= 0 else 0
    ads = _parse_int_list(
        os.environ.get("PHARMFLOW_FARM_DAILY_ADS", ""),
        default=list(DAILY_ADS) if DAILY_ADS else [0] * 6,
        n=max(6, phone_idx + 1, len(DAILY_ADS)),
    )
    if phone_idx < 0:
        return 0
    if phone_idx >= len(ads):
        return int(ads[-1]) if ads else 0
    return int(ads[phone_idx])


def _active_day_end(now: datetime | None = None) -> datetime:
    """End of today's active pacing window (geo end, or local midnight)."""
    now = now or datetime.now().astimezone()
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        from datetime import time as dtime

        from automation.phone_geo_time import parse_window

        _ws, we = parse_window()
        if we == dtime(0, 0):
            return midnight
        end = now.replace(hour=we.hour, minute=we.minute, second=0, microsecond=0)
        if end <= now:
            return midnight
        return end
    except Exception:
        return midnight


def _hours_left_until_midnight() -> float:
    return max(0.15, _secs_until_local_midnight() / 3600.0)


def _evening_fill_active() -> bool:
    """True while forced evening rate applies (expires at next local midnight)."""
    if EVENING_SEQS_PER_HOUR <= 0:
        return False
    today = datetime.now().astimezone().date().isoformat()
    until = EVENING_UNTIL or today
    return today <= until


def _hours_left_today() -> float:
    now = datetime.now().astimezone()
    # Evening fill runs through true local midnight (not geo window end).
    if _evening_fill_active():
        return _hours_left_until_midnight()
    return max(0.35, (_active_day_end(now) - now).total_seconds() / 3600.0)


def _stochastic_hour_quota(
    remaining: int,
    hours_left: float,
    rng: random.Random | None = None,
) -> int:
    """Scatter remaining daily quota across hours left (no fixed seqs/hour lock)."""
    if remaining <= 0:
        return 0
    r = rng or random.SystemRandom()
    hours = max(0.35, float(hours_left))
    ideal = remaining / hours
    base = int(math.floor(ideal))
    frac = ideal - base
    n = base + (1 if r.random() < frac else 0)
    if n <= 0:
        # Sparse remainder: still sometimes place one slot this hour.
        n = 1 if r.random() < min(0.95, max(0.18, ideal)) else 0
    # Light wobble so consecutive hours don't look cloned.
    if n >= 2 and r.random() < 0.4:
        n += r.choice((-1, 1))
    soft_cap = max(1, int(math.ceil(ideal * 1.45)) + 1)
    return max(0, min(remaining, soft_cap, n))


def _phone_seqs_this_hour(phone_idx: int, rng: random.Random | None = None) -> int:
    """Visit slots this hour = remaining daily visits / hours left (scattered)."""
    if _evening_fill_active():
        return max(1, EVENING_SEQS_PER_HOUR)
    cap = _phone_visits_cap(phone_idx)
    if cap <= 0:
        # Legacy mode only when no daily visit cap is configured.
        return max(1, SEQS_PER_HOUR)
    remaining = _phone_visits_remaining(phone_idx)
    if remaining <= 0:
        return 0
    return _stochastic_hour_quota(remaining, _hours_left_today(), rng)


def _phone_path3_this_hour(phone_idx: int, rng: random.Random | None = None) -> int:
    """Path3 slots this hour from remaining ads + operator per-hour CAP.

    Cap is PHARMFLOW_FARM_PATH3_PER_HOUR (0 = no Path3). Never invent a floor
    above the operator value — that kept Path3 on constantly.
    """
    if not _ads_allowed():
        return 0
    if "3" not in _farm_paths():
        return 0
    ads_left = _phone_ads_remaining(phone_idx)
    if ads_left <= 0:
        return 0
    cap = _path3_per_hour(phone_idx)
    if cap <= 0:
        return 0
    if not _DAILY_BUDGET_ENABLED or _phone_ads_cap(phone_idx) <= 0:
        return min(ads_left, cap)
    n = _stochastic_hour_quota(ads_left, _hours_left_today(), rng)
    return min(ads_left, cap, max(0, n))


def _phone_ads_remaining(phone_idx: int) -> int:
    cap = _phone_ads_cap(phone_idx)
    if cap <= 0:
        # No per-phone ad cap configured → allow (farm-wide guard still applies).
        return 999 if not _DAILY_BUDGET_ENABLED else 0
    state = _load_daily_budget()
    used = _phone_budget_row(state, phone_idx)["ads"]
    return max(0, cap - used)


def _phone_visits_remaining(phone_idx: int) -> int:
    cap = _phone_visits_cap(phone_idx)
    if cap <= 0:
        return 9999
    state = _load_daily_budget()
    used = _phone_budget_row(state, phone_idx)["visits"]
    return max(0, cap - used)


def _record_phone_visit(phone_idx: int, *, path3: bool) -> dict[str, int]:
    state = _load_daily_budget()
    phones = state.setdefault("phones", {})
    if not isinstance(phones, dict):
        phones = {}
        state["phones"] = phones
    key = str(phone_idx)
    row = phones.get(key) if isinstance(phones.get(key), dict) else _empty_phone_budget()
    row = {
        "visits": int(row.get("visits") or 0) + 1,
        "ads": int(row.get("ads") or 0) + (1 if path3 else 0),
    }
    phones[key] = row
    _save_daily_budget(state)
    return row


def _secs_until_local_midnight() -> float:
    now = datetime.now().astimezone()
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(30.0, (midnight - now).total_seconds())


def _stop_requested() -> bool:
    """True when env, sticky overrides, or pause/kill-switch ask the farm to stop.

    Dash/kill-switch write PHARMFLOW_FARM_STOP into farm_runtime_overrides.json and
    engage farm_halted(); the worker process env is not rewritten mid-run, so
    env-only checks left sequences running after soft stop.
    """
    if os.environ.get("PHARMFLOW_FARM_STOP", "0").strip().lower() in ("1", "true", "yes", "on"):
        return True
    try:
        if farm_halted():
            return True
    except Exception:
        pass
    try:
        log_dir = Path(
            os.environ.get("PHARMFLOW_LOGS")
            or os.environ.get("PHARMFLOW_LOG_DIR")
            or r"C:\PharmFlow\logs"
        )
        ov_path = log_dir / "farm_runtime_overrides.json"
        if ov_path.is_file():
            ov = json.loads(ov_path.read_text(encoding="utf-8-sig"))
            if isinstance(ov, dict) and str(ov.get("PHARMFLOW_FARM_STOP") or "").strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            ):
                return True
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return False


_BROWSER_STEM_TAGS = ("chromium", "firefox", "brave", "duckduckgo", "opera")


def _pool_stem(stem: str) -> str:
    """Stem with a trailing browser tag folded off before suffix classification.

    Path1/2 sequences are named ..._p1a_<browser>_complete, but a generator that
    appends the tag last (..._complete_<browser>) would silently empty the Path1/2
    pools — the farm then only runs ads. Tolerate both orderings.
    """
    for tag in _BROWSER_STEM_TAGS:
        if stem.endswith(f"_{tag}"):
            return stem[: -(len(tag) + 1)]
    return stem


def _stem_browser_tag(raw_stem: str) -> str | None:
    low = raw_stem.lower()
    for tag in _BROWSER_STEM_TAGS:
        if (
            f"_{tag}_" in low
            or low.endswith(f"_{tag}")
            or low.endswith(f"_{tag}_complete")
            or low.endswith(f"_{tag}_halfway")
        ):
            return tag
    return None


def _allowed_browser_tags() -> set[str] | None:
    """Optional PHARMFLOW_FARM_BROWSERS=chromium,brave,... Restrict Path1/2 stems.

    None = all browsers. Used for overnight click-leak lockdown / profit locks.
    PHARMFLOW_FARM_CHROMIUM_ONLY=1 always locks to chromium even if BROWSERS unset.
    """
    chromium_only = (
        os.environ.get("PHARMFLOW_FARM_CHROMIUM_ONLY") or ""
    ).strip().lower() in ("1", "true", "yes", "on")
    if chromium_only:
        return {"chromium"}
    raw = (os.environ.get("PHARMFLOW_FARM_BROWSERS") or "").strip().lower()
    if not raw:
        return None
    tags = {p.strip() for p in raw.split(",") if p.strip()}
    return tags or None


def _stem_allowed(raw_stem: str) -> bool:
    """Restrict which blueprint paths the farm may schedule."""
    browser_tag = _stem_browser_tag(raw_stem)
    stem = _pool_stem(raw_stem)
    paths = _farm_paths()
    is_ad = stem.endswith("_ad_multi") or stem.endswith("_ad")
    allowed = _allowed_browser_tags()
    if allowed is not None and not is_ad:
        # Untagged stems treated as chromium; tagged stems must be in allow-list.
        tag = browser_tag or "chromium"
        if tag not in allowed:
            return False
    # Path 2 halfway
    if stem.endswith("_timer_halfway") or stem.endswith("_halfway"):
        return "2" in paths
    # Path 1 completes (p1a/p1b/p1c/p1d) and legacy *_timer_complete
    if stem.endswith("_complete"):
        if "_p1" in stem or stem.endswith("_timer_complete"):
            return "1" in paths
        # Path 3 non-ad completes if any appear later
        return "3" in paths
    # Ads — Path 3 only, and only when ads explicitly allowed
    if is_ad:
        return "3" in paths and _ads_allowed()
    if stem.endswith("_browse"):
        return "3" in paths
    return False


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _classify(paths: list[Path]) -> dict[str, list[Path]]:
    ad, complete, halfway = [], [], []
    for p in paths:
        if "smoke" in p.parts:
            continue
        # Pass raw stem so browser tags (..._brave_complete) are visible to filter.
        if not _stem_allowed(p.stem):
            continue
        stem = _pool_stem(p.stem)
        if stem.endswith("_ad_multi") or stem.endswith("_ad"):
            ad.append(p)
        elif stem.endswith("_halfway"):
            halfway.append(p)
        elif stem.endswith("_complete") or stem.endswith("_browse"):
            complete.append(p)
    if not _ads_allowed():
        ad = []
    return {"ad": ad, "complete": complete, "halfway": halfway}


def _coord_base(val: object) -> int | None:
    if isinstance(val, dict) and "base" in val:
        return int(val["base"])
    if isinstance(val, (int, float)):
        return int(val)
    return None


def _is_generic_site_data(data: dict) -> bool:
    return bool(data.get("site_slug")) and str(data.get("site_adapter") or "generic") != "dabflow"


def _is_generic_site_path(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and _is_generic_site_data(data)


def _sequence_root() -> Path:
    configured = os.environ.get("PHARMFLOW_FARM_SEQUENCE_ROOT", "").strip()
    if configured:
        path = Path(configured)
        if not is_nested_recordings_path(path):
            return path
        logger.warning("ignoring nested sequence root %s", path)
    return sequences_dir()


def _playlist_files_for_serials(live_serials: list[str]) -> tuple[list[Path], list[str]]:
    """Bind each live ADB serial to its groups playlist. Never invent phones.

    Empty serials are skipped. If ADB has no serials, return no files — boot
    stays blocked on HNS rather than a fabricated roster.
    """
    cfg, groups = load_groups_list(groups_config_path())
    if not live_serials:
        return [], [
            f"ADB empty — not inventing phones; groups={cfg} boot blocked on HNS"
        ]
    def _accepts(path: Path) -> bool:
        return _preflight(path, strict=True) is None

    bound = bind_live_phone_entries(groups, live_serials)
    files: list[Path] = []
    seen: set[str] = set()
    notes: list[str] = [f"groups={cfg} live={len(live_serials)} bound={len(bound)}"]
    for serial, ent, source in bound:
        refs: list[str] = []
        for field in ("sequence_playlist", "sequence_playlist_secondary"):
            raw = ent.get(field)
            if isinstance(raw, list):
                refs.extend(str(item).strip() for item in raw if str(item).strip())
        resolved: list[str] = []
        misses: list[str] = []
        for ref in refs:
            path = resolve_playlist_ref(ref, accept=_accepts)
            if path is None:
                misses.append(ref)
                continue
            resolved.append(path.name)
            token = str(path.resolve()).lower()
            if token not in seen:
                seen.add(token)
                files.append(path)
        via = f" via {source}" if source != serial else ""
        if not resolved:
            why = "no v3 file passed preflight"
            if misses:
                why = f"{why} ({'; '.join(misses)})"
            notes.append(f"{serial}{via} FAIL {why}")
            continue
        notes.append(
            f"{serial}{via} steps={len(phone_entry_steps(ent, serial))} "
            f"playlist={len(refs)} v3={len(resolved)} {', '.join(resolved)}"
        )
    return files, notes


def _used_stems_path() -> Path:
    """Persist the draw-without-replacement ledger for non-ad sequences.

    Scoped per sequence root so different site profiles keep separate passes.
    """
    slug = os.environ.get("PHARMFLOW_SITE_SLUG", "dabflow").strip() or "dabflow"
    return logs_dir() / f"farm_used_stems_{slug}.json"


def _load_used_stems() -> set[str]:
    """Non-ad stems already run in the current pass (survives restarts)."""
    path = _used_stems_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if isinstance(data, dict):
        used = data.get("used")
    else:
        used = data
    if isinstance(used, list):
        return {str(s) for s in used}
    return set()


def _save_used_stems(used_stems: set[str]) -> None:
    path = _used_stems_path()
    try:
        path.write_text(
            json.dumps({"updated": _utc(), "used": sorted(used_stems)}, indent=0),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.debug("used-stems save failed: %s", exc)


def _coord_in_bounds(x: int | None, y: int | None) -> str | None:
    if x is not None and not (0 <= x <= AUTHOR_W):
        return f"x={x} out of 0..{AUTHOR_W}"
    if y is not None and not (0 <= y <= AUTHOR_H):
        return f"y={y} out of 0..{AUTHOR_H}"
    return None


def _wm_size_ok(size: str) -> bool:
    """Accept any portrait pool profile (Override wm size), not browser viewport."""
    got = _parse_wm_size(size or "")
    return bool(got) and is_portrait_size(got) and is_known_size(got)


def _sticky_adb_serial_for_phone(phone: str) -> str:
    """Prefer operator-locked 10.0.2.x serials over stale MuMu 127.0.0.1:16xxx."""
    canonical = str(CANONICAL_FARM_PHONES.get(phone) or "").strip()
    log_dir = Path(
        os.environ.get("PHARMFLOW_LOGS")
        or os.environ.get("PHARMFLOW_LOG_DIR")
        or r"C:\PharmFlow\logs"
    )
    lock_path = log_dir / "ADB_SERIAL_MAP.lock.json"
    try:
        if lock_path.is_file():
            data = json.loads(lock_path.read_text(encoding="utf-8-sig"))
            ser = str(
                (data.get("phones") or {}).get(phone)
                or (data.get("tablet") or {}).get(phone)
                or ""
            ).strip()
            if ser.startswith("10.0.2.") and not is_banned_serial(ser):
                return ser
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    if canonical and not is_banned_serial(canonical):
        return canonical
    return ""


def _adb_reconnect(farm: MuMuFarmOps, serial: str, phone: str) -> str:
    """Best-effort reattach a dropped MuMu ADB endpoint; return usable serial."""
    serial = (serial or "").strip()
    try:
        farm.refresh_serials()
    except Exception as exc:
        logger.debug("[%s] refresh_serials during reconnect: %s", phone, exc)
    sticky = _sticky_adb_serial_for_phone(phone)
    inst = farm.get_phone(phone) if hasattr(farm, "get_phone") else None
    if inst and getattr(inst, "adb_serial", None):
        serial = str(inst.adb_serial).strip() or serial
    if sticky and (not serial or serial.startswith("127.0.0.1:")):
        serial = sticky
        if inst is not None:
            inst.adb_serial = sticky
            if inst.config is not None:
                inst.config.adb_serial = sticky
    if not serial:
        return serial
    try:
        farm.adb.run("connect", serial, timeout=12.0)
    except Exception as exc:
        logger.warning("[%s] adb connect %s soft-fail: %s", phone, serial, exc)
    try:
        farm.adb.wait_for_device(serial, timeout=12.0)
    except Exception:
        pass
    return serial


def _ensure_wm_size(farm: MuMuFarmOps, serial: str, phone: str) -> tuple[bool, str]:
    """Ensure portrait device wm size (pool); never homogenize or use browser viewport."""
    last = ""
    serial = (serial or "").strip()
    for attempt in range(1, WM_RETRY_ATTEMPTS + 2):
        try:
            if attempt > 1 or not serial:
                serial = _adb_reconnect(farm, serial, phone)
            if not serial:
                last = "no adb serial"
                time.sleep(0.8 * attempt)
                continue
            # Landscape fix bypasses DISPLAY_LOCK; then heal collisions / unknown sizes.
            ok_portrait, portrait_size = ensure_portrait_display(
                farm.adb, serial, phone=phone
            )
            if not ok_portrait:
                last = portrait_size or "portrait fix failed"
                logger.warning(
                    "[%s] portrait wm fix attempt %d: %s",
                    phone,
                    attempt,
                    last,
                )
            ok, got = ensure_unique_display(
                farm.adb, serial, phone=phone, scramble=False
            )
            last = (farm.adb.shell("wm size", serial=serial, timeout=8.0).stdout or "").strip()
            if ok and _wm_size_ok(last):
                if attempt > 1:
                    logger.info("[%s] wm size recovered on attempt %d: %s", phone, attempt, last)
                return True, last or got
            logger.warning(
                "[%s] wm size attempt %d/%d bad: %r — reconnecting",
                phone,
                attempt,
                WM_RETRY_ATTEMPTS + 1,
                last,
            )
            _adb_reconnect(farm, serial, phone)
        except Exception as exc:
            last = str(exc)
            logger.warning(
                "[%s] wm size attempt %d/%d error: %s — reconnecting",
                phone,
                attempt,
                WM_RETRY_ATTEMPTS + 1,
                exc,
            )
            _adb_reconnect(farm, serial, phone)
        time.sleep(0.8 * attempt)
    return False, last


def _live_quarantine_stems() -> set[str]:
    """Hot quarantine written by farm_fail_review — skipped on every _pick."""
    path = logs_dir() / "farm_seq_quarantine.json"
    if not path.is_file():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return set()
    stems = raw.get("stems") if isinstance(raw, dict) else None
    if isinstance(stems, dict):
        return {str(k) for k in stems.keys() if str(k).strip()}
    if isinstance(stems, list):
        return {str(s) for s in stems if str(s).strip()}
    return set()


def _load_repeat_fail_stems() -> dict[str, int]:
    """Count recent FAIL rows per sequence stem (for extra preflight scrutiny)."""
    counts: dict[str, int] = {}
    results_path = logs_dir() / "farm_354_results.jsonl"
    if not results_path.exists():
        return counts
    try:
        data = results_path.read_bytes()
        if len(data) > RESULTS_TAIL_BYTES:
            data = data[-RESULTS_TAIL_BYTES:]
        for line in data.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("success"):
                continue
            stem = str(row.get("sequence") or row.get("stem") or "").strip()
            if stem:
                counts[stem] = counts.get(stem, 0) + 1
    except OSError:
        pass
    return counts


def _load_quarantine_stems(pools: dict[str, list[Path]]) -> set[str]:
    """Quarantine stems that fail structural preflight or repeat JSON-class failures."""
    quarantined: set[str] = set()
    repeat = _load_repeat_fail_stems()
    all_paths: dict[str, Path] = {}
    for paths in pools.values():
        for path in paths:
            all_paths[path.stem] = path

    for stem, fail_n in repeat.items():
        if fail_n < REPEAT_FAIL_THRESHOLD:
            continue
        path = all_paths.get(stem)
        if path is None:
            continue
        err = _preflight(path, strict=True)
        if err:
            quarantined.add(stem)
            logger.warning(
                "quarantine %s (fails=%d): preflight %s",
                stem,
                fail_n,
                err,
            )
            continue
        # Re-check recent error text — only quarantine if failures look JSON/structural.
        jsonish = 0
        results_path = logs_dir() / "farm_354_results.jsonl"
        if results_path.exists():
            try:
                data = results_path.read_bytes()
                if len(data) > RESULTS_TAIL_BYTES:
                    data = data[-RESULTS_TAIL_BYTES:]
                for line in data.decode("utf-8", errors="replace").splitlines():
                    try:
                        row = json.loads(line.strip())
                    except json.JSONDecodeError:
                        continue
                    if row.get("success"):
                        continue
                    if str(row.get("sequence") or row.get("stem") or "") != stem:
                        continue
                    err_txt = str(row.get("error") or "").lower()
                    if any(m in err_txt for m in _RUNTIME_FAIL_MARKERS):
                        continue
                    jsonish += 1
            except OSError:
                pass
        if jsonish >= REPEAT_FAIL_THRESHOLD:
            quarantined.add(stem)
            logger.warning(
                "quarantine %s (fails=%d, jsonish=%d) — repeated non-runtime errors",
                stem,
                fail_n,
                jsonish,
            )
    return quarantined


def _preflight(path: Path, *, strict: bool = False) -> str | None:
    """Reject broken / dangerous sequences before run."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"unreadable: {exc}"
    if int(data.get("sequence_version") or 0) < REQUIRED_SEQUENCE_VERSION:
        return "bad sequence_version"
    aw = int(data.get("author_width") or data.get("base_w") or 0)
    ah = int(data.get("author_height") or data.get("base_h") or 0)
    if aw == AUTHOR_H and ah == AUTHOR_W:
        return f"landscape author size {aw}x{ah} (need {AUTHOR_W}x{AUTHOR_H})"
    if aw and ah and (aw != AUTHOR_W or ah != AUTHOR_H):
        return f"bad author size {aw}x{ah} (need {AUTHOR_W}x{AUTHOR_H})"
    steps = data.get("steps") or []
    if not steps:
        return "no steps"
    descs = " | ".join(str(s.get("description") or "") for s in steps)
    generic_site = _is_generic_site_data(data)
    if generic_site:
        actions = {str(s.get("action") or "") for s in steps if isinstance(s, dict)}
        if not ({"open_url", "launch_app"} & actions):
            return "generic site sequence missing open_url/launch_app"
    elif "Age gate" not in descs:
        return "missing age gate"
    stem = _pool_stem(path.stem)
    is_full = (
        stem.endswith("_complete")
        or stem.endswith("_ad")
        or stem.endswith("_ad_multi")
        or stem.endswith("_browse")
    )
    is_halfway = stem.endswith("_halfway")
    if (is_full or is_halfway) and not generic_site:
        if "Start Perfect Dab" not in descs:
            return "missing Start Perfect Dab timer tap"
    if is_full and not generic_site:
        if "Wait for timer" not in descs and "heat + cool" not in descs.lower():
            return "missing full timer wait"
        for s in steps:
            if s.get("action") != "wait":
                continue
            d = str(s.get("description") or "")
            if "Wait for timer" not in d and "heat + cool" not in d.lower():
                continue
            sec = (s.get("params") or {}).get("seconds") or {}
            mn = float(sec.get("min") or 0) if isinstance(sec, dict) else float(sec or 0)
            if mn < TIMER_WAIT_MIN:
                return f"timer wait too short ({mn}s, need >={TIMER_WAIT_MIN})"
    if (stem.endswith("_ad") or stem.endswith("_ad_multi")) and "ad" not in descs.lower():
        return "ad seq missing ad tap"

    for s in steps:
        action = s.get("action")
        params = s.get("params") or {}
        desc = str(s.get("description") or "")
        if action == "tap":
            x = _coord_base(params.get("x"))
            y = _coord_base(params.get("y"))
            bad = _coord_in_bounds(x, y)
            if bad:
                return f"tap {bad} in {path.name}: {desc}"
            # Never allow taps in Chrome omnibox / voice-search mic zone
            if y is not None and y < OMNIBOX_MAX_Y and "interstitial" not in desc.lower():
                return f"omnibox-zone tap y={y} in {path.name}: {desc}"
        if action == "swipe":
            x1 = _coord_base(params.get("x1") or params.get("x"))
            y1 = _coord_base(params.get("y1") or params.get("y"))
            x2 = _coord_base(params.get("x2"))
            y2 = _coord_base(params.get("y2"))
            for label, cx, cy in (("x1", x1, y1), ("x2", x2, y2)):
                bad = _coord_in_bounds(cx, cy)
                if bad:
                    return f"swipe {label} {bad} in {path.name}: {desc}"
            if y1 is not None and y1 < MIN_SCROLL_Y:
                return f"unsafe swipe y1={y1} (<{MIN_SCROLL_Y})"
        if action == "open_url" and strict:
            url = str(params.get("url") or "").strip()
            if not url.startswith("http"):
                return f"open_url missing http(s) url in {path.name}"
        if action == "wait" and "Mantis" in desc and "View" not in desc:
            sec = params.get("seconds") or {}
            mn = float(sec.get("min") or 0) if isinstance(sec, dict) else float(sec or 0)
            if mn >= 12:
                return f"stale long Mantis fill wait in {path.name}"
    return None


def _filter_pools(pools: dict[str, list[Path]]) -> tuple[int, set[str]]:
    """Preflight every sequence before run; drop failures from pools."""
    quarantined = _load_quarantine_stems(pools)
    if quarantined:
        logger.warning("quarantine active: %d stems skipped", len(quarantined))
    rejected = 0
    for kind in list(pools.keys()):
        kept: list[Path] = []
        for path in pools[kind]:
            if path.stem in quarantined:
                logger.warning("preflight quarantine %s [%s]", path.name, kind)
                rejected += 1
                continue
            err = _preflight(path, strict=True)
            if err:
                logger.warning("preflight reject %s [%s]: %s", path.name, kind, err)
                rejected += 1
            else:
                kept.append(path)
        pools[kind] = kept
    return rejected, quarantined


def _variant_label(path: Path) -> str:
    stem = _pool_stem(path.stem)
    if stem.endswith("_ad_multi"):
        return "ad_multi"
    if stem.endswith("_ad"):
        return "ad"
    if stem.endswith("_halfway"):
        return "halfway"
    if stem.endswith("_browse"):
        return "browse"
    if stem.endswith("_complete"):
        return "complete"
    return "other"


def _schedule_path3_slots(
    rng: random.Random,
    *,
    minute: int,
    phone_idx: int,
    count: int | None = None,
) -> list[int]:
    """Pick up to `count` (default: PATH3_PER_HOUR) *future* minutes this hour.

    Never schedules already-past minutes (restart / late-hour flood).
    Each phone gets a *random* lead offset so Path3 ads do not align.
    Mid-hour restart / late join: if the offset would wipe the hour, still
    schedule at least one click in the remaining minutes when count>=1.
    """
    k = max(0, int(count) if count is not None else _path3_per_hour(phone_idx))
    if k == 0:
        return []
    # Small per-phone lead so ads do not align — keep it small enough that
    # every phone still gets slots this hour (old 0..21m offset wiped late hours).
    rand_offset = rng.randint(0, max(1, PATH3_PHONE_OFFSET_MIN))
    earliest = minute + PATH3_MIN_LEAD_MIN + rand_offset
    lo = max(PATH3_SLOT_LO, earliest)
    pool = list(range(lo, PATH3_SLOT_HI))
    if not pool:
        late_lo = min(58, minute + max(2, PATH3_MIN_LEAD_MIN))
        pool = list(range(late_lo, 59))
        if not pool:
            return []

    slots: list[int] = []
    remaining = pool[:]
    spacing = _path3_slot_spacing_min()
    for _ in range(k):
        if not remaining:
            break
        pick = rng.choice(remaining)
        slots.append(pick)
        remaining = [m for m in remaining if abs(m - pick) >= spacing]
    return sorted(slots)


def _schedule_hour_seq_slots(
    rng: random.Random,
    *,
    phone_idx: int,
    minute_now: int,
    second_now: float = 0.0,
    spacing_s: float | None = None,
    count: int | None = None,
) -> list[float]:
    """Spread visit start offsets (seconds into the hour) for this phone.

    A fresh randomized phase is chosen each hour. Slots cover the whole hour,
    and past slots are dropped so a mid-hour restart never dumps a backlog.
    """
    n = max(1, int(count) if count is not None else SEQS_PER_HOUR)
    base_spacing = spacing_s if spacing_s is not None else PHONE_SPACING_S.get(phone_idx, 240.0)
    # Per-hour spacing wobble so phones don't share identical cadence.
    # Old hard 90s floor capped income at ~40 seq/hr even when overrides said 72.
    rate_floor = max(
        45.0,
        float(os.environ.get("PHARMFLOW_FARM_MIN_SEQ_SPACING_S", "0") or "0")
        or (3600.0 / max(n, 1)) * 0.72,
    )
    spacing = max(rate_floor, base_spacing * rng.uniform(0.82, 1.22))
    # The operator's count is exact — never trimmed. When n does not fit the
    # hour at the requested spacing, compress spacing so every slot is distinct
    # and inside the hour (45s floor keeps starts from colliding); the old code
    # instead stacked duplicates at the 3520s ceiling.
    span = 3516.0  # usable second range inside the hour
    if n > 1 and spacing * (n - 1) > span:
        spacing = max(45.0, span / (n - 1))
    phase = rng.uniform(0.0, max(1.0, spacing))
    jitter = max(8.0, _slot_jitter)
    raw: list[float] = []
    for i in range(n):
        t = phase + i * spacing + rng.uniform(-jitter, jitter)
        # Keep inside the hour with a little headroom for run time.
        t = max(2.0, min(3519.0, t))
        raw.append(t)
    raw = sorted(raw)
    # Deduplicate near-collisions (keep spaced ~45s apart).
    cleaned: list[float] = []
    for t in raw:
        if not cleaned or t - cleaned[-1] >= 45.0:
            cleaned.append(t)
    # If jitter dedupe dropped any slot, restore the exact count with an even
    # grid across the hour — count always wins, duplicates never happen.
    if len(cleaned) < n:
        if n == 1:
            cleaned = [min(3519.0, max(2.0, phase))]
        else:
            step = span / (n - 1)
            cleaned = [2.0 + i * step for i in range(n)]
    cleaned = cleaned[:n]
    cutoff = minute_now * 60.0 + second_now + SLOT_MIN_LEAD_S
    future = [t for t in cleaned if t >= cutoff]
    # Mid-hour restart / operator "clear+restart": don't sit idle 2–3 minutes
    # waiting for a random phase. Kick the first sequence within a few seconds.
    immediate = os.environ.get("PHARMFLOW_FARM_IMMEDIATE_START", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ) or SLOT_MIN_LEAD_S <= 1.0
    if immediate:
        soon = cutoff + rng.uniform(2.0, 6.0)
        rest = [t for t in future if t >= soon + 35.0]
        future = [soon] + rest
    if not future:
        # Late restart: don't clamp everything to 58:40 — park a few random
        # slots in what's left, or yield empty and wait for the next hour.
        remain_s = 3600.0 - minute_now * 60.0 - second_now
        if remain_s < 90.0:
            return []
        left = max(1, min(n // 3, int(remain_s // 90)))
        step = remain_s / (left + 1)
        base = cutoff + rng.uniform(5.0, 25.0)
        future = []
        for i in range(left):
            t = base + i * step + rng.uniform(-step * 0.25, step * 0.25)
            t = max(cutoff, min(3520.0, t))
            if not future or t - future[-1] >= 40.0:
                future.append(t)
    return future


def _path3_due_slot(
    path3_slots: list[int],
    path3_fired: set[int],
    minute: int,
) -> tuple[bool, int | None, list[int]]:
    """Return (want_ads, due_slot, newly_skipped_stale_slots).

    Only the nearest unfired slot may become due. Past slots beyond the grace
    window are skipped (missed), not stacked into a flood.

    When the nearest unfired slot is still upcoming but within
    PATH3_PREEMPT_MIN, return want_ads=True early so the next pick is Path3
    instead of a long Path1/2 that would span (and miss) the slot.
    """
    skipped: list[int] = []
    for slot in path3_slots:
        if slot in path3_fired:
            continue
        if minute < slot:
            # Imminent upcoming slot: fire Path3 now rather than start a browse
            # that will still be running when the minute hits.
            if PATH3_PREEMPT_MIN > 0 and (slot - minute) <= PATH3_PREEMPT_MIN:
                return True, slot, skipped
            # Nearest upcoming — wait; do not look at later past-due leftovers.
            return False, None, skipped
        if minute - slot > PATH3_DUE_GRACE_MIN:
            skipped.append(slot)
            continue
        return True, slot, skipped
    return False, None, skipped


def _parse_combo(stem: str) -> tuple[str, str, str] | None:
    """Extract (material, concentrate, heater) from a sequence stem."""
    materials = ("quartz", "titanium", "ceramic")
    concentrates = (
        "live_resin",
        "hash_rosin",
        "shatter",
        "wax",
        "rosin",
        "diamonds",
        "crumble",
        "budder",
        "sauce",
        "distillate",
    )
    heaters = ("butane", "propane")
    for mat in materials:
        prefix = mat + "_"
        if not stem.startswith(prefix):
            continue
        rest = stem[len(prefix) :]
        for conc in sorted(concentrates, key=len, reverse=True):
            cprefix = conc + "_"
            if not rest.startswith(cprefix):
                continue
            rest2 = rest[len(cprefix) :]
            for heat in heaters:
                if rest2.startswith(heat + "_") or rest2 == heat:
                    return mat, conc, heat
    return None


def _stem_browser(stem: str) -> str:
    """Browser encoded in Path1/2 stem (*_firefox_complete, *_brave_*, …)."""
    low = (stem or "").lower()
    for name in ("duckduckgo", "chromium", "firefox", "brave", "opera"):
        token = f"_{name}_"
        if (
            token in low
            or low.endswith(f"_{name}_complete")
            or low.endswith(f"_{name}_halfway")
            or low.endswith(f"_{name}")
        ):
            return name
    return ""


def _parse_ad_key(stem: str) -> str | None:
    """Stable ad identity: home:N | stats:N | glass:N | settings:N."""
    m = re.search(r"homead(\d+)", stem)
    if m:
        return f"home:{m.group(1)}"
    m = re.search(r"_on(stats|glass|settings)_ad(\d+)_ad$", stem)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    m = re.search(r"_(stats|glass|settings)_ad(\d+)_ad$", stem)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    return None


def _identity_keys(stem: str) -> set[str]:
    """Farm-wide reservation keys for one sequence (file + optional ad slot)."""
    return farm_identity_keys(stem, ad_key_fn=_parse_ad_key)


def _pick(
    pools: dict[str, list[Path]],
    *,
    want_ads: bool,
    rng: random.Random,
    active_keys: set[str],
    used_stems: set[str],
    last_ad: list[str | None],
    recent: list[str],
    recent_ad_keys: list[str],
    recent_combos: list[str],
    recent_stems: list[str],
) -> Path | None:
    """Pick a sequence whose identity keys are free; rotate ads + combos.

    Non-ad (Path 1/2) sequences are drawn WITHOUT REPLACEMENT: a stem is not
    reused until every non-ad sequence in its pool has been run once, at which
    point the pool's pass resets. Ad (Path 3) sequences stay random but never
    repeat the same file concurrently (identity lock) or back-to-back farm-wide.
    """
    # Pool selection follows the PER-SLOT want_ads flag, not the global ads
    # switch. _ads_allowed() alone made every pick draw from the ad pool even
    # on normal visit slots; the Path3 farm-cap guard then refused them all →
    # 24×None → "no unique sequence available" → phones idle (2026-09-13).
    if want_ads and _ads_allowed() and pools.get("ad"):
        candidates = list(pools["ad"])
        # Never the same ad file back-to-back across the whole farm.
        if last_ad and last_ad[0]:
            filtered = [p for p in candidates if p.stem != last_ad[0]]
            if filtered:
                candidates = filtered
    else:
        if rng.random() < _halfway_share() and pools["halfway"]:
            candidates = list(pools["halfway"])
        elif pools["complete"]:
            candidates = list(pools["complete"])
        elif pools["halfway"]:
            candidates = list(pools["halfway"])
        else:
            candidates = list(pools["ad"]) if _ads_allowed() else []
        # Draw-without-replacement: prefer stems not yet run this pass. When the
        # pool is exhausted, reset just this pool's entries and start a new pass.
        if candidates:
            unused = [p for p in candidates if p.stem not in used_stems]
            if not unused:
                pool_stems = {p.stem for p in candidates}
                used_stems.difference_update(pool_stems)
                logger.info(
                    "draw-without-replacement: pool exhausted (%d stems) — new pass",
                    len(pool_stems),
                )
                unused = list(candidates)
            candidates = unused
            # Soft-balance browsers so Brave/DDG are not starved while Firefox
            # unused-pool is huge (draw-without-replacement left Brave rare).
            recent_browsers = [
                _stem_browser(s) for s in list(recent_stems[-24:]) + list(recent[-16:])
            ]
            recent_browsers = [b for b in recent_browsers if b]
            if recent_browsers:
                counts = Counter(recent_browsers)
                # Prefer the least-seen browser among candidates that still have stems.
                by_browser: dict[str, list[Path]] = {}
                for p in candidates:
                    b = _stem_browser(p.stem) or "other"
                    by_browser.setdefault(b, []).append(p)
                if len(by_browser) > 1:
                    # Bias toward underrepresented browsers (Brave often starved).
                    ranked = sorted(
                        by_browser.keys(),
                        key=lambda b: (counts.get(b, 0), rng.random()),
                    )
                    pick_b = ranked[0]
                    if by_browser.get(pick_b) and rng.random() < 0.72:
                        candidates = by_browser[pick_b]
            # Max $ (cloud Mantis docs): soft-prefer Path1C/D multi-tab tours
            # (~more zones/visit → impressions) over single-tab completes.
            multi = [
                p
                for p in candidates
                if "_p1d_" in p.stem or "_p1c_" in p.stem or "_p2" in p.stem
            ]
            prefer = 1.0 if (os.environ.get("PHARMFLOW_EVCPM_PUSH") or "").strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            ) else 0.75
            if multi and rng.random() < prefer:
                candidates = multi

    # Live quarantine from fail_review (broken stems patched past recovery).
    banned = _live_quarantine_stems()
    if banned and candidates:
        kept = [p for p in candidates if p.stem not in banned]
        if kept:
            candidates = kept
        else:
            logger.warning(
                "all candidates quarantined (%d) — picking from banned pool as last resort",
                len(banned),
            )

    rng.shuffle(candidates)
    recent_set = set(recent[-16:])
    farm_recent = set(recent_stems[-24:])
    recent_ads = set(recent_ad_keys[-32:])
    recent_combo_set = set(recent_combos[-20:])
    # Page diversity: home / stats / glass / settings — avoid same page back-to-back.
    recent_pages = []
    for k in recent_ad_keys[-12:]:
        page = (k or "").split(":", 1)[0] if k else ""
        if page:
            recent_pages.append(page)
    last_page = recent_pages[-1] if recent_pages else ""
    page_counts = {p: recent_pages.count(p) for p in ("home", "stats", "glass", "settings")}

    def _score(path: Path) -> tuple[int, int, int, int, int]:
        stem = path.stem
        ad_key = _parse_ad_key(stem)
        combo = _parse_combo(stem)
        combo_s = "|".join(combo) if combo else ""
        page = (ad_key or "").split(":", 1)[0] if ad_key else ""
        # Lower is better.
        ad_pen = 0
        page_pen = 0
        if want_ads:
            if ad_key and ad_key in recent_ads:
                ad_pen += 100
            if recent_ad_keys and ad_key == recent_ad_keys[-1]:
                ad_pen += 80
            if page and page == last_page:
                page_pen += 60
            if page:
                page_pen += int(page_counts.get(page, 0)) * 15
        combo_pen = 30 if combo_s and combo_s in recent_combo_set else 0
        recent_pen = 10 if stem in recent_set else 0
        farm_pen = 20 if stem in farm_recent else 0
        return (ad_pen, page_pen, combo_pen, farm_pen, recent_pen)

    usable: list[Path] = []
    refused = 0
    for path in candidates:
        keys = _identity_keys(path.stem)
        if keys & active_keys:
            refused += 1
            continue
        if _preflight(path, strict=True) is not None:
            continue
        usable.append(path)
    if not usable:
        if refused:
            logger.info(
                "unique-seq lock: all candidates blocked (refused=%d active=%s)",
                refused,
                sorted(active_keys),
            )
        return None

    # When ads are due: hard-prefer a slot we have not used recently + rotate pages.
    if want_ads:
        fresh = [p for p in usable if (_parse_ad_key(p.stem) or "") not in recent_ads]
        if fresh:
            usable = fresh
        else:
            keep = max(4, len(recent_ad_keys) // 2)
            del recent_ad_keys[:-keep]
            recent_ads = set(recent_ad_keys)
            fresh = [p for p in usable if (_parse_ad_key(p.stem) or "") not in recent_ads]
            if fresh:
                usable = fresh
        # Prefer a different page than the last Path3 click farm-wide.
        if last_page:
            other_page = [
                p
                for p in usable
                if (( _parse_ad_key(p.stem) or "").split(":", 1)[0] != last_page)
            ]
            if other_page:
                usable = other_page

    # Prefer unseen material/concentrate/heater combos.
    combo_fresh = [
        p
        for p in usable
        if (c := _parse_combo(p.stem)) is None or "|".join(c) not in recent_combo_set
    ]
    if combo_fresh:
        usable = combo_fresh

    # Soft-prefer stems not recently finished on any phone.
    farm_fresh = [p for p in usable if p.stem not in farm_recent]
    if farm_fresh:
        usable = farm_fresh

    usable.sort(key=_score)
    # Among best-scoring, pick randomly from the top band.
    best = _score(usable[0])
    top = [p for p in usable if _score(p) == best]
    return rng.choice(top)

def _worker(
    phone: str,
    phone_idx: int,
    pools: dict[str, list[Path]],
    farm: MuMuFarmOps,
    runner: SequenceRunner,
    *,
    results_path: Path,
    progress: dict,
    lock: threading.Lock,
    stop_event: threading.Event,
    per_phone: int,
    seq_lock: UniqueSequenceLock,
    used_stems: set[str],
    last_ad: list[str | None],
    recent_ad_keys: list[str],
    recent_combos: list[str],
    recent_stems: list[str],
    deadline_ts: float,
    start_delay_s: float = 0.0,
) -> None:
    rng = random.Random(os.urandom(16) + phone.encode() + phone_idx.to_bytes(2, "little"))
    delay = max(0.0, float(start_delay_s))
    logger.info("[%s] stagger start sleep %.1fs (random assign)", phone, delay)
    time.sleep(delay)

    inst = farm.get_phone(phone)
    if inst and inst.adb_serial:
        ok, size = _ensure_wm_size(farm, inst.adb_serial, phone)
        if not ok:
            logger.warning("[%s] wm size not confirmed at init: %s", phone, size)
        else:
            logger.info("[%s] wm size OK at init: %s", phone, size)
        try:
            # Refresh assignment after stagger so timezone sticks before first sequence.
            for serial, loc in apply_geo_window_to_serials(farm.adb, [inst.adb_serial]):
                logger.info("[%s] GEO refresh %s tz=%s", phone, loc.label, loc.tz)
        except Exception as exc:
            logger.debug("[%s] geo refresh skipped: %s", phone, exc)

    recent: list[str] = []
    done = 0
    path3_hour = -1
    path3_slots: list[int] = []
    path3_fired: set[int] = set()
    hour_budget_key = -1
    hour_seq_slots: list[float] = []
    hour_seq_idx = 0
    slot_fails = 0  # consecutive FAILs on current hour slot (reset on OK / advance)
    path3_nobill_streak = 0  # consecutive Path3 OK-nobill (house/bot) — cooldown Path3 at 3
    # Wall-clock until which this phone skips Path3 only (Path1/2 keep earning).
    path3_cooldown_until = 0.0
    path3_cooldown_log_at = 0.0
    # Per-phone cadence wobble for the whole worker lifetime.
    phone_spacing = max(
        90.0,
        PHONE_SPACING_S.get(phone_idx, 240.0) * rng.uniform(0.85, 1.18),
    )

    while done < per_phone and not stop_event.is_set() and not _stop_requested():
        if time.time() >= deadline_ts:
            logger.info("[%s] duration reached — stopping", phone)
            break

        # Hard daily visit cap — idle until local midnight, then resume.
        # Evening fill bypasses the cap so we can run N/hour until midnight.
        if (
            not _evening_fill_active()
            and _phone_visits_cap(phone_idx) > 0
            and _phone_visits_remaining(phone_idx) <= 0
        ):
            wait_for = min(900.0, _secs_until_local_midnight())
            logger.info(
                "[%s] daily visit cap reached (%d) — idle %.0fs until next day",
                phone,
                _phone_visits_cap(phone_idx),
                wait_for,
            )
            if stop_event.wait(wait_for):
                break
            continue

        n = done + 1
        now = time.time()
        hour_key = int(now // 3600)
        minute_now = int((now % 3600) // 60)
        ads_left = _phone_ads_remaining(phone_idx)
        if hour_key != path3_hour:
            path3_hour = hour_key
            # Path3 count from remaining daily ads / hours left (not locked PATH3_PER_HOUR).
            path3_this_hour = _phone_path3_this_hour(phone_idx, rng)
            if ads_left <= 0 or path3_this_hour <= 0:
                path3_slots = []
            else:
                path3_slots = _schedule_path3_slots(
                    rng,
                    minute=minute_now,
                    phone_idx=phone_idx,
                    count=path3_this_hour,
                )
            path3_fired = set()
            if path3_slots:
                logger.info(
                    "[%s] Path3 slots this hour (min): %s (from minute=%d, ads_left=%d, want=%d)",
                    phone,
                    path3_slots,
                    minute_now,
                    ads_left,
                    path3_this_hour,
                )
            else:
                logger.info(
                    "[%s] Path3 skipped this hour (minute=%d ads_left=%d want=%d)",
                    phone,
                    minute_now,
                    ads_left,
                    path3_this_hour,
                )

        if hour_key != hour_budget_key:
            hour_budget_key = hour_key
            seqs_this_hour = _phone_seqs_this_hour(phone_idx, rng)
            if _evening_fill_active() and seqs_this_hour > 0:
                # Pack into the *remaining* part of this hour (mid-hour restart
                # must not drop rate just because past slots were pruned).
                mins_left = max(1, 60 - minute_now)
                # Dense evening pack floor (minutes/visit). Default 1.5 so evening=36
                # can actually schedule (~40/hr theoretical); was hardcoded 2.5 → max 24/hr.
                try:
                    evening_floor = float(
                        os.environ.get("PHARMFLOW_FARM_EVENING_MIN_PER_VISIT", "1.5")
                        or "1.5"
                    )
                except (TypeError, ValueError):
                    evening_floor = 1.5
                evening_floor = max(0.75, min(5.0, evening_floor))
                max_fit = max(1, int(mins_left // evening_floor))
                if max_fit < seqs_this_hour:
                    logger.info(
                        "[%s] evening fill: %d→%d slots (only %dm left this hour)",
                        phone,
                        seqs_this_hour,
                        max_fit,
                        mins_left,
                    )
                    seqs_this_hour = max_fit
            if seqs_this_hour <= 0:
                wait_for = min(900.0, _secs_until_local_midnight())
                logger.info(
                    "[%s] no visit budget this hour — idle %.0fs",
                    phone,
                    wait_for,
                )
                if stop_event.wait(wait_for):
                    break
                continue
            # Spacing from this phone's remaining daily visits (not locked SEQS_PER_HOUR).
            # Evening fill: spread evenly across minutes left in this hour.
            if _evening_fill_active():
                rem_s = max(90.0, (60 - minute_now) * 60.0 - 20.0)
                phone_spacing = max(75.0, (rem_s / max(1, seqs_this_hour)) * rng.uniform(0.9, 1.1))
            else:
                phone_spacing = max(90.0, (3600.0 / max(1, seqs_this_hour)) * rng.uniform(0.85, 1.18))
            hour_seq_slots = _schedule_hour_seq_slots(
                rng,
                phone_idx=phone_idx,
                minute_now=minute_now,
                second_now=now % 60.0,
                spacing_s=phone_spacing,
                count=seqs_this_hour,
            )
            # Evening fill: if pruning still left us short, re-seed future-only slots.
            if _evening_fill_active() and len(hour_seq_slots) < seqs_this_hour:
                lead = max(SLOT_MIN_LEAD_S, 20.0)
                start = minute_now * 60.0 + (now % 60.0) + lead
                end = 3580.0
                n = seqs_this_hour
                if end > start + 30:
                    gap = (end - start) / max(1, n)
                    hour_seq_slots = [
                        min(end, start + i * gap + rng.uniform(-8.0, 8.0)) for i in range(n)
                    ]
                    hour_seq_slots = sorted(max(start, t) for t in hour_seq_slots)
            hour_seq_idx = 0
            budget = _phone_budget_row(_load_daily_budget(), phone_idx)
            logger.info(
                "[%s] hour schedule %d slots @ %s (spacing=%.0fs, day visits=%d/%d ads=%d/%d, hours_left=%.1f%s)",
                phone,
                len(hour_seq_slots),
                [f"{int(s // 60):02d}:{int(s % 60):02d}" for s in hour_seq_slots[:8]]
                + (["…"] if len(hour_seq_slots) > 8 else []),
                phone_spacing,
                budget["visits"],
                _phone_visits_cap(phone_idx) or 0,
                budget["ads"],
                _phone_ads_cap(phone_idx),
                _hours_left_today(),
                "; evening=%d/hr" % EVENING_SEQS_PER_HOUR if _evening_fill_active() else "",
            )

        # Wait for next scheduled slot this hour (spread through the hour).
        if hour_seq_idx >= len(hour_seq_slots):
            secs_left = 3600.0 - (now % 3600.0)
            wait_for = secs_left + rng.uniform(2.0, 25.0)
            logger.info(
                "[%s] hour schedule complete (%d) — idle %.0fs until next hour",
                phone,
                len(hour_seq_slots),
                wait_for,
            )
            if stop_event.wait(wait_for):
                break
            continue

        target_off = hour_seq_slots[hour_seq_idx]
        sec_into_hour = now % 3600.0
        if sec_into_hour < target_off:
            wait_for = target_off - sec_into_hour
            logger.info(
                "[%s] wait %.0fs for slot %d/%d @ %02d:%02d",
                phone,
                wait_for,
                hour_seq_idx + 1,
                len(hour_seq_slots),
                int(target_off // 60),
                int(target_off % 60),
            )
            if stop_event.wait(wait_for):
                break
            continue

        minute = int((time.time() % 3600) // 60)
        want_ads = False
        due_slot: int | None = None
        path3_on_cooldown = time.time() < path3_cooldown_until
        if path3_on_cooldown:
            # Still advance missed-slot bookkeeping so grace skips do not pile up,
            # but never pick Path3 while house/bot cooldown is active.
            if path3_slots:
                _want, _due, skipped = _path3_due_slot(
                    path3_slots, path3_fired, minute
                )
                for stale in skipped:
                    path3_fired.add(stale)
                    logger.info(
                        "[%s] Path3 slot=%s missed during house cooldown "
                        "(minute=%s, grace=%d) — skip",
                        phone,
                        stale,
                        minute,
                        PATH3_DUE_GRACE_MIN,
                    )
            left_s = max(0.0, path3_cooldown_until - time.time())
            if time.time() - path3_cooldown_log_at >= 120.0:
                path3_cooldown_log_at = time.time()
                logger.info(
                    "[%s] Path3 house/bot cooldown %.0fs left — Path1/2 only "
                    "(phone stays active)",
                    phone,
                    left_s,
                )
        elif _ads_allowed() and pools.get("ad") and path3_slots:
            want_ads, due_slot, skipped = _path3_due_slot(
                path3_slots, path3_fired, minute
            )
            for stale in skipped:
                path3_fired.add(stale)
                logger.info(
                    "[%s] Path3 slot=%s missed (minute=%s, grace=%d) — skip",
                    phone,
                    stale,
                    minute,
                    PATH3_DUE_GRACE_MIN,
                )
            if (
                want_ads
                and due_slot is not None
                and minute < due_slot
                and PATH3_PREEMPT_MIN > 0
            ):
                logger.info(
                    "[%s] Path3 preempt slot=%s (minute=%s, ahead=%dm) — want_ads "
                    "to avoid spanning non-ad",
                    phone,
                    due_slot,
                    minute,
                    due_slot - minute,
                )

        path: Path | None = None
        reserved_keys: set[str] = set()
        path3_reserved = False
        with lock:
            if want_ads and _phone_ads_remaining(phone_idx) <= 0:
                logger.info(
                    "[%s] Path3 phone daily ad cap reached (%d) — use Path1/2",
                    phone,
                    _phone_ads_cap(phone_idx),
                )
                want_ads = False
            if want_ads and not _path3_available_today():
                state = _load_path3_daily_state()
                logger.info(
                    "[%s] Path3 farm-wide guard: count=%s/%s gap=%sm — use Path1/2",
                    phone,
                    state["count"],
                    _path3_farm_daily_cap(),
                    _path3_global_gap_min(),
                )
                want_ads = False
            for _ in range(24):
                cand = _pick(
                    pools,
                    want_ads=want_ads,
                    rng=rng,
                    active_keys=seq_lock.active,
                    used_stems=used_stems,
                    last_ad=last_ad,
                    recent=recent,
                    recent_ad_keys=recent_ad_keys,
                    recent_combos=recent_combos,
                    recent_stems=recent_stems,
                )
                if cand is None:
                    break
                err = _preflight(cand, strict=True)
                if err:
                    logger.warning("preflight skip %s: %s", cand.name, err)
                    continue
                keys = _identity_keys(cand.stem)
                if not seq_lock.try_reserve(keys):
                    logger.info(
                        "unique-seq lock: refuse %s (collision %s)",
                        cand.stem,
                        sorted(seq_lock.conflicts(keys)),
                    )
                    continue
                path = cand
                reserved_keys = keys
                is_ad_pick = cand.stem.endswith("_ad") or cand.stem.endswith("_ad_multi")
                path3_reserved = False
                if is_ad_pick:
                    if _phone_ads_remaining(phone_idx) <= 0:
                        seq_lock.release(reserved_keys)
                        path = None
                        reserved_keys = set()
                        want_ads = False
                        continue
                    daily = _reserve_path3_today()
                    if daily is None:
                        seq_lock.release(reserved_keys)
                        path = None
                        reserved_keys = set()
                        want_ads = False
                        continue
                    path3_reserved = True
                    last_ad[0] = cand.stem
                    logger.info(
                        "[%s] Path3 daily reserve farm=%s/%s phone_ads_left=%s; gap=%sm",
                        phone,
                        daily["count"],
                        _path3_farm_daily_cap(),
                        max(0, _phone_ads_remaining(phone_idx) - 1),
                        _path3_global_gap_min(),
                    )
                # Non-ad stems are marked used only after OK (fail → retry keeps pool honest).
                logger.info(
                    "unique-seq lock: reserve %s keys=%s (used_pass=%d)",
                    path.stem,
                    sorted(keys),
                    len(used_stems),
                )
                break

        if path is None:
            entry = {
                "time": _utc(),
                "phone": phone,
                "n": n,
                "want_ads": want_ads,
                "success": False,
                "error": "no unique sequence available",
            }
            # No sequence available — advance slot so we don't spin forever.
            done += 1
            hour_seq_idx += 1
            with lock:
                progress[phone] = {"done": done, "last": entry}
                with open(results_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry) + "\n")
            continue

        t0 = time.time()
        is_path3 = path.stem.endswith("_ad") or path.stem.endswith("_ad_multi")
        entry: dict = {
            "time": _utc(),
            "phone": phone,
            "n": n,
            "want_ads": want_ads,
            "path3": is_path3,
            "variant": _variant_label(path),
            "path": path.as_posix(),
            "sequence": path.stem,
        }
        try:
            inst = farm.get_phone(phone)
            if inst and inst.adb_serial:
                ok, size = _ensure_wm_size(farm, inst.adb_serial, phone)
                entry["wm_size"] = size
                if not ok:
                    # Don't burn the hour slot on a transient ADB blip — reconnect
                    # and retry this same slot after a short backoff.
                    logger.error(
                        "[%s] bad resolution before run (%r) — backoff+retry same slot",
                        phone,
                        size,
                    )
                    if path3_reserved:
                        try:
                            with lock:
                                _unreserve_path3_today()
                            logger.info(
                                "[%s] Path3 reserve rolled back after bad resolution (keep ad count honest)",
                                phone,
                            )
                        except Exception as exc:
                            logger.warning(
                                "[%s] Path3 unreserve after bad resolution soft-fail: %s",
                                phone,
                                exc,
                            )
                        path3_reserved = False
                    seq_lock.release(reserved_keys)
                    reserved_keys = set()
                    if stop_event.wait(20.0):
                        break
                    continue

            seq = Sequence.from_json(path)
            seq.phone = phone
            generic_site = _is_generic_site_path(path)
            if seq.sequence_version < REQUIRED_SEQUENCE_VERSION:
                entry["success"] = False
                entry["error"] = f"v{seq.sequence_version} rejected"
            elif int(seq.author_width) != AUTHOR_W or int(seq.author_height) != AUTHOR_H:
                entry["success"] = False
                entry["error"] = f"author {seq.author_width}x{seq.author_height} rejected"
            else:
                # Never strip Path 3 ad steps. Path 1/2 have no ad taps to strip.
                descs = " | ".join(s.description or "" for s in seq.steps)
                if not generic_site and "Start Perfect Dab" not in descs:
                    entry["success"] = False
                    entry["error"] = "Start Perfect Dab missing"
                else:
                    report = runner.run(seq)
                    entry["success"] = bool(report.get("success"))
                    entry["error"] = report.get("error")
                    entry["failed_at"] = report.get("failed_at")
                    click_ok = _path3_forced_click_ok(report)
                    entry["path3_click_open"] = click_ok
                    # HARDCODED isolation fields from SequenceRunner (every seq).
                    if report.get("ip_after") or report.get("isolation"):
                        iso = report.get("isolation") or {}
                        entry["ip_before"] = report.get("ip_before") or iso.get("ip_before")
                        entry["ip_after"] = report.get("ip_after") or iso.get("ip_after")
                        entry["ip_changed"] = report.get("ip_changed", iso.get("ip_changed"))
                        entry["ip_retries"] = report.get("ip_retries", iso.get("ip_retries"))
                        entry["geo"] = iso.get("geo")
                        entry["imei"] = iso.get("imei")
                    for step in report.get("steps") or []:
                        if step.get("ad_pick"):
                            pick = step["ad_pick"]
                            entry["ad_live"] = pick.get("key") or pick.get("slot")
                            if pick.get("tab"):
                                entry["ad_tab"] = pick.get("tab")
                            if pick.get("zone"):
                                entry["ad_zone"] = pick.get("zone")
                        if step.get("action") == "rotate_identity":
                            if step.get("exit_ip") and not entry.get("ip_after"):
                                entry["ip_after"] = step.get("exit_ip")
                            if step.get("ip_before") is not None and not entry.get("ip_before"):
                                entry["ip_before"] = step.get("ip_before")
                            if "ip_changed" in step and "ip_changed" not in entry:
                                entry["ip_changed"] = step.get("ip_changed")
                            if "ip_retries" in step and "ip_retries" not in entry:
                                entry["ip_retries"] = step.get("ip_retries")
                            break
                    by_phone = getattr(farm, "_last_exit_ip_rotate_by_phone", None)
                    ip_info = by_phone.get(phone) if isinstance(by_phone, dict) else None
                    if ip_info is None:
                        ip_info = getattr(farm, "_last_exit_ip_rotate", None)
                    if ip_info is not None and "ip_after" not in entry:
                        entry["ip_before"] = ip_info.before
                        entry["ip_after"] = ip_info.after
                        entry["ip_changed"] = ip_info.changed
                        entry["ip_retries"] = ip_info.retries
                    if entry.get("ip_after"):
                        logger.info(
                            "[%s] seq IP before=%s after=%s changed=%s retries=%s",
                            phone,
                            entry.get("ip_before") or "?",
                            entry.get("ip_after") or "?",
                            "yes" if entry.get("ip_changed") else "no",
                            entry.get("ip_retries", "?"),
                        )
                    if is_path3 and entry["success"] and due_slot is not None:
                        # Non-billable (house/bot / NO click_url): do not consume the
                        # hour Path3 slot so a later due/grace window can retry.
                        if click_ok is False:
                            logger.warning(
                                "[%s] Path3 slot=%s non-billable click_url — "
                                "hour slot kept open for retry",
                                phone,
                                due_slot,
                            )
                        else:
                            path3_fired.add(due_slot)
                            logger.info(
                                "[%s] Path3 fired slot=%s (%d/%d this hour)",
                                phone,
                                due_slot,
                                len(path3_fired),
                                _path3_per_hour(phone_idx),
                            )
        except Exception as exc:
            entry["success"] = False
            entry["error"] = str(exc)
            entry["traceback"] = traceback.format_exc()
        entry["elapsed_s"] = round(time.time() - t0, 1)
        ok = bool(entry.get("success"))
        combo = _parse_combo(path.stem)
        ad_key = _parse_ad_key(path.stem)
        if ad_key:
            entry["ad_key"] = ad_key

        if not ok:
            # FAIL: do not burn visit/ad budget or hour slot — retry with fresh
            # isolation (SequenceRunner isolate_before_sequence on next attempt).
            if path3_reserved:
                try:
                    with lock:
                        _unreserve_path3_today()
                    logger.info(
                        "[%s] Path3 reserve rolled back after FAIL (keep ad count honest)",
                        phone,
                    )
                except Exception as exc:
                    logger.warning("[%s] Path3 unreserve soft-fail: %s", phone, exc)
                path3_reserved = False
            with lock:
                seq_lock.release(reserved_keys)
                logger.info(
                    "unique-seq lock: release %s keys=%s (FAIL)",
                    path.stem,
                    sorted(reserved_keys),
                )
                progress[phone] = {"done": done, "last": entry}
                with open(results_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry) + "\n")
            kind = "P3-AD" if is_path3 else ("P2" if "halfway" in path.stem else "P1")
            logger.info(
                "[%s] %d %s FAIL %s %.1fs err=%s",
                phone,
                n,
                kind,
                path.stem,
                entry["elapsed_s"],
                (entry.get("error") or "")[:120],
            )
            slot_fails += 1
            if slot_fails <= FAIL_RETRY_MAX:
                backoff = min(45.0, 8.0 + slot_fails * 6.0) * rng.uniform(0.85, 1.2)
                logger.info(
                    "[%s] FAIL retry %d/%d same slot in %.0fs (daily counts unchanged)",
                    phone,
                    slot_fails,
                    FAIL_RETRY_MAX,
                    backoff,
                )
                if stop_event.wait(backoff):
                    break
                continue
            # Exhausted quick retries — longer backoff, then pick a NEW sequence
            # for the SAME hour slot so the daily visit/ad target still fills.
            backoff = min(90.0, 25.0 + slot_fails * 4.0) * rng.uniform(0.9, 1.15)
            logger.warning(
                "[%s] FAIL after %d retries — re-pick seq for same slot in %.0fs "
                "(visit not counted; keep daily numbers on target)",
                phone,
                FAIL_RETRY_MAX,
                backoff,
            )
            slot_fails = 0
            if stop_event.wait(backoff):
                break
            continue

        # OK — count toward daily budget and advance the hour slot.
        # Path3 with forced click_url open failed (house/bot / NO click_url): refund
        # the farm-wide reserve and skip phone day_ads — house filter stays on.
        count_as_path3_ad = bool(is_path3)
        if is_path3 and path3_reserved and entry.get("path3_click_open") is False:
            path3_nobill_streak += 1
            try:
                with lock:
                    _unreserve_path3_today()
                entry["path3_quota_refunded"] = True
                entry["path3_billable"] = False
                count_as_path3_ad = False
                path3_reserved = False
                state_now = _load_path3_daily_state()
                logger.info(
                    "[%s] Path3 reserve refunded after non-billable OK "
                    "(house/bot or NO click_url) farm=%s/%s streak=%d",
                    phone,
                    state_now.get("count"),
                    _path3_farm_daily_cap(),
                    path3_nobill_streak,
                )
                if path3_nobill_streak >= 8:
                    # Catch-up: do not park Path3 for 30–60 min after house-classified fills.
                    backoff_min = rng.uniform(3.0, 6.0)
                    entry["path3_house_backoff_min"] = round(backoff_min, 1)
                    entry["path3_house_backoff_scope"] = "path3_only"
                    path3_cooldown_until = time.time() + backoff_min * 60.0
                    path3_nobill_streak = 0
                    logger.warning(
                        "[%s] Path3 house/bot streak=8 — Path3-only cooldown "
                        "%.0f min (Path1/2 continue; no phone-wide sleep)",
                        phone,
                        backoff_min,
                    )
            except Exception as exc:
                logger.warning("[%s] Path3 non-billable unreserve soft-fail: %s", phone, exc)
        elif is_path3:
            path3_nobill_streak = 0
            entry["path3_billable"] = entry.get("path3_click_open") is not False
        slot_fails = 0
        done += 1
        hour_seq_idx += 1
        try:
            row = _record_phone_visit(phone_idx, path3=count_as_path3_ad)
            entry["day_visits"] = row["visits"]
            entry["day_ads"] = row["ads"]
            if not is_tablet_phone(phone):
                try:
                    if record_phone_visit_ok():
                        logger.info(
                            "[%s] tablet visit queued (every %d phone OK visits)",
                            phone,
                            tablet_every_n(),
                        )
                except Exception as exc:
                    logger.debug("[%s] tablet schedule soft-fail: %s", phone, exc)
            logger.info(
                "[%s] daily budget visits=%d/%d ads=%d/%d",
                phone,
                row["visits"],
                _phone_visits_cap(phone_idx) or 0,
                row["ads"],
                _phone_ads_cap(phone_idx) or 0,
            )
        except Exception as exc:
            logger.warning("[%s] daily budget record soft-fail: %s", phone, exc)
        recent.append(path.stem)
        with lock:
            seq_lock.release(reserved_keys)
            logger.info(
                "unique-seq lock: release %s keys=%s",
                path.stem,
                sorted(reserved_keys),
            )
            # Draw-without-replacement: mark non-ad stems used only after OK.
            if not is_path3:
                used_stems.add(path.stem)
            recent_stems.append(path.stem)
            if len(recent_stems) > 48:
                del recent_stems[:-36]
            if combo:
                recent_combos.append("|".join(combo))
                if len(recent_combos) > 40:
                    del recent_combos[:-30]
            if ad_key:
                recent_ad_keys.append(ad_key)
                if len(recent_ad_keys) > 40:
                    del recent_ad_keys[:-30]
                logger.info("[%s] ad_key=%s (recent=%s)", phone, ad_key, recent_ad_keys[-6:])
            if combo:
                logger.info("[%s] combo=%s/%s/%s", phone, combo[0], combo[1], combo[2])
            progress[phone] = {"done": done, "last": entry}
            with open(results_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        kind = "P3-AD" if is_path3 else ("P2" if "halfway" in path.stem else "P1")
        if is_path3 and entry.get("path3_quota_refunded"):
            logger.info(
                "[%s] %d %s OK-nobill %s %.1fs (quota refunded)",
                phone,
                n,
                kind,
                path.stem,
                entry["elapsed_s"],
            )
        else:
            logger.info(
                "[%s] %d %s OK %s %.1fs", phone, n, kind, path.stem, entry["elapsed_s"]
            )
        # No fixed post-run idle — next loop waits for the next scheduled slot.
        # Path3 house/bot streak uses path3_cooldown_until (Path3 skip only).


def _ensure_tablet_wm(farm: MuMuFarmOps, serial: str, phone: str) -> tuple[bool, str]:
    """Portrait fix before unique display — tablet vm2 was stuck landscape."""
    ok_portrait, portrait_size = ensure_portrait_display(
        farm.adb, serial, phone=phone
    )
    if not ok_portrait:
        return False, portrait_size or "portrait fix failed"
    ok, got = ensure_unique_display(farm.adb, serial, phone=phone, scramble=False)
    last = (farm.adb.shell("wm size", serial=serial, timeout=8.0).stdout or "").strip()
    if ok and _wm_size_ok(last or got):
        return True, last or got
    return False, last or got or "tablet wm bad"


def _tablet_worker(
    phone: str,
    pools: dict[str, list[Path]],
    farm: MuMuFarmOps,
    runner: SequenceRunner,
    *,
    results_path: Path,
    progress: dict,
    lock: threading.Lock,
    stop_event: threading.Event,
    seq_lock: UniqueSequenceLock,
    used_stems: set[str],
    recent_stems: list[str],
) -> None:
    """Run one Path1/2 sequence on tablet when global phone OK counter hits threshold."""
    rng = random.Random(os.urandom(16) + b"tablet")
    done = 0
    logger.info("[tablet] worker ready phone=%s every_n=%d", phone, tablet_every_n())
    inst = farm.get_phone(phone)
    if inst and inst.adb_serial:
        ok, size = _ensure_tablet_wm(farm, inst.adb_serial, phone)
        logger.info("[tablet] init wm portrait=%s ok=%s", size, ok)

    while not stop_event.is_set() and not _stop_requested():
        if not wait_tablet_due(45.0):
            continue
        if not consume_tablet_pending():
            continue
        if stop_event.is_set():
            break

        path: Path | None = None
        reserved_keys: set[str] = set()
        with lock:
            for _ in range(24):
                cand = _pick(
                    pools,
                    want_ads=False,
                    rng=rng,
                    active_keys=seq_lock.active,
                    used_stems=used_stems,
                    last_ad=[None],
                    recent=[],
                    recent_ad_keys=[],
                    recent_combos=[],
                    recent_stems=recent_stems,
                )
                if cand is None:
                    break
                err = _preflight(cand, strict=True)
                if err:
                    continue
                keys = _identity_keys(cand.stem)
                if not seq_lock.try_reserve(keys):
                    continue
                path = cand
                reserved_keys = keys
                break

        if path is None:
            logger.warning("[tablet] no unique sequence — will retry on next due")
            continue

        entry: dict = {
            "time": _utc(),
            "phone": phone,
            "role": "tablet",
            "path": path.as_posix(),
            "sequence": path.stem,
        }
        t0 = time.time()
        try:
            inst = farm.get_phone(phone)
            if inst and inst.adb_serial:
                ok, size = _ensure_tablet_wm(farm, inst.adb_serial, phone)
                entry["wm_size"] = size
                if not ok:
                    raise RuntimeError(f"tablet bad wm size {size!r}")
            seq = Sequence.from_json(path)
            seq.phone = phone
            report = runner.run(seq)
            entry["success"] = bool(report.get("success"))
            entry["error"] = report.get("error")
        except Exception as exc:
            entry["success"] = False
            entry["error"] = str(exc)
        entry["elapsed_s"] = round(time.time() - t0, 1)

        ok = bool(entry.get("success"))
        with lock:
            seq_lock.release(reserved_keys)
            if ok:
                used_stems.add(path.stem)
                recent_stems.append(path.stem)
                if len(recent_stems) > 48:
                    del recent_stems[:-36]
                record_tablet_visit_ok()
                done += 1
            progress[phone] = {"done": done, "last": entry, "role": "tablet"}
            with open(results_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        logger.info(
            "[tablet] %s %s %.1fs err=%s",
            "OK" if ok else "FAIL",
            path.stem,
            entry["elapsed_s"],
            (entry.get("error") or "")[:80],
        )


def main() -> int:
    log_path = logs_dir() / "farm_354.log"
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    # Replace handlers so Tor/rotate IP lines always land in farm_354.log.
    for h in list(root.handlers):
        root.removeHandler(h)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(sh)
    root.addHandler(fh)
    logging.getLogger("farm_354").info(
        "farm logging ready path=%s unique_exit_ip=%s browse=%s",
        log_path,
        os.environ.get("PHARMFLOW_REQUIRE_UNIQUE_EXIT_IP", "1"),
        os.environ.get("PHARMFLOW_BROWSE_PROXY_MODE", ""),
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-phone", type=int, default=TARGET_PER_PHONE)
    parser.add_argument(
        "--hours",
        type=float,
        default=None,
        help="Stop after this many hours. 0 = day mode (no cycle; run on daily visit/ad caps).",
    )
    parser.add_argument(
        "--phones",
        nargs="*",
        default=None,
        help="Optional preference order. Farm always adapts to live ADB phones "
        "(never hardcodes VMs; tablet excluded).",
    )
    args = parser.parse_args()
    requested_phones = [
        str(p).strip().lstrip("\ufeff")
        for p in (args.phones or [])
        if str(p).strip()
    ]

    if not sequences_run_allowed():
        print("ERROR: set PHARMFLOW_ALLOW_SEQUENCE_RUNS=1")
        return 1

    per_phone = int(args.per_phone)
    hours_raw = (
        args.hours
        if args.hours is not None
        else float(os.environ.get("PHARMFLOW_FARM_HOURS") or "0")
    )
    # Per-day budgets replace hour cycles. hours<=0 OR daily caps set → day mode.
    day_mode = bool(_DAILY_BUDGET_ENABLED) or float(hours_raw) <= 0
    hours = 0.0 if day_mode else float(hours_raw)
    if day_mode:
        # No cycle deadline — phones idle at daily caps until midnight, then resume.
        deadline_ts = time.time() + 3650.0 * 24 * 3600.0
        logger.info(
            "DAY MODE — no hour cycle; pacing by daily_visits=%s daily_ads=%s (midnight reset)%s",
            DAILY_VISITS,
            DAILY_ADS,
            (
                f"; EVENING FILL {EVENING_SEQS_PER_HOUR}/hr/phone until midnight"
                f" (until={EVENING_UNTIL or 'today'})"
                if _evening_fill_active()
                else ""
            ),
        )
    else:
        deadline_ts = time.time() + hours * 3600.0

    farm = MuMuFarmOps()
    # Self-heal (1): the ADB server must be up before discovery. MuMu / Studio /
    # docker devices are useless while the bus is down; `adb start-server` is
    # idempotent and never touches VMs.
    try:
        farm.adb.run("start-server")
        logger.info("adb server ensured (start-server ok)")
    except Exception as exc:
        logger.warning("adb start-server failed: %s", exc)
    # Self-heal (2): reap orphaned Tor instances from a previous farm restart.
    # A dead lane leaves its fleet squatting the canonical HTTP/SOCKS/Control
    # bases; the next lane shifts to dead ports and every sequence dies at
    # isolation. Reap orphans at startup so the phone proxy pin is never dead.
    try:
        n = _reap_orphan_tor()
        if n:
            logger.info("TOR REAP: %d orphan tor instance(s) reaped at startup", n)
    except Exception as exc:  # noqa: BLE001
        logger.warning("TOR REAP failed: %s", exc)
    fast_boot = os.environ.get("PHARMFLOW_FAST_STICKY_BOOT", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    if fast_boot and _lock_boot_ready(farm):
        logger.info("boot fast sticky — skip initial list_instances/mpid scan")
        try:
            farm.refresh_serials()
        except Exception as exc:
            logger.warning("refresh_serials failed: %s", exc)
    else:
        try:
            farm.list_instances()
        except Exception as exc:
            logger.warning("list_instances failed: %s", exc)
        try:
            farm.refresh_serials()
        except Exception as exc:
            logger.warning("refresh_serials failed: %s", exc)

    fixed_lock = sanitize_lock_file_portrait_only()
    if fixed_lock:
        logger.warning("sanitized %d landscape row(s) in farm_display_resolutions.json", fixed_lock)

    preferred = requested_phones or _sticky_phone_preference()
    try:
        available = _discover_available_phones(
            farm, include_names=set(preferred) if preferred else None
        )
        phones = _order_phones(available, preferred=preferred)
    except Exception as exc:
        # Discovery breakage (adb bus wedged, stale lock, no devices) must
        # degrade to the standby scan below — never crash the farm lane.
        logger.warning("phone discovery failed: %s", exc)
        available = {}
        phones = []
    if preferred:
        missing = [p for p in preferred if p not in set(available)]
        if missing:
            # Rewire before adapting away: reconnect known serials + ARM
            # host ports, then re-discover so a phone that dropped off the
            # ADB bus comes back instead of being silently discarded.
            try:
                reattached = _rewire_missing_phones(farm, missing)
                if reattached:
                    logger.info("REWIRE: %d phone(s) reattached: %s", len(reattached), ",".join(reattached))
                    available = _discover_available_phones(
                        farm, include_names=set(preferred) if preferred else None
                    )
                    phones = _order_phones(available, preferred=preferred)
            except Exception as exc:
                logger.warning("rewire pass failed (continuing): %s", exc)
            missing = [p for p in preferred if p not in set(available)]
        if missing:
            logger.warning(
                "sticky phones offline (adapted away after rewire): %s",
                ",".join(missing),
            )
    if not phones:
        # Zero phones is a standby state, not a crash: keep scanning ADB for
        # any emulator/device to appear (MuMu, Android Studio AVD, docker,
        # cloud) instead of exiting non-zero and crash-looping under unison.
        # Bounded by PHARMFLOW_WAIT_PHONES_MIN (default 20); exit 2 = still none.
        try:
            wait_min = float(os.environ.get("PHARMFLOW_WAIT_PHONES_MIN", "20").strip() or 0)
        except (TypeError, ValueError):
            wait_min = 20.0
        phone_deadline = time.time() + max(0.0, wait_min) * 60.0
        logger.warning(
            "no online farm phones (ADB) — scanning every 30s for devices (up to %.0f min; PHARMFLOW_WAIT_PHONES_MIN to change)",
            wait_min,
        )
        while not _stop_requested() and time.time() < phone_deadline:
            time.sleep(30)
            try:
                farm.refresh_serials()
            except Exception as exc:
                logger.debug("phone scan refresh failed: %s", exc)
            try:
                available = _discover_available_phones(
                    farm, include_names=set(preferred) if preferred else None
                )
            except Exception as exc:
                logger.warning("phone scan discover failed: %s", exc)
                continue
            phones = _order_phones(available, preferred=preferred)
            if phones:
                logger.info(
                    "phones appeared after %.0fs: %s",
                    time.time() - (phone_deadline - wait_min * 60.0),
                    phones,
                )
                break
        if not phones:
            logger.error("still no online farm phones after %.0fs wait — farm standing by", wait_min * 60.0)
            return 2
    args.phones = phones
    _persist_live_phones(phones, farm)
    logger.info(
        "ADAPTIVE PHONES online=%d phones=%s (preferred_hint=%s)",
        len(phones),
        phones,
        preferred or "(none)",
    )

    online: list[tuple[str, int]] = []
    for roster_i, name in enumerate(phones):
        inst = farm.get_phone(name)
        st = farm.get_phone_status(name) if inst else {}
        if inst and st.get("connected"):
            # Absolute phone number (vm22 → 22), NOT roster position: Tor lanes,
            # inject proxies and guest proxy pins are all keyed by the absolute
            # index. Roster enumerate() here fed exit_ip_guard roster idx 0..6,
            # so it probed ports belonging to nobody — "fetch_exit_ip failed
            # phone=0 ... 8138 refused" while every lane actually listened.
            stem = name.split(".", 1)[0]
            # Absolute vm index only. roster enumerate() for a leftover
            # serial (adb-10.0.2.141) becomes idx 7, sorts before vm39, and
            # shifts every phone onto a Tor port nobody is listening on.
            if not (stem.startswith("vm") and stem[2:].isdigit()):
                logger.warning(
                    "ONLINE %s serial=%s has no vm index — excluded from Tor slot map",
                    name,
                    inst.adb_serial,
                )
                continue
            idx = int(stem[2:])
            online.append((name, idx))
            logger.info("ONLINE %s serial=%s idx=%d", name, inst.adb_serial, idx)
        else:
            logger.error("OFFLINE %s - skipping (should not happen after discover)", name)

    if not online:
        print("ERROR: no online phones after adapt")
        return 1

    # Money path: farm MUST own absolute inject listeners (vm24→8242). Stealth
    # stands down while farm is alive; without this arm, phones stay pinned to
    # dead ports and bottom ads die. Re-arm at boot; keepalive child holds ports.
    try:
        _ensure_farm_inject(farm, online)
    except Exception as exc:  # noqa: BLE001
        logger.warning("farm inject arm failed: %s", exc)

    # HARD RULE: no two concurrent phones may share the same public exit IP.
    try:
        from automation.exit_ip_guard import enforce_farm_unique_exit_ips, phone_rows_from_farm_ops

        ip_rows = phone_rows_from_farm_ops(farm, online)
        if ip_rows:
            ip_fixes = enforce_farm_unique_exit_ips(farm.tor, farm.adb, ip_rows)
            for fx in ip_fixes:
                logger.info("exit_ip_guard: %s", fx)
    except Exception as exc:
        logger.warning("exit_ip_guard startup failed: %s", exc)

    # New / wiped phones must have Path1/2 browsers sideloaded before farming.
    # Default ON — set PHARMFLOW_REQUIRE_FARM_BROWSERS=0 only for emergency bypass.
    require_browsers = os.environ.get("PHARMFLOW_REQUIRE_FARM_BROWSERS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    if require_browsers:
        serials_for_browsers: list[str] = []
        name_by_serial: dict[str, str] = {}
        for name, _idx in online:
            inst = farm.get_phone(name)
            if inst and inst.adb_serial:
                serials_for_browsers.append(inst.adb_serial)
                name_by_serial[inst.adb_serial] = name
        if serials_for_browsers:
            logger.info(
                "browser sideload gate: ensuring Path1/2 APKs on %d phone(s) before farm",
                len(serials_for_browsers),
            )
            try:
                browser_gate = ensure_missing_farm_browsers_on_serials(
                    farm.adb,
                    serials_for_browsers,
                    progress_cb=lambda msg: logger.info("browser gate: %s", msg),
                )
            except Exception as exc:
                logger.error("browser sideload gate failed: %s", exc)
                browser_gate = {"ok": False, "still_missing": {s: ["gate_error"] for s in serials_for_browsers}}
            still = browser_gate.get("still_missing") or {}
            if still:
                blocked = set()
                for serial, pkgs in still.items():
                    phone = name_by_serial.get(serial, serial)
                    logger.error(
                        "BLOCK %s serial=%s — missing browsers %s (sideload before farm)",
                        phone,
                        serial,
                        pkgs,
                    )
                    blocked.add(phone)
                online = [(n, i) for n, i in online if n not in blocked]
            else:
                logger.info(
                    "browser sideload gate OK required=%s",
                    browser_gate.get("required"),
                )
            # Persist gate result for dash/operators.
            try:
                gate_path = logs_dir() / "farm_browser_sideload_gate.json"
                gate_path.write_text(
                    json.dumps(
                        {
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "required": browser_gate.get("required"),
                            "still_missing": still,
                            "per_phone": browser_gate.get("per_phone"),
                            "ok": bool(browser_gate.get("ok")),
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            except OSError as exc:
                logger.debug("browser gate status write failed: %s", exc)
        if not online:
            print("ERROR: no phones with required browsers sideloaded")
            return 1

    # Place phones where local time is currently 09:30–midnight (awake hours on Earth).
    # Skip on soft restart — isolate_before_sequence applies fresh geo every seq;
    # sequential boot geo was 3–4 minutes of dead wall clock (actives=0 stagnation).
    skip_boot_geo = os.environ.get("PHARMFLOW_SKIP_BOOT_GEO", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if skip_boot_geo:
        logger.info("SKIP boot geo (PHARMFLOW_SKIP_BOOT_GEO=1) — per-seq isolate owns geo")
    else:
        try:
            serials: list[str] = []
            for name, _idx in online:
                inst = farm.get_phone(name)
                if inst and inst.adb_serial:
                    serials.append(inst.adb_serial)
            assigned = apply_geo_window_to_serials(farm.adb, serials)
            for serial, loc in assigned:
                logger.info(
                    "GEO %s -> %s tz=%s (local awake window 09:30–00:00)",
                    serial,
                    loc.label,
                    loc.tz,
                )
        except Exception as exc:
            logger.warning("geo time-window apply failed: %s", exc)

    seq_root = _sequence_root()
    files = discover_sequence_files(seq_root)
    live_serials: list[str] = []
    for name, _idx in online:
        inst = farm.get_phone(name)
        ser = str(getattr(inst, "adb_serial", "") or "").strip() if inst else ""
        if ser:
            live_serials.append(ser)
    playlist_files, playlist_notes = _playlist_files_for_serials(live_serials)
    if playlist_files:
        have = {str(path.resolve()).lower() for path in files}
        for path in playlist_files:
            token = str(path.resolve()).lower()
            if token not in have:
                files.append(path)
                have.add(token)
    logger.info(
        "sequence root=%s groups=%s site=%s",
        seq_root,
        groups_config_path(),
        os.environ.get("PHARMFLOW_SITE_SLUG", "dabflow"),
    )
    for note in playlist_notes:
        logger.info("playlist %s", note)
    pools = _classify(files)
    logger.info(
        "farm mode paths=%s ads_allowed=%s pacing=daily_visits÷hours_left "
        "daily_visits=%s daily_ads=%s hours=%.1f",
        sorted(_farm_paths()),
        _ads_allowed(),
        DAILY_VISITS,
        DAILY_ADS,
        hours,
    )
    logger.info(
        "pools discovered ad=%d complete=%d halfway=%d",
        len(pools["ad"]),
        len(pools["complete"]),
        len(pools["halfway"]),
    )
    rejected, quarantined = _filter_pools(pools)
    logger.info(
        "preflight OK rejected=%d quarantined=%d ad=%d complete=%d halfway=%d (author %dx%d, timer>=%ss)",
        rejected,
        len(quarantined),
        len(pools["ad"]),
        len(pools["complete"]),
        len(pools["halfway"]),
        AUTHOR_W,
        AUTHOR_H,
        int(TIMER_WAIT_MIN),
    )
    if not (pools["complete"] or pools["halfway"]):
        print("ERROR: missing sequence pools (need complete and/or halfway)")
        return 1
    if _ads_allowed() and not pools["ad"]:
        print("ERROR: ads enabled but ad pool is empty")
        return 1

    results_path = logs_dir() / "farm_354_results.jsonl"
    progress_path = logs_dir() / "farm_354_progress.json"
    results_path.write_text("", encoding="utf-8")
    # Write deadline immediately so dash does not show stale "cycle overdue" warning.
    progress_path.write_text(
        json.dumps(
            {
                "updated": _utc(),
                "hours": hours,
                "day_mode": day_mode,
                "deadline": (
                    "midnight-daily"
                    if day_mode
                    else datetime.fromtimestamp(deadline_ts, tz=timezone.utc).isoformat()
                ),
                "phones": {},
                "active_sequences": [],
                "active_keys": [],
                "unique_seq_lock": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    progress: dict = {}
    lock = threading.Lock()
    stop = threading.Event()
    # Farm-wide in-flight identity reservation (file stem + ad slot).
    seq_lock = UniqueSequenceLock()
    # Draw-without-replacement ledger for non-ad sequences (survives restarts).
    used_stems: set[str] = _load_used_stems()
    # Farm-wide last dispatched ad stem — blocks back-to-back same ad.
    last_ad: list[str | None] = [None]
    recent_ad_keys: list[str] = []
    recent_combos: list[str] = []
    recent_stems: list[str] = []
    runner = SequenceRunner(farm)
    nonad_total = len(pools["complete"]) + len(pools["halfway"])
    logger.info(
        "unique-seq lock ACTIVE — hard refuse concurrent file:/ad: identity keys "
        "(6 phones => 6 different sequences)"
    )
    logger.info(
        "draw-without-replacement ACTIVE — non-ad pool=%d already-used=%d "
        "(no repeat until whole pool runs once); ads random, no concurrent/back-to-back repeat",
        nonad_total,
        len(used_stems),
    )

    start_rng = random.Random(os.urandom(16))
    start_delays = _random_phone_start_delays(len(online), start_rng)
    delay_by_phone = {phone: start_delays[i] for i, (phone, _idx) in enumerate(online)}
    logger.info(
        "random start stagger window=%.0fs min_gap=%.0fs delays=%s",
        START_STAGGER_WINDOW_S,
        START_STAGGER_MIN_GAP_S,
        {p: round(d, 1) for p, d in delay_by_phone.items()},
    )

    def make_worker(phone: str, idx: int) -> threading.Thread:
        def run() -> None:
            _worker(
                phone,
                idx,
                pools,
                farm,
                runner,
                results_path=results_path,
                progress=progress,
                lock=lock,
                stop_event=stop,
                per_phone=per_phone,
                seq_lock=seq_lock,
                used_stems=used_stems,
                last_ad=last_ad,
                recent_ad_keys=recent_ad_keys,
                recent_combos=recent_combos,
                recent_stems=recent_stems,
                deadline_ts=deadline_ts,
                start_delay_s=delay_by_phone.get(phone, 0.0),
            )

        return threading.Thread(target=run, name=f"farm-{phone}", daemon=True)

    # Shuffle thread start order so launch itself isn't vm0→vm3.
    online_shuffled = list(online)
    start_rng.shuffle(online_shuffled)
    threads = [make_worker(phone, idx) for phone, idx in online_shuffled]
    logger.info(
        "START %d phones %s (pace from daily visits/ads scattered thru day)",
        len(threads),
        "DAY MODE (daily budgets, no cycle)" if day_mode else f"for {hours:.1f}h",
    )
    for t in threads:
        t.start()

    tablet_thread: threading.Thread | None = None
    t_phone, t_serial = resolve_tablet_serial(farm)
    if t_phone and t_serial:
        logger.info(
            "tablet ONLINE phone=%s serial=%s every_n=%d (Path1/2 only)",
            t_phone,
            t_serial,
            tablet_every_n(),
        )

        def _run_tablet() -> None:
            _tablet_worker(
                t_phone,
                pools,
                farm,
                runner,
                results_path=results_path,
                progress=progress,
                lock=lock,
                stop_event=stop,
                seq_lock=seq_lock,
                used_stems=used_stems,
                recent_stems=recent_stems,
            )

        tablet_thread = threading.Thread(target=_run_tablet, name="farm-tablet", daemon=True)
        tablet_thread.start()
    elif t_phone:
        logger.info(
            "tablet configured (%s) but not ADB-visible — phones continue without blocking",
            t_phone,
        )

    all_threads = list(threads)
    if tablet_thread is not None:
        all_threads.append(tablet_thread)

    # Self-heal (spin-up only, farm already running): the EXE never launches
    # emulators before the operator starts the farm, and it never reboots the
    # program. But once this farm run is live, a phone that was ONLINE at farm
    # start and then dies is spun back up (VM only, 120s cooldown, never a
    # whole-program or whole-farm restart). Synthetic devices (AVD/docker/
    # cloud) and phones that were never online at start are never touched.
    heal_last: dict[str, float] = {}
    try:
        while any(t.is_alive() for t in all_threads):
            if _stop_requested():
                logger.info("Farm stop requested by EXE — signaling workers")
                stop.set()
            if not day_mode and time.time() >= deadline_ts:
                logger.info("Global duration %.1fh reached — signaling stop", hours)
                stop.set()
            now_ts = time.time()
            try:
                live_serials = {
                    d.serial
                    for d in farm.enumerate_adb_devices()
                    if getattr(d, "online", False)
                }
            except Exception:
                live_serials = set()
            for phone, _pidx in list(online):
                if not phone.startswith("vm") or ".gmadoa" not in phone:
                    continue
                if now_ts - heal_last.get(phone, 0.0) < 120.0:
                    continue
                try:
                    inst = farm.get_phone(phone)
                except Exception:
                    inst = None
                if not inst or not inst.adb_serial:
                    continue
                if inst.adb_serial in live_serials:
                    continue
                # Host-wedge guard: an empty ADB list is not proof the server is
                # dead. kill-server drops every live phone. start-server only,
                # then reconnect known serials before churning any VM.
                if not live_serials:
                    try:
                        logger.warning(
                            "SELF-HEAL %s: zero live ADB devices — start-server + reconnecting fleet (no kill-server)",
                            phone,
                        )
                        farm.adb.run("start-server", timeout=20.0)
                        farm._reconnect_known_serials()
                        live_serials = {
                            d.serial
                            for d in farm.enumerate_adb_devices(force=True)
                            if getattr(d, "online", False)
                        }
                    except Exception as exc:
                        logger.warning("SELF-HEAL server restart failed: %s", exc)
                    if inst.adb_serial in live_serials:
                        logger.info("SELF-HEAL %s recovered via server restart (no VM churn)", phone)
                        continue
                heal_last[phone] = now_ts
                logger.warning(
                    "SELF-HEAL %s offline (serial=%s) — spinning its VM back up",
                    phone,
                    inst.adb_serial,
                )
                try:
                    # Scaling-plan gate: same host-health rule as EXE boot —
                    # wait for RAM/CPU headroom before respawning a VM so a
                    # spin-up never wedges the other live earners. Host-health
                    # only; there is no phone-count cap anywhere.
                    if not boot_gates.wait_for_boot_headroom(
                        label=phone,
                        timeout_s=300.0,
                    ):
                        logger.warning(
                            "SELF-HEAL %s deferred — host headroom gate timed out; will retry next cycle",
                            phone,
                        )
                        heal_last.pop(phone, None)
                        continue
                    farm.start_phone(phone)
                except Exception as exc:
                    logger.warning("SELF-HEAL %s spin-up failed: %s", phone, exc)
            with lock:
                snap = {k: v.get("done", 0) for k, v in progress.items()}
                active_keys = seq_lock.active
                active = sorted(k for k in active_keys if k.startswith("file:"))
                active_files = [k.removeprefix("file:") for k in active]
                _save_used_stems(used_stems)
                progress_path.write_text(
                    json.dumps(
                        {
                            "updated": _utc(),
                            "hours": hours,
                            "day_mode": day_mode,
                            "deadline": (
                                "midnight-daily"
                                if day_mode
                                else datetime.fromtimestamp(
                                    deadline_ts, tz=timezone.utc
                                ).isoformat()
                            ),
                            "phones": progress,
                            "active_sequences": active_files,
                            "active_keys": sorted(active_keys),
                            "unique_seq_lock": True,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            logger.info("progress %s active=%s", snap, active_files)
            time.sleep(30)
    except KeyboardInterrupt:
        stop.set()
        logger.warning("interrupt — stopping workers")

    for t in all_threads:
        t.join(timeout=120)
    with lock:
        _save_used_stems(used_stems)
    logger.info(
        "FARM COMPLETE results=%s used_pass=%d",
        results_path,
        len(used_stems),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
