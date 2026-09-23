"""SDK models and closed RPC transports exercise the reviewed RE-1 producer rule."""
from copy import deepcopy
from ast import literal_eval
from datetime import timedelta
from decimal import Decimal
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
CONFIG_PATH = '/rewards/markets/' + CONDITION


def prediction():
    return dict(P_many=2, mode='live', evidence_complete=True, cleanup_ok=True, scoring_seen=True,
        reward_terms_changed=False, visible_two_sided_minutes=200, condition_id=CONDITION,
        adequacy=dict(elapsed_minutes=200, public_book_minutes=200,
                      size_spread_unchanged=True, two_sided_scoring_minutes=200),
        scope={'maker_address': MAKER}, reward_day='2026-09-01')


def sdk_venue(*, fail=None, guard=None):
    from io import BytesIO
    import httpx
    from weather.market import re1_transport as transport
    from polymarket.clients.secure import SecureClient, _CREATE_TOKEN
    from polymarket.clients._transport import SyncTransport
    rows, totals, _ = sdk_earnings_models()
    payloads = {'/rewards/user': dict(data=[r.model_dump(mode='json') for r in rows], next_cursor='LTE='),
        '/rewards/user/total': [r.model_dump(mode='json') for r in totals],
        CONFIG_PATH: dict(data=[dict(condition_id=CONDITION, rewards_min_size=20,
            rewards_max_spread=3, rewards_daily_rate=100)], next_cursor='LTE=', count=1, limit=500),
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
    patcher = pytest.MonkeyPatch()
    def public_open(request, *, timeout):
        assert request.full_url == collector.HOST + CONFIG_PATH and timeout == 2
        assert request.get_method() == 'GET' and request.data is None
        reply = handle(httpx.Request('GET', request.full_url, headers=dict(request.header_items())))
        class Reply(BytesIO):
            status = 200
            def geturl(self): return request.full_url
        return Reply(reply.content)
    patcher.setattr(transport, 'urlopen', public_open)
    patcher.setattr(transport, '_user_agent', lambda: 'weather-re1-attended/123456789')
    class ReadsOnly:
        _ctx = ctx
        def __getattr__(self, name):
            assert name in {'list_user_earnings_for_day',
                'get_total_earnings_for_user_for_day', 'list_activity'}, 'non-read SDK method: ' + name
            return getattr(sdk, name)
        def close(self):
            patcher.undo()
            http.close()
            data_http.close()
    venue = object.__new__(OwnerVenue)
    venue.client, venue.maker, venue.guard = ReadsOnly(), MAKER, guard or SecretGuard()
    venue.readonly, venue.preflight, venue.journal_failed = True, False, False
    venue.condition = CONDITION
    return venue, calls, payloads


class RpcFixture:
    """A monotone finalized chain, hex RPC envelopes and exact Transfer logs."""
    def __init__(self, *, missing=None, cap=None, malformed=None, tip=2600, transfers=None):
        self.missing, self.cap, self.malformed, self.tip = missing, cap, malformed, tip
        self.calls = []
        self.genesis = START - timedelta(seconds=100)
        self.transfers = transfers if transfers is not None else [
            (1729, INCENTIVE_CASH_ASSET['asset_address'], TX, 1250000, 0)]
    def block(self, height):
        return dict(number=hex(height), timestamp=hex(int(self.genesis.timestamp()) + height * 100),
                    hash='0x' + format(height + 100, '064x'))
    def __call__(self, request, timeout):
        assert request.full_url == collector.RPC and request.method == 'POST' and timeout == 10
        assert request.get_header('User-agent') == 'weather-re1-attended/123456789'
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
                for height, asset, tx, units, index in self.transfers:
                    if first <= height <= last:
                        logs.append(dict(address=asset, blockNumber=hex(height), blockHash=self.block(height)['hash'],
                            topics=[collector.TRANSFER, '0x' + '0' * 24 + 'c' * 40, query['topics'][2]],
                            transactionHash=tx, logIndex=hex(index), removed=False, data='0x' + format(units, '064x')))
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


def collect(*, rpc=None, fail=None, now=NOW, activities=None, adjust=None):
    venue, calls, payloads = sdk_venue(fail=fail)
    if activities is not None: payloads['/activity'] = activities
    if adjust is not None: adjust(payloads)
    try:
        result = collector.collect_evidence(venue, prediction(), clock=lambda: now, opener=rpc or RpcFixture())
        assert all(not h for http in (venue.client._ctx.data._client, venue.client._ctx.secure_clob._client)
                   for h in http.event_hooks.values()), 'hooks were not restored'
        return result, calls
    finally:
        venue.client.close()


@pytest.mark.parametrize('missing', [None, 2300])
def test_real_collector_reconciler_verdict_round_trip_without_distribution_fixture(missing):
    result, _ = collect(rpc=RpcFixture(missing=missing))
    reconciled = reconcile_incentive_payments(result)
    verdict = payout_verdict(prediction(), {'rows': result['sdk_earnings']['rows']}, result)
    assert reconciled['valid'], reconciled
    if missing is None:
        assert reconciled['complete'] and reconciled['actual_liquidity_reward_usdc'] == 1.25, reconciled
        assert Decimal(verdict['paid']) == Decimal('1.25') and Decimal(verdict['k']) == Decimal('0.625')
        assert verdict['verdict'] == 'PAID_AS_MODELLED'
        assert result['distributions'][0]['linkage_basis'] == collector.LINKAGE_BASIS
        assert result['payout_diagnostics']['linkage_rule_outcome'] == 'matched'
    else:
        assert not reconciled['complete']
        assert verdict['paid'] is None and verdict['k'] is None and verdict['verdict'] == 'INCONCLUSIVE'


def test_actual_sdk_and_rpc_sources_link_under_reviewed_rule_and_hash_real_bytes():
    rpc = RpcFixture(cap=250)
    result, calls = collect(rpc=rpc)
    accrual, distributions, wallet = (result['sources'][s] for s in ('accruals', 'distributions', 'wallet_credits'))
    assert accrual['complete'] and accrual['pagination_complete']
    assert distributions['complete'] and distributions['status'] == 'OBSERVED'
    assert distributions['venue_earned_period_reference'] is False
    assert distributions['pagination_complete'] and result['distribution_candidates'][0]['type'] == 'REWARD'
    assert wallet['complete'] and wallet['pagination_complete'], wallet
    assert wallet['block_bounds']['first_block'] == 1 and wallet['block_bounds']['last_block'] == 2592
    assert len(wallet['chunks']) > 3 and all(r['complete'] for r in wallet['chunks'])
    assert len(result['wallet_credits']) == 1
    assert sum(len(r['wallet_credits']) for r in result['asset_observations'].values()) == 1
    journal = result['wire_journal']
    assert [r['sha256'] for r in journal if r['event'] == 'sdk_response'] == [hashlib.sha256(raw).hexdigest() for _, raw in calls]
    expected = [hashlib.sha256(req.method.encode() + b'\n' + req.url.raw_path + b'\n' + req.content).hexdigest() for req, _ in calls]
    assert [r['sha256'] for r in journal if r['event'] == 'wire_request'] == expected
    configurations = [(req, raw) for req, raw in calls if req.url.path == CONFIG_PATH]
    assert len(configurations) == 1
    _, config_raw = configurations[0]
    assert result['sdk_earnings']['market_configurations'] == json.loads(config_raw)['data']
    config_responses = [r for r in journal if r['event'] == 'sdk_response' and r['path'] == CONFIG_PATH]
    assert len(config_responses) == 1
    assert config_responses[0]['sha256'] == hashlib.sha256(config_raw).hexdigest()
    retained_journal = collector.ReadJournal(SecretGuard(), lambda: NOW)
    retained_journal.records = journal
    assert retained_journal.last_response_hash(CONFIG_PATH) == hashlib.sha256(config_raw).hexdigest()
    assert all(req.url.path != '/rewards/user/markets' for req, _ in calls)
    assert [r['sha256'] for r in journal if r['event'] == 'rpc_request'] == [hashlib.sha256(req).hexdigest() for req, _ in rpc.calls]
    assert [r['sha256'] for r in journal if r['event'] == 'rpc_response'] == [hashlib.sha256(raw).hexdigest() for _, raw in rpc.calls]
    activity_req = next(req for req, _ in calls if req.url.path == '/activity')
    assert activity_req.url.params['user'] == MAKER
    assert activity_req.url.params['type'] == 'REWARD'
    assert activity_req.url.params['start'] == str(int((START + timedelta(days=1)).timestamp()))
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
    assert payout_verdict(prediction(), {'rows': []}, result)['paid'] is None


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
    assert payout_verdict(prediction(), {'rows': []}, result)['paid'] is None


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
    try:
        result = collector.collect_evidence(venue, prediction(), clock=lambda: NOW, opener=RpcFixture())
    finally:
        venue.client.close()
    if case == 'precision':
        assert result['accruals'][0]['amount'] == '1.250000'
        assert result['accruals'][0]['venue_amount'] == '1.250000001'
        assert reconcile_incentive_payments(result)['complete']
        assert Decimal(payout_verdict(prediction(), {'rows': []}, result)['paid']) == Decimal('1.25')
    else:
        assert not result['sources']['accruals']['complete']
        assert payout_verdict(prediction(), {'rows': []}, result)['paid'] is None


def test_empty_earnings_require_explicit_zero_totals_for_both_assets():
    venue, _, payloads = sdk_venue()
    payloads['/rewards/user']['data'] = []
    payloads[CONFIG_PATH].update(data=[], count=0)
    for row in payloads['/rewards/user/total']: row['earnings'] = '0'
    try:
        result = collector.collect_evidence(venue, prediction(), clock=lambda: NOW, opener=RpcFixture())
    finally:
        venue.client.close()
    assert result['sources']['accruals']['complete']
    assert all(a['accruals'][0]['status'] == 'COMPLETED_ZERO' for a in result['asset_observations'].values())
    assert payout_verdict(prediction(), {'rows': []}, result)['verdict'] == 'INCONCLUSIVE'


@pytest.mark.parametrize('change', [
    {'data': [{}, {}], 'count': 2}, {'next_cursor': 'more'}, {'count': 0}, {'limit': True},
])
def test_invalid_condition_configuration_is_journaled_but_cannot_prove_accruals(change):
    result, calls = collect(adjust=lambda payloads: payloads[CONFIG_PATH].update(change))
    assert result['sources']['accruals']['status'] == 'FAILED'
    assert result['sources']['accruals']['failure_type'] == 'RuntimeError'
    assert not result['sources']['accruals']['complete'] and outcome(result)['paid'] is None
    responses = [r for r in result['wire_journal'] if r['event'] == 'sdk_response' and r['path'] == CONFIG_PATH]
    raw = next(raw for req, raw in calls if req.url.path == CONFIG_PATH)
    assert len(responses) == 1 and responses[0]['sha256'] == hashlib.sha256(raw).hexdigest()


def test_paginator_requires_terminal_page_and_refuses_repeated_cursor():
    from polymarket.pagination import Page
    journal = collector.ReadJournal(SecretGuard(), lambda: NOW)
    for pages in ([], [Page(items=(), has_more=True, next_cursor='same')] * 2,
                  [Page(items=(), has_more=True, next_cursor=None)]):
        with pytest.raises(ValueError, match='pagination'):
            collector.read_pages(pages, journal, '/rewards/user')


@pytest.mark.parametrize('path', ['/rewards/user', CONFIG_PATH, '/rewards/user/total', '/activity'])
def test_read_failure_is_retained_and_never_zero_payment(path):
    result, _ = collect(fail=path)
    assert not result['sources']['distributions']['complete']
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
    assert collector.run_collect_evidence(SimpleNamespace(prediction=path)) == 0
    files = list(session.glob('payout-evidence-*.json'))
    assert len(files) == 1 and len(list(session.iterdir())) == 2
    text = capsys.readouterr().out
    assert 'PAID_AS_MODELLED' in text and hashlib.sha256(files[0].read_bytes()).hexdigest() in text
    assert json.loads(files[0].read_bytes())['sources']['distributions']['status'] == 'OBSERVED'


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
    raw = b'{ "incomplete": true, "payout_diagnostics": {"linkage_rule_outcome":"no_amount_match"} }\n'
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
    assert literal_eval(printed)['payout_diagnostics']['linkage_rule_outcome'] == 'no_amount_match'
    result = json.loads(next(tmp_path.glob('payout-*.json')).read_bytes())
    assert result['payment_evidence_sha256'] == hashlib.sha256(raw).hexdigest() and result['paid'] is None
    assert result['payout_diagnostics']['linkage_rule_outcome'] == 'no_amount_match'


def activity(tx=TX, *, amount='1.25', at=START + timedelta(days=2), kind='REWARD'):
    return dict(proxyWallet=MAKER, timestamp=int(at.timestamp()), transactionHash=tx, type=kind, usdcSize=amount)


def transfer(units=1250000, *, tx=TX, index=0, asset=INCENTIVE_CASH_ASSET['asset_address']):
    return (1729, asset, tx, units, index)


def outcome(evidence):
    return payout_verdict(prediction(), {'rows': evidence['sdk_earnings'].get('rows', [])}, evidence)


@pytest.mark.parametrize('delta,state,complete', [(0, 'PAID', True), (-1, 'PARTIALLY_PAID', True),
    (1, 'PAID', True), (2, None, False)])
def test_amount_boundaries_round_trip(delta, state, complete):
    evidence, _ = collect(rpc=RpcFixture(transfers=[transfer(1250000 + delta)]))
    reconciled, verdict = reconcile_incentive_payments(evidence), outcome(evidence)
    diagnostics = evidence['payout_diagnostics']
    assert diagnostics['accrual_total_venue'] == '1.250000'
    assert diagnostics['accrual_total_units'] == 1250000
    assert Decimal(diagnostics['pusd_credits_in_window'][0]['amount']) == Decimal(1250000 + delta) / 1000000
    if complete:
        assert reconciled['complete'] and reconciled['rounding_tolerance_units'] == 1
        assert reconciled['accrual_states'][0]['state'] == state
        assert Decimal(verdict['paid']) == Decimal(1250000 + delta) / 1000000
        assert Decimal(verdict['k']) == Decimal(1250000 + delta) / 2000000
        assert verdict['verdict'] == 'PAID_AS_MODELLED'
        assert evidence['distributions'][0]['matched_amount_delta_units'] == delta
    else:
        assert diagnostics['linkage_rule_outcome'] == 'no_amount_match'
        assert verdict['verdict'] == 'INCONCLUSIVE' and verdict['paid'] is None and verdict['k'] is None


def test_two_reward_credits_of_accrual_amount_are_ambiguous():
    tx2 = '0x' + '3' * 64
    evidence, _ = collect(activities=[activity(), activity(tx2)], rpc=RpcFixture(transfers=[transfer(), transfer(tx=tx2)]))
    assert evidence['payout_diagnostics']['linkage_rule_outcome'] == 'ambiguous_amount_match'
    assert outcome(evidence)['verdict'] == 'INCONCLUSIVE' and not evidence['distributions']


@pytest.mark.parametrize('asset', collector.ASSETS)
def test_nonzero_second_condition_even_below_micro_precision_forbids_link(asset):
    def second_condition(payloads):
        original = next(r for r in payloads['/rewards/user']['data'] if r['asset_address'].lower() == asset.lower())
        other = dict(original, condition_id='0x' + 'd' * 64, earnings='0.0000001')
        payloads['/rewards/user']['data'].append(other)
        total = next(r for r in payloads['/rewards/user/total'] if r['asset_address'].lower() == asset.lower())
        total['earnings'] = str(Decimal(total['earnings']) + Decimal('0.0000001'))
    evidence, _ = collect(adjust=second_condition)
    assert evidence['sources']['accruals']['complete']
    assert evidence['payout_diagnostics']['linkage_rule_outcome'] == 'other_condition_accruals'
    assert evidence['payout_diagnostics']['other_condition_accruals']['count'] == 1
    assert outcome(evidence)['verdict'] == 'INCONCLUSIVE' and not evidence['distributions']


def test_closed_window_empty_reward_and_both_asset_credit_queries_proves_not_paid():
    evidence, _ = collect(activities=[], rpc=RpcFixture(transfers=[]))
    verdict = outcome(evidence)
    assert evidence['payout_diagnostics']['cash_window_closed']
    assert evidence['payout_diagnostics']['linkage_rule_outcome'] == 'not_paid'
    assert evidence['sources']['distributions']['complete'] and evidence['distributions'] == []
    assert verdict['payment_reconciliation']['accrual_states'][0]['state'] == 'UNPAID'
    assert Decimal(verdict['paid']) == 0 and verdict['verdict'] == 'NOT_PAID'


def test_usdc_credit_prevents_not_paid_when_pusd_and_activity_are_empty():
    evidence, _ = collect(activities=[], rpc=RpcFixture(transfers=[transfer(asset=collector.ASSETS[0].lower())]))
    assert evidence['payout_diagnostics']['usdc_e_credits_in_window']
    assert evidence['payout_diagnostics']['linkage_rule_outcome'] == 'wallet_credit_unattributed'
    assert outcome(evidence)['verdict'] == 'INCONCLUSIVE' and outcome(evidence)['paid'] is None


@pytest.mark.parametrize('transfers', [[], [transfer(), transfer(index=1)]])
def test_activity_requires_exactly_one_credit_for_its_transaction(transfers):
    evidence, _ = collect(rpc=RpcFixture(transfers=transfers))
    assert evidence['payout_diagnostics']['linkage_rule_outcome'] == 'activity_credit_join_failed'
    assert evidence['distribution_candidates'][0]['join_status'] == 'unjoined'
    assert outcome(evidence)['verdict'] == 'INCONCLUSIVE' and outcome(evidence)['paid'] is None


@pytest.mark.parametrize('activities', [[], [activity()], [activity(), activity('0x' + '3' * 64, amount='0.000010')]])
def test_unexplained_pusd_credits_are_never_suppressed(activities):
    evidence, _ = collect(activities=activities, rpc=RpcFixture(transfers=[transfer(), transfer(10, tx='0x' + '3' * 64)]))
    assert evidence['payout_diagnostics']['linkage_rule_outcome'] == 'wallet_credit_unattributed'
    assert evidence['excluded_external_credit_ids'] == []
    reconciled = reconcile_incentive_payments(evidence)
    assert any(r.startswith('wallet_credit_unattributed:') for r in reconciled['unresolved'])
    assert outcome(evidence)['verdict'] == 'INCONCLUSIVE'


@pytest.mark.parametrize('native,quantized', [('1.2500005', '1.250000'), ('1.2500015', '1.250002'),
    ('1.2500000000000000000000000000000001', '1.250000')])
def test_half_even_quantization_preserves_venue_amount_and_exact_totals(native, quantized):
    def adjust(payloads):
        for rows in (payloads['/rewards/user']['data'], payloads['/rewards/user/total']):
            for row in rows:
                if row['asset_address'].lower() == INCENTIVE_CASH_ASSET['asset_address']:
                    row['earnings'] = native
    evidence, _ = collect(adjust=adjust, rpc=RpcFixture(transfers=[transfer(collector.micro_units(quantized))]))
    assert evidence['accruals'][0]['amount'] == quantized
    assert evidence['accruals'][0]['venue_amount'] == native
    assert evidence['payout_diagnostics']['accrual_total_venue'] == native
    assert outcome(evidence)['verdict'] == 'PAID_AS_MODELLED'


@pytest.mark.parametrize('fail', ['/activity', None])
def test_empty_but_incomplete_reads_never_prove_not_paid(fail):
    evidence, _ = collect(activities=[], fail=fail, rpc=RpcFixture(transfers=[], missing=None if fail else 2300))
    assert not evidence['sources']['distributions']['complete']
    assert outcome(evidence)['verdict'] == 'INCONCLUSIVE' and outcome(evidence)['paid'] is None


def test_totals_are_compared_before_rounding_even_when_micro_units_agree():
    def adjust(payloads):
        total = next(r for r in payloads['/rewards/user/total']
                     if r['asset_address'].lower() == INCENTIVE_CASH_ASSET['asset_address'])
        total['earnings'] = '1.2500001'
    evidence, _ = collect(adjust=adjust)
    assert not evidence['sources']['accruals']['complete']
    assert evidence['payout_diagnostics']['linkage_rule_outcome'] == 'accruals_not_final'
    assert evidence['payout_diagnostics']['accrual_total_units'] is None
    assert outcome(evidence)['paid'] is None


def test_native_total_comparison_does_not_round_at_default_decimal_precision():
    def adjust(payloads):
        for row in payloads['/rewards/user']['data']:
            if row['asset_address'].lower() == INCENTIVE_CASH_ASSET['asset_address']:
                row['earnings'] = '1.2500000000000000000000000000000001'
    evidence, _ = collect(adjust=adjust)
    assert evidence['sources']['accruals']['status'] == 'FAILED'
    assert evidence['payout_diagnostics']['accrual_total_venue'] == '1.2500000000000000000000000000000001'
    assert outcome(evidence)['paid'] is None


@pytest.mark.parametrize('bad_activity', [activity(at=START + timedelta(hours=12)), activity(kind='MAKER_REBATE')])
def test_wrong_activity_window_or_programme_is_retained_but_cannot_link(bad_activity):
    evidence, _ = collect(activities=[bad_activity])
    assert evidence['payout_diagnostics']['linkage_rule_outcome'] == 'activity_coverage_incomplete'
    assert not evidence['distributions'] and outcome(evidence)['paid'] is None


def test_guard_refuses_secret_in_payout_diagnostics(tmp_path, monkeypatch):
    from weather.market import re1_attended_cli as cli
    path = tmp_path / 'payment.json'
    path.write_text(json.dumps({'payout_diagnostics': {'unexpected': 'synthetic-loaded-secret'}}))
    monkeypatch.setattr(cli, 'load_prediction', lambda *a, **kw: prediction())
    monkeypatch.setattr('weather.market.re1_transport.load_owner_credentials', lambda *_:
                        ({'FUNDER_ADDRESS': MAKER}, SecretGuard(['synthetic-loaded-secret'])))
    monkeypatch.setattr('weather.market.re1_transport.build_client', lambda *a, **kw: None)
    monkeypatch.setattr('weather.market.re1_transport.OwnerVenue', lambda *a, **kw: SimpleNamespace(
        accrual=lambda day: {'rows': []}, balances=lambda: {}, close=lambda: None))
    with pytest.raises(RuntimeError, match='secret_output_refused'):
        cli.run_collect(SimpleNamespace(prediction=tmp_path / 'prediction.json', payment_evidence=path))
    assert not list(tmp_path.glob('payout-*.json'))


@pytest.mark.parametrize('has_payment', [False, True])
def test_activity_query_started_before_cash_end_cannot_claim_full_coverage_after_response(has_payment):
    venue, _, payloads = sdk_venue()
    clock = {'now': START + timedelta(days=3, seconds=-1)}
    if not has_payment: payloads['/activity'] = []
    def cross_deadline(response):
        clock['now'] = NOW
    venue.client._ctx.data._client.event_hooks['response'].append(cross_deadline)
    try:
        evidence = collector.collect_evidence(venue, prediction(), clock=lambda: clock['now'],
            opener=RpcFixture() if has_payment else RpcFixture(transfers=[]))
    finally:
        venue.client.close()
    source = evidence['sources']['distributions']
    assert utc(source['activity_request_scope']['period_end_utc']) < utc(evidence['scope']['cash_end_utc'])
    assert utc(source['activity_observed_at_utc']) > utc(evidence['scope']['cash_end_utc'])
    assert source['candidate_pagination_complete'] and not source['complete']
    assert evidence['payout_diagnostics']['linkage_rule_outcome'] == 'activity_coverage_incomplete'
    assert outcome(evidence)['paid'] is None and outcome(evidence)['verdict'] == 'INCONCLUSIVE'
