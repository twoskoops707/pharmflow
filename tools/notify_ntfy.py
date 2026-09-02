#!/usr/bin/env python3
"""Post a message to ntfy.sh (or self-hosted ntfy).

Environment:
  NTFY_TOPIC or CPHARM_NTFY_TOPIC — required topic name
  NTFY_SERVER — optional base URL (default https://ntfy.sh)
  NTFY_TOKEN — optional Bearer token for private topics

Example:
  NTFY_TOPIC=mytopic python tools/notify_ntfy.py "CPharm build done"
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request


def notify(
    message: str,
    *,
    title: str = "CPharm",
    tags: str = "white_check_mark",
    topic: str | None = None,
    server: str | None = None,
    token: str | None = None,
) -> bool:
    topic = (topic or os.environ.get("NTFY_TOPIC") or os.environ.get("CPHARM_NTFY_TOPIC") or "").strip()
    if not topic:
        print("NTFY_TOPIC (or CPHARM_NTFY_TOPIC) not set — skip.", file=sys.stderr)
        return True  # skip is not a failure
    base = (server or os.environ.get("NTFY_SERVER") or "https://ntfy.sh").rstrip("/")
    url = f"{base}/{topic}"
    token = token or os.environ.get("NTFY_TOKEN", "").strip()
    headers = {"Title": title, "Tags": tags}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url,
        data=message.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as exc:
        print(f"ntfy HTTP {exc.code}: {exc.reason}", file=sys.stderr)
        return False
    except OSError as exc:
        print(f"ntfy failed: {exc}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Send ntfy push notification")
    parser.add_argument("message", help="Message body")
    parser.add_argument("--title", default="CPharm", help="Notification title")
    parser.add_argument("--tags", default="white_check_mark", help="ntfy tags")
    args = parser.parse_args()
    return 0 if notify(args.message, title=args.title, tags=args.tags) else 1


if __name__ == "__main__":
    raise SystemExit(main())
