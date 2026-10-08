"""Engine rulings W1(a) and W2(a): own legs on both sides of the decision book; replacement on the public book.

Fictional fixtures only (shadow-gate spec v3.1 §3.7.1(a)/§3.7.2(a), v3.2 §1 and Annex K). The first decision
is forced to a known QUOTE by patching the kernel's ``decide``; every later decision is the real ``decide()``.

Guards: registration C11 and C12 (engine rulings W1(a) and W2(a), owner 2026-10-07).
"""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from maker_core.quoting.policy import Book, QuoteDecision, QuoteLeg
from maker_core.replay.bundle import BundleError
from maker_core.replay.v2 import kernel as kernel_module
from maker_core.replay.v2.engine import EngineV2
from maker_core.replay.v2.kernel import V2Config
from maker_core.replay.v2.lockstep import bundle_source, drive, run_plan
from maker_core.replay.v2.reference import ReferenceEngine
from .fixtures.replay_scenario import Scenario

CONFIG = V2Config(hazard_per_minute=.001, debug=True, keep=True)
ZONES = {"a": "UTC", "b": "UTC"}
LEGS = (QuoteLeg("YES", D(".48"), D(20)), QuoteLeg("NO", D(".48"), D(20)))
BASE = dict(yb=((D(".49"), D(75)),), ya=((D(".51"), D(75)),), nb=((D(".49"), D(75)),), na=((D(".51"), D(75)),))
MOVED = 70
T0 = datetime(2020, 1, 1, tzinfo=timezone.utc)


def lv(*rows):
    return tuple((D(p), D(s)) for p, s in rows)


# The public book at MOVED for each fixture. MW3: yes_asks best moves onto the YES leg (p = .48).
# MW3b: no_bids best moves onto the YES leg's mirror (1 - p = .52). MW3c: yes_bids best moves onto the
# NO leg's mirror (1 - q = .52). None of these public books is crossed on its own.
MW3 = dict(yb=lv((".47", 75)), ya=lv((".48", 5), (".52", 75)), nb=lv((".47", 75)), na=lv((".51", 75)))
MW3B = dict(yb=lv((".47", 75)), ya=lv((".51", 75)), nb=lv((".52", 5), (".49", 75)), na=lv((".54", 75)))
MW3C = dict(yb=lv((".52", 5), (".47", 75)), ya=lv((".54", 75)), nb=lv((".47", 75)), na=lv((".51", 75)))
# MW1: the public book has no level at either leg's price or mirror.
MW1 = dict(yb=lv((".49", 75)), ya=lv((".51", 75)), nb=lv((".49", 75)), na=lv((".51", 75), (".55", 10)))


def public(s, seconds, sides):
    s.add("a", "coverage", seconds, dict(trade_stream_ok=True, valid_until_utc=s.at(seconds + 60).isoformat()))
    s.add("a", "book", seconds, Book(s.at(seconds), sides["yb"], sides["ya"], sides["nb"], sides["na"]))


def source(tmp_path, moved, *, grade="shadow"):
    s = Scenario(markets=("a",), minutes=3)
    s.view("a", 0, p=.5, grade=grade)  # calibrated grade: the symmetry check does not pre-empt TOUCH_BUFFER
    for seconds in (0, 30, 60):
        public(s, seconds, BASE)
    public(s, MOVED, moved)
    for seconds in (90, 120, 150):
        public(s, seconds, moved)
    return bundle_source(s.bundle(tmp_path / "bundle"))


class Forced:
    """The first decide() call returns QUOTE ``LEGS``; ``script`` overrides later calls; every input is kept."""

    def __init__(self, script=None):
        self.calls, self.script = [], dict(script or {})
        self.real = kernel_module.decide

    def __call__(self, value):
        self.calls.append(value)
        n = len(self.calls)
        if n == 1:
            return QuoteDecision("QUOTE", LEGS, ("FORCED_FIXTURE_QUOTE",), "0" * 64, value.profile.name)
        if n in self.script:
            return self.script[n](value)
        return self.real(value)


def run(tmp_path, moved, monkeypatch, *, engine=EngineV2, policy="informed-v0", script=None, grade="shadow"):
    forced = Forced(script)
    monkeypatch.setattr(kernel_module, "decide", forced)
    src = source(tmp_path, moved, grade=grade)
    config = replace(CONFIG, policy=policy, debug=engine is EngineV2)
    e = engine(config, run_plan([src]))
    drive([src], [e], time_zones=ZONES)
    return e, forced


def at_moved(engine):
    start = engine.decisions[0].at
    return [d for d in engine.decisions if (d.at - start).total_seconds() == MOVED]


# -- W1(a): compose_book (Annex K.1) ------------------------------------------------------------------------
def test_compose_book_puts_each_leg_on_its_bid_and_its_mirror_ask_creating_levels():
    from maker_core.replay.v2.kernel import compose_book
    book = Book(T0, lv((".49", 75)), lv((".51", 75)), lv((".49", 75)), lv((".51", 75), (".55", 10)))
    composed = compose_book(book, LEGS)
    assert composed.yes_bids == lv((".49", 75), (".48", 20))
    assert composed.no_asks == lv((".51", 75), (".52", 20), (".55", 10))
    assert composed.no_bids == lv((".49", 75), (".48", 20))
    assert composed.yes_asks == lv((".51", 75), (".52", 20))
    assert composed.as_of_utc == T0 and composed.post_only_available == book.post_only_available


def test_compose_book_sums_at_an_existing_level_and_leaves_the_book_without_legs_unchanged():
    from maker_core.replay.v2.kernel import compose_book
    book = Book(T0, lv((".48", 75)), lv((".52", 5)), lv((".47", 1)), lv((".53", 1)))
    composed = compose_book(book, LEGS)
    assert composed.yes_bids == lv((".48", 95))
    assert composed.yes_asks == lv((".52", 25))
    assert composed.no_bids == lv((".48", 20), (".47", 1))
    assert composed.no_asks == lv((".52", 20), (".53", 1))
    assert compose_book(book, ()) == book


def test_compose_book_refuses_an_unmerged_public_book():
    from maker_core.replay.v2.kernel import compose_book
    book = Book(T0, lv((".48", 75), (".48", 1)), lv((".52", 5)), lv((".47", 1)), lv((".53", 1)))
    with pytest.raises(BundleError, match="unmerged_book_levels"):
        compose_book(book, LEGS)


def test_mw1_decision_book_carries_created_levels_on_all_four_arrays(tmp_path, monkeypatch):
    engine, forced = run(tmp_path, MW1, monkeypatch)
    decided = [v for v in forced.calls if (v.now - forced.calls[0].now).total_seconds() == MOVED]
    assert decided and decided[0].existing == LEGS
    book = decided[0].book
    assert book.yes_bids == lv((".49", 75), (".48", 20))
    assert book.no_asks == lv((".51", 75), (".52", 20), (".55", 10))
    assert book.no_bids == lv((".49", 75), (".48", 20))
    assert book.yes_asks == lv((".51", 75), (".52", 20))


# -- W1(a) consequence: own-vs-public crossing (v3.2 §1.1-§1.3) --------------------------------------------
@pytest.mark.parametrize("moved", [MW3, MW3B, MW3C], ids=["MW3", "MW3b", "MW3c"])
@pytest.mark.parametrize("engine", [EngineV2, ReferenceEngine], ids=["v2", "reference"])
def test_mw3_public_book_onto_a_resting_leg_cancels_crossed_book_without_replacement(tmp_path, monkeypatch,
                                                                                      moved, engine):
    e, _ = run(tmp_path, moved, monkeypatch, engine=engine)
    assert e.decisions[0].decision.action == "QUOTE"
    there = at_moved(e)
    assert [(d.decision.action, d.decision.reasons[0]) for d in there] == [("CANCEL", "CROSSED_BOOK")]
    assert e.states[there[0].condition_id].legs == ()
    assert sum(e.own_leg_crossed.values()) == 1


def test_mw3_frozen_kernel_gave_touch_buffer_and_a_same_instant_replacement(tmp_path, monkeypatch):
    from tools.research.maker_replay_v2.attribution import variant
    forced = Forced()
    monkeypatch.setattr(kernel_module, "decide", forced)
    src = source(tmp_path, MW3)
    e = variant(EngineV2, "frozen")(CONFIG, run_plan([src]))
    drive([src], [e], time_zones=ZONES)
    there = at_moved(e)
    assert [(d.decision.action, d.decision.reasons[0]) for d in there][0] == ("CANCEL", "TOUCH_BUFFER")
    assert len(there) == 2  # the same-instant replacement
    assert sum(e.own_leg_crossed.values()) == 0


def test_own_leg_crossed_is_not_counted_when_the_public_book_alone_is_crossed(tmp_path, monkeypatch):
    crossed = dict(yb=lv((".52", 75)), ya=lv((".51", 75)), nb=lv((".47", 75)), na=lv((".51", 75)))
    e, _ = run(tmp_path, crossed, monkeypatch)
    there = at_moved(e)
    assert there[0].decision.reasons[0] == "CROSSED_BOOK"
    assert sum(e.own_leg_crossed.values()) == 0


# -- W2(a): the replacement decides on the book without the cancelled legs (Annex K.2) ---------------------
def touch_buffer_cancel(value):
    return QuoteDecision("CANCEL", (), ("TOUCH_BUFFER",), "1" * 64, value.profile.name)


@pytest.mark.parametrize("engine", [EngineV2, ReferenceEngine], ids=["v2", "reference"])
def test_mw2_replacement_decides_on_the_public_book_with_no_existing_legs(tmp_path, monkeypatch, engine):
    # The public book at MOVED has a level at the YES leg's price, so the pre-cancel book differs from it.
    moved = dict(yb=lv((".48", 75)), ya=lv((".51", 75)), nb=lv((".49", 75)), na=lv((".51", 75)))
    e, forced = run(tmp_path, moved, monkeypatch, engine=engine, script={2: touch_buffer_cancel})
    assert len(forced.calls) >= 3
    cancelled, replacement = forced.calls[1], forced.calls[2]
    assert cancelled.existing == LEGS and replacement.existing == ()
    assert replacement.now == cancelled.now
    assert replacement.book.yes_bids == moved["yb"] and replacement.book.yes_asks == moved["ya"]
    assert replacement.book.no_bids == moved["nb"] and replacement.book.no_asks == moved["na"]
    assert cancelled.book.yes_bids == lv((".48", 95))


def test_replacement_refuses_resting_legs(tmp_path, monkeypatch):
    moved = dict(yb=lv((".48", 75)), ya=lv((".51", 75)), nb=lv((".49", 75)), na=lv((".51", 75)))

    class Sticky(EngineV2):
        def record_decision(self, cid, at, decision):
            super().record_decision(cid, at, decision)
            if decision.reasons[0] == "TOUCH_BUFFER":
                self.states[cid].set_legs(LEGS)  # a defect that left the cancelled legs resting

    forced = Forced({2: touch_buffer_cancel})
    monkeypatch.setattr(kernel_module, "decide", forced)
    src = source(tmp_path, moved)
    with pytest.raises(BundleError, match="replacement_with_resting_legs"):
        drive([src], [Sticky(replace(CONFIG, debug=False), run_plan([src]))], time_zones=ZONES)


# -- Mutants: each restores one frozen rule and must make a test above fail ---------------------------------
def fresh(tmp_path):
    inner = tmp_path / "mutant"
    inner.mkdir()
    return inner


def test_mutant_mw1_dropping_created_levels_is_caught(tmp_path, monkeypatch):
    from tools.research.maker_replay_v2.attribution import frozen_book
    monkeypatch.setattr(kernel_module, "compose_book", frozen_book)
    with pytest.raises(AssertionError):
        test_mw1_decision_book_carries_created_levels_on_all_four_arrays(fresh(tmp_path), monkeypatch)


def test_mutant_mw2_replacement_on_the_pre_cancel_book_is_caught(tmp_path, monkeypatch):
    def pre_cancel(self, state, cancelled):
        return kernel_module.compose_book(state.latest["book"], cancelled)
    monkeypatch.setattr(kernel_module.Kernel, "replacement_book", pre_cancel)
    with pytest.raises(AssertionError):
        test_mw2_replacement_decides_on_the_public_book_with_no_existing_legs(fresh(tmp_path), monkeypatch, EngineV2)


@pytest.mark.parametrize("moved", [MW3, MW3B, MW3C], ids=["MW3", "MW3b", "MW3c"])
def test_mutant_mw3_frozen_book_is_caught(tmp_path, monkeypatch, moved):
    from tools.research.maker_replay_v2.attribution import frozen_book
    monkeypatch.setattr(kernel_module, "compose_book", frozen_book)
    with pytest.raises(AssertionError):
        test_mw3_public_book_onto_a_resting_leg_cancels_crossed_book_without_replacement(
            fresh(tmp_path), monkeypatch, moved, EngineV2)


# -- Defender f0d97f11f note 2: the crossed check covers the NO pair too ------------------------------------
# Public book crossed on the NO pair only (no_bids .53 >= no_asks .51); the YES pair is not crossed.
NO_PAIR_CROSSED = dict(yb=lv((".47", 75)), ya=lv((".51", 75)), nb=lv((".53", 75)), na=lv((".51", 75)))


def test_own_leg_crossed_is_not_counted_when_the_public_no_pair_alone_is_crossed(tmp_path, monkeypatch):
    e, _ = run(tmp_path, NO_PAIR_CROSSED, monkeypatch)
    there = at_moved(e)
    assert there[0].decision.reasons[0] == "CROSSED_BOOK"
    assert sum(e.own_leg_crossed.values()) == 0


def test_mutant_crossed_yes_pair_only_is_caught(tmp_path, monkeypatch):
    def yes_only(book):
        return book is not None and bool(book.yes_bids and book.yes_asks) and (
            max(p for p, _ in book.yes_bids) >= min(p for p, _ in book.yes_asks))
    monkeypatch.setattr(kernel_module, "crossed", yes_only)
    with pytest.raises(AssertionError):
        test_own_leg_crossed_is_not_counted_when_the_public_no_pair_alone_is_crossed(tmp_path, monkeypatch)
