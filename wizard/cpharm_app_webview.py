"""
Unified CPharm WebView shell — 9-step wizard matching CPharmWizard.
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import traceback
from pathlib import Path
from typing import Any

_wizard_dir = Path(__file__).resolve().parent
if str(_wizard_dir) not in sys.path:
    sys.path.insert(0, str(_wizard_dir))

from wizard_paths import wizard_assets_dir  # noqa: E402


def is_pywebview_available() -> bool:
    try:
        import webview  # noqa: F401

        return True
    except Exception:
        return False


def _webview_fail_reason(exc: BaseException | None = None, *, stage: str = "") -> str:
    """Human-readable WHY the WebView2 deck could not start."""
    parts: list[str] = []
    if stage:
        parts.append(f"stage={stage}")
    if exc is not None:
        parts.append(f"{type(exc).__name__}: {exc}")
        tb = traceback.format_exc()
        if tb and tb.strip() != "NoneType: None":
            parts.append(tb.strip())
    arch = ""
    try:
        import platform as _plat

        arch = f"machine={_plat.machine()} frozen={getattr(sys, 'frozen', False)}"
    except Exception:
        arch = f"frozen={getattr(sys, 'frozen', False)}"
    parts.append(arch)
    return "\n".join(parts)


def _log_webview_soft_warn(reason: str) -> None:
    """Record a non-fatal WebView2 provisioning warning (deck still attempted)."""
    banner = (
        "WEBVIEW2 PROVISION WARN — still attempting deck (not Tk fallback).\n"
        f"{reason}\n"
        "--- end webview soft warn ---"
    )
    try:
        print(banner, file=sys.stderr, flush=True)
    except Exception:
        pass
    try:
        err_path = Path.home() / "CPharm" / "cpharm_webview_soft_warn.log"
        err_path.parent.mkdir(parents=True, exist_ok=True)
        err_path.write_text(banner + "\n", encoding="utf-8")
    except OSError:
        pass
    try:
        import cpharm_wizard_bridge as bridge

        for line in banner.splitlines():
            bridge._emit_log("boot", line + "\n")
    except Exception:
        pass


def _log_webview_fallback(reason: str, *, interactive: bool = True) -> None:
    """Never silently fall back to Tk — shout to stderr, boot log, and disk.

    A frozen EXE must not open a Tk window titled Home and pretend that is
    the Control Panel. Source checkouts may still fall back to Tk.
    """
    frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        banner = (
            "WEBVIEW2 DECK FAILED — frozen EXE will not open a Tk Home substitute.\n"
            f"{reason}\n"
            "--- end webview failure ---"
        )
        box_lead = (
            "PharmFlow could not open the Control Panel (WebView2).\n\n"
            "It will not open a Tk Home window in its place.\n\n"
        )
        box_title = "PharmFlow — Control Panel unavailable"
    else:
        banner = (
            "WEBVIEW2 DECK FAILED — falling back to Tk Home UI.\n"
            f"{reason}\n"
            "--- end webview fallback reason ---"
        )
        box_lead = "PharmFlow WebView2 deck failed — using Tk fallback.\n\n"
        box_title = "PharmFlow — WebView2 unavailable"
    try:
        print(banner, file=sys.stderr, flush=True)
    except Exception:
        pass
    try:
        err_path = Path.home() / "CPharm" / "cpharm_webview_fallback.log"
        err_path.parent.mkdir(parents=True, exist_ok=True)
        err_path.write_text(banner + "\n", encoding="utf-8")
    except OSError:
        pass
    try:
        import cpharm_wizard_bridge as bridge

        for line in banner.splitlines():
            bridge._emit_log("boot", line + "\n")
    except Exception:
        pass
    # Visible MessageBox so operators see WHY even when stderr is hidden (windowed EXE).
    if interactive and sys.platform == "win32":
        try:
            import ctypes

            short = reason.strip()
            if len(short) > 900:
                short = short[:900] + "…"
            ctypes.windll.user32.MessageBoxW(
                0,
                f"{box_lead}{short}",
                box_title,
                0x00000010,  # MB_ICONERROR
            )
        except Exception:
            pass


def _webview2_runtime_client_key() -> str:
    return r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def _webview2_nonwow_runtime_registered() -> bool:
    """True when native (non-WOW) EdgeUpdate client key exists — ARM64 apps need this."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _webview2_runtime_client_key()):
            return True
    except OSError:
        return False


def _discover_arm64_webview2_runtime_folder() -> str | None:
    """
    Locate an on-disk ARM64 WebView2 runtime folder (contains msedgewebview2.exe).

    On Snapdragon/ARM64 Windows the Evergreen installer often lands binaries under
    Program Files (x86) and registers only the WOW6432Node client key. Native ARM64
    EXEs miss the non-WOW key and fail unless BrowserExecutableFolder is set.
    """
    if sys.platform != "win32":
        return None
    try:
        import platform as _plat
        import struct
    except Exception:
        return None
    if _plat.machine().lower() not in ("arm64", "aarch64"):
        return None

    roots: list[Path] = []
    for env_name in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(env_name)
        if not base:
            continue
        if env_name == "LOCALAPPDATA":
            roots.append(Path(base) / "Microsoft" / "EdgeWebView" / "Application")
        else:
            roots.append(Path(base) / "Microsoft" / "EdgeWebView" / "Application")

    candidates: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for child in root.iterdir():
            exe = child / "msedgewebview2.exe"
            if child.is_dir() and exe.is_file():
                candidates.append(child)
    if not candidates:
        return None

    def _is_arm64_pe(path: Path) -> bool:
        try:
            data = path.read_bytes()[:4096]
            pe = struct.unpack_from("<I", data, 0x3C)[0]
            machine = struct.unpack_from("<H", data, pe + 4)[0]
            return machine == 0xAA64
        except Exception:
            return False

    arm64 = [c for c in candidates if _is_arm64_pe(c / "msedgewebview2.exe")]
    pool = arm64 or candidates
    pool.sort(key=lambda p: p.name, reverse=True)
    return str(pool[0])


def _ensure_webview2_runtime_path() -> str | None:
    """Set pywebview WEBVIEW2_RUNTIME_PATH when native registry lookup would miss."""
    existing = os.environ.get("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER", "").strip()
    if existing and Path(existing).is_dir():
        try:
            import webview

            webview.settings["WEBVIEW2_RUNTIME_PATH"] = existing
        except Exception:
            pass
        return existing
    if _webview2_nonwow_runtime_registered():
        return None
    folder = _discover_arm64_webview2_runtime_folder()
    if not folder:
        return None
    os.environ["WEBVIEW2_BROWSER_EXECUTABLE_FOLDER"] = folder
    try:
        import webview

        webview.settings["WEBVIEW2_RUNTIME_PATH"] = folder
    except Exception:
        pass
    try:
        print(
            f"WEBVIEW2: non-WOW registry missing; using BrowserExecutableFolder={folder}",
            file=sys.stderr,
            flush=True,
        )
    except Exception:
        pass
    return folder


def _safe_stderr(msg: str) -> None:
    """Print to stderr only when a real stderr exists (windowed EXEs get None)."""
    if sys.stderr is None:
        return
    try:
        print(msg, file=sys.stderr, flush=True)
    except OSError:
        pass


def _load_winforms_compat_shim() -> None:
    """
    Load CPharmWinFormsCompat.dll (defines System.Windows.Forms.ContextMenu).

    pywebview's edgechromium backend reflects Microsoft.Web.WebView2.WinForms.WebView2
    through pythonnet. On .NET 8 (the only runtime native-ARM64 pythonnet can host) the
    WinForms surface still references System.Windows.Forms.ContextMenu — a type removed
    in .NET Core 5+. Without it the reflection aborts with TypeLoadException and the
    frozen EXE dies before a window opens. The shim assembly supplies that type, so the
    reflection (and the whole deck) succeeds. Never raises: a shim failure just means the
    Tk fallback path stays available.
    """
    try:
        import platform as _plat

        if _plat.machine().lower() not in ("arm64", "aarch64"):
            return
        candidates = [
            _wizard_dir / "bundled" / "webview2_netcore" / "CPharmWinFormsCompat.dll",
            Path(getattr(sys, "_MEIPASS", "")) / "bundled" / "webview2_netcore" / "CPharmWinFormsCompat.dll",
            Path(getattr(sys, "_MEIPASS", "")) / "webview" / "lib" / "CPharmWinFormsCompat.dll",
        ]
        shim = next((p for p in candidates if p.is_file()), None)
        if shim is None:
            _safe_stderr(
                "WEBVIEW2: CPharmWinFormsCompat.dll shim not found; deck may fall back to Tk"
            )
            return
        import clr  # noqa: F401  (runtime already selected by dotnet_provision)

        from System.Reflection import Assembly

        Assembly.LoadFrom(str(shim))
        _safe_stderr(f"WEBVIEW2: loaded WinForms compat shim from {shim}")
    except Exception as exc:  # noqa: BLE001 - provisioning must never crash the deck attempt
        _safe_stderr(f"WEBVIEW2: compat shim load failed: {exc}")


def _overlay_netcore_webview2_dlls() -> None:
    """
    On ARM64, replace pywebview's net462 WebView2 managed DLLs with netcoreapp3.0
    copies so pythonnet+coreclr can reflect WebView2 without ContextMenu TypeLoadException.
    """
    try:
        import platform as _plat
        import shutil

        import webview
    except Exception:
        return
    if _plat.machine().lower() not in ("arm64", "aarch64"):
        return

    lib_dir = Path(webview.__file__).resolve().parent / "lib"
    # Order matters: the *bundled* netcore directory must be found before
    # ``webview/lib`` itself. ``webview/lib`` contains the STOCK net462 DLLs that
    # crash on .NET 8 (ContextMenu was removed), so using it as the source and
    # bailing on the self-equality check silently skipped the overlay — the deck
    # then died with a TypeLoadException on every launch. Check the bundled dirs
    # first and only treat webview/lib as "already correct" when nothing else has
    # the DLLs.
    bundled_dirs = [
        Path(getattr(sys, "_MEIPASS", "")) / "bundled" / "webview2_netcore",
        _wizard_dir / "bundled" / "webview2_netcore",
        Path(getattr(sys, "_MEIPASS", "")) / "webview" / "lib",
        _wizard_dir / "webview" / "lib",
    ]
    src_dir = next(
        (p for p in bundled_dirs if (p / "Microsoft.Web.WebView2.WinForms.dll").is_file()),
        None,
    )
    if src_dir is None or not lib_dir.is_dir():
        return
    if src_dir.resolve() == lib_dir.resolve():
        return
    for name in (
        "Microsoft.Web.WebView2.Core.dll",
        "Microsoft.Web.WebView2.WinForms.dll",
    ):
        src = src_dir / name
        dst = lib_dir / name
        if src.is_file():
            try:
                shutil.copy2(src, dst)
                _safe_stderr(f"WEBVIEW2: overlaid {name} -> {dst.name} (netcore)")
            except OSError as exc:
                _safe_stderr(f"WEBVIEW2: could not overlay {name}: {exc}")


def _patch_pywebview_winforms_openfolder() -> None:
    """
    pywebview 6.2.x OpenFolderDialog reflects netfx-only FileDialogNative+IFileDialog.
    That type is absent on .NET 8 Desktop (ARM64 coreclr path) and crashes import.
    Soft-patch the class so folder dialogs degrade instead of killing the deck.
    """
    try:
        import webview
    except Exception:
        return
    path = Path(webview.__file__).resolve().parent / "platforms" / "winforms.py"
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    marker = "CPHARM_NET8_OPENFOLDER_PATCH"
    if marker in text:
        return
    needle = "class OpenFolderDialog:\n"
    start = text.find(needle)
    if start < 0:
        return
    rest = text[start + len(needle) :]
    end_rel = rest.find("\n_main_window_created")
    if end_rel < 0:
        end_rel = rest.find("\nclass ")
    if end_rel < 0:
        return
    # Stub: deck does not need the Vista folder picker; returning None is fine.
    stub = (
        f"class OpenFolderDialog:\n"
        f"    # {marker}\n"
        f"    foldersFilter = 'Folders|\\n'\n"
        f"\n"
        f"    @classmethod\n"
        f"    def show(cls, parent=None, initialDirectory=None, allow_multiple=False, title=None):\n"
        f"        return None\n"
        f"\n"
    )
    new_text = text[:start] + stub + rest[end_rel + 1 :]
    try:
        path.write_text(new_text, encoding="utf-8")
        _safe_stderr("WEBVIEW2: patched pywebview OpenFolderDialog for .NET 8")
    except OSError as exc:
        _safe_stderr(f"WEBVIEW2: OpenFolderDialog patch failed: {exc}")


def _html_url(*, view: str | None = None) -> str:
    index = wizard_assets_dir() / "cpharm_app" / "index.html"
    if not index.is_file():
        raise FileNotFoundError(f"cpharm app UI missing: {index}")
    uri = index.resolve().as_uri()
    if view:
        uri += f"?view={view}"
    return uri


def _js_emit(window: Any, expr: str) -> None:
    try:
        window.evaluate_js(expr)
    except Exception:
        pass


_active_window: Any = None


def _api_log(line: str) -> None:
    """Append one line to the deck API telemetry log under CPHARM_LOG_DIR."""
    try:
        import time as _t

        log_dir = Path(os.environ.get("CPHARM_LOG_DIR", r"C:\CPharm\logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "deck_api.log", "a", encoding="utf-8") as _f:
            _f.write(f"[{_t.strftime('%H:%M:%S')}] {line}\n")
    except Exception:
        pass


def _api_wrapper_result(label: str, fn) -> dict:
    """Run a bridge/setup call with telemetry — name, duration, ok/error."""
    import time as _t

    _api_log(f"CALL {label}")
    t0 = _t.monotonic()
    try:
        result = fn()
        dt = _t.monotonic() - t0
        if isinstance(result, dict):
            ok = result.get("ok")
            err = str(result.get("error") or "")[:160]
            _api_log(f"RET {label} {dt*1000:.0f}ms ok={ok} error={err!r}")
        else:
            n = len(result) if hasattr(result, "__len__") else "-"
            _api_log(f"RET {label} {dt*1000:.0f}ms type={type(result).__name__} len={n}")
        return result
    except Exception as exc:  # noqa: BLE001
        dt = _t.monotonic() - t0
        _api_log(f"EXC {label} {dt*1000:.0f}ms {type(exc).__name__}: {exc}")
        return {"ok": False, "error": str(exc)[:500]}


def emit_app_view(view: str) -> None:
    if _active_window is None:
        return
    _js_emit(_active_window, f"window.CPharmApp && window.CPharmApp.showView({json.dumps(view)})")


def emit_dragon_view(view: str) -> None:
    emit_app_view(view)


def _fallback_tk(*, initial_view: str | None = None) -> None:
    """Source checkouts may use Tk. A frozen EXE must not open a Home window."""
    if getattr(sys, "frozen", False):
        _bootlog("frozen EXE refused Tk Home fallback")
        return
    from cpharm_desktop import run_main_window

    run_main_window(initial_view=initial_view)


class CPharmAppApi:
    def __init__(self) -> None:
        self._window: Any = None
        self._setup_api: Any = None

    def _bridge_call(self, name: str, *args: Any, **kwargs: Any) -> dict:
        """Invoke a bridge endpoint; never raise — always ``{ok,...}`` or wrap lists."""
        def _run():
            import cpharm_wizard_bridge as bridge

            fn = getattr(bridge, name, None)
            if not callable(fn):
                return {"ok": False, "error": f"Bridge has no method {name}"}
            result = fn(*args, **kwargs)
            if isinstance(result, dict):
                return result
            if isinstance(result, list):
                return {"ok": True, "items": result}
            if result is None:
                return {"ok": True}
            return {"ok": True, "data": result}

        return _api_wrapper_result(name, _run)

    def _setup_call(self, method: str, *args: Any, **kwargs: Any) -> dict:
        def _run():
            if self._setup_api is None:
                raise RuntimeError("Setup API not bound yet — wait for window bind")
            fn = getattr(self._setup_api, method, None)
            if not callable(fn):
                raise RuntimeError(f"Setup API has no method {method}")
            result = fn(*args, **kwargs)
            if isinstance(result, dict):
                if result.get("ok") is False and not result.get("error"):
                    result = dict(result)
                    result["error"] = str(result.get("message") or "Setup action failed")
                return result
            if isinstance(result, list):
                return {"ok": True, "items": result}
            if result is None:
                return {"ok": True}
            return {"ok": True, "data": result}

        return _api_wrapper_result(method, _run)

    def debug_log(self, text: str = "") -> dict:
        """JS-side milestone telemetry (init, wiring, bridge checks)."""
        _api_log(f"JS {str(text)[:240]}")
        return {"ok": True}

    def bind_window(self, window: Any) -> None:
        global _active_window
        _active_window = window
        self._window = window
        from mumu_setup_webview import MuMuSetupApi

        self._setup_api = MuMuSetupApi(skip_launch_cpharm=True)
        self._setup_api.bind_window(window)

        import cpharm_wizard_bridge as bridge

        def log_cb(channel: str, text: str) -> None:
            if self._window is None:
                return
            _js_emit(
                self._window,
                f"window.CPharmApp && window.CPharmApp.appendLog({json.dumps(channel)}, {json.dumps(text)})",
            )

        bridge.register_log_callback(log_cb)
        bridge.register_webview_window(window)

    def get_wizard_steps(self) -> list:
        return self._bridge_call("get_wizard_steps").get("items") or []

    def get_journey_state(self) -> dict:
        return self._bridge_call("get_journey_state")

    def navigate_wizard_page(self, index: int) -> dict:
        return self._bridge_call("navigate_wizard_page", index)

    def navigate_wizard_step(self, step_id: str) -> dict:
        return self._bridge_call("navigate_wizard_step", step_id)

    def get_setup_state(self) -> dict:
        return self._setup_call("get_state")

    def run_setup_action(self, action: str) -> dict:
        return self._setup_call("run_action", action)

    def run_setup(self) -> dict:
        return self._setup_call("run_setup")

    def install_chromium(self) -> dict:
        return self._setup_call("install_chromium")

    def browser_apk_options(self) -> list:
        out = self._setup_call("browser_apk_options")
        return out.get("items") if out.get("ok") and isinstance(out.get("items"), list) else []

    def install_browser(self, browser_id: str, serial: str = "") -> dict:
        return self._setup_call("install_browser", str(browser_id or ""), str(serial or ""))

    def live_phone_options(self) -> list:
        out = self._setup_call("live_phone_options")
        return out.get("items") if out.get("ok") and isinstance(out.get("items"), list) else []

    def get_prereq_status(self) -> list:
        out = self._bridge_call("scan_prereqs")
        return out.get("items") if out.get("ok") and isinstance(out.get("items"), list) else []

    def run_install_all(self) -> dict:
        return self._bridge_call("run_install_all")

    def get_android_status(self) -> dict:
        return self._bridge_call("get_android_status")

    def run_android_install(self) -> dict:
        return self._bridge_call("run_android_install")

    def set_phone_farm_count(self, count: int) -> dict:
        return self._bridge_call("set_phone_farm_count", count)

    def run_create_phone_farm(self) -> dict:
        return self._bridge_call("run_create_phone_farm")

    def spin_up_test_phone(self) -> dict:
        return self._bridge_call("spin_up_test_phone_from_app")

    def run_test_url(self, url: str = "") -> dict:
        return self._bridge_call("run_test_url", url or None)

    def get_site_settings(self) -> dict:
        return self._bridge_call("get_site_settings")

    def save_site_url(self, url: str) -> dict:
        return self._bridge_call("save_site_url", url)

    def scan_site(self, url: str = "") -> dict:
        return self._bridge_call("scan_site", url)

    def apply_site_sequence(self, url: str = "") -> dict:
        return self._bridge_call("apply_site_sequence", url)

    def get_automation_info(self) -> dict:
        return self._bridge_call("get_automation_info")

    def cursor_get_sequence(self) -> dict:
        return self._bridge_call("cursor_get_sequence")

    def cursor_add_step(self, step: dict | None = None) -> dict:
        return self._bridge_call("cursor_add_step", step)

    def cursor_update_step(self, i: int, step: dict | None = None) -> dict:
        return self._bridge_call("cursor_update_step", i, step)

    def cursor_remove_step(self, i: int) -> dict:
        return self._bridge_call("cursor_remove_step", i)

    def cursor_move_step(self, i: int, dir: int = 1) -> dict:
        return self._bridge_call("cursor_move_step", i, dir)

    def cursor_add_group(self) -> dict:
        return self._bridge_call("cursor_add_group")

    def cursor_remove_group(self, i: int) -> dict:
        return self._bridge_call("cursor_remove_group", i)

    def cursor_rename_group(self, i: int, name: str = "") -> dict:
        return self._bridge_call("cursor_rename_group", i, name)

    def run_edit_default_sequence(self) -> dict:
        return self._bridge_call("run_edit_default_sequence")

    def open_sequence_builder(self) -> dict:
        return self._bridge_call("open_sequence_builder")

    def run_load_default_sequence(self) -> dict:
        return self._bridge_call("run_load_default_sequence")

    def run_save_default_sequence(self) -> dict:
        return self._bridge_call("run_save_default_sequence")

    def pick_sequence_json(self, save: bool = False) -> dict:
        import webview

        if not self._window:
            return {"ok": False, "cancelled": True, "error": "No window bound"}
        file_types = ("JSON sequences (*.json)", "All files (*.*)")
        try:
            if save:
                result = self._window.create_file_dialog(
                    webview.SAVE_DIALOG,
                    save_filename="default_sequence.json",
                    file_types=file_types,
                )
            else:
                result = self._window.create_file_dialog(
                    webview.OPEN_DIALOG,
                    allow_multiple=False,
                    file_types=file_types,
                )
        except Exception as exc:
            return {"ok": False, "cancelled": True, "error": str(exc)}
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (list, tuple)) else result
        return {"ok": True, "path": str(path)}

    def load_sequence_from_path(self, path: str) -> dict:
        return self._bridge_call("load_sequence_from_path", path)

    def save_sequence_to_path(self, path: str) -> dict:
        return self._bridge_call("save_sequence_to_path", path)

    def run_add_group(self) -> dict:
        return self._bridge_call("run_add_group")

    def boot_all_phones(self) -> dict:
        return self._bridge_call("boot_all_phones")

    def remove_group(self, index: int) -> dict:
        return self._bridge_call("remove_group", index)

    def run_humanize_all_sequences(self) -> dict:
        return self._bridge_call("run_humanize_all_sequences")

    def open_groups_manager(self) -> dict:
        return self._bridge_call("open_groups_manager")

    def get_groups_detail(self) -> dict:
        return self._bridge_call("get_groups_detail")

    def get_groups_summary(self) -> dict:
        return self._bridge_call("get_groups_summary")

    def is_dashboard_ready(self) -> dict:
        return self._bridge_call("is_dashboard_ready")

    def groups_run_status(self) -> dict:
        return self._bridge_call("groups_run_status")

    def get_launch_summary(self) -> dict:
        return self._bridge_call("get_launch_summary")

    def get_browse_mode(self) -> dict:
        return self._bridge_call("get_browse_mode")

    def save_browse_mode(self, mode: str) -> dict:
        return self._bridge_call("save_browse_mode", mode)

    def start_server(self) -> dict:
        return self._bridge_call("start_server")

    def start_server_and_open_dashboard(self) -> dict:
        return self._bridge_call("start_server_and_open_dashboard")

    def run_all_groups(self) -> dict:
        return self._bridge_call("run_all_groups")

    def start_automation_one_click(self) -> dict:
        return self._bridge_call("start_automation_one_click")

    def fix_phone_internet(self) -> dict:
        return self._bridge_call("fix_phone_internet")

    def open_dashboard(self) -> dict:
        return self._bridge_call("open_dashboard")

    def get_farm_health(self) -> dict:
        return self._bridge_call("get_farm_health")

    def open_farm_dashboard(self) -> dict:
        return self._bridge_call("open_farm_dashboard")

    def run_cloud_phone_command(self, command: str, host: str = "", count: int = 0, verify: bool = False) -> dict:
        return self._bridge_call("run_cloud_phone_command", command, host, count, verify=verify)

    def cloud_phone_setup(self, host: str, count: int = 8) -> dict:
        return self._bridge_call("cloud_phone_setup", host, count)

    def cloud_phone_status(self, host: str = "") -> dict:
        return self._bridge_call("cloud_phone_status", host)

    def agent_status(self) -> dict:
        return self._bridge_call("agent_status")

    def run_cloud_agent(self, goal: str, apply: bool = False, base: str = "", model: str = "", max_steps: int = 12) -> dict:
        return self._bridge_call("run_cloud_agent", goal, apply=apply, base=base, model=model, max_steps=max_steps)

    def cloud_agent_config(self) -> dict:
        return self._bridge_call("cloud_agent_config")

    def save_cloud_agent_config(self, base: str = "", model: str = "", api_key: str = "") -> dict:
        return self._bridge_call("save_cloud_agent_config", base, model, api_key)

    def open_advanced_wizard(self) -> dict:
        out = self._bridge_call("open_advanced_wizard")
        if out.get("ok") is False:
            return out
        return {"ok": True}

    def get_dragon_scroll(self) -> list:
        return self.get_wizard_steps()

    def navigate_chapter(self, index: int) -> dict:
        out = self._bridge_call("navigate_wizard_chapter", index)
        if out.get("ok") is False:
            return out
        return {"ok": True}



    # ── Farm start/stop (unison money stack) ──


    def start_farm(self, profile_slug: str = "", hours: float = 0) -> dict:
        return self._bridge_call("start_farm_from_app", str(profile_slug or ""), float(hours or 0))

    def stop_farm(self) -> dict:
        return self._bridge_call("stop_farm_from_app")

    def farm_status(self) -> dict:
        return self._bridge_call("farm_status_from_app")

    def get_farm_hud(self) -> dict:
        return self._bridge_call("get_farm_hud")

    def get_machine_capabilities(self) -> dict:
        return self._bridge_call("get_machine_capabilities")

    # ── Farm settings (Advanced panels) ──

    def get_farm_settings(self) -> dict:
        try:
            from wizard.farm_settings import catalog_payload

            return catalog_payload()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:500]}

    def save_farm_settings(self, updates: dict | None = None) -> dict:
        try:
            from wizard.farm_settings import save

            return save(updates or {}, note="wizard_advanced_panel")
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:500]}

    def reset_farm_settings(self, step: str = "", keys: list | None = None) -> dict:
        try:
            from wizard.farm_settings import reset

            return reset(step or None, keys or None)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:500]}


def _build_native_menu(api: "CPharmAppApi") -> list:
    """Top-of-window menu: File -> Help / Exit.

    Menu actions run on a background thread; both dispatch through the bound
    window so the deck JS stays the single source of truth.
    """
    import webview.menu as wm

    def _open_help() -> None:
        win = api._window
        if win is None:
            return
        try:
            win.evaluate_js(
                "window.__pharmflowOpenHelp ? window.__pharmflowOpenHelp() : null"
            )
        except Exception:
            pass

    def _exit_app() -> None:
        win = api._window
        if win is None:
            return
        try:
            win.destroy()
        except Exception:
            pass

    return [
        wm.Menu(
            "File",
            [
                wm.MenuAction("Help", _open_help),
                wm.MenuSeparator(),
                wm.MenuAction("Exit", _exit_app),
            ],
        )
    ]


# WebView2 parks a windowed (subsystem WINDOWS) form here while
# EnsureCoreWebView2Async runs if STARTUPINFO.wShowWindow is SW_HIDE.
# A left-hand monitor can be slightly negative; -8000 is never a real desktop.
_OFFSCREEN_PARK = -8000
_DECK_WIDTH = 1180
_DECK_HEIGHT = 960
_SW_SHOWNORMAL = 1
_SWP_SHOWWINDOW = 0x0040


def _user32():
    """Private user32 so we do not mutate process-wide windll argtypes."""
    lib = getattr(_user32, "_lib", None)
    if lib is not None:
        return lib
    lib = ctypes.WinDLL("user32", use_last_error=True)
    lib.GetSystemMetrics.argtypes = [ctypes.c_int]
    lib.GetSystemMetrics.restype = ctypes.c_int
    lib.IsWindowVisible.argtypes = [ctypes.c_void_p]
    lib.IsWindowVisible.restype = ctypes.c_bool
    lib.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.ShowWindow.restype = ctypes.c_bool
    lib.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    lib.SetForegroundWindow.restype = ctypes.c_bool
    lib.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.GetWindowRect.restype = ctypes.c_bool
    lib.SetWindowPos.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    lib.SetWindowPos.restype = ctypes.c_bool
    lib.IsIconic.argtypes = [ctypes.c_void_p]
    lib.IsIconic.restype = ctypes.c_bool
    lib.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    lib.GetWindowTextW.restype = ctypes.c_int
    lib.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    lib.GetWindowThreadProcessId.restype = ctypes.c_ulong
    lib.EnumWindows.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.EnumWindows.restype = ctypes.c_bool
    _user32._lib = lib  # type: ignore[attr-defined]
    return lib


class _WinRect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def _deck_hwnd(window: Any) -> int | None:
    native = getattr(window, "native", None)
    if native is None:
        return None
    handle = getattr(native, "Handle", None)
    if handle is None:
        return None
    for meth in ("ToInt64", "ToInt32"):
        fn = getattr(handle, meth, None)
        if not callable(fn):
            continue
        try:
            return int(fn())
        except Exception:
            continue
    try:
        return int(handle)
    except (TypeError, ValueError):
        return None


def _control_panel_hwnd_by_title() -> int | None:
    """Find this process's deck even before pywebview exposes native.Handle."""
    user32 = _user32()
    found: list[int] = []
    self_pid = int(os.getpid())

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def _cb(hwnd, _lparam):  # type: ignore[misc]
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) != self_pid:
            return True
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        if "Control Panel" in (buf.value or ""):
            found.append(int(hwnd))
            return False
        return True

    # Keep the callback alive for the duration of EnumWindows.
    _control_panel_hwnd_by_title._cb = _cb  # type: ignore[attr-defined]
    user32.EnumWindows(_cb, 0)
    return found[0] if found else None


def _window_parked_or_hidden(hwnd: int) -> bool:
    user32 = _user32()
    if not user32.IsWindowVisible(hwnd):
        return True
    rect = _WinRect()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    return rect.left <= _OFFSCREEN_PARK or rect.top <= _OFFSCREEN_PARK


def _onscreen_origin(width: int, height: int) -> tuple[int, int]:
    user32 = _user32()
    sw = int(user32.GetSystemMetrics(0) or 0)  # SM_CXSCREEN
    sh = int(user32.GetSystemMetrics(1) or 0)  # SM_CYSCREEN
    if sw < width + 80:
        sw = width + 160
    if sh < height + 80:
        sh = height + 160
    return max(40, (sw - width) // 2), max(40, (sh - height) // 2)


def _force_control_panel_visible(window: Any, *, width: int, height: int) -> None:
    """Undo WebView2's (-25600, -25600) park and any SW_HIDE on the deck.

    Never calls ShowWindow(SW_HIDE). Only acts when the form is hidden or
    parked off-screen, so a later operator drag is left alone.
    """
    if sys.platform != "win32":
        return
    hwnd = _deck_hwnd(window) or _control_panel_hwnd_by_title()
    if not hwnd or not _window_parked_or_hidden(hwnd):
        return
    user32 = _user32()
    x, y = _onscreen_origin(width, height)
    user32.SetWindowPos(hwnd, None, x, y, width, height, _SWP_SHOWWINDOW)
    # SW_RESTORE if iconic; never SW_HIDE (0). WebView2 parks at -25600 when
    # the process STARTUPINFO show-state is hidden — yank that back on-screen.
    show = 9 if user32.IsIconic(hwnd) else _SW_SHOWNORMAL  # SW_RESTORE / SW_SHOWNORMAL
    user32.ShowWindow(hwnd, show)
    user32.SetForegroundWindow(hwnd)
    _bootlog(f"Control Panel forced on-screen hwnd={hwnd} at {x},{y}")


def _bind_control_panel_visibility(window: Any, *, width: int, height: int) -> None:
    """Keep the deck on-screen after WebView2 init moves or hides it."""

    def _pull_if_parked(x: int = 0, y: int = 0) -> None:
        if int(x) <= _OFFSCREEN_PARK or int(y) <= _OFFSCREEN_PARK:
            _force_control_panel_visible(window, width=width, height=height)

    def _on_shown() -> None:
        _force_control_panel_visible(window, width=width, height=height)

    window.events.shown += _on_shown
    window.events.loaded += _on_shown
    window.events.restored += _on_shown
    window.events.moved += _pull_if_parked

    def _retries() -> None:
        # EnsureCoreWebView2Async parks the form AFTER Shown. A few checks
        # catch that; each is a no-op once the window is visible and on-screen.
        for delay in (0.35, 0.9, 1.8, 3.5, 6.0, 10.0):
            threading.Event().wait(delay)
            _force_control_panel_visible(window, width=width, height=height)

    threading.Thread(target=_retries, name="cpharm-deck-visible", daemon=True).start()


def _bootlog(msg: str) -> None:
    """Frozen-only marker log (same file as cpharm_desktop) for startup tracing."""
    if not getattr(sys, "frozen", False):
        return
    try:
        import tempfile
        import time as _time

        with open(
            os.path.join(tempfile.gettempdir(), "cpharm_boot.log"), "a", encoding="utf-8"
        ) as _f:
            _f.write(f"[{_time.strftime('%H:%M:%S')}] deck: {msg}\n")
    except Exception:
        pass


def run_cpharm_app(*, initial_view: str | None = None) -> None:
    import webview
    from cpharm_version import instance_title

    _bootlog("run_cpharm_app enter")
    _overlay_netcore_webview2_dlls()
    _bootlog("overlay netcore dlls done")
    _load_winforms_compat_shim()
    _bootlog("compat shim loaded")
    _patch_pywebview_winforms_openfolder()
    _bootlog("openfolder patch done")
    _ensure_webview2_runtime_path()
    _bootlog("runtime path done")

    api = CPharmAppApi()
    _bootlog("api created")
    title = instance_title("Control Panel")
    if "Control Panel" not in title:
        title = f"{title} — Control Panel"
    origin_x, origin_y = (80, 60)
    if sys.platform == "win32":
        origin_x, origin_y = _onscreen_origin(_DECK_WIDTH, _DECK_HEIGHT)
    window = webview.create_window(
        title,
        _html_url(view=initial_view),
        js_api=api,
        width=_DECK_WIDTH,
        height=_DECK_HEIGHT,
        x=origin_x,
        y=origin_y,
        min_size=(960, 720),
        hidden=False,
        minimized=False,
        focus=True,
        background_color="#07090f",
    )
    api.bind_window(window)
    _bind_control_panel_visibility(window, width=_DECK_WIDTH, height=_DECK_HEIGHT)
    _bootlog(f"window created title={title!r} at {origin_x},{origin_y}, starting webview loop")

    def _reveal_control_panel() -> None:
        _force_control_panel_visible(window, width=_DECK_WIDTH, height=_DECK_HEIGHT)

    webview.start(
        _reveal_control_panel,
        gui="edgechromium",
        debug=False,
        menu=_build_native_menu(api),
    )
    _bootlog("webview loop returned")


def run_cpharm_app_or_fallback(*, initial_view: str | None = None) -> None:
    # Phone-setup startup cleanup kill-servers adb and closes other PharmFlow
    # processes. That belongs only in phone-setup main(), never on Control
    # Panel open — opening the deck must not drop ADB or farm lanes.
    # Stale-helper reaping belongs on the farm self-heal tick, not here.

    if not is_pywebview_available():
        try:
            import webview  # noqa: F401
        except Exception as exc:
            _log_webview_fallback(_webview_fail_reason(exc, stage="import webview"))
        else:
            _log_webview_fallback(
                _webview_fail_reason(stage="is_pywebview_available returned False")
            )
        _fallback_tk(initial_view=initial_view)
        return

    # pywebview's WinForms backend needs pythonnet against a real .NET runtime.
    # netfx (built into Windows) is preferred; coreclr is auto-installed only if
    # netfx is unavailable. Without this the deck silently degrades to Tk.
    if sys.platform == "win32":
        try:
            from dotnet_provision import ensure_pythonnet_ready

            runtime = ensure_pythonnet_ready()
            if runtime is None:
                # Soft warn only — still attempt the deck; MessageBox on final fallback.
                _log_webview_fallback(
                    _webview_fail_reason(
                        stage="dotnet_provision.ensure_pythonnet_ready returned None"
                    ),
                    interactive=False,
                )
        except Exception as exc:
            _log_webview_fallback(
                _webview_fail_reason(exc, stage="dotnet_provision"),
                interactive=False,
            )

    try:
        run_cpharm_app(initial_view=initial_view)
    except Exception as exc:
        _log_webview_fallback(_webview_fail_reason(exc, stage="run_cpharm_app"))
        _fallback_tk(initial_view=initial_view)
