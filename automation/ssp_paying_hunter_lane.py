"""PharmFlow-owned SSP paying hunter — required while the farm is running.

FamFlow / C:\\CPharm hunters must NOT satisfy the PharmFlow ssp-hunter lane.
Basename-only process scans left tip EXE Start with HUNTER_EXE_CHILD=0 while a
foreign house-only hunter kept writing CPharm and blocked unison respawn.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HUNTER_SCRIPT = "ssp_paying_hunter.py"
_CREATE_NO_WINDOW = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)

_FOREIGN_ROOT_MARKERS = (
    r"\famflow",
    "/famflow",
    r"\cpharm",
    "/cpharm",
)
_PHARMFLOW_ROOT_MARKERS = (
    r"\pharmflow",
    "/pharmflow",
)


def _norm(text: str) -> str:
    return str(text or "").strip().lower().replace("/", "\\")


def cmdline_has_hunter(cmd: str) -> bool:
    low = _norm(cmd)
    return HUNTER_SCRIPT in low and " -c " not in f" {low} " and not low.endswith(" -c")


def cmdline_looks_foreign(cmd: str) -> bool:
    """True when cmdline clearly names FamFlow / CPharm and not PharmFlow."""
    low = _norm(cmd)
    if not low:
        return False
    has_pf = any(m in low for m in _PHARMFLOW_ROOT_MARKERS)
    has_foreign = any(m in low for m in _FOREIGN_ROOT_MARKERS)
    return has_foreign and not has_pf


def cmdline_looks_pharmflow(cmd: str) -> bool:
    low = _norm(cmd)
    return any(m in low for m in _PHARMFLOW_ROOT_MARKERS) and not cmdline_looks_foreign(low)


def process_is_pharmflow_hunter(proc: Any) -> bool:
    """True only for a PharmFlow-owned ssp_paying_hunter worker."""
    try:
        argv = list(proc.cmdline() or [])
    except Exception:
        return False
    cmd = " ".join(str(x) for x in argv)
    if not cmdline_has_hunter(cmd):
        return False
    if cmdline_looks_foreign(cmd):
        return False
    if cmdline_looks_pharmflow(cmd):
        return True
    try:
        env = proc.environ() or {}
    except Exception:
        env = {}
    if str(env.get("PHARMFLOW_EXE_OWNED_FARM") or "").strip() in ("1", "true", "yes", "on"):
        return True
    pp = _norm(env.get("PYTHONPATH") or "")
    if "pharmflow" in pp and "famflow" not in pp and "cpharm" not in pp:
        return True
    try:
        cwd = _norm(proc.cwd() or "")
    except Exception:
        cwd = ""
    if "pharmflow" in cwd and "famflow" not in cwd:
        return True
    if any(m.strip("\\") in cwd for m in ("famflow", "cpharm")):
        return False
    # Ambiguous → do not count as owned (force PharmFlow spawn).
    return False


def process_is_foreign_hunter(proc: Any) -> bool:
    """True for FamFlow / CPharm hunters that must not block PharmFlow spawn."""
    try:
        argv = list(proc.cmdline() or [])
    except Exception:
        return False
    cmd = " ".join(str(x) for x in argv)
    if not cmdline_has_hunter(cmd):
        return False
    if process_is_pharmflow_hunter(proc):
        return False
    if cmdline_looks_foreign(cmd):
        return True
    try:
        cwd = _norm(proc.cwd() or "")
    except Exception:
        cwd = ""
    if "famflow" in cwd or (r"\cpharm" in f"\\{cwd}" and "pharmflow" not in cwd):
        return True
    try:
        env = proc.environ() or {}
    except Exception:
        env = {}
    pp = _norm(env.get("PYTHONPATH") or "")
    if ("famflow" in pp or "cpharm" in pp) and "pharmflow" not in pp:
        return True
    # Unknown hunter while EXE owns farm: treat as foreign so we respawn owned.
    return True


def pharmflow_hunter_pids() -> list[int]:
    try:
        import psutil
    except ImportError:
        return []
    out: list[int] = []
    try:
        for proc in psutil.process_iter(["pid"]):
            try:
                if process_is_pharmflow_hunter(proc):
                    out.append(int(proc.pid))
            except (psutil.Error, OSError, TypeError, ValueError):
                continue
    except Exception:
        return out
    return sorted(out)


def foreign_hunter_pids() -> list[int]:
    try:
        import psutil
    except ImportError:
        return []
    out: list[int] = []
    try:
        for proc in psutil.process_iter(["pid"]):
            try:
                if process_is_foreign_hunter(proc):
                    out.append(int(proc.pid))
            except (psutil.Error, OSError, TypeError, ValueError):
                continue
    except Exception:
        return out
    return sorted(out)


def hunter_script_path(root: Path | None = None) -> Path | None:
    base = Path(root) if root is not None else None
    if base is None:
        try:
            from automation.runtime_paths import code_root

            base = code_root()
        except Exception:
            base = Path(__file__).resolve().parents[1]
    for cand in (
        base / "scripts" / HUNTER_SCRIPT,
        Path(r"C:\PharmFlow") / "scripts" / HUNTER_SCRIPT,
        Path(__file__).resolve().parents[1] / "scripts" / HUNTER_SCRIPT,
    ):
        try:
            if cand.is_file():
                return cand
        except OSError:
            continue
    return None


def _helper_python() -> str:
    try:
        from automation.runtime_paths import helper_python

        found = helper_python()
        if found:
            return found
    except Exception:
        pass
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    return pyw if Path(pyw).is_file() else sys.executable


def spawn_pharmflow_paying_hunter(*, root: Path | None = None) -> int | None:
    """Spawn one PharmFlow paying hunter under C:\\PharmFlow ownership."""
    script = hunter_script_path(root)
    if script is None:
        return None
    code = script.resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(code)
    env["PHARMFLOW_EXE_OWNED_FARM"] = "1"
    env.setdefault("PHARMFLOW_LOG_DIR", r"C:\PharmFlow\logs")
    env.setdefault("PHARMFLOW_LOGS", r"C:\PharmFlow\logs")
    try:
        from automation.pharmflow_farm_config import apply_farm_env

        apply_farm_env(env)
    except Exception:
        pass
    flags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        [_helper_python(), "-u", str(script)],
        cwd=str(code),
        env=env,
        creationflags=flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return int(proc.pid)


def cull_foreign_paying_hunters() -> list[str]:
    """Kill FamFlow / CPharm hunters that block PharmFlow ownership."""
    fixes: list[str] = []
    try:
        import psutil
    except ImportError:
        return fixes
    for pid in foreign_hunter_pids():
        try:
            psutil.Process(pid).kill()
            fixes.append(f"kill_foreign_hunter pid={pid}")
        except (psutil.Error, OSError):
            continue
    return fixes


def ensure_pharmflow_paying_hunter(
    *,
    root: Path | None = None,
    cull_foreign: bool = True,
) -> list[str]:
    """Keep exactly one PharmFlow paying hunter alive.

    Foreign basename matches (FamFlow → CPharm) never satisfy this check.
    """
    fixes: list[str] = []
    if cull_foreign:
        fixes.extend(cull_foreign_paying_hunters())
        # Brief settle so process_iter does not still see killed foreign PIDs.
        if fixes:
            time.sleep(0.05)
    pids = pharmflow_hunter_pids()
    if len(pids) > 1:
        try:
            import psutil

            for pid in pids[:-1]:
                try:
                    psutil.Process(pid).kill()
                    fixes.append(f"kill_dup_pharmflow_hunter pid={pid}")
                except (psutil.Error, OSError):
                    continue
        except ImportError:
            pass
        pids = pharmflow_hunter_pids()[-1:]
    if pids:
        fixes.append(f"pharmflow_hunter_ok pid={pids[-1]}")
        return fixes
    spawned = spawn_pharmflow_paying_hunter(root=root)
    if spawned:
        fixes.append(f"spawn_pharmflow_hunter pid={spawned}")
    else:
        fixes.append("spawn_pharmflow_hunter_missing")
    return fixes
