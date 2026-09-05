"""
Runtime fix for live getdabflow.app Mantis bugs (broken screenZoneMap zone names,
cooldown video slot never shown). Injected via Chrome DevTools Protocol after open_url.

Requires browser flags with ``--remote-debugging-port=9222`` (see ``build_chromium_flags``).
Disable: ``CPHARM_DABFLOW_MANTIS_PATCH=0`` or desktop_prefs ``dabflow_mantis_patch: false``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any

from adb_paths import adb_executable

log = logging.getLogger("dabflow_mantis_patch")

_SUBPROC_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

DABFLOW_HOST_RE = re.compile(r"(^|\.)getdabflow\.app$", re.I)
DEVICE_CDP_PORT = 9222

# Fixes live app.js bugs documented in docs/DABFLOW_MANTIS_LIVE_AUDIT.md
PATCH_JS = r"""
(function cpharmDabflowMantisPatch() {
  if (window.__cpharmMantisPatchV1) return true;
  window.__cpharmMantisPatchV1 = true;

  var fixedZones = {
    home: ['zone-one', 'tester'],
    timer: ['zone-two', 'zone-three', 'zone-four'],
    stats: ['zone-five', 'zone-six', 'zone-seven'],
    glass: ['zone-eight', 'zone-nine', 'zone-ten', 'zone-eleven'],
    settings: ['zone-twelve', 'zone-thirteen', 'zone-fourteen', 'zone-fifteen']
  };

  function refreshZones(zones) {
    if (!zones || typeof mantis === 'undefined') return;
    setTimeout(function() {
      zones.forEach(function(z) {
        try { mantis.push(['display', 'refresh', z]); } catch (e) {}
      });
    }, 120);
  }

  if (typeof switchScreen === 'function') {
    var prevSwitch = switchScreen;
    switchScreen = function(screenName) {
      prevSwitch.apply(this, arguments);
      if (screenName === 'settings' && typeof initializeQRCode === 'function') {
        setTimeout(initializeQRCode, 100);
      }
      refreshZones(fixedZones[screenName]);
    };
  }

  refreshZones(fixedZones.home);

  // Path1/2: live Mantis iframes must not steal functional taps.
  try {
    document.querySelectorAll(
      'iframe[src*="mantis"], iframe[id*="mantis"], iframe[class*="mantis"],'
      + ' [id*="mantis"], [class*="mantis-ad"], [id^="ad-slot-"], [data-mantis-zone], .ad-container'
    ).forEach(function(el) {
      try {
        el.style.pointerEvents = 'none';
        el.setAttribute('aria-disabled', 'true');
      } catch (e2) {}
    });
  } catch (e3) {}

  setInterval(function() {
    try {
      var modeEl = document.getElementById('timer-mode');
      if (!modeEl || !modeEl.textContent || modeEl.textContent.indexOf('Cool') < 0) return;
      var videoAd = document.getElementById('cooldown-video-ad');
      if (!videoAd || videoAd.style.display !== 'none') return;
      videoAd.style.display = 'block';
      if (!videoAd.querySelector('[data-mantis-zone]')) {
        videoAd.innerHTML = '<div data-mantis-zone="zone-two"></div>';
      }
      if (typeof mantis !== 'undefined') {
        mantis.push(['display', 'refresh', 'zone-two']);
      }
    } catch (e) {}
  }, 600);

  return true;
})();
""".strip()


def patch_enabled_from_env() -> bool:
    raw = os.environ.get("CPHARM_DABFLOW_MANTIS_PATCH", "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return True  # default ON — live deploy still has zone typos (audit 2026-07-05)


def patch_enabled_from_prefs(prefs: dict | None) -> bool | None:
    if not isinstance(prefs, dict):
        return None
    if "dabflow_mantis_patch" in prefs:
        return bool(prefs.get("dabflow_mantis_patch"))
    return None


def is_dabflow_url(url: str) -> bool:
    try:
        from urllib.parse import urlparse

        host = urlparse(url).netloc.split(":")[0]
        return bool(DABFLOW_HOST_RE.search(host))
    except Exception:
        return "getdabflow.app" in (url or "").lower()


def host_cdp_port(phone_idx: int) -> int:
    return DEVICE_CDP_PORT + max(0, min(31, int(phone_idx)))


def cdp_debug_flag(port: int = DEVICE_CDP_PORT) -> str:
    return f"--remote-debugging-port={port}"


def _adb(serial: str, *args: str, timeout: float = 12) -> subprocess.CompletedProcess:
    return subprocess.run(
        [adb_executable(), "-s", serial, *args],
        capture_output=True,
        text=True,
        errors="replace",  # device output may contain raw bytes — never crash sequence threads on decode
        timeout=timeout,
        creationflags=_SUBPROC_FLAGS,
    )


def _device_forward_targets() -> tuple[str, ...]:
    """Possible device-side CDP endpoints, best-first.

    Chrome 136+ on Android (Chromium snapshots sideloaded by this repo, e.g.
    152.0.7933.0) ignores ``--remote-debugging-port`` in the command-line file
    and binds DevTools to the ``chrome_devtools_remote`` abstract socket instead
    — forwarding ``tcp:9222`` reaches nothing, so the Mantis patch fails with
    "Remote end closed connection" and the farm earns zero (no ad injection).
    Older builds still honor TCP 9222, so keep it as a fallback.
    """
    return (
        "localabstract:chrome_devtools_remote",
        f"tcp:{DEVICE_CDP_PORT}",
    )


def ensure_adb_forward(serial: str, phone_idx: int) -> int:
    """Forward host ``9222+idx`` → device CDP (abstract socket, then TCP 9222).

    Returns host port, or raises when no device CDP endpoint answers.
    """
    host_port = host_cdp_port(phone_idx)
    last_err = ""
    for target in _device_forward_targets():
        _adb(serial, "forward", "--remove", f"tcp:{host_port}", timeout=8)
        r = _adb(serial, "forward", f"tcp:{host_port}", target, timeout=8)
        if r.returncode != 0:
            last_err = (r.stderr or r.stdout or "").strip()
            continue
        # Probe: only accept the forward when the device actually answers CDP.
        # Chrome cold-starts bind the DevTools abstract socket a moment after
        # launch (1–3 s on slow MuMu guests), so retry briefly before moving on.
        import time as _time

        ok = False
        for _ in range(4):
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{host_port}/json/version",
                    timeout=3,
                ) as resp:
                    if resp.status == 200:
                        ok = True
                        break
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                last_err = str(e)
            _time.sleep(1.5)
        if ok:
            return host_port
    raise RuntimeError(
        f"adb forward: no CDP endpoint on {serial} ({last_err or 'targets failed'})"
    )


def _list_cdp_targets(host_port: int) -> list[dict[str, Any]]:
    url = f"http://127.0.0.1:{host_port}/json"
    req = urllib.request.Request(url, headers={"User-Agent": "CPharm-cdp/1"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if isinstance(data, list):
        return [t for t in data if isinstance(t, dict)]
    return []


def _pick_dabflow_target(targets: list[dict[str, Any]]) -> dict[str, Any] | None:
    for t in targets:
        u = str(t.get("url", ""))
        if "getdabflow.app" in u.lower() and t.get("webSocketDebuggerUrl"):
            return t
    for t in targets:
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
            return t
    return None


async def _cdp_evaluate(ws_url: str, expression: str, *, timeout_sec: float = 8) -> dict:
    import websockets

    msg = {
        "id": 1,
        "method": "Runtime.evaluate",
        "params": {"expression": expression, "returnByValue": True, "awaitPromise": False},
    }
    async with websockets.connect(ws_url, open_timeout=timeout_sec, close_timeout=2) as ws:
        await ws.send(json.dumps(msg))
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout_sec)
            payload = json.loads(raw)
            if payload.get("id") == 1:
                return payload
    return {"error": "timeout waiting for CDP response"}


def inject_patch(host_port: int, *, retries: int = 8, retry_delay_sec: float = 2.0) -> dict[str, Any]:
    """Find getdabflow tab on forwarded CDP port and inject ``PATCH_JS``."""
    last_err = "no target"
    for attempt in range(max(1, retries)):
        try:
            targets = _list_cdp_targets(host_port)
            target = _pick_dabflow_target(targets)
            if not target:
                last_err = f"no CDP page target (attempt {attempt + 1}, {len(targets)} tabs)"
                if attempt + 1 < retries:
                    import time

                    time.sleep(retry_delay_sec)
                continue
            ws_url = str(target["webSocketDebuggerUrl"])
            result = asyncio.run(_cdp_evaluate(ws_url, PATCH_JS))
            err = (result.get("result") or {}).get("exceptionDetails")
            if err:
                return {"ok": False, "error": str(err), "target_url": target.get("url")}
            val = (result.get("result") or {}).get("result", {}).get("value")
            return {"ok": bool(val), "target_url": target.get("url"), "cdp": result}
        except (urllib.error.URLError, OSError, asyncio.TimeoutError) as e:
            last_err = str(e)
            if attempt + 1 < retries:
                import time

                time.sleep(retry_delay_sec)
    return {"ok": False, "error": last_err}


def apply_after_open_url(
    serial: str,
    url: str,
    phone_idx: int,
    *,
    enabled: bool | None = None,
    prefs: dict | None = None,
) -> dict[str, Any]:
    """Call after getdabflow ``open_url`` settle — forwards CDP and injects patch."""
    if enabled is None:
        pref = patch_enabled_from_prefs(prefs)
        enabled = pref if pref is not None else patch_enabled_from_env()
    if not enabled or not is_dabflow_url(url):
        return {"ok": True, "skipped": True, "reason": "disabled or not dabflow"}

    try:
        host_port = ensure_adb_forward(serial, phone_idx)
    except Exception as e:
        log.warning("dabflow patch: adb forward failed serial=%s — %s", serial, e)
        return {"ok": False, "error": f"adb forward: {e}"}

    result = inject_patch(host_port)
    if result.get("ok"):
        log.info(
            "dabflow Mantis patch injected serial=%s url=%s",
            serial,
            result.get("target_url", url),
        )
    else:
        log.warning(
            "dabflow Mantis patch failed serial=%s — %s (browser may lack --remote-debugging-port; "
            "re-run CPharmMuMuSetup GO or Re-apply hide emulator)",
            serial,
            result.get("error"),
        )
    return result


def load_desktop_prefs() -> dict:
    try:
        from config import REC_DIR

        p = REC_DIR / "desktop_prefs.json"
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def maybe_apply_after_open_url_step(
    serial: str,
    url: str,
    phone_idx: int,
    *,
    log_failure: bool = True,
) -> dict[str, Any]:
    """Shared post-open_url hook for dashboard and setup_wizard execute_steps."""
    if not is_dabflow_url(url):
        return {"skipped": True}
    try:
        prefs = load_desktop_prefs()
        result = apply_after_open_url(serial, url, phone_idx, prefs=prefs)
        if log_failure and not result.get("ok") and not result.get("skipped"):
            print(
                f"[cpharm] Mantis patch FAILED serial={serial}: {result.get('error')} "
                "(need Chromium/MuMu Browser + CPharmMuMuSetup GO)",
                flush=True,
            )
        elif result.get("ok"):
            print(
                f"[cpharm] Mantis patch OK serial={serial} tab={result.get('target_url', url)[:60]}",
                flush=True,
            )
        return result
    except Exception as exc:
        if log_failure:
            print(f"[cpharm] Mantis patch error serial={serial}: {exc}", flush=True)
        return {"ok": False, "error": str(exc)}
