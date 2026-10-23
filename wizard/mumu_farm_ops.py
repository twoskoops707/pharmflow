"""
MuMu farm operations — single module used by PharmFlowMuMuSetup, PharmFlow wizard, and dashboard.

Operators run **PharmFlow → Phones → Set up my phones** or wizard Boot/Go buttons. The ``tools/`` scripts
are thin dev-only CLIs that call into this module.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

_wizard_dir = Path(__file__).resolve().parent
if str(_wizard_dir) not in sys.path:
    sys.path.insert(0, str(_wizard_dir))

LogFn = Callable[[str], None]

BASE_W, BASE_H = 900, 1600
HITS_PER_DAY = 720
PHARMFLOW_PHONE_FB_W, PHARMFLOW_PHONE_FB_H, PHARMFLOW_PHONE_FB_DPI = 900, 1600, 300

CORE_NO_AD = "900x1600/no-ad/dabflow__demo__ONE.json"
CORE_AD = "900x1600/ad/dabflow__demo__TWO.json"

NO_AD_VARIANTS = [
    "900x1600/no-ad/dabflow__no_ads__mat-quartz__conc-shatter__heat-butane.json",
    "900x1600/no-ad/dabflow__no_ads__mat-quartz__conc-wax__heat-propane.json",
    "900x1600/no-ad/dabflow__no_ads__mat-titanium__conc-live-resin__heat-butane.json",
    "900x1600/no-ad/dabflow__no_ads__mat-ceramic__conc-rosin__heat-propane.json",
    "900x1600/no-ad/dabflow__no_ads__mat-quartz__conc-diamonds__heat-butane.json",
    "900x1600/no-ad/dabflow__no_ads__mat-titanium__conc-budder__heat-propane.json",
]

AD_VARIANTS = [
    "900x1600/ad/dabflow__demo__TWO.json",
    "900x1600/ad/dabflow__ad__mat-quartz__conc-shatter__heat-butane.json",
    "900x1600/ad/dabflow__ad__mat-titanium__conc-live-resin__heat-propane.json",
    "900x1600/ad/dabflow__ad__mat-ceramic__conc-rosin__heat-butane.json",
]

_TOR_FARM_MODEL_ORDER = (
    "XQ_DE72",
    "XQ-DE72",
    "GC3VE",
    "SM_S9110",
    "SM-S9110",
)

MUMU_INSTALL_CANDIDATES = [
    Path(r"C:\Program Files\Netease\MuMuPlayerARM"),
    Path(r"C:\Program Files\Netease\MuMuPlayer"),
    Path(r"C:\Program Files (x86)\Netease\MuMuPlayerARM"),
]


def _noop_log(_msg: str) -> None:
    pass


def _ensure_automation() -> None:
    from wizard_paths import automation_on_sys_path

    automation_on_sys_path()


def _find_mumu_vms_root() -> Path | None:
    try:
        import mumu_detect

        for root in mumu_detect.iter_mumu_install_roots():
            vms = root / "vms"
            if vms.is_dir():
                return vms
    except Exception:
        pass
    for root in MUMU_INSTALL_CANDIDATES:
        vms = root / "vms"
        if vms.is_dir():
            return vms
    return None


def scan_mumu_vm_profiles() -> list[dict]:
    """Read each MuMu ``vms/vm*/setting.json`` (Phone vs Tablet / resolution)."""
    vms_root = _find_mumu_vms_root()
    if not vms_root:
        return []
    out: list[dict] = []
    for setting_path in sorted(vms_root.glob("vm*.gmadoa/setting.json")):
        try:
            data = json.loads(setting_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        vm_dir = setting_path.parent.name
        idx = vm_dir.split(".", 1)[0]
        res = data.get("ResolutionPresetSelected") or {}
        out.append(
            {
                "vm_dir": vm_dir,
                "vm_index": idx.replace("vm", "", 1) if idx.startswith("vm") else idx,
                "name": data.get("VmName", ""),
                "resolution_type": res.get("ResolutionType", "?"),
                "orientation": data.get("DeviceOrientation", "?"),
                "framebuffer": (
                    int(data.get("FramebufferWidth") or 0),
                    int(data.get("FramebufferHeight") or 0),
                ),
                "dpi": int(data.get("FramebufferDPI") or 0),
                "setting_path": str(setting_path),
            }
        )
    return out


def profile_needs_phone_baseline(prof: dict) -> bool:
    """True when MuMu setting.json is Tablet or not PharmFlow 900x1600 phone portrait."""
    if (prof.get("resolution_type") or "").lower() == "tablet":
        return True
    fw, fh = prof.get("framebuffer") or (0, 0)
    if (fw, fh) != (PHARMFLOW_PHONE_FB_W, PHARMFLOW_PHONE_FB_H):
        return True
    if int(prof.get("dpi") or 0) != PHARMFLOW_PHONE_FB_DPI:
        return True
    if (prof.get("orientation") or "").lower() != "portrait":
        return True
    return False


def fix_mumu_tablet_profiles(log: LogFn | None = None, *, dry_run: bool = False) -> int:
    """Normalize MuMu VMs to Phone portrait 900x1600. Returns fix count."""
    log = log or _noop_log
    fixed = 0
    for prof in scan_mumu_vm_profiles():
        if not profile_needs_phone_baseline(prof):
            continue
        sp = Path(prof["setting_path"])
        tag = (prof.get("resolution_type") or "?").upper()
        log(
            f"  FIX VM {prof['vm_dir']} ({prof.get('name') or '?'}) — {tag}, "
            f"{prof.get('orientation')} {prof['framebuffer'][0]}x{prof['framebuffer'][1]} "
            f"dpi={prof.get('dpi')}"
        )
        if dry_run:
            fixed += 1
            continue
        bak = sp.with_suffix(sp.suffix + f".bak-pharmflow-{int(time.time())}")
        shutil.copy2(sp, bak)
        data = json.loads(sp.read_text(encoding="utf-8-sig"))
        res = data.setdefault("ResolutionPresetSelected", {})
        res["ResolutionType"] = "Phone"
        data["DeviceOrientation"] = "Portrait"
        data["FramebufferWidth"] = PHARMFLOW_PHONE_FB_W
        data["FramebufferHeight"] = PHARMFLOW_PHONE_FB_H
        data["FramebufferDPI"] = PHARMFLOW_PHONE_FB_DPI
        sp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        log(f"    Patched {sp.name} (backup {bak.name}) — cold-boot this MuMu instance.")
        fixed += 1
    return fixed


def log_vm_profile_summary(log: LogFn | None = None) -> list[dict]:
    """Log MuMu VM profiles; return profiles that still need phone baseline."""
    log = log or _noop_log
    profiles = scan_mumu_vm_profiles()
    if not profiles:
        log("(MuMu vms/ not found — skip local profile scan)")
        return []
    log("MuMu VM profiles (setting.json):")
    for p in profiles:
        tag = p["resolution_type"]
        if tag.lower() == "tablet":
            tag = f"**{tag}**"
        log(
            f"  {p['vm_dir']}: {p.get('name') or '?'} — {tag}, "
            f"{p.get('orientation')} {p['framebuffer'][0]}x{p['framebuffer'][1]}"
        )
    bad = [p for p in profiles if profile_needs_phone_baseline(p)]
    if bad:
        log("")
        log("WARNING: A MuMu phone is Pad/Tablet or not 900 x 1600 portrait.")
        log("  GO will patch setting.json when possible — then cold reboot each phone.")
    return bad


def _farm_serial_sort_key(serial: str) -> tuple[int, str]:
    """Stable Tor farm order: XQ DE72 (8118), GC3VE (8119), SM S9110 (8120)."""
    import setup_wizard as wiz

    try:
        model = wiz.adb("shell", "getprop", "ro.product.model", serial=serial, timeout=8).strip()
    except Exception:
        model = ""
    norm = model.upper().replace("-", "_")
    for i, pat in enumerate(_TOR_FARM_MODEL_ORDER):
        pnorm = pat.upper().replace("-", "_")
        if norm == pnorm or pnorm in norm:
            return (i, serial)
    return (len(_TOR_FARM_MODEL_ORDER), serial)


def order_farm_serials(serials: list[str]) -> list[str]:
    return sorted(serials, key=_farm_serial_sort_key)


def list_adb_serials() -> list[str]:
    """Connected ``adb devices`` serials (unordered)."""
    import preflight_core as preflight

    return preflight.list_adb_phones()


def discover_serials(
    log: LogFn | None = None,
    *,
    count: int = 0,
    wait_minutes: float = 0,
    force_mumu_scan: bool = False,
) -> list[str]:
    """
    Discover every phone serial adb answers. ``count`` is ignored — a returned
    slice used to drop phones past that number. ``wait_minutes`` polls until
    any phone appears or the deadline passes.
    """
    log = log or _noop_log
    deadline = time.monotonic() + max(0.0, wait_minutes) * 60.0

    def _from_adb() -> list[str]:
        serials = list_adb_serials()
        if serials:
            log(f"  adb devices: {len(serials)} phone(s) ready")
            return order_farm_serials(serials)
        return []

    while True:
        serials = _from_adb()
        if serials:
            return serials

        if not force_mumu_scan and not count:
            if wait_minutes <= 0 or time.monotonic() >= deadline:
                return serials

        if wait_minutes <= 0 and not force_mumu_scan:
            break

        if time.monotonic() >= deadline and wait_minutes > 0:
            break

        if force_mumu_scan or (not serials and wait_minutes > 0):
            import setup_wizard as wiz

            wiz.state["use_mumu"] = True
            mgr = wiz._find_mumu_manager()
            if mgr:
                wiz.state["mumu_mgr_path"] = str(mgr)
                log(f"MuMu manager: {mgr}")
            connected = wiz._connect_mumu_phones(
                log_fn=lambda m: log(m),
                force_full_scan=True,
            )
            serials = order_farm_serials(connected)
            if serials:
                return serials

        if wait_minutes <= 0:
            break
        log(f"  Found {len(serials)}/{count or '?'} phones — waiting 20s (boot more in MuMu)…")
        time.sleep(20)

    return order_farm_serials(serials)


def adb_device_props(serial: str) -> dict[str, str]:
    import setup_wizard as wiz

    keys = ("ro.build.characteristics", "ro.product.model", "ro.product.brand")
    out: dict[str, str] = {}
    for k in keys:
        try:
            out[k] = wiz.adb("shell", "getprop", k, serial=serial, timeout=8).strip()
        except Exception:
            out[k] = "?"
    try:
        out["wm_size"] = wiz.adb("shell", "wm", "size", serial=serial, timeout=8).strip()
    except Exception:
        out["wm_size"] = "?"
    return out


def phone_playlist_entry(
    index: int,
    *,
    extended_ad: bool = True,
    ad_only: bool = False,
) -> dict:
    """Build one phone entry for groups_config.json (50/50 no-ad vs ad by default)."""
    ad_variant = AD_VARIANTS[index % len(AD_VARIANTS)] if extended_ad else CORE_AD
    if ad_only:
        playlist = [CORE_AD, ad_variant]
        secondary: list[str] = []
        shuffle = "none"
    else:
        variant = NO_AD_VARIANTS[index % len(NO_AD_VARIANTS)]
        ad_pick = ad_variant
        playlist = [CORE_NO_AD, variant]
        secondary = [ad_pick]
        shuffle = "combined"
    return {
        "steps": [],
        "hits_per_day": HITS_PER_DAY,
        "use_default_template": True,
        "explicit_override": False,
        "sequence_base_w": BASE_W,
        "sequence_base_h": BASE_H,
        "sequence_profile_key": f"{BASE_W}x{BASE_H}",
        "sequence_playlist": playlist,
        "sequence_playlist_secondary": secondary,
        "sequence_playlist_mode": "random",
        "sequence_playlist_shuffle": shuffle,
    }


def apply_fingerprint_all(
    serials: list[str],
    log: LogFn | None = None,
    *,
    log_fn: LogFn | None = None,
    patch_vms: bool = True,
) -> dict:
    """Patch MuMu VMs + browser disguise on all serials."""
    _ensure_automation()
    import mumu_fingerprint as mfp

    log = log_fn or log or _noop_log
    return mfp.apply_fingerprint_all_serials(serials, patch_vms=patch_vms, log_fn=log)


def audit_fingerprint_all(serials: list[str], log: LogFn | None = None) -> dict:
    """Audit every serial; return summary with leak counts."""
    _ensure_automation()
    import mumu_fingerprint as mfp

    log = log or _noop_log
    bad = 0
    leaks_total = 0
    for i, serial in enumerate(serials):
        log(mfp.format_audit_report(serial, farm_index=i))
        audit = mfp.audit_device_fingerprint(
            serial,
            expected_profile=mfp.profile_for_index(i),
        )
        if audit.leaks:
            bad += 1
            leaks_total += len(audit.leaks)
        log("-" * 50)
    return {
        "phones": len(serials),
        "phones_with_leaks": bad,
        "leaks_total": leaks_total,
        "all_clean": bad == 0,
    }


def audit_one_serial(
    serial: str,
    log: LogFn | None = None,
    *,
    farm_index: int = 0,
) -> dict:
    """Audit one phone; return audit object summary."""
    _ensure_automation()
    import mumu_fingerprint as mfp

    log = log or _noop_log
    log(mfp.format_audit_report(serial, farm_index=farm_index))
    audit = mfp.audit_device_fingerprint(
        serial,
        expected_profile=mfp.profile_for_index(farm_index),
    )
    return {
        "serial": serial,
        "leaks": list(audit.leaks),
        "clean": not audit.leaks,
    }


def apply_one_serial(
    serial: str,
    log: LogFn | None = None,
    *,
    farm_index: int = 0,
    patch_vms: bool = True,
) -> dict:
    """Apply fingerprint fix to one phone."""
    summary = apply_fingerprint_all([serial], log, patch_vms=patch_vms)
    audit = audit_one_serial(serial, log, farm_index=farm_index)
    summary["clean"] = audit["clean"]
    summary["leaks"] = audit["leaks"]
    return summary


def configure_phone_for_farm(serial: str, log: LogFn | None = None, *, index: int = 0) -> None:
    """Clear proxy, set 900×1600, apply browser fingerprint flags, log props."""
    import browser_setup

    log = log or _noop_log
    log(f"  Configuring {serial}…")
    browser_setup.configure_phone_baseline(serial, log)
    _ensure_automation()
    import mumu_fingerprint as mfp

    fp = mfp.apply_browser_fingerprint_adb(serial, farm_index=index)
    if fp.get("user_agent_written"):
        log(f"    fingerprint: browser UA applied ({fp.get('profile')})")
    else:
        log("    fingerprint: WARNING — could not write browser UA flags on device")
    props = adb_device_props(serial)
    chars = props.get("ro.build.characteristics", "?")
    log(
        f"    getprop: characteristics={chars} model={props.get('ro.product.model', '?')} "
        f"brand={props.get('ro.product.brand', '?')}"
    )
    if "tablet" in chars.lower():
        log(
            "    WARNING: phone reports Tablet — cold reboot after MuMu Phone profile fix."
        )
    audit = mfp.audit_device_fingerprint(serial)
    if audit.leaks:
        log(f"    fingerprint leaks ({len(audit.leaks)}) — cold-boot after VM patch:")
        for leak in audit.leaks[:4]:
            log(f"      • {leak}")


def phones_needing_cold_boot(serials: list[str]) -> tuple[int, list[str]]:
    """Return count and serials that still need a MuMu STOP→START after VM patch."""
    _ensure_automation()
    import mumu_fingerprint as mfp

    bad: list[str] = []
    for i, serial in enumerate(serials):
        audit = mfp.audit_device_fingerprint(
            serial,
            expected_profile=mfp.profile_for_index(i),
        )
        if audit.cold_boot_needed or (
            audit.leaks
            and any(
                "ro.kernel.qemu" in x or "ro.product.model" in x or "ro.product.manufacturer" in x
                for x in audit.leaks
            )
        ):
            bad.append(serial)
    return len(bad), bad


def run_vm_prep_only(log: LogFn | None = None) -> dict:
    """
    Pad→Phone fix + MuMu VM identity patch only (no ADB browser work).

    Returns ``{tablet_fixed, any_vm_patched, needs_cold_boot}``.
    """
    log = log or _noop_log
    prep = prepare_vm_profiles(log, auto_fix=True)
    tablet_fixed = int(prep.get("fixed_count") or 0)
    _ensure_automation()
    import mumu_fingerprint as mfp

    log("")
    log("Patching MuMu VM identities (setting.json)…")
    vm_results = mfp.apply_mumu_vm_fingerprints(log_fn=log)
    any_vm_patched = any(r.get("patched") for r in vm_results)
    needs = tablet_fixed > 0 or any_vm_patched
    if needs and log:
        log("")
        log("MuMu files changed — phones must cold-boot before the next step works.")
    return {
        "tablet_fixed": tablet_fixed,
        "any_vm_patched": any_vm_patched,
        "needs_cold_boot": needs,
    }


def run_post_reboot_setup(
    serials: list[str],
    log: LogFn | None = None,
) -> dict:
    """
    After cold boot: browser flags, Chromium install, baseline — no VM patch.

    Merges fingerprint summary + chromium + browser_warnings.
    """
    log = log or _noop_log
    summary = apply_fingerprint_all(serials, log, patch_vms=False)

    import browser_setup

    log("")
    log("Screen size + proxy cleanup on each phone…")
    for serial in serials:
        browser_setup.configure_phone_baseline(serial, log)

    log("")
    log("Installing Chromium on each phone (getdabflow.app ads need it)…")
    chrome = install_chromium_on_phones(serials, log)
    summary["browser_warnings"] = []
    if not chrome.get("ok"):
        for row in chrome.get("results") or []:
            if not row.get("ok"):
                summary["browser_warnings"].append(
                    f"{row.get('serial')}: {row.get('message', 'no browser')}"
                )
        if not summary["browser_warnings"]:
            fail_msg = str(chrome.get("message") or "Chromium install failed")
            summary["browser_warnings"].extend(f"{s}: {fail_msg}" for s in serials)
    else:
        for row in chrome.get("results") or []:
            pkg = row.get("pkg")
            if row.get("ok") and pkg:
                browser_setup.warm_browser(str(row.get("serial") or ""), str(pkg), log)
    summary["chromium"] = chrome
    return summary


def download_chromium_apk(log: LogFn | None = None) -> Path | None:
    import browser_setup

    return browser_setup.download_official_chromium_apk(log or _noop_log)


def ensure_browsers_on_phones(
    serials: list[str],
    log: LogFn | None = None,
) -> dict:
    """
    Ensure each phone has a DabFlow-capable browser (MuMu Browser preferred).

    Downloads/sideloads Chromium only when no browser is present — used by GO
    after cold boot, not the explicit **Install Chromium** button.
    """
    import browser_setup

    log = log or _noop_log
    if not serials:
        return {"ok": False, "results": [], "message": "No phones connected."}

    log("Checking browser on each phone (MuMu Browser preferred)…")
    results: list[dict] = []
    ok_all = True
    for i, serial in enumerate(serials):
        log(f"  Phone {i + 1} ({serial}):")
        ok, pkg, msg = browser_setup.ensure_browser(serial, log)
        if ok and pkg:
            log(f"    ✓ {msg}")
            browser_setup.warm_browser(serial, pkg, log)
        else:
            log(f"    ✗ {msg}")
            ok_all = False
        results.append({"serial": serial, "ok": ok, "pkg": pkg, "message": msg})

    message = (
        "Browser ready on all phones."
        if ok_all
        else "Some phones still missing a browser — use Install Chromium or open MuMu Browser once."
    )
    return {"ok": ok_all, "results": results, "message": message}


def install_chromium_on_phones(
    serials: list[str],
    log: LogFn | None = None,
    *,
    download_if_missing: bool = True,
) -> dict:
    """
    Download ChromePublic.apk to ``bundled/`` (once) and sideload on every serial.

    Returns ``{ok, apk, results, message}``.
    """
    import browser_setup

    log = log or _noop_log
    if not serials:
        return {"ok": False, "apk": "", "results": [], "message": "No phones connected."}

    log("Chromium for Android (~230 MB once)…")
    abi_hint = browser_setup.device_primary_abi(serials[0]) if serials else ""
    if abi_hint:
        log(f"  Phone ABI: {abi_hint} (MuMu ARM64 needs arm64-v8a build)")
    apk = None
    if download_if_missing:
        apk = browser_setup.download_official_chromium_apk(
            log, abi=abi_hint or None, serial=serials[0] if serials else None
        )
    if not apk or not apk.is_file():
        sideload = browser_setup.find_sideload_apk(serial=serials[0] if serials else None)
        if sideload:
            apk = sideload[0]
            log(f"  Using existing APK: {apk}")
        else:
            return {
                "ok": False,
                "apk": "",
                "results": [],
                "message": "Chromium download failed — check internet and try again.",
            }
    else:
        log(f"  Ready: {apk}")

    log("")
    log(f"Sideloading Chromium on {len(serials)} phone(s)…")
    log("  App drawer icon: Chromium (package org.chromium.chrome)")
    results: list[dict] = []
    ok_all = True
    for i, serial in enumerate(serials):
        log(f"  Phone {i + 1} ({serial}):")
        # Resolve first: an already-known/sideloaded APK must not trigger a
        # fresh 230 MB download, and must not fall through to ensure_browser.
        phone_apk = browser_setup.resolve_chromium_apk(serial, log) if download_if_missing else None
        if not phone_apk or not phone_apk.is_file():
            if download_if_missing:
                phone_apk = browser_setup.download_official_chromium_apk(
                    log, abi=abi_hint or None, serial=serial
                )
            if not phone_apk or not phone_apk.is_file():
                sideload = browser_setup.find_sideload_apk(serial=serial)
                if sideload:
                    phone_apk = sideload[0]
                    log(f"  Using existing APK: {phone_apk}")
        if not phone_apk or not phone_apk.is_file():
            log(f"    ✗ Could not get Chromium APK for this phone")
            ok_all = False
            results.append({"serial": serial, "ok": False, "pkg": None, "message": "Chromium download failed"})
            continue
        ok, pkg, msg = browser_setup.install_chromium_apk(serial, phone_apk, log)
        if ok and pkg:
            log(f"    ✓ {msg}")
            browser_setup.warm_browser(serial, pkg, log)
        else:
            log(f"    ✗ {msg}")
            ok_all = False
        results.append({"serial": serial, "ok": ok, "pkg": pkg, "message": msg})

    message = (
        f"Chromium installed on all {len(serials)} phone(s) — look for Chromium in the app drawer."
        if ok_all
        else "Some phones failed Chromium install — check adb output in the log."
    )
    return {"ok": ok_all, "apk": str(apk), "results": results, "message": message}


def prepare_vm_profiles(log: LogFn | None = None, *, auto_fix: bool = True) -> dict:
    """
    Scan MuMu VM profiles; optionally patch Tablet → Phone.

    Returns ``{bad_profiles, fixed_count, any_fixed}``.
    """
    log = log or _noop_log
    bad = log_vm_profile_summary(log)
    fixed = 0
    if auto_fix and bad:
        log("")
        log("Patching MuMu VM profiles to Phone 900×1600…")
        fixed = fix_mumu_tablet_profiles(log)
        if fixed:
            log(f"  Patched {fixed} VM(s). Cold-boot those instances before ADB setup.")
    return {"bad_profiles": bad, "fixed_count": fixed, "any_fixed": fixed > 0}


def run_farm_setup(
    log: LogFn | None = None,
    *,
    serials: list[str] | None = None,
    fix_tablet: bool = True,
    patch_vms: bool = True,
    configure_browsers: bool = True,
    count: int = 0,
    wait_minutes: float = 0,
) -> tuple[list[str], dict]:
    """
    Core farm prep used by PharmFlowMuMuSetup GO and wizard re-apply buttons.

    Returns ``(serials, fingerprint_summary)``.
    """
    log = log or _noop_log

    if fix_tablet:
        prepare_vm_profiles(log, auto_fix=True)

    if serials is None:
        serials = discover_serials(log, count=count, wait_minutes=wait_minutes)
    elif not serials:
        return [], {"leaks_total": 0, "any_vm_patched": False, "all_clean": False}

    if not serials:
        return [], {"leaks_total": 0, "any_vm_patched": False, "all_clean": False}

    log("")
    log("Hiding emulator look on every phone…")
    log(f"Preparing {len(serials)} phone(s): {', '.join(serials)}")
    summary = apply_fingerprint_all(serials, log, patch_vms=patch_vms)

    if configure_browsers:
        import browser_setup

        log("")
        log("Installing Chromium + screen baseline on each phone…")
        browser_warnings: list[str] = []
        chrome = install_chromium_on_phones(serials, log)
        if not chrome.get("ok"):
            for row in chrome.get("results") or []:
                if not row.get("ok"):
                    browser_warnings.append(
                        f"{row.get('serial')}: {row.get('message', 'Chromium install failed')}"
                    )
        for i, serial in enumerate(serials):
            log(f"  Phone {i + 1} ({serial}):")
            browser_setup.configure_phone_baseline(serial, log)
            pkg = browser_setup.CHROMIUM_PUBLIC_PKG
            if browser_setup.pkg_installed(serial, pkg):
                browser_setup.warm_browser(serial, pkg, log)
                log("    Browser: Chromium ready for getdabflow.app")
            elif browser_setup.pkg_installed(serial, browser_setup.CHROME_PKG):
                pkg = browser_setup.CHROME_PKG
                browser_setup.warm_browser(serial, pkg, log)
                log("    Browser: Chrome ready for getdabflow.app")
            else:
                browser_warnings.append(f"{serial}: Chromium not installed")
                log("    Browser: Chromium missing — run GO again or Install Chromium")
        summary["browser_warnings"] = browser_warnings

    return serials, summary


def write_groups_config_file(
    serials: list[str],
    out_path: Path,
    *,
    extended_ad: bool = False,
    note: str = "Written by PharmFlow MuMu farm setup",
) -> Path:
    """Write ``groups_config.json`` for connected serials (repo dev or install root)."""
    phones = {
        s: phone_playlist_entry(i, extended_ad=extended_ad) for i, s in enumerate(serials)
    }
    cfg = {
        "_note": note,
        "groups": [
            {
                "name": "Group 1",
                "phones": phones,
                "stagger_secs": 30,
                "repeat": 1,
                "repeat_forever": False,
                "human_stagger": True,
            }
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return out_path


def write_desktop_prefs_file(serials: list[str], out_path: Path, *, note: str | None = None) -> Path:
    """Write ``desktop_prefs.json`` with Tor slot phone order."""
    data = {
        "tor_proxy_configured": False,
        "browse_proxy_mode": "scramble",
        "phone_upstream_proxies": [],
        "phone_serials": serials,
        "mumu_setup_complete": False,
        "note": note
        or "MuMu farm setup; Tor/upstream slots follow phone_serials order. Default browse: scramble.",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return out_path


# --- PharmFlow generation appendix (merged): MuMuInstance / MuMuFarmOps ---
import logging as _logging_fb
from dataclasses import asdict, dataclass, field
from automation.adb_wrapper import AdbDevice, AdbWrapper
from automation.browser_farm import ensure_fingerprint_before_browse_impl
from automation.config import (
    MUMU_DEFAULT_DPI,
    MUMU_DEFAULT_HEIGHT,
    MUMU_DEFAULT_WIDTH,
    PhoneConfig,
    is_browser_only_identity,
    is_skip_fingerprint,
)
from automation.mumu_fingerprint import (
    AntiDetectionReport,
    FingerprintProfile,
    apply_farm_guest_rails_file,
    apply_farm_guest_rails_vm,
    apply_fingerprint,
    find_setting_json,
    find_vm_dir,
    random_profile,
    rotate_fingerprint,
    verify_anti_detection,
)
from automation.tor_manager import TorManager
from automation.win_subprocess import hidden_run_kwargs
from wizard.wizard_paths import (
    MUMU_SEARCH_PATHS,
    app_data_root,
    detect_mumu_root,
    desktop_prefs_file,
    load_config,
    mumu_manager_exe,
    mumu_vms_dir,
    save_config,
    save_desktop_prefs,
    validate_mumu_root,
)
logger = _logging_fb.getLogger(__name__)
ADB_PORT_BASE = 16384
ADB_PORT_STRIDE = 32
# One ARM cold-launch at a time — parallel start_phone wedges HCN (Wait For AsyncTask).
_ARM_BOOT_LOCK = threading.Lock()
# Snapdragon cold-boot ADB can take 2–4 min after shell launch.
_ARM_ADB_WAIT_ALREADY_S = 45.0
_ARM_ADB_WAIT_AFTER_LAUNCH_S = 240.0


@dataclass
class MuMuInstance:
    """Represents one MuMu emulator instance."""

    name: str
    index: int
    vm_path: Path
    adb_serial: str = ""
    running: bool = False
    width: int = MUMU_DEFAULT_WIDTH
    height: int = MUMU_DEFAULT_HEIGHT
    fingerprint: FingerprintProfile | None = None
    config: PhoneConfig | None = None

    def __post_init__(self) -> None:
        # Do NOT invent classic 127.0.0.1:16384+N when serial is unknown.
        # On MuMu ARM that false serial marks live 10.0.2.x phones as "offline"
        # and triggers duplicate cold-launches / wrong-phone selection.
        if not self.config:
            self.config = PhoneConfig(
                name=self.name, index=self.index, adb_serial=self.adb_serial or ""
            )


class MuMuFarmOps:
    """Central class for MuMu detection, phone CRUD, and per-phone ADB commands."""

    def __init__(self, mumu_root: Path | None = None) -> None:
        if isinstance(mumu_root, str):
            mumu_root = Path(mumu_root) if mumu_root else None
        self.mumu_root = mumu_root or detect_mumu_root()
        self.manager = mumu_manager_exe(self.mumu_root)
        self.vms_dir = mumu_vms_dir(self.mumu_root)
        self.adb = AdbWrapper()
        self.tor = TorManager(self.adb)
        self.instances: dict[str, MuMuInstance] = {}
        self._profiles: dict[str, FingerprintProfile] = {}
        self._instances_lock = threading.RLock()
        self._last_exit_ip_rotate = None
        self._mpid_map_cache: dict[int, str] | None = None
        self._mpid_map_cache_at: float = 0.0

    # ------------------------------------------------------------------
    # MuMu detection & path discovery
    # ------------------------------------------------------------------

    def discover_mumu_paths(self) -> list[Path]:
        """Return every valid MuMu install root found on this machine."""
        found: list[Path] = []
        seen: set[str] = set()

        def add(path: Path | None) -> None:
            if path and validate_mumu_root(path):
                key = str(path.resolve())
                if key not in seen:
                    seen.add(key)
                    found.append(path)

        cfg = load_config()
        saved = cfg.get("mumu_root")
        if saved:
            add(Path(saved))
        add(self.mumu_root)
        for candidate in MUMU_SEARCH_PATHS:
            add(candidate)
        for pf in (Path(r"C:\Program Files"), Path(r"C:\Program Files (x86)")):
            if not pf.is_dir():
                continue
            for child in pf.iterdir():
                if "mumu" in child.name.lower():
                    add(child)
        return found

    def redetect_mumu(self) -> bool:
        """Re-scan for MuMu and refresh manager/vms paths."""
        paths = self.discover_mumu_paths()
        if not paths:
            self.mumu_root = None
            self.manager = None
            self.vms_dir = None
            return False
        self.mumu_root = paths[0]
        self.manager = mumu_manager_exe(self.mumu_root)
        self.vms_dir = mumu_vms_dir(self.mumu_root)
        return self.is_ready

    @property
    def is_ready(self) -> bool:
        return bool(self.mumu_root and self.manager and self.vms_dir)

    def detect(self) -> dict[str, Any]:
        """Return detection status for preflight."""
        paths = self.discover_mumu_paths()
        return {
            "mumu_root": str(self.mumu_root) if self.mumu_root else None,
            "manager": str(self.manager) if self.manager else None,
            "vms_dir": str(self.vms_dir) if self.vms_dir else None,
            "candidates": [str(p) for p in paths],
            "ready": self.is_ready,
        }

    # ------------------------------------------------------------------
    # ADB enumeration (dynamic serials via adb devices -l)
    # ------------------------------------------------------------------

    def enumerate_adb_devices(self, *, force: bool = False) -> list[AdbDevice]:
        """Return live devices from `adb devices -l` (2s cache to stop poll storms)."""
        now = time.monotonic()
        cached = getattr(self, "_adb_devices_cache", None)
        cache_at = float(getattr(self, "_adb_devices_cache_at", 0.0) or 0.0)
        if not force and cached is not None and (now - cache_at) < 2.0:
            return list(cached)
        devices = self.adb.devices_detailed()
        self._adb_devices_cache = devices
        self._adb_devices_cache_at = now
        return list(devices)

    def refresh_serials(self) -> dict[str, str]:
        """Re-resolve every known phone to its live ADB serial."""
        log_dir = Path(os.environ.get("PHARMFLOW_LOG_DIR", r"C:\PharmFlow\logs"))
        lock_path = log_dir / "ADB_SERIAL_MAP.lock.json"
        phones_map: dict[str, str] = {}
        tablet_map: dict[str, str] = {}
        try:
            if lock_path.is_file():
                data = json.loads(lock_path.read_text(encoding="utf-8-sig"))
                phones_map = dict(data.get("phones") or {})
                tablet_map = dict(data.get("tablet") or {})
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
        # Hold instances lock for list+mutate+snapshot. Concurrent isolate threads
        # previously hit "dictionary changed size during iteration" when one
        # phone called list_instances.clear() while another iterated .items().
        with self._instances_lock:
            self._list_instances_unlocked()
            for name, inst in list(self.instances.items()):
                locked = str(phones_map.get(name) or tablet_map.get(name) or "").strip()
                arm = self._arm_adb_serial_from_state(name)
                # ARM state.json AdbHost is ground truth. A stale lock once mapped
                # vm8 onto vm0's 10.0.2.222 and poisoned remediator + inject.
                if arm.startswith("10.0.2."):
                    prefer = arm
                else:
                    prefer = locked or arm
                if prefer and (
                    not inst.adb_serial
                    or inst.adb_serial.startswith("127.0.0.1:")
                    or prefer != inst.adb_serial
                ):
                    inst.adb_serial = prefer
                    if inst.config is not None:
                        inst.config.adb_serial = prefer
            return {name: inst.adb_serial for name, inst in list(self.instances.items())}

    def _expected_port(self, index: int) -> int:
        return ADB_PORT_BASE + index * ADB_PORT_STRIDE

    def _expected_serial(self, index: int) -> str:
        return f"127.0.0.1:{self._expected_port(index)}"

    def _setting_identity_keys(self, vm_path: Path) -> list[str]:
        """Collect brand/model/Miit tokens from ARM or classic setting.json.

        Prefer PhoneProp.* (what the running guest reports) over PharmFlow patch
        fields that may lag until the next cold boot.
        """
        ordered: list[str] = []
        setting = vm_path / "setting.json"
        if not setting.is_file():
            return ordered
        try:
            data = json.loads(setting.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return ordered
        phone_prop = data.get("PhoneProp") if isinstance(data.get("PhoneProp"), dict) else {}
        for raw in (
            phone_prop.get("Miit"),
            phone_prop.get("Model"),
            data.get("phonePropMiit"),
            data.get("phonePropModel"),
            data.get("phoneModel"),
            data.get("phone_model"),
            phone_prop.get("Brand"),
            data.get("phone_brand"),
        ):
            if isinstance(raw, str) and raw.strip():
                ordered.append(raw.strip().lower().replace(" ", "_").replace("-", "_"))
        return list(dict.fromkeys(ordered))

    def _is_arm_backend(self) -> bool:
        """True when MuMu Player ARM (nemux) manager is configured â€” no classic CLI.

        Do not probe the live ADB bus here: a host can have leftover 10.0.2.x
        devices while unit tests exercise classic localhost port resolution.
        """
        return bool(self.manager and "nemux" in self.manager.name.lower())

    def _serial_map_from_lock(self, live_devices: list[AdbDevice]) -> dict[int, str] | None:
        """Use ADB_SERIAL_MAP.lock when every listed serial is live — skips mpid getprop storm."""
        log_dir = Path(os.environ.get("PHARMFLOW_LOG_DIR", r"C:\PharmFlow\logs"))
        lock_path = log_dir / "ADB_SERIAL_MAP.lock.json"
        if not lock_path.is_file():
            return None
        try:
            data = json.loads(lock_path.read_text(encoding="utf-8-sig"))
            phones_map = dict(data.get("phones") or {})
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None
        if not phones_map:
            return None
        live = {d.serial for d in live_devices if d.online and d.serial.startswith("10.0.2.")}
        out: dict[int, str] = {}
        for name, ser in phones_map.items():
            ser = str(ser or "").strip()
            if not ser or ser not in live:
                continue
            m = re.match(r"^vm(\d+)", name, re.IGNORECASE)
            if not m:
                continue
            out[int(m.group(1))] = ser
        return out or None

    def _arm_mpid_map(self, live_devices: list[AdbDevice]) -> dict[int, str]:
        """Map nemud.player_mpid -> ADB serial for online ARM guests.

        Cached 20s — isolate/scramble used to re-probe every phone (3–60s each)
        and turn a 4–5 min Path3 into 35–45 min.
        """
        now = time.monotonic()
        cached = getattr(self, "_mpid_map_cache", None)
        cache_at = float(getattr(self, "_mpid_map_cache_at", 0.0) or 0.0)
        if cached is not None and (now - cache_at) < 20.0:
            return dict(cached)
        out: dict[int, str] = {}
        for dev in live_devices:
            if not dev.online or not dev.serial.startswith("10.0.2."):
                continue
            mpid = self.adb.getprop("nemud.player_mpid", serial=dev.serial).strip()
            if mpid.isdigit():
                out[int(mpid)] = dev.serial
        self._mpid_map_cache = out
        self._mpid_map_cache_at = now
        return dict(out)

    def _resolve_adb_serial(
        self,
        name: str,
        index: int,
        live_devices: list[AdbDevice],
        vm_path: Path | None = None,
        *,
        claimed: set[str] | None = None,
        mpid_map: dict[int, str] | None = None,
    ) -> str:
        """Map a VM to its current ADB serial (classic localhost ports or ARM 10.0.2.x).

        On MuMu ARM, brand/model identity matching is skipped â€” shared fingerprints
        collide across VMs. Prefer ``nemud.player_mpid`` and never reuse a claimed serial.
        """
        expected = self._expected_serial(index)
        expected_port = str(self._expected_port(index))
        name_key = name.lower()
        taken = claimed or set()
        arm_mode = self._is_arm_backend() or any(d.serial.startswith("10.0.2.") for d in live_devices)

        def _free(serial: str) -> bool:
            return bool(serial) and serial not in taken

        if arm_mode:
            gmadoa_match = re.match(r"^vm(\d+)\.gmadoa$", name, re.IGNORECASE)
            want_idx = int(gmadoa_match.group(1)) if gmadoa_match else index
            mapping = mpid_map if mpid_map is not None else self._arm_mpid_map(live_devices)
            serial = mapping.get(want_idx, "")
            if _free(serial):
                return serial
            mpid_bound = set(mapping.values())
            prev = self.instances.get(name)
            if prev and prev.adb_serial and _free(prev.adb_serial):
                if prev.adb_serial in mpid_bound and mapping.get(want_idx) != prev.adb_serial:
                    pass
                elif any(d.online and d.serial == prev.adb_serial for d in live_devices):
                    return prev.adb_serial
            # Do NOT assign leftovers[0] — that maps the wrong phone onto this VM
            # (vm8→vm0 style) and poisons remediator + inject. Leave unresolved.
            return ""

        identity_keys = self._setting_identity_keys(vm_path) if vm_path else []
        for dev in live_devices:
            if not dev.online or not _free(dev.serial):
                continue
            serial_l = dev.serial.lower()
            if dev.serial == expected or expected_port in dev.serial:
                return dev.serial
            if name_key in serial_l:
                return dev.serial
            blob = " ".join(
                [dev.product, dev.model, dev.device, *dev.extras.values()]
            ).lower()
            if name_key in blob:
                return dev.serial
            blob_norm = blob.replace(" ", "_").replace("-", "_")
            for key in identity_keys:
                if key and key in blob_norm:
                    return dev.serial

        prev = self.instances.get(name)
        if prev and prev.adb_serial and _free(prev.adb_serial):
            for dev in live_devices:
                if dev.online and dev.serial == prev.adb_serial:
                    return prev.adb_serial

        # Classic MuMu: try connecting the default localhost port for this index.
        connect_result = self.adb.connect(expected)
        if connect_result.ok or "already connected" in connect_result.stdout.lower():
            for dev in self.adb.devices_detailed():
                if dev.online and _free(dev.serial) and (dev.serial == expected or expected_port in dev.serial):
                    return dev.serial

        return expected if _free(expected) else ""

    def _run_manager(self, *args: str, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
        if not self.manager:
            raise RuntimeError("MuMuManager.exe not found")
        if self._is_arm_backend():
            # MuMu Player ARM Manager is GUI-only; classic `api create/launch` does not exist.
            logger.warning("MuMu ARM has no CLI for %s â€” skipping manager call", " ".join(args))
            return subprocess.CompletedProcess(args=[str(self.manager), *args], returncode=1, stdout="", stderr="arm-no-cli")
        cmd = [str(self.manager), *args]
        logger.info("MuMuManager: %s", " ".join(cmd))
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            **hidden_run_kwargs(),
        )

    def _phone_index_order(self) -> dict[str, int]:
        """Map phone name -> tor slot index from desktop_prefs (not alphabetical)."""
        order: list[str] = []
        cfg = load_config()
        if cfg.get("phones"):
            order = list(cfg["phones"])
        prefs_path = desktop_prefs_file()
        if prefs_path.is_file():
            try:
                prefs = json.loads(desktop_prefs_file().read_text(encoding="utf-8"))
                order = prefs.get("phone_order") or prefs.get("tor_slot_order") or order
            except json.JSONDecodeError:
                pass
        return {name: idx for idx, name in enumerate(order)}

    def list_instances(self) -> list[MuMuInstance]:
        """Enumerate MuMu VMs; refresh each phone's ADB serial from `adb devices -l`."""
        with self._instances_lock:
            return self._list_instances_unlocked()

    def _seed_adb_only_instances(self, live_devices: list[AdbDevice]) -> list[MuMuInstance]:
        """Build synthetic phones from ADB lock / sticky when MuMu is not installed.

        Used on x64 transfer boxes running BlueStacks, Studio AVD, LDPlayer, etc.
        """
        log_dir = Path(os.environ.get("PHARMFLOW_LOG_DIR", r"C:\PharmFlow\logs"))
        phones_map: dict[str, str] = {}
        try:
            lock_path = log_dir / "ADB_SERIAL_MAP.lock.json"
            if lock_path.is_file():
                data = json.loads(lock_path.read_text(encoding="utf-8-sig"))
                phones_map = {
                    str(k): str(v).strip()
                    for k, v in dict(data.get("phones") or {}).items()
                    if str(v).strip()
                }
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            phones_map = {}
        if not phones_map:
            try:
                ov_path = log_dir / "farm_runtime_overrides.json"
                ov = json.loads(ov_path.read_text(encoding="utf-8-sig")) if ov_path.is_file() else {}
                names = [
                    p.strip()
                    for p in str(ov.get("PHARMFLOW_FARM_PHONES") or "").split(",")
                    if p.strip()
                ]
                serials = [
                    s.strip()
                    for s in str(ov.get("PHARMFLOW_ADB_SERIALS") or "").split(",")
                    if s.strip()
                ]
                for i, name in enumerate(names):
                    if i < len(serials):
                        phones_map[name] = serials[i]
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                phones_map = {}
        online = {d.serial for d in live_devices if d.online}
        # If sticky empty, map online devices to vm0.gmadoa, vm1.gmadoa, ...
        if not phones_map and online:
            for i, ser in enumerate(sorted(online)):
                phones_map[f"vm{i}.gmadoa"] = ser

        self.instances.clear()
        instances: list[MuMuInstance] = []
        for name, serial in sorted(
            phones_map.items(),
            key=lambda kv: int(re.match(r"^vm(\d+)", kv[0], re.I).group(1))
            if re.match(r"^vm(\d+)", kv[0], re.I)
            else 99,
        ):
            m = re.match(r"^vm(\d+)", name, re.I)
            idx = int(m.group(1)) if m else len(instances)
            connected = serial in online
            inst = MuMuInstance(
                name=name,
                index=idx,
                vm_path=Path(r"C:\PharmFlow\adb_only") / name,
                adb_serial=serial,
                running=connected,
            )
            instances.append(inst)
            self.instances[name] = inst
        if instances:
            logger.info(
                "ADB-only phone seed: %s",
                ", ".join(f"{i.name}={i.adb_serial}" for i in instances),
            )
            # Live-only roster here too: an ADB-serial row whose phone is not
            # actually online is a ghost and must not enter the config roster.
            self._sync_phone_names([i.name for i in instances if i.running])
        return instances

    def _list_instances_unlocked(self) -> list[MuMuInstance]:
        instances: list[MuMuInstance] = []
        live_devices = self.enumerate_adb_devices()
        index_map = self._phone_index_order()
        next_auto = 0
        claimed: set[str] = set()
        arm_mode = any(d.serial.startswith("10.0.2.") for d in live_devices) or (
            bool(self.manager and "nemux" in self.manager.name.lower())
        )
        mpid_map = self._serial_map_from_lock(live_devices)
        if mpid_map is None:
            mpid_map = self._arm_mpid_map(live_devices) if arm_mode else {}

        if not self.vms_dir or not self.vms_dir.is_dir():
            # ADB-only mode (BlueStacks / Studio AVD / LDPlayer): no MuMu VMs dir.
            return self._seed_adb_only_instances(live_devices)

        self.instances.clear()
        for child in sorted(self.vms_dir.iterdir()):
            if not child.is_dir():
                continue
            name = child.name
            # Skip MuMu ARM base image folder (not a runnable phone instance).
            if name.lower() in {"base.gmadoa", "base"}:
                continue
            # Inject/Tor ports are 8218+N for vmN — never prefs enumerate order.
            # phone_order slots used to remap vm5→3 etc. and pin the wrong MITM lane.
            gmadoa_match = re.match(r"^vm(\d+)\.gmadoa$", name, re.IGNORECASE)
            if gmadoa_match:
                idx = int(gmadoa_match.group(1))
            elif name in index_map:
                idx = index_map[name]
            else:
                while next_auto in index_map.values():
                    next_auto += 1
                idx = next_auto
                next_auto += 1

            serial = self._resolve_adb_serial(
                name,
                idx,
                live_devices,
                vm_path=child,
                claimed=claimed,
                mpid_map=mpid_map,
            )
            if serial:
                claimed.add(serial)
            online = bool(serial) and any(d.serial == serial and d.online for d in live_devices)

            inst = MuMuInstance(
                name=name,
                index=idx,
                vm_path=child,
                adb_serial=serial,
                running=online,
            )
            instances.append(inst)
            self.instances[name] = inst

        # Roster-less: phones registered from live ADB with no MuMu folder
        # (Android Studio AVD, docker containers, cloud) survive every rescan.
        for extra_name, extra in list(getattr(self, "_adb_only", {}).items()):
            if extra_name in self.instances:
                continue
            extra_online = bool(extra.adb_serial) and any(
                d.serial == extra.adb_serial and d.online for d in live_devices
            )
            if extra_online:
                extra.running = True
            if extra.adb_serial not in claimed:
                instances.append(extra)
                self.instances[extra_name] = extra

        # Roster = LIVE phones only. Syncing every disk folder made the farm
        # adopt 40+ ghost phones (no VM, no ADB), poisoned pharmflow_config.json
        # (phones=49), and blew the per-phone Tor/inject port mapping past the
        # live Tor fleet — the 2026-09-13 "48 ghosts, 8 real" incident.
        self._sync_phone_names([i.name for i in instances if i.running])
        return instances

    def _sync_phone_names(self, names: list[str]) -> None:
        """Keep config/prefs/groups aligned with live VM folder names."""
        if not names:
            return
        cfg = load_config()
        current = [str(x) for x in (cfg.get("phones") or [])]
        legacy = not current or all(re.match(r"^Phone(-\d+)?$", n, re.IGNORECASE) for n in current)
        mismatched = set(current) != set(names)
        count_mismatch = int(cfg.get("phone_count") or 0) != len(names)
        if legacy or mismatched or count_mismatch:
            try:
                save_config({"phones": names, "phone_count": len(names)})
                save_desktop_prefs(names)
                logger.info("Synced phone names to live VMs: %s", ", ".join(names))
            except Exception as exc:
                logger.warning("Could not sync phone names: %s", exc)
        self._repair_group_phone_names(names)

    def _repair_group_phone_names(self, live_names: list[str]) -> None:
        """Rewrite groups.json phone lists that still use Phone-N or bogus names."""
        path = app_data_root() / "groups.json"
        if not path.is_file() or not live_names:
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if not isinstance(raw, dict):
            return
        live_set = set(live_names)
        changed = False
        for gname, g in raw.items():
            if not isinstance(g, dict):
                continue
            phones = g.get("phones")
            if not isinstance(phones, list) or not phones:
                continue
            fixed: list[str] = []
            for p in phones:
                name = str(p).strip()
                if name in live_set:
                    fixed.append(name)
                    continue
                match = re.match(r"^Phone-?(\d+)$", name, re.IGNORECASE)
                if match:
                    idx = int(match.group(1)) - 1
                    if 0 <= idx < len(live_names):
                        fixed.append(live_names[idx])
                        changed = True
                        continue
                # Ignore junk like "1-4"
                changed = True
            # Dedupe while preserving order
            seen: set[str] = set()
            cleaned: list[str] = []
            for n in fixed:
                if n not in seen:
                    seen.add(n)
                    cleaned.append(n)
            if not cleaned and gname == "default":
                cleaned = list(live_names)
                changed = True
            if cleaned != phones:
                g["phones"] = cleaned
                changed = True
                # Drop stale phone_entries keys that are not live
                entries = g.get("phone_entries")
                if isinstance(entries, dict):
                    g["phone_entries"] = {k: v for k, v in entries.items() if k in live_set or k in cleaned}
        if changed:
            try:
                path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
                logger.info("Repaired group phone names to match live VMs")
            except OSError as exc:
                logger.warning("Could not repair groups.json: %s", exc)

    def get_phone(self, name: str) -> MuMuInstance | None:
        """Return a phone instance, refreshing the registry first."""
        with self._instances_lock:
            self._list_instances_unlocked()
            if name in self.instances:
                return self.instances[name]
            # Legacy aliases: Phone-1 -> first VM, Phone-2 -> second, â€¦
            match = re.match(r"^Phone-?(\d+)$", name, re.IGNORECASE)
            if match:
                idx = int(match.group(1)) - 1
                ordered = sorted(self.instances.values(), key=lambda i: i.index)
                if 0 <= idx < len(ordered):
                    return ordered[idx]
            return None

    def read_phone(self, name: str) -> dict[str, Any]:
        """Read full status for one phone."""
        return self.get_phone_status(name)

    # ------------------------------------------------------------------
    # Phone CRUD
    # ------------------------------------------------------------------

    def create_phone(
        self,
        name: str,
        width: int = MUMU_DEFAULT_WIDTH,
        height: int = MUMU_DEFAULT_HEIGHT,
        dpi: int = MUMU_DEFAULT_DPI,
    ) -> MuMuInstance:
        """Create a new MuMu instance: portrait 900x1600, USB debugging enabled."""
        result = self._run_manager(
            "api", "create", f"--name={name}",
            f"--resolution={width},{height},{dpi}",
            "--orientation=1",  # portrait
        )
        if result.returncode != 0:
            logger.warning("MuMuManager create returned %d: %s", result.returncode, result.stderr)
            if self._is_arm_backend():
                raise RuntimeError(
                    f"Cannot create {name!r} via CLI on MuMu ARM â€” create the VM in MuMu Manager first"
                )
            # Fallback: create VM directory structure manually for dev/testing (classic only)
            if self.vms_dir:
                vm_path = self.vms_dir / name
                vm_path.mkdir(parents=True, exist_ok=True)
                setting = vm_path / "setting.json"
                if not setting.exists():
                    setting.write_text(json.dumps({
                        "resolution_width": width,
                        "resolution_height": height,
                        "resolution_dpi": dpi,
                        "orientation": 1,
                    }, indent=2))

        instances = self.list_instances()
        inst = next((i for i in instances if i.name == name), None)
        if not inst:
            idx = len(instances)
            vm_path = (self.vms_dir or Path("vms")) / name
            inst = MuMuInstance(name=name, index=idx, vm_path=vm_path, width=width, height=height)
            self.instances[name] = inst

        inst.width = width
        inst.height = height
        self._enable_usb_debugging_config(inst)
        self._apply_farm_guest_rails(inst)
        return inst

    def _apply_farm_guest_rails(self, inst: MuMuInstance) -> None:
        """Rooted phone (not tablet), writable disk, lean CPU/RAM — PharmFlow.exe create path."""
        vm = find_vm_dir(self.vms_dir or inst.vm_path.parent, inst.name)
        if vm:
            notes = apply_farm_guest_rails_vm(vm)
            if notes:
                logger.info("Farm guest rails applied: %s %s", inst.name, notes[:4])
                return
        setting_path = find_setting_json(self.vms_dir or inst.vm_path.parent, inst.name)
        if setting_path and apply_farm_guest_rails_file(setting_path):
            logger.info("Farm guest rails applied: %s", inst.name)
        else:
            logger.warning("Farm guest rails missing VM files for %s", inst.name)

    def _enable_usb_debugging_config(self, inst: MuMuInstance) -> None:
        """Pre-enable USB debugging in setting.json where supported."""
        setting_path = find_setting_json(self.vms_dir or inst.vm_path.parent, inst.name)
        if setting_path and setting_path.is_file():
            try:
                data = json.loads(setting_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                data = {}
            if not isinstance(data, dict):
                data = {}
            data["adb_debug"] = 1
            data["usb_debugging"] = True
            data["DeviceRoot"] = True
            setting_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def start_phone(self, name: str) -> bool:
        """Start an emulator instance and wait for its live ADB serial."""
        if self._is_arm_backend():
            # Serial boot guarantee — never mass-launch concurrent ARM VMs.
            with _ARM_BOOT_LOCK:
                return self._start_phone_arm(name)
        result = self._run_manager("api", "launch", f"--name={name}")
        inst = self.get_phone(name)
        if inst:
            self.adb.wait_for_device(inst.adb_serial, timeout=90.0)
            self.refresh_serials()
            inst = self.get_phone(name)
            if inst:
                inst.running = True
        return result.returncode == 0

    def _reconnect_known_serials(self) -> int:
        """Reconnect every known ARM serial after an adb server restart.

        ``adb kill-server`` destroys every TCP transport; without a re-connect
        pass every phone looks offline and the farm spins healthy VMs. Gather
        serials from state.json AdbHost (ground truth) + the lock map + each
        instance's live serial, then adb-connect each under a bounded budget.
        Returns how many connected.
        """
        candidates: list[str] = []
        try:
            for name in list(self.instances.keys()):
                arm = self._arm_adb_serial_from_state(name)
                if arm and arm not in candidates:
                    candidates.append(arm)
        except Exception:
            pass
        try:
            log_dir = Path(os.environ.get("PHARMFLOW_LOG_DIR", r"C:\PharmFlow\logs"))
            lock_path = log_dir / "ADB_SERIAL_MAP.lock.json"
            if lock_path.is_file():
                data = json.loads(lock_path.read_text(encoding="utf-8-sig"))
                for v in list((data.get("phones") or {}).values()):
                    s = str(v or "").strip()
                    if s and s not in candidates:
                        candidates.append(s)
        except Exception:
            pass
        ok = 0
        for serial in candidates:
            try:
                r = self.adb.connect(serial, timeout=6.0)
                if r.ok or "already connected" in (r.stdout or "").lower():
                    ok += 1
            except Exception:
                continue
        if candidates:
            logger.info("adb reconnect pass: %d/%d known serials answered", ok, len(candidates))
        return ok

    def _arm_usable_serial(self, name: str, inst: MuMuInstance | None) -> str:
        """Prefer state.json AdbHost; never treat classic localhost as ARM serial."""
        arm = self._arm_adb_serial_from_state(name)
        if arm:
            return arm
        ser = str(inst.adb_serial if inst else "").strip()
        if ser.startswith("127.0.0.1:"):
            return ""
        return ser

    def _start_phone_arm(self, name: str) -> bool:
        """Cold/warm start one MuMu ARM VM; wait ARM-realistic ADB timeouts."""
        from automation.mumu_shell_cli import (
            instance_shell_running,
            launch_instance_index,
            phone_vm_index,
        )

        self.refresh_serials()
        inst = self.get_phone(name)
        idx = phone_vm_index(name, inst.index if inst else 0)
        serial = self._arm_usable_serial(name, inst)
        if serial and inst:
            inst.adb_serial = serial
            if inst.config is not None:
                inst.config.adb_serial = serial

        # Warm path: already online — 45s is enough to confirm, not 12s.
        if serial and self.adb.wait_for_device(serial, timeout=_ARM_ADB_WAIT_ALREADY_S):
            if inst:
                inst.running = True
            return True

        # An empty ADB listing is not proof the server is wedged. kill-server
        # drops every phone the farm is already using, including ones this
        # client failed to list. Reconnect known serials. Do not restart ADB.
        if not instance_shell_running(idx):
            try:
                self._reconnect_known_serials()
            except Exception as exc:
                logger.warning("adb reconnect before ARM start failed: %s", exc)
            serial2 = self._arm_usable_serial(name, inst)
            if serial2 and self.adb.wait_for_device(serial2, timeout=_ARM_ADB_WAIT_ALREADY_S):
                if inst:
                    inst.running = True
                return True

        # Shell already up (slow Snapdragon boot) — wait, do NOT re-launch.
        if instance_shell_running(idx):
            logger.info(
                "ARM start: shell already running idx=%s name=%s — waiting for ADB",
                idx,
                name,
            )
            return self._wait_arm_adb(name, timeout=_ARM_ADB_WAIT_AFTER_LAUNCH_S)

        logger.info(
            "ARM start: single-VM shell launch idx=%s name=%s (no mass restart)",
            idx,
            name,
        )
        ok, _detail = launch_instance_index(idx, timeout=120.0)
        if not ok and not instance_shell_running(idx):
            return False
        # Cold boot on Snapdragon often needs 2–4 min before AdbHost is live.
        return self._wait_arm_adb(name, timeout=_ARM_ADB_WAIT_AFTER_LAUNCH_S)

    def _wait_arm_adb(self, name: str, *, timeout: float) -> bool:
        """Poll state.json AdbHost + wait_for_device until online or deadline."""
        deadline = time.monotonic() + max(30.0, float(timeout))
        while time.monotonic() < deadline:
            self.refresh_serials()
            inst = self.get_phone(name)
            serial = self._arm_usable_serial(name, inst)
            if serial:
                if inst:
                    inst.adb_serial = serial
                    if inst.config is not None:
                        inst.config.adb_serial = serial
                slice_s = min(20.0, max(5.0, deadline - time.monotonic()))
                if self.adb.wait_for_device(serial, timeout=slice_s):
                    if inst:
                        inst.running = True
                    return True
            else:
                time.sleep(5.0)
        return False

    def bootstrap_phone(self, name: str) -> None:
        """Connect ADB, start phone, apply fingerprint, and configure Tor."""
        self.connect_adb(name)
        self.start_phone(name)
        self.patch_fingerprint(name)
        self.setup_tor(name)

    def stop_phone(self, name: str) -> bool:
        """Stop an emulator instance."""
        if self._is_arm_backend():
            logger.info("ARM stop: use MuMu Manager UI for %s â€” marking stopped locally", name)
            inst = self.instances.get(name)
            if inst:
                inst.running = False
            return False
        result = self._run_manager("api", "shutdown", f"--name={name}")
        inst = self.instances.get(name)
        if inst:
            inst.running = False
        return result.returncode == 0

    def cold_boot(self, name: str) -> bool:
        """Stop and restart so a fingerprint patch is visible in getprop.

        ARM MuMu has no manager CLI for this. Power the VM off and on from the
        MuMu window. A True return used to claim a reboot that did not happen.
        """
        if self._is_arm_backend():
            logger.info(
                "ARM cold_boot skipped for %s (no manager CLI). "
                "Patch applies on the next restart from the MuMu window.",
                name,
            )
            return False
        self.stop_phone(name)
        time.sleep(3.0)
        return self.start_phone(name)

    def enable_usb_debugging_ui(self, name: str, taps: int = 7) -> None:
        """Enable developer mode by tapping Build number 7 times via ADB."""
        inst = self.instances.get(name)
        if not inst:
            raise KeyError(f"Unknown instance: {name}")
        self.adb.enable_usb_debugging_taps(inst.adb_serial, taps=taps)
        # Enable USB debugging toggle (approximate coordinates)
        self.adb.shell("am start -a android.settings.APPLICATION_DEVELOPMENT_SETTINGS", serial=inst.adb_serial)
        time.sleep(1.0)
        self.adb.tap(450, 600, serial=inst.adb_serial)  # USB debugging toggle

    def patch_fingerprint(self, name: str, profile: FingerprintProfile | None = None) -> FingerprintProfile:
        """Patch setting.json â€” setup wizard only when browser-only identity is disabled."""
        if is_browser_only_identity():
            logger.info("Browser-only identity â€” skipping MuMu VM patch for %s", name)
            prof = profile or random_profile()
            self._profiles[name] = prof
            inst = self.instances.get(name)
            if inst:
                inst.fingerprint = prof
            return prof
        if is_skip_fingerprint():
            logger.info("Skipping fingerprint for %s", name)
            return profile or random_profile()
        if not self.vms_dir:
            raise RuntimeError("vms directory not found")
        prof = profile or random_profile()

        def shell_fn(cmd: str) -> str:
            inst = self.instances.get(name)
            if inst:
                return self.adb.shell(cmd, serial=inst.adb_serial).stdout
            return ""

        apply_fingerprint(self.vms_dir, name, prof, shell_fn=shell_fn if self.instances.get(name) else None)
        self._profiles[name] = prof
        inst = self.instances.get(name)
        if inst:
            inst.fingerprint = prof
        return prof

    def rotate_identity(self, name: str) -> FingerprintProfile:
        """Scramble browser session; Tor rotate with verified unique exit IP when required."""
        from automation.browser_farm import scramble_for_sequence
        from automation.browse_proxy import (
            browser_package_for_serial,
            dabflow_browse_active,
            restore_inject_after_identity,
        )
        from automation.config import require_unique_exit_ip

        inst = self.instances.get(name) or self.get_phone(name)
        if is_browser_only_identity():
            # scramble_for_sequence handles Tor + verified unique exit IP when required.
            scramble_for_sequence(self, name)
            # Hard restore inject after scramble's :0 clear (Chromium mid-seq).
            try:
                inst = self.instances.get(name) or self.get_phone(name)
                if inst and inst.adb_serial:
                    pkg = browser_package_for_serial(inst.adb_serial)
                    restore_inject_after_identity(
                        self.adb,
                        inst.adb_serial,
                        int(getattr(inst, "index", 0) or 0),
                        browser_package=pkg,
                    )
            except Exception as exc:
                logger.warning("[%s] rotate_identity inject restore soft-fail: %s", name, exc)
            return self._profiles.get(name) or random_profile()

        if not self.vms_dir:
            raise RuntimeError("vms directory not found")
        prof = rotate_fingerprint(self.vms_dir, name)
        self._profiles[name] = prof
        if self._is_arm_backend():
            logger.info(
                "ARM rotate: patched setting.json for %s (cold boot via MuMu UI for full getprop)",
                name,
            )
        else:
            self.cold_boot(name)
        self.refresh_serials()
        inst = self.instances.get(name) or self.get_phone(name)
        if inst:
            if not self.adb.wait_for_device(inst.adb_serial, timeout=_ARM_ADB_WAIT_AFTER_LAUNCH_S):
                logger.warning("Device %s not online after rotate", inst.adb_serial)

            def shell_fn(cmd: str) -> str:
                return self.adb.shell(cmd, serial=inst.adb_serial).stdout

            apply_fingerprint(self.vms_dir, name, prof, shell_fn=shell_fn)
            want_unique = require_unique_exit_ip()
            # Clearing the guest proxy after rotate sent traffic out the VM/host.
            # Re-apply that phone's Tor exit instead.
            try:
                self.setup_tor(name)
                ip_result = self.tor.ensure_unique_exit_ip(inst.index, inst.adb_serial)
                self._last_exit_ip_rotate = ip_result
                logger.info("[%s] %s", name, ip_result.log_line())
                if want_unique and not ip_result.ok:
                    raise RuntimeError(
                        f"exit IP not unique after rotate ({ip_result.log_line()})"
                    )
            except Exception as exc:
                logger.warning("Tor re-setup after rotate failed for %s: %s", name, exc)
                if want_unique:
                    raise
            # Always re-pin inject for Chromium after rotate (never leave :0/null).
            try:
                pkg = browser_package_for_serial(inst.adb_serial)
                restore_inject_after_identity(
                    self.adb,
                    inst.adb_serial,
                    int(getattr(inst, "index", 0) or 0),
                    browser_package=pkg,
                )
            except Exception as exc:
                logger.warning("[%s] rotate_identity inject restore soft-fail: %s", name, exc)
        return prof

    def ensure_fingerprint_before_browse(self, name: str) -> FingerprintProfile:
        """Apply fingerprint before open_url â€” requires cold boot if changed."""
        return ensure_fingerprint_before_browse_impl(self, name)

    def setup_tor(self, name: str) -> None:
        """Start Tor circuit and configure adb reverse for one phone."""
        inst = self.instances.get(name)
        if not inst:
            raise KeyError(f"Unknown instance: {name}")
        self.tor.start_phone_tor(inst.index, inst.adb_serial)

    def get_runtime_resolution(self, name: str) -> tuple[int, int]:
        """Query device wm size (Override) for coordinate scaling â€” not browser viewport."""
        from automation.display_resolution import parse_size_wh, read_wm_size

        inst = self.instances.get(name)
        if not inst:
            return MUMU_DEFAULT_WIDTH, MUMU_DEFAULT_HEIGHT
        size = read_wm_size(self.adb, inst.adb_serial)
        wh = parse_size_wh(size)
        if wh:
            w, h = wh
            inst.config = inst.config or PhoneConfig(name=name, index=inst.index)
            if inst.config:
                inst.config.runtime_width = w
                inst.config.runtime_height = h
            return w, h
        return inst.width, inst.height

    def scale_coordinates(
        self,
        x: int,
        y: int,
        name: str,
        author_w: int = MUMU_DEFAULT_WIDTH,
        author_h: int = MUMU_DEFAULT_HEIGHT,
    ) -> tuple[int, int]:
        """Scale coordinates from authored 900x1600 to runtime resolution."""
        rw, rh = self.get_runtime_resolution(name)
        sx = int(x * rw / author_w)
        sy = int(y * rh / author_h)
        return sx, sy


    def _arm_adb_serial_from_state(self, name: str) -> str:
        """MuMu ARM publishes guest ADB as AdbHost:AdbPort in misc/state.json."""
        if not self.vms_dir:
            return ""
        state_path = Path(self.vms_dir) / name / "misc" / "state.json"
        if not state_path.is_file():
            return ""
        try:
            raw = state_path.read_text(encoding="utf-8-sig")
            data = json.loads(raw)
            host = str(data.get("AdbHost") or "").strip()
            port = data.get("AdbPort") or 5555
            if host:
                return f"{host}:{int(port)}"
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            return ""
        return ""

    def register_serial_phone(self, name: str, serial: str) -> bool:
        """Register a live ADB device that has no MuMu VM folder as a phone.

        Roster-less adoption: docker containers, Android Studio AVDs and cloud
        devices are farmed under a synthetic name bound to their serial. The
        entry lives in ``self._adb_only`` so every ``list_instances`` rescan
        (which rebuilds from the vms dir) keeps it.
        """
        name = str(name or "").strip()
        serial = str(serial or "").strip()
        if not name or not serial:
            return False
        if not hasattr(self, "_adb_only"):
            self._adb_only = {}
        with self._instances_lock:
            existing = self.instances.get(name) if hasattr(self, "instances") else None
            if existing is None and self._adb_only.get(name):
                existing = self._adb_only[name]
            if existing is not None and existing.adb_serial == serial:
                return True
            idx = 8000 + len(self._adb_only)
            inst = MuMuInstance(name=name, index=idx, vm_path=Path("adb"), adb_serial=serial)
            self._adb_only[name] = inst
            if hasattr(self, "instances"):
                self.instances[name] = inst
        return True

    def connect_adb(self, name: str) -> bool:
        """Ensure ADB is connected to the phone's current serial."""
        inst = self.get_phone(name)
        if not inst:
            return False
        candidates: list[str] = []
        arm_serial = self._arm_adb_serial_from_state(name)
        if arm_serial:
            candidates.append(arm_serial)
        if inst.adb_serial:
            candidates.append(inst.adb_serial)
        ordered: list[str] = []
        for serial in candidates:
            if serial and serial not in ordered:
                ordered.append(serial)
        for serial in ordered:
            if ":" not in serial:
                continue
            result = self.adb.connect(serial)
            if result.ok or "already connected" in (result.stdout or "").lower():
                inst.adb_serial = serial
                if inst.config is not None:
                    inst.config.adb_serial = serial
                return True
        if ordered:
            result = self.adb.run("connect", ordered[0])
            ok = result.ok or "already connected" in (result.stdout or "").lower()
            if ok:
                inst.adb_serial = ordered[0]
            return ok
        return False

    def adb_for_phone(self, name: str) -> AdbWrapper | None:
        """Return an ADB wrapper bound to one phone's live serial."""
        inst = self.get_phone(name)
        if not inst:
            return None
        return self.adb.for_phone(inst.adb_serial)

    def get_phone_status(self, name: str) -> dict[str, Any]:
        """Return comprehensive status for dashboard."""
        inst = self.get_phone(name)
        if not inst:
            return {"name": name, "error": "not found"}
        live = self.enumerate_adb_devices()
        connected = any(d.serial == inst.adb_serial and d.online for d in live)
        inst.running = connected
        fp = self._profiles.get(name, inst.fingerprint)
        fp_data: dict[str, Any] | None = None
        if fp is not None:
            fp_data = asdict(fp) if hasattr(fp, "__dataclass_fields__") else {"value": str(fp)}
        return {
            "name": name,
            "index": inst.index,
            "adb_serial": inst.adb_serial,
            "running": inst.running,
            "connected": connected,
            "resolution": f"{inst.width}x{inst.height}",
            "fingerprint": fp_data,
            "tor_port": inst.config.tor_http_port if inst.config else None,
        }

    def get_all_phone_statuses(self) -> list[dict[str, Any]]:
        """Status for every instance using one cached ADB devices call."""
        live = self.enumerate_adb_devices()
        online = {d.serial for d in live if d.online}
        out: list[dict[str, Any]] = []
        for inst in self.list_instances():
            connected = bool(inst.adb_serial) and inst.adb_serial in online
            inst.running = connected
            fp = self._profiles.get(inst.name, inst.fingerprint)
            fp_data: dict[str, Any] | None = None
            if fp is not None:
                fp_data = asdict(fp) if hasattr(fp, "__dataclass_fields__") else {"value": str(fp)}
            out.append(
                {
                    "name": inst.name,
                    "index": inst.index,
                    "adb_serial": inst.adb_serial,
                    "running": inst.running,
                    "connected": connected,
                    "resolution": f"{inst.width}x{inst.height}",
                    "fingerprint": fp_data,
                    "tor_port": inst.config.tor_http_port if inst.config else None,
                }
            )
        return out

    def delete_phone(self, name: str) -> bool:
        """Delete a MuMu VM instance."""
        result = self._run_manager("api", "delete", f"--name={name}")
        self.instances.pop(name, None)
        self._profiles.pop(name, None)
        return result.returncode == 0

    def verify_antidetect(self, name: str) -> AntiDetectionReport:
        """Layer 6: Runtime anti-detection verification via getprop."""
        inst = self.instances.get(name)
        if not inst:
            return AntiDetectionReport(phone=name, passed=False, checks={}, props={}, failures=["not found"])
        profile = self._profiles.get(name)

        def getprop(p: str) -> str:
            return self.adb.getprop(p, serial=inst.adb_serial)

        return verify_anti_detection(getprop, profile, phone=name)

    def verify_all_antidetect(self) -> list[dict[str, Any]]:
        """Verify anti-detection on all phones."""
        return [self.verify_antidetect(i.name).to_dict() for i in self.list_instances()]

    def get_tor_ip_hint(self, name: str) -> str:
        inst = self.instances.get(name)
        if not inst:
            return ""
        port = inst.config.tor_http_port if inst.config else 8118 + inst.index
        return f"127.0.0.1:{port}"
