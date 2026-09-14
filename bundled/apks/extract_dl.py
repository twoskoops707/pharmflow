from pathlib import Path
import re
import json
import urllib.request

html = Path(r"C:\PharmFlow\bundled\apks\dl.html").read_text(encoding="utf-8", errors="replace")
for pat in [
    r'data-url="([^"]+)"',
    r"https://dw\.uptodown\.com/[^\s\"'<>]+",
    r"https://[^\s\"'<>]+\.apk[^\s\"'<>]*",
    r'data-version-id="(\d+)"',
]:
    ms = re.findall(pat, html)
    print(pat, "->", len(ms))
    for m in ms[:15]:
        print(" ", m[:220])

# Look for JSON blobs that might contain download info
blobs = re.findall(r"<script[^>]*>(\{.*?\})</script>", html, flags=re.S)
print("script json-ish blobs", len(blobs))
