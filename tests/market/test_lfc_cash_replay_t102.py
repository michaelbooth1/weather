"""Guards: T102 captured-debit costs agree for writer and dirty replay pools."""
from copy import deepcopy
from datetime import timedelta

from tests.market.test_lfc_f2_personal_cash_b081 import gained_wallet
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_f2_wallet_cash import captured_debit


def test_two_native_debits_keep_costs_identical_on_warm_and_cold_reopen(tmp_path):
    from tests.market.test_lfc_f2_inventory_b080 import fixture, observation
    from tests.market.test_lfc_f2_cash_mirror_b082 import cash_activity
    from tests.market.test_lfc_f2_capital_reads import rpc_packet
    from weather.market.lfc_capital import record_activity
    from weather.market.lfc_capital_reads import synchronize
    from weather.market.lfc_ledger import Ledger
    from weather.market.lfc_recording_io import response_bytes, strict_json
    from weather.market.mm_stage2_hold import digest
    ledger, _, clock, _ = fixture(tmp_path, personal=False)
    clock.value += timedelta(seconds=10)
    ledger.record('session_start', session_id='before', autostart_attempt_id='a'*32)
    late_stamp = int(clock.now().timestamp())
    clock.value += timedelta(seconds=30)
    ledger.record('session_end', session_id='before')
    clock.value += timedelta(seconds=10)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={'denver': '20'}, cash='280'), anchor_mode='session')
    clock.value += timedelta(seconds=10)
    ledger.record('session_start', session_id='after', autostart_attempt_id='b'*32)
    first_stamp = int(clock.now().timestamp())
    clock.value += timedelta(seconds=5)
    ledger.record('session_end', session_id='after')
    first, proof = cash_activity(clock, 'WITHDRAWAL', '5', timestamp=first_stamp)
    first['transaction_hash'] = '0x'+'3'*64
    receipt = strict_json(response_bytes(proof['receipt']))['result']
    receipt['transactionHash'] = first['transaction_hash']
    for log in receipt['logs']:
        log['transactionHash'] = first['transaction_hash']
    proof.update(transaction_hash=first['transaction_hash'], rows=[first], rows_sha256=digest([first]),
                 receipt=rpc_packet(receipt))
    record_activity(ledger, first, native_evidence=proof)
    late, proof = cash_activity(clock, 'WITHDRAWAL', '10', timestamp=late_stamp)
    record_activity(ledger, late, native_evidence=proof)
    writer = CapitalBook(ledger)
    expected = writer.figures()
    assert expected['paid_or_reserved_campaign_costs_native'] == 15_000_000
    assert writer.expected_cash() == 275_000_000
    ledger._replay()
    assert CapitalBook(ledger).figures() == expected
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == expected


def test_late_captured_debit_keeps_writer_and_replay_costs_equal(tmp_path):
    ledger, clock, _ = gained_wallet(tmp_path)
    results = []
    for writer in (False, True):
        book = CapitalBook(ledger)
        book.inventory_anchor = None  # Pre-anchor in-session cash-cost semantics.
        book.pool_movements = []
        book.costs = book.withdrawal_costs = 0
        book.pools_dirty = True
        stamp = int(clock.now().timestamp())
        book.activity_sequences.update(earlier=100, late=101)
        earlier = {'id': 'earlier', 'timestamp': stamp-2}
        late = {'id': 'late', 'timestamp': stamp-1}
        book.withdraw(5_000_000, earlier)
        if writer:
            book.refresh_pools()  # Ledger's validation copy does this.
        book.cash_reference = {**deepcopy(book.cash_reference), 'at_utc': clock.now().isoformat(),
            'snapshot_at_utc': clock.now().isoformat(), 'sequence': 102, 'initial_snapshot': False}
        book.withdraw(10_000_000, late)
        captured_debit(book, late, 10_000_000)
        book.refresh_pools()
        results.append(book.costs)
    assert results == [15_000_000, 15_000_000]
