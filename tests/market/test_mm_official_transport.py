import json
from urllib.parse import parse_qs, urlsplit

import pytest

from weather.market.mm_official_transport import (
    OfficialHeartbeatSender,
    build_l2_hmac_signature,
    fetch_market_rule_endpoints,
    fetch_wallet_deployed,
)


ADDRESS = "0x" + "a" * 40


class Response:
    def __init__(self, payload, status=200):
        self.status = status
        self.payload = payload
        self.closed = False

    def read(self, limit):
        assert limit == 1_000_001
        return json.dumps(self.payload).encode("utf-8")

    def close(self):
        self.closed = True


def test_l2_hmac_matches_the_official_algorithm_vector():
    assert build_l2_hmac_signature(
        secret="c2VjcmV0",
        timestamp=123,
        method="POST",
        path="/heartbeats",
    ) == "a_kOkfbXgDKadsqAtSYCy8T4UjQ8ATIQKZvUyY10zXY="


def test_heartbeat_sender_is_one_purpose_bodyless_and_redacted():
    captured = {}

    def opener(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response({"status": "ok"})

    sender = OfficialHeartbeatSender(
        signer_address=ADDRESS,
        api_key="api-key-secret",
        api_secret="c2VjcmV0",
        api_passphrase="passphrase-secret",
        opener=opener,
        clock=lambda: 123,
    )

    assert sender.send() == {"status": "ok"}
    request = captured["request"]
    headers = {key.lower(): value for key, value in request.header_items()}
    assert request.full_url == "https://clob.polymarket.com/heartbeats"
    assert request.get_method() == "POST"
    assert request.data == b""
    assert captured["timeout"] == 15.0
    assert headers["poly_address"] == ADDRESS
    assert headers["poly_timestamp"] == "123"
    assert headers["poly_signature"] == (
        "a_kOkfbXgDKadsqAtSYCy8T4UjQ8ATIQKZvUyY10zXY="
    )
    assert "api-key-secret" not in repr(sender)
    assert "passphrase-secret" not in repr(sender)


@pytest.mark.parametrize("payload", [{"status": "OK"}, {"status": "ok", "id": "old"}, {}])
def test_heartbeat_sender_rejects_every_noncanonical_ack(payload):
    sender = OfficialHeartbeatSender(
        signer_address=ADDRESS,
        api_key="key",
        api_secret="c2VjcmV0",
        api_passphrase="passphrase",
        opener=lambda _request, timeout: Response(payload),
        clock=lambda: 123,
    )

    with pytest.raises(RuntimeError, match="exact success acknowledgment"):
        sender.send()


@pytest.mark.parametrize("signature_type,expected_type", [(2, "SAFE"), (3, "WALLET")])
def test_wallet_deployment_preflight_uses_exact_public_relayer_scope(
    signature_type,
    expected_type,
):
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        return Response({"deployed": True})

    assert fetch_wallet_deployed(ADDRESS, signature_type, opener=opener) is True
    parsed = urlsplit(captured["url"])
    assert (parsed.scheme, parsed.netloc, parsed.path) == (
        "https",
        "relayer-v2.polymarket.com",
        "/deployed",
    )
    assert parse_qs(parsed.query) == {
        "address": [ADDRESS],
        "type": [expected_type],
    }


def test_wallet_deployment_preflight_rejects_ambiguous_shape():
    with pytest.raises(RuntimeError, match="boolean deployed"):
        fetch_wallet_deployed(
            ADDRESS,
            3,
            opener=lambda _request, timeout: Response({"deployed": 1}),
        )


def test_market_rule_reader_cross_checks_all_public_protocol_gaps():
    paths = []

    def opener(request, timeout):
        parsed = urlsplit(request.full_url)
        paths.append((parsed.path, parse_qs(parsed.query)))
        payloads = {
            "/tick-size": {"minimum_tick_size": "0.01"},
            "/neg-risk": {"neg_risk": False},
            "/fee-rate": {"base_fee": 50},
        }
        return Response(payloads[parsed.path])

    observed = fetch_market_rule_endpoints("123", opener=opener)

    assert str(observed["tick_size"]) == "0.01"
    assert observed["neg_risk"] is False
    assert str(observed["fee_rate_bps"]) == "50"
    assert paths == [
        ("/tick-size", {"token_id": ["123"]}),
        ("/neg-risk", {"token_id": ["123"]}),
        ("/fee-rate", {"token_id": ["123"]}),
    ]


def test_protocol_errors_never_echo_secret_material():
    sender = OfficialHeartbeatSender(
        signer_address=ADDRESS,
        api_key="do-not-echo-key",
        api_secret="c2VjcmV0",
        api_passphrase="do-not-echo-passphrase",
        opener=lambda _request, timeout: Response({}, status=401),
        clock=lambda: 123,
    )

    with pytest.raises(RuntimeError) as exc_info:
        sender.send()
    text = str(exc_info.value)
    assert "do-not-echo-key" not in text
    assert "do-not-echo-passphrase" not in text
