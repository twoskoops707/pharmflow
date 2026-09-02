"""Farm must never launch Camera / Gallery / Settings / Play Store / dialer."""

from __future__ import annotations

from automation.adb_wrapper import AdbResult, AdbWrapper
from automation.browser_adb import launch_app
from automation.farm_launch_guard import (
    blocked_launch_reason,
    extract_launch_package,
    is_denied_launch_package,
    is_farm_browser_package,
    package_from_top_line,
    parse_foreground_package,
    skip_tap_reason_for_fg,
)


def test_denies_camera_and_gallery_packages() -> None:
    assert is_denied_launch_package("com.android.camera")
    assert is_denied_launch_package("com.android.camera2")
    assert is_denied_launch_package("com.android.gallery3d")
    assert is_denied_launch_package("com.android.vending")
    assert is_denied_launch_package("com.android.settings")
    assert is_denied_launch_package("com.android.contacts")
    assert is_denied_launch_package("com.android.dialer")
    assert is_denied_launch_package("com.android.camera/com.android.camera.Camera")


def test_allows_farm_browsers() -> None:
    for pkg in (
        "org.chromium.chrome",
        "com.brave.browser",
        "org.mozilla.firefox",
        "com.duckduckgo.mobile.android",
        "com.opera.browser",
        "com.android.chrome",
    ):
        assert is_farm_browser_package(pkg)
        assert not is_denied_launch_package(pkg)


def test_blocked_am_start_and_monkey() -> None:
    assert blocked_launch_reason(
        "monkey -p com.android.camera -c android.intent.category.LAUNCHER 1"
    )
    assert blocked_launch_reason("am start -n com.android.gallery3d/.app.Gallery")
    assert blocked_launch_reason(
        "am start -a android.media.action.IMAGE_CAPTURE"
    )
    assert blocked_launch_reason(
        'am start -a android.intent.action.VIEW -d https://getdabflow.app/ '
        "-p com.android.vending"
    )
    assert blocked_launch_reason(
        "monkey -p org.chromium.chrome -c android.intent.category.LAUNCHER 1"
    ) is None
    assert blocked_launch_reason(
        "am start -a android.intent.action.VIEW -d https://getdabflow.app/ "
        "-n org.chromium.chrome/com.google.android.apps.chrome.Main"
    ) is None
    assert blocked_launch_reason("settings get global http_proxy") is None


def test_extract_monkey_package() -> None:
    assert extract_launch_package(
        "monkey -p com.android.camera -c android.intent.category.LAUNCHER 1"
    ) == "com.android.camera"


def test_skip_taps_on_home_and_camera() -> None:
    assert skip_tap_reason_for_fg("app.lawnchair")
    assert skip_tap_reason_for_fg("com.android.camera")
    assert skip_tap_reason_for_fg("com.android.gallery3d")
    assert skip_tap_reason_for_fg("org.chromium.chrome") is None
    assert skip_tap_reason_for_fg("org.mozilla.firefox") is None
    assert skip_tap_reason_for_fg("com.opera.browser") is None
    assert skip_tap_reason_for_fg("") is None


def test_parse_fg_and_top_line() -> None:
    dump = "topResumedActivity=ActivityRecord{abc u0 com.android.gallery3d/.app.Gallery t1}"
    assert parse_foreground_package(dump) == "com.android.gallery3d"
    assert package_from_top_line(
        "ACTIVITY app.lawnchair/.LawnchairLauncher b7b8166 pid=671"
    ) == "app.lawnchair"
    assert package_from_top_line("com.android.camera") == "com.android.camera"


def test_adb_shell_blocks_camera_monkey() -> None:
    adb = AdbWrapper(adb_path="adb")
    res = adb.shell("monkey -p com.android.camera -c android.intent.category.LAUNCHER 1")
    assert not res.ok
    assert "denied" in (res.stderr or "").lower()


def test_start_activity_blocks_settings() -> None:
    adb = AdbWrapper(adb_path="adb")
    res = adb.start_activity("com.android.settings/.Settings")
    assert not res.ok


def test_launch_app_refuses_camera(monkeypatch) -> None:
    calls: list[str] = []

    class _Fake:
        def shell(self, cmd: str, serial: str | None = None, timeout: float = 60.0):
            calls.append(cmd)
            return AdbResult(0, "Events injected: 1", "")

    ok = launch_app(_Fake(), "10.0.2.1:5555", "com.android.camera")  # type: ignore[arg-type]
    assert ok is False
    assert calls == []


def test_launch_app_allows_chromium(monkeypatch) -> None:
    class _Fake:
        def shell(self, cmd: str, serial: str | None = None, timeout: float = 60.0):
            return AdbResult(0, "Events injected: 1", "")

    assert launch_app(_Fake(), "10.0.2.1:5555", "org.chromium.chrome")  # type: ignore[arg-type]
