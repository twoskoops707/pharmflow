"""List / kill farm helper processes without spawning PowerShell (no console flash)."""

from __future__ import annotations

from typing import Any

_NEEDLES = (
    "run_farm_354",
    "run_farm_cycles",
    "run_mantis_inject",
    "watch_ads_visible",
    "farm_hourly_ntfy",
    "watch_seq_isolation",
    "watch_proxy_inject",
    "ntfy_farm_responder",
    "ntfy_agent_wake",
    "farm_operator_dash",
    "suppress_console_flash",
)


def _cmdline(proc: Any) -> str:
    try:
        parts = proc.cmdline()
    except Exception:
        return ""
    if not parts:
        return ""
    return " ".join(str(x) for x in parts)


def iter_matching_processes(
    needles: tuple[str, ...] | None = None,
    *,
    names: tuple[str, ...] = ("python.exe", "pythonw.exe", "py.exe"),
) -> list[dict[str, Any]]:
    """Return [{pid, cmd}] for python/pythonw processes whose cmdline matches any needle."""
    try:
        import psutil
    except ImportError:
        return []

    want = needles if needles is not None else _NEEDLES
    name_set = {n.lower() for n in names}
    rows: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            info = proc.info
            name = str(info.get("name") or "").lower()
            if name not in name_set:
                continue
            cmd = _cmdline(proc)
            if not cmd:
                continue
            if not any(n in cmd for n in want):
                continue
            short = cmd if len(cmd) <= 140 else cmd[:140]
            rows.append({"pid": int(info["pid"]), "cmd": short})
        except (psutil.Error, TypeError, ValueError, KeyError):
            continue
    return rows


def pids_matching(needles: tuple[str, ...] | str) -> list[int]:
    if isinstance(needles, str):
        needles_t = (needles,)
    else:
        needles_t = needles
    return [int(r["pid"]) for r in iter_matching_processes(needles_t)]


# Current Control Panel plus the previous filename so a leftover process still counts.
GUI_EXE_NAMES = frozenset({"pharmflow.exe", "pharmflow.exe"})


def pharmflow_exe_pids() -> list[int]:
    """PIDs for PharmFlow.exe (and a leftover PharmFlow.exe)."""
    try:
        import psutil
    except ImportError:
        return []
    out: list[int] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if str(proc.info.get("name") or "").lower() in GUI_EXE_NAMES:
                out.append(int(proc.info["pid"]))
        except (psutil.Error, TypeError, ValueError, KeyError):
            continue
    return out


def kill_matching(needles: tuple[str, ...] | str) -> int:
    """Force-kill matching processes. Returns count killed."""
    import subprocess

    killed = 0
    pids = pids_matching(needles)
    try:
        import psutil
    except ImportError:
        psutil = None  # type: ignore
    for pid in pids:
        ok = False
        if psutil is not None:
            try:
                psutil.Process(pid).kill()
                ok = True
            except Exception:
                ok = False
        if not ok:
            try:
                r = subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                ok = r.returncode == 0
            except OSError:
                ok = False
        if ok:
            killed += 1
    return killed


# Scripts that must never run more than one instance (dash port / double-drive).
SINGLETON_HELPERS: tuple[str, ...] = (
    "farm_operator_dash.py",
    "ensure_farm_24x7.py",
    "keep_farm_alive.py",
    "farm_remediate_loop.py",
    "run_mantis_inject_proxies.py",
    "watch_proxy_inject.py",
    "watch_bottom_ads.py",
    "emu_keepalive.py",
    "farm_fail_review.py",
    "farm_midnight_watch.py",
    "mouse_tickler.py",
    "suppress_console_flash.py",
    "ssp_paying_hunter.py",
    "run_farm_cycles.py",
)

# Keep the process that owns the listen port, not the newest spawn.
# Newest-wins used to kill the working dash after a false DASH_DOWN respawn.
_KEEP_LISTENER_PORT = {
    "farm_operator_dash.py": 8091,
}


def _pid_create_time(pid: int) -> float:
    try:
        import psutil

        return float(psutil.Process(pid).create_time())
    except Exception:
        return 0.0


def cull_duplicates_keep_newest(
    needles: tuple[str, ...] | str | None = None,
) -> list[str]:
    """Kill older duplicate helpers; keep the newest PID per needle.

    Returns human-readable fix strings for heartbeats / remediator logs.
    """
    try:
        import psutil
    except ImportError:
        return []

    want = (
        (needles,)
        if isinstance(needles, str)
        else tuple(needles or SINGLETON_HELPERS)
    )
    fixes: list[str] = []
    for needle in want:
        rows: list[tuple[int, float]] = []
        for proc in psutil.process_iter(["pid", "name", "create_time"]):
            try:
                name = str(proc.info.get("name") or "").lower()
                if name not in ("python.exe", "pythonw.exe", "py.exe"):
                    continue
                parts = [str(x).lower() for x in (proc.cmdline() or [])]
                if "-c" in parts:
                    continue
                joined = " ".join(parts)
                if needle.lower() not in joined:
                    continue
                rows.append(
                    (
                        int(proc.info["pid"]),
                        float(proc.info.get("create_time") or 0.0),
                    )
                )
            except (psutil.Error, TypeError, ValueError, KeyError, OSError):
                continue
        if len(rows) <= 1:
            continue
        rows.sort(key=lambda r: r[1], reverse=True)  # newest first
        keep_pid = rows[0][0]
        listen_port = _KEEP_LISTENER_PORT.get(needle)
        if listen_port:
            listeners = set(port_pids_listening(int(listen_port)))
            owned = [pid for pid, _ctime in rows if pid in listeners]
            if owned:
                keep_pid = owned[0]
            else:
                # Can't see the socket (Windows perms) — keep oldest, likely the listener.
                keep_pid = min(rows, key=lambda r: r[1])[0]
        for pid, _ctime in rows:
            if pid == keep_pid:
                continue
            try:
                psutil.Process(pid).kill()
                fixes.append(f"dup_cull:{needle}:{pid}(keep={keep_pid})")
            except (psutil.Error, OSError):
                pass
    return fixes


def port_pids_listening(port: int) -> list[int]:
    """PIDs with a LISTEN socket on 127.0.0.1:port / 0.0.0.0:port (best-effort)."""
    try:
        import psutil
    except ImportError:
        return []
    found: list[int] = []
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.status != "LISTEN":
                continue
            if not conn.laddr or int(conn.laddr.port) != int(port):
                continue
            if conn.pid:
                found.append(int(conn.pid))
    except (psutil.Error, PermissionError, OSError):
        return []
    return sorted(set(found))
