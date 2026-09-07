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
import time
import urllib.request
import webbrowser
import zipfile
from pathlib import Path
from typing import Callable

IS_WIN = platform.system() == "Windows"
MUMU_DOWNLOAD_URL = "https://www.mumuglobal.com/download"
CPHARM_RELEASES_URL = "https://github.com/twoskoops707/pharmflow/releases/latest"
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
    """True when PharmFlow is available — the running app counts as ready.

    The unified PharmFlow.exe (formerly CPharm.exe) runs phone setup in-process
    (``--phone-setup``), so when this code runs the app is already available.
    """
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        stem = exe.stem.lower()
        if stem in ("pharmflow", "cpharm"):
            return True, exe
        # Legacy standalone helper exe: look for the main app beside it.
        for name in ("PharmFlow.exe", "CPharm.exe"):
            sibling = exe.parent / name
            if sibling.is_file():
                return True, sibling
        return False, exe.parent / "PharmFlow.exe"
    # Running from source inside the app — the app is live.
    return True, Path(__file__).resolve().parent / "cpharm_desktop.py"


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


# (start_port, stride, count) — MuMu uses 16384 + n*32; emulator/cloud uses 5555 + n*2
_AUTO_CONNECT_RANGES = ((16384, 32, 10), (5555, 2, 8))


def _adb_exe() -> str:
    """Single adb resolution used by every discovery helper."""
    try:
        from adb_paths import adb_executable

        return adb_executable()
    except Exception:
        return str(_adb_path())


def _known_fleet_serials() -> list[str]:
    """Live farm serials from CPharm runtime state, never hardcoded ports.

    The farm stack (supervisor, cycles, injectors) persists the canonical
    vm→10.0.2.x mapping in ADB_SERIAL_MAP.lock.json and the active serial list in
    farm_runtime_overrides.json (CPHARM_ADB_SERIALS). On ARM MuMu the guest
    phones live on 10.0.2.x NAT addresses, which the legacy 127.0.0.1 range
    scan can never reach — so discovery must re-attach these exact serials.
    Best-effort and bounded; returns [] when no farm state exists.
    """
    import json

    log_dir = Path(os.environ.get("CPHARM_LOG_DIR", r"C:\CPharm\logs"))
    serials: list[str] = []
    seen: set[str] = set()

    def _add(s: str) -> None:
        s = (s or "").strip()
        if not s or ":" not in s:
            return
        if s in seen:
            return
        seen.add(s)
        serials.append(s)

    try:
        lock = log_dir / "ADB_SERIAL_MAP.lock.json"
        if lock.is_file():
            data = json.loads(lock.read_text(encoding="utf-8-sig"))
            for m in (data.get("phones") or {}, data.get("tablet") or {}):
                for serial in m.values():
                    _add(str(serial))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    try:
        over = log_dir / "farm_runtime_overrides.json"
        if over.is_file():
            data = json.loads(over.read_text(encoding="utf-8-sig"))
            raw = str(data.get("CPHARM_ADB_SERIALS") or "")
            for serial in raw.split(","):
                _add(serial)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return serials


def _connect_serials(serials: list[str], *, deadline: float | None = None) -> list[str]:
    """Bounded ``adb connect`` for each serial; returns online phones found.

    Honors an optional monotonic ``deadline`` so a fleet of dead endpoints can
    never stall discovery beyond the budget — each connect gets at most
    ``min(4, remaining)`` seconds and the loop stops the moment the budget is
    gone.
    """
    exe = _adb_exe()
    if not Path(exe).is_file() or not serials:
        return []
    for serial in serials:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0.1:
                break
        else:
            remaining = 4.0
        try:
            subprocess.run(
                [exe, "connect", serial],
                capture_output=True,
                text=True,
                timeout=min(4.0, remaining),
                creationflags=_subproc_flags(),
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
    return list_adb_phones()


# Whole discovery must never eat more than this even with a fully dead fleet.
_DISCOVER_BUDGET_S = 12.0


def _restart_adb_server() -> None:
    """Restart the local adb server once (kills a wedged/stale 5037 daemon).

    The Windows adb server can outlive its TCP fleet: the daemon keeps answering
    ``adb devices`` with an empty list while ``adb connect`` to a running VM
    hangs (WinError 10060). A fresh server re-attaches the fleet immediately.
    Bounded and silent — never raises.
    """
    exe = _adb_exe()
    if not Path(exe).is_file():
        return
    for arg in ("kill-server", "start-server"):
        try:
            subprocess.run(
                [exe, arg],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=_subproc_flags(),
            )
        except (OSError, subprocess.TimeoutExpired):
            return


def discover_adb_phones(
    log_fn: LogFn | None = None,
    *,
    connect_mumu: bool = True,
    force_mumu_scan: bool = False,
) -> list[str]:
    """List adb devices from BOTH sources — MuMu AND Docker-redroid.

    Docker-redroid and MuMu are meant to run side by side in one farm, so we
    probe the farm's known fleet serials first, then both port ranges instead of
    treating one as the only source. A wedged/stale 5037 adb server (empty
    ``adb devices`` while VMs are up, connects hanging) is self-healed with one
    server restart. The whole call is capped at ``_DISCOVER_BUDGET_S`` seconds
    even when every endpoint is dead — discovery can never hang the deck.
    Never raises.

    Docker stays open alongside the farm: nothing here stops the engine, and the
    redroid range is only probed — offline nodes are simply not surfaced.
    """
    import time as _t

    deadline = _t.monotonic() + _DISCOVER_BUDGET_S
    already = list_adb_phones()
    if already and not force_mumu_scan:
        # Sessions survived a restart — still also connect the Docker-redroid
        # range so Docker phones appear alongside the MuMu ones, then re-list.
        auto_connect_all_phones(log_fn)
        return list_adb_phones()
    fleet = _known_fleet_serials()
    if fleet:
        # Probe the server with ONE short connect. If the fleet can't attach the
        # 5037 daemon is wedged (connects hang with 10060 while ``adb devices``
        # still answers "0 devices") — restart once, then connect the fleet.
        if _t.monotonic() < deadline:
            try:
                subprocess.run(
                    [_adb_exe(), "connect", fleet[0]],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    creationflags=_subproc_flags(),
                )
            except (OSError, subprocess.TimeoutExpired):
                _restart_adb_server()
        got = _connect_serials(fleet, deadline=deadline)
        if got:
            if log_fn:
                log_fn(f"  re-attached fleet: {len(got)} phone(s)\n")
            return got
        if _t.monotonic() < deadline:
            _restart_adb_server()
            got = _connect_serials(fleet, deadline=deadline)
            if got:
                if log_fn:
                    log_fn(f"  adb server restarted; fleet back: {len(got)} phone(s)\n")
                return got
    if connect_mumu and _t.monotonic() < deadline:
        try_connect_mumu_via_adb(log_fn, force_full_scan=force_mumu_scan)
    # Connect BOTH the MuMu (16384 + n*32) and Docker-redroid (5555 + n*2) ranges
    # so the two phone types run together, not either-or. Never sleeps, never
    # raises; offline/unbooted nodes are filtered below.
    return auto_connect_all_phones(log_fn, deadline=deadline)


def auto_connect_all_phones(
    log_fn: LogFn | None = None,
    *,
    deadline: float | None = None,
) -> list[str]:
    """Best-effort ``adb connect`` to the farm fleet + emulator/cloud ranges.

    Connects the farm's known 10.0.2.x serials first (the only addresses that
    reach ARM MuMu guests), then the legacy localhost port ranges as a
    fallback for other emulators. Each connect is bounded to a few seconds,
    honors the shared ``deadline``, and never sleeps or raises — the wizard UI
    cannot hang on phone discovery.
    """
    import time as _t

    exe = _adb_exe()
    if not Path(exe).is_file():
        return []
    fleet = _known_fleet_serials()
    if fleet:
        got = _connect_serials(fleet, deadline=deadline)
        if got:
            return got
        if deadline is None or _t.monotonic() < deadline:
            _restart_adb_server()
            got = _connect_serials(fleet, deadline=deadline)
            if got:
                return got
    for start, stride, count in _AUTO_CONNECT_RANGES:
        for off in range(count):
            if deadline is not None and _t.monotonic() >= deadline:
                return list_adb_phones()
            addr = f"127.0.0.1:{start + off * stride}"
            try:
                subprocess.run(
                    [exe, "connect", addr],
                    capture_output=True,
                    text=True,
                    timeout=3,
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
            # Probe failed — do not pretend Chromium is present.
            browser_ok = False
            browser_help = browser_help or "Could not verify Chromium on phones — refresh checks."

    items: list[dict] = [
        {
            "id": "folder",
            "title": "PharmFlow is ready",
            "help": "One PharmFlow.exe does everything — wizard, phone setup, dashboard, and watchdog.",
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
        for it in items:
            if it.get("id") == "folder":
                it["help"] = (
                    f"Missing: {exe_path.parent}\\PharmFlow.exe — download from GitHub Releases."
                )
                break
    return items


def run_check_action(action: str, log_fn: LogFn | None = None) -> dict:
    """Handle checklist button actions from the setup UI."""
    log = log_fn or (lambda _m: None)
    if action == "download_mumu":
        open_mumu_download()
        return {"ok": True, "message": "Opened MuMu download page in your browser."}
    if action == "download_cpharm":
        open_cpharm_releases()
        return {"ok": True, "message": "Opened GitHub Releases — download PharmFlow.exe into this folder."}
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
