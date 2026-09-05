from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D, Inexact, localcontext
from zoneinfo import ZoneInfo

import pytest

from weather.market.maker_incentive_feasibility import (
    AdjustedMidpoint,
    Book,
    BuyQuote,
    Campaign,
    Capital,
    CompetitionScenario,
    EpochPayoutModel,
    Evidence,
    FeasibilityInputError,
    MarketTerms,
    ScoringRules,
    assess_buy_plan,
)


AS_OF = datetime(2026, 5, 28, 12, tzinfo=timezone.utc)
COLLATERAL = "eip155:137/erc20:0x" + "1" * 40
REWARD = "eip155:137/erc20:0x" + "2" * 40
CONDITION = "0x" + "a" * 64


def _inputs():
    slug = "highest-temperature-in-toronto-on-may-28-2026"
    evidence = lambda character: Evidence(character * 64, AS_OF)
    return {
        "market": MarketTerms(
            "polymarket_global", slug, CONDITION, "101", "202", COLLATERAL,
            D("5"), D("0.01"), D("20"), D("5"), evidence("a"), True,
            "collateral", "synthetic explicit minimum-notional source",
        ),
        "yes_book": Book(slug, CONDITION, "101", D("0.49"), D("0.51"), evidence("b")),
        "no_book": Book(slug, CONDITION, "202", D("0.49"), D("0.51"), evidence("c")),
        "midpoint": AdjustedMidpoint(
            D("0.50"), "size_cutoff_adjusted", "synthetic adjusted-midpoint fixture",
            D("20"), "b" * 64, "c" * 64, evidence("d"),
        ),
        "rules": ScoringRules(D("1"), D("3"), D("0.10"), D("0.90"), evidence("e")),
        "campaigns": (Campaign(
            "synthetic-campaign", CONDITION, REWARD,
            AS_OF.replace(hour=0), AS_OF.replace(hour=0) + timedelta(days=1),
            "synthetic explicit UTC half-open interval", D("144"), evidence("f"),
        ),),
        "quotes": (BuyQuote("YES", "101", D("0.49"), D("20")), BuyQuote("NO", "202", D("0.49"), D("20"))),
        "capital": Capital(COLLATERAL, D("100"), D("0"), D("0"), D("100"), D("0"), D("0"), D("0"), D("10"), D("25"), D("50"), D("100")),
        "scenarios": (CompetitionScenario("assumed other-maker score range", D("12.8"), D("38.4"), D("1"), D("1"), D("1")),),
        "as_of": AS_OF,
        "horizon_end": AS_OF + timedelta(hours=1),
        "max_input_age": timedelta(hours=24),
        "max_book_age": timedelta(seconds=30),
        "max_book_skew": timedelta(seconds=5),
        "other_own_orders_absent": True,
    }


def _payout():
    return EpochPayoutModel(
        "synthetic constant-score epoch; no other own liquidity",
        "synthetic-campaign", CONDITION, REWARD,
        AS_OF.replace(hour=0), AS_OF.replace(hour=0) + timedelta(days=1),
        D("144"), 1440, 60, D("1"), Evidence("9" * 64, AS_OF),
    )


def test_quadratic_cents_scores_and_own_denominator_without_invented_payment():
    result = assess_buy_plan(**_inputs())

    # 20 * ((5 - 1) / 5)^2 = 12.8 on each complementary BUY side.
    assert result["side_scores"] == {"YES": D("12.8"), "NO": D("12.8")}
    assert result["own_q_min"] == D("12.8")
    assert result["scenarios"][0]["conditional_sample_share_range"] == (D("0.25"), D("0.5"))
    assert result["order_notionals"] == (D("9.80"), D("9.80"))
    assert result["simultaneous_reservation"] == D("19.60")
    assert result["minimum_qualifying_shares_by_outcome"] == {"YES": D("20"), "NO": D("20")}
    assert result["incentive_feasible"] is True
    assert result["scenarios"][0]["conditional_reward_amount_range"] == (None, None)
    assert result["payment_estimation_status"] == "unresolved_or_infeasible"
    assert result["paid_rewards"] is result["realized_pnl"] is None
    assert result["no_payment_amount"] == 0
    assert result["live_order_authority"] is False


def test_native_market_identity_is_preserved_for_celsius_and_fahrenheit():
    for location, unit in (("toronto", "C"), ("nyc", "F")):
        inputs = _inputs()
        slug = f"highest-temperature-in-{location}-on-may-28-2026"
        for key in ("market", "yes_book", "no_book"):
            inputs[key] = replace(inputs[key], event_slug=slug)
        result = assess_buy_plan(**inputs)
        assert (result["location_id"], result["settlement_unit"]) == (location, unit)
        assert result["event_date"].isoformat() == "2026-05-28"
        assert result["condition_id"] == CONDITION
        assert result["token_ids"] == {"YES": "101", "NO": "202"}


def test_two_orders_fit_order_cap_but_fail_simultaneous_condition_budget():
    inputs = _inputs()
    inputs["capital"] = replace(inputs["capital"], condition_cap=D("10"))
    result = assess_buy_plan(**inputs, payout_model=_payout())
    assert result["order_feasible"] is result["reward_eligible"] is True
    assert result["capital_feasible"] is result["incentive_feasible"] is False
    assert result["blockers"]["capital"] == ("capital:condition_cap",)
    assert result["scenarios"][0]["conditional_reward_amount_range"] == (None, None)


@pytest.mark.parametrize("field,value,blocker", (
    ("available_collateral", "19.59", "capital:available_collateral"),
    ("order_cap", "9.79", "capital:order_cap"),
    ("event_cap", "19.59", "capital:event_cap"),
    ("wallet_cap", "99.99", "capital:wallet_cap"),
))
def test_capital_limits_are_independent(field, value, blocker):
    inputs = _inputs()
    inputs["capital"] = replace(inputs["capital"], **{field: D(value)})
    assert blocker in assess_buy_plan(**inputs)["blockers"]["capital"]


def test_existing_inventory_reserves_and_cleanup_are_prefunded_without_netting():
    inputs = _inputs()
    inputs["capital"] = Capital(COLLATERAL, D("30"), D("5"), D("4"), D("21"), D("5"), D("9"), D("1.41"), D("10"), D("30"), D("30"), D("30"))
    result = assess_buy_plan(**inputs)
    assert result["total_committed_with_plan_and_cleanup"] == D("30.01")
    assert result["required_available_with_cleanup"] == D("21.01")
    assert "capital:available_collateral" in result["blockers"]["capital"]
    inputs["capital"] = replace(inputs["capital"], cleanup_reserve=D("1.40"))
    assert assess_buy_plan(**inputs)["capital_feasible"] is True


@pytest.mark.parametrize("field,value,code", (
    ("available_collateral", D("101"), "capital:available_exceeds_backing"),
    ("inventory_cost", D("101"), "capital:unbacked_existing_commitments"),
    ("condition_committed", D("1"), "capital:inconsistent_scope_commitments"),
    ("collateral_asset", REWARD, "capital:asset_mismatch"),
))
def test_unbacked_or_wrong_asset_inputs_are_rejected(field, value, code):
    inputs = _inputs()
    inputs["capital"] = replace(inputs["capital"], **{field: value})
    with pytest.raises(FeasibilityInputError, match=code):
        assess_buy_plan(**inputs)


@pytest.mark.parametrize("price,shares,group,blocker", (
    ("0.49", "19", "rewards", "YES:below_reward_minimum"),
    ("0.49", "4", "orders", "YES:below_exchange_minimum"),
    ("0.495", "20", "orders", "YES:off_tick"),
    ("0.51", "20", "orders", "YES:marketable_buy"),
    ("0.45", "20", "rewards", "YES:zero_reward_score"),
    ("0.44", "20", "rewards", "YES:zero_reward_score"),
))
def test_order_size_tick_post_only_and_reward_distance_are_separate(price, shares, group, blocker):
    inputs = _inputs()
    inputs["quotes"] = (BuyQuote("YES", "101", D(price), D(shares)),)
    result = assess_buy_plan(**inputs, payout_model=_payout())
    assert blocker in result["blockers"][group]
    assert result["incentive_feasible"] is False
    assert result["scenarios"][0]["conditional_reward_amount_range"] == (None, None)


def test_exchange_minimum_can_exceed_reward_minimum():
    inputs = _inputs()
    inputs["market"] = replace(inputs["market"], order_min_size=D("11"))
    result = assess_buy_plan(**inputs)
    assert result["minimum_qualifying_shares_by_outcome"]["YES"] == D("22.448979591836734694")
    assert "YES:below_exchange_minimum" in result["blockers"]["orders"]


def test_exchange_minimum_uses_explicit_shares_or_collateral_units():
    inputs = _inputs()
    inputs["market"] = replace(inputs["market"], order_min_size=D("15"))
    assert assess_buy_plan(**inputs)["order_feasible"] is False  # 9.80 collateral < 15.
    inputs["market"] = replace(inputs["market"], order_min_size_unit="shares", order_min_size_reference="synthetic explicit share minimum")
    assert assess_buy_plan(**inputs)["order_feasible"] is True  # 20 shares >= 15.
    inputs["market"] = replace(inputs["market"], order_min_size_unit="unknown")
    with pytest.raises(FeasibilityInputError, match="order_min_size:unit_unproved"):
        assess_buy_plan(**inputs)


def test_closed_order_intake_and_unmodelled_own_orders_do_not_qualify():
    inputs = _inputs()
    inputs["market"] = replace(inputs["market"], accepting_orders=False)
    result = assess_buy_plan(**inputs, payout_model=_payout())
    assert result["blockers"]["orders"] == ("market:not_accepting_orders",)
    assert result["incentive_feasible"] is False
    inputs = _inputs()
    inputs["other_own_orders_absent"] = False
    with pytest.raises(FeasibilityInputError, match="plan:other_own_orders_not_excluded"):
        assess_buy_plan(**inputs)


def test_complementary_book_bid_can_make_buy_marketable():
    inputs = _inputs()
    inputs["yes_book"] = replace(inputs["yes_book"], best_bid=D("0.3"), best_ask=D("0.8"))
    inputs["no_book"] = replace(inputs["no_book"], best_bid=D("0.6"), best_ask=D("0.7"))
    inputs["quotes"] = (BuyQuote("YES", "101", D("0.4"), D("20")),)
    result = assess_buy_plan(**inputs)
    assert result["blockers"]["orders"] == ("YES:complementary_marketable_buy",)


@pytest.mark.parametrize("midpoint,single_side_scores", (("0.099", False), ("0.10", True), ("0.90", True), ("0.901", False)))
def test_midrange_endpoints_and_complementary_buy_sides(midpoint, single_side_scores):
    inputs = _inputs()
    inputs["market"] = replace(inputs["market"], order_price_min_tick_size=D("0.001"), order_min_size=D("0.01"))
    for key in ("yes_book", "no_book"):
        inputs[key] = replace(inputs[key], best_bid=D("0.001"), best_ask=D("0.999"))
    inputs["midpoint"] = replace(inputs["midpoint"], yes_price=D(midpoint))
    yes = BuyQuote("YES", "101", D(midpoint) - D("0.01"), D("20"))
    no = BuyQuote("NO", "202", D("1") - D(midpoint) - D("0.01"), D("20"))
    inputs["quotes"] = (yes,)
    inputs["capital"] = replace(inputs["capital"], order_cap=D("20"))
    assert (assess_buy_plan(**inputs)["own_q_min"] > 0) is single_side_scores
    inputs["quotes"] = (no,)
    assert (assess_buy_plan(**inputs)["own_q_min"] > 0) is single_side_scores
    inputs["quotes"] = (yes, no)
    assert assess_buy_plan(**inputs)["own_q_min"] == D("12.8")


@pytest.mark.parametrize("campaign_change,blocker", (
    (None, "campaign:absent"),
    ({"ends_at": AS_OF}, "campaign:no_horizon_overlap"),
    ({"starts_at": AS_OF + timedelta(hours=1)}, "campaign:no_horizon_overlap"),
    ({"rate_per_day": D("0")}, "campaign:no_positive_allocation"),
))
def test_absent_expired_future_or_unfunded_campaign_is_explicit_infeasibility(campaign_change, blocker):
    inputs = _inputs()
    inputs["campaigns"] = () if campaign_change is None else (replace(inputs["campaigns"][0], **campaign_change),)
    result = assess_buy_plan(**inputs)
    assert result["order_feasible"] is result["capital_feasible"] is True
    assert result["incentive_feasible"] is False
    assert blocker in result["blockers"]["rewards"]


@pytest.mark.parametrize("change,code", (
    ("multiple_campaigns", "campaign:ambiguous_multiple_allocations"),
    ("campaign_condition", "campaign:condition_mismatch"),
    ("campaign_asset", "reward:asset_invalid"),
    ("book_token", "YES:book_identity_mismatch"),
    ("quote_token", "quote:token_identity_mismatch"),
    ("platform", "platform:not_international"),
    ("event", "event_slug:unrecognized"),
    ("ordinary_midpoint", "midpoint:adjustment_unproved"),
    ("midpoint_hash", "midpoint:book_hash_mismatch"),
    ("midpoint_cutoff", "midpoint:cutoff_mismatch"),
    ("book_stale", "YES_book:stale_or_future"),
    ("book_skew", "books:timestamp_skew"),
    ("future_economics", "economics:stale_or_future"),
    ("unhashed_economics", "economics:hash_invalid"),
))
def test_bound_identity_freshness_and_midpoint_provenance_are_required(change, code):
    inputs = _inputs()
    campaign = inputs["campaigns"][0]
    if change == "multiple_campaigns":
        inputs["campaigns"] = (campaign, campaign)
    elif change == "campaign_condition":
        inputs["campaigns"] = (replace(campaign, condition_id="0x" + "b" * 64),)
    elif change == "campaign_asset":
        inputs["campaigns"] = (replace(campaign, reward_asset="USDC"),)
    elif change == "book_token":
        inputs["yes_book"] = replace(inputs["yes_book"], token_id="202")
    elif change == "quote_token":
        inputs["quotes"] = (replace(inputs["quotes"][0], token_id="202"),)
    elif change == "platform":
        inputs["market"] = replace(inputs["market"], platform="polymarket_us")
    elif change == "event":
        inputs["market"] = replace(inputs["market"], event_slug="event")
    elif change == "ordinary_midpoint":
        inputs["midpoint"] = replace(inputs["midpoint"], kind="ordinary_midpoint")
    elif change == "midpoint_hash":
        inputs["midpoint"] = replace(inputs["midpoint"], yes_book_sha256="0" * 64)
    elif change == "midpoint_cutoff":
        inputs["midpoint"] = replace(inputs["midpoint"], cutoff_shares=D("5"))
    elif change in {"book_stale", "book_skew"}:
        age = 31 if change == "book_stale" else 6
        inputs["yes_book"] = replace(inputs["yes_book"], evidence=Evidence("b" * 64, AS_OF - timedelta(seconds=age)))
    elif change == "future_economics":
        inputs["market"] = replace(inputs["market"], evidence=Evidence("a" * 64, AS_OF + timedelta(seconds=1)))
    elif change == "unhashed_economics":
        inputs["market"] = replace(inputs["market"], evidence=Evidence("", AS_OF))
    with pytest.raises(FeasibilityInputError, match=code):
        assess_buy_plan(**inputs)


def test_missing_midpoint_does_not_substitute_ordinary_book_midpoint():
    inputs = _inputs()
    inputs["midpoint"] = None
    result = assess_buy_plan(**inputs, payout_model=_payout())
    assert result["order_feasible"] is True
    assert result["own_q_min"] is None
    assert result["blockers"]["rewards"] == ("midpoint:missing",)
    assert result["scenarios"][0]["conditional_reward_amount_range"] == (None, None)


def test_freshness_uses_elapsed_utc_time_across_repeated_local_hour():
    inputs = _inputs()
    local = ZoneInfo("America/Toronto")
    first = datetime(2026, 11, 1, 1, 30, tzinfo=local, fold=0)
    second = datetime(2026, 11, 1, 1, 30, tzinfo=local, fold=1)
    inputs["as_of"] = second
    inputs["horizon_end"] = second + timedelta(minutes=30)
    inputs["market"] = replace(inputs["market"], evidence=Evidence("a" * 64, first))
    inputs["yes_book"] = replace(inputs["yes_book"], evidence=Evidence("b" * 64, first))
    with pytest.raises(FeasibilityInputError, match="YES_book:stale_or_future"):
        assess_buy_plan(**inputs)


def test_epoch_estimates_include_dilution_participation_and_zero_payment():
    inputs = _inputs()
    base = inputs["scenarios"][0]
    inputs["scenarios"] = (
        base,
        replace(base, label="half participation", participating_sample_fraction=D("0.5")),
        replace(base, label="cancelled", participating_sample_fraction=D("0")),
        replace(base, label="both remaining sizes below minimum", yes_remaining_size_fraction=D("0.5"), no_remaining_size_fraction=D("0.5")),
        replace(base, label="one side below minimum", yes_remaining_size_fraction=D("0.5")),
        replace(base, label="no other scored liquidity", other_makers_q_min=D("0"), other_makers_q_max=D("0")),
    )
    result = assess_buy_plan(**inputs, payout_model=_payout())
    estimates = result["scenarios"]
    assert estimates[0]["conditional_reward_amount_range"] == (D("1.5"), D("3"))
    assert estimates[1]["conditional_reward_amount_range"] == (D("0.75"), D("1.5"))
    assert estimates[2]["conditional_reward_amount_range"] == (D("0"), D("0"))
    assert estimates[3]["remaining_order_q"] == 0
    assert estimates[3]["conditional_reward_amount_range"] == (D("0"), D("0"))
    assert float(estimates[4]["remaining_order_q"]) == pytest.approx(12.8 / 3)
    assert float(estimates[4]["conditional_reward_amount_range"][1]) == pytest.approx(1.5)
    assert estimates[5]["conditional_sample_share_range"] == (D("1"), D("1"))
    assert estimates[5]["conditional_reward_amount_range"] == (D("6"), D("6"))
    assert result["no_payment_amount"] == 0
    assert result["paid_rewards"] is result["realized_pnl"] is None


def test_daily_rate_does_not_become_an_implicit_payout_prorate():
    inputs = _inputs()
    expected = assess_buy_plan(**inputs, payout_model=_payout())["scenarios"]
    inputs["campaigns"] = (replace(inputs["campaigns"][0], rate_per_day=D("999")),)
    assert assess_buy_plan(**inputs, payout_model=_payout())["scenarios"] == expected


def test_partial_remainder_above_reward_cutoff_keeps_score_below_submission_minimum():
    inputs = _inputs()
    inputs["market"] = replace(inputs["market"], order_min_size=D("15"))
    inputs["quotes"] = tuple(replace(quote, shares=D("40")) for quote in inputs["quotes"])
    inputs["capital"] = replace(inputs["capital"], order_cap=D("20"), condition_cap=D("50"))
    inputs["scenarios"] = (replace(inputs["scenarios"][0], yes_remaining_size_fraction=D("0.5"), no_remaining_size_fraction=D("0.5")),)
    result = assess_buy_plan(**inputs, payout_model=_payout())
    assert result["incentive_feasible"] is True
    assert result["scenarios"][0]["remaining_order_q"] == D("12.8")
    assert result["scenarios"][0]["conditional_reward_amount_range"] == (D("1.5"), D("3"))


def test_capital_acceptance_is_independent_of_ambient_decimal_context():
    inputs = _inputs()
    inputs["quotes"] = (replace(inputs["quotes"][0], shares=D("20.1")),)
    inputs["capital"] = replace(inputs["capital"], order_cap=D("9.80"))
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        result = assess_buy_plan(**inputs)
    assert result["order_notionals"] == (D("9.849"),)
    assert result["blockers"]["capital"] == ("capital:order_cap",)


@pytest.mark.parametrize("value", (D("1e-19"), D("1e19")))
def test_unsupported_precision_or_magnitude_is_rejected(value):
    inputs = _inputs()
    inputs["quotes"] = (replace(inputs["quotes"][0], shares=value),)
    with pytest.raises(FeasibilityInputError, match="quote_shares:precision_or_magnitude_unsupported"):
        assess_buy_plan(**inputs)


@pytest.mark.parametrize("changes,code", (
    ({"campaign_id": "different"}, "payout:campaign_identity_mismatch"),
    ({"reward_asset": COLLATERAL}, "payout:campaign_identity_mismatch"),
    ({"epoch_end": AS_OF + timedelta(minutes=30)}, "payout:interval_binding_invalid"),
    ({"plan_samples": 1441}, "payout:sample_counts_invalid"),
    ({"nonempty_epoch_samples": True}, "payout:sample_counts_invalid"),
))
def test_payout_model_requires_exact_campaign_interval_and_sample_binding(changes, code):
    with pytest.raises(FeasibilityInputError, match=code):
        assess_buy_plan(**_inputs(), payout_model=replace(_payout(), **changes))


@pytest.mark.parametrize("invalid", (D("NaN"), D("Infinity"), D("-1"), 0.49, True))
def test_prices_require_finite_explicit_nonnegative_decimals(invalid):
    inputs = _inputs()
    inputs["quotes"] = (replace(inputs["quotes"][0], price=invalid),)
    with pytest.raises(FeasibilityInputError):
        assess_buy_plan(**inputs)


def test_invalid_competitor_bounds_and_missing_scenarios_cannot_produce_estimates():
    inputs = _inputs()
    inputs["scenarios"] = ()
    with pytest.raises(FeasibilityInputError, match="scenarios:missing"):
        assess_buy_plan(**inputs)
    inputs["scenarios"] = (replace(_inputs()["scenarios"][0], other_makers_q_min=D("39")),)
    with pytest.raises(FeasibilityInputError, match="scenario:competitor_range_invalid"):
        assess_buy_plan(**inputs)
