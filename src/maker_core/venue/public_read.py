"""Credential-free International reads. No generic URL, header or method API.

The only wire writes are the public market subscription and protocol ping.
Redirects, environment proxies, cookies and account endpoints are excluded.
"""
from datetime import datetime, timezone
import json
import re
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler, Request

from maker_core.evidence.journal import canonical_bytes

MAX_RESPONSE = 2 * 1024**2
STREAM_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


def endpoint(kind, identity):
    if not isinstance(identity, str):
        raise ValueError("public_identity_required")
    if kind == "book" and re.fullmatch(r"[0-9]{1,100}", identity):
        return "https://clob.polymarket.com/book?token_id=" + identity
    if kind == "rewards" and re.fullmatch(r"0x[0-9a-f]{64}", identity):
        return "https://clob.polymarket.com/rewards/markets/" + identity
    if kind == "discovery" and re.fullmatch(r"[a-z0-9-]{1,180}", identity):
        return "https://gamma-api.polymarket.com/events?slug=" + identity
    raise ValueError("public_endpoint_refused")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("public_redirect_refused")


class HttpReads:
    def __init__(self):
        self._opener = build_opener(ProxyHandler({}), NoRedirect())

    def read(self, kind, identity):
        url = endpoint(kind, identity)
        with self._opener.open(Request(url, method="GET", headers={"Accept": "application/json"}), timeout=1) as response:
            if response.status != 200 or response.geturl() != url:
                raise ValueError("public_response_refused")
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError("public_response_cap")
        return raw


class PublicAdapter:
    """Test transport receives only already-validated endpoint identities."""
    def __init__(self, transport, *, clock):
        self._transport, self.clock = transport, clock

    def read(self, kind, identity):
        endpoint(kind, identity)
        raw = self._transport.read(kind, identity)
        if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE:
            raise ValueError("public_response_cap")
        value = json.loads(raw)
        canonical_bytes(value)  # Reject NaN/Infinity before projection.
        return self.clock(), value


class MarketStream:
    def __init__(self, assets):
        # Local import is deliberately visible to the transitive import ratchet.
        import websocket
        assets = tuple(assets)
        if not 1 <= len(set(assets)) == len(assets) <= 64:
            raise ValueError("public_subscription_scope")
        for asset in assets:
            endpoint("book", asset)
        self._socket = websocket.create_connection(STREAM_URL, timeout=.25, redirect_limit=0,
                                                    http_no_proxy=["*"], enable_multithread=False)
        self._socket.send(json.dumps({"assets_ids": list(assets), "type": "market"}))
        self._timeout = websocket.WebSocketTimeoutException

    def receive(self):
        try:
            raw = self._socket.recv()
        except self._timeout:
            return None
        if not raw:
            raise ValueError("public_stream_closed")
        if len(raw) > MAX_RESPONSE:
            raise ValueError("public_stream_frame_cap")
        return raw

    def ping(self):
        self._socket.send("PING")

    def close(self):
        self._socket.close(timeout=.25)
