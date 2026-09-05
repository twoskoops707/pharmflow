"""Farm session health — log-derived per-phone quality + paying-fill telemetry.

Reads the live farm log and SSP hunter state so the deck can show session
quality (dump timeouts, fallback taps, steps, paying rounds) without opening
log files. Pure reader: never modifies farm state, never spawns processes.

Rows are keyed by ADB serial (the farm log's timeout / fallback lines carry
serials; step lines carry VM names), joined by time-window correlation and
labeled approximate where relevant.
"""
from __future__ import annotations

import glob
import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any

LOG_DIR = os.environ.get("CPHARM_LOGS", r"C:\CPharm\logs")

_STEP_RE = re.compile(r"\[(vm[\w.]+)\] step (\d+)")
_TIMEOUT_RE = re.compile(
    r"ADB timeout \(child killed\).*?-s', '([^']+)'.*?uiautomator dump"
)
_FALLBACK_RE = re.compile(
    r"fallback tap|treating as started|Age gate YES via fallback tap"
)
_SERIAL_ON_RE = re.compile(r"\bon ([0-9.]+:\d+)\b")
_ISOLATE_RE = re.compile(r"isolate phone=(\S+) ok=True")


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _read_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def newest_farm_log() -> str | None:
    logs = sorted(
        glob.glob(os.path.join(LOG_DIR, "farm_*.log")),
        key=os.path.getmtime,
        reverse=True,
    )
    return logs[0] if logs else None


def _parse_line_ts(line: str) -> float | None:
    # 2026-09-05 00:20:02,436 INFO ...
    m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(\d{3})", line)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        return dt.timestamp() + int(m.group(2)) / 1000.0
    except ValueError:
        return None


def parse_farm_log(path: str | None, window_s: float = 3600.0) -> dict:
    """Return raw counts from the newest farm log within the window."""
    out = {
        "steps": 0,
        "step_lines": [],  # (ts, vm_name)
        "timeouts": 0,
        "timeout_events": [],  # (ts, serial)
        "fallbacks": 0,
        "fallback_events": [],  # (ts, serial_or_None)
        "isolates": 0,
        "isolate_events": [],  # (ts, vm_name)
        "log_path": path,
    }
    if not path:
        return out
    now = time.time()
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                ts = _parse_line_ts(line)
                if ts is None or now - ts > window_s:
                    continue
                sm = _STEP_RE.search(line)
                if sm:
                    out["steps"] += 1
                    out["step_lines"].append((ts, sm.group(1)))
                    continue
                tm = _TIMEOUT_RE.search(line)
                if tm:
                    out["timeouts"] += 1
                    out["timeout_events"].append((ts, tm.group(1)))
                    continue
                if _FALLBACK_RE.search(line):
                    out["fallbacks"] += 1
                    sm2 = _SERIAL_ON_RE.search(line)
                    out["fallback_events"].append(
                        (ts, sm2.group(1) if sm2 else None)
                    )
                    continue
                im = _ISOLATE_RE.search(line)
                if im:
                    out["isolates"] += 1
                    out["isolate_events"].append((ts, im.group(1)))
    except OSError:
        pass
    return out


def _nearest_name(ts: float, step_lines: list[tuple[float, str]], tol_s: float = 3.0) -> str | None:
    best: tuple[float, str] | None = None
    for sts, name in step_lines:
        d = abs(sts - ts)
        if d <= tol_s and (best is None or d < best[0]):
            best = (d, name)
    return best[1] if best else None


def _phones(parsed: dict) -> list[dict]:
    """Per-serial rows with correlated VM names (approximate) + per-VM step totals."""
    step_by_vm: dict[str, int] = {}
    for _ts, name in parsed["step_lines"]:
        step_by_vm[name] = step_by_vm.get(name, 0) + 1

    serials: dict[str, dict] = {}
    for ts, serial in parsed["timeout_events"]:
        row = serials.setdefault(
            serial, {"serial": serial, "name": None, "timeouts": 0, "fallbacks": 0, "steps": 0, "last_seen": None}
        )
        row["timeouts"] += 1
        row["last_seen"] = max(row["last_seen"] or 0, ts)
        if row["name"] is None:
            row["name"] = _nearest_name(ts, parsed["step_lines"])
    for ts, serial in parsed["fallback_events"]:
        key = serial or "unknown"
        row = serials.setdefault(
            key, {"serial": key, "name": None, "timeouts": 0, "fallbacks": 0, "steps": 0, "last_seen": None}
        )
        row["fallbacks"] += 1
        row["last_seen"] = max(row["last_seen"] or 0, ts)
        if row["name"] is None and serial:
            row["name"] = _nearest_name(ts, parsed["step_lines"])

    # Attribute steps to serials via nearest-event correlation (approximate).
    for ts, name in parsed["step_lines"]:
        best_serial: tuple[float, str] | None = None
        for ev_ts, serial in list(parsed["timeout_events"]) + [
            (t, s or "") for t, s in parsed["fallback_events"]
        ]:
            if not serial:
                continue
            d = abs(ev_ts - ts)
            if d <= 3.0 and (best_serial is None or d < best_serial[0]):
                best_serial = (d, serial)
        if best_serial:
            serials.setdefault(
                best_serial[1],
                {"serial": best_serial[1], "name": None, "timeouts": 0, "fallbacks": 0, "steps": 0, "last_seen": None},
            )["steps"] += 1

    rows = sorted(serials.values(), key=lambda r: r["serial"])
    for row in rows:
        row["timeout_rate"] = round(row["timeouts"] / row["steps"], 3) if row["steps"] else None
        row["fallback_rate"] = round(row["fallbacks"] / row["steps"], 3) if row["steps"] else None
        if row["last_seen"]:
            row["last_seen_age_s"] = int(time.time() - row["last_seen"])
        if row["name"]:
            row["name"] = f"{row['name']} (approx)"
    return rows


def paying_state() -> dict:
    hb = _read_text(os.path.join(LOG_DIR, "ssp_paying_hunter_heartbeat.txt")).strip()
    paying = None
    round_n = None
    newnym = None
    hb_ts = None
    m = re.search(r"PAYING=(\d+)", hb)
    if m:
        paying = int(m.group(1))
    m = re.search(r"round=(\d+)", hb)
    if m:
        round_n = int(m.group(1))
    m = re.search(r"newnym=(\d+)", hb)
    if m:
        newnym = int(m.group(1))
    m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", hb)
    if m:
        try:
            hb_ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            pass
    fill = _read_json(os.path.join(LOG_DIR, "ssp_paying_fill.json")) or {}
    return {
        "paying": paying,
        "round": round_n,
        "newnym": newnym,
        "heartbeat_ts": hb_ts,
        "heartbeat_age_s": int(time.time() - hb_ts) if hb_ts else None,
        "zones": len(fill.get("ads") or []) if isinstance(fill, dict) else 0,
    }


def payout_latest() -> dict:
    data = _read_json(os.path.join(LOG_DIR, "freebuff_payout_watch.json"))
    if not isinstance(data, list) or not data:
        return {"payout_usd": None, "clicks": None, "impressions": None}
    latest = data[-1]
    return {
        "payout_usd": latest.get("payout_usd"),
        "clicks": latest.get("clicks"),
        "impressions": latest.get("impressions"),
    }


def snapshot(window_s: float = 3600.0) -> dict:
    log_path = newest_farm_log()
    parsed = parse_farm_log(log_path, window_s=window_s)
    log_age_s = None
    if log_path:
        try:
            log_age_s = int(time.time() - os.path.getmtime(log_path))
        except OSError:
            pass
    total_steps = parsed["steps"]
    return {
        "ok": True,
        "window_s": window_s,
        "log_path": log_path,
        "log_age_s": log_age_s,
        "farm_alive": log_age_s is not None and log_age_s < 120,
        "summary": {
            "steps": total_steps,
            "dump_timeouts": parsed["timeouts"],
            "fallback_taps": parsed["fallbacks"],
            "isolates": parsed["isolates"],
            "timeout_rate": round(parsed["timeouts"] / total_steps, 3) if total_steps else None,
            "fallback_rate": round(parsed["fallbacks"] / total_steps, 3) if total_steps else None,
        },
        "phones": _phones(parsed),
        "paying": paying_state(),
        "payout": payout_latest(),
    }


if __name__ == "__main__":
    import pprint

    pprint.pprint(snapshot())