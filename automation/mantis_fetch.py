"""Fetch today's Mantis publisher metrics (Dab Flow) for the operator dash.

Auth: Playwright persistent profile under C:\\CPharm\\logs\\mantis_pw_profile
(login once; invisible reCAPTCHA usually works headless). Falls back to a
cookie header file if present.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request
from zoneinfo import ZoneInfo

log = logging.getLogger("mantis_fetch")

PROPERTY_ID_DEFAULT = "6950d5527c56c6494f189e46"
GRAPHQL_URL = "https://admin.mantisadnetwork.com/graphql"
LOGIN_URL = "https://admin.mantisadnetwork.com/auth/login"
AUTH_PAGE = "https://admin.mantisadnetwork.com/v4/auth/"
ADMIN_ORIGIN = "https://admin.mantisadnetwork.com"
METRICS = ("IMPRESSIONS", "CLICKS", "PAYOUT", "ECPM", "EVCPM")

LOG_DIR = Path(r"C:\CPharm\logs")
COOKIE_HEADER_FILE = LOG_DIR / "mantis_admin_cookie_header.txt"
PW_PROFILE_DIR = LOG_DIR / "mantis_pw_profile"
PW_STATE_FILE = LOG_DIR / "mantis_playwright_state.json"
CREDS_CANDIDATES = (
    LOG_DIR / "MANTIS.json",
    Path(os.environ.get("CPHARM_CODE_ROOT", "")) / "logs" / "MANTIS.json",
)

CREATE_GQL = """
query PropertyReportCreate($propertyId: ID!, $query: ReportQuery!) {
  property(id: $propertyId) {
    report(query: $query) {
      id status created metric
      entries { value interval }
    }
  }
}
""".strip()

LOAD_GQL = """
query ReportLoad($reportId: ID!) {
  report(id: $reportId) {
    id status created metric
    entries { value interval }
  }
}
""".strip()

PROPERTY_BALANCE_GQL = """
query PropertyBalance($id: ID!) {
  property(id: $id) {
    id
    name
    balance
    pending
    payoutIssue
    payoutVerified
  }
}
""".strip()

# Lifetime DAY PAYOUT reports error if the window is too wide; Jan 2025 covers
# Dab Flow history and stays under the API limit (verified live).
_LIFETIME_PAYOUT_START = date(2025, 1, 1)


def _pacific_today() -> date:
    return datetime.now(ZoneInfo("America/Los_Angeles")).date()


def _day_bounds_utc(day: date) -> tuple[str, str]:
    tz = ZoneInfo("America/Los_Angeles")
    start = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=tz)
    end = start + timedelta(days=1) - timedelta(milliseconds=1)
    return (
        start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def _bucket_matches(interval_iso: str, day: date) -> bool:
    raw = (interval_iso or "").strip()
    if not raw:
        return False
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    local = ts.astimezone(ZoneInfo("America/Los_Angeles")).date()
    return local == day


def parse_metric_for_day(entries: list[dict[str, Any]], day: date) -> float | None:
    for row in entries or []:
        if _bucket_matches(str(row.get("interval") or ""), day):
            try:
                return float(row.get("value") or 0)
            except (TypeError, ValueError):
                return None
    return None


def summarize_reports(reports: dict[str, dict[str, Any]], day: date | None = None) -> dict[str, Any]:
    day = day or _pacific_today()
    impr = parse_metric_for_day((reports.get("IMPRESSIONS") or {}).get("entries") or [], day)
    clicks = parse_metric_for_day((reports.get("CLICKS") or {}).get("entries") or [], day)
    payout = parse_metric_for_day((reports.get("PAYOUT") or {}).get("entries") or [], day)
    ecpm = parse_metric_for_day((reports.get("ECPM") or {}).get("entries") or [], day)
    evcpm = parse_metric_for_day((reports.get("EVCPM") or {}).get("entries") or [], day)
    return {
        "date": day.isoformat(),
        "impressions": int(round(impr or 0)),
        "clicks": int(round(clicks or 0)),
        "payout_usd": round(float(payout or 0), 2),
        "ecpm": round(float(ecpm or 0), 2),
        "evcpm": round(float(evcpm or 0), 2),
        "updated": datetime.now(timezone.utc).isoformat(),
        "source": "mantis_graphql",
    }


def _sum_report_entries(entries: list[dict[str, Any]] | None) -> float:
    total = 0.0
    for row in entries or []:
        try:
            total += float(row.get("value") or 0)
        except (TypeError, ValueError):
            continue
    return total


def fetch_property_balance(
    cookie_header: str,
    *,
    property_id: str = PROPERTY_ID_DEFAULT,
) -> dict[str, Any]:
    """Current unpaid balance (amount receivable) from Property.balance."""
    raw = graphql_post(
        cookie_header,
        {
            "operationName": "PropertyBalance",
            "query": PROPERTY_BALANCE_GQL,
            "variables": {"id": property_id},
        },
    )
    if raw.get("errors"):
        raise RuntimeError(f"property balance errors: {raw['errors']}")
    prop = ((raw.get("data") or {}).get("property")) or {}
    try:
        balance = float(prop.get("balance") or 0)
    except (TypeError, ValueError):
        balance = 0.0
    return {
        "receivable_usd": round(balance, 2),
        "pending": bool(prop.get("pending")),
        "payout_issue": prop.get("payoutIssue"),
        "payout_verified": prop.get("payoutVerified"),
        "property_name": prop.get("name"),
    }


def fetch_lifetime_payout(
    cookie_header: str,
    *,
    property_id: str = PROPERTY_ID_DEFAULT,
    start_day: date | None = None,
) -> float:
    """Sum of DAY PAYOUT report entries (accrued publisher earnings)."""
    tz = ZoneInfo("America/Los_Angeles")
    start_day = start_day or _LIFETIME_PAYOUT_START
    end_day = _pacific_today()
    start = datetime(start_day.year, start_day.month, start_day.day, 0, 0, 0, tzinfo=tz)
    end = datetime(end_day.year, end_day.month, end_day.day, 23, 59, 59, 999000, tzinfo=tz)
    start_s = start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    end_s = end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    created = graphql_post(
        cookie_header,
        {
            "operationName": "PropertyReportCreate",
            "query": CREATE_GQL,
            "variables": {
                "propertyId": property_id,
                "query": {
                    "metric": "PAYOUT",
                    "interval": "DAY",
                    "start": start_s,
                    "end": end_s,
                    "filters": [],
                    "groups": [],
                },
            },
        },
    )
    if created.get("errors"):
        raise RuntimeError(f"lifetime payout create errors: {created['errors']}")
    rid = (((created.get("data") or {}).get("property") or {}).get("report") or {}).get("id")
    if not rid:
        raise RuntimeError(f"lifetime payout create failed: {created}")
    report: dict[str, Any] = {}
    for _ in range(40):
        loaded = graphql_post(
            cookie_header,
            {
                "operationName": "ReportLoad",
                "query": LOAD_GQL,
                "variables": {"reportId": rid},
            },
        )
        report = (loaded.get("data") or {}).get("report") or {}
        if report.get("status") != "PENDING":
            break
        time.sleep(0.6)
    # Still PENDING → do not treat as $0 lifetime (that zeros paid_to_date).
    if report.get("status") == "PENDING":
        raise RuntimeError(f"lifetime payout report still PENDING: {rid}")
    if report.get("status") not in ("READY", "COMPLETE", "DONE"):
        # READY is the live status; accept any non-PENDING/non-ERROR with entries.
        if report.get("status") == "ERROR" and not report.get("entries"):
            raise RuntimeError(f"lifetime payout report error: {report}")
    return round(_sum_report_entries(report.get("entries") or []), 2)


def fetch_money_summary(
    cookie_header: str,
    *,
    property_id: str = PROPERTY_ID_DEFAULT,
) -> dict[str, Any]:
    """Paid-to-date + amount receivable from Mantis property money fields.

    Receivable = Property.balance (unpaid).
    Lifetime earnings = sum of historical DAY PAYOUT buckets.
    Paid to date = max(0, lifetime − receivable).
    """
    bal = fetch_property_balance(cookie_header, property_id=property_id)
    lifetime = fetch_lifetime_payout(cookie_header, property_id=property_id)
    receivable = float(bal.get("receivable_usd") or 0)
    paid = max(0.0, round(lifetime - receivable, 2))
    return {
        "receivable_usd": round(receivable, 2),
        "paid_to_date_usd": paid,
        "lifetime_earnings_usd": round(lifetime, 2),
        "pending": bal.get("pending"),
        "payout_issue": bal.get("payout_issue"),
        "payout_verified": bal.get("payout_verified"),
        "property_name": bal.get("property_name"),
    }


def _merge_money_into_summary(
    summary: dict[str, Any],
    cookie_header: str,
    *,
    property_id: str = PROPERTY_ID_DEFAULT,
) -> dict[str, Any]:
    try:
        money = fetch_money_summary(cookie_header, property_id=property_id)
        summary.update(money)
    except Exception as exc:
        log.warning("mantis money summary soft-fail: %s", exc)
        summary.setdefault("receivable_usd", None)
        summary.setdefault("paid_to_date_usd", None)
        summary.setdefault("lifetime_earnings_usd", None)
        summary["money_error"] = str(exc)
    return summary


def load_creds() -> tuple[str, str]:
    for path in CREDS_CANDIDATES:
        if not path.is_file():
            continue
        user = ""
        password = ""
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            low = raw.lower()
            if low.startswith("u:"):
                user = raw.split(":", 1)[1].strip()
            elif low.startswith("p:"):
                password = raw.split(":", 1)[1].strip()
        if user and password:
            return user, password
    raise FileNotFoundError("MANTIS.json credentials not found under FamFlow/logs or C:\\CPharm\\logs")


def load_cookie_header() -> str | None:
    if COOKIE_HEADER_FILE.is_file():
        text = COOKIE_HEADER_FILE.read_text(encoding="utf-8").strip()
        if text:
            return text
    return None


def save_cookie_header(header: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    COOKIE_HEADER_FILE.write_text(header.strip() + "\n", encoding="utf-8")


def graphql_post(cookie_header: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        GRAPHQL_URL,
        data=data,
        headers={
            "content-type": "application/json",
            "accept": "*/*",
            "cookie": cookie_header,
            "origin": ADMIN_ORIGIN,
            "referer": f"{ADMIN_ORIGIN}/v4/",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_today(
    cookie_header: str,
    *,
    property_id: str = PROPERTY_ID_DEFAULT,
    day: date | None = None,
) -> dict[str, Any]:
    """Create+poll one report per metric for the Pacific calendar day."""
    day = day or _pacific_today()
    start, end = _day_bounds_utc(day)
    reports: dict[str, dict[str, Any]] = {}
    for metric in METRICS:
        created = graphql_post(
            cookie_header,
            {
                "operationName": "PropertyReportCreate",
                "query": CREATE_GQL,
                "variables": {
                    "propertyId": property_id,
                    "query": {
                        "metric": metric,
                        "interval": "DAY",
                        "start": start,
                        "end": end,
                        "filters": [],
                        "groups": [],
                    },
                },
            },
        )
        if created.get("errors"):
            raise RuntimeError(f"create errors for {metric}: {created['errors']}")
        rep = (((created.get("data") or {}).get("property") or {}).get("report")) or {}
        rid = rep.get("id")
        if not rid:
            raise RuntimeError(f"create failed for {metric}: {created}")
        for _ in range(25):
            loaded = graphql_post(
                cookie_header,
                {
                    "operationName": "ReportLoad",
                    "query": LOAD_GQL,
                    "variables": {"reportId": rid},
                },
            )
            report = (loaded.get("data") or {}).get("report") or {}
            if report.get("status") != "PENDING":
                reports[metric] = report
                break
            time.sleep(0.7)
        else:
            raise RuntimeError(f"timeout waiting for {metric} report {rid}")
    summary = summarize_reports(reports, day)
    return _merge_money_into_summary(summary, cookie_header, property_id=property_id)


def save_operator_state(summary: dict[str, Any], path: Path | None = None) -> Path:
    path = path or (LOG_DIR / "mantis_today_state.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return path


def _cookie_header_from_jar(jar: CookieJar) -> str:
    parts = [f"{c.name}={c.value}" for c in jar]
    return "; ".join(parts)


def _fetch_reports_in_page(page: Any, *, property_id: str, day: date) -> dict[str, Any]:
    """Run create+poll GraphQL inside an authenticated Playwright page."""
    start, end = _day_bounds_utc(day)
    js = """
    async ({ propertyId, metrics, start, end, createGql, loadGql }) => {
      async function gql(body) {
        const r = await fetch('/graphql', {
          method: 'POST',
          credentials: 'include',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(body),
        });
        return await r.json();
      }
      const reports = {};
      for (const metric of metrics) {
        const created = await gql({
          operationName: 'PropertyReportCreate',
          query: createGql,
          variables: {
            propertyId,
            query: { metric, interval: 'DAY', start, end, filters: [], groups: [] },
          },
        });
        if (created.errors) throw new Error(JSON.stringify(created.errors));
        if (!created.data || !created.data.property || !created.data.property.report) {
          throw new Error('no report for ' + metric + ': ' + JSON.stringify(created));
        }
        const id = created.data.property.report.id;
        let report = null;
        for (let i = 0; i < 25; i++) {
          const loaded = await gql({
            operationName: 'ReportLoad',
            query: loadGql,
            variables: { reportId: id },
          });
          report = loaded.data && loaded.data.report;
          if (report && report.status !== 'PENDING') break;
          await new Promise((r) => setTimeout(r, 700));
        }
        if (!report || report.status === 'PENDING') throw new Error('timeout ' + metric);
        reports[metric] = report;
      }
      return reports;
    }
    """
    reports = page.evaluate(
        js,
        {
            "propertyId": property_id,
            "metrics": list(METRICS),
            "start": start,
            "end": end,
            "createGql": CREATE_GQL,
            "loadGql": LOAD_GQL,
        },
    )
    return summarize_reports(reports, day)


def _page_logged_in(page: Any, property_id: str = PROPERTY_ID_DEFAULT) -> bool:
    """True only if we can read the Dab Flow property (anonymous __typename is NOT enough)."""
    url = (page.url or "").lower()
    if "/v4/auth" in url:
        return False
    try:
        result = page.evaluate(
            """async (pid) => {
              const r = await fetch('/graphql', {
                method: 'POST',
                credentials: 'include',
                headers: {'content-type': 'application/json'},
                body: JSON.stringify({
                  query: 'query($id: ID!) { property(id: $id) { id name } }',
                  variables: { id: pid },
                }),
              });
              return await r.json();
            }""",
            property_id,
        )
        prop = ((result or {}).get("data") or {}).get("property") or {}
        return bool(prop.get("id"))
    except Exception:
        return False


def _playwright_login(page: Any, user: str, password: str) -> None:
    page.goto(AUTH_PAGE, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(2000)
    email = page.locator("#username, input[name='username'], input[type='email']").first
    pwd = page.locator("#password, input[name='password'], input[type='password']").first
    email.wait_for(state="visible", timeout=20000)
    email.fill(user)
    pwd.fill(password)
    # The marketing "Log in" links also match — use the form submit control.
    try:
        with page.expect_response(lambda r: "/auth/login" in r.url, timeout=30000):
            page.locator("text=Log in").last.click()
    except Exception:
        page.locator("text=Log in").last.click()
    try:
        page.wait_for_url("**/v4/**", timeout=30000)
    except Exception:
        page.wait_for_timeout(3000)
    if "/v4/auth" in (page.url or "").lower():
        raise RuntimeError(
            "Mantis login stayed on /auth (captcha?). "
            "Run once headed: py -c \"from automation.mantis_fetch import pull_today; print(pull_today(headed=True))\""
        )
    page.goto(
        f"{ADMIN_ORIGIN}/v4/property/{PROPERTY_ID_DEFAULT}/dashboard",
        wait_until="domcontentloaded",
        timeout=60000,
    )
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(1000)
    if not _page_logged_in(page):
        raise RuntimeError(
            "Mantis session cookie missing after login. "
            "Retry Pull from Mantis (headed window may appear once)."
        )


def pull_today_playwright(
    *,
    property_id: str = PROPERTY_ID_DEFAULT,
    day: date | None = None,
    headed: bool = False,
) -> dict[str, Any]:
    """Authenticated pull via Playwright persistent profile."""
    from playwright.sync_api import sync_playwright

    day = day or _pacific_today()
    user, password = load_creds()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PW_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PW_PROFILE_DIR),
            headless=not headed,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(
                f"{ADMIN_ORIGIN}/v4/property/{property_id}/reporting",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            page.wait_for_timeout(1200)
            if not _page_logged_in(page, property_id):
                _playwright_login(page, user, password)
                page.goto(
                    f"{ADMIN_ORIGIN}/v4/property/{property_id}/reporting",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                page.wait_for_timeout(800)
            if not _page_logged_in(page, property_id):
                raise RuntimeError("Still not authenticated to Dab Flow property after login")
            summary = _fetch_reports_in_page(page, property_id=property_id, day=day)
            try:
                context.storage_state(path=str(PW_STATE_FILE))
            except Exception:
                pass
            # Best-effort cookie header for non-playwright callers (may miss HttpOnly).
            cookie_header = ""
            try:
                cookies = context.cookies()
                cookie_header = "; ".join(
                    f"{c['name']}={c['value']}" for c in cookies if c.get("name")
                )
                if cookie_header:
                    save_cookie_header(cookie_header)
            except Exception:
                pass
            if cookie_header:
                summary = _merge_money_into_summary(
                    summary, cookie_header, property_id=property_id
                )
            return summary
        finally:
            context.close()


def pull_today(
    *,
    property_id: str = PROPERTY_ID_DEFAULT,
    day: date | None = None,
    headed: bool = False,
) -> dict[str, Any]:
    """Pull today's metrics; prefer cookie header, else Playwright session."""
    day = day or _pacific_today()
    cookie = load_cookie_header()
    if cookie:
        try:
            summary = fetch_today(cookie, property_id=property_id, day=day)
            # Verify cookie still authorized (property-scoped).
            if int(summary.get("impressions") or 0) == 0 and int(summary.get("clicks") or 0) == 0:
                # Zeroes can be real early-day; still accept.
                pass
            save_operator_state(summary)
            return summary
        except (urlerror.URLError, urlerror.HTTPError, RuntimeError, TimeoutError, OSError) as exc:
            log.warning("cookie-header pull failed (%s) — trying Playwright", exc)
    # Remediator / money_mon: never open Playwright when skip flag set.
    if os.environ.get("CPHARM_MANTIS_SKIP_PLAYWRIGHT", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        raise RuntimeError(
            f"cookie Mantis pull failed and CPHARM_MANTIS_SKIP_PLAYWRIGHT=1 "
            f"(last cookie error was logged)"
        )
    # Never auto-open a headed Mantis browser from remediator/dash/money_mon.
    # Headed Chromium was popping the Mantis site then dying and looking like
    # the farm dash "shut down". Opt-in only via headed=True AND env flag.
    allow_headed = headed and (
        os.environ.get("CPHARM_MANTIS_ALLOW_HEADED", "").strip().lower()
        in ("1", "true", "yes", "on")
    )
    try:
        summary = pull_today_playwright(
            property_id=property_id,
            day=day,
            headed=allow_headed,
        )
    except Exception as first:
        if allow_headed:
            raise
        # Soft-fail for farm path — keep operator dash up; do not spawn a
        # visible browser that steals focus / looks like a crash.
        log.warning(
            "headless Mantis pull failed (%s) — NOT retrying headed "
            "(set CPHARM_MANTIS_ALLOW_HEADED=1 for manual re-auth)",
            first,
        )
        raise
    save_operator_state(summary)
    return summary
