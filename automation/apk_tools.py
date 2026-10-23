"""APK helpers — aapt package detection and multi-phone install."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from automation.adb_wrapper import AdbWrapper
from automation.browser_adb import apk_install_reported
from automation.win_subprocess import hidden_run_kwargs

logger = logging.getLogger(__name__)

_PACKAGE_RE = re.compile(r"package:\s*name='([^']+)'")


def find_aapt_exe() -> Path | None:
    """Locate aapt.exe from Android SDK build-tools if present."""
    candidates: list[Path] = []
    env_sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if env_sdk:
        candidates.append(Path(env_sdk))
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk"
    candidates.append(local)
    candidates.append(Path(r"C:\Android\Sdk"))
    for sdk in candidates:
        bt = sdk / "build-tools"
        if not bt.is_dir():
            continue
        versions = sorted([p for p in bt.iterdir() if p.is_dir()], reverse=True)
        for ver in versions:
            aapt = ver / "aapt.exe"
            if aapt.is_file():
                return aapt
    which = shutil.which("aapt")
    return Path(which) if which else None


def package_from_apk(apk_path: str | Path, aapt: Path | None = None) -> str | None:
    """Return package name from APK via `aapt dump badging`, or None."""
    path = Path(apk_path)
    if not path.is_file():
        return None
    tool = aapt or find_aapt_exe()
    if not tool:
        logger.warning("aapt not found — cannot auto-detect package from %s", path.name)
        return None
    try:
        proc = subprocess.run(
            [str(tool), "dump", "badging", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            **hidden_run_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("aapt failed: %s", exc)
        return None
    match = _PACKAGE_RE.search(proc.stdout or "")
    return match.group(1) if match else None


def install_apk_on_serials(
    adb: AdbWrapper,
    apk_path: str | Path,
    serials: list[str],
) -> dict[str, bool]:
    """Install APK on each serial with `adb install -r`. Returns serial -> ok."""
    path = Path(apk_path)
    results: dict[str, bool] = {}
    if not path.is_file():
        logger.error("APK not found: %s", path)
        return {s: False for s in serials}
    for serial in serials:
        try:
            result = adb.install(str(path), serial=serial)
            ok = apk_install_reported(result.stdout, result.stderr, result.returncode)
            results[serial] = ok
            logger.info("install %s on %s -> %s", path.name, serial, ok)
        except Exception as exc:
            logger.warning("install failed on %s: %s", serial, exc)
            results[serial] = False
    return results
