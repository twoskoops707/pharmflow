"""Launch a single MuMu Player ARM VM by index (no mass restart)."""
from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

logger = logging.getLogger(__name__)

_NAME_IDX = re.compile(r"^vm(\d+)", re.I)
_SHELL = Path(r"C:\Program Files\Netease\MuMuPlayerARM\shell\nemux-shell-winui.exe")
_HCS_TOOL = Path(r"C:\Program Files\Netease\MuMuPlayerARM\shell\nemu-hcs-tool.exe")
_LAUNCH_CACHE = Path(r"C:\PharmFlow\logs\mumu_launch_cache.json")
# Token charset includes URL-safe base64 (-_) — truncating at '-' broke cache hits.
_VM_IDX = re.compile(
    r"--VmIndex (\d+).*--ThumbnailName (\S+).*--T ([A-Za-z0-9+/=_-]+)"
)


def phone_vm_index(name: str, fallback: int = 0) -> int:
    m = _NAME_IDX.match((name or "").split(".")[0].strip())
    if not m:
        return int(fallback)
    return int(m.group(1))


def _shell_exe() -> Path | None:
    env = Path(os.environ.get("PHARMFLOW_MUMU_ROOT") or "")
    candidates = [
        _SHELL,
        env / "shell" / "nemux-shell-winui.exe" if env else None,
    ]
    for path in candidates:
        if path is not None and path.is_file():
            return path
    return None


def instance_shell_running(idx: int) -> bool:
    try:
        import psutil
    except ImportError:
        return False
    # Substring "--VmIndex 1" falsely matches "--VmIndex 10" / 11 / 12 …
    needle = re.compile(rf"(?:^|\s)--VmIndex\s+{int(idx)}(?:\s|$)")
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            name = str(proc.info.get("name") or "").lower()
            # Manager.exe contains "nemux-shell-winui" but is not a VM shell.
            if "nemux-shell-winui" not in name or "manager" in name:
                continue
            cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or []))
            if needle.search(cmd):
                return True
        except (psutil.Error, TypeError, ValueError):
            continue
    return False


def harvest_launch_cache() -> dict[str, dict[str, str | int]]:
    """Persist full nemux launch args (needs MuMu auth ``--T`` token) from running shells."""
    cache: dict[str, dict[str, str | int]] = {}
    if _LAUNCH_CACHE.is_file():
        try:
            raw = json.loads(_LAUNCH_CACHE.read_text(encoding="utf-8-sig"))
            if isinstance(raw, dict):
                cache = {str(k): v for k, v in raw.items() if isinstance(v, dict)}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            cache = {}
    try:
        import psutil
    except ImportError:
        return cache
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            name = str(proc.info.get("name") or "").lower()
            if "nemux-shell-winui" not in name or "manager" in name:
                continue
            cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or []))
            m = _VM_IDX.search(cmd)
            if not m:
                continue
            key = str(int(m.group(1)))
            cache[key] = {
                "idx": int(key),
                "thumb": m.group(2),
                "t": m.group(3),
            }
        except (psutil.Error, TypeError, ValueError):
            continue
    try:
        _LAUNCH_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _LAUNCH_CACHE.write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("mumu launch cache write failed: %s", exc)
    return cache


_HCS_CACHE: dict[str, tuple[float, bool | None]] = {}
_HCS_CACHE_TTL_S = 300.0
_HCS_TIMEOUT_S = 6.0


def hcs_compute_present(vm_name: str) -> bool | None:
    """Return True when ``vmN.gmadoa`` exists in MuMu HCS; None if tool unavailable.

    The hcs tool hangs (20s+ per call) on MuMuPlayerARM when the HCS service is
    idle, so the result is cached per process and the call is time-boxed — a
    boot of 12 VMs must not spend 4 minutes in this gate.
    """
    now = time.monotonic()
    hit = _HCS_CACHE.get(vm_name)
    if hit is not None and now - hit[0] < _HCS_CACHE_TTL_S:
        return hit[1]
    tool = _HCS_TOOL if _HCS_TOOL.is_file() else None
    if tool is None:
        _HCS_CACHE[vm_name] = (now, None)
        return None
    try:
        r = subprocess.run(
            [str(tool), "--list", "computesystems"],
            capture_output=True,
            text=True,
            timeout=_HCS_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        _HCS_CACHE[vm_name] = (now, None)
        return None
    blob = (r.stdout or "") + (r.stderr or "")
    result = vm_name in blob
    _HCS_CACHE[vm_name] = (now, result)
    return result


# Console classes stay suppressed. The player GUI must not.
_CONSOLE_CLASS_NAMES = {
    "consolewindowclass",
    "pseudoconsolewindow",
    "cascadia_hosting_window_class",
}
# Children of the shell that are consoles / farm tools — never treat their
# windows as the player, and never ShowWindow them (that undoes flash suppression).
_NON_PLAYER_CHILD_NAMES = {
    "adb.exe",
    "adb",
    "cmd.exe",
    "cmd",
    "conhost.exe",
    "conhost",
    "openconsole.exe",
    "windowsterminal.exe",
    "powershell.exe",
    "powershell",
    "pwsh.exe",
    "pwsh",
    "tor.exe",
    "tor",
}
_SW_SHOWNORMAL = 1
_SW_SHOW = 5
_SW_RESTORE = 9
_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SEE_MASK_FLAG_NO_UI = 0x00000400
_STARTF_USESHOWWINDOW = 0x00000001
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_SHOWWINDOW = 0x0040
_DWMWA_CLOAKED = 14
_MIN_PLAYER_AREA = 80 * 80


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


_WIN32: tuple[ctypes.WinDLL, ctypes.WinDLL, ctypes.WinDLL] | None = None
_WIN32_READY = False


def _win32() -> tuple[ctypes.WinDLL, ctypes.WinDLL, ctypes.WinDLL] | None:
    """Private user32/kernel32/dwmapi loads.

    Do not set argtypes on ``ctypes.windll.user32`` — other modules call that
    shared object without a matching signature. Prototypes are required on
    ARM64: an unset HWND is truncated and EnumWindows never sees the player.
    """
    global _WIN32, _WIN32_READY
    if _WIN32_READY:
        return _WIN32
    _WIN32_READY = True
    if sys.platform != "win32":
        return None
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumThreadWindows.argtypes = [wintypes.DWORD, enum_proc, wintypes.LPARAM]
    user32.EnumThreadWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
    user32.AllowSetForegroundWindow.restype = wintypes.BOOL
    dwmapi.DwmSetWindowAttribute.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    _WIN32 = (user32, kernel32, dwmapi)
    return _WIN32


def _shell_procs(idx: int) -> list[object]:
    """Running nemux player processes for ``idx``. Never the Manager GUI."""
    try:
        import psutil
    except ImportError:
        return []
    needle = re.compile(rf"(?:^|\s)--VmIndex\s+{int(idx)}(?:\s|$)")
    found: list[object] = []
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            name = str(proc.info.get("name") or "").lower()
            if "nemux-shell-winui" not in name or "manager" in name:
                continue
            cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or []))
            if needle.search(cmd):
                found.append(proc)
        except (psutil.Error, TypeError, ValueError):
            continue
    return found


def _player_pids(idx: int) -> list[int]:
    """Shell PIDs plus non-console children that may own the player HWND."""
    pids: list[int] = []
    seen: set[int] = set()
    for proc in _shell_procs(idx):
        try:
            pid = int(proc.pid)
        except (AttributeError, TypeError, ValueError):
            continue
        if pid not in seen:
            seen.add(pid)
            pids.append(pid)
        try:
            children = proc.children(recursive=True)  # type: ignore[attr-defined]
        except Exception:
            continue
        for child in children:
            try:
                cname = (child.name() or "").lower()
                if cname in _NON_PLAYER_CHILD_NAMES:
                    continue
                cpid = int(child.pid)
            except Exception:
                continue
            if cpid not in seen:
                seen.add(cpid)
                pids.append(cpid)
    return pids


def _class_name(user32: ctypes.WinDLL, hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    try:
        user32.GetClassNameW(hwnd, buf, 256)
    except Exception:
        return ""
    return str(buf.value or "")


def _is_console_hwnd(user32: ctypes.WinDLL, hwnd: int) -> bool:
    return _class_name(user32, hwnd).lower() in _CONSOLE_CLASS_NAMES


def _window_area(user32: ctypes.WinDLL, hwnd: int) -> int:
    rect = _RECT()
    try:
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return 0
    except Exception:
        return 0
    return max(0, int(rect.right) - int(rect.left)) * max(0, int(rect.bottom) - int(rect.top))


def _hwnds_for_pids(user32: ctypes.WinDLL, pids: set[int]) -> list[int]:
    if not pids:
        return []
    found: list[int] = []
    pid_buf = wintypes.DWORD()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _top(hwnd, _lparam):  # type: ignore[misc]
        try:
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_buf))
            if int(pid_buf.value) in pids:
                found.append(int(hwnd))
        except Exception:
            pass
        return True

    user32.EnumWindows(_top, 0)
    # EnumWindows misses some per-thread top-level windows. Enumerate threads
    # of the player PIDs without touching console children (they are not in pids).
    try:
        import psutil
    except ImportError:
        return found
    seen = set(found)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _thread(hwnd, _lparam):  # type: ignore[misc]
        try:
            handle = int(hwnd)
        except (TypeError, ValueError):
            return True
        if handle not in seen:
            seen.add(handle)
            found.append(handle)
        return True

    for pid in pids:
        try:
            proc = psutil.Process(pid)
            threads = proc.threads()
        except Exception:
            continue
        for thread in threads:
            try:
                user32.EnumThreadWindows(int(thread.id), _thread, 0)
            except Exception:
                continue
    return found


def _is_visible_player(user32: ctypes.WinDLL, hwnd: int) -> bool:
    if _is_console_hwnd(user32, hwnd):
        return False
    try:
        if user32.IsIconic(hwnd):
            return True
        if not user32.IsWindowVisible(hwnd):
            return False
    except Exception:
        return False
    return _window_area(user32, hwnd) >= _MIN_PLAYER_AREA


def player_window_visible(idx: int) -> bool:
    """True only when this VM's player GUI is actually visible.

    A running ``nemux-shell-winui.exe`` with MainWindowHandle 0 is not a
    visible player. Console windows owned by adb/conhost do not count.
    """
    wins = _win32()
    if wins is None:
        return False
    user32, _kernel32, _dwmapi = wins
    pids = set(_player_pids(idx))
    if not pids:
        return False
    return any(_is_visible_player(user32, hwnd) for hwnd in _hwnds_for_pids(user32, pids))


def _reveal_player_hwnd(user32: ctypes.WinDLL, dwmapi: ctypes.WinDLL, hwnd: int) -> None:
    cloaked = wintypes.BOOL(False)
    try:
        dwmapi.DwmSetWindowAttribute(
            hwnd,
            _DWMWA_CLOAKED,
            ctypes.byref(cloaked),
            ctypes.sizeof(cloaked),
        )
    except Exception:
        pass
    try:
        user32.ShowWindow(hwnd, _SW_RESTORE)
        user32.ShowWindow(hwnd, _SW_SHOW)
        user32.SetWindowPos(
            hwnd,
            0,
            0,
            0,
            0,
            0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_SHOWWINDOW,
        )
    except Exception:
        return


def show_instance_player(idx: int) -> tuple[bool, str]:
    """Show the player window of an already-running shell.

    Does not spawn a second shell and does not kill the VM. Console windows
    are left alone so farm flash suppression stays intact.
    """
    idx = int(idx)
    if not instance_shell_running(idx):
        return False, f"shell_not_running idx={idx}"
    wins = _win32()
    if wins is None:
        return False, f"player_show_unsupported idx={idx}"
    user32, _kernel32, dwmapi = wins
    pids = _player_pids(idx)
    if not pids:
        return False, f"shell_not_running idx={idx}"
    hwnds = [
        hwnd
        for hwnd in _hwnds_for_pids(user32, set(pids))
        if not _is_console_hwnd(user32, hwnd)
    ]
    if not hwnds:
        return False, f"no_player_hwnd idx={idx} (VM left running)"
    try:
        user32.AllowSetForegroundWindow(int(pids[0]))
    except Exception:
        pass
    for hwnd in hwnds:
        _reveal_player_hwnd(user32, dwmapi, hwnd)
    if player_window_visible(idx):
        return True, f"player_shown idx={idx}"
    return False, f"player_still_hidden idx={idx} (VM left running)"


def _close_handle(kernel32: ctypes.WinDLL, handle: int) -> None:
    if not handle:
        return
    try:
        kernel32.CloseHandle(handle)
    except Exception:
        return


def _shell_execute_visible(exe: Path, params: str) -> str | None:
    """Open the player the way Explorer does. Returns an error string or None."""
    wins = _win32()
    if wins is None:
        return "not_windows"
    _user32, kernel32, _dwmapi = wins
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    info = _SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(_SHELLEXECUTEINFOW)
    info.fMask = _SEE_MASK_NOCLOSEPROCESS | _SEE_MASK_FLAG_NO_UI
    info.lpVerb = "open"
    info.lpFile = str(exe)
    info.lpParameters = params
    info.lpDirectory = str(exe.parent)
    info.nShow = _SW_SHOWNORMAL
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        err = ctypes.get_last_error()
        return f"ShellExecuteExW:{err}"
    _close_handle(kernel32, int(info.hProcess or 0))
    inst = int(info.hInstApp or 0)
    if 0 < inst <= 32:
        return f"ShellExecuteExW:hInstApp={inst}"
    return None


def _create_process_visible(exe: Path, argv: list[str]) -> None:
    """CreateProcessW with SW_SHOWNORMAL and no CREATE_NO_WINDOW.

    ``automation.no_window`` patches ``subprocess.Popen`` to force
    CREATE_NO_WINDOW + SW_HIDE on every child. That is correct for adb/tor
    consoles and wrong for this GUI: on this ARM64 box the player stays up
    with MainWindowHandle 0. Bypass Popen entirely.
    """
    wins = _win32()
    if wins is None:
        raise OSError("MuMu player launch is Windows-only")
    _user32, kernel32, _dwmapi = wins
    si = _STARTUPINFOW()
    si.cb = ctypes.sizeof(_STARTUPINFOW)
    si.dwFlags = _STARTF_USESHOWWINDOW
    si.wShowWindow = _SW_SHOWNORMAL
    pi = _PROCESS_INFORMATION()
    cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
    kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(_STARTUPINFOW),
        ctypes.POINTER(_PROCESS_INFORMATION),
    ]
    kernel32.CreateProcessW.restype = wintypes.BOOL
    ok = kernel32.CreateProcessW(
        str(exe),
        cmdline,
        None,
        None,
        False,
        _CREATE_UNICODE_ENVIRONMENT,
        None,
        str(exe.parent),
        ctypes.byref(si),
        ctypes.byref(pi),
    )
    if not ok:
        err = ctypes.get_last_error()
        raise OSError(err, f"CreateProcessW failed ({err})")
    _close_handle(kernel32, int(pi.hProcess or 0))
    _close_handle(kernel32, int(pi.hThread or 0))


def _spawn_visible_player(exe: Path, argv: list[str]) -> None:
    """Start the GUI player visible. Never CREATE_NO_WINDOW, never Popen-hidden."""
    params = subprocess.list2cmdline(argv[1:]) if len(argv) > 1 else ""
    err = _shell_execute_visible(exe, params)
    if err is None:
        return
    logger.warning("visible ShellExecute failed (%s) — CreateProcessW fallback", err)
    _create_process_visible(exe, argv)


def _wait_visible_player(idx: int, budget: float) -> str:
    """Wait until the player window is visible. Does not kill a running shell.

    Returns ``visible``, ``windowless`` (shell up, no player window), or ``absent``.
    """
    end = time.monotonic() + max(8.0, float(budget))
    last_show = 0.0
    while time.monotonic() < end:
        if instance_shell_running(idx):
            if player_window_visible(idx):
                harvest_launch_cache()
                return "visible"
            now = time.monotonic()
            if now - last_show >= 2.0:
                show_instance_player(idx)
                last_show = now
                if player_window_visible(idx):
                    harvest_launch_cache()
                    return "visible"
        time.sleep(0.5)
    # A shell that appeared and then exited (HNS tears the VM down) is absent,
    # not a windowless player we left running.
    if instance_shell_running(idx):
        return "windowless"
    return "absent"


def launch_instance_index(idx: int, timeout: float = 120.0) -> tuple[bool, str]:
    """Start MuMu ARM instance ``idx`` with a visible player window.

    A running shell is not success. ``automation.no_window`` hides every
    ``Popen`` child; this launcher bypasses that and never uses
    CREATE_NO_WINDOW on ``nemux-shell-winui.exe``. An already-running shell
    is shown in place — a second shell is not spawned, and the VM is not killed.
    Success requires a visible player window, not merely a live process.
    """
    idx = int(idx)
    if instance_shell_running(idx):
        if player_window_visible(idx):
            return True, f"already_running idx={idx}"
        ok, note = show_instance_player(idx)
        if ok:
            return True, note
        time.sleep(0.8)
        if not instance_shell_running(idx):
            return False, f"launch_timeout idx={idx} (shell exited; VM not killed by launcher)"
        ok, note = show_instance_player(idx)
        if ok:
            return True, note
        if not instance_shell_running(idx):
            return False, f"launch_timeout idx={idx} (shell exited; VM not killed by launcher)"
        return False, f"windowless_shell idx={idx} (player window missing; VM left running)"
    exe = _shell_exe()
    if exe is None:
        return False, "nemux-shell-winui.exe missing"
    cache = harvest_launch_cache()
    entry = cache.get(str(idx)) or {}
    thumb = str(entry.get("thumb") or "").strip()
    token = str(entry.get("t") or "").strip()
    # Pass discrete argv tokens — a single joined string is one argument on
    # Windows and MuMu silently fails to start (shell never sticks, AdbHost stays empty).
    cmd: list[str] = [str(exe), "--VmIndex", str(idx)]
    if thumb:
        cmd += ["--ThumbnailName", thumb]
    if token:
        cmd += ["--T", token]

    def _launch(argv: list[str], budget: float) -> str:
        _spawn_visible_player(exe, argv)
        return _wait_visible_player(idx, budget)

    try:
        state = _launch(cmd, timeout)
    except OSError as exc:
        return False, f"launch_fail:{exc}"
    if state == "visible":
        return True, f"launched idx={idx}"
    if state == "windowless":
        return False, f"windowless_shell idx={idx} (player window missing; VM left running)"
    # Expired/stale --T leaves shell dead (AdbHost empty). Bare --VmIndex is
    # proven to cold-boot; retry once without cached auth tokens. Do not retry
    # if a shell is already up — a second process can replace the VM.
    if (token or thumb) and not instance_shell_running(idx):
        logger.warning(
            "mumu launch idx=%s timed out with cached --T — retrying bare --VmIndex",
            idx,
        )
        bare = [str(exe), "--VmIndex", str(idx)]
        try:
            state = _launch(bare, min(60.0, max(8.0, float(timeout))))
        except OSError as exc:
            return False, f"launch_fail:{exc}"
        if state == "visible":
            return True, f"launched_bare idx={idx}"
        if state == "windowless":
            return False, f"windowless_shell idx={idx} (player window missing; VM left running)"
    return False, f"launch_timeout idx={idx} (need MuMu UI restart if hcs_missing)"
