#!/usr/bin/env python3
"""PEF-41: read-only stealth/gate + optional attach. Never start_farm."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

os.environ["CPHARM_FARM_STOP"] = "1"
os.environ["PHARMFLOW_FARM_STOP"] = "1"

root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(r"C:\Users\jsmil\pharmflow")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "tools"))
sys.path.insert(0, str(root / "wizard"))

EXE_BUTTON = (
    "PharmFlow Control Panel -> Phones -> Discover and attach phones "
    "(applies stealth). Then check Start-farm gate status. Do NOT Start farm."
)

out = {
    "ok": False,
    "phone_count": 0,
    "phones": [],
    "stealth_ok": None,
    "funds_ok": None,
    "attach": "skipped",
    "gate": {},
    "audit": {},
    "exe_button": EXE_BUTTON,
    "notes": [],
}


def emit(k: str, v: object) -> None:
    print(f"{k}={v}")


phones: list[str] = []
try:
    from wizard.preflight_core import discover_adb_phones  # type: ignore

    phones = [
        str(s).strip()
        for s in (discover_adb_phones(None, connect_mumu=True) or [])
        if str(s).strip()
    ]
    out["notes"].append("discover=preflight_core.discover_adb_phones")
except Exception as exc:  # noqa: BLE001
    out["notes"].append(f"discover_preflight_err={exc}")
    try:
        raw = subprocess.check_output(
            ["adb", "devices"], text=True, errors="replace", timeout=30
        )
        phones = [ln.split()[0] for ln in raw.splitlines() if "\tdevice" in ln]
        out["notes"].append("discover=adb_devices_fallback")
    except Exception as exc2:  # noqa: BLE001
        out["notes"].append(f"discover_adb_err={exc2}")

out["phones"] = phones
out["phone_count"] = len(phones)
emit("PHONE_COUNT", out["phone_count"])

try:
    from wizard.mumu_farm_ops import audit_fingerprint_all  # type: ignore

    if phones:
        audit = audit_fingerprint_all(phones, None)
        out["audit"] = audit if isinstance(audit, dict) else {"raw": str(audit)}
        if isinstance(audit, dict) and "all_clean" in audit:
            out["stealth_ok"] = bool(audit.get("all_clean"))
        out["notes"].append("audit=mumu_farm_ops.audit_fingerprint_all")
    else:
        out["notes"].append("audit=skipped_no_phones")
except Exception as exc:  # noqa: BLE001
    out["notes"].append(f"audit_err={exc}")

try:
    import farm_start_gate as gate  # type: ignore

    st = gate.evaluate_start_gate(serials=phones or None, apply_stealth_defaults=True)
    out["gate"] = st if isinstance(st, dict) else {"raw": str(st)}
    if isinstance(st, dict):
        if st.get("stealth_ok") is not None:
            out["stealth_ok"] = bool(st.get("stealth_ok"))
        if st.get("funds_ok") is not None:
            out["funds_ok"] = bool(st.get("funds_ok"))
        if st.get("phone_count") is not None:
            out["phone_count"] = int(st.get("phone_count") or out["phone_count"])
        out["notes"].append("gate=farm_start_gate.evaluate_start_gate")
except Exception as exc:  # noqa: BLE001
    out["notes"].append(f"gate_err={exc}")

emit("STEALTH_OK", out["stealth_ok"] if out["stealth_ok"] is not None else "unknown")
emit("FUNDS_OK", out["funds_ok"] if out["funds_ok"] is not None else "unknown")

attach_fn = None
try:
    import cloud_connect as cc  # type: ignore

    attach_fn = getattr(cc, "attach_local_and_cloud_phones", None)
    if attach_fn:
        out["notes"].append("attach_api=tools.cloud_connect.attach_local_and_cloud_phones")
except Exception as exc:  # noqa: BLE001
    out["notes"].append(f"cloud_connect_import_err={exc}")

if attach_fn is None:
    try:
        from wizard import pharmflow_wizard_bridge as bridge  # type: ignore

        attach_fn = getattr(bridge, "attach_local_and_cloud_phones", None)
        if attach_fn:
            out["notes"].append(
                "attach_api=wizard.pharmflow_wizard_bridge.attach_local_and_cloud_phones"
            )
    except Exception as exc:  # noqa: BLE001
        out["notes"].append(f"bridge_import_err={exc}")

if callable(attach_fn):
    try:
        try:
            res = attach_fn(apply_stealth=True)
        except TypeError:
            try:
                res = attach_fn(root=root, apply_stealth=True)
            except TypeError:
                res = attach_fn()
        out["attach"] = "ok" if (isinstance(res, dict) and res.get("ok")) else "fail"
        if isinstance(res, dict):
            if res.get("phones"):
                out["phones"] = list(res.get("phones") or [])
                out["phone_count"] = len(out["phones"])
            if res.get("stealth_ok") is not None:
                out["stealth_ok"] = bool(res.get("stealth_ok"))
            if res.get("stealth") and isinstance(res["stealth"], dict):
                out["audit"] = res["stealth"]
                if "all_clean" in res["stealth"] and out["stealth_ok"] is None:
                    out["stealth_ok"] = bool(res["stealth"].get("all_clean"))
            out["attach_message"] = res.get("message") or res.get("error") or ""
            emit("ATTACH_MSG", (out.get("attach_message") or "")[:240])
        emit("ATTACH", out["attach"])
        try:
            import farm_start_gate as gate2  # type: ignore

            st2 = gate2.evaluate_start_gate(
                serials=out["phones"] or None, apply_stealth_defaults=True
            )
            if isinstance(st2, dict):
                out["gate"] = st2
                if st2.get("stealth_ok") is not None:
                    out["stealth_ok"] = bool(st2.get("stealth_ok"))
                if st2.get("funds_ok") is not None:
                    out["funds_ok"] = bool(st2.get("funds_ok"))
                out["phone_count"] = int(st2.get("phone_count") or out["phone_count"])
                emit(
                    "STEALTH_OK",
                    out["stealth_ok"] if out["stealth_ok"] is not None else "unknown",
                )
                emit(
                    "FUNDS_OK",
                    out["funds_ok"] if out["funds_ok"] is not None else "unknown",
                )
                emit("PHONE_COUNT", out["phone_count"])
        except Exception as exc:  # noqa: BLE001
            out["notes"].append(f"gate_after_attach_err={exc}")
        out["ok"] = out["attach"] == "ok"
    except Exception as exc:  # noqa: BLE001
        out["attach"] = "error"
        out["notes"].append(f"attach_err={exc}")
        emit("ATTACH", "error")
        emit("ATTACH_ERR", str(exc)[:240])
        emit("EXE_BUTTON", out["exe_button"])
else:
    out["attach"] = "missing_api"
    emit("ATTACH", "missing_api")
    emit("EXE_BUTTON", out["exe_button"])
    out["notes"].append("Use EXE button: Discover and attach phones")

emit("PHONE_COUNT", out["phone_count"])
emit("STEALTH_OK", out["stealth_ok"] if out["stealth_ok"] is not None else "unknown")
emit("FUNDS_OK", out["funds_ok"] if out["funds_ok"] is not None else "unknown")
for n in out.get("notes") or []:
    emit("NOTE", str(n)[:200])
print(
    "JSON="
    + json.dumps(
        {
            "ok": out["ok"],
            "phone_count": out["phone_count"],
            "stealth_ok": out["stealth_ok"],
            "funds_ok": out["funds_ok"],
            "attach": out["attach"],
            "phones": out["phones"][:32],
        },
        default=str,
    )
)
print("START_FARM=never")
print("FARM_STOP=1")
