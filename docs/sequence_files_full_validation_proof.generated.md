# Sequence files — full validation proof (generated)

**Repository:** `C:\Users\jsmil\source\repos\pharmflow`  
**Generated:** 2026-05-06 (Pacific time per captured logs)  
**Git (validation bundle on `main`):** `3d48c658b7d4fd4f1eba5bc7b8b3c0b52f921fcb` — adds recursive `load_sequence_steps_ui` coverage in `verify_sequences.py` and commits UTF-8 `.full.log` captures alongside this proof file.

This document records automated validation runs requested for **every** sequence JSON under `automation/recordings/sequences/` (recursive), plus loader smokes. **No hardware / emulator execution** was performed — results are **static validation only** (JSON parse, UI loader path, schema semantics).

---

## 1. Enumeration — sequence JSON count (recursive)

**Command:**

```powershell
(Get-ChildItem -Path 'C:\Users\jsmil\source\repos\pharmflow\automation\recordings\sequences' -Recurse -File -Filter '*.json').Count
```

**Result:** `1297` sequence JSON files.

**Note:** There are **2** subdirectory nodes under `sequences/` (nested grid/layout folders). All `*.json` are included in the recursive count.

---

## 2. Full validator — `py -3 automation/verify_sequences.py`

**Command:**

```bat
cd /d C:\Users\jsmil\source\repos\pharmflow
py -3 automation\verify_sequences.py
```

**Captured stdout/stderr (complete):**  
`docs/sequence_files_full_validation_verify_sequences.full.log`  
(Captured via `subprocess.run(..., capture_output=True)` — UTF-8; timestamp on line 1.)

**Summary from capture:**

| Metric | Value |
|--------|--------|
| Exit code | **0** |
| JSON files validated under `automation/recordings/` (recursive `*.json`) | **1299** |
| Step collections checked (sequences recursive + `groups_config.json` phones) | **1300** |
| STDERR | empty |

**UI loader:** As of the companion commit, **`verify_sequences.py` loads every sequence file using `load_sequence_steps_ui`** from `automation/sequence_normalize.py` (wizard/dashboard-compatible path) while iterating **`sequences/**/*.json` recursively**. No separate one-shot script is required for batch UI-load rejection testing; impracticality at 1000+ files does **not** apply — the batch completes in a few seconds.

**Age-verification:** The tool prints **WARN** lines for sequences missing age-gate markers; these are **anomalies**, not validator failures (exit code remains **0**).

---

## 3. UI loader smoke — `py -3 automation/smoke_home_combo_ui_loader.py`

**Command:**

```bat
py -3 automation\smoke_home_combo_ui_loader.py
```

**Captured stdout/stderr (complete):**  
`docs/sequence_files_full_validation_smoke_home_combo.full.log`

**Summary:**

| Metric | Value |
|--------|--------|
| Exit code | **0** |
| Pattern | `sequence_home_combo_v2_*.json` (repo root of `sequences/` only) |
| Files loaded | **1152** (per smoke output) |
| STDERR | empty |

This smoke exercises **`load_sequence_steps_ui`** plus coordinate baseline checks for the home-combo matrix subset.

---

## 4. Additional loader-related smoke — template consistency

**Command:**

```bat
py -3 automation\smoke_sequence_template_consistency.py
```

**Captured stdout/stderr (complete):**  
`docs/sequence_files_full_validation_smoke_sequence_template.full.log`

**Summary:** Exit code **0**. Validates top-level `sequences/*.json` sample set (**1288** files per script’s non-recursive glob) + template propagation logic.

---

## 5. Automation import smoke (sanity)

**Command:**

```bat
py -3 automation\smoke_imports.py
```

**Timestamp:** 2026-05-06 21:51:27 -07:00  

**Result:** Exit code **0** — `smoke_imports: OK ...`

---

## 6. Overall pass/fail

| Stage | Pass/Fail |
|-------|-----------|
| `verify_sequences.py` | **PASS** (exit 0) |
| `smoke_home_combo_ui_loader.py` | **PASS** (exit 0) |
| `smoke_sequence_template_consistency.py` | **PASS** (exit 0) |
| `smoke_imports.py` | **PASS** (exit 0) |

**Hardware execution:** **Skipped** — proof covers **static** validation and scripted loaders only.

---

## 7. Code changes proving UI-loader coverage

- **`automation/verify_sequences.py`:** Iterates `recordings/sequences/**/*.json` and uses **`load_sequence_steps_ui`** for each file before semantic checks.
