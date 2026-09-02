# CPharm Troubleshooting

Quick fixes for the most common operator and developer issues.

## Quick reference

| Issue | Fix |
|-------|-----|
| MuMu not detected | Check MuMu installation path; use **ARM** version |
| ADB not working | Use bundled ADB; do not rely on system PATH |
| Fingerprint not applying | **Cold boot** required after `setting.json` changes |
| Tor timeout | Use **MuMu Browser**; enable **HTTPTunnelPort** in torrc |
| Buttons not working | Check `command=` handlers and imports |
| Build fails | Check PyInstaller hidden imports in `wizard/pyinstaller_common.py` |
| Browser missing / Play Store login | Sideload only — see [multi_browser_sideload.md](multi_browser_sideload.md); never sign into Google Play on farm phones |

---

## MuMu not detected

**Symptoms:** Setup wizard shows “MuMu not found”, preflight fails, or `farm.is_ready` is false.

**Fixes:**

1. Install **MuMu Player ARM** from [mumuglobal.com](https://www.mumuglobal.com) (required on Snapdragon / Windows ARM PCs).
2. Confirm `MuMuManager.exe` exists under the install root (e.g. `C:\Program Files\Netease\MuMuPlayerGlobal\`).
3. Set an explicit path if auto-detection fails:
   ```powershell
   set CPHARM_MUMU_ROOT=C:\Program Files\Netease\MuMuPlayerGlobal
   ```
   Or save it in **Settings** / `C:\CPharm\cpharm_config.json` as `mumu_root`.
4. In the wizard, open **Android** → **DETECT MUMU**, or run preflight from **Start** → **CHECK SYSTEM**.
5. Click **LOCATE MUMU** (setup wizard) or **Settings → BROWSE** to manually pick the install folder or `MuMuManager.exe`. Paths are saved to `cpharm_config.json` and `saved_paths.json`.
6. Search paths checked by CPharm: `wizard/wizard_paths.py` → `MUMU_SEARCH_PATHS`.

---

## ADB not working

**Symptoms:** “No ADB”, `adb devices` empty, phone shows **No ADB** in dashboard.

**Fixes:**

1. CPharm uses **bundled ADB only** — never the Android SDK on PATH.
   - Dev: `bundled_adb/adb.exe`
   - Installed: `C:\CPharm\bundled\adb.exe`
2. Run **Install** step (or setup **GO**) to download platform-tools if missing.
3. Start the phone first, then connect:
   - Wizard **Phones** → **Start** on the card, or dashboard `POST /api/phones/{name}/start`.
4. Expected serial format: `127.0.0.1:16384 + (index × 32)` (phone 0 → `16384`, phone 1 → `16416`, …).
5. Enable **USB debugging** on the emulator (see **Android** step in the wizard).
6. Verify manually:
   ```powershell
   C:\CPharm\bundled\adb.exe devices -l
   ```

---

## Fingerprint not applying

**Symptoms:** `getprop` still shows emulator values; anti-detection checks fail; browse sessions look “leaked”.

**Fixes:**

1. Fingerprint is written to `vms/<instance>/setting.json` — changes do **not** apply until a **cold boot** (stop → start).
2. Use **Rotate ID** on a phone card, or a sequence step `rotate_identity` / `ensure_fingerprint` before `open_url`.
3. Do not set `CPHARM_SKIP_FINGERPRINT=1` unless you intentionally want patching disabled.
4. After rotate, wait for boot to finish before opening URLs (sequence `wait` steps help).
5. Re-check on the **Test** step or **Privacy Status** tab.

---

## Tor timeout

**Symptoms:** Pages never load, proxy errors, `verify_phone_tor` fails, “safe network” messages in logs.

**Fixes:**

1. Use **MuMu Browser** (`com.mumudroid.browser`) — it honors `settings put global http_proxy`. Chromium may ignore proxy on some builds.
2. Each phone needs its own **HTTPTunnelPort** in torrc (`8118`, `8119`, …). CPharm writes this in `tor_instances/phone_<n>/torrc`.
3. CPharm maps host Tor into the guest with **`adb reverse tcp:<port> tcp:<port>`** and sets guest proxy to `127.0.0.1:<port>` — not `10.0.2.2` unless `CPHARM_PROXY_LEGACY_GATEWAY=1`.
4. Start Tor for the phone: wizard **Tor Control** or `POST /api/tor/{name}/start`.
5. Confirm torrc contains `HTTPTunnelPort <port>` and the Tor process is running for that index.
6. Click **New IP** / `rotate` if the circuit is stale.

---

## Buttons not working

**Symptoms:** UI clicks do nothing, no log output, no API calls.

**Fixes:**

1. Every CustomTkinter button must pass a callable: `command=self._handler` (not `command=self._handler()` unless intentional).
2. Use `lambda` with default args for loops to avoid closure bugs:
   ```python
   command=lambda n=inst.name: self._start_one(n)
   ```
3. Long work must run on a **background thread**; update UI with `self.after(0, ...)`.
4. Check `cpharm.log` under `C:\CPharm\logs\` (or project `data/logs/` in dev).
5. If imports fail at startup, the window may render but handlers never register — run from a terminal and read the traceback.

---

## Build fails (PyInstaller)

**Symptoms:** `ModuleNotFoundError` at runtime, missing icons/sequences, or Analysis errors during `pyinstaller`.

**Fixes:**

1. Build from repo root with icons generated first:
   ```bash
   python scripts/generate_icons.py
   pyinstaller wizard/CPharm.spec --noconfirm
   pyinstaller wizard/CPharm.spec --noconfirm
   ```
2. Add missing modules to `wizard/pyinstaller_common.py` → `base_hiddenimports()` or `collect_package_assets()`.
3. Ensure data folders exist before build (CI creates empty `bundled_adb/` and `tor/` placeholders).
4. Bundled datas: `automation/recordings`, `dabflow_mapping.json`, `wizard/icons`, `bundled_adb`, `tor`.
5. Common missing imports: `flask`, `werkzeug`, `jinja2`, `customtkinter`, `PIL`, and submodules under `wizard.*` / `automation.*`.
6. For a new automation package, run `collect_submodules("automation")` (already included in common config).

---

## Verification commands

Use **bundled ADB** (not system PATH). Replace `ADB` and `SERIAL` for your install:

```powershell
# Windows (installed EXE)
set ADB=C:\CPharm\bundled\adb.exe
set SERIAL=127.0.0.1:16384

# Dev (repo)
set ADB=bundled_adb\adb.exe
set SERIAL=127.0.0.1:16384
```

Phone index → serial: `16384 + index × 32` (phone 1 → `16416`, phone 2 → `16448`, …).  
Phone index → Tor HTTP port: `8118 + index` (phone 1 → `8119`, …).

### Check MuMu / ADB

```bash
%ADB% devices -l
%ADB% -s %SERIAL% shell getprop ro.build.version.release
```

Expect at least one device in `device` state. If empty, start the phone in the wizard and enable USB debugging.

### Check fingerprint

Run **after** rotate identity or cold boot:

```bash
%ADB% -s %SERIAL% shell getprop ro.product.model
%ADB% -s %SERIAL% shell getprop ro.product.brand
%ADB% -s %SERIAL% shell getprop ro.kernel.qemu
```

| Property | Good | Problem |
|----------|------|---------|
| `ro.product.model` | Retail model (e.g. `SM-S918B`) | Generic/emulator name |
| `ro.product.brand` | Retail brand (e.g. `samsung`) | `generic`, `Android` |
| `ro.kernel.qemu` | `0` or empty | `1` = still looks like emulator |

### Check Tor

Host-side (phone 0 uses port `8118`):

```bash
curl --proxy http://127.0.0.1:8118 https://check.torproject.org/api/ip
```

Or open in a browser: https://check.torproject.org (via the same proxy).  
Success = JSON/HTML indicates Tor usage. Timeout = Tor not running or `HTTPTunnelPort` missing.

Guest proxy inside the emulator (what the browser uses):

```bash
%ADB% -s %SERIAL% shell settings get global http_proxy
```

Expect `127.0.0.1:8118` (or `8119`, … for other phone indices).

### Check ports

Dashboard and Tor listeners (Windows):

```powershell
netstat -an | findstr 8080
netstat -an | findstr 8118
netstat -an | findstr 8119
```

| Port | Service |
|------|---------|
| `8080` | Flask dashboard (`/api/phones`, `/api/tor`, …) |
| `8118` | Tor HTTPTunnelPort — phone 0 |
| `8119+` | Tor HTTPTunnelPort — phone 1, 2, … |

Quick API smoke test:

```bash
curl http://127.0.0.1:8080/api/status
curl http://127.0.0.1:8080/api/tor
```

---

## Logs and diagnostics

| Resource | Location |
|----------|----------|
| Main log | `C:\CPharm\logs\cpharm.log` |
| Setup log | `C:\CPharm\logs\setup.log` (standalone setup EXE) |
| Web dashboard | http://127.0.0.1:8080 — Activity Log + `/api/logs` |
| Preflight | Wizard **Start** → **CHECK SYSTEM** |

## Environment variables (recap)

| Variable | When to use |
|----------|-------------|
| `CPHARM_MUMU_ROOT` | MuMu not auto-detected |
| `CPHARM_SKIP_FINGERPRINT=1` | Disable fingerprint patching (debug only) |
| `CPHARM_PROXY_LEGACY_GATEWAY=1` | Fall back to `10.0.2.2` proxy gateway |
| `CPHARM_TOR_PATH` | Custom `tor.exe` location |
| `CPHARM_DASHBOARD_PORT` | Change dashboard port (default `8080`) |

## Related docs

- [MuMu & Sequences](CPharm_emulator_MuMu_and_sequences.md)
- [Operator Quick Guide](operator_sequence_quick_guide.md)
