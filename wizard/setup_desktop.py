"""CPharm integrated first-run setup — runs inside the single CPharm.exe wizard."""

from __future__ import annotations

import logging
import threading
import webbrowser
from collections.abc import Callable

import customtkinter as ctk

from wizard.gui.styles import FONT_BODY, FONT_SMALL, SUCCESS, TEXT_MUTED, TEXT_PRIMARY
from wizard.gui.widgets import GradientButton, LogPanel
from wizard.mumu_setup_core import MuMuSetupCore
from wizard.preflight_core import CheckStatus, run_preflight
from wizard.path_detection import (
    auto_detect_adb,
    auto_detect_mumu,
    auto_detect_tor,
    detect_with_fallback,
)
from wizard.path_store import PROGRAM_ADB, PROGRAM_MUMU, PROGRAM_TOR
from wizard.ui_helpers import ScreenFrame, WizardShell, friendly_error, load_icon
from wizard.wizard_paths import logs_dir, save_config

logger = logging.getLogger(__name__)

ctk.set_appearance_mode("dark")


class IntegratedSetupWizard(WizardShell):
    """First-run setup screens — transitions to main app via on_complete callback."""

    def __init__(self, on_complete: Callable[[], None] | None = None) -> None:
        super().__init__("PharmFlow — First Run Setup")
        self.on_complete = on_complete
        self.core = MuMuSetupCore()
        self.phone_count = 1
        self._setup_started = False
        self._build_screens()
        self.show_screen("welcome")

    def _build_screens(self) -> None:
        self._screen_welcome()
        self._screen_checklist()
        self._screen_check_mumu()
        self._screen_create_phones()
        self._screen_usb_debug()
        self._screen_setup()
        self._screen_done()

    def _screen_welcome(self) -> None:
        s = ScreenFrame(
            self._container,
            "PharmFlow",
            "We will set up your phone farm for you. Just click the button.",
        )
        icon = load_icon("phone", 64)
        if icon:
            ctk.CTkLabel(s.content, image=icon, text="").pack(pady=30)
        GradientButton(
            s.content,
            "Set everything up",
            icon="start",
            command=lambda: self.show_screen("checklist"),
            color=SUCCESS,
        ).pack(pady=20)
        self.register_screen("welcome", s)

    def _screen_checklist(self) -> None:
        s = ScreenFrame(self._container, "Quick check", "We look for the apps you need. You only click Continue.")
        self.checklist_frame = ctk.CTkScrollableFrame(s.content, height=360)
        self.checklist_frame.pack(fill="both", expand=True, pady=10)
        GradientButton(
            s.content,
            "Continue",
            icon="checkmark",
            command=lambda: self.show_screen("check_mumu"),
            color=SUCCESS,
        ).pack(pady=12)
        # Locate tools only if auto-detect failed — keep off the happy path.
        tools = ctk.CTkFrame(s.content, fg_color="transparent")
        tools.pack(pady=4)
        ctk.CTkLabel(
            tools,
            text="If something is missing, use these:",
            font=FONT_SMALL,
            text_color=TEXT_MUTED,
        ).pack(pady=(0, 6))
        GradientButton(tools, "Find Tor", icon="network", command=self._locate_tor, width=140).pack(side="left", padx=6)
        GradientButton(tools, "Find phone tools", icon="computer", command=self._locate_adb, width=160).pack(
            side="left", padx=6
        )
        self.register_screen("checklist", s)
        self._refresh_checklist()

    def _refresh_checklist(self) -> None:
        for w in self.checklist_frame.winfo_children():
            w.destroy()
        report = run_preflight()
        for item in report.items:
            color = SUCCESS if item.status == CheckStatus.PASS else TEXT_MUTED
            if item.status == CheckStatus.WARN:
                color = "#F59E0B"
            row = ctk.CTkFrame(self.checklist_frame, fg_color="transparent")
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=item.friendly_label, font=FONT_BODY, text_color=TEXT_PRIMARY, anchor="w").pack(
                side="left", fill="x", expand=True
            )
            ctk.CTkLabel(row, text=item.status.value.upper(), font=FONT_BODY, text_color=color).pack(side="right")

    def _screen_check_mumu(self) -> None:
        s = ScreenFrame(
            self._container,
            "Phone software (MuMu)",
            "We look for MuMu Player. If it is missing, download it once.",
        )
        self.mumu_status = ctk.CTkLabel(s.content, text="Looking…", font=FONT_BODY, text_color=TEXT_MUTED)
        self.mumu_status.pack(pady=20)
        btn_frame = ctk.CTkFrame(s.content, fg_color="transparent")
        btn_frame.pack(pady=20)
        GradientButton(btn_frame, "Check again", icon="refresh", command=self._check_mumu).pack(pady=8)
        GradientButton(btn_frame, "Find MuMu folder…", icon="computer", command=self._locate_mumu, width=200).pack(
            pady=8
        )
        GradientButton(
            btn_frame,
            "MuMu is ready — continue",
            icon="checkmark",
            command=lambda: self.show_screen("create_phones"),
            color=SUCCESS,
        ).pack(pady=8)
        GradientButton(btn_frame, "Download MuMu", icon="download", command=self._open_mumu_download).pack(pady=8)
        self.register_screen("check_mumu", s)
        self._check_mumu()

    def _check_mumu(self) -> None:
        result = detect_with_fallback(self, PROGRAM_MUMU, auto_detect_mumu, allow_manual=False)
        if result.found:
            self.mumu_status.configure(
                text=f"Found MuMu.\n{result.path}",
                text_color=SUCCESS,
            )
            self.core.detect_and_save_mumu()
            # Auto-advance when found — fewer clicks.
            self.after(400, lambda: self.show_screen("create_phones"))
        else:
            self.mumu_status.configure(
                text="MuMu was not found.\nClick Download MuMu, install it, then Check again.\nOr click Find MuMu folder…",
                text_color=TEXT_MUTED,
            )

    def _locate_mumu(self) -> None:
        result = detect_with_fallback(self, PROGRAM_MUMU, auto_detect_mumu)
        if result.found:
            self.mumu_status.configure(
                text=f"Found MuMu at:\n{result.path}\n(manual)",
                text_color=SUCCESS,
            )
            self.core.detect_and_save_mumu()
            self._refresh_checklist()

    def _locate_tor(self) -> None:
        detect_with_fallback(self, PROGRAM_TOR, auto_detect_tor)
        self._refresh_checklist()

    def _locate_adb(self) -> None:
        detect_with_fallback(self, PROGRAM_ADB, auto_detect_adb)
        self._refresh_checklist()

    def _open_mumu_download(self) -> None:
        webbrowser.open("https://www.mumuglobal.com")

    def _screen_create_phones(self) -> None:
        s = ScreenFrame(self._container, "How many phones?", "Pick a number. We create them for you.")
        btn_frame = ctk.CTkFrame(s.content, fg_color="transparent")
        btn_frame.pack(pady=20)
        for n in (1, 3, 5, 10):
            ctk.CTkButton(
                btn_frame,
                text=str(n),
                width=80,
                height=80,
                font=("Segoe UI", 24, "bold"),
                command=lambda x=n: self._select_count(x),
            ).pack(side="left", padx=12)
        self.count_label = ctk.CTkLabel(s.content, text="Selected: 1 phone", font=FONT_BODY)
        self.count_label.pack(pady=10)
        GradientButton(
            s.content,
            "Next",
            icon="phone",
            command=lambda: self.show_screen("usb_debug"),
            color=SUCCESS,
        ).pack(pady=20)
        self.register_screen("create_phones", s)

    def _select_count(self, n: int) -> None:
        self.phone_count = n
        self.count_label.configure(text=f"Selected: {n} phone{'s' if n > 1 else ''}")

    def _screen_usb_debug(self) -> None:
        s = ScreenFrame(
            self._container,
            "One phone setting",
            "Do this once inside MuMu, then click Continue. We handle the rest.",
        )
        scroll = ctk.CTkScrollableFrame(s.content, height=280)
        scroll.pack(fill="both", expand=True, pady=10)
        steps = (
            "1. Open MuMu on this computer\n\n"
            "2. Open Settings → About phone\n\n"
            "3. Tap Build number seven times\n\n"
            "4. Go back → Developer options → turn on USB debugging"
        )
        ctk.CTkLabel(
            scroll, text=steps, font=FONT_BODY, text_color=TEXT_PRIMARY, justify="left", wraplength=520
        ).pack(pady=20, padx=20)
        GradientButton(
            s.content,
            "I did that — continue",
            icon="checkmark",
            command=lambda: self.show_screen("setup"),
            color=SUCCESS,
        ).pack(pady=12)
        self.register_screen("usb_debug", s)

    def _screen_setup(self) -> None:
        s = ScreenFrame(
            self._container,
            "Setting up…",
            "Sit tight. We install tools, create phones, and get them ready.",
        )
        self.setup_progress = ctk.CTkProgressBar(s.content, width=500)
        self.setup_progress.pack(pady=10)
        self.setup_progress.set(0)
        self.setup_status = ctk.CTkLabel(s.content, text="Starting…", font=FONT_BODY, text_color=TEXT_MUTED)
        self.setup_status.pack(pady=8)
        self.setup_log = LogPanel(s.content, height=220)
        self.setup_log.pack(fill="both", expand=True, pady=10)
        # Auto-run — no extra GO click required.
        self.register_screen("setup", s)
        self.after(300, self._run_setup)

    def _screen_done(self) -> None:
        s = ScreenFrame(self._container, "Ready!", "Your phone farm is set up. Open the main app to start.")
        icon = load_icon("checkmark", 64)
        if icon:
            ctk.CTkLabel(s.content, image=icon, text="").pack(pady=30)
        GradientButton(
            s.content,
            "Open phone farm",
            icon="start",
            command=self._finish_setup,
            color=SUCCESS,
        ).pack(pady=12)
        self.register_screen("done", s)

    def _finish_setup(self) -> None:
        self.destroy()
        if self.on_complete:
            self.on_complete()
        else:
            from wizard.cpharm_desktop import launch_main_app

            launch_main_app()

    def _run_setup(self) -> None:
        if self._setup_started:
            return
        self._setup_started = True
        threading.Thread(target=self._setup_worker, daemon=True).start()

    def _setup_worker(self) -> None:
        steps: list[tuple[str, Callable[[], None]]] = [
            ("Installing phone tools…", self.core.download_adb),
            ("Installing browser on phones…", self.core.download_browser),
            ("Creating your phones…", self.core.create_all_phones),
            ("Making each phone look unique…", self.core.apply_fingerprints_all),
            ("Starting phones…", self.core.start_all_phones),
            ("Setting up private network…", self.core.setup_tor_all),
        ]
        self.setup_log.clear()
        self.core.phone_count = self.phone_count
        for i, (msg, fn) in enumerate(steps):
            self.after(0, lambda m=msg: self.setup_status.configure(text=m))
            self.after(0, lambda m=msg: self.setup_log.append(m))
            try:
                fn()
                self.after(0, lambda v=(i + 1) / len(steps): self.setup_progress.set(v))
            except Exception as exc:
                self.after(0, lambda f=friendly_error(exc): self.setup_log.append(f))
                logger.exception("Setup step failed")
                return
        save_config({"setup_complete": True, "phone_count": self.phone_count, "first_run": False})
        self.after(0, lambda: self.show_screen("done"))


def run_integrated_setup(on_complete: Callable[[], None] | None = None) -> None:
    """Launch the integrated first-run setup wizard."""
    app = IntegratedSetupWizard(on_complete=on_complete)
    app.mainloop()


# Backward-compatible alias
SetupWizardApp = IntegratedSetupWizard


def main() -> None:
    """Standalone entry — prefer wizard.cpharm_merged.main() for the unified EXE."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(logs_dir() / "setup.log"), logging.StreamHandler()],
    )
    run_integrated_setup()


if __name__ == "__main__":
    main()
