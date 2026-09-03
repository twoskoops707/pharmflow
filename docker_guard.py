"""Docker engine gate — PharmFlow never opens Docker on its own.

Docker Desktop registers a CLI shim on Windows: running any ``docker`` command
while the engine is down LAUNCHES the Docker Desktop GUI. A routine status
check (``docker compose ps``) could therefore pop Docker open without the
operator ever asking for it.

Rule for every docker CLI call in PharmFlow:

  * Engine already running  -> the CLI is safe, use it.
  * Engine down             -> do NOT invoke the docker CLI. Report Docker as
                               off and tell the operator to start Docker
                               Desktop themselves. The wizard's Connect button
                               and the dashboard's docker panel still work the
                               moment the engine is up.

Docker therefore stays fully usable when the operator has it running, while
the app is guaranteed to never start it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

DOCKER_OFF_MSG = (
    "Docker is off. PharmFlow never opens Docker on its own - start Docker "
    "Desktop yourself, wait until it is ready, then retry."
)

_ENGINE_PROC_NAMES = (
    "dockerd.exe",
    "com.docker.backend.exe",
    "com.docker.service.exe",
)

_OVERRIDE_ENV = "CPHARM_DOCKER_ENGINE_UP"


def _no_window_flags() -> int:
    if sys.platform == "win32":
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)
    return 0


def _engine_process_running() -> bool:
    """True when a Docker engine process is alive. Never touches docker CLI."""
    if sys.platform != "win32":
        # Linux/CI: dockerd pidfile or unix socket, still no CLI.
        for probe in (Path("/var/run/docker.pid"), Path("/var/run/docker.sock")):
            if probe.exists():
                return True
        return False
    for name in _ENGINE_PROC_NAMES:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=_no_window_flags(),
                check=False,
            )
            if name.lower() in (result.stdout or "").lower():
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    return False


def engine_running() -> bool:
    """True when it is safe to invoke the docker CLI (it cannot wake Docker)."""
    override = os.environ.get(_OVERRIDE_ENV, "").strip().lower()
    if override in ("1", "true", "yes", "on"):
        return True
    try:
        return _engine_process_running()
    except Exception:  # noqa: BLE001 — never block the caller on a check failure
        return False
