#!/usr/bin/env python3
"""Tune MuMu ARM setting.json down for farm density (CPU/RAM/GPU).

Does NOT change framebuffer resolution (farm coords stay 900x1600).
Changes apply fully after MuMu cold boot of each VM.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

VMS = Path(r"C:\Program Files\Netease\MuMuPlayerARM\vms")

LOW = {
    "PerformanceType": "Low",
    "PerformancePreset": {"Cpu": 2, "MemoryOfMB": 2048},
    "GpuProp": {"Model": "Adreno (TM) 640", "Mode": "Low"},
    "DynamicFpsEnable": True,
    "DynamicFpsLimitToLow": 15,
    "FpsShowEnable": False,
    "RenderEngine": "DirectX",
}


def patch_one(path: Path) -> str:
    raw = path.read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    before = {
        "PerformanceType": data.get("PerformanceType"),
        "PerformancePreset": data.get("PerformancePreset"),
        "GpuProp": data.get("GpuProp"),
        "DynamicFpsEnable": data.get("DynamicFpsEnable"),
        "DynamicFpsLimitToLow": data.get("DynamicFpsLimitToLow"),
    }
    for key, val in LOW.items():
        if key == "GpuProp" and isinstance(data.get("GpuProp"), dict):
            gp = dict(data["GpuProp"])
            gp["Mode"] = "Low"
            data["GpuProp"] = gp
        else:
            data[key] = val
    path.write_text(json.dumps(data, ensure_ascii=False, indent=4) + "\n", encoding="utf-8-sig")
    return f"{path.parent.name}: {before} -> Low/2cpu/2048MB/GpuLow/DynFps15"


def main() -> int:
    if not VMS.is_dir():
        print("vms dir missing", VMS)
        return 1
    for setting in sorted(VMS.glob("*/setting.json")):
        try:
            print(patch_one(setting))
        except OSError as exc:
            print(setting.parent.name, "FAIL", exc)
            return 1
    print("OK — cold-boot each VM for Memory/CPU caps to take effect")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
