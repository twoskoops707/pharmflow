# Sequences (local only)

Production sequence JSON files are **not stored in git**. Generate and store them on your PC:

```text
%USERPROFILE%\CPharm\sequences\
  900x1600\
    ad\       ← DabFlow ad-path combos
    no-ad\    ← same matrix without ad clicks
  720x1280\ …
```

## Generate the full matrix

```powershell
cd C:\Users\jsmil\CPharm\cpharm-clone\automation
python generate_dabflow_gold_matrix.py
# optional: set CPHARM_SEQUENCES_DIR to override the default folder
```

## Wizard / Groups

In **Groups → Edit**, playlist entries use paths like:

`900x1600/ad/dabflow__ad__mat-ceramic__conc-distillate__heat-propane__timer1x__human080.json`

See `docs/operator_sequences_900x1600.md`.
