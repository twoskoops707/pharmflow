"""
Open http(s) links on the Android device via ``adb shell am start``.

Never uses the host desktop browser. Sequences and the dashboard should always
route URLs through ADB.

**Page load vs. launch:** ``am start`` only fires the intent; Chromium may show a blank
shell then navigate. On-device ``net::ERR_TIMED_OUT`` is usually **page load** (proxy/Tor/DNS/slow
first paint). Mitigations: host Tor + ``adb reverse`` ready before opening (see ``tor_manager``),
env waits ``CPHARM_OPEN_URL_*``, and/or add an explicit sequence ``wait`` step after ``open_url``
for heavy sites.

Prefer a generic ``ACTION_VIEW`` intent (no ``-n`` / no package) so the device
**default** handler opens the link — Samsung Internet, OEM browser, a WebView /
custom-tab shell, or another installed browser on MuMu / AVD / real phones.

Generic VIEW respects the user's default (no Chrome requirement). To force a
specific app (including Chrome when installed), pass e.g.
``browser_component="com.android.chrome/com.google.android.apps.chrome.Main"``
(optional JSON field ``browser_component`` on ``open_url`` steps).
"""

from __future__ import annotations

import subprocess

from automation.adb_paths import adb_executable

__all__ = ["am_start_view_url_argv", "_component_is_chrome", "_component_is_farmbrowser"]

# Optional shell debug (host): ``adb -s SERIAL shell dumpsys window windows`` (see mCurrentFocus);
# ``adb logcat -d -t 80`` and filter for Chromium / ActivityManager for launch or crash hints.

# Known Chrome (and Chromium-derivative) Android package names. We match on the
# package portion of an explicit component (``package/Activity``) so that
# components like ``com.example.chromecast/.X`` or random apps with "chrome"
# anywhere in their fully qualified activity name do **not** silently get the
# Chrome-specific ``create_new_tab`` extra appended. The previous heuristic
# (``"chrome" in comp.lower()``) hit false positives for those cases.
_CHROME_PACKAGE_PREFIXES = (
    "com.android.chrome",
    "com.chrome.beta",
    "com.chrome.dev",
    "com.chrome.canary",
    "com.google.android.apps.chrome",  # internal/dogfood Chrome packages
)

# FarmBrowser — CPharm's own stealth browser with proxy/identity rotation.
_FARMBROWSER_PACKAGES = (
    "com.farmbrowser.stealth.debug",
    "com.farmbrowser.stealth",
)


def _component_is_farmbrowser(component: str) -> bool:
    """True when ``component`` is a FarmBrowser package."""
    comp = (component or "").strip().lower()
    if "/" not in comp:
        return False
    pkg = comp.split("/", 1)[0]
    return pkg in _FARMBROWSER_PACKAGES


def _component_is_chrome(component: str) -> bool:
    """True when ``component`` (``package/Activity``) is a Chrome package.

    Matching is on the package half of the component, lowercased, against an
    exact-or-prefix list of known Chrome package names — so that
    ``com.android.chrome/...`` matches but ``com.foo.chromecast/...`` does not.
    """
    comp = (component or "").strip().lower()
    if "/" not in comp:
        return False
    pkg = comp.split("/", 1)[0]
    if not pkg:
        return False
    for known in _CHROME_PACKAGE_PREFIXES:
        if pkg == known or pkg.startswith(known + "."):
            return True
    return False


def _pick_farmbrowser_component(serial: str) -> str | None:
    """Return ``package/Activity`` for FarmBrowser when installed on *serial*.

    Resolves the actual Activity name so we don't hardcode it and break on
    debug vs release builds.
    """
    adb = adb_executable()

    for pkg in _FARMBROWSER_PACKAGES:
        try:
            r = subprocess.run(
                [adb, "-s", serial, "shell", "cmd", "package", "resolve-activity",
                 "--brief", "-a", "android.intent.action.VIEW", "-d", "https://example.com",
                 "-p", pkg],
                capture_output=True, text=True, errors="replace", timeout=10,
            )
            for line in (r.stdout or "").splitlines():
                line = line.strip()
                if "/" in line and pkg in line:
                    return line
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def am_start_view_url_argv(
    url: str,
    *,
    browser_component: str | None = None,
    package: str | None = None,
    new_tab: bool | None = None,
    prefer_farmbrowser: bool = True,
    serial: str | None = None,
) -> list[str]:
    """Arguments after ``adb -s SERIAL`` (i.e. ``shell am start …``).

    Prefer **no** ``-n`` component and no ``-p`` package so the device default http(s)
    handler opens the link. That is the safest fallback for Samsung Internet defaults
    and WebView/custom-tab shells whose exported activity is OEM-specific.

    When ``prefer_farmbrowser`` is ``True`` (default) and ``serial`` is given, the
    function checks if FarmBrowser is installed and routes through it instead of
    the system default — FarmBrowser has built-in proxy routing and identity rotation.

    Optional ``package`` adds ``-p`` only (activity chosen by the app) — use when you must
    target a specific browser that is not the default, while still avoiding fragile
    activity names on Samsung / OEM builds.

    ``new_tab``: when not explicitly set, the ``create_new_tab`` Chrome extra is
    only added if ``browser_component``'s package matches a known Chrome package
    (see :data:`_CHROME_PACKAGE_PREFIXES`). Pass ``new_tab=True`` to force the
    extra for non-Chrome browsers that honor it, or ``new_tab=False`` to suppress
    it for Chrome.
    """
    argv: list[str] = [
        "shell",
        "am",
        "start",
        "-a",
        "android.intent.action.VIEW",
        "-d",
        url,
    ]
    comp = (browser_component or "").strip()
    if comp and "/" in comp:
        argv.extend(["-n", comp])
        use_new_tab = new_tab
        if use_new_tab is None:
            use_new_tab = _component_is_chrome(comp)
        if use_new_tab:
            argv.extend(["--ez", "create_new_tab", "true"])
        return argv
    pkg_only = (package or "").strip()
    if pkg_only:
        argv.extend(["-p", pkg_only])
        return argv
    # Auto-target FarmBrowser when installed and caller opted in
    if prefer_farmbrowser and serial:
        fb_comp = _pick_farmbrowser_component(serial)
        if fb_comp:
            argv.extend(["-n", fb_comp])
    return argv
