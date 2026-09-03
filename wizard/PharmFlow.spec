# -*- mode: python ; coding: utf-8 -*-
#
# Single frozen Windows binary: ``cpharm_desktop.py`` → ``PharmFlow.exe``.
# One exe: 9-step wizard, phone setup (step 4), install, boot, go, dashboard.
# CI: ``pyinstaller PharmFlow.spec`` from ``wizard/`` (see ``.github/workflows/build-wizard.yml``).
#
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

_webview_datas, _webview_binaries, _webview_hidden = collect_all("webview")

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
        ("assets/cpharm_ui", "assets/cpharm_ui"),
        ("../docs", "docs"),
        ("../automation/mumu_fingerprint.py", "automation"),
        ("../automation/dabflow_mantis_client_patch.py", "automation"),
        ("../automation/mantis_farm_math.py", "automation"),
        ("../automation/mantis_gauge_score.py", "automation"),
        ("../automation/adb_paths.py", "automation"),
        ("../cloud_phones", "cloud_phones"),
        ("../tools/cpharm_watchdog.py", "tools"),
        ("../tools/project_agent.py", "tools"),
        ("../tools", "tools"),
        ("../docker_guard.py", "."),
    ]
    + list(_webview_datas)
    + _browser_apk_datas,
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

