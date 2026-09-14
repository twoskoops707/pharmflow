"""Fingerprint engine — retail VM identity, per-phone ADB flags, and getprop verification."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import shutil
import string
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import winreg
except ImportError:  # pragma: no cover — non-Windows
    winreg = None  # type: ignore[assignment]

# Hide console flash for every adb/tool spawn (windowed EXE has no console).
_SUBPROC_FLAGS = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0) if os.name == "nt" else 0

from automation.adb_paths import adb_executable
from automation.config import (
    MUMU_DEFAULT_DPI,
    MUMU_DEFAULT_HEIGHT,
    MUMU_DEFAULT_WIDTH,
    is_skip_fingerprint,
)
from wizard.wizard_paths import detect_mumu_root

logger = logging.getLogger(__name__)

# getprop keys used for runtime anti-detection verification
GETPROP_VERIFY_KEYS: tuple[str, ...] = (
    "ro.kernel.qemu",
    "ro.product.model",
    "ro.product.brand",
    "ro.product.manufacturer",
    "ro.product.device",
    "ro.hardware",
    "ro.bootloader",
    "ro.build.fingerprint",
    "ro.debuggable",
    "ro.secure",
    "ro.adb.secure",
)

# Strings that MUST NOT appear in any fingerprint field
FORBIDDEN_SUBSTRINGS = ("mumu", "emu", "virtual", "vbox", "genymotion", "sdk_gphone", "android_x86")


def _forbidden_leak(value: str) -> bool:
    """True when a getprop value leaks emulator identity."""
    low = value.lower()
    return any(f in low for f in FORBIDDEN_SUBSTRINGS)


# Runtime verification table: (getprop, leak_detector, reason). A phone only
# passes when every populated prop is clean (leak callable returns False).
_EMULATOR_LEAK_CHECKS: tuple[tuple[str, object, str], ...] = (
    ("ro.kernel.qemu", lambda v: bool(v.strip()) and v.strip() != "0", "emulator kernel flag set"),
    ("ro.product.model", _forbidden_leak, "model leaks emulator"),
    ("ro.product.brand", _forbidden_leak, "brand leaks emulator"),
    ("ro.product.manufacturer", _forbidden_leak, "manufacturer leaks emulator"),
    ("ro.product.device", _forbidden_leak, "device leaks emulator"),
    ("ro.product.board", _forbidden_leak, "board leaks emulator"),
    ("ro.hardware", _forbidden_leak, "hardware leaks emulator"),
    ("ro.bootloader", _forbidden_leak, "bootloader leaks emulator"),
    ("ro.build.fingerprint", _forbidden_leak, "build fingerprint leaks emulator"),
    ("ro.debuggable", lambda v: v.strip() != "0", "ro.debuggable must be 0"),
    ("ro.secure", lambda v: v.strip() != "1", "ro.secure must be 1"),
    ("ro.adb.secure", lambda v: v.strip() != "1", "ro.adb.secure must be 1"),
)

# Device paths for per-phone user-agent flags (shell-writable, no root needed).
CHROME_FLAGS_PATH = "/data/local/tmp/chrome-command-line"
WEBVIEW_FLAGS_PATH = "/data/local/tmp/webview-command-line"

# Retail device profiles — real-world brand/model/hardware combos.
# Keep this pool large: Cloudflare device analytics collapse identical models.
RETAIL_PROFILES: list[dict[str, str]] = [
    {
        "brand": "samsung", "manufacturer": "samsung", "model": "SM-G950F",
        "device": "dreamlte", "hardware": "samsungexynos8895",
        "bootloader": "G950FXXU1AQDD", "board": "universal8895",
        "fingerprint": "samsung/dreamltexx/dreamlte:9/PPR1.180610.011/G950FXXU1AQDD:user/release-keys",
    },
    {
        "brand": "samsung", "manufacturer": "samsung", "model": "SM-A546B",
        "device": "a54x", "hardware": "s5e8835",
        "bootloader": "A546BXXU1AWF1", "board": "s5e8835",
        "fingerprint": "samsung/a54xxx/a54x:14/UP1A.231005.007/A546BXXU1AWF1:user/release-keys",
    },
    {
        "brand": "samsung", "manufacturer": "samsung", "model": "SM-S911B",
        "device": "dm1q", "hardware": "qcom",
        "bootloader": "S911BXXU1AWF1", "board": "kalama",
        "fingerprint": "samsung/dm1qxxx/dm1q:14/UP1A.231005.007/S911BXXU1AWF1:user/release-keys",
    },
    {
        "brand": "samsung", "manufacturer": "samsung", "model": "SM-S918B",
        "device": "dm3q", "hardware": "qcom", "bootloader": "S918BXXU1AWD9",
        "board": "kalama", "fingerprint": "samsung/dm3qxxx/dm3q:14/UP1A.231005.007/S918BXXU1AWD9:user/release-keys",
    },
    {
        "brand": "samsung", "manufacturer": "samsung", "model": "SM-G991B",
        "device": "o1s", "hardware": "exynos2100",
        "bootloader": "G991BXXU5CVF3", "board": "exynos2100",
        "fingerprint": "samsung/o1sxxx/o1s:13/TP1A.220624.014/G991BXXU5CVF3:user/release-keys",
    },
    {
        "brand": "google", "manufacturer": "Google", "model": "Pixel 6a",
        "device": "bluejay", "hardware": "bluejay", "bootloader": "bluejay-14.0-10808751",
        "board": "bluejay", "fingerprint": "google/bluejay/bluejay:14/AP2A.240805.005/12025142:user/release-keys",
    },
    {
        "brand": "google", "manufacturer": "Google", "model": "Pixel 7",
        "device": "panther", "hardware": "panther", "bootloader": "panther-1.0-8948682",
        "board": "panther", "fingerprint": "google/panther/panther:14/AP2A.240805.005/12025142:user/release-keys",
    },
    {
        "brand": "google", "manufacturer": "Google", "model": "Pixel 8",
        "device": "shiba", "hardware": "shiba", "bootloader": "shiba-14.0-10808751",
        "board": "shiba", "fingerprint": "google/shiba/shiba:14/AP2A.240805.005/12025142:user/release-keys",
    },
    {
        "brand": "OnePlus", "manufacturer": "OnePlus", "model": "CPH2449",
        "device": "ovaltine", "hardware": "qcom", "bootloader": "unknown",
        "board": "kalama", "fingerprint": "OnePlus/ovaltine/ovaltine:13/TP1A.220905.001/167000:user/release-keys",
    },
    {
        "brand": "OnePlus", "manufacturer": "OnePlus", "model": "CPH2581",
        "device": "aston", "hardware": "qcom", "bootloader": "unknown",
        "board": "pineapple", "fingerprint": "OnePlus/aston/aston:14/UKQ1.230924.001/172000:user/release-keys",
    },
    {
        "brand": "Xiaomi", "manufacturer": "Xiaomi", "model": "2201116SG",
        "device": "mona", "hardware": "qcom", "bootloader": "unknown",
        "board": "taro", "fingerprint": "Xiaomi/mona_global/mona:13/TKQ1.221013.002/V14.0.3.0:user/release-keys",
    },
    {
        "brand": "Xiaomi", "manufacturer": "Xiaomi", "model": "23013PC75G",
        "device": "fuxi", "hardware": "qcom", "bootloader": "unknown",
        "board": "kalama", "fingerprint": "Xiaomi/fuxi_global/fuxi:14/UKQ1.230917.001/V816:user/release-keys",
    },
    {
        "brand": "motorola", "manufacturer": "motorola", "model": "XT2343-3",
        "device": "eqs", "hardware": "qcom", "bootloader": "eqs_gu",
        "board": "taro", "fingerprint": "motorola/eqs_gu/eqs:13/T1SJ33.117-48-7/7:user/release-keys",
    },
    {
        "brand": "motorola", "manufacturer": "motorola", "model": "XT2301-5",
        "device": "rtwo", "hardware": "qcom", "bootloader": "rtwo",
        "board": "taro", "fingerprint": "motorola/rtwo_g/rtwo:13/T1TR33.43-20-12/12:user/release-keys",
    },
    {
        "brand": "motorola", "manufacturer": "motorola", "model": "XT2201-2",
        "device": "hiphi", "hardware": "qcom", "bootloader": "hiphi",
        "board": "taro", "fingerprint": "motorola/hiphi_g/hiphi:13/T1TH33.1-48-2/2:user/release-keys",
    },
    {
        "brand": "sony", "manufacturer": "Sony", "model": "XQ-DQ72",
        "device": "pdx234", "hardware": "qcom", "bootloader": "unknown",
        "board": "kalama", "fingerprint": "Sony/pdx234/pdx234:14/UKQ1.230924.001/1:user/release-keys",
    },
    {
        "brand": "Nothing", "manufacturer": "Nothing", "model": "A065",
        "device": "Pong", "hardware": "qcom", "bootloader": "unknown",
        "board": "taro", "fingerprint": "Nothing/Pong/Pong:14/UKQ1.230917.001/240718:user/release-keys",
    },
    {
        "brand": "OPPO", "manufacturer": "OPPO", "model": "CPH2573",
        "device": "OP5D35L1", "hardware": "mt6985", "bootloader": "unknown",
        "board": "mt6985", "fingerprint": "OPPO/CPH2573/OP5D35L1:14/UP1A.231005.007/1700:user/release-keys",
    },
    {
        "brand": "vivo", "manufacturer": "vivo", "model": "V2254A",
        "device": "PD2254", "hardware": "qcom", "bootloader": "unknown",
        "board": "kalama", "fingerprint": "vivo/PD2254/PD2254:14/UP1A.231005.007/compiler:user/release-keys",
    },
    {
        "brand": "Lenovo", "manufacturer": "Lenovo", "model": "L71061",
        "device": "heart", "hardware": "qcom", "bootloader": "unknown",
        "board": "kalama", "fingerprint": "Lenovo/heart/heart:13/TKQ1.221013.002/14.0.555:user/release-keys",
    },
    {
        "brand": "realme", "manufacturer": "realme", "model": "RMX3706",
        "device": "RE58B2L1", "hardware": "qcom", "bootloader": "unknown",
        "board": "taro", "fingerprint": "realme/RMX3706/RE58B2L1:13/TP1A.220905.001/1690:user/release-keys",
    },
    {
        "brand": "asus", "manufacturer": "asus", "model": "ASUS_AI2205_D",
        "device": "AI2205", "hardware": "qcom", "bootloader": "unknown",
        "board": "taro",        "fingerprint": "asus/WW_AI2205/ASUS_AI2205_D:13/TKQ1.220807.001/33.0820:user/release-keys",
    },
]

def _chrome_version_for_model(model: str) -> str:
    """Chrome version that matches this model's mobile UA, if known."""
    ua = MOBILE_USER_AGENTS.get(model, "")
    m = re.search(r"Chrome/([\d.]+)", ua)
    return m.group(1) if m else "124.0.0.0"


# Farm-first retail pool (MuMu ARM live models + rotation). Keys/match aliases
# are the public contract for profile_for_model / PHONE_PROFILES / dashboard.
_FARM_RETAIL_PROFILES: tuple[dict, ...] = (
    {
        "key": "xq_de72",
        "match": ("XQ_DE72", "XQ-DE72"),
        "brand": "Sony",
        "manufacturer": "Sony",
        "model": "XQ-DE72",
        "miit": "XQ-DE72",
        "android_release": "13",
        "build_id": "61.1.A.14.190",
        "chrome_version": "120.0.6099.210",
        "gpu_preset": "Adreno (TM) 660",
    },
    {
        "key": "pixel_7a",
        "match": ("GC3VE", "Pixel 7a"),
        "brand": "google",
        "manufacturer": "Google",
        "model": "Pixel 7a",
        "miit": "GC3VE",
        "android_release": "14",
        "build_id": "AP2A.240805.005",
        "chrome_version": "128.0.6613.88",
        "gpu_preset": "Adreno (TM) 730",
    },
    {
        "key": "sm_s9110",
        "match": ("SM_S9110", "SM-S9110", "SM-S911B", "SM-S911U"),
        "brand": "samsung",
        "manufacturer": "samsung",
        "model": "SM-S9110",
        "miit": "SM-S9110",
        "android_release": "14",
        "build_id": "UP1A.231005.007",
        "chrome_version": "128.0.6613.88",
        "gpu_preset": "Adreno (TM) 740",
    },
    {
        "key": "sm_s9280",
        "match": ("SM-S9280", "SM-S928B"),
        "brand": "samsung",
        "manufacturer": "samsung",
        "model": "SM-S9280",
        "miit": "SM-S9280",
        "android_release": "14",
        "build_id": "UP1A.231005.007",
        "chrome_version": "128.0.6613.88",
        "gpu_preset": "Adreno (TM) 750",
    },
    {
        "key": "sm_s9210",
        "match": ("SM-S9210", "SM-S921B"),
        "brand": "samsung",
        "manufacturer": "samsung",
        "model": "SM-S9210",
        "miit": "SM-S9210",
        "android_release": "14",
        "build_id": "AP1A.240405.023",
        "chrome_version": "128.0.6613.88",
        "gpu_preset": "Adreno (TM) 750",
    },
    {
        "key": "pixel_8",
        "match": ("Pixel 8", "GP4BC"),
        "brand": "google",
        "manufacturer": "Google",
        "model": "Pixel 8",
        "miit": "GP4BC",
        "android_release": "14",
        "build_id": "AP2A.240805.005",
        "chrome_version": "128.0.6613.88",
        "gpu_preset": "Adreno (TM) 750",
    },
    {
        "key": "pixel_8_pro",
        "match": ("Pixel 8 Pro", "GC3VE2"),
        "brand": "google",
        "manufacturer": "Google",
        "model": "Pixel 8 Pro",
        "miit": "GC3VE2",
        "android_release": "14",
        "build_id": "AP2A.240805.005",
        "chrome_version": "128.0.6613.88",
        "gpu_preset": "Adreno (TM) 750",
    },
    {
        "key": "oneplus_12",
        "match": ("CPH2581", "OnePlus 12"),
        "brand": "OnePlus",
        "manufacturer": "OnePlus",
        "model": "CPH2581",
        "miit": "CPH2581",
        "android_release": "14",
        "build_id": "TP1A.220905.001",
        "chrome_version": "128.0.6613.88",
        "gpu_preset": "Adreno (TM) 750",
    },
    {
        "key": "xiaomi_14",
        "match": ("23127PN0CC", "Xiaomi 14"),
        "brand": "Xiaomi",
        "manufacturer": "Xiaomi",
        "model": "23127PN0CC",
        "miit": "23127PN0CC",
        "android_release": "14",
        "build_id": "UKQ1.240116.001",
        "chrome_version": "128.0.6613.88",
        "gpu_preset": "Adreno (TM) 750",
    },
    {
        "key": "sm_a5460",
        "match": ("SM-A5460", "SM-A546B"),
        "brand": "samsung",
        "manufacturer": "samsung",
        "model": "SM-A5460",
        "miit": "SM-A5460",
        "android_release": "14",
        "build_id": "UP1A.231005.007",
        "chrome_version": "128.0.6613.88",
        "gpu_preset": "Adreno (TM) 644",
    },
    {
        "key": "sm_s9180",
        "match": ("SM-S9180", "SM-S918B"),
        "brand": "samsung",
        "manufacturer": "samsung",
        "model": "SM-S9180",
        "miit": "SM-S9180",
        "android_release": "13",
        "build_id": "TP1A.220624.014",
        "chrome_version": "120.0.6099.210",
        "gpu_preset": "Adreno (TM) 740",
    },
    {
        "key": "motorola_edge",
        "match": ("motorola edge 40", "XT2303-2"),
        "brand": "motorola",
        "manufacturer": "motorola",
        "model": "motorola edge 40",
        "miit": "XT2303-2",
        "android_release": "13",
        "build_id": "T1TC33.105",
        "chrome_version": "120.0.6099.210",
        "gpu_preset": "Adreno (TM) 730",
    },
)


def _retail_pool() -> tuple[dict, ...]:
    """Runtime rotation pool — farm presets first, then extra RETAIL_PROFILES.

    Farm entries carry stable ``key`` / ``match`` aliases (sm_s9110, GC3VE, …).
    Extra RETAIL_PROFILES fill variety without colliding on model/key.
    """
    pool: list[dict] = []
    seen_keys: set[str] = set()
    seen_models: set[str] = set()

    def _mark_model(s: str) -> None:
        n = (s or "").upper().replace("-", "_").replace(" ", "_")
        if n:
            seen_models.add(n)

    for p in _FARM_RETAIL_PROFILES:
        item = dict(p)
        key = str(item.get("key") or "")
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        _mark_model(str(item.get("model") or ""))
        for m in item.get("match") or ():
            _mark_model(str(m))
        pool.append(item)

    for p in RETAIL_PROFILES:
        item = dict(p)
        model = str(item.get("model") or "")
        model_norm = model.upper().replace("-", "_").replace(" ", "_")
        if model_norm and model_norm in seen_models:
            continue
        key = f"{item.get('brand', '')}-{model}".lower().replace(" ", "-")
        if key in seen_keys:
            continue
        seen_keys.add(key)
        _mark_model(model)
        item["key"] = key
        fp = str(item.get("fingerprint", ""))
        m_release = re.search(r":(\d{1,2})/", fp)
        m_build = re.search(r":\d{1,2}/([^/]+)/", fp)
        item["android_release"] = m_release.group(1) if m_release else "13"
        item["build_id"] = m_build.group(1) if m_build else "TP1A.220624.014"
        item["chrome_version"] = _chrome_version_for_model(model)
        item.setdefault("match", (model,))
        pool.append(item)
    return tuple(pool)

# Mobile UAs — model-specific, no emulator leakage
MOBILE_USER_AGENTS: dict[str, str] = {
    "SM-G950F": "Mozilla/5.0 (Linux; Android 9; SM-G950F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.45 Mobile Safari/537.36",
    "SM-A546B": "Mozilla/5.0 (Linux; Android 14; SM-A546B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "SM-S911B": "Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "SM-S918B": "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "SM-G991B": "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.163 Mobile Safari/537.36",
    "Pixel 6a": "Mozilla/5.0 (Linux; Android 14; Pixel 6a) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Pixel 7": "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Pixel 8": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "CPH2449": "Mozilla/5.0 (Linux; Android 13; CPH2449) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.163 Mobile Safari/537.36",
    "CPH2581": "Mozilla/5.0 (Linux; Android 14; CPH2581) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "2201116SG": "Mozilla/5.0 (Linux; Android 13; 2201116SG) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.163 Mobile Safari/537.36",
    "23013PC75G": "Mozilla/5.0 (Linux; Android 14; 23013PC75G) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "XT2343-3": "Mozilla/5.0 (Linux; Android 13; moto g84 5G) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.80 Mobile Safari/537.36",
    "XT2301-5": "Mozilla/5.0 (Linux; Android 13; XT2301-5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "XT2201-2": "Mozilla/5.0 (Linux; Android 13; XT2201-2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.163 Mobile Safari/537.36",
    "XQ-DQ72": "Mozilla/5.0 (Linux; Android 14; XQ-DQ72) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "A065": "Mozilla/5.0 (Linux; Android 14; A065) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "CPH2573": "Mozilla/5.0 (Linux; Android 14; CPH2573) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "V2254A": "Mozilla/5.0 (Linux; Android 14; V2254A) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "L71061": "Mozilla/5.0 (Linux; Android 13; L71061) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "RMX3706": "Mozilla/5.0 (Linux; Android 13; RMX3706) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.163 Mobile Safari/537.36",
    "ASUS_AI2205_D": "Mozilla/5.0 (Linux; Android 13; ASUS_AI2205_D) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.163 Mobile Safari/537.36",
}

# Built after MOBILE_USER_AGENTS so chrome_version can be derived.
RETAIL_PROFILE_POOL: tuple[dict, ...] = _retail_pool()
# Backward-compatible public name used by the legacy automation contract.
# Keep it as a snapshot of the same ARM-aware pool, not a second profile source.
PHONE_PROFILES: tuple[dict, ...] = RETAIL_PROFILE_POOL

WEBGL_RENDERERS: list[str] = [
    "Qualcomm Adreno (TM) 740",
    "ARM Mali-G78",
    "Qualcomm Adreno (TM) 650",
    "Samsung Xclipse 920",
]


@dataclass
class FingerprintProfile:
    """Full 6-layer anti-detection identity."""

    brand: str
    manufacturer: str
    model: str
    device: str
    hardware: str
    bootloader: str
    board: str
    build_fingerprint: str
    imei: str
    mac: str
    android_id: str
    serial_number: str
    user_agent: str
    webgl_renderer: str
    canvas_seed: str
    browser_flags: list[str] = field(
        default_factory=lambda: ["--disable-blink-features=AutomationControlled"]
    )

    def to_setting_patch(self) -> dict[str, Any]:
        """Layer 1: VM fingerprint via MuMu setting.json (classic + ARM PhoneProp)."""
        brand_display = self.brand
        model_sku = self.model
        return {
            # Classic / legacy keys
            "phone_brand": brand_display,
            "phone_manufacturer": self.manufacturer,
            "phone_model": model_sku,
            "phone_device": self.device,
            "phone_imei": self.imei,
            "mac_address": self.mac,
            "android_id": self.android_id,
            "serial_number": self.serial_number,
            "phone_serial": self.serial_number,
            "user_agent": self.user_agent,
            "ro_hardware": self.hardware,
            "ro_bootloader": self.bootloader,
            "ro_build_fingerprint": self.build_fingerprint,
            "browser_command_line": browser_flags_for_profile(self),
            "canvas_noise_seed": self.canvas_seed,
            "webgl_renderer": self.webgl_renderer,
            # MuMu Player ARM schema (guest boots from PhoneProp.*)
            "PhonePropMode": "Custom",
            "PhoneProp": {
                "Brand": brand_display,
                "Model": model_sku,
                "Miit": model_sku,
            },
            "PhoneIMEI": self.imei,
            "phonePropBrand": brand_display,
            "phonePropModel": model_sku,
            "phoneModel": model_sku,
            "phonePropMiit": model_sku,
            "phonePropIMEI": self.imei,
            "macAddress": self.mac,
            "simulationProps": f"android_id={self.android_id}",
        }

    def kernel_props(self) -> dict[str, str]:
        """Layer 2: Kernel getprop values."""
        return {
            "ro.product.model": self.model,
            "ro.product.brand": self.brand,
            "ro.product.manufacturer": self.manufacturer,
            "ro.product.device": self.device,
            "ro.product.board": self.board,
            "ro.build.fingerprint": self.build_fingerprint,
            "ro.bootloader": self.bootloader,
            "ro.hardware": self.hardware,
            "ro.kernel.qemu": "",
            "ro.debug.atrace.tags.enableflags": "0",
            "persist.sys.usb.config": "mtp,adb",
        }

    def security_props(self) -> dict[str, str]:
        """Layer 3: ADB security flags."""
        return {
            "ro.adb.secure": "1",
            "ro.secure": "1",
            "ro.debuggable": "0",
        }


@dataclass
class AntiDetectionReport:
    """Layer 6: Runtime verification result."""

    phone: str
    passed: bool
    checks: dict[str, bool]
    props: dict[str, str]
    checked_at: str = ""
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phone": self.phone,
            "passed": self.passed,
            "checks": self.checks,
            "props": self.props,
            "checked_at": self.checked_at,
            "failures": self.failures,
        }


def _sanitize(value: str) -> str:
    """Remove forbidden emulator strings from a value."""
    out = value
    for bad in FORBIDDEN_SUBSTRINGS:
        out = re.sub(re.escape(bad), "", out, flags=re.IGNORECASE)
    return out.strip() or "unknown"


def generate_imei() -> str:
    tac = random.choice(["35332510", "35693803", "35226005", "35428910", "35875505"])
    serial = "".join(str(random.randint(0, 9)) for _ in range(6))
    base = tac + serial
    # Luhn over the 14-digit body: double every second digit from the right.
    # (A chained ternary previously applied the >9 fold even on non-doubled digits.)
    total = 0
    for i, ch in enumerate(reversed(base)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    check = (10 - (total % 10)) % 10
    return base + str(check)


def generate_mac() -> str:
    octets = [0x02, random.randint(0, 255), random.randint(0, 255),
              random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)]
    return ":".join(f"{b:02X}" for b in octets)


def generate_android_id() -> str:
    return "".join(random.choice("0123456789abcdef") for _ in range(16))


def generate_serial() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=11))


def _profile_from_base(
    base: dict[str, str],
    *,
    android_id: str = "",
    imei: str = "",
    user_agent: str = "",
) -> FingerprintProfile:
    model = base["model"]
    return FingerprintProfile(
        brand=base["brand"],
        manufacturer=base["manufacturer"],
        model=model,
        device=base["device"],
        hardware=base["hardware"],
        bootloader=base["bootloader"],
        board=base["board"],
        build_fingerprint=base["fingerprint"],
        imei=imei or generate_imei(),
        mac=generate_mac(),
        android_id=android_id or generate_android_id(),
        serial_number=generate_serial(),
        user_agent=user_agent
        or MOBILE_USER_AGENTS.get(model, list(MOBILE_USER_AGENTS.values())[0]),
        webgl_renderer=random.choice(WEBGL_RENDERERS),
        canvas_seed=generate_android_id(),
    )


def random_profile() -> FingerprintProfile:
    return _profile_from_base(random.choice(RETAIL_PROFILES))


def profile_matching_model(
    model: str,
    *,
    brand: str = "",
    android_id: str = "",
    imei: str = "",
    user_agent: str = "",
) -> FingerprintProfile:
    """Build a MuMu FingerprintProfile aligned with the browser scramble model.

    ARM PhoneProp only applies on cold boot, but writing the *same* model/IMEI/
    android_id as the live browser identity keeps setting.json coherent and
    prepares the next restart for a matching getprop.
    """
    want = (model or "").strip()
    base = next((p for p in RETAIL_PROFILES if p.get("model") == want), None)
    if base is None and brand:
        brand_l = brand.strip().lower()
        base = next(
            (p for p in RETAIL_PROFILES if p.get("brand", "").lower() == brand_l),
            None,
        )
    if base is None:
        base = random.choice(RETAIL_PROFILES)
    return _profile_from_base(
        base, android_id=android_id, imei=imei, user_agent=user_agent
    )


def find_setting_json(vms_dir: Path, instance_name: str) -> Path | None:
    candidates = [vms_dir / instance_name / "setting.json", vms_dir / instance_name / "configs" / "setting.json"]
    if vms_dir.is_dir():
        for child in vms_dir.iterdir():
            if instance_name.lower() in child.name.lower():
                for rel in ("setting.json", "configs/setting.json"):
                    p = child / rel
                    if p.is_file():
                        candidates.append(p)
    for p in candidates:
        if p.is_file():
            return p
    return None


def find_vm_dir(vms_dir: Path, instance_name: str) -> Path | None:
    direct = vms_dir / instance_name
    if direct.is_dir():
        return direct
    if vms_dir.is_dir():
        for child in vms_dir.iterdir():
            if instance_name.lower() in child.name.lower() and child.is_dir():
                return child
    return None


def adb_flags_path(vms_dir: Path, instance_name: str) -> Path | None:
    vm = find_vm_dir(vms_dir, instance_name)
    return (vm / "adb_flags") if vm else None


def _scrub_setting_json(data: dict[str, Any]) -> dict[str, Any]:
    """Remove all mumu/emu/virtual strings from setting.json values."""
    cleaned: dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, str):
            cleaned[k] = _sanitize(v)
        else:
            cleaned[k] = v
    return cleaned


def _apply_host_gpu_accel(data: dict[str, Any]) -> None:
    """Keep MuMu compositing on host GPU; keep guest CPU/RAM lean.

    GPU High / DirectX offloads *drawing*. Guest cores/RAM stay low so 4–6
    phones do not pin the host. Override with PHARMFLOW_MUMU_CPU_CORES /
    PHARMFLOW_MUMU_RAM_MB if needed.
    """
    mode = (os.environ.get("PHARMFLOW_MUMU_GPU_MODE") or "High").strip() or "High"
    if mode.lower() in ("0", "off", "false", "no", "skip"):
        return
    gp = data.get("GpuProp") if isinstance(data.get("GpuProp"), dict) else {}
    gp = dict(gp)
    gp["Mode"] = mode
    data["GpuProp"] = gp
    engine = (os.environ.get("PHARMFLOW_MUMU_RENDER_ENGINE") or "").strip()
    data["RenderEngine"] = engine or "DirectX"
    apply_farm_guest_rails(data)


def _guest_cpu_ram() -> tuple[int, int]:
    """Lean farm default: 2 cores / 1024 MB. Env can go 1–2 CPU, 1024–2048 MB."""
    try:
        want_cpu = int(os.environ.get("PHARMFLOW_MUMU_CPU_CORES") or 2)
    except (TypeError, ValueError):
        want_cpu = 2
    try:
        want_ram = int(os.environ.get("PHARMFLOW_MUMU_RAM_MB") or 1024)
    except (TypeError, ValueError):
        want_ram = 1536
    return max(1, min(2, want_cpu)), max(1024, min(2048, want_ram))


def apply_farm_guest_rails(data: dict[str, Any]) -> dict[str, Any]:
    """Phone (not tablet), rooted, writable disk, lowest practical CPU/RAM.

    Called whenever PharmFlow.exe creates or fingerprints a MuMu VM.
    """
    data["DeviceRoot"] = True
    data["adb_debug"] = 1
    data["usb_debugging"] = True
    data["orientation"] = 1  # portrait phone
    data["is_tablet"] = False
    data["tablet"] = False
    data["phone_type"] = "phone"
    data["device_type"] = "phone"
    data["resolution_width"] = int(data.get("resolution_width") or MUMU_DEFAULT_WIDTH)
    data["resolution_height"] = int(data.get("resolution_height") or MUMU_DEFAULT_HEIGHT)
    data["resolution_dpi"] = int(data.get("resolution_dpi") or MUMU_DEFAULT_DPI)
    # Never let a farm guest boot as a landscape tablet.
    if int(data.get("resolution_width") or 0) > int(data.get("resolution_height") or 0):
        data["resolution_width"], data["resolution_height"] = (
            int(data["resolution_height"]),
            int(data["resolution_width"]),
        )
    if int(data.get("resolution_width") or 0) >= 1200 and int(data.get("resolution_height") or 0) >= 1800:
        data["resolution_width"] = MUMU_DEFAULT_WIDTH
        data["resolution_height"] = MUMU_DEFAULT_HEIGHT
        data["resolution_dpi"] = MUMU_DEFAULT_DPI

    # Writable guest storage (MuMu key names vary by build — set all common ones).
    data["disk_readonly"] = False
    data["readonly"] = False
    data["nand_writable"] = True
    data["force_nand_writable"] = True
    data["shared_folder"] = True
    data["enable_shared_folder"] = True

    want_cpu, want_ram = _guest_cpu_ram()
    preset = data.get("PerformancePreset") if isinstance(data.get("PerformancePreset"), dict) else {}
    preset = dict(preset)
    preset["Cpu"] = want_cpu
    preset["MemoryOfMB"] = want_ram
    data["PerformancePreset"] = preset
    # Custom + lean cores; GPU Mode stays High separately (compositing).
    perf = (os.environ.get("PHARMFLOW_MUMU_PERFORMANCE_TYPE") or "Custom").strip() or "Custom"
    if perf.lower() not in ("0", "off", "skip", "keep"):
        data["PerformanceType"] = perf
    return data


def apply_farm_guest_rails_file(path: Path) -> bool:
    """Patch one MuMu setting.json with farm guest rails. Returns True if written."""
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        data = {}
    apply_farm_guest_rails(data)
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except OSError as exc:
        logger.warning("farm guest rails write failed %s: %s", path, exc)
        return False


def apply_nx_mumu_guest_rails(vm_dir: Path) -> list[str]:
    """Patch MuMu 12+/15 (nx) configs + .nemu — setting.json is not used there."""
    notes: list[str] = []
    if not vm_dir.is_dir():
        return ["nx_vm_missing"]
    cpu, ram_mb = _guest_cpu_ram()
    ram_gb = f"{ram_mb / 1024.0:.6f}"
    configs = vm_dir / "configs"

    vm_cfg = configs / "vm_config.json"
    if vm_cfg.is_file():
        try:
            data = json.loads(vm_cfg.read_text(encoding="utf-8-sig"))
            vm = data.setdefault("vm", {}) if isinstance(data, dict) else {}
            if isinstance(vm, dict):
                vm["cpu"] = str(cpu)
                vm["memory"] = ram_gb
                vm["root"] = "true"
                sys_vdi = vm.get("system_vdi")
                if not isinstance(sys_vdi, dict):
                    sys_vdi = {}
                    vm["system_vdi"] = sys_vdi
                sys_vdi["sharable"] = "Writable"
                vm_cfg.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
                notes.append(f"nx_vm_config cpu={cpu} ram_gb={ram_gb}")
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            notes.append(f"nx_vm_config_err:{exc}")

    cust = configs / "customer_config.json"
    if cust.is_file():
        try:
            data = json.loads(cust.read_text(encoding="utf-8-sig"))
            setting = data.setdefault("setting", {}) if isinstance(data, dict) else {}
            if isinstance(setting, dict):
                perf = setting.setdefault("performance", {})
                if isinstance(perf, dict):
                    mode = perf.setdefault("mode", {})
                    if isinstance(mode, dict):
                        mode["choose"] = "performance.mode.custom"
                        custom = mode.setdefault("custom", {})
                        if isinstance(custom, dict):
                            custom["cpu"] = str(cpu)
                            custom["memory"] = ram_gb
                frames = setting.setdefault("frame_setting", {})
                if isinstance(frames, dict):
                    frames["desired_framerate"] = "15"
                    frames["fps_limit_low"] = "15"
                    frames["dynamic_adjust_framerate"] = "1"
                vol = setting.setdefault("volume_setting", {})
                if isinstance(vol, dict):
                    sysvol = vol.setdefault("system_volume", {})
                    if isinstance(sysvol, dict):
                        sysvol["close"] = "1"
                other = setting.setdefault("other_optimization", {})
                if isinstance(other, dict):
                    other["memory_optimization"] = "1"
                res = setting.setdefault("resolution", {})
                if isinstance(res, dict):
                    mode = res.setdefault("mode", {})
                    if isinstance(mode, dict):
                        mode["choose"] = "resolution.mode.phone"
                cust.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
                notes.append("nx_customer_config lean+mute")
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            notes.append(f"nx_customer_err:{exc}")

    shell = configs / "shell_config.json"
    if shell.is_file():
        try:
            data = json.loads(shell.read_text(encoding="utf-8-sig"))
            rend = data.setdefault("renderer", {}) if isinstance(data, dict) else {}
            if isinstance(rend, dict):
                rend["fps_limit"] = "15"
                rend["fps_limit_low"] = "15"
                rend["fps_limit_real"] = "15"
                rend["audio_out_hardware_off"] = "1"
                shell.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
                notes.append("nx_shell fps15+audio_off")
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            notes.append(f"nx_shell_err:{exc}")

    for nemu in vm_dir.glob("*.nemu"):
        try:
            text = nemu.read_text(encoding="utf-8")
        except OSError as exc:
            notes.append(f"nemu_read_err:{exc}")
            continue
        updated = re.sub(r'<Memory RAMSize="\d+"/>', f'<Memory RAMSize="{ram_mb}"/>', text, count=1)
        updated = re.sub(r'<CPU count="\d+">', f'<CPU count="{cpu}">', updated, count=1)
        updated = updated.replace('enabledIn="true"', 'enabledIn="false"')
        updated = updated.replace('enabledOut="true"', 'enabledOut="false"')
        if updated != text:
            try:
                nemu.write_text(updated, encoding="utf-8")
                notes.append(f"nemu cpu={cpu} ram={ram_mb} audio_off")
            except OSError as exc:
                notes.append(f"nemu_write_err:{exc}")
    return notes


def apply_farm_guest_rails_vm(vm_dir: Path) -> list[str]:
    """Apply rails to one VM folder (classic setting.json and/or MuMu 15 nx)."""
    notes: list[str] = []
    setting = vm_dir / "setting.json"
    if not setting.is_file():
        alt = vm_dir / "configs" / "setting.json"
        setting = alt if alt.is_file() else setting
    if setting.is_file() and apply_farm_guest_rails_file(setting):
        notes.append("classic_setting.json")
    notes.extend(apply_nx_mumu_guest_rails(vm_dir))
    return notes


def ensure_windows_gpu_prefs_for_mumu(mumu_root: Path | None = None) -> list[str]:
    """Pin MuMu shell/manager to Windows High-performance GPU (GpuPreference=2)."""
    notes: list[str] = []
    if mumu_root:
        root = Path(mumu_root)
    else:
        env = (os.environ.get("PHARMFLOW_MUMU_ROOT") or "").strip()
        root = Path(env) if env else (detect_mumu_root() or Path(r"C:\Program Files\Netease\MuMuPlayer"))
    exes = [
        root / "shell" / "MuMuManager.exe",
        root / "nx_main" / "MuMuManager.exe",
        root / "nx_main" / "MuMuNxMain.exe",
        root / "shell" / "nemux-shell-winui.exe",
        root / "manager" / "nemux-shell-winui.Manager.exe",
        root / "shell" / "nemu_renderer_inspector.exe",
    ]
    if winreg is None:
        return ["winreg_unavailable"]
    try:
        key = winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\DirectX\UserGpuPreferences",
        )
    except OSError as exc:
        return [f"gpu_pref_key_err:{exc}"]
    for exe in exes:
        if not exe.is_file():
            continue
        path = str(exe)
        try:
            winreg.SetValueEx(key, path, 0, winreg.REG_SZ, "GpuPreference=2;")
            notes.append(f"gpu_pref_high:{exe.name}")
        except OSError as exc:
            notes.append(f"gpu_pref_err:{exe.name}:{exc}")
    try:
        winreg.CloseKey(key)
    except OSError:
        pass
    return notes


def reassert_all_vm_gpu_accel(vms_dir: Path) -> list[str]:
    """Rewrite GPU/lean rails on every VM (classic setting.json and MuMu 15 nx)."""
    fixes: list[str] = []
    if not vms_dir.is_dir():
        return ["vms_dir_missing"]
    for vm in sorted(vms_dir.iterdir()):
        if not vm.is_dir():
            continue
        has_guest = (
            (vm / "setting.json").is_file()
            or (vm / "configs" / "setting.json").is_file()
            or (vm / "configs" / "vm_config.json").is_file()
            or any(vm.glob("*.nemu"))
        )
        if not has_guest:
            continue
        notes = apply_farm_guest_rails_vm(vm)
        if notes:
            fixes.append(f"{vm.name}:{','.join(notes[:4])}")
        path = vm / "setting.json"
        if not path.is_file():
            alt = vm / "configs" / "setting.json"
            path = alt if alt.is_file() else path
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        before = (
            str((data.get("GpuProp") or {}).get("Mode") if isinstance(data.get("GpuProp"), dict) else ""),
            str(data.get("PerformanceType") or ""),
            str(data.get("RenderEngine") or ""),
        )
        _apply_host_gpu_accel(data)
        after = (
            str((data.get("GpuProp") or {}).get("Mode") if isinstance(data.get("GpuProp"), dict) else ""),
            str(data.get("PerformanceType") or ""),
            str(data.get("RenderEngine") or ""),
        )
        if before != after:
            try:
                path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                fixes.append(f"{vm.name}:gpu {before}->{after}")
            except OSError as exc:
                fixes.append(f"{vm.name}:write_err:{exc}")
    return fixes


def patch_setting_json(path: Path, profile: FingerprintProfile) -> None:
    if is_skip_fingerprint():
        return
    # MuMu often writes setting.json with a UTF-8 BOM — accept both.
    raw = path.read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    data.update(profile.to_setting_patch())
    data = _scrub_setting_json(data)
    _apply_host_gpu_accel(data)
    apply_farm_guest_rails(data)
    # Farm isolation/wipe needs root adbd; never leave DeviceRoot off after Layer-1 patch.
    data["DeviceRoot"] = True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Layer 1 patched: %s", path)


def write_adb_flags(vms_dir: Path, instance_name: str, profile: FingerprintProfile) -> None:
    """Layers 2+3: kernel getprop + security flags in adb_flags."""
    if is_skip_fingerprint():
        return
    path = adb_flags_path(vms_dir, instance_name)
    if not path:
        logger.warning("adb_flags not found for %s", instance_name)
        return
    lines: list[str] = []
    for k, v in {**profile.kernel_props(), **profile.security_props()}.items():
        lines.append(f"{k}={_sanitize(v)}")
    lines.append(f"browser_flags={browser_flags_for_profile(profile)}")
    lines.append(f"user_agent={profile.user_agent}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Layers 2+3 patched: %s", path)


def _apply_browser_ua_shell_fn(shell_fn: Callable[[str], str], profile: FingerprintProfile) -> None:
    """Layer 4 (VM-config path): browser UA via an injected shell callable."""
    if is_skip_fingerprint():
        return
    shell_fn(f"settings put global user_agent '{profile.user_agent}'")
    shell_fn(f"settings put secure user_agent '{profile.user_agent}'")
    flags = browser_flags_for_profile(profile)
    shell_fn(f"settings put global pharmflow_browser_flags '{flags}'")


def apply_browser_fingerprint_adb(
    serial: str,
    profile: dict | None = None,
    *,
    farm_index: int | None = None,
    enable_dabflow_cdp: bool | None = None,
) -> dict:
    """Layer 4 (per-phone): write retail browser UA/flags over ADB.

    Mirrors the proven PharmFlow implementation: profile resolution by serial
    (with farm_index fallback), optional dabflow CDP flag, chromium flags
    push, and a fresh android_id per application.
    """
    prof = profile or profile_for_serial(serial, farm_index=farm_index)
    ua = build_mobile_user_agent(prof)
    cdp_port: int | None = None
    if enable_dabflow_cdp is not False:
        try:
            try:
                from automation.dabflow_mantis_client_patch import (
                    DEVICE_CDP_PORT,
                    patch_enabled_from_env,
                    patch_enabled_from_prefs,
                )
            except ImportError:  # flat import when automation/ is on sys.path
                from dabflow_mantis_client_patch import (
                    DEVICE_CDP_PORT,
                    patch_enabled_from_env,
                    patch_enabled_from_prefs,
                )

            on = enable_dabflow_cdp
            if on is None:
                try:
                    from automation.dabflow_mantis_client_patch import load_desktop_prefs

                    pref = patch_enabled_from_prefs(load_desktop_prefs())
                    on = pref if pref is not None else patch_enabled_from_env()
                except Exception:
                    on = patch_enabled_from_env()
            if on:
                cdp_port = DEVICE_CDP_PORT
        except Exception:
            cdp_port = None
    written = write_chromium_flags(serial, prof, cdp_port=cdp_port)
    try:
        _shell(serial, "settings", "put", "secure", "android_id", _random_android_id(), timeout=12)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {
        "user_agent_written": written,
        "profile": prof["key"],
        "model": prof["model"],
        "user_agent": ua,
    }


def read_getprop_snapshot(getprop_fn: Callable[[str], str]) -> dict[str, str]:
    """Read all verification properties from the device via getprop."""
    return {key: getprop_fn(key) for key in GETPROP_VERIFY_KEYS}


def verify_fingerprint_with_getprop(
    getprop_fn: Callable[[str], str],
    profile: FingerprintProfile | None = None,
    phone: str = "",
) -> AntiDetectionReport:
    """Verify retail fingerprint using live getprop values."""
    return verify_anti_detection(getprop_fn, profile, phone=phone)


def apply_mumu_vm_fingerprints(
    vms_dir: Path,
    phone_names: str | Sequence[str],
    profiles: dict[str, FingerprintProfile] | None = None,
    shell_fns: dict[str, Callable[[str], str]] | None = None,
) -> dict[str, FingerprintProfile]:
    """
    Apply retail fingerprints to one or more MuMu VMs.

    For each phone:
    - Patch setting.json with retail brand/model/IMEI/MAC/UA
    - Write per-phone adb_flags (kernel getprop + security props)
    - Optionally push browser UA/flags via ADB when shell_fn is provided
    """
    if is_skip_fingerprint():
        logger.info("Skipping apply_mumu_vm_fingerprints (PHARMFLOW_SKIP_FINGERPRINT)")
        names = [phone_names] if isinstance(phone_names, str) else list(phone_names)
        return {name: (profiles or {}).get(name) or random_profile() for name in names}

    names = [phone_names] if isinstance(phone_names, str) else list(phone_names)
    profile_map = profiles or {}
    shell_map = shell_fns or {}
    applied: dict[str, FingerprintProfile] = {}

    for name in names:
        profile = profile_map.get(name) or random_profile()
        setting_path = find_setting_json(vms_dir, name)
        if setting_path:
            patch_setting_json(setting_path, profile)
        else:
            logger.warning("setting.json not found for %s — skipping layer 1", name)
        write_adb_flags(vms_dir, name, profile)
        shell_fn = shell_map.get(name)
        if shell_fn:
            _apply_browser_ua_shell_fn(shell_fn, profile)
        applied[name] = profile
        logger.info("Applied MuMu VM fingerprint for %s (%s %s)", name, profile.brand, profile.model)

    return applied


def apply_mumu_vm_fingerprint(
    vms_dir: Path,
    instance_name: str,
    profile: FingerprintProfile | None = None,
    shell_fn: Callable[[str], str] | None = None,
) -> FingerprintProfile:
    """Apply fingerprint to a single MuMu VM."""
    prof = profile or random_profile()
    apply_mumu_vm_fingerprints(
        vms_dir,
        instance_name,
        profiles={instance_name: prof},
        shell_fns={instance_name: shell_fn} if shell_fn else None,
    )
    return prof


def apply_fingerprint(
    vms_dir: Path,
    instance_name: str,
    profile: FingerprintProfile,
    shell_fn: Callable[[str], str] | None = None,
) -> None:
    """Apply all VM-side fingerprint layers (backward-compatible wrapper)."""
    apply_mumu_vm_fingerprint(vms_dir, instance_name, profile=profile, shell_fn=shell_fn)


def rotate_fingerprint(vms_dir: Path, instance_name: str) -> FingerprintProfile:
    path = find_setting_json(vms_dir, instance_name)
    if not path:
        raise FileNotFoundError(f"setting.json not found for {instance_name}")
    profile = random_profile()
    apply_fingerprint(vms_dir, instance_name, profile)
    return profile


def browser_flags_for_profile(profile: FingerprintProfile) -> str:
    flags = list(profile.browser_flags) + [
        f'--user-agent="{profile.user_agent}"',
        "--disable-web-security",
    ]
    return " ".join(flags)


def verify_anti_detection(
    getprop_fn: Callable[[str], str],
    profile: FingerprintProfile | None = None,
    phone: str = "",
) -> AntiDetectionReport:
    """Layer 6: Runtime verification via getprop before website visits."""
    props = read_getprop_snapshot(getprop_fn)
    checks: dict[str, bool] = {}
    failures: list[str] = []

    qemu = props["ro.kernel.qemu"].strip()
    checks["kernel_qemu_clear"] = qemu in ("", "0")
    if not checks["kernel_qemu_clear"]:
        failures.append(f"ro.kernel.qemu={qemu!r} (emulator detected)")

    for field_name, key in [("brand", "ro.product.brand"), ("model", "ro.product.model"), ("manufacturer", "ro.product.manufacturer")]:
        val = props[key].lower()
        checks[f"retail_{field_name}"] = bool(val) and not any(b in val for b in FORBIDDEN_SUBSTRINGS)
        if not checks[f"retail_{field_name}"]:
            failures.append(f"{key}={props[key]!r}")

    hw = props["ro.hardware"].lower()
    checks["hardware_retail"] = bool(hw) and "mumu" not in hw and "goldfish" not in hw and "ranchu" not in hw
    if not checks["hardware_retail"]:
        failures.append(f"ro.hardware={props['ro.hardware']!r}")

    bl = props["ro.bootloader"].lower()
    checks["bootloader_clean"] = "mumu" not in bl and "goldfish" not in bl
    if not checks["bootloader_clean"]:
        failures.append(f"ro.bootloader suspicious: {props['ro.bootloader']!r}")

    checks["not_debuggable"] = props["ro.debuggable"] in ("0", "")
    checks["secure"] = props["ro.secure"] in ("1", "")
    checks["adb_secure"] = props.get("ro.adb.secure", "1") in ("1", "")

    if profile:
        live_model = props["ro.product.model"].strip().lower()
        live_brand = props["ro.product.brand"].strip().lower()
        expect_model = profile.model.strip().lower()
        expect_brand = profile.brand.strip().lower()
        checks["model_match"] = bool(live_model) and (
            live_model == expect_model or expect_model in live_model or live_model in expect_model
        )
        checks["brand_match"] = bool(live_brand) and (
            live_brand == expect_brand or expect_brand in live_brand or live_brand in expect_brand
        )
        if not checks["model_match"]:
            failures.append(f"model mismatch: expected {profile.model}, got {props['ro.product.model']}")
        if not checks["brand_match"]:
            failures.append(f"brand mismatch: expected {profile.brand}, got {props['ro.product.brand']}")

    # Soft: brand/model profile mismatches do not fail the overall report when
    # retail substring checks already passed (MuMu ARM may still show PhoneProp
    # until the next cold boot applies a newly written patch).
    hard_keys = [k for k in checks if k not in ("model_match", "brand_match")]
    passed = all(checks[k] for k in hard_keys) if hard_keys else all(checks.values())
    return AntiDetectionReport(
        phone=phone,
        passed=passed,
        checks=checks,
        props=props,
        checked_at=datetime.now(timezone.utc).isoformat(),
        failures=failures,
    )


def ensure_fingerprint_before_browse(
    vms_dir: Path | str,
    instance_name: str | None = None,
    getprop_fn: Callable[[str], str] | None = None,
    shell_fn: Callable[[str], str] | None = None,
    profile: FingerprintProfile | None = None,
    reapply_fn: Callable[[FingerprintProfile], None] | None = None,
) -> AntiDetectionReport | dict[str, Any]:
    """
    Pre-open_url hook: verify getprop, apply VM fingerprints if missing or failed.

    Call before every browse_url / open_url sequence step.

    The one-argument form is retained for the legacy skip-fingerprint probe;
    normal browse execution uses the full typed hook above.
    """
    if instance_name is None:
        if not is_skip_fingerprint():
            raise TypeError(
                "ensure_fingerprint_before_browse requires vms_dir, instance_name, "
                "getprop_fn, shell_fn, profile, and reapply_fn"
            )
        return {"skipped": True, "serial": str(vms_dir)}
    if getprop_fn is None or shell_fn is None or reapply_fn is None:
        raise TypeError(
            "ensure_fingerprint_before_browse requires getprop_fn, shell_fn, and reapply_fn"
        )
    if profile is None and not is_skip_fingerprint():
        profile = apply_mumu_vm_fingerprint(vms_dir, instance_name, shell_fn=shell_fn)

    report = verify_fingerprint_with_getprop(getprop_fn, profile, phone=instance_name)
    if not report.passed and not is_skip_fingerprint():
        logger.warning("Anti-detection failed for %s — re-applying fingerprint", instance_name)
        new_profile = profile or random_profile()
        apply_mumu_vm_fingerprint(vms_dir, instance_name, profile=new_profile, shell_fn=shell_fn)
        reapply_fn(new_profile)
        report = verify_fingerprint_with_getprop(getprop_fn, new_profile, phone=instance_name)
    return report


# ==== merged from pharmflow automation/mumu_fingerprint.py (profile/audit helpers) ====

@dataclass
class FingerprintAudit:
    serial: str
    profile_key: str
    leaks: list[str] = field(default_factory=list)
    ok_props: list[str] = field(default_factory=list)
    user_agent_written: bool = False
    cold_boot_needed: bool = False

    @property

    def clean(self) -> bool:
        return not self.leaks



def _shell(serial: str, *args: str, timeout: float = 15) -> subprocess.CompletedProcess:
    exe = adb_executable()
    return subprocess.run(
        [exe, "-s", serial, "shell", *args],
        capture_output=True,
        text=True,
        errors="replace",  # device output can contain raw bytes — never crash sequence threads on decode
        timeout=timeout,
        creationflags=_SUBPROC_FLAGS,
    )



def getprop(serial: str, name: str) -> str:
    try:
        r = _shell(serial, "getprop", name, timeout=10)
        return (r.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""



def _norm_model(s: str) -> str:
    return (s or "").upper().replace("-", "_").replace(" ", "_")



def profile_for_index(index: int) -> dict:
    i = max(0, int(index)) % len(RETAIL_PROFILE_POOL)
    return dict(RETAIL_PROFILE_POOL[i])



def profile_for_model(model: str) -> dict | None:
    norm = _norm_model(model)
    if not norm:
        return None
    for p in RETAIL_PROFILE_POOL:
        # Prefer explicit match aliases; always include the profile's model too
        # (pool entries historically had no "match" key — matching only that
        # made every getprop-based lookup fall through to hash/farm index).
        candidates = list(p.get("match") or ())
        model_name = p.get("model")
        if model_name:
            candidates.append(model_name)
        for m in candidates:
            mn = _norm_model(str(m))
            if not mn:
                continue
            if norm == mn or mn in norm or norm in mn:
                return dict(p)
    return None



def profile_for_serial(serial: str, *, farm_index: int | None = None) -> dict:
    """Stable retail profile per phone — match getprop model, else farm order, else serial hash."""
    matched = profile_for_model(getprop(serial, "ro.product.model"))
    if matched is not None:
        return matched
    if farm_index is not None:
        return profile_for_index(farm_index)
    h = int(hashlib.sha256(serial.encode()).hexdigest()[:8], 16)
    return profile_for_index(h)



def profile_by_farm_index(index: int) -> dict:
    return profile_for_index(index)



def build_mobile_user_agent(profile: dict) -> str:
    fp = str(profile.get("fingerprint", ""))
    m_release = re.search(r":(\d{1,2})/", fp)
    m_build = re.search(r":\d{1,2}/([^/]+)/", fp)
    release = profile.get("android_release") or (m_release.group(1) if m_release else "13")
    build_id = profile.get("build_id") or (m_build.group(1) if m_build else "TP1A.220624.014")
    chrome = profile.get("chrome_version") or _chrome_version_for_model(str(profile.get("model", "")))
    return (
        f"Mozilla/5.0 (Linux; Android {release}; {profile['model']} "
        f"Build/{build_id}; wv) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Version/4.0 Chrome/{chrome} Mobile Safari/537.36"
    )



def build_chromium_flags(profile: dict, *, cdp_port: int | None = None) -> str:
    ua = build_mobile_user_agent(profile)
    flags = (
        "chrome "
        "--enable-features=AllowChromeCommandLineInNonRootBuilds "
        "--disable-blink-features=AutomationControlled "
        f'--user-agent="{ua}" '
        "--disable-first-run-experience "
        "--no-default-browser-check --no-first-run "
        "--disable-fre --disable-sync-by-default "
        "--disable-restore-session-state "
        "--disable-session-crashed-bubble"
    )
    if cdp_port is not None and cdp_port > 0:
        flags += (
            f" --remote-debugging-port={int(cdp_port)}"
            " --remote-allow-origins=*"
        )
    return flags



def _random_imei() -> str:
    return generate_imei()



def _random_mac() -> str:
    octets = [0x02] + [random.randint(0, 255) for _ in range(5)]
    return ":".join(f"{b:02X}" for b in octets)



def _random_android_id() -> str:
    return os.urandom(8).hex()



MUMU_INSTALL_CANDIDATES: tuple[Path, ...] = (
    Path(r"C:\Program Files\Netease\MuMuPlayerARM"),
    Path(r"C:\Program Files\Netease\MuMuPlayer"),
    Path(r"C:\Program Files (x86)\Netease\MuMuPlayerARM"),
    Path(r"C:\Program Files (x86)\Netease\MuMuPlayer"),
)


def find_mumu_vms_root() -> Path | None:
    env = (os.environ.get("PHARMFLOW_MUMU_ROOT") or "").strip()
    roots: list[Path] = [Path(env)] if env else []
    detected = detect_mumu_root()
    if detected:
        roots.append(Path(detected))
    roots.extend(MUMU_INSTALL_CANDIDATES)
    seen: set[str] = set()
    for root in roots:
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        vms = root / "vms"
        if vms.is_dir():
            return vms
    return None



def scan_mumu_setting_paths() -> list[Path]:
    vms_root = find_mumu_vms_root()
    if not vms_root:
        return []
    return sorted(vms_root.glob("vm*.gmadoa/setting.json"))



def patch_mumu_setting_json(
    setting_path: Path,
    profile: dict,
    *,
    randomize_ids: bool = True,
    dry_run: bool = False,
) -> dict:
    result: dict = {"patched": False, "backup": None, "fields": []}
    if not setting_path.is_file():
        result["error"] = "setting.json not found"
        return result

    try:
        data = json.loads(setting_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        result["error"] = str(e)
        return result

    brand = profile["brand"]
    model = profile["model"]
    miit = profile.get("miit") or model

    res = data.setdefault("ResolutionPresetSelected", {})
    identity_keys = (
        "phonePropBrand",
        "phonePropModel",
        "phoneModel",
        "phonePropMiit",
        "ResolutionPresetSelected.ResolutionType",
        "DeviceOrientation",
        "FramebufferWidth",
        "FramebufferHeight",
        "FramebufferDPI",
    )

    # Detect whether identity/resolution already matches (skip re-randomizing IMEI/MAC every GO).
    would_change_identity = False
    if data.get("phonePropBrand") != brand:
        would_change_identity = True
    if data.get("phonePropModel") != model:
        would_change_identity = True
    if data.get("phoneModel") != model:
        would_change_identity = True
    if data.get("phonePropMiit") != miit:
        would_change_identity = True
    if res.get("ResolutionType") != "Phone":
        would_change_identity = True
    for k, v in (
        ("DeviceOrientation", "Portrait"),
        ("FramebufferWidth", 900),
        ("FramebufferHeight", 1600),
        ("FramebufferDPI", 300),
    ):
        if data.get(k) != v:
            would_change_identity = True
    gpu = profile.get("gpu_preset")
    if gpu:
        for gkey in ("phonePropGPUModel", "gpuModel", "GpuModel"):
            if data.get(gkey) != gpu:
                would_change_identity = True

    if not would_change_identity:
        result["patched"] = False
        result["note"] = "already matched profile"
        return result

    imei = _random_imei() if randomize_ids else (data.get("phonePropIMEI") or _random_imei())
    mac = _random_mac() if randomize_ids else (data.get("macAddress") or _random_mac())
    android_id = _random_android_id() if randomize_ids else "0123456789abcdef"

    updates = {
        "phonePropBrand": brand,
        "phonePropModel": model,
        "phoneModel": model,
        "phonePropMiit": miit,
        "phonePropIMEI": imei,
        "macAddress": mac,
        "simulationProps": f"android_id={android_id}",
    }
    for k, v in updates.items():
        if data.get(k) != v:
            data[k] = v
            result["fields"].append(k)

    if res.get("ResolutionType") != "Phone":
        res["ResolutionType"] = "Phone"
        result["fields"].append("ResolutionPresetSelected.ResolutionType")
    for k, v in (
        ("DeviceOrientation", "Portrait"),
        ("FramebufferWidth", 900),
        ("FramebufferHeight", 1600),
        ("FramebufferDPI", 300),
    ):
        if data.get(k) != v:
            data[k] = v
            result["fields"].append(k)

    if gpu:
        for gkey in ("phonePropGPUModel", "gpuModel", "GpuModel"):
            if data.get(gkey) != gpu:
                data[gkey] = gpu
                result["fields"].append(gkey)

    _ = identity_keys  # documentation anchor for cold-boot fields

    if not result["fields"]:
        result["patched"] = False
        result["note"] = "already matched profile"
        return result

    if dry_run:
        result["patched"] = True
        result["dry_run"] = True
        return result

    bak = setting_path.with_suffix(setting_path.suffix + f".bak-fp-{int(os.path.getmtime(setting_path))}")
    try:
        shutil.copy2(setting_path, bak)
        setting_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        result["patched"] = True
        result["backup"] = str(bak)
    except OSError as e:
        result["error"] = str(e)
    return result



def write_chromium_flags(serial: str, profile: dict, *, cdp_port: int | None = None) -> bool:
    flags = build_chromium_flags(profile, cdp_port=cdp_port)

    try:
        exe = adb_executable()


        def _push_flags() -> tuple[bool, str]:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".txt",
                delete=False,
            ) as tmp:
                tmp.write(flags)
                local_path = tmp.name
            try:
                r_push = subprocess.run(
                    [exe, "-s", serial, "push", local_path, CHROME_FLAGS_PATH],
                    capture_output=True,
                    text=True,
                    errors="replace",  # device output can contain raw bytes — never crash sequence threads on decode
                    timeout=30,
                    creationflags=_SUBPROC_FLAGS,
                )
                err = ((r_push.stderr or "") + (r_push.stdout or "")).strip()
                if r_push.returncode != 0:
                    return False, err or "adb push failed"
                r_fix = _shell(
                    serial,
                    "sh",
                    "-c",
                    f"cp {CHROME_FLAGS_PATH} {WEBVIEW_FLAGS_PATH} 2>/dev/null; "
                    f"chmod 644 {CHROME_FLAGS_PATH} {WEBVIEW_FLAGS_PATH} 2>/dev/null; true",
                    timeout=15,
                )
                verify = _shell(serial, "cat", CHROME_FLAGS_PATH, timeout=8)
                body = (verify.stdout or "").strip()
                if "--user-agent=" not in body:
                    return False, "flags file missing or empty after push"
                return True, ""
            finally:
                try:
                    Path(local_path).unlink(missing_ok=True)
                except OSError:
                    pass

        ok, err = _push_flags()
        if ok:
            return True
        subprocess.run(
            [exe, "-s", serial, "root"],
            capture_output=True,
            text=True,
            errors="replace",  # device output can contain raw bytes — never crash sequence threads on decode
            timeout=12,
            creationflags=_SUBPROC_FLAGS,
        )
        ok, err2 = _push_flags()
        return ok
    except (OSError, subprocess.TimeoutExpired):
        return False



def audit_device_fingerprint(
    serial: str,
    *,
    expected_profile: dict | None = None,
) -> FingerprintAudit:
    prof = expected_profile or profile_for_serial(serial)
    audit = FingerprintAudit(serial=serial, profile_key=prof["key"])
    for prop, is_leak, reason in _EMULATOR_LEAK_CHECKS:
        val = getprop(serial, prop)
        if not val:
            continue
        if is_leak(val):
            audit.leaks.append(f"{prop}={val!r} ({reason})")
        else:
            audit.ok_props.append(f"{prop}={val!r}")
    try:
        r = _shell(serial, "cat", CHROME_FLAGS_PATH, timeout=8)
        body = (r.stdout or "").strip()
        audit.user_agent_written = "--user-agent=" in body and prof["model"] in body
    except (OSError, subprocess.TimeoutExpired):
        audit.user_agent_written = False
    if audit.leaks:
        audit.cold_boot_needed = any(
            "ro.kernel.qemu" in x or "ro.product.model" in x or "ro.product.manufacturer" in x
            for x in audit.leaks
        )
    return audit



def apply_fingerprint_all_serials(
    serials: list[str],
    *,
    patch_vms: bool = True,
    log_fn: Callable[[str], None] | None = None,
) -> dict:
    """
    Fix fingerprint on **every** connected phone.

    1. Patch all MuMu VM configs (if MuMu installed on this PC).
    2. Write browser UA flags on each ADB serial (distinct profile per index).
    3. Audit and return honest leak report.
    """
    results: list[dict] = []
    vm_results: list[dict] = []
    if patch_vms:
        # Patch each MuMu setting.json via the dict-profile path. Do NOT call
        # apply_mumu_vm_fingerprints(log_fn=...) — that API requires vms_dir +
        # phone_names and a TypeError aborted the entire "fix all phones" path.
        paths = scan_mumu_setting_paths()
        if log_fn and paths:
            log_fn(f"  Patching {len(paths)} MuMu VM setting.json file(s)…")
        for i, path in enumerate(paths):
            prof = profile_for_index(i)
            try:
                row = patch_mumu_setting_json(path, prof, randomize_ids=True)
            except (OSError, TypeError, ValueError, KeyError) as exc:
                row = {"patched": False, "error": str(exc)}
            row = dict(row)
            row.setdefault("path", str(path))
            vm_results.append(row)
            if log_fn and row.get("patched"):
                log_fn(f"  VM {path.parent.name}: patched")
            elif log_fn and row.get("error"):
                log_fn(f"  VM {path.parent.name}: ERROR {row['error']}")

    any_vm_patched = any(r.get("patched") for r in vm_results)
    if log_fn and serials:
        log_fn(f"  Applying browser disguise on {len(serials)} connected phone(s)…")

    for i, serial in enumerate(serials):
        prof = profile_for_index(i)
        applied = apply_browser_fingerprint_adb(serial, prof, farm_index=i)
        audit = audit_device_fingerprint(serial, expected_profile=prof)
        row = {"serial": serial, "applied": applied, "audit": audit, "index": i}
        results.append(row)
        if log_fn:
            if applied.get("user_agent_written"):
                log_fn(f"  Phone {i + 1} ({serial}): browser set to {prof['brand']} {prof['model']}")
            else:
                log_fn(f"  Phone {i + 1} ({serial}): WARNING — browser flags not written")
            if audit.leaks:
                log_fn(f"    Still leaking ({len(audit.leaks)}):")
                for leak in audit.leaks[:4]:
                    log_fn(f"      • {leak}")
            elif applied.get("user_agent_written"):
                log_fn("    Looks OK from here.")

    if log_fn and any_vm_patched:
        log_fn("")
        log_fn("  IMPORTANT: MuMu phone settings changed — fully STOP then START each phone once.")

    leaks_total = sum(len(r["audit"].leaks) for r in results)
    return {
        "phones": results,
        "vm_patches": vm_results,
        "any_vm_patched": any_vm_patched,
        "leaks_total": leaks_total,
        "all_clean": leaks_total == 0,
    }



def format_audit_report(serial: str, *, farm_index: int | None = None) -> str:
    prof = profile_for_serial(serial, farm_index=farm_index)
    audit = audit_device_fingerprint(serial, expected_profile=prof)
    lines = [
        f"Phone: {serial}",
        f"Disguise: {prof['brand']} {prof['model']} ({audit.profile_key})",
        f"Browser flags on phone: {'yes' if audit.user_agent_written else 'NO'}",
        "",
    ]
    if audit.leaks:
        lines.append("PROBLEMS (website may know this is an emulator):")
        for x in audit.leaks:
            lines.append(f"  ✗ {x}")
        lines.append("")
        lines.append("Fix: run PharmFlow → Phones → Set up my phones, or Re-apply hide emulator on ALL phones")
        lines.append("Then fully stop and start each MuMu phone once.")
    else:
        lines.append("No obvious emulator leaks in phone settings.")
    lines.append("")
    lines.append(f"Browser will say it is: {build_mobile_user_agent(prof)}")
    return "\n".join(lines)
