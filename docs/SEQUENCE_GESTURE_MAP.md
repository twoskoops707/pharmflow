# Sequence gesture and navigation map

> **2026-07 update:** Runtime browser resolution — `close_app` / `clear_cookies` without `package` use the device’s MuMu Browser or sideloaded Chromium, not hardcoded Chrome. See [AGENT_HANDOFF_2026-07-04.md](./AGENT_HANDOFF_2026-07-04.md).

Human-readable meaning for each step in `automation/recordings/sequences/*.json`. **Regions are inferred from x/y** on **900×1600** when `base_w`/`base_h` are present; the repo has **no** labeled screen map—descriptions name **bands**, not UI labels.

**Related:** [Sequence catalog](./SEQUENCE_CATALOG.md) (parameter tables for the same files).

---

## How to read this doc

### Baseline coordinate space

When `base_w: 900` and `base_h: 1600` appear on a step, tap/swipe coordinates are read in that normalized frame. Otherwise raw coordinates are listed; **y may exceed 1600** in some files—treat as recorder-specific (often bottom-edge intent).

### Inferred bands (from coordinates only)

| Axis | Range | Inferred region |
| --- | --- | --- |
| x | 0–300 | Left third |
| x | 300–600 | Center third |
| x | 600–900 | Right third |
| y | 0–400 | Top / chrome / hero top |
| y | 400–800 | Upper-mid |
| y | 800–1100 | Mid viewport |
| y | 1100–1350 | Lower-mid |
| y | 1350–1600 | Bottom strip / CTA / nav zone |

### Swipes vs navigation

- **Finger moves up** (end y is less than start y): typically shows **lower** page content (scroll **down** the document).
- **Finger moves down**: typically shows **higher** content (scroll **up**).
- **`open_url`** steps state the **exact URL** and navigation target.

### Keys (`keyevent`)

| Key | Meaning |
| --- | --- |
| `4` | Android **BACK** — dismiss overlay / navigate back. |
| `66` | **ENTER** — submit focused field. |

---

## `close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__hd2a57d.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 2 | `wait` | Pause 0.6s. | Same navigation state; time only. |
| 3 | `open_url` | Opens URL (device default browser). Post-wait 6s after load. | **URL:** `https://getdabflow.app` |
| 4 | `wait` | Pause 5s. | Same navigation state; time only. |
| 5 | `wait` | Pause 3s. | Same navigation state; time only. |
| 6 | `tap` | Tap (658, 755) on **900×1600** — **inferred:** right third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 7 | `wait` | Pause 2.8s. | Same navigation state; time only. |
| 8 | `tap` | Tap (215, 995) on **900×1600** — **inferred:** left third, mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 9 | `wait` | Pause 2s. | Same navigation state; time only. |
| 10 | `tap` | Tap (455, 1145) on **900×1600** — **inferred:** center third, lower-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 11 | `wait` | Pause 2s. | Same navigation state; time only. |
| 12 | `tap` | Tap (685, 1265) on **900×1600** — **inferred:** right third, lower-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 13 | `wait` | Pause 2s. | Same navigation state; time only. |
| 14 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1280)→(465,620), 720 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 15 | `wait` | Pause 2s. | Same navigation state; time only. |
| 16 | `tap` | Tap (450, 705) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 17 | `wait` | Pause 4s. | Same navigation state; time only. |
| 18 | `wait` | Pause 96s. | Same navigation state; time only. |
| 19 | `wait` | Pause 102s. | Same navigation state; time only. |
| 20 | `wait` | Pause 88s. | Same navigation state; time only. |
| 21 | `wait` | Pause 15s. | Same navigation state; time only. |
| 22 | `tap` | Tap (455, 660) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 23 | `wait` | Pause 2s. | Same navigation state; time only. |
| 24 | `tap` | Tap (465, 1495) on **900×1600** — **inferred:** center third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 25 | `wait` | Pause 30s. | Same navigation state; time only. |
| 26 | `wait` | Pause 15s. | Same navigation state; time only. |
| 27 | `keyevent` | Key `4` (BACK) — Android back; dismiss overlay or go back. | Stack/focus dependent. |
| 28 | `wait` | Pause 2.2s. | Same navigation state; time only. |
| 29 | `tap` | Tap (675, 1458) on **900×1600** — **inferred:** right third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 30 | `wait` | Pause 2.5s. | Same navigation state; time only. |
| 31 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1350)→(460,780), 900 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 32 | `wait` | Pause 2s. | Same navigation state; time only. |
| 33 | `clear_cookies` | Clears cookies for `com.android.chrome`. | Clears browser session data. |
| 34 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 35 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 36 | `wait` | Pause 1.6s. | Same navigation state; time only. |
| 37 | `rotate_identity` | Automation identity rotation. | N/A (harness). |
| 38 | `wait` | Pause 2s. | Same navigation state; time only. |
| 39 | `full_reset` | Full automation reset. | N/A (harness). |

## `close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__hdd71d4.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 2 | `wait` | Pause 0.6s. | Same navigation state; time only. |
| 3 | `open_url` | Opens URL (device default browser). Post-wait 6s after load. | **URL:** `https://getdabflow.app` |
| 4 | `wait` | Pause 5s. | Same navigation state; time only. |
| 5 | `wait` | Pause 3s. | Same navigation state; time only. |
| 6 | `tap` | Tap (658, 755) on **900×1600** — **inferred:** right third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 7 | `wait` | Pause 2.8s. | Same navigation state; time only. |
| 8 | `tap` | Tap (215, 995) on **900×1600** — **inferred:** left third, mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 9 | `wait` | Pause 2s. | Same navigation state; time only. |
| 10 | `tap` | Tap (455, 1145) on **900×1600** — **inferred:** center third, lower-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 11 | `wait` | Pause 2s. | Same navigation state; time only. |
| 12 | `tap` | Tap (685, 1265) on **900×1600** — **inferred:** right third, lower-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 13 | `wait` | Pause 2s. | Same navigation state; time only. |
| 14 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1280)→(465,620), 720 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 15 | `wait` | Pause 2s. | Same navigation state; time only. |
| 16 | `tap` | Tap (450, 705) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 17 | `wait` | Pause 4s. | Same navigation state; time only. |
| 18 | `wait` | Pause 96s. | Same navigation state; time only. |
| 19 | `wait` | Pause 102s. | Same navigation state; time only. |
| 20 | `wait` | Pause 88s. | Same navigation state; time only. |
| 21 | `wait` | Pause 15s. | Same navigation state; time only. |
| 22 | `tap` | Tap (455, 660) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 23 | `wait` | Pause 2s. | Same navigation state; time only. |
| 24 | `tap` | Tap (620, 1395) on **900×1600** — **inferred:** right third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 25 | `wait` | Pause 3s. | Same navigation state; time only. |
| 26 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1320)→(465,760), 520 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 27 | `wait` | Pause 2s. | Same navigation state; time only. |
| 28 | `clear_cookies` | Clears cookies for `com.android.chrome`. | Clears browser session data. |
| 29 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 30 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 31 | `wait` | Pause 1.6s. | Same navigation state; time only. |
| 32 | `rotate_identity` | Automation identity rotation. | N/A (harness). |
| 33 | `wait` | Pause 2s. | Same navigation state; time only. |
| 34 | `full_reset` | Full automation reset. | N/A (harness). |

## `open_getdabflow_app__w4s__tap_consent_strip__tap_age_modal__tap_C_lmid__w4s__tap_L_umid__w6s.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `open_url` | Opens URL (device default browser). | **URL:** `https://getdabflow.app` |
| 2 | `wait` | Pause 3.5s. | Same navigation state; time only. |
| 3 | `tap` | Tap (304, 1028) — baseline (unspecified)×(unspecified); bands not applied strictly. Effect: pixel hit (not labeled). | Same origin unless link navigation (unknown). |
| 4 | `wait` | Pause 3.8s. | Same navigation state; time only. |
| 5 | `tap` | Tap (167, 761) — baseline (unspecified)×(unspecified); bands not applied strictly. Effect: pixel hit (not labeled). | Same origin unless link navigation (unknown). |
| 6 | `wait` | Pause 6s. | Same navigation state; time only. |
| 7 | `tap` | Tap (640, 885) — baseline (unspecified)×(unspecified); bands not applied strictly. Effect: pixel hit (not labeled). | Same origin unless link navigation (unknown). |
| 8 | `wait` | Pause 1.75s. | Same navigation state; time only. |
| 9 | `tap` | Tap (679, 1075) — baseline (unspecified)×(unspecified); bands not applied strictly. Effect: pixel hit (not labeled). | Same origin unless link navigation (unknown). |
| 10 | `wait` | Pause 0.75s. | Same navigation state; time only. |
| 11 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(564,1217)→(609,457), 588 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 12 | `wait` | Pause 1.2s. | Same navigation state; time only. |
| 13 | `tap` | Tap (448, 831) — baseline (unspecified)×(unspecified); bands not applied strictly. Effect: pixel hit (not labeled). | Same origin unless link navigation (unknown). |
| 14 | `wait` | Pause 42s. | Same navigation state; time only. |
| 15 | `wait` | Pause 38s. | Same navigation state; time only. |
| 16 | `wait` | Pause 35s. | Same navigation state; time only. |
| 17 | `wait` | Pause 15s. | Same navigation state; time only. |
| 18 | `tap` | Tap (282, 1176) — baseline (unspecified)×(unspecified); bands not applied strictly. Effect: pixel hit (not labeled). | Same origin unless link navigation (unknown). |
| 19 | `wait` | Pause 1.75s. | Same navigation state; time only. |
| 20 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 21 | `wait` | Pause 1.5s. | Same navigation state; time only. |
| 22 | `rotate_identity` | Automation identity rotation. | N/A (harness). |
| 23 | `wait` | Pause 2s. | Same navigation state; time only. |
| 24 | `full_reset` | Full automation reset. | N/A (harness). |

## `open_getdabflow_app__w10s__tap_C_lbot__tap_C_lmid__su__w3s__tap_C_lmid__tap_C_lbot__rotate.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `open_url` | Opens URL (device default browser). | **URL:** `https://getdabflow.app` |
| 2 | `wait` | Pause 8s. | Same navigation state; time only. |
| 3 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(540,1550)→(540,920), 420 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 4 | `wait` | Pause 3s. | Same navigation state; time only. |
| 5 | `tap` | Tap (540, 1180) — baseline (unspecified)×(unspecified); bands not applied strictly. Effect: pixel hit (not labeled). | Same origin unless link navigation (unknown). |
| 6 | `wait` | Pause 2s. | Same navigation state; time only. |
| 7 | `tap` | Tap (540, 1880) — **y exceeds 1600** vs common baseline; **inferred bottom-edge** intent in recorder space (see JSON). | Same origin unless link navigation (unknown). |
| 8 | `wait` | Pause 4s. | Same navigation state; time only. |
| 9 | `rotate_identity` | Automation identity rotation. | N/A (harness). |

## `google_com__typequery_enter__tap_serp__getdabflow_funnel__cleanup.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 2 | `wait` | Pause 0.6s. | Same navigation state; time only. |
| 3 | `open_url` | Opens Google (entry/search). Post-wait 5s after load. | **URL:** `https://www.google.com` |
| 4 | `wait` | Pause 4s. | Same navigation state; time only. |
| 5 | `tap` | Tap (450, 320) on **900×1600** — **inferred:** center third, top band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 6 | `wait` | Pause 1.2s. | Same navigation state; time only. |
| 7 | `type_text` | Types `getdabflow.app` into focused field. | Text entry until submit. |
| 8 | `wait` | Pause 0.8s. | Same navigation state; time only. |
| 9 | `keyevent` | Key `66` (ENTER) — submit focused field / keyboard Go. | Stack/focus dependent. |
| 10 | `wait` | Pause 5.5s. | Same navigation state; time only. |
| 11 | `tap` | Tap (450, 520) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 12 | `wait` | Pause 6s. | Same navigation state; time only. |
| 13 | `tap` | Tap (658, 755) on **900×1600** — **inferred:** right third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 14 | `wait` | Pause 2.8s. | Same navigation state; time only. |
| 15 | `tap` | Tap (215, 995) on **900×1600** — **inferred:** left third, mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 16 | `wait` | Pause 2s. | Same navigation state; time only. |
| 17 | `tap` | Tap (455, 1145) on **900×1600** — **inferred:** center third, lower-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 18 | `wait` | Pause 2s. | Same navigation state; time only. |
| 19 | `tap` | Tap (685, 1265) on **900×1600** — **inferred:** right third, lower-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 20 | `wait` | Pause 2s. | Same navigation state; time only. |
| 21 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1280)→(465,620), 720 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 22 | `wait` | Pause 2s. | Same navigation state; time only. |
| 23 | `tap` | Tap (450, 705) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 24 | `wait` | Pause 4s. | Same navigation state; time only. |
| 25 | `wait` | Pause 96s. | Same navigation state; time only. |
| 26 | `wait` | Pause 102s. | Same navigation state; time only. |
| 27 | `wait` | Pause 88s. | Same navigation state; time only. |
| 28 | `wait` | Pause 15s. | Same navigation state; time only. |
| 29 | `tap` | Tap (455, 660) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 30 | `wait` | Pause 2s. | Same navigation state; time only. |
| 31 | `tap` | Tap (620, 1395) on **900×1600** — **inferred:** right third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 32 | `wait` | Pause 3s. | Same navigation state; time only. |
| 33 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1320)→(465,760), 520 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 34 | `wait` | Pause 2s. | Same navigation state; time only. |
| 35 | `clear_cookies` | Clears cookies for `com.android.chrome`. | Clears browser session data. |
| 36 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 37 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 38 | `wait` | Pause 1.6s. | Same navigation state; time only. |
| 39 | `rotate_identity` | Automation identity rotation. | N/A (harness). |
| 40 | `wait` | Pause 2s. | Same navigation state; time only. |
| 41 | `full_reset` | Full automation reset. | N/A (harness). |

## `open_getdabflow__timer_scroll_x7__cleanup.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 2 | `wait` | Pause 0.6s. | Same navigation state; time only. |
| 3 | `open_url` | Opens URL (device default browser). Post-wait 6s after load. | **URL:** `https://getdabflow.app` |
| 4 | `wait` | Pause 5s. | Same navigation state; time only. |
| 5 | `wait` | Pause 2s. | Same navigation state; time only. |
| 6 | `tap` | Tap (658, 755) on **900×1600** — **inferred:** right third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 7 | `wait` | Pause 2.6s. | Same navigation state; time only. |
| 8 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1220)→(464,668), 4800 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 9 | `wait` | Pause 2s. | Same navigation state; time only. |
| 10 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(432,1175)→(448,710), 3200 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 11 | `wait` | Pause 1.6s. | Same navigation state; time only. |
| 12 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(400,1080)→(412,805), 680 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 13 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 14 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(500,1040)→(482,848), 620 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 15 | `wait` | Pause 1s. | Same navigation state; time only. |
| 16 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(465,990)→(448,822), 580 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 17 | `wait` | Pause 0.9s. | Same navigation state; time only. |
| 18 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(467,962)→(452,808), 720 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 19 | `wait` | Pause 88s. | Same navigation state; time only. |
| 20 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(440,1150)→(455,628), 2600 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 21 | `wait` | Pause 2.4s. | Same navigation state; time only. |
| 22 | `wait` | Pause 15s. | Same navigation state; time only. |
| 23 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 24 | `wait` | Pause 1.6s. | Same navigation state; time only. |

## `open_getdabflow__timer_tabs_variant_a__su_x7__cleanup.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 2 | `wait` | Pause 0.6s. | Same navigation state; time only. |
| 3 | `open_url` | Opens URL (device default browser). Post-wait 6s after load. | **URL:** `https://getdabflow.app` |
| 4 | `wait` | Pause 5s. | Same navigation state; time only. |
| 5 | `wait` | Pause 2.5s. | Same navigation state; time only. |
| 6 | `tap` | Tap (658, 755) on **900×1600** — **inferred:** right third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 7 | `wait` | Pause 2.5s. | Same navigation state; time only. |
| 8 | `tap` | Tap (128, 1455) on **900×1600** — **inferred:** left third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 9 | `wait` | Pause 1.2s. | Same navigation state; time only. |
| 10 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1220)→(464,668), 4800 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 11 | `wait` | Pause 2s. | Same navigation state; time only. |
| 12 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(432,1175)→(448,710), 3200 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 13 | `wait` | Pause 1.6s. | Same navigation state; time only. |
| 14 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(400,1080)→(412,805), 680 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 15 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 16 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(500,1040)→(482,848), 620 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 17 | `wait` | Pause 1s. | Same navigation state; time only. |
| 18 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(465,990)→(448,822), 580 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 19 | `wait` | Pause 0.9s. | Same navigation state; time only. |
| 20 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(467,962)→(452,808), 720 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 21 | `wait` | Pause 88s. | Same navigation state; time only. |
| 22 | `wait` | Pause 15s. | Same navigation state; time only. |
| 23 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(440,1150)→(455,628), 2600 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 24 | `wait` | Pause 2.4s. | Same navigation state; time only. |
| 25 | `clear_cookies` | Clears cookies for `com.android.chrome`. | Clears browser session data. |
| 26 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 27 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 28 | `wait` | Pause 1.6s. | Same navigation state; time only. |
| 29 | `rotate_identity` | Automation identity rotation. | N/A (harness). |
| 30 | `wait` | Pause 2s. | Same navigation state; time only. |
| 31 | `full_reset` | Full automation reset. | N/A (harness). |

## `open_getdabflow__timer_tabs_variant_b__su_x10__cleanup.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 2 | `wait` | Pause 0.6s. | Same navigation state; time only. |
| 3 | `open_url` | Opens URL (device default browser). Post-wait 6s after load. | **URL:** `https://getdabflow.app` |
| 4 | `wait` | Pause 5s. | Same navigation state; time only. |
| 5 | `wait` | Pause 2.8s. | Same navigation state; time only. |
| 6 | `tap` | Tap (658, 755) on **900×1600** — **inferred:** right third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 7 | `wait` | Pause 2.5s. | Same navigation state; time only. |
| 8 | `tap` | Tap (450, 1455) on **900×1600** — **inferred:** center third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 9 | `wait` | Pause 2.4s. | Same navigation state; time only. |
| 10 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(350,1108)→(366,902), 520 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 11 | `wait` | Pause 1.2s. | Same navigation state; time only. |
| 12 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(532,1120)→(514,918), 540 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 13 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 14 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(316,1148)→(342,876), 580 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 15 | `wait` | Pause 1s. | Same navigation state; time only. |
| 16 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(582,1162)→(564,834), 620 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 17 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 18 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(416,1176)→(432,738), 1400 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 19 | `wait` | Pause 1.4s. | Same navigation state; time only. |
| 20 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(466,1188)→(448,698), 1550 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 21 | `wait` | Pause 1.5s. | Same navigation state; time only. |
| 22 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(400,1202)→(428,658), 4200 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 23 | `wait` | Pause 2s. | Same navigation state; time only. |
| 24 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(500,1094)→(482,766), 900 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 25 | `wait` | Pause 1s. | Same navigation state; time only. |
| 26 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(366,1026)→(382,862), 640 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 27 | `wait` | Pause 102s. | Same navigation state; time only. |
| 28 | `wait` | Pause 15s. | Same navigation state; time only. |
| 29 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(452,1135)→(440,642), 2100 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 30 | `wait` | Pause 2.2s. | Same navigation state; time only. |
| 31 | `clear_cookies` | Clears cookies for `com.android.chrome`. | Clears browser session data. |
| 32 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 33 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 34 | `wait` | Pause 1.5s. | Same navigation state; time only. |
| 35 | `rotate_identity` | Automation identity rotation. | N/A (harness). |
| 36 | `wait` | Pause 2.2s. | Same navigation state; time only. |
| 37 | `full_reset` | Full automation reset. | N/A (harness). |

## `open_getdabflow__timer_tabs_variant_c__su_x8__cleanup.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 2 | `wait` | Pause 0.6s. | Same navigation state; time only. |
| 3 | `open_url` | Opens URL (device default browser). Post-wait 6s after load. | **URL:** `https://getdabflow.app` |
| 4 | `wait` | Pause 5s. | Same navigation state; time only. |
| 5 | `wait` | Pause 1.6s. | Same navigation state; time only. |
| 6 | `tap` | Tap (658, 755) on **900×1600** — **inferred:** right third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 7 | `wait` | Pause 2.5s. | Same navigation state; time only. |
| 8 | `tap` | Tap (772, 1455) on **900×1600** — **inferred:** right third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 9 | `wait` | Pause 2.2s. | Same navigation state; time only. |
| 10 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(600,1230)→(580,668), 5000 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 11 | `wait` | Pause 2.2s. | Same navigation state; time only. |
| 12 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(300,1202)→(322,684), 3400 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 13 | `wait` | Pause 1.8s. | Same navigation state; time only. |
| 14 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,944)→(466,806), 500 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 15 | `wait` | Pause 0.85s. | Same navigation state; time only. |
| 16 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,958)→(432,834), 480 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 17 | `wait` | Pause 0.8s. | Same navigation state; time only. |
| 18 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,972)→(466,848), 520 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 19 | `wait` | Pause 0.85s. | Same navigation state; time only. |
| 20 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,986)→(432,862), 460 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 21 | `wait` | Pause 0.8s. | Same navigation state; time only. |
| 22 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1000)→(466,876), 540 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 23 | `wait` | Pause 76s. | Same navigation state; time only. |
| 24 | `wait` | Pause 15s. | Same navigation state; time only. |
| 25 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(732,1162)→(718,616), 2800 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 26 | `wait` | Pause 2s. | Same navigation state; time only. |
| 27 | `clear_cookies` | Clears cookies for `com.android.chrome`. | Clears browser session data. |
| 28 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 29 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 30 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 31 | `rotate_identity` | Automation identity rotation. | N/A (harness). |
| 32 | `wait` | Pause 1.8s. | Same navigation state; time only. |
| 33 | `full_reset` | Full automation reset. | N/A (harness). |

## `open_getdabflow__timer_scroll_x5__cleanup.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 2 | `wait` | Pause 0.6s. | Same navigation state; time only. |
| 3 | `open_url` | Opens URL (device default browser). Post-wait 6s after load. | **URL:** `https://getdabflow.app` |
| 4 | `wait` | Pause 5s. | Same navigation state; time only. |
| 5 | `wait` | Pause 2.5s. | Same navigation state; time only. |
| 6 | `tap` | Tap (658, 755) on **900×1600** — **inferred:** right third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 7 | `wait` | Pause 2.5s. | Same navigation state; time only. |
| 8 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1148)→(462,806), 2200 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 9 | `wait` | Pause 1.4s. | Same navigation state; time only. |
| 10 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(400,1176)→(428,738), 2600 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 11 | `wait` | Pause 1.4s. | Same navigation state; time only. |
| 12 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(466,1188)→(448,698), 3200 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 13 | `wait` | Pause 1.6s. | Same navigation state; time only. |
| 14 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(416,1094)→(432,766), 900 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 15 | `wait` | Pause 96s. | Same navigation state; time only. |
| 16 | `wait` | Pause 15s. | Same navigation state; time only. |
| 17 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(452,1135)→(440,642), 2100 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 18 | `wait` | Pause 2s. | Same navigation state; time only. |
| 19 | `clear_cookies` | Clears cookies for `com.android.chrome`. | Clears browser session data. |
| 20 | `wait` | Pause 1.2s. | Same navigation state; time only. |
| 21 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 22 | `wait` | Pause 1.5s. | Same navigation state; time only. |
| 23 | `rotate_identity` | Automation identity rotation. | N/A (harness). |
| 24 | `wait` | Pause 2s. | Same navigation state; time only. |
| 25 | `full_reset` | Full automation reset. | N/A (harness). |

## `open_getdabflow__triple_timer_cycles__cleanup.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 2 | `wait` | Pause 0.6s. | Same navigation state; time only. |
| 3 | `open_url` | Opens URL (device default browser). Post-wait 6s after load. | **URL:** `https://getdabflow.app` |
| 4 | `wait` | Pause 5s. | Same navigation state; time only. |
| 5 | `wait` | Pause 2.5s. | Same navigation state; time only. |
| 6 | `tap` | Tap (658, 755) on **900×1600** — **inferred:** right third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 7 | `wait` | Pause 2.5s. | Same navigation state; time only. |
| 8 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1148)→(462,806), 2200 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 9 | `wait` | Pause 1.4s. | Same navigation state; time only. |
| 10 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(400,1176)→(428,738), 2600 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 11 | `wait` | Pause 1.4s. | Same navigation state; time only. |
| 12 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(466,1188)→(448,698), 3200 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 13 | `wait` | Pause 1.6s. | Same navigation state; time only. |
| 14 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(416,1094)→(432,766), 900 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 15 | `wait` | Pause 2s. | Same navigation state; time only. |
| 16 | `tap` | Tap (450, 705) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 17 | `wait` | Pause 3s. | Same navigation state; time only. |
| 18 | `wait` | Pause 88s. | Same navigation state; time only. |
| 19 | `wait` | Pause 15s. | Same navigation state; time only. |
| 20 | `tap` | Tap (455, 660) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 21 | `wait` | Pause 2.5s. | Same navigation state; time only. |
| 22 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1090)→(465,720), 900 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 23 | `wait` | Pause 2s. | Same navigation state; time only. |
| 24 | `tap` | Tap (450, 705) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 25 | `wait` | Pause 3s. | Same navigation state; time only. |
| 26 | `wait` | Pause 88s. | Same navigation state; time only. |
| 27 | `wait` | Pause 15s. | Same navigation state; time only. |
| 28 | `tap` | Tap (455, 660) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 29 | `wait` | Pause 2.5s. | Same navigation state; time only. |
| 30 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1090)→(465,720), 900 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 31 | `wait` | Pause 2s. | Same navigation state; time only. |
| 32 | `tap` | Tap (450, 705) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 33 | `wait` | Pause 3s. | Same navigation state; time only. |
| 34 | `wait` | Pause 88s. | Same navigation state; time only. |
| 35 | `wait` | Pause 15s. | Same navigation state; time only. |
| 36 | `tap` | Tap (455, 660) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 37 | `wait` | Pause 2.2s. | Same navigation state; time only. |
| 38 | `clear_cookies` | Clears cookies for `com.android.chrome`. | Clears browser session data. |
| 39 | `wait` | Pause 1.2s. | Same navigation state; time only. |
| 40 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 41 | `wait` | Pause 1.5s. | Same navigation state; time only. |
| 42 | `rotate_identity` | Automation identity rotation. | N/A (harness). |
| 43 | `wait` | Pause 2s. | Same navigation state; time only. |
| 44 | `full_reset` | Full automation reset. | N/A (harness). |

## `open_getdabflow__timer_extended_scroll_x15__cleanup.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 2 | `wait` | Pause 0.6s. | Same navigation state; time only. |
| 3 | `open_url` | Opens URL (device default browser). Post-wait 6s after load. | **URL:** `https://getdabflow.app` |
| 4 | `wait` | Pause 5s. | Same navigation state; time only. |
| 5 | `wait` | Pause 2.5s. | Same navigation state; time only. |
| 6 | `tap` | Tap (658, 755) on **900×1600** — **inferred:** right third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 7 | `wait` | Pause 2.5s. | Same navigation state; time only. |
| 8 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1148)→(462,806), 2200 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 9 | `wait` | Pause 1.4s. | Same navigation state; time only. |
| 10 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(400,1176)→(428,738), 2600 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 11 | `wait` | Pause 1.4s. | Same navigation state; time only. |
| 12 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(466,1188)→(448,698), 3200 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 13 | `wait` | Pause 1.6s. | Same navigation state; time only. |
| 14 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(416,1094)→(432,766), 900 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 15 | `wait` | Pause 72s. | Same navigation state; time only. |
| 16 | `wait` | Pause 15s. | Same navigation state; time only. |
| 17 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(452,1135)→(440,642), 2100 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 18 | `wait` | Pause 2s. | Same navigation state; time only. |
| 19 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1148)→(462,806), 2200 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 20 | `wait` | Pause 1.4s. | Same navigation state; time only. |
| 21 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(400,1176)→(428,738), 2600 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 22 | `wait` | Pause 1.4s. | Same navigation state; time only. |
| 23 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(466,1188)→(448,698), 3200 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 24 | `wait` | Pause 1.6s. | Same navigation state; time only. |
| 25 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(416,1094)→(432,766), 900 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 26 | `wait` | Pause 72s. | Same navigation state; time only. |
| 27 | `wait` | Pause 15s. | Same navigation state; time only. |
| 28 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(452,1135)→(440,642), 2100 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 29 | `wait` | Pause 2s. | Same navigation state; time only. |
| 30 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1148)→(462,806), 2200 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 31 | `wait` | Pause 1.4s. | Same navigation state; time only. |
| 32 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(400,1176)→(428,738), 2600 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 33 | `wait` | Pause 1.4s. | Same navigation state; time only. |
| 34 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(466,1188)→(448,698), 3200 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 35 | `wait` | Pause 1.6s. | Same navigation state; time only. |
| 36 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(416,1094)→(432,766), 900 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 37 | `wait` | Pause 72s. | Same navigation state; time only. |
| 38 | `wait` | Pause 15s. | Same navigation state; time only. |
| 39 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(452,1135)→(440,642), 2100 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 40 | `wait` | Pause 2s. | Same navigation state; time only. |
| 41 | `clear_cookies` | Clears cookies for `com.android.chrome`. | Clears browser session data. |
| 42 | `wait` | Pause 1.2s. | Same navigation state; time only. |
| 43 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 44 | `wait` | Pause 1.5s. | Same navigation state; time only. |
| 45 | `rotate_identity` | Automation identity rotation. | N/A (harness). |
| 46 | `wait` | Pause 2s. | Same navigation state; time only. |
| 47 | `full_reset` | Full automation reset. | N/A (harness). |

## `google_com__tap_serp__getdabflow_funnel__cleanup.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 2 | `wait` | Pause 0.6s. | Same navigation state; time only. |
| 3 | `open_url` | Opens Google SERP for query in URL. Post-wait 6s after load. | **URL:** `https://www.google.com/search?q=getdabflow.app` |
| 4 | `wait` | Pause 5s. | Same navigation state; time only. |
| 5 | `tap` | Tap (380, 540) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 6 | `wait` | Pause 6s. | Same navigation state; time only. |
| 7 | `tap` | Tap (658, 755) on **900×1600** — **inferred:** right third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 8 | `wait` | Pause 2.8s. | Same navigation state; time only. |
| 9 | `tap` | Tap (215, 995) on **900×1600** — **inferred:** left third, mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 10 | `wait` | Pause 2s. | Same navigation state; time only. |
| 11 | `tap` | Tap (455, 1145) on **900×1600** — **inferred:** center third, lower-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 12 | `wait` | Pause 2s. | Same navigation state; time only. |
| 13 | `tap` | Tap (685, 1265) on **900×1600** — **inferred:** right third, lower-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 14 | `wait` | Pause 2s. | Same navigation state; time only. |
| 15 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1280)→(465,620), 720 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 16 | `wait` | Pause 2s. | Same navigation state; time only. |
| 17 | `tap` | Tap (450, 705) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 18 | `wait` | Pause 4s. | Same navigation state; time only. |
| 19 | `wait` | Pause 72s. | Same navigation state; time only. |
| 20 | `wait` | Pause 72s. | Same navigation state; time only. |
| 21 | `wait` | Pause 72s. | Same navigation state; time only. |
| 22 | `wait` | Pause 15s. | Same navigation state; time only. |
| 23 | `tap` | Tap (455, 660) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 24 | `wait` | Pause 2s. | Same navigation state; time only. |
| 25 | `tap` | Tap (620, 1395) on **900×1600** — **inferred:** right third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 26 | `wait` | Pause 3s. | Same navigation state; time only. |
| 27 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1320)→(465,760), 520 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 28 | `wait` | Pause 2s. | Same navigation state; time only. |
| 29 | `clear_cookies` | Clears cookies for `com.android.chrome`. | Clears browser session data. |
| 30 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 31 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 32 | `wait` | Pause 1.6s. | Same navigation state; time only. |
| 33 | `rotate_identity` | Automation identity rotation. | N/A (harness). |
| 34 | `wait` | Pause 2s. | Same navigation state; time only. |
| 35 | `full_reset` | Full automation reset. | N/A (harness). |

## `open_getdabflow__web_ads_left_hero_footer__back_cleanup.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 2 | `wait` | Pause 0.6s. | Same navigation state; time only. |
| 3 | `open_url` | Opens URL (device default browser). Post-wait 6s after load. | **URL:** `https://getdabflow.app` |
| 4 | `wait` | Pause 5s. | Same navigation state; time only. |
| 5 | `wait` | Pause 2.8s. | Same navigation state; time only. |
| 6 | `tap` | Tap (658, 755) on **900×1600** — **inferred:** right third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 7 | `wait` | Pause 2.6s. | Same navigation state; time only. |
| 8 | `tap` | Tap (128, 1455) on **900×1600** — **inferred:** left third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 9 | `wait` | Pause 2.2s. | Same navigation state; time only. |
| 10 | `tap` | Tap (450, 420) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 11 | `wait` | Pause 2s. | Same navigation state; time only. |
| 12 | `tap` | Tap (455, 1488) on **900×1600** — **inferred:** center third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 13 | `wait` | Pause 6.2s. | Same navigation state; time only. |
| 14 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(432,1188)→(448,668), 1100 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 15 | `wait` | Pause 2s. | Same navigation state; time only. |
| 16 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(366,1148)→(382,670), 980 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 17 | `wait` | Pause 1.8s. | Same navigation state; time only. |
| 18 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(514,1108)→(498,642), 1050 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 19 | `wait` | Pause 2.2s. | Same navigation state; time only. |
| 20 | `keyevent` | Key `4` (BACK) — Android back; dismiss overlay or go back. | Stack/focus dependent. |
| 21 | `wait` | Pause 2.4s. | Same navigation state; time only. |
| 22 | `tap` | Tap (450, 1458) on **900×1600** — **inferred:** center third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 23 | `wait` | Pause 2.6s. | Same navigation state; time only. |
| 24 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(446,1202)→(458,658), 3600 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 25 | `wait` | Pause 1.8s. | Same navigation state; time only. |
| 26 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(416,1094)→(432,738), 1400 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 27 | `wait` | Pause 1.4s. | Same navigation state; time only. |
| 28 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(482,1026)→(498,822), 720 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 29 | `wait` | Pause 1.2s. | Same navigation state; time only. |
| 30 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(400,972)→(416,848), 640 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 31 | `wait` | Pause 2s. | Same navigation state; time only. |
| 32 | `clear_cookies` | Clears cookies for `com.android.chrome`. | Clears browser session data. |
| 33 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 34 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 35 | `wait` | Pause 1.6s. | Same navigation state; time only. |
| 36 | `rotate_identity` | Automation identity rotation. | N/A (harness). |
| 37 | `wait` | Pause 2s. | Same navigation state; time only. |
| 38 | `full_reset` | Full automation reset. | N/A (harness). |

## `open_getdabflow__web_ads_center_footer__back_cleanup.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 2 | `wait` | Pause 0.6s. | Same navigation state; time only. |
| 3 | `open_url` | Opens URL (device default browser). Post-wait 6s after load. | **URL:** `https://getdabflow.app` |
| 4 | `wait` | Pause 5s. | Same navigation state; time only. |
| 5 | `wait` | Pause 3.3s. | Same navigation state; time only. |
| 6 | `tap` | Tap (658, 755) on **900×1600** — **inferred:** right third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 7 | `wait` | Pause 2.5s. | Same navigation state; time only. |
| 8 | `tap` | Tap (450, 1455) on **900×1600** — **inferred:** center third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 9 | `wait` | Pause 2.3s. | Same navigation state; time only. |
| 10 | `tap` | Tap (450, 420) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 11 | `wait` | Pause 2.1s. | Same navigation state; time only. |
| 12 | `tap` | Tap (648, 1492) on **900×1600** — **inferred:** right third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 13 | `wait` | Pause 7s. | Same navigation state; time only. |
| 14 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(332,1215)→(348,684), 900 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 15 | `wait` | Pause 1.7s. | Same navigation state; time only. |
| 16 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(566,1176)→(582,658), 850 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 17 | `wait` | Pause 1.6s. | Same navigation state; time only. |
| 18 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(432,1135)→(448,630), 920 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 19 | `wait` | Pause 1.9s. | Same navigation state; time only. |
| 20 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(300,1080)→(322,712), 780 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 21 | `wait` | Pause 2s. | Same navigation state; time only. |
| 22 | `keyevent` | Key `4` (BACK) — Android back; dismiss overlay or go back. | Stack/focus dependent. |
| 23 | `wait` | Pause 2.3s. | Same navigation state; time only. |
| 24 | `tap` | Tap (690, 1458) on **900×1600** — **inferred:** right third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 25 | `wait` | Pause 2.7s. | Same navigation state; time only. |
| 26 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(582,1215)→(598,642), 2200 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 27 | `wait` | Pause 1.6s. | Same navigation state; time only. |
| 28 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(350,1148)→(366,698), 1800 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 29 | `wait` | Pause 1.5s. | Same navigation state; time only. |
| 30 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(466,1052)→(482,808), 680 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 31 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 32 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(416,998)→(432,862), 600 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 33 | `wait` | Pause 2.1s. | Same navigation state; time only. |
| 34 | `clear_cookies` | Clears cookies for `com.android.chrome`. | Clears browser session data. |
| 35 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 36 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 37 | `wait` | Pause 1.3s. | Same navigation state; time only. |
| 38 | `rotate_identity` | Automation identity rotation. | N/A (harness). |
| 39 | `wait` | Pause 2.1s. | Same navigation state; time only. |
| 40 | `full_reset` | Full automation reset. | N/A (harness). |

## `open_getdabflow__web_ads_right_footer__back_cleanup.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 2 | `wait` | Pause 0.6s. | Same navigation state; time only. |
| 3 | `open_url` | Opens URL (device default browser). Post-wait 6s after load. | **URL:** `https://getdabflow.app` |
| 4 | `wait` | Pause 5s. | Same navigation state; time only. |
| 5 | `wait` | Pause 3.8s. | Same navigation state; time only. |
| 6 | `tap` | Tap (658, 755) on **900×1600** — **inferred:** right third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 7 | `wait` | Pause 2.6s. | Same navigation state; time only. |
| 8 | `tap` | Tap (772, 1455) on **900×1600** — **inferred:** right third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 9 | `wait` | Pause 2.4s. | Same navigation state; time only. |
| 10 | `tap` | Tap (450, 420) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 11 | `wait` | Pause 2.2s. | Same navigation state; time only. |
| 12 | `tap` | Tap (440, 1466) on **900×1600** — **inferred:** center third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 13 | `wait` | Pause 5.8s. | Same navigation state; time only. |
| 14 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1202)→(432,670), 1000 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 15 | `wait` | Pause 1.8s. | Same navigation state; time only. |
| 16 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(266,1162)→(282,658), 880 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 17 | `wait` | Pause 1.7s. | Same navigation state; time only. |
| 18 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(632,1120)→(614,642), 860 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 19 | `wait` | Pause 1.8s. | Same navigation state; time only. |
| 20 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(416,1080)→(432,684), 720 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 21 | `wait` | Pause 2s. | Same navigation state; time only. |
| 22 | `keyevent` | Key `4` (BACK) — Android back; dismiss overlay or go back. | Stack/focus dependent. |
| 23 | `wait` | Pause 2.5s. | Same navigation state; time only. |
| 24 | `tap` | Tap (162, 1458) on **900×1600** — **inferred:** left third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 25 | `wait` | Pause 2.8s. | Same navigation state; time only. |
| 26 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(316,1230)→(332,630), 4500 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 27 | `wait` | Pause 2s. | Same navigation state; time only. |
| 28 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(550,1148)→(566,712), 1200 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 29 | `wait` | Pause 1.5s. | Same navigation state; time only. |
| 30 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(366,1012)→(382,836), 560 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 31 | `wait` | Pause 1s. | Same navigation state; time only. |
| 32 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(498,972)→(514,848), 520 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 33 | `wait` | Pause 2.2s. | Same navigation state; time only. |
| 34 | `clear_cookies` | Clears cookies for `com.android.chrome`. | Clears browser session data. |
| 35 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 36 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 37 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 38 | `rotate_identity` | Automation identity rotation. | N/A (harness). |
| 39 | `wait` | Pause 1.9s. | Same navigation state; time only. |
| 40 | `full_reset` | Full automation reset. | N/A (harness). |

## `close_chrome__open_google_com__w4s__tap_google_search_box__type_query_getdabflow__enter__w6s__h2a611a__n1.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 2 | `wait` | Pause 0.6s. | Same navigation state; time only. |
| 3 | `open_url` | Opens Google (entry/search). Post-wait 5s after load. | **URL:** `https://www.google.com` |
| 4 | `wait` | Pause 4s. | Same navigation state; time only. |
| 5 | `tap` | Tap (450, 320) on **900×1600** — **inferred:** center third, top band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 6 | `wait` | Pause 1.2s. | Same navigation state; time only. |
| 7 | `type_text` | Types `getdabflow.app` into focused field. | Text entry until submit. |
| 8 | `wait` | Pause 0.8s. | Same navigation state; time only. |
| 9 | `keyevent` | Key `66` (ENTER) — submit focused field / keyboard Go. | Stack/focus dependent. |
| 10 | `wait` | Pause 5.5s. | Same navigation state; time only. |
| 11 | `tap` | Tap (450, 520) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 12 | `wait` | Pause 6s. | Same navigation state; time only. |
| 13 | `tap` | Tap (658, 755) on **900×1600** — **inferred:** right third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 14 | `wait` | Pause 2.8s. | Same navigation state; time only. |
| 15 | `tap` | Tap (215, 995) on **900×1600** — **inferred:** left third, mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 16 | `wait` | Pause 2s. | Same navigation state; time only. |
| 17 | `tap` | Tap (455, 1145) on **900×1600** — **inferred:** center third, lower-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 18 | `wait` | Pause 2s. | Same navigation state; time only. |
| 19 | `tap` | Tap (685, 1265) on **900×1600** — **inferred:** right third, lower-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 20 | `wait` | Pause 2s. | Same navigation state; time only. |
| 21 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1280)→(465,620), 720 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 22 | `wait` | Pause 2s. | Same navigation state; time only. |
| 23 | `tap` | Tap (450, 705) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 24 | `wait` | Pause 4s. | Same navigation state; time only. |
| 25 | `wait` | Pause 96s. | Same navigation state; time only. |
| 26 | `wait` | Pause 102s. | Same navigation state; time only. |
| 27 | `wait` | Pause 88s. | Same navigation state; time only. |
| 28 | `wait` | Pause 15s. | Same navigation state; time only. |
| 29 | `tap` | Tap (455, 660) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 30 | `wait` | Pause 2s. | Same navigation state; time only. |
| 31 | `tap` | Tap (620, 1395) on **900×1600** — **inferred:** right third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 32 | `wait` | Pause 3s. | Same navigation state; time only. |
| 33 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1320)→(465,760), 520 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 34 | `wait` | Pause 2s. | Same navigation state; time only. |
| 35 | `clear_cookies` | Clears cookies for `com.android.chrome`. | Clears browser session data. |
| 36 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 37 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 38 | `wait` | Pause 1.6s. | Same navigation state; time only. |
| 39 | `rotate_identity` | Automation identity rotation. | N/A (harness). |
| 40 | `wait` | Pause 2s. | Same navigation state; time only. |
| 41 | `full_reset` | Full automation reset. | N/A (harness). |

## `close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__h25538b.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 2 | `wait` | Pause 0.6s. | Same navigation state; time only. |
| 3 | `open_url` | Opens URL (device default browser). Post-wait 6s after load. | **URL:** `https://getdabflow.app` |
| 4 | `wait` | Pause 5s. | Same navigation state; time only. |
| 5 | `wait` | Pause 3s. | Same navigation state; time only. |
| 6 | `tap` | Tap (658, 755) on **900×1600** — **inferred:** right third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 7 | `wait` | Pause 2.8s. | Same navigation state; time only. |
| 8 | `tap` | Tap (215, 995) on **900×1600** — **inferred:** left third, mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 9 | `wait` | Pause 2s. | Same navigation state; time only. |
| 10 | `tap` | Tap (455, 1145) on **900×1600** — **inferred:** center third, lower-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 11 | `wait` | Pause 2s. | Same navigation state; time only. |
| 12 | `tap` | Tap (685, 1265) on **900×1600** — **inferred:** right third, lower-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 13 | `wait` | Pause 2s. | Same navigation state; time only. |
| 14 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1280)→(465,620), 720 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 15 | `wait` | Pause 2s. | Same navigation state; time only. |
| 16 | `tap` | Tap (450, 705) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 17 | `wait` | Pause 4s. | Same navigation state; time only. |
| 18 | `wait` | Pause 96s. | Same navigation state; time only. |
| 19 | `wait` | Pause 102s. | Same navigation state; time only. |
| 20 | `wait` | Pause 88s. | Same navigation state; time only. |
| 21 | `wait` | Pause 15s. | Same navigation state; time only. |
| 22 | `tap` | Tap (455, 660) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 23 | `wait` | Pause 2s. | Same navigation state; time only. |
| 24 | `tap` | Tap (620, 1395) on **900×1600** — **inferred:** right third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 25 | `wait` | Pause 3s. | Same navigation state; time only. |
| 26 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1320)→(465,760), 520 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 27 | `wait` | Pause 2s. | Same navigation state; time only. |
| 28 | `clear_cookies` | Clears cookies for `com.android.chrome`. | Clears browser session data. |
| 29 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 30 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 31 | `wait` | Pause 1.6s. | Same navigation state; time only. |
| 32 | `rotate_identity` | Automation identity rotation. | N/A (harness). |
| 33 | `wait` | Pause 2s. | Same navigation state; time only. |
| 34 | `full_reset` | Full automation reset. | N/A (harness). |

## `open_getdabflow__combo_landing_short__rotate_wait_fullreset.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `open_url` | Opens URL (device default browser). Post-wait 6s after load. | **URL:** `https://getdabflow.app` |
| 2 | `wait` | Pause 6s. | Same navigation state; time only. |
| 3 | `tap` | Tap (658, 755) on **900×1600** — **inferred:** right third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 4 | `wait` | Pause 2.5s. | Same navigation state; time only. |
| 5 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1094)→(460,650), 450 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 6 | `wait` | Pause 2s. | Same navigation state; time only. |
| 7 | `tap` | Tap (450, 1285) on **900×1600** — **inferred:** center third, lower-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 8 | `wait` | Pause 3s. | Same navigation state; time only. |
| 9 | `rotate_identity` | Automation identity rotation. | N/A (harness). |

## `close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__hf26804.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 2 | `wait` | Pause 0.6s. | Same navigation state; time only. |
| 3 | `open_url` | Opens URL (device default browser). Post-wait 6s after load. | **URL:** `https://getdabflow.app` |
| 4 | `wait` | Pause 5s. | Same navigation state; time only. |
| 5 | `wait` | Pause 3.3s. | Same navigation state; time only. |
| 6 | `tap` | Tap (658, 755) on **900×1600** — **inferred:** right third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 7 | `wait` | Pause 2.5s. | Same navigation state; time only. |
| 8 | `tap` | Tap (450, 1455) on **900×1600** — **inferred:** center third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 9 | `wait` | Pause 2.3s. | Same navigation state; time only. |
| 10 | `tap` | Tap (450, 420) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 11 | `wait` | Pause 2.1s. | Same navigation state; time only. |
| 12 | `tap` | Tap (648, 1492) on **900×1600** — **inferred:** right third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 13 | `wait` | Pause 7s. | Same navigation state; time only. |
| 14 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(332,1215)→(348,684), 900 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 15 | `wait` | Pause 1.7s. | Same navigation state; time only. |
| 16 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(566,1176)→(582,658), 850 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 17 | `wait` | Pause 1.6s. | Same navigation state; time only. |
| 18 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(432,1135)→(448,630), 920 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 19 | `wait` | Pause 1.9s. | Same navigation state; time only. |
| 20 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(300,1080)→(322,712), 780 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 21 | `wait` | Pause 2s. | Same navigation state; time only. |
| 22 | `keyevent` | Key `4` (BACK) — Android back; dismiss overlay or go back. | Stack/focus dependent. |
| 23 | `wait` | Pause 2.3s. | Same navigation state; time only. |
| 24 | `tap` | Tap (690, 1458) on **900×1600** — **inferred:** right third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 25 | `wait` | Pause 2.7s. | Same navigation state; time only. |
| 26 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(582,1215)→(598,642), 2200 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 27 | `wait` | Pause 1.6s. | Same navigation state; time only. |
| 28 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(350,1148)→(366,698), 1800 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 29 | `wait` | Pause 1.5s. | Same navigation state; time only. |
| 30 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(466,1052)→(482,808), 680 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 31 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 32 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(416,998)→(432,862), 600 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 33 | `wait` | Pause 2.1s. | Same navigation state; time only. |
| 34 | `clear_cookies` | Clears cookies for `com.android.chrome`. | Clears browser session data. |
| 35 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 36 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 37 | `wait` | Pause 1.3s. | Same navigation state; time only. |
| 38 | `rotate_identity` | Automation identity rotation. | N/A (harness). |
| 39 | `wait` | Pause 2.1s. | Same navigation state; time only. |
| 40 | `full_reset` | Full automation reset. | N/A (harness). |

## `close_chrome__open_getdabflow_app__w9s__tap_consent_strip__tap_age_modal__tap_landing_hero__hfee6b2.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 2 | `wait` | Pause 0.6s. | Same navigation state; time only. |
| 3 | `open_url` | Opens URL (device default browser). Post-wait 6s after load. | **URL:** `https://getdabflow.app` |
| 4 | `wait` | Pause 5s. | Same navigation state; time only. |
| 5 | `wait` | Pause 2.8s. | Same navigation state; time only. |
| 6 | `tap` | Tap (658, 755) on **900×1600** — **inferred:** right third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 7 | `wait` | Pause 2.6s. | Same navigation state; time only. |
| 8 | `tap` | Tap (128, 1455) on **900×1600** — **inferred:** left third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 9 | `wait` | Pause 2.2s. | Same navigation state; time only. |
| 10 | `tap` | Tap (450, 420) on **900×1600** — **inferred:** center third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 11 | `wait` | Pause 2s. | Same navigation state; time only. |
| 12 | `tap` | Tap (455, 1488) on **900×1600** — **inferred:** center third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 13 | `wait` | Pause 6.2s. | Same navigation state; time only. |
| 14 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(432,1188)→(448,668), 1100 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 15 | `wait` | Pause 2s. | Same navigation state; time only. |
| 16 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(366,1148)→(382,670), 980 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 17 | `wait` | Pause 1.8s. | Same navigation state; time only. |
| 18 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(514,1108)→(498,642), 1050 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 19 | `wait` | Pause 2.2s. | Same navigation state; time only. |
| 20 | `keyevent` | Key `4` (BACK) — Android back; dismiss overlay or go back. | Stack/focus dependent. |
| 21 | `wait` | Pause 2.4s. | Same navigation state; time only. |
| 22 | `tap` | Tap (450, 1458) on **900×1600** — **inferred:** center third, bottom band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 23 | `wait` | Pause 2.6s. | Same navigation state; time only. |
| 24 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(446,1202)→(458,658), 3600 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 25 | `wait` | Pause 1.8s. | Same navigation state; time only. |
| 26 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(416,1094)→(432,738), 1400 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 27 | `wait` | Pause 1.4s. | Same navigation state; time only. |
| 28 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(482,1026)→(498,822), 720 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 29 | `wait` | Pause 1.2s. | Same navigation state; time only. |
| 30 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(400,972)→(416,848), 640 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 31 | `wait` | Pause 2s. | Same navigation state; time only. |
| 32 | `clear_cookies` | Clears cookies for `com.android.chrome`. | Clears browser session data. |
| 33 | `wait` | Pause 1.1s. | Same navigation state; time only. |
| 34 | `close_app` | Stop package `com.android.chrome`. | App/browser process ended. |
| 35 | `wait` | Pause 1.6s. | Same navigation state; time only. |
| 36 | `rotate_identity` | Automation identity rotation. | N/A (harness). |
| 37 | `wait` | Pause 2s. | Same navigation state; time only. |
| 38 | `full_reset` | Full automation reset. | N/A (harness). |

## `open_getdabflow_app__w16s__tap_C_lbot__tap_C_lmid__su__w4s__tap_C_lbot__rotate__w15s__full_reset.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `open_url` | Opens URL (device default browser). | **URL:** `https://getdabflow.app` |
| 2 | `wait` | Pause 14s. | Same navigation state; time only. |
| 3 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(540,1650)→(540,900), 500 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 4 | `wait` | Pause 4s. | Same navigation state; time only. |
| 5 | `tap` | Tap (540, 1880) — **y exceeds 1600** vs common baseline; **inferred bottom-edge** intent in recorder space (see JSON). | Same origin unless link navigation (unknown). |
| 6 | `wait` | Pause 10s. | Same navigation state; time only. |
| 7 | `rotate_identity` | Automation identity rotation. | N/A (harness). |

## `open_getdabflow_app__w6s__tap_consent_strip__tap_age_modal__tap_landing_hero__w3s__su.json`

| Idx | Type | Target / effect | Navigates to |
| ---: | --- | --- | --- |
| 1 | `open_url` | Opens URL (device default browser). Post-wait 6s after load. | **URL:** `https://getdabflow.app` |
| 2 | `wait` | Pause 6s. | Same navigation state; time only. |
| 3 | `tap` | Tap (658, 755) on **900×1600** — **inferred:** right third, upper-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 4 | `wait` | Pause 2.5s. | Same navigation state; time only. |
| 5 | `swipe` | Upward stroke (finger moves up) — typically scrolls page **down**. (~(450,1094)→(460,650), 450 ms). **Inferred:** same-document scroll unless URL changes. | Same URL — scroll position changes (typical). |
| 6 | `wait` | Pause 2s. | Same navigation state; time only. |
| 7 | `tap` | Tap (450, 1285) on **900×1600** — **inferred:** center third, lower-mid band. Effect: hits whatever control occupies that pixel (not labeled in JSON). | Same origin unless link navigation (unknown). |
| 8 | `wait` | Pause 3s. | Same navigation state; time only. |
| 9 | `rotate_identity` | Automation identity rotation. | N/A (harness). |

---

### Duplicate sequence arrays

- `open_getdabflow__web_ads_left_hero_footer__back_cleanup.json` — same ordered steps as `close_chrome__open_getdabflow_app__w9s__tap_consent_strip__tap_age_modal__tap_landing_hero__hfee6b2.json`.
- `open_getdabflow__web_ads_center_footer__back_cleanup.json` — same ordered steps as `close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__hf26804.json`.
- `close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__h25538b.json` — same ordered steps as `close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__hdd71d4.json`.
- `close_chrome__open_google_com__w4s__tap_google_search_box__type_query_getdabflow__enter__w6s__h2a611a__n1.json` — same ordered steps as `google_com__typequery_enter__tap_serp__getdabflow_funnel__cleanup.json`.