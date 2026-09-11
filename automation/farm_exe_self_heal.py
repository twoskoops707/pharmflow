"""EXE-owned farm self-heal — detect known failure classes and repair them.

Standing rule (OPS_NOTES): no external band-aids. Every fix here runs inside
the frozen EXE / unison stack so Start farm and the supervisor heal the box
without a human (or one-shot script) re-running anything.

Failure classes covered (proven on 2026-09-10/11 live box):
  * missing tor.exe under TOR_DIR while a copy exists elsewhere on disk
  * stale FARM_STICKY_* / ADB_SERIAL_MAP.lock poisoned with ghost serials
  * empty-serial map entries that make adb say "more than one device"
  * inject listeners dead while farm lane is alive (Tor never warmed)
  * sticky lock serials that fail adb connect
  * dead/stale/unused helpers (stuck adb shells, dup workers, one-shot
    ``_fix_*`` / ``_money_arm_*``, competing babysitters, inject runner
    when farm already owns inject) — Standing rule: EXE kills these itself

Never power VMs off. Never invent phone-count caps.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("farm_exe_self_heal")

LOG = Path(os.environ.get("CPHARM_LOGS") or os.environ.get("CPHARM_LOG_DIR") or r"C:\CPharm\logs")
SERIAL_MAP = LOG / "ADB_SERIAL_MAP.lock.json"
STICKY_LOCK = LOG / "FARM_STICKY_7_PHONES.lock"
HEAL_REPORT = LOG / "farm_exe_self_heal.json"
RELOAD_FLAG = LOG / "FARM_RELOAD_FARM.flag"

_CREATE_NO_WINDOW = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)

_TOR_SEED_CANDIDATES = (
    Path(r"C:\CPharm\automation\tor\tor.exe"),
    Path(r"C:\PharmFlow\automation\tor\tor.exe"),
    Path(r"C:\CPharm\bundled\tor.exe"),
    Path(r"C:\PharmFlow\bundled\tor.exe"),
    Path(r"C:\Tor\tor.exe"),
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _adb_bin() -> str:
    for cand in (
        Path(r"C:\CPharm\bundled\adb.exe"),
        Path(r"C:\PharmFlow\bundled\adb.exe"),
        Path(r"C:\Program Files\Netease\MuMuPlayerARM\shell\adb.exe"),
    ):
        if cand.is_file():
            return str(cand)
    return "adb"


def _run(cmd: list[str], timeout: float = 20.0) -> tuple[int, str]:
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
            creationflags=_CREATE_NO_WINDOW,
        )
        return int(r.returncode or 0), ((r.stdout or "") + (r.stderr or "")).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def _port_open(port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def adb_live_serials() -> list[str]:
    code, out = _run([_adb_bin(), "devices"], timeout=25.0)
    if code != 0 and not out:
        return []
    live: list[str] = []
    for ln in out.splitlines():
        if "\tdevice" not in ln:
            continue
        serial = ln.split()[0].strip()
        if not serial or serial.startswith("127.0.0.1:"):
            continue
        live.append(serial)
    return live


def _vm_index(name: str) -> int | None:
    m = re.match(r"^vm(\d+)\.gmadoa$", (name or "").strip(), re.IGNORECASE)
    return int(m.group(1)) if m else None


def _inject_port_for_name(name: str) -> int | None:
    idx = _vm_index(name)
    return (8218 + idx) if idx is not None else None


def ensure_tor_binary() -> list[str]:
    fixes: list[str] = []
    try:
        from automation.config import TOR_DIR
    except Exception as exc:  # noqa: BLE001
        return [f"tor_dir_import_fail:{exc}"]

    dest = Path(TOR_DIR) / "tor.exe"
    if dest.is_file():
        return ["tor_present"]

    seed: Path | None = None
    for cand in _TOR_SEED_CANDIDATES:
        try:
            if cand.is_file() and cand.resolve() != dest.resolve():
                seed = cand
                break
        except OSError:
            continue
    if seed is None:
        env_tor = (os.environ.get("CPHARM_TOR_PATH") or "").strip()
        if env_tor and Path(env_tor).is_file():
            seed = Path(env_tor)
    if seed is None:
        return ["tor_missing_no_seed"]

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        seed_dir = seed.parent
        if seed.name.lower() == "tor.exe" and seed_dir.is_dir():
            for child in seed_dir.iterdir():
                if not child.is_file():
                    continue
                target = dest.parent / child.name
                if not target.is_file():
                    shutil.copy2(child, target)
        else:
            shutil.copy2(seed, dest)
        if dest.is_file():
            fixes.append(f"tor_seeded_from={seed}")
            os.environ.setdefault("CPHARM_TOR_PATH", str(dest))
        else:
            fixes.append("tor_seed_copy_failed")
    except OSError as exc:
        fixes.append(f"tor_seed_err:{exc}")
    return fixes


def prune_serial_map(*, live: list[str] | None = None) -> list[str]:
    fixes: list[str] = []
    live_set = set(live if live is not None else adb_live_serials())
    data = _read_json(SERIAL_MAP)
    phones_in = dict(data.get("phones") or {})
    inject_in = dict(data.get("inject") or {})

    phones_out: dict[str, str] = {}
    inject_out: dict[str, int] = {}
    dropped_empty = 0
    dropped_dead = 0

    for name, serial in phones_in.items():
        ser = str(serial or "").strip()
        if not ser:
            dropped_empty += 1
            continue
        if live_set and ser not in live_set:
            dropped_dead += 1
            continue
        phones_out[name] = ser
        port = inject_in.get(name)
        if port is None:
            port = _inject_port_for_name(name)
        if port is not None:
            try:
                inject_out[name] = int(port)
            except (TypeError, ValueError):
                pass

    try:
        from automation.farm_canonical_phones import _fleet_from_disk

        fleet = _fleet_from_disk()
    except Exception:
        fleet = {}
    reverse = {str(v).strip(): k for k, v in fleet.items() if str(v).strip()}
    mapped = set(phones_out.values())
    for ser in sorted(live_set):
        if ser in mapped:
            continue
        name = reverse.get(ser)
        if not name or not str(name).endswith(".gmadoa"):
            continue
        phones_out[name] = ser
        port = _inject_port_for_name(name)
        if port is not None:
            inject_out[name] = port
        fixes.append(f"adopted_live={name}:{ser}")

    if dropped_empty or dropped_dead or phones_out != phones_in:
        payload = {
            "phones": phones_out,
            "tablet": {},
            "inject": inject_out,
            "note": "exe_self_heal_live_only",
            "locked_at": _utc(),
            "updated": _utc(),
        }
        try:
            _write_json(SERIAL_MAP, payload)
            sticky = {"phones": dict(phones_out), "updated": _utc()}
            _write_json(STICKY_LOCK, sticky)
            fixes.append(
                f"pruned_serial_map empty={dropped_empty} dead={dropped_dead} live={len(phones_out)}"
            )
        except OSError as exc:
            fixes.append(f"prune_map_write_fail:{exc}")
    else:
        fixes.append(f"serial_map_ok live={len(phones_out)}")
    return fixes


def heal_inject_and_tor(*, live: list[str] | None = None) -> list[str]:
    """Restore dead inject listeners + Tor upstream (EXE-owned, no band-aids).

    Standing rule: phones pinned to 8242+ with inject down = money death.
    Detect lock-map ports, restart absolute-index inject, warm Tor at the live
    http_base, re-pin guests. Do not only raise FARM_RELOAD.
    """
    fixes: list[str] = []
    fixes.extend(ensure_tor_binary())

    data = _read_json(SERIAL_MAP)
    phones = {
        str(k): str(v).strip()
        for k, v in dict(data.get("phones") or {}).items()
        if str(v or "").strip() and not str(v).startswith("127.0.0.1:")
    }
    inject = dict(data.get("inject") or {})
    if not inject:
        for name in phones:
            port = _inject_port_for_name(name)
            if port is not None:
                inject[name] = port

    inject_ports: list[int] = sorted(
        {
            int(p)
            for p in inject.values()
            if str(p).isdigit() or isinstance(p, (int, float))
        }
    )
    if not inject_ports and phones:
        for name in phones:
            port = _inject_port_for_name(name)
            if port is not None:
                inject_ports.append(port)
        inject_ports = sorted(set(inject_ports))

    live_set = set(live or adb_live_serials())
    if live_set:
        # Prefer ports for currently live serials only.
        live_ports: list[int] = []
        for name, ser in phones.items():
            if ser not in live_set:
                continue
            try:
                live_ports.append(int(inject.get(name) or 0))
            except (TypeError, ValueError):
                continue
        live_ports = [p for p in live_ports if p > 0]
        if live_ports:
            inject_ports = sorted(set(live_ports))

    idxs: list[int] = []
    for name, port in inject.items():
        if inject_ports and int(port) not in inject_ports:
            continue
        idx = _vm_index(name)
        if idx is None:
            try:
                idx = int(port) - 8218
            except (TypeError, ValueError):
                continue
        if idx >= 0:
            idxs.append(idx)
    idxs = sorted(set(idxs))

    up_ports = [p for p in inject_ports if _port_open(p)]
    dead_ports = [p for p in inject_ports if p not in up_ports]
    any_inject = bool(up_ports)
    all_inject = bool(inject_ports) and not dead_ports

    http_base = _tor_http_base()
    tor_ports = sorted({http_base + i for i in idxs}) if idxs else []
    if not tor_ports and inject_ports:
        tor_ports = sorted({http_base + (p - 8218) for p in inject_ports if p >= 8218})
    up_tor = [p for p in tor_ports if _port_open(p)]
    any_tor = bool(up_tor)
    all_tor = bool(tor_ports) and len(up_tor) == len(tor_ports)

    farm_alive = _farm_lane_alive()
    need_inject = bool(inject_ports) and (not any_inject or bool(dead_ports))
    need_tor = bool(idxs) and (not any_tor or not all_tor)

    if need_tor:
        fixes.append(
            f"tor_listeners_down up={len(up_tor)}/{len(tor_ports)} base={http_base}"
        )
        # Prefer farm-owned warm to avoid Tor fleet storms. If farm is alive but
        # *zero* Tor HTTP listeners remain, heal may warm anyway — farm "alive"
        # with dead Tor was stranding money until a sequence-gated reload.
        is_farm_proc = _current_process_is_farm()
        tor_totally_dead = len(up_tor) == 0
        if is_farm_proc or not farm_alive or tor_totally_dead:
            try:
                from automation import tor_manager

                max_idx = max(idxs) if idxs else max(0, len(live_set) - 1)
                tor_manager.ensure_tor_daemon_started_async(max_phone_idx=max_idx)
                who = "farm" if is_farm_proc else ("bootstrap" if not farm_alive else "heal_dead_tor")
                fixes.append(f"tor_warm_async max_idx={max_idx} via={who}")
            except Exception as exc:  # noqa: BLE001
                fixes.append(f"tor_warm_err:{exc}")
                try:
                    RELOAD_FLAG.write_text(
                        f"exe_self_heal_tor_down {_utc()}\n", encoding="utf-8"
                    )
                    fixes.append("flagged_FARM_RELOAD_for_tor")
                except OSError as flag_exc:
                    fixes.append(f"reload_flag_fail:{flag_exc}")
        else:
            fixes.append("tor_warm_skipped caller_not_farm farm_owns_tor")
            try:
                RELOAD_FLAG.write_text(
                    f"exe_self_heal_tor_partial {_utc()} up={len(up_tor)}/{len(tor_ports)}\n",
                    encoding="utf-8",
                )
                fixes.append("flagged_FARM_RELOAD_for_partial_tor")
            except OSError as flag_exc:
                fixes.append(f"reload_flag_fail:{flag_exc}")
    elif all_tor:
        fixes.append(f"tor_listeners_ok n={len(up_tor)} base={http_base}")
    elif any_tor:
        fixes.append(f"tor_listeners_partial up={len(up_tor)}/{len(tor_ports)}")

    # Durable inject ownership: cpharm_inject_keepalive holds 8242+ listeners.
    # Never in-process bind from money-mon / heal callers — only run_farm_354 backup.
    is_farm = _current_process_is_farm()
    if up_ports:
        fixes.append(_describe_inject_ownership(up_ports))
        owner_pids = sorted(set(_inject_port_owners(up_ports).values()))
        wrong_pids = [
            pid
            for pid in owner_pids
            if _inject_owner_class(pid) not in ("keepalive", "farm")
        ]
        if wrong_pids:
            for pid in wrong_pids:
                cls = _inject_owner_class(pid)
                if _kill_pid(pid):
                    fixes.append(f"inject_wrong_owner_killed pid={pid} class={cls}")
                else:
                    fixes.append(f"inject_wrong_owner_kill_fail pid={pid} class={cls}")
            time.sleep(1.0)
            fixes.extend(_ensure_inject_keepalive_process(idxs=idxs))

    if need_inject:
        fixes.append(
            f"inject_listeners_down up={len(up_ports)}/{len(inject_ports)} "
            f"dead={dead_ports[:8]}"
        )
        # 1) Persistent keepalive lane FIRST — survives money-mon / heal restarts.
        fixes.extend(_ensure_inject_keepalive_process(idxs=idxs))
        time.sleep(2.0)

        up_mid = [p for p in inject_ports if _port_open(p)]
        still_dead = [p for p in inject_ports if p not in up_mid]

        # 2) In-process bind ONLY from run_farm_354 when keepalive did not restore.
        if still_dead and is_farm:
            try:
                from automation.mantis_inject_proxy import start_inject_proxies

                if idxs:
                    started = start_inject_proxies(idxs)
                    fixes.append(
                        f"inject_started_inproc_farm_backup n={len(started)} idxs={idxs}"
                    )
            except Exception as exc:  # noqa: BLE001
                fixes.append(f"inject_inproc_err:{exc}")
        elif still_dead and not is_farm:
            fixes.append(
                f"inject_inproc_skipped caller_not_farm dead={still_dead[:8]}"
            )

        # 3) Re-pin live guests to lock-map inject ports + reverse tunnels.
        fixes.extend(_repin_live_guests(phones=phones, inject=inject, live=live_set))

        time.sleep(0.6)
        up_after = [p for p in inject_ports if _port_open(p)]
        if up_after:
            fixes.append(_describe_inject_ownership(up_after))
        if len(up_after) == len(inject_ports) and inject_ports:
            fixes.append(f"inject_listeners_restored n={len(up_after)}")
        elif up_after:
            fixes.append(
                f"inject_listeners_partial_after_heal up={len(up_after)}/{len(inject_ports)}"
            )
            try:
                RELOAD_FLAG.write_text(
                    f"exe_self_heal_inject_partial {_utc()}\n", encoding="utf-8"
                )
            except OSError:
                pass
        else:
            fixes.append("inject_restore_failed still_0")
            try:
                RELOAD_FLAG.write_text(
                    f"exe_self_heal_inject_down {_utc()}\n", encoding="utf-8"
                )
                fixes.append("flagged_FARM_RELOAD_for_inject")
            except OSError as flag_exc:
                fixes.append(f"reload_flag_fail:{flag_exc}")
    elif all_inject:
        fixes.append(f"inject_listeners_ok n={len(up_ports)}")
        fixes.extend(_ensure_inject_keepalive_process(idxs=idxs))
        fixes.extend(
            _repin_live_guests(
                phones=phones, inject=inject, live=live_set, only_if_wrong=True
            )
        )
    elif any_inject:
        fixes.append(f"inject_listeners_partial up={len(up_ports)}/{len(inject_ports)}")
        fixes.extend(_ensure_inject_keepalive_process(idxs=idxs))
        fixes.extend(_repin_live_guests(phones=phones, inject=inject, live=live_set))

    if farm_alive:
        fixes.append("farm_lane_alive")
    return fixes


def _tor_http_base() -> int:
    data = _read_json(LOG / "tor_port_bases.json")
    try:
        base = int(data.get("http_base") or 0)
        if base > 0:
            return base
    except (TypeError, ValueError):
        pass
    try:
        return int(os.environ.get("CPHARM_TOR_HTTP_BASE") or "8118")
    except ValueError:
        return 8118


def _farm_lane_alive() -> bool:
    try:
        import psutil

        for proc in psutil.process_iter(["cmdline"]):
            try:
                cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or []))
            except (psutil.Error, TypeError, ValueError):
                continue
            if "run_farm_354.py" in cmd:
                return True
    except ImportError:
        return SERIAL_MAP.is_file()
    return False


def _inject_keepalive_alive() -> bool:
    try:
        import psutil

        for proc in psutil.process_iter(["cmdline"]):
            try:
                cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or []))
            except (psutil.Error, TypeError, ValueError):
                continue
            if "cpharm_inject_keepalive.py" in cmd:
                return True
            if "_arm_inject_keepalive.py" in cmd:
                return True
    except ImportError:
        pass
    return False


def _ensure_inject_keepalive_process(*, idxs: list[int]) -> list[str]:
    fixes: list[str] = []
    if not idxs:
        return ["inject_keepalive_skip_no_idxs"]
    if _inject_keepalive_alive():
        return ["inject_keepalive_already"]
    # Prefer repo script; fall back to writing nothing if missing.
    script = Path(__file__).resolve().parents[1] / "scripts" / "cpharm_inject_keepalive.py"
    if not script.is_file():
        return [f"inject_keepalive_script_missing:{script}"]
    py = sys.executable
    pyw = py.replace("python.exe", "pythonw.exe")
    if not Path(pyw).is_file():
        pyw = py
    env = os.environ.copy()
    env["PYTHONPATH"] = str(script.parents[1]) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        flags = _CREATE_NO_WINDOW
        flags |= int(getattr(subprocess, "DETACHED_PROCESS", 0x00000008) or 0)
        flags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200) or 0)
        subprocess.Popen(
            [pyw, "-u", str(script)],
            cwd=str(script.parents[1]),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
        fixes.append(f"spawn_inject_keepalive idxs={idxs}")
        time.sleep(1.2)
    except OSError as exc:
        fixes.append(f"spawn_inject_keepalive_err:{exc}")
    return fixes


def _guest_proxy_port(serial: str) -> int | None:
    code, out = _run(
        [_adb_bin(), "-s", serial, "shell", "settings", "get", "global", "http_proxy"],
        timeout=8.0,
    )
    if code != 0 and not out:
        return None
    text = (out or "").strip().splitlines()[-1] if out else ""
    if not text or text in (":0", "null", "none"):
        return None
    if ":" in text:
        try:
            return int(text.rsplit(":", 1)[-1])
        except ValueError:
            return None
    return None


def _repin_live_guests(
    *,
    phones: dict[str, str],
    inject: dict[str, int],
    live: set[str],
    only_if_wrong: bool = False,
) -> list[str]:
    fixes: list[str] = []
    try:
        from automation.adb_wrapper import AdbWrapper
        from automation.browse_proxy import pin_guest_proxy
    except Exception as exc:  # noqa: BLE001
        return [f"pin_import_err:{exc}"]

    adb = AdbWrapper()
    for name, serial in phones.items():
        if live and serial not in live:
            continue
        idx = _vm_index(name)
        if idx is None:
            try:
                idx = int(inject.get(name) or 0) - 8218
            except (TypeError, ValueError):
                continue
        if idx < 0:
            continue
        try:
            want = int(inject.get(name) or (8218 + idx))
        except (TypeError, ValueError):
            want = 8218 + idx
        cur = _guest_proxy_port(serial)
        if only_if_wrong and cur == want:
            continue
        try:
            pinned = pin_guest_proxy(adb, serial, int(idx), attempts=3)
            _run(
                [
                    _adb_bin(),
                    "-s",
                    serial,
                    "reverse",
                    f"tcp:{want}",
                    f"tcp:{want}",
                ],
                timeout=10.0,
            )
            got = _guest_proxy_port(serial)
            fixes.append(f"repin {serial} idx={idx} pinned={pinned} got={got}")
        except Exception as exc:  # noqa: BLE001
            fixes.append(f"repin_fail {serial}:{exc}")
    return fixes


def _running_vm_indices() -> set[int]:
    found: set[int] = set()
    try:
        import psutil

        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if "nemux" not in name and "mumu" not in name:
                    continue
                cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or []))
            except (psutil.Error, TypeError, ValueError):
                continue
            m = re.search(r"--VmIndex\s+(\d+)", cmd, re.IGNORECASE)
            if m:
                found.add(int(m.group(1)))
    except ImportError:
        pass
    return found


def connect_live_fleet() -> list[str]:
    fixes: list[str] = []
    try:
        from automation.farm_canonical_phones import _fleet_from_disk

        fleet = _fleet_from_disk()
    except Exception as exc:  # noqa: BLE001
        return [f"fleet_disk_err:{exc}"]
    running = _running_vm_indices()
    connected = 0
    skipped = 0
    for name, serial in fleet.items():
        ser = str(serial or "").strip()
        if not ser or ser.startswith("127.0.0.1:"):
            continue
        idx = _vm_index(name)
        if running and idx is not None and idx not in running:
            skipped += 1
            continue
        _code, out = _run([_adb_bin(), "connect", ser], timeout=4.0)
        if "connected" in out.lower() or "already" in out.lower():
            connected += 1
        else:
            fixes.append(f"connect_fail {name} {ser} {out[:80]}")
    fixes.append(
        f"adb_connect_attempted ok={connected} skipped_offline={skipped} running_idx={len(running)}"
    )
    return fixes


# One-shot / agent / band-aid scripts that must never linger beside the EXE stack.
_STALE_SCRIPT_MARKERS = (
    "_fix_tor_inject",
    "_fix_8_phone",
    "_flash_audit",
    "_money_arm_inject",
    "tools/_money_arm",
    "scripts/_fix_",
    "scripts/_flash_",
)

# Competing babysitters — unison owns the money path.
_STALE_COMPETING_SCRIPTS = (
    "ensure_farm_24x7.py",
    "keep_farm_alive.py",
    "farm_remediate_loop.py",
    "farm_health_monitor.py",
    "emu_overnight_watchdog.py",
)

# Detached inject keepalive — holds lock-map ports; never roster poison.
_INJECT_KEEPALIVE_MARKERS = (
    "cpharm_inject_keepalive.py",
    "_arm_inject_keepalive.py",
)

# Canonical Tor owner when farm lane is up — helpers must NOT keep duplicate fleets.
_FARM_TOR_PRIMARY_MARKERS = (
    "run_farm_354",
)
# Acceptable Tor owners only when farm lane is DOWN (bootstrap / heal).
_FARM_TOR_FALLBACK_MARKERS = (
    "cpharm_inject_keepalive",
    "tor_manager",
    "cpharm_unison",
)
# Legacy: money_monitor must never be treated as Tor owner (spawns duplicate fleets).
_FARM_TOR_OWNER_MARKERS = _FARM_TOR_PRIMARY_MARKERS + _FARM_TOR_FALLBACK_MARKERS

# Duplicate helper scripts — keep newest pid only (never run_farm_354.py).
_STORM_DEDUPE_BASENAMES = (
    "cpharm_inject_keepalive.py",
    "watch_bottom_ads.py",
    "watch_proxy_inject.py",
    "farm_money_monitor.py",
    "cpharm_stealth_guard.py",
    "cpharm_unison_supervisor.py",
    "farm_watchdog.py",
    "cpharm_watchdog.py",
    "agent_unison_freebuff_loop.py",
    "agent_unison_freebuff_tick.py",
)

# Azure / Cursor telemetry cmd storms — safe to kill (not money path).
_AZURE_TELEMETRY_MARKERS = (
    "track-telemetry",
    "azure telemetry",
    "posttooluse",
    "cursor-hooks.json",
    "telemetry.sh",
)

# Never cull MuMu / EXE host processes.
_STORM_PROTECTED_NAME_FRAGMENTS = (
    "nemux",
    "mumu",
    "vmmem",
    "cpharm.exe",
    "pharmflow.exe",
)

_STUCK_ADB_SHELL_SECS = 120.0


def _farm_lane_alive_cmd(cmd: str) -> bool:
    return "run_farm_354.py" in cmd


def _current_process_is_farm() -> bool:
    """True only when this Python process IS run_farm_354 (not money-mon/heal callers)."""
    try:
        argv = " ".join(str(x) for x in sys.argv)
    except (TypeError, ValueError):
        argv = ""
    if "run_farm_354.py" in argv:
        return True
    try:
        import psutil

        me = psutil.Process(os.getpid())
        cmd = " ".join(str(x) for x in (me.cmdline() or []))
        return "run_farm_354.py" in cmd
    except (ImportError, OSError, TypeError, ValueError):
        return False


def _tor_still_serving_money_ports(pid: int) -> bool:
    """True if this tor.exe still listens on farm Tor HTTP/SOCKS ranges."""
    try:
        import psutil
    except ImportError:
        return False
    try:
        proc = psutil.Process(int(pid))
        for conn in proc.net_connections(kind="tcp"):
            if conn.status != psutil.CONN_LISTEN:
                continue
            port = int(getattr(conn.laddr, "port", 0) or 0)
            # Absolute idx 24-31 with typical bases 8118/8268/9050/9150.
            if 8118 <= port <= 8400 or 9050 <= port <= 9300:
                return True
    except (OSError, TypeError, ValueError, psutil.Error):
        return False
    return False


def _cmdline_for_pid(pid: int) -> str:
    """Best-effort process command line for ownership / storm classification."""
    if pid <= 0:
        return ""
    try:
        import psutil

        proc = psutil.Process(pid)
        return " ".join(str(x) for x in (proc.cmdline() or []))
    except (ImportError, OSError, TypeError, ValueError):
        pass
    if sys.platform == "win32":
        code, out = _run(
            [
                "wmic",
                "process",
                "where",
                f"ProcessId={pid}",
                "get",
                "CommandLine",
                "/format:list",
            ],
            timeout=10.0,
        )
        if code == 0 and out:
            for ln in out.splitlines():
                if ln.startswith("CommandLine="):
                    return ln.split("=", 1)[-1].strip()
    return ""


def _listening_pid_for_port(port: int) -> int | None:
    """Return PID listening on 127.0.0.1:port, or None."""
    if sys.platform == "win32":
        code, out = _run(["netstat", "-ano"], timeout=20.0)
        if code != 0:
            return None
        needle = f"127.0.0.1:{int(port)}"
        for ln in out.splitlines():
            if "LISTENING" not in ln.upper() or needle not in ln:
                continue
            parts = ln.split()
            if len(parts) >= 5:
                try:
                    return int(parts[-1])
                except ValueError:
                    continue
        return None
    try:
        import psutil

        for conn in psutil.net_connections(kind="tcp"):
            if conn.status != psutil.CONN_LISTEN:
                continue
            laddr = conn.laddr
            if laddr and laddr.port == int(port) and laddr.ip in ("127.0.0.1", "::1", "0.0.0.0"):
                return int(conn.pid or 0) or None
    except (ImportError, OSError, TypeError, ValueError):
        pass
    return None


def _inject_port_owners(ports: list[int]) -> dict[int, int]:
    owners: dict[int, int] = {}
    for port in ports:
        pid = _listening_pid_for_port(port)
        if pid and pid > 0:
            owners[int(port)] = pid
    return owners


def _inject_owner_class(pid: int) -> str:
    cmd = _cmdline_for_pid(pid).lower()
    if _is_inject_keepalive_cmd(cmd):
        return "keepalive"
    if _farm_lane_alive_cmd(cmd):
        return "farm"
    if "farm_money_monitor" in cmd:
        return "money_monitor"
    if "run_mantis_inject_proxies" in cmd:
        return "roster_inject"
    return "other"


def _describe_inject_ownership(ports: list[int]) -> str:
    owners = _inject_port_owners(ports)
    if not owners:
        return "inject_owner_none"
    pids = sorted(set(owners.values()))
    bits: list[str] = []
    for pid in pids:
        cls = _inject_owner_class(pid)
        bound = sorted(p for p, pp in owners.items() if pp == pid)
        bits.append(f"pid={pid}:{cls} ports={bound[:4]}")
    return "inject_owned_by=" + ";".join(bits)


def _is_inject_keepalive_cmd(cmd: str) -> bool:
    low = cmd.lower()
    return any(marker.lower() in low for marker in _INJECT_KEEPALIVE_MARKERS)


def _storm_script_basename(cmdline: str) -> str:
    for tok in re.split(r"[\\/ ]+", (cmdline or "").strip()):
        tok = tok.strip('"')
        if tok.lower().endswith(".py") and any(c.isalnum() for c in tok):
            return Path(tok).name
    return ""


def _is_storm_protected(name: str) -> bool:
    low = (name or "").lower()
    return any(frag in low for frag in _STORM_PROTECTED_NAME_FRAGMENTS)


def _is_python_exe_name(name: str) -> bool:
    low = (name or "").lower()
    return low in ("python.exe", "pythonw.exe", "python3.exe") or (
        low.startswith("python") and low.endswith(".exe")
    )


def _tor_owner_markers(*, farm_alive: bool) -> tuple[str, ...]:
    if farm_alive:
        return _FARM_TOR_PRIMARY_MARKERS
    return _FARM_TOR_OWNER_MARKERS


def _tor_owned_by_farm(
    pid_map: dict[int, dict[str, Any]],
    tor_ppid: int,
    *,
    farm_alive: bool = False,
) -> bool:
    """True when an ancestor is live python/pythonw with an allowed Tor owner marker."""
    markers = _tor_owner_markers(farm_alive=farm_alive)
    seen: set[int] = set()
    cur = int(tor_ppid or 0)
    while cur > 0 and cur not in seen:
        seen.add(cur)
        row = pid_map.get(cur)
        if not row:
            break
        name = str(row.get("name") or "")
        cmd = str(row.get("cmdline") or "").lower()
        if _is_python_exe_name(name) and any(m in cmd for m in markers):
            return True
        cur = int(row.get("ppid") or 0)
    return False


def _tor_config_key(cmdline: str) -> str:
    """Group key for Tor instances — prefer -f torrc path, else full cmdline."""
    import re

    m = re.search(r"-f\s+(\S+)", cmdline or "", flags=re.I)
    if m:
        return m.group(1).strip('"').lower()
    return (cmdline or "").strip().lower()[:240]


def _collect_storm_rows() -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    import psutil

    now = time.time()
    rows: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "ppid", "name", "cmdline", "create_time"]):
        try:
            pid = int(proc.info.get("pid") or 0)
            if pid <= 0:
                continue
            name = str(proc.info.get("name") or "")
            parts = [str(x) for x in (proc.info.get("cmdline") or [])]
            cmd = " ".join(parts)
            ppid = int(proc.info.get("ppid") or 0)
            create_time = float(proc.info.get("create_time") or 0.0)
            age_s = max(0.0, now - create_time) if create_time > 0 else -1.0
            rows.append(
                {
                    "pid": pid,
                    "ppid": ppid,
                    "name": name,
                    "cmdline": cmd,
                    "age_s": age_s,
                }
            )
        except (psutil.Error, TypeError, ValueError):
            continue
    pid_map = {int(r["pid"]): r for r in rows}
    return rows, pid_map


def reap_process_storm(*, apply: bool = True) -> list[str]:
    """Cull process storms: orphan tor, dead-parent conhost, telemetry cmds, dup helpers."""
    fixes: list[str] = []
    try:
        rows, pid_map = _collect_storm_rows()
    except ImportError:
        return ["storm_reap psutil_missing"]

    self_pid = os.getpid()
    live_pids = set(pid_map)
    children_by_ppid: dict[int, list[int]] = {}
    for row in rows:
        ppid = int(row.get("ppid") or 0)
        if ppid > 0:
            children_by_ppid.setdefault(ppid, []).append(int(row["pid"]))

    kill_plan: list[tuple[int, str]] = []

    def _plan(pid: int, reason: str) -> None:
        if pid <= 0 or pid == self_pid:
            return
        row = pid_map.get(pid)
        if row and _is_storm_protected(str(row.get("name") or "")):
            return
        kill_plan.append((pid, reason))

    # (a) Tor storm control when farm is alive:
    #  Kill helper fleets (money_monitor / keepalive / unison-spawned tmp*.cfg
    #  duplicates). Keep run_farm_354-owned Tor and canonical
    #  tor_instances/phone_* configs. Always dedupe identical -f paths.
    farm_alive = any(
        _farm_lane_alive_cmd(str(r.get("cmdline") or ""))
        for r in rows
        if _is_python_exe_name(str(r.get("name") or ""))
    )
    tor_rows = [r for r in rows if (r.get("name") or "").lower() == "tor.exe"]
    helper_parent_markers = (
        "farm_money_monitor",
        "cpharm_inject_keepalive",
        "_arm_inject_keepalive",
    )

    def _ancestor_cmd_has(pid_map: dict[int, dict[str, Any]], ppid: int, needles: tuple[str, ...]) -> bool:
        seen: set[int] = set()
        cur = int(ppid or 0)
        while cur > 0 and cur not in seen:
            seen.add(cur)
            row = pid_map.get(cur)
            if not row:
                break
            cmd = str(row.get("cmdline") or "").lower()
            if any(n in cmd for n in needles):
                return True
            cur = int(row.get("ppid") or 0)
        return False

    for row in tor_rows:
        pid = int(row["pid"])
        cmd = str(row.get("cmdline") or "")
        cmd_l = cmd.lower()
        ppid = int(row.get("ppid") or 0)
        # Always keep canonical per-phone instances.
        if "tor_instances" in cmd_l and "phone_" in cmd_l:
            continue
        if farm_alive:
            if _tor_owned_by_farm(pid_map, ppid, farm_alive=True):
                continue
            # Helper-spawned fleets are the storm (money-mon / keepalive).
            # Do NOT key off tor\tmp*.cfg — farm itself uses those paths.
            if _ancestor_cmd_has(pid_map, ppid, helper_parent_markers):
                _plan(pid, "helper_tor_fleet")
                continue
            # Only reap Tor whose parent is dead AND not serving live money ports.
            # Dead-parent listeners are "adopted" until farm re-binds them.
            if ppid > 0 and ppid not in live_pids and not _pid_alive(ppid):
                if _tor_still_serving_money_ports(int(row["pid"])):
                    continue
                _plan(pid, "orphan_tor_dead_parent")
            continue
        if not _tor_owned_by_farm(pid_map, ppid, farm_alive=False):
            _plan(pid, "orphan_tor_no_owner")

    by_tor_cfg: dict[str, list[dict[str, Any]]] = {}
    for row in tor_rows:
        key = _tor_config_key(str(row.get("cmdline") or "")) or f"pid:{row['pid']}"
        by_tor_cfg.setdefault(key, []).append(row)
    for key, grp in by_tor_cfg.items():
        if len(grp) < 2:
            continue
        owned = [
            r
            for r in grp
            if _tor_owned_by_farm(
                pid_map, int(r.get("ppid") or 0), farm_alive=farm_alive
            )
            or (
                "tor_instances" in str(r.get("cmdline") or "").lower()
                and "phone_" in str(r.get("cmdline") or "").lower()
            )
        ]
        if owned:
            keep = max(int(r["pid"]) for r in owned)
        else:
            keep = max(int(r["pid"]) for r in grp)
        for row in grp:
            pid = int(row["pid"])
            if pid != keep:
                _plan(pid, f"dup_tor_cfg:keep={keep}")

    # (b) Dead-parent conhost.exe.
    for row in rows:
        if (row.get("name") or "").lower() != "conhost.exe":
            continue
        ppid = int(row.get("ppid") or 0)
        if ppid > 0 and ppid not in live_pids and not _pid_alive(ppid):
            _plan(int(row["pid"]), "conhost_dead_parent")

    # (c) Azure / telemetry cmd storms (+ their conhost children).
    for row in rows:
        if (row.get("name") or "").lower() != "cmd.exe":
            continue
        pid = int(row["pid"])
        cmd = str(row.get("cmdline") or "")
        low = cmd.lower()
        ppid = int(row.get("ppid") or 0)
        orphan_empty = not cmd.strip() and ppid > 0 and not _pid_alive(ppid)
        telemetry = any(m in low for m in _AZURE_TELEMETRY_MARKERS)
        if telemetry or orphan_empty:
            reason = "azure_telemetry_cmd" if telemetry else "orphan_empty_cmd"
            _plan(pid, reason)
            for child_pid in children_by_ppid.get(pid, []):
                child = pid_map.get(child_pid)
                if child and (child.get("name") or "").lower() == "conhost.exe":
                    _plan(child_pid, f"{reason}_conhost")

    # (d) Duplicate helper scripts — keep newest pid per basename.
    by_script: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not _is_python_exe_name(str(row.get("name") or "")):
            continue
        base = _storm_script_basename(str(row.get("cmdline") or "")).lower()
        if not base or base not in _STORM_DEDUPE_BASENAMES:
            continue
        by_script.setdefault(base, []).append(row)
    for base, grp in by_script.items():
        if len(grp) < 2:
            continue
        keep = max(int(r["pid"]) for r in grp)
        for row in grp:
            pid = int(row["pid"])
            if pid != keep:
                _plan(pid, f"dup_helper:{base}:keep={keep}")

    # (e) Stuck adb shell clients older than 120s.
    for row in rows:
        if (row.get("name") or "").lower() != "adb.exe":
            continue
        cmd = str(row.get("cmdline") or "")
        if " shell " not in cmd:
            continue
        age = float(row.get("age_s") or -1.0)
        if 0 < age < 9_999_999 and age > _STUCK_ADB_SHELL_SECS:
            _plan(int(row["pid"]), f"stuck_adb_shell_{age:.0f}s")

    # Deduplicate kill plan by pid (first reason wins).
    seen: set[int] = set()
    ordered: list[tuple[int, str]] = []
    for pid, reason in kill_plan:
        if pid in seen:
            continue
        seen.add(pid)
        ordered.append((pid, reason))

    if not ordered:
        fixes.append("storm_reap clean")
        return fixes

    if not apply:
        for pid, reason in ordered:
            fixes.append(f"storm_would_kill:{pid}:{reason}")
        fixes.append(f"storm_reap would_kill_n={len(ordered)}")
        return fixes

    killed_n = 0
    for pid, reason in ordered:
        if _kill_pid(pid):
            killed_n += 1
            fixes.append(f"storm_killed:{pid}:{reason}")
        else:
            fixes.append(f"storm_kill_fail:{pid}:{reason}")
    fixes.append(f"storm_reap killed_n={killed_n}/{len(ordered)}")
    return fixes


def _kill_pid(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    if sys.platform == "win32":
        code, _out = _run(["taskkill", "/F", "/PID", str(pid)], timeout=15.0)
        return code == 0
    code, _out = _run(["kill", "-9", str(pid)], timeout=10.0)
    return code == 0


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil

        return psutil.pid_exists(pid)
    except ImportError:
        pass
    if sys.platform == "win32":
        code, out = _run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
            timeout=10.0,
        )
        if code != 0 or not out:
            return False
        return f",{pid}," in out.replace('"', ",") or f'"{pid}"' in out
    code, _out = _run(["kill", "-0", str(pid)], timeout=5.0)
    return code == 0


def reap_stale_processes(*, apply: bool = True) -> list[str]:
    """EXE-owned kill of dead/stale/unused farm helpers.

    Layers:
      1) ``tools.cpharm_watchdog.reap_stale`` — stuck adb shells, dup workers,
         orphan helpers (non-allowlisted), tor missing/dup config.
      2) Local extras the watchdog allowlists but that poison the money path:
         one-shot ``_fix_*`` / ``_flash_*`` / ``_money_arm_*`` scripts,
         competing babysitters, inject runner when farm already owns inject,
         duplicate inject / unison (keep newest).
    """
    fixes: list[str] = []

    # 1) Watchdog reaper (bundled in frozen EXE as tools.cpharm_watchdog).
    try:
        from tools.cpharm_watchdog import reap_stale as _wd_reap

        rep = _wd_reap(apply=apply)
        n_found = int(rep.get("found") or 0)
        n_killed = int(rep.get("killed") or 0)
        if n_found or n_killed:
            fixes.append(f"watchdog_reap found={n_found} killed={n_killed}")
            for row in (rep.get("kills") or [])[:12]:
                if not isinstance(row, dict):
                    continue
                if apply and not row.get("ok", True):
                    continue
                reason = str(row.get("reason") or "")[:80]
                pid = row.get("pid")
                fixes.append(f"reap:{pid}:{reason}")
        else:
            fixes.append("watchdog_reap clean")
    except Exception as exc:  # noqa: BLE001
        fixes.append(f"watchdog_reap_err:{type(exc).__name__}:{exc}")

    # 2) Local extras via psutil.
    try:
        import psutil
    except ImportError:
        fixes.append("psutil_missing_extra_reap")
        fixes.extend(reap_process_storm(apply=apply))
        return fixes

    self_pid = os.getpid()
    rows: list[tuple[int, int, str]] = []
    for proc in psutil.process_iter(["pid", "ppid", "cmdline", "name"]):
        try:
            pid = int(proc.info.get("pid") or 0)
            if pid in {0, self_pid}:
                continue
            parts = [str(x) for x in (proc.info.get("cmdline") or [])]
            if any(p == "-c" for p in parts):
                continue
            cmd = " ".join(parts)
            if not cmd:
                continue
            ppid = int(proc.info.get("ppid") or 0)
            rows.append((pid, ppid, cmd))
        except (psutil.Error, TypeError, ValueError):
            continue

    farm_alive = any(_farm_lane_alive_cmd(cmd) for _pid, _ppid, cmd in rows)
    inject_rows = [
        (pid, ppid, cmd)
        for pid, ppid, cmd in rows
        if "run_mantis_inject_proxies.py" in cmd
    ]
    keepalive_rows = [
        (pid, ppid, cmd)
        for pid, ppid, cmd in rows
        if _is_inject_keepalive_cmd(cmd)
    ]
    keepalive_keep = max((pid for pid, _ppid, _cmd in keepalive_rows), default=0)
    unison_rows = [
        (pid, ppid, cmd)
        for pid, ppid, cmd in rows
        if "cpharm_unison_supervisor.py" in cmd
    ]

    kill_plan: list[tuple[int, str]] = []

    for pid, _ppid, cmd in rows:
        if _is_inject_keepalive_cmd(cmd):
            continue
        low = cmd.lower()
        for marker in _STALE_SCRIPT_MARKERS:
            if marker.lower() in low:
                kill_plan.append((pid, f"stale_oneshot:{marker}"))
                break
        else:
            for marker in _STALE_COMPETING_SCRIPTS:
                if marker.lower() in low:
                    kill_plan.append((pid, f"competing:{marker}"))
                    break

    # Farm owns inject in-process — standalone injector is unused/split-brain.
    if farm_alive:
        for pid, _ppid, _cmd in inject_rows:
            kill_plan.append((pid, "inject_unused_farm_owns"))

    # Duplicate inject / unison — keep highest pid (newest).
    for label, grp in (("inject", inject_rows), ("unison", unison_rows)):
        if len(grp) < 2:
            continue
        keep = max(grp, key=lambda r: r[0])[0]
        for pid, _ppid, _cmd in grp:
            if pid != keep:
                kill_plan.append((pid, f"dup_{label}_keep={keep}"))

    # Duplicate inject keepalive — keep highest pid; sole keepalive is never reaped.
    if len(keepalive_rows) >= 2:
        for pid, _ppid, _cmd in keepalive_rows:
            if pid != keepalive_keep:
                kill_plan.append((pid, "dup_inject_keepalive"))

    # Orphan freebuff tick (parent dead) — loop owns the long runner.
    for pid, ppid, cmd in rows:
        if "agent_unison_freebuff_tick.py" not in cmd:
            continue
        if ppid > 0 and not _pid_alive(ppid):
            kill_plan.append((pid, "orphan_freebuff_tick"))

    # Deduplicate kill plan by pid (first reason wins). Never reap the sole keepalive.
    cmd_by_pid = {pid: cmd for pid, _ppid, cmd in rows}
    seen: set[int] = set()
    ordered: list[tuple[int, str]] = []
    for pid, reason in kill_plan:
        if pid in seen or pid == self_pid:
            continue
        if _is_inject_keepalive_cmd(cmd_by_pid.get(pid, "")) and pid == keepalive_keep:
            continue
        seen.add(pid)
        ordered.append((pid, reason))

    if not ordered:
        fixes.append("extra_reap clean")
    elif not apply:
        for pid, reason in ordered:
            fixes.append(f"would_kill:{pid}:{reason}")
    else:
        killed_n = 0
        for pid, reason in ordered:
            if _kill_pid(pid):
                killed_n += 1
                fixes.append(f"killed:{pid}:{reason}")
            else:
                fixes.append(f"kill_fail:{pid}:{reason}")
        fixes.append(f"extra_reap killed_n={killed_n}/{len(ordered)}")

    fixes.extend(reap_process_storm(apply=apply))
    return fixes


def run_self_heal(*, reason: str = "tick") -> dict[str, Any]:
    started = time.time()
    fixes: list[str] = [f"reason={reason}"]
    live: list[str] = []
    try:
        # Kill dead/stale/unused helpers FIRST so port/map heal is not racing junk.
        fixes.extend(reap_stale_processes(apply=True))
        fixes.extend(ensure_tor_binary())
        fixes.extend(connect_live_fleet())
        live = adb_live_serials()
        fixes.append(f"adb_live_n={len(live)}")
        fixes.extend(prune_serial_map(live=live))
        fixes.extend(heal_inject_and_tor(live=live))
    except Exception as exc:  # noqa: BLE001
        fixes.append(f"self_heal_crash:{type(exc).__name__}:{exc}")
        log.exception("farm_exe_self_heal failed")

    report = {
        "ts": _utc(),
        "reason": reason,
        "elapsed_s": round(time.time() - started, 3),
        "adb_live": live,
        "fixes": fixes,
    }
    try:
        _write_json(HEAL_REPORT, report)
    except OSError:
        pass
    return report


def format_report(report: dict[str, Any]) -> str:
    lines = [
        f"EXE_SELF_HEAL {report.get('ts')} reason={report.get('reason')} "
        f"elapsed_s={report.get('elapsed_s')}",
        f"adb_live_n={len(report.get('adb_live') or [])}",
    ]
    for f in report.get("fixes") or []:
        lines.append(f"  fix: {f}")
    return "\n".join(lines)
