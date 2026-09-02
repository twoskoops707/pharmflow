"""Janitor classification — what CPharm is allowed to reap."""
from __future__ import annotations

from automation.farm_process_janitor import (
    should_kill_adb_conhost,
    should_kill_flash_cmd,
    should_kill_hung_adb,
    should_kill_hung_oneshot,
    should_kill_leak_shell,
    should_kill_orphan_conhost,
)


def test_keeps_adb_server() -> None:
    assert not should_kill_hung_adb(
        "adb.exe", "adb -L tcp:5037 fork-server server --reply-fd 812", 500.0
    )


def test_kills_hung_dump_shell() -> None:
    # Threshold is 25s: a uiautomator dump alive 30s+ is wedged (the wrapper's
    # own dump timeout is 1.2s and kills its child), so 30s IS reaped.
    assert should_kill_hung_adb(
        "adb.exe", "adb -s 10.0.2.1:5555 shell uiautomator dump", 120.0
    )
    assert should_kill_hung_adb(
        "adb.exe", "adb -s 10.0.2.1:5555 shell uiautomator dump", 30.0
    )
    # Young shells are live sequence commands — never reaped.
    assert not should_kill_hung_adb(
        "adb.exe", "adb -s 10.0.2.1:5555 shell uiautomator dump", 5.0
    )


def test_kills_leak_bash_hooks() -> None:
    assert should_kill_leak_shell(
        "bash.exe",
        r"C:\Windows\system32\bash.exe .../hooks/sg-python.sh",
    )
    assert should_kill_leak_shell(
        "wsl.exe", "bash.exe ... track-telemetry.sh ..."
    )
    assert not should_kill_leak_shell("chrome.exe", "track-telemetry")


def test_kills_mumu_adb_cmd_flash() -> None:
    assert should_kill_flash_cmd(
        "cmd.exe", r"cmd /K C:\Program Files\Netease\MuMuPlayerARM\shell\nemux-shell-winui\adb.exe"
    )
    assert not should_kill_flash_cmd("cmd.exe", "cmd /c echo hi")


def test_orphan_and_adb_conhost() -> None:
    assert should_kill_orphan_conhost("conhost.exe", parent_alive=False)
    assert not should_kill_orphan_conhost("conhost.exe", parent_alive=True)
    assert should_kill_adb_conhost("conhost.exe", "adb.exe", 120.0)
    assert not should_kill_adb_conhost("conhost.exe", "adb.exe", 10.0)
    assert not should_kill_adb_conhost("conhost.exe", "tor.exe", 500.0)


def test_hung_azure_oneshot() -> None:
    assert should_kill_hung_oneshot(
        "pythonw.exe", r"C:\Users\jsmil\AppData\Local\FamFlowTools\kill_azure_telemetry.py", 4000.0
    )
    assert not should_kill_hung_oneshot(
        "pythonw.exe", r"C:\Users\jsmil\AppData\Local\FamFlowTools\kill_azure_telemetry.py", 10.0
    )
