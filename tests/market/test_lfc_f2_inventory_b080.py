"""Synthetic enrollment and between-session wallet snapshots.

Guards: B080 immutable inventory cuts, campaign quantities, outside-hours cash,
bounded activity windows and strict in-session wallet reconciliation.
"""
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import Clock, Mutexes
from tests.market.test_lfc_f2_capital import MAKER, NOW, activity, filled
from tests.market.test_lfc_f2_capital_reads import native_packet, packet
from weather.market.lfc_accounting import inventory_delta
from weather.market.lfc_capital import ASSET, CapitalBook, CapitalRefused, native, record_activity
from weather.market.lfc_capital_reads import read_activity, synchronize
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_f2_inventory import activity_start, expected_inventory
from weather.market.lfc_ledger import Ledger, LedgerUnavailable, take_baseline, write_baseline
from weather.market.lfc_recording_io import strict_json, write_new
from weather.market.mm_stage2_hold import digest


def fixture(tmp_path, *, personal=True, bridge=True):
    clock = Clock()
    clock.value = NOW
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=clock.now, maker_address=MAKER)
    baseline = take_baseline(label='t40', now=clock.now(), maker_address=MAKER,
        positions=[{'asset': 'old-personal', 'size': '7', 'conditionId': 'old-owner-condition'}] if personal else [],
        open_orders=[], available_collateral='300')
    write_baseline(tmp_path, baseline, ledger)
    filled(ledger, 'legacy', token='denver')
    positions = {'denver': '20', **({'nfl': '15'} if personal else {})}
    read = observation(ledger, clock, positions=positions, cash='290')
    if bridge:
        synchronize(ledger, baseline, read, anchor_mode='enrollment')
    return ledger, baseline, clock, read


def observation(ledger, clock, *, positions, cash):
    when = clock.now().isoformat()
    start = activity_start(ledger, when)
    end = int(clock.now().timestamp())
    return {'schema_version': 'lfc_campaign_account_read_v0.1', 'complete': True,
        'maker_address': MAKER, 'open_orders': [], 'errors': [],
        'scope': 'account_wide_sdk_trades_and_f0_v2_positions',
        'since': str(int(NOW.timestamp())), 'started_at_utc': when, 'ended_at_utc': when,
        'component_times': {name: {'started_at_utc': when, 'ended_at_utc': when}
            for name in ('open_orders', 'trades', 'positions', 'balances', 'geography')},
        'positions': [{'asset': token, 'size': str(size), 'conditionId': 'c' if token == 'denver' else 'other'}
                      for token, size in positions.items()],
        'trades': [{'status': 'CONFIRMED', 'maker_orders': [
            {'order_id': leg['order_id'], 'matched_amount': leg['size_matched']} for leg in ledger.legs.values()
            if leg['status'] == 'terminal']}],
        'balances': {'available_collateral': cash, 'assets': {ASSET: cash},
                     'collateral_evidence': {'balance': str(native(cash))}},
        'geography': {'blocked': False},
        'capital_activity': native_packet(read_activity(MAKER, start, end,
                          get=lambda *args: packet(), sleep=lambda _: None))}


def test_enrollment_accepts_personal_pre_bridge_changes_and_binds_one_read(tmp_path):
    ledger, baseline, clock, read = fixture(tmp_path)
    book = CapitalBook(ledger)
    anchor = book.inventory_anchor
    assert anchor['positions'] == {'denver': '20', 'nfl': '15'}
    assert anchor['read_sha256'] == book.bridge['proof']['read_sha256'] == digest(read)
    assert anchor['positions_sha256'] == digest(anchor['positions'])
    assert anchor['ledger_cut'] == book.bridge['sequence']
    assert anchor['ledger_head_sha256'] == book.bridge['previous_sha256']
    assert book.anchor == baseline and ledger.L() == 10
    assert book.figures()['funding_native'] == 300_000_000
    assert not inventory_delta(ledger, anchor, anchor['positions'])['changed']


@pytest.mark.parametrize('size', ['0', '19.999999'])
def test_enrollment_cannot_hide_missing_or_short_campaign_holding(tmp_path, size):
    ledger, baseline, clock, read = fixture(tmp_path, bridge=False)
    read['positions'] = [{'asset': 'denver', 'size': size}, {'asset': 'nfl', 'size': '100'}]
    with pytest.raises(CapitalRefused, match='f2_anchor_campaign_inventory'):
        synchronize(ledger, baseline, read, anchor_mode='enrollment')
    assert CapitalBook(ledger).bridge is None


@pytest.mark.parametrize('fault,code', [('session', 'f2_anchor_open_session'),
    ('intent', 'f2_anchor_unknown_submit'), ('unresolved', 'f2_anchor_unresolved_legs'),
    ('orders', 'foreign_open_order'), ('incomplete', 'f2_anchor_account_incomplete')])
def test_enrollment_preconditions_have_named_refusals(tmp_path, fault, code):
    ledger, baseline, clock, read = fixture(tmp_path, bridge=False)
    if fault in {'session', 'intent', 'unresolved'}:
        ledger.record('session_start', session_id='open')
        if fault != 'session':
            ledger.intent(session_id='open', intent_key='open:1', condition_id='c', token_id='yes',
                          price='.4', size='20', fee_rate_bps='0')
            if fault == 'unresolved':
                ledger.ack('open:1', 'open-order')
            ledger.record('session_end', session_id='open')
    elif fault == 'orders':
        read['open_orders'] = [{'id': 'foreign'}]
    else:
        read['complete'] = False
    with pytest.raises(CapitalRefused, match=code):
        synchronize(ledger, baseline, read, anchor_mode='enrollment')
    assert CapitalBook(ledger).bridge is None


@pytest.mark.parametrize('size', ['19.999999', '20.000001'])
def test_session_reanchor_refuses_campaign_surplus_or_shortfall(tmp_path, size):
    ledger, baseline, clock, _ = fixture(tmp_path)
    clock.value += timedelta(days=1)
    read = observation(ledger, clock, positions={'denver': size, 'new-nfl': '99'}, cash='240')
    before = ledger.path.read_bytes()
    with pytest.raises(CapitalRefused, match='capital_inventory_unreconciled'):
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    assert ledger.path.read_bytes() == before


def test_between_session_nfl_buy_withdrawal_and_cash_above_sleeve_do_not_grow_capital(tmp_path):
    ledger, baseline, clock, _ = fixture(tmp_path)
    before = CapitalBook(ledger).figures()
    clock.value += timedelta(hours=12)
    withdrawal = activity(cash='40', size='0', token='', tx='personal-withdraw', kind='WITHDRAWAL')
    withdrawal['timestamp'] = int(clock.now().timestamp())
    record_activity(ledger, withdrawal)
    clock.value += timedelta(hours=12)
    read = observation(ledger, clock, positions={'denver': '20', 'new-nfl': '25'}, cash='230')
    result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    assert result['cash_bridge_complete'] and not result['inventory']['changed']
    book = CapitalBook(ledger)
    assert book.expected_cash() == 230_000_000
    assert book.costs == 0 and book.figures()['funding_native'] == before['funding_native']
    assert book.figures()['charged_native'] == before['charged_native']
    assert book.inventory_anchor['positions'] == {'denver': '20', 'new-nfl': '25'}
    clock.value += timedelta(days=1)
    deposited = observation(ledger, clock, positions={'denver': '20'}, cash='920')
    synchronize(ledger, book.inventory_anchor, deposited, anchor_mode='session')
    after = CapitalBook(ledger)
    assert after.figures()['funding_native'] == 300_000_000
    assert after.figures()['headroom_native'] == 290_000_000
    assert after.external == 690_000_000
    with pytest.raises(CapitalRefused, match='capital_spendable_cash'):
        after.gate(reserve='230.000001', available_cash='920')


def test_foreign_open_order_refuses_session_anchor(tmp_path):
    ledger, baseline, clock, read = fixture(tmp_path)
    read['open_orders'] = [{'id': 'foreign', 'status': 'LIVE'}]
    with pytest.raises(CapitalRefused, match='foreign_open_order'):
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    assert not any(row['event'] == 'f2_session_anchor' for row in ledger.rows)


def test_campaign_fills_and_redemptions_replay_from_each_cut(tmp_path):
    ledger, baseline, clock, _ = fixture(tmp_path, personal=False)
    clock.value += timedelta(hours=1)
    filled(ledger, 'second', token='new-campaign', size='5', price='.4')
    source = activity(cash='0', token='denver', tx='loser')
    source['timestamp'] = int(clock.now().timestamp())
    record_activity(ledger, source)
    clock.value += timedelta(hours=1)
    read = observation(ledger, clock, positions={'new-campaign': '5', 'nfl': '9'}, cash='288')
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    expected = expected_inventory(ledger, CapitalBook(ledger).inventory_anchor, CapitalBook(ledger))
    reopened = Ledger.open(ledger.path, clock=clock.now)
    assert CapitalBook(reopened).inventory_anchor == CapitalBook(ledger).inventory_anchor
    assert expected_inventory(reopened, CapitalBook(reopened).inventory_anchor, CapitalBook(reopened)) == expected
    assert expected == {'new-campaign': '5', 'nfl': '9'}
    assert CapitalBook(reopened).figures() == CapitalBook(ledger).figures()


def test_original_anchor_is_immutable_and_second_bridge_refuses(tmp_path):
    ledger, baseline, clock, _ = fixture(tmp_path)
    row = CapitalBook(ledger).bridge
    before = ledger.path.read_bytes()
    fields = {key: value for key, value in row.items()
              if key not in {'event', 'schema_version', 'kind', 'sequence', 'previous_sha256', 'recorded_at_utc'}}
    with pytest.raises(LedgerUnavailable, match='capital_bridge_already_exists'):
        ledger.record('capital_bridge', **fields)
    assert ledger.path.read_bytes() == before


def test_personal_buy_inside_run_still_changes_all_token_inventory(tmp_path):
    ledger, baseline, clock, _ = fixture(tmp_path)
    anchor = CapitalBook(ledger).inventory_anchor
    result = inventory_delta(ledger, anchor, {'denver': '20', 'nfl': '16'})
    assert result['changed'] == ['nfl']
    with pytest.raises(CapitalRefused, match='capital_inventory_unreconciled'):
        synchronize(ledger, anchor, observation(ledger, clock, positions={'denver': '20', 'nfl': '16'}, cash='290'))


def test_non_campaign_auto_redemption_removes_owner_inventory_without_campaign_income(tmp_path):
    ledger, baseline, clock, _ = fixture(tmp_path)
    clock.value += timedelta(minutes=1)
    source = activity(cash='15', size='15', token='nfl', tx='auto-owner')
    source['timestamp'] = int(clock.now().timestamp())
    record_activity(ledger, source)
    read = observation(ledger, clock, positions={'denver': '20'}, cash='305')
    result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, read)
    assert result['cash_bridge_complete'] and result['inventory']['changed'] == []
    book = CapitalBook(ledger)
    assert book.external == 15_000_000 and book.profit == 0
    assert book.figures()['charged_native'] == 10_000_000


def test_owner_redemption_in_anchor_second_keeps_native_timestamp_precision(tmp_path):
    ledger, baseline, clock, _ = fixture(tmp_path, bridge=False)
    clock.value += timedelta(microseconds=500000)
    read = observation(ledger, clock, positions={'denver': '20', 'nfl': '15'}, cash='290')
    synchronize(ledger, baseline, read, anchor_mode='enrollment')
    source = activity(cash='15', size='15', token='nfl', tx='same-second-auto')
    source['timestamp'] = int(clock.now().timestamp())
    clock.value += timedelta(microseconds=100000)
    record_activity(ledger, source)
    read = observation(ledger, clock, positions={'denver': '20'}, cash='305')
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read)['cash_bridge_complete']


@pytest.mark.parametrize('ctf', [False, True])
def test_native_auto_redemption_of_personal_paired_positions_keeps_session_money_clean(tmp_path, ctf):
    from tests.market.test_lfc_redemption_native import paired
    ledger, baseline, clock, _ = fixture(tmp_path, personal=False, bridge=False)
    source, proof, tokens = paired(auto=True, ctf=ctf)
    positions = {'denver': '20', **{token: '20' for token in tokens}}
    read = observation(ledger, clock, positions=positions, cash='290')
    synchronize(ledger, baseline, read, anchor_mode='enrollment')
    clock.value += timedelta(minutes=1)
    source['timestamp'] = int(clock.now().timestamp())
    proof['rows'] = [source]
    proof['rows_sha256'] = digest(proof['rows'])
    record_activity(ledger, source, native_evidence=proof)
    read = observation(ledger, clock, positions={'denver': '20'}, cash='310')
    result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, read)
    assert result['cash_bridge_complete'] and result['inventory']['changed'] == []
    book = CapitalBook(ledger)
    assert book.external == 20_000_000 and book.profit == 0
    assert book.figures()['headroom_native'] == 290_000_000


def test_account_activity_and_native_receipts_exclude_250_pre_anchor_transactions(tmp_path, monkeypatch):
    from weather.market import re1_transport, lfc_campaign_runtime, lfc_capital_reads, lfc_capital_native
    from weather.market.lfc_f2_pinb import example_policy
    from tests.market.test_lfc_f2_capital_reads import rpc_packet
    ledger, baseline, clock, _ = fixture(tmp_path, bridge=False)
    old = []
    for index in range(250):
        source = activity(cash='1', size='0', token='', tx=f'owner-{index}', kind='WITHDRAWAL')
        source['timestamp'] = int((clock.now() + timedelta(minutes=30)).timestamp())
        old.append(source)
    clock.value += timedelta(hours=1)
    read = observation(ledger, clock, positions={'denver': '20', 'nfl': '15'}, cash='290')
    synchronize(ledger, baseline, read, anchor_mode='enrollment')
    anchor = CapitalBook(ledger).inventory_anchor
    clock.value += timedelta(hours=1)
    path = tmp_path / 'campaign.json'
    write_new(path, example_policy())
    runtime = object.__new__(Runtime)
    runtime.state = SimpleNamespace(ledger=ledger, maker=MAKER, policy_binding={})
    runtime.clock, runtime.policy_path = clock, path
    class Venue:
        def __init__(self, *args, **kwargs):
            assert kwargs['readonly'] is True
        def open_orders(self): return []
        def trades(self): return read['trades']
        def balances(self): return read['balances']
        def geography(self): return {'blocked': False}
        def close(self): pass
    monkeypatch.setattr(re1_transport, 'load_owner_credentials', lambda _: ({'FUNDER_ADDRESS': MAKER}, None))
    monkeypatch.setattr(re1_transport, 'build_client', lambda *a, **k: object())
    monkeypatch.setattr(re1_transport, 'OwnerVenue', Venue)
    monkeypatch.setattr(lfc_campaign_runtime, 'fetch_account_positions', lambda _: read['positions'])
    queries, rpc_calls = [], []
    def get(endpoint, params):
        queries.append(params)
        return packet([row for row in old if params['start'] <= row['timestamp'] <= params['end']])
    real_read, real_collect = lfc_capital_reads.read_activity, lfc_capital_native.collect
    monkeypatch.setattr(lfc_capital_reads, 'read_activity', lambda *a: real_read(*a, get=get, sleep=lambda _: None))
    def rpc(method, params):
        rpc_calls.append(method)
        assert method in {'eth_chainId', 'eth_call'}
        return rpc_packet('0x89' if method == 'eth_chainId' else '0x6')
    monkeypatch.setattr(lfc_capital_native, 'collect', lambda packet, ledger: real_collect(
        packet, ledger=ledger, rpc=rpc, sleep=lambda _: None))
    result = runtime.account_read_once()
    from weather.market.lfc_f2_inventory import ACTIVITY_OVERLAP_SECONDS
    assert queries[0]['start'] + ACTIVITY_OVERLAP_SECONDS == int(NOW.timestamp()) + 3600 == int(datetime.fromisoformat(anchor['at_utc']).timestamp())
    # Overlap retains the API evidence; only eligible rows consume receipts.
    from weather.market.lfc_f2_wallet_reads import native_rows
    assert result['capital_activity']['rows'] == old
    assert native_rows(result['capital_activity'], ledger) == []
    assert rpc_calls == ['eth_chainId', 'eth_call']
    # The same complete synthetic old page exceeds the unchanged native budget.
    old_packet = native_packet(real_read(MAKER, int(NOW.timestamp()), int(clock.now().timestamp()),
                                        get=lambda *a: packet(old), sleep=lambda _: None))
    with pytest.raises(ValueError, match='capital_native_receipt_budget'):
        real_collect(old_packet, ledger=ledger, rpc=rpc, sleep=lambda _: None)


@pytest.mark.parametrize('kind', ['DEPOSIT', 'REWARD'])
def test_pending_incoming_crossing_anchor_is_not_counted_twice_and_remains_provable(tmp_path, monkeypatch, kind):
    from tests.market.test_lfc_review_b066_incoming import incoming
    from weather.market import lfc_capital_native
    from weather.market.lfc_f2_wallet_reads import collect_window
    ledger, baseline, clock, _ = fixture(tmp_path, personal=False)
    source, proof = incoming(ledger, kind=kind, missing=True)
    clock.value = ledger.clock() + timedelta(seconds=1)
    ledger.clock = clock.now
    read = observation(ledger, clock, positions={'denver': '20'}, cash='295')
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    book = CapitalBook(ledger)
    assert book.expected_cash() == 295_000_000
    assert book.external == 5_000_000  # One quarantine for the captured five.
    assert book.quarantined_after_bridge() == 0
    clock.value += timedelta(seconds=1)
    read = observation(ledger, clock, positions={'denver': '20'}, cash='295')
    real_collect = lfc_capital_native.collect
    from tests.market.test_lfc_f2_capital_reads import rpc_packet
    calls = []
    def rpc(method, params):
        calls.append((method, params))
        if method == 'eth_getTransactionReceipt':
            assert params == [source['transaction_hash']]
            return proof['receipt']
        return rpc_packet('0x89' if method == 'eth_chainId' else '0x6')
    monkeypatch.setattr(lfc_capital_native, 'collect', lambda packet, ledger: real_collect(
        packet, ledger=ledger, rpc=rpc, sleep=lambda _: None))
    read['capital_activity'] = collect_window(read['capital_activity'], ledger=ledger)
    assert read['capital_activity']['rows'] == []
    assert read['capital_activity']['pending_native']['rows'] == [source]
    result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, read)
    assert result['cash_bridge_complete']
    before = ledger.path.read_bytes()
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read) == result
    assert ledger.path.read_bytes() == before
    for view in (ledger, Ledger.open(ledger.path, clock=clock.now)):
        book = CapitalBook(view)
        assert book.expected_cash() == 295_000_000
        assert book.figures()['funding_native'] == 300_000_000
        assert book.figures()['retained_gains_available_native'] == 0
    assert sum(method == 'eth_getTransactionReceipt' for method, _ in calls) == 1


def test_unknown_outgoing_cannot_be_crossed_by_a_session_anchor(tmp_path):
    from tests.market.test_lfc_review_b066_incoming import incoming
    ledger, baseline, clock, _ = fixture(tmp_path, personal=False)
    incoming(ledger, kind='WITHDRAWAL', missing=True)
    clock.value = ledger.clock() + timedelta(seconds=1)
    ledger.clock = clock.now
    read = observation(ledger, clock, positions={'denver': '20'}, cash='285')
    before = ledger.path.read_bytes()
    with pytest.raises(CapitalRefused, match='capital_unknown_outgoing_cost'):
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize('basis', ['gross', 'net_of_retained_gains'])
def test_late_paired_payout_reclassifies_captured_cash_and_owner_outflows_consume_gains(tmp_path, basis):
    from tests.market.test_lfc_redemption_native import paired
    from tests.market.test_lfc_f2_capital_reads import rpc_packet
    ledger, baseline, clock, _ = fixture(tmp_path, personal=False, bridge=False)
    source, proof, tokens = paired(auto=True)
    for index, token in enumerate(tokens):
        filled(ledger, f'pair-{index}', token=token, condition=source['condition_id'], price='.48')
    read = observation(ledger, clock, positions={'denver': '20', **{t: '20' for t in tokens}}, cash='270.8')
    synchronize(ledger, baseline, read, anchor_mode='enrollment', loss_basis=basis)
    clock.value += timedelta(minutes=1)
    source.update(timestamp=int(clock.now().timestamp()), token_id=tokens[0], usdc_size='10')
    proof.update(rows=[source], rows_sha256=digest([source]))
    record_activity(ledger, source, native_evidence={**proof, 'receipt': rpc_packet(None)})
    clock.value += timedelta(seconds=1)
    read = observation(ledger, clock, positions={'denver': '20', tokens[1]: '20'}, cash='290.8')
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session', loss_basis=basis)
    book = CapitalBook(ledger)
    assert book.external == 20_000_000 and book.expected_cash() == 290_800_000
    key = next(k for k, item in book.activities.items() if item['type'] == 'REDEEM')
    ledger.record('capital_resolution', source=source, source_sha256=digest(source),
                  previous_source_sha256=book.sources[key], native_evidence=proof)
    for view in (ledger, Ledger.open(ledger.path, clock=clock.now)):
        book = CapitalBook(view)
        assert book.expected_cash() == 290_800_000
        assert book.external == 0 and book.profit == 10_400_000
        assert book.figures(loss_basis=basis)['headroom_native'] == (290_000_000 if basis != 'gross' else 280_400_000)
        assert expected_inventory(view, book.inventory_anchor, book) == {'denver': '20'}
    clock.value += timedelta(days=1)
    withdrawn = observation(ledger, clock, positions={'denver': '20'}, cash='280.4')
    synchronize(ledger, book.inventory_anchor, withdrawn, anchor_mode='session', loss_basis=basis)
    clock.value += timedelta(days=1)
    deposited = observation(ledger, clock, positions={'denver': '20'}, cash='380.4')
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, deposited, anchor_mode='session', loss_basis=basis)
    for view in (ledger, Ledger.open(ledger.path, clock=clock.now)):
        book = CapitalBook(view)
        figures = book.figures(loss_basis=basis)
        assert figures['retained_gains_available_native'] == 0
        assert figures['headroom_native'] == 280_400_000
        assert book.external == 100_000_000 and book.costs == 0
        with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
            book.gate(reserve='280.400001', available_cash='380.4', loss_basis=basis)


def test_zero_proved_incoming_cannot_unquarantine_an_owner_deposit(tmp_path):
    from tests.market.test_lfc_review_b066_incoming import incoming, resolve
    from tests.market.test_lfc_f2_capital_reads import rpc_packet
    ledger, baseline, clock, _ = fixture(tmp_path, personal=False)
    clock.value += timedelta(days=1)
    withdrawn = observation(ledger, clock, positions={'denver': '20'}, cash='190')
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, withdrawn, anchor_mode='session')
    # The old label says five. Actual native proof will establish zero. An
    # unrelated owner deposit supplies the observed five in this snapshot.
    source, proof = incoming(ledger, kind='DEPOSIT', missing=True, nonce=86401)
    clock.value = ledger.clock() + timedelta(seconds=1)
    ledger.clock = clock.now
    read = observation(ledger, clock, positions={'denver': '20'}, cash='195')
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    receipt = json.loads(proof['receipt']['raw_response'])['result']
    receipt['logs'] = []
    proof['receipt'] = rpc_packet(receipt)
    resolve(ledger, source, proof)
    for view in (ledger, Ledger.open(ledger.path, clock=clock.now)):
        book = CapitalBook(view)
        assert book.expected_cash() == 195_000_000 and book.external == 5_000_000
        with pytest.raises(CapitalRefused, match='capital_spendable_cash'):
            book.gate(reserve='190.000001', available_cash='195')


def test_pre_enrollment_campaign_auto_redemption_bootstraps_without_250_personal_receipts(tmp_path, monkeypatch):
    from tests.market.test_lfc_redemption_native import paired
    from tests.market.test_lfc_f2_capital_reads import rpc_packet
    from weather.market import lfc_capital_native
    from weather.market.lfc_f2_wallet_reads import bootstrap_scope, collect_window
    source, proof, tokens = paired(auto=True)
    clock = Clock()
    clock.value = NOW
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=clock.now, maker_address=MAKER)
    baseline = take_baseline(label='t40', now=clock.now(), maker_address=MAKER, open_orders=[],
        positions=[{'asset': tokens[1], 'size': '20', 'conditionId': source['condition_id']}], available_collateral='300')
    write_baseline(tmp_path, baseline, ledger)
    filled(ledger, 'f0', token=tokens[0], condition=source['condition_id'])
    source['timestamp'] = int((NOW + timedelta(minutes=90)).timestamp())
    proof.update(rows=[source], rows_sha256=digest([source]))
    personal = []
    for index in range(250):
        row = activity(cash='1', size='0', kind='DEPOSIT', token='', tx=f'personal-{index}')
        row.update(timestamp=int((NOW + timedelta(minutes=30)).timestamp()), condition_id='unrelated-nfl')
        personal.append(row)
    clock.value += timedelta(hours=2)
    read = observation(ledger, clock, positions={'personal-nfl': '10'}, cash='310')
    scope = bootstrap_scope(ledger, read['positions'])
    assert scope['tokens'] == [tokens[0]]
    read['capital_activity']['bootstrap_scope'] = scope
    read['capital_activity']['bootstrap_activity'] = read_activity(MAKER, scope['start'],
        read['capital_activity']['scope']['end'], get=lambda *a: packet(personal + [source]), sleep=lambda _: None)
    calls = []
    def rpc(method, params):
        calls.append((method, params))
        if method == 'eth_getTransactionReceipt':
            assert params == [source['transaction_hash']]
            return proof['receipt']
        return rpc_packet('0x89' if method == 'eth_chainId' else '0x6')
    real_collect = lfc_capital_native.collect
    monkeypatch.setattr(lfc_capital_native, 'collect', lambda packet, ledger: real_collect(
        packet, ledger=ledger, rpc=rpc, sleep=lambda _: None))
    read['capital_activity'] = collect_window(read['capital_activity'], ledger=ledger)
    result = synchronize(ledger, baseline, read, anchor_mode='enrollment')
    assert result['cash_bridge_complete'] and result['inventory']['changed'] == []
    book = CapitalBook(ledger)
    assert book.inventory_anchor['positions'] == {'personal-nfl': '10'}
    assert book.returned_principal == 10_000_000 and book.profit == 10_000_000
    assert book.figures()['funding_native'] == 300_000_000
    assert sum(method == 'eth_getTransactionReceipt' for method, _ in calls) == 1
    assert synchronize(ledger, book.inventory_anchor, read) == result
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == book.figures()


@pytest.mark.parametrize('role', ['MAKER', 'TAKER'])
def test_bootstrap_refuses_foreign_same_campaign_token_trades_after_its_intent(tmp_path, role):
    from weather.market.lfc_f2_wallet_reads import require_bootstrap_trades
    ledger, baseline, clock, read = fixture(tmp_path, bridge=False)
    trade = {'trader_side': role, 'token_id': 'denver', 'status': 'CONFIRMED',
             'matched_at': (NOW + timedelta(seconds=1)).isoformat(), 'taker_order_id': 'foreign',
             'maker_orders': [{'order_id': 'foreign', 'token_id': 'denver', 'maker_address': MAKER}]}
    with pytest.raises(CapitalRefused, match='f2_bootstrap_campaign_trade'):
        require_bootstrap_trades(ledger, [trade], ['denver'])
    trade['matched_at'] = (NOW - timedelta(days=1)).isoformat()
    require_bootstrap_trades(ledger, [trade], ['denver'])
    trade.update(matched_at=(NOW + timedelta(seconds=1)).isoformat(), status='FAILED')
    require_bootstrap_trades(ledger, [trade], ['denver'])
