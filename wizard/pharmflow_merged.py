"""PharmFlow unified entry point — single EXE with integrated first-run setup."""

from __future__ import annotations

import logging

from wizard.pharmflow_desktop import PharmFlowApp
from wizard.setup_desktop import run_integrated_setup
from wizard.wizard_paths import logs_dir, needs_setup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(logs_dir() / "pharmflow.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def launch_main_app() -> None:
    """Launch the main phone farm dashboard."""
    app = PharmFlowApp()
    app.mainloop()


def main() -> None:
    """Single entry: auto-setup on first run, then main wizard + dashboard."""
    if needs_setup():
        logger.info("First run detected — starting integrated setup")
        run_integrated_setup(on_complete=launch_main_app)
        return
    launch_main_app()


if __name__ == "__main__":
    main()
