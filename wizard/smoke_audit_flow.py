#!/usr/bin/env python3
"""End-to-end flow audit — catches wiring mistakes before they ship in PharmFlow.exe."""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

_WIZARD = Path(__file__).resolve().parent


def _fail(msg: str) -> int:
    print(f"smoke_audit_flow: {msg}", file=sys.stderr)
    return 1


def main() -> int:
    sys.path.insert(0, str(_WIZARD))

    from pharmflow_wizard_bridge import WIZARD_STEPS
    from setup_wizard import PharmFlowWizard

    if len(WIZARD_STEPS) != 10:
        return _fail(f"WIZARD_STEPS has {len(WIZARD_STEPS)} entries, expected 10")
    if len(PharmFlowWizard.PAGES) != 9:
        return _fail(f"PharmFlowWizard.PAGES has {len(PharmFlowWizard.PAGES)} entries, expected 9")
    for i, step in enumerate(WIZARD_STEPS):
        if step.get("index") != i:
            return _fail(f"WIZARD_STEPS[{i}] index mismatch: {step.get('index')}")

    for label, idx in (
        ("edit_sequence", 5),
        ("builder", 6),
        ("groups", 7),
        ("launch", 8),
    ):
        if idx >= len(PharmFlowWizard.PAGE_NAMES):
            return _fail(f"spawn page index {idx} for {label} out of range")

    spawn_src = (_WIZARD / "wizard_tk_spawn.py").read_text(encoding="utf-8")
    if "--internal-tk-page" not in spawn_src:
        return _fail("wizard_tk_spawn must pass --internal-tk-page")
    if "subprocess.Popen" not in spawn_src:
        return _fail("wizard_tk_spawn must use subprocess.Popen")

    desktop = (_WIZARD / "pharmflow_desktop.py").read_text(encoding="utf-8")
    if "run_pharmflow_app_or_fallback" not in desktop.split("def main")[-1]:
        return _fail("default main() path must call run_pharmflow_app_or_fallback() (WebView UI)")
    if "_use_classic_tk_shell" not in desktop:
        return _fail("main() missing classic Tk gate")

    phone_entry = (_WIZARD / "phone_setup_entry.py").read_text(encoding="utf-8")
    if "mumu_setup_webview" not in phone_entry:
        return _fail("phone_setup_main must open mumu_setup_webview")
    if "pharmflow_app_webview" in phone_entry:
        return _fail("phone_setup must not route to pharmflow_app_webview")

    core = (_WIZARD / "mumu_setup_core.py").read_text(encoding="utf-8")
    if "Already set up — opening PharmFlow" not in core:
        return _fail("legacy standalone message missing from mumu_setup_core")
    if "phone settings and sequences refreshed" not in core:
        return _fail("unified exe refresh message missing from mumu_setup_core")

    html = (_WIZARD / "assets" / "pharmflow_app" / "index.html").read_text(encoding="utf-8")
    if "data-bubble" in html or "bubble-panel" in html:
        return _fail("WebView HTML still uses bubble panels")

    import pharmflow_desktop

    src = inspect.getsource(pharmflow_desktop.main)
    tree = ast.parse(src)
    handlers = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Constant):
            if node.left.value == "--internal-tk-page":
                handlers.add("--internal-tk-page")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "is_phone_setup_mode":
                handlers.add("phone_setup")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "_use_classic_tk_shell":
                handlers.add("classic_tk")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "run_pharmflow_app_or_fallback":
                handlers.add("webview")

    for required in ("--internal-tk-page", "phone_setup", "webview"):
        if required not in handlers:
            return _fail(f"main() missing handler for {required}")

    from setup_wizard import _persist_groups_config, _try_load_groups_config

    if not callable(_persist_groups_config) or not callable(_try_load_groups_config):
        return _fail("groups persist/load helpers missing")

    bridge_src = (_WIZARD / "pharmflow_wizard_bridge.py").read_text(encoding="utf-8")
    webview_src = (_WIZARD / "pharmflow_app_webview.py").read_text(encoding="utf-8")
    if "run_startup_cleanup(" in webview_src:
        return _fail("Control Panel open must not run phone-setup cleanup (adb kill-server)")
    # Deck-native path: cursor_* endpoints + headless builder/groups (no Tk page windows).
    for fn in (
        "cursor_get_sequence",
        "cursor_add_step",
        "cursor_add_group",
        "cursor_remove_group",
        "cursor_rename_group",
        "boot_all_phones",
        "boot_all_status",
        "test_phone_status",
        "scan_site_status",
    ):
        if f"def {fn}" not in bridge_src:
            return _fail(f"pharmflow_wizard_bridge missing {fn}")
    for fn in ("open_sequence_builder", "open_groups_manager"):
        block = bridge_src.split(f"def {fn}", 1)
        if len(block) < 2:
            return _fail(f"pharmflow_wizard_bridge missing {fn}")
        head = block[1].split("\ndef ", 1)[0]
        if "_open_wizard_page_window" in head:
            return _fail(f"{fn} must stay deck-native (no Tk page window)")
        if '"deck"' not in head and "'deck'" not in head:
            return _fail(f"{fn} must return a deck navigation hint")

    print("smoke_audit_flow: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
