# Sequence IP+ID Tail Enforcement (Generated)

This document records how combo-sequence flows are forced to end with per-phone IP + device-identity refresh using existing PharmFlow operations only.

## Enforced tail mechanism

- Canonical tail action types:
  - `rotate_identity`
  - `wait` (`seconds: 2.0`)
  - `full_reset`
- Runtime injection point: playlist resolution in `automation/sequence_playlist.py`.
- Rule: if any selected playlist file for a run has `_combo_` in its filename, the resolved run steps are checked; if the canonical tail is missing, it is appended.
- Existing supported ops only:
  - `rotate_identity` (Tor/proxy IP rotate via existing `tor_manager.rotate_identity_adb`)
  - `full_reset` (existing full identity reset path via `tor_manager.full_identity_reset`)
  - `wait` (existing sequencing delay op)

## Coverage details

- `series` mode: after concatenating selected files from set A/set B, enforce final combo tail once at the end of the combined flow.
- `ordered` / `random` modes: after selecting A/B files for the iteration and concatenating them, enforce final combo tail once at the end.
- If the tail already exists, no duplicate tail is added.

## Touched files

- `automation/sequence_playlist.py`
  - Added combo filename detection.
  - Added tail-presence check helper.
  - Added tail-enforcement helper.
  - Applied enforcement in both `series` and non-`series` playlist resolution paths.
- `docs/sequence_ip_id_tail.generated.md`
  - Added this generated mechanism + touched-files record.
