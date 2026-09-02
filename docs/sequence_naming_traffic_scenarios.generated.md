# Traffic scenario sequences (hand-authored)

This document lists JSON sequences under `automation/recordings/sequences/` that encode **intent-rich human-traffic flows** (named files, optional `label` / `meta` wrappers). Runtime loading accepts either a bare JSON array of steps or `{"label": "...", "meta": {...}, "steps": [...]}` — see `sequence_normalize.unwrap_sequence_document`.

## Files

### `close_chrome__open_getdabflow_app__w8s__tap_bottom_center__w2s__tap_C_lmid__w3s.json`

- **Intent:** Age verification → Quartz navigation → Wax-Propane timer region → **71 s** wait → small swipe (breaks back-to-back wait validation and mimics micro-movement) → **15 s** wait → Stats tab → several **slow** upward swipes (`ms` ~1880–2100) → Back → clear Chrome cookies → close Chrome → **rotate_identity → wait → full_reset** (new ID & IP path).
- **Customize:** Replace taps whose coordinates do not match your build (`label` in JSON has the full title). Prefer **Generator → Sequence builder → More options: layouts, browser recording, tap alignment → Record from desktop browser → Open** (optional `pywebview` / WebView2) or the **Small preview — record taps here** canvas at baseline **900×1600**, or edit `x`/`y` in the step list. Conservative `wait` values are intentional; shorten only after you measure render time on-device.
- **Human-like tuning:** Increase `jitter` / `pre_wait_ms` on taps, or enable **`CPHARM_HUMAN_VARIATION`** so `human_variation.effective_tap_jitter` and scaled waits apply at execution time (`automation/human_variation.py`).

### `close_chrome__open_getdabflow_app__w9s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w3s.json`

- **Intent:** Open flow through footer tabs and Stats-oriented scrolling → **middle-ad** tap → long dwell wait → **slow** scroll-to-bottom → Back → **Glass** tab (placeholder x/y on right footer) → pause → Back/cleanup path → clear cookies → close → **rotate_identity → wait → full_reset**.
- **Customize:** Middle-ad and Glass-tab taps are placeholders near common grid positions; calibrate per deployment. Reading-speed scroll uses **long swipe duration** (`ms` 2200–2400) rather than extra step types.

## Wizard tooling (Sequence builder on **Generator** tab)

Under **Category → Human-like**:

| Action | Effect |
|--------|--------|
| **Slow scroll up (~2.1s)** | Adds an upward `swipe` with ~2100 ms duration (baseline W×H from your preset). |
| **Micro-wait (human gap)** | Adds a short `wait` in **0.28–0.52 s**, aligned with `human_variation.STEP_GAP_*` defaults. |
| **Arm higher jitter (next tap)** | Raises jitter budget for the **next** tap appended via recorder, toolbox tap, or browser builder (capped at 120 px total jitter after normalization). |
| **Boost jitter (selected tap)** | Increments `jitter` on the **selected** tap step (+12 px per use). |

**Quick edit** keys now include `jitter`, `pre_wait_ms`, `retries`, and swipe endpoints.

## Verification

Run from repo root:

```text
py -3 automation/verify_sequences.py
py -3 automation/validate_sequence_schema.py --check
```
