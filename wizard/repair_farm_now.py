#!/usr/bin/env python3
"""One-shot repair: reseed groups, sync sequences, re-apply fingerprint masking."""
from __future__ import annotations

import sys
from pathlib import Path

WIZARD = Path(__file__).resolve().parent
sys.path.insert(0, str(WIZARD))

from mumu_setup_core import (  # noqa: E402
    adb_devices,
    data_root,
    write_desktop_prefs,
    write_groups_config,
)
from mumu_setup_core import _sync_local_sequences  # noqa: E402
import mumu_farm_ops as farm  # noqa: E402


def log(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"), flush=True)


def main() -> int:
    serials = adb_devices()
    if not serials:
        log("ERROR: no adb devices — start MuMu phones with USB debugging ON")
        return 1

    root = data_root()
    log(f"Data root: {root}")
    log(f"Phones ({len(serials)}):")
    for i, s in enumerate(serials, 1):
        log(f"  {i}. {s}")

    log("")
    log("Reseeding groups_config.json with playlists for every phone…")
    gp = write_groups_config(serials, root, force=True)
    log(f"  Wrote: {gp}")

    log("")
    log("Syncing sequence files…")
    sync = _sync_local_sequences(log)
    if not sync.get("ok"):
        log(f"  WARN: sequence sync issue: {sync}")
    else:
        log(f"  Sequences at: {sync.get('dest')}")

    log("")
    log("Saving desktop_prefs (phone order + mask flags)…")
    write_desktop_prefs(serials, root, setup_complete=True, awaiting_cold_boot=False)

    log("")
    log("Re-applying browser fingerprint + emulator hide (no VM patch)…")
    summary = farm.apply_fingerprint_all(serials, log, patch_vms=False)
    log(f"  leaks_total={summary.get('leaks_total')} phones_with_leaks={summary.get('phones_with_leaks')}")

    log("")
    log("DONE — open PharmFlow → Run (step 9) → Start service → Run all groups")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
