#!/usr/bin/env python3
"""CPharm Cloud Agent — an LLM-driven operations agent.

The agent calls an OpenAI-compatible chat-completions API (any provider whose
endpoint mirrors that protocol) using the operator's own API key, and lets the
model drive the farm through a fixed set of local tools (status, adb, docker,
watchdog, log tail) in a turn-taking loop.

Design intent
-------------
* We do NOT add any content filtering, censorship, or scoring of the operator's
  prompts or the model's replies. The request goes straight from this process to
  the configured provider, signed with the operator's own key. Whatever the
  chosen provider does with it is that provider's policy — that choice is the
  operator's to make when they pick an endpoint/model.
* We DO gate dangerous actions with the same ``--apply`` convention used
  everywhere else in CPharm: read-only tools run freely; anything that mutates
  the local machine (docker up/down, adb operations, writes) requires ``--apply``.
  That is an operational safety rail for the operator's own infra, not content
  filtering.

Config (in order): environment variables, then a JSON file in the CPharm root.
    CPHARM_CLOUD_AGENT_BASE    base URL, e.g. https://api.openai.com/v1
    CPHARM_CLOUD_AGENT_KEY     API key (never logged)
    CPHARM_CLOUD_AGENT_MODEL   model id, e.g. gpt-4o
    cloud_agent.json           {"base":..., "api_key":..., "model":...}
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _repo_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


ROOT = _repo_root()
VERSION = "1.0.0"
DEFAULT_TIMEOUT = 180
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "farm_status",
            "description": "High-level health of the local CPharm farm (docker, adb, groups, dashboard). Read-only.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "adb_devices",
            "description": "List ADB devices currently connected to this machine. Read-only.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "docker_ps",
            "description": "List running Docker containers (redroid phones). Read-only.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tail_log",
            "description": "Tail the CPharm log file. Returns the last N lines.",
            "parameters": {
                "type": "object",
                "properties": {"lines": {"type": "integer", "description": "number of trailing lines (>=1, <=2000)"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "watchdog_once",
            "description": "Run the CPharm watchdog a single pass for the operator (health + known repairs). Requires --apply to perform any repair.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a local shell command. Only allowed when the agent was started with --apply. Never exposes secrets.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "shell command to run on this machine"}},
                "required": ["command"],
            },
        },
    },
]

SYSTEM_PROMPT = (
    "You are the CPharm farm operations agent. You help run and repair an Android "
    "emulation farm (Redroid Docker containers + MuMu + ADB) that automates visits "
    "and ad interactions on a site. Inspect the real environment with the available "
    "tools, reason step by step, and report what you find and what you recommend "
    "clearly. Use run_command ONLY if an action is needed AND the agent was started "
    "with --apply. Never claim to do something you didn't do. Be concise and direct."
)


# --------------------------------------------------------------------------- tools


def _run(argv: list[str], *, timeout: int = 120, cwd: Path | None = None) -> dict:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd or ROOT),
            creationflags=flags,
        )
    except FileNotFoundError:
        return {"ok": False, "error": f"command not found on PATH: {argv[0]}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"command timed out after {timeout}s"}
    return {"ok": proc.returncode == 0, "returncode": proc.returncode,
            "stdout": (proc.stdout or "").strip()[-4000:],
            "stderr": (proc.stderr or "").strip()[-2000:]}


def _docker_engine_running() -> bool:
    """True only when the docker CLI cannot wake Docker Desktop."""
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from docker_guard import engine_running

        return bool(engine_running())
    except Exception:  # noqa: BLE001
        return False


def tool_farm_status() -> dict:
    out = {}
    if _docker_engine_running():
        out["docker"] = _run(["docker", "ps", "--format", "{{.Names}} {{.Status}}"], timeout=30)
    else:
        out["docker"] = {"ok": False, "error": "Docker off (engine not running) - not started by PharmFlow"}
    out["adb"] = _run(["adb", "devices"], timeout=30)
    log = ROOT / "logs" / "cpharm.log"
    out["log_exists"] = log.is_file()
    return out


def tool_adb_devices() -> dict:
    return _run(["adb", "devices", "-l"], timeout=30)


def tool_docker_ps() -> dict:
    if not _docker_engine_running():
        return {"ok": False, "error": "Docker off (engine not running) - not started by PharmFlow"}
    return _run(["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"], timeout=30)


def tool_tail_log(lines: int = 100) -> dict:
    try:
        n = max(1, min(int(lines or 100), 2000))
    except (TypeError, ValueError):
        n = 100
    log_file = ROOT / "logs" / "cpharm.log"
    if not log_file.is_file():
        return {"ok": False, "error": f"log not found: {log_file}"}
    try:
        data = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "lines": data[-n:]}


def tool_watchdog_once() -> dict:
    wd = ROOT / "tools" / "cpharm_watchdog.py"
    if not wd.is_file():
        return {"ok": False, "error": "watchdog script not found (source tree only)"}
    return _run([sys.executable, str(wd), "--once"], timeout=150)


def tool_run_command(command: str, *, apply_allowed: bool) -> dict:
    if not apply_allowed:
        return {"ok": False,
                "error": "run_command is disabled without --apply (operator safety rail). "
                         "Re-run the agent with --apply to allow local shell actions."}
    if not command or not command.strip():
        return {"ok": False, "error": "empty command"}
    import shlex
    argv = shlex.split(command)
    return _run(argv, timeout=240)


_TOOLS = {
    "farm_status": tool_farm_status,
    "adb_devices": tool_adb_devices,
    "docker_ps": tool_docker_ps,
    "tail_log": lambda lines=100: tool_tail_log(lines),
    "watchdog_once": tool_watchdog_once,
}


def dispatch_tool(name: str, args: dict, *, apply_allowed: bool) -> dict:
    if name == "run_command":
        result = tool_run_command(args.get("command", "") or "", apply_allowed=apply_allowed)
    elif name not in _TOOLS:
        return {"ok": False, "error": f"unknown tool: {name}"}
    else:
        try:
            if name == "tail_log":
                return tool_tail_log(args.get("lines", 100))
            result = _TOOLS[name]()
        except Exception as exc:  # never let a tool failure kill the loop
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    # Redact anything that looks like a credential before sending to the model.
    return _redact(result)


def _redact(obj) -> dict:
    try:
        text = json.dumps(obj)
    except (TypeError, ValueError):
        return obj
    import re
    text = re.sub(r"(?i)(sk-[A-Za-z0-9_\-]{6,}|bearer\s+[A-Za-z0-9._\-]{6,})", "[REDACTED]", text)
    return json.loads(text)


# --------------------------------------------------------------------------- client


def _load_config() -> dict:
    cfg = {
        "base": os.environ.get("CPHARM_CLOUD_AGENT_BASE", "https://api.openai.com/v1").rstrip("/"),
        "api_key": os.environ.get("CPHARM_CLOUD_AGENT_KEY", ""),
        "model": os.environ.get("CPHARM_CLOUD_AGENT_MODEL", "gpt-4o"),
    }
    json_file = ROOT / "cloud_agent.json"
    if json_file.is_file():
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            for k in ("base", "api_key", "model"):
                if isinstance(data.get(k), str) and data.get(k).strip():
                    cfg[k] = data[k].strip()
        except (OSError, ValueError):
            pass
    return cfg


def call_model(cfg: dict, messages: list[dict], *, timeout: int = DEFAULT_TIMEOUT) -> dict:
    url = f"{cfg['base']}/chat/completions"
    body = {
        "model": cfg["model"],
        "messages": messages,
        "tools": TOOL_SCHEMAS,
        "tool_choice": "auto",
        "temperature": 0.4,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['api_key']}",
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800] if exc.read else ""
        return {"ok": False, "error": f"HTTP {exc.code}", "detail": detail}
    except urllib.error.URLError as exc:
        return {"ok": False, "error": f"network error: {exc.reason}"}
    except TimeoutError:
        return {"ok": False, "error": f"request timed out after {timeout}s"}
    try:
        return json.loads(raw)
    except ValueError:
        return {"ok": False, "error": "response was not valid JSON", "detail": raw[:800]}


def run_agent(goal: str, *, apply: bool, max_steps: int = 12, stream=print) -> int:
    cfg = _load_config()
    if not cfg["api_key"]:
        print("No API key configured.", file=sys.stderr)
        print("Set CPHARM_CLOUD_AGENT_KEY or create <root>/cloud_agent.json.", file=sys.stderr)
        return 3
    if not goal or not goal.strip():
        print("A goal is required.", file=sys.stderr)
        return 2

    stream(f"[[ using model {cfg['model']} @ {cfg['base']} ]]")
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": goal.strip()},
    ]

    for step in range(1, max_steps + 1):
        stream(f"[[ step {step}/{max_steps} ]]")
        resp = call_model(cfg, messages)
        if not resp.get("ok"):
            stream(f"[[ model error: {resp.get('error')} ]]")
            if resp.get("detail"):
                stream(resp["detail"])
            return 1
        if "error" in resp:
            stream(f"[[ provider error: {resp.get('error')} ]]")
            return 1
        choices = resp.get("choices") or []
        if not choices:
            stream("[[ no choices returned; stopping ]]")
            return 1
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if content:
            stream(content)
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            # Model finished reasoning without requesting tools.
            stream("[[ agent finished ]]")
            return 0
        messages.append(msg)
        for tc in tool_calls:
            fn = tc.get("function") or {}
            name = fn.get("name") or ""
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            stream(f"[[ tool -> {name} ]]")
            result = dispatch_tool(name, args, apply_allowed=apply)
            stream(json.dumps(result, indent=2)[:3000])
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id") or f"call_{step}_{name}",
                "content": json.dumps(result),
            })
    stream(f"[[ reached step limit {max_steps} ]]")
    return 0


# --------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cpharm-cloud-agent",
        description="LLM-driven CPharm operations agent (OpenAI-compatible API).",
    )
    p.add_argument("--version", action="version", version=f"CPharmCloudAgent {VERSION}")
    p.add_argument("--base", help="API base URL (overrides config)")
    p.add_argument("--model", help="model id (overrides config)")
    p.add_argument("--apply", action="store_true",
                   help="allow local shell actions (run_command). Without it, only read-only tools run.")
    p.add_argument("--max-steps", type=int, default=12, help="max model/tool turns (default 12)")
    p.add_argument("goal", nargs="+", help="the task/goal to give the agent")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = _load_config()
    if args.base:
        cfg["base"] = args.base.rstrip("/")
    if args.model:
        cfg["model"] = args.model
    # Env override is respected; persist base/model through _load_config cache-free.
    os.environ["CPHARM_CLOUD_AGENT_BASE"] = cfg["base"]
    os.environ["CPHARM_CLOUD_AGENT_MODEL"] = cfg["model"]
    return run_agent(" ".join(args.goal), apply=args.apply, max_steps=args.max_steps)


if __name__ == "__main__":
    raise SystemExit(main())