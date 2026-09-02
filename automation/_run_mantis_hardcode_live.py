#!/usr/bin/env python3
"""Run one mantis-hardcode test sequence on MuMu via execute_steps (no wizard GUI)."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CPHARM = Path(r"C:\CPharm") if os.name == "nt" else Path.home() / "CPharm"
DEFAULT_SEQ = (
    "900x1600/ad/mantis-hardcode/"
    "dabflow__mantis_hardcode__01__mat-ceramic__conc-distillate__heat-butane.json"
)

sys.path.insert(0, str(ROOT / "wizard"))
sys.path.insert(0, str(ROOT / "automation"))
os.environ["CPHARM_HUMAN_VARIATION"] = "0"
os.environ.setdefault("CPHARM_USE_SHELL_WM_FOCUS_CHEAT", "1")

import tor_manager
from adb_paths import adb_executable
from sequence_normalize import normalize_automation_steps, unwrap_sequence_document
from setup_wizard import execute_steps

adb = adb_executable()


def _cpharm_root() -> Path:
    raw = (os.environ.get("CPHARM_HOME") or os.environ.get("CPHARM_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    if DEFAULT_CPHARM.is_dir():
        return DEFAULT_CPHARM
    repo_seq = ROOT / "sequences"
    if repo_seq.is_dir():
        return ROOT
    return DEFAULT_CPHARM


def list_adb_states() -> list[tuple[str, str]]:
    out = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=30).stdout or ""
    rows: list[tuple[str, str]] = []
    for ln in out.splitlines():
        if "\t" not in ln:
            continue
        serial, state = ln.split("\t", 1)
        serial, state = serial.strip(), state.strip()
        if serial and state and serial != "List of devices attached":
            rows.append((serial, state))
    return rows


def pick_serial(preferred: str | None = None, *, wait_secs: float = 0.0) -> str:
    deadline = time.monotonic() + max(0.0, wait_secs)
    prefs = [preferred] if preferred else []
    prefs += [
        "10.0.2.108:5555",
        "10.0.2.229:5555",
        "10.0.2.69:5555",
        "10.0.2.179:5555",
        "10.0.2.168:5555",
        "10.0.2.204:5555",
    ]
    seen: set[str] = set()
    pref_order = [p for p in prefs if p and not (p in seen or seen.add(p))]

    def _pick_online(online: list[str]) -> str:
        for pref in pref_order:
            if pref in online:
                return pref
        return online[0] if online else ""

    while True:
        states = list_adb_states()
        online = [s for s, st in states if st == "device"]
        picked = _pick_online(online)
        if picked:
            return picked
        for pref in pref_order:
            if pref not in {s for s, st in states if st == "device"}:
                subprocess.run(
                    [adb, "connect", pref], capture_output=True, text=True, timeout=5
                )
        if time.monotonic() >= deadline:
            break
        if states:
            offline = ", ".join(f"{s}({st})" for s, st in states)
            print(f"[cpharm] waiting for online device; saw: {offline}", flush=True)
        time.sleep(3.0)
    return _pick_online([s for s, st in list_adb_states() if st == "device"])


def repair_proxy(serial: str) -> None:
    """Ensure Tor HTTPTunnel + adb reverse + http_proxy before any open_url (required for farm runs)."""
    idx = tor_manager.phone_idx_from_adb_serial(serial)
    port = tor_manager.http_proxy_port_for_phone_idx(idx)
    print(f"[cpharm] Tor setup serial={serial} phone_idx={idx} http_port={port}", flush=True)
    tor_manager.repair_adb_reverse_for_proxy(serial, idx)
    result = tor_manager.ensure_tor_and_proxy_for_phone(serial, idx)
    if not result.get("ok", True) and result.get("error"):
        raise RuntimeError(f"Tor/proxy not ready: {result.get('error')}")
    proxy = subprocess.run(
        [adb, "-s", serial, "shell", "settings", "get", "global", "http_proxy"],
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout.strip()
    print(f"[cpharm] device http_proxy={proxy!r} reverse={subprocess.run([adb, '-s', serial, 'reverse', '--list'], capture_output=True, text=True, timeout=15).stdout.strip()}", flush=True)
    if not proxy or proxy == "null":
        raise RuntimeError("http_proxy not set on device after Tor setup")
    tor_manager.kick_default_browser_after_proxy_teardown([serial])


def resolve_sequence(seq_arg: str, cpharm: Path) -> Path:
    p = Path(seq_arg)
    if p.is_file():
        return p.resolve()
    for base in (cpharm / "sequences", ROOT / "sequences"):
        candidate = base / seq_arg
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(f"sequence not found: {seq_arg}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Live-run one mantis-hardcode DabFlow sequence on MuMu.")
    ap.add_argument("--serial", default=None, help="ADB serial (default: first online device)")
    ap.add_argument("--sequence", default=DEFAULT_SEQ, help="Relative path under sequences/ or absolute")
    ap.add_argument(
        "--wait-device",
        type=float,
        default=0.0,
        help="Seconds to retry until an ADB serial is online (default 0)",
    )
    ap.add_argument(
        "--skip-tor-wait",
        action="store_true",
        help="Skip background Tor prewarm only (Tor still required on device via http_proxy)",
    )
    ap.add_argument(
        "--out",
        default=None,
        help="Result txt path (default: CPharm/MANTIS_HARDCODE_LIVE.txt)",
    )
    args = ap.parse_args()

    if args.skip_tor_wait:
        os.environ["CPHARM_SKIP_TOR_WAIT"] = "1"

    cpharm = _cpharm_root()
    seq_path = resolve_sequence(args.sequence, cpharm)
    out_path = Path(args.out) if args.out else cpharm / "MANTIS_HARDCODE_LIVE.txt"

    t0 = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    overall = "FAIL"
    fail_reason = ""
    serial = pick_serial(args.serial, wait_secs=float(args.wait_device or 0.0))

    if not serial:
        states = list_adb_states()
        state_line = ", ".join(f"{s}={st}" for s, st in states) if states else "none"
        out_path.write_text(
            f"result=FAIL\nreason=no_adb_device\nadb_states={state_line}\nstarted_at={started_at}\n"
            f"finished_at={datetime.now(timezone.utc).isoformat()}\nwall_sec=0\n",
            encoding="utf-8",
        )
        print("NO ONLINE ADB DEVICE — run `adb devices -l` on the host running MuMu", flush=True)
        print(f"adb states seen: {state_line}", flush=True)
        return 1

    print(f"adb devices:\n{subprocess.run([adb, 'devices'], capture_output=True, text=True, timeout=30).stdout or ''}", flush=True)
    print(f"sequence={seq_path}", flush=True)
    repair_proxy(serial)

    # CDP-capable browser + fingerprint flags required for on-site Mantis ads.
    try:
        from browser_setup import prepare_for_dabflow_open

        prepare_for_dabflow_open(serial, "https://getdabflow.app", log=print)
    except Exception as exc:
        print(f"[cpharm] dabflow browser prep warning: {exc}", flush=True)

    raw = json.loads(seq_path.read_text(encoding="utf-8-sig"))
    steps, meta = unwrap_sequence_document(raw)
    steps = normalize_automation_steps(steps)
    timer_wait = next((float(s["seconds"]) for s in steps if s.get("checkpoint") == "timer_complete"), 0.0)
    hardcode_url = meta.get("mantis_ad_url") or next(
        (s.get("url") for s in steps if s.get("type") == "open_url" and s.get("mantis_hardcode")),
        "",
    )

    try:
        for i, step in enumerate(steps):
            t = step.get("type", "")
            cp = step.get("checkpoint") or ""
            el = time.monotonic() - t0
            extra = f" url={step.get('url')}" if t == "open_url" and step.get("mantis_hardcode") else ""
            print(f"{el:7.1f}s step {i + 1}/{len(steps)} {t} {cp}{extra}", flush=True)
            if t == "wait" and cp == "timer_complete":
                print(f"  >>> TIMER WAIT {timer_wait}s START", flush=True)
            execute_steps([step], serial)
            if t == "wait" and cp == "timer_complete":
                print(f"  >>> TIMER WAIT END wall={time.monotonic() - t0 - el:.1f}s", flush=True)
        overall = "PASS"
    except Exception as exc:
        overall = "FAIL"
        fail_reason = f"{type(exc).__name__}: {exc}"
        print(traceback.format_exc(), flush=True)

    finished_at = datetime.now(timezone.utc).isoformat()
    elapsed = round(time.monotonic() - t0, 2)
    out_path.write_text(
        "\n".join(
            [
                f"result={overall}",
                f"device={serial}",
                f"sequence={seq_path}",
                f"mantis_ad_url={hardcode_url}",
                f"started_at={started_at}",
                f"finished_at={finished_at}",
                f"wall_sec={elapsed}",
                f"steps={len(steps)}",
                *( [f"fail_reason={fail_reason}"] if fail_reason else [] ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"DONE {overall} elapsed={elapsed}s -> {out_path}", flush=True)
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
