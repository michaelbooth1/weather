"""Fake-clock outage budgets, campaign recovery, and retained seeded six-hour proof."""
from datetime import timedelta
import hashlib
import json
import random
from types import SimpleNamespace

import pytest

from tests.market.test_re1_attended import setup
from tests.market.stage2_fakes import Clock
from weather.market.re1_attended import SecretGuard
from weather.market.re1_evidence import reserve_attempt, attempt_state
from weather.market.re1_owner_checks import reconcile_receipt, latency
from weather.market.re1_resilience import HeartbeatLoop


@pytest.mark.parametrize('point,names', [
    ('startup', ('geography', 'heartbeat', 'order', 'events', 'snapshot', 'scoring', 'accrual', 'open_orders', 'positions', 'balances')),
    ('loop', ('geography', 'heartbeat', 'order', 'events', 'snapshot')),
    ('cleanup', ('order', 'open_orders', 'positions', 'balances', 'trades', 'accrual'))])
def test_one_timeout_per_read_at_each_phase_survives(tmp_path, names, point):
    for name in names:
        session, venue, clock = setup(tmp_path / name)
        original = getattr(venue, name)
        failures = []
        def flaky(*args, **kwargs):
            active = {'startup': clock.seconds < 20, 'loop': 60 <= clock.seconds < 120,
                      'cleanup': clock.seconds >= 180}[point]
            if active and not failures:
                failures.append(clock.seconds)
                raise TimeoutError()
            return original(*args, **kwargs)
        setattr(venue, name, flaky)
        result = session.run(rehearsal_seconds=180)
        assert failures, (point, name)
        assert result['reason'] == 'fixed_end', (point, name, result['reason'])
        assert result['cleanup_ok'] and not venue.open_orders()
        assert result['post_count'] == 2


@pytest.mark.parametrize('name,reason,maximum', [('geography', 'geoblock_stale', 46),
    ('heartbeat', 'heartbeat_stale', 39), ('order', 'order_', 61),
    ('events', 'user_stream_stale', 61), ('snapshot', 'market_snapshot_stale', 361)])
def test_persistent_outage_exhausts_own_budget(tmp_path, name, reason, maximum):
    session, venue, clock = setup(tmp_path)
    original = getattr(venue, name)
    def unavailable(*args, **kwargs):
        if not session.closed and 30 <= clock.seconds <= maximum:
            raise TimeoutError()
        return original(*args, **kwargs)
    setattr(venue, name, unavailable)
    result = session.run(rehearsal_seconds=400)
    assert result['reason'].startswith(reason)
    assert result['failure_type'] is None
    assert result['cleanup_ok'] and not venue.open_orders()
    assert clock.seconds <= maximum + 4


def test_noncritical_samples_can_fail_forever(tmp_path):
    session, venue, _ = setup(tmp_path)
    def fail(*args): raise TimeoutError()
    venue.scoring = venue.accrual = fail
    result = session.run(rehearsal_seconds=60)
    assert result['reason'] == 'fixed_end' and result['cleanup_ok']
    assert not result['evidence_complete']


@pytest.mark.parametrize('name', ['open_orders', 'positions', 'balances'])
def test_initial_read_budget_is_named_and_sends_no_orders(tmp_path, name):
    session, venue, _ = setup(tmp_path)
    def unavailable(*args): raise TimeoutError()
    setattr(venue, name, unavailable)
    result = session.run()
    assert result['reason'] == 'initial_' + name + '_stale'
    assert result['post_count'] == 0 and result['failure_type'] is None
    assert not venue.memory.orders


def test_stream_down_uses_rest_fill_detector(tmp_path):
    session, venue, clock = setup(tmp_path)
    def events():
        if clock.seconds >= 30:
            next(iter(venue.memory.orders.values()))['size_matched'] = '.1'
            raise ConnectionError()
        return []
    venue.events = events
    result = session.run(rehearsal_seconds=120)
    assert result['reason'] == 'fill' and result['fill_seen']
    assert result['cleanup_ok'] and not venue.open_orders()
    assert clock.seconds <= 40


def test_heartbeat_daemon_and_main_stall_stop():
    clock, sends = Clock(), []
    beat = HeartbeatLoop(clock, lambda: sends.append(clock.seconds) or {'status': 'ok'},
                         SimpleNamespace(record=lambda *a, **kw: None), threaded=False)
    beat.start()
    for value in range(1, 26):
        clock.seconds = value
        beat.step()
    assert sends == [0, 5, 10, 15]
    assert beat.failure == 'main_loop_stalled'
    # The production path really creates and owns a daemon, not a loop callback.
    beat = HeartbeatLoop(Clock(), lambda: {'status': 'ok'}, SimpleNamespace(record=lambda *a, **k: None), threaded=True)
    beat.start()
    assert beat.thread.daemon and beat.thread.name == 're1-heartbeat'
    beat.stop()
    assert not beat.thread.is_alive()


def test_zero_post_attempt_does_not_consume_session_and_six_marker_cap(tmp_path):
    now = Clock().now()
    for i in range(1, 7):
        directory, marker = reserve_attempt(tmp_path, now=now, selection_sha256='a' * 64)
        assert marker['number'] == i and marker['session_number'] == 1
        assert not attempt_state(tmp_path / f'session-{i}.attempt.json', now=now)['submitted']
    with pytest.raises(RuntimeError, match='six_attempt_cap'):
        reserve_attempt(tmp_path, now=now, selection_sha256='a' * 64)


def test_evidence_gap_does_not_block_safe_next_session(tmp_path):
    directory, _ = reserve_attempt(tmp_path, now=Clock().now(), selection_sha256='a' * 64)
    session, venue, clock = setup(directory)
    def missing(*a): raise TimeoutError()
    venue.scoring = missing
    result = session.run(rehearsal_seconds=1)
    assert not result['evidence_complete'] and result['cleanup_ok']
    _, marker = reserve_attempt(tmp_path, now=clock.now(), selection_sha256='b' * 64)
    assert marker['session_number'] == 2


def test_reconcile_needs_phrase_bound_receipt_and_fresh_empty_account(tmp_path):
    directory, _ = reserve_attempt(tmp_path, now=Clock().now(), selection_sha256='a' * 64)
    session, venue, clock = setup(directory)
    original = venue.submit
    def lost(request, **kwargs):
        original(request, **kwargs)
        raise TimeoutError()
    venue.submit = lost
    result = session.run()
    assert result['unknown_submit'] and result['cleanup_ok']
    marker = tmp_path / 'session-1.attempt.json'
    with pytest.raises(RuntimeError, match='reconciliation'):
        reserve_attempt(tmp_path, now=clock.now(), selection_sha256='b' * 64)
    with pytest.raises(RuntimeError, match='confirmation'):
        reconcile_receipt(marker, venue, clock=clock, guard=SecretGuard(), reader=lambda: 'no')
    from weather.market.mm_stage2_hold import digest
    phrase = 'RE1M RECONCILE ' + digest(attempt_state(marker, now=clock.now()))[:12]
    reconcile_receipt(marker, venue, clock=clock, guard=SecretGuard(), reader=lambda: phrase)
    with pytest.raises(RuntimeError, match='reconciliation'):
        reserve_attempt(tmp_path, now=clock.now(), selection_sha256='b' * 64, maker=venue.maker, open_orders=lambda: [{}])
    _, attempt = reserve_attempt(tmp_path, now=clock.now(), selection_sha256='b' * 64,
                                 maker=venue.maker, open_orders=venue.open_orders)
    assert attempt['session_number'] == 2


def test_reconcile_records_unreadable_historical_order_but_still_needs_empty_account(tmp_path):
    directory, _ = reserve_attempt(tmp_path, now=Clock().now(), selection_sha256='a' * 64)
    session, venue, clock = setup(directory)
    assert session.run(rehearsal_seconds=60)['cleanup_ok']
    marker = tmp_path / 'session-1.attempt.json'
    class UnexpectedResponseError(Exception):
        pass
    def closed(oid): raise UnexpectedResponseError('closed order')
    venue.order = closed
    from weather.market.mm_stage2_hold import digest
    state = attempt_state(marker, now=clock.now())
    assert state['order_ids']
    phrase = 'RE1M RECONCILE ' + digest(state)[:12]
    empty = venue.open_orders
    venue.open_orders = lambda: [{'id': 'resting'}]
    with pytest.raises(RuntimeError, match='reconciliation_requires_empty_account'):
        reconcile_receipt(marker, venue, clock=clock, guard=SecretGuard(), reader=lambda: phrase)
    def broken(): raise TimeoutError()
    venue.open_orders = broken
    with pytest.raises(TimeoutError):
        reconcile_receipt(marker, venue, clock=clock, guard=SecretGuard(), reader=lambda: phrase)
    assert not (directory / 'reconciliation.json').exists()
    venue.open_orders = empty
    receipt = reconcile_receipt(marker, venue, clock=clock, guard=SecretGuard(), reader=lambda: phrase)
    assert receipt['orders'] == [{'order_id': oid, 'read_failed': 'UnexpectedResponseError'}
                                 for oid in state['order_ids']]
    _, attempt = reserve_attempt(tmp_path, now=clock.now(), selection_sha256='b' * 64,
                                 maker=venue.maker, open_orders=venue.open_orders)
    assert attempt['session_number'] == 2


def test_latency_table_uses_nearest_rank_p95():
    assert latency(range(1, 21)) == dict(min=1, median=10.5, p95=19, max=20, count=20)


def test_seeded_two_percent_six_hour_rehearsal(tmp_path):
    session, venue, clock = setup(tmp_path)
    rng, reads, faults = random.Random(84_003), {}, {}
    for name in ('geography', 'heartbeat', 'order', 'events', 'snapshot', 'open_orders',
                 'positions', 'balances', 'scoring', 'accrual', 'trades'):
        original = getattr(venue, name)
        def flaky(*args, _name=name, _original=original, **kwargs):
            reads[_name] = reads.get(_name, 0) + 1
            if rng.random() < .02:
                faults[_name] = faults.get(_name, 0) + 1
                raise TimeoutError()
            return _original(*args, **kwargs)
        setattr(venue, name, flaky)
    result = session.run()
    assert result['reason'] == 'fixed_end' and result['cleanup_ok']
    assert not [r for r in venue.memory.orders.values() if r['status'] == 'LIVE']
    assert result['post_count'] == 2 and clock.seconds >= 21600
    assert 300 <= result['minute_samples'] <= 360 and sum(faults.values()) > 100
    # JUnit stdout retains the deterministic proof; an explicit scratch harness
    # can choose a durable output directory without polluting the offline suite.
    print(json.dumps({'seed': 84_003, 'reads': reads, 'faults': faults,
                      'journal_sha256': hashlib.sha256(session.journal.path.read_bytes()).hexdigest(),
                      'prediction_sha256': hashlib.sha256((tmp_path / 'prediction.json').read_bytes()).hexdigest(),
                      'reason': result['reason'], 'minutes': result['minute_samples']}))
