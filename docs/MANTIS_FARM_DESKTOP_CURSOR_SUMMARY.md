# Mantis farm — Desktop Cursor Local Agent summary

**Paste into Desktop Cursor Local Agent** or say: *“Follow `docs/MANTIS_FARM_DESKTOP_CURSOR_SUMMARY.md` and `docs/MANTIS_FARM_SEQUENCE_GUIDANCE.md`.”*

This is the **one-page** distillation of profitability research (Jul 24–26 Mantis export + farm logs) and operating rules.

---

## Profit model (verified)

```
Payout ≈ Impressions × eCPM ÷ 1,000
```

| KPI | Meaning | Optimize? |
|-----|---------|-----------|
| **evCPM** | Viewable value in export | **#1** — dwell, tab load waits |
| **eCPM** | Credited rate (actual $) | Close gap to evCPM |
| **Impressions** | ~1 per Mantis **zone** served (~22 per farm visit) | Volume via visits + full tab tour |
| **Ad clicks** | Mantis click count | **Cap per `scaling_targets(N)`** — not maximize |

**Clicks do not scale profit.** Jul 25: **117 clicks → $6.18** (~$0.05/click). Jul 24: **7 clicks → $0.47/click** (best recent quality). **New phone?** → `docs/MANTIS_FARM_PHONE_SCALING.md`.

---

## Tab load waits (CRITICAL — load all ads before scroll)

DabFlow runs `mantis.push(['display','refresh'])` on **every tab switch**. Premium/slow ads load at the **top** after refresh.

**Rule:** Random wait in band **before first scroll** on each tab. **Never 0 seconds.**

| Moment | Random band (seconds) | Never |
|--------|----------------------|-------|
| After tab open / land | **3.0 – 5.0** | **0** |
| After tab switch | **3.0 – 5.0** | **0** |
| After scroll to bottom | **2.0 – 4.0** | **0** |
| After scroll up | **2.0 – 3.0** | — |
| Before leave tab | **1.0 – 2.0** | — |
| Micro-gap between UI taps | **0.12 – 0.55** | all identical |
| After ad region tap (dwell) | **30 – 45** | **< 25** |
| `tap.pre_wait_ms` (ad taps) | **200 – 500** ms | **0** |
| `tap.jitter` | **14 – 28** px | — |

**Per-tab template:**

```
open tab → wait random 3–5s → scroll → wait random 2–4s → scroll bottom → wait random 2–4s → leave
```

**Exception:** `checkpoint: timer_complete` — fixed long wait; never shorten.

**Runtime:** `CPHARM_HUMAN_VARIATION=1` always (`automation/human_variation.py` adds ±8% on waits at playback).

**JSON authoring:** `wizard/sequence_humanize.py` — each file variant gets different values inside bands; suffix `__humanNNN`.

---

## DabFlow zones (impressions per visit)

| Tab | Mantis zones |
|-----|--------------|
| home | 2 |
| timer | 3 |
| stats | 3 |
| glass | 4 |
| settings | 4 |

**~20–25 impressions per farm visit** with multi-tab tour + scroll. **Do not cut visits** because impressions hit ~16k — that ratio is normal.

---

## Daily targets (scale with phone count)

**Per phone:** `hits_per_day` **140–165** (band 115–180) on **each** device.

**Farm totals** scale with **N** phones — full table and formulas:

→ **`docs/MANTIS_FARM_PHONE_SCALING.md`**  
→ `scaling_targets(N)` in `automation/scorecard_api.py`  
→ Live: `GET /api/scorecard` → `targets` (uses phones online)

| N | Farm visits / day (sweet) | Impressions / day (sweet) | Ad click hard cap |
|---|---------------------------|---------------------------|-------------------|
| 4 | 560–660 | 15k–18k | **40** |
| **6** | **840–990** | **23k–27k** | **60** |
| 7 | 980–1,155 | 26k–32k | **70** |
| 8 | 1,120–1,320 | 30k–36k | **80** |
| 9 | 1,260–1,485 | 34k–41k | **90** |
| 10 | 1,400–1,650 | 38k–45k | **100** |

**After hard cap:** browse-only / no-ad sequences for **all** phones rest of day.

### Incremental scale-up (add one phone at a time)

Compare **N = 4, 5, 6, 7, 8, 9, 10** before adding the next device. Per-phone `hits_per_day` stays **140–165**; only farm totals and click cap grow.

→ `scaling_incremental_grid()` / `GET /api/scorecard` → `scaling_incremental`  
→ APK **CPharmScorecard** v1.2+ table (net/mo after **$60 AI + $15 power**)

| N | ~Net/mo realistic (eCPM $0.75) | ~Net/mo strong ($1.00) | Click cap |
|---|-------------------------------|------------------------|-----------|
| 4 | ~$296 | ~$495 | 40 |
| 5 | ~$386 | ~$618 | 50 |
| 6 | ~$476 | ~$741 | 60 |
| 7 | ~$566 | ~$870 | 70 |
| 8 | ~$656 | ~$990 | 80 |
| 9 | ~$734 | ~$1,110 | 90 |
| 10 | ~$824 | ~$1,230 | 100 |

**Workflow:** add one phone → green scorecard 2–3 days → repeat. Do not skip to 8/10 without stabilizing quality.

---

## Session / identity rules

- New identity each session (fingerprint, Tor slot, cookies).
- **0–1 ad click per identity** — never 2+ ad taps same session.
- **~70–85% sessions: 0 clicks**; **~15–30%: 1 click** on rotated zone.
- Stagger phones ~15–20 min; vary tab order.
- **50/50 ad / no-ad** playlists in `groups_config.json` until click cap.

---

## Max-profit operating point

1. **evCPM ≥ $2** via tab dwell (viewability gate).
2. **~16k–18k impressions/day** (full 5-tab tour).
3. **20–35 ad clicks** quality taps, not 80–117.
4. **CPHARM_HUMAN_VARIATION=1** + humanized JSON bands.
5. Browse-only after daily click cap.

### Monthly expectations (4 phones)

| Scenario | Daily $ | Monthly $ |
|----------|---------|-----------|
| Floor (Jul 26 evCPM broken) | ~$0.9 | ~$27 |
| Jul 25 actual | ~$6.2 | ~$186 |
| Realistic (16k impr, eCPM $0.75) | ~$12 | ~$360 |
| Strong (18k impr, eCPM $1.00) | ~$18 | ~$540 |
| Stretch (18k impr, eCPM $2.00) | ~$36 | ~$1,080 |

Jul 26: **17,723 impr** at evCPM **$0.34** → **$0.85**. Same volume at Jul 25 evCPM **$4.31** ceiling ≈ **$76/day** — **dwell fixes money**.

### Net profit after operating costs

Subtract fixed monthly costs from gross Mantis payout (defaults in API + APK):

| Cost | Default $/month | Notes |
|------|-----------------|-------|
| **AI tools (Cursor)** | **$60** | Operator subscription to run agents |
| **Power (PC + MuMu)** | **$15** | Small at farm scale |
| **Other** | $0 | Internet, VPN, etc. (optional) |

**Break-even:** ~**$2.50/day** gross Mantis (~$75/mo) at defaults.  
**Net monthly** = `(daily_gross × 30) − ai_tools − power − other` — see `profitability` in `GET /api/scorecard` and **CPharmScorecard** app (v1.1+).

Scale scenarios in the APK use **N phones** from the field or live fetch; edit costs on phone and **Save to farm**.

## Red flags — act immediately

| Signal | Action |
|--------|--------|
| eCPM $0 + 5k impr + clicks | Cut clicks; visibility report; no volume brute-force |
| evCPM drop ($4 → $0.34) | Enforce 3–5s dwell after tab open in JSON |
| Ad clicks > 40 | Browse-only only (**autopilot** on Pull / 2–3h when farm keepers run) |
| CTR on impr > ~0.5% | Remove ad tap steps; check iframe accidental hits |
| Evening flood with flat payout | Evening seqs/hr = **0** |
| Farm vs Mantis clicks large gap | Audit remap + Path1/2 non-interactive paint |
| Dash visits Planned ≠ farm | Prefer `farm_runtime_overrides.json` over stale panel |

---

## Autopilot (closed loop — FamFlow farm keepers)

| Piece | Notes |
|-------|------|
| Dash **Pull from Mantis** | Fetch → score → steer overrides |
| `scripts/mantis_autopilot.py` | Background 2–3h + yellow/red |
| Caps truth | `C:\CPharm\logs\farm_runtime_overrides.json` |
| Lock browsers | `CPHARM_FARM_BROWSERS=chromium` when click-leak |

Uniqueness rails stay on. Ship notes: CPharm.exe Release body mirrors these bands.

---

## Scorecard tools

| Tool | Path / URL |
|------|------------|
| Daily scorecard doc | `docs/MANTIS_FARM_DAILY_SCORECARD.md` |
| **Phone scaling (N phones)** | `docs/MANTIS_FARM_PHONE_SCALING.md` |
| CSV template | `docs/MANTIS_FARM_DAILY_SCORECARD.csv` |
| Full handoff | `docs/MANTIS_FARM_SEQUENCE_GUIDANCE.md` |
| **Android APK** | GitHub Release **CPharmFarmRemote.apk** — big-button farm controller + money scorecard |
| Live API | `GET /api/scorecard` — `targets`, `scaling_incremental`, `profitability` |
| Save Mantis from phone | `POST /api/scorecard/mantis` → `recordings/scorecard_state.json` |

**APK setup:** Install APK → enter `http://<laptop-ip>:8080` → Fetch live. Laptop needs `CPHARM_BIND=0.0.0.0` and firewall open on dashboard port.

---

## Key repo paths

| Need | Path |
|------|------|
| Tap regions | `automation/dabflow_layout.py` |
| Zones JS | `dabflow-fix/app.js` |
| Human variation runtime | `automation/human_variation.py` |
| Humanize JSON | `wizard/sequence_humanize.py` |
| Scorecard API | `automation/scorecard_api.py` |
| **Phone scaling** | `docs/MANTIS_FARM_PHONE_SCALING.md` |
| Scheduler | `automation/scheduler.py` |
| Groups | `automation/recordings/groups_config.json` |
| Sequences | `sequences/` → `C:\CPharm\sequences` |
| Android app | `scorecard-android/` |
| Sync laptop | `scripts/SYNC_CPHARM_FROM_GITHUB.ps1` |

---

## Git / ship workflow

1. Edit sequences or automation on laptop or via agent.
2. `git commit` + `git push origin main`.
3. Laptop: `git pull` + SYNC script.
4. CI builds **CPharm.exe** + **CPharmScorecard.apk** on push to `main`.
5. Verify Release on GitHub before telling operator “build shipped.”

---

## One-liner

**~16–18k impr/day at N=4** (scale with N per `MANTIS_FARM_PHONE_SCALING.md`), random 3–5s dwell, evCPM ≥ $2, ad clicks capped per `scaling_targets(N)`, browse-only after cap.
