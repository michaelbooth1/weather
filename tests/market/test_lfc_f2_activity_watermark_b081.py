"""Guards: B081 activity coverage and snapshot time survive slow native reads."""
from datetime import timedelta

import pytest

from tests.market.test_lfc_f2_inventory_b080 import fixture, observation
from tests.market.test_lfc_f2_capital import MAKER
from tests.market.test_lfc_f2_capital_reads import native_packet, packet
from tests.market.test_lfc_redemption_native import paired
from weather.market.lfc_capital import CapitalBook, CapitalRefused
from weather.market.lfc_capital_reads import read_activity, synchronize
from weather.market.lfc_f2_inventory import activity_start
from weather.market.lfc_ledger import Ledger, LedgerUnavailable
from weather.market.mm_stage2_hold import digest


@pytest.mark.parametrize('reopen', [False, True])
def test_personal_auto_redemption_during_native_collection_uses_snapshot_time(tmp_path, reopen):
    ledger, baseline, clock, _ = fixture(tmp_path, personal=False, bridge=False)
    source, proof, tokens = paired(auto=True)
    # These owner tokens were acquired after enrollment. Their redemption must
    # use the new snapshot's quantities even though its read finishes later.
    synchronize(ledger, baseline, observation(ledger, clock,
        positions={'denver': '20'}, cash='290'), anchor_mode='enrollment')
    clock.value += timedelta(days=1)
    read = observation(ledger, clock,
        positions={'denver': '20', **{token: '20' for token in tokens}}, cash='290')
    cutoff = read['capital_activity']['scope']['end']
    source['timestamp'] = cutoff + 1
    proof.update(rows=[source], rows_sha256=digest([source]))
    clock.value += timedelta(seconds=2)
    read['ended_at_utc'] = clock.now().isoformat()
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    if reopen:
        ledger = Ledger.open(ledger.path, clock=clock.now)
    anchor = CapitalBook(ledger).inventory_anchor
    assert anchor['activity_covered_through'] == cutoff
    assert anchor['snapshot_at_utc'] == read['component_times']['positions']['started_at_utc']
    clock.value += timedelta(seconds=1)
    after = observation(ledger, clock, positions={'denver': '20'}, cash='310')
    since = activity_start(ledger, after['started_at_utc'])
    after['capital_activity'] = native_packet(read_activity(MAKER, since, int(clock.now().timestamp()),
        get=lambda _, params: packet([source] if params['start'] <= source['timestamp'] <= params['end'] else []),
        sleep=lambda _: None))
    after['capital_activity']['native_receipts'] = {source['transaction_hash']: proof}
    result = synchronize(ledger, anchor, after)
    assert result['cash_bridge_complete'] and result['inventory']['changed'] == []
    book = CapitalBook(ledger)
    assert book.profit == 0 and book.external == 20_000_000
    assert book.figures()['funding_native'] == 300_000_000
    assert synchronize(ledger, anchor, after) == result  # Overlap deduplicates.


def test_anchor_cannot_claim_activity_coverage_after_the_queried_end(tmp_path):
    ledger, baseline, clock, _ = fixture(tmp_path)
    read = observation(ledger, clock, positions={'denver': '20'}, cash='290')
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    anchor = dict(CapitalBook(ledger).inventory_anchor)
    anchor['activity_covered_through'] += 1
    before = ledger.path.read_bytes()
    with pytest.raises(LedgerUnavailable, match='f2_anchor_activity_binding'):
        ledger.record('f2_session_anchor', anchor={**anchor, 'ledger_cut': len(ledger.rows),
            'ledger_head_sha256': ledger.previous}, anchor_sha256=digest({**anchor,
            'ledger_cut': len(ledger.rows), 'ledger_head_sha256': ledger.previous}),
            previous_anchor_sha256=digest(CapitalBook(ledger).inventory_anchor), read_sha256=anchor['read_sha256'])
    assert ledger.path.read_bytes() == before
