# Sequence Runtime Observed (Generated)

- Generated at: `2026-05-06T06:53:11.624262+00:00`
- Method: `POST /api/groups/run` + WebSocket log completion marker (`[Group] Done ✓`)
- Timing basis: wall-clock from API call dispatch to group done log
- Expected runtime model: step waits + pre-waits + swipe duration + 0.3s inter-step gap (dashboard runner behavior)
- Divergence flag threshold: `abs(observed-expected)/expected > 20%`

## Devices Observed

- `10.0.2.171:5555` (SM A5460, type=wifi, running=True)
- `10.0.2.60:5555` (GC3VE, type=wifi, running=True)
- `10.0.2.93:5555` (SM S9110, type=wifi, running=True)

## Results

| Sequence | Serial | Expected (s) | Observed (s) | Divergence | Flag | Status |
|---|---|---:|---:|---:|---|---|
| `open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su.json` | `10.0.2.171:5555` | 27.300 | 39.283 | +43.89% | YES | ok |
| `open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su.json` | `10.0.2.60:5555` | 27.300 | 39.008 | +42.89% | YES | ok |
| `google_com__tap_serp__getdabflow_funnel__cleanup.json` | `10.0.2.171:5555` | 63.041 | 78.011 | +23.75% | YES | ok |
| `google_com__tap_serp__getdabflow_funnel__cleanup.json` | `10.0.2.60:5555` | 63.041 | 79.918 | +26.77% | YES | ok |
| `close_chrome__open_getdabflow_app__w9s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s.json` | `10.0.2.171:5555` | 81.660 | 96.891 | +18.65% | no | ok |
| `close_chrome__open_getdabflow_app__w9s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s.json` | `10.0.2.60:5555` | 81.660 | 98.367 | +20.46% | YES | ok |

## Divergences >20%

- `open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su.json` on `10.0.2.171:5555`: expected `27.300s`, observed `39.283`, divergence `+43.89%` (status `ok`; note: completed)
- `open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su.json` on `10.0.2.60:5555`: expected `27.300s`, observed `39.008`, divergence `+42.89%` (status `ok`; note: completed)
- `google_com__tap_serp__getdabflow_funnel__cleanup.json` on `10.0.2.171:5555`: expected `63.041s`, observed `78.011`, divergence `+23.75%` (status `ok`; note: completed)
- `google_com__tap_serp__getdabflow_funnel__cleanup.json` on `10.0.2.60:5555`: expected `63.041s`, observed `79.918`, divergence `+26.77%` (status `ok`; note: completed)
- `close_chrome__open_getdabflow_app__w9s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s.json` on `10.0.2.60:5555`: expected `81.660s`, observed `98.367`, divergence `+20.46%` (status `ok`; note: completed)

## Evidence Excerpts

### `open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su.json` on `10.0.2.171:5555`

- Start: `2026-05-06T06:45:54.090502+00:00`
- End: `2026-05-06T06:46:33.373879+00:00`
- Status: `ok`
- Note: completed
- WebSocket logs:
  - `[OBS-open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su-10.0.2.171_5555] Starting on 1 phone(s)`
  - `[OBS-open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su-10.0.2.171_5555] Running [1] on SM A5460 (14 steps)`
  - `[OBS-open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su-10.0.2.171_5555] Resetting identity on SM A5460…`
  - `[OBS-open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su-10.0.2.171_5555] SM A5460 identity reset ✓`
  - `[OBS-open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su-10.0.2.171_5555] Done ✓`

### `open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su.json` on `10.0.2.60:5555`

- Start: `2026-05-06T06:46:34.382301+00:00`
- End: `2026-05-06T06:47:13.390733+00:00`
- Status: `ok`
- Note: completed
- WebSocket logs:
  - `[OBS-open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su-10.0.2.60_5555] Starting on 1 phone(s)`
  - `[OBS-open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su-10.0.2.60_5555] Running [1] on GC3VE (14 steps)`
  - `[OBS-open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su-10.0.2.60_5555] Resetting identity on GC3VE…`
  - `[OBS-open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su-10.0.2.60_5555] GC3VE identity reset ✓`
  - `[OBS-open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su-10.0.2.60_5555] Done ✓`

### `google_com__tap_serp__getdabflow_funnel__cleanup.json` on `10.0.2.171:5555`

- Start: `2026-05-06T06:47:14.393977+00:00`
- End: `2026-05-06T06:48:32.404601+00:00`
- Status: `ok`
- Note: completed
- WebSocket logs:
  - `[OBS-google_com__tap_serp__getdabflow_funnel__cleanup-10.0.2.171_5555] Starting on 1 phone(s)`
  - `[OBS-google_com__tap_serp__getdabflow_funnel__cleanup-10.0.2.171_5555] Running [1] on SM A5460 (35 steps)`
  - `[OBS-google_com__tap_serp__getdabflow_funnel__cleanup-10.0.2.171_5555] Resetting identity on SM A5460…`
  - `[OBS-google_com__tap_serp__getdabflow_funnel__cleanup-10.0.2.171_5555] SM A5460 identity reset ✓`
  - `[OBS-google_com__tap_serp__getdabflow_funnel__cleanup-10.0.2.171_5555] Done ✓`

### `google_com__tap_serp__getdabflow_funnel__cleanup.json` on `10.0.2.60:5555`

- Start: `2026-05-06T06:48:33.418206+00:00`
- End: `2026-05-06T06:49:53.335815+00:00`
- Status: `ok`
- Note: completed
- WebSocket logs:
  - `[OBS-google_com__tap_serp__getdabflow_funnel__cleanup-10.0.2.60_5555] Starting on 1 phone(s)`
  - `[OBS-google_com__tap_serp__getdabflow_funnel__cleanup-10.0.2.60_5555] Running [1] on GC3VE (35 steps)`
  - `[OBS-google_com__tap_serp__getdabflow_funnel__cleanup-10.0.2.60_5555] Resetting identity on GC3VE…`
  - `[OBS-google_com__tap_serp__getdabflow_funnel__cleanup-10.0.2.60_5555] GC3VE identity reset ✓`
  - `[OBS-google_com__tap_serp__getdabflow_funnel__cleanup-10.0.2.60_5555] Done ✓`

### `close_chrome__open_getdabflow_app__w9s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s.json` on `10.0.2.171:5555`

- Start: `2026-05-06T06:49:54.348829+00:00`
- End: `2026-05-06T06:51:31.240002+00:00`
- Status: `ok`
- Note: completed
- WebSocket logs:
  - `[OBS-close_chrome__open_getdabflow_app__w9s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s-10.0.2.171_5555] Starting on 1 phone(s)`
  - `[OBS-close_chrome__open_getdabflow_app__w9s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s-10.0.2.171_5555] Running [1] on SM A5460 (29 steps)`
  - `[OBS-close_chrome__open_getdabflow_app__w9s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s-10.0.2.171_5555] Resetting identity on SM A5460…`
  - `[OBS-close_chrome__open_getdabflow_app__w9s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s-10.0.2.171_5555] SM A5460 identity reset ✓`
  - `[OBS-close_chrome__open_getdabflow_app__w9s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s-10.0.2.171_5555] Done ✓`

### `close_chrome__open_getdabflow_app__w9s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s.json` on `10.0.2.60:5555`

- Start: `2026-05-06T06:51:32.241728+00:00`
- End: `2026-05-06T06:53:10.608433+00:00`
- Status: `ok`
- Note: completed
- WebSocket logs:
  - `[OBS-close_chrome__open_getdabflow_app__w9s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s-10.0.2.60_5555] Starting on 1 phone(s)`
  - `[OBS-close_chrome__open_getdabflow_app__w9s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s-10.0.2.60_5555] Running [1] on GC3VE (29 steps)`
  - `[OBS-close_chrome__open_getdabflow_app__w9s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s-10.0.2.60_5555] Resetting identity on GC3VE…`
  - `[OBS-close_chrome__open_getdabflow_app__w9s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s-10.0.2.60_5555] GC3VE identity reset ✓`
  - `[OBS-close_chrome__open_getdabflow_app__w9s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s-10.0.2.60_5555] Done ✓`

