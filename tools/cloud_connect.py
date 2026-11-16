#!/usr/bin/env python3
"""PharmFlow cloud connect — one-login free path (Oracle Always Free + FreeLLMAPI).

Wires the operator's cloud Redroid host and the local FreeLLMAPI agent gateway
into the same session the Control Panel already uses (cloud_session.json +
cloud_agent.json). This is not a second farm stack and does not start sequences.

Free path already in-repo:
  * Cloud phones: Oracle Cloud Always Free ARM (A1.Flex) + Redroid
    (cloud_phones/setup-oracle-cloud.sh, PharmFlow.exe --cloud-phones-cli)
  * Cloud agent: FreeLLMAPI local gateway on 127.0.0.1:31415
    (tools/freellmapi_client.py, tools/cloud_agent.py)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Sibling FreeLLMAPI helper (same tools/ package the EXE already bundles).
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
try:
    import freellmapi_client as _freellmapi_client
except ImportError:  # pragma: no cover — frozen/missing optional helper
    _freellmapi_client = None  # type: ignore[assignment]


FREELLM_DEFAULT_BASE = "http://127.0.0.1:31415/v1"
FREELLM_DEFAULT_MODEL = "auto"

# Documented Always Free / local-gateway limits. Guidance only — never a phone cap.
FREE_TIER_LIMITS: dict[str, Any] = {
    "path": "oracle_always_free_redroid_plus_freellmapi",
    "label": "Oracle Cloud Always Free + FreeLLMAPI (local)",
    "compute": (
        "Oracle Always Free Ampere: VM.Standard.A1.Flex — up to 4 OCPU and "
        "24 GB RAM total in the home region (shared across Always Free A1 VMs)."
    ),
    "storage": (
        "Up to 200 GB Always Free block volume storage in the home region "
        "(shared with other Always Free boot/block volumes)."
    ),
    "network": (
        "Use a private path (Tailscale or VCN private IP). Do not expose ADB "
        "ports (5555+) on the public Internet."
    ),
    "agent": (
        "FreeLLMAPI on 127.0.0.1:31415 is the free local agent gateway. "
        "Upstream model rate limits and daily quotas depend on whichever "
        "providers FreeLLMAPI is routing to on this PC — PharmFlow does not "
        "add a second paid vendor."
    ),
    "phones_guidance": (
        "Instance count is operator-chosen (pass --count). There is no product "
        "phone ceiling. On a 24 GB Always Free box, leave RAM for the host OS "
        "and Docker — treat capacity as hardware headroom, not a hard cap."
    ),
    "oracle_console": "https://cloud.oracle.com",
    "setup_script": "cloud_phones/setup-oracle-cloud.sh",
}


def repo_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def cloud_session_path(root: Path | None = None) -> Path:
    return (root or repo_root()) / "cloud_session.json"


def cloud_agent_config_path(root: Path | None = None) -> Path:
    return (root or repo_root()) / "cloud_agent.json"


def load_session(root: Path | None = None) -> dict[str, Any]:
    path = cloud_session_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_session(
    *,
    host: str = "",
    count: int = 0,
    root: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = cloud_session_path(root)
    existing = load_session(root)
    host = str(host or "").strip() or str(existing.get("host") or "").strip()
    try:
        count_i = int(count)
    except (TypeError, ValueError):
        count_i = 0
    if count_i < 1:
        try:
            count_i = int(existing.get("count") or 0)
        except (TypeError, ValueError):
            count_i = 0
    payload: dict[str, Any] = {
        "host": host,
        "count": count_i if count_i > 0 else None,
        "path": FREE_TIER_LIMITS["path"],
        "label": FREE_TIER_LIMITS["label"],
    }
    if extra:
        for k, v in extra.items():
            if k in ("host", "count"):
                continue
            payload[k] = v
    # Drop null count so the file stays honest.
    if payload.get("count") is None:
        payload.pop("count", None)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _freellm_resolve() -> dict[str, str]:
    """Best-effort FreeLLMAPI config. Empty dict when the helper is unavailable."""
    if _freellmapi_client is None:
        return {}
    try:
        cfg = _freellmapi_client.resolve_config(prefer_public=False)
        return {
            "base": str(cfg.get("openai_base") or FREELLM_DEFAULT_BASE).rstrip("/"),
            "api_key": str(cfg.get("key") or ""),
            "model": str(cfg.get("model") or FREELLM_DEFAULT_MODEL),
            "gateway": str(cfg.get("base") or "http://127.0.0.1:31415").rstrip("/"),
        }
    except Exception:  # noqa: BLE001
        return {}


def probe_freellmapi(timeout: float = 2.5) -> dict[str, Any]:
    """Read-only check: is the local FreeLLMAPI gateway answering?"""
    fl = _freellm_resolve()
    gateway = (fl.get("gateway") or "http://127.0.0.1:31415").rstrip("/")
    openai_base = (fl.get("base") or FREELLM_DEFAULT_BASE).rstrip("/")
    key = fl.get("api_key") or ""
    out: dict[str, Any] = {
        "ok": False,
        "reachable": False,
        "key_present": bool(key),
        "base": openai_base,
        "model": fl.get("model") or FREELLM_DEFAULT_MODEL,
        "gateway": gateway,
        "source": "freellmapi",
    }
    try:
        req = urllib.request.Request(gateway + "/", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out["reachable"] = int(resp.status) == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        out["reachable"] = False
    out["ok"] = bool(out["reachable"] and out["key_present"])
    return out


def load_agent_file(root: Path | None = None) -> dict[str, Any]:
    path = cloud_agent_config_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_agent_config(root: Path | None = None) -> dict[str, Any]:
    """Merge env → cloud_agent.json → FreeLLMAPI into one agent config.

    Prefer FreeLLMAPI when the operator has not pointed PharmFlow at a paid
    OpenAI-compatible base. Never invent a paid vendor.
    """
    fl = _freellm_resolve()
    base = (
        os.environ.get("PHARMFLOW_CLOUD_AGENT_BASE")
        or ""
    ).strip().rstrip("/")
    key = (os.environ.get("PHARMFLOW_CLOUD_AGENT_KEY") or "").strip()
    model = (os.environ.get("PHARMFLOW_CLOUD_AGENT_MODEL") or "").strip()

    stored = load_agent_file(root)
    if not base and isinstance(stored.get("base"), str) and stored["base"].strip():
        base = stored["base"].strip().rstrip("/")
    if not key and isinstance(stored.get("api_key"), str) and stored["api_key"].strip():
        key = stored["api_key"].strip()
    if not model and isinstance(stored.get("model"), str) and stored["model"].strip():
        model = stored["model"].strip()

    # Free path fill-in when nothing paid/custom is set.
    if not base:
        base = (fl.get("base") or FREELLM_DEFAULT_BASE).rstrip("/")
    if not key and fl.get("api_key"):
        key = fl["api_key"]
    if not model:
        model = fl.get("model") or FREELLM_DEFAULT_MODEL

    is_freellm = "127.0.0.1:31415" in base or "localhost:31415" in base
    return {
        "base": base or FREELLM_DEFAULT_BASE,
        "api_key": key,
        "model": model or FREELLM_DEFAULT_MODEL,
        "configured": bool(key),
        "free_path": is_freellm,
        "source": "freellmapi" if (is_freellm and fl.get("api_key") and key == fl.get("api_key")) else (
            "cloud_agent.json" if load_agent_file(root) else "env_or_default"
        ),
    }


def wire_agent_config(
    *,
    api_key: str = "",
    base: str = "",
    model: str = "",
    root: Path | None = None,
    prefer_freellm: bool = True,
) -> dict[str, Any]:
    """Persist cloud_agent.json for the free path (or an explicit OpenAI-compatible base)."""
    resolved = resolve_agent_config(root)
    fl = _freellm_resolve()
    use_base = (base or "").strip().rstrip("/")
    use_model = (model or "").strip()
    use_key = (api_key or "").strip()

    if prefer_freellm and not use_base:
        use_base = (fl.get("base") or FREELLM_DEFAULT_BASE).rstrip("/")
    if not use_base:
        use_base = resolved["base"]
    if not use_model:
        use_model = fl.get("model") or resolved["model"] or FREELLM_DEFAULT_MODEL
    if not use_key:
        use_key = (fl.get("api_key") or resolved["api_key"] or "").strip()

    if not use_key:
        return {
            "ok": False,
            "saved": False,
            "configured": False,
            "error": (
                "No agent API key yet. Start FreeLLMAPI on this PC "
                "(writes %LOCALAPPDATA%\\PharmFlowTools\\freellmapi.env), "
                "or paste a key into the Cloud connect widget."
            ),
            "free_tier": FREE_TIER_LIMITS,
            "freellmapi": probe_freellmapi(),
        }

    path = cloud_agent_config_path(root)
    existing = load_agent_file(root)
    existing["base"] = use_base
    existing["model"] = use_model
    existing["api_key"] = use_key
    payload = json.dumps(existing, indent=2) + "\n"
    try:
        path.write_text(payload, encoding="utf-8")
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "saved": False, "configured": False, "error": str(exc)}
    if not isinstance(stored, dict) or stored.get("api_key") != use_key:
        return {
            "ok": False,
            "saved": False,
            "configured": False,
            "error": "Agent settings were not saved on disk.",
        }
    masked = use_key[:4] + "…" if len(use_key) > 6 else "(set)"
    return {
        "ok": True,
        "saved": True,
        "configured": True,
        "base": use_base,
        "model": use_model,
        "api_key": masked,
        "free_path": "127.0.0.1:31415" in use_base or "localhost:31415" in use_base,
        "free_tier": FREE_TIER_LIMITS,
        "message": "Cloud agent ready (FreeLLMAPI)" if "31415" in use_base else "Cloud agent ready",
    }


def session_status(root: Path | None = None) -> dict[str, Any]:
    session = load_session(root)
    agent = resolve_agent_config(root)
    fl = probe_freellmapi()
    host = str(session.get("host") or "").strip()
    count = session.get("count")
    try:
        count_i = int(count) if count is not None else 0
    except (TypeError, ValueError):
        count_i = 0
    ready_phones = bool(host)
    ready_agent = bool(agent.get("configured"))
    return {
        "ok": True,
        "host": host,
        "count": count_i if count_i > 0 else None,
        "session_saved": bool(host or count_i),
        "agent": {
            "configured": ready_agent,
            "base": agent.get("base"),
            "model": agent.get("model"),
            "free_path": bool(agent.get("free_path")),
            "source": agent.get("source"),
            "api_key": (agent["api_key"][:4] + "…") if agent.get("api_key") and len(agent["api_key"]) > 6 else (
                "(set)" if agent.get("api_key") else ""
            ),
        },
        "freellmapi": fl,
        "free_tier": FREE_TIER_LIMITS,
        "ready": ready_phones and ready_agent,
        "ready_phones": ready_phones,
        "ready_agent": ready_agent,
        "message": _status_message(ready_phones, ready_agent, fl),
    }


def _status_message(ready_phones: bool, ready_agent: bool, fl: dict[str, Any]) -> str:
    if ready_phones and ready_agent:
        return "Cloud session ready — phones host saved, agent configured."
    parts = []
    if not ready_phones:
        parts.append("enter the Oracle/Redroid host IP")
    if not ready_agent:
        if fl.get("reachable") and not fl.get("key_present"):
            parts.append("FreeLLMAPI is up but has no API key yet")
        elif not fl.get("reachable"):
            parts.append("start FreeLLMAPI on this PC (or paste an API key)")
        else:
            parts.append("finish agent login")
    return "Cloud connect needs: " + "; ".join(parts) + "."


def connect_login(
    host: str = "",
    count: int = 0,
    api_key: str = "",
    *,
    root: Path | None = None,
    start_phones: bool = True,
) -> dict[str, Any]:
    """One-login entry: save host/count, wire FreeLLMAPI agent, optionally start phone setup.

    Returns a plan the Control Panel bridge uses to kick ``cloud_phone_setup``.
    Does not spawn a second farm process.
    """
    host = str(host or "").strip()
    try:
        count_i = int(count or 0)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Cloud connect needs a whole-number instance count."}
    if count_i < 0:
        return {"ok": False, "error": "Cloud connect needs a non-negative instance count."}

    session = load_session(root)
    if not host:
        host = str(session.get("host") or "").strip()
    if count_i < 1:
        try:
            count_i = int(session.get("count") or 0)
        except (TypeError, ValueError):
            count_i = 0

    agent_out = wire_agent_config(api_key=api_key, root=root, prefer_freellm=True)
    # Agent-only login is allowed (widget can configure FreeLLMAPI without phones).
    if not host and not agent_out.get("configured"):
        return {
            "ok": False,
            "error": agent_out.get("error")
            or "Cloud connect needs a host IP and/or a working FreeLLMAPI key.",
            "free_tier": FREE_TIER_LIMITS,
            "freellmapi": probe_freellmapi(),
        }

    saved = save_session(host=host, count=count_i, root=root) if host or count_i else {}
    out: dict[str, Any] = {
        "ok": True,
        "host": host,
        "count": count_i if count_i > 0 else None,
        "session": saved,
        "agent": agent_out,
        "free_tier": FREE_TIER_LIMITS,
        "freellmapi": probe_freellmapi(),
        "start_phones": bool(start_phones and host and count_i > 0),
        "message": "",
    }
    bits = []
    if agent_out.get("configured"):
        bits.append(agent_out.get("message") or "agent ready")
    elif agent_out.get("error"):
        out["agent_warning"] = agent_out["error"]
        bits.append("agent not ready yet")
    if out["start_phones"]:
        bits.append(f"will connect cloud phones at {host} (count {count_i})")
    elif host and count_i < 1:
        out["phones_warning"] = (
            "Host saved. Enter an instance count to run cloud phone setup "
            "(connect + stealth + Tor)."
        )
        bits.append("host saved; count still needed for phone setup")
    elif not host:
        bits.append("agent-only login (no cloud phone host yet)")
    out["message"] = "Cloud connect: " + "; ".join(bits) + "."
    # Overall ok stays True when at least one side succeeded.
    if not agent_out.get("configured") and not out["start_phones"] and not host:
        out["ok"] = False
        out["error"] = out["message"]
    return out


def attach_local_and_cloud_phones(
    *,
    root: Path | None = None,
    log: Any = None,
    apply_stealth: bool = True,
) -> dict[str, Any]:
    """One control-surface attach: discover local MuMu/ADB + saved cloud host phones.

    Applies stealth fingerprint when ``apply_stealth`` is True (default) using
    existing farm fingerprint helpers — does not invent a second disguise path.
    """
    log_fn = log if callable(log) else None
    session = load_session(root)
    host = str(session.get("host") or "").strip()
    try:
        from wizard.preflight_core import discover_adb_phones, auto_connect_all_phones

        if log_fn:
            log_fn("Attaching local MuMu/ADB + published redroid ports…\n")
        auto_connect_all_phones(log_fn)
        serials = discover_adb_phones(log_fn, connect_mumu=True, force_mumu_scan=True)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"Local/cloud phone attach failed: {exc}",
            "phones": [],
            "host": host,
        }

    phones = [str(s).strip() for s in (serials or []) if str(s).strip()]
    cloud_like = [s for s in phones if s.startswith("127.0.0.1:") or (host and host in s)]
    local_like = [s for s in phones if s not in cloud_like]

    stealth_summary: dict[str, Any] = {}
    if apply_stealth and phones:
        try:
            from wizard.mumu_farm_ops import apply_fingerprint_all, audit_fingerprint_all

            if log_fn:
                log_fn("Applying stealth fingerprint defaults…\n")
            apply_fingerprint_all(phones, log_fn, patch_vms=True)
            stealth_summary = audit_fingerprint_all(phones, log_fn)
        except Exception as exc:  # noqa: BLE001
            stealth_summary = {"ok": False, "error": str(exc), "all_clean": False}

    # Seed stealth default in desktop prefs when missing (never force False→True
    # over an explicit operator off — gate will refuse Start instead).
    try:
        from wizard.wizard_paths import desktop_prefs_file

        prefs_path = desktop_prefs_file()
        prefs: dict[str, Any] = {}
        if prefs_path.is_file():
            try:
                loaded = json.loads(prefs_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    prefs = loaded
            except (OSError, ValueError, TypeError):
                prefs = {}
        if "mask_emulator_fingerprint" not in prefs:
            prefs["mask_emulator_fingerprint"] = True
            prefs.setdefault("dabflow_mantis_patch", True)
            prefs_path.parent.mkdir(parents=True, exist_ok=True)
            prefs_path.write_text(json.dumps(prefs, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass

    clean = bool(stealth_summary.get("all_clean")) if stealth_summary else (not apply_stealth)
    return {
        "ok": bool(phones),
        "phones": phones,
        "local_phones": local_like,
        "cloud_phones": cloud_like,
        "host": host,
        "count": session.get("count"),
        "stealth": stealth_summary,
        "stealth_ok": clean if apply_stealth else None,
        "message": (
            f"Attached {len(phones)} phone(s) "
            f"({len(local_like)} local, {len(cloud_like)} cloud/TCP)"
            + (
                "; stealth clean"
                if apply_stealth and clean
                else ("; stealth still leaking" if apply_stealth else "")
            )
        ),
        "error": None if phones else "No phones answering ADB after attach",
    }
