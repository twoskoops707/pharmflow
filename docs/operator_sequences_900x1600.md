# Operator guide: 900×1600 sequences (ad vs no-ad)

Production JSON lives **on your PC only** — not in the git repo.

## Local folder (default)

```text
%USERPROFILE%\CPharm\sequences\
  900x1600\
    ad/          ← full DabFlow flows with ad tap + ≥30s dwell + scroll-to-bottom
    no-ad/       ← same combos without ad clicks
  720x1280/ …  (other resolutions, same layout)
```

Override with env: `CPHARM_SEQUENCES_DIR=C:\path\to\sequences`

## Generate the matrix

```powershell
cd C:\Users\jsmil\CPharm\cpharm-clone\automation
python generate_dabflow_gold_matrix.py
```

## Pick ad vs no-ad in Groups

1. Wizard → **Groups** → **Edit** on a phone.
2. Confirm **Sequence screen-size profile** is **900 × 1600**.
3. Under **Saved sequences playlist (Set A)** add either:
   - **Ad path:** `900x1600/ad/dabflow__ad__mat-ceramic__conc-distillate__heat-propane__timer1x__human080.json`
   - **No-ad path:** `900x1600/no-ad/dabflow__no_ads__mat-ceramic__conc-distillate__heat-propane__timer1x__human080.json`
4. Use **filenames with folder prefix** (recommended) or basename only — the dashboard searches `{profile}/ad/` and `{profile}/no-ad/`.
5. **Save** the phone editor, then **Save groups** on the Groups step.

## Flow pattern (every combo)

| Step | Action | Coords (900×1600 baseline) |
|------|--------|----------------------------|
| Timer | Start Dab → wait heat+cool → Reset | START_DAB ~450×1310, RESET ~668×1018 |
| Tab excursion | Glass nav → art card → BACK → Home | Glass nav ~630×1565, GLASS_ART_SELECT ~450×520 |
| Stats scroll | Tab tour → segmented scroll on Stats | Stats nav ~450×1565 |
| Ad path only | Scroll to bottom → ad slot tap → **≥30s wait** → scroll → BACK | STATS_AD_SLOT ~450×708 |

## Ad timing rules

- After tapping the stats ad slot, sequences include a **wait ≥ 30 seconds** before advancing.
- **Scroll-to-bottom** swipes run immediately before the ad tap.

## File naming

```text
dabflow__{ad|no_ads}__mat-{material}__conc-{concentrate}__heat-{heater}__timer{1x|2x}__human{NNN}.json
```

- **Materials:** quartz, titanium, ceramic  
- **Concentrates:** shatter, wax, live-resin, rosin, diamonds, crumble, budder, sauce, hash-rosin, distillate  
- **Heaters:** butane, propane  
- **timer2x** ≈ 20% of combos (two timer cycles)

## Verify locally

```powershell
python verify_sequences.py
python verify_ad_sequence_samples.py
```
