"""Shared-wallet notices grant no authority without independent money evidence."""
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_f2_controller import setup
from tests.market.test_lfc_f2_inventory_b080 import fixture, observation
from tests.market.test_lfc_f2_personal_cash_b081 import account_guard, owner_trade
from tests.market.test_lfc_f2_capital import MAKER
from weather.market.lfc_campaign import TransientPrecheck
from weather.market.lfc_campaign_proof import local_money_proof
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_capital import ASSET, CapitalBook, CapitalRefused
from weather.market.lfc_capital_native import TRANSFER
from weather.market.lfc_capital_reads import synchronize
from weather.market.lfc_f2_external_trades import EXCHANGES, NOTICE, ORDER_FILLED, STOP, notice_for, prove_live
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_recording_io import retained
from weather.market.lfc_redemption_native import CTF, SINGLE


ATTEMPT = 'a' * 32
MARKET = '0x' + 'c' * 64
ORDER = '0x' + 'd' * 64
TX = '0x' + '1' * 64


def native_receipt(side, *, wrong_order=False, wrong_fee=False):
    other = '0x' + '9' * 40
    cash_from, cash_to = (MAKER, other) if side == 'BUY' else (other, MAKER)
    block = '0x' + 'b' * 64
    cash_from, cash_to = [f'0x{int(addr, 16):064x}' for addr in (cash_from, cash_to)]
    maker, counterparty = (cash_from, cash_to) if side == 'BUY' else (cash_to, cash_from)
    direction, making, taking = (0, 10_400_000, 20_000_000) if side == 'BUY' else (1, 20_000_000, 10_400_000)
    fields = {'transactionHash': TX, 'blockNumber': '0x100', 'blockHash': block}
    logs = [
        {**fields, 'address': ASSET, 'logIndex': '0x0', 'topics': [TRANSFER, cash_from, cash_to],
         'data': f'0x{10_400_000:064x}'},
        {**fields, 'address': CTF, 'logIndex': '0x1', 'topics': [SINGLE, cash_to, cash_to, cash_from],
         'data': f'0x{90:064x}{20_000_000:064x}'},
        {**fields, 'address': min(EXCHANGES), 'logIndex': '0x2',
         'topics': [ORDER_FILLED, TX if wrong_order else ORDER, maker, counterparty],
         'data': '0x' + ''.join(f'{number:064x}' for number in (direction, 90, making, taking, wrong_fee, 0, 0))},
    ]
    return retained(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': {**fields, 'status': '0x1', 'logs': logs}}).encode())


def armed(ledger, *, protocol='lfc_autostart_v2'):
    ledger.record('autostart_enroll', state_id='state', identity_sha256='identity', state_root='state')
    ledger.record('autostart_claim', attempt_id=ATTEMPT, file_sha256='claim')
    ledger.record('session_start', session_id='new-band', protocol=protocol,
                  autostart_attempt_id=ATTEMPT, condition_id=MARKET)


def traded_wallet(tmp_path, side, *, live=False):
    ledger, baseline, clock, _ = fixture(tmp_path, personal=False, bridge=False)
    holding = 30
    before = observation(ledger, clock, positions={'denver': '20', '90': holding}, cash='290')
    synchronize(ledger, baseline, before, anchor_mode='enrollment')
    clock.value += timedelta(seconds=1)
    armed(ledger, protocol='lfc_autostart_v3' if live else 'lfc_autostart_v2')
    clock.value += timedelta(seconds=6)
    if not live:
        ledger.record('session_end', session_id='new-band')
    cash, qty = ('279.6', 50) if side == 'BUY' else ('300.4', 10)
    read = observation(ledger, clock, positions={'denver': '20', '90': qty}, cash=cash)
    other = '0x' + 'e' * 64
    trade = dict(owner_trade(clock, side, seconds=3), market=other, condition_id=other, taker_order_id=ORDER)
    read['trades'].append(trade)
    read['terminal_orders'] = {}
    read['external_trade_receipts'] = {TX: native_receipt(side)}
    return ledger, clock, read, trade


@pytest.mark.parametrize('side', ['BUY', 'SELL'])
def test_receipt_proves_personal_execution_once_and_survives_next_anchor(tmp_path, side, account_guard):
    ledger, clock, read, trade = traded_wallet(tmp_path, side)
    book = CapitalBook(ledger)
    result = synchronize(ledger, book.inventory_anchor, read)
    assert result['cash_bridge_complete'] and result['inventory']['changed'] == []
    assert ledger.L() == 10
    book = CapitalBook(ledger)
    assert book.figures()['funding_native'] == 300_000_000
    assert book.figures()['retained_gains_available_native'] == 0
    assert book.external_trade_transactions == {TX: trade['id']}
    assert synchronize(ledger, book.inventory_anchor, read)['cash_bridge_complete']
    assert len(ledger.event_rows('capital_external_trades')) == 1
    ledger.record('autostart_close', attempt_id=ATTEMPT, file='closed/' + ATTEMPT + '.json',
                  file_size=1, close_kind='postcheck', closed_at_utc=clock.now().isoformat(),
                  file_sha256='b' * 64, proof_sha256='c' * 64, close_ledger_sha256=ledger.previous,
                  read_binding={'read_sha256': None, 'started_at_utc': None, 'ended_at_utc': None})
    clock.value += timedelta(seconds=1)
    next_read = observation(ledger, clock, positions={'denver': '20', '90': '50' if side == 'BUY' else '10'},
                            cash=read['balances']['available_collateral'])
    next_read['trades'].append(trade)
    assert synchronize(ledger, book.inventory_anchor, next_read, anchor_mode='session')['cash_bridge_complete']
    reopened = Ledger.open(ledger.path, clock=clock.now)
    assert CapitalBook(reopened).expected_cash() == book.expected_cash()
    assert CapitalBook(reopened).external_trade_transactions == book.external_trade_transactions


@pytest.mark.parametrize(('case', 'kind', 'reason'), [
    ('condition', CapitalRefused, 'capital_inventory_unreconciled'),
    ('cash', CapitalRefused, 'capital_cash_unreconciled'),
    ('shares', CapitalRefused, 'capital_inventory_unreconciled'),
    ('receipt_pending', TransientPrecheck, 'external_trade_proof_pending'),
    ('unrelated_later_trade', CapitalRefused, 'capital_inventory_unreconciled'),
    ('wrong_order', CapitalRefused, 'capital_inventory_unreconciled'),
    ('wrong_fee', CapitalRefused, 'capital_inventory_unreconciled'),
])
def test_unavailable_or_conflicting_inputs_do_not_book_a_trade(tmp_path, case, kind, reason, account_guard):
    ledger, clock, read, trade = traded_wallet(tmp_path, 'BUY')
    if case == 'condition':
        trade['market'] = trade['condition_id'] = MARKET
    elif case == 'cash':
        read['balances'] = observation(ledger, clock, positions={}, cash='279.600001')['balances']
    elif case == 'shares':
        read['positions'][1]['size'] = '49.999999'
    elif case == 'receipt_pending':
        read['external_trade_receipts'] = {}
    elif case in {'wrong_order', 'wrong_fee'}:
        read['external_trade_receipts'][TX] = native_receipt(
            'BUY', wrong_order=case == 'wrong_order', wrong_fee=case == 'wrong_fee')
    else:
        read['trades'].append(dict(trade, id='later', matched_at=(clock.now() + timedelta(seconds=1)).isoformat()))
    baseline = CapitalBook(ledger).inventory_anchor
    before = ledger.path.read_bytes()
    with pytest.raises(kind, match=reason):
        synchronize(ledger, baseline, read)
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize('case', ['proved', 'missing_rest', 'foreign_resting', 'too_slow'])
def test_live_external_gate_uses_the_ordinary_account_and_resting_order_proof(tmp_path, case, account_guard):
    ledger, clock, read, trade = traded_wallet(tmp_path, 'BUY', live=True)
    runtime = object.__new__(Runtime)
    runtime.state, runtime.clock = SimpleNamespace(maker=MAKER), clock
    runtime.original_baseline = lambda ledger: CapitalBook(ledger).inventory_anchor
    runtime.read_account = lambda: read
    marker = {'trade_id': trade['id'], 'condition_id': trade['market'], 'transaction_hash': TX}
    before = ledger.path.read_bytes()
    if case == 'missing_rest':
        read['trades'].pop()
    elif case == 'foreign_resting':
        read['open_orders'] = [{'id': 'external'}]
    elif case == 'too_slow':
        def slow_read():
            clock.value += timedelta(seconds=13)
            return read
        runtime.read_account = slow_read
    if case == 'foreign_resting':
        with pytest.raises(TransientPrecheck, match='repost_open_orders_unproven'):
            prove_live(runtime, ledger, ATTEMPT, marker)
    else:
        assert prove_live(runtime, ledger, ATTEMPT, marker) == (TX if case == 'proved' else None)
    if case == 'proved':
        assert len(ledger.event_rows('capital_external_trades')) == 1
        assert ledger.open_sessions() == ['new-band']
    else:
        assert ledger.path.read_bytes() == before


def test_external_redemption_keeps_its_separate_native_proof_inside_a_pending_attempt(tmp_path, account_guard):
    from tests.market.test_lfc_redemption_native import paired
    from weather.market.lfc_capital import record_activity
    from weather.market.mm_stage2_hold import digest

    ledger, baseline, clock, _ = fixture(tmp_path, personal=False, bridge=False)
    source, proof, tokens = paired(auto=True)
    positions = {'denver': '20', **{token: '20' for token in tokens}}
    synchronize(ledger, baseline, observation(ledger, clock, positions=positions, cash='290'), anchor_mode='enrollment')
    clock.value += timedelta(seconds=1)
    armed(ledger)
    clock.value += timedelta(minutes=1)
    source['timestamp'] = int(clock.now().timestamp())
    proof.update(rows=[source], rows_sha256=digest([source]))
    record_activity(ledger, source, native_evidence=proof)
    ledger.record('session_end', session_id='new-band')
    read = observation(ledger, clock, positions={'denver': '20'}, cash='310')
    result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, read)
    assert result['cash_bridge_complete'] and result['inventory']['changed'] == []
    assert CapitalBook(ledger).figures()['retained_gains_available_native'] == 0
    assert not ledger.event_rows('capital_external_trades')


@pytest.mark.parametrize('confirmed', [False, True])
def test_typed_stream_notice_stops_cleanly_or_continues(tmp_path, confirmed, account_guard, monkeypatch):
    from tests.market.test_lfc_f2_evidence import runtime_at_controller
    from tests.market.test_lfc_f2_repost import campaign_stream

    coordinator, account, status, ledger, clock = setup(tmp_path, enrolled=True)
    account.raws[0].fixture_directory = tmp_path
    row = {'event_type': 'trade', 'status': 'MATCHED', 'trader_side': 'TAKER',
           'id': 'external-trade', 'market': '0x' + 'e' * 64, 'maker_address': MAKER,
           'taker_order_id': ORDER, 'transaction_hash': None}
    stream = campaign_stream(account.raws[0])
    assert notice_for(dict(row, maker_address='0x' + 'f' * 40), MAKER) is None
    observed = stream._normalize_event(row)
    assert observed[0]['event_type'] == NOTICE
    account.raws[0].events = lambda: observed if clock.seconds >= 12 else []
    checked = []

    def prove(notice):
        checked.append(notice['trade_id'])
        return TX if confirmed else False

    coordinator.verify_external = prove
    result = coordinator.run()
    assert result['reason'] == ('fixed_end' if confirmed else STOP)
    assert checked == ['external-trade']
    assert result['cleanup_ok'] and ledger.unresolved_legs() == []
    outcome = status.finish(success=True)
    local = local_money_proof(coordinator.directory, ledger=ledger, session_id=coordinator.session_id,
                              attempt_id=coordinator.attempt_id, outcome=outcome,
                              terminal_backfill=True)
    assert local['complete']
    runtime = runtime_at_controller(coordinator, account, status, ledger, clock, monkeypatch)
    runtime.save_result(account.claim, runtime.session_result(account.claim, status, outcome, 0))
    proof = runtime.postcheck(account.claim, runtime.saved_result(account.claim))
    assert proof['cleanup_proven'] and proof['money_accounting_complete']
    runtime.state.close(account.claim, proof, clock.now())
    assert runtime.state.incidents() == [] and runtime.state.pending() == []
