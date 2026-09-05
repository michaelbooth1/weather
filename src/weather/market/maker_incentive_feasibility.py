"""Pure, explicit-input International liquidity-reward feasibility diagnostics.

This module neither loads evidence nor authorizes orders. Decimal inputs are in
whole asset units, shares, and probability prices; only reward distance uses
cents. See docs/operations/maker-incentive-feasibility.md for the input contract.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Context, Decimal, DivisionByZero, InvalidOperation, Overflow, ROUND_CEILING, ROUND_HALF_EVEN, localcontext
from functools import wraps
from typing import Sequence

from weather.market.market_config import date_from_event_slug, event_slug_for_date
from weather.market.market_registry import spec_for_slug


ZERO = Decimal("0")
ONE = Decimal("1")
CONDITION_RE = re.compile(r"0x[0-9a-f]{64}")
ASSET_RE = re.compile(r"eip155:[1-9][0-9]*/erc20:0x[0-9a-f]{40}")
HASH_RE = re.compile(r"[0-9a-f]{64}")


class FeasibilityInputError(ValueError):
    """Malformed, stale, or inconsistently bound supplied evidence."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Evidence:
    sha256: str
    captured_at: datetime


@dataclass(frozen=True)
class MarketTerms:
    # Unit provenance is mandatory even for the exchange_economics field names.
    platform: str
    event_slug: str
    condition_id: str
    yes_token_id: str
    no_token_id: str
    collateral_asset: str
    order_min_size: Decimal
    order_price_min_tick_size: Decimal
    rewards_min_size: Decimal
    rewards_max_spread_cents: Decimal
    evidence: Evidence
    accepting_orders: bool
    order_min_size_unit: str  # shares or collateral; never inferred from name.
    order_min_size_reference: str


@dataclass(frozen=True)
class Book:
    event_slug: str
    condition_id: str
    token_id: str
    best_bid: Decimal
    best_ask: Decimal
    evidence: Evidence


@dataclass(frozen=True)
class AdjustedMidpoint:
    yes_price: Decimal
    kind: str  # Must be size_cutoff_adjusted; never ordinary midpoint.
    method_reference: str
    cutoff_shares: Decimal
    yes_book_sha256: str
    no_book_sha256: str
    evidence: Evidence


@dataclass(frozen=True)
class ScoringRules:
    multiplier: Decimal
    single_side_divisor: Decimal
    single_side_midpoint_low: Decimal
    single_side_midpoint_high: Decimal
    evidence: Evidence


@dataclass(frozen=True)
class Campaign:
    campaign_id: str
    condition_id: str
    reward_asset: str
    starts_at: datetime
    ends_at: datetime
    # Caller supplies an evidenced half-open interval, not unqualified API dates.
    interval_reference: str
    rate_per_day: Decimal
    evidence: Evidence


@dataclass(frozen=True)
class BuyQuote:
    outcome: str  # YES or NO; at most one proposed BUY per outcome.
    token_id: str
    price: Decimal
    shares: Decimal


@dataclass(frozen=True)
class Capital:
    collateral_asset: str
    backed_capital: Decimal  # Free collateral + reserves + funded inventory cost.
    inventory_cost: Decimal
    open_order_reserves: Decimal
    available_collateral: Decimal
    condition_committed: Decimal
    event_committed: Decimal
    cleanup_reserve: Decimal
    order_cap: Decimal
    condition_cap: Decimal
    event_cap: Decimal
    wallet_cap: Decimal


@dataclass(frozen=True)
class CompetitionScenario:
    label: str
    # Sum of OTHER makers' Q_min, after their per-maker nonlinear aggregation.
    other_makers_q_min: Decimal
    other_makers_q_max: Decimal
    participating_sample_fraction: Decimal
    yes_remaining_size_fraction: Decimal
    no_remaining_size_fraction: Decimal


@dataclass(frozen=True)
class EpochPayoutModel:
    """Declared scenario assumptions, never inferred from a daily reward rate."""

    label: str
    campaign_id: str
    condition_id: str
    reward_asset: str
    epoch_start: datetime
    epoch_end: datetime
    reward_pool: Decimal
    nonempty_epoch_samples: int
    plan_samples: int
    minimum_payout_amount: Decimal
    evidence: Evidence


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise FeasibilityInputError(code)


def _number(value: Decimal, name: str, *, positive: bool = False) -> Decimal:
    _require(isinstance(value, Decimal) and value.is_finite(), f"{name}:decimal_required")
    _require(value > ZERO if positive else value >= ZERO, f"{name}:out_of_range")
    _require(-18 <= value.as_tuple().exponent <= 18 and value <= Decimal("1e18"), f"{name}:precision_or_magnitude_unsupported")
    return value


def _fraction(value: Decimal, name: str) -> Decimal:
    _number(value, name)
    _require(value <= ONE, f"{name}:out_of_range")
    return value


def _text(value: str, name: str) -> None:
    _require(isinstance(value, str) and bool(value.strip()), f"{name}:missing")


def _time(value: datetime, name: str) -> None:
    _require(
        isinstance(value, datetime) and value.utcoffset() is not None,
        f"{name}:timezone_required",
    )


def _evidence(value: Evidence, name: str, as_of: datetime, max_age: timedelta) -> None:
    _require(isinstance(value, Evidence), f"{name}:evidence_missing")
    _require(isinstance(value.sha256, str) and bool(HASH_RE.fullmatch(value.sha256)), f"{name}:hash_invalid")
    _time(value.captured_at, name)
    _require(timedelta(0) <= as_of - value.captured_at.astimezone(timezone.utc) <= max_age, f"{name}:stale_or_future")


def _asset(value: str, name: str) -> None:
    _require(isinstance(value, str) and bool(ASSET_RE.fullmatch(value)), f"{name}:asset_invalid")
    _require(not value.endswith("0x" + "0" * 40), f"{name}:asset_invalid")


def _q_min(yes_score: Decimal, no_score: Decimal, midpoint: Decimal, rules: ScoringRules) -> Decimal:
    both = min(yes_score, no_score)
    if rules.single_side_midpoint_low <= midpoint <= rules.single_side_midpoint_high:
        return max(both, max(yes_score, no_score) / rules.single_side_divisor)
    return both


def _submission_minimum_shares(quote: BuyQuote, market: MarketTerms) -> Decimal:
    if market.order_min_size_unit == "shares":
        return market.order_min_size
    return (market.order_min_size / quote.price).quantize(Decimal("1e-18"), rounding=ROUND_CEILING)


def _order_score(quote: BuyQuote, size: Decimal, midpoint: Decimal, market: MarketTerms, rules: ScoringRules) -> Decimal:
    # A valid submitted order can keep resting after a partial fill takes its
    # remainder below the submission minimum; only the reward cutoff applies.
    if size < market.rewards_min_size:
        return ZERO
    distance = abs(quote.price - (midpoint if quote.outcome == "YES" else ONE - midpoint))
    maximum = market.rewards_max_spread_cents / Decimal("100")
    if distance >= maximum:
        return ZERO
    return size * ((maximum - distance) / maximum) ** 2 * rules.multiplier


def _fixed_decimal_context(function):
    @wraps(function)
    def calculate(*args, **kwargs):
        context = Context(prec=80, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999, traps=[InvalidOperation, DivisionByZero, Overflow])
        with localcontext(context):
            return function(*args, **kwargs)
    return calculate


@_fixed_decimal_context
def assess_buy_plan(
    *,
    market: MarketTerms,
    yes_book: Book,
    no_book: Book,
    midpoint: AdjustedMidpoint | None,
    rules: ScoringRules,
    campaigns: Sequence[Campaign],
    quotes: Sequence[BuyQuote],
    capital: Capital,
    scenarios: Sequence[CompetitionScenario],
    as_of: datetime,
    horizon_end: datetime,
    max_input_age: timedelta,
    max_book_age: timedelta,
    max_book_skew: timedelta,
    other_own_orders_absent: bool,
    payout_model: EpochPayoutModel | None = None,
) -> dict:
    """Assess one YES BUY, NO BUY, or simultaneous two-BUY plan without I/O.

    Invalid evidence raises a coded error. Valid but infeasible plans return
    separate order, capital and reward blockers. All reward estimates are
    conditional scenarios with an explicit zero-payment possibility.
    """

    _time(as_of, "as_of")
    _time(horizon_end, "horizon_end")
    as_of = as_of.astimezone(timezone.utc)
    horizon_end = horizon_end.astimezone(timezone.utc)
    _require(horizon_end > as_of, "horizon:invalid")
    for value, name in ((max_input_age, "max_input_age"), (max_book_age, "max_book_age"), (max_book_skew, "max_book_skew")):
        _require(isinstance(value, timedelta) and value >= timedelta(0), f"{name}:invalid")
    _require(max_book_age <= max_input_age, "max_book_age:exceeds_input_age")
    _require(market.platform == "polymarket_global", "platform:not_international")
    _require(type(market.accepting_orders) is bool, "accepting_orders:boolean_required")
    _require(market.order_min_size_unit in {"shares", "collateral"}, "order_min_size:unit_unproved")
    _text(market.order_min_size_reference, "order_min_size_reference")
    _require(other_own_orders_absent is True, "plan:other_own_orders_not_excluded")
    _text(market.event_slug, "event_slug")
    spec = spec_for_slug(market.event_slug)
    event_date = date_from_event_slug(market.event_slug)
    _require(spec is not None and event_date is not None, "event_slug:unrecognized")
    _require(market.event_slug == event_slug_for_date(event_date, spec.id), "event_slug:noncanonical")
    _require(isinstance(market.condition_id, str) and bool(CONDITION_RE.fullmatch(market.condition_id)), "condition_id:invalid")
    tokens = {"YES": market.yes_token_id, "NO": market.no_token_id}
    for token in tokens.values():
        _require(isinstance(token, str) and bool(re.fullmatch(r"[1-9][0-9]*", token)), "token_id:invalid")
    _require(market.yes_token_id != market.no_token_id, "token_id:duplicate")
    _asset(market.collateral_asset, "market_collateral")
    _evidence(market.evidence, "economics", as_of, max_input_age)
    for name in ("order_min_size", "order_price_min_tick_size", "rewards_min_size", "rewards_max_spread_cents"):
        _number(getattr(market, name), name, positive=True)
    _require(market.order_price_min_tick_size < ONE, "tick:out_of_range")
    _require(market.rewards_max_spread_cents <= Decimal("100"), "reward_spread:out_of_range")

    books = {"YES": yes_book, "NO": no_book}
    for outcome, book in books.items():
        _require((book.event_slug, book.condition_id, book.token_id) == (market.event_slug, market.condition_id, tokens[outcome]), f"{outcome}:book_identity_mismatch")
        _evidence(book.evidence, f"{outcome}_book", as_of, max_book_age)
        _fraction(book.best_bid, f"{outcome}_best_bid")
        _fraction(book.best_ask, f"{outcome}_best_ask")
        _require(book.best_bid < book.best_ask, f"{outcome}:locked_or_crossed_book")
    _require(abs(yes_book.evidence.captured_at.astimezone(timezone.utc) - no_book.evidence.captured_at.astimezone(timezone.utc)) <= max_book_skew, "books:timestamp_skew")
    _require(yes_book.best_bid + no_book.best_bid < ONE, "books:complementary_bids_cross")
    _evidence(rules.evidence, "scoring_rules", as_of, max_input_age)
    _number(rules.multiplier, "multiplier", positive=True)
    _number(rules.single_side_divisor, "single_side_divisor", positive=True)
    _require(rules.single_side_divisor >= ONE, "single_side_divisor:out_of_range")
    _fraction(rules.single_side_midpoint_low, "midpoint_low")
    _fraction(rules.single_side_midpoint_high, "midpoint_high")
    _require(rules.single_side_midpoint_low <= rules.single_side_midpoint_high, "midpoint_range:invalid")
    if midpoint is not None:
        _require(midpoint.kind == "size_cutoff_adjusted", "midpoint:adjustment_unproved")
        _text(midpoint.method_reference, "midpoint_method")
        _fraction(midpoint.yes_price, "adjusted_midpoint")
        _number(midpoint.cutoff_shares, "midpoint_cutoff", positive=True)
        _require(midpoint.cutoff_shares == market.rewards_min_size, "midpoint:cutoff_mismatch")
        _require((midpoint.yes_book_sha256, midpoint.no_book_sha256) == (yes_book.evidence.sha256, no_book.evidence.sha256), "midpoint:book_hash_mismatch")
        _evidence(midpoint.evidence, "midpoint", as_of, max_book_age)
        _require(midpoint.evidence.captured_at.astimezone(timezone.utc) >= max(book.evidence.captured_at.astimezone(timezone.utc) for book in books.values()), "midpoint:precedes_books")

    _require(len(campaigns) <= 1, "campaign:ambiguous_multiple_allocations")
    campaign = campaigns[0] if campaigns else None
    reward_blockers = []
    if campaign is None:
        reward_blockers.append("campaign:absent")
    else:
        _text(campaign.campaign_id, "campaign_id")
        _require(campaign.condition_id == market.condition_id, "campaign:condition_mismatch")
        _asset(campaign.reward_asset, "reward")
        _evidence(campaign.evidence, "campaign", as_of, max_input_age)
        _time(campaign.starts_at, "campaign_start")
        _time(campaign.ends_at, "campaign_end")
        campaign_start = campaign.starts_at.astimezone(timezone.utc)
        campaign_end = campaign.ends_at.astimezone(timezone.utc)
        _require(campaign_start < campaign_end, "campaign:interval_invalid")
        _text(campaign.interval_reference, "campaign_interval_reference")
        _number(campaign.rate_per_day, "campaign_rate")
        if campaign.rate_per_day == ZERO:
            reward_blockers.append("campaign:no_positive_allocation")
        if max(as_of, campaign_start) >= min(horizon_end, campaign_end):
            reward_blockers.append("campaign:no_horizon_overlap")

    _require(1 <= len(quotes) <= 2, "quotes:one_or_two_required")
    _require(len({quote.outcome for quote in quotes}) == len(quotes), "quotes:duplicate_outcome")
    order_blockers = [] if market.accepting_orders else ["market:not_accepting_orders"]
    invalid_order_outcomes = set() if market.accepting_orders else set(tokens)
    quote_scores = {"YES": ZERO, "NO": ZERO}
    minimum_shares = {}
    notionals = []
    for quote in quotes:
        _require(quote.outcome in tokens and quote.token_id == tokens[quote.outcome], "quote:token_identity_mismatch")
        _fraction(quote.price, "quote_price")
        _require(ZERO < quote.price < ONE, "quote_price:out_of_range")
        _number(quote.shares, "quote_shares", positive=True)
        prefix = quote.outcome
        minimum_shares[prefix] = max(market.rewards_min_size, _submission_minimum_shares(quote, market))
        blocker_count = len(order_blockers)
        if quote.price % market.order_price_min_tick_size != ZERO:
            order_blockers.append(f"{prefix}:off_tick")
        if quote.price >= books[prefix].best_ask:
            order_blockers.append(f"{prefix}:marketable_buy")
        complement = "NO" if prefix == "YES" else "YES"
        if quote.price + books[complement].best_bid >= ONE:
            order_blockers.append(f"{prefix}:complementary_marketable_buy")
        submission_quantity = quote.shares if market.order_min_size_unit == "shares" else quote.price * quote.shares
        if submission_quantity < market.order_min_size:
            order_blockers.append(f"{prefix}:below_exchange_minimum")
        if len(order_blockers) > blocker_count:
            invalid_order_outcomes.add(prefix)
        if quote.shares < market.rewards_min_size:
            reward_blockers.append(f"{prefix}:below_reward_minimum")
        if midpoint is not None and prefix not in invalid_order_outcomes:
            quote_scores[prefix] = _order_score(quote, quote.shares, midpoint.yes_price, market, rules)
            if quote_scores[prefix] == ZERO:
                reward_blockers.append(f"{prefix}:zero_reward_score")
        notionals.append(quote.price * quote.shares)
    if len(quotes) == 2 and sum(quote.price for quote in quotes) >= ONE:
        order_blockers.append("quotes:complementary_buys_cross")
    if midpoint is None:
        reward_blockers.append("midpoint:missing")
    own_q = None if midpoint is None else _q_min(quote_scores["YES"], quote_scores["NO"], midpoint.yes_price, rules)
    if own_q == ZERO:
        reward_blockers.append("plan:zero_two_side_score")

    _asset(capital.collateral_asset, "capital_collateral")
    _require(capital.collateral_asset == market.collateral_asset, "capital:asset_mismatch")
    for name in ("backed_capital", "inventory_cost", "open_order_reserves", "available_collateral", "condition_committed", "event_committed", "cleanup_reserve", "order_cap", "condition_cap", "event_cap", "wallet_cap"):
        _number(getattr(capital, name), name)
    tied = capital.inventory_cost + capital.open_order_reserves
    _require(tied <= capital.backed_capital, "capital:unbacked_existing_commitments")
    _require(capital.available_collateral <= capital.backed_capital - tied, "capital:available_exceeds_backing")
    _require(capital.condition_committed <= capital.event_committed <= tied, "capital:inconsistent_scope_commitments")
    reservation = sum(notionals, ZERO)
    capital_blockers = []
    if any(notional > capital.order_cap for notional in notionals):
        capital_blockers.append("capital:order_cap")
    if reservation + capital.cleanup_reserve > capital.available_collateral:
        capital_blockers.append("capital:available_collateral")
    if capital.condition_committed + reservation + capital.cleanup_reserve > capital.condition_cap:
        capital_blockers.append("capital:condition_cap")
    if capital.event_committed + reservation + capital.cleanup_reserve > capital.event_cap:
        capital_blockers.append("capital:event_cap")
    if capital.backed_capital > capital.wallet_cap:
        capital_blockers.append("capital:wallet_cap")

    if payout_model is not None:
        _require(campaign is not None, "payout:campaign_missing")
        _text(payout_model.label, "payout_model_label")
        _require((payout_model.campaign_id, payout_model.condition_id, payout_model.reward_asset) == (campaign.campaign_id, campaign.condition_id, campaign.reward_asset), "payout:campaign_identity_mismatch")
        _evidence(payout_model.evidence, "payout_model", as_of, max_input_age)
        _time(payout_model.epoch_start, "epoch_start")
        _time(payout_model.epoch_end, "epoch_end")
        _require(campaign_start <= payout_model.epoch_start.astimezone(timezone.utc) <= as_of < horizon_end <= payout_model.epoch_end.astimezone(timezone.utc) <= campaign_end, "payout:interval_binding_invalid")
        _number(payout_model.reward_pool, "epoch_reward_pool", positive=True)
        _number(payout_model.minimum_payout_amount, "minimum_payout_amount")
        _require(type(payout_model.nonempty_epoch_samples) is int and type(payout_model.plan_samples) is int and 0 < payout_model.plan_samples <= payout_model.nonempty_epoch_samples <= 10**9, "payout:sample_counts_invalid")

    _require(bool(scenarios), "scenarios:missing")
    _require(len({scenario.label for scenario in scenarios}) == len(scenarios), "scenarios:duplicate_label")
    estimates = []
    feasible = not (order_blockers or capital_blockers or reward_blockers)
    for scenario in scenarios:
        _text(scenario.label, "scenario_label")
        _number(scenario.other_makers_q_min, "other_makers_q_min")
        _number(scenario.other_makers_q_max, "other_makers_q_max")
        _require(scenario.other_makers_q_min <= scenario.other_makers_q_max, "scenario:competitor_range_invalid")
        for name in ("participating_sample_fraction", "yes_remaining_size_fraction", "no_remaining_size_fraction"):
            _fraction(getattr(scenario, name), name)
        scenario_q = None
        share_low = share_high = None
        if midpoint is not None:
            scores = {"YES": ZERO, "NO": ZERO}
            for quote in quotes:
                if quote.outcome in invalid_order_outcomes:
                    continue
                remaining = scenario.yes_remaining_size_fraction if quote.outcome == "YES" else scenario.no_remaining_size_fraction
                scores[quote.outcome] = _order_score(quote, quote.shares * remaining, midpoint.yes_price, market, rules)
            scenario_q = _q_min(scores["YES"], scores["NO"], midpoint.yes_price, rules)
            share_low = scenario_q / (scenario_q + scenario.other_makers_q_max) if scenario_q else ZERO
            share_high = scenario_q / (scenario_q + scenario.other_makers_q_min) if scenario_q else ZERO
        estimated_low = estimated_high = None
        if payout_model is not None and feasible:
            weight = Decimal(payout_model.plan_samples) / Decimal(payout_model.nonempty_epoch_samples)
            pool_weight = payout_model.reward_pool * weight * scenario.participating_sample_fraction
            estimated_low, estimated_high = pool_weight * share_low, pool_weight * share_high
        estimates.append({
            "label": scenario.label,
            "other_makers_q_range": (scenario.other_makers_q_min, scenario.other_makers_q_max),
            "remaining_order_q": scenario_q,
            "conditional_sample_share_range": (share_low, share_high),
            "participating_sample_fraction": scenario.participating_sample_fraction,
            "conditional_reward_amount_range": (estimated_low, estimated_high),
            "declared_payout_minimum_met_range": None if estimated_low is None else (estimated_low >= payout_model.minimum_payout_amount, estimated_high >= payout_model.minimum_payout_amount),
        })
    return {
        "mode": "explicit_input_diagnostic",
        "event_slug": market.event_slug,
        "location_id": spec.id,
        "event_date": event_date,
        "settlement_unit": spec.unit,
        "condition_id": market.condition_id,
        "token_ids": tokens,
        "collateral_asset": market.collateral_asset,
        "reward_asset": campaign.reward_asset if campaign else None,
        "campaign_id": campaign.campaign_id if campaign else None,
        "campaign": campaign,
        "as_of": as_of,
        "horizon_end": horizon_end,
        "evidence": {
            "economics": market.evidence,
            "yes_book": yes_book.evidence,
            "no_book": no_book.evidence,
            "midpoint": midpoint.evidence if midpoint else None,
            "rules": rules.evidence,
            "campaign": campaign.evidence if campaign else None,
            "payout_model": payout_model.evidence if payout_model else None,
        },
        "minimum_qualifying_shares_by_outcome": minimum_shares,
        "order_min_size_unit": market.order_min_size_unit,
        "order_min_size_reference": market.order_min_size_reference,
        "order_notionals": tuple(notionals),
        "simultaneous_reservation": reservation,
        "required_available_with_cleanup": reservation + capital.cleanup_reserve,
        "total_committed_with_plan_and_cleanup": tied + reservation + capital.cleanup_reserve,
        "side_scores": quote_scores if midpoint else None,
        "own_q_min": own_q,
        "order_feasible": not order_blockers,
        "capital_feasible": not capital_blockers,
        "reward_eligible": not reward_blockers and not order_blockers,
        "incentive_feasible": feasible,
        "blockers": {"orders": tuple(order_blockers), "capital": tuple(capital_blockers), "rewards": tuple(reward_blockers)},
        "payout_model_label": payout_model.label if payout_model else None,
        "payout_model": payout_model,
        "payment_estimation_status": "conditional_model_only" if payout_model and feasible else "unresolved_or_infeasible",
        "scenarios": tuple(estimates),
        "no_payment_amount": ZERO,
        "paid_rewards": None,
        "realized_pnl": None,
        "live_order_authority": False,
        "other_own_orders_absent_assumption": True,
    }
