#!/usr/bin/env python3
"""Unified CPharm project/agent/cloud-emulator tool.

Safe by default: emulator lifecycle commands require --apply; agent mode only
plans work and never executes arbitrary model-generated commands.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    """Project root. When frozen (PyInstaller onefile), ``__file__`` points into
    the temp ``_MEIPASS`` extraction dir, so resolve relative to the EXE location
    instead. Keeping all three EXEs in the same folder makes that the project root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


ROOT = _repo_root()
COMPOSE = ROOT / "cloud_phones" / "docker-compose.redroid.yml"
VERSION = "1.0.0"


def run_checked(argv: list[str]) -> int:
    print("$ " + " ".join(argv))
    return subprocess.run(argv, cwd=ROOT, check=False).returncode


def project_status(_: argparse.Namespace) -> int:
    dirs = ["automation", "wizard", "tools", "cloud_phones", "sequences"]
    print(json.dumps({"root": str(ROOT), "components": {d: (ROOT / d).is_dir() for d in dirs}}, indent=2))
    return 0


def agent_plan(args: argparse.Namespace) -> int:
    goal = " ".join(args.goal).strip()
    if not goal:
        print("A goal is required", file=sys.stderr)
        return 2
    print(json.dumps({
        "goal": goal,
        "context": ["automation/dashboard.py", "automation/config.py", "cloud_phones/"],
        "steps": [
            "Inspect existing automation and configuration",
            "Select or validate the emulator backend",
            "Run a dry-run health check",
            "Apply only explicitly approved changes",
            "Run syntax checks and relevant tests",
        ],
        "safety": "No cloud, ADB, Docker, or filesystem mutation is performed by agent-plan.",
    }, indent=2))
    return 0


def emulator(args: argparse.Namespace) -> int:
    if not COMPOSE.is_file():
        print(f"Compose file not found: {COMPOSE}", file=sys.stderr)
        return 1
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from docker_guard import DOCKER_OFF_MSG, engine_running

        if not engine_running():
            print(DOCKER_OFF_MSG, file=sys.stderr)
            return 1
    except Exception:  # noqa: BLE001
        print("Docker guard unavailable - Docker left off.", file=sys.stderr)
        return 1
    base = ["docker", "compose", "-f", str(COMPOSE)]
    if args.action == "config":
        return run_checked(base + ["config"])
    if not args.apply:
        print(f"Dry run: would run {' '.join(base + [args.action])}")
        print("Re-run with --apply to change local Docker state.")
        return 0
    return run_checked(base + [args.action] + list(args.services or []))


def watchdog(args: argparse.Namespace) -> int:
    script = ROOT / "tools" / "cpharm_watchdog.py"
    argv = [sys.executable, str(script), *args.watchdog_args]
    return run_checked(argv)


def cloud(args: argparse.Namespace) -> int:
    """Drive the LLM cloud agent (tools/cloud_agent.py)."""
    import cloud_agent

    base = args.base or None
    model = args.model or None
    apply = args.apply or False
    steps = args.max_steps or 12
    return cloud_agent.main([
        *(["--base", base] if base else []),
        *(["--model", model] if model else []),
        *(["--apply"] if apply else []),
        "--max-steps", str(steps),
        *args.goal,
    ])


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="project-agent", description=__doc__)
    p.add_argument("--version", action="version", version=f"CPharmAgent {VERSION}")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("status", help="Show detected project components")
    s.set_defaults(func=project_status)
    a = sub.add_parser("agent-plan", help="Create a bounded implementation plan")
    a.add_argument("goal", nargs="+", help="Goal to plan")
    a.set_defaults(func=agent_plan)
    c = sub.add_parser("cloud", help="Run the LLM cloud agent (needs API key)")
    c.add_argument("goal", nargs="+", help="The task/goal to give the agent")
    c.add_argument("--base", help="API base URL override")
    c.add_argument("--model", help="model id override")
    c.add_argument("--apply", action="store_true", help="allow local shell actions")
    c.add_argument("--max-steps", type=int, default=12, help="max model/tool turns")
    c.set_defaults(func=cloud)
    e = sub.add_parser("emulator", help="Manage the local Redroid compose stack")
    e.add_argument("action", choices=["config", "up", "down", "ps", "logs"])
    e.add_argument("--services", nargs="*", help="Optional compose services to target")
    e.add_argument("--apply", action="store_true", help="Actually invoke Docker Compose")
    e.set_defaults(func=emulator)
    w = sub.add_parser("watchdog", help="Check and repair backend, Docker, and ADB connections")
    w.add_argument("watchdog_args", nargs=argparse.REMAINDER)
    w.set_defaults(func=watchdog)
    return p


if __name__ == "__main__":
    parsed = build_parser().parse_args()
    raise SystemExit(parsed.func(parsed))
