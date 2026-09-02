# Multi-browser Path1/2 (under the radar)

## Goal

Vary the browser package on Path1/Path2 so request fingerprints are not always `org.chromium.chrome`, without looking like a bot farm that rotates exotic browsers every hit.

## Policy

| Path | Browser |
|------|---------|
| Path1 / Path2 | Dedicated sequence files per browser (`_chromium` / `_firefox` / `_brave`) |
| Path3 (ads / Mantis CDP) | Always Chromium (`org.chromium.chrome`) |

Sequence JSON sets `preferred_browser` / `dabflow.browser`. Isolation honors that package (Path3 still forces Chromium). Weighted runtime pick remains as fallback when a preferred package is missing.

### Default weights (fallback only)

- Chromium — **78%**
- Firefox — **15%**
- Brave — **7%**


## Isolation

Before each sequence, pick the browser for that run, store it per phone, then `pm clear` that package (Chromium also re-seeds FRE-complete). `browse_url` opens the stored package; Path3 ignores the store and forces Chromium.

## Out of scope (now)

- Path3 non-Chromium (CDP / Mantis inject assumes Chromium)
- Play Store Chrome sideload (signing)
- Firefox UA via chrome-command-line (N/A; android_id/geo/IP still rotate)
