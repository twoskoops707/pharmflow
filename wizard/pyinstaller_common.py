"""Shared PyInstaller configuration for PharmFlow wizard builds."""

from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.building.api import EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_all, collect_submodules

SPEC_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
ROOT = SPEC_DIR.parent

APP_VERSION = "1.5.0"
COMPANY_NAME = "PharmFlow"
PRODUCT_NAME = "PharmFlow Phone Farm"


def _existing_data_pairs() -> list[tuple[str, str]]:
    """Return (src, dest) data tuples only when source paths exist."""
    candidates: list[tuple[Path, str]] = [
        # Full source trees as DATA so the frozen EXE can spawn system pythonw on
        # scripts/run_farm_354.py and import automation.* / wizard.* from disk.
        # PYZ-only frozen modules are invisible to that external interpreter and
        # made the EXE's own farm driver crash ("Group iter FAIL") — the #1
        # "EXE can't run independently" bug. Duplicating sources into the bundle
        # costs size (~20 MB) but makes the money path fully self-contained.
        (ROOT / "automation", "automation"),
        (ROOT / "wizard", "wizard"),
        (ROOT / "scripts", "scripts"),
        (ROOT / "automation" / "recordings", "automation/recordings"),
        (ROOT / "automation" / "dabflow_mapping.json", "automation"),
        (ROOT / "scripts" / "run_farm_354.py", "scripts"),
        (ROOT / "scripts" / "run_farm_cycles.py", "scripts"),
        (ROOT / "scripts" / "cpharm_unison_supervisor.py", "scripts"),
        (ROOT / "scripts" / "cpharm_stealth_guard.py", "scripts"),
        (ROOT / "scripts" / "purge_farm_overrides.py", "scripts"),
        (ROOT / "scripts" / "farm_watchdog.py", "scripts"),
        (ROOT / "automation" / "cpharm_farm_config.py", "automation"),
        (ROOT / "automation" / "cpharm_farmbrowser_guard.py", "automation"),
        (ROOT / "automation" / "cpharm_unison_dedupe.py", "automation"),
        (ROOT / "scripts" / "farm_operator_dash.py", "scripts"),
        (ROOT / "scripts" / "farm_remediate_loop.py", "scripts"),
        (ROOT / "scripts" / "keep_farm_alive.py", "scripts"),
        (ROOT / "scripts" / "ssp_paying_hunter.py", "scripts"),
        (ROOT / "scripts" / "run_mantis_inject_proxies.py", "scripts"),
        (ROOT / "scripts" / "watch_bottom_ads.py", "scripts"),
        (ROOT / "scripts" / "ntfy_farm_responder.py", "scripts"),
        (ROOT / "scripts" / "ntfy_agent_wake.py", "scripts"),
        (ROOT / "scripts" / "farm_fail_review.py", "scripts"),
        (ROOT / "scripts" / "emu_keepalive.py", "scripts"),
        (ROOT / "scripts" / "farm_midnight_watch.py", "scripts"),
        (ROOT / "scripts" / "farm_pause_until.py", "scripts"),
        (ROOT / "scripts" / "farm_operator_monitor.py", "scripts"),
        (ROOT / "automation" / "farm_health_audit.py", "automation"),
        (ROOT / "automation" / "farm_phone_discover.py", "automation"),
        (ROOT / "automation" / "farm_money_monitor.py", "automation"),
        (ROOT / "automation" / "farm_pause.py", "automation"),
        (ROOT / "automation" / "display_resolution.py", "automation"),
        (ROOT / "automation" / "tablet_scheduler.py", "automation"),
        (ROOT / "automation" / "farm_sites.py", "automation"),
        (ROOT / "automation" / "farm_visit_caps.py", "automation"),
        (ROOT / "scripts" / "farm_hourly_ntfy.py", "scripts"),
        (ROOT / "scripts" / "sideload_farm_browsers.py", "scripts"),
        (ROOT / "scripts" / "generate_dabflow_sequences.py", "scripts"),
        (ROOT / "scripts" / "verify_browser_sequence.py", "scripts"),
        (ROOT / "scripts" / "probe_browser_open.py", "scripts"),
        (ROOT / "docs" / "multi_browser_sideload.md", "docs"),
        (ROOT / "docs" / "operator_sequence_quick_guide.md", "docs"),
        (ROOT / "docs" / "MANTIS_FARM_SEQUENCE_GUIDANCE.md", "docs"),
        (ROOT / "docs" / "MANTIS_FARM_DAILY_SCORECARD.md", "docs"),
        (ROOT / "docs" / "MANTIS_FARM_DESKTOP_CURSOR_SUMMARY.md", "docs"),
        (ROOT / "docs" / "superpowers" / "specs" / "2026-07-24-multi-browser-path12.md", "docs/superpowers/specs"),
        (ROOT / "wizard" / "icons", "wizard/icons"),
        (ROOT / "bundled_adb", "bundled_adb"),
        (ROOT / "tor", "tor"),
    ]
    pairs: list[tuple[str, str]] = []
    for src, dest in candidates:
        if src.is_file():
            pairs.append((str(src), dest))
        elif src.is_dir():
            pairs.append((str(src), dest))
    return pairs


def collect_package_assets() -> tuple[list, list, list]:
    """Collect datas, binaries, and hidden imports for bundled packages."""
    datas: list = []
    binaries: list = []
    hidden: list = []

    for package in ("customtkinter", "flask", "PIL"):
        try:
            pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
            datas.extend(pkg_datas)
            binaries.extend(pkg_binaries)
            hidden.extend(pkg_hidden)
        except Exception:
            continue

    return datas, binaries, hidden


def base_hiddenimports() -> list[str]:
    """Application modules that PyInstaller may miss via static analysis."""
    modules = [
        # GUI
        "wizard.gui",
        "wizard.gui.styles",
        "wizard.gui.widgets",
        "wizard.gui.windows",
        "wizard.cpharm_desktop",
        "wizard.cpharm_merged",
        "wizard.setup_desktop",
        "wizard.ui_helpers",
        "wizard.ui_theme",
        "wizard.browser_setup",
        "wizard.preflight_core",
        "wizard.mumu_setup_core",
        "wizard.path_store",
        "wizard.path_utils",
        "wizard.path_detection",
        "wizard.gui.path_selector",
        "wizard.mumu_farm_ops",
        "wizard.wizard_paths",
        "wizard.wizard_theme",
        "wizard.per_phone_editor",
        "wizard.step_dialogs",
        "wizard.studio_editors",
        "wizard.sequence_humanize",
        "wizard.site_interview",
        "wizard.farm_control",
        "wizard.site_llm",
        "automation.site_profile",
        "automation.site_sequence_gen",
        "automation.dabflow_site_profile",
        "automation.phone_geo_time",
        "automation.sequence_isolation",
        "automation.ad_slot_pick",
        "scripts.farm_hourly_ntfy",
        # Automation
        "automation",
        "automation.dashboard",
        "automation.tor_manager",
        "automation.sequence_runner",
        "automation.sequence_paths",
        "automation.sequence_playlist",
        "automation.apk_tools",
        "automation.browser_apk_catalog",
        "automation.mumu_fingerprint",
        "automation.humanize",
        "automation.dabflow_mapper",
        "automation.dabflow_sequence_gen",
        "automation.browser_adb",
        "automation.browser_onboarding",
        "automation.browser_privacy",
        "automation.web_viewport",
        "wizard.dabflow_studio",
        "automation.browser_farm",
        "automation.browser_identity",
        "automation.browse_proxy",
        "automation.emulator_ad_mode",
        "automation.dabflow_mantis_client_patch",
        "automation.dabflow_mantis_ad_urls",
        "automation.adb_wrapper",
        "automation.config",
        "automation.group_manager",
        "automation.group_runner",
        "automation.scheduler",
        "automation.fix_sequences_strip_chrome",
        "automation.win_subprocess",
        "automation.no_window",
        "automation.process_scan",
        "automation.human_ad_click",
        "automation.dabflow_overlays",
        "automation.farm_checkin",
        "automation.farm_unique_seq",
        "automation.farm_visit_caps",
        "automation.mantis_inject_proxy",
        "automation.mantis_farm_math",
        "automation.mantis_fetch",
        "automation.mantis_gauge_score",
        "automation.mantis_steering",
        "automation.mantis_autopilot_apply",
        "automation.mantis_autopilot_cycle",
        "automation.scorecard_api",
        "scripts.run_farm_354",
        "scripts.farm_operator_dash",
        "scripts.farm_remediate_loop",
        "scripts.keep_farm_alive",
        "scripts.run_mantis_inject_proxies",
        "scripts.ensure_farm_24x7",
        "scripts.run_farm_cycles",
        "automation.farm_health_audit",
        "automation.farm_phone_discover",
        "automation.farm_money_monitor",
        "automation.farm_pause",
        "automation.display_resolution",
        "automation.farm_sites",
        "automation.farm_visit_caps",
        "automation.tablet_scheduler",
        "scripts.ssp_paying_hunter",
        "scripts.watch_bottom_ads",
        "scripts.ntfy_farm_responder",
        "scripts.ntfy_agent_wake",
        "scripts.farm_fail_review",
        "scripts.emu_keepalive",
        "scripts.farm_midnight_watch",
        "psutil",
        # Scheduler (third-party)
        "apscheduler",
        "apscheduler.schedulers",
        "apscheduler.schedulers.background",
        "apscheduler.triggers",
        "apscheduler.triggers.cron",
        "apscheduler.triggers.interval",
        "apscheduler.jobstores",
        "apscheduler.executors",
        "tzlocal",
        "zoneinfo",
        # Flask / Werkzeug stack
        "flask",
        "werkzeug",
        "werkzeug.routing",
        "werkzeug.serving",
        "jinja2",
        "click",
        # Tk / imaging
        "customtkinter",
        "PIL",
        "PIL.Image",
        "PIL.ImageTk",
        # Stdlib used indirectly
        "email",
        "email.mime",
        "email.mime.text",
        "html",
        "http",
        "http.server",
        "logging.handlers",
        "websockets",
        "asyncio",
        "sqlite3",
        "xml",
        "xml.etree",
        "xml.etree.ElementTree",
    ]
    modules.extend(collect_submodules("automation"))
    modules.extend(collect_submodules("wizard"))
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for name in modules:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


def icon_path() -> str:
    """Prefer Windows .ico; fall back to PNG."""
    ico = ROOT / "wizard" / "icons" / "app_icon.ico"
    png = ROOT / "wizard" / "icons" / "app_icon.png"
    if ico.is_file():
        return str(ico)
    return str(png)


def version_info_path(setup: bool = False) -> str | None:
    name = "version_info_setup.txt" if setup else "version_info.txt"
    path = ROOT / "wizard" / name
    return str(path) if path.is_file() else None


def build_analysis(entry_script: str | Path, *, extra_hidden: list[str] | None = None):
    """Create a PyInstaller Analysis object with shared CPharm settings."""
    entry = Path(entry_script)
    pkg_datas, pkg_binaries, pkg_hidden = collect_package_assets()
    hidden = base_hiddenimports() + (extra_hidden or []) + pkg_hidden

    return Analysis(
        [str(entry)],
        pathex=[str(ROOT)],
        binaries=pkg_binaries,
        datas=_existing_data_pairs() + pkg_datas,
        hiddenimports=hidden,
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=["matplotlib", "numpy", "pandas", "scipy", "pytest"],
        win_no_prefer_redirects=False,
        win_private_assemblies=False,
        cipher=None,
        noarchive=False,
    )


def build_exe(analysis, *, name: str, console: bool = False, setup: bool = False):
    """Create one-file EXE with bundled Python runtime."""
    pyz = PYZ(analysis.pure, analysis.zipped_data, cipher=None)
    kwargs: dict = {
        "name": name,
        "debug": False,
        "bootloader_ignore_signals": False,
        "strip": False,
        "upx": True,
        "upx_exclude": [],
        "runtime_tmpdir": None,
        "console": console,
        "disable_windowed_traceback": False,
        "argv_emulation": False,
        "target_arch": None,
        "codesign_identity": None,
        "entitlements_file": None,
        "icon": icon_path(),
    }
    ver = version_info_path(setup=setup)
    if ver:
        kwargs["version"] = ver

    return EXE(
        pyz,
        analysis.scripts,
        analysis.binaries,
        analysis.zipfiles,
        analysis.datas,
        [],
        **kwargs,
    )
