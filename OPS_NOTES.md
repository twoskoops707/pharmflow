# PharmFlow — Ops & Debug Notes (living document)

_Updated: 2026-09-09 ~03:00. Read this before touching anything. Update it whenever system state drifts._

## Standing user rules (ALWAYS APPLY)
1. **Keep going until fully done**: tests green → CI green → CI EXE downloaded (never local build) → swapped in → running → farm verified underneath.
2. **No caps/limits in code.** Never clamp phone counts, sequence pace, or slot counts. Operator config is law.
3. **Don't limit the phone count** in tests or code — derive from the live fleet.
4. **EXE must kill dead/unneeded processes itself** (orphaned tor, wedged adb) and **reconnect all phones on ADB** (boot + running-but-offline).
5. Commit + push only when asked or when it's part of the delivery loop (CI build), per conversation precedent.
6. Machine: **16 GB RAM, x64**. Farm = 7 MuMu ARM VMs + 3 pythonw lanes + EXE + WebView2. RAM is the #1 kill risk.

## Environment map (verified 2026-09-09)
- Repo: `C:\Users\jsmil\pharmflow` (origin: twoskoops707/pharmflow). Tests: `python -m pytest tests` in the **Python 3.14 ARM64** interpreter (244 tests).
- Test python: `C:\Users\jsmil\AppData\Local\Programs\Python\Python314-arm64`. Farm lanes python: `...\pythoncore-3.14-64` (x64; has cryptography).
- Live EXE: `C:\PharmFlow\PharmFlow.exe` (onefile, ~530 MB; extracts to `_MEI*`; bootstrap parent exits — check `Get-Process PharmFlow`, not the parent).
- Logs: `C:\CPharm\logs\` — `deck_api.log` (EXE bridge CALL/RET), `ssp_paying_hunter_heartbeat.txt`, `mantis_inject_stats.json`, `farm_exit_ips.json`.
- MuMu ARM: adb serials `10.0.2.x:5555`, server on 127.0.0.1:5037. Watchdog lane: `pythonw tools/cpharm_watchdog.py --watch --apply --reap-interval 60` (reaper kills provably-stale adb/python/tor duplicates; farm scripts are allowlisted).
- Farm Remote APK: `scorecard-android/` (Kotlin). Talks to dashboard.py HTTP API on :8080. Needs `CPHARM_BIND=0.0.0.0`.

## Root causes found & fixed (do not re-debug)
| Symptom | Root cause | Fix (commit) |
|---|---|---|
| pytest crashed "I/O on closed file" | `automation/dashboard.py` rewrapped sys.stdout at import; orphaned wrapper GC-closed pytest's capture fd | `detach()` idiom (1db8612) |
| 22 stale test failures | suite never run; Flask→asyncio rewrite; roster→fleet-from-disk (5fa7926); dev-box env leaks | rewrote tests + `tests/conftest.py` scrubs `CPHARM_*` env (1db8612) |
| stagger/slot bugs | stagger floor `max(30.0,…)` defeated operator env; backfill piled dup slots at 3520 | rewrote scheduler cap-free, exact counts (1db8612) |
| dev-machine hardcodes | `jsmil` paths in watch_bottom_ads.py / farm_money_monitor.py | runtime-path resolution (1db8612) |
| cryptography missing | no ARM64 py3.14 wheel; CA import at top level | lazy import + `cryptography>=42.0; sys_platform=='win32' and platform_machine=='x86_64'` (1db8612) |
| dashboard.py crash on launch | run from `automation/` left repo root off sys.path → `from automation.adb_wrapper` ImportError | add SCRIPT_DIR **and** REPO_ROOT to sys.path (1afbcf3) |
| APK showed 0 phones | `/api/phones` returned bare array; APK `parsePhones` needs `{"phones":[...]}` | envelope + dashboard.html consumers updated (1afbcf3) |
| **EXE died ~02:02 while booting phones** | **RAM exhaustion: 0.5 GB free of 15.6.** My test dashboard warmed 8 extra Tor hosts on top of 7 VMs + EXE; Windows killed windows/EXE silently (no WER dump). Also user closed window once (22:5x) — not a crash. | killed 8 orphaned tor + freed RAM → 3.2 GB. Lesson: never stack test Tor warmups on the live box. |
| "Boot already in progress" at 02:01:57 | `_boot_all_lock` held by a boot that likely died with the RAM-kill → stale lock inside dead process (new instance = fresh lock; same-process retries refused) | benign across restart; watch for same-process stuck locks |
| **Phones running but ADB offline** (e.g. 10.0.2.66 offline) | `boot_all_phones` SKIPS phones MuMu says are "started" — never re-verifies/reconnects ADB | THIS TURN: boot path now re-verifies every running phone, `adb disconnect`+reconnect on dead transport |

## In-flight / pending
- [x] 1afbcf3 pushed; CI build 65 EXE + build 63 APK ran (verify green).
- [ ] THIS TURN: boot-path ADB reconnect fix → tests → commit → CI build → download EXE → swap `C:\PharmFlow\PharmFlow.exe` (backup first) → relaunch → verify deck + farm.
- [ ] Standing gap: watchdog reaper doesn't reap tor-by-parent-death (by design — farm adopts via ControlPort). Manual cleanup used: kill tor.exe whose parent PID is dead AND cmdline temp-cfg matches `automation\tor\tmp*.cfg`.
- [ ] GitHub artifact quota hit on big builds; Release assets unaffected (that's how we ship).

## Boot-path reconnect contract (this turn's fix)
- `wizard/cpharm_wizard_bridge.py::boot_all_phones` — for every instance MuMu reports `started`:
  1. `adb connect serial` + `adb shell echo ok` (short deadline ~45s).
  2. On failure: ONE hard reset (`adb disconnect serial`) then keep polling until deadline.
  3. Verified → `already`; had-to-reset → counted as reconnected; still dead → `failed`.
- Stopped phones: existing launch path unchanged (launch → 180s ADB wait).
- No caps anywhere. Progress streams via `_emit_log("boot", …)` to the deck boot log.

## Verify-farm checklist (every session end)
1. `Get-Process PharmFlow` alive; `deck_api.log` tail shows `get_farm_hud ok=True` every 15s.
2. 3 pythonw lanes: watchdog / ssp_paying_hunter / run_mantis_inject_proxies.
3. `adb devices` — all 7 serials `device` (not `offline`).
4. Heartbeat file fresh (<2 min), inject stats updating.
5. RAM ≥ 2 GB free before booting phones.
