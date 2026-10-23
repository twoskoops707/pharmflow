# Sequence Verification Report

Generated: 2026-05-05 (local)
Scope: `c:\Users\jsmil\PharmFlow\pharmflow-clone`

## Checks Run

1. Schema/JSON parse + sequence rules:
   - `py -3 automation/verify_sequences.py`
2. Template consistency smoke check:
   - `py -3 automation/smoke_sequence_template_consistency.py`
3. Sequence module import smoke:
   - `py -3 -c "import sequence_normalize, sequence_geometry, verify_sequences; print('ok: sequence module imports')"` (from `automation/`)
4. Sequence consistency scripts discovery:
   - Located and used: `automation/verify_sequences.py`, `automation/smoke_sequence_template_consistency.py`

## Initial Failures

Initial `verify_sequences.py` run failed with 60 issues:
- 59 consecutive `wait` violations
- 1 combo-tail violation (`open_getdabflow__combo_landing_short__rotate_wait_fullreset.json` did not end with `rotate_identity -> wait -> full_reset`)

Representative failure output:

```text
FAILED: 60 issue(s) found
- sequence:open_getdabflow_app__w4s__tap_consent_strip__tap_age_modal__tap_C_lmid__w4s__tap_L_umid__w6s.json: consecutive waits at step indexes 1 and 2
- sequence:open_getdabflow__timer_scroll_x7__cleanup.json: consecutive waits at step indexes 3 and 4
- ...
- sequence:open_getdabflow__combo_landing_short__rotate_wait_fullreset.json: combo sequence must end with ['rotate_identity', 'wait', 'full_reset']; got ['tap', 'wait', 'rotate_identity']
```

## Fixes Applied

Applied safe automated repairs for easy breakages:
- Collapsed adjacent `wait` steps into a single `wait` in sequence files.
- Collapsed adjacent `wait` steps in `recordings/groups_config.json` phone step lists.
- Normalized combo sequence tail for `_combo_` sequences to end with:
  - `{"type":"rotate_identity"}`
  - `{"type":"wait","seconds":2.5}`
  - `{"type":"full_reset"}`

Repair script summary:

```text
changed_files=14 wait_collapses=59 combo_fixes=1
```

## Post-Fix Verification Results

`py -3 automation/verify_sequences.py`

```text
OK: validated 134 JSON file(s); checked 140 step collections
```

`py -3 automation/smoke_sequence_template_consistency.py`

```text
ok: validated 132 sequence files + template propagation
```

Import smoke:

```text
ok: sequence module imports
```

## Notes

- `python` was not available via PATH alias in this environment; `py -3` was used for all checks.
- Repository git metadata was not available from `pharmflow-clone` during this run (`fatal: not a git repository`), so this report records command evidence rather than git diff metadata.
