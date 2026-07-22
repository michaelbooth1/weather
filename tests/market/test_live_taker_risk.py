from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from weather.market.live_taker_risk import (
    CanaryRiskPolicy,
    CanaryRiskState,
    CanaryStage,
    activation_caps,
    full_kelly_fraction,
    policy_hash,
    risk_basis,
    size_alpha_order,
    size_lifecycle_probe,
)


D = Decimal


def _healthy_state(**overrides):
    values = {
        "campaign_funding_usdc": D("75"),
        "reconciled_equity_usdc": D("75"),
        "available_cash_usdc": D("75"),
        "account_reconciled": True,
    }
    values.update(overrides)
    return CanaryRiskState(**values)


def _credible_alpha_state(**overrides):
    values = {
        "lifecycle_clean_reconciliations": 5,
        "live_settled_positions": 20,
        "independent_target_dates": 10,
        "after_cost_lcb_nonnegative": True,
    }
    values.update(overrides)
    return _healthy_state(**values)


def test_default_policy_is_frozen_and_cannot_be_widened():
    policy = CanaryRiskPolicy()

    assert activation_caps(policy) == {
        "lifetime_capital_ceiling_usdc": D("75.00"),
        "probe_order_max_loss_usdc": D("0.50"),
        "probe_daily_trade_count": 1,
        "probe_open_max_loss_usdc": D("1.00"),
        "alpha_order_max_loss_usdc": D("0.75"),
        "alpha_daily_new_risk_usdc": D("1.50"),
        "alpha_daily_trade_count": 2,
        "correlated_open_max_loss_usdc": D("1.50"),
        "total_open_max_loss_usdc": D("3.00"),
        "max_unsettled_positions": 4,
        "daily_realized_loss_halt_usdc": D("1.50"),
        "rolling_seven_day_drawdown_halt_usdc": D("3.75"),
        "permanent_drawdown_halt_usdc": D("15.00"),
        "permanent_equity_floor_usdc": D("60.00"),
    }
    with pytest.raises(FrozenInstanceError):
        policy.alpha_max_order_loss_usdc = D("1")
    with pytest.raises(ValueError, match="cannot widen"):
        CanaryRiskPolicy(alpha_max_order_loss_usdc=D("0.76"))
    with pytest.raises(ValueError, match="cannot widen"):
        CanaryRiskPolicy(consecutive_settled_loss_review_count=4)
    assert policy_hash(policy) == policy_hash(CanaryRiskPolicy())


def test_campaign_state_rejects_funding_above_seventy_five_dollars():
    with pytest.raises(ValueError, match=r"\$75 ceiling"):
        _healthy_state(campaign_funding_usdc=D("75.01"))


def test_risk_inputs_reject_binary_floats():
    with pytest.raises(ValueError, match="finite decimal"):
        _healthy_state(reconciled_equity_usdc=75.0)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("account_reconciled", "false"),
        ("after_cost_lcb_nonnegative", "false"),
        ("account_reconciled", 1),
        ("after_cost_lcb_nonnegative", 0),
    ),
)
def test_risk_state_rejects_non_boolean_gate_values(field, value):
    with pytest.raises(ValueError, match=rf"{field} must be a boolean"):
        _healthy_state(**{field: value})


def test_account_reconciliation_fails_closed_when_omitted():
    state = CanaryRiskState(
        campaign_funding_usdc=D("75"),
        reconciled_equity_usdc=D("75"),
    )

    decision = size_lifecycle_probe(
        limit_price=D("0.90"),
        venue_min_quantity=D("0.1"),
        quantity_step=D("0.01"),
        state=state,
    )

    assert decision.permitted is False
    assert decision.reason_code == "ACCOUNT_NOT_RECONCILED"


def test_risk_basis_escrows_three_quarters_of_positive_profit():
    assert risk_basis(D("82"), D("20")) == D("80")
    assert risk_basis(D("78"), D("20")) == D("78")
    assert risk_basis(D("70"), D("-5")) == D("70")
    assert risk_basis(D("75"), D("0"), campaign_funding_usdc=D("25")) == D("25")


def test_sizing_cannot_use_unfunded_equity():
    decision = size_lifecycle_probe(
        limit_price=D("0.90"),
        venue_min_quantity=D("0.10"),
        quantity_step=D("0.01"),
        state=_healthy_state(campaign_funding_usdc=D("0")),
    )

    assert decision.permitted is False
    assert decision.reason_code == "VENUE_MINIMUM_EXCEEDS_RISK_CAP"
    assert decision.risk_basis_usdc == D("0")


def test_full_kelly_is_decimal_and_floors_negative_edge():
    assert full_kelly_fraction(D("0.95"), D("0.90")) == D("0.5")
    assert full_kelly_fraction(D("0.89"), D("0.90")) == D("0")
    assert isinstance(full_kelly_fraction(D("0.95"), D("0.90")), Decimal)


def test_lifecycle_probe_floors_to_step_and_never_exceeds_fifty_cents():
    decision = size_lifecycle_probe(
        limit_price=D("0.90"),
        venue_min_quantity=D("0.10"),
        quantity_step=D("0.01"),
        state=_healthy_state(),
    )

    assert decision.permitted is True
    assert decision.stage is CanaryStage.LIFECYCLE
    assert decision.quantity == D("0.55")
    assert decision.worst_case_loss_usdc == D("0.4950")
    assert decision.worst_case_loss_usdc <= D("0.50")


def test_lifecycle_probe_does_not_round_up_to_venue_minimum():
    decision = size_lifecycle_probe(
        limit_price=D("0.90"),
        venue_min_quantity=D("1"),
        quantity_step=D("0.01"),
        state=_healthy_state(),
    )

    assert decision.permitted is False
    assert decision.reason_code == "VENUE_MINIMUM_EXCEEDS_RISK_CAP"
    assert decision.quantity == D("0")


def test_alpha_size_is_zero_before_live_skill_is_credible():
    decision = size_alpha_order(
        limit_price=D("0.90"),
        fair_value_lower_bound=D("0.99"),
        fee_per_share_usdc=D("0.005"),
        slippage_per_share_usdc=D("0.005"),
        spread=D("0.01"),
        minutes_to_close=D("30"),
        top_ask_quantity=D("100"),
        venue_min_quantity=D("0.1"),
        quantity_step=D("0.01"),
        state=_healthy_state(lifecycle_clean_reconciliations=5),
    )

    assert decision.permitted is False
    assert decision.reason_code == "LIVE_SKILL_NOT_CREDIBLE_KELLY_ZERO"
    assert decision.quantity == D("0")


def test_alpha_size_applies_all_in_loss_and_hard_order_cap():
    decision = size_alpha_order(
        limit_price=D("0.90"),
        fair_value_lower_bound=D("0.99"),
        fee_per_share_usdc=D("0.005"),
        slippage_per_share_usdc=D("0.005"),
        spread=D("0.01"),
        minutes_to_close=D("30"),
        top_ask_quantity=D("100"),
        venue_min_quantity=D("0.1"),
        quantity_step=D("0.01"),
        state=_credible_alpha_state(),
    )

    assert decision.permitted is True
    assert decision.stage is CanaryStage.ALPHA
    assert decision.limit_price == D("0.90")
    assert decision.all_in_loss_per_share_usdc == D("0.910")
    assert decision.after_cost_edge_per_share == D("0.080")
    assert decision.quantity == D("0.82")
    assert decision.worst_case_loss_usdc == D("0.74620")
    assert decision.worst_case_loss_usdc <= D("0.75")
    assert decision.limiting_control == "alpha_max_order_loss"


def test_above_ninety_percent_can_qualify_but_still_needs_after_cost_edge():
    common = {
        "limit_price": D("0.92"),
        "fee_per_share_usdc": D("0"),
        "slippage_per_share_usdc": D("0"),
        "spread": D("0.01"),
        "minutes_to_close": D("30"),
        "top_ask_quantity": D("100"),
        "venue_min_quantity": D("0.1"),
        "quantity_step": D("0.01"),
        "state": _credible_alpha_state(),
    }

    approved = size_alpha_order(fair_value_lower_bound=D("0.99"), **common)
    blocked = size_alpha_order(fair_value_lower_bound=D("0.93"), **common)

    assert approved.permitted is True
    assert blocked.permitted is False
    assert blocked.reason_code == "AFTER_COST_EDGE_TOO_SMALL"


def test_daily_realized_loss_halts_even_otherwise_credible_alpha():
    decision = size_alpha_order(
        limit_price=D("0.90"),
        fair_value_lower_bound=D("0.99"),
        fee_per_share_usdc=D("0"),
        slippage_per_share_usdc=D("0"),
        spread=D("0.01"),
        minutes_to_close=D("30"),
        top_ask_quantity=D("100"),
        venue_min_quantity=D("0.1"),
        quantity_step=D("0.01"),
        state=_credible_alpha_state(realized_loss_today_usdc=D("1.50")),
    )

    assert decision.permitted is False
    assert decision.reason_code == "DAILY_REALIZED_LOSS_HALT"
