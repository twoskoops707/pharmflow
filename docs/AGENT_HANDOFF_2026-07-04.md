> **Superseded:** the product is a single `PharmFlow.exe` in `C:\PharmFlow\` (`--watchdog`, `--agent`, phone setup in-process). Data still lives under `C:\PharmFlow\`. Ignore EXE names below.

# PharmFlow agent handoff — 2026-07-04

Notes for the next human operator or cloud agent. Supersedes scattered chat context from the Jul 2026 MuMu / fingerprint / dual-exe workstream.

**Latest verified release at time of writing:** [wizard-393](https://github.com/twoskoops707/pharmflow/releases/tag/wizard-393) (CI build after commit `b4a4518`).

---

## What shipped in this conversation

| Build | Topic |
|-------|--------|
| 386–388 | `PharmFlow.exe` (WebView2 UI), wizard de-overlap, preflight checklist |
| 390 | `mumu_fingerprint` bundled in `PharmFlow.exe` (fix `No module named 'mumu_fingerprint'`) |
| 391 | Central `wizard_paths.automation_on_sys_path()` — frozen exe path fixes |
| 392 | Setup GO: browser detect, 900×1600 baseline, warm launch |
| 393 | Auto-download `ChromePublic.apk`, strip `com.android.browser` from 128 sequences, `org.chromium.chrome` support |

---

## Two-exe architecture (do not merge back into one without user approval)

| Binary | Owns |
|--------|------|
| **PharmFlow.exe** | Checklist, adb download (~6 MB), MuMu VM fingerprint (`setting.json`), per-phone ADB flags, browser sideload, `groups_config.json` seed, `desktop_prefs.json` (`mumu_setup_complete`), launch `PharmFlow.exe` |
| **PharmFlow.exe** | Home shell + full wizard: Java/Python/Tor install, clone repo tree, boot/connect MuMu, Tor runtime, run groups, optional re-apply fingerprint |

**Exe-only folder (`C:\PharmFlow\`):** contains both exes only — **no** `tools/`, **no** full `automation/` until wizard **Install** completes. All farm setup logic is in **PharmFlow.exe** (`wizard/mumu_farm_ops.py`).

---

## Consolidated farm module (Jul 2026)

All former `tools/*.py` logic now lives in **`wizard/mumu_farm_ops.py`**:

| Operation | Operator path |
|-----------|----------------|
| Full farm setup | **PharmFlow.exe → GO** |
| Fix Pad→Phone VM profile | GO (auto) or checklist **Fix Pad→Phone** |
| Download Chromium APK | GO (auto) or checklist **Get Chromium** |
| Fingerprint audit/apply | GO, or PharmFlow **Re-apply hide emulator** |
| Write groups / prefs | GO |

`tools/*.py` are thin dev CLIs only — not shipped in Releases.

---

## Operator path (Windows + MuMu)

1. Download **both** exes from [GitHub Releases](https://github.com/twoskoops707/pharmflow/releases/latest) → same folder (e.g. `C:\PharmFlow\`).
2. MuMu Multi-instance: **Phone**, **900×1600**, portrait; start phones; USB debugging ON.
3. **PharmFlow.exe** → complete checklist (Step 7 = browser) → **GO**.
4. If prompted: **STOP then START** each MuMu phone (VM identity patched).
5. **PharmFlow.exe** → Step 2 Setup Wizard → **Install** (first time) → **Boot** → **Go** (Tor F → run groups).

---

## Fingerprint — what actually works (no magic APK)

**There is no PharmFlow-shipped “anti-detect” APK.** Hiding emulator signals uses:

1. **MuMu `vms/*/setting.json`** — retail brand/model/IMEI/MAC (`mumu_fingerprint.apply_mumu_vm_fingerprints`). Requires **cold boot** per phone for `getprop` to update.
2. **ADB flag files** on each phone:
   - `/data/local/tmp/chrome-command-line`
   - `/data/local/tmp/webview-command-line`  
   Fake mobile UA + `--disable-blink-features=AutomationControlled`. Applies on **next browser launch**.
3. **Re-apply before every `open_url`** — `dashboard.run_sequence_step` → `mumu_fingerprint.ensure_fingerprint_before_browse()`.

**Disable:** `PHARMFLOW_SKIP_FINGERPRINT=1`.

**Browser JS injection in sequences:** Not implemented and **not sufficient** — cannot fix `ro.kernel.qemu`, tablet layout, or Tor/proxy. Do not promise a “run script in browser first” fix without verifying getdabflow’s checks.

---

## Browser policy (MuMu farm)

**Preferred:** `com.mumudroid.browser` (MuMu Browser) — honors WebView flags + Android `global http_proxy` (Tor).

**Sideload fallback:** Official **ChromePublic.apk** from Google Chromium snapshots:
- URL: https://download-chromium.appspot.com/dl/Android?type=snapshots
- Installs as **`org.chromium.chrome`** (not `com.android.chrome`)
- Setup GO auto-downloads to `C:\PharmFlow\bundled\ChromePublic.apk` when no browser found (~230 MB once)
- Checklist button **Get Chromium** or GO auto-download (no separate script needed)

**Sequences:** Shipped JSON under `sequences/` does **not** pin browser package on `open_url` / `clear_cookies`. Runtime uses `browser_adb.packages_for_view_url_attempts()` and `browser_pkg_for_clear()`. As of build 393, **`com.android.browser` removed** from `close_app` steps (128 files).

**Do not** hardcode Chrome in new sequences. Use empty `package` on `close_app` / `clear_cookies` unless you must target one app.

---

## ADB / Tor / proxy (verified farm rules)

- Phone serials come from **`adb devices -l`** — dynamic; never hardcode `10.0.2.144:5555` in product code (OK as example in docs/tools).
- Tor slots follow **`desktop_prefs.json` `phone_serials` order**, not alphabetical IP sort.
- Default MuMu ARM: **`adb reverse`** + guest **`127.0.0.1:(8118+idx)`** — **not** `10.0.2.2` gateway (`PHARMFLOW_PROXY_LEGACY_GATEWAY=1` only for legacy).
- Android **`global http_proxy`** needs **HTTP** tunnel (Tor `HTTPTunnelPort`), not SOCKS-only.

---

## Key files

```
wizard/PharmFlow.spec              → PharmFlow.exe PyInstaller
wizard/PharmFlowMuMuSetup.spec     → setup exe PyInstaller
wizard/mumu_farm_ops.py       → all MuMu farm ops (setup + wizard; replaces tools/*.py)
wizard/mumu_setup_core.py       → setup GO backend
wizard/browser_setup.py         → browser download/sideload/baseline
wizard/preflight_core.py        → checklist Steps 1–7 + Fix/Get Chromium actions
automation/mumu_fingerprint.py  → VM + ADB fingerprint engine
automation/browser_adb.py       → runtime browser discovery order
automation/dashboard.py         → open_url fallbacks + fingerprint before browse
wizard/wizard_paths.py          → automation_on_sys_path(), install roots
tools/*.py                      → dev-only thin CLIs (call mumu_farm_ops; not in Releases)
automation/fix_sequences_strip_chrome.py → strip browser pinning in JSON
.github/workflows/build-wizard.yml → CI + GitHub Release on push to main
```

---

## CI / release checklist (mandatory before “done”)

1. `git status` — nothing critical uncommitted  
2. `git push` — branch on `origin`  
3. GitHub Actions **Build PharmFlow (.exe)** green on `main`  
4. New tag **`wizard-<run_number>`** on [Releases](https://github.com/twoskoops707/pharmflow/releases) with **both** `PharmFlow.exe` and `PharmFlow.exe`

Workflow triggers: **`on: push:`** to `main` only (no PR-triggered builds per repo policy).

---

## Common user mistakes (already seen)

| Symptom | Cause | Fix |
|---------|--------|-----|
| `can't open file ... setup_fresh_mumu_farm.py` | Exe-only `C:\PharmFlow\` has no repo | Use **PharmFlow.exe GO** — all logic is in the exe |
| `No module named 'mumu_fingerprint'` | Old `PharmFlow.exe` before build 390 | Download latest Release |
| Browser missing / wrong app | No Chrome on MuMu; old sequences pinned `com.android.browser` | Build 393 + GO; prefer MuMu Browser |
| getdabflow still blocks | VM not cold-booted after patch | Stop/start MuMu phones; GO again |
| Tor timeout in browser | Chrome used instead of MuMu Browser | Ensure MuMu Browser installed; check proxy |

---

## Tasks intentionally NOT done (need user PC)

- Live MuMu/ADB validation on operator’s Windows machine (cloud agent is Linux VM).
- Shipping Google Chrome APK in git (legal/size; use Chromium snapshot or user-supplied APK).
- Merging dual exe back into single binary (user explicitly wanted split).

---

## Suggested next work (if user returns)

1. Live fingerprint audit: **PharmFlow.exe → GO** or PharmFlow Boot/Launch → **Re-apply hide emulator**.
2. Regenerate `docs/SEQUENCE_CATALOG.md` / `SEQUENCE_GESTURE_MAP.md` if automation recordings tree changes (note at top of those files explains runtime browser resolution).
3. Optional: wizard Boot step call into `browser_setup.ensure_browser()` to avoid duplicating logic (setup exe already owns first-run).

---

## Verify-before-success rule

Never tell the user a build shipped without checking: clean git push, remote branch, and **GitHub Releases** asset list (not Actions artifacts as default download path).
