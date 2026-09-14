"""Farm browser APK catalog — public sideload sources (no Google Play / no credentials).

Path1/2 rotate Chromium + Firefox + Brave + DuckDuckGo + Opera. Path3 stays Chromium for Mantis CDP.

APKs are downloaded from public vendor mirrors (Mozilla FTP, Brave/DuckDuckGo GitHub Releases,
Opera get.geo.opera.com FTP, Chromium CI mirrors). Nothing here uses the Play Store, Google
accounts, or paid API keys.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from automation.adb_wrapper import AdbWrapper
from automation.apk_tools import install_apk_on_serials
from automation.config import (
    BROWSER_BRAVE,
    BROWSER_CHROMIUM,
    BROWSER_DUCKDUCKGO,
    BROWSER_FARMBROWSER,
    BROWSER_FIREFOX,
    BROWSER_OPERA,
    CHROMIUM_DOWNLOAD_URL,
)

logger = logging.getLogger(__name__)

ProgressCb = Callable[[str], None] | None

# Canonical on-disk names under the APK cache directory.
APK_FILENAMES: dict[str, str] = {
    BROWSER_CHROMIUM: "ChromePublic-arm64.apk",
    BROWSER_FIREFOX: "fenix-android-arm64.apk",
    BROWSER_BRAVE: "brave-android-arm64.apk",
    BROWSER_DUCKDUCKGO: "duckduckgo-android.apk",
    BROWSER_OPERA: "opera-android-arm64.apk",
    BROWSER_FARMBROWSER: "farmbrowser-debug.apk",
}

MOZILLA_FENIX_RELEASES = "https://ftp.mozilla.org/pub/fenix/releases/"
BRAVE_GITHUB_LATEST = "https://api.github.com/repos/brave/brave-browser/releases/latest"
DUCKDUCKGO_GITHUB_LATEST = "https://api.github.com/repos/duckduckgo/Android/releases/latest"
OPERA_ANDROID_FTP = "https://get.geo.opera.com/ftp/pub/opera/android/"
CHROMIUM_SNAPSHOT_LIST = (
    "https://www.googleapis.com/storage/v1/b/chromium-browser-snapshots/o"
    "?prefix=Android_ARM64%2F&delimiter=%2F"
)

_USER_AGENT = "CPharm-FarmBrowserSideload/1.0 (+https://github.com/twoskoops707/FamFlow)"


@dataclass(frozen=True)
class BrowserApkSpec:
    """One sideloadable browser APK the farm knows how to fetch + install."""

    tag: str
    package: str
    label: str
    filename: str
    path12: bool
    path3: bool
    notes: str


BROWSER_APK_SPECS: tuple[BrowserApkSpec, ...] = (
    BrowserApkSpec(
        tag="chromium",
        package=BROWSER_CHROMIUM,
        label="Chromium",
        filename=APK_FILENAMES[BROWSER_CHROMIUM],
        path12=True,
        path3=True,
        notes=(
            "Ungoogled Chromium ARM64 APK from download-chromium / snapshot mirrors. "
            "Not Play Store Chrome — no Google account required."
        ),
    ),
    BrowserApkSpec(
        tag="firefox",
        package=BROWSER_FIREFOX,
        label="Firefox",
        filename=APK_FILENAMES[BROWSER_FIREFOX],
        path12=True,
        path3=False,
        notes=(
            "Mozilla Fenix multi-locale arm64-v8a from ftp.mozilla.org (public FTP). "
            "No Mozilla account required for sideload."
        ),
    ),
    BrowserApkSpec(
        tag="brave",
        package=BROWSER_BRAVE,
        label="Brave",
        filename=APK_FILENAMES[BROWSER_BRAVE],
        path12=True,
        path3=False,
        notes=(
            "Brave release APK from GitHub Releases (public). "
            "No Brave account / Play Store login required."
        ),
    ),
    BrowserApkSpec(
        tag="duckduckgo",
        package=BROWSER_DUCKDUCKGO,
        label="DuckDuckGo",
        filename=APK_FILENAMES[BROWSER_DUCKDUCKGO],
        path12=True,
        path3=False,
        notes=(
            "DuckDuckGo Android release APK from GitHub Releases (public). "
            "No DuckDuckGo account / Play Store login required."
        ),
    ),
    BrowserApkSpec(
        tag="opera",
        package=BROWSER_OPERA,
        label="Opera",
        filename=APK_FILENAMES[BROWSER_OPERA],
        path12=True,
        path3=False,
        notes=(
            "Opera ARM64 (arm8) APK from get.geo.opera.com public FTP. "
            "Package verified via aapt: com.opera.browser. No account required."
        ),
    ),
    BrowserApkSpec(
        tag="farmbrowser",
        package=BROWSER_FARMBROWSER,
        label="FarmBrowser (stealth)",
        filename=APK_FILENAMES[BROWSER_FARMBROWSER],
        path12=True,
        path3=False,
        notes=(
            "Custom stealth money browser built from farmbrowser/ (gradle). "
            "No public download — ships built-in with the EXE."
        ),
    ),
)


def default_apk_cache_dir() -> Path:
    """Prefer C:\\CPharm\\apks, fall back to repo-relative CPharm/apks when unset."""
    env = (os.environ.get("CPHARM_APK_CACHE") or "").strip()
    if env:
        return Path(env)
    # Match live farm layout used by operators.
    cpharm = Path(r"C:\CPharm\apks")
    if cpharm.parent.is_dir() or os.name == "nt":
        return cpharm
    return Path.cwd() / "apks"


def spec_for_package(package: str) -> BrowserApkSpec | None:
    pkg = (package or "").strip()
    for spec in BROWSER_APK_SPECS:
        if spec.package == pkg:
            return spec
    return None


def spec_for_tag(tag: str) -> BrowserApkSpec | None:
    t = (tag or "").strip().lower()
    for spec in BROWSER_APK_SPECS:
        if spec.tag == t:
            return spec
    return None


def _http_get(url: str, *, timeout: float = 120.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _http_download(url: str, dest: Path, *, timeout: float = 600.0, progress_cb: ProgressCb = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if progress_cb:
        progress_cb(f"Downloading {dest.name}...")
    logger.info("Downloading %s -> %s", url, dest)
    data = _http_get(url, timeout=timeout)
    dest.write_bytes(data)
    if dest.stat().st_size < 1_000_000:
        raise RuntimeError(f"download too small ({dest.stat().st_size} bytes): {url}")
    return dest


def resolve_firefox_apk_url() -> str:
    """Pick latest stable Fenix arm64 APK on Mozilla FTP (no auth)."""
    html = _http_get(MOZILLA_FENIX_RELEASES, timeout=60).decode("utf-8", errors="replace")
    versions = re.findall(r'href="/pub/fenix/releases/([^"/]+)/"', html)
    stable = [v for v in versions if re.fullmatch(r"\d+\.\d+(\.\d+)?", v)]
    if not stable:
        raise RuntimeError("no stable Firefox versions listed on Mozilla FTP")

    def _key(v: str) -> tuple[int, ...]:
        return tuple(int(p) for p in v.split("."))

    ver = sorted(stable, key=_key)[-1]
    base = f"{MOZILLA_FENIX_RELEASES}{ver}/android/fenix-{ver}-android-arm64-v8a/"
    listing = _http_get(base, timeout=60).decode("utf-8", errors="replace")
    apks = re.findall(r'href="([^"]+\.apk)"', listing)
    if not apks:
        raise RuntimeError(f"no Firefox APK under {base}")
    href = apks[0]
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return f"https://ftp.mozilla.org{href}"
    return base + href


def resolve_brave_apk_url() -> str:
    """Pick latest Brave arm64 APK asset from GitHub Releases (no token required)."""
    raw = _http_get(BRAVE_GITHUB_LATEST, timeout=60).decode("utf-8")
    payload = json.loads(raw)
    assets = payload.get("assets") or []
    preferred: list[str] = []
    fallback: list[str] = []
    for asset in assets:
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if not url or not name.lower().endswith(".apk"):
            continue
        low = name.lower()
        if any(x in low for x in ("nightly", "beta", "dev")):
            continue
        if "arm64" in low:
            preferred.append(url)
        else:
            fallback.append(url)
    if preferred:
        return preferred[0]
    if fallback:
        return fallback[0]
    raise RuntimeError("no Brave APK asset on GitHub latest release")


def resolve_duckduckgo_apk_url() -> str:
    """Pick latest DuckDuckGo play-release APK from GitHub Releases (no token)."""
    raw = _http_get(DUCKDUCKGO_GITHUB_LATEST, timeout=60).decode("utf-8")
    payload = json.loads(raw)
    assets = payload.get("assets") or []
    preferred: list[str] = []
    fallback: list[str] = []
    for asset in assets:
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if not url or not name.lower().endswith(".apk"):
            continue
        low = name.lower()
        if "play-release" in low or "release" in low:
            preferred.append(url)
        else:
            fallback.append(url)
    if preferred:
        return preferred[0]
    if fallback:
        return fallback[0]
    raise RuntimeError("no DuckDuckGo APK asset on GitHub latest release")


def resolve_opera_apk_url() -> str:
    """Pick latest Opera Generic arm8 (ARM64) APK from Opera public FTP."""
    html = _http_get(OPERA_ANDROID_FTP, timeout=60).decode("utf-8", errors="replace")
    versions = re.findall(r'href="([0-9]+)/"', html)
    if not versions:
        raise RuntimeError("no Opera version dirs on get.geo.opera.com FTP")
    ver = sorted({int(v) for v in versions})[-1]
    base = f"{OPERA_ANDROID_FTP}{ver}/"
    listing = _http_get(base, timeout=60).decode("utf-8", errors="replace")
    # arm8 = ARM64; ignore arm7 / x86. Prefer highest build number in the folder.
    apks = re.findall(r'href="([^"]+Generic_Opera_arm8_LZMA\.apk)"', listing)
    if not apks:
        apks = re.findall(r'href="([^"]+arm8[^"]+\.apk)"', listing)
    if not apks:
        raise RuntimeError(f"no Opera arm8 APK under {base}")
    href = sorted(apks)[-1]
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return f"https://get.geo.opera.com{href}"
    return base + href


def resolve_chromium_apk_url() -> str:
    """Primary Chromium ARM64 APK URL (public appspot mirror)."""
    return CHROMIUM_DOWNLOAD_URL


def resolve_chromium_snapshot_apk_url() -> str | None:
    """Fallback: newest Android_ARM64 chrome-android.zip revision (extract APK separately)."""
    try:
        raw = _http_get(CHROMIUM_SNAPSHOT_LIST, timeout=30).decode("utf-8")
        payload = json.loads(raw)
        revisions: list[int] = []
        for prefix in payload.get("prefixes") or []:
            m = re.search(r"Android_ARM64/(\d+)/", str(prefix))
            if m:
                revisions.append(int(m.group(1)))
        if not revisions:
            return None
        rev = max(revisions)
        return (
            "https://commondatastorage.googleapis.com/chromium-browser-snapshots/"
            f"Android_ARM64/{rev}/chrome-android.zip"
        )
    except Exception as exc:
        logger.warning("Chromium snapshot list failed: %s", exc)
        return None


def apk_path_for(spec: BrowserApkSpec, cache_dir: Path | None = None) -> Path:
    return (cache_dir or default_apk_cache_dir()) / spec.filename


def _embedded_apk_dirs() -> list[Path]:
    """Directories where browser APKs are built into the EXE (offline install)."""
    dirs: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass) / "bundled" / "apks")
    root = Path(__file__).resolve().parents[1]
    dirs.append(root / "wizard" / "bundled" / "apks")
    dirs.append(root / "bundled" / "apks")
    return dirs


def find_embedded_apk(spec: BrowserApkSpec) -> Path | None:
    """Return the APK built into the EXE for this browser, if present."""
    for d in _embedded_apk_dirs():
        p = d / spec.filename
        if p.is_file() and p.stat().st_size > 1_000_000:
            return p
    return None


def _resolve_farmbrowser_apk(dest: Path) -> Path:
    """FarmBrowser is a prebuilt APK — there is no public download URL.

    Sources, in order: embedded inside the EXE, the APK cache dir, then the
    gradle build output. Never hits the network.
    """
    embedded = find_embedded_apk(spec_for_package(BROWSER_FARMBROWSER))
    if embedded is not None:
        return embedded
    if dest.is_file() and dest.stat().st_size > 100_000:
        return dest
    root = Path(__file__).resolve().parents[1]
    for rel in (
        "farmbrowser/app/build/outputs/apk/debug/app-debug.apk",
        "farmbrowser/app/build/outputs/apk/release/app-release.apk",
    ):
        p = root / rel
        if p.is_file() and p.stat().st_size > 100_000:
            return p
    raise RuntimeError(
        "FarmBrowser APK not found. Build it (farmbrowser/gradlew.bat assembleDebug) "
        "or drop farmbrowser-debug.apk into the apks folder, then retry."
    )


def download_browser_apk(
    spec: BrowserApkSpec,
    *,
    cache_dir: Path | None = None,
    force: bool = False,
    progress_cb: ProgressCb = None,
) -> Path:
    """Download one browser APK into the cache. Reuses existing file unless force=True."""
    dest = apk_path_for(spec, cache_dir)
    if not force and dest.is_file() and dest.stat().st_size > 1_000_000:
        logger.info("Using cached %s (%s bytes)", dest.name, dest.stat().st_size)
        return dest

    # APKs built into PharmFlow.exe install offline — never hit the network.
    embedded = find_embedded_apk(spec)
    if embedded is not None:
        logger.info("Using built-in APK %s", embedded)
        return embedded

    if spec.package == BROWSER_FARMBROWSER:
        return _resolve_farmbrowser_apk(dest)

    if spec.package == BROWSER_FIREFOX:
        url = resolve_firefox_apk_url()
        return _http_download(url, dest, progress_cb=progress_cb)

    if spec.package == BROWSER_BRAVE:
        url = resolve_brave_apk_url()
        return _http_download(url, dest, progress_cb=progress_cb)

    if spec.package == BROWSER_DUCKDUCKGO:
        url = resolve_duckduckgo_apk_url()
        return _http_download(url, dest, progress_cb=progress_cb)

    if spec.package == BROWSER_OPERA:
        url = resolve_opera_apk_url()
        return _http_download(url, dest, progress_cb=progress_cb)

    if spec.package == BROWSER_CHROMIUM:
        try:
            return _http_download(resolve_chromium_apk_url(), dest, progress_cb=progress_cb)
        except Exception as exc:
            logger.warning("Primary Chromium download failed: %s", exc)
        # Snapshot zip → ChromePublic.apk (appspot mirror often 500s)
        try:
            snap = resolve_chromium_snapshot_apk_url()
            if snap:
                if progress_cb:
                    progress_cb(f"Chromium snapshot fallback: {snap}")
                with tempfile.TemporaryDirectory(prefix="cpharm_chromium_") as td:
                    zpath = Path(td) / "chrome-android.zip"
                    _http_download(snap, zpath, progress_cb=progress_cb)
                    with zipfile.ZipFile(zpath, "r") as zf:
                        # Prefer ChromePublic.apk; else any *ChromePublic*.apk / chrome*.apk
                        names = zf.namelist()
                        pick = None
                        for n in names:
                            base = n.rsplit("/", 1)[-1]
                            if base == "ChromePublic.apk":
                                pick = n
                                break
                        if pick is None:
                            for n in names:
                                base = n.rsplit("/", 1)[-1].lower()
                                if base.endswith(".apk") and "chrome" in base:
                                    pick = n
                                    break
                        if not pick:
                            raise RuntimeError("no APK inside chromium snapshot zip")
                        extracted = Path(td) / "out.apk"
                        with zf.open(pick) as src, open(extracted, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(extracted, dest)
                if dest.is_file() and dest.stat().st_size > 1_000_000:
                    logger.info("Chromium snapshot APK ready at %s (%s bytes)", dest, dest.stat().st_size)
                    return dest
        except Exception as exc:
            logger.warning("Chromium snapshot fallback failed: %s", exc)
        # Legacy bundled ChromePublic.apk
        try:
            from wizard.wizard_paths import chrome_apk_path

            legacy = chrome_apk_path()
            if legacy.is_file() and legacy.stat().st_size > 1_000_000:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(legacy, dest)
                logger.info("Using legacy bundled Chromium APK -> %s", dest)
                return dest
        except Exception as exc:
            logger.warning("Legacy Chromium fallback failed: %s", exc)
        raise RuntimeError("Chromium APK unavailable (appspot + snapshot + legacy all failed)")

    raise RuntimeError(f"no download strategy for {spec.package}")


def download_all_path12_apks(
    *,
    cache_dir: Path | None = None,
    force: bool = False,
    progress_cb: ProgressCb = None,
) -> dict[str, Path]:
    """Download Chromium + Firefox + Brave APKs. Returns package → path."""
    out: dict[str, Path] = {}
    errors: list[str] = []
    for spec in BROWSER_APK_SPECS:
        if not spec.path12:
            continue
        try:
            out[spec.package] = download_browser_apk(
                spec, cache_dir=cache_dir, force=force, progress_cb=progress_cb
            )
        except Exception as exc:
            msg = f"{spec.label}: {exc}"
            errors.append(msg)
            logger.error("APK download failed — %s", msg)
    if BROWSER_CHROMIUM not in out:
        # Soft fallback: legacy bundled ChromePublic.apk used by setup wizard.
        try:
            from wizard.wizard_paths import chrome_apk_path

            legacy = chrome_apk_path()
            if legacy.is_file() and legacy.stat().st_size > 1_000_000:
                out[BROWSER_CHROMIUM] = legacy
                logger.info("Using legacy bundled Chromium APK at %s", legacy)
        except Exception:
            pass
    if not out:
        raise RuntimeError("; ".join(errors) or "no browser APKs downloaded")
    return out


def install_apks_on_serials(
    adb: AdbWrapper,
    serials: list[str],
    apk_by_package: dict[str, Path],
) -> dict[str, dict[str, bool]]:
    """Install each APK on every serial. Returns package → {serial: ok}."""
    results: dict[str, dict[str, bool]] = {}
    for package, apk in apk_by_package.items():
        results[package] = install_apk_on_serials(adb, apk, serials)
    return results


def required_path12_packages() -> list[str]:
    """Packages Path1/2 need before a phone may farm.

    Honors ``CPHARM_FARM_BROWSERS=chromium,firefox,brave,duckduckgo`` when set;
    otherwise all Path1/2 catalog packages. Chromium is always required when
    Path3 is enabled (``CPHARM_FARM_PATHS`` contains ``3``).
    """
    raw = (os.environ.get("CPHARM_FARM_BROWSERS") or "").strip().lower()
    pkgs: list[str] = []
    if raw:
        for part in raw.split(","):
            tag = part.strip()
            if not tag:
                continue
            spec = spec_for_tag(tag)
            if spec is None:
                # Allow raw package names too.
                for s in BROWSER_APK_SPECS:
                    if s.package == tag or s.tag == tag:
                        spec = s
                        break
            if spec and spec.path12 and spec.package not in pkgs:
                pkgs.append(spec.package)
    else:
        pkgs = [s.package for s in BROWSER_APK_SPECS if s.path12]
    paths = {
        p.strip()
        for p in (os.environ.get("CPHARM_FARM_PATHS") or "1,2,3").split(",")
        if p.strip()
    }
    if "3" in paths and BROWSER_CHROMIUM not in pkgs:
        pkgs.insert(0, BROWSER_CHROMIUM)
    return pkgs


def packages_on_device(adb: AdbWrapper, serial: str) -> set[str]:
    try:
        return {p.strip() for p in adb.pm_list_packages(serial=serial) if p.strip()}
    except Exception as exc:
        logger.warning("pm list packages failed on %s: %s", serial, exc)
        return set()


def missing_farm_browsers(
    adb: AdbWrapper,
    serial: str,
    *,
    required: list[str] | None = None,
) -> list[str]:
    """Return required package names not yet installed on ``serial``."""
    need = list(required) if required is not None else required_path12_packages()
    have = packages_on_device(adb, serial)
    # Stock Chrome (google_apis AVD / some emulators) satisfies Chromium Path3.
    if "com.android.chrome" in have:
        have = set(have)
        have.add(BROWSER_CHROMIUM)
    return [pkg for pkg in need if pkg not in have]


def ensure_farm_browsers_on_serials(
    adb: AdbWrapper,
    serials: list[str],
    *,
    cache_dir: Path | None = None,
    force_download: bool = False,
    progress_cb: ProgressCb = None,
) -> dict[str, Any]:
    """Download Path1/2 APKs if needed and sideload onto every serial.

    Returns a summary dict suitable for setup UI / CLI printing.
    """
    apks = download_all_path12_apks(
        cache_dir=cache_dir, force=force_download, progress_cb=progress_cb
    )
    if progress_cb:
        progress_cb(f"Installing browsers on {len(serials)} phone(s)...")
    install = install_apks_on_serials(adb, serials, apks)
    per_phone: dict[str, dict[str, bool]] = {s: {} for s in serials}
    for package, by_serial in install.items():
        for serial, ok in by_serial.items():
            per_phone.setdefault(serial, {})[package] = ok
    return {
        "apks": {pkg: str(path) for pkg, path in apks.items()},
        "install": install,
        "per_phone": per_phone,
        "ok": all(all(v.values()) for v in per_phone.values()) if per_phone else False,
        "play_store": False,
        "credentials_required": False,
        "note": (
            "Browsers sideloaded from public vendor mirrors — "
            "no Google Play Store and no account credentials."
        ),
    }


def ensure_missing_farm_browsers_on_serials(
    adb: AdbWrapper,
    serials: list[str],
    *,
    cache_dir: Path | None = None,
    force_download: bool = False,
    progress_cb: ProgressCb = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    """Sideload only *missing* Path1/2 browsers — gate for new farm phones.

    Phones that already have every required package are left alone. New or
    wiped guests get Chromium + Firefox + Brave + DuckDuckGo (or the
    ``CPHARM_FARM_BROWSERS`` subset) before sequences may start.
    """
    need = list(required) if required is not None else required_path12_packages()
    missing_by_serial: dict[str, list[str]] = {}
    for serial in serials:
        miss = missing_farm_browsers(adb, serial, required=need)
        missing_by_serial[serial] = miss
        if progress_cb:
            if miss:
                progress_cb(f"{serial}: missing {', '.join(miss)} — will sideload")
            else:
                progress_cb(f"{serial}: all required browsers present")

    pkgs_to_fetch = sorted({pkg for miss in missing_by_serial.values() for pkg in miss})
    apks: dict[str, Path] = {}
    cache = cache_dir or default_apk_cache_dir()
    for package in pkgs_to_fetch:
        spec = spec_for_package(package)
        if spec is None:
            logger.error("No APK catalog entry for required package %s", package)
            continue
        try:
            apks[package] = download_browser_apk(
                spec, cache_dir=cache, force=force_download, progress_cb=progress_cb
            )
        except Exception as exc:
            logger.error("Cannot download %s for farm gate: %s", package, exc)

    # Chromium soft fallback to bundled ChromePublic.apk
    if BROWSER_CHROMIUM in pkgs_to_fetch and BROWSER_CHROMIUM not in apks:
        try:
            from wizard.wizard_paths import chrome_apk_path

            legacy = chrome_apk_path()
            if legacy.is_file() and legacy.stat().st_size > 1_000_000:
                apks[BROWSER_CHROMIUM] = legacy
        except Exception as exc:
            logger.warning("Legacy Chromium fallback unavailable: %s", exc)

    install: dict[str, dict[str, bool]] = {}
    for package in pkgs_to_fetch:
        miss_serials = [s for s, miss in missing_by_serial.items() if package in miss]
        apk = apks.get(package)
        if not apk:
            install[package] = {s: False for s in miss_serials}
            continue
        if progress_cb:
            progress_cb(f"Installing {package} on {len(miss_serials)} phone(s)...")
        install[package] = install_apk_on_serials(adb, apk, miss_serials)

    per_phone: dict[str, dict[str, bool]] = {}
    still_missing: dict[str, list[str]] = {}
    for serial in serials:
        have = packages_on_device(adb, serial)
        status = {pkg: pkg in have for pkg in need}
        per_phone[serial] = status
        still = [pkg for pkg in need if not status.get(pkg)]
        if still:
            still_missing[serial] = still

    return {
        "required": need,
        "missing_before": missing_by_serial,
        "apks": {pkg: str(path) for pkg, path in apks.items()},
        "install": install,
        "per_phone": per_phone,
        "still_missing": still_missing,
        "ok": not still_missing,
        "play_store": False,
        "credentials_required": False,
        "note": (
            "Missing Path1/2 browsers sideloaded from public mirrors — "
            "no Play Store / no Google credentials."
        ),
    }


def catalog_markdown() -> str:
    """Operator-facing catalog text (also embedded in docs)."""
    lines = [
        "# Farm browser APK catalog",
        "",
        "All browsers are **sideloaded** with `adb install -r`. "
        "**Do not use the Google Play Store** on farm phones — it requires a Google "
        "account, phones home to Google, and breaks the unique-identity model.",
        "",
        "| Tag | Package | Path1/2 | Path3 | Source |",
        "|-----|---------|---------|-------|--------|",
    ]
    for s in BROWSER_APK_SPECS:
        src = {
            BROWSER_CHROMIUM: "download-chromium / Chromium snapshots",
            BROWSER_FIREFOX: "ftp.mozilla.org Fenix releases",
            BROWSER_BRAVE: "GitHub brave/brave-browser releases",
            BROWSER_DUCKDUCKGO: "GitHub duckduckgo/Android releases",
            BROWSER_OPERA: "get.geo.opera.com Opera Android FTP (arm8)",
        }.get(s.package, "?")
        lines.append(
            f"| `{s.tag}` | `{s.package}` | {'yes' if s.path12 else 'no'} | "
            f"{'yes' if s.path3 else 'no'} | {src} |"
        )
    lines.extend(
        [
            "",
            "## Credentials",
            "",
            "- **None required.** Downloads are anonymous HTTPS/FTP.",
            "- GitHub API for Brave is unauthenticated (rate-limited ~60/hr/IP).",
            "- If rate-limited, place APKs manually under `C:\\CPharm\\apks\\` "
            "using the filenames in this catalog and re-run the sideload script.",
            "",
            "## Update APKs",
            "",
            "```powershell",
            "py -3 scripts/sideload_farm_browsers.py --download-only --force",
            "py -3 scripts/sideload_farm_browsers.py --install",
            "```",
            "",
            "Or from PharmFlow.exe setup (Install browsers step) which calls the same logic.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"
