#!/usr/bin/env python3
"""Session ntfy subscriber — streams twskoops into a local inbox + stdout.

Cursor watches stdout for NTFY_MSG lines so the agent can react mid-session.

  py -u scripts/ntfy_session_subscriber.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

TOPIC = "twskoops"
BASE = f"https://ntfy.sh/{TOPIC}"
INBOX = Path(r"C:\CPharm\logs\ntfy_inbox.jsonl")
STATUS = Path(r"C:\CPharm\logs\ntfy_subscriber_status.txt")
POLL_SINCE = "all"  # first connect gets recent cache; then live stream


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_status(msg: str) -> None:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(f"{_utc()} {msg}\n", encoding="utf-8")


def _append_inbox(obj: dict) -> None:
    INBOX.parent.mkdir(parents=True, exist_ok=True)
    with INBOX.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _handle_message(raw: dict) -> None:
    if raw.get("event") != "message":
        return
    text = (raw.get("message") or "").strip()
    title = (raw.get("title") or "").strip()
    entry = {
        "received_at": _utc(),
        "id": raw.get("id"),
        "time": raw.get("time"),
        "title": title,
        "message": text,
        "priority": raw.get("priority"),
        "tags": raw.get("tags"),
    }
    _append_inbox(entry)
    # One-line marker for Cursor notify_on_output (keep under ~200 chars).
    preview = text.replace("\n", " | ")[:160]
    if title:
        print(f"NTFY_MSG title={title!r} body={preview!r}", flush=True)
    else:
        print(f"NTFY_MSG body={preview!r}", flush=True)


def _stream_once() -> None:
    url = f"{BASE}/json?since={POLL_SINCE}"
    req = urllib.request.Request(url, headers={"Accept": "application/x-ndjson"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        _write_status("connected")
        print("NTFY_SUBSCRIBER_READY topic=twskoops", flush=True)
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
                continue
            if ev == "open":
                print("NTFY_OPEN", flush=True)
                continue
            _handle_message(raw)


def main() -> int:
    INBOX.parent.mkdir(parents=True, exist_ok=True)
    backoff = 2.0
    while True:
        try:
            _write_status("connecting")
            print(f"NTFY_CONNECTING {_utc()}", flush=True)
            _stream_once()
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            _write_status(f"reconnect after error: {exc}")
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
