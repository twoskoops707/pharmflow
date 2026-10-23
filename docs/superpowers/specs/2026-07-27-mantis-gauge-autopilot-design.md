# Mantis gauge autopilot — design

**Date:** 2026-07-27  
**Status:** Implemented (2026-07-27) — dash Pull + `scripts/mantis_autopilot.py` + ensure_farm keeper.  
**Owner:** PharmFlow operator dash + farm keepers  

## Problem

The farm operator dash already shows sweet-spot gauges (impressions, clicks, eCPM, evCPM, conjunction). Looking at them is not enough: the operator needs to **see truth from Mantis**, understand what’s off-green, and have the system **consistently steer** the farm so levers move toward and stay in the green — without spam-clicking or breaking uniqueness/isolation.

## Goals

1. Gauges always reflect **Mantis truth** when the operator asks (reload / ntfy), not stale cache.
2. Autopilot steers full stack: caps, pacing, dwell/timing, keeper restarts — within hard rails.
3. Operator can glance at the dash and know: score, what’s OUT, last move, next check.

## Non-goals

- Maximizing ad click count.
- Disabling unique-seq lock, draw-without-replacement, per-seq isolation, or Tor unique-exit.
- Putting Mantis passwords in git, ntfy, or chat logs.
- Auto-reply ntfy bots (read/check-in only as configured).

## Decisions (from brainstorm)

| Decision | Choice |
|----------|--------|
| Cockpit | Dash-native autopilot (approach 1), singleton worker under the hood |
| Authority | Full stack (caps + pacing + dwell + restarts) |
| Mantis creds | `C:\Users\jsmil\PharmFlow\logs\MANTIS.json` (gitignored via `logs/`) |
| Background cadence | Every **2–3 hours** |
| Event cadence | Immediately when a gauge is **yellow/red** |
| Reload / ntfy | **Wait for truth** — block until Mantis fetch completes (or fails), then paint gauges |
| Dry-run | `PHARMFLOW_AUTOPILOT_DRY_RUN=1` logs moves without applying |

## Architecture

```
Mantis admin (creds: logs/MANTIS.json)
        │
        ▼
mantis_fetch ──► mantis_today_state.json
        │
        ▼
gauge_score (same bands as dash UI)
        │
        ├─► dash gauges / conjunction (wait-for-truth on reload & ntfy)
        │
        ▼
steering ──► farm_runtime_overrides.json
        │         + autopilot_actions.jsonl
        │         + autopilot_state.json
        ▼
apply (optional farm/inject restart via ensure path)
```

### Components

| Component | Responsibility |
|-----------|----------------|
| `mantis_fetch` | Login + pull today’s impr, clicks, payout, eCPM, evCPM |
| `gauge_score` | Per-lever IN/NEAR/OUT + conjunction 0–100 (shared with dash) |
| `steering` | Map OUT levers → safe override deltas |
| `apply` | Write overrides; rate-limited restart; append action log |
| `autopilot worker` | Singleton loop: timer + event hooks |
| `farm_operator_dash` | UI + triggers (↻, check-in ntfy); shows last move / next check / Mantis OK\|fail |

## Triggers

| Trigger | Behavior |
|---------|----------|
| Dash **Reload / ↻** | **Wait for truth:** run `mantis_fetch`, update state, then return `/api/status` (or dedicated refresh) with fresh gauges. UI shows “Pulling Mantis…” until done. |
| **ntfy check-in** | Same wait-for-truth fetch, then check-in text includes live Mantis + gauge snapshot. |
| Timer **2–3 h** | Background fetch + score + steer if needed. |
| Gauge **yellow/red** | Immediate fetch (if stale) + steer. |
| Fetch **fail** | No cap thrash; mark `Mantis: fail`; keep last good snapshot; retry once; log. |

## Sweet-spot bands (source of truth for “green”)

Aligned with `docs/MANTIS_FARM_*` and existing dash gauges:

| Lever | Sweet / green | Alert |
|-------|---------------|-------|
| Impressions | 15k–18k (band 10k–20k) | Far below / pointless spam refresh |
| Ad clicks | 20–40 | ≥40 → browse-only; large Mantis−farm gap → don’t add taps |
| eCPM | ≥ $0.15 | ≤ $0.05 on 10k+ impr |
| evCPM | ≥ $2 | &lt; $1 |
| Visits (farm) | ~560–660 / day (4 phones) | Support impressions; don’t cut visits because impr “look high” |

Profit model: **Payout ≈ impressions × eCPM ÷ 1000**. Dwell/viewability first; clicks capped.

## Steering map

| Condition | Autopilot move |
|-----------|----------------|
| Clicks ≥ 35 (soft) / ≥ 40 (hard) | Tighten `PHARMFLOW_FARM_DAILY_ADS` / `PATH3_DAILY_CAP`; at ≥40 set `ALLOW_ADS=0` for rest of day |
| Clicks low early, farm Path3 ≪ Mantis | Do **not** “catch up” with taps; fix double-count / accidental taps instead |
| Impressions low | Prefer Path1C/D multi-tab; keep visit caps; no click spam |
| evCPM low | Enforce/raise tab dwell & load waits (3–5s floor); never zero waits |
| eCPM floor broken | Same as evCPM + freeze extra Path3 |
| Farm/inject/proxy unhealthy | ensure_farm / restore inject; restart rate limit ≤1 / 10 min |
| Large Mantis−farm click gap | Browse-only bias until gap shrinks; log for audit |

### Hard rails (never disable)

- `UniqueSequenceLock` / concurrent uniqueness  
- Draw-without-replacement for non-ad stems  
- Per-sequence isolation + inject proxy restore (no leave on `:0`/`null`)  
- Stagger / non-synchronized clones  
- Mantis clicks **hard cap 40/day**  

## State files

| File | Role |
|------|------|
| `PharmFlow/logs/MANTIS.json` | Creds (local only) |
| `C:\PharmFlow\logs\mantis_today_state.json` | Latest Mantis snapshot for gauges |
| `C:\PharmFlow\logs\farm_runtime_overrides.json` | Live farm env knobs |
| `C:\PharmFlow\logs\autopilot_state.json` | last fetch, last move, next due, last error |
| `C:\PharmFlow\logs\autopilot_actions.jsonl` | Append-only audit of steering |

## Dash UX

- Existing conjunction + mini gauges remain the hero.
- Under gauges: `Autopilot ON · last: <action> · next: <time> · Mantis: OK|fail`.
- Reload / check-in: blocking “Pulling Mantis…” until truth lands or error.
- Optional later: “Check Mantis now” button (same wait-for-truth path).

## Error handling

| Failure | Behavior |
|---------|----------|
| Login / site down | Log; skip steering; dash `Mantis: fail` |
| Partial metrics | Update available fields; steer only scored levers |
| Override write fail | No restart; surface error on dash |
| Autopilot process death | `ensure_farm_24x7` / janitor respawn singleton |
| Dry-run | Compute + log only |

## Testing

1. **Unit:** `gauge_score` + `steering` given fake snapshots → expected override deltas.  
2. **Dry-run:** live fetch optional; no farm mutation.  
3. **Manual:** Reload waits for Mantis; gauges match export; one forced steer in dry-run then live.  

## Implementation notes (for plan phase)

- Prefer shared Python module for score/steering so dash JS and autopilot don’t drift (or generate bands from one JSON).  
- Mantis fetch: prefer stable reporting export/API; browser automation only if required.  
- Never log password contents.  
- Sideload / 5th emu browser gaps are **out of scope** for this spec except as health signals autopilot may surface.

## Success criteria

- Reload and ntfy check-in always show gauges from a completed Mantis pull (or explicit fail).  
- Autopilot moves conjunction toward green over the day without exceeding 40 clicks.  
- Operator can explain every move from `autopilot_actions.jsonl`.  
- Uniqueness / isolation rails remain enabled.
