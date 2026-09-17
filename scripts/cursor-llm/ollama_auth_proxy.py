"""Bearer-token-gated reverse proxy in front of a local Ollama server.

start-ollama-cursor-agent.ps1 tunnels this proxy's port through cloudflared,
not Ollama's own port directly -- so the public URL requires
``Authorization: Bearer <token>`` for every request instead of exposing
Ollama's entire unauthenticated API (chat, model management, etc.) to
anyone who obtains the trycloudflare URL.

Usage: python ollama_auth_proxy.py --listen-port 11435 --upstream-port 11434 --token <token>
"""

from __future__ import annotations

import argparse
import hmac
import http.client
import http.server
import sys


class _Handler(http.server.BaseHTTPRequestHandler):
    upstream_port: int = 11434
    token: str = ""

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: A003
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))

    def _authorized(self) -> bool:
        auth = self.headers.get("Authorization", "")
        expected = f"Bearer {self.token}"
        # Constant-time compare -- a plain == leaks timing info about how many
        # leading characters matched, letting an attacker recover the token
        # byte-by-byte over many requests.
        return hmac.compare_digest(auth.encode("utf-8"), expected.encode("utf-8"))

    def _proxy(self) -> None:
        if not self._authorized():
            body = b'{"error":{"message":"Invalid or missing bearer token","type":"authentication_error"}}'
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        length = int(self.headers.get("Content-Length") or 0)
        payload = self.rfile.read(length) if length else None
        conn = http.client.HTTPConnection("127.0.0.1", self.upstream_port, timeout=120)
        forward_headers = {
            k: v for k, v in self.headers.items()
            if k.lower() not in ("authorization", "host", "content-length")
        }
        if payload is not None:
            forward_headers["Content-Length"] = str(len(payload))
        try:
            conn.request(self.command, self.path, body=payload, headers=forward_headers)
            resp = conn.getresponse()
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() in ("transfer-encoding", "connection"):
                    continue
                self.send_header(k, v)
            self.end_headers()
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001
            try:
                body = str(exc).encode("utf-8", "replace")
                self.send_response(502)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception:
                pass
        finally:
            conn.close()

    def do_GET(self) -> None:  # noqa: N802
        self._proxy()

    def do_POST(self) -> None:  # noqa: N802
        self._proxy()

    def do_PUT(self) -> None:  # noqa: N802
        self._proxy()

    def do_DELETE(self) -> None:  # noqa: N802
        self._proxy()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen-port", type=int, required=True)
    ap.add_argument("--upstream-port", type=int, required=True)
    ap.add_argument("--token", required=True)
    args = ap.parse_args()

    _Handler.upstream_port = args.upstream_port
    _Handler.token = args.token
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.listen_port), _Handler)
    print(f"ollama_auth_proxy listening on 127.0.0.1:{args.listen_port} -> upstream 127.0.0.1:{args.upstream_port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
