"""Local redroid connect must use published Docker ports, not 5555..5562."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cloud_phones.redroid_local as redroid  # noqa: E402


class RedroidPortTests(unittest.TestCase):
    def test_published_ports_are_not_capped_at_eight(self) -> None:
        blob = "\n".join(
            f"0.0.0.0:{5555 + i}->5555/tcp" for i in range(10)
        )
        with (
            patch.object(redroid.docker_guard, "engine_running", return_value=True),
            patch.object(redroid, "_run", return_value=(0, blob)),
        ):
            ports = redroid.published_redroid_ports()
        self.assertEqual(ports, list(range(5555, 5565)))

    def test_engine_down_does_not_call_docker(self) -> None:
        with (
            patch.object(redroid.docker_guard, "engine_running", return_value=False),
            patch.object(redroid, "_run") as run,
        ):
            ports = redroid.published_redroid_ports()
        self.assertEqual(ports, [])
        run.assert_not_called()

    def test_connect_uses_published_ports(self) -> None:
        calls: list[list[str]] = []

        def _run(cmd: list[str], timeout: int = 900, capture: bool = True):
            calls.append(list(cmd))
            return 0, ""

        with (
            patch.object(redroid, "published_redroid_ports", return_value=[5555, 5600, 5701]),
            patch.object(redroid, "_run", side_effect=_run),
        ):
            redroid._connect_all("adb")
        self.assertEqual(
            [cmd[-1] for cmd in calls],
            ["127.0.0.1:5555", "127.0.0.1:5600", "127.0.0.1:5701"],
        )

    def test_compose_create_is_not_capped_at_eight(self) -> None:
        text = redroid.render_compose(12)
        self.assertIn("redroid-11:", text)
        self.assertNotIn("redroid-12:", text)
        self.assertEqual(text.count("container_name:"), 12)

    def test_up_without_count_does_not_invent_eight(self) -> None:
        self.assertIsNone(redroid.parse_create_count(["up"]))
        self.assertEqual(redroid.parse_create_count(["up", "--count", "20"]), 20)

    def test_project_agent_up_does_not_invent_a_count(self) -> None:
        src = (ROOT / "tools" / "project_agent.py").read_text(encoding="utf-8")
        self.assertIn("emulator up needs --count", src)
        self.assertIn("write_compose(count, COMPOSE)", src)

    def test_checked_in_compose_does_not_create_eight_phones(self) -> None:
        text = (ROOT / "cloud_phones" / "docker-compose.redroid.yml").read_text(encoding="utf-8")
        self.assertNotIn("redroid-0:", text)
        self.assertNotIn("container_name:", text)

    def test_source_has_no_eight_port_list(self) -> None:
        src = (ROOT / "cloud_phones" / "redroid_local.py").read_text(encoding="utf-8")
        self.assertNotIn("range(8)", src)
        body = src.split("def _connect_all", 1)[1].split("\ndef ", 1)[0]
        self.assertNotIn("5555", body)


if __name__ == "__main__":
    unittest.main()
