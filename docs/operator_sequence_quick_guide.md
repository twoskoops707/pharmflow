# Operator Sequence Quick Guide

## DabFlow blueprint (v3)

CPharm Studio **Builder** embeds the full combinatorial catalog:

- **60 cores:** 3 materials × 10 concentrates (incl. `hash_rosin`) × 2 heaters
- **Path1 A–D** (no ads): `p1a_complete_<browser>`, `p1b_<tab>_complete_<browser>`, …
- **Path2:** halfway exit (`timer_halfway_<browser>`)
- **Browsers (Path1/2):** `_chromium` / `_firefox` / `_brave` — sideload only, **no Play Store**
- **Path3 A–D** (exactly one ad, Chromium only): `p3a_homeadN_ad`, tab flows with `on<tab>_adN_ad`
- **~7260** sequences total; `REQUIRED_SEQUENCE_VERSION = 3` — older JSON is refused

Live coords (900×1600): Start Perfect Dab is **below the fold** — sequences scroll into view then tap `#start-dab-btn`. Blind tap without scroll fails. Age Yes ~(380,980); session notes Skip ~(229,1201); nav y≈1535.

**Browsers:** [docs/multi_browser_sideload.md](multi_browser_sideload.md) — download/update APKs, no Google credentials.

**Regenerate:** Builder → **Regenerate all sequences** (or `py scripts/generate_dabflow_sequences.py`).

## Running a Sequence

### From Desktop Wizard (CPharm.exe)

1. **Builder → Site Interview** — answer questions for your website or APK → generate humanized sequences
2. Open **Run** step — pick a sequence file/folder (or the site folder under sequences)
3. Select phone(s) → **Run**, or use **Start farm** / **Stop farm** for multi-phone cadence
4. Farm cadence saves phone count / sequences-per-hour / ads-per-hour / hours; Start farm applies them
5. Each phone gets a randomized full-hour schedule and a pronounced startup band (30-minute spread by default); concurrent phones cannot reserve the same sequence

## Site Interview + optional AI

1. Builder → Site Interview — answer questions for any website or APK
2. Optional: paste an OpenAI-compatible API key → **Suggest with AI…** → confirm before fields apply
3. **Save profile + generate sequences**
4. Run → Start farm / Stop farm (the active profile's generated folder is the farm catalog)

AI never auto-starts the farm. Offline Q&A works with no key. ntfy digests default to every 2 hours and are silent between digests.

### From Dashboard (http://localhost:8080)

1. Ensure target phone is **Running**
2. Select sequence from dropdown (v3+ only)
3. Click **Run Now**

### Farm CLI — DO NOT USE ON A NEW DESKTOP

**New / transfer PCs:** start the farm only with **`C:\CPharm\CPharm.exe` → Start farm**.  
Do **not** run `py scripts/run_farm_354.py` from Cursor to “bring the farm up.”

The CLI below is for advanced/dev use when an operator already owns the stack via CPharm — not for transfer setup.

```powershell
# DEV ONLY — not the transfer / new-desktop start path
# Prefer: CPharm.exe → Start farm
```

## Writing a custom sequence

1. Prefer `automation/recordings/sequences/base/<material>/…` for DabFlow blueprint files
2. Set `"sequence_version": 3`, `author_width: 900`, `author_height: 1600`
3. Author taps/swipes in that space; include scroll before Start Perfect Dab
4. Test on one phone before scheduling

### Template

```json
{
  "name": "my_sequence",
  "phone": "Phone-01",
  "sequence_version": 3,
  "author_width": 900,
  "author_height": 1600,
  "steps": [
    {"action": "rotate_identity", "params": {}, "description": "Fresh IP + identity"},
    {"action": "wait", "params": {"seconds": 8}, "description": "Cold boot wait"},
    {"action": "open_url", "params": {"url": "https://target-site.com"}},
    {"action": "wait", "params": {"seconds": 3}},
    {"action": "tap", "params": {"x": 450, "y": 1200}},
    {"action": "swipe", "params": {"x1": 450, "y1": 1400, "x2": 450, "y2": 600, "duration_ms": 400}}
  ]
}
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Refused sequence_version | Regenerate from Builder; need v3+ |
| Start Perfect Dab missed | Must scroll into view first; runner uses live `#start-dab-btn` bounds |
| Wrong tap position | Coords scale from 900×1600 |
| Tor IP not changing | `rotate_identity` step; check `tor/` binary |
| Browser FRE / omnibox | Chromium FRE Skip only when splash visible; omnibox defocus after open_url |

## Best Practices

1. Start with `rotate_identity` for fresh IP when needed
2. Wait after cold boot / site load
3. Use `open_url` not raw shell intents
4. Prefer Chromium for DabFlow (mapped + FRE dismiss)
5. Use farm cadence: 15 starts/hour/phone spread across the entire hour; Path3 defaults to 1/hour/phone
