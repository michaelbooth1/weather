"""Small authenticated LAN server. Rejected requests never reach the reader."""
from __future__ import annotations

from datetime import datetime, timezone
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from urllib.parse import parse_qs, urlsplit

from weather.market.wallet_reader_security import ReaderError, lan_ip

ROUTES = {"/health", "/summary", "/positions", "/open-orders", "/trades", "/balance", "/rewards"}


def dispatch(reader, guard, token, allow, method, target, client_ip, headers):
    """Pure dispatch boundary, exercised without opening sockets in tests."""
    if client_ip != allow:
        return 403, {"error": "forbidden"}
    supplied = headers.get("Authorization", "")
    if not isinstance(supplied, str) or not hmac.compare_digest(
            supplied.encode("utf-8"), ("Bearer " + token).encode("utf-8")):
        return 401, {"error": "unauthorized"}
    if method != "GET":
        return 405, {"error": "method_not_allowed"}
    # Reject browser contexts as well as omitting CORS headers.
    if headers.get("Origin") is not None or headers.get("Sec-Fetch-Mode") is not None:
        return 403, {"error": "browser_forbidden"}
    try:
        parts = urlsplit(target)
        if parts.scheme or parts.netloc or parts.fragment or parts.path not in ROUTES:
            return 404, {"error": "not_found"}
        query = parse_qs(parts.query, keep_blank_values=True, strict_parsing=True)
        allowed = {"since"} if parts.path == "/trades" else {"date"} if parts.path == "/rewards" else set()
        if not set(query) <= allowed or any(len(v) != 1 for v in query.values()):
            return 400, {"error": "invalid_query"}
        if parts.path == "/health":
            value = {"status": "ok", "upstream_checked": False}
        elif parts.path == "/trades":
            since = query.get("since", [str(int(datetime.now(timezone.utc).timestamp()) - 86400)])[0]
            from weather.market.wallet_reader import valid_since
            valid_since(since)
            value = reader.trades(since)
        elif parts.path == "/rewards":
            day = query.get("date", [datetime.now(timezone.utc).date().isoformat()])[0]
            from weather.market.wallet_reader import valid_date
            valid_date(day)
            value = reader.rewards(day)
        else:
            value = getattr(reader, parts.path[1:].replace("-", "_"))()
        return 200, guard.clean(value)
    except Exception:
        return 503, {"error": "read_unavailable"}


def handler_for(reader, guard, token, allow):
    class Handler(BaseHTTPRequestHandler):
        server_version = "WalletReader"
        sys_version = ""

        def log_message(self, *args):
            pass  # No default path/header/exception logging.

        def send_error(self, code, message=None, explain=None):
            self.respond(code, {"error": "request_refused"})

        def respond(self, code, value):
            body = json.dumps(value, allow_nan=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):
            if (len(self.path) > 2048 or len(self.headers.get_all("Authorization", [])) != 1
                    or self.headers.get("Transfer-Encoding") is not None
                    or self.headers.get("Content-Length", "0") != "0"):
                self.respond(400, {"error": "request_refused"})
                return
            code, payload = dispatch(reader, guard, token, allow, self.command, self.path,
                                     self.client_address[0], self.headers)
            self.respond(code, payload)

        do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = do_TRACE = do_CONNECT = do_GET

        def __getattr__(self, name):
            if name.startswith("do_"):
                return self.do_GET  # Unknown verbs use the same auth + 405 gate.
            raise AttributeError(name)

    return Handler


def serve_reader(reader, guard, token, *, bind, allow, port):
    lan_ip(bind)
    lan_ip(allow)

    class Server(HTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(5)
            return connection, address

        def verify_request(self, request, client_address):
            return client_address[0] == allow

        def handle_error(self, request, client_address):
            pass  # Never let default tracebacks emit account data or auth.

    with Server((bind, port), handler_for(reader, guard, token, allow)) as server:
        server.serve_forever(poll_interval=0.5)
