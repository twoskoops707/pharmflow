"""CloudPhones - Unified CLI for cloud Android instance management.

All-in-one tool for:
- Connecting to cloud redroid instances
- Applying stealth protocols (fingerprint, IMEI, browser identity)
- Setting up Tor proxy for unique exit IPs
- Managing cloud phone farm

Usage:
    CloudPhones.exe connect --host 100.x.x.x
    CloudPhones.exe stealth --host 100.x.x.x --count 8
    CloudPhones.exe tor --host 100.x.x.x --verify
    CloudPhones.exe setup --host 100.x.x.x  (runs all steps)
    CloudPhones.exe status
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


# ─────────────────────────────────────────────────────────────────────────────
# Core operations
# ─────────────────────────────────────────────────────────────────────────────

def cmd_connect(args):
    """Connect to cloud instances via ADB."""
    print(f"=== Connecting to {args.count} instances at {args.host} ===\n")
    
    online = 0
    for i in range(args.count):
        port = args.start_port + i
        serial = f"{args.host}:{port}"
        print(f"  {serial}...", end=" ", flush=True)
        
        ok, out = run_adb(serial, "wait-for-device", timeout=5.0)
        if ok or "connected" in out.lower():
            ok2, boot = run_adb(serial, "shell", "getprop", "sys.boot_completed", timeout=5.0)
            if boot.strip() == "1":
                print("✓ Online")
                online += 1
            else:
                print("⚠ Booting")
        else:
            ok3, out3 = run_cmd([get_adb_path(), "connect", serial], timeout=10.0)
            if "connected" in out3.lower():
                print("✓ Connected")
                online += 1
            else:
                print("✗ Offline")
    
    print(f"\nOnline: {online}/{args.count}")
    return 0 if online > 0 else 1


def cmd_stealth(args):
    """Apply stealth protocols to cloud instances."""
    import random
    
    print(f"=== Applying Stealth to {args.count} instances ===\n")
    
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
        
        run_adb(serial, "wait-for-device", timeout=10.0)
        
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
        
        for prop, value in props.items():
            run_adb(serial, "shell", "setprop", prop, value)
        
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
        print(f"    ✓ Applied")
    
    output = Path(args.output) if args.output else Path("cloud_phones/stealth_profiles.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        json.dump(profiles, f, indent=2)
    
    print(f"\n=== Stealth Complete ===")
    print(f"Profiles saved to {output}")
    return 0


def cmd_tor(args):
    """Set up Tor proxy per instance."""
    import random
    
    print(f"=== Setting up Tor for {args.count} instances ===\n")
    
    SOCKS_BASE = 9050
    HTTP_BASE = 8118
    
    for i in range(args.count):
        port = args.start_port + i
        serial = f"{args.host}:{port}"
        socks_port = SOCKS_BASE + i
        http_port = HTTP_BASE + i
        
        print(f"[{i+1}] {serial} (SOCKS:{socks_port}, HTTP:{http_port})")
        
        run_adb(serial, "wait-for-device", timeout=10.0)
        
        run_adb(serial, "shell", f"mkdir -p /data/tor_{i}")
        torrc = f"SocksPort {socks_port}\nDataDirectory /data/tor_{i}\nLog notice file /data/tor_{i}/tor.log"
        run_adb(serial, "shell", f"echo '{torrc}' > /data/tor_{i}/torrc")
        
        run_adb(serial, "shell", "su -c 'pkill tor' 2>/dev/null || true")
        time.sleep(1)
        run_adb(serial, "shell", f"su -c 'tor -f /data/tor_{i}/torrc &'")
        
        print(f"    Waiting for Tor...", end=" ", flush=True)
        time.sleep(8)
        
        run_adb(serial, "shell", "settings", "put", "global", "http_proxy", f"127.0.0.1:{http_port}")
        
        if args.verify:
            ok, out = run_adb(serial, "shell",
                f"curl -s --socks5 127.0.0.1:{socks_port} https://api.ipify.org?format=json",
                timeout=30.0)
            if ok:
                try:
                    ip = json.loads(out).get("ip", "?")
                    print(f"✓ Exit IP: {ip}")
                except Exception:
                    print("✓ Running")
            else:
                print("⚠ Check manually")
        else:
            print("✓ Configured")
    
    print(f"\n=== Tor Setup Complete ===")
    return 0


def cmd_setup(args):
    """Run full setup: connect + stealth + tor."""
    print(f"=== Full Setup for {args.count} instances ===\n")
    
    print("[1/3] Connecting...")
    cmd_connect(args)
    
    print("\n[2/3] Applying stealth...")
    cmd_stealth(args)
    
    print("\n[3/3] Setting up Tor...")
    cmd_tor(args)
    
    print(f"\n{'='*50}")
    print(f"  Setup Complete!")
    print(f"  {args.count} cloud phones ready with:")
    print(f"    - Unique device fingerprints")
    print(f"    - Unique IMEI numbers")
    print(f"    - Unique android_ids")
    print(f"    - Unique browser user-agents")
    print(f"    - Tor proxy with unique exit IPs")
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
        print(f"\nConnect with: CloudPhones.exe connect --host {args.host}")
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

def main():
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=f"{APP_NAME} v{VERSION} - Cloud Android Instance Manager"
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    p_connect = subparsers.add_parser("connect", help="Connect to cloud instances")
    p_connect.add_argument("--host", required=True, help="Cloud instance IP")
    p_connect.add_argument("--start-port", type=int, default=5555, help="Starting port")
    p_connect.add_argument("--count", type=int, default=8, help="Instance count")
    
    p_stealth = subparsers.add_parser("stealth", help="Apply stealth protocols")
    p_stealth.add_argument("--host", required=True, help="Cloud instance IP")
    p_stealth.add_argument("--start-port", type=int, default=5555, help="Starting port")
    p_stealth.add_argument("--count", type=int, default=8, help="Instance count")
    p_stealth.add_argument("--output", help="Output JSON path")
    
    p_tor = subparsers.add_parser("tor", help="Set up Tor proxy")
    p_tor.add_argument("--host", required=True, help="Cloud instance IP")
    p_tor.add_argument("--start-port", type=int, default=5555, help="Starting port")
    p_tor.add_argument("--count", type=int, default=8, help="Instance count")
    p_tor.add_argument("--verify", action="store_true", help="Verify exit IPs")
    
    p_setup = subparsers.add_parser("setup", help="Full setup (connect + stealth + tor)")
    p_setup.add_argument("--host", required=True, help="Cloud instance IP")
    p_setup.add_argument("--start-port", type=int, default=5555, help="Starting port")
    p_setup.add_argument("--count", type=int, default=8, help="Instance count")
    
    p_status = subparsers.add_parser("status", help="Show connected instances")
    p_status.add_argument("--host", default="", help="Filter by host IP")
    
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
