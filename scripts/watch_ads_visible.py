#!/usr/bin/env python3
"""Watch live farm for ads visibility / Mantis failures.

Logs to C:\\CPharm\\logs\\ads_watch.log
Alerts (ntfy) only on sustained problems — not every sequence.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LOG_DIR = Path(r"C:\CPharm\logs")
FARM_LOG = LOG_DIR / "farm_354.log"
WATCH_LOG = LOG_DIR / "ads_watch.log"
SHOT_DIR = LOG_DIR / "ads_watch_shots"
ADB = os.environ.get("CPHARM_ADB") or r"C:\CPharm\bundled\adb.exe"
TOPIC = os.environ.get("CPHARM_NTFY_TOPIC", "twskoops")
INTERVAL_S = int(os.environ.get("CPHARM_ADS_WATCH_INTERVAL", "90") or "90")
ALERT_COOLDOWN_S = int(os.environ.get("CPHARM_ADS_WATCH_ALERT_COOLDOWN", "1800") or "1800")

PHONES = {
    "vm0.gmadoa": "10.0.2.86:5555",
    "vm1.gmadoa": "10.0.2.154:5555",
    "vm2.gmadoa": "10.0.2.69:5555",
    "vm3.gmadoa": "10.0.2.149:5555",
}

_MANTIS_FAIL = re.compile(r"Mantis patch FAILED|dabflow Mantis patch failed", re.I)
_MANTIS_OK = re.compile(r"Mantis patch OK", re.I)
_AD_FALLBACK = re.compile(r"ad_fallback.?[:= ].*true|Ad browse: on-site ad empty", re.I)
_TEMPORARY_DIRECT = re.compile(r"temporary direct for ad fill", re.I)
_SEQ_DONE = re.compile(r"\[(vm\d\.gmadoa)\]\s+(\d+)\s+(P[123]\S*)\s+(OK|FAIL)\s+(\S+)", re.I)

LOG_DIR.mkdir(parents=True, exist_ok=True)
SHOT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(WATCH_LOG, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("ads_watch")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ntfy(title: str, body: str) -> None:
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{TOPIC}",
            data=body.encode("utf-8"),
            method="POST",
            headers={"Title": title[:120], "Tags": "warning,eyes", "Priority": "high"},
        )
        urllib.request.urlopen(req, timeout=15)
        log.info("ntfy sent title=%r", title)
    except Exception as exc:
        log.warning("ntfy failed: %s", exc)


def _tail_bytes(path: Path, n: int = 400_000) -> str:
    if not path.is_file():
        return ""
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - n))
        return f.read().decode("utf-8", errors="replace")


def _screencap(serial: str, label: str) -> Path | None:
    remote = "/sdcard/Download/ads_watch.png"
    local = SHOT_DIR / f"{label}_{int(time.time())}.png"
    try:
        subprocess.run(
            [ADB, "-s", serial, "shell", "screencap", "-p", remote],
            check=False,
            capture_output=True,
            timeout=20,
        )
        subprocess.run(
            [ADB, "-s", serial, "pull", remote, str(local)],
            check=False,
            capture_output=True,
            timeout=20,
        )
        return local if local.is_file() and local.stat().st_size > 1000 else None
    except Exception as exc:
        log.warning("screencap %s: %s", serial, exc)
        return None


def _focus_url(serial: str) -> str:
    try:
        r = subprocess.run(
            [ADB, "-s", serial, "shell", "dumpsys", "activity", "activities"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        out = r.stdout or ""
        if "getdabflow" in out.lower():
            return "dabflow"
        if "chromium" in out.lower() or "chrome" in out.lower():
            return "browser"
        return "other"
    except Exception:
        return "unknown"


def farm_alive() -> bool:
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -and $_.CommandLine -match 'run_farm_354' } | "
        "Measure-Object | Select-Object -ExpandProperty Count"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        return int((r.stdout or "0").strip() or "0") > 0
    except ValueError:
        return False


def analyze_chunk(text: str) -> dict:
    return {
        "mantis_fail": len(_MANTIS_FAIL.findall(text)),
        "mantis_ok": len(_MANTIS_OK.findall(text)),
        "ad_fallback": len(_AD_FALLBACK.findall(text)),
        "temp_direct": len(_TEMPORARY_DIRECT.findall(text)),
        "seq_lines": _SEQ_DONE.findall(text)[-12:],
    }


def main() -> int:
    log.info("ads_watch start interval=%ss", INTERVAL_S)
    last_pos = FARM_LOG.stat().st_size if FARM_LOG.is_file() else 0
    last_alert = 0.0
    window_fails = 0
    window_ok = 0
    window_fallback = 0

    while True:
        try:
            alive = farm_alive()
            if not alive:
                log.warning("farm_354 NOT running")
                if time.time() - last_alert > ALERT_COOLDOWN_S:
                    _ntfy("FamFlow farm missing", "[FamFlow] ads_watch: run_farm_354.py not running")
                    last_alert = time.time()

            if FARM_LOG.is_file():
                size = FARM_LOG.stat().st_size
                if size < last_pos:
                    last_pos = 0  # rotated/truncated
                with FARM_LOG.open("rb") as f:
                    f.seek(last_pos)
                    chunk = f.read().decode("utf-8", errors="replace")
                    last_pos = f.tell()
                stats = analyze_chunk(chunk)
                window_fails += stats["mantis_fail"]
                window_ok += stats["mantis_ok"]
                window_fallback += stats["ad_fallback"]
                if chunk.strip():
                    log.info(
                        "delta mantis_ok=%d mantis_fail=%d fallback=%d direct=%d seq=%s",
                        stats["mantis_ok"],
                        stats["mantis_fail"],
                        stats["ad_fallback"],
                        stats["temp_direct"],
                        stats["seq_lines"][-3:],
                    )

            # Visual sample: any phone on DabFlow
            for name, ser in PHONES.items():
                kind = _focus_url(ser)
                if kind == "dabflow":
                    shot = _screencap(ser, name.replace(".", "_"))
                    log.info("dabflow visible %s shot=%s", name, shot)

            # CDP inject is chronically broken on MuMu (CachedFlag resets); ads still paint.
            # Do NOT ntfy FAIL=N spam — log only. Alert only when farm process is dead (above).
            if window_fails + window_ok + window_fallback > 40:
                if window_fails and window_ok == 0:
                    log.info(
                        "CDP inject still down (fail=%d ok=%d) — not alerting; Path3/ads separate",
                        window_fails,
                        window_ok,
                    )
                window_fails = window_ok = window_fallback = 0

            state = {
                "ts": _utc(),
                "farm_alive": alive,
                "mantis_fail_window": window_fails,
                "mantis_ok_window": window_ok,
                "fallback_window": window_fallback,
            }
            (LOG_DIR / "ads_watch_state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception as exc:
            log.exception("watch loop error: %s", exc)

        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    raise SystemExit(main())
