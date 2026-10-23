"""A JavaScript shell is not a successful site map."""
from __future__ import annotations

import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import site_mapper  # noqa: E402


SHELL = (
    "<!doctype html><html><head><title>App</title>"
    '<script src="/static/app.js"></script></head>'
    '<body><div id="root"></div></body></html>'
)
BUNDLE = 'const routes = [{path: "/pricing"}, {path: "/account"}];'


class SiteMapperWebappTests(unittest.TestCase):
    def test_shell_with_no_routes_is_not_a_successful_map(self) -> None:
        with unittest.mock.patch.object(site_mapper, "fetch_html", return_value=SHELL):
            with unittest.mock.patch.object(site_mapper, "fetch_text", return_value="console.log(1)"):
                out = site_mapper.scan_site("https://example.com")
        self.assertFalse(out["ok"])
        self.assertEqual(out["pages"], [])
        self.assertIn("web app shell", out["error"])

    def test_same_host_script_routes_are_mapped(self) -> None:
        def _html(url: str, timeout: int = 12) -> str:
            return SHELL

        with unittest.mock.patch.object(site_mapper, "fetch_html", side_effect=_html):
            with unittest.mock.patch.object(site_mapper, "fetch_text", return_value=BUNDLE) as fetched:
                out = site_mapper.scan_site("https://example.com")
        fetched.assert_called()
        self.assertTrue(out["ok"])
        urls = {p["url"].rstrip("/") for p in out["pages"]}
        self.assertIn("https://example.com/pricing", urls)
        self.assertIn("https://example.com/account", urls)
        self.assertTrue(any(p.get("read_as") == "webapp_shell" for p in out["pages"]))

    def test_third_party_script_is_not_fetched(self) -> None:
        html = SHELL.replace("/static/app.js", "https://cdn.example.net/app.js")
        with unittest.mock.patch.object(site_mapper, "fetch_html", return_value=html):
            with unittest.mock.patch.object(site_mapper, "fetch_text") as fetched:
                out = site_mapper.scan_site("https://example.com")
        fetched.assert_not_called()
        self.assertFalse(out["ok"])

    def test_static_page_with_a_heading_still_maps(self) -> None:
        html = "<html><title>Docs</title><h1>Hello</h1><p>Body</p></html>"
        with unittest.mock.patch.object(site_mapper, "fetch_html", return_value=html):
            out = site_mapper.scan_site("https://example.com")
        self.assertTrue(out["ok"])
        self.assertEqual(out["pages"][0]["read_as"], "html")

    def test_switch_screen_names_become_action_deep_links(self) -> None:
        html = (
            "<!doctype html><html><head><title>App</title>"
            '<script src="/app.js"></script></head>'
            '<body><div id="root"></div>'
            '<nav data-screen="home"></nav><nav data-screen="stats"></nav>'
            '<div id="settings-screen"></div></body></html>'
        )
        bundle = "function go(){ switchScreen('stats'); switchScreen('glass'); }"

        def _html(url: str, timeout: int = 12) -> str:
            return html

        with unittest.mock.patch.object(site_mapper, "fetch_html", side_effect=_html):
            with unittest.mock.patch.object(site_mapper, "fetch_text", return_value=bundle):
                out = site_mapper.scan_site("https://example.com")
        self.assertTrue(out["ok"])
        urls = {p["url"] for p in out["pages"]}
        self.assertIn("https://example.com/?action=stats", urls)
        self.assertIn("https://example.com/?action=glass", urls)
        self.assertIn("https://example.com/?action=settings", urls)
        home = next(p for p in out["pages"] if "action=" not in p["url"])
        self.assertIn("stats", home.get("screens") or [])
        draft = site_mapper.build_starter_sequence(
            "https://example.com",
            pages=list(out["pages"]),
        )
        step_urls = [s.get("url") for s in draft["steps"] if s.get("type") == "open_url"]
        self.assertTrue(any("action=stats" in str(u) for u in step_urls))
        self.assertIn("glass", draft.get("screens") or [])


if __name__ == "__main__":
    unittest.main()
