#!/usr/bin/env python3
"""EXE Start-farm gate: refuse unless phones are stealth AND funds-ready.

Hard rule (operator): farm must not Start when stealth or income checks fail.
This module is read-only against ADB/prefs/logs — it never starts sequences.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_TOOLS_DIR = Path(__file__).resolve().parent
_ROOT = _TOOLS_DIR.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

LogFn = Callable[[str], None]


def _logs_dir() -> Path:
    env = (os.environ.get("PHARMFLOW_LOG_DIR") or "").strip()
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "logs"
    return Path(r"C:\PharmFlow\logs")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _desktop_prefs() -> dict[str, Any]:
    try:
        from wizard.wizard_paths import desktop_prefs_file

        return _read_json(desktop_prefs_file())
    except Exception:
        return {}


def _discover_phones(log: LogFn | None = None) -> list[str]:
    """Local MuMu/ADB + published redroid/cloud TCP serials already on the bus."""
    try:
        from wizard.preflight_core import discover_adb_phones

        phones = discover_adb_phones(log, connect_mumu=True, force_mumu_scan=False)
        return [str(s).strip() for s in (phones or []) if str(s).strip()]
    except Exception as exc:  # noqa: BLE001
        if log:
            log(f"phone discover failed: {exc}")
        return []


def _stealth_audit(serials: list[str], log: LogFn | None = None) -> dict[str, Any]:
    if not serials:
        return {
            "ok": False,
            "phones": 0,
            "phones_with_leaks": 0,
            "leaks_total": 0,
            "all_clean": False,
            "error": "No phones answering ADB",
        }
    try:
        from wizard.mumu_farm_ops import audit_fingerprint_all

        summary = audit_fingerprint_all(serials, log)
        return {
            "ok": bool(summary.get("all_clean")),
            "phones": int(summary.get("phones") or 0),
            "phones_with_leaks": int(summary.get("phones_with_leaks") or 0),
            "leaks_total": int(summary.get("leaks_total") or 0),
            "all_clean": bool(summary.get("all_clean")),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "phones": len(serials),
            "phones_with_leaks": len(serials),
            "leaks_total": 0,
            "all_clean": False,
            "error": f"stealth audit failed: {exc}",
        }


def _funds_snapshot() -> dict[str, Any]:
    logs = _logs_dir()
    health = _read_json(logs / "FARM_MONEY_HEALTH.json")
    mantis = _read_json(logs / "mantis_today_state.json")
    payout = 0.0
    impressions = 0
    clicks = 0
    for src in (health, mantis):
        try:
            if src.get("payout_usd") is not None:
                payout = max(payout, float(src.get("payout_usd") or 0))
        except (TypeError, ValueError):
            pass
        try:
            if src.get("impressions") is not None:
                impressions = max(impressions, int(src.get("impressions") or 0))
        except (TypeError, ValueError):
            pass
        try:
            if src.get("clicks") is not None:
                clicks = max(clicks, int(src.get("clicks") or 0))
        except (TypeError, ValueError):
            pass
    money_ok_flag = health.get("money_ok")
    generating = bool(
        (money_ok_flag is True)
        or payout > 0
        or impressions > 0
        or clicks > 0
    )
    explicit_fail = bool(health) and money_ok_flag is False and not generating
    return {
        "payout_usd": payout,
        "impressions": impressions,
        "clicks": clicks,
        "money_ok_flag": money_ok_flag,
        "health_present": bool(health),
        "mantis_present": bool(mantis),
        "generating": generating,
        "explicit_fail": explicit_fail,
        "billing_direct": (os.environ.get("PHARMFLOW_MANTIS_BILLING_DIRECT") or "0").strip(),
    }


def _income_path_ready(prefs: dict[str, Any]) -> tuple[bool, list[str]]:
    problems: list[str] = []
    billing = (os.environ.get("PHARMFLOW_MANTIS_BILLING_DIRECT") or "0").strip()
    if billing not in ("", "0", "false", "False", "no", "NO"):
        problems.append("billing_direct is on — host-IP clicks pay $0")
    try:
        try:
            from wizard.site_prefs import load_target_site_url
        except ImportError:  # frozen/deck path may expose site_prefs flat
            from site_prefs import load_target_site_url  # type: ignore[no-redef]

        site = (load_target_site_url() or "").strip()
    except Exception:
        site = ""
    if not site:
        problems.append("target site URL is not saved")
    if prefs.get("dabflow_mantis_patch") is False:
        problems.append("dabflow_mantis_patch is off")
    if prefs.get("mask_emulator_fingerprint") is False:
        problems.append("mask_emulator_fingerprint is off")
    return (not problems), problems


def evaluate_start_gate(
    *,
    serials: list[str] | None = None,
    log: LogFn | None = None,
    apply_stealth_defaults: bool = True,
    skip_audit: bool = False,
) -> dict[str, Any]:
    """Return ok=True only when stealth AND funds checks both pass.

    ``skip_audit=True`` skips the slow fingerprint round-trip (Control Panel
    fast dump). Funds/path checks still run. Never starts the farm.
    """
    prefs = _desktop_prefs()
    if apply_stealth_defaults and prefs.get("mask_emulator_fingerprint") is not True:
        # Soft default: treat missing as True; explicit False is a gate fail
        # (reported in income_path). Do not rewrite prefs from the gate.
        pass

    gate_stop = _logs_dir() / "FARM_STEALTH_GATE_STOP.json"
    if gate_stop.is_file():
        return {
            "ok": False,
            "stealth_ok": False,
            "funds_ok": False,
            "error": "Stealth gate stop file is set (FARM_STEALTH_GATE_STOP.json) — Start farm refused.",
            "phones": [],
            "phone_count": 0,
            "stealth": {},
            "funds": _funds_snapshot(),
            "audit_skipped": bool(skip_audit),
        }

    phones = list(serials) if serials is not None else _discover_phones(log)
    if skip_audit:
        stealth = {
            "ok": True,
            "phones": len(phones),
            "phones_with_leaks": 0,
            "leaks_total": 0,
            "all_clean": True,
            "skipped": True,
        }
    else:
        stealth = _stealth_audit(phones, log)
    stealth_ok = bool(phones) and bool(stealth.get("all_clean")) and not stealth.get("error")

    path_ok, path_problems = _income_path_ready(prefs)
    funds = _funds_snapshot()
    # Funds: money path must be ready. Explicit money_ok=False with no
    # generating evidence refuses Start. Proven payout/impr/clicks passes.
    # No health/mantis yet → path_ok alone (first arm) so phones can earn.
    if funds.get("explicit_fail"):
        funds_ok = False
        funds_reason = "FARM_MONEY_HEALTH says money_ok=false (not generating funds)"
    elif funds.get("generating"):
        funds_ok = path_ok
        funds_reason = "funds generating" if path_ok else "; ".join(path_problems)
    else:
        funds_ok = path_ok
        funds_reason = (
            "income path ready (no funds proof yet — first arm)"
            if path_ok
            else "; ".join(path_problems)
        )

    ok = bool(stealth_ok and funds_ok)
    errors: list[str] = []
    if not phones:
        errors.append("no phones answering ADB (local MuMu/redroid/cloud)")
    elif not stealth_ok:
        if stealth.get("error"):
            errors.append(str(stealth["error"]))
        else:
            errors.append(
                f"stealth fail: {stealth.get('phones_with_leaks', 0)} phone(s) "
                f"still leak emulator identity ({stealth.get('leaks_total', 0)} leak(s))"
            )
    if not funds_ok:
        errors.append(funds_reason or "funds check failed")

    if ok and skip_audit:
        message = "Start farm gate OK — funds-ready (fingerprint audit skipped)."
    elif ok:
        message = "Start farm gate OK — stealth clean and funds-ready."
    else:
        message = "Start farm refused: " + "; ".join(errors)
    return {
        "ok": ok,
        "stealth_ok": stealth_ok,
        "funds_ok": funds_ok,
        "error": None if ok else message,
        "message": message,
        "phones": phones,
        "phone_count": len(phones),
        "stealth": stealth,
        "funds": {**funds, "path_ok": path_ok, "path_problems": path_problems, "reason": funds_reason},
        "prefer_newest_build": True,
        "audit_skipped": bool(skip_audit),
    }


def dump_gate_status_fast(
    *,
    serials: list[str] | None = None,
    skip_audit: bool = True,
    log: LogFn | None = None,
    out_path: Path | None = None,
) -> dict[str, Any]:
    """Dump start-gate status to logs without starting the farm.

    Default skips the slow fingerprint audit (same as ``--skip-audit``). Writes
    ``gate-status-fast-last.txt`` under the PharmFlow logs dir. Never calls
    start_farm; does not clear an existing FARM_STOP.
    """
    st = evaluate_start_gate(
        serials=serials,
        log=log,
        apply_stealth_defaults=True,
        skip_audit=bool(skip_audit),
    )
    phones = list(st.get("phones") or [])
    phone_count = int(st.get("phone_count") or len(phones))
    stealth_ok = st.get("stealth_ok")
    funds_ok = st.get("funds_ok")
    gate_ok = st.get("ok")
    message = st.get("message") or st.get("error") or ""
    if skip_audit:
        stealth_line = f"STEALTH_OK={stealth_ok} (audit_skipped)"
    else:
        stealth_line = f"STEALTH_OK={stealth_ok}"

    lines = [
        f"TIME={datetime.now(timezone.utc).isoformat()}",
        f"ADB={phone_count}",
        f"SERIALS={','.join(str(s) for s in phones)}",
        stealth_line,
        f"FUNDS_OK={funds_ok}",
        f"GATE_OK={gate_ok}",
        f"MESSAGE={message}",
        "FARM_STOP=kept",
        "START_FARM=never",
    ]
    text = "\n".join(lines) + "\n"

    logs = _logs_dir()
    try:
        logs.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {
            **st,
            "ok": False,
            "dumped": False,
            "error": f"Could not create logs dir {logs}: {exc}",
            "path": str(logs / "gate-status-fast-last.txt"),
            "text": text,
        }

    dest = Path(out_path) if out_path is not None else (logs / "gate-status-fast-last.txt")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    except OSError as exc:
        return {
            **st,
            "ok": False,
            "dumped": False,
            "error": f"Could not write {dest}: {exc}",
            "path": str(dest),
            "text": text,
        }

    if log:
        log(f"gate status dumped → {dest}")
    return {
        **st,
        "dumped": True,
        "path": str(dest),
        "text": text,
        "adb": phone_count,
        "start_farm": "never",
    }


def prefer_newest_farm_builds() -> list[str]:
    """Kill duplicate farm/stealth workers; keep newest PID only."""
    notes: list[str] = []
    try:
        from automation.pharmflow_unison_dedupe import dedupe_keep_newest
    except Exception as exc:  # noqa: BLE001
        return [f"dedupe_unavailable:{exc}"]
    for script in (
        "run_farm_354.py",
        "pharmflow_stealth_guard.py",
        "pharmflow_unison_supervisor.py",
        "farm_operator_dash.py",
        "run_mantis_inject_proxies.py",
        "pharmflow_inject_keepalive.py",
    ):
        killed = dedupe_keep_newest(script)
        for pid in killed:
            notes.append(f"dedupe_{script}:{pid}")
    return notes
