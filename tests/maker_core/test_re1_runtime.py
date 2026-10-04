"""Source-derived boundary tests, entirely offline and with explicit clocks."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from maker_core.quoting.policy import QuoteLeg, blind_re1, decide
from maker_core.quoting.re1 import observe, replacement_price, session_caps
from maker_core.replay.re1 import Re1Session, Heartbeat


def session(inputs):
    i = replace(inputs, profile=blind_re1)
    return Re1Session(decide(i).legs, end=i.now+timedelta(hours=6)), i


def post(runtime, inputs):
    intent = runtime.begin_post(inputs)
    if intent:
        asks = inputs.book.yes_asks if intent.leg == 0 else inputs.book.no_asks
        runtime.signed_book(min(p for p, _ in asks))
        runtime.post_result()


def resting(inputs):
    runtime, i = session(inputs)
    post(runtime, i)
    post(runtime, i)
    return runtime, i


@pytest.mark.parametrize('distance,affected', [('0.9999', (0,)), ('1', ()), ('3', ()), ('3.0001', (0,))])
def test_inclusive_requote_boundaries(inputs, distance, affected):
    prices = (D('.5')-D(distance)/100, D('.48'))
    assert observe(inputs.book, inputs.terms, prices, D(20)).requote_legs == affected


def test_no_share_or_touch_or_reward_width_pull_in_live_observer(inputs):
    runtime, i = resting(inputs)
    crowded = replace(i.book, yes_bids=((D('.49'), D(100000)),), yes_asks=((D('.51'), D(100000)),))
    d = decide(replace(i, existing=runtime.legs, book=crowded, terms=replace(i.terms, max_spread_cents=D(2))))
    assert d.action == 'HOLD' and d.share_many < .05
    # A small touch level below our buy is a submit check, not a hold gate.
    touch = replace(i.book, no_bids=((D('.46'), D(100)),), no_asks=((D('.47'), D(1)), (D('.51'), D(100))))
    assert decide(replace(i, existing=runtime.legs, book=touch)).action == 'HOLD'


def test_cancel_all_affected_before_either_post_and_freeze_size(inputs):
    runtime, i = resting(inputs)
    moved = replace(i, book=replace(i.book, yes_bids=((D('.55'), D(100)),), yes_asks=((D('.57'), D(100)),)))
    decision, affected = runtime.minute(moved)
    assert decision.action == 'CANCEL' and affected == (0, 1)
    assert [(v.action, v.leg) for v in runtime.pending] == [('CANCEL', 0), ('CANCEL', 1), ('POST', 0), ('POST', 1)]
    with pytest.raises(ValueError, match='out of order'):
        runtime.begin_post(moved)
    for leg in affected:
        runtime.cancel_result(i.now, acknowledged=True)
        runtime.cancel_open_read(i.now, present=True)
        assert runtime.pending[0].leg == leg
        runtime.cancel_open_read(i.now+timedelta(seconds=1), present=False)
    post(runtime, moved)
    post(runtime, moved)
    assert [v.price for v in runtime.legs] == [D('.54'), D('.42')]
    assert all(v.size == 75 for v in runtime.legs)
    assert runtime.submits == 4 and runtime.requotes == 1


def test_partial_requote_preserves_sibling_and_has_no_post_cooldown(inputs):
    runtime, i = resting(inputs)
    # Force asymmetric but source-valid distances: YES moves outside, NO stays.
    runtime.active[1] = QuoteLeg('NO', D('.47'), D(75))
    runtime.prices[1] = D('.47')
    moved = replace(i, book=replace(i.book, yes_bids=((D('.505'), D(100)),), yes_asks=((D('.525'), D(100)),)))
    _, affected = runtime.minute(moved)
    assert affected == (0,)
    sibling = runtime.active[1]
    runtime.cancel_result(i.now, acknowledged=True)
    runtime.cancel_open_read(i.now, present=False)
    assert runtime.active[1] is sibling
    post(runtime, moved)
    assert runtime.active[1] is sibling and runtime.submits == 3


@pytest.mark.parametrize('where', ['cancel_ack', 'cancel_read', 'post_ack'])
def test_first_fill_ends_even_during_requote_and_ack_races(inputs, where):
    runtime, i = resting(inputs)
    moved = replace(i, book=replace(i.book, yes_bids=((D('.55'), D(100)),), yes_asks=((D('.57'), D(100)),)))
    runtime.minute(moved)
    if where == 'cancel_ack':
        runtime.cancel_result(i.now, acknowledged=True, filled=True)
    elif where == 'cancel_read':
        runtime.cancel_result(i.now, acknowledged=True)
        runtime.cancel_open_read(i.now, present=True, filled=True)
    else:
        for _ in range(2):
            runtime.cancel_result(i.now, acknowledged=True)
            runtime.cancel_open_read(i.now, present=False)
        runtime.begin_post(moved)
        runtime.signed_book(D('.57'))
        runtime.post_result(status='matched')
    assert runtime.reason == 'fill' and not runtime.pending and not runtime.legs


def test_lost_post_ack_is_terminal_never_retry(inputs):
    runtime, i = session(inputs)
    runtime.begin_post(i)
    runtime.signed_book(D('.51'))
    runtime.post_result(ambiguous=True)
    assert runtime.reason == 'submit_transport_ambiguous' and runtime.unknown_submit
    assert runtime.posts == runtime.submits == 1
    with pytest.raises(ValueError):
        runtime.begin_post(i)


def test_cancel_ack_is_not_terminal_until_open_read_and_ten_polls(inputs):
    runtime, i = resting(inputs)
    moved = replace(i, book=replace(i.book, yes_bids=((D('.55'), D(100)),), yes_asks=((D('.57'), D(100)),)))
    runtime.minute(moved)
    runtime.cancel_result(i.now, acknowledged=True)
    for n in range(9):
        runtime.cancel_open_read(i.now+timedelta(seconds=n), present=True)
        assert runtime.reason is None
    runtime.cancel_open_read(i.now+timedelta(seconds=9), present=True)
    assert runtime.reason is None
    runtime.advance(i.now+timedelta(seconds=10))
    assert runtime.reason == 'cancel_not_terminal'


def test_missing_own_post_has_ten_retries_foreign_order_has_none(inputs):
    runtime, i = session(inputs)
    post(runtime, i)
    for n in range(10):
        assert not runtime.pre_submit_open_read(i.now+timedelta(seconds=n), []) and runtime.reason is None
    runtime.pre_submit_open_read(i.now+timedelta(seconds=10), [])
    assert runtime.reason == 'unexpected_open_orders'
    runtime, i = session(inputs)
    runtime.pre_submit_open_read(i.now, [], unknown_count=1)
    assert runtime.reason == 'unexpected_open_orders'


def test_budget_and_exact_submit_horizon(inputs):
    runtime, i = session(inputs)
    runtime.submits = 10
    assert runtime.begin_post(i) is None and runtime.reason == 'submit_budget'
    runtime, i = session(inputs)
    runtime.end = i.now+timedelta(seconds=180)
    assert runtime.begin_post(i) is not None
    runtime, i = session(inputs)
    runtime.end = i.now+timedelta(seconds=179.999)
    assert runtime.begin_post(i) is None and runtime.reason == 'expiration_horizon'
    runtime, i = resting(inputs)
    runtime.requotes = 4
    moved = replace(i, book=replace(i.book, yes_bids=((D('.55'), D(100)),), yes_asks=((D('.57'), D(100)),)))
    runtime.minute(moved)
    assert runtime.reason == 'fifth_requote' and runtime.submits == 2


def test_minute_schedule_and_heartbeat_thresholds(inputs):
    runtime, i = resting(inputs)
    assert runtime.due(i.now)
    assert not runtime.due(i.now+timedelta(seconds=59.999))
    assert runtime.due(i.now+timedelta(seconds=120))
    assert runtime.next_minute == i.now+timedelta(seconds=121)
    heartbeat = Heartbeat(0, 0)
    heartbeat.response(0, .25, ok=True)
    assert heartbeat.next_send == 2
    heartbeat.response(2, 3, resynchronized=True)
    assert heartbeat.last_ack == .25 and heartbeat.next_send == 3
    assert heartbeat.check(8.249) is None
    assert heartbeat.check(8.25) == 'heartbeat_stale'
    heartbeat = Heartbeat(0, 0, last_ack=19)
    assert heartbeat.check(20) == 'main_loop_stalled'


def test_sizing_and_rounding_are_frozen_re1(inputs):
    assert session_caps(D(75), D(100)) == (D('59.25'), D('73.50'))
    assert session_caps(D(20), D(25)) == (D('15.80'), D(15))
    assert replacement_price(D('.505'), 0) == D('.49')
    assert replacement_price(D('.505'), 1) == D('.48')
    assert decide(replace(inputs, profile=blind_re1, portfolio=replace(inputs.portfolio, cash=D(24)))).action == 'NO_QUOTE'


def test_signed_touch_recheck_and_freshness_are_submit_only(inputs):
    runtime, i = session(inputs)
    assert runtime.begin_post(replace(i, now=i.now+timedelta(seconds=10)))
    runtime.signed_book(runtime.pending[0].price)
    assert runtime.reason == 'exception' and runtime.posts == 0 and runtime.submits == 1
    runtime, i = session(inputs)
    assert runtime.begin_post(replace(i, now=i.now+timedelta(seconds=10.001))) is None
    assert runtime.reason == 'fresh_book_scope' and runtime.submits == 0


def test_unsized_treatment_keeps_exact_twenty_share_reward_minimum(inputs):
    pair = tuple(QuoteLeg(side, D('.48'), D(20)) for side in ('YES', 'NO'))
    i = replace(inputs, profile=blind_re1, terms=replace(inputs.terms, min_size=D(10)))
    old = Re1Session(pair, end=i.now+timedelta(hours=6), sized=False)
    assert old.begin_post(i) is None and old.reason == 'reward_terms'
    sized = Re1Session(pair, end=i.now+timedelta(hours=6), sized=True)
    assert sized.begin_post(i) is not None
