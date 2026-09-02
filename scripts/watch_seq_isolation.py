#!/usr/bin/env python3
"""Hourly isolation watchdog — FIX first, then Farm check-in / Farm FIX ntfy.

On problems: restore Tor proxies / rotate stuck IPs, then ntfy:
  - Farm FIX (when something was repaired)
  - Farm check-in (hourly useful numbers)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from automation.farm_checkin import gather_checkin, publish_checkin


LOG_DIR = Path(r"C:\CPharm\logs")
STATE = LOG_DIR / "isolation_watch_state.json"
WATCH_LOG = LOG_DIR / "isolation_watch.log"
INTERVAL_S = int(os.environ.get("CPHARM_ISOLATION_WATCH_INTERVAL", "90") or "90")
# ntfy at most once every 2h (global throttle in farm_checkin); fixes still run every INTERVAL_S.
NTFY_EVERY_S = int(os.environ.get("CPHARM_ISOLATION_NTFY_EVERY_S", "7200") or "7200")

# Fallback map if MuMu refresh fails (index → serial).
_FALLBACK_PHONES = {
    0: "10.0.2.86:5555",
    1: "10.0.2.154:5555",
    2: "10.0.2.69:5555",
    3: "10.0.2.149:5555",
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _setup_log() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("isolation_watch")
    log.setLevel(logging.INFO)
    if not log.handlers:
        fh = logging.FileHandler(WATCH_LOG, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(fh)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(sh)
    return log


def _phone_map(log: logging.Logger) -> dict[int, str]:
    try:
        from wizard.mumu_farm_ops import MuMuFarmOps

        farm = MuMuFarmOps()
        farm.refresh_serials()
        out: dict[int, str] = {}
        for inst in farm.list_instances():
            if inst.adb_serial and inst.index is not None and int(inst.index) < 4:
                out[int(inst.index)] = str(inst.adb_serial)
        for idx, serial in _FALLBACK_PHONES.items():
            out.setdefault(idx, serial)
        if out:
            return out
    except Exception as exc:
        log.warning("MuMu phone map failed: %s — using fallback", exc)
    return dict(_FALLBACK_PHONES)


def _fix_proxies(log: logging.Logger) -> list[str]:
    """Restore Tor/inject on any phone with cleared proxy. Returns human fix lines."""
    from automation.adb_wrapper import AdbWrapper
    from automation.tor_manager import TorManager, phone_http_port

    os.environ.setdefault("CPHARM_MANTIS_INJECT_PROXY", "1")
    adb = AdbWrapper()
    tor = TorManager(adb)
    fixes: list[str] = []
    for idx, serial in _phone_map(log).items():
        try:
            proxy = (
                adb.shell("settings get global http_proxy", serial=serial, timeout=8.0).stdout or ""
            ).strip()
            expect_tor = f"127.0.0.1:{phone_http_port(idx)}"
            expect_inject = f"127.0.0.1:{8218 + idx}"
            if expect_inject in proxy or expect_tor in proxy:
                continue
            was = proxy or "none"
            log.info("fixing Tor/inject proxy phone%d was=%s", idx, was)
            tor.start_phone_tor(idx, serial)
            # Prefer inject port when enabled.
            try:
                from automation.mantis_inject_proxy import inject_enabled, phone_inject_port

                if inject_enabled():
                    inj = phone_inject_port(idx)
                    adb.shell(
                        f"settings put global http_proxy 127.0.0.1:{inj}",
                        serial=serial,
                        timeout=8.0,
                    )
            except Exception:
                pass
            proxy2 = (
                adb.shell("settings get global http_proxy", serial=serial, timeout=8.0).stdout or ""
            ).strip()
            if expect_inject in proxy2 or expect_tor in proxy2 or "127.0.0.1:" in proxy2:
                fixes.append(f"vm{idx} proxy {was}→{proxy2}")
            else:
                fixes.append(f"vm{idx} proxy fix attempted was={was} now={proxy2 or 'none'}")
        except Exception as exc:
            log.warning("proxy fix phone%d failed: %s", idx, exc)
            fixes.append(f"vm{idx} Tor proxy fix FAILED: {exc}")
    return fixes


def run_once(log: logging.Logger, *, allow_ntfy: bool = True) -> dict:
    fixes = _fix_proxies(log)
    # Only count successful restores as "fixed" for the FIX title.
    real_fixes = [f for f in fixes if "FAILED" not in f]
    snap = gather_checkin(fixes=real_fixes)

    prev: dict = {}
    if STATE.is_file():
        try:
            prev = json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prev = {}

    state = {
        "ts": _utc(),
        "fixes": real_fixes,
        "verdict": snap.verdict,
        "ran": snap.cycle_ran,
        "ok": snap.cycle_ok,
        "path3": snap.path3_clicks,
        "ip_switches": snap.ip_switches,
        "last_ntfy_unix": prev.get("last_ntfy_unix") or 0,
    }
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    log.info(
        "isolation tick verdict=%s fixed=%d ran=%s Path3=%s",
        snap.verdict,
        len(real_fixes),
        snap.cycle_ran,
        snap.path3_clicks,
    )

    # Quiet proxy repairs every tick; at most ONE ntfy every 2 hours (single check-in).
    if allow_ntfy:
        last = float(state.get("last_ntfy_unix") or 0)
        now = time.time()
        if last <= 0 or (now - last) >= NTFY_EVERY_S:
            # One message only — check-in body already includes any fixes.
            if publish_checkin(snap):
                state["last_ntfy_unix"] = now
                STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
                log.info("isolation ntfy check-in sent (2h cap)")
            else:
                log.info("isolation ntfy skipped (global throttle or send fail)")
        else:
            left = int(NTFY_EVERY_S - (now - last))
            log.info("isolation ntfy skipped (%ss left in 2h window); fixes logged only", left)
    return state


def main() -> int:
    log = _setup_log()
    log.info(
        "isolation_watch start fix_every=%ss ntfy_every=%ss (quiet fixes; max 1 ntfy/2h)",
        INTERVAL_S,
        NTFY_EVERY_S,
    )
    while True:
        try:
            run_once(log)
        except Exception as exc:
            log.exception("watch loop error: %s", exc)
        time.sleep(max(60, INTERVAL_S))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
