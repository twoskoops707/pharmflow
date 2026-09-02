# DabFlow Sequence Catalog

Source: [https://getdabflow.app](https://getdabflow.app)
Baseline: 900x1600
Total: **8280** (60 cores × 138 paths)

## Live-proven coords (2026-07-11)

- Start Perfect Dab: scroll into view, then tap ~(449, 1281)
- Session notes Skip: ~(229, 1201)
- Nav: Home(90) Timer(270) Stats(449) Glass(629) Settings(809) @ y≈1535
- Home Mantis feed: multiple Sponsored cards (ordinal slots 0–3)
- Tab slots: stats/glass/settings ad-slot containers (2 ordinals each)

- Required sequence_version: **3**
- isolation_policy: **hardcoded_every_seq** (new IP/geo/IMEI/identity every run; runner enforces)
- Path1/2: one file per browser tag (`_chromium` / `_firefox` / `_brave`)
- Path3: Chromium only (Mantis CDP); ads: live on-screen slot pick
