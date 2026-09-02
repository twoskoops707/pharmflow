#!/usr/bin/env python3
"""FamFlow farm digest reporter (default hourly) → ntfy.sh/twskoops.

Parses farm_354_results.jsonl (+ optional log hints) and posts a summary every hour,
including a per-browser OK/ran line (chrome/brave/ff/ddg) so the operator does not
have to watch four browsers. Also watches for farm death and alerts once.

  py -u scripts/farm_hourly_ntfy.py
  py -u scripts/farm_hourly_ntfy.py --once          # single report then exit
  py -u scripts/farm_hourly_ntfy.py --interval 3600

Logs: C:\\CPharm\\logs\\farm_hourly_ntfy.log
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from automation.farm_checkin import format_browsers, summarize_browsers  # noqa: E402

DEFAULT_TOPIC = "twskoops"
RESULTS = Path(r"C:\CPharm\logs\farm_354_results.jsonl")
FARM_LOG = Path(r"C:\CPharm\logs\farm_354.log")
PROGRESS = Path(r"C:\CPharm\logs\farm_354_progress.json")
WATCHER_LOG = Path(r"C:\CPharm\logs\farm_hourly_ntfy.log")
STATE = Path(r"C:\CPharm\logs\farm_hourly_ntfy_state.json")

# Same identity rules as scripts/run_farm_354.py::_parse_ad_key
_AD_HOME = re.compile(r"homead(\d+)")
_AD_ON = re.compile(r"_on(stats|glass|settings)_ad(\d+)_ad$")
_AD_PAGE = re.compile(r"_(stats|glass|settings)_ad(\d+)_ad$")
_START_RE = re.compile(r"START\s+(\d+)\s+phones")
_FARM_COMPLETE_RE = re.compile(r"FARM COMPLETE")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _topic() -> str:
    return os.environ.get("CPHARM_NTFY_TOPIC", DEFAULT_TOPIC).strip() or DEFAULT_TOPIC


def _ntfy_url() -> str:
    return f"https://ntfy.sh/{_topic()}"


def _setup_log() -> logging.Logger:
    WATCHER_LOG.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("farm_hourly_ntfy")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(WATCHER_LOG, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


log = _setup_log()


def parse_ad_key(stem: str) -> str | None:
    m = _AD_HOME.search(stem)
    if m:
        return f"home:{m.group(1)}"
    m = _AD_ON.search(stem)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    m = _AD_PAGE.search(stem)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    return None


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_results(since: datetime | None) -> list[dict]:
    if not RESULTS.exists():
        return []
    out: list[dict] = []
    with RESULTS.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _parse_ts(obj.get("time"))
            if since is not None and ts is not None and ts < since:
                continue
            if ts is not None:
                obj["_ts"] = ts
            out.append(obj)
    return out


def summarize(rows: list[dict], *, window_label: str) -> dict:
    ok = fail = path3_ran = path3_ok = timer_ok = timer_fail = 0
    phones: set[str] = set()
    ad_keys: set[str] = set()
    ad_keys_ok: set[str] = set()
    variants: dict[str, int] = {}
    errors: dict[str, int] = {}

    for r in rows:
        phone = r.get("phone") or "?"
        phones.add(phone)
        success = bool(r.get("success"))
        if success:
            ok += 1
            timer_ok += 1  # success implies Start Perfect Dab timer confirmed
        else:
            fail += 1
            err = (r.get("error") or "unknown").strip()
            errors[err] = errors.get(err, 0) + 1
            if "did not confirm timer" in err.lower() or "start perfect dab" in err.lower():
                timer_fail += 1

        variant = str(r.get("variant") or "?")
        variants[variant] = variants.get(variant, 0) + 1

        is_p3 = bool(r.get("path3")) or variant == "ad"
        stem = str(r.get("sequence") or Path(str(r.get("path") or "")).stem)
        ad_key = parse_ad_key(stem)
        if is_p3:
            path3_ran += 1
            if success:
                path3_ok += 1
            if ad_key:
                ad_keys.add(ad_key)
                if success:
                    ad_keys_ok.add(ad_key)

    return {
        "window": window_label,
        "browsers": summarize_browsers(rows),
        "total": len(rows),
        "ok": ok,
        "fail": fail,
        "timer_ok": timer_ok,
        "timer_fail": timer_fail,
        "path3_ran": path3_ran,
        "path3_ok": path3_ok,
        "ad_keys": sorted(ad_keys),
        "ad_keys_ok": sorted(ad_keys_ok),
        "phones": sorted(phones),
        "variants": variants,
        "top_errors": sorted(errors.items(), key=lambda x: -x[1])[:5],
    }


def farm_start_hint() -> datetime | None:
    """Best-effort farm start from progress file or last START line mtime window."""
    if PROGRESS.exists():
        try:
            data = json.loads(PROGRESS.read_text(encoding="utf-8"))
            # progress has updated + deadline; estimate start = deadline - hours
            hours = float(data.get("hours") or 6)
            deadline = _parse_ts(data.get("deadline"))
            if deadline:
                return deadline - timedelta(hours=hours)
            updated = _parse_ts(data.get("updated"))
            if updated:
                return updated
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    if not FARM_LOG.exists():
        return None
    # Scan last ~200 lines for START
    try:
        lines = FARM_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
    except OSError:
        return None
    for line in reversed(lines):
        if _START_RE.search(line):
            # "2026-07-12 10:04:16,436 INFO START ..."
            m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
            if m:
                try:
                    local = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                    # Assume local machine local time → attach local tz then to UTC
                    return local.astimezone().astimezone(timezone.utc)
                except ValueError:
                    pass
            return None
    return None


def farm_pids() -> list[int]:
    """PIDs for the real farm runner only (not this watcher / probe shells)."""
    if os.environ.get("CPHARM_FARM_IN_PROCESS", "0").strip().lower() in {"1", "true", "yes", "on"}:
        return [os.getpid()]
    # IMPORTANT: do not put the needle in the PowerShell -Command text, or the
    # probe process matches itself and death detection never fires.
    ps = (
        "$needle = 'run_farm' + '_354.py'; "
        "Get-CimInstance Win32_Process | "
        "Where-Object { "
        "  $_.CommandLine -and "
        "  $_.CommandLine.Contains($needle) -and "
        "  $_.CommandLine -notmatch 'farm_hourly_ntfy' "
        "} | Select-Object -ExpandProperty ProcessId"
    )
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps],
            text=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("farm_pids query failed: %s", exc)
        return []
    pids: list[int] = []
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def log_fresh_seconds(max_age: float = 180.0) -> bool:
    if not FARM_LOG.exists():
        return False
    age = time.time() - FARM_LOG.stat().st_mtime
    return age <= max_age


def farm_alive() -> bool:
    # Process is authoritative; log freshness alone must not hide a dead farm.
    return bool(farm_pids())


def publish(title: str, body: str, *, priority: str = "default", tags: str = "chart_with_upwards_trend,phone") -> bool:
    data = body.encode("utf-8")
    req = urllib.request.Request(
        _ntfy_url(),
        data=data,
        method="POST",
        headers={
            "Title": title,
            "Priority": priority,
            "Tags": tags,
            "Content-Type": "text/plain; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        log.info("ntfy OK title=%r bytes=%d", title, len(data))
        return True
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.error("ntfy FAILED: %s", exc)
        return False


def format_report(summary: dict, *, farm_up: bool, pids: list[int], kind: str) -> tuple[str, str]:
    """Check-in shaped digest (operator format) + window note."""
    try:
        from automation.farm_checkin import format_checkin, gather_checkin

        snap = gather_checkin(
            note=f"window={summary.get('window') or kind} · timers_OK={summary.get('timer_ok', 0)}"
        )
        # Prefer this window's Path3/OK when results-based summary has data.
        if summary.get("total"):
            snap.cycle_ran = int(summary["total"])
            snap.cycle_ok = int(summary["ok"])
            snap.cycle_fail = int(summary["fail"])
            snap.path3_clicks = int(summary.get("path3_ok") or 0)
            snap.browsers = summary.get("browsers") or {}
        snap.farm_up = farm_up or snap.farm_up
        snap.farm_pids = pids or snap.farm_pids
        if not snap.farm_up:
            snap.verdict = "DOWN"
        elif snap.healthy:
            snap.verdict = "healthy"
        title = f"Farm check-in - {snap.verdict}"
        return title, format_checkin(snap)
    except Exception as exc:  # noqa: BLE001 — never break digest loop
        log.warning("check-in format failed: %s", exc)
        ad_ok = ", ".join(summary["ad_keys_ok"]) if summary["ad_keys_ok"] else "none"
        title = f"Farm check-in - {'UP' if farm_up else 'DOWN'}"
        body = "\n".join(
            [
                f"Farm check-in - {'UP' if farm_up else 'DOWN'}",
                f"This window: ran={summary['total']} | OK={summary['ok']} | FAIL={summary['fail']}",
                f"Path3={summary['path3_ok']}/{summary['path3_ran']} | timers_OK={summary['timer_ok']}",
                f"Browsers: {format_browsers(summary.get('browsers') or {})}",
                f"ad_slots={ad_ok} | phones={len(summary['phones'])}",
            ]
        )
        return title, body


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def build_window(state: dict, *, baseline: bool, interval_s: int = 3600) -> tuple[datetime | None, str]:
    now = _utc_now()
    if baseline:
        start = farm_start_hint()
        # Prefer results file birth: oldest row, or last report cursor
        last_sent = _parse_ts(state.get("last_report_at"))
        if start and last_sent and last_sent > start:
            start = last_sent
        if start is None:
            # first hour of results present, else last interval
            rows = load_results(None)
            if rows and rows[0].get("_ts"):
                start = rows[0]["_ts"]
            else:
                start = now - timedelta(seconds=max(60, interval_s))
        label = f"since farm start / baseline → {now.strftime('%H:%M')}Z"
        return start, label
    mins = max(1, int(interval_s // 60))
    start = now - timedelta(seconds=max(60, interval_s))
    label = f"last {mins}m ending {now.strftime('%Y-%m-%d %H:%M')}Z"
    return start, label


def send_report(*, baseline: bool, state: dict, interval_s: int = 3600) -> bool:
    since, label = build_window(state, baseline=baseline, interval_s=interval_s)
    rows = load_results(since)
    summary = summarize(rows, window_label=label)
    pids = farm_pids()
    up = bool(pids)
    kind = "watching / baseline" if baseline else f"{max(1, interval_s // 60)}min"
    title, body = format_report(summary, farm_up=up, pids=pids, kind=kind)
    tags = "clipboard,white_check_mark,phone" if up else "clipboard,warning,phone"
    ok = publish(title, body, tags=tags)
    state["last_report_at"] = _utc_now().isoformat()
    state["last_baseline"] = bool(baseline)
    state["last_ok"] = ok
    save_state(state)
    return ok


def maybe_death_alert(state: dict, saw_alive: bool) -> bool:
    """Alert once when farm was seen alive and is now dead."""
    if os.environ.get("CPHARM_NTFY_EMERGENCY_ALERTS", "0").strip().lower() not in {"1", "true", "yes", "on"}:
        log.info("farm death alert suppressed by CPHARM_NTFY_EMERGENCY_ALERTS=0")
        state["death_alerted"] = True
        state["saw_alive"] = False
        save_state(state)
        return False
    if not saw_alive:
        return False
    if farm_alive():
        state["saw_alive"] = True
        state["death_alerted"] = False
        save_state(state)
        return False
    if state.get("death_alerted"):
        return False
    # Confirm still dead after a short grace (caller already waited)
    title = "FamFlow farm DIED"
    body = (
        f"run_farm_354 not running at {_utc_now().isoformat()}\n"
        f"log mtime age={_log_age_s():.0f}s\n"
        "Not auto-restarting — check FRE / phones."
    )
    ok = publish(title, body, priority="high", tags="warning,skull")
    state["death_alerted"] = True
    state["saw_alive"] = False
    save_state(state)
    return ok


def _log_age_s() -> float:
    if not FARM_LOG.exists():
        return -1.0
    return time.time() - FARM_LOG.stat().st_mtime


def wait_for_farm(timeout_s: float = 600.0, poll_s: float = 20.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        pids = farm_pids()
        if pids and log_fresh_seconds(300):
            log.info("farm UP pids=%s", pids)
            return True
        if pids:
            log.info("farm process present pids=%s (log may still be warming)", pids)
            return True
        log.info("waiting for farm… log_age=%.0fs", _log_age_s())
        time.sleep(poll_s)
    return False


def run_reporter(
    *,
    interval_s: int = 3600,
    once: bool = False,
    baseline: bool = False,
    wait_for_start: bool = True,
    wait_seconds: int = 600,
    stop_event: threading.Event | None = None,
) -> int:
    """Run the reusable digest loop for CLI or the frozen EXE."""
    state = load_state()
    log.info("farm_hourly_ntfy starting topic=%s interval=%ss", _topic(), interval_s)

    if wait_for_start:
        up = wait_for_farm(timeout_s=float(wait_seconds))
        if not up:
            log.warning("farm not detected after wait — startup notification suppressed")

    sent = False
    if baseline:
        sent = send_report(baseline=True, state=state, interval_s=int(interval_s))
        log.info("baseline sent=%s", sent)
    else:
        log.info("baseline suppressed; first report in %ss", interval_s)
    if once:
        return 0 if sent else 1

    next_report = time.time() + max(60, int(interval_s))
    # Only trust a live process — stale state.saw_alive must not suppress death alerts.
    saw_alive = bool(farm_pids())
    if saw_alive:
        state["saw_alive"] = True
        state["death_alerted"] = False
        save_state(state)
    else:
        state["saw_alive"] = False
        save_state(state)

    miss_ticks = 0
    while not (stop_event and stop_event.is_set()):
        try:
            pids = farm_pids()
            if pids:
                miss_ticks = 0
                saw_alive = True
                if state.get("death_alerted") or not state.get("saw_alive"):
                    state["saw_alive"] = True
                    state["death_alerted"] = False
                    save_state(state)
            elif saw_alive:
                miss_ticks += 1
                # ~90s with 30s sleep (3 misses)
                if miss_ticks >= 3:
                    maybe_death_alert(state, saw_alive=True)
                    saw_alive = False
                    miss_ticks = 0

            now = time.time()
            if now >= next_report:
                send_report(baseline=False, state=state, interval_s=int(interval_s))
                next_report = now + max(60, int(interval_s))
            if stop_event:
                stop_event.wait(30)
            else:
                time.sleep(30)
        except KeyboardInterrupt:
            log.info("interrupt — exiting")
            return 0
        except Exception as exc:  # noqa: BLE001 — durable loop
            log.exception("loop error: %s", exc)
            if stop_event:
                stop_event.wait(60)
            else:
                time.sleep(60)
    log.info("stop requested — exiting")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Farm → ntfy digest reporter")
    ap.add_argument("--once", action="store_true", help="Send one report and exit")
    ap.add_argument("--interval", type=int, default=3600, help="Seconds between reports (default hourly)")
    ap.add_argument("--baseline", action="store_true", help="Send an immediate startup baseline report")
    ap.add_argument("--no-wait", action="store_true", help="Do not wait for farm before baseline")
    ap.add_argument("--wait-seconds", type=int, default=600, help="Max wait for farm startup")
    args = ap.parse_args()
    return run_reporter(
        interval_s=int(args.interval),
        once=bool(args.once),
        baseline=bool(args.baseline),
        wait_for_start=not bool(args.no_wait),
        wait_seconds=int(args.wait_seconds),
    )


if __name__ == "__main__":
    raise SystemExit(main())
