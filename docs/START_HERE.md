# Start here (simple)

You do **not** need to use a terminal for day-to-day farming. Open **PharmFlow.exe** and click.

## Moving to another (non-ARM) PC

**Roles (do not mix these up):**

| App | Job |
|-----|-----|
| **Cursor** | Setup help only |
| **PharmFlow.exe** (`C:\PharmFlow\`) | **Runs the farm** + opens the dashboard |
| **MuMu Player x64** | The phones — **not** Android Studio |

Full steps: **[TRANSFER_TO_NEW_DESKTOP_CURSOR.md](TRANSFER_TO_NEW_DESKTOP_CURSOR.md)**

Success on the new PC = phones you started yourself, **PharmFlow → Start farm**, dash at **http://127.0.0.1:8091/**.

## First time (this PC)

1. Open **PharmFlow**.
2. Click **Set everything up**.
3. If it asks for **MuMu**: install **MuMu Player** (x64 on Intel/AMD; ARM only on Snapdragon), then continue.
4. Pick how many phones (**4, 5, or 6** for a real farm — not 1).
5. If it shows the USB debugging tip: do those taps inside MuMu once, then continue.
6. Wait while PharmFlow installs tools and sets up the phones you already started.
7. Click **Start farm**, then **Open dashboard**.

## Every day

1. Open **MuMu** (phones running).
2. Open **PharmFlow** → **Start farm**.
3. Open dashboard to watch status (`http://127.0.0.1:8091/`).

To stop: **Stop farm** in PharmFlow.

## What PharmFlow does for you

- Installs phone tools and **FarmBrowser** (money browser) on each phone
- Creates and starts MuMu phones
- **Start farm** → one unison supervisor (farm + stealth + watchdog + FreeBuff money lane)
- Operator dashboard at **`http://127.0.0.1:8091/`**
- Keeps each phone on a different sequence identity and exit IP

## When something is wrong

- **MuMu missing** → Download MuMu (correct arch), install, then Check again.
- **Only one phone** → start more phones in MuMu, then Start farm. PharmFlow farms whatever is live on ADB.
- **No dash** → Start farm in **PharmFlow.exe** (never `py scripts\ensure_farm…`).
- **Phone offline** → open MuMu, start that phone, Refresh on Phones.
- Still stuck → **Check computer** on Home, or ask Cursor using the transfer doc (setup only — Cursor must not start the farm from Python).
