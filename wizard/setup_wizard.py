"""
PharmFlow — Windows onboarding for virtual phones + browser dashboard (`wizard/setup_wizard.py`).

**Primary entry (standalone wizard, no unified desktop):** from repo root run
``py -3 wizard/setup_wizard.py`` — or from ``wizard/``: ``py -3 setup_wizard.py``.
Optional unified shell: ``py -3 wizard/pharmflow_desktop.py``, or set ``PHARMFLOW_USE_DESKTOP=1``
when executing this file to launch that shell instead.

Happy path: Start → install tools (Java/Python/PharmFlow + quick verify) → Android or MuMu →
create/connect phones → automation & groups → launch dashboard (browser-only: Chrome → getdabflow.app).

When you close the wizard (X or File → Exit), PharmFlow tries to fix each phone's internet so
browsers are not stuck. Use **Launch → Fix the phone's internet** anytime without closing.
Advanced: ``PHARMFLOW_SKIP_EXIT_PROXY_CLEAR=1`` skips exit cleanup; ``PHARMFLOW_SKIP_TOR_WAIT=1``
is for quick tests on your home network only.

State keys `state[...]` hold install path, `use_mumu`, `sdk_path`, `avds`, `phones`, `groups`,
`default_steps`, and merge install uses `_install_targets_live_tree` + `_merge_zip_tree_safe` / `_merge_dir_into`.

Frozen ship (one .exe for end users), from the ``wizard`` directory — use the unified spec
(``PharmFlow.spec`` → ``PharmFlow.exe``; embeds this wizard via ``pharmflow_desktop.py``):
    pip install pyinstaller pillow
    pyinstaller PharmFlow.spec
"""

import copy
import hashlib
import json
import os
import platform
import shlex
import socket
import traceback
import re
import shutil
import subprocess
import sys
import tarfile
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

# importlib / embedded loaders may not prepend this directory to sys.path.
_wizard_dir = Path(__file__).resolve().parent
_sd = str(_wizard_dir)
if _sd not in sys.path:
    sys.path.insert(0, _sd)

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from wizard_paths import (
    automation_on_sys_path,
    pharmflow_default_install_root,
    pharmflow_install_root,
    pharmflow_search_roots_ordered,
    first_existing_subdir,
    bind_live_phone_entries,
    groups_config_path,
    iter_group_phone_entries,
    meipass_dir,
    persist_groups_config_text,
    phone_entry_steps,
    wizard_module_dir,
)
from wizard_theme import (
    ACCENT,
    ACCENT_DIM,
    ACCENT_GLOW,
    ACCENT_SUBTLE,
    ACCENT_MUTED,
    DIVIDER_ACCENT,
    FOOTER_BG,
    BG,
    BG2,
    BG3,
    BG4,
    BG_LOG_ROW,
    BG_MUMU,
    BORDER,
    BORDER_FOCUS,
    BORDER_STRONG,
    CALLOUT_ACCENT_BAR,
    CALLOUT_BG,
    CALLOUT_BORDER,
    CALLOUT_FG,
    CALLOUT_MUTED,
    CALLOUT_STRIP,
    FB,
    FH,
    FM,
    FS,
    FONT_CAPTION,
    FONT_DISPLAY,
    FONT_EYEBROW,
    FONT_H2,
    FONT_LEAD,
    FONT_PAGE_TITLE,
    FONT_SECTION,
    FONT_UI,
    GREEN,
    GREEN_ACTIVE,
    ON_ACCENT,
    PURPLE,
    PURPLE_ACTIVE,
    RADIUS,
    RED,
    SHELL_RAIL_ACCENT,
    SHELL_SIDEBAR_BG,
    SP,
    STATUS_PENDING,
    STATUS_PROGRESS,
    T1,
    T2,
    T3,
    WARN_FG,
    WARNING,
    _attach_readonly_log_text,
    _style_scrollbars,
    accent_top_strip,
    draw_round_rect,
    load_icon,
    instruction_card,
    mumu_setup_callout,
    operator_callout,
    callout_copy,
    style_danger_button,
    style_ghost_button,
    style_primary_button,
    style_secondary_button,
    themed_vertical_scrollbar,
    bind_responsive_wraplength,
    canvas_embed_set_width,
    canvas_set_scrollregion_from_bbox_all,
    canvas_schedule_scrollregion_refresh,
    scroll_bottom_spacer,
    register_nested_scroll_canvas,
    nested_scroll_canvas_at_widget,
    bind_canvas_mousewheel,
    SCROLL_BOTTOM_PAD,
)
from sequence_humanize import humanize_steps

REPO_URL            = "https://github.com/twoskoops707/pharmflow.git"
IS_WIN              = platform.system() == "Windows"
SETUP_GUIDE_URL     = "https://github.com/twoskoops707/pharmflow/blob/main/docs/PharmFlow_emulator_MuMu_and_sequences.md"
# Raw markdown — more reliable to open in a browser than the GitHub HTML "blob" wrapper page.
SETUP_GUIDE_URL_RAW = (
    "https://raw.githubusercontent.com/twoskoops707/pharmflow/main/docs/PharmFlow_emulator_MuMu_and_sequences.md"
)
PLAY_CONSOLE_URL    = "https://play.google.com/console"
PLAY_TESTING_DOCS_URL = "https://support.google.com/googleplay/android-developer/answer/9845334"


_DASHBOARD_LISTEN_HTTP_PORT_CACHE: int | None = None


def clear_dashboard_listen_port_cache() -> None:
    """Forget resolved dashboard HTTP port (e.g. after stopping the server)."""
    global _DASHBOARD_LISTEN_HTTP_PORT_CACHE
    _DASHBOARD_LISTEN_HTTP_PORT_CACHE = None


def _env_dashboard_http_port() -> int:
    """Configured HTTP port from ``PHARMFLOW_PORT`` — first candidate when probing for the server."""
    try:
        return int(os.environ.get("PHARMFLOW_PORT", "8080"))
    except (TypeError, ValueError):
        return 8080


def _dashboard_port_try_count() -> int:
    raw = (os.environ.get("PHARMFLOW_PORT_TRY_COUNT") or "").strip()
    if not raw:
        return 20
    try:
        return max(1, min(int(raw), 128))
    except (TypeError, ValueError):
        return 20


def _dashboard_candidate_ports() -> list[int]:
    """Ports to try for GET ``/api/config``, matching dashboard bind fallback (see ``dashboard.py``)."""
    base = _env_dashboard_http_port()
    out: list[int] = []
    for i in range(_dashboard_port_try_count()):
        p = base + i
        if p > 65535:
            break
        out.append(p)
    return out


def probe_dashboard_listen_port() -> bool:
    """Resolve the running dashboard's HTTP port via GET ``/api/config`` on loopback candidates.

    If ``PHARMFLOW_PORT`` is busy, the server binds the next free port; this probes
    ``PHARMFLOW_PORT`` … ``PHARMFLOW_PORT + PHARMFLOW_PORT_TRY_COUNT - 1`` (defaults mirror ``dashboard.py``),
    caches ``httpPort`` from JSON, and keeps wizard URLs aligned.

    Returns True when the dashboard responded with a valid config payload.
    """
    global _DASHBOARD_LISTEN_HTTP_PORT_CACHE

    if _DASHBOARD_LISTEN_HTTP_PORT_CACHE is not None:
        chk = f"http://127.0.0.1:{_DASHBOARD_LISTEN_HTTP_PORT_CACHE}/api/config"
        try:
            req = urllib.request.Request(chk, method="GET")
            with urllib.request.urlopen(req, timeout=4.0) as r:
                json.loads(r.read().decode())
            return True
        except Exception:
            clear_dashboard_listen_port_cache()

    def _probe_port(port: int):
        """Return the dashboard's resolved HTTP port, or None if unreachable."""
        url = f"http://127.0.0.1:{port}/api/config"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=1.0) as r:
                raw = r.read().decode()
            data = json.loads(raw)
        except Exception:
            return None
        hp = data.get("httpPort")
        if hp is None:
            hp = data.get("port")
        try:
            hp_i = int(hp) if hp is not None else int(port)
        except (TypeError, ValueError):
            hp_i = int(port)
        if 1 <= hp_i <= 65535:
            return hp_i
        return None

    # Parallel probe under one hard budget: on this box closed-loopback ports
    # blackhole until the per-request timeout, so a sequential scan of 20 ports
    # can take ~25s (freezing the deck's dashboard poll). Probing in parallel
    # bounds the whole scan to roughly one request timeout instead.
    import concurrent.futures as _cf

    candidates = _dashboard_candidate_ports()
    deadline = time.monotonic() + 3.5
    resolved: int | None = None
    with _cf.ThreadPoolExecutor(max_workers=min(8, max(1, len(candidates)))) as ex:
        futs = {ex.submit(_probe_port, p): p for p in candidates}
        for fut in _cf.as_completed(futs, timeout=max(0.1, deadline - time.monotonic())):
            port = futs[fut]
            try:
                hp_i = fut.result()
            except Exception:
                hp_i = None
            if hp_i is not None and resolved is None:
                resolved = hp_i
            if resolved is not None and port >= resolved:
                break
    if resolved is not None:
        _DASHBOARD_LISTEN_HTTP_PORT_CACHE = resolved
        return True
    return False


def dashboard_http_port() -> int:
    """HTTP port for dashboard APIs — ``PHARMFLOW_PORT`` until :func:`probe_dashboard_listen_port` succeeds."""
    if _DASHBOARD_LISTEN_HTTP_PORT_CACHE is not None:
        return _DASHBOARD_LISTEN_HTTP_PORT_CACHE
    return _env_dashboard_http_port()


def dashboard_base_url() -> str:
    """Probe loopback with IPv4 ``127.0.0.1`` (matches default ``PHARMFLOW_BIND``; avoids ``localhost`` → ``::1`` flakes)."""
    return f"http://127.0.0.1:{dashboard_http_port()}"


def _bind_nested_canvas_mousewheel(canvas: tk.Canvas) -> None:
    """Scroll a nested canvas with the wheel; return ``break`` so the wizard shell does not also scroll."""
    register_nested_scroll_canvas(canvas)

    def _wheel_linux(event: tk.Event) -> str:
        if event.num == 4:
            canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            canvas.yview_scroll(1, "units")
        return "break"

    def _wheel_win(event: tk.Event) -> str:
        d = getattr(event, "delta", 0) or 0
        if d == 0:
            return "break"
        scaled = -d / 120.0
        n = int(round(scaled))
        if n == 0:
            n = 1 if scaled > 0 else -1
        canvas.yview_scroll(n, "units")
        return "break"

    canvas.bind("<MouseWheel>", _wheel_win)
    canvas.bind("<Button-4>", _wheel_linux)
    canvas.bind("<Button-5>", _wheel_linux)
    canvas.bind("<Enter>", lambda _e: canvas.focus_set(), add="+")


def _dashboard_ready_timeout_sec() -> float:
    """Seconds to poll GET /api/config after spawning the dashboard (pip/deps often exceed 45s)."""
    raw = (os.environ.get("PHARMFLOW_DASHBOARD_READY_SEC") or "").strip()
    if not raw:
        return 180.0
    try:
        return max(15.0, float(raw))
    except (TypeError, ValueError):
        return 180.0


CMDLINE_TOOLS_URL        = "https://dl.google.com/android/repository/commandlinetools-win-14742923_latest.zip"
CMDLINE_TOOLS_URL_ALT    = "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip"
SDK_DEFAULT_PATH         = os.path.join(os.environ.get("LOCALAPPDATA", "C:\\"), "Android", "Sdk")
JAVA_DOWNLOAD_URL        = "https://aka.ms/download-jdk/microsoft-jdk-21-windows-aarch64.msi"
JAVA_DOWNLOAD_URL_X64    = "https://aka.ms/download-jdk/microsoft-jdk-21-windows-x64.msi"
TOR_FALLBACK_URL  = "https://dist.torproject.org/torbrowser/14.0.9/tor-expert-bundle-windows-x86_64-14.0.9.tar.gz"
PYTHON_URL        = "https://www.python.org/ftp/python/3.13.0/python-3.13.0-arm64.exe"
PYTHON_URL_X64    = "https://www.python.org/ftp/python/3.13.0/python-3.13.0-amd64.exe"
PHARMFLOW_ZIP_URL    = "https://github.com/twoskoops707/pharmflow/archive/refs/heads/main.zip"
PHARMFLOW_DEFAULT    = os.path.join(os.path.expanduser("~"), "PharmFlow")

# MuMu / Netease CLI: newer installs use nemux-shell-winui.Manager.exe; older builds use MuMuManager.exe
MUMU_MANAGER_PRIMARY = "nemux-shell-winui.Manager.exe"
MUMU_MANAGER_LEGACY = "MuMuManager.exe"
MUMU_MANAGER_EXES = (MUMU_MANAGER_PRIMARY, MUMU_MANAGER_LEGACY)


def _pharmflow_install_root() -> Path:
    """Delegate to :func:`wizard_paths.pharmflow_install_root` (PyInstaller + ``PHARMFLOW_HOME`` + common clone paths)."""
    return pharmflow_install_root()


def _automation_on_sys_path() -> Path:
    """Backward-compatible alias — use :func:`wizard_paths.automation_on_sys_path`."""
    return automation_on_sys_path()


def _wizard_runtime_root() -> Path:
    """Repo/install root containing automation/ and wizard/ for this running wizard."""
    return _pharmflow_install_root()


def _pharmflow_tree_root() -> Path:
    """Prefer ``state['pharmflow_dir']`` when set; else bundled/install root."""
    d = (state.get("pharmflow_dir") or "").strip()
    if d:
        try:
            return Path(d).expanduser().resolve()
        except Exception:
            pass
    return _pharmflow_install_root()


def _pharmflow_search_roots_ordered() -> list[Path]:
    """Distinct search roots — delegates to :func:`wizard_paths.pharmflow_search_roots_ordered`."""
    d = (state.get("pharmflow_dir") or "").strip()
    return pharmflow_search_roots_ordered(d if d else None)


def _default_sequences_dir() -> Path:
    """Local sequences folder (``PHARMFLOW_SEQUENCES_DIR`` or ``~/PharmFlow/sequences``)."""
    raw = (os.environ.get("PHARMFLOW_SEQUENCES_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / "PharmFlow" / "sequences").resolve()


def _ensure_sequences_dir() -> Path:
    """Ensure local sequences folder exists."""
    p = _default_sequences_dir()
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return p


def _sync_sequences_to_user_profile(log_write=None) -> None:
    """Copy shipped ``sequences/`` from the install tree into ``~/PharmFlow/sequences``."""
    log = log_write or (lambda _m: None)
    try:
        from wizard_paths import automation_on_sys_path

        automation_on_sys_path()
        from sequences_sync import sync_shipped_sequences

        result = sync_shipped_sequences(log=log)
        if not result.get("ok"):
            missing = result.get("missing_playlists") or []
            if missing:
                log(
                    f"  WARNING: {len(missing)} sequence playlist file(s) missing after sync "
                    "(run Phone Setup GO on PharmFlow Home → Step 1, or copy sequences/ manually)."
                )
    except Exception as exc:
        log(f"  (sequence sync skipped: {exc})")

def _read_json_text_file(path: Path) -> str:
    """Read JSON source with UTF-8 BOM support (Windows Notepad / exports)."""
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeError:
        return path.read_text(encoding="utf-8", errors="replace")


class SequenceJsonLoadError(Exception):
    """User-readable failure loading a sequence JSON file (encoding, JSON shape, or schema)."""


def _load_sequence_document_from_path(path: Path):
    """Parse UTF-8/BOM JSON and validate sequence shape via ``load_sequence_steps_ui``."""
    try:
        text = _read_json_text_file(path)
    except OSError as exc:
        raise SequenceJsonLoadError(f"Could not read file:\n{exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SequenceJsonLoadError(
            f"Invalid JSON ({path.name}): {exc.msg} (line {getattr(exc, 'lineno', '?')}, column {getattr(exc, 'colno', '?')}).\n\n"
            "Save as UTF-8. The root must be a JSON array of step objects, "
            'or an object with a "steps" array (optional "label", "meta").'
        ) from exc
    try:
        automation_on_sys_path()
        from sequence_normalize import load_sequence_steps_ui

        return load_sequence_steps_ui(payload)
    except ImportError as exc:
        raise SequenceJsonLoadError(
            "Sequence tools not available (complete PharmFlow Install step first)."
        ) from exc
    except ValueError as exc:
        raise SequenceJsonLoadError(
            f"Not a valid sequence document: {exc}\n\n"
            "Expected a JSON array of steps, or an object like "
            '{"steps": [...]} with optional "label" / "meta".'
        ) from exc


def _sequences_initial_dir() -> str:
    """Default folder for sequence JSON dialogs — local ``~/PharmFlow/sequences``."""
    try:
        p = _ensure_sequences_dir()
        if p.is_dir():
            return str(p)
    except Exception:
        pass
    return str(_default_sequences_dir())


def _sequences_dir_str() -> str:
    """Backward-compatible alias for :func:`_sequences_initial_dir`."""
    return _sequences_initial_dir()


def _recordings_dir_str() -> str:
    """Return ``automation/recordings`` under a known PharmFlow root (prefer existing dir among roots)."""
    roots = _pharmflow_search_roots_ordered()
    hit = first_existing_subdir(roots, "automation", "recordings")
    if hit is not None:
        return str(hit)
    try:
        p = _pharmflow_tree_root() / "automation" / "recordings"
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        if p.is_dir():
            return str(p)
    except Exception:
        pass
    try:
        for root in roots:
            alt = root / "automation" / "recordings"
            try:
                alt.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            if alt.is_dir():
                return str(alt)
    except Exception:
        pass
    return ""


def _resolve_under_pharmflow(
    *names: str,
    subdirs: tuple[str, ...] | None = None,
    glob_patterns: tuple[str, ...] | None = None,
) -> str:
    """First existing file under ``pharmflow_dir`` / install roots (cheap; shallow names + globs)."""
    roots = _pharmflow_search_roots_ordered()
    subs = subdirs or ()
    globs = glob_patterns or ()
    names_t = tuple(n for n in names if n)
    for root in roots:
        bases: list[Path] = [root]
        for sd in subs:
            try:
                bases.append(root / sd)
            except Exception:
                pass
        for base in bases:
            try:
                if not base.is_dir():
                    continue
            except Exception:
                continue
            for name in names_t:
                try:
                    hit = base / name
                    if hit.is_file():
                        return str(hit.resolve())
                except Exception:
                    pass
            for pattern in globs:
                try:
                    for cand in sorted(base.glob(pattern)):
                        if cand.is_file():
                            return str(cand.resolve())
                except Exception:
                    pass
    return ""


def _rel_to_sequences_root(path: str | Path) -> str:
    """Return a path relative to the local sequences root for folder playlists."""
    root = _default_sequences_dir().resolve()
    p = Path(path).resolve()
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        return p.name


def _normalize_sequence_playlist_items(raw) -> list[str]:
    """Preserve relative paths under ``recordings/sequences/`` (e.g. ``900x1600/ad/foo.json``)."""
    out: list[str] = []
    if not raw:
        return out
    seq_root = _default_sequences_dir()
    for x in raw:
        if not isinstance(x, str):
            continue
        t = x.strip().replace("\\", "/")
        if not t:
            continue
        if ".." in t.split("/"):
            t = os.path.basename(t)
        p = Path(t)
        if p.is_absolute():
            try:
                t = p.resolve().relative_to(seq_root.resolve()).as_posix()
            except ValueError:
                t = p.name
        else:
            t = t.lstrip("/")
        if t and t not in out:
            out.append(t)
    return out


def _normalize_sequence_playlist_shuffle(raw) -> str:
    s = (raw or "none").strip().lower()
    if s in ("none", "set_a", "set_b", "both_sets_separately", "combined"):
        return s
    return "none"


_SEQUENCE_FOLDER_MODES = frozenset({"folder", "folder_random"})


def _normalize_sequence_folder(raw) -> str:
    """Safe relative path under the sequences root (no ``..``)."""
    t = str(raw or "").strip().replace("\\", "/").strip("/")
    if not t or ".." in t.split("/"):
        return ""
    return t


def _sync_sequence_playlist_basenames() -> None:
    """Normalize persisted playlist entries whenever groups are normalized."""
    for g in state.get("groups") or []:
        pmap = g.get("phones") or {}
        for ent in pmap.values():
            if not isinstance(ent, dict):
                continue
            pl = ent.get("sequence_playlist")
            if isinstance(pl, list):
                ent["sequence_playlist"] = _normalize_sequence_playlist_items(pl)
            pl2 = ent.get("sequence_playlist_secondary")
            if isinstance(pl2, list):
                ent["sequence_playlist_secondary"] = _normalize_sequence_playlist_items(pl2)


def _json_file_dialog_fallback_dir() -> str | None:
    """Last-resort folder when no PharmFlow tree paths exist yet (avoids broken Tk initialdir)."""
    try:
        dl = Path.home() / "Downloads"
        if dl.is_dir():
            return str(dl)
        home = Path.home()
        if home.is_dir():
            return str(home)
    except OSError:
        pass
    return None


def _json_file_dialog_initialdir() -> str | None:
    """Prefer sequences, then recordings, for JSON flow pickers."""
    s = _sequences_initial_dir()
    if s:
        return s
    s = _recordings_dir_str()
    if s:
        return s
    return _json_file_dialog_fallback_dir()


def _sdk_path_browse_initialdir(manual_path: str) -> str | None:
    """Initial folder for Android SDK directory picker."""
    s = (manual_path or "").strip()
    if s:
        p = Path(s)
        par = p.parent if p.is_file() else p
        if par.is_dir():
            return str(par)
    d = Path(SDK_DEFAULT_PATH)
    if d.is_dir():
        return str(d)
    return None


def _apk_pick_initialdir() -> str | None:
    """Typical folder for APK side-loads."""
    try:
        dl = Path.home() / "Downloads"
        if dl.is_dir():
            return str(dl)
        home = Path.home()
        if home.is_dir():
            return str(home)
    except Exception:
        pass
    return None


def _browse_file(
    parent,
    var: "tk.StringVar",
    filetypes,
    initialdir_fn,
    title: str = "Choose file",
) -> str | None:
    """Set ``var`` from ``filedialog.askopenfilename`` using ``initialdir_fn()``; return path or ``None``."""
    init = None
    try:
        init = initialdir_fn()
    except Exception:
        pass
    if init == "":
        init = None
    path = filedialog.askopenfilename(
        parent=parent,
        title=title,
        filetypes=filetypes,
        initialdir=init,
    )
    if path:
        var.set(path)
        return path
    return None


def _install_targets_live_tree(install_dir: Path) -> bool:
    """True if we must not delete/replace install_dir wholesale (wizard runs from that tree or below)."""
    try:
        inst = install_dir.resolve()
        rt = _wizard_runtime_root().resolve()
    except OSError:
        return False
    if inst == rt:
        return True
    try:
        return rt.is_relative_to(inst)
    except (ValueError, AttributeError):
        ip, rp = str(inst), str(rt)
        if not ip.endswith(os.sep):
            ip += os.sep
        return rp.lower().startswith(ip.lower())


def _merge_dir_into(src: Path, dst: Path) -> None:
    """Copy src tree into dst; existing files are overwritten. Does not delete dst first."""
    if not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        s, d = item, dst / item.name
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)


def _path_parts_contain_vcs_marker(parts: tuple[str, ...]) -> bool:
    """True if any path part is a VCS dir (case-insensitive on Windows)."""
    for p in parts:
        pl = p.lower()
        if pl == ".git" or pl == ".svn":
            return True
    return False


def _merge_zip_tree_safe(src: Path, dst: Path) -> None:
    """Merge GitHub ZIP extract into dst by walking **src** only.

    Avoids ``shutil.copytree`` merges that can touch nested ``.git`` trees under *dst*
    (WinError 5: Access denied on locked objects/*.git).
    Skips any destination path whose parts contain ``.git`` or ``.svn`` (any case).
    Permission errors on locked files are skipped (best-effort merge).
    """
    if not src.is_dir():
        return
    skip_names = {".git", ".svn", "__pycache__", ".venv", "node_modules"}
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d.lower() not in {x.lower() for x in skip_names}]
        rel = Path(root).relative_to(src)
        for fname in files:
            if fname.endswith(".pyc"):
                continue
            sp = Path(root) / fname
            dp_pre = dst / rel / fname
            # Check un-resolved path first — resolve() can behave oddly with junctions on Windows.
            if _path_parts_contain_vcs_marker(dp_pre.parts):
                continue
            dp = dp_pre
            try:
                dp = dp_pre.resolve()
            except OSError:
                dp = dp_pre
            if _path_parts_contain_vcs_marker(dp.parts):
                continue
            # Belt-and-suspenders: any ".git" segment in normalized path string (WoA / short paths).
            dp_s = str(dp).lower().replace("/", "\\")
            if "\\.git\\" in dp_s or dp_s.endswith("\\.git"):
                continue
            try:
                dp.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(sp, dp)
            except (OSError, PermissionError) as e:
                # Locked .git/objects, ACL, sharing violation — skip file; never abort whole install
                we = getattr(e, "winerror", None)
                en = getattr(e, "errno", None)
                if we in (5, 32) or en in (13, 5, 32, 16):
                    continue
                # Any remaining error while merging into a messy tree — skip (best-effort); never fail ZIP step.
                continue


def _git_repo_roots_for_pull(install_dir: Path) -> list[Path]:
    """Git repo roots under *install_dir* (including nested clones like ``…/pharmflow-clone``).

    Walk is depth-bounded and skips descending into ``.git`` (objects packfiles are locked on Windows).
    """
    roots: list[Path] = []
    seen: set[Path] = set()

    def add(p: Path) -> None:
        try:
            r = p.resolve()
        except OSError:
            return
        if r in seen:
            return
        git_meta = r / ".git"
        try:
            # ``exists()`` is enough (worktrees use a .git *file*); ``is_dir()`` can raise or
            # mis-report when AV locks packfiles or objects under .git (missed repo → ZIP merge → WinError 5).
            if git_meta.exists():
                seen.add(r)
                roots.append(r)
        except OSError:
            pass

    try:
        root = install_dir.resolve()
        if not root.is_dir():
            return roots
        max_depth = 12
        for dirpath, dirnames, _ in os.walk(root):
            cur = Path(dirpath)
            try:
                depth = len(cur.relative_to(root).parts)
            except ValueError:
                continue
            if depth > max_depth:
                dirnames.clear()
                continue
            try:
                gm = cur / ".git"
                if gm.exists():
                    add(cur)
            except OSError:
                pass
            if ".git" in dirnames:
                dirnames[:] = [d for d in dirnames if d != ".git"]
            dirnames[:] = [
                d for d in dirnames if d.lower() not in {"__pycache__", "node_modules", ".venv"}
            ]
    except OSError:
        pass
    return roots


def _install_dir_has_any_git(install_dir: Path) -> bool:
    """True if *install_dir* contains a git working tree (.git file or dir), including nested clones."""
    return len(_git_repo_roots_for_pull(install_dir)) > 0


def _try_git_pull_pharmflow(install_dir: Path, log_fn) -> bool:
    """If a git checkout exists, try ``git pull --ff-only`` so we never overwrite .git via ZIP."""
    for repo in _git_repo_roots_for_pull(install_dir):
        log_fn(f"  Git repo found at {repo} — trying git pull --ff-only…\n")
        ok, out = run_cmd(
            ["git", "-C", str(repo), "pull", "--ff-only"],
            timeout=180,
        )
        if ok and (repo / "automation" / "dashboard.py").exists():
            log_fn("  Updated from GitHub via git pull ✅\n")
            return True
        log_fn(f"  git pull failed or incomplete: {(out or '')[-500:]}\n")
    return False


def _find_pharmflow_dashboard_root(install_dir: Path) -> Path | None:
    """Directory containing ``automation/dashboard.py`` (repo root, ``pharmflow/``, or nested clone)."""
    for base in (install_dir, install_dir / "pharmflow"):
        if (base / "automation" / "dashboard.py").is_file():
            try:
                return base.resolve()
            except OSError:
                pass
    try:
        root = install_dir.resolve()
        if not root.is_dir():
            return None
        max_depth = 5
        for dirpath, dirnames, _ in os.walk(root):
            cur = Path(dirpath)
            try:
                depth = len(cur.relative_to(root).parts)
            except ValueError:
                continue
            if depth > max_depth:
                dirnames.clear()
                continue
            dash = cur / "automation" / "dashboard.py"
            if dash.is_file():
                return cur.resolve()
            dirnames[:] = [
                d
                for d in dirnames
                if d.lower() not in {".git", "__pycache__", "node_modules", ".venv"}
            ]
    except OSError:
        pass
    return None


def _install_dir_empty_or_absent(path: Path) -> bool:
    """True if *path* does not exist or exists as an empty directory (safe target for ``git clone``)."""
    try:
        if not path.exists():
            return True
        return not any(path.iterdir())
    except OSError:
        return False


# ``dashboard.py`` imports these — partial ZIP/git trees show "done" but fail at runtime.
_AUTOMATION_REQUIRED_FILES = (
    "dashboard.py",
    "config.py",
    "tor_manager.py",
    "teach.py",
    "playstore.py",
    "sequence_normalize.py",
    "human_variation.py",
)


def _automation_bundle_missing(root: Path) -> list[str]:
    """Missing ``automation/*.py`` paths (posix-style) relative to repo root."""
    auto = root / "automation"
    if not auto.is_dir():
        return ["automation/"]
    missing: list[str] = []
    for name in _AUTOMATION_REQUIRED_FILES:
        if not (auto / name).is_file():
            missing.append(f"automation/{name}")
    return missing


def _is_mumu_manager_cli_path(path: Path | str) -> bool:
    n = Path(path).name.lower()
    return n in {x.lower() for x in MUMU_MANAGER_EXES}


def _is_mumu_gui_path(path: Path | str) -> bool:
    """True if path looks like the MuMu Player GUI, not the shell CLI manager."""
    n = Path(path).name.lower()
    if _is_mumu_manager_cli_path(path):
        return False
    return n in ("mumuplayer.exe", "mumunxmain.exe")


# MuMu "manager" binaries that are GUI apps (WinUI shell), never CLIs.
# Executing them with any argument opens the MuMu Player manager window —
# on MuMuPlayerARM the user sees this as "PharmFlow opened MuMu at start".
# Discovery and state refreshes must never run them; only legacy shell CLIs
# (MuMuManager.exe under shell\ / nx_main\) or ADB port scans are allowed.
MUMU_GUI_MANAGER_EXES = {
    "nemux-shell-winui.manager.exe",
    "nemux-shell-winui.manager",
}


def _is_gui_only_manager(path: Path | str) -> bool:
    """True when the path is a GUI-only MuMu manager that must never be executed."""
    n = Path(path).name.lower()
    return n in MUMU_GUI_MANAGER_EXES


# Daily scheduler default (per-phone override lives on Groups page).
DEFAULT_HITS_PER_DAY = 720
DEFAULT_SEQUENCE_BASE_W = 900
DEFAULT_SEQUENCE_BASE_H = 1600

STEP_LABELS = {
    "open_url":        "Open a website in the phone default browser",
    "launch_app":      "Open an installed app (Android package name)",
    "tap":             "Tap the screen at a spot",
    "wait":            "Wait N seconds",
    "swipe":           "Swipe up or down",
    "keyevent":        "Press Back / Home / Enter",
    "close_app":       "Close the app",
    "clear_cookies":   "Clear browser cookies",
    "rotate_identity": "Switch internet identity (Tor circuit or session scramble)",
    "type_text":       "Type some text",
}

state = {
    "pharmflow_dir":  "",
    "python_cmd":  "python",
    "python_cmd_argv": ["python"],
    "sdk_path":    "",
    "num_phones":  3,
    "phones":      [],
    "avds":      [],
    "_emu_procs":  [],
    "groups": [{
        "name":           "Group 1",
        "phones":         {},      # {serial: {"steps": [...], "name": "Phone 1"}}
        "stagger_secs":   30,
        "repeat":         1,
        "repeat_forever": False,
        "apk":            "",      # APK filename (in apks/) installed on each phone before run
    }],
    "use_mumu": False,
}


def _cmd_display(cmd: list[str] | tuple[str, ...] | str) -> str:
    if isinstance(cmd, str):
        return cmd
    try:
        return subprocess.list2cmdline(list(cmd))
    except Exception:
        return " ".join(str(x) for x in cmd)


def _split_cmd_string(cmd: str) -> list[str]:
    s = (cmd or "").strip()
    if not s:
        return []
    if s.lower() == "py -3":
        return ["py", "-3"]
    # Absolute/quoted Windows paths with spaces must stay one argv token even when
    # the file is not on disk yet (installer paths, pending installs).
    if " " in s:
        if Path(s).exists() or (len(s) >= 2 and s[1] == ":"):
            return [s]
        try:
            parts = shlex.split(s, posix=not IS_WIN)
            if parts:
                return parts
        except ValueError:
            pass
    return s.split()


def _is_frozen_app_python_candidate(argv: list[str]) -> bool:
    """True when argv[0] is PharmFlow.exe — never treat it as CPython.

    Probing ``[sys.executable, "--version"]`` while frozen re-spawns the EXE
    (and ``-c`` would open another Control Panel). Journey scan hit this on
    every deck open.
    """
    if not argv:
        return False
    try:
        stem = Path(str(argv[0])).stem.lower()
    except (TypeError, ValueError, OSError):
        return False
    if stem == "pharmflow":
        return True
    if getattr(sys, "frozen", False) and Path(str(argv[0])).resolve() == Path(sys.executable).resolve():
        return True
    return False


def _probe_python_cmd(argv: list[str]) -> bool:
    if not argv or _is_frozen_app_python_candidate(argv):
        return False
    try:
        r = subprocess.run(
            argv + ["--version"],
            capture_output=True,
            text=True,
            timeout=6,
            creationflags=_NO_WIN,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return False
    out = (r.stdout or "") + "\n" + (r.stderr or "")
    if "Python was not found" in out:
        return False
    if r.returncode != 0 or "Python 3" not in out:
        return False
    try:
        r2 = subprocess.run(
            argv
            + ["-c", "import sys; assert sys.version_info >= (3, 8); import encodings"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_NO_WIN,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return False
    return r2.returncode == 0


def _resolve_python_cmd(preferred: str | None = None) -> tuple[list[str], str]:
    candidates: list[list[str]] = []
    if preferred:
        pc = _split_cmd_string(preferred)
        if pc:
            candidates.append(pc)
    saved = state.get("python_cmd_argv")
    if isinstance(saved, list) and saved:
        candidates.append([str(x) for x in saved])
    # Never put the frozen Control Panel EXE on the Python candidate list.
    host_exe = [sys.executable]
    if not _is_frozen_app_python_candidate(host_exe):
        candidates.append(host_exe)
    candidates.extend([["py", "-3"], ["python"], ["python3"], ["py"]])
    seen: set[tuple[str, ...]] = set()
    for cand in candidates:
        key = tuple(cand)
        if key in seen:
            continue
        seen.add(key)
        if _is_frozen_app_python_candidate(cand):
            continue
        if _probe_python_cmd(cand):
            disp = _cmd_display(cand)
            state["python_cmd"] = disp
            state["python_cmd_argv"] = list(cand)
            return list(cand), disp
    return ["python"], "python"


def _normalize_step_list(raw_steps) -> list:
    if isinstance(raw_steps, list):
        return _normalize_sequence_steps(list(raw_steps))
    return []


def _coerce_profile_dim(value, fallback: int) -> int:
    try:
        v = int(value)
        return v if v > 0 else fallback
    except (TypeError, ValueError):
        return fallback


def _profile_key(base_w: int, base_h: int) -> str:
    return f"{int(base_w)}x{int(base_h)}"


def _step_baseline_hint(steps: list) -> tuple[int, int] | None:
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        if step.get("type") not in ("tap", "swipe"):
            continue
        bw = step.get("base_w")
        bh = step.get("base_h")
        try:
            ibw = int(bw)
            ibh = int(bh)
        except (TypeError, ValueError):
            continue
        if ibw > 0 and ibh > 0:
            return ibw, ibh
    return None


def _parse_wm_size_quick(raw: str) -> tuple[int, int] | None:
    if not (raw or "").strip():
        return None
    override = None
    physical = None
    line_re = re.compile(
        r"(?P<label>Physical|Override|Display)\s+size:\s*(?P<w>\d+)\s*[xX]\s*(?P<h>\d+)",
        re.IGNORECASE,
    )
    for line in raw.splitlines():
        m = line_re.search(line.strip())
        if not m:
            continue
        w, h = int(m.group("w")), int(m.group("h"))
        if w <= 0 or h <= 0:
            continue
        if m.group("label").lower() == "override":
            override = (w, h)
        else:
            physical = (w, h)
    if override is not None:
        return override
    if physical is not None:
        return physical
    generic = re.compile(r"\b(\d{2,5})\s*[xX]\s*(\d{2,5})\b")
    for line in raw.splitlines():
        m = generic.search(line)
        if not m:
            continue
        w, h = int(m.group(1)), int(m.group(2))
        if w > 0 and h > 0:
            return w, h
    return None


def _apply_default_steps_to_template_phones(log_fn=None) -> int:
    changed = 0
    default_steps = list(state.get("default_steps", []))
    for g in state.get("groups") or []:
        phones = g.get("phones") or {}
        if not isinstance(phones, dict):
            continue
        for serial, pdata in phones.items():
            if not isinstance(pdata, dict):
                continue
            use_template = bool(pdata.get("use_default_template", True))
            if not use_template:
                continue
            prev = _normalize_step_list(pdata.get("steps"))
            if prev != default_steps:
                pdata["steps"] = list(default_steps)
                changed += 1
                if log_fn:
                    log_fn(
                        f"Template sync: {g.get('name', 'Group')} / {serial} "
                        f"{len(prev)} -> {len(default_steps)} steps"
                    )
            else:
                pdata["steps"] = list(default_steps)
    return changed


def _ensure_group_defaults(g: dict) -> None:
    """Ensure metadata keys exist (hand-edited groups_config.json often omits them)."""
    nm = g.get("name")
    if not isinstance(nm, str) or not nm.strip():
        g["name"] = "Group"
    try:
        g["stagger_secs"] = max(0, int(g.get("stagger_secs", 30)))
    except (TypeError, ValueError):
        g["stagger_secs"] = 30
    # Optional explicit phone-start spread (seconds); overrides stagger_secs jitter when both set.
    for key in ("stagger_min", "stagger_max"):
        if key in g and g[key] is not None:
            try:
                g[key] = max(0, int(g[key]))
            except (TypeError, ValueError):
                g.pop(key, None)
    if g.get("human_stagger") is None:
        g["human_stagger"] = True
    try:
        g["repeat"] = max(1, int(g.get("repeat", 1)))
    except (TypeError, ValueError):
        g["repeat"] = 1
    g["repeat_forever"] = bool(g.get("repeat_forever", False))
    g["apk"] = str(g.get("apk") or "").strip() or ""


def _normalize_all_groups():
    """Ensure groups[].phones uses per-phone dicts with steps + hits_per_day."""
    if not state.get("groups"):
        return
    default_steps = state.get("default_steps", [])
    phones_booted = state.get("phones") or []
    kept: list[dict] = []
    for g in state["groups"]:
        if not isinstance(g, dict):
            continue
        phones_field = g.get("phones")
        if isinstance(phones_field, list):
            norm: dict[str, dict] = {}
            phone_template = {
                "steps": list(default_steps),
                "hits_per_day": DEFAULT_HITS_PER_DAY,
                "use_default_template": True,
                "explicit_override": False,
                "sequence_base_w": DEFAULT_SEQUENCE_BASE_W,
                "sequence_base_h": DEFAULT_SEQUENCE_BASE_H,
                "sequence_profile_key": _profile_key(DEFAULT_SEQUENCE_BASE_W, DEFAULT_SEQUENCE_BASE_H),
            }
            for p in phones_field:
                if isinstance(p, str):
                    ser = p.strip()
                    if ser:
                        norm[ser] = dict(phone_template)
                elif isinstance(p, dict):
                    ser = (p.get("serial") or "").strip()
                    if ser:
                        norm[ser] = dict(phone_template)
            g["phones"] = norm
        elif not isinstance(phones_field, dict):
            g["phones"] = {}
        if phones_booted and not g["phones"]:
            for p in phones_booted:
                if not isinstance(p, dict):
                    continue
                ser = (p.get("serial") or "").strip()
                if not ser:
                    continue
                g["phones"][ser] = {
                    "steps": list(default_steps),
                    "hits_per_day": DEFAULT_HITS_PER_DAY,
                    "use_default_template": True,
                    "explicit_override": False,
                    "sequence_base_w": DEFAULT_SEQUENCE_BASE_W,
                    "sequence_base_h": DEFAULT_SEQUENCE_BASE_H,
                    "sequence_profile_key": _profile_key(DEFAULT_SEQUENCE_BASE_W, DEFAULT_SEQUENCE_BASE_H),
                }
        for _serial, pdata in list(g.get("phones", {}).items()):
            if not isinstance(pdata, dict):
                g["phones"][_serial] = {
                    "steps": list(default_steps),
                    "hits_per_day": DEFAULT_HITS_PER_DAY,
                    "use_default_template": True,
                    "explicit_override": False,
                    "sequence_base_w": DEFAULT_SEQUENCE_BASE_W,
                    "sequence_base_h": DEFAULT_SEQUENCE_BASE_H,
                    "sequence_profile_key": _profile_key(DEFAULT_SEQUENCE_BASE_W, DEFAULT_SEQUENCE_BASE_H),
                }
                continue
            if "hits_per_day" not in pdata:
                pdata["hits_per_day"] = DEFAULT_HITS_PER_DAY
            steps_norm = _normalize_step_list(pdata.get("steps"))
            explicit_override_raw = pdata.get("explicit_override", None)
            use_template_raw = pdata.get("use_default_template", None)
            has_playlist = bool(_normalize_sequence_playlist_items(pdata.get("sequence_playlist"))) or bool(
                _normalize_sequence_playlist_items(pdata.get("sequence_playlist_secondary"))
            )
            has_nondefault_steps = steps_norm != list(default_steps)
            inferred_override = has_playlist or has_nondefault_steps
            if use_template_raw is None and explicit_override_raw is None:
                use_template = not inferred_override
            elif use_template_raw is None:
                use_template = not bool(explicit_override_raw)
            else:
                use_template = bool(use_template_raw)
            pdata["use_default_template"] = use_template
            pdata["explicit_override"] = not use_template
            base_w = _coerce_profile_dim(pdata.get("sequence_base_w"), DEFAULT_SEQUENCE_BASE_W)
            base_h = _coerce_profile_dim(pdata.get("sequence_base_h"), DEFAULT_SEQUENCE_BASE_H)
            hinted = _step_baseline_hint(steps_norm)
            if hinted and not ("sequence_base_w" in pdata and "sequence_base_h" in pdata):
                base_w, base_h = hinted
            pdata["sequence_base_w"] = base_w
            pdata["sequence_base_h"] = base_h
            pdata["sequence_profile_key"] = _profile_key(base_w, base_h)
            if use_template:
                pdata["steps"] = list(default_steps)
            else:
                pdata["steps"] = steps_norm
        _ensure_group_defaults(g)
        kept.append(g)
    state["groups"] = kept
    _sync_sequence_playlist_basenames()


def _scheduler_maps_for_serials(serials: list[str], fallback_hits: int):
    """Per-phone hits/steps from groups (first group listing each serial wins)."""
    wanted = [str(s).strip() for s in serials if str(s or "").strip()]
    bound = bind_live_phone_entries(list(state.get("groups") or []), wanted)
    hits_ps: dict[str, int] = {}
    steps_ps: dict[str, list] = {}
    for serial, pdata, _source in bound:
        if serial in hits_ps:
            continue
        try:
            h = int(pdata.get("hits_per_day", DEFAULT_HITS_PER_DAY))
        except (TypeError, ValueError):
            h = DEFAULT_HITS_PER_DAY
        hits_ps[serial] = max(0, h)
        steps_ps[serial] = phone_entry_steps(pdata, serial)
    try:
        fb = max(0, int(fallback_hits))
    except (TypeError, ValueError):
        fb = DEFAULT_HITS_PER_DAY
    hits_out: dict[str, int] = {}
    steps_out: dict[str, list] = {}
    for s in wanted:
        if s in hits_ps:
            hits_out[s] = hits_ps[s]
            steps_out[s] = steps_ps.get(s, [])
        else:
            hits_out[s] = fb
            steps_out[s] = []
    return hits_out, steps_out


def _int_clamped_entry(
    parent: tk.Misc,
    variable: tk.IntVar,
    lo: int,
    hi: int | None,
    *,
    width: int = 6,
    bg: str = BG3,
    font=None,
) -> tk.Entry:
    """Plain numeric entry (no Spinbox arrows) with subtle field styling."""
    font = font or FM
    ent = tk.Entry(
        parent,
        textvariable=variable,
        width=width,
        font=font,
        bg=bg,
        fg=T1,
        relief="flat",
        insertbackground=T1,
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=BORDER_FOCUS,
    )

    def _commit(_event=None):
        try:
            v = int(str(variable.get()).strip())
        except (tk.TclError, ValueError, TypeError):
            v = lo
        v = max(lo, v if hi is None else min(hi, v))
        variable.set(v)

    ent.bind("<FocusOut>", _commit)
    ent.bind("<Return>", _commit)
    return ent


def _open_setup_guide_doc(parent: tk.Misc | None = None) -> None:
    """Open MuMu / sequence / display docs (local tree or bundled _MEIPASS), else the guide in a browser.

    The Groups-step button targets operator-facing **emulator + sequence** notes shipped under
    ``docs/`` (also embedded in ``PharmFlow.exe`` via PyInstaller ``datas``).
    """
    roots: list[Path] = []
    try:
        md = meipass_dir()
        if md is not None and (md / "docs").is_dir():
            roots.append(md)
    except Exception:
        pass
    try:
        d = (state.get("pharmflow_dir") or "").strip()
        if d:
            roots.append(Path(d))
    except Exception:
        pass
    roots.extend(_pharmflow_search_roots_ordered())
    roots.append(_pharmflow_install_root())
    seen_root: set[str] = set()
    uniq_roots: list[Path] = []
    for r in roots:
        try:
            key = str(r.resolve()).lower()
        except OSError:
            key = str(r).lower()
        if key in seen_root:
            continue
        seen_root.add(key)
        uniq_roots.append(r)
    roots = uniq_roots
    doc_names = (
        "PharmFlow_emulator_MuMu_and_sequences.md",
        "PharmFlow_EMULATOR_AND_DISPLAY.md",
        "SEQUENCE_CATALOG.md",
    )
    mb_parent = parent
    if mb_parent is None:
        try:
            w = tk._default_root
            if w is not None:
                mb_parent = w.winfo_toplevel()
        except tk.TclError:
            mb_parent = tk._default_root
    checked: list[str] = []
    open_errors: list[str] = []
    for root in roots:
        for doc_name in doc_names:
            p = (root / "docs" / doc_name).resolve()
            checked.append(str(p))
            if not p.is_file():
                continue
            try:
                if IS_WIN:
                    os.startfile(str(p))
                else:
                    webbrowser.open(p.as_uri())
                return
            except Exception as exc:
                open_errors.append(f"{p}: {type(exc).__name__}: {exc}")
                break
    url_opened = False
    for url in (SETUP_GUIDE_URL_RAW, SETUP_GUIDE_URL):
        try:
            if IS_WIN:
                os.startfile(url)
                url_opened = True
                break
        except OSError as exc:
            open_errors.append(f"startfile {url}: {type(exc).__name__}: {exc}")
        try:
            if webbrowser.open(url, new=1, autoraise=True):
                url_opened = True
                break
        except Exception as exc:
            open_errors.append(f"{url}: {type(exc).__name__}: {exc}")
    if url_opened:
        messagebox.showinfo(
            "Setup guide",
            "Opened the help guide in your browser.\n\n"
            "Tip: you can also read the docs folder that came with PharmFlow.",
            parent=mb_parent,
        )
        return
    detail = ""
    if open_errors:
        detail = "\n\nErrors:\n" + "\n".join(open_errors[:8])
    elif checked:
        detail = "\n\nChecked:\n" + "\n".join(checked[:8])
    messagebox.showerror(
        "Could not open guide",
        "Could not open the local setup guide or any online guide URL."
        + detail,
        parent=mb_parent,
    )


def _try_hydrate_default_steps_from_groups() -> None:
    """If default_steps is empty, seed from the first inline steps list in groups."""
    if state.get("default_steps"):
        return
    for g in state.get("groups") or []:
        phones = g.get("phones") or {}
        if not isinstance(phones, dict):
            continue
        for pdata in phones.values():
            if not isinstance(pdata, dict):
                continue
            steps = _normalize_step_list(pdata.get("steps"))
            if steps:
                state["default_steps"] = list(steps)
                return


def _drop_empty_phone_serials(groups: list) -> None:
    """Drop ``phones['']`` keys. Do not invent serials when ADB is empty."""
    for group in groups:
        if not isinstance(group, dict):
            continue
        phones = group.get("phones")
        if not isinstance(phones, dict):
            continue
        group["phones"] = {
            str(raw).strip(): ent
            for raw, ent in phones.items()
            if str(raw or "").strip() and isinstance(ent, dict)
        }


def _try_load_default_steps() -> bool:
    """Load the operator default sequence. False means the file is absent."""
    from wizard_paths import default_sequence_path

    path = default_sequence_path()
    if not path.is_file():
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError, TypeError, ValueError) as exc:
        print(f"[wizard] Could not load default sequence ({path}): {exc}", file=sys.stderr)
        return False
    steps = raw.get("steps") if isinstance(raw, dict) else raw
    if not isinstance(steps, list):
        return False
    state["default_steps"] = _normalize_step_list(steps)
    return True


def _persist_default_steps() -> str | None:
    """Write the operator default sequence even when groups cannot be written."""
    from wizard_paths import default_sequence_path

    path = default_sequence_path()
    steps = list(state.get("default_steps") or [])
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"steps": steps}, indent=2) + "\n",
            encoding="utf-8",
        )
        return str(path)
    except OSError as exc:
        print(f"[wizard] Could not persist default sequence: {exc}", file=sys.stderr)
        return None


def _try_load_groups_config():
    """Restore groups from the live recordings/groups_config.json when present."""
    loaded_default = _try_load_default_steps()
    cfg = groups_config_path()
    if not cfg.is_file():
        if not loaded_default:
            _try_hydrate_default_steps_from_groups()
        return
    try:
        raw = json.loads(cfg.read_text(encoding="utf-8"))
        groups = raw.get("groups")
        if isinstance(groups, list) and groups:
            _drop_empty_phone_serials(groups)
            state["groups"] = groups
            _normalize_all_groups()
            if not loaded_default:
                _try_hydrate_default_steps_from_groups()
    except (json.JSONDecodeError, OSError, UnicodeError, TypeError, ValueError) as exc:
        print(f"[wizard] Could not load groups config ({cfg}): {exc}", file=sys.stderr)


def _groups_have_assigned_phones() -> bool:
    return bool(iter_group_phone_entries(list(state.get("groups") or [])))


def _persist_groups_config() -> str | None:
    """Write groups to recordings/groups_config.json (shared by wizard + spawned windows)."""
    _persist_default_steps()
    if not _groups_have_assigned_phones():
        try:
            from mumu_setup_core import repair_groups_if_empty

            repaired, _wrote = repair_groups_if_empty()
            if repaired is not None:
                _try_load_groups_config()
                return str(repaired)
        except Exception:
            pass
        print(
            "[wizard] Skipped persist — groups have no phones (run Phone Setup GO)",
            file=sys.stderr,
        )
        return None
    out = groups_config_path()
    try:
        groups = state["groups"]
        _drop_empty_phone_serials(groups)
        payload = {"_note": "Written by PharmFlow", "groups": groups}
        written = persist_groups_config_text(
            json.dumps(payload, indent=2) + "\n",
            primary=out,
        )
        return str(written)
    except OSError as exc:
        print(f"[wizard] Could not persist groups config: {exc}", file=sys.stderr)
        return None


# ─── per-phone sequence editor ────────────────────────────────────────────────

class PerPhoneSequenceEditor(tk.Toplevel):
    """Edit the sequence for ONE specific phone within a group.

    Each phone gets its own independent steps list. Cloning makes
    a copy of the master (Phone 1) steps to all other phones.

    Optional ``phone_ent`` is the group's ``phones[serial]`` dict — used to edit
    optional rotation of saved flow files (playlist) alongside inline steps.
    """
    def __init__(self, parent, serial, phone_name, steps_list, phone_ent=None, phone_wm_size=None):
        super().__init__(parent)
        self.steps_list = steps_list   # shared target reference — only mutated on Save
        self.serial     = serial
        self._phone_ent = phone_ent    # optional dict ref from state["groups"]
        self._phone_wm_size = phone_wm_size if isinstance(phone_wm_size, tuple) else None
        self._draft_steps = copy.deepcopy(steps_list)
        self._sequence_dirty = False
        self._playlist_steps_paned: tk.PanedWindow | None = None
        self._playlist_steps_sash_placed = False
        self._after_sash_idle_id: str | None = None
        self._after_sash_retry_id: str | None = None
        self._did_save = False
        self.title(f"Sequence — {phone_name}")
        self.config(bg=BG)
        # Taller default so playlist + inline steps panes fit on 1080p after header cards.
        self.geometry("980x900")
        self.minsize(780, 680)
        self.resizable(True, True)
        try:
            if parent.winfo_viewable():
                self.transient(parent)
        except Exception:
            pass
        self.grab_set()
        self.after(50, self._lift_to_front)

        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=SP["page"], pady=SP["page"])

        scroll_host = tk.Frame(outer, bg=BG)
        scroll_host.pack(fill="both", expand=True)
        self._canvas = tk.Canvas(scroll_host, bg=BG, highlightthickness=0)
        scroll_y = themed_vertical_scrollbar(scroll_host, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scroll_y.set)
        scroll_y.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        main = tk.Frame(self._canvas, bg=BG)
        self._main_window_id = self._canvas.create_window((0, 0), window=main, anchor="nw")
        main.bind(
            "<Configure>",
            lambda _e: canvas_set_scrollregion_from_bbox_all(self._canvas),
        )
        self._canvas.bind(
            "<Configure>",
            lambda e: canvas_embed_set_width(self._canvas, self._main_window_id, e),
        )
        self._canvas.bind("<Enter>", lambda _e: self._canvas.focus_set())
        main.bind("<Enter>", lambda _e: self._canvas.focus_set())
        _bind_nested_canvas_mousewheel(self._canvas)

        bottom = tk.Frame(
            outer,
            bg=FOOTER_BG,
            height=64,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        bottom.pack_propagate(False)
        back_btn = tk.Button(
            bottom,
            text="← Back",
            font=("Segoe UI", 11, "bold"),
            bg=BG3,
            fg=T1,
            relief="flat",
            cursor="hand2",
            command=self._back_without_save,
            padx=SP["lg"],
            pady=SP["sm"],
            bd=0,
            highlightthickness=0,
        )
        style_secondary_button(back_btn)
        back_btn.pack(side="left")
        run_now_btn = tk.Button(
            bottom,
            text="Tryout / Run now",
            font=("Segoe UI", 11, "bold"),
            bg=ACCENT,
            fg=ON_ACCENT,
            relief="flat",
            cursor="hand2",
            command=self._save_and_tryout,
            padx=SP["lg"],
            pady=SP["sm"],
            bd=0,
            highlightthickness=0,
        )
        style_primary_button(run_now_btn)
        run_now_btn.pack(side="left", padx=(SP["sm"], 0))
        ok_btn = tk.Button(
            bottom,
            text="OK",
            font=("Segoe UI", 11, "bold"),
            bg=GREEN,
            fg=ON_ACCENT,
            relief="flat",
            cursor="hand2",
            command=self._save_and_close,
            padx=SP["lg"],
            pady=SP["sm"],
            bd=0,
            highlightthickness=0,
        )
        ok_btn.configure(activebackground=GREEN_ACTIVE, activeforeground=ON_ACCENT)
        ok_btn.pack(side="right")
        cancel_btn = tk.Button(
            bottom,
            text="Cancel",
            font=("Segoe UI", 11, "bold"),
            bg=BG3,
            fg=T1,
            relief="flat",
            cursor="hand2",
            command=self._cancel,
            padx=SP["lg"],
            pady=SP["sm"],
            bd=0,
            highlightthickness=0,
        )
        style_secondary_button(cancel_btn)
        cancel_btn.pack(side="right", padx=(0, SP["sm"]))
        bottom.pack(side="bottom", fill="x", pady=(SP["md"], 0))
        bind_canvas_mousewheel(outer, self._canvas, primary=self._canvas)

        intro = instruction_card(main)
        intro.pack(fill="x", pady=(0, SP["md"]))
        tk.Label(intro, text=f"Phone: {phone_name}  ({serial})",
                 font=("Segoe UI", 13, "bold"), bg=BG2, fg=T1).pack(
                     anchor="w", fill="x")
        tk.Label(intro,
                 text="This sequence is only for this phone. "
                      "Changes here do not affect other phones.",
                 font=FS, bg=BG2, fg=T2).pack(anchor="w", fill="x", pady=(SP["xs"], 0))
        tk.Label(
            intro,
            text=(
                "Scroll to the bottom to reach inline backup steps and OK. "
                "Playlist options (Set A / Set B) are above the step list — use the inner scrollbar if the pane is tall."
            ),
            font=FONT_CAPTION,
            bg=BG2,
            fg=T3,
            anchor="w",
            justify="left",
            wraplength=820,
        ).pack(anchor="w", fill="x", pady=(SP["sm"], 0))
        tk.Label(
            intro,
            text="These steps run only if a saved sequence file is missing.",
            font=FONT_CAPTION,
            bg=BG2,
            fg=T3,
            anchor="w",
        ).pack(anchor="w", fill="x", pady=(SP["sm"], 0))

        prof_card = instruction_card(main)
        prof_card.pack(fill="x", pady=(0, SP["md"]))
        tk.Label(
            prof_card,
            text="Sequence screen-size profile",
            font=FONT_SECTION,
            bg=BG2,
            fg=T1,
            anchor="w",
        ).pack(fill="x", pady=(0, SP["xs"]))
        tk.Label(
            prof_card,
            text=(
                "profile = coordinates you planned for (base_w × base_h). "
                "wm = live adb shell wm size on the device — keep them aligned to avoid mis-taps."
            ),
            font=FONT_CAPTION,
            bg=BG2,
            fg=T3,
            anchor="w",
            wraplength=680,
            justify="left",
        ).pack(fill="x", pady=(0, SP["xs"]))
        if isinstance(phone_ent, dict):
            base_w = _coerce_profile_dim(phone_ent.get("sequence_base_w"), DEFAULT_SEQUENCE_BASE_W)
            base_h = _coerce_profile_dim(phone_ent.get("sequence_base_h"), DEFAULT_SEQUENCE_BASE_H)
        else:
            base_w, base_h = DEFAULT_SEQUENCE_BASE_W, DEFAULT_SEQUENCE_BASE_H
        self._base_w_var = tk.IntVar(value=base_w)
        self._base_h_var = tk.IntVar(value=base_h)
        self._profile_lbl = tk.Label(prof_card, text="", font=FS, bg=BG2, fg=T2, anchor="w")
        self._profile_lbl.pack(fill="x", pady=(0, SP["xs"]))
        self._profile_warn_lbl = tk.Label(prof_card, text="", font=FONT_CAPTION, bg=BG2, fg=T3, anchor="w")
        self._profile_warn_lbl.pack(fill="x", pady=(0, SP["sm"]))
        prof_row = tk.Frame(prof_card, bg=BG2)
        prof_row.pack(fill="x")
        tk.Label(prof_row, text="base_w", font=FS, bg=BG2, fg=T3).pack(side="left")
        bw_sb = _int_clamped_entry(prof_row, self._base_w_var, 240, 5000, width=6, bg=BG3)
        bw_sb.pack(side="left", padx=(6, 10))
        tk.Label(prof_row, text="base_h", font=FS, bg=BG2, fg=T3).pack(side="left")
        bh_sb = _int_clamped_entry(prof_row, self._base_h_var, 240, 8000, width=6, bg=BG3)
        bh_sb.pack(side="left", padx=(6, 10))
        tk.Label(
            prof_row,
            text="Screen size for taps (default 900 x 1600)",
            font=FONT_CAPTION,
            bg=BG2,
            fg=T3,
        ).pack(side="left")
        self._base_w_var.trace_add("write", lambda *_: self._on_profile_changed())
        self._base_h_var.trace_add("write", lambda *_: self._on_profile_changed())
        self._refresh_profile_status()

        actions_card = instruction_card(main)
        actions_card.pack(fill="x", pady=(0, SP["md"]))
        tk.Label(
            actions_card,
            text="Edit steps",
            font=FONT_SECTION,
            bg=BG2,
            fg=T1,
            anchor="w",
        ).pack(fill="x", pady=(0, SP["sm"]))
        ctrl = tk.Frame(actions_card, bg=BG2)
        ctrl.pack(fill="x")
        for text, cmd, color in [
            ("+ Add Step",  self._add,    GREEN),
            ("Remove",      self._remove, RED),
            ("Move up",     self._up,     BG3),
            ("Move down",   self._dn,     BG3),
        ]:
            b = tk.Button(ctrl, text=text, command=cmd,
                          bg=color, fg=ON_ACCENT if color != BG3 else T1,
                          font=("Segoe UI", 10, "bold"),
                          relief="flat", cursor="hand2",
                          padx=10, pady=6, bd=0, highlightthickness=0)
            if color == GREEN:
                b.configure(activebackground=GREEN_ACTIVE, activeforeground=ON_ACCENT)
            elif color == RED:
                style_danger_button(b)
            else:
                style_secondary_button(b)
            b.pack(side="left", padx=(0, SP["sm"]))

        att_btn = tk.Button(
            ctrl,
            text="ATT / tracking prefs",
            font=("Segoe UI", 10, "bold"),
            command=self._att_tracking_quick_help,
            bg=BG4,
            fg=T1,
            relief="flat",
            cursor="hand2",
            padx=10,
            pady=6,
            bd=0,
            highlightthickness=0,
        )
        style_secondary_button(att_btn)
        att_btn.pack(side="right")

        file_card = instruction_card(main)
        file_card.pack(fill="x", pady=(0, SP["md"]))
        tk.Label(
            file_card,
            text="Saved sequence file (this phone only)",
            font=FONT_SECTION,
            bg=BG2,
            fg=T1,
            anchor="w",
        ).pack(fill="x", pady=(0, SP["xs"]))
        tk.Label(
            file_card,
            text="Load a file if this phone should be different from others. Save to export these steps.",
            font=FONT_CAPTION,
            bg=BG2,
            fg=T3,
            anchor="w",
        ).pack(fill="x", pady=(0, SP["sm"]))
        fr_btns = tk.Frame(file_card, bg=BG2)
        fr_btns.pack(fill="x")
        lb = tk.Button(
            fr_btns,
            text="Load sequence file…",
            font=FS,
            bg=ACCENT,
            fg=ON_ACCENT,
            relief="flat",
            cursor="hand2",
            padx=SP["sm"],
            pady=SP["sm"],
            command=self._load_json,
            bd=0,
            highlightthickness=0,
        )
        style_primary_button(lb)
        lb.pack(side="left", padx=(0, SP["xs"]))
        sb_btn = tk.Button(
            fr_btns,
            text="Save sequence file as…",
            font=FS,
            bg=BG3,
            fg=T1,
            relief="flat",
            cursor="hand2",
            padx=SP["sm"],
            pady=SP["sm"],
            command=self._save_json,
            bd=0,
            highlightthickness=0,
        )
        style_secondary_button(sb_btn)
        sb_btn.pack(side="left", padx=(0, SP["sm"]))

        body = tk.Frame(main, bg=BG)
        # fill=x so the outer scroll canvas grows with playlist + steps (expand=True clips inside create_window).
        body.pack(fill="x", pady=(0, SP["sm"]))

        if phone_ent is not None:
            self._playlist_names: list[str] = _normalize_sequence_playlist_items(
                phone_ent.get("sequence_playlist") or []
            )
            phone_ent["sequence_playlist"] = list(self._playlist_names)
            self._playlist_secondary_names: list[str] = _normalize_sequence_playlist_items(
                phone_ent.get("sequence_playlist_secondary") or []
            )
            phone_ent["sequence_playlist_secondary"] = list(self._playlist_secondary_names)
            paned = tk.PanedWindow(
                body,
                orient=tk.VERTICAL,
                bg=BG,
                sashwidth=6,
                sashrelief="flat",
                bd=0,
                height=720,
            )
            paned.pack(fill="x")

            # Scroll the playlist card: mode/shuffle radios are tall; without this the PanedWindow
            # assigns the whole top pane to that content and crops the inline steps list below.
            pl_scroll_outer = tk.Frame(paned, bg=BG)
            canvas_pl = tk.Canvas(pl_scroll_outer, bg=BG, highlightthickness=0)
            self._playlist_scroll_canvas = canvas_pl
            vsb_pl = themed_vertical_scrollbar(pl_scroll_outer, command=canvas_pl.yview)
            canvas_pl.configure(yscrollcommand=vsb_pl.set)
            vsb_pl.pack(side="right", fill="y")
            canvas_pl.pack(side="left", fill="both", expand=True)
            pl_inner = tk.Frame(canvas_pl, bg=BG)
            pl_win_id = canvas_pl.create_window((0, 0), window=pl_inner, anchor="nw")
            pl_inner.bind(
                "<Configure>",
                lambda _e: canvas_set_scrollregion_from_bbox_all(canvas_pl),
            )
            canvas_pl.bind(
                "<Configure>",
                lambda e: canvas_embed_set_width(canvas_pl, pl_win_id, e),
            )
            _bind_nested_canvas_mousewheel(canvas_pl)

            pl_box = instruction_card(pl_inner, pad=SP["card"])
            pl_box.pack(fill="x")
            tk.Label(
                pl_box,
                text="Saved sequences playlist (optional)",
                font=FONT_SECTION,
                bg=BG2,
                fg=T1,
                anchor="w",
            ).pack(fill="x", pady=(0, SP["xs"]))
            tk.Label(
                pl_box,
                text="Pick saved .json files, or use Folder mode to run every file in a "
                     "subfolder (e.g. 900x1600/no-ad). Set A is main; Set B runs after A. "
                     "If lists are empty, backup steps below are used.",
                font=FONT_CAPTION,
                bg=BG2,
                fg=T3,
                anchor="w",
                justify="left",
                wraplength=840,
            ).pack(fill="x", pady=(0, SP["md"]))
            self._pl_manual_outer = tk.Frame(pl_box, bg=BG2)
            self._pl_manual_outer.pack(fill="x")
            tk.Label(
                self._pl_manual_outer,
                text="Set A — sequence files",
                font=FS,
                bg=BG2,
                fg=T2,
                anchor="w",
            ).pack(fill="x", pady=(0, SP["xs"]))
            pl_row = tk.Frame(self._pl_manual_outer, bg=BG2)
            pl_row.pack(fill="x")
            pl_list_wrap = tk.Frame(pl_row, bg=BG2)
            pl_list_wrap.pack(side="left", fill="both", expand=True)
            self._pl_lb = tk.Listbox(
                pl_list_wrap,
                font=FM,
                bg=BG3,
                fg=T1,
                relief="flat",
                height=5,
                activestyle="none",
                selectbackground=ACCENT,
            )
            pl_yscroll = themed_vertical_scrollbar(
                pl_list_wrap,
                command=self._pl_lb.yview,
            )
            self._pl_lb.configure(yscrollcommand=pl_yscroll.set)
            self._pl_lb.pack(side="left", fill="both", expand=True)
            pl_yscroll.pack(side="right", fill="y")
            pl_btns = tk.Frame(pl_row, bg=BG2)
            pl_btns.pack(side="left", fill="y", padx=(SP["md"], 0))
            for txt, cmd in [
                ("Add flow(s)…", self._pl_add_file),
                ("Remove", self._pl_remove),
                ("Move up", self._pl_up),
                ("Move down", self._pl_down),
            ]:
                bb = tk.Button(
                    pl_btns,
                    text=txt,
                    command=cmd,
                    font=("Segoe UI", 9, "bold"),
                    bg=BG3,
                    fg=T1,
                    relief="flat",
                    cursor="hand2",
                    padx=SP["sm"],
                    pady=SP["xs"],
                    bd=0,
                    highlightthickness=0,
                )
                style_secondary_button(bb)
                bb.pack(fill="x", pady=(0, SP["xs"]))
            self._pl_mode = tk.StringVar(
                value=(phone_ent.get("sequence_playlist_mode") or "series")
            )
            mode_fr = tk.Frame(pl_box, bg=BG2)
            mode_fr.pack(fill="x", pady=(SP["md"], 0))
            tk.Label(
                mode_fr,
                text="How each run picks files:",
                font=FS,
                bg=BG2,
                fg=T2,
                anchor="w",
            ).pack(fill="x", pady=(0, SP["xs"]))
            tk.Radiobutton(
                mode_fr,
                text="Ordered — one file per group repeat (round-robin). "
                     "Use Series to chain every file before identity reset.",
                variable=self._pl_mode,
                value="ordered",
                command=self._on_pl_mode_changed,
                bg=BG2,
                fg=T1,
                activebackground=BG2,
                activeforeground=T1,
                selectcolor=BG,
                font=FS,
                anchor="w",
                justify="left",
            ).pack(fill="x")
            tk.Radiobutton(
                mode_fr,
                text="Random — pick one file from each list per run.",
                variable=self._pl_mode,
                value="random",
                command=self._on_pl_mode_changed,
                bg=BG2,
                fg=T1,
                activebackground=BG2,
                activeforeground=T1,
                selectcolor=BG,
                font=FS,
                anchor="w",
                justify="left",
            ).pack(fill="x")
            tk.Radiobutton(
                mode_fr,
                text="Series — run every file in set A in order, then every file in set B in order, "
                     "on each repeat (full chain every time)",
                variable=self._pl_mode,
                value="series",
                command=self._on_pl_mode_changed,
                bg=BG2,
                fg=T1,
                activebackground=BG2,
                activeforeground=T1,
                selectcolor=BG,
                font=FS,
                anchor="w",
                justify="left",
            ).pack(fill="x")
            tk.Radiobutton(
                mode_fr,
                text="Folder — run every .json in a sequences subfolder (sorted) each repeat",
                variable=self._pl_mode,
                value="folder",
                command=self._on_pl_mode_changed,
                bg=BG2,
                fg=T1,
                activebackground=BG2,
                activeforeground=T1,
                selectcolor=BG,
                font=FS,
                anchor="w",
                justify="left",
            ).pack(fill="x")
            tk.Radiobutton(
                mode_fr,
                text="Folder (random) — shuffle all .json in folder each phone cycle, then run series",
                variable=self._pl_mode,
                value="folder_random",
                command=self._on_pl_mode_changed,
                bg=BG2,
                fg=T1,
                activebackground=BG2,
                activeforeground=T1,
                selectcolor=BG,
                font=FS,
                anchor="w",
                justify="left",
            ).pack(fill="x")
            folder_fr = tk.Frame(pl_box, bg=BG2)
            self._pl_folder_outer = folder_fr
            tk.Label(
                folder_fr,
                text="Sequence folder (relative to sequences root, e.g. 900x1600/no-ad):",
                font=FS,
                bg=BG2,
                fg=T2,
                anchor="w",
            ).pack(fill="x", pady=(0, SP["xs"]))
            folder_row = tk.Frame(folder_fr, bg=BG2)
            folder_row.pack(fill="x")
            self._sequence_folder_var = tk.StringVar(
                value=str(phone_ent.get("sequence_folder") or "").strip()
            )
            self._sequence_folder_entry = tk.Entry(
                folder_row,
                textvariable=self._sequence_folder_var,
                font=FM,
                bg=BG3,
                fg=T1,
                relief="flat",
                insertbackground=T1,
            )
            self._sequence_folder_entry.pack(side="left", fill="x", expand=True, padx=(0, SP["sm"]))
            self._sequence_folder_entry.bind(
                "<KeyRelease>", lambda _e: self._mark_sequence_edited()
            )
            folder_btn = tk.Button(
                folder_row,
                text="Browse folder…",
                command=self._pl_browse_folder,
                font=("Segoe UI", 9, "bold"),
                bg=BG3,
                fg=T1,
                relief="flat",
                cursor="hand2",
                padx=SP["sm"],
                pady=SP["xs"],
                bd=0,
                highlightthickness=0,
            )
            style_secondary_button(folder_btn)
            folder_btn.pack(side="left")
            self._sequence_folder_var.trace_add(
                "write", lambda *_: self._sync_folder_mode_ui()
            )
            self._pl_mode.trace_add("write", lambda *_: self._sync_folder_mode_ui())
            self._sync_folder_mode_ui()
            self._pl_shuffle = tk.StringVar(
                value=_normalize_sequence_playlist_shuffle(
                    phone_ent.get("sequence_playlist_shuffle")
                )
            )
            shuffle_fr = tk.Frame(self._pl_manual_outer, bg=BG2)
            shuffle_fr.pack(fill="x", pady=(SP["md"], 0))
            tk.Label(
                shuffle_fr,
                text="Shuffle file order each run (optional):",
                font=FS,
                bg=BG2,
                fg=T2,
                anchor="w",
            ).pack(fill="x", pady=(0, SP["xs"]))
            shuf_row = tk.Frame(shuffle_fr, bg=BG2)
            shuf_row.pack(fill="x")
            self._pl_shuffle_combo = ttk.Combobox(
                shuf_row,
                textvariable=self._pl_shuffle,
                values=(
                    "none",
                    "set_a",
                    "set_b",
                    "both_sets_separately",
                    "combined",
                ),
                state="readonly",
                font=FM,
                width=30,
            )
            self._pl_shuffle_combo.pack(side="left")
            self._pl_shuffle_combo.bind(
                "<<ComboboxSelected>>", lambda _e: self._mark_sequence_edited()
            )
            tk.Label(
                shuffle_fr,
                text="none = keep order · set_a/set_b = shuffle one list · "
                     "both = shuffle each list · combined = shuffle A and B together.",
                font=FONT_CAPTION,
                bg=BG2,
                fg=T3,
                anchor="w",
                justify="left",
                wraplength=520,
            ).pack(fill="x", pady=(SP["xs"], 0))
            self._pl_second_set_var = tk.BooleanVar(value=bool(self._playlist_secondary_names))
            sec_chk = tk.Checkbutton(
                self._pl_manual_outer,
                text="Set B (optional) — runs after Set A in the same run",
                variable=self._pl_second_set_var,
                command=self._pl_toggle_second_set,
                font=FS,
                bg=BG2,
                fg=T1,
                activebackground=BG2,
                activeforeground=T1,
                selectcolor=BG,
                anchor="w",
            )
            sec_chk.pack(fill="x", pady=(SP["md"], SP["xs"]))
            self._pl_sec_outer = tk.Frame(self._pl_manual_outer, bg=BG2)
            tk.Label(
                self._pl_sec_outer,
                text="Set B — sequence files (after Set A)",
                font=FS,
                bg=BG2,
                fg=T2,
                anchor="w",
            ).pack(fill="x", pady=(0, SP["xs"]))
            pl_row_b = tk.Frame(self._pl_sec_outer, bg=BG2)
            pl_row_b.pack(fill="x")
            pl_list_b = tk.Frame(pl_row_b, bg=BG2)
            pl_list_b.pack(side="left", fill="both", expand=True)
            self._pl_lb_b = tk.Listbox(
                pl_list_b,
                font=FM,
                bg=BG3,
                fg=T1,
                relief="flat",
                height=4,
                activestyle="none",
                selectbackground=ACCENT,
            )
            pl_yscroll_b = themed_vertical_scrollbar(
                pl_list_b,
                command=self._pl_lb_b.yview,
            )
            self._pl_lb_b.configure(yscrollcommand=pl_yscroll_b.set)
            self._pl_lb_b.pack(side="left", fill="both", expand=True)
            pl_yscroll_b.pack(side="right", fill="y")
            pl_btns_b = tk.Frame(pl_row_b, bg=BG2)
            pl_btns_b.pack(side="left", fill="y", padx=(SP["md"], 0))
            for txt, cmd in [
                ("Add flow(s)…", self._pl_b_add_file),
                ("Remove", self._pl_b_remove),
                ("Move up", self._pl_b_up),
                ("Move down", self._pl_b_down),
            ]:
                bb = tk.Button(
                    pl_btns_b,
                    text=txt,
                    command=cmd,
                    font=("Segoe UI", 9, "bold"),
                    bg=BG3,
                    fg=T1,
                    relief="flat",
                    cursor="hand2",
                    padx=SP["sm"],
                    pady=SP["xs"],
                    bd=0,
                    highlightthickness=0,
                )
                style_secondary_button(bb)
                bb.pack(fill="x", pady=(0, SP["xs"]))
            self._pl_refresh_playlist()
            self._pl_refresh_playlist_b()
            self._pl_toggle_second_set()
            self._pl_bind_drop(self._pl_lb, set_b=False)
            self._pl_bind_drop(self._pl_lb_b, set_b=True)
            paned.add(pl_scroll_outer, minsize=200)

            steps_card = instruction_card(paned, pad=SP["card"])
            tk.Label(
                steps_card,
                text="Inline backup steps",
                font=FONT_SECTION,
                bg=BG2,
                fg=T1,
                anchor="w",
            ).pack(fill="x", pady=(0, SP["sm"]))
            tk.Label(
                steps_card,
                text="Backup steps (used if playlists are empty or files are missing)",
                font=FONT_CAPTION,
                bg=BG2,
                fg=T3,
                anchor="w",
            ).pack(fill="x", pady=(0, SP["sm"]))
            fr = tk.Frame(steps_card, bg=BG2)
            fr.pack(fill="both", expand=True)
            paned.add(steps_card, minsize=260)
            self._playlist_steps_paned = paned
            try:
                paned.paneconfigure(pl_scroll_outer, stretch="always")
                paned.paneconfigure(steps_card, stretch="always")
            except tk.TclError:
                pass
        else:
            steps_card = instruction_card(body, pad=SP["card"])
            steps_card.pack(fill="both", expand=True)
            tk.Label(
                steps_card,
                text="Steps",
                font=FONT_SECTION,
                bg=BG2,
                fg=T1,
                anchor="w",
            ).pack(fill="x", pady=(0, SP["sm"]))
            fr = tk.Frame(steps_card, bg=BG2)
            fr.pack(fill="both", expand=True)

        self._lb = tk.Listbox(
            fr,
            font=FM,
            bg=BG3,
            fg=T1,
            selectbackground=ACCENT,
            relief="flat",
            height=18,
            activestyle="none",
        )
        sb = themed_vertical_scrollbar(
            fr,
            command=self._lb.yview,
        )
        self._lb.configure(yscrollcommand=sb.set)
        self._lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        tk.Frame(main, bg=BG, height=SCROLL_BOTTOM_PAD).pack(fill="x")

        self._refresh()
        if self._playlist_steps_paned is not None:
            self.bind("<Destroy>", self._cancel_per_phone_deferred, add=True)
            self._after_sash_idle_id = self.after_idle(self._sync_playlist_steps_sash)
        canvas_schedule_scrollregion_refresh(self._canvas)
        bind_canvas_mousewheel(self, self._canvas, primary=self._canvas)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", self._cancel)
        self.bind("<Control-s>", self._save_and_close)
        self.bind("<Control-S>", self._save_and_close)
        self.bind("<Return>", self._save_on_return)

    def _cancel_per_phone_deferred(self, event=None) -> None:
        """Cancel pending sash callbacks so Tcl does not invoke a dead binding after destroy."""
        if event is not None and getattr(event, "widget", None) is not self:
            return
        for attr in ("_after_sash_idle_id", "_after_sash_retry_id"):
            aid = getattr(self, attr, None)
            if aid is not None:
                try:
                    self.after_cancel(aid)
                except tk.TclError:
                    pass
                setattr(self, attr, None)

    def _sync_playlist_steps_sash(self, event=None) -> None:
        """Place the playlist / inline-steps splitter once so both panes are visible (PanedWindow defaults can hide steps)."""
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        if self._playlist_steps_sash_placed:
            return
        paned = self._playlist_steps_paned
        if paned is None:
            return
        try:
            self.update_idletasks()
            h = int(paned.winfo_height())
        except tk.TclError:
            return
        if h < 140:
            if self._after_sash_retry_id is not None:
                try:
                    self.after_cancel(self._after_sash_retry_id)
                except tk.TclError:
                    pass
            self._after_sash_retry_id = self.after(80, self._sync_playlist_steps_sash)
            return
        bottom_reserve = max(260, min(440, int(h * 0.55)))
        sash_y = max(120, min(int(h * 0.40), h - bottom_reserve))
        try:
            paned.sashpos(0, sash_y)
        except tk.TclError:
            return
        self._playlist_steps_sash_placed = True
        if self._after_sash_retry_id is not None:
            try:
                self.after_cancel(self._after_sash_retry_id)
            except tk.TclError:
                pass
            self._after_sash_retry_id = None

    def _mark_sequence_edited(self) -> None:
        """Track local edits; only persisted when Save is used."""
        self._sequence_dirty = True

    def _profile_dims(self) -> tuple[int, int]:
        try:
            bw = max(1, int(self._base_w_var.get()))
        except (tk.TclError, TypeError, ValueError):
            bw = DEFAULT_SEQUENCE_BASE_W
        try:
            bh = max(1, int(self._base_h_var.get()))
        except (tk.TclError, TypeError, ValueError):
            bh = DEFAULT_SEQUENCE_BASE_H
        return bw, bh

    def _refresh_profile_status(self) -> None:
        bw, bh = self._profile_dims()
        sel = _profile_key(bw, bh)
        self._profile_lbl.config(text=f"Selected sequence profile: {sel}")
        wm = self._phone_wm_size
        if not wm:
            self._profile_warn_lbl.config(
                text="Device wm size unavailable right now. Runs still use selected sequence profile metadata.",
                fg=T3,
            )
            return
        live = _profile_key(wm[0], wm[1])
        if live == sel:
            self._profile_warn_lbl.config(text=f"Current device wm size matches: {live}", fg=GREEN)
        else:
            self._profile_warn_lbl.config(
                text=f"Warning: phone screen is {live}; sequences expect {sel}. "
                     "Set MuMu to 900 x 1600 portrait Phone.",
                fg=RED,
            )

    def _on_profile_changed(self) -> None:
        self._mark_sequence_edited()
        self._refresh_profile_status()

    def _apply_profile_to_steps(self) -> None:
        bw, bh = self._profile_dims()
        for step in self._draft_steps:
            if not isinstance(step, dict):
                continue
            if step.get("type") in ("tap", "swipe"):
                step["base_w"] = bw
                step["base_h"] = bh

    def _apply_phone_ent_metadata(self) -> None:
        ent = getattr(self, "_phone_ent", None)
        if isinstance(ent, dict):
            if self._sequence_dirty:
                ent["use_default_template"] = False
                ent["explicit_override"] = True
            bw, bh = self._profile_dims()
            ent["sequence_base_w"] = bw
            ent["sequence_base_h"] = bh
            ent["sequence_profile_key"] = _profile_key(bw, bh)
            if hasattr(self, "_playlist_names"):
                ent["sequence_playlist"] = list(self._playlist_names)
                try:
                    mode = self._pl_mode.get()
                    ent["sequence_playlist_mode"] = mode
                except (tk.TclError, AttributeError):
                    ent["sequence_playlist_mode"] = "series"
                try:
                    mode = ent["sequence_playlist_mode"]
                except KeyError:
                    mode = "series"
                if mode in _SEQUENCE_FOLDER_MODES:
                    try:
                        ent["sequence_folder"] = _normalize_sequence_folder(
                            self._sequence_folder_var.get()
                        )
                    except (tk.TclError, AttributeError):
                        ent.pop("sequence_folder", None)
                    ent["sequence_playlist"] = []
                    ent["sequence_playlist_secondary"] = []
                else:
                    ent.pop("sequence_folder", None)
                try:
                    ent["sequence_playlist_shuffle"] = _normalize_sequence_playlist_shuffle(
                        self._pl_shuffle.get()
                    )
                except (tk.TclError, AttributeError):
                    ent["sequence_playlist_shuffle"] = "none"
            if hasattr(self, "_playlist_secondary_names"):
                try:
                    use_b = self._pl_second_set_var.get()
                except (tk.TclError, AttributeError):
                    use_b = False
                ent["sequence_playlist_secondary"] = (
                    list(self._playlist_secondary_names) if use_b else []
                )

    def _save_and_close(self, event=None):
        self._apply_profile_to_steps()
        self.steps_list[:] = copy.deepcopy(self._draft_steps)
        self._apply_phone_ent_metadata()
        self._did_save = True
        self.destroy()

    def _resolve_wizard_shell(self):
        cur = self.master
        while cur is not None:
            if isinstance(cur, PharmFlowWizard):
                return cur
            cur = getattr(cur, "master", None)
        return None

    def _save_and_tryout(self, event=None):
        self._apply_profile_to_steps()
        self.steps_list[:] = copy.deepcopy(self._draft_steps)
        self._apply_phone_ent_metadata()
        self._did_save = True
        wiz = self._resolve_wizard_shell()
        if wiz is None:
            messagebox.showinfo(
                "Can't run now",
                "Something went wrong starting a test run.\n\n"
                "Go to the Launch step and tap Start automation.",
                parent=self,
            )
            return
        self.destroy()
        try:
            wiz.start_tryout_from_groups()
        except Exception as exc:
            messagebox.showerror(
                "Run failed",
                f"Could not start the run:\n{exc}",
                parent=wiz.winfo_toplevel(),
            )

    def _cancel(self, event=None):
        if self._sequence_dirty:
            if not messagebox.askyesno(
                "Discard changes?",
                "Close without saving edits to this phone sequence?",
                parent=self,
            ):
                return
        self.destroy()

    def _lift_to_front(self) -> None:
        """WebView shell keeps tk root withdrawn — raise editor above PharmFlow window."""
        try:
            import sys

            self.deiconify()
            self.state("normal")
            self.lift()
            self.attributes("-topmost", True)
            self.update_idletasks()
            if sys.platform == "win32":
                import ctypes

                hwnd = int(self.winfo_id())
                user32 = ctypes.windll.user32
                user32.ShowWindow(hwnd, 9)
                user32.keybd_event(0x12, 0, 0, 0)
                user32.keybd_event(0x12, 0, 2, 0)
                user32.SetForegroundWindow(hwnd)
            self.focus_force()
            self.after(600, lambda: self.attributes("-topmost", False))
        except Exception:
            pass

    def _back_without_save(self, event=None):
        """Return to Groups without applying edits (does not save)."""
        self._cancel(event)

    def _save_on_return(self, event=None):
        w = self.focus_get()
        if w is not None:
            cls = str(w.winfo_class()).lower()
            if cls in {"entry", "text", "spinbox", "ttk::combobox", "listbox"}:
                return
        self._save_and_close(event)

    def _pl_refresh_playlist(self) -> None:
        if not hasattr(self, "_pl_lb"):
            return
        self._pl_lb.delete(0, "end")
        for name in self._playlist_names:
            self._pl_lb.insert("end", f"  {name}")

    def _pl_toggle_second_set(self) -> None:
        """Show or hide set B editor."""
        self._mark_sequence_edited()
        if not hasattr(self, "_pl_sec_outer"):
            return
        try:
            on = self._pl_second_set_var.get()
        except (tk.TclError, AttributeError):
            on = False
        if on:
            self._pl_sec_outer.pack(fill="x", pady=(0, SP["sm"]))
        else:
            self._pl_sec_outer.pack_forget()
        self.after_idle(self._refresh_per_phone_scrollregions)

    def _refresh_per_phone_scrollregions(self) -> None:
        """Update scrollregions after playlist / set B layout changes."""
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        canvas_set_scrollregion_from_bbox_all(self._canvas)
        pl_canvas = getattr(self, "_playlist_scroll_canvas", None)
        if pl_canvas is not None:
            canvas_set_scrollregion_from_bbox_all(pl_canvas)

    def _pl_refresh_playlist_b(self) -> None:
        if not hasattr(self, "_pl_lb_b"):
            return
        self._pl_lb_b.delete(0, "end")
        for name in self._playlist_secondary_names:
            self._pl_lb_b.insert("end", f"  {name}")

    @staticmethod
    def _playlist_basenames_from_paths(paths) -> list[str]:
        out: list[str] = []
        seq_root = Path(_sequences_initial_dir()).resolve()
        for raw in paths or ():
            try:
                s = str(raw or "").strip()
            except Exception:
                s = ""
            if not s:
                continue
            p = Path(s)
            try:
                if p.is_absolute():
                    ref = p.resolve().relative_to(seq_root).as_posix()
                else:
                    ref = p.as_posix().lstrip("/")
            except ValueError:
                ref = p.name
            if not ref.lower().endswith(".json"):
                continue
            if ".." in ref.split("/"):
                ref = p.name
            if ref and ref not in out:
                out.append(ref)
        return out

    def _pl_add_from_paths(self, paths, *, set_b: bool) -> int:
        names = self._playlist_basenames_from_paths(paths)
        if not names:
            return 0
        target = self._playlist_secondary_names if set_b else self._playlist_names
        added = 0
        for base in names:
            if base in target:
                continue
            target.append(base)
            added += 1
        if added:
            self._mark_sequence_edited()
            if set_b:
                self._pl_refresh_playlist_b()
            else:
                self._pl_refresh_playlist()
        return added

    def _pl_choose_files(self, *, set_b: bool) -> None:
        title = "Choose one or more saved sequence files"
        if set_b:
            title += " (Set B)"
        paths = filedialog.askopenfilenames(
            parent=self,
            title=title,
            filetypes=[("Saved sequence", "*.json"), ("All files", "*.*")],
            initialdir=_json_file_dialog_initialdir(),
        )
        if not paths:
            return
        self._pl_add_from_paths(paths, set_b=set_b)

    def _pl_parse_drop_paths(self, event_data: str) -> list[str]:
        data = (event_data or "").strip()
        if not data:
            return []
        try:
            items = list(self.tk.splitlist(data))
            if items:
                return items
        except Exception:
            pass
        try:
            return shlex.split(data)
        except ValueError:
            return [data]

    def _pl_bind_drop(self, widget: tk.Misc, *, set_b: bool) -> None:
        if not hasattr(widget, "drop_target_register") or not hasattr(widget, "dnd_bind"):
            return
        try:
            widget.drop_target_register("DND_Files")
        except Exception:
            return
        def _on_drop(event):
            paths = self._pl_parse_drop_paths(getattr(event, "data", ""))
            added = self._pl_add_from_paths(paths, set_b=set_b)
            if added <= 0:
                messagebox.showwarning(
                    "No sequence files added",
                    "Drop saved .json sequence files here, or tap Add flow(s)…",
                    parent=self,
                )
            return "break"
        widget.dnd_bind("<<Drop>>", _on_drop)

    def _on_pl_mode_changed(self) -> None:
        self._mark_sequence_edited()
        self._sync_folder_mode_ui()

    def _sync_folder_mode_ui(self) -> None:
        try:
            mode = self._pl_mode.get()
        except (tk.TclError, AttributeError):
            mode = "series"
        folder_mode = mode in _SEQUENCE_FOLDER_MODES
        folder_outer = getattr(self, "_pl_folder_outer", None)
        manual_outer = getattr(self, "_pl_manual_outer", None)
        if folder_outer is not None:
            if folder_mode:
                folder_outer.pack(fill="x", pady=(SP["md"], 0))
            else:
                folder_outer.pack_forget()
        if manual_outer is not None:
            if folder_mode:
                manual_outer.pack_forget()
            else:
                manual_outer.pack(fill="x")
        entry = getattr(self, "_sequence_folder_entry", None)
        if entry is not None:
            entry.configure(state="normal" if folder_mode else "disabled")
        self.after_idle(self._refresh_per_phone_scrollregions)

    def _pl_browse_folder(self) -> None:
        root = _default_sequences_dir()
        root.mkdir(parents=True, exist_ok=True)
        picked = filedialog.askdirectory(
            parent=self,
            title="Choose sequences folder (every .json inside runs on each cycle)",
            initialdir=str(root),
        )
        if not picked:
            return
        self._sequence_folder_var.set(_rel_to_sequences_root(picked))
        self._pl_mode.set("folder_random")
        self._mark_sequence_edited()

    def _pl_add_file(self) -> None:
        self._pl_choose_files(set_b=False)

    def _pl_remove(self) -> None:
        sel = self._pl_lb.curselection()
        if not sel:
            return
        i = int(sel[0])
        if 0 <= i < len(self._playlist_names):
            self._playlist_names.pop(i)
            self._mark_sequence_edited()
            self._pl_refresh_playlist()

    def _pl_up(self) -> None:
        sel = self._pl_lb.curselection()
        if not sel:
            return
        i = int(sel[0])
        if i > 0:
            self._playlist_names[i - 1], self._playlist_names[i] = (
                self._playlist_names[i],
                self._playlist_names[i - 1],
            )
            self._mark_sequence_edited()
            self._pl_refresh_playlist()
            self._pl_lb.selection_set(i - 1)

    def _pl_down(self) -> None:
        sel = self._pl_lb.curselection()
        if not sel:
            return
        i = int(sel[0])
        if i < len(self._playlist_names) - 1:
            self._playlist_names[i + 1], self._playlist_names[i] = (
                self._playlist_names[i],
                self._playlist_names[i + 1],
            )
            self._mark_sequence_edited()
            self._pl_refresh_playlist()
            self._pl_lb.selection_set(i + 1)

    def _pl_b_add_file(self) -> None:
        self._pl_choose_files(set_b=True)

    def _pl_b_remove(self) -> None:
        sel = self._pl_lb_b.curselection()
        if not sel:
            return
        i = int(sel[0])
        if 0 <= i < len(self._playlist_secondary_names):
            self._playlist_secondary_names.pop(i)
            self._mark_sequence_edited()
            self._pl_refresh_playlist_b()

    def _pl_b_up(self) -> None:
        sel = self._pl_lb_b.curselection()
        if not sel:
            return
        i = int(sel[0])
        if i > 0:
            self._playlist_secondary_names[i - 1], self._playlist_secondary_names[i] = (
                self._playlist_secondary_names[i],
                self._playlist_secondary_names[i - 1],
            )
            self._mark_sequence_edited()
            self._pl_refresh_playlist_b()
            self._pl_lb_b.selection_set(i - 1)

    def _pl_b_down(self) -> None:
        sel = self._pl_lb_b.curselection()
        if not sel:
            return
        i = int(sel[0])
        if i < len(self._playlist_secondary_names) - 1:
            self._playlist_secondary_names[i + 1], self._playlist_secondary_names[i] = (
                self._playlist_secondary_names[i],
                self._playlist_secondary_names[i + 1],
            )
            self._mark_sequence_edited()
            self._pl_refresh_playlist_b()
            self._pl_lb_b.selection_set(i + 1)

    def _load_json(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title=f"Load sequence for {self.serial}",
            filetypes=[("JSON sequence", "*.json"), ("All files", "*.*")],
            initialdir=_json_file_dialog_initialdir(),
        )
        if not path:
            return
        try:
            data, _seq_meta = _load_sequence_document_from_path(Path(path))
        except SequenceJsonLoadError as exc:
            messagebox.showerror("Could not load sequence", str(exc), parent=self)
            return
        raw_n = len(data)
        data = _normalize_sequence_steps(data)
        norm_n = len(data)
        if norm_n < raw_n:
            messagebox.showwarning(
                "Some steps skipped",
                f"{raw_n - norm_n} step(s) were removed because they were invalid. "
                "Review the list before saving.",
                parent=self,
            )
        self._mark_sequence_edited()
        self._draft_steps.clear()
        self._draft_steps.extend(data)
        self._apply_profile_to_steps()
        self._refresh()
        messagebox.showinfo(
            "Loaded",
            f"{len(data)} step(s) loaded for this phone.",
            parent=self,
        )

    def _save_json(self) -> None:
        if not self._draft_steps:
            messagebox.showinfo(
                "Nothing to save",
                "Add or load steps first.",
                parent=self,
            )
            return
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(self.serial))[:40]
        initfile = f"sequence_{safe}.json" if safe else "sequence.json"
        path = filedialog.asksaveasfilename(
            parent=self,
            title=f"Save sequence for {self.serial}",
            defaultextension=".json",
            filetypes=[("JSON sequence", "*.json"), ("All files", "*.*")],
            initialfile=initfile,
            initialdir=_json_file_dialog_initialdir(),
        )
        if not path:
            return
        Path(path).write_text(
            json.dumps(self._draft_steps, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        messagebox.showinfo("Saved", f"Sequence saved to:\n{path}", parent=self)

    def _att_tracking_quick_help(self) -> None:
        """Surface privacy/tracking notes for Chrome automation (ATT is iOS-specific)."""
        serial = (self.serial or "").strip()
        print(
            "[wizard] ATT/tracking quick helper invoked "
            f"(device serial={serial or 'unknown'})",
            flush=True,
        )
        adb_hint = ""
        if serial:
            adb_hint = (
                f"adb -s {serial} shell am start -a "
                "android.settings.APPLICATION_DETAILS_SETTINGS "
                "-d package:com.android.chrome\n\n"
            )
        msg = (
            "App Tracking Transparency (ATT) is an iOS prompt for native apps. "
            "This wizard drives Android Chrome; there is no ATT dialog in that path.\n\n"
            "For tracking-related checks on the device:\n"
            "• Chrome → Settings → Privacy and security.\n"
            "• Android Settings → Google → Ads (reset Ad ID if needed).\n\n"
            "Optional ADB (USB debugging authorized):\n"
            f"{adb_hint}"
            "Docs: docs/SEQUENCE_CATALOG.md (flow timing and presets)."
        )
        messagebox.showinfo("ATT / tracking prefs", msg, parent=self)
        adb_exe = shutil.which("adb")
        if adb_exe and serial:
            try:
                subprocess.Popen(
                    [
                        adb_exe,
                        "-s",
                        serial,
                        "shell",
                        "am",
                        "start",
                        "-a",
                        "android.settings.APPLICATION_DETAILS_SETTINGS",
                        "-d",
                        "package:com.android.chrome",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=_NO_WIN,
                )
            except OSError:
                pass

    def _refresh(self):
        self._lb.delete(0, "end")
        for i, s in enumerate(self._draft_steps, 1):
            self._lb.insert("end", f"  {i:>2}.  {describe_step(s)}")

    def _add(self):
        dlg = AddStepDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            self._mark_sequence_edited()
            self._draft_steps.append(dlg.result)
            self._refresh()

    def _remove(self):
        sel = self._lb.curselection()
        if sel:
            self._mark_sequence_edited()
            del self._draft_steps[sel[0]]
            self._refresh()

    def _up(self):
        sel = self._lb.curselection()
        if not sel or sel[0] == 0: return
        i = sel[0]
        self._mark_sequence_edited()
        self._draft_steps[i-1], self._draft_steps[i] = self._draft_steps[i], self._draft_steps[i-1]
        self._refresh(); self._lb.selection_set(i-1)

    def _dn(self):
        sel = self._lb.curselection()
        if not sel or sel[0] >= len(self._draft_steps) - 1: return
        i = sel[0]
        self._mark_sequence_edited()
        self._draft_steps[i], self._draft_steps[i+1] = self._draft_steps[i+1], self._draft_steps[i]
        self._refresh(); self._lb.selection_set(i+1)




# ─── helpers ──────────────────────────────────────────────────────────────────

_NO_WIN = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
# Dashboard child: hide console and detach from parent console on Windows so a hosting
# cmd.exe window closing does not take down the server; stdin closed so adb/python never
# wait on inherited CONIN$.
_DASHBOARD_SPAWN_FLAGS = _NO_WIN
if IS_WIN and hasattr(subprocess, "DETACHED_PROCESS"):
    _DASHBOARD_SPAWN_FLAGS = _NO_WIN | int(subprocess.DETACHED_PROCESS)  # type: ignore[attr-defined]
# Serialize ADB/Tor cleanup so "Fix browsers" (bg thread) cannot race wizard exit / Turn off Tor.
_wiz_proxy_clear_lock = threading.Lock()


def adb_executable() -> str:
    """Prefer SDK platform-tools adb so TCP connects work even when PATH is wrong."""
    sdk = state.get("sdk_path") or find_sdk()
    if sdk:
        p = Path(sdk) / "platform-tools" / ("adb.exe" if IS_WIN else "adb")
        if p.exists():
            return str(p)
    guess = Path(SDK_DEFAULT_PATH) / "platform-tools" / ("adb.exe" if IS_WIN else "adb")
    if guess.exists():
        return str(guess)
    w = shutil.which("adb")
    if w:
        return w
    return "adb"


def _ensure_minimal_platform_tools(log_fn=None) -> bool:
    """
    MuMu-only users often skip the full SDK; still need adb for TCP.
    Drop Google's platform-tools into %LOCALAPPDATA%\\Android\\Sdk if missing.
    """
    sdk_root = Path(SDK_DEFAULT_PATH)
    pt = sdk_root / "platform-tools" / ("adb.exe" if IS_WIN else "adb")
    if pt.exists():
        if not state.get("sdk_path"):
            state["sdk_path"] = str(sdk_root)
        return True
    try:
        sdk_root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _wiz_debug(f"_ensure_minimal_platform_tools: mkdir {sdk_root}: {e!r}", log_fn)
    if log_fn:
        log_fn("  Downloading Android platform-tools (adb only, ~6 MB)…\n")
    ok = _direct_download_platform_tools(str(sdk_root), log_fn=log_fn)
    if ok and pt.exists():
        state["sdk_path"] = str(sdk_root)
        return True
    return False


def run_cmd(cmd, cwd=None, timeout=120):
    # Always argv-list execution (no shell). Passing a string would be a shell-injection footgun.
    if isinstance(cmd, str):
        raise TypeError("run_cmd expects a sequence of program arguments, not a string")
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=cwd, timeout=timeout,
            shell=False,
            creationflags=_NO_WIN,
            encoding="utf-8",
            errors="replace",
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.SubprocessError, UnicodeError) as e:
        return False, str(e)


def _calibrate_installed_stack(py: str | list[str], pharmflow_root: Path, log_fn) -> bool:
    """Post-install health check: bytecode compile + ``smoke_imports``; stamp recordings dir."""
    try:
        root = Path(pharmflow_root).resolve()
    except OSError:
        return False
    auto = root / "automation"
    if not auto.is_dir():
        log_fn("  (Skipping quick check — no automation folder.)\n")
        return False
    log_fn("  Quick check — making sure PharmFlow runs…\n")
    parent = str(root)
    if isinstance(py, str):
        py_cmd, _disp = _resolve_python_cmd(py)
    elif isinstance(py, list) and py:
        py_cmd = [str(x) for x in py]
        if len(py_cmd) == 1 and " " in py_cmd[0]:
            py_cmd, _disp = _resolve_python_cmd(py_cmd[0])
    else:
        py_cmd, _disp = _resolve_python_cmd(state.get("python_cmd"))
    py_disp = _cmd_display(py_cmd)
    ok_c, out_c = run_cmd(
        py_cmd + ["-m", "compileall", "-q", "automation"],
        cwd=parent,
        timeout=180,
    )
    if not ok_c:
        log_fn(f"  compileall note: {(out_c or '')[-400:]}\n")
        log_fn(f"  (Checked folder: {auto})\n")
    smoke = auto / "smoke_imports.py"
    if smoke.is_file():
        ok_s, out_s = run_cmd(py_cmd + [str(smoke)], cwd=parent, timeout=120)
        tail = (out_s or "").strip()
        if not ok_s:
            log_fn("  Something didn’t verify. Last lines:\n")
            if tail:
                for line in tail.splitlines()[-3:]:
                    log_fn(f"    {line}\n")
            log_fn("  Tap Try again on the install screen, or fix the note above.\n")
            return False
    elif not ok_c:
        # No smoke script — do not stamp success when bytecode compile already failed.
        log_fn("  Quick check failed (compileall) — fix errors above, then Try again.\n")
        return False
    try:
        rec = auto / "recordings"
        rec.mkdir(parents=True, exist_ok=True)
        stamp = rec / ".wizard_calibrated"
        stamp.write_text(
            "ok=True\n"
            f"time_iso={time.strftime('%Y-%m-%dT%H:%M:%S')}\n"
            f"python={py_disp}\n"
            f"root={root}\n",
            encoding="utf-8",
        )
    except OSError:
        pass
    log_fn("  Quick check passed — you can continue.\n")
    return True


def adb_result(*args, serial=None, timeout=20) -> tuple[int, str]:
    """Returncode and text. Empty text with returncode 0 is a landed command."""
    exe = adb_executable()
    cmd = [exe]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_NO_WIN,
            encoding="utf-8",
            errors="replace",
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.SubprocessError, UnicodeError) as e:
        _wiz_debug(f"adb({args!r}, serial={serial!r}): {e!r}", None)
        return 1, ""


def adb(*args, serial=None, timeout=20):
    _rc, text = adb_result(*args, serial=serial, timeout=timeout)
    return text


def input_command_landed(rc: int, text: str) -> bool:
    """True when adb accepted an input command. Empty text with returncode 0 is enough.

    A non-zero exit or an error line is not a tap, a swipe, a key, or typed text.
    """
    if rc != 0:
        return False
    blob = (text or "").lower()
    if "error:" in blob or "exception" in blob:
        return False
    return True


def _adb_start_server_if_needed(log_fn=None):
    """Ensure adb responds; call ``start-server`` only if needed (less churn than always starting)."""
    exe = adb_executable()
    if not Path(exe).exists() and exe == "adb":
        if log_fn:
            log_fn("  adb not found — downloading minimal platform-tools…\n")
        _ensure_minimal_platform_tools(log_fn=log_fn)
        exe = adb_executable()
    try:
        r = subprocess.run(
            [exe, "version"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=_NO_WIN,
        )
        if r.returncode == 0:
            return
    except (OSError, subprocess.SubprocessError) as e:
        _wiz_debug(f"_adb_start_server_if_needed: adb version probe: {e!r}", None)
    adb("start-server", timeout=12)


def list_adb_devices():
    raw = adb("devices", "-l")
    devices = []
    for line in raw.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2 or parts[1] != "device":
            continue
        serial = parts[0]
        name = serial
        for p in parts[2:]:
            if p.startswith("model:"):
                name = p.split(":", 1)[1].replace("_", " ")
                break
        rec = {"serial": serial, "name": name}
        wm = _parse_wm_size_quick(adb("shell", "wm", "size", serial=serial, timeout=6))
        if wm is not None:
            rec["wm_w"] = int(wm[0])
            rec["wm_h"] = int(wm[1])
            rec["wm_profile_key"] = _profile_key(wm[0], wm[1])
        devices.append(rec)
    return devices


def _wiz_collect_all_adb_serials_for_proxy_cleanup() -> list[str]:
    """Every serial from ``adb devices -l`` (any usual state) plus ``state['phones']``."""
    seen: set[str] = set()
    out: list[str] = []
    raw = adb("devices", "-l")
    for line in raw.splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith("List of"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        s = parts[0].strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    for p in state.get("phones") or []:
        if isinstance(p, dict):
            ser = (p.get("serial") or "").strip()
            if ser and ser not in seen:
                seen.add(ser)
                out.append(ser)
    return out


def wiz_repin_phone_exits() -> tuple[bool, int, str]:
    """Reconnect ADB and re-pin guests onto their own Tor/inject exits.

    Does not delete ``http_proxy`` and does not stop Tor. Clearing those sends
    farm traffic out the VM or host path.
    """
    try:
        from automation.farm_exe_self_heal import (
            adb_live_serials,
            connect_live_fleet,
            heal_inject_and_tor,
        )
    except Exception as exc:
        return False, 0, str(exc)
    notes: list[str] = []
    try:
        notes.extend(connect_live_fleet() or [])
    except Exception as exc:
        notes.append(f"connect_failed:{exc}")
    try:
        live = list(adb_live_serials() or [])
    except Exception as exc:
        return False, 0, str(exc)
    try:
        notes.extend(heal_inject_and_tor(live=live) or [])
    except Exception as exc:
        return False, len(live), str(exc)
    failed = [
        n
        for n in notes
        if "repin_fail" in n or n.startswith("inject_start_err") or n.startswith("connect_failed")
    ]
    if failed:
        return False, len(live), "; ".join(failed)[:400]
    return True, len(live), f"Re-pinned {len(live)} phone(s) onto their own exits."


def wiz_clear_phone_proxies_best_effort(*, stop_tor_host: bool = True) -> int:
    """Re-pin exits. The old body deleted http_proxy and stopped Tor.

    ``stop_tor_host`` is ignored. Clearing the guest proxy is host-IP egress.
    """
    _ = stop_tor_host
    ok, n, _msg = wiz_repin_phone_exits()
    return n if ok else 0


def _adb_devices_tcp_ready_serials(devices_l_output: str):
    """Parse ``adb devices -l`` for TCP serials (``host:port``) already in ``device`` state."""
    lines = []
    serials = []
    for line in (devices_l_output or "").splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        lines.append(line)
        parts = line.split()
        if len(parts) < 2:
            continue
        ser, st = parts[0], parts[1]
        if ":" in ser and st == "device":
            serials.append(ser)
    return len(lines), serials


def _filter_live_adb_serials(serials: list[str]) -> list[str]:
    """Drop cached MuMu serials that no longer answer ``adb shell``."""
    live: list[str] = []
    for serial in serials:
        if not serial:
            continue
        try:
            check = adb("shell", "echo", "ok", serial=serial, timeout=6)
            if check.strip() == "ok":
                live.append(serial)
        except Exception:
            continue
    return live


def find_sdk():
    candidates = [
        os.environ.get("ANDROID_HOME", ""),
        os.environ.get("ANDROID_SDK_ROOT", ""),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk"),
        os.path.expanduser("~/Android/Sdk"),
        os.path.expanduser("~/Library/Android/sdk"),
        "C:/Android/Sdk",
        "C:/Users/Public/Android/Sdk",
    ]
    for p in candidates:
        if p and Path(p, "platform-tools").exists():
            return str(Path(p))
    return ""


def _resolve_sdk_root_auto() -> str:
    """Best-effort Android SDK root (folder containing ``platform-tools``)."""
    for ps in (
        (state.get("sdk_path") or "").strip(),
        find_sdk(),
        (os.environ.get("ANDROID_SDK_ROOT") or "").strip(),
        (os.environ.get("ANDROID_HOME") or "").strip(),
    ):
        if ps and Path(ps, "platform-tools").exists():
            try:
                return str(Path(ps).resolve())
            except OSError as e:
                _wiz_debug(f"_resolve_sdk_root_auto: resolve sdk_path {ps!r}: {e!r}", None)
                return str(Path(ps))
    guess = Path(SDK_DEFAULT_PATH)
    if (guess / "platform-tools").exists():
        try:
            return str(guess.resolve())
        except OSError as e:
            _wiz_debug(f"_resolve_sdk_root_auto: resolve default {guess!r}: {e!r}", None)
            return str(guess)
    # PATH adb → …/platform-tools/adb(.exe) → SDK root (silent discovery on Windows/macOS/Linux)
    try:
        w = shutil.which("adb")
        if w:
            p = Path(w).resolve()
            if p.stem.lower() == "adb" and p.parent.name.lower() == "platform-tools":
                root = p.parent.parent
                if (root / "platform-tools").is_dir():
                    try:
                        return str(root.resolve())
                    except OSError as e:
                        _wiz_debug(f"_resolve_sdk_root_auto: resolve from PATH adb: {e!r}", None)
                        return str(root)
    except OSError as e:
        _wiz_debug(f"_resolve_sdk_root_auto: PATH adb discovery: {e!r}", None)
    return ""


def _maybe_autofill_pharmflow_dir() -> None:
    """If ``pharmflow_dir`` is missing or not a valid install tree, set from install root."""
    d = (state.get("pharmflow_dir") or "").strip()
    if d:
        try:
            p = Path(d).expanduser().resolve()
            if p.is_dir() and (p / "automation" / "dashboard.py").is_file():
                return
        except Exception as e:
            _wiz_debug(f"_maybe_autofill_pharmflow_dir: invalid pharmflow_dir {d!r}: {e!r}", None)
    try:
        root = _pharmflow_install_root()
        if (root / "automation" / "dashboard.py").is_file():
            state["pharmflow_dir"] = str(root.resolve())
    except Exception as e:
        _wiz_debug(f"_maybe_autofill_pharmflow_dir: could not set from install root: {e!r}", None)


def sdk_tool(name):
    sdk = state.get("sdk_path") or find_sdk()
    if not sdk:
        suffix = ".bat" if IS_WIN else ""
        return name + suffix
    base = Path(sdk)
    exts = [".bat", ".cmd", ".exe", ""] if IS_WIN else ["", ".sh"]
    search_dirs = [
        base / "cmdline-tools" / "latest" / "bin",
        base / "cmdline-tools" / "bin",
        base / "emulator",
        base / "platform-tools",
        base / "tools" / "bin",
    ]
    for d in search_dirs:
        for ext in exts:
            p = d / (name + ext)
            if p.exists():
                return str(p)
    return name


def list_avds():
    avdmgr = sdk_tool("avdmanager")
    flags = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
    try:
        r = subprocess.run(
            [avdmgr, "list", "avd", "-c"],
            capture_output=True, text=True, timeout=30,
            env=_sdk_env(), creationflags=flags,
        )
        return [ln.strip() for ln in r.stdout.splitlines()
                if ln.strip() and not ln.startswith("Error")]
    except Exception:
        return []


def _find_java_home() -> str:
    """
    Find an installed JDK/JRE directory on Windows and return its root path.
    Checks JAVA_HOME, then Android Studio's bundled JBR, then common install locations.
    """
    import glob

    # 1. Respect existing JAVA_HOME if valid
    existing = os.environ.get("JAVA_HOME", "")
    if existing and Path(existing, "bin", "java.exe").exists():
        return existing

    # 2. Android Studio bundles a JetBrains Runtime (jbr/) — glob for any version.
    #    AS installs as "Android Studio", "Android Studio3", "Android Studio Panda", etc.
    #    Sort descending so the newest install is tried first.
    as_search_roots = [
        os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), "Android"),
        os.path.join(os.environ.get("LOCALAPPDATA",  ""), "Programs", "Android"),
        os.path.join(os.environ.get("LOCALAPPDATA",  ""), "Programs"),
        os.path.join(os.environ.get("LOCALAPPDATA",  ""), "Google"),
        os.path.join(os.environ.get("LOCALAPPDATA",  ""), "Android"),
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        r"C:\Android",
    ]
    for as_root in as_search_roots:
        if not as_root or not Path(as_root).exists():
            continue
        for studio_dir in sorted(Path(as_root).glob("Android Studio*"), reverse=True):
            jbr = studio_dir / "jbr"
            if (jbr / "bin" / "java.exe").exists():
                return str(jbr)

    # 3. Standard JDK/JRE install locations
    search_roots = [
        os.environ.get("PROGRAMFILES",      r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA",      ""),
        r"C:\Program Files\Microsoft",
        r"C:\Program Files\Eclipse Adoptium",
        r"C:\Program Files\Java",
        r"C:\Program Files\OpenJDK",
    ]
    for root in search_roots:
        if not root:
            continue
        for java_exe in glob.glob(
            os.path.join(root, "**", "bin", "java.exe"), recursive=True
        ):
            return str(Path(java_exe).parent.parent)
    return ""


def _sdk_env() -> dict:
    """
    Return a copy of os.environ with JAVA_HOME, ANDROID_SDK_ROOT, and PATH set
    so sdkmanager and avdmanager can find both Java and the SDK root.
    """
    env = os.environ.copy()
    java_home = _find_java_home()
    if java_home:
        env["JAVA_HOME"] = java_home
        java_bin = str(Path(java_home) / "bin")
        env["PATH"] = java_bin + os.pathsep + env.get("PATH", "")
    sdk = state.get("sdk_path") or find_sdk()
    if sdk:
        env["ANDROID_SDK_ROOT"] = sdk
        env["ANDROID_HOME"]     = sdk
    return env


def _machine_arch():
    """
    Return the Android ABI for the HOST machine.
    On Windows ARM64, Python x64 reports AMD64 via env vars and platform.machine().
    Read the registry system-level PROCESSOR_ARCHITECTURE as ground truth.
    """
    if IS_WIN:
        # 1. Process-level env vars (x64 Python on ARM64 sets ARCHITEW6432=ARM64)
        wow    = os.environ.get("PROCESSOR_ARCHITEW6432", "").upper()
        native = os.environ.get("PROCESSOR_ARCHITECTURE",  "").upper()
        if "ARM" in (wow + native):
            return "arm64-v8a"

        # 2. System-level registry key — always reflects real CPU regardless of emulation
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
            )
            val, _ = winreg.QueryValueEx(key, "PROCESSOR_ARCHITECTURE")
            winreg.CloseKey(key)
            if "ARM" in str(val).upper():
                return "arm64-v8a"
        except Exception:
            pass

        # 3. PowerShell OSArchitecture as last resort
        try:
            r = subprocess.run(
                ["powershell", "-Command",
                 "[System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture"],
                capture_output=True, text=True, timeout=6,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if "ARM" in r.stdout.upper():
                return "arm64-v8a"
        except Exception:
            pass

    m = platform.machine().lower()
    if "arm" in m or "aarch" in m:
        return "arm64-v8a"
    return "x86_64"


def _canonical_sdkmanager(sdk: str) -> str:
    """
    Always return the cmdline-tools/latest/bin/sdkmanager path.
    The legacy tools/bin/sdkmanager only understands XML v3 and will fail
    against Google's current v4 repository — never use it.
    """
    base = Path(sdk)
    ext  = ".bat" if IS_WIN else ""
    primary = base / "cmdline-tools" / "latest" / "bin" / f"sdkmanager{ext}"
    if primary.exists():
        return str(primary)
    # Fallback: any cmdline-tools version (but never tools/bin)
    for p in (base / "cmdline-tools").glob(f"*/bin/sdkmanager{ext}"):
        if p.exists():
            return str(p)
    return str(primary)   # return expected path even if missing (will error clearly)


def _run_sdkmanager(args, sdk, log_fn=None, timeout=900):
    """
    Run sdkmanager, piping 'y' answers so license prompts never block.
    Streams output line-by-line to log_fn if provided.
    Always uses cmdline-tools/latest (XML v4) — never the legacy tools/bin version.
    Injects JAVA_HOME + PATH so sdkmanager finds Java even if PATH not updated yet.
    Returns (success, full_output).
    """
    sdkmgr = _canonical_sdkmanager(sdk)
    # --sdk_root MUST come before the subcommand/packages
    cmd = [sdkmgr, f"--sdk_root={sdk}"] + args
    env = _sdk_env()
    if log_fn:
        log_fn(f"  JAVA_HOME = {env.get('JAVA_HOME', '(not found)')}\n")
        log_fn(f"  $ {' '.join(cmd)}\n")
    flags = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            creationflags=flags,
            encoding="utf-8",
            errors="replace",
        )
        # Feed unlimited 'y' responses so license prompts never block
        try:
            proc.stdin.write("y\n" * 50)
            proc.stdin.close()
        except Exception:
            pass

        lines: list[str] = []
        read_done = threading.Event()

        def _drain_stdout() -> None:
            try:
                for line in proc.stdout:
                    line = line.rstrip()
                    if line and log_fn:
                        log_fn("    " + line + "\n")
                    lines.append(line)
            finally:
                read_done.set()

        reader = threading.Thread(target=_drain_stdout, daemon=True)
        reader.start()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            read_done.wait(timeout=2)
            return False, f"sdkmanager timed out after {timeout} seconds"
        read_done.wait(timeout=5)
        full = "\n".join(lines)
        return proc.returncode == 0, full
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
        return False, f"sdkmanager timed out after {timeout} seconds"
    except Exception as e:
        return False, str(e)


def _direct_download_platform_tools(sdk_path, log_fn=None):
    """
    Download platform-tools directly via Python urllib, bypassinging Java/sdkmanager.
    Uses Google's documented stable URL — no XML parsing needed.
    """
    if IS_WIN:
        url = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
    elif platform.system() == "Darwin":
        url = "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip"
    else:
        url = "https://dl.google.com/android/repository/platform-tools-latest-linux.zip"
    dest = Path(sdk_path)
    tmp  = dest / "_pt_tmp.zip"
    if log_fn:
        log_fn(f"  Downloading platform-tools directly…\n")
    try:
        _urlretrieve(url, tmp, timeout=60)
        with zipfile.ZipFile(tmp, "r") as zf:
            zf.extractall(dest)
        tmp.unlink(missing_ok=True)
        # Google's platform-tools zip ships a remotePackage package.xml.
        # avdmanager needs localPackage format to recognise it as installed.
        _write_local_package_xml(
            dest / "platform-tools" / "package.xml",
            path_id="platform-tools",
            major=35, minor=0, micro=2,
            display="Android SDK Platform-Tools",
            license_ref="android-sdk-license",
            ns_type="ns5:genericDetailsType",
            extra_ns='xmlns:ns3="http://schemas.android.com/repository/android/generic/01"',
        )
        if log_fn:
            log_fn("  platform-tools installed ✅\n")
        return True
    except Exception as e:
        if log_fn:
            log_fn(f"  ❌  platform-tools direct download failed: {e}\n")
        tmp.unlink(missing_ok=True)
        return False


_arm64_adb_warned = False


def _pe_machine_type(exe_path: str) -> int:
    """Read Windows PE machine type. Returns 0xAA64 for ARM64, 0x8664 for x64, 0 on error."""
    try:
        with open(exe_path, "rb") as f:
            if f.read(2) != b"MZ":
                return 0
            f.seek(0x3C)
            pe_off = int.from_bytes(f.read(4), "little")
            f.seek(pe_off)
            if f.read(4) != b"PE\x00\x00":
                return 0
            return int.from_bytes(f.read(2), "little")
    except Exception:
        return 0


def _warn_arm64_x64_adb(log_fn) -> None:
    """If the host is Windows ARM64 but ``adb.exe`` is x64, log one Prism-emulation note."""
    global _arm64_adb_warned
    if not log_fn or not IS_WIN or _arm64_adb_warned:
        return
    if "arm64" not in _machine_arch():
        return
    exe = adb_executable()
    if not exe or not Path(exe).exists():
        return
    if _pe_machine_type(exe) != 0x8664:
        return
    _arm64_adb_warned = True
    log_fn(
        "  Note: adb.exe is x64 — on ARM64 Windows it runs under Prism emulation "
        "(may be slower than a native ARM64 build).\n"
    )


# Official downloads hub (pick Windows vs Windows ARM); windows-arm.html previously 404'd.
MUMU_DOWNLOAD_URL = "https://www.mumuglobal.com/download"

# MuMu only forwards ADB from the host after it is enabled *per instance* (settings / device info).
MUMU_ADB_PER_INSTANCE_HINT = (
    "In each MuMu phone: open Settings (≡ or gear) and turn on ADB / USB debugging "
    "(wording varies — sometimes under Other or Device information). "
    "Without this, the PC cannot connect."
)

# Module-level MuMu ADB / instance cache (``_connect_mumu_phones`` may run on worker threads).
# Verbose MuMu/ADB trace lines: set PHARMFLOW_WIZARD_DEBUG=1 in the environment before launching.
MUMU_INSTANCES_CACHE_TTL_S = 8.0
MUMU_CONNECT_COOLDOWN_S = 3.0
_mumu_connect_lock = threading.Lock()
_mumu_inst_cache_key: str | None = None
_mumu_inst_cache_val: list | None = None
_mumu_inst_cache_mono: float = 0.0
_last_mumu_connected_serials: list = []
_last_mumu_connect_mono: float = 0.0


def _wiz_debug_enabled() -> bool:
    for key in ("PHARMFLOW_WIZARD_DEBUG", "PHARMFLOW_WIZ_DEBUG"):
        v = os.environ.get(key, "").strip().lower()
        if v and v not in ("0", "false", "no", "off"):
            return True
    return False


def _wiz_dbg_path(p) -> str:
    """Short path for debug logs (reduces noise; avoids dumping full user paths)."""
    if p is None:
        return "(none)"
    try:
        path = Path(p)
        name = path.name or str(path)
        par = path.parent.name
        if par and par not in (".", "/", "\\") and path.parent != path:
            return f"{par}/{name}"
        return name
    except Exception:
        return "(path)"


def _wiz_debug(msg: str, log_fn=None) -> None:
    if not _wiz_debug_enabled():
        return
    line = f"[dbg] {msg}\n"
    if log_fn:
        log_fn(line)
    else:
        try:
            print(line, end="", file=sys.stderr)
        except Exception:
            pass


def _mumu_install_root(mgr_path) -> Path:
    """Directory that contains MuMuPlayer.exe (parent of shell/nx_main)."""
    p = Path(mgr_path)
    if p.parent.name.lower() in ("shell", "nx_main"):
        return p.parent.parent
    return p.parent


def _glob_mumu_manager(max_dirs=160):
    """Search for nemux-shell-winui.Manager.exe or MuMuManager.exe under MuMu install trees."""
    roots = []
    for base_var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA", "PROGRAMW6432"):
        base = os.environ.get(base_var, "")
        if not base:
            continue
        base_path = Path(base)
        for child in ("Netease", "MuMuPlayer", "MuMuPlayerARM"):
            d = base_path / child
            if d.is_dir():
                roots.append(d)
        try:
            for d in base_path.glob("MuMu*"):
                if d.is_dir():
                    roots.append(d)
        except Exception:
            pass
    seen_paths = set()
    seen_roots = set()
    for root in roots:
        if root in seen_roots:
            continue
        seen_roots.add(root)
        for exe_name in MUMU_MANAGER_EXES:
            try:
                for i, p in enumerate(root.rglob(exe_name)):
                    if i >= max_dirs:
                        break
                    if p.is_file():
                        rp = str(p.resolve())
                        if rp not in seen_paths:
                            seen_paths.add(rp)
                            yield p
            except Exception:
                pass


def _find_mumu_manager():
    """Return path to MuMu shell CLI (nemux-shell-winui.Manager.exe preferred), or None.

    Search order:
      1. User-browsed path stored in state["mumu_mgr_path"]
      2. 'where' for nemux-shell-winui.Manager.exe / MuMuManager.exe (PATH)
      3. Windows registry Uninstall entries for any "MuMu" product
      4. Standard filesystem candidates under PROGRAMFILES / LOCALAPPDATA
      5. Shallow glob under Netease / MuMu* folders
    """
    if not IS_WIN:
        _wiz_debug("find_mumu_manager: not Windows", None)
        return None

    # 1. User manually selected path
    cached = state.get("mumu_mgr_path", "")
    if cached:
        p = Path(cached)
        if p.exists() and _is_mumu_manager_cli_path(p):
            _wiz_debug(f"find_mumu_manager: state mumu_mgr_path hit {_wiz_dbg_path(p)}", None)
            return p

    candidates = []

    # 2. 'where' command — works if MuMu install dir is on PATH
    for query in (
        MUMU_MANAGER_PRIMARY,
        MUMU_MANAGER_LEGACY,
        "nemux-shell-winui.Manager",
        "MuMuManager",
    ):
        try:
            r = subprocess.run(
                ["where", query],
                capture_output=True, text=True, timeout=8,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if r.returncode == 0:
                for line in (r.stdout + r.stderr).strip().splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    p = Path(line)
                    if p.exists() and _is_mumu_manager_cli_path(p):
                        candidates.insert(0, p)
        except Exception:
            pass

    # 3. Registry Uninstall entries
    try:
        import winreg
        reg_roots = [
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        for hive, reg_path in reg_roots:
            try:
                key = winreg.OpenKey(hive, reg_path)
                i = 0
                while True:
                    try:
                        sub_name = winreg.EnumKey(key, i)
                        i += 1
                        sub = winreg.OpenKey(key, sub_name)
                        try:
                            name_val = winreg.QueryValueEx(sub, "DisplayName")[0]
                            if "mumu" in name_val.lower():
                                for val_name in ("InstallLocation", "InstallDir"):
                                    try:
                                        loc = Path(winreg.QueryValueEx(sub, val_name)[0])
                                        for sub_dir in ("shell", "nx_main", ""):
                                            for exe_name in MUMU_MANAGER_EXES:
                                                exe = (
                                                    loc / sub_dir / exe_name
                                                    if sub_dir
                                                    else loc / exe_name
                                                )
                                                candidates.append(exe)
                                    except OSError:
                                        pass
                        except OSError:
                            pass
                        winreg.CloseKey(sub)
                    except OSError:
                        break
                winreg.CloseKey(key)
            except OSError:
                pass
    except ImportError:
        pass

    # 4. Filesystem candidates (prefer nemux CLI, then legacy)
    for base_var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA", "PROGRAMW6432"):
        base = os.environ.get(base_var, "")
        if not base:
            continue
        for folder in (
            "Netease\\MuMuPlayerARM",
            "Netease\\MuMuPlayer-12.0",
            "Netease\\MuMuPlayerGlobal-12.0",
            "Netease\\MuMuPlayer",
            "MuMuPlayerARM",
            "MuMuPlayer-12.0",
            "MuMuPlayer",
        ):
            root = Path(base) / folder
            for sub_dir in ("shell", "nx_main", ""):
                for exe_name in MUMU_MANAGER_EXES:
                    candidates.append(
                        root / sub_dir / exe_name if sub_dir
                        else root / exe_name
                    )

    for p in candidates:
        if p.exists() and _is_mumu_manager_cli_path(p):
            _wiz_debug(f"find_mumu_manager: fixed candidate {_wiz_dbg_path(p)}", None)
            return p

    # 5. Discovery search (new install paths / renamed folders)
    try:
        for p in _glob_mumu_manager():
            if _is_mumu_manager_cli_path(p):
                _wiz_debug(f"find_mumu_manager: glob hit {_wiz_dbg_path(p)}", None)
                return p
    except Exception as e:
        _wiz_debug(f"find_mumu_manager: glob error {e!r}", None)
    _wiz_debug("find_mumu_manager: not found", None)
    return None


def _mumu_browse_initialdir() -> str | None:
    """Initial folder for MuMu Manager ``.exe`` file dialogs (state, discovery, or Netease)."""
    cached = (state.get("mumu_mgr_path") or "").strip()
    if cached:
        p = Path(cached)
        par = p.parent if p.is_file() else p
        if par.is_dir():
            return str(par)
    mgr = _find_mumu_manager()
    if mgr:
        par = Path(mgr).parent
        if par.is_dir():
            return str(par)
    for base_var in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(base_var, "")
        if not base:
            continue
        d = Path(base) / "Netease"
        if d.is_dir():
            return str(d)
    return None


def _mumu_parse_json_output(out: str):
    """MuMu shell CLI sometimes prints banners; extract the JSON object or array."""
    s = (out or "").strip()
    if not s:
        return None
    if s.startswith("{") or s.startswith("["):
        try:
            return json.loads(s)
        except Exception:
            pass
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        i = s.find(open_ch)
        j = s.rfind(close_ch)
        if i >= 0 and j > i:
            try:
                return json.loads(s[i : j + 1])
            except Exception:
                continue
    # Nemux / newer builds often mix log lines ("info: g.gX…", "App … Redirect") with JSON.
    for blob in _mumu_iter_json_blobs(s):
        try:
            return json.loads(blob)
        except Exception:
            continue
    return None


def _mumu_iter_json_blobs(text: str):
    """Yield balanced `{…}` / `[…]` substrings — finds JSON embedded in noisy CLI logs."""
    if not text:
        return
    i = 0
    n = len(text)
    while i < n:
        if text[i] not in "{[":
            i += 1
            continue
        opener, closer = text[i], "}" if text[i] == "{" else "]"
        depth = 0
        start = i
        for j in range(i, n):
            c = text[j]
            if c == opener:
                depth += 1
            elif c == closer:
                depth -= 1
                if depth == 0:
                    yield text[start : j + 1]
                    i = j + 1
                    break
        else:
            i += 1


def _mumu_shell_manager_fallback(nemux_path: Path) -> Path | None:
    """Locate legacy ``MuMuManager.exe`` when ``nemux-shell-winui.Manager.exe`` prints log spam only.

    Layout differs by MuMu build: ``shell\\``, ``nx_main\\``, ``manager\\``, or alongside nemux.
    """
    nemux_path = nemux_path.resolve()
    root = nemux_path.parent.parent
    managers = ("MuMuManager.exe", MUMU_MANAGER_LEGACY)

    for mid in ("shell", "nx_main", "manager"):
        for name in managers:
            p = root / mid / name
            if p.is_file():
                return p

    for name in managers:
        p = nemux_path.parent / name
        if p.is_file():
            return p

    # Last resort: shallow search (some installs nest extras under locale or version dirs).
    try:
        for p in root.rglob("MuMuManager.exe"):
            if p.is_file() and p.stat().st_size > 10_000:
                return p
    except OSError:
        pass

    return None


def _mumu_adb_port(d: dict):
    for k in ("adb_port", "adb_host_port", "port", "AdbPort", "adbPort"):
        v = d.get(k)
        if v is None:
            continue
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    return None


def _mumu_run_capture(mgr_path, *args, timeout=15, log_fn=None):
    """Run MuMu CLI; return (ok, stdout, stderr). Nemux often puts JSON only on one stream."""
    mgr_path = Path(mgr_path)
    cwd = str(mgr_path.parent)
    flags = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
    try:
        r = subprocess.run(
            [str(mgr_path)] + list(args),
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=flags,
            cwd=cwd,
            encoding="utf-8",
            errors="replace",
        )
        ok = r.returncode == 0
        _wiz_debug(
            f"mumu_run_capture exe={_wiz_dbg_path(mgr_path)} args={list(args)!r} rc={r.returncode} "
            f"out_len={len(r.stdout or '')} err_len={len(r.stderr or '')}",
            log_fn,
        )
        return ok, (r.stdout or ""), (r.stderr or "")
    except Exception as e:
        _wiz_debug(
            f"mumu_run_capture FAILED exe={_wiz_dbg_path(mgr_path)} args={list(args)!r} err={e!r}",
            log_fn,
        )
        return False, "", str(e)


def _mumu_run(mgr_path, *args, timeout=15):
    """Run MuMu shell CLI — returns (ok, combined_stdout_stderr)."""
    ok, out, err = _mumu_run_capture(mgr_path, *args, timeout=timeout)
    return ok, (out + "\n" + err).strip()


def _instances_append_from_info_json(data, instances: list) -> None:
    """Parse MuMu ``info`` JSON into instance dicts (mutates ``instances``)."""

    def _parse_one(d):
        if not isinstance(d, dict):
            return
        ip = str(d.get("adb_host_ip") or d.get("ip") or "").strip()
        port = _mumu_adb_port(d)
        if port is None:
            return
        idx = d.get("index", 0)
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            idx = 0
        # A missing host is not this PC's loopback. ARM MuMu publishes
        # 10.0.2.x in state.json. Inventing 127.0.0.1 hides that serial.
        serial = f"{ip}:{port}" if ip else ""
        instances.append({
            "index":      idx,
            "name":       d.get("name") or d.get("vm_name") or f"MuMu-{idx}",
            "adb_serial": serial,
            "started":    bool(d.get("is_android_started") or d.get("started")),
        })

    if isinstance(data, dict):
        if any(k in data for k in ("index", "adb_port")) or _mumu_adb_port(data) is not None:
            _parse_one(data)
        else:
            for v in data.values():
                if isinstance(v, dict):
                    _parse_one(v)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                _parse_one(item)


def _prefer_mumu_serial(current: str, incoming: str) -> str:
    """Keep a published guest serial over an invented loopback serial."""
    cur = str(current or "").strip()
    inc = str(incoming or "").strip()
    if not cur:
        return inc
    if not inc:
        return cur
    if cur.startswith("127.0.0.1:") and inc.startswith("10.0.2."):
        return inc
    return cur


def _merge_mumu_instances(primary: list, extra: list) -> list:
    """Union MuMu instance rows by index. ``extra`` fills indexes primary missed.

    A CLI row that names 127.0.0.1 does not hide the state.json 10.0.2.x serial
    for that same index. Classic boot was connecting a port this ARM host does not publish.
    """
    out = [row for row in primary if isinstance(row, dict)]
    seen = set()
    for row in out:
        try:
            seen.add(int(row.get("index")))
        except (TypeError, ValueError):
            continue
    for row in extra:
        if not isinstance(row, dict):
            continue
        try:
            idx = int(row.get("index"))
        except (TypeError, ValueError):
            continue
        if idx in seen:
            for row_out in out:
                try:
                    out_idx = int(row_out.get("index"))
                except (TypeError, ValueError):
                    continue
                if out_idx != idx:
                    continue
                row_out["adb_serial"] = _prefer_mumu_serial(
                    str(row_out.get("adb_serial") or ""),
                    str(row.get("adb_serial") or ""),
                )
                if row.get("started") and not row_out.get("started"):
                    row_out["started"] = True
                break
            continue
        out.append(row)
        seen.add(idx)
    return out


def _mumu_instances_from_disk(log_fn=None) -> list:
    """Every MuMu VM folder. Not a 0–15 probe."""
    found: list = []
    try:
        from mumu_farm_ops import MuMuFarmOps

        live = set()
        try:
            raw = adb("devices", "-l", timeout=10)
            for line in raw.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    live.add(parts[0])
        except Exception as exc:  # noqa: BLE001
            _wiz_debug(f"mumu disk listing adb devices probe failed: {exc}", log_fn)

        ops = MuMuFarmOps()
        vms_dir = getattr(ops, "vms_dir", None)
        try:
            from automation.mumu_shell_cli import instance_shell_running
        except Exception:  # noqa: BLE001
            instance_shell_running = None

        for _inst in ops.list_instances() or []:
            idx = int(getattr(_inst, "index", 0) or 0)
            name = str(getattr(_inst, "name", "") or "")
            serial = str(getattr(_inst, "adb_serial", "") or "")
            started = bool(getattr(_inst, "running", False)) or (
                bool(serial) and serial in live
            )
            if instance_shell_running is not None:
                try:
                    if instance_shell_running(idx):
                        started = True
                except Exception:  # noqa: BLE001
                    pass
            if vms_dir is not None and name:
                state_path = Path(vms_dir) / name / "misc" / "state.json"
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8-sig"))
                    host = str(state.get("AdbHost") or "").strip()
                    port = str(state.get("AdbPort") or "5555").strip()
                    if host.startswith("10.0.2."):
                        serial = f"{host}:{port}"
                        if serial in live:
                            started = True
                except (OSError, ValueError, TypeError):
                    pass
            found.append(
                {
                    "index": idx,
                    "name": name or f"MuMu-{idx}",
                    "adb_serial": serial,
                    "started": started,
                }
            )
    except Exception as exc:  # noqa: BLE001 — best-effort fallback
        _wiz_debug(f"mumu disk listing failed: {exc}", log_fn)
    return found


def _mumu_probe_indexes_until_gap(exes: list, log_fn=None) -> list:
    """Ask the CLI for indexes until replies stop. A gap is the end of the list, not a phone cap."""
    found: list = []
    misses = 0
    idx = 0
    while misses < 4:
        progressed = False
        for exe in exes:
            ok, so, se = _mumu_run_capture(
                exe, "info", "-v", str(idx), timeout=10, log_fn=log_fn
            )
            del ok
            blob = (so + "\n" + se).strip()
            if not blob:
                continue
            data = _mumu_parse_json_output(blob)
            if data is None:
                continue
            before = len(found)
            _instances_append_from_info_json(data, found)
            added = found[before:]
            if any(int(row.get("index", -1)) == idx for row in added):
                progressed = True
                break
        if progressed:
            misses = 0
        else:
            misses += 1
        idx += 1
    return found


def _mumu_get_instances(mgr_path, log_fn=None):
    """Return list of dicts: {index, name, adb_serial, started}.

    Tries ``nemux-shell-winui.Manager.exe`` and ``shell\\MuMuManager.exe`` (JSON ``info``
    often works only on the legacy shell binary). A partial CLI list is merged with
    every VM folder on disk. Index probing is only the last resort, and it stops
    on a gap — it does not stop at phone 16.
    """
    _wiz_debug(f"mumu_get_instances start mgr={_wiz_dbg_path(mgr_path)}", log_fn)
    mgr_path = Path(mgr_path)
    fb = _mumu_shell_manager_fallback(mgr_path)
    exes: list[Path] = [mgr_path]
    if fb and fb.resolve() != mgr_path.resolve():
        exes.append(fb)
    # Never execute a GUI-only manager (nemux-shell-winui.Manager.exe): running it
    # opens the MuMu Player manager window. Discovery falls back to the legacy
    # shell CLI below or, when none exists, the caller's ADB port scan.
    gui_only = [e for e in exes if _is_gui_only_manager(e)]
    if gui_only:
        exes = [e for e in exes if not _is_gui_only_manager(e)]
        if log_fn:
            log_fn(
                "  Skipping GUI-only MuMu manager (would open the MuMu window); "
                "using shell CLI / config files / ADB port scan instead.\n"
            )
        _wiz_debug(f"mumu_get_instances dropped GUI-only managers: {[e.name for e in gui_only]}", log_fn)
    if log_fn:
        install_root = mgr_path.resolve().parent.parent
        if fb is None:
            log_fn(
                "  Fallback not found: no MuMuManager.exe under shell\\, nx_main\\, or manager\\ "
                f"(install root {install_root}). JSON-only discovery needs legacy CLI or working ADB ports.\n"
            )
        elif fb.resolve() != mgr_path.resolve():
            log_fn(f"  Shell fallback will run after primary if needed: {fb}\n")

    instances: list = []

    for ei, exe in enumerate(exes):
        if ei > 0 and log_fn:
            log_fn(f"  Trying fallback: {exe}\n")
        tag = exe.name
        # 1) info -v all — try stdout, stderr, merge (nemux may spam GUI logs without JSON).
        ok, so, se = _mumu_run_capture(
            exe, "info", "-v", "all", timeout=18, log_fn=log_fn
        )
        if log_fn:
            comb = (so + "\n" + se).strip()
            log_fn(
                f"  Manager CLI ({tag}) rc={ok} out={repr(comb[:320]) if comb else '(empty)'}\n"
            )
        for blob in (so + "\n" + se, so, se):
            data = _mumu_parse_json_output(blob)
            if data is not None:
                _instances_append_from_info_json(data, instances)
        if instances:
            if log_fn and exe != mgr_path:
                log_fn(f"  Using JSON from fallback: {exe}\n")
            break

    disk = _mumu_instances_from_disk(log_fn)
    if disk:
        if log_fn and not instances:
            log_fn(
                "  CLI returned no MuMu instances — reading VMs from config "
                "files (no window opened)...\n"
            )
        instances = _merge_mumu_instances(instances, disk)
    if not instances and exes:
        if log_fn:
            log_fn("  CLI and disk listing were empty — probing indexes until the replies stop…\n")
        instances = _mumu_probe_indexes_until_gap(exes, log_fn)
    if not instances and log_fn:
        log_fn(
            "  Could not parse JSON from manager output — "
            "will rely on adb port scan.\n"
        )

    # Dedupe by adb_serial
    seen = set()
    uniq = []
    for inst in sorted(instances, key=lambda x: x["index"]):
        s = inst["adb_serial"]
        if s not in seen:
            seen.add(s)
            uniq.append(inst)
    _wiz_debug(f"mumu_get_instances return n={len(uniq)}", log_fn)
    return uniq


def _mumu_get_instances_cached(mgr_path, log_fn=None):
    """TTL cache so Connect & boot UI + ADB connect don't each spawn a full nemux CLI sweep."""
    global _mumu_inst_cache_key, _mumu_inst_cache_val, _mumu_inst_cache_mono
    if not mgr_path:
        _wiz_debug("instances_cached: no mgr_path", log_fn)
        return _mumu_get_instances(mgr_path, log_fn=log_fn)
    key = str(Path(mgr_path).resolve())
    now = time.monotonic()
    if (
        _mumu_inst_cache_key == key
        and _mumu_inst_cache_val is not None
        and now - _mumu_inst_cache_mono < MUMU_INSTANCES_CACHE_TTL_S
    ):
        n = len(_mumu_inst_cache_val)
        _wiz_debug(
            f"instances_cached HIT age={now - _mumu_inst_cache_mono:.2f}s n={n}", log_fn
        )
        return list(_mumu_inst_cache_val)
    _wiz_debug("instances_cached MISS", log_fn)
    val = _mumu_get_instances(mgr_path, log_fn=log_fn)
    _mumu_inst_cache_key = key
    _mumu_inst_cache_val = val
    _mumu_inst_cache_mono = now
    return list(val)


def _mumu_launch(mgr_path, index, log_fn=None):
    """Launch a MuMuPlayer instance by index.

    GUI-only managers (nemux-shell-winui.Manager.exe) are never executed —
    they would open the MuMu manager window instead of a phone. Prefer the
    legacy shell CLI, then the ARM shell launcher, before giving up.
    """
    if log_fn:
        log_fn(f"  Launching MuMu instance {index}…\n")
    mgr_path = Path(mgr_path)
    if _is_gui_only_manager(mgr_path):
        fb = _mumu_shell_manager_fallback(mgr_path)
        if fb:
            if log_fn:
                log_fn(f"  Using shell CLI fallback: {fb.name}\n")
            mgr_path = fb
        else:
            if log_fn:
                log_fn(
                    "  GUI-only manager without shell CLI — using ARM shell launcher...\n"
                )
            try:
                from automation.mumu_shell_cli import launch_instance_index

                return launch_instance_index(int(index), timeout=120.0)[0]
            except Exception as exc:  # noqa: BLE001
                if log_fn:
                    log_fn(f"  ARM shell launch failed: {exc}\n")
                return False
    ok, out = _mumu_run(mgr_path, "control", "-v", str(index), "launch", timeout=30)
    return ok


def _connect_mumu_phones(count=0, log_fn=None, *, force_full_scan=False):
    """Connect to MuMuPlayer instances via MuMu shell CLI + published guests.

    ``count`` is ignored. Stopping at 16 dropped phones whose guest serial was
    not in the first localhost sweep. Returns every serial that answers ADB.
    """
    global _last_mumu_connected_serials, _last_mumu_connect_mono

    now = time.monotonic()
    cd_age = (
        (now - _last_mumu_connect_mono)
        if _last_mumu_connect_mono
        else None
    )
    _wiz_debug(
        f"connect_mumu_phones enter count={count} force_full_scan={force_full_scan} "
        f"cooldown_age={cd_age!s} have_cached={bool(_last_mumu_connected_serials)}",
        log_fn,
    )
    if (
        not force_full_scan
        and _last_mumu_connected_serials
        and now - _last_mumu_connect_mono < MUMU_CONNECT_COOLDOWN_S
    ):
        live = _filter_live_adb_serials(_last_mumu_connected_serials)
        if live:
            _wiz_debug(
                f"connect skip cooldown age={now - _last_mumu_connect_mono:.3f}s "
                f"n_cached_serials={len(live)}",
                log_fn,
            )
            if log_fn:
                log_fn(
                    "  (MuMu ADB scan skipped — recent connect still valid; "
                    'use \"Start all phones\" to force a full rescan)\n'
                )
            return live

    if not _mumu_connect_lock.acquire(blocking=False):
        _wiz_debug("connect lock acquire failed (another connect in progress)", log_fn)
        if log_fn:
            log_fn("  (ADB scan skipped — another MuMu connect is already running)\n")
        return _filter_live_adb_serials(list(_last_mumu_connected_serials))

    try:
        _wiz_debug("connect lock acquired → _connect_mumu_phones_impl", log_fn)
        return _connect_mumu_phones_impl(count, log_fn=log_fn)
    finally:
        _mumu_connect_lock.release()
        _wiz_debug("connect lock released", log_fn)


def _connect_mumu_phones_impl(count=16, log_fn=None):
    """Internal: single-flight caller holds ``_mumu_connect_lock``."""
    global _last_mumu_connected_serials, _last_mumu_connect_mono

    exe = adb_executable()
    exe_path = Path(exe)
    exe_exists = exe_path.exists()
    _wiz_debug(
        f"connect_impl enter count={count} adb_exe={_wiz_dbg_path(exe)} exists={exe_exists} "
        f"is_bare_adb_name={exe == 'adb'}",
        log_fn,
    )
    if not exe_exists and exe == "adb":
        _wiz_debug("_ensure_minimal_platform_tools (bare adb, path missing)", log_fn)
        if log_fn:
            log_fn("  adb not found — downloading minimal platform-tools…\n")
        _ensure_minimal_platform_tools(log_fn=log_fn)
        exe2 = adb_executable()
        _wiz_debug(
            f"after ensure adb_exe={_wiz_dbg_path(exe2)} exists={Path(exe2).exists()}",
            log_fn,
        )

    # Ensure the adb daemon is running. Do **not** call ``adb kill-server`` here — it
    # tears down *all* adb TCP sessions on this PC (other terminals, IDE, etc.).
    _adb_start_server_if_needed(log_fn=log_fn)
    _wiz_debug("adb_start_server_if_needed returned", log_fn)

    devices_raw = adb("devices", "-l", timeout=12)
    n_dev_lines, tcp_ready = _adb_devices_tcp_ready_serials(devices_raw)
    _wiz_debug(
        f"adb devices -l parse n_lines={n_dev_lines} tcp_ready={len(tcp_ready)}",
        log_fn,
    )
    if log_fn:
        log_fn(
            f"  adb devices -l: {n_dev_lines} device line(s), "
            f"{len(tcp_ready)} TCP host:port in device state\n"
        )

    _warn_arm64_x64_adb(log_fn)

    mgr = _find_mumu_manager()
    _wiz_debug(f"mgr_found={bool(mgr)} mgr_exe={_wiz_dbg_path(mgr)}", log_fn)
    connected = []
    tried_serials = set()

    _wiz_debug(f"reuse listed tcp devices pass n_tcp={len(tcp_ready)}", log_fn)
    for serial in tcp_ready:
        if serial in tried_serials:
            _wiz_debug(f"tcp_skip duplicate serial={serial}", log_fn)
            continue
        tried_serials.add(serial)
        check = adb("shell", "echo", "ok", serial=serial, timeout=6)
        ok_shell = check.strip() == "ok"
        _wiz_debug(f"tcp listed serial={serial} shell_ok={ok_shell}", log_fn)
        if ok_shell:
            connected.append(serial)
            if log_fn:
                log_fn(f"  ✅ using listed TCP device: {serial}\n")

    if mgr:
        if log_fn:
            log_fn(f"  MuMu CLI found ({Path(mgr).name}): {mgr}\n")
        instances = _mumu_get_instances_cached(mgr, log_fn=log_fn)
        _wiz_debug(f"instances from cli/cache n={len(instances)}", log_fn)
        if log_fn:
            log_fn(f"  Instances from MuMu CLI: {len(instances)}\n")
        for inst in instances:
            serial = inst["adb_serial"]
            name = inst.get("name", "")
            tried_serials.add(serial)
            _wiz_debug(f"adb connect try serial={serial} name={name!r}", log_fn)
            out = adb("connect", serial, timeout=8)
            hint_ok = "connected" in out.lower() or "already" in out.lower()
            _wiz_debug(
                f"adb connect out serial={serial} ok_hint={hint_ok} out_len={len(out or '')}",
                log_fn,
            )
            if log_fn:
                log_fn(f"  adb connect {serial}: {out or '(no output)'}\n")
            if hint_ok:
                check = adb("shell", "echo", "ok", serial=serial, timeout=6)
                shell2 = check.strip() == "ok"
                _wiz_debug(f"post-connect shell serial={serial} ok={shell2}", log_fn)
                if shell2:
                    connected.append(serial)
                    if log_fn:
                        log_fn(f"  ✅ {inst['name']}: {serial}\n")
            else:
                _wiz_debug(f"adb connect no success token serial={serial}", log_fn)
    else:
        _wiz_debug("no MuMu manager CLI — CLI branch skipped; port scan next", log_fn)
        if log_fn:
            log_fn("  MuMu shell CLI not found — using port scan fallback\n")

    # CLI found nothing. Attach every published guest, not a 16- or 48-port
    # localhost sweep. ``count`` is ignored: a phone-count ceiling drops live VMs.
    if not connected:
        try:
            from automation.farm_canonical_phones import _fleet_from_disk

            disk_fleet = _fleet_from_disk()
        except Exception as exc:  # noqa: BLE001
            disk_fleet = {}
            _wiz_debug(f"disk fleet unavailable: {exc}", log_fn)
        _wiz_debug(
            f"guest attach begin n_vms={len(disk_fleet)} connected_before={len(connected)}",
            log_fn,
        )
        for name, raw_serial in disk_fleet.items():
            serial = str(raw_serial or "").strip()
            if not serial:
                m_idx = re.match(r"^vm(\d+)", str(name), re.IGNORECASE)
                if not m_idx:
                    continue
                serial = f"127.0.0.1:{16384 + int(m_idx.group(1)) * 32}"
            if serial in tried_serials or serial in connected:
                continue
            tried_serials.add(serial)
            out = adb("connect", serial, timeout=4)
            low = (out or "").lower()
            if "connected" not in low and "already" not in low:
                continue
            check = adb("shell", "echo", "ok", serial=serial, timeout=5)
            if check.strip() != "ok":
                continue
            connected.append(serial)
            _wiz_debug(f"guest attach hit {name} {serial}", log_fn)
            if log_fn:
                log_fn(f"  ✅ guest attach: {serial}\n")
    elif log_fn:
        log_fn(f"  Skipping guest attach — {len(connected)} phone(s) already connected.\n")

    _last_mumu_connected_serials = connected
    _last_mumu_connect_mono = time.monotonic()
    _wiz_debug(f"connect_impl exit n_connected={len(connected)}", log_fn)
    return connected


def _direct_download_emulator(sdk_path, log_fn=None):
    """
    Download emulator directly via Python urllib, bypassing Java/sdkmanager.
    On ARM64 Windows: preserves an existing ARM64 emulator binary and tries to
    download the ARM64 build before falling back to x64 (which cannot run arm64-v8a).
    """
    import xml.etree.ElementTree as ET
    REPO_XML = "https://dl.google.com/android/repository/repository2-3.xml"
    BASE_URL = "https://dl.google.com/android/repository/"

    host_is_arm64 = IS_WIN and "arm64" in _machine_arch()

    # If an ARM64 emulator binary already exists (e.g. installed by Android Studio),
    # don't overwrite it with an x64 binary that can't run arm64-v8a images.
    emu_exe = Path(sdk_path) / "emulator" / "emulator.exe"
    if host_is_arm64 and emu_exe.exists():
        machine = _pe_machine_type(str(emu_exe))
        if machine == 0xAA64:
            if log_fn:
                log_fn("  ARM64 emulator already installed — skipping download ✅\n")
            return True
        if log_fn:
            log_fn("  Existing emulator is x64; will try to replace with ARM64 build.\n")

    if log_fn:
        log_fn("  Fetching SDK catalog via Python (bypassing Java network)…\n")
    try:
        with urllib.request.urlopen(REPO_XML, timeout=30) as r:
            xml_data = r.read().decode("utf-8")
    except Exception as e:
        if log_fn:
            log_fn(f"  ❌  Cannot reach dl.google.com from Python either: {e}\n")
            log_fn("      Your network is blocking Google entirely.\n")
            log_fn("      Check VPN, proxy, or router DNS settings.\n")
        return False

    x64_url = None
    arm64_url = None
    try:
        root = ET.fromstring(xml_data)
        for pkg in root.iter():
            if pkg.get("path") == "emulator":
                for archive in pkg.iter():
                    tag = archive.tag.split("}")[-1] if "}" in archive.tag else archive.tag
                    if tag == "url":
                        val = (archive.text or "").strip()
                        if val.endswith(".zip") and "windows" in val:
                            if "aarch64" in val or "arm64" in val:
                                arm64_url = BASE_URL + val
                            elif "x64" in val:
                                x64_url = BASE_URL + val
                            elif not x64_url:
                                x64_url = BASE_URL + val
                if x64_url or arm64_url:
                    break
    except ET.ParseError:
        pass

    if not x64_url and not arm64_url:
        all_win = re.findall(r"emulator-windows[^\"<\s]+\.zip", xml_data)
        for m in all_win:
            if "aarch64" in m or "arm64" in m:
                arm64_url = BASE_URL + m
            elif "x64" in m and not x64_url:
                x64_url = BASE_URL + m
        if not x64_url and not arm64_url and all_win:
            x64_url = BASE_URL + all_win[-1]

    # On ARM64 Windows: try substituting aarch64 into x64 URL if no ARM64 found in XML.
    # Google sometimes publishes ARM64 builds at the same build number under a different filename.
    if host_is_arm64 and not arm64_url and x64_url:
        candidate = re.sub(r"emulator-windows_x64-", "emulator-windows_aarch64-", x64_url)
        if candidate != x64_url:
            try:
                req = urllib.request.Request(candidate, method="HEAD")
                with urllib.request.urlopen(req, timeout=10):
                    arm64_url = candidate
                    if log_fn:
                        log_fn(f"  ARM64 emulator build found on CDN: {arm64_url}\n")
            except Exception:
                pass

    if host_is_arm64:
        if not arm64_url:
            if log_fn:
                log_fn(
                    "  ❌  Google does not publish a Windows ARM64 Android Emulator.\n"
                    "     Even Android Studio for Windows ARM64 downloads only the x64\n"
                    "     emulator — there is no ARM64 emulator binary available from Google.\n\n"
                    "  ✅  Use MuMuPlayer for Windows ARM instead:\n"
                    "     MuMuPlayer is a free Android emulator with native ARM64 Windows\n"
                    "     support, multi-instance, and full ADB access — exactly what\n"
                    "     PharmFlow needs.\n\n"
                    "  How to set up (wizard handles connection automatically):\n"
                    "     1. Download MuMuPlayer for Windows ARM:\n"
                    f"        {MUMU_DOWNLOAD_URL}\n"
                    "     2. Install MuMuPlayer ARM and open it.\n"
                    "     3. Use MuMuPlayer's multi-instance manager to create your phones.\n"
                    "     4. Keep MuMuPlayer running, then open Connect & boot in this wizard.\n"
                    "        The wizard will detect and connect to all running MuMu instances.\n"
                )
            return False
        emulator_url = arm64_url
    else:
        if not x64_url:
            if log_fn:
                log_fn("  ❌  Emulator URL not found in repository XML.\n")
            return False
        emulator_url = x64_url

    if log_fn:
        log_fn(f"  Emulator URL: {emulator_url}\n")
        log_fn("  Downloading emulator (~300 MB)…\n")

    tmp = Path(sdk_path) / "_emu_tmp.zip"
    try:
        _urlretrieve(emulator_url, tmp, timeout=120)
        emu_dest = Path(sdk_path) / "emulator"
        if emu_dest.exists():
            shutil.rmtree(emu_dest)
        with zipfile.ZipFile(tmp, "r") as zf:
            zf.extractall(Path(sdk_path))
        tmp.unlink(missing_ok=True)
        _write_emulator_package_xml(emu_dest)
        _write_sdk_licenses(sdk_path)
        if log_fn:
            log_fn("  emulator installed ✅\n")
        return True
    except Exception as e:
        if log_fn:
            log_fn(f"  ❌  Emulator direct download failed: {e}\n")
        tmp.unlink(missing_ok=True)
        return False


def _write_local_package_xml(path: Path, *, path_id, major, minor, micro,
                              display, license_ref, ns_type, extra_ns="",
                              extra_details=""):
    """Write a localPackage package.xml that sdkmanager and avdmanager accept.

    Structure must match Google's official package XML format exactly,
    including all xmlns namespace declarations and the <dependencies> block.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # Build the full namespace string — avdmanager validates these
    base_ns = 'xmlns:ns2="http://schemas.android.com/repository/android/common/01"'
    addon2  = 'xmlns:ns3="http://schemas.android.com/sdk/android/repo/addon2/01"'
    sysimg  = 'xmlns:ns4="http://schemas.android.com/sdk/android/repo/sys-img2/01"'
    generic = 'xmlns:ns5="http://schemas.android.com/repository/android/generic/01"'
    repo2   = 'xmlns:ns6="http://schemas.android.com/repository/android/repository2/01"'
    xsi     = 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
    all_ns  = f"{base_ns} {addon2} {sysimg} {generic} {repo2} {xsi}"

    path.write_text(
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<ns2:repository\n'
        f'    {all_ns}>\n'
        f'  <license id="{license_ref}" type="text">Android Software Development Kit License Agreement\n'
        f'</license>\n'
        f'  <localPackage path="{path_id}" obsolete="false">\n'
        f'    <type-details xsi:type="{ns_type}">{extra_details}</type-details>\n'
        f'    <revision>\n'
        f'      <major>{major}</major><minor>{minor}</minor><micro>{micro}</micro>\n'
        f'    </revision>\n'
        f'    <display-name>{display}</display-name>\n'
        f'    <uses-license ref="{license_ref}"/>\n'
        f'  </localPackage>\n'
        f'</ns2:repository>\n',
        encoding="utf-8",
    )


def _write_emulator_package_xml(emu_dir: Path):
    """Write the official emulator top-level package.xml with all namespaces and dependencies.

    This is the exact format Google ships in sdk/emulator/package.xml.
    avdmanager validates both the namespace declarations AND the dependencies block.
    """
    pkg_xml = emu_dir / "package.xml"
    pkg_xml.write_text(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<ns2:repository '
        'xmlns:ns2="http://schemas.android.com/repository/android/common/01" '
        'xmlns:ns3="http://schemas.android.com/sdk/android/repo/addon2/01" '
        'xmlns:ns4="http://schemas.android.com/sdk/android/repo/sys-img2/01" '
        'xmlns:ns5="http://schemas.android.com/repository/android/generic/01" '
        'xmlns:ns6="http://schemas.android.com/repository/android/repository2/01" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<license id="android-sdk-license" type="text">Android Software Development Kit License Agreement\n'
        '</license>'
        '<localPackage path="emulator" obsolete="false">'
        '<type-details xsi:type="ns5:genericDetailsType"/>'
        '<revision><major>36</major><minor>6</minor><micro>4</micro></revision>'
        '<display-name>Android Emulator</display-name>'
        '<uses-license ref="android-sdk-license"/>'
        '<dependencies>'
        '<dependency path="patcher;v4"/>'
        '<dependency path="tools"><min-revision><major>25</major><minor>3</minor></min-revision></dependency>'
        '</dependencies>'
        '</localPackage>'
        '</ns2:repository>',
        encoding="utf-8",
    )


def _write_sdk_licenses(sdk: str):
    """
    Write Android SDK license files to sdk/licenses/.
    avdmanager validates <uses-license ref="..."/> against these files at startup.
    Without them it logs "package.XML parsing problem undefined ID <license-name>".
    SHA-1 hashes are the official values from Google's SDK license agreements.
    """
    lic_dir = Path(sdk) / "licenses"
    lic_dir.mkdir(parents=True, exist_ok=True)
    licenses = {
        "android-sdk-license": (
            "\n8933bad161af4178b1185d1a37fbf41ea5269c55\n"
            "d56f5187479451eabf01fb78af6dfcb131a6481e\n"
            "24333f8a63b6825ea9c5514f83c2829b004d1fee"
        ),
        "android-sdk-preview-license": (
            "\n84831b9409646a918e30573bab4c9c91346d8abd"
        ),
        "android-sdk-arm-dbt-license": (
            "\n859f317696f67ef3d7f30a50a5560e7834b43903"
        ),
    }
    for name, content in licenses.items():
        (lic_dir / name).write_text(content, encoding="utf-8")


def _direct_download_system_image(arch: str, sdk_path: str, log_fn=None) -> bool:
    """
    Download the Android 34 google_apis system image directly via Python urllib,
    bypassinging Java/sdkmanager.  Parses Google's repository XML to find the URL.
    """
    import xml.etree.ElementTree as ET
    REPO_XML = "https://dl.google.com/android/repository/sys-img/google_apis/sys-img2-3.xml"
    BASE_URL = "https://dl.google.com/android/repository/sys-img/google_apis/"

    if log_fn:
        log_fn("  Fetching system image catalog…\n")
    try:
        with urllib.request.urlopen(REPO_XML, timeout=30) as r:
            xml_data = r.read().decode("utf-8")
    except Exception as e:
        if log_fn:
            log_fn(f"  ❌  Cannot reach system image catalog: {e}\n")
        return False

    image_url = None
    try:
        root = ET.fromstring(xml_data)
        for pkg in root.iter():
            tag = pkg.tag.split("}")[-1] if "}" in pkg.tag else pkg.tag
            if tag not in ("remotePackage", "package"):
                continue
            path_attr = pkg.get("path", "")
            if "android-34" not in path_attr or "google_apis" not in path_attr:
                continue
            if arch not in path_attr:
                continue
            for child in pkg.iter():
                ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if ctag == "url":
                    val = (child.text or "").strip()
                    if val.endswith(".zip"):
                        image_url = BASE_URL + val
                        break
            if image_url:
                break
    except ET.ParseError:
        pass

    if not image_url:
        if log_fn:
            log_fn("  ❌  Could not locate system image URL in repository XML.\n")
        return False

    if log_fn:
        log_fn(f"  Downloading system image (~1 GB): {image_url}\n")

    dest = Path(sdk_path)
    tmp  = dest / "_sysimg_tmp.zip"
    img_dir = dest / "system-images" / "android-34" / "google_apis" / arch
    try:
        _urlretrieve(image_url, tmp, timeout=120)
        img_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(tmp, "r") as zf:
            for member in zf.namelist():
                parts = Path(member).parts
                if len(parts) > 1:
                    out_path = img_dir / Path(*parts[1:])
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    if not member.endswith("/"):
                        out_path.write_bytes(zf.read(member))
                elif parts:
                    out_path = img_dir / parts[0]
                    if not member.endswith("/"):
                        out_path.write_bytes(zf.read(member))
        tmp.unlink(missing_ok=True)
        TARGET_PATH = f"system-images;android-34;google_apis;{arch}"
        _simg_display = ("Google APIs Intel x86_64 Atom System Image"
                         if arch == "x86_64"
                         else "Google APIs ARM 64 v8a System Image")
        _simg_license = ("android-sdk-license"
                         if arch == "x86_64"
                         else "android-sdk-arm-dbt-license")
        _write_local_package_xml(
            img_dir / "package.xml",
            path_id=TARGET_PATH,
            major=14, minor=0, micro=0,
            display=_simg_display,
            license_ref=_simg_license,
            ns_type="ns4:sysImgDetailsType",
            extra_ns='xmlns:ns4="http://schemas.android.com/sdk/android/repo/sys-img2/01"',
            extra_details=(
                f"<ns4:api-level>34</ns4:api-level>"
                f"<ns4:tag><ns4:id>google_apis</ns4:id>"
                f"<ns4:display>Google APIs</ns4:display></ns4:tag>"
                f"<ns4:vendor><ns4:id>google</ns4:id>"
                f"<ns4:display>Google Inc.</ns4:display></ns4:vendor>"
                f"<ns4:abi>{arch}</ns4:abi>"
            ),
        )
        if log_fn:
            log_fn("  System image installed ✅\n")
        return True
    except Exception as e:
        if log_fn:
            log_fn(f"  ❌  Direct system image download failed: {e}\n")
        tmp.unlink(missing_ok=True)
        return False


def _add_firewall_exception_for_java() -> bool:
    """
    Add a Windows Firewall outbound allow rule for java.exe via PowerShell.
    Requires elevation (UAC prompt will appear).
    Returns True if the PowerShell command was launched successfully.
    """
    java_home = _find_java_home()
    if java_home:
        java_exe = str(Path(java_home) / "bin" / "java.exe")
    else:
        java_exe = "java.exe"

    ps_cmd = (
        f"New-NetFirewallRule -DisplayName 'PharmFlow Java' "
        f"-Direction Outbound -Action Allow "
        f"-Program '{java_exe}' -Enabled True"
    )
    try:
        subprocess.Popen(
            ["powershell", "-Command",
             f"Start-Process powershell -Verb RunAs -ArgumentList "
             f"'-NoProfile -Command {ps_cmd}'"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True
    except Exception:
        return False


def _ensure_emulator_meta(sdk, log_fn=None):
    """
    Install emulator device definitions (device-catalog.xml) so avdmanager can
    enumerate hardware profiles (pixel_6, etc.) and AVD creation succeeds.

    Without this, 'avdmanager list device' returns empty and AVD creation fails
    with: "CRITICAL: emulator package must be installed!"

    Strategy (in order):
      1. Android Studio: copy device-catalog.xml from Android Studio's own copy
         of the emulator, if Android Studio is installed.
      2. sdkmanager: run sdkmanager "emulator" (the authoritative install path).
         This downloads and installs the emulator package including device-catalog.xml.
      3. Direct Python download: if sdkmanager fails (network blocked), download
         the emulator ZIP directly from Google's repo XML.
    After each path, verify emulator/meta/device-catalog.xml exists.
    """
    emu_dir = Path(sdk) / "emulator"
    catalog = emu_dir / "meta" / "device-catalog.xml"
    host_is_arm64 = IS_WIN and "arm64" in _machine_arch()

    # ── ARM64-specific binary check (runs even if catalog already exists) ──
    # Step 2 (SDK install) can write an x64 emulator.exe + catalog.  The
    # catalog check below would short-circuit before replacing the x64 binary,
    # causing "CPU Architecture not supported" crashes at boot.  We handle this
    # separately so catalog presence and binary architecture are independent.
    needs_arm64_copy = False
    if host_is_arm64:
        emu_exe = emu_dir / "emulator.exe"
        if emu_exe.exists():
            machine = _pe_machine_type(str(emu_exe))
            if machine == 0xAA64:
                if log_fn:
                    log_fn("  ARM64 emulator binary confirmed ✓\n")
            else:
                if log_fn:
                    log_fn("  ⚠  emulator.exe is x64 — will replace with ARM64 build.\n")
                needs_arm64_copy = True
        else:
            needs_arm64_copy = True  # no binary at all

    # Already present and no ARM64 binary replacement needed — nothing to do
    if catalog.exists() and not needs_arm64_copy:
        if log_fn:
            log_fn("  Emulator device metadata already present.\n")
        return

    if log_fn:
        log_fn("  Installing emulator device definitions (device-catalog.xml)…\n")

    installed = False

    # ── Path 1: Android Studio bundled emulator ─────────────────────────
    # Android Studio ships a complete copy of the emulator with device-catalog.xml.
    # On ARM64 Windows, Android Studio's emulator.exe IS the ARM64 native binary —
    # copy the entire emulator directory so arm64-v8a images boot natively.
    studio_emulator = None
    search_roots = [
        Path(os.environ.get("PROGRAMFILES",      "")) / "Android",
        Path(os.environ.get("LOCALAPPDATA",      "")) / "Programs" / "Android",
        Path(os.environ.get("PROGRAMFILES",      "")) / "Android Studio",
        Path(os.environ.get("LOCALAPPDATA",      "")) / "Programs" / "Android Studio",
        Path(os.environ.get("LOCALAPPDATA",      "")) / "Google",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Android",
        Path(os.environ.get("LOCALAPPDATA",      "")) / "Android",
    ]
    for search_root in search_roots:
        if not search_root.exists():
            continue
        # Glob for any "Android Studio*" subdirectory (handles Studio, Studio3, etc.)
        candidates = sorted(search_root.glob("Android Studio*"), reverse=True)
        if not candidates and search_root.name.startswith("Android Studio"):
            candidates = [search_root]
        for studio_root in candidates:
            candidate = studio_root / "emulator"
            if (candidate / "emulator.exe").exists():
                studio_emulator = candidate
                break
        if studio_emulator:
            break

    if studio_emulator:
        if log_fn:
            log_fn(f"  Found Android Studio emulator:\n  {studio_emulator}\n")
        try:
            # On ARM64 Windows, Android Studio's emulator.exe is the ARM64 native binary.
            # Copy the entire emulator directory so arm64-v8a guests boot natively.
            as_exe = studio_emulator / "emulator.exe"
            if host_is_arm64 and as_exe.exists() and _pe_machine_type(str(as_exe)) == 0xAA64:
                if log_fn:
                    log_fn("  ARM64 emulator binary found in Android Studio — copying full emulator directory…\n")
                if emu_dir.exists():
                    shutil.rmtree(emu_dir)
                shutil.copytree(str(studio_emulator), str(emu_dir))
                if log_fn:
                    log_fn("  ARM64 emulator installed from Android Studio ✅\n")
            else:
                # x64 host or AS binary is x64 — just copy device-catalog.xml
                meta_dest = emu_dir / "meta"
                meta_dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(
                    studio_emulator / "meta" / "device-catalog.xml",
                    meta_dest / "device-catalog.xml",
                )
                if log_fn:
                    log_fn("  Copied device definitions from Android Studio ✅\n")
            _write_emulator_package_xml(emu_dir)
            _write_local_package_xml(
                emu_dir / "meta" / "package.xml",
                path_id="emulator;meta",
                major=36, minor=6, micro=4,
                display="Android Emulator Device Metadata",
                license_ref="android-sdk-license",
                ns_type="ns5:genericDetailsType",
                extra_ns='xmlns:ns3="http://schemas.android.com/repository/android/generic/01"',
            )
            installed = True
        except Exception as e:
            if log_fn:
                log_fn(f"  Could not copy from Android Studio: {e}\n")

    # ── Path 2: sdkmanager "emulator" (x64 hosts only) ──────────────────
    # On ARM64 Windows, sdkmanager always downloads the x64 emulator binary which
    # cannot run arm64-v8a guests and crashes immediately at boot.  Skip straight
    # to the direct-download path which parses the repo XML for the aarch64 build.
    if not installed and not (host_is_arm64 and needs_arm64_copy):
        if log_fn:
            log_fn("  Trying sdkmanager 'emulator' install (authoritative)…\n")

        ok, out = _run_sdkmanager(["emulator"], sdk, log_fn=log_fn, timeout=300)
        if catalog.exists():
            if log_fn:
                log_fn("  Emulator + device metadata installed via sdkmanager ✅\n")
            installed = True
        else:
            if log_fn:
                log_fn(f"  sdkmanager 'emulator' did not produce device-catalog.xml.\n"
                       f"  Output preview: {out[:300]}\n")

    # ── Path 3: Direct Python download ──────────────────────────────────
    # Primary path on ARM64 Windows (skips x64-only sdkmanager above).
    # _direct_download_emulator parses the repo XML for aarch64 builds first.
    if not installed:
        if log_fn:
            log_fn("  Falling back to direct Python download of emulator.\n"
                   "  (This bypasses Java's network stack.)\n")
        _direct_download_emulator(sdk, log_fn=log_fn)

    # ── Final verdict ────────────────────────────────────────────────────
    if catalog.exists():
        if log_fn:
            log_fn("  Emulator device metadata installed ✅\n")
    else:
        if log_fn:
            log_fn("  ⚠  device-catalog.xml still missing after all fallbacks.\n"
                   "    AVD creation will fail. Consider installing Android Studio\n"
                   "    to get the full emulator package with device definitions.\n")

    # On ARM64 Windows, verify the final emulator binary is actually ARM64.
    if host_is_arm64:
        emu_exe = emu_dir / "emulator.exe"
        if emu_exe.exists() and _pe_machine_type(str(emu_exe)) != 0xAA64:
            if log_fn:
                log_fn(
                    "  ❌  emulator.exe is still x64 after all install attempts.\n"
                    "     Google does not publish a Windows ARM64 Android Emulator —\n"
                    "     even Android Studio ARM64 only downloads the x64 emulator via\n"
                    "     its SDK Manager. There is no ARM64 AVD emulator from Google.\n\n"
                    "  ✅  Use MuMuPlayer for Windows ARM instead:\n"
                    "     Free, native ARM64, multi-instance, full ADB — skip AVD entirely.\n"
                    f"     Download: {MUMU_DOWNLOAD_URL}\n"
                    "     After installing, open MuMuPlayer, create instances, then go\n"
                    "     directly to Connect & boot — the wizard attaches over ADB.\n"
                )


def create_avd(name, log_fn=None):
    sdk = state.get("sdk_path") or find_sdk()
    if not sdk:
        return False, "Android SDK not found"

    # avdmanager lives beside sdkmanager in cmdline-tools/latest/bin/
    sdkmgr_path = _canonical_sdkmanager(sdk)
    ext    = ".bat" if IS_WIN else ""
    avdmgr = str(Path(sdkmgr_path).parent / f"avdmanager{ext}")
    arch   = _machine_arch()
    # On ARM64 Windows: arm64-v8a — the native ARM64 emulator binary runs
    # arm64-v8a guests directly without any hypervisor requirement, avoiding
    # the Intel/AMD CPU check that blocks x86_64 guests on Snapdragon.
    # On x64 Windows: x86_64 system images (WHPX-accelerated).
    # _machine_arch() already returns the correct ABI — no override needed.
    image  = f"system-images;android-34;google_apis;{arch}"

    java_home = _find_java_home()
    if log_fn:
        log_fn(f"  Host architecture : {arch}\n")
        log_fn(f"  System image      : {image}\n")
        log_fn(f"  SDK root          : {sdk}\n")
        log_fn(f"  sdkmanager        : {_canonical_sdkmanager(sdk)}\n")
        log_fn(f"  avdmanager        : {avdmgr}\n")
        log_fn(f"  Java home         : {java_home or '❌ NOT FOUND'}\n\n")

    if not java_home:
        return False, (
            "Java not found.\n\n"
            "Go back to Install tools and make sure Java installed successfully,\n"
            "then come back and try again."
        )

    # ── write license files + accept all licenses ─────────────────────────────
    if log_fn:
        log_fn("  Writing SDK license files…\n")
    _write_sdk_licenses(sdk)
    if log_fn:
        log_fn("  Accepting SDK licenses…\n")
    _run_sdkmanager(["--licenses"], sdk, log_fn=None, timeout=60)

    # ── install system image ──────────────────────────────────────────────────
    img_path = Path(sdk) / "system-images" / "android-34" / "google_apis" / arch
    # system.img may be gzipped (system.img.gz) in downloaded zips — check both
    img_ready = (img_path / "system.img.gz").exists() or (img_path / "system.img").exists()
    if img_ready:
        # Ensure package.xml is in localPackage format — Google's zip ships a
        # remotePackage XML that avdmanager cannot use; re-write it if needed.
        pkg_xml = img_path / "package.xml"
        try:
            if not pkg_xml.exists() or "<localPackage" not in pkg_xml.read_text(encoding="utf-8", errors="ignore"):
                TARGET_PATH = f"system-images;android-34;google_apis;{arch}"
                _img_display = ("Google APIs Intel x86_64 Atom System Image"
                                if arch == "x86_64"
                                else "Google APIs ARM 64 v8a System Image")
                _img_license = ("android-sdk-license"
                                if arch == "x86_64"
                                else "android-sdk-arm-dbt-license")
                _write_local_package_xml(
                    pkg_xml,
                    path_id=TARGET_PATH,
                    major=14, minor=0, micro=0,
                    display=_img_display,
                    license_ref=_img_license,
                    ns_type="ns4:sysImgDetailsType",
                    extra_ns='xmlns:ns4="http://schemas.android.com/sdk/android/repo/sys-img2/01"',
                    extra_details=(
                        f"<ns4:api-level>34</ns4:api-level>"
                        f"<ns4:tag><ns4:id>google_apis</ns4:id>"
                        f"<ns4:display>Google APIs</ns4:display></ns4:tag>"
                        f"<ns4:vendor><ns4:id>google</ns4:id>"
                        f"<ns4:display>Google Inc.</ns4:display></ns4:vendor>"
                        f"<ns4:abi>{arch}</ns4:abi>"
                    ),
                )
                if log_fn:
                    log_fn("  Rewrote package.xml to localPackage format.\n")
        except Exception as e:
            if log_fn:
                log_fn(f"  ⚠  Could not rewrite package.xml: {e}\n")
        if log_fn:
            log_fn(f"  System image already installed at {img_path} — skipping download.\n")
    else:
        if log_fn:
            log_fn(f"  Installing Android 14 image — this downloads ~1 GB, please wait…\n")
        ok, out = _run_sdkmanager([image], sdk, log_fn=log_fn, timeout=1200)

        if not ok:
            if (img_path / "system.img.gz").exists() or (img_path / "system.img").exists():
                if log_fn:
                    log_fn("  Image present on disk — continuing despite sdkmanager exit code.\n")
            else:
                if log_fn:
                    log_fn("  sdkmanager failed — trying direct download fallback…\n")
                ok2 = _direct_download_system_image(arch, sdk, log_fn=log_fn)
                if not ok2:
                    return False, f"sdkmanager failed and direct download also failed.\nLast sdkmanager output:\n{out[-400:]}"

    # ── create the AVD ────────────────────────────────────────────────────────
    if log_fn:
        log_fn(f"\n  Creating AVD: {name}…\n")

    flags = subprocess.CREATE_NO_WINDOW if IS_WIN else 0

    # Ensure emulator metadata (device definitions) is present before calling avdmanager.
    # Without emulator/meta/device-catalog.xml, 'avdmanager list device' returns empty
    # and AVD creation fails with "emulator package must be installed!"
    _ensure_emulator_meta(sdk, log_fn)

    # Discover device IDs that are actually present in this SDK installation.
    # Never guess IDs — avdmanager -d is case-sensitive and varies between SDK versions.
    try:
        r = subprocess.run(
            [avdmgr, "list", "device", "-c"],
            capture_output=True, text=True, timeout=30,
            env=_sdk_env(), creationflags=flags,
        )
        all_ids = [l.strip() for l in r.stdout.splitlines() if l.strip()]
    except Exception:
        all_ids = []

    # Preferred device IDs in priority order — use the first one that exists in this SDK.
    preferred = [
        "pixel_9", "pixel_9_pro", "pixel_8", "pixel_8_pro",
        "pixel_7", "pixel_7_pro", "pixel_6", "pixel_6_pro",
        "pixel_5", "pixel_4", "pixel_3", "pixel_2",
        "pixel_xl", "pixel", "nexus_6p", "nexus_6", "nexus_5",
    ]
    device_profiles = [d for d in preferred if d in all_ids]

    # If none of our preferred IDs exist, fall back to the first available device
    if not device_profiles and all_ids:
        device_profiles = [all_ids[0]]

    if not device_profiles:
        device_profiles = ["pixel_6"]   # last resort — avdmanager will give a clear error

    if log_fn:
        log_fn(f"  Available device IDs (first 5): {all_ids[:5]}\n")
        log_fn(f"  Will try: {device_profiles}\n")

    if not Path(avdmgr).exists():
        return False, (
            f"avdmanager not found at: {avdmgr}\n"
            "Go back to Android runtime and reinstall the SDK."
        )

    last_err = ""
    for device in device_profiles:
        if log_fn:
            log_fn(f"  Trying device profile: {device}\n")
        try:
            proc = subprocess.Popen(
                [avdmgr, "create", "avd", "-n", name,
                 "-k", image, "-d", device, "--force"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=_sdk_env(),
                creationflags=flags,
            )
        except OSError as e:
            return False, f"Failed to launch avdmanager: {e}"

        try:
            stdout, stderr = proc.communicate(input="no\n", timeout=120)
        except subprocess.TimeoutExpired:
            proc.kill()
            return False, "avdmanager timed out"

        combined = (stdout + stderr).strip()
        if log_fn and combined:
            log_fn(combined + "\n")

        if proc.returncode == 0:
            if log_fn:
                log_fn(f"  ✅  {name} created (device: {device}).\n")
            return True, ""
        last_err = combined
        if log_fn:
            log_fn(f"  Device profile '{device}' failed — trying next…\n")

    return False, last_err or "avdmanager failed with all device profiles"


def start_emulator(avd_name, port):
    emu   = sdk_tool("emulator")
    env   = _sdk_env()

    # On ARM64 Windows: arm64-v8a guest runs natively on the ARM64 emulator binary —
    #   no hypervisor required, no Intel/AMD CPU check triggered.
    # On x64 Windows: x86_64 guest needs -accel auto (WHPX or HAXM).
    # -gpu swiftshader_indirect — Adreno Vulkan lacks VK_KHR_external_memory so
    #   host GPU passthrough is unavailable; software GLES is required either way.
    # -wipe-data on every start erased the phone. A start keeps the data disk.
    # CREATE_NO_WINDOW hides the console only. DETACHED_PROCESS plus SW_HIDE
    # parked the phone window off-screen, so those flags are not used.
    host_is_arm64 = IS_WIN and "arm64" in _machine_arch()
    base_args = ["-gpu", "swiftshader_indirect",
                 "-no-snapshot-save", "-no-boot-anim", "-no-audio"]
    accel_args = base_args if host_is_arm64 else ["-accel", "auto"] + base_args
    launch_flags = subprocess.CREATE_NO_WINDOW if IS_WIN else 0

    log_path = None
    try:
        log_dir = Path(os.environ.get("TEMP", "/tmp"))
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"pharmflow_emu_{avd_name}.log"
        log_file = open(log_path, "w")
    except Exception:
        log_file = subprocess.DEVNULL

    # On Windows, emulator may be a .bat wrapper (emulator.bat/emulator.cmd).
    # Popen with a list on Windows does NOT automatically run .bat files —
    # we must use shell=True so cmd.exe handles them.
    argv = [emu, "-avd", avd_name, "-port", str(port)] + accel_args
    cmd_str = subprocess.list2cmdline(argv)

    popen_kwargs = dict(env=env, creationflags=launch_flags, shell=True)
    if log_file is not None:
        popen_kwargs["stdout"] = log_file
        popen_kwargs["stderr"] = log_file

    proc = subprocess.Popen(cmd_str, **popen_kwargs)
    if log_file and log_file is not subprocess.DEVNULL:
        proc._log_file = log_file
    return proc, log_path


def wait_for_boot(serial, timeout=300, log_fn=None):
    # Cap wait-for-device so a missing device cannot consume the entire budget;
    # remaining time is used to poll sys.boot_completed.
    wait_budget = max(15, min(int(timeout), max(30, int(timeout * 0.4))))
    adb("wait-for-device", serial=serial, timeout=wait_budget)
    deadline = time.time() + timeout
    start    = time.time()
    last_log = start
    while time.time() < deadline:
        out = adb("shell", "getprop", "sys.boot_completed", serial=serial)
        if out.strip() == "1":
            return True
        now = time.time()
        if log_fn and now - last_log >= 30:
            elapsed = int(now - start)
            log_fn(f"    still booting... ({elapsed}s elapsed)\n")
            last_log = now
        time.sleep(3)
    return False


def rotate_android_id(serial):
    new_id = format(hash(serial + str(time.time())) & 0xFFFFFFFFFFFFFFFF, "016x")
    adb("shell", "settings", "put", "secure", "android_id", new_id, serial=serial)
    return new_id


def _serial_to_idx(serial: str) -> int:
    """Tor slot for this serial. Do not treat every ARM guest (10.0.2.x:5555) as phone 0."""
    automation_on_sys_path()
    import tor_manager as _tm

    return _tm.phone_idx_from_adb_serial(serial)


def _try_newnym(serial: str) -> bool:
    automation_on_sys_path()
    import tor_manager as _tm

    idx = _tm.phone_idx_from_adb_serial(serial)
    ctrl_port = _tm.phone_control_port(idx)
    try:
        with socket.create_connection(("127.0.0.1", ctrl_port), timeout=2) as s:
            s.sendall(b'AUTHENTICATE ""\r\n')
            s.recv(256)
            s.sendall(b"SIGNAL NEWNYM\r\n")
            return b"250" in s.recv(256)
    except OSError:
        return False


def _apk_pkg_installed(serial: str, pkg: str) -> bool:
    out = adb("shell", "pm", "path", pkg, serial=serial, timeout=20)
    return "package:" in (out or "")


def _chrome_pkg_installed(serial: str) -> bool:
    return _apk_pkg_installed(serial, "com.android.chrome")


# F-Droid browser packages (no APK shipped here). Optional files under ``wizard/bundled/``:
# ``Fennec.apk``, ``Mull.apk``, or ``fennec_fdroid.apk`` — user obtains builds from F-Droid / upstream.
FDROID_FENNEC_PKG = "org.mozilla.fennec_fdroid"
FDROID_MULL_PKG = "us.spotco.fennec_dos"


def _try_pm_install_existing_pkg(serial: str, pkg: str, log_fn=None) -> bool:
    """Enable stub / recoverable system package via ``pm install-existing`` variants."""
    if _apk_pkg_installed(serial, pkg):
        return True
    adb("shell", "pm", "enable", pkg, serial=serial, timeout=15)
    if _apk_pkg_installed(serial, pkg):
        return True
    for args in (
        ("shell", "cmd", "package", "install-existing", pkg),
        ("shell", "cmd", "package", "install-existing", "--user", "0", pkg),
        ("shell", "pm", "install-existing", pkg),
        ("shell", "pm", "install-existing", "--user", "0", pkg),
    ):
        out = adb(*args, serial=serial, timeout=120)
        if log_fn:
            log_fn(f"    {' '.join(args[1:])} → {(out or '')[:160]}\n")
        if _apk_pkg_installed(serial, pkg):
            return True
    return False


def _try_bundled_fdroid_apk(serial: str, log_fn=None) -> str | None:
    """Install optional bundled Fennec/Mull APKs; return package id if one becomes installed."""
    here = wizard_module_dir() / "bundled"
    candidates = (
        ("Fennec.apk", FDROID_FENNEC_PKG),
        ("fennec_fdroid.apk", FDROID_FENNEC_PKG),
        ("Mull.apk", FDROID_MULL_PKG),
    )
    for fname, expect_pkg in candidates:
        p = here / fname
        if not p.is_file():
            continue
        if log_fn:
            log_fn(f"    adb install (bundled {fname})…\n")
        out = adb("install", "-r", str(p), serial=serial, timeout=300)
        if log_fn and out:
            log_fn(f"    → {(out or '')[:200]}\n")
        if _apk_pkg_installed(serial, expect_pkg):
            return expect_pkg
    return None


def ensure_fdroid_browser(serial: str, log_fn=None) -> str | None:
    """Ensure Fennec or Mull is installed; return the package id or None.

    Order: already installed → ``install-existing`` for Fennec then Mull → optional bundled APKs.
    """
    if _apk_pkg_installed(serial, FDROID_FENNEC_PKG):
        return FDROID_FENNEC_PKG
    if _apk_pkg_installed(serial, FDROID_MULL_PKG):
        return FDROID_MULL_PKG
    if _try_pm_install_existing_pkg(serial, FDROID_FENNEC_PKG, log_fn):
        return FDROID_FENNEC_PKG
    if _try_pm_install_existing_pkg(serial, FDROID_MULL_PKG, log_fn):
        return FDROID_MULL_PKG
    got = _try_bundled_fdroid_apk(serial, log_fn)
    return got


#
# Chrome APK workflow (user supplies APK — do not redistribute Google Chrome APK in open source):
# - Place ``ChromePublic.apk`` / ``chrome.apk`` under ``wizard/bundled/`` (wizard installs per device),
#   or sideload once via **Install APK on all phones** (``adb install -r`` per device).
# - DabFlow / getdabflow.app testing is browser-only — no Google Play Store required.
#


def _install_apk_all_phones(apk_path: str | Path, serials, log_fn=None) -> dict:
    """Run ``adb install -r`` on each serial. ``serials`` is an iterable of ADB serial strings."""
    path = Path(apk_path)
    results = []
    if not path.is_file():
        if log_fn:
            log_fn(f"    APK not found or not a file: {path}\n")
        return {"ok": False, "results": results}
    resolved = str(path.resolve())
    name = path.name
    for serial in serials:
        if log_fn:
            log_fn(f"    [{serial}] adb install -r {name} …\n")
        out = adb("install", "-r", resolved, serial=serial, timeout=600)
        if log_fn and out:
            log_fn(f"    → {(out or '')[:400]}\n")
        o = out or ""
        ok = ("Success" in o) and ("Failure" not in o)
        results.append({"serial": serial, "ok": ok})
    return {"ok": all(r["ok"] for r in results) if results else False, "results": results}


def _bundled_chrome_apk_path():
    """Optional APK in ``wizard/bundled/`` (not shipped by default)."""
    here = wizard_module_dir() / "bundled"
    for name in ("ChromePublic.apk", "chrome.apk"):
        p = here / name
        if p.is_file():
            return p
    return None


def _try_install_bundled_chrome_apk(serial: str, log_fn) -> bool:
    apk = _bundled_chrome_apk_path()
    if not apk:
        return False
    if log_fn:
        log_fn(f"    adb install (bundled {apk.name})…\n")
    out = adb("install", "-r", str(apk), serial=serial, timeout=300)
    if log_fn and out:
        log_fn(f"    → {(out or '')[:200]}\n")
    return _chrome_pkg_installed(serial)


def ensure_android_chrome(serial: str, log_fn=None) -> bool:
    """Ensure ``com.android.chrome`` exists (many MuMu / AVD images ship without Chrome).

    Browser-only path: enable stub if present, optional bundled APK under ``wizard/bundled/``,
    then ``pm install-existing``. No Play Store — sideload an APK if Chrome is still missing.
    """
    if _chrome_pkg_installed(serial):
        return True
    adb("shell", "pm", "enable", "com.android.chrome", serial=serial, timeout=15)
    if _chrome_pkg_installed(serial):
        return True
    if _try_install_bundled_chrome_apk(serial, log_fn):
        return True
    for args in (
        ("shell", "cmd", "package", "install-existing", "com.android.chrome"),
        ("shell", "cmd", "package", "install-existing", "--user", "0", "com.android.chrome"),
        ("shell", "pm", "install-existing", "com.android.chrome"),
        ("shell", "pm", "install-existing", "--user", "0", "com.android.chrome"),
    ):
        out = adb(*args, serial=serial, timeout=120)
        if log_fn:
            log_fn(f"    {' '.join(args[1:])} → {(out or '')[:160]}\n")
        if _chrome_pkg_installed(serial):
            return True
    if log_fn:
        log_fn(
            "    Chrome still missing — sideload an APK with **Install APK on all phones** or "
            "``adb install -r chrome.apk`` (no Google account needed), or place "
            "``ChromePublic.apk`` / ``chrome.apk`` under wizard/bundled/ and try again.\n"
        )
    return False


def setup_chrome(serial, log_fn=None):
    """
    Kill Chrome first-run experience so URLs open immediately every time.

    Fresh AVDs show ToS / sync screens that swallow the target URL.
    Writing the chrome-command-line flags file disables all of that.
    Works without root — shell user can write to /data/local/tmp.

    If Chrome is not installed, tries bundled APK (if present) and ``pm install-existing``.
    """
    if not ensure_android_chrome(serial, log_fn=log_fn):
        return False
    flags = (
        "chrome --disable-first-run-experience "
        "--no-default-browser-check --no-first-run "
        "--disable-fre --disable-sync-by-default"
    )
    adb("shell", "sh", "-c",
        f"mkdir -p /data/local/tmp && "
        f"echo '{flags}' > /data/local/tmp/chrome-command-line",
        serial=serial)
    adb("shell", "am", "force-stop", "com.android.chrome", serial=serial)
    time.sleep(0.8)
    # Open about:blank so Chrome initialises with the new flags
    adb("shell", "am", "start",
        "-a", "android.intent.action.VIEW",
        "-d", "about:blank",
        "-n", "com.android.chrome/com.google.android.apps.chrome.Main",
        "--ez", "create_new_tab", "true",
        serial=serial)
    time.sleep(3)
    try:
        ap = str(_pharmflow_install_root() / "automation")
        if ap not in sys.path:
            sys.path.insert(0, ap)
        import chromium_fre_uia as _fre

        _fre.dismiss_chromium_fre_after_open(serial, log_fn=log_fn)
    except Exception:
        for _ in range(3):
            adb("shell", "input", "keyevent", "4", serial=serial)
            time.sleep(0.4)
    adb("shell", "am", "force-stop", "com.android.chrome", serial=serial)
    return True


def _wiz_phone_idx_for_tor(s: str) -> int:
    """Tor slot from ADB serial — delegated to ``tor_manager.phone_idx_from_adb_serial``."""
    root = _pharmflow_install_root()
    auto_path = root / "automation"
    ap = str(auto_path)
    if ap not in sys.path:
        sys.path.insert(0, ap)
    try:
        import tor_manager as _tm

        return _tm.phone_idx_from_adb_serial(str(s))
    except Exception:
        return 0


def _wiz_repair_proxy_adb_reverse(serial: str) -> None:
    """Re-apply ``adb reverse`` when ``http_proxy`` is set but the forward dropped (MuMu reconnect)."""
    root = _pharmflow_install_root()
    auto_path = root / "automation"
    ap = str(auto_path)
    if ap not in sys.path:
        sys.path.insert(0, ap)
    try:
        import tor_manager as _tm

        idx = _wiz_phone_idx_for_tor(serial)
        result = _tm.repair_adb_reverse_for_proxy(str(serial), idx)
        if result.get("repaired"):
            print(
                f"[pharmflow] Proxy reverse repaired serial={serial} "
                f"port={result.get('port')} reason={result.get('reason')}"
            )
    except Exception:
        pass


def _wiz_open_url_am_start_timeout_sec() -> float:
    try:
        v = float(os.environ.get("PHARMFLOW_OPEN_URL_AM_START_TIMEOUT_SEC", "35") or 35)
    except (TypeError, ValueError):
        v = 35.0
    return max(15.0, min(120.0, v))


def _wiz_normalize_url_for_intent(raw) -> str:
    txt = str(raw or "").strip()
    if not txt:
        return txt
    if "://" not in txt and "." in txt and " " not in txt:
        txt = f"https://{txt}"
    try:
        p = urllib.parse.urlparse(txt)
    except Exception:
        return txt
    if p.scheme in ("http", "https") and p.netloc:
        return urllib.parse.urlunparse(p._replace(fragment=""))
    return txt


def _wiz_skip_tor_wait() -> bool:
    return os.environ.get("PHARMFLOW_SKIP_TOR_WAIT", "").strip().lower() in ("1", "true", "yes", "on")


def _wiz_pid_pkg_running(serial: str, pkg: str) -> bool:
    out = adb("shell", "pidof", pkg, serial=serial, timeout=8)
    if (out or "").strip():
        return True
    out2 = adb("shell", "pgrep", "-f", pkg, serial=serial, timeout=8)
    return bool((out2 or "").strip())


def _wiz_wait_browser_pid_after_open(serial: str, pkgs: list[str]) -> None:
    if not pkgs:
        return
    try:
        timeout = float(os.environ.get("PHARMFLOW_OPEN_URL_LAUNCH_WAIT_SEC", "65"))
    except (TypeError, ValueError):
        timeout = 65.0
    timeout = max(8.0, min(timeout, 180.0))
    deadline = time.time() + timeout
    while time.time() < deadline:
        for pkg in pkgs:
            if _wiz_pid_pkg_running(serial, pkg):
                return
        time.sleep(0.48)


def _wiz_settle_after_open_url(*, fast: bool = False) -> float:
    if fast:
        try:
            return min(1.0, max(0.0, float(os.environ.get("PHARMFLOW_OPEN_URL_FAST_SETTLE_SEC", "0") or 0)))
        except (TypeError, ValueError):
            return 0.0
    try:
        d = float(os.environ.get("PHARMFLOW_OPEN_URL_DEFAULT_WAIT_SEC", "6") or 6)
    except (TypeError, ValueError):
        d = 0.0
    try:
        f = float(os.environ.get("PHARMFLOW_OPEN_URL_FIRST_NAV_SEC", "4") or 4)
    except (TypeError, ValueError):
        f = 4.0
    d = max(0.0, d)
    f = max(0.0, f)
    return max(d, f)


def _plain_tor_user_message(err: str | None) -> str:
    """Turn Tor/proxy errors into short operator-facing text."""
    s = (err or "").strip()
    if not s:
        return "Tor is still starting. Wait 2–3 minutes, then try again."
    low = s.lower()
    if "bootstrap" in low or "not confirmed" in low:
        return "Tor is still starting. Wait 2–3 minutes, then try again."
    if "socks" in low or ("port" in low and "not" in low):
        return "Tor is still starting. Wait a minute and try again."
    if "proxy" in low or "reverse" in low:
        return (
            "The phone's internet helper isn't ready yet. "
            "Wait a minute, then try again."
        )
    if len(s) > 72 or any(x in low for x in ("adb", "cparm_", "endpoint", "api/")):
        return "Tor is still starting. Wait 2–3 minutes, then try again."
    return s


def _wiz_prepare_browse_skip_tor(serial: str, url: str) -> bool:
    """Pin the guest exit before a getdabflow open. Never clear the proxy.

    The old call passed the serial as the adb object, so it always threw and
    Test URL opened without a pin.
    """
    if "getdabflow.app" not in (url or "").lower():
        return False
    try:
        automation_on_sys_path()
        import browse_proxy as bp
        from adb_wrapper import AdbWrapper

        if not bp.dabflow_browse_active():
            return False
        idx = _wiz_phone_idx_for_tor(serial)
        out = bp.prepare_browse_session(
            AdbWrapper(),
            str(serial),
            idx,
            log_fn=lambda m: print(f"[pharmflow] {m}", flush=True),
        )
        return bool(out.get("ok"))
    except Exception as exc:
        print(f"[pharmflow] browse pin failed serial={serial}: {exc}", flush=True)
        return False


def _wiz_apply_dabflow_mantis_patch(serial: str, url: str) -> None:
    """Inject live Mantis zone fix after getdabflow loads in Chromium."""
    if "getdabflow.app" not in (url or "").lower():
        return
    try:
        automation_on_sys_path()
        from dabflow_mantis_client_patch import maybe_apply_after_open_url_step

        maybe_apply_after_open_url_step(
            serial,
            url,
            _wiz_phone_idx_for_tor(serial),
        )
    except Exception as exc:
        print(f"[pharmflow] Mantis patch error serial={serial}: {exc}", flush=True)


def _wiz_read_guest_proxy(serial: str) -> str:
    out = adb(
        "shell",
        "settings",
        "get",
        "global",
        "http_proxy",
        serial=serial,
        timeout=8,
    )
    return (out or "").strip()


def _wiz_ensure_phone_exit(serial: str) -> tuple[bool, str]:
    """Refuse to browse until the guest proxy is this phone's loopback exit.

    An empty, null, or ``:0`` proxy sends the page out the VM NAT (this PC).
    That rule applies to every URL, not only getdabflow. A pinned exit short-
    circuits. A missing one gets one pin attempt, then a re-read. Failure does
    not launch the browser.
    """
    cur = _wiz_read_guest_proxy(serial)
    if "error:" in cur.lower():
        return False, cur
    try:
        automation_on_sys_path()
        from browse_proxy import guest_proxy_healthy, pin_guest_proxy
        from adb_wrapper import AdbWrapper
    except Exception as exc:
        return False, f"Could not check this phone's exit: {exc}"
    if guest_proxy_healthy(cur):
        return True, cur
    try:
        pinned = pin_guest_proxy(
            AdbWrapper(),
            str(serial),
            _wiz_phone_idx_for_tor(serial),
            attempts=1,
        )
    except Exception as exc:
        print(f"[pharmflow] exit pin failed serial={serial}: {exc}", flush=True)
        pinned = ""
    if guest_proxy_healthy(str(pinned or "")):
        return True, str(pinned)
    again = _wiz_read_guest_proxy(serial)
    if "error:" in again.lower():
        return False, again
    if guest_proxy_healthy(again):
        return True, again
    return False, (
        "This phone has no exit proxy, so the page was not opened. "
        "Traffic would leave this PC. Press Fix phone internet, then try again."
    )


def _am_start_landed(out: str | None) -> bool:
    """True only when ``am start`` reported a start or a delivery to a running app."""
    low = (out or "").strip().lower()
    if not low:
        return False
    if "error:" in low or "exception" in low or "unable to resolve intent" in low:
        return False
    return (
        "starting:" in low
        or "intent has been delivered" in low
        or "brought to the front" in low
    )


def chrome_open_url(serial, url, *, fast_pre_site: bool = False):
    """Open a URL on-device with the same fallback order as runtime.

    Returns ``(ok, note)`` where ``ok`` is True only when ``am start`` reported
    Starting, delivered, or brought to the front. Empty adb output is not an
    open. ``note`` is set when Tor/proxy was not ready (pages may still time
    out) or when ``ok`` is False to carry the last adb error / a short reason.
    """
    root = _pharmflow_install_root()
    auto_path = root / "automation"
    ap = str(auto_path)
    if ap not in sys.path:
        sys.path.insert(0, ap)

    skip_tor = _wiz_prepare_browse_skip_tor(serial, url)

    _tor_m = None
    if not skip_tor:
        try:
            import tor_manager as _tor_m  # noqa: WPS433 — after sys.path

            _wiz_repair_proxy_adb_reverse(serial)
            _tor_m.start_tor_warm_background(_wiz_phone_idx_for_tor(serial))
        except Exception:
            _tor_m = None

    url = _wiz_normalize_url_for_intent(url)
    dabflow = "getdabflow.app" in url.lower()
    if dabflow:
        try:
            from browser_setup import prepare_for_dabflow_open

            prepare_for_dabflow_open(
                serial,
                url,
                log=lambda m: print(f"[pharmflow] {m}", flush=True),
            )
        except Exception as _prep_exc:
            print(f"[pharmflow] dabflow prep warning serial={serial}: {_prep_exc}", flush=True)

    tor_note = None
    try:
        _p = urllib.parse.urlparse(url)
        if _p.scheme not in ("http", "https") or not _p.netloc or " " in url:
            return False, "Invalid or unsupported URL (need http(s) with a host)."
    except Exception:
        return False, "Could not parse URL."

    if not skip_tor and not _wiz_skip_tor_wait() and _tor_m is not None:
        try:
            _tor_ready = _tor_m.ensure_tor_ready(serial, _wiz_phone_idx_for_tor(serial))
            if not _tor_ready.get("ok"):
                _err = _tor_ready.get("error", "unknown")
                tor_note = _plain_tor_user_message(str(_err))
                print(
                    f"[pharmflow] Tor not ready before opening link — {_err} "
                    f"(wait for Set up Tor on Launch)"
                )
                if os.environ.get("PHARMFLOW_OPEN_URL_DEBUG", "").strip().lower() in (
                    "1",
                    "true",
                    "yes",
                    "on",
                ):
                    print(f"[pharmflow] open_url DEBUG tor detail: {_err}")
        except Exception as exc:
            tor_note = _plain_tor_user_message(str(exc))
            print(f"[pharmflow] Tor check failed before opening link — {exc}", flush=True)

    # A getdabflow open with no pin and no ready exit leaves the host IP.
    if dabflow and not skip_tor and not _wiz_skip_tor_wait():
        if _tor_m is None:
            return False, tor_note or (
                "This phone's exit is not ready. The page was not opened."
            )
        if tor_note:
            return False, tor_note

    # Every URL, not only getdabflow. No guest loopback proxy means the page
    # leaves through the VM NAT (this PC). Do not launch the browser.
    exit_ok, exit_note = _wiz_ensure_phone_exit(serial)
    if not exit_ok:
        return False, exit_note or (
            "This phone has no exit proxy, so the page was not opened. "
            "Traffic would leave this PC."
        )

    try:
        from browser_adb import package_installed, packages_for_dabflow_view_url_attempts, packages_for_view_url_attempts
        from device_open_url import am_start_view_url_argv
    except ImportError:
        tout_fb = int(_wiz_open_url_am_start_timeout_sec())
        out = adb(
            "shell",
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            url,
            serial=serial,
            timeout=tout_fb,
        )
        if _am_start_landed(out):
            try:
                _st = _wiz_settle_after_open_url(fast=fast_pre_site)
                if _st > 0:
                    time.sleep(_st)
            except (TypeError, ValueError):
                pass
            if dabflow:
                _wiz_apply_dabflow_mantis_patch(serial, url)
            return True, tor_note
        tail = (out or "").strip().replace("\r", " ")
        if len(tail) > 220:
            tail = tail[:217] + "..."
        return False, tor_note or tail or "The phone did not open a browser."
    am_t = int(_wiz_open_url_am_start_timeout_sec())
    if dabflow:
        pkgs = packages_for_dabflow_view_url_attempts(serial, "")
    else:
        pkgs = packages_for_view_url_attempts(serial, "")
    if dabflow:
        try:
            automation_on_sys_path()
            import emulator_ad_mode as _eam
            from adb_wrapper import AdbWrapper

            paused = _eam.pause_tor_for_ads(
                AdbWrapper(), serial, _wiz_phone_idx_for_tor(serial)
            )
        except Exception:
            return False, (
                "This phone's exit was not pinned, so the page was not opened."
            )
        if (
            isinstance(paused, dict)
            and paused.get("ok") is False
            and not paused.get("skipped")
        ):
            return False, (
                "This phone's exit was not pinned, so the page was not opened."
            )
    if pkgs and "org.chromium.chrome" in pkgs:
        try:
            from browser_setup import reset_chromium_session

            reset_chromium_session(serial)
        except Exception:
            pass
    if dabflow and pkgs:
        for pkg in pkgs:
            if pkg == "org.chromium.chrome":
                continue
            adb("shell", "am", "force-stop", pkg, serial=serial)
        try:
            import mumu_fingerprint as _mf

            _mf.ensure_fingerprint_before_browse(serial, log_fn=lambda m: None)
        except Exception:
            pass
        time.sleep(0.4)
        attempts = [am_start_view_url_argv(url, package=pkg) for pkg in pkgs]
    else:
        attempts = [am_start_view_url_argv(url)]
        for pkg in pkgs:
            attempts.append(am_start_view_url_argv(url, package=pkg))
    # No Chrome-specific component / package fallback: operator wants device default browser
    # so the system http_proxy → Tor path is honored. Chromium bypasses that proxy in many
    # builds and triggers ERR_TIMED_OUT. Set PHARMFLOW_CHROME_FALLBACK_INTENTS=1 to opt back in.
    if os.environ.get("PHARMFLOW_CHROME_FALLBACK_INTENTS", "").strip().lower() in (
        "1", "true", "yes", "on"
    ):
        attempts.extend(
            [
                am_start_view_url_argv(url, package="com.android.chrome"),
                am_start_view_url_argv(
                    url,
                    browser_component="com.android.chrome/com.google.android.apps.chrome.Main",
                ),
            ]
        )
    _ou_debug = os.environ.get("PHARMFLOW_OPEN_URL_DEBUG", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if _ou_debug:
        print(
            f"[pharmflow] open_url DEBUG serial={serial} candidates={pkgs[:8]} "
            f"attempts={len(attempts)}"
        )
    last_fail: str | None = None
    seen: set[tuple[str, ...]] = set()
    for argv in attempts:
        key = tuple(argv)
        if key in seen:
            continue
        seen.add(key)
        out = adb(*argv, serial=serial, timeout=am_t)
        low = (out or "").lower()
        if _ou_debug:
            print(
                f"[pharmflow] open_url DEBUG attempt serial={serial} argv={' '.join(argv[:8])} "
                f"out={(out or '')[:160].strip()}"
            )
        if _am_start_landed(out):
            _wiz_wait_browser_pid_after_open(serial, pkgs)
            try:
                _st = _wiz_settle_after_open_url(fast=fast_pre_site)
                if _st > 0:
                    time.sleep(_st)
            except (TypeError, ValueError):
                pass
            if pkgs and "org.chromium.chrome" in pkgs:
                try:
                    import chromium_fre_uia as _fre

                    _fre.dismiss_chromium_fre_after_open(serial)
                except Exception:
                    pass
            if dabflow:
                _wiz_apply_dabflow_mantis_patch(serial, url)
            return True, tor_note
        if last_fail is None or len(str(last_fail)) < len(out or ""):
            last_fail = (out or "").strip().replace("\r", " ")

    fail_txt = (last_fail or "").strip()
    if len(fail_txt) > 240:
        fail_txt = fail_txt[:237] + "..."
    print(
        f"[pharmflow] open_url FAILED serial={serial} url={url[:80]} "
        f"attempts={len(seen)} last={fail_txt[:120]!r}"
    )
    return False, tor_note or fail_txt or "The phone did not open a browser."


def describe_step(step):
    t = step.get("type", "")
    if t == "open_url":
        u = step.get("url", "")
        pws = step.get("post_wait_secs")
        if pws is not None and pws != "":
            try:
                extra = f"  (+{float(pws):g}s after open)"
            except (TypeError, ValueError):
                extra = ""
        else:
            extra = ""
        return f"Open URL  →  {u}{extra}"
    if t == "tap":
        return f"Tap  →  ({step.get('x', 0)}, {step.get('y', 0)})"
    if t == "wait":
        return f"Wait  →  {step.get('seconds', 1)}s"
    if t == "swipe":
        return (f"Swipe  →  ({step.get('x1', 0)},{step.get('y1', 0)})"
                f"  →  ({step.get('x2', 0)},{step.get('y2', 0)})")
    if t == "keyevent":
        return f"Key  →  {step.get('key', 'BACK')}"
    if t == "close_app":
        return f"Close app  →  {step.get('package') or 'default browser'}"
    if t == "clear_cookies":
        return "Clear cookies"
    if t == "rotate_identity":
        return "New internet location + fresh device ID"
    if t == "full_reset":
        return "Full identity reset"
    if t == "type_text":
        return f"Type  →  \"{step.get('text', '')}\""
    return f"Step  →  {t}" if t else "Step"


def _normalize_sequence_steps(steps: list) -> list:
    """Coerce MuMu/PharmFlow sequence JSON (e.g. string wait.seconds) before storing in state."""
    automation_on_sys_path()
    try:
        from sequence_normalize import normalize_automation_steps
    except ImportError:
        return list(steps)
    try:
        return normalize_automation_steps(steps)
    except (TypeError, ValueError):
        return list(steps)


def execute_steps(steps, serial):
    automation_on_sys_path()
    try:
        import browse_proxy as _bp

        if _bp.browse_proxy_mode() == "tor":
            _wiz_repair_proxy_adb_reverse(serial)
    except Exception:
        pass
    from browser_adb import (
        browser_pkg_for_clear,
        invalidate_webview_inset_cache,
        looks_like_package,
        monkey_launch_reported,
        pm_clear_reported,
        webview_content_top_inset,
    )
    from sequence_geometry import baseline_from_step, baseline_y_to_screen_y, parse_wm_size_output, scale_point
    from session_notes_uia import dismiss_session_notes_verified, wait_session_notes_gone
    from sequence_normalize import step_is_fast_phase
    pkg_re = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.]*$")

    raw_wm = adb("shell", "wm", "size", serial=serial)
    phys = parse_wm_size_output(raw_wm or "")

    last_open_url: str | None = None

    for step in steps:
        t = step.get("type", "")
        if t == "open_url":
            url = str(step.get("url", "") or "https://google.com")
            try:
                pr = urllib.parse.urlparse(url)
                if pr.scheme not in ("http", "https") or not pr.netloc or " " in url:
                    print(f"[pharmflow] sequence open_url failed serial={serial}: not a web address")
                    return False
            except Exception:
                print(f"[pharmflow] sequence open_url failed serial={serial}: not a web address")
                return False
            skip_launch = last_open_url == url
            if skip_launch:
                print(f"[pharmflow] execute_steps: skip duplicate open_url serial={serial} url={url[:80]}")
            else:
                invalidate_webview_inset_cache(serial)
                if "getdabflow.app" in url.lower():
                    try:
                        from browser_setup import prepare_for_dabflow_open

                        prepare_for_dabflow_open(
                            serial,
                            url,
                            log=lambda m: print(f"[pharmflow] {m}", flush=True),
                        )
                    except Exception as _prep_exc:
                        print(f"[pharmflow] dabflow browser prep failed serial={serial}: {_prep_exc}", flush=True)
                _ou_ok, _ou_note = chrome_open_url(serial, url, fast_pre_site=step_is_fast_phase(step))
                if not _ou_ok:
                    print(f"[pharmflow] sequence open_url failed serial={serial}: {_ou_note}")
                    return False
                last_open_url = url
            try:
                pws = step.get("post_wait_secs", None)
                if pws is not None and pws != "":
                    base = max(0.0, float(pws))
                    if "getdabflow.app" in url.lower():
                        automation_on_sys_path()
                        from dabflow_layout import AGE_GATE_OPEN_POST_WAIT_MAX_SEC

                        phase = str(step.get("phase") or "").lower()
                        cp = str(step.get("checkpoint") or "").lower()
                        if step_is_fast_phase(step) or phase in ("pre_site_fast", "") or cp in ("loaded", ""):
                            base = min(base, AGE_GATE_OPEN_POST_WAIT_MAX_SEC)
                    try:
                        extra = float(os.environ.get("PHARMFLOW_OPEN_URL_EXTRA_WAIT", "") or 0)
                    except (TypeError, ValueError):
                        extra = 0.0
                    if step_is_fast_phase(step):
                        extra = 0.0
                    extra = max(0.0, extra)
                    time.sleep(base + extra)
                else:
                    time.sleep(0.8 if not step_is_fast_phase(step) else 0.2)
            except (TypeError, ValueError):
                time.sleep(0.8 if not step_is_fast_phase(step) else 0.2)
            if "getdabflow.app" in url.lower():
                automation_on_sys_path()
                try:
                    from dabflow_mantis_client_patch import maybe_apply_after_open_url_step

                    maybe_apply_after_open_url_step(
                        serial,
                        url,
                        _wiz_phone_idx_for_tor(serial),
                    )
                except Exception:
                    pass
        elif t == "launch_app":
            pkg = str(step.get("package", "")).strip()
            if not pkg_re.match(pkg):
                print(f"[pharmflow] sequence launch_app did not land serial={serial} pkg={pkg or '(empty)'}")
                return False
            launched = adb(
                "shell",
                "monkey",
                "-p",
                pkg,
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
                serial=serial,
            )
            if not monkey_launch_reported(launched or "", ""):
                print(f"[pharmflow] sequence launch_app did not land serial={serial} pkg={pkg}")
                return False
            try:
                pws = step.get("post_wait_secs", None)
                if pws is not None and pws != "":
                    base = max(0.0, float(pws))
                    try:
                        extra = float(os.environ.get("PHARMFLOW_OPEN_URL_EXTRA_WAIT", "") or 0)
                    except (TypeError, ValueError):
                        extra = 0.0
                    extra = max(0.0, extra)
                    time.sleep(base + extra)
                else:
                    time.sleep(2.0)
            except (TypeError, ValueError):
                time.sleep(2.0)
        elif t == "tap":
            is_age = bool(
                step.get("age_verification") is True
                or step.get("age_gate") is True
                or str(step.get("checkpoint", "")).strip().lower() in ("age_verification", "age_gate")
            )
            pre_ms = float(step.get("pre_wait_ms", 0) or 0)
            if is_age:
                automation_on_sys_path()
                from dabflow_layout import (
                    AGE_GATE_PRE_WAIT_MAX_MS,
                    age_gate_page_bounds,
                    age_gate_tap_page_coords,
                )

                pre_ms = min(AGE_GATE_PRE_WAIT_MAX_MS, pre_ms)
            if pre_ms > 0:
                time.sleep(pre_ms / 1000.0)
            try:
                retries = int(step.get("retries", 1) or 1)
            except (TypeError, ValueError):
                retries = 1
            if is_age:
                retries = max(retries, 5)
            retries = max(1, retries)
            try:
                jitter = int(step.get("jitter", 0) or 0)
            except (TypeError, ValueError):
                jitter = 0
            jitter = max(0, jitter)
            if is_age:
                jitter = min(jitter, 6)
            bw, bh = baseline_from_step(step)
            bx0, by0 = int(step.get("x", 0)), int(step.get("y", 0))
            if is_age:
                automation_on_sys_path()
                from dabflow_layout import age_gate_page_bounds, age_gate_tap_page_coords

                bx0, by0 = age_gate_tap_page_coords()
                age_x_lo, age_x_hi, age_y_lo, age_y_hi = age_gate_page_bounds()
            _cp_tap = str(step.get("checkpoint", "")).strip().lower()
            if _cp_tap == "tab_stats":
                wait_session_notes_gone(serial, timeout_sec=10.0)
            if step.get("ad_selected") and _cp_tap and not step.get("mantis_hardcode"):
                try:
                    automation_on_sys_path()
                    import emulator_ad_mode as _eam

                    _eam.prepare_ad_tap(
                        serial,
                        _cp_tap,
                        log_fn=lambda m: print(f"[pharmflow] {m}", flush=True),
                    )
                except Exception:
                    pass
            is_bottom_nav = bool(step.get("bottom_nav"))
            wv_top = webview_content_top_inset(serial, force_refresh=is_age)
            if phys:
                bx, by_page = scale_point(bx0, by0, phys[0], phys[1], bw, bh)
                if is_age:
                    age_x_min, _ = scale_point(age_x_lo, 0, phys[0], phys[1], bw, bh)
                    age_x_max, _ = scale_point(age_x_hi, 0, phys[0], phys[1], bw, bh)
                    _, age_y_lo_s = scale_point(0, age_y_lo, phys[0], phys[1], bw, bh)
                    _, age_y_hi_s = scale_point(0, age_y_hi, phys[0], phys[1], bw, bh)
                else:
                    age_x_min, _ = scale_point(286, 0, phys[0], phys[1], bw, bh)
                    age_x_max, _ = scale_point(432, 0, phys[0], phys[1], bw, bh)
                    _, age_y_lo_s = scale_point(0, 878, phys[0], phys[1], bw, bh)
                    _, age_y_hi_s = scale_point(0, 946, phys[0], phys[1], bw, bh)
                if is_bottom_nav:
                    by = by_page
                else:
                    by = baseline_y_to_screen_y(by_page, phys_h=phys[1], base_h=bh, wv_top=wv_top)
                age_y_min = baseline_y_to_screen_y(age_y_lo_s, phys_h=phys[1], base_h=bh, wv_top=wv_top)
                age_y_max = baseline_y_to_screen_y(age_y_hi_s, phys_h=phys[1], base_h=bh, wv_top=wv_top)
            else:
                bx, by_page = bx0, by0
                if is_age:
                    age_x_min, age_x_max = age_x_lo, age_x_hi
                    age_y_lo_s, age_y_hi_s = age_y_lo, age_y_hi
                else:
                    age_x_min, age_x_max = 286, 432
                    age_y_lo_s, age_y_hi_s = 878, 946
                if is_bottom_nav:
                    by = by_page
                else:
                    by = baseline_y_to_screen_y(by_page, phys_h=bh, base_h=bh, wv_top=wv_top)
                age_y_min = baseline_y_to_screen_y(age_y_lo_s, phys_h=bh, base_h=bh, wv_top=wv_top)
                age_y_max = baseline_y_to_screen_y(age_y_hi_s, phys_h=bh, base_h=bh, wv_top=wv_top)
            age_tapped_uia = False
            if is_age:
                try:
                    automation_on_sys_path()
                    from age_gate_uia import wait_for_age_yes_button

                    uia_center = wait_for_age_yes_button(serial, timeout_sec=12.0)
                except Exception:
                    uia_center = None
                if uia_center:
                    ucx, ucy = uia_center
                    tap_landed = False
                    for r in range(retries):
                        jx = ucx + (random.randint(-jitter, jitter) if jitter else 0)
                        jy = ucy + (random.randint(-jitter, jitter) if jitter else 0)
                        rc, text = adb_result(
                            "shell",
                            "input",
                            "tap",
                            str(max(0, jx)),
                            str(max(0, jy)),
                            serial=serial,
                        )
                        tap_landed = tap_landed or input_command_landed(rc, text)
                        if r + 1 < retries:
                            time.sleep(random.uniform(0.12, 0.22))
                    if not tap_landed:
                        print(f"[pharmflow] sequence tap did not land serial={serial}")
                        return False
                    age_tapped_uia = True
            if not age_tapped_uia:
                tap_landed = False
                for r in range(retries):
                    jx = bx + (random.randint(-jitter, jitter) if jitter else 0)
                    jy = by + (random.randint(-jitter, jitter) if jitter else 0)
                    if is_age:
                        jx = min(age_x_max, max(age_x_min, jx))
                        jy = min(age_y_max, max(age_y_min, jy))
                    rc, text = adb_result(
                        "shell", "input", "tap",
                        str(max(0, jx)), str(max(0, jy)), serial=serial,
                    )
                    tap_landed = tap_landed or input_command_landed(rc, text)
                    if r + 1 < retries:
                        gap = random.uniform(0.12, 0.22) if is_age else random.uniform(0.08, 0.18)
                        time.sleep(gap)
                if not tap_landed:
                    print(f"[pharmflow] sequence tap did not land serial={serial}")
                    return False
            if is_age:
                from dabflow_layout import AGE_GATE_POST_TAP_WAIT_SEC

                time.sleep(AGE_GATE_POST_TAP_WAIT_SEC)
            _cp_skip = str(step.get("checkpoint", "")).strip().lower()
            if _cp_skip == "popup_dismiss" or step.get("verify_dismiss") is True:
                def _json_skip_tap(_bx, _by_page):
                    _by_s = baseline_y_to_screen_y(_by_page, phys_h=phys[1] if phys else bh, base_h=bh, wv_top=webview_content_top_inset(serial, force_refresh=False))
                    rc, text = adb_result(
                        "shell", "input", "tap",
                        str(max(0, _bx)), str(max(0, _by_s)), serial=serial,
                    )
                    if not input_command_landed(rc, text):
                        print(f"[pharmflow] sequence popup dismiss tap did not land serial={serial}")
                if not dismiss_session_notes_verified(serial, json_tap=(bx0, by0), json_tap_fn=_json_skip_tap):
                    print(f"[pharmflow] sequence popup dismiss did not land serial={serial}")
                    return False
            elif step.get("ad_selected") and _cp_skip and not step.get("mantis_hardcode"):
                try:
                    automation_on_sys_path()
                    import emulator_ad_mode as _eam

                    _eam.maybe_fallback_ad_open_url(
                        serial,
                        _cp_skip,
                        open_url_fn=lambda s, u: chrome_open_url(s, u),
                        log_fn=lambda m: print(f"[pharmflow] {m}", flush=True),
                    )
                except Exception:
                    pass
        elif t == "wait":
            time.sleep(float(step.get("seconds", 1)))
            if step.get("until_session_notes_gone") is True or str(step.get("checkpoint", "")).strip().lower() == "popup_dismissed":
                if not wait_session_notes_gone(serial, timeout_sec=8.0):
                    print(f"[pharmflow] sequence session notes still up serial={serial}")
                    return False
        elif t == "swipe":
            sw_bw, sw_bh = baseline_from_step(step)
            x1, y1 = int(step.get("x1", 0)), int(step.get("y1", 0))
            x2, y2 = int(step.get("x2", 0)), int(step.get("y2", 0))
            wv_top_sw = webview_content_top_inset(serial, force_refresh=False)
            if phys:
                x1, y1p = scale_point(x1, y1, phys[0], phys[1], sw_bw, sw_bh)
                x2, y2p = scale_point(x2, y2, phys[0], phys[1], sw_bw, sw_bh)
                y1 = baseline_y_to_screen_y(y1p, phys_h=phys[1], base_h=sw_bh, wv_top=wv_top_sw)
                y2 = baseline_y_to_screen_y(y2p, phys_h=phys[1], base_h=sw_bh, wv_top=wv_top_sw)
            else:
                y1 = baseline_y_to_screen_y(y1, phys_h=sw_bh, base_h=sw_bh, wv_top=wv_top_sw)
                y2 = baseline_y_to_screen_y(y2, phys_h=sw_bh, base_h=sw_bh, wv_top=wv_top_sw)
            rc, text = adb_result(
                "shell", "input", "swipe",
                str(x1), str(y1), str(x2), str(y2),
                str(step.get("ms", 500)), serial=serial,
            )
            if not input_command_landed(rc, text):
                print(f"[pharmflow] sequence swipe did not land serial={serial}")
                return False
        elif t == "keyevent":
            key = str(step.get("key", "BACK") or "BACK")
            rc, text = adb_result("shell", "input", "keyevent", key, serial=serial)
            if not input_command_landed(rc, text):
                print(f"[pharmflow] sequence keyevent did not land serial={serial} key={key}")
                return False
        elif t == "clear_cookies":
            preferred = str(step.get("package", "")).strip()
            pkg = browser_pkg_for_clear(serial, preferred)
            if not pkg:
                print(
                    f"[pharmflow] execute_steps: cookies were not cleared "
                    f"serial={serial} (no browser package)"
                )
                return False
            out = adb("shell", "pm", "clear", pkg, serial=serial)
            if not pm_clear_reported(out or "", ""):
                time.sleep(0.4)
                out = adb("shell", "pm", "clear", pkg, serial=serial)
            if pm_clear_reported(out or "", ""):
                last_open_url = None
            else:
                print(
                    f"[pharmflow] execute_steps: cookies were not cleared "
                    f"serial={serial} pkg={pkg}"
                )
                return False
        elif t == "close_app":
            preferred = str(step.get("package", "")).strip()
            pkg = preferred if looks_like_package(preferred) else ""
            if not pkg:
                pkg = browser_pkg_for_clear(serial, "") or ""
            if not pkg:
                print(
                    f"[pharmflow] execute_steps: app was not closed "
                    f"serial={serial} (no browser package)"
                )
                return False
            rc, text = adb_result("shell", "am", "force-stop", pkg, serial=serial)
            if rc != 0 or "error" in (text or "").lower() or "exception" in (text or "").lower():
                print(
                    f"[pharmflow] execute_steps: app was not closed "
                    f"serial={serial} pkg={pkg}"
                )
                return False
            last_open_url = None
            try:
                automation_on_sys_path()
                import emulator_ad_mode as _eam

                _eam.resume_tor_after_ads(serial, _wiz_phone_idx_for_tor(serial))
            except Exception:
                pass
        elif t == "type_text":
            raw_text = str(step.get("text") or "")
            if not raw_text:
                print(f"[pharmflow] sequence type_text did not land serial={serial} (no text)")
                return False
            text = raw_text.replace(" ", "%s").replace("'", "")
            rc, typed = adb_result("shell", "input", "text", text, serial=serial)
            if not input_command_landed(rc, typed):
                print(f"[pharmflow] sequence type_text did not land serial={serial}")
                return False
        elif t == "rotate_identity":
            idx = _wiz_phone_idx_for_tor(serial)
            try:
                automation_on_sys_path()
                import browse_proxy as _bp

                mode = _bp.browse_proxy_mode()
                if mode in ("scramble", "direct", "upstream"):
                    from adb_wrapper import AdbWrapper
                    import emulator_ad_mode as _eam

                    scrambled = _eam.scramble_device_session(
                        AdbWrapper(),
                        serial,
                        idx,
                        log_fn=lambda m: print(f"[pharmflow] {m}", flush=True),
                    )
                    if not (isinstance(scrambled, dict) and scrambled.get("ok")):
                        print(
                            f"[pharmflow] sequence rotate_identity scramble did not land "
                            f"serial={serial}"
                        )
                        return False
                else:
                    import tor_manager as _tm

                    rotated = _tm.rotate_identity_adb(serial, idx)
                    proxy = str((rotated or {}).get("http_proxy") or "")
                    pinned = (
                        isinstance(rotated, dict)
                        and rotated.get("circuit_rotated")
                        and rotated.get("http_proxy_applied")
                        and proxy.startswith("127.0.0.1:")
                        and not proxy.endswith(":0")
                    )
                    if not pinned:
                        print(
                            f"[pharmflow] sequence rotate_identity did not pin a loopback exit "
                            f"serial={serial} proxy={proxy}"
                        )
                        return False
            except Exception as exc:
                print(f"[pharmflow] sequence rotate_identity failed serial={serial}: {exc}")
                return False
        elif t == "full_reset":
            idx = _wiz_phone_idx_for_tor(serial)
            ap = str(_pharmflow_install_root() / "automation")
            if ap not in sys.path:
                sys.path.insert(0, ap)
            import tor_manager as _tm

            reset = _tm.full_identity_reset(serial, idx)
            landed_reset = (
                isinstance(reset, dict)
                and reset.get("tor_circuit_rotated")
                and reset.get("http_proxy_applied")
            )
            if landed_reset:
                last_open_url = None
            else:
                print(
                    f"[pharmflow] sequence full_reset did not land a new circuit on a pinned exit "
                    f"serial={serial}"
                )
                return False
            try:
                import emulator_ad_mode as _eam

                _eam.resume_tor_after_ads(serial, idx)
            except Exception:
                pass
        else:
            print(f"[pharmflow] sequence step is not runnable serial={serial} type={t}")
            return False
        if step_is_fast_phase(step):
            time.sleep(0.05)
        elif step.get("phase") == "on_site_human":
            time.sleep(random.uniform(0.05, 0.12))
        else:
            time.sleep(0.4)
    return True


# ─── base page ────────────────────────────────────────────────────────────────

class PageBase(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.app = parent

    def on_enter(self):  pass
    def can_advance(self): return True

    def header(self, title, sub="", eyebrow=None, container=None):
        root = self if container is None else container
        shell = tk.Frame(root, bg=BG)
        shell.pack(fill="x", pady=(0, SP["lg"]))
        if eyebrow:
            tk.Label(
                shell,
                text=str(eyebrow).upper(),
                font=FONT_EYEBROW,
                bg=BG,
                fg=T3,
                justify="left",
                anchor="w",
            ).pack(fill="x", pady=(0, SP["xs"]))
        tk.Label(
            shell,
            text=title,
            font=FONT_PAGE_TITLE,
            bg=BG,
            fg=T1,
            justify="left",
            anchor="w",
        ).pack(fill="x")
        if sub:
            sub_lbl = tk.Label(
                shell,
                text=sub,
                font=FS,
                bg=BG,
                fg=T2,
                justify="left",
                anchor="w",
            )
            sub_lbl.pack(fill="x", pady=(SP["sm"], 0))
            bind_responsive_wraplength(sub_lbl, shell, pad=8)

    def btn(self, parent, text, cmd, color=ACCENT, width=None, side="left", pady=7):
        kw = dict(
            text=text, command=cmd,
            font=("Segoe UI", 10, "bold"),
            relief="flat", cursor="hand2", pady=pady, padx=14, bd=0,
            highlightthickness=0,
        )
        if width:
            kw["width"] = width
        if color in (ACCENT, GREEN, RED, PURPLE):
            kw["bg"], kw["fg"] = color, ON_ACCENT
        elif color in (BG3, BG4):
            kw["bg"], kw["fg"] = color, T1
        else:
            kw["bg"], kw["fg"] = color, T1
        b = tk.Button(parent, **kw)
        if color == ACCENT:
            style_primary_button(b)
        elif color in (BG3, BG4):
            style_secondary_button(b)
        elif color == RED:
            style_danger_button(b)
        elif color == GREEN:
            b.configure(activebackground=GREEN_ACTIVE, activeforeground=ON_ACCENT)
        elif color == PURPLE:
            b.configure(activebackground=PURPLE_ACTIVE, activeforeground=ON_ACCENT)
        b.pack(side=side, padx=(0, 8))
        return b

    def code_row(self, parent, text):
        row = tk.Frame(parent, bg=BG_LOG_ROW, padx=10, pady=8)
        row.pack(fill="x", pady=(4, 0))
        tk.Label(row, text=text, font=FM, bg=BG_LOG_ROW, fg=GREEN,
                 anchor="w").pack(side="left", fill="x", expand=True)
        tk.Button(row, text="Copy", font=FS, bg=BG3, fg=T1,
                  relief="flat", cursor="hand2", padx=8,
                  command=lambda t=text: (self.clipboard_clear(),
                                          self.clipboard_append(t))).pack(side="right")


# ─── page 1: welcome ──────────────────────────────────────────────────────────

class WelcomePage(PageBase):
    def __init__(self, parent):
        super().__init__(parent)
        top = self.winfo_toplevel()
        self._welcome_images: list[tk.PhotoImage] = []

        # Hero card: title + subtitle + two columns (brand lives in sidebar only).
        hero_inner = instruction_card(self, pad=SP["page"])
        hero_inner.pack(fill="x", pady=(0, SP["lg"]))

        tk.Label(
            hero_inner,
            text="Start here",
            font=FONT_PAGE_TITLE,
            bg=BG2,
            fg=T1,
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            hero_inner,
            text=(
                "MuMu users: use PharmFlow Phone Setup tab first (checklist + GO). "
                "This advanced wizard covers teams, sequences, and extra options."
            ),
            font=FONT_LEAD,
            bg=BG2,
            fg=T2,
            anchor="w",
            justify="left",
            wraplength=840,
        ).pack(fill="x", pady=(SP["sm"], SP["md"]))
        tk.Label(
            hero_inner,
            text=(
                "Google-phone (AVD) users: start here — no separate setup exe needed."
            ),
            font=FONT_LEAD,
            bg=BG2,
            fg=T2,
            anchor="w",
            justify="left",
            wraplength=840,
        ).pack(fill="x", pady=(SP["sm"], SP["lg"]))

        mumu_setup_callout(hero_inner).pack(fill="x", pady=(0, SP["lg"]))

        cols = tk.Frame(hero_inner, bg=BG2)
        cols.pack(fill="x")

        col_left = tk.Frame(cols, bg=BG2)
        col_left.pack(side="left", fill="both", expand=True, padx=(0, SP["xl"]))

        tk.Label(
            col_left,
            text="What happens",
            font=FONT_SECTION,
            bg=BG2,
            fg=T1,
            anchor="w",
        ).pack(fill="x")
        bullets = [
            "1. Install what PharmFlow needs on this PC (Java, Python, Tor).",
            "2. Start MuMu phones (Setup exe already hid emulator look if you ran it).",
            "3. Set up Tor — each phone gets its own internet address.",
            "4. Run your phone teams on getdabflow.app.",
        ]
        for line in bullets:
            brow = tk.Frame(col_left, bg=BG2)
            brow.pack(fill="x", pady=(SP["sm"], 0))
            tk.Label(
                brow, text="•", font=FB, bg=BG2, fg=ACCENT_DIM, width=2, anchor="n",
            ).pack(side="left", anchor="n", pady=(2, 0))
            tk.Label(
                brow,
                text=line,
                font=FS,
                bg=BG2,
                fg=T2,
                anchor="w",
                justify="left",
            ).pack(side="left", fill="x", expand=True)
            bind_responsive_wraplength(brow.winfo_children()[-1], col_left, pad=36)

        col_right = tk.Frame(
            cols,
            bg=BG3,
            highlightthickness=1,
            highlightbackground=BORDER,
            padx=SP["md"],
            pady=SP["md"],
        )
        col_right.pack(side="right", fill="y")

        tk.Label(
            col_right,
            text="At a glance",
            font=FONT_SECTION,
            bg=BG3,
            fg=T1,
            anchor="w",
        ).pack(fill="x")
        mini = [
            ("1", "Install & verify"),
            ("2", "Phones & ADB"),
            ("3", "Dashboard live"),
            ("4", "Automate & groups"),
        ]
        for num, title in mini:
            mrow = tk.Frame(col_right, bg=BG3)
            mrow.pack(fill="x", pady=(SP["sm"], 0))
            nb = tk.Frame(mrow, bg=ACCENT_SUBTLE, padx=6, pady=2)
            nb.pack(side="left")
            tk.Label(
                nb,
                text=num,
                font=("Segoe UI", 9, "bold"),
                bg=ACCENT_SUBTLE,
                fg=ACCENT_GLOW,
                width=2,
                anchor="center",
            ).pack()
            tk.Label(
                mrow,
                text=title,
                font=FONT_UI,
                bg=BG3,
                fg=T2,
                anchor="w",
            ).pack(side="left", padx=(SP["sm"], 0))

        # Architecture diagram — canvas only; static content is packed below, NOT inside the callback
        c = tk.Canvas(
            self,
            bg=BG3,
            height=176,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        c.pack(fill="x", pady=(0, SP["lg"]))
        c.bind("<Configure>", lambda e: self._draw_diagram(c))

        # Static "What you get:" section — built once here, never inside _draw_diagram
        tk.Label(self, text="What you get",
                 font=FONT_H2, bg=BG, fg=ACCENT,
                 anchor="w").pack(fill="x", padx=4)
        tk.Label(self, text="Later: Automation, Generator (Setup→Build→Save), Groups, schedules, Launch (browser → getdabflow.app).",
                 font=FS, bg=BG, fg=T3, anchor="w").pack(fill="x", padx=4, pady=(0, SP["sm"]))
        f = instruction_card(self, pad=SP["lg"])
        f.pack(fill="x", pady=(SP["xs"], 0))
        feat_icons = (
            "feat_phones",
            "feat_network",
            "feat_identity",
            "feat_play",
        )
        items = [
            ("Several virtual phones on one PC"),
            ("Automated taps and browsing"),
            ("Groups, schedules, and Tor-backed per-phone IP rotation"),
            ("Browser testing via Chrome (getdabflow.app)"),
        ]
        for stem, text in zip(feat_icons, items):
            row = tk.Frame(f, bg=BG2)
            row.pack(fill="x", pady=4)
            img = load_icon(stem, top)
            if img:
                self._welcome_images.append(img)
                tk.Label(row, image=img, bg=BG2).pack(side="left", padx=(0, 10))
            else:
                tk.Label(row, text="·", font=FB, bg=BG2, fg=T3, width=2).pack(side="left")
            tk.Label(row, text=text, font=FB, bg=BG2, fg=T1,
                     anchor="w").pack(side="left")

    def _draw_diagram(self, c):
        c.delete("all")
        w = c.winfo_width() or 700
        boxes = [
            (ACCENT, "Tools\n(adb / SDK)"),
            (GREEN, "Phones\n(AVD / MuMu)"),
            (ACCENT_DIM, "Browser\ndashboard"),
            (PURPLE, "PharmFlow\nSetup"),
        ]
        bw = 128
        gap = max(8, (w - len(boxes) * bw) // (len(boxes) + 1))
        y1, y2 = 22, 102
        rr = float(RADIUS["md"])
        positions = []
        for i, (col, label) in enumerate(boxes):
            x1 = gap + i * (bw + gap)
            x2 = x1 + bw
            mx, my = (x1 + x2) // 2, (y1 + y2) // 2
            draw_round_rect(c, x1, y1, x2, y2, rr, fill=BG4, outline=col, width=2)
            c.create_text(mx, my, text=label, fill=T1,
                          font=("Segoe UI", 9, "bold"), justify="center")
            positions.append((x1, x2, y1, y2))

        for i in range(len(positions) - 1):
            _, rx, _, _ = positions[i]
            lx, _, _, _ = positions[i + 1]
            mid_y = (y1 + y2) // 2
            c.create_line(rx, mid_y, lx, mid_y, fill=T3, width=2, arrow="last")

        c.create_text(
            w // 2, 132,
            text="Runs on this PC — no extra hardware",
            fill=T2, font=("Segoe UI", 9),
        )


# ─── page 2: prerequisites auto-install ──────────────────────────────────────

def _urlretrieve(url, dest, hook=None, timeout=60, retries=3, backoff=2.0):
    """Download with timeout and bounded retries.

    The wizard runs unattended at first-boot time and many environments hit
    transient blips (Wi-Fi reconnect, DNS lag, mirror restarts). A single
    failure used to bubble out and abort the whole setup step. We now retry up
    to ``retries`` times with exponential backoff so flaky networks don't block
    setup, but we never loop forever — total worst-case wait is roughly
    ``timeout * retries`` plus the backoff schedule.

    The per-attempt socket timeout is preserved (no infinite hangs). On the
    final failure we re-raise the underlying exception so callers see the
    real error.
    """
    attempts = max(1, int(retries))
    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    last_err: Exception | None = None
    try:
        for attempt in range(1, attempts + 1):
            try:
                urllib.request.urlretrieve(url, dest, hook)
                return
            except Exception as exc:
                last_err = exc
                if attempt >= attempts:
                    break
                wait = float(backoff) * (2 ** (attempt - 1))
                wait = min(wait, 30.0)
                time.sleep(wait)
    finally:
        socket.setdefaulttimeout(old)
    if last_err is not None:
        raise last_err

def _fetch_latest_tor_url() -> str:
    try:
        with urllib.request.urlopen(
            "https://dist.torproject.org/torbrowser/", timeout=20
        ) as r:
            content = r.read().decode()
        versions = re.findall(r'href="(\d+\.\d+\.\d+)/"', content)
        if versions:
            latest = sorted(versions,
                            key=lambda v: tuple(int(x) for x in v.split(".")))[-1]
            return (
                f"https://dist.torproject.org/torbrowser/{latest}/"
                f"tor-expert-bundle-windows-x86_64-{latest}.tar.gz"
            )
    except Exception:
        pass
    return TOR_FALLBACK_URL


def _find_python() -> str:
    """Return path to a ``python.exe`` on disk (venv / common installs), or ``''``."""
    bundled = _resolve_under_pharmflow(
        "python.exe",
        subdirs=(".venv/Scripts", "venv/Scripts", "tools"),
    )
    if bundled:
        return bundled
    for guess in [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python",
                     "Python313", "python.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python",
                     "Python312", "python.exe"),
        r"C:\Python313\python.exe",
        r"C:\Python312\python.exe",
    ]:
        if os.path.exists(guess):
            return guess
    return ""


def _maybe_autofill_python_cmd() -> None:
    """If Python isn’t usable yet, pick a nearby ``python.exe`` (venv / standard installs)."""
    argv, _disp = _resolve_python_cmd(state.get("python_cmd"))
    if _probe_python_cmd(argv):
        return
    hit = _find_python()
    if hit and Path(hit).is_file():
        state["python_cmd"] = hit
        state["python_cmd_argv"] = [hit]


class PrerequisitesPage(PageBase):
    """Install path + Java/Python/packages/Tor/PharmFlow; then a quick run check."""

    _log_write = lambda self, t: self._log(t)

    def __init__(self, parent):
        super().__init__(parent)
        self._ready   = False
        self._working = False
        self._rows    = {}

        self.header(
            "Install",
            "1. We download what is missing.\n"
            "2. We run a quick check.\n"
            "3. You tap Next.\n"
            "Tor installs near the end so each phone can browse from a different place on the internet.",
        )

        primary = tk.Frame(
            self,
            bg=BG2,
            highlightthickness=1,
            highlightbackground=BORDER_STRONG,
            padx=SP["lg"],
            pady=SP["lg"],
        )
        primary.pack(fill="x", pady=(SP["xs"], SP["md"]))

        path_hint = tk.Label(
            primary,
            text="We default paths from your PharmFlow folder when we can — use Pick a different "
                 "folder only if you need another copy.",
            font=FONT_CAPTION,
            bg=BG2,
            fg=T3,
            anchor="w",
            justify="left",
        )
        path_hint.pack(fill="x", pady=(0, SP["sm"]))
        bind_responsive_wraplength(path_hint, primary, pad=28)

        # ── install path row ──────────────────────────────────────────────────
        path_card = tk.Frame(
            primary,
            bg=BG4,
            padx=SP["lg"],
            pady=SP["md"],
            highlightthickness=1,
            highlightbackground=BORDER_STRONG,
        )
        path_card.pack(fill="x", pady=(0, SP["md"]))
        tk.Label(path_card, text="Folder for PharmFlow:",
                 font=("Segoe UI", 10, "bold"), bg=BG4, fg=T1).pack(side="left")
        self._install_dir = tk.StringVar(value=PHARMFLOW_DEFAULT)
        tk.Entry(path_card, textvariable=self._install_dir, font=FM,
                 bg=BG2, fg=T1, insertbackground=T1, relief="flat",
                 width=36).pack(side="left", padx=8)
        tk.Button(path_card, text="Pick a different folder…", font=FS, bg=BG3, fg=T1,
                  relief="flat", cursor="hand2", padx=8, pady=4,
                  command=self._browse_dir).pack(side="left")

        # ── prerequisite list ─────────────────────────────────────────────────
        list_card = tk.Frame(
            primary,
            bg=BG3,
            padx=SP["lg"],
            pady=SP["card"],
            highlightthickness=1,
            highlightbackground=BORDER_STRONG,
        )
        list_card.pack(fill="x", pady=(0, SP["md"]))

        self._prereq_icons: list[tk.PhotoImage] = []
        top = self.winfo_toplevel()
        items = [
            ("java",     "prereq_java", "Java",                   "For Android tools",           True),
            ("python",   "prereq_python", "Python",               "Runs PharmFlow",                 True),
            ("packages", "prereq_packages", "Python add-ons",      "Dashboard dependencies",      True),
            (
                "tor",
                "prereq_tor",
                "Tor",
                "Gives each phone its own internet location for browsing.",
                False,
            ),
            ("pharmflow",   "prereq_pharmflow", "PharmFlow files",       "App + automation folder",     True),
        ]
        for key, icon_stem, name, desc, required in items:
            row = tk.Frame(list_card, bg=BG2, pady=5)
            row.pack(fill="x")
            pic = load_icon(icon_stem, top)
            if pic:
                self._prereq_icons.append(pic)
                tk.Label(row, image=pic, bg=BG2).pack(side="left", padx=(0, 6))
            else:
                tk.Label(row, text="·", font=FB, bg=BG2, fg=T3, width=2).pack(side="left")
            info = tk.Frame(row, bg=BG2)
            info.pack(side="left", fill="x", expand=True)
            name_disp = name + (
                "" if required or key == "tor" else "  (optional)"
            )
            tk.Label(info, text=name_disp,
                     font=("Segoe UI", 10, "bold"), bg=BG2, fg=T1,
                     anchor="w").pack(fill="x")
            tk.Label(info, text=desc, font=FS, bg=BG2, fg=T3,
                     anchor="w").pack(fill="x")
            status_lbl = tk.Label(row, text="—", font=("Segoe UI", 10, "bold"),
                                  bg=BG2, fg=T3, width=22, anchor="e")
            status_lbl.pack(side="right")
            self._rows[key] = status_lbl

        # ── big install button ────────────────────────────────────────────────
        dl_icon = load_icon("icon_download", top)
        if dl_icon:
            self._prereq_icons.append(dl_icon)
        tk.Label(
            primary,
            text="If install doesn’t start on its own:",
            font=("Segoe UI", 11, "bold"),
            bg=BG2,
            fg=T1,
            anchor="w",
        ).pack(fill="x", pady=(0, SP["xs"]))
        ib_kw = dict(
            text="Install everything",
            font=("Segoe UI", 14, "bold"),
            bg=GREEN, fg=ON_ACCENT,
            relief="flat", cursor="hand2",
            padx=24, pady=14, bd=0, highlightthickness=0,
            command=self._install_all,
        )
        if dl_icon:
            ib_kw["image"] = dl_icon
            ib_kw["compound"] = "left"
        self._install_btn = tk.Button(primary, **ib_kw)
        self._install_btn.configure(activebackground=GREEN_ACTIVE, activeforeground=ON_ACCENT)
        self._install_btn.pack(fill="x", pady=(0, 0))

        # ── progress ──────────────────────────────────────────────────────────
        self._progress = ttk.Progressbar(self, mode="determinate", maximum=100)
        self._progress.pack(fill="x", pady=(0, 4))
        self._progress_lbl = tk.Label(self, text="", font=FS, bg=BG, fg=T2)
        self._progress_lbl.pack(anchor="w")

        # ── log ───────────────────────────────────────────────────────────────
        log_fr = tk.Frame(self, bg=BG2)
        log_fr.pack(fill="x", pady=(6, 0))
        self._log_box = tk.Text(log_fr, height=5, font=FM, bg=BG2, fg=T1,
                                relief="flat", wrap="word")
        _attach_readonly_log_text(self._log_box)
        sb = themed_vertical_scrollbar(log_fr, command=self._log_box.yview)
        self._log_box.configure(yscrollcommand=sb.set)
        self._log_box.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self._auto_install_started = False
        self._auto_install_allowed = os.environ.get(
            "PHARMFLOW_WIZARD_AUTO_INSTALL", "1"
        ).strip().lower() not in ("0", "false", "no", "off")

    def on_enter(self):
        """Scan installed tools; optionally auto-run full install."""
        try:
            root = _pharmflow_install_root()
            if (root / "automation" / "dashboard.py").is_file():
                good = str(root.resolve())
                cur = self._install_dir.get().strip()
                replace = False
                if not cur:
                    replace = True
                else:
                    try:
                        p = Path(cur).expanduser().resolve()
                        replace = not (
                            p.is_dir()
                            and (p / "automation" / "dashboard.py").is_file()
                        )
                    except Exception:
                        replace = True
                if replace:
                    self._install_dir.set(good)
                    state["pharmflow_dir"] = good
        except Exception:
            pass
        try:
            _maybe_autofill_pharmflow_dir()
        except Exception:
            pass
        try:
            _maybe_autofill_python_cmd()
        except Exception:
            pass
        threading.Thread(target=self._scan_thread, daemon=True).start()
        if not self._auto_install_allowed or self._auto_install_started:
            return

        def _schedule_auto():
            if self._working or self._auto_install_started:
                return
            if self._check_all():
                return
            self._auto_install_started = True
            self._log(
                "\nStarting install in 3 seconds — or tap Install everything.\n"
            )
            self.after(3000, self._maybe_auto_install)

        self.after(1500, _schedule_auto)

    def _maybe_auto_install(self):
        app = getattr(self, "app", None)
        if app is not None and getattr(app, "_current", -1) != 1:
            return
        if self._working:
            return
        if self._check_all():
            return
        self._install_all()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _browse_dir(self):
        init = self._install_dir.get().strip()
        init_path = init if init and Path(init).is_dir() else None
        d = filedialog.askdirectory(
            title="Choose where to install PharmFlow",
            initialdir=init_path,
        )
        if d:
            self._install_dir.set(d)

    def _log(self, text):
        def _do():
            self._log_box.insert("end", text if text.endswith("\n") else text + "\n")
            self._log_box.see("end")
        self.after(0, _do)

    def _set_row(self, key, text, color=T2):
        def _do():
            lbl = self._rows.get(key)
            if lbl:
                lbl.config(text=text, fg=color)

        self.after(0, _do)

    def _set_progress(self, pct, label=""):
        def _do():
            self._progress["value"] = pct
            self._progress_lbl.config(text=label)

        self.after(0, _do)

    def _download(self, url, dest, label, start_pct, end_pct):
        def hook(block, bsize, total):
            if total > 0:
                done = block * bsize
                frac = min(done / total, 1.0)
                pct  = int(start_pct + frac * (end_pct - start_pct))
                mb   = done / 1_048_576
                tot  = total / 1_048_576
                self._set_progress(pct, f"{label}  {mb:.0f} / {tot:.0f} MB")
        _urlretrieve(url, dest, hook)

    # ── checks ────────────────────────────────────────────────────────────────

    def _check_java(self) -> bool:
        if bool(_find_java_home()):
            return True
        ok, _ = run_cmd(["java", "-version"])
        return ok

    def _check_python(self) -> bool:
        py_argv, _ = _resolve_python_cmd(state.get("python_cmd"))
        return _probe_python_cmd(py_argv)

    def _check_packages(self) -> bool:
        py_argv, py_disp = _resolve_python_cmd(state.get("python_cmd"))
        if not _probe_python_cmd(py_argv):
            return False
        state["python_cmd"] = py_disp
        state["python_cmd_argv"] = list(py_argv)
        ok, out = run_cmd(
            py_argv + [
                "-c",
                "import websockets, psutil, socks; "
                "from zoneinfo import ZoneInfo; ZoneInfo('UTC')",
            ]
        )
        return ok

    def _check_tor(self) -> bool:
        d = state.get("pharmflow_dir", "") or self._install_dir.get()
        if d:
            tor_exe = Path(d) / "automation" / "tor" / "tor.exe"
            if tor_exe.exists():
                return True
        for p in [r"C:\Tor\tor.exe", r"C:\Program Files\Tor\tor.exe"]:
            if Path(p).exists():
                return True
        return False

    def _check_pharmflow(self) -> bool:
        d = state.get("pharmflow_dir", "") or self._install_dir.get()
        if d:
            p = Path(d).resolve()
            if (p / "automation" / "dashboard.py").is_file():
                miss = _automation_bundle_missing(p)
                if not miss:
                    state["pharmflow_dir"] = str(p)
                    return True
                return False
            nested = _find_pharmflow_dashboard_root(p)
            if nested:
                miss = _automation_bundle_missing(nested)
                if not miss:
                    state["pharmflow_dir"] = str(nested)
                    return True
        root = _pharmflow_install_root()
        if (root / "automation" / "dashboard.py").is_file():
            miss = _automation_bundle_missing(root)
            if not miss:
                state["pharmflow_dir"] = str(root)
                return True
        return False

    def _check_all(self):
        checks = {
            "java":     self._check_java,
            "python":   self._check_python,
            "packages": self._check_packages,
            "tor":      self._check_tor,
            "pharmflow":   self._check_pharmflow,
        }
        all_required = True
        for key, fn in checks.items():
            try:
                ok = fn()
            except Exception:
                ok = False
            if ok:
                self._set_row(key, "✅  Ready", GREEN)
            else:
                self._set_row(key, "⬇  Not installed", T2)
                if key in ("java", "python", "packages", "pharmflow"):
                    all_required = False
        return all_required

    def _show_java_manual_btn(self):
        if hasattr(self, "_java_manual_btn"):
            return
        self._java_manual_btn = tk.Button(
            self,
            text="☕  Download Java for Windows ARM64  (opens browser)",
            font=("Segoe UI", 11, "bold"),
            bg=ACCENT, fg=ON_ACCENT,
            relief="flat", cursor="hand2",
            padx=SP["lg"], pady=SP["md"],
            command=lambda: webbrowser.open(JAVA_DOWNLOAD_URL),
        )
        style_primary_button(self._java_manual_btn)
        self._java_manual_btn.pack(fill="x", pady=(6, 0))

    # ── installers ────────────────────────────────────────────────────────────

    def _install_java(self):
        # Prefer native MSI first. Do not use ``platform.machine()`` alone: x64 Python on
        # ARM64 Windows often reports AMD64; ``_machine_arch()`` uses WoA/registry ground truth.
        _pairs = [
            ("ARM64", JAVA_DOWNLOAD_URL, "microsoft-jdk-21-arm64.msi"),
            ("x64", JAVA_DOWNLOAD_URL_X64, "microsoft-jdk-21-x64.msi"),
        ]
        if not (IS_WIN and "arm64" in _machine_arch()):
            _pairs.reverse()
        for label, url, fname in _pairs:
            self._set_row("java", f"⬇  Downloading ({label})…", ACCENT)
            self._log_write(f"Downloading Java JDK 21 ({label})…")
            tmp = Path(os.environ.get("TEMP", "C:\\Temp")) / fname
            try:
                self._download(url, tmp, f"Java JDK ({label})", 2, 18)
            except Exception as e:
                self._log_write(f"  Download failed ({label}): {e}")
                tmp.unlink(missing_ok=True)
                continue
            self._set_row("java", "⚙  Installing…", STATUS_PROGRESS)
            self._log_write(f"Installing Java {label} (silent, no restart)…")
            ok, out = run_cmd(
                ["msiexec", "/i", str(tmp), "/quiet", "/norestart"],
                timeout=300,
            )
            tmp.unlink(missing_ok=True)
            if ok or self._check_java():
                self._set_row("java", "✅  Done", GREEN)
                self._log_write(f"Java installed ✅  ({label})")
                return
            self._log_write(f"  Install failed ({label}): {out[-200:]}")
        self._set_row("java", "❌  Failed", RED)
        self._log_write("Java install failed on both ARM64 and x64 installers.")
        self.after(0, self._show_java_manual_btn)

    def _install_python(self):
        _pairs = [
            ("ARM64", PYTHON_URL,     "python-3.13-arm64.exe"),
            ("x64",   PYTHON_URL_X64, "python-3.13-x64.exe"),
        ]
        # Match Java installer: prefer host arch first (x64 hosts must not try ARM64 first).
        if not (IS_WIN and "arm64" in _machine_arch()):
            _pairs.reverse()
        for label, url, fname in _pairs:
            self._set_row("python", f"⬇  Downloading ({label})…", ACCENT)
            self._log_write(f"Downloading Python 3.13 ({label})…")
            tmp = Path(os.environ.get("TEMP", "C:\\Temp")) / fname
            try:
                self._download(url, tmp, f"Python ({label})", 20, 36)
            except Exception as e:
                self._log_write(f"  Download failed ({label}): {e}")
                tmp.unlink(missing_ok=True)
                continue
            self._set_row("python", "⚙  Installing…", STATUS_PROGRESS)
            self._log_write(f"Installing Python {label}…")
            ok, out = run_cmd(
                [str(tmp), "/quiet",
                 "InstallAllUsers=0", "PrependPath=1", "Include_launcher=0"],
                timeout=300,
            )
            tmp.unlink(missing_ok=True)
            if ok or self._check_python():
                py_argv, py_disp = _resolve_python_cmd(state.get("python_cmd"))
                state["python_cmd"] = py_disp
                state["python_cmd_argv"] = list(py_argv)
                self._set_row("python", "✅  Done", GREEN)
                self._log_write(f"Python installed ✅  ({state['python_cmd']})")
                return
            self._log_write(f"  Install failed ({label}): {out[-200:]}")
        self._set_row("python", "❌  Failed", RED)
        self._log_write("Python install failed on both ARM64 and x64 installers.")

    def _install_packages(self):
        py_argv, py_disp = _resolve_python_cmd(state.get("python_cmd"))
        state["python_cmd"] = py_disp
        state["python_cmd_argv"] = list(py_argv)
        self._set_row("packages", "⚙  Installing…", STATUS_PROGRESS)
        self._set_progress(55, "Installing Python packages…")
        req_txt = pharmflow_default_install_root() / "requirements.txt"
        if req_txt.is_file():
            self._log_write(f"Running: pip install -r {req_txt.name} …\n")
            ok, out = run_cmd(
                py_argv + ["-m", "pip", "install", "--upgrade", "-r", str(req_txt)],
                timeout=180,
            )
            if ok or self._check_packages():
                self._set_row("packages", "✅  Done", GREEN)
                self._log_write("Packages installed ✅  (from requirements.txt)\n")
                return
            self._log_write(f"  pip -r requirements.txt failed: {out[-300:]}\n")
        extras = ["websockets", "psutil", "PySocks", "tzdata"]
        for extra, label in [([], "global"), (["--user"], "--user fallback")]:
            self._log_write(f"Running: pip install {' '.join(extras)} {' '.join(extra)}…\n")
            ok, out = run_cmd(
                py_argv + ["-m", "pip", "install", "--upgrade"] + extra + extras,
                timeout=120,
            )
            if ok or self._check_packages():
                self._set_row("packages", "✅  Done", GREEN)
                self._log_write(f"Packages installed ✅  ({label})\n")
                return
            self._log_write(f"  pip {label} failed: {out[-200:]}\n")
        self._set_row("packages", "❌  Failed", RED)
        self._log_write(
            "pip failed.\nTry in a terminal:\n"
            f"  {py_disp} -m pip install -r requirements.txt\n"
        )

    def _install_tor(self):
        install_dir = Path(state.get("pharmflow_dir", "") or self._install_dir.get())
        tor_dir = install_dir / "automation" / "tor"
        tor_dir.mkdir(parents=True, exist_ok=True)

        if (tor_dir / "tor.exe").exists():
            self._set_row("tor", "✅  Already installed", GREEN)
            self._log_write(
                f"Tor already present at {tor_dir} — skipping re-download "
                f"(avoids overwriting files while the wizard uses this tree).\n"
            )
            return

        self._set_row("tor", "⬇  Finding latest…", ACCENT)
        self._log_write("Looking up latest Tor version…")
        tor_url = _fetch_latest_tor_url()
        self._log_write(f"Downloading: {tor_url}")
        self._set_row("tor", "⬇  Downloading…", ACCENT)

        tmp = Path(os.environ.get("TEMP", "C:\\Temp")) / "pharmflow_tor_bundle.tar.gz"
        try:
            _urlretrieve(tor_url, tmp, timeout=120)
        except Exception as e:
            self._log_write(f"  Download failed: {e}")
            self._set_row("tor", "❌  Failed", RED)
            self._log_write("  Tor download failed — IP rotation will use system Tor if available.")
            return

        self._set_row("tor", "📦  Extracting…", STATUS_PROGRESS)
        self._log_write("Extracting Tor to a temp folder, then merging into automation/tor…")
        ext_root = Path(os.environ.get("TEMP", "C:\\Temp")) / "_pharmflow_tor_extract"
        try:
            if ext_root.exists():
                shutil.rmtree(ext_root)
            ext_root.mkdir(parents=True)
            with tarfile.open(tmp, "r:gz") as tf:
                for member in tf.getmembers():
                    if member.name.startswith("tor/"):
                        member.name = member.name[len("tor/"):]
                        if not member.name:
                            continue
                        tf.extract(member, ext_root)
            inner = ext_root
            if inner.exists():
                _merge_dir_into(inner, tor_dir)
        except Exception as e:
            self._log_write(f"  Extract/merge failed: {e}")
            self._set_row("tor", "❌  Failed", RED)
            self._log_write("  Tor install failed — IP rotation will use system Tor if available.")
            return
        finally:
            tmp.unlink(missing_ok=True)
            shutil.rmtree(ext_root, ignore_errors=True)

        if (tor_dir / "tor.exe").exists():
            self._set_row("tor", "✅  Done", GREEN)
            self._log_write("Tor installed ✅")
        else:
            self._set_row("tor", "⚠  Skipped", T3)
            self._log_write("Tor not found after extract — IP rotation will use system Tor if available.")

    def _install_pharmflow(self):
        install_dir = Path(self._install_dir.get()).resolve()
        live_tree = _install_targets_live_tree(install_dir)

        if self._check_pharmflow():
            self._set_row("pharmflow", "✅  Already here", GREEN)
            self._log_write(f"PharmFlow files already present at {state.get('pharmflow_dir', install_dir)}")
            return

        if live_tree:
            self._log_write(
                "Install folder is (or contains) the running PharmFlow checkout — "
                "will merge updates without deleting the live tree.\n"
            )
            self._log_write(
                "If this path is a git repo, updating with git pull first "
                "(ZIP files never overwrite .git — avoids Access denied on locked objects).\n"
            )
            if _try_git_pull_pharmflow(install_dir, self._log_write):
                root = _find_pharmflow_dashboard_root(install_dir)
                if root:
                    miss = _automation_bundle_missing(root)
                    if miss:
                        self._log_write(
                            "  git pull ran but automation bundle is incomplete — missing:\n    "
                            + "\n    ".join(miss)
                            + "\n"
                        )
                    else:
                        state["pharmflow_dir"] = str(root)
                        self._set_row("pharmflow", "✅  Done", GREEN)
                        self._log_write(f"PharmFlow ready at {root} ✅\n")
                        _sync_sequences_to_user_profile(self._log_write)
                        return

        elif _install_dir_has_any_git(install_dir):
            # Install path is not the live wizard tree, but may still hold a nested clone (e.g. …/PharmFlow/pharmflow-clone).
            self._log_write(
                "Install path contains a git working tree — trying git pull before ZIP (avoids "
                "WinError 5 on locked .git objects).\n"
            )
            if _try_git_pull_pharmflow(install_dir, self._log_write):
                root = _find_pharmflow_dashboard_root(install_dir)
                if root:
                    miss = _automation_bundle_missing(root)
                    if not miss:
                        state["pharmflow_dir"] = str(root)
                        self._set_row("pharmflow", "✅  Done", GREEN)
                        self._log_write(f"PharmFlow ready at {root} ✅\n")
                        _sync_sequences_to_user_profile(self._log_write)
                        return
                    self._log_write(
                        "  git pull ran but automation bundle is incomplete — missing:\n    "
                        + "\n    ".join(miss)
                        + "\n"
                    )

        self._set_row("pharmflow", "⬇  Downloading…", ACCENT)
        self._log_write("Downloading PharmFlow files from GitHub…")
        tmp = Path(os.environ.get("TEMP", "C:\\Temp")) / "pharmflow.zip"
        zip_ok = True
        try:
            _urlretrieve(PHARMFLOW_ZIP_URL, tmp, timeout=120)
        except Exception as e:
            self._log_write(f"  ZIP download failed: {e}")
            tmp.unlink(missing_ok=True)
            zip_ok = False

        if zip_ok:
            self._set_row("pharmflow", "📦  Extracting…", STATUS_PROGRESS)
            self._log_write(f"Extracting ZIP to temp, then merging into {install_dir}…")
            extract_tmp = Path(os.environ.get("TEMP", "C:\\Temp")) / "_pharmflow_zip_extract"
            if extract_tmp.exists():
                shutil.rmtree(extract_tmp)
            extract_tmp.mkdir(parents=True)
            try:
                with zipfile.ZipFile(tmp, "r") as zf:
                    zf.extractall(extract_tmp)
                tmp.unlink(missing_ok=True)
                inner = next(extract_tmp.iterdir(), None)
                src_root = inner if inner and inner.is_dir() else extract_tmp
                if live_tree:
                    install_dir.mkdir(parents=True, exist_ok=True)
                    # Nested clones (e.g. …/PharmFlow/pharmflow-clone/.git) cannot be ZIP-merged; git pull runs above.
                    if _install_dir_has_any_git(install_dir):
                        self._log_write(
                            "  Skipping ZIP merge into this folder — a git repo already exists here "
                            "(merging would touch locked .git objects → WinError 5).\n"
                            "  Prefer: open a terminal in your clone and run  git pull origin\n"
                            "  Or: set install directory to an empty folder for a fresh ZIP extract.\n"
                        )
                    else:
                        _merge_zip_tree_safe(src_root, install_dir)
                        self._log_write(
                            "Merged ZIP contents into the folder (safe merge — skipped .git / VCS dirs).\n"
                        )
                else:
                    if install_dir.exists() and _install_dir_has_any_git(install_dir):
                        self._log_write(
                            "  Refusing ZIP replace — this folder already contains a git working tree "
                            "(nested clone). Choose an empty install path, or run git pull in your clone.\n"
                        )
                        zip_ok = False
                    else:
                        if install_dir.exists():
                            shutil.rmtree(install_dir)
                        install_dir.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(src_root), str(install_dir))
                shutil.rmtree(extract_tmp, ignore_errors=True)
            except Exception as e:
                self._log_write(f"  Extraction failed: {e}")
                zip_ok = False
                shutil.rmtree(extract_tmp, ignore_errors=True)

        root = _find_pharmflow_dashboard_root(install_dir)
        if root:
            miss = _automation_bundle_missing(root)
            if miss:
                self._set_row("pharmflow", "⚠  Incomplete tree", WARNING)
                self._log_write(
                    "  ZIP extracted but automation bundle is incomplete — missing:\n    "
                    + "\n    ".join(miss)
                    + "\n  Trying git fallback…\n"
                )
            else:
                state["pharmflow_dir"] = str(root)
                self._set_row("pharmflow", "✅  Done", GREEN)
                self._log_write(f"PharmFlow installed at {root} ✅")
                _sync_sequences_to_user_profile(self._log_write)
                return

        self._log_write("  ZIP method failed — trying git clone fallback…")
        self._set_row("pharmflow", "⬇  git clone…", STATUS_PROGRESS)

        if live_tree and install_dir == _wizard_runtime_root().resolve():
            self._set_row("pharmflow", "❌  Failed", RED)
            self._log_write(
                "Git clone skipped: install path is this running repo, but automation/dashboard.py "
                "is still missing.\n"
                "Clone or unpack PharmFlow into this folder manually, or choose a different install directory.\n"
            )
            self._log_write(f"Manual: git clone {REPO_URL} \"{install_dir}\"")
            return

        import tempfile as _tf

        clone_dest = install_dir
        temp_clone: Path | None = None
        if not _install_dir_empty_or_absent(install_dir):
            try:
                temp_clone = Path(
                    _tf.mkdtemp(prefix="pharmflow_git_clone_", dir=os.environ.get("TEMP"))
                )
            except OSError:
                temp_clone = Path(_tf.mkdtemp(prefix="pharmflow_git_clone_"))
            clone_dest = temp_clone
            self._log_write(
                f"  Install folder is not empty — cloning to temp, then merging into {install_dir}…\n"
            )

        ok, out = run_cmd(
            ["git", "clone", REPO_URL, str(clone_dest)],
            timeout=120,
        )
        if temp_clone and temp_clone.exists():
            if ok:
                try:
                    install_dir.mkdir(parents=True, exist_ok=True)
                    _merge_dir_into(temp_clone, install_dir)
                except Exception as e:
                    self._log_write(f"  Temp clone merge failed: {e}\n")
                    ok = False
            shutil.rmtree(temp_clone, ignore_errors=True)
        root = _find_pharmflow_dashboard_root(install_dir)
        if root:
            miss = _automation_bundle_missing(root)
            if miss:
                self._set_row("pharmflow", "❌  Incomplete", RED)
                self._log_write(
                    "Git clone finished but automation bundle is still incomplete — missing:\n    "
                    + "\n    ".join(miss)
                    + f"\nManual: git clone {REPO_URL} \"{install_dir}\""
                )
            else:
                state["pharmflow_dir"] = str(root)
                self._set_row("pharmflow", "✅  Done", GREEN)
                self._log_write("PharmFlow installed via git clone ✅")
        else:
            self._set_row("pharmflow", "❌  Failed", RED)
            self._log_write("Both ZIP download and git clone failed.")
            if not ok and (out or "").strip():
                self._log_write(f"  git clone output (tail): {(out or '')[-600:]}\n")
            self._log_write(f"Manual: git clone {REPO_URL} \"{install_dir}\"")

    # ── main install flow ─────────────────────────────────────────────────────

    def _install_all(self):
        if self._working:
            return
        self._working = True
        self._install_btn.config(state="disabled", text="Working… please wait")
        threading.Thread(target=self._install_thread, daemon=True).start()

    def _install_thread(self):
        try:
            self._set_progress(0, "Starting…")

            if not self._check_java():
                self._install_java()
            else:
                self._set_row("java", "✅  Already installed", GREEN)

            self._set_progress(20, "")

            if not self._check_python():
                self._install_python()
            else:
                self._set_row("python", "✅  Already installed", GREEN)
                py_argv, py_disp = _resolve_python_cmd(state.get("python_cmd"))
                state["python_cmd"] = py_disp
                state["python_cmd_argv"] = list(py_argv)

            self._set_progress(40, "")

            if not self._check_packages():
                self._install_packages()
            else:
                self._set_row("packages", "✅  Already installed", GREEN)

            self._set_progress(56, "")

            if not self._check_pharmflow():
                self._install_pharmflow()
            else:
                self._set_row("pharmflow", "✅  Already here", GREEN)

            if not self._check_pharmflow():
                install_root = Path(self._install_dir.get()).resolve()
                found_root = _find_pharmflow_dashboard_root(install_root)
                check_root = found_root if found_root else install_root
                miss = (
                    _automation_bundle_missing(check_root)
                    if (check_root / "automation").exists()
                    else ["automation/"]
                )
                self._set_progress(100, "Incomplete install folder")
                self._set_row("pharmflow", "❌  Incomplete", RED)
                self._log_write(
                    "\nInstall folder is incomplete — dashboard needs these:\n    "
                    + "\n    ".join(miss)
                    + "\n\n"
                    "Check network/antivirus/disk, then try again, or:\n    git clone "
                    + REPO_URL
                    + ' "' + str(check_root) + '"\n'
                )
                self.after(
                    0,
                    lambda: self._install_btn.config(
                        state="normal",
                        text="Try again",
                        bg=RED,
                    ),
                )
                return

            self._set_progress(66, "Quick check…")
            py_argv, _ = _resolve_python_cmd(state.get("python_cmd"))
            cal_root = Path(state.get("pharmflow_dir") or self._install_dir.get()).resolve()
            if not _calibrate_installed_stack(py_argv, cal_root, self._log_write):
                self._set_progress(100, "Didn’t verify — tap Try again")

                def _retry_cal():
                    self._install_btn.config(
                        state="normal",
                        text="Try again",
                        bg=ACCENT,
                        fg=ON_ACCENT,
                    )
                    style_primary_button(self._install_btn)

                self.after(0, _retry_cal)
                return

            self._set_progress(74, "")

            if not self._check_tor():
                self._install_tor()
            else:
                self._set_row("tor", "✅  Already installed", GREEN)

            self._set_progress(100, "Done!")
            self._log_write("\n✅  Done — tap Next.")
            self._ready = True
            self.after(0, lambda: self._install_btn.config(
                state="normal",
                text="Ready — Next →",
                bg=GREEN,
            ))
        except Exception as exc:
            self._log_write(f"\nSomething went wrong: {exc}")
            self.after(0, lambda: self._install_btn.config(state="normal", text="Try again"))
        finally:
            self._working = False

    # ── page hooks ────────────────────────────────────────────────────────────

    def _scan_thread(self):
        all_ok = self._check_all()
        if all_ok:
            self._set_progress(100, "Already set up — tap Next")
            self.after(0, lambda: self._install_btn.config(
                text="Ready — Next →",
                bg=GREEN,
            ))
            self._ready = True
        else:
            self._set_progress(0, "")

    def can_advance(self):
        if not self._ready:
            if self._check_all() and self._check_pharmflow():
                self._ready = True
                return True
            messagebox.showinfo(
                "Almost there",
                "Wait for the green install bar to finish,\n"
                "or tap Install everything.\n\n"
                "When it says Ready, tap Next.",
                parent=self.winfo_toplevel(),
            )
            return False
        return True


# ─── page 3: android sdk auto-install ────────────────────────────────────────

class AndroidStudioPage(PageBase):
    """
    Auto-downloads and installs the Android SDK command-line tools.
    No Android Studio, no terminal, no manual steps.
    """

    _log_write = lambda self, t: self._log(t)

    def __init__(self, parent):
        super().__init__(parent)
        self._ready    = False
        self._working  = False

        self.header(
            "Android tools",
            "One button installs adb, SDK bits, and the emulator (licenses handled for you).\n"
            "On ARM / Snapdragon PCs, the green MuMu card below is usually simpler than Google’s emulator."
        )

        tip_card = instruction_card(self)
        tip_card.pack(fill="x", pady=(0, SP["sm"]))
        tip_outer, tip_body = operator_callout(tip_card, title="Quick path")
        tip_outer.pack(fill="x")
        callout_copy(
            tip_body,
            (
                "1. Tap Install Android tools and wait for the green check.\n"
                "2. On ARM PCs, the MuMu card below is often faster — tap Use MuMu to skip the big download.\n"
                "3. Already have an SDK folder? Pick a different folder and tap Verify folder."
            ),
            wrap_container=tip_card,
            pady_top=0,
        )

        # ── status card ───────────────────────────────────────────────────────
        status_card = instruction_card(self)
        status_card.pack(fill="x", pady=(0, SP["sm"]))

        self._icon_lbl = tk.Label(status_card, text="🔍", font=("Segoe UI", 28),
                                  bg=BG2)
        self._icon_lbl.pack(side="left", padx=(0, 14))

        right = tk.Frame(status_card, bg=BG2)
        right.pack(side="left", fill="x", expand=True)
        self._status_lbl = tk.Label(right, text="Checking for Android SDK…",
                                    font=("Segoe UI", 12, "bold"),
                                    bg=BG2, fg=T1, anchor="w")
        self._status_lbl.pack(fill="x")
        self._detail_lbl = tk.Label(right, text="",
                                    font=FM, bg=BG2, fg=T3,
                                    anchor="w")
        self._detail_lbl.pack(fill="x", pady=(2, 0))
        bind_responsive_wraplength(self._detail_lbl, right, pad=20)

        # ── big install button ────────────────────────────────────────────────
        self._install_btn = tk.Button(
            self,
            text="Install Android tools (SDK + ADB)",
            font=("Segoe UI", 14, "bold"),
            bg=GREEN,
            fg=ON_ACCENT,
            relief="flat",
            cursor="hand2",
            padx=24,
            pady=14,
            command=self._auto_install,
        )
        self._install_btn.configure(
            activebackground=GREEN_ACTIVE,
            activeforeground=ON_ACCENT,
            bd=0,
            highlightthickness=0,
        )
        self._install_btn.pack(fill="x", pady=(0, 10))

        # ── progress bar ──────────────────────────────────────────────────────
        self._progress = ttk.Progressbar(self, mode="determinate", maximum=100)
        self._progress.pack(fill="x", pady=(0, 6))
        self._progress_lbl = tk.Label(self, text="", font=FS, bg=BG, fg=T2)
        self._progress_lbl.pack(anchor="w")

        # ── log box ───────────────────────────────────────────────────────────
        log_fr = tk.Frame(self, bg=BG2)
        log_fr.pack(fill="x", pady=(6, 0))
        self._log_box = tk.Text(log_fr, height=6, font=FM, bg=BG2, fg=T1,
                                relief="flat", wrap="word")
        _attach_readonly_log_text(self._log_box)
        sb = themed_vertical_scrollbar(log_fr, command=self._log_box.yview)
        self._log_box.configure(yscrollcommand=sb.set)
        self._log_box.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # ── MuMuPlayer ARM64 alternative (shown on ARM64 host) ───────────────
        if IS_WIN and "arm64" in _machine_arch():
            mumu_sep = tk.Frame(self, bg=BORDER, height=1)
            mumu_sep.pack(fill="x", pady=(8, 6))
            mumu_outer, mumu_body = operator_callout(self, title="ARM PC: MuMu is simpler here")
            mumu_outer.pack(fill="x", pady=(0, 8))
            callout_copy(
                mumu_body,
                "Google doesn't ship a Windows ARM emulator.\n"
                "Use MuMu for native ARM, multiple instances, and ADB — tap below to skip the big SDK install.",
                wrap_container=mumu_outer,
                pady_top=0,
            )
            mumu_btn_row = tk.Frame(mumu_body, bg=CALLOUT_BG)
            mumu_btn_row.pack(fill="x", pady=(SP["sm"], 0))
            self._mumu_mode_btn = tk.Button(
                mumu_btn_row,
                text="Use MuMu (skip Android SDK)",
                font=("Segoe UI", 11, "bold"),
                bg=GREEN, fg=ON_ACCENT,
                relief="flat", cursor="hand2",
                padx=SP["lg"], pady=SP["sm"], bd=0, highlightthickness=0,
                command=self._activate_mumu_mode,
            )
            self._mumu_mode_btn.configure(activebackground=GREEN_ACTIVE, activeforeground=ON_ACCENT)
            self._mumu_mode_btn.pack(side="left", padx=(0, 10))
            tk.Button(mumu_btn_row,
                      text="Download MuMuPlayer ARM",
                      font=FS, bg=BG3, fg=T1,
                      relief="flat", cursor="hand2", padx=8, pady=6,
                      command=lambda: __import__("webbrowser").open(MUMU_DOWNLOAD_URL),
                      ).pack(side="left")
            tk.Button(
                mumu_btn_row,
                text="Pick a different MuMu CLI…",
                font=FS, bg=BG3, fg=T1,
                relief="flat", cursor="hand2", padx=8, pady=6,
                command=self._browse_mumu_early,
            ).pack(side="left", padx=(6, 0))
            self._mumu_status_lbl = tk.Label(mumu_body, text="",
                                             font=FS, bg=CALLOUT_BG, fg=GREEN)
            self._mumu_status_lbl.pack(anchor="w", pady=(6, 0))

        # ── already installed / manual path ──────────────────────────────────
        sep = tk.Frame(self, bg=BORDER, height=1)
        sep.pack(fill="x", pady=(10, 6))
        note_row = tk.Frame(self, bg=BG)
        note_row.pack(fill="x")
        tk.Label(note_row,
                 text="Android SDK folder (filled automatically when empty):",
                 font=FS, bg=BG, fg=T2).pack(side="left")
        self._path_var = tk.StringVar()
        tk.Entry(note_row, textvariable=self._path_var, font=FM,
                 bg=BG2, fg=T1, insertbackground=T1, relief="flat",
                 width=28).pack(side="left", padx=6)
        tk.Button(note_row, text="Pick a different folder…", font=FS, bg=BG3, fg=T1,
                  relief="flat", cursor="hand2", padx=8, pady=4,
                  command=self._browse).pack(side="left")
        tk.Button(note_row, text="Verify folder", font=FS, bg=BG3, fg=T1,
                  relief="flat", cursor="hand2", padx=8, pady=4,
                  command=self._check).pack(side="left", padx=(4, 0))

    # ── helpers ───────────────────────────────────────────────────────────────

    def _log(self, text):
        def _do():
            self._log_box.insert("end", text if text.endswith("\n") else text + "\n")
            self._log_box.see("end")
        self.after(0, _do)

    def _set_status(self, icon, text, detail="", color=T1):
        def _do():
            self._icon_lbl.config(text=icon)
            self._status_lbl.config(text=text, fg=color)
            self._detail_lbl.config(text=detail)

        self.after(0, _do)

    def _set_progress(self, pct, label=""):
        def _do():
            self._progress["value"] = pct
            self._progress_lbl.config(text=label)

        self.after(0, _do)

    def _has_java(self):
        # Delegate to the shared helper which checks JBR, all common locations, etc.
        return bool(_find_java_home())

    # ── auto install ──────────────────────────────────────────────────────────

    def _auto_install(self):
        if self._working:
            return
        self._working = True
        self._install_btn.config(state="disabled", text="Working… please wait")
        threading.Thread(target=self._install_thread, daemon=True).start()

    def _install_thread(self):
        try:
            self._do_install()
        except Exception as exc:
            self._log_write(f"\n❌  Unexpected error: {exc}")
            self._set_status("❌", "Something went wrong. See the log below.", color=RED)
        finally:
            self._working = False
            if not self._ready:
                self.after(0, lambda: self._install_btn.config(state="normal",
                                                              text="Try Again"))

    def _do_install(self):
        sdk_path = Path(SDK_DEFAULT_PATH)

        # ── step 0: check if already installed ───────────────────────────────
        self._set_status("🔍", "Checking for an existing Android SDK…", color=T2)
        self._set_progress(5, "Scanning…")
        existing = find_sdk()
        if existing:
            state["sdk_path"] = existing
            self._log_write(f"SDK already found at:  {existing}")
            # Make sure emulator is actually present — if not, install it
            if not Path(sdk_tool("emulator")).exists():
                self._log_write("Emulator missing — installing it now…")
                self._install_missing_tools(existing)
                return
            self._finish_ok(existing)
            return

        # ── step 1: Java check ────────────────────────────────────────────────
        self._set_status("☕", "Checking for Java…", color=T2)
        self._set_progress(8, "Checking Java…")
        if not self._has_java():
            self._log_write("Java not found. The SDK tools need Java to run.")
            self._log_write(f"Download Java here:  {JAVA_DOWNLOAD_URL}")
            self._set_status(
                "☕",
                "Java is required — please install it first.",
                detail="Click the button below, install Java, then click 'Try Again'.",
                color=WARNING,
            )
            self._set_progress(0, "")
            self.after(0, self._show_java_button)
            self._working = False
            self.after(0, lambda: self._install_btn.config(
                state="normal", text="Try Again (after installing Java)"))
            return
        self._log_write("Java found ✅")

        # ── step 2: create SDK folder ─────────────────────────────────────────
        self._set_status("📁", "Creating SDK folder…", color=T2)
        self._set_progress(12, "Creating folders…")
        tools_dir = sdk_path / "cmdline-tools"
        tools_dir.mkdir(parents=True, exist_ok=True)
        self._log_write(f"SDK folder:  {sdk_path}")

        # ── step 3: download cmdline-tools zip ────────────────────────────────
        zip_path = sdk_path / "cmdline-tools" / "cmdline-tools.zip"
        if zip_path.exists():
            self._log_write("Zip already downloaded — skipping download.")
            self._set_progress(50, "Already downloaded.")
        else:
            self._set_status("⬇", "Downloading Android SDK tools…",
                             detail="~130 MB — this takes a minute on slow connections.",
                             color=ACCENT)

            def _progress_hook(block_num, block_size, total_size):
                if total_size > 0:
                    pct = min(12 + int(block_num * block_size / total_size * 38), 50)
                    mb_done = block_num * block_size / 1_048_576
                    mb_total = total_size / 1_048_576
                    self._set_progress(pct, f"Downloading…  {mb_done:.0f} / {mb_total:.0f} MB")

            downloaded = False
            for try_url in [CMDLINE_TOOLS_URL, CMDLINE_TOOLS_URL_ALT]:
                self._log_write(f"Downloading from:\n  {try_url}")
                try:
                    _urlretrieve(try_url, zip_path, _progress_hook, timeout=120)
                    downloaded = True
                    break
                except Exception as e:
                    self._log_write(f"  Failed ({try_url}): {e}")
                    zip_path.unlink(missing_ok=True)

            if not downloaded:
                self._log_write("Both cmdline-tools URLs failed.")
                self._set_status("❌", "Network blocked. See options below.", color=RED)
                self._set_progress(0, "")
                return

            self._log_write("Download complete ✅")

        # ── step 4: extract zip ───────────────────────────────────────────────
        self._set_status("📦", "Extracting files…", color=T2)
        self._set_progress(55, "Extracting…")
        self._log_write("Extracting zip…")

        extract_tmp = tools_dir / "_extract_tmp"
        if extract_tmp.exists():
            shutil.rmtree(extract_tmp)

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_tmp)

        # The zip ships a remotePackage package.xml (for distribution).
        # sdkmanager reads localPackage format when scanning installed packages.
        # Write the correct localPackage package.xml so sdkmanager sees emulator
        # as installed and doesn't block system image install with a dependency error.
        _write_local_package_xml(
            extract_tmp / "cmdline-tools" / "package.xml",
            path_id="cmdline-tools;latest",
            major=16, minor=0, micro=0,
            display="Android SDK Command-line Tools (latest)",
            license_ref="android-sdk-license",
            ns_type="ns5:genericDetailsType",
            extra_ns='xmlns:ns3="http://schemas.android.com/repository/android/generic/01"',
        )
        latest_dir = tools_dir / "latest"
        if latest_dir.exists():
            shutil.rmtree(latest_dir)
        shutil.move(str(extract_tmp / "cmdline-tools"), str(latest_dir))
        shutil.rmtree(extract_tmp, ignore_errors=True)
        self._log_write("Extraction done ✅")
        self._set_progress(62, "Extracted.")

        # ── step 5: run sdkmanager to install platform-tools + emulator ───────
        state["sdk_path"] = str(sdk_path)
        self._install_missing_tools(str(sdk_path))

    def _install_missing_tools(self, sdk):
        """
        Install platform-tools and emulator via sdkmanager.
        Uses _run_sdkmanager so Java env is injected and licenses are auto-accepted.
        """
        # Before downloading anything, check if the emulator directory exists but is
        # missing device-catalog.xml (avdmanager needs it to list device profiles).
        # Install it now so avdmanager can enumerate hardware profiles for AVD creation.
        if Path(sdk_tool("emulator")).exists():
            self._install_emulator_device_catalog(sdk, log_fn=self._log)

        missing = []
        if not Path(sdk_tool("emulator")).exists():
            missing.append("emulator")
        if not Path(sdk_tool("avdmanager")).exists():
            missing.append("cmdline-tools;latest")
        missing.append("platform-tools")   # always refresh

        self._set_status("⚙", "Installing Android tools…",
                         detail="Downloads ~200 MB. Please wait — do not close the window.",
                         color=STATUS_PROGRESS)
        self._set_progress(60, "Accepting licenses…")
        self._log_write(f"JAVA_HOME: {_find_java_home() or '(not found — Java required)'}")

        # Accept all pending SDK licenses first — required before any install on fresh SDK
        self._log_write("Accepting SDK licenses…")
        _run_sdkmanager(["--licenses"], sdk, log_fn=self._log, timeout=60)

        # Check what packages sdkmanager can actually see — if emulator doesn't show
        # here it means the remote repo fetch is failing (network/proxy/TLS issue).
        self._set_progress(63, "Checking available packages…")
        self._log_write("Checking available packages (fetching remote catalog)…")
        self._set_progress(65, "Running sdkmanager…")
        self._log_write(f"Installing: {', '.join(missing)}")
        ok, out = _run_sdkmanager(
            ["--channel=0"] + missing,
            sdk,
            log_fn=self._log,
            timeout=600,
        )

        self._set_progress(92, "Verifying…")

        if not Path(sdk_tool("emulator")).exists():
            self._log("\n⚠  sdkmanager couldn't install emulator — Java network blocked by firewall.")
            self._log("   Switching to direct Python download (bypasses Java network stack)…\n")
            self._set_status("⬇", "Downloading emulator directly…",
                             detail="Java is blocked by firewall — using Python downloader instead.",
                             color=STATUS_PROGRESS)
            self._set_progress(70, "Direct downloading emulator…")
            ok_emu = _direct_download_emulator(sdk, log_fn=self._log)
            self._set_progress(85, "Direct downloading platform-tools…")
            ok_pt  = _direct_download_platform_tools(sdk, log_fn=self._log)
            self._set_progress(92, "Verifying…")

            if not Path(sdk_tool("emulator")).exists():
                self._log_write("\n❌  Both sdkmanager and direct download failed.")
                self._log_write("    Your network is blocking dl.google.com entirely.")
                self._set_status("❌", "Network blocked. See options below.", color=RED)
                self._set_progress(0, "")
                self.after(0, lambda: self._install_btn.config(state="normal", text="Try Again"))
                self.after(0, self._show_firewall_btn)
                return

            self._install_emulator_device_catalog(sdk, log_fn=self._log)

        self._log_write("emulator        ✅")
        self._log_write("platform-tools  ✅")

        if IS_WIN and "arm64" in _machine_arch():
            self._log_write("ARM64 host — checking emulator binary…")
            _ensure_emulator_meta(sdk, log_fn=self._log)

        self._finish_ok(sdk)



    def _install_emulator_device_catalog(self, sdk, log_fn=None):
        # The emulator/ package contains the emulator binary but NOT device definitions.
        # Those live in emulator/meta/device-catalog.xml — a separate metadata package.
        # Without it, 'avdmanager list device' returns empty → "emulator package must be installed!"
        emu_dir = Path(sdk) / "emulator"
        meta_dir = emu_dir / "meta"
        catalog_file = meta_dir / "device-catalog.xml"

        if catalog_file.exists():
            if log_fn:
                log_fn("  Device catalog already present — skipping metadata install.\n")
            return

        if log_fn:
            log_fn("  Installing emulator device catalog metadata…\n")

        import xml.etree.ElementTree as ET
        try:
            with urllib.request.urlopen(
                "https://dl.google.com/android/repository/repository2-3.xml", timeout=20
            ) as r:
                xml_data = r.read().decode("utf-8")
        except Exception as e:
            if log_fn:
                log_fn("  ⚠  Could not fetch emulator repo XML: " + str(e) + "\n"
                       "    Device profiles may not be available.\n")
            return

        meta_url = None
        try:
            root = ET.fromstring(xml_data)
            for pkg in root.iter():
                if pkg.get("path") == "emulator":
                    for child in pkg.iter():
                        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                        if tag in ("archives", "archive"):
                            for a in child:
                                atag = a.tag.split("}")[-1] if "}" in a.tag else a.tag
                                if atag == "url":
                                    val = (a.text or "").strip()
                                    if val and val.endswith(".zip"):
                                        meta_url = "https://dl.google.com/android/repository/" + val
                                        break
                            if meta_url:
                                break
                    if meta_url:
                        break
        except ET.ParseError:
            pass

        if not meta_url:
            if log_fn:
                log_fn("  ⚠  Could not find emulator meta URL — device profiles may be missing.\n")
            return

        if log_fn:
            log_fn("  Downloading emulator meta: " + meta_url + "\n")

        tmp = Path(sdk) / "_emu_meta.zip"
        try:
            _urlretrieve(meta_url, tmp, timeout=60)
            meta_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(tmp, "r") as zf:
                for member in zf.namelist():
                    if "meta/" in member or "device-catalog" in member:
                        zf.extract(member, emu_dir)
            tmp.unlink(missing_ok=True)

            # Also register the emulator as an installed package (path_id="emulator").
            # avdmanager checks for this before listing device profiles.
            _write_emulator_package_xml(emu_dir)
            _write_local_package_xml(
                meta_dir / "package.xml",
                path_id="emulator;meta",
                major=36, minor=6, micro=4,
                display="Android Emulator Device Metadata",
                license_ref="android-sdk-license",
                ns_type="ns5:genericDetailsType",
                extra_ns='xmlns:ns3="http://schemas.android.com/repository/android/generic/01"',
            )
            if log_fn:
                log_fn("  Emulator device catalog installed ✅\n")
        except Exception as e:
            if log_fn:
                log_fn("  ⚠  Could not install device catalog: " + str(e) + "\n")
            tmp.unlink(missing_ok=True)

    def _finish_ok(self, sdk_path):
        self._set_status("✅", "Android SDK is ready!",
                         detail=f"SDK installed at:  {sdk_path}",
                         color=GREEN)
        self._set_progress(100, "Done!")
        self._log_write(f"\n✅  All good. Click Next → to continue.")
        self._ready = True
        self.after(0, lambda: self._install_btn.config(
            state="normal",
            text="✅  SDK Ready — click Next →",
            bg=GREEN,
        ))

    def _show_firewall_btn(self):
        if hasattr(self, "_fw_btn"):
            return
        self._fw_btn = tk.Button(
            self,
            text="🛡  Allow Java through Windows Firewall  (click → approve UAC prompt)",
            font=("Segoe UI", 11, "bold"),
            bg=ACCENT, fg=ON_ACCENT,
            relief="flat", cursor="hand2",
            padx=SP["lg"], pady=SP["md"],
            command=self._do_firewall,
        )
        style_primary_button(self._fw_btn)
        self._fw_btn.pack(fill="x", pady=(6, 0))

    def _do_firewall(self):
        ok = _add_firewall_exception_for_java()
        if ok:
            self._log_write("\nFirewall rule submitted — approve the UAC prompt that appeared.")
            self._log_write("Then click Try Again.\n")
        else:
            self._log_write("\n❌  Could not launch PowerShell — add the rule manually:\n")
            self._log_write('   Windows Security → Firewall → Advanced → Outbound Rules')
            self._log_write('   → New Rule → Program → browse to java.exe → Allow\n')

    def _show_java_button(self):
        if hasattr(self, "_java_btn"):
            return
        self._java_btn = tk.Button(
            self,
            text="☕  Download Java for Windows ARM64  (opens browser)",
            font=("Segoe UI", 11, "bold"),
            bg=ACCENT, fg=ON_ACCENT,
            relief="flat", cursor="hand2",
            padx=SP["lg"], pady=SP["md"],
            command=lambda: webbrowser.open(JAVA_DOWNLOAD_URL),
        )
        style_primary_button(self._java_btn)
        self._java_btn.pack(fill="x", pady=(6, 0))

    # ── standard page hooks ───────────────────────────────────────────────────

    def _auto_fill_sdk_path_var(self) -> None:
        """Populate SDK path when the field is blank or does not contain ``platform-tools``."""
        cur = self._path_var.get().strip()
        ok = False
        if cur:
            try:
                ok = Path(cur, "platform-tools").exists()
            except Exception:
                ok = False
        if ok:
            return
        got = _resolve_sdk_root_auto()
        if got:
            self._path_var.set(got)
            state["sdk_path"] = got

    def on_enter(self):
        try:
            _maybe_autofill_pharmflow_dir()
        except Exception:
            pass
        if state.get("use_mumu") and IS_WIN:
            mp = (state.get("mumu_mgr_path") or "").strip()
            needs = True
            if mp:
                try:
                    needs = not (Path(mp).is_file() and _is_mumu_manager_cli_path(mp))
                except Exception:
                    needs = True
            if needs:
                hit = _find_mumu_manager()
                if hit:
                    state["mumu_mgr_path"] = str(hit)
        self._auto_fill_sdk_path_var()
        self._check()

    def _browse(self):
        d = filedialog.askdirectory(
            title="Select Android SDK folder  (the one containing platform-tools)",
            initialdir=_sdk_path_browse_initialdir(self._path_var.get()),
        )
        if d:
            self._path_var.set(d)
            self._check()

    def _check(self):
        manual = self._path_var.get().strip()
        if manual and Path(manual, "platform-tools").exists():
            state["sdk_path"] = manual
            self._log_write(f"Manual path set: {manual}\n")

        sdk = state.get("sdk_path", "")
        if not sdk:
            self._set_status("⬇", "Android SDK not installed yet.",
                             detail="Click Install below, or paste folder path above and click Check.",
                             color=T2)
            self._log_write("No SDK path found. Install it or enter a path above.\n")
            self._ready = False
            return False

        self._log_write(f"Checking SDK at: {sdk}\n")

        # Check tools directly in common locations — more reliable than sdk_tool()
        base = Path(sdk)
        has_emu = (base / "emulator" / "emulator.exe").exists() or (base / "emulator" / "emulator").exists()
        has_avd = (base / "cmdline-tools" / "latest" / "bin" / "avdmanager.bat").exists() \
                  or (base / "cmdline-tools" / "latest" / "bin" / "avdmanager").exists() \
                  or (base / "tools" / "bin" / "avdmanager.bat").exists()
        has_sdk = (base / "cmdline-tools" / "latest" / "bin" / "sdkmanager.bat").exists() \
                  or (base / "cmdline-tools" / "latest" / "bin" / "sdkmanager").exists()

        self._log_write(f"  emulator: {'found' if has_emu else 'missing'}\n")
        self._log_write(f"  avdmanager: {'found' if has_avd else 'missing'}\n")
        self._log_write(f"  sdkmanager: {'found' if has_sdk else 'missing'}\n")

        if has_emu and has_avd and has_sdk:
            self._log_write("All tools present!\n")
            self._finish_ok(sdk)
            return True

        missing = []
        if not has_emu: missing.append("emulator")
        if not has_avd: missing.append("avdmanager")
        if not has_sdk: missing.append("sdkmanager")
        self._set_status(
            "⚙",
            f"SDK found but missing: {', '.join(missing)}",
            detail="Click Install missing tools below.",
            color=ACCENT,
        )
        self._log_write(f"Missing: {', '.join(missing)} — click Install below.\n")
        self._install_btn.config(
            state="normal",
            text=f"Install missing tools ({', '.join(missing)})",
            bg=ACCENT,
            fg=ON_ACCENT,
        )
        style_primary_button(self._install_btn)
        self._ready = False
        return False

    def _activate_mumu_mode(self):
        """Set MuMu mode — bypasses SDK requirement entirely."""
        state["use_mumu"] = True
        self._ready = True
        mgr = _find_mumu_manager()
        if mgr:
            lbl = (f"✅ MuMuPlayer found at {_mumu_install_root(mgr)}\n"
                   "   Steps 2 and 3 will use MuMuPlayer — click Next →")
        else:
            lbl = ("✅ MuMu mode activated — click Next →\n"
                   "   Install MuMuPlayer ARM first if you haven't already.")
        if hasattr(self, "_mumu_status_lbl"):
            self._mumu_status_lbl.config(text=lbl)
        if hasattr(self, "_mumu_mode_btn"):
            self._mumu_mode_btn.config(
                text="✅  MuMuPlayer mode active",
                state="disabled", bg=BG3, fg=GREEN)
        self._set_status("✅", "MuMuPlayer ARM64 mode — SDK not needed",
                         detail="Click Next → to continue.", color=GREEN)

    def _browse_mumu_early(self):
        tmp = tk.StringVar(value=state.get("mumu_mgr_path") or "")
        _mumu_ft = [
            ("MuMu CLI", "*.exe"),
            ("nemux-shell-winui.Manager", "nemux-shell-winui.Manager.exe"),
            ("MuMuManager (legacy)", "MuMuManager.exe"),
            ("All files", "*.*"),
        ]
        path = _browse_file(
            self.winfo_toplevel(),
            tmp,
            _mumu_ft,
            _mumu_browse_initialdir,
            title="Select MuMu shell CLI (shell or nx_main folder)",
        )
        if not path:
            return
        if _is_mumu_gui_path(path):
            messagebox.showwarning(
                "Wrong file",
                "That is the MuMu Player app, not the helper tool PharmFlow needs.\n\n"
                "Pick nemux-shell-winui.Manager.exe or MuMuManager.exe in the shell folder:\n"
                "  …\\MuMuPlayerARM\\shell\\nemux-shell-winui.Manager.exe",
                parent=self.winfo_toplevel(),
            )
            return
        if not _is_mumu_manager_cli_path(path):
            messagebox.showwarning(
                "Wrong file",
                "Pick nemux-shell-winui.Manager.exe or MuMuManager.exe.\n\n"
                "Usually here:\n"
                "  …\\MuMuPlayerARM\\shell\\nemux-shell-winui.Manager.exe",
                parent=self.winfo_toplevel(),
            )
            return
        state["mumu_mgr_path"] = path
        if hasattr(self, "_mumu_status_lbl"):
            self._mumu_status_lbl.config(
                text="✅ Saved this path. Now click 'Use MuMu (skip Android SDK)' above.",
                fg=GREEN,
            )

    def can_advance(self):
        if state.get("use_mumu"):
            return True
        if self._ready:
            return True
        messagebox.showinfo(
            "Not ready",
            "Click Install Android tools and wait for completion,\n"
            "or use the green MuMu button on ARM / Snapdragon PCs.",
            parent=self.winfo_toplevel(),
        )
        return False


# ─── page 4: phone farm (create AVDs / MuMu) ─────────────────────────────────

def coerce_phone_count(raw) -> int | None:
    """Positive phone count. None means the field is empty or not a number yet."""
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if n < 1:
        return None
    return n


class PhoneFarmPage(PageBase):
    def __init__(self, parent):
        super().__init__(parent)
        self._done = False
        self.header(
            "Create phones",
            "Google: downloads Android 14 and builds Pixel-style AVDs.\n"
            "MuMu: add instances in MuMu — connect after they boot.\n"
            "Roughly ~2 GB RAM + ~4 GB disk per phone."
        )

        # Phone name prefix
        name_box = tk.Frame(self, bg=BG3, padx=SP["lg"], pady=SP["md"])
        name_box.pack(fill="x", pady=(0, 8))
        tk.Label(name_box, text="Phone name prefix:",
                 font=("Segoe UI", 10, "bold"), bg=BG3, fg=T1, anchor="w").pack(side="left")
        self._prefix_var = tk.StringVar(value=state.get("phone_prefix", "PharmFlow_Phone"))
        tk.Entry(name_box, textvariable=self._prefix_var, font=FM,
                 bg=BG2, fg=T1, insertbackground=T1, relief="flat",
                 width=22).pack(side="left", padx=(8, 6))
        tk.Label(name_box, text="_1, _2, _3…", font=FS, bg=BG3, fg=T3).pack(side="left")
        self._prefix_var.trace_add("write", lambda *_: state.update(
            {"phone_prefix": self._prefix_var.get().strip() or "PharmFlow_Phone"}))

        # Count selection
        count_box = tk.Frame(self, bg=BG3, padx=SP["lg"], pady=SP["lg"])
        count_box.pack(fill="x", pady=(0, 10))
        tk.Label(count_box, text="How many virtual phones?",
                 font=("Segoe UI", 11, "bold"), bg=BG3, fg=T1, anchor="w").pack(fill="x")
        tk.Label(count_box,
                 text="Type any number, or use a shortcut. A host RAM and CPU check "
                      "still runs before each phone boots. There is no phone-count stop.",
                 font=FS, bg=BG3, fg=T2, anchor="w", justify="left", wraplength=640,
                 ).pack(fill="x", pady=(4, 10))

        picker = tk.Frame(count_box, bg=BG3)
        picker.pack(fill="x", pady=(4, 8))

        self._count_btns: dict[int, tk.Button] = {}
        for n in [1, 2, 3, 5, 8, 10]:
            b = tk.Button(picker, text=str(n), width=4,
                          font=("Segoe UI", 12, "bold"),
                          bg=ACCENT if n == 3 else BG2,
                          fg=ON_ACCENT if n == 3 else T1,
                          relief="flat", cursor="hand2",
                          command=lambda v=n: self._pick_count(v))
            b.pack(side="left", padx=3)
            self._count_btns[n] = b

        typed = tk.Frame(count_box, bg=BG3)
        typed.pack(fill="x", pady=(4, 0))
        tk.Label(typed, text="Count:", font=FS, bg=BG3, fg=T1).pack(side="left")
        self._count_var = tk.StringVar(value=str(state.get("num_phones", 3)))
        tk.Entry(
            typed,
            textvariable=self._count_var,
            font=FM,
            bg=BG2,
            fg=T1,
            insertbackground=T1,
            relief="flat",
            width=8,
        ).pack(side="left", padx=(8, 0))
        self._count_var.trace_add("write", lambda *_: self._on_count_typed())

        self._count_lbl = tk.Label(count_box, text="3 phones selected",
                                    font=FS, bg=BG3, fg=T2)
        self._count_lbl.pack(anchor="w", pady=(8, 0))

        # What happens box
        explain = tk.Frame(self, bg=BG2, padx=14, pady=10)
        explain.pack(fill="x", pady=(0, 10))
        tk.Label(explain, text="What clicking Create does:",
                 font=("Segoe UI", 10, "bold"), bg=BG2, fg=T1, anchor="w").pack(fill="x")
        tk.Label(explain,
                 text=f"  1.  Downloads Android 14 {_machine_arch()} system image (~1 GB) — only once\n"
                      "  2.  Creates one Pixel 6 virtual phone per slot\n"
                      "  3.  Each phone gets a unique device ID and storage\n"
                      "  4.  Names them {prefix}_1, {prefix}_2, etc.",
                 font=FB, bg=BG2, fg=T2, justify="left", anchor="w").pack(fill="x", pady=(8, 0))

        # Create + Delete buttons
        create_row = tk.Frame(self, bg=BG)
        create_row.pack(fill="x", pady=(0, 8))
        self._create_btn = tk.Button(create_row,
                                     text="Create phone farm",
                                     font=("Segoe UI", 12, "bold"),
                                     bg=GREEN, fg=ON_ACCENT, relief="flat",
                                     cursor="hand2", command=self._create,
                                     padx=20, pady=10, bd=0, highlightthickness=0)
        self._create_btn.configure(activebackground=GREEN_ACTIVE, activeforeground=ON_ACCENT)
        self._create_btn.pack(side="left", padx=(0, 10))
        top_pf = self.winfo_toplevel()
        trash = load_icon("icon_trash", top_pf)
        del_kw = dict(
            text="Delete all PharmFlow phones",
            font=FS, bg=RED, fg=ON_ACCENT, relief="flat",
            cursor="hand2", command=self._delete_phones,
            padx=10, pady=8, bd=0, highlightthickness=0,
        )
        if trash:
            del_kw["image"] = trash
            del_kw["compound"] = "left"
        del_btn = tk.Button(create_row, **del_kw)
        style_danger_button(del_btn)
        del_btn.pack(side="left", padx=(0, 10))
        # Auto-connect every published guest. Not a fixed 10-port or 8-port range.
        auto_btn = tk.Button(
            create_row,
            text="Auto-Connect All Phones",
            font=FS,
            bg=ACCENT, fg=ON_ACCENT, relief="flat",
            cursor="hand2", command=self._auto_connect_phones,
            padx=10, pady=8, bd=0, highlightthickness=0,
        )
        auto_btn.configure(activebackground=GREEN_ACTIVE, activeforeground=ON_ACCENT)
        auto_btn.pack(side="left", padx=(0, 10))
        self._progress_lbl = tk.Label(create_row, text="", font=FS, bg=BG, fg=T2)
        self._progress_lbl.pack(side="left")

        # Log
        log_fr = tk.Frame(self, bg=BG2)
        log_fr.pack(fill="both", expand=True, pady=(4, 0))
        self._log_box = tk.Text(log_fr, height=7, font=FM, bg=BG2, fg=T1,
                                relief="flat", wrap="word")
        _attach_readonly_log_text(self._log_box)
        sb = themed_vertical_scrollbar(log_fr, command=self._log_box.yview)
        self._log_box.configure(yscrollcommand=sb.set)
        self._log_box.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # MuMuPlayer info panel (hidden on non-MuMu machines at on_enter)
        self._mumu_panel = tk.Frame(self, bg=BG_MUMU, padx=14, pady=12,
                                    highlightthickness=1, highlightbackground=GREEN)
        tk.Label(self._mumu_panel,
                 text="MuMuPlayer ARM64 mode",
                 font=("Segoe UI", 12, "bold"), bg=BG_MUMU, fg=GREEN,
                 anchor="w").pack(fill="x")
        self._mumu_help_lbl = tk.Label(self._mumu_panel,
                 text="Before you start\n"
                      "  • PC: on x86 Windows, turn on VT/CPU virtualization in BIOS and verify in MuMu "
                      "(Help / device diagnostics). Poor VT = slow instances.\n"
                      "  • Right installer: use “Windows ARM” from mumuglobal.com/download on Snapdragon PCs; "
                      "do not mix installers.\n"
                      "  • Network / proxy: campus firewalls and broken DNS can block the emulator; if you "
                      "used VPN or “accelerator” tools in MuMu, stale global HTTP proxy settings can linger "
                      "(MuMu’s network FAQ documents clearing them).\n"
                      "  • Multi-instance: each phone has its own ADB port — enable ADB per instance and use "
                      "distinct instance names so shortcuts don’t overwrite.\n\n"
                      "How to create phones\n"
                      "  1. Open MuMuPlayer (it's in your Start menu or taskbar)\n"
                      "  2. Click the multi-window icon at the top-right\n"
                      "  3. Click '+ New Instance' for each phone you want\n"
                      "  4. In each instance open Settings (≡ or gear) and turn ON ADB / "
                      "debugging — otherwise this PC cannot connect\n"
                      "  5. Leave MuMuPlayer running\n"
                      "  6. Click Next below — PharmFlow does not start MuMuPlayer; it only connects over ADB "
                      "when you're ready\n\n"
                      "Note: MuMu uses OEM-style images (e.g. Google Pixel 8 / GC3VE, HONOR 200 Pro,\n"
                      "  etc.) — whatever appears under Device model here is normal for that template.\n"
                      "  Each instance can be a different model or resolution; PharmFlow connects by ADB serial,\n"
                      "  so mixed farms are fine. Root / writable system may be off unless you enable them\n"
                      "  in MuMu settings per instance.",
                 font=FS, bg=BG_MUMU, fg=T2,
                 anchor="w", justify="left")
        self._mumu_help_lbl.pack(fill="x", pady=(6, 10))
        bind_responsive_wraplength(self._mumu_help_lbl, self._mumu_panel, pad=28)
        tk.Label(
            self._mumu_panel,
            text="PharmFlow does not launch MuMuPlayer — open it yourself from the Start menu or taskbar.",
            font=("Segoe UI", 9, "italic"),
            bg=BG_MUMU,
            fg=T3,
            anchor="w",
        ).pack(fill="x", pady=(0, 4))

        # Docker / cloud phones panel (redroid) — shown when Docker is available
        self._docker_panel = tk.Frame(self, bg="#0b1f1c", padx=14, pady=12,
                                      highlightthickness=1, highlightbackground=ACCENT)
        tk.Label(
            self._docker_panel,
            text="Docker / Cloud phones (redroid)",
            font=("Segoe UI", 12, "bold"),
            bg="#0b1f1c",
            fg=ACCENT_GLOW,
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            self._docker_panel,
            text="If you run redroid containers (Docker Desktop / Linux host), connect them here."
            "\nEach container's published ADB port is connected. There is no 8-port ceiling."
            "\nDocker stays open alongside the farm — connecting never stops containers.",
            font=FS, bg="#0b1f1c", fg=T2, anchor="w", justify="left",
        ).pack(fill="x", pady=(6, 10))
        dock_row = tk.Frame(self._docker_panel, bg="#0b1f1c")
        dock_row.pack(fill="x")
        self._docker_btn = tk.Button(
            dock_row,
            text="Connect Docker phones",
            font=FS,
            bg=ACCENT, fg=ON_ACCENT, relief="flat",
            cursor="hand2", command=self._connect_docker_phones,
            padx=10, pady=8, bd=0, highlightthickness=0,
        )
        self._docker_btn.configure(activebackground=ACCENT_DIM, activeforeground=ON_ACCENT)
        self._docker_btn.pack(side="left", padx=(0, 10))
        self._docker_status_lbl = tk.Label(
            dock_row, text="Docker not checked yet", font=FS, bg="#0b1f1c", fg=T2)
        self._docker_status_lbl.pack(side="left")

    def _connect_docker_phones(self):
        """Read Docker container state and adb-connect the redroid ADB range."""
        self._docker_status_lbl.config(text="Checking Docker…", fg=STATUS_PROGRESS)
        self._log_write("Connecting Docker (redroid) phones…\n")

        def go():
            containers = []
            # Docker Desktop's CLI shim launches the GUI when the engine is
            # down - never run docker here unless the engine is already up.
            try:
                import sys as _sys
                _base = getattr(_sys, "_MEIPASS", None) or str(Path(__file__).resolve().parent.parent)
                if str(_base) not in _sys.path:
                    _sys.path.insert(0, str(_base))
                import docker_guard as _dg
                if not _dg.engine_running():
                    self._log_write("  " + _dg.DOCKER_OFF_MSG + "\n")
                    self._docker_status_lbl.config(
                        text="Docker off - start Docker Desktop yourself, then Connect", fg=WARN_FG
                    )
                    return
            except Exception:
                self._log_write("  Docker guard unavailable - Docker left off.\n")
                self._docker_status_lbl.config(text="Docker off", fg=WARN_FG)
                return
            try:
                import subprocess as _sp
                r = _sp.run(
                    ["docker", "ps", "-a", "--format", "{{.Names}}|{{.Status}}"],
                    capture_output=True, text=True, timeout=20,
                    creationflags=_sp.CREATE_NO_WINDOW if IS_WIN else 0,
                )
                if r.returncode == 0:
                    for line in r.stdout.splitlines():
                        if "|" in line:
                            containers.append(line.split("|", 1)[0])
            except Exception:
                containers = []

            connected = []
            try:
                import preflight_core as _pfc
                connected = _pfc.auto_connect_all_phones(self._log_write)
            except Exception as e:
                self._log_write(f"  ⚠ Docker connect error: {e}\n")
                connected = []

            n_cont = len(containers)
            n_conn = len(connected)
            if n_cont:
                msg = f"{n_cont} container(s) found · {n_conn} phone(s) connected via ADB"
                clr = GREEN if n_conn else WARN_FG
            else:
                msg = "No Docker containers found — start redroid (see cloud_phones/README.md)"
                clr = WARN_FG

            def fin():
                self._docker_status_lbl.config(text=msg, fg=clr)
            self.after(0, fin)
            self._log_write(f"Docker: {msg}\n")

    def _on_count_typed(self):
        n = coerce_phone_count(self._count_var.get())
        if n is None:
            return
        self._pick_count(n)

    def _pick_count(self, n):
        n = coerce_phone_count(n)
        if n is None:
            return
        state["num_phones"] = n
        for num, btn in self._count_btns.items():
            btn.config(bg=ACCENT if num == n else BG2,
                       fg=ON_ACCENT    if num == n else T1)
        if hasattr(self, "_count_var") and self._count_var.get() != str(n):
            self._count_var.set(str(n))
        ram  = n * 2
        disk = n * 4
        self._count_lbl.config(
            text=f"{n} phone{'s' if n != 1 else ''} selected  "
                 f"(~{ram} GB RAM, ~{disk} GB disk needed)")

    def _auto_connect_phones(self):
        """Best-effort ADB connect to existing MuMu + emulator/cloud phones."""
        self._progress_lbl.config(text="Connecting phones…", fg=STATUS_PROGRESS)
        self._log_write("Auto-connecting MuMu + emulator/cloud ADB ports…\n")

        def go():
            try:
                import preflight_core as _pfc
                connected = _pfc.auto_connect_all_phones(self._log_write)
            except Exception as e:
                self._log_write(f"  ⚠ Auto-connect error: {e}\n")
                connected = []
            msg = (f"✅ {len(connected)} phone(s) connected" if connected
                   else "No phones found — open MuMu and enable ADB per instance")
            clr = GREEN if connected else RED

            def fin():
                self._progress_lbl.config(text=msg, fg=clr)
            self.after(0, fin)
            self._log_write(f"Auto-connect: {msg}\n")

    def on_enter(self):
        try:
            _maybe_autofill_pharmflow_dir()
        except Exception as e:
            _wiz_debug(f"PhoneFarmPage.on_enter _maybe_autofill_pharmflow_dir: {e!r}", None)
        # Docker / cloud phones — show the panel when the engine answers; never
        # auto-starts or stops containers, only surfaces + connects via ADB.
        try:
            import subprocess as _sp
            r = _sp.run(
                ["docker", "ps", "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=8,
                creationflags=_sp.CREATE_NO_WINDOW if IS_WIN else 0,
            )
            docker_up = r.returncode == 0
        except Exception:
            docker_up = False
        if docker_up:
            self._docker_panel.pack(fill="x", pady=(6, 0))
        elif self._docker_panel.winfo_manager():
            self._docker_panel.pack_forget()
        if not state.get("use_mumu"):
            try:
                sp = (state.get("sdk_path") or "").strip()
                bad = True
                if sp:
                    try:
                        bad = not Path(sp, "platform-tools").is_dir()
                    except OSError as e:
                        _wiz_debug(f"PhoneFarmPage.on_enter sdk_path stat {sp!r}: {e!r}", None)
                        bad = True
                if bad:
                    got = _resolve_sdk_root_auto()
                    if got:
                        state["sdk_path"] = got
            except Exception as e:
                _wiz_debug(f"PhoneFarmPage.on_enter sdk auto-resolve: {e!r}", None)
        if state.get("use_mumu"):
            self._mumu_panel.pack(fill="x", pady=(6, 0))
            self._log_write(
                "MuMuPlayer ARM64 mode — no AVD creation needed.\n"
                "Boot all phones in the Control Panel starts stopped MuMu instances. "
                "Enable USB debugging on each phone, then Check again.\n"
            )

            def _prep_adb():
                _ensure_minimal_platform_tools(log_fn=self._log_write)
                self._log_write(f"Using adb: {adb_executable()}\n")
                _warn_arm64_x64_adb(self._log_write)

            threading.Thread(target=_prep_adb, daemon=True).start()
            return
        else:
            if self._mumu_panel.winfo_manager():
                self._mumu_panel.pack_forget()

        self._pick_count(state.get("num_phones", 3))
        prefix = state.get("phone_prefix", "PharmFlow_Phone")
        existing = [a for a in list_avds() if a.startswith(prefix + "_")]
        if not existing:
            existing = [a for a in list_avds() if a.startswith("PharmFlow_Phone_")]
        if existing:
            state["avds"] = existing
            self._log_write(f"Found {len(existing)} existing phone(s): "
                            f"{', '.join(existing)}\n")
            self._log_write("Phones already created! Click Next → to continue.\n")
            self._progress_lbl.config(
                text=f"✅  {len(existing)} phone(s) ready", fg=GREEN)
            self._done = True

    def _log_write(self, text):
        def _do():
            self._log_box.insert("end", text)
            self._log_box.see("end")
        self.after(0, _do)

    def _delete_phones(self):
        all_avds = list_avds()
        prefix = state.get("phone_prefix", "PharmFlow_Phone")
        # Only wizard-created AVD names (prefix + legacy PharmFlow_Phone_*); never substring-match "pharmflow".
        seen: set[str] = set()
        to_delete: list[str] = []
        for a in all_avds:
            if (a.startswith(prefix + "_") or a.startswith("PharmFlow_Phone_")) and a not in seen:
                seen.add(a)
                to_delete.append(a)
        if not to_delete:
            self._log_write("No PharmFlow phones found to delete.\n")
            return
        if not messagebox.askyesno(
            "Delete phones?",
            f"Delete {len(to_delete)} AVD(s)?\n\n" + "\n".join(to_delete),
            parent=self.winfo_toplevel(),
        ):
            return
        self._progress_lbl.config(text="Deleting…", fg=STATUS_PROGRESS)
        def go():
            avdmgr = sdk_tool("avdmanager")
            flags = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
            deleted = []
            for avd in to_delete:
                self._log_write(f"  Deleting {avd}…\n")
                try:
                    subprocess.run(
                        [avdmgr, "delete", "avd", "-n", avd],
                        capture_output=True, timeout=30,
                        env=_sdk_env(), creationflags=flags,
                    )
                    deleted.append(avd)
                except (OSError, subprocess.SubprocessError) as e:
                    self._log_write(f"  ⚠ {avd}: {e}\n")
            msg = f"✅ Deleted {len(deleted)} phone(s)" if deleted else "❌ Nothing deleted"
            clr = GREEN if deleted else RED

            def _after_delete():
                state["avds"] = []
                self._done = False
                self._progress_lbl.config(text=msg, fg=clr)

            self.after(0, _after_delete)
            self._log_write(f"Deleted {len(deleted)} phone(s). Ready to create fresh.\n")
        threading.Thread(target=go, daemon=True).start()

    def _create(self):
        n = state.get("num_phones", 3)
        prefix = state.get("phone_prefix", "PharmFlow_Phone")
        self._create_btn.config(state="disabled", text=" Creating phones… ")
        self._log_write(f"Creating {n} virtual phone(s). This may take 10–30 minutes.\n\n")

        def go():
            created = []
            for i in range(1, n + 1):
                name = f"{prefix}_{i}"
                self.after(0, lambda t=f"Creating {i}/{n}: {name}…":
                           self._progress_lbl.config(text=t, fg=STATUS_PROGRESS))
                self._log_write(f"══ Phone {i} of {n}: {name} ══\n")
                try:
                    ok, err = create_avd(name, log_fn=self._log_write)
                except Exception as exc:
                    ok, err = False, str(exc)
                if ok:
                    created.append(name)
                else:
                    self._log_write(f"  ❌  Error: {err}\n")

            total = len(created)

            if created:
                self._log_write(f"\n✅  Done! {total} phone(s) created.\n")
                self._log_write("Click Next → to start the phones.\n")
            else:
                self._log_write("\n❌  No phones were created. Check errors above.\n")

            btn_txt = "Phones created" if created else "Try again"

            def _finish_create():
                state["avds"] = created
                self._done = bool(created)
                if created:
                    self._progress_lbl.config(text=f"✅  {total} phone(s) ready!", fg=GREEN)
                else:
                    self._progress_lbl.config(text="❌  Failed — check log", fg=RED)
                self._create_btn.config(state="normal", text=btn_txt)

            self.after(0, _finish_create)

        threading.Thread(target=go, daemon=True).start()

    def can_advance(self):
        if state.get("use_mumu"):
            return True
        avds = state.get("avds", [])
        if avds:
            return True
        prefix = state.get("phone_prefix", "PharmFlow_Phone")
        running = [a for a in list_avds()
                   if a.startswith(prefix + "_") or a.startswith("PharmFlow_Phone_")]
        if running:
            state["avds"] = running
            return True
        messagebox.showinfo(
            "Phones not created yet",
            "Click 'Create Phone Farm' and wait for it to finish.\n\n"
            "This downloads Android 14 and sets up virtual phones — only happens once.",
            parent=self.winfo_toplevel(),
        )
        return False


# ─── page 5: connect & boot (ADB) ─────────────────────────────────────────────


class BootPage(PageBase):
    def __init__(self, parent):
        super().__init__(parent)
        self._boot_row_images: list[tk.PhotoImage] = []
        # Avoid overlapping MuMu work — concurrent adb + CLI launch storms crash nemux/MuMu ARM.
        self._mumu_scan_lock = threading.Lock()
        self._mumu_boot_lock = threading.Lock()
        self.header(
            "Boot phones",
            "1. Tap Start all phones.\n2. Tap Open link to test getdabflow.app.\n"
            "(Emulator hide: you already ran Phone Setup — use Re-apply below only if needed.)",
        )

        # Start Phones
        phone_ctrl = tk.Frame(self, bg=BG3, padx=14, pady=12)
        phone_ctrl.pack(fill="x", pady=(0, 8))
        tk.Label(phone_ctrl, text="Turn phones on",
                 font=("Segoe UI", 11, "bold"),
                 bg=BG3, fg=ACCENT, anchor="w").pack(fill="x")
        tk.Label(phone_ctrl,
                 text="First boot can take a few minutes per phone. Wait until you see the Android home screen.",
                 font=FS, bg=BG3, fg=T2, anchor="w").pack(fill="x", pady=(2, 8))
        phone_row = tk.Frame(phone_ctrl, bg=BG3)
        phone_row.pack(fill="x", pady=(4, 8))
        self._boot_btn = tk.Button(phone_row, text="Start all phones",
                                  font=("Segoe UI", 10, "bold"),
                                  bg=GREEN, fg=ON_ACCENT, relief="flat",
                                  cursor="hand2", command=self._boot_all,
                                  bd=0, highlightthickness=0)
        self._boot_btn.configure(activebackground=GREEN_ACTIVE, activeforeground=ON_ACCENT)
        self._boot_btn.pack(side="left", padx=(0, 8))
        self._stop_btn = tk.Button(phone_row, text="Stop all",
                                  font=("Segoe UI", 10, "bold"),
                                  bg=RED, fg=ON_ACCENT, relief="flat",
                                  cursor="hand2", command=self._stop_all,
                                  state="disabled", bd=0, highlightthickness=0)
        style_danger_button(self._stop_btn)
        self._stop_btn.pack(side="left")
        self._overall_lbl = tk.Label(phone_row, text="",
                                     font=FS, bg=BG3, fg=T2)
        self._overall_lbl.pack(side="left", padx=10)

        self._mumu_cfg_row = tk.Frame(phone_ctrl, bg=BG3)
        tk.Label(
            self._mumu_cfg_row,
            text="MuMu helper tool (auto-filled when possible):",
            font=FS,
            bg=BG3,
            fg=T2,
        ).pack(side="left")
        self._mumu_path_var = tk.StringVar(value="")
        self._mumu_path_entry = tk.Entry(
            self._mumu_cfg_row, textvariable=self._mumu_path_var,
            font=FM, bg=BG2, fg=T1, insertbackground=T1,
            relief="flat", width=40,
        )
        self._mumu_path_entry.pack(side="left", padx=6)
        tk.Button(self._mumu_cfg_row, text="Pick a different file…",
                  font=FS, bg=BG3, fg=T1, relief="flat", cursor="hand2",
                  command=self._browse_mumu_mgr).pack(side="left")
        self._mumu_hint = tk.Label(phone_ctrl,
                 text="Usually: …\\MuMuPlayerARM\\shell\\nemux-shell-winui.Manager.exe",
                 font=("Segoe UI", 9), bg=BG3, fg=T3, anchor="w")

        # Browser setup + URL test (optional Chrome first-run; sequences use default browser)
        chrome_box = tk.Frame(
            self,
            bg=BG2,
            padx=SP["md"],
            pady=SP["md"],
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        chrome_box.pack(fill="x", pady=(0, 8))
        ch_head = tk.Frame(chrome_box, bg=BG2)
        ch_head.pack(fill="x")
        tk.Frame(ch_head, bg=CALLOUT_STRIP, width=3).pack(side="left", fill="y", padx=(0, SP["sm"]))
        ch_titles = tk.Frame(ch_head, bg=BG2)
        ch_titles.pack(side="left", fill="x", expand=True)
        tk.Label(
            ch_titles,
            text="Browser on each phone",
            font=FONT_SECTION,
            bg=BG2,
            fg=T1,
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            ch_titles,
            text=(
                "1. Chromium is installed from Phone Setup → GO or Install Chromium.\n"
                "2. MuMu Browser also works and is best with Tor.\n"
                "3. Test getdabflow.app with the button below."
            ),
            font=FS,
            bg=BG2,
            fg=T2,
            anchor="w",
            wraplength=840,
            justify="left",
        ).pack(fill="x", pady=(4, 0))
        chrome_ctrl = tk.Frame(chrome_box, bg=BG2)
        chrome_ctrl.pack(fill="x", pady=(SP["sm"], 0))
        self._chrome_lbl = tk.Label(
            chrome_ctrl,
            text="Use Phone Setup → Install Chromium (Home → Step 1), not this screen.",
            font=FS,
            bg=BG2,
            fg=T3,
            wraplength=840,
            justify="left",
        )
        self._chrome_lbl.pack(fill="x")
        self._chrome_btn = None
        # Test URL row — same ADB VIEW path as sequences / dashboard ``open_url``.
        test_row = tk.Frame(chrome_box, bg=BG2)
        test_row.pack(fill="x", pady=(8, 0))
        tk.Label(
            test_row,
            text="Test link (first phone that is on):",
            font=FS,
            bg=BG2,
            fg=T2,
        ).pack(side="left")
        self._test_url_var = tk.StringVar(value="https://getdabflow.app")
        tk.Entry(test_row, textvariable=self._test_url_var, font=FM,
                 bg=BG2, fg=T1, insertbackground=T1, relief="flat",
                 width=34).pack(side="left", padx=6)
        ob = tk.Button(
            test_row,
            text="Open link on phone",
            font=("Segoe UI", 10, "bold"),
            command=self._test_url,
        )
        style_primary_button(ob)
        ob.pack(side="left")
        chrome_hint = tk.Label(
            chrome_box,
            text=(
                "A happy pop-up means the link opened. A blank page often means wait a minute — "
                "the internet helper is still starting. No pop-up? Turn on USB debugging on the phone "
                "and pick a browser app."
            ),
            font=FONT_CAPTION,
            bg=BG2,
            fg=T3,
            anchor="w",
            justify="left",
        )
        chrome_hint.pack(fill="x", pady=(SP["xs"], 0))
        bind_responsive_wraplength(chrome_hint, chrome_box, pad=28)

        # Fingerprint — hide emulator from websites (getdabflow.app)
        fp_box = tk.Frame(
            self,
            bg=BG2,
            padx=SP["md"],
            pady=SP["md"],
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        fp_box.pack(fill="x", pady=(0, 8))
        fp_head = tk.Frame(fp_box, bg=BG2)
        fp_head.pack(fill="x")
        tk.Frame(fp_head, bg=GREEN, width=3).pack(side="left", fill="y", padx=(0, SP["sm"]))
        fp_titles = tk.Frame(fp_head, bg=BG2)
        fp_titles.pack(side="left", fill="x", expand=True)
        tk.Label(
            fp_titles,
            text="Re-apply hide emulator + DabFlow ad fix (optional)",
            font=FONT_SECTION,
            bg=BG2,
            fg=T1,
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            fp_titles,
            text=(
                "Already ran Phone Setup? Skip unless MuMu phones were cold-booted, "
                "getdabflow blocks you, or Mantis ads never appear. Re-applies retail phone "
                "disguise + browser flags (includes ad-zone CDP patch port) on ALL phones."
            ),
            font=FS,
            bg=BG2,
            fg=T2,
            anchor="w",
            wraplength=840,
            justify="left",
        ).pack(fill="x", pady=(4, 0))
        fp_ctrl = tk.Frame(fp_box, bg=BG2)
        fp_ctrl.pack(fill="x", pady=(SP["sm"], 0))
        self._fp_btn = tk.Button(
            fp_ctrl,
            text="Re-apply hide emulator on ALL phones",
            font=("Segoe UI", 10, "bold"),
            bg=GREEN,
            fg=ON_ACCENT,
            relief="flat",
            cursor="hand2",
            command=self._hide_emulator_all,
            bd=0,
            highlightthickness=0,
        )
        self._fp_btn.configure(activebackground=GREEN_ACTIVE, activeforeground=ON_ACCENT)
        self._fp_btn.pack(side="left", padx=(0, 10))
        self._fp_lbl = tk.Label(fp_ctrl, text="", font=FS, bg=BG2, fg=T2)
        self._fp_lbl.pack(side="left")
        tk.Label(
            fp_box,
            text=(
                "If it says you still have leaks: fully STOP then START each MuMu phone once, "
                "then tap this button again."
            ),
            font=FONT_CAPTION,
            bg=BG2,
            fg=T3,
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(SP["xs"], 0))

        adb_card = instruction_card(self, pad=SP["md"])
        adb_card.pack(fill="x", pady=(0, SP["sm"]))
        tk.Label(
            adb_card,
            text="Tips",
            font=FONT_SECTION,
            bg=BG2,
            fg=T1,
            anchor="w",
        ).pack(fill="x", pady=(0, SP["xs"]))
        adb_tips = tk.Label(
            adb_card,
            text=(
                "• Turn on USB debugging on each phone (Settings → Developer options).\n"
                "• MuMu asks for Google? Skip it — you don't need it.\n"
                "• Page won't load? Go to the Go step and tap Fix the phone's internet.\n"
                "• Hiding emulator look is different from Tor — do BOTH."
            ),
            font=FS,
            bg=BG2,
            fg=T2,
            anchor="w",
            justify="left",
        )
        adb_tips.pack(fill="x")
        bind_responsive_wraplength(adb_tips, adb_card, pad=28)

        act = tk.Frame(self, bg=BG)
        act.pack(fill="x", pady=(SP["sm"], 0))
        tk.Label(
            act,
            text="Activity",
            font=FONT_CAPTION,
            bg=BG,
            fg=T3,
            anchor="w",
        ).pack(fill="x", pady=(0, 2))
        self._boot_activity_lbl = tk.Label(
            act,
            text="—",
            font=FS,
            bg=BG2,
            fg=T2,
            anchor="w",
            justify="left",
            padx=SP["md"],
            pady=SP["sm"],
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        self._boot_activity_lbl.pack(fill="x")
        bind_responsive_wraplength(self._boot_activity_lbl, act, pad=28)

        summary_outer = tk.Frame(
            self, bg=BG2, padx=SP["md"], pady=SP["sm"],
            highlightthickness=1, highlightbackground=BORDER,
        )
        summary_outer.pack(fill="x", pady=(SP["sm"], SP["sm"]))
        tk.Label(
            summary_outer,
            text="Connected phones",
            font=FONT_SECTION,
            bg=BG2,
            fg=T1,
            anchor="w",
        ).pack(fill="x")
        sum_row = tk.Frame(summary_outer, bg=BG2)
        sum_row.pack(fill="x")
        self._summary = tk.Text(
            sum_row, height=4, font=FM, bg=BG2, fg=T1,
            relief="flat", wrap="word",
        )
        _attach_readonly_log_text(self._summary)
        sum_sb = themed_vertical_scrollbar(sum_row, command=self._summary.yview)
        self._summary.configure(yscrollcommand=sum_sb.set)
        self._summary.pack(side="left", fill="both", expand=True)
        sum_sb.pack(side="right", fill="y")

        # Status grid — one row per target phone before boot
        self._status_frame = tk.Frame(self, bg=BG)
        self._status_frame.pack(fill="x", pady=(0, SP["xs"]))
        self._status_rows = {}

    def _refresh_phone_summary(self):
        lines = []
        for p in state.get("phones") or []:
            nm = p.get("name", "?")
            ser = p.get("serial", "")
            lines.append(f"  {nm}: {ser}")
        try:
            self._summary.delete("1.0", "end")
            self._summary.insert(
                "end",
                "\n".join(lines) if lines else "  (none yet — start phones above)",
            )
        except tk.TclError:
            pass

    def _prune_phones_against_adb(self) -> None:
        """Drop phones no longer in ``adb devices``; if cache was wrong but ADB has devices, adopt ADB list."""
        try:
            cur = list_adb_devices()
        except Exception:
            return
        by_s = {d["serial"]: d for d in cur}
        pl = state.get("phones") or []
        if not pl:
            return
        kept: list = []
        for p in pl:
            if not isinstance(p, dict):
                continue
            s = p.get("serial")
            if s and s in by_s:
                q = by_s[s]
                kept.append({"serial": s, "name": p.get("name") or q.get("name", s)})
        if not kept and cur:
            state["phones"] = list(cur)
        else:
            state["phones"] = kept

    def on_enter(self):
        try:
            from site_prefs import apply_site_url_to_boot_page

            apply_site_url_to_boot_page(self)
        except Exception:
            pass
        try:
            _maybe_autofill_pharmflow_dir()
        except Exception:
            pass
        if not state.get("use_mumu"):
            try:
                sp = (state.get("sdk_path") or "").strip()
                bad = True
                if sp:
                    try:
                        bad = not Path(sp, "platform-tools").is_dir()
                    except Exception:
                        bad = True
                if bad:
                    got = _resolve_sdk_root_auto()
                    if got:
                        state["sdk_path"] = got
            except Exception:
                pass
        self._rebuild_grid()
        self._refresh_phone_summary()

        if state.get("use_mumu"):
            v = self._mumu_path_var.get().strip()
            needs_fill = True
            if v:
                try:
                    pv = Path(v)
                    needs_fill = not (
                        pv.is_file()
                        and _is_mumu_manager_cli_path(pv)
                    )
                except Exception:
                    needs_fill = True
            if needs_fill:
                detected = _find_mumu_manager()
                if detected:
                    ds = str(detected)
                    self._mumu_path_var.set(ds)
                    state["mumu_mgr_path"] = ds
            elif v:
                state["mumu_mgr_path"] = v
            self._mumu_cfg_row.pack(fill="x", pady=(0, 2))
            self._mumu_hint.pack(fill="x", pady=(0, 4))
        else:
            self._mumu_cfg_row.pack_forget()
            self._mumu_hint.pack_forget()

        if state.get("use_mumu"):
            self._prune_phones_against_adb()
            if state.get("phones"):
                n = len(state["phones"])
                self._overall_lbl.config(
                    text=f"✅  {n} phone(s) in session — use Start all phones to rescan",
                    fg=GREEN,
                )
                return
            self._overall_lbl.config(text="Connecting to MuMu instances…", fg=STATUS_PROGRESS)

            def _mumu_scan():
                # Acquire in this worker thread only (same thread as release) — avoids Tk/win32 instability.
                if not self._mumu_scan_lock.acquire(blocking=False):
                    self.after(
                        0,
                        lambda: self._log_write(
                            "(Skipping auto-connect: another MuMu scan or boot is already running — "
                            "wait a few seconds or use Start all phones once.)\n"
                        ),
                    )
                    return
                try:
                    connected = _connect_mumu_phones(log_fn=self._log_write)
                    if connected:
                        mgr = _find_mumu_manager()
                        instances = _mumu_get_instances_cached(mgr) if mgr else []
                        name_map = {inst["adb_serial"]: inst["name"] for inst in instances}
                        phones = [{"serial": s, "name": name_map.get(s, f"MuMu-{i}")}
                                  for i, s in enumerate(connected)]
                        state["phones"] = phones
                        # No auto Chrome configuration: operator prefers device default browser
                        # (OEM / Samsung Internet / Fennec / Mull) so traffic flows through
                        # Android's global http_proxy → Tor reliably. Chrome bypasses the
                        # system proxy in many builds and causes ERR_TIMED_OUT. Operators who
                        # still want it run the explicit "Optional: Configure Chrome" button.
                        self.after(0, lambda: (
                            self._overall_lbl.config(
                                text=f"✅  {len(phones)} MuMu phone(s) connected!", fg=GREEN),
                            self._rebuild_grid(),
                        ))
                        for s in connected:
                            row_lbl = self._status_rows.get(s)
                            if row_lbl:
                                self.after(0, lambda lbl=row_lbl: lbl.config(text="✅  Running", fg=GREEN))
                    else:
                        self.after(0, lambda: self._overall_lbl.config(
                            text="No MuMu phones found — start instances, enable ADB in each instance’s settings, retry",
                            fg=STATUS_PROGRESS))
                except Exception as exc:
                    self.after(
                        0,
                        lambda e=str(exc): self._log_write(
                            f"\n❌  MuMu auto-connect crashed: {e}\n"
                            "   If this repeats, open MuMu manually first, then use « Start all phones ».\n"
                        ),
                    )
                    self.after(
                        0,
                        lambda: self._overall_lbl.config(
                            text="MuMu connect error — see Activity",
                            fg=RED,
                        ),
                    )
                finally:
                    self._mumu_scan_lock.release()

            threading.Thread(target=_mumu_scan, daemon=True).start()
            return

        devs = list_adb_devices()

        # Include physical USB phones and already-running emulators
        already = []
        for d in devs:
            s = d["serial"]
            if s.startswith("emulator-") or ":" in s:
                already.append(d)
            else:
                already.append(d)
        if already:
            state["phones"] = already
            n = len(already)
            self._overall_lbl.config(
                text=f"✅  {n} phone(s) already connected!",
                fg=GREEN)
            avds = state.get("avds", [])
            for d in already:
                serial = d["serial"]
                avd_name = None
                if serial.startswith("emulator-"):
                    try:
                        port = int(serial.split("-")[1])
                        idx  = (port - 5554) // 2
                        avd_name = avds[idx] if idx < len(avds) else None
                    except (IndexError, ValueError):
                        pass
                row_lbl = self._status_rows.get(avd_name or serial)
                if row_lbl:
                    row_lbl.config(text="✅  Running", fg=GREEN)

    def _rebuild_grid(self):
        for w in self._status_frame.winfo_children():
            w.destroy()
        self._status_rows.clear()
        self._boot_row_images.clear()
        top = self.winfo_toplevel()

        if state.get("use_mumu"):
            mgr = _find_mumu_manager()
            if mgr:
                instances = _mumu_get_instances_cached(mgr)
                for inst in instances:
                    key = inst["adb_serial"]
                    row = tk.Frame(self._status_frame, bg=BG2, padx=12, pady=7,
                                   highlightthickness=1, highlightbackground=BORDER)
                    row.pack(fill="x", pady=2)
                    im = load_icon("row_mumu", top)
                    if im:
                        self._boot_row_images.append(im)
                        tk.Label(row, image=im, bg=BG2).pack(side="left", padx=(0, 6))
                    else:
                        tk.Label(row, text="MuMu", font=FONT_CAPTION, bg=BG2, fg=T3
                                 ).pack(side="left", padx=(0, 6))
                    tk.Label(row, text=inst["name"], font=FB, bg=BG2, fg=T1,
                             width=26, anchor="w").pack(side="left")
                    tk.Label(row, text=f"Link: {key}", font=FM, bg=BG2,
                             fg=T3, width=22, anchor="w").pack(side="left")
                    lbl = tk.Label(row, text="Not started", font=FS, bg=BG2, fg=T3)
                    lbl.pack(side="left", padx=6)
                    self._status_rows[key] = lbl
            return

        # AVD emulator rows
        for i, avd in enumerate(state.get("avds", [])):
            port   = 5554 + i * 2
            serial = f"emulator-{port}"
            row    = tk.Frame(self._status_frame, bg=BG2, padx=12, pady=7,
                              highlightthickness=1, highlightbackground=BORDER)
            row.pack(fill="x", pady=2)
            im = load_icon("row_avd", top)
            if im:
                self._boot_row_images.append(im)
                tk.Label(row, image=im, bg=BG2).pack(side="left", padx=(0, 6))
            else:
                tk.Label(row, text="AVD", font=FONT_CAPTION, bg=BG2, fg=T3
                         ).pack(side="left", padx=(0, 6))
            tk.Label(row, text=avd, font=FB, bg=BG2, fg=T1,
                     width=26, anchor="w").pack(side="left")
            tk.Label(row, text=f"Link: {serial}", font=FM, bg=BG2,
                     fg=T3, width=20, anchor="w").pack(side="left")
            lbl = tk.Label(row, text="Not started", font=FS,
                           bg=BG2, fg=T3)
            lbl.pack(side="left", padx=6)
            self._status_rows[avd] = lbl

        # Physical USB phones
        for d in list_adb_devices():
            s = d["serial"]
            if s.startswith("emulator-") or ":" in s:
                continue
            row = tk.Frame(self._status_frame, bg=BG2, padx=12, pady=7,
                           highlightthickness=1, highlightbackground=BORDER)
            row.pack(fill="x", pady=2)
            im = load_icon("row_usb", top)
            if im:
                self._boot_row_images.append(im)
                tk.Label(row, image=im, bg=BG2).pack(side="left", padx=(0, 6))
            else:
                tk.Label(row, text="USB", font=FONT_CAPTION, bg=BG2, fg=T3
                         ).pack(side="left", padx=(0, 6))
            tk.Label(row, text=d["name"], font=FB, bg=BG2, fg=T1,
                     width=26, anchor="w").pack(side="left")
            tk.Label(row, text=f"USB ID: {s}", font=FM, bg=BG2,
                     fg=T3, width=20, anchor="w").pack(side="left")
            lbl = tk.Label(row, text="Connected", font=FS, bg=BG2, fg=GREEN)
            lbl.pack(side="left", padx=6)
            self._status_rows[s] = lbl

    def _browse_mumu_mgr(self):
        tmp = tk.StringVar(value=self._mumu_path_var.get())
        _mumu_ft = [
            ("MuMu CLI", "*.exe"),
            ("nemux-shell-winui.Manager", "nemux-shell-winui.Manager.exe"),
            ("MuMuManager (legacy)", "MuMuManager.exe"),
            ("All executables", "*.exe"),
            ("All files", "*.*"),
        ]
        path = _browse_file(
            self.winfo_toplevel(),
            tmp,
            _mumu_ft,
            _mumu_browse_initialdir,
            title="Select MuMu shell CLI — shell\\ or nx_main\\ under MuMuPlayerARM",
        )
        if not path:
            return
        name = Path(path).name
        if _is_mumu_gui_path(path):
            messagebox.showwarning(
                "Wrong file",
                f"'{name}' is the MuMu Player app, not the helper tool.\n"
                "  Pick nemux-shell-winui.Manager.exe in the shell folder.",
                parent=self.winfo_toplevel(),
            )
            return
        if not _is_mumu_manager_cli_path(path):
            messagebox.showwarning(
                "Wrong file",
                f"'{name}' is not the MuMu helper tool.\n"
                "  Pick nemux-shell-winui.Manager.exe or MuMuManager.exe in shell\\.",
                parent=self.winfo_toplevel(),
            )
            return
        state["mumu_mgr_path"] = path
        self._mumu_path_var.set(path)
        self._log_write(f"MuMu CLI set ({name}): {path}\n")

    def _log_write(self, text):
        """Route verbose install/boot output to a single-line status (scroll log removed)."""

        def _do():
            raw = (text or "").rstrip()
            if not raw:
                return
            last_line = raw.split("\n")[-1].strip() or raw.replace("\n", " ").strip()
            show = last_line if len(last_line) <= 160 else "…" + last_line[-157:]
            low = last_line.lower()
            if "❌" in last_line or "failed" in low or "error" in low:
                fg = RED
            elif "✅" in last_line or "ready" in low and "not " not in low[:20]:
                fg = GREEN
            elif "⚠" in last_line:
                fg = WARN_FG
            else:
                fg = T2
            self._boot_activity_lbl.config(text=show, fg=fg)
            self._refresh_phone_summary()

        self.after(0, _do)

    def _boot_all(self):
        # ── MuMuPlayer mode ───────────────────────────────────────────────────
        if state.get("use_mumu"):
            self._boot_btn.config(state="disabled", text="Connecting…")
            self._log_write("MuMuPlayer mode — launching and connecting instances…\n")
            def go_mumu():
                _wiz_debug("go_mumu thread started", self._log_write)
                if not self._mumu_boot_lock.acquire(blocking=False):
                    _wiz_debug("go_mumu boot_lock busy — exiting early", self._log_write)
                    self._log_write("Already running a MuMu boot/connect — please wait.\n")
                    self.after(0, lambda: self._boot_btn.config(state="normal", text="Start all phones"))
                    return
                try:
                    global _mumu_inst_cache_val
                    _wiz_debug("go_mumu acquired boot_lock", self._log_write)
                    _mumu_inst_cache_val = None
                    _wiz_debug("cleared _mumu_inst_cache_val", self._log_write)
                    mgr = _find_mumu_manager()
                    _wiz_debug(f"go_mumu find mgr → {_wiz_dbg_path(mgr)}", self._log_write)
                    if not mgr:
                        _wiz_debug("go_mumu abort: no mgr CLI", self._log_write)
                        self._log_write(
                            "❌ MuMu helper tool not found "
                            "(nemux-shell-winui.Manager.exe or MuMuManager.exe).\n"
                            f"   Install MuMuPlayer from: {MUMU_DOWNLOAD_URL}\n"
                        )
                        self.after(0, lambda: (
                            self._boot_btn.config(state="normal", text="Start all phones"),
                            self._overall_lbl.config(text="❌ MuMuPlayer not installed", fg=RED),
                        ))
                        return

                    instances = _mumu_get_instances(mgr, log_fn=self._log_write)
                    _wiz_debug(f"go_mumu instances n={len(instances)}", self._log_write)
                    if not instances:
                        _wiz_debug("go_mumu no instances — port_scan path via _connect_mumu_phones", self._log_write)
                        self._log_write(
                            "  Could not list MuMu phones — scanning for connections…\n"
                            "  If nothing appears, turn on ADB in each phone's Settings.\n"
                        )
                        connected = _connect_mumu_phones(
                            log_fn=self._log_write, force_full_scan=True
                        )
                        _wiz_debug(f"go_mumu port_scan path connected n={len(connected)}", self._log_write)
                        if connected:
                            phones_from_scan = [{"serial": s, "name": f"MuMu-{i}"} for i, s in enumerate(connected)]
                            state["phones"] = phones_from_scan
                            state["_emu_procs"] = []
                            n = len(phones_from_scan)
                            self.after(0, lambda: (
                                self._boot_btn.config(state="normal", text="Start all phones"),
                                self._stop_btn.config(state="normal"),
                                self._overall_lbl.config(text=f"✅ {n} MuMu phone(s) ready", fg=GREEN),
                            ))
                            self._log_write(f"\n{n} phone(s) connected.\n")
                            _wiz_debug("go_mumu port_scan success exit", self._log_write)
                            return
                        self._log_write(
                            "❌ No MuMu phones found.\n"
                            "   Open MuMuPlayer and start at least one phone.\n"
                            f"   {MUMU_ADB_PER_INSTANCE_HINT}\n"
                            "   Open MuMuPlayer → multi-window icon → '+ New Instance'\n"
                        )
                        self.after(0, lambda: (
                            self._boot_btn.config(state="normal", text="Start all phones"),
                            self._overall_lbl.config(text="❌ No MuMu instances", fg=RED),
                        ))
                        _wiz_debug("go_mumu port_scan path found nothing", self._log_write)
                        return

                    phones = []
                    for inst in instances:
                        idx  = inst["index"]
                        name = inst["name"]
                        serial = inst["adb_serial"]
                        already_up = bool(inst.get("started"))
                        _wiz_debug(
                            f"go_mumu instance idx={idx} name={name!r} serial={serial} "
                            f"already_up={already_up}",
                            self._log_write,
                        )
                        if already_up:
                            self._log_write(
                                f"  {name} (instance {idx}) already running — "
                                "skipping duplicate MuMu CLI launch\n"
                            )
                        else:
                            self._log_write(f"  Launching {name} (instance {idx})…\n")
                            _wiz_debug(f"go_mumu launch idx={idx}", self._log_write)
                            _mumu_launch(mgr, idx, log_fn=None)
                            time.sleep(2)

                        # Wait up to 3 min for Android to boot.
                        # Ground truth is ADB: connect + echo until the phone answers.
                        # Never trust MuMu's ``started`` flag alone — on ARM guest-bridge
                        # serials it can be true while ADB is not ready yet.
                        wait_secs = 60 if already_up else 180
                        deadline = time.time() + wait_secs
                        booted   = False
                        loop_i = 0
                        while not booted and time.time() < deadline:
                            if loop_i > 0 or not already_up:
                                time.sleep(5 if not already_up else 2)
                            loop_i += 1
                            adb("connect", serial, timeout=8)
                            check = adb("shell", "echo", "ok", serial=serial, timeout=8)
                            booted = check.strip() == "ok"
                            if loop_i == 1 or loop_i % 6 == 0:
                                _wiz_debug(
                                    f"go_mumu boot_wait idx={idx} iter={loop_i} serial={serial} "
                                    f"booted={booted}",
                                    self._log_write,
                                )

                        if not booted:
                            _wiz_debug(
                                f"go_mumu boot_wait TIMEOUT idx={idx} after ~180s — adb anyway",
                                self._log_write,
                            )
                            self._log_write(f"  ⚠ {name} slow — trying ADB connect anyway…\n")

                        _wiz_debug(f"go_mumu adb connect serial={serial}", self._log_write)
                        conn_out = adb("connect", serial, timeout=10)
                        _wiz_debug(
                            f"go_mumu adb connect out len={len(conn_out or '')}",
                            self._log_write,
                        )
                        check = adb("shell", "echo", "ok", serial=serial, timeout=8)
                        shell_ok = check.strip() == "ok"
                        _wiz_debug(f"go_mumu adb shell_ok serial={serial} ok={shell_ok}", self._log_write)
                        if shell_ok:
                            new_id = rotate_android_id(serial)
                            phones.append({"serial": serial, "name": name})
                            self._log_write(f"  ✅ {name}: {serial}  ID:{new_id[:8]}…\n")
                            row_lbl = self._status_rows.get(serial)
                            if row_lbl:
                                self.after(0, lambda lb=row_lbl: lb.config(text="✅ Running", fg=GREEN))
                        else:
                            _wiz_debug(f"go_mumu adb FAIL serial={serial}", self._log_write)
                            self._log_write(f"  ❌ {name}: ADB not responding on {serial}\n")

                    state["phones"]      = phones
                    state["_emu_procs"]  = []
                    n = len(phones)
                    self.after(0, lambda: (
                        self._boot_btn.config(state="normal", text="Start all phones"),
                        self._stop_btn.config(state="disabled" if not phones else "normal"),
                        self._overall_lbl.config(
                            text=f"✅ {n} MuMuPlayer phone(s) ready" if phones else "❌ No phones connected",
                            fg=GREEN if phones else RED),
                    ))
                    if phones:
                        self._log_write(f"\n{n} MuMuPlayer phone(s) ready.\n")
                    else:
                        self._log_write("\nNo phones connected. Nothing is ready.\n")
                    _wiz_debug(f"go_mumu normal exit phones={n}", self._log_write)
                except Exception as exc:
                    tb = traceback.format_exc()
                    _wiz_debug(
                        f"go_mumu EXCEPTION type={type(exc).__name__} msg={exc!r}",
                        self._log_write,
                    )
                    _wiz_debug(f"go_mumu TRACEBACK\n{tb}", self._log_write)
                    self._log_write(f"\n❌  MuMu boot thread failed: {exc}\n")
                    self.after(0, lambda: (
                        self._boot_btn.config(state="normal", text="Start all phones"),
                        self._overall_lbl.config(text="MuMu error — see Activity", fg=RED),
                    ))
                finally:
                    self._mumu_boot_lock.release()
                    _wiz_debug("go_mumu released boot_lock", self._log_write)
            threading.Thread(target=go_mumu, daemon=True).start()
            return

        # ── AVD emulator mode ───────────────────────────────────────────────────
        avds = state.get("avds", [])

        # Also include any physical USB phones already attached
        usb_phones = [d for d in list_adb_devices()
                      if not d["serial"].startswith("emulator-") and ":" not in d["serial"]]
        if usb_phones and not avds:
            state["phones"] = usb_phones
            n = len(usb_phones)
            self._overall_lbl.config(text=f"✅ {n} USB phone(s) connected", fg=GREEN)
            self._log_write(f"✅ {n} physical USB phone(s) already connected.\n")
            return

        if not avds:
            messagebox.showerror(
                "No phones",
                "Go back to Create phones and finish there first.\n\n"
                "Or connect a physical Android phone via USB — "
                "the wizard will detect it automatically.",
                parent=self.winfo_toplevel(),
            )
            return

        # A non-ARM64 emulator.exe is not a reason to refuse the start.
        # Refusing here left Studio AVDs unlaunched on this host. Start, then
        # report a dead process. Hide the console only — start_emulator does that.
        if IS_WIN and "arm64" in _machine_arch():
            sdk = state.get("sdk_path") or find_sdk()
            emu_exe = Path(sdk) / "emulator" / "emulator.exe" if sdk else Path()
            if not emu_exe.is_file():
                self._log_write(
                    "Studio AVDs are listed but emulator.exe was not found — not launched.\n"
                )
                messagebox.showerror(
                    "Emulator not found",
                    "Android Studio AVDs are listed, but emulator.exe was not found.\n\n"
                    "Install Android tools, then start the phones again.",
                    parent=self.winfo_toplevel(),
                )
                self._boot_btn.config(state="normal", text="Start all phones")
                return
            if _pe_machine_type(str(emu_exe)) != 0xAA64:
                self._log_write(
                    "emulator.exe is not an ARM64 binary. Starting anyway. "
                    "If the phone window dies immediately, install the ARM64 emulator.\n"
                )

        self._boot_btn.config(state="disabled", text="Starting…")
        self._stop_btn.config(state="normal")
        self._log_write(f"Starting {len(avds)} phone(s)...\n")

        def go():
            procs = []          # (avd_name, serial, proc, log_path)
            phones = []
            for i, avd in enumerate(avds):
                port = 5554 + i * 2
                serial = f"emulator-{port}"
                self.after(0, lambda a=avd: (
                    self._overall_lbl.config(text=f"Launching {a}...", fg=STATUS_PROGRESS)
                ))
                try:
                    proc, log_path = start_emulator(avd, port)
                except Exception as e:
                    self._log_write(f"  ❌ {avd} start failed: {e}\n")
                    continue

                # Detect instant crash (proc exits before we even wait for boot)
                time.sleep(1.5)
                crash = proc.poll()
                if crash is not None:
                    # Emulator exited immediately — read its output for the error
                    err_lines = []
                    if log_path and Path(log_path).exists():
                        try:
                            err_lines = Path(log_path).read_text(errors="ignore").splitlines()[-12:]
                        except Exception:
                            pass
                    err_msg = "\n".join(err_lines) if err_lines else f"(exit code {crash})"
                    self._log_write(
                        f"  ❌ {avd} CRASHED immediately (exit {crash}):\n"
                        f"     {err_msg[:300]}\n"
                        f"     Log: {log_path or 'N/A'}"
                    )
                    self.after(0, lambda a=avd: (
                        self._overall_lbl.config(text=f"❌ {a} crashed", fg=RED)
                    ))
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    continue

                procs.append((avd, serial, proc, log_path))
                self._log_write(
                    f"  Waiting for {avd} to boot...\n"
                    f"  (SwiftShader GPU — expect 10-20 min on first boot)\n")
                if log_path and Path(log_path).exists():
                    self._log_write(f"  Emulator log: {log_path}\n")
                ok = wait_for_boot(serial, timeout=1200, log_fn=self._log_write)
                if not ok:
                    self._log_write(f"  ⚠ {avd} slow — waiting extra 10 min...\n")
                    ok = wait_for_boot(serial, timeout=600, log_fn=self._log_write)
                if ok:
                    new_id = rotate_android_id(serial)
                    phones.append({"serial": serial, "name": avd})
                    self._log_write(
                        f"  ✅ {avd} ready! Android ID: {new_id[:8]}...\n")
                    self.after(0, lambda a=avd: (
                        self._overall_lbl.config(text=f"✅ {a} running", fg=GREEN)
                    ))
                else:
                    # Boot timeout — dump emulator log for diagnosis
                    err_lines = []
                    if log_path and Path(log_path).exists():
                        try:
                            err_lines = Path(log_path).read_text(errors="ignore").splitlines()[-20:]
                        except Exception:
                            pass
                    err_msg = "\n".join(err_lines) if err_lines else "(no log)"
                    self._log_write(
                        f"  ❌ {avd} BOOT TIMED OUT.\n"
                        f"     Enable Windows Hypervisor Platform:\n"
                        f"       Settings → Turn Windows features on/off → Windows Hypervisor Platform ✅\n"
                        f"     Emulator log:\n"
                        f"     {err_msg[:400]}")
                    self.after(0, lambda a=avd: (
                        self._overall_lbl.config(text=f"❌ {a} timed out", fg=RED)
                    ))

            state["phones"] = phones
            state["_emu_procs"] = [p for _, _, p, _ in procs]
            n = len(phones)
            self.after(0, lambda: (
                self._boot_btn.config(state="normal", text="Start all phones"),
                self._stop_btn.config(
                    state="disabled" if not phones else "normal"),
                self._overall_lbl.config(
                    text=f"✅ {n}/{len(avds)} phone(s) running" if phones
                        else "❌ No phones booted",
                    fg=GREEN if phones else RED),
            ))
            self._log_write(f"\n{n}/{len(avds)} phone(s) running.\n")

        threading.Thread(target=go, daemon=True).start()

    def _stop_all(self):
        for proc in state.get("_emu_procs", []):
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                lf = getattr(proc, "_log_file", None)
                if lf:
                    lf.close()
            except Exception:
                pass
        state["_emu_procs"] = []
        state["phones"] = []
        self._boot_btn.config(state="normal", text="Start all phones")
        self._stop_btn.config(state="disabled")
        self._overall_lbl.config(text="All phones stopped.", fg=T2)
        self._log_write("All phones stopped.\n")

    def _hide_emulator_all(self):
        phones = state.get("phones", [])
        if not phones:
            messagebox.showwarning(
                "No phones",
                "Tap Start all phones first.",
                parent=self.winfo_toplevel(),
            )
            return
        self._fp_btn.config(state="disabled", text="Working…")
        self._fp_lbl.config(text="", fg=T2)
        serials = [p["serial"] for p in phones]

        def go():
            try:
                _automation_on_sys_path()
                import mumu_farm_ops as farm

                self._log_write("\nHiding emulator look on ALL phones…\n")
                summary = farm.apply_fingerprint_all(
                    serials,
                    log=lambda msg: self._log_write(msg + "\n"),
                    patch_vms=True,
                )
                n_leak = summary.get("leaks_total", 0)
                if summary.get("any_vm_patched"):
                    self._log_write(
                        "Stop each MuMu phone fully, then start it again (one time).\n"
                    )
                if n_leak == 0:
                    msg = f"Done — {len(serials)} phone(s) look clean."
                    fg = GREEN
                else:
                    msg = f"Done — {n_leak} leak(s) left. Cold-boot phones and run again."
                    fg = RED
            except Exception as e:
                msg = f"Error: {e}"
                fg = RED
                self._log_write(f"  ❌ {e}\n")

            def done_ui():
                self._fp_btn.config(state="normal", text="Re-apply hide emulator on ALL phones")
                self._fp_lbl.config(text=msg, fg=fg)

            self.after(0, done_ui)

        threading.Thread(target=go, daemon=True).start()

    def _setup_chrome_all(self):
        if not getattr(self, "_chrome_btn", None):
            messagebox.showinfo(
                "Install Chromium",
                "Use Phone Setup (Home → Step 1) → Install Chromium on all phones.",
                parent=self.winfo_toplevel(),
            )
            return
        phones = state.get("phones", [])
        if not phones:
            messagebox.showwarning(
                "No phones",
                "Boot phones first.",
                parent=self.winfo_toplevel(),
            )
            return
        self._chrome_btn.config(state="disabled", text="Working…")
        self._chrome_lbl.config(text="", fg=T2)
        def go():
            for p in phones:
                try:
                    setup_chrome(p["serial"], log_fn=self._log_write)
                    self._log_write(f"  ✅ {p['name']}: Chrome first-run flags applied\n")
                except Exception as e:
                    self._log_write(f"  ⚠ {p['name']}: {e}\n")
            def done_ui():
                self._chrome_btn.config(state="normal", text="Optional: tame Chrome first-run on all phones")
                self._log_write("Chrome optional pass finished (browser-only — no Google account).\n")

            self.after(0, done_ui)
        threading.Thread(target=go, daemon=True).start()

    def _install_user_apk_all_phones(self):
        phones = state.get("phones", [])
        if not phones:
            messagebox.showwarning(
                "No phones",
                "Boot phones first.",
                parent=self.winfo_toplevel(),
            )
            return
        path = filedialog.askopenfilename(
            parent=self.winfo_toplevel(),
            title="Choose APK to install on all connected phones",
            filetypes=[("Android package", "*.apk"), ("All files", "*.*")],
            initialdir=_apk_pick_initialdir(),
        )
        if not path:
            return
        serials = [p["serial"] for p in phones]

        def go():
            summary = _install_apk_all_phones(path, serials, log_fn=None)

            def done_ui():
                apk_name = Path(path).name
                if not summary.get("results"):
                    messagebox.showerror(
                        "APK install",
                        f"Could not install {apk_name}.\n"
                        "Check that the file exists and USB debugging is authorized.",
                        parent=self.winfo_toplevel(),
                    )
                    return
                lines = []
                for p in phones:
                    match = next(
                        (
                            r
                            for r in summary["results"]
                            if r["serial"] == p["serial"]
                        ),
                        None,
                    )
                    ok_d = match and match["ok"]
                    lines.append(f"• {p['name']}: {'OK' if ok_d else 'Failed'}")
                body = "\n".join(lines)
                tail = (
                    "If this was Chrome, use Configure Chrome on all phones next."
                )
                if summary.get("ok"):
                    messagebox.showinfo(
                        "APK installed",
                        f"{apk_name}\n\n{body}\n\n{tail}",
                        parent=self.winfo_toplevel(),
                    )
                else:
                    messagebox.showwarning(
                        "APK install finished with errors",
                        f"{apk_name}\n\n{body}\n\n{tail}",
                        parent=self.winfo_toplevel(),
                    )

            self.after(0, done_ui)

        threading.Thread(target=go, daemon=True).start()

    def _setup_fdroid_browsers_all(self):
        phones = state.get("phones", [])
        if not phones:
            messagebox.showwarning(
                "No phones",
                "Boot phones first.",
                parent=self.winfo_toplevel(),
            )
            return
        self._log_write(
            "\nFennec / Mull: trying install-existing, then optional wizard/bundled/ "
            "(Fennec.apk, Mull.apk). Packages: "
            f"{FDROID_FENNEC_PKG}, {FDROID_MULL_PKG}\n"
        )

        def go():
            for p in phones:
                serial = p["serial"]
                try:
                    pkg = ensure_fdroid_browser(serial, log_fn=self._log_write)
                    if pkg:
                        self._log_write(f"  ✅ {p['name']}: {pkg}\n")
                    else:
                        self._log_write(
                            f"  ⚠ {p['name']}: no Fennec/Mull — install from F-Droid app or add "
                            f"bundled APK under wizard/bundled/\n"
                        )
                except Exception as e:
                    self._log_write(f"  ⚠ {p['name']}: {e}\n")
            self._log_write("Fennec/Mull pass finished.\n")

        threading.Thread(target=go, daemon=True).start()


    def _test_url(self):
        phones = state.get("phones", [])
        if not phones:
            messagebox.showwarning(
                "No phones",
                "Boot phones first.",
                parent=self.winfo_toplevel(),
            )
            return
        url = self._test_url_var.get().strip() or "https://google.com"
        serial = phones[0]["serial"]
        name = phones[0].get("name", serial)
        self._log_write(f"[wizard] Open test URL: {url!r} on {name} ({serial}) …\n")
        top = self.winfo_toplevel()

        def go():
            try:
                ok, note = chrome_open_url(serial, url)
            except Exception as e:
                err = str(e).strip() or type(e).__name__

                def fail_exc():
                    self._log_write(f"[wizard] Open test URL exception: {err}\n")
                    messagebox.showerror(
                        "Could not open URL on device",
                        f"{name}\n{url}\n\n{err}",
                        parent=top,
                    )

                self.after(0, fail_exc)
                return

            def done_ui():
                if ok:
                    self._log_write(
                        f"[wizard] Open test URL: adb VIEW ok on {name}. "
                        f"{note or 'Check the phone browser window.'}\n"
                    )
                    if note:
                        messagebox.showwarning(
                            "Link opened — check the phone",
                            f"{name}\n{url}\n\n{note}\n\n"
                            "1. On Launch, click Set up Tor and wait about a minute.\n"
                            "2. Click Fix the phone's internet.\n"
                            "3. Try the link again.",
                            parent=top,
                        )
                    else:
                        messagebox.showinfo(
                            "Link opened",
                            f"{name}\n{url}\n\n"
                            "Look at the phone screen.\n"
                            "Blank page? Wait a minute and try again.",
                            parent=top,
                        )
                else:
                    self._log_write(
                        f"[wizard] Open test URL FAILED on {name}: {note or 'unknown'}\n"
                    )
                    messagebox.showerror(
                        "Could not open link",
                        f"{name}\n{url}\n\n{note or 'The phone did not open a browser.'}\n\n"
                        "1. Turn on USB debugging on the phone.\n"
                        "2. Pick a browser (MuMu Browser on MuMu).\n"
                        "3. Make sure the phone is on in the list above.",
                        parent=top,
                    )

            self.after(0, done_ui)

        threading.Thread(target=go, daemon=True).start()

    def can_advance(self):
        self._prune_phones_against_adb()
        if state.get("phones"):
            return True
        # Emulator / MuMu often comes online after this page loaded — sync ADB once before blocking.
        try:
            devs = list_adb_devices()
        except Exception:
            devs = []
        if devs:
            state["phones"] = devs
            try:
                self._rebuild_grid()
                self._refresh_phone_summary()
                self._overall_lbl.config(
                    text=f"✅  {len(devs)} phone(s) connected (ADB)",
                    fg=GREEN,
                )
                avds = state.get("avds") or []
                for d in devs:
                    s = d["serial"]
                    row_lbl = self._status_rows.get(s)
                    if not row_lbl and s.startswith("emulator-"):
                        try:
                            port = int(s.split("-")[1])
                            idx = (port - 5554) // 2
                            if 0 <= idx < len(avds):
                                row_lbl = self._status_rows.get(avds[idx])
                        except (ValueError, IndexError):
                            pass
                    if row_lbl:
                        row_lbl.config(text="✅  Running", fg=GREEN)
            except tk.TclError:
                pass
            return True
        messagebox.showwarning(
            "Boot phones first",
            "Start phones on this step until at least one shows online,\n"
            "then tap Next.",
            parent=self.winfo_toplevel(),
        )
        return False


# ─── page: automation — default sequence (after devices exist) ────────────────


class AutomationPage(PageBase):
    """Edit default automation steps once phones are booted — feeds Groups."""

    def __init__(self, parent):
        super().__init__(parent)
        self._seq_steps: list = []
        self.header(
            "Automation",
            "Optional starter steps. You can change each phone later on Groups.",
        )

        intro = instruction_card(self)
        intro.pack(fill="x", pady=(0, SP["lg"]))
        tk.Label(
            intro,
            text="What to do here",
            font=FONT_SECTION,
            bg=BG2,
            fg=T1,
            anchor="w",
        ).pack(fill="x")
        intro_steps = tk.Label(
            intro,
            text=(
                "1. Build steps here or load a saved file.\n"
                "2. New phones in a team start with these steps.\n"
                "3. Change one phone anytime on Groups → Edit."
            ),
            font=FS,
            bg=BG2,
            fg=T2,
            justify="left",
            anchor="w",
        )
        intro_steps.pack(fill="x", pady=(SP["xs"], SP["md"]))
        bind_responsive_wraplength(intro_steps, intro, pad=28)
        intro_types = tk.Label(
            intro,
            text="Steps can open a website, tap the screen, wait, or switch internet place.",
            font=FS,
            bg=BG2,
            fg=T2,
            justify="left",
            anchor="w",
        )
        intro_types.pack(fill="x")
        bind_responsive_wraplength(intro_types, intro, pad=28)
        intro_timing = tk.Label(
            intro,
            text="Each phone waits and taps a little differently each time — that is on purpose.",
            font=FONT_CAPTION,
            bg=BG2,
            fg=T3,
            justify="left",
            anchor="w",
        )
        intro_timing.pack(fill="x", pady=(SP["sm"], 0))
        bind_responsive_wraplength(intro_timing, intro, pad=28)

        seq_row = tk.Frame(self, bg=BG)
        seq_row.pack(fill="x", pady=(0, SP["sm"]))
        tk.Button(
            seq_row, text="Edit default sequence",
            font=("Segoe UI", 10, "bold"),
            bg=ACCENT, fg=ON_ACCENT, relief="flat", cursor="hand2",
            padx=SP["md"], pady=SP["sm"],
            command=self._edit_sequence,
        ).pack(side="left", padx=(0, SP["sm"]))
        tk.Button(
            seq_row, text="Save sequence file as…",
            font=FS, bg=BG3, fg=T1, relief="flat", cursor="hand2",
            padx=SP["sm"], pady=SP["sm"],
            command=self._save_sequence,
        ).pack(side="left", padx=(0, SP["xs"]))
        tk.Button(
            seq_row, text="Load sequence file…",
            font=FS, bg=BG3, fg=T1, relief="flat", cursor="hand2",
            padx=SP["sm"], pady=SP["sm"],
            command=self._load_sequence,
        ).pack(side="left", padx=(0, SP["sm"]))
        self._seq_lbl = tk.Label(seq_row, text="No steps defined",
                                 font=FS, bg=BG, fg=T3)
        self._seq_lbl.pack(side="left")

    def on_enter(self):
        try:
            _maybe_autofill_python_cmd()
        except Exception:
            pass
        try:
            _maybe_autofill_pharmflow_dir()
        except Exception:
            pass
        self._seq_steps.clear()
        self._seq_steps.extend(state.get("default_steps", []))
        n = len(self._seq_steps)
        self._seq_lbl.config(
            text=f"{n} step{'s' if n != 1 else ''} in template" if n else "No steps defined",
            fg=T1 if n else T3,
        )

    def can_advance(self):
        if not state.get("phones"):
            messagebox.showwarning(
                "Boot phones first",
                "Go back one step and start your phones so ADB sees them.",
                parent=self.winfo_toplevel(),
            )
            return False
        state["default_steps"] = list(self._seq_steps)
        _apply_default_steps_to_template_phones()
        return True

    def _edit_sequence(self):
        dlg = PerPhoneSequenceEditor(
            self,
            serial="default",
            phone_name="Default sequence (template for group assignments)",
            steps_list=self._seq_steps,
        )
        self.wait_window(dlg)
        n = len(self._seq_steps)
        self._seq_lbl.config(
            text=f"{n} step{'s' if n != 1 else ''} in template" if n else "No steps defined",
            fg=T1 if n else T3,
        )
        state["default_steps"] = list(self._seq_steps)
        _apply_default_steps_to_template_phones()
        _persist_groups_config()

    def _save_sequence(self):
        if not self._seq_steps:
            messagebox.showinfo(
                "Nothing to save",
                "Add steps first via Edit.",
                parent=self.winfo_toplevel(),
            )
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Save sequence",
            defaultextension=".json",
            filetypes=[("JSON sequence", "*.json"), ("All files", "*.*")],
            initialfile="default_sequence.json",
            initialdir=_json_file_dialog_initialdir(),
        )
        if not path:
            return
        Path(path).write_text(json.dumps(self._seq_steps, indent=2))
        messagebox.showinfo(
            "Saved",
            f"Sequence saved to:\n{path}",
            parent=self.winfo_toplevel(),
        )

    def _load_sequence(self):
        path = filedialog.askopenfilename(
            parent=self,
            title="Load sequence",
            filetypes=[("JSON sequence", "*.json"), ("All files", "*.*")],
            initialdir=_json_file_dialog_initialdir(),
        )
        if not path:
            return
        try:
            data, _seq_meta = _load_sequence_document_from_path(Path(path))
        except SequenceJsonLoadError as exc:
            messagebox.showerror("Could not load sequence", str(exc), parent=self.winfo_toplevel())
            return
        raw_n = len(data)
        data = _normalize_sequence_steps(data)
        norm_n = len(data)
        if norm_n < raw_n:
            messagebox.showwarning(
                "Sequence normalized",
                f"Normalization dropped {raw_n - norm_n} step(s). "
                "Review unsupported or invalid entries before continuing.",
                parent=self.winfo_toplevel(),
            )
        self._seq_steps.clear()
        self._seq_steps.extend(data)
        state["default_steps"] = list(self._seq_steps)
        _apply_default_steps_to_template_phones()
        _persist_groups_config()
        n = len(self._seq_steps)
        self._seq_lbl.config(
            text=f"{n} step{'s' if n != 1 else ''} loaded" if n else "No steps defined",
            fg=T1 if n else T3,
        )


# ─── page: google play testing guide (deprecated — not in wizard flow) ─────────

class PlayStorePage(PageBase):
    """Deprecated stub — not in ``PharmFlowWizard.PAGES``. DabFlow is browser-only (getdabflow.app)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.header(
            "Removed",
            "Play Store testing is not part of PharmFlow. DabFlow runs in the browser only.",
        )
        box = instruction_card(self, pad=SP["md"])
        box.pack(fill="x", pady=(0, SP["sm"]))
        tk.Label(
            box,
            text=(
                "No Google account or Play Store install is required.\n"
                "Use Boot → test https://getdabflow.app, or assign browser ``open_url`` sequences in Groups."
            ),
            font=FS,
            bg=BG2,
            fg=T2,
            anchor="w",
            justify="left",
            wraplength=860,
        ).pack(fill="x")


# ─── page 6: groups & sequences ───────────────────────────────────────────────


class GroupsPage(PageBase):
    def __init__(self, parent):
        super().__init__(parent)
        self.header(
            "Groups",
            "Put phones in teams. Say how many times per day each phone should run.",
        )

        how_card = instruction_card(self)
        how_card.pack(fill="x", pady=(0, SP["md"]))
        how_outer, how_body = operator_callout(how_card, title="How this works")
        how_outer.pack(fill="x")
        callout_copy(
            how_body,
            (
                "1. Check the phones in this team (each phone joins one team only).\n"
                "2. Set how many runs per day for each phone.\n"
                "3. Tap Edit to change what one phone does.\n"
                "4. Red text on a row? Screen size may not match — open Edit to fix.\n"
                "5. Stuck? Tap Open setup guide for help."
            ),
            wrap_container=how_card,
            pady_top=0,
        )

        detail_card = instruction_card(self)
        detail_card.pack(fill="x", pady=(0, SP["lg"]))
        tk.Label(
            detail_card,
            text="Details",
            font=FONT_SECTION,
            bg=BG2,
            fg=T1,
            anchor="w",
        ).pack(fill="x", pady=(0, SP["xs"]))
        detail_lbl = tk.Label(
            detail_card,
            text="Stagger spreads phones apart so they do not all start at once. "
                 "Repeat runs the team more than once. "
                 "Clone to all phones copies Phone 1's plan to everyone else in the team.",
            font=FS,
            bg=BG2,
            fg=T2,
            justify="left",
            anchor="w",
        )
        detail_lbl.pack(fill="x")
        bind_responsive_wraplength(detail_lbl, detail_card, pad=28)
        self._grp_status = tk.Label(detail_card, text="", font=FS, bg=BG2, fg=GREEN, anchor="w")
        self._grp_status.pack(fill="x", pady=(SP["sm"], 0))

        ctrl = tk.Frame(self, bg=BG)
        ctrl.pack(fill="x", pady=(0, SP["md"]))
        ctrl_top = tk.Frame(ctrl, bg=BG)
        ctrl_top.pack(fill="x")
        ctrl_bot = tk.Frame(ctrl, bg=BG)
        ctrl_bot.pack(fill="x", pady=(SP["xs"], 0))
        self.btn(ctrl_top, "+ Add Group", self._add_group, color=GREEN)
        self.btn(
            ctrl_top,
            "Open setup guide",
            lambda: _open_setup_guide_doc(self.winfo_toplevel()),
            color=BG3,
        )
        self.btn(ctrl_bot, "Natural timing — all phones", self._humanize_all_sequences, color=PURPLE)
        self._count_lbl = tk.Label(ctrl_bot, text="", font=FS, bg=BG, fg=T2)
        self._count_lbl.pack(side="left", padx=8)

        wrapper = tk.Frame(self, bg=BG)
        wrapper.pack(fill="x")
        self._canvas = tk.Canvas(wrapper, bg=BG, highlightthickness=0)
        sb = themed_vertical_scrollbar(wrapper, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._inner = tk.Frame(self._canvas, bg=BG)
        self._win_id = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._inner.bind(
            "<Configure>",
            lambda _e: canvas_set_scrollregion_from_bbox_all(self._canvas),
        )
        self._canvas.bind(
            "<Configure>",
            lambda e: canvas_embed_set_width(self._canvas, self._win_id, e),
        )
        _bind_nested_canvas_mousewheel(self._canvas)
        self._cards: list[tk.Frame] = []
        self._scroll_bottom_pad: tk.Frame | None = None
        scroll_bottom_spacer(self).pack(fill="x")

    def on_enter(self):
        try:
            _maybe_autofill_pharmflow_dir()
        except Exception:
            pass
        try:
            _maybe_autofill_python_cmd()
        except Exception:
            pass
        _normalize_all_groups()
        _apply_default_steps_to_template_phones()
        self._rebuild()

    def _write_groups_or_warn(self, fail_text: str) -> bool:
        if _persist_groups_config():
            cur = str(self._grp_status.cget("text") or "")
            if "Groups on disk were not changed." in cur:
                self._grp_status.config(text="", fg=T2)
            return True
        self._grp_status.config(text=fail_text, fg=RED)
        return False

    def _add_group(self):
        n = len(state["groups"]) + 1
        default_steps = state.get("default_steps", [])
        phones_map = {}
        for p in state.get("phones", []):
            if not isinstance(p, dict):
                continue
            ser = (p.get("serial") or "").strip()
            if not ser:
                continue
            phones_map[ser] = {
                "steps": list(default_steps),
                "hits_per_day": DEFAULT_HITS_PER_DAY,
                "use_default_template": True,
                "explicit_override": False,
                "sequence_base_w": DEFAULT_SEQUENCE_BASE_W,
                "sequence_base_h": DEFAULT_SEQUENCE_BASE_H,
                "sequence_profile_key": _profile_key(DEFAULT_SEQUENCE_BASE_W, DEFAULT_SEQUENCE_BASE_H),
                "sequence_playlist": [],
                "sequence_playlist_secondary": [],
                "sequence_playlist_mode": "series",
                "sequence_playlist_shuffle": "none",
            }
        state["groups"].append({
            "name":           f"Group {n}",
            "phones":         phones_map,
            "stagger_secs":   30,
            "repeat":         1,
            "repeat_forever": False,
        })
        if not self._write_groups_or_warn(
            "Group was not saved. Groups on disk were not changed."
        ):
            state["groups"].pop()
            _try_load_groups_config()
        self._rebuild()

    def _remove_group(self, idx):
        if len(state["groups"]) <= 1:
            messagebox.showinfo(
                "Can't remove",
                "Need at least one group.",
                parent=self.winfo_toplevel(),
            )
            return
        removed = state["groups"].pop(idx)
        if not self._write_groups_or_warn(
            "Group was not removed. Groups on disk were not changed."
        ):
            state["groups"].insert(idx, removed)
            _try_load_groups_config()
        self._rebuild()

    def _rebuild(self):
        for c in self._cards:
            c.destroy()
        self._cards.clear()
        if self._scroll_bottom_pad is not None:
            self._scroll_bottom_pad.pack_forget()
        for i, g in enumerate(state["groups"]):
            card = self._build_card(i, g)
            card.pack(fill="x", pady=5, padx=2)
            self._cards.append(card)
        if self._scroll_bottom_pad is None:
            self._scroll_bottom_pad = tk.Frame(self._inner, bg=BG, height=48)
        self._scroll_bottom_pad.pack(fill="x")
        n = len(state["groups"])
        self._count_lbl.config(
            text=f"{n} group{'s' if n != 1 else ''}  — all run at the same time")
        canvas_schedule_scrollregion_refresh(self._canvas)


    def _build_card(self, idx, group):
        colors = [ACCENT, GREEN, ACCENT_DIM, RED, PURPLE]
        col    = colors[idx % len(colors)]

        card = tk.Frame(self._inner, bg=BG2, padx=14, pady=12,
                        highlightthickness=1, highlightbackground=BORDER)

        hdr = tk.Frame(card, bg=BG2)
        hdr.pack(fill="x")
        tk.Frame(hdr, bg=col, width=5).pack(side="left", fill="y", padx=(0, 10))

        name_var = tk.StringVar(value=group["name"])
        name_ent = tk.Entry(hdr, textvariable=name_var, font=("Segoe UI", 13, "bold"),
                            bg=BG3, fg=T1, relief="flat", width=20,
                            insertbackground=T1)
        name_ent.pack(side="left")
        name_var.trace_add("write", lambda *_: group.update({"name": name_var.get()}))

        def _persist_name(_event=None, g=group, var=name_var):
            g["name"] = var.get()
            self._write_groups_or_warn("Group name was not saved. Groups on disk were not changed.")

        name_ent.bind("<FocusOut>", _persist_name)
        name_ent.bind("<Return>", _persist_name)

        if len(state["groups"]) > 1:
            rm = tk.Button(hdr, text="Remove", font=FS, bg=RED, fg=ON_ACCENT,
                           relief="flat", cursor="hand2", padx=8, pady=3, bd=0,
                           highlightthickness=0,
                           command=lambda i=idx: self._remove_group(i))
            style_danger_button(rm)
            rm.pack(side="right")

        tk.Frame(card, bg=BORDER, height=1).pack(fill="x", pady=8)

        # ── Per-phone sequence editor ─────────────────────────────────────
        phones_frame = tk.Frame(card, bg=BG2)
        phones_frame.pack(fill="x", pady=(0, 8))

        tk.Label(phones_frame, text="Per-Phone Sequences",
                 font=("Segoe UI", 10, "bold"), bg=BG2, fg=T1, anchor="w").pack(fill="x")

        phone_map = group.get("phones", {})

        if not state["phones"]:
            tk.Label(phones_frame, text="Boot phones on Connect & boot before assigning groups.",
                     font=FS, bg=BG2, fg=RED).pack(anchor="w")
        else:
            for phone in state["phones"]:
                serial = phone["serial"]
                in_group = serial in phone_map
                if in_group:
                    pdata = phone_map[serial]
                    if not isinstance(pdata, dict):
                        pdata = {"steps": [], "hits_per_day": DEFAULT_HITS_PER_DAY}
                        phone_map[serial] = pdata
                    if "hits_per_day" not in pdata:
                        pdata["hits_per_day"] = DEFAULT_HITS_PER_DAY
                    if "use_default_template" not in pdata:
                        pdata["use_default_template"] = True
                    psteps = pdata.setdefault("steps", [])
                    use_template = bool(pdata.get("use_default_template", True))
                    hit_initial = int(pdata["hits_per_day"])
                else:
                    pdata = None
                    psteps = []
                    use_template = False
                    hit_initial = DEFAULT_HITS_PER_DAY

                row = tk.Frame(phones_frame, bg=BG3, padx=8, pady=5)
                row.pack(fill="x", pady=2)
                controls = tk.Frame(row, bg=BG3)
                controls.pack(side="right", anchor="e")
                details = tk.Frame(row, bg=BG3)
                details.pack(side="left", fill="x", expand=True)

                # Phone name
                tk.Label(details, text=f"{phone['name']}",
                         font=FM, bg=BG3, fg=T1, anchor="w").pack(side="left")

                # Step count
                step_cnt = len(psteps)
                source_label = "template" if use_template else "override"
                cnt_lbl = tk.Label(details, text=f"{step_cnt} steps ({source_label})",
                                   font=FM, bg=BG3,
                                   fg=GREEN if step_cnt else STATUS_PENDING, anchor="w")
                cnt_lbl.pack(side="left", padx=(4, 6))
                wm_w = phone.get("wm_w")
                wm_h = phone.get("wm_h")
                wm_size = (wm_w, wm_h) if isinstance(wm_w, int) and isinstance(wm_h, int) else None
                seq_bw = _coerce_profile_dim(
                    pdata.get("sequence_base_w") if isinstance(pdata, dict) else None,
                    DEFAULT_SEQUENCE_BASE_W,
                )
                seq_bh = _coerce_profile_dim(
                    pdata.get("sequence_base_h") if isinstance(pdata, dict) else None,
                    DEFAULT_SEQUENCE_BASE_H,
                )
                live_key = _profile_key(wm_size[0], wm_size[1]) if wm_size else "unknown"
                seq_key = _profile_key(seq_bw, seq_bh)
                mismatch = bool(wm_size and live_key != seq_key)
                prof_lbl = tk.Label(
                    details,
                    text=f"screen {seq_key} · phone {live_key}",
                    font=FONT_CAPTION,
                    bg=BG3,
                    fg=RED if mismatch else T3,
                    anchor="w",
                    justify="left",
                    wraplength=360,
                )
                prof_lbl.pack(side="left", padx=(0, 8))

                # Scheduler: hits per day (per phone)
                tk.Label(details, text="hits/day", font=FS, bg=BG3, fg=T3, width=7, anchor="e").pack(
                    side="left", padx=(2, 0))
                hits_var = tk.IntVar(value=hit_initial)

                def save_hits(*_, sv=serial, var=hits_var, g=group):
                    ent = g["phones"].get(sv)
                    if sv not in g["phones"] or not isinstance(ent, dict):
                        return
                    try:
                        ent["hits_per_day"] = max(0, int(var.get()))
                    except (tk.TclError, TypeError, ValueError):
                        ent["hits_per_day"] = DEFAULT_HITS_PER_DAY

                hits_ent = _int_clamped_entry(details, hits_var, 0, None, width=5, bg=BG2)
                hits_ent.pack(side="left", padx=(2, 8))

                def persist_hits(_event=None):
                    save_hits()
                    self._write_groups_or_warn(
                        "Hits per day was not saved. Groups on disk were not changed."
                    )

                hits_ent.bind("<FocusOut>", persist_hits)
                hits_ent.bind("<Return>", persist_hits)

                # Edit this phone's sequence
                def edit_phone(serial=serial, psteps_ref=[psteps], cnt_lbl=cnt_lbl, prof_lbl=prof_lbl, phone_wm_size=wm_size):
                    phone_name = next(
                        (p["name"] for p in state["phones"] if p["serial"] == serial),
                        serial
                    )
                    ent = group["phones"].get(serial)
                    if serial in group.get("phones", {}) and not isinstance(ent, dict):
                        ent = {
                            "steps": list(psteps_ref[0]),
                            "hits_per_day": DEFAULT_HITS_PER_DAY,
                            "use_default_template": False,
                            "explicit_override": True,
                        }
                        group["phones"][serial] = ent
                    win = PerPhoneSequenceEditor(
                        self.app, serial, phone_name, psteps_ref[0],
                        phone_ent=ent if isinstance(ent, dict) else None,
                        phone_wm_size=phone_wm_size,
                    )
                    self.app.wait_window(win)
                    if not getattr(win, "_did_save", False):
                        return
                    ent = group["phones"].get(serial)
                    if isinstance(ent, dict):
                        ent["use_default_template"] = False
                        ent["explicit_override"] = True
                        seq_bw2 = _coerce_profile_dim(ent.get("sequence_base_w"), DEFAULT_SEQUENCE_BASE_W)
                        seq_bh2 = _coerce_profile_dim(ent.get("sequence_base_h"), DEFAULT_SEQUENCE_BASE_H)
                        seq_key2 = _profile_key(seq_bw2, seq_bh2)
                        live_key2 = _profile_key(phone_wm_size[0], phone_wm_size[1]) if phone_wm_size else "unknown"
                        prof_lbl.config(
                            text=f"screen {seq_key2} · phone {live_key2}",
                            fg=RED if (phone_wm_size and live_key2 != seq_key2) else T3,
                        )
                    cnt_lbl.config(text=f"{len(psteps_ref[0])} steps (override)",
                                   fg=GREEN if psteps_ref[0] else STATUS_PENDING)
                    _persist_groups_config()

                ed_img = load_icon("icon_edit", self.winfo_toplevel())
                eb_kw = dict(
                    text="Edit",
                    font=FS, bg=ACCENT, fg=ON_ACCENT, relief="flat",
                    cursor="hand2", command=edit_phone,
                    padx=6, pady=2, bd=0, highlightthickness=0,
                )
                if ed_img:
                    eb_kw["image"] = ed_img
                    eb_kw["compound"] = "left"
                eb = tk.Button(row, **eb_kw)
                style_primary_button(eb)
                eb.pack(in_=controls, side="left", padx=(2, 0))

                # Toggle
                var = tk.BooleanVar(value=serial in phone_map)

                def toggle(v=var, s=serial, ref=[psteps], hv=hits_var, g=group):
                    if v.get():
                        for other in state["groups"]:
                            if other is g:
                                continue
                            if s in (other.get("phones") or {}):
                                other["phones"].pop(s, None)
                        if s not in g["phones"]:
                            try:
                                h = max(0, int(hv.get()))
                            except (tk.TclError, TypeError, ValueError):
                                h = DEFAULT_HITS_PER_DAY
                            g["phones"][s] = {
                                "steps": list(state.get("default_steps", [])),
                                "hits_per_day": h,
                                "use_default_template": True,
                                "explicit_override": False,
                                "sequence_base_w": DEFAULT_SEQUENCE_BASE_W,
                                "sequence_base_h": DEFAULT_SEQUENCE_BASE_H,
                                "sequence_profile_key": _profile_key(DEFAULT_SEQUENCE_BASE_W, DEFAULT_SEQUENCE_BASE_H),
                            }
                        self._rebuild()
                    else:
                        g["phones"].pop(s, None)

                def remove_from_group(s=serial, v=var, g=group):
                    g["phones"].pop(s, None)
                    v.set(False)
                    self._rebuild()

                tk.Checkbutton(row, text="", variable=var, onvalue=True, offvalue=False,
                               command=toggle, font=FB, bg=BG3, fg=T1, selectcolor=GREEN,
                               activebackground=BG3).pack(in_=controls, side="right")
                ou = tk.Button(row, text="Out", font=FS, bg=BG4, fg=T1, relief="flat",
                               cursor="hand2", padx=6, pady=2, bd=0,
                               command=remove_from_group)
                style_secondary_button(ou)
                ou.pack(in_=controls, side="right", padx=(4, 4))

            # ── Clone master button ───────────────────────────────────────────
            if state["phones"] and len(state["phones"]) > 1:
                _fp = state["phones"][0]
                _ms = (
                    (_fp.get("serial") or "").strip()
                    if isinstance(_fp, dict)
                    else ""
                )
                if _ms:
                    clone_row = tk.Frame(phones_frame, bg=BG2)
                    clone_row.pack(fill="x", pady=(6, 0))
                    master_serial = _ms
                    _ment = phone_map.get(master_serial, {}) or {}
                    master_steps = _ment.get("steps", [])

                    def clone_all(ms=master_serial, msteps=master_steps, g=group, me=_ment):
                        # Clone Phone 1's sequence (and optional playlist) to every phone in the group.
                        mpl = me.get("sequence_playlist")
                        mpl2 = me.get("sequence_playlist_secondary")
                        mpm = me.get("sequence_playlist_mode")
                        mpsh = me.get("sequence_playlist_shuffle")
                        mbw = _coerce_profile_dim(me.get("sequence_base_w"), DEFAULT_SEQUENCE_BASE_W)
                        mbh = _coerce_profile_dim(me.get("sequence_base_h"), DEFAULT_SEQUENCE_BASE_H)
                        for phone in state["phones"]:
                            if not isinstance(phone, dict):
                                continue
                            s = (phone.get("serial") or "").strip()
                            if not s:
                                continue
                            for other in state["groups"]:
                                if other is g:
                                    continue
                                other["phones"].pop(s, None)
                            if s in g["phones"]:
                                ent = g["phones"][s]
                                if not isinstance(ent, dict):
                                    ent = {"steps": list(msteps),
                                           "hits_per_day": DEFAULT_HITS_PER_DAY,
                                           "use_default_template": False,
                                           "explicit_override": True}
                                    g["phones"][s] = ent
                                else:
                                    prev_h = ent.get("hits_per_day", DEFAULT_HITS_PER_DAY)
                                    ent["steps"] = list(msteps)
                                    ent["hits_per_day"] = prev_h
                                    ent["use_default_template"] = False
                                    ent["explicit_override"] = True
                                ent["sequence_base_w"] = mbw
                                ent["sequence_base_h"] = mbh
                                ent["sequence_profile_key"] = _profile_key(mbw, mbh)
                                if isinstance(mpl, list):
                                    ent["sequence_playlist"] = list(mpl)
                                if isinstance(mpl2, list):
                                    ent["sequence_playlist_secondary"] = list(mpl2)
                                if mpm:
                                    ent["sequence_playlist_mode"] = mpm
                                ent["sequence_playlist_shuffle"] = (
                                    _normalize_sequence_playlist_shuffle(mpsh)
                                )
                            else:
                                ent = {
                                    "steps": list(msteps),
                                    "hits_per_day": DEFAULT_HITS_PER_DAY,
                                    "use_default_template": False,
                                    "explicit_override": True,
                                    "sequence_base_w": mbw,
                                    "sequence_base_h": mbh,
                                    "sequence_profile_key": _profile_key(mbw, mbh),
                                }
                                if isinstance(mpl, list):
                                    ent["sequence_playlist"] = list(mpl)
                                if isinstance(mpl2, list):
                                    ent["sequence_playlist_secondary"] = list(mpl2)
                                if mpm:
                                    ent["sequence_playlist_mode"] = mpm
                                ent["sequence_playlist_shuffle"] = (
                                    _normalize_sequence_playlist_shuffle(mpsh)
                                )
                                g["phones"][s] = ent
                        saved = _persist_groups_config()
                        if not saved:
                            _try_load_groups_config()
                            self._rebuild()
                            self._grp_status.config(
                                text=f"[{g['name']}] Copy was not saved. Groups on disk were not changed.",
                                fg=RED,
                            )
                            return
                        self._rebuild()
                        self._log_write(f"[{g['name']}] Master sequence copied to all phones.")

                    cl_img = load_icon("icon_clone", self.winfo_toplevel())
                    cb_kw = dict(
                        text="Clone to all phones (Phone 1 is master)",
                        font=FS, bg=PURPLE, fg=ON_ACCENT, relief="flat", cursor="hand2",
                        command=clone_all, padx=8, pady=4, bd=0, highlightthickness=0,
                    )
                    if cl_img:
                        cb_kw["image"] = cl_img
                        cb_kw["compound"] = "left"
                    cb = tk.Button(clone_row, **cb_kw)
                    cb.configure(activebackground=PURPLE_ACTIVE, activeforeground=ON_ACCENT)
                    cb.pack(side="left")

        tk.Frame(card, bg=BORDER, height=1).pack(fill="x", pady=(0, 8))

        # Timing
        timing = tk.Frame(card, bg=BG2)
        timing.pack(fill="x")

        def lbl(text): return tk.Label(timing, text=text, font=FS, bg=BG2, fg=T2)

        stag_var    = tk.IntVar(value=group["stagger_secs"])
        rep_var     = tk.IntVar(value=group["repeat"])
        forever_var = tk.BooleanVar(value=group["repeat_forever"])

        def save(*_):
            group.update({"stagger_secs": stag_var.get(),
                          "repeat":       rep_var.get(),
                          "repeat_forever": forever_var.get()})
            self._write_groups_or_warn(
                "Group timing was not saved. Groups on disk were not changed."
            )

        def int_timing_entry(var, lo, hi, w=5):
            e = _int_clamped_entry(timing, var, lo, hi, width=w, bg=BG3)

            def on_commit(_event=None):
                save()

            e.bind("<FocusOut>", on_commit)
            e.bind("<Return>", on_commit)
            return e

        lbl("Delay between phones:").pack(side="left")
        int_timing_entry(stag_var, 0, None).pack(side="left", padx=4)
        lbl("sec  |  Repeat:").pack(side="left", padx=(4, 0))
        int_timing_entry(rep_var, 1, None).pack(side="left", padx=4)
        lbl("times  |").pack(side="left")
        tk.Checkbutton(timing, text="Forever", variable=forever_var,
                       font=FS, bg=BG2, fg=T1, selectcolor=BG3,
                       activebackground=BG2).pack(side="left", padx=4)

        forever_var.trace_add("write", save)

        # Test APK: installed on every phone in this group before the group runs.
        apk_row = tk.Frame(card, bg=BG2)
        apk_row.pack(fill="x", pady=(6, 0))
        tk.Label(apk_row, text="Test APK:", font=FS, bg=BG2, fg=T2).pack(side="left")
        apk_var = tk.StringVar(value=str(group.get("apk") or ""))
        apk_entry = tk.Entry(apk_row, textvariable=apk_var, width=32,
                             bg=BG3, fg=T1, relief="flat", insertbackground=T1, font=FS)
        apk_entry.pack(side="left", padx=4)
        apk_browse_btn = tk.Button(
            apk_row, text="Browse…", font=FS, bg=BG3, fg=T1, relief="flat",
            cursor="hand2", padx=8, pady=2, bd=0, highlightthickness=0,
        )
        apk_browse_btn.pack(side="left", padx=(0, 4))

        def _apk_browse():
            apks_dir = Path(__file__).resolve().parents[1] / "apks"
            apks_dir.mkdir(parents=True, exist_ok=True)
            path = filedialog.askopenfilename(
                parent=self.winfo_toplevel(),
                title="Pick test APK for this group",
                filetypes=[("Android package", "*.apk"), ("All files", "*.*")],
                initialdir=str(apks_dir),
            )
            if not path:
                return
            src = Path(path)
            dest = apks_dir / src.name
            if src.resolve() != dest.resolve():
                try:
                    shutil.copyfile(src, dest)
                except OSError:
                    self._log_write(f"Could not copy APK into apks/: {src.name}")
                    return
            apk_var.set(src.name)
            save()

        def _save_apk(_event=None):
            group["apk"] = apk_var.get().strip()
            save()

        apk_browse_btn.config(command=_apk_browse)
        apk_entry.bind("<FocusOut>", _save_apk)
        apk_entry.bind("<Return>", _save_apk)

        return card


    def _log_write(self, text: str):
        self._grp_status.config(text=text, fg=GREEN)
        self.after(6000, lambda: self._grp_status.config(text=""))

    def _humanize_all_sequences(self):
        n = 0
        for g in state.get("groups") or []:
            pmap = g.get("phones") or {}
            for serial, ent in pmap.items():
                if not isinstance(ent, dict):
                    continue
                steps = ent.get("steps")
                if not isinstance(steps, list) or not steps:
                    continue
                digest = hashlib.sha256(
                    serial.encode("utf-8", errors="replace")
                ).digest()[:8]
                seed = int.from_bytes(digest, "big")
                rng = random.Random(seed)
                ent["steps"] = humanize_steps(steps, rng)
                ent["explicit_override"] = True
                ent["use_default_template"] = False
                n += 1
        if n == 0:
            self._grp_status.config(
                text="No phone sequences to change. Add steps on a phone first.",
                fg=T2,
            )
            return
        saved = _persist_groups_config()
        if not saved:
            _try_load_groups_config()
            self._rebuild()
            self._grp_status.config(
                text="Natural timing was not saved. Groups on disk were not changed.",
                fg=RED,
            )
            return
        self._rebuild()
        self._log_write(f"Applied natural timing tweaks on {n} phone sequence(s).")

    def can_advance(self):
        for g in state["groups"]:
            if not g["phones"]:
                messagebox.showwarning(
                    "Empty group",
                    f"'{g['name']}' has no phones assigned.\n"
                    "Tick at least one phone or remove the group.",
                    parent=self.winfo_toplevel(),
                )
                return False
        return True

    def populate_footer_actions(self, parent: tk.Frame) -> None:
        """Wizard-shell hook: add Groups-specific buttons to the non-scrolling footer.

        Mirrors the per-phone editor's "Tryout / Run now" button but applies to every
        phone in every group, so users can validate the full playlist setup without
        opening Edit on each phone first.
        """
        run_now = tk.Button(
            parent,
            text="Tryout / Run playlist now",
            font=("Segoe UI", 11, "bold"),
            bg=ACCENT,
            fg=ON_ACCENT,
            relief="flat",
            cursor="hand2",
            command=self._tryout_all,
            padx=SP["lg"],
            pady=SP["sm"],
            bd=0,
            highlightthickness=0,
        )
        style_primary_button(run_now)
        run_now.pack(side="left")

    def _tryout_runnable_phone_count(self) -> int:
        """Count phones in any group that have inline steps or a configured playlist."""
        usable = 0
        for g in state.get("groups") or []:
            for ent in (g.get("phones") or {}).values():
                if not isinstance(ent, dict):
                    continue
                steps = ent.get("steps") or []
                pl_a = _normalize_sequence_playlist_items(ent.get("sequence_playlist"))
                pl_b = _normalize_sequence_playlist_items(
                    ent.get("sequence_playlist_secondary")
                )
                if steps or pl_a or pl_b:
                    usable += 1
        return usable

    def _tryout_all(self) -> None:
        """Save groups and start running every phone now via the existing Launch path.

        Validation order matches ``can_advance`` so the same dialogs surface that
        ``Next Step`` would show, then we additionally require at least one phone
        to have steps or a playlist (otherwise the run would target zero phones).
        Routes through ``PharmFlowWizard.start_tryout_from_groups`` so the actual
        sequence execution stays on the single, tested ``_start_automation_one_click``
        code path used by the Launch step.
        """
        groups = state.get("groups") or []
        if not groups:
            messagebox.showwarning(
                "No groups",
                "Add at least one group with phones before running a tryout.",
                parent=self.winfo_toplevel(),
            )
            return
        if not self.can_advance():
            return
        usable = self._tryout_runnable_phone_count()
        if usable == 0:
            messagebox.showwarning(
                "Nothing to run",
                "No phone has steps or saved sequence files yet.\n\n"
                "Tap Edit on a phone to add steps or pick sequence files.",
                parent=self.winfo_toplevel(),
            )
            return
        if not messagebox.askokcancel(
            "Run playlist now?",
            f"Save groups and start running {usable} phone(s) now?\n\n"
            "This switches to the Launch step and triggers the same one-click run "
            "(server start if needed, load groups, run all groups).",
            parent=self.winfo_toplevel(),
        ):
            return
        wiz = getattr(self, "app", None)
        if wiz is None or not hasattr(wiz, "start_tryout_from_groups"):
            messagebox.showerror(
                "Can't run now",
                "Something went wrong starting a test run.\n\n"
                "Go to the Launch step and tap Start automation.",
                parent=self.winfo_toplevel(),
            )
            return
        try:
            wiz.start_tryout_from_groups()
        except Exception as exc:
            messagebox.showerror(
                "Run failed",
                f"Could not start the run:\n{exc}",
                parent=self.winfo_toplevel(),
            )


# ─── add step dialog ──────────────────────────────────────────────────────────

class AddStepDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.result = None
        self.title("Add a Step")
        self.config(bg=BG)
        self.geometry("600x560")
        self.minsize(520, 460)
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True)

        scroll_host = tk.Frame(outer, bg=BG)
        scroll_host.pack(fill="both", expand=True, padx=SP["page"], pady=(SP["page"], 0))
        self._scroll_canvas = tk.Canvas(scroll_host, bg=BG, highlightthickness=0)
        scroll_sb = themed_vertical_scrollbar(scroll_host, command=self._scroll_canvas.yview)
        self._scroll_canvas.configure(yscrollcommand=scroll_sb.set)
        scroll_sb.pack(side="right", fill="y")
        self._scroll_canvas.pack(side="left", fill="both", expand=True)
        shell = tk.Frame(self._scroll_canvas, bg=BG)
        self._scroll_window_id = self._scroll_canvas.create_window((0, 0), window=shell, anchor="nw")
        shell.bind(
            "<Configure>",
            lambda _e: canvas_set_scrollregion_from_bbox_all(self._scroll_canvas),
        )
        self._scroll_canvas.bind(
            "<Configure>",
            lambda e: canvas_embed_set_width(self._scroll_canvas, self._scroll_window_id, e),
        )
        _bind_nested_canvas_mousewheel(self._scroll_canvas)

        tk.Label(shell, text="What should the phone do?",
                 font=("Segoe UI", 13, "bold"), bg=BG, fg=T1).pack(anchor="w", pady=(0, SP["md"]))

        type_frame = instruction_card(shell)
        type_frame.pack(fill="x", pady=(0, SP["md"]))
        tk.Label(type_frame, text="Action:", font=FB,
                 bg=BG2, fg=T2, width=10, anchor="w").pack(side="left")
        self._type = tk.StringVar(value="open_url")
        combo = ttk.Combobox(type_frame, textvariable=self._type,
                             values=list(STEP_LABELS.keys()),
                             state="readonly", font=FB, width=28)
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda _: self._update())

        self._desc = tk.Label(shell, text="", font=FS, bg=BG, fg=T2,
                              wraplength=500, justify="left")
        self._desc.pack(anchor="w", pady=(0, SP["sm"]))
        bind_responsive_wraplength(self._desc, shell, pad=32, min_width=180)

        self._fields_frame = instruction_card(shell)
        self._fields_frame.pack(fill="x", pady=(0, SP["md"]))
        self._fields: dict[str, tk.StringVar] = {}
        self._update()

        scroll_bottom_spacer(shell).pack(fill="x")

        btn_row = tk.Frame(
            outer,
            bg=FOOTER_BG,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        btn_row.pack(side="bottom", fill="x", padx=SP["page"], pady=(SP["sm"], SP["page"]))
        tk.Button(btn_row, text="  OK  ",
                  font=("Segoe UI", 11, "bold"),
                  bg=GREEN, fg=ON_ACCENT, relief="flat",
                  cursor="hand2", command=self._ok,
                  padx=SP["lg"], pady=SP["sm"]).pack(side="left", padx=(0, SP["sm"]))
        tk.Button(btn_row, text="Cancel", font=FB,
                  bg=BG3, fg=T2, relief="flat",
                  cursor="hand2", command=self.destroy,
                  padx=SP["md"], pady=SP["sm"]).pack(side="left")

    def _update(self):
        for w in self._fields_frame.winfo_children():
            w.destroy()
        self._fields.clear()
        t = self._type.get()
        self._desc.config(text=STEP_LABELS.get(t, ""))

        def field(label, key, default="", width=32):
            row = tk.Frame(self._fields_frame, bg=BG2)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, font=FB, bg=BG2, fg=T2,
                     width=18, anchor="w").pack(side="left")
            var = tk.StringVar(value=str(default))
            tk.Entry(row, textvariable=var, font=FM, bg=BG, fg=T1,
                     insertbackground=T1, relief="flat",
                     width=width).pack(side="left")
            self._fields[key] = var

        def tip(text):
            tk.Label(self._fields_frame, text=text, font=FS,
                     bg=BG2, fg=T3, justify="left").pack(anchor="w", pady=1)

        if t == "open_url":
            field("Website URL:", "url", "https://getdabflow.app", 36)
            field("After-open wait (sec):", "post_wait_secs", "", 8)
            tip(
                "Optional pause after the browser opens — use 3–8 on slow networks or heavy pages. "
                "Leave blank for no extra wait."
            )
        elif t == "launch_app":
            field("Package name:", "package", "com.example.app", 36)
            field("After-open wait (sec):", "post_wait_secs", "", 8)
            tip("Install the app on the phone first. Package looks like com.company.app.")
        elif t == "tap":
            field("X (left ↔ right):", "x", 540)
            field("Y (top ↕ bottom):", "y", 1280)
            field("Retries:", "retries", 2)
            field("Jitter ±px:", "jitter", 24)
            field("Pre-wait ms:", "pre_wait_ms", 0)
            tip("Retries + jitter help flaky buttons. Typical phone 1080×2400 — adjust Y for your UI.")
        elif t == "wait":
            field("Seconds:", "seconds", 5)
        elif t == "swipe":
            field("Start X:", "x1", 540)
            field("Start Y:", "y1", 1600)
            field("End X:",   "x2", 540)
            field("End Y:",   "y2", 400)
            field("Speed ms:", "ms", 600)
            tip("Swipe up: high Y → low Y")
        elif t == "keyevent":
            field("Key:", "key", "BACK")
            tip("Options: BACK   HOME   ENTER   APP_SWITCH   VOLUME_UP")
        elif t == "close_app":
            field("Package (optional):", "package", "")
            tip("Leave empty to close the default browser on the device (auto-detected).")
        elif t == "type_text":
            field("Text:", "text", "hello world")
        elif t == "rotate_identity":
            tip(
                "Gives this phone a new identity. In Scramble mode: new device fingerprint. "
                "In Tor mode: new exit country. Use before steps that open websites."
            )
        self.after_idle(lambda: canvas_set_scrollregion_from_bbox_all(self._scroll_canvas))

    def _ok(self):
        t    = self._type.get()
        step = {"type": t}
        for key, var in self._fields.items():
            v = var.get().strip()
            if v == "":
                continue
            if key == "post_wait_secs" and t == "open_url":
                try:
                    step[key] = max(0.0, float(v))
                except ValueError:
                    pass
                continue
            if t == "tap" and key == "pre_wait_ms":
                try:
                    step[key] = float(v)
                except ValueError:
                    step[key] = v
                continue
            try:
                step[key] = int(v)
            except ValueError:
                step[key] = v
        self.result = step
        self.destroy()


# ─── page 7: launch & control ─────────────────────────────────────────────────

_running_groups: dict[str, bool] = {}


class LaunchPage(PageBase):
    def __init__(self, parent):
        super().__init__(parent)
        self._server_proc = None
        self.header(
            "Go",
            "Start PharmFlow, pick browse mode (Scramble recommended for ads), run your phone teams. "
            "(Emulator hide: done in Phone Setup (Home → Step 1) unless you need Re-apply in section E.)",
        )

        # Summary
        summary_outer = instruction_card(self, pad=SP["md"])
        summary_outer.pack(fill="x", pady=(0, SP["sm"]))
        tk.Label(summary_outer, text="Your groups:",
                 font=("Segoe UI", 10, "bold"), bg=BG2, fg=T1,
                 anchor="w").pack(fill="x")
        sum_row = tk.Frame(summary_outer, bg=BG2)
        sum_row.pack(fill="x")
        self._summary = tk.Text(sum_row, height=4, font=FM, bg=BG2, fg=T1,
                                relief="flat", wrap="word")
        _attach_readonly_log_text(self._summary)
        sum_sb = themed_vertical_scrollbar(sum_row, command=self._summary.yview)
        self._summary.configure(yscrollcommand=sum_sb.set)
        self._summary.pack(side="left", fill="both", expand=True)
        sum_sb.pack(side="right", fill="y")

        go_outer = tk.Frame(summary_outer, bg=BG2)
        go_outer.pack(fill="x", pady=(10, 0))
        go_callout_outer, go_body = operator_callout(go_outer, title="Quick steps")
        go_callout_outer.pack(fill="x")
        callout_copy(
            go_body,
            (
                "1. Tap Start server (section A).\n"
                "2. Save browse mode Scramble (section F) — or Set up Tor if mode is Tor.\n"
                "3. Tap Run all groups (section B).\n"
                "(Section E only if Setup exe did not run or phones were rebooted.)"
            ),
            wrap_container=go_outer,
            pady_top=0,
        )
        go_hint = tk.Label(
            go_body,
            text="Big green button starts the server and runs groups (Scramble: no Tor setup needed).",
            font=FS,
            bg=CALLOUT_BG,
            fg=CALLOUT_MUTED,
            anchor="w",
            justify="left",
        )
        go_hint.pack(fill="x", pady=(SP["xs"], SP["sm"]))
        bind_responsive_wraplength(go_hint, go_outer, pad=32)
        go_row = tk.Frame(go_body, bg=CALLOUT_BG)
        go_row.pack(fill="x")
        self._btn_start_automation = tk.Button(
            go_row,
            text="Start automation",
            font=("Segoe UI", 12, "bold"),
            bg=GREEN,
            fg=ON_ACCENT,
            relief="flat",
            cursor="hand2",
            command=self._start_automation_one_click,
            bd=0,
            highlightthickness=0,
        )
        self._btn_start_automation.configure(
            activebackground=GREEN_ACTIVE, activeforeground=ON_ACCENT
        )
        self._btn_start_automation.pack(side="left", padx=(0, 10))
        tk.Label(
            go_row,
            text="(Step-by-step: A → B below if you prefer.)",
            font=FONT_CAPTION,
            bg=CALLOUT_BG,
            fg=T3,
            anchor="w",
        ).pack(side="left")

        # Server
        srv = tk.Frame(self, bg=BG3, padx=14, pady=12)
        srv.pack(fill="x", pady=(0, 8))
        tk.Label(srv, text="A — Start PharmFlow on this PC",
                 font=("Segoe UI", 11, "bold"), bg=BG3,
                 fg=ACCENT, anchor="w").pack(fill="x")
        srv_hint = tk.Label(
            srv,
            text=(
                "This keeps PharmFlow running on your PC. Leave it on while your phone teams work."
            ),
            font=FS,
            bg=BG3,
            fg=T2,
            anchor="w",
            justify="left",
        )
        srv_hint.pack(fill="x", pady=(2, 8))
        bind_responsive_wraplength(srv_hint, srv, pad=28)
        srv_note = tk.Label(
            srv,
            text="Each phone waits and taps a little differently each time — that is on purpose.",
            font=FONT_CAPTION,
            bg=BG3,
            fg=T3,
            anchor="w",
            justify="left",
        )
        srv_note.pack(fill="x", pady=(0, 6))
        bind_responsive_wraplength(srv_note, srv, pad=28)
        srv_row = tk.Frame(srv, bg=BG3)
        srv_row.pack(fill="x")
        self._btn_srv_start = tk.Button(srv_row, text="Start server",
                                        font=("Segoe UI", 10, "bold"),
                                        bg=GREEN, fg=ON_ACCENT, relief="flat",
                                        cursor="hand2", command=self._start_server,
                                        bd=0, highlightthickness=0)
        self._btn_srv_start.configure(activebackground=GREEN_ACTIVE, activeforeground=ON_ACCENT)
        self._btn_srv_start.pack(side="left", padx=(0, 8))
        self._btn_srv_stop = tk.Button(srv_row, text="Stop server",
                                       font=("Segoe UI", 10, "bold"),
                                       bg=RED, fg=ON_ACCENT, relief="flat",
                                       cursor="hand2", command=self._stop_server,
                                       state="disabled", bd=0, highlightthickness=0)
        style_danger_button(self._btn_srv_stop)
        self._btn_srv_stop.pack(side="left")
        self._srv_lbl = tk.Label(srv_row, text="Server not running",
                                  font=FS, bg=BG3, fg=T2)
        self._srv_lbl.pack(side="left", padx=10)

        # Groups (B — after server)
        grp = tk.Frame(self, bg=BG3, padx=14, pady=12)
        grp.pack(fill="x", pady=(0, 8))
        tk.Label(grp, text="B — Run your phone teams",
                 font=("Segoe UI", 11, "bold"), bg=BG3,
                 fg=GREEN, anchor="w").pack(fill="x")
        grp_hint = tk.Label(grp,
                 text="Starts all groups at the same time. Each group runs on its assigned phones.",
                 font=FS, bg=BG3, fg=T2, anchor="w", justify="left")
        grp_hint.pack(fill="x", pady=(2, 8))
        bind_responsive_wraplength(grp_hint, grp, pad=28)
        grp_row = tk.Frame(grp, bg=BG3)
        grp_row.pack(fill="x")
        self._btn_run = tk.Button(grp_row, text="Run all groups",
                                  font=("Segoe UI", 10, "bold"),
                                  bg=GREEN, fg=ON_ACCENT, relief="flat",
                                  cursor="hand2", command=self._run_groups,
                                  bd=0, highlightthickness=0)
        self._btn_run.configure(activebackground=GREEN_ACTIVE, activeforeground=ON_ACCENT)
        self._btn_run.pack(side="left", padx=(0, 8))
        self._btn_stop_grp = tk.Button(grp_row, text="Stop all groups",
                                       font=("Segoe UI", 10, "bold"),
                                       bg=RED, fg=ON_ACCENT, relief="flat",
                                       cursor="hand2", state="disabled",
                                       command=self._stop_groups,
                                       bd=0, highlightthickness=0)
        style_danger_button(self._btn_stop_grp)
        self._btn_stop_grp.pack(side="left")
        self._run_lbl = tk.Label(grp_row, text="", font=FS, bg=BG3, fg=T2)
        self._run_lbl.pack(side="left", padx=10)

        # Schedule (C)
        sched = tk.Frame(self, bg=BG3, padx=14, pady=12)
        sched.pack(fill="x", pady=(0, 8))
        tk.Label(sched, text="C — Daily Schedule",
                 font=("Segoe UI", 11, "bold"), bg=BG3,
                 fg=PURPLE, anchor="w").pack(fill="x")
        sched_copy = tk.Label(
            sched,
            text="Enter how many hits per day — the schedule randomizer places them in uneven bursts "
                 "across the full 24h (not equal spacing). Per-phone counts override on the Groups page; "
                 "the number below is the fallback for phones not in any group.",
            font=FS,
            bg=BG3,
            fg=T2,
            anchor="w",
            justify="left",
        )
        sched_copy.pack(fill="x", pady=(2, 8))
        bind_responsive_wraplength(sched_copy, sched, pad=28)

        sched_row = tk.Frame(sched, bg=BG3)
        sched_row.pack(fill="x")
        tk.Label(sched_row, text="Hits / day (fallback):", font=FS, bg=BG3, fg=T2).pack(side="left")
        self._sched_hits_var = tk.IntVar(value=DEFAULT_HITS_PER_DAY)
        tk.Entry(sched_row, textvariable=self._sched_hits_var, font=FM,
                 bg=BG2, fg=T1, insertbackground=T1, relief="flat",
                 width=8).pack(side="left", padx=6)
        tk.Label(sched_row, text="(unassigned phones only)", font=FS, bg=BG3, fg=T2).pack(side="left")
        sched_opts = tk.Frame(sched, bg=BG3)
        sched_opts.pack(fill="x", pady=(SP["xs"], 0))
        self._sched_organic_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            sched_opts,
            text="Uneven 24h spread (recommended)",
            variable=self._sched_organic_var,
            font=FS,
            bg=BG3,
            fg=T2,
            selectcolor=BG2,
            activebackground=BG3,
            activeforeground=T1,
        ).pack(anchor="w")
        self._sched_tor_local_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            sched_opts,
            text="Daytime in Tor exit country (no 3am host hits when exit is abroad)",
            variable=self._sched_tor_local_var,
            font=FS,
            bg=BG3,
            fg=T2,
            selectcolor=BG2,
            activebackground=BG3,
            activeforeground=T1,
        ).pack(anchor="w", pady=(SP["xs"], 0))
        sched_btns = tk.Frame(sched, bg=BG3)
        sched_btns.pack(fill="x", pady=(SP["xs"], 0))
        self._sched_btn = tk.Button(sched_btns,
                                   text="Start schedule",
                                   font=("Segoe UI", 10, "bold"),
                                   bg=PURPLE, fg=ON_ACCENT, relief="flat",
                                   cursor="hand2", command=self._start_schedule,
                                   bd=0, highlightthickness=0)
        self._sched_btn.configure(activebackground=PURPLE_ACTIVE, activeforeground=ON_ACCENT)
        self._sched_btn.pack(side="left", padx=(8, 0))
        self._sched_stop_btn = tk.Button(
            sched_btns,
            text="Stop schedule",
            font=("Segoe UI", 10, "bold"),
            bg=BG4,
            fg=T1,
            relief="flat",
            cursor="hand2",
            command=self._stop_schedule,
            bd=0,
            highlightthickness=0,
        )
        style_secondary_button(self._sched_stop_btn)
        self._sched_stop_btn.pack(side="left", padx=(8, 0))
        self._sched_lbl = tk.Label(sched_btns, text="", font=FS, bg=BG3, fg=T2)
        self._sched_lbl.pack(side="left", padx=8)

        # Same POST route the dashboard uses for "Load Groups Config" (in-browser fetch uses POST body).
        grp_reload = tk.Frame(self, bg=BG3, padx=14, pady=10)
        grp_reload.pack(fill="x", pady=(0, 8))
        tk.Label(
            grp_reload,
            text="D — Reload saved groups into the server",
            font=("Segoe UI", 11, "bold"),
            bg=BG3,
            fg=T1,
            anchor="w",
        ).pack(fill="x")
        reload_copy = tk.Label(
            grp_reload,
            text="After you save groups (or edit groups_config.json by hand), click here so "
                 "Run all groups uses the latest file.",
            font=FS,
            bg=BG3,
            fg=T2,
            anchor="w",
            justify="left",
        )
        reload_copy.pack(fill="x", pady=(2, 8))
        bind_responsive_wraplength(reload_copy, grp_reload, pad=28)
        gr_row = tk.Frame(grp_reload, bg=BG3)
        gr_row.pack(fill="x")
        self._btn_reload_groups = tk.Button(
            gr_row,
            text="Reload groups file",
            font=("Segoe UI", 10, "bold"),
            bg=ACCENT,
            fg=ON_ACCENT,
            relief="flat",
            cursor="hand2",
            command=self._reload_groups_on_server,
            bd=0,
            highlightthickness=0,
        )
        style_primary_button(self._btn_reload_groups)
        self._btn_reload_groups.pack(side="left")
        self._reload_groups_lbl = tk.Label(gr_row, text="", font=FS, bg=BG3, fg=T2)
        self._reload_groups_lbl.pack(side="left", padx=10)

        fp_fr = tk.Frame(self, bg=BG3, padx=14, pady=12)
        fp_fr.pack(fill="x", pady=(0, 8))
        tk.Label(
            fp_fr,
            text="E — Re-apply hide emulator + DabFlow ads (optional)",
            font=("Segoe UI", 11, "bold"),
            bg=BG3,
            fg=GREEN,
            anchor="w",
        ).pack(fill="x")
        fp_copy = tk.Label(
            fp_fr,
            text=(
                "Use if PharmFlow MuMu setup did not run, after MuMu cold boot, or Mantis ads never show. "
                "Re-applies retail phone disguise + browser ad-zone patch flags on ALL phones."
            ),
            font=FS,
            bg=BG3,
            fg=T2,
            anchor="w",
            justify="left",
        )
        fp_copy.pack(fill="x", pady=(2, 8))
        bind_responsive_wraplength(fp_copy, fp_fr, pad=28)
        fp_row = tk.Frame(fp_fr, bg=BG3)
        fp_row.pack(fill="x")
        self._btn_fp_launch = tk.Button(
            fp_row,
            text="Re-apply hide emulator on ALL phones",
            font=("Segoe UI", 10, "bold"),
            bg=GREEN,
            fg=ON_ACCENT,
            relief="flat",
            cursor="hand2",
            command=self._launch_hide_emulator_all,
            bd=0,
            highlightthickness=0,
        )
        self._btn_fp_launch.configure(activebackground=GREEN_ACTIVE, activeforeground=ON_ACCENT)
        self._btn_fp_launch.pack(side="left", padx=(0, 8))
        self._fp_launch_lbl = tk.Label(fp_row, text="", font=FS, bg=BG3, fg=T2)
        self._fp_launch_lbl.pack(side="left", padx=10)

        tor_fr = tk.Frame(self, bg=BG3, padx=14, pady=12)
        tor_fr.pack(fill="x", pady=(0, 8))
        tk.Label(
            tor_fr,
            text="F — Internet & ad browse mode",
            font=("Segoe UI", 11, "bold"),
            bg=BG3,
            fg=GREEN,
            anchor="w",
        ).pack(fill="x")
        tor_copy = tk.Label(
            tor_fr,
            text=(
                "Scramble (default) — pin each phone's own exit and rotate device look each visit. "
                "Never the host IP.\n"
                "Tor — different country per phone (privacy; ads often empty on emulator).\n"
                "Upstream — add residential proxy URLs in desktop_prefs.json (one per phone)."
            ),
            font=FS,
            bg=BG3,
            fg=T2,
            anchor="w",
            justify="left",
        )
        tor_copy.pack(fill="x", pady=(2, 8))
        bind_responsive_wraplength(tor_copy, tor_fr, pad=28)
        browse_row = tk.Frame(tor_fr, bg=BG3)
        browse_row.pack(fill="x", pady=(0, 8))
        tk.Label(browse_row, text="Browse mode:", font=FS, bg=BG3, fg=T2).pack(side="left")
        self._browse_mode_var = tk.StringVar(value="scramble")
        self._browse_mode_combo = ttk.Combobox(
            browse_row,
            textvariable=self._browse_mode_var,
            values=("scramble", "direct", "upstream", "tor"),
            state="readonly",
            width=14,
            font=FS,
        )
        self._browse_mode_combo.pack(side="left", padx=(8, 8))
        self._btn_browse_mode_save = tk.Button(
            browse_row,
            text="Save mode",
            font=FS,
            bg=BG4,
            fg=T1,
            relief="flat",
            cursor="hand2",
            command=self._save_browse_proxy_mode,
            bd=0,
            highlightthickness=0,
        )
        style_secondary_button(self._btn_browse_mode_save)
        self._btn_browse_mode_save.pack(side="left")
        self._browse_mode_lbl = tk.Label(browse_row, text="", font=FS, bg=BG3, fg=T2)
        self._browse_mode_lbl.pack(side="left", padx=10)
        self.after_idle(self._load_browse_proxy_mode_ui)
        tor_row = tk.Frame(tor_fr, bg=BG3)
        tor_row.pack(fill="x")
        tk.Label(
            tor_row,
            text="Tor (optional — only when browse mode is Tor):",
            font=FS,
            bg=BG3,
            fg=T2,
        ).pack(side="left", padx=(0, 8))
        self._btn_tor = tk.Button(
            tor_row,
            text="Set up Tor",
            font=("Segoe UI", 10, "bold"),
            bg=GREEN,
            fg=ON_ACCENT,
            relief="flat",
            cursor="hand2",
            command=self._tor_setup,
            bd=0,
            highlightthickness=0,
        )
        self._btn_tor.configure(activebackground=GREEN_ACTIVE, activeforeground=ON_ACCENT)
        self._btn_tor.pack(side="left", padx=(0, 8))
        self._btn_tor_off = tk.Button(
            tor_row,
            text="Re-pin phone exits",
            font=FS,
            bg=BG4,
            fg=T1,
            relief="flat",
            cursor="hand2",
            command=self._tor_teardown,
            bd=0,
            highlightthickness=0,
        )
        style_secondary_button(self._btn_tor_off)
        self._btn_tor_off.pack(side="left")
        self._tor_lbl = tk.Label(tor_row, text="", font=FS, bg=BG3, fg=T2)
        self._tor_lbl.pack(side="left", padx=10)

        tor_fix = tk.Frame(tor_fr, bg=BG3)
        tor_fix.pack(fill="x", pady=(8, 0))
        tor_fix_copy = tk.Label(
            tor_fix,
            text=(
                "Phone says no internet or the page is blank? Tap the button below. "
                "It reconnects that phone to its own exit. It does not turn the proxy off."
            ),
            font=FS,
            bg=BG3,
            fg=T2,
            anchor="w",
            justify="left",
        )
        tor_fix_copy.pack(fill="x", pady=(0, 6))
        bind_responsive_wraplength(tor_fix_copy, tor_fr, pad=28)
        self._btn_fix_browsers = tk.Button(
            tor_fix,
            text="Fix the phone's internet",
            font=("Segoe UI", 10, "bold"),
            bg=ACCENT,
            fg=ON_ACCENT,
            relief="flat",
            cursor="hand2",
            command=self._fix_browsers_clear_proxy,
            bd=0,
            highlightthickness=0,
        )
        style_primary_button(self._btn_fix_browsers)
        self._btn_fix_browsers.pack(side="left")

        # True-up (daily scheduler — swap steps without restarting threads)
        tu = tk.Frame(self, bg=BG3, padx=14, pady=12)
        tu.pack(fill="x", pady=(0, 8))
        tk.Label(tu, text="G — True-up daily schedule",
                 font=("Segoe UI", 11, "bold"), bg=BG3,
                 fg=ACCENT, anchor="w").pack(fill="x")
        tu_copy = tk.Label(
            tu,
            text="While the daily schedule runs: paste new steps for one phone. "
                 "The next scheduled run uses this list — you do not need to restart the schedule.",
            font=FS,
            bg=BG3,
            fg=T2,
            anchor="w",
            justify="left",
        )
        tu_copy.pack(fill="x", pady=(2, 8))
        bind_responsive_wraplength(tu_copy, tu, pad=28)
        tu_row = tk.Frame(tu, bg=BG3)
        tu_row.pack(fill="x")
        tk.Label(tu_row, text="Phone ID (from Boot step):", font=FS, bg=BG3, fg=T2).pack(side="left")
        self._true_up_serial = tk.Entry(tu_row, font=FM, bg=BG2, fg=T1,
                                        insertbackground=T1, relief="flat", width=24)
        self._true_up_serial.pack(side="left", padx=6)
        tub = tk.Button(tu_row, text="Apply true-up",
                        font=("Segoe UI", 10, "bold"),
                        bg=ACCENT, fg=ON_ACCENT, relief="flat",
                        cursor="hand2", command=self._true_up_schedule,
                        bd=0, highlightthickness=0)
        style_primary_button(tub)
        tub.pack(side="left", padx=(8, 0))
        self._true_up_lbl = tk.Label(tu_row, text="", font=FS, bg=BG3, fg=T2)
        self._true_up_lbl.pack(side="left", padx=8)
        tu_json_row = tk.Frame(tu, bg=BG3)
        tu_json_row.pack(fill="x", pady=(6, 0))
        tu_ld = tk.Button(
            tu_json_row,
            text="Load steps from JSON…",
            font=FS,
            bg=BG3,
            fg=T1,
            relief="flat",
            cursor="hand2",
            command=self._true_up_load_json,
            bd=0,
            highlightthickness=0,
        )
        style_secondary_button(tu_ld)
        tu_ld.pack(side="left")
        json_fr = tk.Frame(tu, bg=BG3)
        json_fr.pack(fill="x", pady=(8, 0))
        self._true_up_json = tk.Text(json_fr, height=4, font=FM, bg=BG2, fg=T1,
                                     relief="flat", wrap="word")
        json_sb = themed_vertical_scrollbar(json_fr, command=self._true_up_json.yview)
        self._true_up_json.configure(yscrollcommand=json_sb.set)
        self._true_up_json.pack(side="left", fill="both", expand=True)
        json_sb.pack(side="right", fill="y")

        # Log
        tk.Label(self, text="Live log:", font=("Segoe UI", 9, "bold"),
                 bg=BG, fg=T2, anchor="w").pack(fill="x", pady=(4, 2))
        log_fr = tk.Frame(self, bg=BG2)
        log_fr.pack(fill="x", pady=(4, 0))
        self._log_box = tk.Text(log_fr, height=6, font=FM, bg=BG2, fg=T1,
                                relief="flat", wrap="word")
        _attach_readonly_log_text(self._log_box)
        log_sb = themed_vertical_scrollbar(log_fr, command=self._log_box.yview)
        self._log_box.configure(yscrollcommand=log_sb.set)
        self._log_box.pack(side="left", fill="both", expand=True)
        log_sb.pack(side="right", fill="y")

        # APK install, Teach recording, and “open URL on all phones” are full web flows; open the dashboard
        # instead of re-implementing them in Tk (see buttons below).
        misc = tk.Frame(self, bg=BG)
        misc.pack(fill="x", pady=SP["sm"])
        tk.Button(
            misc,
            text="Open dashboard",
            font=FS,
            bg=BG3,
            fg=T1,
            relief="flat",
            cursor="hand2",
            command=self._open_dashboard_browser,
        ).pack(side="left", padx=(0, SP["sm"]))
        tk.Button(misc, text="Save groups config",
                  font=FS, bg=BG3, fg=T1, relief="flat", cursor="hand2",
                  command=self._save).pack(side="left")

        scroll_bottom_spacer(self).pack(fill="x")

    def on_enter(self):
        try:
            _maybe_autofill_pharmflow_dir()
        except Exception:
            pass
        try:
            _maybe_autofill_python_cmd()
        except Exception:
            pass
        try:
            _normalize_all_groups()
            _apply_default_steps_to_template_phones()
            self._refresh_summary()
            self._save()
        except Exception:
            tb = traceback.format_exc()
            print(f"[wizard] Launch page on_enter failed:\n{tb}", file=sys.stderr)
            try:
                self._log(f"Launch page setup error — check stderr log.\n{tb}")
            except Exception:
                pass

    def _refresh_summary(self):
        lines = []
        for i, g in enumerate(state["groups"], 1):
            if not isinstance(g, dict):
                continue
            names = []
            hits_list = []
            pmap = g.get("phones")
            if not isinstance(pmap, dict):
                pmap = {}
            for s in pmap:
                m = next(
                    (
                        p
                        for p in state["phones"]
                        if isinstance(p, dict) and p.get("serial") == s
                    ),
                    None,
                )
                names.append(m.get("name", s) if m else s)
                ent = pmap.get(s)
                if isinstance(ent, dict) and "hits_per_day" in ent:
                    try:
                        hits_list.append(int(ent["hits_per_day"]))
                    except (TypeError, ValueError):
                        pass
            rep = "forever" if g.get("repeat_forever") else f"{g.get('repeat', 1)}×"
            hpart = ""
            if hits_list:
                lo, hi = min(hits_list), max(hits_list)
                hpart = f"  |  hits/day {lo}" if lo == hi else f"  |  hits/day {lo}–{hi}"
            lens = []
            for ent in pmap.values():
                if isinstance(ent, dict):
                    lens.append(len(ent.get("steps") or []))
            if lens:
                slo, shi = min(lens), max(lens)
                step_part = f"{slo} steps" if slo == shi else f"{slo}–{shi} steps"
            else:
                step_part = "0 steps"
            lines.append(
                f"  {g.get('name', 'Group')}  |  {len(names)} phone(s)  |  {step_part}{hpart}  |  "
                f"stagger {g.get('stagger_secs', 30)}s  |  {rep}")
        self._summary.delete("1.0", "end")
        self._summary.insert("end", "\n".join(lines) or "  (no groups)")

    def _log(self, text):
        def _do():
            self._log_box.insert("end", text + "\n")
            self._log_box.see("end")
        self.after(0, _do)

    _log_write = lambda self, t: self._log(t)

    def _save(self):
        return _persist_groups_config() or ""

    def _open_dashboard_browser(self, path: str = "/") -> None:
        """Open the web dashboard; discover actual HTTP port if default ``PHARMFLOW_PORT`` is busy."""

        def work() -> None:
            probe_dashboard_listen_port()
            base = dashboard_base_url().rstrip("/")
            if path in ("", "/"):
                url = base + "/"
            else:
                p = path if path.startswith("/") else "/" + path
                url = base + p
            self.after(0, lambda u=url: webbrowser.open(u))

        threading.Thread(target=work, daemon=True).start()

    def _start_server(self):
        import tempfile

        d = state.get("pharmflow_dir", "")
        if not d:
            d = str(_pharmflow_install_root())
            state["pharmflow_dir"] = d

        self._save()
        dashboard = Path(d) / "automation" / "dashboard.py"
        if not dashboard.exists():
            messagebox.showerror(
                "Not found",
                f"dashboard.py not found at:\n{dashboard}\n\n"
                "Make sure PharmFlow is cloned correctly.",
                parent=self.winfo_toplevel(),
            )
            return

        clear_dashboard_listen_port_cache()

        self._btn_srv_start.config(state="disabled")
        self._srv_lbl.config(text="Installing packages…", fg=STATUS_PROGRESS)
        self._log("Checking/installing websockets + psutil…")

        def _launch():
            try:
                # Frozen EXE is not CPython — probing/spawning it as python opens
                # another Control Panel. Prefer a real interpreter; fall back to
                # in-process dashboard (same path the WebView deck uses).
                if getattr(sys, "frozen", False):
                    try:
                        from pharmflow_wizard_bridge import _start_dashboard_headless

                        res = _start_dashboard_headless()
                        if res.get("ok"):
                            self.after(
                                0,
                                lambda: (
                                    self._srv_lbl.config(text="Server running", fg=GREEN),
                                    self._btn_run.config(state="normal"),
                                    self._btn_srv_start.config(state="disabled"),
                                    self._btn_srv_stop.config(state="normal"),
                                    self._log(
                                        "Control server started (frozen EXE — in-process / helper).\n"
                                    ),
                                ),
                            )
                            return
                        err = res.get("error") or "dashboard start refused"
                        self.after(
                            0,
                            lambda: (
                                self._srv_lbl.config(text="Start failed", fg=RED),
                                self._btn_srv_start.config(state="normal"),
                                self._log(f"Dashboard start failed: {err}\n"),
                            ),
                        )
                        return
                    except Exception as exc:  # noqa: BLE001
                        self.after(
                            0,
                            lambda: (
                                self._srv_lbl.config(text="Start failed", fg=RED),
                                self._btn_srv_start.config(state="normal"),
                                self._log(f"Dashboard start failed: {exc}\n"),
                            ),
                        )
                        return

                py_argv, py_disp = _resolve_python_cmd(state.get("python_cmd"))
                state["python_cmd"] = py_disp
                state["python_cmd_argv"] = list(py_argv)
                cf = _NO_WIN

                self.after(0, lambda: self._log(f"Using Python: {py_disp}"))

                def _deps_ok():
                    chk = subprocess.run(
                        py_argv + ["-c", "import websockets, psutil"],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        creationflags=cf,
                    )
                    return chk.returncode == 0

                skip_pip = os.environ.get("PHARMFLOW_OFFLINE", "").strip().lower() in (
                    "1",
                    "true",
                    "yes",
                )

                if _deps_ok():
                    self.after(
                        0,
                        lambda: self._log(
                            "Dependencies already present — skipping pip.\n"
                        ),
                    )
                elif skip_pip:
                    self.after(
                        0,
                        lambda: self._log(
                            "PHARMFLOW_OFFLINE set — skipping pip. "
                            f"If launch fails, install:\n  {py_disp} -m pip install websockets psutil\n"
                        ),
                    )
                    if not _deps_ok():
                        self.after(
                            0,
                            lambda: (
                                self._srv_lbl.config(text="Missing packages", fg=RED),
                                self._btn_srv_start.config(state="normal"),
                                self._log(
                                    "websockets/psutil not importable. "
                                    "Unset PHARMFLOW_OFFLINE or install deps manually.\n"
                                ),
                            ),
                        )
                        return
                else:
                    attempts = [
                        (
                            "pip (global)",
                            py_argv + ["-m", "pip", "install", "--quiet",
                             "websockets>=12.0", "psutil>=5.9.0"],
                        ),
                        (
                            "pip --user",
                            py_argv + ["-m", "pip", "install", "--quiet", "--user",
                             "websockets>=12.0", "psutil>=5.9.0"],
                        ),
                    ]
                    pip_ok = False
                    for label, cmd in attempts:
                        pip = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            timeout=120,
                            creationflags=cf,
                        )
                        if pip.returncode == 0 or _deps_ok():
                            pip_ok = True
                            self.after(
                                0,
                                lambda lbl=label: self._log(f"{lbl}: OK\n"),
                            )
                            break
                        err = pip.stderr.strip() or pip.stdout.strip() or "pip failed"
                        self.after(
                            0,
                            lambda lbl=label, e=err[-800:]: self._log(
                                f"{lbl} failed (continuing if imports work…)\n{e}\n"
                            ),
                        )
                    if not pip_ok and not _deps_ok():
                        self.after(
                            0,
                            lambda: self._log(
                                "pip did not report success; checking imports…\n"
                            ),
                        )
                    if not _deps_ok():
                        self.after(
                            0,
                            lambda: (
                                self._srv_lbl.config(
                                    text="Missing websockets/psutil", fg=RED
                                ),
                                self._btn_srv_start.config(state="normal"),
                                self._log(
                                    "Cannot start dashboard: install with\n"
                                    f"  {py_disp} -m pip install --user websockets psutil\n"
                                ),
                            ),
                        )
                        return

                self.after(0, lambda: (
                    self._srv_lbl.config(text="Starting…", fg=STATUS_PROGRESS),
                    self._log("Dependencies OK — launching server…"),
                ))

                import tempfile as _tmp
                err_file = _tmp.NamedTemporaryFile(
                    mode="w", suffix=".log", delete=False
                )
                err_path = err_file.name
                err_file.close()

                log_fh = open(err_path, "w")
                try:
                    launch_cmd = py_argv + [str(dashboard)]
                    self.after(
                        0,
                        lambda c=launch_cmd: self._log(f"Launch command: {_cmd_display(c)}"),
                    )
                    proc = subprocess.Popen(
                        launch_cmd,
                        cwd=str(dashboard.parent),
                        stdin=subprocess.DEVNULL,
                        stdout=log_fh,
                        stderr=log_fh,
                        creationflags=_DASHBOARD_SPAWN_FLAGS,
                    )
                finally:
                    log_fh.close()

                self._server_proc = proc
                self.after(0, lambda: self._btn_srv_stop.config(state="normal"))

                # Wait until GET /api/config answers (or process dies). A fixed 3s sleep
                # falsely reports "running" before the HTTP bind on slow ARM64 hosts.
                ready_sec = float(_dashboard_ready_timeout_sec())
                deadline = time.time() + ready_sec
                ready = False
                while time.time() < deadline:
                    if proc.poll() is not None:
                        break
                    if probe_dashboard_listen_port():
                        ready = True
                        break
                    time.sleep(0.45)
                if ready:
                    self.after(0, lambda: (
                        self._srv_lbl.config(text="Server running", fg=GREEN),
                        self._btn_run.config(state="normal"),
                        self._log("Server is up! Click Run All Groups to start."),
                    ))
                elif proc.poll() is None:
                    self.after(0, lambda: (
                        self._srv_lbl.config(text="Server starting…", fg=STATUS_PROGRESS),
                        self._btn_run.config(state="normal"),
                        self._log(
                            "Server process is alive but /api/config is not ready yet — "
                            "wait a bit, then retry Run / Set up Tor."
                        ),
                    ))
                else:
                    try:
                        errtxt = Path(err_path).read_text(errors="replace").strip()[-1200:]
                    except Exception:
                        errtxt = "(no output captured)"
                    self.after(0, lambda et=errtxt: (
                        self._srv_lbl.config(text="Server crashed", fg=RED),
                        self._btn_srv_start.config(state="normal"),
                        self._btn_srv_stop.config(state="disabled"),
                        self._log(f"Server crashed:\n{et}"),
                    ))
            except Exception as exc:
                attempted = state.get("python_cmd_argv") or [state.get("python_cmd") or "python"]
                self.after(0, lambda e=exc: (
                    self._srv_lbl.config(text="Launch error", fg=RED),
                    self._btn_srv_start.config(state="normal"),
                    self._log(
                        f"Launch error: {e}\n"
                        f"Attempted: {_cmd_display(attempted)} {dashboard.name}\n"
                        "If Python is missing, install it and retry Launch."
                    ),
                ))

        threading.Thread(target=_launch, daemon=True).start()

    def _stop_server(self):
        self._stop_groups()
        # Stopping the wizard server must not delete guest http_proxy or stop
        # Tor. That drops farm traffic onto the VM/host path.
        self._api("/api/scheduler/stop", {})
        if self._server_proc:
            self._server_proc.terminate()
            self._server_proc = None
        clear_dashboard_listen_port_cache()
        self._srv_lbl.config(text="Stopped", fg=T2)
        self._btn_srv_start.config(state="normal")
        self._btn_srv_stop.config(state="disabled")
        self._btn_run.config(state="disabled")
        self._log_write("Server stopped.")

    def _api(self, path, body, timeout=12):
        import urllib.error
        import urllib.request

        data = json.dumps(body).encode()
        delay = 0.35
        last_err = None
        retried_probe = False
        for attempt in range(6):
            url = f"{dashboard_base_url()}{path}"
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                try:
                    raw = e.read().decode("utf-8", errors="replace")
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict) and parsed.get("error"):
                        return parsed
                except Exception:
                    pass
                return {"error": str(e)}
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last_err = e
                err_s = str(e).lower()
                refused = (
                    "10061" in str(e)
                    or "refused" in err_s
                    or "actively refused" in err_s
                )
                if refused and not retried_probe:
                    retried_probe = True
                    if probe_dashboard_listen_port():
                        continue
                if attempt < 5 and (
                    refused
                    or "timed out" in err_s
                ):
                    time.sleep(delay)
                    delay = min(delay * 1.65, 2.8)
                    continue
                if "10061" in str(e) or "refused" in err_s:
                    return {
                        "error": (
                            "The server is not running. "
                            "On Launch, tap Start server, wait until it says running, then try again."
                        )
                    }
                return {"error": str(e)}
        if last_err and ("10061" in str(last_err) or "refused" in str(last_err).lower()):
            return {
                "error": (
                    "The server is not running. "
                    "On Launch, tap Start server first."
                )
            }
        return {"error": str(last_err) if last_err else "Could not reach the server"}

    def _run_groups(self):
        self._log_write("Starting all groups… (Tor may still be starting — that is OK)")
        self._btn_run.config(state="disabled")
        self._btn_stop_grp.config(state="normal")

        def go():
            result = self._api("/api/groups/run", {"groups": state["groups"]}, timeout=120)
            if "error" in result:

                def err_ui():
                    self._log_write(f"❌  {result['error']}")
                    self._btn_run.config(state="normal")
                    self._btn_stop_grp.config(state="disabled")

                self.after(0, err_ui)
            else:
                n = result.get("groups", len(state["groups"]))
                pt = result.get("phones_targeted")

                def ok_ui():
                    if isinstance(pt, int) and pt >= 0:
                        self._log_write(
                            f"✅  {n} group(s) running in parallel — {pt} phone(s) targeted."
                        )
                        self._run_lbl.config(text=f"{n} groups · {pt} phones", fg=GREEN)
                    else:
                        self._log_write(f"✅  {n} group(s) running in parallel!")
                        self._run_lbl.config(text=f"{n} running", fg=GREEN)

                self.after(0, ok_ui)

        threading.Thread(target=go, daemon=True).start()

    def _dashboard_config_reachable(self) -> bool:
        return probe_dashboard_listen_port()

    def _wait_dashboard_reachable(self, timeout_sec: float) -> bool:
        deadline = time.time() + float(timeout_sec)
        delay = 0.35
        while time.time() < deadline:
            if self._dashboard_config_reachable():
                return True
            time.sleep(delay)
            delay = min(delay * 1.45, 2.6)
        return False

    def _start_automation_one_click(self):
        """Save groups, ensure GET /api/config works, load groups on server, run all groups."""
        self._log_write("Start automation: saving groups…")
        self._save()

        def work():
            if not self._dashboard_config_reachable():
                _ready_sec = _dashboard_ready_timeout_sec()
                self.after(
                    0,
                    lambda s=_ready_sec: self._log_write(
                        f"Starting server — wait up to ~{int(s)}s "
                        "(first run may install packages)…"
                    ),
                )
                self.after(0, self._start_server)
                time.sleep(0.5)
                if not self._wait_dashboard_reachable(_ready_sec):
                    msg = (
                        "The server did not start in time.\n\n"
                        f"Waited about {int(_ready_sec)} seconds.\n"
                        "1. Check the Live log below for errors.\n"
                        "2. Tap Start server and wait until it says running.\n"
                        "3. Try Start automation again."
                    )

                    def fail():
                        self._log_write(f"❌  Server did not start in time.")
                        messagebox.showerror(
                            "Server not ready",
                            msg,
                            parent=self.winfo_toplevel(),
                        )

                    self.after(0, fail)
                    return

            load_r = self._api("/api/groups/load", {})
            if load_r.get("error"):

                def load_err():
                    self._log_write(f"❌  Load groups: {load_r['error']}")

                self.after(0, load_err)
                return

            run_r = self._api("/api/groups/run", {"groups": state["groups"]}, timeout=120)
            if run_r.get("error"):

                def run_err():
                    self._log_write(f"❌  {run_r['error']}")
                    self._btn_run.config(state="normal")
                    self._btn_stop_grp.config(state="disabled")

                self.after(0, run_err)
                return

            n = run_r.get("groups", len(state["groups"]))
            pt = run_r.get("phones_targeted")

            def ok():
                if isinstance(pt, int) and pt >= 0:
                    self._log_write(
                        f"✅  {n} group(s) running — {pt} phone(s) targeted "
                        "(config loaded from disk)."
                    )
                    self._run_lbl.config(text=f"{n} groups · {pt} phones", fg=GREEN)
                else:
                    self._log_write(
                        f"✅  {n} group(s) running in parallel (config loaded from disk)."
                    )
                    self._run_lbl.config(text=f"{n} running", fg=GREEN)
                self._btn_run.config(state="disabled")
                self._btn_stop_grp.config(state="normal")

            self.after(0, ok)

        threading.Thread(target=work, daemon=True).start()

    def _stop_groups(self):
        def go():
            self._api("/api/groups/stop", {})

            def done_ui():
                self._log_write("All groups stopped.")
                self._run_lbl.config(text="", fg=T2)
                self._btn_run.config(state="normal")
                self._btn_stop_grp.config(state="disabled")

            self.after(0, done_ui)

        threading.Thread(target=go, daemon=True).start()

    def _start_schedule(self):
        """Start the daily schedule on all booted phones (per-phone steps and hits from Groups)."""
        try:
            fallback_hits = max(0, int(self._sched_hits_var.get()))
        except (TypeError, ValueError, tk.TclError):
            fallback_hits = DEFAULT_HITS_PER_DAY
        phones = state.get("phones", [])
        if not phones:
            messagebox.showwarning(
                "No phones running",
                "Boot phones on Connect & boot first.",
                parent=self.winfo_toplevel(),
            )
            return
        serials = [
            s
            for p in phones
            if isinstance(p, dict) and (s := (p.get("serial") or "").strip())
        ]
        default_steps = list(state.get("default_steps", []))
        steps_per_serial = {s: list(default_steps) for s in serials}
        hits_per_serial = {s: fallback_hits for s in serials}
        assigned: set[str] = set()
        for g in state.get("groups") or []:
            for s, pdata in (g.get("phones") or {}).items():
                if s not in serials or s in assigned:
                    continue
                if isinstance(pdata, dict):
                    steps_per_serial[s] = list(pdata.get("steps", default_steps))
                    try:
                        hits_per_serial[s] = max(0, int(pdata.get("hits_per_day", fallback_hits)))
                    except (TypeError, ValueError):
                        hits_per_serial[s] = fallback_hits
                assigned.add(s)
        try:
            import urllib.request
            url = f"{dashboard_base_url()}/api/scheduler/start"
            spread = "organic" if self._sched_organic_var.get() else "uniform"
            body = json.dumps({
                "serials": serials,
                "steps": default_steps,
                "hits_per_day": fallback_hits,
                "steps_per_serial": steps_per_serial,
                "hits_per_serial": hits_per_serial,
                "schedule_spread": spread,
                "schedule_tor_local": bool(self._sched_tor_local_var.get()),
            }).encode()
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json"},
                method="POST")
            with urllib.request.urlopen(req, timeout=5) as r:
                result = json.loads(r.read())
            started = result.get("started") if isinstance(result.get("started"), list) else []
            already = result.get("already_running") if isinstance(result.get("already_running"), list) else []
            errors = result.get("errors") if isinstance(result.get("errors"), list) else []
            if started or already:
                hvals = [hits_per_serial.get(s, fallback_hits) for s in started or already]
                hsum = f"{min(hvals)}-{max(hvals)}" if hvals and min(hvals) != max(hvals) else str(
                    hvals[0] if hvals else fallback_hits)
                note = "already running" if already and not started else "threads started"
                self._sched_lbl.config(
                    text=f"Scheduler {note} for {len(started or already)} phone(s) ({hsum} hits/day). A hit counts only after the sequence lands.",
                    fg=T1)
                self._log_write(
                    "Scheduler threads started. Each phone uses its own Groups steps and hits. "
                    "A hit counts only after that sequence lands.\n"
                )
                for err in errors:
                    self._log_write(f"Scheduler: {err}\n")
            else:
                self._sched_lbl.config(text="Failed: " + str(result.get("error") or result), fg=RED)
        except Exception as e:
            self._sched_lbl.config(text=f"Error: {e}", fg=RED)

    def _stop_schedule(self):
        """POST /api/scheduler/stop — mirrors dashboard scheduler API (no dedicated web button)."""

        def go():
            result = self._api("/api/scheduler/stop", {})

            def ui():
                if result.get("ok"):
                    self._sched_lbl.config(text="Schedule stopped", fg=T2)
                    self._log_write("Daily scheduler stopped.\n")
                else:
                    err = result.get("error", result)
                    self._sched_lbl.config(text=str(err)[:96], fg=RED)
                    self._log_write(f"Stop schedule: {err}\n")

            self.after(0, ui)

        threading.Thread(target=go, daemon=True).start()

    def _reload_groups_on_server(self):
        """POST /api/groups/load — same data path as dashboard “Load Groups Config”."""

        def go():
            result = self._api("/api/groups/load", {})

            def ui():
                err = result.get("error")
                if err:
                    self._reload_groups_lbl.config(text=str(err)[:120], fg=RED)
                    self._log_write(f"Reload groups failed: {err}\n")
                    return
                groups = result.get("groups")
                if not isinstance(groups, list):
                    self._reload_groups_lbl.config(text="Unexpected response", fg=RED)
                    return
                n = len(groups)
                self._reload_groups_lbl.config(text=f"Loaded {n} group(s)", fg=GREEN)
                self._log_write(
                    f"Server reloaded recordings/groups_config.json ({n} group(s)).\n"
                )

            self.after(0, ui)

        threading.Thread(target=go, daemon=True).start()

    def _collect_phone_serials(self) -> list[str]:
        """All ADB serials from state phones + groups (deduped, order preserved)."""
        out: list[str] = []
        seen: set[str] = set()
        for p in state.get("phones") or []:
            if isinstance(p, dict):
                s = str(p.get("serial") or "").strip()
                if s and s not in seen:
                    seen.add(s)
                    out.append(s)
        for g in state.get("groups") or []:
            if not isinstance(g, dict):
                continue
            phones = g.get("phones")
            if isinstance(phones, dict):
                for s in phones:
                    s = str(s).strip()
                    if s and s not in seen:
                        seen.add(s)
                        out.append(s)
        if not out:
            try:
                for d in list_adb_devices():
                    s = str(d.get("serial") or "").strip()
                    if s and s not in seen:
                        seen.add(s)
                        out.append(s)
            except Exception:
                pass
        return out

    def _launch_hide_emulator_all(self):
        serials = self._collect_phone_serials()
        if not serials:
            messagebox.showwarning(
                "No phones",
                "Boot phones first (Boot step), or connect MuMu with USB debugging ON.",
                parent=self.winfo_toplevel(),
            )
            return
        self._btn_fp_launch.config(state="disabled", text="Working…")
        self._fp_launch_lbl.config(text="", fg=T2)

        def go():
            try:
                _automation_on_sys_path()
                import mumu_farm_ops as farm

                self._log_write(
                    f"\nHiding emulator look on {len(serials)} phone(s)…\n"
                )
                summary = farm.apply_fingerprint_all(
                    serials,
                    log=lambda msg: self._log_write(msg + "\n"),
                    patch_vms=True,
                )
                n_leak = summary.get("leaks_total", 0)
                if summary.get("any_vm_patched"):
                    self._log_write(
                        "Stop each MuMu phone fully, then start it again (one time).\n"
                    )
                if n_leak == 0:
                    msg = f"OK — {len(serials)} phone(s) look clean."
                    fg = GREEN
                else:
                    msg = f"{n_leak} leak(s) — cold-boot phones and tap again."
                    fg = RED
            except Exception as e:
                msg = f"Error: {e}"
                fg = RED
                self._log_write(f"Fingerprint error: {e}\n")

            def ui():
                self._btn_fp_launch.config(
                    state="normal", text="Re-apply hide emulator on ALL phones"
                )
                self._fp_launch_lbl.config(text=msg, fg=fg)

            self.after(0, ui)

        threading.Thread(target=go, daemon=True).start()

    def _load_browse_proxy_mode_ui(self) -> None:
        try:
            automation_on_sys_path()
            import browse_proxy as bp

            mode = bp.browse_proxy_mode()
            bp.sync_browse_proxy_env_from_prefs()
            self._browse_mode_var.set(mode)
            self._browse_mode_lbl.config(
                text=bp.browse_proxy_mode_label(mode)[:72],
                fg=GREEN,
            )
        except Exception as exc:
            self._browse_mode_lbl.config(text=str(exc)[:72], fg=RED)

    def _save_browse_proxy_mode(self) -> None:
        mode = (self._browse_mode_var.get() or "scramble").strip().lower()
        if mode not in ("tor", "scramble", "direct", "upstream"):
            mode = "scramble"
        try:
            automation_on_sys_path()
            import browse_proxy as bp

            saved = bp.save_browse_prefs(browse_proxy_mode=mode)
            if not saved or saved.get("browse_proxy_mode") != mode:
                self._browse_mode_lbl.config(text="Browse mode was not saved", fg=RED)
                self._log_write("Browse mode was not saved — disk copy does not match.\n")
                return
            os.environ["PHARMFLOW_BROWSE_PROXY_MODE"] = mode
            self._browse_mode_lbl.config(
                text=f"Saved: {bp.browse_proxy_mode_label(mode)[:64]}",
                fg=GREEN,
            )
            self._log_write(f"Browse mode saved: {mode}\n")
        except Exception as exc:
            self._browse_mode_lbl.config(text=str(exc)[:72], fg=RED)
            self._log_write(f"Browse mode save failed: {exc}\n")

    def _tor_setup(self):
        if not self._ensure_server_ready_for_tor():
            return
        self._btn_tor.config(state="disabled")
        self._tor_lbl.config(text="Starting…", fg=STATUS_PROGRESS)

        def go():
            result = self._api("/api/proxy/setup", {})

            def ui():
                self._btn_tor.config(state="normal")
                err = result.get("error")
                if err:
                    self._tor_lbl.config(text=str(err)[:96], fg=RED)
                    self._log_write(f"Tor setup error: {err}\n")
                else:
                    self._tor_lbl.config(text="Started — read each phone line in the Live log", fg=STATUS_PROGRESS)
                    self._log_write(
                        "Tor setup started. Each phone line says whether a loopback exit was pinned.\n"
                    )

            self.after(0, ui)

        threading.Thread(target=go, daemon=True).start()

    def _ensure_server_ready_for_tor(self) -> bool:
        if self._dashboard_config_reachable():
            return True

        self._log_write("Tor setup needs the server; attempting to start it now…")
        self._start_server()
        time.sleep(0.5)
        if self._wait_dashboard_reachable(_dashboard_ready_timeout_sec()):
            return True

        msg = (
            "Tor setup needs the server running first.\n\n"
            "1. On Launch, tap Start server.\n"
            "2. Wait until it says Server running.\n"
            "3. Tap Set up Tor again."
        )
        self._tor_lbl.config(text="Start the server first", fg=RED)
        self._log_write(msg + "\n")
        messagebox.showerror(
            "Start the server first",
            msg,
            parent=self.winfo_toplevel(),
        )
        return False

    def _show_repin_result(self, ok: bool, n: int, msg: str) -> None:
        if not ok and n <= 0:
            self._tor_lbl.config(text="No phones connected — start phones on Connect", fg=STATUS_PROGRESS)
            self._log_write(f"{msg}\n")
            messagebox.showinfo(
                "Re-pin phone exits",
                "No phones are connected yet.\n\n"
                "1. Start your phones on the Connect step.\n"
                "2. Wait until they show in the list.\n"
                "3. Tap this button again.",
                parent=self.winfo_toplevel(),
            )
            return
        if not ok:
            self._tor_lbl.config(text=msg[:96], fg=RED)
            self._log_write(f"Re-pin failed: {msg}\n")
            messagebox.showerror("Re-pin phone exits", msg, parent=self.winfo_toplevel())
            return
        self._tor_lbl.config(text=msg[:96], fg=GREEN)
        self._log_write(msg + "\n")
        messagebox.showinfo("Re-pin phone exits", msg, parent=self.winfo_toplevel())

    def _tor_teardown(self):
        """Re-pin exits. Do not delete guest proxies or stop Tor."""

        def work():
            ok, n, msg = wiz_repin_phone_exits()
            self.after(0, lambda: self._show_repin_result(ok, n, msg))

        threading.Thread(target=work, daemon=True).start()

    def _fix_browsers_clear_proxy(self):
        """Re-pin live phones onto their own exits. Does not clear http_proxy."""

        def work():
            ok, n, msg = wiz_repin_phone_exits()
            self.after(0, lambda: self._show_repin_result(ok, n, msg))

        threading.Thread(target=work, daemon=True).start()

    def _true_up_load_json(self):
        path = filedialog.askopenfilename(
            parent=self.winfo_toplevel(),
            title="Load automation steps (JSON array)",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
            initialdir=_json_file_dialog_initialdir(),
        )
        if not path:
            return
        try:
            text = _read_json_text_file(Path(path))
        except OSError as exc:
            messagebox.showerror(
                "Load failed",
                str(exc),
                parent=self.winfo_toplevel(),
            )
            return
        self._true_up_json.delete("1.0", "end")
        self._true_up_json.insert("1.0", text)
        self._true_up_lbl.config(
            text=f"Loaded: {Path(path).name}", fg=GREEN
        )

    def _true_up_schedule(self):
        serial = self._true_up_serial.get().strip()
        raw = self._true_up_json.get("1.0", "end").strip()
        if not serial:
            messagebox.showwarning(
                "Phone ID required",
                "Enter the phone ID from Connect & boot (the connection line for that phone).",
                parent=self.winfo_toplevel(),
            )
            return
        try:
            steps = json.loads(raw) if raw else []
        except json.JSONDecodeError as e:
            messagebox.showerror(
                "Invalid JSON",
                str(e),
                parent=self.winfo_toplevel(),
            )
            return
        if not isinstance(steps, list):
            messagebox.showerror(
                "Invalid format",
                "JSON root must be an array of step objects.",
                parent=self.winfo_toplevel(),
            )
            return

        def go():
            result = self._api("/api/scheduler/true_up", {"serial": serial, "steps": steps})

            def ui():
                if result.get("ok"):
                    self._true_up_lbl.config(text="Saved ✓", fg=GREEN)
                    self._log_write(f"True-up: {serial} → {len(steps)} steps (next fires).\n")
                else:
                    err = result.get("error", result)
                    self._true_up_lbl.config(text=str(err)[:96], fg=RED)
                    self._log_write(f"True-up failed: {err}\n")

            self.after(0, ui)

        threading.Thread(target=go, daemon=True).start()


class SequenceGeneratorPage(PageBase):
    """Sequence builder: gate → website/app setup → step list → save under automation/recordings/sequences/."""

    _DISPLAY_PRESETS = [
        ("Large emulator phone (900×1600)", 900, 1600),
        ("Typical phone (390×844)", 390, 844),
        ("Full HD phone (1080×1920)", 1080, 1920),
        ("HD phone (720×1280)", 720, 1280),
        ("Custom size", None, None),
    ]

    _CAL_EXPECTED = ("the top-left corner", "the center", "the bottom-right corner")

    _INLINE_QUICK_EDIT_FIELDS = (
        ("Wait time (seconds)", "seconds"),
        ("Horizontal position", "x"),
        ("Vertical position", "y"),
        ("Website address", "url"),
        ("App package name", "package"),
        ("Typed text", "text"),
        ("Swipe length (milliseconds)", "ms"),
        ("Phone key code (advanced)", "key"),
        ("Tap variation (pixels)", "jitter"),
        ("Pause before tap (milliseconds)", "pre_wait_ms"),
        ("Retry count", "retries"),
        ("Swipe start — across", "x1"),
        ("Swipe start — down", "y1"),
        ("Swipe end — across", "x2"),
        ("Swipe end — down", "y2"),
    )

    _TEMPLATES = {
        "Open site and tap once": [
            {"type": "open_url"},
            {"type": "tap", "x": 359, "y": 912, "base_w": 900, "base_h": 1600, "retries": 5, "jitter": 6, "pre_wait_ms": 750, "age_verification": True, "checkpoint": "age_verification"},
            {"type": "wait", "seconds": 4.0},
        ],
        "Open, tap, then scroll": [
            {"type": "open_url"},
            {"type": "tap", "x": 359, "y": 912, "base_w": 900, "base_h": 1600, "retries": 5, "jitter": 6, "pre_wait_ms": 750, "age_verification": True, "checkpoint": "age_verification"},
            {"type": "wait", "seconds": 3.0},
            {"type": "swipe", "x1": 450, "y1": 1300, "x2": 460, "y2": 760, "ms": 900},
            {"type": "wait", "seconds": 2.0},
        ],
        "Open, tap ad, wait, scroll": [
            {"type": "open_url"},
            {"type": "tap", "x": 359, "y": 912, "base_w": 900, "base_h": 1600, "retries": 5, "jitter": 6, "pre_wait_ms": 750, "age_verification": True, "checkpoint": "age_verification"},
            {"type": "wait", "seconds": 4.0},
            {"type": "tap", "x": 650, "y": 760, "retries": 2, "jitter": 24, "pre_wait_ms": 300},
            {"type": "wait", "seconds": 12.0},
            {"type": "swipe", "x1": 450, "y1": 1300, "x2": 460, "y2": 700, "ms": 900},
        ],
        "Wait 96 seconds, then Back": [
            {"type": "open_url"},
            {"type": "tap", "x": 359, "y": 912, "base_w": 900, "base_h": 1600, "retries": 5, "jitter": 6, "pre_wait_ms": 750, "age_verification": True, "checkpoint": "age_verification"},
            {"type": "wait", "seconds": 4.0},
            {"type": "tap", "x": 450, "y": 705, "retries": 2, "jitter": 18, "pre_wait_ms": 250},
            {"type": "wait", "seconds": 96.0},
            {"type": "keyevent", "key": "4"},
        ],
    }

    _TOOLBOX = {
        "Navigation": {
            "Open website": lambda self: {"type": "open_url", "url": self._url_var.get().strip() or "https://getdabflow.app"},
            "Launch installed app": lambda self: {
                "type": "launch_app",
                "package": self._package_var.get().strip() or "com.example.app",
            },
            "Tap age confirmation (if the site asks)": lambda _self: {"type": "tap", "x": 359, "y": 912, "base_w": 900, "base_h": 1600, "retries": 5, "jitter": 6, "pre_wait_ms": 750, "age_verification": True, "checkpoint": "age_verification"},
            "Press back": lambda _self: {"type": "keyevent", "key": "4"},
            "Close browser": lambda _self: {"type": "close_app"},
        },
        "Timing": {
            "Wait 2 seconds": lambda _self: {"type": "wait", "seconds": 2.0},
            "Wait 8 seconds (stay on screen)": lambda _self: {"type": "wait", "seconds": 8.0},
        },
        "Gestures": {"Tap center": lambda self: self._tap_step(450, 800), "Swipe up": lambda self: self._swipe_step(450, 1300, 460, 700, 900)},
        "Identity": {"Switch profile": lambda _self: {"type": "rotate_identity"}, "Reset session completely": lambda _self: {"type": "full_reset"}},
        "Device": {"Type text": lambda _self: {"type": "type_text", "text": "hello"}, "Clear browser cookies": lambda _self: {"type": "clear_cookies"}},
        "Natural timing": {
            "Slow scroll up (about 2 seconds)": lambda self: self._human_slow_scroll_up(),
            "Short random pause": lambda self: self._human_micro_wait_gap(),
        },
    }

    _APP_TEMPLATES = {
        "Open app, then tap": [
            {"type": "launch_app"},
            {"type": "tap", "x": 359, "y": 912, "base_w": 900, "base_h": 1600, "retries": 5, "jitter": 6, "pre_wait_ms": 750, "age_verification": True, "checkpoint": "age_verification"},
            {"type": "wait", "seconds": 3.0},
        ],
        "Open app, then swipe": [
            {"type": "launch_app"},
            {"type": "wait", "seconds": 2.0},
            {"type": "swipe", "x1": 450, "y1": 1300, "x2": 460, "y2": 760, "ms": 900},
        ],
    }

    @classmethod
    def _inline_key_from_label(cls, label: str) -> str:
        s = (label or "").strip()
        for disp, key in cls._INLINE_QUICK_EDIT_FIELDS:
            if disp == s:
                return key
        return s

    @classmethod
    def _inline_label_for_key(cls, key: str) -> str:
        for disp, k in cls._INLINE_QUICK_EDIT_FIELDS:
            if k == key:
                return disp
        return key

    def _hint_scroll_to_steps(self) -> None:
        self._status_var.set("The step list is above this section. Scroll up to add or change steps.")
        self._status_lbl.config(fg=T2)

    def __init__(self, parent, *, footer_parent: tk.Misc | None = None):
        super().__init__(parent)
        self._steps: list[dict] = []
        self._tap_jitter_boost_next = 0
        self._window_ready = False
        self._record_armed = False
        self._drag_start: tuple[int, int, float] | None = None
        self._cal_mode = False
        self._cal_points_raw: list[tuple[float, float]] = []
        self._cal_profile = {"scale_x": 1.0, "scale_y": 1.0, "offset_x": 0.0, "offset_y": 0.0}
        self._advanced_visible = False
        self._target_kind: str | None = None
        self._human_timing_var = tk.BooleanVar(value=True)

        self._url_var = tk.StringVar(value="https://getdabflow.app")
        self._package_var = tk.StringVar(value="")
        self._display_var = tk.StringVar(value=self._DISPLAY_PRESETS[0][0])
        self._base_w_var = tk.IntVar(value=DEFAULT_SEQUENCE_BASE_W)
        self._base_h_var = tk.IntVar(value=DEFAULT_SEQUENCE_BASE_H)

        # Rely on the wizard shell canvas for vertical scroll — avoid expand=True here (clips inside create_window).

        self.header(
            "Sequence builder",
            "1. Pick website or app.\n2. Add steps.\n3. Save your file.",
            eyebrow="Generator",
        )
        self._status_var = tk.StringVar(
            value="Start here: tap Website or App.",
        )
        self._status_lbl = tk.Label(self, textvariable=self._status_var, font=FS, bg=BG, fg=T2, anchor="w")
        self._status_lbl.pack(fill="x", pady=(0, SP["sm"]))

        self._layer_gate = tk.Frame(self, bg=BG)
        self._layer_setup_web = tk.Frame(self, bg=BG)
        self._layer_setup_app = tk.Frame(self, bg=BG)
        self._layer_builder = tk.Frame(self, bg=BG)

        self._build_gate_screen(self._layer_gate)
        self._build_web_setup_screen(self._layer_setup_web)
        self._build_app_setup_screen(self._layer_setup_app)

        sum_card = instruction_card(self._layer_builder)
        sum_card.pack(fill="x", pady=(0, SP["md"]))
        tk.Label(sum_card, text="Your automation", font=FONT_SECTION, bg=BG2, fg=T1, anchor="w").pack(fill="x")
        self._builder_summary_var = tk.StringVar(value="")
        tk.Label(
            sum_card,
            textvariable=self._builder_summary_var,
            font=FS,
            bg=BG2,
            fg=T2,
            anchor="w",
            wraplength=820,
            justify="left",
        ).pack(fill="x", pady=(SP["xs"], SP["sm"]))
        tk.Button(
            sum_card,
            text="Change website / app choice",
            font=FONT_CAPTION,
            bg=BG2,
            fg=ACCENT,
            relief="flat",
            cursor="hand2",
            bd=0,
            highlightthickness=0,
            command=self._change_automation_target,
        ).pack(anchor="w")

        self._builder_inner = tk.Frame(self._layer_builder, bg=BG)
        self._builder_inner.pack(fill="x")

        self._build_advanced_tools_card(self._builder_inner)
        self._build_build_screen(self._builder_inner)
        self._build_save_screen(self._builder_inner)

        scroll_bottom_spacer(self._layer_builder).pack(fill="x")

        self._refresh_builder()
        self._load_calibration_profile()

        _footer_root = footer_parent if footer_parent is not None else self
        seq_ftr = tk.Frame(
            _footer_root,
            bg=FOOTER_BG,
            height=72,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        seq_ftr.pack_propagate(False)
        if footer_parent is None:
            seq_ftr.pack(side="bottom", fill="x")
        else:
            seq_ftr.pack(fill="x")
        sf_left = tk.Frame(seq_ftr, bg=FOOTER_BG)
        sf_left.pack(side="left", padx=SP["lg"], pady=SP["sm"])
        sf_right = tk.Frame(seq_ftr, bg=FOOTER_BG)
        sf_right.pack(side="right", padx=SP["lg"], pady=SP["sm"])
        self.btn(sf_left, "← Back", self._seq_footer_back, color=BG3, side="left", pady=8)
        self.btn(sf_left, "Cancel", self._seq_footer_cancel, color=BG3, side="left", pady=8)
        ok_footer = tk.Button(
            sf_right,
            text="OK",
            command=self._seq_footer_ok,
            font=("Segoe UI", 11, "bold"),
            bg=GREEN,
            fg=ON_ACCENT,
            relief="flat",
            cursor="hand2",
            padx=SP["lg"],
            pady=SP["sm"],
            bd=0,
            highlightthickness=0,
        )
        ok_footer.configure(activebackground=GREEN_ACTIVE, activeforeground=ON_ACCENT)
        ok_footer.pack(side="right")

        self.bind_all("<Control-s>", self._save_to_file)
        self.bind_all("<Control-S>", self._save_to_file)
        self._show_phase("gate")
        tk.Frame(self, bg=BG, height=32).pack(fill="x")

    def _seq_footer_back(self) -> None:
        ph = getattr(self, "_phase_name", "gate")
        if ph == "builder":
            if not self._window_ready:
                self._show_phase("gate")
                return
            kind = self._target_kind or "website"
            if kind == "app":
                self._show_phase("setup_app")
            else:
                self._show_phase("setup_web")
        elif ph in ("setup_web", "setup_app"):
            self._show_phase("gate")
        else:
            self._status_var.set("Use the wizard’s Back button below the step list to return to the previous setup step.")
            self._status_lbl.config(fg=T2)

    def _seq_footer_cancel(self) -> None:
        if self._steps and not messagebox.askyesno(
            "Clear sequence builder?",
            "Discard the current step list and reset this screen?",
            parent=self.winfo_toplevel(),
        ):
            return
        self._cancel_builder()

    def _seq_footer_ok(self) -> None:
        self._steps = self._normalize_with_context(self._steps)
        _lines, ok = self._validation_lines()
        if not ok:
            messagebox.showwarning(
                "Fix checks first",
                "Resolve the items under “Checks before saving” (scroll the content above if needed), then try OK again.",
                parent=self.winfo_toplevel(),
            )
            self._status_var.set("Cannot save yet — fix validation checks above.")
            self._status_lbl.config(fg=RED)
            return
        self._do_save(use_dialog=False)

    def _show_phase(self, phase: str) -> None:
        self._phase_name = phase
        for w in (
            self._layer_gate,
            self._layer_setup_web,
            self._layer_setup_app,
            self._layer_builder,
        ):
            w.pack_forget()
        if phase == "gate":
            self._layer_gate.pack(fill="x")
        elif phase == "setup_web":
            self._layer_setup_web.pack(fill="x")
        elif phase == "setup_app":
            self._layer_setup_app.pack(fill="x")
        elif phase == "builder":
            self._layer_builder.pack(fill="x")
            self._update_builder_summary()
            try:
                if not (self._name_var.get() or "").strip() or self._name_var.get() == "sequence_generated":
                    self._auto_name()
            except (AttributeError, tk.TclError):
                pass
            self._validate_and_refresh()

    def _build_gate_screen(self, host: tk.Frame) -> None:
        """Only choice: website automation vs app automation."""
        card = instruction_card(host, pad=SP["page"])
        card.pack(fill="x")
        tk.Label(
            card,
            text="What are we automating?",
            font=FONT_PAGE_TITLE,
            bg=BG2,
            fg=T1,
            anchor="w",
        ).pack(fill="x", pady=(0, SP["lg"]))
        btns = tk.Frame(card, bg=BG2)
        btns.pack(fill="x", pady=(0, SP["md"]))
        b_web = tk.Button(
            btns,
            text="Website (URL)",
            font=("Segoe UI", 14, "bold"),
            bg=GREEN,
            fg=ON_ACCENT,
            relief="flat",
            cursor="hand2",
            pady=18,
            bd=0,
            highlightthickness=0,
            command=self._gate_pick_website,
        )
        b_web.configure(activebackground=GREEN_ACTIVE, activeforeground=ON_ACCENT)
        b_web.pack(fill="x", pady=(0, SP["sm"]))
        b_app = tk.Button(
            btns,
            text="App (APK / package)",
            font=("Segoe UI", 14, "bold"),
            bg=ACCENT,
            fg=ON_ACCENT,
            relief="flat",
            cursor="hand2",
            pady=18,
            bd=0,
            highlightthickness=0,
            command=self._gate_pick_app,
        )
        style_primary_button(b_app)
        b_app.pack(fill="x")
        tk.Label(
            card,
            text=(
                "This step scrolls in the main wizard canvas (not a nested panel) so both choices stay visible. "
                "Use the scrollbar on the right if the buttons look cut off."
            ),
            font=FONT_CAPTION,
            bg=BG2,
            fg=T3,
            anchor="w",
            wraplength=820,
            justify="left",
        ).pack(fill="x", pady=(SP["md"], 0))

    def _gate_pick_website(self) -> None:
        self._target_kind = "website"
        self._status_var.set("Enter the website address and phone screen size, then tap Continue.")
        self._status_lbl.config(fg=T2)
        self._show_phase("setup_web")

    def _gate_pick_app(self) -> None:
        self._target_kind = "app"
        self._status_var.set(
            "Install the app on the phone first. Enter its package name (or pick an APK file), then Continue.",
        )
        self._status_lbl.config(fg=T2)
        self._show_phase("setup_app")

    def _find_aapt_exe(self) -> Path | None:
        roots: list[Path] = []
        raw_sdk = (state.get("sdk_path") or os.environ.get("ANDROID_HOME") or "").strip()
        if raw_sdk:
            roots.append(Path(raw_sdk).expanduser())
        roots.append(Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk")
        for sdk_root in roots:
            bt = sdk_root / "build-tools"
            if not bt.is_dir():
                continue
            try:
                versions = sorted(bt.iterdir(), key=lambda p: p.name, reverse=True)
            except OSError:
                continue
            for vdir in versions:
                exe = vdir / ("aapt.exe" if IS_WIN else "aapt")
                if exe.is_file():
                    return exe
        return None

    def _apk_try_package_from_apk(self, apk_path: Path) -> str | None:
        aapt = self._find_aapt_exe()
        if not aapt:
            return None
        try:
            r = subprocess.run(
                [str(aapt), "dump", "badging", str(apk_path)],
                capture_output=True,
                text=True,
                timeout=60,
                creationflags=_NO_WIN,
            )
        except Exception:
            return None
        if r.returncode != 0 or not (r.stdout or "").strip():
            return None
        m = re.search(r"package:\s*name='([^']+)'", r.stdout)
        return m.group(1) if m else None

    def _apk_browse(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.winfo_toplevel(),
            title="Pick an APK file",
            filetypes=[("Android package", "*.apk"), ("All files", "*.*")],
        )
        if not path:
            return
        pkg = self._apk_try_package_from_apk(Path(path))
        if pkg:
            self._package_var.set(pkg)
            self._status_var.set(f"Package name filled from APK ({Path(path).name}).")
            self._status_lbl.config(fg=GREEN)
        else:
            messagebox.showinfo(
                "Could not read package name",
                "Install Android SDK build-tools, or type the package name yourself "
                "(for example com.mycompany.myapp).",
                parent=self.winfo_toplevel(),
            )

    def _build_web_setup_screen(self, host: tk.Frame) -> None:
        card = instruction_card(host)
        card.pack(fill="x", pady=(0, SP["md"]))
        tk.Label(
            card,
            text="Website + phone screen size",
            font=FONT_SECTION,
            bg=BG2,
            fg=T1,
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            card,
            text=(
                "Paste the full website address. Pick a screen size that matches the phone or emulator "
                f"you used when planning taps (defaults {DEFAULT_SEQUENCE_BASE_W}×{DEFAULT_SEQUENCE_BASE_H})."
            ),
            font=FS,
            bg=BG2,
            fg=T2,
            anchor="w",
            wraplength=840,
            justify="left",
        ).pack(fill="x", pady=(SP["xs"], SP["sm"]))

        url_row = tk.Frame(card, bg=BG2)
        url_row.pack(fill="x", pady=(0, SP["xs"]))
        tk.Label(url_row, text="Website address", font=FS, bg=BG2, fg=T2, width=14, anchor="w").pack(side="left")
        tk.Entry(
            url_row,
            textvariable=self._url_var,
            font=FM,
            bg=BG,
            fg=T1,
            insertbackground=T1,
            relief="flat",
        ).pack(side="left", fill="x", expand=True, padx=(0, SP["sm"]))

        disp_row = tk.Frame(card, bg=BG2)
        disp_row.pack(fill="x", pady=(SP["xs"], SP["xs"]))
        tk.Label(disp_row, text="Phone screen size", font=FS, bg=BG2, fg=T2, width=14, anchor="w").pack(side="left")
        self._display_combo = ttk.Combobox(
            disp_row,
            textvariable=self._display_var,
            values=[p[0] for p in self._DISPLAY_PRESETS],
            state="readonly",
            width=30,
        )
        self._display_combo.pack(side="left", padx=(0, SP["sm"]))
        self._display_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_window_context_changed())
        tk.Label(disp_row, text="W", font=FS, bg=BG2, fg=T3).pack(side="left")
        tk.Entry(disp_row, textvariable=self._base_w_var, width=6, font=FM, bg=BG, fg=T1, relief="flat").pack(
            side="left", padx=(4, 8)
        )
        tk.Label(disp_row, text="H", font=FS, bg=BG2, fg=T3).pack(side="left")
        tk.Entry(disp_row, textvariable=self._base_h_var, width=6, font=FM, bg=BG, fg=T1, relief="flat").pack(
            side="left", padx=(4, 8)
        )

        self._viewport_var = tk.StringVar(value="Not confirmed yet.")
        tk.Label(card, textvariable=self._viewport_var, font=FONT_CAPTION, bg=BG2, fg=T3, anchor="w").pack(
            fill="x", pady=(SP["sm"], 0)
        )
        self._import_info_var = tk.StringVar(value="")
        tk.Label(
            card,
            textvariable=self._import_info_var,
            font=FONT_CAPTION,
            bg=BG2,
            fg=T3,
            anchor="w",
            wraplength=840,
            justify="left",
        ).pack(fill="x", pady=(SP["xs"], 0))

        nav = tk.Frame(card, bg=BG2)
        nav.pack(fill="x", pady=(SP["md"], 0))
        self.btn(nav, "Continue →", self._web_setup_continue, color=GREEN, side="right", pady=10)
        self.btn(nav, "Load sequence file…", self._load_sequence_file_from_gate, color=BG3, side="left", pady=10)
        self.btn(nav, "← Back", lambda: self._show_phase("gate"), color=BG3, side="left", pady=10)

        self._url_var.trace_add("write", lambda *_: self._on_window_context_changed())
        self._base_w_var.trace_add("write", lambda *_: self._on_window_context_changed())
        self._base_h_var.trace_add("write", lambda *_: self._on_window_context_changed())

    def _build_app_setup_screen(self, host: tk.Frame) -> None:
        card = instruction_card(host)
        card.pack(fill="x", pady=(0, SP["md"]))
        tk.Label(
            card,
            text="App package name",
            font=FONT_SECTION,
            bg=BG2,
            fg=T1,
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            card,
            text=(
                "The app must already be installed on the phone. "
                "The package name looks like com.company.app — or tap Browse APK and we will try to read it from the file."
            ),
            font=FS,
            bg=BG2,
            fg=T2,
            anchor="w",
            wraplength=840,
            justify="left",
        ).pack(fill="x", pady=(SP["xs"], SP["sm"]))
        row = tk.Frame(card, bg=BG2)
        row.pack(fill="x", pady=(0, SP["xs"]))
        tk.Label(row, text="Package name", font=FS, bg=BG2, fg=T2, width=14, anchor="w").pack(side="left")
        tk.Entry(
            row,
            textvariable=self._package_var,
            font=FM,
            bg=BG,
            fg=T1,
            insertbackground=T1,
            relief="flat",
        ).pack(side="left", fill="x", expand=True, padx=(0, SP["sm"]))
        self.btn(row, "Browse APK…", self._apk_browse, color=BG3, side="left", pady=6)

        nav = tk.Frame(card, bg=BG2)
        nav.pack(fill="x", pady=(SP["md"], 0))
        self.btn(nav, "Continue →", self._app_setup_continue, color=GREEN, side="right", pady=10)
        self.btn(nav, "Load sequence file…", self._load_sequence_file_from_gate, color=BG3, side="left", pady=10)
        self.btn(nav, "← Back", lambda: self._show_phase("gate"), color=BG3, side="left", pady=10)

    def _web_setup_continue(self) -> None:
        url = self._url_var.get().strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            messagebox.showerror(
                "Website address",
                "Enter a full address starting with http:// or https://",
                parent=self.winfo_toplevel(),
            )
            return
        for name, w, h in self._DISPLAY_PRESETS:
            if self._display_var.get() == name and w and h:
                self._base_w_var.set(w)
                self._base_h_var.set(h)
                break
        bw, bh = self._profile_dims()
        self._viewport_var.set(f"Using {url} • screen {bw}×{bh}")
        self._finish_enter_builder()

    def _app_setup_continue(self) -> None:
        pkg = self._package_var.get().strip()
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_.]*$", pkg):
            messagebox.showerror(
                "Package name",
                "Enter a valid Android package name, for example org.mozilla.firefox or mark.via.gp",
                parent=self.winfo_toplevel(),
            )
            return
        self._finish_enter_builder()

    def _finish_enter_builder(self) -> None:
        """Enter shared builder: seed first step, enable tools, show builder layer."""
        kind = self._target_kind or "website"
        bw, bh = self._profile_dims()
        if kind == "website":
            url = self._url_var.get().strip()
            self._tools_context_var.set(f"Website steps use {url} at screen {bw}×{bh}.")
            self._viewport_var.set(f"Using {url} • screen {bw}×{bh}")
        else:
            pkg = self._package_var.get().strip()
            self._tools_context_var.set(f"App steps launch {pkg} • taps use screen {bw}×{bh}.")
        self._set_tools_enabled(True)
        self._window_ready = True
        if not self._steps:
            if kind == "website":
                u = self._url_var.get().strip() or "https://getdabflow.app"
                self._steps.append({"type": "open_url", "url": u})
            else:
                self._steps.append({"type": "launch_app", "package": self._package_var.get().strip()})
            self._steps = self._normalize_with_context(self._steps)
            self._refresh_builder()
        self._status_var.set("Add steps below, then save your file.")
        self._status_lbl.config(fg=GREEN)
        self._show_phase("builder")

    def _update_builder_summary(self) -> None:
        bw, bh = self._profile_dims()
        if self._target_kind == "app":
            self._builder_summary_var.set(
                f"App: {self._package_var.get().strip() or '(not set yet)'} — taps use screen {bw}×{bh}",
            )
        else:
            self._builder_summary_var.set(
                f"Website: {self._url_var.get().strip() or '(no address yet)'} — taps use screen {bw}×{bh}",
            )
        self._sync_template_combo()

    def _change_automation_target(self) -> None:
        if not messagebox.askyesno(
            "Change choice?",
            "Go back and choose website or app? Your step list stays — you can still edit or clear it.",
            parent=self.winfo_toplevel(),
        ):
            return
        self._show_phase("gate")

    def _load_sequence_file_from_gate(self) -> None:
        prev = len(self._steps)
        self._load_file()
        if len(self._steps) != prev or self._steps:
            has_launch = any(isinstance(s, dict) and s.get("type") == "launch_app" for s in self._steps)
            has_url = any(isinstance(s, dict) and s.get("type") == "open_url" for s in self._steps)
            if has_launch:
                self._target_kind = "app"
                for s in self._steps:
                    if isinstance(s, dict) and s.get("type") == "launch_app" and s.get("package"):
                        self._package_var.set(str(s["package"]))
                        break
            elif has_url:
                self._target_kind = "website"
            else:
                self._target_kind = "website"
            self._finish_enter_builder()

    def _build_advanced_tools_card(self, host: tk.Frame) -> None:
        """Collapsed advanced: templates depth, browser builder, calibration."""
        card = instruction_card(host)
        card.pack(fill="x", pady=(0, SP["md"]))
        self._advanced_toggle_btn = tk.Button(
            card,
            text="More options: layouts, browser recording, tap alignment",
            font=FONT_CAPTION,
            bg=BG2,
            fg=T3,
            relief="flat",
            cursor="hand2",
            bd=0,
            highlightthickness=0,
            padx=0,
            pady=4,
            anchor="w",
            command=self._toggle_advanced,
        )
        self._advanced_toggle_btn.pack(fill="x")
        self._advanced_panel = tk.Frame(
            card,
            bg=BG3,
            highlightthickness=1,
            highlightbackground=BORDER,
            padx=SP["md"],
            pady=SP["md"],
        )
        tk.Label(
            self._advanced_panel,
            text="Advanced — optional",
            font=FB,
            bg=BG3,
            fg=T1,
            anchor="w",
        ).pack(fill="x")
        tpl_row = tk.Frame(self._advanced_panel, bg=BG3)
        tpl_row.pack(fill="x", pady=(0, SP["sm"]))
        tk.Label(tpl_row, text="Preset template", font=FS, bg=BG3, fg=T2).pack(side="left")
        self._template_var = tk.StringVar(value=list(self._TEMPLATES.keys())[0])
        self._template_combo = ttk.Combobox(
            tpl_row,
            textvariable=self._template_var,
            values=list(self._TEMPLATES.keys()),
            state="readonly",
            width=26,
        )
        self._template_combo.pack(side="left", padx=(8, 8))
        self._btn_apply_template = self.btn(tpl_row, "Use this layout", self._apply_template, color=ACCENT, side="left", pady=5)

        tk.Label(
            self._advanced_panel,
            text=(
                "Website automation only: open your page in a desktop browser window and tap there to build steps. "
                "Tap alignment fixes clicks if they land slightly off on the small preview."
            ),
            font=FS,
            bg=BG3,
            fg=T2,
            anchor="w",
            wraplength=820,
            justify="left",
        ).pack(fill="x", pady=(SP["xs"], SP["sm"]))

        bb_row = tk.Frame(self._advanced_panel, bg=BG3)
        bb_row.pack(fill="x", pady=(0, SP["xs"]))
        tk.Label(bb_row, text="Record from desktop browser", font=FS, bg=BG3, fg=T2, width=22, anchor="w").pack(side="left")
        self.btn(bb_row, "Open", self._browser_builder_navigate, color=ACCENT, side="left", pady=4)
        self._bb_hint_var = tk.StringVar(value="")
        tk.Label(
            self._advanced_panel,
            textvariable=self._bb_hint_var,
            font=FONT_CAPTION,
            bg=BG3,
            fg=T3,
            anchor="w",
            wraplength=820,
            justify="left",
        ).pack(fill="x")
        self._refresh_bb_hint()

        cal_row = tk.Frame(self._advanced_panel, bg=BG3)
        cal_row.pack(fill="x", pady=(SP["sm"], 0))
        tk.Label(cal_row, text="Touch calibration", font=FS, bg=BG3, fg=T2, width=18, anchor="w").pack(side="left")
        self._calibration_var = tk.StringVar(value="Tap alignment: none saved yet (using defaults).")
        tk.Label(cal_row, textvariable=self._calibration_var, font=FONT_CAPTION, bg=BG3, fg=T3).pack(
            side="left", padx=(0, 8)
        )
        self.btn(cal_row, "Start calibration", self._start_calibration, color=BG4, side="right", pady=4)

        rec_hdr = tk.Frame(self._advanced_panel, bg=BG3)
        rec_hdr.pack(fill="x", pady=(SP["md"], SP["xs"]))
        tk.Label(rec_hdr, text="Small preview — record taps here", font=FB, bg=BG3, fg=T1, anchor="w").pack(side="left")
        self._rec_state_var = tk.StringVar(value="Recording: off")
        tk.Label(rec_hdr, textvariable=self._rec_state_var, font=FONT_CAPTION, bg=BG3, fg=T3).pack(side="left", padx=(8, 0))
        self._btn_clear_rec = self.btn(rec_hdr, "Clear", self._clear_recording, color=BG4, side="right", pady=3)
        self._btn_stop_rec = self.btn(rec_hdr, "Stop", self._stop_recording, color=RED, side="right", pady=3)
        self._btn_start_rec = self.btn(rec_hdr, "Start recording", self._start_recording, color=GREEN, side="right", pady=3)

        self._viewport_canvas = tk.Canvas(
            self._advanced_panel,
            width=360,
            height=180,
            bg=BG,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        self._viewport_canvas.pack(fill="x", pady=(SP["xs"], 0))
        self._viewport_canvas.create_text(
            180,
            16,
            text="Click or drag here to add taps and swipes",
            fill=T3,
            font=FONT_CAPTION,
        )
        self._viewport_canvas.bind("<ButtonPress-1>", self._capture_press)
        self._viewport_canvas.bind("<ButtonRelease-1>", self._capture_release)
        self._viewport_canvas.bind("<B1-Motion>", self._capture_drag)

    def _toggle_advanced(self) -> None:
        self._advanced_visible = not self._advanced_visible
        if self._advanced_visible:
            self._advanced_panel.pack(fill="x", pady=(SP["sm"], 0))
            self._advanced_toggle_btn.config(text="Hide extra options")
        else:
            self._advanced_panel.pack_forget()
            self._advanced_toggle_btn.config(
                text="More options: layouts, browser recording, tap alignment",
            )
        try:
            self.update_idletasks()
        except tk.TclError:
            pass
        if isinstance(self.master, tk.Canvas):
            canvas_set_scrollregion_from_bbox_all(self.master)

    def _calibration_path(self) -> Path:
        root = _pharmflow_tree_root()
        return root / "automation" / "recordings" / "sequence_generator_calibration.json"

    def _load_calibration_profile(self) -> None:
        p = self._calibration_path()
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            for k in ("scale_x", "scale_y", "offset_x", "offset_y"):
                self._cal_profile[k] = float(data.get(k, self._cal_profile[k]))
            self._calibration_var.set("Saved tap alignment loaded.")
        except Exception:
            self._calibration_var.set("Could not read saved tap alignment; using defaults.")

    def _save_calibration_profile(self) -> None:
        p = self._calibration_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self._cal_profile, indent=2), encoding="utf-8")

    def _build_build_screen(self, host: tk.Frame) -> None:
        """Mini-step 2 — add and order actions, optionally record from the in-app viewport."""
        self._tools_card = instruction_card(host)
        self._tools_card.pack(fill="x", pady=(0, SP["md"]))
        tk.Label(
            self._tools_card, text="Add the actions you want to run",
            font=FONT_SECTION, bg=BG2, fg=T1, anchor="w",
        ).pack(fill="x")
        self._tools_context_var = tk.StringVar(value="Finish website or app setup to edit steps.")
        tk.Label(
            self._tools_card, textvariable=self._tools_context_var,
            font=FS, bg=BG2, fg=T2, anchor="w", wraplength=840,
        ).pack(fill="x", pady=(SP["xs"], SP["sm"]))

        human_row = tk.Frame(self._tools_card, bg=BG2)
        human_row.pack(fill="x", pady=(0, SP["sm"]))
        tk.Checkbutton(
            human_row,
            text="Make pauses feel more natural (recommended)",
            variable=self._human_timing_var,
            font=FS,
            bg=BG2,
            fg=T2,
            selectcolor=BG,
            activebackground=BG2,
            activeforeground=T1,
        ).pack(side="left")

        top = tk.Frame(self._tools_card, bg=BG2); top.pack(fill="x", pady=(0, SP["sm"]))
        tk.Label(top, text="Category", font=FS, bg=BG2, fg=T2).pack(side="left", padx=(16, 0))
        self._tool_cat_var = tk.StringVar(value="Navigation")
        cat_combo = ttk.Combobox(
            top, textvariable=self._tool_cat_var,
            values=list(self._TOOLBOX.keys()), state="readonly", width=16,
        )
        cat_combo.pack(side="left", padx=(8, 8))
        cat_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_tool_names())
        self._tool_name_var = tk.StringVar(value="")
        self._tool_name_combo = ttk.Combobox(
            top, textvariable=self._tool_name_var, values=[], state="readonly", width=24,
        )
        self._tool_name_combo.pack(side="left")
        self._btn_add_tool = self.btn(top, "Add action", self._add_selected_tool, color=GREEN, side="left", pady=5)

        list_row = tk.Frame(self._tools_card, bg=BG2)
        list_row.pack(fill="x")
        steps_fr = tk.Frame(list_row, bg=BG2)
        steps_fr.pack(side="left", fill="both", expand=True)
        self._steps_lb = tk.Listbox(
            steps_fr, height=10, font=FM, bg=BG, fg=T1,
            selectbackground=ACCENT, selectforeground=ON_ACCENT,
        )
        steps_sb = themed_vertical_scrollbar(steps_fr, command=self._steps_lb.yview)
        self._steps_lb.configure(yscrollcommand=steps_sb.set)
        self._steps_lb.pack(side="left", fill="both", expand=True)
        steps_sb.pack(side="right", fill="y")
        self._steps_lb.bind("<<ListboxSelect>>", lambda _e: self._load_inline_editor())
        btn_col = tk.Frame(list_row, bg=BG2); btn_col.pack(side="left", fill="y", padx=(SP["sm"], 0))
        self._btn_up = self.btn(btn_col, "Up", self._move_up, color=BG3, side="top", pady=4)
        self._btn_down = self.btn(btn_col, "Down", self._move_down, color=BG3, side="top", pady=4)
        self._btn_dup = self.btn(btn_col, "Duplicate", self._duplicate_step, color=BG3, side="top", pady=4)
        self._btn_del = self.btn(btn_col, "Delete", self._delete_step, color=RED, side="top", pady=4)

        edit = tk.Frame(self._tools_card, bg=BG2); edit.pack(fill="x", pady=(SP["sm"], 0))
        tk.Label(edit, text="Quick edit", font=FS, bg=BG2, fg=T2, width=12, anchor="w").pack(side="left")
        _iq_labels = [pair[0] for pair in self._INLINE_QUICK_EDIT_FIELDS]
        self._inline_key_var = tk.StringVar(value=_iq_labels[0])
        self._inline_val_var = tk.StringVar(value="")
        self._inline_key_combo = ttk.Combobox(
            edit, textvariable=self._inline_key_var,
            values=_iq_labels,
            state="readonly", width=28,
        )
        self._inline_key_combo.pack(side="left", padx=(0, 8))
        self._inline_key_combo.bind("<<ComboboxSelected>>", lambda _e: self._load_inline_editor())
        tk.Entry(
            edit, textvariable=self._inline_val_var,
            font=FM, bg=BG, fg=T1, relief="flat", width=24,
        ).pack(side="left", padx=(0, 8))
        self._btn_inline = self.btn(edit, "Apply change", self._apply_inline_edit, color=ACCENT, side="left", pady=5)

        strip = tk.Frame(self._tools_card, bg=BG2)
        strip.pack(fill="x", pady=(SP["md"], 0))
        tk.Label(strip, text="Add step:", font=FS, bg=BG2, fg=T2).pack(side="left", padx=(0, SP["sm"]))
        self.btn(strip, "Wait", self._quick_add_wait, color=GREEN, side="left", pady=6)
        self.btn(strip, "Tap", self._quick_add_tap, color=GREEN, side="left", pady=6)
        self.btn(strip, "Swipe", self._quick_add_swipe, color=GREEN, side="left", pady=6)
        self.btn(strip, "Back", self._quick_add_back, color=GREEN, side="left", pady=6)
        self.btn(strip, "Key", self._quick_add_key, color=GREEN, side="left", pady=6)

        self._save_status_var = tk.StringVar(value="No steps yet — use Add step or Advanced templates.")
        tk.Label(
            self._tools_card, textvariable=self._save_status_var,
            font=FONT_CAPTION, bg=BG2, fg=T3, anchor="w", wraplength=840,
        ).pack(fill="x", pady=(SP["xs"], 0))
        self._refresh_tool_names()
        self._set_tools_enabled(False)

    def _build_save_screen(self, host: tk.Frame) -> None:
        """Mini-step 3 — review, run a quick test, then save."""
        head = instruction_card(host)
        head.pack(fill="x", pady=(0, SP["md"]))
        tk.Label(
            head, text="Save your sequence file",
            font=FONT_SECTION, bg=BG2, fg=T1, anchor="w",
        ).pack(fill="x")
        tk.Label(
            head,
            text=(
                "By default, files save under automation/recordings/sequences/. "
                "Use Save As to choose another folder. Run Test checks your steps without running them on a phone."
            ),
            font=FS, bg=BG2, fg=T2, anchor="w", wraplength=840, justify="left",
        ).pack(fill="x", pady=(SP["xs"], SP["sm"]))

        name_row = tk.Frame(head, bg=BG2); name_row.pack(fill="x")
        tk.Label(name_row, text="File name", font=FS, bg=BG2, fg=T2, width=14, anchor="w").pack(side="left")
        self._name_var = tk.StringVar(value="sequence_generated")
        tk.Entry(
            name_row, textvariable=self._name_var,
            font=FM, bg=BG, fg=T1, insertbackground=T1, relief="flat",
        ).pack(side="left", fill="x", expand=True, padx=(0, SP["sm"]))
        self.btn(name_row, "Auto-name", self._auto_name_button, color=BG3, side="left", pady=4)

        primary = tk.Frame(head, bg=BG2); primary.pack(fill="x", pady=(SP["md"], 0))
        self.btn(primary, "Save sequence", self._save_to_file, color=GREEN, side="left", pady=8)
        self.btn(primary, "Save As…", self._save_as, color=BG3, side="left", pady=8)
        self.btn(primary, "Run Test", self._run_test, color=ACCENT, side="left", pady=8)
        self.btn(primary, "Add to Schedule", self._add_to_schedule, color=PURPLE, side="left", pady=8)

        nav = tk.Frame(head, bg=BG2); nav.pack(fill="x", pady=(SP["sm"], 0))
        self.btn(nav, "Where are my steps?", self._hint_scroll_to_steps, color=BG3, side="left", pady=6)
        self.btn(nav, "Cancel / clear", self._cancel_builder, color=BG3, side="left", pady=6)

        self._save_status_lbl = tk.Label(
            head, textvariable=self._save_status_var,
            font=FB, bg=BG2, fg=T1, anchor="w", wraplength=840, justify="left",
        )
        self._save_status_lbl.pack(fill="x", pady=(SP["md"], 0))

        v_card = instruction_card(host); v_card.pack(fill="x", pady=(0, SP["md"]))
        tk.Label(
            v_card, text="Checks before saving",
            font=FONT_SECTION, bg=BG2, fg=T1, anchor="w",
        ).pack(fill="x")
        self._validation_var = tk.StringVar(value="No steps yet.")
        tk.Label(
            v_card, textvariable=self._validation_var,
            font=FS, bg=BG2, fg=T2, anchor="w", justify="left", wraplength=840,
        ).pack(fill="x", pady=(SP["xs"], 0))

        log_card = instruction_card(host); log_card.pack(fill="x")
        tk.Label(log_card, text="Test results", font=FB, bg=BG2, fg=T1, anchor="w").pack(fill="x", pady=(0, SP["xs"]))
        run_log_fr = tk.Frame(log_card, bg=BG2)
        run_log_fr.pack(fill="x")
        self._run_log = tk.Text(run_log_fr, height=6, font=FM, bg=BG, fg=T1, relief="flat", wrap="word")
        _attach_readonly_log_text(self._run_log)
        run_sb = themed_vertical_scrollbar(run_log_fr, command=self._run_log.yview)
        self._run_log.configure(yscrollcommand=run_sb.set)
        self._run_log.pack(side="left", fill="both", expand=True)
        run_sb.pack(side="right", fill="y")

    def _auto_name_button(self) -> None:
        self._auto_name()
        self._save_status_var.set(f"File name set to “{self._name_var.get()}”.")

    def _set_tools_enabled(self, enabled: bool) -> None:
        state_txt = "normal" if enabled else "disabled"
        for btn in (self._btn_apply_template, self._btn_add_tool, self._btn_up, self._btn_down, self._btn_dup, self._btn_del, self._btn_inline):
            btn.config(state=state_txt)
        self._steps_lb.config(state=state_txt)
        self._btn_start_rec.config(state=state_txt)
        self._btn_clear_rec.config(state=state_txt)
        self._window_ready = enabled
        if enabled:
            self._status_lbl.config(fg=GREEN)
        else:
            self._status_lbl.config(fg=T2)

    def _refresh_tool_names(self) -> None:
        cat = self._tool_cat_var.get()
        if cat == "Natural timing":
            names = [
                "Slow scroll up (about 2 seconds)",
                "Short random pause",
                "More tap randomness (next tap)",
                "More tap randomness (selected step)",
            ]
        else:
            names = list(self._TOOLBOX.get(cat, {}).keys())
        self._tool_name_combo.configure(values=names)
        if names:
            self._tool_name_var.set(names[0])

    def _profile_dims(self) -> tuple[int, int]:
        try: return max(1, int(self._base_w_var.get())), max(1, int(self._base_h_var.get()))
        except (TypeError, ValueError, tk.TclError): return DEFAULT_SEQUENCE_BASE_W, DEFAULT_SEQUENCE_BASE_H

    def _tap_step(self, x: int, y: int) -> dict:
        bw, bh = self._profile_dims()
        boost = int(getattr(self, "_tap_jitter_boost_next", 0))
        self._tap_jitter_boost_next = 0
        human = bool(self._human_timing_var.get())
        if human:
            j = 20 + boost
            pre = random.randint(150, 380)
        else:
            j = max(4, 8 + boost // 3)
            pre = 0
        return {"type": "tap", "x": x, "y": y, "base_w": bw, "base_h": bh, "retries": 2, "jitter": j, "pre_wait_ms": pre}

    def _quick_add_wait(self) -> None:
        if self._human_timing_var.get():
            sec = round(random.uniform(2.4, 3.9), 2)
        else:
            sec = 3.0
        self._steps.append({"type": "wait", "seconds": sec})
        self._steps = self._normalize_with_context(self._steps)
        self._refresh_builder(select_last=True)

    def _quick_add_tap(self) -> None:
        bw, bh = self._profile_dims()
        self._steps.append(self._tap_step(max(1, bw // 2), max(1, int(bh * 0.55))))
        self._steps = self._normalize_with_context(self._steps)
        self._refresh_builder(select_last=True)

    def _quick_add_swipe(self) -> None:
        bw, bh = self._profile_dims()
        ms = 900
        if self._human_timing_var.get():
            ms = int(max(1, random.gauss(900, 85)))
        self._steps.append(
            self._swipe_step(max(1, bw // 2), int(bh * 0.78), max(1, bw // 2) + 12, int(bh * 0.32), ms),
        )
        self._steps = self._normalize_with_context(self._steps)
        self._refresh_builder(select_last=True)

    def _quick_add_back(self) -> None:
        self._steps.append({"type": "keyevent", "key": "BACK"})
        self._steps = self._normalize_with_context(self._steps)
        self._refresh_builder(select_last=True)

    def _quick_add_key(self) -> None:
        self._steps.append({"type": "keyevent", "key": "ENTER"})
        self._steps = self._normalize_with_context(self._steps)
        self._refresh_builder(select_last=True)

    def _human_slow_scroll_up(self) -> dict:
        """Long-duration swipe for slow, human-like scrolling (baseline coords)."""
        return self._swipe_step(450, 1260, 456, 660, 2100)

    def _human_micro_wait_gap(self) -> dict:
        """Short pause in the same band as ``human_variation.step_gap_seconds`` defaults."""
        lo, hi = 0.28, 0.52
        return {"type": "wait", "seconds": round(random.uniform(lo, hi), 2)}

    def _human_arm_jitter_next_tap(self) -> None:
        self._tap_jitter_boost_next = int(getattr(self, "_tap_jitter_boost_next", 0)) + 14
        self._save_status_var.set(
            f"The next tap will use extra randomness ({self._tap_jitter_boost_next} pixels). "
            "Record in the preview, add an action, or use Record from desktop browser."
        )

    def _human_boost_selected_tap_jitter(self) -> None:
        idx = self._selected_index()
        if idx is None:
            self._save_status_var.set("Select a tap step first.")
            return
        step = self._steps[idx]
        if step.get("type") != "tap":
            self._save_status_var.set("That step is not a tap — pick a tap in the list.")
            return
        j = int(step.get("jitter", 20))
        step["jitter"] = j + 12
        self._steps = self._normalize_with_context(self._steps)
        self._refresh_builder(select_index=idx)
        self._save_status_var.set(f"Tap randomness is now {step['jitter']} pixels.")

    def _swipe_step(self, x1: int, y1: int, x2: int, y2: int, ms: int) -> dict:
        bw, bh = self._profile_dims()
        dur = ms
        if self._human_timing_var.get():
            dur = int(max(1, random.gauss(ms, ms * 0.08)))
        return {"type": "swipe", "x1": x1, "y1": y1, "x2": x2, "y2": y2, "ms": dur, "base_w": bw, "base_h": bh}

    def _normalize_with_context(self, steps: list[dict]) -> list[dict]:
        bw, bh = self._profile_dims(); out = _normalize_sequence_steps(list(steps))
        for step in out:
            if isinstance(step, dict) and step.get("type") in ("tap", "swipe"):
                step["base_w"] = int(step.get("base_w", bw) or bw); step["base_h"] = int(step.get("base_h", bh) or bh)
        return out

    def _viewport_to_baseline(self, vx: float, vy: float) -> tuple[int, int]:
        bw, bh = self._profile_dims()
        c_w = max(1, int(self._viewport_canvas.winfo_width())); c_h = max(1, int(self._viewport_canvas.winfo_height()))
        raw_x = max(0.0, min(1.0, vx / c_w)) * bw
        raw_y = max(0.0, min(1.0, vy / c_h)) * bh
        x = raw_x * self._cal_profile["scale_x"] + self._cal_profile["offset_x"]
        y = raw_y * self._cal_profile["scale_y"] + self._cal_profile["offset_y"]
        return int(max(0, min(bw, round(x)))), int(max(0, min(bh, round(y))))

    def _load_window(self) -> None:
        url = self._url_var.get().strip()
        if not url or not (url.startswith("http://") or url.startswith("https://")):
            self._status_var.set("Enter a website address that starts with http:// or https://."); self._status_lbl.config(fg=RED); return
        for name, w, h in self._DISPLAY_PRESETS:
            if self._display_var.get() == name and w and h:
                self._base_w_var.set(w); self._base_h_var.set(h); break
        bw, bh = self._profile_dims()
        self._viewport_var.set(f"Using {url} • screen {bw}×{bh}")
        self._tools_context_var.set(f"Steps use this website at screen size {bw}×{bh}.")
        self._set_tools_enabled(True)
        self._validate_and_refresh()

    def _on_window_context_changed(self) -> None:
        if self._window_ready and self._steps:
            self._status_var.set("Website or screen size changed — review your steps before saving.")
            self._status_lbl.config(fg=WARNING)

    def _start_recording(self) -> None:
        if not self._window_ready:
            self._status_var.set("Finish setup above first, then tap Start recording."); self._status_lbl.config(fg=RED); return
        self._record_armed = True
        self._rec_state_var.set("Ready — click or drag on the preview")
        self._viewport_canvas.config(cursor="crosshair")
        self._status_var.set("Recording: click once for a tap, drag for a swipe."); self._status_lbl.config(fg=GREEN)

    def _stop_recording(self) -> None:
        self._record_armed = False; self._drag_start = None
        self._rec_state_var.set("Recording: off")
        self._viewport_canvas.config(cursor="arrow")

    def _clear_recording(self) -> None:
        self._steps.clear(); self._viewport_canvas.delete("capture"); self._refresh_builder()
        self._status_var.set("Recorded steps cleared."); self._status_lbl.config(fg=T2)

    def _start_calibration(self) -> None:
        self._cal_mode = True; self._cal_points_raw.clear()
        self._calibration_var.set(f"Tap {self._CAL_EXPECTED[0]} on the small preview.")
        self._status_var.set("Tap alignment: follow the prompts on the preview."); self._status_lbl.config(fg=STATUS_PROGRESS)

    def _capture_press(self, event) -> None:
        if self._cal_mode:
            bx, by = self._viewport_to_baseline(event.x, event.y)
            self._cal_points_raw.append((bx, by))
            n = len(self._cal_points_raw)
            self._viewport_canvas.create_oval(event.x - 4, event.y - 4, event.x + 4, event.y + 4, outline=GREEN, fill=GREEN, tags=("capture",))
            if n < 3:
                self._calibration_var.set(f"Tap {self._CAL_EXPECTED[n]} on the small preview.")
            else:
                self._finish_calibration()
            return
        if not self._record_armed:
            return
        bx, by = self._viewport_to_baseline(event.x, event.y)
        self._drag_start = (bx, by, time.time())
        self._viewport_canvas.delete("dragline")
        self._viewport_canvas.create_line(event.x, event.y, event.x, event.y, fill=ACCENT, width=2, tags=("dragline", "capture"))

    def _capture_drag(self, event) -> None:
        if not self._record_armed or not self._drag_start:
            return
        self._viewport_canvas.coords("dragline", event.x, event.y, event.x + 1, event.y + 1)

    def _capture_release(self, event) -> None:
        if not self._record_armed or not self._drag_start:
            return
        sx, sy, started = self._drag_start
        ex, ey = self._viewport_to_baseline(event.x, event.y)
        dur_ms = max(80, int((time.time() - started) * 1000))
        if abs(ex - sx) + abs(ey - sy) < 24:
            self._steps.append(self._tap_step(ex, ey))
            self._save_status_var.set(f"Recorded tap at ({ex},{ey}).")
        else:
            self._steps.append(self._swipe_step(sx, sy, ex, ey, dur_ms))
            self._save_status_var.set(f"Recorded swipe ({sx},{sy}) -> ({ex},{ey}) in {dur_ms}ms.")
        self._drag_start = None
        self._steps = self._normalize_with_context(self._steps)
        self._refresh_builder(select_last=True)

    def _finish_calibration(self) -> None:
        self._cal_mode = False
        bw, bh = self._profile_dims()
        p1, p2, p3 = self._cal_points_raw
        e1 = (0.1 * bw, 0.1 * bh); e3 = (0.9 * bw, 0.9 * bh)
        dx = max(1.0, p3[0] - p1[0]); dy = max(1.0, p3[1] - p1[1])
        sx = (e3[0] - e1[0]) / dx; sy = (e3[1] - e1[1]) / dy
        ox = e1[0] - p1[0] * sx; oy = e1[1] - p1[1] * sy
        self._cal_profile = {"scale_x": sx, "scale_y": sy, "offset_x": ox, "offset_y": oy}
        try:
            self._save_calibration_profile()
            self._calibration_var.set("Tap alignment saved — your clicks should match the phone better.")
            self._status_var.set("Tap alignment saved."); self._status_lbl.config(fg=GREEN)
        except OSError as exc:
            self._calibration_var.set(f"Could not save tap alignment: {exc}")

    def _apply_template(self) -> None:
        kind = self._target_kind or "website"
        pool = self._APP_TEMPLATES if kind == "app" else self._TEMPLATES
        base = pool.get(self._template_var.get(), [])
        steps: list[dict] = []
        for step in base:
            s = copy.deepcopy(step)
            if s.get("type") == "open_url":
                s["url"] = self._url_var.get().strip() or "https://getdabflow.app"
            if s.get("type") == "launch_app":
                s["package"] = self._package_var.get().strip() or "com.example.app"
            if s.get("type") == "tap":
                marker = bool(s.get("age_verification") or s.get("age_gate"))
                s = self._tap_step(int(s.get("x", 450)), int(s.get("y", 800)))
                if marker:
                    s["age_verification"] = True
            if s.get("type") == "swipe":
                s = self._swipe_step(
                    int(s.get("x1", 450)),
                    int(s.get("y1", 1300)),
                    int(s.get("x2", 460)),
                    int(s.get("y2", 700)),
                    int(s.get("ms", 900)),
                )
            steps.append(s)
        self._steps = self._normalize_with_context(steps)
        self._refresh_builder()

    def _sync_template_combo(self) -> None:
        combo = getattr(self, "_template_combo", None)
        if combo is None:
            return
        kind = self._target_kind or "website"
        names = list((self._APP_TEMPLATES if kind == "app" else self._TEMPLATES).keys())
        combo.configure(values=names)
        if names:
            self._template_var.set(names[0])

    def _add_selected_tool(self) -> None:
        cat = self._tool_cat_var.get()
        name = self._tool_name_var.get()
        if cat == "Natural timing" and name == "More tap randomness (next tap)":
            self._human_arm_jitter_next_tap()
            self._validate_and_refresh()
            return
        if cat == "Natural timing" and name == "More tap randomness (selected step)":
            self._human_boost_selected_tap_jitter()
            self._validate_and_refresh()
            return
        fn = self._TOOLBOX.get(cat, {}).get(name)
        if not fn:
            return
        self._steps.append(fn(self))
        self._steps = self._normalize_with_context(self._steps)
        self._refresh_builder(select_last=True)

    def _selected_index(self) -> int | None:
        sel = self._steps_lb.curselection(); return int(sel[0]) if sel else None

    def _move_up(self): self._move_selected(-1)
    def _move_down(self): self._move_selected(1)

    def _move_selected(self, direction: int) -> None:
        idx = self._selected_index(); 
        if idx is None: return
        dst = idx + direction
        if dst < 0 or dst >= len(self._steps): return
        self._steps[idx], self._steps[dst] = self._steps[dst], self._steps[idx]
        self._refresh_builder(select_index=dst)

    def _duplicate_step(self) -> None:
        idx = self._selected_index()
        if idx is None: return
        self._steps.insert(idx + 1, copy.deepcopy(self._steps[idx])); self._refresh_builder(select_index=idx + 1)

    def _delete_step(self) -> None:
        idx = self._selected_index()
        if idx is None: return
        self._steps.pop(idx); self._refresh_builder(select_index=min(idx, len(self._steps) - 1))

    def _load_inline_editor(self) -> None:
        idx = self._selected_index()
        if idx is None: return
        key = self._inline_key_from_label(self._inline_key_var.get())
        self._inline_val_var.set(str(self._steps[idx].get(key, "")))

    def _apply_inline_edit(self) -> None:
        idx = self._selected_index()
        if idx is None: return
        key = self._inline_key_from_label(self._inline_key_var.get().strip())
        raw = self._inline_val_var.get().strip()
        step = self._steps[idx]
        if raw == "":
            step.pop(key, None)
        else:
            try:
                if key in ("seconds", "pre_wait_ms"): step[key] = float(raw)
                elif key in ("x", "y", "x1", "y1", "x2", "y2", "ms", "retries", "jitter"): step[key] = int(float(raw))
                else: step[key] = raw
            except ValueError:
                self._save_status_var.set(f"Invalid value for “{self._inline_label_for_key(key)}”.")
        self._steps = self._normalize_with_context(self._steps); self._refresh_builder(select_index=idx)

    def _render_step_label(self, idx: int, step: dict) -> str:
        t = step.get("type", "unknown")
        if t == "open_url":
            return f"{idx + 1}. Open website — {step.get('url', '')}"
        if t == "launch_app":
            return f"{idx + 1}. Open app — {step.get('package', '')}"
        if t == "tap":
            return f"{idx + 1}. Tap — position ({step.get('x')},{step.get('y')})"
        if t == "wait":
            return f"{idx + 1}. Wait — {step.get('seconds', 0)} seconds"
        if t == "swipe":
            return (
                f"{idx + 1}. Swipe — from ({step.get('x1')},{step.get('y1')}) to "
                f"({step.get('x2')},{step.get('y2')}), {step.get('ms')} ms"
            )
        if t == "keyevent":
            return f"{idx + 1}. Phone key — code {step.get('key', '')}"
        if t == "rotate_identity":
            return f"{idx + 1}. Switch profile"
        if t == "full_reset":
            return f"{idx + 1}. Reset session completely"
        return f"{idx + 1}. {t}"

    def _refresh_builder(self, select_last: bool = False, select_index: int | None = None) -> None:
        self._steps_lb.delete(0, "end")
        for i, step in enumerate(self._steps): self._steps_lb.insert("end", self._render_step_label(i, step))
        if self._steps:
            idx = len(self._steps) - 1 if select_last else (select_index if select_index is not None else None)
            if idx is not None and idx >= 0:
                self._steps_lb.selection_set(idx); self._steps_lb.activate(idx)
        self._validate_and_refresh()

    def _validation_lines(self) -> tuple[list[str], bool]:
        lines: list[str] = []
        ok = True
        if not self._steps:
            return ["No steps yet — add actions, record in the preview, or load a file."], False
        bad = [
            i
            for i, s in enumerate(self._steps)
            if not isinstance(s, dict)
            or s.get("type") not in STEP_LABELS
            and s.get("type") not in ("full_reset", "clear_cookies")
        ]
        if bad:
            ok = False
            shown = ", ".join(str(i + 1) for i in bad)
            lines.append(f"Step types: problem at step number(s): {shown}.")
        else:
            lines.append("Step types: OK.")
        waits = [
            (i - 1, i)
            for i in range(1, len(self._steps))
            if self._steps[i - 1].get("type") == "wait" and self._steps[i].get("type") == "wait"
        ]
        if waits:
            ok = False
            lines.append("Do not place two waits in a row — put another action between them.")
        else:
            lines.append("Back-to-back waits: OK.")
        tail = [s.get("type") for s in self._steps[-3:]]
        if tail == ["rotate_identity", "wait", "full_reset"]:
            lines.append("Recommended ending: OK (switch profile → wait → full reset).")
        else:
            ok = False
            lines.append(
                "Recommended ending: finish with Switch profile, then Wait, then Reset session completely.",
            )
        bw, bh = self._profile_dims()
        missing = [
            i
            for i, s in enumerate(self._steps)
            if s.get("type") in ("tap", "swipe") and not (s.get("base_w") and s.get("base_h"))
        ]
        if missing:
            ok = False
            shown = ", ".join(str(i + 1) for i in missing)
            lines.append(f"Screen size on taps/swipes: missing on step number(s): {shown}.")
        else:
            lines.append(f"Screen size on taps/swipes: OK ({bw}×{bh}).")
        est = 0.0
        for s in self._steps:
            t = s.get("type")
            if t == "wait":
                est += float(s.get("seconds", 0))
            elif t == "swipe":
                est += max(0.1, float(s.get("ms", 600)) / 1000.0)
            elif t in ("open_url", "launch_app"):
                est += 2.0
            else:
                est += 0.5
        lines.append(f"Rough total time on phone: about {est:.1f} seconds.")
        return lines, ok

    def _set_run_log(self, text: str) -> None:
        self._run_log.configure(state="normal")
        self._run_log.delete("1.0", "end")
        self._run_log.insert("1.0", text)
        self._run_log.configure(state="disabled")

    def _run_test(self) -> None:
        self._steps = self._normalize_with_context(self._steps)
        lines, ok = self._validation_lines()
        warn: list[str] = []
        bw, bh = self._profile_dims()
        total = 0.0
        for i, step in enumerate(self._steps):
            t = step.get("type")
            if t == "open_url":
                u = str(step.get("url", "")).strip()
                if not (u.startswith("http://") or u.startswith("https://")):
                    warn.append(f"Step {i + 1}: add a full website address starting with http:// or https://.")
                total += 0.5
            elif t == "launch_app":
                pk = str(step.get("package", "")).strip()
                if not re.match(r"^[a-zA-Z][a-zA-Z0-9_.]*$", pk):
                    warn.append(f"Step {i + 1}: open-app step needs a valid app package name.")
                total += 2.0
            elif t == "tap":
                x = int(step.get("x", 0)); y = int(step.get("y", 0))
                if x < 0 or x > bw or y < 0 or y > bh:
                    warn.append(
                        f"Step {i + 1}: tap is outside the screen size you chose ({bw}×{bh}).",
                    )
                total += 0.5
            elif t == "swipe":
                for k in ("x1", "y1", "x2", "y2"):
                    v = int(step.get(k, 0)); hi = bw if "x" in k else bh
                    if v < 0 or v > hi:
                        warn.append(
                            f"Step {i + 1}: swipe goes outside the screen size you chose ({bw}×{bh}).",
                        )
                total += max(0.1, float(step.get("ms", 600)) / 1000.0)
            elif t == "wait":
                secs = float(step.get("seconds", 0))
                total += secs
                if secs > 120:
                    warn.append(f"Step {i + 1}: very long wait ({secs} seconds).")
            else:
                total += 0.5
        summary = [
            "Practice run finished (nothing was sent to a phone yet).",
            f"Steps in list: {len(self._steps)}",
            f"About how long on a phone: {total:.1f} seconds",
            f"Checks above: {'passed' if ok else 'need fixes'}",
        ]
        if warn:
            summary.append("Heads-up:")
            summary.extend(f"- {w}" for w in warn)
        else:
            summary.append("No timing or position warnings.")
        self._set_run_log("\n".join(summary))
        self._save_status_var.set("Run Test finished — read Test results below and adjust steps if needed.")

    def _validate_and_refresh(self) -> None:
        lines, ok = self._validation_lines()
        self._validation_var.set("\n".join(lines))
        self._save_status_var.set(
            "Ready to save." if ok else "Fix the items under Checks before saving.",
        )

    def _auto_name(self) -> None:
        bw, bh = self._profile_dims()
        slug = (self._url_var.get().strip().replace("https://", "").replace("http://", "").split("/")[0] or "site").replace(".", "_")
        self._name_var.set(f"sequence_generated_{slug}_{bw}x{bh}")

    def _target_path(self, use_dialog: bool) -> str:
        default_dir = _default_sequences_dir(); default_dir.mkdir(parents=True, exist_ok=True)
        init_name = self._name_var.get().strip() or "sequence_generated"
        if not init_name.endswith(".json"): init_name += ".json"
        if use_dialog:
            return filedialog.asksaveasfilename(parent=self.winfo_toplevel(), title="Save generated sequence", defaultextension=".json", filetypes=[("JSON sequence", "*.json"), ("All files", "*.*")], initialdir=str(default_dir), initialfile=init_name)
        return str(default_dir / init_name)

    def _save_to_file(self, event=None) -> None: self._do_save(use_dialog=False)
    def _save_as(self) -> None: self._do_save(use_dialog=True)

    def _do_save(self, use_dialog: bool) -> None:
        self._steps = self._normalize_with_context(self._steps)
        _lines, ok = self._validation_lines()
        if not ok:
            self._save_status_var.set("Cannot save yet — fix the checks listed above."); return
        path = self._target_path(use_dialog=use_dialog)
        if not path: return
        p = Path(path)
        if p.exists() and not messagebox.askyesno("Overwrite file?", f"File already exists:\n{p}\n\nOverwrite?", parent=self.winfo_toplevel()):
            self._save_status_var.set("Save cancelled — existing file kept."); return
        try:
            p.write_text(json.dumps(self._steps, indent=2), encoding="utf-8")
            self._save_status_var.set(f"Saved successfully: {p}")
            self._status_var.set(f"Saved to file: {p}"); self._status_lbl.config(fg=GREEN)
        except OSError as exc:
            self._save_status_var.set(f"Save failed: {exc}"); self._status_lbl.config(fg=RED)

    def _cancel_builder(self) -> None:
        self._steps = []
        self._stop_recording()
        self._set_run_log("")
        self._refresh_builder()
        self._status_var.set("Builder cleared. You can load a file or start again."); self._status_lbl.config(fg=T2)

    def _load_file(self) -> None:
        path = filedialog.askopenfilename(parent=self.winfo_toplevel(), title="Load sequence file", filetypes=[("JSON sequence", "*.json"), ("All files", "*.*")], initialdir=_json_file_dialog_initialdir())
        if not path: return
        try:
            data, seq_meta = _load_sequence_document_from_path(Path(path))
        except SequenceJsonLoadError as exc:
            self._status_var.set(f"Load failed: {exc}"); self._status_lbl.config(fg=RED); return
        self._steps = self._normalize_with_context(data)
        meta_suffix = ""
        if seq_meta and isinstance(seq_meta.get("label"), str) and seq_meta["label"].strip():
            meta_suffix = f"\nLabel: {seq_meta['label'].strip()}"
        detected_url = ""
        detected_pkg = ""
        for step in self._steps:
            if isinstance(step, dict) and step.get("type") == "open_url":
                detected_url = str(step.get("url", "")).strip()
                if detected_url:
                    break
        for step in self._steps:
            if isinstance(step, dict) and step.get("type") == "launch_app":
                detected_pkg = str(step.get("package", "")).strip()
                if detected_pkg:
                    break
        hinted = _step_baseline_hint(self._steps)
        if hinted:
            self._base_w_var.set(hinted[0]); self._base_h_var.set(hinted[1])
        if detected_pkg:
            self._target_kind = "app"
            self._package_var.set(detected_pkg)
            url_msg = "n/a (app sequence)"
        elif detected_url:
            self._target_kind = "website"
            self._url_var.set(detected_url); url_msg = detected_url
        else:
            self._target_kind = "website"
            url_msg = "none detected — choose Website or App above"
        self._set_tools_enabled(True)
        bw, bh = self._profile_dims()
        self._viewport_var.set(f"Loaded from file • screen {bw}×{bh}")
        self._import_info_var.set(
            f"File: {Path(path).name}\nSaved at: {path}\n"
            f"Website in file: {url_msg}\nApp package in file: {detected_pkg or '(none)'}\n"
            f"Screen size used for taps: {bw}×{bh}\nSteps loaded: {len(self._steps)}.{meta_suffix}"
        )
        self._status_var.set("File loaded — you can edit steps or save.")
        self._status_lbl.config(fg=GREEN if (detected_url or detected_pkg) else WARNING)
        self._refresh_builder()
        self._show_phase("builder")

    def _add_to_schedule(self) -> None:
        self._steps = self._normalize_with_context(self._steps)
        state["default_steps"] = list(self._steps)
        _apply_default_steps_to_template_phones()
        self._status_var.set("This sequence is now the default for scheduling.")
        self._status_lbl.config(fg=GREEN)
        messagebox.showinfo(
            "Added for scheduling",
            "This sequence is now the default plan used in Groups and the scheduler.\n\n"
            "Next: open Groups to pick phones and how many runs per day.",
            parent=self.winfo_toplevel(),
        )

    def _refresh_bb_hint(self) -> None:
        """Reflect pywebview availability in the inline hint shown next to the Open button."""
        try:
            import browser_builder_webview as bbw
        except Exception as exc:
            self._bb_hint_var.set(f"Desktop browser recording is not available: {exc}.")
            return
        if bbw.is_pywebview_available():
            self._bb_hint_var.set("Ready — tap Open to use a desktop browser window for recording.")
        else:
            self._bb_hint_var.set(
                f"Optional add-on for desktop browser recording: {bbw.PYWEBVIEW_INSTALL_CMD}"
            )

    def _browser_builder_navigate(self) -> None:
        """Open WebView2 (pywebview) or navigate; bridge pointer events into sequence steps."""
        if self._target_kind == "app":
            messagebox.showinfo(
                "Website flows only",
                "Desktop browser recording is only for website automation. "
                "For apps, record taps using the small preview or your phone.",
                parent=self.winfo_toplevel(),
            )
            return
        try:
            import browser_builder_webview as bbw
        except Exception as exc:
            self._bb_hint_var.set(f"Desktop browser recording is not available: {exc}.")
            messagebox.showerror(
                "Desktop browser recording unavailable",
                f"Could not load the helper used for desktop browser recording:\n\n{exc}",
                parent=self.winfo_toplevel(),
            )
            return

        raw_url = (self._url_var.get() or "").strip()
        ok_url, normalized_url = bbw.validate_url(raw_url)
        if not ok_url:
            self._status_var.set(
                "Enter a full website address with http:// or https:// (for example https://example.com).",
            )
            self._status_lbl.config(fg=RED)
            return

        if not bbw.is_pywebview_available():
            self._bb_hint_var.set(f"{bbw.PYWEBVIEW_INSTALL_CMD} — {bbw.PYWEBVIEW_DOCS_URL}")
            messagebox.showinfo(
                "Desktop browser recording",
                "Recording clicks in a separate desktop browser uses an optional add-on "
                "(Microsoft Edge WebView on Windows).\n\n"
                f"{bbw.PYWEBVIEW_INSTALL_CMD}\n\n"
                f"More help:\n{bbw.PYWEBVIEW_DOCS_URL}",
                parent=self.winfo_toplevel(),
            )
            # Without the add-on: open the URL in your normal browser; use the small preview or phone to record.
            try:
                webbrowser.open(normalized_url, new=1)
            except Exception:
                pass
            self._load_window()
            self._status_var.set(
                "Opened the page in your normal web browser. Use the small preview below or your phone to record taps.",
            )
            self._status_lbl.config(fg=WARNING)
            return

        for name, w, h in self._DISPLAY_PRESETS:
            if self._display_var.get() == name and w and h:
                self._base_w_var.set(w)
                self._base_h_var.set(h)
                break

        bw, bh = self._profile_dims()

        def tap_cb(x, y, vw, vh):
            try:
                self.after(
                    0,
                    lambda x=x, y=y, vw=vw, vh=vh: self._bb_apply_from_browser_tap(x, y, vw, vh),
                )
            except (RuntimeError, tk.TclError):
                pass  # Tk loop may already be torn down (window closed first)

        def swipe_cb(x1, y1, x2, y2, vw, vh, ms):
            try:
                self.after(
                    0,
                    lambda x1=x1, y1=y1, x2=x2, y2=y2, vw=vw, vh=vh, ms=ms: self._bb_apply_from_browser_swipe(
                        x1, y1, x2, y2, vw, vh, ms
                    ),
                )
            except (RuntimeError, tk.TclError):
                pass

        ok, err = bbw.launch_browser_builder(normalized_url, bw, bh, tap_cb, swipe_cb)
        if ok:
            self._bb_hint_var.set(
                f"Browser window {bw}×{bh} — tap or drag there to add steps to your list.",
            )
            self._viewport_var.set(f"Desktop browser • {normalized_url} • screen {bw}×{bh}")
            self._set_tools_enabled(True)
            self._tools_context_var.set(
                f"Steps match screen size {bw}×{bh} (same as width and height you set).",
            )
            self._status_var.set(
                "Desktop browser is open — click and drag there to add taps and swipes to your list.",
            )
            self._status_lbl.config(fg=GREEN)
            return

        if err == bbw.ERR_BUSY:
            messagebox.showwarning(
                "Browser window busy",
                "A recording browser window is already open or starting. "
                "Use that window, close it, or wait a moment, then try again.",
                parent=self.winfo_toplevel(),
            )
            self._status_var.set("Finish or close the other browser window first.")
            self._status_lbl.config(fg=WARNING)
        elif err == bbw.ERR_BADURL:
            self._status_var.set("That website address is not valid for desktop browser recording.")
            self._status_lbl.config(fg=RED)
        elif err == bbw.ERR_IMPORT:
            self._refresh_bb_hint()
            self._status_var.set("Install the optional add-on shown above to use desktop browser recording.")
            self._status_lbl.config(fg=WARNING)
        else:
            detail = bbw.last_error() or err or "unknown error"
            messagebox.showerror(
                "Could not open recording browser",
                "The desktop recording window could not start. "
                "Install Microsoft Edge WebView2 if prompted, then try again.\n\n"
                f"Details: {detail}",
                parent=self.winfo_toplevel(),
            )
            self._status_var.set("Desktop browser recording did not start — see the message above.")
            self._status_lbl.config(fg=RED)

    def _bb_apply_from_browser_tap(self, x, y, vw, vh) -> None:
        bw, bh = self._profile_dims()
        vw_f = max(1.0, float(vw))
        vh_f = max(1.0, float(vh))
        bx = int(max(0, min(bw, round(float(x) / vw_f * bw))))
        by = int(max(0, min(bh, round(float(y) / vh_f * bh))))
        self._steps.append(self._tap_step(bx, by))
        self._steps = self._normalize_with_context(self._steps)
        self._save_status_var.set(f"From desktop browser: added tap at ({bx},{by}) for your screen size.")
        self._refresh_builder(select_last=True)

    def _bb_apply_from_browser_swipe(self, x1, y1, x2, y2, vw, vh, ms) -> None:
        bw, bh = self._profile_dims()
        vw_f = max(1.0, float(vw))
        vh_f = max(1.0, float(vh))
        sx1 = int(max(0, min(bw, round(float(x1) / vw_f * bw))))
        sy1 = int(max(0, min(bh, round(float(y1) / vh_f * bh))))
        sx2 = int(max(0, min(bw, round(float(x2) / vw_f * bw))))
        sy2 = int(max(0, min(bh, round(float(y2) / vh_f * bh))))
        dur = int(max(80, min(8000, round(float(ms)))))
        self._steps.append(self._swipe_step(sx1, sy1, sx2, sy2, dur))
        self._steps = self._normalize_with_context(self._steps)
        self._save_status_var.set(
            f"From desktop browser: added swipe from ({sx1},{sy1}) to ({sx2},{sy2}).",
        )
        self._refresh_builder(select_last=True)


class WebpePage(PageBase):
    """Beginner-friendly sequencer EXE setup/debug workflow with log capture and sequence import."""

    def __init__(self, parent):
        super().__init__(parent)
        self.header(
            "webpe",
            "Set your external sequencer EXE, test it, run debug mode, and import output sequence files.",
            eyebrow="New applet",
        )
        self._debug_proc: subprocess.Popen[str] | None = None
        self._latest_log_path: Path | None = None
        self._log_dir = _pharmflow_tree_root() / "automation" / "logs" / "webpe"
        remembered_exe = (state.get("webpe_exe_path") or "").strip()
        remembered_out = (state.get("webpe_output_path") or "").strip()
        self._exe_var = tk.StringVar(value=remembered_exe or str(self._guess_default_exe()))
        self._health_var = tk.StringVar(value="Health: not tested yet")
        self._status_var = tk.StringVar(value="Ready. Start with 'Verify EXE'.")
        self._error_var = tk.StringVar(value="")
        self._output_var = tk.StringVar(value=remembered_out)
        self._contract_var = tk.StringVar(value="Contract: not checked yet")
        self._dirty = False
        self._download_busy = False
        self._download_webpe_btn: tk.Button | None = None
        self._download_progress_var = tk.StringVar(value="")
        self._guidance_var = tk.StringVar(
            value=(
                "Download official WebPE from GitHub (twoskoops707/webpe) with one click — it installs under "
                "%LOCALAPPDATA%\\PharmFlow\\webpe\\webpe.exe. Or set a path from another build (for example shine)."
            )
        )
        self._build_layout()

        scroll_bottom_spacer(self).pack(fill="x")

    def _guess_default_exe(self) -> Path:
        env = (os.environ.get("PHARMFLOW_SEQUENCER_EXE") or "").strip()
        if env:
            p = Path(env).expanduser()
            return p
        managed = _webpe_managed_exe_path()
        if managed.is_file():
            return managed
        roots = [_pharmflow_tree_root(), Path.home() / "source" / "repos", Path.home()]
        cands = [
            ("shine", "dist", "sequencer.exe"),
            ("shine", "bin", "sequencer.exe"),
            ("shine", "build", "sequencer.exe"),
            ("sequencer.exe",),
        ]
        for r in roots:
            for tup in cands:
                p = r.joinpath(*tup)
                if p.exists():
                    return p
        return _pharmflow_tree_root() / "automation" / "tools" / "sequencer.exe"

    def _build_layout(self) -> None:
        shell = tk.Frame(self, bg=BG)
        shell.pack(fill="both", expand=True)
        panes = tk.PanedWindow(shell, orient="horizontal", bg=BG, sashwidth=8, showhandle=False)
        panes.pack(fill="both", expand=True)

        rail = instruction_card(panes, pad=SP["md"])
        studio = instruction_card(panes, pad=SP["md"])
        status = instruction_card(panes, pad=SP["md"])
        panes.add(rail, minsize=220)
        panes.add(studio, minsize=450)
        panes.add(status, minsize=320)

        tk.Label(rail, text="Workflow", font=FONT_SECTION, bg=BG2, fg=T1, anchor="w").pack(fill="x")
        flow = [
            "1) Download WebPE or set EXE path",
            "2) Save applet settings",
            "3) Verify version + contract",
            "4) Run health check",
            "5) Launch debug mode",
            "6) Import produced sequence",
            "7) Use in Groups/Scheduler",
        ]
        for line in flow:
            tk.Label(rail, text=line, font=FS, bg=BG2, fg=T2, anchor="w", justify="left", wraplength=220).pack(fill="x", pady=(SP["xs"], 0))
        tk.Frame(rail, height=1, bg=BORDER).pack(fill="x", pady=(SP["md"], SP["sm"]))
        tk.Label(rail, textvariable=self._guidance_var, font=FONT_CAPTION, bg=BG2, fg=T3, anchor="w", justify="left", wraplength=220).pack(fill="x")

        tk.Label(studio, text="Sequencer control studio", font=FONT_SECTION, bg=BG2, fg=T1, anchor="w").pack(fill="x")
        tk.Label(studio, text="Keep this simple: save settings, verify first, then debug-run, then import generated sequence output.", font=FS, bg=BG2, fg=T2, anchor="w", wraplength=860).pack(fill="x", pady=(SP["xs"], SP["md"]))

        row = tk.Frame(studio, bg=BG2)
        row.pack(fill="x", pady=(0, SP["xs"]))
        tk.Label(row, text="Sequencer EXE", font=FS, bg=BG2, fg=T2, width=14, anchor="w").pack(side="left")
        tk.Entry(row, textvariable=self._exe_var, font=FM, bg=BG, fg=T1, relief="flat", insertbackground=T1).pack(side="left", fill="x", expand=True, padx=(0, SP["sm"]))
        self.btn(row, "Browse", self._browse_exe, color=BG3, side="left", pady=5)
        self.btn(row, "Save settings", self._save_settings, color=GREEN, side="left", pady=5)
        self.btn(row, "Cancel edits", self._revert_settings, color=BG3, side="left", pady=5)

        dl = tk.Frame(studio, bg=BG2)
        dl.pack(fill="x", pady=(SP["xs"], 0))
        self._download_webpe_btn = self.btn(
            dl, "Download WebPE", self._download_webpe_clicked, color=PURPLE, side="left", pady=5
        )
        tk.Label(
            dl,
            textvariable=self._download_progress_var,
            font=FONT_CAPTION,
            bg=BG2,
            fg=T3,
            anchor="w",
            wraplength=520,
            justify="left",
        ).pack(side="left", fill="x", expand=True, padx=(SP["sm"], 0))

        actions = tk.Frame(studio, bg=BG2)
        actions.pack(fill="x", pady=(SP["xs"], SP["sm"]))
        self.btn(actions, "Verify EXE", self._verify_exe, color=ACCENT, side="left", pady=5)
        self.btn(actions, "Test health", self._test_health, color=BG3, side="left", pady=5)
        self.btn(actions, "Launch sequencer EXE", self._launch_debug, color=GREEN, side="left", pady=5)
        self.btn(actions, "Stop debug run", self._stop_debug, color=RED, side="left", pady=5)

        actions2 = tk.Frame(studio, bg=BG2)
        actions2.pack(fill="x", pady=(0, SP["sm"]))
        self.btn(actions2, "Open logs", self._open_logs, color=BG3, side="left", pady=5)
        self.btn(actions2, "Import sequence into PharmFlow", self._import_sequence, color=PURPLE, side="left", pady=5)

        out = tk.Frame(studio, bg=BG2)
        out.pack(fill="x", pady=(0, SP["xs"]))
        tk.Label(out, text="Produced file", font=FS, bg=BG2, fg=T2, width=14, anchor="w").pack(side="left")
        tk.Entry(out, textvariable=self._output_var, font=FM, bg=BG, fg=T1, relief="flat", insertbackground=T1).pack(side="left", fill="x", expand=True, padx=(0, SP["sm"]))
        self.btn(out, "Browse file", self._browse_output, color=BG3, side="left", pady=5)

        tk.Label(status, text="Status + helper panel", font=FONT_SECTION, bg=BG2, fg=T1, anchor="w").pack(fill="x")
        tk.Label(status, textvariable=self._status_var, font=FS, bg=BG2, fg=T2, anchor="w", justify="left", wraplength=420).pack(fill="x", pady=(SP["xs"], SP["xs"]))
        tk.Label(status, textvariable=self._health_var, font=FONT_CAPTION, bg=BG2, fg=T3, anchor="w").pack(fill="x", pady=(0, SP["xs"]))
        tk.Label(status, textvariable=self._contract_var, font=FONT_CAPTION, bg=BG2, fg=T3, anchor="w").pack(fill="x", pady=(0, SP["xs"]))
        tk.Label(status, textvariable=self._error_var, font=FONT_CAPTION, bg=BG2, fg=WARN_FG, anchor="w", justify="left", wraplength=420).pack(fill="x", pady=(0, SP["sm"]))
        tk.Label(status, text="Debug log output", font=FB, bg=BG2, fg=T1, anchor="w").pack(fill="x", pady=(0, SP["xs"]))
        dbg_log_fr = tk.Frame(status, bg=BG2)
        dbg_log_fr.pack(fill="both", expand=True)
        self._log_text = tk.Text(dbg_log_fr, height=18, font=FM, bg=BG, fg=T1, relief="flat", wrap="word")
        dbg_sb = themed_vertical_scrollbar(dbg_log_fr, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=dbg_sb.set)
        self._log_text.pack(side="left", fill="both", expand=True)
        dbg_sb.pack(side="right", fill="y")
        self._log_text.configure(state="disabled")
        self._exe_var.trace_add("write", lambda *_: self._mark_dirty())
        self._output_var.trace_add("write", lambda *_: self._mark_dirty())

    def _set_status(self, msg: str, *, error: str = "") -> None:
        self._status_var.set(msg)
        self._error_var.set(error)

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _save_settings(self) -> None:
        state["webpe_exe_path"] = self._exe_var.get().strip()
        state["webpe_output_path"] = self._output_var.get().strip()
        self._dirty = False
        self._set_status("Applet settings saved for this Wizard session.")

    def _revert_settings(self) -> None:
        self._exe_var.set((state.get("webpe_exe_path") or "").strip() or str(self._guess_default_exe()))
        self._output_var.set((state.get("webpe_output_path") or "").strip())
        self._dirty = False
        self._set_status("Unsaved applet edits were discarded.")

    def _append_log(self, line: str) -> None:
        txt = line.rstrip("\r\n") + "\n"
        self._log_text.configure(state="normal")
        self._log_text.insert("end", txt)
        self._log_text.see("end")
        self._log_text.configure(state="disabled")
        if self._latest_log_path is not None:
            try:
                with self._latest_log_path.open("a", encoding="utf-8") as fh:
                    fh.write(txt)
            except OSError:
                pass

    def _browse_exe(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.winfo_toplevel(),
            title="Select sequencer executable",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
            initialdir=str(Path(self._exe_var.get()).parent) if self._exe_var.get().strip() else str(Path.home()),
        )
        if path:
            self._exe_var.set(path)
            self._set_status("Path updated. Click 'Verify EXE' to confirm it runs.")

    def _download_webpe_clicked(self) -> None:
        if self._download_busy:
            return
        self._download_busy = True
        if self._download_webpe_btn is not None:
            self._download_webpe_btn.configure(state="disabled")
        self._error_var.set("")
        self._download_progress_var.set("")
        dest_hint = _webpe_managed_exe_path()
        self._set_status("Downloading latest WebPE from GitHub…")
        self._append_log(f"Download WebPE: repo {WEBPE_GH_REPO} → {dest_hint}")

        def work() -> None:
            def prog(msg: str) -> None:
                self.after(0, lambda m=msg: self._download_progress_var.set(m))

            path, err = download_webpe_to_managed_path(progress_cb=prog)

            def finish() -> None:
                self._download_busy = False
                if self._download_webpe_btn is not None:
                    self._download_webpe_btn.configure(state="normal")
                self._download_progress_var.set("")
                if path:
                    self._exe_var.set(str(path))
                    state["webpe_exe_path"] = str(path)
                    self._dirty = False
                    self._append_log(f"Downloaded WebPE: {path}")
                    self._set_status("Download complete. Running --healthcheck…")
                    self._test_health()
                    health = (self._health_var.get() or "").lower()
                    detail = (self._error_var.get() or "").strip()
                    if detail:
                        self._set_status(
                            "WebPE downloaded, but the health check needs attention.",
                            error=detail,
                        )
                    elif "pass" in health:
                        self._set_status(
                            "WebPE downloaded and health check passed. Click Save settings to keep this path.",
                            error="",
                        )
                    else:
                        self._set_status(
                            "WebPE downloaded. Use Test health or Verify EXE if the result looks unclear.",
                            error="",
                        )
                else:
                    self._set_status(
                        "Could not download WebPE automatically.",
                        error=err,
                    )
                    self._append_log(f"Download failed:\n{err}")

            self.after(0, finish)

        threading.Thread(target=work, daemon=True).start()

    def _browse_output(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.winfo_toplevel(),
            title="Select produced sequence JSON",
            filetypes=[("JSON sequence", "*.json"), ("All files", "*.*")],
            initialdir=_json_file_dialog_initialdir(),
        )
        if path:
            self._output_var.set(path)

    def _exe_path(self) -> Path:
        return Path(self._exe_var.get().strip()).expanduser()

    def _probe_command(self, cmd: list[str], timeout: float = 12.0) -> tuple[bool, str]:
        try:
            run = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=_NO_WIN,
            )
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        blob = ((run.stdout or "") + "\n" + (run.stderr or "")).strip()
        if run.returncode == 0 and blob:
            return True, blob
        if run.returncode == 0:
            return True, "Process returned successfully."
        return False, blob or f"Exit code {run.returncode}"

    def _verify_exe(self) -> bool:
        exe = self._exe_path()
        if not exe.is_file():
            self._health_var.set("Health: EXE path not found")
            self._contract_var.set("Contract: unavailable (missing executable)")
            self._set_status(
                "The EXE path does not exist yet.",
                error="Pick the sequencer executable file and retry.",
            )
            return False
        ok_contract, raw_contract = self._probe_command([str(exe), "--pharmflow-contract"], timeout=10.0)
        if ok_contract:
            try:
                payload = json.loads(raw_contract)
                cv = str(payload.get("contractVersion") or "").strip()
                if cv:
                    self._contract_var.set(f"Contract: compatible ({cv})")
                else:
                    self._contract_var.set("Contract: response missing version")
                    self._set_status(
                        "Sequencer replied, but contract info is incomplete.",
                        error="Use a build that returns JSON with contractVersion.",
                    )
                    return False
            except Exception:
                self._contract_var.set("Contract: invalid response")
                self._set_status(
                    "Sequencer contract probe returned non-JSON output.",
                    error="Expected JSON from '--pharmflow-contract'.",
                )
                return False
        else:
            self._contract_var.set("Contract: not advertised (legacy executable)")
        attempts = [[str(exe), "--version"], [str(exe), "version"], [str(exe), "-v"]]
        for cmd in attempts:
            ok, out = self._probe_command(cmd, timeout=10.0)
            if ok:
                self._health_var.set("Health: executable verified")
                self._set_status("Sequencer executable is reachable and responding.")
                state["webpe_exe_path"] = str(exe)
                self._dirty = False
                self._append_log(f"$ {_cmd_display(cmd)}")
                self._append_log(out[:1200])
                return True
        self._health_var.set("Health: executable did not verify")
        self._set_status(
            "The EXE was found, but version check failed.",
            error="Try the right build path, then test health or launch debug for details.",
        )
        return False

    def _test_health(self) -> None:
        exe = self._exe_path()
        if not exe.is_file():
            self._health_var.set("Health: EXE path not found")
            self._contract_var.set("Contract: unavailable (missing executable)")
            self._set_status("No EXE file at this path.", error="Select a valid EXE first.")
            return
        cmd = [str(exe), "--healthcheck"]
        ok, out = self._probe_command(cmd, timeout=10.0)
        if ok:
            try:
                hp = json.loads(out)
                if bool(hp.get("ok")):
                    ver = str(hp.get("version") or "unknown")
                    self._health_var.set(f"Health: pass ({ver})")
                    self._set_status("Health test passed. You can launch debug mode.")
                    self._append_log(f"$ {_cmd_display(cmd)}")
                    self._append_log(out[:1200])
                    return
            except Exception:
                pass
        if not ok:
            cmd = [str(exe)]
            ok, out = self._probe_command(cmd, timeout=8.0)
        if ok:
            self._health_var.set("Health: pass")
            self._set_status("Health test passed. You can launch debug mode.")
            self._append_log(f"$ {_cmd_display(cmd)}")
            self._append_log(out[:1200])
        else:
            self._health_var.set("Health: needs attention")
            self._set_status("Health test could not confirm startup.", error="Open logs after a debug run for details.")
            self._append_log(f"$ {_cmd_display(cmd)}")
            self._append_log(out[:1200])

    def _new_log_path(self) -> Path:
        self._log_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        return self._log_dir / f"webpe_debug_{stamp}.log"

    def _launch_debug(self) -> None:
        if self._debug_proc and self._debug_proc.poll() is None:
            self._set_status("Debug run is already active.")
            return
        if not self._verify_exe():
            return
        exe = self._exe_path()
        try:
            self._latest_log_path = self._new_log_path()
        except OSError as exc:
            self._set_status(
                "Could not prepare debug log file.",
                error=f"{type(exc).__name__}: {exc}",
            )
            self._health_var.set("Health: logging setup failed")
            return
        cmd = [str(exe), "--debug"]
        ok_probe, _ = self._probe_command(cmd, timeout=8.0)
        if not ok_probe:
            cmd = [str(exe), "debug"]
        try:
            self._debug_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=_NO_WIN,
            )
        except Exception as exc:
            self._set_status(
                "Could not launch debug mode.",
                error=f"{type(exc).__name__}: {exc}",
            )
            return
        self._set_status("Debug run started. Output is streaming below.")
        self._append_log(f"$ {_cmd_display(cmd)}")
        self._append_log(f"Log file: {self._latest_log_path}")
        threading.Thread(target=self._pump_process_output, daemon=True).start()

    def _pump_process_output(self) -> None:
        proc = self._debug_proc
        if proc is None:
            return

        def drain(stream, tag: str) -> None:
            for line in iter(stream.readline, ""):
                self.after(0, lambda l=line, t=tag: self._append_log(f"[{t}] {l.rstrip()}"))

        threads = []
        if proc.stdout is not None:
            t1 = threading.Thread(target=drain, args=(proc.stdout, "stdout"), daemon=True)
            t1.start()
            threads.append(t1)
        if proc.stderr is not None:
            t2 = threading.Thread(target=drain, args=(proc.stderr, "stderr"), daemon=True)
            t2.start()
            threads.append(t2)
        code = proc.wait()
        for t in threads:
            t.join(timeout=0.5)
        self.after(0, lambda: self._on_debug_exit(code))

    def _on_debug_exit(self, code: int) -> None:
        if code == 0:
            self._set_status("Debug run finished successfully.")
            self._health_var.set("Health: debug run exited cleanly")
        else:
            self._set_status("Debug run ended with an error.", error=f"Exit code: {code}. Use Open logs for details.")
            self._health_var.set("Health: debug run failed")

    def _stop_debug(self) -> None:
        if not self._debug_proc or self._debug_proc.poll() is not None:
            self._set_status("No active debug run to stop.")
            return
        try:
            self._debug_proc.terminate()
            self._set_status("Stop requested. Waiting for process to exit.")
        except Exception as exc:
            self._set_status("Could not stop process cleanly.", error=str(exc))

    def _open_logs(self) -> None:
        target: Path | None = self._latest_log_path if self._latest_log_path and self._latest_log_path.exists() else None
        if target is None:
            if self._log_dir.exists():
                target = self._log_dir
            else:
                self._set_status("No logs yet.", error="Run a debug session first so logs are created.")
                return
        try:
            if IS_WIN:
                os.startfile(str(target))
            else:
                webbrowser.open(target.as_uri())
            self._set_status("Opened logs.")
        except Exception as exc:
            self._set_status("Could not open logs.", error=str(exc))

    @staticmethod
    def _extract_steps_from_payload(payload) -> tuple[list | None, str]:
        """Validate WebPE export shape and return steps with a user-facing error message."""
        if isinstance(payload, list):
            return payload, ""
        if isinstance(payload, dict):
            steps = payload.get("steps")
            if isinstance(steps, list):
                return steps, ""
            keys = ", ".join(sorted(str(k) for k in payload.keys())) or "(none)"
            if "steps" not in payload:
                return None, (
                    "Schema mismatch: expected top-level JSON array or object with 'steps' array. "
                    f"Found object keys: {keys}"
                )
            return None, (
                "Schema mismatch: expected 'steps' to be a JSON array. "
                f"Found type '{type(steps).__name__}' (keys: {keys})"
            )
        return None, (
            "Schema mismatch: expected top-level JSON array or object, "
            f"found '{type(payload).__name__}'"
        )

    @staticmethod
    def _validate_webpe_steps(steps: list) -> list[str]:
        required_by_type: dict[str, tuple[str, ...]] = {
            "open_url": ("url",),
            "tap": ("x", "y"),
            "wait": ("seconds",),
            "swipe": ("x1", "y1", "x2", "y2"),
            "keyevent": ("key",),
            "close_app": ("package",),
            "type_text": ("text",),
        }
        issues: list[str] = []
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                issues.append(f"step {idx}: expected object, found {type(step).__name__}")
                continue
            stype = step.get("type")
            if not isinstance(stype, str) or not stype.strip():
                issues.append(f"step {idx}: missing required string field 'type'")
                continue
            required = required_by_type.get(stype)
            if not required:
                continue
            missing = [name for name in required if step.get(name) in (None, "")]
            if missing:
                issues.append(f"step {idx} ({stype}): missing required field(s): {', '.join(missing)}")
        return issues

    def _import_sequence(self) -> None:
        path = (self._output_var.get() or "").strip()
        if not path:
            self._browse_output()
            path = (self._output_var.get() or "").strip()
        if not path:
            return
        src = Path(path)
        if not src.is_file():
            self._set_status("Produced file was not found.", error="Select an existing JSON output file.")
            return
        try:
            # utf-8-sig: accept UTF-8 BOM (common for Windows "export" / Notepad) without json.loads errors
            raw = src.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            self._append_log(f"Import read failure for {src}: {type(exc).__name__}: {exc}")
            self._set_status("Could not read produced file.", error=f"{type(exc).__name__}: {exc}")
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._append_log(
                f"Import JSON parse failure for {src}: line {exc.lineno}, col {exc.colno}: {exc.msg}"
            )
            self._set_status(
                "Could not parse produced file JSON.",
                error=f"{src.name}: line {exc.lineno}, col {exc.colno}: {exc.msg}",
            )
            return
        except Exception as exc:
            self._append_log(f"Import JSON parse failure for {src}: {type(exc).__name__}: {exc}")
            self._set_status("Could not parse produced file JSON.", error=f"{type(exc).__name__}: {exc}")
            return
        steps, schema_error = self._extract_steps_from_payload(payload)
        if steps is None:
            self._append_log(f"Import schema mismatch for {src}: {schema_error}")
            self._set_status("Produced file format is not supported.", error=schema_error)
            return
        issues = self._validate_webpe_steps(steps)
        if issues:
            preview = "; ".join(issues[:5])
            extra = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
            self._append_log(
                f"Import step schema mismatch for {src}: " + " | ".join(issues)
            )
            self._set_status(
                "Produced sequence failed validation.",
                error=f"{src.name}: {preview}{extra}",
            )
            return
        try:
            normalized = _normalize_sequence_steps(steps)
        except Exception as exc:
            self._append_log(f"Import normalize failure for {src}: {type(exc).__name__}: {exc}")
            self._set_status("Produced sequence could not be normalized.", error=f"{type(exc).__name__}: {exc}")
            return
        dst_dir = _default_sequences_dir()
        dst_dir.mkdir(parents=True, exist_ok=True)
        stem = src.stem
        dst = dst_dir / f"webpe_{stem}.json"
        i = 2
        while dst.exists():
            dst = dst_dir / f"webpe_{stem}_{i}.json"
            i += 1
        try:
            dst.write_text(json.dumps(normalized, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception as exc:
            self._append_log(f"Import save failure for {dst}: {type(exc).__name__}: {exc}")
            self._set_status("Import failed while saving.", error=str(exc))
            return
        self._set_status(f"Sequence imported to PharmFlow: {dst.name} ({len(normalized)} step(s))")
        state["webpe_output_path"] = str(src)
        self._dirty = False
        self._append_log(f"Imported sequence: {src} -> {dst} ({len(normalized)} step(s))")
        messagebox.showinfo(
            "Imported sequence",
            f"Imported and normalized sequence:\n{dst}\n\nYou can use it in Groups or Sequence Generator.",
            parent=self.winfo_toplevel(),
        )


# ─── main wizard ──────────────────────────────────────────────────────────────

class PharmFlowWizard(tk.Frame):
    """Nine-screen standalone setup flow with focused content and simple progress chrome."""

    PAGES = [
        WelcomePage,
        PrerequisitesPage,
        AndroidStudioPage,
        PhoneFarmPage,
        BootPage,
        AutomationPage,
        SequenceGeneratorPage,
        GroupsPage,
        LaunchPage,
    ]
    PAGE_NAMES = [
        "Start",
        "Install",
        "Android",
        "Phones",
        "Boot",
        "Steps",
        "Builder",
        "Teams",
        "Go",
    ]
    PAGE_SUBTITLES = [
        "What this does.",
        "Get the tools.",
        "Pick MuMu or Android Studio.",
        "Make your fake phones.",
        "Turn phones on + test getdabflow.",
        "Default tap list for each phone.",
        "Make your own tap list.",
        "Put phones in teams.",
        "Start everything.",
    ]

    def __init__(self, parent, *, on_finish=None):
        super().__init__(parent, bg=BG)
        self._on_finish = on_finish
        _style_scrollbars(self.winfo_toplevel())

        self._build_header()

        self._body = tk.Frame(self, bg=BG)
        self._body.pack(fill="both", expand=True, padx=SP["lg"], pady=(SP["md"], SP["md"]))

        self._content_card = tk.Frame(
            self._body,
            bg=BG2,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        self._content_card.pack(fill="both", expand=True)

        self._content = tk.Frame(self._content_card, bg=BG, padx=SP["lg"], pady=SP["lg"])
        self._content.pack(fill="both", expand=True)
        self._build_footer()

        self._active_canvas = None
        self._page_wrappers = []
        self._pages = []
        for P in self.PAGES:
            outer = tk.Frame(self._content, bg=BG)
            if P is SequenceGeneratorPage:
                # Keep Back/Cancel/OK outside the wizard canvas so they stay visible while scrolling.
                canvas_area = tk.Frame(outer, bg=BG)
                scroll_host = tk.Frame(canvas_area, bg=BG)
                canvas = tk.Canvas(scroll_host, bg=BG, highlightthickness=0)
                vsb = themed_vertical_scrollbar(
                    scroll_host,
                    command=canvas.yview,
                )
                canvas.configure(yscrollcommand=vsb.set)
                vsb.pack(side="right", fill="y")
                canvas.pack(side="left", fill="both", expand=True)
                scroll_host.pack(fill="both", expand=True)
                footer_slot = tk.Frame(outer, bg=BG, height=76)
                footer_slot.pack_propagate(False)
                canvas_area.pack(fill="both", expand=True)
                footer_slot.pack(side="bottom", fill="x")
                page = P(canvas, footer_parent=footer_slot)
            else:
                scroll_host = tk.Frame(outer, bg=BG)
                canvas = tk.Canvas(scroll_host, bg=BG, highlightthickness=0)
                vsb = themed_vertical_scrollbar(
                    scroll_host,
                    command=canvas.yview,
                )
                canvas.configure(yscrollcommand=vsb.set)
                vsb.pack(side="right", fill="y")
                canvas.pack(side="left", fill="both", expand=True)
                scroll_host.pack(fill="both", expand=True)
                page = P(canvas)
            page.app = self
            cwin = canvas.create_window((0, 0), window=page, anchor="nw")
            page.bind(
                "<Configure>",
                lambda _e, c=canvas: canvas_set_scrollregion_from_bbox_all(c),
            )
            canvas.bind(
                "<Configure>",
                lambda e, c=canvas, w=cwin: canvas_embed_set_width(c, w, e),
            )
            canvas.bind("<Enter>", lambda e, c=canvas: c.focus_set())
            page.bind("<Enter>", lambda e, c=canvas: c.focus_set())
            if P not in (LaunchPage, SequenceGeneratorPage, WebpePage):
                scroll_bottom_spacer(page).pack(fill="x")
            canvas_schedule_scrollregion_refresh(canvas)
            outer.place(relwidth=1, relheight=1)
            self._pages.append(page)
            self._page_wrappers.append((outer, canvas))

        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>",   self._on_mousewheel)
        self.bind_all("<Button-5>",   self._on_mousewheel)

        self._current = 0
        self._show(0)

        # Try to auto-detect PharmFlow directory
        guesses = [
            _pharmflow_install_root(),
            Path.home() / "PharmFlow",
            Path("C:/PharmFlow"),
        ]
        for g in guesses:
            gp = Path(g)
            if (gp / "automation" / "dashboard.py").exists():
                state["pharmflow_dir"] = str(gp.resolve())
                break
            found = _find_pharmflow_dashboard_root(gp)
            if found:
                state["pharmflow_dir"] = str(found)
                break
        _try_load_groups_config()

    def _build_header(self):
        """Clean standalone header: title, subtitle, and compact horizontal step tracker."""
        bar = tk.Frame(self, bg=BG2, highlightthickness=1, highlightbackground=BORDER)
        bar.pack(fill="x", padx=SP["xl"], pady=(SP["xl"], 0))
        accent_top_strip(bar).pack(fill="x")

        top = tk.Frame(bar, bg=BG2)
        top.pack(fill="x", padx=SP["xl"], pady=(SP["lg"], SP["sm"]))
        copy_col = tk.Frame(top, bg=BG2)
        copy_col.pack(side="left", fill="x", expand=True)
        tk.Label(
            copy_col,
            text="PharmFlow",
            font=FONT_PAGE_TITLE,
            bg=BG2,
            fg=T1,
            anchor="w",
        ).pack(fill="x")
        self._subtitle_lbl = tk.Label(
            copy_col,
            text="",
            font=FS,
            bg=BG2,
            fg=T2,
            anchor="w",
            justify="left",
        )
        self._subtitle_lbl.pack(fill="x", pady=(SP["xs"], 0))
        bind_responsive_wraplength(self._subtitle_lbl, copy_col, pad=8)

        self._step_lbl = tk.Label(
            top,
            text="",
            font=FONT_UI,
            bg=BG2,
            fg=T2,
            anchor="e",
            justify="right",
        )
        self._step_lbl.pack(side="right", padx=(SP["md"], 0), pady=(0, SP["xs"]))

        tk.Frame(bar, bg=BORDER, height=1).pack(fill="x", padx=SP["xl"], pady=(0, SP["sm"]))
        track = tk.Frame(bar, bg=BG2)
        track.pack(fill="x", padx=SP["xl"], pady=(0, SP["lg"]))
        self._nav_rows: list[dict[str, tk.Widget]] = []
        for i, name in enumerate(self.PAGE_NAMES):
            cell = tk.Frame(track, bg=BG2)
            cell.pack(side="left", fill="x", expand=True, padx=(0 if i == 0 else 6, 0))
            dot = tk.Label(
                cell,
                text=str(i + 1),
                font=("Segoe UI", 9, "bold"),
                bg=BG4,
                fg=T3,
                width=2,
                pady=3,
            )
            dot.pack(side="left")
            title = tk.Label(
                cell,
                text=name,
                font=FONT_CAPTION,
                bg=BG2,
                fg=T3,
                anchor="w",
            )
            title.pack(side="left", padx=(6, 0))
            self._nav_rows.append({"dot": dot, "title": title})

    def _build_footer(self):
        dock = tk.Frame(self, bg=BG)
        dock.pack(fill="x", side="bottom")
        tk.Frame(dock, height=1, bg=BORDER).pack(fill="x", padx=SP["xl"])
        ftr = tk.Frame(dock, bg=FOOTER_BG, height=96, highlightthickness=1, highlightbackground=BORDER)
        ftr.pack(fill="x")
        ftr.pack_propagate(False)

        def _sync_footer_hint_wrap(_event: tk.Event | None = None) -> None:
            try:
                wpx = int(ftr.winfo_width())
            except (tk.TclError, ValueError):
                return
            reserve = 440
            self._footer_hint.configure(wraplength=max(160, wpx - reserve))

        self._footer_hint = tk.Label(
            ftr,
            text="",
            font=FONT_CAPTION,
            bg=FOOTER_BG,
            fg=T3,
            anchor="w",
            justify="left",
        )
        self._footer_hint.pack(side="left", padx=SP["xl"], pady=(SP["xs"], SP["xs"]))
        ftr.bind("<Configure>", lambda e: _sync_footer_hint_wrap(e), add=True)
        self._cancel_btn = tk.Button(
            ftr, text="Cancel",
            font=("Segoe UI", 11),
            command=lambda: self.winfo_toplevel().destroy(),
            padx=SP["md"], pady=SP["sm"],
        )
        style_ghost_button(self._cancel_btn)
        self._cancel_btn.pack(side="left", padx=SP["lg"], pady=SP["sm"])
        # Per-page button slot (e.g. Groups → "Tryout / Run playlist now").
        # Pages opt in by implementing ``populate_footer_actions(parent)``; the
        # slot is cleared and rebuilt on every ``_show`` so leaving the page
        # removes its buttons automatically.
        self._footer_page_actions = tk.Frame(ftr, bg=FOOTER_BG)
        self._footer_page_actions.pack(side="left", padx=(0, SP["sm"]), pady=SP["sm"])
        self._next_btn = tk.Button(ftr, text="Next",
                                   font=("Segoe UI", 11, "bold"),
                                   command=self._next,
                                   padx=SP["lg"], pady=SP["sm"])
        style_primary_button(self._next_btn)
        self._next_btn.pack(side="right", padx=SP["lg"], pady=SP["sm"])
        self._back_btn = tk.Button(ftr, text="Back",
                                   font=("Segoe UI", 11),
                                   command=self._back,
                                   padx=SP["md"], pady=SP["sm"])
        style_secondary_button(self._back_btn)
        self._back_btn.pack(side="right", padx=(0, SP["sm"]), pady=SP["sm"])
        ftr.after_idle(lambda: _sync_footer_hint_wrap())

    def start_tryout_from_groups(self) -> None:
        """Open Launch and run the one-click automation path."""
        idx = self.PAGES.index(LaunchPage)
        self._show(idx)
        page = self._pages[idx]
        if hasattr(page, "_start_automation_one_click"):
            self.after(80, page._start_automation_one_click)

    def _on_mousewheel(self, event):
        try:
            w = self.winfo_containing(event.x_root, event.y_root) or event.widget
        except tk.TclError:
            w = event.widget
        nested = nested_scroll_canvas_at_widget(w, exclude=self._active_canvas)
        target = nested if nested is not None else self._active_canvas
        if not target:
            return
        if event.num == 4:
            target.yview_scroll(-1, "units")
        elif event.num == 5:
            target.yview_scroll(1, "units")
        else:
            # Windows precision touchpads emit |delta| < 120; int(delta/120) was often 0.
            d = getattr(event, "delta", 0) or 0
            if d == 0:
                return
            scaled = -d / 120.0
            n = int(round(scaled))
            if n == 0:
                n = 1 if scaled > 0 else -1
            target.yview_scroll(n, "units")

    def _show(self, idx):
        self._current = idx
        for i, (outer, canvas) in enumerate(self._page_wrappers):
            if i == idx:
                outer.lift()
                self._active_canvas = canvas
                canvas.yview_moveto(0)
                canvas_schedule_scrollregion_refresh(canvas)
        for i, cell in enumerate(self._nav_rows):
            dot = cell["dot"]
            title = cell["title"]
            if i < idx:
                dot.config(bg=ACCENT_MUTED, fg=T1)
                title.config(fg=T2, font=FONT_CAPTION)
            elif i == idx:
                dot.config(bg=ACCENT, fg=ON_ACCENT)
                title.config(fg=T1, font=("Segoe UI", 9, "bold"))
            else:
                dot.config(bg=BG4, fg=T3)
                title.config(fg=T3, font=FONT_CAPTION)
        total = len(self.PAGES)
        self._step_lbl.config(
            text=f"Step {idx + 1} of {total}",
            fg=T2 if idx < total - 1 else ACCENT,
        )
        self._subtitle_lbl.config(text=self.PAGE_SUBTITLES[idx])
        self._footer_hint.config(
            text=f"{self.PAGE_NAMES[idx]} — {self.PAGE_SUBTITLES[idx]}",
            fg=T2 if idx < total - 1 else ACCENT,
        )
        self._back_btn.config(state="normal" if idx > 0 else "disabled")
        self._next_btn.config(
            text="Finish Setup" if idx == total - 1 else "Next Step")
        self._refresh_footer_page_actions(idx)
        self._pages[idx].on_enter()

    def _refresh_footer_page_actions(self, idx: int) -> None:
        """Reset the wizard's footer-action slot and let the active page populate it."""
        slot = getattr(self, "_footer_page_actions", None)
        if slot is None:
            return
        for child in list(slot.winfo_children()):
            try:
                child.destroy()
            except tk.TclError:
                pass
        page = self._pages[idx]
        populate = getattr(page, "populate_footer_actions", None)
        if not callable(populate):
            return
        try:
            populate(slot)
        except Exception:
            tb = traceback.format_exc()
            print(
                f"[wizard] populate_footer_actions failed for {type(page).__name__}:\n{tb}",
                file=sys.stderr,
            )

    def _next(self):
        if self._pages[self._current].can_advance():
            if self._current < len(self._pages) - 1:
                self._show(self._current + 1)
            else:
                if self._on_finish:
                    self._on_finish()
                else:
                    self.winfo_toplevel().destroy()

    def _back(self):
        if self._current > 0:
            self._show(self._current - 1)


def _env_truthy(name: str) -> bool:
    v = os.environ.get(name, "").strip().lower()
    return v in ("1", "true", "yes", "on")


if __name__ == "__main__":
    # Default: full Tk wizard only (embeddable ``PharmFlowWizard`` needs a ``Tk`` or ``Toplevel`` parent).
    if _env_truthy("PHARMFLOW_USE_DESKTOP"):
        try:
            from pharmflow_desktop import main as _desktop_main
        except ImportError:
            pass
        else:
            _desktop_main()
            raise SystemExit(0)

    _root = tk.Tk()
    _style_scrollbars(_root)
    _root.title("PharmFlow")
    _root.geometry("1120x960")
    _root.minsize(960, 780)
    _root.config(bg=BG)
    _root.configure(highlightthickness=0)
    _wiz = PharmFlowWizard(_root)
    _wiz.pack(fill="both", expand=True)

    def _standalone_wm_delete() -> None:
        _root.destroy()

    _root.protocol("WM_DELETE_WINDOW", _standalone_wm_delete)
    _root.mainloop()
