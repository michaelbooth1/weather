"""OD23 diagnostic in the replay v2 kernel: per UTC date, decision books with own legs and those whose qualified
mid differs with own size removed. Count only: the decisions are unchanged.

Fictional fixtures only; the first decision is forced to a known QUOTE (as in ``test_replay_v2_own_legs``).

Guards: OD23 (signed 2026-10-08, DECISION_LOG): the shadow gate reports how many decisions' qualified mid would
differ with own size removed; engine ruling W1(a) composition imported from ``maker_core.quoting.book``.
"""
from decimal import Decimal as D

import pytest

from maker_core.quoting import book as book_module
from maker_core.replay.v2 import kernel as kernel_module
from maker_core.replay.v2.engine import EngineV2
from maker_core.replay.v2.reference import ReferenceEngine
from .test_replay_v2_own_legs import lv, run

# The YES leg (.48 x 20, min_size 20) becomes the best qualified bid over .47: mid .495 vs public .49.
MID_MOVE = dict(yb=lv((".47", 75)), ya=lv((".51", 75)), nb=lv((".49", 75)), na=lv((".53", 75)))
# The public book changes (a new decision) but the best qualified bid .49 stays ahead of the YES leg at .48.
BEHIND = dict(yb=lv((".49", 80)), ya=lv((".51", 75)), nb=lv((".49", 75)), na=lv((".51", 75)))


def test_kernel_composes_through_the_quoting_module():
    assert kernel_module._compose_book is book_module.compose_book
    assert kernel_module.crossed is book_module.crossed


@pytest.mark.parametrize("engine", [EngineV2, ReferenceEngine], ids=["v2", "reference"])
def test_resting_leg_that_sets_the_best_qualified_bid_is_counted(tmp_path, monkeypatch, engine):
    e, _ = run(tmp_path, MID_MOVE, monkeypatch, engine=engine)
    assert sum(e.own_size_books.values()) >= 1
    assert sum(e.own_mid_differs.values()) >= 1
    assert set(e.own_mid_differs) <= set(e.own_size_books)


@pytest.mark.parametrize("engine", [EngineV2, ReferenceEngine], ids=["v2", "reference"])
def test_resting_legs_behind_the_best_are_counted_as_books_but_not_as_differences(tmp_path, monkeypatch, engine):
    e, _ = run(tmp_path, BEHIND, monkeypatch, engine=engine)
    assert sum(e.own_size_books.values()) >= 1
    assert sum(e.own_mid_differs.values()) == 0


def sub(tmp_path, name):
    (tmp_path / name).mkdir()
    return tmp_path / name


def test_diagnostic_does_not_change_decisions(tmp_path, monkeypatch):
    counted, _ = run(sub(tmp_path, "on"), MID_MOVE, monkeypatch)
    monkeypatch.setattr(kernel_module.Kernel, "own_mid_diagnostic", lambda self, state, book, at: None)
    silent, _ = run(sub(tmp_path, "off"), MID_MOVE, monkeypatch)
    assert counted.decision_sha.hexdigest() == silent.decision_sha.hexdigest()
    assert sum(silent.own_mid_differs.values()) == 0


def test_engines_agree_on_the_counts(tmp_path, monkeypatch):
    v2, _ = run(sub(tmp_path, "v2"), MID_MOVE, monkeypatch, engine=EngineV2)
    ref, _ = run(sub(tmp_path, "ref"), MID_MOVE, monkeypatch, engine=ReferenceEngine)
    assert (v2.own_size_books, v2.own_mid_differs) == (ref.own_size_books, ref.own_mid_differs)


def test_mutant_diagnostic_on_the_frozen_book_misses_a_created_level(tmp_path, monkeypatch):
    from tools.research.maker_replay_v2.attribution import frozen_book
    monkeypatch.setattr(kernel_module.Kernel, "decision_book",
                        lambda self, state, legs: frozen_book(state.latest["book"], legs))
    e, _ = run(tmp_path, MID_MOVE, monkeypatch)
    assert sum(e.own_mid_differs.values()) == 0  # .48 is not a public level: the frozen rule cannot move the mid
