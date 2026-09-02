#!/usr/bin/env python3
"""Watch twskoops for USER ntfy messages and print agent wake sentinels.

Run under Cursor with notify_on_output on AGENT_LOOP_WAKE_ntfy so inbound
operator messages wake the agent (not just the auto-responder).

  py -u scripts/ntfy_agent_wake.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TOPIC = "twskoops"
BASE = f"https://ntfy.sh/{TOPIC}"
LOG_DIR = Path(r"C:\CPharm\logs")
STATE = LOG_DIR / "ntfy_agent_wake_state.json"
WAKE_LOG = LOG_DIR / "ntfy_agent_wake.log"
POLL_S = 15.0

_OWN_TITLE_PREFIXES = (
    "FamFlow",
    "Farm check-in",
    "Farm FIX",
    "Farm:",
    "[FamFlow]",
    "Agent reply",
    "StockFlow",
)
_OWN_BODY_PREFIXES = (
    "[FamFlow]",
    "Farm:",
    "Farm check-in",
    "Farm FIX",
    "FamFlow farm",
    "window: ",
    "run_farm_354",
    "debug + release OK",
    "workflow run:",
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg: str) -> None:
    line = f"{_utc()} {msg}"
    print(line, flush=True)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with WAKE_LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"seen_ids": []}


def _save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    # Cap seen ids
    ids = list(state.get("seen_ids") or [])[-500:]
    state["seen_ids"] = ids
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _is_own(title: str, text: str, tags) -> bool:
    t = (title or "").strip()
    b = (text or "").strip()
    for p in _OWN_TITLE_PREFIXES:
        if t.startswith(p):
            return True
    for p in _OWN_BODY_PREFIXES:
        if b.startswith(p):
            return True
    tag_list = tags if isinstance(tags, list) else []
    own_tags = {
        "speech_balloon",
        "robot",
        "chart_with_upwards_trend",
        "white_check_mark",
        "wrench",
        "clipboard",
        "phone",
    }
    if tag_list and own_tags.intersection(tag_list):
        if (
            t.startswith("FamFlow")
            or t.startswith("Farm check-in")
            or t.startswith("Farm FIX")
            or b.startswith("[FamFlow]")
            or b.startswith("Farm check-in")
            or b.startswith("Farm FIX")
            or b.startswith("window:")
        ):
            return True
    return False


def _poll(since: str = "30m") -> list[dict]:
    url = f"{BASE}/json?poll=1&since={since}"
    req = urllib.request.Request(url, headers={"Accept": "application/x-ndjson"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _log(f"poll err: {exc}")
        return []
    out: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("event") == "message":
            out.append(obj)
    return out


def _wake(msg_id: str, text: str) -> None:
    # Keep prompt short — agent reads inbox for full context.
    safe = (text or "").replace("\n", " ").replace('"', "'")[:180]
    payload = {
        "prompt": (
            "NTFY USER MESSAGE — reply on ntfy.twskoops with a Farm check-in "
            "(Status/Phones/cycle ran·OK·FAIL·Path3/IP/Tor/cycle end) and a separate "
            f"Farm FIX message if you repaired anything. Message: {safe}"
        ),
        "id": msg_id,
        "at": _utc(),
    }
    print(f"AGENT_LOOP_WAKE_ntfy {json.dumps(payload, ensure_ascii=False)}", flush=True)
    _log(f"WAKE id={msg_id} text={safe[:100]!r}")


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    state = _load_state()
    seen = set(state.get("seen_ids") or [])
    _log("ntfy_agent_wake starting topic=twskoops")
    print("NTFY_AGENT_WAKE_READY", flush=True)
    # Seed seen with current backlog so we only wake on NEW messages.
    for obj in _poll("2h"):
        mid = str(obj.get("id") or "")
        if mid:
            seen.add(mid)
    state["seen_ids"] = list(seen)
    _save_state(state)
    _log(f"seeded seen={len(seen)}")

    while True:
        try:
            for obj in _poll("10m"):
                mid = str(obj.get("id") or "")
                if not mid or mid in seen:
                    continue
                title = (obj.get("title") or "").strip()
                text = (obj.get("message") or "").strip()
                tags = obj.get("tags")
                seen.add(mid)
                state["seen_ids"] = list(seen)
                _save_state(state)
                if _is_own(title, text, tags):
                    continue
                if not text and not title:
                    continue
                _wake(mid, text or title)
        except Exception as exc:  # noqa: BLE001
            _log(f"loop err: {exc}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    raise SystemExit(main())
