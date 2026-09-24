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


def test_undecodable_order_read_is_transient_and_other_errors_are_not():
    class UnexpectedResponseError(Exception):
        pass
    def lagging(order_id): raise UnexpectedResponseError('not yet readable')
    def broken(order_id): raise ValueError('malformed')
    with pytest.raises(TimeoutError, match='order_read_undecodable'):
        OwnerVenue.order(SimpleNamespace(adapter=SimpleNamespace(get_order=lagging)), 'x')
    with pytest.raises(ValueError):
        OwnerVenue.order(SimpleNamespace(adapter=SimpleNamespace(get_order=broken)), 'x')
    assert OwnerVenue.order(SimpleNamespace(adapter=SimpleNamespace(get_order=lambda order_id: {'id': order_id})), 'x') == {'id': 'x'}


@pytest.fixture(autouse=True)
def clear_user_agent_cache():
    from weather.market.re1_transport import _user_agent
    _user_agent.cache_clear()
    yield
    _user_agent.cache_clear()


def reward_payload(rows=None):
    rows = [{'condition_id': CONDITION, 'rewards_min_size': 20, 'rewards_max_spread': 3}] if rows is None else rows
    return dict(data=rows, count=len(rows), next_cursor='LTE=', limit=500)


@pytest.fixture
def accrual_venue(monkeypatch):
    from weather.market import re1_transport as transport
    calls = []
    payload = reward_payload()
    def read(url, **kwargs):
        calls.append(url)
        return payload
    monkeypatch.setattr(transport, 'json_read', read)
    def universe(**kwargs): pytest.fail('universe configuration paginator called')
    venue = object.__new__(OwnerVenue)
    venue.condition = CONDITION
    venue.client = SimpleNamespace(
        list_user_earnings_for_day=lambda **kwargs: [SimpleNamespace(items=[{'earnings': '1.25'}], next_cursor=None)],
        list_user_earnings_and_markets_config=universe,
        get_total_earnings_for_user_for_day=lambda **kwargs: [{'earnings': '1.25'}],
        get_reward_percentages=lambda: {CONDITION: '0.5'})
    return venue, payload, calls


@pytest.mark.parametrize('empty', [False, True])
def test_accrual_reads_selected_condition_once(accrual_venue, empty):
    venue, payload, calls = accrual_venue
    if empty: payload.update(data=[], count=0)
    result = venue.accrual('2026-09-22')
    assert calls == ['https://clob.polymarket.com/rewards/markets/' + CONDITION]
    assert result == dict(day='2026-09-22', rows=[{'earnings': '1.25'}],
        market_configurations=payload['data'], total_earnings=[{'earnings': '1.25'}],
        percentages={CONDITION: '0.5'}, payment_verified=False)


@pytest.mark.parametrize('change', [
    {'data': [{}, {}], 'count': 2}, {'data': {}}, {'next_cursor': 'more'}, {'count': 0},
    {'limit': 0}, {'limit': 501}, {'limit': True}, {'limit': '500'},
])
def test_accrual_refuses_incomplete_condition_configuration(accrual_venue, change):
    venue, payload, _ = accrual_venue
    payload.update(change)
    with pytest.raises(RuntimeError, match='^condition_config_unreadable$'):
        venue.accrual('2026-09-22')


def test_accrual_requires_condition_before_any_read(accrual_venue):
    venue, _, calls = accrual_venue
    venue.condition, venue.client = None, None
    with pytest.raises(RuntimeError, match='^condition_required$'):
        venue.accrual('2026-09-22')
    assert calls == []


@pytest.mark.parametrize('url,body', [
    ('https://polymarket.com/api/geoblock', None),
    ('https://polygon.drpc.org', {'jsonrpc': '2.0', 'id': 1, 'method': 'eth_blockNumber', 'params': []}),
])
def test_json_read_request_identifies_attended_commit(monkeypatch, url, body):
    from io import BytesIO
    from weather.market import re1_transport as transport
    monkeypatch.setattr('weather.market.re1_owner_checks.code_identity', lambda: '123456789' + 'a' * 31)
    monkeypatch.setattr(transport, 'assert_no_ambient_proxy_configuration', lambda: None)
    requests = []
    class Reply(BytesIO):
        status = 200
        def geturl(self): return url
    def opened(request, *, timeout):
        requests.append(request)
        assert request.full_url == url and timeout == 2
        assert request.get_method() == ('GET' if body is None else 'POST')
        assert request.data == (None if body is None else json.dumps(body).encode())
        assert dict(request.header_items()) == {
            'Accept': 'application/json', 'Content-type': 'application/json',
            'User-agent': 'weather-re1-attended/123456789'}
        return Reply(b'{"ok": true}')
    monkeypatch.setattr(transport, 'urlopen', opened)
    assert transport.json_read(url, body=body) == {'ok': True}
    assert len(requests) == 1


def test_ten_public_reads_compute_identity_once_and_keep_initial_header(monkeypatch):
    from io import BytesIO
    from weather.market import re1_transport as transport
    calls, requests = [], []
    url = transport.GEOBLOCK
    def identity():
        calls.append(True)
        if len(calls) > 1: raise RuntimeError('preflight_requires_clean_tip')
        return '123456789' + 'a' * 31
    class Reply(BytesIO):
        status = 200
        def geturl(self): return url
    def opened(request, **kwargs):
        requests.append(request)
        return Reply(b'{}')
    monkeypatch.setattr('weather.market.re1_owner_checks.code_identity', identity)
    monkeypatch.setattr(transport, 'assert_no_ambient_proxy_configuration', lambda: None)
    monkeypatch.setattr(transport, 'urlopen', opened)
    for _ in range(10): assert transport.json_read(url) == {}
    assert len(calls) == 1 and len(requests) == 10
    assert {r.get_header('User-agent') for r in requests} == {'weather-re1-attended/123456789'}


def test_first_public_read_still_requires_clean_tip(monkeypatch):
    from weather.market import re1_transport as transport
    def dirty(): raise RuntimeError('preflight_requires_clean_tip')
    monkeypatch.setattr('weather.market.re1_owner_checks.code_identity', dirty)
    monkeypatch.setattr(transport, 'assert_no_ambient_proxy_configuration', lambda: None)
    monkeypatch.setattr(transport, 'urlopen', lambda *a, **kw: pytest.fail('request before clean identity'))
    with pytest.raises(RuntimeError, match='preflight_requires_clean_tip'):
        transport.json_read(transport.GEOBLOCK)


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


@pytest.mark.parametrize('size', [30, 50, 75])
@pytest.mark.parametrize('corrupt', [False, True])
def test_sized_signed_order_binds_both_amounts(size, corrupt):
    venue, request, signed, _, calls = fixture()
    venue.size = Decimal(size)
    request['size'] = str(size)
    sized = replace(signed, taker_amount=size * 1_000_000 + int(corrupt),
                    maker_amount=int(Decimal(request['price']) * size * 1_000_000))
    venue.client.create_limit_order = lambda **_: sized
    if corrupt:
        with pytest.raises(RuntimeError, match='signed_order_binding'):
            venue.submit(request, checkpoint=lambda: None)
        assert calls == []
    else:
        assert venue.submit(request, checkpoint=lambda: None)['ok']
        assert calls == [('post', sized)]


def test_ask_moves_after_signing_refuses_raw_post():
    venue, request, _, book, calls = fixture()
    changed = book.model_copy(update={'asks': (book.asks[0].model_copy(update={'price': Decimal('.33')}),)})
    venue.client.get_order_book = lambda **kwargs: changed
    with pytest.raises(RuntimeError, match='fresh_ask'):
        venue.submit(request, checkpoint=lambda: None)
    assert len(calls) == 1 and calls[0][0] == 'sign'


def test_pinned_sdk_reward_readers_and_pagination(monkeypatch):
    monkeypatch.setattr('weather.market.re1_transport.json_read', lambda *a, **kw: reward_payload())
    client, http, calls = sdk_fixture()
    try:
        venue = object.__new__(OwnerVenue)
        venue.client = client
        venue.condition = CONDITION
        result = venue.accrual('2026-09-21')
        assert result['rows'][0]['earnings'] == '0.123456789012345678'
        assert result['payment_verified'] is False
        assert all(method == 'GET' for method, _ in calls)
    finally:
        http.close()


def test_v1_heartbeat_binds_exact_body_and_rotates_id(monkeypatch):
    monkeypatch.setattr('weather.market.re1_owner_checks.code_identity', lambda: '123456789' + 'a' * 31)
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
        # Cloudflare answers 403 to urllib's default agent (owner preflight 2026-09-23T01:21Z).
        assert request.get_header('User-agent') == 'weather-re1-attended/123456789'


def test_rotating_heartbeat_resynchronizes_without_claiming_ack(monkeypatch):
    monkeypatch.setattr('weather.market.re1_owner_checks.code_identity', lambda: '123456789' + 'a' * 31)
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
    client = SimpleNamespace(wallet=MAKER, signer=Account.from_key(key).address, wallet_type='GNOSIS_SAFE',
                             fetch_api_keys=lambda: ('synthetic',), close=lambda: None)
    names = ('gamma', 'data', 'clob', 'secure_clob', 'relayer', 'rfq', 'combos', 'builder_gateway')
    client._ctx = SimpleNamespace(**{n: SimpleNamespace(_client=SimpleNamespace(event_hooks={'request': []})) for n in names})
    monkeypatch.setattr('polymarket.SecureClient.create', lambda **kwargs: pytest.fail('deployment-capable factory'))
    def bootstrap(**kwargs):
        assert kwargs['validate_credentials'] is False and kwargs['credentials'] is not None
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
    client.fetch_api_keys = lambda: ()
    with pytest.raises(RuntimeError, match='supplied_credentials_not_active'):
        transport.build_client(fields, readonly=True)


def test_pinned_bootstrap_cannot_create_or_derive_credentials(monkeypatch):
    from polymarket import ApiKeyCreds
    from polymarket.clients import secure
    credentials = ApiKeyCreds(key='fixture', secret='fixture', passphrase='fixture')
    def forbidden(*args, **kwargs): pytest.fail('credential mutation or SDK fallback validation')
    monkeypatch.setattr(secure, '_credentials_are_active_sync', forbidden)
    monkeypatch.setattr(secure, 'sign_api_key_auth', forbidden)
    monkeypatch.setattr(secure._auth_actions, 'create_or_derive_api_key_sync', forbidden)
    assert secure._bootstrap_credentials_sync(config=None, signer=None, clob=None,
        provided=credentials, nonce=0, validate=False, logger=None) is credentials


def test_sdk_request_and_response_times_are_journaled_without_auth(monkeypatch):
    monkeypatch.setattr('weather.market.re1_transport.json_read', lambda *a, **kw: reward_payload())
    client, http, _ = sdk_fixture()
    venue = object.__new__(OwnerVenue)
    venue.client = client
    venue.condition = CONDITION
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
