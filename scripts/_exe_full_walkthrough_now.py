"""Full non-destructive deck walkthrough — every major bridge surface.

Does NOT start/stop farm, boot phones, or kill Buffy's money lanes.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Repo root + wizard/ (setup_wizard is imported as a top-level module by the bridge).
_ROOT = Path(__file__).resolve().parents[1]
_WIZARD = _ROOT / "wizard"
for _p in (_ROOT, _WIZARD):
    s = str(_p)
    if s not in sys.path:
        sys.path.insert(0, s)

os.environ.setdefault("PHARMFLOW_AUTOPILOT_PAUSE", "1")

RESULTS: list[dict] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    RESULTS.append({"name": name, "ok": bool(ok), "detail": str(detail)[:400]})
    print(("PASS" if ok else "FAIL"), name, str(detail)[:160], flush=True)


def main() -> int:
    import wizard.pharmflow_wizard_bridge as b
    from automation.farm_exe_self_heal import ensure_tor_binary
    from automation.pharmflow_farm_config import apply_farm_env, reset_runtime, resolve_tor_exe_path
    from wizard.farm_control import apply_profile_farm_env
    from wizard.wizard_paths import groups_config_path, tor_binary_path

    # 1 dual-root money path
    reset_runtime(note="walk")
    tor = Path(resolve_tor_exe_path())
    check("tor_resolve_exists", tor.is_file(), tor)
    env: dict[str, str] = {}
    apply_farm_env(env)
    check("tor_env_exists", Path(env.get("PHARMFLOW_TOR_PATH", "")).is_file(), env.get("PHARMFLOW_TOR_PATH"))
    check("billing_direct_forced_0", env.get("PHARMFLOW_MANTIS_BILLING_DIRECT") == "0", env.get("PHARMFLOW_MANTIS_BILLING_DIRECT"))
    os.environ.pop("PHARMFLOW_FARM_SEQUENCE_ROOT", None)
    apply_profile_farm_env(None)
    root = os.environ.get("PHARMFLOW_FARM_SEQUENCE_ROOT", "")
    hw = sum(1 for _ in Path(root).rglob("*halfway*.json")) if root else 0
    check("sequence_root_halfway", hw > 0, f"{root} hw={hw}")
    check("ensure_tor", any(str(x).startswith("tor_present") or "seeded" in str(x) for x in ensure_tor_binary()), ensure_tor_binary())
    check("wizard_paths_tor", Path(tor_binary_path()).is_file(), tor_binary_path())
    gpath = Path(groups_config_path())
    check("groups_config", gpath.is_file(), gpath)

    # 2 deck read APIs (full surface used by app.js — via PharmFlowAppApi)
    from wizard.pharmflow_app_webview import PharmFlowAppApi

    api = PharmFlowAppApi()
    calls = [
        ("get_journey_state", api.get_journey_state),
        ("scan_prereqs", api.scan_prereqs if hasattr(api, "scan_prereqs") else b.scan_prereqs),
        ("get_android_status", api.get_android_status),
        ("get_machine_capabilities", api.get_machine_capabilities),
        ("get_site_settings", api.get_site_settings),
        ("get_earn_plan", api.get_earn_plan),
        ("get_farm_hud", api.get_farm_hud),
        ("get_farm_health", api.get_farm_health),
        ("get_farm_settings", api.get_farm_settings),
        ("get_groups_detail", api.get_groups_detail),
        ("get_groups_summary", getattr(api, "get_groups_summary", b.get_groups_summary)),
        ("boot_all_status", api.boot_all_status),
        ("farm_status", api.farm_status),
        ("cursor_get_sequence", api.cursor_get_sequence),
        ("get_launch_summary", api.get_launch_summary),
        ("get_automation_info", api.get_automation_info),
        ("agent_status", api.agent_status),
    ]
    for name, fn in calls:
        try:
            data = fn()
        except Exception as exc:  # noqa: BLE001
            check(name, False, f"{type(exc).__name__}: {exc}")
            continue
        ok = data is not None and (
            (isinstance(data, dict) and (data.get("ok", True) is not False or "steps" in data or "error" in data))
            or isinstance(data, list)
        )
        detail: object
        if isinstance(data, dict):
            detail = {k: data.get(k) for k in list(data)[:10]}
        elif isinstance(data, list):
            detail = f"list len={len(data)}"
        else:
            detail = type(data).__name__
        check(name, ok, detail)

    # 3 prereq tor specifically
    prereqs = b.scan_prereqs()
    tor_row = next((x for x in prereqs if isinstance(x, dict) and x.get("key") == "tor"), None)
    check("prereq_tor_ok", bool(tor_row and tor_row.get("ok")), tor_row)

    # 3b honesty rails (Path3 / Tor SOCKS / Groups ADB / dual-root adb)
    paths = str(env.get("PHARMFLOW_FARM_PATHS") or "")
    cap = int(float(str(env.get("PHARMFLOW_FARM_PATH3_DAILY_CAP") or 0) or 0))
    socks = int(float(str(env.get("PHARMFLOW_TOR_SOCKS_BASE") or 0) or 0))
    check("path3_in_paths", "3" in {p.strip() for p in paths.split(",") if p.strip()}, paths)
    check("path3_daily_cap_nonzero", cap > 0, cap)
    check("tor_socks_not_9050_when_live", socks != 9050 or socks == 0, socks)
    # Prefer live broadcast when present; 9550 is the Hyper-V-safe farm base.
    try:
        bases = []
        for bp in (
            Path(r"C:\PharmFlow\logs\tor_port_bases.json"),
            Path(r"C:\CPharm\logs\tor_port_bases.json"),
        ):
            if bp.is_file():
                bases.append(json.loads(bp.read_text(encoding="utf-8-sig")))
        live_socks = 0
        if bases:
            live_socks = int(float(str(sorted(bases, key=lambda d: float(d.get("mtime") or 0), reverse=True)[0].get("socks_base") or 0)))
            # files may not carry mtime field — fall back to freshest file mtime above via apply_farm_env
        if live_socks > 0:
            check("tor_socks_matches_broadcast", socks == live_socks, f"env={socks} live={live_socks}")
        else:
            check("tor_socks_safe_default", socks in {9550, 0} or socks > 9050, socks)
    except Exception as exc:  # noqa: BLE001
        check("tor_socks_broadcast_read", False, exc)

    from automation.farm_exe_self_heal import adb_live_serials
    from wizard.wizard_paths import bundled_adb_path

    adb_path = Path(bundled_adb_path())
    live = list(adb_live_serials(timeout=4.0) or [])
    groups = b.get_groups_detail()
    hud = b.get_farm_hud()
    check("adb_resolver_exists", adb_path.is_file(), adb_path)
    check(
        "groups_connected_matches_adb",
        int(groups.get("connected_phones") or 0) == len(live),
        f"groups={groups.get('connected_phones')} adb={len(live)}",
    )
    # HUD may also count operator-dash rows; when ADB is empty both should be 0.
    if not live:
        check(
            "hud_phones_zero_when_adb_empty",
            int(hud.get("phones_online") or 0) == 0,
            hud.get("phones_online"),
        )
    else:
        check(
            "hud_phones_nonzero_when_adb_live",
            int(hud.get("phones_online") or 0) >= len(live),
            f"hud={hud.get('phones_online')} adb={len(live)}",
        )

    # Start/Stop honesty: Stop must takeover external python (policy aligned with Start).
    import inspect

    stop_src = inspect.getsource(b.stop_farm_from_app)
    check(
        "stop_farm_takeovers_external",
        "stop_external_python_farm" in stop_src and "does not kill that money path" not in stop_src,
        "policy_source",
    )

    # 4 connector: critical API methods bound on the deck object
    for meth in (
        "get_journey_state",
        "boot_all_phones",
        "start_farm",
        "stop_farm",
        "get_farm_hud",
        "get_earn_plan",
        "get_groups_detail",
        "open_farm_dashboard",
        "get_farm_settings",
        "save_farm_settings",
    ):
        check(f"api_has_{meth}", callable(getattr(api, meth, None)), meth)

    out = Path(r"C:\PharmFlow\logs\exe_full_walkthrough.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    failed = [r for r in RESULTS if not r["ok"]]
    print("---", flush=True)
    print(f"TOTAL {len(RESULTS)} FAIL {len(failed)} -> {out}", flush=True)
    for row in failed:
        print("FAIL_DETAIL", row["name"], row["detail"], flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
