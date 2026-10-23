"""
Copy shipped DabFlow sequence JSON from the PharmFlow install tree to the local sequences folder.

Runtime resolves playlists from ``~/PharmFlow/sequences`` (or ``PHARMFLOW_SEQUENCES_DIR``).
The git repo (and GitHub ZIP install) keeps canonical JSON under ``sequences/`` at repo root —
this module syncs those files onto the operator PC.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable

LogFn = Callable[[str], None]

# Playlist refs written by PharmFlowMuMuSetup (50/50 combined shuffle) — must exist after sync.
DEFAULT_PLAYLIST_REFS = (
    "900x1600/no-ad/dabflow__demo__ONE.json",
    "900x1600/no-ad/dabflow__no_ads__mat-quartz__conc-shatter__heat-butane.json",
    "900x1600/ad/dabflow__demo__TWO.json",
    "900x1600/ad/dabflow__ad__mat-quartz__conc-shatter__heat-butane.json",
    "900x1600/ad/dabflow__ad__mat-quartz__conc-wax__heat-propane.json",
    "900x1600/ad/dabflow__ad__mat-titanium__conc-live-resin__heat-butane.json",
    "900x1600/ad/dabflow__ad__mat-ceramic__conc-rosin__heat-propane.json",
)


def _repo_root_from_here() -> Path | None:
    here = Path(__file__).resolve().parent
    candidate = here.parent / "sequences"
    if candidate.is_dir() and any(candidate.rglob("dabflow*.json")):
        return here.parent
    return None


def find_shipped_sequences_source() -> Path | None:
    """Best ``sequences/`` tree to copy from (repo root, install dir, or env)."""
    env = (os.environ.get("PHARMFLOW_SEQUENCES_SOURCE") or "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_dir() and any(p.rglob("dabflow*.json")):
            return p.resolve()

    roots: list[Path] = []
    repo = _repo_root_from_here()
    if repo is not None:
        roots.append(repo / "sequences")

    for key in ("PHARMFLOW_HOME",):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            roots.append(Path(raw).expanduser().parent / "sequences")
            roots.append(Path(raw).expanduser() / "sequences")

    try:
        from wizard_paths import pharmflow_search_roots_ordered

        for root in pharmflow_search_roots_ordered():
            roots.append(root / "sequences")
            roots.append(root.parent / "sequences")
    except Exception:
        pass

    exe_parent: Path | None = None
    try:
        import sys

        if getattr(sys, "frozen", False):
            exe_parent = Path(sys.executable).resolve().parent
            roots.append(exe_parent / "sequences")
            for name in ("pharmflow-main", "pharmflow", "PharmFlow"):
                roots.append(exe_parent / name / "sequences")
    except Exception:
        pass

    seen: set[str] = set()
    for root in roots:
        try:
            r = root.resolve()
        except OSError:
            continue
        key = str(r).lower()
        if key in seen or not r.is_dir():
            continue
        seen.add(key)
        if any(r.rglob("dabflow*.json")):
            return r
    return None


def sync_shipped_sequences(
    dest: Path | None = None,
    log: LogFn | None = None,
    *,
    force: bool = False,
) -> dict:
    """
    Copy ``sequences/**/*.json`` from the shipped source into ``dest``.

    Returns ``{ok, copied, skipped, source, dest, missing_playlists}``.
    """
    from sequences_paths import resolve_sequences_dir

    log = log or (lambda _m: None)
    src = find_shipped_sequences_source()
    dst = (dest or resolve_sequences_dir(create=True)).resolve()

    if src is None:
        log("  No shipped sequences source found (run PharmFlow Install first).")
        return {
            "ok": False,
            "copied": 0,
            "skipped": 0,
            "source": "",
            "dest": str(dst),
            "missing_playlists": list(DEFAULT_PLAYLIST_REFS),
        }

    src = src.resolve()
    copied = 0
    skipped = 0
    log(f"  Syncing sequences: {src} → {dst}")
    for json_path in sorted(src.rglob("*.json")):
        if json_path.name.startswith("_"):
            continue
        rel = json_path.relative_to(src)
        target = dst / rel
        if target.is_file() and not force:
            try:
                if target.stat().st_mtime >= json_path.stat().st_mtime:
                    skipped += 1
                    continue
            except OSError:
                pass
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(json_path, target)
        copied += 1

    missing = [ref for ref in DEFAULT_PLAYLIST_REFS if not (dst / ref).is_file()]
    ok = not missing
    log(f"  Sequences: {copied} copied, {skipped} up-to-date.")
    if missing:
        log(f"  WARNING: {len(missing)} playlist file(s) still missing after sync.")
    return {
        "ok": ok,
        "copied": copied,
        "skipped": skipped,
        "source": str(src),
        "dest": str(dst),
        "missing_playlists": missing,
    }


def verify_playlist_refs(
    refs: list[str],
    *,
    sequences_dir: Path | None = None,
) -> list[str]:
    """Return playlist refs that are missing on disk."""
    from sequences_paths import resolve_sequences_dir

    root = sequences_dir or resolve_sequences_dir(create=False)
    missing: list[str] = []
    for ref in refs:
        if not ref or not str(ref).strip().endswith(".json"):
            continue
        if not (root / str(ref).replace("\\", "/")).is_file():
            missing.append(ref)
    return missing
