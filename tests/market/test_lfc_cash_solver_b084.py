"""Guards: B084 unique cash solving, fixed personal terms and conservative anchors."""
from datetime import timedelta
from decimal import Decimal
from itertools import product

import pytest

from tests.market.test_lfc_f2_overlap_b082 import wallet, feed
from tests.market.test_lfc_f2_inventory_b080 import observation
from tests.market.test_lfc_f2_personal_cash_b081 import owner_trade
from weather.market.lfc_campaign import TransientPrecheck
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_capital_reads import synchronize
from weather.market.lfc_ledger import Ledger
from weather.market.mm_stage2_hold import digest


@pytest.mark.parametrize('residual', ['0', '-0.05', '0.05'])
@pytest.mark.parametrize('reopen', [False, True])
@pytest.mark.parametrize('side', ['BUY', 'SELL'])
def test_late_same_second_receipt_with_personal_trade_and_fee_reanchors(tmp_path, residual, reopen, side):
    ledger, _, clock, source, proof, tokens, _ = wallet(tmp_path)
    second = clock.now()
    clock.value += timedelta(microseconds=250000)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={**{token: '20' for token in tokens},
            **({'90': '20'} if side == 'SELL' else {})}, cash='290'), anchor_mode='session')
    source['timestamp'] = int(second.timestamp())
    proof.update(rows=[source], rows_sha256=digest([source]))
    clock.value += timedelta(seconds=2)
    cash = str(Decimal('310') + (Decimal('10.4') if side == 'SELL' else -Decimal('10.4')) -
               Decimal('.49920') + Decimal(residual))
    read = feed(ledger, clock, source, proof, {'90': '20'} if side == 'BUY' else {}, cash)
    trade = owner_trade(clock, side)
    trade['fee_rate_bps'] = '1000'
    read['trades'] = [trade]
    result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session',
                         loss_basis='net_of_retained_gains')
    book = CapitalBook(ledger)
    assert result['cash_bridge_complete'] and result['inventory']['changed'] == []
    assert book.expected_cash() == int(Decimal(cash) * 1_000_000)
    assert len(book.personal_trades) == 1
    assert next(iter(book.personal_trades.values()))['fee_native'] == 499200
    expected_gain = 9_500_800 if side == 'SELL' and residual == '0' else 0
    assert book.figures(loss_basis='net_of_retained_gains')['retained_gains_available_native'] == expected_gain
    if residual != '0':
        assert any(value.get('surplus_only') for value in book.cash_capture_bindings.values())
        assert book.profit == 0  # An ambiguous inclusion never books refill gain.
    else:
        assert all(not value.get('surplus_only') for value in book.cash_capture_bindings.values())
    if reopen:
        ledger = Ledger.open(ledger.path, clock=clock.now)
    raw = ledger.path.read_bytes()
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read)['cash_bridge_complete']
    assert ledger.path.read_bytes() == raw
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == CapitalBook(ledger).figures()


@pytest.mark.parametrize('reopen', [False, True])
def test_persistent_unexplained_difference_can_close_only_at_session_anchor(tmp_path, reopen):
    ledger, _, clock, source, proof, tokens, _ = wallet(tmp_path)
    second = clock.now()
    clock.value += timedelta(microseconds=250000)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={token: '20' for token in tokens}, cash='290'), anchor_mode='session')
    source['timestamp'] = int(second.timestamp())
    proof.update(rows=[source], rows_sha256=digest([source]))
    clock.value += timedelta(seconds=2)
    read = feed(ledger, clock, source, proof, {}, '300')
    with pytest.raises(TransientPrecheck, match='capital_cash_snapshot_pending'):
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, read)
    if reopen:
        ledger = Ledger.open(ledger.path, clock=clock.now)
    result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    book = CapitalBook(ledger)
    assert result['cash_bridge_complete'] and book.expected_cash() == 300_000_000
    assert book.profit == 0 and book.figures()['retained_gains_available_native'] == 0
    assert book.figures()['headroom_native'] <= 300_000_000
    raw = ledger.path.read_bytes()
    clock.value += timedelta(seconds=901)
    fresh = feed(ledger, clock, source, proof, {}, '300')
    assert synchronize(ledger, book.inventory_anchor, fresh)['cash_bridge_complete']
    assert ledger.path.read_bytes() == raw
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == book.figures()
    # B085: a later claim must not invalidate this historical fallback's cut.
    from tests.market.test_lfc_campaign import MAKER, Mutexes
    from weather.market.lfc_campaign_guard import account_lease
    with account_lease(MAKER, backend=Mutexes()):
        ledger.record('autostart_enroll', state_id='e'*32, identity_sha256='f'*64,
                      state_root=str(tmp_path/'synthetic-state'), protocol='lfc_autostart_v1')
        ledger.record('autostart_claim', attempt_id='a'*32, file_sha256='b'*64,
                      local_date=clock.now().date().isoformat())
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == CapitalBook(ledger).figures()


def test_target_aware_solver_matches_exhaustive_signed_sums():
    from weather.market.lfc_f2_cash_snapshot import solve
    for amounts in ((3, 4, 9, 12), (-3, 4, -9, 12), (20, 20, -10), (1, 2, 4, 8, 16)):
        variables = [(str(i), amount) for i, amount in enumerate(amounts)]
        solutions = {}
        for flags in product((False, True), repeat=len(amounts)):
            chosen = frozenset(str(i) for i, flag in enumerate(flags) if flag)
            total = sum(amount for amount, flag in zip(amounts, flags) if flag)
            solutions.setdefault(total, []).append(chosen)
        for target in range(sum(min(0, n) for n in amounts) - 1, sum(max(0, n) for n in amounts) + 2):
            expected = solutions.get(target, [])
            if len(expected) == 1:
                assert solve(variables, target) == expected[0]
            else:
                with pytest.raises(TransientPrecheck, match='capital_cash_snapshot_pending'):
                    solve(variables, target)


@pytest.mark.parametrize('all_fresh', [False, True])
def test_extreme_and_sparse_target_do_not_enumerate_every_subset(all_fresh):
    from weather.market.lfc_f2_cash_snapshot import solve
    variables = [(str(i), 20_000_000 + i) for i in range(200)]
    assert solve(variables, sum(n for _, n in variables) if all_fresh else 0) == (
        frozenset(key for key, _ in variables) if all_fresh else frozenset())
    assert solve([(str(i), 2**i) for i in range(100)], 2**99 + 1) == frozenset({'0', '99'})


@pytest.mark.parametrize('reopen', [False, True])
@pytest.mark.parametrize('interrupted', [False, True])
def test_nonunique_batch_never_promotes_a_peer_to_campaign_gain(tmp_path, reopen, interrupted, monkeypatch):
    from tests.market.test_lfc_f2_cash_mirror_b082 import single_redemption
    from tests.market.test_lfc_f2_capital import filled, MAKER
    from tests.market.test_lfc_f2_capital_reads import native_packet, packet, rpc_packet
    from weather.market.lfc_capital_reads import read_activity
    from weather.market.lfc_recording_io import response_bytes, strict_json
    ledger, _, clock, first, first_proof, tokens, _ = wallet(tmp_path)
    filled(ledger, 'second-lot', token='203', condition='0x'+'6'*64)
    second, second_proof = single_redemption('203', '20', '20', '0x'+'e'*64, '0x'+'6'*64)
    # Distinct native blocks may straddle the snapshot within one event second.
    receipt = strict_json(response_bytes(second_proof['receipt']))['result']
    receipt.update(blockHash='0x'+'9'*64, blockNumber='0x124')
    for log in receipt['logs']:
        if 'blockHash' in log:
            log['blockHash'] = receipt['blockHash']
        if 'blockNumber' in log:
            log['blockNumber'] = receipt['blockNumber']
    second_proof['receipt'] = rpc_packet(receipt)
    stamp = clock.now()
    clock.value += timedelta(microseconds=250000)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={**{token: '20' for token in tokens}, '203': '20'}, cash='280'),
        anchor_mode='session')
    for row, proof in ((first, first_proof), (second, second_proof)):
        row['timestamp'] = int(stamp.timestamp())
        proof.update(rows=[row], rows_sha256=digest([row]))
    clock.value += timedelta(seconds=2)
    read = observation(ledger, clock, positions={}, cash='300')
    raw = read_activity(MAKER, read['capital_activity']['scope']['start'], int(clock.now().timestamp()),
                        get=lambda *args: packet([first, second]), sleep=lambda _: None)
    read['capital_activity'] = {**native_packet(raw), 'native_receipts': {
        first['transaction_hash']: first_proof, second['transaction_hash']: second_proof}}
    if reopen:
        ledger = Ledger.open(ledger.path, clock=clock.now)
    if interrupted:
        original = ledger.record
        def record(event, **fields):
            result = original(event, **fields)
            if event == 'capital_activity':
                raise OSError('injected interruption after durable first fallback')
            return result
        monkeypatch.setattr(ledger, 'record', record)
        with pytest.raises(OSError, match='injected interruption'):
            synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
        monkeypatch.setattr(ledger, 'record', original)
        if reopen:
            ledger = Ledger.open(ledger.path, clock=clock.now)
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')['cash_bridge_complete']
    book = CapitalBook(ledger)
    assert book.profit == 0 and book.figures()['retained_gains_available_native'] == 0
    assert all(value.get('surplus_only') for value in book.cash_capture_bindings.values())
    assert book.expected_cash() == 300_000_000
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == book.figures()
