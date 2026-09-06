"""
Ensure pythonnet can host pywebview's WinForms/EdgeChromium backend on this machine.

pywebview's Windows backend loads .NET through pythonnet. Two runtimes can host it:

  netfx   - .NET Framework 4.x, built into every Windows install. Preferred:
            zero downloads, no admin, and it owns the legacy ``ContextMenu``
            type that pywebview's edgechromium reflection requires. On .NET
            Core 5+ that type was removed, so coreclr reflection of the
            WebView2 control fails with ``TypeLoadException``.

  coreclr - .NET Core/5+ Desktop runtime. Used only when netfx is unavailable.
            If no Desktop runtime is present, one is auto-installed (user-local,
            no admin) via Microsoft's ``dotnet-install.ps1`` into
            ``%LOCALAPPDATA%\\Microsoft\\dotnet``, then wired up with a
            runtime spec that references ``Microsoft.WindowsDesktop.App``.

``ensure_pythonnet_ready()`` returns ``"netfx"`` / ``"coreclr"`` on success and
``None`` on total failure (caller falls back to the Tk deck). Every step is
logged to ``%USERPROFILE%\\CPharm\\dotnet_provision.log`` so a headless EXE
failure is diagnosable without the agent.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
from pathlib import Path

_LOG_DIR = Path.home() / "CPharm"
_LOG_PATH = _LOG_DIR / "dotnet_provision.log"

logger = logging.getLogger("dotnet_provision")

_ARCH_ALIASES = {
    "AMD64": "x64",
    "x86_64": "x64",
    "ARM64": "arm64",
    "aarch64": "arm64",
}


def _machine_arch() -> str:
    """Match the running Python's architecture (native ARM64 or emulated x64)."""
    m = platform.machine()
    return _ARCH_ALIASES.get(m, m.lower())


def _local_app_data() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    if root:
        return Path(root)
    return Path.home() / "AppData" / "Local"


def _dotnet_root_candidates() -> list[Path]:
    cands: list[Path] = []
    env_root = os.environ.get("DOTNET_ROOT")
    if env_root:
        cands.append(Path(env_root))
    prog = os.environ.get("ProgramFiles")
    if prog:
        cands.append(Path(prog) / "dotnet")
    cands.append(_local_app_data() / "Microsoft" / "dotnet")
    seen: set[Path] = set()
    uniq: list[Path] = []
    for c in cands:
        c = c.resolve()
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def _has_desktop_runtime(root: Path) -> bool:
    return (root / "shared" / "Microsoft.WindowsDesktop.App").is_dir()


def _newest_desktop_version(root: Path) -> str | None:
    d = root / "shared" / "Microsoft.WindowsDesktop.App"
    if not d.is_dir():
        return None
    versions = [p.name for p in d.iterdir() if p.is_dir()]
    if not versions:
        return None
    return sorted(versions, key=lambda v: [int(x) for x in v.split(".")[:3]])[-1]


def _install_desktop_runtime(root: Path) -> bool:
    """Download + run Microsoft's dotnet-install.ps1 (user-local, no admin)."""
    try:
        tmp = Path(os.environ.get("TEMP", "/tmp"))
        script = tmp / "dotnet-install.ps1"
        ps = (
            f"$ErrorActionPreference='Stop'; "
            f"Invoke-WebRequest https://dot.net/v1/dotnet-install.ps1 -OutFile '{script}'; "
            f"& '{script}' -Channel 8.0 -Runtime dotnet -Architecture {_machine_arch()} "
            f"-InstallDir '{root}' 2>&1 | Out-Null; "
            f"& '{script}' -Channel 8.0 -Runtime windowsdesktop -Architecture {_machine_arch()} "
            f"-InstallDir '{root}' 2>&1 | Out-Null"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=600,
        )
        ok = r.returncode == 0 and _has_desktop_runtime(root)
        logger.info("dotnet-install rc=%s ok=%s", r.returncode, ok)
        if not ok:
            logger.warning("dotnet-install stderr: %s", (r.stderr or "")[-2000:])
        return ok
    except Exception as exc:  # noqa: BLE001 - provisioning must never crash the app
        logger.warning("dotnet-install failed: %s", exc)
        return False


def _activate_coreclr(root: Path) -> bool:
    """Wire pythonnet to the Desktop runtime at ``root`` and preload WinForms."""
    try:
        import clr_loader
        import pythonnet
        from clr_loader.util.runtime_spec import DotnetCoreRuntimeSpec

        version = _newest_desktop_version(root)
        if not version:
            logger.warning("no WindowsDesktop version under %s", root)
            return False
        spec = DotnetCoreRuntimeSpec(
            "Microsoft.WindowsDesktop.App",
            version,
            root / "shared" / "Microsoft.WindowsDesktop.App" / version,
        )
        # set_runtime MUST precede any `import clr` (that would trigger the
        # default netfx loader first).
        pythonnet.set_runtime(
            clr_loader.get_coreclr(runtime_spec=spec, dotnet_root=root)
        )
        import clr  # noqa: F401  (no-op now; runtime already selected)

        # Own assembly in the Desktop framework; needed by pywebview's import.
        clr.AddReference("Microsoft.Win32.SystemEvents")
        clr.AddReference("System.Windows.Forms")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("coreclr activation failed: %s", exc)
        return False


def _activate_netfx() -> bool:
    """Load pythonnet against the built-in .NET Framework (no downloads)."""
    # clr_loader only ships amd64/x86 ClrLoader.dll — native ARM64 Python cannot
    # load them (WinError 0xc1). Skip so ARM64 goes straight to coreclr + netcore
    # WebView2 WinForms DLLs (see PharmFlow.spec bundled/webview2_netcore).
    if _machine_arch() == "arm64":
        logger.info("skipping netfx on arm64 (no ARM64 ClrLoader.dll in clr_loader)")
        return False
    try:
        import pythonnet

        pythonnet.load("netfx")
        import clr  # noqa: F401  (now no-ops; runtime already loaded)

        clr.AddReference("System.Windows.Forms")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("netfx activation failed: %s", exc)
        return False


def ensure_pythonnet_ready() -> str | None:
    """Return 'netfx' | 'coreclr' once pythonnet can host WinForms, else None."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        logger.handlers.clear()
        h = logging.FileHandler(_LOG_PATH, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
        logger.setLevel(logging.INFO)
    except OSError:
        pass

    logger.info("ensure_pythonnet_ready arch=%s frozen=%s", _machine_arch(), getattr(sys, "frozen", False))

    if _activate_netfx():
        logger.info("using netfx (built-in .NET Framework)")
        return "netfx"

    for root in _dotnet_root_candidates():
        if _has_desktop_runtime(root) and _activate_coreclr(root):
            logger.info("using coreclr at %s", root)
            return "coreclr"

    auto = _local_app_data() / "Microsoft" / "dotnet"
    logger.info("no Desktop runtime found; installing to %s", auto)
    if _install_desktop_runtime(auto) and _activate_coreclr(auto):
        logger.info("using auto-installed coreclr at %s", auto)
        return "coreclr"

    logger.error("no usable .NET runtime; Tk fallback will be used")
    return None