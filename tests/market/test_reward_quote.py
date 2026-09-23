from decimal import Decimal

import pytest

from weather.market.reward_quote import QuoteRefused, price_reward_quote
from weather.market.reward_share_estimate import evaluate_sample


def inputs(bid="0.34", ask="0.35"):
    return {
        "yes_bids": [{"price": bid, "size": "100"}],
        "yes_asks": [{"price": ask, "size": "100"}],
        "no_bids": [{"price": str(1 - Decimal(ask)), "size": "100"}],
        "no_asks": [{"price": str(1 - Decimal(bid)), "size": "100"}],
        "reward_min_size": "20", "reward_max_spread_cents": "4.5",
        "reward_rate_per_day": "54", "tick": "0.01", "post_only_available": True,
    }


def test_handoff_golden_quote_matches_estimator_to_the_cent():
    quote = price_reward_quote(**inputs())
    assert (quote.adjusted_mid, quote.yes_buy, quote.no_buy, quote.reserve_pusd) == tuple(
        map(Decimal, ("0.345", "0.33", "0.64", "19.40"))
    )
    reference = evaluate_sample(
        [(0.34, 100)], [(0.35, 100)], max_spread_cents=4.5, min_size=20,
        sizes=(20,), distances_cents=(1.5,), min_size_for_mid=True,
    )["quotes"][(20.0, 1.5)]
    assert quote.share_many == pytest.approx(reference["share_many"])
    assert quote.share_single == pytest.approx(reference["share_single"])
    assert quote.own_q_min == pytest.approx(reference["own_q_min"])
    assert quote.predicted_per_minute_many == pytest.approx(54 / 1440 * quote.share_many)


def test_grid_never_crosses_exceeds_cap_or_snaps_inward():
    accepted = 0
    for bid_cents in range(17, 81):
        for spread_cents in range(1, 7):
            bid = Decimal(bid_cents) / 100
            ask = bid + Decimal(spread_cents) / 100
            mid = (bid + ask) / 2
            if not Decimal("0.20") <= mid <= Decimal("0.80"):
                continue
            quote = price_reward_quote(**inputs(str(bid), str(ask)))
            accepted += 1
            assert ask - quote.yes_buy >= Decimal("0.01")
            assert 1 - bid - quote.no_buy >= Decimal("0.01")
            assert mid - quote.yes_buy >= Decimal("0.015")
            assert 1 - mid - quote.no_buy >= Decimal("0.015")
            assert quote.reserve_pusd <= 20
            assert max(quote.yes_buy, quote.no_buy) * 20 <= 16
            assert quote.yes_buy % Decimal("0.01") == 0
            assert quote.no_buy % Decimal("0.01") == 0
    assert accepted > 300


@pytest.mark.parametrize("change, reason", [
    ({"tick": "0.001"}, "unsupported_tick"),
    ({"reward_min_size": 100}, "reward_minimum"),
    ({"reward_min_size": 0}, "reward_minimum"),
    ({"reward_rate_per_day": "39.99"}, "reward_terms"),
    ({"reward_max_spread_cents": "2.9"}, "reward_terms"),
    ({"post_only_available": False}, "post_only"),
    ({"post_only_available": 1}, "post_only"),
    ({"yes_asks": []}, "one_sided"),
    ({"yes_asks": [{"price": ".34", "size": 100}]}, "crossed"),
    ({"yes_asks": [{"price": ".41", "size": 100}]}, "spread"),
    ({"yes_asks": [{"price": ".351", "size": 100}]}, "off_tick"),
    ({"yes_bids": [{"price": ".34", "size": 19}]}, "no_size_adjusted"),
    ({"no_bids": [{"price": ".62", "size": 100}],
      "no_asks": [{"price": ".64", "size": 100}]}, "would_cross"),
    ({"per_band_ceiling": 10}, "capital_ceiling"),
    ({"per_order_ceiling": 10}, "capital_ceiling"),
    ({"per_band_ceiling": 21}, "invalid_capital"),
    ({"per_order_ceiling": 17}, "invalid_capital"),
])
def test_refusals(change, reason):
    with pytest.raises(QuoteRefused, match=reason):
        price_reward_quote(**{**inputs(), **change})


@pytest.mark.parametrize("field", ["reward_min_size", "reward_max_spread_cents", "reward_rate_per_day", "tick", "per_order_ceiling", "per_band_ceiling"])
@pytest.mark.parametrize("value", [None, True, "NaN", "Infinity", "-Infinity", "1e9999", "invalid"])
def test_bad_numbers_fail_closed(field, value):
    with pytest.raises(QuoteRefused, match="invalid_number"):
        price_reward_quote(**{**inputs(), field: value})


def test_small_touch_orders_bind_safety_but_do_not_set_adjusted_mid():
    values = inputs("0.32", "0.38")
    values["yes_bids"].append({"price": ".34", "size": 1})
    quote = price_reward_quote(**values)
    assert quote.adjusted_mid == Decimal(".35")
    values["yes_asks"].append({"price": ".33", "size": 1})
    with pytest.raises(QuoteRefused):
        price_reward_quote(**values)


@pytest.mark.parametrize("bid, ask", [(".18", ".19"), (".81", ".82")])
def test_midpoint_outside_treatment(bid, ask):
    with pytest.raises(QuoteRefused, match="midpoint_outside"):
        price_reward_quote(**inputs(bid, ask))
