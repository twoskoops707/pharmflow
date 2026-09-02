"""Live ADB sequence farm test — distributes JSON sequences across connected phones."""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.config import sequences_run_allowed
from automation.sequence_runner import Sequence, SequenceRunner
from wizard.mumu_farm_ops import MuMuFarmOps
from wizard.wizard_paths import logs_dir, sequences_dir

logger = logging.getLogger("live_sequence_farm_test")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _discover_sequences(root: Path) -> list[Path]:
    from automation.config import REQUIRED_SEQUENCE_VERSION
    from automation.sequence_paths import discover_sequence_files

    base = root / "sequences" if (root / "sequences").is_dir() else root
    return discover_sequence_files(base)


def _load_checkpoint(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data.get("done", []))
    except (OSError, json.JSONDecodeError):
        return set()


def _save_checkpoint(path: Path, done: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"done": sorted(done), "updated": _utc()}, indent=2), encoding="utf-8")


def _worker(
    phone: str,
    work: queue.Queue[str],
    farm: MuMuFarmOps,
    runner: SequenceRunner,
    *,
    results_path: Path,
    done: set[str],
    done_lock: threading.Lock,
    checkpoint_path: Path,
    skip_fingerprint: bool,
) -> None:
    if skip_fingerprint:
        os.environ["CPHARM_SKIP_FINGERPRINT"] = "1"
    while True:
        try:
            rel = work.get_nowait()
        except queue.Empty:
            return
        path = Path(rel)
        key = str(path.as_posix())
        try:
            seq = Sequence.from_json(path)
            seq.phone = phone
            from automation.config import REQUIRED_SEQUENCE_VERSION

            if seq.sequence_version < REQUIRED_SEQUENCE_VERSION:
                entry = {
                    "time": _utc(),
                    "phone": phone,
                    "sequence": seq.name,
                    "path": key,
                    "success": False,
                    "error": f"sequence v{seq.sequence_version} — rewrite required (need v{REQUIRED_SEQUENCE_VERSION}+)",
                }
                with open(results_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry) + "\n")
                continue
            t0 = time.time()
            report = runner.run(seq)
            elapsed = round(time.time() - t0, 1)
            entry = {
                "time": _utc(),
                "phone": phone,
                "sequence": seq.name,
                "path": key,
                "success": bool(report.get("success")),
                "elapsed_s": elapsed,
                "error": report.get("error"),
                "failed_at": report.get("failed_at"),
                "failed_step": None,
            }
            if report.get("failed_at") is not None:
                steps = report.get("steps") or []
                idx = int(report["failed_at"])
                if 0 <= idx < len(steps):
                    entry["failed_step"] = steps[idx]
        except Exception as exc:
            entry = {
                "time": _utc(),
                "phone": phone,
                "sequence": path.stem,
                "path": key,
                "success": False,
                "elapsed_s": 0,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        with open(results_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if entry.get("success"):
            with done_lock:
                done.add(key)
                if len(done) % 5 == 0:
                    _save_checkpoint(checkpoint_path, done)
        status = "OK" if entry["success"] else "FAIL"
        logger.info("[%s] %s %s (%.0fs) %s", phone, status, path.name, entry.get("elapsed_s", 0), entry.get("error") or "")
        work.task_done()


def main() -> int:
    parser = argparse.ArgumentParser(description="Live sequence farm test on MuMu ADB phones")
    parser.add_argument("--root", type=Path, default=sequences_dir(), help="Sequences root directory")
    parser.add_argument("--workers", type=int, default=0, help="Phone workers (0 = all connected)")
    parser.add_argument("--limit", type=int, default=0, help="Max sequences to run (0 = all)")
    parser.add_argument("--skip-fingerprint", action="store_true", help="Set CPHARM_SKIP_FINGERPRINT=1")
    parser.add_argument("--setup-tor", action="store_true", help="Start Tor on each phone before run")
    parser.add_argument("--resume", action="store_true", help="Skip sequences in checkpoint file")
    args = parser.parse_args()

    if not sequences_run_allowed():
        print(
            "BLOCKED: Sequence farm test will not run until CPHARM_ALLOW_SEQUENCE_RUNS=1",
            file=sys.stderr,
        )
        return 2

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(logs_dir() / "live_sequence_farm_test.log", encoding="utf-8"),
        ],
    )

    farm = MuMuFarmOps()
    farm.list_instances()
    phones = [name for name, inst in farm.instances.items() if farm.get_phone_status(name).get("connected")]
    if not phones:
        logger.error("No connected phones")
        return 1
    if args.workers > 0:
        phones = phones[: args.workers]
    logger.info("Phones: %s", phones)

    if args.setup_tor:
        for name in phones:
            try:
                farm.setup_tor(name)
                logger.info("Tor started for %s", name)
            except Exception as exc:
                logger.warning("Tor setup failed for %s: %s", name, exc)

    all_paths = _discover_sequences(args.root)
    if args.limit > 0:
        all_paths = all_paths[: args.limit]

    checkpoint_path = logs_dir() / "live_sequence_checkpoint.json"
    done: set[str] = _load_checkpoint(checkpoint_path) if args.resume else set()
    pending = [p for p in all_paths if str(p.as_posix()) not in done]
    logger.info("Sequences: %d total, %d pending, %d already done", len(all_paths), len(pending), len(done))

    results_path = logs_dir() / "live_sequence_results.jsonl"
    work: queue.Queue[str] = queue.Queue()
    for p in pending:
        work.put(str(p.resolve()))

    runner = SequenceRunner(farm)
    done_lock = threading.Lock()
    threads: list[threading.Thread] = []
    for phone in phones:
        t = threading.Thread(
            target=_worker,
            args=(phone, work, farm, runner),
            kwargs={
                "results_path": results_path,
                "done": done,
                "done_lock": done_lock,
                "checkpoint_path": checkpoint_path,
                "skip_fingerprint": args.skip_fingerprint,
            },
            name=f"seq-worker-{phone}",
            daemon=True,
        )
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    with done_lock:
        _save_checkpoint(checkpoint_path, done)

    # Summary
    ok = fail = 0
    if results_path.is_file():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("success"):
                ok += 1
            else:
                fail += 1
    summary = {
        "finished": _utc(),
        "phones": phones,
        "tested_this_run": len(pending),
        "total_done": len(done),
        "results_ok": ok,
        "results_fail": fail,
        "results_file": str(results_path),
    }
    summary_path = logs_dir() / "live_sequence_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("Done. tested=%d ok=%d fail=%d", len(pending), ok, fail)
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
