"""Guards: owner decision 2026-11-16, confirmed owner cash repays overdraw.

Synthetic account, trades, receipts and amounts; no external services.
"""
from datetime import timedelta
from decimal import Decimal
import json

import pytest

from tests.market.test_lfc_f2_cash_mirror_b082 import single_redemption
from tests.market.test_lfc_f2_capital import filled
from tests.market.test_lfc_f2_capital_reads import rpc_packet
from tests.market.test_lfc_f2_inventory_b080 import fixture, observation
from tests.market.test_lfc_f2_personal_cash_b081 import owner_trade
from tests.market.test_lfc_sleeve_cash_b090 import move
from weather.market.lfc_capital import CapitalBook, CapitalRefused, record_activity
from weather.market.lfc_capital_reads import synchronize
from weather.market.lfc_ledger import Ledger
from weather.market.mm_stage2_hold import digest


UNIT = 1_000_000


@pytest.mark.parametrize('role', ['MAKER', 'TAKER'])
@pytest.mark.parametrize('sale,repaid,external', [('60', 60, 0), ('100', 100, 0), ('150', 100, 50)])
def test_confirmed_sale_repays_only_outstanding_overdraw(tmp_path, role, sale, repaid, external):
    ledger, _, clock, _ = fixture(tmp_path, personal=False)
    before = CapitalBook(ledger).figures()
    clock.value += timedelta(hours=12)
    move(ledger, clock, kind='WITHDRAWAL', cash='100', tx='owner-debit')
    clock.value += timedelta(hours=12)
    trade = owner_trade(clock, 'SELL', role=role)
    if role == 'MAKER':
        trade['maker_orders'][0].update(price='.5', matched_amount=str(Decimal(sale) * 2))
    else:
        trade.update(price='.5', size=str(Decimal(sale) * 2))
    cash = str(Decimal('190') + Decimal(sale))
    read = observation(ledger, clock, positions={'denver': '20'}, cash=cash)
    read['trades'].append(trade)
    result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    assert result['cash_bridge_complete']
    book = CapitalBook(ledger)
    after = book.figures()
    assert after['owner_overdraw_outstanding_native'] == (100 - repaid) * UNIT
    assert after['owner_overdraw_repaid_native'] == repaid * UNIT
    assert book.external == external * UNIT
    for key in ('funding_native', 'charged_native', 'headroom_native', 'retained_gains_offset_native'):
        assert after[key] == before[key]
    assert book.profit == book.incentives == 0
    book.gate(reserve=str(190 + repaid), available_cash=cash)
    with pytest.raises(CapitalRefused):
        book.gate(reserve=str(Decimal(190 + repaid) + Decimal('.000001')), available_cash=cash)
    synchronize(ledger, book.inventory_anchor, read, anchor_mode='session')
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == after


def test_unattributed_snapshot_surplus_never_repays_and_deposit_still_does(tmp_path):
    ledger, _, clock, _ = fixture(tmp_path, personal=False)
    clock.value += timedelta(hours=12)
    move(ledger, clock, kind='WITHDRAWAL', cash='100', tx='owner-debit')
    clock.value += timedelta(hours=12)
    read = observation(ledger, clock, positions={'denver': '20'}, cash='240')
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    book = CapitalBook(ledger)
    assert book.external == 50 * UNIT
    assert book.owner_overdraw_outstanding == 100 * UNIT
    assert book.owner_overdraw_repaid == 0
    clock.value += timedelta(hours=1)
    move(ledger, clock, kind='DEPOSIT', cash='60', tx='owner-deposit')
    book = CapitalBook(ledger)
    assert book.owner_overdraw_outstanding == 40 * UNIT
    assert book.owner_overdraw_repaid == 60 * UNIT
    assert book.external == 50 * UNIT
    assert book.figures()['funding_native'] == 300 * UNIT


def test_native_personal_redemption_repays_without_creating_campaign_gain(tmp_path):
    ledger, baseline, clock, _ = fixture(tmp_path, personal=False, bridge=False)
    read = observation(ledger, clock, positions={'denver': '20', '101': '40'}, cash='290')
    synchronize(ledger, baseline, read, anchor_mode='enrollment')
    clock.value += timedelta(hours=12)
    move(ledger, clock, kind='WITHDRAWAL', cash='15', tx='owner-debit')
    clock.value += timedelta(hours=1)
    source, proof = single_redemption('101', '40', '40', '0x' + 'c' * 64, '0x' + '2' * 64)
    source['timestamp'] = int(clock.now().timestamp())
    proof.update(rows=[source], rows_sha256=digest([source]))
    record_activity(ledger, source, native_evidence=proof)
    for view in (ledger, Ledger.open(ledger.path, clock=clock.now)):
        book = CapitalBook(view)
        assert book.owner_overdraw_outstanding == 0
        assert book.owner_overdraw_repaid == 15 * UNIT
        assert book.external == 25 * UNIT
        assert book.profit == book.incentives == book.returned_principal == 0
        assert book.figures()['headroom_native'] == 290 * UNIT
        book.gate(reserve='290', available_cash='315')


def test_unallocated_native_redemption_remains_quarantined_owner_cash(tmp_path):
    ledger, _, clock, _ = fixture(tmp_path, personal=False)
    clock.value += timedelta(hours=12)
    move(ledger, clock, kind='WITHDRAWAL', cash='15', tx='owner-debit')
    clock.value += timedelta(hours=1)
    source, proof = single_redemption('101', '40', '40', '0x' + 'c' * 64, '0x' + '2' * 64)
    source['timestamp'] = int(clock.now().timestamp())
    proof.update(rows=[source], rows_sha256=digest([source]))
    record_activity(ledger, source, native_evidence=proof)
    book = CapitalBook(ledger)
    assert book.owner_overdraw_outstanding == 15 * UNIT
    assert book.owner_overdraw_repaid == 0
    assert book.external == 40 * UNIT
    assert book.figures()['proven_campaign_profit_cumulative_native'] == 0


def test_mixed_redemption_repays_only_the_proved_owner_allocation(tmp_path):
    ledger, baseline, clock, _ = fixture(tmp_path, personal=False, bridge=False)
    synchronize(ledger, baseline, observation(ledger, clock,
        positions={'denver': '20', '101': '20'}, cash='290'), anchor_mode='enrollment')
    clock.value += timedelta(hours=12)
    move(ledger, clock, kind='WITHDRAWAL', cash='25', tx='owner-debit')
    clock.value += timedelta(hours=1)
    tx = '0x' + '2' * 64
    source, proof = single_redemption('101', '20', '20', '0x' + 'c' * 64, tx)
    _, other = single_redemption('102', '10', '10', '0x' + 'c' * 64, tx)
    receipt = json.loads(proof['receipt']['raw_response'])['result']
    receipt['logs'].extend(json.loads(other['receipt']['raw_response'])['result']['logs'])
    for index, entry in enumerate(receipt['logs']):
        entry['logIndex'] = hex(index)
    source.update(timestamp=int(clock.now().timestamp()), usdc_size='30')
    proof.update(rows=[source], rows_sha256=digest([source]), receipt=rpc_packet(receipt))
    record_activity(ledger, source, native_evidence=proof)
    book = CapitalBook(ledger)
    assert book.owner_overdraw_repaid == 20 * UNIT
    assert book.owner_overdraw_outstanding == 5 * UNIT
    assert book.external == 10 * UNIT  # The unallocated part stays segregated.
    assert book.unknown
    assert book.profit == book.returned_principal == 0
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == book.figures()


def test_campaign_redemption_profit_does_not_repay_owner_overdraw(tmp_path):
    ledger, baseline, clock, _ = fixture(tmp_path, personal=False, bridge=False)
    filled(ledger, 'campaign-winner', token='101', condition='0x' + 'c' * 64)
    synchronize(ledger, baseline, observation(ledger, clock,
        positions={'denver': '20', '101': '20'}, cash='280'), anchor_mode='enrollment')
    clock.value += timedelta(hours=12)
    move(ledger, clock, kind='WITHDRAWAL', cash='15', tx='owner-debit')
    clock.value += timedelta(hours=1)
    source, proof = single_redemption('101', '20', '20', '0x' + 'c' * 64, '0x' + '2' * 64)
    source['timestamp'] = int(clock.now().timestamp())
    proof.update(rows=[source], rows_sha256=digest([source]))
    record_activity(ledger, source, native_evidence=proof)
    book = CapitalBook(ledger)
    assert book.owner_overdraw_outstanding == 15 * UNIT
    assert book.owner_overdraw_repaid == book.external == 0
    assert book.profit == book.returned_principal == 10 * UNIT
    assert book.figures()['funding_native'] == 300 * UNIT
