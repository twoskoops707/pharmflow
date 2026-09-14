# -*- mode: python ; coding: utf-8 -*-
#
# Single frozen Windows binary: ``pharmflow_desktop.py`` → ``PharmFlow.exe``.
# One exe: 9-step wizard, phone setup (step 4), install, boot, go, dashboard.
# CI: ``pyinstaller PharmFlow.spec`` from ``wizard/`` (see ``.github/workflows/build-wizard.yml``).
#
import os
import platform
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

# Diagnostics: PyInstaller's CArchiveWriter._write_file raises PermissionError
# on read with no filename in the traceback. Wrap it so the exact source that
# fails on CI (Windows 2025 runner) is printed instead of guessing.
import PyInstaller.archive.writers as _pw  # noqa: E402

_orig_write_file = _pw.CArchiveWriter._write_file


def _write_file_trace(self, fp, src_name, dest_name, typecode, compress=False):
    try:
        return _orig_write_file(self, fp, src_name, dest_name, typecode, compress)
    except PermissionError:
        print(f"PERMISSION_DENIED_SRC: {src_name!r} -> {dest_name!r}", flush=True)
        raise


_pw.CArchiveWriter._write_file = _write_file_trace

_webview_datas, _webview_binaries, _webview_hidden = collect_all("webview")

# Farm operator dash (scripts/farm_operator_dash.py) runs in-process when no
# capable system python is found, so flask + deps must ship inside the EXE.
# Each collect_all returns a 3-tuple (datas, binaries, hiddenimports); merge
# element-wise — never tuple-+ the triples together (flattens, breaks unpack).
_dash_parts = [
    collect_all(name)
    for name in ("flask", "werkzeug", "jinja2", "markupsafe",
                 "itsdangerous", "click", "blinker")
]
_dash_datas = [item for _d, _b, _h in _dash_parts for item in _d]
_dash_binaries = [item for _d, _b, _h in _dash_parts for item in _b]
_dash_hidden = [item for _d, _b, _h in _dash_parts for item in _h]

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

    # Only drop pywebview's managed DLLs when both netcore replacements exist.
    # Stripping with an empty bundled/webview2_netcore leaves the freeze with no
    # WebView2 assemblies, so webview.start() never paints and the Control
    # Panel title never appears.
    _netcore_names = (
        "Microsoft.Web.WebView2.Core.dll",
        "Microsoft.Web.WebView2.WinForms.dll",
    )
    _have_netcore = all((_webview2_netcore_dir / _name).is_file() for _name in _netcore_names)
    if _have_netcore:
        _webview_datas = [e for e in _webview_datas if not _is_stock_webview2_managed(e)]
        _webview_binaries = [e for e in _webview_binaries if not _is_stock_webview2_managed(e)]
        for _name in _netcore_names:
            _webview_datas.append((str(_webview2_netcore_dir / _name), "webview/lib"))
        print("WEBVIEW2: overlaying netcore managed DLLs from bundled/webview2_netcore", flush=True)
    else:
        print(
            "WEBVIEW2: netcore overlays missing; keeping stock WebView2 managed DLLs",
            flush=True,
        )

# Tor runtime data dirs (automation/tor/data_*) must NOT ship in the EXE:
# their per-run 'lock' files raise PermissionError when PyInstaller reads
# them into the archive on CI (writers._write_file -> readinto), and the
# state is runtime-only — the farm creates fresh data dirs on the operator
# box. Build the automation datas explicitly, skipping tor/data_* and
# __pycache__ (bytecode is regenerated at runtime).
_automation_datas: list = []
_auto_root = Path("../automation").resolve()
for _f in _auto_root.rglob("*"):
    if not _f.is_file():
        continue
    _rel = _f.relative_to(_auto_root)
    if "__pycache__" in _rel.parts:
        continue
    if _rel.parts[0] == "tor" and any(p.startswith("data_") for p in _rel.parts):
        continue
    _dest = "automation" if _rel.parent == Path(".") else f"automation/{_rel.parent.as_posix()}"
    _automation_datas.append((str(_f), _dest))

# Farm helpers (run_farm_354.py, pharmflow_unison_supervisor.py, farm_operator_dash.py,
# tools/pharmflow_watchdog.py) run as plain .py under an external system pythonw and do
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
        "pharmflow_app_webview",
        "pharmflow_wizard_bridge",
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
        "automation.earn_plan",
        "age_gate_uia",
        "session_notes_uia",
        "browser_builder_webview",
        "webview",
        "pharmflow_watchdog",
        "tools.pharmflow_watchdog",
        "cloud_phones.cloud_phones_cli",
    ]
    + collect_submodules("webview")
    + list(_webview_hidden)
    + _dash_hidden
)

# Stamp the real build identity at build time so the frozen EXE's window header
# shows which commit/build it actually is (git is not available at runtime).
# ``pharmflow_version.build_label`` prefers bundled assets/build_info.json, so the
# header reads e.g. ``(build git-abc1234 @ 20260907-1700)`` — always current.
import datetime as _dt
import subprocess as _sp

_build_commit = ""
for _c in (
    ["git", "rev-parse", "HEAD"],
    ["git", "log", "-1", "--format=%H"],
):
    try:
        _build_commit = _sp.check_output(_c, cwd=os.getcwd(), text=True, timeout=10).strip()
    except Exception:
        pass
    if _build_commit:
        break
_build_stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M")
_build_info = {
    "build_number": f"{_build_stamp}",
    "commit": _build_commit,
    "built_at_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
}
_build_info_path = Path("assets") / "build_info.json"
_build_info_path.parent.mkdir(parents=True, exist_ok=True)
import json as _json
_build_info_path.write_text(
    _json.dumps(_build_info, indent=2), encoding="utf-8"
)
print(f"BUILD_INFO: {_json.dumps(_build_info)}")

a = Analysis(
    ["pharmflow_desktop.py"],
    pathex=[".", "..", "../automation", "../tools"],
    binaries=list(_webview_binaries) + list(_webview_root_binaries)
    + _dash_binaries,
    datas=[
        ("assets", "assets"),
        ("assets/pharmflow_app", "assets/pharmflow_app"),

        ("../docs", "docs"),
        # Farm runtime payload: the frozen EXE owns Start farm, and farm_control
        # resolves helpers from bundle_root()/scripts + bundle_root()/automation
        # (run_farm_354.py, pharmflow_unison_supervisor.py, farm_operator_dash.py,
        # suppress_console_flash.py, and the automation package they import).
        ("../scripts", "scripts"),
        *_automation_datas,
        ("../sequences", "sequences"),
        ("../cloud_phones", "cloud_phones"),
        ("../tools", "tools"),
        ("../docker_guard.py", "."),
    ]
    + list(_webview_datas)
    + _dash_datas
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

