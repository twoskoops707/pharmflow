from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from websockets.client import connect


ROOT = Path(__file__).resolve().parents[1]
AUTOMATION = ROOT / "automation"
DOC_OUT = ROOT / "docs" / "sequence_runtime_observed.generated.md"
API_BASE = "http://127.0.0.1:8080"
WS_URL = "ws://127.0.0.1:8081"

SEQUENCE_FILES = [
    "open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su.json",
    "google_com__tap_serp__getdabflow_funnel__cleanup.json",
    "close_chrome__open_getdabflow_app__w9s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s.json",
]


def _http_json(method: str, path: str, payload: dict | None = None, timeout: int = 15) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{API_BASE}{path}", data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _load_steps(name: str) -> list[dict]:
    from sequence_normalize import unwrap_sequence_document

    path = AUTOMATION / "recordings" / "sequences" / name
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    steps, _meta = unwrap_sequence_document(raw)
    return steps if isinstance(steps, list) else []


def _expected_seconds(steps: list[dict]) -> float:
    total = 0.0
    for st in steps:
        t = str(st.get("type", ""))
        if t == "wait":
            try:
                total += max(0.0, min(300.0, float(st.get("seconds", 1))))
            except (TypeError, ValueError):
                total += 1.0
        elif t == "tap":
            try:
                pre = float(st.get("pre_wait_ms", 0) or 0) / 1000.0
            except (TypeError, ValueError):
                pre = 0.0
            try:
                retries = int(st.get("retries", 1) or 1)
            except (TypeError, ValueError):
                retries = 1
            retries = max(1, min(retries, 8))
            total += min(pre, 10.0) + max(0, retries - 1) * 0.15
        elif t == "swipe":
            try:
                ms = int(float(st.get("ms", 400)))
            except (TypeError, ValueError):
                ms = 400
            total += max(1, min(ms, 5000)) / 1000.0
        elif t == "open_url":
            pws = st.get("post_wait_secs", None)
            if pws not in (None, ""):
                try:
                    total += min(120.0, max(0.0, float(pws)))
                except (TypeError, ValueError):
                    pass
        # run loop sleeps 0.3s after each step.
        total += 0.3
    return round(total, 3)


@dataclass
class RunResult:
    sequence: str
    serial: str
    expected_seconds: float
    observed_seconds: float | None
    divergence_pct: float | None
    flagged: bool
    started_at: str | None
    ended_at: str | None
    status: str
    note: str
    log_excerpt: list[str]


async def _run_one(group_name: str, serial: str, sequence: str, steps: list[dict]) -> RunResult:
    expected = _expected_seconds(steps)
    log_excerpt: list[str] = []
    done_marker = f"[{group_name}] Done"
    start_iso = datetime.now(timezone.utc).isoformat()
    t0 = time.perf_counter()
    try:
        async with connect(WS_URL, open_timeout=10) as ws:
            response = _http_json(
                "POST",
                "/api/groups/run",
                {
                    "groups": [
                        {
                            "name": group_name,
                            "phones": {serial: {"steps": steps}},
                            "repeat": 1,
                            "repeat_forever": False,
                            "stagger_secs": 0,
                        }
                    ]
                },
                timeout=30,
            )
            if not response.get("ok"):
                return RunResult(
                    sequence=sequence,
                    serial=serial,
                    expected_seconds=expected,
                    observed_seconds=None,
                    divergence_pct=None,
                    flagged=True,
                    started_at=start_iso,
                    ended_at=datetime.now(timezone.utc).isoformat(),
                    status="api_error",
                    note=str(response),
                    log_excerpt=[],
                )
            timeout_secs = max(120.0, expected * 3.5 + 180.0)
            deadline = time.perf_counter() + timeout_secs
            while time.perf_counter() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5)
                except TimeoutError:
                    continue
                payload = json.loads(msg)
                if payload.get("type") == "log":
                    text = str(payload.get("msg", ""))
                    if group_name in text and len(log_excerpt) < 10:
                        log_excerpt.append(text)
                    if done_marker in text:
                        observed = round(time.perf_counter() - t0, 3)
                        div = round(((observed - expected) / expected) * 100.0, 2) if expected > 0 else None
                        return RunResult(
                            sequence=sequence,
                            serial=serial,
                            expected_seconds=expected,
                            observed_seconds=observed,
                            divergence_pct=div,
                            flagged=bool(div is not None and abs(div) > 20.0),
                            started_at=start_iso,
                            ended_at=datetime.now(timezone.utc).isoformat(),
                            status="ok",
                            note="completed",
                            log_excerpt=log_excerpt,
                        )
            return RunResult(
                sequence=sequence,
                serial=serial,
                expected_seconds=expected,
                observed_seconds=None,
                divergence_pct=None,
                flagged=True,
                started_at=start_iso,
                ended_at=datetime.now(timezone.utc).isoformat(),
                status="timeout",
                note=f"did not receive done log within {int(timeout_secs)}s",
                log_excerpt=log_excerpt,
            )
    except Exception as exc:
        return RunResult(
            sequence=sequence,
            serial=serial,
            expected_seconds=expected,
            observed_seconds=None,
            divergence_pct=None,
            flagged=True,
            started_at=start_iso,
            ended_at=datetime.now(timezone.utc).isoformat(),
            status="error",
            note=f"{type(exc).__name__}: {exc}",
            log_excerpt=log_excerpt,
        )


def _write_report(runs: list[RunResult], phones: list[dict]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    flagged = [r for r in runs if r.flagged]
    lines: list[str] = []
    lines.append("# Sequence Runtime Observed (Generated)")
    lines.append("")
    lines.append(f"- Generated at: `{now}`")
    lines.append("- Method: `POST /api/groups/run` + WebSocket log completion marker (`[Group] Done ✓`)")
    lines.append("- Timing basis: wall-clock from API call dispatch to group done log")
    lines.append("- Expected runtime model: step waits + pre-waits + swipe duration + 0.3s inter-step gap (dashboard runner behavior)")
    lines.append("- Divergence flag threshold: `abs(observed-expected)/expected > 20%`")
    lines.append("")
    lines.append("## Devices Observed")
    lines.append("")
    for p in phones:
        lines.append(f"- `{p.get('serial')}` ({p.get('name')}, type={p.get('type')}, running={p.get('running')})")
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append("| Sequence | Serial | Expected (s) | Observed (s) | Divergence | Flag | Status |")
    lines.append("|---|---|---:|---:|---:|---|---|")
    for r in runs:
        obs = f"{r.observed_seconds:.3f}" if r.observed_seconds is not None else "n/a"
        div = f"{r.divergence_pct:+.2f}%" if r.divergence_pct is not None else "n/a"
        lines.append(
            f"| `{r.sequence}` | `{r.serial}` | {r.expected_seconds:.3f} | {obs} | {div} | "
            f"{'YES' if r.flagged else 'no'} | {r.status} |"
        )
    lines.append("")
    lines.append("## Divergences >20%")
    lines.append("")
    if not flagged:
        lines.append("- None")
    else:
        for r in flagged:
            lines.append(
                f"- `{r.sequence}` on `{r.serial}`: expected `{r.expected_seconds:.3f}s`, "
                f"observed `{(r.observed_seconds if r.observed_seconds is not None else 'n/a')}`, "
                f"divergence `{(f'{r.divergence_pct:+.2f}%' if r.divergence_pct is not None else 'n/a')}` "
                f"(status `{r.status}`; note: {r.note})"
            )
    lines.append("")
    lines.append("## Evidence Excerpts")
    lines.append("")
    for r in runs:
        lines.append(f"### `{r.sequence}` on `{r.serial}`")
        lines.append("")
        lines.append(f"- Start: `{r.started_at}`")
        lines.append(f"- End: `{r.ended_at}`")
        lines.append(f"- Status: `{r.status}`")
        lines.append(f"- Note: {r.note}")
        if r.log_excerpt:
            lines.append("- WebSocket logs:")
            for log in r.log_excerpt:
                lines.append(f"  - `{log}`")
        else:
            lines.append("- WebSocket logs: none captured")
        lines.append("")
    DOC_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _main() -> int:
    env = os.environ.copy()
    env["CPHARM_HUMAN_VARIATION"] = "0"
    env.setdefault("CPHARM_BIND", "127.0.0.1")
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
            return 2

        phones = _http_json("GET", "/api/phones")
        online = [p for p in phones if p.get("running")]
        if not online:
            _write_report([], phones)
            return 0

        target_serials = [p["serial"] for p in online][:2]
        runs: list[RunResult] = []
        for seq in SEQUENCE_FILES:
            steps = _load_steps(seq)
            for serial in target_serials:
                gname = f"OBS-{Path(seq).stem}-{serial.replace(':', '_')}"
                runs.append(await _run_one(gname, serial, seq, steps))
                await asyncio.sleep(1.0)
        _write_report(runs, online)
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
