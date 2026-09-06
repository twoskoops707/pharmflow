#!/usr/bin/env python3
"""Overnight x86 AVD watchdog — diagnose/fix ADB first; never kill emulators."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import automation.no_window  # noqa: E402,F401  — hide adb/emulator consoles
from automation.win_subprocess import hidden_run_kwargs  # noqa: E402

ADB = r"C:\CPharm\bundled\adb.exe"
EMU = os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Android\Sdk\emulator\emulator.exe")
AVD = "farmphone0"
LOG = Path(r"C:\CPharm\logs")
HB = LOG / "emu_overnight_watchdog_heartbeat.txt"


def devices() -> str:
    try:
        out = subprocess.check_output(
            [ADB, "devices"], text=True, timeout=15, **hidden_run_kwargs()
        )
    except (subprocess.SubprocessError, OSError) as e:
        return f"ERROR:{e}"
    return out


def online() -> bool:
    raw = devices()
    if raw.startswith("ERROR:"):
        return False
    return any(
        line.strip().endswith("\tdevice") and "emulator-" in line
        for line in raw.splitlines()
    )


def _emu_process_running() -> bool:
    """True if emulator.exe already alive — do not spawn duplicates."""
    if psutil is not None:
        for p in psutil.process_iter(["name"]):
            try:
                if str(p.info.get("name") or "").lower() == "emulator.exe":
                    return True
            except (psutil.Error, OSError):
                continue
        return False
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq emulator.exe"],
            text=True,
            timeout=15,
            **hidden_run_kwargs(),
        )
        return "emulator.exe" in out.lower()
    except (subprocess.SubprocessError, OSError):
        return False


def _fix_adb() -> None:
    """Prefer diagnose/fix over launching another emulator."""
    try:
        subprocess.run(
            [ADB, "start-server"],
            capture_output=True,
            timeout=20,
            **hidden_run_kwargs(),
        )
    except (subprocess.SubprocessError, OSError):
        pass


def start_emu() -> bool:
    if not os.path.isfile(EMU):
        return False
    if _emu_process_running():
        return False
    subprocess.Popen(
        [EMU, "-avd", AVD, "-no-snapshot-save", "-no-boot-anim", "-gpu", "swiftshader_indirect", "-memory", "2048"],
        cwd=os.path.dirname(EMU),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return True


def pin(serial: str = "emulator-5554") -> None:
    for args in (
        [ADB, "-s", serial, "reverse", "tcp:8218", "tcp:8218"],
        [ADB, "-s", serial, "reverse", "tcp:8118", "tcp:8118"],
        [ADB, "-s", serial, "shell", "settings", "put", "global", "http_proxy", "127.0.0.1:8218"],
    ):
        try:
            subprocess.run(args, timeout=20, capture_output=True, **hidden_run_kwargs())
        except (subprocess.SubprocessError, OSError):
            pass


def main() -> None:
    LOG.mkdir(parents=True, exist_ok=True)
    while True:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        ok = online()
        action = "ok"
        if not ok:
            # Diagnose/fix ADB first — offline often means adb died, not the AVD.
            _fix_adb()
            time.sleep(2)
            if online():
                action = "adb_fixed"
            elif _emu_process_running():
                action = "emu_alive_adb_down"
            else:
                action = "restart"
                started = start_emu()
                if not started and not os.path.isfile(EMU):
                    action = "no_emulator_binary"
                else:
                    for _ in range(60):
                        time.sleep(5)
                        if online():
                            pin()
                            action = "restarted"
                            break
                    else:
                        action = "restart_failed"
        else:
            # soft pin every loop
            try:
                lines = [
                    l
                    for l in devices().splitlines()
                    if "emulator-" in l and l.strip().endswith("device")
                ]
                ser = lines[0].split()[0] if lines else "emulator-5554"
                pin(ser)
            except (IndexError, OSError):
                pass
        try:
            HB.write_text(f"{ts} online={int(ok)} action={action}\n", encoding="utf-8")
        except OSError:
            pass
        time.sleep(45)


if __name__ == "__main__":
    main()
