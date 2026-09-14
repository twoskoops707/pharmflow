"""Per-VM trim A/B test: measure CPU/RAM savings of resource trims on one phone.

Implements the scaling-plan experiment: trim ONE phone (1024 MB preset,
1 guest core, fps cap) and measure the delta against its own pre-trim
baseline, so the fleet-wide decision is data-driven instead of guessed.

Method (no guessing, no unsafe kills):
1. Snapshot all ``vmmemNemu`` pids and sample per-pid CPU% for BASELINE_SECS.
2. Power the test VM off gracefully via ``adb reboot -p`` (Android's own
   shutdown — MuMu reaps the VM cleanly; never taskkill a VM).
3. Edit the VM's ``setting.json`` while stopped (Custom.Cpu, Custom.MemoryOfMB,
   MaxFpsLimit), backing up the original first.
4. Relaunch via the farm's own proven launcher (launch_instance_index) and
   wait for ADB.
5. Re-sample per-pid CPU% for SAMPLE_SECS and report the delta.

The per-pid mapping is by set-difference: the pid that appears after the
restart that was not in the baseline snapshot is the test VM. That works even
though MuMu exposes no pid mapping.

Usage:
    python tools/per_vm_trim_test.py --vm 22 [--baseline-secs 360] [--sample-secs 360]
                                     [--cpu 1] [--mem 1024] [--fps 20] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from automation.mumu_shell_cli import launch_instance_index  # noqa: E402

ADB = REPO / "bundled" / "adb.exe"
VMS_DIR = Path(r"C:\Program Files\Netease\MuMuPlayerARM\vms")
SERIAL_MAP = Path(r"C:\PharmFlow\logs\ADB_SERIAL_MAP.lock.json")


def adb_serial(vm_idx: int) -> str:
    """Resolve a VM's adb serial from the farm's sticky serial map (vm name → addr)."""
    name = f"vm{vm_idx}.gmadoa"
    try:
        phones = json.loads(SERIAL_MAP.read_text(encoding="utf-8-sig")).get("phones", {})
        addr = str(phones.get(name) or "").strip()
        if addr:
            return addr
    except (OSError, ValueError):
        pass
    raise SystemExit(f"no adb serial for {name} in {SERIAL_MAP.name}")


def adb(*args: str, timeout: float = 15.0) -> str:
    out = subprocess.run(
        [str(ADB), *args], capture_output=True, text=True, timeout=timeout
    )
    return (out.stdout or "").strip()


def vmmem_pids() -> dict[int, float]:
    """pid -> one short-interval CPU% sample (primes counters on first call)."""
    import psutil

    procs = [
        p
        for p in psutil.process_iter(["name"])
        if (p.info["name"] or "").lower() == "vmmemnemu"
    ]
    for p in procs:
        p.cpu_percent(None)
    return {p.pid: p.cpu_percent(None) for p in procs}


def sample_pids(pids: dict[int, float], secs: float) -> dict[int, float]:
    """Average CPU% per pid over ``secs`` seconds."""
    import psutil

    procs = {p.pid: p for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() == "vmmemnemu"}
    marks = {}
    for pid in pids:
        proc = psutil.Process(pid) if pid in procs else None
        if proc:
            proc.cpu_percent(None)
            marks[pid] = proc
    time.sleep(secs)
    result = {}
    for pid, proc in marks.items():
        try:
            # cpu_percent(None) over the slept window already returns
            # % of one core for that window (cpu-time delta / wall delta).
            result[pid] = proc.cpu_percent(None)
        except psutil.Error:
            pass
    return result


def sample_host_ram() -> float:
    import psutil

    return psutil.virtual_memory().available / (1024 * 1024)


def set_setting(vm_idx: int, cpu: int, mem_mb: int, fps: int) -> tuple[dict, Path]:
    cfg = VMS_DIR / f"vm{vm_idx}.gmadoa" / "setting.json"
    backup = cfg.with_suffix(".json.pre_trim_backup")
    if not backup.is_file():
        shutil.copy2(cfg, backup)
    data = json.loads(cfg.read_text(encoding="utf-8-sig"))
    data.setdefault("Custom", {})
    data["Custom"]["Cpu"] = int(cpu)
    data["Custom"]["MemoryOfMB"] = int(mem_mb)
    data["Custom"]["Fps"] = int(fps)
    data["MaxFpsLimit"] = int(fps)
    data["PerformanceType"] = "Custom"
    cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data, backup


def wait_adb(serial: str, budget: float = 240.0) -> bool:
    deadline = time.time() + budget
    while time.time() < deadline:
        try:
            adb("connect", serial, timeout=10)
            if adb("-s", serial, "shell", "echo", "ok", timeout=10) == "ok":
                return True
        except subprocess.TimeoutExpired:
            pass
        time.sleep(5)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vm", type=int, required=True)
    ap.add_argument("--baseline-secs", type=float, default=360.0)
    ap.add_argument("--sample-secs", type=float, default=360.0)
    ap.add_argument("--cpu", type=int, default=1)
    ap.add_argument("--mem", type=int, default=1024)
    ap.add_argument("--fps", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    serial = adb_serial(args.vm)
    print(f"vm{args.vm} serial={serial}", flush=True)

    pids_before = vmmem_pids()
    ram_before = sample_host_ram()
    print(f"baseline: {len(pids_before)} vmmemNemu pids, host free RAM {ram_before:.0f}MB", flush=True)
    print(f"sampling baseline CPU for {args.baseline_secs:.0f}s …", flush=True)
    base_cpu = sample_pids(pids_before, args.baseline_secs)
    ranked = sorted(base_cpu.items(), key=lambda kv: -kv[1])[:3]
    print("baseline top pids:", [(pid, f"{cpu:.1f}%core") for pid, cpu in ranked], flush=True)

    if args.dry_run:
        print("dry-run: would power off, trim, relaunch, sample — stopping here.")
        return 0

    print(f"powering off vm{args.vm} via adb reboot -p …", flush=True)
    try:
        adb("-s", serial, "reboot", "-p", timeout=20)
    except subprocess.TimeoutExpired:
        pass
    deadline = time.time() + 120
    while time.time() < deadline:
        if adb("-s", serial, "shell", "echo", "ok", timeout=8) != "ok":
            break
        time.sleep(5)
    pids_after_off = vmmem_pids()
    gone = set(pids_before) - set(pids_after_off)
    print(f"pids gone after shutdown: {len(gone)}", flush=True)
    if not gone:
        print("WARN: no vmmemNemu pid disappeared — shutdown may have failed; aborting trim.", flush=True)
        return 2

    data, backup = set_setting(args.vm, args.cpu, args.mem, args.fps)
    print(f"trim applied: cpu={args.cpu} mem={args.mem}MB fps={args.fps} (backup: {backup.name})", flush=True)

    def config_matches_current() -> bool:
        try:
            cur = json.loads((VMS_DIR / f"vm{args.vm}.gmadoa" / "setting.json").read_text(encoding="utf-8-sig"))
            c = cur.get("Custom", {})
            return (
                int(c.get("Cpu", -1)) == int(args.cpu)
                and int(c.get("MemoryOfMB", -1)) == int(args.mem)
                and int(cur.get("MaxFpsLimit", -1)) == int(args.fps)
            )
        except (OSError, ValueError, TypeError):
            return False

    for attempt in (1, 2):
        ok, msg = launch_instance_index(args.vm, timeout=180.0)
        print(f"relaunch attempt {attempt}: {msg}", flush=True)
        if not ok:
            print("relaunch failed — restoring backup config", flush=True)
            shutil.copy2(backup, VMS_DIR / f"vm{args.vm}.gmadoa" / "setting.json")
            return 3
        if not wait_adb(serial):
            print("no ADB after relaunch — VM may still be booting; sample later manually.", flush=True)
            return 4
        if config_matches_current():
            break
        # A race (e.g. farm self-heal) booted the VM with the old config while
        # it was stopped — power off again and redo the trim once.
        print("config on disk does not match trim (raced boot) — redoing cycle", flush=True)
        try:
            adb("-s", serial, "reboot", "-p", timeout=20)
        except subprocess.TimeoutExpired:
            pass
        deadline = time.time() + 120
        while time.time() < deadline:
            if adb("-s", serial, "shell", "echo", "ok", timeout=8) != "ok":
                break
            time.sleep(5)
        set_setting(args.vm, args.cpu, args.mem, args.fps)
    else:
        print("could not land trimmed config after redo — aborting", flush=True)
        return 5
    print("phone back online; settle 120s before sampling …", flush=True)
    time.sleep(120)

    pids_trim = vmmem_pids()
    new_pids = set(pids_trim) - set(pids_after_off)
    if len(new_pids) != 1:
        print(f"WARN: expected exactly 1 new pid, got {len(new_pids)} — mapping ambiguous.", flush=True)
    ram_after = sample_host_ram()
    print(f"sampling trimmed CPU for {args.sample_secs:.0f}s …", flush=True)
    trim_cpu = sample_pids(pids_trim, args.sample_secs)

    report = {
        "vm": args.vm,
        "trim": {"cpu": args.cpu, "mem_mb": args.mem, "fps": args.fps},
        "baseline": {
            "pids": len(pids_before),
            "top_cpu_pct": {str(k): round(v, 2) for k, v in ranked},
            "host_free_ram_mb": round(ram_before, 0),
        },
        "after": {
            "new_pids": sorted(new_pids),
            "new_pid_cpu_pct": {str(p): round(trim_cpu.get(p, 0.0), 2) for p in new_pids},
            "host_free_ram_mb": round(ram_after, 0),
        },
        "ram_delta_mb": round(ram_after - ram_before, 0),
        "note": "pid mapping by set-difference across the restart; CPU% is % of one core",
    }
    out = REPO / "automation" / "recordings" / f"per_vm_trim_report_vm{args.vm}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    print(f"report written: {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
