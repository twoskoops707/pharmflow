"""
Backend for phone setup — preflight, ADB discovery, fingerprint, groups.

UI: embedded in PharmFlow.exe step 4 (``cpharm_app``) via ``MuMuSetupApi``;
legacy standalone ``cpharm_mumu_setup.py`` / ``mumu_setup_webview.py`` for dev only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

_wizard_dir = Path(__file__).resolve().parent
if str(_wizard_dir) not in sys.path:
    sys.path.insert(0, str(_wizard_dir))

import mumu_farm_ops as farm  # noqa: E402
import preflight_core as preflight  # noqa: E402
from wizard_paths import (  # noqa: E402
    cpharm_default_install_root,
    cpharm_install_root,
    has_automation_dashboard,
)

LogFn = Callable[[str], None]

_CORE_NO_AD = "900x1600/no-ad/dabflow__demo__ONE.json"
_NO_AD_VARIANTS = [
    "900x1600/no-ad/dabflow__no_ads__mat-quartz__conc-shatter__heat-butane.json",
    "900x1600/no-ad/dabflow__no_ads__mat-quartz__conc-wax__heat-propane.json",
    "900x1600/no-ad/dabflow__no_ads__mat-titanium__conc-live-resin__heat-butane.json",
    "900x1600/no-ad/dabflow__no_ads__mat-ceramic__conc-rosin__heat-propane.json",
    "900x1600/no-ad/dabflow__no_ads__mat-quartz__conc-diamonds__heat-butane.json",
    "900x1600/no-ad/dabflow__no_ads__mat-titanium__conc-budder__heat-propane.json",
]
_AD = "900x1600/ad/dabflow__demo__TWO.json"


def automation_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        bundled = Path(sys._MEIPASS) / "automation"
        if bundled.is_dir():
            return bundled
    return _wizard_dir.parent / "automation"


def ensure_automation_importable() -> None:
    ap = str(automation_dir())
    if ap not in sys.path:
        sys.path.insert(0, ap)


def exe_dir() -> Path:
    return cpharm_default_install_root()


def data_root() -> Path:
    try:
        root = cpharm_install_root()
    except Exception:
        root = exe_dir()
    if has_automation_dashboard(root):
        return root
    home_clone = Path.home() / "CPharm"
    if has_automation_dashboard(home_clone):
        return home_clone
    return exe_dir()


def cpharm_exe_path() -> Path:
    """Primary app exe beside this program — PharmFlow.exe, else legacy CPharm.exe."""
    folder = exe_dir()
    primary = folder / "PharmFlow.exe"
    if primary.is_file():
        return primary
    return folder / "CPharm.exe"


def launch_env() -> dict[str, str]:
    env = dict(os.environ)
    root = data_root()
    if has_automation_dashboard(root):
        env["CPHARM_HOME"] = str(root)
    return env


def adb_devices() -> list[str]:
    ensure_automation_importable()
    if not preflight.adb_usable():
        preflight.download_platform_tools()
    phones = preflight.discover_adb_phones(connect_mumu=True)
    return farm.order_farm_serials(phones)


def get_checklist() -> list[dict]:
    return preflight.build_checklist(data_root())


def run_check_action(action: str, log: LogFn | None = None) -> dict:
    result = preflight.run_check_action(action, log_fn=log)
    if action == "refresh":
        phones = farm.order_farm_serials(result.get("phones") or [])
        result["phones"] = phones
        result["phone_count"] = len(phones)
    return result


def _groups_config_path(install_root: Path) -> Path:
    """Live groups file. Do not append automation/recordings onto a recordings dir."""
    from wizard_paths import (
        _groups_file_for_root,
        groups_config_path,
        is_nested_recordings_path,
    )

    live = groups_config_path()
    if live.is_file() and not is_nested_recordings_path(live):
        return live
    cand = _groups_file_for_root(install_root)
    if cand is not None and not is_nested_recordings_path(cand):
        return cand
    return live


def should_seed_groups(install_root: Path) -> bool:
    """Do not stomp hand-edited groups unless forced or first-run."""
    if os.environ.get("CPHARM_FORCE_RESEED_GROUPS", "").strip().lower() in ("1", "true", "yes"):
        return True
    gp = _groups_config_path(install_root)
    if not gp.is_file():
        return True
    try:
        data = json.loads(gp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    note = str(data.get("_note") or "")
    groups = data.get("groups")
    if not groups:
        return True
    # Spawned Tk windows once saved empty phones{} — treat as corrupt and reseed.
    if "Written by CPharm" in note or "CPharmMuMuSetup" in note:
        for g in groups:
            if not isinstance(g, dict):
                continue
            phones = g.get("phones")
            if not isinstance(phones, dict) or not phones:
                return True
    return False


def repair_groups_if_empty(
    serials: list[str] | None = None,
    install_root: Path | None = None,
    *,
    force: bool = False,
) -> Path | None:
    """Ensure groups_config has every adb phone with default playlists."""
    root = install_root or data_root()
    if serials is None:
        serials = adb_devices()
    if not serials:
        return None
    gp = _groups_config_path(root)
    needs = force
    if not needs and gp.is_file():
        try:
            data = json.loads(gp.read_text(encoding="utf-8"))
            for g in data.get("groups") or []:
                if not isinstance(g, dict):
                    continue
                phones = g.get("phones")
                if not isinstance(phones, dict) or not phones:
                    needs = True
                    break
        except (OSError, json.JSONDecodeError):
            needs = True
    else:
        needs = True
    if needs:
        return write_groups_config(serials, root, force=True)
    return gp if gp.is_file() else None


def write_groups_config(serials: list[str], install_root: Path, *, force: bool = False) -> Path | None:
    if not force and not should_seed_groups(install_root):
        return None
    serials = [str(s).strip() for s in serials if str(s or "").strip()]
    if not serials:
        return None
    phones = {
        s: farm.phone_playlist_entry(i, extended_ad=True)
        for i, s in enumerate(serials)
    }
    cfg = {
        "_note": "Written by CPharm",
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
    out = _groups_config_path(install_root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return out


def write_desktop_prefs(
    serials: list[str],
    install_root: Path,
    *,
    setup_complete: bool,
    awaiting_cold_boot: bool | None = None,
) -> Path:
    rec = install_root / "automation" / "recordings"
    rec.mkdir(parents=True, exist_ok=True)
    prefs = rec / "desktop_prefs.json"
    existing = read_setup_prefs(install_root)
    existing.update(
        {
            "tor_proxy_configured": existing.get("tor_proxy_configured", False),
            "phone_serials": serials,
            "mumu_setup_complete": setup_complete,
            "mask_emulator_fingerprint": existing.get("mask_emulator_fingerprint", True),
            "dabflow_mantis_patch": existing.get("dabflow_mantis_patch", True),
            "mumu_setup_at": (
                datetime.now(timezone.utc).isoformat()
                if setup_complete
                else existing.get("mumu_setup_at")
            ),
            "browse_proxy_mode": existing.get("browse_proxy_mode", "scramble"),
            "phone_upstream_proxies": existing.get("phone_upstream_proxies", []),
            "note": "Phone order for Tor/upstream slots. Default browse mode: scramble (best ad fill on MuMu).",
        }
    )
    if awaiting_cold_boot is not None:
        existing["mumu_awaiting_cold_boot"] = awaiting_cold_boot
        if awaiting_cold_boot:
            existing["mumu_cold_boot_requested_at"] = datetime.now(timezone.utc).isoformat()
        else:
            existing.pop("mumu_cold_boot_requested_at", None)
    prefs.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return prefs


def launch_cpharm() -> tuple[bool, str]:
    try:
        from phone_setup_entry import is_unified_cpharm, skip_launch_cpharm_after_setup

        if skip_launch_cpharm_after_setup() or is_unified_cpharm():
            return True, (
                "Phones are ready. Next: Test (step 5) → Steps → Teams → Run (step 9)."
            )
    except Exception:
        if "--phone-setup" in sys.argv:
            return True, (
                "Phones are ready. Next: Test (step 5) → Steps → Teams → Run (step 9)."
            )
    cpharm = cpharm_exe_path()
    if not cpharm.is_file():
        return False, (
            "PharmFlow.exe not found next to this program:\n"
            f"  {cpharm.parent}\n"
            "Download PharmFlow.exe from the GitHub release into that folder."
        )
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    subprocess.Popen(
        [str(cpharm)],
        cwd=str(cpharm.parent),
        env=launch_env(),
        creationflags=flags,
    )
    return True, str(cpharm)


_COLD_BOOT_MSG = (
    "STOP — cold-boot each MuMu phone before we continue.\n\n"
    "In MuMu Multi-instance:\n"
    "  1. Click STOP on every phone (fully shut down — not just home screen).\n"
    "  2. Wait a few seconds.\n"
    "  3. Click START on each phone — wait for Android home.\n"
    "  4. Click Set up my phones again.\n\n"
    "PharmFlow will NOT open until phones pass this check."
)

_BROWSER_RETRY_MSG = (
    "Chromium/browser missing on some phones.\n"
    "{details}\n\n"
    "Click Install Chromium on all phones, then Set up my phones again."
)

_SEQUENCES_MISSING_MSG = (
    "Sequence files missing on this PC.\n\n"
    "In PharmFlow run Install (step 2), then open Phones (step 4) and click Set up my phones again.\n"
    "Or copy the repo sequences/ folder to:\n"
    "  %USERPROFILE%\\CPharm\\sequences\n\n"
    "Missing: {sample}{more}"
)


def _prefs_path(install_root: Path) -> Path:
    return install_root / "automation" / "recordings" / "desktop_prefs.json"


def read_setup_prefs(install_root: Path) -> dict:
    p = _prefs_path(install_root)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_setup_prefs(install_root: Path, **fields: object) -> Path:
    p = _prefs_path(install_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = read_setup_prefs(install_root)
    data.update(fields)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return p


def setup_awaiting_cold_boot(install_root: Path | None = None) -> bool:
    root = install_root or data_root()
    return bool(read_setup_prefs(root).get("mumu_awaiting_cold_boot"))


def go_button_label() -> str:
    root = data_root()
    prefs = read_setup_prefs(root)
    if setup_awaiting_cold_boot(root):
        return "Phones restarted — set up again"
    if str(prefs.get("mumu_setup_phase") or "") == "browser_retry":
        return "Try phone setup again"
    return "Set up my phones"


def _sync_local_sequences(log: LogFn) -> dict:
    """Copy shipped ``sequences/`` into ``~/CPharm/sequences`` for the dashboard."""
    from sequences_sync import sync_shipped_sequences

    return sync_shipped_sequences(log=log)


def _sequences_missing_message(missing: list[str]) -> str:
    sample = missing[0] if missing else "(unknown)"
    more = f" (+{len(missing) - 1} more)" if len(missing) > 1 else ""
    return _SEQUENCES_MISSING_MSG.format(sample=sample, more=more)


def initial_state() -> dict:
    root = data_root()
    exe_ok, exe_path = preflight.cpharm_exe_beside_setup()
    awaiting = setup_awaiting_cold_boot(root)
    if not preflight.list_adb_phones():
        # View-load discovery must NEVER launch MuMu players and must never eat
        # the full connect storm — that wedges the deck right after phones get
        # linked ("stops working", Application Hang). Re-attach the farm's
        # known fleet only (bounded + self-healing in discover_adb_phones);
        # player launching stays with the explicit Check again / setup actions.
        try:
            preflight.discover_adb_phones(connect_mumu=False)
        except Exception:
            pass
    checklist = get_checklist()
    setup_done = preflight.mumu_setup_already_done(root)
    # Operator-only rows stay "manual" forever; warn/fail still block ready.
    _ready_skip = {"phones", "mumu_run", "usb"}
    ready = setup_done and not awaiting and all(
        (c.get("status") == "pass" or c.get("optional"))
        for c in checklist
        if c.get("id") not in _ready_skip and c.get("status") != "manual"
    )
    state = {
        "cpharm_found": exe_ok,
        "cpharm_path": str(exe_path),
        "data_root": str(root),
        "checklist": checklist,
        "setup_already_done": setup_done,
        "ready": ready,
        "awaiting_cold_boot": awaiting,
        "go_label": go_button_label(),
    }
    cleanup = globals().get("_STARTUP_CLEANUP_SUMMARY")
    if isinstance(cleanup, dict):
        state["startup_cleanup"] = cleanup
    return state


def run_setup_startup_cleanup(log: LogFn | None = None) -> dict:
    """Close stale MuMu/adb/CPharm before the setup UI opens."""
    from setup_startup_cleanup import run_setup_startup_cleanup as _run

    summary = _run(log=log)
    globals()["_STARTUP_CLEANUP_SUMMARY"] = summary
    return summary


def _no_phones_message() -> str:
    return (
        "No phones found yet.\n\n"
        "YOU do these (we cannot start MuMu for you):\n"
        "  1. Open MuMu Player on this PC.\n"
        "  2. Click Start on each phone — wait for Android home.\n"
        "  3. On each phone: Settings → Developer options → USB debugging ON.\n"
        "     (Leave USB debugging ON — PharmFlow needs it; websites still get disguised.)\n"
        "  4. If MuMu shows Root, leave Root ON.\n"
        "  5. Click Check again, then Set up my phones.\n\n"
        "Tip: If phone connection helper (adb) was red, click Fix first."
    )


def run_install_chromium(log: LogFn) -> dict:
    """Download ChromePublic.apk and sideload on every connected phone."""
    ensure_automation_importable()

    if not preflight.adb_usable():
        log("Installing phone connection tools (adb)…")
        if not preflight.download_platform_tools(log):
            return {"ok": False, "message": "Could not install adb. Click Fix on Step 3."}

    serials = adb_devices()
    if not serials:
        return {"ok": False, "message": _no_phones_message(), "serials": []}

    log(f"Found {len(serials)} phone(s) for Chromium install.")
    summary = farm.install_chromium_on_phones(serials, log)
    summary["serials"] = serials
    return summary


def run_full_setup(log: LogFn) -> tuple[bool, str, list[str]]:
    """
    Phased MuMu setup. Returns ``(ready, message, serials)``.

    ``ready=True`` only when phones are verified and CPharm may open.
    ``ready=False`` means stop (cold boot, missing phones, or fix needed) — do NOT launch CPharm.
    """
    ensure_automation_importable()
    root = data_root()
    prefs = read_setup_prefs(root)
    phase = str(prefs.get("mumu_setup_phase") or "")

    if not preflight.adb_usable():
        log("Installing phone connection tools (adb)…")
        if not preflight.download_platform_tools(log):
            return False, "Could not install adb. Check internet and click Fix on Step 3.", []

    serials = adb_devices()
    if not serials:
        log("Connecting to MuMu phones via adb…")
        serials = farm.order_farm_serials(
            preflight.discover_adb_phones(log, connect_mumu=True, force_mumu_scan=True)
        )
    if not serials:
        return False, _no_phones_message(), []

    log(f"Found {len(serials)} phone(s):")
    for i, s in enumerate(serials):
        log(f"  {i + 1}. {s}")

    awaiting = setup_awaiting_cold_boot(root)
    force_setup = os.environ.get("CPHARM_FORCE_SETUP", "").strip().lower() in ("1", "true", "yes")

    if (
        preflight.mumu_setup_already_done(root)
        and not awaiting
        and phase != "browser_retry"
        and not force_setup
    ):
        n_bad, _ = farm.phones_needing_cold_boot(serials)
        if n_bad == 0:
            log("")
            log("Phone Setup already completed — refreshing phones, masking, and sequences…")
            sync = _sync_local_sequences(log)
            if not sync.get("ok"):
                missing = list(sync.get("missing_playlists") or [])
                return False, _sequences_missing_message(missing), serials
            write_desktop_prefs(serials, root, setup_complete=True, awaiting_cold_boot=False)
            write_setup_prefs(root, mumu_setup_phase="complete")
            # Never force-reseed — hand-edited playlists must survive refresh.
            gp = repair_groups_if_empty(serials, root, force=False)
            if gp:
                log(f"  Updated groups: {gp}")
            log("")
            log("Clearing stale proxies and resetting screen size…")
            import browser_setup

            for serial in serials:
                browser_setup.configure_phone_baseline(serial, log)
            log("Re-applying browser fingerprint + emulator hide…")
            fp = farm.apply_fingerprint_all(serials, log, patch_vms=False)
            leaks = int(fp.get("leaks_total") or 0)
            if leaks:
                log(f"  {leaks} fingerprint warning(s) — cold-boot MuMu if ads fail.")
            log("  Phone order, masking, and sequences refreshed.")
            from phone_setup_entry import skip_launch_cpharm_after_setup

            if skip_launch_cpharm_after_setup():
                return True, "Already set up — phone settings and sequences refreshed.", serials
            return True, "Already set up — opening PharmFlow…", serials

    if awaiting:
        log("")
        log("Checking phones after MuMu cold boot…")
        n_bad, bad = farm.phones_needing_cold_boot(serials)
        if n_bad:
            log(f"  {n_bad} phone(s) still show old emulator VM settings:")
            for s in bad[:5]:
                log(f"    • {s}")
            write_desktop_prefs(serials, root, setup_complete=False, awaiting_cold_boot=True)
            write_setup_prefs(root, mumu_setup_phase="awaiting_cold_boot")
            return False, _COLD_BOOT_MSG, serials
        log("  Phones passed cold-boot check.")
        log("")
        log("Finishing setup (browser + Chromium + save settings)…")
        summary = farm.run_post_reboot_setup(serials, log)
    elif phase == "browser_retry":
        log("")
        log("Retry — browser/Chromium only (skipping VM patch)…")
        summary = farm.run_post_reboot_setup(serials, log)
    else:
        log("")
        log("Step 1 — MuMu VM profile (Pad→Phone + phone identity)…")
        vm_prep = farm.run_vm_prep_only(log)
        if vm_prep.get("needs_cold_boot"):
            write_desktop_prefs(serials, root, setup_complete=False, awaiting_cold_boot=True)
            write_setup_prefs(root, mumu_setup_phase="awaiting_cold_boot")
            log("")
            log("Stopping here — reboot phones before we install the browser or continue.")
            return False, _COLD_BOOT_MSG, serials

        n_bad, _ = farm.phones_needing_cold_boot(serials)
        if n_bad:
            write_desktop_prefs(serials, root, setup_complete=False, awaiting_cold_boot=True)
            write_setup_prefs(root, mumu_setup_phase="awaiting_cold_boot")
            log("")
            log("Phones still report emulator VM props — cold boot required.")
            return False, _COLD_BOOT_MSG, serials

        log("")
        log("No VM file changes — finishing setup in one pass…")
        summary = farm.run_post_reboot_setup(serials, log)

    browser_warnings: list[str] = list(summary.get("browser_warnings") or [])
    leaks = int(summary.get("leaks_total") or 0)

    if leaks:
        n_bad, _ = farm.phones_needing_cold_boot(serials)
        if n_bad:
            write_desktop_prefs(serials, root, setup_complete=False, awaiting_cold_boot=True)
            write_setup_prefs(root, mumu_setup_phase="awaiting_cold_boot")
            return False, _COLD_BOOT_MSG, serials

    if browser_warnings:
        write_desktop_prefs(serials, root, setup_complete=False, awaiting_cold_boot=False)
        write_setup_prefs(root, mumu_setup_phase="browser_retry")
        details = "\n".join(browser_warnings)
        return False, _BROWSER_RETRY_MSG.format(details=details), serials

    log("")
    log("Syncing DabFlow sequence files to this PC…")
    sync = _sync_local_sequences(log)
    if not sync.get("ok"):
        missing = list(sync.get("missing_playlists") or [])
        write_desktop_prefs(serials, root, setup_complete=False, awaiting_cold_boot=False)
        write_setup_prefs(root, mumu_setup_phase="browser_retry")
        return False, _sequences_missing_message(missing), serials

    log("")
    log("Saving tap lists for getdabflow.app…")
    try:
        gp = write_groups_config(serials, root)
        if gp:
            log(f"  Saved: {gp}")
        else:
            log("  Kept your existing groups file (already edited in PharmFlow).")
        write_desktop_prefs(serials, root, setup_complete=True, awaiting_cold_boot=False)
        write_setup_prefs(root, mumu_setup_phase="complete")
        log("  Phone Setup complete.")
        if has_automation_dashboard(root):
            log(f"  Data folder: {root}")
            log(f"  Sequences folder: {sync.get('dest')}")
        else:
            log(f"  Settings folder: {root / 'automation' / 'recordings'}")
            log(f"  Sequences folder: {sync.get('dest')}")
            log("  In PharmFlow: Install step downloads the rest (Java, Python, Tor).")
    except OSError as e:
        log(f"  Warning: could not save settings: {e}")
        return False, f"Could not save settings: {e}", serials

    if leaks:
        return (
            False,
            (
                f"{leaks} minor fingerprint warning(s) — if getdabflow blocks you, cold-boot and GO again."
            ),
            serials,
        )

    return True, "All phones ready. Opening PharmFlow…", serials
