"""Unit tests for automation.farm_exe_self_heal — no live adb required."""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import automation.farm_exe_self_heal as heal


def test_tor_seed_candidates_include_cpharm_after_branding() -> None:
    """Start farm must seed tor.exe from C:\\CPharm when C:\\PharmFlow lacks it."""
    texts = [str(p).replace("/", "\\").lower() for p in heal._TOR_SEED_CANDIDATES]
    assert any(t.endswith(r"c:\cpharm\bundled\tor.exe") for t in texts)
    assert any(t.endswith(r"c:\pharmflow\bundled\tor.exe") for t in texts)


def test_ensure_tor_binary_seeds_from_candidate(tmp_path: Path, monkeypatch) -> None:
    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    seed = seed_dir / "tor.exe"
    seed.write_bytes(b"tor-bin")
    (seed_dir / "libevent.dll").write_bytes(b"dll")

    tor_dir = tmp_path / "tor_dir"
    monkeypatch.setattr(heal, "_TOR_SEED_CANDIDATES", (seed,))
    monkeypatch.setattr(
        "automation.config.TOR_DIR",
        tor_dir,
        raising=False,
    )
    # Import path used inside ensure_tor_binary
    import automation.config as cfg

    monkeypatch.setattr(cfg, "TOR_DIR", tor_dir)

    fixes = heal.ensure_tor_binary()
    assert (tor_dir / "tor.exe").is_file()
    assert any(str(f).startswith("tor_seeded_from=") for f in fixes)
    assert (tor_dir / "libevent.dll").is_file()


def test_prune_serial_map_drops_empty_and_rewrites_sticky(tmp_path: Path, monkeypatch) -> None:
    log = tmp_path / "logs"
    log.mkdir()
    serial_map = log / "ADB_SERIAL_MAP.lock.json"
    sticky = log / "FARM_STICKY_7_PHONES.lock"
    serial_map.write_text(
        json.dumps(
            {
                "phones": {
                    "vm24.gmadoa": "10.0.2.30:5555",
                    "vm0.gmadoa": "",
                    "vm1.gmadoa": "",
                },
                "inject": {"vm24.gmadoa": 8242},
            }
        ),
        encoding="utf-8",
    )
    sticky.write_text(
        json.dumps({"phones": {"vm22.gmadoa": "10.0.2.1:5555"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(heal, "LOG", log)
    monkeypatch.setattr(heal, "SERIAL_MAP", serial_map)
    monkeypatch.setattr(heal, "STICKY_LOCK", sticky)

    with mock.patch.object(heal, "adb_live_serials", return_value=["10.0.2.30:5555"]):
        with mock.patch.object(heal, "_run", return_value=(0, "already connected")):
            with mock.patch(
                "automation.farm_canonical_phones._fleet_from_disk",
                return_value={"vm24.gmadoa": "10.0.2.30:5555"},
            ):
                fixes = heal.prune_serial_map(live=["10.0.2.30:5555"])

    data = json.loads(serial_map.read_text(encoding="utf-8"))
    assert data["phones"] == {"vm24.gmadoa": "10.0.2.30:5555"}
    assert "vm0.gmadoa" not in data["phones"]
    sticky_data = json.loads(sticky.read_text(encoding="utf-8"))
    assert sticky_data["phones"] == {"vm24.gmadoa": "10.0.2.30:5555"}
    assert any("pruned_serial_map" in str(f) for f in fixes)


def test_canonical_workset_lists_serials_when_online_empty() -> None:
    from automation.farm_canonical_phones import canonical_workset

    with mock.patch(
        "automation.farm_canonical_phones._fleet",
        return_value={"vm24.gmadoa": "10.0.2.30:5555", "vm25.gmadoa": "10.0.2.188:5555"},
    ):
        rows = canonical_workset(online_serials={"10.0.2.30:5555", "10.0.2.188:5555"})
    serials = [s for _n, s, _p in rows]
    assert "10.0.2.30:5555" in serials
    assert "10.0.2.188:5555" in serials
    assert all(s for s in serials)


def test_reap_stale_never_kills_inject_keepalive() -> None:
    """Keepalive holds lock-map inject ports — roster inject is poison, keepalive is not."""
    farm_cmd = "pythonw -u scripts/run_farm_354.py"
    roster_inject_cmd = "pythonw -u scripts/run_mantis_inject_proxies.py --phones 14"
    keepalive_cmd = "pythonw -u scripts/pharmflow_inject_keepalive.py"

    class _Proc:
        def __init__(self, pid: int, ppid: int, cmd: str) -> None:
            self.info = {"pid": pid, "ppid": ppid, "cmdline": cmd.split(), "name": "pythonw.exe"}

    rows = [
        _Proc(100, 1, farm_cmd),
        _Proc(200, 1, roster_inject_cmd),
        _Proc(300, 1, keepalive_cmd),
    ]

    fake_psutil = mock.MagicMock()
    fake_psutil.process_iter.return_value = rows
    fake_psutil.Error = Exception
    fake_psutil.pid_exists.return_value = True

    with mock.patch.dict("sys.modules", {"psutil": fake_psutil}):
        with mock.patch(
            "tools.pharmflow_watchdog.reap_stale",
            return_value={"found": 0, "killed": 0, "kills": []},
        ):
            fixes = heal.reap_stale_processes(apply=False)

    would_kill = [f for f in fixes if str(f).startswith("would_kill:")]
    keepalive_hits = [f for f in would_kill if "300" in str(f)]
    inject_hits = [f for f in would_kill if "200" in str(f)]
    assert not keepalive_hits, f"keepalive must not be reaped: {keepalive_hits}"
    assert inject_hits, f"roster inject should be reaped when farm alive: {would_kill}"


def test_reap_stale_dedupes_inject_keepalive() -> None:
    """When >1 keepalive, kill extras but keep highest PID."""
    keepalive_old = "pythonw -u scripts/pharmflow_inject_keepalive.py"
    keepalive_new = "pythonw -u scripts/pharmflow_inject_keepalive.py"

    class _Proc:
        def __init__(self, pid: int, ppid: int, cmd: str) -> None:
            self.info = {"pid": pid, "ppid": ppid, "cmdline": cmd.split(), "name": "pythonw.exe"}

    rows = [
        _Proc(300, 1, keepalive_old),
        _Proc(400, 1, keepalive_new),
    ]

    fake_psutil = mock.MagicMock()
    fake_psutil.process_iter.return_value = rows
    fake_psutil.Error = Exception
    fake_psutil.pid_exists.return_value = True

    with mock.patch.dict("sys.modules", {"psutil": fake_psutil}):
        with mock.patch(
            "tools.pharmflow_watchdog.reap_stale",
            return_value={"found": 0, "killed": 0, "kills": []},
        ):
            fixes = heal.reap_stale_processes(apply=False)

    would_kill = [f for f in fixes if str(f).startswith("would_kill:")]
    dup_hits = [f for f in would_kill if "300" in str(f) and "dup_inject_keepalive" in str(f)]
    kept_hits = [f for f in would_kill if "400" in str(f)]
    assert dup_hits, f"older keepalive should be reaped: {would_kill}"
    assert not kept_hits, f"newest keepalive must survive: {would_kill}"


def _storm_proc(pid: int, ppid: int, name: str, cmd: str, age_s: float = 10.0) -> dict:
    return {
        "pid": pid,
        "ppid": ppid,
        "name": name,
        "cmdline": cmd,
        "age_s": age_s,
    }


def test_reap_process_storm_kills_orphan_tor() -> None:
    farm_cmd = "pythonw -u scripts/run_farm_354.py"
    owned_tor_cmd = r'tor.exe -f C:\PharmFlow\automation\tor\tmp1.cfg'
    orphan_tor_cmd = r'tor.exe -f C:\PharmFlow\automation\tor\tmp99.cfg'

    rows = [
        _storm_proc(100, 1, "pythonw.exe", farm_cmd),
        _storm_proc(200, 100, "tor.exe", owned_tor_cmd),
        _storm_proc(300, 9999, "tor.exe", orphan_tor_cmd),  # dead parent
        _storm_proc(
            400,
            450,
            "tor.exe",
            orphan_tor_cmd,
        ),
        _storm_proc(450, 1, "pythonw.exe", "pythonw -u automation/farm_money_monitor.py loop"),
    ]
    pid_map = {r["pid"]: r for r in rows}

    with mock.patch.object(heal, "_collect_storm_rows", return_value=(rows, pid_map)):
        fixes = heal.reap_process_storm(apply=False)

    would = [f for f in fixes if str(f).startswith("storm_would_kill:")]
    orphan_hits = [
        f
        for f in would
        if ":300:" in str(f)
        and ("orphan_tor" in str(f) or "helper_tor" in str(f))
    ]
    helper_hits = [f for f in would if ":400:" in str(f) and "helper_tor" in str(f)]
    owned_hits = [f for f in would if ":200:" in str(f)]
    assert orphan_hits, f"dead-parent tor should be reaped: {would}"
    assert helper_hits, f"money-mon tor fleet should be reaped: {would}"
    assert not owned_hits, f"farm-owned tor must survive: {would}"


def test_reap_process_storm_keeps_farm_owned_tor() -> None:
    """Tor spawned under tor_manager.py (not run_farm) is still farm-owned."""
    owner_cmd = "pythonw -u automation/tor_manager.py warm"
    tor_cmd = r'tor.exe -f C:\PharmFlow\automation\tor\data_5\torrc'

    rows = [
        _storm_proc(50, 1, "pythonw.exe", owner_cmd),
        _storm_proc(60, 50, "tor.exe", tor_cmd),
    ]
    pid_map = {r["pid"]: r for r in rows}

    with mock.patch.object(heal, "_collect_storm_rows", return_value=(rows, pid_map)):
        fixes = heal.reap_process_storm(apply=False)

    would = [f for f in fixes if str(f).startswith("storm_would_kill:")]
    assert not would, f"tor_manager-owned tor must survive: {would}"
    assert any("storm_reap clean" in str(f) for f in fixes)


def test_reap_process_storm_dedupes_keepalive() -> None:
    keepalive = "pythonw -u scripts/pharmflow_inject_keepalive.py"
    rows = [
        _storm_proc(300, 1, "pythonw.exe", keepalive),
        _storm_proc(400, 1, "pythonw.exe", keepalive),
    ]
    pid_map = {r["pid"]: r for r in rows}

    with mock.patch.object(heal, "_collect_storm_rows", return_value=(rows, pid_map)):
        fixes = heal.reap_process_storm(apply=False)

    would = [f for f in fixes if str(f).startswith("storm_would_kill:")]
    dup_hits = [f for f in would if ":300:" in str(f) and "dup_helper" in str(f)]
    kept_hits = [f for f in would if ":400:" in str(f)]
    assert dup_hits, f"older keepalive should be reaped: {would}"
    assert not kept_hits, f"newest keepalive must survive: {would}"


def test_heal_restores_slot_tor_and_does_not_claim_async_warm(
    tmp_path: Path, monkeypatch
) -> None:
    """Supervisor tick must start slot HTTP tunnels and report them still down."""
    log = tmp_path / "logs"
    log.mkdir()
    serial_map = log / "ADB_SERIAL_MAP.lock.json"
    serial_map.write_text(
        json.dumps(
            {
                "phones": {
                    "vm39.gmadoa": "10.0.2.10:5555",
                    "vm40.gmadoa": "10.0.2.11:5555",
                },
                "inject": {"vm39.gmadoa": 8257, "vm40.gmadoa": 8258},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(heal, "LOG", log)
    monkeypatch.setattr(heal, "SERIAL_MAP", serial_map)
    monkeypatch.setattr(heal, "RELOAD_FLAG", log / "FARM_RELOAD_FARM.flag")
    monkeypatch.setattr(heal, "ensure_tor_binary", lambda: ["tor_present"])
    monkeypatch.setattr(heal, "_port_open", lambda port, timeout=0.4: False)
    monkeypatch.setattr(heal, "_farm_lane_alive", lambda: True)
    monkeypatch.setattr(heal, "_current_process_is_farm", lambda: False)
    monkeypatch.setattr(heal, "_inject_keepalive_alive", lambda: True)
    monkeypatch.setattr(heal, "adb_live_serials", lambda: [])
    monkeypatch.setattr(heal, "_ensure_inject_keepalive_process", lambda **_k: ["inject_keepalive_already"])

    seen: dict[str, object] = {}

    def fake_restore(slots: list[int]) -> dict:
        seen["slots"] = list(slots)
        return {
            "http_base": 8118,
            "restored": [],
            "started": [],
            "bootstrapping": [],
            "still_dead": list(slots),
            "errors": ["slot=0:RuntimeError:tor missing"],
        }

    def fake_start(idxs: list[int]) -> list:
        seen["inject_idxs"] = list(idxs)
        return []

    monkeypatch.setattr(
        "automation.tor_manager.restore_tor_http_for_slots",
        fake_restore,
    )
    monkeypatch.setattr(
        "automation.mantis_inject_proxy.start_inject_proxies",
        fake_start,
    )

    fixes = heal.heal_inject_and_tor(live=[])
    text = "\n".join(str(f) for f in fixes)
    assert seen["slots"] == [0, 1], seen
    assert seen["inject_idxs"] == [39, 40], seen
    assert "tor_warm_async" not in text
    assert "tor_warm_skipped" not in text
    assert "inject_inproc_skipped" not in text
    assert "tor_listeners_ok" not in text
    assert "tor_listeners_not_restored" in text
    assert "inject_restore_failed" in text
    assert "inject_guest_pin_skipped adb_empty" in text


def test_ensure_inject_not_ok_when_listener_down(monkeypatch) -> None:
    from automation.mantis_inject_proxy import ensure_inject_for_phone

    monkeypatch.setattr(
        "automation.mantis_inject_proxy.start_inject_proxies",
        lambda _idxs: [],
    )
    monkeypatch.setattr(
        "automation.mantis_inject_proxy.inject_port_open",
        lambda _port, timeout=0.35: False,
    )
    info = ensure_inject_for_phone(object(), "10.0.2.10:5555", 39, install_ca=True)
    assert info.get("ok") is False
    assert info.get("error") == "inject_listener_down"
    assert info.get("port") == 8257
