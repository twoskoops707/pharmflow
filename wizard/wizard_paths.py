"""Path management for PharmFlow wizard — bundled resources, sys.path, and MuMu detection."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# wizard_paths is imported from wizard/ before automation/ is on sys.path.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from automation.config import REQUIRED_SEQUENCE_VERSION  # noqa: E402

# Windows install root
PHARMFLOW_WINDOWS_ROOT = Path(r"C:\PharmFlow")

MUMU_SEARCH_PATHS: list[Path] = [
    Path(p)
    for p in (
        os.environ.get("PHARMFLOW_MUMU_ROOT", "").strip(),
        r"C:\Program Files\Netease\MuMuPlayer",
        r"C:\Program Files\Netease\MuMuPlayerGlobal",
        r"C:\Program Files (x86)\Netease\MuMuPlayer",
        str(Path(os.environ.get("LOCALAPPDATA", "").strip() or "") / "MuMuPlayer")
        if (os.environ.get("LOCALAPPDATA") or "").strip()
        else "",
        # ARM last — never prefer it on Intel/AMD x64 transfer PCs.
        r"C:\Program Files\Netease\MuMuPlayerARM",
    )
    if p and p not in (".", "")
]


def is_frozen() -> bool:
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def bundle_root() -> Path:
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def ensure_sys_path() -> None:
    """Add project roots to sys.path for exe and dev mode."""
    roots = [bundle_root(), bundle_root() / "wizard", bundle_root() / "automation"]
    for r in roots:
        s = str(r)
        if s not in sys.path:
            sys.path.insert(0, s)


def app_data_root() -> Path:
    """Writable data dir — C:\\PharmFlow on Windows, else project data/."""
    if os.name == "nt":
        root = Path(os.environ.get("PHARMFLOW_ROOT", str(PHARMFLOW_WINDOWS_ROOT)))
    elif is_frozen():
        root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "PharmFlow"
    else:
        root = bundle_root() / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root


def bundled_dir() -> Path:
    """C:\\PharmFlow\\bundled — ADB, ChromePublic.apk, etc."""
    d = app_data_root() / "bundled"
    d.mkdir(parents=True, exist_ok=True)
    return d


def automation_dir() -> Path:
    """Runtime automation folder (created after setup GO)."""
    d = app_data_root() / "automation"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_file() -> Path:
    return app_data_root() / "pharmflow_config.json"


def desktop_prefs_file() -> Path:
    """Tor slot order follows desktop_prefs.json, not alphabetical IP."""
    return app_data_root() / "desktop_prefs.json"


def bundled_adb_path() -> Path:
    cfg = load_config()
    manual = cfg.get("adb_path")
    if manual:
        p = Path(manual)
        if p.is_file():
            return p
    candidates = [
        bundled_dir() / "adb.exe",
        bundle_root() / "bundled_adb" / "adb.exe",
        app_data_root() / "adb" / "adb.exe",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return candidates[0]


def chrome_apk_path() -> Path:
    return bundled_dir() / "ChromePublic.apk"


def tor_binary_path() -> Path:
    cfg = load_config()
    manual = cfg.get("tor_path")
    if manual:
        p = Path(manual)
        if p.is_file():
            return p
    candidates = [
        bundled_dir() / "tor.exe",
        bundle_root() / "tor" / "tor.exe",
        app_data_root() / "tor" / "tor.exe",
        Path(os.environ.get("PHARMFLOW_TOR_PATH", "")),
    ]
    for p in candidates:
        if p and p.is_file():
            return p
    return candidates[0]


def validate_mumu_root(path: Path) -> bool:
    """Return True when path looks like a MuMu install root."""
    return _validate_mumu_root(path)


def detect_mumu_root() -> Path | None:
    cfg = load_config()
    saved = cfg.get("mumu_root")
    if saved:
        p = Path(saved)
        if _validate_mumu_root(p):
            return p
    for candidate in MUMU_SEARCH_PATHS:
        if candidate and _validate_mumu_root(candidate):
            logger.info("Detected MuMu at %s", candidate)
            return candidate
    for pf in (Path(r"C:\Program Files"), Path(r"C:\Program Files (x86)")):
        if not pf.is_dir():
            continue
        for child in pf.iterdir():
            if "mumu" in child.name.lower() and _validate_mumu_root(child):
                return child
    return None


def _validate_mumu_root(path: Path) -> bool:
    if not path.is_dir():
        return False
    # Classic MuMu 12 / Global
    if (path / "shell" / "MuMuManager.exe").is_file():
        return True
    if (path / "nx_main" / "MuMuNxMain.exe").is_file():
        return True
    # MuMu Player ARM (Hyper-V / nemux) — vms/ is a directory, not a file
    if (path / "vms").is_dir() and (
        (path / "manager" / "nemux-shell-winui.Manager.exe").is_file()
        or (path / "shell" / "nemux-shell-winui.exe").is_file()
        or (path / "shell" / "adb.exe").is_file()
    ):
        return True
    return False


def mumu_manager_exe(mumu_root: Path | None = None) -> Path | None:
    root = mumu_root or detect_mumu_root()
    if not root:
        return None
    root = Path(root)
    for rel in (
        "shell/MuMuManager.exe",
        "nx_main/MuMuManager.exe",  # MuMu 12+/Global x64 (no classic shell/ layout)
        "MuMuManager.exe",
        "manager/nemux-shell-winui.Manager.exe",
    ):
        p = root / rel
        if p.is_file():
            return p
    return None


def mumu_vms_dir(mumu_root: Path | None = None) -> Path | None:
    root = mumu_root or detect_mumu_root()
    if not root:
        return None
    vms = Path(root) / "vms"
    return vms if vms.is_dir() else None


def load_config() -> dict[str, Any]:
    path = config_file()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load config: %s", exc)
        return {}


def save_config(data: dict[str, Any]) -> None:
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_config()
    existing.update(data)
    path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    logger.info("Saved config to %s", path)


def save_desktop_prefs(phone_order: list[str]) -> None:
    prefs: dict[str, Any] = {
        "phone_order": phone_order,
        "tor_slot_order": phone_order,
        "browse_proxy_mode": "scramble",
        "dabflow_mantis_patch": True,
        "mask_emulator_fingerprint": False,
        "note": "Scramble: direct internet + browser UA scramble + Mantis CDP patch for ads.",
        # Farm cadence defaults (UI + scripts/run_farm_354.py via env). Does not auto-start farm.
        "farm": {
            "paths": "1,2,3",
            "gap_min_s": 30.0,
            "gap_max_s": 45.0,
            "path3_per_hour": 2,
            "allow_ads": True,
            "hours": 6.0,
        },
    }
    path = desktop_prefs_file()
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                # Preserve operator overrides; only force phone/tor order from this call.
                merged = {**prefs, **existing}
                merged["phone_order"] = phone_order
                merged["tor_slot_order"] = phone_order
                if isinstance(existing.get("farm"), dict):
                    merged["farm"] = {**prefs["farm"], **existing["farm"]}
                else:
                    merged["farm"] = prefs["farm"]
                prefs = merged
        except (json.JSONDecodeError, OSError):
            pass
    path.write_text(json.dumps(prefs, indent=2) + "\n", encoding="utf-8")


def seed_default_groups(phone_names: list[str]) -> None:
    """Create groups.json on first setup if missing."""
    groups_path = app_data_root() / "groups.json"
    if groups_path.is_file():
        return
    payload = {
        "default": {
            "phones": phone_names,
            "sequence": "",
            "schedule_cron": "0 */6 * * *",
            "tor_enabled": True,
            "metadata": {"seeded_by": "first_run_setup"},
        }
    }
    groups_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    logger.info("Seeded default group at %s", groups_path)


def needs_setup() -> bool:
    """True when first-run integrated setup should run."""
    cfg = load_config()
    if cfg.get("setup_complete"):
        return False
    if not cfg.get("phones"):
        return True
    if not desktop_prefs_file().is_file():
        return True
    if not detect_mumu_root():
        return True
    return not bundled_adb_path().is_file()


def sequences_dir() -> Path:
    runtime = automation_dir() / "recordings" / "sequences"
    if runtime.is_dir() and any(runtime.rglob("*.json")):
        return runtime
    dev = bundle_root() / "automation" / "recordings" / "sequences"
    dev.mkdir(parents=True, exist_ok=True)
    return dev


def logs_dir() -> Path:
    d = app_data_root() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


# Ensure import paths on module load
ensure_sys_path()


# ==== merged from pharmflow wizard_paths.py (frozen EXE install-root/asset helpers) ====

def has_automation_dashboard(root: Path) -> bool:
    try:
        return (root / "automation" / "dashboard.py").is_file()
    except OSError:
        return False


def meipass_dir() -> Path | None:
    """PyInstaller one-file extraction dir, or ``None`` when not frozen / not set."""
    m = getattr(sys, "_MEIPASS", None)
    return Path(m) if m else None


def path_is_meipass(p: Path) -> bool:
    """True if ``p`` resolves to ``sys._MEIPASS`` (bundle extract — not the user's data tree)."""
    m = meipass_dir()
    if m is None:
        return False
    try:
        return p.resolve() == m.resolve()
    except OSError:
        return str(p) == str(m)


def first_existing_subdir(roots: list[Path], *parts: str) -> Path | None:
    """First ``root / parts`` that exists as a directory (for sequences / recordings pickers)."""
    for root in roots:
        try:
            candidate = root.joinpath(*parts)
        except (OSError, TypeError):
            continue
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            continue
    return None


def frozen_pharmflow_tree_candidate_dirs() -> list[Path]:
    """Dirs to probe for ``automation/dashboard.py`` when running a PyInstaller one-file exe."""
    exe_dir = Path(sys.executable).resolve().parent
    out: list[Path] = [exe_dir]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        out.append(Path(meipass))
    home = Path.home()
    out.extend(
        [
            home / "PharmFlow",
            home / "PharmFlow" / "pharmflow-clone",
            home / "source" / "repos" / "pharmflow-clone",
            home / "source" / "repos" / "pharmflow",
        ]
    )
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        try:
            key = str(p.resolve()).lower()
        except OSError:
            key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def pharmflow_search_roots_ordered(preferred: Path | str | None = None) -> list[Path]:
    """Distinct roots to probe for ``automation/`` (dialogs, sequence-path fallbacks).

    Order: optional ``preferred`` (e.g. ``state['pharmflow_dir']``), then
    :func:`pharmflow_install_root`, then (PyInstaller one-file only) other entries from
    :func:`frozen_pharmflow_tree_candidate_dirs` that contain ``automation/dashboard.py``.
    This mirrors install-root resolution for the primary tree while still listing other
    valid clone locations for ``File`` dialogs.
    """
    roots: list[Path] = []
    seen: set[str] = set()
    if preferred is not None:
        d = str(preferred).strip()
        if d:
            try:
                p = Path(d).expanduser().resolve()
                k = str(p).lower()
                if k not in seen:
                    seen.add(k)
                    roots.append(p)
            except Exception:
                pass
    try:
        p2 = pharmflow_install_root().resolve()
    except Exception:
        p2 = pharmflow_install_root()
    k2 = str(p2).lower()
    if k2 not in seen:
        seen.add(k2)
        roots.append(p2)
    if getattr(sys, "frozen", False):
        for cand in frozen_pharmflow_tree_candidate_dirs():
            try:
                r = cand.expanduser().resolve()
            except Exception:
                continue
            if path_is_meipass(r):
                continue
            if not has_automation_dashboard(r):
                continue
            key = str(r).lower()
            if key in seen:
                continue
            seen.add(key)
            roots.append(r)
    return roots


def pharmflow_install_root() -> Path:
    """
    Root directory that contains ``automation/dashboard.py`` (checkout or install tree).

    Order: ``PHARMFLOW_HOME`` if valid, then (when frozen) exe dir, bundle dir, and common
    Windows clone paths such as ``%USERPROFILE%\\PharmFlow`` and nested ``pharmflow-clone``,
    then :func:`pharmflow_default_install_root` (folder next to the exe, or repo root in dev).
    """
    env = (os.environ.get("PHARMFLOW_HOME") or "").strip()
    if env:
        try:
            p = Path(env).expanduser().resolve()
        except OSError:
            p = Path(env).expanduser()
        if has_automation_dashboard(p):
            return p

    if getattr(sys, "frozen", False):
        for cand in frozen_pharmflow_tree_candidate_dirs():
            try:
                r = cand.expanduser().resolve()
            except OSError:
                continue
            if path_is_meipass(r):
                # Bundled extract may contain automation/ for imports — never treat as install/data root.
                continue
            if has_automation_dashboard(r):
                return r

    return pharmflow_default_install_root()


def wizard_module_dir() -> Path:
    """
    Directory that matches dev ``wizard/`` (icons, optional ``bundled/``).

    PyInstaller may place code flat under ``_MEIPASS`` or under ``_MEIPASS/wizard/``;
    this returns the path that actually contains those trees.
    """
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", "."))
        nested = root / "wizard"
        if nested.is_dir():
            return nested
        return root
    return Path(__file__).resolve().parent


def wizard_assets_dir() -> Path:
    """``assets/`` for PNG icons (``--add-data "assets;assets"`` in onefile)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        root = Path(sys._MEIPASS)
        for bundled in (root / "assets", root / "wizard" / "assets"):
            if bundled.is_dir():
                return bundled
    return wizard_module_dir() / "assets"


def pharmflow_default_install_root() -> Path:
    """
    When frozen, the folder containing the ``.exe`` (portable / “next to the binary” tree).

    This must not use ``__file__``-relative parents. Not the same as :func:`wizard_module_dir`.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def automation_on_sys_path() -> Path:
    """Ensure ``automation/`` is on ``sys.path`` for lazy imports (PyInstaller or dev checkout)."""
    candidates: list[Path] = []
    m = meipass_dir()
    if m is not None:
        candidates.append(m / "automation")
    try:
        candidates.append(pharmflow_install_root() / "automation")
    except Exception:
        pass
    candidates.append(pharmflow_default_install_root() / "automation")
    candidates.append(Path.home() / "PharmFlow" / "automation")
    if not getattr(sys, "frozen", False):
        candidates.append(wizard_module_dir().parent / "automation")

    seen: set[str] = set()
    chosen: Path | None = None
    for auto in candidates:
        try:
            key = str(auto.resolve()).lower()
        except OSError:
            key = str(auto).lower()
        if key in seen:
            continue
        seen.add(key)
        if auto.is_dir():
            chosen = auto
            break
    if chosen is None:
        chosen = pharmflow_default_install_root() / "automation"
    ap = str(chosen)
    if ap not in sys.path:
        sys.path.insert(0, ap)
    return chosen


def is_nested_recordings_path(path: Path) -> bool:
    """True for the mistaken ``recordings/automation/recordings`` copy."""
    return "recordings/automation/recordings" in str(path).replace("\\", "/").lower()


def default_sequence_path() -> Path:
    """Operator default sequence, beside the live groups file.

    Must not live inside ``groups_config.json``. Dashboard and phone-setup
    writers replace that file with a groups-only payload, which drops any
    extra key. The Sequence page then reloads the first phone's steps.
    """
    return groups_config_path().parent / "default_sequence.json"


def groups_config_path() -> Path:
    """Live groups file the frozen EXE must read.

    Prefer ``C:\\PharmFlow\\automation\\recordings\\groups_config.json``.
    Never a nested ``recordings/automation/recordings`` copy, and never a
    path built by appending ``automation/recordings`` onto a recordings dir.
    """
    preferred = app_data_root() / "automation" / "recordings" / "groups_config.json"
    windows = Path(r"C:\PharmFlow\automation\recordings\groups_config.json")
    for cand in (preferred, windows):
        if cand.is_file() and not is_nested_recordings_path(cand):
            return cand
    for root in _groups_search_roots():
        cand = _groups_file_for_root(root)
        if cand is None or is_nested_recordings_path(cand):
            continue
        if cand.is_file():
            return cand
    if not is_nested_recordings_path(preferred):
        return preferred
    return windows


def _groups_search_roots() -> list[Path]:
    roots: list[Path] = []
    env = (os.environ.get("PHARMFLOW_HOME") or os.environ.get("PHARMFLOW_ROOT") or "").strip()
    if env:
        roots.append(Path(env).expanduser())
    try:
        roots.append(pharmflow_install_root())
    except Exception:
        pass
    roots.append(pharmflow_default_install_root())
    roots.append(Path.home() / "PharmFlow")
    return roots


def _groups_file_for_root(root: Path) -> Path | None:
    """Join groups_config.json without nesting recordings under recordings."""
    try:
        root = root.expanduser()
    except OSError:
        return None
    name = root.name.lower()
    if name == "recordings":
        return root / "groups_config.json"
    if name == "automation":
        return root / "recordings" / "groups_config.json"
    return root / "automation" / "recordings" / "groups_config.json"


def playlist_sequence_roots() -> list[Path]:
    """Dirs that hold playlist JSON referenced from groups_config.

    Playlist refs like ``900x1600/no-ad/...json`` live under
    ``C:\\PharmFlow\\sequences``, not only under the v3 recordings tree.
    """
    roots: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        if is_nested_recordings_path(path):
            return
        try:
            key = str(path.resolve()).lower()
        except OSError:
            key = str(path).lower()
        if key in seen:
            return
        seen.add(key)
        roots.append(path)

    add(app_data_root() / "sequences")
    add(Path(r"C:\PharmFlow\sequences"))
    raw = (os.environ.get("PHARMFLOW_SEQUENCES_DIR") or "").strip()
    if raw:
        add(Path(raw).expanduser())
    add(Path.home() / "PharmFlow" / "sequences")
    try:
        add(sequences_dir())
    except Exception:
        pass
    return roots


def sequence_version_error(path: Path) -> str | None:
    """Same version gate ``run_farm_354._preflight`` uses. None means the file passes it."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"unreadable: {exc}"
    if not isinstance(data, dict):
        return "unreadable: not an object"
    try:
        version = int(data.get("sequence_version") or 0)
    except (TypeError, ValueError):
        version = 0
    if version < REQUIRED_SEQUENCE_VERSION:
        return "bad sequence_version"
    return None


def _direct_playlist_file(rel: str) -> Path | None:
    for root in playlist_sequence_roots():
        cand = root / rel
        if is_nested_recordings_path(cand):
            continue
        try:
            if cand.is_file():
                return cand
        except OSError:
            continue
    return None


def v3_pool_root() -> Path:
    """Existing v3 sequence tree (``recordings/sequences``), never a nested copy."""
    runtime = sequences_dir()
    if (runtime / "base").is_dir() and not is_nested_recordings_path(runtime):
        return runtime
    live = Path(r"C:\PharmFlow\automation\recordings\sequences")
    if (live / "base").is_dir():
        return live
    return runtime


_PLAYLIST_MATERIALS = {
    "mat-quartz": "quartz",
    "mat-titanium": "titanium",
    "mat-ceramic": "ceramic",
}
_PLAYLIST_CONCENTRATES = {
    "conc-live-resin": "live_resin",
    "conc-shatter": "shatter",
    "conc-diamonds": "diamonds",
    "conc-budder": "budder",
    "conc-rosin": "rosin",
    "conc-wax": "wax",
}
_PLAYLIST_HEATS = {
    "heat-butane": "butane",
    "heat-propane": "propane",
}


def _playlist_kind(rel: str) -> str:
    text = rel.replace("\\", "/").lower()
    if "/no-ad/" in text or "__no_ads__" in text or "__no-ad__" in text:
        return "no-ad"
    if "/ad/" in text or "__ad__" in text:
        return "ad"
    return "no-ad"


def _token(text: str, table: dict[str, str]) -> str:
    for raw, name in table.items():
        if raw in text:
            return name
    return ""


def playlist_v3_candidates(ref: str) -> list[Path]:
    """Existing v3 pool files for a groups playlist ref. No stubs."""
    rel = str(ref or "").strip().replace("\\", "/").lstrip("/").lower()
    kind = _playlist_kind(rel)
    mat = _token(rel, _PLAYLIST_MATERIALS)
    conc = _token(rel, _PLAYLIST_CONCENTRATES)
    heat = _token(rel, _PLAYLIST_HEATS)
    if not (mat and conc and heat):
        # Demo refs have no combo. Stable pool files that already exist.
        if kind == "ad":
            mat, conc, heat = "ceramic", "shatter", "butane"
        else:
            mat, conc, heat = "quartz", "shatter", "butane"
    folder = v3_pool_root() / "base" / mat
    if kind == "ad":
        names = [
            f"{mat}_{conc}_{heat}_p3a_homead0_ad.json",
            f"{mat}_{conc}_{heat}_p3a_homead1_ad.json",
        ]
        pattern = f"{mat}_{conc}_{heat}_*_ad.json"
    else:
        names = [
            f"{mat}_{conc}_{heat}_p1a_{browser}_complete.json"
            for browser in ("brave", "chromium", "firefox", "duckduckgo")
        ]
        pattern = f"{mat}_{conc}_{heat}_*_complete.json"
    found: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        if is_nested_recordings_path(path):
            return
        try:
            if not path.is_file():
                return
            key = str(path.resolve()).lower()
        except OSError:
            return
        if key in seen:
            return
        seen.add(key)
        found.append(path)

    for name in names:
        add(folder / name)
    if not found and folder.is_dir():
        for path in sorted(folder.glob(pattern)):
            add(path)
    return found


def resolve_playlist_ref(
    ref: str,
    accept: Callable[[Path], bool] | None = None,
) -> Path | None:
    """Resolve a playlist ref to a file the farm version gate accepts.

    A direct hit is used only when it already passes the v3 version check.
    Pre-v3 groups refs fall through to the existing v3 pool. Never a stub.
    """
    rel = str(ref or "").strip().replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        return None
    gate = accept or (lambda path: sequence_version_error(path) is None)
    direct = _direct_playlist_file(rel)
    if direct is not None and gate(direct):
        return direct
    for cand in playlist_v3_candidates(rel):
        if gate(cand):
            return cand
    return None


def phone_entry_steps(ent: dict[str, Any], serial: str) -> list[Any]:
    """Steps for one phone. Empty serial is not a phone. Playlist files fill empty steps."""
    if not str(serial or "").strip() or not isinstance(ent, dict):
        return []
    inline = ent.get("steps")
    if isinstance(inline, list) and inline:
        return list(inline)
    refs: list[str] = []
    for key in ("sequence_playlist", "sequence_playlist_secondary"):
        raw = ent.get(key)
        if not isinstance(raw, list):
            continue
        refs.extend(str(item).strip() for item in raw if str(item).strip())
    loaded: list[Any] = []
    mode = str(ent.get("sequence_playlist_mode") or "ordered").strip().lower()
    for ref in refs:
        path = resolve_playlist_ref(ref)
        if path is None:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue
        file_steps = data.get("steps") if isinstance(data, dict) else None
        if not isinstance(file_steps, list) or not file_steps:
            continue
        loaded.extend(file_steps)
        if mode != "series":
            break
    return loaded


def _slot_sort_key(serial: str) -> tuple[int, int, str]:
    """Farm-slot order for MuMu guest serials (``10.0.2.N:5555``)."""
    text = str(serial or "").strip()
    if text.startswith("10.0.2.") and ":" in text:
        octet = text.split(":", 1)[0].rsplit(".", 1)[-1]
        try:
            return (0, int(octet), text)
        except ValueError:
            pass
    if text.startswith("emulator-"):
        try:
            return (1, int(text.split("-", 1)[1]), text)
        except ValueError:
            pass
    return (2, 0, text)


def bind_live_phone_entries(
    groups: list[Any],
    live_serials: list[str],
) -> list[tuple[str, dict[str, Any], str]]:
    """Pair live ADB serials to configured playlists.

    Exact serial match wins. If guest IPs churned, pair by farm-slot order.
    Empty serials are skipped. An empty ADB list returns nothing — no invented phones.
    """
    live: list[str] = []
    seen: set[str] = set()
    for raw in live_serials:
        serial = str(raw or "").strip()
        if not serial or serial in seen:
            continue
        seen.add(serial)
        live.append(serial)
    if not live:
        return []
    configured = iter_group_phone_entries(groups)
    by_serial = {serial: ent for serial, ent in configured}
    if all(serial in by_serial for serial in live):
        return [(serial, by_serial[serial], serial) for serial in live]
    live_sorted = sorted(live, key=_slot_sort_key)
    cfg_sorted = sorted(configured, key=lambda item: _slot_sort_key(item[0]))
    n = min(len(live_sorted), len(cfg_sorted))
    return [(live_sorted[i], cfg_sorted[i][1], cfg_sorted[i][0]) for i in range(n)]


def iter_group_phone_entries(groups: list[Any]) -> list[tuple[str, dict[str, Any]]]:
    """Non-empty serials from ``group['phones']``. First group wins. No invented phones."""
    out: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            continue
        phones = group.get("phones")
        if not isinstance(phones, dict):
            continue
        for raw, ent in phones.items():
            serial = str(raw or "").strip()
            if not serial or not isinstance(ent, dict) or serial in seen:
                continue
            seen.add(serial)
            out.append((serial, ent))
    return out


def load_groups_list(path: Path | None = None) -> tuple[Path, list[Any]]:
    """Read the groups list from the live groups file. Empty list if unreadable."""
    cfg = path or groups_config_path()
    if is_nested_recordings_path(cfg) or not cfg.is_file():
        return cfg, []
    try:
        raw = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError, TypeError, ValueError):
        return cfg, []
    groups = raw.get("groups") if isinstance(raw, dict) else None
    if not isinstance(groups, list):
        return cfg, []
    return cfg, groups


def automation_data_dir() -> Path:
    """Writable ``automation/`` tree (``recordings/``, ``tor/``) — prefer install over bundle."""
    candidates: list[Path] = []
    env = (os.environ.get("PHARMFLOW_HOME") or "").strip()
    if env:
        candidates.append(Path(env).expanduser() / "automation")
    try:
        candidates.append(pharmflow_install_root() / "automation")
    except Exception:
        pass
    candidates.append(pharmflow_default_install_root() / "automation")
    candidates.append(Path.home() / "PharmFlow" / "automation")
    for auto in candidates:
        try:
            if (auto / "dashboard.py").is_file() or (auto / "recordings").is_dir():
                return auto
        except OSError:
            continue
    auto = pharmflow_default_install_root() / "automation"
    try:
        (auto / "recordings").mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    m = meipass_dir()
    if m is not None and (m / "automation").is_dir():
        return m / "automation"
    return auto
