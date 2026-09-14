#!/usr/bin/env python3
"""Smart ntfy auto-responder for twskoops.

Reads inbound user message text, classifies intent, answers with live farm
data, and executes safe commands (start/stop farm, clear+home phones).

  py -u scripts/ntfy_farm_responder.py

Logs: C:\\CPharm\\logs\\ntfy_farm_responder.log
Inbox: C:\\CPharm\\logs\\ntfy_inbox.jsonl
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

# Reuse status helpers from the hourly reporter + shared check-in format.
_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import automation.no_window  # noqa: E402,F401  — hide helper consoles
import farm_hourly_ntfy as farm  # noqa: E402
from automation.cpharm_exe_owned import exe_owns_farm  # noqa: E402
from automation.farm_checkin import format_checkin, gather_checkin  # noqa: E402
from automation.process_scan import cpharm_exe_pids  # noqa: E402
from wizard.farm_control import start_farm  # noqa: E402

TOPIC = "twskoops"
BASE = f"https://ntfy.sh/{TOPIC}"
NTFY_URL = BASE
LOG_DIR = Path(r"C:\CPharm\logs")
INBOX = LOG_DIR / "ntfy_inbox.jsonl"
STATUS = LOG_DIR / "ntfy_farm_responder_status.txt"
WATCHER_LOG = LOG_DIR / "ntfy_farm_responder.log"
REPLY_PREFIX = "[FamFlow]"
REPO = _REPO
PYTHON = sys.executable
PHONE_NAMES = ("vm0.gmadoa", "vm1.gmadoa", "vm2.gmadoa", "vm3.gmadoa", "vm4.gmadoa", "vm5.gmadoa")
# Default farm size is 6 MuMu x64 phones (vm0–vm5). Override via CPHARM_FARM_PHONES.
EXPECTED_PHONES = 6
# Legacy fallbacks only - live serials come from MuMuFarmOps / adb devices.
PHONE_SERIALS_FALLBACK = {
    "vm0.gmadoa": "10.0.2.86:5555",
    "vm1.gmadoa": "10.0.2.154:5555",
    "vm2.gmadoa": "10.0.2.69:5555",
    "vm3.gmadoa": "10.0.2.149:5555",
    "vm4.gmadoa": "10.0.2.161:5555",
    "vm5.gmadoa": "10.0.2.16:5555",
}

# Titles / body prefixes that mean "we posted this" - do not reply.
_OWN_TITLE_PREFIXES = (
    "FamFlow",
    "Farm check-in",
    "Farm FIX",
    "Farm:",
    "[FamFlow]",
    "Agent reply",
    "StockFlow",  # CI / release bots - never treat as operator chat
)
_OWN_BODY_PREFIXES = (
    "[FamFlow]",
    "Farm:",
    "Farm check-in",
    "Farm FIX",
    "FamFlow farm",
    "Heard you.",
    "window: ",
    "run_farm_354",
    "debug + release OK",
    "workflow run:",
)

IntentHandler = Callable[[str], str]

# Set True after ntfy stream urlopen succeeds so reconnect backoff can reset.
_STREAM_CONNECTED = False


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _setup_log() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("ntfy_farm_responder")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(WATCHER_LOG, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


log = _setup_log()


def _write_status(msg: str) -> None:
    STATUS.write_text(f"{_utc()} {msg}\n", encoding="utf-8")


def _append_inbox(obj: dict) -> None:
    with INBOX.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _is_own_message(title: str, text: str, tags) -> bool:
    t = (title or "").strip()
    b = (text or "").strip()
    for p in _OWN_TITLE_PREFIXES:
        if t.startswith(p) or t == p.rstrip(":"):
            return True
    for p in _OWN_BODY_PREFIXES:
        if b.startswith(p):
            return True
    tag_list = tags if isinstance(tags, list) else []
    own_tags = {
        "chart_with_upwards_trend",
        "eyes",
        "skull",
        "warning",
        "hourglass",
        "speech_balloon",
        "white_check_mark",
        "robot",
    }
    if tag_list and own_tags.intersection(tag_list) and (
        t.startswith("FamFlow") or b.startswith("window:") or b.startswith("FamFlow") or b.startswith("[FamFlow]")
    ):
        return True
    return False


def _adb_bin() -> str:
    return os.environ.get("CPHARM_ADB") or r"C:\CPharm\bundled\adb.exe"


def _adb_devices() -> list[str]:
    try:
        out = subprocess.check_output(
            [_adb_bin(), "devices"],
            text=True,
            timeout=20,
            errors="replace",
        )
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        try:
            out = subprocess.check_output(
                ["adb", "devices"],
                text=True,
                timeout=20,
                errors="replace",
            )
        except (subprocess.SubprocessError, OSError, FileNotFoundError) as exc:
            log.warning("adb devices failed: %s", exc)
            return []
    serials: list[str] = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def _live_phone_serials() -> dict[str, str]:
    """Resolve current ADB serials for farm phones (IPs change across MuMu restarts)."""
    out: dict[str, str] = {}
    try:
        sys.path.insert(0, str(REPO))
        from wizard.mumu_farm_ops import MuMuFarmOps

        farm_ops = MuMuFarmOps()
        farm_ops.list_instances()
        farm_ops.refresh_serials()
        for name in PHONE_NAMES:
            inst = farm_ops.get_phone(name)
            if inst and inst.adb_serial:
                out[name] = inst.adb_serial
    except Exception as exc:
        log.warning("live serial resolve failed: %s", exc)
    if len(out) < 6:
        for name, serial in PHONE_SERIALS_FALLBACK.items():
            out.setdefault(name, serial)
    return out


def _reconnect_phones() -> tuple[int, list[str]]:
    missing: list[str] = []
    phone_serials = _live_phone_serials()
    for name, serial in phone_serials.items():
        target = serial if ":" in serial else f"{serial}:5555"
        try:
            subprocess.run(
                [_adb_bin(), "connect", target],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (subprocess.SubprocessError, OSError, FileNotFoundError):
            try:
                subprocess.run(
                    ["adb", "connect", target],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
            except (subprocess.SubprocessError, OSError, FileNotFoundError):
                missing.append(name)
    time.sleep(1.0)
    online = _adb_devices()
    for name, serial in phone_serials.items():
        base = serial.split(":")[0]
        if not any(base in s for s in online):
            if name not in missing:
                missing.append(name)
    return len(online), missing


def _progress_snapshot() -> dict:
    if not farm.PROGRESS.exists():
        return {}
    try:
        return json.loads(farm.PROGRESS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _last_start_line() -> str:
    if not farm.FARM_LOG.exists():
        return ""
    try:
        lines = farm.FARM_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-500:]
    except OSError:
        return ""
    for line in reversed(lines):
        if "START " in line and "phones" in line:
            return line.strip()
        if "ONLINE vm" in line:
            # keep scanning for START preferentially
            continue
    for line in reversed(lines):
        if re.search(r"ONLINE vm\d", line):
            return line.strip()
    return ""


def _online_from_log() -> list[str]:
    if not farm.FARM_LOG.exists():
        return []
    try:
        lines = farm.FARM_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-500:]
    except OSError:
        return []
    # Find last START block and collect ONLINE lines after previous START.
    start_idx = None
    for i in range(len(lines) - 1, -1, -1):
        if "START " in lines[i] and "phones" in lines[i]:
            start_idx = i
            break
    if start_idx is None:
        return []
    # ONLINE lines appear just before START
    found: list[str] = []
    for line in lines[max(0, start_idx - 20) : start_idx]:
        m = re.search(r"ONLINE (vm\d+\.gmadoa)", line)
        if m:
            found.append(m.group(1))
    return found


def _expected_phone_n() -> int:
    raw = (os.environ.get("CPHARM_FARM_PHONES") or "").strip()
    if raw:
        n = len([p for p in raw.split(",") if p.strip()])
        if n > 0:
            return n
    return EXPECTED_PHONES


def _recent_log_hits(patterns: list[str], *, limit: int = 3) -> list[str]:
    if not farm.FARM_LOG.exists():
        return []
    try:
        lines = farm.FARM_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
    except OSError:
        return []
    hits: list[str] = []
    for line in reversed(lines):
        if any(p in line for p in patterns):
            # Strip timestamp prefix if present for brevity.
            short = re.sub(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d+\s+\w+\s+", "", line).strip()
            hits.append(short[:110])
            if len(hits) >= limit:
                break
    return hits


def _live_status_text() -> str:
    """Operator check-in format for all auto-replies."""
    try:
        return format_checkin(gather_checkin())
    except Exception as exc:  # noqa: BLE001
        log.warning("check-in gather failed: %s", exc)
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        rows = farm.load_results(since)
        summary = farm.summarize(rows, window_label="last 60m")
        pids = farm.farm_pids()
        return (
            f"Farm check-in - {'UP' if pids else 'DOWN'}\n"
            f"This cycle: ran={summary['total']} · OK={summary['ok']} · FAIL={summary['fail']}\n"
            f"Path3={summary['path3_ok']}"
        )


def classify_intent(text: str) -> str:
    t = (text or "").strip().lower()
    if not t:
        return "unknown"
    if t in {"marco", "ping", "polo?"} or t.startswith("marco"):
        return "marco"
    if re.search(r"\b(help|commands|\?)\b", t) and len(t) < 40:
        return "help"
    if re.search(r"\b(clear|home)\b.*\b(phone|phones|all)\b|\b(clear|wipe).*(chrome|browser|phones?)\b|\bhome\s+phones?\b", t):
        return "clear_phones"
    if re.search(r"\b(stop|kill|halt|pause)\b.*\b(farm|runner|sequence)\b|\bfarm\b.*\b(stop|kill|halt)\b", t):
        return "farm_stop"
    if re.search(
        r"\b(start|restart|launch|spin\s*up|bring\s*up)\b.*\b(farm|all\s*six|6\s*phones?)\b"
        r"|\bfarm\b.*\b(start|restart)\b"
        r"|\brestart\b.*\b(phones?|farm)\b"
        r"|\ball\s*(six|6)\s*phones?\b",
        t,
    ):
        # "all six phones" shout without start verb → status-ish, but user wants action
        if (
            re.search(r"\b(start|restart|launch|spin\s*up|bring\s*up)\b", t)
            or "being used" in t
            or "!!!" in text
        ):
            return "farm_start"
        if re.fullmatch(r"all\s*(six|6)\s*phones?\s*!+", t) or t.strip("! ").lower() in {
            "all six phones",
            "all 6 phones",
        }:
            return "farm_start"
    if re.search(
        r"\b(status|how.*(farm|going|phones?)|progress|update|operational|adb|"
        r"how many|what.*(going|on)|why.*(zero|0|zeros)|seqs?|timers?|ads?|"
        r"broke|broken|dead|nothing)\b",
        t,
    ):
        return "status"
    if re.search(r"\b(progress|timers?|ads?|path\s*3|seqs?|sequences?)\b", t):
        return "progress"
    if "?" in t or re.search(r"\b(what|why|how|when|where|who|does|do you|can you|are you)\b", t):
        return "question"
    return "unknown"


def _cmd_stop_farm() -> str:
    pids = farm.farm_pids()
    if not pids:
        return "Farm already stopped (no run_farm_354 process)."
    killed: list[int] = []
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            killed.append(pid)
        except (subprocess.SubprocessError, OSError) as exc:
            return f"Tried to stop farm PIDs {pids}; failed on {pid}: {exc}"
    time.sleep(1.0)
    left = farm.farm_pids()
    return f"Stopped farm PIDs {killed}. Remaining={left or 'none'}."


def _cmd_start_farm(*, force_restart: bool = False) -> str:
    expect_n = _expected_phone_n()
    adb_n, missing = _reconnect_phones()
    pids = farm.farm_pids()
    if pids and not force_restart:
        online = _online_from_log()
        if len(online) >= expect_n and adb_n >= expect_n:
            return (
                f"Farm already UP pids={pids} with {len(online)}/{expect_n} phones in START log "
                f"and ADB {adb_n}/{expect_n}. Not restarting. {_live_status_text()}"
            )
        force_restart = True
    if pids and force_restart:
        stop_msg = _cmd_stop_farm()
        time.sleep(2.0)
        pids = farm.farm_pids()
    else:
        stop_msg = ""

    clear_note = ""
    if force_restart:
        clear_note = _cmd_clear_phones(quick=True)

    if cpharm_exe_pids() or exe_owns_farm():
        if pids:
            return (
                f"PharmFlow.exe already owns the farm pids={pids}. "
                f"ADB={adb_n}/{expect_n}. {_live_status_text()}"
            )
        return (
            "PharmFlow.exe is running — click Start farm in the PharmFlow window. "
            "This agent will not spawn a second Python farm. "
            f"ADB={adb_n}/{expect_n} missing={missing or 'none'}"
        )

    ok = start_farm(hours=0.0, takeover=True)
    bits = [
        stop_msg,
        clear_note,
        (
            "Started farm via CPharm start_farm (hours=0 daily caps)."
            if ok
            else "start_farm returned False — click Start farm in PharmFlow.exe."
        ),
        f"ADB={adb_n}/{expect_n} missing={missing or 'none'}.",
        _live_status_text(),
    ]
    return " ".join(b for b in bits if b)


def _cmd_clear_phones(*, quick: bool = False) -> str:
    script = LOG_DIR / "oneshot_all6_clear_home.py"
    if not script.exists():
        # inline minimal HOME+force-stop
        serials = _adb_devices()
        ok = 0
        for ser in serials:
            try:
                subprocess.run(
                    [_adb_bin(), "-s", ser, "shell", "am", "force-stop", "org.chromium.chrome"],
                    capture_output=True,
                    timeout=15,
                )
                subprocess.run(
                    [_adb_bin(), "-s", ser, "shell", "input", "keyevent", "3"],
                    capture_output=True,
                    timeout=15,
                )
                ok += 1
            except (subprocess.SubprocessError, OSError):
                continue
        return f"Clear/HOME via adb on {ok}/{len(serials)} devices."
    try:
        timeout = 90 if quick else 180
        out = subprocess.check_output(
            [PYTHON, "-u", str(script)],
            cwd=str(REPO),
            text=True,
            timeout=timeout,
            errors="replace",
        )
        # summarize last lines
        tail = " | ".join(out.strip().splitlines()[-6:])[:400]
        return f"Clear+HOME all 6 done. {tail}"
    except subprocess.TimeoutExpired:
        return "Clear+HOME timed out (partial). Check oneshot_all6 logs."
    except (subprocess.SubprocessError, OSError) as exc:
        return f"Clear+HOME failed: {exc}"


def _handle_marco(_text: str) -> str:
    return format_checkin(gather_checkin(note="polo - listening"))


def _handle_help(_text: str) -> str:
    return (
        "Commands: status | start farm | stop farm | clear phones | marco\n"
        "---\n"
        + format_checkin(gather_checkin())
    )


def _handle_status(text: str) -> str:
    status = _live_status_text()
    expect_n = _expected_phone_n()
    low = text.lower()
    if "zero" in low or re.search(r"\bwhy\b", low):
        return (
            "Note: idle/zeros early usually = hour-slot stagger wait, not dead farm.\n"
            "---\n"
            + status
        )
    if "how many" in low or "operational" in low or "all six" in low or "all 6" in low or "adb" in low:
        adb_n = len(_adb_devices())
        online = _online_from_log()
        return (
            f"Note: ADB {adb_n}/{expect_n}; farm START {len(online)}/{expect_n}"
            f" ({', '.join(online) or 'none'}).\n"
            "---\n"
            + status
        )
    return status


def _handle_progress(text: str) -> str:
    return _handle_status(text)


def _handle_farm_start(text: str) -> str:
    # Always scrub Cursor shell poison on farm start (User-env braces break agent Shell).
    try:
        script = LOG_DIR / "fix_cursor_shell.py"
        if script.is_file():
            subprocess.run(
                [PYTHON, "-u", str(script)],
                cwd=str(REPO),
                timeout=45,
                capture_output=True,
            )
    except (subprocess.SubprocessError, OSError):
        pass
    low = text.lower()
    force = bool(re.search(r"\b(restart|being used)\b", low))
    result = _cmd_start_farm(force_restart=force)
    return f"Farm FIX - {result}\n---\n{_live_status_text()}"


def _handle_farm_stop(_text: str) -> str:
    return f"Farm FIX - {_cmd_stop_farm()}\n---\n{_live_status_text()}"


def _handle_clear(text: str) -> str:
    low = text.lower()
    # Always scrub Cursor shell poison when clearing (oneshot also runs it).
    try:
        script = LOG_DIR / "fix_cursor_shell.py"
        if script.is_file():
            subprocess.run([PYTHON, "-u", str(script)], cwd=str(REPO), timeout=45, capture_output=True)
    except (subprocess.SubprocessError, OSError):
        pass
    result = _cmd_clear_phones()
    if re.search(r"\b(start|restart)\b", low):
        result += " " + _cmd_start_farm(force_restart=True)
    return f"Farm FIX - {result}\n---\n{_live_status_text()}"


def _handle_question(text: str) -> str:
    low = text.lower()
    status = _live_status_text()
    if "phone" in low or "farm" in low or "zero" in low or "adb" in low or "broke" in low:
        return _handle_status(text)
    return f"Re: {text[:80]!r}\n---\n{status}"


def _handle_unknown(text: str) -> str:
    return (
        f"Re: {text[:80]!r}\n"
        "cmds: status | start farm | stop farm | clear phones | marco | help\n"
        "---\n"
        + _live_status_text()
    )

HANDLERS: dict[str, IntentHandler] = {
    "marco": _handle_marco,
    "help": _handle_help,
    "status": _handle_status,
    "progress": _handle_progress,
    "farm_start": _handle_farm_start,
    "farm_stop": _handle_farm_stop,
    "clear_phones": _handle_clear,
    "question": _handle_question,
    "unknown": _handle_unknown,
}


def publish_reply(body: str, *, title: str = "Farm check-in") -> bool:
    data = body.encode("utf-8")
    req = urllib.request.Request(
        NTFY_URL,
        data=data,
        method="POST",
        headers={
            "Title": title,
            "Priority": "default",
            "Tags": "clipboard,phone",
            "Content-Type": "text/plain; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        log.info("reply OK bytes=%d", len(data))
        return True
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.error("reply FAILED: %s", exc)
        return False


def _handle_message(raw: dict, *, reply: bool) -> None:
    if raw.get("event") != "message":
        return
    text = (raw.get("message") or "").strip()
    title = (raw.get("title") or "").strip()
    tags = raw.get("tags")
    entry = {
        "received_at": _utc(),
        "id": raw.get("id"),
        "time": raw.get("time"),
        "title": title,
        "message": text,
        "priority": raw.get("priority"),
        "tags": tags,
    }
    _append_inbox(entry)
    preview = text.replace("\n", " | ")[:160]
    try:
        if title:
            print(f"NTFY_MSG title={title!r} body={preview!r}", flush=True)
        else:
            print(f"NTFY_MSG body={preview!r}", flush=True)
    except UnicodeEncodeError:
        print(f"NTFY_MSG id={raw.get('id')}", flush=True)

    if not reply:
        return
    if _is_own_message(title, text, tags):
        log.info("skip own msg id=%s title=%r", raw.get("id"), title[:40])
        return
    if not text and not title:
        return

    intent = classify_intent(text or title)
    log.info("inbound id=%s intent=%s text=%r", raw.get("id"), intent, (text or title)[:120])
    handler = HANDLERS.get(intent, _handle_unknown)
    try:
        body = handler(text or title)
    except Exception as exc:  # noqa: BLE001 - never crash the stream loop
        log.exception("handler failed intent=%s: %s", intent, exc)
        body = f"{REPLY_PREFIX} Error handling {intent}: {exc}. Live: {_live_status_text()}"
    log.info("outbound intent=%s bytes=%d", intent, len(body.encode("utf-8")))
    title_out = "Farm FIX" if body.startswith("Farm FIX") else "Farm check-in"
    publish_reply(body, title=("Farm FIX" if body.startswith("Farm FIX") else "Farm check-in"))


def _stream_once(*, reply: bool) -> None:
    global _STREAM_CONNECTED
    url = f"{BASE}/json?since=latest"
    req = urllib.request.Request(url, headers={"Accept": "application/x-ndjson"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        _STREAM_CONNECTED = True
        _write_status("connected")
        print("NTFY_RESPONDER_READY topic=twskoops", flush=True)
        log.info("stream open since=latest reply=%s", reply)
        while True:
            line = resp.readline()
            if not line:
                raise ConnectionError("stream closed")
            line = line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            ev = raw.get("event")
            if ev == "keepalive":
                _write_status("connected keepalive")
                continue
            if ev == "open":
                print("NTFY_OPEN", flush=True)
                continue
            _handle_message(raw, reply=reply)
            # Wake Cursor agent sessions that monitor this stdout / wake log.
            if raw.get("event") == "message" and not _is_own_message(
                (raw.get("title") or ""),
                (raw.get("message") or ""),
                raw.get("tags"),
            ):
                text = ((raw.get("message") or raw.get("title") or "").replace("\n", " "))[:160]
                print(
                    "AGENT_LOOP_WAKE_ntfy "
                    + json.dumps(
                        {
                            "prompt": (
                                "NTFY USER MESSAGE - reply on twskoops with a Farm check-in "
                                f"(Status/Phones/cycle ran·OK·FAIL·Path3/IP) plus Farm FIX if you repaired anything. Message: {text}"
                            ),
                            "id": raw.get("id"),
                            "at": _utc(),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )


def main() -> int:
    global _STREAM_CONNECTED
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    backoff = 2.0
    log.info("ntfy_farm_responder starting topic=%s (smart intents)", TOPIC)
    while True:
        try:
            _write_status("connecting")
            print(f"NTFY_CONNECTING {_utc()}", flush=True)
            _STREAM_CONNECTED = False
            _stream_once(reply=True)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            if _STREAM_CONNECTED:
                backoff = 2.0
            _write_status(f"reconnect after error: {exc}")
            log.warning("reconnect err=%r sleep=%.0fs", exc, backoff)
            print(f"NTFY_RECONNECT err={exc!r} sleep={backoff:.0f}s", flush=True)
            time.sleep(backoff)
            backoff = min(60.0, backoff * 1.5)
            continue
        except KeyboardInterrupt:
            _write_status("stopped")
            print("NTFY_STOPPED", flush=True)
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
