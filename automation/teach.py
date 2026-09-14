"""
Teach Mode - record taps on the first phone, replay on all others staggered.
Uses ADB device serials - works with any connected Android device.
"""
import json
import re
import random
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from adb_paths import adb_executable

_SUBPROC_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

_DEVICE_RE = re.compile(r'^/dev/input/event\d+$')
_HEX_DEC_RE = re.compile(r'^[0-9A-Fa-f]+$')

from config import REC_DIR

REC_DIR.mkdir(exist_ok=True)
_recording_active = False
_recording_thread: threading.Thread | None = None
_current_file: Path | None = None


def _adb(serial: str, *args) -> str:
    exe = adb_executable()
    try:
        r = subprocess.run(
            [exe, "-s", serial, *args],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=_SUBPROC_FLAGS,
        )
        return r.stdout.strip()
    except Exception:
        return ""



def _parse_getevent_line(line: str) -> tuple[str, str, str, str] | None:
    """Parse ``getevent -t`` output into (device, type, code, value) hex fields.

    Formats:
      ``/dev/input/event1: 0003 0035 00000258``
      ``[  1234.567890] /dev/input/event1: 0003 0035 00000258``
    """
    parts = line.split()
    if not parts:
        return None
    idx = 0
    if parts[0].startswith("["):
        if parts[0].endswith("]"):
            idx = 1
        elif len(parts) > 1 and parts[1].endswith("]"):
            idx = 2
        else:
            idx = 1
    if len(parts) < idx + 4:
        return None
    device = parts[idx].rstrip(":")
    etype, code, value = parts[idx + 1], parts[idx + 2], parts[idx + 3]
    if not (
        _DEVICE_RE.match(device)
        and _HEX_DEC_RE.match(etype)
        and _HEX_DEC_RE.match(code)
        and _HEX_DEC_RE.match(value)
    ):
        return None
    return device, etype, code, value


def _hex_to_sendevent_arg(raw: str) -> str | None:
    """Convert getevent hex tokens to decimal ints for ``sendevent``."""
    text = str(raw).strip()
    if not _HEX_DEC_RE.match(text):
        return None
    try:
        return str(int(text, 16))
    except ValueError:
        return None


def recording_event_count(path: str | Path | None) -> int:
    """How many captured events are in a recording file. Missing or empty is 0."""
    if not path:
        return 0
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return 0
    return len(data) if isinstance(data, list) else 0


def start_recording(serial: str) -> str | None:
    """Start getevent. Returns the file path only if the process is still running."""
    global _recording_active, _recording_thread, _current_file

    ts = int(time.time())
    _current_file = REC_DIR / f"session_{ts}.rec"
    _recording_active = True
    events: list[dict] = []
    start_time = time.time()
    started = threading.Event()
    failed: list[str] = []

    def record():
        exe = adb_executable()
        # ``-t`` keeps timestamps + numeric hex codes. ``-l`` (labels) breaks
        # sendevent replay because type/code become EV_ABS / ABS_* strings.
        try:
            proc = subprocess.Popen(
                [exe, "-s", serial, "shell", "getevent", "-t"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                creationflags=_SUBPROC_FLAGS,
            )
        except Exception as exc:
            failed.append(str(exc))
            started.set()
            return
        time.sleep(0.4)
        if proc.poll() is not None:
            failed.append("getevent exited")
            started.set()
            try:
                proc.stdout.close()
            except Exception:
                pass
            return
        started.set()
        try:
            for line in proc.stdout:
                if not _recording_active:
                    break
                line = line.strip()
                if not line:
                    continue
                parsed = _parse_getevent_line(line)
                if not parsed:
                    continue
                device, event_type, event_code, event_value = parsed
                events.append({
                    "t":     round(time.time() - start_time, 3),
                    "d":     device,
                    "type":  event_type,
                    "code":  event_code,
                    "value": event_value,
                })
        finally:
            proc.terminate()
            try:
                proc.stdout.close()
            except Exception:
                pass
            if _current_file is not None:
                _current_file.write_text(json.dumps(events), encoding="utf-8")

    _recording_thread = threading.Thread(target=record, daemon=True)
    _recording_thread.start()
    if not started.wait(8) or failed:
        _recording_active = False
        _current_file = None
        return None
    return str(_current_file)


def stop_recording() -> str | None:
    """Stop getevent. Returns the file only if at least one tap was captured."""
    global _recording_active, _recording_thread, _current_file
    _recording_active = False
    if _recording_thread:
        _recording_thread.join(timeout=3)
    path = _current_file
    if path is None or recording_event_count(path) < 1:
        return None
    return str(path)


def replay_on_phone(serial: str, recording_path: str) -> int:
    """Replay a recording on a specific phone using sendevent.

    Works without root on AVD emulators. Each event is sent with a 3-second
    timeout so a dead device never hangs the replay.
    """
    try:
        data = json.loads(Path(recording_path).read_text(encoding="utf-8"))
    except (ValueError, OSError, TypeError):
        return 0
    if not isinstance(data, list) or not data:
        return 0

    last_t = 0.0
    sent = 0
    for entry in data:
        try:
            t = float(entry.get("t", last_t) or 0.0)
        except (TypeError, ValueError):
            t = last_t
        delay = t - last_t
        if delay > 0:
            time.sleep(delay)
        last_t = t

        d     = entry.get("d", "")
        etype = _hex_to_sendevent_arg(entry.get("type", ""))
        code  = _hex_to_sendevent_arg(entry.get("code", ""))
        value = _hex_to_sendevent_arg(entry.get("value", ""))
        if (not _DEVICE_RE.match(str(d))
                or etype is None
                or code is None
                or value is None):
            continue
        try:
            result = subprocess.run(
                [
                    adb_executable(),
                    "-s",
                    serial,
                    "shell",
                    "sendevent",
                    d,
                    etype,
                    code,
                    value,
                ],
                capture_output=True,
                timeout=3,
                creationflags=_SUBPROC_FLAGS,
            )
            if result.returncode == 0:
                sent += 1
        except subprocess.TimeoutExpired:
            break  # Device went offline - stop replaying
        except Exception:
            pass
    return sent


def replay_all(
    phones: list[dict],
    recording_path: str,
    delay_secs: int = 60,
    on_complete: Callable | None = None,
):
    def run():
        sent = 0
        for i, phone in enumerate(phones):
            if i > 0:
                actual = max(0.1, delay_secs + random.uniform(-delay_secs * 0.3, delay_secs * 0.3))
                time.sleep(actual)
            sent += replay_on_phone(phone["serial"], recording_path)
        if on_complete:
            on_complete(sent)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def list_recordings() -> list[dict]:
    out = []
    for f in sorted(REC_DIR.glob("session_*.rec"), reverse=True):
        try:
            data = json.loads(f.read_text())
            out.append({
                "name":     f.name,
                "path":     str(f),
                "steps":    len(data),
                "duration": round(data[-1]["t"], 1) if data else 0,
            })
        except Exception:
            continue
    return out
