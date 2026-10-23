# DabFlow gold sequences — schema limits vs humanization

PharmFlow normalizes steps in `sequence_normalize.py`; the dashboard enforces the same ceilings during playback.

| Field | Limit | Humanization impact |
|-------|-------|---------------------|
| `wait.seconds` | ≤ 300 | Long “reading” pauses and post-open waits cannot exceed 5 minutes per step; multi-minute sessions use **multiple** wait steps. |
| `tap.jitter` | ≤ 120 px | Imprecision is applied via `jitter` (not `tap_jitter_px`, which the executor does not read). |
| `tap.pre_wait_ms` | ≤ 10000 | Pre-tap hesitation capped at 10s per tap. |
| `tap.retries` | 1–8 (normalized) | Burst retries for flaky taps. |
| `swipe.ms` | ≤ 5000 | Scroll segments cannot exceed 5s each; long paths use **many** swipes. |
| `open_url.post_wait_secs` | ≤ 120 | Initial load wait after `open_url` cannot exceed 2 minutes in one step. |

**Not supported in schema:** alternate field names such as `tap_jitter_px`, per-step Gaussian definitions, or distributions attached to waits — variation must be **materialized** as concrete `seconds` / `jitter` / `pre_wait_ms` values per JSON.

**Keyevent:** Android back uses numeric keycode `"4"` (see existing repo sequences); pattern must match `^[A-Z0-9_]+$`.

## Identity tail (exit browser → IP → device/session ID)

Gold matrix sequences end with the same **step-type** ordering as home-combo reference flows (`rotate_identity` → `wait` → `full_reset` as the final three types):

| Step `type` | Role |
|-------------|------|
| `close_app` | Force-stop the browser package (typically Chrome after DabFlow session). |
| `wait` | Short settle after kill. |
| `rotate_identity` | Host Tor **NEWNYM** + reapply device `http_proxy` (`dashboard.run_sequence_step` → `tor_manager.rotate_identity_adb`). **Exit IP change** for proxied traffic. |
| `wait` | Brief gap before full reset (matches curated sequences ~1.2–2s). |
| `full_reset` | Tor circuit again, new **Android ID** (`settings put secure android_id`), best-effort MAC randomization (root), `pm clear` default browser — **device/session identifier change** plus cookie wipe. |

**JSON cannot express:** VPN vendor APIs, non-Tor proxies, MuMu “instance” cloning, or IMEI-style identifiers. Those stay **outside** the sequence file (host/network/emulator orchestration).

**Requires external/runtime setup (not validated by JSON):**

- Tor must be running per phone index on the **host** with control + HTTP tunnel ports; Android uses `adb reverse` + `settings put global http_proxy` (see `automation/tor_manager.py`). If Tor is down, `rotate_identity` / `full_reset` still execute but may no-op or log failures.

**Overlap:** `full_reset` performs another Tor rotation after `rotate_identity`. That double **NEWNYM** matches the repo’s explicit combo tail and keeps the narrative “IP step then handset/session reset step” visible in the playlist.
