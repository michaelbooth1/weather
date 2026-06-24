"""Market-making risk and sizing primitives.

Pure calculations only: no exchange client, wallet, or order side effects.
"""
from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import dataclass, field


SIDES = {"YES", "NO", "YES_BID", "NO_BID", "YES_ASK"}
NEGATIVE_RISK_SIMULATION_SCHEMA_VERSION = "mm_negative_risk_simulation_v0.1"
CORRELATED_REGIME_EXPOSURE_SCHEMA_VERSION = "correlated_regime_exposure_v0.1"
DEFAULT_CORRELATED_MARKET_GROUPS = {
    "toronto": "great_lakes_northeast",
    "nyc": "great_lakes_northeast",
    "atlanta": "southeast",
    "miami": "southeast",
    "austin": "texas_southern_plains",
    "dallas": "texas_southern_plains",
    "houston": "texas_southern_plains",
    "chicago": "midwest",
    "denver": "rockies_high_plains",
    "los-angeles": "west_coast",
    "san-francisco": "west_coast",
    "seattle": "pacific_northwest",
}


def _float(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _first_present(row, *keys):
    for key in keys:
        value = (row or {}).get(key)
        if value not in (None, ""):
            return value
    return None


def _clean_token(value, default="unknown"):
    text = str(value or "").strip().lower().replace(" ", "_")
    return text or default


def _parse_market_group_overrides(overrides):
    if not overrides:
        return {}
    if isinstance(overrides, dict):
        return {
            _clean_token(key): _clean_token(value)
            for key, value in overrides.items()
            if key not in (None, "") and value not in (None, "")
        }
    text = str(overrides).strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, dict):
        return _parse_market_group_overrides(parsed)
    result = {}
    for chunk in text.replace(";", ",").split(","):
        if ":" not in chunk:
            continue
        market_id, group = chunk.split(":", 1)
        if market_id.strip() and group.strip():
            result[_clean_token(market_id)] = _clean_token(group)
    return result


def _target_day(row):
    target = _first_present(row, "target_date", "market_date", "date")
    if target:
        return str(target)[:10]
    timestamp = _first_present(row, "captured_at_utc", "generated_at_utc", "quote_time_utc", "fill_time_utc")
    return str(timestamp)[:10] if timestamp else "unknown_date"


def _row_market_group(row, overrides=None):
    market_id = _clean_token(_first_present(row, "market_id"), default="unknown_market")
    override_groups = _parse_market_group_overrides(overrides)
    return override_groups.get(market_id) or DEFAULT_CORRELATED_MARKET_GROUPS.get(market_id) or market_id


def _label_numbers(row):
    numbers = []
    text = str((row or {}).get("range_label") or "")
    current = ""
    for char in text:
        if char.isdigit() or (char == "-" and not current):
            current += char
        elif current:
            try:
                numbers.append(float(current))
            except ValueError:
                pass
            current = ""
    if current:
        try:
            numbers.append(float(current))
        except ValueError:
            pass
    return numbers


def _band_midpoint(row):
    value = _float(_first_present(row, "bin_value", "bin_value_c", "winning_band_value"), None)
    value_hi = _float(_first_present(row, "bin_value_hi", "winning_band_value_hi"), None)
    if value is None:
        numbers = _label_numbers(row)
        if numbers:
            value = numbers[0]
            value_hi = numbers[-1]
    if value is None:
        return None
    kind = str(_first_present(row, "bin_kind", "winning_band_kind") or "eq").lower()
    if kind in {"lte", "below", "under", "gte", "above"}:
        return value
    if value_hi is None:
        value_hi = value
    return (value + value_hi) / 2.0


def _reference_temperature(row):
    reference = _float(_first_present(
        row,
        "correlated_regime_reference_temperature",
        "market_modal_band_hi",
        "settlement_current_high",
        "raw_current_high_bucket",
        "raw_current_high",
    ), None)
    return reference


def _base_temperature_direction(row):
    explicit = _clean_token(_first_present(
        row,
        "correlated_regime_direction",
        "regime_direction",
        "temperature_regime_direction",
    ), default="")
    if explicit in {"warm", "hot", "above", "upside"}:
        return 1
    if explicit in {"cool", "cold", "below", "downside"}:
        return -1
    if explicit in {"center", "neutral", "modal"}:
        return 0
    kind = str(_first_present(row, "bin_kind", "winning_band_kind") or "").lower()
    if kind in {"gte", "above"}:
        return 1
    if kind in {"lte", "below", "under"}:
        return -1
    midpoint = _band_midpoint(row)
    reference = _reference_temperature(row)
    if midpoint is None or reference is None:
        return None
    tolerance = max(0.0, _float((row or {}).get("correlated_regime_center_tolerance"), 0.5))
    if midpoint > reference + tolerance:
        return 1
    if midpoint < reference - tolerance:
        return -1
    return 0


def _side_direction_multiplier(side):
    text = str(side or "").strip().upper()
    if text in {"NO", "NO_BUY", "NO_BID", "YES_ASK"}:
        return -1
    return 1


def correlated_regime_direction(row, side=None):
    """Side-adjusted weather-regime direction for same-day joint-risk grouping."""
    base = _base_temperature_direction(row)
    if base is None:
        return "unknown_direction"
    adjusted = base * _side_direction_multiplier(side or _first_present(row, "side", "order_side"))
    if adjusted > 0:
        return "warm"
    if adjusted < 0:
        return "cool"
    return "center"


def correlated_regime_group_key(row, market_group_overrides=None, side=None):
    """Stable target-day/market-cluster/direction key for correlated exposure caps."""
    if (row or {}).get("correlated_regime_group_key"):
        return str(row.get("correlated_regime_group_key"))
    return "|".join([
        _target_day(row),
        _row_market_group(row, market_group_overrides),
        correlated_regime_direction(row, side=side),
    ])


def correlated_exposure_state(
    row,
    *,
    current_notional_usdc=0.0,
    candidate_notional_usdc=0.0,
    current_joint_loss_usdc=None,
    candidate_joint_loss_usdc=None,
    max_notional_usdc=0.0,
    max_joint_loss_usdc=0.0,
    market_group_overrides=None,
    side=None,
):
    """Return group-level correlated exposure before/after a candidate fill/quote."""
    key = correlated_regime_group_key(row, market_group_overrides=market_group_overrides, side=side)
    direction = correlated_regime_direction(row, side=side)
    direction_sign = {"warm": 1.0, "cool": -1.0}.get(direction, 0.0)
    before = max(0.0, _float(current_notional_usdc))
    candidate = max(0.0, _float(candidate_notional_usdc))
    loss_before = before if current_joint_loss_usdc is None else max(0.0, _float(current_joint_loss_usdc))
    loss_candidate = candidate if candidate_joint_loss_usdc is None else max(0.0, _float(candidate_joint_loss_usdc))
    after = before + candidate
    loss_after = loss_before + loss_candidate
    notional_cap = max(0.0, _float(max_notional_usdc))
    loss_cap = max(0.0, _float(max_joint_loss_usdc))
    notional_remaining = None if notional_cap <= 0 else max(0.0, notional_cap - before)
    loss_remaining = None if loss_cap <= 0 else max(0.0, loss_cap - loss_before)
    notional_breach = notional_cap > 0 and after > notional_cap + 1e-9
    loss_breach = loss_cap > 0 and loss_after > loss_cap + 1e-9
    return {
        "correlated_regime_schema_version": CORRELATED_REGIME_EXPOSURE_SCHEMA_VERSION,
        "correlated_regime_group_key": key,
        "correlated_regime_direction": direction,
        "correlated_regime_market_group": _row_market_group(row, market_group_overrides),
        "correlated_regime_notional_before_usdc": before,
        "correlated_regime_notional_after_usdc": after,
        "correlated_regime_signed_notional_before_usdc": before * direction_sign,
        "correlated_regime_signed_notional_after_usdc": after * direction_sign,
        "correlated_regime_joint_stress_loss_before_usdc": loss_before,
        "correlated_regime_joint_stress_loss_after_usdc": loss_after,
        "correlated_regime_notional_remaining_usdc": notional_remaining,
        "correlated_regime_joint_loss_remaining_usdc": loss_remaining,
        "correlated_regime_notional_cap_usdc": notional_cap,
        "correlated_regime_joint_loss_cap_usdc": loss_cap,
        "correlated_regime_cap_breached": bool(notional_breach or loss_breach),
        "correlated_regime_cap_reason": (
            "correlated_regime_joint_loss_cap"
            if loss_breach
            else "correlated_regime_notional_cap"
            if notional_breach
            else ""
        ),
    }


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, _float(value)))


def normalize_probabilities(probabilities, outcomes):
    raw = {outcome: max(0.0, _float((probabilities or {}).get(outcome))) for outcome in outcomes}
    total = sum(raw.values())
    if total <= 0:
        return {outcome: 1.0 / len(outcomes) for outcome in outcomes} if outcomes else {}
    return {outcome: value / total for outcome, value in raw.items()}


@dataclass(frozen=True)
class InventoryLeg:
    outcome: str
    side: str
    shares: float
    avg_price: float
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        side = str(self.side).upper()
        if side not in SIDES:
            raise ValueError(f"unsupported inventory side: {self.side!r}")
        if _float(self.shares) < 0:
            raise ValueError("shares must be non-negative; use NO legs for hedges")
        if not 0.0 <= _float(self.avg_price) <= 1.0:
            raise ValueError("avg_price must be in [0, 1]")


def leg_pnl_if_outcome(leg, settlement_outcome):
    """Settlement P&L for a bought YES/NO-equivalent leg."""
    side = str(leg.side).upper()
    shares = _float(leg.shares)
    price = _float(leg.avg_price)
    if side in {"YES", "YES_BID"}:
        payout = 1.0 if str(leg.outcome) == str(settlement_outcome) else 0.0
        return shares * (payout - price)
    if side in {"NO", "NO_BID"}:
        payout = 0.0 if str(leg.outcome) == str(settlement_outcome) else 1.0
        return shares * (payout - price)
    # A covered YES ask is economically a NO bid at 1 - ask.
    payout = 0.0 if str(leg.outcome) == str(settlement_outcome) else 1.0
    no_price = 1.0 - price
    return shares * (payout - no_price)


def event_inventory_metrics(outcomes, probabilities, legs, negative_risk_conversion_state="not_verified"):
    outcomes = [str(outcome) for outcome in outcomes]
    probs = normalize_probabilities(probabilities, outcomes)
    pnl_by_outcome = {
        outcome: sum(leg_pnl_if_outcome(leg, outcome) for leg in (legs or []))
        for outcome in outcomes
    }
    expected_value = sum(probs[outcome] * pnl_by_outcome[outcome] for outcome in outcomes)
    variance = sum(
        probs[outcome] * ((pnl_by_outcome[outcome] - expected_value) ** 2)
        for outcome in outcomes
    )
    worst = min(pnl_by_outcome.values()) if pnl_by_outcome else 0.0
    best = max(pnl_by_outcome.values()) if pnl_by_outcome else 0.0
    return {
        "outcomes": outcomes,
        "probabilities": probs,
        "pnl_by_outcome": pnl_by_outcome,
        "expected_value": expected_value,
        "variance": variance,
        "stdev": math.sqrt(max(0.0, variance)),
        "worst_case_loss": max(0.0, -worst),
        "best_case_profit": best,
        "negative_risk_conversion_state": negative_risk_conversion_state,
    }


@dataclass(frozen=True)
class SizingConfig:
    rewards_min_size_or_target: float = 5.0
    per_band_cap_usdc: float = 10.0
    per_event_expected_loss_cap_usdc: float = 25.0
    per_event_worst_case_cap_usdc: float = 25.0
    per_correlated_regime_notional_cap_usdc: float = 0.0
    per_correlated_regime_joint_loss_cap_usdc: float = 0.0
    daily_drawdown_budget_usdc: float = 25.0
    fractional_kelly: float = 0.0
    available_backed_balance_usdc: float = 0.0
    open_order_reserves_usdc: float = 0.0
    live_edge_is_credible: bool = False
    correlated_regime_group_key: str = ""


@dataclass(frozen=True)
class SizingState:
    current_band_notional_usdc: float = 0.0
    current_event_expected_loss_usdc: float = 0.0
    current_event_worst_case_loss_usdc: float = 0.0
    current_correlated_regime_notional_usdc: float = 0.0
    current_correlated_regime_joint_loss_usdc: float = 0.0
    daily_loss_used_usdc: float = 0.0


def side_probability(side, fair_probability):
    side = str(side).upper()
    fair = _clamp(fair_probability)
    return 1.0 - fair if side in {"NO", "NO_BID", "YES_ASK"} else fair


def risk_per_share(side, price):
    side = str(side).upper()
    price = _clamp(price)
    if side == "YES_ASK":
        return max(0.0, 1.0 - price)
    return price


def full_kelly_fraction(side, fair_probability, price):
    p = side_probability(side, fair_probability)
    risk_price = risk_per_share(side, price)
    if risk_price <= 0 or risk_price >= 1:
        return 0.0
    edge = p - risk_price
    return max(0.0, edge / (1.0 - risk_price))


def sizing_decision(side, price, fair_probability, config=None, state=None):
    config = config or SizingConfig()
    state = state or SizingState()
    risk = risk_per_share(side, price)
    if risk <= 0:
        return {
            "size": 0.0,
            "final_size_limiter": "invalid_risk_price",
            "limiters": [],
            "kelly_fraction": 0.0,
            "available_after_reserves_usdc": 0.0,
        }
    available_after_reserves = max(
        0.0,
        _float(config.available_backed_balance_usdc) - _float(config.open_order_reserves_usdc),
    )
    event_expected_loss_remaining = max(
        0.0,
        _float(config.per_event_expected_loss_cap_usdc) - _float(state.current_event_expected_loss_usdc),
    )
    event_worst_case_remaining = max(
        0.0,
        _float(config.per_event_worst_case_cap_usdc) - _float(state.current_event_worst_case_loss_usdc),
    )
    correlated_notional_cap = _float(config.per_correlated_regime_notional_cap_usdc)
    correlated_joint_loss_cap = _float(config.per_correlated_regime_joint_loss_cap_usdc)
    correlated_notional_remaining = max(
        0.0,
        correlated_notional_cap - _float(state.current_correlated_regime_notional_usdc),
    )
    correlated_joint_loss_remaining = max(
        0.0,
        correlated_joint_loss_cap - _float(state.current_correlated_regime_joint_loss_usdc),
    )
    daily_drawdown_remaining = max(
        0.0,
        _float(config.daily_drawdown_budget_usdc) - _float(state.daily_loss_used_usdc),
    )
    band_remaining = max(
        0.0,
        _float(config.per_band_cap_usdc) - _float(state.current_band_notional_usdc),
    )
    expected_loss_per_share = max(0.0, risk - side_probability(side, fair_probability))
    kelly_fraction = full_kelly_fraction(side, fair_probability, price)
    if not config.live_edge_is_credible:
        kelly_fraction = 0.0
    kelly_risk_cap = (
        available_after_reserves
        * max(0.0, _float(config.fractional_kelly))
        * kelly_fraction
    )
    limiters = [
        ("rewards_min_size_or_target", _float(config.rewards_min_size_or_target)),
        ("per_band_cap", band_remaining / risk),
        (
            "per_event_expected_loss_cap",
            event_expected_loss_remaining / expected_loss_per_share
            if expected_loss_per_share > 0 else float("inf"),
        ),
        ("per_event_worst_case_cap", event_worst_case_remaining / risk),
        ("daily_drawdown_budget", daily_drawdown_remaining / risk),
        ("available_backed_balance_after_reserves", available_after_reserves / risk),
        ("fractional_kelly_cap", kelly_risk_cap / risk),
    ]
    if correlated_notional_cap > 0:
        limiters.append(("correlated_regime_notional_cap", correlated_notional_remaining / risk))
    if correlated_joint_loss_cap > 0:
        limiters.append(("correlated_regime_joint_loss_cap", correlated_joint_loss_remaining / risk))
    finite = [(name, max(0.0, value)) for name, value in limiters if math.isfinite(value)]
    if not finite:
        return {
            "size": 0.0,
            "final_size_limiter": "no_finite_limit",
            "limiters": limiters,
            "kelly_fraction": kelly_fraction,
            "available_after_reserves_usdc": available_after_reserves,
            "correlated_regime_group_key": config.correlated_regime_group_key,
        }
    limiter, size = min(finite, key=lambda item: item[1])
    return {
        "size": size,
        "risk_usdc": size * risk,
        "final_size_limiter": limiter,
        "limiters": [{"name": name, "size": value} for name, value in finite],
        "kelly_fraction": kelly_fraction,
        "available_after_reserves_usdc": available_after_reserves,
        "correlated_regime_group_key": config.correlated_regime_group_key,
    }


HALT_REASON_FIELDS = {
    "daily_loss_halt": "daily loss halt is active",
    "stale_source_halt": "source freshness is stale",
    "stale_book_halt": "CLOB book is stale",
    "stale_observation_trigger_halt": "observation-trigger watcher is stale",
    "heartbeat_halt": "required heartbeat is stale",
    "manual_pause": "manual pause is active",
    "cancel_all": "cancel-all is active",
}


def risk_halt_decision(**flags):
    reasons = [
        {"reason": name, "detail": detail}
        for name, detail in HALT_REASON_FIELDS.items()
        if bool(flags.get(name))
    ]
    return {
        "quote_permission": not reasons,
        "halted": bool(reasons),
        "reasons": reasons,
        "primary_reason": reasons[0]["reason"] if reasons else None,
    }


@dataclass(frozen=True)
class BalanceState:
    backed_balance_usdc: float
    open_order_reserves_usdc: float = 0.0
    pending_allowance_usdc: float = 0.0
    negative_risk_conversion_state: str = "not_verified"


def balance_available(state):
    return max(
        0.0,
        _float(state.backed_balance_usdc)
        - _float(state.open_order_reserves_usdc)
        - _float(state.pending_allowance_usdc),
    )


def reserve_order(state, additional_risk_usdc):
    additional = max(0.0, _float(additional_risk_usdc))
    available = balance_available(state)
    accepted = min(available, additional)
    return {
        "accepted": accepted >= additional,
        "reserved_usdc": accepted,
        "available_before_usdc": available,
        "available_after_usdc": max(0.0, available - accepted),
        "negative_risk_conversion_state": state.negative_risk_conversion_state,
    }


def _round_money(value):
    return round(_float(value), 10)


def _position_side(side):
    side = str(side).upper()
    if side in {"YES", "YES_BID"}:
        return "yes"
    if side in {"NO", "NO_BID", "YES_ASK"}:
        return "no"
    raise ValueError(f"unsupported order side: {side!r}")


def _position_price(side, price):
    side = str(side).upper()
    price = _clamp(price)
    return 1.0 - price if side == "YES_ASK" else price


def negative_risk_initial_state(backed_balance_usdc, outcomes, negative_risk_conversion_state="simulated_only"):
    outcomes = [str(outcome) for outcome in outcomes]
    return {
        "schema_version": NEGATIVE_RISK_SIMULATION_SCHEMA_VERSION,
        "starting_backed_balance_usdc": _round_money(backed_balance_usdc),
        "available_balance_usdc": _round_money(backed_balance_usdc),
        "open_order_reserves_usdc": 0.0,
        "pusd_collateral_spent_usdc": 0.0,
        "pusd_collateral_released_usdc": 0.0,
        "settlement_redemption_usdc": 0.0,
        "outcomes": outcomes,
        "yes_positions": {outcome: 0.0 for outcome in outcomes},
        "no_positions": {outcome: 0.0 for outcome in outcomes},
        "open_orders": {},
        "ledger": [],
        "negative_risk_conversion_state": negative_risk_conversion_state,
    }


def _append_ledger(state, event):
    state["ledger"].append(event)


def negative_risk_place_order(state, order_id, outcome, side, price, size):
    """Reserve pUSD/backed collateral for an order; reject if not fully backed."""
    out = deepcopy(state)
    outcome = str(outcome)
    side = str(side).upper()
    price = _clamp(price)
    size = max(0.0, _float(size))
    if outcome not in out["outcomes"]:
        raise ValueError(f"unknown outcome: {outcome!r}")
    if order_id in out["open_orders"]:
        raise ValueError(f"duplicate order_id: {order_id!r}")
    reserve = risk_per_share(side, price) * size
    if reserve > out["available_balance_usdc"] + 1e-12:
        _append_ledger(out, {
            "event": "order_rejected",
            "order_id": order_id,
            "outcome": outcome,
            "side": side,
            "price": price,
            "size": size,
            "required_reserve_usdc": _round_money(reserve),
            "available_balance_usdc": _round_money(out["available_balance_usdc"]),
            "reason": "insufficient_backed_balance",
        })
        return out
    out["available_balance_usdc"] = _round_money(out["available_balance_usdc"] - reserve)
    out["open_order_reserves_usdc"] = _round_money(out["open_order_reserves_usdc"] + reserve)
    out["open_orders"][order_id] = {
        "order_id": order_id,
        "outcome": outcome,
        "side": side,
        "price": price,
        "size": size,
        "remaining_size": size,
        "filled_size": 0.0,
        "reserved_usdc": _round_money(reserve),
    }
    _append_ledger(out, {
        "event": "order_placed",
        "order_id": order_id,
        "outcome": outcome,
        "side": side,
        "price": price,
        "size": size,
        "reserved_usdc": _round_money(reserve),
    })
    return out


def negative_risk_reduce_order(state, order_id, new_remaining_size):
    """Reduce an open order and release the no-longer-needed reserve."""
    out = deepcopy(state)
    order = out["open_orders"].get(order_id)
    if not order:
        raise ValueError(f"unknown open order: {order_id!r}")
    new_remaining = max(0.0, min(_float(new_remaining_size), _float(order["remaining_size"])))
    old_remaining = _float(order["remaining_size"])
    released_size = old_remaining - new_remaining
    release = released_size * risk_per_share(order["side"], order["price"])
    order["remaining_size"] = _round_money(new_remaining)
    order["reserved_usdc"] = _round_money(max(0.0, _float(order["reserved_usdc"]) - release))
    out["open_order_reserves_usdc"] = _round_money(max(0.0, out["open_order_reserves_usdc"] - release))
    out["available_balance_usdc"] = _round_money(out["available_balance_usdc"] + release)
    if new_remaining <= 1e-12:
        del out["open_orders"][order_id]
    _append_ledger(out, {
        "event": "order_reduced",
        "order_id": order_id,
        "released_size": _round_money(released_size),
        "released_reserve_usdc": _round_money(release),
        "remaining_size": _round_money(new_remaining),
    })
    return out


def negative_risk_apply_fill(state, order_id, fill_size, fill_price=None):
    """Apply a partial/full fill, moving reserved collateral into positions."""
    out = deepcopy(state)
    order = out["open_orders"].get(order_id)
    if not order:
        raise ValueError(f"unknown open order: {order_id!r}")
    fill_size = max(0.0, min(_float(fill_size), _float(order["remaining_size"])))
    price = _clamp(fill_price if fill_price is not None else order["price"])
    side = str(order["side"]).upper()
    risk_reserved_per_share = risk_per_share(side, order["price"])
    risk_filled_per_share = risk_per_share(side, price)
    reserved_release = fill_size * risk_reserved_per_share
    spent = fill_size * risk_filled_per_share
    reserve_delta = reserved_release - spent
    order["remaining_size"] = _round_money(_float(order["remaining_size"]) - fill_size)
    order["filled_size"] = _round_money(_float(order["filled_size"]) + fill_size)
    order["reserved_usdc"] = _round_money(max(0.0, _float(order["reserved_usdc"]) - reserved_release))
    out["open_order_reserves_usdc"] = _round_money(max(0.0, out["open_order_reserves_usdc"] - reserved_release))
    out["available_balance_usdc"] = _round_money(out["available_balance_usdc"] + max(0.0, reserve_delta))
    out["pusd_collateral_spent_usdc"] = _round_money(out["pusd_collateral_spent_usdc"] + spent)
    position_side = _position_side(side)
    position_price = _position_price(side, price)
    positions = out["yes_positions"] if position_side == "yes" else out["no_positions"]
    positions[order["outcome"]] = _round_money(positions.get(order["outcome"], 0.0) + fill_size)
    if order["remaining_size"] <= 1e-12:
        del out["open_orders"][order_id]
    _append_ledger(out, {
        "event": "fill",
        "order_id": order_id,
        "outcome": order["outcome"],
        "side": side,
        "position_side": position_side,
        "fill_size": _round_money(fill_size),
        "fill_price": price,
        "position_price": _round_money(position_price),
        "spent_usdc": _round_money(spent),
        "released_reserve_usdc": _round_money(max(0.0, reserve_delta)),
    })
    return out


def negative_risk_convert_complete_sets(state):
    """Convert complete YES sets across all mutually exclusive outcomes to pUSD."""
    out = deepcopy(state)
    outcomes = out.get("outcomes") or []
    if not outcomes:
        return out
    complete_sets = min(_float(out["yes_positions"].get(outcome)) for outcome in outcomes)
    if complete_sets <= 1e-12:
        _append_ledger(out, {
            "event": "conversion_skipped",
            "reason": "no_complete_yes_set",
            "negative_risk_conversion_state": out.get("negative_risk_conversion_state"),
        })
        return out
    for outcome in outcomes:
        out["yes_positions"][outcome] = _round_money(out["yes_positions"][outcome] - complete_sets)
    out["available_balance_usdc"] = _round_money(out["available_balance_usdc"] + complete_sets)
    out["pusd_collateral_released_usdc"] = _round_money(
        out["pusd_collateral_released_usdc"] + complete_sets
    )
    _append_ledger(out, {
        "event": "complete_yes_set_converted",
        "complete_sets": _round_money(complete_sets),
        "released_usdc": _round_money(complete_sets),
        "negative_risk_conversion_state": out.get("negative_risk_conversion_state"),
    })
    return out


def negative_risk_cancel_all(state):
    out = deepcopy(state)
    released = sum(_float(order.get("reserved_usdc")) for order in out["open_orders"].values())
    order_count = len(out["open_orders"])
    out["open_orders"] = {}
    out["open_order_reserves_usdc"] = 0.0
    out["available_balance_usdc"] = _round_money(out["available_balance_usdc"] + released)
    _append_ledger(out, {
        "event": "cancel_all",
        "order_count": order_count,
        "released_reserve_usdc": _round_money(released),
    })
    return out


def negative_risk_settle(state, settlement_outcome):
    """Cancel open orders, redeem remaining positions, and report final P&L."""
    out = negative_risk_cancel_all(state)
    settlement_outcome = str(settlement_outcome)
    if settlement_outcome not in out["outcomes"]:
        raise ValueError(f"unknown settlement outcome: {settlement_outcome!r}")
    yes_redemption = _float(out["yes_positions"].get(settlement_outcome))
    no_redemption = sum(
        _float(shares)
        for outcome, shares in out["no_positions"].items()
        if outcome != settlement_outcome
    )
    redemption = yes_redemption + no_redemption
    out["settlement_redemption_usdc"] = _round_money(redemption)
    out["available_balance_usdc"] = _round_money(out["available_balance_usdc"] + redemption)
    final_balance = _float(out["available_balance_usdc"])
    pnl = final_balance - _float(out["starting_backed_balance_usdc"])
    _append_ledger(out, {
        "event": "settled",
        "settlement_outcome": settlement_outcome,
        "yes_redemption_usdc": _round_money(yes_redemption),
        "no_redemption_usdc": _round_money(no_redemption),
        "settlement_redemption_usdc": _round_money(redemption),
        "final_balance_usdc": _round_money(final_balance),
        "realized_pnl_usdc": _round_money(pnl),
    })
    return out


def negative_risk_summary(state):
    return {
        "schema_version": state.get("schema_version"),
        "starting_backed_balance_usdc": state.get("starting_backed_balance_usdc"),
        "available_balance_usdc": state.get("available_balance_usdc"),
        "open_order_reserves_usdc": state.get("open_order_reserves_usdc"),
        "pusd_collateral_spent_usdc": state.get("pusd_collateral_spent_usdc"),
        "pusd_collateral_released_usdc": state.get("pusd_collateral_released_usdc"),
        "settlement_redemption_usdc": state.get("settlement_redemption_usdc"),
        "open_order_count": len(state.get("open_orders") or {}),
        "yes_positions": dict(state.get("yes_positions") or {}),
        "no_positions": dict(state.get("no_positions") or {}),
        "negative_risk_conversion_state": state.get("negative_risk_conversion_state"),
        "ledger_count": len(state.get("ledger") or []),
    }
