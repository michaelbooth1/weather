"""Daily earnings are scoped accrual observations, never wallet payments."""

import base64
from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import urlencode

import pytest

from weather.market import mm_liquidity_earnings_evidence as owner
from weather.market.exchange_economics_sources import response_evidence


DAY = "2026-09-10"
NOW = "2026-09-11T08:00:00Z"
MAKER = "0x" + "a" * 40
ASSET = "0x" + "b" * 40
CONDITION = "0x" + "c" * 64
OTHER_CONDITION = "0x" + "d" * 64


def earning(**changes):
    row = {
        "date": DAY + "T00:00:00Z", "maker_address": MAKER,
        "asset_address": ASSET, "condition_id": CONDITION,
        "earnings": "0.100000000000000001", "asset_rate": "1",
    }
    row.update(changes)
    return row


def page(rows=None, *, cursor=None, next_cursor="LTE=", query=None, payload=None, raw=None):
    params = {"date": DAY, "signature_type": "2"}
    if cursor is not None:
        params["next_cursor"] = cursor
    if query:
        params.update(query)
    rows = [earning()] if rows is None else rows
    payload = payload if payload is not None else {
        "limit": 100, "count": len(rows), "next_cursor": next_cursor, "data": rows,
    }
    body = raw if raw is not None else json.dumps(payload).encode()
    evidence = response_evidence(
        body, url="https://clob.polymarket.com/rewards/user?" + urlencode(params),
        http_status=200, content_type="application/json; charset=utf-8",
        origin="http_response_bytes",
    )
    evidence["retrieved_at_utc"] = "2026-09-11T07:59:00Z"
    return evidence


def normalize(pages=None, **changes):
    scope = dict(query_date=DAY, maker_address=MAKER, signature_type=2, as_of_utc=NOW)
    scope.update(changes)
    return owner.normalize_liquidity_earnings_pages([page()] if pages is None else pages, **scope)


def test_earnings_source_identity():
    expected = Path(__file__).resolve().parents[2] / "src/weather/market/mm_liquidity_earnings_evidence.py"
    assert Path(owner.__file__).resolve() == expected
    print("EARNINGS_OWNER_SOURCE=" + str(Path(owner.__file__).resolve()))


def test_complete_pages_retain_exact_bytes_and_separate_assets_from_payments():
    first = page(next_cursor="next+opaque=")
    second = page(
        [earning(condition_id=OTHER_CONDITION, earnings="0.2"),
         earning(asset_address="0x" + "e" * 40, earnings="3")],
        cursor="next+opaque=",
    )
    sources = [first, second]
    before = deepcopy(sources)
    result = normalize(sources)
    assert sources == before
    assert result["earnings_by_asset"] == {ASSET: "0.300000000000000001", "0x" + "e" * 40: "3"}
    assert result["row_count"] == 3 and result["page_count"] == 2
    assert result["pagination_complete"] is True
    assert result["paid_incentive_amount"] is None
    assert result["status"] == "ACCRUAL_OBSERVED"
    assert all(result[name] is False for name in (
        "payment_verified", "accrual_finality_verified", "accrual_linkage_verified",
        "source_authenticity_verified", "account_cash_completeness_verified",
    ))
    assert result["pages"][0] == first
    assert result["rows"][2]["page_index"] == 1
    assert result["rows"][2]["response_sha256"] == second["response_sha256"]


def test_terminal_empty_is_only_empty_scope_and_explicit_zero_is_accrual():
    empty = normalize([page([])])
    assert empty["status"] == "COMPLETE_EMPTY_SCOPE"
    assert empty["earnings_by_asset"] == {}
    assert empty["paid_incentive_amount"] is None
    zero = normalize([page([earning(earnings=0)])])
    assert zero["status"] == "ACCRUAL_OBSERVED"
    assert zero["earnings_by_asset"] == {ASSET: "0"}


def test_exact_json_decimal_spelling_and_whitespace_survive():
    body = json.dumps({
        "limit": 100, "count": 1, "next_cursor": "LTE=",
        "data": [earning(earnings="PLACEHOLDER")],
    }, indent=2).replace('"PLACEHOLDER"', "0.100000000000000001").encode()
    result = normalize([page(raw=body)])
    assert result["rows"][0]["earnings"] == "0.100000000000000001"
    assert base64.b64decode(result["pages"][0]["response_body_base64"]) == body


@pytest.mark.parametrize("change", [
    {"date": "2026-09-09"}, {"signature_type": "1"}, {"maker_address": "0x" + "f" * 40},
    {"sponsored": "true"}, {"next_cursor": "unrequested"}, {"unrecognized": "value"},
])
def test_wrong_query_scope_is_rejected(change):
    with pytest.raises(ValueError, match="scope"):
        normalize([page(query=change)])


def test_explicit_maker_and_sponsored_scope():
    result = normalize([page(query={"maker_address": MAKER, "sponsored": "true"})], sponsored=True)
    assert result["sponsored"] is True
    assert normalize([page(query={"sponsored": "false"})])["sponsored"] is False


@pytest.mark.parametrize("url", [
    "http://clob.polymarket.com/rewards/user",
    "https://evil.example/rewards/user",
    "https://clob.polymarket.com:443/rewards/user",
    "https://clob.polymarket.com/rewards/user/earnings",
    "https://user@clob.polymarket.com/rewards/user",
])
def test_endpoint_identity_is_exact(url):
    evidence = page()
    evidence["url"] = url + "?date=" + DAY + "&signature_type=2"
    with pytest.raises(ValueError, match="endpoint"):
        normalize([evidence])


def test_duplicate_query_keys_do_not_collapse():
    evidence = page()
    evidence["url"] += "&date=" + DAY
    with pytest.raises(ValueError, match="scope"):
        normalize([evidence])


@pytest.mark.parametrize("payload", [
    {}, {"data": None}, {"data": []}, {"data": "error"},
    {"data": [], "count": 0, "limit": 100, "next_cursor": "LTE=", "error": "unavailable"},
    {"data": [], "count": 0, "limit": 100, "next_cursor": "LTE=", "errors": []},
    {"data": [], "count": 0, "limit": 100},
    {"data": [], "count": 0, "limit": 100, "next_cursor": None},
    {"data": [], "count": False, "limit": 100, "next_cursor": "LTE="},
    {"data": [], "count": 1, "limit": 100, "next_cursor": "LTE="},
    {"data": [], "count": 0, "limit": True, "next_cursor": "LTE="},
    {"data": [], "count": 0, "limit": 101, "next_cursor": "LTE="},
    {"data": [], "count": 0, "limit": 0, "next_cursor": "LTE="},
    {"data": [], "count": 0, "limit": 100, "next_cursor": ""},
])
def test_incomplete_or_malformed_envelopes_never_become_zero(payload):
    with pytest.raises(ValueError):
        normalize([page(payload=payload)])


@pytest.mark.parametrize("pages", [
    [], [page(next_cursor="more")],
    [page(), page(cursor="LTE=")],
    [page(next_cursor="more"), page(cursor="wrong")],
    [page([], next_cursor="more"), page(cursor="more")],
    [page(next_cursor="more"), page([earning(condition_id=OTHER_CONDITION)], cursor="more", next_cursor="more"), page(cursor="more")],
])
def test_pagination_must_be_complete_ordered_and_acyclic(pages):
    with pytest.raises(ValueError):
        normalize(pages)


@pytest.mark.parametrize("different_case", [False, True])
def test_duplicate_identity_across_pages_is_rejected(different_case):
    duplicate = earning()
    if different_case:
        duplicate["condition_id"] = "0x" + "C" * 64
        duplicate["asset_address"] = "0x" + "B" * 40
    with pytest.raises(ValueError, match="duplicate"):
        normalize([page(next_cursor="more"), page([duplicate], cursor="more")])


@pytest.mark.parametrize("changes", [
    {"maker_address": "0x" + "f" * 40}, {"condition_id": "bad"},
    {"asset_address": "pUSD"}, {"date": "2026-09-09T00:00:00Z"},
    {"date": DAY + "T00:00:01Z"}, {"date": DAY + "T00:00:00"},
    {"date": 1788998400000}, {"earnings": -1}, {"earnings": True},
    {"earnings": "NaN"}, {"earnings": "Infinity"}, {"earnings": "1e100000"},
    {"earnings": "1e-100000"}, {"earnings": "0." + "0" * 127 + "1"},
    {"asset_rate": -1}, {"asset_rate": None}, {"earnings": None},
])
def test_wrong_row_scope_or_unbounded_numbers_are_rejected(changes):
    with pytest.raises(ValueError):
        normalize([page([earning(**changes)])])


@pytest.mark.parametrize("raw", [
    b'{"limit":100,"count":0,"data":[],"next_cursor":"LTE=","next_cursor":"LTE="}',
    b'{"limit":100,"count":0,"data":[],"next_cursor":"LTE=","extra":NaN}',
    b'not-json', b'[]', b'\xff',
])
def test_invalid_wire_json_is_rejected(raw):
    with pytest.raises(ValueError):
        normalize([page(raw=raw)])


@pytest.mark.parametrize("changes", [
    {"response_body_base64": "broken"}, {"response_sha256": "0" * 64},
    {"response_bytes": 0}, {"http_status": 503}, {"http_status": True},
    {"request_method": "POST"}, {"content_type": "text/html"},
    {"response_origin": "unverified-sdk-items"},
])
def test_tampered_response_proof_is_rejected(changes):
    evidence = page()
    evidence.update(changes)
    with pytest.raises(ValueError):
        normalize([evidence])


@pytest.mark.parametrize("retrieved", [
    "2026-09-11T06:00:00Z", "2026-09-11T08:00:01Z", "2026-09-11T07:59:00",
])
def test_stale_future_or_unzoned_retrieval_is_rejected(retrieved):
    evidence = page()
    evidence["retrieved_at_utc"] = retrieved
    with pytest.raises(ValueError):
        normalize([evidence])


def test_retrieval_order_is_preserved_and_input_claims_are_not_promoted():
    first, second = page(next_cursor="more"), page([earning(condition_id=OTHER_CONDITION)], cursor="more")
    second["retrieved_at_utc"] = "2026-09-11T07:58:00Z"
    with pytest.raises(ValueError, match="unordered"):
        normalize([first, second])
    supplied = page()
    supplied["source_authenticity_verified"] = True
    supplied["secret_header"] = "must-not-be-copied"
    result = normalize([supplied])
    assert result["source_authenticity_verified"] is False
    assert "secret_header" not in result["pages"][0]


@pytest.mark.parametrize("changes", [
    {"signature_type": 3}, {"signature_type": True}, {"signature_type": "2"},
    {"sponsored": 1}, {"max_age_seconds": 0}, {"max_age_seconds": True},
    {"max_age_seconds": 86401}, {"as_of_utc": "2026-09-09T08:00:00Z"},
    {"query_date": "20260910"},
])
def test_expected_scope_is_validated(changes):
    with pytest.raises(ValueError):
        normalize(**changes)


def test_page_and_total_byte_budgets_are_refusal_boundaries(monkeypatch):
    with pytest.raises(ValueError, match="50"):
        normalize([page()] * 51)
    monkeypatch.setattr(owner, "MAX_TOTAL_RESPONSE_BYTES", 1)
    with pytest.raises(ValueError, match="total raw-byte"):
        normalize()


def test_unsupported_asset_remains_explicit_and_is_not_pusd():
    result = normalize([page([earning(asset_address="0x" + "f" * 40, earnings="7")])])
    assert result["earnings_by_asset"] == {"0x" + "f" * 40: "7"}
    assert result["paid_incentive_amount"] is None
