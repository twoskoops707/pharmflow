"""Multi-publisher registry for the operator console (additive; Mantis core untouched).

The console's top tabs let the operator add ad publishers. Each publisher gets the
same gauge treatment as Mantis: its own saved account totals (same shape as the
Mantis pull) plus a "Total" tab that sums every configured publisher's numbers.

Only Mantis has a real account pull client today (``automation.mantis_fetch``).
Newly added publishers are ``configured=False`` — the operator can enter their
totals manually (or wire a client later) while Mantis stays pull-only. Nothing in
this module touches the single-Mantis money core; it only adds state + endpoints.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOG_DIR = Path(os.environ.get("PHARMFLOW_LOG_DIR", r"C:\PharmFlow\logs"))
_REGISTRY = Path(os.environ.get("PHARMFLOW_PUBLISHERS_FILE", r"C:\PharmFlow\publishers.json"))
_LOCK = threading.RLock()

# Mantis is the live, pull-configured publisher. AdSense/Ezoic/Other remain as
# stubs until a real account client exists (same contract the dash already used).
_DEFAULT = {
    "mantis": {"display_name": "Mantis", "configured": True, "stub": False},
    "adsense": {"display_name": "AdSense", "configured": False, "stub": True},
    "ezoic": {"display_name": "Ezoic", "configured": False, "stub": True},
    "other": {"display_name": "Other SSP", "configured": False, "stub": True},
}

_DEFAULT_TOTALS: dict[str, Any] = {
    "date": "",
    "impressions": 0,
    "clicks": 0,
    "payout_usd": 0.0,
    "ecpm": 0.0,
    "evcpm": 0.0,
    "receivable_usd": None,
    "paid_to_date_usd": None,
    "updated": None,
    "source": "manual",
}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return s or "publisher"


def _registry_path() -> Path:
    p = _REGISTRY
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return p


def load_registry() -> dict[str, dict[str, Any]]:
    """slug -> record. Seeds defaults on first run; never drops existing keys."""
    with _LOCK:
        path = _registry_path()
        data: dict[str, dict[str, Any]] = {}
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = {str(k): v for k, v in raw.items() if isinstance(v, dict)}
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                data = {}
        changed = False
        for slug, rec in _DEFAULT.items():
            if slug not in data:
                data[slug] = dict(rec)
                changed = True
        if changed:
            _save_locked(data)
        return data


def _save_locked(data: dict[str, dict[str, Any]]) -> None:
    try:
        _registry_path().write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )
    except OSError:
        pass


def _totals_path(slug: str) -> Path:
    safe = _slugify(slug)
    return _LOG_DIR / f"publisher_totals_{safe}.json"


def load_publisher_totals(slug: str) -> dict[str, Any]:
    """Saved totals for one publisher (Mantis mirrors the pull state file)."""
    slug = _slugify(slug)
    if slug == "mantis":
        return _load_mantis_today_core()
    base = dict(_DEFAULT_TOTALS)
    base["date"] = _today()
    path = _totals_path(slug)
    if not path.is_file():
        return base
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return base
    if not isinstance(raw, dict):
        return base
    out = dict(base)
    for key in ("impressions", "clicks"):
        try:
            out[key] = max(0, int(raw.get(key) or 0))
        except (TypeError, ValueError):
            pass
    for key in ("payout_usd", "ecpm", "evcpm"):
        try:
            out[key] = float(raw.get(key) or 0)
        except (TypeError, ValueError):
            pass
    for key in ("receivable_usd", "paid_to_date_usd", "lifetime_earnings_usd"):
        if raw.get(key) in (None, ""):
            out[key] = None
            continue
        try:
            out[key] = float(raw.get(key))
        except (TypeError, ValueError):
            out[key] = None
    out["updated"] = raw.get("updated")
    out["source"] = raw.get("source") or "manual"
    return out


def save_publisher_totals(slug: str, data: dict[str, Any]) -> dict[str, Any]:
    """Persist totals for a non-Mantis publisher. Mantis stays pull-only (core)."""
    slug = _slugify(slug)
    if slug == "mantis":
        raise ValueError("Mantis totals are pull-only (single-Mantis core owns that file)")
    rec = load_registry().get(slug)
    if rec and rec.get("configured"):
        raise ValueError(f"{slug} has a live pull client — totals are pull-only")
    path = _totals_path(slug)
    today = _today()
    cur = load_publisher_totals(slug)
    out = {
        "date": today,
        "impressions": max(0, int(cur.get("impressions") or 0)),
        "clicks": max(0, int(cur.get("clicks") or 0)),
        "payout_usd": float(cur.get("payout_usd") or 0.0),
        "ecpm": float(cur.get("ecpm") or 0.0),
        "evcpm": float(cur.get("evcpm") or 0.0),
        "receivable_usd": cur.get("receivable_usd"),
        "paid_to_date_usd": cur.get("paid_to_date_usd"),
        "lifetime_earnings_usd": cur.get("lifetime_earnings_usd"),
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "manual",
    }
    for key, val in data.items():
        if key in ("date", "updated", "source"):
            continue
        if key in ("impressions", "clicks"):
            try:
                out[key] = max(0, int(val or 0))
            except (TypeError, ValueError):
                pass
        elif key in ("payout_usd", "ecpm", "evcpm", "receivable_usd", "paid_to_date_usd", "lifetime_earnings_usd"):
            if val in (None, ""):
                out[key] = None
                continue
            try:
                out[key] = float(val)
            except (TypeError, ValueError):
                pass
    try:
        path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    return out


def add_publisher(name: str) -> dict[str, Any] | None:
    """Add a publisher record from a display name. Returns the record or None."""
    name = (name or "").strip()
    if not name:
        return None
    slug = _slugify(name)
    if not slug:
        return None
    with _LOCK:
        reg = load_registry()
        if slug in reg:
            rec = dict(reg[slug])
            if rec.get("stub"):
                # Seeded (later) stub gets promoted to a real, addable publisher.
                rec["stub"] = False
                rec["display_name"] = name
                rec["configured"] = bool(rec.get("configured"))
                reg[slug] = rec
                _save_locked(reg)
            return reg[slug]
        reg[slug] = {"display_name": name, "configured": False, "stub": False}
        _save_locked(reg)
        return reg[slug]


def remove_publisher(slug: str) -> bool:
    """Remove a publisher (never Mantis — the single-Mantis core depends on it)."""
    slug = _slugify(slug)
    if slug == "mantis":
        return False
    with _LOCK:
        reg = load_registry()
        if slug not in reg:
            return False
        del reg[slug]
        _save_locked(reg)
    try:
        _totals_path(slug).unlink(missing_ok=True)
    except OSError:
        pass
    return True


def publishers_payload() -> dict[str, Any]:
    """Tab payload: every publisher record + whether it has saved totals today."""
    reg = load_registry()
    pubs: list[dict[str, Any]] = []
    for slug, rec in sorted(reg.items()):
        if rec.get("stub") and not rec.get("configured"):
            continue  # (later) stubs stay hidden until an account client exists
        totals = load_publisher_totals(slug)
        has = bool(
            totals
            and (totals.get("impressions") or totals.get("clicks") or totals.get("payout_usd"))
        )
        pubs.append(
            {
                "slug": slug,
                "display_name": rec.get("display_name") or slug,
                "configured": bool(rec.get("configured")),
                "stub": bool(rec.get("stub")),
                "has_totals": has,
                "updated": totals.get("updated"),
            }
        )
    active = "mantis"
    try:
        state_path = _LOG_DIR / "publisher_active.json"
        if state_path.is_file():
            raw = json.loads(state_path.read_text(encoding="utf-8"))
            if str(raw.get("active") or "") in reg:
                active = str(raw["active"])
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return {"ok": True, "active": active, "publishers": pubs}


def set_active_publisher(slug: str) -> dict[str, Any]:
    reg = load_registry()
    slug = _slugify(slug)
    if slug not in reg:
        slug = "mantis"
    try:
        (_LOG_DIR / "publisher_active.json").write_text(
            json.dumps({"active": slug, "ts": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8",
        )
    except OSError:
        pass
    return publishers_payload()


def total_payload() -> dict[str, Any]:
    """Summed account totals across every configured publisher (the Total tab)."""
    reg = load_registry()
    acc: dict[str, Any] = dict(_DEFAULT_TOTALS)
    acc["date"] = _today()
    acc["source"] = "sum"
    any_data = False
    updated: list[str] = []
    for slug in reg:
        if reg[slug].get("stub") and not reg[slug].get("configured"):
            continue
        t = load_publisher_totals(slug)
        if not (t.get("impressions") or t.get("clicks") or t.get("payout_usd")):
            continue
        any_data = True
        acc["impressions"] = int(acc["impressions"] or 0) + int(t.get("impressions") or 0)
        acc["clicks"] = int(acc["clicks"] or 0) + int(t.get("clicks") or 0)
        acc["payout_usd"] = float(acc.get("payout_usd") or 0.0) + float(t.get("payout_usd") or 0.0)
        acc["paid_to_date_usd"] = _add_opt(acc.get("paid_to_date_usd"), t.get("paid_to_date_usd"))
        acc["receivable_usd"] = _add_opt(acc.get("receivable_usd"), t.get("receivable_usd"))
        if t.get("updated"):
            updated.append(str(t["updated"]))
    if not any_data:
        acc["paid_to_date_usd"] = None
        acc["receivable_usd"] = None
    if any_data and acc.get("impressions"):
        acc["ecpm"] = round(float(acc["payout_usd"] or 0.0) / float(acc["impressions"]) * 1000.0, 4)
    if any_data and acc.get("clicks"):
        acc["evcpm"] = round(float(acc["payout_usd"] or 0.0) / float(acc["clicks"]) * 1000.0, 4)
    acc["updated"] = max(updated) if updated else None
    return {"ok": True, "has_data": any_data, "totals": acc}


def _add_opt(a: Any, b: Any) -> float | None:
    if a is None and b is None:
        return None
    return float(a or 0.0) + float(b or 0.0)


def _load_mantis_today_core() -> dict[str, Any]:
    """Mirror of dash load_mantis_today (date-guarded) so Total sums match the core."""
    path = _LOG_DIR / "mantis_today_state.json"
    base = dict(_DEFAULT_TOTALS)
    base["date"] = _today()
    base["source"] = "mantis_graphql"
    if not path.is_file():
        return base
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return base
    if not isinstance(raw, dict) or str(raw.get("date") or "") != _today():
        return base
    out = dict(base)
    for key in ("impressions", "clicks"):
        try:
            out[key] = max(0, int(raw.get(key) or 0))
        except (TypeError, ValueError):
            pass
    for key in ("payout_usd", "ecpm", "evcpm"):
        try:
            out[key] = float(raw.get(key) or 0)
        except (TypeError, ValueError):
            pass
    for key in ("receivable_usd", "paid_to_date_usd", "lifetime_earnings_usd"):
        if raw.get(key) in (None, ""):
            out[key] = None
            continue
        try:
            out[key] = float(raw.get(key))
        except (TypeError, ValueError):
            out[key] = None
    out["updated"] = raw.get("updated")
    return out
