# PharmFlow Scaling Plan — More Phones

_Measured on the live box 2026-09-10. Re-measure before acting; numbers below are facts, not guesses._

## Current limits (measured)

| Resource | Value | Status with 7 phones |
|---|---|---|
| CPU | 8 cores / 8 logical (no SMT) | **97% load — binding constraint** |
| RAM | 15.61 GB total | ~1.1 GB free |
| Per-VM RAM (all-in) | `vmmemNemu` 715–1034 MB + ~230 MB shell ≈ **~1.05 GB** | 7 × 1.05 ≈ 7.4 GB |
| Per-VM vCPU | 2 cores configured per guest | 14 vCPU on 8 cores = 1.75:1 overcommit |
| Per-VM disk | ~3.6 GB image | 351 GB free → disk is never the limit |
| Pagefile | 28.7 GB allocated | crash net exists, but thrash = the freeze we lived |

**Key fact: CPU, not RAM, is the current wall.** 7 phones already push 97% load. Adding VMs on 8 cores makes every phone slower (the lag audit showed steps crawl at 100% CPU) — marginal added phones earn ≈ $0 extra and cause timeout cascades.

## Phase 0 — now, 16 GB, 8 cores: stay at 7 (max 8)

- Do **not** add phones for throughput. There is no CPU headroom.
- Only acceptable add: +1 phone during a money-day push **if** 10-min avg CPU < 70% AND free RAM ≥ 2 GB. Cull it (newest first) when pressure returns.

## Phase 1 — 32 GB RAM, same 8-core CPU: 10–12 phones

- RAM math: 32 − ~3 GB host stack (EXE, WebView2, dashes, 9 lanes, Tor) − 2 GB safety = ~27 GB → RAM would allow ~24 VMs. **The CPU is what caps you at 10–12.**
- What the extra RAM actually buys even at 10 phones: no thrash kill-zone, roomier pagefile, Tor/browser caches, zero RAM-crash repeats.
- Per-VM trims to test before scaling (each may buy ~15–25% CPU back):
  1. MuMu preset 1024 MB (config shows custom 1536 MB; measured use is ~850 MB — reclaim works)
  2. Try 1 guest core on 2–3 phones; watch sequence wall-time (manual band: 400–600s/cycle)
  3. Cap MuMu frame rate (frames are pure CPU on ad-scroll heavy cycles)

## Phase 2 — 32 GB + CPU upgrade (12–16 cores): 16–24 phones

- Rule of thumb from tonight's data: **each +4 physical cores ≈ +3–4 phones** at 2 guest cores each, keeping total overcommit ≤ 2:1 with load ≤ 85%.
- 16 cores → ~16–18 phones; 24 cores → ~24 phones (RAM then needs 48 GB if you pass ~24).

## Safest boot order (any phase)

1. **Pre-flight per boot:** free RAM ≥ 2 GB, no orphan tor, adb server healthy (`adb devices` snappy), disk > 50 GB.
2. **One VM at a time, 90–120 s apart** — simultaneous Android boots thrash CPU.
3. **Wait for adoption between boots:** transport shows `device` AND farm log shows the new `ONLINE <name>` line before starting the next VM.
4. **Gate on CPU after each boot:** 60-s avg load < 70% before the next boot; if > 85%, stop — you found the ceiling.
5. **RAM pressure rule:** free < 0.8 GB → stop the newest VM first (never one running an active sequence — that's killing an earner).
6. **Never boot during the UTC-midnight money window** unless a phone died — boot storms cost more than the phone earns in that hour.

## Watch metrics after every scale-up (24 h before adding more)

- `farm_money_history.jsonl`: impressions **per phone per hour** must not drop > 20% vs the pre-scale day.
- `farm_354.log`: ADB timeout count per hour (storm = over-committed).
- Sequence wall-time: mean P3 cycle must stay in the 400–600 s band.
- RAM: free must never sit < 1 GB for more than a few minutes.
