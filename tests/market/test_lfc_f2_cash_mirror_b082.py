"""Guards: B082 C1-C7 cash captures reconcile once without restoring spent gains."""
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.market.test_lfc_campaign import Clock
from tests.market.test_lfc_f2_capital import MAKER, NOW, activity, filled
from tests.market.test_lfc_f2_capital_reads import native_packet, packet, rpc_packet
from tests.market.test_lfc_f2_inventory_b080 import observation
from tests.market.test_lfc_f2_native import BLOCK, proof as transfer_proof, log
from tests.market.test_lfc_redemption_native import event
from weather.market.lfc_capital import CapitalBook, record_activity
from weather.market.lfc_capital_reads import read_activity, synchronize
from weather.market.lfc_ledger import Ledger, take_baseline, write_baseline
from weather.market.lfc_recording_io import response_bytes, strict_json
from weather.market.lfc_redemption_native import AUTO, AUTO_POSITION, MODULES, PM, SINGLE, POSITION, ZERO
from weather.market.mm_stage2_hold import digest


def single_redemption(token, shares, payout, condition, tx):
    quantity_native = int(Decimal(shares) * 1_000_000)
    payout_native = int(Decimal(payout) * 1_000_000)
    source = activity(cash=payout, size=shares, token=token, tx=tx)
    source['condition_id'] = condition
    module = sorted(MODULES)[0]
    logs = [event(PM, SINGLE, [AUTO, MAKER, module], ['uint256', 'uint256'], [int(token), quantity_native], 0),
            event(PM, SINGLE, [module, module, ZERO], ['uint256', 'uint256'], [int(token), quantity_native], 1),
            event(module, POSITION, [AUTO, int(token), AUTO], ['uint256', 'uint256'], [quantity_native, payout_native], 2),
            log(payout_native, index=3),
            event(AUTO, AUTO_POSITION, [MAKER, int(token)], ['uint256'], [payout_native], 4)]
    for row in logs:
        row['transactionHash'] = tx
    receipt = {'transactionHash': tx, 'blockHash': BLOCK, 'blockNumber': '0x123', 'status': '0x1', 'logs': logs}
    return source, {'transaction_hash': tx, 'rows': [source], 'rows_sha256': digest([source]),
                    'receipt': rpc_packet(receipt), 'failure_type': None}


def profitable_wallet(tmp_path):
    clock = Clock()
    clock.value = NOW
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=clock.now, maker_address=MAKER)
    baseline = take_baseline(label='t40', now=clock.now(), maker_address=MAKER,
        positions=[], open_orders=[], available_collateral='300')
    write_baseline(tmp_path, baseline, ledger)
    filled(ledger, 'carry', token='103', condition='0x' + 'd' * 64)
    for number in range(5):
        filled(ledger, 'winner-' + str(number), token='101', condition='0x' + 'c' * 64, price='.17')
    synchronize(ledger, baseline, observation(ledger, clock,
        positions={'103': '20', '101': '100'}, cash='273'), anchor_mode='enrollment')
    clock.value += timedelta(seconds=10)
    ledger.record('session_start', session_id='past', autostart_attempt_id='a' * 32)
    clock.value += timedelta(seconds=40)
    ledger.record('session_end', session_id='past')
    clock.value += timedelta(seconds=10)
    source, proof = single_redemption('101', '100', '100', '0x' + 'c' * 64, '0x' + '1' * 64)
    source['timestamp'] = int(clock.now().timestamp())
    proof.update(rows=[source], rows_sha256=digest([source]))
    record_activity(ledger, source, native_evidence=proof)
    clock.value += timedelta(minutes=10)
    assert CapitalBook(ledger).figures(loss_basis='net_of_retained_gains')['retained_gains_available_native'] == 83_000_000
    return ledger, clock


def cash_activity(clock, kind, amount, *, timestamp=None):
    source = activity(cash=str(amount), size='0', token='', tx='0x' + '2' * 64, kind=kind)
    source['timestamp'] = timestamp if timestamp is not None else int(clock.now().timestamp()) - 20
    if kind == 'TIP':
        source['side'] = 'OUT'
    incoming = kind == 'DEPOSIT'
    proof = transfer_proof([source], incoming=int(Decimal(amount) * 1_000_000) if incoming else 0,
                           outgoing=0 if incoming else int(Decimal(amount) * 1_000_000))
    receipt = strict_json(response_bytes(proof['receipt']))['result']
    receipt['transactionHash'] = source['transaction_hash']
    for row in receipt['logs']:
        row['transactionHash'] = source['transaction_hash']
    proof.update(transaction_hash=source['transaction_hash'], receipt=rpc_packet(receipt))
    return source, proof


def observed(ledger, clock, source, proof, cash, *, positions=None):
    read = observation(ledger, clock, positions={'103': '20'} if positions is None else positions, cash=cash)
    raw = read_activity(MAKER, read['capital_activity']['scope']['start'], int(clock.now().timestamp()),
                        get=lambda *a: packet([source]), sleep=lambda _: None)
    read['capital_activity'] = {**native_packet(raw), 'native_receipts': {source['transaction_hash']: proof}}
    return read


@pytest.mark.parametrize('reopen', [False, True])
@pytest.mark.parametrize('kind,cash,external,gain,cost', [
    ('DEPOSIT', '423', 50_000_000, 83_000_000, 0),
    ('WITHDRAWAL', '323', 0, 33_000_000, 0),
    ('TIP', '323', 0, 33_000_000, 0),
    ('MASKED', '363', 40_000_000, 33_000_000, 0),
    ('SESSION', '323', 0, 33_000_000, 50_000_000)])
def test_c2_c6_late_cash_is_absorbed_once_at_captured_time(tmp_path, reopen, kind, cash, external, gain, cost):
    ledger, clock = profitable_wallet(tmp_path)
    source, proof = cash_activity(clock, 'WITHDRAWAL' if kind in {'MASKED', 'SESSION'} else kind, '50',
        timestamp=int(NOW.timestamp()) + 30 if kind == 'SESSION' else None)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={'103': '20'}, cash=cash), anchor_mode='session')
    if reopen:
        ledger = Ledger.open(ledger.path, clock=clock.now)
    before = CapitalBook(ledger)
    before_gain = before.figures(loss_basis='net_of_retained_gains')['retained_gains_available_native']
    clock.value += timedelta(seconds=90)
    read = observed(ledger, clock, source, proof, cash)
    result = synchronize(ledger, before.inventory_anchor, read)
    book = CapitalBook(ledger)
    figures = book.figures(loss_basis='net_of_retained_gains')
    assert result['cash_bridge_complete']
    assert book.expected_cash() == before.expected_cash() == int(Decimal(cash) * 1_000_000)
    assert book.external == external and book.costs == cost
    assert figures['retained_gains_available_native'] == gain
    assert gain <= before_gain and figures['funding_native'] == 300_000_000
    assert book.external + book.profit + book.incentives == before.external + before.profit + before.incentives
    raw = ledger.path.read_bytes()
    synchronize(ledger, book.inventory_anchor, read)
    assert ledger.path.read_bytes() == raw
    replay = CapitalBook(Ledger.open(ledger.path, clock=clock.now))
    assert replay.figures(loss_basis='net_of_retained_gains') == figures


@pytest.mark.parametrize('redemption', [False, True])
def test_c7_pending_credit_and_masked_owner_debit_do_not_raise_expected_cash(tmp_path, redemption):
    ledger, clock = profitable_wallet(tmp_path)
    if redemption:
        source, proof = single_redemption('103', '20', '20', '0x' + 'd' * 64, '0x' + '2' * 64)
        source['timestamp'] = int(clock.now().timestamp()) - 20
        proof.update(rows=[source], rows_sha256=digest([source]))
    else:
        source, proof = cash_activity(clock, 'DEPOSIT', '20')
    pending = {**proof, 'receipt': rpc_packet(None)}
    positions = {} if redemption else {'103': '20'}
    read = observed(ledger, clock, source, pending, '373', positions=positions)
    result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    assert result['cash_bridge_complete']
    before = CapitalBook(ledger)
    assert before.cash_reference['included_incoming'][next(iter(before.incoming_quarantines))] == 20_000_000
    clock.value += timedelta(seconds=90)
    after = observed(ledger, clock, source, proof, '373', positions=positions)
    result = synchronize(ledger, before.inventory_anchor, after)
    book = CapitalBook(ledger)
    assert result['cash_bridge_complete'] and book.expected_cash() == before.expected_cash() == 373_000_000
    assert book.figures()['funding_native'] == 300_000_000
    raw = ledger.path.read_bytes()
    synchronize(ledger, book.inventory_anchor, after)
    assert ledger.path.read_bytes() == raw
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == book.figures()
