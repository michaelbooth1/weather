"""Synthetic independent-review witnesses; no live clients or account calls.

Guards: B058 pre-POST aborts, delayed lifecycle events, peer cash, setup and owner terms.
"""
from decimal import Decimal

import pytest

from tests.market.test_lfc_f2_repost import fixture
from weather.market.lfc_ledger import Ledger, LedgerUnavailable
from weather.market.lfc_recording_io import strict_json


@pytest.mark.parametrize('reason', ['ledger_clock_regressed', 'ledger_write_failed',
                                  'ledger_changed_underneath', 'require_account'])
def test_intent_refusal_before_any_durable_intent_is_not_ambiguous_placement(tmp_path, monkeypatch, reason):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path)
    account.fills_enabled = False
    def refused(**kwargs):
        raise LedgerUnavailable(reason)
    monkeypatch.setattr(ledger, 'intent', refused)
    result = controller.run()
    assert ledger.legs == {} and not ledger.unacknowledged_intents()
    assert not result['unknown_submit'], result
    assert all(raw.memory.orders == {} for raw in account.raws)
    assert any(strict_json(line)['event'] == 'pre_post_abort'
               for line in controller.bands[0].journal.path.read_bytes().splitlines())


def test_durable_intent_followed_by_snapshot_failure_remains_ambiguous(tmp_path, monkeypatch):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path)
    account.fills_enabled = False
    original = ledger.intent
    def refused(**kwargs):
        original(**kwargs)
        raise LedgerUnavailable('ledger_snapshot_write_failed')
    monkeypatch.setattr(ledger, 'intent', refused)
    result = controller.run()
    assert ledger.unacknowledged_intents() and result['unknown_submit']
    assert all(raw.memory.orders == {} for raw in account.raws)


def test_twelve_band_intents_with_equal_timestamps_have_monotonic_sequences(tmp_path):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, k=12)
    try:
        for band in controller.bands:
            ledger.intent(session_id=band.session_id, intent_key=band.session_id + ':same-clock',
                condition_id=band.condition, token_id=band.tokens[0], price=str(band.prices[0]),
                size='20', fee_rate_bps='0')
        rows = [row for row in ledger.rows if row['event'] == 'leg_intent']
        assert len(rows) == 12 and len({r['recorded_at_utc'] for r in rows}) == 1
        assert [r['sequence'] for r in rows] == sorted({r['sequence'] for r in rows})
        reopened = Ledger.open(ledger.path, clock=clock.now)
        assert len(reopened.legs) == 12 and reopened.previous == ledger.previous
    finally:
        for band in controller.bands:
            band.journal.close()
        controller.journal.close()


@pytest.mark.parametrize('mutation', ['partial_append', 'same_length_edit', 'missing'])
def test_intent_absence_never_waives_changed_or_unreadable_history(tmp_path, mutation):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path)
    try:
        assert ledger.intent_proven_absent('not-appended')
        if mutation == 'partial_append':
            with ledger.path.open('ab') as handle:
                handle.write(b'{')
        elif mutation == 'same_length_edit':
            with ledger.path.open('r+b') as handle:
                handle.write(b'!')
        else:
            ledger.path.unlink()
        assert not ledger.intent_proven_absent('not-appended')
    finally:
        for band in controller.bands:
            band.journal.close()
        controller.journal.close()
