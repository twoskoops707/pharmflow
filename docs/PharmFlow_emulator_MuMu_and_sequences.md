# PharmFlow Emulator: MuMu ARM & Automation Sequences

## Overview

PharmFlow manages a farm of MuMu Player ARM emulator instances on Windows Snapdragon PCs. Each instance is a virtual Android phone controlled via bundled ADB, routed through its own Tor circuit, and automated via JSON sequences.

## MuMu ARM Installation

1. Download MuMu Player **ARM version** from [mumuglobal.com](https://www.mumuglobal.com)
2. Install to default path or set `PHARMFLOW_MUMU_ROOT`
3. Run `PharmFlow.exe` — first launch runs integrated setup and verifies MuMu detection

### Phone Creation Defaults

| Setting | Value |
|---------|-------|
| Resolution | 900 × 1600 |
| Orientation | Portrait |
| DPI | 320 |
| USB Debugging | Enabled via setting.json + UI taps |

### MuMuManager CLI

PharmFlow uses `MuMuManager.exe` for instance lifecycle:

```
MuMuManager.exe api create --name=Phone-01 --resolution=900,1600,320 --orientation=1
MuMuManager.exe api launch --name=Phone-01
MuMuManager.exe api shutdown --name=Phone-01
```

## ADB Architecture

- **Bundled ADB** at `bundled_adb/adb.exe` — never uses system PATH ADB
- Serial format: `127.0.0.1:16384 + (index × 32)`
- All operations go through `automation/adb_wrapper.py`

## Fingerprint Patching

Fingerprints are patched in `vms/<instance>/setting.json`:

| Field | Example |
|-------|---------|
| `phone_brand` | samsung |
| `phone_model` | SM-S918B |
| `phone_imei` | 353325101234567 |
| `mac_address` | 02:AB:CD:EF:12:34 |
| `user_agent` | Mobile Chrome UA |
| `browser_command_line` | `--disable-blink-features=AutomationControlled` |

### Cold Boot Requirement

After patching `setting.json`, a **cold boot** (stop → start) is required for `getprop` to reflect new values. PharmFlow does this automatically via `rotate_identity` and `ensure_fingerprint_before_browse()`.

Disable fingerprinting: `PHARMFLOW_SKIP_FINGERPRINT=1`

## Tor Per-Phone Proxy

```
Phone 0: HTTPTunnelPort 8118, adb reverse tcp:8118
Phone 1: HTTPTunnelPort 8119, adb reverse tcp:8119
Phone N: HTTPTunnelPort 8118+N
```

Android proxy: `settings put global http_proxy 127.0.0.1:<port>`

**Important**: Uses `adb reverse` to map guest `127.0.0.1` to host Tor — NOT the `10.0.2.2` emulator gateway.

## Browser Priority

1. **MuMu Browser** (`com.mumudroid.browser`) — honors `http_proxy`
2. **Chromium** (`org.chromium.chrome`) — sideloaded from ARM64 snapshots
3. Device default browser

`open_url` always calls `ensure_fingerprint_before_browse()` first.

## Sequence Format

Sequences are JSON files in `automation/recordings/sequences/`:

```json
{
  "name": "example_browse",
  "phone": "Phone-01",
  "author_width": 900,
  "author_height": 1600,
  "steps": [
    {"action": "rotate_identity", "params": {}},
    {"action": "wait", "params": {"seconds": 5}},
    {"action": "open_url", "params": {"url": "https://example.com"}},
    {"action": "tap", "params": {"x": 450, "y": 800}},
    {"action": "swipe", "params": {"x1": 450, "y1": 1200, "x2": 450, "y2": 400, "duration_ms": 500}}
  ]
}
```

### Supported Actions

| Action | Params | Description |
|--------|--------|-------------|
| `tap` | `x`, `y` | Tap at coordinates (authored space) |
| `wait` | `seconds` | Sleep |
| `swipe` | `x1`, `y1`, `x2`, `y2`, `duration_ms` | Swipe gesture |
| `open_url` | `url` | Open URL in preferred browser |
| `rotate_identity` | — | New fingerprint + Tor circuit + cold boot |
| `shell` | `command` | Raw adb shell |
| `keyevent` | `code` | Android keyevent code |

### Coordinate Scaling

Coordinates are authored at **900×1600**. At runtime, PharmFlow queries `wm size` and scales:

```
scaled_x = x × runtime_width / 900
scaled_y = y × runtime_height / 1600
```

## Dashboard API

Server: `http://localhost:8080`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | MuMu detection status |
| `/api/phones` | GET/POST | List/create phones |
| `/api/phones/{name}/start` | POST | Start phone + Tor |
| `/api/phones/{name}/stop` | POST | Stop phone |
| `/api/phones/{name}/rotate` | POST | Rotate identity |
| `/api/sequences` | GET | List sequences |
| `/api/sequences/run` | POST | Run sequence |
| `/api/groups` | GET/POST | Group management |
| `/api/scheduler/jobs` | GET | List scheduled jobs |
| `/api/tor` | GET | Tor detection + per-phone status |
| `/api/tor/{name}/start\|stop\|rotate` | POST | Tor control |
| `/api/logs` | GET | Activity log for UI |

## Troubleshooting

See [Common Issues + Fixes](troubleshooting.md) for MuMu detection, ADB, fingerprint cold boot, Tor, UI buttons, PyInstaller build failures, and [verification commands](troubleshooting.md#verification-commands).

## File Reference

| File | Purpose |
|------|---------|
| `wizard/mumu_farm_ops.py` | All MuMu farm logic |
| `automation/mumu_fingerprint.py` | Fingerprint engine |
| `automation/tor_manager.py` | Tor control |
| `automation/browser_adb.py` | Browser discovery |
| `automation/dashboard.py` | API server |
| `automation/sequence_runner.py` | Sequence execution |
