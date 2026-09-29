from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json

import pytest

from maker_core.evidence.journal import canonical_bytes
from maker_core.venue.public_read import PublicAdapter, HttpReads, NoRedirect, endpoint
from maker_core.shadow.public_feed import Feed
from tests.maker_core.fixtures.fictional_domain import FictionalDomain, T0


class RecordingTransport:
    def __init__(self, response=b"{}"):
        self.calls, self.response = [], response

    def read(self, kind, identity):
        self.calls.append(("GET", endpoint(kind, identity)))
        return self.response


@pytest.mark.parametrize("kind,identity", [
    ("order", "123"), ("cancel", "123"), ("balance", "123"), ("book", "../order"),
    ("book", "1&api_key=secret"), ("book", "https://evil.example"),
    ("rewards", "0x"+"a"*64+"/orders"), ("discovery", "name?user=x"),
])
def test_allowlist_blocks_before_transport(kind, identity):
    transport = RecordingTransport()
    adapter = PublicAdapter(transport, clock=lambda: T0)
    with pytest.raises(ValueError):
        adapter.read(kind, identity)
    assert not transport.calls


def test_recording_transport_only_public_gets_and_no_mutation_surface():
    transport = RecordingTransport()
    adapter = PublicAdapter(transport, clock=lambda: T0)
    for kind, identity in (("book", "123"), ("rewards", "0x"+"a"*64), ("discovery", "fixture-event")):
        assert adapter.read(kind, identity) == (T0, {})
    assert len(transport.calls) == 3
    for cls in (PublicAdapter, HttpReads):
        assert not any(hasattr(cls, n) for n in ("post", "delete", "cancel", "submit", "heartbeat", "credentials"))
    with pytest.raises(ValueError, match="redirect"):
        NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://evil.example")


def test_http_transport_fixes_method_timeout_and_response_cap():
    seen = []
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def geturl(self): return endpoint("book", "123")
        def read(self, limit):
            seen.append(limit)
            return b"{}"
    class Opener:
        def open(self, request, timeout):
            seen.append((request.method, request.full_url, request.headers, timeout))
            return Response()
    transport = HttpReads()
    transport._opener = Opener()
    assert transport.read("book", "123") == b"{}"
    assert seen[0] == ("GET", endpoint("book", "123"), {"Accept": "application/json"}, 1)
    assert seen[1] == 2*1024**2+1


def test_public_book_terms_and_trade_identity_projection():
    market = replace(FictionalDomain().market, condition_id="0x"+"a"*64,
                     outcome_tokens={"YES": "123", "NO": "456"})
    feed = Feed((market,))
    def book(asset):
        return {"asset_id": asset, "market": market.condition_id,
                "timestamp": str(int(T0.timestamp()*1000)), "tick_size": str(market.tick),
                "min_order_size": str(market.min_order_size), "bids": [{"price": ".49", "size": "75"}],
                "asks": [{"price": ".51", "size": "75"}]}
    row = feed.books(market.condition_id, T0, book("123"), book("456"))
    assert row.payload["as_of_utc"] == T0.isoformat()
    with pytest.raises(ValueError, match="identity"):
        feed.books(market.condition_id, T0, book("123"), book("789"))
    with pytest.raises(ValueError, match="clock"):
        feed.books(market.condition_id, T0+timedelta(seconds=11), book("123"), book("456"))
    trade = {"event_type": "last_trade_price", "asset_id": "123", "market": market.condition_id,
             "timestamp": str(int(T0.timestamp()*1000)), "price": ".47", "size": "2", "side": "SELL"}
    rows = feed.stream(T0, json.dumps(trade))
    assert rows[0].kind == "trade" and rows[0].payload["outcome"] == "YES"
    assert rows[1].kind == "coverage"
    assert feed.stream(T0, "PONG")[0].kind == "coverage"  # Does not create/refresh a book.
    bad = {**trade, "event_type": "tick_size_change"}
    with pytest.raises(ValueError, match="rules_changed"):
        feed.stream(T0, json.dumps(bad))
