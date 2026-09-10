"""Groups editor + sequence playlist regression tests.

Covers the 2026-09-10 port of the old wizard's Groups/per-phone-steps/playlist
editing into the dashboard:

1. ``sequence_playlist`` used to reference a bare ``SEQUENCES_DIR`` constant it
   never defined. Any dashboard POST that normalized playlist refs
   (``/api/groups/save`` with ``sequence_playlist`` entries) crashed with
   NameError — silently, since the handler only logged it. These tests pin the
   contract that crashed: module attribute exists and normalization succeeds
   with and without an explicit directory.

2. The dashboard must expose the groups-editor surface end to end:
   ``/api/sequences/list`` (playlist picker source, fast on the 8k+ file tree),
   ``/api/groups/delete`` (old-GUI parity for removing groups), and the editor
   JS entry points in the served HTML.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_sequences_dir_module_attribute_exists() -> None:
    """The NameError killer: bare SEQUENCES_DIR must exist post-import."""
    from automation import sequence_playlist as sp

    assert isinstance(sp.SEQUENCES_DIR, Path)


def test_normalize_playlist_ref_no_explicit_dir_no_nameerror() -> None:
    """Default-dir normalization path must not raise (was unconditional NameError)."""
    from automation.sequence_playlist import normalize_playlist_ref

    # Non-.json and unknown refs → '' (refused), but crucially no NameError.
    assert normalize_playlist_ref("720x1280/__definitely_missing__") == ""
    assert normalize_playlist_ref("") == ""
    assert normalize_playlist_ref("../escape") == ""


def test_normalize_playlist_ref_with_explicit_dir(tmp_path: Path) -> None:
    """Explicit-dir path keeps working alongside the default-dir fix."""
    from automation.sequence_playlist import normalize_playlist_ref

    real_dir = tmp_path / "seqs"
    real_dir.mkdir()
    (real_dir / "my_seq.json").write_text('{"steps": []}', encoding="utf-8")

    # Refs carry the .json suffix (normalize refuses anything else).
    assert normalize_playlist_ref("720x1280/my_seq.json", sequences_dir=real_dir) == "720x1280/my_seq.json"
    assert normalize_playlist_ref(str(real_dir / "my_seq.json"), sequences_dir=real_dir) == "my_seq.json"
    assert normalize_playlist_ref("../escape.json", sequences_dir=real_dir) == "escape.json"
    assert normalize_playlist_ref("nope.json", sequences_dir=real_dir) == "nope.json"


def test_normalize_sequence_folder_rejects_escape() -> None:
    from automation.sequence_playlist import normalize_sequence_folder

    assert normalize_sequence_folder("720x1280/ad") == "720x1280/ad"
    assert normalize_sequence_folder("../etc") == ""
    assert normalize_sequence_folder("") == ""


def test_resolve_sequence_file_finds_real_sequence() -> None:
    """Resolution lands on a real file under the module's own sequences root."""
    from automation.sequence_playlist import SEQUENCES_DIR, resolve_sequence_file

    if not SEQUENCES_DIR.is_dir():  # pragma: no cover — instance without recordings
        pytest.skip("no sequences tree on this instance")

    profile = next(
        (d for d in sorted(SEQUENCES_DIR.iterdir()) if d.is_dir() and list(d.glob("*.json"))),
        None,
    )
    if profile is None:  # pragma: no cover — root exists but empty
        pytest.skip("sequences root has no profile subdirs with files")

    target = sorted(profile.glob("*.json"))[0]
    ref = f"{profile.name}/{target.name}"
    hit = resolve_sequence_file(ref, profile_key=profile.name)
    assert hit is not None and hit.is_file()
    # Direct path always resolves when the ref is exact.
    assert resolve_sequence_file(ref) is not None


# ---------------------------------------------------------------------------
# Dashboard API surface for the editor UI
# ---------------------------------------------------------------------------


def test_dashboard_source_has_sequences_list_endpoint() -> None:
    src = (REPO_ROOT / "automation" / "dashboard.py").read_text(encoding="utf-8")
    assert '"/api/sequences/list"' in src, "playlist picker needs its data source"


def test_dashboard_source_has_groups_delete_endpoint() -> None:
    src = (REPO_ROOT / "automation" / "dashboard.py").read_text(encoding="utf-8")
    assert '"/api/groups/delete"' in src, "old-GUI parity: groups must be deletable"


def test_dashboard_html_has_editor_entry_points() -> None:
    src = (REPO_ROOT / "automation" / "dashboard.html").read_text(encoding="utf-8")
    for fn in ("openGroupEditor", "renderSteps", "openPlaylistEditor"):
        assert fn in src, f"groups editor UI missing: {fn}"
