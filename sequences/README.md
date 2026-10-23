# Production sequences (900x1600)

This directory mirrors the local PharmFlow sequences tree used by automation and the setup wizard.

- **Canonical local path (Windows):** `C:\Users\jsmil\PharmFlow\sequences`
- **Override:** set `PHARMFLOW_SEQUENCES_DIR` to point at another folder.

JSON under `900x1600/` are the kept automation sequences (ad / no-ad / doesnt-finish / early-exit subsets). Do not commit Tor data, `.rec` recordings, or live ADB screenshots — those stay local per `.gitignore`.
