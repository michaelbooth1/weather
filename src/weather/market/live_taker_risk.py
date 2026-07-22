"""Pure, fail-closed risk calculations for the $75 capital canary.

This module deliberately has no exchange, credential, filesystem, or clock
dependencies.  Monetary values and prices remain :class:`~decimal.Decimal`
throughout so an order gate never depends on binary floating-point rounding.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from enum import StrEnum
import hashlib
import json
from typing import Any


ZERO = Decimal("0")
ONE = Decimal("1")


def _decimal(value: Any, *, name: str) -> Decimal:
    if isinstance(value, (bool, float)):
        raise ValueError(f"{name} must be a finite decimal")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite decimal") from exc
    if not number.is_finite():
        raise ValueError(f"{name} must be a finite decimal")
    return number


def _nonnegative_decimal(value: Any, *, name: str) -> Decimal:
    number = _decimal(value, name=name)
    if number < ZERO:
        raise ValueError(f"{name} must be non-negative")
    return number


def _probability(value: Any, *, name: str, inclusive: bool = True) -> Decimal:
    number = _decimal(value, name=name)
    valid = ZERO <= number <= ONE if inclusive else ZERO < number < ONE
    if not valid:
        boundary = "[0, 1]" if inclusive else "(0, 1)"
        raise ValueError(f"{name} must be in {boundary}")
    return number


def _decimal_text(value: Decimal) -> str:
    """Return a stable non-exponent decimal representation."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= ZERO:
        raise ValueError("quantity_step must be positive")
    if value <= ZERO:
        return ZERO
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


class CanaryStage(StrEnum):
    """Risk stage; authority to enter either stage lives outside this module."""

    LIFECYCLE = "LIFECYCLE"
    ALPHA = "ALPHA"


@dataclass(frozen=True)
class CanaryRiskPolicy:
    """Hard policy limits from ``capital-canary-bot.md``.

    Instances are frozen.  Constructor overrides may only tighten a hard
    limit; attempts to widen the reviewed $75 envelope fail during creation.
    """

    campaign_capital_ceiling_usdc: Decimal = Decimal("75.00")

    lifecycle_max_order_loss_usdc: Decimal = Decimal("0.50")
    lifecycle_max_orders_per_day: int = 1
    lifecycle_max_unresolved_loss_usdc: Decimal = Decimal("1.00")
    lifecycle_clean_reconciliations_required: int = 5

    alpha_max_order_loss_usdc: Decimal = Decimal("0.75")
    alpha_max_event_loss_usdc: Decimal = Decimal("0.75")
    alpha_max_new_risk_per_day_usdc: Decimal = Decimal("1.50")
    alpha_max_trades_per_day: int = 2
    alpha_max_correlated_unresolved_loss_usdc: Decimal = Decimal("1.50")
    alpha_max_total_unresolved_loss_usdc: Decimal = Decimal("3.00")
    alpha_max_unsettled_positions: int = 4
    alpha_daily_realized_loss_halt_usdc: Decimal = Decimal("1.50")
    alpha_rolling_7d_drawdown_halt_usdc: Decimal = Decimal("3.75")
    permanent_canary_drawdown_halt_usdc: Decimal = Decimal("15.00")
    permanent_equity_floor_usdc: Decimal = Decimal("60.00")
    consecutive_settled_loss_review_count: int = 3

    fractional_kelly: Decimal = Decimal("0.10")
    max_risk_basis_fraction: Decimal = Decimal("0.01")
    positive_profit_risk_basis_share: Decimal = Decimal("0.25")
    min_live_settled_positions: int = 20
    min_independent_target_dates: int = 10

    min_limit_price: Decimal = Decimal("0.85")
    max_limit_price: Decimal = Decimal("0.97")
    min_after_cost_edge_per_share: Decimal = Decimal("0.02")
    min_after_cost_roi: Decimal = Decimal("0.02")
    max_spread: Decimal = Decimal("0.01")
    max_top_ask_fraction: Decimal = Decimal("0.10")
    min_minutes_to_close: Decimal = Decimal("10")

    def __post_init__(self) -> None:
        decimal_names = {
            item.name for item in fields(self) if item.type is Decimal
        }
        # ``from __future__ import annotations`` can leave string annotations.
        decimal_names.update(
            item.name for item in fields(self) if item.type == "Decimal"
        )
        for name in decimal_names:
            object.__setattr__(
                self,
                name,
                _nonnegative_decimal(getattr(self, name), name=name),
            )

        integer_names = {
            "lifecycle_max_orders_per_day",
            "lifecycle_clean_reconciliations_required",
            "alpha_max_trades_per_day",
            "alpha_max_unsettled_positions",
            "consecutive_settled_loss_review_count",
            "min_live_settled_positions",
            "min_independent_target_dates",
        }
        for name in integer_names:
            value = getattr(self, name)
            if isinstance(value, bool) or int(value) != value or int(value) <= 0:
                raise ValueError(f"{name} must be a positive integer")
            object.__setattr__(self, name, int(value))

        maximums = {
            "campaign_capital_ceiling_usdc": Decimal("75.00"),
            "lifecycle_max_order_loss_usdc": Decimal("0.50"),
            "lifecycle_max_orders_per_day": 1,
            "lifecycle_max_unresolved_loss_usdc": Decimal("1.00"),
            "alpha_max_order_loss_usdc": Decimal("0.75"),
            "alpha_max_event_loss_usdc": Decimal("0.75"),
            "alpha_max_new_risk_per_day_usdc": Decimal("1.50"),
            "alpha_max_trades_per_day": 2,
            "alpha_max_correlated_unresolved_loss_usdc": Decimal("1.50"),
            "alpha_max_total_unresolved_loss_usdc": Decimal("3.00"),
            "alpha_max_unsettled_positions": 4,
            "alpha_daily_realized_loss_halt_usdc": Decimal("1.50"),
            "alpha_rolling_7d_drawdown_halt_usdc": Decimal("3.75"),
            "permanent_canary_drawdown_halt_usdc": Decimal("15.00"),
            "fractional_kelly": Decimal("0.10"),
            "max_risk_basis_fraction": Decimal("0.01"),
            "positive_profit_risk_basis_share": Decimal("0.25"),
            "consecutive_settled_loss_review_count": 3,
            "max_limit_price": Decimal("0.97"),
            "max_spread": Decimal("0.01"),
            "max_top_ask_fraction": Decimal("0.10"),
        }
        for name, hard_maximum in maximums.items():
            if getattr(self, name) > hard_maximum:
                raise ValueError(f"{name} cannot widen the reviewed canary policy")

        minimums = {
            "lifecycle_clean_reconciliations_required": 5,
            "permanent_equity_floor_usdc": Decimal("60.00"),
            "min_live_settled_positions": 20,
            "min_independent_target_dates": 10,
            "min_limit_price": Decimal("0.85"),
            "min_after_cost_edge_per_share": Decimal("0.02"),
            "min_after_cost_roi": Decimal("0.02"),
            "min_minutes_to_close": Decimal("10"),
        }
        for name, hard_minimum in minimums.items():
            if getattr(self, name) < hard_minimum:
                raise ValueError(f"{name} cannot widen the reviewed canary policy")

        if self.min_limit_price > self.max_limit_price:
            raise ValueError("min_limit_price cannot exceed max_limit_price")
        if self.permanent_equity_floor_usdc > self.campaign_capital_ceiling_usdc:
            raise ValueError("permanent_equity_floor_usdc cannot exceed the capital ceiling")


@dataclass(frozen=True)
class CanaryRiskState:
    """Reconciled inputs needed by the pure sizing gates.

    Loss and drawdown fields are positive magnitudes.  Settled net profit is
    signed.  ``available_cash_usdc=None`` means the risk code must derive a
    conservative bound from equity and unresolved loss.
    """

    campaign_funding_usdc: Decimal
    reconciled_equity_usdc: Decimal
    cumulative_settled_net_profit_usdc: Decimal = ZERO
    available_cash_usdc: Decimal | None = None
    unresolved_worst_case_loss_usdc: Decimal = ZERO
    event_unresolved_worst_case_loss_usdc: Decimal = ZERO
    correlated_regime_unresolved_loss_usdc: Decimal = ZERO
    new_risk_today_usdc: Decimal = ZERO
    realized_loss_today_usdc: Decimal = ZERO
    rolling_7d_drawdown_usdc: Decimal = ZERO
    campaign_drawdown_usdc: Decimal = ZERO
    trades_today: int = 0
    unsettled_positions: int = 0
    consecutive_settled_losses: int = 0
    lifecycle_clean_reconciliations: int = 0
    live_settled_positions: int = 0
    independent_target_dates: int = 0
    after_cost_lcb_nonnegative: bool = False
    account_reconciled: bool = False

    def __post_init__(self) -> None:
        nonnegative_names = {
            "campaign_funding_usdc",
            "reconciled_equity_usdc",
            "unresolved_worst_case_loss_usdc",
            "event_unresolved_worst_case_loss_usdc",
            "correlated_regime_unresolved_loss_usdc",
            "new_risk_today_usdc",
            "realized_loss_today_usdc",
            "rolling_7d_drawdown_usdc",
            "campaign_drawdown_usdc",
        }
        for name in nonnegative_names:
            object.__setattr__(
                self,
                name,
                _nonnegative_decimal(getattr(self, name), name=name),
            )
        object.__setattr__(
            self,
            "cumulative_settled_net_profit_usdc",
            _decimal(
                self.cumulative_settled_net_profit_usdc,
                name="cumulative_settled_net_profit_usdc",
            ),
        )
        if self.available_cash_usdc is not None:
            object.__setattr__(
                self,
                "available_cash_usdc",
                _nonnegative_decimal(self.available_cash_usdc, name="available_cash_usdc"),
            )
        for name in (
            "trades_today",
            "unsettled_positions",
            "consecutive_settled_losses",
            "lifecycle_clean_reconciliations",
            "live_settled_positions",
            "independent_target_dates",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or int(value) != value or int(value) < 0:
                raise ValueError(f"{name} must be a non-negative integer")
            object.__setattr__(self, name, int(value))
        for name in ("after_cost_lcb_nonnegative", "account_reconciled"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a boolean")
        if self.campaign_funding_usdc > Decimal("75.00"):
            raise ValueError("campaign funding exceeds the immutable $75 ceiling")


@dataclass(frozen=True)
class SizingDecision:
    permitted: bool
    reason_code: str
    stage: CanaryStage
    quantity: Decimal = ZERO
    limit_price: Decimal = ZERO
    all_in_loss_per_share_usdc: Decimal = ZERO
    worst_case_loss_usdc: Decimal = ZERO
    risk_basis_usdc: Decimal = ZERO
    full_kelly_fraction: Decimal = ZERO
    applied_kelly_fraction: Decimal = ZERO
    after_cost_edge_per_share: Decimal | None = None
    after_cost_roi: Decimal | None = None
    limiting_control: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in asdict(self).items():
            if isinstance(value, Decimal):
                result[key] = _decimal_text(value)
            elif isinstance(value, CanaryStage):
                result[key] = value.value
            else:
                result[key] = value
        return result


def policy_payload(policy: CanaryRiskPolicy | None = None) -> dict[str, Any]:
    """Return the policy in deterministic, JSON-safe form."""
    policy = policy or CanaryRiskPolicy()
    return {
        field.name: (
            _decimal_text(getattr(policy, field.name))
            if isinstance(getattr(policy, field.name), Decimal)
            else getattr(policy, field.name)
        )
        for field in fields(policy)
    }


def policy_hash(policy: CanaryRiskPolicy | None = None) -> str:
    payload = json.dumps(policy_payload(policy), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def activation_caps(policy: CanaryRiskPolicy | None = None) -> dict[str, Decimal | int]:
    """Return the canonical activation-facing hard-cap mapping.

    The names are part of the reviewed activation contract.  Keeping this
    projection here prevents controllers from restating the limits with floats.
    """
    policy = policy or CanaryRiskPolicy()
    return {
        "lifetime_capital_ceiling_usdc": policy.campaign_capital_ceiling_usdc,
        "probe_order_max_loss_usdc": policy.lifecycle_max_order_loss_usdc,
        "probe_daily_trade_count": policy.lifecycle_max_orders_per_day,
        "probe_open_max_loss_usdc": policy.lifecycle_max_unresolved_loss_usdc,
        "alpha_order_max_loss_usdc": policy.alpha_max_order_loss_usdc,
        "alpha_daily_new_risk_usdc": policy.alpha_max_new_risk_per_day_usdc,
        "alpha_daily_trade_count": policy.alpha_max_trades_per_day,
        "correlated_open_max_loss_usdc": (
            policy.alpha_max_correlated_unresolved_loss_usdc
        ),
        "total_open_max_loss_usdc": policy.alpha_max_total_unresolved_loss_usdc,
        "max_unsettled_positions": policy.alpha_max_unsettled_positions,
        "daily_realized_loss_halt_usdc": (
            policy.alpha_daily_realized_loss_halt_usdc
        ),
        "rolling_seven_day_drawdown_halt_usdc": (
            policy.alpha_rolling_7d_drawdown_halt_usdc
        ),
        "permanent_drawdown_halt_usdc": (
            policy.permanent_canary_drawdown_halt_usdc
        ),
        "permanent_equity_floor_usdc": policy.permanent_equity_floor_usdc,
    }


def risk_basis(
    reconciled_equity_usdc: Any,
    cumulative_settled_net_profit_usdc: Any,
    *,
    campaign_funding_usdc: Any | None = None,
    policy: CanaryRiskPolicy | None = None,
) -> Decimal:
    """Apply the reviewed 25% profit escrow rule to the sizing basis."""
    policy = policy or CanaryRiskPolicy()
    equity = _nonnegative_decimal(reconciled_equity_usdc, name="reconciled_equity_usdc")
    profit = _decimal(
        cumulative_settled_net_profit_usdc,
        name="cumulative_settled_net_profit_usdc",
    )
    funding = (
        policy.campaign_capital_ceiling_usdc
        if campaign_funding_usdc is None
        else min(
            policy.campaign_capital_ceiling_usdc,
            _nonnegative_decimal(
                campaign_funding_usdc,
                name="campaign_funding_usdc",
            ),
        )
    )
    expanded_cap = (
        funding
        + policy.positive_profit_risk_basis_share * max(ZERO, profit)
    )
    return min(equity, expanded_cap)


def full_kelly_fraction(fair_probability: Any, all_in_price: Any) -> Decimal:
    """Full Kelly fraction for a long binary share, floored at zero."""
    fair = _probability(fair_probability, name="fair_probability")
    price = _probability(all_in_price, name="all_in_price", inclusive=False)
    return max(ZERO, (fair - price) / (ONE - price))


def alpha_skill_is_credible(
    state: CanaryRiskState,
    *,
    policy: CanaryRiskPolicy | None = None,
) -> bool:
    policy = policy or CanaryRiskPolicy()
    return bool(
        state.live_settled_positions >= policy.min_live_settled_positions
        and state.independent_target_dates >= policy.min_independent_target_dates
        and state.after_cost_lcb_nonnegative
    )


def risk_halt_reasons(
    state: CanaryRiskState,
    *,
    policy: CanaryRiskPolicy | None = None,
) -> tuple[str, ...]:
    policy = policy or CanaryRiskPolicy()
    reasons: list[str] = []
    if not state.account_reconciled:
        reasons.append("ACCOUNT_NOT_RECONCILED")
    if state.realized_loss_today_usdc >= policy.alpha_daily_realized_loss_halt_usdc:
        reasons.append("DAILY_REALIZED_LOSS_HALT")
    if state.rolling_7d_drawdown_usdc >= policy.alpha_rolling_7d_drawdown_halt_usdc:
        reasons.append("ROLLING_7D_DRAWDOWN_HALT")
    if state.campaign_drawdown_usdc >= policy.permanent_canary_drawdown_halt_usdc:
        reasons.append("PERMANENT_CANARY_DRAWDOWN_HALT")
    if state.reconciled_equity_usdc <= policy.permanent_equity_floor_usdc:
        reasons.append("PERMANENT_EQUITY_FLOOR_HALT")
    if state.consecutive_settled_losses >= policy.consecutive_settled_loss_review_count:
        reasons.append("CONSECUTIVE_LOSS_REVIEW_REQUIRED")
    if state.unresolved_worst_case_loss_usdc > policy.alpha_max_total_unresolved_loss_usdc:
        reasons.append("UNRESOLVED_RISK_ALREADY_BREACHED")
    if state.unsettled_positions > policy.alpha_max_unsettled_positions:
        reasons.append("UNSETTLED_POSITION_COUNT_ALREADY_BREACHED")
    return tuple(reasons)


def _available_cash(state: CanaryRiskState) -> Decimal:
    if state.available_cash_usdc is not None:
        return state.available_cash_usdc
    return max(
        ZERO,
        state.reconciled_equity_usdc - state.unresolved_worst_case_loss_usdc,
    )


def _blocked(
    reason_code: str,
    *,
    stage: CanaryStage,
    limit_price: Decimal = ZERO,
    all_in_loss_per_share_usdc: Decimal = ZERO,
    risk_basis_usdc: Decimal = ZERO,
    full_kelly: Decimal = ZERO,
    edge: Decimal | None = None,
    roi: Decimal | None = None,
) -> SizingDecision:
    return SizingDecision(
        permitted=False,
        reason_code=reason_code,
        stage=stage,
        limit_price=limit_price,
        all_in_loss_per_share_usdc=all_in_loss_per_share_usdc,
        risk_basis_usdc=risk_basis_usdc,
        full_kelly_fraction=full_kelly,
        after_cost_edge_per_share=edge,
        after_cost_roi=roi,
    )


def _cost_inputs(
    limit_price: Any,
    fee_per_share_usdc: Any,
    slippage_per_share_usdc: Any,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    price = _probability(limit_price, name="limit_price", inclusive=False)
    fee = _nonnegative_decimal(fee_per_share_usdc, name="fee_per_share_usdc")
    slippage = _nonnegative_decimal(
        slippage_per_share_usdc,
        name="slippage_per_share_usdc",
    )
    return price, fee, slippage, price + fee + slippage


def _quantity_inputs(venue_min_quantity: Any, quantity_step: Any) -> tuple[Decimal, Decimal]:
    minimum = _nonnegative_decimal(venue_min_quantity, name="venue_min_quantity")
    step = _nonnegative_decimal(quantity_step, name="quantity_step")
    if minimum <= ZERO:
        raise ValueError("venue_min_quantity must be positive")
    if step <= ZERO:
        raise ValueError("quantity_step must be positive")
    return minimum, step


def size_lifecycle_probe(
    *,
    limit_price: Any,
    venue_min_quantity: Any,
    quantity_step: Any,
    state: CanaryRiskState,
    fee_per_share_usdc: Any = ZERO,
    slippage_per_share_usdc: Any = ZERO,
    policy: CanaryRiskPolicy | None = None,
) -> SizingDecision:
    """Size at most one lifecycle probe without ever rounding up."""
    policy = policy or CanaryRiskPolicy()
    price, _fee, _slippage, all_in_loss = _cost_inputs(
        limit_price,
        fee_per_share_usdc,
        slippage_per_share_usdc,
    )
    minimum, step = _quantity_inputs(venue_min_quantity, quantity_step)
    basis = risk_basis(
        state.reconciled_equity_usdc,
        state.cumulative_settled_net_profit_usdc,
        campaign_funding_usdc=state.campaign_funding_usdc,
        policy=policy,
    )
    if not state.account_reconciled:
        return _blocked(
            "ACCOUNT_NOT_RECONCILED",
            stage=CanaryStage.LIFECYCLE,
            limit_price=price,
            all_in_loss_per_share_usdc=all_in_loss,
            risk_basis_usdc=basis,
        )
    halts = risk_halt_reasons(state, policy=policy)
    if halts:
        return _blocked(
            halts[0],
            stage=CanaryStage.LIFECYCLE,
            limit_price=price,
            all_in_loss_per_share_usdc=all_in_loss,
            risk_basis_usdc=basis,
        )
    if state.campaign_funding_usdc > policy.campaign_capital_ceiling_usdc:
        return _blocked("CAMPAIGN_CAPITAL_CEILING_BREACHED", stage=CanaryStage.LIFECYCLE)
    if state.trades_today >= policy.lifecycle_max_orders_per_day:
        return _blocked("LIFECYCLE_DAILY_ORDER_LIMIT", stage=CanaryStage.LIFECYCLE)
    if state.unsettled_positions >= 1:
        return _blocked("LIFECYCLE_UNRESOLVED_POSITION_LIMIT", stage=CanaryStage.LIFECYCLE)
    if not policy.min_limit_price <= price <= policy.max_limit_price:
        return _blocked(
            "LIMIT_PRICE_OUTSIDE_APPROVED_LANE",
            stage=CanaryStage.LIFECYCLE,
            limit_price=price,
            all_in_loss_per_share_usdc=all_in_loss,
            risk_basis_usdc=basis,
        )
    if all_in_loss >= ONE:
        return _blocked(
            "ALL_IN_LOSS_PER_SHARE_INVALID",
            stage=CanaryStage.LIFECYCLE,
            limit_price=price,
            all_in_loss_per_share_usdc=all_in_loss,
            risk_basis_usdc=basis,
        )

    caps = {
        "lifecycle_max_order_loss": policy.lifecycle_max_order_loss_usdc,
        "lifecycle_max_unresolved_loss": max(
            ZERO,
            policy.lifecycle_max_unresolved_loss_usdc
            - state.unresolved_worst_case_loss_usdc,
        ),
        "available_cash": _available_cash(state),
        "risk_basis": basis,
    }
    limiting_control, risk_cap = min(caps.items(), key=lambda item: item[1])
    quantity = _floor_to_step(risk_cap / all_in_loss, step)
    if quantity < minimum:
        return _blocked(
            "VENUE_MINIMUM_EXCEEDS_RISK_CAP",
            stage=CanaryStage.LIFECYCLE,
            limit_price=price,
            all_in_loss_per_share_usdc=all_in_loss,
            risk_basis_usdc=basis,
        )
    worst_case_loss = quantity * all_in_loss
    return SizingDecision(
        permitted=True,
        reason_code="LIFECYCLE_PROBE_SIZE_APPROVED",
        stage=CanaryStage.LIFECYCLE,
        quantity=quantity,
        limit_price=price,
        all_in_loss_per_share_usdc=all_in_loss,
        worst_case_loss_usdc=worst_case_loss,
        risk_basis_usdc=basis,
        limiting_control=limiting_control,
    )


def size_alpha_order(
    *,
    limit_price: Any,
    fair_value_lower_bound: Any,
    fee_per_share_usdc: Any,
    slippage_per_share_usdc: Any,
    spread: Any,
    minutes_to_close: Any,
    top_ask_quantity: Any,
    venue_min_quantity: Any,
    quantity_step: Any,
    state: CanaryRiskState,
    policy: CanaryRiskPolicy | None = None,
) -> SizingDecision:
    """Apply evidence, microstructure, Kelly, and every hard alpha cap."""
    policy = policy or CanaryRiskPolicy()
    price, _fee, _slippage, all_in_loss = _cost_inputs(
        limit_price,
        fee_per_share_usdc,
        slippage_per_share_usdc,
    )
    fair = _probability(fair_value_lower_bound, name="fair_value_lower_bound")
    spread_value = _nonnegative_decimal(spread, name="spread")
    close_minutes = _nonnegative_decimal(minutes_to_close, name="minutes_to_close")
    top_quantity = _nonnegative_decimal(top_ask_quantity, name="top_ask_quantity")
    minimum, step = _quantity_inputs(venue_min_quantity, quantity_step)
    basis = risk_basis(
        state.reconciled_equity_usdc,
        state.cumulative_settled_net_profit_usdc,
        campaign_funding_usdc=state.campaign_funding_usdc,
        policy=policy,
    )

    if state.lifecycle_clean_reconciliations < policy.lifecycle_clean_reconciliations_required:
        return _blocked("LIFECYCLE_EVIDENCE_INCOMPLETE", stage=CanaryStage.ALPHA)
    if not alpha_skill_is_credible(state, policy=policy):
        return _blocked(
            "LIVE_SKILL_NOT_CREDIBLE_KELLY_ZERO",
            stage=CanaryStage.ALPHA,
            limit_price=price,
            all_in_loss_per_share_usdc=all_in_loss,
            risk_basis_usdc=basis,
        )
    halts = risk_halt_reasons(state, policy=policy)
    if halts:
        return _blocked(
            halts[0],
            stage=CanaryStage.ALPHA,
            limit_price=price,
            all_in_loss_per_share_usdc=all_in_loss,
            risk_basis_usdc=basis,
        )
    if state.trades_today >= policy.alpha_max_trades_per_day:
        return _blocked("ALPHA_DAILY_TRADE_LIMIT", stage=CanaryStage.ALPHA)
    if state.unsettled_positions >= policy.alpha_max_unsettled_positions:
        return _blocked("ALPHA_POSITION_LIMIT", stage=CanaryStage.ALPHA)
    if not policy.min_limit_price <= price <= policy.max_limit_price:
        return _blocked(
            "LIMIT_PRICE_OUTSIDE_APPROVED_LANE",
            stage=CanaryStage.ALPHA,
            limit_price=price,
            all_in_loss_per_share_usdc=all_in_loss,
            risk_basis_usdc=basis,
        )
    if all_in_loss >= ONE:
        return _blocked(
            "ALL_IN_LOSS_PER_SHARE_INVALID",
            stage=CanaryStage.ALPHA,
            limit_price=price,
            all_in_loss_per_share_usdc=all_in_loss,
            risk_basis_usdc=basis,
        )
    if spread_value > policy.max_spread:
        return _blocked("SPREAD_TOO_WIDE", stage=CanaryStage.ALPHA)
    if close_minutes < policy.min_minutes_to_close:
        return _blocked("TOO_CLOSE_TO_MARKET_CLOSE", stage=CanaryStage.ALPHA)

    edge = fair - all_in_loss
    roi = edge / all_in_loss
    kelly = full_kelly_fraction(fair, all_in_loss)
    if edge < policy.min_after_cost_edge_per_share:
        return _blocked(
            "AFTER_COST_EDGE_TOO_SMALL",
            stage=CanaryStage.ALPHA,
            limit_price=price,
            all_in_loss_per_share_usdc=all_in_loss,
            risk_basis_usdc=basis,
            full_kelly=kelly,
            edge=edge,
            roi=roi,
        )
    if roi < policy.min_after_cost_roi:
        return _blocked(
            "AFTER_COST_ROI_TOO_SMALL",
            stage=CanaryStage.ALPHA,
            limit_price=price,
            all_in_loss_per_share_usdc=all_in_loss,
            risk_basis_usdc=basis,
            full_kelly=kelly,
            edge=edge,
            roi=roi,
        )

    applied_kelly = kelly * policy.fractional_kelly
    caps = {
        "alpha_max_order_loss": policy.alpha_max_order_loss_usdc,
        "alpha_max_event_loss": max(
            ZERO,
            policy.alpha_max_event_loss_usdc
            - state.event_unresolved_worst_case_loss_usdc,
        ),
        "alpha_max_new_risk_per_day": max(
            ZERO,
            policy.alpha_max_new_risk_per_day_usdc - state.new_risk_today_usdc,
        ),
        "alpha_max_correlated_unresolved_loss": max(
            ZERO,
            policy.alpha_max_correlated_unresolved_loss_usdc
            - state.correlated_regime_unresolved_loss_usdc,
        ),
        "alpha_max_total_unresolved_loss": max(
            ZERO,
            policy.alpha_max_total_unresolved_loss_usdc
            - state.unresolved_worst_case_loss_usdc,
        ),
        "fractional_kelly": basis * applied_kelly,
        "one_percent_risk_basis": basis * policy.max_risk_basis_fraction,
        "available_cash": _available_cash(state),
    }
    limiting_control, risk_cap = min(caps.items(), key=lambda item: item[1])
    depth_quantity_cap = _floor_to_step(
        top_quantity * policy.max_top_ask_fraction,
        step,
    )
    quantity = min(
        _floor_to_step(risk_cap / all_in_loss, step),
        depth_quantity_cap,
    )
    if quantity < minimum:
        return _blocked(
            "VENUE_MINIMUM_EXCEEDS_RISK_CAP",
            stage=CanaryStage.ALPHA,
            limit_price=price,
            all_in_loss_per_share_usdc=all_in_loss,
            risk_basis_usdc=basis,
            full_kelly=kelly,
            edge=edge,
            roi=roi,
        )
    if quantity == depth_quantity_cap and quantity * all_in_loss < risk_cap:
        limiting_control = "top_ask_depth_fraction"
    worst_case_loss = quantity * all_in_loss
    return SizingDecision(
        permitted=True,
        reason_code="ALPHA_ORDER_SIZE_APPROVED",
        stage=CanaryStage.ALPHA,
        quantity=quantity,
        limit_price=price,
        all_in_loss_per_share_usdc=all_in_loss,
        worst_case_loss_usdc=worst_case_loss,
        risk_basis_usdc=basis,
        full_kelly_fraction=kelly,
        applied_kelly_fraction=applied_kelly,
        after_cost_edge_per_share=edge,
        after_cost_roi=roi,
        limiting_control=limiting_control,
    )


__all__ = [
    "CanaryRiskPolicy",
    "CanaryRiskState",
    "CanaryStage",
    "SizingDecision",
    "activation_caps",
    "alpha_skill_is_credible",
    "full_kelly_fraction",
    "policy_hash",
    "policy_payload",
    "risk_basis",
    "risk_halt_reasons",
    "size_alpha_order",
    "size_lifecycle_probe",
]
