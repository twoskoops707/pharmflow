#!/usr/bin/env python3
"""FREEBUFF task runner — flat $, SSP paying, path3 OK rate. Never kills MuMu."""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = Path(r"C:\PharmFlow\logs")
sys.path.insert(0, str(ROOT))

from automation.agent_unison import claim_task, complete_task, heartbeat, read_board, set_status
from automation.farm_checkin import format_checkin, gather_checkin

AGENT = "freebuff"


def _mantis() -> dict:
    try:
        return json.loads((LOG / "mantis_today_state.json").read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _p3_ok_fail() -> tuple[int, int]:
    fl = LOG / "farm_354.log"
    if not fl.is_file():
        return 0, 0
    try:
        lines = fl.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]
    except OSError:
        return 0, 0
    ok = sum(1 for ln in lines if " P3-AD OK " in ln)
    fail = sum(1 for ln in lines if " P3-AD FAIL " in ln)
    return ok, fail


def _flat_dollar() -> tuple[bool, str]:
    m = _mantis()
    payout = float(m.get("payout_usd") or 0)
    clicks = int(m.get("clicks") or 0)
    impr = int(m.get("impressions") or 0)
    hist = LOG / "freebuff_payout_watch.json"
    row = {"ts": time.time(), "payout_usd": payout, "clicks": clicks, "impressions": impr}
    hist_rows: list[dict] = []
    if hist.is_file():
        try:
            hist_rows = json.loads(hist.read_text(encoding="utf-8-sig"))
            if not isinstance(hist_rows, list):
                hist_rows = []
        except Exception:
            hist_rows = []
    hist_rows.append(row)
    hist_rows = hist_rows[-40:]
    hist.write_text(json.dumps(hist_rows, indent=2) + "\n", encoding="utf-8")
    if len(hist_rows) < 3:
        return False, f"watching payout=${payout} clk={clicks}"
    old = hist_rows[0]
    dp = abs(payout - float(old.get("payout_usd") or 0))
    dc = clicks - int(old.get("clicks") or 0)
    di = impr - int(old.get("impressions") or 0)
    flat = dp < 0.15 and dc == 0 and di > 80
    proof = f"payout=${payout} d$={dp:.2f} dclk={dc} dimpr={di} window={len(hist_rows)}"
    return flat, proof


def _pull_mantis() -> str:
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8091/api/mantis_pull",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode())
        return f"mantis_pull ok payout={data.get('payout_usd')} clk={data.get('clicks')}"
    except Exception as exc:
        return f"mantis_pull_err:{exc}"


def main() -> int:
    tasks_done: list[str] = []
    fixes: list[str] = []

    # ── TASK 1: flat dollar ──
    if claim_task(AGENT, "flat_dollar_fix", ttl_s=90):
        heartbeat(AGENT, task="flat_dollar_fix")
        flat, proof = _flat_dollar()
        fixes.append(f"flat_check {proof}")
        if flat:
            fixes.append("FLAT_DOLLAR_CONFIRMED")
            try:
                from automation.farm_money_monitor import evaluate

                st = evaluate(flat_min=5.0, do_fix=True)
                fixes.extend((st.get("auto_fixes") or [])[-8:])
                fixes.append(f"evaluate alert={st.get('alert')}")
            except Exception as exc:
                fixes.append(f"evaluate_err:{exc}")
            fixes.append(_pull_mantis())
        complete_task(AGENT, "flat_dollar_fix", result="ok")
        tasks_done.append("flat_dollar_fix")

    # ── TASK 2: SSP paying burst ──
    if claim_task(AGENT, "ssp_paying_burst", ttl_s=90):
        heartbeat(AGENT, task="ssp_paying_burst")
        try:
            from automation.dabflow_mantis_client_patch import prefetch_ssp_ads_prefer_paying, ssp_ads_paying_count
            from automation.farm_money_monitor import probe_ssp, write_ssp_force_refresh

            ssp = probe_ssp()
            paying = int(ssp.get("paying") or 0)
            house = int(ssp.get("house") or 0)
            fixes.append(f"ssp_before paying={paying} house={house}")
            fixes.extend(write_ssp_force_refresh(ssp)[:4])
            if paying < 3:
                ads = prefetch_ssp_ads_prefer_paying(
                    attempts=16, delay_s=0.35, allow_house_fallback=False
                )
                paying = ssp_ads_paying_count(ads or [])
                fixes.append(f"prefer_paying_burst paying={paying} n={len(ads or [])}")
            (LOG / "SSP_FORCE_REFRESH.flag").write_text("freebuff_burst", encoding="utf-8")
        except Exception as exc:
            fixes.append(f"ssp_burst_err:{exc}")
        complete_task(AGENT, "ssp_paying_burst", result="ok")
        tasks_done.append("ssp_paying_burst")

    # ── TASK 3: path3 OK monitor ──
    if claim_task(AGENT, "path3_ok_monitor", ttl_s=90):
        heartbeat(AGENT, task="path3_ok_monitor")
        ok, fail = _p3_ok_fail()
        fixes.append(f"path3_log ok={ok} fail={fail}")
        if ok == 0 and fail >= 1:
            # Never pause/kill bottom-ads watcher — that starves money while
            # path3 is recovering. Flag the condition only.
            fixes.append("PATH3_NO_OK_IN_LOG")
            pause = LOG / "PAUSE_BOTTOM_ADS_WATCH.flag"
            if pause.is_file():
                try:
                    pause.unlink()
                    fixes.append("cleared_PAUSE_BOTTOM_ADS_WATCH")
                except OSError:
                    pass
        complete_task(AGENT, "path3_ok_monitor", result="ok")
        tasks_done.append("path3_ok_monitor")

    # ── TASK 4: money tick (legacy) ──
    if claim_task(AGENT, "money_tick", ttl_s=90):
        heartbeat(AGENT, task="money_tick")
        try:
            from automation.farm_money_monitor import probe_ssp

            ssp = probe_ssp()
            fixes.append(f"ssp paying={ssp.get('paying')} house={ssp.get('house')}")
        except Exception as exc:
            fixes.append(f"ssp_err:{exc}")
        complete_task(AGENT, "money_tick", result="ok")
        tasks_done.append("money_tick")

    m = _mantis()
    snap = gather_checkin(fixes=fixes, note="FREEBUFF tasks · emulators untouched")
    set_status(
        payout_usd=m.get("payout_usd"),
        clicks=m.get("clicks"),
        impressions=m.get("impressions"),
        freebuff_tasks_done=tasks_done,
        freebuff_fixes=fixes[-15:],
        money_verdict="flat" if _flat_dollar()[0] else snap.verdict,
    )
    heartbeat(AGENT, task="freebuff_done", extra={"tasks": tasks_done, "fixes": fixes[:8]})

    body = (
        f"FREEBUFF tasks={tasks_done}\n"
        f"${m.get('payout_usd')} clk={m.get('clicks')} impr={m.get('impressions')}\n"
        + "\n".join(fixes[-12:])
        + "\n\n"
        + format_checkin(snap)
    )
    print(body, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
