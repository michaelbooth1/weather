"""Shadow leg handling after a paper fill matches the replay kernel: the first fill cancels the band.

Fictional fixtures only (``fixtures.shadow_rig``). Separate commit so it can be dropped on its own.

Guards: parity with replay v2 ``FILL_CANCEL_SIBLING``/``END`` at the fill instant (Defender COMPOSE-ALIGN N3;
owner parity definition 2026-10-08); docs/operations/maker-shadow-runner.md, shadow campaign book.
"""
from datetime import timedelta
from decimal import Decimal as D

from maker_core.shadow.tape import inputs_from

from .fixtures.shadow_rig import CONDITION, MARKETS, NO, NOW, YES, Reads, data_print, paper_ledger, rig


def filled_minute(tmp_path, prints):
    reads = Reads()
    runner, _, _, clock, _ = rig(tmp_path, paper=paper_ledger(rule="at_price"), reads=reads)
    first = runner.step(NOW, MARKETS)
    assert first["conditions"][0]["decision"]["action"] == "QUOTE"
    reads.prints = {CONDITION: prints}
    clock.now = NOW + timedelta(minutes=1)
    return runner, runner.step(clock.now, MARKETS)


def test_first_fill_cancels_the_sibling_and_the_next_decision_has_no_own_legs(tmp_path):
    # Both legs would fill from these prints; replay cancels the band at the first (YES at +10 s).
    runner, second = filled_minute(tmp_path, [data_print(YES, NOW + timedelta(seconds=10), "0.48", 5, tx="0x1"),
                                              data_print(NO, NOW + timedelta(seconds=20), "0.48", 50, tx="0x2")])
    fills = second["paper"]["fills"]
    assert [(f["outcome"], D(f["size"])) for f in fills] == [("YES", D(5))]
    row = second["conditions"][0]
    inputs = inputs_from(row["inputs"])
    assert inputs.fill_seen is True and inputs.existing == ()
    assert (D(".48"), D(30)) not in inputs.book.yes_bids  # no resting leg composed into the book
    assert (row["decision"]["action"], row["decision"]["reasons"][0]) == ("CANCEL", "FILL_CANCEL_SIBLING")
    assert second["own_size_mid"]["books_with_own_legs"] == 0
    assert second["resting_after"] == {} and runner.resting == {}


def test_earliest_print_wins_whatever_the_leg_order(tmp_path):
    _, second = filled_minute(tmp_path, [data_print(YES, NOW + timedelta(seconds=30), "0.48", 50, tx="0x1"),
                                         data_print(NO, NOW + timedelta(seconds=5), "0.48", 7, tx="0x2")])
    assert [(f["outcome"], D(f["size"])) for f in second["paper"]["fills"]] == [("NO", D(7))]


def test_no_print_keeps_both_legs_resting(tmp_path):
    runner, second = filled_minute(tmp_path, [])
    assert second["paper"]["fills"] == [] and set(runner.resting) == {CONDITION}
    assert second["own_size_mid"]["books_with_own_legs"] == 1
