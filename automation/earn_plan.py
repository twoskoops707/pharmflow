"""Sequence mix from the operator's earnings parameters.

Path names match the farm runner, not a site:

- Path 1 is a complete browse sequence (stem ends with ``_complete``).
- Path 2 is a halfway browse (stem ends with ``_halfway``).
- Path 3 is one paid action (stem ends with ``_ad`` or ``_ad_multi``).

Money follows the scorecard equation already in this repo:

    impressions = visits x impressions_per_visit
    payout = impressions x ecpm / 1000

That equation is not Mantis-specific. eCPM is whatever the site pays per
thousand impressions. A missing input is an error. This module does not
invent a phone count, a click ceiling, or a payout.

Stealth: phones do not get identical daily counts. The fleet total still
matches the operator target. Each phone draws a different share so the
farm does not look cloned.
"""

from __future__ import annotations

import json
import math
import os
import random
import secrets
from pathlib import Path
from typing import Any

IMPRESSIONS_PER_VISIT_DEFAULT = 22.0
HALFWAY_RATIO_DEFAULT = 0.20
# Documented quality band from docs/MANTIS_FARM_SEQUENCE_GUIDANCE.md.
# Shown to the operator. Not applied unless they enter a number.
VISITS_PER_PAID_ACTION_BAND = (30, 45)
# Soft band around the mean when splitting the fleet across phones.
# Matches the uneven day-plan style already used in mantis_farm_math
# (173, 148, 141, 119). Not a phone-count or click ceiling.
SPREAD_LO = 0.80
SPREAD_HI = 1.20

PLAN_NAME = "earn_plan.json"


def plan_path() -> Path:
    root = (
        os.environ.get("PHARMFLOW_LOGS")
        or os.environ.get("PHARMFLOW_LOG_DIR")
        or r"C:\PharmFlow\logs"
    )
    return Path(root) / PLAN_NAME


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_at_least_zero(value: float) -> int:
    return max(0, int(value))


def _int_list(raw: Any) -> list[int]:
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for item in raw:
        try:
            out.append(max(0, int(item)))
        except (TypeError, ValueError):
            continue
    return out


def random_phone_counts(total: int, n: int, rng: random.Random) -> list[int]:
    """Split ``total`` across ``n`` phones. Sum is exact. Values differ when possible."""
    if n < 1:
        return []
    total = max(0, int(total))
    if n == 1:
        return [total]
    if total <= 0:
        return [0] * n
    weights = [rng.uniform(SPREAD_LO, SPREAD_HI) for _ in range(n)]
    weight_sum = sum(weights) or float(n)
    raw = [total * (w / weight_sum) for w in weights]
    out = [int(math.floor(x)) for x in raw]
    left = total - sum(out)
    order = list(range(n))
    rng.shuffle(order)
    for i in order:
        if left <= 0:
            break
        out[i] += 1
        left -= 1
    # Identical counts look like a farm. Force one transfer when the split
    # landed flat and there is room to move a visit.
    if n > 1 and total >= n and len(set(out)) == 1:
        donors = [i for i, v in enumerate(out) if v > 0]
        if donors:
            i = rng.choice(donors)
            j = rng.choice([x for x in range(n) if x != i])
            out[i] -= 1
            out[j] += 1
    return out


def _path_mix_for_visits(
    visits: int,
    *,
    ads_allowed: bool,
    visits_per_paid: float | None,
    path2_share: float,
) -> tuple[int, int, int]:
    if ads_allowed and visits_per_paid is not None and visits_per_paid > 0:
        path3 = _int_at_least_zero(math.floor(visits / visits_per_paid))
        if path3 > visits:
            path3 = visits
    else:
        path3 = 0
    browse = visits - path3
    path2 = int(round(browse * path2_share))
    if path2 > browse:
        path2 = browse
    path1 = browse - path2
    return path1, path2, path3


def _value_at(values: list[int], phone_idx: int, seed: int) -> int:
    """Phone count from a saved list. Extra live phones draw around the mean."""
    if phone_idx < 0:
        return 0
    if not values:
        return 0
    if phone_idx < len(values):
        return int(values[phone_idx])
    mean = sum(values) / float(len(values))
    rng = random.Random((int(seed) << 16) ^ (phone_idx * 1009) ^ (len(values) * 9176))
    lo = max(0, int(math.floor(mean * SPREAD_LO)))
    hi = max(lo, int(math.ceil(mean * SPREAD_HI)))
    if hi <= lo:
        return int(round(mean))
    return int(rng.randint(lo, hi))


def compute_earn_plan(
    params: dict[str, Any] | None,
    *,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Return path counts for the fleet, or an error.

    ``visits_per_phone`` is the mean. The saved plan stores a random per-phone
    list whose sum is ``mean * phones``. Path 3 on each phone is the whole
    number of paid actions that fit that phone's visits. A fractional action
    is not added.
    """
    raw = params if isinstance(params, dict) else {}
    phones = _num(raw.get("phones"))
    if phones is None or phones < 1 or phones != int(phones):
        return {
            "ok": False,
            "error": "Enter how many phones this plan is for. There is no default fleet size.",
        }
    phone_count = int(phones)

    hours = _num(raw.get("awake_hours"))
    if hours is None or hours <= 0:
        hours = 24.0
    ipv = _num(raw.get("impressions_per_visit"))
    if ipv is None or ipv <= 0:
        ipv = IMPRESSIONS_PER_VISIT_DEFAULT
        ipv_source = "default_22"
    else:
        ipv_source = "operator"

    ratio = _num(raw.get("path2_share"))
    if ratio is None:
        ratio = HALFWAY_RATIO_DEFAULT
        path2_source = "default_0.20"
    elif ratio < 0 or ratio > 1:
        return {
            "ok": False,
            "error": "Path 2 share must be from 0 to 1. That is the halfway-browse portion of non-ad visits.",
        }
    else:
        path2_source = "operator"

    ads_allowed = raw.get("ads_allowed") is True or str(raw.get("ads_allowed") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    visits_per_paid = _num(raw.get("visits_per_paid_action"))
    if ads_allowed and (visits_per_paid is None or visits_per_paid <= 0):
        lo, hi = VISITS_PER_PAID_ACTION_BAND
        return {
            "ok": False,
            "error": (
                f"Enter visits per paid action. The documented quality band is {lo}-{hi}. "
                "This plan does not pick one for you."
            ),
        }

    typed_visits = _num(raw.get("visits_per_phone"))
    target_usd = _num(raw.get("target_usd"))
    ecpm = _num(raw.get("ecpm"))
    visit_source = ""
    if typed_visits is not None and typed_visits > 0:
        visits_mean = int(math.ceil(typed_visits))
        visit_source = "operator_visits"
    elif target_usd is not None and target_usd > 0 and ecpm is not None and ecpm > 0:
        fleet_impressions = (target_usd * 1000.0) / ecpm
        fleet_visits = fleet_impressions / ipv
        visits_mean = int(math.ceil(fleet_visits / phone_count))
        visit_source = "target_usd"
    else:
        return {
            "ok": False,
            "error": (
                "Enter visits per phone, or both a target daily payout and the site eCPM. "
                "Payout is impressions x eCPM / 1000. Missing either number is not a guess."
            ),
        }

    seed_raw = _num(raw.get("spread_seed"))
    if seed_raw is not None and seed_raw == int(seed_raw) and seed_raw >= 0:
        spread_seed = int(seed_raw)
    else:
        spread_seed = secrets.randbelow(2**31 - 1) + 1
    draw = rng if rng is not None else random.Random(spread_seed)

    fleet_visits = visits_mean * phone_count
    visits_by_phone = random_phone_counts(fleet_visits, phone_count, draw)
    path1_by_phone: list[int] = []
    path2_by_phone: list[int] = []
    path3_by_phone: list[int] = []
    for visits in visits_by_phone:
        p1, p2, p3 = _path_mix_for_visits(
            visits,
            ads_allowed=ads_allowed,
            visits_per_paid=visits_per_paid,
            path2_share=ratio,
        )
        path1_by_phone.append(p1)
        path2_by_phone.append(p2)
        path3_by_phone.append(p3)

    path1 = int(round(sum(path1_by_phone) / phone_count)) if phone_count else 0
    path2 = int(round(sum(path2_by_phone) / phone_count)) if phone_count else 0
    path3 = int(round(sum(path3_by_phone) / phone_count)) if phone_count else 0
    # Hourly Path 3 on a phone equals that phone's daily Path 3. The mean is
    # kept for display; the runner reads the per-phone list.
    path3_per_hour = path3 if path3 else 0

    implied_impressions = sum(visits_by_phone) * ipv
    implied_usd = (implied_impressions * ecpm / 1000.0) if ecpm and ecpm > 0 else None
    paths = "1,2,3" if any(path3_by_phone) else "1,2"
    visits_csv = ",".join(str(v) for v in visits_by_phone)
    ads_csv = ",".join(str(a) for a in path3_by_phone)
    note = (
        f"{phone_count} phones. Fleet total {sum(visits_by_phone)} visits/day "
        f"({visits_csv}). Path 3 per phone: {ads_csv}. "
        "Counts are randomized per phone so the farm does not look cloned. "
        f"Means are about {path1} Path 1, {path2} Path 2, and {path3} Path 3. "
        "One sequence is one identity. Path 3 is one paid action in that sequence, not an extra click. "
        "Path 2 exists so visits are not identical full tours. "
        f"Visits came from {visit_source}. Impressions per visit came from {ipv_source}. "
        f"Path 2 share came from {path2_source}. "
        "Hourly Path 3 allowance equals that phone's daily Path 3 count so a lower hourly number cannot cut the day short. "
        "The remaining-ad spread still spaces them. "
        "Save this plan to use it. The dashboard can change the same numbers after the farm is up."
    )
    if implied_usd is None:
        note += " Implied payout is blank because eCPM was not entered."
    return {
        "ok": True,
        "phones": phone_count,
        "awake_hours": hours,
        "impressions_per_visit": ipv,
        "path2_share": ratio,
        "ads_allowed": ads_allowed,
        "visits_per_paid_action": visits_per_paid if ads_allowed else None,
        "visits_per_phone": visits_mean,
        "visits_by_phone": visits_by_phone,
        "path1_by_phone": path1_by_phone,
        "path2_by_phone": path2_by_phone,
        "path3_by_phone": path3_by_phone,
        "visits_csv": visits_csv,
        "ads_csv": ads_csv,
        "spread_seed": spread_seed,
        "path1_per_phone": path1,
        "path2_per_phone": path2,
        "path3_per_phone": path3,
        "path3_per_hour": path3_per_hour,
        "paths": paths,
        "target_usd": target_usd,
        "ecpm": ecpm,
        "implied_impressions": implied_impressions,
        "implied_usd": implied_usd,
        "visit_source": visit_source,
        "note": note,
    }


def save_earn_plan(params: dict[str, Any] | None, dest: Path | None = None) -> dict[str, Any]:
    """Compute the plan and write it only when the compute step succeeded."""
    plan = compute_earn_plan(params)
    if not plan.get("ok"):
        return plan
    path = dest or plan_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    stored = dict(plan)
    stored["saved"] = True
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(stored, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    stored["path"] = str(path)
    return stored


def load_earn_plan(dest: Path | None = None) -> dict[str, Any] | None:
    """Return a saved plan, or None. A corrupt file is left in place."""
    path = dest or plan_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("saved") is not True or data.get("ok") is not True:
        return None
    return data


def _plan_visits_list(plan: dict[str, Any]) -> list[int]:
    vals = _int_list(plan.get("visits_by_phone"))
    if vals:
        return vals
    # Legacy scalar plans still get a stealth split, locked by spread_seed.
    try:
        n = max(1, int(plan.get("phones") or 1))
        mean = max(0, int(plan.get("visits_per_phone") or 0))
        seed = int(plan.get("spread_seed") or 1)
    except (TypeError, ValueError):
        return []
    return random_phone_counts(mean * n, n, random.Random(seed))


def _plan_ads_list(plan: dict[str, Any]) -> list[int]:
    vals = _int_list(plan.get("path3_by_phone"))
    if vals:
        return vals
    visits = _plan_visits_list(plan)
    if not visits:
        try:
            n = max(1, int(plan.get("phones") or 1))
            mean = max(0, int(plan.get("path3_per_phone") or 0))
            seed = int(plan.get("spread_seed") or 1)
        except (TypeError, ValueError):
            return []
        return random_phone_counts(mean * n, n, random.Random(seed ^ 0xA5A5))
    ads_allowed = bool(plan.get("ads_allowed"))
    visits_per_paid = _num(plan.get("visits_per_paid_action"))
    ratio = _num(plan.get("path2_share"))
    if ratio is None:
        ratio = HALFWAY_RATIO_DEFAULT
    out: list[int] = []
    for v in visits:
        _p1, _p2, p3 = _path_mix_for_visits(
            v,
            ads_allowed=ads_allowed,
            visits_per_paid=visits_per_paid,
            path2_share=ratio,
        )
        out.append(p3)
    return out


def applied_visits_per_phone(phone_idx: int = 0, dest: Path | None = None) -> int | None:
    plan = load_earn_plan(dest)
    if not plan:
        return None
    try:
        seed = int(plan.get("spread_seed") or 0)
    except (TypeError, ValueError):
        seed = 0
    return _value_at(_plan_visits_list(plan), phone_idx, seed)


def applied_ads_per_phone(phone_idx: int = 0, dest: Path | None = None) -> int | None:
    plan = load_earn_plan(dest)
    if not plan:
        return None
    try:
        seed = int(plan.get("spread_seed") or 0)
    except (TypeError, ValueError):
        seed = 0
    return _value_at(_plan_ads_list(plan), phone_idx, seed)


def applied_path3_per_hour(phone_idx: int = 0, dest: Path | None = None) -> int | None:
    """That phone's daily Path 3 count. Missing file returns None."""
    return applied_ads_per_phone(phone_idx, dest)


def applied_halfway_share(dest: Path | None = None) -> float | None:
    plan = load_earn_plan(dest)
    if not plan:
        return None
    try:
        share = float(plan.get("path2_share"))
    except (TypeError, ValueError):
        return None
    if share < 0 or share > 1:
        return None
    return share


def applied_ads_allowed(dest: Path | None = None) -> bool | None:
    plan = load_earn_plan(dest)
    if not plan:
        return None
    return bool(plan.get("ads_allowed"))


def applied_paths(dest: Path | None = None) -> set[str] | None:
    plan = load_earn_plan(dest)
    if not plan:
        return None
    raw = str(plan.get("paths") or "")
    found = {part.strip() for part in raw.split(",") if part.strip() in {"1", "2", "3"}}
    return found or None


def applied_path3_farm_cap(live_phones: int, dest: Path | None = None) -> int | None:
    """Farm-wide Path 3 count. More live phones raise the cap. None if no plan."""
    plan = load_earn_plan(dest)
    if not plan:
        return None
    ads = _plan_ads_list(plan)
    try:
        planned = max(1, int(plan.get("phones") or len(ads) or 1))
        live = max(0, int(live_phones or 0))
        seed = int(plan.get("spread_seed") or 0)
    except (TypeError, ValueError):
        return None
    n = max(planned, live, len(ads))
    return sum(_value_at(ads, i, seed) for i in range(n))
