"""Validated, explicit-path inputs for offline T1 replay; no account or network IO."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from functools import wraps
import hashlib
import json

D = Decimal
ZERO = D(0)
ONE = D(1)


def decimal_context(function):
    """Keep replay arithmetic independent of the caller's thread-local context."""
    @wraps(function)
    def bound(*args, **kwargs):
        with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
            return function(*args, **kwargs)
    return bound


def number(value, *, minimum=ZERO, maximum=None):
    result = D(str(value))
    if (not result.is_finite() or minimum is not None and result < minimum
            or maximum is not None and result > maximum):
        raise ValueError("invalid numeric input")
    return result


def utc(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset().total_seconds() != 0:
        raise ValueError("UTC timestamp required")
    return result.astimezone(timezone.utc)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str) + "\n").encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def source_hash(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('source sha256 required')
    return value


def lineage_hashes(value):
    """All retained source/projection lineage hashes, including condition-day pools."""
    out = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key.endswith('source_sha256'):
                out.add(source_hash(child))
            else:
                out.update(lineage_hashes(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            out.update(lineage_hashes(child))
    return out


@dataclass(frozen=True)
class ReplayConfig:
    """All economic assumptions are required inputs, with no qualifying defaults."""

    informed_fraction: str  # Deprecated wire name: incremental cost reserve / filled purchase cost, NOT informed flow.
    latency_seconds: str
    order_latency_seconds: str
    latency_source_sha256: str
    measured_p95_seconds: str
    measured_order_p95_seconds: str
    per_market_cap: str
    total_cap: str
    queue_rule: str
    competition_rule: str
    reward_epoch_rule: str
    max_book_age_seconds: str
    markout_seconds: int
    mark_max_delay_seconds: str
    fee_coefficient: str
    rebate_fraction: str
    cancel_latency_seconds: str = '0'
    measured_cancel_p95_seconds: str = '0'
    midpoint_rule: str = 'level_filter'
    fee_rounding_rule: str = 'unrounded_diagnostic'

    def __post_init__(self):
        for name in ("informed_fraction", "rebate_fraction"):
            number(getattr(self, name), maximum=ONE)
        for name in ("latency_seconds", "order_latency_seconds", "measured_p95_seconds",
                     "measured_order_p95_seconds", "per_market_cap", "total_cap",
                     "max_book_age_seconds", "mark_max_delay_seconds", "fee_coefficient"):
            number(getattr(self, name))
        if (number(self.latency_seconds) < number(self.measured_p95_seconds)
                or number(self.order_latency_seconds) < number(self.measured_order_p95_seconds)
                or number(self.latency_seconds) < number(self.order_latency_seconds)):
            raise ValueError("latency is below measured bound or transport latency")
        if (number(self.per_market_cap) > number(self.total_cap)
                or number(self.max_book_age_seconds) <= 0 or number(self.total_cap) <= 0
                or type(self.markout_seconds) is not int or self.markout_seconds <= 0):
            raise ValueError("invalid replay limits")
        if self.queue_rule not in ("back_strict_through", "back_at_price"):
            raise ValueError("unsupported queue rule")
        if self.competition_rule not in ("maker_grouped", "aggregate_upper_bound"):
            raise ValueError("unsupported competition rule")
        if self.reward_epoch_rule not in ('captured_active', 'full_day_upper_bound'):
            raise ValueError('unsupported reward epoch rule')
        if number(self.fee_coefficient) != D('.05') or number(self.rebate_fraction) != D('.25'):
            raise ValueError('T1 weather economics differ from the charter')
        source_hash(self.latency_source_sha256)
        number(self.cancel_latency_seconds)
        if number(self.cancel_latency_seconds) < number(self.measured_cancel_p95_seconds):
            raise ValueError('cancel latency is below its own measured transport bound')
        if self.midpoint_rule not in ('level_filter', 'cumulative_depth'):
            raise ValueError('unsupported midpoint semantics')
        if self.fee_rounding_rule not in ('unrounded_diagnostic', 'per_match_5dp_half_even'):
            raise ValueError('unsupported fee precision rule')

    def projection(self):
        return asdict(self)


def levels(rows):
    out = []
    for row in rows:
        p, size = number(row["price"], maximum=ONE), number(row["size"])
        if not ZERO < p < ONE or size <= ZERO:
            raise ValueError("invalid book level")
        out.append({**row, "price": p, "size": size})
    return out


def book_valid(book, *, now, max_age):
    available, observed = utc(book['at']), utc(book['observed_at'])
    if observed > available or available > now or not ZERO <= D(str((now - observed).total_seconds())) <= max_age:
        raise ValueError("stale or future book")
    for outcome in ("YES", "NO"):
        number(book[outcome]['tick'], minimum=D('.000001'), maximum=ONE)
        number(book[outcome]['min_order_size'], minimum=D('.000001'))
        bids, asks = levels(book[outcome]["bids"]), levels(book[outcome]["asks"])
        if ((not bids or not asks) and not book.get('competitor_only')
                or bids and asks and max(r["price"] for r in bids) >= min(r["price"] for r in asks)):
            raise ValueError("incomplete or crossed book")


@decimal_context
def fee(size, price, coefficient, rounding_rule='unrounded_diagnostic'):
    """Weather taker fee; maker fee is identically zero (charter section 2)."""
    p = number(price, maximum=ONE)
    value = number(size) * number(coefficient) * p * (ONE - p)
    return value.quantize(D('.00001')) if rounding_rule == 'per_match_5dp_half_even' else value
