"""Pinned SDK models at the attended transport boundary; no real signing/network."""
from dataclasses import replace
from types import SimpleNamespace
from decimal import Decimal
import base64
import hashlib
import hmac
import json
import pytest

from tests.market.stage2_fakes import CONDITION, TOKENS, MAKER
from tests.market.test_mm_stage2_rewards import sdk_fixture
from weather.market.re1_transport import OwnerVenue, bounded_rows


def fixture():
    pytest.importorskip('polymarket')
    from polymarket.models.clob.orders import SignedOrder
    from polymarket.models.clob.order_book import OrderBook
    request = dict(token_id=TOKENS[0], side='BUY', price='.33', size='20', post_only=True, expiration=2000000000)
    signed = SignedOrder(builder='0x' + '0' * 64, expiration=request['expiration'], maker=MAKER,
        maker_amount=6600000, metadata='0x' + '0' * 64, order_type='GTD', salt=1, side='BUY', signature='synthetic',
        signature_type=2, signer='0x' + 'c' * 40, taker_amount=20000000, timestamp=1, token_id=TOKENS[0], post_only=True)
    book = OrderBook.model_validate({'market': CONDITION, 'asset_id': TOKENS[0], 'bids': [{'price': '.32', 'size': '100'}],
        'asks': [{'price': '.36', 'size': '100'}], 'tick_size': '.01', 'min_order_size': '5', 'neg_risk': False, 'hash': 'fixture'})
    calls = []
    venue = object.__new__(OwnerVenue)
    venue.readonly, venue.maker, venue.condition, venue.fields = False, MAKER, CONDITION, {'SIGNATURE_TYPE': '2'}
    def create(**kwargs):
        calls.append(('sign', kwargs))
        return signed
    def post(value):
        calls.append(('post', value))
        return {'ok': True, 'order_id': 'test', 'status': 'live'}
    venue.client = SimpleNamespace(signer=signed.signer, create_limit_order=create, post_order=post,
                                   get_order_book=lambda **kwargs: book)
    return venue, request, signed, book, calls


def test_gtd_post_only_preserves_exact_expiry_and_actual_sdk_book_alias():
    venue, request, signed, _, calls = fixture()
    checkpoints = []
    assert venue.submit(request, checkpoint=lambda: checkpoints.append(True))['ok']
    assert calls == [('sign', request), ('post', signed)] and checkpoints == [True]


@pytest.mark.parametrize('change', [{'side': 'SELL'}, {'post_only': False}, {'order_type': 'GTC'},
                                  {'expiration': 0}, {'taker_amount': 21000000}, {'maker_amount': 15800001},
                                  {'token_id': TOKENS[1]}, {'maker': '0x' + 'd' * 40}, {'signature_type': 3}])
def test_corrupt_signed_order_never_posts(change):
    venue, request, signed, _, calls = fixture()
    venue.client.create_limit_order = lambda **_: replace(signed, **change)
    with pytest.raises(RuntimeError, match='signed_order_binding'):
        venue.submit(request, checkpoint=lambda: None)
    assert calls == []


def test_ask_moves_after_signing_refuses_raw_post():
    venue, request, _, book, calls = fixture()
    changed = book.model_copy(update={'asks': (book.asks[0].model_copy(update={'price': Decimal('.33')}),)})
    venue.client.get_order_book = lambda **kwargs: changed
    with pytest.raises(RuntimeError, match='fresh_ask'):
        venue.submit(request, checkpoint=lambda: None)
    assert len(calls) == 1 and calls[0][0] == 'sign'


def test_pinned_sdk_reward_readers_and_pagination():
    client, http, calls = sdk_fixture()
    try:
        venue = object.__new__(OwnerVenue)
        venue.client = client
        result = venue.accrual('2026-09-21')
        assert result['rows'][0]['earnings'] == '0.123456789012345678'
        assert result['payment_verified'] is False
        assert all(method == 'GET' for method, _ in calls)
    finally:
        http.close()


def test_v1_heartbeat_binds_exact_body_and_rotates_id():
    from weather.market.re1_transport import Re1Heartbeat
    requests = []
    def opener(request, **kwargs):
        requests.append(request)
        class Response:
            status = 200
            def read(self, *args): return json.dumps({'heartbeat_id': 'id-' + str(len(requests))}).encode()
            def close(self): pass
        return Response()
    secret = base64.urlsafe_b64encode(b'fixture-only-secret').decode()
    sender = Re1Heartbeat(signer_address=MAKER, api_key='fixture-key', api_secret=secret,
                          api_passphrase='fixture-pass', opener=opener, clock=lambda: 100)
    assert sender.send() == sender.send() == {'status': 'ok'}
    assert [r.data for r in requests] == [b'{"heartbeat_id":""}', b'{"heartbeat_id":"id-1"}']
    for request in requests:
        material = b'100POST/v1/heartbeats' + request.data
        expected = base64.urlsafe_b64encode(hmac.new(b'fixture-only-secret', material, hashlib.sha256).digest()).decode()
        assert request.get_header('Poly_signature') == expected
        assert request.full_url == 'https://clob.polymarket.com/v1/heartbeats'


def test_rotating_heartbeat_resynchronizes_without_claiming_ack():
    from io import BytesIO
    from urllib.error import HTTPError
    from weather.market.re1_transport import Re1Heartbeat
    calls = []
    def opener(request, **kwargs):
        calls.append(json.loads(request.data))
        if len(calls) == 1:
            raise HTTPError(request.full_url, 400, 'fixture', {},
                            BytesIO(b'{"error_msg":"Invalid Heartbeat ID","heartbeat_id":"expected-id"}'))
        class Reply:
            status = 200
            def read(self, *args): return b'{"heartbeat_id":"new-id"}'
            def close(self): pass
        return Reply()
    sender = Re1Heartbeat(signer_address=MAKER, api_key='fixture', api_secret='Zml4dHVyZQ==',
                          api_passphrase='fixture', opener=opener)
    with pytest.raises(ConnectionError, match='resynchronized'): sender.send()
    assert sender.last_response['error_msg'] == 'Invalid Heartbeat ID'
    assert sender.send() == {'status': 'ok'}
    assert calls == [{'heartbeat_id': ''}, {'heartbeat_id': 'expected-id'}]


def test_collection_sdk_transport_refuses_every_non_get(monkeypatch):
    import httpx
    from eth_account import Account
    from weather.market import re1_transport as transport
    # Public test key, used only to derive its address locally. No real client.
    key = '1' * 64
    client = SimpleNamespace(wallet=MAKER, signer=Account.from_key(key).address, wallet_type='GNOSIS_SAFE')
    names = ('gamma', 'data', 'clob', 'secure_clob', 'relayer', 'rfq', 'combos', 'builder_gateway')
    client._ctx = SimpleNamespace(**{n: SimpleNamespace(_client=SimpleNamespace(event_hooks={'request': []})) for n in names})
    monkeypatch.setattr('polymarket.SecureClient.create', lambda **kwargs: pytest.fail('deployment-capable factory'))
    def bootstrap(**kwargs):
        assert kwargs['validate_credentials'] is True and kwargs['credentials'] is not None
        return client
    monkeypatch.setattr('polymarket.SecureClient._create', bootstrap)
    monkeypatch.setattr(transport, 'fetch_wallet_deployed', lambda *args, **kwargs: True)
    fields = dict(PRIVATE_KEY=key, FUNDER_ADDRESS=MAKER, WALLET_ADDRESS=client.signer, SIGNATURE_TYPE='2',
                  API_KEY='synthetic', API_SECRET='synthetic', API_PASSPHRASE='synthetic')
    assert transport.build_client(fields, readonly=True) is client
    for name in names:
        hook = getattr(client._ctx, name)._client.event_hooks['request'][0]
        hook(httpx.Request('GET', transport.HOST + '/rewards/user'))
        for method, path in [('POST', '/order'), ('DELETE', '/cancel-all'), ('POST', '/orders-scoring')]:
            with pytest.raises(RuntimeError, match='collection_is_read_only'):
                hook(httpx.Request(method, transport.HOST + path))


def test_sdk_request_and_response_times_are_journaled_without_auth():
    client, http, _ = sdk_fixture()
    venue = object.__new__(OwnerVenue)
    venue.client = client
    records = []
    venue.set_journal(SimpleNamespace(record=lambda event, **fields: records.append((event, fields))))
    try:
        venue.accrual('2026-09-21')
        assert records[0][0] == 'sdk_request' and records[1][0] == 'sdk_response'
        assert records[0][1] == {'method': 'GET', 'path': '/rewards/user'}
        assert all('headers' not in row for _, row in records)
    finally:
        http.close()


def test_post_signing_book_is_retained_before_post():
    venue, request, _, _, _ = fixture()
    records = []
    venue.journal = SimpleNamespace(record=lambda event, **fields: records.append((event, fields)))
    assert venue.submit(request, checkpoint=lambda: None)['ok']
    assert records[0][0] == 'signed_order_book'
    assert records[0][1]['book']['token_id'] == request['token_id']
