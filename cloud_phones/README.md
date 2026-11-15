# PharmFlow Cloud Emulator Tools

Unified tooling for local or hosted Android emulator instances (Redroid), including connection checks, backend recovery, and controlled phone-farm operations.

## Quick Start

The Windows operator interface is `PharmFlow.exe` in `C:\PharmFlow\`. Diagnostics and the watchdog are `PharmFlow.exe --agent` and `PharmFlow.exe --watchdog` — not separate downloads. The complete operator guide is [../docs/EXE_QUICK_START.md](../docs/EXE_QUICK_START.md). Full free-tier limits: [../docs/CLOUD_PHONES_SETUP.md](../docs/CLOUD_PHONES_SETUP.md).

The focused watchdog can repair only known Docker/ADB connection failures and does not touch unrelated processes.

### 1. One login in the Control Panel (preferred)
Open **PharmFlow.exe → Run → Cloud connect**. Enter host + count (agent key optional if FreeLLMAPI is on this PC). Click **Connect cloud phones + agent**. That saves the session, wires the FreeLLMAPI agent, and runs setup — no separate CloudPhones.exe and no second farm stack.

### 2. Deploy to Oracle Cloud (Always Free ARM)
```bash
# On your Oracle Cloud Always Free A1.Flex ARM instance:
bash cloud_phones/setup-oracle-cloud.sh
```

### 3. CLI connect (same code path as the widget)
```batch
REM One command does everything (no separate CloudPhones.exe):
PharmFlow.exe --cloud-phones-cli setup --host 100.x.x.x --count N

REM Watch local backend and ADB connections:
python tools\project_agent.py watchdog -- --apply --repair-docker

REM Or step by step:
PharmFlow.exe --cloud-phones-cli connect --host 100.x.x.x --count N
PharmFlow.exe --cloud-phones-cli stealth --host 100.x.x.x --count N
PharmFlow.exe --cloud-phones-cli tor --host 100.x.x.x --count N --verify
```

## Commands

| Command | Description |
|---------|-------------|
| `connect` | Connect to cloud instances via ADB |
| `stealth` | Apply fingerprint, IMEI, browser identity |
| `tor` | Set up Tor proxy per device |
| `setup` | Run all three steps |
| `status` | Show connected devices |

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | (required) | Cloud instance IP |
| `--count` | walk until a port gap | Number of instances. No default of 8. |
| `--start-port` | 5555 | First ADB port |
| `--verify` | false | Verify Tor exit IPs |

## Stealth Protocols

Each cloud device gets unique:

- **Device fingerprint** (brand/model/build) - Samsung, Pixel, OnePlus, etc.
- **IMEI** - Valid with Luhn check digit
- **Android ID** - Random 16-char hex
- **Serial number** - Unique per device
- **Browser user-agent** - Matches device fingerprint
- **MAC address** - Unique per device
- **Tor proxy** - Own exit IP per device

## Files

| File | Purpose |
|------|---------|
| `cloud_phones_cli.py` | Main CLI entry point |
| `connect-cloud-phones.py` | ADB connection logic |
| `stealth-setup.py` | Fingerprint/IMEI stealth |
| `tor-proxy-setup.py` | Tor proxy setup |
| `docker-compose.redroid.yml` | Docker config for redroid instances |
| `setup-oracle-cloud.sh` | Server-side setup script |
| `build.bat` | Build CloudPhones.exe |
| `build_cloud_phones.py` | PyInstaller build script |

## Requirements

- Windows with ADB (bundled or system)
- Oracle Cloud Always Free ARM (`VM.Standard.A1.Flex`, ≤4 OCPU / 24 GB) — see free-tier table in `docs/CLOUD_PHONES_SETUP.md`
- Docker installed on cloud instance
- FreeLLMAPI on this PC for the free agent path (`127.0.0.1:31415`)
- Tor (optional, for unique exit IPs)
