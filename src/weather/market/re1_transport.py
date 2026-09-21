"""Owner-only RE-1M SDK wiring. No sealed grant is created, altered or consumed.

The official adapter supplies read/cancel normalization, RewardsReaders supplies
scoring validation, and the existing user-stream transport supplies its lifecycle.
Only the separate RE-1M Session may call submit; read-only collection has a
transport-level GET-only guard. No .env is accessed merely by importing this file.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
from pathlib import Path
import re
import subprocess
import time
from urllib.request import Request, urlopen

from weather.market.mm_official_adapter import (
    OfficialPolymarketGlobalAdapter, _plain_sdk_value, fetch_current_positions,
    normalize_official_user_event, require_official_clob_version,
)
from weather.market.mm_official_transport import (
    OfficialHeartbeatSender, fetch_wallet_deployed, build_l2_hmac_signature, _open_json,
)
from weather.market.mm_stage2_rewards import RewardsReaders
from weather.market.mm_user_stream import OfficialUserStreamReader
from weather.market.re1_attended import HOST, SecretGuard, number
from weather.operations.live_path_security import assert_no_ambient_proxy_configuration, validate_regular_nonreparse_file
from weather.paths import REPO_ROOT

ASSETS = ('0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174', '0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB')
RPC = 'https://polygon.drpc.org'


class Re1Heartbeat(OfficialHeartbeatSender):
    """Current documented v1 rotating-ID contract; Stage 1 stays unchanged."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.heartbeat_id = ''
        self.last_response = None

    def send(self):
        assert_no_ambient_proxy_configuration()
        timestamp = int(self._clock())
        path = '/v1/heartbeats'
        body = json.dumps({'heartbeat_id': self.heartbeat_id}, separators=(',', ':'))
        signature = build_l2_hmac_signature(secret=self._api_secret, timestamp=timestamp,
                                           method='POST', path=path, body=body)
        request = Request(HOST + path, data=body.encode(), method='POST', headers={
            'Content-Type': 'application/json', 'Accept': 'application/json',
            'POLY_ADDRESS': self._signer_address, 'POLY_API_KEY': self._api_key,
            'POLY_PASSPHRASE': self._api_passphrase, 'POLY_SIGNATURE': signature,
            'POLY_TIMESTAMP': str(timestamp)})
        response = _open_json(request, opener=self._opener, timeout_seconds=self._timeout_seconds,
                              label='RE-1M v1 heartbeat')
        value = response.get('heartbeat_id')
        if not isinstance(value, str) or not 1 <= len(value) <= 256 or response.get('error_msg'):
            raise RuntimeError('heartbeat_acknowledgment')
        self.heartbeat_id, self.last_response = value, response
        return {'status': 'ok'}


def common_repository_root():
    result = subprocess.run(['git', '-C', str(REPO_ROOT), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                            capture_output=True, text=True, check=True, timeout=10)
    return Path(result.stdout.strip()).parent


def load_owner_credentials(mode):
    if mode not in {'live', 'cancel-only', 'collect-payout'}:
        raise RuntimeError('credentials_forbidden_in_rehearsal')
    # Owner-authorized exception: read this one file in memory; never copy it,
    # export values to os.environ, echo parser errors, or touch WinCred.
    from dotenv import dotenv_values
    path = validate_regular_nonreparse_file(common_repository_root() / '.env')
    values = dotenv_values(path, interpolate=False)
    required = ('PRIVATE_KEY', 'API_KEY', 'API_SECRET', 'API_PASSPHRASE',
                'WALLET_ADDRESS', 'FUNDER_ADDRESS', 'SIGNATURE_TYPE', 'CLOB_HOST', 'CHAIN_ID')
    if any(not values.get('POLYMM_' + key) for key in required):
        raise RuntimeError('credential_fields_missing')
    fields = {key: values['POLYMM_' + key] for key in required}
    guard = SecretGuard(fields[key] for key in ('PRIVATE_KEY', 'API_KEY', 'API_SECRET', 'API_PASSPHRASE'))
    if fields['CLOB_HOST'] != HOST or fields['CHAIN_ID'] != '137' or fields['SIGNATURE_TYPE'] not in {'2', '3'}:
        raise RuntimeError('credential_topology_refused')
    return fields, guard


def json_read(url, *, body=None):
    assert_no_ambient_proxy_configuration()
    request = Request(url, data=None if body is None else json.dumps(body).encode(),
                      headers={'Accept': 'application/json', 'Content-Type': 'application/json'})
    with urlopen(request, timeout=2) as response:
        raw = response.read(2_000_001)
        if response.status != 200 or response.geturl() != url or len(raw) > 2_000_000:
            raise RuntimeError('public_read_refused')
        return json.loads(raw)


def geography():
    value = json_read('https://polymarket.com/api/geoblock')
    if type(value.get('blocked')) is not bool:
        raise RuntimeError('geoblock_unreadable')
    return value


def build_client(fields, *, readonly=False):
    assert_no_ambient_proxy_configuration()
    require_official_clob_version()
    from eth_account import Account
    from polymarket import SecureClient, ApiKeyCreds
    from polymarket._internal.environment import PRODUCTION_CONFIG
    import httpx
    signer = Account.from_key(fields['PRIVATE_KEY']).address
    maker = fields['FUNDER_ADDRESS']
    kind = int(fields['SIGNATURE_TYPE'])
    if signer.lower() != fields['WALLET_ADDRESS'].lower() or signer.lower() == maker.lower():
        raise RuntimeError('signer_funder_identity')
    if PRODUCTION_CONFIG.clob_url != HOST or PRODUCTION_CONFIG.rpc_url != RPC:
        raise RuntimeError('pinned_sdk_endpoint_changed')
    if fetch_wallet_deployed(maker, kind, timeout_seconds=2) is not True:
        raise RuntimeError('existing_wallet_required_no_deployment')
    logger = logging.Logger('re1-sdk-disabled')
    logger.disabled = True
    client = SecureClient.create(private_key=fields['PRIVATE_KEY'], wallet=maker,
        credentials=ApiKeyCreds(key=fields['API_KEY'], secret=fields['API_SECRET'], passphrase=fields['API_PASSPHRASE']),
        logger=logger)
    try:
        if (client.wallet.lower() != maker.lower() or client.signer.lower() != signer.lower() or
                client.wallet_type != {2: 'GNOSIS_SAFE', 3: 'DEPOSIT_WALLET'}[kind]):
            raise RuntimeError('sdk_identity_changed')
        def constrain(request):
            assert_no_ambient_proxy_configuration()
            if str(request.url).startswith(HOST + '/'):
                if readonly and request.method != 'GET':
                    raise RuntimeError('collection_is_read_only')
                if not readonly and (request.method, request.url.path) not in {
                        ('POST', '/order'), ('POST', '/orders-scoring'), ('DELETE', '/order'), ('DELETE', '/cancel-all')} and request.method != 'GET':
                    raise RuntimeError('unapproved_sdk_mutation')
            elif request.method != 'GET':
                raise RuntimeError('non_clob_mutation_forbidden')
        for name in ('gamma', 'data', 'clob', 'secure_clob', 'relayer', 'rfq', 'combos', 'builder_gateway'):
            transport = getattr(client._ctx, name)
            transport._client.timeout = httpx.Timeout(.5)
            transport._client.event_hooks['request'].append(constrain)
        return client
    except BaseException:
        client.close()
        raise


class PairStream(OfficialUserStreamReader):
    """RE-1M exact-pair validation on the existing account-wide WS transport.

The Stage2 reader's grant enforcement is left intact. This separate mission
does not inherit it or override its grant check.
"""
    def __init__(self, *, tokens, guard, **kwargs):
        self.tokens, self.guard = tuple(tokens), guard
        if len(self.tokens) != 2 or len(set(self.tokens)) != 2:
            raise ValueError('exact_pair_required')
        super().__init__(token_id=self.tokens[0], **kwargs)

    def _append(self, event_type, **fields):
        super()._append(event_type, **self.guard.clean(fields))

    def _normalize_event(self, item):
        token = item.get('asset_id')
        if token not in self.tokens:
            raise RuntimeError('unknown_account_event')
        return normalize_official_user_event(item, maker_address=self.maker_address,
                                             condition_id=self.condition_id, token_id=token)

    def _journal_token_scope(self):
        return {'token_ids': list(self.tokens)}


def bounded_rows(paginator):
    rows, cursors = [], set()
    for page in paginator:
        if len(cursors) >= 50 or page.next_cursor is not None and page.next_cursor in cursors:
            raise RuntimeError('pagination_budget')
        cursors.add(page.next_cursor)
        rows.extend(_plain_sdk_value(page.items))
        if len(rows) > 25000:
            raise RuntimeError('row_budget')
    return rows


class OwnerVenue:
    host = HOST
    def __init__(self, client, fields, guard, *, condition=None, tokens=(), directory=None, readonly=False):
        self.client, self.fields, self.guard = client, fields, guard
        self.maker, self.condition, self.tokens = fields['FUNDER_ADDRESS'], condition, tuple(tokens)
        self.readonly, self.stream = readonly, None
        self.adapter = OfficialPolymarketGlobalAdapter(client, maker_address=self.maker, condition_id=condition,
                                                       sdk_version='0.6.0')
        self.readers = RewardsReaders(client, purpose='explicit_post_session_collect' if readonly else 'sealed_stage2_scoring')
        self.sender = Re1Heartbeat(signer_address=client.signer, api_key=fields['API_KEY'],
            api_secret=fields['API_SECRET'], api_passphrase=fields['API_PASSPHRASE'], timeout_seconds=2)
        if directory is not None:
            self.stream = PairStream(tokens=tokens, guard=guard, api_key=fields['API_KEY'], secret=fields['API_SECRET'],
                passphrase=fields['API_PASSPHRASE'], maker_address=self.maker, condition_id=condition,
                journal_path=Path(directory) / 'user-stream.jsonl', connect_timeout_seconds=2)
        self.event_count = 0

    def set_journal(self, journal):
        self.journal = journal
        def sent(request):
            # Exact send time, with no inspection of auth headers or signed
            # request bodies. The controller records the unsigned order.
            journal.record('sdk_request', method=request.method, path=request.url.path)
        def retain(response):
            raw = response.read()
            if len(raw) > 2_000_000:
                raise RuntimeError('sdk_response_budget')
            journal.record('sdk_response', method=response.request.method,
                           path=response.url.path, status=response.status_code,
                           response=json.loads(raw))
        self.client._ctx.secure_clob._client.event_hooks['request'].append(sent)
        self.client._ctx.secure_clob._client.event_hooks['response'].append(retain)

    def start(self):
        self.stream.start()
        end = time.monotonic() + 20
        while time.monotonic() < end:
            evidence = self.stream.bootstrap_evidence()
            if evidence['transport_active'] and evidence['server_pong_observed'] and evidence['account_wide_subscription_sent']:
                return
            if self.stream.health()['state'] == 'FAILED': break
            time.sleep(.1)
        raise RuntimeError('user_stream_readiness')

    def events(self):
        evidence = self.stream.bootstrap_evidence()
        if not evidence['transport_active'] or not evidence['server_pong_observed']:
            raise RuntimeError('user_stream_failed')
        events = self.stream.events()
        new = events[self.event_count:]
        self.event_count = len(events)
        return new

    def open_orders(self): return self.adapter.open_orders()
    def order(self, oid): return self.adapter.get_order(oid)
    def trades(self):
        return bounded_rows(self.client.list_account_trades(market=self.condition))
    def positions(self):
        evidence = fetch_current_positions(self.maker, self.condition, timeout_seconds=2)
        if evidence.get('status') != 'OBSERVED': raise RuntimeError('positions_unreadable')
        return evidence['rows']
    def geography(self): return geography()
    def heartbeat(self):
        if self.readonly: raise RuntimeError('read_only')
        response = self.sender.send()
        if hasattr(self, 'journal'):
            self.journal.record('heartbeat_v1_acknowledgment', response=self.sender.last_response)
        return response
    def scoring(self, ids): return self.readers.scoring(ids)
    def accrual(self, day):
        return {'day': day, 'rows': bounded_rows(self.client.list_user_earnings_for_day(date=day)),
                'market_configurations': bounded_rows(self.client.list_user_earnings_and_markets_config(date=day)),
                'total_earnings': _plain_sdk_value(self.client.get_total_earnings_for_user_for_day(date=day)),
                'percentages': _plain_sdk_value(self.client.get_reward_percentages()), 'payment_verified': False}
    def balances(self):
        assets = {}
        for i, asset in enumerate(ASSETS):
            result = json_read(RPC, body={'jsonrpc': '2.0', 'id': i + 1, 'method': 'eth_call',
                'params': [{'to': asset, 'data': '0x70a08231' + self.maker[2:].lower().rjust(64, '0')}, 'latest']})
            if result.get('id') != i + 1 or 'error' in result or re.fullmatch(r'0x[0-9a-fA-F]{64}', result.get('result', '')) is None:
                raise RuntimeError('asset_balance_unreadable')
            assets[asset] = str(Decimal(int(result['result'], 16)) / 1_000_000)
        collateral = self.adapter.refresh_balance_allowance()
        if not collateral.get('allowances') or max(number(v) for v in collateral['allowances'].values()) < 19600000:
            raise RuntimeError('collateral_allowance')
        return {'assets': assets, 'available_collateral': str(number(collateral['balance']) / 1_000_000),
                'collateral_evidence': collateral}

    def submit(self, request, *, checkpoint):
        if self.readonly: raise RuntimeError('read_only')
        signed = self.client.create_limit_order(**request)
        expected_signer = self.maker if self.fields['SIGNATURE_TYPE'] == '3' else self.client.signer
        if (signed.maker.lower() != self.maker.lower() or signed.signer.lower() != expected_signer.lower() or
                signed.signature_type != int(self.fields['SIGNATURE_TYPE']) or signed.token_id != request['token_id'] or
                signed.side != 'BUY' or signed.order_type != 'GTD' or signed.post_only is not True or
                signed.expiration != request['expiration'] or signed.taker_amount != 20000000 or
                signed.maker_amount != int(number(request['price']) * 20000000)):
            raise RuntimeError('signed_order_binding')
        checkpoint()
        # Signing can fetch SDK metadata. Re-read the actual token ask after
        # signing so those reads cannot make the submit-time touch stale.
        book = _plain_sdk_value(self.client.get_order_book(token_id=request['token_id']))
        if hasattr(self, 'journal'):
            self.journal.record('signed_order_book', book=book)
        if (book['token_id'] != request['token_id'] or book['market'] != self.condition or
                not book['asks'] or number(request['price']) >= min(number(r['price']) for r in book['asks'])):
            raise RuntimeError('signed_order_fresh_ask')
        # No place_limit_order/allowance recovery or retry: one raw post only.
        return _plain_sdk_value(self.client.post_order(signed))
    def cancel(self, oid):
        if self.readonly: raise RuntimeError('read_only')
        return self.adapter.cancel_order(oid)
    def cancel_all(self):
        if self.readonly: raise RuntimeError('read_only')
        return _plain_sdk_value(self.client.cancel_all())
    def close(self):
        try:
            if self.stream is not None: self.stream.stop()
        finally:
            self.client.close()
