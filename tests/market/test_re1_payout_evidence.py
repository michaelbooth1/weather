"""Closed SDK/RPC transports. A supplied distribution fixture is not a venue endpoint."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from types import SimpleNamespace

import pytest

pytest.importorskip('polymarket')

from tests.market.test_re1_sdk_shapes import sdk_earnings_models, MAKER, CONDITION
from weather.market import re1_payout_evidence as collector
from weather.market.mm_exchange_reports import INCENTIVE_CASH_ASSET, reconcile_incentive_payments
from weather.market.mm_stage2_hold import utc
from weather.market.re1_attended import SecretGuard
from weather.market.re1_evidence import payout_verdict
from weather.market.re1_transport import OwnerVenue

START = utc('2026-09-01T00:00:00Z')
NOW = START + timedelta(days=3, hours=1)
TX = '0x' + '1' * 64


def prediction():
    return dict(P_many=2, mode='live', evidence_complete=True, cleanup_ok=True, scoring_seen=True,
        reward_terms_changed=False, visible_two_sided_minutes=200, condition_id=CONDITION,
        scope={'maker_address': MAKER}, reward_day='2026-09-01')


def sdk_venue(*, fail=None, guard=None):
    import httpx
    from polymarket.clients.secure import SecureClient, _CREATE_TOKEN
    from polymarket.clients._transport import SyncTransport
    rows, totals, config = sdk_earnings_models()
    payloads = {'/rewards/user': dict(data=[r.model_dump(mode='json') for r in rows], next_cursor='LTE='),
        '/rewards/user/total': [r.model_dump(mode='json') for r in totals],
        '/rewards/user/markets': dict(data=[config.model_dump(mode='json')], next_cursor='LTE=', total_count=1),
        '/activity': [dict(proxyWallet=MAKER, timestamp=int((START + timedelta(days=2)).timestamp()),
            transactionHash=TX, type='REWARD', usdcSize=1.25)]}
    calls = []
    def handle(request):
        assert request.method == 'GET', 'venue write attempted'
        assert not any(k.lower().startswith('poly_') for k in request.headers)
        if request.url.path == fail:
            raise TimeoutError('synthetic read failure')
        raw = json.dumps(payloads[request.url.path], indent=2).encode() + b'\n'
        calls.append((request, raw))
        return httpx.Response(200, content=raw)
    http = httpx.Client(base_url=collector.HOST, transport=httpx.MockTransport(handle))
    data_http = httpx.Client(base_url='https://data-api.polymarket.com', transport=httpx.MockTransport(handle))
    ctx = SimpleNamespace(secure_clob=SyncTransport(base_url=collector.HOST, client=http),
        data=SyncTransport(base_url='https://data-api.polymarket.com', client=data_http), wallet_type='GNOSIS_SAFE')
    sdk = SecureClient(ctx=ctx, _create_token=_CREATE_TOKEN)
    class ReadsOnly:
        _ctx = ctx
        def __getattr__(self, name):
            assert name in {'list_user_earnings_for_day', 'list_user_earnings_and_markets_config',
                'get_total_earnings_for_user_for_day', 'list_activity'}, 'non-read SDK method: ' + name
            return getattr(sdk, name)
        def close(self):
            http.close()
            data_http.close()
    venue = object.__new__(OwnerVenue)
    venue.client, venue.maker, venue.guard = ReadsOnly(), MAKER, guard or SecretGuard()
    venue.readonly, venue.preflight, venue.journal_failed = True, False, False
    return venue, calls, payloads


class RpcFixture:
    """A monotone finalized chain, hex RPC envelopes and exact Transfer logs."""
    def __init__(self, *, missing=None, cap=None, malformed=None, tip=2600):
        self.missing, self.cap, self.malformed, self.tip = missing, cap, malformed, tip
        self.calls = []
        self.genesis = START - timedelta(seconds=100)
    def block(self, height):
        return dict(number=hex(height), timestamp=hex(int(self.genesis.timestamp()) + height * 100),
                    hash='0x' + format(height + 100, '064x'))
    def __call__(self, request, timeout):
        assert request.full_url == collector.RPC and request.method == 'POST' and timeout == 10
        body = json.loads(request.data)
        method, params = body['method'], body['params']
        assert method in {'eth_chainId', 'eth_getBlockByNumber', 'eth_getLogs'}
        response = dict(jsonrpc='2.0', id=body['id'])
        if method == 'eth_chainId': response['result'] = '0x89'
        elif method == 'eth_getBlockByNumber':
            response['result'] = self.block(self.tip if params[0] == 'finalized' else int(params[0], 16))
        else:
            query = params[0]
            assert query['topics'] == [collector.TRANSFER, None, '0x' + MAKER[2:].rjust(64, '0')]
            assert set(query['address']) == set(collector.ASSET_MARKERS)
            first, last = int(query['fromBlock'], 16), int(query['toBlock'], 16)
            if self.missing is not None and first <= self.missing <= last:
                self.calls.append((request.data, None))
                raise TimeoutError('one chunk missing')
            if self.cap and last - first + 1 > self.cap:
                response['error'] = dict(code=-32005, message='block range limit')
            else:
                logs = []
                for height, asset, tx in [(1729, INCENTIVE_CASH_ASSET['asset_address'], TX),
                        (1730, collector.ASSETS[0].lower(), '0x' + '2' * 64)]:
                    if first <= height <= last:
                        logs.append(dict(address=asset, blockNumber=hex(height), blockHash=self.block(height)['hash'],
                            topics=[collector.TRANSFER, '0x' + '0' * 24 + 'c' * 40, query['topics'][2]],
                            transactionHash=tx, logIndex='0x0', removed=False, data='0x' + format(1250000, '064x')))
                if self.malformed and logs: self.malformed(logs)
                response['result'] = logs
        raw = json.dumps(response, indent=1).encode() + b'\n'
        self.calls.append((request.data, raw))
        class Reply:
            status = 200
            def geturl(self): return collector.RPC
            def read(self, size): return raw[:size]
            def __enter__(self): return self
            def __exit__(self, *args): pass
        return Reply()


def collect(*, rpc=None, fail=None, now=NOW):
    venue, calls, _ = sdk_venue(fail=fail)
    try:
        result = collector.collect_evidence(venue, prediction(), clock=lambda: now, opener=rpc or RpcFixture())
        assert all(not h for http in (venue.client._ctx.data._client, venue.client._ctx.secure_clob._client)
                   for h in http.event_hooks.values()), 'hooks were not restored'
        return result, calls
    finally:
        venue.client.close()


def with_explicit_test_distribution(evidence):
    """Conditional positive control ONLY: supply the missing authoritative link.

    No SDK/public endpoint supplies these fields. This is intentionally kept in
    tests, never a production fallback from an activity row or a wallet credit.
    """
    result = deepcopy(evidence)
    accrual = result['accruals'][0]
    result['sources']['distributions'].update(status='OBSERVED', complete=True,
        pagination_complete=True, payout_cycle_complete=True, coverage_through_utc=result['scope']['cash_end_utc'])
    result['distributions'] = [dict(maker_address=MAKER, cash_asset=dict(INCENTIVE_CASH_ASSET),
        observed_at_utc=NOW.isoformat(), source_record_sha256='d' * 64, amount='1.250000',
        distribution_id='synthetic-explicit-period-link', accrual_id=accrual['accrual_id'],
        programme='liquidity_reward', condition_id=CONDITION, status='PAID', credit_id=f'137:{TX}:0')]
    return result


@pytest.mark.parametrize('missing', [None, 2300])
def test_real_reconciler_round_trip_with_explicit_distribution_control(missing):
    result, _ = collect(rpc=RpcFixture(missing=missing))
    # The actual output must refuse: neither activity nor credit establishes
    # the day-to-payment link. The positive control explicitly supplies it.
    assert result['sources']['distributions']['status'] == 'UNSUPPORTED'
    assert not reconcile_incentive_payments(result)['valid']
    result = with_explicit_test_distribution(result)
    reconciled = reconcile_incentive_payments(result)
    verdict = payout_verdict(prediction(), {'rows': result['sdk_earnings']['rows']}, result)
    assert reconciled['valid'], reconciled
    if missing is None:
        assert reconciled['complete'] and reconciled['actual_liquidity_reward_usdc'] == 1.25, reconciled
        assert verdict['paid'] == '1.25' and verdict['k'] == '0.625' and verdict['verdict'] == 'PAID_AS_MODELLED'
    else:
        assert not reconciled['complete']
        assert verdict['paid'] is None and verdict['k'] is None and verdict['verdict'] == 'INCONCLUSIVE'


def test_actual_sdk_and_rpc_sources_remain_unlinked_and_hash_real_bytes():
    rpc = RpcFixture(cap=250)
    result, calls = collect(rpc=rpc)
    accrual, distributions, wallet = (result['sources'][s] for s in ('accruals', 'distributions', 'wallet_credits'))
    assert accrual['complete'] and accrual['pagination_complete']
    assert not distributions['complete'] and distributions['status'] == 'UNSUPPORTED'
    assert distributions['pagination_complete'] and result['distribution_candidates'][0]['type'] == 'REWARD'
    assert wallet['complete'] and wallet['pagination_complete'], wallet
    assert wallet['block_bounds']['first_block'] == 1 and wallet['block_bounds']['last_block'] == 2592
    assert len(wallet['chunks']) > 3 and all(r['complete'] for r in wallet['chunks'])
    assert len(result['wallet_credits']) == 1
    assert all(len(r['wallet_credits']) == 1 for r in result['asset_observations'].values())
    journal = result['wire_journal']
    assert [r['sha256'] for r in journal if r['event'] == 'sdk_response'] == [hashlib.sha256(raw).hexdigest() for _, raw in calls]
    expected = [hashlib.sha256(req.method.encode() + b'\n' + req.url.raw_path + b'\n' + req.content).hexdigest() for req, _ in calls]
    assert [r['sha256'] for r in journal if r['event'] == 'wire_request'] == expected
    assert [r['sha256'] for r in journal if r['event'] == 'rpc_request'] == [hashlib.sha256(req).hexdigest() for req, _ in rpc.calls]
    assert [r['sha256'] for r in journal if r['event'] == 'rpc_response'] == [hashlib.sha256(raw).hexdigest() for _, raw in rpc.calls]
    activity_req = next(req for req, _ in calls if req.url.path == '/activity')
    assert activity_req.url.params['user'] == MAKER
    assert activity_req.url.params['type'] == 'REWARD,MAKER_REBATE'
    assert 'market' not in activity_req.url.params
    assert activity_req.url.params['end'] == str(int((START + timedelta(days=3)).timestamp()) - 1)


@pytest.mark.parametrize('mutate', [lambda logs: logs[0].update(removed=True),
    lambda logs: logs[0].update(blockHash='0x' + 'f' * 64),
    lambda logs: logs[0].update(data='0x1'), lambda logs: logs.append(deepcopy(logs[0])),
    lambda logs: logs[0]['topics'].__setitem__(2, '0x' + '0' * 64)])
def test_malformed_or_ambiguous_log_never_proves_coverage(mutate):
    result, _ = collect(rpc=RpcFixture(malformed=mutate))
    assert not result['sources']['wallet_credits']['complete']
    assert not result['sources']['wallet_credits']['pagination_complete']
    assert payout_verdict(prediction(), {'rows': []}, with_explicit_test_distribution(result))['paid'] is None


def test_future_cash_window_and_unfinalized_tail_are_not_claimed_complete():
    result, _ = collect(now=START + timedelta(days=1, hours=1), rpc=RpcFixture(tip=900))
    wallet = result['sources']['wallet_credits']
    assert not wallet['complete'] and not wallet['payout_cycle_complete']
    assert utc(wallet['coverage_through_utc']) <= utc(wallet['observed_at_utc'])
    assert not reconcile_incentive_payments(result)['valid']
    assert payout_verdict(prediction(), {'rows': []}, result)['paid'] is None


@pytest.mark.parametrize('tip', [2700, 2500])
def test_future_block_or_insufficient_finality_refuses_cash_completeness(tip):
    result, _ = collect(rpc=RpcFixture(tip=tip))
    assert not result['sources']['wallet_credits']['complete']
    assert payout_verdict(prediction(), {'rows': []}, with_explicit_test_distribution(result))['paid'] is None


@pytest.mark.parametrize('case', ['missing_total', 'wrong_maker', 'wrong_day', 'total_mismatch', 'duplicate', 'precision'])
def test_sdk_evidence_scope_omission_and_precision_fail_closed(case):
    venue, _, payloads = sdk_venue()
    if case == 'missing_total': payloads['/rewards/user/total'].pop()
    elif case == 'wrong_maker': payloads['/rewards/user']['data'][0]['maker_address'] = '0x' + 'e' * 40
    elif case == 'wrong_day': payloads['/rewards/user']['data'][0]['date'] = '2026-08-31T00:00:00Z'
    elif case == 'total_mismatch': payloads['/rewards/user/total'][0]['earnings'] = '9'
    elif case == 'duplicate': payloads['/rewards/user']['data'].append(deepcopy(payloads['/rewards/user']['data'][0]))
    else:
        payloads['/rewards/user']['data'][1]['earnings'] = '1.250000001'
        payloads['/rewards/user/total'][1]['earnings'] = '1.250000001'
        payloads['/rewards/user/markets']['data'][0]['earnings'][1]['earnings'] = '1.250000001'
    try:
        result = collector.collect_evidence(venue, prediction(), clock=lambda: NOW, opener=RpcFixture())
    finally:
        venue.client.close()
    if case == 'precision':
        # Preserve the venue's sub-micro-unit estimate. Never round it into
        # authoritative native cash just to satisfy the existing schema.
        assert result['accruals'][0]['amount'] == '1.250000001'
        assert not reconcile_incentive_payments(with_explicit_test_distribution(result))['valid']
    else:
        assert not result['sources']['accruals']['complete']
    assert payout_verdict(prediction(), {'rows': []}, result)['paid'] is None


def test_empty_earnings_require_explicit_zero_totals_for_both_assets():
    venue, _, payloads = sdk_venue()
    payloads['/rewards/user']['data'] = []
    payloads['/rewards/user/markets']['data'] = []
    for row in payloads['/rewards/user/total']: row['earnings'] = '0'
    try:
        result = collector.collect_evidence(venue, prediction(), clock=lambda: NOW, opener=RpcFixture())
    finally:
        venue.client.close()
    assert result['sources']['accruals']['complete']
    assert all(a['accruals'][0]['status'] == 'COMPLETED_ZERO' for a in result['asset_observations'].values())
    assert payout_verdict(prediction(), {'rows': []}, result)['verdict'] == 'INCONCLUSIVE'


def test_paginator_requires_terminal_page_and_refuses_repeated_cursor():
    from polymarket.pagination import Page
    journal = collector.ReadJournal(SecretGuard(), lambda: NOW)
    for pages in ([], [Page(items=(), has_more=True, next_cursor='same')] * 2,
                  [Page(items=(), has_more=True, next_cursor=None)]):
        with pytest.raises(ValueError, match='pagination'):
            collector.read_pages(pages, journal, '/rewards/user')


@pytest.mark.parametrize('path', ['/rewards/user', '/rewards/user/markets', '/rewards/user/total', '/activity'])
def test_read_failure_is_retained_and_never_zero_payment(path):
    result, _ = collect(fail=path)
    assert result['sources']['distributions']['status'] != 'OBSERVED'
    assert payout_verdict(prediction(), {'rows': []}, result)['paid'] is None
    assert any(s.get('failure_type') == 'TimeoutError' for s in result['sources'].values())


def test_credential_mode_is_readonly_and_exclusive_file_is_in_fixed_campaign(tmp_path, monkeypatch, capsys):
    root, session = tmp_path / 'campaign', tmp_path / 'campaign/session-1'
    session.mkdir(parents=True)
    path = session / 'prediction.json'
    path.write_text('{}')
    venue, _, _ = sdk_venue()
    monkeypatch.setattr(collector, 'campaign_root', lambda: root)
    monkeypatch.setattr(collector, 'load_prediction', lambda *a, **kw: prediction())
    monkeypatch.setattr(collector, 'now_utc', lambda: NOW)
    def load(mode):
        assert mode == 'collect-payout'
        return {'FUNDER_ADDRESS': MAKER}, venue.guard
    def client(fields, *, readonly):
        assert readonly is True
        return venue.client
    monkeypatch.setattr('weather.market.re1_transport.load_owner_credentials', load)
    monkeypatch.setattr('weather.market.re1_transport.build_client', client)
    monkeypatch.setattr('weather.market.re1_transport.OwnerVenue', lambda *a, **kw: venue)
    original = collector.collect_evidence
    monkeypatch.setattr(collector, 'collect_evidence', lambda v, p: original(v, p, clock=lambda: NOW, opener=RpcFixture()))
    assert collector.run_collect_evidence(SimpleNamespace(prediction=path)) == 2
    files = list(session.glob('payout-evidence-*.json'))
    assert len(files) == 1 and len(list(session.iterdir())) == 2
    text = capsys.readouterr().out
    assert 'INCONCLUSIVE' in text and hashlib.sha256(files[0].read_bytes()).hexdigest() in text
    assert json.loads(files[0].read_bytes())['sources']['distributions']['status'] == 'UNSUPPORTED'


def test_prediction_refusal_precedes_credentials(tmp_path, monkeypatch):
    root = tmp_path / 'campaign'
    root.mkdir()
    monkeypatch.setattr(collector, 'campaign_root', lambda: root)
    monkeypatch.setattr('weather.market.re1_transport.load_owner_credentials', lambda *_: pytest.fail('credentials read'))
    with pytest.raises(ValueError, match='prediction_outside_campaign'):
        collector.run_collect_evidence(SimpleNamespace(prediction=tmp_path / 'prediction.json'))


def test_guard_prevents_sdk_secret_output_and_no_nonread_endpoints():
    import httpx
    journal = collector.ReadJournal(SecretGuard(['synthetic-loaded-secret']), lambda: NOW)
    with pytest.raises(RuntimeError, match='secret_output_refused'):
        journal.record('sdk_response', response={'unexpected': 'synthetic-loaded-secret'})
    for method, path in [('POST', '/order'), ('DELETE', '/cancel-all'), ('POST', '/v1/heartbeats'), ('GET', '/auth/api-keys')]:
        with pytest.raises(ValueError, match='read_only_endpoint'):
            journal.request(httpx.Request(method, collector.HOST + path))


def test_collect_payout_prints_hash_of_exact_input_bytes(tmp_path, monkeypatch, capsys):
    from weather.market import re1_attended_cli as cli
    path = tmp_path / 'payment.json'
    raw = b'{ "incomplete": true }\n'
    path.write_bytes(raw)
    guard = SecretGuard()
    monkeypatch.setattr(cli, 'load_prediction', lambda *a, **kw: prediction())
    monkeypatch.setattr('weather.market.re1_transport.load_owner_credentials', lambda *_: ({'FUNDER_ADDRESS': MAKER}, guard))
    monkeypatch.setattr('weather.market.re1_transport.build_client', lambda *a, **kw: None)
    monkeypatch.setattr('weather.market.re1_transport.OwnerVenue', lambda *a, **kw: SimpleNamespace(
        accrual=lambda day: {'rows': []}, balances=lambda: {}, close=lambda: None))
    assert cli.run_collect(SimpleNamespace(prediction=tmp_path / 'prediction.json', payment_evidence=path)) == 0
    printed = capsys.readouterr().out
    assert hashlib.sha256(raw).hexdigest() in printed and 'payment_evidence_path' in printed
    result = json.loads(next(tmp_path.glob('payout-*.json')).read_bytes())
    assert result['payment_evidence_sha256'] == hashlib.sha256(raw).hexdigest() and result['paid'] is None
