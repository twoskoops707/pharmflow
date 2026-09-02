#!/usr/bin/env python3
"""Tight loop: keep guest http_proxy on the right port for the active browser.

Ad-fill (FORCE_DIRECT) sets http_proxy=:0 for a few seconds. This watcher
must stay alive and re-pin within ~3s so Chromium phones never sit on direct IP.

Scramble + Firefox/DuckDuckGo/Brave: expected proxy is cleared (:0). Do NOT
start Tor or inject on those — their cert stores reject the MITM CA and freeze
sequences (Brave shows "not safe website"). Brave still gets ads via CDP paint.

Uses idempotent pin_guest_proxy — no busy loop, no adb disconnect.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import automation.no_window  # noqa: E402,F401  (kill child console-window flashes)

# Honor farm overrides (scramble vs tor) before first pin.
try:
    ov_path = Path(os.environ.get("CPHARM_LOG_DIR", r"C:\CPharm\logs")) / "farm_runtime_overrides.json"
    if ov_path.is_file():
        import json

        ov = json.loads(ov_path.read_text(encoding="utf-8"))
        if isinstance(ov, dict):
            for k, v in ov.items():
                if str(k).startswith("CPHARM_") and v not in (None, ""):
                    os.environ.setdefault(str(k), str(v))
except Exception:
    pass

os.environ.setdefault("CPHARM_MANTIS_INJECT_PROXY", "1")

from automation.adb_wrapper import AdbWrapper  # noqa: E402
from automation.browse_proxy import (  # noqa: E402
    _CLEARED_PROXY_VALUES,
    detect_foreground_browser_package,
    expected_guest_proxy,
    guest_proxy_healthy,
    pin_guest_proxy,
    remember_browser_package,
    resolve_browser_package,
)
from automation.tor_manager import TorManager  # noqa: E402

INTERVAL = float(os.environ.get("CPHARM_PROXY_WATCH_INTERVAL", "3") or "3")
HEARTBEAT = Path(r"C:\CPharm\logs\proxy_watch_heartbeat.txt")
# MuMu indices are not packed 0..N-1 (live farm uses 1,2,3,4 = vm11/vm3/vm4/vm5).
# Cap must cover highest index we inject for (8218+idx); was 4 and skipped vm5 (idx=4).
_MAX_PHONE = int(os.environ.get("CPHARM_PROXY_WATCH_MAX_INDEX", "16") or "16")


def _is_cleared(proxy: str) -> bool:
    raw = (proxy or "").strip()
    return (not raw) or raw.lower() in _CLEARED_PROXY_VALUES or raw.endswith(":0")


def _map(adb: AdbWrapper) -> dict[int, str]:
    """Live MuMu serials only — never trust stale hardcoded 10.0.2.x fallbacks.

    Indexes are MuMu VM indices (not packed 0..N-1). Live money-day set is
    typically idx 1/2/3/4 (vm11/vm3/vm4/vm5) — must include idx>=4 so vm5
    inject 8222 is watched.
    """
    out: dict[int, str] = {}
    try:
        from wizard.mumu_farm_ops import MuMuFarmOps

        farm = MuMuFarmOps()
        farm.refresh_serials()
        for inst in farm.list_instances():
            if inst.adb_serial and inst.index is not None and 0 <= int(inst.index) < _MAX_PHONE:
                out[int(inst.index)] = str(inst.adb_serial)
    except Exception as exc:
        print(f"map err {exc}", flush=True)
    # If MuMu enumeration failed, fall back to live ADB order (best-effort).
    if len(out) < 4:
        live = [d.serial for d in adb.devices_detailed() if d.online]
        for i, ser in enumerate(sorted(live)[:4]):
            out.setdefault(i, ser)
    return out


def once() -> list[str]:
    adb = AdbWrapper()
    tor = TorManager(adb)
    live = {d.serial for d in adb.devices_detailed() if d.online}
    fixes: list[str] = []
    for idx, serial in _map(adb).items():
        if serial not in live:
            continue
        try:
            pkg = resolve_browser_package(adb, serial)
            proxy = (
                adb.shell("settings get global http_proxy", serial=serial, timeout=6.0).stdout or ""
            ).strip()
            # Unknown browser: never invent inject — wait for foreground/remember.
            if not pkg:
                detected = detect_foreground_browser_package(adb, serial)
                if detected:
                    pkg = detected
                    remember_browser_package(serial, pkg)
                else:
                    continue

            want = expected_guest_proxy(idx, browser_package=pkg)

            # Scramble/direct for Firefox/DDG/Brave: cleared proxy is the correct state.
            if not want:
                if _is_cleared(proxy):
                    continue
                now = pin_guest_proxy(adb, serial, idx, attempts=2, browser_package=pkg)
                if now != proxy:
                    fixes.append(f"vm{idx} {proxy or 'none'}->{now}")
                    print(
                        f"fixed vm{idx} pkg={pkg or '?'} {proxy!r} -> {now!r} (clear)",
                        flush=True,
                    )
                continue

            if guest_proxy_healthy(proxy, idx) and proxy == want:
                continue

            # Chromium (or Tor mode): re-pin inject/Tor. Only start Tor when
            # we actually want a live 127.0.0.1:port — never for cleared-want browsers.
            now = pin_guest_proxy(adb, serial, idx, attempts=2, browser_package=pkg)
            if not guest_proxy_healthy(now, idx) or now != want:
                try:
                    tor.start_phone_tor(idx, serial)
                except Exception:
                    pass
                now = pin_guest_proxy(adb, serial, idx, attempts=2, browser_package=pkg)
            if now != proxy:
                fixes.append(f"vm{idx} {proxy or 'none'}->{now}")
                print(f"fixed vm{idx} pkg={pkg or '?'} {proxy!r} -> {now!r}", flush=True)
        except Exception as exc:
            print(f"vm{idx} err {exc}", flush=True)
    try:
        HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT.write_text(
            f"{time.strftime('%Y-%m-%d %H:%M:%S')} fixes={len(fixes)} interval={INTERVAL:g}\n",
            encoding="utf-8",
        )
    except OSError:
        pass
    return fixes


def main() -> int:
    print(f"proxy watch every {INTERVAL:g}s", flush=True)
    while True:
        try:
            once()
        except Exception as exc:
            print(f"loop err {exc}", flush=True)
        time.sleep(max(1.0, INTERVAL))


if __name__ == "__main__":
    raise SystemExit(main())
