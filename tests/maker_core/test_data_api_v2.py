"""Guards: Data API v2 public prints never turn retired or partial reads into no trades."""
from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from maker_core.venue import public_feed as public
from maker_core.shadow.paper import parse_prints

FIXTURE = Path(__file__).parents[1] / "fixtures" / "data_api_v2_trades.json"


def page():
    return json.loads(FIXTURE.read_text())["trades"]


def test_cursor_walk_preserves_public_filter_and_paper_identity():
    first = page()
    row = first["data"][0]
    cid = row["condition_id"]
    last = deepcopy(first)
    last["data"][0]["token_id"] = "124"
    last["data"][0]["timestamp"] += 1
    first["pagination"].update(has_more=True, next_cursor="opaque+/=")
    transport = public.FixtureTransport({public.trades_url(cid): first,
                                        public.trades_url(cid, "opaque+/="): last})
    rows = public.PublicFeed(transport).trades(cid)
    assert len(rows) == 2
    assert [r["asset"] for r in rows] == ["123", "124"]
    assert all(r["conditionId"] == cid for r in rows)
    assert rows[0]["transactionHash"] == row["transaction_hash"]
    prints = parse_prints(rows, cid)
    assert [p[1] for p in prints] == ["123", "124"]
    assert str(prints[0][3]) == "2.5"
    query = parse_qs(urlsplit(transport.requests[1]).query)
    assert query == {"condition": [cid], "limit": ["500"], "cursor": ["opaque+/="],
                     "taker_only": ["true"], "filter_type": ["TOKENS"], "filter_amount": ["0.01"]}


@pytest.mark.parametrize("status", [201, 400, 410, 429, 500])
def test_non_200_never_yields_empty_prints(status):
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, limit):
            return json.dumps(page()).encode()
        def geturl(self):
            return public.trades_url(page()["data"][0]["condition_id"])
    response = Response()
    response.status = status
    class Opener:
        def open(self, request, timeout):
            assert request.get_method() == "GET"
            return response
    with pytest.raises(ValueError, match="public_read_refused"):
        public.PublicFeed(public.UrllibTransport(opener=Opener())).trades(page()["data"][0]["condition_id"])


@pytest.mark.parametrize("field,value", [("size", None), ("price", None), ("size", "2"),
                                         ("size", float("nan")), ("size", -1),
                                         ("size", True), ("price", 2), ("token_id", None),
                                         ("condition_id", "wrong"), ("transaction_hash", ""),
                                         ("side", "unknown"), ("timestamp", None)])
def test_malformed_row_refuses_entire_poll(field, value):
    payload = page()
    cid = payload["data"][0]["condition_id"]
    payload["data"][0][field] = value
    with pytest.raises(ValueError):
        public.PublicFeed(public.FixtureTransport({public.trades_url(cid): payload})).trades(cid)


def test_missing_size_is_refused():
    payload = page()
    cid = payload["data"][0]["condition_id"]
    del payload["data"][0]["size"]
    with pytest.raises(ValueError):
        public.PublicFeed(public.FixtureTransport({public.trades_url(cid): payload})).trades(cid)


@pytest.mark.parametrize("payload", [[], {}, {"data": []}, {"data": None, "pagination": {}},
    {"data": [], "pagination": {"has_more": 0, "next_cursor": None}},
    {"data": [], "pagination": {"has_more": False}},
    {"data": [], "pagination": {"has_more": False, "next_cursor": "extra"}},
    {"data": [], "pagination": {"has_more": True, "next_cursor": None}}])
def test_malformed_envelope_is_not_an_empty_feed(payload):
    cid = page()["data"][0]["condition_id"]
    with pytest.raises(ValueError):
        public.PublicFeed(public.FixtureTransport({public.trades_url(cid): payload})).trades(cid)


def test_cursor_cycle_and_budget_refuse_partial_results(monkeypatch):
    payload = page()
    cid = payload["data"][0]["condition_id"]
    payload["pagination"].update(has_more=True, next_cursor="repeat")
    feed = public.PublicFeed(public.FixtureTransport({public.trades_url(cid): payload,
                                                    public.trades_url(cid, "repeat"): payload}))
    with pytest.raises(ValueError, match="cursor"):
        feed.trades(cid)
    monkeypatch.setattr(public, "MAX_TRADES_PAGES", 1)
    with pytest.raises(ValueError, match="budget"):
        feed.trades(cid)


@pytest.mark.parametrize("suffix", ["&user=0x1", "&offset=0", "&cursor=", "&cursor=x&cursor=y"])
def test_only_condition_cursor_query_is_allowed(suffix):
    cid = page()["data"][0]["condition_id"]
    with pytest.raises(ValueError):
        public.public_url(public.trades_url(cid) + suffix)


def test_empty_final_page_is_a_successful_empty_feed():
    payload = page()
    cid = payload["data"][0]["condition_id"]
    payload["data"] = []
    transport = public.FixtureTransport({public.trades_url(cid): payload})
    assert public.PublicFeed(transport).trades(cid) == []
    assert transport.requests == [public.trades_url(cid)]


def test_later_malformed_row_discards_prior_valid_page():
    first = page()
    cid = first["data"][0]["condition_id"]
    last = deepcopy(first)
    del last["data"][0]["size"]
    first["pagination"].update(has_more=True, next_cursor="next")
    transport = public.FixtureTransport({public.trades_url(cid): first,
                                        public.trades_url(cid, "next"): last})
    with pytest.raises(ValueError):
        public.PublicFeed(transport).trades(cid)
    assert transport.requests == [public.trades_url(cid), public.trades_url(cid, "next")]


@pytest.mark.parametrize("status", [400, 410])
def test_later_http_failure_discards_prior_valid_page(status):
    from urllib.error import HTTPError

    first = page()
    cid = first["data"][0]["condition_id"]
    first["pagination"].update(has_more=True, next_cursor="next")
    transport = public.FixtureTransport({public.trades_url(cid): first})
    class FailingCursorTransport:
        def get(self, url):
            if url == public.trades_url(cid, "next"):
                raise HTTPError(url, status, "refused", {}, None)
            return transport.get(url)
    with pytest.raises(HTTPError) as exc:
        public.PublicFeed(FailingCursorTransport()).trades(cid)
    assert exc.value.code == status


def test_full_final_page_stops_on_pagination_not_row_count():
    payload = page()
    cid = payload["data"][0]["condition_id"]
    payload["data"] *= public.TRADES_LIMIT
    transport = public.FixtureTransport({public.trades_url(cid): payload})
    assert len(public.PublicFeed(transport).trades(cid)) == public.TRADES_LIMIT
    assert transport.requests == [public.trades_url(cid)]


@pytest.mark.parametrize("cursor", [None, "", 5, "x" * (public.MAX_CURSOR_LENGTH + 1), "bad cursor"])
def test_invalid_continuation_never_returns_first_page(cursor):
    payload = page()
    cid = payload["data"][0]["condition_id"]
    payload["pagination"].update(has_more=True, next_cursor=cursor)
    with pytest.raises(ValueError):
        public.PublicFeed(public.FixtureTransport({public.trades_url(cid): payload})).trades(cid)


def test_hex_condition_case_preserves_the_exact_condition_scope():
    payload = page()
    cid = payload["data"][0]["condition_id"]
    payload["data"][0]["condition_id"] = cid.upper()
    rows = public.PublicFeed(public.FixtureTransport({public.trades_url(cid): payload})).trades(cid)
    assert len(rows) == 1 and rows[0]["conditionId"] == cid
    assert len(parse_prints(rows, cid)) == 1


@pytest.mark.parametrize("raw", [
    b'{"data":[{}],"data":[],"pagination":{"has_more":false,"next_cursor":null}}',
    b'{"data":[],"pagination":{"has_more":true,"has_more":false,"next_cursor":null}}',
    b'{"data":[],"pagination":{"has_more":false,"next_cursor":null},"unused":NaN}',
    b'{"data":[],"pagination":{"has_more":false,"next_cursor":null},"unused":Infinity}',
    b'{',
])
def test_ambiguous_or_non_json_wire_reply_never_proves_an_empty_feed(raw):
    cid = page()["data"][0]["condition_id"]
    transport = public.FixtureTransport({public.trades_url(cid): raw})
    with pytest.raises(ValueError):
        public.PublicFeed(transport).trades(cid)


def test_error_bearing_success_body_is_refused():
    payload = page()
    cid = payload["data"][0]["condition_id"]
    payload.update(data=[], error="unavailable")
    with pytest.raises(ValueError):
        public.PublicFeed(public.FixtureTransport({public.trades_url(cid): payload})).trades(cid)


@pytest.mark.parametrize("field,value", [
    ("timestamp", True), ("timestamp", 0), ("timestamp", -1),
    ("timestamp", 253402300800), ("timestamp", 10 ** 100),
    ("side", []), ("size", 10 ** 1000),
])
def test_unusable_print_fields_are_refused_before_the_recorder(field, value):
    payload = page()
    cid = payload["data"][0]["condition_id"]
    payload["data"][0][field] = value
    with pytest.raises(ValueError):
        public.PublicFeed(public.FixtureTransport({public.trades_url(cid): payload})).trades(cid)


def test_complete_cursor_walk_shares_the_original_reply_byte_budget(monkeypatch):
    first = page()
    cid = first["data"][0]["condition_id"]
    last = page()
    first["pagination"].update(has_more=True, next_cursor="next")
    first_size, last_size = (len(json.dumps(p).encode()) for p in (first, last))
    replies = {public.trades_url(cid): first, public.trades_url(cid, "next"): last}
    monkeypatch.setattr(public, "MAX_REPLY_BYTES", first_size + last_size)
    assert len(public.PublicFeed(public.FixtureTransport(replies)).trades(cid)) == 2
    monkeypatch.setattr(public, "MAX_REPLY_BYTES", first_size + last_size - 1)
    assert max(first_size, last_size) <= public.MAX_REPLY_BYTES
    transport = public.FixtureTransport(replies)
    with pytest.raises(ValueError, match="bytes_exhausted"):
        public.PublicFeed(transport).trades(cid)
    assert transport.requests == [public.trades_url(cid), public.trades_url(cid, "next")]


@pytest.mark.parametrize("old,new", [("taker_only=true", "taker_only=false"),
                                     ("filter_type=TOKENS", "filter_type=CASH"),
                                     ("filter_amount=0.01", "filter_amount=0")])
def test_print_role_and_size_filters_cannot_change_mid_walk(old, new):
    cid = page()["data"][0]["condition_id"]
    with pytest.raises(ValueError):
        public.public_url(public.trades_url(cid, "next").replace(old, new))
