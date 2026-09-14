"""FarmBrowser install + UI guard — single owner (stealth lane). No double re-arm."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from automation.config import BROWSER_FARMBROWSER

LOG = Path(r"C:\PharmFlow\logs")
ADB = Path(r"C:\PharmFlow\bundled\adb.exe")
APK_CANDIDATES = (
    Path(r"C:\PharmFlow\farmbrowser\app\build\outputs\apk\debug\app-debug.apk"),
    Path(r"C:\PharmFlow\apks\farmbrowser-debug.apk"),
)
FB_ACTIVITY = "com.farmbrowser.stealth.browser.BrowserActivity"
INSTALL_STAMP = LOG / "_farmbrowser_install_stamp.json"
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LAWNCHAIR_PKGS = (
    "app.lawnchair",
    "ch.deletescape.lawnchair",
    "com.google.android.apps.nexuslauncher",
)


def _adb(*args: str, serial: str = "", timeout: float = 20.0) -> str:
    cmd = [str(ADB)]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(args)
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=FLAGS,
        )
        return ((p.stdout or "") + (p.stderr or "")).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"ERR:{exc}"


def _apk_path() -> Path | None:
    for p in APK_CANDIDATES:
        if p.is_file():
            return p
    return None


def farmbrowser_installed(serial: str) -> bool:
    out = _adb("shell", "pm", "list", "packages", BROWSER_FARMBROWSER, serial=serial, timeout=12.0)
    return BROWSER_FARMBROWSER in out


def ensure_farmbrowser_installed(serial: str) -> str:
    """Install APK once per serial until Success."""
    if farmbrowser_installed(serial):
        return "already"
    stamp: dict[str, float] = {}
    if INSTALL_STAMP.is_file():
        try:
            raw = json.loads(INSTALL_STAMP.read_text(encoding="utf-8-sig"))
            if isinstance(raw, dict):
                stamp = {str(k): float(v) for k, v in raw.items()}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            stamp = {}
    last = float(stamp.get(serial) or 0)
    if time.time() - last < 300.0:
        return "install_cooldown"
    apk = _apk_path()
    if apk is None:
        return "missing_apk"
    out = _adb("install", "-r", "-g", str(apk), serial=serial, timeout=180.0)
    stamp[serial] = time.time()
    try:
        INSTALL_STAMP.parent.mkdir(parents=True, exist_ok=True)
        INSTALL_STAMP.write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    if "Success" in out:
        return "installed"
    return out[:80]


def stop_lawnchair(serial: str) -> list[str]:
    fixes: list[str] = []
    for pkg in LAWNCHAIR_PKGS:
        top_hint = _adb("shell", "dumpsys", "activity", "top", serial=serial, timeout=6.0)
        if pkg.split(".")[-1] in (top_hint or "").lower() or pkg in (top_hint or ""):
            _adb("shell", "am", "force-stop", pkg, serial=serial, timeout=8.0)
            fixes.append(f"stop_lawnchair {pkg}")
    return fixes


def arm_dabflow_farmbrowser(serial: str) -> str:
    if not farmbrowser_installed(serial):
        return "no_apk"
    out = _adb(
        "shell",
        "am",
        "start",
        "-a",
        "android.intent.action.VIEW",
        "-d",
        "https://getdabflow.app/",
        "-n",
        f"{BROWSER_FARMBROWSER}/{FB_ACTIVITY}",
        serial=serial,
        timeout=12.0,
    )
    return out[:100]


def farm_sequences_active() -> bool:
    """True when run_farm_354 has live actives — stealth must not double-tap."""
    prog = LOG / "farm_354_progress.json"
    if not prog.is_file():
        return False
    try:
        data = json.loads(prog.read_text(encoding="utf-8-sig"))
        updated = str(data.get("updated") or "")
        if updated:
            from datetime import datetime

            ts = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            age = (datetime.now(ts.tzinfo) - ts).total_seconds()
            if age > 180.0:
                return False
        phones = data.get("phones") if isinstance(data.get("phones"), dict) else {}
        for row in phones.values():
            last = row.get("last") if isinstance(row, dict) else {}
            if isinstance(last, dict) and last.get("success") is None:
                return True
        return bool(data.get("active"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False


def ensure_phones_farmbrowser(
    phone_rows: list[dict],
    *,
    allow_ui_rearm: bool = True,
) -> list[str]:
    """Install FarmBrowser + stop Lawnchair. Re-arm dabflow only when idle."""
    fixes: list[str] = []
    farm_busy = farm_sequences_active()
    for row in phone_rows:
        serial = str(row.get("serial") or "")
        name = str(row.get("name") or "")
        if not serial or row.get("state") != "device":
            continue
        inst = ensure_farmbrowser_installed(serial)
        if inst not in ("already", "install_cooldown"):
            fixes.append(f"fb_{name}:{inst}")
        fixes.extend(stop_lawnchair(serial))
        top = str(row.get("top") or "").lower()
        if farm_busy and not allow_ui_rearm:
            fixes.append(f"skip_fb_rearm {name} farm_active")
            continue
        idle = any(
            x in top
            for x in (
                "lawnchair",
                "launcher",
                "settings",
                "systemui",
                "not responding",
            )
        )
        if idle or (not farm_busy and "farmbrowser" not in top):
            if "farmbrowser" not in top and not farm_busy:
                arm = arm_dabflow_farmbrowser(serial)
                fixes.append(f"arm_fb {name} {arm[:50]}")
    return fixes
