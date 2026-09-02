# Sequence Coverage Audit (Generated)

Audit scope: `automation/recordings/sequences/*.json` against current home-screen combo logic and documented mappings.

## Snapshot

- Total sequence JSON files scanned: `242`
- Home-combo files scanned (`sequence_home_combo_*.json`): `116`
- V2 combo files (`sequence_home_combo_v2_*`): `108`
- Legacy home-combo alias files: `8`

## 1) Missing combinations

Canonical V2 grid from combo logic is:

- `entry`: `direct` | `google_home` (2)
- `footer`: `left` | `center` | `right` (3)
- `hero`: `off` | `on` (2)
- `bottom`: `center` | `right` | `left` (3)
- `timer`: `none` | `single96` | `stacked` (3)

Expected combinations: `2 * 3 * 2 * 3 * 3 = 108`

Result:

- Expected V2 files: `108`
- Present V2 files: `108`
- Missing combinations: **none**
- Unexpected extra V2 files: **none**

## 2) Duplicates

- Duplicate payload groups among V2 files: **0**
- Duplicate payload groups among all home-combo files (`v2 + legacy`): **0**

No exact duplicate JSON content was found under distinct filenames in the audited home-combo set.

## 3) Broken mappings

### A. Generator/documented timer policy drift vs actual V2 files

The canonical generator/doc model says:

- `single96` => includes a `wait 96`
- `stacked` => includes `wait 96`, `wait 102`, `wait 88`, plus cushion

Observed in current V2 JSON:

- `single96` files use `wait 100` (not `96`)
- `stacked` files use `wait 100 + 102 + 88` (not `96 + 102 + 88`)

Impact:

- Files affected: `72` (`36` single96 + `36` stacked)
- Logical mismatch class: filename token/documentation says `96`, content executes `100`

Actionable gap:

1. Pick canonical truth: keep `100` behavior or revert to `96`.
2. If keeping `100`, rename token/option (`single100`) and update:
   - `automation/recordings/sequences/generate_home_combo_sequences.py`
   - `docs/HOME_COMBO_MATRIX.md`
   - any UI/config references that expose `single96` / `stacked` semantics
3. If reverting to `96`, regenerate all V2 combo files from generator.

### B. Legacy alias mirror contract drift

`docs/SEQUENCE_CATALOG.md` says legacy alias files are byte-identical mirrors of canonical files. Current status:

- `close_chrome__open_google_com__w4s__tap_google_search_box__type_query_getdabflow__enter__w6s__h2a611a__n1.json` -> `google_com__typequery_enter__tap_serp__getdabflow_funnel__cleanup.json`: `OK` (identical)
- `close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__h25538b.json` -> `close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__hdd71d4.json`: **DRIFTED**
  - first diff: alias has `wait 305`, canonical has `wait 96`
- `open_getdabflow__combo_landing_short__rotate_wait_fullreset.json` -> `open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su.json`: **DRIFTED**
  - first diff starts at first step (`open_url` object differs; post-wait precision/value mismatch)
- `close_chrome__open_getdabflow_app__w9s__tap_consent_strip__tap_age_modal__tap_landing_hero__hfee6b2.json` -> `open_getdabflow__web_ads_left_hero_footer__back_cleanup.json`: **DRIFTED**
  - first diff at early wait (`9.3` vs `5`)
- `close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__hf26804.json` -> `open_getdabflow__web_ads_center_footer__back_cleanup.json`: **DRIFTED**
  - first diff at early wait (`9.8` vs `5`)
- `close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__h593e70.json` -> `open_getdabflow__web_ads_right_footer__back_cleanup.json`: **DRIFTED**
  - first diff at early wait (`10.3` vs `5`)

Actionable gap:

1. Decide whether legacy aliases are:
   - true mirrors (then re-copy from canonical now), or
   - independently tuned variants (then stop calling them mirrors in docs).
2. Update `docs/SEQUENCE_CATALOG.md` to reflect the chosen policy.
3. Add CI validation for alias mapping consistency to avoid future silent drift.

### C. Catalog mapping omission

In the home-combo alias matrix section of `docs/SEQUENCE_CATALOG.md`, `close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__h593e70.json` is referenced elsewhere but missing from the alias table rows shown in the matrix.

Actionable gap:

- Add the missing right-footer alias row to keep mapping table complete and prevent operator confusion.

## 4) Stale files

Legacy home-combo files not part of canonical legacy alias set or V2 grid:

- `close_chrome__open_getdabflow_app__w9s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s.json`
- `close_chrome__open_getdabflow_app__w8s__tap_bottom_center__tap_bottom_left__tap_R_lbot__w2s.json`

These look stale relative to current V2 naming/model and are undocumented in the current home-combo matrices.

Actionable gap:

1. If still in use, document them explicitly (purpose, owner, and where referenced).
2. If not in use, archive/remove and scrub references.
3. Add a lint/check that flags undocumented `sequence_home_combo_*` files.

## 5) Recommended follow-up checklist

- [ ] Resolve `96` vs `100` timer policy mismatch (code vs filenames/docs).
- [ ] Regenerate V2 combos from a single source of truth after policy decision.
- [ ] Reconcile legacy alias behavior (mirror vs tuned variant).
- [ ] Fix alias matrix completeness in `docs/SEQUENCE_CATALOG.md`.
- [ ] Triage/remove stale `webapp_tabs` home-combo files.
- [ ] Add automated audit script in repo to enforce combo coverage + mapping integrity.
