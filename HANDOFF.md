# HANDOFF — current (2026-08-16)

**New desktop pickup:**

1. [`docs/SITUATION_2026-08-16.md`](docs/SITUATION_2026-08-16.md)  
2. [`docs/TRANSFER_TO_NEW_DESKTOP_CURSOR.md`](docs/TRANSFER_TO_NEW_DESKTOP_CURSOR.md)  

| Who | Job |
|-----|-----|
| **Cursor** | Setup / diagnose **only** |
| **`C:\PharmFlow\PharmFlow.exe`** | **Runs the farm** — Start farm in the UI |
| **MuMu x64** | Phones |

## Never (Cursor / Python)

Do **not** start the farm with `ensure_farm_24x7.py`, `run_farm_354.py`, or `start_hidden.py`.  
If there is no dash: open **PharmFlow.exe** → **Start farm**.

## Product

- Product: **`C:\PharmFlow\PharmFlow.exe`** from the latest [GitHub Release](https://github.com/twoskoops707/cpharm/releases). Logs stay under `C:\CPharm\`.
- Ship fixes as a new Release EXE — not live `.py` copies onto `C:\PharmFlow\`
