from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from measure_sequence_runtime_observed import _http_json, _load_steps, _run_one


ROOT = Path(__file__).resolve().parents[1]
AUTOMATION = ROOT / "automation"
DOC_OUT = ROOT / "docs" / "sequence_runtime_retest_probe.generated.md"

SEQUENCES = [
    "open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su.json",
    "close_chrome__open_getdabflow_app__w5s__tap_consent_strip__tap_age_modal__tap_landing_hero__ha5b8ae.json",
    "close_chrome__open_google_com__w4s__tap_google_search_box__type_query_getdabflow__enter__w6s__h153c50.json",
    "close_chrome__open_google_com__w4s__tap_google_search_box__type_query_getdabflow__enter__w6s__hefa78b.json",
    "close_chrome__open_getdabflow_app__w8s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s.json",
    "close_chrome__open_getdabflow_app__w9s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s.json",
]


def _pick_device(phones: list[dict]) -> str | None:
    online = [p for p in phones if p.get("running")]
    if not online:
        return None
    preferred = os.environ.get("PHARMFLOW_RETEST_SERIAL", "").strip()
    if preferred:
        for p in online:
            if p.get("serial") == preferred:
                return preferred
    if len(online) >= 3:
        return str(online[2].get("serial"))
    return str(online[-1].get("serial"))


def _write(lines: list[str]) -> None:
    DOC_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _main() -> int:
    env = os.environ.copy()
    env["PHARMFLOW_HUMAN_VARIATION"] = "0"
    env.setdefault("PHARMFLOW_BIND", "127.0.0.1")
    dash = subprocess.Popen(
        [sys.executable, "dashboard.py"],
        cwd=str(AUTOMATION),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        up = False
        start = time.perf_counter()
        while time.perf_counter() - start < 40:
            line = dash.stdout.readline() if dash.stdout is not None else ""
            if line and "ready" in line.lower():
                up = True
                break
            try:
                _http_json("GET", "/api/config", timeout=2)
                up = True
                break
            except Exception:
                await asyncio.sleep(0.5)

        if not up:
            _write(
                [
                    "# Sequence Runtime Retest Probe (Generated)",
                    "",
                    f"- Generated at: `{datetime.now(timezone.utc).isoformat()}`",
                    "- Status: failed to boot dashboard",
                ]
            )
            return 2

        phones = _http_json("GET", "/api/phones")
        serial = _pick_device(phones)
        if not serial:
            _write(
                [
                    "# Sequence Runtime Retest Probe (Generated)",
                    "",
                    f"- Generated at: `{datetime.now(timezone.utc).isoformat()}`",
                    "- Status: no running phones",
                ]
            )
            return 0

        runs = []
        for seq in SEQUENCES:
            steps = _load_steps(seq)
            gname = f"RETEST-{Path(seq).stem}-{serial.replace(':', '_')}"
            runs.append(await _run_one(gname, serial, seq, steps))
            await asyncio.sleep(1.0)

        lines = [
            "# Sequence Runtime Retest Probe (Generated)",
            "",
            f"- Generated at: `{datetime.now(timezone.utc).isoformat()}`",
            f"- Target serial: `{serial}`",
            "- Method: dashboard `/api/groups/run` + WS done marker",
            "",
            "| Sequence | Expected (s) | Observed (s) | Divergence | Status | ADB error in logs |",
            "|---|---:|---:|---:|---|---|",
        ]
        for r in runs:
            obs = f"{r.observed_seconds:.3f}" if r.observed_seconds is not None else "n/a"
            div = f"{r.divergence_pct:+.2f}%" if r.divergence_pct is not None else "n/a"
            has_adb_error = any("adb failure" in log.lower() for log in r.log_excerpt)
            lines.append(
                f"| `{r.sequence}` | {r.expected_seconds:.3f} | {obs} | {div} | `{r.status}` | "
                f"{'YES' if has_adb_error else 'no'} |"
            )
        lines.append("")
        lines.append("## Log excerpts")
        lines.append("")
        for r in runs:
            lines.append(f"### `{r.sequence}`")
            lines.append(f"- Status: `{r.status}`")
            lines.append(f"- Note: {r.note}")
            if not r.log_excerpt:
                lines.append("- Logs: none captured")
            else:
                for msg in r.log_excerpt:
                    lines.append(f"- `{msg}`")
            lines.append("")
        _write(lines)
        return 0
    finally:
        if dash.poll() is None:
            dash.terminate()
            try:
                dash.wait(timeout=10)
            except subprocess.TimeoutExpired:
                dash.kill()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
