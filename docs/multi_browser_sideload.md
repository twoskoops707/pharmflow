# Multi-browser sideload for CPharm EXE / farm

## FarmBrowser (primary — money / Path3)

| Package | Role |
|---------|------|
| `com.farmbrowser.stealth.debug` | **Path3 / Mantis clicks** — built-in proxy, identity rotation, JS control via ADB broadcast |
| `com.farmbrowser.stealth` | Release package name (same app) |

Source + APK build: **[github.com/twoskoops707/cpharm](https://github.com/twoskoops707/cpharm)** → `farmbrowser/`

Install on phones:

```powershell
py -3 scripts/remove_lawnchair_arm_farmbrowser.py
```

Sequences use `preferred_browser: com.farmbrowser.stealth.debug` and `browser_tag: farmbrowser`.
Bulk rewrite: `py -3 scripts/rewrite_sequences_farmbrowser.py`

SSOT browser allow-list: `automation/cpharm_farm_config.py` (`PATH3_BROWSERS=farmbrowser,chromium`).

---

## Why sideload legacy browsers (not Google Play)

Farm phones must stay **unique and isolated**. The Play Store requires a Google
account, syncs identity across devices, and phones home. **Do not sign into
Google Play on farm VMs.**

CPharm sideloads browsers with `adb install -r` from **public vendor mirrors**.
**No credentials, API keys, or Play Store tokens are required or stored.**

| Browser | Package | Used on | Public source |
|---------|---------|---------|---------------|
| **FarmBrowser** | `com.farmbrowser.stealth.debug` | **Path3 (ads)** + preferred money browser | Built in cpharm repo (`farmbrowser/`) |
| Chromium | `org.chromium.chrome` | Path1/2 fallback | download-chromium / Chromium snapshots |
| Firefox | `org.mozilla.firefox` | Path1/2 only | Mozilla FTP (`ftp.mozilla.org/pub/fenix/releases/`) |
| Brave | `com.brave.browser` | Path1/2 only | GitHub `brave/brave-browser` Releases |
| DuckDuckGo | `com.duckduckgo.mobile.android` | Path1/2 only | GitHub `duckduckgo/Android` Releases |

Path3 (ads / Mantis) uses **FarmBrowser first**, Chromium as CDP fallback per SSOT.

## Where APKs live

Default cache: `C:\CPharm\apks\`

| File | Package |
|------|---------|
| `ChromePublic-arm64.apk` | Chromium |
| `fenix-android-arm64.apk` | Firefox |
| `brave-android-arm64.apk` | Brave |
| `duckduckgo-android.apk` | DuckDuckGo |

Override with env `CPHARM_APK_CACHE`. Legacy setup still accepts
`C:\CPharm\bundled\ChromePublic.apk` for Chromium.

## Download + install (CLI)

From the repo (or any checkout that has `scripts/` + `automation/`):

```powershell
cd C:\Users\jsmil\FamFlow
$env:PYTHONPATH='C:\Users\jsmil\FamFlow'

# Download only (safe; no device changes)
py -3 scripts/sideload_farm_browsers.py --download-only

# Force re-download latest public builds, then install on all online phones
py -3 scripts/sideload_farm_browsers.py --force --install

# Print catalog
py -3 scripts/sideload_farm_browsers.py --print-catalog
```

## How CPharm.exe uses this

1. **First-run / Setup GO** (`wizard/mumu_setup_core.py`) calls
   `ensure_farm_browsers()` after Chromium — same catalog as the CLI.
2. **Runtime** (`automation/browser_farm.py` + `dabflow_sequence_gen.py`):
   - Path1/2 sequence stems include `_chromium` / `_firefox` / `_brave` / `_duckduckgo`
     before the `_complete` / `_halfway` suffix
   - JSON field `preferred_browser` selects the package
   - Isolation `pm clear`s that package before each run
   - Path3 stems (`*_ad`) force Chromium

Expected count: Path1/2 × 4 browsers + Path3 Chromium-only (see
`dabflow_mapper.combination_count()` → **8280**).

3. **Regenerate sequences** after pulling this logic:

```powershell
py -3 scripts/generate_dabflow_sequences.py `
  --base-dir C:\CPharm\automation\recordings\sequences\base
```

Or in the EXE: **Builder → Regenerate all sequences**.

Expected count: **8280** (Path1/2 × 4 browsers + Path3 Chromium-only).

## DuckDuckGo notes

- Package: `com.duckduckgo.mobile.android`
- VIEW activity: `…/com.duckduckgo.app.browser.BrowserActivity`
- After `pm clear`, LAUNCHER opens `OnboardingActivity` ("Welcome to DuckDuckGo!").
  `clear_browser_package` / `open_url` seed Room `userStage.appStage = ESTABLISHED`
  so Path1/2 `launch_app` + `open_url` reach getdabflow.app without the Welcome gate.
- Page viewport (900×1600): webViewContainer `[0,176]–[900,1600]` (same top inset as Firefox).

## Updating browsers later

1. `py -3 scripts/sideload_farm_browsers.py --force --download-only`
2. Spot-check sizes under `C:\CPharm\apks\` (each should be tens–hundreds of MB)
3. `py -3 scripts/sideload_farm_browsers.py --install`
4. Optional: restart the farm cycle from the operator dash so running workers
   reload code (JSON stems are read from disk each pick).

If Mozilla FTP or GitHub rate-limits you:

1. Manually download the arm64 APK in a browser
2. Save it under `C:\CPharm\apks\` with the exact filename from the table above
3. Re-run `--install` (skips download when cache is present unless `--force`)

## Implementing in other EXEs / forks

Only one shipped EXE today (`wizard/CPharm.spec` → `CPharm.exe`). Any additional
EXE must:

1. Keep `automation.browser_apk_catalog` and `wizard.browser_setup` in
   `wizard/pyinstaller_common.py` → `base_hiddenimports()` (already covered by
   `collect_submodules("automation")` / `"wizard"`).
2. Bundle docs + CLI via `_existing_data_pairs()`:
   - `docs/multi_browser_sideload.md`
   - `scripts/sideload_farm_browsers.py`
3. Call `wizard.browser_setup.ensure_farm_browsers(adb, serials)` from setup /
   “Install browsers” UI — **do not** invent a second Play Store path.
4. Generate sequences with `automation.dabflow_sequence_gen` so Path1/2 stems
   include browser tags and `preferred_browser`.

### Code entry points

| Concern | Module |
|---------|--------|
| Download URLs / cache | `automation/browser_apk_catalog.py` |
| Setup + EXE helper | `wizard/browser_setup.py` → `ensure_farm_browsers` |
| CLI | `scripts/sideload_farm_browsers.py` |
| Sequence stems | `automation/dabflow_sequence_gen.py` |
| Runtime pick / wipe | `automation/browser_farm.py`, `sequence_isolation.py` |
| Package constants / Path1/2 weights | `automation/config.py` |

## Credentials checklist

- [ ] No Google account on farm phones
- [ ] No Play Store sideload / `com.android.vending` login
- [ ] No API tokens committed for browser downloads
- [ ] Brave GitHub calls are anonymous (expect rate limits on shared CI IPs)
- [ ] Tor / inject proxy credentials stay separate (not part of browser APKs)

## Related

- Spec: [docs/superpowers/specs/2026-07-24-multi-browser-path12.md](superpowers/specs/2026-07-24-multi-browser-path12.md)
- Operator sequences: [docs/operator_sequence_quick_guide.md](operator_sequence_quick_guide.md)
