"""Non-destructive EXE feature surface smoke — no Start farm / Boot all / Stop farm."""
from __future__ import annotations

import json
import os
import traceback
from pathlib import Path

os.environ.setdefault("PHARMFLOW_AUTOPILOT_PAUSE", "1")

results: list[dict] = []


def check(name: str, fn) -> None:
    try:
        ok, detail = fn()
        results.append({"name": name, "ok": bool(ok), "detail": str(detail)[:500]})
        print(("PASS" if ok else "FAIL"), name, str(detail)[:180], flush=True)
    except Exception as exc:  # noqa: BLE001
        results.append({"name": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"})
        print("FAIL", name, type(exc).__name__, exc, flush=True)
        traceback.print_exc()


def t_tor_resolve():
    from automation.pharmflow_farm_config import apply_farm_env, reset_runtime, resolve_tor_exe_path

    reset_runtime(note="smoke")
    path = Path(resolve_tor_exe_path())
    env: dict[str, str] = {}
    apply_farm_env(env)
    tor_path = Path(env.get("PHARMFLOW_TOR_PATH", ""))
    return path.is_file() and tor_path.is_file(), f"resolve={path} env={tor_path}"


def t_seq_root():
    from wizard.farm_control import apply_profile_farm_env

    os.environ.pop("PHARMFLOW_FARM_SEQUENCE_ROOT", None)
    apply_profile_farm_env(None)
    root = os.environ.get("PHARMFLOW_FARM_SEQUENCE_ROOT", "")
    halfway = sum(1 for _ in Path(root).rglob("*halfway*.json")) if root else 0
    return bool(root) and halfway > 0, f"root={root} halfway={halfway}"


def t_billing_direct():
    from wizard.farm_control import apply_profile_farm_env

    apply_profile_farm_env(None)
    val = os.environ.get("PHARMFLOW_MANTIS_BILLING_DIRECT")
    return val == "0", val


def t_self_heal_tor_cands():
    from automation.farm_exe_self_heal import _TOR_SEED_CANDIDATES

    texts = [str(p).lower().replace("/", "\\") for p in _TOR_SEED_CANDIDATES]
    return (
        any("cpharm" in t for t in texts)
        and any(Path(p).is_file() for p in _TOR_SEED_CANDIDATES),
        texts,
    )


def t_wizard_paths_tor():
    from wizard.wizard_paths import groups_config_path, tor_binary_path

    tor = Path(tor_binary_path())
    groups = groups_config_path()
    return tor.is_file(), f"tor={tor} groups={groups} exists={Path(groups).is_file()}"


def t_earn_plan():
    import wizard.pharmflow_wizard_bridge as bridge

    data = bridge.get_earn_plan()
    return isinstance(data, dict), list(data)[:12] if isinstance(data, dict) else data


def t_journey():
    import wizard.pharmflow_wizard_bridge as bridge

    data = bridge.get_journey_state()
    if not isinstance(data, dict):
        return False, data
    steps = data.get("steps")
    ok = isinstance(steps, list) and len(steps) >= 5 and all(
        isinstance(s, dict) and s.get("id") for s in steps
    )
    return ok, {"step_count": len(steps) if isinstance(steps, list) else 0, "keys": list(data)[:8]}


def t_hud():
    import wizard.pharmflow_wizard_bridge as bridge

    data = bridge.get_farm_hud()
    blob = json.dumps(data).lower() if isinstance(data, dict) else ""
    return isinstance(data, dict) and (
        "ok" in data or "phones" in data or "farm" in blob or "status" in blob
    ), list(data)[:20] if isinstance(data, dict) else data


def t_groups():
    import wizard.pharmflow_wizard_bridge as bridge

    for name in ("get_groups", "groups_state", "load_groups", "get_groups_detail"):
        fn = getattr(bridge, name, None)
        if callable(fn):
            data = fn()
            return isinstance(data, (dict, list)), f"{name}={type(data).__name__}"
    from wizard.wizard_paths import groups_config_path

    path = Path(groups_config_path())
    return path.is_file(), f"path={path}"


def t_site_settings():
    import wizard.pharmflow_wizard_bridge as bridge

    data = bridge.get_site_settings()
    return isinstance(data, dict), list(data)[:15] if isinstance(data, dict) else data


def t_scan_prereqs():
    import wizard.pharmflow_wizard_bridge as bridge

    data = bridge.scan_prereqs()
    return isinstance(data, list) and len(data) > 0, data[:5] if isinstance(data, list) else data


def t_android_status():
    import wizard.pharmflow_wizard_bridge as bridge

    data = bridge.get_android_status()
    return isinstance(data, dict), list(data)[:15] if isinstance(data, dict) else data


def t_boot_status():
    import wizard.pharmflow_wizard_bridge as bridge

    data = bridge.boot_all_status()
    return isinstance(data, dict), list(data)[:20] if isinstance(data, dict) else data


def t_heal_dry():
    from automation.farm_exe_self_heal import ensure_tor_binary

    fixes = ensure_tor_binary()
    ok = any(
        str(item).startswith("tor_present") or "seeded" in str(item) or "healed" in str(item)
        for item in fixes
    )
    return ok, fixes


def t_next_exe():
    path = Path(r"C:\PharmFlow\PharmFlow.next.exe")
    return path.is_file() and path.stat().st_size > 100_000_000, (
        f"size={path.stat().st_size if path.is_file() else 0}"
    )


def main() -> int:
    for name, fn in [
        ("next_exe_present", t_next_exe),
        ("tor_ssot_resolve", t_tor_resolve),
        ("sequence_root_halfway", t_seq_root),
        ("billing_direct_0", t_billing_direct),
        ("self_heal_cpharm_seeds", t_self_heal_tor_cands),
        ("wizard_paths_tor_groups", t_wizard_paths_tor),
        ("ensure_tor_binary", t_heal_dry),
        ("bridge_earn_plan", t_earn_plan),
        ("bridge_journey", t_journey),
        ("bridge_farm_hud", t_hud),
        ("bridge_groups", t_groups),
        ("bridge_site_settings", t_site_settings),
        ("bridge_scan_prereqs", t_scan_prereqs),
        ("bridge_android_status", t_android_status),
        ("bridge_boot_status", t_boot_status),
    ]:
        check(name, fn)

    out = Path(r"C:\PharmFlow\logs\exe_feature_smoke.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    failed = [row for row in results if not row["ok"]]
    print("---", flush=True)
    print(f"TOTAL {len(results)} FAIL {len(failed)} -> {out}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
