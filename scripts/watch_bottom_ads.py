"""Probe farm Chromium UIs for bottom-ad presence — and AUTO-FIX when broken.

Writes:
  C:\\CPharm\\logs\\ads_watch_state.json
  C:\\CPharm\\logs\\bottom_ads_alert.flag  (when ads missing / too few Chromium FG)
  C:\\CPharm\\logs\\FARM_BOTTOM_ADS_NOW.txt  (NOT FARM_HONEST_NOW — remediator owns that)

Safe: no MuMu restart / adb kill-server. Does NOT Start CPharm EXE farm.

  py -u scripts/watch_bottom_ads.py once
  py -u scripts/watch_bottom_ads.py loop --loop 75
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import automation.no_window  # noqa: E402,F401  — CREATE_NO_WINDOW for every adb child

LOG = Path(r"C:\CPharm\logs")
OUT = LOG / "ads_watch_state.json"
ALERT = LOG / "bottom_ads_alert.flag"
# Own file — do NOT overwrite FARM_HONEST_NOW.txt (remediator + money_monitor own that).
HONEST = LOG / "FARM_BOTTOM_ADS_NOW.txt"
MONEY_HONEST = LOG / "FARM_HONEST_NOW.txt"
STICKY = LOG / "farm_runtime_overrides.json"
PROGRESS = LOG / "farm_354_progress.json"
DABFLOW = "https://getdabflow.app/"
CHROME = "org.chromium.chrome"

# Prefer bundled adb (same as farm) — platform-tools adb often pops a Terminal window.
_ADB = str(Path(r"C:\CPharm\bundled\adb.exe"))
if not Path(_ADB).is_file():
    _ADB = "adb"

# Legacy ARM MuMu defaults — only used when ADB_SERIAL_MAP.lock.json is missing.
_LEGACY_ARM_PHONES = (
    ("10.0.2.222:5555", 8218, "vm0"),
    ("10.0.2.171:5555", 8219, "vm1"),
    ("10.0.2.27:5555", 8220, "vm2"),
    ("10.0.2.156:5555", 8221, "vm3"),
    ("10.0.2.155:5555", 8222, "vm4"),
    ("10.0.2.100:5555", 8223, "vm5"),
)


def _phones_from_lock() -> list[tuple[str, int, str]]:
    """Prefer live lock map (AVD emulator-5554 / BlueStacks) over stale ARM defaults."""
    lock = LOG / "ADB_SERIAL_MAP.lock.json"
    try:
        if not lock.is_file():
            return list(_LEGACY_ARM_PHONES)
        data = json.loads(lock.read_text(encoding="utf-8-sig"))
        phones = data.get("phones") or {}
        if not isinstance(phones, dict) or not phones:
            return list(_LEGACY_ARM_PHONES)
        inject_map = data.get("inject") or {}
        out: list[tuple[str, int, str]] = []
        seen_serials: set[str] = set()
        for name, serial in phones.items():
            ser = str(serial or "").strip()
            nm = str(name or "").strip()
            if not ser or not nm:
                continue
            # A serial can appear under two vm names (vm14 AND vm15 -> same IP) —
            # only the first (lowest-index) entry wins; the duplicate would pin
            # the phone to a dead port (e.g. 8233) nothing listens on.
            if ser in seen_serials:
                continue
            seen_serials.add(ser)
            # Prefer the lock's authoritative inject map (farm-written) over
            # recomputing 8218 + index from the name — the name-derived port can
            # drift from the live listener when names/serials shift.
            port = 0
            try:
                port = int(inject_map.get(nm) or 0)
            except (TypeError, ValueError):
                port = 0
            if port <= 0:
                idx = 0
                m = re.match(r"vm(\d+)", nm.lower())
                if m:
                    idx = int(m.group(1))
                port = 8218 + idx
            short = nm.split(".", 1)[0]
            out.append((ser, port, short))
        return out or list(_LEGACY_ARM_PHONES)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return list(_LEGACY_ARM_PHONES)



# Consecutive Lawnchair cycles before we force Chromium (avoid fighting isolate wipe).
_LAWN_STREAK: dict[str, int] = {}
_INJECT_SOFT_RESTART_AT = 0.0
_LAST_FIXES: list[str] = []
_DUMP_LOCK = LOG / "_uiautomator_dump.lock"
_DUMP_LOCK_STALE_S = 45.0


def _adb(serial: str, *args: str, timeout: float = 12.0) -> str:
    try:
        p = subprocess.run(
            [_ADB, "-s", serial, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)),
        )
        return (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"ERR:{exc}"


def _acquire_dump_lock(timeout_s: float = 20.0) -> bool:
    """Serialize uiautomator dumps across watcher + remediator procs."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if _DUMP_LOCK.is_file():
                age = time.time() - _DUMP_LOCK.stat().st_mtime
                if age > _DUMP_LOCK_STALE_S:
                    try:
                        _DUMP_LOCK.unlink()
                    except OSError:
                        pass
            fd = os.open(str(_DUMP_LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(f"{os.getpid()} {time.time():.3f}\n")
            return True
        except FileExistsError:
            time.sleep(0.35)
        except OSError:
            time.sleep(0.35)
    return False


def _release_dump_lock() -> None:
    try:
        if _DUMP_LOCK.is_file():
            _DUMP_LOCK.unlink()
    except OSError:
        pass


def _fg_pkg(serial: str) -> str:
    # Prefer topResumedActivity — on MuMu, mCurrentFocus is often null while
    # Chromium is actually resumed/visible (false Lawnchair / empty FG).
    out2 = _adb(serial, "shell", "dumpsys", "activity", "activities", timeout=8.0)
    m2 = re.search(r"topResumedActivity=ActivityRecord\{[^ ]+ u0 ([^/]+)/", out2)
    if m2:
        return m2.group(1)
    out = _adb(serial, "shell", "dumpsys", "window", "windows", timeout=8.0)
    m = re.search(r"mCurrentFocus=Window\{[^ ]+ u0 ([^/]+)/", out)
    if m:
        return m.group(1)
    # Last resort: focusedApp
    m3 = re.search(r"mFocusedApp=ActivityRecord\{[^ ]+ u0 ([^/]+)/", out2 + "\n" + out)
    return m3.group(1) if m3 else ""


def _proxy(serial: str) -> str:
    return (_adb(serial, "shell", "settings", "get", "global", "http_proxy") or "").strip()


def _port_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.6):
            return True
    except OSError:
        return False


def _active_count() -> int:
    try:
        raw = json.loads(PROGRESS.read_text(encoding="utf-8"))
        keys = raw.get("active_keys") or raw.get("active_sequences") or []
        return len(keys)
    except (OSError, ValueError, TypeError):
        return -1


def _stagger_ok() -> tuple[bool, str]:
    try:
        sticky = json.loads(STICKY.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False, "sticky_missing"
    win = str(sticky.get("CPHARM_FARM_START_STAGGER_WINDOW") or "")
    gap = str(sticky.get("CPHARM_FARM_START_STAGGER_MIN_GAP") or "")
    uniq = str(sticky.get("CPHARM_FARM_UNIQUE_SEQ") or "")
    # Operator 150/18 plus squeezed money-day windows. Unique-seq must stay on.
    ok = uniq == "1" and win in {"60", "75", "120", "150"} and gap in {"8", "10", "15", "18"}
    return ok, f"window={win} gap={gap} unique={uniq}"


def _repin_proxy(serial: str, port: int) -> str:
    """adb reverse inject(+tor) then pin guest http_proxy. Reverse mismatch → ERR_PROXY.

    Farm (old EXE) sometimes pins packed ADB_SERIALS order (e.g. vm3→8219). We force
    MuMu-index ports (vm3→8220, vm11→8219) and ensure reverse exists so MITM works
    even during a brief farm race.
    """
    want = f"127.0.0.1:{port}"
    tor = 8118 + (port - 8218)
    cur = _proxy(serial)
    cur_port = None
    mcur = re.search(r"127\.0\.0\.1:(\d+)", cur or "")
    if mcur:
        cur_port = int(mcur.group(1))
    listing = _adb(serial, "reverse", "--list", timeout=6.0)
    # Keep sticky reverse; also keep current farm port reverse if it differs.
    keep = {port}
    if cur_port and 8218 <= cur_port <= 8222:
        keep.add(cur_port)
    for m in re.finditer(r"tcp:(\d+)\s+tcp:\d+", listing or ""):
        g = int(m.group(1))
        if 8218 <= g <= 8222 and g not in keep:
            _adb(serial, "reverse", "--remove", f"tcp:{g}", timeout=5.0)
    _adb(serial, "reverse", f"tcp:{port}", f"tcp:{port}", timeout=8.0)
    _adb(serial, "reverse", f"tcp:{tor}", f"tcp:{tor}", timeout=6.0)
    if cur_port and cur_port != port and 8218 <= cur_port <= 8222:
        _adb(serial, "reverse", f"tcp:{cur_port}", f"tcp:{cur_port}", timeout=6.0)
    _adb(serial, "shell", "settings", "put", "global", "http_proxy", want)
    # Re-assert once — farm isolate often clears to :0 in the same second.
    time.sleep(0.2)
    _adb(serial, "shell", "settings", "put", "global", "http_proxy", want)
    got = _proxy(serial)
    listing2 = _adb(serial, "reverse", "--list", timeout=6.0)
    rev_ok = f"tcp:{port}" in (listing2 or "")
    return f"repin {serial}->{want} got={got} reverse_ok={rev_ok} had={cur}"


def _dismiss_age_gate(serial: str) -> str:
    """Dismiss dabflow age gate.

    Prefer tapping the live age-yes-btn bounds from a quick UI dump; fall back to
    coords that match the current gate layout (YES is mid/lower screen).
    """
    dump = LOG / f"_age_gate_{serial.replace(':', '_').replace('.', '_')}.xml"
    _adb(serial, "shell", "uiautomator", "dump", "/sdcard/_age_gate.xml")
    _adb(serial, "pull", "/sdcard/_age_gate.xml", str(dump))
    text = dump.read_text(encoding="utf-8", errors="ignore") if dump.is_file() else ""
    # Iterate nodes (YES text may include non-ASCII checkmark glyphs).
    for node in re.finditer(r"<node\b[^>]*>", text):
        s = node.group(0)
        if "age-yes-btn" not in s and "I AM 21" not in s and not (
            "YES" in s and "21" in s and "age" in s.lower()
        ):
            # Still accept plain YES+21 on dabflow age gate nodes.
            if not ("YES" in s and "21" in s and ("btn" in s.lower() or "clickable=\"true\"" in s)):
                continue
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', s)
        if not b:
            continue
        x1, y1, x2, y2 = map(int, b.groups())
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        _adb(serial, "shell", "input", "tap", str(cx), str(cy))
        time.sleep(0.25)
        return f"age_gate_bounds_tap {serial} ({cx},{cy})"
    # Fallback coords: MuMu money phones are often 900x1600 (YES ~[112,1297][530,1485]).
    # Also keep a few 1080x2280 guesses.
    for x, y in (
        (321, 1391),
        (300, 1390),
        (250, 1390),
        (400, 1400),
        (321, 1450),
        (325, 1491),
        (340, 1480),
        (540, 1500),
        (450, 1420),
    ):
        _adb(serial, "shell", "input", "tap", str(x), str(y))
        time.sleep(0.12)
    return f"age_gate_taps {serial} bounds=False"


def _open_dabflow_chromium(serial: str) -> str:
    _adb(
        serial,
        "shell",
        "am",
        "start",
        "-a",
        "android.intent.action.VIEW",
        "-d",
        DABFLOW,
        "-n",
        f"{CHROME}/com.google.android.apps.chrome.Main",
    )
    # Age gate paints after load — wait, dismiss, retry once if still gated.
    time.sleep(2.2)
    msg = _dismiss_age_gate(serial)
    time.sleep(1.0)
    dump = LOG / f"_age_gate_{serial.replace(':', '_').replace('.', '_')}.xml"
    _adb(serial, "shell", "uiautomator", "dump", "/sdcard/_age_gate.xml")
    _adb(serial, "pull", "/sdcard/_age_gate.xml", str(dump))
    text = dump.read_text(encoding="utf-8", errors="ignore") if dump.is_file() else ""
    if "age-gate" in text or "age-yes-btn" in text:
        msg = _dismiss_age_gate(serial)
        time.sleep(0.8)
    # Scroll bottom zones into view.
    for _ in range(5):
        _adb(serial, "shell", "input", "swipe", "450", "1400", "450", "450", "280")
        time.sleep(0.2)
    return f"am_start_dabflow {serial} ({msg})"


def _soft_restart_inject() -> str:
    global _INJECT_SOFT_RESTART_AT
    now = time.time()
    if now - _INJECT_SOFT_RESTART_AT < 180.0:
        return "inject_restart_skipped_cooldown"
    _INJECT_SOFT_RESTART_AT = now
    # Kill existing inject listeners on 8218-8222 owners gently via taskkill pattern.
    try:
        from automation.process_scan import kill_matching

        kill_matching("run_mantis_inject_proxies.py")
    except Exception:
        pass
    time.sleep(1.5)
    # Helper interpreter + repo root derived at runtime (portable EXE contract).
    pyw = None
    try:
        from automation.runtime_paths import helper_python

        pyw = helper_python()
    except Exception:
        pyw = None
    pyw = pyw or sys.executable
    # Run the injector from the live code tree (bundle root), never a stale
    # checkout copy — a stale injector lacks the current Tor/reverse fixes.
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "run_mantis_inject_proxies.py"
    try:
        from automation.farm_phone_discover import inject_listener_count

        inject_n = str(max(11, int(inject_listener_count())))
    except Exception:
        inject_n = "11"
    try:
        subprocess.Popen(
            # --phones N = indices 0..N-1. vm10 → :8228 needs N>=11.
            [str(pyw), "-u", str(script), "--phones", inject_n],
            cwd=str(root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        return f"inject_restart_fail:{exc}"
    time.sleep(3.5)
    ok = all(_port_listening(p) for p in (8218, 8219, 8220, 8221, 8222, 8223))
    return f"inject_soft_restart listen_ok={ok}"


def probe_phone(serial: str, port: int, name: str, *, farm_active: bool = False) -> dict:
    fg = _fg_pkg(serial)
    px = _proxy(serial)
    want = f"127.0.0.1:{port}"
    row: dict = {
        "name": name,
        "serial": serial,
        "inject_port": port,
        "proxy": px,
        "proxy_ok": px == want,
        "fg": fg,
        # True Chromium only — Brave/Opera also expose *.chrome.Main in dumpsys.
        "chromium_fg": (
            "org.chromium.chrome" in fg.lower() or "com.android.chrome" in fg.lower()
        )
        and ("brave" not in fg.lower())
        and ("opera" not in fg.lower()),
        "adsbymantis": 0,
        "cpharm": 0,
        "fat_bounds": None,
        "ok": False,
        "note": "",
        "fixes": [],
    }
    if not row["chromium_fg"]:
        row["note"] = "not_chromium_fg"
        return row
    if farm_active:
        # Mid-seq swipe + uiautomator dump races Start Perfect Dab / age-gate.
        row["ok"] = True
        row["note"] = "skip_dump_farm_active"
        return row
    # 2 scrolls only — 6x swipe/phone was an ADB storm multiplier.
    for _ in range(2):
        _adb(serial, "shell", "input", "swipe", "450", "1400", "450", "450", "280", timeout=6.0)
        time.sleep(0.15)
    time.sleep(0.35)
    dump = LOG / f"_bottom_ads_{name}.xml"
    got_lock = _acquire_dump_lock(18.0)
    try:
        _adb(serial, "shell", "uiautomator", "dump", "/sdcard/_bottom_ads.xml", timeout=14.0)
        _adb(serial, "pull", "/sdcard/_bottom_ads.xml", str(dump), timeout=10.0)
    finally:
        if got_lock:
            _release_dump_lock()
    text = dump.read_text(encoding="utf-8", errors="ignore") if dump.is_file() else ""
    if not text:
        row["note"] = "dump_empty" if got_lock else "dump_lock_busy"
        return row
    row["adsbymantis"] = text.count("adsbymantis")
    row["cpharm"] = text.lower().count("cpharm")
    fat = None
    for m in re.finditer(r"<node[^>]*adsbymantis[^>]*>", text):
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', m.group(0))
        if not b:
            continue
        x1, y1, x2, y2 = map(int, b.groups())
        w, h = x2 - x1, y2 - y1
        if h >= 40 and w >= 80:
            cand = {"bounds": [x1, y1, x2, y2], "w": w, "h": h}
            if fat is None or cand["h"] > fat["h"]:
                fat = cand
    row["fat_bounds"] = fat
    row["ok"] = bool(row["adsbymantis"] > 0)
    if row["adsbymantis"] > 0 and fat is None:
        row["note"] = "ads_marker_no_fat_bounds"
    elif not row["ok"]:
        row["note"] = "no_adsbymantis"
    return row


def remediate(phones: list[dict], chromium_ok: int, chromium_total: int, actives: int) -> list[str]:
    """Auto-fix: re-pin inject, open dabflow, age-gate, soft-restart inject if needed."""
    fixes: list[str] = []
    if int(actives) > 0:
        for p in phones:
            if p.get("proxy_ok"):
                continue
            serial = str(p["serial"])
            port = int(p["inject_port"])
            msg = _repin_proxy(serial, port)
            fixes.append(f"farm_active_proxy_only {msg}")
            p["fixes"].append(msg)
            p["proxy"] = _proxy(serial)
            p["proxy_ok"] = p["proxy"] == f"127.0.0.1:{port}"
        if fixes:
            return fixes
        return [f"skip_ui_rearm farm_active actives={actives}"]
    ports_ok = all(_port_listening(p) for _, p, _ in _phones_from_lock())
    if not ports_ok or not all(_port_listening(p) for p in (8218, 8219, 8220, 8221, 8222)):
        fixes.append(_soft_restart_inject())
        ports_ok = all(_port_listening(p) for p in (8218, 8219, 8220, 8221, 8222))

    chromium_fg = sum(1 for p in phones if p.get("chromium_fg"))
    # Push toward 4+/5 Chromium FG for BOTTOM_ADS (Brave/Opera don't count).
    need_more_chromium = chromium_fg < 4
    ads_bad = chromium_total > 0 and chromium_ok == 0
    actives_low = 0 <= actives < 2

    for p in phones:
        serial = str(p["serial"])
        port = int(p["inject_port"])
        name = str(p["name"])
        if not p.get("proxy_ok"):
            msg = _repin_proxy(serial, port)
            fixes.append(msg)
            p["fixes"].append(msg)
            p["proxy"] = _proxy(serial)
            p["proxy_ok"] = p["proxy"] == f"127.0.0.1:{port}"

        if p.get("chromium_fg"):
            _LAWN_STREAK[name] = 0
            if not p.get("ok"):
                # Chromium up but no bottom ads — age gate / reload dabflow / scroll.
                msg1 = _dismiss_age_gate(serial)
                msg2 = _open_dabflow_chromium(serial)
                fixes.extend([msg1, msg2])
                p["fixes"].extend([msg1, msg2])
                # Isolate may have cleared proxy during reload.
                if _proxy(serial) != f"127.0.0.1:{port}":
                    msg3 = _repin_proxy(serial, port)
                    fixes.append(msg3)
                    p["fixes"].append(msg3)
            continue

        # Not Chromium FG (Lawnchair / Brave / FF / Opera). Force Chromium when
        # FG < 4 so BOTTOM_ADS can climb toward 4+/5.
        _LAWN_STREAK[name] = int(_LAWN_STREAK.get(name, 0)) + 1
        fg = str(p.get("fg") or "").lower()
        if any(x in fg for x in ("brave", "firefox", "opera", "duckduckgo")):
            for pkg in (
                "com.brave.browser",
                "org.mozilla.firefox",
                "com.opera.browser",
                "com.duckduckgo.mobile.android",
            ):
                if pkg.split(".")[1] in fg or pkg in fg:
                    _adb(serial, "shell", "am", "force-stop", pkg, timeout=6.0)
                    fixes.append(f"force_stop_other {name} {pkg}")
        if need_more_chromium and _LAWN_STREAK[name] >= 1:
            msg = _open_dabflow_chromium(serial)
            fixes.append(f"lawn_streak={_LAWN_STREAK[name]} {msg}")
            p["fixes"].append(msg)
            if _proxy(serial) != f"127.0.0.1:{port}":
                msgp = _repin_proxy(serial, port)
                fixes.append(msgp)
                p["fixes"].append(msgp)
        elif actives_low and _LAWN_STREAK[name] >= 1:
            msg = _open_dabflow_chromium(serial)
            fixes.append(f"actives_low {msg}")
            p["fixes"].append(msg)

    # If Chromium present but zero ads after per-phone fixes, soft-restart inject once.
    if ads_bad and ports_ok:
        fixes.append(_soft_restart_inject())
        for _, port, _ in _phones_from_lock():
            pass
        for serial, port, name in _phones_from_lock():
            fixes.append(_repin_proxy(serial, port))

    return fixes


def _write_honest(payload: dict, fixes: list[str], actives: int, stagger: str, usd: str) -> None:
    phones = payload.get("phones") or []
    chrom = sum(1 for p in phones if p.get("chromium_fg"))
    now_local = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    # Ads-visible is NOT money health — never claim last_ok $ from this watcher.
    ads_ok = bool(payload.get("bottom_ads_visible") and chrom >= 3)
    lines = [
        f"FARM_BOTTOM_ADS_NOW  {now_local}",
        "=" * 40,
        f"$NOW: {usd}",
        f"ads_ok: {ads_ok}  (visible!=paying — house creatives can paint and still pay $0)",
        f"last_farming_ts: {payload.get('ts')}",
        f"actives: {actives}",
        f"Chromium_FG: {chrom}/{len(phones) or 5}",
        f"bottom_ads: {payload.get('bottom_ads_chromium_ok')}/{payload.get('bottom_ads_chromium_total')} "
        f"visible={payload.get('bottom_ads_visible')} missing={payload.get('bottom_ads_missing')}",
        f"stagger/unique: {stagger}",
        f"inject_listen: {all(_port_listening(p) for p in (8218, 8219, 8220, 8221, 8222))}",
        f"alert: {payload.get('alert')}",
        f"money_honest_file: {MONEY_HONEST.name}",
        "phones:",
    ]
    for p in phones:
        lines.append(
            f"  {p.get('name')}: fg={p.get('fg')} proxy={p.get('proxy')} "
            f"ads={p.get('adsbymantis')} ok={p.get('ok')} note={p.get('note')}"
        )
    lines.append("auto_fixes_this_cycle:")
    if fixes:
        for f in fixes[-20:]:
            lines.append(f"  - {f}")
    else:
        lines.append("  (none)")
    lines.append("")
    HONEST.write_text("\n".join(lines), encoding="utf-8")


def _usd_quick() -> str:
    try:
        import urllib.request

        req = urllib.request.Request(
            "http://127.0.0.1:8091/api/mantis_pull",
            method="POST",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=25) as r:
            t = json.loads(r.read()).get("mantis_today") or {}
        return f"${t.get('payout_usd')} eCPM=${t.get('ecpm')} impr={t.get('impressions')}"
    except Exception:
        try:
            raw = json.loads((LOG / "mantis_today_state.json").read_text(encoding="utf-8"))
            return f"${raw.get('payout_usd')} eCPM=${raw.get('ecpm')} impr={raw.get('impressions')} (cache)"
        except Exception:
            return "unknown"


def run_once(*, fix: bool = True) -> dict:
    global _LAST_FIXES
    actives = _active_count()
    farm_active = int(actives) > 0
    phones: list[dict] = []
    for s, p, n in _phones_from_lock():
        phones.append(probe_phone(s, p, n, farm_active=farm_active))
        time.sleep(0.4)  # serialize across phones — cut concurrent adb storms
    chromium = [p for p in phones if p.get("chromium_fg")]
    visible_n = sum(1 for p in chromium if p.get("ok"))
    missing = [p["name"] for p in chromium if not p.get("ok")]
    stag_ok, stag_s = _stagger_ok()
    chromium_fg = len(chromium)
    proxy_bad = any(not p.get("proxy_ok") for p in phones)
    if farm_active:
        # Farm owns Chromium / age-gate / Start Dab. Watcher only flags proxy.
        alert = bool(proxy_bad)
        missing = []
    else:
        alert = bool(
            (chromium and visible_n == 0)
            or chromium_fg < 3
            or (0 <= actives < 2)
            or (not stag_ok)
            or proxy_bad
        )
    fixes: list[str] = []
    # Remediating when ANY Chromium FG phone is missing ads (partial 2/3 used to
    # skip fix because alert stayed false). Also remediating on hard alerts.
    need_fix = bool(fix and (alert or missing))
    if need_fix:
        # Two passes: Lawnchair→dabflow often lands on age-gate; second pass
        # dismisses gate / reloads once Chromium is actually FG.
        for _pass in range(2):
            fixes.extend(remediate(phones, visible_n, len(chromium), actives))
            phones = [
                probe_phone(s, p, n, farm_active=farm_active)
                for s, p, n in _phones_from_lock()
            ]
            chromium = [p for p in phones if p.get("chromium_fg")]
            visible_n = sum(1 for p in chromium if p.get("ok"))
            missing = [] if farm_active else [p["name"] for p in chromium if not p.get("ok")]
            chromium_fg = len(chromium)
            if farm_active or not missing:
                break
        if farm_active:
            alert = any(not p.get("proxy_ok") for p in phones)
        else:
            alert = bool(
                (chromium and visible_n == 0)
                or chromium_fg < 3
                or (0 <= actives < 2)
                or any(not p.get("proxy_ok") for p in phones)
            )
    _LAST_FIXES = fixes
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "bottom_ads_visible": visible_n > 0,
        "bottom_ads_chromium_ok": visible_n,
        "bottom_ads_chromium_total": len(chromium),
        "bottom_ads_missing": missing,
        "chromium_fg": chromium_fg,
        "actives": actives,
        "stagger": stag_s,
        "stagger_ok": stag_ok,
        "phones": phones,
        "farm_alive": True,
        "alert": alert,
        "auto_fixes": fixes,
        "watch_pid": os.getpid(),
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if alert:
        ALERT.write_text(
            f"ALERT ts={payload['ts']} ads={visible_n}/{len(chromium)} "
            f"chromium_fg={chromium_fg}/{len(phones)} actives={actives} missing={missing} "
            f"fixes={fixes[:8]}\n",
            encoding="utf-8",
        )
    elif ALERT.is_file():
        try:
            ALERT.unlink()
        except OSError:
            pass
    usd = _usd_quick()
    _write_honest(payload, fixes, actives, stag_s, usd)
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="once", choices=("once", "loop"))
    ap.add_argument("--loop", type=float, default=120.0, help="seconds between probes")
    ap.add_argument("--no-fix", action="store_true", help="probe only (no remediations)")
    args = ap.parse_args()
    while True:
        payload = run_once(fix=not args.no_fix)
        print(
            "BOTTOM_ADS_VISIBLE="
            + ("yes" if payload["bottom_ads_visible"] else "no"),
            f"ok={payload['bottom_ads_chromium_ok']}/{payload['bottom_ads_chromium_total']}",
            f"chromium_fg={payload.get('chromium_fg')}/{len(payload.get('phones') or [])}",
            f"actives={payload.get('actives')}",
            f"missing={payload['bottom_ads_missing']}",
            f"alert={payload.get('alert')}",
            f"fixes={len(payload.get('auto_fixes') or [])}",
            flush=True,
        )
        if args.mode != "loop":
            break
        # Floor 90s — tighter loops were fighting CPharm uiautomator + timing out ADB.
        time.sleep(max(90.0, float(args.loop)))


if __name__ == "__main__":
    main()
