"""
Real browser surface for Sequence Generator tap/swipe capture (Windows: Edge WebView2 via pywebview).

Imports ``webview`` only inside worker functions so ``setup_wizard`` and frozen smoke imports work
without pywebview installed.
"""

from __future__ import annotations

import threading
import time
from typing import Callable
from urllib.parse import urlparse

# User-facing strings (graceful degradation).
PYWEBVIEW_INSTALL_CMD = "pip install pywebview"
PYWEBVIEW_DOCS_URL = "https://pywebview.flowrl.com/guide/installation.html"

# Defensive bounds for window dimensions (mirrors webview limits we tested with).
_MIN_W = 320
_MAX_W = 4096
_MIN_H = 480
_MAX_H = 4096

# Public error codes returned from launch_browser_builder.
ERR_IMPORT = "import"
ERR_BADURL = "badurl"
ERR_BUSY = "busy"
ERR_START = "start_failed"

_state_lock = threading.Lock()
_win_ref: object | None = None
_busy_starting = False
_last_error: str = ""

TapCb = Callable[[float, float, float, float], None]
SwipeCb = Callable[[float, float, float, float, float, float, float], None]

_INJECT_JS = r"""
(function () {
  if (window.__cpharmBbInjected) { return; }
  window.__cpharmBbInjected = true;
  var api = window.pywebview && window.pywebview.api;
  if (!api) { return; }
  var st = null;
  var lastRec = 0;
  var DEB = 280;
  var MIN_SW = 14;

  function vwvh() {
    var d = document.documentElement;
    return [Math.max(1, d.clientWidth), Math.max(1, d.clientHeight)];
  }

  function safeCall(fn) {
    try { fn(); } catch (e) { /* swallow JS->Python bridge errors */ }
  }

  document.addEventListener('pointerdown', function (e) {
    if (e.pointerType === 'mouse' && e.button !== 0) { return; }
    st = { x: e.clientX, y: e.clientY, t: Date.now(), pid: e.pointerId };
  }, true);

  document.addEventListener('pointerup', function (e) {
    if (!st) { return; }
    // Ignore pointerup from a different pointer; keep st intact for the original gesture.
    if (e.pointerId !== st.pid) { return; }
    var start = st;
    st = null;
    var dt = Date.now() - start.t;
    var dx = e.clientX - start.x;
    var dy = e.clientY - start.y;
    var dist = Math.sqrt(dx * dx + dy * dy);
    var vv = vwvh();
    var now = Date.now();
    if (dist < MIN_SW && dt < 1200) {
      if (now - lastRec < DEB) { return; }
      lastRec = now;
      safeCall(function () { api.record_tap(e.clientX, e.clientY, vv[0], vv[1]); });
    } else if (dist >= MIN_SW * 2) {
      if (now - lastRec < DEB) { return; }
      lastRec = now;
      var ms = Math.max(80, Math.min(8000, dt));
      safeCall(function () { api.record_swipe(start.x, start.y, e.clientX, e.clientY, vv[0], vv[1], ms); });
    }
  }, true);

  document.addEventListener('pointercancel', function (e) {
    if (st && e.pointerId === st.pid) { st = null; }
  }, true);
})();
"""


def is_pywebview_available() -> bool:
    """Return True when ``import webview`` succeeds. Broad except to cover backend DLL issues."""
    try:
        import webview  # noqa: F401
    except Exception:
        return False
    return True


def validate_url(url: str) -> tuple[bool, str]:
    """Return (ok, normalized) for an http/https URL with a non-empty host."""
    u = (url or "").strip()
    if not u:
        return False, ""
    try:
        parsed = urlparse(u)
    except ValueError:
        return False, ""
    if parsed.scheme not in ("http", "https"):
        return False, ""
    if not parsed.netloc:
        return False, ""
    return True, u


def clamp_dims(width: int, height: int) -> tuple[int, int]:
    """Clamp window dimensions to safe bounds. Non-numeric input falls back to defaults."""
    try:
        w = int(width)
    except (TypeError, ValueError):
        w = _MIN_W
    try:
        h = int(height)
    except (TypeError, ValueError):
        h = _MIN_H
    return max(_MIN_W, min(_MAX_W, w)), max(_MIN_H, min(_MAX_H, h))


def last_error() -> str:
    """Most recent non-empty error reason, for diagnostic surfaces. May be empty."""
    with _state_lock:
        return _last_error


def _set_last_error(msg: str) -> None:
    global _last_error
    with _state_lock:
        _last_error = msg or ""


def try_load_url(url: str) -> bool:
    """If a builder window is active, navigate without tearing down the UI."""
    with _state_lock:
        w = _win_ref
    if w is None:
        return False
    try:
        w.load_url(url)
        return True
    except Exception as exc:
        _set_last_error(f"load_url failed: {exc}")
        return False


def is_session_active() -> bool:
    """True when a WebView window is open or in the process of starting."""
    with _state_lock:
        return _win_ref is not None or _busy_starting


def close() -> bool:
    """Best-effort close of the active window. Returns True if a window was asked to close."""
    with _state_lock:
        w = _win_ref
    if w is None:
        return False
    try:
        w.destroy()
    except Exception as exc:
        _set_last_error(f"close failed: {exc}")
        return False
    return True


def _run_webview_session(
    url: str,
    width: int,
    height: int,
    on_tap: TapCb,
    on_swipe: SwipeCb,
    on_started: Callable[[], None] | None = None,
) -> None:
    global _win_ref
    import webview

    class JsApi:
        def record_tap(self, x, y, vw, vh):
            try:
                on_tap(float(x), float(y), float(vw), float(vh))
            except Exception as exc:  # never let a callback exception crash the JS bridge
                _set_last_error(f"on_tap callback raised: {exc}")

        def record_swipe(self, x1, y1, x2, y2, vw, vh, ms):
            try:
                on_swipe(
                    float(x1),
                    float(y1),
                    float(x2),
                    float(y2),
                    float(vw),
                    float(vh),
                    float(ms),
                )
            except Exception as exc:
                _set_last_error(f"on_swipe callback raised: {exc}")

    api = JsApi()
    w, h = clamp_dims(width, height)
    window = webview.create_window(
        "PharmFlow — Browser builder",
        url,
        js_api=api,
        width=w,
        height=h,
    )

    def _inject(*_args, **_kwargs):
        try:
            window.evaluate_js(_INJECT_JS)
        except Exception as exc:
            _set_last_error(f"inject failed: {exc}")

    try:
        window.events.loaded += _inject
    except Exception as exc:
        # Some pywebview versions expose events differently; record but keep going.
        _set_last_error(f"events.loaded wiring failed: {exc}")

    try:
        with _state_lock:
            _win_ref = window
        if on_started is not None:
            on_started()
        # Edge Chromium (WebView2) — preferred on Windows; pywebview falls back automatically.
        webview.start(gui="edgechromium", debug=False)
    finally:
        with _state_lock:
            _win_ref = None


def launch_browser_builder(
    url: str,
    width: int,
    height: int,
    on_tap: TapCb,
    on_swipe: SwipeCb,
) -> tuple[bool, str]:
    """
    Open or focus the WebView window. If a session is already running, ``try_load_url`` is used.

    Returns ``(ok, message)``. ``message`` is empty on success, or one of:
    ``"import"``, ``"badurl"``, ``"busy"``, ``"start_failed"``.
    """
    if not is_pywebview_available():
        return False, ERR_IMPORT

    ok, normalized = validate_url(url)
    if not ok:
        return False, ERR_BADURL

    if try_load_url(normalized):
        _set_last_error("")
        return True, ""

    global _busy_starting
    with _state_lock:
        if _busy_starting:
            return False, ERR_BUSY
        _busy_starting = True
    _set_last_error("")

    started = threading.Event()

    def worker() -> None:
        global _busy_starting
        try:
            _run_webview_session(
                normalized,
                width,
                height,
                on_tap,
                on_swipe,
                on_started=started.set,
            )
        except Exception as exc:
            _set_last_error(f"webview start failed: {exc}")
        finally:
            with _state_lock:
                _busy_starting = False
            started.set()

    threading.Thread(target=worker, daemon=True, name="cpharm-browser-builder").start()
    # Wait briefly to detect immediate startup failures and avoid reporting false success.
    for _ in range(20):
        if started.wait(timeout=0.1):
            break
        with _state_lock:
            if _win_ref is not None:
                return True, ""
            if not _busy_starting:
                break
    with _state_lock:
        active = _win_ref is not None
        still_starting = _busy_starting
    if active or still_starting:
        return True, ""
    # Give callback wiring errors a moment to populate diagnostics.
    time.sleep(0.05)
    return False, ERR_START
