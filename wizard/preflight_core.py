"""
Shared preflight checks for CPharmMuMuSetup and the wizard (MuMu / adb / exes).

Keeps host + MuMu readiness logic in one place so the setup exe and wizard do not
duplicate downloads or contradict each other.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import webbrowser
import zipfile
from pathlib import Path
from typing import Callable

IS_WIN = platform.system() == "Windows"
MUMU_DOWNLOAD_URL = "https://www.mumuglobal.com/download"
CPHARM_RELEASES_URL = "https://github.com/twoskoops707/cpharm/releases/latest"
SDK_DEFAULT_PATH = Path(os.environ.get("LOCALAPPDATA", "C:\\")) / "Android" / "Sdk"

MUMU_MANAGER_NAMES = (
    "nemux-shell-winui.Manager.exe",
    "MuMuManager.exe",
)

LogFn = Callable[[str], None]


def _subproc_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WIN else 0


def _adb_path(sdk_root: Path | None = None) -> Path:
    root = sdk_root or SDK_DEFAULT_PATH
    return root / "platform-tools" / ("adb.exe" if IS_WIN else "adb")


def adb_usable() -> bool:
    """True if adb exists and responds to ``version``."""
    try:
        from adb_paths import adb_executable

        exe = adb_executable()
    except Exception:
        exe = str(_adb_path())
    if not Path(exe).is_file():
        return False
    try:
        r = subprocess.run(
            [exe, "version"],
            capture_output=True,
            text=True,
            timeout=12,
            creationflags=_subproc_flags(),
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def find_mumu_install() -> Path | None:
    """Best-effort: MuMu manager CLI or player GUI on Windows."""
    try:
        import mumu_detect

        return mumu_detect.find_mumu_install()
    except Exception:
        pass
    return _legacy_find_mumu_install()


def _legacy_find_mumu_install() -> Path | None:
    """Fallback when mumu_detect import fails."""
    if not IS_WIN:
        return None

    for query in MUMU_MANAGER_NAMES:
        hit = shutil.which(query)
        if hit and Path(hit).is_file():
            return Path(hit)

    roots = [
        Path(os.environ.get("ProgramFiles", "C:\\Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")),
        Path(os.environ.get("LOCALAPPDATA", "")),
    ]
    for base in roots:
        if not base.is_dir():
            continue
        for pattern in ("MuMu*", "Netease*", "MuMuPlayer*"):
            try:
                for folder in base.glob(pattern):
                    for sub in ("shell", "nx_main", ""):
                        for name in MUMU_MANAGER_NAMES:
                            p = folder / sub / name if sub else folder / name
                            if p.is_file():
                                return p
                    if folder.name.lower() == "netease":
                        for child in folder.iterdir():
                            if not child.is_dir() or "mumu" not in child.name.lower():
                                continue
                            for sub in ("shell", "nx_main", ""):
                                for name in MUMU_MANAGER_NAMES:
                                    p = child / sub / name if sub else child / name
                                    if p.is_file():
                                        return p
            except OSError:
                continue
    return None


def cpharm_exe_beside_setup() -> tuple[bool, Path]:
    """True when PharmFlow is available — unified exe counts as ready."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        if exe.stem.lower() == "cpharm":
            return True, exe
        folder = exe.parent
        cpharm = folder / "CPharm.exe"
        return cpharm.is_file(), cpharm
    folder = Path(__file__).resolve().parent
    return True, folder / "CPharm.exe"


def setup_marker_path(data_root: Path) -> Path:
    return data_root / "automation" / "recordings" / "desktop_prefs.json"


def read_setup_marker(data_root: Path) -> dict:
    p = setup_marker_path(data_root)
    if not p.is_file():
        return {}
    try:
        import json

        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def mumu_setup_already_done(data_root: Path) -> bool:
    return bool(read_setup_marker(data_root).get("mumu_setup_complete"))


def open_mumu_download() -> None:
    webbrowser.open(MUMU_DOWNLOAD_URL)


def open_cpharm_releases() -> None:
    webbrowser.open(CPHARM_RELEASES_URL)


def download_platform_tools(log_fn: LogFn | None = None) -> bool:
    """Install Google's platform-tools (~6 MB) into the default SDK path."""
    sdk_root = SDK_DEFAULT_PATH
    pt = _adb_path(sdk_root)
    if pt.is_file():
        return True
    if IS_WIN:
        url = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
    elif platform.system() == "Darwin":
        url = "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip"
    else:
        url = "https://dl.google.com/android/repository/platform-tools-latest-linux.zip"
    tmp = sdk_root / "_pt_tmp.zip"
    if log_fn:
        log_fn("Downloading phone connection tools (adb)… about 6 MB.")
    try:
        sdk_root.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, tmp)
        with zipfile.ZipFile(tmp, "r") as zf:
            zf.extractall(sdk_root)
        tmp.unlink(missing_ok=True)
        if log_fn:
            log_fn("Phone connection tools installed.")
        return pt.is_file()
    except Exception as exc:
        if log_fn:
            log_fn(f"Download failed: {exc}")
        tmp.unlink(missing_ok=True)
        return False


def list_adb_phones() -> list[str]:
    try:
        from adb_paths import adb_executable

        exe = adb_executable()
    except Exception:
        exe = str(_adb_path())
    if not Path(exe).is_file():
        return []
    try:
        r = subprocess.run(
            [exe, "devices", "-l"],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=_subproc_flags(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    out: list[str] = []
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line or line.startswith("List of"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            out.append(parts[0])
    return out


def try_connect_mumu_via_adb(
    log_fn: LogFn | None = None,
    *,
    force_full_scan: bool = False,
) -> list[str]:
    """Best-effort ``adb connect`` to MuMu TCP ports before ``adb devices``."""
    if not IS_WIN or not adb_usable():
        return []
    try:
        import setup_wizard as wiz

        wiz.state["use_mumu"] = True
        mgr = wiz._find_mumu_manager()
        if mgr:
            wiz.state["mumu_mgr_path"] = str(mgr)
        return wiz._connect_mumu_phones(
            count=16,
            log_fn=log_fn,
            force_full_scan=force_full_scan,
        )
    except Exception as exc:
        if log_fn:
            log_fn(f"  MuMu connect warning: {exc}\n")
        return []


def discover_adb_phones(
    log_fn: LogFn | None = None,
    *,
    connect_mumu: bool = True,
    force_mumu_scan: bool = False,
) -> list[str]:
    """List adb devices from BOTH sources — MuMu AND Docker-redroid.

    Docker-redroid and MuMu are meant to run side by side in one farm, so we
    always probe both port ranges instead of treating one as the only source.
    Phone endpoints that connect but never reach ``device`` (e.g. redroid that
    sits ``offline`` when the host can't boot it) are filtered by
    ``list_adb_phones()``, so only usable online phones are returned. Bounded
    and non-blocking throughout.

    Docker stays open alongside the farm: nothing here stops the engine, and the
    redroid range is only probed — offline nodes are simply not surfaced.
    """
    already = list_adb_phones()
    if already and not force_mumu_scan:
        # Sessions survived a restart — still also connect the Docker-redroid
        # range so Docker phones appear alongside the MuMu ones, then re-list.
        auto_connect_all_phones(log_fn)
        return list_adb_phones()
    if connect_mumu:
        try_connect_mumu_via_adb(log_fn, force_full_scan=force_mumu_scan)
    # Connect BOTH the MuMu (16384-16393) and Docker-redroid (5555-5562) ranges
    # so the two phone types run together, not either-or. Never sleeps, never
    # raises; offline/unbooted nodes are filtered below.
    auto_connect_all_phones(log_fn)
    return list_adb_phones()


_AUTO_CONNECT_RANGES = ((16384, 10), (5555, 8))  # (start_port, count) MuMu then emulator/cloud


def auto_connect_all_phones(log_fn: LogFn | None = None) -> list[str]:
    """Best-effort ``adb connect`` to known MuMu + emulator/cloud TCP ports.

    Intended as a quick last-resort from :func:`discover_adb_phones` when the
    primary scanner returns nothing. Each connect is bounded to a few seconds and
    the function never sleeps or raises, so the wizard UI cannot hang on phone
    discovery.
    """
    try:
        from adb_paths import adb_executable

        exe = adb_executable()
    except Exception:
        exe = str(_adb_path())
    if not Path(exe).is_file():
        return []
    for start, count in _AUTO_CONNECT_RANGES:
        for off in range(count):
            addr = f"127.0.0.1:{start + off}"
            try:
                subprocess.run(
                    [exe, "connect", addr],
                    capture_output=True,
                    text=True,
                    timeout=4,
                    creationflags=_subproc_flags(),
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
    if log_fn:
        log_fn("  auto-connect finished; re-scanning adb devices\n")
    return list_adb_phones()


def _site_display_host() -> str:
    try:
        from site_prefs import site_display_host

        return site_display_host()
    except Exception:
        return "your target site"


def build_checklist(data_root: Path) -> list[dict]:
    """
    Plain-English steps for the setup UI. Each item:
    id, title, help, status (pass|fail|manual|warn), optional action key.
    """
    exe_ok, exe_path = cpharm_exe_beside_setup()
    mumu = find_mumu_install()
    adb_ok = adb_usable()
    phones = list_adb_phones()
    setup_done = mumu_setup_already_done(data_root)
    awaiting_reboot = bool(read_setup_marker(data_root).get("mumu_awaiting_cold_boot"))
    browser_ok = False
    browser_help = ""
    tablet_warn = False
    try:
        import mumu_farm_ops as farm

        bad_profiles = [p for p in farm.scan_mumu_vm_profiles() if farm.profile_needs_phone_baseline(p)]
        tablet_warn = bool(bad_profiles)
    except Exception:
        tablet_warn = False
    if phones and adb_ok:
        try:
            import browser_setup

            missing = [s for s in phones if not browser_setup.dabflow_ad_browser_installed(s)]
            browser_ok = not missing
            sideload = browser_setup.find_sideload_apk(serial=phones[0] if phones else None)
            if missing and sideload:
                browser_help = (
                    f"Chromium missing on {len(missing)} phone(s). Click Set up my phones below "
                    f"(or Install Chromium; APK ready: {sideload[0].name})."
                )
            elif missing:
                from site_prefs import site_display_host

                host = site_display_host()
                browser_help = (
                    "Chromium not installed yet. Click Set up my phones below. "
                    f"{host} ads need Chromium on each phone."
                )
            elif setup_done:
                from site_prefs import site_display_host

                host = site_display_host()
                browser_help = f"Chromium installed — {host} ads use this browser."
        except Exception:
            browser_ok = True

    items: list[dict] = [
        {
            "id": "folder",
            "title": "PharmFlow is ready",
            "help": "One CPharm.exe does everything — wizard, phone setup, and dashboard.",
            "status": "pass" if exe_ok else "fail",
            "action": None if exe_ok else "download_cpharm",
        },
        {
            "id": "mumu",
            "title": "MuMu is on this computer",
            "help": "MuMu Player must be installed." if not mumu else "MuMu found. Good!",
            "status": "pass" if mumu else "fail",
            "action": None if mumu else "download_mumu",
        },
        {
            "id": "mumu_profile",
            "title": "Phones look like real phones (not tablets)",
            "help": (
                "Click Fix — then turn each phone off and on again."
                if tablet_warn
                else "Looks good."
            ),
            "status": "warn" if tablet_warn else ("pass" if mumu else "manual"),
            "action": "fix_tablet" if tablet_warn else None,
        },
        {
            "id": "adb",
            "title": "Phone connection helper (adb)",
            "help": "Click Fix if this line is red. We download a tiny helper for you.",
            "status": "pass" if adb_ok else "fail",
            "action": None if adb_ok else "install_adb",
        },
        {
            "id": "mumu_run",
            "title": "MuMu is running",
            "help": "Open MuMu on your computer. Press Start on each phone. Wait for the home screen.",
            "status": "manual",
            "action": None,
        },
        {
            "id": "usb",
            "title": "USB debugging is ON",
            "help": (
                "Settings → Developer options → USB debugging ON — leave it on. "
                "PharmFlow needs this to control MuMu; it does not stop hiding the emulator from websites. "
                "If MuMu shows a Root switch, leave Root ON."
            ),
            "status": "manual",
            "action": None,
        },
        {
            "id": "phones",
            "title": "PharmFlow sees your phones",
            "help": "Click Check again when MuMu is running.",
            "status": "pass" if phones else ("warn" if adb_ok else "fail"),
            "action": "refresh",
            "phone_count": len(phones),
            "phones": phones,
        },
        {
            "id": "browser",
            "title": "Chromium on each phone",
            "help": browser_help
            or (
                f"Click Set up my phones below — downloads Chromium once (~230 MB) for {_site_display_host()} ads."
                if phones
                else "Start MuMu first, then refresh checks."
            ),
            "status": "pass" if browser_ok else ("warn" if phones else "manual"),
            "action": "install_chromium" if phones and not browser_ok else None,
        },
        {
            "id": "ads",
            "title": "Phones disguised for ads",
            "help": f"Click Set up my phones — makes phones look like real devices and prepares {_site_display_host()} ads.",
            "status": "pass" if setup_done else ("manual" if phones else "warn"),
            "action": None,
        },
    ]
    if awaiting_reboot:
        items.insert(
            0,
            {
                "id": "cold_boot",
                "title": "STOP — turn phones off and on",
                "help": "Stop every MuMu phone. Start them again. Then click Set up my phones.",
                "status": "fail",
                "action": None,
            },
        )
    if setup_done and not awaiting_reboot:
        items.append(
            {
                "id": "done_before",
                "title": "All set on this step",
                "help": (
                    "Continue the wizard: Test (5) → Steps (6) → Groups (8) → Run (9). "
                    "Builder (7) is optional."
                ),
                "status": "pass",
                "action": None,
            }
        )
    if not exe_ok:
        items[0]["help"] = f"Missing: {exe_path.parent}\\CPharm.exe — download from GitHub Releases."
    return items


def run_check_action(action: str, log_fn: LogFn | None = None) -> dict:
    """Handle checklist button actions from the setup UI."""
    log = log_fn or (lambda _m: None)
    if action == "download_mumu":
        open_mumu_download()
        return {"ok": True, "message": "Opened MuMu download page in your browser."}
    if action == "download_cpharm":
        open_cpharm_releases()
        return {"ok": True, "message": "Opened GitHub Releases — download CPharm.exe into this folder."}
    if action == "install_adb":
        ok = download_platform_tools(log)
        return {
            "ok": ok,
            "message": "adb ready." if ok else "Could not install adb — check your internet and try again.",
        }
    if action == "refresh":
        phones = discover_adb_phones(log, connect_mumu=True, force_mumu_scan=True)
        return {"ok": True, "phones": phones, "phone_count": len(phones)}
    if action == "fix_tablet":
        import mumu_farm_ops as farm

        n = farm.fix_mumu_tablet_profiles(log)
        msg = (
            f"Patched {n} MuMu VM(s) to Phone 900×1600. Stop and start each phone, then Set up my phones again."
            if n
            else "All MuMu VMs already Phone 900×1600 (or MuMu vms/ not found)."
        )
        return {"ok": True, "message": msg, "fixed_count": n}
    if action == "download_chromium":
        import mumu_farm_ops as farm

        apk = farm.download_chromium_apk(log)
        if apk and apk.is_file():
            return {"ok": True, "message": f"Saved {apk} — use Install Chromium to sideload phones."}
        return {"ok": False, "message": "Chromium download failed — check internet."}
    if action == "install_chromium":
        import mumu_farm_ops as farm

        if not adb_usable():
            ok = download_platform_tools(log)
            if not ok:
                return {"ok": False, "message": "Could not install adb — click Fix on Step 3."}
        serials = discover_adb_phones(log, connect_mumu=True, force_mumu_scan=True)
        if not serials:
            return {"ok": False, "message": "No phones — boot MuMu and turn USB debugging ON."}
        summary = farm.install_chromium_on_phones(serials, log)
        return {
            "ok": summary.get("ok", False),
            "message": summary.get("message", ""),
            "apk": summary.get("apk", ""),
            "results": summary.get("results", []),
        }
    if action == "audit_fingerprint":
        import mumu_farm_ops as farm

        serials = discover_adb_phones(log, connect_mumu=True, force_mumu_scan=True)
        if not serials:
            return {"ok": False, "message": "No phones — boot MuMu and turn USB debugging ON."}
        summary = farm.audit_fingerprint_all(serials, log)
        clean = summary.get("all_clean")
        return {
            "ok": clean,
            "message": (
                "All phones look clean."
                if clean
                else f"{summary.get('phones_with_leaks', 0)} phone(s) still leak — click GO to fix."
            ),
            "summary": summary,
        }
    if action == "apply_fingerprint":
        import mumu_farm_ops as farm

        serials = discover_adb_phones(log, connect_mumu=True, force_mumu_scan=True)
        if not serials:
            return {"ok": False, "message": "No phones — boot MuMu first."}
        summary = farm.apply_fingerprint_all(serials, log, patch_vms=True)
        leaks = summary.get("leaks_total", 0)
        return {
            "ok": leaks == 0,
            "message": (
                "Fingerprint applied — all phones look clean."
                if leaks == 0
                else f"Applied — {leaks} leak(s) left. Cold-boot MuMu phones if VM settings changed."
            ),
            "summary": summary,
        }
    return {"ok": False, "message": f"Unknown action: {action}"}
