# Sequence Retest Verification Dossier (Generated)

- Timestamp: `Wednesday, May 6, 2026 0:16:55` (local shell)
- Repo: `c:\Users\jsmil\source\repos\pharmflow`
- Host OS: `Windows 10.0.26200`
- Shell: `powershell`
- Python: `3.14.4`

## Scope and Active Sets

- Active inline set source: `automation/recordings/groups_config.json` (`Group 1`, 3 phone serials, inline steps)
- Active sequence library: `automation/recordings/sequences/*.json`
- Total sequence files revalidated (static): `242`
- Step collections validated by core verifier: `245` (`242` sequence files + `3` groups-config phone step lists)

## Static Validation Evidence

| Check | Command | Result | Pass/Fail |
|---|---|---|---|
| Core JSON + supported actions + no-consecutive-waits + combo tail rule | `py -3 automation/verify_sequences.py` | `OK: validated 244 JSON file(s); checked 245 step collections` | PASS |
| Naming/schema consistency for combo matrix | `py -3 automation/validate_sequence_schema.py` | `OK: validated 108 combo sequence file(s)` | PASS |
| Template consistency propagation smoke | `py -3 automation/smoke_sequence_template_consistency.py` | `ok: validated 242 sequence files + template propagation` | PASS |
| Safety audit | `py -3 automation/audit_sequence_safety.py` | `audit complete: scope=242 files, issues=110, auto_fixed=0, changed_files=0` | PASS (audit completed; issues enumerated in report) |
| Timing profile build | `py -3 automation/build_sequence_timing_profile.py` | `WROTE ... sequence_timing_profile.generated.md; ACTIVE_FLOWS: 3; PATCHED_SHORT_FLOWS: 0` | PASS |
| Runtime static audit | `py -3 automation/sequence_runtime_audit.py` | `scanned=242 suspicious=4 fixed=0` | PASS (audit completed; suspicious entries listed in report) |

### Static output artifacts

- `docs/sequence_safety_audit.generated.md`
- `docs/sequence_timing_profile.generated.md`
- `docs/sequence_runtime_audit.generated.md`
- `docs/sequence_naming_and_schema.generated.md`

## Dynamic Verification Evidence

### Dashboard import/smoke

| Check | Command | Result | Pass/Fail |
|---|---|---|---|
| Dashboard/module import smoke | `py -3 automation/smoke_imports.py` | `smoke_imports: OK  BIND='127.0.0.1'  HTTP=8080  WS=8081  human_variation=True` | PASS |
| Reachable ADB devices snapshot | `adb devices` | `10.0.2.171:5555`, `10.0.2.60:5555`, `10.0.2.93:5555` (all `device`) | PASS |

### Representative runtime runs (major families)

#### Run set A (built-in observed runtime suite, first two online devices)

Command:

`py -3 automation/measure_sequence_runtime_observed.py`

Result artifact:

- `docs/sequence_runtime_observed.generated.md`

Coverage:

- `open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su.json` (no-combo baseline)
- `google_com__tap_serp__getdabflow_funnel__cleanup.json` (no-combo alternate entry path)
- `close_chrome__open_getdabflow_app__w9s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s.json` (combo + webapp tabs/adclick)

Devices covered by this run:

- `10.0.2.171:5555`
- `10.0.2.60:5555`

Observed notable log evidence:

- `ADB failure (swipe) on 10.0.2.171:5555 rc=1 — adb.exe: device offline` captured during one adclick variant run (see artifact section for exact lines).

#### Run set B (expanded probe for timer/no-timer and tabs/adclick families)

Commands:

- `py -3 automation/runtime_probe_retest.py` (targeted third online device)
- `$env:PHARMFLOW_RETEST_SERIAL='10.0.2.171:5555'; py -3 automation/runtime_probe_retest.py` (retest on previously flaky device)

Result artifact:

- `docs/sequence_runtime_retest_probe.generated.md` (last run reflects serial `10.0.2.171:5555`)

Coverage matrix executed:

| Family requirement | Sequence used |
|---|---|
| No-combo, no-timer | `open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su.json` |
| No-combo, timer | `open_getdabflow__timer_scroll_x7__cleanup.json` |
| Combo, no-timer | `sequence_home_combo_v2_entry-google_home_footer-left_hero-on_bottom-left_timer-none.json` |
| Combo, timer | `sequence_home_combo_v2_entry-google_home_footer-left_hero-on_bottom-left_timer-single96.json` |
| Webapp tabs variant | `close_chrome__open_getdabflow_app__w8s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s.json` |
| Webapp tabs + adclick variant | `close_chrome__open_getdabflow_app__w9s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s.json` |

Devices dynamically exercised across both run sets:

- `10.0.2.171:5555`
- `10.0.2.60:5555`
- `10.0.2.93:5555`

## Pass/Fail Summary

| Area | Status | Notes |
|---|---|---|
| Static validations | PASS | All required validators executed successfully with concrete outputs. |
| Dashboard import/smoke | PASS | Import smoke passed with HTTP/WS bind confirmation. |
| Device connectivity | PASS | 3/3 reachable devices detected by `adb devices` at test time. |
| Representative dynamic families | PASS with risk note | Required family variants executed; one transient offline ADB failure observed in one earlier run but not reproduced in focused rerun. |

## Remaining Risks / Blockers (with exact repro commands)

1. Transient ADB offline event can inflate observed runtime and reduce confidence in single-run measurements.
   - Repro command: `py -3 automation/measure_sequence_runtime_observed.py`
   - Evidence location: `docs/sequence_runtime_observed.generated.md` (adclick run on `10.0.2.171:5555`).

2. Safety audit and runtime audit contain non-zero findings that require manual policy triage before declaring strict "zero-findings" quality.
   - Repro commands:
     - `py -3 automation/audit_sequence_safety.py`
     - `py -3 automation/sequence_runtime_audit.py`
   - Evidence locations:
     - `docs/sequence_safety_audit.generated.md`
     - `docs/sequence_runtime_audit.generated.md`

## Untested Areas (and reasons)

- Full dynamic execution of all `242` sequence files was not run (time and device-availability constraints); dynamic checks used representative cross-family sampling plus multi-device coverage.
- No physical USB device runs were included in this retest because only emulator/TCP ADB devices were reachable during execution.

