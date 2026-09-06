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
MAX_PAGES_DEFAULT = 20
MAX_BYTES = 400_000
SKIP_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
    ".css", ".js", ".json", ".xml", ".pdf", ".zip", ".gz",
    ".mp4", ".webm", ".mp3", ".woff", ".woff2", ".ttf", ".eot",
)
SKIP_PREFIXES = ("javascript:", "mailto:", "tel:", "data:", "#")


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
        # None when not inside <button>; [] only while collecting button text.
        self._btn_buf: list[str] | None = None
        self._h_tag: str | None = None
        self._h_buf: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        a = dict(attrs)
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


def scan_site(
    url: str,
    max_pages: int | None = None,
    timeout: int = FETCH_TIMEOUT,
) -> dict:
    """Crawl same-host pages from ``url`` and return the site map."""
    if max_pages is None:
        try:
            max_pages = int(os.environ.get("CPHARM_SITE_MAP_MAX_PAGES") or MAX_PAGES_DEFAULT)
        except (TypeError, ValueError):
            max_pages = MAX_PAGES_DEFAULT
    max_pages = max(1, min(500, max_pages))
    start = normalize_url(url)
    if not start:
        return {"ok": False, "error": "Enter a valid URL like https://example.com"}
    host = urlsplit(start).netloc.lower()
    started = time.time()

    to_visit = [start]
    seen: set[str] = set()
    pages: list[dict] = []
    errors: list[dict] = []

    while to_visit and len(pages) < max_pages:
        cur = to_visit.pop(0)
        key = urlsplit(cur)._replace(fragment="").geturl().rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        try:
            html = fetch_html(cur, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 — report any fetch failure
            errors.append({"url": cur, "error": str(exc)[:120]})
            continue
        if html is None:
            continue

        p = _SiteParser(cur)
        try:
            p.feed(html)
        except Exception:  # noqa: BLE001 — partial parse is fine
            pass

        pages.append(
            {
                "url": cur,
                "title": " ".join("".join(p.title_parts).split())[:160],
                "headings": [
                    {"level": lvl, "text": txt}
                    for lvl, txt in _dedupe(p.headings)
                ][:12],
                "links": _dedupe(p.links)[:40],
                "external_links": _dedupe(p.external_links)[:12],
                "forms": [
                    {
                        "action": f["action"][:200] or "(same page)",
                        "method": f["method"],
                        "inputs": _dedupe(f["inputs"])[:10],
                    }
                    for f in p.forms
                ][:8],
                "buttons": _dedupe(p.buttons)[:20],
                "inputs": _dedupe(p.inputs)[:20],
            }
        )

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

    total_links = sum(len(pg["links"]) for pg in pages)
    total_forms = sum(len(pg["forms"]) for pg in pages)
    return {
        "ok": True,
        "start_url": start,
        "host": host,
        "pages_scanned": len(pages),
        "total_internal_links": total_links,
        "total_forms": total_forms,
        "pages": pages,
        "errors": errors[:5],
        "duration_ms": int((time.time() - started) * 1000),
    }


def build_starter_sequence(url: str, pages: list | None = None) -> dict:
    """Draft sequence using only runner-valid step types.

    open_url + checkpoint 'loaded' mirror the shipped money sequences;
    the draft is a starting point the user refines in Steps/Builder.
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
    return {
        "steps": steps,
        "note": (
            "Starter draft from the site map — add taps/waits in Steps or "
            "Builder before running the farm."
        ),
        "pages_mapped": len(pages),
    }


def save_sequence(steps: list, host: str, output_dir: Path | None = None) -> Path:
    """Persist a sequence JSON under ``output_dir/site_scans/<host>/``."""
    base = Path(output_dir) if output_dir else Path("sequences") / "site_scans"
    folder = base / (re.sub(r"[^a-zA-Z0-9._-]", "_", host) or "site")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"starter_{time.strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(steps, indent=2), encoding="utf-8")
    return path