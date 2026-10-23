#!/usr/bin/env python3
"""Thin FreeLLMAPI helper for PharmFlow / Cursor / FREEBUFF agents.

Talks to the local FreeLLMAPI desktop gateway (OpenAI + MCP introspection).
Does NOT touch farm Start Farm / Tor inject money-path.

Config (first match wins for key/base):
  FREELLMAPI_URL / FREELLMAPI_API_KEY
  OPENAI_BASE_URL / OPENAI_API_KEY  (base may end with /v1)
  ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY
  %LOCALAPPDATA%\\PharmFlowTools\\freellmapi.env
  %APPDATA%\\FreeLLMAPI\\config.json  (port only; default 31415)

Examples:
  python tools/freellmapi_client.py status
  python tools/freellmapi_client.py mcp provider_health
  python tools/freellmapi_client.py mcp list_models
  python tools/freellmapi_client.py chat "Summarize farm health in one line"
  python tools/freellmapi_client.py models
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_PORT = 31415
ENV_FILE = Path(os.environ.get("LOCALAPPDATA", "")) / "PharmFlowTools" / "freellmapi.env"
CONFIG_FILE = Path(os.environ.get("APPDATA", "")) / "FreeLLMAPI" / "config.json"


def _load_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _port_from_config() -> int:
    if not CONFIG_FILE.is_file():
        return DEFAULT_PORT
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return int(data.get("port") or DEFAULT_PORT)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return DEFAULT_PORT


def resolve_config(*, prefer_public: bool | None = None) -> dict[str, str]:
    """Resolve gateway URLs.

    Local desktop (:31415) is default for agents. Stale cloudflared URLs in
    freellmapi.env must not hijack local MCP/chat — set FREELLMAPI_USE_PUBLIC=1
    (or prefer_public=True) only for Cursor cloud model-override paths.
    """
    file_env = _load_dotenv(ENV_FILE)
    port = _port_from_config()
    default_base = f"http://127.0.0.1:{port}"

    if prefer_public is None:
        prefer_public = (os.environ.get("FREELLMAPI_USE_PUBLIC") or "").strip() in {
            "1",
            "true",
            "yes",
            "on",
        }

    url = (
        os.environ.get("FREELLMAPI_URL")
        or file_env.get("FREELLMAPI_URL")
        or os.environ.get("ANTHROPIC_BASE_URL")
        or default_base
    ).rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    # Prefer loopback when ANTHROPIC_BASE_URL is local but FREELLMAPI_URL missing.
    if "127.0.0.1" not in url and "localhost" not in url:
        local_candidate = file_env.get("FREELLMAPI_URL") or default_base
        if not prefer_public:
            url = local_candidate.rstrip("/")

    local_openai = f"{url}/v1"
    public_openai = (
        os.environ.get("OPENAI_BASE_URL")
        or file_env.get("OPENAI_BASE_URL")
        or file_env.get("FREELLMAPI_PUBLIC_URL")
        or ""
    ).rstrip("/")
    if public_openai and not public_openai.endswith("/v1"):
        public_openai = public_openai.rstrip("/") + "/v1"

    openai_base = public_openai if (prefer_public and public_openai) else local_openai

    key = (
        os.environ.get("FREELLMAPI_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or file_env.get("FREELLMAPI_API_KEY")
        or file_env.get("OPENAI_API_KEY")
        or ""
    )
    model = (
        os.environ.get("OPENAI_MODEL")
        or file_env.get("OPENAI_MODEL")
        or "auto"
    )
    return {
        "base": url if ("127.0.0.1" in url or "localhost" in url) else default_base,
        "openai_base": openai_base,
        "mcp": f"{(url if ('127.0.0.1' in url or 'localhost' in url) else default_base)}/mcp",
        "key": key,
        "model": model,
        "env_file": str(ENV_FILE),
        "prefer_public": "1" if prefer_public else "0",
        "public_openai_base": public_openai,
    }


def _request(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    key: str = "",
    timeout: float = 120.0,
) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return int(resp.status), json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return int(resp.status), raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed: Any = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw
        return int(exc.code), parsed
    except Exception as exc:  # noqa: BLE001
        return 0, {"error": str(exc)}


def mcp_call(cfg: dict[str, str], method: str, params: dict[str, Any] | None = None) -> Any:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    status, payload = _request(cfg["mcp"], method="POST", body=body, key=cfg["key"], timeout=60)
    if status != 200:
        return {"ok": False, "http_status": status, "payload": payload}
    return payload


def mcp_tool(cfg: dict[str, str], name: str, arguments: dict[str, Any] | None = None) -> Any:
    return mcp_call(cfg, "tools/call", {"name": name, "arguments": arguments or {}})


def cmd_status(cfg: dict[str, str]) -> int:
    dash_status, dash = _request(cfg["base"] + "/", key="", timeout=5)
    models_status, models = _request(
        cfg["openai_base"] + "/models", key=cfg["key"], timeout=15
    )
    health = mcp_tool(cfg, "provider_health")
    routing = mcp_tool(cfg, "routing_info")
    out = {
        "ok": dash_status == 200 and bool(cfg["key"]),
        "base": cfg["base"],
        "openai_base": cfg["openai_base"],
        "mcp": cfg["mcp"],
        "dashboard_http": dash_status,
        "models_http": models_status,
        "key_present": bool(cfg["key"]),
        "key_prefix": (cfg["key"][:12] + "…") if cfg["key"] else "",
        "default_model": cfg["model"],
        "env_file": cfg["env_file"],
        "provider_health": health,
        "routing_info": routing,
        "models_sample": None,
    }
    if isinstance(models, dict) and isinstance(models.get("data"), list):
        out["models_count"] = len(models["data"])
        out["models_sample"] = [m.get("id") for m in models["data"][:12]]
    else:
        out["models_payload"] = models
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


def cmd_models(cfg: dict[str, str]) -> int:
    status, payload = _request(cfg["openai_base"] + "/models", key=cfg["key"], timeout=30)
    print(json.dumps({"http_status": status, "payload": payload}, indent=2))
    return 0 if status == 200 else 1


def cmd_mcp(cfg: dict[str, str], tool: str, args_json: str | None) -> int:
    arguments: dict[str, Any] = {}
    if args_json:
        arguments = json.loads(args_json)
    if tool == "tools_list":
        result = mcp_call(cfg, "tools/list", {})
    else:
        result = mcp_tool(cfg, tool, arguments)
    print(json.dumps(result, indent=2))
    # unwrap text JSON if present for easier reading
    try:
        text = result["result"]["content"][0]["text"]
        print("--- parsed ---")
        print(json.dumps(json.loads(text), indent=2))
    except (TypeError, KeyError, IndexError, json.JSONDecodeError):
        pass
    return 0


def cmd_chat(cfg: dict[str, str], prompt: str, model: str | None, max_tokens: int) -> int:
    body = {
        "model": model or cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "stream": False,
    }
    status, payload = _request(
        cfg["openai_base"] + "/chat/completions",
        method="POST",
        body=body,
        key=cfg["key"],
        timeout=180,
    )
    print(json.dumps({"http_status": status, "payload": payload}, indent=2))
    return 0 if status == 200 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FreeLLMAPI local gateway helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Dashboard + MCP health snapshot")
    sub.add_parser("models", help="GET /v1/models")

    p_mcp = sub.add_parser("mcp", help="Call FreeLLMAPI MCP tool (introspection)")
    p_mcp.add_argument(
        "tool",
        help="Tool name, or tools_list",
    )
    p_mcp.add_argument("--args", dest="args_json", default=None, help="JSON object of arguments")

    p_chat = sub.add_parser("chat", help="POST /v1/chat/completions")
    p_chat.add_argument("prompt", nargs="+", help="User prompt")
    p_chat.add_argument("--model", default=None)
    p_chat.add_argument("--max-tokens", type=int, default=256)

    args = parser.parse_args(argv)
    cfg = resolve_config()
    if args.cmd == "status":
        return cmd_status(cfg)
    if args.cmd == "models":
        return cmd_models(cfg)
    if args.cmd == "mcp":
        return cmd_mcp(cfg, args.tool, args.args_json)
    if args.cmd == "chat":
        return cmd_chat(cfg, " ".join(args.prompt), args.model, args.max_tokens)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
