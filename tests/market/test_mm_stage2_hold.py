from datetime import timedelta
import hashlib
import json

import pytest

from weather.market.mm_live_envelope import STAGE2_HOLD_V1 as PROFILE
from weather.market.mm_stage2_hold import CONFIRMATION, run_hold_session, verify_prediction_journal, canonical_bytes
from tests.market.stage2_fakes import Clock, Venue, adapters_and_gates, CONDITION, TOKENS, MAKER


def run(tmp_path, *, change=None, stop_at=None, seconds=125):
    clock = Clock()
    venue = Venue(clock)
    adapters, gates = adapters_and_gates(tmp_path / 'authority', clock, venue)
    if change:
        change(venue)
    scope = {'profile_sha256': PROFILE.sha256, 'selection_sha256': 'c' * 64,
             'condition_id': CONDITION, 'token_ids': list(TOKENS), 'maker_address': MAKER,
             'end_at_utc': (clock.now() + timedelta(seconds=seconds)).isoformat()}
    result = run_hold_session(
        adapters, gates, scope=scope, initial_public=venue.snapshot(),
        public_reader=getattr(venue, 'public_reader', venue.snapshot), geography_reader=venue.geography,
        journal_path=tmp_path / 'journal.jsonl', prediction_path=tmp_path / 'prediction.json',
        confirmation=CONFIRMATION,
        operator_stop=lambda: stop_at is not None and clock.seconds >= stop_at,
        scoring_reader=lambda ids: dict.fromkeys(ids, True), utc_clock=clock.now,
        monotonic_clock=clock.monotonic, sleeper=clock.sleep, mode='rehearsal',
    )
    rows = [json.loads(line) for line in (tmp_path / 'journal.jsonl').read_text().splitlines()]
    return result, venue, rows


def assert_clean(result, venue, rows):
    assert result['cleanup_ok'], result
    assert result['cancel_acknowledged'], result
    assert not list(venue.list_open_orders().iter_items())
    assert sum(call[0] == 'fake_submit' for call in venue.calls) <= 2
    assert any(row['event'] == 'cancel_all_acknowledged' for row in rows)
    assert not result['earnings_read']


def test_timeout_holds_two_single_use_tokens_and_one_heartbeat(tmp_path):
    result, venue, rows = run(tmp_path)
    assert_clean(result, venue, rows)
    assert result['end_condition'] == 'timeout', result
    assert result['visible_two_sided_minutes'] == 2
    assert result['P_many'] > 0 and result['P_single'] > 0
    submits = [call for call in venue.calls if call[0] == 'fake_submit']
    assert submits == [('fake_submit', '111'), ('fake_submit', '222')]
    first = venue.calls.index(submits[0])
    second = venue.calls.index(submits[1])
    assert ('open_orders', ()) in venue.calls[:first]
    assert ('open_orders', ('fixture-order-1',)) in venue.calls[first:second]
    beats = [call[1] for call in venue.calls if call[0] == 'heartbeat']
    assert beats == list(range(0, 125, 5))
    assert result['journal_sha256'] == hashlib.sha256((tmp_path / 'journal.jsonl').read_bytes()).hexdigest()
    previous = None
    for sequence, line in enumerate((tmp_path / 'journal.jsonl').read_bytes().splitlines(keepends=True)):
        row = json.loads(line)
        assert row['sequence'] == sequence and row['previous_sha256'] == previous
        previous = hashlib.sha256(line).hexdigest()


@pytest.mark.parametrize(('attribute', 'value', 'reason'), [
    ('reject_second', True, 'control_or_transport_failure'),
    ('fill_at', 12, 'fill'),
    ('fail_heartbeat_at', 10, 'heartbeat_loss'),
    ('fail_geoblock_at', 30, 'geoblock'),
])
def test_end_conditions_cancel_both_legs(tmp_path, attribute, value, reason):
    result, venue, rows = run(tmp_path, change=lambda v: setattr(v, attribute, value))
    assert_clean(result, venue, rows)
    assert result['end_condition'] == reason, result
    assert result['fill_seen'] is (attribute == 'fill_at')


def test_operator_stop_cancels_both(tmp_path):
    result, venue, rows = run(tmp_path, stop_at=8)
    assert_clean(result, venue, rows)
    assert result['end_condition'] == 'operator_stop'


@pytest.mark.parametrize(('key', 'value', 'reason'), [
    ('reward_min_size', '100', 'reward_minimum_outside_treatment'),
    ('reward_rate_per_day', '39', 'reward_terms_outside_treatment'),
    ('yes_bids', [], 'one_sided_book'),
])
def test_public_end_conditions_cancel_both(tmp_path, key, value, reason):
    def change(venue):
        venue.public_change = lambda values: values.update({key: value})
    result, venue, rows = run(tmp_path, change=change)
    assert_clean(result, venue, rows)
    assert result['end_condition'] == reason, result
    assert result['reward_terms_changed'] is key.startswith('reward_')
    verify_prediction_journal(result, tmp_path / 'journal.jsonl')


def test_primary_cancel_failure_is_no_go_even_when_deadman_clears(tmp_path):
    result, venue, rows = run(tmp_path, change=lambda v: setattr(v, 'cancel_unavailable', True), stop_at=8)
    assert not result['cleanup_ok'] and not result['cancel_acknowledged']
    assert not list(venue.list_open_orders().iter_items())
    backstop = [r for r in rows if r['event'] == 'dead_man_backstop_observed']
    assert len(backstop) == 1 and backstop[0]['accepted_window']
    assert backstop[0]['heartbeat_age_seconds'] == 12


def test_midpoint_drift_cancels_original_prices_without_requote(tmp_path):
    def change(venue):
        def shift(values):
            for key, price in [('yes_bids', '.35'), ('yes_asks', '.36'),
                               ('no_bids', '.64'), ('no_asks', '.65')]:
                values[key][0]['price'] = price
        venue.public_change = shift
    result, venue, rows = run(tmp_path, change=change)
    assert_clean(result, venue, rows)
    assert result['end_condition'] == 'midpoint_drift'


def test_unreadable_geoblock_cancels_at_refresh(tmp_path):
    def change(venue):
        original = venue.geography
        def geography():
            if venue.clock.seconds >= 30:
                raise ConnectionError('fixture unavailable')
            return original()
        venue.geography = geography
    result, venue, rows = run(tmp_path, change=change)
    assert_clean(result, venue, rows)
    assert result['end_condition'] == 'geoblock'
    trigger = next(r for r in rows if r['event'] == 'end_condition')
    assert trigger['recorded_at_utc'].endswith('12:00:35+00:00')


def test_shared_heartbeat_never_extends_source_lease(tmp_path):
    clock = Clock()
    venue = Venue(clock)
    a, _ = adapters_and_gates(tmp_path / 'authority', clock, venue)
    a[0].heartbeat()
    clock.sleep(7)
    a[1].accept_shared_stage2_heartbeat(a[0])
    assert a[1]._last_heartbeat_monotonic == 0
    clock.sleep(1)
    with pytest.raises(RuntimeError):
        a[1].accept_shared_stage2_heartbeat(a[0])
    assert sum(call[0] == 'heartbeat' for call in venue.calls) == 1


def test_slow_public_responses_keep_checking_controls_between_reads(tmp_path):
    def change(venue):
        original = venue.snapshot
        def read(*, checkpoint=lambda: None):
            # Five two-second HTTP responses, each using the controller's
            # real checkpoint. No control function is replaced.
            for _ in range(5):
                checkpoint()
                venue.clock.sleep(2)
                checkpoint()
            return original()
        venue.public_reader = read
    result, venue, rows = run(tmp_path, change=change, seconds=145)
    assert_clean(result, venue, rows)
    assert result['end_condition'] == 'timeout'
    assert result['visible_two_sided_minutes'] > 0
    verify_prediction_journal(result, tmp_path / 'journal.jsonl')


def test_no_fill_cash_change_cannot_pass_reconciliation(tmp_path):
    def change(venue):
        original = venue.cancel_all
        def cancel():
            result = original()
            venue.cash = '49000000'
            return result
        venue.cancel_all = cancel
    result, venue, rows = run(tmp_path, change=change, stop_at=8)
    assert result['cancel_acknowledged'] and not result['cleanup_ok']
    assert not list(venue.list_open_orders().iter_items())


def test_rehashed_journal_without_cancellation_ack_is_not_evidence(tmp_path):
    result, venue, rows = run(tmp_path)
    rows = [r for r in rows if r['event'] != 'cancel_all_acknowledged']
    previous, output = None, b''
    for i, row in enumerate(rows):
        row.update(sequence=i, previous_sha256=previous)
        raw = canonical_bytes(row)
        previous = hashlib.sha256(raw).hexdigest()
        output += raw
    path = tmp_path / 'edited.jsonl'
    path.write_bytes(output)
    result['journal_sha256'] = hashlib.sha256(output).hexdigest()
    with pytest.raises(ValueError, match='cleanup lacks'):
        verify_prediction_journal(result, path)
