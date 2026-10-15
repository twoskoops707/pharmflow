"""Smoke tests: sequence UIs expose non-scrolling footer actions (Tk layout)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_wizard_dir = Path(__file__).resolve().parent
if str(_wizard_dir) not in sys.path:
    sys.path.insert(0, str(_wizard_dir))

import tkinter as tk  # noqa: E402

import wizard_theme as _wizard_theme  # noqa: E402

import setup_wizard as sw  # noqa: E402
from setup_wizard import (  # noqa: E402
    CPharmWizard,
    GroupsPage,
    PerPhoneSequenceEditor,
    SequenceGeneratorPage,
)


def _reset_icon_cache() -> None:
    """Drop process-wide PhotoImage cache so a new ``tk.Tk()`` can re-load icons.

    ``wizard_theme.load_icon`` caches PhotoImage objects bound to the first Tk
    interpreter that created them; when that interpreter is destroyed (test
    teardown) the cached entries become invalid and the *next* test that calls
    ``load_icon`` raises ``image "pyimageN" doesn't exist``. Tests that build a
    ``CPharmWizard`` clear the cache here to keep the suite order-independent.
    """
    cache = getattr(_wizard_theme, "_icon_cache", None)
    if isinstance(cache, dict):
        cache.clear()


def _collect_button_texts(widget: tk.Misc) -> list[str]:
    out: list[str] = []
    for w in widget.winfo_children():
        cls = w.winfo_class()
        if cls == "Button":
            try:
                out.append(str(w.cget("text")))
            except tk.TclError:
                pass
        out.extend(_collect_button_texts(w))
    return out


def _collect_widgets_by_class(widget: tk.Misc, cls_name: str) -> list[tk.Misc]:
    out: list[tk.Misc] = []
    for w in widget.winfo_children():
        if w.winfo_class() == cls_name:
            out.append(w)
        out.extend(_collect_widgets_by_class(w, cls_name))
    return out


class TestSequenceFooterVisibility(unittest.TestCase):
    def test_per_phone_sequence_editor_has_footer_actions(self) -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            ed = PerPhoneSequenceEditor(root, "emu-0", "Test phone", [])
            ed.update_idletasks()
            texts = _collect_button_texts(ed)
            self.assertIn("OK", texts)
            self.assertIn("Cancel", texts)
            self.assertTrue(any(t.startswith("\u2190") or "Back" in t for t in texts))
            self.assertIn("Tryout / Run now", texts)
            canvases = _collect_widgets_by_class(ed, "Canvas")
            self.assertGreaterEqual(len(canvases), 1, "Editor should use a scroll canvas")
            outer = ed.winfo_children()[0]
            self.assertGreaterEqual(len(outer.winfo_children()), 2)
            self.assertTrue(
                any("OK" in _collect_button_texts(ch) for ch in outer.winfo_children()),
                msg="Footer row with OK must be a direct child of the outer layout frame",
            )
            ed.destroy()
        finally:
            root.destroy()

    def test_per_phone_sequence_editor_tryout_routes_to_wizard(self) -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            called = {"count": 0}
            host = tk.Frame(root)
            host.pack()

            class _StubWizard:
                def start_tryout_from_groups(self_nonlocal) -> None:
                    called["count"] += 1

            steps = [{"type": "sleep", "seconds": 1}]
            ent = {"steps": [], "sequence_playlist": [], "sequence_playlist_secondary": []}
            ed = PerPhoneSequenceEditor(host, "emu-0", "Test phone", steps, phone_ent=ent)
            ed._resolve_wizard_shell = lambda: _StubWizard()  # type: ignore[method-assign]
            ed._draft_steps = [{"type": "sleep", "seconds": 2}]
            ed._save_and_tryout()
            self.assertEqual(called["count"], 1)
            self.assertEqual(steps, [{"type": "sleep", "seconds": 2}])
        finally:
            root.destroy()

    def test_sequence_generator_page_footer_slot_has_actions(self) -> None:
        """Footer buttons live under ``footer_parent``, not inside the canvas scroll region."""
        root = tk.Tk()
        root.withdraw()
        try:
            outer = tk.Frame(root, bg="#111")
            outer.pack(fill="both", expand=True)
            canvas_area = tk.Frame(outer)
            canvas_area.pack(fill="both", expand=True)
            canvas = tk.Canvas(canvas_area, highlightthickness=0)
            canvas.pack(fill="both", expand=True)
            footer_slot = tk.Frame(outer)
            footer_slot.pack(side="bottom", fill="x")

            page = SequenceGeneratorPage(canvas, footer_parent=footer_slot)
            page.update_idletasks()

            footer_texts = _collect_button_texts(footer_slot)
            self.assertIn("OK", footer_texts)
            self.assertIn("Cancel", footer_texts)
            self.assertTrue(any("Back" in t or t.startswith("\u2190") for t in footer_texts))

            page_texts = _collect_button_texts(page)
            self.assertNotIn("OK", page_texts, msg="OK should not be inside canvas-embedded page")

            # With withdrawn root, ``winfo_ismapped`` / ``winfo_viewable`` may be false; rely on widget tree.

            # When possible, ensure buttons are not disabled.
            for w in footer_slot.winfo_children():
                for sub in w.winfo_children():
                    if sub.winfo_class() == "Button" and sub.cget("text") == "OK":
                        self.assertEqual(sub.cget("state"), "normal")
            page.destroy()
        finally:
            root.destroy()

    def test_wizard_sequence_step_footer_is_outside_canvas(self) -> None:
        _reset_icon_cache()
        root = tk.Tk()
        root.withdraw()
        try:
            wiz = CPharmWizard(root)
            wiz.update_idletasks()
            seq_index = wiz.PAGES.index(SequenceGeneratorPage)
            seq_outer, _seq_canvas = wiz._page_wrappers[seq_index]  # internal layout contract
            seq_children = seq_outer.winfo_children()
            self.assertGreaterEqual(
                len(seq_children), 2, "Sequence step should have canvas area + footer slot"
            )
            footer_slot = seq_children[-1]
            footer_texts = _collect_button_texts(footer_slot)
            self.assertIn("OK", footer_texts)
            self.assertIn("Cancel", footer_texts)
            self.assertTrue(any("Back" in t or t.startswith("\u2190") for t in footer_texts))
            wiz.destroy()
        finally:
            root.destroy()

    def test_wizard_groups_step_has_tryout_button_in_global_footer(self) -> None:
        """Tryout button lives in the wizard's non-scrolling footer slot, not inside the page canvas."""
        _reset_icon_cache()
        root = tk.Tk()
        root.withdraw()
        try:
            wiz = CPharmWizard(root)
            wiz.update_idletasks()
            groups_index = wiz.PAGES.index(GroupsPage)
            wiz._show(groups_index)
            wiz.update_idletasks()

            slot = wiz._footer_page_actions  # internal layout contract
            footer_texts = _collect_button_texts(slot)
            self.assertIn("Tryout / Run playlist now", footer_texts)

            # Button must not be inside the GroupsPage canvas-embedded scroll area.
            groups_page = wiz._pages[groups_index]
            self.assertNotIn(
                "Tryout / Run playlist now",
                _collect_button_texts(groups_page),
                msg="Tryout button must live in the non-scrolling footer, not the scrolled page",
            )

            # Switching pages clears the slot so the button does not bleed into other steps.
            launch_index = wiz.PAGES.index(sw.LaunchPage)
            wiz._show(launch_index)
            wiz.update_idletasks()
            self.assertNotIn(
                "Tryout / Run playlist now",
                _collect_button_texts(slot),
                msg="Footer page actions must reset when leaving the Groups step",
            )
            wiz.destroy()
        finally:
            root.destroy()

    def test_open_setup_guide_uses_url_fallback_when_local_missing(self) -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                old_state = dict(sw.state)
                old_open = sw.webbrowser.open
                old_showinfo = sw.messagebox.showinfo
                old_showerror = sw.messagebox.showerror
                old_roots = sw._cpharm_search_roots_ordered
                old_install = sw._cpharm_install_root
                old_startfile = getattr(sw.os, "startfile", None)
                called: dict[str, str] = {}
                try:
                    sw.state["cpharm_dir"] = str(tmp_path)
                    sw._cpharm_search_roots_ordered = lambda: [tmp_path]
                    sw._cpharm_install_root = lambda: tmp_path
                    # Windows tries ``os.startfile(https…)`` before ``webbrowser``; force the browser path
                    # so this test stays deterministic on all platforms.
                    if old_startfile is not None:
                        sw.os.startfile = lambda *_a, **_k: (_ for _ in ()).throw(OSError("test skip startfile"))  # type: ignore[attr-defined]
                    sw.webbrowser.open = lambda url, new=0, autoraise=True: called.setdefault("url", url) or True
                    sw.messagebox.showinfo = lambda *a, **k: called.setdefault("info", "1")
                    sw.messagebox.showerror = lambda *a, **k: called.setdefault("error", "1")
                    sw._open_setup_guide_doc()
                finally:
                    sw.state.clear()
                    sw.state.update(old_state)
                    sw.webbrowser.open = old_open
                    sw.messagebox.showinfo = old_showinfo
                    sw.messagebox.showerror = old_showerror
                    sw._cpharm_search_roots_ordered = old_roots
                    sw._cpharm_install_root = old_install
                    if old_startfile is not None:
                        sw.os.startfile = old_startfile  # type: ignore[attr-defined]
                self.assertIn("url", called)
                self.assertIn("github", called["url"].lower())
                self.assertIn("info", called)
        finally:
            root.destroy()

    def test_groups_add_group_initializes_playlist_per_phone(self) -> None:
        _reset_icon_cache()
        root = tk.Tk()
        root.withdraw()
        try:
            old_state = dict(sw.state)
            try:
                sw.state["phones"] = [
                    {"serial": "emu-1", "name": "Phone 1"},
                    {"serial": "emu-2", "name": "Phone 2"},
                ]
                sw.state["groups"] = []
                sw.state["default_steps"] = []
                page = GroupsPage(root)
                page._add_group()
                phone_map = sw.state["groups"][0]["phones"]
                self.assertIn("emu-1", phone_map)
                self.assertIn("emu-2", phone_map)
                for serial in ("emu-1", "emu-2"):
                    ent = phone_map[serial]
                    self.assertIn("sequence_playlist", ent)
                    self.assertIn("sequence_playlist_secondary", ent)
                    self.assertEqual(ent.get("sequence_playlist_mode"), "series")
                    self.assertEqual(ent.get("sequence_playlist_shuffle"), "none")
                page.destroy()
            finally:
                sw.state.clear()
                sw.state.update(old_state)
        finally:
            root.destroy()
