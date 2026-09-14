"""CloudPhones - Unified CLI for cloud Android instance management.

All-in-one tool for:
- Connecting to cloud redroid instances
- Applying stealth protocols (fingerprint, IMEI, browser identity)
- Setting up Tor proxy for unique exit IPs
- Managing cloud phone farm

Usage (from PharmFlow.exe, or this module in a checkout):
    PharmFlow.exe --cloud-phones-cli connect --host 100.x.x.x
    PharmFlow.exe --cloud-phones-cli stealth --host 100.x.x.x --count N
    PharmFlow.exe --cloud-phones-cli tor --host 100.x.x.x --verify
    PharmFlow.exe --cloud-phones-cli setup --host 100.x.x.x
    PharmFlow.exe --cloud-phones-cli status

Omit --count to walk ADB ports until they stop answering. Do not assume 8.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

VERSION = "1.0.0"
APP_NAME = "CloudPhones"
# Consecutive unanswered ports before an omitted --count stops. A gap is the
# end of the list, not a phone-count ceiling.
_PROBE_GAP = 4
SOCKS_BASE = 9050
HTTP_BASE = 8118

# ADB path - check bundled first, then system
BUNDLED_ADB = Path(__file__).parent / "bundled" / "adb.exe"
SYSTEM_ADB = "adb"

def get_adb_path() -> str:
    """Get the ADB executable path."""
    if BUNDLED_ADB.is_file():
        return str(BUNDLED_ADB)
    return SYSTEM_ADB

# ─────────────────────────────────────────────────────────────────────────────
# Device profiles for stealth
# ─────────────────────────────────────────────────────────────────────────────

DEVICE_PROFILES = [
    {
        "brand": "samsung", "manufacturer": "samsung", "model": "SM-A546B",
        "device": "a54x", "hardware": "s5e8835",
        "fingerprint": "samsung/a54x/a54x:14/UP1A.231005.007/A546BXXU1AWF1:user/release-keys",
        "display_id": "UP1A.231005.007", "android_version": "14", "sdk_version": "34",
    },
    {
        "brand": "samsung", "manufacturer": "samsung", "model": "SM-G950F",
        "device": "dreamlte", "hardware": "samsungexynos8895",
        "fingerprint": "samsung/dreamltexx/dreamlte:9/PPR1.180610.011/G950FXXU1AQDD:user/release-keys",
        "display_id": "PPR1.180610.011", "android_version": "9", "sdk_version": "28",
    },
    {
        "brand": "google", "manufacturer": "Google", "model": "Pixel 7",
        "device": "panther", "hardware": "panther",
        "fingerprint": "google/panther/panther:14/AP2A.240805.005/12025142:user/release-keys",
        "display_id": "AP2A.240805.005", "android_version": "14", "sdk_version": "34",
    },
    {
        "brand": "google", "manufacturer": "Google", "model": "Pixel 8",
        "device": "shiba", "hardware": "shiba",
        "fingerprint": "google/shiba/shiba:14/AP2A.240805.005/12025142:user/release-keys",
        "display_id": "AP2A.240805.005", "android_version": "14", "sdk_version": "34",
    },
    {
        "brand": "OnePlus", "manufacturer": "OnePlus", "model": "CPH2451",
        "device": "aston", "hardware": "qcom",
        "fingerprint": "OnePlus/aston/aston:14/UKQ1.230924.001/172000:user/release-keys",
        "display_id": "UKQ1.230924.001", "android_version": "14", "sdk_version": "34",
    },
    {
        "brand": "Xiaomi", "manufacturer": "Xiaomi", "model": "2211133C",
        "device": "fuxi", "hardware": "qcom",
        "fingerprint": "Xiaomi/fuxi_global/fuxi:14/UKQ1.230917.001/V816:user/release-keys",
        "display_id": "UKQ1.230917.001", "android_version": "14", "sdk_version": "34",
    },
    {
        "brand": "motorola", "manufacturer": "motorola", "model": "Edge 30 Pro",
        "device": "eqs", "hardware": "qcom",
        "fingerprint": "motorola/eqs_gu/eqs:13/T1SJ33.117-48-7/7:user/release-keys",
        "display_id": "T1SJ33.117-48-7", "android_version": "13", "sdk_version": "33",
    },
    {
        "brand": "Sony", "manufacturer": "Sony", "model": "SO-51C",
        "device": "pdx234", "hardware": "qcom",
        "fingerprint": "Sony/pdx234/pdx234:14/UKQ1.230924.001/1:user/release-keys",
        "display_id": "UKQ1.230924.001", "android_version": "14", "sdk_version": "34",
    },
]

CHROME_VERSIONS = [
    "120.0.6099.144", "119.0.6045.163", "118.0.5993.112",
    "117.0.5938.60", "116.0.5845.163", "115.0.5790.166",
]

# ─────────────────────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────────────────────

def run_cmd(cmd: list[str], timeout: float = 30.0) -> tuple[bool, str]:
    """Run a command and return (success, output)."""
    try:
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kwargs)
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    except Exception as e:
        return False, str(e)


def run_adb(serial: str, *args: str, timeout: float = 30.0) -> tuple[bool, str]:
    """Run an ADB command."""
    adb = get_adb_path()
    return run_cmd([adb, "-s", serial] + list(args), timeout)


def generate_imei() -> str:
    """Generate valid IMEI with Luhn check digit."""
    import random
    tac = str(random.randint(10000000, 99999999))
    serial = str(random.randint(100000, 999999))
    digits = [int(d) for d in tac + serial]
    for i in range(0, len(digits), 2):
        digits[i] *= 2
        if digits[i] > 9:
            digits[i] -= 9
    check_digit = (10 - sum(digits) % 10) % 10
    return tac + serial + str(check_digit)


def generate_android_id() -> str:
    return secrets.token_hex(8)


def generate_serial_number(brand: str) -> str:
    import random, string
    return brand[:3].upper() + ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))


def generate_mac() -> str:
    import random
    return ':'.join(f'{random.randint(0, 255):02X}' for _ in range(6))


def _port_answers(host: str, port: int) -> bool:
    """True when adb connect reaches that host:port. Misses are disconnected."""
    serial = f"{host}:{port}"
    _ok, out = run_cmd([get_adb_path(), "connect", serial], timeout=10.0)
    text = (out or "").lower()
    if "connected" in text and "cannot" not in text and "failed" not in text:
        return True
    run_cmd([get_adb_path(), "disconnect", serial], timeout=5.0)
    return False


def resolve_instance_count(args) -> int:
    """Use an explicit --count. If omitted, walk ports until a gap. Never assume 8."""
    raw = getattr(args, "count", None)
    if raw is not None:
        try:
            n = int(raw)
        except (TypeError, ValueError):
            n = 0
        args.count = n
        return n
    host = str(getattr(args, "host", "") or "").strip()
    start = int(getattr(args, "start_port", 5555) or 5555)
    if not host:
        args.count = 0
        return 0
    found = 0
    misses = 0
    port = start
    while misses < _PROBE_GAP:
        if _port_answers(host, port):
            found = (port - start) + 1
            misses = 0
        else:
            misses += 1
        port += 1
    args.count = found
    return found


def _guest_http_tunnel_open(serial: str, http_port: int, log_path: str) -> bool:
    """True only when the guest Tor log shows this HTTP tunnel port opened."""
    needle = str(http_port)
    for _ in range(4):
        time.sleep(2)
        ok, out = run_adb(serial, "shell", "grep", "-F", needle, log_path, timeout=8.0)
        blob = (out or "").lower()
        if ok and needle in blob and ("http tunnel" in blob or "httptunnel" in blob):
            return True
    return False


def _loopback_http_proxy(http_port: int, socks_port: int) -> str:
    """Android http_proxy must be the guest HTTP tunnel, never SOCKS and never :0."""
    if http_port <= 0 or http_port == socks_port:
        return ""
    proxy = f"127.0.0.1:{http_port}"
    if not proxy.startswith("127.0.0.1:") or proxy.endswith(":0"):
        return ""
    return proxy


# ─────────────────────────────────────────────────────────────────────────────
# Core operations
# ─────────────────────────────────────────────────────────────────────────────

def cmd_connect(args):
    """Connect to cloud instances via ADB."""
    n = resolve_instance_count(args)
    if n < 1:
        print("No instance count. Pass --count, or start the instances so their ADB ports answer.")
        return 1
    print(f"=== Connecting to {n} instances at {args.host} ===\n")
    
    online = 0
    for i in range(args.count):
        port = args.start_port + i
        serial = f"{args.host}:{port}"
        print(f"  {serial}...", end=" ", flush=True)
        
        ok, out = run_adb(serial, "wait-for-device", timeout=5.0)
        if ok or "connected" in out.lower():
            ok2, boot = run_adb(serial, "shell", "getprop", "sys.boot_completed", timeout=5.0)
            if boot.strip() == "1":
                print("Online")
                online += 1
            else:
                print("Booting")
        else:
            ok3, out3 = run_cmd([get_adb_path(), "connect", serial], timeout=10.0)
            blob = (out3 or "").lower()
            handshake = (
                ok3
                and ("connected to" in blob or "already connected" in blob)
                and not any(word in blob for word in ("cannot", "failed", "unable", "error"))
            )
            booted = False
            if handshake:
                _boot_ok, boot = run_adb(
                    serial, "shell", "getprop", "sys.boot_completed", timeout=5.0
                )
                booted = (boot or "").strip() == "1"
            if booted:
                print("Online")
                online += 1
            elif handshake:
                print("Connected, still booting")
            else:
                print("Offline")
    
    print(f"\nOnline: {online}/{n}")
    if online != n:
        print("Not every instance is booted. This is not a finished connect.")
        return 1
    return 0


def cmd_stealth(args):
    """Apply stealth protocols to cloud instances."""
    import random

    n = resolve_instance_count(args)
    if n < 1:
        print("No instance count. Pass --count, or start the instances so their ADB ports answer.")
        return 1
    print(f"=== Applying Stealth to {n} instances ===\n")
    
    profiles = []
    for i in range(args.count):
        port = args.start_port + i
        serial = f"{args.host}:{port}"
        device = DEVICE_PROFILES[i % len(DEVICE_PROFILES)]
        chrome = random.choice(CHROME_VERSIONS)
        imei = generate_imei()
        android_id = generate_android_id()
        serial_num = generate_serial_number(device["brand"])
        mac = generate_mac()
        ua = f"Mozilla/5.0 (Linux; Android {device['android_version']}; {device['model']} Build/{device['display_id']}; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/{chrome} Mobile Safari/537.36"
        
        print(f"[{i+1}] {serial} ({device['model']})")
        print(f"    IMEI: {imei} | Android ID: {android_id}")
        
        online, _boot = run_adb(serial, "wait-for-device", timeout=10.0)
        if not online:
            print("    not online - stealth not applied")
            continue

        props = {
            "ro.product.brand": device["brand"],
            "ro.product.manufacturer": device["manufacturer"],
            "ro.product.model": device["model"],
            "ro.product.device": device["device"],
            "ro.hardware": device["hardware"],
            "ro.build.fingerprint": device["fingerprint"],
            "ro.build.display.id": device["display_id"],
            "ro.build.version.release": device["android_version"],
            "ro.build.version.sdk": device["sdk_version"],
            "ro.serialno": serial_num,
            "ro.kernel.qemu": "0",
            "ro.secure": "1",
            "ro.build.tags": "release-keys",
            "ro.build.type": "user",
        }
        
        fingerprint_ok = False
        for prop, value in props.items():
            ok_prop, _out = run_adb(serial, "shell", "setprop", prop, value)
            if prop == "ro.build.fingerprint":
                fingerprint_ok = ok_prop
        if not fingerprint_ok:
            print("    fingerprint was not set")
            continue
        got_ok, got_fp = run_adb(serial, "shell", "getprop", "ro.build.fingerprint")
        if not got_ok or (got_fp or "").strip() != device["fingerprint"]:
            seen = (got_fp or "").strip() or "empty"
            print(f"    fingerprint readback was {seen} - stealth not applied")
            continue
        
        run_adb(serial, "shell", "settings", "put", "secure", "android_id", android_id)
        
        chrome_flags = (
            f'chrome --user-agent="{ua}" '
            "--disable-blink-features=AutomationControlled "
            "--remote-allow-origins=* "
            "--no-first-run --disable-fre"
        )
        run_adb(serial, "shell", f"echo '{chrome_flags}' > /data/local/tmp/chrome-command-line")
        run_adb(serial, "shell", "settings", "put", "global", "user_agent", ua)
        
        run_adb(serial, "shell", "settings", "put", "secure", "wifi_mac_address", mac)
        
        run_adb(serial, "shell", "am", "force-stop", "org.chromium.chrome")
        
        profiles.append({
            "serial": serial, "device": device, "imei": imei,
            "android_id": android_id, "serial_number": serial_num,
            "mac": mac, "user_agent": ua,
        })
        print("    applied")
    
    output = Path(args.output) if args.output else Path("cloud_phones/stealth_profiles.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        json.dump(profiles, f, indent=2)
    
    print(f"\nStealth applied on {len(profiles)}/{n} instance(s)")
    print(f"Profiles saved to {output}")
    if len(profiles) != n:
        print("Stealth did not apply to every instance. This is not a finished stealth pass.")
        return 1
    return 0


def cmd_tor(args):
    """Set up Tor proxy per instance.

    Android ``global http_proxy`` is an HTTP proxy. A SOCKS-only torrc leaves
    that setting pointed at a port nothing is listening on. The guest proxy is
    written only after HTTPTunnelPort shows up in the guest Tor log.
    """
    n = resolve_instance_count(args)
    if n < 1:
        print("No instance count. Pass --count, or start the instances so their ADB ports answer.")
        return 1
    print(f"=== Setting up Tor for {n} instances ===\n")

    configured = 0

    for i in range(n):
        port = args.start_port + i
        serial = f"{args.host}:{port}"
        socks_port = SOCKS_BASE + i
        http_port = HTTP_BASE + i
        log_path = f"/data/tor_{i}/tor.log"

        print(f"[{i+1}] {serial} (SOCKS:{socks_port}, HTTP:{http_port})")

        online, _boot = run_adb(serial, "wait-for-device", timeout=10.0)
        if not online:
            print("    not online - proxy not set")
            continue

        proxy = _loopback_http_proxy(http_port, socks_port)
        if not proxy:
            print("    refusing a non-loopback proxy")
            continue

        run_adb(serial, "shell", f"mkdir -p /data/tor_{i}")
        torrc = (
            f"SocksPort 127.0.0.1:{socks_port}\n"
            f"HTTPTunnelPort 127.0.0.1:{http_port}\n"
            f"DataDirectory /data/tor_{i}\n"
            f"Log notice file {log_path}"
        )
        run_adb(serial, "shell", f"echo '{torrc}' > /data/tor_{i}/torrc")

        run_adb(serial, "shell", "su -c 'pkill tor' 2>/dev/null || true")
        time.sleep(1)
        run_adb(serial, "shell", f"su -c 'tor -f /data/tor_{i}/torrc &'")

        print("    Waiting for HTTP tunnel...", end=" ", flush=True)
        if not _guest_http_tunnel_open(serial, http_port, log_path):
            print("HTTP tunnel did not open - proxy not set")
            continue

        proxy_ok, _proxy_out = run_adb(
            serial, "shell", "settings", "put", "global", "http_proxy", proxy
        )
        if not proxy_ok:
            print("proxy was not set")
            continue
        got_ok, got = run_adb(
            serial, "shell", "settings", "get", "global", "http_proxy"
        )
        # settings put can exit 0 and still leave :0 or the host path. Count
        # the phone only when the guest read is the loopback tunnel we wrote.
        if not got_ok or (got or "").strip() != proxy:
            seen = (got or "").strip() or "empty"
            print(f"proxy readback was {seen} - not pinned")
            continue
        configured += 1

        if args.verify:
            ok, out = run_adb(serial, "shell",
                f"curl -s --socks5 127.0.0.1:{socks_port} https://api.ipify.org?format=json",
                timeout=30.0)
            if ok:
                try:
                    ip = json.loads(out).get("ip", "?")
                    print(f"Exit IP: {ip}")
                except Exception:
                    print("Running")
            else:
                print("Check manually")
        else:
            print("Configured")
    
    print(f"\nPhone proxy set on {configured}/{n} instance(s).")
    print("Exit IPs are not confirmed unless --verify succeeded.")
    if configured != n:
        print("The phone proxy was not set on every instance. This is not a finished Tor pass.")
        return 1
    return 0


def cmd_setup(args):
    """Run full setup: connect + stealth + tor.

    The Control Panel treats exit 0 as "Cloud setup finished." Exit 0 is only
    valid when every requested instance connected, kept the fingerprint, and
    read back its own loopback proxy. One phone of many is not a finish.
    """
    n = resolve_instance_count(args)
    if n < 1:
        print("No instance count. Pass --count, or start the instances so their ADB ports answer.")
        return 1
    print(f"=== Full Setup for {n} instances ===\n")

    print("[1/3] Connecting...")
    connected = cmd_connect(args)
    if connected != 0:
        print("\nSetup stopped: not every instance came online.")
        return connected

    print("\n[2/3] Applying stealth...")
    stealth = cmd_stealth(args)
    if stealth != 0:
        print("\nSetup stopped: stealth did not apply to every instance.")
        return stealth

    print("\n[3/3] Setting up Tor...")
    tor = cmd_tor(args)
    if tor != 0:
        print("\nSetup stopped: the phone proxy was not set on every instance.")
        return tor

    print(f"\n{'='*50}")
    print(f"  Setup finished for all {n} instance(s).")
    print(f"  Each fingerprint read back. Each phone proxy is that instance's loopback tunnel.")
    print(f"  Exit IPs are not confirmed from this button.")
    print(f"{'='*50}")
    return 0


def cmd_status(args):
    """Show status of connected instances."""
    print(f"=== Cloud Phone Status ===\n")
    
    adb = get_adb_path()
    ok, out = run_cmd([adb, "devices"], timeout=10.0)
    
    if not ok:
        print("Error: ADB not found")
        return 1
    
    cloud_devices = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serial = parts[0]
            if args.host in serial:
                cloud_devices.append(serial)
    
    if not cloud_devices:
        print("No cloud devices connected")
        print(
            "\nConnect from PharmFlow Extra tools, or:\n"
            f"  PharmFlow.exe --cloud-phones-cli connect --host {args.host}"
        )
        return 1
    
    for serial in sorted(cloud_devices):
        print(f"  {serial}", end=" ")
        
        _, model = run_adb(serial, "shell", "getprop", "ro.product.model", timeout=5.0)
        _, brand = run_adb(serial, "shell", "getprop", "ro.product.brand", timeout=5.0)
        _, android = run_adb(serial, "shell", "getprop", "ro.build.version.release", timeout=5.0)
        
        print(f"({brand.strip()} {model.strip()} Android {android.strip()})")
    
    print(f"\nTotal: {len(cloud_devices)} devices")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Main CLI
# ─────────────────────────────────────────────────────────────────────────────

def _add_instance_args(parser: argparse.ArgumentParser, *, host_required: bool) -> None:
    if host_required:
        parser.add_argument("--host", required=True, help="Cloud instance IP")
    parser.add_argument("--start-port", type=int, default=5555, help="Starting port")
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Instance count. Omit to walk ports until they stop answering.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=f"{APP_NAME} v{VERSION} - Cloud Android Instance Manager"
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    p_connect = subparsers.add_parser("connect", help="Connect to cloud instances")
    _add_instance_args(p_connect, host_required=True)

    p_stealth = subparsers.add_parser("stealth", help="Apply stealth protocols")
    _add_instance_args(p_stealth, host_required=True)
    p_stealth.add_argument("--output", help="Output JSON path")

    p_tor = subparsers.add_parser("tor", help="Set up Tor proxy")
    _add_instance_args(p_tor, host_required=True)
    p_tor.add_argument("--verify", action="store_true", help="Verify exit IPs")

    p_setup = subparsers.add_parser("setup", help="Full setup (connect + stealth + tor)")
    _add_instance_args(p_setup, host_required=True)
    
    p_status = subparsers.add_parser("status", help="Show connected instances")
    p_status.add_argument("--host", default="", help="Filter by host IP")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    commands = {
        "connect": cmd_connect,
        "stealth": cmd_stealth,
        "tor": cmd_tor,
        "setup": cmd_setup,
        "status": cmd_status,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
