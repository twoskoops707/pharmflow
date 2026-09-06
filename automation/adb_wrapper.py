"""Bundled ADB wrapper — all emulator control goes through this module."""

from __future__ import annotations

import logging
import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import Sequence

from automation.win_subprocess import hidden_run_kwargs
from wizard.wizard_paths import bundled_adb_path

logger = logging.getLogger(__name__)

_DEVICE_LINE_RE = re.compile(
    r"^(?P<serial>\S+)\s+(?P<state>\S+)(?:\s+(?P<attrs>.+))?$"
)
_ATTR_RE = re.compile(r"(\S+):(\S+)")


@dataclass
class AdbDevice:
    """One row from `adb devices -l`."""

    serial: str
    state: str
    product: str = ""
    model: str = ""
    device: str = ""
    transport_id: str = ""
    extras: dict[str, str] = field(default_factory=dict)

    @property
    def online(self) -> bool:
        return self.state == "device"


@dataclass
class AdbResult:
    """Result of an ADB shell/command invocation."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class AdbWrapper:
    """Thin wrapper around bundled adb.exe with per-serial targeting."""

    def __init__(self, adb_path: str | None = None, default_serial: str = "") -> None:
        self.adb_path = str(adb_path or bundled_adb_path())
        self.default_serial = default_serial

    def _base_cmd(self, serial: str | None = None) -> list[str]:
        cmd = [self.adb_path]
        target = serial or self.default_serial
        if target:
            cmd.extend(["-s", target])
        return cmd

    def run(
        self,
        *args: str,
        serial: str | None = None,
        timeout: float = 60.0,
    ) -> AdbResult:
        """Run an adb subcommand and return captured output."""
        cmd = self._base_cmd(serial) + list(args)
        logger.debug("ADB: %s", " ".join(cmd))
        proc: subprocess.Popen | None = None
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                **hidden_run_kwargs(),
            )
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Root cause of the recurring MuMu wedge: subprocess.run() does
                # NOT kill the child on TimeoutExpired, so every timed-out
                # `adb shell ...` left a live adb.exe client holding an open
                # transport into the guest. The CPU-starved VM queued them all,
                # and `input tap`/`input swipe` (the actual sequence steps)
                # queued behind the pile until they timed out too — sequences
                # then FAIL at tap/swipe steps. Kill the client NOW so the adb
                # server drops its queue slot and the transport stays usable.
                proc.kill()
                try:
                    proc.communicate(timeout=5)  # drain + reap before returning
                except (subprocess.TimeoutExpired, OSError):
                    pass
                logger.error("ADB timeout (child killed): %s", cmd)
                return AdbResult(124, "", "timeout")
            return AdbResult(proc.returncode, (out or "").strip(), (err or "").strip())
        except OSError as exc:
            if proc is not None and proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
            logger.error("ADB launch failed: %s", exc)
            return AdbResult(1, "", str(exc))

    def shell(
        self,
        command: str,
        serial: str | None = None,
        timeout: float = 60.0,
    ) -> AdbResult:
        """Run adb shell <command>."""
        from automation.farm_launch_guard import blocked_launch_reason

        reason = blocked_launch_reason(command)
        if reason:
            logger.warning(
                "blocked farm launch serial=%s %s cmd=%s",
                serial or self.default_serial,
                reason,
                (command or "")[:180],
            )
            return AdbResult(1, "", reason)
        return self.run("shell", command, serial=serial, timeout=timeout)

    def devices(self) -> list[tuple[str, str]]:
        """List connected devices as (serial, state) pairs."""
        return [(d.serial, d.state) for d in self.devices_detailed()]

    def devices_detailed(self) -> list[AdbDevice]:
        """Parse `adb devices -l` including product/model metadata."""
        result = self.run("devices", "-l")
        devices: list[AdbDevice] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices"):
                continue
            match = _DEVICE_LINE_RE.match(line)
            if not match:
                continue
            serial = match.group("serial")
            state = match.group("state")
            attrs_raw = match.group("attrs") or ""
            extras = {k: v for k, v in _ATTR_RE.findall(attrs_raw)}
            devices.append(
                AdbDevice(
                    serial=serial,
                    state=state,
                    product=extras.get("product", ""),
                    model=extras.get("model", ""),
                    device=extras.get("device", ""),
                    transport_id=extras.get("transport_id", ""),
                    extras=extras,
                )
            )
        return devices

    def connect(
        self,
        target: str,
        serial: str | None = None,
        timeout: float = 15.0,
    ) -> AdbResult:
        """Connect to a TCP/IP serial such as 10.0.2.x:5555.

        Default timeout is short — stale MuMu NIC targets hang for the full
        ``run()`` budget and starve the farm wait loop.
        """
        return self.run("connect", target, serial=serial, timeout=timeout)

    def disconnect(
        self,
        target: str,
        serial: str | None = None,
        timeout: float = 10.0,
    ) -> AdbResult:
        """Disconnect a TCP/IP serial."""
        return self.run("disconnect", target, serial=serial, timeout=timeout)

    def for_phone(self, serial: str) -> AdbWrapper:
        """Return a view of this wrapper bound to one device serial."""
        return AdbWrapper(adb_path=self.adb_path, default_serial=serial)

    def wait_for_device(self, serial: str, timeout: float = 120.0) -> bool:
        """Block until device is online; attempts connect for host:port serials.

        Drops offline/unauthorized transports before reconnect so a stale NIC
        entry does not block ``adb connect`` forever.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if ":" in serial:
                for dev in self.devices_detailed():
                    if dev.serial == serial and not dev.online:
                        self.disconnect(serial, timeout=5.0)
                        break
                self.connect(serial, timeout=8.0)
            for dev in self.devices_detailed():
                if dev.serial == serial and dev.online:
                    return True
            time.sleep(2.0)
        return False

    def tap(self, x: int, y: int, serial: str | None = None) -> AdbResult:
        return self.shell(f"input tap {x} {y}", serial=serial)

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
        serial: str | None = None,
    ) -> AdbResult:
        return self.shell(
            f"input swipe {x1} {y1} {x2} {y2} {duration_ms}",
            serial=serial,
        )

    def keyevent(self, code: int, serial: str | None = None) -> AdbResult:
        return self.shell(f"input keyevent {code}", serial=serial)

    def set_http_proxy(self, host: str, port: int, serial: str | None = None) -> AdbResult:
        """Set Android global HTTP proxy (honored by MuMu Browser)."""
        return self.shell(f"settings put global http_proxy {host}:{port}", serial=serial)

    def clear_http_proxy(self, serial: str | None = None) -> AdbResult:
        return self.shell("settings put global http_proxy :0", serial=serial)

    def reverse(self, remote: str, local: str, serial: str | None = None) -> AdbResult:
        """adb reverse — map guest port to host."""
        return self.run("reverse", f"tcp:{remote}", f"tcp:{local}", serial=serial)

    def reverse_remove(self, remote: str, serial: str | None = None) -> AdbResult:
        return self.run("reverse", "--remove", f"tcp:{remote}", serial=serial)

    def install(self, apk_path: str, serial: str | None = None) -> AdbResult:
        return self.run("install", "-r", apk_path, serial=serial, timeout=180.0)

    def pm_list_packages(self, serial: str | None = None) -> Sequence[str]:
        """List installed packages; retry once on timeout/failure (ARM guests).

        A failed/timed-out ``pm list`` used to return ``[]``, which callers treat
        as \"no browsers installed\" and silently skip Chromium selection.
        """
        target = serial or self.default_serial
        result = self.shell("pm list packages", serial=serial, timeout=20.0)
        if not result.ok:
            logger.warning(
                "pm list packages failed on %s rc=%s — retrying",
                target,
                result.returncode,
            )
            result = self.shell("pm list packages", serial=serial, timeout=30.0)
            if not result.ok:
                logger.warning(
                    "pm list packages retry failed on %s rc=%s — empty list",
                    target,
                    result.returncode,
                )
                return []
        pkgs: list[str] = []
        for line in result.stdout.splitlines():
            pkg = line.replace("package:", "").strip()
            if pkg:
                pkgs.append(pkg)
        return pkgs

    def start_activity(
        self,
        component: str,
        extras: dict[str, str] | None = None,
        serial: str | None = None,
    ) -> AdbResult:
        from automation.farm_launch_guard import is_denied_launch_package, package_from_component

        pkg = package_from_component(component)
        if pkg and is_denied_launch_package(pkg):
            logger.warning("blocked start_activity package=%s component=%s", pkg, component)
            return AdbResult(1, "", f"denied package {pkg}")
        cmd = f"am start -n {component}"
        if extras:
            for k, v in extras.items():
                cmd += f" -e {k} {v}"
        return self.shell(cmd, serial=serial)

    def getprop(self, prop: str, serial: str | None = None) -> str:
        # Short timeout — offline 10.0.2.x leftovers were freezing farm discover for 60s+.
        result = self.shell(f"getprop {prop}", serial=serial, timeout=3.0)
        return result.stdout.strip()

    def push(self, local: str, remote: str, serial: str | None = None) -> AdbResult:
        return self.run("push", local, remote, serial=serial, timeout=120.0)

    def enable_usb_debugging_taps(self, serial: str, taps: int = 7) -> None:
        """Tap Build number N times to enable developer options."""
        # Typical Build number location in Settings > About phone
        # Coordinates are approximate; sequences can override per device skin
        build_x, build_y = 450, 900
        for i in range(taps):
            self.tap(build_x, build_y, serial=serial)
            time.sleep(0.4)
        logger.info("Tapped Build number %d times on %s", taps, serial)
