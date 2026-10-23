"""Map Mantis gauge scores → safe farm override deltas."""

from __future__ import annotations

from typing import Any

from automation.mantis_farm_math import AD_CLICKS_HARD_CAP

# Soft warn before hard browse-only.
AD_CLICKS_SOFT_STOP = 9999


def _as_float(raw: object, default: float) -> float:
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _as_int(raw: object, default: int) -> int:
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return default


def _path3_click_budget(cur: dict[str, str]) -> int:
    """Stop Path3 at the live per-phone ads sum — not the old 4-phone cap of 40."""
    total = 0
    for part in str(cur.get("PHARMFLOW_FARM_DAILY_ADS") or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            total += max(0, int(float(part)))
        except ValueError:
            continue
    cap = _as_int(cur.get("PHARMFLOW_FARM_PATH3_DAILY_CAP"), 0)
    return max(AD_CLICKS_HARD_CAP, cap, total)


def plan_steering(
    score: dict[str, Any],
    *,
    farm_ads_used: int = 0,
    path3_count: int = 0,
    current_overrides: dict[str, str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Build override patch + actions from a score_levers() result.

    Hard rails: never touch uniqueness env keys. Path3 daily stop follows ads sum.
    """
    cur = {str(k): str(v) for k, v in (current_overrides or {}).items()}
    levers = score.get("levers") if isinstance(score.get("levers"), dict) else {}
    clicks_lever = levers.get("clicks") if isinstance(levers.get("clicks"), dict) else {}
    evcpm_lever = levers.get("evcpm") if isinstance(levers.get("evcpm"), dict) else {}
    ecpm_lever = levers.get("ecpm") if isinstance(levers.get("ecpm"), dict) else {}
    impr_lever = levers.get("impressions") if isinstance(levers.get("impressions"), dict) else {}

    clicks = float(clicks_lever.get("value") or 0.0)
    evcpm = float(evcpm_lever.get("value") or 0.0)
    ecpm = float(ecpm_lever.get("value") or 0.0)
    impr = float(impr_lever.get("value") or 0.0)
    tone = str(score.get("tone") or "red")

    used = max(0, int(farm_ads_used), int(path3_count))
    actions: list[dict[str, Any]] = []
    patch: dict[str, str] = {}
    restart_farm = False
    reasons: list[str] = []

    click_budget = _path3_click_budget(cur)
    soft_stop = max(AD_CLICKS_SOFT_STOP, int(click_budget * 0.9))

    # --- Clicks: hard / soft stop ---
    if clicks >= click_budget:
        patch["PHARMFLOW_FARM_ALLOW_ADS"] = "0"
        patch["PHARMFLOW_FARM_PATHS"] = "1,2"
        patch["PHARMFLOW_FARM_DAILY_ADS"] = "0,0,0,0"
        patch["PHARMFLOW_FARM_PATH3_DAILY_CAP"] = "0"
        patch["PHARMFLOW_FARM_PATH3_PER_HOUR"] = "0"
        patch["PHARMFLOW_FARM_EVENING_SEQS_PER_HOUR"] = "0"
        actions.append(
            {
                "type": "browse_only",
                "detail": f"clicks={clicks:.0f} ≥ hard {click_budget} — Path3 off",
            }
        )
        reasons.append("clicks_hard_cap")
        restart_farm = cur.get("PHARMFLOW_FARM_ALLOW_ADS", "1") not in ("0", "false", "no")
    elif clicks >= soft_stop:
        # Leave a tiny remainder only if farm still under Mantis; else freeze.
        remain = max(0, click_budget - int(clicks) - 1)
        new_cap = min(click_budget, used + remain)
        patch["PHARMFLOW_FARM_PATH3_DAILY_CAP"] = str(new_cap)
        patch["PHARMFLOW_FARM_PATH3_PER_HOUR"] = "0" if remain <= 0 else "1"
        if remain <= 0:
            patch["PHARMFLOW_FARM_ALLOW_ADS"] = "0"
            patch["PHARMFLOW_FARM_PATHS"] = "1,2"
            patch["PHARMFLOW_FARM_DAILY_ADS"] = "0,0,0,0"
            actions.append({"type": "browse_only", "detail": f"clicks={clicks:.0f} soft-stop freeze"})
        else:
            actions.append(
                {
                    "type": "tighten_path3",
                    "detail": f"clicks={clicks:.0f} ≥ soft {AD_CLICKS_SOFT_STOP}; cap→{new_cap}",
                }
            )
        reasons.append("clicks_soft_stop")
        restart_farm = True

    # --- Rate dilution / low evCPM or eCPM ---
    load_wait = _as_float(cur.get("PHARMFLOW_DABFLOW_LOAD_WAIT"), 2.0)
    if (evcpm_lever.get("kind") == "out" or evcpm < 1.0) and clicks < click_budget:
        if load_wait < 3.5:
            patch["PHARMFLOW_DABFLOW_LOAD_WAIT"] = "5.0"
            actions.append({"type": "raise_dwell", "detail": f"evcpm={evcpm:.2f} → load_wait 5.0"})
            reasons.append("low_evcpm_dwell")
        patch["PHARMFLOW_HUMAN_VARIATION"] = "1"
        patch["PHARMFLOW_EVCPM_PUSH"] = "1"
        # Kill evening flood that dilutes rates.
        if _as_int(cur.get("PHARMFLOW_FARM_EVENING_SEQS_PER_HOUR"), 0) > 0:
            patch["PHARMFLOW_FARM_EVENING_SEQS_PER_HOUR"] = "0"
            patch["PHARMFLOW_FARM_EVENING_UNTIL"] = ""
            actions.append({"type": "kill_evening_flood", "detail": "evening fill off (rate dilution)"})
            reasons.append("kill_evening_flood")
            restart_farm = True

    if ecpm > 0 and ecpm < 0.15 and impr >= 10000:
        patch["PHARMFLOW_FARM_EVENING_SEQS_PER_HOUR"] = "0"
        if clicks >= 20:
            # Already have clicks — stop burning more; bias browse.
            if cur.get("PHARMFLOW_FARM_ALLOW_ADS", "1") not in ("0", "false", "no"):
                patch["PHARMFLOW_FARM_ALLOW_ADS"] = "0"
                patch["PHARMFLOW_FARM_PATHS"] = "1,2"
                actions.append({"type": "browse_only", "detail": f"ecpm={ecpm:.2f} floor broken"})
                reasons.append("ecpm_floor")
                restart_farm = True
        seqs = _as_int(cur.get("PHARMFLOW_FARM_SEQS_PER_HOUR"), 15)
        if seqs > 8:
            patch["PHARMFLOW_FARM_SEQS_PER_HOUR"] = "8"
            actions.append({"type": "throttle_volume", "detail": f"seqs/hr {seqs}→8 (ecpm dilute)"})
            reasons.append("throttle_volume")
            restart_farm = True

    # Overshoot impressions past sweet while rates are bad → throttle hard.
    if impr > 18000 and (ecpm < 0.15 or evcpm < 1.0):
        patch["PHARMFLOW_FARM_SEQS_PER_HOUR"] = "4"
        patch["PHARMFLOW_FARM_EVENING_SEQS_PER_HOUR"] = "0"
        actions.append({"type": "throttle_volume", "detail": f"impr={impr:.0f} overshoot + weak rates"})
        reasons.append("impr_overshoot")
        restart_farm = True

    # When clicks already past hard cap: keep a honest visit plan near the
    # impression sweet band — no fake 900+ "planned" on the dash.
    if clicks >= click_budget and impr >= 14000:
        remain = max(0, int((18000.0 - impr) / 22.0))
        patch["PHARMFLOW_FARM_SEQS_PER_HOUR"] = "4" if remain <= 40 else "6"
        patch["PHARMFLOW_EVCPM_PUSH"] = "1"
        patch["PHARMFLOW_DABFLOW_LOAD_WAIT"] = str(
            max(5.0, _as_float(cur.get("PHARMFLOW_DABFLOW_LOAD_WAIT"), 3.5))
        )
        visits_csv = str(cur.get("PHARMFLOW_FARM_DAILY_VISITS") or "")
        parts = [p.strip() for p in visits_csv.split(",") if p.strip()]
        try:
            cur_sum = sum(int(float(p)) for p in parts) if parts else 0
        except ValueError:
            cur_sum = 0
        if cur_sum > 820 or cur_sum <= 0:
            patch["PHARMFLOW_FARM_DAILY_VISITS"] = "210,205,200,190"
            actions.append(
                {
                    "type": "fix_visit_plan",
                    "detail": f"clicks={clicks:.0f} impr={impr:.0f}: visits plan→805 (was {cur_sum})",
                }
            )
            reasons.append("fix_visit_plan")
            restart_farm = True
        if remain <= 40:
            actions.append({"type": "throttle_volume", "detail": f"impr near 18k remain~{remain}"})
            reasons.append("near_impr_ceiling")

    # Never raise a steering Path3 cap above the live ads-sum budget.
    if "PHARMFLOW_FARM_PATH3_DAILY_CAP" in patch:
        cap = _as_int(patch["PHARMFLOW_FARM_PATH3_DAILY_CAP"], 0)
        if cap > click_budget:
            patch["PHARMFLOW_FARM_PATH3_DAILY_CAP"] = str(click_budget)

    if not actions and tone == "green":
        reasons.append("in_pocket_hold")

    if not actions and tone in ("yellow", "red"):
        # Still off-target but no specific lever rule — keep ads discipline, no flood.
        if _as_int(cur.get("PHARMFLOW_FARM_EVENING_SEQS_PER_HOUR"), 0) > 0:
            patch["PHARMFLOW_FARM_EVENING_SEQS_PER_HOUR"] = "0"
            actions.append({"type": "kill_evening_flood", "detail": "off-target: evening off"})
            reasons.append("off_target_no_flood")
            restart_farm = True

    reason = "+".join(reasons) if reasons else "no_change"
    return {
        "actions": actions,
        "overrides_patch": patch,
        "restart_farm": bool(restart_farm and patch),
        "reason": reason,
        "tone": tone,
        "dry_run": bool(dry_run),
        "clicks": clicks,
        "evcpm": evcpm,
        "ecpm": ecpm,
        "impressions": impr,
    }
