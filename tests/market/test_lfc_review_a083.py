"""Guards: B084 adopts the unchanged A083 atomic-block assertions.

A complete atomic block of personal redemptions must not strand admission.

All native receipts share a block. The cash snapshot includes NONE or ALL of
that block; it never splits its receipts. Whole-second activity timestamps
overlap the fractional cash snapshot, exactly the B083 interval contract.
"""
from datetime import timedelta
from decimal import Decimal
import pytest

from tests.market.test_lfc_f2_overlap_b082 import wallet
from tests.market.test_lfc_f2_cash_mirror_b082 import single_redemption
from tests.market.test_lfc_f2_inventory_b080 import observation
from tests.market.test_lfc_f2_capital import MAKER
from tests.market.test_lfc_f2_capital_reads import native_packet, packet
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_capital_reads import read_activity, synchronize
from weather.market.lfc_campaign import TransientPrecheck
from weather.market.lfc_ledger import Ledger
from weather.market.mm_stage2_hold import digest


@pytest.mark.parametrize('count', [12, 13])
@pytest.mark.parametrize('captured', [False, True])
@pytest.mark.parametrize('reopen', [False, True])
def test_atomic_personal_redemption_block_resolves_complete_cash(tmp_path, count, captured, reopen):
    ledger, baseline, clock, _, _, old_tokens, campaign = wallet(tmp_path, campaign=False, enroll=False)
    positions = {campaign: '20', **{token: '20' for token in old_tokens}}
    pairs = []
    total = 0
    for number in range(count):
        token = str(203 + number)
        # Ordinary ~20-share holdings; small unique fractional parts give
        # 2**count distinct subset sums without huge wallet value or dust lots.
        amount = 20_000_000 + 2**number
        size = str(Decimal(amount) / 1_000_000)
        positions[token] = size
        row, proof = single_redemption(token, size, size,
            '0x'+format(203+number, '064x'), '0x'+format(1003+number, '064x'))
        pairs.append((row, proof))
        total += amount
    synchronize(ledger, baseline, observation(ledger, clock, positions=positions, cash='290'),
                anchor_mode='enrollment')
    clock.value += timedelta(days=1)
    second = clock.now()
    clock.value += timedelta(microseconds=250000)
    final_cash = str(Decimal(290_000_000 + total) / 1_000_000)
    # All transactions are in one atomic block: ALL captured, or NONE.
    # For captured=True only the public position/activity indexes lag.
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions=positions, cash=final_cash if captured else '290'),
        anchor_mode='session')
    for row, proof in pairs:
        row['timestamp'] = int(second.timestamp())
        proof.update(rows=[row], rows_sha256=digest([row]))
    outcomes = []
    for offset in (2, 3, 901):
        if reopen:
            ledger = Ledger.open(ledger.path, clock=clock.now)
        clock.value = second + timedelta(seconds=offset)
        read = observation(ledger, clock,
            positions={campaign:'20', **{token:'20' for token in old_tokens}}, cash=final_cash)
        raw = read_activity(MAKER, read['capital_activity']['scope']['start'], int(clock.now().timestamp()),
            get=lambda *a: packet([row for row, _ in pairs]), sleep=lambda _: None)
        read['capital_activity'] = {**native_packet(raw), 'native_receipts': {
            row['transaction_hash']: proof for row, proof in pairs}}
        try:
            result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
            outcomes.append('clean' if result['cash_bridge_complete'] else 'incomplete')
        except TransientPrecheck as exc:
            outcomes.append(str(exc))
    assert outcomes[1:] == ['clean', 'clean'], outcomes
    book = CapitalBook(ledger)
    assert book.expected_cash() == 290_000_000 + total
    assert book.external == total and book.profit == 0
    assert book.figures()['funding_native'] == 300_000_000
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == book.figures()
