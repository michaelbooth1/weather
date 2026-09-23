"""84g: complementary fills and the dated owner-approved payout interpretation."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from tests.market.stage2_fakes import CONDITION, TOKENS, MAKER
from tests.market.test_re1_attended import setup
from tests.market.test_re1_payout_evidence import (
    prediction, collect, RpcFixture, transfer, activity, collector,
)
from weather.market.re1_attended import SecretGuard
from weather.market.re1_evidence import payout_verdict, journal_adequacy
from weather.market.re1_transport import PairStream, OwnerVenue


def trade(order_id='maker-no', *, same_token=False, amount='5.57'):
    # REST session-1 uses token_id; the WS documented alias is asset_id.
    # All identities are synthetic. No retained owner/key fields are copied.
    return dict(event_type='trade', id='synthetic-trade', market=CONDITION,
        asset_id=TOKENS[1] if same_token else TOKENS[0], trader_side='MAKER',
        outcome='No' if same_token else 'Yes', side='BUY', price='.52', size='25.57', status='MATCHED',
        maker_orders=[dict(asset_id=TOKENS[1], outcome='No', side='BUY', maker_address=MAKER,
                          order_id=order_id, matched_amount=amount, price='.48')])


def stream(tmp_path, **kwargs):
    return PairStream(tokens=TOKENS, guard=SecretGuard(['loaded-secret']), maker_address=MAKER,
        condition_id=CONDITION, api_key='synthetic-key', secret='synthetic-secret', passphrase='synthetic-pass',
        journal_path=tmp_path / 'stream.jsonl', **kwargs)


@pytest.mark.parametrize('case', ['complementary', 'same_token', 'full', 'unmatched', 'malformed'])
def test_trade_signal_ends_session_with_fill_rows_and_cleanup(tmp_path, case):
    session, venue, clock = setup(tmp_path)
    reader = stream(tmp_path, known_order_ids=session.known)
    reads = []
    original_order = venue.order
    def order(oid):
        reads.append((clock.seconds, oid))
        return original_order(oid)
    venue.order = order
    sent = False
    def events():
        nonlocal sent
        if clock.seconds < 30 or sent: return []
        sent = True
        oid = next(k for k, leg in session.known.items() if leg == 1)
        item = trade(oid, same_token=case == 'same_token', amount='20' if case == 'full' else '5.57')
        if case == 'unmatched': item['maker_orders'] = []
        if case == 'malformed':
            item['maker_orders'] = 9
            with pytest.raises(TypeError): reader._normalize_event(item)
            reader._state, reader._failure_type = 'FAILED', 'TypeError'
            owner = object.__new__(OwnerVenue)
            owner.stream, owner.event_count, owner.condition = reader, 0, CONDITION
            return owner.events()
        return reader._normalize_event(item)
    venue.events = events
    result = session.run(rehearsal_seconds=120)
    assert result['reason'] == 'fill' and result['failure_type'] is None
    assert result['fill_seen'] and result['cleanup_ok'] and venue.open_orders() == []
    rows = [json.loads(s) for s in session.journal.path.read_text().splitlines()]
    fill = next(r for r in rows if r['event'] == 'fill')
    assert len(fill['rows']) == 2
    assert set(oid for at, oid in reads if at == 30) == set(session.known)
    assert any(r['event'] == 'unmatched_trade_event' for r in rows) == (case == 'unmatched')


def test_known_order_can_match_without_maker_identity_and_token_alias(tmp_path):
    reader = stream(tmp_path, known_order_ids={'ours'})
    item = trade('ours')
    maker = item['maker_orders'][0]
    maker.pop('maker_address')
    maker['token_id'] = maker.pop('asset_id')
    result = reader._normalize_event(item)[0]
    assert result['order_id'] == 'ours' and result['clob_token_id'] == TOKENS[1]
    assert result['fill_size'] == '5.57' and result['outcome'] == 'No'


@pytest.mark.parametrize('ours', [False, True])
def test_failed_stream_journals_redacted_message_and_other_market_fails_closed(tmp_path, ours):
    item = trade()
    item.update(maker_orders=7, owner='another-key', api_key='loaded-secret',
                nested={'POLY_API_KEY': 'another-key', 'credentials': {'secret': 'loaded-secret'}, 'outcome': 'Yes'})
    if not ours: item['market'] = '0x' + 'f' * 64
    socket = SimpleNamespace(send=lambda x: None, settimeout=lambda x: None,
                             recv=lambda: json.dumps(item), close=lambda: None)
    reader = stream(tmp_path, websocket_factory=lambda *a, **k: socket)
    with pytest.raises((RuntimeError, TypeError)): reader.run()
    rows = [json.loads(s) for s in reader.journal_path.read_text().splitlines()]
    failed = next(r for r in rows if r['event_type'] == 'stream_failed')
    assert len(failed['raw_event_sha256']) == 64
    assert failed['failing_message']['nested'] == {'outcome': 'Yes'}
    def keys(value):
        if isinstance(value, dict):
            for key, child in value.items():
                assert not any(p in key.lower() for p in ('owner', 'key', 'secret', 'credential', 'auth', 'signature'))
                keys(child)
        elif isinstance(value, list):
            for child in value: keys(child)
    keys(failed['failing_message'])
    assert 'loaded-secret' not in reader.journal_path.read_text()
    owner = object.__new__(OwnerVenue)
    owner.stream, owner.event_count, owner.condition = reader, 0, CONDITION
    if ours: assert owner.events()[0]['force_order_read']
    else:
        with pytest.raises(RuntimeError, match='user_stream_invalid_event'): owner.events()


def amended_prediction(**changes):
    p = prediction()
    p['adequacy'] = dict(elapsed_minutes=200, public_book_minutes=200,
                         size_spread_unchanged=True, two_sided_scoring_minutes=200)
    p.update(changes)
    return p


def earnings(amount):
    def adjust(payloads):
        for name in ('/rewards/user', '/rewards/user/total'):
            rows = payloads[name]['data'] if name == '/rewards/user' else payloads[name]
            for row in rows:
                row['earnings'] = amount if row['asset_address'].lower() == collector.INCENTIVE_CASH_ASSET['asset_address'] else '0'
    return adjust


@pytest.mark.parametrize('amount,p,expected,accrued', [
    ('1.25', 2, 'PAID_AS_MODELLED', None), ('1.25', 10, 'PAID_DILUTED', None),
    ('.12', .105, 'BELOW_PAYOUT_MINIMUM', 'ACCRUED_AS_MODELLED'),
    ('.2', 1, 'BELOW_PAYOUT_MINIMUM', 'ACCRUED_DILUTED'),
    ('.05', 1, 'BELOW_PAYOUT_MINIMUM', 'ACCRUED_LOW'),
    ('2', 2, 'NOT_PAID', None), ('0', 2, 'NOT_PAID', None),
    ('1.25', 20, 'INCONCLUSIVE', None),
])
def test_addendum_verdict_rows(amount, p, expected, accrued):
    paid = expected.startswith('PAID') or expected == 'INCONCLUSIVE'
    evidence, _ = collect(adjust=earnings(amount), activities=[activity()] if paid else [],
        rpc=RpcFixture(transfers=[transfer(collector.micro_units(amount))] if paid else []))
    result = payout_verdict(amended_prediction(P_many=p), evidence['sdk_earnings'], evidence)
    assert result['verdict_amended'] == expected, result
    assert result['accrued_verdict'] == accrued


def test_session_one_shape_keeps_frozen_and_amended_verdicts():
    evidence, _ = collect(adjust=earnings('.12'), activities=[], rpc=RpcFixture(transfers=[]))
    p = amended_prediction(P_many=.105, visible_two_sided_minutes=42,
        evidence_complete=False, reward_terms_changed=True, failure_type='RuntimeError')
    p['adequacy'].update(elapsed_minutes=43, public_book_minutes=42, two_sided_scoring_minutes=42)
    result = payout_verdict(p, evidence['sdk_earnings'], evidence)
    assert result['verdict_frozen'] == 'INCONCLUSIVE'
    assert result['verdict_amended'] == 'BELOW_PAYOUT_MINIMUM'
    assert result['accrued_verdict'] == 'ACCRUED_AS_MODELLED' and result['flags'] == ['SHORT']


@pytest.mark.parametrize('sampled,unchanged,cleanup,adequate', [
    (190, True, True, True), (189, True, True, False),
    (200, False, True, False), (200, True, False, False),
])
def test_adequacy_exact_95_percent_and_size_spread_cleanup(sampled, unchanged, cleanup, adequate):
    evidence, _ = collect(rpc=RpcFixture(transfers=[transfer()]))
    p = amended_prediction(evidence_complete=False, reward_terms_changed=True, cleanup_ok=cleanup)
    p['adequacy'].update(public_book_minutes=sampled, size_spread_unchanged=unchanged)
    result = payout_verdict(p, evidence['sdk_earnings'], evidence)
    assert result['adequate'] == adequate
    assert result['verdict_amended'] == ('PAID_AS_MODELLED' if adequate else 'INCONCLUSIVE')


@pytest.mark.parametrize('amount', ['0', '2'])
def test_short_cannot_be_not_paid(amount):
    evidence, _ = collect(adjust=earnings(amount), activities=[], rpc=RpcFixture(transfers=[]))
    result = payout_verdict(amended_prediction(visible_two_sided_minutes=179), evidence['sdk_earnings'], evidence)
    assert result['verdict_amended'] != 'NOT_PAID' and result['flags'] == ['SHORT']


@pytest.mark.parametrize('asset', collector.ASSETS)
@pytest.mark.parametrize('earning_asset', collector.ASSETS)
def test_both_native_payment_assets_and_ambiguity(asset, earning_asset):
    def adjust(payloads):
        for name in ('/rewards/user', '/rewards/user/total'):
            rows = payloads[name]['data'] if name == '/rewards/user' else payloads[name]
            for row in rows:
                row['earnings'] = '1.25' if row['asset_address'].lower() == earning_asset.lower() else '0'
    evidence, _ = collect(adjust=adjust, rpc=RpcFixture(transfers=[transfer(asset=asset.lower())]))
    result = payout_verdict(amended_prediction(), evidence['sdk_earnings'], evidence)
    assert result['verdict_amended'] == 'PAID_AS_MODELLED', result
    assert result['payment_reconciliation']['cash_assets'][0]['asset_address'] == asset.lower()
    ambiguous, _ = collect(activities=[activity(), activity('0x' + '3' * 64)],
        rpc=RpcFixture(transfers=[transfer(), transfer(asset=asset.lower(), tx='0x' + '3' * 64)]))
    assert payout_verdict(amended_prediction(), ambiguous['sdk_earnings'], ambiguous)['paid'] is None


def test_short_paid_session_is_reported_and_missing_cash_coverage_is_not_zero():
    evidence, _ = collect(rpc=RpcFixture(transfers=[transfer()]))
    result = payout_verdict(amended_prediction(visible_two_sided_minutes=42), evidence['sdk_earnings'], evidence)
    assert result['flags'] == ['SHORT'] and result['verdict_amended'] == 'PAID_AS_MODELLED'
    assert result['verdict_frozen'] == 'INCONCLUSIVE'
    evidence['sources']['wallet_credits']['complete'] = False
    assert payout_verdict(amended_prediction(), evidence['sdk_earnings'], evidence)['paid'] is None


@pytest.mark.parametrize('change', ['maker', 'asset', 'amount', 'time', 'distribution', 'earnings', 'assets'])
def test_native_replay_refuses_tampered_evidence(change):
    asset = collector.ASSETS[0].lower()
    evidence, _ = collect(rpc=RpcFixture(transfers=[transfer(asset=asset)]))
    credit = evidence['asset_observations'][asset]['wallet_credits'][0]
    if change == 'maker': credit['maker_address'] = '0x' + 'e' * 40
    elif change == 'asset': credit['cash_asset'] = dict(collector.INCENTIVE_CASH_ASSET)
    elif change == 'amount': credit['amount'] = '9'
    elif change == 'time': credit['credited_at_utc'] = '2026-08-01T00:00:00Z'
    elif change == 'distribution': evidence['reward_distributions'][0]['amount'] = '9'
    elif change == 'earnings': evidence['sdk_earnings']['total_earnings'][0]['earnings'] = '9'
    else: evidence['sources']['wallet_credits']['assets'] = [asset]
    assert payout_verdict(amended_prediction(), evidence['sdk_earnings'], evidence)['paid'] is None


@pytest.mark.parametrize('field', ['reward_rate_per_day', 'reward_min_size', 'reward_max_spread_cents'])
def test_journal_adequacy_distinguishes_integrated_rate_from_size_spread(tmp_path, field):
    session, venue, clock = setup(tmp_path)
    session.run(rehearsal_seconds=120)
    rows = [json.loads(s) for s in session.journal.path.read_text().splitlines()]
    changed = deepcopy(rows)
    next(r for r in changed if r['event'] == 'minute')['snapshot']['quote_inputs'][field] = '41'
    assert journal_adequacy(changed)['size_spread_unchanged'] == (field == 'reward_rate_per_day')
    assert journal_adequacy(rows)['public_book_minutes'] == journal_adequacy(rows)['elapsed_minutes'] == 2
