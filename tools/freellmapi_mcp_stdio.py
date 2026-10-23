#!/usr/bin/env python3
"""Stdio MCP bridge → FreeLLMAPI local gateway.

Cursor's streamable-HTTP client often fails tool discovery against FreeLLMAPI's
stateless POST /mcp. This process speaks MCP over stdio and proxies tool calls
to http://127.0.0.1:<port>/mcp (plus a thin chat_completion tool on /v1).

Launch via ~/.cursor/mcp.json:
  "freellmapi": {
    "command": "python",
    "args": ["C:\\\\Users\\\\jsmil\\\\pharmflow\\\\tools\\\\freellmapi_mcp_stdio.py"]
  }

No farm / Tor / Start Farm side effects.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Import shared resolver from sibling helper (same directory).
_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from freellmapi_client import mcp_call, mcp_tool, resolve_config, _request  # noqa: E402

PROTOCOL = "2024-11-05"

REMOTE_TOOLS = (
    "list_models",
    "provider_health",
    "usage_summary",
    "routing_info",
    "set_routing_strategy",
    "cache_stats",
    "compression_stats",
)


def _log(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def _read_message() -> dict[str, Any] | None:
    """Read one LSP-style Content-Length framed JSON-RPC message from stdin."""
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        try:
            text = line.decode("utf-8", errors="replace").rstrip("\r\n")
        except Exception:  # noqa: BLE001
            return None
        if ":" in text:
            k, _, v = text.partition(":")
            headers[k.strip().lower()] = v.strip()
    length = int(headers.get("content-length", "0") or 0)
    if length <= 0:
        return None
    body = sys.stdin.buffer.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _write_message(msg: dict[str, Any]) -> None:
    data = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii") + data)
    sys.stdout.buffer.flush()


def _tool_schemas() -> list[dict[str, Any]]:
    # Prefer live schemas from FreeLLMAPI when reachable.
    cfg = resolve_config()
    remote = mcp_call(cfg, "tools/list", {})
    tools: list[dict[str, Any]] = []
    try:
        for t in remote["result"]["tools"]:
            tools.append(
                {
                    "name": t["name"],
                    "description": t.get("description") or t["name"],
                    "inputSchema": t.get("inputSchema") or {"type": "object", "properties": {}},
                }
            )
    except (TypeError, KeyError):
        for name in REMOTE_TOOLS:
            tools.append(
                {
                    "name": name,
                    "description": f"FreeLLMAPI MCP tool: {name}",
                    "inputSchema": {"type": "object", "properties": {}},
                }
            )
    tools.append(
        {
            "name": "chat_completion",
            "description": (
                "Run one OpenAI-compatible chat completion via FreeLLMAPI /v1 "
                "(inference — not farm money-path). Prefer model 'auto'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "model": {"type": "string", "default": "auto"},
                    "max_tokens": {"type": "integer", "default": 256},
                },
                "required": ["prompt"],
            },
        }
    )
    tools.append(
        {
            "name": "gateway_status",
            "description": "Local FreeLLMAPI dashboard/key/port snapshot for operators.",
            "inputSchema": {"type": "object", "properties": {}},
        }
    )
    return tools


def _content_text(obj: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(obj, indent=2, ensure_ascii=False)}]}


def _run_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    cfg = resolve_config()
    if name == "gateway_status":
        dash_status, _ = _request(cfg["base"] + "/", timeout=5)
        return _content_text(
            {
                "base": cfg["base"],
                "openai_base": cfg["openai_base"],
                "mcp": cfg["mcp"],
                "dashboard_http": dash_status,
                "key_present": bool(cfg["key"]),
                "default_model": cfg["model"],
            }
        )
    if name == "chat_completion":
        prompt = str(arguments.get("prompt") or "")
        model = str(arguments.get("model") or cfg["model"] or "auto")
        max_tokens = int(arguments.get("max_tokens") or 256)
        status, payload = _request(
            cfg["openai_base"] + "/chat/completions",
            method="POST",
            body={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "stream": False,
            },
            key=cfg["key"],
            timeout=180,
        )
        return _content_text({"http_status": status, "payload": payload})
    if name in REMOTE_TOOLS or name:
        result = mcp_tool(cfg, name, arguments or {})
        # Pass through FreeLLMAPI tool result shape when present.
        if isinstance(result, dict) and "result" in result:
            return result["result"]  # type: ignore[return-value]
        return _content_text(result)
    return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}


def _handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "freellmapi-stdio-bridge", "version": "1.0.0"},
                "instructions": (
                    "FreeLLMAPI bridge: introspection tools proxy to /mcp; "
                    "chat_completion uses /v1. Inference is separate from farm money-path."
                ),
            },
        }
    if method == "notifications/initialized" or method == "initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": _tool_schemas()}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            result = _run_tool(str(name), args if isinstance(args, dict) else {})
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except Exception as exc:  # noqa: BLE001
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "content": [{"type": "text", "text": f"tool failed: {exc}"}],
                    "isError": True,
                },
            }
    if mid is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": mid,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> int:
    cfg = resolve_config()
    _log(f"freellmapi-stdio-bridge base={cfg['base']} key={'yes' if cfg['key'] else 'NO'}")
    while True:
        try:
            msg = _read_message()
        except Exception as exc:  # noqa: BLE001
            _log(f"read error: {exc}")
            return 1
        if msg is None:
            return 0
        try:
            resp = _handle(msg)
        except Exception as exc:  # noqa: BLE001
            _log(f"handle error: {exc}")
            if msg.get("id") is not None:
                _write_message(
                    {
                        "jsonrpc": "2.0",
                        "id": msg.get("id"),
                        "error": {"code": -32603, "message": str(exc)},
                    }
                )
            continue
        if resp is not None:
            _write_message(resp)


if __name__ == "__main__":
    raise SystemExit(main())
