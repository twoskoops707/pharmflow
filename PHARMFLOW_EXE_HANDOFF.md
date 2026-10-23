# PharmFlow.exe — build & ship (no live patches)

## Rule

**The product is the Release EXE.** Do not “fix” production by editing `C:\PharmFlow\automation\*.py` or hot-copying PharmFlow onto a running farm and claiming the EXE is updated. The frozen binary uses bundled MEI modules.

## EXE SYNC RULE (MANDATORY — project memory)

**All code and logic changed locally must be updated in the EXE and pushed to the repo to build a new EXE on GitHub.**

After any meaningful local change (automation/, scripts/, wizard/, sequences, caps, stealth, inject, click paths):
1. Commit the specific changed files to the PharmFlow repo.
2. Push to `main` — triggers the **Build PharmFlow Wizard** GitHub Action.
3. Confirm CI green: `gh run list --workflow "Build PharmFlow Wizard"`.
4. Confirm new Release EXE exists with the new run number.
5. Stop farm → replace `C:\PharmFlow\PharmFlow.exe` from the Release → Start farm → verify `:8091`.

Never leave the farm running logic that exists only in local files and not in the EXE. Commit → push → build → confirm new exe.

## Ship checklist

1. Change code under `automation/`, `scripts/`, `wizard/` as needed.
2. Bump `APP_VERSION` in `wizard/pyinstaller_common.py` + `wizard/version_info.txt`.
3. Push `main` (path filters trigger **Build PharmFlow Wizard**).
4. Confirm CI **green** (`gh run list --workflow "Build PharmFlow Wizard"`).
5. Download `PharmFlow.exe` from https://github.com/twoskoops707/PharmFlow/releases
6. Stop farm → replace `C:\PharmFlow\PharmFlow.exe` → Start farm → verify `:8091`.

## Local rebuild (dev only)

```powershell
py -m PyInstaller wizard\PharmFlow.spec --noconfirm --distpath C:\PharmFlow\dist_next
```

Still replace the operator’s default `C:\PharmFlow\PharmFlow.exe` from a **Release** for handoff PCs.

## Current ship target

- App **1.4.9** — Release **[wizard-64](https://github.com/twoskoops707/PharmFlow/releases/tag/wizard-64)**
- Situation notes for other desktops: `docs/SITUATION_2026-08-16.md`
