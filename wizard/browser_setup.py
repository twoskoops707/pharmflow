"""
Ensure a DabFlow-capable browser exists on each MuMu phone (setup exe + wizard).

No Google Play required. Order:
  1. MuMu Browser / other installed handler (WebView flags from mumu_fingerprint apply)
  2. Chrome via ``pm install-existing`` or optional sideload APK
  3. Fennec/Mull via optional bundled APK

Drop ``chrome.apk``, ``ChromePublic.apk``, ``Fennec.apk``, or ``Mull.apk`` under
``bundled/`` next to the exes (e.g. ``C:\\CPharm\\bundled\\``).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from wizard_paths import cpharm_default_install_root, meipass_dir, wizard_module_dir

LogFn = Callable[[str], None]

CHROME_PKG = "com.android.chrome"
CHROMIUM_PUBLIC_PKG = "org.chromium.chrome"  # package id for official ChromePublic.apk
CHROME_MAIN = "com.android.chrome/com.google.android.apps.chrome.Main"
CHROMIUM_MAIN = "org.chromium.chrome/com.google.android.apps.chrome.Main"
CHROMIUM_PKGS = frozenset({CHROMIUM_PUBLIC_PKG, CHROME_PKG})
MUMU_BROWSER_PKG = "com.mumudroid.browser"
FENNEC_PKG = "org.mozilla.fennec_fdroid"
MULL_PKG = "us.spotco.fennec_dos"

# Stock AOSP Browser on MuMu: no CDP, Mantis patch cannot run, often empty ad slots.
AOSP_STOCK_BROWSER = "com.android.browser"
DABFLOW_CAPABLE_PKGS = (
    MUMU_BROWSER_PKG,
    CHROMIUM_PUBLIC_PKG,
    CHROME_PKG,
    FENNEC_PKG,
    MULL_PKG,
)

# Official Google Chromium Android snapshot (open-source; not Play Store Chrome).
CHROMIUM_SNAPSHOT_URL_TEMPLATE = "https://download-chromium.appspot.com/dl/{platform}?type=snapshots"

# Verified 2026-07: generic ``Android`` zip ships armeabi-v7a only; MuMu ARM64 needs ``Android_Arm64``.
ABI_TO_CHROMIUM_PLATFORM: dict[str, str] = {
    "arm64-v8a": "Android_Arm64",
    "armeabi-v7a": "Android",
    "armeabi": "Android",
}

_APK_NAMES: tuple[tuple[str, str], ...] = (
    ("ChromePublic.apk", CHROMIUM_PUBLIC_PKG),
    ("chrome.apk", CHROME_PKG),
    ("Fennec.apk", FENNEC_PKG),
    ("fennec_fdroid.apk", FENNEC_PKG),
    ("Mull.apk", MULL_PKG),
)

_SUBPROC_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _adb_exe() -> str:
    from adb_paths import adb_executable

    return adb_executable()


def _adb(serial: str, *args: str, timeout: float = 30) -> str:
    exe = _adb_exe()
    try:
        r = subprocess.run(
            [exe, "-s", serial, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_SUBPROC_FLAGS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (r.stdout or "") + (r.stderr or "")


def pkg_installed(serial: str, pkg: str) -> bool:
    out = _adb(serial, "shell", "pm", "path", pkg, timeout=20)
    return "package:" in (out or "")


def bundled_dir() -> Path:
    d = cpharm_default_install_root() / "bundled"
    d.mkdir(parents=True, exist_ok=True)
    return d


def device_primary_abi(serial: str) -> str:
    """``adb shell getprop ro.product.cpu.abi`` — e.g. arm64-v8a on MuMu ARM64."""
    out = _adb(serial, "shell", "getprop", "ro.product.cpu.abi", timeout=12)
    for line in reversed((out or "").splitlines()):
        line = line.strip()
        if line and "error" not in line.lower():
            return line
    return ""


def default_chromium_abi(*, serial: str | None = None) -> str:
    if serial:
        abi = device_primary_abi(serial)
        if abi:
            return abi
    if sys.platform == "win32":
        import platform

        mach = platform.machine().lower()
        if "arm" in mach or "aarch64" in mach:
            return "arm64-v8a"
    return "arm64-v8a"


def chromium_apk_filename(abi: str) -> str:
    safe = (abi or "unknown").replace("/", "-")
    return f"ChromePublic-{safe}.apk"


def chromium_platform_for_abi(abi: str) -> str | None:
    if abi in ABI_TO_CHROMIUM_PLATFORM:
        return ABI_TO_CHROMIUM_PLATFORM[abi]
    if "arm64" in abi:
        return "Android_Arm64"
    if "arm" in abi:
        return "Android"
    return None


def apk_native_abis(apk: Path) -> set[str]:
    abis: set[str] = set()
    try:
        with zipfile.ZipFile(apk, "r") as zf:
            for name in zf.namelist():
                if name.startswith("lib/") and name.count("/") >= 2:
                    abis.add(name.split("/")[1])
    except (OSError, zipfile.BadZipFile):
        pass
    return abis


def apk_matches_abi(apk: Path, abi: str) -> bool:
    native = apk_native_abis(apk)
    if not native:
        return True
    if not abi:
        return True
    if abi in native:
        return True
    if abi == "arm64-v8a" and "arm64-v8a" in native:
        return True
    if abi in ("armeabi-v7a", "armeabi") and "armeabi-v7a" in native:
        return True
    return False


def is_abi_mismatch_error(output: str) -> bool:
    low = (output or "").lower()
    return (
        "no matching abis" in low
        or "no_matching_abis" in low
        or "failed to extract native libraries" in low
    )


def download_official_chromium_apk(
    log: LogFn | None = None,
    *,
    abi: str | None = None,
    serial: str | None = None,
) -> Path | None:
    """
    Fetch ChromePublic.apk from Google's official Chromium snapshot bucket (~230 MB zip).

    MuMu ARM64 phones need ``Android_Arm64`` (``arm64-v8a``). The generic ``Android``
    build is **armeabi-v7a only** and fails with INSTALL_FAILED_NO_MATCHING_ABIS.

    Saves to ``bundled/ChromePublic-<abi>.apk``. Skip when file exists unless
    ``CPHARM_FORCE_APK_DOWNLOAD=1``.
    """
    log = log or (lambda _m: None)
    if os.environ.get("CPHARM_SKIP_APK_DOWNLOAD", "").strip().lower() in ("1", "true", "yes"):
        return find_sideload_apk(serial=serial)[0] if find_sideload_apk(serial=serial) else None

    abi = abi or default_chromium_abi(serial=serial)
    platform = chromium_platform_for_abi(abi)
    if not platform:
        log(
            f"  No Chromium snapshot for device ABI {abi!r}. "
            "Use MuMu Browser (built in) on this phone."
        )
        return None

    dest = bundled_dir() / chromium_apk_filename(abi)
    if dest.is_file() and os.environ.get("CPHARM_FORCE_APK_DOWNLOAD", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        if apk_matches_abi(dest, abi):
            return dest

    legacy = bundled_dir() / "ChromePublic.apk"
    if (
        legacy.is_file()
        and apk_matches_abi(legacy, abi)
        and os.environ.get("CPHARM_FORCE_APK_DOWNLOAD", "").strip().lower()
        not in ("1", "true", "yes")
    ):
        return legacy

    # APKs built into PharmFlow.exe install offline — use them first.
    embedded = find_sideload_apk(serial=serial)
    if embedded:
        e_apk, _ = embedded
        if apk_matches_abi(e_apk, abi):
            log(f"  Using built-in browser APK: {e_apk.name}")
            return e_apk

    url = CHROMIUM_SNAPSHOT_URL_TEMPLATE.format(platform=platform)
    tmp_zip = bundled_dir() / f"_chromium_android_{platform}.zip"
    log(f"Downloading Chromium for Android ({abi}, {platform}) — one time…")
    try:
        urllib.request.urlretrieve(url, tmp_zip)
        with zipfile.ZipFile(tmp_zip, "r") as zf:
            member = next(
                (n for n in zf.namelist() if n.endswith("ChromePublic.apk")),
                None,
            )
            if not member:
                log("  Download failed: ChromePublic.apk not in zip.")
                tmp_zip.unlink(missing_ok=True)
                return None
            dest.write_bytes(zf.read(member))
        tmp_zip.unlink(missing_ok=True)
        native = apk_native_abis(dest)
        log(f"  Saved {dest.name} ({dest.stat().st_size // (1024 * 1024)} MB, libs: {', '.join(sorted(native)) or '?'})")
        return dest
    except (OSError, urllib.error.URLError, zipfile.BadZipFile) as exc:
        log(f"  Chromium download failed: {exc}")
        tmp_zip.unlink(missing_ok=True)
        return None


def bundled_search_dirs() -> list[Path]:
    dirs: list[Path] = []
    for base in (cpharm_default_install_root(), wizard_module_dir()):
        dirs.append(base / "bundled")
        dirs.append(base / "apks")
        dirs.append(base / "bundled" / "apks")
    m = meipass_dir()
    if m is not None:
        dirs.extend([m / "bundled", m / "wizard" / "bundled"])
        dirs.append(m / "bundled" / "apks")
    seen: set[str] = set()
    out: list[Path] = []
    for d in dirs:
        key = str(d).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def find_sideload_apk(serial: str | None = None) -> tuple[Path, str] | None:
    preferred_abi = default_chromium_abi(serial=serial) if serial else None
    if preferred_abi:
        named = bundled_dir() / chromium_apk_filename(preferred_abi)
        if named.is_file() and apk_matches_abi(named, preferred_abi):
            return named, CHROMIUM_PUBLIC_PKG
    for folder in bundled_search_dirs():
        if not folder.is_dir():
            continue
        for fname, expect_pkg in _APK_NAMES:
            p = folder / fname
            if p.is_file():
                if preferred_abi and not apk_matches_abi(p, preferred_abi):
                    continue
                return p, expect_pkg
        for p in sorted(folder.glob("ChromePublic-*.apk")):
            if preferred_abi and not apk_matches_abi(p, preferred_abi):
                continue
            return p, CHROMIUM_PUBLIC_PKG
        for p in sorted(folder.glob("*.apk")):
            low = p.name.lower()
            if preferred_abi and not apk_matches_abi(p, preferred_abi):
                continue
            if "chrome" in low or "chromium" in low:
                return p, CHROMIUM_PUBLIC_PKG
            if "fennec" in low:
                return p, FENNEC_PKG
            if "mull" in low:
                return p, MULL_PKG
    return None


def install_apk(serial: str, apk: Path, log: LogFn | None = None) -> tuple[bool, str]:
    if log:
        log(f"    adb install -r {apk.name} on {serial}…")
    exe = _adb_exe()
    try:
        r = subprocess.run(
            [exe, "-s", serial, "install", "-r", str(apk.resolve())],
            capture_output=True,
            text=True,
            timeout=600,
            creationflags=_SUBPROC_FLAGS,
        )
    except subprocess.TimeoutExpired:
        if log:
            log("    -> timed out after 10 minutes")
        return False, "timed out"
    out = (r.stdout or "") + (r.stderr or "")
    if log and out.strip():
        log(f"    -> {out.strip()[:400]}")
    if r.returncode == 0:
        return True, out
    low = out.lower()
    ok = "success" in low and "failure [" not in low
    return ok, out


LAWNCHAIR_PKGS = (
    "app.lawnchair",
    "ch.deletescape.lawnchair",
    "com.google.android.apps.nexuslauncher",
)


def remove_lawnchair(serial: str, log: LogFn | None = None) -> list[str]:
    """Delete the Lawnchair launcher apps (and its variants) from a phone.

    Best effort: force-stops, then uninstalls per-user so system copies can be
    restored later if ever needed. Returns the list of packages removed.
    """
    log = log or (lambda _m: None)
    exe = _adb_exe()
    removed: list[str] = []
    for pkg in LAWNCHAIR_PKGS:
        try:
            chk = subprocess.run(
                [exe, "-s", serial, "shell", "pm", "list", "packages", pkg],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=_SUBPROC_FLAGS,
            )
        except subprocess.TimeoutExpired:
            continue
        if pkg not in ((chk.stdout or "") + (chk.stderr or "")):
            continue  # not present — nothing to delete
        log(f"    Removing Lawnchair ({pkg}) on {serial}…")
        try:
            subprocess.run(
                [exe, "-s", serial, "shell", "am", "force-stop", pkg],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=_SUBPROC_FLAGS,
            )
        except subprocess.TimeoutExpired:
            pass
        for args in (("pm", "uninstall", "--user", "0", pkg), ("pm", "uninstall", pkg)):
            try:
                r = subprocess.run(
                    [exe, "-s", serial, "shell", *args],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    creationflags=_SUBPROC_FLAGS,
                )
            except subprocess.TimeoutExpired:
                continue
            if "Success" in ((r.stdout or "") + (r.stderr or "")):
                removed.append(pkg)
                log(f"    -> {pkg} deleted ✓")
                break
        else:
            log(f"    -> {pkg} could not be uninstalled (system app?)")
    return removed


def resolve_chromium_apk(serial: str, log: LogFn | None = None) -> Path | None:
    """Pick or download the ChromePublic.apk matching ``serial`` device ABI."""
    log = log or (lambda _m: None)
    abi = device_primary_abi(serial) or default_chromium_abi(serial=serial)
    if abi:
        log(f"    Phone CPU ABI: {abi}")
    sideload = find_sideload_apk(serial=serial)
    if sideload:
        return sideload[0]
    return download_official_chromium_apk(log, abi=abi, serial=serial)


def install_chromium_apk(
    serial: str,
    apk: Path,
    log: LogFn | None = None,
) -> tuple[bool, str | None, str]:
    """
    Sideload ``ChromePublic.apk`` on ``serial``.

    Unlike ``ensure_browser``, this always runs ``adb install`` — it does not
    stop early when MuMu Browser is already present.
    """
    log = log or (lambda _m: None)
    if pkg_installed(serial, CHROMIUM_PUBLIC_PKG):
        log(f"    Chromium ({CHROMIUM_PUBLIC_PKG}) already installed")
        return True, CHROMIUM_PUBLIC_PKG, "Chromium already installed"
    if not apk.is_file():
        return False, None, f"APK missing: {apk}"
    ok, out = install_apk(serial, apk, log)
    if not ok and is_abi_mismatch_error(out):
        abi = device_primary_abi(serial) or "arm64-v8a"
        log(
            f"    APK CPU mismatch (need {abi}) — deleting wrong build and re-downloading…"
        )
        try:
            apk.unlink(missing_ok=True)
        except OSError:
            pass
        legacy = bundled_dir() / "ChromePublic.apk"
        try:
            legacy.unlink(missing_ok=True)
        except OSError:
            pass
        fresh = download_official_chromium_apk(log, abi=abi, serial=serial)
        if fresh and fresh.is_file():
            ok, out = install_apk(serial, fresh, log)
            apk = fresh
    if not ok:
        abi = device_primary_abi(serial) or "?"
        hint = (
            f"adb install failed — APK ABI must match phone ({abi}). "
            "MuMu ARM64 needs arm64 Chromium; delete bundled\\ChromePublic*.apk and retry, "
            "or use MuMu Browser (built in)."
        )
        return False, None, hint
    for pkg in (CHROMIUM_PUBLIC_PKG, CHROME_PKG):
        if pkg_installed(serial, pkg):
            return True, pkg, f"Installed {apk.name} ({browser_label(pkg)})"
    return (
        False,
        None,
        "adb reported success but Chromium package not found — cold-boot the phone and retry",
    )


def _try_install_existing(serial: str, pkg: str, log: LogFn | None = None) -> bool:
    if pkg_installed(serial, pkg):
        return True
    _adb(serial, "shell", "pm", "enable", pkg, timeout=15)
    if pkg_installed(serial, pkg):
        return True
    for args in (
        ("shell", "cmd", "package", "install-existing", pkg),
        ("shell", "cmd", "package", "install-existing", "--user", "0", pkg),
        ("shell", "pm", "install-existing", pkg),
        ("shell", "pm", "install-existing", "--user", "0", pkg),
    ):
        out = _adb(serial, *args, timeout=120)
        if log and out.strip():
            log(f"    {' '.join(args[1:])} -> {out.strip()[:120]}")
        if pkg_installed(serial, pkg):
            return True
    return False


def dabflow_ad_browser_installed(serial: str) -> bool:
    """True when Chromium/Chrome is installed (CDP + Mantis on-site ads)."""
    return pkg_installed(serial, CHROMIUM_PUBLIC_PKG) or pkg_installed(serial, CHROME_PKG)


def pick_browser_pkg(serial: str, *, dabflow: bool = False) -> str | None:
    try:
        from browser_adb import (
            packages_for_dabflow_view_url_attempts,
            packages_for_view_url_attempts,
        )

        if dabflow:
            pkgs = packages_for_dabflow_view_url_attempts(serial)
        else:
            pkgs = packages_for_view_url_attempts(serial)
        if pkgs:
            return pkgs[0]
    except Exception:
        pass
    if dabflow:
        for pkg in (CHROMIUM_PUBLIC_PKG, CHROME_PKG):
            if pkg_installed(serial, pkg):
                return pkg
        return None
    for pkg in (MUMU_BROWSER_PKG, CHROMIUM_PUBLIC_PKG, CHROME_PKG, FENNEC_PKG, MULL_PKG):
        if pkg_installed(serial, pkg):
            return pkg
    return None


def browser_label(pkg: str) -> str:
    labels = {
        MUMU_BROWSER_PKG: "MuMu Browser",
        CHROME_PKG: "Chrome",
        CHROMIUM_PUBLIC_PKG: "Chromium",
        FENNEC_PKG: "Fennec",
        MULL_PKG: "Mull",
    }
    return labels.get(pkg, pkg)


def is_dabflow_ad_browser(pkg: str | None) -> bool:
    """Browsers that support CDP injection for getdabflow.app Mantis ad slots."""
    if not pkg:
        return False
    if pkg in (CHROMIUM_PUBLIC_PKG, CHROME_PKG):
        return True
    low = (pkg or "").strip().lower()
    return low.startswith("com.android.chrome") or low.startswith("org.chromium.chrome")


def is_dabflow_capable_browser(pkg: str | None) -> bool:
    """Any browser that can open getdabflow (MuMu Browser included)."""
    if not pkg:
        return False
    if is_dabflow_ad_browser(pkg):
        return True
    if pkg in DABFLOW_CAPABLE_PKGS:
        return True
    if pkg == AOSP_STOCK_BROWSER:
        return False
    low = pkg.lower()
    return "mumu" in low or "nemu" in low


def ensure_browser(
    serial: str,
    log: LogFn | None = None,
    *,
    dabflow: bool = False,
) -> tuple[bool, str | None, str]:
    """
    Return ``(ok, package_id, message)``.

    MuMu Browser is preferred when present — it honors WebView command-line flags
    written by ``mumu_fingerprint`` and routes through Android ``http_proxy`` better
    than Chrome on many emulator images.

    When ``dabflow=True``, requires Chromium/Chrome (CDP) for on-site Mantis ads —
    MuMu Browser alone is not enough.
    """
    log = log or (lambda _m: None)

    if dabflow:
        if pkg_installed(serial, CHROMIUM_PUBLIC_PKG):
            return True, CHROMIUM_PUBLIC_PKG, "Using Chromium"
        if pkg_installed(serial, CHROME_PKG):
            return True, CHROME_PKG, "Using Chrome"
        log(f"  Installing Chromium on {serial} (getdabflow.app ads need it)…")
    else:
        existing = pick_browser_pkg(serial)
        # Stock AOSP Browser has no CDP / empty ad slots — never treat as ready.
        if existing and existing != AOSP_STOCK_BROWSER and is_dabflow_capable_browser(existing):
            return True, existing, f"Using {browser_label(existing)}"

    if dabflow or pick_browser_pkg(serial) in (None, AOSP_STOCK_BROWSER):
        log(
            f"  Stock/MuMu-only browser cannot run DabFlow Mantis ads — "
            "installing Chromium…"
        )

    log(f"  No Chromium yet on {serial} — trying Chrome install-existing…")
    if _try_install_existing(serial, CHROME_PKG, log):
        return True, CHROME_PKG, "Chrome recovered via install-existing"

    sideload = find_sideload_apk(serial=serial)
    if not sideload:
        downloaded = download_official_chromium_apk(log, serial=serial)
        if downloaded:
            sideload = (downloaded, CHROMIUM_PUBLIC_PKG)
    if sideload:
        apk, expect = sideload
        ok, _out = install_apk(serial, apk, log)
        if ok:
            for pkg in (expect, CHROMIUM_PUBLIC_PKG, CHROME_PKG):
                if pkg_installed(serial, pkg):
                    return True, pkg, f"Installed {apk.name}"

    log(
        "  Still no browser. MuMu Browser (built in) is best — open it once on the phone.\n"
        "  Or put ChromePublic.apk in bundled\\ (setup can auto-download on GO)."
    )
    return False, None, "No browser — use MuMu Browser or bundled\\ChromePublic.apk"


def chromium_reset_enabled() -> bool:
    return os.environ.get("CPHARM_SKIP_CHROMIUM_RESET", "").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    )


def reset_chromium_session(serial: str, log: LogFn | None = None) -> bool:
    """
    Wipe Chromium tabs, history, cache, and cookies (``pm clear``) before each open.

    Re-applies ``chrome-command-line`` flags after clear. Skip with ``CPHARM_SKIP_CHROMIUM_RESET=1``.
    """
    log = log or (lambda _m: None)
    if not chromium_reset_enabled():
        return False
    clear_pkg = None
    if pkg_installed(serial, CHROMIUM_PUBLIC_PKG):
        clear_pkg = CHROMIUM_PUBLIC_PKG
    elif pkg_installed(serial, CHROME_PKG):
        clear_pkg = CHROME_PKG
    if not clear_pkg:
        return False
    log(f"    {browser_label(clear_pkg)}: clear all tabs, history, cache, cookies…")
    _adb(serial, "shell", "am", "force-stop", clear_pkg, timeout=12)
    time.sleep(0.35)
    out = _adb(serial, "shell", "pm", "clear", clear_pkg, timeout=45)
    ok = "success" in (out or "").lower()
    if not ok and (out or "").strip():
        log(f"    {browser_label(clear_pkg)} pm clear: {(out or '').strip()[:120]}")
    try:
        from wizard_paths import automation_on_sys_path

        automation_on_sys_path()
        from browser_adb import invalidate_webview_inset_cache

        import mumu_fingerprint as mf

        mf.ensure_fingerprint_before_browse(serial, log_fn=log)
        invalidate_webview_inset_cache(serial)
    except Exception as exc:
        log(f"    Chromium flags refresh warning: {exc}")
    time.sleep(0.35)
    return ok


def dismiss_chromium_first_run(serial: str, log: LogFn | None = None) -> bool:
    """Dismiss Chromium FRE (Stay signed out / Skip ahead) via uiautomator."""
    log = log or (lambda _m: None)
    try:
        from wizard_paths import automation_on_sys_path

        automation_on_sys_path()
        import chromium_fre_uia as fre

        return fre.dismiss_chromium_fre_after_open(serial, log_fn=log)
    except Exception as exc:
        log(f"    Chromium FRE dismiss warning: {exc}")
        return False


def warm_browser(serial: str, pkg: str, log: LogFn | None = None) -> bool:
    """Launch once so WebView/Chrome picks up ``chrome-command-line`` flags."""
    log = log or (lambda _m: None)
    if not pkg:
        return False
    _adb(serial, "shell", "am", "force-stop", pkg, timeout=12)
    time.sleep(0.5)
    if pkg == CHROMIUM_PUBLIC_PKG:
        component = CHROMIUM_MAIN
    elif pkg == CHROME_PKG:
        component = CHROME_MAIN
    else:
        component = None
    if component:
        out = _adb(
            serial,
            "shell",
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            "about:blank",
            "-n",
            component,
            "--ez",
            "create_new_tab",
            "true",
            timeout=20,
        )
    else:
        out = _adb(
            serial,
            "shell",
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            "https://getdabflow.app",
            "-p",
            pkg,
            timeout=20,
        )
    ok = "Error" not in (out or "")
    if log:
        log(f"    Opened {browser_label(pkg)} — flags apply on this launch.")
    settle = 3.0 if pkg in CHROMIUM_PKGS else 2.0
    time.sleep(settle)
    if pkg in CHROMIUM_PKGS:
        dismiss_chromium_first_run(serial, log)
    _adb(serial, "shell", "am", "force-stop", pkg, timeout=12)
    return ok


def prepare_for_dabflow_open(serial: str, url: str, log: LogFn | None = None) -> dict:
    """Install CDP-capable browser + write fingerprint flags before getdabflow ``open_url``."""
    if "getdabflow.app" not in (url or "").lower():
        return {"skipped": True}
    log = log or (lambda m: print(f"[cpharm] {m}", flush=True))
    result: dict = {"serial": serial}

    try:
        from wizard_paths import automation_on_sys_path

        automation_on_sys_path()
        import emulator_ad_mode as eam
        import tor_manager as tm

        idx = tm.phone_idx_from_adb_serial(serial)
        result["emulator_ad_pause"] = eam.pause_tor_for_ads(serial, idx, log_fn=log)
    except Exception as exc:
        result["emulator_ad_pause_error"] = str(exc)

    ok, pkg, msg = ensure_browser(serial, log, dabflow=True)
    result.update({"browser_ok": ok, "browser_pkg": pkg, "browser_msg": msg})
    if not ok:
        log(f"DabFlow browser setup FAILED on {serial}: {msg}")
        return result

    try:
        from wizard_paths import automation_on_sys_path

        automation_on_sys_path()
        import mumu_fingerprint as mf

        fp = mf.ensure_fingerprint_before_browse(serial, log_fn=log)
        result["fingerprint"] = fp
        if pkg and is_dabflow_ad_browser(pkg):
            try:
                import browse_proxy as bp

                if not bp.dabflow_browse_active(serial):
                    warm_browser(serial, pkg, log)
            except Exception:
                warm_browser(serial, pkg, log)
    except Exception as exc:
        result["fingerprint_error"] = str(exc)
        log(f"DabFlow fingerprint setup warning: {exc}")

    return result


def configure_phone_baseline(serial: str, log: LogFn | None = None) -> None:
    """Clear stale proxy and set 900×1600 — matches sequence tap coordinates."""
    log = log or (lambda _m: None)
    proxy_keys = (
        "http_proxy",
        "global_http_proxy_host",
        "global_http_proxy_port",
        "global_http_proxy_exclusion_list",
        "global_proxy_pac_url",
    )
    try:
        from wizard_paths import automation_on_sys_path

        automation_on_sys_path()
        import tor_manager as tm

        tm.clear_all_proxies_on_devices([serial])
        tm.kick_default_browser_after_proxy_teardown([serial])
    except Exception:
        for key in proxy_keys:
            _adb(serial, "shell", "settings", "delete", "global", key, timeout=12)
        _adb(serial, "shell", "settings", "put", "global", "http_proxy", ":0", timeout=12)
    _adb(serial, "shell", "wm", "size", "900x1600", timeout=10)
    _adb(serial, "shell", "wm", "density", "reset", timeout=8)
    size = _adb(serial, "shell", "wm", "size", timeout=8).strip()
    proxy_after = _adb(serial, "shell", "settings", "get", "global", "http_proxy", timeout=8).strip()
    if log and size:
        log(f"    Screen: {size.splitlines()[-1] if size else size}")
    if log and proxy_after and proxy_after not in ("null", ":0", ""):
        log(f"    WARNING: proxy still set ({proxy_after}) — browser may fail until cleared")


# --- FamFlow generation appendix (merged) ---
import logging
import re
import shutil
import tarfile
import tempfile
import json
from typing import Any
from urllib.request import urlopen
from automation.adb_wrapper import AdbWrapper
from automation.browser_adb import is_chromium_available
from automation.config import BROWSER_CHROMIUM, CHROMIUM_DOWNLOAD_URL
from wizard.wizard_paths import chrome_apk_path
# Keep module-level bundled_dir() (install-root) — do not shadow with wizard_paths.bundled_dir.
logger = logging.getLogger(__name__)
CHROMIUM_SNAPSHOT_URL = (
    "https://www.googleapis.com/storage/v1/b/chromium-browser-snapshots/o"
    "?prefix=Android_ARM64%2F&delimiter=%2F"
)
TOR_FALLBACK_URL = (
    "https://dist.torproject.org/torbrowser/14.0.9/tor-expert-bundle-windows-x86_64-14.0.9.tar.gz"
)

def _local_chromium_candidates() -> list[Path]:
    """Known on-disk Chromium APK locations (including prior installs)."""
    root = chrome_apk_path().parent
    app_root = root.parent
    return [
        chrome_apk_path(),
        root / "ChromePublic-arm64-v8a.apk",
        root / "chrome.apk",
        app_root / "OLD" / "bundled" / "ChromePublic.apk",
        app_root / "OLD" / "bundled" / "ChromePublic-arm64-v8a.apk",
    ]


def _reuse_local_chromium_apk(dest: Path) -> Path | None:
    """Copy a usable local Chromium APK into the canonical bundled path."""
    for candidate in _local_chromium_candidates():
        try:
            if not candidate.is_file() or candidate.stat().st_size < 1_000_000:
                continue
            if candidate.resolve() == dest.resolve():
                return dest
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(candidate.read_bytes())
            logger.info("Reused local Chromium APK from %s → %s", candidate, dest)
            return dest
        except OSError as exc:
            logger.warning("Could not reuse %s: %s", candidate, exc)
    return None


def download_chrome_public_apk(dest: Path | None = None, progress_cb: Any = None) -> Path | None:
    """Download ChromePublic.apk (~230 MB) to C:\\CPharm\\bundled."""
    apk = dest or chrome_apk_path()
    if apk.is_file() and apk.stat().st_size > 1_000_000:
        logger.info("Using cached ChromePublic.apk: %s", apk)
        return apk

    reused = _reuse_local_chromium_apk(apk)
    if reused is not None:
        return reused

    apk.parent.mkdir(parents=True, exist_ok=True)
    if progress_cb:
        progress_cb("Downloading Chromium browser...")

    # Primary: download-chromium.appspot.com ARM64 APK
    try:
        logger.info("Downloading from %s", CHROMIUM_DOWNLOAD_URL)
        with urlopen(CHROMIUM_DOWNLOAD_URL, timeout=300) as resp:
            data = resp.read()
        apk.write_bytes(data)
        if apk.stat().st_size > 1_000_000:
            return apk
    except Exception as exc:
        logger.warning("Primary Chromium download failed: %s", exc)

    # Fallback: Chromium snapshots
    snap = download_chromium_snapshot_apk(apk, progress_cb)
    if snap is not None:
        return snap

    # Last resort: local OLD/bundled copies again (in case download wiped nothing)
    return _reuse_local_chromium_apk(apk)


def download_chromium_snapshot_apk(dest: Path, progress_cb: Any = None) -> Path | None:
    try:
        with urlopen(CHROMIUM_SNAPSHOT_URL, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        prefixes = payload.get("prefixes") or []
        revisions: list[int] = []
        for prefix in prefixes:
            m = re.search(r"Android_ARM64/(\d+)/", str(prefix))
            if m:
                revisions.append(int(m.group(1)))
        if not revisions:
            return None
        rev = max(revisions)
        zip_url = (
            f"https://commondatastorage.googleapis.com/chromium-browser-snapshots/"
            f"Android_ARM64/{rev}/chrome-android.zip"
        )
        if progress_cb:
            progress_cb("Downloading Chromium (snapshot)...")
        zip_path = dest.parent / f"chrome_{rev}.zip"
        with urlopen(zip_url, timeout=300) as resp:
            zip_path.write_bytes(resp.read())
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                if name.endswith(".apk"):
                    zf.extract(name, dest.parent)
                    extracted = dest.parent / name
                    extracted.rename(dest)
                    break
        zip_path.unlink(missing_ok=True)
        return dest if dest.is_file() else None
    except Exception as exc:
        logger.error("Snapshot download failed: %s", exc)
        return None


def _platform_tools_download_url() -> str:
    base = "https://dl.google.com/android/repository"
    if sys.platform == "win32":
        return f"{base}/platform-tools-latest-windows.zip"
    if sys.platform == "darwin":
        return f"{base}/platform-tools-latest-darwin.zip"
    return f"{base}/platform-tools-latest-linux.zip"


def _adb_binary_name() -> str:
    return "adb.exe" if sys.platform == "win32" else "adb"


def _copy_platform_tools_to_bundled(pt_dir: Path, dest: Path) -> None:
    """Copy adb (and Windows USB helpers) into the bundled tools root."""
    names = ["adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"] if sys.platform == "win32" else ["adb"]
    for name in names:
        src = pt_dir / name
        if src.is_file():
            shutil.copy2(src, dest / name)


def download_platform_tools_adb(dest_dir: Path | None = None) -> Path | None:
    """Download Google's platform-tools and place adb in the bundled dir."""
    dest = dest_dir or bundled_dir()
    dest.mkdir(parents=True, exist_ok=True)
    adb_name = _adb_binary_name()
    adb = dest / adb_name
    if adb.is_file():
        return adb

    nested = dest / "platform-tools" / adb_name
    if nested.is_file():
        _copy_platform_tools_to_bundled(nested.parent, dest)
        if adb.is_file():
            return adb

    url = _platform_tools_download_url()
    tmp = dest / "_platform_tools.zip"
    try:
        logger.info("Downloading platform-tools from %s", url)
        with urlopen(url, timeout=120) as resp:
            tmp.write_bytes(resp.read())
        with zipfile.ZipFile(tmp, "r") as zf:
            zf.extractall(dest)
        tmp.unlink(missing_ok=True)
    except Exception as exc:
        logger.error("platform-tools download failed: %s", exc)
        tmp.unlink(missing_ok=True)
        logger.warning("%s not present — place platform-tools in %s", adb_name, dest)
        return None

    extracted = dest / "platform-tools" / adb_name
    if extracted.is_file():
        _copy_platform_tools_to_bundled(extracted.parent, dest)
    return adb if adb.is_file() else None


def _fetch_latest_tor_url() -> str:
    """Resolve the newest Windows x64 Tor expert bundle URL."""
    if sys.platform != "win32":
        return TOR_FALLBACK_URL
    try:
        with urlopen("https://dist.torproject.org/torbrowser/", timeout=12) as resp:
            content = resp.read().decode("utf-8", errors="replace")
        versions = re.findall(r'href="(\d+\.\d+\.\d+)/"', content)
        if versions:
            latest = sorted(versions, key=lambda v: tuple(int(x) for x in v.split(".")))[-1]
            return (
                f"https://dist.torproject.org/torbrowser/{latest}/"
                f"tor-expert-bundle-windows-x86_64-{latest}.tar.gz"
            )
    except Exception as exc:
        logger.warning("Could not resolve latest Tor version: %s", exc)
    return TOR_FALLBACK_URL


def _merge_tor_extract(src_dir: Path, dest: Path) -> None:
    """Copy extracted Tor expert bundle files into the bundled directory."""
    for path in src_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(src_dir)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def download_tor_expert_bundle(dest_dir: Path | None = None, progress_cb: Any = None) -> Path | None:
    """Download Tor expert bundle and place tor.exe under the bundled dir."""
    if sys.platform != "win32":
        logger.warning("Tor auto-download is only implemented for Windows")
        return None

    dest = dest_dir or bundled_dir()
    dest.mkdir(parents=True, exist_ok=True)
    tor_exe = dest / "tor.exe"
    if tor_exe.is_file():
        return tor_exe

    url = _fetch_latest_tor_url()
    if progress_cb:
        progress_cb("Downloading Tor expert bundle...")
    logger.info("Downloading Tor from %s", url)

    tmp_path: Path | None = None
    extract_root: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        with urlopen(url, timeout=180) as resp:
            tmp_path.write_bytes(resp.read())

        if progress_cb:
            progress_cb("Extracting Tor...")
        extract_root = Path(tempfile.mkdtemp(prefix="cpharm_tor_"))
        with tarfile.open(tmp_path, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.name.startswith("tor/"):
                    continue
                member.name = member.name[len("tor/") :]
                if not member.name:
                    continue
                archive.extract(member, extract_root)

        inner = extract_root
        if inner.is_dir():
            _merge_tor_extract(inner, dest)
    except Exception as exc:
        logger.error("Tor download failed: %s", exc)
        return None
    finally:
        if tmp_path and tmp_path.is_file():
            tmp_path.unlink(missing_ok=True)
        if extract_root and extract_root.is_dir():
            shutil.rmtree(extract_root, ignore_errors=True)

    return tor_exe if tor_exe.is_file() else None


def sideload_chromium(adb: AdbWrapper, serial: str, apk_path: Path | None = None) -> bool:
    apk = apk_path or chrome_apk_path()
    if not apk.is_file():
        apk = download_chrome_public_apk()
    if not apk or not apk.is_file():
        return False
    result = adb.install(str(apk), serial=serial)
    if result.ok:
        logger.info("Chromium installed on %s", serial)
    else:
        logger.error("Chromium install failed: %s", result.stderr)
    return result.ok


def ensure_browser_via_adb(adb: AdbWrapper, serial: str, prefer_mumu: bool = False) -> dict[str, Any]:
    """Ensure Chromium is installed (download + sideload). MuMu Browser is not required."""
    _ = prefer_mumu  # legacy kwarg — ignored; Chromium is the setup browser
    if is_chromium_available(adb, serial):
        packages = set(adb.pm_list_packages(serial=serial))
        pkg = BROWSER_CHROMIUM if BROWSER_CHROMIUM in packages else "com.android.chrome"
        return {"installed": True, "browser": "Chromium", "package": pkg}

    ok = sideload_chromium(adb, serial)
    if ok and is_chromium_available(adb, serial):
        return {"installed": True, "browser": "Chromium", "package": BROWSER_CHROMIUM}

    return {
        "installed": False,
        "browser": None,
        "package": BROWSER_CHROMIUM,
        "error": "Chromium not installed — run Install browser / place ChromePublic.apk in C:\\CPharm\\bundled",
    }


def ensure_farm_browsers(
    adb: AdbWrapper,
    serials: list[str],
    *,
    progress_cb: Any = None,
    force_download: bool = False,
) -> dict[str, Any]:
    """Download + sideload Chromium/Firefox/Brave/DuckDuckGo for Path1/2 (no Play Store).

    Used by CPharm.exe setup and scripts/sideload_farm_browsers.py. Path3 still
    requires Chromium; this function installs all Path1/2 packages.
    """
    from automation.browser_apk_catalog import ensure_farm_browsers_on_serials

    # Keep legacy Chromium path populated for older helpers / docs.
    try:
        download_chrome_public_apk(progress_cb=progress_cb)
    except Exception as exc:
        logger.warning("Legacy ChromePublic.apk download soft-fail: %s", exc)

    return ensure_farm_browsers_on_serials(
        adb,
        list(serials),
        force_download=force_download,
        progress_cb=progress_cb,
    )

