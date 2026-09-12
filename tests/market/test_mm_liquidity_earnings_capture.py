"""The collector may observe accrual, but cannot manufacture a paid reward."""

import base64
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import ssl
from urllib.parse import parse_qs, urlsplit

import pytest

from weather.market import mm_liquidity_earnings_capture as owner
from weather.market.mm_liquidity_earnings_evidence import normalize_liquidity_earnings_pages

NOW = datetime(2026, 9, 11, 20, tzinfo=timezone.utc)
MAKER = "0x" + "a" * 40
SIGNER = "0x" + "b" * 40
ASSET = "0x" + "c" * 40
CONDITION = "0x" + "d" * 64
HEADERS = {
    "POLY_ADDRESS": SIGNER,
    "POLY_API_KEY": "fixture-api-key-never-persist",
    "POLY_PASSPHRASE": "fixture-passphrase-never-persist",
    "POLY_SIGNATURE": "fixture-signature-never-persist",
    "POLY_TIMESTAMP": "1789156800",
}


def body(*, rows=None, cursor="LTE=", **changes):
    row = {
        "date": "2026-09-10", "maker_address": MAKER, "condition_id": CONDITION,
        "asset_address": ASSET, "earnings": "0.100000000000000001", "asset_rate": "1",
    }
    row.update(changes)
    return json.dumps({
        "data": [row] if rows is None else rows, "count": 1 if rows is None else len(rows),
        "limit": 100, "next_cursor": cursor,
    }, indent=2).encode()


class Response:
    def __init__(self, raw, status=200, headers=None, error_after=None):
        self.raw = io.BytesIO(raw)
        self.status = status
        self.headers = {"Content-Type": "application/json", "Content-Length": str(len(raw))}
        self.headers.update(headers or {})
        self.error_after = error_after

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read1(self, count):
        if self.error_after is not None and self.raw.tell() >= self.error_after:
            raise OSError("error containing " + HEADERS["POLY_API_KEY"])
        if self.error_after is not None:
            count = min(count, self.error_after - self.raw.tell())
        return self.raw.read(count)


@pytest.fixture
def transport(monkeypatch):
    responses, calls, connections = [], [], []

    class Connection:
        sock = None

        def __init__(self, host, *, timeout, context):
            assert host == "clob.polymarket.com"
            assert 0 < timeout <= owner.REQUEST_TIMEOUT_SECONDS
            assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
            self.closed = False
            connections.append(self)

        def request(self, method, path, *, headers):
            assert method == "GET"
            assert path.startswith("/rewards/user?")
            calls.append((method, path, dict(headers)))

        def getresponse(self):
            result = responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        def close(self):
            self.closed = True

    monkeypatch.setattr(owner.http.client, "HTTPSConnection", Connection)
    return responses, calls, connections


def capture(tmp_path, **changes):
    args = {
        "query_date": "2026-09-10", "maker_address": MAKER, "signer_address": SIGNER,
        "signature_type": 2, "headers_provider": lambda *args: dict(HEADERS),
        "output_dir": tmp_path / "attempt", "clock": lambda: NOW,
    }
    args.update(changes)
    return owner.capture_liquidity_earnings(**args)


def request_file(tmp_path, n=1):
    return json.loads((tmp_path / "attempt" / f"request-{n:03d}.json").read_text())


def test_complete_capture_replays_exact_decimals_and_keeps_cash_unknown(tmp_path, transport):
    responses, calls, connections = transport
    first = body(cursor="opaque+cursor=").replace(
        b'"0.100000000000000001"', b'0.100000000000000001',
    )
    second = body(condition_id="0x" + "e" * 64, earnings="0.2")
    responses.extend([Response(first), Response(second)])
    result = capture(tmp_path)
    assert result["status"] == "COMPLETE"
    assert result["network_request_count"] == result["request_count"] == 2
    assert result["earnings"]["earnings_by_asset"] == {ASSET: "0.300000000000000001"}
    assert parse_qs(urlsplit(calls[1][1]).query)["next_cursor"] == ["opaque+cursor="]
    assert all(connection.closed for connection in connections)
    pages = []
    for index, raw in enumerate((first, second), 1):
        filename = tmp_path / "attempt" / f"request-{index:03d}.json"
        assert hashlib.sha256(filename.read_bytes()).hexdigest() == result["requests"][index - 1]["sha256"]
        page = request_file(tmp_path, index)
        assert base64.b64decode(page["response"]["response_body_base64"]) == raw
        assert page["body_complete"] is True
        pages.append(page["response"])
    replay = normalize_liquidity_earnings_pages(
        pages, query_date="2026-09-10", maker_address=MAKER,
        signature_type=2, sponsored=False, as_of_utc=NOW.isoformat(),
    )
    assert result["earnings"] == {key: value for key, value in replay.items() if key != "pages"}
    assert result["paid_incentive_amount"] is None
    assert result["attribution_status"] == "ATTRIBUTION_BLOCKED"
    assert all(result[key] is False for key in (
        "payment_verified", "accrual_linkage_verified", "account_cash_completeness_verified",
        "source_authenticity_verified", "identity_binding_verified", "live_authority",
    ))
    saved = "".join(path.read_text() for path in (tmp_path / "attempt").iterdir())
    for key in owner.SECRET_HEADER_NAMES:
        assert HEADERS[key] not in saved


def test_completed_empty_scope_is_not_zero_paid_income(tmp_path, transport):
    transport[0].append(Response(body(rows=[])))
    result = capture(tmp_path)
    assert result["earnings"]["status"] == "COMPLETE_EMPTY_SCOPE"
    assert result["earnings"]["earnings_by_asset"] == {}
    assert result["paid_incentive_amount"] is None


def test_exact_authenticated_request_scope_and_query_callback(tmp_path, transport):
    transport[0].append(Response(body()))
    observed = []

    def provider(method, path, query):
        observed.append((method, path, query))
        query["maker_address"] = "callback-cannot-change-request"
        return HEADERS

    result = capture(tmp_path, headers_provider=provider, sponsored=True)
    expected = {
        "date": ["2026-09-10"], "signature_type": ["2"],
        "maker_address": [MAKER], "sponsored": ["true"],
    }
    assert parse_qs(urlsplit(transport[1][0][1]).query) == expected
    assert observed[0][:2] == ("GET", "/rewards/user")
    assert result["scope"]["sponsored"] is True


@pytest.mark.parametrize("changes", [
    {"query_date": "2026-09-12"}, {"query_date": "bad"}, {"signature_type": 3},
    {"signature_type": True}, {"sponsored": "false"}, {"maker_address": "bad"},
    {"signer_address": "bad"}, {"signature_type": 0}, {"headers_provider": None},
    {"output_dir": "relative"}, {"clock": lambda: NOW.replace(tzinfo=None)},
])
def test_invalid_intent_cannot_contact_account_or_create_attempt(tmp_path, transport, changes):
    with pytest.raises((ValueError, TypeError)):
        capture(tmp_path, **changes)
    assert not transport[1]
    assert not (tmp_path / "attempt").exists()


def test_spent_attempt_is_never_reused(tmp_path, transport):
    (tmp_path / "attempt").mkdir()
    with pytest.raises(FileExistsError):
        capture(tmp_path)
    assert not transport[1]


@pytest.mark.parametrize("headers", [
    {}, {**HEADERS, "Authorization": "extra"},
    {**HEADERS, "POLY_ADDRESS": MAKER},
    {**HEADERS, "POLY_SIGNATURE": "header\rinjection"},
])
def test_bad_authentication_has_no_request_and_no_secret_exception(tmp_path, transport, headers):
    result = capture(tmp_path, headers_provider=lambda *args: headers)
    assert result["error"] == "authentication_failed"
    assert result["network_request_count"] == 0 and not transport[1]
    assert result["earnings"] is None


def test_callback_exception_is_sanitized(tmp_path, transport):
    def provider(*args):
        raise RuntimeError(HEADERS["POLY_API_KEY"])

    result = capture(tmp_path, headers_provider=provider)
    assert result["error"] == "authentication_failed"
    assert HEADERS["POLY_API_KEY"] not in (tmp_path / "attempt" / "capture.json").read_text()


@pytest.mark.parametrize("status", [302, 401, 429, 500])
def test_http_failure_is_retained_and_never_redirected_or_retried(tmp_path, transport, status):
    raw = b'{"error": "request failed"}'
    transport[0].append(Response(raw, status, {"Location": "https://other.example"}))
    result = capture(tmp_path)
    assert result["error"] == "http_status_not_success"
    assert result["request_count"] == 1
    assert base64.b64decode(request_file(tmp_path)["response"]["response_body_base64"]) == raw
    assert result["earnings"] is None


def test_partial_network_failure_preserves_previous_page_and_prefix(tmp_path, transport):
    transport[0].extend([Response(body(cursor="next")), Response(body(), error_after=20)])
    result = capture(tmp_path)
    assert result["error"] == "transport_failed" and result["earnings"] is None
    failed = request_file(tmp_path, 2)
    assert base64.b64decode(failed["response"]["response_body_base64"]) == body()[:20]
    assert failed["body_complete"] is False
    assert request_file(tmp_path)["cursor_out"] == "next"
    assert all(connection.closed for connection in transport[2])


@pytest.mark.parametrize("raw", [
    b'{"data":[],"count":0,"count":1,"limit":100,"next_cursor":"LTE="}',
    b'{"data":[],"count":NaN,"limit":100,"next_cursor":"LTE="}',
    b'[]', body(cursor="next", rows=[]),
    b'{"data":[],"count":true,"limit":100,"next_cursor":"LTE="}',
    b'{"data":[],"count":0,"limit":100}',
])
def test_invalid_pages_cannot_complete_or_select_another_cursor(tmp_path, transport, raw):
    transport[0].append(Response(raw))
    result = capture(tmp_path)
    assert result["error"] == "invalid_earnings_page"
    assert result["request_count"] == 1 and result["earnings"] is None


@pytest.mark.parametrize("changes", [
    {"maker_address": SIGNER}, {"date": "2026-09-09"}, {"earnings": "-1"},
])
def test_final_validator_rejects_wrong_identity_or_amount(tmp_path, transport, changes):
    transport[0].append(Response(body(**changes)))
    result = capture(tmp_path)
    assert result["error"] == "earnings_scope_or_evidence_invalid"
    assert result["pagination_complete"] is False and result["earnings"] is None


def test_cursor_cycle_stops_with_raw_failure_evidence(tmp_path, transport):
    transport[0].extend([Response(body(cursor="next")), Response(body(cursor="next"))])
    result = capture(tmp_path)
    assert result["error"] == "invalid_earnings_page"
    assert result["request_count"] == 2


def test_response_budget_retains_prefix_and_never_normalizes(tmp_path, transport, monkeypatch):
    monkeypatch.setattr(owner, "MAX_RESPONSE_BYTES", 64)
    transport[0].append(Response(body()))
    result = capture(tmp_path)
    assert result["error"] == "response_byte_budget_exceeded"
    assert request_file(tmp_path)["response"]["response_bytes"] == 64
    assert not request_file(tmp_path)["body_complete"]
    assert result["earnings"] is None


def test_total_byte_budget_stops_before_another_request(tmp_path, transport, monkeypatch):
    raw = body(cursor="next")
    monkeypatch.setattr(owner, "MAX_TOTAL_RESPONSE_BYTES", len(raw))
    transport[0].append(Response(raw))
    result = capture(tmp_path)
    assert result["error"] == "capture_budget_exhausted"
    assert result["network_request_count"] == 1 and not result["pagination_complete"]


def test_page_budget_never_means_complete(tmp_path, transport, monkeypatch):
    monkeypatch.setattr(owner, "MAX_PAGES", 1)
    transport[0].append(Response(body(cursor="next")))
    result = capture(tmp_path)
    assert result["error"] == "page_budget_exhausted"
    assert result["earnings"] is None


@pytest.mark.parametrize("headers,error", [
    ({"Content-Length": "99999"}, "incomplete_response_body"),
    ({"Content-Length": "bad"}, "invalid_content_length"),
    ({"Content-Encoding": "gzip"}, "encoded_response_unsupported"),
    ({"Content-Type": "text/html"}, "response_content_type_not_json"),
])
def test_transport_completeness_and_encoding(tmp_path, transport, headers, error):
    transport[0].append(Response(body(), headers=headers))
    result = capture(tmp_path)
    assert result["error"] == error and result["earnings"] is None


@pytest.mark.parametrize("where", ["body", "metadata"])
def test_authentication_secret_echo_is_withheld(tmp_path, transport, where):
    raw = HEADERS["POLY_API_KEY"].encode() if where == "body" else b"error"
    extra = {"Content-Type": HEADERS["POLY_API_KEY"]} if where == "metadata" else {}
    transport[0].append(Response(raw, status=500, headers=extra))
    result = capture(tmp_path)
    assert result["error"] == "response_contains_authentication_secret"
    assert request_file(tmp_path)["response"] is None
    assert request_file(tmp_path)["response_body_withheld"] is True


def test_slow_body_is_stopped_at_capture_deadline(tmp_path, transport):
    elapsed = [0]

    class SlowResponse(Response):
        def read1(self, count):
            elapsed[0] += 61
            return super().read1(count)

    transport[0].append(SlowResponse(body()))
    result = capture(tmp_path, monotonic=lambda: elapsed[0])
    assert result["error"] == "capture_deadline_exceeded"
    assert result["earnings"] is None
    assert all(connection.closed for connection in transport[2])


def test_module_import_is_from_this_worktree():
    expected = Path(__file__).resolve().parents[2] / "src/weather/market/mm_liquidity_earnings_capture.py"
    assert Path(owner.__file__).resolve() == expected
