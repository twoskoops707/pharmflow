# Subagent Task Packets — 2026-09-18 (Buffy session dispatch)

Precision work packets for parallel sessions (Cursor / any agent terminal).
Repo: `C:\Users\jsmil\pharmflow`, branch `cursor/pharmflow-branding-cleanup`,
tip `9427106` (425/425 tests green). Live box: `C:\PharmFlow` EXE build
`20260919-0027` (ARM64), farm lanes + dash `:8091` UP — treat as PRODUCTION.

## Standing rules (every packet, no exceptions)

- Stealth and MONEY are the two priorities. Never break either. If a fix
  touches the money path, prove confinement before shipping.
- NO CAPS anywhere: no phone-count, pace, or slot clamps. Operator config is law.
- No `adb reboot -p`, no `adb kill-server`, no proxy `:0`, no host-IP egress,
  no MuMu kills, no touching live farm/inject/Tor/dash processes.
- Every packet: read → trace → test → fix → `python -m pytest tests -q`
  (ARM64 py 3.14) → commit → push → stop. Do NOT rebuild the EXE except in
  Packet A; do not swap `C:\PharmFlow\PharmFlow.exe` except in Packet A.

## Packet A — Money-path line-by-line: `automation/dashboard.py` (+1399/−478 vs main)

The biggest unreviewed money-path diff on the branch. Read every hunk.
Verify: honesty strings match behavior (no false ok/ready/✓), the
`/api/devices/connect` strictness, `/api/teach/*` guards, identity-reset
landed-check (`tor_circuit_rotated AND http_proxy_applied`), envelope shapes
for the APK (`{"phones": [...]}`). Deliverable: fixes as commits on this
branch, one per defect, each with a test. Report line numbers of anything
suspicious you do NOT change.

## Packet B — Money-path line-by-line: `wizard/farm_control.py` (+526/−197)

Includes the frozen-EXE / helper-python resolution chain I partially fixed
(`_is_frozen_app_exe`, `_resolve_helper_python`). Verify the full chain:
`start_farm` env writes, unison ownership, `stop_farm` teardown needles,
`open_operator_dashboard` honesty, `_wait_farm_armed` deadline. Known-fixed
baseline: commit `9427106`. Look for any remaining branding-collapse
(`"pharmflow", "pharmflow"`-style duplicates) anywhere in the file.

## Packet C — Money-path line-by-line: `automation/tor_manager.py` (+878/−347)

Focus: slot-map precedence (`CPHARM_/PHARMFLOW_INJECT_SLOT_MAP` → live serial
map → absolute idx), `_free_base_or_adopt` port-base logic, identity rotation
(NOT claiming success without a pinned guest exit), ControlPort adoption of
orphaned Tor. Cross-check against `mantis_inject_proxy._fleet_slot` — the two
must resolve slots identically or the 2026-09-13 split-brain returns.

## Packet D — Money-path line-by-line: `automation/mantis_inject_proxy.py` (+515/−114)

Focus: `ensure_inject_for_phone` (CA install truth), `verify_reverse_tunnel`
(ADB restarts wipe them), listener adoption on `[WinError 10048]`,
zero-stat stub rejection, client-hint headers. Cross-check
`automation/dabflow_mantis_client_patch.py` paying-fill handoff (fixed in
`9427106`: `_paying_fill_paths` override semantics).

## Packet E — EXE UI sweep (snapshots, not guessing)

Launch EXE (already running), walk every Control Panel page via screenshots,
verify: uniform modern styling (operator standing rule #4), all buttons
launch what they claim (Open dashboard must open :8091 only), no dead ends,
no placeholder text. Screenshot evidence per page. UI fixes go on this
branch under `wizard/assets/pharmflow_app/`. Do not touch farm processes.

## Verification gate (all packets)

`C:\Users\jsmil\AppData\Local\Programs\Python\Python314-arm64\python.exe -m pytest tests -q`
must end `425 passed` (or higher, never lower) before each push. Farm stays
up the whole time — if a run requires touching live state, stop and ask.
