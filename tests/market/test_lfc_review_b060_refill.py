"""Guards: owner B060 net sleeve; native proven gains, no top-ups or owner funding.

Every receipt and account fact is synthetic. No client, signer or service exists.
"""
from copy import deepcopy
from decimal import Decimal
from datetime import timedelta

import pytest

from tests.market.test_lfc_campaign import Mutexes
from tests.market.test_lfc_f2_capital import NOW, MAKER, filled, install, ledger_at, activity
from tests.market.test_lfc_f2_capital_reads import rpc_packet
from tests.market.test_lfc_f2_native import BLOCK, log
from tests.market.test_lfc_redemption_native import paired
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_state import AccountState
from weather.market.lfc_capital import CapitalBook, CapitalRefused, native, pusd, record_activity
from weather.market.lfc_f2_breadth import example_policy
from weather.market.lfc_ledger import Ledger, LedgerUnavailable, take_baseline, write_baseline
from weather.market.mm_stage2_hold import digest

BASES = ['gross', 'net_of_retained_gains']


@pytest.fixture(autouse=True)
def guard():
    with account_lease(MAKER, backend=Mutexes()): yield


def opening(tmp_path, basis, *, wallet='300', outside_winner='0'):
    ledger = ledger_at(tmp_path)
    if Decimal(outside_winner):
        source, _, tokens = paired()
        baseline = take_baseline(label='t40', now=NOW, maker_address=MAKER,
            positions=[{'asset': tokens[0], 'conditionId': source['condition_id'], 'size': outside_winner}],
            open_orders=[], available_collateral=wallet)
        write_baseline(ledger.path.parent, baseline, ledger)
        ledger.record('capital_anchor', baseline=baseline, baseline_sha256=digest(baseline))
    install(ledger, cash=wallet)
    state = AccountState(tmp_path / 'state', ledger); state.enroll(NOW)
    row = example_policy(); row.update(enabled=True, max_session_seconds=300)
    # The pre-feature baseline reaches its existing gross gate. Once the new
    # field ships, both variants go through the real policy parser and claim.
    if 'sleeve_loss_basis' in row: row['sleeve_loss_basis'] = basis
    policy = parse_policy(row)
    entry = next(e for e in policy.entries if e.local_date == '2026-11-11')
    claim = state.claim(entry, policy, NOW)
    return ledger, state, claim, policy


def settled_pair(tmp_path, basis, *, wallet='300', winner_size='20', loser=True, winner=True, pending=False):
    # The mixed-lot case includes separately proved pre-existing owner inventory.
    # This tests accounting of legacy holdings, not permission to select that event.
    outside = str(Decimal('20')-Decimal(winner_size)) if winner else '0'
    ledger, state, claim, policy = opening(tmp_path, basis, wallet=wallet, outside_winner=outside)
    source, evidence, tokens = paired()
    if winner: filled(ledger, 'winner', price='.48', size=winner_size, token=tokens[0], condition=source['condition_id'], market_id='denver')
    if loser: filled(ledger, 'loser', price='.48', token=tokens[1], condition=source['condition_id'], market_id='toronto')
    if pending: evidence = {**evidence, 'receipt': rpc_packet(None)}
    record_activity(ledger, source, native_evidence=evidence)
    return ledger, state, source, evidence


def transfer(ledger, amount, kind, *, nonce):
    tx = '0x' + f'{nonce:064x}'
    source = activity(cash=amount, size='0', tx=tx, kind=kind)
    source['timestamp'] += nonce
    ledger.clock = lambda: NOW + timedelta(seconds=nonce)
    outgoing = kind == 'WITHDRAWAL'
    entry = log(native(amount), **({'sender': MAKER, 'receiver': '0x' + 'c' * 40} if outgoing else {}))
    entry['transactionHash'] = tx
    receipt = {'transactionHash': tx, 'blockHash': BLOCK, 'blockNumber': '0x123', 'status': '0x1', 'logs': [entry]}
    evidence = {'transaction_hash': tx, 'rows': [source], 'rows_sha256': digest([source]),
                'receipt': rpc_packet(receipt), 'failure_type': None}
    record_activity(ledger, source, native_evidence=evidence)


@pytest.mark.parametrize('basis', BASES)
def test_complete_pair_refills_only_under_net_basis(tmp_path, basis):
    ledger, *_ = settled_pair(tmp_path, basis)
    row = CapitalBook(ledger).figures()
    assert row['realized_principal_losses_native'] == 9_600_000
    assert row['headroom_native'] == (300_000_000 if basis != 'gross' else 290_400_000)
    assert row['retained_gains_offset_native'] == (9_600_000 if basis != 'gross' else 0)
    assert ledger.L() == Decimal('19.20')


@pytest.mark.parametrize('basis', BASES)
def test_losing_single_burns_its_full_basis(tmp_path, basis):
    ledger, *_ = settled_pair(tmp_path, basis, winner=False)
    row = CapitalBook(ledger).figures()
    assert row['headroom_native'] == 290_400_000 and row['realized_principal_losses_native'] == 9_600_000
    assert row['retained_gains_offset_native'] == 0


@pytest.mark.parametrize('basis', BASES)
def test_profit_never_lifts_principal_risk_or_headroom_above_three_hundred(tmp_path, basis):
    ledger, *_ = settled_pair(tmp_path, basis, loser=False)
    book = CapitalBook(ledger)
    assert book.figures()['headroom_native'] == 300_000_000
    book.gate(reserve='300', available_cash=pusd(book.expected_cash()))
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        book.gate(reserve='300.000001', available_cash='1000')


@pytest.mark.parametrize('basis', BASES)
def test_owner_withdrawal_consumes_retained_gains_even_with_other_owner_cash(tmp_path, basis):
    ledger, *_ = settled_pair(tmp_path, basis, wallet='920.24')
    transfer(ledger, '10.4', 'WITHDRAWAL', nonce=41)
    book = CapitalBook(ledger); row = book.figures()
    assert row['retained_gains_available_native'] == 0
    assert row['headroom_native'] == 290_400_000
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        book.gate(reserve='290.400001', available_cash=pusd(book.expected_cash()))


@pytest.mark.parametrize('basis', BASES)
def test_deposit_never_adds_headroom_or_replaces_withdrawn_gains(tmp_path, basis):
    ledger, *_ = settled_pair(tmp_path, basis, wallet='920.24')
    transfer(ledger, '10.4', 'WITHDRAWAL', nonce=42)
    before = CapitalBook(ledger).figures()['headroom_native']
    transfer(ledger, '100', 'DEPOSIT', nonce=43)
    book = CapitalBook(ledger)
    assert book.figures()['headroom_native'] == before == 290_400_000
    assert book.figures()['retained_gains_available_native'] == 0
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        book.gate(reserve='300', available_cash=pusd(book.expected_cash()))


@pytest.mark.parametrize('basis', BASES)
def test_pending_redemption_has_zero_offset_until_native_resolution(tmp_path, basis):
    ledger, state, source, evidence = settled_pair(tmp_path, basis, pending=True)
    row = CapitalBook(ledger).figures()
    assert row['retained_gains_offset_native'] == row['retained_gains_available_native'] == 0
    known, native_evidence, _ = paired()
    book = CapitalBook(ledger); identity = next(iter(book.unknown))
    ledger.record('capital_resolution', source=known, source_sha256=digest(known),
        previous_source_sha256=book.sources[identity], native_evidence=native_evidence)
    assert CapitalBook(ledger).figures()['headroom_native'] == (300_000_000 if basis != 'gross' else 290_400_000)


@pytest.mark.parametrize('basis', BASES)
def test_a_new_unknown_cash_observation_disables_even_previously_proven_offsets(tmp_path, basis):
    ledger, *_ = settled_pair(tmp_path, basis)
    before = CapitalBook(ledger).figures()
    assert before['retained_gains_available_native'] == 10_400_000
    source = activity(cash='1', size='0', kind='REWARD', tx='0x'+'e'*64)
    source['timestamp'] += 1; ledger.clock = lambda: NOW + timedelta(seconds=1)
    evidence = {'transaction_hash': source['transaction_hash'], 'rows': [source],
        'rows_sha256': digest([source]), 'receipt': rpc_packet(None), 'failure_type': None}
    record_activity(ledger, source, native_evidence=evidence)
    book = CapitalBook(ledger); row = book.figures()
    assert row['unknown_payouts']
    assert row['proven_campaign_profit_cumulative_native'] == before['proven_campaign_profit_cumulative_native']
    assert row['retained_gains_available_native'] == row['retained_gains_offset_native'] == 0
    assert row['headroom_native'] == 290_400_000
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        book.gate(reserve='300', available_cash='1000')


@pytest.mark.parametrize('basis', BASES)
def test_restart_reopen_and_repeated_views_count_the_offset_exactly_once(tmp_path, basis):
    ledger, *_ = settled_pair(tmp_path, basis)
    expected = CapitalBook(ledger).figures(); original = ledger.path.read_bytes()
    for _ in range(3):
        reopened = Ledger.open(ledger.path, clock=lambda: NOW)
        assert CapitalBook(reopened).figures() == expected
        assert reopened.path.read_bytes() == original
    assert expected['sleeve_loss_basis'] == basis


@pytest.mark.parametrize('basis', BASES)
def test_mixed_owner_and_campaign_redemption_reports_only_campaign_payout(tmp_path, basis):
    from weather.market.lfc_f2_economics import measured
    ledger, *_ = settled_pair(tmp_path, basis, winner_size='10')
    row = measured(ledger, ['winner', 'loser'])
    assert row['settlement']['redemptions'][0]['session_cash_native'] == 10_000_000
    assert row['campaign_capital']['proven_campaign_profit_cumulative_native'] == 5_200_000
    assert row['campaign_capital']['headroom_native'] == (295_600_000 if basis != 'gross' else 290_400_000)


@pytest.mark.parametrize('basis', BASES)
def test_serial_intent_gate_keeps_all_bands_inside_the_same_sleeve(tmp_path, basis):
    ledger, *_ = settled_pair(tmp_path, basis)
    # Carried inventory and reserve count independently of available profit.
    for n in range(24): filled(ledger, 'carry-' + str(n), size='20', price='.5', token=str(1000+n), condition='carry')
    accepted = 0
    for n in range(12):
        key = 'parallel-' + str(n)
        ledger.record('session_start', session_id=key, counted=False)
        try:
            ledger.intent(session_id=key, intent_key=key, token_id=str(2000+n), condition_id='new',
                price='.48', size='20', fee_rate_bps='0')
        except CapitalRefused as exc:
            assert str(exc) == 'capital_total_ceiling'
            continue
        accepted += 1
        row = CapitalBook(ledger).figures()
        assert row['unrecovered_inventory_cost_native'] + row['resting_reserve_native'] <= 300_000_000
    assert accepted == (6 if basis != 'gross' else 5)
    rows = [row for row in ledger.rows if row['event'] == 'leg_intent' and row['session_id'].startswith('parallel-')]
    assert all(row['capital_admission']['sleeve_loss_basis'] == basis for row in rows)
    assert all(row['capital_admission']['retained_gains_offset_native'] ==
               (9_600_000 if basis != 'gross' else 0) for row in rows)
    reopened = Ledger.open(ledger.path, clock=ledger.clock)
    assert [row['capital_admission'] for row in reopened.rows if row in rows] == [row['capital_admission'] for row in rows]


@pytest.mark.parametrize('basis', BASES)
def test_reserved_costs_use_only_the_remaining_proven_gain(tmp_path, basis):
    ledger, *_ = settled_pair(tmp_path, basis)
    proof = {'synthetic_reserved_cost': True}
    ledger.record('capital_cost', cost_id='reserved', amount_native=2_000_000, paid=False,
                  evidence=proof, evidence_sha256=digest(proof))
    row = CapitalBook(ledger).figures()
    assert row['realized_principal_losses_native'] == 9_600_000
    assert row['paid_or_reserved_campaign_costs_native'] == 2_000_000
    assert row['headroom_native'] == (298_800_000 if basis != 'gross' else 288_400_000)


@pytest.mark.parametrize('basis', BASES)
def test_account_reward_cash_without_campaign_attribution_never_offsets_losses(tmp_path, basis):
    ledger, *_ = settled_pair(tmp_path, basis, winner=False)
    transfer(ledger, '50', 'REWARD', nonce=52)
    row = CapitalBook(ledger).figures()
    assert row['headroom_native'] == 290_400_000
    assert row['retained_gains_available_native'] == row['proven_campaign_profit_cumulative_native'] == 0


@pytest.mark.parametrize('basis', BASES)
def test_owner_fractional_payout_remainder_cannot_become_a_campaign_gain(tmp_path, basis):
    import json
    from eth_abi import encode
    from weather.market.lfc_redemption_native import POSITION
    from weather.market.lfc_recording_io import response_bytes
    ledger, *_ = opening(tmp_path, basis, outside_winner='10')
    source, evidence, tokens = paired()
    filled(ledger, 'winner', price='.48', size='10', token=tokens[0], condition=source['condition_id'])
    filled(ledger, 'loser', price='.48', token=tokens[1], condition=source['condition_id'])
    source['usdc_size'] = '10.000001'
    receipt = json.loads(response_bytes(evidence['receipt']))['result']
    first = next(entry for entry in receipt['logs'] if entry['topics'][0] == POSITION)
    first['data'] = '0x' + encode(['uint256', 'uint256'], [20_000_000, 10_000_001]).hex()
    receipt['logs'][-1]['data'] = '0x' + f'{10_000_001:064x}'
    evidence.update(rows=[source], rows_sha256=digest([source]), receipt=rpc_packet(receipt))
    record_activity(ledger, source, native_evidence=evidence)
    row = CapitalBook(ledger).figures()
    assert row['segregated_profit_native'] == 200_001
    assert row['proven_campaign_profit_cumulative_native'] == 200_000
    assert row['retained_gains_offset_native'] == (200_000 if basis != 'gross' else 0)
