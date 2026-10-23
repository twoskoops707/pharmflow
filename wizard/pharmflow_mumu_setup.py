"""
Phone setup runs in-process inside PharmFlow.exe (there is no separate setup EXE).

Primary UI: pywebview (WebView2) with modern HTML/CSS frontend.
Fallback: tkinter when pywebview is unavailable.

Build: pyinstaller PharmFlow.spec (see .github/workflows/build-wizard.yml)
"""

from __future__ import annotations

import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext

_wizard_dir = Path(__file__).resolve().parent
if str(_wizard_dir) not in sys.path:
    sys.path.insert(0, str(_wizard_dir))

import mumu_setup_core as core  # noqa: E402
from wizard_theme import (  # noqa: E402
    BG,
    BG2,
    GREEN,
    GREEN_ACTIVE,
    ON_ACCENT,
    T1,
    T2,
    T3,
    _style_scrollbars,
    style_primary_button,
)


class MuMuSetupTkFallback(tk.Tk):
    """Classic tkinter UI when WebView2 / pywebview is not available."""

    def __init__(self, *, skip_launch_pharmflow: bool = False) -> None:
        super().__init__()
        self._skip_launch_pharmflow = skip_launch_pharmflow
        self.title("PharmFlow — Phone Setup")
        self.configure(bg=BG)
        self.minsize(640, 520)
        self.geometry("720x580")

        tk.Label(
            self,
            text="PharmFlow Phone Setup",
            font=("Segoe UI", 22, "bold"),
            bg=BG,
            fg=T1,
        ).pack(pady=(20, 4))
        tk.Label(
            self,
            text=(
                "Step-by-step checklist is in the main window.\n"
                "Short version: MuMu open → phones started → USB debugging ON → GO."
            ),
            font=("Segoe UI", 10),
            bg=BG,
            fg=T3,
            justify="center",
        ).pack(pady=(0, 12))

        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(pady=(0, 12))
        self._go_btn = tk.Button(
            btn_row,
            text=core.go_button_label(),
            font=("Segoe UI", 14, "bold"),
            bg=GREEN,
            fg=ON_ACCENT,
            relief="flat",
            cursor="hand2",
            command=self._on_go,
            padx=16,
            pady=10,
        )
        self._go_btn.configure(activebackground=GREEN_ACTIVE, activeforeground=ON_ACCENT)
        style_primary_button(self._go_btn)
        self._go_btn.pack(side="left", padx=6)

        self._chrome_btn = tk.Button(
            btn_row,
            text="Install Chromium on all phones",
            font=("Segoe UI", 11, "bold"),
            bg=BG2,
            fg=GREEN,
            relief="flat",
            cursor="hand2",
            command=self._on_install_chromium,
            padx=12,
            pady=8,
        )
        self._chrome_btn.pack(side="left", padx=6)

        self._pharmflow_only_btn = tk.Button(
            btn_row,
            text="Open PharmFlow only",
            font=("Segoe UI", 10),
            bg=BG2,
            fg=T1,
            relief="flat",
            cursor="hand2",
            command=self._launch_pharmflow,
            padx=12,
            pady=8,
        )
        self._pharmflow_only_btn.pack(side="left", padx=6)

        log_frame = tk.Frame(self, bg=BG)
        log_frame.pack(fill="both", expand=True, padx=20, pady=(4, 20))
        self._log = scrolledtext.ScrolledText(
            log_frame,
            height=16,
            font=("Consolas", 10),
            bg=BG2,
            fg=T1,
            relief="flat",
            wrap="word",
            state="disabled",
        )
        self._log.pack(fill="both", expand=True)
        _style_scrollbars(self)

        if not core.pharmflow_exe_path().is_file():
            self._log_write(
                f"Note: PharmFlow.exe not found:\n  {core.pharmflow_exe_path()}\n"
                "Download both exes from GitHub Releases into the same folder.\n\n"
            )

    def _log_write(self, msg: str) -> None:
        self._log.configure(state="normal")
        self._log.insert("end", msg + ("\n" if not msg.endswith("\n") else ""))
        self._log.see("end")
        self._log.configure(state="disabled")

    def _launch_pharmflow(self) -> None:
        if self._skip_launch_pharmflow:
            self._log_write("\nSetup complete — return to the main PharmFlow window.\n")
            messagebox.showinfo(
                "Phone Setup",
                "Setup complete.\n\nReturn to the main PharmFlow window to continue.",
            )
            return
        ok, msg = core.launch_pharmflow()
        if not ok:
            messagebox.showerror("PharmFlow.exe missing", msg)
            return
        self._log_write(f"\nOpened: {msg}\n")

    def _on_install_chromium(self) -> None:
        self._go_btn.config(state="disabled")
        self._chrome_btn.config(state="disabled", text="Installing…")
        self._pharmflow_only_btn.config(state="disabled")

        def work() -> None:
            result = core.run_install_chromium(lambda m: self.after(0, lambda t=m: self._log_write(t)))

            def done() -> None:
                self._go_btn.config(state="normal")
                self._chrome_btn.config(state="normal", text="Install Chromium on all phones")
                self._pharmflow_only_btn.config(state="normal")
                msg = result.get("message") or "Done."
                self._log_write(f"\n{msg}\n")
                if not result.get("ok"):
                    messagebox.showwarning("Install Chromium", msg)

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _on_go(self) -> None:
        self._go_btn.config(state="disabled", text="Working…")
        if getattr(self, "_chrome_btn", None):
            self._chrome_btn.config(state="disabled")
        self._pharmflow_only_btn.config(state="disabled")

        def work() -> None:
            ready, msg, _ = core.run_full_setup(lambda m: self.after(0, lambda t=m: self._log_write(t)))

            def done() -> None:
                self._go_btn.config(state="normal", text=core.go_button_label())
                if getattr(self, "_chrome_btn", None):
                    self._chrome_btn.config(state="normal")
                self._pharmflow_only_btn.config(state="normal")
                self._log_write(f"\n{msg}\n")
                if ready:
                    if core.pharmflow_exe_path().is_file():
                        self._launch_pharmflow()
                    else:
                        messagebox.showinfo(
                            "Setup done",
                            msg + "\n\nDownload PharmFlow.exe into the same folder, then double-click it.",
                        )
                else:
                    title = (
                        "Phone Setup — wait for reboot"
                        if "cold-boot" in (msg or "").lower() or "STOP" in (msg or "")
                        else "Phone Setup"
                    )
                    messagebox.showwarning(title, msg)

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()


def main() -> None:
    from phone_setup_entry import phone_setup_main

    phone_setup_main()


if __name__ == "__main__":
    main()
