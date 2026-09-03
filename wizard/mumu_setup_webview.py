"""
Modern pywebview (WebView2) shell for CPharmMuMuSetup.

Uses bundled HTML/CSS under ``assets/mumu_setup/``. Falls back to tkinter when pywebview
is unavailable (see ``cpharm_mumu_setup.main``).
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any

_wizard_dir = Path(__file__).resolve().parent
if str(_wizard_dir) not in sys.path:
    sys.path.insert(0, str(_wizard_dir))

import mumu_setup_core as core  # noqa: E402
from wizard_paths import wizard_assets_dir  # noqa: E402


def is_pywebview_available() -> bool:
    try:
        import webview  # noqa: F401

        return True
    except Exception:
        return False


def _mumu_setup_html_dir() -> Path:
    return wizard_assets_dir() / "mumu_setup"


def _html_url() -> str:
    index = _mumu_setup_html_dir() / "index.html"
    if not index.is_file():
        raise FileNotFoundError(f"mumu setup UI missing: {index}")
    return index.resolve().as_uri()


def _js_call(window: Any, expr: str) -> None:
    try:
        window.evaluate_js(expr)
    except Exception:
        pass


def _emit(window: Any, fn: str, payload: dict | list | str | bool | None = None) -> None:
    if payload is None:
        _js_call(window, f"window.CPharmSetup && window.CPharmSetup.{fn}()")
    else:
        _js_call(
            window,
            f"window.CPharmSetup && window.CPharmSetup.{fn}({json.dumps(payload)})",
        )


# Browser sideload catalog: (id, label, package, apk file under <root>/apks).
# farmbrowser is the stealth money browser; fenix = the new Firefox build.
_BROWSER_APKS: tuple[tuple[str, str, str, str], ...] = (
    ("chromium", "Chromium (ChromePublic)", "org.chromium.chrome", "ChromePublic-arm64.apk"),
    ("firefox", "Firefox Fenix (new browser)", "org.mozilla.firefox", "fenix-android-arm64.apk"),
    ("brave", "Brave", "com.brave.browser", "brave-android-arm64.apk"),
    ("duckduckgo", "DuckDuckGo", "com.duckduckgo.mobile.android", "duckduckgo-android.apk"),
    ("opera", "Opera", "com.opera.browser", "opera-android-arm64.apk"),
    ("farmbrowser", "FarmBrowser (stealth)", "com.farmbrowser.stealth.debug", "farmbrowser-debug.apk"),
)

# fenix shipped under two names — prefer the newer Aug build when present.
_APK_ALIASES: dict[str, tuple[str, ...]] = {
    "fenix-android-arm64.apk": ("fenix-android-arm64.apk", "fenix-153.0-arm64.apk"),
}


def _browser_apk_path(apk_name: str) -> Path | None:
    """Resolve a browser APK: embedded in the EXE first, then <root>/apks."""
    from wizard_paths import cpharm_default_install_root, meipass_dir

    root = cpharm_default_install_root()
    embedded = meipass_dir()
    for base in ((embedded,) if embedded is not None else ()) + (root,):
        p = base / "bundled" / "apks" / apk_name
        if p.is_file():
            return p
    for name in (_APK_ALIASES.get(apk_name) or (apk_name,)):
        path = root / "apks" / name
        if path.is_file():
            return path
    return root / "apks" / apk_name


def _live_adb_serials() -> list[str]:
    """Live ``adb devices`` serials (MuMu VMs are 10.0.2.x:5555 / host:port)."""
    import subprocess

    from automation.adb_paths import adb_executable

    try:
        result = subprocess.run(
            [str(adb_executable()), "devices"],
            capture_output=True,
            text=True,
            timeout=25,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [ln.split()[0] for ln in (result.stdout or "").splitlines() if "\tdevice" in ln]


class MuMuSetupApi:
    def __init__(self, *, skip_launch_cpharm: bool = False) -> None:
        self._window: Any = None
        self._busy = False
        self._lock = threading.Lock()
        self._skip_launch_cpharm = skip_launch_cpharm

    def bind_window(self, window: Any) -> None:
        self._window = window

    def get_state(self) -> dict:
        return core.initial_state()

    def get_checklist(self) -> list[dict]:
        return core.get_checklist()

    def run_action(self, action: str) -> dict:
        window = self._window
        logs: list[str] = []

        def log(m: str) -> None:
            logs.append(m)
            if window is not None:
                _emit(window, "appendLog", m)

        result = core.run_check_action(action, log)
        result["checklist"] = core.get_checklist()
        if logs:
            result["log"] = "\n".join(logs)
        phones = result.get("phones")
        if phones is not None and window is not None:
            _emit(window, "setPhones", phones)
        if window is not None:
            _emit(window, "setChecklist", result["checklist"])
        return result

    def launch_cpharm_only(self) -> dict:
        ok, msg = core.launch_cpharm()
        return {"ok": ok, "message": msg}

    def run_setup(self) -> dict:
        with self._lock:
            if self._busy:
                return {"ok": False, "error": "busy"}
            self._busy = True

        window = self._window

        def log(msg: str) -> None:
            if window is not None:
                _emit(window, "appendLog", msg)

        def work() -> None:
            ok = False
            msg = ""
            serials: list[str] = []
            try:
                if window is not None:
                    _emit(window, "setStep", {"index": 0, "state": "active"})
                ok, msg, serials = core.run_full_setup(log)
                if window is not None and serials:
                    _emit(window, "setPhones", serials)
                if window is not None:
                    _emit(window, "setChecklist", core.get_checklist())
            except Exception as exc:
                ok = False
                msg = f"Setup failed: {exc}"
                log(msg)
            finally:
                with self._lock:
                    self._busy = False
                if window is not None:
                    _emit(
                        window,
                        "onComplete",
                        {
                            "ok": ok,
                            "ready": ok,
                            "message": msg,
                            "go_label": core.go_button_label(),
                        },
                    )
                if ok and not self._skip_launch_cpharm and core.cpharm_exe_path().is_file():
                    core.launch_cpharm()

        threading.Thread(target=work, daemon=True).start()
        return {"ok": True, "started": True}

    def install_chromium(self) -> dict:
        with self._lock:
            if self._busy:
                return {"ok": False, "error": "busy"}
            self._busy = True

        window = self._window

        def log(msg: str) -> None:
            if window is not None:
                _emit(window, "appendLog", msg)

        def work() -> None:
            ok = False
            msg = ""
            serials: list[str] = []
            try:
                if window is not None:
                    _emit(window, "setStep", {"index": 1, "state": "active"})
                result = core.run_install_chromium(log)
                ok = bool(result.get("ok"))
                msg = str(result.get("message") or "")
                serials = list(result.get("serials") or [])
                if window is not None:
                    _emit(window, "setChecklist", core.get_checklist())
                    if serials:
                        _emit(window, "setPhones", serials)
            except Exception as exc:
                ok = False
                msg = f"Chromium install failed: {exc}"
                log(msg)
            finally:
                with self._lock:
                    self._busy = False
                if window is not None:
                    _emit(
                        window,
                        "onChromiumComplete",
                        {"ok": ok, "message": msg},
                    )

        threading.Thread(target=work, daemon=True).start()
        return {"ok": True, "started": True}

    def live_phone_options(self) -> list:
        """ADB-live phones the browser picker can target."""
        try:
            return [{"serial": s, "label": s} for s in _live_adb_serials()]
        except Exception:
            return []

    def browser_apk_options(self) -> list:
        """Available browsers to sideload: id, label, package, size, has_apk, installed."""
        from wizard import browser_setup  # noqa: F401

        out: list[dict] = []
        serials: list[str] = []
        try:
            serials = _live_adb_serials()
        except Exception:
            serials = []
        probe = serials[:3]
        for bid, label, pkg, apk_name in _BROWSER_APKS:
            path = _browser_apk_path(apk_name)
            size_mb = round(path.stat().st_size / 1048576.0, 1) if path.is_file() else 0
            installed = False
            for ser in probe:
                try:
                    if browser_setup.pkg_installed(ser, pkg):
                        installed = True
                        break
                except Exception:
                    continue
            out.append(
                {
                    "id": bid,
                    "label": label,
                    "package": pkg,
                    "apk": path.name if path.is_file() else apk_name,
                    "size_mb": size_mb,
                    "has_apk": path.is_file(),
                    "installed": installed,
                }
            )
        return out

    def install_browser(self, browser_id: str, serial: str = "") -> dict:
        """Sideload a chosen browser APK on one serial or every live phone.

        ``serial`` of "" / "all" targets every ADB-live phone; any other value
        must match a live serial or the install refuses with a clear message.
        """
        with self._lock:
            if self._busy:
                return {"ok": False, "error": "busy"}
            self._busy = True

        window = self._window

        def log(msg: str) -> None:
            if window is not None:
                _emit(window, "appendLog", msg)

        def work() -> None:
            ok = False
            msg = ""
            results: list[dict] = []
            serials: list[str] = []
            entry = next((e for e in _BROWSER_APKS if e[0] == browser_id), None)
            try:
                from wizard import browser_setup

                if entry is None:
                    msg = f"Unknown browser id: {browser_id}"
                    log(msg)
                    return
                _bid, label, pkg, apk_name = entry
                apk = _browser_apk_path(apk_name)
                if not apk.is_file():
                    msg = f"APK missing for {label}: {apk_name} (put it in apks/)"
                    log(msg)
                    return
                log(f"\n— Installing {label} ({apk.name}) —\n")
                live = _live_adb_serials()
                target = (serial or "").strip()
                if target and target not in ("all",) and target not in live:
                    msg = f"Phone {target} is not live (live: {live or 'none'})"
                    log(msg)
                    return
                serials = [target] if target and target != "all" else live
                if not serials:
                    msg = "No live phones — start MuMu and check ADB first"
                    log(msg)
                    return
                log(f"Installing on {target if target and target != 'all' else str(len(serials)) + ' phone(s)'}")
                for ser in serials:
                    installed_ok, note = browser_setup.install_apk(ser, apk, log)
                    if installed_ok:
                        log(f"    Verify {pkg} on {ser}…")
                        try:
                            seen = browser_setup.pkg_installed(ser, pkg)
                        except Exception:
                            seen = False
                        if seen:
                            log(f"    -> {pkg} confirmed on {ser}")
                        else:
                            note = "installed but package not confirmed"
                    if installed_ok:
                        removed = browser_setup.remove_lawnchair(ser, log)
                        if removed:
                            log(f"    Lawnchair deleted on {ser}: {', '.join(removed)}")
                    results.append({"serial": ser, "ok": bool(installed_ok), "note": note})
                ok = all(r["ok"] for r in results)
                msg = (
                    f"{label}: {len([r for r in results if r['ok']])}/{len(results)} phones OK"
                    if results
                    else "No phones to install on"
                )
                log(f"\n{msg}")
            except Exception as exc:  # noqa: BLE001
                ok = False
                msg = f"Browser install failed: {exc}"
                log(msg)
            finally:
                with self._lock:
                    self._busy = False
                if window is not None:
                    _emit(
                        window,
                        "onBrowserComplete",
                        {"ok": ok, "message": msg, "serials": serials, "results": results},
                    )

        threading.Thread(target=work, daemon=True).start()
        return {"ok": True, "started": True}


def run_webview_app(*, skip_launch_cpharm: bool = False) -> None:
    import webview

    api = MuMuSetupApi(skip_launch_cpharm=skip_launch_cpharm)
    window = webview.create_window(
        "PharmFlow — Phone Setup",
        _html_url(),
        js_api=api,
        width=980,
        height=820,
        min_size=(760, 620),
        background_color="#07090f",
    )
    api.bind_window(window)
    webview.start(gui="edgechromium", debug=False)
