# Debug / test sweep (generated)

**Repo:** `C:\Users\jsmil\source\repos\cpharm`  
**Date:** 2026-05-06  
**Python:** `py -3` (Windows)

## Environment notes

- **`rg` (ripgrep)** was not available on `PATH` in the sweep shell (`rg : The term 'rg' was not recognized`). Equivalent checks used workspace search / ripgrep semantics via Cursor `Grep` against the repo tree.
- **`unittest discover -s tests`** failed because there is **no `tests/` directory** in this repo (ImportError: start directory not importable). No top-level `tests/` package exists.

---

## 1) Static

### `py -3 -m py_compile …`

**Command:**

```text
py -3 -m py_compile wizard/setup_wizard.py wizard/cpharm_desktop.py wizard/wizard_theme.py gui/cpharm_gui.py automation/dashboard.py
```

**Result:** **PASS** — exit code **0**

---

### `rg -i webpe` (entire repo)

**Substitute:** workspace search, pattern `webpe`, case-insensitive.

**Result:** **NON-ZERO matches** (not empty).

| Location | Notes |
|----------|--------|
| `wizard/setup_wizard.py` | `WebpePage` class and related `webpe_*` strings remain in source for legacy/import paths; **not** included in `CPharmWizard.PAGES` — operators do not see a WebPE tab in the shipping wizard. |

**Exception / interpretation:** A text search for `webpe` is **expected to be non-zero** until dead code is deleted. **Product UX:** use the **Generator** tab (**Sequence builder**); WebPE is not part of the navigable wizard flow.

---

### `rg -i "WebpePage|WEBPE" wizard/`

**Substitute:** workspace search under `wizard/`, patterns `WebpePage` / `WEBPE`.

**Result:** **Matches in `wizard/setup_wizard.py`** (same `WebpePage` / WebPE strings as above). **Not zero.**

---

## 2) Smoke / tests

| Command | Exit | Summary |
|---------|------|---------|
| `py -3 wizard/smoke_frozen_imports.py` | **0** | `smoke_frozen_imports: OK` |
| `py -3 automation/smoke_imports.py` | **0** | `smoke_imports: OK` … |
| `py -3 automation/verify_sequences.py` | **0** | `OK: validated 244 JSON file(s); checked 245 step collections` |
| `py -3 automation/smoke_sequence_template_consistency.py` | **0** | `ok: validated 242 sequence files + template propagation` |
| `py -3 automation/smoke_wizard_reliability.py` | **0** | `smoke_wizard_reliability: OK` … (extra sanity, not in minimal list) |

### Unittest

| Command | Exit | Summary |
|---------|------|---------|
| `py -3 -m unittest discover -s wizard -p "test*.py" -v` | **0** | Ran **6** tests in `test_sequence_generator_edge_cases.py` — **OK** |
| `py -3 -m unittest discover -s tests -p "test*.py" -v` | **1** | **ImportError:** start directory `tests` not importable — **no `tests/` tree** |

---

## 3) Runtime probes

| Command | Exit | Summary |
|---------|------|---------|
| `py -3 -c "import wizard.setup_wizard"` | **0** | `import wizard.setup_wizard OK` |

---

## 4) Fix blockers

**No code patches were required** for this sweep: all requested smoke scripts and `py_compile` passed; `import wizard.setup_wizard` succeeded.

**Non-blockers recorded:**

- Missing `rg` on PATH (used equivalent search).
- `tests/` unittest discovery failure is **structural** (directory absent), not a failing test suite.

---

## 5) Pass/fail summary

| Area | Status |
|------|--------|
| `py_compile` (listed modules) | **PASS** |
| WebPE string grep = 0 | **N/A for UX** — source may still reference `WebpePage` for removal later; wizard tabs do not expose it |
| Wizard smoke imports | **PASS** |
| Automation smoke / verify sequences | **PASS** |
| Sequence template consistency | **PASS** |
| Unittest (`wizard/`) | **PASS** |
| Unittest (`tests/`) | **N/A** — no `tests/` dir |
| Import `wizard.setup_wizard` | **PASS** |

---

## 6) Remaining risks

1. **WebPE dead code:** Optional follow-up to delete `WebpePage` and `webpe_*` strings from `setup_wizard.py` for a clean repo search; this does not change the operator-facing wizard, which already omits that page from `PAGES`.
2. **CI vs local:** This sweep did not run GitHub Actions; local smoke passes only guarantee what these scripts cover.
3. **GUI paths:** No full Tk/GUI event-loop or device automation run was executed beyond import/smoke scripts.

---

## Command exit codes (quick reference)

| Step | Exit |
|------|------|
| py_compile | 0 |
| smoke_frozen_imports | 0 |
| smoke_imports | 0 |
| verify_sequences | 0 |
| smoke_sequence_template_consistency | 0 |
| smoke_wizard_reliability | 0 |
| unittest wizard | 0 |
| unittest tests | 1 (no directory) |
| import wizard.setup_wizard | 0 |
