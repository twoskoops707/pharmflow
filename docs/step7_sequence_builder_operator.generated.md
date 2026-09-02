# Step 7 — Sequence Generator (operator)

In the current wizard, **Step 7** is the **Generator** page (sidebar: **Generator**). It uses three substeps: **Setup → Build → Save** (shown as 1 of 3 / 2 of 3 / 3 of 3 at the top of the page).

## Simple path (URL-first)

1. **Setup** — Enter a full **`http://` or `https://` URL**. The UI defaults to **`https://getdabflow.app`** (check spelling). Pick a display baseline (often **900×1600** for shipped presets). Click **Load context** (or equivalent) so the Build step can use the right viewport; you can **Load sequence file…** to import existing JSON and continue in **Build**.
2. **Build** — Add steps via templates, **Add action**, optional **desktop browser helper** (WebView2 when installed), and/or **tap/swipe in the small preview** on the canvas. For **Website (URL)** flows, sequences drive the **device browser** via **`open_url`** and gestures. For **App (APK / package)** flows, steps use **`launch_app`** and in-app gestures — APK install/launch from the dashboard is separate from JSON step types.
3. **Save** — **Run Test** for validation, then **Save sequence** / **Save As…**. Default folder is **`automation/recordings/sequences/`** — use this path so **Groups** playlist basenames resolve. **Add to Schedule** pushes the current steps as the default template for Groups/scheduler.

**URL vs native app:** Opening links uses **`open_url`** (or dashboard **`POST /api/open_url`**). Installing or launching an installed app uses **`POST /api/install`** / **`POST /api/launch_app`** — not sequence JSON.

**Human-like behavior:** The automation server defaults to natural timing (`CPHARM_HUMAN_VARIATION`; see `automation/config.py`). The **Launch** page explains that this stays **on** unless you disable it for debugging.

**More options** on Setup is collapsed by default — expand for preset layouts, optional desktop-browser helper (pywebview), touch calibration, and the small preview.

---

## Supported `type` values (scheduler / `run_sequence_step`)

These are the only step types executed during sequence runs. Any other `type` is ignored.

| `type` | Purpose / main keys |
| --- | --- |
| `open_url` | Open **http(s)** on the device via Android **VIEW** intent — **`url`** required. Optional: **`browser_component`**, **`package`** / **`activity`**, **`new_tab`** / **`create_new_tab`**, **`post_wait_secs`**. |
| `tap` | **`x`**, **`y`**; optional **`base_w`**, **`base_h`**, **`retries`**, **`jitter`**, **`pre_wait_ms`**. |
| `wait` | **`seconds`** (capped by runtime). |
| `swipe` | **`x1`**, **`y1`**, **`x2`**, **`y2`**, **`ms`**; optional **`base_w`**, **`base_h`**. |
| `keyevent` | **`key`** — Android key name or numeric code (`BACK`, `66`, `4`, …). |
| `close_app` | **`package`** — `am force-stop`. |
| `clear_cookies` | **`package`** (browser); picks installed browser if unset/invalid. |
| `type_text` | **`text`** — passed to `input text`. |
| `rotate_identity` | Tor / identity rotation (no extra keys). |
| `full_reset` | Full identity reset (no extra keys). |

**URLs vs packages / APKs (dashboard):** Opening links uses **`open_url`** steps or **`POST /api/open_url`** (device browser only, never the host PC). Installing an APK uses **`POST /api/install`** (after **`POST /api/upload`**). Launching an installed app by package uses **`POST /api/launch_app`** — not a sequence step.
