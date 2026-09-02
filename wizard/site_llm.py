"""Optional OpenAI-compatible LLM assist for Site Interview (suggest only; user confirms)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from automation.site_profile import SiteProfile
from wizard.wizard_paths import load_config, save_config

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"

_SYSTEM = """You help operators configure a virtual Android phone farm for ANY website or mobile app.
Return ONLY a JSON object with suggested Site Interview fields. Do not invent brand-specific product names
as if the farm tool belongs to that brand. Coords assume a 900x1600 portrait phone.
Allowed keys:
  display_name (string), target_kind ("website"|"app"), url (string), package (string),
  has_gate (bool), gate_xy ("x,y"), core_xy ("x,y"), core_scroll (bool),
  include_browse (bool), include_ads (bool), humanize ("conservative"|"moderate"|"aggressive"),
    phone_count (int), seqs_per_hour (int), hours (number), ads_per_hour (int),
    startup_spread_minutes (int), ntfy_topic (string), notes (string),
  rationale (short string explaining suggestions).
Omit keys you cannot infer. Never include API keys or secrets."""


def get_llm_settings() -> dict[str, str]:
    cfg = load_config()
    llm = cfg.get("llm") if isinstance(cfg.get("llm"), dict) else {}
    key = str(llm.get("api_key") or os.environ.get("CPHARM_LLM_API_KEY") or "").strip()
    base = str(llm.get("base_url") or os.environ.get("CPHARM_LLM_BASE_URL") or DEFAULT_BASE_URL).strip()
    model = str(llm.get("model") or os.environ.get("CPHARM_LLM_MODEL") or DEFAULT_MODEL).strip()
    return {"api_key": key, "base_url": base.rstrip("/"), "model": model or DEFAULT_MODEL}


def save_llm_settings(*, api_key: str | None = None, base_url: str | None = None, model: str | None = None) -> None:
    current = get_llm_settings()
    save_config(
        {
            "llm": {
                "api_key": current["api_key"] if api_key is None else api_key.strip(),
                "base_url": (base_url if base_url is not None else current["base_url"] or DEFAULT_BASE_URL)
                .strip()
                .rstrip("/"),
                "model": (model if model is not None else current["model"] or DEFAULT_MODEL).strip(),
            }
        }
    )


def llm_configured() -> bool:
    return bool(get_llm_settings()["api_key"])


def _chat_completion(*, system: str, user: str, timeout_s: float = 60.0) -> str:
    settings = get_llm_settings()
    if not settings["api_key"]:
        raise RuntimeError("No LLM API key — set one in Site Interview or Settings (Assist).")
    url = f"{settings['base_url']}/chat/completions"
    body = {
        "model": settings["model"],
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }
    raw = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=raw,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings['api_key']}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM network error: {exc}") from exc

    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("LLM returned no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("LLM returned empty content")
    return content.strip()


def suggest_profile_fields(draft: SiteProfile | dict[str, Any], *, extra_notes: str = "") -> dict[str, Any]:
    """
    Ask the LLM for interview field suggestions.

    Returns a plain dict of suggested form fills. Caller must show them to the user
    and apply only after confirmation. Never starts the farm.
    """
    if isinstance(draft, SiteProfile):
        draft_payload = draft.to_dict()
    elif isinstance(draft, dict):
        draft_payload = draft
    else:
        raise TypeError("draft must be SiteProfile or dict")

    user = (
        "Current interview draft (may be incomplete):\n"
        + json.dumps(draft_payload, indent=2)
        + "\n\nOperator notes:\n"
        + (extra_notes.strip() or "(none)")
        + "\n\nSuggest improved field values for a natural, humanized farm for this target."
    )
    content = _chat_completion(system=_SYSTEM, user=user)
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError(f"LLM did not return JSON: {content[:200]}") from exc
        data = json.loads(content[start : end + 1])
    if not isinstance(data, dict):
        raise RuntimeError("LLM JSON root must be an object")
    return data


def apply_suggestions_to_interview_vars(app: Any, suggestions: dict[str, Any]) -> list[str]:
    """Apply confirmed suggestions onto Site Interview vars. Returns applied keys."""
    applied: list[str] = []
    mapping = [
        ("display_name", "_si_name", "str"),
        ("url", "_si_url", "str"),
        ("package", "_si_package", "str"),
        ("gate_xy", "_si_gate_xy", "str"),
        ("core_xy", "_si_core_xy", "str"),
        ("humanize", "_si_humanize", "str"),
        ("phone_count", "_si_phones", "str"),
        ("seqs_per_hour", "_si_seqs_hr", "str"),
        ("hours", "_si_hours", "str"),
        ("ads_per_hour", "_si_ads_hr", "str"),
        ("startup_spread_minutes", "_si_start_spread", "str"),
        ("ntfy_topic", "_si_ntfy", "str"),
        ("target_kind", "_si_kind", "str"),
        ("has_gate", "_si_gate", "bool"),
        ("core_scroll", "_si_core_scroll", "bool"),
        ("include_browse", "_si_browse", "bool"),
        ("include_ads", "_si_ads", "bool"),
    ]
    for key, attr, kind in mapping:
        if key not in suggestions:
            continue
        var = getattr(app, attr, None)
        if var is None:
            continue
        val = suggestions[key]
        try:
            if kind == "bool":
                var.set(bool(val))
            else:
                if key == "target_kind":
                    s = str(val).strip().lower()
                    var.set("app" if s == "app" else "website")
                elif key == "humanize":
                    s = str(val).strip().lower()
                    var.set(s if s in ("conservative", "moderate", "aggressive") else "moderate")
                else:
                    var.set(str(val).strip())
            applied.append(key)
        except (TypeError, ValueError):
            continue
    return applied
