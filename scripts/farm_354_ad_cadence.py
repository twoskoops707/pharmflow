#!/usr/bin/env python3
"""
354-sequence farm per phone with per-phone ad-click cadences + halfway exits.

Phone ad slots (1-based n):
  vm0: n%10==0 or n%22==0
  vm1: n%7==0 or n%18==0
  vm2: n%5==0 or n%7==0
  vm3: n%28 in {1,7,15,0}  # 0 = 28th of each cycle

Non-ad slots: mix complete + halfway (~38% halfway) to humanize early exits.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["PHARMFLOW_ALLOW_SEQUENCE_RUNS"] = "1"
os.environ.setdefault("PHARMFLOW_EMULATOR_AD_FILL_WAIT", "5")

from automation.config import REQUIRED_SEQUENCE_VERSION
from automation.sequence_paths import discover_sequence_files
from automation.sequence_runner import Sequence, SequenceRunner
from wizard.mumu_farm_ops import MuMuFarmOps
from wizard.wizard_paths import logs_dir, sequences_dir

logger = logging.getLogger("farm_354")

PHONE_ORDER = ["vm0.gmadoa", "vm1.gmadoa", "vm2.gmadoa", "vm3.gmadoa"]
TARGET_PER_PHONE = 354
HALFWAY_RATIO = 0.38  # non-ad slots that exit before timer ends


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def should_click_ads(phone: str, n: int) -> bool:
    """1-based sequence index n."""
    if phone == "vm0.gmadoa":
        return n % 10 == 0 or n % 22 == 0
    if phone == "vm1.gmadoa":
        return n % 7 == 0 or n % 18 == 0
    if phone == "vm2.gmadoa":
        return n % 5 == 0 or n % 7 == 0
    if phone == "vm3.gmadoa":
        return (n % 28) in (1, 7, 15, 0)
    return False


def _pool_by_type(root: Path) -> dict[str, list[Path]]:
    files = discover_sequence_files(root)
    pools: dict[str, list[Path]] = {"ad": [], "complete": [], "halfway": [], "other": []}
    for p in files:
        stem = p.stem
        if stem.endswith("_ad") or "/smoke/" in str(p.as_posix()) or "\\smoke\\" in str(p):
            if "smoke" in stem:
                continue
            pools["ad"].append(p)
        elif stem.endswith("_complete"):
            pools["complete"].append(p)
        elif stem.endswith("_halfway"):
            pools["halfway"].append(p)
        else:
            pools["other"].append(p)
    return pools


def pick_sequence(pools: dict[str, list[Path]], phone: str, n: int, rng: random.Random) -> Path:
    if should_click_ads(phone, n) and pools["ad"]:
        return rng.choice(pools["ad"])
    # Humanize: many early exits before timer completes
    if pools["halfway"] and rng.random() < HALFWAY_RATIO:
        return rng.choice(pools["halfway"])
    if pools["complete"]:
        return rng.choice(pools["complete"])
    if pools["halfway"]:
        return rng.choice(pools["halfway"])
    raise RuntimeError("no sequences available")


def _worker(
    phone: str,
    pools: dict[str, list[Path]],
    farm: MuMuFarmOps,
    runner: SequenceRunner,
    *,
    target: int,
    results_path: Path,
    status: dict,
    status_lock: threading.Lock,
) -> None:
    rng = random.Random(hash(phone) ^ int(time.time()) & 0xFFFFFFFF)
    for n in range(1, target + 1):
        path = pick_sequence(pools, phone, n, rng)
        ad_slot = should_click_ads(phone, n)
        t0 = time.time()
        entry: dict = {
            "time": _utc(),
            "phone": phone,
            "n": n,
            "ad_slot": ad_slot,
            "path": str(path.as_posix()),
            "sequence": path.stem,
        }
        try:
            seq = Sequence.from_json(path)
            seq.phone = phone
            if seq.sequence_version < REQUIRED_SEQUENCE_VERSION:
                entry.update(success=False, error=f"v{seq.sequence_version} blocked")
            else:
                report = runner.run(seq)
                entry["success"] = bool(report.get("success"))
                entry["error"] = report.get("error")
                entry["failed_at"] = report.get("failed_at")
                # Count ad engagements if present
                ad_hits = 0
                for step in report.get("steps") or []:
                    if step.get("ad_fallback") or (
                        "ad" in (step.get("description") or "").lower()
                        and step.get("ok")
                        and step.get("action") == "tap"
                    ):
                        ad_hits += 1
                entry["ad_taps"] = ad_hits
        except Exception as exc:
            entry["success"] = False
            entry["error"] = str(exc)
            entry["traceback"] = traceback.format_exc()
        entry["elapsed_s"] = round(time.time() - t0, 1)

        with open(results_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

        with status_lock:
            st = status.setdefault(phone, {"done": 0, "ok": 0, "fail": 0, "ad_slots": 0})
            st["done"] = n
            st["ok"] += 1 if entry.get("success") else 0
            st["fail"] += 0 if entry.get("success") else 1
            if ad_slot:
                st["ad_slots"] += 1
            st["last"] = entry["sequence"]
            st["updated"] = _utc()

        logger.info(
            "%s [%d/%d] ad=%s %s success=%s %.1fs",
            phone,
            n,
            target,
            ad_slot,
            path.stem,
            entry.get("success"),
            entry["elapsed_s"],
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="354-seq farm with ad cadences")
    parser.add_argument("--per-phone", type=int, default=TARGET_PER_PHONE)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--phones", nargs="*", default=None)
    args = parser.parse_args()

    log_dir = logs_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "farm_354.log", encoding="utf-8"),
        ],
    )

    seq_root = args.root or sequences_dir()
    if (seq_root / "sequences").is_dir():
        seq_root = seq_root / "sequences"
    pools = _pool_by_type(seq_root)
    logger.info(
        "Pools ad=%d complete=%d halfway=%d",
        len(pools["ad"]),
        len(pools["complete"]),
        len(pools["halfway"]),
    )
    if not pools["ad"] or not pools["complete"] or not pools["halfway"]:
        logger.error("Missing sequence pools — regenerate base sequences")
        return 1

    farm = MuMuFarmOps()
    farm.list_instances()
    phones = args.phones or [
        p for p in PHONE_ORDER if farm.get_phone_status(p).get("connected")
    ]
    if not phones:
        logger.error("No connected phones")
        return 1
    logger.info("Phones: %s  target=%d each", phones, args.per_phone)

    results_path = log_dir / "farm_354_results.jsonl"
    # Fresh run marker
    with open(results_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": "farm_start", "time": _utc(), "phones": phones, "per_phone": args.per_phone}) + "\n")

    status: dict = {}
    status_lock = threading.Lock()
    status_path = log_dir / "farm_354_status.json"

    def _status_writer() -> None:
        while True:
            time.sleep(15)
            with status_lock:
                payload = {"updated": _utc(), "phones": dict(status)}
            status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    threading.Thread(target=_status_writer, daemon=True, name="status-writer").start()

    runner = SequenceRunner(farm)
    threads: list[threading.Thread] = []
    for phone in phones:
        t = threading.Thread(
            target=_worker,
            args=(phone, pools, farm, runner),
            kwargs={
                "target": args.per_phone,
                "results_path": results_path,
                "status": status,
                "status_lock": status_lock,
            },
            name=f"farm354-{phone}",
            daemon=True,
        )
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    with status_lock:
        summary = {"finished": _utc(), "phones": status, "results": str(results_path)}
    (log_dir / "farm_354_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("Farm complete: %s", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
