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
    ov_path = Path(os.environ.get("PHARMFLOW_LOG_DIR", r"C:\PharmFlow\logs")) / "farm_runtime_overrides.json"
    if ov_path.is_file():
        import json

        ov = json.loads(ov_path.read_text(encoding="utf-8"))
        if isinstance(ov, dict):
            for k, v in ov.items():
                if str(k).startswith("PHARMFLOW_") and v not in (None, ""):
                    os.environ.setdefault(str(k), str(v))
except Exception:
    pass

os.environ.setdefault("PHARMFLOW_MANTIS_INJECT_PROXY", "1")

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
from automation.mumu_shell_cli import phone_vm_index  # noqa: E402
from automation.tor_manager import TorManager  # noqa: E402

INTERVAL = float(os.environ.get("PHARMFLOW_PROXY_WATCH_INTERVAL", "3") or "3")
HEARTBEAT = Path(r"C:\PharmFlow\logs\proxy_watch_heartbeat.txt")
# Absolute MuMu idx (vm24 → 24 → inject 8242). Never clamp to a packed roster.
_MAX_PHONE = int(os.environ.get("PHARMFLOW_PROXY_WATCH_MAX_INDEX", "512") or "512")


def _is_cleared(proxy: str) -> bool:
    raw = (proxy or "").strip()
    return (not raw) or raw.lower() in _CLEARED_PROXY_VALUES or raw.endswith(":0")


def _map(adb: AdbWrapper) -> dict[int, str]:
    """Live MuMu serials keyed by absolute vmN index (not packed roster 0..N-1).

    Roster enumerate(live[:4]) → 8218..8221 must never run on a vm24–vm31 farm.
    Prefer lock-map inject keys; fall back to phone_vm_index(name).
    """
    out: dict[int, str] = {}
    try:
        from wizard.mumu_farm_ops import MuMuFarmOps

        farm = MuMuFarmOps()
        farm.refresh_serials()
        for inst in farm.list_instances():
            if not inst.adb_serial:
                continue
            name = str(getattr(inst, "name", "") or "")
            idx = phone_vm_index(name, int(getattr(inst, "index", 0) or 0))
            if idx is None:
                continue
            idx_i = int(idx)
            if 0 <= idx_i < _MAX_PHONE:
                out[idx_i] = str(inst.adb_serial)
    except Exception as exc:
        print(f"map err {exc}", flush=True)
    if out:
        return out
    # Lock-map fallback: absolute ports already baked as 8218+vmN.
    try:
        lock_path = Path(os.environ.get("PHARMFLOW_LOG_DIR", r"C:\PharmFlow\logs")) / "ADB_SERIAL_MAP.lock.json"
        if lock_path.is_file():
            import json

            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            phones = lock.get("phones") if isinstance(lock, dict) else None
            if isinstance(phones, dict):
                live = {d.serial for d in adb.devices_detailed() if d.online}
                for name, serial in phones.items():
                    ser = str(serial or "").strip()
                    if ser not in live:
                        continue
                    idx = phone_vm_index(str(name), None)
                    if idx is not None and 0 <= int(idx) < _MAX_PHONE:
                        out[int(idx)] = ser
    except Exception as exc:
        print(f"lock map err {exc}", flush=True)
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
