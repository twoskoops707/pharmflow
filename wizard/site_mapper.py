"""
Site Map — scan a website into a navigable map and generate a starter
farm sequence draft the user can refine in Steps/Builder.

Stdlib-only (urllib + html.parser) so it runs inside the frozen EXE
with no extra dependencies. All network I/O is read-only GET.
"""

from __future__ import annotations

import json
import os
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, urljoin
from urllib.request import Request, urlopen

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
FETCH_TIMEOUT = 12
MAX_BYTES = 400_000
SKIP_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
    ".css", ".js", ".json", ".xml", ".pdf", ".zip", ".gz",
    ".mp4", ".webm", ".mp3", ".woff", ".woff2", ".ttf", ".eot",
)
SKIP_PREFIXES = ("javascript:", "mailto:", "tel:", "data:", "#")
_ROUTE_IN_SCRIPT = re.compile(
    r"""(?:\bpath|\bto|\bpathname)\s*:\s*['"](/[^'"?#\s]*)['"]"""
)
_JSON_PATH = re.compile(r'''"(?:path|pathname|href)"\s*:\s*"(/(?:[^"\\]|\\.)*)"''')
# In-app screens (DabFlow switchScreen, data-screen nav). Not URL routes.
_SWITCH_SCREEN = re.compile(
    r"""(?:switchScreen|showScreen|navigateTo|openScreen)\(\s*['"]([a-zA-Z][\w-]*)['"]"""
)
_SKIP_SCREEN_NAMES = frozenset(
    {
        "app",
        "root",
        "main",
        "content",
        "wrapper",
        "container",
        "modal",
        "overlay",
        "loading",
        "spinner",
    }
)


class _SiteParser(HTMLParser):
    """Collects title, links, forms, buttons, inputs, headings from one page."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_parts: list[str] = []
        self.in_title = False
        self.link_stack = 0
        self.link_href: str | None = None
        self.link_text: list[str] = []
        self.links: list[dict] = []
        self.external_links: list[dict] = []
        self.form: dict | None = None
        self.forms: list[dict] = []
        self.buttons: list[str] = []
        self.inputs: list[dict] = []
        self.headings: list[tuple[str, str]] = []
        self.screens: list[str] = []
        # None when not inside <button>; [] only while collecting button text.
        self._btn_buf: list[str] | None = None
        self._h_tag: str | None = None
        self._h_buf: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        a = dict(attrs)
        for key in ("data-screen", "data-nav", "data-target", "data-view"):
            raw = (a.get(key) or "").strip()
            if raw and re.match(r"^[a-zA-Z][\w-]*$", raw):
                self.screens.append(raw.lower())
        eid = (a.get("id") or "").strip()
        low_id = eid.lower()
        if low_id.endswith("-screen"):
            stem = eid[: -len("-screen")]
            if re.match(r"^[a-zA-Z][\w-]*$", stem):
                self.screens.append(stem.lower())
        if tag == "title":
            self.in_title = True
        elif tag == "a":
            self.link_stack += 1
            self.link_href = (a.get("href") or "").strip()
            self.link_text = []
        elif tag == "form":
            self.form = {
                "action": (a.get("action") or "").strip(),
                "method": (a.get("method") or "get").upper(),
                "inputs": [],
            }
        elif tag == "input":
            inp = {
                "name": (a.get("name") or "").strip(),
                "type": (a.get("type") or "text").lower(),
                "placeholder": (a.get("placeholder") or "").strip(),
            }
            self.inputs.append(inp)
            if self.form is not None:
                self.form["inputs"].append(inp)
        elif tag == "textarea":
            inp = {
                "name": (a.get("name") or "").strip(),
                "type": "textarea",
                "placeholder": (a.get("placeholder") or "").strip(),
            }
            self.inputs.append(inp)
            if self.form is not None:
                self.form["inputs"].append(inp)
        elif tag == "select":
            inp = {
                "name": (a.get("name") or "").strip(),
                "type": "select",
                "placeholder": "",
            }
            self.inputs.append(inp)
            if self.form is not None:
                self.form["inputs"].append(inp)
        elif tag == "button":
            self._btn_buf = []
        elif tag in ("h1", "h2", "h3", "h4"):
            self._h_tag = tag
            self._h_buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        elif tag == "a" and self.link_stack > 0:
            self.link_stack -= 1
            href = self.link_href or ""
            text = " ".join("".join(self.link_text).split())
            self.link_href = None
            if href and not href.startswith(SKIP_PREFIXES):
                full = urljoin(self.base_url, href)
                entry = {"url": full, "text": text[:80]}
                if _same_host(self.base_url, full):
                    self.links.append(entry)
                else:
                    self.external_links.append(entry)
        elif tag == "form":
            # Keep forms that declare fields or a non-empty action (textarea-only, etc.).
            if self.form is not None and (self.form["inputs"] or self.form["action"]):
                self.forms.append(self.form)
            self.form = None
        elif tag == "button":
            if self._btn_buf is not None:
                txt = " ".join("".join(self._btn_buf).split())
                if txt:
                    self.buttons.append(txt[:60])
            self._btn_buf = None
        elif tag in ("h1", "h2", "h3", "h4"):
            txt = " ".join("".join(self._h_buf).split())
            if txt:
                self.headings.append((tag, txt[:120]))
            self._h_tag = None
            self._h_buf = []

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if self.link_stack > 0:
            self.link_text.append(data)
        if self._btn_buf is not None:
            self._btn_buf.append(data)
        if self._h_tag is not None:
            self._h_buf.append(data)


def _same_host(base: str, url: str) -> bool:
    b = urlsplit(base)
    u = urlsplit(url)
    return u.scheme in ("http", "https") and u.netloc.lower() == b.netloc.lower()


def _dedupe(items: list) -> list:
    seen = set()
    out = []
    for it in items:
        key = it if isinstance(it, str) else json.dumps(it, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def normalize_url(raw: str) -> str | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", raw):
        raw = "https://" + raw
    u = urlsplit(raw)
    if u.scheme not in ("http", "https") or not u.netloc:
        return None
    host = u.netloc.split("@")[-1].split(":")[0].strip().lower()
    if " " in u.netloc or not host:
        return None
    # Allow localhost / IPv6 / dotted hosts; reject bare words with no host shape.
    if host not in ("localhost",) and "." not in host and ":" not in u.netloc and not host.startswith("["):
        return None
    path = u.path or "/"
    return urlsplit(raw)._replace(path=path, fragment="").geturl()


def fetch_html(url: str, timeout: int = FETCH_TIMEOUT) -> str | None:
    """GET one page, return decoded HTML (capped) or None for non-HTML."""
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        data = resp.read(MAX_BYTES)
        # Many servers omit Content-Type; sniff HTML when header is empty/generic.
        if ctype and "html" not in ctype and "text/plain" not in ctype and "octet-stream" not in ctype:
            return None
        if ctype and "html" not in ctype and "text/plain" not in ctype:
            head = data[:256].lstrip().lower()
            if not (head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<html" in head[:200]):
                return None
    for enc in ("utf-8", "iso-8859-1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _mount_present(html: str) -> bool:
    low = (html or "").lower()
    return any(
        mark in low
        for mark in (
            'id="root"',
            "id='root'",
            'id="app"',
            "id='app'",
            'id="__next"',
            'id="__nuxt"',
        )
    )


def _script_sources(html: str, base_url: str) -> list[str]:
    out: list[str] = []
    for match in re.finditer(r"""<script\b[^>]*\bsrc=['"]([^'"]+)['"]""", html or "", re.I):
        src = (match.group(1) or "").strip()
        if not src or src.startswith(SKIP_PREFIXES):
            continue
        full = urljoin(base_url, src)
        if _same_host(base_url, full):
            out.append(full)
    return out


def routes_from_webapp_source(text: str, base_url: str) -> list[str]:
    """Same-host routes declared in a bundle or JSON payload. Not guessed."""
    found: list[str] = []
    seen: set[str] = set()
    blob = text or ""
    for pattern in (_ROUTE_IN_SCRIPT, _JSON_PATH):
        for match in pattern.finditer(blob):
            raw = match.group(1)
            if pattern is _JSON_PATH:
                raw = raw.replace("\\/", "/")
            if not raw.startswith("/") or raw.startswith("//"):
                continue
            full = urljoin(base_url, raw)
            if not _same_host(base_url, full):
                continue
            path = urlsplit(full).path.lower()
            if path.endswith(SKIP_SUFFIXES):
                continue
            key = urlsplit(full)._replace(fragment="").geturl().rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            found.append(key)
    return found


def screens_from_webapp_source(text: str) -> list[str]:
    """In-app screen names from switchScreen / showScreen style calls."""
    found: list[str] = []
    seen: set[str] = set()
    for match in _SWITCH_SCREEN.finditer(text or ""):
        name = (match.group(1) or "").strip().lower()
        if not name or name in _SKIP_SCREEN_NAMES or name in seen:
            continue
        seen.add(name)
        found.append(name)
    return found


def normalize_screen_names(*groups: list[str]) -> list[str]:
    """Stable unique screen names. Prefer home first when present."""
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for raw in group or []:
            name = str(raw or "").strip().lower()
            if not name or name in _SKIP_SCREEN_NAMES or name in seen:
                continue
            if not re.match(r"^[a-z][\w-]*$", name):
                continue
            seen.add(name)
            out.append(name)
    if "home" in seen:
        out = ["home"] + [n for n in out if n != "home"]
    return out


def screen_deep_link(base_url: str, screen: str) -> str:
    """Deep link many web apps honor via ?action=<screen> (DabFlow does)."""
    start = normalize_url(base_url) or base_url
    parts = urlsplit(start)
    # Keep path; replace query with the screen action.
    return parts._replace(query=f"action={screen}", fragment="").geturl()


def fetch_text(url: str, timeout: int = FETCH_TIMEOUT) -> str | None:
    """GET a text body. Used for same-host script bundles, which are not HTML."""
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read(MAX_BYTES)
    return data.decode("utf-8", errors="replace")


def _webapp_route_page(url: str, fetch_error: str) -> dict:
    return {
        "url": url,
        "title": "",
        "headings": [],
        "links": [],
        "link_count": 0,
        "external_links": [],
        "forms": [],
        "form_count": 0,
        "buttons": [],
        "inputs": [],
        "routes": [],
        "screens": [],
        "read_as": "webapp_route",
        "fetch_error": fetch_error,
    }


def _queue_script_routes(
    html: str,
    page_url: str,
    start: str,
    seen: set[str],
    to_visit: list[str],
    declared_routes: set[str],
    errors: list[dict],
    timeout: int,
) -> tuple[list[str], list[str]]:
    """Read same-host bundles for declared routes and switchScreen names."""
    found: list[str] = []
    screens: list[str] = []
    seen_routes: set[str] = set()
    blobs = [html or ""]
    for src in _script_sources(html, page_url):
        try:
            body = fetch_text(src, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 — one bundle must not hide the rest
            errors.append({"url": src, "error": "script: " + str(exc)[:100]})
            continue
        if body:
            blobs.append(body)
    for blob in blobs:
        screens.extend(screens_from_webapp_source(blob))
        for route in routes_from_webapp_source(blob, start):
            if route in seen_routes:
                continue
            seen_routes.add(route)
            found.append(route)
            declared_routes.add(route)
            if route not in seen and route not in to_visit:
                to_visit.append(route)
    return found, normalize_screen_names(screens)


def _is_webapp_shell(html: str, page: dict) -> bool:
    """True for a JS mount with no crawlable links, forms, buttons, or headings."""
    if not _mount_present(html):
        return False
    if "<script" not in (html or "").lower():
        return False
    return not (
        page.get("links")
        or page.get("forms")
        or page.get("buttons")
        or page.get("headings")
    )


def scan_site(
    url: str,
    max_pages: int | None = None,
    timeout: int = FETCH_TIMEOUT,
) -> dict:
    """Crawl same-host pages from ``url`` and return the site map.

    A JavaScript shell with a mount node and no links is not a successful map.
    Same-host script bundles are read for declared routes. A shell with no
    routes returns ok False. Third-party script URLs are not crawled.
    """
    # No default page ceiling. An operator env limit is optional and must be
    # reported as truncated — it is not a silent "the site was fully mapped".
    if max_pages is None:
        raw_limit = (os.environ.get("PHARMFLOW_SITE_MAP_MAX_PAGES") or "").strip()
        if raw_limit:
            try:
                max_pages = int(raw_limit)
            except (TypeError, ValueError):
                max_pages = None
    if max_pages is not None:
        max_pages = max(1, int(max_pages))
    start = normalize_url(url)
    if not start:
        return {"ok": False, "error": "Enter a valid URL like https://example.com"}
    host = urlsplit(start).netloc.lower()
    started = time.time()

    to_visit = [start]
    seen: set[str] = set()
    pages: list[dict] = []
    errors: list[dict] = []
    # Routes declared in a same-host bundle. A 404 on the route URL is still a
    # mapped page: the phone browser loads the shell and the client router runs.
    declared_routes: set[str] = set()

    while to_visit and (max_pages is None or len(pages) < max_pages):
        cur = to_visit.pop(0)
        key = urlsplit(cur)._replace(fragment="").geturl().rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        try:
            html = fetch_html(cur, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 — report any fetch failure
            if key in declared_routes:
                pages.append(_webapp_route_page(cur, str(exc)[:120]))
            else:
                errors.append({"url": cur, "error": str(exc)[:120]})
            continue
        if html is None:
            if key in declared_routes:
                pages.append(_webapp_route_page(cur, "empty response"))
            continue

        p = _SiteParser(cur)
        try:
            p.feed(html)
        except Exception:  # noqa: BLE001 — partial parse is fine
            pass

        # Queue every same-host link before any display trim. The stored page
        # keeps a short sample for the deck; the crawl frontier must not.
        for link in p.links:
            u = urlsplit(link["url"])._replace(fragment="").geturl()
            u = u.rstrip("/")
            if (
                u not in seen
                and u not in to_visit
                and _same_host(start, link["url"])
                and not urlsplit(u).path.lower().endswith(SKIP_SUFFIXES)
            ):
                to_visit.append(u)

        all_links = _dedupe(p.links)
        all_forms = [
            {
                "action": f["action"] or "(same page)",
                "method": f["method"],
                "inputs": _dedupe(f["inputs"]),
            }
            for f in p.forms
        ]
        page = {
            "url": cur,
            "title": " ".join("".join(p.title_parts).split())[:160],
            "headings": [
                {"level": lvl, "text": txt}
                for lvl, txt in _dedupe(p.headings)
            ],
            "links": all_links,
            "link_count": len(all_links),
            "external_links": _dedupe(p.external_links),
            "forms": all_forms,
            "form_count": len(all_forms),
            "buttons": _dedupe(p.buttons),
            "inputs": _dedupe(p.inputs),
            "routes": [],
            "screens": [],
            "read_as": "html",
        }
        if key in declared_routes:
            page["read_as"] = "webapp_route"
        elif _is_webapp_shell(html, page):
            page["read_as"] = "webapp_shell"
        html_screens = normalize_screen_names(list(p.screens))
        script_screens: list[str] = []
        if _mount_present(html) and "<script" in (html or "").lower():
            routes, script_screens = _queue_script_routes(
                html,
                cur,
                start,
                seen,
                to_visit,
                declared_routes,
                errors,
                timeout,
            )
            page["routes"] = routes
        page["screens"] = normalize_screen_names(html_screens, script_screens)
        if page["screens"] and page["read_as"] == "html" and not page["links"]:
            page["read_as"] = "webapp_screens"
        pages.append(page)

        # Deep-link each in-app screen once from the start host. DabFlow and
        # similar apps honor ?action=<screen>. Do not re-queue from an action URL.
        cur_query = urlsplit(cur).query.lower()
        if "action=" not in cur_query:
            for screen in page["screens"]:
                if screen in ("home",):
                    continue
                deep = screen_deep_link(start, screen)
                deep_key = urlsplit(deep)._replace(fragment="").geturl().rstrip("/")
                if deep_key not in seen and deep not in to_visit:
                    to_visit.append(deep)

    total_links = sum(int(pg.get("link_count") or len(pg["links"])) for pg in pages)
    total_forms = sum(int(pg.get("form_count") or len(pg["forms"])) for pg in pages)
    truncated = bool(to_visit)
    shell_only = bool(pages) and all(
        pg.get("read_as") == "webapp_shell"
        and not pg.get("routes")
        and not pg.get("screens")
        for pg in pages
    )
    if not pages or shell_only:
        if shell_only:
            first = (
                "That page is a web app shell. Same-host scripts did not declare any routes "
                "or in-app screens. The empty shell was not mapped."
            )
        else:
            first = errors[0]["error"] if errors else "No pages could be read from that URL."
        detail = first if shell_only or len(errors) <= 1 else (
            f"No pages mapped. {len(errors)} fetch error(s): {first}"
        )
        return {
            "ok": False,
            "error": detail,
            "start_url": start,
            "host": host,
            "pages_scanned": 0,
            "total_internal_links": 0,
            "total_forms": 0,
            "pages": [],
            "errors": errors,
            "truncated": False,
            "remaining_urls": 0,
            "duration_ms": int((time.time() - started) * 1000),
        }
    return {
        "ok": True,
        "start_url": start,
        "host": host,
        "pages_scanned": len(pages),
        "total_internal_links": total_links,
        "total_forms": total_forms,
        "pages": pages,
        "errors": errors,
        "truncated": truncated,
        "remaining_urls": len(to_visit),
        "duration_ms": int((time.time() - started) * 1000),
    }


def build_starter_sequence(url: str, pages: list | None = None) -> dict:
    """Draft sequence using only runner-valid step types.

    open_url + checkpoint 'loaded' mirror the shipped money sequences;
    the draft is a starting point the user refines in Steps/Builder.

    In-app screens (switchScreen / data-screen) become ``?action=<screen>``
    opens when the site exposes that deep link — same pattern DabFlow uses.
    """
    if pages is None:
        result = scan_site(url)
        pages = result.get("pages", []) if result.get("ok") else []
    target = normalize_url(url) or url
    steps = [
        {"type": "clear_cookies", "phase": "pre_site_fast"},
        {"type": "wait", "seconds": 0.3, "phase": "pre_site_fast"},
        {
            "type": "open_url",
            "url": target,
            "post_wait_secs": 1.2,
            "phase": "pre_site_fast",
            "checkpoint": "loaded",
        },
        {"type": "wait", "seconds": 0.4},
    ]
    seen_urls = {target.rstrip("/")}
    screen_names: list[str] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        screen_names.extend(list(page.get("screens") or []))
        page_url = normalize_url(str(page.get("url") or "")) or ""
        if not page_url or page_url.rstrip("/") in seen_urls:
            continue
        seen_urls.add(page_url.rstrip("/"))
        steps.append(
            {
                "type": "open_url",
                "url": page_url,
                "post_wait_secs": 1.2,
                "checkpoint": "loaded",
            }
        )
        steps.append({"type": "wait", "seconds": 0.4})
    for screen in normalize_screen_names(screen_names):
        if screen == "home":
            continue
        deep = screen_deep_link(target, screen)
        if deep.rstrip("/") in seen_urls:
            continue
        seen_urls.add(deep.rstrip("/"))
        steps.append(
            {
                "type": "open_url",
                "url": deep,
                "post_wait_secs": 1.2,
                "checkpoint": "loaded",
                "note": f"webapp screen:{screen}",
            }
        )
        steps.append({"type": "wait", "seconds": 0.4})
    extra = len(seen_urls) - 1
    screens = normalize_screen_names(screen_names)
    return {
        "steps": steps,
        "note": (
            f"Starter draft opens the {len(seen_urls)} mapped page(s)"
            + (f" ({extra} beyond the start URL)" if extra else "")
            + (f", including screens: {', '.join(screens)}" if screens else "")
            + ". Add taps and waits in Steps or Builder before running the farm."
        ),
        "pages_mapped": len(pages),
        "screens": screens,
    }


def save_sequence(steps: list, host: str, output_dir: Path | None = None) -> Path:
    """Persist a sequence JSON under ``output_dir/site_scans/<host>/``."""
    base = Path(output_dir) if output_dir else Path("sequences") / "site_scans"
    folder = base / (re.sub(r"[^a-zA-Z0-9._-]", "_", host) or "site")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"starter_{time.strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(steps, indent=2), encoding="utf-8")
    return path