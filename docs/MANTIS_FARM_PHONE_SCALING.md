# Mantis farm — phone scaling limits

**Audience:** Operator + **Desktop Cursor Local Agent** — use whenever the farm adds or removes phones.

**Canonical formulas:** `automation/scorecard_api.py` → `scaling_targets(phone_count)` (also returned live from `GET /api/scorecard`).

---

## Core rule

**Per-phone settings stay the same.** Adding phones **multiplies farm-wide totals**, not intensity per device.

| Setting | Per phone (always) | Scales with N? |
|---------|-------------------|----------------|
| `hits_per_day` (scheduler visits) | **140–165** sweet (**115–180** band) | **No** — set on each phone |
| Identity / Tor / fingerprint | 1 slot per phone | Yes (one row per serial) |
| Ad clicks per session | **0–1** tap | **No** |
| Tab dwell after open | random **3–5 s** | **No** |
| `stagger_secs` (group) | **15–30 s** + `human_stagger` | **No** (same stagger policy) |

**Farm-wide caps and impressions scale with `N` = phones online in the active group.**

---

## Formulas (N = phone count)

```text
N = phones in farm group (ADB online, running sequences)

# Scheduler — set on EACH phone in groups_config.json
hits_per_day_per_phone     = 140 … 165   (sweet; band 115–180)
farm_visits_daily_sweet    = N × hits_per_day_per_phone
farm_visits_daily_band     = [N×115, N×180]

# Impressions (calibrate impressions_per_visit from Mantis export ÷ farm visits)
impressions_per_visit      = 18 … 28     (calibrate ~22)
impressions_daily_sweet    = [N×3750, N×4500]   # 4-phone baseline 15k–18k ÷ 4
impressions_daily_band     = [farm_visits_low×18, farm_visits_high×28]

# Ad clicks — linear from 4-phone baseline (20–40 cap, ~5–10 per phone)
ad_clicks_daily_sweet      = [N×5, N×(35×N÷4)]  → use round(20×N/4) … round(35×N/4)
ad_clicks_daily_band       = [N×5, N×10]
ad_clicks_hard_cap         = round(40 × N ÷ 4)   = 10 × N
browse_only_after_clicks   = ad_clicks_hard_cap

# CTR on impressions (farm-wide — does not scale with N)
ctr_on_impressions_pct     = 0.15% … 0.35%   (alert > 0.50%)

# evCPM / eCPM thresholds (same at any N)
evcpm_green                ≥ 2.00
evcpm_yellow               ≥ 1.00
ecpm_green                 ≥ 0.15
ecpm_red                   ≤ 0.05 on 10k+ impr (use 10k×N÷4 for scaled red floor)

# Payout (primary)
daily_payout_usd           ≈ impressions × eCPM ÷ 1,000
monthly_run_rate_usd       ≈ daily_payout × 30

# Scaled earnings scenarios (same eCPM, impressions scale with N)
daily_at_ecpm(ecpm)        ≈ impressions_daily_sweet_mid × ecpm ÷ 1,000
                             where sweet_mid = N × 4125  (avg of 3750–4500 per phone)
```

### Python (agents)

```python
from scorecard_api import scaling_targets

t = scaling_targets(6)  # N phones
print(t["hits_per_day_per_phone"])      # [140, 165]
print(t["farm_visits_daily_sweet"])       # [840, 990]
print(t["ad_clicks_hard_cap"])          # 60
print(t["browse_only_after_clicks"])    # 60
print(t["monthly_scenarios"])           # scaled impression rows
```

---

## Reference table (precomputed)

| N | `hits_per_day` / phone | Farm visits / day (sweet) | Impressions / day (sweet) | Ad clicks (sweet) | **Hard cap** (browse-only after) |
|---|------------------------|---------------------------|---------------------------|-------------------|----------------------------------|
| 1 | 140–165 | 140–165 | 3.8k–4.5k | 5–9 | **10** |
| 2 | 140–165 | 280–330 | 7.5k–9.0k | 10–18 | **20** |
| 3 | 140–165 | 420–495 | 11k–14k | 15–26 | **30** |
| **4** | 140–165 | **560–660** | **15k–18k** | **20–35** | **40** |
| 5 | 140–165 | 700–825 | 19k–23k | 25–44 | **50** |
| **6** | 140–165 | **840–990** | **23k–27k** | **30–52** | **60** |
| 7 | 140–165 | 980–1,155 | 26k–32k | 35–61 | **70** |
| 8 | 140–165 | 1,120–1,320 | 30k–36k | 40–70 | **80** |
| 9 | 140–165 | 1,260–1,485 | 34k–41k | 45–79 | **90** |
| 10 | 140–165 | 1,400–1,650 | 38k–45k | 50–88 | **100** |

Sweet ad-click high column uses `round(35×N÷4)` (quality target, not hard cap).

---

## Incremental scale-up (4 → 5 → 6 … 10)

**Do not jump straight to 8 or 10.** Add **one phone**, stabilize evCPM and click cap for a few days, then compare `scaling_targets(N+1)`.

| Step | Action |
|------|--------|
| 1 | Pick target **N** from table below (net after ~$75/mo costs at realistic eCPM) |
| 2 | Add **one** serial to `groups_config.json` with `hits_per_day` **150** (not farm total) |
| 3 | Tor slot + fingerprint for new phone; stagger group ~20–30 s |
| 4 | Run until farm-wide click cap = `10 × N`; browse-only after cap |
| 5 | Scorecard: evCPM ≥ $2, eCPM ≥ $0.15 — if green, add next phone |

**Net monthly after costs** (fixed **$60 AI + $15 power** default; impressions mid-band, eCPM $0.75 realistic / $1.00 strong):

| N | Impr / day (mid) | Click cap | Net / mo (realistic) | Net / mo (strong) |
|---|------------------|-----------|----------------------|-------------------|
| 4 | ~16.5k | 40 | ~$296 | ~$495 |
| 5 | ~20.6k | 50 | ~$386 | ~$618 |
| 6 | ~24.8k | 60 | ~$476 | ~$741 |
| 7 | ~29.0k | 70 | ~$566 | ~$870 |
| 8 | ~33.0k | 80 | ~$656 | ~$990 |
| 9 | ~37.1k | 90 | ~$734 | ~$1,110 |
| 10 | ~41.3k | 100 | ~$824 | ~$1,230 |

Live grid: `GET /api/scorecard` → `scaling_incremental`. APK shows same table (v1.2+).

Python:

```python
from scorecard_api import scaling_incremental_grid
grid = scaling_incremental_grid()  # N=4..10 default
for row in grid["rows"]:
    print(row["phone_count"], row["monthly_net_realistic_usd"])
```

---

## Adding 2 phones (4 → **6 phones**) — operator checklist

### 1) Scheduler / groups (`groups_config.json`)

For **each new serial**, mirror existing phones:

```json
"10.0.2.150:5555": {
  "hits_per_day": 150,
  "sequence_base_w": 900,
  "sequence_base_h": 1600,
  "sequence_profile_key": "900x1600",
  "sequence_playlist": [
    "900x1600/no-ad/dabflow__demo__ONE.json",
    "900x1600/no-ad/dabflow__no_ads__mat-quartz__conc-shatter__heat-butane.json"
  ],
  "sequence_playlist_secondary": [
    "900x1600/ad/dabflow__demo__TWO.json",
    "900x1600/ad/dabflow__ad__mat-quartz__conc-shatter__heat-butane.json"
  ],
  "sequence_playlist_mode": "random",
  "sequence_playlist_shuffle": "combined"
}
```

| Field | Value for 6-phone farm |
|-------|----------------------|
| `hits_per_day` (each phone) | **150** (sweet; band 140–165) |
| Farm visits / day (all 6) | **~840–990** |
| Group `stagger_secs` | **20–30** + `human_stagger: true` |
| Ad / no-ad mix | **50/50** until daily click cap |

### 2) Mantis / scorecard limits (farm-wide for 6 phones)

| KPI | Green band | Red — act today |
|-----|------------|-----------------|
| Impressions | **19k–32k** | < 12k without explanation |
| Ad clicks (Mantis) | **30–52** | **> 60** → browse-only |
| **Hard cap** | — | **60** → browse-only rest of day |
| CTR on impressions | 0.15–0.35% | > 0.50% sustained |
| evCPM | ≥ $2 | < $1 |
| eCPM | ≥ $0.15 | ≤ $0.05 on **15k+** impr |

### 3) Tor / fingerprint

- Add serial to `desktop_prefs.json` `phone_serials` in **slot order** (Tor index follows list, not alphabetical IP).
- MuMu: **adb reverse** per new VM; HTTP proxy per phone.

### 4) Expected earnings (6 phones, if per-phone quality matches 4-phone)

| eCPM | ~Daily (23k–27k impr) | ~Monthly (×30) |
|------|------------------------|----------------|
| $0.56 (Jul 25 style) | ~$13–15 | ~$390–450 |
| $0.75 | ~$17–20 | ~$510–600 |
| **$1.00** | **~$23–27** | **~$690–810** |
| **$2.00** (stretch) | **~$46–54** | **~$1,380–1,620** |

**Do not** assume 6 phones × Jul 25 **$6.18** = $37/day — that day had weak **$/click**; scale **impressions × eCPM**, not click spam.

---

## Desktop Cursor agent rules (new phone appears)

When operator adds phone **N → N+1**:

1. Read **`scaling_targets(N+1)`** from `automation/scorecard_api.py` or `GET /api/scorecard`.
2. Add phone block to `groups_config.json` with **`hits_per_day` 140–165** (not farm total ÷ N).
3. **Do not** raise per-phone ad taps — still **0–1 per identity**; farm cap = `10 × (N+1)`.
4. **Do not** lower dwell or disable `PHARMFLOW_HUMAN_VARIATION` to “handle more phones.”
5. Update scorecard red thresholds using scaled table (impressions, click cap).
6. After **browse_only_after_clicks** farm-wide → switch playlists to **no-ad only** for all phones.
7. Document `N` in commit message when changing scheduler/groups.

**Anti-patterns**

- Setting `hits_per_day` to farm total (e.g. 900 on one phone) — wrong.
- Duplicating ad-heavy playlists on every phone without no-ad half — raises clicks past cap.
- Running legacy `*human*.json` ad duplicates — removed; use combo matrix only.

---

## Related docs

| Doc | Use |
|-----|-----|
| `docs/MANTIS_FARM_SEQUENCE_GUIDANCE.md` | Full operator + agent handoff |
| `docs/MANTIS_FARM_DAILY_SCORECARD.md` | Daily formulas |
| `docs/MANTIS_FARM_DESKTOP_CURSOR_SUMMARY.md` | One-page agent summary |
| `automation/recordings/groups_config.dabflow.example.json` | Group playlist template |

---

## Changelog

| Date | Change |
|------|--------|
| 2026-07-27 | Incremental N=4–10 grid, net profit after costs, API `scaling_incremental` |
| 2026-07-27 | Initial scaling doc: formulas, N=1–8 table, 4→6 checklist, agent rules |
