# CPharm — Virtual Phone Farm

Run many Android phones on one Windows PC and control them from one place. **No Android Studio required** if you use **MuMu**.

**Download:** [GitHub Releases](https://github.com/twoskoops707/cpharm/releases/latest) — download all three files into the same folder:

| File | Role |
|------|------|
| **CPharm.exe** | Main GUI: wizard, MuMu setup, **Start farm**, operator dashboard **`:8091`**, sequences |
| **CPharmAgent.exe** | Project status and bounded agent planning |
| **CPharmWatchdog.exe** | ADB / inject / emulator health checks and known repairs |

**Automation source (CI mirror):** [github.com/twoskoops707/FamFlow](https://github.com/twoskoops707/FamFlow)

**Run order:** Start `CPharm.exe` first. Use **Start farm** for the Mantis money farm (unison stack). Use `CPharmWatchdog.exe` for connection recovery. Keep all three EXEs in one folder.

**Complete EXE guide:** [docs/EXE_QUICK_START.md](docs/EXE_QUICK_START.md)

**From source:** `py -3 wizard/cpharm_desktop.py` from the repo root.

---

## Mantis money farm (operators)

1. MuMu x64 — **8** portrait phones online (canonical vm0,1,5,7,9,10,12,13).
2. **FarmBrowser** installed on each phone (`farmbrowser/` → debug APK).
3. Open **CPharm.exe** → **Start farm** (spawns unison: farm + stealth + watchdog + FreeBuff money lane).
4. Dashboard: **`http://127.0.0.1:8091/`** (not `:8080` wizard server).
5. **Stop farm** in CPharm when done.

Sequences under `sequences/` use `preferred_browser: com.farmbrowser.stealth.debug` for Path3/ad flows.

**Never** start the farm from Cursor/Python (`ensure_farm_24x7.py`, etc.) — **CPharm.exe owns Start farm**.

---

## Quick start (exe users — wizard / groups mode)

1. Install **MuMu for Windows ARM** on Snapdragon PCs ([mumuglobal.com/download](https://www.mumuglobal.com/download)) — not the x64 installer on ARM.
2. MuMu Multi-instance: create phones as **Phone**, **900 × 1600**, **portrait**.
3. On each phone: **USB debugging ON** (tap Build number 7× in About).
4. Download **CPharm.exe**, **CPharmAgent.exe**, and **CPharmWatchdog.exe** into one folder (e.g. `C:\CPharm\`).
5. Double-click **CPharm.exe** → **Phones (step 4)** → checklist → **Set up my phones** (cold-boot phones if prompted).
6. **Install** (step 2, first time) → **Boot** → **Go** (Tor + run groups).
7. To test an app, use **Phones → Install APK** after ADB shows the phones as `device`.
8. Dashboard: `http://localhost:8080` (port shown in Launch log if 8080 is busy).
9. If Docker or ADB is unhealthy, run `CPharmWatchdog.exe` from PowerShell; see the EXE guide for commands.

**All MuMu farm logic lives in CPharm.exe** — `wizard/mumu_farm_ops.py` is bundled in the binary. The agent and watchdog are separate utilities so the main GUI stays focused and the recovery tools can be run independently.

**Full MuMu guide:** [docs/CPharm_emulator_MuMu_and_sequences.md](docs/CPharm_emulator_MuMu_and_sequences.md)

**Agent handoff (Jul 2026):** [docs/AGENT_HANDOFF_2026-07-04.md](docs/AGENT_HANDOFF_2026-07-04.md)

**Sequence cheat sheet:** [docs/operator_sequence_quick_guide.md](docs/operator_sequence_quick_guide.md)

---

## Unified project and cloud tools (source checkout)

The three release EXEs are the recommended Windows operator interface. The commands below are for developers working from a repository checkout.


The repository now includes one safe entrypoint for project status, bounded agent planning, and the existing Redroid cloud-emulator stack:

```bash
python tools/project_agent.py status
python tools/project_agent.py agent-plan "describe the next automation change"
python tools/project_agent.py emulator config
python tools/project_agent.py emulator up --apply
```

Emulator lifecycle operations are dry-run by default; `--apply` is required before Docker state changes. The focused watchdog can diagnose and repair known Docker/ADB connection failures. See [tools/README.md](tools/README.md).

---

## Recent farm features (included in the EXEs)

- **Per-group test APK** — the wizard's **Teams/group editor** card has **“Pick test APK for this group”**. CPharm copies the chosen APK into `apks/` and installs it on that group's phones before their sequence runs, so each group can test a different app.
- **Live farm status panel** — the dashboard **Run** page shows a live panel (auto-refresh every 2 s) with each group, its phones, and per-phone run # / state / result / APK while automation runs. Backed by `GET /api/groups/status`.
- **Auto-Connect All Phones** — wizard **Step 4 (Phones)** button that best-effort `adb connect`s the MuMu (16384–16393) and emulator/cloud (5555–5562) port ranges without blocking or hanging the wizard. It reuses the shared preflight helper and only runs when needed.
- **Standalone ADB logging** — `auto_phone_adb.py` and `auto_adb_mumu.py` mirror their diagnostics to `logs/cpharm.log` (honoring `CPHARM_LOGS`, same location the wizard/watchdog use) while keeping `--json`/stdout output clean.

## Cloud phones (redroid — native Linux required)

Redroid (Android-in-Docker) requires a **binder** transport that Docker Desktop/WSL2 does **not** expose, so cloud phones stay `offline` on a Windows/WSL2 PC. Run the identical stack on a native-Linux host — a Linux VPS or an Oracle Cloud Ampere A1 instance with a Canonical Ubuntu 24.04 (AArch64) image:

```bash
bash cloud_phones/setup-oracle-cloud.sh
```

The script installs `linux-modules-extra-$(uname -r)` (the source of `binder_linux`), loads the module with `devices=binder,hwbinder,vndbinder`, boots the same redroid compose stack on ports 5555–5562, and verifies each ADB port actually listens. If the host kernel exposes no binder device it **aborts with remediation** rather than producing offline phones. Then connect ADB from your PC:

```bash
adb connect HOST_IP:5555   # repeat up to :5562
```

Details: [cloud_phones/README.md](cloud_phones/README.md)

## Requirements

- Windows 10 or 11 (64-bit)
- 16 GB RAM minimum — each virtual phone uses ~2 GB RAM and ~4 GB disk
- Internet connection for the one-time setup (~1.5 GB download total)

---

## Windows on ARM (Snapdragon)

1. Install **MuMu for Windows ARM** from [mumuglobal.com/download](https://www.mumuglobal.com/download) — not the x64 installer.
2. Use **one** `adb.exe` (the copy CPharm installs). Do not mix old SDK copies.
3. Each phone gets an address like `127.0.0.1:16384` — normal for MuMu.
4. **3 phones** is typical. Addresses change when you recreate VMs — open CPharm → **Phones** → **Set up my phones** again.
5. Browsers use **Tor on your PC** tunneled to each phone at **127.0.0.1** (ports 8118, 8119, 8120…). Do **not** use `10.0.2.2` on this ARM farm.
6. Screen size **900×1600**, **Phone** (not Pad), **portrait**.

Full guide: [docs/CPharm_emulator_MuMu_and_sequences.md](docs/CPharm_emulator_MuMu_and_sequences.md)

---

## Wizard steps (sidebar — work 1→9 in order)

| # | Step | What you do |
|---|------|-------------|
| 1 | **Start** | Read the four-part roadmap |
| 2 | **Install** | Java, Python, Tor, CPharm files on this PC |
| 3 | **Android** | MuMu (recommended) or Google SDK |
| 4 | **Phones** | Connect MuMu, hide emulator look, **Set up my phones** |
| 5 | **Test** | Open getdabflow.app — confirm site + ads |
| 6 | **Steps** | Default tap list (usually set in step 4) |
| 7 | **Builder** | Custom sequences *(optional)* |
| 8 | **Teams** | Group phones + playlists |
| 9 | **Run** | Start service and play sequences |

**DabFlow / getdabflow.app:** uses **FarmBrowser** on each phone for Path3/money sequences (`com.farmbrowser.stealth.debug`). Legacy Path1/2 may use Chromium/Firefox/Brave. Sequences pick browser via `preferred_browser` in JSON.

**Operator docs:** [operator_sequence_quick_guide.md](docs/operator_sequence_quick_guide.md) · [MuMu guide](docs/CPharm_emulator_MuMu_and_sequences.md)

---

## How Many Phones Can You Run?

| RAM | Safe limit |
|-----|-----------|
| 16 GB | 5 phones |
| 32 GB | 10 phones |

Start with 3. You can add more later.

---

## The Dashboard

Once the wizard completes, the automation server runs in the background and the wizard becomes your control panel. You can also open the web dashboard in any browser:

```
http://localhost:8080
```

From your phone: connect to the same WiFi as your PC and use the address shown in the wizard.

---

## Browser Intent Flow (why URL opens are reliable)

CPharm opens links with Android `VIEW` intents and fallbacks, in this order:

- Step-configured target (`browser_component`, then package/activity hints)
- Installed browsers from `browser_adb.packages_for_view_url_attempts` (**MuMu Browser first** on MuMu)
- Generic device-default browser fallback

`close_app` and `clear_cookies` steps **without** a `package` field resolve the active browser via `browser_pkg_for_clear` (same priority). Shipped sequences under `sequences/` no longer pin `com.android.browser` or Chrome.

---

## Sequence + Scaling Flow

Automation runs JSON steps (`open_url`, `tap`, `wait`, `swipe`, `rotate_identity`, etc.) per phone/group.

- `tap`/`swipe` can include `base_w` + `base_h` (authoring resolution)
- Runtime reads device logical size via `adb shell wm size`
- Coordinates are scaled proportionally to the current phone size
- Per-phone `sequence_base_w`/`sequence_base_h` profile is applied to steps that omit baseline fields
- If `wm size` cannot be parsed, raw coordinates are used (backward-compatible fallback)
- Scheduler and group runs now execute through the same scaled/humanized step runner, so tap/swipe mapping and pacing stay consistent per phone display profile.

In-repo sequence samples commonly use a `900x1600` baseline. Keep emulator resolution stable to reduce drift.

**Playlist files** can be assigned per phone (Set A and optional Set B) with `sequence_playlist_mode`: `ordered` (round-robin + one from B), `random` (one random file per non-empty set per repeat), or `series` (chain every file in A, then every file in B, each repeat). Optional `sequence_playlist_shuffle` reorders filenames **each repeat** before that mode runs (deterministic per phone + iteration). Allowed values: `none`, `set_a`, `set_b`, `both_sets_separately`, `combined`. Unknown strings fall back to `none`. **`combined`** merges Set A and Set B into one list, shuffles it, then treats it as a single set: `ordered` / `random` pick **one** file from that merged pool per repeat (not two); `series` runs every merged file in shuffled order. Full shuffle × mode matrix: [docs/CPharm_emulator_MuMu_and_sequences.md](docs/CPharm_emulator_MuMu_and_sequences.md).

The **Generator** tab (**Sequence builder**) is one vertical scroll:

- **Gate:** **Website (URL)**, **App (APK / package)**, or **I already have a sequence file…**
- **Setup cards:** **Website + phone screen size** or **App package name**, then **Continue →** (Unicode arrow in the UI).
- **Your automation** summary, then optional **More options: layouts, browser recording, tap alignment** — expands to preset templates (**Use this layout**), **Record from desktop browser** → **Open** (Edge WebView2 when `pywebview` is available), **Touch calibration**, and **Small preview — record taps here**.
- **Add the actions you want to run** — category toolbox, step list, **Quick edit**, **Add step** shortcuts (Wait / Tap / Swipe / Back / Key).
- **Save your sequence file** — **Save sequence**, **Save As…**, **Run Test**, **Add to Schedule** — default **`automation/recordings/sequences/`**.

Shipped templates still include an age-verification tap marker and browser-oriented defaults (`https://getdabflow.app`) where relevant; app flows use `launch_app` instead of `open_url`.

**Note:** The legacy **WebPE** external-EXE helper is **not** part of the wizard’s tab list anymore (only leftover code may exist for compatibility). Use the **Sequence builder** or hand-edit JSON under **`automation/recordings/sequences/`**.

---

## Identity Rotation (Tor)

Each phone gets its own Tor circuit so every session looks like a different person from a different location.

**Option A — Tor Browser (easiest)**
1. Download and install Tor Browser from **torproject.org**
2. Open it and click Connect
3. Leave it running — CPharm uses it automatically

**Option B — Expert Bundle (no browser)**
1. Download the Tor Expert Bundle for Windows from **torproject.org/download**
2. Unzip it and copy everything into `automation\tor\` inside the CPharm folder
   - `tor.exe` should end up at `cpharm\automation\tor\tor.exe`

### Closing CPharm (wizard clears device proxy)

When you exit CPharm or stop the dashboard from the wizard **Launch** step, the wizard clears each device’s **`http_proxy`** and **Tor `adb reverse`** mappings (best effort over ADB) so emulators are not left pointing at a dead tunnel. Set **`CPHARM_SKIP_EXIT_PROXY_CLEAR=1`** to opt out of that exit-time cleanup. If a phone’s browser still looks broken after a teardown error, open **Launch** in the wizard and use **Fix phone browsers (clear proxy)**.

---

## Folder Layout

```
cpharm/
  automation/
    dashboard.py      ← Automation server — started by the wizard
    tor_manager.py    ← Tor identity rotation
    scheduler.py      ← Daily hit scheduler (random fire-times per phone)
    teach.py          ← Record on one phone, replay on all
    config.py         ← Ports and paths
    tor/              ← Tor Expert Bundle (Option B)
    recordings/       ← Saved teach sessions, group configs, sequences
      sequences/      ← JSON sequence libraries (combo/home matrix, playlists)
  wizard/
    setup_wizard.py   ← Setup wizard source
  requirements.txt
  README.md
```

---

## Running the Server Without the Wizard

```bash
cd automation
python dashboard.py
```

---

## Sequence playlists (optional)

Saved sequence JSON files normally live under **`automation\recordings\sequences\`** (the same folder the **Generator** save dialog uses, and where playlist basenames in **Groups** are resolved). Each phone can **rotate or chain** saved JSON flows (set **Set A** / optional **Set B** in **Groups → Edit**, or edit `automation\recordings\groups_config.json`).

| Key | Role |
|-----|------|
| `sequence_playlist` | Set A: list of sequence **filenames** (basenames only). |
| `sequence_playlist_secondary` | Optional set B; omit or `[]` for single-list behavior. |
| `sequence_playlist_mode` | `ordered` (default), `random`, or `series`. Unknown values → `ordered`. |
| `sequence_playlist_shuffle` | `none` (default), `set_a`, `set_b`, `both_sets_separately`, or `combined`. Unknown values → `none`. |

If no playlist step loads successfully, the phone falls back to its inline `steps`. Full semantics (including **`combined`** shuffle and **`series`** chaining) are in [docs/CPharm_emulator_MuMu_and_sequences.md](docs/CPharm_emulator_MuMu_and_sequences.md).

## Scenario file naming

Repo presets use **event-chain basenames**: ordered phases joined with `__`, derived from step types and tap semantics — see `automation/recordings/sequences/NAMING_PATTERN.txt`. Legacy `sequence_*.json` names may still appear in older notes.

- Examples: `google_com__tap_serp__getdabflow_funnel__cleanup.json`, `open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su.json`
- Avoid spaces and mixed separators; use only letters, numbers, and underscores (Windows-safe); stay within ~200 characters including `.json`.

---

## Troubleshooting

| Problem | What to do |
|---------|------------|
| Phone not on Boot list | Start it in MuMu → **Start all phones** on Boot |
| Browser blank / no internet | Launch → **Fix the phone's internet** |
| Page times out | Launch → **Set up Tor** — wait until log says ready |
| Taps miss | MuMu **Phone** model, **900×1600** portrait; re-run **CPharmMuMuSetup → GO** |
| Groups won't run | **Reload groups file** on Launch after editing Groups |
| Dashboard won't open | Launch → **Start server** first |
| Out of memory | Stop extra MuMu instances; ~2–3 GB RAM per phone |

More fixes: [docs/CPharm_emulator_MuMu_and_sequences.md](docs/CPharm_emulator_MuMu_and_sequences.md) → **If something breaks**
