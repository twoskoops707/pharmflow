# FarmBrowser — Build & Sideloading Guide

## Prerequisites

- **Android Studio** (2023.2+ / Hedgehog or later) OR **Android SDK command-line tools**
- **JDK 17** (bundled with Android Studio, or install separately)
- **Gradle 8.11+** (wrapper included — no separate install needed)

## Build from Android Studio (Recommended)

1. Open Android Studio → **File → Open** → select `farmbrowser/` folder
2. Wait for Gradle sync to complete (bottom-right progress bar)
3. **Build → Build Bundle(s) / APK(s) → Build APK(s)**
4. APK output: `farmbrowser/app/build/outputs/apk/debug/app-debug.apk`
5. For release: **Build → Generate Signed Bundle / APK** → create keystore → `app-release.apk`

## Build from Command Line

```bash
cd farmbrowser

# Windows
gradlew.bat assembleDebug

# Linux / macOS
./gradlew assembleDebug
```

Output: `app/build/outputs/apk/debug/app-debug.apk`

For release build:
```bash
./gradlew assembleRelease
```

## Sideload on Emulators

### Single Phone (MuMu / AVD)
```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

### Multi-Phone Farm (all connected emulators)
```batch
@echo off
:: Sideload FarmBrowser on every connected phone
for /f "tokens=1" %%s in ('adb devices ^| findstr /r "device$"') do (
    echo Installing on %%s ...
    adb -s %%s install -r app\build\outputs\apk\debug\app-debug.apk
)
echo Done!
```

### Via CPharm (automated)
1. Drop `app-debug.apk` into `C:\CPharm\apks\`
2. Run CPharm → Setup → Install Apps on All Phones
3. Or use the `scripts/install_app.bat` (it picks up APKs from `apks/`)

## Set as Default Browser

After sideloading, make FarmBrowser the default URL handler:
```bash
adb shell pm set-home-activity com.farmbrowser.stealth/.browser.BrowserActivity
adb shell am start -a android.intent.action.MAIN -c android.intent.category.HOME
```

## ADB Remote Control

FarmBrowser exposes a JavaScript interface (`FarmBrowser.*`) for ADB automation:

```bash
# Open a URL
adb shell am start -a android.intent.action.VIEW \
    -d "https://example.com" \
    -p com.farmbrowser.stealth

# Set proxy via JS interface (after app is open)
adb shell content call --uri content://com.farmbrowser.stealth/proxy \
    --method set --arg "127.0.0.1:8118"

# Or via CPharm's existing http_proxy setting:
adb shell settings put global http_proxy 127.0.0.1:8118
```

## Proxy Integration with CPharm Tor

FarmBrowser auto-detects Tor proxy via:

1. **System proxy** — reads `settings get global http_proxy` (set by CPharm's `tor_manager.py`)
2. **Port scanning** — probes 127.0.0.1:8118, 8119, 9050, 9051, 9150
3. **Manual config** — Settings screen or `FarmBrowser.setProxy(host, port, type)` JS call

When CPharm runs `adb reverse tcp:8118 tcp:8118`, FarmBrowser automatically picks up the Tor tunnel.

## Stealth Profile

Each emulator instance gets a distinct retail phone profile:
- Real brand/model (Pixel 8, Samsung S24, OnePlus 12, etc.)
- Matching User-Agent, screen size, DPI, GPU renderer
- WebGL vendor/renderer spoofed
- Canvas fingerprint noise
- `navigator.webdriver = false`
- Chrome DevTools detection bypassed

Profiles rotate automatically. Force a specific profile in Settings.

## Architecture

```
WebView → localhost:8199 (local HTTP tunnel)
                ↓
    SOCKS5/HTTP proxy upstream
                ↓
    Tor (via CPharm host Tor instance)
```

For HTTP proxies (upstream residential, Tor HTTPTunnelPort), WebView uses them directly.
For SOCKS5 proxies (Tor SOCKS), the local tunnel bridges HTTP→SOCKS5.
