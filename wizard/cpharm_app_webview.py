"""
Unified CPharm WebView shell — 9-step wizard matching CPharmWizard.
"""
from __future__ import annotations

import json
import sys
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


def emit_app_view(view: str) -> None:
    if _active_window is None:
        return
    _js_emit(_active_window, f"window.CPharmApp && window.CPharmApp.showView({json.dumps(view)})")


def emit_dragon_view(view: str) -> None:
    emit_app_view(view)


def _fallback_tk(*, initial_view: str | None = None) -> None:
    from cpharm_desktop import run_main_window

    run_main_window(initial_view=initial_view)


class CPharmAppApi:
    def __init__(self) -> None:
        self._window: Any = None
        self._setup_api: Any = None

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
        import cpharm_wizard_bridge as bridge

        return bridge.get_wizard_steps()

    def get_journey_state(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.get_journey_state()

    def navigate_wizard_page(self, index: int) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.navigate_wizard_page(index)

    def get_setup_state(self) -> dict:
        return self._setup_api.get_state()

    def run_setup_action(self, action: str) -> dict:
        return self._setup_api.run_action(action)

    def run_setup(self) -> dict:
        return self._setup_api.run_setup()

    def install_chromium(self) -> dict:
        return self._setup_api.install_chromium()

    def browser_apk_options(self) -> list:
        return self._setup_api.browser_apk_options()

    def install_browser(self, browser_id: str, serial: str = "") -> dict:
        return self._setup_api.install_browser(str(browser_id or ""), str(serial or ""))

    def live_phone_options(self) -> list:
        return self._setup_api.live_phone_options()

    def get_prereq_status(self) -> list:
        import cpharm_wizard_bridge as bridge

        return bridge.scan_prereqs()

    def run_install_all(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.run_install_all()

    def get_android_status(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.get_android_status()

    def run_android_install(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.run_android_install()

    def set_phone_farm_count(self, count: int) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.set_phone_farm_count(count)

    def run_create_phone_farm(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.run_create_phone_farm()

    def spin_up_test_phone(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.spin_up_test_phone_from_app()

    def run_test_url(self, url: str = "") -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.run_test_url(url or None)

    def get_site_settings(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.get_site_settings()

    def save_site_url(self, url: str) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.save_site_url(url)

    def scan_site(self, url: str = "") -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.scan_site(url)

    def apply_site_sequence(self, url: str = "") -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.apply_site_sequence(url)

    def get_automation_info(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.get_automation_info()

    def run_edit_default_sequence(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.run_edit_default_sequence()

    def open_sequence_builder(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.open_sequence_builder()

    def run_load_default_sequence(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.run_load_default_sequence()

    def run_save_default_sequence(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.run_save_default_sequence()

    def pick_sequence_json(self, save: bool = False) -> dict:
        import webview

        if not self._window:
            return {"cancelled": True}
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
            return {"cancelled": True, "error": str(exc)}
        if not result:
            return {"cancelled": True}
        path = result[0] if isinstance(result, (list, tuple)) else result
        return {"path": str(path)}

    def load_sequence_from_path(self, path: str) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.load_sequence_from_path(path)

    def save_sequence_to_path(self, path: str) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.save_sequence_to_path(path)

    def run_add_group(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.run_add_group()

    def run_humanize_all_sequences(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.run_humanize_all_sequences()

    def open_groups_manager(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.open_groups_manager()

    def get_groups_detail(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.get_groups_detail()

    def get_groups_summary(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.get_groups_summary()

    def is_dashboard_ready(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.is_dashboard_ready()

    def get_launch_summary(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.get_launch_summary()

    def get_browse_mode(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.get_browse_mode()

    def save_browse_mode(self, mode: str) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.save_browse_mode(mode)

    def start_server(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.start_server()

    def start_server_and_open_dashboard(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.start_server_and_open_dashboard()

    def run_all_groups(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.run_all_groups()

    def start_automation_one_click(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.start_automation_one_click()

    def fix_phone_internet(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.fix_phone_internet()

    def open_dashboard(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.open_dashboard()

    def open_farm_dashboard(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.open_farm_dashboard()

    def run_cloud_phone_command(self, command: str, host: str = "", count: int = 0, verify: bool = False) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.run_cloud_phone_command(command, host, count, verify=verify)

    def cloud_phone_setup(self, host: str, count: int = 8) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.cloud_phone_setup(host, count)

    def cloud_phone_status(self, host: str = "") -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.cloud_phone_status(host)

    def agent_status(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.agent_status()

    def run_cloud_agent(self, goal: str, apply: bool = False, base: str = "", model: str = "", max_steps: int = 12) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.run_cloud_agent(goal, apply=apply, base=base, model=model, max_steps=max_steps)

    def cloud_agent_config(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.cloud_agent_config()

    def save_cloud_agent_config(self, base: str = "", model: str = "", api_key: str = "") -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.save_cloud_agent_config(base, model, api_key)

    def open_advanced_wizard(self) -> dict:
        import cpharm_wizard_bridge as bridge

        bridge.open_advanced_wizard()
        return {"ok": True}

    def get_dragon_scroll(self) -> list:
        return self.get_wizard_steps()

    def navigate_chapter(self, index: int) -> dict:
        import cpharm_wizard_bridge as bridge

        bridge.navigate_wizard_chapter(index)
        return {"ok": True}



    # ── Farm start/stop (unison money stack) ──


    def start_farm(self, profile_slug: str = "", hours: float = 0) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.start_farm_from_app(str(profile_slug or ""), float(hours or 0))

    def stop_farm(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.stop_farm_from_app()

    def farm_status(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.farm_status_from_app()

    def get_farm_hud(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.get_farm_hud()

    def get_machine_capabilities(self) -> dict:
        import cpharm_wizard_bridge as bridge

        return bridge.get_machine_capabilities()

    # ── Farm settings (Advanced panels) ──

    def get_farm_settings(self) -> dict:
        from wizard.farm_settings import catalog_payload

        return catalog_payload()

    def save_farm_settings(self, updates: dict | None = None) -> dict:
        from wizard.farm_settings import save

        return save(updates or {}, note="wizard_advanced_panel")

    def reset_farm_settings(self, step: str = "", keys: list | None = None) -> dict:
        from wizard.farm_settings import reset

        return reset(step or None, keys or None)


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


def run_cpharm_app(*, initial_view: str | None = None) -> None:
    import webview
    from cpharm_version import instance_title

    api = CPharmAppApi()
    window = webview.create_window(
        instance_title("Control Panel"),
        _html_url(view=initial_view),
        js_api=api,
        width=1180,
        height=960,
        min_size=(960, 720),
        background_color="#07090f",
    )
    api.bind_window(window)
    webview.start(gui="edgechromium", debug=False, menu=_build_native_menu(api))


def run_cpharm_app_or_fallback(*, initial_view: str | None = None) -> None:
    if sys.platform == "win32":
        try:
            from setup_startup_cleanup import run_startup_cleanup

            # Main CPharm.exe must never kill running MuMu phones — only stale CPharm/adb dupes.
            run_startup_cleanup(first_time=False)
        except Exception:
            pass

    if not is_pywebview_available():
        _fallback_tk(initial_view=initial_view)
        return

    # pywebview's WinForms backend needs pythonnet against a real .NET runtime.
    # netfx (built into Windows) is preferred; coreclr is auto-installed only if
    # netfx is unavailable. Without this the deck silently degrades to Tk.
    if sys.platform == "win32":
        try:
            from dotnet_provision import ensure_pythonnet_ready

            ensure_pythonnet_ready()
        except Exception:
            pass

    try:
        run_cpharm_app(initial_view=initial_view)
    except Exception:
        try:
            err_path = Path.home() / "CPharm" / "cpharm_webview_fallback.log"
            err_path.parent.mkdir(parents=True, exist_ok=True)
            err_path.write_text(traceback.format_exc(), encoding="utf-8")
        except OSError:
            pass
        _fallback_tk(initial_view=initial_view)
