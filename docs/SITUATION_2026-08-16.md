> **Superseded:** the product is a single `PharmFlow.exe` in `C:\PharmFlow\` (`--watchdog`, `--agent`, phone setup in-process). Data still lives under `C:\PharmFlow\`. Ignore EXE names below.

# Farm situation brief — 2026-08-16 (for the other desktop)

## STOP — how this PC runs the farm

| Correct | Wrong |
|---------|--------|
| Install **`C:\PharmFlow\PharmFlow.exe`** from Release **wizard-64+** | `py scripts\ensure_farm_24x7.py` |
| Human clicks **Start farm** in the **PharmFlow UI** | `py scripts\run_farm_354.py` / `start_hidden.py` |
| Dash from PharmFlow: `http://127.0.0.1:8091/` | Cursor “starts the farm” from the terminal |

**Cursor = setup/diagnose. PharmFlow.exe = farm.**  
Full setup: [`TRANSFER_TO_NEW_DESKTOP_CURSOR.md`](TRANSFER_TO_NEW_DESKTOP_CURSOR.md).

---

## What the other desktop must install

| Item | Value |
|------|--------|
| Repo | `main` (`git pull`) — for **docs/source**, not to run the farm |
| **Product** | **[PharmFlow.exe @ wizard-64](https://github.com/twoskoops707/PharmFlow/releases/tag/wizard-64)** → `C:\PharmFlow\PharmFlow.exe` |
| Emulator | **MuMu Player x64 only** |
| Success | `PharmFlow.exe` running + **Start farm** clicked + 4–6 ADB phones + dash `:8091` |

Secrets zip = private (USB/Desktop). Never commit.

---

## Money / ads situation (why payout looked “healthy” while junk)

### Live symptoms (source farm, afternoon PT 2026-08-16)

- Payout stuck ~**$4.36**, eCPM ~**$0.15–0.16**, impressions ~**27k–28k**, tone **behind** ($40 floor).
- SSP often **`paying=0` `house=8`**.
- Bottom ads can be **visible** while money is junk — **visible ≠ paying**.

### Root causes (fixed on `main`, in EXE **1.4.9** / wizard-64)

1. **Immortal SSP paying fill** — fill `ts` kept refreshing → same creative forever. Fix: no ts refresh; expire/clear. (`f3022ea3`)
2. **Money monitor lied OK** — only watched flat $; set `last_ok` on junk eCPM; **hold** rails on house-only. Fix: alert on house/dilution/junk; heat_down; `money_ok` needs paying + eCPM. (`2c58e9e8`)
3. **`watch_bottom_ads` overwrote honest** — now writes `FARM_BOTTOM_ADS_NOW.txt` only.
4. **Health audit** — behind no longer blocks heat_down when house/dilution present.
5. **Path3** — **FarmBrowser** (`com.farmbrowser.stealth.debug`) primary; Chromium CDP fallback per SSOT.

### Never repeat

Do not “fix” by copying PharmFlow `.py` onto `C:\PharmFlow\`. Ship a new **Release EXE**.  
Do not “fix” a missing Start farm by launching Python ensure/farm_354 from Cursor.

---

## How to read money truth

| File | Meaning |
|------|---------|
| `C:\PharmFlow\logs\farm_money_monitor_state.json` | `alert`, `money_ok`, `problems` |
| `C:\PharmFlow\logs\FARM_MONEY_HEALTH.json` | Short snapshot |
| `C:\PharmFlow\logs\FARM_HONEST_NOW.txt` | Remediator + money_monitor |
| `C:\PharmFlow\logs\FARM_BOTTOM_ADS_NOW.txt` | Ads UI only — not money OK |

Trust `money_ok` + SSP `paying>0` + non-junk eCPM — not ads-visible alone.

---

## Cutover

1. New PC: install **PharmFlow.exe**, MuMu x64, secrets → wizard → **human Start farm** → `:8091`.  
2. Old PC: **Stop farm** in PharmFlow; kill leftover `ensure_farm` / `run_farm_354` if any.  
3. One PC farms Mantis per day.

---

## Doc map

| Doc | Role |
|-----|------|
| [`TRANSFER_TO_NEW_DESKTOP_CURSOR.md`](TRANSFER_TO_NEW_DESKTOP_CURSOR.md) | Setup — **PharmFlow.exe only** |
| This file | Situation + money findings |
| [`START_HERE.md`](START_HERE.md) | Operator short path |
| [`../PHARMFLOW_EXE_HANDOFF.md`](../PHARMFLOW_EXE_HANDOFF.md) | Rebuild/ship EXE |
