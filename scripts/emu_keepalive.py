#!/usr/bin/env python3
"""Reconnect ADB serials quietly — no console windows."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import automation.no_window  # noqa: E402,F401

LOG = Path(r"C:\CPharm\logs")
ADB = r"C:\CPharm\bundled\adb.exe"
if not Path(ADB).is_file():
    ADB = "adb"
INTERVAL_S = 45.0
_NOWIN = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))


def _normalize_serial(raw: str) -> str:
    """Ensure host:port form — bare IPs fail `adb connect` silently."""
    s = (raw or "").strip()
    if not s:
        return ""
    if ":" not in s:
        return f"{s}:5555"
    return s


def _serials() -> list[str]:
    path = LOG / "farm_runtime_overrides.json"
    try:
        ov = json.loads(path.read_text(encoding="utf-8-sig"))
        return [
            _normalize_serial(s)
            for s in str(ov.get("CPHARM_ADB_SERIALS") or "").split(",")
            if _normalize_serial(s)
        ]
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []


def _ensure_adb_server() -> None:
    try:
        subprocess.run(
            [ADB, "start-server"],
            capture_output=True,
            timeout=15,
            creationflags=_NOWIN,
        )
    except (subprocess.SubprocessError, OSError):
        pass


def main() -> int:
    LOG.mkdir(parents=True, exist_ok=True)
    hb = LOG / "emu_keepalive_heartbeat.txt"
    while True:
        serials = _serials()
        ok = 0
        for ser in serials:
            try:
                r = subprocess.run(
                    [ADB, "connect", ser],
                    capture_output=True,
                    timeout=8,
                    creationflags=_NOWIN,
                    text=True,
                    errors="replace",
                )
                out = (r.stdout or "") + (r.stderr or "")
                if "connected" in out.lower() or "already connected" in out.lower():
                    ok += 1
                elif "cannot connect" in out.lower() or "failed" in out.lower():
                    _ensure_adb_server()
            except (subprocess.SubprocessError, OSError):
                _ensure_adb_server()
        try:
            hb.write_text(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} serials={len(serials)} ok={ok}\n",
                encoding="utf-8",
            )
        except OSError:
            pass
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    raise SystemExit(main())
