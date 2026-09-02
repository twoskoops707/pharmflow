#!/usr/bin/env python3
"""Watch farm_354_results.jsonl, review failures, FIX broken sequences as found.

Runs alongside the farm. On each new FAIL:
  - classifies error
  - logs review note (local only — never ntfy about fails)
  - isolation/proxy → repin inject
  - early ADB/disconnect → reconnect + force 900x1600
  - timer / age-gate / FRE → bump shared wait overrides
  - tap/swipe/launch at failed_at → patch THAT sequence JSON (waits/duration/tol)
  - after repeated same-stem patches still failing → live quarantine so _pick skips it

  py -u scripts/farm_fail_review.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import automation.no_window  # noqa: E402,F401  — hide adb consoles

RESULTS = Path(r"C:\CPharm\logs\farm_354_results.jsonl")
REVIEW_LOG = Path(r"C:\CPharm\logs\farm_fail_review.log")
REVIEW_JSONL = Path(r"C:\CPharm\logs\farm_fail_reviews.jsonl")
STATE = Path(r"C:\CPharm\logs\farm_fail_review_state.json")
OVERRIDES = Path(r"C:\CPharm\logs\farm_runtime_overrides.json")
QUARANTINE = Path(r"C:\CPharm\logs\farm_seq_quarantine.json")
PATCH_JSONL = Path(r"C:\CPharm\logs\farm_seq_patches.jsonl")
SEQ_ROOT = Path(r"C:\CPharm\automation\recordings\sequences")

PHONES = ("vm0.gmadoa", "vm1.gmadoa", "vm2.gmadoa", "vm3.gmadoa", "vm4.gmadoa", "vm5.gmadoa")
RECOVER_COOLDOWN_S = 45.0
PATCH_COOLDOWN_S = 20.0
MAX_PATCHES_PER_STEP = 3
TARGET_WM = "900x1600"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _setup() -> logging.Logger:
    REVIEW_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("farm_fail_review")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(REVIEW_LOG, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    # Only attach console handler when we have a real TTY — DEVNULL/pythonw
    # + StreamHandler has crashed this loop under farm_cycles/ensure spawn.
    try:
        if sys.stdout and hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
            sh = logging.StreamHandler(sys.stdout)
            sh.setFormatter(fmt)
            log.addHandler(sh)
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
            except Exception:
                pass
    except Exception:
        pass
    return log


log = _setup()


def classify(row: dict) -> str:
    err = str(row.get("error") or "").lower()
    elapsed = float(row.get("elapsed_s") or 0)
    if "isolation" in err or "guest proxy" in err or "http_proxy" in err or "':0'" in err or '":0"' in err:
        return "isolation_proxy"
    if "bad resolution" in err or (
        elapsed < 5.0 and ("adb" in err or "device" in err or "serial" in err or not err)
    ):
        return "early_disconnect"
    if "start perfect dab" in err or ("timer" in err and "confirm" in err):
        return "timer_fail"
    if err in ("tap", "swipe") or err.startswith("tap ") or err.startswith("swipe "):
        return "adb_gesture"
    if "launch_app" in err or err == "launch_app":
        return "launch_app"
    if "open_url" in err or "open url" in err:
        return "open_url"
    if "close_app" in err or err == "close_app":
        return "close_app"
    if "fre" in err or "signed out" in err or "splash" in err:
        return "fre_splash"
    if "age" in err or "gate" in err:
        return "age_gate"
    if elapsed < 5.0:
        return "early_abort"
    if "halfway" in str(row.get("stem") or row.get("sequence") or ""):
        return "path2_halfway"
    return "other"


def _load_overrides() -> dict:
    if OVERRIDES.exists():
        try:
            data = json.loads(OVERRIDES.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def persist_overrides(updates: dict[str, str]) -> str:
    """Write wait bumps so farm processes / next cycle can consume them."""
    if not updates:
        return "no override updates"
    data = _load_overrides()
    changed: list[str] = []
    for key, value in updates.items():
        prev = str(data.get(key) or "")
        try:
            if prev and float(value) <= float(prev):
                continue
        except ValueError:
            pass
        if prev != value:
            data[key] = value
            changed.append(f"{key}={value}")
            os.environ[key] = value
    data["updated"] = _utc()
    OVERRIDES.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDES.write_text(json.dumps(data, indent=2), encoding="utf-8")
    if not changed:
        return "overrides unchanged (" + ", ".join(f"{k}={updates[k]}" for k in updates) + ")"
    return "persisted " + ", ".join(changed)


def recover_phone(phone: str | None, state: dict) -> str:
    """Reconnect ADB and force authored 900x1600 on the failing phone (rate-limited)."""
    name = (phone or "").strip() or None
    targets = (name,) if name and name in PHONES else PHONES
    last_map = state.setdefault("last_recover_by_phone", {})
    now = time.time()
    bits: list[str] = []
    try:
        from wizard.mumu_farm_ops import MuMuFarmOps

        farm = MuMuFarmOps()
        farm.list_instances()
        farm.refresh_serials()
        for pname in targets:
            prev = float(last_map.get(pname) or 0)
            if now - prev < RECOVER_COOLDOWN_S:
                bits.append(f"{pname}=cooldown")
                continue
            last_map[pname] = now
            connected = False
            try:
                connected = bool(farm.connect_adb(pname))
            except Exception as exc:
                bits.append(f"{pname}=connect_err:{exc}")
                continue
            inst = farm.get_phone(pname)
            if not inst or not inst.adb_serial:
                bits.append(f"{pname}=no_serial")
                continue
            serial = inst.adb_serial
            try:
                farm.adb.shell(f"wm size {TARGET_WM}", serial=serial, timeout=8.0)
            except Exception:
                pass
            try:
                size = (farm.adb.shell("wm size", serial=serial, timeout=8.0).stdout or "").strip()
            except Exception as exc:
                bits.append(f"{pname}=wm_err:{exc}")
                continue
            ok_echo = False
            try:
                ok_echo = "ok" in (farm.adb.shell("echo ok", serial=serial, timeout=5.0).stdout or "")
            except Exception:
                pass
            size_ok = TARGET_WM.replace(" ", "") in size.replace(" ", "")
            bits.append(
                f"{pname}=conn:{int(connected)} echo:{int(ok_echo)} size_ok:{int(size_ok)} wm={size[:40]!r}"
            )
        return "recover " + "; ".join(bits)
    except Exception as exc:
        return f"recover failed: {exc}"


def repin_inject(phone: str | None) -> str:
    """Restore inject guest proxy after isolation left :0 / null."""
    try:
        from automation.browse_proxy import pin_guest_proxy
        from wizard.mumu_farm_ops import MuMuFarmOps

        farm = MuMuFarmOps()
        farm.list_instances()
        farm.refresh_serials()
        name = (phone or "").strip()
        targets = (name,) if name and name in PHONES else PHONES
        bits: list[str] = []
        for pname in targets:
            inst = farm.get_phone(pname)
            if not inst or not inst.adb_serial:
                bits.append(f"{pname}=no_serial")
                continue
            idx = int(getattr(inst, "index", 0) or 0)
            ok = bool(pin_guest_proxy(farm.adb, inst.adb_serial, idx))
            bits.append(f"{pname}=pin:{int(ok)}")
        return "repin " + "; ".join(bits)
    except Exception as exc:
        return f"repin failed: {exc}"


def _find_seq(stem: str) -> Path | None:
    stem = (stem or "").strip()
    if not stem:
        return None
    direct = SEQ_ROOT / f"{stem}.json"
    if direct.is_file():
        return direct
    hits = list(SEQ_ROOT.rglob(f"{stem}.json"))
    return hits[0] if hits else None


def _load_quarantine() -> dict:
    if QUARANTINE.is_file():
        try:
            data = json.loads(QUARANTINE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {"updated": _utc(), "stems": {}}


def quarantine_stem(stem: str, *, reason: str) -> str:
    stem = (stem or "").strip()
    if not stem:
        return "quarantine skipped (no stem)"
    data = _load_quarantine()
    stems = data.setdefault("stems", {})
    stems[stem] = {"reason": reason[:200], "ts": _utc()}
    data["updated"] = _utc()
    QUARANTINE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return f"quarantined {stem}"


def patch_sequence_json(row: dict, state: dict) -> str:
    """Patch the failing step / preceding wait in the sequence JSON on disk."""
    stem = str(row.get("stem") or row.get("sequence") or "").strip()
    if not stem:
        return "patch skipped (no stem)"
    failed_at = row.get("failed_at")
    try:
        idx = int(failed_at) if failed_at is not None else -1
    except (TypeError, ValueError):
        idx = -1
    if idx < 0:
        return "patch skipped (no failed_at)"

    path = _find_seq(stem)
    if path is None:
        return f"patch skipped (missing file {stem})"

    key = f"{stem}@{idx}"
    patches = state.setdefault("stem_patches", {})
    last_ts = state.setdefault("last_patch_ts", {})
    now = time.time()
    if now - float(last_ts.get(key) or 0) < PATCH_COOLDOWN_S:
        return f"patch cooldown {key}"
    n = int(patches.get(key) or 0)
    if n >= MAX_PATCHES_PER_STEP:
        return quarantine_stem(
            stem,
            reason=f"still failing after {n} patches at step {idx}: {row.get('error')}",
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"patch read fail: {exc}"
    steps = data.get("steps")
    if not isinstance(steps, list) or idx >= len(steps):
        return f"patch skipped (bad steps idx={idx})"

    changed: list[str] = []
    # Always stretch the wait immediately before the failing step when present.
    if idx > 0 and str(steps[idx - 1].get("action") or "") == "wait":
        params = steps[idx - 1].setdefault("params", {})
        secs = params.get("seconds")
        if isinstance(secs, dict):
            for k in ("min", "max"):
                if k in secs:
                    try:
                        secs[k] = round(float(secs[k]) * 1.4 + 0.2, 2)
                    except (TypeError, ValueError):
                        pass
            changed.append(f"wait@{idx - 1}")
        elif isinstance(secs, (int, float)):
            params["seconds"] = round(float(secs) * 1.4 + 0.2, 2)
            changed.append(f"wait@{idx - 1}")

    step = steps[idx]
    action = str(step.get("action") or "")
    params = step.setdefault("params", {})
    if action == "swipe":
        dur = params.get("duration_ms", params.get("duration"))
        if isinstance(dur, (int, float)):
            params["duration_ms"] = int(min(950, max(int(dur) + 80, int(dur * 1.3))))
            changed.append("swipe_duration")
        # Nudge scroll travel slightly if nearly flat.
        try:
            y1 = float(params.get("y1") or params.get("y_start") or 0)
            y2 = float(params.get("y2") or params.get("y_end") or 0)
            if abs(y1 - y2) < 180:
                mid = (y1 + y2) / 2.0
                params["y1"] = int(mid + 320)
                params["y2"] = int(mid - 320)
                changed.append("swipe_travel")
        except (TypeError, ValueError):
            pass
    elif action == "tap":
        for axis in ("x", "y"):
            ax = params.get(axis)
            if isinstance(ax, dict) and "tolerance" in ax:
                try:
                    ax["tolerance"] = int(min(28, int(ax["tolerance"]) + 6))
                    changed.append(f"tol_{axis}")
                except (TypeError, ValueError):
                    pass
        # Insert a short settle wait after this tap if next step is another tap/swipe.
        if idx + 1 < len(steps) and str(steps[idx + 1].get("action") or "") in ("tap", "swipe"):
            insert = {
                "action": "wait",
                "description": f"Settle after patched tap (auto-fix step {idx})",
                "params": {"seconds": {"min": 0.45, "max": 0.9}},
            }
            # Avoid stacking duplicate auto waits.
            desc = str(steps[idx + 1].get("description") or "")
            if "auto-fix" not in desc:
                steps.insert(idx + 1, insert)
                changed.append("insert_settle")

    if not changed:
        return f"patch noop {stem}@{idx} action={action}"

    bak = path.with_suffix(".json.bak_failfix")
    try:
        if not bak.is_file():
            bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        return f"patch write fail: {exc}"

    patches[key] = n + 1
    last_ts[key] = now
    note = {
        "time": _utc(),
        "stem": stem,
        "path": str(path),
        "failed_at": idx,
        "error": row.get("error"),
        "changed": changed,
        "patch_n": n + 1,
    }
    with PATCH_JSONL.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(note) + "\n")
    return f"patched {stem}@{idx} n={n + 1} " + ",".join(changed)


def apply_fix(kind: str, row: dict, state: dict) -> str:
    """Mutate overrides / phone / sequence JSON for subsequent runs."""
    actions: list[str] = []
    phone = row.get("phone")
    if kind in ("early_disconnect", "early_abort"):
        actions.append(recover_phone(str(phone) if phone else None, state))
        actions.append(persist_overrides({"CPHARM_GEO_TIME_WINDOW": "1"}))
    if kind == "isolation_proxy":
        actions.append(repin_inject(str(phone) if phone else None))
        actions.append(recover_phone(str(phone) if phone else None, state))
    if kind in ("adb_gesture", "launch_app", "open_url", "close_app"):
        actions.append(recover_phone(str(phone) if phone else None, state))
        actions.append(patch_sequence_json(row, state))
    if kind == "timer_fail":
        actions.append(
            persist_overrides(
                {
                    "CPHARM_DABFLOW_LOAD_WAIT": "5.5",
                    "CPHARM_AGE_GATE_WAIT": "2.0",
                    "CPHARM_START_DAB_VERIFY_WAIT": "2.5",
                }
            )
        )
        actions.append(recover_phone(str(phone) if phone else None, state))
        actions.append(patch_sequence_json(row, state))
    if kind == "fre_splash":
        actions.append(persist_overrides({"CPHARM_FRE_PAINT_WAIT": "5.5"}))
    if kind == "age_gate":
        actions.append(
            persist_overrides({"CPHARM_AGE_GATE_WAIT": "2.0", "CPHARM_DABFLOW_LOAD_WAIT": "5.5"})
        )
        actions.append(patch_sequence_json(row, state))
    if kind == "path2_halfway":
        actions.append(patch_sequence_json(row, state))
    if kind == "other":
        actions.append(patch_sequence_json(row, state))
    if not actions:
        actions.append("logged for manual review")
    return "; ".join(actions)


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"offset": 0, "counts": {}, "last_recover_by_phone": {}, "stem_patches": {}}


def save_state(state: dict) -> None:
    state.pop("last_ntfy_by_kind", None)
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def tail_new_rows(state: dict) -> list[dict]:
    if not RESULTS.exists():
        return []
    data = RESULTS.read_bytes()
    offset = int(state.get("offset") or 0)
    if offset > len(data):
        offset = 0
    chunk = data[offset:].decode("utf-8", errors="replace")
    state["offset"] = len(data)
    rows: list[dict] = []
    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def review_row(row: dict, state: dict) -> None:
    if row.get("success"):
        return
    kind = classify(row)
    counts = state.setdefault("counts", {})
    counts[kind] = int(counts.get(kind) or 0) + 1
    fix = apply_fix(kind, row, state)
    note = {
        "time": _utc(),
        "phone": row.get("phone"),
        "stem": row.get("stem") or row.get("sequence"),
        "error": row.get("error"),
        "failed_at": row.get("failed_at"),
        "elapsed_s": row.get("elapsed_s"),
        "kind": kind,
        "fix": fix,
    }
    with REVIEW_JSONL.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(note) + "\n")
    log.info(
        "FAIL review phone=%s kind=%s failed_at=%s elapsed=%s err=%r fix=%s",
        note["phone"],
        kind,
        note["failed_at"],
        note["elapsed_s"],
        (note["error"] or "")[:80],
        fix,
    )


def main() -> int:
    crash = Path(r"C:\CPharm\logs\_fail_review_crash.txt")
    try:
        log.info("farm_fail_review starting (no ntfy; patch+quarantine broken seqs)")
        state = load_state()
        # Skip backlog — only new fails from now
        if RESULTS.exists():
            state["offset"] = RESULTS.stat().st_size
            save_state(state)
        # Floor critical waits immediately (current sticky had age_gate=0.5).
        persist_overrides(
            {
                "CPHARM_AGE_GATE_WAIT": "2.0",
                "CPHARM_DABFLOW_LOAD_WAIT": "5.5",
                "CPHARM_START_DAB_VERIFY_WAIT": "2.5",
            }
        )
        while True:
            try:
                rows = tail_new_rows(state)
                for row in rows:
                    review_row(row, state)
                save_state(state)
            except Exception as exc:
                log.exception("review loop: %s", exc)
            time.sleep(12)
    except Exception as exc:
        try:
            crash.write_text(f"{_utc()} FATAL {exc}\n", encoding="utf-8")
        except OSError:
            pass
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
