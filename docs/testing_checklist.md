# CPharm Comprehensive Testing Checklist

Complete verification checklist for **every** phone farm feature. Use before each release or after major changes to wizard, automation, Tor, fingerprint, or build code.

**Automated subset:** `python scripts/run_verification_tests.py` (runs headless checks and prints a report).

**Manual tests:** Require Windows ARM + MuMu + running phones. Mark Pass/Fail in the tables below.

---

## Category 1: Installation & Setup

| # | Test | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 1.1 | EXE runs without errors | App launches, window opens | [ ] |
| 1.2 | First-run detection works | Detects if first time running (`needs_setup()` → integrated setup) | [ ] |
| 1.3 | Manual path selector opens | `PathSelectorWindow` popup appears (Browse .exe / folder) | [ ] |
| 1.4 | Manual path can be saved | Path saved to `cpharm_config.json` + `saved_paths.json` | [ ] |
| 1.5 | Saved paths persist | Paths available in dropdown after restart | [ ] |

**How to test 1.2–1.5:** Delete or rename `C:\CPharm\cpharm_config.json`, launch `PharmFlow.exe`, use **LOCATE MUMU** on setup checklist, restart app and confirm saved path appears.

---

## Category 2: MuMu Detection

| # | Test | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 2.1 | Auto-detect MuMu Player | Finds under `C:\Program Files\Netease\MuMuPlayer` (or saved path) | [ ] |
| 2.2 | Auto-detect MuMu Global | Finds ARM install (`MuMuPlayerGlobal`) | [ ] |
| 2.3 | Detects on non-standard drive | Portable / D: install found via scan or manual path | [ ] |
| 2.4 | Detects in AppData | `%LOCALAPPDATA%\MuMuPlayer` found if present | [ ] |
| 2.5 | Manual browse works | User can locate folder or `MuMuManager.exe` | [ ] |
| 2.6 | Shows clear "not found" message | Wizard shows locate instructions (not a crash) | [ ] |

**Verify:** Wizard **Start → CHECK SYSTEM** or setup **CHECK AGAIN** / **LOCATE MUMU**. Config key: `mumu_root`.

---

## Category 3: ADB Integration

| # | Test | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 3.1 | ADB auto-downloads | ~6 MB platform-tools downloaded to `C:\CPharm\bundled\adb.exe` | [ ] |
| 3.2 | ADB connects to MuMu | `adb devices -l` shows `127.0.0.1:16384+` as `device` | [ ] |
| 3.3 | ADB commands work | `shell`, `install`, `reverse` succeed | [ ] |
| 3.4 | Multiple device support | Multiple serials visible when multiple phones running | [ ] |

**Commands:**

```powershell
set ADB=C:\CPharm\bundled\adb.exe
%ADB% devices -l
%ADB% -s 127.0.0.1:16384 shell echo ok
```

---

## Category 4: Phone Management

| # | Test | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 4.1 | Can create new phone | New VM created in MuMu (`create_phone`) | [ ] |
| 4.2 | Can start phone | Phone boots, status shows Running | [ ] |
| 4.3 | Can stop phone | Phone shuts down, Tor stopped | [ ] |
| 4.4 | Can configure phone | Resolution 900×1600, fingerprint/Tor applied on start | [ ] |
| 4.5 | Can delete phone | VM removed (`delete_phone` / MuMuManager) | [ ] |

**UI:** Wizard **Phones** step or dashboard `POST /api/phones`, Start/Stop on cards.

---

## Category 5: USB Debugging

| # | Test | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 5.1 | Instructions display | Clear steps on setup **USB Debug** screen | [ ] |
| 5.2 | Can enable via wizard | USB debugging on in emulator Developer Options | [ ] |
| 5.3 | Verification works | `adb devices` shows device; shell responds | [ ] |

**Optional getprop:**

```powershell
%ADB% -s 127.0.0.1:16384 shell getprop ro.debuggable
```

---

## Category 6: Fingerprint System

| # | Test | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 6.1 | setting.json patched | Retail `phone_brand`, `phone_model`, IMEI in `vms/<name>/setting.json` | [ ] |
| 6.2 | ADB flags set | `adb_flags` / security props applied per phone | [ ] |
| 6.3 | Browser flags work | `AutomationControlled` disabled in browser command line | [ ] |
| 6.4 | getprop shows retail | Not "MuMu" or generic emulator strings | [ ] |
| 6.5 | Cold boot required | Changes apply only after stop → start / rotate | [ ] |
| 6.6 | Re-apply works | **RE-APPLY FINGERPRINT** / rotate succeeds | [ ] |

**Commands:**

```powershell
%ADB% -s 127.0.0.1:16384 shell getprop ro.product.model
%ADB% -s 127.0.0.1:16384 shell getprop ro.product.brand
%ADB% -s 127.0.0.1:16384 shell getprop ro.kernel.qemu
```

---

## Category 7: Tor Integration

| # | Test | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 7.1 | Tor Browser detected | Tor install found if present | [ ] |
| 7.2 | Tor Expert Bundle works | `tor.exe` runs, torrc has `HTTPTunnelPort` | [ ] |
| 7.3 | Proxy per phone works | Phone 0 → 8118, phone 1 → 8119, … | [ ] |
| 7.4 | adb reverse setup works | Guest `http_proxy` = `127.0.0.1:<port>` | [ ] |
| 7.5 | Identity rotation works | New circuit after **New IP** / rotate | [ ] |
| 7.6 | Each phone has unique IP | Different exit IP per phone (when all running) | [ ] |

**Commands:**

```powershell
curl --proxy http://127.0.0.1:8118 https://check.torproject.org/api/ip
%ADB% -s 127.0.0.1:16384 shell settings get global http_proxy
netstat -an | findstr 8118
```

---

## Category 8: Browser Management

| # | Test | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 8.1 | Chromium downloads | ~230 MB `ChromePublic.apk` in `C:\CPharm\bundled\` | [ ] |
| 8.2 | Chromium sideloads | `pm list packages` shows Chromium if installed | [ ] |
| 8.3 | MuMu Browser works | `com.mumudroid.browser` opens URLs | [ ] |
| 8.4 | http_proxy honored | Tor works with MuMu Browser | [ ] |
| 8.5 | Chrome ignores proxy | Documented: Chromium may bypass proxy (use MuMu Browser for Tor) | [ ] |

---

## Category 9: Dashboard

| # | Test | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 9.1 | Dashboard starts | http://127.0.0.1:8080 accessible | [ ] |
| 9.2 | Phone grid displays | All phones shown with badges | [ ] |
| 9.3 | Status updates | Live status changes on refresh / poll | [ ] |
| 9.4 | Controls work | Start/stop/rotate from dashboard UI | [ ] |
| 9.5 | Sequence can run | `POST /api/sequences/run` completes | [ ] |

**API smoke:**

```bash
curl http://127.0.0.1:8080/api/status
curl http://127.0.0.1:8080/api/phones
curl http://127.0.0.1:8080/api/tor
```

---

## Category 10: Sequences

| # | Test | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 10.1 | Sequences load | JSON files listed (`/api/sequences`, wizard Steps) | [ ] |
| 10.2 | Sequence runs | Steps execute in order | [ ] |
| 10.3 | Timing works | `wait` steps accurate (± humanization jitter) | [ ] |
| 10.4 | Coordinates scale | 900×1600 authored coords scale to runtime `wm size` | [ ] |
| 10.5 | Humanization works | Timing/coords vary within base v2 sequences | [ ] |
| 10.6 | Ad smoke (internal) | `py scripts/smoke_dabflow_ad_internal.py` offline PASS; `--live` on vm0 shows Mantis patch OK | [ ] |

---

## Category 11: UI/UX

| # | Test | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 11.1 | All screens scroll | No text cut off on small windows | [ ] |
| 11.2 | Scrollbars work | `ScrolledText` log + scroll panels scroll | [ ] |
| 11.3 | Sub-windows open | Settings, Phone Details, Path Selector, Privacy | [ ] |
| 11.4 | Buttons respond | All `command=` handlers fire (check log) | [ ] |
| 11.5 | Colors display | Dark theme / gradient buttons render | [ ] |
| 11.6 | Custom icons display | PNG icons show (not emojis / missing boxes) | [ ] |

---

## Category 12: Anti-Detection

| # | Test | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 12.1 | ro.kernel.qemu empty | Not `1` | [ ] |
| 12.2 | Retail brand shows | samsung / google / etc. | [ ] |
| 12.3 | Retail model shows | Real model number | [ ] |
| 12.4 | No MuMu strings in getprop | `verify_antidetect` passes | [ ] |
| 12.5 | JavaScript detection fails | `navigator.webdriver` not exposed in MuMu Browser | [ ] |

**UI:** **Privacy Status** tab or `/api/privacy`.

---

## Category 13: Build & Release

| # | Test | Expected Result | Pass/Fail |
|---|------|-----------------|-----------|
| 13.1 | EXE builds | `PharmFlow.exe` from PyInstaller | [ ] |
| 13.2 | EXE runs standalone | No Python install required on target PC | [ ] |
| 13.3 | All features in EXE | No `ModuleNotFoundError`; icons/sequences bundled | [ ] |
| 13.4 | GitHub Release works | CI artifact + draft release uploaded | [ ] |

**Build:**

```bash
python scripts/generate_icons.py
pyinstaller wizard/CPharm.spec --noconfirm
pyinstaller wizard/CPharm.spec --noconfirm
```

---

## Verification form

```
TESTING COMPLETED: _____________

Tester Name: ___________________

Date: ___________________

Build / tag: wizard-___________

OVERALL STATUS:
[ ] ALL TESTS PASSED - READY FOR RELEASE
[ ] SOME TESTS FAILED - See below

Failed Tests:
_________________________________
_________________________________
_________________________________

RE-TEST DATE: ___________________
```

### Release criteria (minimum)

| Priority | Categories | Required |
|----------|------------|----------|
| **P0** | 1, 2, 3, 4, 6, 7, 9 | Must pass for any release |
| **P1** | 5, 8, 10, 12 | Must pass for automation releases |
| **P2** | 11, 13 | Must pass before public GitHub release |

---

## Quick verification commands

```powershell
set ADB=C:\CPharm\bundled\adb.exe
set SERIAL=127.0.0.1:16384
%ADB% devices -l
%ADB% -s %SERIAL% shell getprop ro.product.model
%ADB% -s %SERIAL% shell getprop ro.product.brand
%ADB% -s %SERIAL% shell getprop ro.kernel.qemu
curl --proxy http://127.0.0.1:8118 https://check.torproject.org/api/ip
curl http://127.0.0.1:8080/api/status
netstat -an | findstr 8080
netstat -an | findstr 8118
```

## Related docs

- [Troubleshooting](troubleshooting.md)
- [MuMu & Sequences](CPharm_emulator_MuMu_and_sequences.md)
- [Operator Quick Guide](operator_sequence_quick_guide.md)
