#!/usr/bin/env python3
"""Kill/hide all farm-related console flashes: MuMu ADB, Tor, azure telemetry.

MuMu opens ``cmd /K …nemux-shell-winui\\adb.exe …``.
Tor Expert Bundle is a console app — without CREATE_NO_WINDOW it pops blank
terminals (conhost→tor.exe). This watcher kills MuMu ADB shells and force-hides
any visible console owned by tor/adb/cmd related to the farm.

Also uses a WinEventHook so Cascadia/PseudoConsole flashes are hidden the
instant they appear (polling alone is too slow for 1-frame flashes).
"""
from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import automation.no_window  # noqa: E402,F401  (kill child console-window flashes)

INTERVAL = float(os.environ.get("CPHARM_SUPPRESS_FLASH_INTERVAL", "0.35") or "0.35")

user32 = ctypes.windll.user32 if sys.platform == "win32" else None
ole32 = ctypes.windll.ole32 if sys.platform == "win32" else None

SW_HIDE = 0
EVENT_OBJECT_SHOW = 0x8002
WINEVENT_OUTOFCONTEXT = 0x0000
OBJID_WINDOW = 0

_FLASH_CMD_MARKERS = (
    "nemux-shell-winui",
    "kill-azure-telemetry",
    "kill_azure_telemetry",
    "c:\\cpharm\\bundled\\adb",
    "c:\\cpharm\\bundled\\tor",
    "platform-tools\\adb",
    "platform-tools/adb",
    "run_farm_",
    "watch_proxy",
    "watch_bottom_ads",
    "force_ads_visible",
    "_force_ads_visible",
    "farm_operator",
    "fix_proxies",
    "run_mantis_inject",
    "suppress_console",
    "ensure_farm_24x7",
    "mouse_tickler",
    "watch_adb_devices",
)


def _hide_hwnd(hwnd: int) -> None:
    if not user32:
        return
    try:
        user32.ShowWindow(hwnd, SW_HIDE)
    except Exception:
        pass


def _should_hide_pid(pid: int) -> bool:
    """Hide tor/adb/farm helper consoles — all farm terminals stay suppressed."""
    try:
        import psutil

        proc = psutil.Process(pid)
        name = (proc.name() or "").lower()
        cmd = " ".join(str(x) for x in (proc.cmdline() or [])).lower()
        if name in {"tor.exe", "tor", "adb.exe", "adb"}:
            return True
        if name in {"cmd.exe", "cmd"} and (
            "nemux-shell-winui" in cmd
            or "watch_adb_devices" in cmd
            or any(m in cmd for m in _FLASH_CMD_MARKERS)
        ):
            return True
        if name in {"conhost.exe", "conhost"}:
            try:
                parent = proc.parent()
                pname = ((parent.name() if parent else "") or "").lower()
                if pname in {"tor.exe", "tor", "adb.exe", "adb", "cmd.exe", "cmd", "powershell.exe", "powershell"}:
                    if pname.startswith("powershell") or pname.startswith("pwsh"):
                        pcmd = " ".join(str(x) for x in (parent.cmdline() or [])).lower()
                        return any(
                            m in pcmd
                            for m in (
                                "kill-azure-telemetry",
                                "kill_azure_telemetry",
                                "cpharm",
                                "famflow",
                                "run_farm",
                            )
                        )
                    return True
            except (psutil.Error, ProcessLookupError):
                return False
        if name in {"powershell.exe", "powershell", "pwsh.exe", "pwsh"}:
            return any(
                m in cmd
                for m in (
                    "kill-azure-telemetry",
                    "kill_azure_telemetry",
                    "c:\\cpharm",
                    "famflow",
                    "run_farm",
                )
            )
        if name == "windowsterminal.exe":
            try:
                title = ""
                try:
                    title = (proc.name() and "") or ""
                except Exception:
                    title = ""
                # Title often shows the flashing adb path.
                try:
                    import ctypes

                    hwnd = int(getattr(proc, "_hwnd", 0) or 0)
                except Exception:
                    hwnd = 0
                for child in proc.children(recursive=True):
                    ccmd = " ".join(str(x) for x in (child.cmdline() or [])).lower()
                    cname = (child.name() or "").lower()
                    if cname in {"adb.exe", "adb"} or any(
                        m in ccmd
                        for m in (
                            "kill-azure-telemetry",
                            "kill_azure_telemetry",
                            "nemux-shell-winui",
                            "c:\\cpharm\\bundled\\adb",
                            "platform-tools\\adb",
                            "platform-tools/adb",
                            "watch_adb_devices",
                            "watch_bottom_ads",
                            "run_farm_",
                            "force_ads",
                        )
                    ):
                        return True
            except (psutil.Error, ProcessLookupError):
                return False
        if name in {"python.exe", "py.exe"} and any(n in cmd for n in _FLASH_CMD_MARKERS):
            return True
        if "cpharm" in cmd or "famflow" in cmd:
            if name in {"adb.exe", "adb", "cmd.exe", "cmd"}:
                return True
    except Exception:
        return False
    return False


def _enum_hide_for_pids(pids: set[int]) -> int:
    """Hide visible top-level windows owned by any pid in pids. Returns hide count."""
    if not user32 or not pids:
        return 0
    hidden = 0
    pid_buf = ctypes.c_ulong()

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def _cb(hwnd, _lparam):  # type: ignore[misc]
        nonlocal hidden
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_buf))
            if int(pid_buf.value) not in pids:
                return True
            _hide_hwnd(int(hwnd))
            hidden += 1
        except Exception:
            pass
        return True

    user32.EnumWindows(_cb, 0)
    return hidden


def _kill_flash_procs() -> tuple[int, int]:
    try:
        import psutil
    except ImportError:
        return 0, 0
    killed = 0
    hide_pids: set[int] = set()
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmd = proc.info.get("cmdline") or []
            joined = " ".join(str(x) for x in cmd).lower()
            pid = int(proc.info["pid"])

            # Windows Terminal hosting platform-tools adb = the visible flash.
            if name in {"windowsterminal.exe", "openconsole.exe"}:
                title = ""
                try:
                    title = (psutil.Process(pid).name() or "").lower()
                except Exception:
                    title = ""
                try:
                    # MainWindowTitle via GetWindowText is unreliable here; use children.
                    kids_adb = False
                    for child in proc.children(recursive=True):
                        cname = (child.name() or "").lower()
                        ccmd = " ".join(str(x) for x in (child.cmdline() or [])).lower()
                        if cname in {"adb.exe", "adb"} or "platform-tools" in ccmd:
                            kids_adb = True
                            break
                    if kids_adb or "platform-tools" in joined:
                        proc.kill()
                        killed += 1
                        continue
                except (psutil.Error, ProcessLookupError, PermissionError):
                    pass

            # ALL orphan cmd.exe flash windows (MuMu /K, watchers, etc.).
            if name in {"cmd.exe", "cmd"}:
                proc.kill()
                killed += 1
                continue

            # MuMu ADB debug consoles (any /c or /k).
            if name in {"cmd.exe", "cmd"} and "nemux-shell-winui" in joined:
                proc.kill()
                killed += 1
                continue

            # Operator ADB watch / farm helper cmd windows.
            if name in {"cmd.exe", "cmd"} and "watch_adb_devices" in joined:
                proc.kill()
                killed += 1
                continue

            # Orphaned interactive adb from MuMu / platform-tools (NOT bundled farm adb).
            if name in {"adb.exe", "adb"} and "fork-server" not in joined and "-L tcp:" not in joined:
                if "nemux-shell-winui" in joined or "platform-tools" in joined:
                    proc.kill()
                    killed += 1
                    continue

            if name in {"cmd.exe", "cmd", "powershell.exe", "powershell", "pwsh.exe", "pwsh"}:
                if any(m in joined for m in ("kill-azure-telemetry", "kill_azure_telemetry")):
                    proc.kill()
                    killed += 1
                    continue

            if _should_hide_pid(pid):
                hide_pids.add(pid)
        except (psutil.Error, ProcessLookupError, PermissionError, TypeError, ValueError):
            continue
    hid = _enum_hide_for_pids(hide_pids)
    return killed, hid


def _start_win_event_hook() -> object | None:
    """Hide flash windows the moment they appear (covers Cascadia 1-frame pops)."""
    if not user32 or not ole32:
        return None
    try:
        WinEventProcType = ctypes.WINFUNCTYPE(
            None,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_long,
            ctypes.c_long,
            ctypes.c_ulong,
            ctypes.c_ulong,
        )
        pid_buf = ctypes.c_ulong()

        def _on_show(h_hook, event, hwnd, id_object, id_child, thread_id, event_time):  # noqa: ARG001
            if int(id_object) != OBJID_WINDOW or not hwnd:
                return
            try:
                if not user32.IsWindowVisible(hwnd):
                    return
                cls = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls, 256)
                cl = cls.value.lower()
                if (
                    "console" not in cl
                    and "cascadia" not in cl
                    and "pseudo" not in cl
                ):
                    return
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_buf))
                if _should_hide_pid(int(pid_buf.value)):
                    _hide_hwnd(int(hwnd))
            except Exception:
                return

        cb = WinEventProcType(_on_show)
        # Keep callback alive for process lifetime.
        _start_win_event_hook._cb = cb  # type: ignore[attr-defined]
        ole32.CoInitialize(None)
        hook = user32.SetWinEventHook(
            EVENT_OBJECT_SHOW,
            EVENT_OBJECT_SHOW,
            0,
            cb,
            0,
            0,
            WINEVENT_OUTOFCONTEXT,
        )
        return hook or None
    except Exception:
        return None


def _pump_messages_briefly() -> None:
    if not user32:
        return
    msg = wintypes.MSG()
    # Drain a few messages so the WinEventHook fires between poll sleeps.
    for _ in range(32):
        if not user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):
            break
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def main() -> int:
    from automation.no_window import pin_windows_console_host

    pin_windows_console_host()
    print(f"suppress_console_flash every {INTERVAL:g}s (+ WinEventHook)", flush=True)
    hook = _start_win_event_hook()
    print(f"winevent_hook={'on' if hook else 'off'}", flush=True)
    while True:
        try:
            _pump_messages_briefly()
            killed, hid = _kill_flash_procs()
            if killed or hid:
                print(f"killed={killed} hid={hid}", flush=True)
        except Exception as exc:
            print(f"err {exc}", flush=True)
        # Short slices so hook messages keep pumping.
        slice_s = min(0.05, max(0.02, INTERVAL / 4))
        end = time.time() + max(0.2, INTERVAL)
        while time.time() < end:
            _pump_messages_briefly()
            time.sleep(slice_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
