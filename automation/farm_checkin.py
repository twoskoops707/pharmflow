"""Farm check-in snapshot + ntfy body format.

Operator wants ntfy digests that look like a live check-in, plus separate
FIX messages when monitoring repairs something.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from automation.adb_wrapper import AdbWrapper
from automation.browse_proxy import (
    browse_proxy_mode,
    expected_guest_proxy,
    guest_proxy_healthy,
    resolve_browser_package,
    skips_mitm,
)
from automation.pharmflow_exe_owned import exe_owns_farm
from automation.process_scan import pids_matching

DEFAULT_TOPIC = "twskoops"
LOG_DIR = Path(r"C:\PharmFlow\logs")
PROGRESS = LOG_DIR / "farm_354_progress.json"
RESULTS = LOG_DIR / "farm_354_results.jsonl"
FARM_LOG = LOG_DIR / "farm_354.log"
MANTIS_TODAY = LOG_DIR / "mantis_today_state.json"
NTFY_THROTTLE = LOG_DIR / "ntfy_throttle.json"
# Hard cap: at most one outbound ntfy to twskoops every 2 hours (unless force=True).
NTFY_MIN_INTERVAL_S = int(os.environ.get("PHARMFLOW_NTFY_MIN_INTERVAL_S", "7200") or "7200")

_START_RE = re.compile(r"START\s+(\d+)\s+phones")
_ONLINE_RE = re.compile(r"ONLINE (vm\d+\.gmadoa)")

# Path1/2 stems carry a browser tag; Path3 (ad) stems are untagged and always Chromium.
_BROWSER_TAGS = ("duckduckgo", "chromium", "firefox", "brave", "opera")
_BROWSER_SHORT = {
    "duckduckgo": "ddg",
    "chromium": "chrome",
    "firefox": "ff",
    "brave": "brave",
    "opera": "opera",
}


def browser_of_stem(stem: str) -> str:
    low = str(stem).lower()
    for tag in _BROWSER_TAGS:
        if f"_{tag}_" in low or low.endswith(f"_{tag}"):
            return tag
    return "chromium"


def summarize_browsers(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """{browser: {ok, fail}} from farm result rows."""
    out: dict[str, dict[str, int]] = {}
    for row in rows:
        stem = str(row.get("sequence") or Path(str(row.get("path") or "")).stem)
        if not stem:
            continue
        bucket = out.setdefault(browser_of_stem(stem), {"ok": 0, "fail": 0})
        bucket["ok" if row.get("success") else "fail"] += 1
    return out


@dataclass
class FarmCheckin:
    farm_up: bool = False
    farm_pids: list[int] = field(default_factory=list)
    start_phones: int = 0
    adb_online: int = 0
    adb_serials: list[str] = field(default_factory=list)
    online_names: list[str] = field(default_factory=list)
    expect_phones: int = 5
    cycle_ran: int = 0
    cycle_ok: int = 0
    cycle_fail: int = 0
    path3_clicks: int = 0
    ip_switches: int = 0
    per_phone_done: dict[str, int] = field(default_factory=dict)
    proxies_ok: int = 0
    proxies_total: int = 0
    proxy_bad: list[str] = field(default_factory=list)
    browsers: dict[str, dict[str, int]] = field(default_factory=dict)
    deadline_utc: datetime | None = None
    hours: float = 0.0
    day_mode: bool = True
    verdict: str = "unknown"
    fixes: list[str] = field(default_factory=list)
    note: str = ""
    # Today's Mantis pull (Pacific day) — from mantis_today_state.json.
    mantis_payout_usd: float | None = None
    mantis_impressions: int | None = None
    mantis_clicks: int | None = None
    mantis_ecpm: float | None = None
    mantis_updated: str = ""
    mantis_available: bool = False

    @property
    def healthy(self) -> bool:
        return (
            self.farm_up
            and self.adb_online >= max(1, self.start_phones or self.expect_phones)
            and self.cycle_fail == 0
            and not self.proxy_bad
        )


def _topic() -> str:
    return os.environ.get("PHARMFLOW_NTFY_TOPIC", DEFAULT_TOPIC).strip() or DEFAULT_TOPIC


def _ntfy_url() -> str:
    return f"https://ntfy.sh/{_topic()}"


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if text.lower() in {"midnight-daily", "midnight", "day", "24h"}:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_day_mode(prog: dict[str, Any]) -> bool:
    if bool(prog.get("day_mode")):
        return True
    try:
        hours = float(prog.get("hours") if prog.get("hours") is not None else 0)
    except (TypeError, ValueError):
        hours = 0.0
    deadline = prog.get("deadline")
    if isinstance(deadline, str) and deadline.strip().lower() in {
        "midnight-daily",
        "midnight",
        "day",
        "24h",
    }:
        return True
    return hours <= 0


def _local_midnight_utc() -> datetime:
    now = datetime.now().astimezone()
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc)


def _today_local_start_ts() -> float:
    now = datetime.now().astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp()


def _pharmflow_exe_pids() -> list[int]:
    """PharmFlow/PharmFlow.exe PIDs — GUI alone is not proof the farm is running."""
    try:
        import psutil

        out: list[int] = []
        names = {"pharmflow.exe", "pharmflow.exe"}
        for proc in psutil.process_iter(["pid", "name"]):
            if str(proc.info.get("name") or "").lower() in names:
                out.append(int(proc.info["pid"]))
        return out
    except Exception:
        return []


def _progress_fresh(max_age_s: float = 180.0) -> bool:
    """True when progress.json is recent or has active sequences (EXE in-process farm)."""
    prog = _progress()
    if not prog:
        return False
    if prog.get("active_sequences") or prog.get("active_keys"):
        return True
    ts = _parse_ts(str(prog.get("updated") or ""))
    if ts is None:
        return False
    return (time.time() - ts.timestamp()) <= max_age_s


def _farm_pids() -> list[int]:
    try:
        # Either python worker counts as UP: 354 can exit after --hours while
        # cycles --forever keeps going.
        pids = pids_matching(("run_farm_354.py", "run_farm_cycles.py"))
        if pids:
            return pids
        # EXE-owned farm (1.4.1+): require ownership flag or fresh progress —
        # an idle PharmFlow/PharmFlow window must not report farm UP.
        exe_pids = _pharmflow_exe_pids()
        if exe_pids and (exe_owns_farm() or _progress_fresh()):
            return exe_pids
        return []
    except Exception:
        exe_pids = _pharmflow_exe_pids()
        if exe_pids and (exe_owns_farm() or _progress_fresh()):
            return exe_pids
        return []


def _adb_devices() -> list[str]:
    adb = os.environ.get("PHARMFLOW_ADB") or r"C:\PharmFlow\bundled\adb.exe"
    try:
        from automation.win_subprocess import hidden_run_kwargs

        out = subprocess.check_output(
            [adb, "devices"],
            text=True,
            timeout=20,
            **hidden_run_kwargs(),
        )
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return []
    serials: list[str] = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("List"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def _last_start_phones() -> tuple[int, list[str]]:
    if not FARM_LOG.is_file():
        return 0, []
    try:
        lines = FARM_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-600:]
    except OSError:
        return 0, []
    start_idx = None
    start_n = 0
    for i in range(len(lines) - 1, -1, -1):
        m = _START_RE.search(lines[i])
        if m:
            start_idx = i
            start_n = int(m.group(1))
            break
    if start_idx is None:
        return 0, []
    names: list[str] = []
    for line in lines[max(0, start_idx - 30) : start_idx]:
        m = _ONLINE_RE.search(line)
        if m and m.group(1) not in names:
            names.append(m.group(1))
    return start_n, names


def _progress() -> dict[str, Any]:
    if not PROGRESS.is_file():
        return {}
    try:
        return json.loads(PROGRESS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _cycle_stats_from_progress(prog: dict[str, Any]) -> tuple[int, int, int, int, int, dict[str, int]]:
    """Prefer progress.json last-rows; fall back to results since deadline-hours."""
    phones = prog.get("phones") or {}
    per: dict[str, int] = {}
    ran = ok = fail = path3 = ip_sw = 0
    for name, blob in phones.items():
        short = str(name).split(".")[0]
        if isinstance(blob, dict):
            done = int(blob.get("done") or 0)
            per[short] = done
            ran += done
            last = blob.get("last") or {}
            if isinstance(last, dict):
                if last.get("success") is True:
                    ok += 1
                elif last.get("success") is False:
                    fail += 1
                if last.get("path3") and last.get("success"):
                    path3 += 1
                if last.get("ip_changed"):
                    ip_sw += 1
        else:
            per[short] = int(blob or 0)
            ran += int(blob or 0)
    # Enrich from results since local midnight (day mode) or cycle start.
    day_mode = _is_day_mode(prog)
    deadline = _parse_ts(prog.get("deadline"))
    hours = float(prog.get("hours") or 0.0)
    since = None
    if day_mode:
        since = _today_local_start_ts()
    elif deadline:
        since = deadline.timestamp() - max(hours, 0.01) * 3600.0
    r_ok = r_fail = r_p3 = r_ip = r_ran = 0
    if RESULTS.is_file() and since is not None:
        try:
            with RESULTS.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = _parse_ts(row.get("time"))
                    if ts is None or ts.timestamp() < since:
                        continue
                    r_ran += 1
                    if row.get("success"):
                        r_ok += 1
                    else:
                        r_fail += 1
                    if row.get("path3") and row.get("success"):
                        r_p3 += 1
                    if row.get("ip_changed"):
                        r_ip += 1
        except OSError:
            pass
    if r_ran > 0:
        return r_ran, r_ok, r_fail, r_p3, r_ip, per
    # Approximate OK from done counts when results empty
    return ran, ran, 0, path3, ip_sw, per


def _rows_since(since: float | None) -> list[dict[str, Any]]:
    if not RESULTS.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with RESULTS.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = _parse_ts(row.get("time"))
                if since is not None and (ts is None or ts.timestamp() < since):
                    continue
                rows.append(row)
    except OSError:
        return []
    return rows


def _cycle_window_start(prog: dict[str, Any]) -> float | None:
    if _is_day_mode(prog):
        return _today_local_start_ts()
    deadline = _parse_ts(prog.get("deadline"))
    if deadline is None:
        return None
    return deadline.timestamp() - float(prog.get("hours") or 0.0) * 3600.0


def _pacific_today() -> str:
    """Pacific calendar date — matches Mantis DAY buckets / mantis_today_state.json."""
    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


def _load_mantis_today() -> dict[str, Any]:
    """Freshest today's Mantis stats from pull_today / autopilot state file.

    Returns empty dict when missing or not Pacific-today (do not invent numbers).
    """
    if not MANTIS_TODAY.is_file():
        return {}
    try:
        raw = json.loads(MANTIS_TODAY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    if str(raw.get("date") or "") != _pacific_today():
        return {}
    out: dict[str, Any] = {"available": True}
    try:
        out["impressions"] = max(0, int(raw.get("impressions") or 0))
    except (TypeError, ValueError):
        out["impressions"] = 0
    try:
        out["clicks"] = max(0, int(raw.get("clicks") or 0))
    except (TypeError, ValueError):
        out["clicks"] = 0
    try:
        out["payout_usd"] = float(raw.get("payout_usd") or 0)
    except (TypeError, ValueError):
        out["payout_usd"] = 0.0
    try:
        out["ecpm"] = float(raw.get("ecpm") or 0)
    except (TypeError, ValueError):
        out["ecpm"] = 0.0
    # Derive eCPM when pull has $ + impr but ecpm left at 0.
    if out["ecpm"] <= 0 and out["impressions"] > 0 and out["payout_usd"] > 0:
        out["ecpm"] = out["payout_usd"] * 1000.0 / out["impressions"]
    out["updated"] = str(raw.get("updated") or "")
    return out


def _read_proxy(serial: str) -> str | None:
    adb = os.environ.get("PHARMFLOW_ADB") or r"C:\PharmFlow\bundled\adb.exe"
    try:
        from automation.win_subprocess import hidden_run_kwargs

        hide = hidden_run_kwargs()
    except Exception:
        hide = {}
    try:
        return subprocess.check_output(
            [adb, "-s", serial, "shell", "settings", "get", "global", "http_proxy"],
            text=True,
            timeout=10,
            **hide,
        ).strip()
    except (subprocess.SubprocessError, OSError):
        return None


def _proxy_cleared(value: str | None) -> bool:
    raw = (value or "").strip().lower()
    return (not raw) or raw in ("null", "none", ":0") or raw.endswith(":0")


def inject_pin_needed(cur: str | None, want: str, fg_package: str | None) -> bool:
    """True when remediator should force guest http_proxy onto the inject port.

    Firefox/Brave/Opera on ``:0`` is isolate MITM-skip (their CA rejects MITM),
    not a dead inject listener. Chromium on ``:0`` / wrong port still needs a pin.
    """
    want_s = (want or "").strip()
    cur_s = (cur or "").strip()
    if cur_s == want_s and want_s:
        return False
    pkg = (fg_package or "").split("/")[0].strip()
    if skips_mitm(pkg) and _proxy_cleared(cur_s):
        return False
    return True


def _phone_idx_for_serial(serial: str) -> int | None:
    """Map ADB serial → MuMu index. None if unknown (do not default to 0)."""
    ser = str(serial or "")
    if not ser:
        return None
    try:
        from wizard.mumu_farm_ops import MuMuFarmOps

        farm = MuMuFarmOps()
        farm.refresh_serials()
        for inst in farm.list_instances():
            if str(getattr(inst, "adb_serial", "") or "") == ser:
                idx = getattr(inst, "index", None)
                if idx is not None:
                    return int(idx)
    except Exception:
        pass
    return None


def _roster_indexes() -> list[int]:
    """Absolute vm indexes from the live serial map. Not a count ceiling."""
    try:
        data = json.loads((LOG_DIR / "ADB_SERIAL_MAP.lock.json").read_text(encoding="utf-8"))
        names = [str(k) for k, v in dict(data.get("phones") or {}).items() if str(v or "").strip()]
    except Exception:
        names = []
    out: list[int] = []
    for name in names:
        match = re.match(r"^vm(\d+)\.", name)
        if match:
            out.append(int(match.group(1)))
    return out


def _idx_from_guest_proxy(value: str) -> int | None:
    """Infer phone index from 127.0.0.1:<inject|tor> port when MuMu map misses.

    Inject ports are INJECT_BASE + index. Tor HTTPTunnelPort is base + slot.
    Scanning indexes 0-15 marked every later live pin as broken.
    """
    raw = (value or "").strip()
    if not raw.startswith("127.0.0.1:"):
        return None
    try:
        port = int(raw.split(":", 1)[1])
    except (IndexError, ValueError):
        return None
    if port <= 0:
        return None
    try:
        from automation.mantis_inject_proxy import INJECT_BASE, phone_inject_port
        from automation.tor_manager import HTTP_TUNNEL_BASE, phone_http_port
    except Exception:
        return None

    for idx in _roster_indexes():
        try:
            if int(phone_http_port(idx)) == port or int(phone_inject_port(idx)) == port:
                return idx
        except Exception:
            continue

    try:
        if port >= int(INJECT_BASE):
            idx = port - int(INJECT_BASE)
            if int(phone_inject_port(idx)) == port:
                return idx
    except Exception:
        pass

    try:
        base = int(HTTP_TUNNEL_BASE)
    except (TypeError, ValueError):
        return None
    if port < base:
        return None
    linear = port - base
    try:
        if int(phone_http_port(linear)) == port:
            return linear
    except Exception:
        return None
    return None


def _proxy_ok_for_serial(serial: str, value: str | None) -> bool:
    """Guest http_proxy matches the *expected* endpoint for the active browser.

    Scramble + Firefox/DuckDuckGo/Brave correctly use :0 (no MITM CA). Calling that
    "Tor broken" made the dash lie and triggered thrash re-pins onto Tor.

    Chromium may sit on inject (8218+) or Tor (8118+). Never default unknown
    serials to phone_idx=0 — that falsely flagged good 8220/8221 pins as bad.
    """
    try:
        adb = AdbWrapper()
        pkg = resolve_browser_package(adb, serial)
        cur = (value or "").strip()
        phone_idx = _phone_idx_for_serial(serial)
        if phone_idx is None:
            phone_idx = _idx_from_guest_proxy(cur)

        # MITM-skip browsers: cleared proxy is the happy path.
        if skips_mitm(pkg):
            if _proxy_cleared(cur):
                return True
            # Mid-scramble race: inject briefly visible — not a hard fault if
            # mode is scramble and package is Brave/FF/DDG (watcher will clear).
            if browse_proxy_mode() in ("scramble", "direct", "upstream"):
                return False
            return bool(phone_idx is not None and guest_proxy_healthy(cur, phone_idx))

        if phone_idx is None:
            # Chromium + unknown index: accept any farm inject/tor port.
            return bool(_idx_from_guest_proxy(cur) is not None)

        want = expected_guest_proxy(phone_idx, browser_package=pkg)
        if not want:
            return _proxy_cleared(cur)
        # Accept exact want OR either inject/Tor port for this phone.
        if cur == want or guest_proxy_healthy(cur, phone_idx):
            return True
        # Path3 FORCE_DIRECT clears proxy for a few seconds — not lasting damage.
        return False
    except Exception:
        # Fall back: any live 127.0.0.1:port OR cleared scramble proxy.
        if _proxy_cleared(value):
            return True
        return bool(value) and str(value).startswith("127.0.0.1:") and not str(value).endswith(":0")


def _proxy_health(serials: list[str]) -> tuple[int, int, list[str]]:
    """Return (ok, total, bad_labels) using per-browser expected guest proxy.

    Ad-fill deliberately drops the proxy to direct for a few seconds, so a single
    bad read is re-checked before it is reported — otherwise every digest that
    lands mid-ad-fill claims a broken phone.
    """
    if not serials:
        return 0, 0, []
    readings = {ser: _read_proxy(ser) for ser in serials}
    suspect = [ser for ser, val in readings.items() if not _proxy_ok_for_serial(ser, val)]
    if suspect:
        time.sleep(float(os.environ.get("PHARMFLOW_CHECKIN_PROXY_RECHECK_S", "8") or "8"))
        for ser in suspect:
            readings[ser] = _read_proxy(ser)
    ok = 0
    bad: list[str] = []
    for ser in serials:
        val = readings[ser]
        if _proxy_ok_for_serial(ser, val):
            ok += 1
        else:
            bad.append(f"{ser}={val if val else '?'}")
    return ok, len(serials), bad


def gather_checkin(*, fixes: list[str] | None = None, note: str = "") -> FarmCheckin:
    pids = _farm_pids()
    serials = _adb_devices()
    start_n, online_names = _last_start_phones()
    prog = _progress()
    ran, ok, fail, p3, ip_sw, per = _cycle_stats_from_progress(prog)
    proxies_ok, proxies_total, proxy_bad = _proxy_health(serials)
    expect = int(os.environ.get("PHARMFLOW_FARM_EXPECT_PHONES") or "5")
    # The cycle's own phone list beats the env default, which goes stale the
    # moment the farm is launched with a different --phones set.
    cycle_phones = len(prog.get("phones") or {})
    if cycle_phones > 0:
        expect = cycle_phones
    else:
        try:
            panel = Path(r"C:\PharmFlow\logs\farm_operator_panel.json")
            if panel.is_file():
                pdata = json.loads(panel.read_text(encoding="utf-8"))
                n_panel = len(pdata.get("phones") or [])
                if n_panel > 0:
                    expect = n_panel
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    if start_n > 0:
        # The launched phone count is authoritative — a stale default/panel list
        # must not report "4/5 ADB" forever on a 4-phone farm.
        expect = start_n
    day_mode = _is_day_mode(prog)
    deadline = _parse_ts(prog.get("deadline"))
    if day_mode:
        deadline = _local_midnight_utc()
    hours = 0.0 if day_mode else float(prog.get("hours") or 0.0)
    mantis = _load_mantis_today()
    snap = FarmCheckin(
        farm_up=bool(pids),
        farm_pids=pids,
        start_phones=start_n,
        adb_online=len(serials),
        adb_serials=serials,
        online_names=online_names,
        expect_phones=expect,
        cycle_ran=ran,
        cycle_ok=ok,
        cycle_fail=fail,
        path3_clicks=p3,
        ip_switches=ip_sw,
        per_phone_done=per,
        proxies_ok=proxies_ok,
        proxies_total=proxies_total,
        proxy_bad=proxy_bad,
        browsers=summarize_browsers(_rows_since(_cycle_window_start(prog))),
        deadline_utc=deadline,
        hours=hours,
        day_mode=day_mode,
        fixes=list(fixes or []),
        note=note,
        mantis_available=bool(mantis.get("available")),
        mantis_payout_usd=float(mantis["payout_usd"]) if mantis else None,
        mantis_impressions=int(mantis["impressions"]) if mantis else None,
        mantis_clicks=int(mantis["clicks"]) if mantis else None,
        mantis_ecpm=float(mantis["ecpm"]) if mantis else None,
        mantis_updated=str(mantis.get("updated") or ""),
    )
    if not snap.farm_up:
        snap.verdict = "DOWN"
    elif snap.proxy_bad:
        snap.verdict = "needs fix"
    elif snap.adb_online < (start_n or expect):
        snap.verdict = "partial"
    elif snap.healthy:
        snap.verdict = "healthy"
    else:
        snap.verdict = "UP"
    return snap


def _local_deadline_bits(deadline: datetime | None, *, day_mode: bool = False) -> str:
    if deadline is None:
        return "midnight (24h day)" if day_mode else "unknown"
    now = datetime.now(timezone.utc)
    left_s = (deadline - now).total_seconds()
    local = deadline.astimezone()
    if left_s <= 0:
        return f"{local.strftime('%H:%M')} local (day rolled)"
    hrs = int(left_s // 3600)
    mins = int((left_s % 3600) // 60)
    label = "midnight" if day_mode else "end"
    return f"~{local.strftime('%H:%M')} local {label} (~{hrs}h {mins}m left)"


def format_browsers(browsers: dict[str, dict[str, int]]) -> str:
    """chrome 12/12 OK | brave 4/5 | ff 3/3 | ddg 2/2 — idle browsers shown as idle."""
    if not browsers:
        return "no sequences yet this window"
    parts: list[str] = []
    for tag in _BROWSER_TAGS:
        stats = browsers.get(tag)
        short = _BROWSER_SHORT.get(tag, tag)
        if not stats:
            parts.append(f"{short} idle")
            continue
        ran = stats["ok"] + stats["fail"]
        parts.append(f"{short} {stats['ok']}/{ran}")
    return " | ".join(parts)


def format_mantis_today_line() -> str:
    """One-line Mantis today from freshest pull — safe to call alone."""
    m = _load_mantis_today()
    if not m:
        return "Mantis today: (no pull yet)"
    return (
        f"Mantis today: ${float(m['payout_usd']):.2f}"
        f" | impr={int(m['impressions'])}"
        f" | clk={int(m['clicks'])}"
        f" | eCPM=${float(m['ecpm']):.2f}"
    )


def _format_mantis_line(snap: FarmCheckin) -> str:
    """One-line Mantis today from a check-in snapshot."""
    if not snap.mantis_available:
        return "Mantis today: (no pull yet)"
    pay = float(snap.mantis_payout_usd or 0)
    impr = int(snap.mantis_impressions or 0)
    clicks = int(snap.mantis_clicks or 0)
    ecpm = float(snap.mantis_ecpm or 0)
    return f"Mantis today: ${pay:.2f} | impr={impr} | clk={clicks} | eCPM=${ecpm:.2f}"


def format_checkin(snap: FarmCheckin, *, include_fixes: bool = True) -> str:
    """Plain-text check-in body for ntfy (phone-readable)."""
    names = snap.online_names or [f"vm{i}" for i in range(snap.start_phones or snap.adb_online)]
    name_s = ",".join(n.split(".")[0] for n in names) if names else "—"
    start_show = snap.start_phones or snap.adb_online or "?"
    phones_line = (
        f"Phones: {snap.adb_online}/{snap.expect_phones} ADB"
        f" | START {start_show}"
        f" ({name_s})"
    )
    per = " | ".join(f"{k}:{v}" for k, v in sorted(snap.per_phone_done.items())) or "-"
    if snap.proxies_total:
        if snap.proxy_bad:
            ip_line = (
                f"Guest proxy: {snap.proxies_ok}/{snap.proxies_total} OK"
                f" | bad={','.join(snap.proxy_bad[:4])}"
                f" | IP_switches={snap.ip_switches}"
            )
        else:
            ip_line = (
                f"Guest proxy: {snap.proxies_ok}/{snap.proxies_total} OK"
                f" | IP_switches={snap.ip_switches}"
            )
    else:
        ip_line = f"Guest proxy: IP_switches={snap.ip_switches}"

    status_bit = "UP" if snap.farm_up else "DOWN"
    lines = [
        f"Farm check-in - {snap.verdict}",
        (
            f"Status: {status_bit} | 24h day mode (daily visit/ad caps)"
            if snap.day_mode
            else f"Status: {status_bit} | {snap.hours:g}h window"
        ),
        phones_line,
        (
            f"Today: ran={snap.cycle_ran} | OK={snap.cycle_ok}"
            f" | FAIL={snap.cycle_fail} | Path3={snap.path3_clicks}"
            if snap.day_mode
            else (
                f"This window: ran={snap.cycle_ran} | OK={snap.cycle_ok}"
                f" | FAIL={snap.cycle_fail} | Path3={snap.path3_clicks}"
            )
        ),
        _format_mantis_line(snap),
        f"Per phone: {per}",
        f"Browsers: {format_browsers(snap.browsers)}",
        ip_line,
        (
            f"Day resets: {_local_deadline_bits(snap.deadline_utc, day_mode=True)}"
            if snap.day_mode
            else f"Window end: {_local_deadline_bits(snap.deadline_utc)}"
        ),
    ]
    if snap.note:
        lines.append(f"Note: {snap.note}")
    if include_fixes and snap.fixes:
        lines.append("Fixes: " + "; ".join(snap.fixes[:6]))
    return "\n".join(lines)


def format_fix_message(fixes: list[str], snap: FarmCheckin | None = None) -> str:
    """Separate FIX ntfy body, then a short check-in."""
    head = "Farm FIX - " + ("; ".join(fixes[:4]) if fixes else "repaired")
    lines = [head]
    for f in fixes[:8]:
        lines.append(f"- {f}")
    if snap is None:
        snap = gather_checkin(fixes=fixes)
    lines.append("---")
    lines.append(format_checkin(snap, include_fixes=False))
    return "\n".join(lines)


def publish_ntfy(
    title: str,
    body: str,
    *,
    tags: str = "clipboard,phone",
    priority: str = "default",
    force: bool = False,
) -> bool:
    """Post to ntfy. Throttled to one message per NTFY_MIN_INTERVAL_S unless force=True."""
    now = time.time()
    if not force and NTFY_MIN_INTERVAL_S > 0:
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            prev = 0.0
            if NTFY_THROTTLE.is_file():
                raw = json.loads(NTFY_THROTTLE.read_text(encoding="utf-8"))
                prev = float(raw.get("last_sent_unix") or 0)
            elapsed = now - prev
            if prev > 0 and elapsed < NTFY_MIN_INTERVAL_S:
                left = int(NTFY_MIN_INTERVAL_S - elapsed)
                print(
                    f"ntfy throttled ({left}s left in 2h window) skipped title={title!r}",
                    flush=True,
                )
                return False
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    data = body.encode("utf-8")
    safe_title = title[:120].encode("ascii", "replace").decode("ascii")
    req = urllib.request.Request(
        _ntfy_url(),
        data=data,
        method="POST",
        headers={
            "Title": safe_title,
            "Priority": priority,
            "Tags": tags,
            "Content-Type": "text/plain; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            NTFY_THROTTLE.write_text(
                json.dumps(
                    {
                        "last_sent_unix": now,
                        "last_title": safe_title,
                        "min_interval_s": NTFY_MIN_INTERVAL_S,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def publish_checkin(
    snap: FarmCheckin | None = None,
    *,
    title: str | None = None,
    force: bool = False,
) -> bool:
    snap = snap or gather_checkin()
    body = format_checkin(snap)
    ttl = title or f"Farm check-in - {snap.verdict}"
    # ntfy Title header must be latin-1 safe
    ttl = ttl.encode("ascii", "replace").decode("ascii")
    tags = "white_check_mark,phone" if snap.farm_up else "warning,phone"
    return publish_ntfy(ttl, body, tags=tags, force=force)


def publish_fix(
    fixes: list[str],
    snap: FarmCheckin | None = None,
    *,
    force: bool = False,
) -> bool:
    if not fixes:
        return False
    snap = snap or gather_checkin(fixes=fixes)
    body = format_fix_message(fixes, snap)
    return publish_ntfy(
        "Farm FIX",
        body,
        tags="wrench,white_check_mark",
        priority="high",
        force=force,
    )


def one_line(snap: FarmCheckin | None = None) -> str:
    """Compact single-line variant (replies / logs)."""
    snap = snap or gather_checkin()
    per = ",".join(f"{k}:{v}" for k, v in sorted(snap.per_phone_done.items())) or "-"
    return (
        f"check-in {snap.verdict}: farm={'UP' if snap.farm_up else 'DOWN'} "
        f"phones={snap.adb_online}/{snap.expect_phones} START={snap.start_phones} "
        f"ran={snap.cycle_ran} OK={snap.cycle_ok} FAIL={snap.cycle_fail} "
        f"Path3={snap.path3_clicks} IP_sw={snap.ip_switches} "
        f"GuestProxy={snap.proxies_ok}/{snap.proxies_total} done=[{per}]"
    )
