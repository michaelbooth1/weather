"""Guards: T117 exact redemption against a truncated inventory anchor.

All quantities, identities and native receipt events are synthetic.
"""
from datetime import timedelta
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import Clock
from tests.market.test_lfc_f2_capital import MAKER, NOW, activity, filled
from tests.market.test_lfc_f2_capital_reads import rpc_packet
from tests.market.test_lfc_f2_inventory_b080 import observation
from tests.market.test_lfc_f2_native import TX, log, proof
from tests.market.test_lfc_redemption_native import event
from weather.market.lfc_capital import CapitalBook, record_activity
from weather.market.lfc_capital_reads import synchronize
from weather.market.lfc_f2_inventory import expected_inventory, inventory
from weather.market.lfc_ledger import Ledger, take_baseline, write_baseline
from weather.market.lfc_redemption_native import MODULES, PM, POSITION, SINGLE, ZERO


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
