# Mantis farm — daily scorecard

**Use with:** `docs/MANTIS_FARM_SEQUENCE_GUIDANCE.md` (operator runbook + agent rules).

Fill **one row per calendar day**. Farm logs and the Mantis export must cover the **same date**.

---

## Quick copy — today's numbers

| Section | Field | Value |
|---------|-------|-------|
| Farm | Phones running | |
| Farm | Successful visits (total) | |
| Farm | Farm-counted ad clicks | |
| Mantis | Impressions | |
| Mantis | Ad clicks | |
| Mantis | Payout ($) | |
| Mantis | eCPM | |
| Mantis | evCPM | |
| Mantis | CTR% | |
| Calc | impressions_per_visit | |
| Calc | blended_ecpm | |
| Calc | $/ad_click | |
| Calc | visits_per_ad_click | |
| Calc | evcpm_ceiling_$ | |
| Calc | click_contribution_$ (est.) | |
| Status | Green / Yellow / Red | |

---

## Formulas (always compute after export)

Spreadsheet-friendly (Excel / Google Sheets). Replace cell refs with your columns.

```
impressions_per_visit   = Mantis_impressions / farm_visits
blended_ecpm            = payout / Mantis_impressions * 1000
$/ad_click              = payout / Mantis_clicks          (if clicks > 0)
visits_per_ad_click     = farm_visits / Mantis_clicks     (if clicks > 0)
ctr_on_impressions_%    = Mantis_clicks / Mantis_impressions * 100
evcpm_ceiling_$         = Mantis_impressions * evCPM / 1000
display_payout_$        = Mantis_impressions * eCPM / 1000   (should ≈ payout)
gap_evcpm_vs_ecpm_$     = evcpm_ceiling_$ - payout
click_contribution_$   = Mantis_clicks * $/ad_click        (informational)
monthly_run_rate_$      = payout * 30
```

Python (paste export row):

```python
impr, clicks, payout, ecpm, evcpm = 17723, 32, 0.85, 0.05, 0.34
visits = 703
impr_per_visit = impr / visits
blended = payout / impr * 1000
per_click = payout / clicks if clicks else 0
visits_per_click = visits / clicks if clicks else 0
ceiling = impr * evcpm / 1000
print(impr_per_visit, blended, per_click, visits_per_click, ceiling)
```

---

## Thresholds (4-phone farm)

| KPI | Green | Yellow | Red — act today |
|-----|-------|--------|-----------------|
| **evCPM** | ≥ $2.00 | $1.00 – $1.99 | **< $1.00** → enforce tab dwell 3–5 s |
| **eCPM** | ≥ $0.15 | $0.06 – $0.14 | **≤ $0.05** on 10k+ impr → dwell/load fix |
| Impressions | 10k – 20k | 8k – 10k or 20k – 22k | < 5k or > 25k without explanation |
| Ad clicks (Mantis) | 20 – 40 | 41 – 60 | **> 60** or **> 80** |
| CTR on impressions | 0.15% – 0.35% | 0.35% – 0.50% | **> 0.50%** sustained |
| impressions/visit | 18 – 28 | 15 – 18 or 28 – 32 | Wild swing vs prior week |
| Farm vs Mantis clicks | within ~10% | 10% – 25% gap | > 25% gap → audit tap regions |
| Payout | rising vs $0 streak | flat | **$0** with 5k+ impr + clicks |

### Rest-of-day actions

| Condition | Action |
|-----------|--------|
| Mantis ad clicks ≥ **40** | Schedule **browse-only** (no ad taps) for remainder of day |
| evCPM < **$1** | Do **not** add clicks; add/enforce **3–5 s** wait after every tab open |
| eCPM ≤ **$0.05** on 10k+ impr | Same — Jul 26 pattern (unviewed top ads) |
| gap_evcpm_vs_ecpm_$ large | Viewability problem — Mantis Visibility report by zone |

---

## Earnings expectation tables (4 phones, 30-day)

**Primary revenue:** `Payout ≈ Impressions × eCPM ÷ 1,000`. Clicks are **not** the main driver at farm scale (often **$0.03–$0.05/click** at volume).

### Daily payout by eCPM and impressions

| eCPM | 12k impr | 15k impr | 18k impr | 20k impr |
|------|----------|----------|----------|----------|
| $0.05 (fail) | $0.60 | $0.75 | $0.90 | $1.00 |
| $0.21 (Jul 24) | $2.52 | $3.15 | $3.78 | $4.20 |
| $0.56 (Jul 25) | $6.72 | $8.40 | $10.08 | $11.20 |
| $1.00 | $12.00 | $15.00 | $18.00 | $20.00 |
| $2.00 (target) | $24.00 | $30.00 | $36.00 | $40.00 |

### Monthly run rate (payout × 30)

| Scenario | Daily impr | eCPM | Daily $ | Monthly $ |
|----------|------------|------|---------|-----------|
| **Floor (broken)** | 17k | $0.05 | ~$0.9 | ~$27 |
| **Jul 24 style** | 15k | $0.21 | ~$3.2 | ~$96 |
| **Jul 25 style** | 11k | $0.56 | ~$6.2 | ~$186 |
| **Realistic target** | 16k | $0.75 | ~$12 | ~$360 |
| **Strong target** | 18k | $1.00 | ~$18 | ~$540 |
| **Stretch (evCPM recovered)** | 18k | $2.00 | ~$36 | ~$1,080 |

### Click $ contribution (secondary — do not optimize click spam)

| $/click | 20 clicks/day | 35 clicks/day | 40 clicks/day |
|---------|---------------|---------------|---------------|
| $0.03 | $0.60 | $1.05 | $1.20 |
| $0.05 | $1.00 | $1.75 | $2.00 |
| $0.47 (Jul 24 quality) | $9.40 | $16.45 | $18.80 |

At **$0.05/click**, even 117 clicks (Jul 25) only added ~$6 total payout — **display eCPM paid the bill**.

---

## Verified reference days (export)

| Date | Impr | Clicks | Payout | eCPM | evCPM | $/click |
|------|------|--------|--------|------|-------|---------|
| Jul 24 | 15,322 | 7 | $3.27 | $0.21 | $7.36 | $0.47 |
| Jul 25 | 10,955 | 117 | $6.18 | $0.56 | $4.31 | $0.05 |
| Jul 26 | 17,723 | 32 | $0.85 | $0.05 | $0.34 | $0.03 |

---

## Weekly rollup (copy 7 daily rows)

| Week | Sum impr | Sum clicks | Sum payout | Weekly eCPM | Weekly $/click | Best day driver |
|------|----------|------------|------------|-------------|----------------|-----------------|
| | | | | payout/impr×1000 | payout/clicks | evCPM / eCPM / clicks |

---

## Mantis dashboard checks (weekly, ~5 min)

1. [Mantis admin](https://admin.mantisadnetwork.com/v4/login) → **Reporting** → **Impressions**
2. Segment **Visibility** (viewed vs unviewed)
3. Segment **Page Zone** on mobile — worst zones get more dwell in sequences
4. [Ad visibility guide](https://www.mantisadnetwork.com/blog/ad-visibility-explained-earn-mantis-ads)

---

## CSV template

A blank row template lives at `docs/MANTIS_FARM_DAILY_SCORECARD.csv` for spreadsheet import.

**Android:** Install **PharmFlowScorecard.apk** from GitHub Releases (`scorecard-*` tag). Live fetch: `GET /api/scorecard` on farm dashboard.

---

## Changelog

| Date | Change |
|------|--------|
| 2026-07-27 | Standalone scorecard: formulas, thresholds, earnings tables, reference days |
