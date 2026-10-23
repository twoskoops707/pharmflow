"""Run a phone group with per-phone steps, playlists, and repeat settings."""

from __future__ import annotations

import logging
import random
import threading
import time
from pathlib import Path
from typing import Any, Callable

from automation.group_manager import GroupManager
from automation.sequence_paths import resolve_sequence_path
from automation.sequence_playlist import resolve_steps
from automation.sequence_runner import Sequence, SequenceRunner, SequenceStep, StepAction
from wizard.mumu_farm_ops import MuMuFarmOps
from wizard.wizard_paths import sequences_dir

logger = logging.getLogger(__name__)

LogFn = Callable[[str, str], None]
CancelFn = Callable[[], bool]


def _canonical_phone(farm: MuMuFarmOps, raw: str) -> str | None:
    inst = farm.get_phone(raw)
    return inst.name if inst else (raw if raw in farm.instances else None)


def _run_phone_once(
    farm: MuMuFarmOps,
    runner: SequenceRunner,
    group_name: str,
    phone: str,
    ent: dict[str, Any],
    group_sequence: str | None,
    iteration: int,
    root: Path,
    *,
    log_fn: LogFn | None = None,
    cancel: CancelFn | None = None,
) -> dict[str, Any] | None:
    if cancel and cancel():
        return None
    steps_raw, note = resolve_steps(ent, iteration, phone, inline_steps=ent.get("steps") or [])
    if not steps_raw and group_sequence:
        try:
            path = resolve_sequence_path(root, group_sequence)
            seq = Sequence.from_json(path)
            seq.phone = phone
            report = runner.run(seq)
            if log_fn:
                log_fn(
                    f"Group {group_name} iter {iteration} {phone}: {seq.name} "
                    f"{'OK' if report.get('success') else 'FAIL'}",
                    "ok" if report.get("success") else "err",
                )
            return report
        except (OSError, ValueError, KeyError, FileNotFoundError) as exc:
            if log_fn:
                log_fn(f"Group {group_name} {phone}: {exc}", "err")
            return {"success": False, "error": str(exc), "phone": phone}
    if not steps_raw:
        if log_fn:
            log_fn(f"Group {group_name} {phone}: no steps for iteration {iteration}", "warn")
        return None
    seq_steps = _inline_steps(steps_raw, phone, log_fn=log_fn)
    if not seq_steps:
        return None
    seq = Sequence(
        name=f"{group_name}:{phone}:{iteration}:{note or 'inline'}",
        phone=phone,
        steps=seq_steps,
    )
    report = runner.run(seq)
    ok = report.get("success")
    err = report.get("error") or ""
    if log_fn:
        msg = f"Group {group_name} iter {iteration} {phone}"
        if note:
            msg += f" [{note}]"
        msg += f": {'OK' if ok else 'FAIL'}"
        if err:
            msg += f" — {err}"
        log_fn(msg, "ok" if ok else "err")
    return report


def run_group(
    farm: MuMuFarmOps,
    groups: GroupManager,
    runner: SequenceRunner,
    name: str,
    *,
    max_iterations: int = 0,
    sequences_root: Path | None = None,
    log_fn: LogFn | None = None,
    cancel: CancelFn | None = None,
) -> dict[str, Any]:
    """Execute a group run (same logic as dashboard ``/api/groups/<name>/run``)."""
    group = groups.get_group(name)
    if not group:
        return {"success": False, "error": "group not found", "group": name}

    root = sequences_root or sequences_dir()

    def _log(message: str, kind: str = "info") -> None:
        if log_fn:
            log_fn(message, kind)
        else:
            logger.info("[%s] %s", kind, message)

    reports: list[dict[str, Any]] = []
    iteration = 0
    forever = bool(group.repeat_forever)
    if max_iterations > 0:
        target: int | None = max_iterations
    elif forever:
        target = None
    else:
        target = max(1, int(group.repeat or 1))
    phones = [p for p in (_canonical_phone(farm, x) for x in group.phones) if p]
    if not phones:
        return {"success": False, "error": "no valid phones in group", "group": name}
    if group.shuffle:
        random.shuffle(phones)

    while target is None or iteration < target:
        if cancel and cancel():
            _log(f"Group {name} cancelled at iteration {iteration}", "warn")
            break
        threads: list[threading.Thread] = []
        thread_reports: list[dict[str, Any] | None] = []
        lock = threading.Lock()

        def _phone_worker(phone: str) -> None:
            ent = group.ensure_phone_entry(phone)
            hits = int(ent.get("hits_per_day") or 0)
            if hits > 0 and iteration >= hits:
                return
            report = _run_phone_once(
                farm,
                runner,
                name,
                phone,
                ent,
                group.sequence,
                iteration,
                root,
                log_fn=_log,
                cancel=cancel,
            )
            if report is not None:
                with lock:
                    thread_reports.append(report)

        for idx, phone in enumerate(phones):
            if cancel and cancel():
                break
            t = threading.Thread(target=_phone_worker, args=(phone,), name=f"group-{name}-{phone}")
            t.start()
            threads.append(t)
            if group.stagger_seconds > 0 and idx < len(phones) - 1:
                time.sleep(float(group.stagger_seconds))
        for t in threads:
            t.join()
        reports.extend(r for r in thread_reports if r is not None)
        iteration += 1

    success = all(r.get("success") for r in reports) if reports else False
    return {"success": success, "iterations": iteration, "reports": reports, "group": name}


def _inline_steps(
    steps_raw: list[Any],
    phone: str,
    *,
    log_fn: LogFn | None = None,
) -> list[SequenceStep]:
    seq_steps: list[SequenceStep] = []
    for s in steps_raw:
        if not isinstance(s, dict):
            continue
        raw_action = s.get("action") or s.get("type") or ""
        try:
            action = StepAction(raw_action)
        except ValueError:
            if log_fn:
                log_fn(f"Unknown action {raw_action!r} on {phone}", "warn")
            continue
        params = dict(s.get("params") or {})
        if not params:
            for key in ("url", "package", "seconds", "x", "y", "cmd", "keycode", "code", "key", "text", "ms"):
                if key in s:
                    params[key] = s[key]
        seq_steps.append(
            SequenceStep(action=action, params=params, description=str(s.get("description") or ""))
        )
    return seq_steps
