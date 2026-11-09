"""Synthetic native-unit sleeve witnesses; no account or public service.

Guards: B036 fixed total, legacy bridge, disjoint lots and no income-funded risk.
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from weather.market.lfc_capital import (CapitalBook, CapitalRefused, bridge, native, record_activity)
from weather.market.lfc_ledger import Ledger, LedgerCap, LedgerUnavailable, take_baseline, write_baseline
from weather.market.mm_stage2_hold import digest


NOW = datetime(2026, 11, 11, 14, tzinfo=timezone.utc)
MAKER = '0x' + 'a' * 40


def ledger_at(tmp_path):
    return Ledger.create(tmp_path / 'ledger.jsonl', clock=lambda: NOW, maker_address=MAKER)


def filled(ledger, key, *, size='20', price='.5', token='yes', condition='c', market_id=None):
    ledger.record('session_start', session_id=key, counted=True,
                  **({'market_id': market_id} if market_id is not None else {}))
    ledger.intent(session_id=key, intent_key=key, token_id=token, condition_id=condition, size=size,
                  price=price, fee_rate_bps='0')
    ledger.ack(key, 'order-' + key)
    ledger.terminal('order-' + key, {'id': 'order-' + key, 'status': 'MATCHED', 'size_matched': size}, source='fixture')
    ledger.record('session_end', session_id=key)


def install(ledger, cash='290', *, complete=True):
    book = CapitalBook(ledger)
    if book.anchor is None:
        positions = [{'asset': lot['token_id'], 'conditionId': lot['condition_id'], 'size': str(lot['quantity'])}
                     for lot in book.lots.values()]
        baseline = take_baseline(label='t40', now=ledger.clock(), maker_address=MAKER, positions=positions,
                                 open_orders=[], available_collateral=cash)
        write_baseline(ledger.path.parent, baseline, ledger)
        ledger.record('capital_anchor', baseline=baseline, baseline_sha256=digest(baseline))
        book = CapitalBook(ledger)
    from weather.market.lfc_capital import ASSET, prefix_inventory
    proof = {'complete': complete, 'legacy_L_native': native(ledger.L()), 'genesis_sha256': ledger.row_sha256(0),
             'baseline_sha256': digest(book.anchor), 'asset': ASSET, 'decimals': 6, 'cash_native': native(cash),
             'read_sha256': digest({'fixture_read': cash}), 'activity_packet_sha256': digest({'fixture': []}),
             'inventory': {'changed': [], 'expected': prefix_inventory(ledger, book.anchor, len(ledger.rows))}}
    return bridge(ledger, funding='300', cash=cash, proof=proof)


def activity(*, cash, size='20', token='yes', tx='tx', kind='REDEEM'):
    return {'proxy_wallet': MAKER, 'timestamp': int(NOW.timestamp()), 'condition_id': 'c',
            'type': kind, 'size': size, 'usdc_size': cash, 'transaction_hash': tx, 'token_id': token}


def test_loss_then_redemption_does_not_restore_lost_headroom(tmp_path):
    ledger = ledger_at(tmp_path)
    filled(ledger, 'loser')
    filled(ledger, 'winner', token='no')
    install(ledger, '280')
    record_activity(ledger, activity(cash='0'))
    record_activity(ledger, activity(cash='10', token='no', tx='winner'))
    figures = CapitalBook(ledger).figures()
    assert figures['realized_principal_losses_native'] == 10_000_000
    assert figures['headroom_native'] == 290_000_000
    assert ledger.L() == 20  # Original L is carried, never reset or netted.
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        CapitalBook(ledger).gate(reserve='290.000001', available_cash='1000')


def test_unknown_payout_returns_nothing(tmp_path):
    ledger = ledger_at(tmp_path)
    filled(ledger, 'lot')
    install(ledger)
    record_activity(ledger, activity(cash=None))
    figures = CapitalBook(ledger).figures()
    assert figures['headroom_native'] == 290_000_000
    assert figures['returned_principal_native'] == 0
    assert len(figures['unknown_payouts']) == 1


@pytest.mark.parametrize('before_bridge', [False, True])
def test_unknown_payout_later_known_releases_only_evidenced_principal_once(tmp_path, before_bridge):
    ledger = ledger_at(tmp_path)
    filled(ledger, 'lot')
    if not before_bridge:
        install(ledger)
    source = activity(cash=None)
    record_activity(ledger, source)
    if before_bridge:
        with pytest.raises(CapitalRefused, match='capital_bridge_unknown_cash'):
            install(ledger, cash='310')
    book = CapitalBook(ledger)
    assert book.figures()['headroom_native'] == (0 if before_bridge else 290_000_000)
    known = activity(cash='20')
    ledger.record('capital_resolution', source=known, source_sha256=digest(known),
                  previous_source_sha256=book.sources[next(iter(book.unknown))])
    if before_bridge:
        install(ledger, cash='310')
    book = CapitalBook(ledger)
    assert book.figures()['headroom_native'] == 300_000_000
    assert book.figures()['segregated_profit_native'] == 10_000_000
    assert book.expected_cash() == 310_000_000
    assert book.figures()['unknown_payouts'] == []
    with pytest.raises(LedgerUnavailable, match='capital_resolution_scope'):
        ledger.record('capital_resolution', source=known, source_sha256=digest(known),
                      previous_source_sha256=book.sources[next(iter(book.activities))])
    assert CapitalBook(Ledger.open(ledger.path, clock=lambda: NOW)).figures() == book.figures()


def test_unknown_outgoing_cost_blocks_new_orders_and_is_not_zero(tmp_path):
    ledger = ledger_at(tmp_path)
    install(ledger, cash='300')
    record_activity(ledger, activity(cash=None, size='0', kind='WITHDRAWAL'))
    with pytest.raises(CapitalRefused, match='capital_unknown_outgoing_cost'):
        CapitalBook(ledger).gate(reserve='1', available_cash='300')


def test_case_only_replayed_redemption_is_not_a_second_receipt(tmp_path):
    ledger = ledger_at(tmp_path)
    filled(ledger, 'lot')
    install(ledger)
    first = activity(cash='10', size='10', tx='0xabcdef')
    record_activity(ledger, first)
    replayed = {**first, 'transaction_hash': '0xABCDEF', 'proxy_wallet': MAKER.upper()}
    with pytest.raises(LedgerUnavailable, match='capital_activity_repeated'):
        record_activity(ledger, replayed)


def test_profitable_redemption_returns_only_basis_and_cash_excludes_profit(tmp_path):
    ledger = ledger_at(tmp_path)
    filled(ledger, 'lot')
    install(ledger)
    record_activity(ledger, activity(cash='20'))
    book = CapitalBook(ledger)
    assert book.figures()['returned_principal_native'] == 10_000_000
    assert book.figures()['segregated_profit_native'] == 10_000_000
    book.gate(reserve='300', available_cash='310')
    with pytest.raises(CapitalRefused, match='capital_cash_changed'):
        book.gate(reserve='300', available_cash='309.999999')
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        book.gate(reserve='300.000001', available_cash='1000')


def test_concurrent_reserve_and_ambiguous_intent_never_release_money(tmp_path):
    ledger = ledger_at(tmp_path)
    install(ledger, cash='300')
    ledger.record('session_start', session_id='first', counted=True)
    ledger.intent(session_id='first', intent_key='first', token_id='yes', condition_id='c', price='.5',
                  size='580', fee_rate_bps='0')
    assert CapitalBook(ledger).figures()['resting_reserve_native'] == 290_000_000
    ledger.record('session_start', session_id='second', counted=False)
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        ledger.intent(session_id='second', intent_key='second', token_id='no', condition_id='d', price='.5',
                      size='20.000002', fee_rate_bps='0')
    assert 'second' not in ledger.legs
    ledger.intent(session_id='second', intent_key='second', token_id='no', condition_id='d', price='.5',
                  size='20', fee_rate_bps='0')
    assert CapitalBook(ledger).figures()['charged_native'] == 300_000_000


def test_bridge_required_and_failed_reconciliation_creates_no_bridge(tmp_path):
    ledger = ledger_at(tmp_path)
    with pytest.raises(CapitalRefused, match='capital_bridge_required'):
        CapitalBook(ledger).gate(reserve='1')
    with pytest.raises(CapitalRefused, match='capital_bridge_unreconciled'):
        install(ledger, complete=False)
    assert CapitalBook(ledger).bridge is None
    proof = {'complete': True, 'legacy_L_native': 1, 'genesis_sha256': ledger.row_sha256(0)}
    with pytest.raises(LedgerUnavailable, match='capital_bridge_unreconciled'):
        bridge(ledger, funding='300', cash='300', proof=proof)
    assert CapitalBook(ledger).bridge is None


def test_bridge_no_reset_on_date_config_or_reboot(tmp_path):
    ledger = ledger_at(tmp_path)
    filled(ledger, 'lot')
    install(ledger)
    record_activity(ledger, activity(cash='0'))
    reopened = Ledger.open(ledger.path, clock=lambda: NOW)
    assert CapitalBook(reopened).figures() == CapitalBook(ledger).figures()
    with pytest.raises(LedgerUnavailable, match='capital_bridge_already_exists'):
        install(reopened, cash='300')
    assert CapitalBook(Ledger.open(ledger.path, clock=lambda: NOW)).figures()['headroom_native'] == 290_000_000
    with pytest.raises(LedgerCap, match='capital_requires_native_gate'):
        reopened.post_gate(reserve='1')


def test_partial_redemptions_and_incentives_never_double_credit(tmp_path):
    ledger = ledger_at(tmp_path)
    filled(ledger, 'lot', price='.333333')
    install(ledger, '293.33334')
    first = activity(cash='10', size='10')
    record_activity(ledger, first)
    record_activity(ledger, activity(cash='10', size='10', tx='second'))
    record_activity(ledger, activity(cash='5', size='0', tx='reward', kind='REWARD'))
    record_activity(ledger, activity(cash='100', size='0', tx='topup', kind='DEPOSIT'))
    figures = CapitalBook(ledger).figures()
    assert figures['returned_principal_native'] == 6_666_660
    assert figures['segregated_profit_native'] == 13_333_340
    assert figures['segregated_incentives_native'] == 5_000_000
    assert figures['segregated_external_cash_native'] == 100_000_000
    assert figures['headroom_native'] == 300_000_000
    with pytest.raises(LedgerUnavailable, match='capital_activity_repeated'):
        record_activity(ledger, first)


def test_paid_and_reserved_costs_charge_total_once(tmp_path):
    ledger = ledger_at(tmp_path)
    install(ledger, '300')
    from weather.market.mm_stage2_hold import digest
    for index, paid in enumerate((False, True)):
        evidence = {'source': 'synthetic-invoice', 'index': index}
        ledger.record('capital_cost', cost_id=str(index), amount_native=500_000, paid=paid,
                      evidence=evidence, evidence_sha256=digest(evidence))
    assert CapitalBook(ledger).figures()['headroom_native'] == 299_000_000
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        CapitalBook(ledger).gate(reserve='299.000001')


def test_inflight_topup_or_reward_cannot_finance_a_post_before_activity_sync(tmp_path):
    ledger = ledger_at(tmp_path)
    install(ledger, cash='100')
    book = CapitalBook(ledger)
    assert book.figures()['owner_contributions_native'] == 100_000_000
    assert book.figures()['owner_funding_ceiling_native'] == 300_000_000
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        book.gate(reserve='100.000001', available_cash='1000')
    record_activity(ledger, activity(cash='200', kind='DEPOSIT', size='0', tx='topup'))
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        CapitalBook(ledger).gate(reserve='100.000001', available_cash='300')
    with pytest.raises(CapitalRefused, match='capital_cash_changed'):
        CapitalBook(ledger).gate(reserve='1', available_cash='299.99')


@pytest.mark.parametrize('value', ['.0000001', True, '-1', 'NaN'])
def test_native_units_refuse_unrepresentable_or_invalid_cash(value):
    with pytest.raises(ValueError):
        native(value)
    assert native(Decimal('.0000001'), ceil=True) == 1
