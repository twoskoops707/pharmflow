#!/usr/bin/env python3
"""FREEBUFF loop — runs agent_unison_freebuff_tick every 45s."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TICK = ROOT / "scripts" / "agent_unison_freebuff_tick.py"


def _python() -> str:
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    return pyw if Path(pyw).is_file() else sys.executable
LOG = Path(r"C:\CPharm\logs\freebuff_loop.log")
INTERVAL = 45
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def main() -> int:
    _log("freebuff_loop armed interval=45s")
    while True:
        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(ROOT)
            r = subprocess.run(
                [_python(), "-u", str(TICK)],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
                creationflags=FLAGS,
            )
            out = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
            _log(f"tick exit={r.returncode} " + (out[0][:120] if out else "empty"))
        except subprocess.TimeoutExpired:
            _log("tick TIMEOUT")
        except Exception as exc:
            _log(f"tick_err:{exc}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
