# AGENTS.md — cross-agent coordination for this checkout

Multiple agents work this repo concurrently. This file is the mailbox and the
rules of engagement. Check it at session start and after long tool runs.

Current agents:

- **Buffy** (Freebuff desktop agent) — owns `main`-line commits: boot gates
  (`39823ea`), injector client-hint fixes (`fb6b2ec`), Groups port (`c4abc1c`).
- **Cursor agent** — works branch `cursor/pharmflow-branding-cleanup`
  (branding, inject-keepalive supervision, Start Farm false-fail fix `28e3f98`).

## Rules of engagement (both agents)

1. **Message inbox** — `AGENTS_MESSAGES.md` next to this file, append-only.
   Format:

   ```
   ## [UTC timestamp] FROM <agent> TO <agent>
   <body>
   ```

   Read the tail before doing anything destructive. Reply in the same file.
   Never delete prior messages.

2. **Division of labor** — Buffy: farm correctness on `main` (boot gates,
   injector fixes, watchdog/LLM integration). Cursor: branding, EXE
   supervision, deck UX. Merge order: Cursor rebases onto `main` when its
   branch is ready; conflicts go through the inbox BEFORE force-fixing.

3. **File conflicts** — before editing a file the other agent has dirty in
   `git status`, leave a note in the inbox with the path and intent.

4. **Fleet safety** — never kill another agent's lanes (farm/watchdog/inject/
   tor/PharmFlow.exe) without an inbox note first. Never `adb reboot -p` a VM
   (standing rule: MuMu wedge — power VMs off via MuMu UI only).

5. **Standing user rules** (from CLAUDE.md, honored by both): no caps/limits
   in code, todo list every turn, farm money is priority #1, terminal-flash
   suppression for all spawned children.

## Shared tooling

- Subagent dispatch: `~/.agents/skills/subagent-driven-development/` —
  probe → spawn → verify → journal. Any agent may use it; journal verdicts
  are shared context.
- FreeLLMAPI client: `C:\Users\jsmil\freellmapi\tools\pharmflow_agent_client.py`
  (`chat()` / `classify_failure()`) — optional brain for watchdog triage;
  returns None when the gateway is down; currently down (502) until a
  provider key is topped up.
