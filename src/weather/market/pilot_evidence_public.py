"""Credential-free HTTP and socket transport with a fixed public allowlist.

Uses http.client directly: no environment proxy, netrc, cookies, SDK, requests
authentication, credential loader or redirect following is involved.
"""
from __future__ import annotations

import http.client
import json
import re
import ssl
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urlsplit

from weather.market.pilot_evidence_store import CaptureStopped, MIB, stamp

CLOB = "https://clob.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"
SOCKET = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
CONDITION = r"0x[0-9a-fA-F]{64}"
PUBLIC_GETS = {
    "clob.polymarket.com": {"/time": set(), "/fee-rate": {"token_id"}},
    "data-api.polymarket.com": {
        "/v2/trades": {"user", "limit", "cursor", "start", "end", "taker_only", "filter_amount"},
        "/v2/activity": {"user", "limit", "cursor", "start", "end", "type",
                         "sort_by", "sort_direction", "exclude_deposits_withdrawals"},
        "/v2/positions": {"user", "limit", "cursor", "status", "filter_amount", "include_archived"},
    },
}


def allow_url(method, url, params=None):
    if any(ord(c) <= 32 or c in "\\%" for c in url):
        raise ValueError("non-allowlisted URL")
    parts = urlsplit(url)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("non-allowlisted URL")
    if method == "WS" and url == SOCKET:
        return parts
    if parts.scheme != "https" or parts.netloc != parts.hostname:
        raise ValueError("non-allowlisted URL")
    keys = None
    if method == "POST" and url == CLOB + "/books":
        keys = set()
    elif method == "GET":
        keys = PUBLIC_GETS.get(parts.hostname, {}).get(parts.path)
        if parts.hostname == "clob.polymarket.com":
            if re.fullmatch(r"/rewards/markets/" + CONDITION, parts.path):
                keys = {"next_cursor"}
            elif re.fullmatch(r"/clob-markets/" + CONDITION, parts.path):
                keys = set()
        elif parts.hostname == "gamma-api.polymarket.com" and re.fullmatch(
                r"/events/slug/highest-temperature-in-[a-z-]+-on-[a-z]+-\d{1,2}-\d{4}", parts.path):
            keys = set()
    if keys is None or not set(params or {}).issubset(keys):
        raise ValueError("non-allowlisted URL or parameters")
    return parts


class RateGate:
    """No bursts: every public HTTP start is separated by at least 1/rps."""

    def __init__(self, rps=2, *, clock=time.monotonic, sleep=time.sleep, check=lambda: None):
        if not 0 < rps <= 2:
            raise ValueError("max-rest-rps must be >0 and <=2")
        self.interval, self.clock, self.sleep, self.check = 1 / rps, clock, sleep, check
        self.next_at = 0.0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            while True:
                self.check()
                delay = self.next_at - self.clock()
                if delay <= 0:
                    now = self.clock()
                    self.next_at = now + self.interval
                    return now
                self.sleep(min(delay, 0.2))

    def defer(self, seconds):
        with self.lock:
            self.next_at = max(self.next_at, self.clock() + max(self.interval, seconds))


def retry_delay(value, failures, now=None):
    seconds = 0.0
    if value:
        try:
            seconds = float(value)
        except ValueError:
            try:
                seconds = (parsedate_to_datetime(value) -
                           (now or datetime.now(timezone.utc))).total_seconds()
            except (ValueError, TypeError, OverflowError):
                pass
    return max(min(300, 2 ** min(failures, 9)), seconds)


def direct_request(method, parts, params, body):
    connection = http.client.HTTPSConnection(parts.hostname, timeout=5,
                                             context=ssl.create_default_context())
    try:
        path = parts.path + (("?" + urlencode(params)) if params else "")
        encoded = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
        headers = {"Accept": "application/json", "User-Agent": "weather-public-evidence/1"}
        if encoded is not None:
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=encoded, headers=headers)
        response = connection.getresponse()
        received_headers = {k: response.getheader(k) for k in ("Date", "Retry-After", "Content-Type")}
        raw = response.read(4 * MIB + 1)
        return response.status, received_headers, raw
    finally:
        connection.close()


class PublicHTTP:
    def __init__(self, store, gate, *, request=direct_request):
        self.store, self.gate, self.request = store, gate, request
        self.failures = 0

    def read(self, url, *, params=None, body=None):
        method = "POST" if body is not None else "GET"
        parts = allow_url(method, url, params)
        for attempt in range(5):
            self.gate.wait()
            sent = stamp()
            self.store.write("http_request", {"method": method, "url": url,
                                              "params": params or {}, "body": body}, received=sent)
            # A slow disk must not consume the spacing before the HTTP call.
            self.gate.defer(self.gate.interval)
            self.store.request_started(self.gate.clock())
            sent = stamp()
            try:
                status, headers, raw = self.request(method, parts, params or {}, body)
            except (OSError, http.client.HTTPException) as exc:
                self.store.gap("http_transport", url=url, error=type(exc).__name__, request_start=sent)
                status, headers, raw = 599, {}, b""
            received = stamp()
            if len(raw) > 4 * MIB:
                self.store.fail("http_body_cap", url=url, bytes=len(raw))
                raise CaptureStopped("http_body_cap")
            parsed = self.store.raw("http_response", raw, received=received, url=url, method=method,
                                    params=params or {}, request_body=body, request_start=sent,
                                    status=status, response_headers=headers)
            if status == 429 or 500 <= status <= 599:
                self.failures += 1
                delay = retry_delay(headers.get("Retry-After"), self.failures)
                self.gate.defer(delay)
                self.store.gap("http_backoff", url=url, status=status, seconds=delay, attempt=attempt)
                continue
            if status != 200:
                self.store.gap("http_status", url=url, status=status)
                raise ValueError(f"public HTTP status {status}")
            self.failures = 0
            if parsed is None:
                self.store.gap("http_shape", url=url)
                raise ValueError("public response is not JSON")
            return parsed
        raise ValueError("public retry bound reached")


def open_socket():
    # Import installed public websocket support only, never a venue SDK.
    import websocket

    allow_url("WS", SOCKET)
    return websocket.create_connection(SOCKET, timeout=1, http_no_proxy=["*"],
                                       redirect_limit=0, enable_multithread=True)
