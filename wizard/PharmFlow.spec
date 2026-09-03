# -*- mode: python ; coding: utf-8 -*-
#
# Single frozen Windows binary: ``cpharm_desktop.py`` → ``PharmFlow.exe``.
# One exe: 9-step wizard, phone setup (step 4), install, boot, go, dashboard.
# CI: ``pyinstaller PharmFlow.spec`` from ``wizard/`` (see ``.github/workflows/build-wizard.yml``).
#
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

_webview_datas, _webview_binaries, _webview_hidden = collect_all("webview")

# Farm helpers (run_farm_354.py, cpharm_unison_supervisor.py, farm_operator_dash.py,
# tools/cpharm_watchdog.py) run as plain .py under an external system pythonw and do
# ``sys.path.insert(0, <bundle root>)`` then ``import wizard.*`` (wizard_paths,
# mumu_farm_ops, ...). Those modules must exist as source on disk in the extract, so
# ship every wizard/*.py (skipping heavyweight dirs already excluded / bundled elsewhere).
_wizard_py_datas: list = []
_wizard_src = Path("..") / "wizard"
_wizard_excluded = {"__pycache__", "build", "dist", "bundled", "docs", "assets"}
for _py in _wizard_src.rglob("*.py"):
    _rel = _py.relative_to(_wizard_src)
    if _rel.parts and _rel.parts[0] in _wizard_excluded:
        continue
    _dest_dir = _rel.parent.as_posix()
    _wizard_py_datas.append((str(_py), f"wizard/{_dest_dir}" if _dest_dir != "." else "wizard"))

# Browser APKs fetched at build time (tools/prefetch_browser_apks.py) embed
# inside the EXE so browser installs work offline. Absent locally/CI = no-op.
_browser_apk_datas: list = []
if os.path.isdir("bundled/apks"):
    _browser_apk_datas.append(("bundled/apks", "bundled/apks"))

_hidden = (
    [
        "wizard_paths",
        "wizard_theme",
        "setup_wizard",
        "sequence_humanize",
        "tor_manager",
        "browse_proxy",
        "emulator_ad_mode",
        "chromium_fre_uia",
        "config",
        "automation.config",
        "mumu_fingerprint",
        "dabflow_mantis_client_patch",
        "mumu_farm_ops",
        "preflight_core",
        "browser_setup",
        "mumu_setup_core",
        "mumu_setup_webview",
        "phone_setup_entry",
        "cpharm_app_webview",
        "cpharm_wizard_bridge",
        "wizard_tk_spawn",
        "setup_startup_cleanup",
        "mumu_detect",
        "adb_paths",
        "browser_adb",
        "device_open_url",
        "sequence_normalize",
        "sequence_geometry",
        "human_variation",
        "mantis_farm_math",
        "automation.mantis_farm_math",
        "mantis_gauge_score",
        "automation.mantis_gauge_score",
        "age_gate_uia",
        "session_notes_uia",
        "browser_builder_webview",
        "webview",
        "cpharm_watchdog",
        "tools.cpharm_watchdog",
        "cloud_phones.cloud_phones_cli",
    ]
    + collect_submodules("webview")
    + list(_webview_hidden)
)

a = Analysis(
    ["cpharm_desktop.py"],
    pathex=[".", "..", "../automation", "../tools"],
    binaries=list(_webview_binaries),
    datas=[
        ("assets", "assets"),
        ("assets/cpharm_app", "assets/cpharm_app"),

        ("../docs", "docs"),
        # Farm runtime payload: the frozen EXE owns Start farm, and farm_control
        # resolves helpers from bundle_root()/scripts + bundle_root()/automation
        # (run_farm_354.py, cpharm_unison_supervisor.py, farm_operator_dash.py,
        # suppress_console_flash.py, and the automation package they import).
        ("../scripts", "scripts"),
        ("../automation", "automation"),
        ("../sequences", "sequences"),
        ("../cloud_phones", "cloud_phones"),
        ("../tools", "tools"),
        ("../docker_guard.py", "."),
    ]
    + list(_webview_datas)
    + _browser_apk_datas
    + _wizard_py_datas,
    hiddenimports=_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PharmFlow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

