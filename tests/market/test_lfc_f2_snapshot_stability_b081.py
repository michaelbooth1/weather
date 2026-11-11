"""Guards: B081 anchors require coherent gross-flow and activity snapshots."""
from datetime import timedelta
from copy import deepcopy

import pytest

from tests.market.test_lfc_f2_inventory_b080 import fixture, observation
from tests.market.test_lfc_f2_personal_cash_b081 import gained_wallet, owner_trade
from tests.market.test_lfc_f2_capital_reads import native_packet, packet
from tests.market.test_lfc_redemption_native import paired
from weather.market.lfc_capital import CapitalBook, CapitalRefused
from weather.market.lfc_capital_reads import read_activity, synchronize
from weather.market.mm_stage2_hold import digest


def test_already_visible_owner_redemption_cannot_bind_pre_redemption_positions(tmp_path):
    ledger, baseline, clock, _ = fixture(tmp_path, personal=False, bridge=False)
    source, proof, tokens = paired(auto=True)
    positions = {'denver': '20', **{token: '20' for token in tokens}}
    synchronize(ledger, baseline, observation(ledger, clock, positions=positions, cash='290'), anchor_mode='enrollment')
    clock.value += timedelta(days=1)
    read = observation(ledger, clock, positions=positions, cash='290')
    source['timestamp'] = int(clock.now().timestamp())
    proof.update(rows=[source], rows_sha256=digest([source]))
    raw = read_activity(read['maker_address'], read['capital_activity']['scope']['start'], source['timestamp'],
        get=lambda *a: packet([source]), sleep=lambda _: None)
    read['capital_activity'] = {**native_packet(raw), 'native_receipts': {source['transaction_hash']: proof}}
    clock.value += timedelta(seconds=2)
    read['ended_at_utc'] = clock.now().isoformat()
    before = ledger.path.read_bytes()
    with pytest.raises(CapitalRefused, match='f2_anchor_snapshot_pending'):
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    assert ledger.path.read_bytes() == before
    after = observation(ledger, clock, positions={'denver': '20'}, cash='310')
    after['capital_activity'] = {**native_packet(read_activity(read['maker_address'],
        read['capital_activity']['scope']['start'], int(clock.now().timestamp()),
        get=lambda *a: packet([source]), sleep=lambda _: None)),
        'native_receipts': {source['transaction_hash']: proof}}
    result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, after, anchor_mode='session')
    assert result['cash_bridge_complete'] and result['inventory']['changed'] == []
    assert CapitalBook(ledger).external == 20_000_000


def test_confirmed_trade_metadata_update_does_not_redecide_cash(tmp_path):
    ledger, clock, read = gained_wallet(tmp_path)
    read['trades'].extend([owner_trade(clock, 'BUY', seconds=2), owner_trade(clock, 'SELL')])
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    figures = CapitalBook(ledger).figures(loss_basis='net_of_retained_gains')
    clock.value += timedelta(seconds=1)
    after = observation(ledger, clock, positions={'denver': '20', 'owner-new-nfl': '20'}, cash='290.8')
    after['trades'] = deepcopy(read['trades'])
    after['trades'][-1]['updated_at'] = clock.now().isoformat()
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, after, anchor_mode='session')
    assert CapitalBook(ledger).figures(loss_basis='net_of_retained_gains') == figures
    assert len(CapitalBook(ledger).personal_trades) == 2
