"""Tests for the two-sided (NO-side) taker (item 253)."""

from __future__ import annotations

from weather.market import taker_bot_two_sided as ts
from weather.market.taker_bot_scoring import build_pnl_payload, settlement_outcome_for_order
from weather.market.taker_bot_strategy_registry import DEFAULT_STRATEGY_REGISTRY


def test_no_book_synthetic_from_yes_book():
    # Buying NO = selling YES: no_ask = 1 - yes_bid, no_bid = 1 - yes_ask.
    book = ts.no_book_fields({"best_bid": 0.55, "best_ask": 0.60})
    assert abs(book["no_best_ask"] - 0.45) < 1e-9
    assert abs(book["no_best_bid"] - 0.40) < 1e-9
    assert book["no_book_source"] == "synthetic_from_yes_bid"


def test_no_book_prefers_captured_no_token_book():
    book = ts.no_book_fields({
        "best_bid": 0.55,
        "no_best_ask": 0.42,
        "no_ask_size_at_best": 12.0,
        "no_ask_depth_1pct": 18.0,
        "no_book_age_seconds": 20.0,
    })
    assert book["no_best_ask"] == 0.42
    assert book["no_ask_size_at_best"] == 12.0
    assert book["no_ask_depth_1pct"] == 18.0
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


def test_no_side_input_row_marks_real_no_book_depth_eligible():
    row = {
        "fair_probability": 0.30,
        "best_bid": 0.55,
        "best_ask": 0.60,
        "clob_token_id": "YESTOK",
        "clob_no_token_id": "NOTOK",
        "no_best_bid": 0.40,
        "no_best_ask": 0.42,
        "no_ask_size_at_best": 12.0,
        "no_ask_depth_1pct": 18.0,
        "no_book_age_seconds": 20.0,
        "bin_kind": "eq",
        "bin_value": 24,
    }
    no_row = ts.no_side_input_row(row, {"two_sided_real_no_book_max_age_seconds": 120})
    assert no_row["no_book_source"] == "no_token_book"
    assert no_row["no_book_fresh"] is True
    assert no_row["real_no_book_depth_eligible"] is True
    assert no_row["ask_depth_1pct"] == 18.0


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


def _settled_no_order(no_book_source, eligible, no_book_fresh=None):
    if no_book_fresh is None:
        no_book_fresh = eligible
    return {
        "run_id": "r1",
        "target_date": "2026-06-14",
        "generated_at_utc": "2026-06-14T16:00:00+00:00",
        "strategy_id": "fade_overpriced",
        "strategy_family": "two_sided",
        "strategy_status": "shadow",
        "side": "NO_BUY",
        "order_status": "FILLED",
        "reason_code": "BUY_EDGE",
        "market_id": "atlanta",
        "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
        "range_label": "80-81 F",
        "bin_kind": "eq",
        "bin_value": 80,
        "bin_value_hi": 81,
        "clob_token_id": "NO80",
        "fair_probability": 0.70,
        "best_ask": 0.42,
        "edge": 0.28,
        "fill_size": 10.0,
        "fill_notional_usdc": 4.2,
        "total_spent_usdc": 4.3,
        "fee_usdc": 0.1,
        "pnl_fee_basis": "after_fee",
        "after_fee_pnl_scored": True,
        "after_slippage_pnl_scored": True,
        "executable_depth_model_version": "top_of_book_plus_1pct_depth_v1",
        "expected_profit_after_friction_per_share": 0.25,
        "settlement_status": "settled",
        "settlement_outcome": 1.0,
        "settlement_payout_usdc": 10.0,
        "settlement_pnl_usdc": 5.7,
        "net_pnl_usdc": 5.7,
        "pnl_source": "settlement_finalized",
        "no_book_source": no_book_source,
        "no_book_fresh": bool(no_book_fresh),
        "real_no_book_depth_eligible": bool(eligible),
    }


def test_synthetic_no_book_fill_is_non_promotable():
    payload = build_pnl_payload(
        [_settled_no_order("synthetic_from_yes_bid", False)],
        100,
        "r1",
        "2026-06-14",
        now="2026-06-15T12:00:00+00:00",
    )
    strategy = payload["by_strategy"][0]

    assert strategy["no_side_fill_count"] == 1
    assert strategy["no_side_synthetic_book_fill_count"] == 1
    assert strategy["no_side_live_scale_book_status"] == "BLOCK_SYNTHETIC_OR_STALE_NO_BOOK"
    assert strategy["settlement_promotion_gate_status"] == "BLOCK"
    assert "real_no_book_depth_for_two_sided" in strategy["settlement_promotion_failed_gates"]


def test_stale_real_no_book_fill_is_non_promotable():
    payload = build_pnl_payload(
        [_settled_no_order("no_token_book", False, no_book_fresh=False)],
        100,
        "r1",
        "2026-06-14",
        now="2026-06-15T12:00:00+00:00",
    )
    strategy = payload["by_strategy"][0]

    assert strategy["no_side_fill_count"] == 1
    assert strategy["no_side_stale_book_fill_count"] == 1
    assert strategy["no_side_live_scale_book_status"] == "BLOCK_SYNTHETIC_OR_STALE_NO_BOOK"
    assert "real_no_book_depth_for_two_sided" in strategy["settlement_promotion_failed_gates"]


def test_missing_real_no_book_depth_is_non_promotable():
    payload = build_pnl_payload(
        [_settled_no_order("no_token_book", False, no_book_fresh=True)],
        100,
        "r1",
        "2026-06-14",
        now="2026-06-15T12:00:00+00:00",
    )
    strategy = payload["by_strategy"][0]

    assert strategy["no_side_fill_count"] == 1
    assert strategy["no_side_missing_depth_fill_count"] == 1
    assert strategy["no_side_live_scale_book_status"] == "BLOCK_SYNTHETIC_OR_STALE_NO_BOOK"
    assert "real_no_book_depth_for_two_sided" in strategy["settlement_promotion_failed_gates"]


def test_real_no_book_fill_clears_book_depth_promotion_gate():
    payload = build_pnl_payload(
        [_settled_no_order("no_token_book", True)],
        100,
        "r1",
        "2026-06-14",
        now="2026-06-15T12:00:00+00:00",
    )
    strategy = payload["by_strategy"][0]

    assert strategy["no_side_real_book_fill_count"] == 1
    assert strategy["no_side_live_scale_book_status"] == "PASS"
    assert "real_no_book_depth_for_two_sided" not in strategy["settlement_promotion_failed_gates"]
