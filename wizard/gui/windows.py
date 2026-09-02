"""Sub-window management — phone details, settings, fingerprint status."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Any, Callable

import customtkinter as ctk

from wizard.gui.path_selector import PathSelectorWindow
from wizard.gui.styles import (
    BG,
    FONT_BODY,
    FONT_MONO,
    FONT_TITLE,
    SURFACE,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WIN_FINGERPRINT,
    WIN_PHONE_DETAIL,
    WIN_SETTINGS,
)
from wizard.gui.widgets import GradientButton, LogPanel, ScrollPanel, StatusCard
from wizard.path_utils import apply_adb_path, apply_mumu_path, apply_tor_path
from wizard.path_store import PROGRAM_ADB, PROGRAM_MUMU, PROGRAM_TOR
from wizard.site_llm import save_llm_settings


class SubWindow(ctk.CTkToplevel):
    """Base sub-window — centered, scrollable, proper sizing."""

    def __init__(self, parent: tk.Misc, title: str, size: tuple[int, int]) -> None:
        super().__init__(parent)
        self.title(title)
        self.configure(fg_color=BG)
        w, h = size
        self.geometry(f"{w}x{h}")
        self.minsize(min(w, 600), min(h, 500))
        self.transient(parent)  # type: ignore[arg-type]
        self._center_on(parent, w, h)
        self.content = ctk.CTkFrame(self, fg_color=BG)
        self.content.pack(fill="both", expand=True, padx=16, pady=16)

    def _center_on(self, parent: tk.Misc, w: int, h: int) -> None:
        self.update_idletasks()
        try:
            px = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
            py = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
            self.geometry(f"+{max(0, px)}+{max(0, py)}")
        except tk.TclError:
            pass


class PhoneDetailsWindow(SubWindow):
    def __init__(self, parent: tk.Misc, phone_name: str, status: dict[str, Any]) -> None:
        super().__init__(parent, f"Phone Details — {phone_name}", WIN_PHONE_DETAIL)
        ctk.CTkLabel(self.content, text=phone_name, font=FONT_TITLE, text_color=TEXT_PRIMARY).pack(anchor="w")
        scroll = ScrollPanel(self.content, height=500)
        scroll.pack(fill="both", expand=True, pady=12)
        for key, val in status.items():
            row = ctk.CTkFrame(scroll.inner, fg_color=SURFACE, corner_radius=6)
            row.pack(fill="x", pady=3, padx=4)
            ctk.CTkLabel(row, text=str(key), font=FONT_BODY, text_color=TEXT_SECONDARY, width=140, anchor="w").pack(
                side="left", padx=8, pady=6,
            )
            ctk.CTkLabel(row, text=str(val), font=FONT_BODY, text_color=TEXT_PRIMARY, wraplength=360, justify="left").pack(
                side="left", padx=8, pady=6,
            )
        GradientButton(self.content, "CLOSE", command=self.destroy, width=160).pack(pady=8)


class SettingsWindow(SubWindow):
    def __init__(
        self,
        parent: tk.Misc,
        on_save: Callable[[dict[str, Any]], None],
        initial: dict[str, Any],
    ) -> None:
        super().__init__(parent, "Settings", WIN_SETTINGS)
        self.tabs = ctk.CTkTabview(self.content)
        self.tabs.pack(fill="both", expand=True)
        general = self.tabs.add("General")
        privacy = self.tabs.add("Privacy")
        assist = self.tabs.add("Assist")

        ctk.CTkLabel(general, text="MuMu folder", font=FONT_BODY).pack(anchor="w", pady=(8, 0))
        mumu_row = ctk.CTkFrame(general, fg_color="transparent")
        mumu_row.pack(fill="x", pady=4)
        self.mumu_path = ctk.CTkEntry(mumu_row, width=320)
        self.mumu_path.pack(side="left", padx=(0, 8))
        self.mumu_path.insert(0, initial.get("mumu_root", ""))
        GradientButton(mumu_row, "BROWSE", command=self._browse_mumu, width=100).pack(side="left")

        ctk.CTkLabel(general, text="Tor (tor.exe)", font=FONT_BODY).pack(anchor="w", pady=(12, 0))
        tor_row = ctk.CTkFrame(general, fg_color="transparent")
        tor_row.pack(fill="x", pady=4)
        self.tor_path = ctk.CTkEntry(tor_row, width=320)
        self.tor_path.pack(side="left", padx=(0, 8))
        self.tor_path.insert(0, initial.get("tor_path", ""))
        GradientButton(tor_row, "BROWSE", command=self._browse_tor, width=100).pack(side="left")

        ctk.CTkLabel(general, text="ADB (adb.exe)", font=FONT_BODY).pack(anchor="w", pady=(12, 0))
        adb_row = ctk.CTkFrame(general, fg_color="transparent")
        adb_row.pack(fill="x", pady=4)
        self.adb_path = ctk.CTkEntry(adb_row, width=320)
        self.adb_path.pack(side="left", padx=(0, 8))
        self.adb_path.insert(0, initial.get("adb_path", ""))
        GradientButton(adb_row, "BROWSE", command=self._browse_adb, width=100).pack(side="left")

        self.skip_fp = ctk.CTkSwitch(general, text="Skip fingerprint (CPHARM_SKIP_FINGERPRINT)")
        self.skip_fp.pack(anchor="w", pady=8)
        if initial.get("skip_fingerprint"):
            self.skip_fp.select()

        self.legacy_proxy = ctk.CTkSwitch(general, text="Legacy proxy gateway (10.0.2.2)")
        self.legacy_proxy.pack(anchor="w", pady=4)
        if initial.get("legacy_proxy"):
            self.legacy_proxy.select()

        ctk.CTkLabel(privacy, text="Anti-detection uses 6 layers:", font=FONT_BODY, wraplength=500, justify="left").pack(
            anchor="w", pady=8,
        )
        for layer in (
            "1. Browser UA + headers (chrome-command-line, per-phone getprop)",
            "2. Session scramble (android_id + UA each sequence)",
            "3. Browse proxy scramble (direct internet for ad networks)",
            "4. Optional site CDP patch when a profile enables it",
            "5. Tor network identity (optional per phone)",
            "6. Runtime header verification",
        ):
            ctk.CTkLabel(privacy, text=f"  {layer}", font=FONT_BODY, text_color=TEXT_SECONDARY).pack(anchor="w")

        ctk.CTkLabel(
            assist,
            text="Optional AI for Site Interview (OpenAI-compatible). Offline Q&A always works without this.",
            font=FONT_BODY,
            wraplength=500,
            justify="left",
        ).pack(anchor="w", pady=8)
        ctk.CTkLabel(assist, text="API key", font=FONT_BODY).pack(anchor="w", pady=(8, 0))
        self.llm_key = ctk.CTkEntry(assist, width=420, show="*")
        self.llm_key.pack(anchor="w", pady=4)
        self.llm_key.insert(0, str(initial.get("llm_api_key") or ""))
        ctk.CTkLabel(assist, text="Base URL", font=FONT_BODY).pack(anchor="w", pady=(8, 0))
        self.llm_base = ctk.CTkEntry(assist, width=420)
        self.llm_base.pack(anchor="w", pady=4)
        self.llm_base.insert(0, str(initial.get("llm_base_url") or "https://api.openai.com/v1"))
        ctk.CTkLabel(assist, text="Model", font=FONT_BODY).pack(anchor="w", pady=(8, 0))
        self.llm_model = ctk.CTkEntry(assist, width=420)
        self.llm_model.pack(anchor="w", pady=4)
        self.llm_model.insert(0, str(initial.get("llm_model") or "gpt-4o-mini"))

        self._on_save = on_save
        GradientButton(self.content, "APPLY", command=self._save, width=160).pack(pady=8)

    def _browse_mumu(self) -> None:
        selector = PathSelectorWindow(self, PROGRAM_MUMU, current_path=self.mumu_path.get())
        chosen = selector.get_result()
        if chosen:
            result = apply_mumu_path(chosen)
            if result.found:
                self.mumu_path.delete(0, "end")
                self.mumu_path.insert(0, result.path)
            else:
                messagebox.showwarning("Invalid Path", result.detail, parent=self)

    def _browse_tor(self) -> None:
        selector = PathSelectorWindow(self, PROGRAM_TOR, current_path=self.tor_path.get())
        chosen = selector.get_result()
        if chosen:
            result = apply_tor_path(chosen)
            if result.found:
                self.tor_path.delete(0, "end")
                self.tor_path.insert(0, result.path)
            else:
                messagebox.showwarning("Invalid Path", result.detail, parent=self)

    def _browse_adb(self) -> None:
        selector = PathSelectorWindow(self, PROGRAM_ADB, current_path=self.adb_path.get())
        chosen = selector.get_result()
        if chosen:
            result = apply_adb_path(chosen)
            if result.found:
                self.adb_path.delete(0, "end")
                self.adb_path.insert(0, result.path)
            else:
                messagebox.showwarning("Invalid Path", result.detail, parent=self)

    def _save(self) -> None:
        mumu = self.mumu_path.get().strip()
        tor = self.tor_path.get().strip()
        adb = self.adb_path.get().strip()
        if mumu:
            result = apply_mumu_path(mumu)
            if not result.found:
                messagebox.showwarning("Invalid Path", result.detail, parent=self)
                return
            mumu = result.path
        if tor:
            result = apply_tor_path(tor)
            if not result.found:
                messagebox.showwarning("Invalid Path", result.detail, parent=self)
                return
            tor = result.path
        if adb:
            result = apply_adb_path(adb)
            if not result.found:
                messagebox.showwarning("Invalid Path", result.detail, parent=self)
                return
            adb = result.path
        self._on_save({
            "mumu_root": mumu,
            "tor_path": tor,
            "adb_path": adb,
            "skip_fingerprint": bool(self.skip_fp.get()),
            "legacy_proxy": bool(self.legacy_proxy.get()),
        })
        save_llm_settings(
            api_key=self.llm_key.get(),
            base_url=self.llm_base.get(),
            model=self.llm_model.get(),
        )
        self.destroy()


class FingerprintStatusWindow(SubWindow):
    def __init__(
        self,
        parent: tk.Misc,
        reports: list[dict[str, Any]],
        on_verify_all: Callable[[], None],
        on_reapply: Callable[[str], None],
    ) -> None:
        super().__init__(parent, "Privacy Status — Anti-Detection", WIN_FINGERPRINT)
        toolbar = ctk.CTkFrame(self.content, fg_color="transparent")
        toolbar.pack(fill="x", pady=(0, 8))
        GradientButton(toolbar, "VERIFY ALL", icon="shield", command=on_verify_all, width=160).pack(side="left", padx=4)

        scroll = ScrollPanel(self.content, height=420)
        scroll.pack(fill="both", expand=True)
        self._scroll = scroll

        for report in reports:
            self._add_report_card(scroll.inner, report, on_reapply)

    def _add_report_card(self, parent: tk.Misc, report: dict[str, Any], on_reapply: Callable[[str], None]) -> None:
        phone = report.get("phone", "?")
        passed = report.get("passed", False)
        card = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=10)
        card.pack(fill="x", pady=6, padx=4)
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=8)
        ctk.CTkLabel(header, text=phone, font=FONT_BODY, text_color=TEXT_PRIMARY).pack(side="left")
        ctk.CTkLabel(
            header, text="PROTECTED" if passed else "NEEDS FIX",
            text_color=TEXT_PRIMARY,
        ).pack(side="right")
        for check, ok in report.get("checks", {}).items():
            StatusCard(card, check.replace("_", " ").title(), ok).pack(fill="x", padx=8, pady=2)
        props = report.get("props", {})
        if props:
            log = LogPanel(card, height=100)
            log.pack(fill="x", padx=8, pady=4)
            for k, v in props.items():
                log.append(f"{k} = {v}")
        GradientButton(card, "RE-APPLY FINGERPRINT", command=lambda p=phone: on_reapply(p), width=220).pack(pady=8)

    def refresh_reports(self, reports: list[dict[str, Any]], on_reapply: Callable[[str], None]) -> None:
        for w in self._scroll.inner.winfo_children():
            w.destroy()
        for report in reports:
            self._add_report_card(self._scroll.inner, report, on_reapply)
