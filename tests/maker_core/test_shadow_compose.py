"""Shadow runner decision book: the public book with its resting paper legs, built by the engine's own
``compose_book`` (imported, not copied), and the OD23 own-size mid diagnostic counts on the minute tape.

Fictional fixtures only (``fixtures.shadow_rig``).

Guards: OD23 (signed 2026-10-08, DECISION_LOG) and engine ruling W1(a): forward shadow and replay v2 decide on
the same composed book (parity blocker 2, owner 2026-10-08 20:21); docs/operations/maker-shadow-runner.md.
"""
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

from maker_core.evidence.journal import digest
from maker_core.quoting import book as book_module
from maker_core.shadow import runner as runner_module
from maker_core.shadow.tape import inputs_from

from .fixtures.shadow_rig import MARKETS, NO, NOW, YES, Reads, public_book, rig


def levels(rows):
    return [(D(p), D(s)) for p, s in rows]


def two_minutes(tmp_path, second_yes_bids):
    """Minute 1 quotes on the rig book; minute 2 reads a YES book with ``second_yes_bids``."""
    reads = Reads()
    runner, _, _, clock, _ = rig(tmp_path, reads=reads)
    first = runner.step(NOW, MARKETS)
    legs = first["conditions"][0]["decision"]["legs"]
    reads.books[YES] = public_book(YES, bids=second_yes_bids)
    clock.now = NOW + timedelta(minutes=1)
    return first, runner.step(clock.now, MARKETS), legs


def test_runner_imports_the_engine_composition_and_defines_no_copy():
    assert runner_module.compose_book is book_module.compose_book
    source = Path(runner_module.__file__).read_text(encoding="utf-8")
    assert "def compose_book" not in source and "def add_own" not in source


def test_first_minute_has_no_own_legs_and_decides_on_the_public_book(tmp_path):
    first, _, _ = two_minutes(tmp_path, (("0.49", "75"),))
    row = first["conditions"][0]
    assert row["decision"]["action"] == "QUOTE"
    assert inputs_from(row["inputs"]).book.yes_bids == tuple(levels((("0.49", "75"),)))
    assert first["own_size_mid"] == {"books_with_own_legs": 0, "mid_differs": 0, "own_leg_crossed": 0}


def test_resting_legs_are_on_the_decision_book_and_the_tape_round_trips(tmp_path):
    first, second, legs = two_minutes(tmp_path, (("0.49", "75"),))
    yes_leg = next(leg for leg in legs if leg["outcome"] == "YES")
    no_leg = next(leg for leg in legs if leg["outcome"] == "NO")
    row = second["conditions"][0]
    inputs = inputs_from(row["inputs"])
    assert [(leg.outcome, leg.price, leg.size) for leg in inputs.existing] == [
        (leg["outcome"], D(leg["price"]), D(leg["size"])) for leg in legs]
    assert (D(yes_leg["price"]), D(yes_leg["size"])) in inputs.book.yes_bids
    assert (D(no_leg["price"]), D(no_leg["size"])) in inputs.book.no_bids
    assert (1 - D(yes_leg["price"]), D(yes_leg["size"])) in inputs.book.no_asks
    assert digest(inputs) == row["decision"]["input_hash"]
    assert second["own_size_mid"] == {"books_with_own_legs": 1, "mid_differs": 0, "own_leg_crossed": 0}  # .49 x 75 stays best


def test_a_resting_leg_that_becomes_the_best_qualified_bid_is_counted(tmp_path):
    # The public YES bid drops to .47: the resting YES leg (.48, size >= min 20) is now the best qualified bid.
    _, second, legs = two_minutes(tmp_path, (("0.47", "75"),))
    yes_leg = next(leg for leg in legs if leg["outcome"] == "YES")
    assert D(yes_leg["price"]) == D(".48") and D(yes_leg["size"]) >= 20
    assert second["own_size_mid"] == {"books_with_own_legs": 1, "mid_differs": 1, "own_leg_crossed": 0}


def test_marks_use_the_public_book_not_the_composed_one(tmp_path):
    from .fixtures.shadow_rig import paper_ledger
    paper = paper_ledger()
    reads = Reads()
    runner, _, _, clock, _ = rig(tmp_path, reads=reads, paper=paper)
    seen = []
    original = paper.mark
    paper.mark = lambda asset, cid, bids, asks, at: (seen.append((asset, bids)), original(asset, cid, bids, asks, at))
    runner.step(NOW, MARKETS)
    clock.now = NOW + timedelta(minutes=1)
    runner.step(clock.now, MARKETS)
    assert {bids for asset, bids in seen if asset == YES} == {tuple(levels((("0.49", "75"),)))}
    assert {bids for asset, bids in seen if asset == NO} == {tuple(levels((("0.49", "100"),)))}


def test_public_book_moving_onto_a_resting_leg_is_counted_as_own_leg_crossed(tmp_path):
    # The public YES ask drops to .48, onto the resting YES leg: only the composed book is crossed.
    reads = Reads()
    runner, _, _, clock, _ = rig(tmp_path, reads=reads)
    first = runner.step(NOW, MARKETS)
    assert first["own_size_mid"]["own_leg_crossed"] == 0
    reads.books[YES] = public_book(YES, bids=(("0.47", "75"),), asks=(("0.48", "75"),))
    clock.now = NOW + timedelta(minutes=1)
    second = runner.step(clock.now, MARKETS)
    decision = second["conditions"][0]["decision"]
    assert (decision["action"], decision["reasons"][0]) == ("CANCEL", "CROSSED_BOOK")
    assert second["own_size_mid"]["own_leg_crossed"] == 1


def test_a_public_book_crossed_on_its_own_is_not_own_leg_crossed(tmp_path):
    reads = Reads()
    runner, _, _, clock, _ = rig(tmp_path, reads=reads)
    runner.step(NOW, MARKETS)
    reads.books[YES] = public_book(YES, bids=(("0.52", "75"),), asks=(("0.51", "75"),))
    clock.now = NOW + timedelta(minutes=1)
    second = runner.step(clock.now, MARKETS)
    assert second["conditions"][0]["decision"]["reasons"][0] == "CROSSED_BOOK"
    assert second["own_size_mid"]["own_leg_crossed"] == 0
