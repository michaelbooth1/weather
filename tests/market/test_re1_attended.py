"""RE-1M submit limits, reference arithmetic, and unconditional cleanup."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import json

import pytest

from tests.market.stage2_fakes import Clock, Venue, CONDITION, TOKENS
from tests.market.test_re1_attended_parity_audit import reference_evaluate
from weather.market.market_registry import REGISTRY
from weather.market.mm_stage2_selection import select_table
from weather.market.re1_attended import Session, SecretGuard, HoldEnd, observe, replacement_price
from weather.market.re1_rehearsal import RehearsalVenue


def setup(tmp_path):
    clock = Clock()
    snapshot = Venue(clock).snapshot()
    # Qualifying synthetic public selection, full competing depth.
    snapshot['quote_inputs'].update(reward_rate_per_day='100')
    table = select_table([{'market_id': 'los-angeles', 'market_timezone': REGISTRY['los-angeles'].timezone,
        'target_date': '2026-09-22', 'condition_id': CONDITION, 'token_ids': list(TOKENS), 'snapshot': snapshot}], now=clock.now())
    venue = RehearsalVenue(snapshot, tmp_path, clock=clock)
    session = Session(venue=venue, public=venue, table=table, clock=clock, directory=tmp_path)
    return session, venue, clock


def test_full_360_minute_flow_and_expiry(tmp_path):
    session, venue, clock = setup(tmp_path)
    result = session.run()
    assert result['cleanup_ok'] and not venue.open_orders()
    assert result['minute_samples'] == result['visible_two_sided_minutes'] == 360
    assert result['P_many'] > 0 and result['P_many_plain_mid'] > 0
    assert result['submits'] == 2
    assert all(r['expiration'] == int(session.end.timestamp()) + 60 for r in venue.calls)
    with pytest.raises(RuntimeError, match='one_session'):
        session.run()


def test_one_sided_book_at_open_posts_nothing(tmp_path):
    session, venue, clock = setup(tmp_path)
    original = venue.snapshot
    def snapshot(*args, **kwargs):
        value = original(*args, **kwargs)
        value['quote_inputs']['no_asks'] = []
        return value
    venue.snapshot = snapshot
    result = session.run(rehearsal_seconds=60)
    assert result['reason'] == 'one_sided_book_before_post'
    assert result['post_count'] == 0 and not venue.calls and result['cleanup_ok']


def test_cancel_wait_keeps_the_main_loop_alive(tmp_path):
    from types import SimpleNamespace
    session, venue, clock = setup(tmp_path)
    oid = session.submit(0, session.prices[0])
    ticks = []
    session.heartbeat_loop = SimpleNamespace(tick=lambda: ticks.append(clock.seconds), stop=lambda: None)
    real_open, stale, reads = venue.open_orders, venue.open_orders(), {'n': 0}
    def open_orders():
        reads['n'] += 1
        return stale if reads['n'] <= 6 else real_open()
    venue.open_orders = open_orders
    session.cancel_leg(oid)
    assert ticks and oid not in session.active
    session.cleanup()
    session.journal.close()


def test_post_read_lag_is_waited_out_but_foreign_orders_still_stop(tmp_path):
    session, venue, clock = setup(tmp_path)
    real_open, reads = venue.open_orders, {'n': 0}
    first = session.submit(0, session.prices[0])
    def lagging():
        reads['n'] += 1
        return [] if reads['n'] <= 2 else real_open()
    venue.open_orders = lagging
    second = session.submit(1, session.prices[1])
    assert first and second and reads['n'] >= 3
    venue.open_orders = lambda: real_open() + [{'id': 'foreign', 'order_id': 'foreign'}]
    session.prices = list(session.prices)
    with pytest.raises(HoldEnd, match='unexpected_open_orders'):
        session.submit(0, session.prices[0])
    session.cleanup()
    session.journal.close()


def test_second_leg_crossing_at_open_posts_nothing(tmp_path):
    session, venue, clock = setup(tmp_path)
    original = venue.snapshot
    def snapshot(*args, **kwargs):
        value = original(*args, **kwargs)
        value['quote_inputs']['no_asks'] = [{'price': str(session.prices[1]), 'size': '100'}]
        return value
    venue.snapshot = snapshot
    result = session.run(rehearsal_seconds=60)
    assert result['reason'] == 'fresh_ask_before_post'
    assert result['post_count'] == 0 and result['submits'] == 0 and not venue.calls
    assert result['cleanup_ok'] and not venue.open_orders()
    assert not list(tmp_path.glob('submit-*.intent.json'))


@pytest.mark.parametrize('cause', ['minimum', 'rate', 'one_sided', 'geoblock', 'unreadable_geo',
                                  'heartbeat', 'fill', 'exception', 'interrupt'])
def test_end_conditions_cancel_every_order(tmp_path, cause):
    session, venue, clock = setup(tmp_path)
    original = venue.snapshot
    def snapshot(*args, **kwargs):
        value = original(*args, **kwargs)
        if clock.seconds >= 60:
            inputs = value['quote_inputs']
            if cause == 'minimum': inputs['reward_min_size'] = '100'
            if cause == 'rate': inputs['reward_rate_per_day'] = '39'
            if cause == 'one_sided': inputs['yes_asks'] = []
        return value
    venue.snapshot = snapshot
    original_events = venue.events
    def events():
        if clock.seconds >= 30:
            if cause == 'exception': raise RuntimeError('test')
            if cause == 'interrupt': raise KeyboardInterrupt()
            if cause == 'fill':
                first = next(iter(venue.memory.orders.values()))
                first['size_matched'] = '0.5'
        return original_events()
    venue.events = events
    def geo():
        if cause == 'unreadable_geo' and clock.seconds >= 30: raise ConnectionError()
        return {'blocked': cause == 'geoblock' and clock.seconds >= 30}
    venue.geography = geo
    def beat():
        if cause == 'heartbeat' and clock.seconds >= 30: raise ConnectionError()
        return {'status': 'ok'}
    venue.heartbeat = beat
    result = session.run(rehearsal_seconds=120)
    assert result['cleanup_ok'] and not venue.open_orders()
    assert result['minute_samples'] <= 1
    assert all(row['side'] == 'BUY' for row in venue.calls)
    if cause == 'fill': assert result['fill_seen']
    if cause in {'minimum', 'rate'}:
        assert result['reward_terms_changed']
        records = [json.loads(line) for line in session.journal.path.read_text().splitlines()]
        assert any(row['event'] == 'market_snapshot' for row in records)
    if cause == 'one_sided': assert result['reason'] == 'one_sided_book'


@pytest.mark.parametrize('exception', [RuntimeError, KeyboardInterrupt])
def test_failure_between_submits_cancels_first(tmp_path, exception):
    session, venue, _ = setup(tmp_path)
    original = venue.submit
    def submit(request, **kwargs):
        if venue.calls: raise exception()
        return original(request, **kwargs)
    venue.submit = submit
    result = session.run()
    assert result['cleanup_ok'] and not venue.open_orders() and len(venue.calls) == 1


@pytest.mark.parametrize('change', ['side', 'size', 'post_only', 'type', 'host', 'price', 'ask',
                                   'eleventh', 'third', 'one_leg_cost', 'both_cost', 'utc_day', 'duration',
                                   'too_late', 'session_four', 'proxy', 'minimum_not_twenty'])
def test_single_submit_boundary_refuses_hard_limit(tmp_path, monkeypatch, change):
    session, venue, clock = setup(tmp_path)
    kwargs = {}
    if change == 'side': kwargs['side'] = 'SELL'
    if change == 'size': kwargs['size'] = 21
    if change == 'post_only': kwargs['post_only'] = False
    if change == 'type': kwargs['order_type'] = 'GTC'
    if change == 'host': venue.host = 'https://example.invalid'
    if change == 'price': session.prices[0] = Decimal('.16')
    if change == 'ask':
        price = session.prices[0]
        inputs = venue.memory.public_input['quote_inputs']
        for name, level in [('yes_bids', price - Decimal('.02')), ('yes_asks', price),
                            ('no_bids', 1 - price), ('no_asks', 1 - price + Decimal('.02'))]:
            inputs[name] = [{'price': str(level), 'size': '100'}]
    if change == 'eleventh': session.submits = 10
    if change == 'third':
        session.submit(0, session.prices[0]); session.submit(1, session.prices[1])
    if change == 'one_leg_cost': session.prices = [Decimal('.80'), Decimal('.17')]
    if change == 'both_cost': session.prices = [Decimal('.40'), Decimal('.59')]
    if change == 'utc_day': session.end += timedelta(days=1)
    if change == 'duration': session.end += timedelta(seconds=1)
    if change == 'too_late': clock.seconds = 21600 - 179
    if change == 'session_four': session.mode, session.attempt = 'live', {'number': 31}
    if change == 'proxy': monkeypatch.setenv('HTTPS_PROXY', 'http://example.invalid')
    if change == 'minimum_not_twenty': venue.memory.public_input['quote_inputs']['reward_min_size'] = '19'
    count = len(venue.calls)
    with pytest.raises((HoldEnd, RuntimeError)) as refused:
        session.submit(0, session.prices[0], **kwargs)
    if change == 'ask': assert refused.value.reason == 'fresh_ask'
    assert len(venue.calls) == count
    session.cleanup(); session.journal.close()
    assert not venue.open_orders()


def test_cancel_read_lag_is_waited_out_on_requote_and_cleanup(tmp_path):
    session, venue, clock = setup(tmp_path)
    original = venue.snapshot
    def snapshot(*args, **kwargs):
        # One 3c move after the first minute forces one requote.
        shift = Decimal('.03') if clock.seconds >= 60 else Decimal(0)
        value = original(*args, **kwargs)
        raw = venue.memory.public_input['quote_inputs']
        for side in ('yes', 'no'):
            delta = shift if side == 'yes' else -shift
            for direction in ('bids', 'asks'):
                name = side + '_' + direction
                value['quote_inputs'][name] = [dict(r, price=str(Decimal(r['price']) + delta)) for r in raw[name]]
        return value
    venue.snapshot = snapshot
    real_open, real_cancel, real_cancel_all = venue.open_orders, venue.cancel, venue.cancel_all
    lag = {'rows': None, 'left': 0, 'served': 0}
    def lagging(fn):
        # After a cancel, the next two open-order reads still show the pre-cancel rows.
        def wrapped(*args, **kwargs):
            if not lag['left']:
                lag['rows'], lag['left'] = real_open(), 2
            return fn(*args, **kwargs)
        return wrapped
    def open_orders():
        if lag['left']:
            lag['left'] -= 1
            lag['served'] += 1
            return lag['rows']
        return real_open()
    venue.cancel, venue.cancel_all, venue.open_orders = lagging(real_cancel), lagging(real_cancel_all), open_orders
    result = session.run(rehearsal_seconds=180)
    assert result['requotes'] >= 1 and lag['served'] >= 4
    assert result['reason'] == 'fixed_end' and result['cleanup_ok']
    assert not real_open()


def test_requotes_legs_outside_window_instead_of_hold_lane_stop(tmp_path):
    session, venue, clock = setup(tmp_path)
    original = venue.snapshot
    def snapshot(*args, **kwargs):
        # Move the whole underlying book up 3c each minute, removing simulation
        # depth only while computing the shifted raw market input.
        shift = Decimal('.03') * int(clock.seconds // 60)
        value = original(*args, **kwargs)
        raw = venue.memory.public_input['quote_inputs']
        for side in ('yes', 'no'):
            delta = shift if side == 'yes' else -shift
            for direction in ('bids', 'asks'):
                name = side + '_' + direction
                value['quote_inputs'][name] = [dict(r, price=str(Decimal(r['price']) + delta)) for r in raw[name]]
        return value
    venue.snapshot = snapshot
    result = session.run(rehearsal_seconds=360)
    assert result['requotes'] == 4 and result['submits'] == 10
    assert result['reason'] == 'fifth_requote'
    assert result['cleanup_ok'] and not venue.open_orders()


def test_held_and_plain_mid_sensitivity_matches_corrected_reference(tmp_path):
    session, venue, _ = setup(tmp_path)
    snapshot = venue.memory.public_input
    snapshot['quote_inputs']['yes_bids'] = [{'price': '.33', 'size': '100'}, {'price': '.34', 'size': '1'}]
    snapshot['quote_inputs']['yes_asks'] = [{'price': '.36', 'size': '100'}]
    snapshot['quote_inputs']['no_bids'] = [{'price': '.64', 'size': '100'}]
    observed = observe(snapshot, ['.33', '.64'])
    reference = reference_evaluate(snapshot, {'yesBid': .33, 'yesAsk': .36, 'size': 20, 'resting': True})
    assert observed['share_many'] == pytest.approx(reference['share_many'])
    assert float(observed['plain_mid']) == pytest.approx(.35)
    assert observed['share_many_plain_mid'] == pytest.approx(25 / 173)
    assert replacement_price('.345', 0) == Decimal('.33')
    assert replacement_price('.345', 1) == Decimal('.64')
    session.journal.close()


def test_secret_guard_redacts_and_refuses_residual_secrets():
    guard = SecretGuard(['synthetic-secret-123'])
    assert guard.clean({'headers': {'Authorization': 'synthetic-secret-123'}, 'signature': 'abc', 'ok': True}) == {'ok': True}
    with pytest.raises(RuntimeError, match='secret_output_refused'):
        guard.clean({'message': 'contains synthetic-secret-123'})


def test_journal_failure_still_cancels(tmp_path):
    session, venue, _ = setup(tmp_path)
    original = session.journal.record
    def record(event, **fields):
        if len(venue.calls) == 2: raise OSError('disk full')
        original(event, **fields)
    session.journal.record = record
    result = session.run()
    assert not venue.open_orders() and result['cleanup_ok']
    assert not result['evidence_complete']


def test_fill_racing_cancel_never_reenters(tmp_path):
    session, venue, _ = setup(tmp_path)
    session.submit(0, session.prices[0]); session.submit(1, session.prices[1])
    original = venue.cancel
    def racing(oid):
        venue.memory.orders[oid]['size_matched'] = '.1'
        return original(oid)
    venue.cancel = racing
    with pytest.raises(HoldEnd, match='fill'):
        session.cancel_leg(next(iter(session.active)))
    session.cleanup(); session.journal.close()
    assert session.fill_seen and len(venue.calls) == 2 and not venue.open_orders()


def test_geography_and_heartbeat_cadence(tmp_path):
    session, venue, clock = setup(tmp_path)
    geo, beats = [], []
    def geography():
        geo.append(clock.seconds)
        return {'blocked': False}
    def heartbeat():
        beats.append(clock.seconds)
        return {'status': 'ok'}
    venue.geography, venue.heartbeat = geography, heartbeat
    session.run(rehearsal_seconds=125)
    assert max(b-a for a, b in zip(geo, geo[1:])) <= 45
    assert max(b-a for a, b in zip(beats, beats[1:])) <= 5


def test_cleanup_failure_emits_panic_and_never_claims_zero(tmp_path, capsys):
    session, venue, _ = setup(tmp_path)
    def fail(*args): raise ConnectionError()
    venue.cancel = venue.cancel_all = fail
    result = session.run(rehearsal_seconds=1)
    assert not result['cleanup_ok'] and venue.open_orders()
    assert 'PANIC' in capsys.readouterr().out


def test_initial_foreign_orders_remain_untouched(tmp_path):
    session, venue, _ = setup(tmp_path)
    venue.memory.orders['foreign'] = {'id': 'foreign', 'status': 'LIVE'}
    result = session.run(rehearsal_seconds=1)
    assert result['reason'] == 'initial_open_orders' and not venue.calls
    assert venue.memory.orders['foreign']['status'] == 'LIVE'


def test_deadline_cleanup_fill_is_recorded(tmp_path):
    session, venue, _ = setup(tmp_path)
    original = venue.cancel_all
    def race():
        first = next(iter(venue.memory.orders.values()))
        first['size_matched'] = '.2'
        return original()
    venue.cancel_all = race
    result = session.run(rehearsal_seconds=1)
    assert result['fill_seen'] and result['reason'] == 'fill'
    assert result['cleanup_ok'] and len(venue.calls) == 2


def test_lost_submit_ack_checks_inventory_and_marks_incomplete(tmp_path):
    session, venue, _ = setup(tmp_path)
    original = venue.submit
    def lost(request, **kwargs):
        original(request, **kwargs)
        venue.positions = lambda: [{'asset': TOKENS[0], 'size': '.2'}]
        raise ConnectionError('acknowledgement lost')
    venue.submit = lost
    result = session.run()
    assert result['fill_seen'] and not result['evidence_complete']
    assert result['cleanup_ok'] and not venue.open_orders() and len(venue.calls) == 1


def test_external_cancellation_stops_resting_minute_credit(tmp_path):
    session, venue, clock = setup(tmp_path)
    def events():
        if clock.seconds >= 30: venue.cancel_all()
        return []
    venue.events = events
    result = session.run(rehearsal_seconds=120)
    assert result['reason'] == 'order_no_longer_resting'
    assert result['minute_samples'] == 1 and not result['evidence_complete']
    assert result['cleanup_ok'] and not venue.open_orders()
