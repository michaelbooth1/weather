"""Pure FIFO campaign inventory and complete-pairs quote proposals (T113).

Inputs are money-proven own lots from the canonical fill projection. A proposal
is never order authority: the ordinary runtime screens and money gates apply.
"""
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR

from weather.market.lfc_accounting import quantity


CONTINUE = 'continue'
COMPLETE_PAIRS = 'complete_pairs'
MODES = (CONTINUE, COMPLETE_PAIRS)
DUST = Decimal('0.0001')
PAIR_MARGIN = Decimal('0.015')
SIZE = Decimal('20')
ZERO = Decimal(0)


def mode(raw):
    """An omitted historical field preserves continue semantics and bytes."""
    value = raw.get('post_fill_mode', CONTINUE)
    if not isinstance(value, str) or value not in MODES:
        raise ValueError('unsupported_post_fill_mode')
    return value


def instant(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('completion_timestamp')
    return result.astimezone(timezone.utc)


@dataclass(frozen=True)
class OwnLot:
    """One canonical, money-proven own trade/order allocation, at trade precision.

    Only campaign-owned, still-held shares enter inventory. The adapter owns
    lifecycle validation, provenance, attribution and evidenced removals.
    """
    trade_id: str
    order_id: str
    campaign_id: str
    condition_id: str
    leg: int
    shares: Decimal
    price: Decimal
    at_utc: datetime

    def __post_init__(self):
        if any(not isinstance(v, str) or not v.strip() for v in
               (self.trade_id, self.order_id, self.campaign_id, self.condition_id)):
            raise ValueError('completion_lot_identity')
        if type(self.leg) is not int or self.leg not in (0, 1):
            raise ValueError('completion_lot_leg')
        shares, price = quantity(self.shares), quantity(self.price)
        if shares <= 0 or not 0 < price < 1:
            raise ValueError('completion_lot_quantity_or_price')
        object.__setattr__(self, 'shares', shares)
        object.__setattr__(self, 'price', price)
        object.__setattr__(self, 'at_utc', instant(self.at_utc))

    @property
    def identity(self):
        return self.trade_id, self.order_id


@dataclass(frozen=True)
class PairSlice:
    yes_identity: tuple
    no_identity: tuple
    shares: Decimal
    yes_price: Decimal
    no_price: Decimal
    at_utc: datetime

    @property
    def margin_per_share(self):
        return 1 - self.yes_price - self.no_price

    @property
    def margin(self):
        return self.shares * self.margin_per_share

    def evidence(self):
        return {'yes_fill': list(self.yes_identity), 'no_fill': list(self.no_identity),
                'shares': str(self.shares), 'yes_price': str(self.yes_price),
                'no_price': str(self.no_price), 'margin_per_share': str(self.margin_per_share),
                'locked_margin': str(self.margin), 'at_utc': self.at_utc.isoformat()}


@dataclass(frozen=True)
class PairInventory:
    campaign_id: str
    condition_id: str
    yes_shares: Decimal
    no_shares: Decimal
    unpaired_cost: Decimal
    residuals: tuple  # (OwnLot, remaining shares), FIFO
    pairs: tuple
    flips: tuple  # own fill identities that strictly over-completed a non-dust U

    @property
    def u(self):
        return self.yes_shares - self.no_shares

    @property
    def completing(self):
        return abs(self.u) > DUST

    @property
    def average_cost(self):
        return self.unpaired_cost / abs(self.u) if self.u else None

    @property
    def completion_leg(self):
        return (1 if self.u > 0 else 0) if self.completing else None

    def evidence(self):
        return {'condition_id': self.condition_id, 'u': str(self.u),
                'yes_shares': str(self.yes_shares), 'no_shares': str(self.no_shares),
                'unpaired_shares': str(abs(self.u)), 'unpaired_cost': str(self.unpaired_cost),
                'unpaired_avg_cost': None if self.average_cost is None else str(self.average_cost),
                'completion_mode': self.completing, 'completion_leg': self.completion_leg,
                'paired_shares': str(sum((p.shares for p in self.pairs), ZERO)),
                'locked_pair_margin': str(sum((p.margin for p in self.pairs), ZERO)),
                'over_completions': len(self.flips)}


def inventory(lots, *, campaign_id, condition_id):
    """Match the oldest over-held own lot first, across all campaign sessions.

    Duplicate canonical identities must agree exactly. Public/owner-discretionary
    holdings never enter this function through a balance or position estimate.
    """
    unique = {}
    for lot in lots:
        if not isinstance(lot, OwnLot):
            raise ValueError('completion_canonical_lot_required')
        if lot.campaign_id != campaign_id or lot.condition_id != condition_id:
            continue
        old = unique.get(lot.identity)
        if old is not None and old != lot:
            raise ValueError('completion_conflicting_fill')
        unique[lot.identity] = lot
    queues, totals, pairs, flips = [deque(), deque()], [ZERO, ZERO], [], []
    # Stable ordering retains the canonical projection's ordering for trades
    # sharing the venue's timestamp precision.
    for lot in sorted(unique.values(), key=lambda r: r.at_utc):
        before = totals[0] - totals[1]
        totals[lot.leg] += lot.shares
        remaining, other = lot.shares, queues[1-lot.leg]
        while remaining and other:
            prior, available = other.popleft()
            matched = min(remaining, available)
            yes, no = (lot, prior) if lot.leg == 0 else (prior, lot)
            pairs.append(PairSlice(yes.identity, no.identity, matched, yes.price, no.price, lot.at_utc))
            remaining -= matched
            if available > matched:
                other.appendleft((prior, available-matched))
        if remaining:
            queues[lot.leg].append((lot, remaining))
        after = totals[0] - totals[1]
        if abs(before) > DUST and before * after < 0:
            flips.append(lot.identity)
    residuals = tuple(queues[0]) + tuple(queues[1])
    cost = sum((lot.price * shares for lot, shares in residuals), ZERO)
    return PairInventory(campaign_id, condition_id, *totals, cost, residuals, tuple(pairs), tuple(flips))


@dataclass(frozen=True)
class CompletionQuote:
    leg: int
    uncapped_price: Decimal
    pair_cap: Decimal
    price: Decimal
    refusal: str | None
    shares: Decimal = SIZE

    @property
    def allowed(self):
        return self.refusal is None

    def evidence(self):
        return {'completion_leg': self.leg, 'uncapped_completion_price': str(self.uncapped_price),
                'completion_pair_cap': str(self.pair_cap), 'capped_completion_price': str(self.price),
                'completion_size': str(self.shares), 'completion_refusal': self.refusal}


def quote(state, normal_prices, *, tick, leg_bounds, venue_bounds=None,
          min_order_size=0, reward_min_size=0):
    """Return the one complementary proposal, or None when the band is flat.

    A refusal preserves the proposed price for evidence and grants no order.
    The caller must still apply every ordinary screen, freshness and cap gate.
    """
    if not state.completing:
        return None
    if len(normal_prices) != 2:
        raise ValueError('completion_normal_pair_required')
    step = quantity(tick)
    low, high = map(quantity, leg_bounds)
    venue_low, venue_high = map(quantity, venue_bounds or (step, 1-step))
    if not 0 < step < 1 or not 0 < low <= high < 1 or not 0 < venue_low <= venue_high < 1:
        raise ValueError('completion_price_rules')
    normal = quantity(normal_prices[state.completion_leg])
    cap = 1 - state.average_cost - PAIR_MARGIN
    price = (min(normal, cap) / step).to_integral_value(rounding=ROUND_FLOOR) * step
    refusal = None
    if not low <= price <= high:
        refusal = 'completion_leg_price_bounds'
    elif not venue_low <= price <= venue_high:
        refusal = 'completion_venue_price_bounds'
    elif quantity(min_order_size) > SIZE:
        refusal = 'completion_venue_minimum'
    elif quantity(reward_min_size) > SIZE:
        refusal = 'completion_reward_minimum'
    return CompletionQuote(state.completion_leg, normal, cap, price, refusal)


def effective_legs(state, normal_legs, *, post_fill_mode):
    if post_fill_mode not in MODES:
        raise ValueError('unsupported_post_fill_mode')
    return (state.completion_leg,) if post_fill_mode == COMPLETE_PAIRS and state.completing else tuple(normal_legs)


def completion_seconds(events, *, until):
    """Integrate retained per-band UTC mode observations, including restarts.

    Events are (observed_at_utc, completing). Repeated states are harmless;
    out-of-order events refuse instead of fabricating elapsed time.
    """
    end, previous, began, total = instant(until), None, None, ZERO
    for at, active in events:
        at = instant(at)
        if type(active) is not bool or at > end or previous is not None and at < previous:
            raise ValueError('completion_interval')
        if active and began is None:
            began = at
        elif not active and began is not None:
            total += Decimal(str((at-began).total_seconds()))
            began = None
        previous = at
    if began is not None:
        total += Decimal(str((end-began).total_seconds()))
    return total
