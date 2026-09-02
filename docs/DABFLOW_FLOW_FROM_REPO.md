# DabFlow canonical flow (from `origin/web` repo)

Source of truth: `C:\Users\jsmil\StudioProjects\DabFlow` branch **`web`** (`origin/web`), deployed at `https://getdabflow.app`.

Key files:

| File | Role |
|------|------|
| `www/index.html` | Screens, age gate, option grids, `#start-dab-btn`, timer UI, `#session-notes-modal`, bottom nav, Mantis `data-mantis-zone` slots |
| `www/js/app.js` | `CONFIG`, `state.settings`, `calculateTimings()`, `startTimer()`, `runTimer()`, `completeTimer()`, `showCompletionAnimation()`, `skipSessionNotes()`, tab nav |
| `www/css/components.css` | `.nav-bar` height **70px**, `.option-grid`, modal/button layout |

Execution note: CPharm dashboard applies **`webview_content_top_inset` (+192px @ 900×1600)** to tap Y at runtime. All coords below are **baseline 900×1600 content coords** (before inset).

---

## Canonical user flow (as implemented)

1. **Age gate → Yes** — `#age-yes-btn` sets `localStorage.dabflow_age_verified`, hides `#age-gate`, shows `#app`, calls `initializeApp()`.
2. **Home selections** — Three independent option groups (defaults: quartz / shatter / butane). Selections are **not enforced** before start; `#start-dab-btn` always calls `startTimer()` with current `state.settings`. Automation still taps all three for deterministic combo coverage.
3. **Start Perfect Dab** — `#start-dab-btn` → `startTimer()` → switches to `#timer-screen`, sets nav `[data-screen="timer"]` active, begins heat phase.
4. **Timer phases** — **Heat** then **Cool** only (no separate “post” countdown). `runTimer()` 1s interval; at heat end switches to cool; at cool end calls `completeTimer()`.
5. **Completion → session notes** — `showCompletionAnimation()` (~5.5s overlays), `switchScreen('home')`, then `showSessionNotesModal()` if trial/premium (`totalSessions ≤ 5` or premium) and notes enabled. Dismiss via **Skip** → `skipSessionNotes()`.
6. **Tab tour** (matrix sequences) — Bottom nav: Home, Timer, Stats, Glass, Settings. Matrix adds Glass art select → BACK → Home, then other tabs before Stats scroll.
7. **Ad path** (matrix `ad/` only) — Home banner → timer cooldown video + timer banners during cool → tab tour taps on Glass / Stats / Settings Mantis zones; Stats dwell **≥30s**.

## Mantis ad slots (DabFlow web app — not configured in CPharm)

CPharm automates taps on Mantis zones defined in the **DabFlow** repo (`origin/web`, `www/index.html`). Publisher/network setup lives there, not in this repo.

**Live deploy audit:** run `python3 automation/audit_dabflow_live.py` — see [DABFLOW_MANTIS_LIVE_AUDIT.md](./DABFLOW_MANTIS_LIVE_AUDIT.md) for known `app.js` bugs (zone typos, cooldown video slot).

| Zone | DOM | Baseline tap (900×1600) |
|------|-----|-------------------------|
| Stats banner | `#stats-screen .ad-container` / `data-mantis-zone` zone-five | (450, 857) |
| Home banner | `#ad-slot-1` zone-one | (450, 964) |
| Timer cooldown video | `#cooldown-video-ad` | (450, 875) |
| Timer banner | `#ad-slot-2` zone-two | (450, 1000) |
| Glass banner | `#ad-slot-8` zone-eight | (450, 1100) |
| Settings banner | `#ad-slot-12` zone-twelve | (450, 1180) |

**If ads do not visually load after a correct tap:**

1. Confirm Mantis is integrated and filling on `https://getdabflow.app` in a normal desktop browser (Stats tab).
2. Premium / ad-free flags in DabFlow `localStorage` block slots — test with a fresh profile (`clear_cookies` step).
3. Tor exit IPs may get low fill — expected for some networks; the automation still performs tap + 30s dwell.
4. On MuMu: sequences must **switch to Stats tab** (`bottom_nav: true` at y≈1566) before tapping (450, 857). Combo ad JSON regenerated 2026-07 fixes ending on Settings without returning to Stats.
5. Farm playlists default to **50/50 no-ad/ad** (`dabflow__demo__ONE.json` + no-ad variants vs `dabflow__demo__TWO.json` + ad variants, `sequence_playlist_shuffle: combined`). Re-run **CPharmMuMuSetup GO** to refresh `groups_config.json` if you still have ad-only playlists.
8. **Identity tail** (matrix) — `close_app` → `rotate_identity` → `full_reset`.

Demo ONE (`dabflow__demo__ONE.json`) covers steps **1–5 + Stats tab** only.

---

## Timing formula (`app.js` → `calculateTimings()`)

```javascript
heatTime  = round(material.heatUp * heater.heatModifier)   // cap maxHeatTime=20
coolTime  = round(material.coolDown * heater.coolModifier * concentrate.coolModifier)
          // floor minCoolTime=50, cap maxCoolTime=85
totalTime = heatTime + coolTime
```

### CONFIG tables (mirrored in `generate_dabflow_gold_matrix.py`)

**Materials**

| Key | heatUp | coolDown |
|-----|--------|----------|
| quartz | 18 | 60 |
| titanium | 15 | 70 |
| ceramic | 20 | 75 |

**Heaters**

| Key | heatModifier | coolModifier |
|-----|--------------|--------------|
| butane | 1.1 | 1.0 |
| propane | 1.0 | 0.95 |

**Concentrates** (coolModifier only)

| shatter 1.0 | wax 0.93 | live-resin 1.05 | rosin 1.08 | diamonds 1.15 |
| crumble 0.95 | budder 0.97 | sauce 1.10 | hash-rosin 1.12 | distillate 0.90 |

**Safety limits:** `maxHeatTime=20`, `minCoolTime=50`, `maxCoolTime=85`.

### Demo combo (ceramic + distillate + propane)

| Phase | Calculation | Seconds |
|-------|-------------|---------|
| Heat | round(20 × 1.0) | **20** |
| Cool | round(75 × 0.95 × 0.90) = round(64.125) | **64** |
| Countdown total | | **84** |

### Automation wait after Start Dab

Must cover countdown **plus** completion animation before Skip is tappable:

```
wait_sec = heat + cool + COMPLETION_ANIMATION_SEC + MODAL_RENDER_BUFFER_SEC
COMPLETION_ANIMATION_SEC = 5.5   // app.js: 3500ms + 1500ms fade + 500ms delay
MODAL_RENDER_BUFFER_SEC  = 1.0   // modal paint buffer
```

Demo ONE: `20 + 64 + 5.5 + 1.0 = **90.5s**`

Matrix sequences add Gaussian jitter on top of the same floor (see `timer_session_wait_seconds()`).

Inter-tap gaps (demo ONE): **0.25–0.35s** between funnel taps.

---

## Coordinates table (900×1600 baseline)

Measured live via `measure_dabflow_coords.py` / Playwright on getdabflow.app (2026-06-19). Defined in `cpharm-clone/automation/dabflow_layout.py`.

| Region | DOM | cx | cy | half_w × half_h |
|--------|-----|----|----|-----------------|
| Age Yes | `#age-yes-btn` | 359 | 912 | 50 × 30 |
| Material quartz | `[data-value="quartz"]` | 163 | 445 | 115 × 22 |
| Material titanium | `[data-value="titanium"]` | 450 | 445 | 115 × 22 |
| Material ceramic | `[data-value="ceramic"]` | 737 | 445 | 115 × 22 |
| Concentrate row 1 | shatter…budder | 81–819 | 535 | 50 × 22 |
| Concentrate row 2 | sauce, hash-rosin, distillate | 81, 204, 327 | 592 | 50 × 22 |
| Heater butane | `[data-value="butane"]` | 235 | 682 | 200 × 22 |
| Heater propane | `[data-value="propane"]` | 665 | 682 | 200 × 22 |
| Start Perfect Dab | `#start-dab-btn` | 450 | 1231 | 400 × 40 |
| Session notes Skip | `skipSessionNotes()` button | **337** | **1266** | 55 × 25 |
| Nav Home / Timer / Stats / Glass / Settings | `.nav-item` | 90 / 270 / 450 / 630 / 810 | 1566 | 72 × 28 |
| Stats Mantis banner | `#stats-screen .ad-container` | 450 | 857 | 140 × 120 |
| Home Mantis banner | `#ad-slot-1` | 450 | 964 | 140 × 120 |
| Glass art card | `#glass-screen a[href*="instagram"]` | 247 | 323 | 180 × 70 |
| Pause / Reset (timer) | `#pause-btn` / `#reset-btn` | 84 / 220 | 767 | 55 × 25 |

**Previous bug:** `SESSION_NOTES_SKIP` was **y=1015** (stale); live modal Skip is **y=1266**.

---

## Sequence step list — demo ONE

| # | Type | Target | Wait / notes |
|---|------|--------|--------------|
| 1 | clear_cookies | | |
| 2 | open_url | getdabflow.app | post_wait 2.0s, checkpoint `loaded` |
| 3 | tap | Age Yes (359,912) | age_verification |
| 4 | wait | 0.35s | |
| 5 | tap | Ceramic (737,445) | |
| 6 | wait | 0.28s | |
| 7 | tap | Distillate (327,592) | |
| 8 | wait | 0.32s | |
| 9 | tap | Propane (665,682) | checkpoint `selections_done` |
| 10 | wait | 0.3s | |
| 11 | tap | Start Dab (450,1231) | checkpoint `timer_started` |
| 12 | wait | 0.25s | |
| 13 | wait | **90.5s** | checkpoint `timer_complete` |
| 14 | tap | Skip (337,1266) | checkpoint `popup_dismiss` |
| 15 | wait | 0.3s | checkpoint `popup_dismissed` |
| 16 | tap | Stats nav (450,1566) | checkpoint `tab_stats` |
| 17 | wait | 0.3s | |

---

## Gap analysis vs old automation

| Issue | Old behavior | Repo truth / fix |
|-------|--------------|------------------|
| Post-timer tap | Tapped **Reset** on timer screen | Must tap **Skip** on `#session-notes-modal` after completion animation |
| Skip Y coord | 1015 | **1266** (measured) |
| Timer wait | `total+20` (~104–108s) or wrong floor | `heat+cool+5.5+1.0` = **90.5s** for demo combo |
| Funnel order | Selections OK | Matches app: material → concentrate → heater → start |
| “Post” phase | Assumed third timer phase | Only heat + cool; “post” = completion overlay + modal |
| Required selections | Sometimes skipped | Not required by app; kept for combo determinism |

---

## Generator & demo paths

- Layout: `cpharm-clone/automation/dabflow_layout.py`
- Matrix generator: `cpharm-clone/automation/generate_dabflow_gold_matrix.py` (fixed funnel: start → wait → skip → tab tour → ad/identity)
- Demo ONE builder: `cpharm-clone/automation/_build_ONE.py` → `sequences/900x1600/no-ad/dabflow__demo__ONE.json`
- Live proof: `cpharm-clone/automation/_proof_demo_ONE_live.py` on device **10.0.2.179**
