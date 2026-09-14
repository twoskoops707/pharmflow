> **Superseded:** the product is a single `PharmFlow.exe` in `C:\PharmFlow\` (`--watchdog`, `--agent`, phone setup in-process). Data still lives under `C:\PharmFlow\`. Ignore EXE names below.

# Overnight completion handoff — 2026-07-05

Read this first in the morning. MuMu was **offline** overnight (no ADB devices); all **code + sequences + tests** were finished on the host.

## What was fixed

### Age gate timing (human_pace_v8)
- Generator tightened pre-site path: **~1.5–2s** from `open_url` to age tap (was up to ~3.5s).
- Runtime caps age `pre_wait_ms` at **250ms**; faster retry gaps on age tap.
- **480 matrix JSON** regenerated (all resolutions) + demo ONE/TWO + 5 mantis-hardcode tests.
- Synced to `C:\PharmFlow\sequences` and `%USERPROFILE%\PharmFlow\sequences`.

### Mantis on-site ads (execute_steps gap closed)
- `setup_wizard.execute_steps` now applies `dabflow_mantis_client_patch` after getdabflow `open_url` (same as dashboard).
- Shared helper: `maybe_apply_after_open_url_step()` in `dabflow_mantis_client_patch.py` (no duplicate inject logic).

### Sequence integrity
- `timer_complete` waits **never merge** with adjacent waits (fixes humanize + preserves full timer seconds).
- Audit: **0** consecutive-duplicate violations across all sequence JSON.

### Live runners
- `_run_mantis_hardcode_live.py` — picks current MuMu IPs (`10.0.2.108`, `10.0.2.229`, …).
- `_run_age_gate_live.py` + `scripts/RUN_AGE_GATE_LIVE.bat` — quick proof loaded→age ≤ ~3.5s.

## Verification (host, no MuMu required)

```powershell
cd C:\PharmFlow\pharmflow-main
$py = "$env:LOCALAPPDATA\Programs\Python\Python311-arm64\python.exe"
# All unit tests
Get-ChildItem automation\test_*.py, wizard\test_*.py | ForEach-Object { & $py $_.FullName }
# Sequence duplicate audit (should print violations 0)
cd automation
& $py -c "from sequence_step_audit import find_consecutive_duplicate_violations; ..."
```

**Result this session:** all **20** test modules **PASS**; sequence audit **0 violations**.

## Morning checklist (MuMu live)

1. Start MuMu phones → `adb devices -l` must show `device` (not empty/offline).
2. **PharmFlow.exe** → **GO** (browser, fingerprint, sync sequences).
3. **PharmFlow.exe** → Boot → Go (Tor + groups).
4. Age gate smoke:
   ```powershell
   cd C:\PharmFlow\pharmflow-main
   scripts\RUN_AGE_GATE_LIVE.bat
   ```
   Expect `loaded_to_age_sec` **≤ 3.5** in `C:\PharmFlow\AGE_GATE_TIMING.txt`.
5. Full mantis-hardcode:
   ```powershell
   scripts\RUN_MANTIS_LIVE.bat
   ```
   Expect `result=PASS`, `wall_sec` **≥ 180** in `C:\PharmFlow\MANTIS_HARDCODE_LIVE.txt`.

## Git / release

Local branch has uncommitted work (generator, wizard, sequences, runners). After review:

```powershell
cd C:\PharmFlow\pharmflow-main
git add -A
git commit -m "..."
git push origin main
```

Then wait for GitHub Actions → new **wizard-*** release → `SYNC_PHARMFLOW_FROM_GITHUB.ps1` on the farm PC.

## Known external item (DabFlow site)

Production `app.js` zone typos still exist on Cloudflare until DabFlow `web` branch is redeployed. PharmFlow CDP patch compensates at runtime when browser has `--remote-debugging-port=9222` (MuMu Setup GO).

## Files touched (summary)

| Area | Files |
|------|--------|
| Sequences | `sequences/**` (480 matrix + demos + mantis-hardcode) |
| Generator | `automation/generate_dabflow_gold_matrix.py` |
| Runtime | `wizard/setup_wizard.py`, `automation/dashboard.py`, `automation/dabflow_mantis_client_patch.py` |
| Normalize | `automation/sequence_normalize.py` |
| Runners | `_run_mantis_hardcode_live.py`, `_run_age_gate_live.py`, `RUN_AGE_GATE_LIVE.bat` |
| Tests | `test_sequence_wait_duplicates.py` |

Good night — run the MuMu checklist above when phones are up.
