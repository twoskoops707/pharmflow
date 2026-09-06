"""Launch a single MuMu Player ARM VM by index (no mass restart)."""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_NAME_IDX = re.compile(r"^vm(\d+)", re.I)
_SHELL = Path(r"C:\Program Files\Netease\MuMuPlayerARM\shell\nemux-shell-winui.exe")
_HCS_TOOL = Path(r"C:\Program Files\Netease\MuMuPlayerARM\shell\nemu-hcs-tool.exe")
_LAUNCH_CACHE = Path(r"C:\CPharm\logs\mumu_launch_cache.json")
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
    env = Path(os.environ.get("CPHARM_MUMU_ROOT") or "")
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
            if "nemux-shell-winui" not in name:
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
            if "nemux-shell-winui" not in name:
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


def launch_instance_index(idx: int, timeout: float = 120.0) -> tuple[bool, str]:
    """Start MuMu ARM instance ``idx`` if its shell is not already running."""
    idx = int(idx)
    if instance_shell_running(idx):
        return True, f"already_running idx={idx}"
    vm_name = f"vm{idx}.gmadoa"
    # No HCS gate here: a STOPPED VM is legitimately absent from HCS — the shell
    # process itself registers and boots it (MuHcsDaemon runs inside the shell,
    # see vm0 hcs.log). Gating on HCS presence refused every cold start with
    # "hcs_missing", which is why Start-all-phones could not boot stopped phones.
    # Bare launches are proven working (vm10 farmed with a bare --VmIndex shell).
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
    flags = 0
    if sys.platform == "win32":
        flags = int(getattr(subprocess, "DETACHED_PROCESS", 0) or 0)

    def _spawn(argv: list[str]) -> None:
        subprocess.Popen(
            argv,
            cwd=str(exe.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )

    def _wait_shell(budget: float) -> bool:
        end = time.monotonic() + max(8.0, float(budget))
        while time.monotonic() < end:
            if instance_shell_running(idx):
                harvest_launch_cache()
                return True
            time.sleep(1.0)
        return False

    try:
        _spawn(cmd)
    except OSError as exc:
        return False, f"launch_fail:{exc}"
    if _wait_shell(timeout):
        return True, f"launched idx={idx}"
    # Expired/stale --T leaves shell dead (AdbHost empty). Bare --VmIndex is
    # proven to cold-boot; retry once without cached auth tokens.
    if token or thumb:
        logger.warning(
            "mumu launch idx=%s timed out with cached --T — retrying bare --VmIndex",
            idx,
        )
        bare = [str(exe), "--VmIndex", str(idx)]
        try:
            _spawn(bare)
        except OSError as exc:
            return False, f"launch_fail:{exc}"
        if _wait_shell(min(60.0, max(8.0, float(timeout)))):
            return True, f"launched_bare idx={idx}"
    return False, f"launch_timeout idx={idx} (need MuMu UI restart if hcs_missing)"
