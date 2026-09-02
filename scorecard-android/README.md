# Farm Remote (Android)

**Farm Remote** — dead-simple phone app to control your CPharm laptop farm. Big buttons, kid-simple.

## Main screen

| Button | Does |
|--------|------|
| **Connect** | Link to laptop dashboard |
| **Find phones** | Scan ADB / emulators |
| **GO!** | Run saved groups (start farm) |
| **STOP** | Stop groups + all phones |
| **Tor ON** | Start Tor proxies |
| **New faces** | Reset identity on all phones |
| **See money $** | Mantis scorecard (scaling, costs, net profit) |

## Setup

1. Laptop: run dashboard (`CPharm Go` or `automation/run_dashboard.bat`).
2. `CPHARM_BIND=0.0.0.0` + Windows firewall allow TCP **8080**.
3. Phone on same Wi‑Fi → enter `192.168.x.x:8080` → **Connect**.

## Build

```bash
cd scorecard-android
./gradlew assembleRelease
```

## CI / download

Push to `main` builds **CPharmFarmRemote.apk** on GitHub Releases (`scorecard-*` tag).

## Docs

- `docs/MANTIS_FARM_DESKTOP_CURSOR_SUMMARY.md`
- `docs/MANTIS_FARM_PHONE_SCALING.md`
