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

AGE_SPA = (
    "<!doctype html><html><head><title>App</title>"
    '<script src="/app.js"></script></head>'
    '<body data-theme="x"><div id="app"></div>'
    '<div id="age-gate" class="age-gate">'
    '<button>Yes, I am 21+</button><button>No</button></div>'
    '<nav data-screen="home"></nav><nav data-screen="timer"></nav>'
    '<nav data-screen="stats"></nav><nav data-screen="glass"></nav>'
    '<nav data-screen="settings"></nav>'
    '<div id="home-screen"></div><div id="timer-screen"></div>'
    '<div id="stats-screen"></div><div id="glass-screen"></div>'
    '<div id="settings-screen"></div></body></html>'
)


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
        # Split SPA: one page per tab (home keeps start URL when no age gate).
        self.assertTrue(
            "https://example.com/?action=stats" in urls
            or any((p.get("screens") or []) == ["stats"] for p in out["pages"])
        )
        self.assertTrue(
            "https://example.com/?action=glass" in urls
            or any((p.get("screens") or []) == ["glass"] for p in out["pages"])
        )
        self.assertTrue(
            "https://example.com/?action=settings" in urls
            or any((p.get("screens") or []) == ["settings"] for p in out["pages"])
        )
        draft = site_mapper.build_starter_sequence(
            "https://example.com",
            pages=list(out["pages"]),
        )
        open_urls = [s.get("url") for s in draft["steps"] if s.get("type") == "open_url"]
        self.assertEqual(len(open_urls), 1)
        self.assertIn("glass", draft.get("screens") or [])
        self.assertTrue(any(s.get("bottom_nav") and "stats" in str(s.get("note")) for s in draft["steps"]))

    def test_age_gate_is_own_node_and_tabs_use_bottom_nav(self) -> None:
        def _html(url: str, timeout: int = 12) -> str:
            return AGE_SPA

        with unittest.mock.patch.object(site_mapper, "fetch_html", side_effect=_html):
            with unittest.mock.patch.object(site_mapper, "fetch_text", return_value="switchScreen('stats');"):
                out = site_mapper.scan_site("https://example.com")
        self.assertTrue(out["ok"])
        roles = [p.get("role") or p.get("read_as") for p in out["pages"]]
        self.assertIn("age_gate", roles)
        gate = next(p for p in out["pages"] if p.get("role") == "age_gate")
        self.assertEqual(gate.get("screens"), ["age_gate"])
        tab_screens = [
            (p.get("screens") or [None])[0]
            for p in out["pages"]
            if p.get("role") == "webapp_tab"
        ]
        for name in ("home", "timer", "stats", "glass", "settings"):
            self.assertIn(name, tab_screens)
        draft = site_mapper.build_starter_sequence(
            "https://example.com",
            pages=list(out["pages"]),
        )
        self.assertTrue(draft.get("age_gate"))
        opens = [s for s in draft["steps"] if s.get("type") == "open_url"]
        self.assertEqual(len(opens), 1)
        self.assertTrue(
            any(
                s.get("type") == "tap"
                and (s.get("age_gate") or s.get("checkpoint") == "age_verification")
                for s in draft["steps"]
            )
        )
        nav_tabs = [
            str(s.get("note") or "").replace("webapp tab:", "")
            for s in draft["steps"]
            if s.get("bottom_nav")
        ]
        for name in ("timer", "stats", "glass", "settings"):
            self.assertIn(name, nav_tabs)
        # No blind deep-link open_url after the gate.
        self.assertFalse(any("action=" in str(s.get("url") or "") for s in opens))


if __name__ == "__main__":
    unittest.main()
