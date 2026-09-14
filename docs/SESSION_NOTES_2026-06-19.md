> **Superseded:** the product is a single `PharmFlow.exe` in `C:\PharmFlow\` (`--watchdog`, `--agent`, phone setup in-process). Data still lives under `C:\CPharm\`. Ignore EXE names below.

﻿# Session notes — 2026-06-19 (DabFlow / MuMu demo)

> **Superseded in part by Jul 2026 dual-exe work:** see [AGENT_HANDOFF_2026-07-04.md](./AGENT_HANDOFF_2026-07-04.md) for current operator path (CPharmMuMuSetup + CPharm.exe, browser policy, fingerprint).

## What you wanted

- Run **DabFlow demo sequences** aligned with the web app from the repo (`origin/web`), on the MuMu emulator.
- **Record real taps** (manual and guided) so automation uses your coordinates, not guesses.
- A **guided demo** walkthrough with logging (`GUIDED_TAP_LOG`) while you tapped through the flow.

## What we fixed or tuned

| Area | Detail |
|------|--------|
| **Proxy / browser** | Re-applied `adb reverse tcp:8118 tcp:8118` so emulator `http_proxy` (127.0.0.1:8118) works again after reconnect. Verified host + device curl to getdabflow.app. See `PROXY_FIX_STATUS.txt`. |
| **WebView coords** | Dashboard taps use **+192 px on Y** (screen vs page); age gate treated as screen=page. |
| **Age Yes** | Coordinates updated from your tap log (page ~460,907). |
| **Start Dab** | From your taps: **page (528, 1068)** — above layout center; long dwell cluster in log. |
| **Skip (session notes popup)** | Left-side tap ~**page (184, 1230)** from dwell cluster. |
| **Timer waits** | Timer segment tuned for demo (~**90.5 s** total vibe: 84 s + 8 s popup window in JSON). |
| **Human pace** | **0.28 s** between selection taps (0.38 s after age); matches `USER_TAP_ANALYSIS.txt`. |

## Key files (local workspace)

| File | Role |
|------|------|
| `C:\Users\jsmil\CPharm\sequences\900x1600\no-ad\dabflow__demo__ONE.json` | Main demo sequence (local sequences folder; repo JSONs purged for local-only storage). |
| `C:\Users\jsmil\CPharm\USER_TAP_ANALYSIS.txt` | Parsed `USER_TAP_LOG` → taps mapped to JSON checkpoints. |
| `C:\Users\jsmil\CPharm\GUIDED_DEMO_RESULT.txt` | Guided session outcome; short log warning. |
| `C:\Users\jsmil\CPharm\DABFLOW_FLOW_FROM_REPO.md` | Flow reference from repo/web. |
| `C:\Users\jsmil\CPharm\PROXY_FIX_STATUS.txt` | Proxy reverse fix verification steps. |
| `C:\Users\jsmil\CPharm\cpharm-clone\` (git root) | Automation code changes (browser, dabflow layout, tor repair, wizard, docs). |

## What did not finish

- **Guided tap log** only captured **~13 frames** (one drag); steps 2–9 were not in `GUIDED_TAP_LOG` — you finished manually.
- **480× gold matrix** (`generate_dabflow_gold_matrix.py`) was **not regenerated** this session.
- **Too many parallel agents** slowed things down and was frustrating — prefer one thread when resuming.
- **Emulator offline** at stop time: device `10.0.2.179:5555` not connected, so touch overlays could not be cleared via adb (command failed: device not found).

## When you resume

1. **Replay demo ONE live** on MuMu using `dabflow__demo__ONE.json` and proof/run scripts under `cpharm-clone/automation/`.
2. Or run a **full record session** with `getevent` kept alive for the whole flow (both `USER_TAP_LOG` and `GUIDED_TAP_LOG` patterns).
3. **Emulator checklist**
   - `adb connect 10.0.2.179:5555`
   - If browser proxy fails: `adb -s 10.0.2.179:5555 reverse tcp:8118 tcp:8118` (when `http_proxy` is 127.0.0.1:8118).
   - Turn off debug overlays: `show_touches 0`, `pointer_location 0`.

## Cloud upload

See `C:\Users\jsmil\CPharm\cpharm-clone\docs\SESSION_NOTES_2026-06-19.md` (copy in repo) and `CLOUD_UPLOAD_STATUS.txt` after push attempt.

**Do not run** separate `tools/` scripts unless you are developing from a git clone — operators use **CPharmMuMuSetup.exe → GO**.
