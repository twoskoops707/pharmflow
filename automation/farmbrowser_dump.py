"""
FarmBrowser dump — extract identity, proxy status, page title, and device
info from every phone running FarmBrowser via ADB broadcast.

Usage (CLI):
    python farmbrowser_dump.py                  # dump all phones
    python farmbrowser_dump.py 10.0.2.130:5555  # dump one phone
    python farmbrowser_dump.py --json            # JSON output
    python farmbrowser_dump.py --watch           # refresh every 5s

Usage (module):
    from farmbrowser_dump import dump_phone, dump_all
    print(dump_all())
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import Optional

_SUBPROC_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

_FARMBROWSER_PKG = "com.farmbrowser.stealth.debug"
_FARMBROWSER_PKG_RELEASE = "com.farmbrowser.stealth"
_BROADCAST_ACTION = "com.farmbrowser.stealth.CONTROL"


def _adb_executable() -> str:
    from adb_paths import adb_executable
    return adb_executable()


def _shell(serial: str, *args: str, timeout: int = 15) -> subprocess.CompletedProcess:
    exe = _adb_executable()
    try:
        return subprocess.run(
            [exe, "-s", serial, "shell", *args],
            capture_output=True, text=True, errors="replace",
            timeout=timeout, creationflags=_SUBPROC_FLAGS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(
            args=[exe, "-s", serial, "shell", *args],
            returncode=1, stdout="", stderr=str(exc),
        )


def _broadcast(serial: str, action: str, extras: dict | None = None) -> str:
    """Send a broadcast and return the resultData string."""
    for pkg in (_FARMBROWSER_PKG, _FARMBROWSER_PKG_RELEASE):
        cmd = [
            "am", "broadcast",
            "-a", _BROADCAST_ACTION,
            "-n", f"{pkg}/com.farmbrowser.stealth.browser.FarmBrowserReceiver",
            "--es", "action", action,
            "--receiver-include-background",
        ]
        if extras:
            for k, v in extras.items():
                if isinstance(v, bool):
                    cmd.extend(["--ez", k, str(v).lower()])
                elif isinstance(v, int):
                    cmd.extend(["--ei", k, str(v)])
                else:
                    cmd.extend(["--es", k, str(v)])
        r = _shell(serial, *cmd, timeout=10)
        stdout = (r.stdout or "").strip()
        # Parse resultData from:
        #   Broadcast completed: result=-1, data="..."
        # or:  Broadcast completed: result=-1, data="{...}"
        if "Broadcast completed" in stdout and "data=" in stdout:
            # Find the data= marker and extract everything after it
            idx = stdout.index("data=")
            data_val = stdout[idx + 5:]  # everything after "data="
            # Strip wrapping quotes if present
            if data_val.startswith('"'):
                # Find the LAST quote — data may contain inner quotes (JSON)
                last_quote = data_val.rfind('"')
                if last_quote > 0:
                    data_val = data_val[1:last_quote]
            # Unescape ADB shell escapes
            data_val = data_val.replace('\\"', '"')
            return data_val
        # result=0 with no data means FarmBrowser is not running (activity was null)
        if "result=0" in stdout and "data=" not in stdout:
            return ""
        # Fallback: check if package was not installed
        if "does not exist" in stdout or "not found" in stdout:
            continue
        # Return raw output if we can't parse
        return stdout
    return ""


def dump_phone(serial: str) -> dict:
    """Full state dump from one phone. Returns parsed JSON dict."""
    raw = _broadcast(serial, "dump")
    if not raw:
        return {"serial": serial, "error": "no response (FarmBrowser not running?)"}
    try:
        data = json.loads(raw)
        data["serial"] = serial
        return data
    except json.JSONDecodeError:
        return {"serial": serial, "error": "invalid JSON", "raw": raw[:500]}


def dump_status(serial: str) -> dict:
    """Lightweight status (no page title/URL). Returns parsed JSON dict."""
    raw = _broadcast(serial, "status")
    if not raw:
        return {"serial": serial, "error": "no response"}
    try:
        data = json.loads(raw)
        data["serial"] = serial
        return data
    except json.JSONDecodeError:
        return {"serial": serial, "error": "invalid JSON", "raw": raw[:500]}


def dump_all(serials: list[str] | None = None) -> list[dict]:
    """Dump all phones. If serials is None, auto-discover from adb devices."""
    if serials is None:
        serials = _discover_serials()
    return [dump_phone(s) for s in serials]


def _discover_serials() -> list[str]:
    """List connected ADB devices."""
    exe = _adb_executable()
    try:
        r = subprocess.run(
            [exe, "devices"],
            capture_output=True, text=True, errors="replace",
            timeout=10, creationflags=_SUBPROC_FLAGS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    serials = []
    for line in (r.stdout or "").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def format_table(dumps: list[dict]) -> str:
    """Format a list of phone dumps as a readable table."""
    if not dumps:
        return "No phones found."

    lines = []
    header = f"{'Serial':<22} {'Identity':<20} {'Proxy':<18} {'Page Title':<40} {'Cookies':>6}"
    lines.append(header)
    lines.append("-" * len(header))

    for d in dumps:
        serial = d.get("serial", "?")
        if "error" in d:
            lines.append(f"{serial:<22} ERROR: {d['error']}")
            continue

        identity = d.get("identity", "?")
        proxy_mode = d.get("proxy_mode", "DIRECT")
        proxy_host = d.get("proxy_host", "")
        proxy_port = d.get("proxy_port", "")
        proxy_str = proxy_mode
        if proxy_host:
            proxy_str = f"{proxy_host}:{proxy_port}" if proxy_port else proxy_host

        page_title = d.get("page_title", "")
        if len(page_title) > 38:
            page_title = page_title[:35] + "..."

        cookies = d.get("cookie_count", "?")

        lines.append(f"{serial:<22} {identity:<20} {proxy_str:<18} {page_title:<40} {cookies:>6}")

    return "\n".join(lines)


def format_detail(d: dict) -> str:
    """Format a single phone dump as a detailed multi-line string."""
    if "error" in d:
        return f"  {d.get('serial', '?')}: ERROR — {d['error']}"

    lines = []
    lines.append(f"  Serial:       {d.get('serial', '?')}")
    lines.append(f"  Identity:     {d.get('identity', '?')} (index {d.get('identity_index', '?')})")
    lines.append(f"  UA:           {d.get('user_agent', '?')[:80]}")
    lines.append(f"  Proxy:        {d.get('proxy_mode', 'DIRECT')} {d.get('proxy_host', '')}:{d.get('proxy_port', '')}")
    lines.append(f"  Device:       {d.get('device_brand', '?')} {d.get('device_model', '?')} ({d.get('device_key', '?')})")
    lines.append(f"  Android:      {d.get('android_version', '?')}")
    lines.append(f"  Screen:       {d.get('screen_w', '?')}x{d.get('screen_h', '?')} @{d.get('dpi', '?')}dpi")
    lines.append(f"  GPU:          {d.get('gpu', '?')}")
    lines.append(f"  Page Title:   {d.get('page_title', '(empty)')}")
    lines.append(f"  Page URL:     {d.get('page_url', '(empty)')}")
    lines.append(f"  History:      {d.get('history_size', 0)} entries (back={d.get('can_go_back')}, fwd={d.get('can_go_forward')})")
    lines.append(f"  Cookies:      {d.get('cookie_count', 0)}")
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="FarmBrowser phone dump utility")
    parser.add_argument("serials", nargs="*", help="Phone serials (default: all connected)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--detail", action="store_true", help="Detailed per-phone output")
    parser.add_argument("--watch", type=int, default=0, metavar="SECONDS",
                        help="Refresh every N seconds (0 = once)")
    parser.add_argument("--status", action="store_true",
                        help="Lightweight status only (no page title)")
    args = parser.parse_args()

    serials = args.serials if args.serials else None

    while True:
        if args.watch:
            # Clear screen on refresh
            print("\033[2J\033[H", end="")

        if args.status:
            dumps = [dump_status(s) for s in (serials or _discover_serials())]
        else:
            dumps = [dump_phone(s) for s in (serials or _discover_serials())]

        if args.json:
            print(json.dumps(dumps, indent=2))
        elif args.detail:
            for d in dumps:
                print(format_detail(d))
                print()
        else:
            print(f"=== FarmBrowser Dump ({time.strftime('%H:%M:%S')}) ===")
            print(format_table(dumps))
            print()

        if not args.watch:
            break
        time.sleep(args.watch)


if __name__ == "__main__":
    main()
