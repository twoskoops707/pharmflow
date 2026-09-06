# -*- mode: python ; coding: utf-8 -*-
#
# Single frozen Windows binary: ``cpharm_desktop.py`` → ``PharmFlow.exe``.
# One exe: 9-step wizard, phone setup (step 4), install, boot, go, dashboard.
# CI: ``pyinstaller PharmFlow.spec`` from ``wizard/`` (see ``.github/workflows/build-wizard.yml``).
#
import os
import platform
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

_webview_datas, _webview_binaries, _webview_hidden = collect_all("webview")

# Farm operator dash (scripts/farm_operator_dash.py) runs in-process when no
# capable system python is found, so flask + deps must ship inside the EXE.
_dash_datas, _dash_binaries, _dash_hidden = collect_all("flask")
_dash_extra = (collect_all("werkzeug") + collect_all("jinja2")
               + collect_all("markupsafe") + collect_all("itsdangerous")
               + collect_all("click") + collect_all("blinker"))

# On ARM64 Windows, pywebview's edgechromium backend LoadLibrary's
# WebView2Loader.dll from PATH / MEI root. collect_all embeds it under
# webview/lib/runtimes/win-arm64/native/, but frozen onefile lookups also
# probe ``_MEIPASS/WebView2Loader.dll``. Explicitly ship the native ARM64
# loader at the frozen app root so the deck does not silently miss it.
#
# Also: pywebview ships net462 WebView2 WinForms DLLs. Those fail on ARM64
# under pythonnet+coreclr with ContextMenu TypeLoadException. Overlay the
# netcoreapp3.0 DLLs (vendored under bundled/webview2_netcore/) so the deck
# can host on .NET 8 Desktop — the only workable path (clr_loader has no
# ARM64 netfx ClrLoader.dll).
_webview_root_binaries: list = []
_host_machine = platform.machine().lower()
_is_arm64_host = _host_machine in ("arm64", "aarch64")
_webview2_netcore_dir = Path("bundled") / "webview2_netcore"
if _is_arm64_host:
    _arm64_loader = _webview2_netcore_dir / "WebView2Loader.dll"
    if not _arm64_loader.is_file():
        try:
            import webview as _wv_mod

            _arm64_loader = (
                Path(_wv_mod.__file__).resolve().parent
                / "lib"
                / "runtimes"
                / "win-arm64"
                / "native"
                / "WebView2Loader.dll"
            )
        except Exception:
            _arm64_loader = Path()
    if _arm64_loader.is_file():
        _webview_root_binaries.append((str(_arm64_loader), "."))

    def _is_stock_webview2_managed(entry: object) -> bool:
        src = str(entry[0]).replace("\\", "/")
        return src.endswith("Microsoft.Web.WebView2.Core.dll") or src.endswith(
            "Microsoft.Web.WebView2.WinForms.dll"
        )

    _webview_datas = [e for e in _webview_datas if not _is_stock_webview2_managed(e)]
    _webview_binaries = [e for e in _webview_binaries if not _is_stock_webview2_managed(e)]
    for _name in (
        "Microsoft.Web.WebView2.Core.dll",
        "Microsoft.Web.WebView2.WinForms.dll",
    ):
        _src = _webview2_netcore_dir / _name
        if _src.is_file():
            _webview_datas.append((str(_src), "webview/lib"))

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
if _is_arm64_host and _webview2_netcore_dir.is_dir():
    _browser_apk_datas.append(("bundled/webview2_netcore", "bundled/webview2_netcore"))

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
    + list(_dash_hidden)
    + [name for _d, _b, _h in _dash_extra for name in _h]
)

a = Analysis(
    ["cpharm_desktop.py"],
    pathex=[".", "..", "../automation", "../tools"],
    binaries=list(_webview_binaries) + list(_webview_root_binaries)
    + list(_dash_binaries)
    + [bin_pair for _d, _bins, _h in _dash_extra for bin_pair in _bins],
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
    + list(_dash_datas)
    + [data_pair for _datas, _b, _h in _dash_extra for data_pair in _datas]
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

