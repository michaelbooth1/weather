"""Independent B039 capital witnesses, using only synthetic ledger/venue IO.

Guards: unknown legacy bridge, mislabeled batch cash, quarantined credits,
withdrawal allocation, T+1-only and the real F2Band/ledger/start admission path.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_f2_capital import (MAKER, NOW, activity, filled, install, ledger_at)
from tests.market.test_lfc_f2_controller import setup
from tests.market.test_lfc_f2_native import proof, source
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_capital import CapitalBook, CapitalRefused, native, record_activity
from weather.market.lfc_f2_policy import example_policy, support_table
from weather.market.lfc_ledger import Ledger, LedgerUnavailable
from weather.market.mm_stage2_hold import HoldEnd, digest


@pytest.mark.parametrize('kind', ['REDEEM', 'WITHDRAWAL'])
def test_unknown_legacy_cash_refuses_underfunded_bridge_and_replay(tmp_path, kind):
    ledger = ledger_at(tmp_path)
    filled(ledger, 'legacy')  # A 10 pUSD lot; the unknown redeem may have paid 20.
    row = activity(cash=None, kind=kind, size='20' if kind == 'REDEEM' else '0')
    record_activity(ledger, row)
    with pytest.raises(CapitalRefused, match='capital_bridge_unknown_cash'):
        install(ledger, cash='200')
    book = CapitalBook(ledger)
    assert book.bridge is None and book.unknown
    before = ledger.previous
    # Replay must reject too, even if somebody bypasses the bridge() API.
    with pytest.raises(LedgerUnavailable, match='capital_bridge_unknown_cash'):
        ledger.record('capital_bridge', mode='synthetic-bypass')
    assert ledger.previous == before and CapitalBook(ledger).bridge is None
    known = {**row, 'usdc_size': '20' if kind == 'REDEEM' else '2'}
    ledger.record('capital_resolution', source=known, source_sha256=digest(known),
                  previous_source_sha256=book.sources[book.unknown[0]])
    install(ledger, cash='200')
    restored = CapitalBook(ledger)
    assert not restored.unknown and restored.bridge
    assert restored.figures()['funding_native'] == (190_000_000 if kind == 'REDEEM' else 210_000_000)
    restored.gate(reserve='1', available_cash='200')


def test_swapped_batched_redemption_labels_return_no_principal(tmp_path):
    ledger = ledger_at(tmp_path)
    filled(ledger, 'denver', price='.45', condition='denver')  # cost 9, actually lost
    filled(ledger, 'toronto', price='.35', token='no', condition='toronto')  # cost 7, actually won
    install(ledger, cash='284')
    denver, toronto = source(cash='20'), source(cash='0', token='no')
    denver['condition_id'], toronto['condition_id'] = 'denver', 'toronto'
    evidence = proof([denver, toronto], incoming=20_000_000)
    for row in (denver, toronto):
        record_activity(ledger, row, native_evidence=evidence)
    book = CapitalBook(ledger)
    assert len(book.unknown) == 2
    assert book.figures()['returned_principal_native'] == 0
    assert book.figures()['realized_principal_losses_native'] == 16_000_000
    assert book.figures()['headroom_native'] == 284_000_000
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        book.gate(reserve='284.000001', available_cash='304')


@pytest.mark.parametrize('kind', ['REWARD', 'TIP', 'DEPOSIT'])
@pytest.mark.parametrize('cash', ['200', '320'])
def test_late_prebridge_credit_is_not_counted_twice(tmp_path, kind, cash):
    ledger = ledger_at(tmp_path)
    ledger.clock = lambda: NOW + timedelta(seconds=10)
    install(ledger, cash=cash)
    row = activity(cash='20', kind=kind, size='0')
    row['timestamp'] += 1  # After genesis, before the bridge's observed balance.
    if kind == 'TIP':
        row['side'] = 'IN'
    record_activity(ledger, row)
    book = CapitalBook(ledger)
    assert book.expected_cash() == native(cash)
    expected_funding = min(300, int(cash) - (0 if kind == 'DEPOSIT' else 20))
    assert book.figures()['funding_native'] == expected_funding * 1_000_000
    book.gate(reserve=str(expected_funding), available_cash=cash)
    assert book.bridge['funding_native'] == min(300, int(cash)) * 1_000_000  # Original receipt stays immutable.


def test_late_legacy_profit_cannot_replace_principal_with_a_later_topup(tmp_path):
    ledger = ledger_at(tmp_path)
    ledger.clock = lambda: NOW + timedelta(seconds=10)
    install(ledger, cash='200')
    topup = activity(cash='100', kind='DEPOSIT', size='0', tx='later-topup')
    topup['timestamp'] += 11
    record_activity(ledger, topup)
    reward = activity(cash='20', kind='REWARD', size='0', tx='late-legacy-reward')
    reward['timestamp'] += 1
    record_activity(ledger, reward)
    book = CapitalBook(ledger)
    assert book.expected_cash() == 300_000_000
    assert book.figures()['funding_native'] == 180_000_000
    assert book.external == 100_000_000 and book.incentives == 20_000_000
    assert CapitalBook(Ledger.open(ledger.path, clock=ledger.clock)).figures() == book.figures()
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        book.gate(reserve='180.000001', available_cash='300')


def test_late_unknown_legacy_credit_blocks_until_resolved_without_reset(tmp_path):
    ledger = ledger_at(tmp_path)
    ledger.clock = lambda: NOW + timedelta(seconds=10)
    install(ledger, cash='200')
    unknown = activity(cash=None, kind='REWARD', size='0')
    unknown['timestamp'] += 1
    record_activity(ledger, unknown)
    book = CapitalBook(ledger)
    with pytest.raises(CapitalRefused, match='capital_legacy_unknown_cash'):
        book.gate(reserve='1', available_cash='200')
    known = {**unknown, 'usdc_size': '20'}
    ledger.record('capital_resolution', source=known, source_sha256=digest(known),
                  previous_source_sha256=book.sources[book.unknown[0]])
    assert CapitalBook(ledger).expected_cash() == 200_000_000
    assert CapitalBook(ledger).figures()['funding_native'] == 180_000_000


def test_same_second_credit_is_not_assumed_to_precede_the_bridge_balance(tmp_path):
    ledger = ledger_at(tmp_path)
    ledger.clock = lambda: NOW + timedelta(milliseconds=500)
    install(ledger, cash='200')
    record_activity(ledger, activity(cash='20', kind='REWARD', size='0'))
    book = CapitalBook(ledger)
    assert book.expected_cash() == 220_000_000 and book.figures()['funding_native'] == 200_000_000
    book.gate(reserve='200', available_cash='220')


def test_late_legacy_credit_does_not_consume_already_classified_external_cash(tmp_path):
    ledger = ledger_at(tmp_path)
    tip = {**activity(cash='100', kind='TIP', size='0'), 'side': 'IN'}
    record_activity(ledger, tip)
    ledger.clock = lambda: NOW + timedelta(seconds=10)
    install(ledger, cash='200')
    reward = activity(cash='20', kind='REWARD', size='0', tx='late-reward')
    reward['timestamp'] += 1
    record_activity(ledger, reward)
    book = CapitalBook(ledger)
    assert book.figures()['funding_native'] == 80_000_000
    assert book.external == 100_000_000 and book.incentives == 20_000_000
    book.gate(reserve='80', available_cash='200')


@pytest.mark.parametrize('same_second', [False, True])
def test_later_topup_cannot_cover_a_resolved_older_principal_withdrawal(tmp_path, same_second):
    ledger = ledger_at(tmp_path)
    install(ledger, cash='300')
    withdrawal = activity(cash=None, kind='WITHDRAWAL', size='0', tx='withdraw')
    withdrawal['timestamp'] += 1
    record_activity(ledger, withdrawal)
    topup = activity(cash='100', kind='DEPOSIT', size='0', tx='later-topup')
    topup['timestamp'] += 1 if same_second else 2
    record_activity(ledger, topup)
    book = CapitalBook(ledger)
    known = {**withdrawal, 'usdc_size': '100'}
    ledger.record('capital_resolution', source=known, source_sha256=digest(known),
                  previous_source_sha256=book.sources[book.unknown[0]])
    book = CapitalBook(ledger)
    assert book.costs == book.external == 100_000_000
    assert CapitalBook(Ledger.open(ledger.path, clock=ledger.clock)).figures() == book.figures()
    assert book.expected_cash() == 300_000_000 and book.figures()['headroom_native'] == 200_000_000
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        book.gate(reserve='200.000001', available_cash='300')


def test_late_legacy_reward_explains_an_already_recorded_withdrawal(tmp_path):
    ledger = ledger_at(tmp_path)
    ledger.clock = lambda: NOW + timedelta(seconds=10)
    install(ledger, cash='200')
    withdrawal = activity(cash='10', kind='WITHDRAWAL', size='0', tx='withdraw')
    withdrawal['timestamp'] += 11
    record_activity(ledger, withdrawal)
    reward = activity(cash='20', kind='REWARD', size='0', tx='late-reward')
    reward['timestamp'] += 1
    record_activity(ledger, reward)
    book = CapitalBook(ledger)
    assert book.figures()['funding_native'] == 180_000_000
    assert book.costs == 0 and book.incentives == 10_000_000
    assert book.expected_cash() == 190_000_000
    book.gate(reserve='180', available_cash='190')


@pytest.mark.parametrize('amount,external,profit,incentives', [('10', 20, 10, 5), ('35', 0, 5, 5), ('42', 0, 0, 3)])
def test_partial_withdrawal_uses_external_then_profit_then_incentives(tmp_path, amount, external, profit, incentives):
    ledger = ledger_at(tmp_path)
    filled(ledger, 'legacy')
    install(ledger)
    rows = [activity(cash='20'), activity(cash='5', kind='REWARD', size='0', tx='reward'),
            activity(cash='30', kind='DEPOSIT', size='0', tx='topup'),
            activity(cash=amount, kind='WITHDRAWAL', size='0', tx='withdraw')]
    for seconds, row in enumerate(rows, 1):
        row['timestamp'] += seconds
        record_activity(ledger, row)
    book = CapitalBook(ledger)
    assert (book.external, book.profit, book.incentives) == tuple(x*1_000_000 for x in (external, profit, incentives))
    assert book.costs == 0


def test_real_synchronize_refuses_unknown_legacy_payout_under_300_then_reconciles(tmp_path):
    from tests.market.test_lfc_f2_capital_reads import setup_read, packet, native_packet
    from tests.market.test_lfc_f2_native import TX
    from weather.market.lfc_capital import ASSET
    from weather.market.lfc_capital_reads import read_activity, synchronize
    from tests.market.test_lfc_redemption_native import paired
    ledger, baseline, read = setup_read(tmp_path, token='101')
    row, position_proof, _ = paired()
    raw = native_packet(read_activity(MAKER, int(NOW.timestamp()), int(NOW.timestamp()),
                        get=lambda *a: packet([row]), sleep=lambda _: None))
    unknown = {**proof([row]), 'receipt': None}
    read['capital_activity'] = {**raw, 'native_receipts': {TX: unknown}}
    read['positions'] = [{'asset': '101', 'size': '20'}]
    read['balances'] = {'available_collateral': '200', 'assets': {ASSET: '200'},
                        'collateral_evidence': {'balance': '200000000'}}
    # B046 A6: the bounded incoming label is held outside principal. Unknown
    # outgoing cash and incoming cash without a label still refuse separately.
    quarantined = synchronize(ledger, baseline, read)
    assert quarantined['funding_native'] == 190_000_000
    assert quarantined['returned_principal_native'] == 0 and quarantined['unknown_payouts']
    assert ledger.L() == 10
    read['capital_activity']['native_receipts'][TX] = position_proof
    read['positions'] = []
    result = synchronize(ledger, baseline, read)
    assert result['cash_bridge_complete'] and result['funding_native'] == 190_000_000
    assert result['returned_principal_native'] == result['segregated_profit_native'] == 10_000_000
    assert ledger.L() == 10


@pytest.mark.parametrize('unknown', [False, True])
def test_withdrawal_spends_setaside_pools_before_principal(tmp_path, unknown):
    ledger = ledger_at(tmp_path)
    filled(ledger, 'legacy')
    install(ledger)
    rows = [activity(cash='20'), activity(cash='5', kind='REWARD', size='0', tx='reward'),
            activity(cash='30', kind='DEPOSIT', size='0', tx='topup')]
    for seconds, row in enumerate(rows, 1):
        row['timestamp'] += seconds
        record_activity(ledger, row)
    withdrawal = activity(cash=None if unknown else '47', kind='WITHDRAWAL', size='0', tx='withdraw')
    withdrawal['timestamp'] += 4
    record_activity(ledger, withdrawal)
    if unknown:
        book = CapitalBook(ledger)
        with pytest.raises(CapitalRefused, match='capital_unknown_outgoing_cost'):
            book.gate(reserve='1', available_cash='298')
        known = {**withdrawal, 'usdc_size': '47'}
        debit = next(key for key in book.unknown if book.activities[key]['type'] == 'WITHDRAWAL')
        ledger.record('capital_resolution', source=known, source_sha256=digest(known),
                      previous_source_sha256=book.sources[debit])
    book = CapitalBook(ledger)
    assert book.external == book.profit == book.incentives == 0
    assert book.costs == 2_000_000 and book.cash_out == 47_000_000
    assert book.expected_cash() == 298_000_000
    assert book.figures()['headroom_native'] == 298_000_000
    book.gate(reserve='298', available_cash='298')


@pytest.mark.parametrize('days', [[2], [1, 2], [True], [1.0], [], [0], [1, 1]])
def test_F2_horizon_is_fixed_to_owner_approved_T_plus_one(days):
    row = example_policy()
    assert parse_policy(row).raw['local_event_dte'] == [1]
    assert support_table()['local_event_dte_subset'] == [1]
    row['local_event_dte'] = days
    with pytest.raises(ValueError, match='unsupported_local_event_dte'):
        parse_policy(row)


def close_fixture(controller):
    for band in controller.bands:
        band.journal.close()
    controller.journal.close()


def test_real_band_submit_refuses_second_band_when_exactly_one_fits(tmp_path, monkeypatch):
    controller, account, status, ledger, clock = setup(tmp_path, tokens=['YES'])
    first, second = controller.bands
    # Only owner/watchdog machinery is inert. Every monetary and submit gate is real.
    for band in controller.bands:
        monkeypatch.setattr(band, 'control', lambda **kw: None)
    reserve = first.size * first.prices[0]
    assert reserve == second.size * second.prices[0]
    bill = {'fixture_reserved_cost': True}
    ledger.record('capital_cost', cost_id='prior-cost', amount_native=300_000_000-native(reserve), paid=False,
                  evidence=bill, evidence_sha256=digest(bill))
    seen = []
    actual_intent = ledger.intent
    def intent(**kw):
        seen.append(kw['session_id'])
        return actual_intent(**kw)
    monkeypatch.setattr(ledger, 'intent', intent)
    try:
        first.submit(0, first.prices[0])
        with pytest.raises(HoldEnd) as refused:
            second.submit(0, second.prices[0])
        assert refused.value.reason == 'capital_total_ceiling'
        assert seen == [first.session_id]
        assert [len(raw.calls) for raw in account.raws] == [1, 0]
        assert len(ledger.legs) == 1 and CapitalBook(ledger).figures()['charged_native'] == 300_000_000
    finally:
        close_fixture(controller)


def test_real_submit_reaches_durable_intent_gate_after_a_stale_plan(tmp_path, monkeypatch):
    controller, account, status, ledger, clock = setup(tmp_path, tokens=['YES'])
    first, second = controller.bands
    for band in controller.bands:
        monkeypatch.setattr(band, 'control', lambda **kw: None)
    reserve = first.size * first.prices[0]
    bill = {'fixture_reserved_cost': True}
    ledger.record('capital_cost', cost_id='prior-cost', amount_native=300_000_000-2*native(reserve), paid=False,
                  evidence=bill, evidence_sha256=digest(bill))
    actual_post_intent = second.post_intent
    def late_fact(request):
        # Adversarial observation after every planning/raw-post gate. The
        # actual durable ledger.intent still runs; no admission gate is mocked.
        ledger.record('capital_cost', cost_id='late-native-unit', amount_native=1, paid=False,
                      evidence=bill, evidence_sha256=digest(bill))
        return actual_post_intent(request)
    monkeypatch.setattr(second, 'post_intent', late_fact)
    seen, refusals, actual_intent = [], [], ledger.intent
    def intent(**kw):
        seen.append(kw['session_id'])
        try:
            return actual_intent(**kw)
        except CapitalRefused as exc:
            refusals.append(str(exc))
            raise
    monkeypatch.setattr(ledger, 'intent', intent)
    try:
        first.submit(0, first.prices[0])
        with pytest.raises(HoldEnd, match='pre_post_abort'):
            second.submit(0, second.prices[0])
        assert refusals == ['capital_total_ceiling']  # The actual durable gate still refuses.
        assert second.posts == 0 and not ledger.unacknowledged_intents()
        assert seen == [first.session_id, second.session_id]
        assert [len(raw.calls) for raw in account.raws] == [1, 0]
        assert len(ledger.legs) == 1
    finally:
        close_fixture(controller)


@pytest.mark.parametrize('phase', ['authorize', 'raw_post'])
def test_real_band_submit_refuses_cash_drop_between_plan_and_post(tmp_path, monkeypatch, phase):
    controller, account, status, ledger, clock = setup(tmp_path)
    band = controller.bands[0]
    monkeypatch.setattr(band, 'control', lambda **kw: None)
    raw = account.raws[0]
    if phase == 'authorize':
        monkeypatch.setattr(raw, 'balances', lambda: {'available_collateral': '299.999999'})
    else:
        actual_submit = raw.submit
        def submit(request, **kw):
            monkeypatch.setattr(raw, 'balances', lambda: {'available_collateral': '299.999999'})
            return actual_submit(request, **kw)
        monkeypatch.setattr(raw, 'submit', submit)
    try:
        with pytest.raises(HoldEnd) as refused:
            band.submit(0, band.prices[0])
        assert refused.value.reason == 'capital_cash_changed'
        assert not ledger.legs and raw.calls == [] and band.posts == 0
        assert not any(row['event'] == 'capital_cost' for row in ledger.rows)
    finally:
        close_fixture(controller)


@pytest.mark.parametrize('fault,reason', [('unbridged', 'capital_bridge_required'),
                                        ('ceiling', 'capital_total_ceiling'),
                                        ('cash_debit', 'capital_cash_changed')])
def test_run_live_start_gate_refuses_before_creating_order_capable_clients(tmp_path, monkeypatch, fault, reason):
    from weather.market import re1_transport as transport, re1_owner_checks, lfc_ledger
    from weather.market.lfc_f2_runtime import run_live
    from weather.market.re1_attended import SecretGuard
    controller, account, status, ledger, clock = setup(tmp_path / 'prepared')
    try:
        if fault == 'unbridged':
            ledger = ledger_at(tmp_path / 'unbridged')
        if fault == 'ceiling':
            bill = {'fixture_reserved_cost': True}
            ledger.record('capital_cost', cost_id='all-spent', amount_native=300_000_000, paid=False,
                          evidence=bill, evidence_sha256=digest(bill))
        closed, clients = [], []
        reader = SimpleNamespace(balances=lambda: {'available_collateral': '299.99' if fault == 'cash_debit' else '300'},
                                 open_orders=lambda: [], close=lambda: closed.append('reader'))
        def client(*args, **kw):
            assert kw.get('readonly') is True
            clients.append('read-only')
            return SimpleNamespace()
        monkeypatch.setattr(transport, 'load_owner_credentials', lambda _: ({'FUNDER_ADDRESS': MAKER}, SecretGuard()))
        monkeypatch.setattr(transport, 'build_client', client)
        monkeypatch.setattr(transport, 'OwnerVenue', lambda *a, **kw: reader)
        monkeypatch.setattr(re1_owner_checks, 'code_identity', lambda: 'f' * 40)
        monkeypatch.setattr(lfc_ledger, 'fetch_account_positions', lambda _: [])
        authority = SimpleNamespace(policy=controller.policy, entry=controller.entry,
            claim={'attempt_id': 'a' * 32}, preflight=lambda **kw: None, selection=lambda: controller.table,
            prepared={'preflight': {'timeouts_seconds': {'get': 1}}}, start_gates=lambda **kw: [])
        runtime = SimpleNamespace(state=SimpleNamespace(ledger=ledger, maker=MAKER), clock=clock,
                                  pilot_root=tmp_path / 'never-created-live-root')
        with pytest.raises(CapitalRefused, match=reason):
            run_live(runtime, authority, status)
        assert clients == ['read-only'] and closed == ['reader']
        assert not runtime.pilot_root.exists() and not ledger.legs
    finally:
        close_fixture(controller)
