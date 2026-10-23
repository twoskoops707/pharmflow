"""Dashboard actions must not report success before the work lands."""
from __future__ import annotations

import sys
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.browser_adb import (  # noqa: E402
    am_start_reported_landing,
    apk_install_reported,
    pm_clear_reported,
)
from automation.dashboard import (  # noqa: E402
    dashboard_reach_host,
    docker_stop_landed,
    emu_kill_landed,
    _adb_connect_landed,
    _dashboard_open_exit_ready,
    _dead_tor_http_reason,
    _host_port_from_docker_port_text,
    _identity_reset_log,
    _open_url_result_log,
    _redroid_name_from_ps_text,
)

DASH = ROOT / "automation" / "dashboard.py"
HTML = ROOT / "automation" / "dashboard.html"


class DashboardActionHonestyTests(unittest.TestCase):
    def test_dashboard_address_is_the_bind_not_the_lan_ip(self) -> None:
        import automation.dashboard as dash

        src = DASH.read_text(encoding="utf-8")
        html = HTML.read_text(encoding="utf-8")
        self.assertNotIn("On phone:", src)
        self.assertIn("Phone traffic does not use this address", src)
        self.assertIn("dashboard_reach_host()", src)
        chip = html.split("async function initIp")[1].split("async function")[0]
        self.assertIn("This PC", chip)
        self.assertNotIn("chip.textContent = r.ip", chip)
        stop = html.split("getElementById('btn-stop-all')")[1].split("Connect device")[0]
        self.assertIn("r.disconnected", stop)
        self.assertIn("r.disconnected ? '' : 'ok'", stop)
        with unittest.mock.patch.object(dash, "LISTEN_HOST", "127.0.0.1"):
            self.assertEqual(dashboard_reach_host(), "127.0.0.1")
        with unittest.mock.patch.object(dash, "LISTEN_HOST", "0.0.0.0"), unittest.mock.patch.object(
            dash, "get_local_ip", return_value="192.0.2.10"
        ):
            self.assertEqual(dashboard_reach_host(), "192.0.2.10")

    def test_dashboard_log_does_not_paint_a_negative_line_green(self) -> None:
        html = HTML.read_text(encoding="utf-8")
        block = html.split("function addLog")[1].split("function toast")[0]
        err = block.split("tone = 'err'")[0]
        ok = block.split("tone = 'ok'")[0]
        self.assertIn("not ready", err)
        self.assertIn("not installed", err)
        self.assertIn("not connected", err)
        self.assertLess(block.find("tone = 'err'"), block.find("tone = 'ok'"))

    def test_group_run_does_not_abandon_a_phone_at_five_minutes(self) -> None:
        src = DASH.read_text(encoding="utf-8")
        loop = src.split("while _running_groups.get(name) and (forever or iteration < repeat):", 1)[1]
        loop = loop.split("iteration += 1", 1)[0]
        self.assertNotIn("t.join(timeout=300)", loop)
        self.assertIn("while t.is_alive() and _running_groups.get(name):", loop)
        self.assertIn("if not _running_groups.get(name):", loop)
        runner = (ROOT / "automation" / "group_runner.py").read_text(encoding="utf-8")
        body = runner.split("def run_group", 1)[1].split("\ndef ", 1)[0]
        self.assertNotIn("10_000", body)
        self.assertIn("target = None", body)

    def test_group_runner_does_not_cut_tap_jitter_at_120(self) -> None:
        src = DASH.read_text(encoding="utf-8")
        tap = src.split('elif t == "tap":', 1)[1].split('elif t == "swipe":', 1)[0]
        self.assertNotIn("min(jitter, 120)", tap)
        self.assertIn("jitter = max(0, jitter)", tap)
        self.assertIn("jitter = min(jitter, 6)", tap)

    def test_silent_adb_install_is_not_an_install(self) -> None:
        self.assertFalse(apk_install_reported("", "", 0))
        self.assertFalse(apk_install_reported("Success", "", 1))
        self.assertFalse(apk_install_reported("Success\nFailure [INSTALL_FAILED]", "", 0))
        self.assertTrue(apk_install_reported("Success", "", 0))
        teach = (ROOT / "automation" / "teach.py").read_text(encoding="utf-8")
        replay = teach.split("def replay_on_phone", 1)[1].split("\ndef ", 1)[0]
        self.assertNotIn("min(delay, 5", replay)

    def test_connect_is_not_ok_when_adb_failed(self) -> None:
        self.assertFalse(_adb_connect_landed("failed to connect to 10.0.2.16:5555", 0))
        self.assertFalse(_adb_connect_landed("cannot connect to 10.0.2.16:5555", 1))
        self.assertTrue(_adb_connect_landed("connected to 10.0.2.16:5555", 0))
        self.assertTrue(_adb_connect_landed("already connected to 10.0.2.16:5555", 0))

    def test_identity_reset_log_has_no_checkmark_without_a_new_circuit(self) -> None:
        failed = _identity_reset_log("vm3", {"tor_circuit_rotated": False})
        self.assertIn("failed", failed)
        self.assertNotIn("✓", failed)
        landed = _identity_reset_log(
            "vm3", {"tor_circuit_rotated": True, "http_proxy_applied": True}
        )
        self.assertIn("new Tor circuit", landed)
        self.assertNotIn("failed", landed)

    def test_rotate_and_install_do_not_claim_a_finish_they_did_not_get(self) -> None:
        src = DASH.read_text(encoding="utf-8")
        html = HTML.read_text(encoding="utf-8")
        self.assertNotIn("All phones have new identities!", src)
        self.assertNotIn("identity reset ✓", src)
        self.assertNotIn("App installed on all phones!", html)
        self.assertIn('status": "error"', src)
        self.assertIn("No phones connected — nothing to rotate", src)
        self.assertIn("No phones connected — nothing to install", src)
        rotate = src.split('if path == "/api/proxy/rotate":', 1)[1].split(
            'if path == "/api/proxy/teardown":', 1
        )[0]
        self.assertIn("_guest_loopback_pinned", rotate)
        self.assertIn("rotate failed", rotate)
        self.assertIn("pinned < 1", rotate)
        self.assertGreater(rotate.find("run_in_executor"), 0)
        self.assertGreater(rotate.find('json_ok({"ok": True, "n": pinned'), rotate.find("run_in_executor"))
        self.assertNotIn('"started": True', rotate)
        install = src.split('if path == "/api/install":', 1)[1].split(
            'if path == "/api/phone/stop":', 1
        )[0]
        self.assertIn("apk_install_reported", install)
        self.assertNotIn('"Success" in text', install)
        self.assertIn('return json_err(', install)
        stop = html.split("async function stopPhone")[1].split("async function connectDevice")[0]
        self.assertIn("was not powered off", stop)
        self.assertNotIn("was not powered off', 'ok'", stop)

    def test_repin_is_an_error_unless_a_pin_landed(self) -> None:
        src = DASH.read_text(encoding="utf-8")
        html = HTML.read_text(encoding="utf-8")
        teardown = src.split('if path == "/api/proxy/teardown":', 1)[1].split(
            'if path == "/api/identity/reset":', 1
        )[0]
        self.assertIn("if not pinned_ok:", teardown)
        self.assertIn("return json_err(msg)", teardown)
        self.assertIn("len(pinned) < len(phones)", teardown)
        self.assertNotIn("Set Up Now", html[html.find("btn-tor-off"):html.find("btn-tor-off") + 900])
        self.assertIn("res.repinned", html)
        self.assertIn("res.message", html)
        self.assertNotIn("toast('Re-pinned phone exits'", html)

    def test_open_url_log_does_not_say_opened_when_the_tap_failed(self) -> None:
        self.assertEqual(
            _open_url_result_log("vm3", "https://example.com", opened=True),
            "Opened https://example.com on vm3",
        )
        failed = _open_url_result_log("vm3", "https://example.com", opened=False, note="error: device offline")
        self.assertNotIn("Opened", failed)
        self.assertIn("not opened", failed)
        self.assertFalse(am_start_reported_landing("", ""))
        self.assertFalse(am_start_reported_landing("Error: Activity not started", ""))
        self.assertTrue(am_start_reported_landing("Starting: Intent { }", ""))
        self.assertTrue(am_start_reported_landing("", "Warning: Activity not started, intent has been delivered to currently running top-most instance."))
        self.assertTrue(am_start_reported_landing("Warning: Activity not started, its current task has been brought to the front", ""))
        with unittest.mock.patch(
            "automation.dashboard.tor_manager.phone_http_port", return_value=8118
        ):
            self.assertEqual(
                _dead_tor_http_reason(4, "127.0.0.1:8218", {"ok": False, "error": "bootstrap"}),
                "",
            )
            self.assertIn(
                "bootstrap",
                _dead_tor_http_reason(4, "127.0.0.1:8118", {"ok": False, "error": "bootstrap"}),
            )
            self.assertEqual(
                _dead_tor_http_reason(4, "127.0.0.1:8118", {"ok": True}),
                "",
            )

    def test_open_url_refuses_a_page_without_a_loopback_exit(self) -> None:
        src = DASH.read_text(encoding="utf-8")
        html = HTML.read_text(encoding="utf-8")
        body = src.split('if path == "/api/open_url":', 1)[1].split('if path == "/api/teach/start":', 1)[0]
        self.assertIn("No phones are answering ADB", body)
        self.assertIn("_dashboard_open_exit_ready", body)
        self.assertIn("_phones_with_exit", body)
        self.assertIn("No phone has a loopback exit", body)
        self.assertLess(body.find("_phones_with_exit"), body.find("create_task(open_all())"))
        self.assertNotIn("min(int(data.get(\"stagger_secs\", 0)), 3600)", body)
        self.assertNotIn('min(int(data.get("delay_secs", 60)), 3600)', src)
        self.assertNotIn('min(int(data.get("stagger_secs", 0)), 3600)', src)
        self.assertNotIn("stagIn.max = '3600'", html)
        self.assertNotIn("repIn.max = '9999'", html)
        store = (ROOT / "automation" / "playstore.html").read_text(encoding="utf-8")
        self.assertNotIn('max="3600"', store)
        self.assertNotIn('max="50"', store)
        self.assertNotIn('max="600"', store)
        self.assertNotIn('f"Opened {url} on {p[\'name\']}"', body)
        launch = html[html.find("async function launchUrl"):html.find("async function teachRecord")]
        self.assertIn("am_start_reported_landing", body)
        self.assertIn("_dead_tor_http_reason", body)
        self.assertIn('"queued": True', body)
        self.assertNotIn("opened = not _adb_indicates_trouble(res)", body)
        self.assertIn("res.n", launch)
        self.assertIn("res.queued", launch)
        self.assertIn("phone(s) that have an exit", launch)
        self.assertIn("The log says when each page lands", launch)
        self.assertNotIn("Opening on ", launch)
        self.assertNotIn("toast(msg, 'ok')", launch)
        install = html.split("async function installApk", 1)[1].split("function onInstallProgress", 1)[0]
        self.assertNotIn("', 'ok')", install)
        self.assertIn("Install started on", install)
        self.assertNotIn("No phones are answering", launch)
        self.assertNotIn("Opening on all phones", html)
        step = src.split("def run_sequence_step", 1)[1].split("\ndef ", 1)[0]
        self.assertLess(step.find("am_start_reported_landing"), step.find("_bump_farm_visit"))
        self.assertIn("if landed and", step)
        self.assertIn("_dead_tor_http_reason", step)
        launch = src.split('elif t == "launch_app":', 1)[1].split('elif t == "tap":', 1)[0]
        self.assertIn("monkey_launch_reported", launch)
        self.assertNotIn("No activities", launch)
        api_launch = src.split('if path == "/api/launch_app":', 1)[1].split(
            'if path == "/api/input_text":', 1
        )[0]
        self.assertIn("monkey_launch_reported", api_launch)
        self.assertNotIn("_adb_landed(res)", api_launch)
        keys = src.split('if path == "/api/input_key":', 1)[1].split(
            'if path == "/api/quick_action":', 1
        )[0]
        self.assertNotIn("keycode <= 300", keys)
        self.assertIn("keycode < 0", keys)
        self.assertFalse(pm_clear_reported("", ""))
        self.assertFalse(pm_clear_reported("Failed", ""))
        self.assertTrue(pm_clear_reported("Success", ""))
        cookies = src.split('elif t == "clear_cookies":', 1)[1].split(
            'elif t == "type_text":', 1
        )[0]
        self.assertIn("pm_clear_reported", cookies)
        self.assertIn("clear_cookies did not land", cookies)
        self.assertNotIn("return True", cookies)
        self.assertNotIn("continuing with force-stop", cookies)
        close_app = src.split('elif t == "close_app":', 1)[1].split(
            'elif t == "rotate_identity":', 1
        )[0]
        self.assertIn("close_app did not land", close_app)
        self.assertNotIn("return True", close_app)
        runner = (ROOT / "automation" / "sequence_runner.py").read_text(encoding="utf-8")
        self.assertNotIn("ok or True", runner)
        self.assertIn("cookies were not cleared", runner)
        self.assertIn("app was not closed", runner)
        self.assertNotIn("skipped clear_cookies", runner)
        classic = (ROOT / "wizard" / "setup_wizard.py").read_text(encoding="utf-8")
        self.assertIn("app was not closed", classic)
        js = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        classifier = js.split("function classifySetupLine", 1)[1].split("function setBusy", 1)[0]
        self.assertLess(classifier.find("Found 0"), classifier.find("Found [1-9]"))
        self.assertIn("ad tap refused — guest has no loopback exit", runner)

    def test_teach_play_does_not_say_all_phones_when_none_are_answering(self) -> None:
        src = DASH.read_text(encoding="utf-8")
        html = HTML.read_text(encoding="utf-8")
        body = src.split('if path == "/api/teach/play":', 1)[1].split("# ── Tor / identity", 1)[0]
        self.assertIn("No other phone is answering", body)
        self.assertIn("No taps were captured", body)
        self.assertIn('"n": len(phones)', body)
        self.assertNotIn("Teach Mode playback complete", body)
        self.assertNotIn("Playing on all phones", html)
        self.assertNotIn("Playing on ' + res.n", html)
        self.assertNotIn("not confirmed', 'ok'", html)
        wait = src.split('elif t == "wait":', 1)[1].split('elif t == "swipe":', 1)[0]
        self.assertNotIn("min(float(step.get(\"seconds\", 1)), 300)", wait)
        self.assertNotIn("min(300.0,", wait)
        self.assertNotIn("min(retries, 8)", src)
        self.assertIn("rotate did not pin a new loopback exit", src)
        rotate_after = src.split("def _rotate_after", 1)[1].split("async def open_all", 1)[0]
        self.assertIn("_guest_loopback_pinned", rotate_after)
        self.assertNotIn(
            'if result.get("circuit_rotated"):\n                msg = f"{p[\'name\']}: identity rotated',
            rotate_after,
        )
        self.assertNotIn('"max_phones_recommended": 4', src)
        self.assertNotIn("Starting ' + res.phones_targeted", html)
        self.assertNotIn("toast('Stopping ' + res.stopping", html)
        open_step = src.split('if t == "open_url":', 1)[1].split('elif t == "launch_app":', 1)[0]
        self.assertNotIn("min(120.0, base + extra)", open_step)
        classic = (ROOT / "wizard" / "setup_wizard.py").read_text(encoding="utf-8")
        self.assertIn("cookies were not cleared", classic)
        self.assertIn("sequence launch_app did not land", classic)
        self.assertIn("scramble did not land", classic)
        self.assertIn("phone_idx_from_adb_serial", classic)
        self.assertNotIn("ctrl_port = 10050 + idx", classic)
        self.assertNotIn("scramble_device_session(\n                        serial,", classic)
        failed_at = classic.find("sequence open_url failed")
        stored_at = classic.find("last_open_url = url", failed_at)
        # Branch contract: failures return False WITHOUT marking the URL as
        # last-opened (stays retry-able); the dedupe mark only happens after a
        # successful prepare, and the skip-duplicate guard still exists.
        self.assertGreater(stored_at, failed_at)
        self.assertIn("skip duplicate open_url", classic)
        start = src.split('if path == "/api/teach/start":', 1)[1].split(
            'if path == "/api/teach/stop":', 1
        )[0]
        self.assertIn("getevent is not running", start)
        self.assertLess(start.find("start_recording"), start.find("json_ok"))
        ident = src.split('if path == "/api/identity/reset":', 1)[1].split(
            'if path == "/api/identity/reset_all":', 1
        )[0]
        self.assertIn("tor_circuit_rotated", ident)
        self.assertIn("_identity_reset_landed", ident)
        reset_step = src.split('elif t == "full_reset":', 1)[1].split("def _get_resources", 1)[0]
        self.assertIn("_identity_reset_landed", reset_step)
        self.assertNotIn('reset.get("http_proxy_applied")', reset_step)
        self.assertNotIn('"started": True', ident)
        self.assertFalse(
            _identity_reset_log(
                "phone",
                {"tor_circuit_rotated": True, "http_proxy_applied": False, "http_proxy": ":0"},
            ).startswith("phone identity reset — new")
        )
        self.assertIn(
            "not pinned",
            _identity_reset_log(
                "phone",
                {"tor_circuit_rotated": True, "http_proxy_applied": False},
            ),
        )
        self.assertIn(
            "127.0.0.1:8218",
            _identity_reset_log(
                "phone",
                {
                    "tor_circuit_rotated": True,
                    "http_proxy_applied": True,
                    "http_proxy": "127.0.0.1:8218",
                },
            ),
        )
        self.assertNotIn("All done!", (ROOT / "wizard" / "pharmflow_desktop.py").read_text(encoding="utf-8"))

    def test_missing_exit_does_not_count_as_ready(self) -> None:
        from unittest.mock import patch

        with patch("automation.dashboard._adb") as adb, patch(
            "automation.dashboard.pin_guest_proxy", return_value=""
        ):
            adb.return_value.stdout = ":0"
            adb.return_value.text = ":0"
            ok, note = _dashboard_open_exit_ready("10.0.2.16:5555")
        self.assertFalse(ok)
        self.assertIn("no exit proxy", note)

    def test_group_save_and_finish_do_not_claim_work_that_did_not_land(self) -> None:
        src = DASH.read_text(encoding="utf-8")
        html = HTML.read_text(encoding="utf-8")
        self.assertNotIn("Done ✓", src)
        save = src.split('if path == "/api/groups/save":', 1)[1].split(
            'if path == "/api/groups/load":', 1
        )[0]
        self.assertIn("_persist_groups_cfg", save)
        self.assertIn('"saved": True', save)
        self.assertIn("disk copy does not match", save)
        delete = src.split('if path == "/api/groups/delete":', 1)[1].split(
            'if path == "/api/groups/save":', 1
        )[0]
        self.assertIn("_persist_groups_cfg", delete)
        self.assertIn("res.saved !== true", html)
        self.assertIn("res.deleted !== name", html)
        self.assertNotIn("Running ${loadedGroups.length} group(s) in parallel", html)
        self.assertIn("does not mean they finished", src)
        runner = src.split("def _run_steps_adb", 1)[1].split("def _effective_group_repeat", 1)[0]
        self.assertIn("landed is False", runner)
        self.assertIn("did not land", runner)
        self.assertIn('return "stopped"', runner)
        self.assertLess(runner.find("if not ic()"), runner.find("landed is False"))
        mark = src.split("step_fail = _run_steps_adb", 1)[1].split("iteration = 0", 1)[0]
        self.assertIn('result=step_fail', mark)
        self.assertIn('step_fail == "stopped"', mark)
        self.assertIn('result="stopped"', mark)
        self.assertNotIn('result="completed"', mark.split("if step_fail", 1)[0])

    def test_group_finish_log_has_no_checkmark_without_a_completed_phone(self) -> None:
        from automation.dashboard import _group_finish_log, _running_groups, _group_phone_runs

        _running_groups["g1"] = True
        _group_phone_runs.clear()
        try:
            bare = _group_finish_log("g1")
            self.assertNotIn("✓", bare)
            self.assertIn("no completed", bare)
            _group_phone_runs[("g1", "s1")] = {
                "serial": "s1",
                "group": "g1",
                "state": "error",
                "result": "adb failed",
            }
            failed = _group_finish_log("g1")
            self.assertNotIn("✓", failed)
            self.assertIn("no completed", failed)
            _group_phone_runs[("g1", "s2")] = {
                "serial": "s2",
                "group": "g1",
                "state": "done",
                "result": "completed",
            }
            mixed = _group_finish_log("g1")
            self.assertIn("1 phone(s) completed", mixed)
            self.assertIn("1 failed", mixed)
            self.assertNotIn("✓", mixed)
        finally:
            _running_groups.pop("g1", None)
            _group_phone_runs.clear()

    def test_redroid_adb_uses_the_published_port_not_5555_plus_index(self) -> None:
        src = DASH.read_text(encoding="utf-8")
        html = HTML.read_text(encoding="utf-8")
        docker = src.split("def _docker_phone_state", 1)[1].split("async def handle_http", 1)[0]
        self.assertNotIn("5555 + idx", docker)
        self.assertNotIn("5555 + idx", src.split("async def handle_docker_action", 1)[1].split("async def handle_http", 1)[0])
        self.assertFalse(docker_stop_landed(0, 0, "true"))
        self.assertFalse(docker_stop_landed(0, 1, "false"))
        self.assertTrue(docker_stop_landed(0, 0, "false"))
        self.assertIn("_published_host_port", docker)
        self.assertIn("name=redroid-", docker)
        self.assertNotIn("docker-compose.redroid.yml", docker)
        self.assertIn("res.connected", html)
        self.assertIsNone(_host_port_from_docker_port_text(""))
        self.assertEqual(_host_port_from_docker_port_text("0.0.0.0:16001\n"), 16001)
        self.assertEqual(_host_port_from_docker_port_text("127.0.0.1:5557"), 5557)

    def test_stop_does_not_power_off_mumu_with_adb_and_uses_docker_for_redroid(self) -> None:
        src = DASH.read_text(encoding="utf-8")
        html = HTML.read_text(encoding="utf-8")
        body = src.split("def _stop_device_result", 1)[1].split("def get_local_ip", 1)[0]
        code = body.split('"""', 2)[-1]
        self.assertNotIn("reboot", code)
        self.assertIn("emu_kill_landed", body)
        self.assertIn("docker_stop_landed", body)
        self.assertIn("_docker_engine_running", body)
        self.assertFalse(emu_kill_landed("", 0))
        self.assertFalse(emu_kill_landed("KO: unknown command", 0))
        self.assertTrue(emu_kill_landed("OK\n", 0))
        self.assertIn("not powered off", body)
        self.assertIn("not powered off", html)
        self.assertNotIn("Stopping all phones", html)
        self.assertNotIn("toast('Stopping ' + serial", html)
        listing = "redroid-2\t0.0.0.0:16002->5555/tcp\n"
        self.assertEqual(_redroid_name_from_ps_text("127.0.0.1:16002", listing), "redroid-2")
        self.assertIsNone(_redroid_name_from_ps_text("10.0.2.16:5555", listing))

    def test_sequence_open_url_does_not_launch_without_a_loopback_exit(self) -> None:
        src = DASH.read_text(encoding="utf-8")
        body = src.split('if t == "open_url":', 1)[1].split('elif t == "launch_app":', 1)[0]
        exit_at = body.find("_dashboard_open_exit_ready")
        launch_at = body.find("_open_url_with_fallbacks")
        self.assertGreater(exit_at, 0)
        self.assertGreater(launch_at, exit_at)
        self.assertIn("open_url refused", body)
        self.assertIn("return", body[exit_at:launch_at])

    def test_stealth_toggle_does_not_wipe_prefs_or_claim_a_failed_write(self) -> None:
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        import automation.dashboard as dash

        src = DASH.read_text(encoding="utf-8")
        body = src.split("def _write_stealth_prefs", 1)[1].split(
            "def _rotate_every_sequence_enabled", 1
        )[0]
        self.assertIn("return None", body)
        self.assertNotIn("data = {}", body)
        html = HTML.read_text(encoding="utf-8")
        toggle = html.split("async function toggleStealth", 1)[1].split(
            "(async () => {", 1
        )[0]
        self.assertIn("res.saved !== true", toggle)
        self.assertIn("Could not read the current setting", toggle)
        self.assertNotIn(".catch(() => ({}))", toggle)
        with tempfile.TemporaryDirectory() as tmp:
            prefs = Path(tmp) / "desktop_prefs.json"
            prefs.write_text("{not json", encoding="utf-8")
            with patch.object(dash, "DESKTOP_PREFS", prefs):
                self.assertIsNone(dash._write_stealth_prefs(unique_exit_ips=False))
            self.assertEqual(prefs.read_text(encoding="utf-8"), "{not json")
            prefs.write_text(json.dumps({"mumu_setup_complete": True}), encoding="utf-8")
            with patch.object(dash, "DESKTOP_PREFS", prefs):
                stored = dash._write_stealth_prefs(unique_exit_ips=False)
            self.assertIsInstance(stored, dict)
            self.assertTrue(stored.get("mumu_setup_complete"))
            self.assertIs(stored.get("unique_exit_ips"), False)
            disk = json.loads(prefs.read_text(encoding="utf-8"))
            self.assertTrue(disk.get("mumu_setup_complete"))
            self.assertIs(disk.get("unique_exit_ips"), False)

    def test_find_phones_group_stop_and_upload_do_not_claim_work_that_did_not_land(self) -> None:
        src = DASH.read_text(encoding="utf-8")
        refresh = src.split('if path == "/api/devices/refresh":', 1)[1].split(
            'if path == "/api/upload":', 1
        )[0]
        self.assertIn('"n": len(answering)', refresh)
        self.assertIn("No phones are answering", refresh)
        upload = src.split('if path == "/api/upload":', 1)[1].split(
            'if path == "/api/install":', 1
        )[0]
        self.assertIn("stored != raw", upload)
        self.assertIn("disk copy does not match", upload)
        stop = src.split('if path == "/api/groups/stop":', 1)[1].split(
            'if path == "/api/groups/clone":', 1
        )[0]
        self.assertIn("No groups are running", stop)
        self.assertIn('"stopping": stopping', stop)
        clone = src.split('if path == "/api/groups/clone":', 1)[1].split(
            'if path == "/api/groups/phone_steps":', 1
        )[0]
        self.assertNotIn("1440", clone)
        html = HTML.read_text(encoding="utf-8")
        self.assertNotIn("Finding phones", html)
        self.assertIn("phone(s) answering", html)
        self.assertNotIn("Stopping all groups", html)
        self.assertIn("up.saved !== true", html)
        setup = src.split('if path == "/api/proxy/setup":', 1)[1].split(
            'if path == "/api/proxy/rotate":', 1
        )[0]
        wait_at = setup.find("run_in_executor")
        ok_at = setup.find('json_ok({"ok": True, "n": pinned')
        self.assertGreater(wait_at, 0)
        self.assertGreater(ok_at, wait_at)
        self.assertIn("pinned < 1", setup)
        self.assertNotIn("Setting up different locations", html)
        self.assertIn("have a loopback exit", html)
        badge = html.split("const uniq = new Set(ips).size;", 1)[1].split("if (asof)", 1)[0]
        self.assertIn("no exit IPs yet", badge)
        self.assertLess(badge.find("uniq > 0"), badge.find("var(--g, #3fb950)"))
        self.assertIn("var(--t2)", badge)

    def test_corrupt_groups_and_prefs_are_not_replaced_with_empty(self) -> None:
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        import automation.dashboard as dash

        src = DASH.read_text(encoding="utf-8")
        load = src.split("def _load_groups_cfg", 1)[1].split("def _persist_groups_cfg", 1)[0]
        self.assertIn("the file was not replaced", load)
        self.assertNotIn("groups_config.corrupt_", src)
        remap = src.split("def _remap_group_serials_to_live", 1)[1].split(
            "def _sync_phone_serials_prefs", 1
        )[0]
        self.assertIn("_persist_groups_cfg", remap)
        self.assertNotIn("except OSError:\n            pass", remap)
        self.assertIn("disk copy does not match", src)
        with tempfile.TemporaryDirectory() as tmp:
            groups = Path(tmp) / "groups_config.json"
            groups.write_text("{not json", encoding="utf-8")
            prefs = Path(tmp) / "desktop_prefs.json"
            prefs.write_text("{not json", encoding="utf-8")
            with patch.object(dash, "GROUPS_CFG", groups), patch.object(dash, "REC_DIR", Path(tmp)):
                loaded, err = dash._load_groups_cfg()
                self.assertIsNone(loaded)
                self.assertIn("not replaced", err)
                self.assertFalse(dash._sync_phone_serials_prefs(["10.0.2.20:5555"]))
            self.assertEqual(groups.read_text(encoding="utf-8"), "{not json")
            self.assertEqual(prefs.read_text(encoding="utf-8"), "{not json")
            groups.write_text(json.dumps({"groups": [{"name": "A", "phones": {}}]}), encoding="utf-8")
            prefs.write_text(json.dumps({"mumu_setup_complete": True}), encoding="utf-8")
            with patch.object(dash, "GROUPS_CFG", groups), patch.object(dash, "REC_DIR", Path(tmp)):
                loaded, err = dash._load_groups_cfg()
                self.assertEqual(err, "")
                self.assertEqual(loaded["groups"][0]["name"], "A")
                self.assertTrue(dash._sync_phone_serials_prefs(["10.0.2.20:5555"]))
            disk = json.loads(prefs.read_text(encoding="utf-8"))
            self.assertTrue(disk.get("mumu_setup_complete"))
            self.assertEqual(disk.get("phone_serials"), ["10.0.2.20:5555"])

    def test_app_tester_does_not_claim_a_launch_adb_did_not_land(self) -> None:
        src = DASH.read_text(encoding="utf-8")
        launch = src.split('if path == "/api/launch_app":', 1)[1].split(
            'if path == "/api/input_text":', 1
        )[0]
        self.assertIn("monkey_launch_reported", launch)
        self.assertIn("did not launch", launch)
        self.assertIn("No phones are answering", launch)
        self.assertLess(launch.find("json_err"), launch.find('return json_ok'))
        typed = src.split('if path == "/api/input_text":', 1)[1].split(
            'if path == "/api/input_key":', 1
        )[0]
        self.assertIn("input did not land", typed)
        store = (ROOT / "automation" / "playstore.py").read_text(encoding="utf-8")
        open_fn = store.split("def open_store_page_serial", 1)[1].split("def search_store", 1)[0]
        self.assertIn("am_start_reported_landing", store)
        self.assertIn("return not _intent_failed(fallback)", open_fn)
        self.assertIn("if not _intent_failed(result)", open_fn)
        install = store.split("def install_from_store", 1)[1].split("def launch_app", 1)[0]
        self.assertIn("Install was not tapped", install)
        self.assertIn("Install tap did not land", install)
        self.assertNotIn("tapped Install", install)
        review = store.split("def leave_review", 1)[1].split("def run_full_sequence", 1)[0]
        self.assertIn("review was not sent", review)
        self.assertIn("review tap did not land", review)
        self.assertNotIn("review submitted", review)
        run = store.split("def run_full_sequence", 1)[1]
        self.assertIn("search did not open", run)
        self.assertIn('"landed": landed', run)
        launch_fn = store.split("def launch_app", 1)[1].split("def leave_review", 1)[0]
        self.assertIn("monkey_launch_reported", launch_fn)
        self.assertIn("did not launch", launch_fn)
        html = (ROOT / "automation" / "playstore.html").read_text(encoding="utf-8")
        self.assertNotIn("Test loop done!", html)
        self.assertNotIn("All done!", html)
        self.assertNotIn("Sent to ", html)
        self.assertIn("No phone launched the app", html)
        self.assertIn("did not land on any phone", html)
        deck = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        setup = deck.split("async function runSetupAction", 1)[1].split("async function refreshMachineCaps", 1)[0]
        self.assertNotIn("complete", setup)
        settings = (ROOT / "wizard" / "gui" / "windows.py").read_text(encoding="utf-8")
        self.assertNotIn("10.0.2.2", settings)

    def test_setup_does_not_claim_ready_while_fingerprint_leaks(self) -> None:
        src = (ROOT / "wizard" / "mumu_setup_core.py").read_text(encoding="utf-8")
        refresh = src.split("Phone Setup already completed", 1)[1].split("if awaiting:", 1)[0]
        self.assertLess(refresh.find("fingerprint leak"), refresh.find("return True"))
        self.assertIn("setup_complete=False", refresh)
        fresh = src.split("Saving tap lists", 1)[1]
        self.assertLess(fresh.find("setup_complete=False"), fresh.find("setup_complete=True"))
        self.assertNotIn("minor fingerprint warning", src)
        self.assertNotIn("Phones are ready. Next:", src)
        # Branch honesty contract (deliberate change from main): windowless
        # phones (ADB up, player hidden) count as usable for farm/setup, and
        # partial boots carry partial=True + a warning instead of failing.
        boot = (ROOT / "wizard" / "pharmflow_wizard_bridge.py").read_text(encoding="utf-8")
        self.assertIn("not a visible player (VM left running)", boot)
        self.assertIn('"windowless": len(windowless)', boot)
        self.assertIn('payload["partial"] = True', boot)

    def test_corrupt_desktop_prefs_are_not_replaced(self) -> None:
        import tempfile

        from wizard.mumu_setup_core import write_desktop_prefs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prefs = root / "automation" / "recordings" / "desktop_prefs.json"
            prefs.parent.mkdir(parents=True)
            prefs.write_text("{not json", encoding="utf-8")
            with self.assertRaises(OSError):
                write_desktop_prefs(["10.0.2.20:5555"], root, setup_complete=True)
            self.assertEqual(prefs.read_text(encoding="utf-8"), "{not json")


    def test_partial_tor_setup_and_rotate_are_not_a_green_finish(self) -> None:
        html = HTML.read_text(encoding="utf-8")
        setup = html.split("async function setupTor", 1)[1].split("async function teach", 1)[0]
        self.assertIn("of ' + targeted", setup)
        self.assertIn("The rest were not pinned", setup)
        rotate = html.split("btn-tor-rotate", 1)[1].split("function dockRotate", 1)[0]
        self.assertIn("The rest did not", rotate)
        src = DASH.read_text(encoding="utf-8")
        body = src.split("def setup() -> int:", 1)[1].split("return pinned", 1)[0]
        self.assertIn("Tor setup incomplete", body)
        self.assertNotIn("Tor setup finished — {pinned} of", body)

    def test_earn_mix_save_is_not_a_green_finish_unless_the_file_was_written(self) -> None:
        html = HTML.read_text(encoding="utf-8")
        block = html.split("btn-earn-save", 1)[1].split("serviceWorker", 1)[0]
        self.assertIn("plan.saved !== true", block)
        self.assertLess(block.find("plan.saved !== true"), block.find("farm reads it while running', 'ok'"))
        src = DASH.read_text(encoding="utf-8")
        self.assertIn("save_earn_plan(body)", src)


class AgentSettingsGuardTests(unittest.TestCase):
    def test_corrupt_agent_settings_are_not_replaced(self) -> None:
        import tempfile

        import wizard.pharmflow_wizard_bridge as bridge

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cloud_agent.json"
            path.write_text("{not json", encoding="utf-8")
            with unittest.mock.patch.object(bridge, "_agent_config_path", return_value=path):
                out = bridge.save_cloud_agent_config(base="https://example.invalid", model="x")
            self.assertFalse(out.get("ok"))
            self.assertEqual(path.read_text(encoding="utf-8"), "{not json")


class PlayStoreLandingTests(unittest.TestCase):
    def test_install_does_not_succeed_when_the_tap_misses(self) -> None:
        import automation.playstore as store

        with unittest.mock.patch.object(store, "open_store_page_serial", return_value=True), \
                unittest.mock.patch.object(store, "_scale", return_value=(1, 1)), \
                unittest.mock.patch.object(store, "_tap", return_value=False):
            self.assertFalse(store.install_from_store("10.0.2.15:5555", "com.example.app"))

    def test_run_does_not_count_a_phone_when_search_does_not_open(self) -> None:
        import automation.playstore as store

        done: list[dict] = []
        phones = [{"serial": "10.0.2.15:5555", "name": "p", "running": True}]
        with unittest.mock.patch.object(store, "search_store", return_value=False), \
                unittest.mock.patch.object(store.time, "sleep"):
            thread = store.run_full_sequence(
                phones, "", "query", 0, "", 0, on_complete=done.append,
            )
            thread.join(5)
        self.assertEqual(done, [{"landed": 0, "failed": 1, "targeted": 1}])


if __name__ == "__main__":
    unittest.main()
