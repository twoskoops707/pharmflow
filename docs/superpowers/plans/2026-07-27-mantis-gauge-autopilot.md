# Mantis Gauge Autopilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep dash gauges on Mantis truth (wait-for-truth on reload/ntfy) and autopilot-steer the farm toward sweet-spot green within uniqueness rails.

**Architecture:** Shared Python modules for gauge scoring + steering; a singleton `mantis_autopilot.py` worker (timer + event); `farm_operator_dash` blocks on Mantis fetch for Reload/ntfy; writes `mantis_today_state.json` / overrides / `autopilot_*.json(l)`.

**Tech Stack:** Python 3.14, Flask operator dash (`scripts/farm_operator_dash.py`), unittest, existing `automation/mantis_farm_math.py`, farm overrides at `C:\PharmFlow\logs\`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-27-mantis-gauge-autopilot-design.md`
- Creds only from `C:\Users\jsmil\PharmFlow\logs\MANTIS.json` (never commit / never log password)
- Hard rails: unique-seq, draw-without-replacement, isolation, Tor unique exit, clicks hard cap 40/day
- Dry-run: `PHARMFLOW_AUTOPILOT_DRY_RUN=1` computes/logs without applying overrides or restarts
- No auto-ntfy reply bots; check-in may include Mantis snapshot text only
- Prefer small focused modules under `automation/`; do not paste secrets into tests

## File map

| File | Responsibility |
|------|----------------|
| `automation/mantis_gauge_score.py` | Shared bands + conjunction scoring (dash + autopilot) |
| `automation/mantis_steering.py` | Snapshot → override deltas |
| `automation/mantis_fetch.py` | Load creds + fetch today’s Mantis metrics |
| `automation/mantis_autopilot_apply.py` | Write overrides, action log, rate-limited restart hook |
| `scripts/mantis_autopilot.py` | Singleton loop (2–3h + yellow/red) |
| `scripts/farm_operator_dash.py` | Wait-for-truth refresh API + UI strip |
| `scripts/ensure_farm_24x7.py` | Ensure autopilot singleton |
| `scripts/clear_dead_farm_procs.py` / `C:\PharmFlow\logs\process_janitor.py` | Keep/dedupe autopilot |
| `tests/test_mantis_gauge_score.py` | Score unit tests |
| `tests/test_mantis_steering.py` | Steering unit tests |
| `tests/test_mantis_fetch_creds.py` | Cred parse tests (no live login) |

---

### Task 1: Shared gauge score module

**Files:**
- Create: `automation/mantis_gauge_score.py`
- Test: `tests/test_mantis_gauge_score.py`

**Interfaces:**
- Produces: `score_levers(impressions, clicks, ecpm, evcpm, farm_visits=0) -> dict` with keys `conjunction` (0..1), `tone` (`green`|`yellow`|`red`), `levers` map of name → `{value, kind: in|near|out, score}`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mantis_gauge_score.py
import unittest
from automation.mantis_gauge_score import score_levers

class TestMantisGaugeScore(unittest.TestCase):
    def test_strong_day_is_green(self):
        r = score_levers(
            impressions=16000, clicks=28, ecpm=0.75, evcpm=2.1, farm_visits=600
        )
        self.assertGreaterEqual(r["conjunction"], 0.72)
        self.assertEqual(r["tone"], "green")
        self.assertEqual(r["levers"]["evcpm"]["kind"], "in")

    def test_low_evcpm_pulls_yellow_or_red(self):
        r = score_levers(
            impressions=16000, clicks=28, ecpm=0.15, evcpm=0.5, farm_visits=600
        )
        self.assertIn(r["tone"], ("yellow", "red"))
        self.assertEqual(r["levers"]["evcpm"]["kind"], "out")

    def test_click_spam_out(self):
        r = score_levers(
            impressions=12000, clicks=55, ecpm=0.2, evcpm=2.0, farm_visits=500
        )
        self.assertEqual(r["levers"]["clicks"]["kind"], "out")

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -m unittest tests.test_mantis_gauge_score -v`  
Expected: FAIL (`ModuleNotFoundError` or import error)

- [ ] **Step 3: Write minimal implementation**

Implement `automation/mantis_gauge_score.py` with bands from the spec:
- Impr sweet 15k–18k (scale 0–20k)
- Clicks sweet 20–40 (hard out >40)
- eCPM green ≥0.15
- evCPM green ≥2.0 (yellow 1–2, out &lt;1)
- Visits sweet 560–660
- Conjunction weights: impr 0.28, clicks 0.18, ecpm 0.22, evcpm 0.32
- Tone: ≥0.72 green, ≥0.45 yellow, else red

- [ ] **Step 4: Run tests — expect PASS**

Run: `py -m unittest tests.test_mantis_gauge_score -v`

- [ ] **Step 5: Commit**

```bash
git add automation/mantis_gauge_score.py tests/test_mantis_gauge_score.py
git commit -m "feat: shared Mantis gauge sweet-spot scoring"
```

---

### Task 2: Steering module (snapshot → override deltas)

**Files:**
- Create: `automation/mantis_steering.py`
- Test: `tests/test_mantis_steering.py`

**Interfaces:**
- Consumes: `score_levers(...)` result
- Produces: `plan_steering(score: dict, *, farm_ads_used: int, path3_count: int, current_overrides: dict[str,str], dry_run: bool=False) -> dict` with `actions: list[dict]`, `overrides_patch: dict[str,str]`, `restart_farm: bool`, `reason: str`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from automation.mantis_gauge_score import score_levers
from automation.mantis_steering import plan_steering

class TestMantisSteering(unittest.TestCase):
    def test_clicks_at_hard_cap_disables_ads(self):
        score = score_levers(17000, 42, 0.2, 2.0, 600)
        plan = plan_steering(
            score,
            farm_ads_used=10,
            path3_count=10,
            current_overrides={"PHARMFLOW_FARM_ALLOW_ADS": "1", "PHARMFLOW_FARM_PATH3_DAILY_CAP": "16"},
        )
        self.assertEqual(plan["overrides_patch"].get("PHARMFLOW_FARM_ALLOW_ADS"), "0")
        self.assertTrue(any(a.get("type") == "browse_only" for a in plan["actions"]))

    def test_low_evcpm_raises_dwell_waits(self):
        score = score_levers(16000, 25, 0.15, 0.8, 580)
        plan = plan_steering(
            score,
            farm_ads_used=8,
            path3_count=8,
            current_overrides={"PHARMFLOW_DABFLOW_LOAD_WAIT": "2.0", "PHARMFLOW_AGE_GATE_WAIT": "2.0"},
        )
        self.assertGreaterEqual(float(plan["overrides_patch"]["PHARMFLOW_DABFLOW_LOAD_WAIT"]), 3.5)
        self.assertTrue(any(a.get("type") == "raise_dwell" for a in plan["actions"]))

    def test_never_raises_click_cap_above_40(self):
        score = score_levers(9000, 10, 0.15, 2.0, 400)
        plan = plan_steering(
            score,
            farm_ads_used=5,
            path3_count=5,
            current_overrides={"PHARMFLOW_FARM_PATH3_DAILY_CAP": "16"},
        )
        cap = int(plan["overrides_patch"].get("PHARMFLOW_FARM_PATH3_DAILY_CAP", "16"))
        self.assertLessEqual(cap, 40)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run — expect FAIL**

Run: `py -m unittest tests.test_mantis_steering -v`

- [ ] **Step 3: Implement `plan_steering`**

Rules (from spec):
- clicks ≥40 → `ALLOW_ADS=0`, cap ≤ used
- clicks ≥35 → tighten PATH3 cap toward used+small remainder
- evCPM out → set `PHARMFLOW_DABFLOW_LOAD_WAIT` ≥3.5, `PHARMFLOW_HUMAN_VARIATION=1`
- impr low + visits low → do not bump ads; leave visit caps alone or note `prefer_multitab` action (farm already biases p1c/d)
- Never set PATH3 cap &gt; 40
- Never clear uniqueness-related env keys

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add automation/mantis_steering.py tests/test_mantis_steering.py
git commit -m "feat: Mantis autopilot steering plans from gauge scores"
```

---

### Task 3: Creds loader + fetch interface (no live login in CI)

**Files:**
- Create: `automation/mantis_fetch.py`
- Test: `tests/test_mantis_fetch_creds.py`

**Interfaces:**
- Produces:
  - `load_mantis_credentials(path: Path | None = None) -> dict` with `url`, `user`, `password` (parse `WEB:` / `u:` / `p:` lines or JSON)
  - `fetch_mantis_today(*, creds: dict | None = None, timeout_s: float = 60) -> dict` returning `{ok, impressions, clicks, payout_usd, ecpm, evcpm, error, fetched_at}`
  - For first ship: implement real fetch behind `fetch_mantis_today`; if network/login fails, return `ok=False` without raising
  - Optional env `PHARMFLOW_MANTIS_FETCH_STUB=1` returns fixture numbers for local UI testing

- [ ] **Step 1: Write cred parse test**

```python
import tempfile, unittest
from pathlib import Path
from automation.mantis_fetch import load_mantis_credentials

class TestMantisCreds(unittest.TestCase):
    def test_parse_line_format(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "MANTIS.json"
            p.write_text(
                "WEB: https://example.test\nu: user@x.com\np: secret\n",
                encoding="utf-8",
            )
            c = load_mantis_credentials(p)
            self.assertEqual(c["user"], "user@x.com")
            self.assertEqual(c["password"], "secret")
            self.assertIn("example.test", c["url"])

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement loader + fetch**

`load_mantis_credentials`:
- Default path `Path(r"C:\Users\jsmil\PharmFlow\logs\MANTIS.json")`
- Support line format and JSON `{"url","user","password"}`
- Never print password

`fetch_mantis_today`:
1. If stub env set → return stub ok payload
2. Else attempt login/report pull (requests or Playwright — pick whatever works against mantisadnetwork admin; isolate in `_fetch_live`)
3. Map to ints/floats; on any error return `{ok: False, error: str, ...keep zeros}`

- [ ] **Step 4: Run cred tests PASS** (do not run live login in CI)

- [ ] **Step 5: Commit**

```bash
git add automation/mantis_fetch.py tests/test_mantis_fetch_creds.py
git commit -m "feat: Mantis credential load and today-metrics fetch"
```

---

### Task 4: Apply layer (overrides + action log + restart hook)

**Files:**
- Create: `automation/mantis_autopilot_apply.py`
- Test: `tests/test_mantis_autopilot_apply.py`

**Interfaces:**
- Produces: `apply_steering_plan(plan: dict, *, log_dir: Path, dry_run: bool | None = None) -> dict`  
  Writes/merges `farm_runtime_overrides.json`, appends `autopilot_actions.jsonl`, updates `autopilot_state.json`  
  If `plan["restart_farm"]` and not dry-run: call internal `_restart_farm_rate_limited(log_dir)` (≤1 / 10 min) by killing `run_farm_354.py` only when cycles/ensure will respawn — or set a flag file `autopilot_restart_farm.flag` that ensure/cycles honor

- [ ] **Step 1: Failing test with temp log dir**

```python
import json, tempfile, unittest
from pathlib import Path
from automation.mantis_autopilot_apply import apply_steering_plan

class TestApply(unittest.TestCase):
    def test_dry_run_does_not_write_overrides(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td)
            (log / "farm_runtime_overrides.json").write_text("{}", encoding="utf-8")
            plan = {
                "actions": [{"type": "browse_only"}],
                "overrides_patch": {"PHARMFLOW_FARM_ALLOW_ADS": "0"},
                "restart_farm": False,
                "reason": "test",
            }
            out = apply_steering_plan(plan, log_dir=log, dry_run=True)
            self.assertTrue(out["dry_run"])
            self.assertEqual(json.loads((log / "farm_runtime_overrides.json").read_text()), {})
            self.assertTrue((log / "autopilot_actions.jsonl").is_file())

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2–4: Implement + PASS**

Merge patch into overrides with `updated` ISO timestamp; always append JSONL action even on dry-run (mark `"dry_run": true`).

- [ ] **Step 5: Commit**

```bash
git add automation/mantis_autopilot_apply.py tests/test_mantis_autopilot_apply.py
git commit -m "feat: apply autopilot steering to farm overrides"
```

---

### Task 5: Autopilot worker script

**Files:**
- Create: `scripts/mantis_autopilot.py`

**Interfaces:**
- Loop: sleep until next due (randomize 120–180 min) OR wake file `C:\PharmFlow\logs\autopilot_wake.flag`
- Each cycle: `fetch_mantis_today` → `save` into `mantis_today_state.json` (reuse dash helper or duplicate small writer) → load farm budget/path3 → `score_levers` → if tone yellow/red or timer: `plan_steering` → `apply_steering_plan`
- Honor `PHARMFLOW_AUTOPILOT_DRY_RUN`
- Heartbeat: `C:\PharmFlow\logs\mantis_autopilot_heartbeat.txt`

- [ ] **Step 1: Implement script with `--once` for manual run**

```bash
py -u scripts/mantis_autopilot.py --once
```

Expected: prints ok/fail JSON summary; updates state files under `C:\PharmFlow\logs` (or dry-run)

- [ ] **Step 2: Manual smoke (operator machine)**

With network: `--once` should populate `mantis_today_state.json` without logging password.

- [ ] **Step 3: Commit**

```bash
git add scripts/mantis_autopilot.py
git commit -m "feat: mantis autopilot worker loop"
```

---

### Task 6: Dash wait-for-truth refresh + status strip

**Files:**
- Modify: `scripts/farm_operator_dash.py`

**Interfaces:**
- Add `POST /api/refresh_truth` → runs `fetch_mantis_today`, `save_mantis_today`, returns full `status_payload()` plus `truth: {ok, error, fetched_at}`
- Change JS `refresh()` used by ↻ / Refresh: show toast/overlay “Pulling Mantis…”, `await post('/api/refresh_truth')`, then render (do not paint gauges from stale `/api/status` first)
- `POST /api/checkin_ntfy`: call same truth fetch before `gather_checkin` / publish; include Mantis impr/clicks/eCPM/evCPM + conjunction in check-in text
- Status strip under gauges: Autopilot last/next/Mantis OK|fail from `autopilot_state.json`

- [ ] **Step 1: Add API route**

```python
@app.post("/api/refresh_truth")
def api_refresh_truth():
    from automation.mantis_fetch import fetch_mantis_today
    snap = fetch_mantis_today()
    if snap.get("ok"):
        save_mantis_today({k: snap[k] for k in ("impressions","clicks","payout_usd","ecpm","evcpm") if k in snap})
    payload = status_payload()
    payload["truth"] = {
        "ok": bool(snap.get("ok")),
        "error": snap.get("error"),
        "fetched_at": snap.get("fetched_at"),
    }
    return jsonify(payload)
```

- [ ] **Step 2: Wire JS wait-for-truth**

```javascript
async function refreshTruth(){
  toast('Pulling Mantis…');
  const r = await fetch('/api/refresh_truth', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
  const j = await r.json();
  if(!j.truth || !j.truth.ok) toast('Mantis fail: '+(j.truth && j.truth.error || 'unknown'));
  else toast('Mantis OK');
  STATE = j;
  // existing renderStatus(STATE) path
  renderStatus(STATE);
}
document.getElementById('btnRefreshTop').onclick = () => refreshTruth();
document.getElementById('btnRefresh').onclick = () => refreshTruth();
```

- [ ] **Step 3: Manual verify**

Open `http://127.0.0.1:8091` → ↻ → UI blocks/toasts until truth → gauges match Mantis.

- [ ] **Step 4: Commit**

```bash
git add scripts/farm_operator_dash.py
git commit -m "feat: dash wait-for-truth Mantis refresh on reload and check-in"
```

---

### Task 7: Keep autopilot alive (ensure + janitor)

**Files:**
- Modify: `scripts/ensure_farm_24x7.py`
- Modify: `scripts/clear_dead_farm_procs.py`
- Modify: `C:\PharmFlow\logs\process_janitor.py` (runtime copy; also keep PharmFlow script in sync if one exists)

- [ ] **Step 1: ensure starts singleton**

In `tick()` / ensure loop, after dash:

```python
if _count("mantis_autopilot.py") < 1:
    _start_hidden("scripts/mantis_autopilot.py")
    actions.append("mantis_autopilot")
```

- [ ] **Step 2: clear_dead / janitor**

Add `mantis_autopilot.py` to singleton keep list; never always-kill it.

- [ ] **Step 3: Restart ensure or run once; confirm process**

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'mantis_autopilot' }
```

Expected: one process.

- [ ] **Step 4: Commit**

```bash
git add scripts/ensure_farm_24x7.py scripts/clear_dead_farm_procs.py
git commit -m "feat: ensure and dedupe mantis autopilot keeper"
```

(If janitor lives only under `C:\PharmFlow\logs`, patch there and note in commit body; prefer also adding `scripts/process_janitor.py` in-repo if missing.)

---

### Task 8: Optional dash JS score alignment

**Files:**
- Modify: `scripts/farm_operator_dash.py` HTML/JS **or** expose `score` from API

Prefer: `status_payload()` includes `gauge_score: score_levers(...)` so JS can render conjunction from server (single source of truth). Keep SVG needles; replace local weight math with API fields when present.

- [ ] **Step 1: Add `gauge_score` to `status_payload` / refresh_truth**
- [ ] **Step 2: JS uses `s.gauge_score` when present for conj score/bits**
- [ ] **Step 3: Commit**

```bash
git add scripts/farm_operator_dash.py
git commit -m "feat: serve shared gauge_score on dash status API"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Shared gauge bands / conjunction | 1, 8 |
| Steering map + hard rails | 2, 4 |
| Mantis fetch from `MANTIS.json` | 3 |
| Apply overrides + action log | 4 |
| 2–3h worker + yellow/red | 5 |
| Wait-for-truth reload | 6 |
| Wait-for-truth ntfy check-in | 6 |
| Autopilot status strip | 6 |
| Dry-run | 4, 5 |
| ensure/janitor singleton | 7 |

## Placeholder / consistency self-review

- No TBD steps; fetch live implementation is explicit in Task 3 with stub escape hatch.
- Function names consistent: `score_levers`, `plan_steering`, `apply_steering_plan`, `fetch_mantis_today`, `load_mantis_credentials`.
- Log dir default `C:\PharmFlow\logs` everywhere.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-27-mantis-gauge-autopilot.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — run tasks in this session with executing-plans checkpoints  

Which approach?
