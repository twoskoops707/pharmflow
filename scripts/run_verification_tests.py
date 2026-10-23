#!/usr/bin/env python3
"""Run automated verification checks mapped to docs/testing_checklist.md.

Headless checks run on any OS. MuMu/ADB/Tor/UI items are reported as MANUAL
with instructions. Exit code 0 if all automated checks pass.

Usage:
    python scripts/run_verification_tests.py
    python scripts/run_verification_tests.py --json
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_gui_stubs() -> bool:
    """Stub tkinter/customtkinter on headless CI so import checks can run."""
    try:
        import tkinter  # noqa: F401
        return True
    except ModuleNotFoundError:
        pass

    import types

    tk_mod = types.ModuleType("tkinter")
    tk_mod.scrolledtext = types.ModuleType("tkinter.scrolledtext")
    tk_mod.scrolledtext.ScrolledText = object
    tk_mod.filedialog = types.ModuleType("tkinter.filedialog")
    tk_mod.filedialog.askopenfilename = lambda **_: ""
    tk_mod.filedialog.askdirectory = lambda **_: ""
    tk_mod.messagebox = types.ModuleType("tkinter.messagebox")
    tk_mod.messagebox.askyesno = lambda *a, **k: False
    tk_mod.messagebox.showwarning = lambda *a, **k: None
    sys.modules["tkinter"] = tk_mod
    sys.modules["tkinter.scrolledtext"] = tk_mod.scrolledtext
    sys.modules["tkinter.filedialog"] = tk_mod.filedialog
    sys.modules["tkinter.messagebox"] = tk_mod.messagebox

    ctk_mod = types.ModuleType("customtkinter")
    for name in (
        "CTk",
        "CTkFrame",
        "CTkLabel",
        "CTkButton",
        "CTkEntry",
        "CTkComboBox",
        "CTkToplevel",
        "CTkTabview",
        "CTkScrollableFrame",
        "CTkProgressBar",
        "CTkSwitch",
        "CTkImage",
        "set_appearance_mode",
        "set_default_color_theme",
    ):
        setattr(ctk_mod, name, type(name, (), {}) if name.startswith("CTk") else lambda *a, **k: None)
    sys.modules["customtkinter"] = ctk_mod
    return False


_HEADLESS = not _ensure_gui_stubs()


@dataclass
class CheckResult:
    checklist_id: str
    name: str
    status: str  # PASS, FAIL, SKIP, MANUAL
    detail: str = ""


@dataclass
class VerificationReport:
    results: list[CheckResult] = field(default_factory=list)

    def add(self, checklist_id: str, name: str, status: str, detail: str = "") -> None:
        self.results.append(CheckResult(checklist_id, name, status, detail))

    @property
    def automated_passed(self) -> bool:
        return not any(r.status == "FAIL" for r in self.results)

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.results:
            counts[r.status] = counts.get(r.status, 0) + 1
        return counts


def _import_module(name: str) -> tuple[bool, str]:
    try:
        importlib.import_module(name)
        return True, ""
    except Exception as exc:
        return False, str(exc)


def run_unit_tests() -> tuple[bool, str]:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for mod_name in (
        "tests.test_path_detection",
        "tests.test_pyinstaller_common",
        "tests.test_tor_manager",
        "tests.test_mumu_farm_ops",
        "tests.test_dashboard",
        "tests.test_mumu_fingerprint",
    ):
        mod_path = ROOT / mod_name.replace(".", "/")
        if (mod_path.parent / f"{mod_path.name}.py").is_file():
            try:
                suite.addTests(loader.loadTestsFromName(mod_name))
            except Exception:
                pass
    runner = unittest.TextTestRunner(stream=open(os.devnull, "w"), verbosity=0)
    result = runner.run(suite)
    if result.wasSuccessful():
        return True, f"{result.testsRun} tests passed"
    failures = len(result.failures) + len(result.errors)
    return False, f"{failures} failures/errors in {result.testsRun} tests"


def check_sequences_load(report: VerificationReport) -> None:
    try:
        from automation.sequence_paths import discover_sequence_files, list_sequence_ids
        from wizard.wizard_paths import sequences_dir

        seq_dir = sequences_dir()
        files = discover_sequence_files(seq_dir)
        ids = list_sequence_ids(seq_dir)
        if files:
            report.add("10.1", "Sequences load (JSON)", "PASS", f"{len(files)} files, {len(ids)} ids")
        else:
            report.add("10.1", "Sequences load (JSON)", "SKIP", f"No sequences under {seq_dir}")
    except Exception as exc:
        report.add("10.1", "Sequences load (JSON)", "FAIL", str(exc))


def check_dashboard_api(report: VerificationReport) -> None:
    try:
        import automation.dashboard as dashboard
        from unittest.mock import MagicMock, patch

        mock_farm = MagicMock()
        mock_farm.is_ready = True
        mock_farm.instances = {}
        mock_farm.detect.return_value = {}
        mock_farm.tor.detect.return_value = {}
        mock_farm.list_instances.return_value = []
        mock_farm.get_phone_status.return_value = {"name": "t", "running": False, "connected": False}
        dashboard.farm = mock_farm
        dashboard.runner = MagicMock()
        dashboard.groups = MagicMock()
        dashboard.groups.list_groups.return_value = []
        dashboard.scheduler = MagicMock()
        dashboard.scheduler.get_job_log.return_value = []
        if hasattr(dashboard, "_activity_log"):
            dashboard._activity_log.clear()

        client = dashboard.app.test_client()
        routes = {rule.rule for rule in dashboard.app.url_map.iter_rules()}
        expected = [
            ("/api/status", "9.1"),
            ("/api/phones", "9.2"),
            ("/api/sequences", "10.1"),
        ]
        if "/api/tor" in routes:
            expected.append(("/api/tor", "7.3"))

        patches = []
        if hasattr(dashboard, "_enrich_phone_status"):
            patches.append(patch.object(dashboard, "_enrich_phone_status", side_effect=lambda s: s))
        if hasattr(dashboard, "_phone_tor_status"):
            patches.append(patch.object(dashboard, "_phone_tor_status", return_value={"name": "t", "ok": True}))

        for p in patches:
            p.start()
        try:
            for path, label in expected:
                if path not in routes:
                    report.add(label, f"Dashboard route {path}", "SKIP", "not in this build")
                    continue
                resp = client.get(path)
                if resp.status_code == 200:
                    report.add(label, f"Dashboard GET {path}", "PASS", "200 OK")
                else:
                    report.add(label, f"Dashboard GET {path}", "FAIL", f"status {resp.status_code}")
        finally:
            for p in patches:
                p.stop()
    except Exception as exc:
        report.add("9.1", "Dashboard API", "FAIL", str(exc))


def check_hidden_imports(report: VerificationReport) -> None:
    try:
        from wizard.pyinstaller_common import base_hiddenimports

        required = (
            "wizard.pharmflow_desktop",
            "wizard.setup_desktop",
            "wizard.path_detection",
            "wizard.path_utils",
            "automation.dashboard",
            "flask",
            "customtkinter",
        )
        hidden = base_hiddenimports()
        missing = [m for m in required if m not in hidden]
        if missing:
            report.add("13.3", "PyInstaller hidden imports", "FAIL", f"Missing: {missing}")
        else:
            report.add("13.3", "PyInstaller hidden imports", "PASS", f"{len(hidden)} modules listed")
    except Exception as exc:
        report.add("13.3", "PyInstaller hidden imports", "FAIL", str(exc))


def check_spec_files(report: VerificationReport) -> None:
    specs = ("wizard/PharmFlow.spec",)
    for spec in specs:
        path = ROOT / spec
        if path.is_file():
            report.add("13.1", f"Spec exists: {spec}", "PASS", str(path))
        else:
            report.add("13.1", f"Spec exists: {spec}", "FAIL", "missing")


def check_path_modules(report: VerificationReport) -> None:
    pairs = (
        ("1.3", "wizard.gui.path_selector", "PathSelectorWindow module"),
        ("1.4", "wizard.path_store", "Path persistence module"),
        ("1.4", "wizard.path_utils", "Path normalize/apply module"),
        ("2.5", "wizard.path_detection", "detect_with_fallback module"),
    )
    for cid, mod, label in pairs:
        ok, err = _import_module(mod)
        if ok:
            report.add(cid, label, "PASS", mod)
        elif _HEADLESS and "tkinter" in err.lower():
            report.add(cid, label, "SKIP", "headless — no tkinter")
        else:
            report.add(cid, label, "FAIL", err or f"Cannot import {mod}")


def check_core_imports(report: VerificationReport) -> None:
    modules = (
        "wizard.pharmflow_merged",
        "wizard.pharmflow_desktop",
        "wizard.setup_desktop",
        "wizard.mumu_farm_ops",
        "automation.tor_manager",
        "automation.mumu_fingerprint",
        "automation.sequence_runner",
    )
    for mod in modules:
        ok, err = _import_module(mod)
        if ok:
            report.add("13.3", f"Import {mod}", "PASS", "ok")
        elif _HEADLESS and "tkinter" in err.lower():
            report.add("13.3", f"Import {mod}", "SKIP", "headless")
        else:
            report.add("13.3", f"Import {mod}", "FAIL", err)


def add_manual_items(report: VerificationReport) -> None:
    manual = (
        ("1.1", "EXE launches window"),
        ("1.2", "First-run setup detection"),
        ("1.5", "Saved paths persist after restart"),
        ("2.1", "Auto-detect MuMu Player"),
        ("2.2", "Auto-detect MuMu Global ARM"),
        ("2.3", "Detect non-standard drive install"),
        ("2.4", "Detect AppData MuMu install"),
        ("2.6", "Clear not-found message in UI"),
        ("3.1", "ADB auto-download"),
        ("3.2", "ADB connects to emulator"),
        ("3.3", "ADB shell/install/reverse"),
        ("3.4", "Multiple ADB devices"),
        ("4.1", "Create phone VM"),
        ("4.2", "Start phone"),
        ("4.3", "Stop phone"),
        ("4.4", "Configure phone settings"),
        ("4.5", "Delete phone VM"),
        ("5.1", "USB debug instructions UI"),
        ("5.2", "Enable USB debugging on emulator"),
        ("5.3", "USB debug verification via adb"),
        ("6.1", "setting.json retail values"),
        ("6.2", "ADB security flags"),
        ("6.3", "Browser automation flags"),
        ("6.4", "getprop retail values"),
        ("6.5", "Cold boot applies fingerprint"),
        ("6.6", "Re-apply fingerprint"),
        ("7.1", "Tor Browser detection"),
        ("7.2", "Tor Expert Bundle tor.exe"),
        ("7.4", "adb reverse guest proxy"),
        ("7.5", "Tor identity rotation"),
        ("7.6", "Unique IP per phone"),
        ("8.1", "Chromium APK download"),
        ("8.2", "Chromium sideload"),
        ("8.3", "MuMu Browser opens URLs"),
        ("8.4", "MuMu Browser honors http_proxy"),
        ("8.5", "Chromium proxy behavior documented"),
        ("9.3", "Dashboard live status refresh"),
        ("9.4", "Dashboard start/stop controls"),
        ("9.5", "Run sequence from dashboard UI"),
        ("10.2", "Execute sequence on phone"),
        ("10.3", "Sequence wait timing"),
        ("10.4", "Coordinate scaling"),
        ("10.5", "Humanization variance"),
        ("11.1", "UI screen scrolling"),
        ("11.2", "Scrollbar / ScrolledText"),
        ("11.3", "Sub-windows (Settings, etc.)"),
        ("11.4", "All button handlers"),
        ("11.5", "Theme colors render"),
        ("11.6", "Custom icons display"),
        ("12.1", "ro.kernel.qemu not 1"),
        ("12.2", "Retail brand in getprop"),
        ("12.3", "Retail model in getprop"),
        ("12.4", "No MuMu strings in getprop"),
        ("12.5", "navigator.webdriver not exposed"),
        ("13.2", "Standalone EXE on clean Windows"),
        ("13.4", "GitHub Release artifact upload"),
    )
    for cid, name in manual:
        report.add(cid, name, "MANUAL", "Requires Windows + MuMu — see docs/testing_checklist.md")


def run_verification() -> VerificationReport:
    report = VerificationReport()

    ok, detail = run_unit_tests()
    report.add("—", "Unit test suite", "PASS" if ok else "FAIL", detail)

    check_spec_files(report)
    check_path_modules(report)
    check_core_imports(report)
    check_hidden_imports(report)
    check_sequences_load(report)
    check_dashboard_api(report)
    add_manual_items(report)

    return report


def print_report(report: VerificationReport, as_json: bool = False) -> None:
    if as_json:
        print(
            json.dumps(
                {
                    "summary": report.summary(),
                    "passed": report.automated_passed,
                    "results": [r.__dict__ for r in report.results],
                },
                indent=2,
            )
        )
        return

    print("=" * 60)
    print("PharmFlow Verification Report")
    print("=" * 60)
    for r in report.results:
        print(f"  [{r.status:6}] {r.checklist_id:6} {r.name}")
        if r.detail and r.status in ("FAIL", "SKIP"):
            print(f"           → {r.detail}")
    print("-" * 60)
    summary = report.summary()
    print(f"Summary: {summary}")
    print(f"Automated checks OK: {report.automated_passed}")
    print("Complete manual checklist: docs/testing_checklist.md")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PharmFlow automated verification checks")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    args = parser.parse_args()

    report = run_verification()
    print_report(report, as_json=args.json)
    return 0 if report.automated_passed else 1


if __name__ == "__main__":
    sys.exit(main())
