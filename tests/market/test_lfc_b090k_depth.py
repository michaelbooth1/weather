"""Guards: B090-K thin depth cancels/proves/pauses without changing arm, caps or budgets."""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_f2_repost import fixture
from tests.market.test_lfc_f2_breadth import start, post
from tests.market.test_lfc_f2_capital import ledger_at
from weather.market.lfc_capital import CapitalRefused
from weather.market.lfc_f2_breadth import daily_gate
from weather.market.lfc_recording_io import strict_json
from weather.market.mm_stage2_hold import HoldEnd


def depth_fixture(tmp_path, *, restore_at=180):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, seconds=600, min_depth='40')
    account.fills_enabled = False
    band, raw = controller.bands[0], account.raws[0]
    ordinary = raw.snapshot
    sampled = []
    def snapshot(condition, tokens, *, checkpoint=lambda: None):
        result = ordinary(condition, tokens, checkpoint=checkpoint)
        sampled.append(clock.seconds)
        if 60 <= clock.seconds < restore_at:
            result = deepcopy(result)
            for side in ('yes_bids', 'yes_asks'):
                result['quote_inputs'][side] = [dict(result['quote_inputs'][side][0], size='20')]
        return result
    raw.snapshot = snapshot
    return controller, account, ledger, clock, band, raw, sampled


def test_thin_depth_proves_cancels_and_resumes_same_band_only_after_fresh_pass(tmp_path):
    controller, account, ledger, clock, band, raw, sampled = depth_fixture(tmp_path)
    original_arm = {key: band.scope[key] for key in ('quote_offset_pusd', 'quote_arm', 'trade_legs')}
    result = controller.run()
    assert result['cleanup_ok'], result
    assert controller.results[band.session_id]['reason'] == 'fixed_end'
    assert band.submits == 4 and band.requotes == 0
    assert {key: band.scope[key] for key in original_arm} == original_arm
    assert all(row['condition_id'] == band.condition for row in band.own_trades.rows())
    assert sorted(set(t for t in sampled if 60 <= t <= 180)) == [60, 120, 180]
    assert all(not any(oid.startswith('0-') for oid in ids)
               for t, ids in account.exposure if 61 <= t < 180)
    assert any(len(ids) == 4 for t, ids in account.exposure if 181 <= t < 600)
    assert all(t >= 600 for t, _ in account.raws[1].cancellations)
    rows = [strict_json(line) for line in band.journal.path.read_bytes().splitlines()]
    assert len([row for row in rows if row['event'] == 'depth_paused']) == 2
    assert len([row for row in rows if row['event'] == 'depth_resumed']) == 1
    assert not ledger.unresolved_legs()


@pytest.mark.parametrize('stop', ['fixed_end', 'owner_stop', 'submit_budget', 'capital'])
def test_depth_pause_keeps_end_stop_budgets_and_cap_gates(tmp_path, stop):
    controller, account, ledger, clock, band, raw, sampled = depth_fixture(tmp_path, restore_at=600 if stop == 'fixed_end' else 180)
    if stop == 'owner_stop':
        account.stop_at = 90
    if stop == 'submit_budget':
        band.MAX_SUBMITS = 2
    if stop == 'capital':
        ordinary = band.authorize_post
        def refused(*args):
            if clock.seconds >= 180:
                raise HoldEnd('per_band_daily_filled_cap')
            return ordinary(*args)
        band.authorize_post = refused
    result = controller.run()
    expected = 'per_band_daily_filled_cap' if stop == 'capital' else stop
    assert controller.results[band.session_id]['reason'] == expected
    assert band.submits == 2 and not ledger.unresolved_legs()
    assert account.cancel_all_calls == [90 if stop == 'owner_stop' else 600]


def test_nonterminal_cancel_never_reposts_after_depth_pause(tmp_path):
    controller, account, ledger, clock, band, raw, _ = depth_fixture(tmp_path)
    ordinary = raw.cancel
    def stuck(oid):
        if clock.seconds < 600:
            return {'canceled': [oid], 'not_canceled': {}}
        return ordinary(oid)
    raw.cancel = stuck
    result = controller.run()
    assert band.submits == 2 and not result['cleanup_ok']
    assert not any(row['event'] == 'depth_resumed' for row in
                   map(strict_json, band.journal.path.read_bytes().splitlines()))


def test_daily_cap_refusal_retains_exact_six_native_figures_without_rule_change(tmp_path):
    ledger = ledger_at(tmp_path)
    row = start(ledger, 'band')
    post(ledger, 'band', 'yes', price='.24')
    ledger.ack('yes', 'order-yes')
    ledger.terminal('order-yes', {'id': 'order-yes', 'status': 'MATCHED', 'size_matched': '20'}, source='test')
    post(ledger, 'band', 'no', price='.76', size='10')
    ledger.ack('no', 'order-no')
    ledger.terminal('order-no', {'id': 'order-no', 'status': 'MATCHED', 'size_matched': '10'}, source='test')
    # Historical helper cap is 40; use a read-only start view for the actual 30 rail.
    row = dict(row, per_band_daily_filled_cap_pusd='30')
    rows = []
    sink = SimpleNamespace(record=lambda event, **fields: rows.append({'event': event, **fields}))
    with pytest.raises(CapitalRefused, match='per_band_daily_filled_cap'):
        daily_gate(ledger, row, reserve=Decimal('19.40'), journal=sink)
    assert rows == [{'event': 'per_band_daily_filled_cap', 'filled_native': 12_400_000,
        'resting_native': 0, 'own_native': 0, 'proposed_native': 19_400_000,
        'cap_native': 30_000_000, 'headroom_native': 17_600_000}]
    assert daily_gate(ledger, row, reserve=Decimal('17.60'))['remaining_native'] == 0
