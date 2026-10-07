"""The S1 logical-time barrier (D-shadow-gate-spec-v3 §4.5, M4; L6 in v3 §4.4).

Controls Kx1 (records processed in arrival order, not logical order) and Kx3 (a timer fired before the same-instant
records) are v3 §7 adapter controls; MB1 (a websocket print delayed behind a book read) and MB2 (6 s lateness ->
``INCOMPLETE (live_lateness)``) are v3 §15 mutants. Each property is a checker function so that the mutant tests
can show the same checker fails on a deliberately broken barrier.
"""
from datetime import datetime, timedelta, timezone

import pytest

from maker_core.shadow.barrier import (LATE_RECORDS, LIVE_LATENESS, DrainedInstant, LogicalTimeBarrier)

T0 = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
WS, BOOK, VIEW = "ws_market", "book_poll", "view"


def at(seconds):
    return T0 + timedelta(seconds=seconds)


def make(cls=LogicalTimeBarrier):
    return cls((WS, BOOK, VIEW), wall_clock=lambda: at(100))


def steps(barrier):
    return [(step, item.channel if step != "timer" else item.kind, item.at)
            for instant in barrier.drain() for step, item in instant.steps()]


# -- checkers ------------------------------------------------------------------------------------------------------
def mb1_barrier_holds_book_until_websocket_catches_up(cls):
    """MB1 rig: the book read at t=10.5 completes before the websocket delivers a print stamped t=10.0."""
    barrier = make(cls)
    barrier.advance(VIEW, at(60))
    barrier.enqueue(BOOK, "book", condition_id="c1", received_at=at(10.5))
    barrier.advance(WS, at(9))
    assert steps(barrier) == []  # W = 9 < 10.5: the book read is held
    barrier.enqueue(WS, "trade", condition_id="c1", received_at=at(10.0))  # arrives late in wall order
    barrier.advance(WS, at(11))  # ping/pong
    assert steps(barrier) == [("trade", WS, at(10.0)), ("record", BOOK, at(10.5))]


def kx1_same_instant_prints_before_records(cls):
    barrier = make(cls)
    barrier.enqueue(BOOK, "book", condition_id="c1", received_at=at(5))
    barrier.enqueue(VIEW, "outcome_view", condition_id="c1", received_at=at(5))
    barrier.enqueue(WS, "trade", condition_id="c1", received_at=at(5))
    for channel in (WS, BOOK, VIEW):
        barrier.advance(channel, at(6))
    assert steps(barrier) == [("trade", WS, at(5)), ("record", BOOK, at(5)), ("record", VIEW, at(5))]


def kx3_timer_after_same_instant_records(cls):
    barrier = make(cls)
    barrier.schedule_timer(at(7), condition_id="c1", kind="cooldown")
    barrier.enqueue(BOOK, "book", condition_id="c1", received_at=at(7))
    barrier.enqueue(WS, "trade", condition_id="c1", received_at=at(7))
    for channel in (WS, BOOK, VIEW):
        barrier.advance(channel, at(8))
    assert steps(barrier) == [("trade", WS, at(7)), ("record", BOOK, at(7)), ("timer", "cooldown", at(7))]


def timers_wait_for_the_watermark(cls):
    barrier = make(cls)
    barrier.schedule_timer(at(3), kind="requote")
    barrier.advance(WS, at(10))
    barrier.advance(BOOK, at(10))
    assert steps(barrier) == []  # VIEW has delivered nothing: W is undefined, a timer cannot fire early
    barrier.advance(VIEW, at(2))
    assert steps(barrier) == []
    barrier.advance(VIEW, at(3))
    assert steps(barrier) == [("timer", "requote", at(3))]


CHECKERS = (mb1_barrier_holds_book_until_websocket_catches_up, kx1_same_instant_prints_before_records,
            kx3_timer_after_same_instant_records, timers_wait_for_the_watermark)


@pytest.mark.parametrize("checker", CHECKERS)
def test_barrier_contract(checker):
    checker(LogicalTimeBarrier)


# -- mutants: each broken barrier must be caught -------------------------------------------------------------------
class ArrivalOrder(LogicalTimeBarrier):
    """Kx1 / MB1: process records in arrival order and do not wait for the global watermark."""

    def pop_ready(self):
        with self._lock:
            if not self._records and not self._timers:
                return None
            if self._records:
                first = min(self._records, key=lambda r: r.sequence)
                self._records.remove(first)
                return DrainedInstant(first.at, (first,) if first.kind == "trade" else (),
                                      () if first.kind == "trade" else (first,), ())
            timer = self._timers.pop(0)
            return DrainedInstant(timer.at, (), (), (timer,))


class EnqueueOrderWithinInstant(LogicalTimeBarrier):
    """Kx1 within an instant: records by enqueue sequence only, prints not first."""

    def _instant(self, at, items, timers):
        items = sorted(items, key=lambda r: r.sequence)
        return DrainedInstant(at, (), tuple(items), tuple(timers))

    def drain(self):
        while (instant := self.pop_ready()) is not None:
            yield instant


class TimersFirst(LogicalTimeBarrier):
    """Kx3: a timer fired before the same-instant records."""

    def _instant(self, at, items, timers):
        instant = super()._instant(at, items, timers)
        return _TimerFirstInstant(instant.at, instant.trades, instant.records, instant.timers)


class _TimerFirstInstant(DrainedInstant):
    def steps(self):
        return (*(("timer", t) for t in self.timers), *(("trade", r) for r in self.trades),
                *(("record", r) for r in self.records))


class NoWatermarkWait(LogicalTimeBarrier):
    def _global(self):
        return datetime.max.replace(tzinfo=timezone.utc)


@pytest.mark.parametrize("mutant,checker", [
    (ArrivalOrder, mb1_barrier_holds_book_until_websocket_catches_up),
    (EnqueueOrderWithinInstant, kx1_same_instant_prints_before_records),
    (TimersFirst, kx3_timer_after_same_instant_records),
    (NoWatermarkWait, timers_wait_for_the_watermark),
    (NoWatermarkWait, mb1_barrier_holds_book_until_websocket_catches_up),
])
def test_mutants_are_killed(mutant, checker):
    with pytest.raises(AssertionError):
        checker(mutant)


# -- late records ----------------------------------------------------------------------------------------------------
def test_late_record_restamped_strictly_after_processed_instant_and_counted():
    barrier = make()
    for channel in (WS, BOOK, VIEW):
        barrier.advance(channel, at(10))
    barrier.enqueue(BOOK, "book", condition_id="c1", received_at=at(10))
    assert [i.at for i in barrier.drain()] == [at(10)]
    late = barrier.enqueue(WS, "trade", condition_id="c1", received_at=at(9))
    assert late.restamped and late.received_at == at(9) and late.at == at(10) + timedelta(microseconds=1)
    barrier.advance(WS, at(11))
    barrier.advance(BOOK, at(11))
    barrier.advance(VIEW, at(11))
    drained = list(barrier.drain())
    assert [(i.at, len(i.trades)) for i in drained] == [(late.at, 1)]
    assert drained[0].trades[0].received_at == at(9)  # the original receipt is kept
    report = barrier.day_report(T0.date())
    assert report["records"] == 2 and report["late_restamped"] == 1 and LATE_RECORDS in report["incomplete"]


def test_late_record_fraction_at_one_percent_is_not_incomplete():
    barrier = make()
    for n in range(100):
        barrier.enqueue(BOOK, "book", condition_id="c1", received_at=at(n + 1))
    for channel in (WS, VIEW):
        barrier.advance(channel, at(200))
    list(barrier.drain())
    barrier.enqueue(WS, "trade", condition_id="c1", received_at=at(50))  # 1 late of 101 records < 1 %
    assert barrier.day_report(T0.date())["incomplete"] == []


def test_timer_cannot_be_scheduled_at_or_before_processed_instant():
    barrier = make()
    for channel in (WS, BOOK, VIEW):
        barrier.advance(channel, at(10))
    barrier.enqueue(BOOK, "book", received_at=at(10))
    list(barrier.drain())
    with pytest.raises(ValueError, match="timer_not_after_processed_instant"):
        barrier.schedule_timer(at(10))


def test_timer_scheduled_while_handling_an_instant_is_seen_by_the_drain():
    barrier = make()
    for channel in (WS, BOOK, VIEW):
        barrier.advance(channel, at(20))
    barrier.enqueue(BOOK, "book", condition_id="c1", received_at=at(5))
    seen = []
    for instant in barrier.drain():
        seen.append(instant.at)
        if instant.at == at(5):
            barrier.schedule_timer(at(15), condition_id="c1")
    assert seen == [at(5), at(15)]


def test_inputs_must_be_utc_and_channels_known():
    barrier = make()
    with pytest.raises(ValueError, match="unknown_channel"):
        barrier.enqueue("rewards", "terms", received_at=at(1))
    with pytest.raises(ValueError, match="received_at_must_be_utc"):
        barrier.enqueue(BOOK, "book", received_at=datetime(2026, 9, 28, 12))
    with pytest.raises(ValueError):
        LogicalTimeBarrier((WS, WS), wall_clock=lambda: T0)


# -- lateness bounds (MB2) ------------------------------------------------------------------------------------------
def test_lateness_within_bounds_is_complete():
    barrier = make()
    for n in range(200):
        barrier.note_decision(at(n), at(n) + timedelta(milliseconds=300))
        barrier.note_timer_fired(at(n), at(n) + timedelta(milliseconds=500))
    barrier.note_decision(at(500), at(500) + timedelta(seconds=4.9))  # one outlier under max, beyond p99 rank
    report = barrier.day_report(T0.date())
    assert report["decision_p99"] == pytest.approx(0.3) and report["decision_max"] == pytest.approx(4.9)
    assert report["incomplete"] == []


def test_mb2_six_second_lateness_is_incomplete():
    barrier = make()
    barrier.note_decision(at(1), at(1) + timedelta(milliseconds=100))
    barrier.note_timer_fired(at(2), at(8))  # 6 s
    report = barrier.day_report(T0.date())
    assert report["timer_max"] == 6.0 and report["incomplete"] == [LIVE_LATENESS]


def test_p99_over_one_second_is_incomplete():
    barrier = make()
    for n in range(100):
        barrier.note_decision(at(n), at(n) + timedelta(seconds=1.5 if n >= 98 else 0.1))
    assert barrier.day_report(T0.date())["incomplete"] == [LIVE_LATENESS]


def test_watermark_lags():
    barrier = make()
    barrier.advance(WS, at(99))
    assert barrier.watermark_lags(at(100)) == {WS: 1.0, BOOK: None, VIEW: None}
    assert barrier.watermark() is None
