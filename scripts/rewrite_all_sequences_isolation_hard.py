#!/usr/bin/env python3
"""Regenerate + patch EVERY sequence for hardcoded isolation + ad-tap live-pick labels.

Does not stop until all JSON under the live sequences dir are updated and verified.
Target: C:\\PharmFlow\\automation\\recordings\\sequences (farm runtime) + repo mirror.
"""

from __future__ import annotations

import json
import sys
import time
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from automation.dabflow_sequence_gen import write_catalog, write_presets, write_sequences
from wizard.wizard_paths import sequences_dir

HARD_ROTATE_DESC = "HARD isolation: new Tor exit IP + geo/tz + IMEI + browser identity"
HARD_CLEAR_DESC = "Wipe cookies/cache/site data (no carryover)"
HARD_WAIT_DESC = "Wait after HARD isolation rotate"
ISOLATION_POLICY = "hardcoded_every_seq"


def _normalize_ad_desc(desc: str) -> str:
    low = desc.lower()
    if "tap ad" in low:
        return desc
    if "ad" not in low:
        return desc
    # Legacy banner wording → live-pick friendly "Tap ad (...)"
    if "banner" in low or "sponsored" in low or "mantis" in low or "slot" in low:
        if "post-timer" in low:
            return "Tap ad (post-timer slot)"
        if "home" in low:
            return "Tap ad (home slot)"
        if "stats" in low:
            return "Tap ad (stats slot)"
        if "glass" in low:
            return "Tap ad (glass slot)"
        if "settings" in low:
            return "Tap ad (settings slot)"
        return "Tap ad (sponsored slot)"
    return desc


def _ensure_identity_preamble(steps: list[dict]) -> list[dict]:
    """Guarantee clear_cookies + HARD rotate_identity near the front."""
    out = [deepcopy(s) for s in steps]
    # Update existing rotate / clear / wait descriptions in place.
    for s in out:
        act = s.get("action")
        desc = str(s.get("description") or "")
        if act == "rotate_identity":
            s["description"] = HARD_ROTATE_DESC
        elif act == "clear_cookies":
            s["description"] = HARD_CLEAR_DESC
        elif act == "wait" and (
            "identity scramble" in desc.lower()
            or "after identity" in desc.lower()
            or "hard isolation" in desc.lower()
        ):
            s["description"] = HARD_WAIT_DESC
        elif act == "tap":
            s["description"] = _normalize_ad_desc(desc)

    acts = [s.get("action") for s in out]
    if "rotate_identity" not in acts:
        out.insert(
            0,
            {"action": "rotate_identity", "params": {}, "description": HARD_ROTATE_DESC},
        )
        out.insert(
            1,
            {
                "action": "wait",
                "params": {"seconds": {"min": 1.2, "max": 2.0}},
                "description": HARD_WAIT_DESC,
            },
        )
    if "clear_cookies" not in acts:
        # Prefer clear before rotate
        out.insert(
            0,
            {"action": "clear_cookies", "params": {}, "description": HARD_CLEAR_DESC},
        )
    else:
        # Move clear_cookies before rotate_identity when both exist
        clear_i = next(i for i, s in enumerate(out) if s.get("action") == "clear_cookies")
        rot_i = next(i for i, s in enumerate(out) if s.get("action") == "rotate_identity")
        if clear_i > rot_i:
            clear_step = out.pop(clear_i)
            rot_i = next(i for i, s in enumerate(out) if s.get("action") == "rotate_identity")
            out.insert(rot_i, clear_step)
    return out


def patch_document(data: dict) -> dict:
    out = deepcopy(data)
    out["isolation_policy"] = ISOLATION_POLICY
    out["steps"] = _ensure_identity_preamble(list(out.get("steps") or []))
    return out


def patch_tree(root: Path) -> tuple[int, int, list[str]]:
    """Patch every *.json under root. Returns (ok, fail, errors)."""
    ok = fail = 0
    errors: list[str] = []
    files = sorted(root.rglob("*.json"))
    total = len(files)
    print(f"PATCH {total} json under {root}", flush=True)
    t0 = time.time()
    for i, path in enumerate(files, 1):
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict) or "steps" not in data:
                # presets / non-sequence json — skip
                if "humanize" in data and "steps" not in data:
                    continue
                # still try if it looks like a sequence
            if "steps" not in data:
                continue
            patched = patch_document(data)
            path.write_text(json.dumps(patched, indent=2) + "\n", encoding="utf-8")
            ok += 1
        except Exception as exc:
            fail += 1
            errors.append(f"{path}: {exc}")
        if i % 250 == 0 or i == total:
            elapsed = time.time() - t0
            print(f"  … {i}/{total} patched ok={ok} fail={fail} ({elapsed:.0f}s)", flush=True)
    return ok, fail, errors


def verify_tree(root: Path) -> tuple[int, int, int]:
    """Return (total_seq, with_policy, with_hard_rotate)."""
    total = policy = hard = 0
    for path in root.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "steps" not in data:
            continue
        total += 1
        if data.get("isolation_policy") == ISOLATION_POLICY:
            policy += 1
        descs = " | ".join(
            str(s.get("description") or "") for s in (data.get("steps") or [])
        )
        if HARD_ROTATE_DESC in descs or "HARD isolation" in descs:
            hard += 1
    return total, policy, hard


def main() -> int:
    live = sequences_dir()
    base = live / "base"
    presets = live / "presets"
    catalog = live / "sequence_catalog.md"
    repo_base = ROOT / "automation" / "recordings" / "sequences" / "base"
    repo_live = ROOT / "automation" / "recordings" / "sequences"

    print(f"LIVE sequences_dir={live}", flush=True)
    print("=== REGENERATE 5220 base sequences (PharmFlow) ===", flush=True)
    t0 = time.time()
    write_presets(presets)
    n = write_sequences(base, preset="moderate", base_only=True, clean=True)
    write_catalog(catalog)
    print(f"Generated {n} -> {base} in {time.time() - t0:.0f}s", flush=True)
    if n != 5220:
        print(f"WARNING expected 5220 got {n} — continuing patch of all files", flush=True)

    # Mirror into repo if different path
    if repo_base.resolve() != base.resolve():
        print(f"=== MIRROR regenerate -> {repo_base} ===", flush=True)
        write_sequences(repo_base, preset="moderate", base_only=True, clean=True)

    print("=== PATCH every sequence JSON (isolation_policy + HARD rotate + ad labels) ===", flush=True)
    ok, fail, errs = patch_tree(live)
    print(f"PATCH live done ok={ok} fail={fail}", flush=True)
    if repo_live.resolve() != live.resolve():
        ok2, fail2, errs2 = patch_tree(repo_live)
        print(f"PATCH repo done ok={ok2} fail={fail2}", flush=True)
        errs.extend(errs2)

    print("=== VERIFY ===", flush=True)
    total, policy, hard = verify_tree(live)
    print(
        f"VERIFY live total={total} isolation_policy={policy} HARD_rotate={hard}",
        flush=True,
    )
    if errs:
        print("ERRORS:", flush=True)
        for e in errs[:20]:
            print(f"  {e}", flush=True)

    if total < 5220 or policy < total or hard < total:
        print(
            f"FAIL: not all done total={total} policy={policy} hard={hard}",
            flush=True,
        )
        return 1
    print(f"ALL DONE: {total}/{total} sequences updated for hardcoded isolation", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
