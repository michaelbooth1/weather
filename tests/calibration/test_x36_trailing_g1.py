"""Pure pieces of the L47 K row 112 G1 module (no data, no model, no run env)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "tools" / "research" / "x36_v5_reopen" / "x36_trailing_g1.py"
_SPEC = importlib.util.spec_from_file_location("x36_trailing_g1_under_test", _PATH)
g1 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(g1)


def _series():
    return {"denver": [(f"2023-08-{d:02d}", float(d)) for d in range(1, 21)]
            + [("2022-09-29", 100.0)]}


def test_grid_order_puts_smaller_lambda_then_smaller_window_first():
    assert g1.grid() == [(0, 0.0), (7, 0.25), (14, 0.25), (7, 0.5), (14, 0.5), (7, 0.75), (14, 0.75),
                         (7, 1.0), (14, 1.0)]


def test_b_recent_uses_strictly_earlier_same_year_dates_only():
    s = {m: sorted(v) for m, v in _series().items()}
    assert g1.b_recent(s, "denver", "2023-08-08", 7) == pytest.approx(sum(range(1, 8)) / 7)
    assert g1.b_recent(s, "denver", "2023-08-07", 7) is None  # six prior dates; 2022 is not borrowed
    assert g1.b_recent(s, "denver", "2023-08-21", 14) == pytest.approx(sum(range(7, 21)) / 14)


def test_shift_clips_and_zeroes():
    recent = {("denver", "2023-08-10", 7): 9.0, ("denver", "2023-08-10", 14): None}
    assert g1.shift(recent, {"denver": 1.0}, "denver", "2023-08-10", 7, 0.5) == pytest.approx(0.5 * 3.0)
    assert g1.shift(recent, {"denver": 8.0}, "denver", "2023-08-10", 7, 1.0) == pytest.approx(1.0)
    assert g1.shift(recent, {"denver": 1.0}, "denver", "2023-08-10", 14, 1.0) == 0.0
    assert g1.shift(recent, {"denver": 1.0}, "denver", "2023-08-10", 7, 0.0) == 0.0


def test_b_train_uses_only_named_years():
    s = {"denver": [("2022-08-01", 2.0), ("2023-08-01", 4.0), ("2024-08-01", 9.0)]}
    assert g1.b_train(s, {2022, 2023}) == {"denver": pytest.approx(3.0)}


def test_pick_breaks_ties_to_smaller_lambda_then_window():
    scores = {(0, 0.0): 10.0, (7, 0.5): 9.0, (14, 0.25): 9.0, (7, 0.25): 9.0 + 1e-13}
    assert g1.pick(scores) == (7, 0.25)
    assert g1.pick({(0, 0.0): 1.0, (14, 1.0): 1.0}) == (0, 0.0)


def test_gate_window_and_kill_line():
    assert g1.in_gate("2024-08-15") and g1.in_gate("2024-09-29")
    assert not g1.in_gate("2024-08-14")
    assert g1.verdict(-0.0006)["pass"] is True
    assert g1.verdict(-0.0005)["pass"] is False
    assert g1.verdict(0.001)["verdict"] == "KILL"
