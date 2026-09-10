#!/usr/bin/env python3
"""CPharm Watchdog Agent — self-healing health monitor.

Monitors the CPharm farm and recovers what is safe to recover:

  - CPharm.exe main process alive?
  - Dashboard HTTP server (CPHARM_PORT, default 8080) answering?
  - ADB cloud/emulator endpoints reachable + reconnected?
  - Docker compose stack running (Redroid / helpers)?
  - Optional ntfy alerts on degraded<->recovered transitions.

Process reaper (built-in, every --reap-interval in watch mode):
  Classifies the live process table every sweep and kills ONLY what is
  provably stale — duplicate adb fork-servers, orphaned adb clients and
  `shell` clients stuck >180s (the timeout-leak that wedges MuMu), duplicate
  dashboard.py, dead-parent python helpers outside the farm allowlist, and
  Tor instances with a missing or duplicated config. Farm-owned/adopted
  processes are never touched (the farm re-creates Tor by ControlPort, so
  killing an adopted instance would break income). Kills require --apply; the
  sweep always reports counts so a monitoring log exists every minute.

Stealth uniqueness (--stealth) runs on the SAME sweep as the reaper:
  the exit-IP verification/rotation and stale-process cleanup share one
  --reap-interval (default 60s) maintenance tick instead of hammering the
  dashboard's /api/stealth/verify endpoint every check interval.

Safety model: nothing is killed except known duplicates/stale orphans when
(and only when) `--apply` is set; recovery actions restart the dashboard and
re-run `docker compose up` and `adb connect`. The agent never touches the
filesystem outside logs.

Flags (all optional):
  --watch                 run in a loop (agent mode) until interrupted
  --interval SECONDS      seconds between checks (default 15)
  --once                  a single pass then exit                    (default)
  --apply                 actually perform recovery actions (incl. stale kills)
  --no-reap               disable the kill pass (detection still logged)
  --reap-interval SECONDS min seconds between reaper sweeps (default 60)
  --reap-only             run a single maintenance sweep (reaper + stealth if
                          --stealth is given) and exit
  --repair-dashboard      (with --apply) respawn the dashboard if HTTP is down
  --repair-docker         (with --apply) `docker compose up -d` if stack is down
  --service NAME          limit Docker repair to one compose service
  --host / --start-port / --count   which ADB endpoints to monitor
  --alert                 send ntfy notifications on degraded/recovered edges
  --version / --help
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "cloud_phones" / "docker-compose.redroid.yml"
DASHBOARD_PY = ROOT / "automation" / "dashboard.py"
LOG_DIR = Path(os.environ.get("CPHARM_LOGS") or (ROOT / "logs"))
HEARTBEAT = LOG_DIR / "watchdog_agent_heartbeat.jsonl"
DEFAULT_PORTS = list(range(5555, 5563))
VERSION = "1.4.3"
_FAMFLOW = Path(r"C:\Users\jsmil\FamFlow")

_HTTP_PORT = int(os.environ.get("CPHARM_PORT", "8080").strip() or "8080")
CPHARM_EXE_NAMES = ("PharmFlow.exe", "CPharm.exe", "CPharmMuMuSetup.exe")


def _redirect_stdout_when_hidden() -> None:
    """When running under pythonw (no console), sys.stdout is None and the
    watch loop's print(flush=True) would crash on the first pass. Redirect to a
    log file so the watchdog survives when launched hidden by Task Scheduler.
    """
    if sys.stdout is not None:
        return
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stream = open(LOG_DIR / "watchdog_stdout.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = stream
        sys.stderr = stream
    except OSError:
        pass


_redirect_stdout_when_hidden()


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def command(argv: list[str], timeout: float = 20) -> tuple[int, str]:
    try:
        kwargs = {"capture_output": True, "text": True, "cwd": ROOT, "timeout": timeout}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(argv, **kwargs, check=False)
        return result.returncode, ((result.stdout or "") + (result.stderr or "")).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def _proc(name: str) -> int:
    if sys.platform != "win32":
        rc, out = command(["pgrep", "-f", name], timeout=10)
        return 0 if rc == 0 else 1
    # tasklist is locale-safe enough for a name match; avoid psutil dependency here.
    rc, out = command(["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV"], timeout=15)
    return 0 if rc == 0 and ("\"" + name.lower() + "\"" in out.lower() or name.lower() in out.lower()) else 1


# ---------------------------------------------------------------------------
# Process reaper — kill stale/duplicate/orphan processes as soon as discovered.
#
# Sweeps run every `--reap-interval` (default 60s) in watch mode. Classification
# is deliberately conservative: we only kill what is provably stale OR a known
# duplicate, and we NEVER kill anything the farm owns/adopts. Farm processes
# (run_farm_354, remediate loop, hunter, inject proxies, dashboard, watchdog,
# project/cloud agents) are allowlisted; Tor instances are only reaped when
# their config file is missing or two instances share the same config (the
# duplicate-data-dir wedge seen in the field), never by parent death alone
# because the farm adopts orphaned Tor via ControlPort.
# ---------------------------------------------------------------------------
REAP_DEFAULT_INTERVAL = 60.0
_REAP_LAST_RUN = 0.0
# Script basenames that are legitimately long-running farm-owned workers.
FARM_KEEP_SCRIPTS = frozenset({
    "dashboard.py",
    "run_farm_354.py",
    "farm_remediate_loop.py",
    "keep_farm_alive.py",
    "farm_operator_dash.py",
    "ssp_paying_hunter.py",
    "watch_bottom_ads.py",
    "run_mantis_inject_proxies.py",
    "_monitor_loop_90s.py",
    "farm_fail_review.py",
    "kill_azure_telemetry.py",
    "suppress_console_flash.py",
    "cpharm_watchdog.py",
    "project_agent.py",
    "cloud_agent.py",
    # Unison stack (supervised lanes) — spawned detached, so their powershell
    # parent exits immediately and the dead-parent rule would reap them every
    # sweep without this allowlist (this killed the supervisor AND the
    # adb-keeper/money lanes repeatedly in the field).
    "cpharm_unison_supervisor.py",
    "farm_watchdog.py",
    "farm_money_monitor.py",
    "adb_bond_keeper.py",
    "cpharm_stealth_guard.py",
    "agent_unison_freebuff_loop.py",
})


def _win_powershell(text: str, timeout: float = 40) -> tuple[int, str]:
    argv = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", text]
    if sys.platform == "win32":
        return command(argv, timeout=timeout)
    return 1, ""


def _pgrep_all(pattern: str) -> list[dict]:
    """POSIX fallback: pgrep -P '' style table flattened to the same shape."""
    rows: list[dict] = []
    rc, out = command(["pgrep", "-af", pattern], timeout=15)
    if rc != 0 or not out:
        return rows
    for line in out.splitlines():
        parts = line.split(maxsplit=1)
        if not parts:
            continue
        rows.append({"pid": int(parts[0]), "ppid": -1, "name": "", "cmdline": parts[1] if len(parts) > 1 else "", "started": ""})
    return rows


def process_table() -> list[dict]:
    """Live process snapshot: pid, ppid, name, started, cmdline for watchable names.

    Uses PowerShell CIM (no psutil dependency) on Windows; pgrep on POSIX.
    """
    if sys.platform == "win32":
        ps = (
            "$names = 'python.exe','pythonw.exe','tor.exe','adb.exe','PharmFlow.exe','CPharm.exe','CPharmWatchdog.exe'; "
            "$rows = Get-CimInstance Win32_Process | Where-Object { $names -contains $_.Name } | "
            "ForEach-Object { [PSCustomObject]@{ pid=$_.ProcessId; ppid=$_.ParentProcessId; "
            "name=$_.Name; started=$_.CreationDate.ToString('o'); cmdline=[string]$_.CommandLine } } | "
            "ConvertTo-Json -Compress -Depth 3; Write-Output $rows"
        )
        rc, out = _win_powershell(ps, timeout=40)
        if rc != 0 or not out:
            return []
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            # ConvertTo-Json emitted an array spanning multiple lines; try again with a wrapping trick.
            # Must redefine $names — the retry is a fresh powershell process.
            try:
                rc2, out2 = _win_powershell(
                    "$names = 'python.exe','pythonw.exe','tor.exe','adb.exe','PharmFlow.exe','CPharm.exe','CPharmWatchdog.exe'; "
                    "$rows = Get-CimInstance Win32_Process | Where-Object { $names -contains $_.Name } | "
                    "ForEach-Object { [PSCustomObject]@{ pid=$_.ProcessId; ppid=$_.ParentProcessId; "
                    "name=$_.Name; started=$_.CreationDate.ToString('o'); cmdline=[string]$_.CommandLine } }; "
                    "Write-Output ('[' + (( $rows | ConvertTo-Json -Compress -Depth 3 ) -join ',') + ']')",
                    timeout=40,
                )
                data = json.loads(out2) if rc2 == 0 and out2 else []
            except (json.JSONDecodeError, OSError):
                return []
        if isinstance(data, dict):
            data = [data]
        return [
            {
                "pid": int(r.get("pid") or 0),
                "ppid": int(r.get("ppid") or -1),
                "name": str(r.get("name") or ""),
                "started": str(r.get("started") or ""),
                "cmdline": str(r.get("cmdline") or ""),
            }
            for r in (data if isinstance(data, list) else [])
            if int(r.get("pid") or 0) > 0
        ]
    return _pgrep_all("python|python3|tor|adb|CPharm")


def _script_basename(cmdline: str) -> str:
    for tok in re.split(r"[\\/ ]+", cmdline.strip()):
        tok = tok.strip('"')
        if tok.lower().endswith(".py") and any(c.isalnum() for c in tok):
            return tok
    return ""


def _row_age_s(row: dict) -> float:
    """Seconds since the process started; -1 when unknown."""
    started = (row.get("started") or "").strip()
    if not started:
        return -1.0
    try:
        ts = datetime.fromisoformat(started.replace("Z", "+00:00"))
        if ts.tzinfo is not None:
            ts = ts.astimezone()
        return max(0.0, time.time() - ts.timestamp())
    except (ValueError, OSError, OverflowError):
        return -1.0


def _pid_alive(pid: int) -> bool:
    """True when *pid* exists on the host (not limited to process_table names)."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        rc, out = command(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"], timeout=10)
        if rc != 0 or not out:
            return False
        # tasklist still rc=0 with "INFO: No tasks..." when missing — require the pid token.
        return f",{pid}," in out.replace('"', ",") or f'"{pid}"' in out
    rc, _out = command(["kill", "-0", str(pid)], timeout=5)
    return rc == 0


class _Kill:
    def __init__(self, pid: int, reason: str, cmdline: str) -> None:
        self.pid = int(pid)
        self.reason = reason
        self.cmdline = (cmdline or "")[:220]


def reap_stale(*, apply: bool) -> dict:
    """One reaper sweep. Returns structured result; kills only when apply=True."""
    rows = process_table()
    result: dict = {
        "sweep": _utc(),
        "checked": len(rows),
        "found": 0,
        "killed": 0,
        "kills": [],
        "allowlisted": 0,
        "error": None,
    }
    if not rows:
        result["error"] = "no process table"
        return result

    kills: list[_Kill] = []
    allowlisted = 0
    by_name: dict[str, list[dict]] = {}
    for r in rows:
        by_name.setdefault((r.get("name") or "").lower(), []).append(r)

    # 1) Duplicate adb fork-servers — only one server may own port 5037.
    adb_servers = [r for r in by_name.get("adb.exe", []) if "fork-server" in (r.get("cmdline") or "")]
    if len(adb_servers) > 1:
        keep = max(adb_servers, key=lambda r: r["pid"])
        for r in adb_servers:
            if r["pid"] != keep["pid"]:
                kills.append(_Kill(r["pid"], "duplicate adb fork-server", r.get("cmdline") or ""))

    # 1b) Stale adb CLIENTS — the recurring MuMu wedge amplifier. subprocess.run
    #     leaks the child adb.exe on TimeoutExpired, so every timed-out
    #     `uiautomator dump` left a live client queued on the wedged guest until
    #     tap/swipe steps timed out too. Kill provably-dead clients:
    #       - orphaned clients (parent process gone) at any age
    #       - `shell` clients older than 180s (no legitimate shell command runs
    #         3 minutes; install/push are subcommands, not `shell`, so this
    #         cannot misclassify long installs).
    live_pids = {r["pid"] for r in rows}
    for r in by_name.get("adb.exe", []):
        cmd = r.get("cmdline") or ""
        if "fork-server" in cmd:
            continue  # handled above
        ppid = int(r.get("ppid") or -1)
        # live_pids only covers watched names — confirm parent death via OS when absent.
        orphan = ppid > 0 and ppid not in live_pids and not _pid_alive(ppid)
        age = _row_age_s(r)
        stuck_shell = " shell " in cmd and 0 < age < 9_999_999 and age > 180
        if orphan:
            kills.append(_Kill(r["pid"], "orphaned adb client (parent dead)", cmd))
        elif stuck_shell:
            kills.append(_Kill(r["pid"], f"stuck adb shell client {age:.0f}s", cmd))

    # 2) Duplicate dashboard.py instances — only one serves the farm HTTP API.
    dashes = [r for r in rows if "dashboard.py" in (r.get("cmdline") or "") and (r.get("name") or "").lower().startswith("python")]
    if len(dashes) > 1:
        keep = max(dashes, key=lambda r: r["pid"])
        for r in dashes:
            if r["pid"] != keep["pid"]:
                kills.append(_Kill(r["pid"], "duplicate dashboard.py", r.get("cmdline") or ""))

    # 3) Duplicate long-running farm worker scripts by (basename, working set is
    #    implied by identical cmdline) — keep newest, kill the rest.
    by_script: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        if not (r.get("name") or "").lower().startswith("python"):
            continue
        base = _script_basename(r.get("cmdline") or "")
        if not base:
            continue
        key = (base.lower(), (r.get("cmdline") or "")[:400])
        by_script.setdefault(key, []).append(r)
    for (base, _cmd), grp in by_script.items():
        if len(grp) < 2:
            continue
        keep = max(grp, key=lambda r: r["pid"])
        for r in grp:
            if r["pid"] != keep["pid"]:
                kills.append(_Kill(r["pid"], f"duplicate worker script {base}", r.get("cmdline") or ""))

    # 4) Dead-parent python helpers that are NOT farm-owned workers.
    live_pids = {r["pid"] for r in rows}
    for r in rows:
        if not (r.get("name") or "").lower().startswith("python"):
            continue
        base = _script_basename(r.get("cmdline") or "").lower()
        if not base:
            continue  # REPL / no script — leave it.
        if base in FARM_KEEP_SCRIPTS:
            allowlisted += 1
            continue
        ppid = int(r.get("ppid") or -1)
        # Parents are often cmd/explorer/services — not in the watched name list.
        parent_alive = ppid <= 0 or ppid in live_pids or _pid_alive(ppid)
        if not parent_alive:
            kills.append(_Kill(r["pid"], f"orphan helper (parent dead): {base}", r.get("cmdline") or ""))

    # 5) Tor: kill only when config file is missing OR two instances share one
    #    config path (duplicate data dir). Never by parent-death alone — the
    #    farm adopts orphaned Tor via ControlPort and killing it breaks income.
    torrc_re = re.compile(r"-f\s+(\S+)")
    tor_cfg_counts: dict[str, list[dict]] = {}
    for r in rows:
        if (r.get("name") or "").lower() != "tor.exe":
            continue
        m = torrc_re.search(r.get("cmdline") or "")
        cfg = m.group(1).strip('"') if m else ""
        if cfg:
            tor_cfg_counts.setdefault(cfg.lower(), []).append(r)
        else:
            ppid = int(r.get("ppid") or -1)
            if ppid > 0 and ppid not in live_pids and not _pid_alive(ppid):
                kills.append(_Kill(r["pid"], "tor without config (orphan)", r.get("cmdline") or ""))
    for cfg, grp in tor_cfg_counts.items():
        if len(grp) > 1:
            keep = max(grp, key=lambda r: r["pid"])
            for r in grp:
                if r["pid"] != keep["pid"]:
                    kills.append(_Kill(r["pid"], f"duplicate tor config {cfg}", r.get("cmdline") or ""))
        else:
            # Keys are lowercased for grouping; keep original cmdline path for exists check.
            raw_cfg = cfg
            m0 = torrc_re.search(grp[0].get("cmdline") or "")
            if m0:
                raw_cfg = m0.group(1).strip('"')
            if not Path(raw_cfg).is_file():
                kills.append(_Kill(grp[0]["pid"], f"tor config gone {raw_cfg}", grp[0].get("cmdline") or ""))

    result["allowlisted"] = allowlisted
    result["found"] = len(kills)
    if not kills:
        return result
    if not apply:
        result["kills"] = [{"pid": k.pid, "reason": k.reason, "cmdline": k.cmdline} for k in kills]
        return result

    killed_pids: list[int] = []
    kill_rows: list[dict] = []
    for k in kills:
        code, out = _kill_one(k.pid)
        ok = code == 0
        if ok:
            killed_pids.append(k.pid)
        kill_rows.append({"pid": k.pid, "ok": ok, "reason": k.reason, "detail": (out or "")[-160:], "cmdline": k.cmdline})
    result["killed"] = len(killed_pids)
    result["kills"] = kill_rows
    result["killed_pids"] = killed_pids
    return result


def _kill_one(pid: int) -> tuple[int, str]:
    if sys.platform == "win32":
        return command(["taskkill", "/F", "/PID", str(pid)], timeout=15)
    return command(["kill", "-9", str(pid)], timeout=10)


def _reap_line(rep: dict) -> str:
    if not rep:
        return ""
    err = f" err={rep.get('error')}" if rep.get("error") else ""
    return (f"reaper checked={rep.get('checked')} found={rep.get('found')} "
            f"killed={rep.get('killed')} allowlisted={rep.get('allowlisted')}{err}")



def check_main_process() -> dict:
    for name in CPHARM_EXE_NAMES:
        if _proc(name) == 0:
            return {"ok": True, "name": name}
    return {"ok": False, "name": "PharmFlow.exe not running"}


def _http_alive(timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", _HTTP_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def check_dashboard() -> dict:
    alive = _http_alive()
    return {"ok": alive, "port": _HTTP_PORT}


def repair_dashboard(*, apply: bool) -> dict:
    if not apply:
        return {"action": "respawn automation/dashboard.py", "status": "dry_run"}
    if not DASHBOARD_PY.is_file():
        return {"action": "respawn dashboard", "status": "failed", "detail": f"dashboard.py missing: {DASHBOARD_PY}"}
    try:
        subprocess.Popen(
            [sys.executable, str(DASHBOARD_PY)],
            cwd=str(ROOT),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform == "win32" else 0,
        )
        return {"action": "respawn dashboard", "status": "started"}
    except Exception as exc:  # noqa: BLE001
        return {"action": "respawn dashboard", "status": "failed", "detail": str(exc)}


def adb_path() -> str:
    return shutil.which("adb") or str(Path(os.environ.get("ANDROID_HOME", "")) / "platform-tools" / "adb.exe")


def adb_reconnect(host: str, port: int, apply: bool) -> dict:
    serial = f"{host}:{port}"
    row = {"serial": serial, "tcp_open": tcp_open(host, port), "adb": "not_checked"}
    if not row["tcp_open"]:
        row["adb"] = "unreachable"
        return row
    if not apply:
        row["adb"] = "dry_run"
        return row
    exe = adb_path()
    if not Path(exe).is_file() and not shutil.which(exe):
        row["adb"] = "adb_not_found"
        row["detail"] = "Install Android platform-tools or set ANDROID_HOME."
        return row
    code, output = command([exe, "connect", serial], timeout=12)
    low = output.lower()
    row["adb"] = "connected" if code == 0 and "failed" not in low and "cannot" not in low else "failed"
    row["detail"] = output[-300:]
    return row


def tcp_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _docker_guard() -> tuple[object, str]:
    """Return (engine_running_check, off_message).

    Docker Desktop's CLI shim launches the GUI when the engine is down, so we
    must never invoke the docker CLI unless the engine is already running.
    Fail closed: if the guard cannot load, docker stays off.
    """
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from docker_guard import DOCKER_OFF_MSG, engine_running

        return engine_running, DOCKER_OFF_MSG
    except Exception:  # noqa: BLE001
        def _off() -> bool:
            return False

        return _off, "Docker guard unavailable - Docker left off."


def docker_status(apply: bool) -> dict:
    if not COMPOSE.is_file():
        return {"ok": False, "error": f"Missing compose file: {COMPOSE}"}
    engine_running, off_msg = _docker_guard()
    if not engine_running():
        # Never touch the docker CLI while the engine is down - the Docker
        # Desktop shim would launch the GUI on its own. Docker stays off.
        return {"ok": True, "disabled": True, "apply": apply, "detail": off_msg}
    code, output = command(["docker", "compose", "-f", str(COMPOSE), "ps", "--format", "json"], timeout=45)
    return {"ok": code == 0, "apply": apply, "detail": output[-2000:]}


def repair_docker(apply: bool, service: str | None) -> dict:
    target = [service] if service else []
    if not apply:
        return {"action": "docker compose up -d", "services": target, "status": "dry_run"}
    engine_running, off_msg = _docker_guard()
    if not engine_running():
        return {"action": "docker compose up -d", "services": target,
                "status": "failed", "detail": off_msg}
    code, output = command(["docker", "compose", "-f", str(COMPOSE), "up", "-d", *target], timeout=180)
    return {"action": "docker compose up -d", "services": target, "status": "ok" if code == 0 else "failed", "detail": output[-1000:]}


def _log_heartbeat(state: dict) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with HEARTBEAT.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(state) + "\n")
    except OSError:
        pass


def _alert(msg: str, *, title: str = "CPharm Watchdog", tags: str = "rotating_light") -> bool:
    try:
        sys.path.insert(0, str(ROOT))
        from tools import notify_ntfy
        return bool(notify_ntfy.notify(msg, title=title, tags=tags))
    except Exception:  # noqa: BLE001
        return False


def verify_exit_ips(timeout: float = 30.0) -> dict:
    """Ask the dashboard to verify + rotate to unique exit IPs (single pass).

    All uniqueness logic lives in the running dashboard (which owns Tor/proxy state),
    so the watchdog just triggers and reports it. The endpoint reports uniqueness at
    the top level (``unique_exit_ips``) with the per-run detail under ``last``
    (``unique`` / ``rotations`` / ``ips``); this normalizes both shapes so callers
    always see ``unique``, ``rotations`` and ``ips`` at the top.
    """
    url = f"http://127.0.0.1:{_HTTP_PORT}/api/stealth/verify"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        if not isinstance(data, dict):
            return {"ok": False, "error": "bad payload"}
        last = data.get("last") if isinstance(data.get("last"), dict) else {}
        unique = data.get("unique_exit_ips")
        if unique is None:
            unique = last.get("unique")
        if unique is None:
            unique = data.get("unique")
        return {
            "ok": bool(data.get("ok")),
            "running": bool(data.get("running", False)),
            "unique": bool(unique),
            "rotations": int(last.get("rotations") or data.get("rotations") or 0),
            "ips": last.get("ips") or data.get("ips") or {},
            "phones": int(last.get("phones") or data.get("phones") or 0),
            "error": data.get("error"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _farm_investigate(*, apply: bool) -> dict:
    """Evidence-based farm pass — FamFlow automation module (no estimates)."""
    for base in (_FAMFLOW, ROOT):
        mod_path = base / "automation" / "farm_watchdog_investigate.py"
        if not mod_path.is_file():
            continue
        if str(base) not in sys.path:
            sys.path.insert(0, str(base))
        try:
            from automation.farm_watchdog_investigate import format_report, investigate

            report = investigate(apply=apply)
            report["text"] = format_report(report)
            return report
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "module": str(mod_path)}
    return {"ok": False, "error": "farm_watchdog_investigate.py not found"}


def check_once(args: argparse.Namespace) -> dict:
    main = check_main_process()
    dash = check_dashboard()
    docker = docker_status(args.apply)
    adb = [adb_reconnect(args.host, port, args.apply) for port in range(args.start_port, args.start_port + args.count)]
    # Stale-process cleanup and stealth exit-IP recovery share ONE maintenance
    # sweep: when the tick fires (every --reap-interval in watch mode, always in
    # --once), run the reaper AND the exit-IP uniqueness verification together.
    # This keeps /api/stealth/verify from being called every check interval and
    # makes stealth recovery + process reaping a single 60s cadence.
    global _REAP_LAST_RUN
    uniqueness = {"checked": False}
    reaper: dict = {}
    if getattr(args, "reap", True) or getattr(args, "stealth", False):
        now2 = time.time()
        interval = float(getattr(args, "reap_interval", REAP_DEFAULT_INTERVAL) or REAP_DEFAULT_INTERVAL)
        due = not getattr(args, "watch", False) or _REAP_LAST_RUN == 0.0 or (now2 - _REAP_LAST_RUN) >= interval
        if due:
            _REAP_LAST_RUN = now2
            if getattr(args, "reap", True):
                reaper = reap_stale(apply=bool(args.apply) and not getattr(args, "no_reap", False))
            if getattr(args, "stealth", False) and dash["ok"]:
                uniqueness = verify_exit_ips()
                uniqueness["checked"] = True
    exit_ips_unique = bool(uniqueness.get("unique", True)) if uniqueness.get("checked") else None
    reaped_pids = list(reaper.get("killed_pids") or [])

    recovered = []
    if not dash["ok"] and args.apply and args.repair_dashboard:
        r = repair_dashboard(apply=True)
        _wait_dashboard_up(args)
        dash = check_dashboard()
        recovered.append(r)
    if not docker["ok"] and args.apply and args.repair_docker:
        r = repair_docker(True, args.service)
        docker = docker_status(args.apply)
        recovered.append(r)

    healthy = main["ok"] and dash["ok"] and docker["ok"] and (exit_ips_unique is not False)
    farm_report: dict = {}
    if args.farm:
        farm_report = _farm_investigate(apply=args.apply)
        farm_problems = int(farm_report.get("problem_count") or 0)
        if farm_problems > 0:
            healthy = False
    cloud_up = sum(1 for a in adb if a["adb"] != "unreachable")
    summary = {
        "agent": "CPharm Watchdog Agent",
        "version": VERSION,
        "status": "healthy" if healthy else "degraded",
        "main_process": "up" if main["ok"] else "down",
        "dashboard": "up" if dash["ok"] else "down",
        "docker_stack": "off (disabled)" if docker.get("disabled") else ("up" if docker["ok"] else "down"),
        "adb_endpoints_online": cloud_up,
        "exit_ips_unique": exit_ips_unique,
        "exit_ip_rotations": uniqueness.get("rotations", 0) if uniqueness.get("checked") else 0,
        "farm_problems": int(farm_report.get("problem_count") or 0) if farm_report else None,
        "stale_found": int(reaper.get("found") or 0) if reaper else 0,
        "stale_killed": reaped_pids if reaped_pids else 0,
    }
    result = {
        "timestamp": int(time.time()),
        "utc": _utc(),
        "apply": args.apply,
        "checks": {
            "main_process": main,
            "dashboard": dash,
            "docker": docker,
            "adb": adb,
            "reaper": reaper,
            "uniqueness": uniqueness,
            "farm": farm_report,
        },
        "recovered": recovered,
        "summary": summary,
    }
    _log_heartbeat(result)
    return result


def _wait_dashboard_up(args: argparse.Namespace, attempts: int = 10) -> None:
    for _ in range(attempts):
        if _http_alive(timeout=1.0):
            return
        time.sleep(2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--version", action="version", version=f"CPharmWatchdog {VERSION}")
    parser.add_argument("--watch", action="store_true", help="Run as a looping agent until interrupted")
    parser.add_argument("--once", action="store_true", help="Run a single pass and exit")
    parser.add_argument("--interval", type=float, default=15, help="Watch interval in seconds")
    parser.add_argument("--apply", action="store_true", help="Perform recovery actions")
    parser.add_argument("--no-reap", action="store_true", help="Disable the process-reaper kill pass (detection is still logged)")
    parser.add_argument("--reap-interval", type=float, default=REAP_DEFAULT_INTERVAL,
                        help="Minimum seconds between process-reaper sweeps in watch mode")
    parser.add_argument("--reap-only", action="store_true",
                        help="Run a single maintenance sweep: reaper, plus stealth exit-IP check with --stealth (kill with --apply)")
    parser.add_argument("--repair-dashboard", action="store_true", help="Respawn dashboard when HTTP is down")
    parser.add_argument("--repair-docker", action="store_true", help="Ensure the compose stack is running")
    parser.add_argument("--service", help="Limit Docker repair to one compose service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--start-port", type=int, default=5555)
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--alert", action="store_true", help="Send ntfy alerts on state changes")
    parser.add_argument("--stealth", action="store_true",
                        help="Verify unique Tor exit IPs via the dashboard and rotate duplicates; runs on the same sweep as the reaper")
    parser.add_argument("--farm", action="store_true",
                        help="Run evidence-based farm investigate (flat $, seq FAILs, log facts) — use with --apply to fix")
    args = parser.parse_args()
    if args.count < 1 or args.count > 32:
        parser.error("--count must be between 1 and 32")
    if args.reap_interval < 1:
        parser.error("--reap-interval must be >= 1")

    if getattr(args, "reap_only", False):
        rep = reap_stale(apply=bool(args.apply) and not getattr(args, "no_reap", False))
        print(_reap_line(rep), flush=True)
        if rep.get("kills"):
            for k in rep["kills"]:
                print(f"  kill pid={k.get('pid')} ok={k.get('ok', True)} {k.get('reason')}", flush=True)
        if getattr(args, "stealth", False):
            uniq = verify_exit_ips()
            uniq["checked"] = True
            print(f"stealth unique={uniq.get('unique')} rotations={uniq.get('rotations', 0)} "
                  f"ips={uniq.get('ips')} checked={uniq.get('checked')}", flush=True)
        return 0 if not rep.get("killed_pids") else 0

    last_status: str | None = None
    first = True
    while True:
        now = time.time()

        state = check_once(args)
        s = state["summary"]
        line = (f"[{s['status'].upper()}] main={s['main_process']} dashboard={s['dashboard']} "
                f"docker={s['docker_stack']} adb_online={s['adb_endpoints_online']} "
                f"unique_exit_ips={s['exit_ips_unique'] if s['exit_ips_unique'] is not None else 'n/a'} "
                f"farm_problems={s.get('farm_problems')} stale_found={s.get('stale_found')} "
                f"stale_killed={s.get('stale_killed')}")
        print(line, flush=True)
        reaper = (state.get("checks") or {}).get("reaper") or {}
        reap_line = _reap_line(reaper)
        if reap_line:
            print(reap_line, flush=True)
        farm_chk = (state.get("checks") or {}).get("farm") or {}
        if farm_chk.get("text"):
            print(farm_chk["text"], flush=True)
        if args.alert and not first and last_status and last_status != s["status"]:
            _alert(f"CPharm {s['status']} — {s['main_process']} | dashboard {s['dashboard']} | "
                   f"docker {s['docker_stack']} | adb {s['adb_endpoints_online']} online",
                   tags="rotating_light" if s["status"] == "degraded" else "white_check_mark")
            try:
                LOG_DIR.mkdir(parents=True, exist_ok=True)
                (LOG_DIR / "watchdog_agent_last.json").write_text(
                    json.dumps(state, indent=2), encoding="utf-8")
            except OSError:
                pass
        last_status = s["status"]
        first = False
        if not args.watch:
            return 0
        time.sleep(max(1.0, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())