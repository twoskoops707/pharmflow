"""Operator health audit — detect AND fix (not spectate).

Writes C:\\PharmFlow\\logs\\FARM_MONITOR_ALERTS.jsonl + FARM_MONITOR_NOW.txt
and ntfy on critical alerts (rate-limited). Critical findings trigger
apply_money_rails / prefer-paying / dash respawn — turn the heat down,
don't just announce dinner is burnt.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import automation.no_window  # noqa: F401  — hide helper consoles
from automation.farm_visit_caps import enforce_multi_browser

LOG = Path(os.environ.get("PHARMFLOW_LOGS") or r"C:\PharmFlow\logs")
ROOT = Path(__file__).resolve().parents[1]
ALERTS = LOG / "FARM_MONITOR_ALERTS.jsonl"
NOW = LOG / "FARM_MONITOR_NOW.txt"
HEAT_FLAG_NAME = "FARM_HEAT_DOWN.flag"
HEAT_FLAG = LOG / HEAT_FLAG_NAME
NTFY_STAMP = LOG / "_last_monitor_ntfy_ts.txt"
NTFY_TOPIC = os.environ.get("PHARMFLOW_NTFY_TOPIC", "twskoops").strip() or "twskoops"
NTFY_MIN_GAP_S = float(os.environ.get("PHARMFLOW_MONITOR_NTFY_GAP_S", "900"))  # 15m

try:
    from automation.dabflow_mantis_client_patch import (
        clear_ssp_cache,
        prefetch_ssp_ads_prefer_paying,
        ssp_ads_paying_count,
    )
except Exception:  # noqa: BLE001 — optional at import time
    clear_ssp_cache = None  # type: ignore[assignment]
    prefetch_ssp_ads_prefer_paying = None  # type: ignore[assignment]
    ssp_ads_paying_count = None  # type: ignore[assignment]

HOLD = {
    "ipv": "21.64",
    "est_impr": "12000",
    "seqs": "60",
    "visits": "999,999,999,999,999,999",
    "ads": "300,300,300,300,300,300",
    "path3_daily": "9999",
    "path3_hour": "60",
}
# House-only / dilution: cut Path1/2 volume. Path3 keys stay parallel
# (gap 0 / per_hour 60 / cap = ads_sum) — GO BIG never the old 24-cap drip.
HEAT_DOWN = {
    "ipv": "21.64",
    "est_impr": "16000",
    "seqs": "60",
    "visits": "999,999,999,999,999,999",
    "ads": "300,300,300,300,300,300",
    "path3_daily": "9999",
    "path3_hour": "60",
}
# Behind ($/clicks): GO BIG — money-monitor rails must never re-lower caps.
BEHIND_ADS_UNEVEN = "300,295,290,285,280,275,270,265,260,255,250"
BEHIND_VISITS = "999,999,999,999,999,999,999,999,999"
BEHIND_PATH3_PER_HOUR = "60"
BEHIND_PATH3_CAP_FLOOR = 3000
# Auditor flags SEQS_TOO_HIGH when seqs > 36 (house-spam pace).
HOUSE_SPAM_SEQ_CAP = 36


def scale_csv(template: str, n: int, *, min_val: int = 40, step: int = 5) -> str:
    """Pad or trim a per-phone CSV to n slots so a 9-phone farm isn't 6-wide."""
    parts = [p.strip() for p in str(template).split(",") if p.strip()]
    n = max(1, int(n))
    if not parts:
        parts = [str(min_val)]
    out = list(parts)
    try:
        last = int(out[-1])
    except ValueError:
        last = min_val
        out = [str(last)]
    while len(out) < n:
        if step:
            last = max(min_val, last - step)
        out.append(str(last))
    return ",".join(out[:n])


def ads_csv_all_equal(csv: str) -> bool:
    """True when every per-phone ad budget is identical (clone farm — refuse for behind)."""
    parts = [p.strip() for p in str(csv or "").split(",") if p.strip()]
    if len(parts) < 2:
        return False
    return len(set(parts)) == 1


def _ads_csv_sum(csv: str) -> int:
    total = 0
    for part in str(csv or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            total += max(0, int(float(part)))
        except ValueError:
            continue
    return total


def scale_uneven_ads(template: str, n: int, *, min_val: int = 36) -> str:
    """Scale an uneven ads CSV; when padding past template, cycle (never flat clone)."""
    parts = [p.strip() for p in str(template).split(",") if p.strip()]
    n = max(1, int(n))
    if not parts:
        parts = [str(min_val)]
    out: list[str] = []
    i = 0
    while len(out) < n:
        raw = parts[i % len(parts)]
        try:
            val = max(min_val, int(float(raw)))
        except ValueError:
            val = min_val
        out.append(str(val))
        i += 1
    return ",".join(out)


def _phone_n_from_ov(ov: dict) -> int:
    sticky_names = [
        p.strip()
        for p in str(ov.get("PHARMFLOW_FARM_PHONES") or "").split(",")
        if p.strip()
    ]
    raw = str(ov.get("PHARMFLOW_FARM_PHONE_COUNT") or ov.get("PHARMFLOW_FARM_EXPECT_PHONES") or "9")
    try:
        sticky_n = int(float(raw))
    except ValueError:
        sticky_n = 9
    # No cap: the operator's count is the fleet size, period. Floor at 1 so a
    # mis-typed 0 still yields a runnable farm instead of a silent no-op.
    return max(len(sticky_names), sticky_n, 1)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _heat_flag() -> Path:
    return LOG / HEAT_FLAG_NAME


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _ntfy(msg: str) -> str:
    try:
        if NTFY_STAMP.is_file() and (time.time() - NTFY_STAMP.stat().st_mtime) < NTFY_MIN_GAP_S:
            return "ntfy_skipped_cooldown"
    except OSError:
        pass
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=msg.encode("utf-8"),
            method="POST",
            headers={
                "Title": "PharmFlow MONITOR",
                "Priority": "high",
                "Tags": "warning,rotating_light",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            r.read()
        NTFY_STAMP.write_text(_utc(), encoding="utf-8")
        return "ntfy_sent"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return f"ntfy_err:{exc}"


def utc_clicks_and_payout(profit: dict | None = None) -> tuple[int, float]:
    """UTC-day Mantis clicks + payout from profit dict or mantis_today_state.json."""
    src = profit if isinstance(profit, dict) and profit else _load_json(LOG / "mantis_today_state.json")
    try:
        clicks = int(float(src.get("clicks") or src.get("click_count") or 0))
    except (TypeError, ValueError):
        clicks = 0
    try:
        payout = float(src.get("payout_usd") or src.get("payout") or 0)
    except (TypeError, ValueError):
        payout = 0.0
    return clicks, payout


def behind_on_path3_clicks(
    clicks: int | None = None,
    payout_usd: float | None = None,
    *,
    profit: dict | None = None,
) -> bool:
    """UTC catch-up: keep Path3 pushed until the day is past early-morning drip.

    Thresholds are intentionally above a single good hour ($5 / 15 clicks) so
    remediate does not slam Path3 back to 8/hr mid-morning while still far
    under the daily floor.
    """
    if clicks is None or payout_usd is None:
        c, p = utc_clicks_and_payout(profit)
        if clicks is None:
            clicks = c
        if payout_usd is None:
            payout_usd = p
    return int(clicks or 0) < 40 or float(payout_usd or 0) < 15.0


def rails_for_mode(
    mode: str,
    *,
    clicks: int | None = None,
    payout_usd: float | None = None,
    profit: dict | None = None,
) -> dict[str, str]:
    """HEAT_DOWN Path1/2 cut only when clicks already exist. Else HOLD."""
    if (
        str(mode or "").strip().lower() == "heat_down"
        and not behind_on_path3_clicks(clicks, payout_usd, profit=profit)
    ):
        return dict(HEAT_DOWN)
    return dict(HOLD)


def apply_money_rails(
    *,
    mode: str = "hold",
    reason: str = "",
    clicks: int | None = None,
    payout_usd: float | None = None,
    profit: dict | None = None,
) -> list[str]:
    """Enforce sticky + caps + site lock + panel env. mode=hold|heat_down."""
    fixes: list[str] = []
    behind = behind_on_path3_clicks(clicks, payout_usd, profit=profit)
    # UTC $0 / clicks 0 is not dilution — heat_down must not serialize Path3
    # or cut seqs to 10/14. HOLD Path3 (gap 0, cap=ads_sum, seqs 20).
    effective = "hold" if (mode == "heat_down" and behind) else mode
    rails = rails_for_mode(effective, clicks=clicks, payout_usd=payout_usd, profit=profit)
    tag = f"rails_{mode}" + (f":{reason}" if reason else "")
    if mode == "heat_down" and behind:
        tag = f"rails_hold:zero_click_override:{reason or 'heat_down'}"

    from automation.pharmflow_farm_config import get_runtime, merge_runtime, write_adb_serial_lock

    ov = get_runtime()
    n = _phone_n_from_ov(ov)
    # When behind on clicks/$, push per-phone Path3 ads hard (money day).
    # Uneven template only — never identical 36×N clones (under-radar).
    if behind:
        ads = scale_uneven_ads(BEHIND_ADS_UNEVEN, n, min_val=36)
        visits = scale_csv(BEHIND_VISITS, n)
    else:
        visits = scale_csv(rails["visits"], n)
        ads = scale_csv(rails["ads"], n, min_val=16, step=0)
    ads_sum = _ads_csv_sum(ads)
    # Farm-wide Path3 ceiling = sum of per-phone ad budgets (not the old 24/48 drip).
    path3_daily = str(ads_sum or rails["path3_daily"])
    path3_hr = str(rails["path3_hour"])
    seqs = str(rails["seqs"])
    dwell_min = "3.5"
    dwell_max = "7.0"
    pace_overrides: dict[str, str] = {}
    try:
        from automation.farm_visit_caps import _money_path3_floor

        _cap_f, _hr_f, _gap_f = _money_path3_floor(LOG)
        if _hr_f > int(path3_hr):
            path3_hr = str(_hr_f)
        try:
            if int(float(seqs)) < 36 and behind:
                seqs = "36"
        except (TypeError, ValueError):
            pass
        path3_daily = str(
            max(
                int(path3_daily or 0),
                int(_cap_f or 0),
                ads_sum,
                BEHIND_PATH3_CAP_FLOOR if behind else 0,
            )
        )
        # Prefer aggressive-floor ads CSV when it is uneven and budgets more Path3.
        # Never adopt a flat clone CSV from a prior bad write.
        money = _load_json(LOG / "_money_day_path3_aggressive.json")
        floor_ads = str(money.get("ads") or "").strip()
        if floor_ads and not ads_csv_all_equal(floor_ads):
            floor_sum = _ads_csv_sum(floor_ads)
            if floor_sum > ads_sum:
                ads = scale_uneven_ads(floor_ads, n, min_val=36)
                ads_sum = _ads_csv_sum(ads)
                path3_daily = str(
                    max(
                        int(path3_daily or 0),
                        ads_sum,
                        int(_cap_f or 0),
                        BEHIND_PATH3_CAP_FLOOR if behind else 0,
                    )
                )
        # Hard money-day lock — never undercut while operator lock file is present.
        # Prefer uneven ads from aggressive file; never overwrite with flat min_ad×N.
        lock = _load_json(LOG / "_money_day_lock.json")
        if lock.get("lock"):
            min_cap = int(float(lock.get("min_path3_cap") or BEHIND_PATH3_CAP_FLOOR))
            min_hr = int(float(lock.get("min_path3_per_hour") or int(BEHIND_PATH3_PER_HOUR)))
            min_ad = int(float(lock.get("min_ads_each") or 36))
            path3_daily = str(
                max(
                    int(path3_daily or 0),
                    min_cap,
                    BEHIND_PATH3_CAP_FLOOR if behind else 0,
                )
            )
            path3_hr = str(max(int(path3_hr or 0), min_hr))
            money_ads = str(
                (_load_json(LOG / "_money_day_path3_aggressive.json") or {}).get("ads")
                or ""
            ).strip()
            if money_ads and not ads_csv_all_equal(money_ads):
                ads = scale_uneven_ads(money_ads, n, min_val=min_ad)
            elif behind:
                ads = scale_uneven_ads(BEHIND_ADS_UNEVEN, n, min_val=min_ad)
            else:
                # Caught-up + lock but no uneven CSV: keep HOLD-style stagger, not clones.
                ads = scale_csv(rails["ads"], n, min_val=min_ad, step=0)
            ads_sum = _ads_csv_sum(ads)
            path3_daily = str(max(int(path3_daily or 0), ads_sum, min_cap))
            min_seqs = int(float(lock.get("min_seqs_per_hour") or 0))
            # No ceiling: take the higher of current pace and the lock minimum —
            # the operator's speed is the speed (HOUSE_SPAM_SEQ_CAP removed).
            seqs = str(
                max(int(float(seqs or 0)), min_seqs if min_seqs else int(rails["seqs"]))
            )
            pace = lock.get("pace") if isinstance(lock.get("pace"), dict) else {}
            for pk, pv in pace.items():
                if pv is not None and str(pv).strip():
                    pace_overrides[str(pk)] = str(pv)
    except Exception:
        pass
    try:
        # No seq ceiling: the operator's pace is the pace. (The old
        # HOUSE_SPAM_SEQ_CAP silently re-wrote anything above 36.)
        _ = int(float(seqs or 0))
    except (TypeError, ValueError):
        pass
    if behind:
        path3_daily = str(
            max(int(path3_daily or 0), ads_sum, BEHIND_PATH3_CAP_FLOOR)
        )
    want_ov = {
        "PHARMFLOW_IPV_STICKY": rails["ipv"],
        "PHARMFLOW_FARM_IMPRESSIONS_PER_VISIT": rails["ipv"],
        "PHARMFLOW_FARM_EST_IMPRESSIONS": rails["est_impr"],
        "PHARMFLOW_FARM_SEQS_PER_HOUR": seqs,
        "PHARMFLOW_FARM_DAILY_VISITS": visits,
        "PHARMFLOW_FARM_DAILY_ADS": ads,
        "PHARMFLOW_FARM_PHONE_COUNT": str(n),
        "PHARMFLOW_FARM_EXPECT_PHONES": str(n),
        "PHARMFLOW_FARM_PATH3_DAILY_CAP": path3_daily,
        "PHARMFLOW_PATH3_DAILY_CAP": path3_daily,
        "PHARMFLOW_FARM_PATH3_PER_HOUR": path3_hr,
        "PHARMFLOW_PATH3_PER_HOUR": path3_hr,
        "PHARMFLOW_PATH3_CAP": path3_daily,
        "PHARMFLOW_FARM_PATH3_PREEMPT_MIN": "2",
        # 0 = phones run Path3 in parallel. Unique-seq still blocks the same ad.
        "PHARMFLOW_FARM_PATH3_GLOBAL_GAP_MIN": "0",
        "PHARMFLOW_PATH3_GAP_MIN": "0",
        "PHARMFLOW_FARM_PATH3_SPACING": "1" if behind else "2",
        "PHARMFLOW_FARM_PATH3_PHONE_OFFSET": "1",
        "PHARMFLOW_FARM_PATH3_LEAD_MIN": "0",
        "PHARMFLOW_PREFER_PAYING": "1",
        "PHARMFLOW_SSP_PREFER_PAYING": "1",
        "PHARMFLOW_PATH3_REQUIRE_PAYING": "0",
        "PHARMFLOW_FARM_ALLOW_ADS": "1",
        "PHARMFLOW_FARM_PATHS": "1,2,3",
        "PHARMFLOW_FARM_PATH3": "1",
        "PHARMFLOW_PATH3": "1",
        "PHARMFLOW_FARM_UNIQUE_SEQ": "1",
        "PHARMFLOW_FARM_IMMEDIATE_START": "1",
        # Keep autopilot PAUSED — its click caps (40 hard / 35 soft) killed Path3
        # revenue. The money monitor owns pacing now; never re-enable the LLM AP.
        "PHARMFLOW_AUTOPILOT_PAUSE": "1",
        "PHARMFLOW_FARM_STOP": "0",
        "PHARMFLOW_EMULATOR_AD_FALLBACK": "1",
        "PHARMFLOW_EMULATOR_AD_FORCE_DIRECT": "1",
        "PHARMFLOW_SKIP_SEQUENCE_ISOLATION": "0",
        "PHARMFLOW_FARM_START_STAGGER_WINDOW": "45",
        "PHARMFLOW_FARM_START_STAGGER_BAND": "45",
        "PHARMFLOW_FARM_START_STAGGER_MIN_GAP": "5",
        "PHARMFLOW_FARM_SLOT_MIN_LEAD": "0" if behind else "30",
        "PHARMFLOW_EMULATOR_AD_FILL_WAIT": "2.8",
        "PHARMFLOW_DABFLOW_LOAD_WAIT": "3.8",
        "PHARMFLOW_AGE_GATE_WAIT": "0.55",
        "PHARMFLOW_START_DAB_VERIFY_WAIT": "1.7",
        "PHARMFLOW_AD_DWELL_MIN": dwell_min,
        "PHARMFLOW_AD_DWELL_MAX": dwell_max,
        # CRITICAL: inject/proxy/patch settings MUST be enforced every tick.
        # These were repeatedly clobbered to 0 by stale panel env merge in save_panel,
        # killing creative paint and routing all traffic from the host IP.
        "PHARMFLOW_MANTIS_INJECT_PROXY": "1",
        "PHARMFLOW_MANTIS_INJECT_MITM": "1",
        "PHARMFLOW_MANTIS_BILLING_DIRECT": "0",
        "PHARMFLOW_SKIP_MANTIS_PATCH": "0",
        "PHARMFLOW_DABFLOW_MANTIS_PATCH": "1",
        "PHARMFLOW_EMULATOR_AD_MODE": "1",
    }
    for pk, pv in pace_overrides.items():
        want_ov[pk] = pv
    if mode == "heat_down" and not behind:
        # House-only with existing clicks: cut Path1/2 volume only.
        want_ov["PHARMFLOW_PATH3_REQUIRE_PAYING"] = "0"
        want_ov["PHARMFLOW_FARM_PATH3_PER_HOUR"] = "8"
        want_ov["PHARMFLOW_PATH3_PER_HOUR"] = "8"
        want_ov["PHARMFLOW_EMULATOR_AD_FALLBACK"] = "1"
        want_ov["PHARMFLOW_EMULATOR_AD_FORCE_DIRECT"] = "1"
        try:
            _heat_flag().write_text(
                json.dumps({"ts": _utc(), "reason": reason or "heat_down", "rails": rails}, indent=2)
                + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass
    elif (mode == "hold" or behind) and _heat_flag().is_file():
        try:
            _heat_flag().unlink(missing_ok=True)
            fixes.append("heat_flag_cleared")
        except OSError:
            pass

    from automation.pharmflow_farm_config import merge_runtime

    changed = merge_runtime(want_ov, note=tag)
    if changed:
        fixes.append(f"{tag}_ssot")

    if not fixes:
        fixes.append(f"{tag}_noop_already")
    return fixes


def _prefer_paying_burst() -> list[str]:
    fixes: list[str] = []
    if clear_ssp_cache is None or prefetch_ssp_ads_prefer_paying is None:
        return ["FIX_prefer_paying_unavailable"]
    try:
        clear_ssp_cache()
        ads = prefetch_ssp_ads_prefer_paying(
            attempts=14, delay_s=0.4, allow_house_fallback=False
        )
        paying = ssp_ads_paying_count(ads or []) if ssp_ads_paying_count else 0
        fixes.append(f"FIX_prefer_paying_burst paying={paying} n={len(ads or [])}")
        (LOG / "SSP_FORCE_REFRESH.flag").write_text(
            json.dumps({"paying": paying, "ts": _utc(), "src": "health_audit"}, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        fixes.append(f"FIX_prefer_paying_err:{exc}")
    return fixes


def _ensure_dash_process() -> list[str]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8091/api/status", timeout=3) as r:
            r.read(64)
        return []
    except Exception:
        pass
    dash = ROOT / "scripts" / "farm_operator_dash.py"
    if not dash.is_file():
        return ["FIX_dash_missing_script"]
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    if not Path(pyw).is_file():
        pyw = sys.executable
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    flags = 0x00000008 | 0x00000200 | 0x08000000
    proc = subprocess.Popen(
        [pyw, "-u", str(dash)],
        cwd=str(ROOT),
        env=env,
        creationflags=flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return [f"FIX_spawn_dash pid={proc.pid}"]


def _sync_panel_phones_from_sticky() -> list[str]:
    ov = _load_json(LOG / "farm_runtime_overrides.json")
    phones_csv = str(ov.get("PHARMFLOW_FARM_PHONES") or "")
    serials_csv = str(ov.get("PHARMFLOW_ADB_SERIALS") or "")
    if not phones_csv or not serials_csv:
        return []
    names = [p.strip() for p in phones_csv.split(",") if p.strip()]
    serials = [s.strip() for s in serials_csv.split(",") if s.strip()]
    if len(names) < 4:
        return []
    phone_list = []
    for i, name in enumerate(names):
        ser = serials[i] if i < len(serials) else ""
        phone_list.append({"name": name, "serial": ser})
    fixes: list[str] = []
    for panel_name in ("farm_operator_panel.json", "farm_panel_state.json"):
        panel_path = LOG / panel_name
        panel = _load_json(panel_path)
        if not panel:
            continue
        cur = panel.get("phones") or []
        if len(cur) >= len(phone_list):
            continue
        panel["phones"] = phone_list
        panel["updated"] = _utc()
        _write_json(panel_path, panel)
        fixes.append(f"FIX_panel_phones_n={len(phone_list)}:{panel_name}")
    return fixes


def remediate(
    *,
    critical: list[str],
    alerts: list[str],
    profit: dict | None = None,
    ssp: dict | None = None,
) -> list[str]:
    """Apply real fixes for what audit found. Always returns FIX_* strings."""
    fixes: list[str] = []
    blob = " ".join(critical + alerts)
    profit = profit or {}
    ssp = ssp or {}

    if "DASH_DOWN" in blob:
        fixes.extend(_ensure_dash_process())

    # Dilution / house-only ALWAYS beat "behind" — holding volume while house-spamming
    # burns impr and keeps eCPM junk. Behind alone (paying fill present) → hold.
    behind = "MONEY_BEHIND" in blob
    dilution = any(
        x in blob
        for x in (
            "SEQS_TOO_HIGH",
            "SITE_LOCK_HIGH_VISITS",
            "PANEL_IPV_DILUTION",
            "STICKY_IPV_DILUTION",
            "IMPR_DILUTION",
            "SSP_HOUSE_ONLY",
        )
    )
    try:
        _paying_n = int(ssp["paying"]) if "paying" in ssp and ssp["paying"] is not None else -1
    except (TypeError, ValueError):
        _paying_n = -1
    house_only = "SSP_HOUSE_ONLY" in blob or _paying_n == 0
    clicks_n, payout_n = utc_clicks_and_payout(profit)
    catching_up = behind_on_path3_clicks(clicks_n, payout_n) or float(payout_n or 0) < 5.0
    if (dilution or house_only) and catching_up:
        for f in apply_money_rails(
            mode="hold",
            reason="zero_click_not_dilution",
            clicks=clicks_n,
            payout_usd=payout_n,
            profit=profit,
        ):
            fixes.append(f"FIX_{f}")
    elif dilution or house_only:
        for f in apply_money_rails(
            mode="heat_down",
            reason="dilution_or_house",
            clicks=clicks_n,
            payout_usd=payout_n,
            profit=profit,
        ):
            fixes.append(f"FIX_{f}")
    elif behind:
        for f in apply_money_rails(
            mode="hold",
            reason="behind_hold",
            clicks=clicks_n,
            payout_usd=payout_n,
            profit=profit,
        ):
            fixes.append(f"FIX_{f}")

    if house_only:
        fixes.extend(_prefer_paying_burst())

    if "INJECT_SHORT" in blob or "inject_listen_low" in blob:
        try:
            from automation.farm_money_monitor import repin_all_inject, soft_restart_inject_if_needed

            fixes.extend(soft_restart_inject_if_needed()[:8])
            fixes.extend(repin_all_inject()[:12])
        except Exception as exc:
            fixes.append(f"FIX_inject_restart_err:{exc}")

    if "DASH_PHONE_TABLE_SHORT" in blob or "DASH_PANEL_PHONES_SHORT" in blob:
        fixes.extend(_sync_panel_phones_from_sticky())

    # Cursor agent shell cleanup — prefer PharmFlow live script; re-run if flag or no report.
    shell_flag = LOG / "FARM_FIX_SHELL.flag"
    shell_report = LOG / "_shell_fix_report.json"
    shell_script = Path(r"C:\PharmFlow\logs\fix_cursor_shell.py")
    if not shell_script.is_file():
        shell_script = ROOT / "_tmp_fix_cursor_shell.py"
    need_shell = shell_flag.is_file() or (not shell_report.is_file())
    if need_shell and shell_script.is_file():
        try:
            subprocess.run(
                [sys.executable, str(shell_script)],
                cwd=str(ROOT),
                timeout=60,
                capture_output=True,
            )
            shell_flag.unlink(missing_ok=True)
            (LOG / "_shell_fix_done.txt").write_text(_utc() + "\n", encoding="utf-8")
            fixes.append("FIX_cursor_shell_env_cleanup")
        except Exception as exc:
            fixes.append(f"FIX_cursor_shell_err:{exc}")

    # Persist last fix set for dash / keepalive.
    try:
        _write_json(
            LOG / "FARM_MONITOR_LAST_FIX.json",
            {
                "ts": _utc(),
                "critical": critical,
                "alerts": alerts,
                "fixes": fixes,
                "payout": profit.get("payout_usd"),
                "ssp": ssp,
            },
        )
    except OSError:
        pass
    return fixes


def audit(*, profit: dict | None = None, ssp: dict | None = None, state: dict | None = None) -> list[str]:
    """Detect issues, APPLY fixes, return alert+fix strings for honest log."""
    alerts: list[str] = []
    critical: list[str] = []
    profit = profit or {}
    ssp = ssp or {}
    state = state or {}

    honest = LOG / "FARM_HONEST_NOW.txt"
    honest_age = 9999.0
    try:
        honest_age = time.time() - honest.stat().st_mtime
    except OSError:
        critical.append("HONEST_MISSING remediator not writing")
    if honest_age > 180:
        critical.append(f"REMEDIATOR_STALE honest_age={honest_age:.0f}s")

    dash: dict = {}
    try:
        with urllib.request.urlopen("http://127.0.0.1:8091/api/status", timeout=6) as r:
            dash = json.loads(r.read().decode())
    except Exception as exc:
        critical.append(f"DASH_DOWN {exc}")

    if dash:
        rows = dash.get("phone_rows") or []
        panel_phones = (dash.get("panel") or {}).get("phones") or []
        checkin = dash.get("checkin") or {}
        text = str(checkin.get("text") or "")
        if "full check-in loading" in text.lower() or "check-in deferred" in text.lower():
            if checkin.get("adb_online") is None:
                alerts.append("DASH_CHECKIN_DEGRADED no ADB count in check-in")
        if len(rows) < 6 and len(panel_phones) >= 6:
            critical.append(
                f"DASH_PHONE_TABLE_SHORT rows={len(rows)} panel={len(panel_phones)} "
                "(UI may look like 2 phones)"
            )
        if len(panel_phones) < 6:
            alerts.append(f"DASH_PANEL_PHONES_SHORT n={len(panel_phones)}")

        env = ((dash.get("panel") or {}).get("env") or {})
        try:
            ipv = float(env.get("PHARMFLOW_FARM_IMPRESSIONS_PER_VISIT") or 0)
        except (TypeError, ValueError):
            ipv = 0.0
        if ipv > 40:
            critical.append(f"PANEL_IPV_DILUTION ipv={ipv:.1f} (dash plan lying)")

    ov = _load_json(LOG / "farm_runtime_overrides.json")
    try:
        sticky_ipv = float(ov.get("PHARMFLOW_IPV_STICKY") or ov.get("PHARMFLOW_FARM_IMPRESSIONS_PER_VISIT") or 0)
    except (TypeError, ValueError):
        sticky_ipv = 0.0
    if sticky_ipv > 40:
        critical.append(f"STICKY_IPV_DILUTION ipv={sticky_ipv:.1f}")
    try:
        seqs = int(float(ov.get("PHARMFLOW_FARM_SEQS_PER_HOUR") or 0))
    except (TypeError, ValueError):
        seqs = 0
    if seqs > 36:
        critical.append(f"SEQS_TOO_HIGH seqs={seqs} (house-spam pace)")

    site = _load_json(LOG / "farm_site_lock.json")
    visits = str(site.get("daily_visits_csv") or "")
    if "500" in visits or "490" in visits:
        critical.append(f"SITE_LOCK_HIGH_VISITS {visits[:40]}")

    payout = float(profit.get("payout_usd") or 0)
    ecpm = float(profit.get("ecpm") or 0)
    impr = int(profit.get("impressions") or 0)
    paying = ssp.get("paying")
    house = ssp.get("house")
    try:
        paying_i = int(paying) if paying is not None else -1
    except (TypeError, ValueError):
        paying_i = -1
    try:
        house_i = int(house) if house is not None else -1
    except (TypeError, ValueError):
        house_i = -1

    if paying_i == 0 and house_i > 0:
        critical.append(f"SSP_HOUSE_ONLY paying=0 house={house_i}")
    if impr > 20000 and ecpm < 0.5:
        critical.append(f"IMPR_DILUTION impr={impr} ecpm=${ecpm:.2f}")
    if payout < 15 and honest_age < 300:
        tone = str(profit.get("tone") or "")
        if tone == "behind":
            alerts.append(f"MONEY_BEHIND ${payout:.2f} tone={tone}")

    # Paying inventory returned — clear heat-down and restore hold rails.
    if paying_i > 0 and _heat_flag().is_file():
        alerts.append(f"HEAT_CLEAR paying={paying_i} restore hold rails")
        apply_money_rails(mode="hold", reason="clear")

    adb_online = int(state.get("adb_online") or 0)
    adb_expect = int(state.get("adb_expect") or 0)
    try:
        from automation.farm_canonical_phones import canonical_expect_phones

        canon = canonical_expect_phones()
        if adb_expect <= 0 or adb_expect > canon:
            adb_expect = canon
    except Exception:
        pass
    if adb_expect > 0 and adb_online < adb_expect:
        critical.append(f"ADB_SHORT {adb_online}/{adb_expect}")
    inject_pinned = int(state.get("inject_pinned") or 0)
    pin_need = max(1, min(adb_online, adb_expect) - 1) if adb_online > 0 else 0
    if pin_need > 0 and inject_pinned < pin_need:
        critical.append(f"INJECT_SHORT pin={inject_pinned}/{adb_online or adb_expect}")
    actives = int(state.get("actives") or 0)
    if actives == 0 and adb_online >= 4:
        critical.append("FARM_IDLE actives=0 with phones online")

    ads = _load_json(LOG / "ads_watch_state.json")
    try:
        ads_age = time.time() - (LOG / "ads_watch_state.json").stat().st_mtime
    except OSError:
        ads_age = 9999.0
    cok = ads.get("bottom_ads_chromium_ok")
    ctot = ads.get("bottom_ads_chromium_total")
    if ads_age > 600:
        alerts.append(f"ADS_WATCH_STALE age={ads_age:.0f}s")
    if cok is not None and ctot is not None and adb_expect >= 6 and int(cok) <= 2:
        alerts.append(
            f"ADS_WATCH_LOOKS_LIKE_2_PHONES paint={cok}/{ctot} "
            f"(ADB is {adb_online}/{adb_expect} — do not confuse)"
        )

    # TURN THE HEAT DOWN / FIX — not just alert.
    applied = remediate(critical=critical, alerts=alerts, profit=profit, ssp=ssp)

    payload = {
        "ts": _utc(),
        "critical": critical,
        "alerts": alerts,
        "fixes": applied,
        "payout": payout,
        "ecpm": ecpm,
        "impr": impr,
        "ssp": {"paying": paying_i, "house": house_i},
        "adb": f"{adb_online}/{adb_expect}",
        "actives": actives,
    }
    try:
        LOG.mkdir(parents=True, exist_ok=True)
        with ALERTS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
        lines = [
            f"FARM_MONITOR_NOW {_utc()}",
            f"critical={len(critical)} alerts={len(alerts)} fixes={len(applied)}",
            f"ADB {adb_online}/{adb_expect} actives={actives} pin={inject_pinned}/{adb_online or adb_expect}",
            f"${payout:.2f} eCPM=${ecpm:.2f} impr={impr} SSP paying={paying_i} house={house_i}",
            "CRITICAL:" if critical else "CRITICAL: (none)",
        ]
        for a in critical:
            lines.append(f"  ! {a}")
        lines.append("ALERTS:" if alerts else "ALERTS: (none)")
        for a in alerts:
            lines.append(f"  - {a}")
        lines.append("FIXED:" if applied else "FIXED: (none)")
        for f in applied:
            lines.append(f"  + {f}")
        NOW.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass

    if critical:
        msg = (
            f"MONITOR FIX {len(applied)} | crit {len(critical)} | "
            f"ADB {adb_online}/{adb_expect} | ${payout:.2f} | "
            f"SSP {paying_i}/{house_i} | "
            + "; ".join(critical[:3])
        )
        applied.append(_ntfy(msg))

    out: list[str] = []
    for a in critical:
        out.append(f"CRIT {a}")
    for a in alerts:
        out.append(f"ALERT {a}")
    for f in applied:
        out.append(f if str(f).startswith("FIX") or str(f).startswith("ntfy") else f"FIX {f}")
    return out
