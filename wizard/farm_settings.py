"""Wizard farm-settings catalog + persistence.

Every knob listed here maps to a PHARMFLOW_* env key that the farm runner
(scripts/run_farm_354.py) or its supporting automation modules genuinely read.
The wizard's per-step "Advanced" panels render from CATALOG so the UI can
never drift from what the farm honors.

Persistence is a single user settings file next to the app data root
(``wizard_farm_settings.json``). The farm itself keeps its SSOT in code
(automation.pharmflow_farm_config); this file only records *user overrides* from
the wizard, and :func:`apply_saved_to_env` is called by
``wizard.farm_control.start_farm`` so every lane inherits them as env.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()

# Phone-count ceilings and rate caps. The farm uses every phone on ADB.
# A saved wizard file must not shrink that roster or stop the earn path early.
_EXE_CAP_KEYS = frozenset(
    {
        "PHARMFLOW_FARM_PHONE_COUNT",
        "PHARMFLOW_FARM_EXPECT_PHONES",
        "PHARMFLOW_FARM_SEQS_PER_HOUR",
        "PHARMFLOW_FARM_PATH3_PER_HOUR",
        "PHARMFLOW_FARM_EVENING_SEQS_PER_HOUR",
        "PHARMFLOW_FARM_DAILY_VISITS",
        "PHARMFLOW_FARM_DAILY_ADS",
        "PHARMFLOW_FARM_MIN_SEQ_SPACING_S",
        "PHARMFLOW_SITE_MAP_MAX_PAGES",
    }
)
# Daily visit/ad CSVs are also a plan the runner may have just written.
# Drop them from the wizard file, but do not unset a value the start path
# already put in the environment.
_CAP_KEYS_LEAVE_ENV = frozenset(
    {
        "PHARMFLOW_FARM_DAILY_VISITS",
        "PHARMFLOW_FARM_DAILY_ADS",
    }
)

# step -> display title used by the Advanced panel header.
STEP_TITLES: dict[str, str] = {
    "phones": "Phones",
    "boot": "Test & site",
    "map": "Site Map",
    "steps": "Sequences",
    "teams": "Groups",
    "go": "Run",
}

# Every entry: key (env), step (view), kind, label, hint, and optional options.
# kind: int | float | toggle | select | text | csv
# Values are validated on save; toggles store "1"/"0".
CATALOG: list[dict[str, Any]] = [
    # ── Phones ────────────────────────────────────────────────────────────────
    # No phone-count field. Discovery uses every phone that answers ADB.
    {
        "key": "PHARMFLOW_FARM_BAN_SERIALS",
        "step": "phones",
        "kind": "text",
        "label": "Banned serials",
        "hint": "Comma-separated ADB serials the farm must never use.",
    },
    {
        "key": "PHARMFLOW_REQUIRE_FARM_BROWSERS",
        "step": "phones",
        "kind": "toggle",
        "label": "Require farm browsers first",
        "hint": "Block a phone from farming until its Path 1/2 browsers are sideloaded.",
    },
    {
        "key": "PHARMFLOW_FAST_STICKY_BOOT",
        "step": "phones",
        "kind": "toggle",
        "label": "Fast sticky boot",
        "hint": "Skip the slow full VM rescan at farm start when a known-good lock exists.",
    },
    {
        "key": "PHARMFLOW_TABLET_FARM",
        "step": "phones",
        "kind": "toggle",
        "label": "Tablet farm mode",
        "hint": "Run the tablet lane (Path 1/2 only) alongside the phone fleet.",
    },
    # ── Test / boot ───────────────────────────────────────────────────────────
    {
        "key": "PHARMFLOW_GEO_TIME_WINDOW",
        "step": "boot",
        "kind": "toggle",
        "label": "Geo awake-time window",
        "hint": "Only assign geos whose local time is inside the awake window.",
    },
    {
        "key": "PHARMFLOW_SKIP_BOOT_GEO",
        "step": "boot",
        "kind": "toggle",
        "label": "Skip boot geo pass",
        "hint": "Skip the one-time geo assignment at farm start; per-sequence isolation still geos.",
    },
    {
        "key": "PHARMFLOW_BROWSE_PROXY_MODE",
        "step": "boot",
        "kind": "select",
        "label": "Browse proxy mode",
        "hint": "How each phone's own exit is used. None of these send farm traffic out the host IP.",
        "options": ["scramble", "tor", "direct", "upstream"],
    },
    # Site map has no page ceiling. A saved max would report a partial crawl as done.
    # ── Steps / sequences ─────────────────────────────────────────────────────
    {
        "key": "PHARMFLOW_FARM_PATHS",
        "step": "steps",
        "kind": "text",
        "label": "Active paths",
        "hint": "Comma list of paths to run: 1,2 and 3 (Path 3 is the ad path).",
    },
    {
        "key": "PHARMFLOW_FARM_ALLOW_ADS",
        "step": "steps",
        "kind": "toggle",
        "label": "Allow bottom-ad pools (Path 1/2)",
        "hint": "Enables Path 1/2 ad impression pools. Path 3 is controlled by Active paths (include 3).",
    },
    {
        "key": "PHARMFLOW_FARM_UNIQUE_SEQ",
        "step": "steps",
        "kind": "toggle",
        "label": "Unique-sequence lock",
        "hint": "Never run the same sequence file/ad identity on two phones at once.",
    },
    {
        "key": "PHARMFLOW_SKIP_SEQUENCE_ISOLATION",
        "step": "steps",
        "kind": "toggle",
        "label": "Skip sequence isolation",
        "hint": "DANGER: turns off per-sequence fingerprint/IP isolation. Leave off.",
    },
    # Daily visit/ad lists are not wizard knobs. A short saved list is a rate cap.
    {
        "key": "PHARMFLOW_FARM_IMPRESSIONS_PER_VISIT",
        "step": "teams",
        "kind": "float",
        "label": "Impressions per visit",
        "hint": "Revenue-model impressions target per visit for pacing math.",
    },
    # ── Run / go ──────────────────────────────────────────────────────────────
    {
        "key": "PHARMFLOW_FARM_HOURS",
        "step": "go",
        "kind": "float",
        "label": "Run duration (hours)",
        "hint": "0 = keep running. A number stops the farm after that many hours.",
    },
    {
        "key": "PHARMFLOW_AUTOPILOT_PAUSE",
        "step": "go",
        "kind": "toggle",
        "label": "Pause Mantis autopilot",
        "hint": "Keeps the operator dashboard from auto-reshaping ads while the farm runs.",
    },
    {
        "key": "PHARMFLOW_FARM_START_STAGGER_WINDOW",
        "step": "go",
        "kind": "int",
        "label": "Start stagger window (s)",
        "hint": "Spread over which phones begin their first sequence after farm start.",
    },
    {
        "key": "PHARMFLOW_FARM_START_STAGGER_MIN_GAP",
        "step": "go",
        "kind": "int",
        "label": "Start stagger min gap (s)",
        "hint": "Minimum delay between two phones starting, within the window.",
    },
]

_KEYS_BY_STEP: dict[str, list[dict[str, Any]]] = {}
for _e in CATALOG:
    _KEYS_BY_STEP.setdefault(str(_e["step"]), []).append(_e)


def steps() -> list[str]:
    """Steps that carry an Advanced panel (in wizard order)."""
    return ["phones", "boot", "map", "steps", "teams", "go"]


def catalog_for_step(step: str) -> list[dict[str, Any]]:
    return list(_KEYS_BY_STEP.get(step, []))


def user_settings_path() -> Path:
    try:
        from wizard.wizard_paths import app_data_root

        root = app_data_root()
        return Path(root) / "wizard_farm_settings.json"
    except Exception:
        return Path(r"C:\PharmFlow\wizard_farm_settings.json")


def _settings_candidate_paths() -> list[Path]:
    paths = [
        user_settings_path(),
        Path(r"C:\PharmFlow\wizard_farm_settings.json"),
        Path(r"C:\CPharm\wizard_farm_settings.json"),
    ]
    # Dedupe while preserving order.
    out: list[Path] = []
    seen: set[str] = set()
    for p in paths:
        key = str(p).replace("/", "\\").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _normalize_settings_key(key: str) -> str | None:
    """Accept PHARMFLOW_* and migrate legacy CPHARM_* branding keys."""
    k = str(key or "").strip()
    if not k:
        return None
    if k.startswith("PHARMFLOW_"):
        return k
    if k.startswith("CPHARM_"):
        return "PHARMFLOW_" + k[len("CPHARM_") :]
    return None


def load_saved() -> dict[str, str]:
    """Load farm settings from the freshest PharmFlow/CPharm settings file."""
    newest: tuple[float, dict[str, str]] | None = None
    for path in _settings_candidate_paths():
        try:
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        out: dict[str, str] = {}
        for key, val in data.items():
            nk = _normalize_settings_key(str(key))
            if nk is None or val is None:
                continue
            out[nk] = str(val)
        if not out:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        if newest is None or mtime >= newest[0]:
            newest = (mtime, out)
    return dict(newest[1]) if newest else {}


def _write_saved(data: dict[str, str]) -> None:
    """Persist to PharmFlow and mirror to CPharm so branding cannot split."""
    payload = json.dumps(data, indent=2) + "\n"
    errors: list[str] = []
    for path in (
        user_settings_path(),
        Path(r"C:\PharmFlow\wizard_farm_settings.json"),
        Path(r"C:\CPharm\wizard_farm_settings.json"),
    ):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")
        except OSError as exc:
            errors.append(f"{path}: {exc}")
    if errors and not user_settings_path().is_file():
        raise RuntimeError("cannot persist farm settings: " + "; ".join(errors))


def _runtime_defaults() -> dict[str, str]:
    try:
        from automation.pharmflow_farm_config import get_runtime

        return dict(get_runtime())
    except Exception:
        return {}


def _env_value(key: str) -> str:
    val = os.environ.get(key)
    return str(val).strip() if val is not None and str(val).strip() != "" else ""


def _default_for(key: str) -> str:
    """Best default: runtime SSOT if the key lives there, else the EXE env."""
    val = _runtime_defaults().get(key)
    if val is not None and str(val).strip() != "":
        return str(val)
    return _env_value(key)


def effective_values() -> dict[str, dict[str, str]]:
    """Per catalog key: {value, source} — saved wins, then env, then runtime default."""
    saved = load_saved()
    out: dict[str, dict[str, str]] = {}
    for entry in CATALOG:
        key = str(entry["key"])
        if key in saved and str(saved[key]).strip() != "":
            out[key] = {"value": str(saved[key]), "source": "saved"}
        else:
            env = _env_value(key)
            if env:
                out[key] = {"value": env, "source": "env"}
            else:
                out[key] = {"value": _default_for(key), "source": "default"}
    return out


def _coerce(kind: str, key: str, raw: Any) -> tuple[str | None, str]:
    """Return (error, value-string). None error means the value is valid."""
    val = "" if raw is None else str(raw).strip()
    if val == "":
        return None, val
    try:
        if kind == "int":
            n = int(float(val))
            if n < 0:
                return f"{key}: must be 0 or a positive number", val
            return None, str(n)
        if kind == "float":
            f = float(val)
            if f < 0:
                return f"{key}: must be 0 or a positive number", val
            return None, repr(f) if "." in val else val
        if kind == "toggle":
            low = val.lower()
            if low in ("1", "true", "yes", "on"):
                return None, "1"
            if low in ("0", "false", "no", "off"):
                return None, "0"
            return f"{key}: expected on/off", val
        if kind == "select":
            allowed = [str(o).lower() for o in (entry_options(key) or [])]
            if allowed and val.lower() not in allowed:
                return f"{key}: choose one of {', '.join(allowed)}", val
            return None, val
        if kind == "csv":
            parts = [p.strip() for p in val.split(",") if p.strip()]
            if not parts:
                return None, ""
            for p in parts:
                if float(p) < 0:
                    return f"{key}: budget values must be 0 or positive", val
            return None, ",".join(parts)
        return None, val
    except (TypeError, ValueError):
        return f"{key}: not a valid {kind} value", val


def entry_options(key: str) -> list[str]:
    for entry in CATALOG:
        if entry["key"] == key:
            return [str(o) for o in (entry.get("options") or [])]
    return []


def save(updates: dict[str, Any] | None, *, note: str = "") -> dict[str, Any]:
    """Validate + persist user overrides, then apply them live to env/runtime."""
    if not updates:
        return {"ok": True, "saved": [], "errors": []}
    by_key = {str(e["key"]): e for e in CATALOG}
    errors: list[str] = []
    cleaned: dict[str, str] = {}
    for raw_key, raw_val in updates.items():
        key = str(raw_key or "").strip()
        if key in _EXE_CAP_KEYS:
            continue
        entry = by_key.get(key)
        if entry is None:
            errors.append(f"{key}: not a farm setting")
            continue
        err, val = _coerce(str(entry["kind"]), key, raw_val)
        if err:
            errors.append(err)
            continue
        cleaned[key] = val
    if errors:
        return {"ok": False, "saved": [], "errors": errors}
    with _LOCK:
        data = load_saved()
        for cap_key in _EXE_CAP_KEYS:
            data.pop(cap_key, None)
        data.update(cleaned)
        if note:
            data["_note"] = str(note)[:200]
            data["_updated"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        _write_saved(data)
        disk = load_saved()
        missing = [k for k, v in cleaned.items() if disk.get(k) != v]
        if missing:
            return {
                "ok": False,
                "saved": [],
                "errors": ["Farm settings were not saved. Disk copy does not match."],
            }
        _apply_to_env(cleaned)
    return {"ok": True, "saved": sorted(cleaned), "errors": []}


def reset(step: str | None = None, keys: list[str] | None = None) -> dict[str, Any]:
    """Drop saved overrides for a step (or specific keys) so the farm decides again."""
    keys = [str(k) for k in (keys or [])]
    if step:
        keys = [str(e["key"]) for e in catalog_for_step(step)]
    if not keys:
        return {"ok": True, "reset": []}
    with _LOCK:
        data = load_saved()
        removed = [k for k in keys if k in data]
        for k in removed:
            data.pop(k, None)
        _write_saved(data)
        disk = load_saved()
        still = [k for k in removed if k in disk]
        if still:
            return {
                "ok": False,
                "reset": [],
                "errors": ["Reset was not saved. Disk copy still has those settings."],
            }
        for k in removed:
            os.environ.pop(k, None)
    return {"ok": True, "reset": removed}


def _apply_to_env(updates: dict[str, str]) -> None:
    for key, val in updates.items():
        os.environ[key] = val
    try:
        from automation.pharmflow_farm_config import merge_runtime

        merge_runtime(dict(updates), note="wizard_farm_settings")
    except Exception:
        pass


def apply_saved_to_env() -> int:
    """Set saved overrides into os.environ (called by farm_control.start_farm).

    Runs after profile defaults are applied so user tweaks win, and before the
    unison stack spawns so every lane inherits them as env. Phone-count and
    rate-cap keys are stripped from the file and are not applied. A matching
    process value is cleared so an old save cannot ride into the child.
    """
    saved = load_saved()
    caps = {k: saved.pop(k) for k in list(saved) if k in _EXE_CAP_KEYS}
    if caps:
        stored = load_saved()
        for key, old in caps.items():
            stored.pop(key, None)
            if key not in _CAP_KEYS_LEAVE_ENV and os.environ.get(key) == old:
                os.environ.pop(key, None)
        _write_saved(stored)
    if not saved:
        return 0
    # Never let a sticky dash toggle skip per-seq isolation on the money path.
    saved.pop("PHARMFLOW_SKIP_SEQUENCE_ISOLATION", None)
    _apply_to_env(saved)
    os.environ["PHARMFLOW_SKIP_SEQUENCE_ISOLATION"] = "0"
    os.environ.setdefault("PHARMFLOW_ALLOW_SEQUENCE_RUNS", "1")
    return len(saved)


def catalog_payload() -> dict[str, Any]:
    vals = effective_values()
    return {
        "ok": True,
        "catalog": CATALOG,
        "values": vals,
        "saved_keys": sorted(load_saved()),
        "steps": steps(),
        "step_titles": STEP_TITLES,
    }
