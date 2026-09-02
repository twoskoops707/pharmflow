"""Manual path selector popup — browse for executable or install folder."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from wizard.gui.styles import BG, FONT_BODY, FONT_SMALL, FONT_TITLE, SUCCESS, TEXT_PRIMARY, TEXT_SECONDARY
from wizard.gui.widgets import GradientButton
from wizard.path_store import load_saved_paths, remember_path


class PathSelectorWindow(ctk.CTkToplevel):
    """Popup for manually selecting program paths with saved history."""

    def __init__(self, parent: tk.Misc, program_name: str, current_path: str | None = None) -> None:
        super().__init__(parent)
        self.title(f"Select {program_name}")
        self.configure(fg_color=BG)
        self.geometry("520x420")
        self.resizable(False, False)
        self.transient(parent)  # type: ignore[arg-type]
        self._center_on(parent, 520, 420)

        self.program_name = program_name
        self.selected_path: str | None = None
        self.saved_paths = load_saved_paths()

        self.content = ctk.CTkFrame(self, fg_color=BG)
        self.content.pack(fill="both", expand=True, padx=16, pady=16)
        self._build_ui(current_path)

    def _center_on(self, parent: tk.Misc, w: int, h: int) -> None:
        self.update_idletasks()
        try:
            px = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
            py = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
            self.geometry(f"+{max(0, px)}+{max(0, py)}")
        except tk.TclError:
            pass

    def _build_ui(self, current_path: str | None) -> None:
        ctk.CTkLabel(
            self.content,
            text=f"{self.program_name} Location",
            font=FONT_TITLE,
            text_color=TEXT_PRIMARY,
        ).pack(pady=(8, 4))
        ctk.CTkLabel(
            self.content,
            text="Browse for the executable or installation folder",
            font=FONT_SMALL,
            text_color=TEXT_SECONDARY,
        ).pack(pady=(0, 12))

        ctk.CTkLabel(self.content, text="Current location", font=FONT_BODY, text_color=TEXT_SECONDARY).pack(anchor="w")
        self.path_var = tk.StringVar(value=current_path or "Not set")
        self.path_entry = ctk.CTkEntry(self.content, textvariable=self.path_var, width=460)
        self.path_entry.pack(fill="x", pady=6)

        btn_row = ctk.CTkFrame(self.content, fg_color="transparent")
        btn_row.pack(pady=12)
        GradientButton(btn_row, "BROWSE .EXE", icon="computer", command=self._browse_executable, width=150).pack(
            side="left", padx=6
        )
        GradientButton(btn_row, "BROWSE FOLDER", icon="download", command=self._browse_folder, width=170).pack(
            side="left", padx=6
        )

        saved = self.saved_paths.get(self.program_name, [])
        if saved:
            ctk.CTkLabel(
                self.content,
                text="Previously saved",
                font=FONT_BODY,
                text_color=TEXT_SECONDARY,
            ).pack(anchor="w", pady=(8, 4))
            self.saved_combo = ctk.CTkComboBox(self.content, values=list(reversed(saved)), width=440)
            self.saved_combo.set(saved[-1])
            self.saved_combo.pack(pady=4)
            GradientButton(self.content, "USE SELECTED", command=self._use_saved, width=160).pack(pady=6)

        action = ctk.CTkFrame(self.content, fg_color="transparent")
        action.pack(side="bottom", pady=16)
        GradientButton(action, "CANCEL", command=self.destroy, width=120).pack(side="left", padx=8)
        GradientButton(action, "SAVE & USE", icon="checkmark", command=self._save_and_use, color=SUCCESS, width=140).pack(
            side="left", padx=8
        )

        self.grab_set()
        self.focus_force()

    def _browse_executable(self) -> None:
        filename = filedialog.askopenfilename(
            parent=self,
            title=f"Select {self.program_name} executable",
            filetypes=[("Executable files", "*.exe"), ("All files", "*.*")],
        )
        if filename:
            self.path_var.set(filename)

    def _browse_folder(self) -> None:
        foldername = filedialog.askdirectory(parent=self, title=f"Select {self.program_name} folder")
        if foldername:
            self.path_var.set(foldername)

    def _use_saved(self) -> None:
        if hasattr(self, "saved_combo"):
            self.path_var.set(self.saved_combo.get())

    def _save_and_use(self) -> None:
        path = self.path_var.get().strip()
        if not path or path == "Not set":
            messagebox.showwarning("No Path", "Please select a path first.", parent=self)
            return
        remember_path(self.program_name, path)
        self.selected_path = path
        self.destroy()

    def get_result(self) -> str | None:
        self.wait_window()
        return self.selected_path
