"""Tests for the two-sided (NO-side) taker (item 253)."""

from __future__ import annotations

from weather.market import taker_bot_two_sided as ts
from weather.market.taker_bot_scoring import settlement_outcome_for_order
from weather.market.taker_bot_strategy_registry import DEFAULT_STRATEGY_REGISTRY


def test_no_book_synthetic_from_yes_book():
    # Buying NO = selling YES: no_ask = 1 - yes_bid, no_bid = 1 - yes_ask.
    book = ts.no_book_fields({"best_bid": 0.55, "best_ask": 0.60})
    assert abs(book["no_best_ask"] - 0.45) < 1e-9
    assert abs(book["no_best_bid"] - 0.40) < 1e-9
    assert book["no_book_source"] == "synthetic_from_yes_bid"


def test_no_book_prefers_captured_no_token_book():
    book = ts.no_book_fields({"best_bid": 0.55, "no_best_ask": 0.42, "no_ask_size_at_best": 12.0})
    assert book["no_best_ask"] == 0.42
    assert book["no_ask_size_at_best"] == 12.0
    assert book["no_book_source"] == "no_token_book"


def test_no_book_unavailable_without_yes_bid():
    book = ts.no_book_fields({"best_ask": 0.60})
    assert book["no_best_ask"] is None
    assert book["no_book_source"] == "unavailable"


def test_no_edge_positive_when_market_overprices_yes():
    # Model fair_yes=0.30 (fair_no=0.70); yes_bid=0.55 -> no_ask=0.45.
    # NO edge = 0.70 - 0.45 = 0.25 > 0  => the market over-prices the YES band.
    row = {"fair_probability": 0.30, "best_bid": 0.55, "best_ask": 0.60}
    assert abs(ts.no_edge(row) - 0.25) < 1e-9


def test_no_side_input_row_repoints_fair_book_and_token():
    row = {
        "fair_probability": 0.30,
        "best_bid": 0.55,
        "best_ask": 0.60,
        "clob_token_id": "YESTOK",
        "clob_no_token_id": "NOTOK",
        "bin_kind": "eq",
        "bin_value": 24,
    }
    no_row = ts.no_side_input_row(row)
    assert no_row["taker_side"] == "NO_BUY"
    assert abs(no_row["fair_probability"] - 0.70) < 1e-9   # fair_no
    assert no_row["yes_fair_probability"] == 0.30
    assert no_row["clob_token_id"] == "NOTOK"
    assert abs(no_row["best_ask"] - 0.45) < 1e-9            # no_ask
    # band identity is preserved so the existing gates apply unchanged
    assert no_row["bin_kind"] == "eq" and no_row["bin_value"] == 24


def test_no_side_input_row_none_without_no_token_or_book():
    assert ts.no_side_input_row({"fair_probability": 0.3, "best_bid": 0.5}) is None  # no NO token
    assert ts.no_side_input_row({"fair_probability": 0.3, "clob_no_token_id": "N"}) is None  # no book


def test_settlement_outcome_inverts_for_no_buy():
    # Band eq=24, settlement bucket = 23 -> YES on 24 LOSES, NO on 24 WINS.
    settlement = {"settlement_bucket": 23}
    band = {"bin_kind": "eq", "bin_value": 24, "bin_value_hi": 24}
    yes_row = {**band, "side": "YES_BUY"}
    no_row = {**band, "side": "NO_BUY"}
    assert settlement_outcome_for_order(yes_row, settlement) == 0.0
    assert settlement_outcome_for_order(no_row, settlement) == 1.0


def test_yes_loses_no_wins_end_to_end_fixture():
    # The June-20-style mistake: model buys YES on a warm band above the eventual
    # high and loses. The same view ("this band is over-priced") on the NO side
    # would have won. This is the edge the YES-only bot discards.
    settlement = {"settlement_bucket": 23}
    input_row = {
        "fair_probability": 0.30,        # model: 30% the high is exactly 24
        "best_bid": 0.55, "best_ask": 0.60,  # market prices YES-24 ~0.6 (over-priced vs model)
        "clob_token_id": "YES24", "clob_no_token_id": "NO24",
        "bin_kind": "eq", "bin_value": 24, "bin_value_hi": 24, "side": "YES_BUY",
    }
    # YES side: settles to a loss.
    assert settlement_outcome_for_order(input_row, settlement) == 0.0
    # NO side: positive model edge AND settles to a win.
    no_row = ts.no_side_input_row(input_row)
    assert ts.no_edge(input_row) > 0
    no_scored = {**no_row, "side": "NO_BUY"}
    assert settlement_outcome_for_order(no_scored, settlement) == 1.0


def test_fade_overpriced_arm_registered_and_two_sided():
    arm = DEFAULT_STRATEGY_REGISTRY.get("fade_overpriced")
    assert arm is not None
    assert arm["strategy_family"] == "two_sided"
    assert arm["config_overrides"]["two_sided_enabled"] is True
    assert ts.two_sided_enabled(arm["config_overrides"]) is True
    assert ts.two_sided_enabled({}) is False  # YES-only arms unchanged
