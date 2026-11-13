"""Credential-free HTTP and socket transport with a fixed public allowlist.

Uses http.client directly: no environment proxy, netrc, cookies, SDK, requests
authentication, credential loader or redirect following is involved.
"""
from __future__ import annotations

import http.client
import json
import re
import threading
import time
from urllib.parse import urlencode, urlsplit

from weather.market.pilot_evidence_contract import retry_delay
from weather.market.pilot_evidence_store import CaptureStopped, MIB, stamp
from weather.market.pilot_evidence_transport import header_cooldown, http_exchange, socket_exchange, TransportLimit

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
        self.halted = threading.Event()

    def halt(self):
        self.halted.set()  # Terminal for this run; no cooldown can re-arm it.

    def wait(self):
        return self.start(lambda: None)

    def start(self, send):
        """Serialize actual connect/send boundaries, including slow preparation.

        The lock stays held through connect and send, never through the response
        body. A slow journal/DNS/TLS setup cannot race another reservation.
        """
        with self.lock:
            while True:
                if self.halted.is_set():
                    raise CaptureStopped("venue_congestion")
                self.check()
                delay = self.next_at - self.clock()
                if delay <= 0:
                    now = self.clock()
                    try:
                        send()
                        return now
                    finally:
                        self.next_at = self.clock() + self.interval
                self.sleep(min(delay, 0.2))

    def defer(self, seconds):
        with self.lock:
            self.next_at = max(self.next_at, self.clock() + max(self.interval, seconds))


class RetryPending(ValueError):
    """Return control to the scheduler while the shared cooldown is active."""


class PublicHTTP:
    def __init__(self, store, gate, *, request=None):
        self.store, self.gate, self.request = store, gate, request
        self.failures = 0
        self.last_body_bytes = 0
        self.pool = {}

    def read(self, url, *, params=None, body=None):
        for _ in range(5):
            try:
                return self.once(url, params=params, body=body)
            except RetryPending:
                pass
        raise ValueError("public retry bound reached")

    def once(self, url, *, params=None, body=None):
        method = "POST" if body is not None else "GET"
        parts = allow_url(method, url, params)
        sent = stamp()
        self.store.write("http_request", {"method": method, "url": url,
                                          "params": params or {}, "body": body}, received=sent)
        try:
            if self.request is None:
                status, headers, raw = http_exchange(method, parts, params or {}, body,
                                                      gate=self.gate, store=self.store, pool=self.pool)
            else:
                result = []
                def send():
                    self.store.network_started("rest", monotonic=self.gate.clock())
                    result.append(self.request(method, parts, params or {}, body))
                self.gate.start(send)
                status, headers, raw = result[0]
        except TransportLimit as exc:
            self.store.fail("transport_size_cap", error=str(exc))
            raise CaptureStopped("transport_size_cap") from None
        except (OSError, http.client.HTTPException) as exc:
            self.store.gap("http_transport", url=url, error=type(exc).__name__, request_start=sent)
            status, headers, raw = 599, {}, b""
        received = stamp()
        self.last_body_bytes = len(raw)
        if len(raw) > 4 * MIB:
            self.store.fail("http_body_cap", url=url, bytes=len(raw))
            raise CaptureStopped("http_body_cap")
        parsed = self.store.raw("http_response", raw, received=received, url=url, method=method,
                                params=params or {}, request_body=body, request_start=sent,
                                transport_start=self.store.last_network_stamp.get("rest"),
                                status=status, response_headers=headers)
        if self.request is not None:  # Real transport already inspected headers before reading the body.
            header_cooldown(status, headers, self.gate, self.store, "rest", endpoint=url, body_unread=False)
        if status == 429 or 500 <= status <= 599:
            self.failures += 1
            delay = retry_delay(headers.get("Retry-After"), self.failures)
            self.gate.defer(delay)
            self.store.gap("http_backoff", url=url, status=status, seconds=delay)
            raise RetryPending("shared cooldown")
        if status != 200:
            self.store.gap("http_status", url=url, status=status)
            raise ValueError(f"public HTTP status {status}")
        self.failures = 0
        if parsed is None:
            raise ValueError("public response is not validated JSON")
        return parsed


def open_socket(*, gate, store, max_size=MIB):
    return socket_exchange(allow_url("WS", SOCKET), gate=gate, store=store, max_size=max_size)
