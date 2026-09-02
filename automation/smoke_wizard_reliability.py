#!/usr/bin/env python3
"""
Deterministic checks for wizard reliability fixes (no GUI, no HTTP).

From repo root:

  py -3 automation/smoke_wizard_reliability.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_WIZ = _ROOT / "wizard"


def main() -> int:
    sys.path.insert(0, str(_ROOT))
    sys.path.insert(0, str(_WIZ))

    import setup_wizard as sw  # noqa: E402
    import tor_manager as tm  # noqa: E402

    # ── Python argv resolution (must not treat "py -3" as a single executable) ──
    if sw._split_cmd_string("py -3") != ["py", "-3"]:  # noqa: SLF001
        print("smoke: _split_cmd_string py -3", file=sys.stderr)
        return 1
    st = copy.deepcopy(sw.state)
    disp_out = ""
    try:
        sw.state["python_cmd"] = ""
        sw.state.pop("python_cmd_argv", None)
        argv, disp_out = sw._resolve_python_cmd(None)  # noqa: SLF001
        if not argv or not sw._probe_python_cmd(argv):  # noqa: SLF001
            print("smoke: _resolve_python_cmd failed", argv, disp_out, file=sys.stderr)
            return 1
    finally:
        sw.state.clear()
        sw.state.update(st)

    # ── Group template + first-wins scheduler mapping ──
    st2 = copy.deepcopy(sw.state)
    try:
        sw.state["default_steps"] = [{"tap": {"x": 1, "y": 2, "w": 10, "h": 10}}]
        sw.state["phones"] = [
            {"serial": "emulator-5554", "name": "A"},
            {"serial": "emulator-5556", "name": "B"},
        ]
        sw.state["groups"] = [
            {
                "name": "G1",
                "phones": {
                    "emulator-5554": {
                        "steps": [{"first_group_wins": True}],
                        "hits_per_day": 10,
                        "use_default_template": False,
                        "explicit_override": True,
                    },
                    "emulator-5556": {
                        "steps": [{"wait": {"seconds": 2}}],
                        "hits_per_day": 20,
                        "use_default_template": False,
                        "explicit_override": True,
                    },
                },
                "stagger_secs": 1,
                "repeat": 1,
                "repeat_forever": False,
            },
            {
                "name": "G2",
                "phones": {
                    "emulator-5554": {
                        "steps": [{"ignored_duplicate": True}],
                        "hits_per_day": 99,
                        "use_default_template": False,
                        "explicit_override": True,
                    },
                },
                "stagger_secs": 1,
                "repeat": 1,
                "repeat_forever": False,
            },
        ]
        hits, steps = sw._scheduler_maps_for_serials(  # noqa: SLF001
            ["emulator-5554", "emulator-5556"], 100
        )
        if not steps["emulator-5554"] or not steps["emulator-5554"][0].get("first_group_wins"):
            print("smoke: first-group-wins steps", steps, file=sys.stderr)
            return 1
        if hits["emulator-5554"] != 10:
            print("smoke: first-group-wins hits", hits, file=sys.stderr)
            return 1
        if hits["emulator-5556"] != 20:
            print("smoke: scheduler hits 5556", hits, file=sys.stderr)
            return 1
    finally:
        sw.state.clear()
        sw.state.update(st2)

    # ── Tor preflight returns structured dict (may be ok=False in CI without Tor) ──
    pre = tm.tor_proxy_preflight()
    if not isinstance(pre, dict) or "ok" not in pre:
        print("smoke: tor_proxy_preflight shape", pre, file=sys.stderr)
        return 1

    print(
        "smoke_wizard_reliability: OK  python=%r  tor_preflight_ok=%s"
        % (disp_out, pre.get("ok"))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
