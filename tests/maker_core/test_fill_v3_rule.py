"""Fill model v3, the pure rule: known answers and seeded stdlib-random properties (item 330 build 1).

Guards: 0 <= v3 <= at-price bound; v3 <= strictly-through bound + max(0, V_at - q_ahead); invariance to print
order within a minute; exact YES/NO mirror; the streaming form's first fill falls in the pure rule's minute.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import random

import pytest

from maker_core.quoting.policy import Book, QuoteLeg
from maker_core.replay.fill_model import match
from maker_core.replay.fill_v3 import (Print, QueueState, at_price_bound, deplete, eligibility, minute_of, q_ahead,
                                       strictly_through_bound)
from maker_core.replay.payloads import Trade

T0 = datetime(2020, 1, 1, tzinfo=timezone.utc)
SEEDS = range(20)


def p(seconds, kind, size):
    return Print(T0 + timedelta(seconds=seconds), kind, D(size))


def trade(price, outcome="YES", size="10"):
    return Trade("t", outcome, D(price), D(size), T0, "SELL")


# -- known answers ----------------------------------------------------------------------------------------
def test_queue_is_consumed_before_any_fill():
    result = deplete(D(20), D(30), [p(10, "at", 25), p(70, "thr", 10), p(130, "at", 8)])
    assert (result.total, result.from_at, result.from_thr, result.queue_left) == (D(13), D(8), D(5), D(0))
    assert result.first_fill_minute == T0 + timedelta(minutes=1)


def test_no_fill_while_the_queue_absorbs_every_print():
    result = deplete(D(20), D(100), [p(0, "at", 40), p(5, "thr", 59)])
    assert (result.total, result.queue_left, result.first_fill_minute) == (D(0), D(1), None)


def test_empty_queue_matches_the_at_price_bound_and_fill_caps_at_leg_size():
    prints = [p(0, "at", 7), p(1, "thr", 30)]
    assert deplete(D(20), D(0), prints).total == at_price_bound(D(20), prints) == D(20)
    assert strictly_through_bound(D(20), prints) == D(20)
    assert strictly_through_bound(D(50), prints) == D(30)


def test_within_a_minute_at_price_volume_consumes_the_queue_first():
    result = deplete(D(50), D(10), [p(1, "thr", 10), p(2, "at", 10)])
    assert (result.from_at, result.from_thr) == (D(0), D(10))


def test_inputs_are_validated():
    with pytest.raises(ValueError, match="v3_queue_ahead"):
        deplete(D(1), D(-1), [])
    with pytest.raises(ValueError, match="v3_leg_size"):
        deplete(D(0), D(1), [])
    with pytest.raises(ValueError, match="v3_unknown_print_kind"):
        Print(T0, "near", D(1))
    with pytest.raises(ValueError, match="v3_naive_print_time"):
        Print(datetime(2020, 1, 1), "at", D(1))
    with pytest.raises(ValueError, match="v3_print_size"):
        Print(T0, "at", D(0))


def test_eligibility_is_v2s_yes_axis_predicate():
    yes, no = QuoteLeg("YES", D(".48"), D(20)), QuoteLeg("NO", D(".48"), D(20))
    assert eligibility(yes, trade(".48")) == "at"
    assert eligibility(yes, trade(".47")) == "thr"
    assert eligibility(yes, trade(".49")) is None
    assert eligibility(yes, trade(".52", "NO")) == "at"  # NO at .52 is YES at .48
    assert eligibility(no, trade(".52")) == "at"
    assert eligibility(no, trade(".55")) == "thr"
    assert eligibility(no, trade(".46", "NO")) == "thr"
    for leg in (yes, no):
        for price in (".40", ".47", ".48", ".49", ".52", ".53", ".60"):
            for outcome in ("YES", "NO"):
                kind = eligibility(leg, trade(price, outcome))
                assert (kind == "thr") == (match((leg,), trade(price, outcome), "strictly_through") is not None)
                assert (kind is not None) == (match((leg,), trade(price, outcome), "at_price") is not None)


def test_q_ahead_reads_the_legs_own_bid_array_at_its_price():
    book = Book(T0, ((D(".49"), D(75)), (D(".48"), D(30))), ((D(".51"), D(1)),),
                ((D(".48"), D(10)),), ((D(".52"), D(30)),))
    assert q_ahead(book, QuoteLeg("YES", D(".48"), D(1))) == D(30)
    assert q_ahead(book, QuoteLeg("NO", D(".48"), D(1))) == D(10)
    assert q_ahead(book, QuoteLeg("YES", D(".47"), D(1))) == D(0)
    assert q_ahead(None, QuoteLeg("YES", D(".48"), D(1))) is None


# -- seeded properties ------------------------------------------------------------------------------------
def scenario(rng):
    size = D(rng.randint(1, 100))
    queue = D(rng.randint(0, 200))
    prints = [p(rng.randint(0, 299), rng.choice(("at", "thr")), rng.randint(1, 60)) for _ in range(rng.randint(0, 30))]
    return size, queue, prints


@pytest.mark.parametrize("seed", SEEDS)
def test_bounds(seed):
    rng = random.Random(seed)
    for _ in range(200):
        size, queue, prints = scenario(rng)
        result = deplete(size, queue, prints)
        volume_at = sum((x.size for x in prints if x.kind == "at"), D(0))
        volume_thr = sum((x.size for x in prints if x.kind == "thr"), D(0))
        assert D(0) <= result.total <= at_price_bound(size, prints)
        assert result.total <= strictly_through_bound(size, prints) + max(D(0), volume_at - queue)
        assert result.total == min(size, max(D(0), volume_at + volume_thr - queue))
        assert result.total == result.from_at + result.from_thr


@pytest.mark.parametrize("seed", SEEDS)
def test_invariant_to_print_order_within_a_minute(seed):
    rng = random.Random(1000 + seed)
    for _ in range(200):
        size, queue, prints = scenario(rng)
        by_minute = {}
        for x in prints:
            by_minute.setdefault(minute_of(x.traded_at), []).append(x)
        shuffled = []
        for minute in rng.sample(sorted(by_minute), len(by_minute)):
            group = by_minute[minute][:]
            rng.shuffle(group)
            # Move each print to another second of its own minute as well.
            shuffled += [Print(minute + timedelta(seconds=rng.randint(0, 59)), x.kind, x.size) for x in group]
        assert deplete(size, queue, shuffled) == deplete(size, queue, prints)


@pytest.mark.parametrize("seed", SEEDS)
def test_streaming_first_fill_falls_in_the_pure_rules_minute(seed):
    rng = random.Random(2000 + seed)
    for _ in range(200):
        size, queue, prints = scenario(rng)
        expected = deplete(size, queue, prints).first_fill_minute
        ordered = sorted(prints, key=lambda x: (minute_of(x.traded_at), rng.random()))
        state, first = QueueState(size, queue), None
        for x in ordered:
            if state.consume(x.size) > 0:
                first = minute_of(x.traded_at)
                break
        assert first == expected


@pytest.mark.parametrize("seed", SEEDS)
def test_exact_yes_no_mirror(seed):
    rng = random.Random(3000 + seed)
    for _ in range(300):
        price = D(rng.randint(1, 99)) / 100
        size = D(rng.randint(1, 50))
        depth = D(rng.randint(0, 80))
        other = D(rng.randint(0, 80))
        yes, no = QuoteLeg("YES", price, size), QuoteLeg("NO", price, size)
        book = Book(T0, ((price, depth),), (), ((price, other),), ())
        mirror = Book(T0, ((price, other),), (), ((price, depth),), ())
        assert q_ahead(book, yes) == q_ahead(mirror, no) == depth
        x = D(rng.randint(1, 99)) / 100
        # A YES leg facing YES prints is the NO leg facing NO prints at the same price...
        assert eligibility(yes, trade(str(x), "YES")) == eligibility(no, trade(str(x), "NO"))
        # ...and a print on one token is the complementary print on the other.
        assert eligibility(yes, trade(str(x), "YES")) == eligibility(yes, trade(str(1 - x), "NO"))
        assert eligibility(no, trade(str(x), "NO")) == eligibility(no, trade(str(1 - x), "YES"))
