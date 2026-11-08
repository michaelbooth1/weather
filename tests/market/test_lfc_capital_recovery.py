"""Synthetic ordinary cash events must not permanently stop the sleeve.

Guards: B046 A4-A7 / D4-2/3/4/8; no API, RPC, credential or account calls.
"""
from copy import deepcopy
from datetime import timedelta

import pytest

from tests.market.test_lfc_f2_capital import MAKER, NOW, activity, filled, install, ledger_at
from tests.market.test_lfc_f2_capital_reads import packet, native_packet, read_activity, setup_read, rpc_packet
from tests.market.test_lfc_f2_native import TX, proof
from tests.market.test_lfc_redemption_native import paired
from weather.market.lfc_capital import ASSET, CapitalBook, CapitalRefused, label_native, normalize_activity, record_activity
from weather.market.lfc_capital_reads import synchronize
from weather.market.lfc_ledger import Ledger
from weather.market.mm_stage2_hold import digest


@pytest.mark.parametrize('reverse', [False, True])
def test_two_city_unknown_redemptions_resolve_the_whole_transaction_before_inventory_check(tmp_path, reverse):
    from weather.market.lfc_ledger import take_baseline, write_baseline
    from tests.market.test_lfc_f2_redemption import observed_packet, set_cash
    row, native, tokens = paired()
    row.update(token_id=tokens[0], condition_id='denver')
    second = {**row, 'token_id': tokens[1], 'condition_id': 'toronto', 'usdc_size': '0'}
    sources = [second, row] if reverse else [row, second]
    native.update(rows=sources, rows_sha256=digest(sources))
    ledger = ledger_at(tmp_path)
    baseline = take_baseline(label='t40', now=NOW, maker_address=MAKER, positions=[],
                             open_orders=[], available_collateral='300')
    write_baseline(tmp_path, baseline, ledger)
    filled(ledger, 'denver', token=tokens[0], condition='denver', price='.40')
    filled(ledger, 'toronto', token=tokens[1], condition='toronto', price='.55')
    read = {'complete': True, 'maker_address': MAKER, 'open_orders': [],
        'positions': [{'asset': token, 'size': '20'} for token in tokens], 'ended_at_utc': NOW.isoformat(),
        'capital_activity': observed_packet([], {})}
    set_cash(read, '281')
    synchronize(ledger, baseline, read)
    read.update(positions=[], capital_activity=observed_packet(sources, {TX: {**native, 'receipt': rpc_packet(None)}}))
    set_cash(read, '301')
    assert synchronize(ledger, baseline, read)['returned_principal_native'] == 0
    read['capital_activity'] = observed_packet(sources, {TX: native})
    figures = synchronize(ledger, baseline, read)
    assert figures['returned_principal_native'] == 8_000_000
    assert figures['realized_principal_losses_native'] == 11_000_000
    assert figures['segregated_profit_native'] == 12_000_000
    assert figures['inventory']['changed'] == [] and figures['cash_bridge_complete']
    assert not CapitalBook(ledger).unknown
    assert synchronize(ledger, baseline, read) == figures


@pytest.mark.parametrize('withdrawal', ['250', '300', '1000'])
@pytest.mark.parametrize('seen_late', [False, True])
def test_prebridge_withdrawals_do_not_charge_the_new_sleeve(tmp_path, withdrawal, seen_late):
    ledger = ledger_at(tmp_path)
    filled(ledger, 'legacy', size='20', price='.75')
    reward = activity(cash='5', kind='REWARD', size='0', tx='reward')
    record_activity(ledger, reward)
    row = activity(cash=withdrawal, kind='WITHDRAWAL', size='0', tx='withdrawal')
    row['timestamp'] += 1
    ledger.clock = lambda: NOW + timedelta(seconds=10)
    if not seen_late: record_activity(ledger, row)
    install(ledger, cash='920')
    if seen_late: record_activity(ledger, row)
    book = CapitalBook(ledger)
    assert book.costs == book.incentives == 0
    assert book.figures()['funding_native'] == 300_000_000
    assert book.figures()['headroom_native'] == 285_000_000
    assert book.expected_cash() == 920_000_000
    assert CapitalBook(Ledger.open(ledger.path, clock=ledger.clock)).figures() == book.figures()


def test_batched_unknown_reward_and_rebate_are_quarantined_without_blocking_bridge(tmp_path):
    ledger, baseline, read = setup_read(tmp_path)
    first = {**activity(cash='3', size='0', kind='REWARD', tx=TX)}
    second = {**activity(cash='1', size='0', kind='MAKER_REBATE', tx=TX)}
    sources = [first, second]
    raw = native_packet(read_activity(MAKER, int(NOW.timestamp()), int(NOW.timestamp()),
                        get=lambda *a: packet(sources), sleep=lambda _: None))
    raw['native_receipts'] = {TX: proof(sources, incoming=4_000_000)}
    read.update(capital_activity=raw, balances={'available_collateral': '920', 'assets': {ASSET: '920'},
                 'collateral_evidence': {'balance': '920000000'}})
    result = synchronize(ledger, baseline, read)
    assert result['funding_native'] == 300_000_000 and result['cash_bridge_complete']
    book = CapitalBook(ledger)
    assert book.unknown and not book.blocking_unknown()
    assert result['quarantined_unknown_incoming_native'] == 4_000_000
    assert book.returned_principal == 0 and book.incentives == 0
    book.gate(reserve='1', available_cash='920')


def test_unknown_initial_payout_label_cannot_become_owner_funding(tmp_path):
    ledger, baseline, read = setup_read(tmp_path)
    row = activity(cash='20', tx=TX)
    raw = native_packet(read_activity(MAKER, int(NOW.timestamp()), int(NOW.timestamp()),
                        get=lambda *a: packet([row]), sleep=lambda _: None))
    raw['native_receipts'] = {TX: {**proof([row]), 'receipt': rpc_packet(None)}}
    read.update(positions=[], capital_activity=raw, balances={'available_collateral': '110', 'assets': {ASSET: '110'},
                 'collateral_evidence': {'balance': '110000000'}})
    result = synchronize(ledger, baseline, read)
    assert result['funding_native'] == 100_000_000 and result['headroom_native'] == 90_000_000
    assert result['returned_principal_native'] == 0
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        CapitalBook(ledger).gate(reserve='90.000001', available_cash='110')


def test_postbridge_unknown_income_never_funds_new_risk_or_permanently_blocks(tmp_path):
    ledger = ledger_at(tmp_path)
    install(ledger, cash='100')
    row = activity(cash='250', kind='REWARD', size='0', tx=TX)
    record_activity(ledger, row, native_evidence={**proof([row]), 'receipt': rpc_packet(None)})
    book = CapitalBook(ledger)
    assert book.figures()['funding_native'] == 100_000_000 and book.blocking_unknown() == []
    book.gate(reserve='100', available_cash='350')
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'): book.gate(reserve='100.000001', available_cash='350')
    ledger.record('capital_resolution', source=row, source_sha256=digest(row),
                  previous_source_sha256=book.sources[book.unknown[0]], native_evidence=proof([row], incoming=250_000_000))
    book = CapitalBook(ledger)
    assert not book.unknown and book.incentives == 250_000_000 and book.external == 0
    assert book.figures()['funding_native'] == 100_000_000


def test_unknown_outgoing_cash_still_refuses(tmp_path):
    ledger = ledger_at(tmp_path)
    install(ledger, cash='100')
    row = activity(cash='1', kind='WITHDRAWAL', size='0', tx=TX)
    record_activity(ledger, row, native_evidence={**proof([row]), 'receipt': rpc_packet(None)})
    with pytest.raises(CapitalRefused, match='capital_unknown_outgoing_cost'): CapitalBook(ledger).gate(reserve='1')


@pytest.mark.parametrize('amount,lower,held', [('6.6000000000000005', 6_600_000, 6_600_001),
    ('0.0000001', 0, 1), ('1.123456789', 1_123_456, 1_123_457)])
def test_api_labels_with_extra_decimals_round_toward_less_cash(amount, lower, held):
    assert label_native(amount) == lower and label_native(amount, quarantine=True) == held
    row = activity(cash=amount, kind='REWARD', size='0')
    assert normalize_activity(row)['cash_native'] == lower
    assert read_activity(MAKER, int(NOW.timestamp()), int(NOW.timestamp()),
                         get=lambda *a: packet([row]), sleep=lambda _: None)['complete']
