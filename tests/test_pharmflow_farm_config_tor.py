"""SSOT must not pin PHARMFLOW_TOR_PATH at a missing branded path."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import automation.pharmflow_farm_config as cfg


def _norm(value: object) -> str:
    return str(value).replace("/", "\\").lower()


def test_resolve_tor_exe_path_falls_back_to_cpharm_when_pharmflow_missing(
    monkeypatch,
) -> None:
    """When branded PharmFlow trees lack tor.exe, use C:\\CPharm seed."""

    def _is_file(self: Path) -> bool:  # noqa: ANN001
        text = _norm(self)
        if "\\pharmflow\\" in text:
            return False
        if text.endswith("c:\\cpharm\\bundled\\tor.exe"):
            return True
        return False

    monkeypatch.setattr(Path, "is_file", _is_file)
    got = _norm(cfg.resolve_tor_exe_path())
    assert got.endswith("c:\\cpharm\\bundled\\tor.exe")


def test_apply_farm_env_heals_missing_tor_path(monkeypatch) -> None:
    monkeypatch.setattr(
        cfg,
        "resolve_tor_exe_path",
        lambda: r"C:\CPharm\bundled\tor.exe",
    )

    # Hermetic: the heal only fires when the branded PharmFlow tor.exe is
    # actually absent. On a host that really has C:\PharmFlow\bundled\tor.exe a
    # plain is_file() check made this assertion host-dependent.
    def _is_file(self: Path) -> bool:  # noqa: ANN001
        text = _norm(self)
        return not ("\\pharmflow\\" in text and text.endswith("\\tor.exe"))

    monkeypatch.setattr(Path, "is_file", _is_file)
    env: dict[str, str] = {}
    with mock.patch.object(
        cfg,
        "get_runtime",
        return_value={"PHARMFLOW_TOR_PATH": r"C:\PharmFlow\bundled\tor.exe"},
    ):
        out = cfg.apply_farm_env(env)
    assert _norm(out["PHARMFLOW_TOR_PATH"]).endswith("c:\\cpharm\\bundled\\tor.exe")
