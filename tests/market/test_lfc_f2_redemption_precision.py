"""Guards: T117 exact redemption against a truncated inventory anchor, and
B090-K3 owner-only (personal) AutoRedeemer burns whose exact 6-decimal
quantity exceeds the anchor's 4-decimal positions report by under 0.0001.

All quantities, identities and native receipt events are synthetic.
"""
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import Clock
from tests.market.test_lfc_f2_capital import MAKER, NOW, activity, filled
from tests.market.test_lfc_f2_capital_reads import rpc_packet
from tests.market.test_lfc_f2_inventory_b080 import observation
from tests.market.test_lfc_f2_native import BLOCK, TX, log, proof
from tests.market.test_lfc_f2_overlap_b082 import feed
from tests.market.test_lfc_redemption_native import event
from weather.market.lfc_accounting import inventory_delta
from weather.market.lfc_capital import CapitalBook, CapitalRefused, native, normalize_activity, record_activity
from weather.market.lfc_capital_reads import synchronize
from weather.market.lfc_f2_inventory import expected_inventory, inventory
from weather.market.lfc_ledger import Ledger, take_baseline, write_baseline
from weather.market.lfc_redemption_native import AUTO, AUTO_POSITION, MODULES, PM, POSITION, SINGLE, ZERO

PERSONAL = ('101', '102')  # Owner-only tokens; the campaign lot is 'denver'.


@pytest.mark.parametrize('mode', ['idle', 'session'])
@pytest.mark.parametrize('reopen', [False, True])
def test_exact_native_redemption_after_truncated_anchor(tmp_path, mode, reopen):
    clock = Clock()
    clock.value = NOW
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=clock.now, maker_address=MAKER)
    baseline = take_baseline(label='t40', now=clock.now(), maker_address=MAKER,
        positions=[], open_orders=[], available_collateral='300')
    write_baseline(tmp_path, baseline, ledger)
    filled(ledger, 'fractional', token='101', size='12.345678')
    read = observation(ledger, clock, positions={'101': '12.3456'}, cash='293.827161')
    synchronize(ledger, baseline, read, anchor_mode='enrollment')
    anchor = CapitalBook(ledger).inventory_anchor
    assert anchor['positions'] == {'101': '12.3456'}
    assert anchor['campaign_quantities'] == {'101': '12.345678'}

    clock.value += timedelta(minutes=1)
    source = activity(cash='12.345678', size='12.345678', token='101', tx=TX)
    source['timestamp'] = int(clock.now().timestamp())
    module = sorted(MODULES)[0]
    native = proof([source], incoming=12_345_678)
    logs = [
        event(PM, SINGLE, [MAKER, MAKER, module], ['uint256', 'uint256'], [101, 12_345_678], 0),
        event(PM, SINGLE, [module, module, ZERO], ['uint256', 'uint256'], [101, 12_345_678], 1),
        event(module, POSITION, [MAKER, 101, MAKER], ['uint256', 'uint256'], [12_345_678, 12_345_678], 2),
        log(12_345_678, index=3),
    ]
    receipt = native['receipt']['raw_response']
    native['receipt'] = rpc_packet({**json.loads(receipt)['result'], 'logs': logs})
    record_activity(ledger, source, native_evidence=native)
    if reopen:
        ledger = Ledger.open(ledger.path, clock=clock.now)
    book = CapitalBook(ledger)
    assert book.removed == {'101': Decimal('12.345678')}
    assert len(book.removal_events) == 1
    assert book.removal_events[0]['outside_quantity'] == '0'
    assert book.returned_principal == 6_172_839
    assert book.profit == 6_172_839
    assert book.losses == 0
    assert book.lots['fractional']['remaining_quantity'] == 0
    assert book.lots['fractional']['remaining_basis'] == 0
    assert expected_inventory(ledger, anchor, book) == {}

    read = observation(ledger, clock, positions={}, cash='306.172839')
    result = synchronize(ledger, anchor, read, anchor_mode=mode)
    assert result['cash_bridge_complete'] and result['inventory']['changed'] == []
    before = CapitalBook(ledger).figures()
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode=mode)
    replayed = CapitalBook(Ledger.open(ledger.path, clock=clock.now))
    assert replayed.figures() == before
    assert len(replayed.removal_events) == 1


@pytest.mark.parametrize('excess', ['0.000099', '0.0001', '0.000101', '1'])
def test_negative_redemption_scope_keeps_strict_reporting_boundary(excess):
    ledger = SimpleNamespace(rows=[])
    anchor = {'positions': {'token': '1'}, 'filled_totals': {}, 'removed_totals': {}, 'ledger_cut': 0}
    book = SimpleNamespace(removed={'token': Decimal('1') + Decimal(excess)})
    if excess == '0.000099':
        assert expected_inventory(ledger, anchor, book) == {}
    else:
        with pytest.raises(ValueError, match='inventory_redemption_scope'):
            expected_inventory(ledger, anchor, book)


def test_missing_holding_without_redemption_still_changes_inventory():
    ledger = SimpleNamespace(rows=[])
    anchor = {'positions': {'token': '12.3456'}, 'filled_totals': {}, 'removed_totals': {}, 'ledger_cut': 0}
    book = SimpleNamespace(removed={})
    result = inventory(ledger, anchor, {}, book)
    assert result['changed'] == ['token']
    assert result['missing_or_below_visibility'] == ['token']


def personal_wallet(tmp_path, held):
    """One exact campaign lot plus owner-only holdings reported to 4 decimals."""
    clock = Clock()
    clock.value = NOW
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=clock.now, maker_address=MAKER)
    baseline = take_baseline(label='t40', now=clock.now(), maker_address=MAKER,
        positions=[], open_orders=[], available_collateral='300')
    write_baseline(tmp_path, baseline, ledger)
    filled(ledger, 'campaign', token='denver')
    read = observation(ledger, clock, positions={'denver': '20', **{token: held for token in PERSONAL}}, cash='290')
    synchronize(ledger, baseline, read, anchor_mode='enrollment')
    anchor = CapitalBook(ledger).inventory_anchor
    assert anchor['positions'] == {'denver': '20', **{token: held for token in PERSONAL}}
    assert anchor['campaign_quantities'] == {'denver': '20'}
    clock.value += timedelta(minutes=5)
    return ledger, clock


def row_burn(ledger, clock, size, *, token='101'):
    """Activity row only, no receipt: the burned size is the row's exact size."""
    source = activity(cash=size, size=size, token=token, tx='auto-owner-' + token)
    source['condition_id'] = 'owner-condition'
    source['timestamp'] = int(clock.now().timestamp())
    record_activity(ledger, source)
    return normalize_activity(source)['id']


def receipt_burn(clock, amount, *, ago=30):
    """AutoRedeemer receipt for both owner tokens; 102 is the zero-payout loser."""
    source = json.loads((Path(__file__).parents[1] / 'fixtures/lfc/paired_redeem_v2.json').read_text())
    size = str(Decimal(amount) / 10**6)
    source.update(timestamp=int(clock.now().timestamp()) - ago, size=size, usdc_size=size)
    module, logs = sorted(MODULES)[0], []
    for token, payout in zip(map(int, PERSONAL), (amount, 0)):
        logs.append(event(PM, SINGLE, [AUTO, MAKER, module], ['uint256', 'uint256'], [token, amount], len(logs)))
        logs.append(event(PM, SINGLE, [module, module, ZERO], ['uint256', 'uint256'], [token, amount], len(logs)))
        logs.append(event(module, POSITION, [AUTO, token, AUTO], ['uint256', 'uint256'], [amount, payout], len(logs)))
        if payout:
            logs.append(log(payout, index=len(logs)))
        logs.append(event(AUTO, AUTO_POSITION, [MAKER, token], ['uint256'], [payout], len(logs)))
    evidence = proof([source])
    evidence.update(receipt=rpc_packet({'transactionHash': TX, 'blockHash': BLOCK, 'blockNumber': '0x123',
                                        'status': '0x1', 'logs': logs}), ctf_views={})
    return source, evidence


# Truncated (12.345678 -> 12.3456), its 0.000099 boundary, rounded up (12.3457)
# and rounded down (12.345638 -> 12.3456) positions reports of one exact burn.
SUB_REPORTING = [('12.3456', '12.345678'), ('12.3456', '12.345699'), ('12.3457', '12.345678'),
                 ('12.3456', '12.345638')]


@pytest.mark.parametrize('mode', [None, 'idle', 'session'])
@pytest.mark.parametrize('path', ['row', 'receipt'])
@pytest.mark.parametrize('held,burn', SUB_REPORTING)
def test_personal_burn_within_reporting_precision_reconciles_owner_side(tmp_path, held, burn, path, mode):
    ledger, clock = personal_wallet(tmp_path, held)
    amount = native(burn)
    cash = str(Decimal('290') + Decimal(burn))
    if path == 'row':
        key, burned = row_burn(ledger, clock, burn), ['101']
        read = observation(ledger, clock, positions={'denver': '20', '102': held}, cash=cash)
    else:
        source, evidence = receipt_burn(clock, amount)
        key, burned = normalize_activity(source)['id'], list(PERSONAL)
        read = feed(ledger, clock, source, evidence, {'denver': '20'}, cash)
    result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode=mode)
    assert result['cash_bridge_complete'] and result['inventory']['changed'] == []
    book = CapitalBook(ledger)
    assert book.unknown == []
    assert book.redemptions[key]['unallocated'] == [] and book.redemptions[key]['outside_campaign'] is True
    assert {token: book.removed[token] for token in burned} == {token: Decimal(burn) for token in burned}
    assert sorted((row['token_id'], row['quantity'], row['outside_quantity']) for row in book.removal_events) == [
        (token, burn, burn) for token in burned]
    # The whole payout is owner cash; no campaign lot, basis, loss or gain moves.
    assert book.external == amount and book.profit == 0 and book.losses == 0 and book.returned_principal == 0
    assert book.allocations == []
    assert book.lots['campaign']['remaining_quantity'] == 20
    if path == 'receipt':
        assert sum(row.get('owner_cash_native', 0) for row in book.pool_movements
                   if row['activity_id'] == key) == amount
    before = book.figures()
    synchronize(ledger, book.inventory_anchor, read, anchor_mode=mode)
    replayed = CapitalBook(Ledger.open(ledger.path, clock=clock.now))
    assert replayed.figures() == before
    assert len(replayed.removal_events) == len(burned)


@pytest.mark.parametrize('burn', ['12.3457', '12.345701', '13'])
def test_personal_burn_at_or_beyond_reporting_precision_still_refuses(tmp_path, burn):
    ledger, clock = personal_wallet(tmp_path, '12.3456')
    key = row_burn(ledger, clock, burn)
    book = CapitalBook(ledger)
    assert book.redemptions[key]['unallocated'] == [{'token_id': '101', 'reason': 'unproved_or_pre_snapshot_redemption'}]
    assert key in book.unknown and '101' not in book.removed and book.removal_events == []
    read = observation(ledger, clock, positions={'denver': '20', '102': '12.3456'},
                       cash=str(Decimal('290') + Decimal(burn)))
    with pytest.raises(CapitalRefused, match='capital_inventory_unreconciled'):
        synchronize(ledger, book.inventory_anchor, read)


@pytest.mark.parametrize('burn,accepted', [('12.345678', True), ('12.345679', False), ('12.345728', False)])
def test_campaign_lot_capacity_stays_exact_against_a_truncated_anchor(tmp_path, burn, accepted):
    clock = Clock()
    clock.value = NOW
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=clock.now, maker_address=MAKER)
    baseline = take_baseline(label='t40', now=clock.now(), maker_address=MAKER,
        positions=[], open_orders=[], available_collateral='300')
    write_baseline(tmp_path, baseline, ledger)
    filled(ledger, 'fractional', token='101', size='12.345678')
    synchronize(ledger, baseline, observation(ledger, clock, positions={'101': '12.3456'}, cash='293.827161'),
                anchor_mode='enrollment')
    clock.value += timedelta(minutes=1)
    source = activity(cash=burn, size=burn, token='101', tx='auto-campaign')
    source['timestamp'] = int(clock.now().timestamp())
    record_activity(ledger, source)
    book = CapitalBook(ledger)
    redemption = book.redemptions[normalize_activity(source)['id']]
    if accepted:
        assert redemption['unallocated'] == [] and book.removed == {'101': Decimal(burn)}
        assert book.lots['fractional']['remaining_quantity'] == 0
        assert book.removal_events[0]['outside_quantity'] == '0'
    else:
        # A campaign token never borrows the owner-only reporting allowance.
        assert redemption['unallocated'] == [{'token_id': '101', 'reason': 'unproved_or_pre_snapshot_redemption'}]
        assert book.removed == {} and book.allocations == []
        assert book.lots['fractional']['remaining_quantity'] == Decimal('12.345678')


@pytest.mark.parametrize('excess,clean', [('0.000078', True), ('0.000099', True), ('0.0001', False), ('0.000178', False)])
def test_t40_start_gate_inventory_keeps_strict_reporting_bound_for_personal_burns(tmp_path, excess, clean):
    """lfc_campaign_runtime start_gates compares against the prepared T-40 file."""
    ledger, clock = personal_wallet(tmp_path, '12.3456')
    burn = '12.345678'
    t40 = take_baseline(label='t40', now=clock.now(), maker_address=MAKER,
        positions=[{'asset': 'denver', 'size': '20', 'conditionId': 'c'},
                   {'asset': '101', 'size': str(Decimal(burn) - Decimal(excess)), 'conditionId': 'owner-condition'},
                   {'asset': '102', 'size': '12.3456', 'conditionId': 'owner-condition'}],
        open_orders=[], available_collateral='290')
    write_baseline(tmp_path, t40, ledger)
    clock.value += timedelta(minutes=1)
    row_burn(ledger, clock, burn)
    assert CapitalBook(ledger).removed == {'101': Decimal(burn)}
    if clean:
        result = inventory_delta(ledger, t40, {'denver': '20', '102': '12.3456'})
        assert result['changed'] == [] and '101' not in result['expected']
        assert inventory_delta(ledger, t40, {'denver': '20', '102': '12.3455'})['changed'] == ['102']
    else:
        with pytest.raises(ValueError, match='inventory_redemption_scope'):
            inventory_delta(ledger, t40, {'denver': '20', '102': '12.3456'})


def test_late_personal_receipt_against_lagging_endpoint_catches_up_by_reported_quantity(tmp_path):
    """Read-bound owner catch-up compares 4-decimal reads only; the receipt bounds it."""
    held, amount = '12.3456', 12_345_678
    ledger, clock = personal_wallet(tmp_path, held)
    source, evidence = receipt_burn(clock, amount, ago=20)
    cash = str(Decimal('290') + Decimal(amount) / 10**6)
    lagging = {'denver': '20', **{token: held for token in PERSONAL}}
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
                observation(ledger, clock, positions=lagging, cash=cash), anchor_mode='session')
    clock.value += timedelta(seconds=2)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, feed(ledger, clock, source, evidence, lagging, cash))
    clock.value += timedelta(seconds=2)
    result = synchronize(ledger, CapitalBook(ledger).inventory_anchor,
                         feed(ledger, clock, source, evidence, {'denver': '20'}, cash))
    assert result['inventory']['changed'] == []
    rows = ledger.event_rows('capital_owner_inventory')
    assert sorted((row['token_id'], Decimal(row['before']), Decimal(row['after'])) for row in rows) == [
        (token, Decimal(held), 0) for token in PERSONAL]
    book = CapitalBook(ledger)
    assert book.profit == 0 and book.losses == 0 and not set(PERSONAL) & set(book.removed)
    assert expected_inventory(ledger, book.inventory_anchor, book) == {'denver': '20'}
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == book.figures()
