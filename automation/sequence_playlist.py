"""Resolve per-phone playlists (ordered / random / series) for group runs."""

from __future__ import annotations

import hashlib
import json
import logging
import random
from pathlib import Path
from typing import Any

from automation.sequence_paths import resolve_sequence_path
from wizard.wizard_paths import sequences_dir

log = logging.getLogger(__name__)

# Sequences root used by normalize_playlist_ref / resolve_sequence_file /
# folder_json_refs when no explicit directory is passed. This was previously
# referenced but never defined — any caller without an explicit directory
# (e.g. the dashboard's /api/groups/save normalizing playlist refs) crashed
# with NameError. Same source as load_steps_from_filename's default.
def _resolve_sequences_dir() -> Path:
    try:
        return sequences_dir()
    except Exception:  # noqa: BLE001 — frozen-app path failures must not kill imports
        return Path.cwd() / "automation" / "recordings" / "sequences"


SEQUENCES_DIR = _resolve_sequences_dir()

FOLDER_MODES = {"folder", "folder_sorted", "folder_random"}
PLAYLIST_MODES = {"ordered", "random", "series"} | FOLDER_MODES
_COMBO_REQUIRED_TAIL_TYPES = ("rotate_identity", "wait", "full_reset")

SHUFFLE_MODES = frozenset({"none", "set_a", "set_b", "both_sets_separately", "combined"})


def _normalize_shuffle(raw: Any) -> str:
    s = (str(raw or "none")).strip().lower()
    return s if s in SHUFFLE_MODES else "none"


def _stable_seed(serial: str, iteration: int) -> int:
    digest = hashlib.sha256(f"{serial}:{iteration}".encode()).hexdigest()
    return int(digest[:8], 16)


def _shuffle_names(names: list[str], iteration: int, serial: str) -> list[str]:
    if len(names) <= 1:
        return list(names)
    rng = random.Random(_stable_seed(serial, iteration))
    out = list(names)
    rng.shuffle(out)
    return out


def _apply_playlist_shuffle(
    primary: list[str],
    secondary: list[str],
    shuffle: str,
    iteration: int,
    serial: str,
) -> tuple[list[str], list[str]]:
    sh = _normalize_shuffle(shuffle)
    if sh == "combined":
        merged = list(primary) + list(secondary)
        return _shuffle_names(merged, iteration, serial), []
    if sh == "set_a":
        return _shuffle_names(primary, iteration, serial), list(secondary)
    if sh == "set_b":
        return list(primary), _shuffle_names(secondary, iteration, serial)
    if sh == "both_sets_separately":
        return (
            _shuffle_names(primary, iteration, serial),
            _shuffle_names(secondary, iteration, serial),
        )
    return list(primary), list(secondary)


def _playlist_basenames(raw: Any) -> list[str]:
    if not isinstance(raw, list) or not raw:
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def pick_rotating_filename(
    names: list[str], mode: str, iteration: int, serial: str
) -> str | None:
    if not names:
        return None
    m = (mode or "ordered").strip().lower()
    if m == "random":
        rng = random.Random(_stable_seed(serial, iteration))
        return names[rng.randint(0, len(names) - 1)]
    return names[iteration % len(names)]


def load_steps_from_filename(name: str, directory: Path | str | None = None) -> list[dict[str, Any]] | None:
    """Load steps from a sequence JSON (basename or relative id).

    ``directory`` may be a :class:`Path` (used as root directly) or a string
    profile key (resolved via :func:`resolve_sequence_file`).
    """
    if isinstance(directory, str):
        resolved = resolve_sequence_file(name, profile_key=directory)
        if resolved is not None:
            path = resolved
        else:
            log.warning("sequence playlist file missing: %s", name)
            return None
    else:
        root = directory or SEQUENCES_DIR
        direct = Path(name)
        if direct.is_file():
            path = direct
        else:
            candidate = root / name
            if candidate.is_file():
                path = candidate
            else:
                try:
                    path = resolve_sequence_path(root, name)
                except FileNotFoundError:
                    log.warning("sequence playlist file missing: %s", name)
                    return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("sequence playlist bad JSON %s: %s", path, exc)
        return None
    if isinstance(data, list):
        steps = data
    else:
        steps = data.get("steps")
    if not isinstance(steps, list):
        return None
    # Normalize prior CPharm "type" field to FamFlow "action".
    out: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        item = dict(step)
        if "action" not in item and "type" in item:
            item["action"] = item["type"]
        out.append(item)
    return out


def resolve_steps(
    ent: dict[str, Any],
    iteration: int,
    serial: str,
    inline_steps: list[Any] | None = None,
    directory: Path | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Return (steps_to_run, playlist_note). Falls back to inline steps."""
    primary = _playlist_basenames(ent.get("sequence_playlist"))
    secondary = _playlist_basenames(ent.get("sequence_playlist_secondary"))
    shuffle_mode = _normalize_shuffle(ent.get("sequence_playlist_shuffle"))
    primary, secondary = _apply_playlist_shuffle(
        primary, secondary, shuffle_mode, iteration, serial
    )
    mode = (ent.get("sequence_playlist_mode") or "ordered").strip().lower()
    if mode not in ("ordered", "random", "series"):
        mode = "ordered"

    if not primary and not secondary:
        return list(inline_steps or []), None

    if mode == "series":
        combined: list[dict[str, Any]] = []
        labels: list[str] = []
        for name in primary + secondary:
            loaded = load_steps_from_filename(name, directory)
            if not loaded:
                continue
            combined.extend(loaded)
            labels.append(name)
        if combined:
            return combined, "series:" + "+".join(labels)
        return list(inline_steps or []), None

    steps_acc: list[dict[str, Any]] = []
    tag_parts: list[str] = []
    fn_a = pick_rotating_filename(primary, mode, iteration, serial) if primary else None
    fn_b = pick_rotating_filename(secondary, mode, iteration, serial) if secondary else None
    for fn in (fn_a, fn_b):
        if not fn:
            continue
        loaded = load_steps_from_filename(fn, directory)
        if loaded:
            steps_acc.extend(loaded)
            tag_parts.append(fn)
    if steps_acc:
        return steps_acc, "+".join(tag_parts)
    return list(inline_steps or []), None


def estimate_step_count(ent: dict[str, Any], inline_steps: list[Any] | None = None) -> int:
    primary = _playlist_basenames(ent.get("sequence_playlist"))
    secondary = _playlist_basenames(ent.get("sequence_playlist_secondary"))
    if primary or secondary:
        tot = 0
        for name in primary + secondary:
            loaded = load_steps_from_filename(name)
            tot += len(loaded) if loaded else 1
        return max(tot, 1)
    return len(inline_steps or [])


# ==== merged from cpharm automation/sequence_playlist.py (old playlist API) ====

def normalize_playlist_ref(raw: str, *, sequences_dir: Path | None = None) -> str:
    """Normalize a playlist entry to a safe path relative to the sequences root.

    Preserves subpaths such as ``900x1600/ad/foo.json``. Absolute paths under the
    sequences tree are relativized; other absolute paths collapse to basename only.
    """
    t = str(raw or "").strip().replace("\\", "/")
    if not t or not t.lower().endswith(".json"):
        return ""
    if ".." in t.split("/"):
        t = Path(t).name
    root = sequences_dir or SEQUENCES_DIR
    p = Path(t)
    if p.is_absolute():
        try:
            return p.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return p.name
    return t.lstrip("/")



def _profile_key_from_ent(ent: dict) -> str:
    pk = str(ent.get("sequence_profile_key") or "").strip()
    if pk:
        return pk
    try:
        bw = int(ent.get("sequence_base_w") or 900)
        bh = int(ent.get("sequence_base_h") or 1600)
        if bw > 0 and bh > 0:
            return f"{bw}x{bh}"
    except (TypeError, ValueError):
        pass
    return "900x1600"



def resolve_sequence_file(name: str, profile_key: str | None = None) -> Path | None:
    """Resolve a playlist ref to an on-disk JSON under the local sequences folder."""
    ref = normalize_playlist_ref(name)
    if not ref:
        return None
    direct = SEQUENCES_DIR / ref
    if direct.is_file():
        return direct
    base = Path(ref).name
    pk = (profile_key or "").strip()
    if pk:
        pk_dir = SEQUENCES_DIR / pk
        if pk_dir.is_dir():
            for cand in pk_dir.rglob(base):
                if cand.is_file():
                    return cand
    flat = SEQUENCES_DIR / base
    if flat.is_file():
        return flat
    return None



def normalize_sequence_folder(raw) -> str:
    """Normalize ``sequence_folder`` to a safe path relative to the sequences root."""
    t = str(raw or "").strip().replace("\\", "/").strip("/")
    if not t or ".." in t.split("/"):
        return ""
    return t



def folder_json_refs(
    ent: dict,
    iteration: int,
    serial: str,
    *,
    sequences_dir: Path | None = None,
) -> list[str]:
    """Resolve ``sequence_folder`` to sorted ``*.json`` refs (shuffle when ``folder_random``)."""
    folder = normalize_sequence_folder(ent.get("sequence_folder"))
    if not folder:
        return []
    root = sequences_dir or SEQUENCES_DIR
    dir_path = root / folder
    if not dir_path.is_dir():
        log.warning("sequence folder missing: %s", dir_path)
        return []
    files = sorted(
        p
        for p in dir_path.glob("*.json")
        if p.is_file() and not p.name.startswith("_")
    )
    refs = [p.relative_to(root.resolve()).as_posix() for p in files]
    mode = (ent.get("sequence_playlist_mode") or "").strip().lower()
    if mode == "folder_random" and len(refs) > 1:
        refs = _shuffle_names(refs, iteration, serial)
    return refs



def _playlist_refs(raw) -> list[str]:
    if not isinstance(raw, list) or not raw:
        return []
    out: list[str] = []
    for x in raw:
        ref = normalize_playlist_ref(str(x))
        if ref and ref not in out:
            out.append(ref)
    return out



def playlist_cycle_length(ent: dict) -> int:
    """
    Group iterations needed to visit each playlist slot once in ``ordered`` / ``random``.

    ``series`` chains every file in a single iteration, so one group iteration suffices.
    Inline-only phones (no playlist) also return 1.
    """
    mode = (ent.get("sequence_playlist_mode") or "ordered").strip().lower()
    if mode in FOLDER_MODES:
        return 1
    primary = _playlist_refs(ent.get("sequence_playlist"))
    secondary = _playlist_refs(ent.get("sequence_playlist_secondary"))
    if not primary and not secondary:
        return 1
    if mode == "series":
        return 1
    shuffle_mode = _normalize_shuffle(ent.get("sequence_playlist_shuffle"))
    if shuffle_mode == "combined":
        return max(len(primary) + len(secondary), 1)
    return max(len(primary), len(secondary), 1)



def is_playlist_cycle_end(ent: dict, iteration: int) -> bool:
    """True when ``iteration`` (0-based) completes a full ordered/random playlist cycle."""
    cycle = playlist_cycle_length(ent)
    return cycle <= 1 or (iteration + 1) % cycle == 0



def _combo_tail_present(steps: list) -> bool:
    if not isinstance(steps, list):
        return False
    tail_types = [
        step.get("type") for step in steps if isinstance(step, dict) and step.get("type")
    ]
    if len(tail_types) < len(_COMBO_REQUIRED_TAIL_TYPES):
        return False
    return tuple(tail_types[-3:]) == _COMBO_REQUIRED_TAIL_TYPES



def _strip_trailing_ip_id_tail(steps: list) -> list:
    """Remove canonical identity tail from the end of one playlist file's steps."""
    out = list(steps or [])
    types = [
        step.get("type") for step in out if isinstance(step, dict) and step.get("type")
    ]
    if len(types) >= 4 and tuple(types[-4:]) == ("close_app",) + _COMBO_REQUIRED_TAIL_TYPES:
        return out[: len(out) - 4]
    if len(types) >= 3 and tuple(types[-3:]) == _COMBO_REQUIRED_TAIL_TYPES:
        return out[: len(out) - 3]
    return out



def _enforce_ip_id_tail(steps: list) -> list:
    out = list(steps or [])
    if _combo_tail_present(out):
        return out
    out.extend(
        [
            {"type": "rotate_identity"},
            {"type": "wait", "seconds": 2.0},
            {"type": "full_reset"},
        ]
    )
    return out



def resolve_step_chunks(
    ent: dict, iteration: int, serial: str, inline_steps: list
) -> list[tuple[list, str | None]]:
    """
    Like :func:`resolve_steps` but ``series`` mode returns one chunk per playlist file
    so callers can insert human gaps between sequence launches.
    """
    profile_key = _profile_key_from_ent(ent)
    mode = (ent.get("sequence_playlist_mode") or "ordered").strip().lower()
    if mode not in PLAYLIST_MODES:
        mode = "ordered"

    if mode in FOLDER_MODES:
        folder_refs = folder_json_refs(ent, iteration, serial)
        if not folder_refs:
            inline = list(inline_steps or [])
            return [(inline, None)] if inline else []
        chunks: list[tuple[list, str | None]] = []
        for name in folder_refs:
            loaded = load_steps_from_filename(name, profile_key)
            if loaded is None or len(loaded) == 0:
                if loaded is not None and len(loaded) == 0:
                    log.warning("sequence playlist empty array in %s — skipping", name)
                continue
            chunks.append((_strip_trailing_ip_id_tail(loaded), name))
        if not chunks:
            inline = list(inline_steps or [])
            return [(inline, None)] if inline else []
        last_steps, last_name = chunks[-1]
        chunks[-1] = (_enforce_ip_id_tail(last_steps), last_name)
        return chunks

    primary = _playlist_refs(ent.get("sequence_playlist"))
    secondary = _playlist_refs(ent.get("sequence_playlist_secondary"))
    shuffle_mode = _normalize_shuffle(ent.get("sequence_playlist_shuffle"))
    primary, secondary = _apply_playlist_shuffle(
        primary, secondary, shuffle_mode, iteration, serial
    )

    if not primary and not secondary:
        inline = list(inline_steps or [])
        return [(inline, None)] if inline else []

    if mode != "series":
        steps, note = resolve_steps(ent, iteration, serial, inline_steps)
        return [(steps, note)] if steps else []

    chunks: list[tuple[list, str | None]] = []
    for name in primary + secondary:
        loaded = load_steps_from_filename(name, profile_key)
        if loaded is None or len(loaded) == 0:
            if loaded is not None and len(loaded) == 0:
                log.warning("sequence playlist empty array in %s — skipping", name)
            continue
        chunks.append((_strip_trailing_ip_id_tail(loaded), name))

    if not chunks:
        inline = list(inline_steps or [])
        return [(inline, None)] if inline else []

    last_steps, last_name = chunks[-1]
    chunks[-1] = (_enforce_ip_id_tail(last_steps), last_name)
    return chunks


