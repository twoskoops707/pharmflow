# Agent Handoff — 2026-09-17

Session summary for whoever (human or agent) picks this up next, from any terminal.
Read this before touching farm/money-path code, per CLAUDE.md's standing rule.

## TL;DR

- `main` is untouched, clean, at `169c06a`.
- `cursor/pharmflow-branding-cleanup` (the big rebrand + money-path hardening
  branch, 457 files) is still **not merged into main** — explicit operator
  decision to hold off. It got a line-by-line error-correction pass this
  session (see below) and is pushed.
- A **new branch**, `fix/branding-cleanup-error-corrections`, was cut from
  that branch's tip so the corrections have their own clean home. No PR
  opened yet — GitHub gave this compare link:
  https://github.com/twoskoops707/pharmflow/pull/new/fix/branding-cleanup-error-corrections
- GitHub auth is now **SSH**, not the old token. `origin` on `main` points to
  `git@github.com:twoskoops707/pharmflow.git`. A deploy-capable SSH keypair
  was generated this session at `/root/.ssh/id_ed25519` and its public half
  is already added to the GitHub account.
- A duplicate/stale clone of this repo was retired (moved, not deleted) to
  `/root/.retired_PharmFlow_repo_20260915` — safe to delete once you're sure
  nothing in it is needed (its tip commit `1db8612d` is a strict ancestor of
  `main`'s current HEAD, so `main` already has everything it had).

## Security note

A GitHub PAT (`ghp_AA01s...`) was pasted into chat earlier this session and
is still technically valid — the operator explicitly said not to worry about
rotating it for now. It's no longer needed for day-to-day git ops since the
switch to SSH. If you're picking this up fresh: consider revoking it at
github.com/settings/tokens regardless, since it's sitting in this machine's
`/root/.retired_PharmFlow_repo_20260915/.git/config` and in this chat's
history.

## What got fixed this session (line-by-line, not pattern search)

All on top of `cursor/pharmflow-branding-cleanup`'s tip, verified by actually
running the `automation/` and `wizard/` unittest suites (not just reading):

- `automation/sequence_playlist.py` — `PLAYLIST_MODES`, `FOLDER_MODES`,
  `_COMBO_REQUIRED_TAIL_TYPES`, `_FLOW_SUBDIRS` were referenced but never
  defined anywhere in the file's history (`NameError` on every playlist
  resolution call). Two call sites passed a profile-key string where a
  directory `Path` was required (`TypeError`). `resolve_steps` never
  defaulted its `directory` arg to `SEQUENCES_DIR`. The file loader only
  accepted `{"steps": [...]}` JSON, crashing on the plain-list format used
  elsewhere in this codebase. Identity-tail detection
  (`_combo_tail_present`/`_strip_trailing_ip_id_tail`) only checked a
  step's `"type"` key, but the loader renames loaded steps' `"type"` to
  `"action"` — this silently broke identity/exit-rotation-tail detection
  for every file-loaded playlist chunk (money-path relevant).
  `resolve_steps` never stripped that tail at all, unlike `resolve_step_chunks`.
- `wizard/phone_setup_entry.py` — **real regression introduced by this
  branch's rebrand pass**: the `CPharm.exe` backward-compat check collapsed
  from `("pharmflow", "cpharm")` to `("pharmflow", "pharmflow")`, which
  would've silently broken existing `CPharm.exe` installs. Restored.
- `automation/dabflow_mantis_client_patch.py` — added `_device_forward_targets()`,
  a helper the test suite already called but that never existed anywhere in
  git history; reconstructed from the existing `cdp_abstract_sockets()` /
  tcp-fallback convention already used inline in `ensure_adb_forward`.
- Several stale/over-broad test assertions fixed to match actual (correct)
  behavior, including one test that mocked the wrong executable name
  (`PharmFlow.exe` instead of `PharmFlowMuMuSetup.exe`).

**Some of these bugs are preexisting on `main` too** (the missing
constants, the dict-only JSON assumption, the tail-detection key mismatch)
and were deliberately **not** touched there — only the branch was fixed,
per explicit operator instruction.

## What's still open

1. **PR decision** — open a PR for `fix/branding-cleanup-error-corrections`
   (link above), or just merge/use `cursor/pharmflow-branding-cleanup`
   directly. Not decided yet.
2. **Merge `cursor/pharmflow-branding-cleanup` into `main`?** — still on
   hold at operator's request. A rule-compliance scan earlier this session
   found no CLAUDE.md violations (no `adb reboot -p` in code, net *increase*
   in `CREATE_NO_WINDOW` usage, no new host-IP routing, a new host-IP
   guardrail test even got added). The branch is a clean fast-forward from
   `main`'s current tip — zero merge conflicts either way. But the biggest
   money-path files (`dashboard.py` +1399/-478, `wizard/farm_control.py`
   +526/-197, `tor_manager.py` +878/-347, `mantis_inject_proxy.py`
   +515/-114) were **not** read line-by-line this session — only
   `sequence_playlist.py`, `phone_setup_entry.py`, and
   `dabflow_mantis_client_patch.py` got the full debug treatment. If asked
   to continue the "line by line" pass, those four files are next.
3. **Local API-key inventory** (not in any repo, intentionally — lives at
   `/root/API_KEYS_MASTER.md` and `/root/API_KEYS_MASTER.csv` on this
   machine, chmod 600). Covers GitHub, PharmFlow, LoansFlow, social-analyzer,
   6Degrees, Pen15. A few entries are flagged "not present on this machine"
   (LoansFlow's Cloudflare token, PharmFlow's LLM/ntfy config) — fill in if
   you have them.
4. **`~/.claude/agents` description trim** — a separate, repo-unrelated
   task (273 custom agent definition files, description fields already
   near the requested ~15k-token budget) that was queued but never started.

## Environment notes for whoever runs tests here

This Linux dev container is missing `tkinter` and `websockets` (both
confirmed identical gaps on `main`, not branch bugs — real CI runs on
`windows-latest`). Two `wizard/test_phone_setup_entry.py` tests also fail
here only because `pathlib.Path` doesn't parse Windows backslashes as
separators on POSIX — also confirmed identical on `main`. None of these are
things to fix in code.
